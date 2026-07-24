# ARDY Rig Lab

ARDY Rig Lab is the private 3D model-import and retargeting workspace for
UE5-Spark. It runs beside the companion application and the official NVIDIA
ARDY demo; it does not replace either one.

Spark link:

<https://spark-ccb2-1.tail2b1107.ts.net:8476/>

The viewport is real Three.js WebGL, not a video. It supports orbit, pan, zoom,
fullscreen, a floor, chair and bed scale references, the exact ARDY Core27
source overlay, imported skinned characters, and live 20 FPS pose playback.

## Add and rig a character

1. Open **Character model**.
2. Choose a model file.
   - GLB is the recommended portable format.
   - VRM and FBX are supported.
   - A GLTF plus its `.bin` and texture sidecars can be opened for the current
     browser session, but is not stored in the private library. Export a GLB
     when persistence is required.
3. Select **Add model to this Spark**.
4. Review the detected meshes, skeletons and bones.
5. Select the body skeleton if the file contains more than one.
6. Start with **Auto-map bones**, then correct any Core27 row manually.
7. Use **Character calibration** to adjust model height, orientation, position,
   and per-joint local rotation corrections.
8. Leave root motion off for in-place testing. Enable it only when the
   character should travel through the room.
9. Open **Rig profile**, name the setup, and save it.
10. Enter a movement prompt and choose **Run once** or **Loop**.

Mappings use stable bone paths scoped to one selected skeleton. One target bone
cannot drive two Core27 joints. Every pose frame starts from the imported bind
pose, so corrections do not accumulate or drift. Root travel is opt-in and is
anchored to the first accepted frame instead of applying an absolute hip
position.

## What counts as a rigged model

A movable character must contain:

- at least one `SkinnedMesh`;
- a bound skeleton;
- joints and skin weights; and
- a usable body-bone mapping.

Static meshes can be inspected, positioned and scaled, but the lab does not
invent skin weights or claim that a static model is rigged. Unreal `.uasset`
files also cannot be opened directly in a browser. Casual Girl, Ada and Aoi
currently need a one-time skinned GLB export from Unreal before they can use
this lab.

## Private storage

The standalone server stores model files and profiles under
`RIG_LAB_DATA_ROOT`. A typical private location is:

```text
<private-data-root>/rig-lab
```

The directory and stored files are private and excluded from Git. Profile JSON
can be exported manually for backup or imported into the currently loaded
matching model. Import rejects a different model ID or skeleton.

Server routes:

- `GET /api/models`
- `POST /api/models`
- `GET /api/models/:id/file`
- `GET|PUT /api/models/:id/profile`
- `DELETE /api/models/:id`
- `GET /api/ardy-health`
- `POST /v2/poses`

The server binds to loopback only. The public-facing Spark link is a private
Tailscale Serve route.

## Motion truth boundary

The neutral Core27 overlay is a labeled reference pose. Once or Loop sends the
prompt and controls to the real project-owned ARDY protocol-v2 service. Only
validated batches animate the character. A malformed response, unavailable
service, or underrun holds the last verified pose; the browser does not
manufacture fallback motion.

The character driver consumes the complete ARDY frame:

- root position and XYZW quaternion;
- all 27 local XYZW joint rotations;
- global Core27 positions; and
- foot-contact confidences.

## Run locally

```bash
cd apps/ardy-rig-lab
npm install
npm run build
npm start
```

Environment variables:

```text
RIG_LAB_HOST=127.0.0.1
RIG_LAB_PORT=8488
ARDY_RIG_LAB_UPSTREAM=http://127.0.0.1:8777
RIG_LAB_DATA_ROOT=/private/path/rig-lab
```

The reproducible user-service template is
`deploy/systemd/user/ue5-spark-rig-lab.service.in`.

## Validate

```bash
npm test
npm run build
```

The browser also exposes:

- `window.render_game_to_text()` for a bounded model/mapping/motion status; and
- `window.advanceTime(milliseconds)` for deterministic browser testing.
