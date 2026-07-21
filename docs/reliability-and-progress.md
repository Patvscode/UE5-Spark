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

The harness samples Unreal RSS, private-dirty and anonymous mappings, swap,
shared-GPU utilization, and unified `MemAvailable` every five seconds. It aborts
after three consecutive excessive GPU samples, rejects an optional absolute RSS
ceiling, and measures tail growth from the time-based midpoint rather than from
sparse per-turn samples. Spark does not expose a useful separate `memory.used`
value through `nvidia-smi`, so that column may be `-1` while RSS,
`smaps_rollup`, and `MemAvailable` remain available.

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
sends `TERM` only to that process, and waits up to 30 seconds for an ordinary
exit. If the same executable and Linux `/proc` start time are still present, it
sends `KILL`, reaps the owned child, and fails the run rather than leaving a
project process behind or treating forced termination as qualification. The
launcher may retain its PID and start time while changing only from the Bash
wrapper to the expected sealed Unreal executable; any other executable
transition is refused and never signaled.

The strict harness runs in a project-owned process session with a derived,
finite wall-clock deadline. `HUP`, `INT`, `TERM`, timeout, and ordinary error
paths cancel and reap that session before Unreal teardown. After Unreal exits,
the wrapper recaptures the complete launch-to-shutdown runtime log and kernel
journal, reruns the fatal/Vulkan/kernel scans, proves that the original Fay
executable and `/proc` start time still own all four listeners, repeats the Fay
HTTP health probes, and rechecks the package seal. It never starts, stops, or
reconfigures Fay or another model service. A shell-level identity check still
cannot eliminate the final check-to-signal race the way a native Linux
`pidfd_send_signal` helper could.

Every private result directory includes the exact NUL-delimited runtime command
line (`runtime-argv.nul`), a readable shell-escaped rendering, and a package
identity record containing the executable, launcher, character-manifest, and
deep-verification-seal hashes. The summary repeats the command-line and seal
digests, allowing evidence to be tied to one exact invocation and sealed build.
Production status remains pending in the inner harness output; only the owning
wrapper changes it to passed after exact-process teardown, child reaping,
launch-to-shutdown failure rescanning, stable Fay identity and health, and the
post-run package-seal verification all succeed. The finalized summary records
the Unreal wait status, whether forced termination was required, the post-run
seal digest, and the post-teardown failure counts.

The default evidence class is `production` only for the exact reviewed policy:
rendered speech, a reviewed Ada or Aoi profile, 1280x720, the standard audio and
motion requirements, the default resource and facial-performance limits, no
CSV profiling, and no additional Unreal arguments. Any changed resolution,
limit, diagnostic switch, or extra Unreal argument automatically makes an
otherwise unspecified run diagnostic. Explicitly requesting `production` with
any such deviation fails closed. Set `FAY_SOAK_EVIDENCE_MODE=diagnostic` for a
speech, profiling, renderer-isolation, or alternate-threshold experiment.
Diagnostic mode preserves those controlled experiments but marks the summary
`diagnostic-only-not-production-qualification` and lists the detected policy
deviations. A diagnostic pass is never reported as production qualification.

Set the turn count to zero for an idle-only rendered diagnostic. The same
launcher, exact-PID ownership, five-second resource sampling, failure scanning,
teardown, Fay survival check, and package-seal verification still apply, but no
HTTP speech turn or semantic action is sent. This separates a renderer or
always-on animation slope from speech-lifecycle growth without creating a
second launch path:

```bash
./scripts/run-spark-avatar-soak.sh \
  /path/to/FayAvatarRuntime-Arm64.sh \
  FAY_PID /path/below/logs-private/rendered-idle 720 0
```

The reviewed idle gate ignores its first 120 seconds, then evaluates one
bounded final measurement window using the actual elapsed run time. Growth,
ordinary-least-squares slope, and 7--18 MiB step-like increases all use that same
window; the summary records its actual start, end, and sample count. The gate
requires no more than 96 MiB of growth, a slope no greater than 128 KiB/s, and
no more than two step-like increases. It aborts if
Unreal exceeds 2.9 GiB RSS or unified `MemAvailable` drops below 48 GiB. These
limits distinguish a stable warm-up from the recurring allocation staircase
that a short endpoint-only gate can miss.

The idle measurement window is 300 seconds by default. Short, diagnostic-only
isolation runs may explicitly set
`FAY_SOAK_IDLE_MEASUREMENT_SECONDS` from 30 through 3600; the result remains a
diagnostic and cannot qualify a production package.

When dormancy is enabled, the gate parses the ordered history and requires
`Enter, (Wake for accepted Fay message, Enter)*`: one accepted-message wake per
requested turn, strict alternation, exactly one more enter than wake, and
`Enter` as the latest transition. Production qualification permits no
dormancy-preparation cancellations. A diagnostic may set
`FAY_SOAK_MAX_DORMANCY_CANCELLATIONS` to a reviewed non-negative bound, which is
recorded in the summary.

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
