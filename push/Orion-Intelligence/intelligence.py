import base64
import copy
import hashlib
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
PROJECT = 'trusted-search'
IMAGE = '${ORION_PACKAGE_IMAGE:?Select the Intelligence image}'
ASSETS = '${ORION_INTELLIGENCE_ASSETS:?Set the image assets directory}'
SOURCE = '${ORION_SOURCE_DIR:?Set the existing Intelligence data directory}'
STORAGE = {'/app/static': '/backend/static', '/app/workspace/resource': '/backend/workspace/resource',
           '/app/workspace/logs': '/backend/workspace/logs', '/app/workspace/parser/parser_files': '/backend/workspace/parser/parser_files',
           '/app/backups': '/backend/build/backups'}


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def failure(message, action):
    color = '\033[31m' if sys.stderr.isatty() else ''
    reset = '\033[0m' if color else ''
    print(f'{color}Error: {message}{reset}\nAction: {action}', file=sys.stderr, flush=True)


def bind(source, target, read_only=False):
    return {'type': 'bind', 'source': source, 'target': target, 'read_only': read_only,
            'bind': {'create_host_path': False}}


def deployment(repo):
    raw = run('docker', 'compose', '--env-file', '/dev/null', '--file', str(repo / 'docker-compose-production.yml'),
              'config', '--no-interpolate', '--no-env-resolution', '--no-path-resolution',
              '--format', 'json', capture_output=True, text=True).stdout
    config = json.loads(raw)
    config['name'] = PROJECT
    for group in ('networks', 'volumes'):
        for value in config.get(group, {}).values():
            if not value.get('external'):
                value.pop('name', None)
    services = config['services']
    web = services['web']
    web.pop('build')
    web.update(image=IMAGE, command=['web'], user='${APP_UID:-1000}:${APP_GID:-1000}')
    web['env_file'] = ['${ORION_ENV_FILE:?Set the Intelligence env file}']
    web['environment'].update(PRODUCTION='1', TESTING_ENABLED='0', PYTHONPATH='/app',
                              APP_UID='${APP_UID:-1000}', APP_GID='${APP_GID:-1000}')
    web['healthcheck']['test'] = ['CMD-SHELL', 'host="$${APP_URL#https://}"; host="$${host%%/*}"; '
                                  'curl --fail --silent --header "Host: $$host" http://127.0.0.1:8070/api/public > /dev/null']
    web['volumes'] = [bind(SOURCE + suffix, target) for target, suffix in STORAGE.items()]
    web['volumes'].append({'type': 'volume', 'source': 'bloom-data', 'target': '/app/bloom_data'})
    web['depends_on'] = {name: {'condition': 'service_healthy'} for name in ('elasticsearch', 'mongo', 'arangodb', 'redis_server')}
    cron = copy.deepcopy(web)
    cron.update(container_name='trusted-web-cron', command=['cron'], depends_on={'web': {'condition': 'service_healthy'}},
                healthcheck={'disable': True})
    cron.pop('expose', None)
    services['cron'] = cron
    nginx = services['nginx']
    nginx['volumes'] = [bind(ASSETS + '/nginx/nginx.conf', '/etc/nginx/nginx.conf', True),
                         bind(ASSETS + '/client', '/client_build', True),
                         bind(SOURCE + '/backend/static', '/app/static', True),
                         bind(SOURCE + '/backend/workspace/resource', '/app/workspace/resource', True),
                         bind('${ORION_LETSENCRYPT_DIR:-/etc/letsencrypt}', '/etc/letsencrypt', True),
                         {'type': 'volume', 'source': 'letsencrypt-webroot', 'target': '/var/www/letsencrypt', 'read_only': True}]
    nginx['depends_on'] = {name: {'condition': 'service_started'} for name in ('web', 'documentation')}
    nginx['command'] = ['sh', '-ec', '(while sleep 43200; do nginx -t && nginx -s reload || true; done) & exec nginx -g "daemon off;"']
    nginx['environment'] = {'ENABLE_BROTLI': '1', 'APP_URL': '${APP_URL}'}
    nginx['healthcheck']['test'] = ['CMD', 'nginx', '-t']
    docs = services['documentation']
    docs.pop('build')
    docs.update(image=nginx['image'], read_only=True,
                volumes=[bind(ASSETS + '/docs', '/usr/share/nginx/html', True),
                         bind(ASSETS + '/nginx/docs.conf', '/etc/nginx/nginx.conf', True)],
                tmpfs=['/run', '/var/cache/nginx', '/tmp'],
                healthcheck={'test': ['CMD-SHELL', 'wget -q -O /dev/null http://127.0.0.1/'],
                             'interval': '10s', 'timeout': '5s', 'retries': 6})

    services['mongo']['command'] = ['mongod', '--auth', '--bind_ip_all']
    services['redis_server'].pop('env_file', None)
    return config


