#!/usr/bin/env bash
set -euo pipefail

usage() {
    printf 'Usage: %s /absolute/path/to/cooker-workspace /path/to/UnrealEngine\n' \
        "${0##*/}" >&2
    printf 'Creates a workspace-local UE 5.8 x86-64 cross-toolchain driven by native ARM64 clang.\n' >&2
}

fail() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

if [[ $# -ne 2 ]]; then
    usage
    exit 64
fi
case $1 in
    /*) workspace=$1 ;;
    *) fail 'the cooker workspace must be an absolute path' ;;
esac

if [[ "$(uname -s)" != Linux || "$(uname -m)" != aarch64 ]]; then
    fail "this adapter requires Linux/aarch64, not $(uname -s)/$(uname -m)"
fi

engine_root=$(cd "$2" && pwd -P)
native_llvm="$engine_root/.spark-tools/llvm-20.1.8/bin"
native_clang="$native_llvm/clang"
native_clangxx="$native_llvm/clang++"
for required in curl file git grep sha256sum tar "$native_clang" "$native_clangxx" \
    "$native_llvm/llvm-ar" "$native_llvm/llvm-objcopy" "$native_llvm/ld.lld"; do
    if [[ $required == */* ]]; then
        [[ -x $required ]] || fail "required native tool is missing: $required"
    else
        command -v "$required" >/dev/null 2>&1 || fail "required command is missing: $required"
    fi
done
file -L "$native_clang" | grep -q 'ARM aarch64' || fail "native clang is not AArch64: $native_clang"
file -L "$native_clangxx" | grep -q 'ARM aarch64' || fail "native clang++ is not AArch64: $native_clangxx"
"$native_clang" --version | grep -q 'clang version 20\.1\.8' || \
    fail 'the prepared source profile requires native clang 20.1.8'

build_version="$engine_root/Engine/Build/Build.version"
expected_revision=7deeb413d3dc1fc034f48d1aacc0861301829d32
profile_name=ue5.8.0-7deeb413-spark-x86-cooker-v1
[[ -f $build_version ]] || fail 'source does not look like Unreal Engine'
grep -Eq '"MajorVersion"[[:space:]]*:[[:space:]]*5' "$build_version" &&
    grep -Eq '"MinorVersion"[[:space:]]*:[[:space:]]*8' "$build_version" &&
    grep -Eq '"PatchVersion"[[:space:]]*:[[:space:]]*0' "$build_version" || \
    fail 'the source-build profile requires Unreal Engine 5.8.0 exactly'
actual_revision=$(git -C "$engine_root" rev-parse HEAD 2>/dev/null) || \
    fail 'the source-build profile requires a Git checkout with verifiable revision metadata'
[[ $actual_revision == "$expected_revision" ]] || \
    fail "the source-build profile requires Unreal revision $expected_revision, not $actual_revision"

toolchain_version=v26_clang-20.1.8-rockylinux8
archive_name="native-linux-$toolchain_version.tar.gz"
archive_url="https://cdn.unrealengine.com/Toolchain_Linux/$archive_name"
archive_sha256=6eef42679b744cdcb50276f2d7cff0a51f7ddd632960e06bfbc3f6b9508ef615
downloads="$workspace/downloads"
official_root="$workspace/toolchains/$toolchain_version"
overlay_root="$workspace/toolchains/native-cross-v26"
overlay_profile="$overlay_root/UE5SparkToolchainProfile.txt"
archive="$downloads/$archive_name"
script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
wrapper="$script_dir/native-clang-wrapper.sh"

mkdir -p "$downloads" "$workspace/toolchains" "$workspace/smoke/native-cross"

if [[ ! -f $archive ]]; then
    partial="$archive.partial"
    printf 'Downloading Epic UE 5.8 v26 Linux toolchain.\n'
    curl --fail --location --continue-at - --output "$partial" "$archive_url"
    mv "$partial" "$archive"
