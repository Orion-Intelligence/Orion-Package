#!/usr/bin/env bash
set -euo pipefail
repository="$1"
[[ -d "$repository/.git" || -f "$repository/.git" ]] || { printf 'Missing Git source checkout: %s\n' "$repository" >&2; exit 1; }
[[ -z "$(git -C "$repository" status --porcelain)" ]] || {
    printf 'Refusing to update dirty source checkout: %s. Commit or stash your work first.\n' "$repository" >&2; exit 1;
}
git -C "$repository" fetch origin refs/heads/trusted-main:refs/remotes/origin/trusted-main
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
