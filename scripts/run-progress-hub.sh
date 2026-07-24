#!/usr/bin/env bash
set -euo pipefail

fail() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

if (( $# != 3 )); then
    printf 'Usage: %s /private/status.json /private/media-root AGENT_BOARD_URL\n' "${0##*/}" >&2
    exit 64
fi
[[ $(uname -s) == Linux ]] || fail 'run the progress hub on the Spark'
(( ${EUID:-$(id -u)} != 0 )) || fail 'run as the normal workspace user'
for command_name in python3 tailscale; do
    command -v "$command_name" >/dev/null 2>&1 || fail "missing command: $command_name"
done
status=$1
media_root=$2
board_url=$3
[[ -f $status && ! -L $status && -d $media_root && ! -L $media_root ]] || \
    fail 'status and media inputs must be real private paths'
host=$(tailscale ip -4 | head -n1)
[[ -n $host ]] || fail 'no Tailscale IPv4 address is available'
script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
exec python3 "$script_dir/../tools/progress_hub.py" \
    --host "$host" --port 8474 --status "$status" --media-root "$media_root" \
    --agent-board-url "$board_url"

