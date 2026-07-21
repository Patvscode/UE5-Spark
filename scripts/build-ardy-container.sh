#!/usr/bin/env bash
set -euo pipefail

fail() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

[[ $(uname -s) == Linux && $(uname -m) == aarch64 ]] || \
    fail 'build the ARDY image on the Linux ARM64 DGX Spark'
(( ${EUID:-$(id -u)} != 0 )) || fail 'build the ARDY image as the normal workspace user'
command -v docker >/dev/null 2>&1 || fail 'Docker is not available'

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
repository=$(cd "$script_dir/.." && pwd -P)
docker build \
    --pull=false \
    --build-arg ARDY_COMMIT=693f74d13b3d04a0a22ce127ee79c929dd89756b \
    --tag ue5-spark-ardy:0.2.0 \
    "$repository/services/ardy"
