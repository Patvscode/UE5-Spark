#!/usr/bin/env bash
set -euo pipefail

usage() {
    printf 'Usage: %s /path/to/cooker-workspace /path/to/UnrealEngine /path/to/project.uproject\n' \
        "${0##*/}" >&2
    printf 'Creates and fingerprints a fresh LinuxArm64 cook; it does not build, stage, package, or archive.\n' >&2
}

fail() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

if [[ $# -ne 3 ]]; then
    usage
    exit 64
fi
if [[ $(uname -s) != Linux || $(uname -m) != aarch64 ]]; then
    fail "the FEX cook must run on Linux/aarch64, not $(uname -s)/$(uname -m)"
fi
if (( ${EUID:-$(id -u)} == 0 )); then
    fail 'run the FEX cook as the normal workspace owner, not root'
fi

for command_name in file find flock grep nice python3 rm tee timeout; do
    command -v "$command_name" >/dev/null 2>&1 || \
        fail "required command is missing: $command_name"
done

workspace=$(cd "$1" && pwd -P)
engine_root=$(cd "$2" && pwd -P)
project_input=$3
[[ -f $project_input ]] || fail "project is missing: $project_input"
project_dir=$(cd "$(dirname "$project_input")" && pwd -P)
project="$project_dir/$(basename "$project_input")"

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
runner="$script_dir/run-fex-rootless.sh"
run_uat="$engine_root/Engine/Build/BatchFiles/RunUAT.sh"
build_version="$engine_root/Engine/Build/Build.version"
editor="$engine_root/Engine/Binaries/Linux/UnrealEditor"
toolchain="$workspace/toolchains/v26_clang-20.1.8-rockylinux8"
arm64_clang="$toolchain/aarch64-unknown-linux-gnueabi/bin/clang++"
cook_root="$project_dir/Saved/Cooked/LinuxArm64"
cook_state="$workspace/state/fay-avatar-linuxarm64-cook.json"
cook_pending_state="$workspace/state/fay-avatar-linuxarm64-cook.inputs.json"
log_dir="$workspace/logs/fex-cook"
log="$log_dir/linux-arm64-cook.log"
cook_timeout=${UE5_SPARK_COOK_TIMEOUT:-12h}

case "$engine_root/" in
    "$workspace"/*) ;;
    *) fail 'the cooking Engine must be an isolated tree inside the cooker workspace' ;;
esac
case "$project/" in
    "$workspace"/*) ;;
    *) fail 'the cooking project must be inside the cooker workspace' ;;
esac

[[ -x $runner ]] || fail "the rootless FEX runner is missing: $runner"
[[ -x $run_uat ]] || fail "RunUAT.sh is missing or not executable: $run_uat"
[[ -x $editor ]] || fail "the x86-64 Editor is missing or not executable: $editor"
[[ -x $arm64_clang ]] || \
    fail 'the pinned v26 toolchain is missing; run setup-unreal-toolchain-rootless.sh first'
file "$editor" | grep -q 'x86-64' || fail 'the cooking Editor is not an x86-64 ELF'
file "$arm64_clang" | grep -q 'x86-64' || fail 'the v26 compiler is not an x86-64 ELF'
if [[ ! -f $build_version ]] || \
   ! grep -Eq '"MajorVersion"[[:space:]]*:[[:space:]]*5' "$build_version" || \
   ! grep -Eq '"MinorVersion"[[:space:]]*:[[:space:]]*8' "$build_version"; then
    fail 'the isolated Engine is not Unreal Engine 5.8'
fi

arm64_module_count=$(find "$engine_root/Engine/Binaries/Linux" -maxdepth 1 -type f \
    -iname '*LinuxArm64*TargetPlatform*.so' | wc -l | tr -d ' ')
if (( arm64_module_count == 0 )); then
    fail 'this Editor has no compiled LinuxArm64 target-platform module'
fi

ada_source="$project_dir/Content/FayMetaHumans/Built/AdaFay/BP_AdaFay.uasset"
streaming_model="$engine_root/Engine/Plugins/Animation/AudioDrivenAnimation/StreamingADA/Content/xsada_face_base_fp32_v2_0_0.uasset"
[[ -s $ada_source ]] || \
    fail 'the assembled Ada Blueprint is missing; finish MetaHuman assembly before cooking'
[[ -s $streaming_model ]] || fail 'the UE 5.8 StreamingADA v2 model is missing'

if [[ $cook_timeout != none && ! $cook_timeout =~ ^[1-9][0-9]*[smhd]$ ]]; then
    fail 'UE5_SPARK_COOK_TIMEOUT must be none or a positive duration such as 12h'
fi

[[ ! -L $workspace/state && ! -L $workspace/logs && ! -L $log_dir ]] || \
    fail 'workspace state and log directories must not be symlinks'
mkdir -p "$workspace/state" "$log_dir"
lock_file="$workspace/state/digital-human-postbuild.lock"
[[ ! -L $lock_file && ! -L $log ]] || \
    fail 'cook lock and log files must not be symlinks'
exec 9>>"$lock_file"
flock -n 9 || fail 'another digital-human cook/package operation holds the workspace lock'

if [[ -d $cook_root ]] && find "$cook_root" -mindepth 1 -print -quit | grep -q .; then
    fail "the LinuxArm64 cook directory must be absent or empty to prevent stale output: $cook_root"
fi

# Invalidate only this pipeline's prior success record. A failed attempt can
# never authorize the native packager to reuse an older cook.
rm -f -- "$cook_state" "$cook_pending_state"
cleanup_pending_state() {
    rm -f -- "$cook_pending_state"
}
trap cleanup_pending_state EXIT

priority_prefix=(nice -n 15)
if command -v ionice >/dev/null 2>&1; then
    priority_prefix+=(ionice -c 2 -n 7)
fi

"${priority_prefix[@]}" python3 "$script_dir/cook-state.py" begin \
    --workspace "$workspace" \
    --engine "$engine_root" \
    --project "$project" \
    --cook-root "$cook_root"

export LINUX_MULTIARCH_ROOT="$toolchain"
export FEX_SILENTLOG=1
uat_command=(
    "$runner" "$workspace" -- /bin/bash "$run_uat" BuildCookRun
    -project="$project"
    -target=FayAvatarRuntime
    -platform=LinuxArm64
    -clientconfig=Development
    -skipbuild
    -cook
    -nocompileeditor
    -unattended
    -nop4
    -utf8output
    '-AdditionalCookerOptions=-SkipZenStore -DDC=(Local) -nullrhi -nosound -corelimit=4'
)

printf 'Creating a fresh LinuxArm64 cook through the x86-64 Editor/FEX path.\n'
printf 'This step will not build, stage, package, or archive a Game executable.\n'
if [[ $cook_timeout == none ]]; then
    set +e
    "${priority_prefix[@]}" "${uat_command[@]}" 2>&1 | tee "$log"
    cook_status=${PIPESTATUS[0]}
    set -e
else
    printf 'Safety limit: %s\n' "$cook_timeout"
    set +e
    timeout --signal=TERM --kill-after=60s "$cook_timeout" \
        "${priority_prefix[@]}" "${uat_command[@]}" 2>&1 | tee "$log"
    cook_status=${PIPESTATUS[0]}
    set -e
fi

if (( cook_status == 124 || cook_status == 137 )); then
    fail "the FEX cook exceeded its $cook_timeout limit"
elif (( cook_status != 0 )); then
    fail "the FEX cook failed with status $cook_status; no successful-cook state was recorded"
fi

"$script_dir/verify-linux-arm64-cook.sh" "$cook_root"
"${priority_prefix[@]}" python3 "$script_dir/cook-state.py" record \
    --workspace "$workspace" \
    --engine "$engine_root" \
    --project "$project" \
    --cook-root "$cook_root"

printf 'Fresh LinuxArm64 cook completed and fingerprinted.\n'
printf 'Next: run package-linux-arm64-hybrid.sh with a new empty archive path.\n'
