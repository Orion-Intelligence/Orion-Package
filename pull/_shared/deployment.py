import argparse
import getpass
import ipaddress
import json
import os
from pathlib import Path
import re
import sys
import subprocess
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from environment import ROOT, MenuBack, ask, update
from env_filler import MODULES
sys.path.insert(0, str(ROOT.parent / '_shared'))
from session import request

STATE = ROOT / '.runtime/deployment.json'


def validate(name, address):
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,38}[a-z0-9]|[a-z]', name):
        raise ValueError('Project name must be a lowercase DNS label, starting with a letter, at most 40 characters')
    ip = ipaddress.ip_address(address)
    if ip.is_loopback or ip.is_unspecified or ip.is_multicast or '%' in address:
        raise ValueError('Enter the VPS public IPv4 or IPv6 address, not a loopback/unspecified address')
    return {'project_name': name, 'server_ip': str(ip)}


def load():
    if STATE.is_symlink():
        raise ValueError('Deployment settings must not be a symlink')
    data = json.loads(STATE.read_text())
    return validate(data['project_name'], data['server_ip'])


def save(data):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    if STATE.is_symlink():
        raise ValueError('Deployment settings must not be a symlink')
    descriptor, temporary = tempfile.mkstemp(prefix='.deployment-', dir=STATE.parent)
    try:
        with os.fdopen(descriptor, 'w') as output:
            json.dump(data, output, indent=2)
            output.write('\n')
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, STATE)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def values(module, data):
    project = data['project_name']
    app = project + '.orionintelligence.org'
    mail = project + 'mail.orionintelligence.org'
    result = {'PROJECT_NAME': project, 'SERVER_IP': data['server_ip']}
    if module == 'Orion-Intelligence':
        result.update(APP_URL='https://' + app, PRODUCTION_DOMAIN='https://' + app,
                      TENANT_BASE_DOMAIN='orionintelligence.org', MAIL_DOMAIN=mail,
                      ORION_MAIL_PUBLIC_URL='https://' + mail,
                      ORION_MAIL_REDIRECT_URIS='https://' + mail + '/auth/callback',
                      LETSENCRYPT_CERT_NAME=project + '-edge')
    elif module == 'Orion-mail':
        result.update(MAIL_DOMAIN=mail, SMTP_HOSTNAME=project + 'smtp.orionintelligence.org', ORION_INTELLIGENCE_PUBLIC_URL='https://' + app,
                      ORION_MAIL_PUBLIC_URLS='https://' + mail, CORS_ALLOWED_ORIGINS='https://' + mail,
                      ALLOWED_HOSTS=mail + ',localhost,127.0.0.1,orion-mail-web',
                      ORION_MAIL_CERT_DIR='/etc/letsencrypt/live/' + project + '-edge')
    elif module == 'Orion-Tor2Web':
        result.update(BASEHOST=project + 'tor.orionintelligence.org', LETSENCRYPT_CERT_NAME=project + '-tor')
    return result



def configure_docker(action='pull'):
    if not sys.stdin.isatty():
        raise ValueError('Run push.sh or pull.sh in a terminal to configure Docker Hub login')
    if not os.environ.get('ORION_SESSION_SOCKET'):
        raise ValueError('A private in-memory credential session is required')
    username = os.environ.get('ORION_IMAGE_NAMESPACE', 'msmannan00')
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]*', username):
        raise ValueError('ORION_IMAGE_NAMESPACE is not a valid Docker Hub namespace')
    permission = 'Read & Write' if action == 'push' else 'Read'
    print(f'Docker Hub PAT for {username}: {permission} access. Credentials are held in memory for this run only.')
    while True:
        token = getpass.getpass('Docker Hub PAT (hidden): ').strip()
        if not token or any(character.isspace() for character in token):
            print('Enter a nonempty PAT without whitespace, or Ctrl+C to cancel.')
            continue
        result = subprocess.run(
            ['docker', 'login', '--username', username, '--password-stdin', 'docker.io'],
            input=token + '\n', text=True, capture_output=True,
        )
        if result.returncode:
            print('Docker Hub login failed. Check the PAT/account/network and retry, or Ctrl+C to cancel.')
            continue
        request('set', 'docker_ready', True)
        print('Docker Hub login ready for this run; no PAT saved.')
        return


def menu(selected_modules=None):
    if not sys.stdin.isatty():
        raise ValueError('Run pull.sh in a terminal to configure this VPS')
    while True:
        if STATE.exists():
            data = load()
            print(f"Project: {data['project_name']} | VPS IP: {data['server_ip']}")
            print('Application: https://' + data['project_name'] + '.orionintelligence.org')
            print('Mail: https://' + data['project_name'] + 'mail.orionintelligence.org')
            public_selected = not selected_modules or any(module in {'Orion-Intelligence', 'Orion-mail', 'Orion-Tor2Web'} for module in selected_modules)
            options = ['Pull', 'Edit project/IP']
            if public_selected:
                options.append('Cloudflare setup')
            try:
                choice = ask('  '.join(f'{index}) {label}' for index, label in enumerate(options, 1)))
            except MenuBack:
                raise KeyboardInterrupt from None
            if choice == '1':
                if not request('get', 'docker_ready'):
                    configure_docker()
                return
            if choice == '3':
                from cloudflare_setup import configure
                try:
                    configure()
                except MenuBack:
                    continue
            if choice != '2':
                continue
            print('Editing updates this existing deployment; it does not create a second isolated stack. Existing credentials/data are retained.')
        else:
            print('First deployment: configure the project name and public VPS IP.')
        try:
            data = validate(ask('Project name'), ask('Public VPS IP'))
        except ValueError as error:
            print(error)
            continue
        save(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', choices=MODULES)
    parser.add_argument('--docker-login', choices=('push', 'pull'))
    parser.add_argument('--modules', nargs='*')
    args = parser.parse_args()
    if args.docker_login:
        configure_docker(args.docker_login)
    elif args.apply:
        data = load()
        from runtime_env import prepare
        prepare(ROOT)
        update(ROOT / args.apply / '.env', values(args.apply, data))
    else:
        menu(args.modules)


if __name__ == '__main__':
    try:
        main()
    except (EOFError, KeyboardInterrupt):
        print('\nDeployment cancelled.', file=sys.stderr)
        sys.exit(1)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f'Deployment settings failed: {error}', file=sys.stderr)
        sys.exit(1)
