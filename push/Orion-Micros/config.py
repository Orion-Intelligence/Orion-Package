SLUG = 'micros'
PORT = 8010
MODULE = 'server:app'
PROJECT = 'trusted-micros'
COMPOSE = 'docker-compose.yml'
REQUIRED_ENV = ('REDIS_PASSWORD', 'FULL_SCAN_ZAP_API_KEY', 'TOR_PASSWORD')


def configure(config):
    services = config['services']
    services['api'].setdefault('volumes', []).append({
        'type': 'bind', 'source': '${ORION_RUNTIME_DIR:-${ORION_SOURCE_DIR}}/app/raw/netintel',
        'target': '/app/raw/netintel'})
    services['tor-extend-1']['healthcheck']['test'] = [
        'CMD-SHELL', 'curl --fail --max-time 15 --proxy socks5h://localhost:9352 https://check.torproject.org/api/ip >/dev/null']
