# ARDY Blender Adapter

This is a thin adapter for **real Blender**, not another home-grown rig editor.
The supported workflow is Blender 4.0.2 or newer (the Spark image is pinned to
Blender 5.0.1). Once a character is loaded, use Blender's normal Outliner,
Edit Mode, Pose Mode, Weight Paint, Material Properties, UV Editor, modifiers,
shape keys, and animation tools.

## What it loads

- **NVIDIA Original:** NVIDIA ARDY's actual `cskel27/skin_standard.npz`,
  including its exact Core27 hierarchy, skin, and weights.
- **Casual Girl, preferred:** the original modular FBX directory selected by
  `ARDY_CASUAL_GIRL_FBX_ROOT`. Blender's built-in FBX importer preserves the
  source meshes, UVs, material slots, texture references, and vertex groups it
  supports. The original UE body FBX remains the canonical armature; modular
  meshes are rebound to it and duplicate imported armatures are removed.
- **Casual Girl, fallback:** the reviewed private `manifest.json` plus NPZ
  parts already used by the ARDY Viser lab. This carries geometry, Core27
  weights, bind pose, category, and simple reviewed colors; NPZ has no UV,
  texture, or morph arrays to recover.

Set `ARDY_CASUAL_GIRL_BODY_FBX` when automatic body-file selection picks the
wrong FBX. Original identifiers and categories are retained as
`ardy_identifier`, `ardy_category`, `ardy_source_kind`, and
`ardy_source_name` custom properties on Blender collections and objects.

Body morph caveat: Blender 5's built-in FBX importer must be checked against the
actual seller export before relying on imported morph/shape-key preservation.
The adapter does not claim to reconstruct morphs omitted by the FBX, and
rebinding a modular mesh cannot make incompatible morph bases compatible.

## Use in Blender

Install `ardy_blender` as a normal add-on (or put this app directory on
`PYTHONPATH`) and enable **ARDY Character Adapter**. Open the **ARDY** tab in
the 3D View sidebar (`N`).

1. Choose `skin_standard.npz`, then click **Load NVIDIA Original**.
2. Choose the Casual Girl native FBX root. Optionally choose its canonical body
   FBX. Choose the NPZ manifest root only as a fallback.
3. Click **Load Casual Girl**.
4. Select a Core27 armature or its mesh and click **Validate Selected Core27**.
5. Rig with Blender's standard Edit/Pose/Weight Paint tools.
6. Select a mesh and armature, then **Export Selected for Unreal**. The adapter
   calls Blender's standard FBX exporter with Unreal-friendly axis/unit and
   no-leaf-bone settings.
7. To send an adjusted mesh back toward the ARDY pipeline, make that mesh
   active, choose a staging directory, and click **Stage Active Mesh as NPZ**.

NPZ export is create-only: it generates a timestamped file inside the selected
staging directory and will never overwrite a live/private input or an existing
staging artifact.

## Private scene builder

Build a private `.blend` without putting character assets in Git:

```bash
blender --background --factory-startup \
  --python apps/ardy-blender/build_private_blend.py -- \
  --nvidia-skin /private/ardy/cskel27/skin_standard.npz \
  --casual-fbx-root /private/casual-girl/fbx \
  --casual-manifest-root /private/casual-girl/npz \
  --output /staging/ardy-characters.blend
```

The FBX root wins when present. The NPZ root is the fallback. Existing `.blend`
outputs are refused unless `--replace-output` is explicitly supplied.

## DGX Spark container

The Dockerfile uses the pinned Ubuntu 26.04 ARM64-compatible distro packages:

- base digest:
  `sha256:3131b4cc82a783df6c9df078f86e01819a13594b865c2cad47bd1bca2b7063bb`
- `blender=5.0.1+dfsg-1ubuntu1`
- `blender-data=5.0.1+dfsg-1ubuntu1`

Build it with the logged-in user's numeric IDs:

```bash
docker build \
  --build-arg APP_UID="$(id -u)" \
  --build-arg APP_GID="$(id -g)" \
  -t ue5-spark-ardy-blender:5.0.1-arm64 \
  apps/ardy-blender
```

Set the four host roots and run the X11 launcher:

```bash
export ARDY_PRIVATE_ROOT=/path/to/private-assets
export ARDY_BLENDER_STAGING_ROOT=/path/to/staging
export ARDY_BLENDER_CONFIG_ROOT=/path/to/blender-config
export XAUTHORITY="${XAUTHORITY:-$HOME/.Xauthority}"
apps/ardy-blender/run-blender-x11-container.sh
```

The launcher drops every Linux capability, enables `no-new-privileges`, uses
the logged-in UID/GID, disables container networking, and mounts only:

- this repository, read-only;
- the explicitly selected private asset and staging roots, read/write;
- the Blender config root, read/write;
- X11 socket and Xauthority;
- NVIDIA GPU/display capabilities.

No source FBX or NPZ is modified by import.

## Test the pure format layer

```bash
python3 -m pytest apps/ardy-blender/tests
```
