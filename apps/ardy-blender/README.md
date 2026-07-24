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
5. Click **Clear ARDY View**, then rig with Blender's standard
   Edit/Pose/Weight Paint tools.
6. Enter any movement description under **Live ARDY rig test**, select the
   edited mesh or armature, and click **Generate & Play on Selected Rig**.
7. Select a mesh and armature, then **Export Selected for Unreal**. The adapter
   calls Blender's standard FBX exporter with Unreal-friendly axis/unit and
   no-leaf-bone settings.
8. To send an adjusted mesh back toward the ARDY pipeline, make that mesh
   active, choose a staging directory, and click **Stage Active Mesh as NPZ**.

NPZ export is create-only: it generates a timestamped file inside the selected
staging directory and will never overwrite a live/private input or an existing
staging artifact.

## Position the rig correctly

The large white wedges in Blender's default octahedral display are not body
geometry and do not prove that the imported joints are misplaced. Casual
Girl's native UE skeleton includes long IK helpers, twist bones, and FBX display
tails. Use **Clear ARDY View** before judging placement.

- Make rest-pose corrections in **Edit Mode**. Pose Mode is only for testing.
- A bone's **head** is its anatomical pivot. Place the pelvis between the hip
  sockets; thighs at the hip sockets; calves at the knee pivots; feet at the
  ankles; upper arms at the shoulder pivots; lower arms at the elbows; hands
  at the wrists; and spine/neck bones on the body's center line.
- A bone's **tail** defines its local axis and roll. It does not need to land on
  the next joint in this imported UE rig. Do not use “Connect” or snap all tails
  to children: that breaks twist, IK, and helper bones.
- Keep the armature object's imported location, rotation, and scale unchanged.
  Work on rest bones, not the whole object. Blender is +Z up, −Y
  character-forward, and +X character-left; scene units are metres.
- Check both front and side orthographic views. `_l` and `_r` mean the
  character's left and right, not the viewer's. Enable X-axis mirror only after
  confirming that the pair names and center line are correct.
- Adjust the main deform chain first. ARDY drives pelvis, spine, clavicles,
  upper/lower arms, hands, thighs, calves, feet, and toe bases. Fingers, twist
  bones, breasts, IK helpers, and facial bones keep their authored pose during
  this quick body-motion test.

After each rest edit, return to Object or Pose Mode, keep the character mesh or
armature selected, enter a prompt such as `squat twice and stand naturally`,
and generate again. Each run creates a separate `ARDY Preview · ...` Action;
**Restore / Reset Pose** returns to the Action that was active before the
preview, or clears the generated Pose Mode transforms when there was no prior
Action.

## Live ARDY preview

The desktop launcher starts the real open-text ARDY Horizon8 service on
`127.0.0.1:8777` and gives only the Blender container access to that loopback
endpoint. The complete 1–512 character prompt is sent to NVIDIA ARDY; it is not
reduced to a movement catalog entry. Blender receives protocol-v2 Core27 frames
at 20 FPS, builds a temporary Action, retargets the main body chains, and starts
timeline playback.

The first prompt after startup can take longer while the text encoder and model
warm up. Later repeats of the same prompt reuse the bounded in-memory embedding
cache. **Keep character in place** is enabled by default so rig defects are
easier to see; disable it when evaluating ARDY root translation.

The separate NVIDIA Viser Character Lab and Blender are alternative interactive
front ends for the same large model. Opening ARDY Blender stops the Viser lab
service first, preventing two model copies from consuming the Spark's unified
memory. Its desktop icon can start the Viser lab again later.

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
the logged-in UID/GID, and uses host networking solely so the add-on can reach
the fixed loopback ARDY endpoint. It mounts only:

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
