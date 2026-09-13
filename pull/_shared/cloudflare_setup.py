import getpass
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import socket
import ssl
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler

sys.path.insert(0, str(Path(__file__).resolve().parent))
import environment as env

sys.path.insert(0, str(env.ROOT.parent / '_shared'))
from session import request as session_request


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Cloudflare:
    def __init__(self, zone, token, owner):
        if not re.fullmatch(r'[a-fA-F0-9]{32}', zone):
            raise ValueError('Zone ID must contain 32 hexadecimal characters (not the Account ID)')
        if not re.fullmatch(r'[A-Za-z0-9_.-]{20,256}', token):
            raise ValueError('Enter a Cloudflare API token, without spaces or line breaks')
        self.zone, self.token, self.owner = zone, token, owner
        self.base = '/zones/' + zone

    def request(self, method, path, data=None):
        request = Request('https://api.cloudflare.com/client/v4' + path, method=method,
                          headers={'Authorization': 'Bearer ' + self.token, 'Content-Type': 'application/json'},
                          data=None if data is None else json.dumps(data).encode())
        try:
            with build_opener(NoRedirect()).open(request, timeout=30) as response:
                payload = json.load(response)
        except HTTPError as error:
            if error.code == 401:
                raise ValueError('Cloudflare authentication failed (HTTP 401): the token is invalid, expired, revoked, or the wrong token type') from None
            if error.code == 403:
                raise ValueError('Cloudflare denied access (HTTP 403): check token permissions and zone access') from None
            if error.code == 429:
                raise ValueError('Cloudflare rate limit reached (HTTP 429): wait and retry') from None
            raise ValueError(f'Cloudflare HTTP {error.code}: no further changes made') from None
        except (URLError, TimeoutError, OSError, ValueError):
            raise ValueError('Cloudflare request failed; check connectivity and retry. A timed-out write may have succeeded; the next run rechecks DNS.') from None
        if not payload.get('success'):
            codes = ', '.join(str(item.get('code', 'unknown')) for item in payload.get('errors', []))
            raise ValueError('Cloudflare rejected the request (error codes: ' + codes + ')')
        return payload

    def verify(self):
        if self.request('GET', '/user/tokens/verify')['result'].get('status') != 'active':
            raise ValueError('Cloudflare token is not active')
        zone = self.request('GET', self.base)['result']
        if zone.get('name') != 'orionintelligence.org' or zone.get('status') != 'active' or zone.get('paused'):
            raise ValueError('Select the active, unpaused orionintelligence.org zone')

    def records(self, name):
        result = []
        for page in range(1, 101):
            payload = self.request('GET', self.base + '/dns_records?' + urlencode({'name': name, 'per_page': 100, 'page': page}))
            result.extend(payload['result'])
            if page >= payload.get('result_info', {}).get('total_pages', 1):
                return result
        raise ValueError('Unexpected DNS pagination; inspect the zone manually')

    def plan(self, desired):
        plan = []
        for record in desired:
            name = record['name']
            if not name.endswith('.orionintelligence.org'):
                raise ValueError('Refusing to manage DNS outside deployment subdomains')
            existing = self.records(name)
            if any(item['type'] == 'CNAME' for item in existing):
                raise ValueError(f'{name}: existing CNAME conflicts; resolve it manually')
            if record['type'] in {'A', 'AAAA'} and any(item['type'] in {'A', 'AAAA'} and item['type'] != record['type'] for item in existing):
                raise ValueError(f'{name}: an existing address of the other IP family requires manual review')
            matching = [item for item in existing if item['type'] == record['type']]
            if record['type'] == 'TXT':
                prefix = record['content'].split(';')[0].split()[0]
                matching = [item for item in matching if item['content'].strip('"').startswith(prefix)]
            if len(matching) > 1:
                raise ValueError(f'{name}: multiple relevant records; reconcile manually')
            previous = matching[0] if matching else None
            def equivalent(key, value):
                before = previous.get(key) if previous else None
                if key == 'content' and record['type'] == 'TXT':
                    def text_value(text):
                        text = str(text)
                        return ''.join(re.findall(r'"([^"\\]*(?:\\.[^"\\]*)*)"', text)) if re.fullmatch(r'(?:"(?:[^"\\]|\\.)*"\s*)+', text) else text
                    return text_value(before) == text_value(value)
                if key == 'content' and record['type'] == 'MX':
                    return str(before).lower().rstrip('.') == value.lower().rstrip('.')
                return before == value
            if previous and all(equivalent(key, value) for key, value in record.items() if key != 'ttl'):
                continue
            if previous and previous.get('comment') != self.owner:
                raise ValueError(f'{name}: conflicting record is not owned by this deployment; refusing to overwrite it')
            plan.append((previous, dict(record, comment=self.owner)))
        return plan

    def reconcile(self, desired):
        plan = self.plan(desired)
        if not plan:
            print('Cloudflare DNS already matches; no changes required.')
            return
        print('Proposed Cloudflare DNS changes (unrelated records will not be deleted):')
        for previous, record in plan:
            content = '[DKIM public key]' if record['content'].startswith('v=DKIM1') else record['content']
            print(f"  {'Update' if previous else 'Create'} {record['type']} {record['name']} -> {content}; proxied={record.get('proxied', False)}")
        if env.ask('Apply these DNS changes? [y/N]').lower() != 'y':
            raise ValueError('DNS changes declined; deployment blocked')
        for previous, record in plan:

            current = self.plan([{key: value for key, value in record.items() if key != 'comment'}])
            if not current:
                continue
            if current[0][0] != previous:
                raise ValueError('DNS changed during approval; rerun to review a fresh plan')
            path = self.base + '/dns_records'
            self.request('PATCH' if previous else 'POST', path + ('/' + previous['id'] if previous else ''), record)
        if self.plan(desired):
            raise ValueError('Cloudflare DNS verification failed after applying changes')


