#!/usr/bin/env bash

PACKAGE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
ORION_BASE_DIR="${ORION_BASE_DIR:-$(cd -- "$PACKAGE_DIR/.." && pwd)}"
ORION_IMAGE_NAMESPACE="${ORION_IMAGE_NAMESPACE:-msmannan00}"
ORION_IMAGE_TAG="${ORION_IMAGE_TAG:-latest}"
REPOSITORIES=(Orion-Intelligence Orion-Micros Orion-Social Orion-Dark-Nexus
    Orion-mail Orion-Tor2Web Orion-Crawler Orion-Sandbox Orion-Storage)
SELECTED=(0 0 0 0 0 0 0 0 0)

pending() { printf '%s: %s not implemented yet.\n' "$1" "$ACTION" >&2; return 1; }

push_backend() {
    python3 -B "$PACKAGE_DIR/_shared/backend.py" build "$REPO_PACKAGE_DIR" "$REPO_SOURCE_DIR" "$IMAGE" || return $?
    docker push "$IMAGE" || return $?
}

pull_backend() {
    python3 -B "$PACKAGE_DIR/_shared/backend.py" pull "$REPO_PACKAGE_DIR" "$ENV_FILE" "$IMAGE"
}

dispatch() (
    REPO_PACKAGE_DIR="$PACKAGE_DIR/push/$1"
    REPO_SOURCE_DIR="$ORION_BASE_DIR/$1"
    ENV_FILE="$PACKAGE_DIR/pull/$1/.env"
    export ORION_SOURCE_DIR="$REPO_SOURCE_DIR"
    source "$REPO_PACKAGE_DIR/repo.sh" || return $?
    IMAGE="$ORION_IMAGE_NAMESPACE/orion-$SLUG:$ORION_IMAGE_TAG"
    if [[ "$ACTION" == push ]]; then bash "$PACKAGE_DIR/_shared/source.sh" "$REPO_SOURCE_DIR" || return $?; fi
    "$ACTION"
)

restore_terminal() { printf '\033[?25h\033[?1049l'; }

choose_repositories() {
    [[ -t 0 && -t 1 && "${TERM:-dumb}" != dumb ]] || {
        printf 'Run this script in a terminal.\n' >&2; return 1;
    }
    local cursor=0 count index row checked label key suffix value
    local total=${#REPOSITORIES[@]}
    trap restore_terminal EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    printf '\033[?1049h\033[?25l'
    while true; do
        count=0
        for value in "${SELECTED[@]}"; do count=$((count + value)); done
        printf '\033[H\033[2JOrion Docker %s\n\n' "$ACTION"
        printf 'Up/Down: move | Space: toggle | Enter: run | q/Esc: cancel\n\n'
        for ((row = 0; row <= total; row++)); do
            checked=' '
            if ((row == 0)); then
                label=All
                if ((count == total)); then checked=x; fi
            else
                label="${REPOSITORIES[row - 1]}"
                if ((SELECTED[row - 1])); then checked=x; fi
            fi
            if ((cursor == row)); then printf '\033[7m'; fi
            printf '  [%s] %-24s\033[0m\n' "$checked" "$label"
        done
        printf '\nSelected: %s/%s | %s:<%s>\n' "$count" "$total" "$ORION_IMAGE_NAMESPACE" "$ORION_IMAGE_TAG"
        printf 'Ready: Intelligence, Tor2Web, Micros, Social, Dark Nexus, Mail. Other handlers are pending.\n'
        IFS= read -rsn1 key || exit 130
        if [[ "$key" == $'\033' ]]; then
            suffix=''
            IFS= read -rsn2 -t 0.15 suffix || true
            key+="$suffix"
        fi
        case "$key" in
            $'\033[A'|k) cursor=$(((cursor + total) % (total + 1))) ;;
            $'\033[B'|j) cursor=$(((cursor + 1) % (total + 1))) ;;
            ' ')
                if ((cursor == 0)); then
                    value=$((count != total))
                    for index in "${!SELECTED[@]}"; do SELECTED[index]=$value; done
                else
                    index=$((cursor - 1))
                    SELECTED[index]=$((1 - SELECTED[index]))
                fi
                ;;
            '') if ((count > 0)); then break; fi ;;
            q|Q|$'\033') exit 130 ;;
        esac
    done
    restore_terminal
    trap - EXIT INT TERM
}

main() {
    if (($#)); then printf 'Usage: %s (interactive)\n' "$0" >&2; return 1; fi
    choose_repositories || return $?
    bash "$PACKAGE_DIR/setup.sh" --system "$ACTION" || return $?
    if [[ "$ACTION" == pull ]]; then python3 -B "$PACKAGE_DIR/pull/_shared/deployment.py" || return $?; fi
    local index repository logged_in=0 status
    for index in "${!REPOSITORIES[@]}"; do
        ((SELECTED[index])) || continue
        repository="${REPOSITORIES[index]}"
        printf '\n%s: %s\n' "$ACTION" "$repository"
        if [[ ! -f "$PACKAGE_DIR/push/$repository/repo.sh" ]]; then
            pending "$repository"
            return 1
        fi
        if [[ "$ACTION" == push && "$logged_in" == 0 ]]; then
            printf 'Docker Hub login: enter a token with Read & Write access.\n'
            docker login --username "$ORION_IMAGE_NAMESPACE" || return $?
            logged_in=1
        fi
        if dispatch "$repository"; then
            :
        else
            status=$?
            printf '%s %s failed (exit %s). Stopping; see the error above. Existing services are not automatically removed.\n' "$ACTION" "$repository" "$status" >&2
            return "$status"
        fi
    done
    return 0
}
