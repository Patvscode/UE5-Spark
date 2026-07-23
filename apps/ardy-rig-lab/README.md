# ARDY Rig Lab

An isolated, local-only Core27 diagnostic viewport for UE5-Spark. It does not
import, modify, or replace `apps/private-controller`.

The viewport is real Three.js WebGL—not a video replay. It renders the exact
27-joint ARDY source skeleton, diagnostic proxy geometry, joint markers, a
floor, and simple chair/bed scale references. It supports orbit, pan, zoom,
fullscreen, component visibility, global rig calibration, and per-joint
translation trims.

## Why this is separate from the official demo

The pinned official ARDY repository includes:

- `scripts/run_demo.py`, a Viser UI that loads and runs the ARDY model
  in-process; and
- `scripts/visualize.py`, a Viser viewer for exported `.npz` files.

Neither consumes the existing UE5-Spark pose service. Running the official
interactive demo beside the project service would load a second model stack,
while exporting `.npz` files would prevent live rig debugging. This lab instead
keeps the official Core27 order, basis, 20 FPS cadence, and camera controls
while consuming the project's strict service contract directly.

## Run locally

```bash
cd apps/ardy-rig-lab
npm install
npm run dev
```

Open `http://127.0.0.1:8488`. Vite proxies the following same-origin routes to
the loopback service at `http://127.0.0.1:8777`:

- `GET /api/ardy-health` → `GET /healthz`
- `POST /v2/poses` → `POST /v2/poses`

For the standalone built server:

```bash
npm run build
npm start
```

The server remains loopback-only. `ARDY_RIG_LAB_UPSTREAM` may select a
different loopback HTTP port; it cannot target another host.

## Motion truth boundary

The neutral standing source rig is a static, labeled Core27 calibration pose
from the repository's protocol mock positions. It is not presented as
generated motion.

Once or Loop sends the user prompt and controls to the real `POST /v2/poses`
endpoint. Only validated protocol-v2 batches animate the viewport. On an
invalid response, unavailable service, or underrun, the lab holds the last
verified frame; it never manufactures fallback motion.

When health reports `dynamicTextReady: false`, free-text prompting is blocked
instead of pretending the mock provider followed the text. The base behavior
can still be requested after clearing the prompt.

## Current blocker

The repository handoff currently says the qualified Spark runtime is still the
protocol-v1 ARDY service, while protocol v2 is a source-only candidate. The Rig
Lab therefore cannot show live Spark motion until the v2 candidate is safely
activated at loopback port `8777`. A v1 health response or missing v2 route is
shown as unavailable, and the viewport remains on the labeled reference pose.

## Tests

```bash
npm test
npm run build
```
