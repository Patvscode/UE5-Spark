#!/usr/bin/env bash
set -euo pipefail

fail() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

if (( $# != 2 )); then
    printf 'Usage: %s /private/media-root /path/to/built/dist/client\n' "${0##*/}" >&2
    exit 64
fi

[[ $(uname -s) == Linux ]] || fail 'run the private controller on the Spark'
(( ${EUID:-$(id -u)} != 0 )) || fail 'run as the normal workspace user'
for command_name in python3 tailscale; do
    command -v "$command_name" >/dev/null 2>&1 || fail "missing command: $command_name"
done

media_root=$1
dist_root=$2
[[ -d $media_root && ! -L $media_root ]] || fail 'media root must be a real directory'
[[ -d $dist_root && ! -L $dist_root ]] || fail 'built client must be a real directory'

tailnet_ip=$(tailscale ip -4 | head -n1)
[[ -n $tailnet_ip ]] || fail 'no Tailscale IPv4 address is available'
script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)

exec python3 "$script_dir/../apps/private-controller/server/controller_server.py" \
    --host 127.0.0.1 \
    --port 8475 \
    --dist "$dist_root" \
    --media-root "$media_root" \
    --fay-base "http://$tailnet_ip:5000" \
    --ardy-base http://127.0.0.1:8777