def ignored(_directory, names):
    return [name for name in names if name in {'.git', '__pycache__', 'node_modules', '.angular', '_build',
            'tests', 'venv', '.venv', 'logs', 'sessions', '.runtime'} or name.startswith('.env')
            or name.endswith(('.pyc', '.pyo', '.pem', '.key', '.log', '.map', '-source.zip'))]


def build(repo, image):
    with tempfile.TemporaryDirectory(prefix='orion-intelligence-build-') as directory:
        context = Path(directory)
        app = context / 'app'
        app.mkdir()
        for name in ('main.py', 'interface.py', 'cronjobs.py', 'restore_backup.py'):
            shutil.copy2(repo / 'backend' / name, app / name)
        for name in ('orion', 'configs', 'routes', 'migrations'):
            shutil.copytree(repo / 'backend' / name, app / name, ignore=ignored)
        shutil.copy2(PACKAGE / 'runtime.py', app / 'package_runtime.py')
        client = context / 'client'
        client.mkdir()
        for name in ('package.json', 'package-lock.json', 'angular.json', 'tsconfig.json', 'tsconfig.app.json', 'postcss.config.cjs', 'tailwind.config.ts'):
            shutil.copy2(repo / 'client' / name, client / name)
        shutil.copytree(repo / 'client/src', client / 'src', ignore=ignored)
        shutil.copytree(repo / 'docs', context / 'docs', ignore=ignored)
        for source in (repo / 'docs/api_docs').rglob('*.md'):
            destination = context / 'api_docs' / source.relative_to(repo / 'docs/api_docs')
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        shutil.copytree(repo / 'backend/workspace/extension', context / 'extension', ignore=ignored)

        defaults = context / 'defaults'
        defaults.mkdir()
        tracked = run('git', '-C', str(repo), 'ls-files', '-z', '--', 'backend/static', 'backend/workspace/resource',
                      capture_output=True, text=True).stdout.split('\0')
        for name in filter(None, tracked):
            source = repo / name
            if source.suffix == '.py' or ('workspace/resource/' in name and 'default' not in source.name):
                continue
            relative = Path(name).relative_to('backend')
            destination = defaults / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        shutil.copytree(defaults / 'static', app / 'static')
        dependencies = (repo / 'backend/requirements.txt').read_text().splitlines()
        (context / 'requirements.txt').write_text('\n'.join(
            line for line in dependencies if not line.startswith(('coverage', 'pytest'))) + '\n')
        for name in ('pyproject.toml', 'LICENSE'):
            shutil.copy2(repo / name, context / name)
        for name in ('Dockerfile', 'prepare.py'):
            shutil.copy2(PACKAGE / name, context / name)
        shutil.copy2(PACKAGE_ROOT / '_shared/compile_backend.py', context / 'compile_backend.py')
        shutil.copy2(PACKAGE_ROOT / '_shared/audit_release.py', context / 'audit_release.py')
        shutil.copytree(PACKAGE_ROOT / '_shared/obfuscation', context / 'obfuscation')
        (context / 'nginx').mkdir()
        shutil.copy2(repo / 'nginx/nginx-prod.conf', context / 'nginx/nginx.conf')
        (context / 'nginx/docs.conf').write_text('events {}\nhttp { include /etc/nginx/mime.types; server { listen 80; root /usr/share/nginx/html; index index.html; } }\n')
        (context / 'compose.json').write_text(json.dumps(deployment(repo)))
        command = ['docker', 'build', '--tag', image]
        for name in ('DOCUMENTATION_PROJECT_NAME', 'DOCUMENTATION_COMPANY_NAME'):
            if os.environ.get(name):
                command.extend(['--build-arg', f'{name}={os.environ[name]}'])
        run(*command, str(context))


