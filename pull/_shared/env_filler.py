import argparse
import base64
import fcntl
import os
from pathlib import Path
import re
import secrets
import string
import sys
import tempfile
from urllib.parse import quote

AUTO = '{value_auto}'
MANUAL = '{value}'
MODULES = ('Orion-Intelligence', 'Orion-Micros', 'Orion-Social',
           'Orion-Dark-Nexus', 'Orion-mail', 'Orion-Tor2Web')
SHARED = {
    'S_SUPER_PASSWORD_V1': ('Orion-Intelligence', 'Orion-Micros', 'Orion-Social'),
    'ORION_SOCIAL_INTERNAL_TOKEN': ('Orion-Intelligence', 'Orion-Social'),
    'ORION_MAIL_SSO_CLIENT_SECRET': ('Orion-Intelligence', 'Orion-mail'),
    'NEXUS_PASSWORD': ('Orion-Intelligence', 'Orion-Dark-Nexus'),
}
AUTOMATIC = {
    'Orion-Intelligence': {'S_SUPER_PASSWORD_V1', 'S_CRAWLER_PASSWORD', 'JWT_SECRET_KEY',
                          'ENCRYPTION_KEY', 'MONGO_ROOT_PASSWORD',
                          'REDIS_PASSWORD', 'ARANGO_PASSWORD', 'TRAEFIK_PASSWORD', 'DEMO_PASSWORD',
                          'ORION_SOCIAL_INTERNAL_TOKEN', 'ORION_MAIL_SSO_CLIENT_SECRET', 'NEXUS_PASSWORD'},
    'Orion-Micros': {'S_SUPER_PASSWORD_V1', 'REDIS_PASSWORD', 'I2P_PASSWORD', 'TOR_PASSWORD', 'FULL_SCAN_ZAP_API_KEY'},
    'Orion-Social': {'S_SUPER_PASSWORD_V1', 'REDIS_PASSWORD', 'I2P_PASSWORD', 'TOR_PASSWORD', 'ORION_SOCIAL_INTERNAL_TOKEN'},
    'Orion-Dark-Nexus': {'ENCRYPTION_KEY', 'MONGO_ROOT_PASSWORD', 'NEXUS_PASSWORD'},
    'Orion-mail': {'ENCRYPTION_KEY', 'MONGO_ROOT_PASSWORD', 'MONGODB_URL',
                   'ORION_MAIL_SSO_CLIENT_SECRET', 'INCOMING_MAIL_TOKEN', 'RSPAMD_CONTROLLER_PASSWORD'},
    'Orion-Tor2Web': set(),
}
ASSIGNMENT = re.compile(r'^(\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*)(.*)$')
VALUE = re.compile(r'''^('(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*"|[^'"].*?|)(\s+\#.*)?$''')


def pending(value):
    return AUTO in value or MANUAL in value


def decode(raw):
    if raw.startswith("'"):
        return re.sub(r"\\(['\\])", r'\1', raw[1:-1])
    if raw.startswith('"'):
        escapes = {'n': '\n', 'r': '\r', 't': '\t', '\\': '\\', '"': '"', "'": "'"}
        return re.sub(r'''\\([nrt\\"'])''', lambda match: escapes[match[1]], raw[1:-1])
    return raw.strip()


def encode(value):
    if not value or pending(value) or any(char in value for char in '\n\r\0'):
        raise ValueError('Enter a nonempty, single-line value without placeholders')
    if re.fullmatch(r'[A-Za-z0-9_./:@!?=+,-]+', value):
        return value

    return "'" + value.replace('\\', '\\\\').replace("'", "\\'") + "'"


class Environment:
    def __init__(self, path):
        self.path = path
        if path.is_symlink() or not path.is_file():
            raise ValueError(f'{path}: a regular .env file is required')
        self.original = path.read_text()
        self.lines = self.original.splitlines(keepends=True)
        self.entries = {}
        self.changed = []
        for index, line in enumerate(self.lines):
            match = ASSIGNMENT.fullmatch(line.rstrip('\r\n'))
            if not match:
                if line.strip() and not line.lstrip().startswith('#'):
                    raise ValueError(f'{path}: expected a single-line KEY=value at line {index + 1}')
                continue
            key = match[2]
            value = VALUE.fullmatch(match[3].strip())
            if not value or key in self.entries:
                raise ValueError(f'{path}: invalid or duplicate assignment for {key}')
            self.entries[key] = (index, match[1], value[1], value[2] or '')

    def get(self, key):
        if key not in self.entries:
            raise ValueError(f'{self.path}: missing {key}')
        return decode(self.entries[key][2])

    def set(self, key, value, *, replace=False):
        if not replace and not pending(self.get(key)):
            return
        index, prefix, _, comment = self.entries[key]
        raw = encode(value)
        self.lines[index] = prefix + raw + comment + '\n'
        self.entries[key] = (index, prefix, raw, comment)
        self.changed.append(key)


def generate(key):
    if key == 'ENCRYPTION_KEY':
        return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode('ascii')
    if 'PASSWORD' in key:

        groups = (string.ascii_lowercase, string.ascii_uppercase, string.digits, '!')
        characters = [secrets.choice(group) for group in groups]
        characters.extend(secrets.choice(''.join(groups)) for _ in range(44))
        secrets.SystemRandom().shuffle(characters)
        return ''.join(characters)
    if key in {'JWT_SECRET_KEY', 'ORION_SOCIAL_INTERNAL_TOKEN', 'ORION_MAIL_SSO_CLIENT_SECRET'}:
        return secrets.token_hex(32)
    return secrets.token_urlsafe(32)


