# Verified status

This page separates measured results from planned work. The latest evidence was
recorded on DGX Spark through 2026-07-22. The cooked package and all Epic-licensed
content remain private and are not part of this repository.

## Current deployment boundary

- **Live and qualified:** sealed native ARM64 v29, portrait/chest-up Ada and Aoi,
  ARDY image `0.2.0` with protocol v1 and three cached motions, plus the deployed
  three-action private controller. V28 remains the immediate and long-run
  rollback baseline.
- **Known v29 motion defect:** the legacy nineteen-bone adapter mutates finalized
  component-space Body transforms through unsupported access. It does not use a
  source-rest/target-rest IK retarget and portrait evidence cannot qualify lower
  body, hand orientation, or ancestor isolation from the head/face.
- **Source-only v30 candidate:** protocol v2, exact Core27 source identity,
  global joint positions and contacts, quaternion continuity, a hidden Core27
  source mesh, reviewed IK Retargeter/post-process contract, nine-motion shared
  catalog, free-text movement director, and content-free wardrobe boundary.
- **Not yet done:** no v2 container or nine-embedding cache has been qualified,
  no v30 content assets/package have been cooked, no candidate code has replaced
  the live v29 runtime, and no full-body visual/reliability gate has passed.
- **Fab candidate:** Casual Girl is not present or imported in this workspace and
  remains `pending_asset_audit`. Source now contains its exact sealed character
  profile, a separate direct ARKit morph driver, adapter-aware cook/package
  verification, and Casual Girl capture/soak selection. The ARKit runtime and
  character-selection translation units compile cleanly as Linux ARM64 objects
  on the Spark. They have not been linked against an imported vendor character
  or cooked into a replacement package; wardrobe controls and full undress
  remain disabled.

Source tests prove parsing and fail-closed contracts only. They do not prove a
real ARDY v2 generation, Unreal asset binding, natural motion, correct retarget,
or Spark runtime stability.

## Working end to end on DGX Spark (live and retained evidence)

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
- A later boot CSV made the v27 frame-rate limitation measurable: 12,000 frames
  completed in 70.536429 seconds, or 170.125 FPS. The per-frame `FrameTime`
  values summed to the same capture duration. V27's config had requested 30 FPS,
  but the standard GameUserSettings value subsequently reset `t.MaxFPS` to zero.
  V27 remains the prior production-qualified functional rollback, not a verified
  30 FPS performance baseline.
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
- The retained protocol-v1 strict mock pose service passed schema, sequence,
  allowlist, Core27,
  neck/head-exclusion, and coordinate-mapping tests. Approved access to the
  gated encoder was then used once in isolation to seal the `idle`, `listen`,
  and `explain` embeddings. The real Horizon8 provider loads those three
  embeddings without a runtime network request, credential, or text encoder.
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
- The sealed dual-character v15 package added repeated neutral Live Link
  bootstrap frames to remove a measured cold-start scheduler race and introduced
  the intended 30 FPS config value. The later v27 CSV proved that
  GameUserSettings neutralized that value, so the historical v15 result is not
  frame-cap evidence. Its first cold launch
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
- Ada then passed the prior sealed 1,802-second / 20-turn rendered production soak.
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

## Current verified v29 result

This section records valid v29 speech, recovery, process, and bounded portrait
evidence. It does not certify the legacy body writer as a correct IK retarget or
prove natural full-body motion. V29 remains live while the source-only v30
replacement is built and gated.

- The sealed dual-character v29 package has package-seal digest
  `592cd46a35a1a8708acaeb4cc072c772d031af9f0d34c4b1b8a3773156b4786a`
  and native AArch64 executable SHA-256
  `75b024c4867cc866511122b44de1ff89a82f459f134640a49b9449fd643cb9ee`.
  Ada and Aoi each passed earlier five-turn rendered runs against the real
  Horizon8 provider. The retained Aoi bundle
  `rendered-v29-aoi-real-ardy-5turn-20260722T0011Z` completed five turns in
  302 seconds with 8.74 ms worst facial p95, 13,764 KiB tail RSS growth, five
  dormancy wakes, zero cancellations, and zero runtime/kernel/action failures.
  The same package then completed the guarded recovery and fresh Ada gates below.
