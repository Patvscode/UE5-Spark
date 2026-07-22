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
