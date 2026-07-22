#!/usr/bin/env bash
set -euo pipefail

usage() {
    printf 'Usage: %s [--check] /path/to/cooker-workspace /path/to/isolated/UnrealEngine /path/to/FayFabAcquisition.uproject /path/to/private-baseline.json\n' \
        "${0##*/}" >&2
    printf 'Starts the isolated Fab acquisition Editor through rootless FEX.\n' >&2
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
    fail "the Fab staging launcher requires Linux/aarch64, not $(uname -s)/$(uname -m)"
fi
if (( ${EUID:-$(id -u)} == 0 )); then
    fail 'run the Fab staging launcher as the normal workspace owner, not root'
fi
for command_name in cmp file grep id mkdir mktemp nice python3 sed timeout; do
    command -v "$command_name" >/dev/null 2>&1 || \
        fail "required command is missing: $command_name"
done

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
    *) fail 'the baseline manifest must remain in the private Fab log directory' ;;
esac
[[ ${project##*/} == FayFabAcquisition.uproject ]] || \
    fail 'the reviewed staging descriptor must be named FayFabAcquisition.uproject'
for forbidden in Source Plugins; do
    [[ ! -e $project_dir/$forbidden && ! -L $project_dir/$forbidden ]] || \
        fail "the content-only staging project must not contain $forbidden"
done

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
runner="$script_dir/run-fex-rootless.sh"
manifest_tool="$script_dir/fab-staging-manifest.py"
project_template="$script_dir/../staging/fab-acquisition-template/FayFabAcquisition.uproject"
editor="$engine_root/Engine/Binaries/Linux/UnrealEditor"
engine_version="$engine_root/Engine/Binaries/Linux/UnrealEditor.version"
fab_binary="$engine_root/Engine/Plugins/Fab/Binaries/Linux/libUnrealEditor-Fab.so"
fab_modules="$engine_root/Engine/Plugins/Fab/Binaries/Linux/UnrealEditor.modules"
fab_downloader="$engine_root/Engine/Plugins/Fab/ThirdParty/libBuildPatchInstallerLib.so"
epic_web_helper="$engine_root/Engine/Binaries/Linux/EpicWebHelper"
guest_portal="$workspace/rootfs/ubuntu-24.04-x86_64/usr/bin/xdg-open"

for required in "$runner" "$manifest_tool" "$project_template" "$editor" "$engine_version" \
    "$fab_binary" "$fab_modules" "$fab_downloader" "$epic_web_helper" \
    "$guest_portal"; do
    [[ -f $required && ! -L $required ]] || fail "required launch input is missing: $required"
done
[[ -x $runner && -x $editor && -x $guest_portal ]] || \
    fail 'the FEX runner, Editor, and portal adapter must be executable'
file "$editor" | grep -q 'x86-64' || fail 'the isolated Unreal Editor is not x86-64'
file "$fab_binary" | grep -q 'x86-64' || fail 'the Fab Editor module is not x86-64'
file "$fab_downloader" | grep -q 'x86-64' || fail 'the Fab downloader is not x86-64'
file "$epic_web_helper" | grep -q 'x86-64' || fail 'EpicWebHelper is not x86-64'
grep -qx '# UE5-SPARK-FEX-XDG-OPEN-PORTAL-V3' "$guest_portal" || \
    fail 'the guarded FEX portal adapter is missing or unreviewed'
cmp -s "$project_template" "$project" || \
    fail 'the staging descriptor differs from the reviewed template'

read_build_id() {
    sed -n 's/.*"BuildId"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$1" | head -1
}
engine_build_id=$(read_build_id "$engine_version")
[[ -n $engine_build_id && $(read_build_id "$fab_modules") == "$engine_build_id" ]] || \
    fail 'the Fab module manifest does not match the isolated Editor build ID'
python3 "$manifest_tool" verify "$project_dir" "$manifest"

if (( check_only == 1 )); then
    printf 'Fab staging launch preflight passed; the Editor was not started.\n'
    exit 0
fi

display=${DISPLAY:-}
[[ -n $display ]] || fail 'DISPLAY is unset; use the existing Spark desktop display'
runtime_dir=${XDG_RUNTIME_DIR:-"/run/user/$(id -u)"}
[[ -S $runtime_dir/bus ]] || fail 'the desktop session D-Bus is unavailable'
export XDG_RUNTIME_DIR="$runtime_dir"
export DBUS_SESSION_BUS_ADDRESS=${DBUS_SESSION_BUS_ADDRESS:-"unix:path=$runtime_dir/bus"}
if [[ -z ${XAUTHORITY:-} && -r $runtime_dir/gdm/Xauthority ]]; then
    export XAUTHORITY="$runtime_dir/gdm/Xauthority"
fi
[[ -n ${XAUTHORITY:-} && -r $XAUTHORITY ]] || \
    fail 'the existing Spark desktop Xauthority is unavailable'

vk_driver_files=${VK_DRIVER_FILES:-/usr/share/vulkan/icd.d/nvidia_icd.json}
IFS=: read -r -a vk_manifests <<< "$vk_driver_files"
for vk_manifest in "${vk_manifests[@]}"; do
    [[ -n $vk_manifest && -r $vk_manifest ]] || \
        fail "Vulkan driver manifest is missing or unreadable: $vk_manifest"
done
export VK_DRIVER_FILES="$vk_driver_files"
export FEX_SILENTLOG=${FEX_SILENTLOG:-1}

private_state="$workspace/state/fab-acquisition"
private_logs="$workspace/logs-private/fab-acquisition"
mkdir -p "$private_state/home" "$private_state/config" "$private_state/cache" \
    "$private_state/data" "$private_state/state" "$private_logs"
chmod 0700 "$private_state" "$private_state/home" "$private_state/config" \
    "$private_state/cache" "$private_state/data" "$private_state/state" "$private_logs"
export HOME="$private_state/home"
export XDG_CONFIG_HOME="$private_state/config"
export XDG_CACHE_HOME="$private_state/cache"
export XDG_DATA_HOME="$private_state/data"
export XDG_STATE_HOME="$private_state/state"

session_limit=${UE5_SPARK_FAB_TIMEOUT:-60m}
[[ $session_limit == none || $session_limit =~ ^[1-9][0-9]*[smhd]$ ]] || \
    fail 'UE5_SPARK_FAB_TIMEOUT must be none or a positive duration such as 60m'
umask 077
log=$(mktemp "$private_logs/editor-session.XXXXXX.log")
editor_args=(
    "$project"
    -vulkan
    -log
    -NoSplash
    -NoSound
    -NoSourceControl
    -NoCompile
    -NoCompileEditor
    -corelimit=2
    -onethread
    -norhithread
    -nogpucrashdebugging
)

printf 'Starting isolated Fab staging Editor on display %s.\n' "$display"
printf 'Complete account authentication only in the browser opened by the desktop portal.\n'
printf 'Editor output is restricted to a private mode-0600 log and is not echoed here.\n'
set +e
if [[ $session_limit == none ]]; then
    nice -n 15 "$runner" "$workspace" -- "$editor" "${editor_args[@]}" \
        >"$log" 2>&1
    status=$?
else
    nice -n 15 timeout --signal=TERM --kill-after=20s "$session_limit" \
        "$runner" "$workspace" -- "$editor" "${editor_args[@]}" \
        >"$log" 2>&1
    status=$?
fi
set -e

python3 "$manifest_tool" verify "$project_dir" "$manifest" || \
    fail 'Fab changed non-content staging state; preserve and review the private evidence'
if (( status == 124 || status == 137 )); then
    fail "the Editor reached its $session_limit safety stop; inspect the private log"
elif (( status != 0 )); then
    fail "the Editor exited with status $status; inspect the private log"
fi
printf 'Fab staging Editor exited normally and the non-content seal still matches.\n'
printf 'Private Editor log: %s\n' "$log"
