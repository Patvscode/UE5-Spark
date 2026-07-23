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
