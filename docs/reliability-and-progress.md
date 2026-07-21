# Reliability and private progress

The reliability runner and progress hub are optional project tools. Neither one
starts, stops, reconfigures, or supervises Fay, and neither modifies DGX OS,
drivers, CUDA, or system services.

## Guarded soak test

`scripts/soak-spark-avatar.sh` accepts the exact Unreal PID, exact externally
managed Fay PID, a private output directory, duration, and turn count. It
refuses unrelated executables and proves that the supplied Fay PID owns HTTP,
avatar WebSocket, MCP administration, and MCP SSE. Rendered mode additionally
requires the exact sealed executable, explicit Vulkan, the expected resolution,
and the absence of Null RHI.

The harness samples Unreal RSS, shared-GPU utilization, and unified
`MemAvailable` every five seconds. It aborts after three consecutive excessive
GPU samples, rejects an optional absolute RSS ceiling, and measures tail growth
from the time-based midpoint rather than from sparse per-turn samples. Spark
does not expose a useful separate `memory.used` value through `nvidia-smi`, so
that column may be `-1` while RSS and `MemAvailable` remain enforceable.

Every requested speech turn must produce exactly one facial summary, exactly
50 solver frames per speech second plus the ten-frame tail, and facial p95 at
or below 20 ms. A rendered gate also requires one normal Unreal audio
completion, allocator release, and delayed speech-object collection per turn.
Audio watchdog fallbacks and bridge warnings fail the gate instead of being
mistaken for successful playback. Mixed prompts exercise wave, invite, think,
warn, explain, and the bounded head path. Deterministic procedural body actions
must appear in the new runtime log. `explain` may instead report the ARDY
generated provider; either that generated-provider marker or its procedural
fallback marker is accepted so the gate follows the provider Unreal actually
selected.

All new runtime-log lines and kernel-journal lines are preserved privately.
Fatal/assertion/OOM/Vulkan failures, project error markers, queue overflow, new
NVIDIA Xids, context-switch timeouts, allocation failures, or a fallen GPU fail
automatically. The kernel cursor is captured before the run so historical
driver events cannot contaminate a new result.

Use `scripts/run-spark-avatar-soak.sh` for rendered testing. It owns one cold
launch of the selected sealed package, discovers exactly one matching process,
waits for the Fay and character readiness markers, invokes the strict harness,
sends `TERM` only to that process, verifies that Fay still owns its listeners,
and rechecks the package seal after teardown. It never starts, stops, or
reconfigures Fay.

Run a four-minute, four-turn 1280x720 qualification before the final endurance
gate:

```bash
./scripts/run-spark-avatar-soak.sh \
  /path/to/FayAvatarRuntime-Arm64.sh \
  FAY_PID /path/below/logs-private/rendered-qualification 240 4
```

Only after that passes, cold-launch again for 1,800 seconds and 20 turns. Keep
CSV profiling disabled for this memory/reliability gate; the wrapper defaults
to `FAY_SOAK_ENABLE_CSV=0` so profiling allocations cannot be mistaken for an
avatar leak. Run a separate short performance capture with
`FAY_SOAK_ENABLE_CSV=1` and retain that CSV alongside the endurance evidence. The
rendered defaults enforce tail RSS growth at or below 128 MiB, total Unreal RSS
at or below 3 GiB, facial p95 at or below 20 ms, and no three consecutive GPU
samples above 95 percent. Preserve CSV timing and private beginning/midpoint/end
media for the final visual review. A short 1080p gate follows the 720p endurance
pass; do not substitute a 30-minute 1080p run for the qualification sequence.

Run rendered tests only when enough unified memory is genuinely available. The
launcher requires 48 GiB of `MemAvailable` even when GPU utilization is idle,
because resident model servers can otherwise make Vulkan fail with
`NV_ERR_NO_MEMORY`. Never lower this reserve, and never pause an unrelated
workload without explicit operator approval. Null-RHI diagnostics skip the
Vulkan-memory gate but do not
prove audio-device completion, skin/hair rendering, frame rate, or the delayed
rendered cleanup path. The packaged avatar caps rendering at 30 FPS to retain
compute headroom for speech and motion.

## Tailscale progress hub

`scripts/run-progress-hub.sh` binds `tools/progress_hub.py` only to the Spark's
Tailscale IPv4 address on unprivileged port 8474. It requires a private JSON
status document, a real private media root, and a Tailscale agent-board URL.

The server validates a narrow status schema and serves only files explicitly
listed in that document. Absolute paths, traversal, symlinks, directory
listing, arbitrary board hosts, and non-Tailscale binds are rejected. Images
and videos support `HEAD` and single byte ranges for mobile playback. Responses
disable caching, MIME sniffing, and framing and use a restrictive content
security policy.

The source repository contains no private hostname, listener address, media,
status data, authentication material, or licensed MetaHuman capture. Keep the
status document, process log, screenshots, and videos outside Git.

The hub is deliberately a small visibility aid rather than a dependency of the
avatar stack. Unreal, Fay, StreamingADA, and ARDY continue to run if the hub is
stopped.
