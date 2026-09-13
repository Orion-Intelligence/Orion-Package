FROM node:24-alpine AS assets
COPY --from=orion_obfuscation / /obfuscation/
RUN npm ci --prefix /obfuscation --ignore-scripts --no-audit --no-fund
COPY data/ /data/
RUN node /obfuscation/obfuscate.cjs /data browser-no-eval

FROM python:3.13-slim AS runtime

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl gettext-base tini tor netcat-openbsd \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --system --gid 990 tor2web \
 && useradd --system --uid 990 --gid 990 --home-dir /var/lib/tor2web --shell /usr/sbin/nologin tor2web

WORKDIR /opt/tor2web
COPY requirements/requirements-modern.txt /opt/tor2web/requirements.txt
RUN pip install --no-cache-dir -r /opt/tor2web/requirements.txt

FROM runtime AS compiler
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev shc binutils \
 && pip install --no-cache-dir Cython==3.3.0 setuptools==84.0.0
WORKDIR /build
COPY tor2web/ tor2web/
COPY deploy/tor2web-entrypoint.sh /build/tor2web-entrypoint

RUN CFLAGS='-O2 -g0 -fvisibility=hidden' LDFLAGS=-s python3 <<'PY'
from pathlib import Path
from setuptools import setup
from Cython.Build import cythonize
from Cython.Compiler import Options

def patch(filename, old, new):
    path = Path(filename)
    source = path.read_text()
    if source.count(old) != 1:
        raise RuntimeError(f'{filename} changed; review the compiled launcher.')
    path.write_text(source.replace(old, new))

main = 'tor2web/t2w.py'
patch(main, '[sys.executable, os.path.abspath(__file__)]',
      "[sys.executable, '-c', 'import tor2web.t2w']")

bridge = '''
def _compiled_inline_callbacks(function):
    namespace = {'function': function}
    exec('def bridge(*args, **kwargs):\\n    return (yield from function(*args, **kwargs))', namespace)
    return defer.inlineCallbacks(namespace['bridge'])

'''
patch(main, 'def parse_header(value):', bridge + 'def parse_header(value):')
patch(main, '@defer.inlineCallbacks', '@_compiled_inline_callbacks')
patch('/build/tor2web-entrypoint', 'exec python3 /opt/tor2web/tor2web/t2w.py',
      "exec python3 -c 'import tor2web.t2w'")

Options.docstrings = False
modules = [str(path) for path in Path('tor2web').rglob('*.py')]
setup(
    ext_modules=cythonize(modules, compiler_directives={'language_level': 3, 'annotation_typing': False, 'embedsignature': False, 'emit_code_comments': False}),
    script_args=['build_ext', '--build-lib', '/compiled', '--parallel', '2'],
)
assert len(list(Path('/compiled').rglob('*.so'))) == len(modules), 'Incomplete compilation'
PY

COPY --chmod=755 <<'SH' /build/tor2web-stack
#!/bin/bash
set -eu
export BASEHOST="${BASEHOST:-tor.orionintelligence.org}"
export LETSENCRYPT_CERT_NAME="${LETSENCRYPT_CERT_NAME:-onion-tor-orionintelligence-org}"
export UPSTREAM_HOST=127.0.0.1 UPSTREAM_PORT="${LISTEN_PORT_HTTP:-9080}"
[[ "$BASEHOST" =~ ^[a-z0-9][a-z0-9.-]*[a-z0-9]$ && "$LETSENCRYPT_CERT_NAME" =~ ^[a-zA-Z0-9_-]+$ ]]
envsubst '${BASEHOST} ${LETSENCRYPT_CERT_NAME} ${UPSTREAM_HOST} ${UPSTREAM_PORT}' \
    < /etc/nginx/tor2web.conf.template > /etc/nginx/tor2web.conf
cert="/etc/letsencrypt/live/$LETSENCRYPT_CERT_NAME/fullchain.pem"
openssl x509 -in "$cert" -noout -checkend 0
openssl x509 -in "$cert" -noout -checkhost "check.onion.$BASEHOST"
nginx -t
[[ "${1:-}" != --check ]] || exit 0