def validate_settings(settings):
    for key in ('S_SUPER_PASSWORD_V1', 'S_CRAWLER_PASSWORD', 'MONGO_ROOT_USERNAME', 'MONGO_ROOT_PASSWORD',
                'ELASTIC_ROOT_PASSWORD', 'ARANGO_PASSWORD', 'REDIS_PASSWORD'):
        if not settings.get(key) or '{value}' in settings[key]:
            raise ValueError(f'Configure {key}; use existing credentials when reusing data')
    if len(settings.get('JWT_SECRET_KEY', '')) < 32:
        raise ValueError('JWT_SECRET_KEY must contain at least 32 characters')
    if len(base64.b64decode(settings.get('ENCRYPTION_KEY', ''), altchars=b'-_', validate=True)) != 32:
        raise ValueError('ENCRYPTION_KEY must be the existing valid Fernet key')
    if settings.get('ARANGO_USERNAME') != 'root':
        raise ValueError('ARANGO_USERNAME must match the provisioned Arango root user')
    url = urlsplit(settings.get('APP_URL', ''))
    base = settings.get('TENANT_BASE_DOMAIN', '')
    mail = settings.get('MAIL_DOMAIN', 'mail.' + base)
    for host in (url.hostname or '', base, mail):
        if len(host) > 253 or '.' not in host or not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label) for label in host.split('.')):
            raise ValueError('APP_URL, TENANT_BASE_DOMAIN and MAIL_DOMAIN must contain valid DNS hostnames')
    if (url.scheme != 'https' or url.netloc != url.hostname or url.path not in ('', '/')
            or url.query or url.fragment or not url.hostname.endswith('.' + base)):
        raise ValueError('APP_URL must be an HTTPS subdomain of TENANT_BASE_DOMAIN without a port or path')
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]*', settings.get('LETSENCRYPT_CERT_NAME', 'try.orionintelligence.org')):
        raise ValueError('LETSENCRYPT_CERT_NAME must be a plain certificate name')
    for key in ('APP_UID', 'APP_GID'):
        if not settings.get(key, '1000').isdigit() or int(settings.get(key, '1000')) <= 0:
            raise ValueError(f'{key} must be a non-root numeric ID')


def render_nginx(source, settings):
    replacements = {
        '/etc/letsencrypt/live/try.orionintelligence.org/': '/etc/letsencrypt/live/' + settings.get('LETSENCRYPT_CERT_NAME', 'try.orionintelligence.org') + '/',
        'mail.orionintelligence.org': settings.get('MAIL_DOMAIN', 'mail.' + settings['TENANT_BASE_DOMAIN']),
        'try.orionintelligence.org': urlsplit(settings['APP_URL']).hostname,
        'orionintelligence.org': settings['TENANT_BASE_DOMAIN'],
    }
    return re.sub('|'.join(map(re.escape, replacements)), lambda match: replacements[match[0]], source)


def check_existing(config):
    ids = run('docker', 'ps', '--all', '--filter', f'label=com.docker.compose.project={PROJECT}',
              '--format', '{{.ID}}', capture_output=True, text=True).stdout.split()
    if not ids:
        return
    containers = json.loads(run('docker', 'inspect', *ids, capture_output=True, text=True).stdout)
    keys = {'web': ('ENCRYPTION_KEY', 'JWT_SECRET_KEY', 'MONGO_ROOT_PASSWORD', 'ELASTIC_ROOT_PASSWORD', 'ARANGO_PASSWORD', 'REDIS_PASSWORD'),
            'mongo': ('MONGO_INITDB_ROOT_USERNAME', 'MONGO_INITDB_ROOT_PASSWORD'),
            'elasticsearch': ('ELASTIC_PASSWORD',), 'arangodb': ('ARANGO_ROOT_PASSWORD',)}
    for container in containers:
        name = container['Config']['Labels'].get('com.docker.compose.service')
        if name not in config['services']:
            continue
        desired = config['services'][name]
        for volume in desired.get('volumes', []):
            if volume['type'] != 'volume':
                continue
            expected = config['volumes'][volume['source']]['name']
            previous = next((item.get('Name') for item in container['Mounts'] if item['Destination'] == volume['target']), None)
            if previous and previous != expected:
                raise RuntimeError(f'{name}: existing volume {previous} differs from {expected}; migrate explicitly, do not replace a test/development stack')
        previous_env = dict(item.split('=', 1) for item in container['Config'].get('Env', []) if '=' in item)
        for key in keys.get(name, ()):
            if previous_env.get(key) and previous_env[key] != desired.get('environment', {}).get(key):
                raise RuntimeError(f'{name}: {key} differs from the existing deployment; preserve its credentials')


