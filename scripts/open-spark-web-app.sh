#!/usr/bin/env bash
set -euo pipefail

fail() {
    local message=$1
    printf 'error: %s\n' "$message" >&2
    if command -v zenity >/dev/null 2>&1; then
        zenity --error --title="$title" --text="$message" >/dev/null 2>&1 || true
    fi
    exit 1
}

[[ $(uname -s) == Linux && $(uname -m) == aarch64 ]] || {
    printf 'error: run this application on the Linux ARM64 DGX Spark\n' >&2
    exit 1
}
(( ${EUID:-$(id -u)} != 0 )) || {
    printf 'error: run this application as the normal desktop user\n' >&2
    exit 1
}

case "${1:-}" in
    avatar)
        title='UE5 Spark Avatar'
        service=ue5-spark-private-controller.service
        health_url=http://127.0.0.1:8475/
        app_url=https://spark-ccb2-1.tail2b1107.ts.net:8475/
        wait_seconds=30
        browser_class=UE5SparkAvatar
        ;;
    ardy)
        title='NVIDIA ARDY Character Lab'
        service=ue5-spark-ardy-viser-lab.service
        health_url=http://127.0.0.1:2334/
        app_url=https://spark-ccb2-1.tail2b1107.ts.net:8477/
        wait_seconds=180
        browser_class=NVIDIAARDYCharacterLab
        ;;
    *)
        printf 'Usage: %s avatar|ardy\n' "${0##*/}" >&2
        exit 64
        ;;
esac

for command_name in curl systemctl; do
    command -v "$command_name" >/dev/null 2>&1 || \
        fail "Required command is missing: $command_name"
done

if ! systemctl --user is-active --quiet "$service"; then
    if command -v notify-send >/dev/null 2>&1; then
        notify-send "$title" 'Starting its local service…' >/dev/null 2>&1 || true
    fi
    systemctl --user start "$service" || \
        fail "Could not start $service. Check its user-service log."
fi

ready=0
for ((attempt = 0; attempt < wait_seconds; attempt++)); do
    if curl --fail --silent --show-error --max-time 2 \
        --output /dev/null "$health_url"; then
        ready=1
        break
    fi
    if systemctl --user is-failed --quiet "$service"; then
        break
    fi
    sleep 1
done
(( ready == 1 )) || \
    fail "$title did not become ready. Check: journalctl --user -u $service"

if [[ -x /snap/bin/chromium ]]; then
    exec /snap/bin/chromium \
        "--app=$app_url" \
        --start-maximized \
        "--class=$browser_class"
elif command -v chromium >/dev/null 2>&1; then
    exec chromium \
        "--app=$app_url" \
        --start-maximized \
        "--class=$browser_class"
elif command -v xdg-open >/dev/null 2>&1; then
    exec xdg-open "$app_url"
else
    fail 'No supported browser launcher was found'
fi
