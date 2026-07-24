#!/usr/bin/env bash
set -euo pipefail

usage() {
    printf 'Usage: %s /path/to/cooker-workspace /path/to/isolated/UnrealEngine /path/to/FayFabAcquisition.uproject /path/to/private-baseline.json\n' \
        "${0##*/}" >&2
    printf 'Starts one tailnet-only, ten-minute Epic/Fab phone authorization session.\n' >&2
}

fail() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

if (( $# != 4 )); then
    usage
    exit 64
fi
if [[ $(uname -s) != Linux || $(uname -m) != aarch64 ]]; then
    fail "Fab phone authorization requires Linux/aarch64, not $(uname -s)/$(uname -m)"
fi
if (( ${EUID:-$(id -u)} == 0 )); then
    fail 'run Fab phone authorization as the normal workspace owner, not root'
fi
for command_name in basename chmod cmp curl dirname file flock grep head id install jq mkfifo \
    mktemp nice openssl ps readlink rm sed sleep ss systemctl tailscale \
    timeout; do
    command -v "$command_name" >/dev/null 2>&1 || \
        fail "required command is missing: $command_name"
done
host_python=/usr/bin/python3
[[ -x $host_python ]] || fail "fixed host Python is unavailable: $host_python"

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
phase_lock="$script_dir/fab-phase-lock.sh"
[[ -f $phase_lock && ! -L $phase_lock ]] || \
    fail "shared Fab phase-lock helper is missing: $phase_lock"
# shellcheck source=fab-phase-lock.sh
source "$phase_lock"

workspace=$(cd "$1" && pwd -P)
engine_root=$(cd "$2" && pwd -P)
project_input=$3
manifest_input=$4
[[ -f $project_input && ! -L $project_input ]] || fail "project does not exist: $project_input"
[[ -f $manifest_input && ! -L $manifest_input ]] || fail 'private baseline manifest is missing'
project_dir=$(cd "$(dirname "$project_input")" && pwd -P)
project="$project_dir/$(basename "$project_input")"
manifest=$(cd "$(dirname "$manifest_input")" && pwd -P)/$(basename "$manifest_input")
case "$engine_root/" in
    "$workspace"/*) ;;
    *) fail 'the isolated Engine must remain below the cooker workspace' ;;
esac
case "$project_dir/" in
    "$workspace"/fab-acquisition-staging/FayFabAcquisition/) ;;
    *) fail 'the Fab project must be the dedicated acquisition-staging project' ;;
esac
case "$manifest" in
    "$workspace"/logs-private/fab-acquisition/*) ;;
    *) fail 'the baseline must remain in the private Fab log directory' ;;
esac
[[ ${project##*/} == FayFabAcquisition.uproject ]] || \
    fail 'the reviewed staging descriptor must be named FayFabAcquisition.uproject'

preflight="$script_dir/run-fex-fab-staging.sh"
runner="$script_dir/run-fex-rootless.sh"
relay="$script_dir/fab-auth-relay.py"
manifest_tool="$script_dir/fab-staging-manifest.py"
project_template="$script_dir/../staging/fab-acquisition-template/FayFabAcquisition.uproject"
editor="$engine_root/Engine/Binaries/Linux/UnrealEditor"
engine_version="$engine_root/Engine/Binaries/Linux/UnrealEditor.version"
fab_binary="$engine_root/Engine/Plugins/Fab/Binaries/Linux/libUnrealEditor-Fab.so"
fab_modules="$engine_root/Engine/Plugins/Fab/Binaries/Linux/UnrealEditor.modules"
fab_downloader="$engine_root/Engine/Plugins/Fab/ThirdParty/libBuildPatchInstallerLib.so"
epic_web_helper="$engine_root/Engine/Binaries/Linux/EpicWebHelper"
guest_portal="$workspace/rootfs/ubuntu-24.04-x86_64/usr/bin/xdg-open"
private_state="$workspace/state/fab-acquisition"
private_logs="$workspace/logs-private/fab-acquisition"
backend_port=18790
tailnet_port=8474

for required in "$preflight" "$runner" "$relay" "$manifest_tool" "$project_template" \
    "$editor" "$engine_version" "$fab_binary" "$fab_modules" "$fab_downloader" \
    "$epic_web_helper" "$guest_portal"; do
    [[ -f $required && ! -L $required ]] || fail "required input is missing: $required"
done
[[ -x $preflight && -x $runner && -x $relay && -x $editor && -x $guest_portal ]] || \
    fail 'one or more reviewed launch inputs are not executable'