def check_ports():
    listeners = run('ss', '-H', '-ltn', '( sport = :80 or sport = :443 )', capture_output=True, text=True).stdout
    if not listeners.strip():
        return
    existing = subprocess.run(['docker', 'inspect', 'trusted-web-nginx'], capture_output=True, text=True)
    owned = set()
    if existing.returncode == 0:
        container = json.loads(existing.stdout)[0]
        if container['Config'].get('Labels', {}).get('com.docker.compose.project') == PROJECT:
            owned = {binding['HostPort'] for bindings in container['NetworkSettings'].get('Ports', {}).values()
                     for binding in (bindings or [])}
    for line in listeners.splitlines():
        port = line.split()[3].rsplit(':', 1)[-1]
        if port not in owned:
            raise RuntimeError(f'Port {port} is already occupied outside the existing Orion edge proxy')


def unpack(payload, destination):
    with tarfile.open(fileobj=io.BytesIO(payload)) as archive:
        total = 0
        for member in archive.getmembers():
            path = Path(member.name)
            total += member.size
            if (path.is_absolute() or '..' in path.parts or not (member.isfile() or member.isdir())
                    or (path.parts and path.parts[0] not in {'nginx', 'docs', 'client'})
                    or member.size > 128 * 1024 * 1024 or total > 1024 * 1024 * 1024):
                raise ValueError(f'Unexpected published asset: {member.name}')
        destination.mkdir(parents=True, exist_ok=True)
        archive.extractall(destination, filter='data')