fi
actual_sha=$(sha256sum "$archive" | awk '{print $1}')
[[ $actual_sha == "$archive_sha256" ]] || \
    fail "Epic toolchain SHA-256 mismatch; leave the archive for inspection: $archive"
tar -tzf "$archive" >/dev/null || fail "Epic toolchain archive validation failed: $archive"

if [[ ! -f $official_root/ToolchainVersion.txt ]]; then
    if [[ -e $official_root ]]; then
        fail "official toolchain destination exists but is incomplete: $official_root"
    fi
    tar -xzf "$archive" -C "$workspace/toolchains"
fi

if [[ ! -f $overlay_root/ToolchainVersion.txt ]]; then
    if [[ -e $overlay_root ]]; then
        fail "native cross-toolchain destination exists but is incomplete: $overlay_root"
    fi

    # Hard links keep a pristine, archive-restorable copy of the Epic sysroots
    # without consuming another 3.4 GiB. Only the new overlay's bin directories
    # are moved aside and replaced with native ARM64 tools.
    cp -al "$official_root" "$overlay_root"
    for architecture in x86_64-unknown-linux-gnu aarch64-unknown-linux-gnueabi; do
        architecture_root="$overlay_root/$architecture"
        mv "$architecture_root/bin" "$architecture_root/bin-x86-host"
        mkdir "$architecture_root/bin"
        for tool_name in ld.lld lld llvm-ar llvm-cov llvm-objcopy llvm-profdata \
            llvm-ranlib llvm-symbolizer llvm-strip; do
            if [[ -x $native_llvm/$tool_name ]]; then
                ln -s "$native_llvm/$tool_name" "$architecture_root/bin/$tool_name"
            fi
        done
    done
fi

for architecture in x86_64-unknown-linux-gnu aarch64-unknown-linux-gnueabi; do
    architecture_root="$overlay_root/$architecture"
    cp "$wrapper" "$architecture_root/bin/clang"
    cp "$wrapper" "$architecture_root/bin/clang++"
    [[ -x $overlay_root/$architecture/bin/clang++ ]] || \
        fail "native compiler wrapper is missing for $architecture"
    [[ -d $overlay_root/$architecture/bin-x86-host ]] || \
        fail "recoverable original tool directory is missing for $architecture"
done

export UE5_SPARK_NATIVE_CLANG="$native_clang"
export UE5_SPARK_NATIVE_CLANGXX="$native_clangxx"
x86_root="$overlay_root/x86_64-unknown-linux-gnu"
smoke_root="$workspace/smoke/native-cross"
"$x86_root/bin/clang" -target x86_64-unknown-linux-gnu \
    --sysroot="$x86_root" -x c -c /dev/null -o "$smoke_root/empty-c.o"
"$x86_root/bin/clang++" -target x86_64-unknown-linux-gnu \
    --sysroot="$x86_root" -x c++ -c /dev/null -o "$smoke_root/empty.o"
"$x86_root/bin/clang++" -target x86_64-unknown-linux-gnu \
    --sysroot="$x86_root" -fuse-ld=lld -shared "$smoke_root/empty.o" \
    -o "$smoke_root/libempty.so"
file "$smoke_root/libempty.so" | grep -q 'x86-64' || fail 'native cross-compile smoke test failed'

{
    printf 'profile=%s\n' "$profile_name"
    printf 'engine_revision=%s\n' "$actual_revision"
    printf 'epic_toolchain=v26_clang-20.1.8-rockylinux8\n'
    printf 'native_llvm=20.1.8\n'
    printf 'archive_sha256=%s\n' "$archive_sha256"
} >"$overlay_profile"

printf 'Native ARM64 -> x86-64 UE toolchain adapter is ready: %s\n' "$overlay_root"
printf 'Validated source profile: %s\n' "$profile_name"
printf 'Original x86-host tools remain recoverable below each bin-x86-host directory.\n'
