import argparse
import fcntl
import ipaddress
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from env_filler import Environment, MODULES, pending, save, encode

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = {'Orion-Intelligence', 'Orion-mail'}


class MenuBack(Exception):
    pass


def failure_text(message, action):
    color = '\033[31m' if sys.stderr.isatty() else ''
    reset = '\033[0m' if color else ''
    return f'{color}Error: {message}{reset}\nAction: {action}'


def show_error(message, action):
    print(failure_text(message, action), file=sys.stderr, flush=True)


def command(*args, privileged=False, capture=True, input_data=None, timeout=30):
    prefix = ['sudo', '--'] if privileged and os.geteuid() else []
    try:
        result = subprocess.run([*prefix, *map(str, args)], capture_output=capture, text=True, input=input_data,
                                timeout=timeout if capture else None)
    except subprocess.TimeoutExpired:
        raise ValueError(f'{args[0]} timed out; fix the prerequisite and retry') from None
    if result.returncode:

        detail = (result.stderr or '').strip()
        raise ValueError(f'{args[0]} failed (exit {result.returncode})' + (': ' + detail if detail else '; fix the prerequisite and retry'))
    return result.stdout or ''


def choose(prompt, options):
    result = subprocess.run(['bash', str(ROOT.parent / '_shared/menu.sh'), prompt, *options],
                            capture_output=True, text=True)
    if result.returncode == 129:
        raise MenuBack
    if result.returncode in (130, 143):
        raise KeyboardInterrupt
    if result.returncode or result.stdout.strip() not in {str(index + 1) for index in range(len(options))}:
        raise ValueError('Interactive menu failed: ' + result.stderr.strip())
    return result.stdout.strip()


def ask(prompt):
    if prompt.startswith('1) '):
        options = re.split(r'\s{2,}(?=\d+\) )', prompt)
        return choose('Select an option', [re.sub(r'^\d+\) ', '', option) for option in options])
    if prompt.startswith('Fix prerequisites then Enter'):
        return 'network' if choose('Missing prerequisites', ['Retry checks', 'Create required Docker bridge']) == '2' else ''
    if any(text in prompt.lower() for text in ('press enter', 'then enter to retry')):
        if choose(prompt, ['Retry / continue', 'Cancel']) == '2':
            raise KeyboardInterrupt
        return ''
    reply = input(prompt + ' (q to cancel): ').strip()
    if reply.lower() == 'q':
        raise KeyboardInterrupt
    return reply


def hostname(value):
    try:
        ipaddress.ip_address(value)
    except ValueError:
        pass
    else:
        raise ValueError('Use a DNS hostname, not an IP address')
    if len(value) > 253 or '.' not in value or not all(
            re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label)
            for label in value.split('.')):
        raise ValueError('Enter a lowercase DNS hostname, without https://, a port, path or wildcard')
    return value


def get(document, key, default=''):
    return document.get(key) if key in document.entries else default


