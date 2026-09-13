import ast
import copy
from pathlib import Path
import shutil
import sys

SLUG = 'dark-nexus'
PORT = 8030
MODULE = 'api.server:app'
PROJECT = 'orion-model-gateway'
COMPOSE = 'docker-compose.prod.yml'
COMPILER_PACKAGES = 'gcc libc6-dev python3-dev'
RELEASE = 'USER 65534:65534\n'


def ignore(directory, names, default):

    if Path(directory).name == 'system_probe':
        return [name for name in names if name == 'run_conformance.sh']
    if Path(directory).name == 'probe_manager':
        return [name for name in names if name not in {'__init__.py', 'system_probe'}]
    if Path(directory).name == 'system_probe':
        return [name for name in names if name not in {'__init__.py', 'fixtures'}]
    excluded = default(directory, names)
    if Path(directory).name == 'api' and 'probe_manager' in excluded:
        excluded.remove('probe_manager')
    return excluded


def configure_runtime(config):
    services = config['services']
    services.pop('sandbox_manager', None)
    for name in ('api', 'mcp'):
        if name not in services:
            continue
        service = services[name]
        service.setdefault('environment', {}).pop('SANDBOX_MANAGER_URL', None)
        service.setdefault('depends_on', {}).pop('sandbox_manager', None)
        networks = service.get('networks', {})
        if isinstance(networks, dict):
            networks.pop('sandbox_api', None)
        else:
            service['networks'] = [network for network in networks
                                   if network != 'sandbox_api']
    config.get('networks', {}).pop('sandbox_api', None)
    config.get('networks', {}).pop('sandbox_egress', None)


def configure(config):
    configure_runtime(config)
    services = config['services']
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


def configure_pull(config):
    configure_runtime(config)


def prepare(context, repo, ignored, run):
    manager = context / 'app/api/shared_services/model_manager.py'
    manifest = manager.with_name('topic_classifier.sha256')
    source_manifest = repo / 'app/api/shared_services/topic_classifier.sha256'
    if source_manifest.is_symlink():
        raise ValueError('Refusing unsafe topic-classifier manifest symlink')
    if not source_manifest.exists():
        pins = [node.value.value for node in ast.parse(manager.read_text()).body
                if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
                and any(isinstance(target, ast.Name) and target.id == 'ARCHIVE_SHA256' for target in node.targets)]
        if pins != ['b12a93e816327ab5941b24ae34d39ce2d1d56c43bfad19b1fee786eb365d21f0']:
            raise ValueError('Model archive pin changed; review the packaged checksum manifest before building')
        shutil.copy2(Path(__file__).with_name('topic_classifier.sha256'), manifest)
    run(sys.executable, '-B', str(manager),
        '--destination', str(context / 'app/raw/validators/topic_classifier'))
