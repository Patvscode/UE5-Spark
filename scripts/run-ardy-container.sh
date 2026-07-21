#!/usr/bin/env bash
set -euo pipefail

fail() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

if (( $# < 1 || $# > 2 )); then
    printf 'Usage: %s /private/read-only/checkpoints-root [mock|ardy]\n' "${0##*/}" >&2
    exit 64
fi
[[ $(uname -s) == Linux && $(uname -m) == aarch64 ]] || \
    fail 'run the ARDY service on the Linux ARM64 DGX Spark'
(( ${EUID:-$(id -u)} != 0 )) || fail 'run the service as the normal workspace user'
command -v docker >/dev/null 2>&1 || fail 'Docker is not available'

models_root=$(cd "$1" && pwd -P)
provider=${2:-mock}
case $provider in
    mock|ardy) ;;
    *) fail 'provider must be mock or ardy' ;;
esac
[[ -d $models_root && ! -L $models_root ]] || fail 'checkpoint root must be a real directory'
docker image inspect ue5-spark-ardy:0.2.0 >/dev/null 2>&1 || \
    fail 'build ue5-spark-ardy:0.2.0 first'

exec docker run --rm \
    --name ue5-spark-ardy \
    --gpus all \
    --network host \
    --read-only \
    --cap-drop ALL \
    --security-opt no-new-privileges:true \
    --pids-limit 512 \
    --shm-size 4g \
    --tmpfs /tmp:rw,noexec,nosuid,size=1g \
    --user "$(id -u):$(id -g)" \
    --mount "type=bind,src=$models_root,dst=/models,readonly" \
    ue5-spark-ardy:0.2.0 \
    --host 127.0.0.1 --port 8777 --provider "$provider" --models-root /models
