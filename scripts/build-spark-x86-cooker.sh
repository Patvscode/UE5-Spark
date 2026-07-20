#!/usr/bin/env bash
set -euo pipefail

usage() {
    printf 'Usage: %s /path/to/cooker-workspace /path/to/isolated/UnrealEngine /path/to/project.uproject\n' \
        "${0##*/}" >&2
}

fail() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

if [[ $# -ne 3 ]]; then
    usage
    exit 64
fi
if [[ "$(uname -s)" != Linux || "$(uname -m)" != aarch64 ]]; then
    fail "this hybrid builder requires Linux/aarch64, not $(uname -s)/$(uname -m)"
fi
if (( ${EUID:-$(id -u)} == 0 )); then
    fail 'run the hybrid builder as the normal workspace owner, not root'
fi
for command_name in file grep tee; do
    command -v "$command_name" >/dev/null 2>&1 || \
        fail "required command is missing: $command_name"
done

workspace=$(cd "$1" && pwd -P)
engine_root=$(cd "$2" && pwd -P)
case "$engine_root/" in
    "$workspace/"*) ;;
    *) fail 'the isolated Engine must be located below the cooker workspace' ;;
esac
project_input=$3
[[ -f $project_input ]] || fail "project does not exist: $project_input"
project_dir=$(cd "$(dirname "$project_input")" && pwd -P)
project="$project_dir/$(basename "$project_input")"

dotnet="$engine_root/.spark-tools/dotnet/dotnet"
ubt="$engine_root/Engine/Binaries/DotNET/UnrealBuildTool/UnrealBuildTool.dll"
native_llvm="$engine_root/.spark-tools/llvm-20.1.8/bin"
native_clang="$native_llvm/clang"
native_clangxx="$native_llvm/clang++"
toolchain="$workspace/toolchains/native-cross-v26"
engine_profile="$engine_root/.ue5-spark-engine-profile"
toolchain_profile="$toolchain/UE5SparkToolchainProfile.txt"
build_version="$engine_root/Engine/Build/Build.version"
turnkey_rules="$engine_root/Engine/Source/Developer/TargetPlatform/TargetPlatform.Build.cs"
editor_target="$project_dir/Source/FayAvatarRuntimeEditor.Target.cs"
log_dir="$workspace/logs/x86-cooker-build"
parallel_actions=${UE5_SPARK_BUILD_JOBS:-2}
expected_revision=7deeb413d3dc1fc034f48d1aacc0861301829d32
profile_name=ue5.8.0-7deeb413-spark-x86-cooker-v1

if [[ ! $parallel_actions =~ ^[1-4]$ ]]; then
    fail 'UE5_SPARK_BUILD_JOBS must be an integer from 1 through 4'
fi
for required in "$dotnet" "$ubt" "$native_clang" "$native_clangxx" \
    "$build_version" "$engine_profile" "$toolchain_profile" "$turnkey_rules" \
    "$editor_target" "$toolchain/ToolchainVersion.txt" \
    "$toolchain/x86_64-unknown-linux-gnu/bin/clang" \
    "$toolchain/x86_64-unknown-linux-gnu/bin/clang++"; do
    [[ -e $required ]] || fail "required builder input is missing: $required"
done

grep -Fxq "profile=$profile_name" "$engine_profile" &&
    grep -Fxq 'engine_version=5.8.0' "$engine_profile" &&
    grep -Fxq "engine_revision=$expected_revision" "$engine_profile" &&
    grep -Fxq 'host=linux-aarch64' "$engine_profile" &&
    grep -Fxq 'native_llvm=20.1.8' "$engine_profile" || \
    fail "isolated Engine profile is missing or incompatible: $engine_profile"
grep -Fxq "profile=$profile_name" "$toolchain_profile" &&
    grep -Fxq "engine_revision=$expected_revision" "$toolchain_profile" &&
    grep -Fxq 'epic_toolchain=v26_clang-20.1.8-rockylinux8' "$toolchain_profile" &&
    grep -Fxq 'native_llvm=20.1.8' "$toolchain_profile" &&
    grep -Fxq 'archive_sha256=6eef42679b744cdcb50276f2d7cff0a51f7ddd632960e06bfbc3f6b9508ef615' \
        "$toolchain_profile" || \
    fail "native cross-toolchain profile is missing or incompatible: $toolchain_profile"
