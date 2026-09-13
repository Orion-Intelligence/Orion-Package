#!/bin/sh
set -eu

check_certificate() {
    certificate="${ORION_MAIL_CERT_DIR:-/etc/letsencrypt/live/try.orionintelligence.org}/fullchain.pem"
    private_key="${certificate%/*}/privkey.pem"
    openssl x509 -in "$certificate" -noout -checkhost "${SMTP_HOSTNAME:-${MAIL_DOMAIN:-mail.orionintelligence.org}}"
    openssl x509 -in "$certificate" -noout -checkend 86400
    openssl verify -untrusted "$certificate" "$certificate"
    python3 -c 'import ssl,sys; ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER).load_cert_chain(sys.argv[1], sys.argv[2])' "$certificate" "$private_key"
}

refresh_certificate() {
    check_certificate
    install -m 644 "$certificate" /etc/postfix/orion-fullchain.pem
    install -m 640 -g postfix "$private_key" /etc/postfix/orion-privkey.pem
}

case "${1:-web}" in
    web)
        exec uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4 --proxy-headers --forwarded-allow-ips='*'
        ;;
    cron)
        exec python3 -c 'import asyncio; from cronjobs import main; asyncio.run(main())'
        ;;
    nginx)
        # shellcheck disable=SC2016
        envsubst '${MAIL_DOMAIN}' < /etc/nginx/orion/nginx-prod.conf > /tmp/nginx.conf
        exec nginx -c /tmp/nginx.conf -g 'daemon off;'
        ;;
    check)
        check_certificate
        ;;
    prepare)
        mkdir -p /app/static/resource/attachments/incoming /app/static/resource/attachments/outgoing \
            /app/static/resource/attachments/raw /app/static/resource/attachments/staging
        chown "${APP_UID:-1000}:${APP_GID:-1000}" /app/static/resource/attachments \
            /app/static/resource/attachments/incoming /app/static/resource/attachments/outgoing \
            /app/static/resource/attachments/raw /app/static/resource/attachments/staging
        ;;
    certs)
        refresh_certificate
        ;;
    postfix)
        refresh_certificate
        relay_network="$(ip -4 route show dev eth0 proto kernel scope link | awk 'NR == 1 {print $1}')"
        test -n "$relay_network"
        export POSTFIX_MYNETWORKS="127.0.0.0/8 $relay_network"
        (while sleep 43200; do /usr/local/bin/mail-entrypoint certs && postfix reload || true; done) &
        exec /usr/local/bin/postfix-entrypoint
        ;;
    *) printf 'Unknown mail role: %s\n' "$1" >&2; exit 1 ;;
esac