pids=()
trap 'kill "${pids[@]}" 2>/dev/null || true; wait "${pids[@]}" 2>/dev/null || true' EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
setpriv --reuid=990 --regid=990 --init-groups --no-new-privs tor -f /etc/tor/torrc &
pids+=($!)
setpriv --reuid=990 --regid=990 --init-groups --no-new-privs /usr/local/bin/tor2web-entrypoint &
pids+=($!)
nginx -g 'daemon off;' &
pids+=($!)
(while sleep 43200; do nginx -s reload; done) &
pids+=($!)
wait -n "${pids[@]}" || true
printf 'A stack process exited; stopping the container.\n' >&2
exit 1
SH
COPY deploy/tor-healthcheck.sh /build/tor-healthcheck
RUN mkdir -p /build/bin \
 && shc -r -f /build/tor2web-entrypoint -o /build/bin/tor2web-entrypoint \
 && shc -r -f /build/tor-healthcheck -o /build/bin/tor-healthcheck \
 && shc -r -f /build/tor2web-stack -o /build/bin/tor2web-stack \
 && strip --strip-all /build/bin/*

RUN python3 -c "from pathlib import Path; assert all(Path(p).read_bytes()[:4] == bytes([127,69,76,70]) for p in ['/build/bin/tor2web-entrypoint', '/build/bin/tor-healthcheck', '/build/bin/tor2web-stack'])"

FROM runtime AS release
RUN apt-get update && apt-get install -y --no-install-recommends nginx \
 && rm -rf /var/lib/apt/lists/*
ENV PYTHONPATH=/opt/tor2web PYTHONDONTWRITEBYTECODE=1 SOCKS_HOST=127.0.0.1 T2W_DEBUG=False
COPY --from=compiler /compiled/tor2web/ /opt/tor2web/tor2web/
COPY --from=compiler --chmod=755 /build/bin/tor2web-entrypoint /usr/local/bin/tor2web-entrypoint
COPY --from=assets /data/ /usr/share/tor2web/data/
COPY LICENSE /usr/share/doc/tor2web/LICENSE
COPY --from=compiler /usr/share/doc/shc/copyright /usr/share/doc/tor2web/shc-copyright
COPY deploy/tor2web.conf.template /etc/tor2web.conf.template
COPY deploy/torrc /etc/tor/torrc
COPY --from=compiler --chmod=755 /build/bin/tor-healthcheck /usr/local/bin/tor-healthcheck
COPY deploy/nginx.conf.template /etc/nginx/tor2web.conf.template
COPY <<'NGINX' /etc/nginx/nginx.conf
user tor2web;
worker_processes auto;
pid /run/nginx.pid;
error_log /dev/stderr warn;
events { worker_connections 1024; }
http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;
    access_log /dev/stdout;
    include /etc/nginx/tor2web.conf;
}
NGINX
COPY --from=compiler --chmod=755 /build/bin/tor2web-stack /usr/local/bin/tor2web-stack
RUN sed -i 's/^SocksPort 0.0.0.0:/SocksPort 127.0.0.1:/' /etc/tor/torrc \
 && sed -i 's/listen_ipv4 = 0.0.0.0/listen_ipv4 = 127.0.0.1/' /etc/tor2web.conf.template \
 && sed -i 's/listen 9080 ssl/listen 443 ssl/g; s/\$host:\$server_port/\$http_host/g' /etc/nginx/tor2web.conf.template \
 && mkdir -p /var/lib/tor /var/lib/tor2web/logs /var/lib/tor2web/certs /var/lib/tor2web/lists /run/tor2web \
 && chown -R tor2web:tor2web /var/lib/tor /var/lib/tor2web /run/tor2web \
 && setpriv --reuid=990 --regid=990 --init-groups tor --verify-config -f /etc/tor/torrc

EXPOSE 443
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD curl -fksS -o /dev/null https://127.0.0.1/healthz && curl -fsS -o /dev/null "http://127.0.0.1:${LISTEN_PORT_HTTP:-9080}/antanistaticmap/tor2web.css" && /usr/local/bin/tor-healthcheck
ENTRYPOINT ["/usr/bin/tini", "-s", "--", "/usr/local/bin/tor2web-stack"]
