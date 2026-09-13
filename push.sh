#!/usr/bin/env bash
set -euo pipefail
ACTION=push
source "$(dirname -- "${BASH_SOURCE[0]}")/_shared/common.sh"
main "$@"
