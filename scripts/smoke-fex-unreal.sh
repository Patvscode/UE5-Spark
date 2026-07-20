#!/usr/bin/env bash
set -euo pipefail

usage() {
    printf 'Usage: %s /path/to/cooker-workspace /path/to/UnrealEngine /path/to/project.uproject\n' \
        "${0##*/}" >&2
    printf 'Runs a bounded FEX and Unreal 5.8 LinuxArm64 cook probe; it does not package the project.\n' >&2
}

fail() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

if [[ $# -ne 3 ]]; then
    usage
    exit 64
fi

if [[ "$(uname -s)" != "Linux" || "$(uname -m)" != "aarch64" ]]; then
    fail "the FEX probe must run on Linux/aarch64, not $(uname -s)/$(uname -m)"
fi

for command_name in file grep timeout tee; do
    command -v "$command_name" >/dev/null 2>&1 || fail "required command is missing: $command_name"
done

workspace=$(cd "$1" && pwd -P)
engine_root=$(cd "$2" && pwd -P)
project_input=$3
[[ -f "$project_input" ]] || fail "project does not exist: $project_input"
project_dir=$(cd "$(dirname "$project_input")" && pwd -P)
project="$project_dir/$(basename "$project_input")"

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
runner="$script_dir/run-fex-rootless.sh"
editor="$engine_root/Engine/Binaries/Linux/UnrealEditor-Cmd"
if [[ ! -x "$editor" ]]; then
    editor="$engine_root/Engine/Binaries/Linux/UnrealEditor"
fi
shader_worker="$engine_root/Engine/Binaries/Linux/ShaderCompileWorker"
build_version="$engine_root/Engine/Build/Build.version"
log_dir="$workspace/logs"
mkdir -p "$log_dir"
export FEX_SILENTLOG=0

[[ -x "$editor" ]] || fail 'x86-64 UnrealEditor or UnrealEditor-Cmd is missing'
[[ -x "$shader_worker" ]] || fail "ShaderCompileWorker is missing or not executable: $shader_worker"
file "$editor" | grep -q 'x86-64' || fail "the Unreal Editor executable is not an x86-64 ELF"
file "$shader_worker" | grep -q 'x86-64' || fail "ShaderCompileWorker is not an x86-64 ELF"

if [[ ! -f "$build_version" ]] || \
   ! grep -Eq '"MajorVersion"[[:space:]]*:[[:space:]]*5' "$build_version" || \
   ! grep -Eq '"MinorVersion"[[:space:]]*:[[:space:]]*8' "$build_version"; then
    fail 'the Engine is not Unreal Engine 5.8'
fi

arm64_module_count=$(find "$engine_root/Engine/Binaries/Linux" -maxdepth 2 -type f \
    -iname 'libUnrealEditor-LinuxArm64*TargetPlatform*.so' | wc -l | tr -d ' ')
if (( arm64_module_count == 0 )); then
    fail 'this Editor has no compiled LinuxArm64 target-platform module; build the project Editor target with bForceBuildTargetPlatforms=true'
fi

printf 'Stage 1/2: FEX guest architecture\n'
guest_arch=$(timeout --signal=TERM --kill-after=5s 30s \
    "$runner" "$workspace" -- /usr/bin/uname -m)
[[ "$guest_arch" == "x86_64" ]] || fail "FEX guest reported unexpected architecture: $guest_arch"
printf 'Guest architecture: %s\n' "$guest_arch"

printf 'Stage 2/2: minimal LinuxArm64 cook (45 minute limit)\n'
printf 'This stage intentionally reports four cores, limiting initial ShaderCompileWorker fan-out.\n'
set +e
timeout --signal=TERM --kill-after=30s 45m \
    "$runner" "$workspace" -- "$editor" "$project" \
    -run=Cook -targetplatform=LinuxArm64 -CookCultures=en \
    -unattended -nop4 -nullrhi -nosplash -nosound -SkipZenStore \
    -NoCompile -NoCompileEditor -stdout -FullStdOutLogOutput -corelimit=4 \
    2>&1 | tee "$log_dir/linux-arm64-cook-probe.log"
cook_status=${PIPESTATUS[0]}
set -e

if (( cook_status == 124 || cook_status == 137 )); then
    fail "the bounded cook timed out; inspect $log_dir/linux-arm64-cook-probe.log"
elif (( cook_status != 0 )); then
    fail "the bounded cook failed with status $cook_status; inspect $log_dir/linux-arm64-cook-probe.log"
fi

if ! grep -Eq 'Cook complete|Cooked packages|Packages Cooked:|Success - 0 error|Completed Launch On Stage: Cooking' \
    "$log_dir/linux-arm64-cook-probe.log"; then
    fail 'the process exited successfully but no cook-completion marker was found in the log'
fi

printf 'FEX, UnrealEditor-Cmd, ShaderCompileWorker, and the LinuxArm64 cooker passed the bounded probe.\n'