def update(path, values):
    lock_dir = ROOT / '.runtime'
    lock_dir.mkdir(exist_ok=True)
    with (lock_dir / 'env-fill.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        document = Environment(path)
        for key, value in values.items():
            if key in document.entries:
                document.set(key, value, replace=True)
            else:
                if document.lines and not document.lines[-1].endswith('\n'):
                    document.lines[-1] += '\n'
                document.lines.append(key + '=' + encode(value) + '\n')
                document.changed.append(key)
        save({path.parent.name: document})


def domains(document) -> tuple[str, ...]:
    module = document.path.parent.name
    if module == 'Orion-Intelligence':
        base = hostname(get(document, 'TENANT_BASE_DOMAIN'))
        url = urlsplit(get(document, 'APP_URL'))
        host = hostname(url.hostname or '')
        if url.scheme != 'https' or url.netloc != host or url.path not in ('', '/') or url.query or url.fragment:
            raise ValueError('APP_URL must be https://hostname without credentials, port or path')
        if not host.endswith('.' + base):
            raise ValueError('APP_URL must be a subdomain of TENANT_BASE_DOMAIN')
        mail = hostname(get(document, 'MAIL_DOMAIN', 'mail.' + base))
        return host, base, mail
    if module == 'Orion-mail':
        return (hostname(get(document, 'MAIL_DOMAIN')),)
    return ()


def edit_domains(path):
    module = path.parent.name
    if module == 'Orion-Intelligence':
        base = hostname(ask('Tenant base domain (example.org)'))
        host = hostname(ask('Application hostname (app.example.org)'))
        mail = hostname(ask('Mail hostname (mail.example.org)'))
        if not host.endswith('.' + base):
            raise ValueError('Application hostname must be below the tenant base domain')
        values = {'TENANT_BASE_DOMAIN': base, 'APP_URL': 'https://' + host,
                  'PRODUCTION_DOMAIN': 'https://' + host, 'MAIL_DOMAIN': mail,
                  'ORION_MAIL_PUBLIC_URL': 'https://' + mail,
                  'ORION_MAIL_REDIRECT_URIS': 'https://' + mail + '/auth/callback'}
        print('Also update the Mail module’s Intelligence URL and DNS when changing this domain.')
    elif module == 'Orion-mail':
        host = hostname(ask('Mail hostname'))
        intelligence = hostname(ask('Intelligence application hostname'))
        smtp = hostname(ask('DNS-only SMTP hostname (different from webmail)'))
        if smtp == host:
            raise ValueError('SMTP hostname must differ from the proxied webmail hostname')
        values = {'MAIL_DOMAIN': host, 'SMTP_HOSTNAME': smtp, 'ORION_INTELLIGENCE_PUBLIC_URL': 'https://' + intelligence,
                  'ORION_MAIL_PUBLIC_URLS': 'https://' + host, 'CORS_ALLOWED_ORIGINS': 'https://' + host,
                  'ALLOWED_HOSTS': host + ',localhost,127.0.0.1,orion-mail-web'}
        print('Configure this hostname in the shared Intelligence edge and its SSO redirect allowlist too.')
    update(path, values)


def domain_menu(path):
    if path.parent.name not in PUBLIC:
        print('Internal service: no public domain/certificate is required; internal service names stay unchanged.')
        return
    while True:
        try:
            current = domains(Environment(path))
            print('Configured domains: ' + ', '.join(current))
        except ValueError as error:
            current = ()
            print(error)
        choice = ask('1) Change domains  2) Continue')
        try:
            if choice == '1':
                edit_domains(path)
            elif choice == '2' and current:
                return
        except ValueError as error:
            print(error)


def certificate_spec(document):
    names = domains(document)
    module = document.path.parent.name
    if module == 'Orion-Intelligence':
        host, base, mail = names
        directory = get(document, 'ORION_LETSENCRYPT_DIR', '/etc/letsencrypt')
        name = get(document, 'LETSENCRYPT_CERT_NAME', 'try.orionintelligence.org')
        hosts = (host, '*.' + base, mail)
    elif module == 'Orion-mail':
        directory = get(document, 'ORION_LETSENCRYPT_DIR', '/etc/letsencrypt')
        cert = get(document, 'ORION_MAIL_CERT_DIR', '/etc/letsencrypt/live/try.orionintelligence.org')
        if not cert.startswith('/etc/letsencrypt/live/'):
            raise ValueError('ORION_MAIL_CERT_DIR must be /etc/letsencrypt/live/<certificate-name> inside the container')
        name = cert.removeprefix('/etc/letsencrypt/live/')
        hosts = tuple(dict.fromkeys((*names, hostname(get(document, 'SMTP_HOSTNAME', names[0])))))
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]*', name) or not Path(directory).is_absolute():
        raise ValueError('Use an absolute Let’s Encrypt directory and a plain certificate name')
    return Path(directory), name, hosts


def check_certificate(document):
    directory, name, hosts = certificate_spec(document)
    cert = directory / 'live' / name / 'fullchain.pem'
    key = cert.with_name('privkey.pem')
    if not cert.is_file() or not key.is_file():
        raise ValueError(f'Certificate files are missing from {cert.parent}')
    sans = command('openssl', 'x509', '-in', cert, '-noout', '-ext', 'subjectAltName', privileged=True)
    certificate_names = set(re.findall(r'DNS:([a-zA-Z0-9*.-]+)', sans))
    if any(host.startswith('*.') and host not in certificate_names for host in hosts):
        raise ValueError('Certificate is missing a required wildcard SAN')
    for host in hosts:
        command('openssl', 'x509', '-in', cert, '-noout', '-checkhost', host.replace('*.', 'setup-check.'), privileged=True)
    command('openssl', 'x509', '-in', cert, '-noout', '-checkend', '86400', privileged=True)
    command('openssl', 'verify', '-purpose', 'sslserver', '-untrusted', cert, cert, privileged=True)
    public = command('openssl', 'x509', '-in', cert, '-noout', '-pubkey', privileged=True)
    if public != command('openssl', 'pkey', '-in', key, '-pubout', privileged=True):
        raise ValueError('Certificate and private key do not match')


