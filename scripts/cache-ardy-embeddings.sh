#!/usr/bin/env bash
set -euo pipefail

fail() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

if (( $# < 2 || $# > 4 )); then
    printf 'Usage: %s /private/checkpoints-root /private/hf-token-file [cpu|cuda] [bfloat16|float32]\n' "${0##*/}" >&2
    exit 64
fi
[[ $(uname -s) == Linux && $(uname -m) == aarch64 ]] || \
    fail 'generate ARDY embeddings on the Linux ARM64 DGX Spark'
(( ${EUID:-$(id -u)} != 0 )) || fail 'run as the normal workspace user'
command -v docker >/dev/null 2>&1 || fail 'Docker is not available'

models_root=$(cd "$1" && pwd -P)
token_file=$(cd "$(dirname "$2")" && pwd -P)/$(basename "$2")
device=${3:-cpu}
precision=${4:-bfloat16}
case $device in
    cpu|cuda) ;;
    *) fail 'device must be cpu or cuda' ;;
esac
case $precision in
    bfloat16|float32) ;;
    *) fail 'precision must be bfloat16 or float32' ;;
esac
[[ -d $models_root && ! -L $models_root ]] || \
    fail 'checkpoint root must be a real directory'
[[ ! -e $models_root/embeddings && ! -L $models_root/embeddings ]] || \
    fail 'embedding cache already exists; refusing to overwrite it'
[[ -f $token_file && ! -L $token_file ]] || \
    fail 'token must be a regular file'
[[ $(stat -c '%a' "$token_file") =~ ^(400|600)$ ]] || \
    fail 'token file must not grant group or other access'
docker image inspect ue5-spark-ardy:0.2.0 >/dev/null 2>&1 || \
    fail 'build ue5-spark-ardy:0.2.0 first'

umask 077
models_parent=$(dirname "$models_root")
[[ -d $models_parent && ! -L $models_parent ]] || \
    fail 'checkpoint parent must be a real directory'
encoder_cache="$models_parent/.hf-text-encoder-cache"
mkdir -p "$encoder_cache"
chmod 700 "$encoder_cache"

gpu_args=()
if [[ $device == cuda ]]; then
    gpu_args=(--gpus all)
fi
precision_args=()
if [[ $precision == float32 ]]; then
    precision_args=(--fp32)
fi

exec docker run --rm \
    --network bridge \
    "${gpu_args[@]}" \
    --read-only \
    --cap-drop ALL \
    --security-opt no-new-privileges:true \
    --pids-limit 512 \
    --shm-size 4g \
    --tmpfs /tmp:rw,noexec,nosuid,size=2g \
    --user "$(id -u):$(id -g)" \
    --env HF_HOME=/hf-cache \
    --env HUGGINGFACE_CACHE_DIR=/hf-cache/hub \
    --env HF_TOKEN_PATH=/run/secrets/hf_token \
    --env TEXT_ENCODER_DEVICE="$device" \
    --mount "type=bind,src=$models_root,dst=/models" \
    --mount "type=bind,src=$encoder_cache,dst=/hf-cache" \
    --mount "type=bind,src=$token_file,dst=/run/secrets/hf_token,readonly" \
    --entrypoint python \
    ue5-spark-ardy:0.2.0 \
    /opt/ue5-spark-ardy/cache_embeddings.py \
    --models-root /models --device "$device" "${precision_args[@]}"
