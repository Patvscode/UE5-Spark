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

The runtime wrapper uses a read-only root filesystem and checkpoint mount,
drops every Linux capability, enables `no-new-privileges`, applies a PID limit,
and shares host networking only so the process can bind loopback. The normal
runtime receives no Hugging Face token. A separate one-shot downloader mounts
the token read-only and writes only approved checkpoint IDs.

```bash
./scripts/build-ardy-container.sh
./scripts/download-ardy-checkpoint.sh \
  ARDY-Core-RP-20FPS-Horizon8 /private/checkpoints ~/.cache/huggingface/token
./scripts/run-ardy-container.sh /private/checkpoints mock
```

Use `ardy` instead of `mock` only after approved embeddings exist and the
Unreal retarget adapter has passed its safety gates.
