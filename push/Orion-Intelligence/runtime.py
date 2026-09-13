import asyncio
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import sys
from urllib.parse import urlsplit

STORAGE = ('static', 'workspace/resource', 'workspace/logs', 'workspace/parser/parser_files', 'backups', 'bloom_data')


def prepare_storage():
    uid, gid = int(os.environ.get('APP_UID', '1000')), int(os.environ.get('APP_GID', '1000'))
    if uid <= 0 or gid <= 0:
        raise ValueError('APP_UID and APP_GID must be non-root')
    for name in STORAGE:
        destination = Path('/app') / name
        destination.mkdir(parents=True, exist_ok=True)
        os.chown(destination, uid, gid)

    for source in Path('/opt/orion/defaults').rglob('*'):
        target = Path('/app') / source.relative_to('/opt/orion/defaults')
        if source.is_dir():
            if not target.exists():
                target.mkdir()
                os.chown(target, uid, gid)
        elif source.is_file() and not target.exists():
            with target.open('xb') as output, source.open('rb') as content:
                shutil.copyfileobj(content, output)
            os.chown(target, uid, gid)


def check_storage():
    for name in STORAGE:
        path = Path('/app') / name
        if not path.is_dir() or not os.access(path, os.W_OK | os.X_OK):
            raise RuntimeError(f'Writable runtime directory required: {path}')


def check_certificate():
    directory = Path('/etc/letsencrypt/live/try.orionintelligence.org')
    certificate, key = directory / 'fullchain.pem', directory / 'privkey.pem'
    hosts = {urlsplit(os.environ['APP_URL']).hostname, 'mail.orionintelligence.org', 'check.orionintelligence.org'}
    for host in hosts:
        subprocess.run(['openssl', 'x509', '-in', str(certificate), '-noout', '-checkhost', str(host)], check=True)
    subprocess.run(['openssl', 'x509', '-in', str(certificate), '-noout', '-checkend', '86400'], check=True)
    subprocess.run(['openssl', 'verify', '-untrusted', str(certificate), str(certificate)], check=True)
    ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER).load_cert_chain(certificate, key)


async def bootstrap():

    from orion.management.managers.service_manager import service_manager
    manager = service_manager.get_instance()
    assert manager is not None
    await manager.build_assets(manager.default_build_dir())
    await manager.init_services()


def main():
    role = sys.argv[1] if len(sys.argv) > 1 else 'web'
    if role == 'prepare':
        prepare_storage()
    elif role == 'check-certificate':
        check_certificate()
    elif role == 'check-storage':
        check_storage()
    elif role == 'web':
        check_storage()
        asyncio.run(bootstrap())
        os.execvp('gunicorn', ['gunicorn', '-w', os.environ.get('ORION_WEB_WORKERS', '4'), '--threads', '4',
                              '-k', 'uvicorn.workers.UvicornWorker', 'main:app', '--bind', '0.0.0.0:8070', '--timeout', '900',
                              '--control-socket', '/tmp/gunicorn.ctl'])
    elif role == 'cron':
        check_storage()
        from cronjobs import main as run_cron
        asyncio.run(run_cron())
    else:
        raise ValueError(f'Unknown Intelligence role: {role}')
