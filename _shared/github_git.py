import os
from pathlib import Path
import re
import subprocess
import sys

from session import request


def main():
    environment = dict(os.environ, GIT_ASKPASS=str(Path(__file__).with_name('github_askpass.py')),
                       GIT_TERMINAL_PROMPT='0', LC_ALL='C')
    command = ['git', '-c', 'credential.helper=', '-c', 'core.askPass=', *sys.argv[1:]]
    while True:
        rejected = False
        cancelled = False
        with subprocess.Popen(command, env=environment, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True, errors='replace') as process:
            try:
                assert process.stdout is not None
                for line in process.stdout:
                    print(line, end='', flush=True)
                    rejected |= bool(re.search(
                        r'Authentication failed|Invalid username or token|Write access to repository not granted|requested URL returned error: (401|403)',
                        line, re.IGNORECASE))
                    cancelled |= 'GitHub PAT entry cancelled or unavailable' in line
                status = process.wait()
            except KeyboardInterrupt:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                return 130
        if status == 0 or not rejected or cancelled or status in (130, 143) or status < 0:
            return status if status >= 0 else 128 - status
        request('delete', 'github')
        print('GitHub rejected the PAT or repository access. Enter a different GitHub PAT with access to this repository, or press Ctrl+C to cancel.',
              file=sys.stderr, flush=True)
        entered = subprocess.run(
            [sys.executable, '-B', environment['GIT_ASKPASS'], "Password for 'https://github.com': "],
            env=environment, stdout=subprocess.DEVNULL,
        )
        if entered.returncode:
            return 130


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except (OSError, ValueError) as error:
        print(f'GitHub source operation failed: {error}', file=sys.stderr)
        sys.exit(1)
