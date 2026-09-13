#!/usr/bin/env bash
set -euo pipefail
[[ $# -ge 2 ]] || { printf 'A menu title and options are required.\n' >&2; exit 1; }
exec 3<>/dev/tty || { printf 'Run this menu in an interactive terminal.\n' >&2; exit 1; }
title="$1"
shift
options=("$@")
cursor=0
cleanup() { printf '\033[?25h\033[?1049l' >&3; }
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
printf '\033[?1049h\033[?25l' >&3
while true; do
    printf '\033[H\033[2J%s\n\nArrows: choose | Space: select | Enter: confirm | q/Esc: cancel\n\n' "$title" >&3
    for index in "${!options[@]}"; do
        if ((index == cursor)); then
            printf '\033[7m  (*) %s\033[0m\n' "${options[index]}" >&3
        else
            printf '  ( ) %s\n' "${options[index]}" >&3
        fi
    done
    IFS= read -u 3 -rsn1 key || exit 130
    if [[ "$key" == $'\033' ]]; then
        suffix=''
        IFS= read -u 3 -rsn2 -t 0.15 suffix || true
        key+="$suffix"
    fi
    case "$key" in
        $'\033[A'|$'\033[D'|$'\033OA'|$'\033OD'|k|h) cursor=$(((cursor + ${#options[@]} - 1) % ${#options[@]})) ;;
        $'\033[B'|$'\033[C'|$'\033OB'|$'\033OC'|j|l) cursor=$(((cursor + 1) % ${#options[@]})) ;;
        ' ') ;;
        '') printf '%s\n' "$((cursor + 1))"; exit 0 ;;
        q|Q|$'\033'|$'\004') exit 130 ;;
    esac
done
