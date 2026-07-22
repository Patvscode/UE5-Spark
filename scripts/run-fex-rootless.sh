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

for command_name in basename chmod dirname env mkdir readlink; do
    command -v "$command_name" >/dev/null 2>&1 || \
        fail "required command is missing: $command_name"
done

case $1 in
    /*) workspace=$1 ;;
    *) fail 'the cooker workspace must be an absolute path' ;;
esac
shift 2

[[ -d $workspace && ! -L $workspace ]] || \
    fail "the cooker workspace must be one real directory: $workspace"
workspace=$(cd "$workspace" && pwd -P)

fex_root="$workspace/fex-root"
rootfs_root="$workspace/rootfs/ubuntu-24.04-x86_64"
epic_toolchain="$workspace/toolchains/v26_clang-20.1.8-rockylinux8"
fex_binary="$fex_root/usr/bin/FEX"
script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
fex_thunk_config=${FEX_THUNKCONFIG:-"$script_dir/fex-vulkan-thunks.json"}

state_root_input=${FEX_STATE_ROOT:-"$workspace/state"}
case $state_root_input in
    /*) ;;
    *) fail 'FEX_STATE_ROOT must be an absolute path below the cooker workspace' ;;
esac
if [[ -e $state_root_input || -L $state_root_input ]]; then
    [[ -d $state_root_input && ! -L $state_root_input ]] || \
        fail 'FEX_STATE_ROOT must be one real directory'
    state_root=$(cd "$state_root_input" && pwd -P)
else
    state_parent_input=$(dirname "$state_root_input")
    [[ -d $state_parent_input && ! -L $state_parent_input ]] || \
        fail 'FEX_STATE_ROOT parent must be one existing real directory'
    state_parent=$(cd "$state_parent_input" && pwd -P)
    state_root="$state_parent/$(basename "$state_root_input")"
fi
state_parent_root="$workspace/state"
case "$state_root/" in
    "$state_parent_root"/) ;;
    "$state_parent_root"/*) ;;
    *) fail 'FEX_STATE_ROOT must remain at or below the workspace state root' ;;
esac
private_state_override=1
if [[ $state_root == "$state_parent_root" ]]; then
    private_state_override=0
fi

[[ -x "$fex_binary" ]] || fail "FEX is missing; run setup-fex-rootless.sh first: $fex_binary"
[[ -x "$rootfs_root/usr/bin/uname" ]] || fail "the x86-64 RootFS is missing: $rootfs_root"
[[ -f "$fex_thunk_config" ]] || fail "the FEX thunk configuration is missing: $fex_thunk_config"

mkdir -p "$state_root"
[[ -d $state_root && ! -L $state_root && -O $state_root ]] || \
    fail 'could not create a safe user-owned FEX state root'
if (( private_state_override == 1 )); then
    chmod 0700 "$state_root"
fi
for state_directory in data config cache ue-ddc; do
    state_path="$state_root/$state_directory"
    if [[ -e $state_path || -L $state_path ]]; then
        [[ -d $state_path && ! -L $state_path && -O $state_path ]] || \
            fail "FEX state child must be one real user-owned directory: $state_directory"
    else
        mkdir "$state_path"
    fi
    if (( private_state_override == 1 )); then
        chmod 0700 "$state_path"
    fi
done
server_socket="$state_root/fex-server.socket"
if [[ -e $server_socket || -L $server_socket ]]; then
    [[ -S $server_socket && ! -L $server_socket && -O $server_socket ]] || \
        fail 'the existing FEX server socket is unsafe'
fi

export FEX_PORTABLE=1
export FEX_ROOTFS="$rootfs_root"
export FEX_STATE_ROOT="$state_root"
export FEX_APP_DATA_LOCATION="$state_root/data/"
export FEX_APP_CONFIG_LOCATION="$state_root/config/"
export FEX_APP_CACHE_LOCATION="$state_root/cache/"
export FEX_SERVERSOCKETPATH="$server_socket"
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
