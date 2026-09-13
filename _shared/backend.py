import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

PACKAGE = Path(__file__).resolve().parent


def profile(directory):
    spec = importlib.util.spec_from_file_location('repo_config', directory / 'config.py')
    if spec is None or spec.loader is None:
        raise RuntimeError(f'Cannot load repository configuration: {directory}')
    config = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(config)
    return config


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def service_diagnostics(configure, config):
    for service in getattr(configure, 'RECOVERABLE_SERVICES', {}):
        container = config['services'][service].get('container_name')
        if not container:
            continue
        print(f'{service}: container status and recent logs', file=sys.stderr)
        subprocess.run(('docker', 'inspect', '--format',
                        'Image={{.Config.Image}} Memory={{.HostConfig.Memory}} Status={{.State.Status}} OOMKilled={{.State.OOMKilled}} Restarts={{.RestartCount}} Health={{if .State.Health}}{{.State.Health.Status}}{{end}}',
                        container), check=False)
        subprocess.run(('docker', 'logs', '--tail', '150', container), check=False)


def prepare_recoverable_services(configure, config, command, env):
    recoverable = getattr(configure, 'RECOVERABLE_SERVICES', {})
    if not recoverable:
        return
    services = tuple(recoverable)
    start = (*command, 'up', '--detach', '--no-build', '--wait', '--wait-timeout', '720', *services)
    try:
        run(*start, env=env)
        return
    except subprocess.CalledProcessError:
        service_diagnostics(configure, config)
    print('ClamAV did not become healthy; rebuilding its disposable signature cache and retrying.', file=sys.stderr)
    for service, volumes in recoverable.items():
        subprocess.run((*command, 'rm', '--stop', '--force', service), env=env, check=False)
        for volume in volumes:
            subprocess.run(('docker', 'volume', 'rm', f'{config["name"]}_{volume}'), check=False)
    try:
        run(*command, 'up', '--detach', '--no-build', '--force-recreate', '--wait',
            '--wait-timeout', '720', *services, env=env)
    except subprocess.CalledProcessError:
        service_diagnostics(configure, config)
        raise


def deployment(configure, repo):
    result = run('docker', 'compose', '--env-file', '/dev/null', '--file', str(repo / configure.COMPOSE),
                 'config', '--no-interpolate', '--no-env-resolution', '--no-path-resolution',
                 '--format', 'json', capture_output=True, text=True)
    config = json.loads(result.stdout)
    config['name'] = configure.PROJECT

    for group in ('networks', 'volumes'):
        for resource in config.get(group, {}).values():
            if not resource.get('external'):
                resource.pop('name', None)
    services = config['services']
    for service in services.values():
        if 'build' in service:
            del service['build']
            service['image'] = '${ORION_PACKAGE_IMAGE:?Select the application image}'
            service.pop('pull_policy', None)
        if 'env_file' in service:
            service['env_file'] = ['${ORION_ENV_FILE:?Set the runtime env file}']

        volumes = []
        for volume in service.get('volumes', []):
            target = volume['target']
            if target in {'/app/api', '/app/orion', '/app/raw', '/app/social-automation',
                          '/app/social-automation/node_modules', '/etc/tor/torrc'}:
                continue
            if target == '/app/sessions':
                volume['source'] = '${ORION_RUNTIME_DIR:-${ORION_SOURCE_DIR}}/sessions'
            volumes.append(volume)
        if volumes:
            service['volumes'] = volumes
        else:
            service.pop('volumes', None)
    api = services['api']
    api.setdefault('environment', {})['PYTHONPATH'] = '/app'
    api['healthcheck'] = {'test': ['CMD', 'python', '-c',
        f"import urllib.request; urllib.request.urlopen('http://127.0.0.1:{configure.PORT}/openapi.json', timeout=5).read()"],
        'interval': '30s', 'timeout': '10s', 'retries': 5, 'start_period': '120s'}
    configure.configure(config)
    encoded = json.dumps(config)
    for key in getattr(configure, 'REQUIRED_ENV', ()):
        encoded = encoded.replace('${' + key + '}', '${' + key + ':?Set ' + key + ' in the runtime env file}')
    return json.loads(encoded)


def ignored(directory, names):
    banned = {'.git', '.venv', 'venv', '__pycache__', 'node_modules', '.cache', 'sessions',
              'tests', 'probe', 'probe_manager', '_stress', 'training', '.pytest_cache'}
    return [name for name in names if name in banned or name.startswith('.env')
            or name.endswith(('.pyc', '.pyo', '.log', '.pem', '.key'))]


