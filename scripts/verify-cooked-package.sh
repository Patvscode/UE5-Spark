#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 || ! -d "$1" ]]; then
    printf 'Usage: %s /path/to/cooked/archive\n' "${0##*/}" >&2
    exit 64
fi

archive_root=$(cd "$1" && pwd -P)
mapfile -t launchers < <(find "$archive_root" -type f -name 'FayAvatarRuntime.sh' -print)

if [[ ${#launchers[@]} -ne 1 ]]; then
    printf 'error: expected exactly one FayAvatarRuntime.sh launcher under %s; found %d\n' \
        "$archive_root" "${#launchers[@]}" >&2
    exit 1
fi

launcher=${launchers[0]}
package_root=$(cd "$(dirname "$launcher")" && pwd -P)
game_root="$package_root/FayAvatarRuntime"
game_binary="$game_root/Binaries/Linux/FayAvatarRuntime"

if [[ ! -x "$launcher" ]]; then
    printf 'error: package launcher is not executable: %s\n' "$launcher" >&2
    exit 1
fi
if [[ ! -x "$game_binary" ]]; then
    printf 'error: expected packaged game executable is missing: %s\n' "$game_binary" >&2
    exit 1
fi

description=$(file -b "$game_binary")
if [[ "$description" != *"ELF 64-bit"* || "$description" != *"ARM aarch64"* ]]; then
    printf 'error: packaged FayAvatarRuntime is not a Linux AArch64 ELF\n' >&2
    printf '  %s: %s\n' "$game_binary" "$description" >&2
    exit 1
fi

mapfile -t containers < <(find "$game_root/Content/Paks" -type f \( -name '*.pak' -o -name '*.utoc' \) -print 2>/dev/null)
if [[ ${#containers[@]} -eq 0 ]]; then
    printf 'error: no cooked .pak or .utoc exists under %s/Content/Paks\n' "$game_root" >&2
    exit 1
fi

printf 'Launcher: %s\n' "$launcher"
printf 'ARM64 game executable: %s\n' "$game_binary"
printf '  %s\n' "$description"
printf 'Cooked content containers: %s\n' "${#containers[@]}"
printf 'Package verification passed.\n'
