#!/usr/bin/env bash
set -euo pipefail
repository="${1:?Source checkout path required}"

source_git() {
    local url="$1"
    shift
    if [[ "$url" == https://github.com/* ]]; then
        printf 'GitHub source login: use a GitHub PAT with repository Contents: Read access. It is not saved.\n'
        GIT_ASKPASS="$(dirname "${BASH_SOURCE[0]}")/github_askpass.py" GIT_TERMINAL_PROMPT=0 \
            git -c credential.helper= -c core.askPass= "$@"
    else
        git "$@"
    fi
}

if [[ ! -e "$repository" && ! -L "$repository" ]]; then
    name="$(basename "$repository")"
    case "$name" in
        Orion-Intelligence|Orion-Micros|Orion-Social|Orion-Dark-Nexus|Orion-mail|Orion-Tor2Web) ;;
        *) printf 'Unknown source repository: %s\n' "$name" >&2; exit 1 ;;
    esac
    origin="https://github.com/Orion-Intelligence/$name.git"
    printf 'Cloning %s (trusted-main) into %s\n' "$origin" "$repository"
    source_git "$origin" clone --branch trusted-main --single-branch -- "$origin" "$repository"
else
    [[ -d "$repository/.git" || -f "$repository/.git" ]] || {
        printf 'Existing path is not a Git source checkout: %s. Move it aside manually before retrying.\n' "$repository" >&2; exit 1;
    }
    [[ -z "$(git -C "$repository" status --porcelain)" ]] || {
        printf 'Refusing to update dirty source checkout: %s. Commit or stash your work first.\n' "$repository" >&2; exit 1;
    }
    origin="$(git -C "$repository" remote get-url origin)"
    source_git "$origin" -C "$repository" fetch origin refs/heads/trusted-main:refs/remotes/origin/trusted-main
fi
if git -C "$repository" show-ref --verify --quiet refs/heads/trusted-main; then
    git -C "$repository" merge-base --is-ancestor trusted-main origin/trusted-main || {
        printf 'Local trusted-main is ahead/diverged in %s; reconcile it manually.\n' "$repository" >&2; exit 1;
    }
    git -C "$repository" switch trusted-main
else
    git -C "$repository" switch --track -c trusted-main origin/trusted-main
fi
git -C "$repository" merge --ff-only origin/trusted-main
[[ "$(git -C "$repository" rev-parse HEAD)" == "$(git -C "$repository" rev-parse origin/trusted-main)" ]] || exit 1
printf 'Building %s from trusted-main at %s\n' "$repository" "$(git -C "$repository" rev-parse --short HEAD)"