def active():
    return bool(os.environ.get('ORION_SESSION_SOCKET') and session_request('get', 'cloudflare'))


def load():
    config = session_request('get', 'cloudflare')
    if not config:
        raise ValueError('Select option 3 in the pull project menu to configure Cloudflare for this run')
    return config, Cloudflare(config['zone_id'], config['token'], config['owner'])


def configure():
    print('Token permissions: Zone / DNS / Edit, Zone / Zone / Read, Zone / Zone Settings / Edit.')
    print('Cloudflare credentials are kept in memory only. Certificate renewal requires a new interactive run before expiry.')
    from deployment import load as deployment_settings
    project = deployment_settings()['project_name']
    owner = 'orion-package:' + hashlib.sha256(project.encode()).hexdigest()[:32]
    while True:
        token = getpass.getpass('Cloudflare API token for orionintelligence.org (hidden; Ctrl+C to cancel): ').strip()
        try:
            probe = Cloudflare('0' * 32, token, owner)
            if probe.request('GET', '/user/tokens/verify')['result'].get('status') != 'active':
                raise ValueError('Cloudflare token is not active')
            zones = probe.request('GET', '/zones?' + urlencode({'name': 'orionintelligence.org', 'status': 'active'}))['result']
            if len(zones) != 1 or zones[0].get('name') != 'orionintelligence.org':
                raise ValueError('Token cannot access the active orionintelligence.org zone')
            zone = zones[0].get('id', '')
            client = Cloudflare(zone, token, owner)
            client.request('GET', client.base + '/settings/ssl')
            break
        except ValueError as error:
            env.show_error(error, 'Paste a newly created User API token scoped to orionintelligence.org; do not enter a Token ID, Zone ID, Account ID, or Global API Key.')
    while True:
        email = env.ask('Let’s Encrypt account email')
        if re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
            break
        env.show_error('A valid Let’s Encrypt account email is required', 'Enter a complete email address, or q to cancel.')
    if env.ask('Enable Cloudflare DNS/certificate setup for this run only? [y/N]').lower() != 'y':
        raise ValueError('Cloudflare setup cancelled')
    session_request('set', 'cloudflare', {'zone_id': zone, 'email': email, 'owner': owner, 'token': token})
    print('Cloudflare enabled for this run only; no token or Zone ID saved.')