grep -qx '# UE5-SPARK-FEX-XDG-OPEN-PORTAL-V3' "$guest_portal" || \
    fail 'the phone-capable guarded FEX portal adapter is missing'
"$preflight" --check "$workspace" "$engine_root" "$project" "$manifest" >/dev/null
fab_phase_lock_acquire "$workspace" || exit 1

# The first check gives a useful standalone diagnostic. Repeat every mutable,
# authoritative input check after owning the common phase lock so no other
# cooperating Fab phase can change the project between preflight and launch.
for required in "$preflight" "$runner" "$relay" "$manifest_tool" "$project_template" \
    "$editor" "$engine_version" "$fab_binary" "$fab_modules" "$fab_downloader" \
    "$epic_web_helper" "$guest_portal"; do
    [[ -f $required && ! -L $required ]] || fail "required input changed after preflight: $required"
done
for forbidden in Source Plugins; do
    [[ ! -e $project_dir/$forbidden && ! -L $project_dir/$forbidden ]] || \
        fail "the content-only staging project must not contain $forbidden"
done
file "$editor" | grep -q 'x86-64' || fail 'the isolated Unreal Editor is not x86-64'
file "$fab_binary" | grep -q 'x86-64' || fail 'the Fab Editor module is not x86-64'
file "$fab_downloader" | grep -q 'x86-64' || fail 'the Fab downloader is not x86-64'
file "$epic_web_helper" | grep -q 'x86-64' || fail 'EpicWebHelper is not x86-64'
grep -qx '# UE5-SPARK-FEX-XDG-OPEN-PORTAL-V3' "$guest_portal" || \
    fail 'the phone-capable guarded FEX portal adapter changed after preflight'
cmp -s "$project_template" "$project" || \
    fail 'the staging descriptor changed after preflight'
read_build_id() {
    sed -n 's/.*"BuildId"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$1" | head -1
}
engine_build_id=$(read_build_id "$engine_version")
[[ -n $engine_build_id && $(read_build_id "$fab_modules") == "$engine_build_id" ]] || \
    fail 'the Fab module manifest changed after preflight'
"$host_python" "$manifest_tool" verify "$project_dir" "$manifest" >/dev/null || \
    fail 'the staging baseline changed after preflight'
systemctl --user is-active ue5-spark-avatar-live.service >/dev/null || \
    fail 'the live avatar service is not active; refusing to hide a pre-existing failure'
fab_owned_directory "$workspace/logs-private" shared || exit 1
fab_owned_directory "$private_logs" private || exit 1
fab_owned_directory "$workspace/state" shared || exit 1
fab_owned_directory "$private_state" private || exit 1
for private_directory in home config cache data state; do
    fab_owned_directory "$private_state/$private_directory" private || exit 1
done

if ss -ltnH "sport = :$backend_port" | grep -q .; then
    fail "loopback relay port is already in use: $backend_port"
fi
if tailscale serve status --json | jq -e --arg port "$tailnet_port" \
    '.TCP[$port] != null' >/dev/null; then
    fail "Tailscale Serve port is already assigned: $tailnet_port"
fi
if ps -u "$(id -u)" -o args= | grep -F "$editor $project" | grep -v grep >/dev/null; then
    fail 'the Fab staging Editor is already running'
fi

session_dir=$(mktemp -d "$private_state/phone-auth.XXXXXX")
chmod 0700 "$session_dir"
fifo="$session_dir/activation.fifo"
token_file="$session_dir/relay-token"
relay_log="$private_logs/phone-auth-relay.$(basename "$session_dir").log"
editor_log="$private_logs/editor-phone-auth.$(basename "$session_dir").log"
mkfifo -m 0600 "$fifo"
umask 077
openssl rand -hex 24 >"$token_file"
chmod 0600 "$token_file"
: >"$relay_log"
: >"$editor_log"
chmod 0600 "$relay_log" "$editor_log"

relay_pid=
serve_added=0
editor_pid=
cleanup() {
    local status=$?
    local cleanup_status=$status
    trap - EXIT HUP INT TERM
    if [[ -n $editor_pid ]] && ps -p "$editor_pid" >/dev/null 2>&1; then
        kill -TERM "$editor_pid" 2>/dev/null || true
        for _attempt in {1..25}; do
            ps -p "$editor_pid" >/dev/null 2>&1 || break
            sleep 1
        done
    fi
    if (( serve_added == 1 )); then
        if ! tailscale serve --https="$tailnet_port" off >/dev/null 2>&1; then
            printf 'error: failed to remove the temporary Tailscale Serve route\n' >&2
            cleanup_status=1
        elif tailscale serve status --json | jq -e --arg port "$tailnet_port" \
            '.TCP[$port] != null' >/dev/null; then
            printf 'error: temporary Tailscale Serve route remained after removal\n' >&2
            cleanup_status=1
        fi
    fi
    if [[ -n $relay_pid ]] && ps -p "$relay_pid" >/dev/null 2>&1; then
        kill -TERM "$relay_pid" 2>/dev/null || true
    fi
    case "$session_dir" in
        "$private_state"/phone-auth.*) rm -rf -- "$session_dir" ;;
        *)
            printf 'error: refusing unsafe phone-auth cleanup target\n' >&2
            cleanup_status=1
            ;;
    esac
    exit "$cleanup_status"
}
trap cleanup EXIT HUP INT TERM

