#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 Patrick Mello
# SPDX-License-Identifier: MIT

set -euo pipefail

if (( $# != 2 )); then
    echo "usage: $0 /path/to/ufbx/checkout /path/to/ufbx_dump_skin" >&2
    exit 2
fi

ufbx_root="$(cd "$1" && pwd -P)"
output="$2"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"

if [[ ! -f "$ufbx_root/ufbx.c" || ! -f "$ufbx_root/ufbx.h" ]]; then
    echo "ufbx.c and ufbx.h were not found under $ufbx_root" >&2
    exit 1
fi

mkdir -p "$(dirname "$output")"
cc -O2 -DNDEBUG -std=c11 \
    -I"$ufbx_root" \
    "$script_dir/ufbx_dump_skin.c" \
    "$ufbx_root/ufbx.c" \
    -lm \
    -o "$output"
chmod 0755 "$output"
"$output" 2>&1 | head -1 || true
echo "Built ARM64-safe ufbx dumper: $output"
