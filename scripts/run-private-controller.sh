#!/usr/bin/env bash
set -euo pipefail

fail() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

if (( $# != 5 )); then
    printf 'Usage: %s /private/media-root /path/to/built/dist/client /run/user/UID/live-root /private/config-workspace /path/to/UE5-Spark\n' \
        "${0##*/}" >&2
    exit 64
fi

[[ $(uname -s) == Linux ]] || fail 'run the private controller on the Spark'
(( ${EUID:-$(id -u)} != 0 )) || fail 'run as the normal workspace user'
for command_name in python3 stat tailscale; do
    command -v "$command_name" >/dev/null 2>&1 || fail "missing command: $command_name"
done

media_root=$1
dist_root=$2
live_root=$3
config_workspace=$4
project_root=$5
[[ -d $media_root && ! -L $media_root ]] || fail 'media root must be a real directory'
[[ -d $dist_root && ! -L $dist_root ]] || fail 'built client must be a real directory'
[[ -d $live_root && ! -L $live_root && -O $live_root ]] || \
    fail 'live root must be a real directory owned by this user'
[[ $(stat -c '%a' "$live_root") == 700 ]] || fail 'live root must have mode 0700'
[[ -d $config_workspace && ! -L $config_workspace && -O $config_workspace ]] || \
    fail 'config workspace must be a real directory owned by this user'
[[ $(stat -c '%a' "$config_workspace") == 700 ]] || \
    fail 'config workspace must have mode 0700'
[[ -d $project_root && ! -L $project_root ]] || \
    fail 'project root must be a real directory'

tailnet_ip=$(tailscale ip -4 | head -n1)
[[ -n $tailnet_ip ]] || fail 'no Tailscale IPv4 address is available'
script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)

exec python3 "$script_dir/../apps/private-controller/server/controller_server.py" \
    --host 127.0.0.1 \
    --port 8475 \
    --dist "$dist_root" \
    --media-root "$media_root" \
    --live-root "$live_root" \
    --fay-base "http://$tailnet_ip:5000" \
    --ardy-base http://127.0.0.1:8777 \
    --llm-base http://127.0.0.1:8090 \
    --llm-model qwen3-4b-q4-k-m \
    --config-workspace "$config_workspace" \
    --project-root "$project_root" \
    --enable-service-control
