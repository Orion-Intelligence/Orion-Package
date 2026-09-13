import copy
from pathlib import Path
import shutil
import subprocess
import sys

SLUG = 'dark-nexus'
PORT = 8030
MODULE = 'api.server:app'
PROJECT = 'orion-model-gateway'
COMPOSE = 'docker-compose.prod.yml'
COMPILER_PACKAGES = 'gcc libc6-dev python3-dev'
RELEASE = 'USER 65534:65534\n'


def ignore(directory, names, default):

    if Path(directory).name == 'probe_manager':
        return [name for name in names if name not in {'__init__.py', 'system_probe'}]
    if Path(directory).name == 'system_probe':
        return [name for name in names if name not in {'__init__.py', 'fixtures'}]
    excluded = default(directory, names)
    if Path(directory).name == 'api' and 'probe_manager' in excluded:
        excluded.remove('probe_manager')
    return excluded


def configure(config):
    services = config['services']
    manager = services['sandbox_manager']
    manager['user'] = '0:0'
    manager['command'] = ['uvicorn', 'dark_nexus_sandbox.sandbox_app:app', '--host', '0.0.0.0', '--port', '8090']
    manager.setdefault('environment', {})['PYTHONPATH'] = '/app'
    mcp = copy.deepcopy(services['api'])
    mcp['container_name'] = 'orion-mcp2'
    mcp['environment'].update(PYTHONPATH='/app:/app/api/mcp2', HEALTH_PORT='8300',
                              ORION_NEXUS_API_BASE='http://trusted-nexus-api:8030')
    mcp['command'] = ['python', '-c', 'from api.mcp2.server import main; main()']
    mcp['ports'] = ['127.0.0.1:8300:8300']
    mcp['depends_on'] = {'api': {'condition': 'service_healthy'}}
    mcp['healthcheck']['test'] = ['CMD', 'python', '-c',
        "import socket; socket.create_connection(('127.0.0.1',8300),5).close()"]
    services['mcp'] = mcp


def prepare(context, repo, ignored, run):
    run(sys.executable, '-B', str(repo / 'app/api/shared_services/model_manager.py'),
        '--destination', str(context / 'app/raw/validators/topic_classifier'))
    run('docker', 'build', '--file', str(repo / 'dockerFiles/app_base_docker'),
        '--tag', 'localhost/orion-nexus-kali-tools:local', str(repo))
    shutil.copytree(repo / 'sandbox/dark_nexus_sandbox', context / 'app/dark_nexus_sandbox', ignore=ignored)


def check_runtime():
    result = subprocess.run(['systemctl', 'is-active', '--quiet', 'orion-nexus-sandbox-manager-egress.service'])
    if result.returncode:
        raise RuntimeError('Provision the existing Dark Nexus sandbox egress firewall before deployment.')
