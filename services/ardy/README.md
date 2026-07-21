# Isolated ARDY pose service

This directory builds a project-owned ARM64 container from NVIDIA's PyTorch
image and the official Apache-2.0
[nv-tlabs/ardy](https://github.com/nv-tlabs/ardy) source at a reviewed commit.
It does not install host packages or include TensorRT.

The service binds only to `127.0.0.1:8777` and exposes `GET /healthz` and
`POST /v1/poses`. Requests accept only an allowlisted behavior, bounded
intensity/duration, and the last consumed sequence. Arbitrary prompts and
credentials are not part of the service API. Responses contain at most eight
Core27 frames at 20 FPS in ARDY's Y-up, +Z-forward, metre coordinate system.
Neck and head rotations are replaced with identity so StreamingADA retains
ownership.

Two providers exist:

- `mock` produces deterministic protocol data for Unreal bridge and failure
  tests.
- `ardy` loads the approved Horizon8 checkpoint and only cached `idle`,
  `listen`, and `explain` embeddings. It reports degraded health and returns
  503 when those private embeddings are absent.

Image `0.2.0` adds the sealed embedding contract and is the qualified real
provider. Keep `0.1.0` available as the automatic mock-provider rollback.

The runtime wrapper uses a read-only root filesystem and checkpoint mount,
drops every Linux capability, enables `no-new-privileges`, applies a PID limit,
and shares host networking only so the process can bind loopback. The normal
runtime receives no Hugging Face token. Separate one-shot tools mount the token
read-only and write only approved checkpoint IDs or the three reviewed text
embeddings. Embedding generation uses a private Hugging Face cache and publishes
the complete cache atomically with prompt, exact encoder revision, shape, and
file hash seals. The large one-time encoder cache is a sibling of the runtime
model root, so the host-networked normal service cannot read it.

```bash
./scripts/build-ardy-container.sh
./scripts/download-ardy-checkpoint.sh \
  ARDY-Core-RP-20FPS-Horizon8 /private/checkpoints /private/hf-token
./scripts/cache-ardy-embeddings.sh \
  /private/checkpoints /private/hf-token cpu bfloat16
./scripts/activate-ardy-provider.sh \
  /private/checkpoints /private/logs-private/ardy-activation-UNIQUE-ID
```

The guarded activator validates a retained real canary for 30 pose batches,
revalidates the untouched mock production container, switches only the fixed
ARDY container, and then repeats the 30-batch qualification on port 8777. A
post-switch failure recreates the exact sealed `0.1.0` mock configuration. It
never manages Fay, Unreal, Voxtral, system services, drivers, or CUDA.

The first Spark qualification generated 240 frames in both canary and
production stages. Production steady request latency was 83.775 ms mean,
155.470 ms p95, and 210.926 ms maximum against a 400 ms playback buffer. A
subsequent five-turn rendered Ada gate completed a 7.20-second real `explain`
action and returned to baked idle with ARDY p95 at 151.57 ms. The exact ARDY
container identity remained unchanged and its restart count remained zero.
