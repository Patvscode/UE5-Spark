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
for command_name in docker flock readlink stat; do
    command -v "$command_name" >/dev/null 2>&1 || fail "missing command: $command_name"
done

umask 077
auth_lock_parent="/run/user/$(id -u)"
[[ -d $auth_lock_parent && -O $auth_lock_parent && ! -L $auth_lock_parent && \
    $(stat -c '%a' "$auth_lock_parent") == 700 ]] || \
    fail 'the fixed per-user runtime directory is missing or unsafe'
auth_lock_parent=$(cd "$auth_lock_parent" && pwd -P)
[[ $auth_lock_parent == "/run/user/$(id -u)" ]] || \
    fail 'the fixed per-user runtime directory resolved unexpectedly'
auth_lock_file="$auth_lock_parent/ue5-spark-hf-authorization-cleanup.lock"
[[ ! -L $auth_lock_file ]] || fail 'the Hugging Face authorization lock is a symlink'
if [[ -e $auth_lock_file ]]; then
    [[ -f $auth_lock_file && -O $auth_lock_file && \
        $(stat -c '%a' "$auth_lock_file") == 600 && \
        $(stat -c '%h' "$auth_lock_file") == 1 ]] || \
        fail 'the Hugging Face authorization lock is unsafe'
fi
exec 8>>"$auth_lock_file"
[[ $(readlink -f /proc/self/fd/8) == "$auth_lock_file" && \
    -f $auth_lock_file && -O $auth_lock_file && ! -L $auth_lock_file && \
    $(stat -c '%a' "$auth_lock_file") == 600 && \
    $(stat -c '%h' "$auth_lock_file") == 1 ]] || \
    fail 'the Hugging Face authorization lock changed while opening it'
flock -n 8 || fail 'Hugging Face authorization cleanup is already running'

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
if [[ -L $encoder_cache || ( -e $encoder_cache && ! -d $encoder_cache ) ]]; then
    fail 'encoder cache must be a real directory'
fi
if [[ ! -e $encoder_cache ]]; then
    mkdir -- "$encoder_cache"
fi
[[ -d $encoder_cache && ! -L $encoder_cache ]] || \
    fail 'encoder cache must be a real directory'
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