- The rendered diagnostic `rendered-v29-ardy-recovery-20260722T0313Z`
  started a ten-second generated `explain` action during a speech turn, stopped
  only the exact captured project ARDY container, observed service loss and a
  completed bounded baked-idle fallback, and kept facial speech running at
  7.46 ms p95. A new sealed real provider became ready, after which Unreal
  completed generated `explain`, `idle`, and `listen` actions.
- The post-recovery operational audit ended at the first normal Unreal
  `PreExit` after the final `listen` completion. It recorded zero rejected pose
  batches, unavailable transitions, generated fallbacks, or neutral-explain
  fallbacks in that live window. The later teardown-only unavailable message is
  expected because the ARDY client clears readiness during `EndPlay`; final
  ARDY identity/health and Unreal absence are checked separately.
- Recovery cleanup validated the replacement endpoint twice, preserved Fay's
  exact process and listeners, restored the fixed Voxtral user unit, rechecked
  the package, and reported zero cleanup errors. This is diagnostic recovery
  evidence and is not labeled production qualification.
- The independent production bundle
  `rendered-v29-ada-fresh-production-20260722T031759Z` completed five Ada
  turns in 303 seconds. All five facial summaries, normal audio completions,
  allocator releases, and delayed collections passed. Worst facial p95 was
  7.85 ms; Unreal RSS moved from 2,189,848 KiB to 2,166,724 KiB, reached a
  2,189,848 KiB maximum, and grew 2,892 KiB across the tail. Minimum
  `MemAvailable` was 53,552,328 KiB and peak GPU utilization was 20 percent.
- Facial-frame, frame-policy, watchdog, bridge, procedural-action, runtime, and
  kernel failure counts were zero. Owned teardown, Fay/ARDY continuity,
  Voxtral restoration, package verification, and Unreal absence all passed.
- V29 is the latest Ada production-passing package. V28 remains the retained
  extended endurance, Aoi portability, measured-30-FPS baseline, and immediate
  rollback until v29 accumulates matching long-run breadth.

## Retained verified v28 result

- The private v28 native ARM64 package is sealed. Its recorded package-seal
  digest is
  `653d14a1205a25bbd7c5f434c998919c3d5284af40717d0c267294909b67139f`,
  and the native AArch64 executable SHA-256 begins with `b1184ec`.
- Ada passed v28's rendered four-turn production qualification in 241 seconds.
  Worst facial p95 was 17.03 ms, maximum Unreal RSS was 2,132,444 KiB, tail RSS
  growth was 8,176 KiB, and minimum unified `MemAvailable` was 58,918,672 KiB.
- The run verified the project-owned `FayGameUserSettings` policy exactly once,
  enforced the reviewed frame-rate policy exactly once, and recorded zero policy
  violations. These markers prove policy selection and enforcement; the guarded
  CSV gate remains the separate measurement of effective frame rate.
- Dormancy history contained five entries, four accepted-message wakes, and no
  preparation cancellation. Runtime, kernel, and action failure counts were all
  zero. Controlled teardown completed cleanly, the externally managed Fay and
  ARDY services remained unchanged, and the separately managed Voxtral service
  was restored.
- Ada's separate production endurance gate passed 20 turns over 1,803 seconds.
  Unreal RSS moved from 2,119,152 KiB in the first sample to 2,117,968 KiB in the
  last, reached a 2,123,648 KiB maximum, and grew only 6,328 KiB across the
  measured tail at a 6.10 KiB/s slope. Minimum `MemAvailable` was 58,743,872 KiB.
  GPU utilization peaked briefly at 95 percent; no three-sample excessive-GPU
  condition occurred.
