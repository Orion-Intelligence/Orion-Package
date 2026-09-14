FROM node:24-alpine AS client
WORKDIR /client
ENV CYPRESS_INSTALL_BINARY=0 NG_CLI_ANALYTICS=false
COPY client/package.json client/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY client/ ./
COPY obfuscation/ /obfuscation/
RUN npx ng build --configuration production --source-map=false \
 && test -f build/index.html && test -f build/assets/data/map/world.json

RUN node /obfuscation/obfuscate.cjs /client/build browser-no-eval

FROM python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de AS documentation
WORKDIR /docs
COPY docs/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY docs/ ./
RUN ORION_DOCS_PUBLIC=1 sphinx-build -W --keep-going -b html -D html_copy_source=0 . /site
ARG DOCUMENTATION_PROJECT_NAME=Platform
ARG DOCUMENTATION_COMPANY_NAME="Platform Operator"
RUN python replace_branding.py /site "$DOCUMENTATION_PROJECT_NAME" "$DOCUMENTATION_COMPANY_NAME"

FROM client AS protected-documentation
COPY --from=documentation /site/ /site/
RUN node /obfuscation/obfuscate.cjs /site browser-no-eval

FROM python:3.11-slim@sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93 AS dependencies
COPY requirements.txt /requirements.txt
RUN pip install --no-cache-dir --prefix=/install -r /requirements.txt

FROM dependencies AS compiler
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev \
 && pip install --no-cache-dir Cython==3.3.0 setuptools==84.0.0
COPY app/ /build/app/
COPY compile_backend.py prepare.py audit_release.py /build/
RUN python /build/compile_backend.py

FROM python:3.11-slim@sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app HOME=/tmp
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl openssl tini \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --gid 1000 orion && useradd --uid 1000 --gid 1000 --no-create-home --home-dir /tmp --shell /usr/sbin/nologin orion \
 && mkdir -p /app/workspace/parser/parser_files /app/workspace/logs /app/workspace/resource /app/backups /app/bloom_data /app/static \
 && chown -R orion:orion /app \
 && ln -s workspace/build /app/build \
 && python -m pip uninstall -y pip setuptools wheel
COPY --from=dependencies /install/ /usr/local/
COPY --from=compiler /release/ /app/
COPY extension/ /app/workspace/extension/
COPY --from=client /client/build/ /app/workspace/build/
COPY --from=protected-documentation /site/ /opt/orion/assets/docs/
COPY nginx/ /opt/orion/assets/nginx/
COPY defaults/ /opt/orion/defaults/
COPY api_docs/ /app/docs/api_docs/
COPY pyproject.toml /app/pyproject.toml
COPY LICENSE /usr/share/doc/orion/LICENSE
COPY compose.json /opt/orion/compose.json
RUN ln -s /app/workspace/build /client_build
WORKDIR /app
USER 1000:1000
EXPOSE 8070
HEALTHCHECK --interval=30s --timeout=10s --start-period=300s --retries=3 \
    CMD host="${APP_URL#https://}"; host="${host%%/*}"; curl --fail --silent --header "Host: ${host}" http://127.0.0.1:8070/api/public > /dev/null
ENTRYPOINT ["/usr/bin/tini", "--", "python3", "-c", "from package_runtime import main; main()"]
CMD ["web"]