def pull(env_file, image):
    runtime = env_file.parent / '.runtime'
    run('docker', 'pull', image)
    run(sys.executable, '-B', str(PACKAGE_ROOT / 'pull/_shared/deployment.py'), '--apply', env_file.parent.name)
    run(sys.executable, '-B', str(env_file.parent / 'fill_env.py'))
    run(sys.executable, '-B', str(env_file.parent / 'setup.py'))
    digest = run('docker', 'image', 'inspect', '--format', '{{.Id}}', image, capture_output=True, text=True).stdout.strip()
    if not re.fullmatch(r'sha256:[a-f0-9]{64}', digest):
        raise ValueError('Unexpected application image ID')
    assets = runtime / digest.split(':')[1]
    manifest = run('docker', 'run', '--rm', '--network', 'none', '--entrypoint', 'cat',
                   image, '/opt/orion/compose.json', capture_output=True, text=True).stdout
    config = json.loads(manifest)
    if config.get('name') != PROJECT or any(config['services'][name]['image'] != IMAGE for name in ('web', 'cron')):
        raise ValueError('Unexpected Intelligence deployment manifest')
    nginx_service = config['services']['nginx']
    web_service = config['services']['web']
    web_service['healthcheck']['test'] = ['CMD-SHELL', 'host="$${APP_URL#https://}"; host="$${host%%/*}"; '
                                          'curl --fail --silent --header "Host: $$host" http://127.0.0.1:8070/api/public > /dev/null']
    nginx_service['depends_on'] = {name: {'condition': 'service_started'} for name in ('web', 'documentation')}
    nginx_service['healthcheck']['test'] = ['CMD', 'nginx', '-t']
    for volume in nginx_service['volumes']:
        if volume['target'] == '/etc/nginx/nginx.conf':
            volume['source'] = '${ORION_INTELLIGENCE_NGINX:?Set the rendered nginx configuration}'
    manifest = json.dumps(config)
    environment = dict(os.environ, ORION_PACKAGE_IMAGE=image, ORION_ENV_FILE=str(env_file), ORION_INTELLIGENCE_ASSETS=str(assets),
                       ORION_INTELLIGENCE_NGINX=str(assets / 'nginx/nginx.conf'))
    environment.setdefault('ORION_SOURCE_DIR', str(PACKAGE_ROOT.parent / 'Orion-Intelligence'))
    with tempfile.TemporaryDirectory(prefix='orion-intelligence-pull-') as directory:
        compose_file = Path(directory) / 'compose.json'
        compose_file.write_text(manifest)
        command = ['docker', 'compose', '--project-name', PROJECT, '--env-file', str(env_file),
                   '--project-directory', str(env_file.parent), '--file', str(compose_file)]
        def compose(*args, **kwargs):
            return run(*command, *args, env=environment, **kwargs)
        resolved = json.loads(compose('config', '--format', 'json', capture_output=True, text=True).stdout)
        settings = resolved['services']['web']['environment']
        validate_settings(settings)
        check_existing(resolved)
        check_ports()
        nginx = resolved['services']['nginx']
        certificate = next(item['source'] for item in nginx['volumes'] if item['target'] == '/etc/letsencrypt')
        if not Path(certificate).is_dir():
            raise RuntimeError('Provision the existing production Let’s Encrypt certificate and renewal job first')
        run('docker', 'run', '--rm', '--network', 'none', '--read-only', '--user', '0:0',
            '--mount', f'type=bind,src={certificate},dst=/etc/letsencrypt,readonly', '--env',
            'APP_URL=' + settings['APP_URL'], '--env', 'TENANT_BASE_DOMAIN=' + settings['TENANT_BASE_DOMAIN'],
            '--env', 'MAIL_DOMAIN=' + settings.get('MAIL_DOMAIN', 'mail.' + settings['TENANT_BASE_DOMAIN']),
            '--env', 'LETSENCRYPT_CERT_NAME=' + settings.get('LETSENCRYPT_CERT_NAME', 'try.orionintelligence.org'),
            '--entrypoint', 'python3', image, '-c',
            "import os,ssl,subprocess; from urllib.parse import urlsplit; "
            "p='/etc/letsencrypt/live/'+os.environ['LETSENCRYPT_CERT_NAME']; c=p+'/fullchain.pem'; "
            "hosts=[urlsplit(os.environ['APP_URL']).hostname,os.environ['MAIL_DOMAIN'],'setup-check.'+os.environ['TENANT_BASE_DOMAIN']]; "
            "[subprocess.run(['openssl','x509','-in',c,'-noout','-checkhost',h],check=True) for h in hosts]; "
            "subprocess.run(['openssl','x509','-in',c,'-noout','-checkend','86400'],check=True); "
            "subprocess.run(['openssl','verify','-untrusted',c,c],check=True); "
            "ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER).load_cert_chain(c,p+'/privkey.pem')")
        compose('pull')
        if not (assets / '.ready').is_file():
            payload = run('docker', 'run', '--rm', '--network', 'none', '--entrypoint', 'tar', image,
                          '-C', '/opt/orion/assets', '-cf', '-', '.', '-C', '/app/workspace',
                          '--transform=s,^build,client,', 'build', capture_output=True).stdout
            unpack(payload, assets)
            (assets / '.ready').touch()
        rendered = render_nginx((assets / 'nginx/nginx.conf').read_text(), settings)
        nginx_file = assets / 'nginx' / (hashlib.sha256(rendered.encode()).hexdigest() + '.conf')
        if not nginx_file.exists():
            nginx_file.write_text(rendered)
        environment['ORION_INTELLIGENCE_NGINX'] = str(nginx_file)
        for name in ('shared_bridge', 'orion_nexus_backend'):
            exists = subprocess.run(['docker', 'network', 'inspect', name], capture_output=True)
            if exists.returncode:
                run('docker', 'network', 'create', '--driver', 'bridge', name)
        for volume in resolved['services']['web']['volumes']:
            if volume['type'] == 'bind':
                Path(volume['source']).mkdir(parents=True, exist_ok=True)
        compose('run', '--rm', '--no-deps', '--user', '0:0', '--cap-add', 'CHOWN', '--cap-add', 'DAC_OVERRIDE',
                '--cap-add', 'FOWNER', 'web', 'prepare')
        compose('run', '--rm', '--no-deps', 'web', 'check-storage')
        compose('run', '--rm', '--no-deps', 'nginx', 'nginx', '-t')
        try:
            compose('up', '--detach', '--no-build', '--wait', '--wait-timeout', '900',
                    'web', 'cron', 'documentation', 'mongo', 'elasticsearch', 'arangodb', 'redis_server', 'nginx')
        except subprocess.CalledProcessError:
            failure('Intelligence services did not become healthy',
                    'Read the health output and service logs below, correct the first application error, then rerun ./pull.sh.')
            subprocess.run([*command, 'ps', '--all'], env=environment)
            subprocess.run(['docker', 'inspect', '--format', '{{json .State.Health}}', 'trusted-web-main'], env=environment)
            subprocess.run(['docker', 'logs', '--tail', '200', 'trusted-web-main'], env=environment)
            subprocess.run(['docker', 'logs', '--tail', '100', 'trusted-web-nginx'], env=environment)
            raise
        runtime.mkdir(parents=True, exist_ok=True)
        (runtime / 'compose.json').write_text(manifest)
        print('Intelligence deployed. Keep the existing Let’s Encrypt renewal job enabled; nginx reloads every 12 hours.')


if __name__ == '__main__':
    try:
        action, location, image = sys.argv[1:]
        if action not in {'build', 'pull'}:
            raise ValueError('Use build or pull')
        (build if action == 'build' else pull)(Path(location).resolve(), image)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        failure(f'Intelligence packaging failed: {error}', 'Correct the reported failure and rerun ./pull.sh; existing data volumes are preserved.')
        sys.exit(1)
