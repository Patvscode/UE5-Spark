#!/usr/bin/env bash
set -euo pipefail

usage() {
    printf 'Usage: %s /path/to/cooker-workspace /path/to/UnrealEngine /path/to/project.uproject /path/to/archive\n' \
        "${0##*/}" >&2
    printf 'Validates a fingerprinted fresh cook, then builds/stages/seals it with native Spark host tools.\n' >&2
}

fail() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

if [[ $# -ne 4 ]]; then
    usage
    exit 64
fi
if [[ $(uname -s) != Linux || $(uname -m) != aarch64 ]]; then
    fail "this hybrid packager requires Linux/aarch64, not $(uname -s)/$(uname -m)"
fi
if (( ${EUID:-$(id -u)} == 0 )); then
    fail 'run the hybrid packager as the normal workspace owner, not root'
fi

for command_name in awk df file find flock grep nice python3 tee timeout; do
    command -v "$command_name" >/dev/null 2>&1 || \
        fail "required command is missing: $command_name"
done

workspace=$(cd "$1" && pwd -P)
engine_root=$(cd "$2" && pwd -P)
project_input=$3
archive_input=$4
[[ -f $project_input ]] || fail "project does not exist: $project_input"
project_dir=$(cd "$(dirname "$project_input")" && pwd -P)
project="$project_dir/$(basename "$project_input")"

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
build_uat="$engine_root/Engine/Build/BatchFiles/BuildUAT.sh"
build_version="$engine_root/Engine/Build/Build.version"
dotnet="$engine_root/.spark-tools/dotnet/dotnet"
ubt="$engine_root/Engine/Binaries/DotNET/UnrealBuildTool/UnrealBuildTool.dll"
automation_tool_dir="$engine_root/Engine/Binaries/DotNET/AutomationTool"
native_llvm="$engine_root/.spark-tools/llvm-20.1.8/bin"
native_clang="$native_llvm/clang"
native_clangxx="$native_llvm/clang++"
toolchain="$workspace/toolchains/native-cross-v26"
host_unrealpak="$engine_root/Engine/Binaries/Linux/UnrealPak"
native_unrealpak="$engine_root/Engine/Binaries/LinuxArm64/UnrealPak"
x86_unrealpak="$engine_root/Engine/Binaries/Linux/UnrealPak.x86_64"
cooked_root="$project_dir/Saved/Cooked/LinuxArm64"
staged_root="$project_dir/Saved/StagedBuilds/LinuxArm64"
native_binary="$project_dir/Binaries/LinuxArm64/FayAvatarRuntime"
native_receipt="$project_dir/Binaries/LinuxArm64/FayAvatarRuntime.target"
log_dir="$workspace/logs/hybrid-package"
cook_state_helper="$script_dir/cook-state.py"
loose_cook_verifier="$script_dir/verify-linux-arm64-cook.sh"
parallel_actions=${UE5_SPARK_BUILD_JOBS:-2}
build_timeout=${UE5_SPARK_NATIVE_BUILD_TIMEOUT:-6h}
uat_build_timeout=${UE5_SPARK_UAT_BUILD_TIMEOUT:-45m}
stage_timeout=${UE5_SPARK_STAGE_TIMEOUT:-3h}
minimum_free_gb=${UE5_SPARK_MIN_FREE_GB:-50}

if [[ ! $parallel_actions =~ ^[1-4]$ ]]; then
    fail 'UE5_SPARK_BUILD_JOBS must be an integer from 1 through 4'
fi
if [[ ! $minimum_free_gb =~ ^[1-9][0-9]*$ ]]; then
    fail 'UE5_SPARK_MIN_FREE_GB must be a positive integer'
fi
for timeout_value in "$build_timeout" "$uat_build_timeout" "$stage_timeout"; do
    [[ $timeout_value =~ ^[1-9][0-9]*[smhd]$ ]] || \
        fail 'build/stage timeout values must be positive durations such as 45m or 6h'
done
if [[ ! -f $build_version ]] || \
   ! grep -Eq '"MajorVersion"[[:space:]]*:[[:space:]]*5' "$build_version" || \
   ! grep -Eq '"MinorVersion"[[:space:]]*:[[:space:]]*8' "$build_version"; then
    fail 'the isolated Engine is not Unreal Engine 5.8'
fi

case "$engine_root/" in
    "$workspace"/*) ;;
    *) fail 'the packaging engine must be an isolated tree inside the cooker workspace' ;;
esac

archive_input=$(python3 - "$workspace" "$engine_root" "$project_dir" \
    "$staged_root" "$archive_input" <<'PY'
import os
import sys
from pathlib import Path


def stop(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


workspace = Path(sys.argv[1]).resolve(strict=True)
engine = Path(sys.argv[2]).resolve(strict=True)
project = Path(sys.argv[3]).resolve(strict=True)
stage = Path(os.path.abspath(sys.argv[4]))
archive = Path(os.path.abspath(sys.argv[5]))


def require_safe_workspace_path(path: Path, label: str) -> None:
    if not path.is_relative_to(workspace):
        stop(f"{label} must remain inside the cooker workspace")
    current = workspace
    for component in path.relative_to(workspace).parts:
        current /= component
        if current.is_symlink():
            stop(f"{label} contains a symlinked path component")
    if path.exists() and not path.is_dir():
        stop(f"{label} exists but is not a directory")


expected_stage = project / "Saved/StagedBuilds/LinuxArm64"
if stage != expected_stage:
    stop("staging root does not match the project's LinuxArm64 staging directory")
require_safe_workspace_path(stage, "staging root")
require_safe_workspace_path(archive, "archive root")

protected_paths = (
    engine,
    project,
    workspace / "state",
    workspace / "logs",
    workspace / "toolchains",
)
for protected in protected_paths:
    if (
        archive == protected
        or archive.is_relative_to(protected)
        or protected.is_relative_to(archive)
    ):
        stop("archive root overlaps an Engine, project, state, log, or toolchain tree")

print(archive)
PY
) || fail 'staging/archive path validation failed'

for required in "$build_uat" "$dotnet" "$ubt" "$native_clang" \
    "$native_clangxx" "$toolchain/ToolchainVersion.txt" \
    "$toolchain/aarch64-unknown-linux-gnueabi/bin/clang++" \
    "$workspace/toolchains/v26_clang-20.1.8-rockylinux8/ToolchainVersion.txt" \
    "$host_unrealpak" "$native_unrealpak"; do
    [[ -e $required ]] || fail "required packaging input is missing: $required"
done
[[ -x $build_uat && -x $dotnet && -x $native_clang && \
   -x $native_clangxx && -x $host_unrealpak && -x $native_unrealpak && \
   -x $loose_cook_verifier && -f $cook_state_helper ]] || \
    fail 'one or more required build, packaging, or verification tools are not executable'
file -L "$dotnet" | grep -q 'ARM aarch64' || fail "dotnet is not native AArch64: $dotnet"
file -L "$native_clangxx" | grep -q 'ARM aarch64' || \
    fail "clang++ is not native AArch64: $native_clangxx"
file "$native_unrealpak" | grep -q 'ARM aarch64' || \
    fail 'the staging path requires a native AArch64 UnrealPak'
grep -q 'LinuxArm64/UnrealPak' "$host_unrealpak" || \
    fail 'the Linux UnrealPak host path is not configured with the dual-architecture wrapper'
if [[ -e $x86_unrealpak ]]; then
    file "$x86_unrealpak" | grep -q 'x86-64' || \
        fail 'the preserved x86-64 UnrealPak has the wrong architecture'
fi

[[ -d $cooked_root ]] || \
    fail "the LinuxArm64 cook is missing; finish the FEX cook first: $cooked_root"
if [[ -d $staged_root ]] && find "$staged_root" -mindepth 1 -print -quit | grep -q .; then
    fail "the LinuxArm64 staging directory must be absent or empty to prevent stale output: $staged_root"
fi

available_kb=$(df -Pk "$workspace" | awk 'NR == 2 { print $4 }')
[[ $available_kb =~ ^[0-9]+$ ]] || fail 'could not determine free workspace storage'
if (( available_kb < minimum_free_gb * 1024 * 1024 )); then
    fail "the workspace has less than the required ${minimum_free_gb} GiB free"
fi

managed_directories=(
    "$workspace/state"
    "$workspace/logs"
    "$log_dir"
    "$log_dir/uat"
    "$workspace/state/dotnet-home"
    "$workspace/state/nuget-packages"
    "$workspace/state/xdg-cache"
    "$workspace/state/xdg-config"
    "$workspace/state/xdg-data"
)
for managed_directory in "${managed_directories[@]}"; do
    [[ ! -L $managed_directory ]] || \
        fail "managed state/log directory must not be a symlink: $managed_directory"
done
mkdir -p "${managed_directories[@]}"

lock_file="$workspace/state/digital-human-postbuild.lock"
package_logs=(
    "$log_dir/native-automation-tool-build.log"
    "$log_dir/native-linux-arm64-build.log"
    "$log_dir/native-stage-package.log"
)
[[ ! -L $lock_file ]] || fail 'the post-build lock file must not be a symlink'
for package_log in "${package_logs[@]}"; do
    [[ ! -L $package_log ]] || fail "package log file must not be a symlink: $package_log"
done
exec 9>>"$lock_file"
flock -n 9 || fail 'another digital-human cook/package operation holds the workspace lock'

priority_prefix=(nice -n 10)
if command -v ionice >/dev/null 2>&1; then
    priority_prefix+=(ionice -c 2 -n 7)
fi

if [[ -d $staged_root ]] && find "$staged_root" -mindepth 1 -print -quit | grep -q .; then
    fail "the LinuxArm64 staging directory became nonempty; refusing stale output: $staged_root"
fi

"$loose_cook_verifier" "$cooked_root"
"${priority_prefix[@]}" python3 "$cook_state_helper" check \
    --workspace "$workspace" \
    --engine "$engine_root" \
    --project "$project" \
    --cook-root "$cooked_root"

if [[ -d $archive_input ]] && find "$archive_input" -mindepth 1 -print -quit | grep -q .; then
    fail "archive directory must be empty to prevent stale-package validation: $archive_input"
fi
mkdir -p "$archive_input"
archive_root=$(cd "$archive_input" && pwd -P)

export PATH="$engine_root/.spark-tools/dotnet:$native_llvm:$PATH"
export LINUX_MULTIARCH_ROOT="$toolchain"
export UE5_SPARK_NATIVE_CLANG="$native_clang"
export UE5_SPARK_NATIVE_CLANGXX="$native_clangxx"
export UE_LOCAL_DDC_PATH="$workspace/state/native-build-ddc"
export DOTNET_CLI_HOME="$workspace/state/dotnet-home"
export NUGET_PACKAGES="$workspace/state/nuget-packages"
export XDG_CACHE_HOME="$workspace/state/xdg-cache"
export XDG_CONFIG_HOME="$workspace/state/xdg-config"
export XDG_DATA_HOME="$workspace/state/xdg-data"
export uebp_LogFolder="$log_dir/uat"
export UE_DOTNET_DIR="$engine_root/.spark-tools/dotnet"
export DOTNET_ROOT="$engine_root/.spark-tools/dotnet"

printf 'Stage 1/3: build the managed AutomationTool with native ARM64 .NET (limit %s)\n' \
    "$uat_build_timeout"
set +e
timeout --signal=TERM --kill-after=60s "$uat_build_timeout" \
    "${priority_prefix[@]}" env \
    UE_DOTNET_DIR="$engine_root/.spark-tools/dotnet" \
    DOTNET_ROOT="$engine_root/.spark-tools/dotnet" \
    PATH="$engine_root/.spark-tools/dotnet:$PATH" \
    "$build_uat" quiet \
    2>&1 | tee "$log_dir/native-automation-tool-build.log"
uat_build_status=${PIPESTATUS[0]}
set -e
if (( uat_build_status == 124 || uat_build_status == 137 )); then
    fail "the native AutomationTool build exceeded its $uat_build_timeout limit"
elif (( uat_build_status != 0 )); then
    fail "the native AutomationTool build failed with status $uat_build_status"
fi
[[ -s "$engine_root/Engine/Binaries/DotNET/AutomationTool/AutomationTool.dll" ]] || \
    fail 'the native AutomationTool build did not produce AutomationTool.dll'

printf 'Stage 2/3: native LinuxArm64 Game build (%s action(s), limit %s)\n' \
    "$parallel_actions" "$build_timeout"
set +e
timeout --signal=TERM --kill-after=60s "$build_timeout" \
    "${priority_prefix[@]}" "$dotnet" "$ubt" FayAvatarRuntime LinuxArm64 Development \
    -Project="$project" -NoUBA -NoDumpSyms \
    -MaxParallelActions="$parallel_actions" \
    2>&1 | tee "$log_dir/native-linux-arm64-build.log"
build_status=${PIPESTATUS[0]}
set -e
if (( build_status == 124 || build_status == 137 )); then
    fail "the native LinuxArm64 build exceeded its $build_timeout limit"
elif (( build_status != 0 )); then
    fail "the native LinuxArm64 build failed with status $build_status"
fi

[[ -x $native_binary ]] || fail "native Game executable is missing: $native_binary"
file "$native_binary" | grep -q 'ARM aarch64' || \
    fail "Game executable is not an AArch64 ELF: $native_binary"
[[ -f $native_receipt ]] || fail "native build receipt is missing: $native_receipt"
grep -Eq '"TargetName"[[:space:]]*:[[:space:]]*"FayAvatarRuntime"' "$native_receipt" || \
    fail 'native receipt has the wrong target name'
grep -Eq '"Platform"[[:space:]]*:[[:space:]]*"LinuxArm64"' "$native_receipt" || \
    fail 'native receipt has the wrong platform'
grep -Eq '"Configuration"[[:space:]]*:[[:space:]]*"Development"' "$native_receipt" || \
    fail 'native receipt has the wrong configuration'
grep -Eqi '"Architecture"[[:space:]]*:[[:space:]]*"arm64"' "$native_receipt" || \
    fail 'native receipt has the wrong architecture'

printf 'Stage 3/3: reuse the successful cook and create the archive natively (limit %s)\n' \
    "$stage_timeout"
"$loose_cook_verifier" "$cooked_root"
"${priority_prefix[@]}" python3 "$cook_state_helper" check \
    --workspace "$workspace" \
    --engine "$engine_root" \
    --project "$project" \
    --cook-root "$cooked_root"
pushd "$automation_tool_dir" >/dev/null
set +e
timeout --signal=TERM --kill-after=60s "$stage_timeout" \
    "${priority_prefix[@]}" "$dotnet" AutomationTool.dll BuildCookRun \
    -project="$project" \
    -target=FayAvatarRuntime \
    -platform=LinuxArm64 \
    -clientconfig=Development \
    -skipbuild \
    -skipcook \
    -stage \
    -pak \
    -skipiostore \
    -package \
    -archive \
    -archivedirectory="$archive_root" \
    -nocompileeditor \
    -unattended \
    -nop4 \
    -utf8output \
    2>&1 | tee "$log_dir/native-stage-package.log"
stage_status=${PIPESTATUS[0]}
set -e
popd >/dev/null
if (( stage_status == 124 || stage_status == 137 )); then
    fail "the native stage/package operation exceeded its $stage_timeout limit"
elif (( stage_status != 0 )); then
    fail "the native stage/package operation failed with status $stage_status"
fi

"${priority_prefix[@]}" "$script_dir/verify-cooked-package.sh" "$archive_root" \
    --unrealpak "$native_unrealpak" --seal
printf 'Verified LinuxArm64 archive: %s\n' "$archive_root"
