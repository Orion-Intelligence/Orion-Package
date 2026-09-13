#!/usr/bin/env python3
import getpass
import os
from pathlib import Path
import stat
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
    directory = os.environ.get('ORION_GITHUB_AUTH_DIR')
    cached = Path(directory) / 'token' if directory else None
    if cached is not None:
        details = cached.parent.lstat()
        if not stat.S_ISDIR(details.st_mode) or details.st_uid != os.getuid() or details.st_mode & 0o077:
            raise ValueError('Unsafe GitHub credential directory')
        try:
            descriptor = os.open(cached, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            pass
        else:
            with os.fdopen(descriptor) as stored:
                details = os.fstat(stored.fileno())
                if not stat.S_ISREG(details.st_mode) or details.st_uid != os.getuid() or details.st_mode & 0o077:
                    raise ValueError('Unsafe GitHub credential file')
                token = stored.read()
            if not token or any(character.isspace() for character in token):
                raise ValueError('Invalid cached GitHub token')
            print(token)
            return 0
    warnings.simplefilter('error', getpass.GetPassWarning)
    token = getpass.getpass('GitHub PAT for all selected repositories (once per push; hidden): ')
    if not token or any(character.isspace() for character in token):
        return 1
    if cached is not None:
        descriptor = os.open(cached, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, 'w') as stored:
            stored.write(token)
    print(token)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (EOFError, KeyboardInterrupt, OSError, ValueError, getpass.GetPassWarning):
        print('GitHub PAT entry cancelled or unavailable; run push.sh in a terminal.', file=sys.stderr)
        sys.exit(1)
