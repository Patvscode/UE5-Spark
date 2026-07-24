#!/usr/bin/env bash
set -euo pipefail

binary_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)

case $(uname -m) in
    aarch64|arm64)
        host_binary="$binary_dir/../LinuxArm64/UnrealPak"
        ;;
    x86_64|amd64)
        host_binary="$binary_dir/UnrealPak.x86_64"
        ;;
    *)
        printf 'error: UnrealPak host wrapper does not support architecture %s\n' \
            "$(uname -m)" >&2
        exit 69
        ;;
esac

if [[ ! -x $host_binary ]]; then
    printf 'error: UnrealPak host executable is missing: %s\n' "$host_binary" >&2
    exit 66
fi

exec "$host_binary" "$@"
