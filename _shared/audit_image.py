import subprocess
import sys


AUDIT = r'''
from pathlib import Path
import sys

module = sys.argv[1]
roots = {
    'intelligence': ('/app', '/opt/orion/assets'),
    'mail': ('/app', '/client_build', '/opt/orion/runtime'),
    'micros': ('/app',),
    'social': ('/app',),
    'dark-nexus': ('/app',),
    'tor2web': ('/opt/tor2web', '/usr/share/tor2web/data'),
}[module]
source = {'.py', '.pyc', '.pyo', '.pyx', '.pxd', '.pyi', '.c', '.h', '.o', '.ts', '.tsx', '.jsx',
          '.sh', '.bash', '.zsh', '.ipynb', '.vue', '.svelte', '.coffee'}
leaked = []
for root_name in roots:
    root = Path(root_name)
    if not root.exists():
        raise SystemExit(f'Missing protected image path: {root}')
    for file in root.rglob('*'):
        if not file.is_file() or 'node_modules' in file.parts:
            continue
        relative = str(file)
        if (file.suffix in source or file.name.endswith(('.js.map', '.mjs.map', '.css.map', '-source.zip'))
                or '.git' in file.parts or file.name == '.env' or file.name.startswith('.env.')):
            leaked.append(relative)
        elif file.suffix in {'.js', '.mjs', '.cjs'} and not file.read_bytes()[:128].startswith(b'/*! orion-protected:'):
            leaked.append(relative)
if leaked:
    raise SystemExit('Unprotected application files in final image: ' + ', '.join(leaked[:20]))
executables = {
    'mail': ('/usr/local/bin/mail-entrypoint', '/usr/local/bin/mail-incoming', '/usr/local/bin/postfix-entrypoint.sh'),
    'tor2web': ('/usr/local/bin/tor2web-entrypoint', '/usr/local/bin/tor-healthcheck', '/usr/local/bin/tor2web-stack'),
}.get(module, ())
for name in executables:
    if Path(name).read_bytes()[:4] != b'\x7fELF':
        raise SystemExit(f'Entrypoint is not an encoded native executable: {name}')
print(f'Final {module} image protection audit passed.')
'''


def main():
    if len(sys.argv) != 3:
        raise ValueError('Usage: audit_image.py IMAGE MODULE')
    image, module = sys.argv[1:]
    if module not in {'intelligence', 'mail', 'micros', 'social', 'dark-nexus', 'tor2web'}:
        raise ValueError('Unknown image profile')
    subprocess.run(['docker', 'run', '--rm', '--network', 'none', '--entrypoint', 'python3',
                    image, '-c', AUDIT, module], check=True)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f'Final image protection audit failed: {error}', file=sys.stderr)
        sys.exit(1)