def build(configure, repo, image):
    dockerfile = (repo / 'dockerFiles/app_docker').read_text()
    boundary = 'COPY app /app'
    if dockerfile.count(boundary) != 1:
        raise RuntimeError('Review upstream Dockerfile: application COPY changed')
    prefix = dockerfile.split(boundary)[0]
    lines = prefix.splitlines()
    first = next(index for index, line in enumerate(lines) if line.startswith('FROM '))
    lines[first] += ' AS runtime'
    prefix = '\n'.join(lines) + '\n'
    with tempfile.TemporaryDirectory(prefix=f'orion-{configure.SLUG}-build-') as directory:
        context = Path(directory)
        def ignore(directory, names):
            return configure.ignore(directory, names, ignored) if hasattr(configure, 'ignore') else ignored(directory, names)

        shutil.copytree(repo / 'app', context / 'app', ignore=ignore)
        shutil.copy2(PACKAGE / 'compile_backend.py', context / 'compile_backend.py')
        shutil.copy2(PACKAGE / 'audit_release.py', context / 'audit_release.py')
        if configure.SLUG == 'social':
            shutil.copytree(PACKAGE / 'obfuscation', context / 'obfuscation')
        prepare = Path(configure.__file__).parent / 'prepare.py'
        if prepare.is_file():
            shutil.copy2(prepare, context / 'prepare.py')
        else:
            (context / 'prepare.py').touch()
        if hasattr(configure, 'prepare'):
            configure.prepare(context, repo, ignore, run)
        config = deployment(configure, repo)
        (context / 'compose.json').write_text(json.dumps(config, indent=2))
        for filename in ('LICENSE', 'LICENSE.md', 'LICENSE.txt', 'NOTICE'):
            if (repo / filename).is_file():
                shutil.copy2(repo / filename, context / 'app' / filename)
        compiler_packages = getattr(configure, 'COMPILER_PACKAGES', 'gcc libc6-dev')
        suffix = f'''
FROM runtime AS compiler
USER root
RUN apt-get update && apt-get install -y --no-install-recommends {compiler_packages} \\
 && pip install --no-cache-dir Cython==3.3.0 setuptools==84.0.0
WORKDIR /build
COPY app/ /build/app/
COPY compile_backend.py audit_release.py /build/
COPY prepare.py /build/prepare.py
RUN python /build/compile_backend.py

FROM runtime AS release
WORKDIR /app
COPY --from=compiler /release/ /app/
COPY compose.json /opt/orion/compose.json
ENV PYTHONPATH=/app
EXPOSE {configure.PORT}
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=5 \\
 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:{configure.PORT}/openapi.json', timeout=5).read()"
'''
        if configure.SLUG == 'social':
            suffix = suffix.replace('COPY prepare.py /build/prepare.py', 'COPY prepare.py /build/prepare.py\nCOPY obfuscation/ /build/obfuscation/')
        suffix += getattr(configure, 'RELEASE', '')
        suffix += 'CMD ' + json.dumps(['uvicorn', configure.MODULE, '--host', '0.0.0.0', '--port', str(configure.PORT)]) + '\n'
        (context / 'Dockerfile').write_text(prefix + suffix)
        run('docker', 'build', '--tag', image, str(context))


def pull(configure, env_file, image):
    env_file = env_file.resolve()
    run('docker', 'pull', image)
    run(sys.executable, '-B', str(PACKAGE.parent / 'pull/_shared/deployment.py'), '--apply', env_file.parent.name)
    run(sys.executable, '-B', str(env_file.parent / 'fill_env.py'))
    run(sys.executable, '-B', str(env_file.parent / 'setup.py'))
    if hasattr(configure, 'check_runtime'):
        configure.check_runtime()
    manifest = run('docker', 'run', '--rm', '--network', 'none', '--entrypoint', '/bin/cat',
                   image, '/opt/orion/compose.json', capture_output=True, text=True).stdout
    config = json.loads(manifest)
    if hasattr(configure, 'configure_pull'):
        configure.configure_pull(config)
        manifest = json.dumps(config)
    if config['services']['api']['image'] != '${ORION_PACKAGE_IMAGE:?Select the application image}':
        raise RuntimeError('Unexpected deployment manifest')
    runtime = env_file.parent / '.runtime'
    runtime.mkdir(parents=True, exist_ok=True)
    (runtime / 'compose.json').write_text(manifest)
    env = dict(os.environ, ORION_ENV_FILE=str(env_file), ORION_PACKAGE_IMAGE=image)
    env.setdefault('ORION_SOURCE_DIR', str(PACKAGE.parents[1] / Path(configure.__file__).parent.name))
    with tempfile.TemporaryDirectory(prefix=f'orion-{configure.SLUG}-pull-') as directory:
        compose = Path(directory) / 'compose.json'
        compose.write_text(manifest)
        command = ['docker', 'compose', '--env-file', str(env_file), '--project-directory', str(env_file.parent),
                   '--file', str(compose)]
        run(*command, 'config', '--quiet', env=env)
        run(*command, 'pull', env=env)
        prepare_recoverable_services(configure, config, command, env)
        try:
            run(*command, 'up', '--detach', '--no-build', '--wait', '--wait-timeout', '900', env=env)
        except subprocess.CalledProcessError:
            service_diagnostics(configure, config)
            raise


if __name__ == '__main__':
    try:
        action, repo_package, location, image = sys.argv[1:]
        if action not in {'build', 'pull'}:
            raise ValueError('Unsupported backend action')
        (build if action == 'build' else pull)(profile(Path(repo_package).resolve()), Path(location).resolve(), image)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f'Packaging failed: {error}', file=sys.stderr)
        sys.exit(1)
