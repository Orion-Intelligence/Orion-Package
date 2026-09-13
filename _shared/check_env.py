"""Refuse unconfigured deployments without printing any credential values."""
from pathlib import Path
import re
import sys


def check_env(path: Path) -> None:
    if not path.is_file():
        raise ValueError(f'{path}: copy template-env to .env and configure it first')
    missing = []
    for line in path.read_text().splitlines():
        match = re.match(r'^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$', line)
        if match and '{value}' in match[2]:
            missing.append(match[1])
    if missing:
        raise ValueError(f'{path}: replace {{value}} for: {", ".join(missing)}')


if __name__ == '__main__':
    failed = False
    for filename in sys.argv[1:]:
        try:
            check_env(Path(filename))
        except (OSError, ValueError) as error:
            print(error, file=sys.stderr)
            failed = True
    sys.exit(int(failed))
