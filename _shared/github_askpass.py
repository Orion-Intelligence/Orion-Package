#!/usr/bin/env python3
import getpass
import re
import sys
import warnings
from urllib.parse import urlsplit


def main():
    prompt = sys.argv[1] if len(sys.argv) == 2 else ''
    match = re.fullmatch(r"(Username|Password) for '(https://[^']+)': ?", prompt)
    if not match:
        return 1
    address = urlsplit(match[2])
    if address.hostname != 'github.com' or address.port not in (None, 443):
        return 1
    if match[1] == 'Username':
        print('x-access-token')
        return 0
    warnings.simplefilter('error', getpass.GetPassWarning)
    token = getpass.getpass('GitHub PAT for trusted-main fetch (hidden; NOT Docker Hub PAT): ')
    if not token or any(character.isspace() for character in token):
        return 1
    print(token)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (EOFError, KeyboardInterrupt, OSError, ValueError, getpass.GetPassWarning):
        print('GitHub PAT entry cancelled or unavailable; run push.sh in a terminal.', file=sys.stderr)
        sys.exit(1)