- All 20 endurance turns produced facial summaries, normal playbacks, allocator
  releases, and delayed collections. Worst facial p95 was 6.56 ms. Dormancy
  history contained 21 entries, 20 accepted-message wakes, and no preparation
  cancellation. Policy, action, runtime, and kernel failure counts were zero;
  controlled teardown, package-seal verification, and service-continuity checks
  all passed.
- Aoi passed its own 241-second / four-turn rendered qualification. Maximum
  Unreal RSS was 2,177,596 KiB, tail growth was 2,512 KiB, and minimum
  `MemAvailable` was 58,668,572 KiB. All four facial summaries completed with
  6.54 ms worst p95; dormancy recorded five entries and four wakes. Frame-policy
  drift, runtime failures, and kernel failures were zero, and the outer guarded
  wrapper passed.
- The guarded diagnostic captured exactly 6,000 CSV frames, trimmed 300 startup
  and 30 ending frames, and analyzed 5,670 frames. Mean `FrameTime` was
  33.33156 ms, average rate was 30.001596 FPS, p95 was 38.4833 ms, and p99 was
  39.5503 ms. The complete capture lasted 202.981269 seconds; summed frame time
  differed from metadata by only 0.0149 ms. The retained CSV SHA-256 is
  `d7ce10963ab418dc30ecbc090918795a55b6c77605d24e5dd4e873d569dad9b1`.
  Diagnostic teardown and the outer service-restoration checks passed cleanly.
- V28 remains the retained 20-turn endurance, Aoi portability, and measured
  30 FPS baseline, plus the immediate rollback for v29. V27 remains intact as
  the older functional rollback, with its known uncapped frame-rate limitation
  documented above.
- A separate passing 90-second, one-turn diagnostic captured Ada's exact
  1280x720 client as a PNG and an eight-second, 30 FPS MP4 for the private
  progress hub. The outer gate still passed teardown, service restoration, and
  process-identity checks; capture overhead is not part of the production or CSV
  results above.

## Live protocol-v1 ARDY qualification

- Exact access to ARDY's original Meta Llama 3 text encoder was used once in an
  isolated CPU-only generator. It emitted only the reviewed `idle`, `listen`,
  and `explain` embeddings. Each private NPZ and the manifest are hash-sealed;
  ordinary runtime receives neither the Hugging Face token nor the 16 GiB text
  encoder cache.
- The guarded real-provider activation first ran 30 batches / 240 frames on a
  retained canary, enough to cross the complete 192-frame history boundary.
  Canary steady latency was 86.602 ms mean, 173.577 ms p95, and 215.318 ms
  maximum. It then repeated the same 30-batch qualification on the fixed
  production endpoint: 83.775 ms mean, 155.470 ms p95, and 210.926 ms maximum.
- Ada subsequently passed a 302-second / five-turn rendered production gate.
  Wave, invite, think, and warn used their deterministic fallbacks. Explain used
  the real generated provider for 7.20 seconds and explicitly returned to baked
  idle. Five facial summaries completed with 8.39 ms worst p95, and all five
  speech playbacks, allocator releases, and delayed collections completed.
- Tail Unreal RSS growth was 1,408 KiB, peak GPU utilization was 78 percent,
  and minimum `MemAvailable` was 53,318,704 KiB. Runtime, kernel, bridge,
  procedural-action, frame-policy, and teardown failures were all zero.
- The exact real ARDY container and host process identities remained unchanged,
  restart count stayed zero, final ARDY p95 was 151.57 ms, Fay retained its
  original PID/listeners, Voxtral restored, no Unreal process remained, and the
  v28 package seal still matched.

These figures qualify image `0.2.0`, protocol v1, and the three-file schema-1
cache. They are regression targets for v2, not evidence for image `0.3.0` or the
nine-motion schema-2 cache.

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

- Back up the passing integrated source before syncing it to Spark. Preserve the
  sealed v29 package, live ARDY `0.2.0` image and schema-1 cache, and v28 rollback.
