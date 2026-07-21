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

for command_name in awk curl id nvidia-smi python3 sleep ss; do
    command -v "$command_name" >/dev/null 2>&1 || \
        fail "required command is missing: $command_name"
done

# Spark's CPU and GPU share the same physical memory. Low GPU utilization is
# therefore not enough to prove that Vulkan can allocate a graphics context:
# idle model servers can still reserve most of unified memory. Headless NullRHI
# diagnostics do not create a Vulkan device and intentionally skip this gate.
uses_vulkan=1
for argument in "$@"; do
    if [[ ${argument,,} == -nullrhi ]]; then
        uses_vulkan=0
        break
    fi
done

if (( uses_vulkan == 1 )); then
    if [[ -z ${DISPLAY:-} ]]; then
        command -v systemctl >/dev/null 2>&1 || \
            fail 'DISPLAY is unset and systemctl is unavailable for local-session discovery'
        user_service_environment=$(systemctl --user show-environment 2>/dev/null || true)
        discovered_display=$(awk -F= \
            '$1 == "DISPLAY" {sub(/^[^=]*=/, ""); print; exit}' \
            <<<"$user_service_environment")
        [[ $discovered_display =~ ^:[0-9]+([.][0-9]+)?$ ]] || \
            fail 'DISPLAY is unset and no unambiguous local X11 display was found'
        display_number=${discovered_display#:}
        display_number=${display_number%%.*}
        display_socket="/tmp/.X11-unix/X$display_number"
        [[ -S $display_socket && -O $display_socket ]] || \
            fail "the discovered X11 socket is missing or not owned by this user: $display_socket"
        export DISPLAY="$discovered_display"
        printf 'Using existing local X11 display %s.\n' "$DISPLAY"
    fi

    if [[ $DISPLAY =~ ^:([0-9]+)([.][0-9]+)?$ ]]; then
        display_socket="/tmp/.X11-unix/X${BASH_REMATCH[1]}"
        [[ -S $display_socket && -O $display_socket ]] || \
            fail "the selected local X11 socket is missing or not owned by this user: $display_socket"
        if [[ -z ${XDG_RUNTIME_DIR:-} ]]; then
            candidate_runtime_dir="/run/user/$(id -u)"
            [[ -d $candidate_runtime_dir && -O $candidate_runtime_dir ]] || \
                fail "the local desktop runtime directory is unavailable: $candidate_runtime_dir"
            export XDG_RUNTIME_DIR="$candidate_runtime_dir"
        fi
        [[ -d $XDG_RUNTIME_DIR && -O $XDG_RUNTIME_DIR ]] || \
            fail "the local desktop runtime directory is missing or not owned by this user: $XDG_RUNTIME_DIR"
        if [[ -z ${XAUTHORITY:-} && -r $XDG_RUNTIME_DIR/gdm/Xauthority &&
            -O $XDG_RUNTIME_DIR/gdm/Xauthority ]]; then
            export XAUTHORITY="$XDG_RUNTIME_DIR/gdm/Xauthority"
        fi
        [[ -n ${XAUTHORITY:-} ]] || \
            fail 'the selected local X11 display has no same-user readable XAUTHORITY file'
        [[ -r $XAUTHORITY && -O $XAUTHORITY ]] || \
            fail "the selected XAUTHORITY file is unreadable or not owned by this user: $XAUTHORITY"
    fi
fi

min_available_memory_gib=${UE5_SPARK_MIN_AVAILABLE_MEMORY_GIB:-48}
[[ $min_available_memory_gib =~ ^([0-9]|[1-9][0-9]|1[01][0-9]|12[0-8])$ ]] || \
    fail 'UE5_SPARK_MIN_AVAILABLE_MEMORY_GIB must be an integer from 0 through 128'
if (( uses_vulkan == 1 && min_available_memory_gib > 0 )); then
    available_memory_kib=$(awk '/^MemAvailable:/ { print $2; exit }' /proc/meminfo)
    [[ $available_memory_kib =~ ^[0-9]+$ ]] || \
        fail 'could not read available unified memory from /proc/meminfo'
    required_memory_kib=$((min_available_memory_gib * 1024 * 1024))
    (( available_memory_kib >= required_memory_kib )) || \
        fail "only $((available_memory_kib / 1024 / 1024)) GiB of unified memory is available; Vulkan launch requires ${min_available_memory_gib} GiB"
fi

max_start_gpu_utilization=${UE5_SPARK_MAX_START_GPU_UTILIZATION:-85}
[[ $max_start_gpu_utilization =~ ^([0-9]|[1-9][0-9]|100)$ ]] || \
    fail 'UE5_SPARK_MAX_START_GPU_UTILIZATION must be an integer from 0 through 100'
high_gpu_samples=0
for _ in 1 2 3; do
    gpu_utilization=$(nvidia-smi --query-gpu=utilization.gpu \
        --format=csv,noheader,nounits 2>/dev/null | head -n1 | tr -d ' ' || true)
    [[ $gpu_utilization =~ ^([0-9]|[1-9][0-9]|100)$ ]] || \
        fail 'could not read shared GPU utilization'
    if (( gpu_utilization > max_start_gpu_utilization )); then
        ((++high_gpu_samples))
    fi
    sleep 1
done
(( high_gpu_samples < 3 )) || \
    fail "shared GPU utilization remained above ${max_start_gpu_utilization}%; defer the avatar launch"

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
