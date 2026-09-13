from pathlib import Path
import sys


def audit(root):
    root = Path(root)
    leaked = []
    for file in root.rglob('*'):
        if not file.is_file():
            continue
        relative = file.relative_to(root)
        if 'node_modules' in relative.parts:
            continue
        if (file.suffix in {'.py', '.pyc', '.pyo', '.pyx', '.pxd', '.pyi', '.c', '.h', '.o', '.ts', '.tsx', '.jsx', '.sh', '.bash', '.zsh', '.ipynb', '.vue', '.svelte', '.coffee'}
                or file.name.endswith(('.js.map', '.mjs.map', '.css.map', '-source.zip'))
                or '.git' in relative.parts or file.name == '.env' or file.name.startswith('.env.')):
            leaked.append(str(relative))
        elif file.suffix in {'.js', '.mjs', '.cjs'}:
            prefix = file.read_bytes()[:128]
            if not prefix.startswith(b'/*! orion-protected:'):
                leaked.append(str(relative))
    if leaked:
        raise ValueError('Unprotected source/debug files in release: ' + ', '.join(leaked[:20]))


if __name__ == '__main__':
    for directory in sys.argv[1:]:
        audit(directory)
    print('Release source checks passed.')
