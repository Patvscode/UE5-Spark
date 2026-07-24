#!/usr/bin/env bash
set -euo pipefail

usage() {
    printf 'Usage: %s /absolute/path/to/cooker-workspace\n' "${0##*/}" >&2
    printf 'Downloads and extracts pinned FEX files entirely below that directory.\n' >&2
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

if [[ "$(uname -s)" != "Linux" || "$(uname -m)" != "aarch64" ]]; then
    fail "this rootless FEX bundle is for Linux/aarch64, not $(uname -s)/$(uname -m)"
fi

for command_name in curl dpkg-deb file sha256sum unsquashfs; do
    command -v "$command_name" >/dev/null 2>&1 || fail "required command is missing: $command_name"
done

fex_version=2607
fex_deb_name="fex-emu-armv8.4_${fex_version}-1~n_arm64.deb"
fex_deb_url="https://ppa.launchpadcontent.net/fex-emu/fex/ubuntu/pool/main/f/fex-emu-armv8.4/$fex_deb_name"
fex_deb_sha256=39e2ce943f5315c9626c7d4f615e2c5367fed2cca892cce19b6ba860036e564c

rootfs_name=Ubuntu_24_04.sqsh
rootfs_url=https://rootfs.fex-emu.gg/Ubuntu_24_04/2025-12-27/Ubuntu_24_04.sqsh
rootfs_xxh64=f1aafb8234af1ac5
extract_jobs=${UE5_SPARK_SETUP_JOBS:-4}

if [[ ! "$extract_jobs" =~ ^[1-9][0-9]*$ ]] || (( extract_jobs > 8 )); then
    fail 'UE5_SPARK_SETUP_JOBS must be an integer from 1 through 8'
fi

downloads="$workspace/downloads"
fex_root="$workspace/fex-root"
rootfs_root="$workspace/rootfs/ubuntu-24.04-x86_64"
state_root="$workspace/state"

mkdir -p "$downloads" "$workspace/rootfs" \
    "$state_root/data" "$state_root/config" "$state_root/cache" \
    "$state_root/ue-ddc" "$workspace/logs"

download_file() {
    local url=$1
    local destination=$2
    local partial="$destination.partial"

    if [[ -f "$destination" ]]; then
        printf 'Using existing download: %s\n' "$destination"
        return
    fi
    if [[ -e "$destination" ]]; then
        fail "download destination exists but is not a regular file: $destination"
    fi

    printf 'Downloading %s\n' "$url"
    curl --fail --location --continue-at - --output "$partial" "$url"
    mv "$partial" "$destination"
}

fex_deb="$downloads/$fex_deb_name"
download_file "$fex_deb_url" "$fex_deb"
actual_fex_sha=$(sha256sum "$fex_deb" | awk '{print $1}')
if [[ "$actual_fex_sha" != "$fex_deb_sha256" ]]; then
    fail "FEX package checksum mismatch; leave the file in place for inspection: $fex_deb"
fi

fex_binary="$fex_root/usr/bin/FEX"
if [[ ! -x "$fex_binary" ]]; then
    if [[ -e "$fex_root" ]] && find "$fex_root" -mindepth 1 -print -quit | grep -q .; then
        fail "FEX destination is nonempty but incomplete: $fex_root"
    fi
    mkdir -p "$fex_root"
    dpkg-deb --extract "$fex_deb" "$fex_root"
fi

if ! file "$fex_binary" | grep -q 'ARM aarch64'; then
    fail "the extracted FEX interpreter is not an AArch64 ELF: $fex_binary"
fi

rootfs_image="$downloads/$rootfs_name"
download_file "$rootfs_url" "$rootfs_image"

hash_output=$("$fex_root/usr/bin/FEXRootFSFetcher" "$rootfs_image")
printf '%s\n' "$hash_output"
actual_rootfs_hash=$(printf '%s\n' "$hash_output" | sed -n 's/.* has hash: \([[:xdigit:]]*\)$/\1/p')
if [[ "$actual_rootfs_hash" != "$rootfs_xxh64" ]]; then
    fail "FEX RootFS XXH64 mismatch; leave the file in place for inspection: $rootfs_image"
fi

if [[ ! -x "$rootfs_root/usr/bin/uname" ]]; then
    if [[ -e "$rootfs_root" ]] && find "$rootfs_root" -mindepth 1 -print -quit | grep -q .; then
        fail "RootFS destination is nonempty but incomplete: $rootfs_root"
    fi
    mkdir -p "$rootfs_root"
    unsquashfs -processors "$extract_jobs" -no-progress -dest "$rootfs_root" "$rootfs_image"
fi

if ! file "$rootfs_root/usr/bin/uname" | grep -q 'x86-64'; then
    fail "the extracted RootFS does not contain an x86-64 uname binary"
fi

printf '\nRootless FEX workspace is ready: %s\n' "$workspace"
printf 'No package, binfmt handler, driver, service, or system directory was changed.\n'
printf 'Next: %s %s -- /usr/bin/uname -m\n' \
    "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)/run-fex-rootless.sh" \
    "$workspace"