def fill_shared(documents, groups, regenerate):

    for key, names in groups.items():
        values = [documents[name].get(key) for name in names]
        existing = {value for value in values if not pending(value)}
        if not regenerate and '' in existing:
            raise ValueError(f'{key}: empty value in {", ".join(names)}')
        if not regenerate and len(existing) > 1:
            value = next(documents[name].get(key) for name in names if not pending(documents[name].get(key)))
            for name in names:
                if documents[name].get(key) != value:
                    documents[name].set(key, value, replace=True)
        for name in names:
            raw = documents[name].entries[key][2]
            if AUTO in raw and key not in AUTOMATIC[name]:
                raise ValueError(f'{name}/{key}: requires an existing credential; use {MANUAL}')
            if not regenerate and not pending(raw) and '$' in raw and not raw.startswith("'"):
                raise ValueError(f'{name}/{key}: use a literal single-quoted value, not interpolation')
    for key, names in groups.items():
        values = [documents[name].get(key) for name in names]
        existing = next((value for value in values if not pending(value)), None)
        if regenerate:
            value = generate(key)
        elif all(not pending(value) for value in values):
            continue
        elif existing is not None:
            value = existing
        elif all(value == AUTO and key in AUTOMATIC[name] for name, value in zip(names, values)):
            value = generate(key)
        else:
            continue
        if value is not None:
            for name in names:
                documents[name].set(key, value, replace=regenerate)


def fill_module(document, regenerate):
    module = document.path.parent.name
    for key in document.entries:
        value = document.get(key)
        if key in SHARED or key == 'MONGODB_URL':
            continue
        rotate = regenerate and key in AUTOMATIC[module] and key != 'FULL_SCAN_ZAP_API_KEY'
        if rotate:
            value = generate(key)
        elif AUTO in value:
            if key not in AUTOMATIC[module] or value != AUTO:
                raise ValueError(f'{module}/{key}: cannot auto-generate this value; use {MANUAL}')
            value = generate(key)
        else:
            continue
        document.set(key, value, replace=rotate)
    if 'MONGODB_URL' in document.entries:
        value = document.get('MONGODB_URL')
        if AUTO in value or regenerate:
            username, password = document.get('MONGO_ROOT_USERNAME'), document.get('MONGO_ROOT_PASSWORD')
            if pending(username) or pending(password) or not username or not password:
                return
            match = re.fullmatch(r'(mongodb(?:\+srv)?://)[^/]*@(.+)', value)
            if not match:
                raise ValueError('MONGODB_URL: preserve the existing MongoDB URL and mark its password {value_auto}')
            value = match[1] + quote(username, safe='') + ':' + quote(password, safe='') + '@' + match[2]
        else:
            return
        document.set('MONGODB_URL', value, replace=regenerate)


def save(documents):
    changes = [document for document in documents.values() if document.changed]
    for document in changes:
        if document.path.is_symlink() or document.path.read_text() != document.original:
            raise ValueError(f'{document.path}: changed while filling; nothing was written')
    staged = []
    try:
        for document in changes:
            descriptor, filename = tempfile.mkstemp(prefix='.env.', dir=document.path.parent)
            staged.append((document, Path(filename)))
            with os.fdopen(descriptor, 'w') as stream:
                os.fchmod(stream.fileno(), 0o600)
                stream.write(''.join(document.lines))
                stream.flush()
                os.fsync(stream.fileno())
        for document, filename in staged:
            os.replace(filename, document.path)
            print(f'{document.path.parent.name}: filled {", ".join(document.changed)}')
    finally:
        for _, filename in staged:
            filename.unlink(missing_ok=True)
    if not changes:
        print('No configured values changed.')


def fill(root, module=None, *, all_modules=False, regenerate=False):
    local = list(MODULES) if all_modules else ([module] if module else [])
    groups = {key: names for key, names in SHARED.items()
              if module is None or module in names}
    names = set(local).union(*(set(names) for names in groups.values()))
    runtime = root / '.runtime'
    runtime.mkdir(mode=0o700, exist_ok=True)
    with (runtime / 'env-fill.lock').open('a') as lock:
        os.chmod(lock.name, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        documents = {name: Environment(root / name / '.env') for name in sorted(names)}
        fill_shared(documents, groups, regenerate)
        for name in local:
            fill_module(documents[name], regenerate)
        save(documents)
        for name, document in documents.items():
            if module is not None and name != module:
                continue
            remaining = [key for key in document.entries if pending(document.get(key))]
            if remaining:
                print(f'{name}: still requires input/filling for {", ".join(remaining)}')


def main(module=None):
    parser = argparse.ArgumentParser(description='Generate random values for {value_auto}; leave external {value} fields unchanged.')
    parser.add_argument('--regenerate', action='store_true', help='replace generated credentials with a fresh set, including shared copies; does not update databases/accounts')
    if module is None:
        parser.add_argument('--all', action='store_true', dest='all_modules', help='fill module-local values too (default: shared keys only)')
    options = parser.parse_args()
    try:
        if options.regenerate:
            print('Warning: new credentials do not update existing databases/accounts or re-encrypt stored data.', file=sys.stderr)
        fill(Path(__file__).resolve().parents[1], module,
             all_modules=getattr(options, 'all_modules', False), regenerate=options.regenerate)
    except (OSError, ValueError, EOFError) as error:
        print(f'Environment filler: {error}', file=sys.stderr)
        raise SystemExit(1) from None
    except KeyboardInterrupt:
        print('\nCancelled.', file=sys.stderr)
        raise SystemExit(130) from None
