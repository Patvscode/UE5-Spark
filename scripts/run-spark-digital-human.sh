#!/usr/bin/env bash
set -euo pipefail

usage() {
    printf 'Usage: %s /path/to/FayAvatarRuntime-Arm64.sh [Unreal arguments...]\n' \
        "${0##*/}" >&2
    printf 'Discovers the existing private Fay/MCP listeners and launches the packaged avatar.\n' >&2
}

fail() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

if (( $# < 1 )); then
    usage
    exit 64
fi
if [[ $(uname -s) != Linux || $(uname -m) != aarch64 ]]; then
    fail "the Spark stack launcher requires Linux/aarch64, not $(uname -s)/$(uname -m)"
fi
if (( ${EUID:-$(id -u)} == 0 )); then
    fail 'run the digital human as the normal workspace owner, not root'
fi

for command_name in curl python3 ss; do
    command -v "$command_name" >/dev/null 2>&1 || \
        fail "required command is missing: $command_name"
done

launcher_input=$1
shift
[[ -f $launcher_input ]] || fail "package launcher does not exist: $launcher_input"
launcher_dir=$(cd "$(dirname "$launcher_input")" && pwd -P)
launcher="$launcher_dir/$(basename "$launcher_input")"

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
runtime_launcher="$script_dir/run-cooked-package.sh"
[[ -x $runtime_launcher ]] || fail "the guarded package launcher is missing: $runtime_launcher"

require_mcp=${UE5_SPARK_REQUIRE_MCP:-1}
if [[ $require_mcp != 0 && $require_mcp != 1 ]]; then
    fail 'UE5_SPARK_REQUIRE_MCP must be 0 or 1'
fi

resolve_private_listener() {
    local port=$1
    python3 - "$port" <<'PY'
import ipaddress
import subprocess
import sys


port = int(sys.argv[1])
result = subprocess.run(
    ("ss", "-H", "-ltn", f"sport = :{port}"),
    check=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.DEVNULL,
    text=True,
)

addresses = []
for line in result.stdout.splitlines():
    fields = line.split()
    if len(fields) < 4:
        continue
    endpoint = fields[3]
    if endpoint.startswith("["):
        closing = endpoint.rfind("]:")
        host = endpoint[1:closing] if closing > 0 else ""
    else:
        host, separator, service = endpoint.rpartition(":")
        if not separator or service != str(port):
            continue
    if not host or host == "*" or "%" in host:
        raise SystemExit(2)
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        raise SystemExit(2)
    if address.is_unspecified or address.is_multicast or address.is_global:
        raise SystemExit(2)
    addresses.append(address)

unique_addresses = sorted(
    set(addresses),
    key=lambda value: (not value.is_loopback, value.version, str(value)),
)
if not unique_addresses:
    raise SystemExit(3)

print(unique_addresses[0].compressed)
PY
}

url_host() {
    if [[ $1 == *:* ]]; then
        printf '[%s]' "$1"
    else
        printf '%s' "$1"
    fi
}

http_ready() {
    local host=$1
    local port=$2
    local path=$3
    local formatted_host
    formatted_host=$(url_host "$host")
    local code
    code=$(curl --silent --show-error --output /dev/null \
        --noproxy '*' \
        --connect-timeout 2 --max-time 3 --write-out '%{http_code}' \
        "http://$formatted_host:$port$path" 2>/dev/null || true)
    [[ $code =~ ^[23][0-9][0-9]$ ]]
}

tcp_ready() {
    local host=$1
    local port=$2
    python3 - "$host" "$port" <<'PY'
import socket
import sys


with socket.create_connection((sys.argv[1], int(sys.argv[2])), timeout=2):
    pass
PY
}

fay_http_host=$(resolve_private_listener 5000) || \
    fail 'Fay HTTP/audio is not listening on one unambiguous private interface'
fay_avatar_host=$(resolve_private_listener 10002) || \
    fail 'Fay avatar WebSocket is not listening on one unambiguous private interface'

http_ready "$fay_http_host" 5000 / || fail 'Fay HTTP/audio did not pass its readiness probe'
tcp_ready "$fay_avatar_host" 10002 || fail 'Fay avatar WebSocket did not pass its TCP probe'
printf 'Fay HTTP/audio and avatar WebSocket are ready.\n'

if [[ $require_mcp == 1 ]]; then
    fay_mcp_admin_host=$(resolve_private_listener 5010) || \
        fail 'Fay MCP administration is not listening on one unambiguous private interface'
    fay_mcp_sse_host=$(resolve_private_listener 8766) || \
        fail 'Fay MCP SSE is not listening on one unambiguous private interface'
    http_ready "$fay_mcp_admin_host" 5010 / || \
        fail 'Fay MCP administration did not pass its readiness probe'
    http_ready "$fay_mcp_sse_host" 8766 /sse || \
        fail 'Fay MCP SSE did not pass its readiness probe'
    printf 'Fay MCP administration and SSE are ready.\n'
fi

formatted_http_host=$(url_host "$fay_http_host")
formatted_avatar_host=$(url_host "$fay_avatar_host")
export FAY_AUDIO_BASE_URL="http://$formatted_http_host:5000/audio/"
export FAY_WS_URL="ws://$formatted_avatar_host:10002"

printf 'Starting the packaged digital human with discovered private Fay endpoints.\n'
exec "$runtime_launcher" "$launcher" "$@"
