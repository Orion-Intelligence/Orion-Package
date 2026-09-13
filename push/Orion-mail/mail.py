import base64
import copy
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from urllib.parse import urlsplit

PACKAGE = Path(__file__).resolve().parent
PACKAGE_ROOT = PACKAGE.parents[1]
IMAGE_VARIABLE = '${ORION_PACKAGE_IMAGE:?Select the mail image}'
RUNTIME = '${ORION_MAIL_RUNTIME:?Set the mail runtime directory}'


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def deployment(repo):
    result = run('docker', 'compose', '--env-file', '/dev/null', '--file', str(repo / 'docker-compose-production.yml'),
                 'config', '--no-interpolate', '--no-env-resolution', '--no-path-resolution',
                 '--format', 'json', capture_output=True, text=True)
    config = json.loads(result.stdout)
    config['name'] = 'orion-mail'
    for group in ('networks', 'volumes'):
        for item in config.get(group, {}).values():
            if not item.get('external'):
                item.pop('name', None)
    services = config['services']
    del services['certbot']
    for name in ('web', 'postfix', 'nginx'):
        service = services[name]
        service.pop('build', None)
        service['image'] = IMAGE_VARIABLE
        service['command'] = [name]
        service['user'] = '0:0' if name == 'postfix' else '${APP_UID:-1000}:${APP_GID:-1000}'
    web = services['web']
    web['env_file'] = ['${ORION_ENV_FILE:?Set the mail env file}']
    web['environment'].update(ORION_TESTING='false', ORION_COVERAGE='false', SMTP_START_TLS='false',
                              MAIL_DOMAIN='${MAIL_DOMAIN:-mail.orionintelligence.org}',
                              INCOMING_MAIL_TOKEN='${INCOMING_MAIL_TOKEN:?Set the incoming-mail token}',
                              APP_UID='${APP_UID:-1000}', APP_GID='${APP_GID:-1000}')
    web['volumes'] = [{'type': 'bind', 'source': '${ORION_MAIL_ATTACHMENTS:-${ORION_SOURCE_DIR}/backend/static/resource/attachments}',
                       'target': '/app/static/resource/attachments'}]
    cron = copy.deepcopy(web)
    cron['container_name'] = 'orion-mail-cron'
    cron['command'] = ['cron']
    cron.pop('ports', None)
    cron['depends_on'] = {'web': {'condition': 'service_healthy'}}
    cron['healthcheck'] = {'disable': True}
    services['cron'] = cron
    postfix = services['postfix']
    postfix['depends_on']['web']['condition'] = 'service_healthy'
    postfix['depends_on']['rspamd']['condition'] = 'service_healthy'
    postfix['environment'].pop('POSTFIX_MYNETWORKS', None)
    postfix['environment']['SMTP_HOSTNAME'] = '${SMTP_HOSTNAME:?Set the DNS-only SMTP hostname}'
    postfix['environment']['ORION_MAIL_CERT_DIR'] = '${ORION_MAIL_CERT_DIR:-/etc/letsencrypt/live/try.orionintelligence.org}'
    postfix['volumes'].append({'type': 'bind', 'source': '${ORION_LETSENCRYPT_DIR:-/etc/letsencrypt}',
                               'target': '/etc/letsencrypt', 'read_only': True,
                               'bind': {'create_host_path': False}})
    postfix['ports'] = ['${ORION_MAIL_SMTP_BIND:-0.0.0.0}:${ORION_MAIL_SMTP_PORT:-25}:25']
    nginx = services['nginx']
    nginx['environment'] = {'MAIL_DOMAIN': '${MAIL_DOMAIN:-mail.orionintelligence.org}'}
    nginx.pop('volumes', None)
    nginx['healthcheck']['test'] = ['CMD', 'python3', '-c',
        "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=5).read()"]
    services['rspamd']['environment'] = {'MAIL_DOMAIN': '${MAIL_DOMAIN:-mail.orionintelligence.org}'}
    for service, target, source in (('rspamd', '/etc/rspamd/local.d', '/rspamd'),
                                    ('clamav', '/etc/clamav/clamd.conf', '/clamd.conf')):
        for volume in services[service]['volumes']:
            if volume['target'] == target:
                volume['source'] = RUNTIME + source
    config['volumes'].pop('letsencrypt-webroot', None)
    config['volumes'].pop('tls-certs', None)
    return config


