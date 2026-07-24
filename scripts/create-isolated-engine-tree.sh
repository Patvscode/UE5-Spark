#!/usr/bin/env bash
set -euo pipefail

usage() {
    printf 'Usage: %s /path/to/source/UnrealEngine /absolute/path/to/isolated/UnrealEngine\n' \
        "${0##*/}" >&2
}

fail() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

if [[ $# -ne 2 ]]; then
    usage
    exit 64
fi
source_root=$(cd "$1" && pwd -P)
case $2 in
    /*) destination_input=$2 ;;
    *) fail 'the destination must be an absolute path' ;;
esac

if [[ $(uname -s) != Linux || $(uname -m) != aarch64 ]]; then
    fail "this isolated source-build profile requires Linux/aarch64, not $(uname -s)/$(uname -m)"
fi
if (( ${EUID:-$(id -u)} == 0 )); then
    fail 'create the isolated tree as the normal workspace owner, not root'
fi

for command_name in file git grep realpath rsync; do
    command -v "$command_name" >/dev/null 2>&1 || \
        fail "required command is missing: $command_name"
done

destination=$(realpath -m -- "$destination_input")
[[ $destination != / ]] || fail 'the destination cannot be the filesystem root'
[[ $source_root != "$destination" ]] || fail 'source and destination must differ'
case "$destination/" in
    "$source_root/"*) fail 'the destination must not be inside the source tree' ;;
esac
case "$source_root/" in
    "$destination/"*) fail 'the source tree must not be inside the destination' ;;
esac

build_version="$source_root/Engine/Build/Build.version"
expected_revision=7deeb413d3dc1fc034f48d1aacc0861301829d32
profile_name=ue5.8.0-7deeb413-spark-x86-cooker-v1
profile_file=.ue5-spark-engine-profile
[[ -f $build_version ]] || fail 'source does not look like Unreal Engine'
grep -Eq '"MajorVersion"[[:space:]]*:[[:space:]]*5' "$build_version" &&
    grep -Eq '"MinorVersion"[[:space:]]*:[[:space:]]*8' "$build_version" &&
    grep -Eq '"PatchVersion"[[:space:]]*:[[:space:]]*0' "$build_version" || \
    fail 'the source-build profile requires Unreal Engine 5.8.0 exactly'

actual_revision=$(git -C "$source_root" rev-parse HEAD 2>/dev/null) || \
    fail 'the source-build profile requires a Git checkout with verifiable revision metadata'
[[ $actual_revision == "$expected_revision" ]] || \
    fail "the source-build profile requires Unreal revision $expected_revision, not $actual_revision"

native_dotnet="$source_root/.spark-tools/dotnet/dotnet"
native_clang="$source_root/.spark-tools/llvm-20.1.8/bin/clang"
native_clangxx="$source_root/.spark-tools/llvm-20.1.8/bin/clang++"
for native_tool in "$native_dotnet" "$native_clang" "$native_clangxx"; do
    [[ -x $native_tool ]] || fail "prepared source profile is missing a native tool: $native_tool"
    file -L "$native_tool" | grep -q 'ARM aarch64' || \
        fail "prepared source-profile tool is not AArch64: $native_tool"
done
"$native_clang" --version | grep -q 'clang version 20\.1\.8' || \
    fail 'the prepared source profile requires native clang 20.1.8'

[[ ! -e $destination ]] || fail "destination already exists: $destination"

mkdir -p "$destination"

# Immutable source, content, and third-party inputs are hard-linked. Generated
# directories are omitted, while mutable binary/program inputs are copied below.
rsync -a --link-dest="$source_root/" \
    --exclude='/.git/' \
    --exclude='/.spark-build/' \
    --exclude='Binaries/' \
    --exclude='Intermediate/' \
    --exclude='Saved/' \
    --exclude='/Engine/DerivedDataCache/' \
    --exclude='/Engine/Programs/' \
    --exclude='/LocalBuilds/' \
    "$source_root/" "$destination/"

# UnrealBuildTool writes its log below Engine/Programs, so this small directory
# must not share inodes with the protected source tree.
mkdir -p "$destination/Engine/Programs"
if [[ -d $source_root/Engine/Programs ]]; then
    rsync -a --exclude='Binaries/' --exclude='Intermediate/' --exclude='Saved/' \
        "$source_root/Engine/Programs/" "$destination/Engine/Programs/"
fi

# Binaries directories also occur inside plugins and platform extensions.
# Copy every one rather than hard-linking or silently dropping binary-only
# third-party inputs.
while IFS= read -r -d '' source_binaries; do
    relative=${source_binaries#"$source_root"/}
    destination_binaries="$destination/$relative"
    mkdir -p "$destination_binaries"
    rsync -a --exclude='Intermediate/' --exclude='Saved/' \
        "$source_binaries/" "$destination_binaries/"
done < <(find "$source_root" \
    \( -path "$source_root/.git" -o \
       -path "$source_root/Engine/DerivedDataCache" -o \
       -type d \( -name Intermediate -o -name Saved \) \) -prune -o \
    -type d -name Binaries -print0)

mkdir -p "$destination/Engine/DerivedDataCache" \
    "$destination/Engine/Intermediate" "$destination/Engine/Saved"

source_ddc_module="$source_root/Engine/Source/Developer/DerivedDataCache"
destination_ddc_module="$destination/Engine/Source/Developer/DerivedDataCache"
if [[ -d $source_ddc_module && ! -d $destination_ddc_module ]]; then
    fail 'the DerivedDataCache source module was incorrectly excluded'
fi

{
    printf 'profile=%s\n' "$profile_name"
    printf 'engine_version=5.8.0\n'
    printf 'engine_revision=%s\n' "$actual_revision"
    printf 'host=linux-aarch64\n'
    printf 'native_llvm=20.1.8\n'
} >"$destination/$profile_file"

source_probe="$source_root/Engine/Binaries/DotNET/UnrealBuildTool/UnrealBuildTool.dll"
destination_probe="$destination/Engine/Binaries/DotNET/UnrealBuildTool/UnrealBuildTool.dll"
[[ -f $source_probe && -f $destination_probe ]] || fail 'UnrealBuildTool copy is incomplete'
if [[ $source_probe -ef $destination_probe ]]; then
    fail 'Engine/Binaries was unexpectedly hard-linked; do not build in this tree'
fi

printf 'Isolated Engine build tree is ready: %s\n' "$destination"
printf 'Validated source profile: %s\n' "$profile_name"
printf 'Do not run Setup.sh or GenerateProjectFiles.sh in this hard-linked build tree.\n'
