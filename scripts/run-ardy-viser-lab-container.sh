#!/usr/bin/env bash
set -euo pipefail

fail() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

if (( $# != 3 )); then
    printf 'Usage: %s MODELS_ROOT ENCODER_CACHE_ROOT CASUAL_GIRL_ROOT\n' "${0##*/}" >&2
    exit 64
fi

[[ $(uname -s) == Linux && $(uname -m) == aarch64 ]] || \
    fail 'run the ARDY Viser Character Lab on the Linux ARM64 DGX Spark'
(( ${EUID:-$(id -u)} != 0 )) || fail 'run as the normal workspace user'

for command_name in docker readlink; do
    command -v "$command_name" >/dev/null 2>&1 || fail "missing command: $command_name"
done

for input_dir in "$1" "$2" "$3"; do
    [[ -d $input_dir && ! -L $input_dir ]] || fail "required directory is missing or symlinked: $input_dir"
done

models_root=$(readlink -f "$1")
encoder_cache_root=$(readlink -f "$2")
casual_girl_root=$(readlink -f "$3")
project_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
overlay_root="$project_root/apps/ardy-viser-lab"
mobile_root="$overlay_root/mobile"
viser_build_root=/usr/local/lib/python3.12/dist-packages/viser/client/build

[[ -f $models_root/ARDY-Core-RP-20FPS-Horizon8/config.yaml ]] || fail 'MODELS_ROOT is missing Horizon8'
[[ -f $models_root/ARDY-Core-RP-20FPS-Horizon40/config.yaml ]] || fail 'MODELS_ROOT is missing Horizon40'
[[ -d $encoder_cache_root/hub && ! -L $encoder_cache_root/hub ]] || fail 'ENCODER_CACHE_ROOT is missing the pinned Hub cache'
[[ -f $casual_girl_root/manifest.json ]] || fail 'CASUAL_GIRL_ROOT is missing manifest.json'
[[ -f $overlay_root/project_demo.py ]] || fail 'project-owned Viser overlay is missing'
[[ -f $mobile_root/index.html ]] || fail 'mobile Viser index is missing'
[[ -f $mobile_root/ue5-spark-mobile.css ]] || fail 'mobile Viser stylesheet is missing'
[[ -f $mobile_root/ue5-spark-mobile.js ]] || fail 'mobile Viser controller is missing'

docker image inspect ue5-spark-ardy-demo:0.1.0 >/dev/null 2>&1 || \
    fail 'build ue5-spark-ardy-demo:0.1.0 first'
if docker container inspect ue5-spark-ardy-viser-lab >/dev/null 2>&1; then
    fail 'the fixed ARDY Viser Character Lab container already exists'
fi

exec docker run --rm \
    --name ue5-spark-ardy-viser-lab \
    --gpus all \
    --publish 127.0.0.1:2334:2333 \
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
    --env CASUAL_GIRL_ROOT=/characters/casual-girl \
    --env PYTHONPATH=/project:/opt/ardy/scripts:/opt/ardy \
    --mount "type=bind,src=$models_root,dst=/models,readonly" \
    --mount "type=bind,src=$encoder_cache_root,dst=/hf-cache,readonly" \
    --mount "type=bind,src=$casual_girl_root,dst=/characters/casual-girl,readonly" \
    --mount "type=bind,src=$overlay_root,dst=/project,readonly" \
    --mount "type=bind,src=$mobile_root/index.html,dst=$viser_build_root/index.html,readonly" \
    --mount "type=bind,src=$mobile_root/ue5-spark-mobile.css,dst=$viser_build_root/ue5-spark-mobile.css,readonly" \
    --mount "type=bind,src=$mobile_root/ue5-spark-mobile.js,dst=$viser_build_root/ue5-spark-mobile.js,readonly" \
    --entrypoint python \
    ue5-spark-ardy-demo:0.1.0 \
    /project/project_demo.py --no-compile
