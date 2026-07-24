#!/usr/bin/env bash
set -euo pipefail

fail() {
    printf 'error: %s\n' "$*" >&2
    if [[ -n ${DISPLAY:-} ]] && command -v zenity >/dev/null 2>&1; then
        zenity --error --title='ARDY Blender' --text="$*" >/dev/null 2>&1 || true
    fi
    exit 1
}

[[ $(uname -s) == Linux && $(uname -m) == aarch64 ]] || \
    fail 'run ARDY Blender on the Linux ARM64 DGX Spark'
(( ${EUID:-$(id -u)} != 0 )) || fail 'run as the normal desktop user'

for command_name in chmod docker hostname install pgrep readlink stat systemctl tee touch tr; do
    command -v "$command_name" >/dev/null 2>&1 || fail "missing command: $command_name"
done

project_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cooker_root=$(readlink -f "$project_root/..")
private_root="$cooker_root/models-private/ardy-blender"
casual_fbx_root="$cooker_root/private-export-proofs/casual-girl-20260723/output/fbx"
casual_runtime_root="$cooker_root/models-private/ardy-viser-lab/casual-girl"
nvidia_skin="$cooker_root/vendor-private/ardy/ardy/assets/skeletons/cskel27/skin_standard.npz"
nvidia_skin_root=${nvidia_skin%/*}
image_name=ue5-spark-blender:5.0.1
container_name=ue5-spark-blender
ardy_service=ue5-spark-ardy.service
viser_service=ue5-spark-ardy-viser-lab.service

[[ -d $casual_fbx_root && ! -L $casual_fbx_root ]] || \
    fail "Casual Girl FBX source is missing: $casual_fbx_root"
[[ -f $casual_runtime_root/manifest.json && ! -L $casual_runtime_root ]] || \
    fail "Casual Girl ARDY runtime source is missing: $casual_runtime_root"
[[ -f $nvidia_skin && ! -L $nvidia_skin ]] || \
    fail "NVIDIA Core27 source is missing: $nvidia_skin"
docker image inspect "$image_name" >/dev/null 2>&1 || \
    fail "Blender image is missing; run scripts/install-ardy-blender.sh first"
image_identity=$(docker image inspect \
    --format '{{.Architecture}} {{index .Config.Labels "io.ue5-spark.blender.version"}}' \
    "$image_name")
[[ $image_identity == 'arm64 5.0.1' ]] || \
    fail "refusing unexpected Blender image identity: $image_identity"
if docker container inspect "$container_name" >/dev/null 2>&1; then
    if [[ $(docker container inspect --format '{{.State.Running}}' "$container_name") == true ]]; then
        fail 'ARDY Blender is already open'
    fi
    docker container rm "$container_name" >/dev/null
fi

# Blender and the NVIDIA Viser lab are alternative interactive front ends for
# the same large ARDY model. Avoid keeping both GPU copies resident, then start
# the project-owned open-text pose endpoint that the Blender add-on consumes.
systemctl --user stop "$viser_service" >/dev/null 2>&1 || true
systemctl --user reset-failed "$viser_service" >/dev/null 2>&1 || true
systemctl --user start "$ardy_service" || \
    fail 'the open-text ARDY service could not be started'

install -d -m 0700 \
    "$private_root" \
    "$private_root/cache" \
    "$private_root/config" \
    "$private_root/exports" \
    "$private_root/home" \
    "$private_root/projects"

display_value=${DISPLAY:-}
xauthority_path=${XAUTHORITY:-}
if [[ -z $display_value || -z $xauthority_path ]]; then
    gnome_pid=$(pgrep -u "$(id -u)" -n gnome-shell || true)
    [[ -n $gnome_pid ]] || fail 'no active GNOME desktop session was found'
    while IFS='=' read -r key value; do
        case "$key" in
            DISPLAY) [[ -n $display_value ]] || display_value=$value ;;
            XAUTHORITY) [[ -n $xauthority_path ]] || xauthority_path=$value ;;
        esac
    done < <(tr '\0' '\n' < "/proc/$gnome_pid/environ")
fi
[[ -n $display_value ]] || fail 'the desktop DISPLAY is unavailable'
[[ -f $xauthority_path ]] || fail "the desktop Xauthority file is unavailable: $xauthority_path"
[[ $display_value =~ ^:([0-9]+)(\.[0-9]+)?$ ]] || \
    fail "only a local X11 display is accepted: $display_value"
display_number=${BASH_REMATCH[1]}
[[ -S /tmp/.X11-unix/X$display_number ]] || \
    fail "the X11 socket for $display_value is unavailable"

device_group_args=()
device_group_ids=()
for device_path in /dev/dri/renderD* /dev/dri/card*; do
    [[ -e $device_path ]] || continue
    device_gid=$(stat -c '%g' "$device_path")
    if [[ " ${device_group_ids[*]-} " != *" $device_gid "* ]]; then
        device_group_ids+=("$device_gid")
        device_group_args+=(--group-add "$device_gid")
    fi
done

project_file="$private_root/projects/ARDY-Rigging.blend"
launcher_log="$private_root/launcher.log"
touch "$launcher_log"
chmod 0600 "$launcher_log"
startup_script=/project/apps/ardy-blender/startup.py
blender_args=(--python "$startup_script")
if [[ -f $project_file ]]; then
    blender_args=("/work/projects/${project_file##*/}" "${blender_args[@]}")