def tls_menu(path):
    if path.parent.name not in PUBLIC:
        return
    import cloudflare_setup
    if cloudflare_setup.active():
        cloudflare_setup.ensure(path)
        return
    document = Environment(path)
    _, _, hosts = certificate_spec(document)
    try:
        check_certificate(document)
    except ValueError as error:
        show_error(error, 'A Cloudflare token is required now to create or repair this certificate.')
        cloudflare_setup.configure()
        cloudflare_setup.ensure(path)
        return
    print('Checking DNS...', flush=True)
    for host in hosts:
        command('getent', 'ahosts', host.replace('*.', 'setup-check.'), timeout=10)
    print('TLS verified.', flush=True)

def required_values(path):
    document = Environment(path)
    missing = [(key, document.get(key)) for key in document.entries if pending(document.get(key))]

    from env_filler import AUTOMATIC
    for key in AUTOMATIC[path.parent.name]:
        if key not in document.entries or not document.get(key).strip():
            missing.append((key, '{value_auto}'))
    if missing:
        assignments = '\n'.join(f'  {key}={value}' for key, value in sorted(set(missing)))
        raise ValueError(f'Required environment values now:\n{assignments}')


def module_prerequisites(path):
    document = Environment(path)
    module = path.parent.name
    if module in {'Orion-Micros', 'Orion-Social', 'Orion-mail'}:
        command('docker', 'network', 'inspect', 'shared_bridge')
    if module == 'Orion-mail':
        domain = domains(document)[0]
        config = command('docker', 'exec', 'trusted-web-nginx', 'nginx', '-T')
        if not re.search(r'server_name\s+' + re.escape(domain) + r'\s*;', config) or 'orion-mail-nginx:8080' not in config:
            raise ValueError('Configure/start the Intelligence shared edge with the Mail domain before continuing')
    if module == 'Orion-Dark-Nexus':
        command('docker', 'network', 'inspect', 'orion_nexus_backend')


def mail_dns(path):

    import cloudflare_setup
    if not cloudflare_setup.active():
        cloudflare_setup.configure()
    _, client = cloudflare_setup.load()
    client.verify()
    document = Environment(path)
    client.reconcile(cloudflare_setup.desired_records(document))
    cloudflare_setup.publish_dkim(path)
    print('Cloudflare verified the Mail address, SMTP, MX, SPF, DMARC and DKIM records. Public DNS propagation continues without blocking deployment.')


def main(module=None):
    if module is None:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument('module', nargs='?', default='')
        parser.add_argument('--mail-dns', type=Path)
        args = parser.parse_args()
        if args.mail_dns:
            if not sys.stdin.isatty():
                raise ValueError('Mail DNS setup requires a terminal')
            mail_dns(args.mail_dns)
            return
        module = args.module
    if not sys.stdin.isatty():
        raise ValueError('Environment setup requires a terminal; no prerequisites are silently skipped')
    if not module:
        choice = choose('Choose module', list(MODULES))
        if not choice.isdigit() or not 1 <= int(choice) <= len(MODULES):
            raise ValueError('Choose a listed module')
        module = MODULES[int(choice) - 1]
    if module not in MODULES:
        raise ValueError('Unknown module')
    path = ROOT / module / '.env'
    while not path.is_file():
        ask(f'Create {path} with the module’s required settings, then press Enter to retry')
    while True:
        domain_menu(path)
        while True:
            try:
                required_values(path)
                break
            except ValueError as error:
                choice = choose(failure_text(error, f'Set the listed values in {path}, then recheck. Passwords and internal shared secrets are generated automatically.'),
                                ['Recheck', 'Stop pull'])
                if choice == '2':
                    raise KeyboardInterrupt
        try:
            tls_menu(path)
            break
        except MenuBack:
            continue
    while True:
        try:
            module_prerequisites(path)
            break
        except (OSError, ValueError) as error:
            print(error)
            print('Required networks: shared_bridge (Micros/Social/Mail), orion_nexus_backend (Dark Nexus). Deploy Intelligence first or provision the existing network explicitly.')
            choice = ask('Fix prerequisites then Enter to retry, or type network to create the required bridge')
            network = 'orion_nexus_backend' if module == 'Orion-Dark-Nexus' else 'shared_bridge'
            if choice == 'network' and module != 'Orion-Intelligence':
                try:
                    command('docker', 'network', 'inspect', network)
                except ValueError:
                    command('docker', 'network', 'create', '--driver', 'bridge', network)
    required_values(path)
    print(f'{module}: setup gates passed; deployment will perform its remaining runtime/health checks.')


def cli(module=None):
    try:
        main(module)
    except (EOFError, KeyboardInterrupt, MenuBack):
        print('\nSetup cancelled; deployment blocked.', file=sys.stderr)
        sys.exit(1)
    except (OSError, ValueError) as error:
        print(error, file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    cli()
