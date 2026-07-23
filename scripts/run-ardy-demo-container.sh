#!/usr/bin/env bash
set -euo pipefail

fail() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

if (( $# != 2 )); then
    printf 'Usage: %s MODELS_ROOT ENCODER_CACHE_ROOT\n' "${0##*/}" >&2
    exit 64
fi

[[ $(uname -s) == Linux && $(uname -m) == aarch64 ]] || \
    fail 'run the ARDY Motion Lab on the Linux ARM64 DGX Spark'
(( ${EUID:-$(id -u)} != 0 )) || fail 'run as the normal workspace user'

for command_name in docker readlink; do
    command -v "$command_name" >/dev/null 2>&1 || \
        fail "missing command: $command_name"
done

[[ -d $1 && ! -L $1 ]] || fail 'MODELS_ROOT must be a real directory'
[[ -d $2 && ! -L $2 ]] || fail 'ENCODER_CACHE_ROOT must be a real directory'
models_root=$(readlink -f "$1")
encoder_cache_root=$(readlink -f "$2")
[[ -f $models_root/ARDY-Core-RP-20FPS-Horizon8/config.yaml ]] || \
    fail 'MODELS_ROOT is missing Horizon8'
[[ -f $models_root/ARDY-Core-RP-20FPS-Horizon40/config.yaml ]] || \
    fail 'MODELS_ROOT is missing Horizon40'
[[ -d $encoder_cache_root/hub && ! -L $encoder_cache_root/hub ]] || \
    fail 'ENCODER_CACHE_ROOT is missing the pinned Hub cache'

docker image inspect ue5-spark-ardy-demo:0.1.0 >/dev/null 2>&1 || \
    fail 'build ue5-spark-ardy-demo:0.1.0 first'
if docker container inspect ue5-spark-ardy-demo >/dev/null 2>&1; then
    fail 'the fixed ARDY Motion Lab container already exists'
fi

exec docker run --rm \
    --name ue5-spark-ardy-demo \
    --gpus all \
    --publish 127.0.0.1:2333:2333 \
    --read-only \
    --cap-drop ALL \
    --security-opt no-new-privileges:true \
    --pids-limit 1024 \
    --memory 36g \
    --memory-swap 36g \
    --shm-size 4g \
    --tmpfs "/tmp:rw,noexec,nosuid,size=2g,uid=$(id -u),gid=$(id -g),mode=0700" \
    --tmpfs "/opt/ardy/.cache:rw,noexec,nosuid,size=1g,uid=$(id -u),gid=$(id -g),mode=0700" \
    --tmpfs "/opt/ardy/datasets/bones-seed/cache:rw,noexec,nosuid,size=256m,uid=$(id -u),gid=$(id -g),mode=0700" \
    --tmpfs "/opt/ardy/outputs:rw,noexec,nosuid,size=1g,uid=$(id -u),gid=$(id -g),mode=0700" \
    --user "$(id -u):$(id -g)" \
    --env CHECKPOINTS_DIR=/models \
    --env HF_HOME=/hf-cache \
    --env HUGGINGFACE_CACHE_DIR=/hf-cache/hub \
    --env HF_HUB_OFFLINE=1 \
    --env TRANSFORMERS_OFFLINE=1 \
    --env HF_DATASETS_OFFLINE=1 \
    --env HF_HUB_DISABLE_TELEMETRY=1 \
    --env TEXT_ENCODER_DEVICE=cuda:0 \
    --env HOME=/tmp \
    --mount "type=bind,src=$models_root,dst=/models,readonly" \
    --mount "type=bind,src=$encoder_cache_root,dst=/hf-cache,readonly" \
    ue5-spark-ardy-demo:0.1.0 \
    --no-compile
