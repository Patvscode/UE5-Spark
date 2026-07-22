#!/usr/bin/env bash
set -euo pipefail

usage() {
    printf 'Usage: %s [--check] /path/to/cooker-workspace /path/to/isolated/UnrealEngine /path/to/FayFabAcquisition.uproject /path/to/private-offline-baseline.json\n' \
        "${0##*/}" >&2
    printf 'Runs the fixed Casual Girl inventory with Fab and Internet sockets disabled.\n' >&2
}

fail() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

check_only=0
if [[ ${1:-} == --check ]]; then
    check_only=1
    shift
fi
if (( $# != 4 )); then
    usage
    exit 64
fi
if [[ $(uname -s) != Linux || $(uname -m) != aarch64 ]]; then
    fail "the offline Fab review requires Linux/aarch64, not $(uname -s)/$(uname -m)"
fi
if (( ${EUID:-$(id -u)} == 0 )); then
    fail 'run the offline Fab review as the normal workspace owner, not root'
fi
for command_name in cmp file flock grep id mkdir mktemp nice python3 sed \
    systemctl systemd-run timeout; do
    command -v "$command_name" >/dev/null 2>&1 || \
        fail "required command is missing: $command_name"
done

workspace=$(cd "$1" && pwd -P)
engine_root=$(cd "$2" && pwd -P)
project_input=$3
manifest_input=$4
[[ -f $project_input && ! -L $project_input ]] || fail "project does not exist: $project_input"
[[ -f $manifest_input && ! -L $manifest_input ]] || fail 'private offline baseline is missing'
project_dir=$(cd "$(dirname "$project_input")" && pwd -P)
project="$project_dir/$(basename "$project_input")"
manifest=$(cd "$(dirname "$manifest_input")" && pwd -P)/$(basename "$manifest_input")
case "$engine_root/" in
    "$workspace"/*) ;;
    *) fail 'the isolated Engine must remain below the cooker workspace' ;;
esac
case "$project_dir/" in
    "$workspace"/fab-acquisition-staging/FayFabAcquisition/) ;;
    *) fail 'the Fab project must be the dedicated staging project' ;;
esac
case "$manifest" in
    "$workspace"/logs-private/fab-acquisition/*) ;;
    *) fail 'the offline baseline must remain in the private Fab log directory' ;;
esac

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
runner="$script_dir/run-fex-rootless.sh"
non_content_tool="$script_dir/fab-staging-manifest.py"
content_tool="$script_dir/fab-content-manifest.py"
inventory_script="$script_dir/inspect-fab-casual-girl.py"
offline_template="$script_dir/../staging/fab-offline-template/FayFabAcquisition.uproject"
content_manifest="$workspace/logs-private/fab-acquisition/casual-girl-content-before-migration.json"
transition_receipt="$workspace/logs-private/fab-acquisition/offline-transition.json"
editor="$engine_root/Engine/Binaries/Linux/UnrealEditor-Cmd"
engine_version="$engine_root/Engine/Binaries/Linux/UnrealEditor.version"
python_binary="$engine_root/Engine/Plugins/Experimental/PythonScriptPlugin/Binaries/Linux/libUnrealEditor-PythonScriptPlugin.so"
python_modules="$engine_root/Engine/Plugins/Experimental/PythonScriptPlugin/Binaries/Linux/UnrealEditor.modules"
scripting_binary="$engine_root/Engine/Plugins/Editor/EditorScriptingUtilities/Binaries/Linux/libUnrealEditor-EditorScriptingUtilities.so"
scripting_modules="$engine_root/Engine/Plugins/Editor/EditorScriptingUtilities/Binaries/Linux/UnrealEditor.modules"
chaos_binary="$engine_root/Engine/Plugins/ChaosCloth/Binaries/Linux/libUnrealEditor-ChaosCloth.so"
chaos_editor_binary="$engine_root/Engine/Plugins/ChaosCloth/Binaries/Linux/libUnrealEditor-ChaosClothEditor.so"
chaos_modules="$engine_root/Engine/Plugins/ChaosCloth/Binaries/Linux/UnrealEditor.modules"

for required in "$runner" "$non_content_tool" "$content_tool" "$inventory_script" \
    "$offline_template" "$content_manifest" "$transition_receipt" "$editor" \
    "$engine_version" "$python_binary" "$python_modules" "$scripting_binary" \
    "$scripting_modules" "$chaos_binary" "$chaos_editor_binary" "$chaos_modules"; do
    [[ -f $required && ! -L $required ]] || fail "required offline input is missing: $required"
done
[[ -x $runner && -x $editor ]] || fail 'the FEX runner and commandlet Editor must be executable'
cmp -s "$offline_template" "$project" || fail 'the project is not in the reviewed offline phase'
for binary in "$editor" "$python_binary" "$scripting_binary" \
    "$chaos_binary" "$chaos_editor_binary"; do
    file "$binary" | grep -q 'x86-64' || fail "offline binary is not x86-64: $binary"
done

read_build_id() {
    sed -n 's/.*"BuildId"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$1" | head -1
}
engine_build_id=$(read_build_id "$engine_version")
[[ -n $engine_build_id ]] || fail 'the isolated Editor BuildId is missing'
for modules in "$python_modules" "$scripting_modules" "$chaos_modules"; do
    [[ $(read_build_id "$modules") == "$engine_build_id" ]] || \
        fail "offline module manifest does not match the Editor BuildId: $modules"
done
python3 "$non_content_tool" verify "$project_dir" "$manifest"
python3 "$content_tool" verify "$project_dir" "$content_manifest"
systemctl --user is-active ue5-spark-avatar-live.service >/dev/null || \
    fail 'the live avatar service is not active; refusing to hide a pre-existing failure'

lock_parent="/run/user/$(id -u)"
[[ -d $lock_parent && ! -L $lock_parent ]] || fail 'the private runtime directory is unavailable'
lock="$lock_parent/ue5-spark-fab-phase.lock"
exec 9>>"$lock"
chmod 0600 "$lock"
flock -n 9 || fail 'another Fab phase operation is active'

if (( check_only == 1 )); then
    systemd-run --user --quiet --wait --pipe --collect \
        -p RestrictAddressFamilies=AF_UNIX \
        /usr/bin/python3 -c 'import socket; socket.socket(socket.AF_INET, socket.SOCK_STREAM)' \
        >/dev/null 2>&1 && fail 'the systemd sandbox did not block Internet socket creation'
    printf 'Offline Fab review preflight passed; Unreal was not started.\n'
    exit 0
fi

private_state="$workspace/state/fab-offline"
private_logs="$workspace/logs-private/fab-offline"
mkdir -p "$private_state/home" "$private_state/config" "$private_state/cache" \
    "$private_state/data" "$private_state/state" "$private_logs"
chmod 0700 "$private_state" "$private_state/home" "$private_state/config" \
    "$private_state/cache" "$private_state/data" "$private_state/state" "$private_logs"
export HOME="$private_state/home"
export XDG_CONFIG_HOME="$private_state/config"
export XDG_CACHE_HOME="$private_state/cache"
export XDG_DATA_HOME="$private_state/data"
export XDG_STATE_HOME="$private_state/state"
export FEX_SILENTLOG=${FEX_SILENTLOG:-1}
export FAY_FAB_STAGING_BASELINE_VERIFIED=1
export FAY_FAB_EXPECT_OFFLINE=1
unset DISPLAY XAUTHORITY DBUS_SESSION_BUS_ADDRESS EPIC_LAUNCHER_APP \
    UE5_SPARK_FAB_ACTION UE5_SPARK_FAB_PHONE_AUTH

session_limit=${UE5_SPARK_FAB_OFFLINE_TIMEOUT:-30m}
[[ $session_limit =~ ^[1-9][0-9]*[smhd]$ ]] || \
    fail 'UE5_SPARK_FAB_OFFLINE_TIMEOUT must be a positive duration such as 30m'
umask 077
log=$(mktemp "$private_logs/review-session.XXXXXX.log")
editor_args=(
    "$project"
    -run=pythonscript
    "-script=$inventory_script"
    -unattended
    -nullrhi
    -stdout
    -FullStdOutLogOutput
    -NoSplash
    -NoSound
    -NoSourceControl
    -NoCompile
    -NoCompileEditor
    -corelimit=2
    -onethread
    -norhithread
)

printf 'Starting the network-blocked offline Casual Girl inventory.\n'
set +e
systemd-run --user --quiet --wait --pipe --collect \
    -p RestrictAddressFamilies=AF_UNIX \
    -p NoNewPrivileges=yes \
    /usr/bin/env \
    "HOME=$HOME" \
    "XDG_CONFIG_HOME=$XDG_CONFIG_HOME" \
    "XDG_CACHE_HOME=$XDG_CACHE_HOME" \
    "XDG_DATA_HOME=$XDG_DATA_HOME" \
    "XDG_STATE_HOME=$XDG_STATE_HOME" \
    "FEX_SILENTLOG=$FEX_SILENTLOG" \
    "FAY_FAB_STAGING_BASELINE_VERIFIED=$FAY_FAB_STAGING_BASELINE_VERIFIED" \
    "FAY_FAB_EXPECT_OFFLINE=$FAY_FAB_EXPECT_OFFLINE" \
    nice -n 15 timeout --signal=TERM --kill-after=20s "$session_limit" \
    "$runner" "$workspace" -- "$editor" "${editor_args[@]}" >"$log" 2>&1
status=$?
set -e

python3 "$non_content_tool" verify "$project_dir" "$manifest" || \
    fail 'the offline review changed non-content state'
python3 "$content_tool" verify "$project_dir" "$content_manifest" || \
    fail 'the offline review changed staged Content'
systemctl --user is-active ue5-spark-avatar-live.service >/dev/null || \
    fail 'the live avatar service changed state during offline review'
if (( status != 0 )); then
    fail "the offline review exited with status $status; inspect the private log"
fi
if grep -Fq 'FAY_FAB_INVENTORY_ERROR=' "$log"; then
    fail 'the offline inventory emitted an error; inspect the private log'
fi
grep -Fq 'FAY_FAB_INVENTORY_OFFLINE_PLUGINS=OK' "$log" || \
    fail 'the offline plugin-state marker is missing'
grep -Fq 'FAY_FAB_INVENTORY_COMPLETE=OK' "$log" || \
    fail 'the offline inventory completion marker is missing'

printf 'Network-blocked offline Casual Girl inventory passed.\n'
printf 'Private offline log: %s\n' "$log"
