# Isolated ARDY pose service

> **Deployment boundary:** this directory now describes the source-only
> `ue5-spark-ardy:0.3.0` / protocol-v2 candidate. The service currently running
> with the sealed v29 package on Spark is still the qualified `0.2.0` /
> protocol-v1 provider with three cached motions (`idle`, `listen`, `explain`).
> No v2 container, nine-motion cache, or v30 package has been deployed yet.

This directory builds a project-owned ARM64 container from NVIDIA's PyTorch
image and the official Apache-2.0
[nv-tlabs/ardy](https://github.com/nv-tlabs/ardy) source at a reviewed commit.
It does not install host packages or include TensorRT.

The service binds only to `127.0.0.1:8777` and exposes `GET /healthz`,
idempotent `POST /v2/prompts` prewarming, and `POST /v2/poses`. The incompatible
v1 URL returns 404 rather than serving a v2 envelope under a misleading path.
Pose requests retain the internal reviewed behavior used for routing and
fallback, and may additionally carry any user-authored prompt from 1 to 512
characters. Prompts receive no semantic allowlist or classifier. The real
provider uses NVIDIA's official persistent LLM2Vec encoder and holds the 32
most recently used prompt embeddings in a SHA-256-keyed LRU. Protocol v2
responses contain at most eight Core27 frames at 20 FPS. Each frame contains
local XYZW rotations, global posed-joint positions, root translation/rotation,
and contacts. Root and Hips rotations are replaced with identity to keep the
avatar upright; neck and head rotations are also replaced with identity so
StreamingADA retains ownership.
The root fields are a redundant stream anchor: root XYZ must equal global
`positions[0]` (Hips), and both root rotation and local `joints[0]` are identity
in the same quaternion hemisphere. Protocol validation rejects inconsistent
data.

The source coordinate contract is explicit: ARDY is right-handed with +X
pointing to the character's left, +Y up, +Z forward, and positions in metres.
Unreal is +X forward, +Y right, +Z up, in centimetres. Therefore source vectors
map as `(x, y, z) -> (z, -x, y) * 100`. That mapping changes handedness, so an
XYZW orientation maps as `(x, y, z, w) -> (-z, x, -y, w)`, followed by
normalization and hemisphere stabilization. The implementation is covered by
golden axis tests and deterministic randomized matrix-equivalence tests.

Every v2 batch and health response carries the strict source descriptor:

- system `nv-tlabs/ardy` at reviewed revision
  `693f74d13b3d04a0a22ce127ee79c929dd89756b`, skeleton `Core27`;
- the exact 27-joint order;
- local rotation space and XYZW quaternion order;
- global posed-joint position space;
- contact order `left_heel`, `left_toe`, `right_heel`, `right_toe`.

Quaternion representatives are stabilized across both frames and request
batches, preventing identical `q`/`-q` orientations from appearing as a large
interpolation jump. Behavior changes retain ARDY's bounded autoregressive
history so transitions start from the current pose. Request intensity maps
monotonically onto a reviewed CFG range of 1.25–2.75 (2.0 at intensity 0.5).

Two providers exist:

- `mock` produces deterministic protocol data for Unreal bridge and failure
  tests.
- `ardy` loads the approved Horizon8 checkpoint, the nine reviewed cached
  embeddings in [`config/motion-catalog.json`](../../config/motion-catalog.json),
  and the official persistent text encoder for open prompts. The reviewed
  cached behaviors remain the zero-encoding-latency path:
  `idle`, `listen`, `explain`, `wave`, `jog_in_place`, `run_in_place`,
  `jumping_jacks`, `stretch`, and `dance_relaxed`. It fails startup when either
  the complete private motion cache or the pinned offline encoder cache is
  absent.

Protocol v2 bumps the sealed embedding manifest to schema 2. An existing
three-embedding schema-1 cache is deliberately rejected and must be regenerated
before the newly tagged `ue5-spark-ardy:0.3.0` image can report ready. This
source change does not replace or modify the currently qualified Spark runtime.
Keep the existing qualified image available as rollback until v2 passes the
same canary, render, and soak gates.

The runtime wrapper uses a read-only root filesystem and checkpoint mounts,
drops every Linux capability, enables `no-new-privileges`, applies a PID limit,
and shares host networking only so the process can bind loopback. The normal
runtime receives no Hugging Face token or network model access. Its completed,
pinned Hugging Face cache is mounted read-only and forced into offline mode.
Separate one-shot tools use credentials only to populate that private cache.

Do not run a mixed v1/v2 activation sequence. The build script names the new
`0.3.0` candidate, while the download, cache, run, activation, recovery, and
package gates still contain retained `0.2.0`/protocol-v1/count-three contracts.
Before v2 deployment, version those wrappers coherently, preserve explicit v1
rollback, generate the nine-file schema-2 cache into a new private location,
and pass mock plus real canaries without touching the live v1 container.

The currently qualified v1 guarded activator validates a retained real canary
for 30 pose batches,
revalidates the untouched mock production container, switches only the fixed
ARDY container, and then repeats the 30-batch qualification on port 8777. A
post-switch failure recreates the exact sealed `0.1.0` mock configuration. It
never manages Fay, Unreal, Voxtral, system services, drivers, or CUDA.
If the fixed container is absent after a crash, rerun the same activator with a
new private evidence directory. It first requires the canonical name and port
to be unused, repeats the retained canary, and then restores the real endpoint;
a failed recovery attempt tries to restore and strictly verify the sealed mock
endpoint instead, and emits an emergency error plus evidence if the fixed name
or port prevents safe rollback. All launches use the captured immutable image
ID, and one fixed per-user lock serializes activation across evidence roots.

The retained protocol-v1 Spark qualification generated 240 frames in both
canary and production stages. Production steady request latency was 83.775 ms
mean, 155.470 ms p95, and 210.926 ms maximum against a 400 ms playback buffer.
A subsequent five-turn rendered Ada gate completed a 7.20-second real `explain`
action and returned to baked idle with ARDY p95 at 151.57 ms. The exact ARDY
container identity remained unchanged and its restart count remained zero.
Those numbers qualify the live v1 provider; they are a regression target, not
evidence that the v2 source candidate has run on Spark.
