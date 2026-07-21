#!/usr/bin/env bash
set -euo pipefail

fail() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

if (( $# != 3 )); then
    printf 'Usage: %s MODEL /private/checkpoints-root /private/hf-token-file\n' "${0##*/}" >&2
    exit 64
fi
model=$1
case $model in
    ARDY-Core-RP-20FPS-Horizon40|ARDY-Core-RP-20FPS-Horizon8) ;;
    *) fail 'model is not in the approved Core27 allowlist' ;;
esac
models_root=$(cd "$2" && pwd -P)
token_file=$(cd "$(dirname "$3")" && pwd -P)/$(basename "$3")
[[ -d $models_root && ! -L $models_root ]] || fail 'checkpoint root must be a real directory'
[[ -f $token_file && ! -L $token_file ]] || fail 'token must be a regular file'
[[ $(stat -c '%a' "$token_file") =~ ^(400|600)$ ]] || \
    fail 'token file must not grant group or other access'

docker image inspect ue5-spark-ardy:0.2.0 >/dev/null 2>&1 || \
    fail 'build ue5-spark-ardy:0.2.0 first'
docker run --rm \
    --network bridge \
    --read-only \
    --cap-drop ALL \
    --security-opt no-new-privileges:true \
    --tmpfs /tmp:rw,noexec,nosuid,size=2g \
    --user "$(id -u):$(id -g)" \
    --mount "type=bind,src=$models_root,dst=/models" \
    --mount "type=bind,src=$token_file,dst=/run/secrets/hf_token,readonly" \
    --entrypoint python \
    ue5-spark-ardy:0.2.0 \
    /opt/ue5-spark-ardy/download_checkpoint.py --model "$model"
