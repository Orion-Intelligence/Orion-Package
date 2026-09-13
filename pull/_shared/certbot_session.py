import json
import os
import re
import resource
import subprocess
import sys


def main():
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    payload = json.load(sys.stdin)
    token = payload['token']
    if not re.fullmatch(r'[A-Za-z0-9_.-]{20,256}', token):
        raise ValueError('Invalid Cloudflare token format')
    descriptor = os.memfd_create('orion-cloudflare', os.MFD_CLOEXEC)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(os.dup(descriptor), 'w') as stream:
            stream.write('dns_cloudflare_api_token = ' + token + '\n')
        credentials = f'/proc/{os.getpid()}/fd/{descriptor}'
        result = subprocess.run(['certbot', 'certonly', '--dns-cloudflare',
            '--dns-cloudflare-credentials', credentials, '--dns-cloudflare-propagation-seconds', '60',
            '--no-autorenew', '--no-directory-hooks', *payload['args']])
        return result.returncode
    finally:
        os.close(descriptor)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except (OSError, ValueError, KeyError):
        print('Session-only certificate issuance failed; no API token was saved.', file=sys.stderr)
        sys.exit(1)
