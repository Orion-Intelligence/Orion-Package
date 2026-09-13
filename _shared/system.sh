#!/usr/bin/env bash
set -euo pipefail
MENU="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/menu.sh"
ask() { local reply; reply="$(bash "$MENU" "$1" No Yes)" || return $?; [[ "$reply" == 2 ]]; }
admin() { if ((EUID == 0)); then "$@"; else sudo -- "$@"; fi; }
apt_host() {
    [[ -f /etc/os-release ]] || return 1
    source /etc/os-release
    [[ "$ID" == ubuntu || "$ID" == debian ]] && command -v apt-get >/dev/null
}
install_base() {
    apt_host || { printf 'Install Python 3.12+, OpenSSL, iproute2 and Docker Compose manually on this OS.\n'; return 1; }
    ask 'Install missing host utilities using apt (requires administrator access)?' || return 1
    admin apt-get update
    admin apt-get install -y python3 openssl iproute2 dnsutils ca-certificates curl git
}
for binary in python3 openssl ss dig curl git; do
    if ! command -v "$binary" >/dev/null; then install_base; break; fi
done
python3 -c 'import sys; sys.exit(sys.version_info < (3, 12))' || {
    printf 'Python 3.12+ is required. Install it as python3, then retry.\n'; exit 1;
}
compose_ready() {
    local version
    version="$(docker compose version --short 2>/dev/null)" || return 1
    python3 -c 'import re,sys; match=re.search(r"(\d+)\.(\d+)",sys.argv[1]); sys.exit(not match or tuple(map(int, match.groups())) < (2,30))' "$version"
}
if ! docker --version >/dev/null 2>&1 || ! compose_ready ||
   { [[ "${1:-pull}" == push ]] && ! docker buildx version >/dev/null 2>&1; }; then
    apt_host || { printf 'Install Docker Engine and the Compose plugin manually, then retry.\n'; exit 1; }
    for package in docker.io docker-compose docker-compose-v2 podman-docker containerd runc; do
        if dpkg-query -W -f='${Status}' "$package" 2>/dev/null | grep -q 'install ok installed'; then
            printf 'Existing package %s detected. Follow https://docs.docker.com/engine/install/ for a safe migration, then retry.\n' "$package"
            exit 1
        fi
    done
    ask 'Install Docker Engine, Compose and Buildx from Docker’s official apt repository (starts Docker)?' || exit 1
    admin apt-get update
    admin apt-get install -y ca-certificates curl
    admin install -m 0755 -d /etc/apt/keyrings
    if [[ ! -f /etc/apt/keyrings/docker.asc ]]; then
        admin curl --fail --show-error --silent --location "https://download.docker.com/linux/$ID/gpg" -o /etc/apt/keyrings/docker.asc
        admin chmod a+r /etc/apt/keyrings/docker.asc
    fi
    if ! grep -Rq 'download.docker.com/linux' /etc/apt/sources.list /etc/apt/sources.list.d 2>/dev/null; then
        [[ ! -e /etc/apt/sources.list.d/orion-docker.sources ]] || { printf 'Review existing orion-docker.sources first.\n'; exit 1; }
        printf 'Types: deb\nURIs: https://download.docker.com/linux/%s\nSuites: %s\nComponents: stable\nArchitectures: %s\nSigned-By: /etc/apt/keyrings/docker.asc\n' \
            "$ID" "${UBUNTU_CODENAME:-$VERSION_CODENAME}" "$(dpkg --print-architecture)" | admin tee /etc/apt/sources.list.d/orion-docker.sources >/dev/null
    fi
    admin apt-get update
    admin apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
while ! docker info >/dev/null 2>&1; do
    printf 'Docker is installed but this user cannot reach the daemon.\n'
    choice="$(bash "$MENU" 'Docker is unavailable' 'Start local Docker with sudo' 'Retry after fixing permissions/context' 'Cancel')" || exit $?
    case "$choice" in
        1) ask 'Enable and start docker.service?' && admin systemctl enable --now docker || true ;;
        2) ;;
        3) exit 1 ;;
    esac
    printf 'No socket chmod or automatic docker-group membership changes are made (Docker access grants root-equivalent power).\n'
done
endpoint="${DOCKER_HOST:-$(docker context inspect --format '{{.Endpoints.docker.Host}}')}"
[[ "$endpoint" == unix://* ]] || { printf 'Use a local Docker context: deployments bind local data and certificate paths.\n'; exit 1; }
compose_ready || { printf 'Docker Compose 2.30+ is required. Upgrade the Compose plugin and retry.\n'; exit 1; }
if [[ "${1:-pull}" == push ]]; then docker buildx version >/dev/null; fi
printf 'Host prerequisites ready.\n'
