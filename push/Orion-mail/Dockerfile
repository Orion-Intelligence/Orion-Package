FROM node:24-alpine AS client
WORKDIR /client
ENV CYPRESS_INSTALL_BINARY=0 NG_CLI_ANALYTICS=false
COPY client/package.json client/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY client/ ./
COPY obfuscation/ /obfuscation/
RUN npm ci --prefix /obfuscation --ignore-scripts --no-audit --no-fund
RUN npm run build -- --configuration production --source-map=false

RUN node /obfuscation/obfuscate.cjs /client/build browser-no-eval

FROM python:3.12-slim@sha256:2c941e860699f878900b0edc2403613c234d4b32eda3cc9fa7036991a2a63c4a AS dependencies
COPY requirements.txt /requirements.txt
RUN pip install --no-cache-dir --prefix=/install -r /requirements.txt

FROM dependencies AS compiler
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev shc binutils \
 && pip install --no-cache-dir Cython==3.3.0 setuptools==84.0.0
COPY app/ /build/app/
COPY entrypoint.sh /build/mail-entrypoint
COPY compile_backend.py prepare.py audit_release.py /build/
COPY --chmod=755 <<'SH' /build/mail-incoming
#!/bin/sh
exec /usr/local/bin/python3 -c 'import sys; sys.path.insert(0, "/app"); from postfix_incoming_handler import main; sys.exit(main())' "$@"
SH
RUN python /build/compile_backend.py
RUN mkdir -p /build/bin \
 && shc -r -f /build/mail-entrypoint -o /build/bin/mail-entrypoint \
 && shc -r -f /build/mail-incoming -o /build/bin/mail-incoming \
 && shc -r -f /build/app/postfix-entrypoint.sh -o /release/postfix-entrypoint.sh \
 && strip --strip-all /build/bin/mail-entrypoint /build/bin/mail-incoming /release/postfix-entrypoint.sh

RUN python3 -c "from pathlib import Path; assert all(Path(p).read_bytes()[:4] == bytes([127,69,76,70]) for p in ['/build/bin/mail-entrypoint', '/build/bin/mail-incoming', '/release/postfix-entrypoint.sh'])"

FROM python:3.12-slim@sha256:2c941e860699f878900b0edc2403613c234d4b32eda3cc9fa7036991a2a63c4a
LABEL orion.package.smtp-hostname="1"
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app HOME=/tmp
RUN printf 'postfix postfix/mailname string localhost\npostfix postfix/main_mailer_type string Internet Site\n' | debconf-set-selections \
 && apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    postfix gnupg nginx gettext-base openssl ca-certificates tini iproute2 \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --gid 1000 orionmail \
 && useradd --uid 1000 --gid 1000 --no-create-home --home-dir /tmp --shell /usr/sbin/nologin orionmail \
 && cp -a /etc/postfix /etc/postfix.template \
 && ln -sf /dev/stdout /var/log/nginx/access.log \
 && ln -sf /dev/stderr /var/log/nginx/error.log \
 && mkdir -p /app/static/resource/attachments /client_build \
 && python -m pip uninstall -y pip setuptools wheel
COPY --from=dependencies /install/ /usr/local/
COPY --from=compiler /release/ /app/
COPY --from=compiler /usr/share/doc/shc/copyright /usr/share/doc/orion/shc-copyright
COPY --from=client /client/build/ /client_build/
COPY nginx/ /etc/nginx/orion/
COPY maintenance.html /app/static/maintenance.html
COPY runtime/ /opt/orion/runtime/
COPY compose.json /opt/orion/compose.json
COPY --from=compiler --chmod=755 /build/bin/mail-entrypoint /usr/local/bin/mail-entrypoint
COPY --from=compiler --chmod=755 /release/postfix-entrypoint.sh /usr/local/bin/postfix-entrypoint.sh
COPY --from=compiler --chmod=755 /build/bin/mail-incoming /usr/local/bin/mail-incoming
WORKDIR /app
USER 1000:1000
EXPOSE 8000 8080 25
ENTRYPOINT ["/usr/bin/tini", "-s", "--", "/usr/local/bin/mail-entrypoint"]
CMD ["web"]