def build(repo, image):
    with tempfile.TemporaryDirectory(prefix='orion-mail-build-') as directory:
        context = Path(directory)
        app = context / 'app'
        app.mkdir()
        for name in ('main.py', 'cronjobs.py', 'cleanup_attachments.py', 'postfix_incoming_handler.py'):
            shutil.copy2(repo / 'backend' / name, app / name)
        ignored = shutil.ignore_patterns('__pycache__', '*.pyc', '*.log', '.env*', 'tests')
        for name in ('configs', 'routes', 'orion'):
            shutil.copytree(repo / 'backend' / name, app / name, ignore=ignored)
        shutil.copy2(repo / 'dockerFiles/postfix-entrypoint.sh', app / 'postfix-entrypoint.sh')
        client = context / 'client'
        client.mkdir()
        for name in ('package.json', 'package-lock.json', 'angular.json', 'tsconfig.json', 'tsconfig.app.json', '.postcssrc.json'):
            shutil.copy2(repo / 'client' / name, client / name)
        shutil.copytree(repo / 'client/src', client / 'src', ignore=ignored)
        (context / 'nginx').mkdir()
        for name in ('nginx-prod.conf', 'proxy-params.conf', 'security-headers.conf'):
            shutil.copy2(repo / 'nginx' / name, context / 'nginx' / name)
        nginx = context / 'nginx/nginx-prod.conf'
        nginx.write_text(nginx.read_text().replace('mail.orionintelligence.org', '${MAIL_DOMAIN}'))
        runtime = context / 'runtime'
        runtime.mkdir()
        shutil.copytree(repo / 'rspamd/local.d', runtime / 'rspamd',
                        ignore=shutil.ignore_patterns('*secret*', '*.key', '*.pem'))
        shutil.copy2(repo / 'clamav/clamd.conf', runtime / 'clamd.conf')
        shutil.copy2(repo / 'backend/static/maintenance.html', context / 'maintenance.html')
        dependencies = (repo / 'backend/requirements.txt').read_text().splitlines()
        (context / 'requirements.txt').write_text('\n'.join(
            line for line in dependencies if not line.startswith(('pytest', 'coverage'))) + '\n')
        for name in ('Dockerfile', 'prepare.py', 'entrypoint.sh'):
            shutil.copy2(PACKAGE / name, context / name)
        shutil.copy2(PACKAGE_ROOT / '_shared/compile_backend.py', context / 'compile_backend.py')
        shutil.copy2(PACKAGE_ROOT / '_shared/audit_release.py', context / 'audit_release.py')
        shutil.copytree(PACKAGE_ROOT / '_shared/obfuscation', context / 'obfuscation')
        (context / 'compose.json').write_text(json.dumps(deployment(repo)))
        run('docker', 'build', '--tag', image, str(context))


