import fcntl
import os
from pathlib import Path
import tempfile

from env_filler import Environment, MODULES


def prepare(root):
    runtime = root / '.runtime'
    runtime.mkdir(mode=0o700, exist_ok=True)
    with (runtime / 'env-fill.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        planned = []
        for module in MODULES:
            directory = root / module
            if directory.is_symlink():
                raise ValueError(f'{directory}: refuse a symlinked module directory')
            template = Environment(directory / 'env')
            target = directory / '.env'
            if target.is_symlink():
                raise ValueError(f'{target}: refuse a symlinked runtime environment')
            previous = Environment(target) if target.exists() else None
            lines = []
            for key in template.entries:
                document = previous if previous and key in previous.entries else template
                _, prefix, raw, comment = document.entries[key]
                lines.append(prefix + raw + comment + '\n')
            if previous:
                for key in previous.entries:
                    if key in template.entries:
                        continue
                    _, prefix, raw, comment = previous.entries[key]
                    lines.append(prefix + raw + comment + '\n')
            content = ''.join(lines)
            if previous is None or content != previous.original:
                planned.append((target, previous.original if previous else None, content))
            else:
                target.chmod(0o600)
        for target, original, content in planned:
            fd, temporary = tempfile.mkstemp(prefix='.env-', dir=target.parent)
            try:
                with os.fdopen(fd, 'w') as output:
                    output.write(content)
                    output.flush()
                    os.fsync(output.fileno())
                if original is None:
                    os.link(temporary, target)
                else:
                    if target.is_symlink() or target.read_text() != original:
                        raise ValueError(f'{target}: changed during preparation; retry')
                    os.replace(temporary, target)
                print(f'{target.parent.name}: prepared .env from env; existing values preserved')
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)


if __name__ == '__main__':
    prepare(Path(__file__).resolve().parents[1])
