#!/usr/bin/env bash
set -euo pipefail

# A template for a normal, interactive X11 Blender window on the DGX Spark.
# Required mounts are deliberately narrow; no host root or Docker socket enters
# the container.

image="${ARDY_BLENDER_IMAGE:-ue5-spark-ardy-blender:5.0.1-arm64}"
repo_root="${ARDY_PROJECT_ROOT:-$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)}"
private_root="${ARDY_PRIVATE_ROOT:?set ARDY_PRIVATE_ROOT to the private character asset directory}"
staging_root="${ARDY_BLENDER_STAGING_ROOT:?set ARDY_BLENDER_STAGING_ROOT to an existing staging directory}"
config_root="${ARDY_BLENDER_CONFIG_ROOT:?set ARDY_BLENDER_CONFIG_ROOT to an existing Blender config directory}"
xauthority_source="${XAUTHORITY:-}"

if [[ -z "${DISPLAY:-}" ]]; then
  echo "DISPLAY is not set; launch this from the logged-in X11 desktop session" >&2
  exit 2
fi
if [[ -z "$xauthority_source" || ! -f "$xauthority_source" ]]; then
  echo "XAUTHORITY must name the logged-in user's existing Xauthority file" >&2
  exit 2
fi
for path in "$repo_root" "$private_root" "$staging_root" "$config_root"; do
  if [[ ! -d "$path" || -L "$path" ]]; then
    echo "required mount must be an existing real directory: $path" >&2
    exit 2
  fi
done
if [[ ! -d /tmp/.X11-unix ]]; then
  echo "/tmp/.X11-unix is unavailable" >&2
  exit 2
fi

docker run --rm --init \
  --name ue5-spark-ardy-blender \
  --user "$(id -u):$(id -g)" \
  --network none \
  --cap-drop ALL \
  --security-opt no-new-privileges:true \
  --gpus all \
  --env "DISPLAY=$DISPLAY" \
  --env XAUTHORITY=/run/ardy-xauth/Xauthority \
  --env NVIDIA_VISIBLE_DEVICES=all \
  --env NVIDIA_DRIVER_CAPABILITIES=graphics,display,utility,compute \
  --env PYTHONPATH=/opt/ue5-spark \
  --env ARDY_NVIDIA_SKIN="${ARDY_NVIDIA_SKIN_CONTAINER:-/private/ardy/cskel27/skin_standard.npz}" \
  --env ARDY_CASUAL_GIRL_FBX_ROOT="${ARDY_CASUAL_GIRL_FBX_ROOT_CONTAINER:-/private/casual-girl/fbx}" \
  --env ARDY_CASUAL_GIRL_MANIFEST_ROOT="${ARDY_CASUAL_GIRL_MANIFEST_ROOT_CONTAINER:-/private/casual-girl/npz}" \
  --env ARDY_BLENDER_STAGING_ROOT=/staging \
  --mount "type=bind,src=$repo_root,dst=/workspace,readonly" \
  --mount "type=bind,src=$private_root,dst=/private" \
  --mount "type=bind,src=$staging_root,dst=/staging" \
  --mount "type=bind,src=$config_root,dst=/var/lib/ardy-blender/.config/blender" \
  --mount "type=bind,src=/tmp/.X11-unix,dst=/tmp/.X11-unix" \
  --mount "type=bind,src=$xauthority_source,dst=/run/ardy-xauth/Xauthority,readonly" \
  "$image" \
  --python-expr \
  "import bpy; bpy.ops.preferences.addon_enable(module='ardy_blender')"
