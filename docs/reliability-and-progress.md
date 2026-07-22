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

That generated-provider marker proves Unreal transport and provider selection;
checkpoint identity is qualified separately by the guarded ARDY service and
container checks. The production endpoint now uses Horizon8 with three sealed
cached embeddings. The text encoder and Hugging Face credential are absent from
ordinary runtime, while the deterministic Core27 service remains useful for
offline protocol and fault-injection tests.

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
launcher is owned by its immutable child PID and Linux `/proc` start time.
Before runtime it may move repeatedly through only the exact canonical Bash
and `/usr/bin/env` interpreters used by the reviewed script chain. The expected
sealed Unreal executable is a terminal state. A scanned Unreal PID is never
adopted until it matches that original PID and start time; a collision or any
unexpected transition fails the run. Early-error cleanup still terminates and
reaps the known child by that immutable identity so an allowed interpreter
handoff cannot strand Unreal.

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

### Current verified v29 result

The private native ARM64 v29 package is sealed with package-seal digest
`592cd46a35a1a8708acaeb4cc072c772d031af9f0d34c4b1b8a3773156b4786a`;
the AArch64 executable SHA-256 is
`75b024c4867cc866511122b44de1ff89a82f459f134640a49b9449fd643cb9ee`.
Ada and Aoi both passed five-turn rendered gates with the real Horizon8
provider before the final recovery work. The retained Aoi bundle is
`rendered-v29-aoi-real-ardy-5turn-20260722T0011Z`: five turns in 302 seconds,
8.74 ms worst facial p95, 13,764 KiB tail RSS growth, five dormancy wakes with
zero cancellations, and zero runtime/kernel/action failures.

After the recovery verifier was hardened, a fresh Ada production qualification
completed five turns in 303 seconds. All five facial summaries, normal audio
playbacks, allocator releases, and delayed collections completed. Worst facial
p95 was 7.85 ms. Unreal RSS moved from 2,189,848 KiB to 2,166,724 KiB, reached
2,189,848 KiB maximum, and grew 2,892 KiB across the measured tail. Minimum
`MemAvailable` was 53,552,328 KiB and GPU utilization peaked at 20 percent.
Frame-policy, facial-frame, audio-watchdog, bridge, procedural-action, runtime,
and kernel failure counts were zero. The package seal reverified, Fay and ARDY
kept their exact identities, Voxtral restored, and no Unreal process remained.

A separate earlier diagnostic proved the failure path rather than merely
checking steady state. While a ten-second generated `explain` action and a 9.68-second
speech turn overlapped, the guard stopped only the exact captured project ARDY
container. Unreal observed the provider loss, entered and completed bounded
baked-idle fallback, and completed facial speech at 7.46 ms p95. The guarded
activator published a new sealed Horizon8 provider; Unreal requalified it and
completed generated `explain`, `idle`, and `listen` actions. The audit counted
zero rejected pose batches, unavailable transitions, generated fallbacks, or
neutral-explain fallbacks between recovered readiness and normal Unreal
`PreExit`. Cleanup validated the replacement provider twice, preserved Fay,
restored Voxtral, rechecked the package, and left no Unreal process or cleanup
error.

V29 is therefore the latest Ada production-qualified package. This diagnostic
is recovery evidence only; it does not replace the production or endurance gates.
V28 remains the immediate rollback, long-endurance, and measured-frame-rate
baseline.

### Retained verified v28 result

The private native ARM64 v28 package is sealed with package-seal digest
`653d14a1205a25bbd7c5f434c998919c3d5284af40717d0c267294909b67139f`;
the AArch64 executable SHA-256 begins with `b1184ec`. Ada passed its rendered
four-turn production qualification in 241 seconds. Worst facial p95 was
17.03 ms, maximum Unreal RSS was 2,132,444 KiB, tail RSS growth was 8,176 KiB,
and minimum `MemAvailable` was 58,918,672 KiB.

