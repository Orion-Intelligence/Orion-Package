from pathlib import Path
import re
import sys


def check_env(path: Path) -> None:
    if not path.is_file():
        raise ValueError(f'{path}: create and configure this .env file first')
    missing = []
    for line in path.read_text().splitlines():
        match = re.match(r'^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$', line)
        if match and any(marker in match[2] for marker in ('{value}', '{value_auto}')):
            missing.append(match[1])
    if missing:
        raise ValueError(f'{path}: fill {{value}} / {{value_auto}} for: {", ".join(missing)}')


if __name__ == '__main__':
    failed = False
    for filename in sys.argv[1:]:
        try:
            check_env(Path(filename))
        except (OSError, ValueError) as error:
            print(error, file=sys.stderr)
            failed = True
    sys.exit(int(failed))
