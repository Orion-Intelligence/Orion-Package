from pathlib import Path

SLUG = 'dark-nexus'
PORT = 8030
MODULE = 'api.server:app'
COMMAND = ['uvicorn', 'api.fastapi_app.app:create_fastapi_app', '--factory',
           '--host', '0.0.0.0', '--port', '8030']
PROJECT = 'orion-model-gateway'
COMPOSE = 'docker-compose.prod.yml'
BASE_IMAGE = 'python:3.13-slim'
COMPILER_PACKAGES = 'gcc libc6-dev python3-dev'
RELEASE = 'USER 65534:65534\n'
INFERENCE_PACKAGES = {
    'mpmath', 'networkx', 'sympy', 'torch', 'triton',
}


def ignore(directory, names, default):
    excluded = default(directory, names)
    if Path(directory).name == 'api' and 'mcp2' in names:
        excluded.append('mcp2')
    return excluded


def configure_runtime(config):
    services = config['services']
    for name in tuple(services):
        if name not in {'api', 'mongo'}:
            services.pop(name)
    api = services['api']
    api['runtime'] = 'runc'
    api['command'] = ['uvicorn', 'api.fastapi_app.app:create_fastapi_app', '--factory',
                      '--host', '0.0.0.0', '--port', '8030']
    api.setdefault('environment', {}).update({
        'AI_PRODUCTION': '0',
        'GPU_ENABLED': 'false',
        'NVIDIA_VISIBLE_DEVICES': 'void',
        'LLM_URL': 'http://127.0.0.1:1',
        'LLM_CHAT_URL': 'http://127.0.0.1:1',
        'OLLAMA_BASE_URL': 'http://127.0.0.1:1',
        'DEFAULT_MODEL': 'disabled',
        'OPENAI_API_KEY': '',
        'OPENROUTER_API_KEY': '',
        'LIVE_LLM_API_KEY': '',
        'SANDBOX_MANAGER_URL': 'http://127.0.0.1:1',
    })
    api.setdefault('depends_on', {}).pop('sandbox_manager', None)
    networks = api.get('networks', {})
    if isinstance(networks, dict):
        networks.pop('sandbox_api', None)
    else:
        api['networks'] = [network for network in networks
                           if network != 'sandbox_api']
    for name in ('model_egress', 'sandbox_api', 'sandbox_egress'):
        config.get('networks', {}).pop(name, None)
    config.get('volumes', {}).pop('model_engine_data', None)


def configure(config):
    configure_runtime(config)


def configure_pull(config):
    configure_runtime(config)


def keep_dependency(line):
    if not line or line.startswith('#'):
        return True
    name = line.split()[0].split('==')[0].lower()
    return not name.startswith('nvidia-') and name not in INFERENCE_PACKAGES


def prepare(context, _repo, _ignored, _run):
    for filename in ('requirements.txt', 'requirements.lock'):
        path = context / 'app' / filename
        lines = path.read_text().splitlines()
        path.write_text('\n'.join(line for line in lines if keep_dependency(line)) + '\n')