fab_phase_lock_exec_without_fd "$relay" \
    --fifo "$fifo" --token-file "$token_file" --bind 127.0.0.1 \
    --port "$backend_port" >"$relay_log" 2>&1 &
relay_pid=$!
for _attempt in 1 2 3 4 5 6 7 8 9 10; do
    if curl --fail --silent --max-time 1 \
        "http://127.0.0.1:$backend_port/healthz" >/dev/null; then
        break
    fi
    sleep 1
done
curl --fail --silent --show-error --max-time 1 \
    "http://127.0.0.1:$backend_port/healthz" >/dev/null || \
    fail "phone authorization relay did not become healthy; inspect $relay_log"

tailscale serve --bg --yes --https="$tailnet_port" \
    "http://127.0.0.1:$backend_port" >/dev/null
serve_added=1
tailnet_name=$(tailscale status --json | jq -r '.Self.DNSName | rtrimstr(".")')
[[ -n $tailnet_name && $tailnet_name != null ]] || fail 'could not determine Spark MagicDNS name'
relay_token=$(<"$token_file")
[[ $relay_token =~ ^[a-f0-9]{48}$ ]] || fail 'generated relay token is malformed'

printf 'PHONE_AUTH_URL=https://%s:%s/%s\n' "$tailnet_name" "$tailnet_port" "$relay_token"
printf 'The tailnet-only page shows one validated Epic device code and links to Epic activation.\n'
printf 'The authorization session expires automatically after twelve minutes.\n'

export DISPLAY=${DISPLAY:-:1}
export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-"/run/user/$(id -u)"}
export DBUS_SESSION_BUS_ADDRESS=${DBUS_SESSION_BUS_ADDRESS:-"unix:path=$XDG_RUNTIME_DIR/bus"}
export XAUTHORITY=${XAUTHORITY:-"$XDG_RUNTIME_DIR/gdm/Xauthority"}
export VK_DRIVER_FILES=${VK_DRIVER_FILES:-/usr/share/vulkan/icd.d/nvidia_icd.json}
export FEX_SILENTLOG=${FEX_SILENTLOG:-1}
export HOME="$private_state/home"
export XDG_CONFIG_HOME="$private_state/config"
export XDG_CACHE_HOME="$private_state/cache"
export XDG_DATA_HOME="$private_state/data"
export XDG_STATE_HOME="$private_state/state"
export UE5_SPARK_FAB_AUTH_FIFO="$fifo"

fab_phase_lock_exec_without_fd nice -n 15 \
    timeout --signal=TERM --kill-after=20s 12m \
    "$runner" "$workspace" -- "$editor" "$project" \
    -nullrhi -log -NoSplash -NoSound -NoSourceControl -NoCompile -NoCompileEditor \
    -corelimit=2 -onethread -norhithread -nogpucrashdebugging \
    -ExecCmds=Fab.Login >"$editor_log" 2>&1 &
editor_pid=$!
auth_complete=0
while ps -p "$editor_pid" >/dev/null 2>&1; do
    if grep -Eq 'LogFab:.*User logged in' "$editor_log"; then
        auth_complete=1
        sleep 5
        kill -TERM "$editor_pid" 2>/dev/null || true
        break
    fi
    sleep 2
done
set +e
wait "$editor_pid"
editor_status=$?
set -e
editor_pid=

"$host_python" "$manifest_tool" verify "$project_dir" "$manifest" >/dev/null || \
    fail 'Fab changed non-content staging state; preserve and review the private evidence'
if (( auth_complete == 1 )); then
    printf 'FAB_AUTH_COMPLETE_OK\n'
elif (( editor_status == 124 || editor_status == 137 )); then
    fail "the phone authorization session expired; start a fresh one"
elif (( editor_status != 0 )); then
    fail "the Fab Editor exited with status $editor_status; inspect $editor_log"
fi
printf 'Fab phone authorization Editor exited normally.\n'
