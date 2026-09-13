import json
import os
from pathlib import Path
import resource
import socket
import subprocess
import sys
import tempfile
import threading


def request(action, key, value=None):
    address = os.environ.get('ORION_SESSION_SOCKET')
    if not address:
        raise ValueError('Run push.sh or pull.sh to start a private credential session')
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(15)
        connection.connect(address)
        stream = connection.makefile('rwb')
        stream.write(json.dumps([action, key, value]).encode() + b'\n')
        stream.flush()
        result = json.loads(stream.readline(1024 * 1024))
        if not result['ok']:
            raise ValueError('Credential session request failed')
        return result['value']


def serve(listener, stop):
    values = {}
    listener.settimeout(0.5)
    while not stop.is_set():
        try:
            connection, _ = listener.accept()
        except socket.timeout:
            continue
        with connection:
            connection.settimeout(5)
            try:
                stream = connection.makefile('rwb')
                action, key, value = json.loads(stream.readline(1024 * 1024))
                if action == 'set':
                    values[key] = value
                elif action == 'delete':
                    values.pop(key, None)
                elif action != 'get':
                    raise ValueError('Unknown action')
                result = values.get(key) if action == 'get' else None
                stream.write(json.dumps({'ok': True, 'value': result}).encode() + b'\n')
                stream.flush()
            except (OSError, ValueError, TypeError, KeyError):
                pass
    values.clear()


def run_session(action, modules):
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    shared = Path(__file__).resolve().parent
    original = Path(os.environ.get('DOCKER_CONFIG', str(Path.home() / '.docker')))
    with tempfile.TemporaryDirectory(prefix='orion-session-') as temporary:
        directory = Path(temporary)
        docker = directory / 'docker'
        docker.mkdir(mode=0o700)
        settings = {}
        if (original / 'config.json').is_file():
            previous = json.loads((original / 'config.json').read_text())
            settings = {key: previous[key] for key in ('currentContext', 'experimental', 'features', 'detachKeys') if key in previous}
        settings['credsStore'] = 'orion'
        (docker / 'config.json').write_text(json.dumps(settings))
        for name in ('contexts', 'cli-plugins', 'buildx'):
            if (original / name).is_dir():
                (docker / name).symlink_to((original / name).resolve(), target_is_directory=True)
        address = str(directory / 'credentials.sock')
        environment = dict(os.environ, ORION_SESSION_SOCKET=address, DOCKER_CONFIG=str(docker),
                           PATH=str(shared) + os.pathsep + os.environ.get('PATH', ''),
                           ORION_IMAGE_NAMESPACE=os.environ.get('ORION_IMAGE_NAMESPACE', 'msmannan00'))
        environment.pop('ORION_GITHUB_AUTH_DIR', None)
        stop = threading.Event()
        with socket.socket(socket.AF_UNIX) as listener:
            listener.bind(address)
            listener.listen()
            worker = threading.Thread(target=serve, args=(listener, stop), daemon=True)
            worker.start()
            try:
                result = subprocess.run(['bash', '-c',
                    'source "$1"; ACTION="$2"; shift 2; run_selected "$@"',
                    'orion-session', str(shared / 'common.sh'), action, *modules], env=environment)
                return result.returncode
            finally:
                stop.set()
                worker.join(timeout=6)


if __name__ == '__main__':
    try:
        sys.exit(run_session(sys.argv[1], sys.argv[2:]))
    except KeyboardInterrupt:
        sys.exit(130)
    except (OSError, ValueError) as error:
        print(f'Credential session failed: {error}', file=sys.stderr)
        sys.exit(1)
