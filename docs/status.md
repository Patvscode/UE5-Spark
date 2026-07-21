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
  rendering at 30 FPS to retain compute headroom. Its first cold launch
  configured Ada immediately, then a GPU-isolated Null-RHI gate completed 20
  turns over 1,803 seconds: 6,552 exact facial frames over 127.040 speech
  seconds, zero frame-accounting failures, 11.69 ms worst p95, and no fatal,
  assertion, OOM, or queue-overflow marker. RSS moved from 539,300 KiB to
  542,560 KiB overall and only 616 KiB across the latter half, demonstrating a
  plateau instead of v13's linear growth. The externally managed Fay process
  remained alive through verified teardown.
- The private Tailscale progress hub was verified running independently of the avatar stack.
  It serves only allowlisted private milestone media, supports mobile video
  ranges, and links to the existing agent board without exposing private data
  through this public repository.
- A fresh dual-character v16 cook rebuilt 947 LinuxArm64 packages, then native
  Clang 20.1.8 compiled the changed body-motion and MetaHuman runtime modules,
  linked the AArch64 Game, staged a Pak-only archive, and passed deep Ada/Aoi,
  StreamingADA, garment, ONNX Runtime, architecture, and immutable-file checks.
- v16 cold-launched Ada without an NVIDIA context under Null RHI and connected
  Fay, StreamingADA, and ARDY. Live Fay actions selected the character-neutral
  procedural `wave` and `invite` fallbacks and the face driver explicitly
  delegated those actions without taking body ownership. Three completed
  speech turns retained exact frame accounting (98/1.760 s, 162/3.040 s, and
  346/6.720 s), all at 6.27 ms p95 or lower. No fatal marker appeared and Fay
  remained alive after verified teardown.
- v16 also rendered Ada through native Vulkan at 1080p and 720p. Front-view
  private captures confirmed recognizable wave and invite poses, continuous
  facial speech, and no visible root jump or face/head ownership conflict. A
  rendered soak was stopped at turn seven because RSS was still increasing by
  roughly 74--80 MiB per utterance; that result is retained as a failure.
- v17 and v18 added immediate and delayed allocator trimming. The v18 rendered
  eight-turn gate passed its bounded tail-growth, exact-frame, 20 ms facial
  p95, and 95 percent GPU ceilings, but the longer warm slope still justified
  a stronger completed-speech cleanup rather than declaring a soak pass.
- The sealed dual-character v19 package now collects completed speech objects
  before its delayed allocator trim. Its GPU-independent eight-turn gate passed
  over 242 seconds with exact facial accounting, 6.24 ms worst p95, and only
  892 KiB of latter-half RSS growth. A rendered v19 launch was unable to create
  a Vulkan context because unrelated model servers left about 38 GiB of Spark's
  unified memory available; NVIDIA reported `NV_ERR_NO_MEMORY`. No unrelated
  workload was stopped. The launcher now requires a reviewed 48 GiB unified-
  memory reserve before Vulkan startup, while allowing Null-RHI diagnostics.
- The companion Fay runtime was fast-forwarded to its reviewed `d86d6a4`
  branch and restarted under its existing user service without changing the
  unit, DGX OS, drivers, or CUDA. All backend health probes passed after normal
  listener warmup. The live MCP advertised `avatar_perform_action`; an actual
  MCP call produced an allowlisted `invite` event on the registered avatar
  WebSocket, while a non-allowlisted direct action returned HTTP 400. A separate
  post-deployment turn returned the exact requested text, synthesized a
  fetchable WAV, and preserved all existing MCP connections.
- The rendered reliability tools now reject a weaker false positive observed in
  the earlier Null-RHI evidence: headless audio used the queue watchdog and did
  not prove normal audio-device completion or the delayed object-collection
  marker. Rendered mode now requires exact executable/arguments, exact Fay port
  ownership, normal playback and delayed collection once per turn, strict
  facial-summary equality, five-second RSS/GPU/unified-memory sampling, new
  runtime and kernel failure scanning, mixed deterministic actions, owned TERM
  teardown, Fay survival, and package-seal verification.
- The sealed dual-character v21 package adds action-only head control without
  giving body motion ownership of face, neck, or head. Live MCP calls exercised
  `wave`, `invite`, `think`, `warn`, `explain`, `nod`, and `shake`; Unreal used
  deterministic procedural fallbacks for the timing-critical actions, selected
  the configured Core27 test provider for `explain`, and Fay rejected
  non-allowlisted `dance`. A speech-overlap check started `nod` while
  StreamingADA was active;
  the face solve completed its exact 530 frames over 10.400 seconds at 6.26 ms
  p95 with no project error marker.
- The same v21 executable selected Aoi solely through `-FayCharacter=Aoi`,
  initialized the shared bridge/StreamingADA/retarget paths, and passed the
  complete MCP action matrix without character-specific C++ changes. Exact
  Unreal teardown left Fay owning ports 5000, 5010, 8766, and 10002, and the
  immutable package seal passed again afterward. This remains headless control
  and portability evidence; final visual quality still belongs to the rendered
  gate.