grep -Eq '"MajorVersion"[[:space:]]*:[[:space:]]*5' "$build_version" &&
    grep -Eq '"MinorVersion"[[:space:]]*:[[:space:]]*8' "$build_version" &&
    grep -Eq '"PatchVersion"[[:space:]]*:[[:space:]]*0' "$build_version" || \
    fail 'the isolated Engine must remain Unreal Engine 5.8.0 exactly'

# The compatibility adjustment is made only in the private, licensed isolated
# Engine tree. This public repository validates the build profile but does not
# redistribute an Epic-source patch.
grep -Eq 'UE_WITH_TURNKEY_SUPPORT[[:space:]]*=[[:space:]]*1' "$turnkey_rules" || \
    fail 'the licensed TargetPlatform/Turnkey source-profile adjustment is missing'
grep -Fq 'bForceBuildTargetPlatforms = true;' "$editor_target" &&
    grep -Fq 'bForceBuildShaderFormats = true;' "$editor_target" || \
    fail 'the project Editor target does not enable target-platform and shader-format modules'

file -L "$dotnet" | grep -q 'ARM aarch64' || fail "dotnet is not native AArch64: $dotnet"
file -L "$native_clang" | grep -q 'ARM aarch64' || fail "clang is not native AArch64: $native_clang"
file -L "$native_clangxx" | grep -q 'ARM aarch64' || fail "clang++ is not native AArch64: $native_clangxx"
"$native_clang" --version | grep -q 'clang version 20\.1\.8' || \
    fail 'the native compiler is not clang 20.1.8'

mkdir -p "$log_dir"
export PATH="$native_llvm:$PATH"
export LINUX_MULTIARCH_ROOT="$toolchain"
export UE5_SPARK_NATIVE_CLANG="$native_clang"
export UE5_SPARK_NATIVE_CLANGXX="$native_clangxx"
export UE_LOCAL_DDC_PATH="$workspace/state/native-build-ddc"

run_target() {
    local target=$1
    shift
    local log="$log_dir/$target.log"
    printf '\nBuilding %s for Linux x86-64 with %s parallel action(s).\n' \
        "$target" "$parallel_actions"
    set +e
    "$dotnet" "$ubt" "$target" Linux Development "$@" \
        -NoUBA -NoDumpSyms -MaxParallelActions="$parallel_actions" \
        2>&1 | tee "$log"
    local status=${PIPESTATUS[0]}
    set -e
    (( status == 0 )) || fail "$target failed with status $status; inspect $log"
}

run_target BlankProgram
file "$engine_root/Engine/Binaries/Linux/BlankProgram" | grep -q 'x86-64' || \
    fail 'BlankProgram did not produce an x86-64 executable'

run_target ShaderCompileWorker
file "$engine_root/Engine/Binaries/Linux/ShaderCompileWorker" | grep -q 'x86-64' || \
    fail 'ShaderCompileWorker did not produce an x86-64 executable'

run_target UnrealPak
host_unrealpak="$engine_root/Engine/Binaries/Linux/UnrealPak"
preserved_x86_unrealpak="$engine_root/Engine/Binaries/Linux/UnrealPak.x86_64"
if file "$host_unrealpak" | grep -q 'x86-64'; then
    :
elif grep -q 'LinuxArm64/UnrealPak' "$host_unrealpak" && \
    file "$preserved_x86_unrealpak" | grep -q 'x86-64'; then
    # The native packager installs this dispatch wrapper after preserving the
    # x86 binary. Keeping it is required for native ARM64 AutomationTool.
    :
else
    fail 'UnrealPak is neither x86-64 nor the verified dual-architecture wrapper'
fi

run_target FayAvatarRuntimeEditor -Project="$project"
file "$engine_root/Engine/Binaries/Linux/UnrealEditor" | grep -q 'x86-64' || \
    fail 'FayAvatarRuntimeEditor did not produce an x86-64 UnrealEditor executable'

printf '\nThe x86-64 Editor/cooker build completed on the ARM64 Spark.\n'
