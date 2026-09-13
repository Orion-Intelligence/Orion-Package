from pathlib import Path

script = Path('/build/app/postfix-entrypoint.sh')
source = script.read_text()
replacements = {
    'postconf -e "myhostname = ${MAIL_DOMAIN}"': 'postconf -e "myhostname = ${SMTP_HOSTNAME:-${MAIL_DOMAIN}}"',
    'argv=/usr/local/bin/python3 /opt/orion-mail/backend/postfix_incoming_handler.py':
        'argv=/usr/local/bin/mail-incoming',
    '/etc/ssl/certs/ssl-cert-snakeoil.pem': '/etc/postfix/orion-fullchain.pem',
    '/etc/ssl/private/ssl-cert-snakeoil.key': '/etc/postfix/orion-privkey.pem',
    'postfix check || true': 'postfix check',
}
for before, after in replacements.items():
    if source.count(before) != 1:
        raise RuntimeError(f'Review Postfix launcher: expected {before!r} once')
    source = source.replace(before, after)
script.write_text(source)