def pull(env_file, image):
    runtime = env_file.parent / '.runtime'
    environment = dict(os.environ, ORION_PACKAGE_IMAGE=image, ORION_ENV_FILE=str(env_file),
                       ORION_MAIL_RUNTIME=str(runtime))
    environment.setdefault('ORION_SOURCE_DIR', str(PACKAGE_ROOT.parent / 'Orion-mail'))
    run('docker', 'pull', image)
    capability = run('docker', 'image', 'inspect', '--format', '{{index .Config.Labels "orion.package.smtp-hostname"}}', image, capture_output=True, text=True).stdout.strip()
    if capability != '1':
        raise RuntimeError('Rebuild/push Orion-mail with this package first: the downloaded image does not support a separate SMTP hostname. No DNS changes were made.')
    run(sys.executable, '-B', str(PACKAGE_ROOT / 'pull/_shared/deployment.py'), '--apply', env_file.parent.name)
    run(sys.executable, '-B', str(env_file.parent / 'fill_env.py'))
    run(sys.executable, '-B', str(env_file.parent / 'setup.py'))
    manifest = run('docker', 'run', '--rm', '--network', 'none', '--entrypoint', 'cat',
                   image, '/opt/orion/compose.json', capture_output=True, text=True).stdout
    config = json.loads(manifest)
    if config.get('name') != 'orion-mail' or any(
            config['services'][name]['image'] != IMAGE_VARIABLE for name in ('web', 'cron', 'postfix', 'nginx')):
        raise RuntimeError('Unexpected mail deployment manifest')
    runtime.mkdir(parents=True, exist_ok=True)
    (runtime / 'compose.json').write_text(manifest)
    with tempfile.TemporaryDirectory(prefix='orion-mail-pull-') as directory:
        compose_file = Path(directory) / 'compose.json'
        compose_file.write_text(manifest)
        command = ['docker', 'compose', '--project-name', 'orion-mail', '--env-file', str(env_file),
                   '--project-directory', str(env_file.parent), '--file', str(compose_file)]

        def compose(*args, **kwargs):
            return run(*command, *args, env=environment, **kwargs)

        resolved = json.loads(compose('config', '--format', 'json', capture_output=True, text=True).stdout)
        services = resolved['services']
        settings = services['web']['environment']
        validate_settings(settings)
        check_smtp_port(services['postfix'])
        domain = services['postfix']['environment']['MAIL_DOMAIN']
        edge = environment.get('ORION_MAIL_EDGE_CONTAINER', 'trusted-web-nginx')
        run('docker', 'network', 'inspect', 'shared_bridge', capture_output=True)
        edge_config = run('docker', 'exec', edge, 'nginx', '-T', capture_output=True, text=True).stdout
        if not re.search(r'server_name\s+' + re.escape(domain) + r'\s*;', edge_config) or 'orion-mail-nginx:8080' not in edge_config:
            raise RuntimeError(f'Configure the shared edge proxy for {domain} before deploying mail')
        cert_mount = next(item for item in services['postfix']['volumes'] if item['target'] == '/etc/letsencrypt')
        run('docker', 'run', '--rm', '--network', 'none', '--read-only', '--user', '0:0',
            '--mount', f"type=bind,src={cert_mount['source']},dst=/etc/letsencrypt,readonly",
            '--env', f'MAIL_DOMAIN={domain}', '--env', 'SMTP_HOSTNAME=' + services['postfix']['environment']['SMTP_HOSTNAME'], '--env',
            'ORION_MAIL_CERT_DIR=' + services['postfix']['environment']['ORION_MAIL_CERT_DIR'], image, 'check')
        compose('pull')
        payload = run('docker', 'run', '--rm', '--network', 'none', '--entrypoint', 'tar', image,
                      '-C', '/opt/orion/runtime', '-cf', '-', '.', capture_output=True).stdout
        unpack_runtime(payload, runtime)
        password = settings['RSPAMD_CONTROLLER_PASSWORD']
        hashed = run('docker', 'run', '--rm', '--interactive', '--network', 'none', '--entrypoint', 'sh',
                     services['rspamd']['image'], '-ec',
                     'IFS= read -r password; exec rspamadm pw --encrypt -p "$password"',
                     input=password + '\n', capture_output=True, text=True).stdout.strip()
        if not re.fullmatch(r'\$[A-Za-z0-9$./+=_-]+', hashed):
            raise RuntimeError('Rspamd did not return a valid password hash')
        secret = runtime / 'rspamd/worker-controller-secret.inc'
        secret.write_text(f'password = "{hashed}";\nenable_password = "{hashed}";\n')
        secret.chmod(0o644)
        attachment = next(item['source'] for item in services['web']['volumes']
                          if item['target'] == '/app/static/resource/attachments')
        Path(attachment).mkdir(parents=True, exist_ok=True)
        compose('run', '--rm', '--no-deps', '--user', '0:0', '--cap-add', 'CHOWN',
                '--cap-add', 'DAC_OVERRIDE', '--cap-add', 'FOWNER', 'web', 'prepare')
        public_key = compose('run', '--rm', '--no-deps', '--entrypoint', 'sh', 'rspamd', '-ec',
            'umask 077; mkdir -p /var/lib/rspamd/dkim; key="/var/lib/rspamd/dkim/$MAIL_DOMAIN.mail.key"; '
            'if [ ! -s "$key" ]; then rspamadm dkim_keygen -d "$MAIL_DOMAIN" -s mail -k "$key" > "$key.txt"; fi; '
            'if [ -s "$key.txt" ]; then cat "$key.txt"; fi', capture_output=True, text=True).stdout
        if public_key.strip():
            (runtime / 'dkim-record.txt').write_text(public_key)
            print(f'DKIM public DNS record: {runtime / "dkim-record.txt"} (publish it in DNS if not already present)')
        run(sys.executable, '-B', str(PACKAGE_ROOT / 'pull/_shared/environment.py'), '--mail-dns', str(env_file))
        compose('up', '--detach', '--no-build', '--wait', '--wait-timeout', '900')
        compose('exec', '-T', 'rspamd', 'rspamadm', 'control', 'reload')
        run('docker', 'exec', edge, 'nginx', '-t')
        run('docker', 'exec', edge, 'nginx', '-s', 'reload')
        print('Mail deployed. Keep the shared Let’s Encrypt renewal job enabled; Postfix reloads certificates every 12 hours.')


