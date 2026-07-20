#!/usr/bin/env bash
set -euo pipefail

usage() {
    printf 'Usage: %s /absolute/path/to/cooker-workspace -- /path/to/x86_64/program [arguments...]\n' \
        "${0##*/}" >&2
}

fail() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

if [[ $# -lt 3 || $2 != -- ]]; then
    usage
    exit 64
fi

case $1 in
    /*) workspace=$1 ;;
    *) fail 'the cooker workspace must be an absolute path' ;;
esac
shift 2

fex_root="$workspace/fex-root"
rootfs_root="$workspace/rootfs/ubuntu-24.04-x86_64"
state_root="$workspace/state"
epic_toolchain="$workspace/toolchains/v26_clang-20.1.8-rockylinux8"
fex_binary="$fex_root/usr/bin/FEX"
script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
fex_thunk_config=${FEX_THUNKCONFIG:-"$script_dir/fex-vulkan-thunks.json"}

[[ -x "$fex_binary" ]] || fail "FEX is missing; run setup-fex-rootless.sh first: $fex_binary"
[[ -x "$rootfs_root/usr/bin/uname" ]] || fail "the x86-64 RootFS is missing: $rootfs_root"
[[ -f "$fex_thunk_config" ]] || fail "the FEX thunk configuration is missing: $fex_thunk_config"

mkdir -p "$state_root/data" "$state_root/config" "$state_root/cache" "$state_root/ue-ddc"

export FEX_PORTABLE=1
export FEX_ROOTFS="$rootfs_root"
export FEX_APP_DATA_LOCATION="$state_root/data/"
export FEX_APP_CONFIG_LOCATION="$state_root/config/"
export FEX_APP_CACHE_LOCATION="$state_root/cache/"
export FEX_SERVERSOCKETPATH="$state_root/fex-server.socket"
export FEX_THUNKHOSTLIBS="$fex_root/usr/lib/aarch64-linux-gnu/fex-emu/HostThunks"
export FEX_THUNKGUESTLIBS="$fex_root/usr/share/fex-emu/GuestThunks"
export FEX_THUNKCONFIG="$fex_thunk_config"
export FEX_OUTPUTLOG=stderr
export FEX_SILENTLOG="${FEX_SILENTLOG:-1}"

# Let Unreal's platform validator discover the official Epic v26 SDK without
# installing it globally. The same path is visible inside FEX's guest view.
if [[ -f "$epic_toolchain/ToolchainVersion.txt" ]]; then
    export LINUX_MULTIARCH_ROOT="$epic_toolchain"
fi

# Unreal's environment key contains hyphens, so pass it with env instead of
# trying to export it as a shell identifier.
exec env "UE-LocalDataCachePath=$state_root/ue-ddc" "$fex_binary" "$@"
