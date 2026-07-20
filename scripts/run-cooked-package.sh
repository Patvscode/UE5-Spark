#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
    printf 'Usage: %s /path/to/FayAvatarRuntime-Arm64.sh [Unreal arguments...]\n' \
        "${0##*/}" >&2
    exit 64
fi

if [[ "$(uname -s)" != "Linux" || "$(uname -m)" != "aarch64" ]]; then
    printf 'error: the packaged Spark runtime requires Linux/aarch64\n' >&2
    exit 69
fi
if [[ ${EUID:-$(id -u)} -eq 0 ]]; then
    printf 'error: do not run the avatar application as root\n' >&2
    exit 77
fi

launcher_input=$1
shift
if [[ ! -f "$launcher_input" ]]; then
    printf 'error: launcher does not exist: %s\n' "$launcher_input" >&2
    exit 66
fi

launcher_dir=$(cd "$(dirname "$launcher_input")" && pwd -P)
launcher="$launcher_dir/$(basename "$launcher_input")"
if [[ $(basename "$launcher") != 'FayAvatarRuntime-Arm64.sh' || ! -x "$launcher" ]]; then
    printf 'error: expected an executable FayAvatarRuntime-Arm64.sh launcher: %s\n' \
        "$launcher" >&2
    exit 77
fi

game_root="$launcher_dir/FayAvatarRuntime"
game_binary="$game_root/Binaries/LinuxArm64/FayAvatarRuntime"
if [[ ! -x "$game_binary" ]]; then
    printf 'error: expected packaged game executable is missing: %s\n' "$game_binary" >&2
    exit 65
fi

description=$(file -b "$game_binary")
if [[ "$description" != *"ELF 64-bit"* || "$description" != *"ARM aarch64"* ]]; then
    printf 'error: packaged FayAvatarRuntime is not a Linux AArch64 ELF\n' >&2
    printf '  %s\n' "$description" >&2
    exit 65
fi
"$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)/verify-cooked-package.sh" "$launcher_dir"

printf 'Launcher: %s\n' "$launcher"
printf 'ARM64 game executable: %s\n' "$game_binary"
printf 'Starting Unreal with Vulkan; no system settings will be changed.\n'

cd "$launcher_dir"
exec "$launcher" -vulkan -log "$@"