else
    blender_args=(--factory-startup "${blender_args[@]}")
fi

set +e
docker run --rm \
    --name "$container_name" \
    --hostname "$(hostname)" \
    --gpus all \
    --network host \
    --read-only \
    --cap-drop ALL \
    --security-opt no-new-privileges:true \
    --pids-limit 4096 \
    --memory 24g \
    --memory-swap 24g \
    --shm-size 2g \
    --tmpfs "/tmp:rw,nosuid,size=2g,uid=$(id -u),gid=$(id -g),mode=0700" \
    --user "$(id -u):$(id -g)" \
    "${device_group_args[@]}" \
    --env "DISPLAY=$display_value" \
    --env XAUTHORITY=/tmp/.Xauthority \
    --env HOME=/work/home \
    --env XDG_CONFIG_HOME=/work/config \
    --env XDG_CACHE_HOME=/work/cache \
    --env NVIDIA_DRIVER_CAPABILITIES=compute,utility,graphics,display \
    --env ARDY_NVIDIA_SKIN=/inputs/nvidia/skin_standard.npz \
    --env ARDY_CASUAL_GIRL_ROOT=/inputs/casual-runtime \
    --env ARDY_CASUAL_GIRL_MANIFEST_ROOT=/inputs/casual-runtime \
    --env ARDY_CASUAL_GIRL_FBX_ROOT=/inputs/casual-fbx \
    --env ARDY_BLENDER_PROJECT=/work/projects/ARDY-Rigging.blend \
    --env ARDY_BLENDER_EXPORT_ROOT=/work/exports \
    --env ARDY_SERVICE_URL=http://127.0.0.1:8777 \
    --mount "type=bind,src=/tmp/.X11-unix,dst=/tmp/.X11-unix,readonly" \
    --mount "type=bind,src=$xauthority_path,dst=/tmp/.Xauthority,readonly" \
    --mount "type=bind,src=$project_root,dst=/project,readonly" \
    --mount "type=bind,src=$casual_fbx_root,dst=/inputs/casual-fbx,readonly" \
    --mount "type=bind,src=$casual_runtime_root,dst=/inputs/casual-runtime,readonly" \
    --mount "type=bind,src=$nvidia_skin_root,dst=/inputs/nvidia,readonly" \
    --mount "type=bind,src=$private_root,dst=/work" \
    "$image_name" \
    "${blender_args[@]}" \
    2>&1 | tee -a "$launcher_log"
docker_status=${PIPESTATUS[0]}
set -e
(( docker_status == 0 )) || \
    fail "Blender failed to start or exited unexpectedly. See $launcher_log"