The finalized summary recorded one project-owned GameUserSettings verification,
one reviewed frame-policy enforcement, and zero frame-policy violations. It also
recorded five dormancy entries, four accepted-message wakes, no dormancy
preparation cancellation, and zero runtime, kernel, or action failures.
Controlled teardown was clean. Fay and ARDY remained unchanged, and the
separately managed Voxtral service was restored.

Ada's separate production endurance gate passed 20 turns over 1,803 seconds.
Unreal RSS began at 2,119,152 KiB, ended at 2,117,968 KiB, reached a maximum of
2,123,648 KiB, and grew 6,328 KiB across the measured tail with a 6.10 KiB/s
slope. Minimum `MemAvailable` was 58,743,872 KiB. GPU utilization peaked
briefly at 95 percent; no three-sample excessive-GPU condition occurred.

All 20 turns produced facial summaries, normal playbacks, allocator releases,
and delayed collections; worst facial p95 was 6.56 ms. The ordered dormancy
history contained 21 entries, 20 accepted-message wakes, and no preparation
cancellation. Policy, action, runtime, and kernel failure counts were zero.
Controlled teardown, post-run seal verification, and external-service
continuity all passed.

Aoi then passed its 241-second / four-turn rendered qualification. Maximum RSS
was 2,177,596 KiB, tail growth was 2,512 KiB, and minimum `MemAvailable` was
58,668,572 KiB. Four facial summaries completed with 6.54 ms worst p95;
dormancy recorded five entries and four wakes. Frame-policy drift, runtime
failures, and kernel failures were zero, and the outer wrapper passed.

The separate guarded CSV run was diagnostic-only. It captured exactly 6,000
frames, discarded 300 startup and 30 ending frames, and evaluated 5,670 frames.
Mean `FrameTime` was 33.33156 ms, average rate was 30.001596 FPS, p95 was
38.4833 ms, and p99 was 39.5503 ms. Capture duration was 202.981269 seconds,
with only 0.0149 ms difference between summed frame time and duration metadata.
The retained CSV SHA-256 is
`d7ce10963ab418dc30ecbc090918795a55b6c77605d24e5dd4e873d569dad9b1`.
Diagnostic teardown and outer service restoration passed cleanly. This measured
result confirms the intended limiter without promoting profiling overhead into
the production endurance evidence.

A separate 90-second, one-turn v28 diagnostic produced a guarded 1280x720 PNG
and an exact eight-second, 30 FPS MP4 for the private progress hub. The capture
watcher selected Ada's exact X11 client and the outer gate still passed teardown,
service restoration, and identity checks. Those pixels are visual evidence only;
capture and encoder overhead were absent from the production and CSV gates above.

### Prior verified v27 rollback result

The sealed Ada v27 package passed this sequence on Spark. Its four-turn
qualification produced 1,640 exact facial frames over 32 seconds of speech,
15.78 ms worst facial p95, four normal audio completions, four allocator
releases, four delayed collections, and exact dormancy wake/re-entry history.
Tail RSS growth was 10,704 KiB.

The subsequent cold-launched endurance run completed 20 turns over 1,802
seconds. It recorded 20 exact facial summaries, 20 normal playbacks/releases/
collections, 21 dormancy entries and 20 accepted-message wakes, 15.92 ms worst
facial p95, and 29,072 KiB tail RSS growth. No watchdog, queue, runtime, Vulkan,
kernel, forced-teardown, Fay-survival, or package-seal check failed.

V27 remains intact as the prior production-qualified functional rollback, but
it is not the verified frame-cap baseline. A later boot diagnostic captured
exactly 12,000 frames in 70.536429 seconds, or 170.125 FPS, after the standard
GameUserSettings value reset the intended `t.MaxFPS=30` configuration to zero.

The Ada PNG and eight-second MP4 allowlisted on the private progress hub came
from a later one-turn diagnostic. They are visual evidence only; the guarded
capture's extra X11 and encoder work was not present in either production
result.

