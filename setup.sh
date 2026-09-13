#!/usr/bin/env bash
set -euo pipefail
usage() { printf 'Usage: ./setup.sh [--system [pull|push] | Orion-Intelligence | Orion-mail | Orion-Micros | Orion-Social | Orion-Dark-Nexus]\nNo argument: check host prerequisites, then choose a module.\n'; }
case "${1:-}" in
    -h|--help) usage; exit 0 ;;
    --system) [[ $# -le 2 && ( "${2:-pull}" == pull || "${2:-pull}" == push ) ]] || { usage; exit 1; } ;;
    ''|Orion-Intelligence|Orion-mail|Orion-Micros|Orion-Social|Orion-Dark-Nexus)
        [[ $# -le 1 ]] || { usage; exit 1; } ;;
    *) usage; exit 1 ;;
esac
PACKAGE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
bash "$PACKAGE_DIR/_shared/system.sh" "${2:-pull}"
if [[ "${1:-}" != --system ]]; then
    python3 -B "$PACKAGE_DIR/pull/_shared/environment.py" "${1:-}"
fi
