# Verified status

This page separates measured results from planned work. The latest evidence was
recorded on DGX Spark on 2026-07-21. The cooked package and all Epic-licensed
content remain private and are not part of this repository.

## Working end to end on DGX Spark

- UE 5.8's x86-64 graphical Editor and commandlets run through a pinned,
  rootless FEX userspace. This is the cooker and MetaHuman assembly environment;
  it does not install packages, register `binfmt_misc`, change services, or
  replace the NVIDIA driver.
- Epic's included female Ada preset was assembled as an Optimized / High
  MetaHuman and cooked for LinuxArm64 on the Spark.
- The v10 cook is driven by a reviewed `Ada` character profile rather than
  hard-coded runtime and cook paths. The profile seals the actor class,
  face/body component names, adapter, spawn/camera framing, cook directories,
  and required assets. Unknown or unsafe profile IDs fail closed to the
  diagnostic avatar.
- Native ARM64 UnrealBuildTool, AutomationTool, the Game target, and UnrealPak
  produced a Pak-only sealed archive with an AArch64 executable and AArch64 ONNX
  Runtime.
- The archive verifier deep-confirmed Ada, MetaHuman common content, the
  StreamingADA v2 model, Ada's Interchange garment material dependency, and the
  absence of the Editor-only assembly helper. Every immutable shipped file is
  hash-sealed; runtime files below the packaged Game and Engine `Saved` trees are
  deliberately excluded.
- The native package renders Ada through the Spark's NVIDIA GB10 Vulkan SM6 path
  with visible skin, hair, clothing, materials, and portrait lighting. Audio
  plays through the Spark.
- The local UE 5.8 StreamingADA model loads with 81 solver curves and converts
  its output to all 251 MetaHuman raw controls. The adapter publishes the exact
  local Live Link Basic subject `FayAudio` and installs UE 5.8's native
  `ULiveLinkInstance` on Ada's Body as required by the generated assembly.
- Fay's existing HTTP/audio and avatar WebSocket listeners are discovered and
  readiness-probed without printing or persisting their private addresses. MCP
  administration and SSE readiness are also checked before launch.
- A live Fay response downloaded and played its WAV while visibly driving Ada's
  learned facial speech motion. A captured speaking frame showed the animated
  mouth open with visible teeth, distinct from the neutral frame.
- The Ada v10 regression performed a 7.920-second live speech turn with 406
  solved frames, 10.00 ms average, 18.02 ms p95, and 19.27 ms maximum solve
  time. A second recorded 5.680-second turn produced 294 frames with 18.24 ms
  p95. The sealed package passed deep verification again after teardown, and
  the externally managed Fay process remained alive.
- A minimized-window 2.240-second speech test solved exactly 122 frames: 112
  speech frames at 50 Hz plus the configured 10-frame tail. Per-solve timing was
  9.28 ms average, 11.17 ms p95, and 19.10 ms maximum.
- A separate 4.64-second speech chunk solved exactly 242 frames after the
  background-window idle throttle was disabled in runtime code.
- One idle diagnostic frame reported approximately 187.35 FPS / 5.34 ms. Treat
  this as an observed frame, not a formal performance benchmark.
- The final sealed package completed two consecutive cold launches, reached the
  solver, exact Live Link consumer, Fay WebSocket, and background-throttle
  markers on each run, then completed clean teardown without leaving a runtime
  process behind.
- The project-owned ARDY image builds on Spark from NVIDIA's ARM64 PyTorch
  25.05 image and the reviewed official ARDY commit. Inside the container,
  PyTorch 2.8 detects the GB10 GPU. Runtime checks confirmed a read-only root
  filesystem/checkpoint mount, dropped capabilities, `no-new-privileges`, PID
  limit, and a loopback-only `127.0.0.1:8777` listener.
- Both approved Core27 checkpoints downloaded into the private model mount. The
  eager Horizon40 model generated 40 frames in 1.682 seconds. Horizon8 then ran
  six steady eight-frame generations in 59-153 ms with 132 ms p95, passing the
  400 ms buffer target after warmup. No TensorRT was installed or used.
- The strict mock pose service passed schema, sequence, allowlist, Core27,
  neck/head-exclusion, and coordinate-mapping tests. The real Horizon8 provider
  loads without network/token access and fails closed because the account does
  not yet have access to the separate gated Meta Llama text encoder.
- The sealed Ada v12 package initialized the generated Core27-to-MetaHuman
  retargeter without replacing the Body's StreamingADA `ULiveLinkInstance`.
  Nineteen reviewed body bones are mapped after ordinary body evaluation;
  face, neck, head, and sparse hand endpoints remain excluded.
- A live 16.400-second Fay turn drove both the facial path and continuous
  loopback pose requests. StreamingADA solved 830 frames at 8.88 ms average,
  15.77 ms p95, and 20.28 ms maximum while the body adapter remained active.