def address(document, name, proxied):
    ip = ipaddress.ip_address(env.get(document, 'SERVER_IP'))
    return {'type': 'A' if ip.version == 4 else 'AAAA', 'name': name, 'content': str(ip), 'ttl': 1, 'proxied': proxied}


def desired_records(document):
    module = document.path.parent.name
    domains = env.domains(document)
    if module == 'Orion-Intelligence':
        return [address(document, domains[0], True)]
    if module == 'Orion-Tor2Web':
        return [address(document, domains[0], False), address(document, '*.onion.' + domains[0], False)]
    mail = domains[0]
    smtp = env.hostname(env.get(document, 'SMTP_HOSTNAME'))
    if smtp == mail:
        raise ValueError('SMTP_HOSTNAME must differ from the proxied webmail MAIL_DOMAIN')
    if ipaddress.ip_address(env.get(document, 'SERVER_IP')).version != 4:
        raise ValueError('This Postfix profile currently requires a public IPv4 address for SMTP')
    return [address(document, mail, True), address(document, smtp, False),
            {'type': 'MX', 'name': mail, 'content': smtp, 'priority': 10, 'ttl': 1},
            {'type': 'TXT', 'name': mail, 'content': 'v=spf1 ip4:' + env.get(document, 'SERVER_IP') + ' -all', 'ttl': 1},
            {'type': 'TXT', 'name': '_dmarc.' + mail, 'content': 'v=DMARC1; p=none', 'ttl': 1}]


def certificates(document, config):
    directory, name, hosts = env.certificate_spec(document)
    if directory != Path('/etc/letsencrypt'):
        raise ValueError('Session-only issuance uses /etc/letsencrypt; provision custom certificate mounts manually')
    try:
        env.check_certificate(document)
        env.command('openssl', 'x509', '-in', directory / 'live' / name / 'fullchain.pem',
                    '-noout', '-checkend', str(30 * 86400), privileged=True)
        print('Existing certificate is valid for more than 30 days; reusing it.')
        return
    except ValueError:
        pass
    print('Certificate issuance uses the API token in memory only. No unattended renewal will be configured for this certificate.')
    if env.ask('Issue/renew now and accept Let’s Encrypt terms? [y/N]').lower() != 'y':
        raise ValueError('Certificate issuance declined')
    if not shutil.which('certbot'):
        if not shutil.which('apt-get'):
            raise ValueError('Install Certbot and its dns-cloudflare plugin manually')
        env.command('apt-get', 'update', privileged=True, capture=False)
        env.command('apt-get', 'install', '-y', 'certbot', 'python3-certbot-dns-cloudflare', privileged=True, capture=False)
    if 'dns-cloudflare' not in env.command('certbot', 'plugins', privileged=True):
        raise ValueError('Install the dns-cloudflare plugin in your Certbot installation, then retry')
    try:
        previous = env.command('openssl', 'x509', '-in', directory / 'live' / name / 'fullchain.pem',
                               '-noout', '-ext', 'subjectAltName', privileged=True)
    except ValueError:
        previous = ''
    hosts = tuple(sorted(set(hosts) | set(re.findall(r'DNS:([a-zA-Z0-9*.-]+)', previous))))
    if any(not host.removeprefix('*.').endswith('.orionintelligence.org') and host.removeprefix('*.') != 'orionintelligence.org' for host in hosts):
        raise ValueError('Existing certificate includes names outside this zone; review manually')
    args = ['--cert-name', name, '--email', config['email'], '--agree-tos', '--non-interactive', '--expand',
            *[part for host in hosts for part in ('-d', host)]]
    env.command('python3', Path(__file__).with_name('certbot_session.py'), privileged=True, capture=False,
                input_data=json.dumps({'token': config['token'], 'args': args}))
    env.check_certificate(document)
    env.command('bash', Path(__file__).with_name('renew_orion.sh'), privileged=True, capture=False)
    print('Certificate ready. Rerun pull and select option 3 before expiry to renew; no saved DNS token or automatic renewal.')