- The remaining rendered allocation staircase was traced to an Unreal Vulkan
  parallel-render-pass allocation-lifetime issue in the private UE 5.8 source build. An
  A/B diagnostic first proved that disabling parallel RDG execution stopped the
  growth. After the reviewed ownership fix, v27 ran the normal parallel path
  with zero net positive RSS growth over the measured post-warmup window, a
  -286.38 KiB/s measured slope,
  and no runtime, Vulkan, or kernel failure. The private Engine patch is not
  published by this source-only repository.
- The resulting sealed dual-character v27 package contains 947 cooked packages
  and passed the complete architecture, Ada/Aoi, StreamingADA, garment, ONNX
  Runtime, Pak-only layout, Editor-helper exclusion, and immutable-file checks.
  A headless regression matrix also passed default Ada startup, dormancy, live
  wake/action/re-dormancy, and exact teardown.
- Ada's rendered four-turn production qualification completed 1,640 exact
  facial frames across 32 seconds of speech with 15.78 ms worst p95. Wave,
  invite, think, and warn actions were routed; every turn produced normal audio
  completion, allocator release, and delayed object collection. Five dormancy
  entries and four accepted-message wakes alternated exactly, and tail RSS grew
  only 10,704 KiB.
- Ada then passed the current sealed 1,802-second / 20-turn rendered production soak.
  All 20 facial summaries, normal playbacks, allocator releases, delayed
  collections, and dormancy wakes were present; worst facial p95 was 15.92 ms
  and tail RSS growth was 29,072 KiB. There were no watchdog, queue, runtime,
  Vulkan, kernel, or forced-teardown failures. Fay retained its original
  process identity and listeners, and the v27 package seal verified again.
- The complete v27 direct-action boundary accepted `idle`, `listen`,
  `wave`, `invite`, `think`, `warn`, `nod`, `shake`, and `explain`, while
  rejecting non-allowlisted `dance` with HTTP 400. Earlier live MCP evidence
  exercised the same allowlisted backend tool path. The isolated Core27 test
  provider exercised the generated-provider route for idle, listen, and explain;
  timing-critical actions retained deterministic fallbacks. This does not
  qualify the gated real prompt-conditioned Horizon8 provider. An unsafe
  unknown profile value also failed closed to the diagnostic avatar rather
  than becoming an arbitrary asset path.
- The same sealed v27 binary selected Aoi only through
  `-FayCharacter=Aoi` and passed a four-turn rendered production qualification
  with 15.94 ms worst facial p95, normal audio cleanup, 3,004 KiB tail RSS
  growth, clean teardown, Fay survival, and post-run seal verification. No
  Aoi-specific C++ was required.
- A separate diagnostic—not the production soak—captured an allowlisted
  1280x720 Ada window frame and an eight-second H.264 clip while speech and a
  wave were active. The capture guard tied the one visible X11 window to the
  exact sealed executable, PID, start time, runtime log, reviewed profile, and
  real playback markers, recorded no desktop or audio, and revalidated the
  media before it was allowlisted on the private progress hub.

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
- Further visually tune the compiled and packaged deterministic procedural gesture
  fallback. It supplies character-neutral `wave`, `invite`, `think`, `warn`,
  and conversational arm/wrist poses when no reviewed montage is configured;
  compatible private montages retain precedence. `nod` and `shake` remain
  owned by the face driver's bounded head curves.
- Cache approved ARDY text embeddings after Meta Llama access is granted. The
  real provider currently reports degraded and returns 503 without them.
- Visually validate and tune the source-level semantic head-control mappings for
  `nod`, `shake`, `think`, and `warn`.
- Add optional reviewed MetaHuman-compatible body montages for more polished
  action performances. No licensed body montage is published or required by
  the procedural fallback.
- Tune gaze, breathing, idle motion, emotional range, lighting, LODs, and scene
  presentation for a polished long-running character experience.
- Assemble and validate a second reviewed female preset. Aoi already proves the
  no-character-specific-C++ portability requirement but is male in UE 5.8.
- Repeat the isolated malformed-envelope, stale/out-of-order sequence, and
  ARDY service kill/restart injections against the sealed v27 package. Earlier
  builds passed those recovery paths, but they remain separate from v27's
  completed production soak and must not interrupt the externally managed Fay
  process.
- Run a short CSV-enabled performance diagnostic at 720p and 1080p, then retain
  front/side motion review and an Aoi v27 comparison capture. CSV and capture
  overhead remain diagnostic-only and cannot replace the already-passing
  production qualification.
- Keep the free modular Casual Girl Fab character as a deferred private
  compatibility target. Reliability, MCP control, deterministic motion, and
  real ARDY activation take precedence; no Fab content belongs in this public
  repository.

## Publication boundary

The isolated source build uses private compatibility work against
Epic-licensed source. Publishing the Engine tree, its patches, MetaHuman
content, StreamingADA model, cooked packages, screenshots derived from licensed
content, or private validation logs would cross the repository boundary. This
repository contains only original project source, adapters, guards, and public
instructions.