def validate_settings(settings):
    domain = settings.get('MAIL_DOMAIN', 'mail.orionintelligence.org')
    if not re.fullmatch(r'(?=.{1,253}$)[a-zA-Z0-9](?:[a-zA-Z0-9.-]*[a-zA-Z0-9])?', domain) or '..' in domain:
        raise ValueError('MAIL_DOMAIN must be a DNS hostname')
    if len(settings.get('ORION_MAIL_SSO_CLIENT_SECRET', '')) < 32:
        raise ValueError('ORION_MAIL_SSO_CLIENT_SECRET must match Orion Intelligence and contain at least 32 characters')
    public_url = urlsplit(settings.get('ORION_INTELLIGENCE_PUBLIC_URL', ''))
    if public_url.scheme != 'https' or not public_url.hostname or public_url.username:
        raise ValueError('Set ORION_INTELLIGENCE_PUBLIC_URL to the public HTTPS Orion Intelligence URL before production deployment')
    if len(base64.urlsafe_b64decode(settings.get('ENCRYPTION_KEY', ''))) != 32:
        raise ValueError('ENCRYPTION_KEY must be the existing Fernet key; never replace it for an existing database')
    for key in ('INCOMING_MAIL_TOKEN', 'RSPAMD_CONTROLLER_PASSWORD'):
        if not settings.get(key) or any(char in settings[key] for char in '\r\n'):
            raise ValueError(f'{key} must be configured without line breaks')
    for key in ('APP_UID', 'APP_GID'):
        if not settings.get(key, '').isdigit() or int(settings[key]) == 0:
            raise ValueError(f'{key} must be a non-root numeric ID')


def check_smtp_port(service):
    port = str(service['ports'][0]['published'])
    listeners = run('ss', '-H', '-ltn', capture_output=True, text=True).stdout
    if not any(line.split()[3].rsplit(':', 1)[-1] == port for line in listeners.splitlines() if len(line.split()) >= 4):
        return
    existing = subprocess.run(['docker', 'inspect', '--format', '{{json .NetworkSettings.Ports}}', 'orion-mail-postfix'],
                              capture_output=True, text=True)
    bindings = ((json.loads(existing.stdout) or {}).get('25/tcp') or []) if existing.returncode == 0 else []
    if not any(binding['HostPort'] == port for binding in bindings):
        raise RuntimeError(f'SMTP port {port} is occupied outside Orion-mail; resolve the conflict before pulling')


def unpack_runtime(payload, destination):
    with tarfile.open(fileobj=io.BytesIO(payload)) as bundle:
        for member in bundle.getmembers():
            path = Path(member.name)
            if (path.is_absolute() or '..' in path.parts or not (member.isfile() or member.isdir())
                    or (member.isfile() and not (path == Path('clamd.conf')
                        or (path.parent == Path('rspamd') and path.suffix in {'.conf', '.inc'})))
                    or member.size > 1024 * 1024):
                raise ValueError(f'Unexpected runtime configuration: {member.name}')
        destination.mkdir(parents=True, exist_ok=True)
        bundle.extractall(destination, filter='data')


if __name__ == '__main__':
    try:
        action, location, image = sys.argv[1:]
        if action not in {'build', 'pull'}:
            raise ValueError('Use build or pull')
        (build if action == 'build' else pull)(Path(location).resolve(), image)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f'Mail packaging failed: {error}', file=sys.stderr)
        sys.exit(1)
