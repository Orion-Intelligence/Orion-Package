SLUG = 'micros'
PORT = 8010
MODULE = 'server:app'
PROJECT = 'trusted-micros'
COMPOSE = 'docker-compose.yml'
REQUIRED_ENV = ('REDIS_PASSWORD', 'FULL_SCAN_ZAP_API_KEY', 'TOR_PASSWORD')


def configure(config):
    services = config['services']
    clamav = services['clamav']
    clamav['image'] = 'clamav/clamav:1.5.4@sha256:0af8760cd96f9ab67d07977af36e155431581a9fe9f0ec8b256c9f855fda183e'
    clamav['deploy']['resources']['limits']['memory'] = '3221225472'
    clamav['healthcheck'] = {
        'test': ['CMD', 'clamdcheck.sh'],
        'interval': '15s',
        'timeout': '10s',
        'retries': 20,
        'start_period': '6m',
    }
    environment = clamav.get('environment', {})
    if isinstance(environment, dict):
        environment.pop('CLAMD_SOCKET', None)
    else:
        clamav['environment'] = [value for value in environment
                                 if not value.startswith('CLAMD_SOCKET=')]
    for service in (services['api'], clamav):
        service['volumes'] = [volume for volume in service.get('volumes', [])
                              if volume['target'] != '/var/run/clamav']
    config.get('volumes', {}).pop('clamav_socket', None)
    services['api'].setdefault('volumes', []).append({
        'type': 'bind', 'source': '${ORION_RUNTIME_DIR:-${ORION_SOURCE_DIR}}/app/raw/netintel',
        'target': '/app/raw/netintel'})
    services['tor-extend-1']['healthcheck']['test'] = [
        'CMD-SHELL', 'curl --fail --max-time 15 --proxy socks5h://localhost:9352 https://check.torproject.org/api/ip >/dev/null']
