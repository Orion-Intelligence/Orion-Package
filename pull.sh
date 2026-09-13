#!/usr/bin/env bash
set -euo pipefail
ACTION=pull
source "$(dirname -- "${BASH_SOURCE[0]}")/_shared/common.sh"
main "$@"
