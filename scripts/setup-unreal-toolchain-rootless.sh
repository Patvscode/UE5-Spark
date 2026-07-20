#!/usr/bin/env bash
set -euo pipefail

usage() {
    printf 'Usage: %s /absolute/path/to/cooker-workspace\n' "${0##*/}" >&2
    printf 'Downloads Epic UE 5.8 Linux native toolchain v26 below that directory.\n' >&2
}

fail() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

if [[ $# -ne 1 ]]; then
    usage
    exit 64
fi

case $1 in
    /*) workspace=$1 ;;
    *) fail 'the cooker workspace must be an absolute path' ;;
esac

for command_name in curl file sha256sum tar; do
    command -v "$command_name" >/dev/null 2>&1 || fail "required command is missing: $command_name"
done

archive_name=native-linux-v26_clang-20.1.8-rockylinux8.tar.gz
archive_url="https://cdn.unrealengine.com/Toolchain_Linux/$archive_name"
archive_sha256=6eef42679b744cdcb50276f2d7cff0a51f7ddd632960e06bfbc3f6b9508ef615
toolchain_name=v26_clang-20.1.8-rockylinux8
downloads="$workspace/downloads"
toolchains="$workspace/toolchains"
archive="$downloads/$archive_name"
toolchain="$toolchains/$toolchain_name"

mkdir -p "$downloads" "$toolchains"

if [[ ! -f "$archive" ]]; then
    if [[ -e "$archive" ]]; then
        fail "toolchain download destination exists but is not a regular file: $archive"
    fi
    partial="$archive.partial"
    curl --fail --location --continue-at - --output "$partial" "$archive_url"
    mv "$partial" "$archive"
fi

actual_sha=$(sha256sum "$archive" | awk '{print $1}')
if [[ "$actual_sha" != "$archive_sha256" ]]; then
    fail "toolchain checksum mismatch; leave the file in place for inspection: $archive"
fi

clang_path="$toolchain/aarch64-unknown-linux-gnueabi/bin/clang++"
if [[ ! -x "$clang_path" ]]; then
    if [[ -e "$toolchain" ]] && find "$toolchain" -mindepth 1 -print -quit | grep -q .; then
        fail "toolchain destination is nonempty but incomplete: $toolchain"
    fi
    tar -xzf "$archive" -C "$toolchains"
fi

file "$clang_path" | grep -q 'x86-64' || fail 'Epic toolchain clang is not an x86-64 ELF'

printf 'Epic UE 5.8 toolchain is ready: %s\n' "$toolchain"
printf 'It will run inside FEX and emit native LinuxArm64 project binaries.\n'
