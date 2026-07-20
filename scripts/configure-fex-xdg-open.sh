#!/usr/bin/env bash
set -euo pipefail

usage() {
    printf 'Usage: %s /absolute/path/to/cooker-workspace\n' "${0##*/}" >&2
    printf 'Installs a guarded xdg-open portal adapter only in the rootless FEX guest.\n' >&2
}

fail() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

if (( $# != 1 )); then
    usage
    exit 64
fi
if [[ $(uname -s) != Linux || $(uname -m) != aarch64 ]]; then
    fail "the FEX portal adapter requires Linux/aarch64, not $(uname -s)/$(uname -m)"
fi
if (( ${EUID:-$(id -u)} == 0 )); then
    fail 'run the adapter installer as the normal workspace owner, not root'
fi

for command_name in cmp file grep id install mktemp rm sh; do
    command -v "$command_name" >/dev/null 2>&1 || \
        fail "required command is missing: $command_name"
done

case $1 in
    /*) workspace_input=$1 ;;
    *) fail 'the cooker workspace must be an absolute path' ;;
esac
[[ -d $workspace_input ]] || fail "cooker workspace does not exist: $workspace_input"
workspace=$(cd "$workspace_input" && pwd -P)
[[ $workspace != / ]] || fail 'the filesystem root cannot be used as the cooker workspace'
[[ -O $workspace && -w $workspace ]] || \
    fail 'the cooker workspace must be owned and writable by the invoking user'

rootfs_input="$workspace/rootfs/ubuntu-24.04-x86_64"
state_input="$workspace/state"
[[ -d $rootfs_input ]] || fail "the pinned FEX RootFS is missing: $rootfs_input"
[[ -d $state_input ]] || fail "the FEX state directory is missing: $state_input"
rootfs=$(cd "$rootfs_input" && pwd -P)
state_dir=$(cd "$state_input" && pwd -P)
case "$rootfs/" in
    "$workspace"/*) ;;
    *) fail 'the resolved FEX RootFS escapes the cooker workspace' ;;
esac
case "$state_dir/" in
    "$workspace"/*) ;;
    *) fail 'the resolved FEX state directory escapes the cooker workspace' ;;
esac
[[ -O $rootfs && -O $state_dir && -w $state_dir ]] || \
    fail 'the FEX RootFS and state directory must be owned by the invoking user'

guest_bin_input="$rootfs/usr/bin"
[[ -d $guest_bin_input ]] || fail "the guest binary directory is missing: $guest_bin_input"
guest_bin=$(cd "$guest_bin_input" && pwd -P)
case "$guest_bin/" in
    "$rootfs"/*) ;;
    *) fail 'the resolved guest binary directory escapes the FEX RootFS' ;;
esac
[[ -w $guest_bin ]] || fail "the guest binary directory is not writable: $guest_bin"

guest_gdbus="$guest_bin/gdbus"
guest_shell="$rootfs/bin/sh"
guest_id="$guest_bin/id"
[[ -x $guest_gdbus ]] || fail "the guest gdbus executable is missing: $guest_gdbus"
[[ -x $guest_shell ]] || fail "the guest shell is missing: $guest_shell"
[[ -x $guest_id ]] || fail "the guest id executable is missing: $guest_id"
file "$guest_gdbus" | grep -q 'x86-64' || fail 'the guest gdbus is not an x86-64 ELF'
file -L "$guest_shell" | grep -q 'x86-64' || fail 'the guest shell is not an x86-64 ELF'
file "$guest_id" | grep -q 'x86-64' || fail 'the guest id is not an x86-64 ELF'

temporary=
cleanup() {
    if [[ -n $temporary ]]; then
        rm -f -- "$temporary"
    fi
}
trap cleanup EXIT HUP INT TERM
temporary=$(mktemp "$state_dir/xdg-open-portal.XXXXXX")

{
    printf '%s\n' '#!/bin/sh'
    printf '%s\n' '# UE5-SPARK-FEX-XDG-OPEN-PORTAL-V2'
    printf '%s\n' 'set -eu'
    printf '%s\n' 'if [ "$#" -ne 1 ]; then'
    printf '%s\n' '    exit 64'
    printf '%s\n' 'fi'
    printf '%s\n' 'case "$1" in'
    printf '%s\n' '    http://?*|https://?*) ;;'
    printf '%s\n' '    *) exit 65 ;;'
    printf '%s\n' 'esac'
    printf '%s\n' 'if [ -z "${XDG_RUNTIME_DIR:-}" ]; then'
    printf '%s\n' '    XDG_RUNTIME_DIR="/run/user/$(/usr/bin/id -u)"'
    printf '%s\n' '    export XDG_RUNTIME_DIR'
    printf '%s\n' 'fi'
    printf '%s\n' 'if [ ! -S "$XDG_RUNTIME_DIR/bus" ]; then'
    printf '%s\n' '    exit 69'
    printf '%s\n' 'fi'
    printf '%s\n' 'if [ -z "${DBUS_SESSION_BUS_ADDRESS:-}" ]; then'
    printf '%s\n' '    DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"'
    printf '%s\n' '    export DBUS_SESSION_BUS_ADDRESS'
    printf '%s\n' 'fi'
    printf '%s\n' 'exec /usr/bin/gdbus call --session \'
    printf '%s\n' '    --dest org.freedesktop.portal.Desktop \'
    printf '%s\n' '    --object-path /org/freedesktop/portal/desktop \'
    printf '%s\n' '    --method org.freedesktop.portal.OpenURI.OpenURI \'
    printf '%s\n' '    "" "$1" "{}" >/dev/null 2>&1'
} >"$temporary"
sh -n "$temporary" || fail 'the generated guest portal adapter failed its syntax check'

target="$guest_bin/xdg-open"
if [[ -e $target || -L $target ]]; then
    if cmp -s "$temporary" "$target" && [[ -x $target ]]; then
        printf 'The guarded FEX guest portal adapter is already installed.\n'
        exit 0
    fi
    if [[ -f $target && ! -L $target && -O $target ]] &&
       grep -qx '# UE5-SPARK-FEX-XDG-OPEN-PORTAL-V1' "$target"; then
        printf 'Upgrading the guarded FEX guest portal adapter from V1.\n'
    else
        fail "refusing to replace an existing guest xdg-open: $target"
    fi
fi

install -m 0755 "$temporary" "$target"
[[ -x $target ]] || fail "the installed guest adapter is not executable: $target"
cmp -s "$temporary" "$target" || fail 'the installed guest adapter failed verification'

printf 'Installed the guarded portal adapter inside the FEX guest RootFS.\n'
printf 'No host or system xdg-open file was changed.\n'