Run rendered tests only when enough unified memory is genuinely available. The
launcher requires 48 GiB of `MemAvailable` even when GPU utilization is idle,
because resident model servers can otherwise make Vulkan fail with
`NV_ERR_NO_MEMORY`. Never lower this reserve, and never pause an unrelated
workload without explicit operator approval. Null-RHI diagnostics skip the
Vulkan-memory gate but do not
prove audio-device completion, skin/hair rendering, frame rate, or the delayed
rendered cleanup path. V28 verifies the project-owned 30 FPS policy at startup,
audits it every five seconds, and now has a separate exact-frame CSV measurement
at 30.001596 FPS. V27 remains a functional rollback with the known uncapped
limitation above.

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

## Real ARDY milestone

The sealed Horizon8 provider is now active at `127.0.0.1:8777`. Both the
30-batch retained canary and the 30-batch production validator passed the exact
Core27, sequence/time, normalized-quaternion, numeric-contact, face-exclusion,
checkpoint, embedding-count, isolation, and 400 ms latency contracts. The
production validator measured 83.775 ms steady mean, 155.470 ms p95, and
210.926 ms maximum request latency.

The first rendered integration gate ran five Ada speech turns over 302 seconds
so the behavior matrix reached generated `explain`. Unreal logged the real ARDY
provider for 7.20 seconds and a clean return to baked idle. Worst StreamingADA
face p95 was 8.39 ms, tail RSS growth was 1,408 KiB, and every audio, allocator,
action, teardown, package-seal, Fay-continuity, ARDY-identity, and Voxtral-
restoration check passed. Private evidence and media remain outside Git.

## Private progress media capture

Capture media only in a separate diagnostic run after production qualification
has torn down. `scripts/capture-spark-avatar-window.sh` arms before launch and
waits for one exact sealed `FayAvatarRuntime` process, a fresh runtime log, the
reviewed character marker, and real speech playback. It then requires one
visible X11 client whose `_NET_WM_PID` equals the recorded runtime PID and whose
client geometry is exactly 1280x720. It never captures the whole desktop and
records no audio.

```bash
./scripts/capture-spark-avatar-window.sh \
  /path/to/FayAvatarRuntime/Binaries/LinuxArm64/FayAvatarRuntime \
  /path/to/FayAvatarRuntime/Saved/Logs/FayAvatarRuntime.log \
  Ada \
  /private/media-root/v27/ada-v27-speaking-wave.png \
  /private/media-root/v27/ada-v27-speaking-wave-8s.mp4 \
  180 speech Portrait
```

For a real generated-motion progress clip, pass the optional sealed
`ardy-explain` phase after the wait bound. The watcher then waits for the exact
allowlisted ARDY `explain` start marker before capturing; arbitrary log markers
are not accepted.

```bash
./scripts/capture-spark-avatar-window.sh \
  /path/to/FayAvatarRuntime/Binaries/LinuxArm64/FayAvatarRuntime \
  /path/to/FayAvatarRuntime/Saved/Logs/FayAvatarRuntime.log \
  Ada /private/media-root/v28/ada-real-ardy.png \
  /private/media-root/v28/ada-real-ardy-8s.mp4 480 ardy-explain Portrait
```

For lower-body evidence, launch the reviewed `FullBody` runtime preset and pass
`FullBody` as the final capture argument. The watcher requires exactly one
matching framing marker before it records, and its output metadata names the
framing that was actually qualified.

Run that watcher in parallel with an explicitly diagnostic one-turn rendered
test, or a five-turn diagnostic when capturing `ardy-explain`. The capture
revalidates executable, Linux start time, X11 window PID,
visibility, geometry, image dimensions, video frame rate, and duration before
no-clobber publishing the private PNG/MP4 pair. NVENC and X11 capture add GPU
work, so media runs must never be promoted to production evidence. Add a file
to the progress status allowlist only after capture passes; keep partial files,
media, and capture metadata outside Git.