- The guarded activator now implements a fail-closed `0.2.0` protocol-v1 to
  `0.3.0` protocol-v2 migration. It requires the live real v1 provider, runs an
  exact 30-batch v1 preflight, captures its immutable image and read-only model
  mount, content-seals both the v1 rollback and isolated v2 candidate trees,
  qualifies v2 on `127.0.0.1:18777`, then rechecks v1 before cutover. Any
  post-cutover failure recreates the real v1 provider from its captured image ID
  and model root and repeats the strict v1 qualification. It will not substitute
  the old `0.1.0` mock and will not migrate when production is absent. This guard
  is source-tested but has not been executed against the live Spark.
- Update the recovery and package gates that still assume absent-service mock
  recovery or protocol-v1 production. Keep explicit v1 rollback checks rather
  than silently reinterpreting v1 as v2.
- Build ARDY `0.3.0` in an isolated container, generate all nine reviewed
  schema-2 embeddings through the credentialed one-shot path, remove the token/
  encoder from normal runtime, and pass mock plus real 30-batch canaries at
  `/v2/poses`. The current three-file cache must not be overwritten.
- In the UE 5.8 Editor, create and inspect the Core27 source skeleton/mesh, source
  and target IK Rigs, IK Retargeter, Ada/Aoi target post-process AnimBP, retarget
  profile, and exactly one binding per reviewed character. Runtime must fail to
  baked idle when any class, property, hierarchy, or asset identity differs.
- Compile and package a new native ARM64 v30 candidate without the unsupported
  finalized-transform writer. Deep-verify and seal it before testing against the
  v2 canary; never point live v29 at the incompatible service.
- Capture full-body front and side views for `idle`, `listen`, `explain`, `wave`,
  `jog_in_place`, `run_in_place`, `jumping_jacks`, `stretch`, and
  `dance_relaxed`. Reject swapped sides, palm inversion, rigid shoulders,
  elbow/knee hyperextension, root jumps, foot sliding, finger collapse, face/
  head displacement, or interrupted StreamingADA speech.
- Run speech/motion overlap, malformed and stale pose batches, provider kill/
  restart, baked fallback, recovery, Ada/Aoi portability, five-turn rendered
  production, and 30-minute mixed-motion soak gates. Record memory, frame rate,
  pose-buffer health, facial p95, process ownership, and clean teardown.
- Deploy the free-text movement director only when each catalog item's
  `rendererPackaged` flag matches the sealed v30 contents. Deterministic aliases
  remain primary; optional Qwen classification can return only an advisory ID.
  A staged response must never claim that movement occurred.
- Keep the lightweight planner/chat resource profile separate from larger 9B or
  35B experiments until measured unified-memory coexistence with Unreal, ARDY,
  Fay, speech, and the preview path passes.
- Acquire/import Casual Girl only through the user's Fab library into an
  isolated private content root. Audit UE 5.8 and LinuxArm64 compatibility,
  skeleton/physics/plugins, every body region and LOD beneath clothing, ARKit
  morphs, and component identities before promoting its profile.
- Compile and tune the new Casual Girl Apple-ARKit source adapter against its
  audited morph names, then build its Epic-skeleton ARDY retarget and sealed
  wardrobe mapping. Keep wardrobe disabled and
  `allowFullyUnclothed=false` unless a manual complete-body audit explicitly
  passes. No Fab content or private asset paths belong in Git.
- After body correctness is established, tune gaze, breathing, emotion,
  detailed hand poses, lighting, LODs, clothing/hair physics, and presentation.

## Publication boundary

The isolated source build uses private compatibility work against
Epic-licensed source. Publishing the Engine tree, its patches, MetaHuman
content, StreamingADA model, cooked packages, screenshots derived from licensed
content, or private validation logs would cross the repository boundary. This
repository contains only original project source, adapters, guards, and public
instructions.