- Failure injection removed only the project-owned ARDY container during a
  second live turn. Ada completed 14.640 seconds of audio and 742 facial frames
  at 9.01 ms average / 15.79 ms p95; Unreal and the externally managed Fay
  process stayed alive. The body path fell back to idle and detected the
  restarted loopback service automatically without restarting Unreal or Fay.
- The reviewed builder was generalized without permitting arbitrary presets or
  overwrites. Epic's included Aoi preset assembled beside Ada on Spark, and a
  fresh 947-package LinuxArm64 cook produced a sealed dual-character v13
  package whose manifest deep-verifies both Blueprints.
- Aoi launched from that native package using only `-FayCharacter=Aoi` and the
  reviewed profile. The same StreamingADA and generated Core27 retarget paths
  initialized without Aoi-specific C++. Two live turns solved 622 frames over
  12.240 seconds at 15.87 ms p95 and 486 frames over 9.520 seconds at 15.91 ms
  p95; the second turn continuously requested body poses.
- The installed UE 5.8 Aoi preset is male. It remains a valid portability
  fixture, but it does not satisfy the desired second-female appearance; Ada is
  still the female demonstration character until another reviewed preset is
  assembled.
- The v13 reliability run completed 20 turns and 6,552 facial frames over
  1,802 seconds without a functional crash; worst facial p95 was 15.86 ms.
  It was correctly rejected for long-running use because Unreal RSS increased
  from 2,266,288 KiB to 3,562,212 KiB instead of plateauing.
- A v14 package made StreamingADA utterance reset selectable. Relying on the
  solver's documented non-contiguous first-frame marker instead of calling
  `ClearCache` completed an eight-turn gate with exact facial output. RSS grew
  128,888 KiB overall but only 50,056 KiB across the latter four turns, with
  per-turn growth declining from roughly 25 MiB to 10 MiB.
- The subsequent long v14 run was invalidated by shared-GPU contention, not
  treated as an avatar pass or failure. A separate `lm-eval` workload drove the
  GB10 to about 90 percent utilization; the kernel recorded NVIDIA Xid 109
  (`CTX SWITCH TIMEOUT`) against Unreal before its render watchdog terminated.
  Fay remained alive. The soak tool now detects sustained shared-GPU saturation.
- The sealed dual-character v15 package adds repeated neutral Live Link
  bootstrap frames to remove a measured cold-start scheduler race and caps
  rendering at 30 FPS to retain compute headroom. Its final uncontended soak is
  pending shared-GPU availability; v14 remains the measured memory-regression
  reference and v13 remains the rollback package.
- The private Tailscale progress hub is live independently of the avatar stack.
  It serves only allowlisted private milestone media, supports mobile video
  ranges, and links to the existing agent board without exposing private data
  through this public repository.

## Important boundary

The packaged application is native Linux ARM64. The full Editor is not a native
ARM64 Editor build: it remains an x86-64 UE 5.8 process running experimentally
through FEX. Its stable tested mode exposes two emulated cores and uses
`-onethread` plus `-norhithread`; the ordinary render/RHI thread split was not
stable in the tested configuration.

An earlier uncooked Game target stopped because it had no cooked Global shader
library. The final workflow does not use that shortcut. FEX runs the real
Editor/cooker, then native ARM64 tools build, stage, package, and verify the
deployable application.

## Remaining work

- Tune and visually validate the post-evaluation Core27 retarget adapter with
  polished motion. Its character-neutral routing, eight-frame interpolating
  buffer, baseline calibration, head/face mask, bounded root motion, blend-in,
  cached-pose fade-out, and automatic service recovery now run natively on
  Spark without replacing StreamingADA.
- Author or generate the private deterministic gesture clips. The current
  baked provider fails safely to idle when no compatible reviewed montage is
  configured.
- Cache approved ARDY text embeddings after Meta Llama access is granted. The
  real provider currently reports degraded and returns 503 without them.
- Visually validate and tune the source-level semantic head-control mappings for
  `nod`, `shake`, `think`, and `warn`.
- Add reviewed, MetaHuman-compatible body animations and explicit mappings for
  actions such as `wave` and `invite`. No body montages are included today.
- Tune gaze, breathing, idle motion, emotional range, lighting, LODs, and scene
  presentation for a polished long-running character experience.
- Assemble and validate a second reviewed female preset. Aoi already proves the
  no-character-specific-C++ portability requirement but is male in UE 5.8.
- Complete the uncontended v15 30-minute mixed-action soak. Malformed envelope
  and stale-sequence live injections already passed while speech/facial output
  continued; the remaining gate is sustained runtime under available GPU
  headroom.

## Publication boundary

The isolated source build uses private compatibility work against
Epic-licensed source. Publishing the Engine tree, its patches, MetaHuman
content, StreamingADA model, cooked packages, screenshots derived from licensed
content, or private validation logs would cross the repository boundary. This
repository contains only original project source, adapters, guards, and public
instructions.
