#!/usr/bin/env bash
set -euo pipefail

usage() {
    printf 'Usage: %s /path/to/cooker-workspace /path/to/UnrealEngine /path/to/project.uproject [-- editor arguments...]\n' \
        "${0##*/}" >&2
    printf 'Starts the x86-64 UE 5.8 graphical Editor through rootless FEX and Vulkan forwarding.\n' >&2
}

fail() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

if (( $# < 3 )); then
    usage
    exit 64
fi
if [[ $(uname -s) != Linux || $(uname -m) != aarch64 ]]; then
    fail "the FEX Editor adapter requires Linux/aarch64, not $(uname -s)/$(uname -m)"
fi
if (( ${EUID:-$(id -u)} == 0 )); then
    fail 'run the Editor adapter as the normal workspace owner, not root'
fi

for command_name in file find grep head nice sed tee timeout; do
    command -v "$command_name" >/dev/null 2>&1 || \
        fail "required command is missing: $command_name"
done

workspace=$(cd "$1" && pwd -P)
engine_root=$(cd "$2" && pwd -P)
project_input=$3
shift 3
if (( $# > 0 )); then
    [[ $1 == -- ]] || fail 'put -- before additional Unreal Editor arguments'
    shift
fi

[[ -f $project_input ]] || fail "project does not exist: $project_input"
project_dir=$(cd "$(dirname "$project_input")" && pwd -P)
project="$project_dir/$(basename "$project_input")"
case "$engine_root/" in
    "$workspace"/*) ;;
    *) fail 'the mutable Editor build must be inside the isolated cooker workspace' ;;
esac

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
runner="$script_dir/run-fex-rootless.sh"
editor="$engine_root/Engine/Binaries/Linux/UnrealEditor"
build_version="$engine_root/Engine/Build/Build.version"
engine_version="$engine_root/Engine/Binaries/Linux/UnrealEditor.version"
engine_manifest="$engine_root/Engine/Binaries/Linux/UnrealEditor.modules"
native_dotnet_dir="$engine_root/.spark-tools/dotnet"
native_dotnet="$native_dotnet_dir/dotnet"
log_dir="$workspace/logs"
log="$log_dir/fex-unreal-editor.log"
session_limit=${UE5_SPARK_EDITOR_TIMEOUT:-30m}
reported_cores=${UE5_SPARK_EDITOR_CORES:-2}
safe_mode=${UE5_SPARK_EDITOR_SAFE_MODE:-1}

[[ -x $runner ]] || fail "the rootless FEX runner is missing: $runner"
[[ -x $editor ]] || fail "the Unreal Editor is missing or not executable: $editor"
[[ -x $native_dotnet ]] || fail "the prepared native ARM64 .NET runtime is missing: $native_dotnet"
file "$editor" | grep -q 'x86-64' || fail 'the Unreal Editor is not an x86-64 ELF'
file -L "$native_dotnet" | grep -q 'ARM aarch64' || \
    fail 'the prepared .NET runtime is not an AArch64 ELF'
if [[ ! -f $build_version ]] || \
   ! grep -Eq '"MajorVersion"[[:space:]]*:[[:space:]]*5' "$build_version" || \
   ! grep -Eq '"MinorVersion"[[:space:]]*:[[:space:]]*8' "$build_version"; then
    fail 'the isolated Engine is not Unreal Engine 5.8'
fi
if [[ $session_limit != none && ! $session_limit =~ ^[1-9][0-9]*[smhd]$ ]]; then
    fail 'UE5_SPARK_EDITOR_TIMEOUT must be none or a positive duration such as 30m'
fi
if [[ ! $reported_cores =~ ^[1-8]$ ]]; then
    fail 'UE5_SPARK_EDITOR_CORES must be an integer from 1 through 8'
fi
if [[ $safe_mode != 0 && $safe_mode != 1 ]]; then
    fail 'UE5_SPARK_EDITOR_SAFE_MODE must be 0 or 1'
fi

display=${DISPLAY:-}
[[ -n $display ]] || fail 'DISPLAY is unset; launch from the Spark desktop or set its existing X display'
if [[ -z ${XAUTHORITY:-} ]]; then
    runtime_dir=${XDG_RUNTIME_DIR:-"/run/user/$(id -u)"}
    if [[ -r $runtime_dir/gdm/Xauthority ]]; then
        export XAUTHORITY="$runtime_dir/gdm/Xauthority"
    fi
fi
if [[ -n ${XAUTHORITY:-} && ! -r $XAUTHORITY ]]; then
    fail "XAUTHORITY is not readable: $XAUTHORITY"
fi

# FEX's Vulkan thunk calls the native host loader. If that loader is allowed to
# enumerate every installed ICD, Unreal can open Mesa's software/experimental
# drivers in addition to NVIDIA and fail device creation while probing them.
# Pin the Spark's native NVIDIA manifest unless the operator intentionally
# supplies a different readable list.
vk_driver_files=${VK_DRIVER_FILES:-/usr/share/vulkan/icd.d/nvidia_icd.json}
IFS=: read -r -a vk_driver_manifests <<< "$vk_driver_files"
for vk_driver_manifest in "${vk_driver_manifests[@]}"; do
    [[ -n $vk_driver_manifest && -r $vk_driver_manifest ]] || \
        fail "Vulkan driver manifest is missing or unreadable: $vk_driver_manifest"
done
export VK_DRIVER_FILES="$vk_driver_files"

read_build_id() {
    sed -n 's/.*"BuildId"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$1" | head -1
}

[[ -f $engine_version && -f $engine_manifest ]] || \
    fail 'the Editor version or module manifest is missing; build FayAvatarRuntimeEditor first'
engine_build_id=$(read_build_id "$engine_version")
[[ -n $engine_build_id ]] || fail "the Editor BuildId is missing: $engine_version"
[[ $(read_build_id "$engine_manifest") == "$engine_build_id" ]] || \
    fail 'the Engine module manifest does not match UnrealEditor.version'

project_manifest_count=0
while IFS= read -r -d '' manifest; do
    project_manifest_count=$((project_manifest_count + 1))
    manifest_build_id=$(read_build_id "$manifest")
    [[ $manifest_build_id == "$engine_build_id" ]] || \
        fail "project module manifest is stale; rebuild FayAvatarRuntimeEditor: $manifest"
done < <(find "$project_dir/Binaries/Linux" "$project_dir/Plugins" \
    -type f -name UnrealEditor.modules -print0 2>/dev/null)
(( project_manifest_count > 0 )) || \
    fail 'no project Editor module manifest exists; build FayAvatarRuntimeEditor first'

mkdir -p "$log_dir" "$workspace/state/dotnet-home" "$workspace/state/nuget-packages"
export FEX_SILENTLOG=${FEX_SILENTLOG:-1}
export UE_DOTNET_DIR="$native_dotnet_dir"
export DOTNET_ROOT="$native_dotnet_dir"
export DOTNET_CLI_HOME="$workspace/state/dotnet-home"
export NUGET_PACKAGES="$workspace/state/nuget-packages"
export PATH="$native_dotnet_dir:$PATH"

editor_args=(
    "$project"
    -vulkan
    -log
    -NoSplash
    -NoSound
    -NoSourceControl
    -NoCompile
    -NoCompileEditor
    "-corelimit=$reported_cores"
)
# The FEX/Vulkan path is stable on the Spark when Unreal keeps rendering on
# the game thread. With the normal render/RHI thread split, the Editor can
# render its first frame and then enter Unreal's recursive SIGSEGV handler.
# Keep the verified conservative mode on by default; advanced experiments can
# explicitly opt out without changing this public adapter.
if [[ $safe_mode == 1 ]]; then
    editor_args+=(
        -onethread
        -norhithread
        -nogpucrashdebugging
    )
fi
if [[ ${UE5_SPARK_EDITOR_UNATTENDED:-0} == 1 ]]; then
    editor_args+=(-unattended)
fi
editor_args+=("$@")

printf 'Starting UE 5.8 Editor through FEX on display %s with %s reported core(s).\n' \
    "$display" "$reported_cores"
printf 'Vulkan driver manifest: %s\n' "$VK_DRIVER_FILES"
if [[ $safe_mode == 1 ]]; then
    printf 'Spark safe mode: enabled (single-threaded rendering).\n'
else
    printf 'Spark safe mode: disabled by UE5_SPARK_EDITOR_SAFE_MODE=0.\n'
fi
if [[ $session_limit == none ]]; then
    printf 'No automatic stop is configured; close the Editor normally when finished.\n'
    nice -n 15 "$runner" "$workspace" -- "$editor" "${editor_args[@]}" \
        2>&1 | tee "$log"
    editor_status=${PIPESTATUS[0]}
else
    printf 'The safety stop is %s. First launch can spend several minutes warming shaders.\n' \
        "$session_limit"
    set +e
    nice -n 15 timeout --signal=TERM --kill-after=20s "$session_limit" \
        "$runner" "$workspace" -- "$editor" "${editor_args[@]}" \
        2>&1 | tee "$log"
    editor_status=${PIPESTATUS[0]}
    set -e
fi

if (( editor_status == 124 || editor_status == 137 )); then
    fail "the bounded Editor session reached its $session_limit safety stop; inspect $log"
elif (( editor_status != 0 )); then
    fail "the Editor exited with status $editor_status; inspect $log"
fi

printf 'Unreal Editor exited normally. Log: %s\n' "$log"