def ensure(path):
    config, client = load()
    client.verify()
    document = env.Environment(path)
    desired = desired_records(document)
    client.plan(desired)
    certificates(document, config)
    if any(record.get('proxied') for record in desired):
        setting = client.request('GET', client.base + '/settings/ssl')['result']
        if setting.get('value') != 'strict':
            print('Full (strict) is a ZONE-WIDE change; other sites with invalid origin certificates may break.')
            if env.ask('Change this entire zone to Full (strict)? [y/N]').lower() != 'y':
                raise ValueError('Set Full (strict) manually, then retry; no DNS changes applied')
            client.request('PATCH', client.base + '/settings/ssl', {'value': 'strict'})
            if client.request('GET', client.base + '/settings/ssl')['result'].get('value') != 'strict':
                raise ValueError('Could not verify Full (strict)')
    client.reconcile(desired)
    for record in desired:
        if record['type'] not in {'A', 'AAAA'}:
            continue
        hostname = record['name'].replace('*.', 'setup-check.')
        while True:
            try:
                addresses = {item[4][0] for item in socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)}
                if not record['proxied'] and record['content'] not in addresses:
                    raise ValueError('Public DNS does not yet resolve to the VPS IP')
                if record['proxied']:
                    with socket.create_connection((hostname, 443), timeout=10) as connection:
                        with ssl.create_default_context().wrap_socket(connection, server_hostname=hostname):
                            pass
                break
            except (OSError, ValueError):
                print(f'{hostname}: DNS or Cloudflare edge TLS is not ready yet. Check propagation/Universal SSL activation.')
                env.ask('Press Enter to recheck, or q to stop')
    print('Cloudflare DNS and certificates ready for this deployment. Provider firewall/SMTP port access still requires verification.')
    if path.parent.name == 'Orion-mail':
        print('Set provider PTR for ' + env.get(document, 'SERVER_IP') + ' to ' + env.get(document, 'SMTP_HOSTNAME'))
        if env.ask('Confirm provider PTR and inbound/outbound TCP 25 access are configured [y/N]').lower() != 'y':
            raise ValueError('Finish VPS-provider mail setup before continuing')


def publish_dkim(path):
    _, client = load()
    client.verify()
    document = env.Environment(path)
    text = (path.parent / '.runtime/dkim-record.txt').read_text()
    compact = re.sub(r'[\s"]', '', text)
    key = re.search(r'p=([A-Za-z0-9+/=]+)', compact)
    if not key:
        raise ValueError('No DKIM public key found; private keys are never published')
    client.reconcile([{'type': 'TXT', 'name': 'mail._domainkey.' + env.get(document, 'MAIL_DOMAIN'),
                       'content': 'v=DKIM1; k=rsa; p=' + key[1], 'ttl': 1}])


if __name__ == '__main__':
    try:
        if not sys.stdin.isatty():
            raise ValueError('Run Cloudflare setup in a terminal; token input must be hidden')
        configure()
    except (EOFError, KeyboardInterrupt):
        print('\nCloudflare setup cancelled.', file=sys.stderr)
        sys.exit(1)
    except (OSError, ValueError, KeyError, TypeError) as error:
        env.show_error(f'Cloudflare setup failed: {error}', 'Check the Zone ID, token permissions, DNS conflict, or connectivity, then retry Cloudflare setup.')
        sys.exit(1)
