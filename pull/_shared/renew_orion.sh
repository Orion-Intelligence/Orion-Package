#!/bin/sh
set -eu
reload_nginx() {
    name="$1"
    project="$2"
    actual="$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}:{{.State.Running}}' "$name" 2>/dev/null)" || return 0
    [ "$actual" = "$project:true" ] || return 0
    docker exec --user 0 "$name" nginx -t
    docker exec --user 0 "$name" nginx -s reload
}
reload_nginx trusted-web-nginx trusted-search
actual="$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}:{{.State.Running}}' orion-mail-postfix 2>/dev/null)" || actual=''
if [ "$actual" = 'orion-mail:true' ]; then
    docker exec --user 0 orion-mail-postfix /usr/local/bin/mail-entrypoint certs
    docker exec --user 0 orion-mail-postfix postfix reload
fi
