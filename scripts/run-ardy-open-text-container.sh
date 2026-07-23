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
    fail 'run the open-text ARDY service on the Linux ARM64 DGX Spark'
(( ${EUID:-$(id -u)} != 0 )) || \
    fail 'run the service as the normal workspace user'
for command_name in docker readlink; do
    command -v "$command_name" >/dev/null 2>&1 || fail "missing command: $command_name"
done

[[ -d $1 && ! -L $1 ]] || \
    fail 'MODELS_ROOT must be a real directory'
[[ -d $2 && ! -L $2 ]] || \
    fail 'ENCODER_CACHE_ROOT must be a real directory'
models_root=$(cd "$1" && pwd -P)
encoder_cache_root=$(cd "$2" && pwd -P)
[[ -d $encoder_cache_root/hub && ! -L $encoder_cache_root/hub ]] || \
    fail 'ENCODER_CACHE_ROOT must contain a real hub directory'
[[ -f $models_root/ARDY-Core-RP-20FPS-Horizon8/config.yaml ]] || \
    fail 'MODELS_ROOT is missing the Horizon8 checkpoint'
[[ -f $models_root/embeddings/manifest.json ]] || \
    fail 'MODELS_ROOT is missing the sealed fallback embedding manifest'

models_root=$(readlink -f "$models_root")
encoder_cache_root=$(readlink -f "$encoder_cache_root")
[[ $models_root == /* && $encoder_cache_root == /* ]] || \
    fail 'private roots must resolve to absolute paths'
[[ $models_root != "$encoder_cache_root" ]] || \
    fail 'model and encoder cache roots must be separate directories'

docker image inspect ue5-spark-ardy:0.4.0-open-text >/dev/null 2>&1 || \
    fail 'build ue5-spark-ardy:0.4.0-open-text first'

# The equal memory and memory-swap limits disable container swap. This keeps a
# failed encoder load inside the project-owned container instead of allowing it
# to consume the Spark's already constrained host swap.
exec docker run --rm \
    --name ue5-spark-ardy \
    --gpus all \
    --network host \
    --read-only \
    --cap-drop ALL \
    --security-opt no-new-privileges:true \
    --pids-limit 512 \
    --memory 24g \
    --memory-swap 24g \
    --shm-size 4g \
    --tmpfs /tmp:rw,noexec,nosuid,size=2g \
    --user "$(id -u):$(id -g)" \
    --env HF_HOME=/hf-cache \
    --env HUGGINGFACE_CACHE_DIR=/hf-cache/hub \
    --env HF_HUB_OFFLINE=1 \
    --env TRANSFORMERS_OFFLINE=1 \
    --env HF_DATASETS_OFFLINE=1 \
    --env HF_HUB_DISABLE_TELEMETRY=1 \
    --env TEXT_ENCODER_DEVICE=cuda:0 \
    --mount "type=bind,src=$models_root,dst=/models,readonly" \
    --mount "type=bind,src=$encoder_cache_root,dst=/hf-cache,readonly" \
    ue5-spark-ardy:0.4.0-open-text \
    --host 127.0.0.1 --port 8777 --provider ardy --models-root /models
