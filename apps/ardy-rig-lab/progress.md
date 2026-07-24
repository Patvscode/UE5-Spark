Original prompt: Prototype subtask, local repo only, no remote deployment yet: inspect apps/private-controller and create a separate minimal ARDY Rig Lab frontend/server only if it can be isolated cleanly. It must be real WebGL 3D (Three.js or official Viser integration), not video; orbit/pan/zoom, floor + simple chair/bed boxes, skeleton joint markers, prompt/once/loop, rig mapping adjustment controls, and mesh/component visibility. Prefer reusing official ARDY demo if code already provides this. Do not modify existing companion controller behavior. Use apply_patch and report files/tests. Avoid fake motion; wire to /v2/poses or document exact blocker.

## 2026-07-22

- Inspected the pinned official `nv-tlabs/ardy` revision
  `693f74d13b3d04a0a22ce127ee79c929dd89756b`.
- The official interactive demo uses Viser and runs ARDY in-process. Its smaller
  `scripts/visualize.py` viewer consumes generated `.npz` files rather than the
  existing UE5-Spark `/v2/poses` service. Reusing either directly would create
  a second model runtime or a file-export detour.
- Decision: build an isolated Three.js diagnostic viewer that consumes the
  repository's strict protocol-v2 Core27 batches directly. Keep the official
  Core27 joint order, coordinate basis, 20 FPS cadence, and orbit/pan/zoom
  interaction conventions.
- Current live blocker: repository documentation says the qualified Spark
  service is still protocol v1; this lab will fail closed and hold the labeled
  neutral reference pose until the source-only v2 candidate is activated.

## TODO

- Implemented the standalone Three.js app and same-origin loopback proxy.
- Added strict protocol validation, real-batch once/loop buffering, orbit/pan/
  zoom, fullscreen, proxy body/skeleton/joint visibility, chair and bed scale
  references, global mapping calibration, and per-joint translation trims.
- Added eight passing Node tests covering protocol failure, mapping, real-frame
  playback, no-synthesis failure behavior, proxy confinement, and UI contracts.
- `npm run build` passes with Vite 8.1.5 and Three.js 0.185.1. The single
  Three.js bundle is 569.26 kB before gzip (144.04 kB gzip); acceptable for this
  isolated prototype, but code splitting remains an optional polish item.
- Run the required Playwright interaction/screenshot loop and inspect output.
- Do not deploy or alter the companion controller.

## 2026-07-23 — reusable character setup

User request: make the lab able to add and rig models as a complete reusable
setup.

- The Spark ARDY service is now live on protocol v2 at loopback port 8777, so
  the earlier protocol-v1 blocker no longer applies.
- Implement skinned GLB/GLTF/VRM and FBX import, skeleton inventory, Core27
  automatic/manual bone mapping, bind-pose calibration, reusable profiles,
  private model persistence, and live pose retargeting.
- Unrigged static meshes must be identified honestly; this milestone will not
  fabricate skin weights or call a hidden auto-rigger.
- Deploy the Rig Lab separately from the official NVIDIA demo and the companion
  controller, then verify it through its own private Tailscale route.

### Implemented

- Added GLB, GLTF-with-sidecars, VRM and FBX browser import with explicit
  unrigged-model diagnostics.
- Added private single-file GLB/VRM/FBX persistence and model removal.
- Added multi-skeleton inspection and body-skeleton selection.
- Added stable-path Core27 auto-mapping, 27 manual mapping rows, duplicate-target
  prevention, mapping coverage, and missing required-chain reporting.
- Added character scale/orientation/placement calibration and per-joint local
  rotation corrections.
- Added reusable private profiles plus JSON import/export.
- Added complete pose-frame interpolation, including shortest-path XYZW
  quaternion interpolation.
- Added bind-pose-restoring character retargeting, skeleton helper, bone
  selection, mesh visibility, auto-fit, and first-frame-anchored opt-in root
  motion.
- Added a standalone hardened user service and private Tailscale route:
  `https://spark-ccb2-1.tail2b1107.ts.net:8476/`.
- Loaded the private `Core27Source.glb` diagnostic skin and confirmed 27/27
  automatic mappings.
- Completed one real two-second ARDY prompt: 40/40 frames played, no missing
  frames, and no browser console errors.
- Confirmed the responsive 390 × 844 layout and the full desktop workflow.

### Current asset boundary

- The portable Core27 debug skin works end-to-end.
- Casual Girl, Ada and Aoi remain Unreal-only `.uasset` content. The next asset
  step is a private skinned GLB export through the existing Unreal/FEX toolchain;
  the lab itself is ready to import and profile those exports.
