# Current state and handoff

This is the short operational checkpoint for the DGX Spark digital-human work.
It records what is actually working, what evidence supports it, what is still
missing, and the safest place to resume. Private packages, logs, credentials,
MetaHuman assets, and captured media are intentionally not stored in Git.

## Snapshot

- Recorded: 2026-07-22
- Source branch: `agent/dgx-spark-metahuman`
- Draft pull request: `Patvscode/UE5-Spark#1`
- Live-controller evidence source checkpoint: `0844863`
- Current package: sealed v29 native Linux ARM64, Ada and Aoi included; latest
  Ada production-qualified package, portrait/chest-up camera
- Current production character: Ada
- Replacement source candidate: exact `CasualGirl` / `UE5EpicArkit` profile,
  direct ARKit morph driver, package/cook guards, and capture/soak selection;
  vendor content is not acquired and no replacement binary exists yet
- Current motion service: real ARDY Horizon8 image `0.2.0`, protocol v1,
  three approved cached embeddings (`idle`, `listen`, `explain`)
- Current private controller: immersive live Unreal preview plus narrow chat and
  three-action proxy, validated at a 390 × 844 iPhone viewport
- Immediate rollback: sealed v28
- Long-run and measured-30-FPS baseline: sealed v28
- Older functional rollback: v27, with its documented uncapped-frame limitation

## Deployment boundary: live v29 versus source-only v30

The sealed v29 package is still the only deployed and qualified package. It
uses the protocol-v1 ARDY client and the legacy nineteen-bone adapter that
writes reconstructed component-space transforms after body evaluation. That
writer relies on unsupported mutable access to finalized transforms and does
not perform a source-rest/target-rest IK retarget. Its limited portrait evidence
does not rule out ancestor propagation into the head/face or incorrect
arm/hand/leg axes. Treat it as a rollback-capable prototype, not the motion
architecture to extend.

The current source tree contains a v30 candidate, but it has not been cooked,
packaged, copied to Spark, activated, or visually qualified. The candidate adds:

- ARDY protocol v2 at `POST /v2/poses`, with the exact reviewed ARDY revision,
  Core27 hierarchy/joint order, right-handed +X-left/+Y-up/+Z-forward basis,
  local XYZW rotations, global 27-joint positions, explicit contact order, and
  quaternion-hemisphere continuity;
- a hidden Core27 source skeletal mesh feeding a reviewed Unreal IK Retargeter
  from a post-process Animation Blueprint, instead of mutating finalized Body
  transforms;
- explicit preservation of the Body's ordinary animation class, StreamingADA
  face/head ownership, neck/head exclusion, and the existing finger pose;
- one shared reviewed nine-motion catalog: `idle`, `listen`, `explain`, `wave`,
  `jog_in_place`, `run_in_place`, `jumping_jacks`, `stretch`, and
  `dance_relaxed`;
- a fail-closed free-text movement director that may use a local Qwen model only
  to suggest one catalog ID; deterministic code owns duration, intensity, root
  mode, and whether the current renderer may receive it; and
- content-free wardrobe/profile boundaries plus a separate fail-closed ARKit
  facial adapter for the pending Fab Casual Girl.

Source tests establish contract behavior only. They are not evidence of a v30
binary, real nine-embedding ARDY run, correct IK assets, natural full-body
motion, or long-running reliability.

## What works now

The live v29 packaged path runs on DGX Spark:

```text
Fay conversation / LLM / ASR / TTS / MCP
                    |
                    | local WAV + avatar events
                    v
Native ARM64 Unreal 5.8 package
  - Ada or Aoi reviewed character profile
  - local StreamingADA facial solve
  - MetaHuman audio playback and rendering
  - allowlisted deterministic gestures
  - real ARDY Horizon8 body motion
  - automatic baked-idle fallback and provider re-detection
```

Verified capabilities:

- Ada and Aoi are selected through reviewed profile IDs; arbitrary assets and
  unknown profiles fail closed.
- Ada renders with skin, hair cards, garments, lighting, normal audio, and local
  learned facial speech motion.
- StreamingADA converts each speech turn to the complete expected 50 Hz facial
  solve cadence and publishes 251 MetaHuman raw controls through `FayAudio`.
- Fay semantic actions reach Unreal through the constrained avatar bridge.
- `idle`, `listen`, and `explain` can use the real Horizon8 provider.
- `wave`, `invite`, `think`, and `warn` retain deterministic timing-safe
  fallbacks; `nod` and `shake` use bounded head curves.
- The legacy v29 ARDY adapter maps nineteen reviewed body bones, including
  pelvis/root, spine, shoulders/arms, thighs, calves, feet, and toes. Its
  unsupported late component-space writer is the defect the v30 IK-retarget
  candidate is intended to remove.
- ARDY does not own the face, neck, head, or sparse finger endpoints. This keeps
  facial speech and the body provider from competing for the same controls.
- Provider loss crossfades to baked idle. A guarded external activator supplies
  a replacement when required, and Unreal automatically requalifies the returned
  real provider without restarting Fay or the packaged application.
- The same source and package route work for Aoi without character-specific C++.
- The package is created entirely on Spark: the x86-64 UE 5.8 Editor/cooker runs
  through rootless FEX and the shipped runtime runs natively on ARM64.
- The private controller displays fresh 960 × 540 frames from the exact native
  Unreal window without opening another network listener. The loopback BFF is
  exposed only through the existing private Tailscale HTTPS boundary.
- The deployed mobile UI uses the live renderer as the full-screen stage.
  Conversation and setup controls are dismissible sheets, and the movement
  controls stay in a compact bottom shelf.
- `Explain` and `Listen` dispatch to the real ARDY provider while it is healthy;
  `Wave` is the deterministic real-time fallback. The UI falls back honestly to
  retained evidence media if the renderer or frame producer is unavailable.
- Deployed text chat has a resource-aware prototype path: a small local Qwen
  model writes the reply, then Fay performs TTS and sends the audio to Unreal
  for playback and StreamingADA lip motion. Hidden reasoning tags are removed
  before display or speech. The much larger 35B model is not required for this
  trial path.

## Current v29 evidence

The package identity is sealed:

- Package seal SHA-256:
  `592cd46a35a1a8708acaeb4cc072c772d031af9f0d34c4b1b8a3773156b4786a`
- ARM64 executable SHA-256:
  `75b024c4867cc866511122b44de1ff89a82f459f134640a49b9449fd643cb9ee`

Aoi's retained v29 portability bundle
`rendered-v29-aoi-real-ardy-5turn-20260722T0011Z` completed five turns in
302 seconds with 8.74 ms worst facial p95, 13,764 KiB tail RSS growth, five
dormancy wakes, zero cancellations, and zero runtime/kernel/action failures.

Fresh Ada production gate:

- 303 seconds, five speech turns, 1280x720 native Vulkan rendering
- Five exact facial summaries and five normal playback/cleanup sequences
- 7.85 ms worst facial p95 against a 20 ms limit
- RSS 2,189,848 KiB first, 2,166,724 KiB last, 2,189,848 KiB maximum
- 2,892 KiB measured tail growth against a 131,072 KiB limit
- 53,552,328 KiB minimum unified `MemAvailable`
- 20 percent peak measured GPU utilization
- Zero facial-frame, frame-policy, watchdog, bridge, action, runtime, or kernel
  failures
- Clean owned teardown, unchanged Fay/ARDY identities, restored Voxtral,
  reverified package seal, and no remaining Unreal process

Controlled live ARDY recovery diagnostic:

- Started a ten-second generated `explain` action during a 9.68-second speech
  turn.
- Stopped only the exact captured project ARDY container with a bounded stop.
- Unreal observed provider loss, entered baked-idle fallback, and kept speech and
  facial animation running.
- Facial p95 for the interrupted turn was 7.46 ms.
- The guarded activator published a new real Horizon8 provider.
- Unreal requalified it and completed generated `explain`, `idle`, and `listen`.
- The operational audit found zero rejected poses or degraded transitions from
  recovered readiness through the final gesture and normal `PreExit`.
- Cleanup revalidated the replacement provider twice, preserved the original
  Fay process/listeners, restored Voxtral, rechecked the package, and left zero
  Unreal processes or cleanup errors.

The recovery run is diagnostic evidence. The fresh five-turn gate is the v29
production qualification. V28's separate 20-turn endurance and exact
6,000-frame 30.001596 FPS diagnostic remain the longer-term baselines.

Private-controller live check at source checkpoint `0844863`:

- Controller status reported Fay, ARDY, native renderer, and fresh live stream
  ready at the same time.
- The browser decoded the live 960 × 540 JPEG stage at 390 × 844 with no
  horizontal or vertical page overflow.
- A real `explain` request reached Unreal, used the ARDY provider for its bounded
  duration, crossfaded to baked idle, and left Ada's face attached and visible.
- A text request returned the exact requested English response, Fay accepted it
  for transparent speech, and Unreal completed two seconds of audio playback
  with 110 facial frames and 15.24 ms p95 solve time.
- Only the small reviewed chat model remained loaded after the check, leaving
  approximately 56.5 GiB of unified memory available while Unreal, ARDY, Fay,
  the frame producer, and the controller were active.

## Runtime ownership and safety boundary

Keep these rules for every future change:

- Do not modify DGX OS, NVIDIA drivers, CUDA, display services, or system units.
- Do not stop, restart, or reconfigure Fay from project launchers.
- Normal production gates observe ARDY; they do not manage it.
- Only the explicit recovery diagnostic may stop the exact captured project
  ARDY container and activate its sealed replacement.
- Only the fixed allowlisted Voxtral user unit may be paused for a rendered gate,
  and every exit path must restore and health-check it.
- Bind ARDY and new control services to loopback. Use Tailscale as the private
  remote access boundary rather than exposing backend ports globally.
- Keep credentials, checkpoints, embeddings, cooked packages, logs, and media
  outside Git.
- Back up passing source changes to GitHub before syncing them to Spark.
- Keep v28 intact until v29 has also accumulated a comparable endurance run.

## Credential state

The three live protocol-v1 ARDY prompt embeddings were generated and sealed
privately. Ordinary ARDY runtime does not need the Hugging Face token or the
Meta Llama encoder cache. Temporary authorization/cache cleanup is intentionally
separate: preserve models, checkpoints, embeddings, and the default Hugging
Face login; quarantine project OAuth material first, and finalize deletion only
after the user revokes the connected application.

Protocol v2 uses embedding-manifest schema 2 and requires nine private cached
embeddings. Those six additional reviewed embeddings have not been generated or
activated. The live three-file cache is intentionally incompatible with the v2
image and remains untouched for rollback.

## What is not finished

- The current private controller services are a trial deployment, not yet a
  reboot-persistent supervised product. Startup must retain the same ownership,
  memory, exact-process, loopback, and private-file guards.
- The lightweight trial chat path does not yet preserve Fay's full agent memory
  or MCP planning. It deliberately keeps the native avatar usable alongside
  ARDY; the full planner remains a separate resource profile.
- The free-text movement director and its optional local classifier exist only
  in source. Direct alias matching is deterministic; an LLM response is merely
  an advisory catalog ID and cannot supply poses, asset paths, timing, root
  motion, or arbitrary ARDY text. Staged motions must not be presented as live.
- Current Ada framing is portrait/chest-up. It proves face and upper-body motion
  but does not visually prove the lower-body retarget path.
- Source now contains sealed per-character `FullBody` camera presets; a new
  package plus wide front/side capture is still required.
- Live ARDY v1 accepts only three generated behaviors. Candidate v2 remains
  limited to the nine reviewed cached behaviors; arbitrary prompts still do not
  enter Unreal.
- Detailed fingers need reviewed hand poses or another compatible provider.
- Head/neck behavior and emotional/gaze polish still need visual tuning.
- Aoi proves portability but is male in the installed UE 5.8 preset set. The
  second female source profile/face adapter is ready, but its licensed model,
  retarget assets, and Spark package remain pending.
- The free Fab Casual Girl is not installed. The source profile remains
  `pending_asset_audit`; its wardrobe controls are disabled, and full undress is
  prohibited until every hidden body region, material, and LOD is manually
  verified as complete.

## Next implementation order

1. Commit and back up the passing source candidate before any Spark sync. Keep
   the v29 package, ARDY `0.2.0` image/cache, and v28 rollback immutable.
2. Build the new `0.3.0` ARDY image in isolation, generate and hash-seal all nine
   schema-2 embeddings, update the activator/qualification gates for the v2
   endpoint and count, then pass mock and real canaries without replacing the
   live v1 provider prematurely.
3. In the UE 5.8 Editor, create and review the Core27 source mesh, IK Rig/IK
   Retargeter, target post-process AnimBP, retarget profile, and one sealed
   binding on both Ada and Aoi. A missing or changed asset must fail to baked
   idle; it must never re-enable the legacy writer.
4. Compile, cook, package, deep-verify, and seal a new v30 LinuxArm64 package.
   Cold-launch it against the v2 canary before any production switch.
5. Capture wide front and side full-body clips for every new catalog motion.
   Reject wrong limb sides, palm inversion, elbow/knee hyperextension, root
   jumps, foot sliding, face/head displacement, finger collapse, or facial
   interruption.
6. Run v30 speech overlap, malformed/stale pose, provider-loss/recovery,
   Ada/Aoi portability, five-turn rendered qualification, and 30-minute mixed-
   motion soak gates. Promote only after clean fallback and teardown.
7. Deploy the controller movement director only after its advertised
   `rendererPackaged` flags match the sealed v30 package. Keep large planner
   models out of the trial resource profile unless measured coexistence passes.
8. Do not register the web client as a second `User` on Fay's avatar WebSocket;
   that could mask the real Unreal renderer. Proxy only the reviewed control and
   sanitized status surfaces.
9. Run mobile Safari and desktop browser acceptance through Tailscale, including
   reconnection, microphone permission, media playback, and safe failure states.
10. Add guarded startup/recovery for the lightweight model and three transient
   controller services without modifying system drivers, CUDA, DGX OS, or Fay.
11. Restore full Fay memory/MCP planning as an explicit resource profile after
   measuring whether it can coexist with the full-body package.
12. Acquire Casual Girl through the user's Fab library, import it only into an
    isolated private project root, run the asset and complete-body/LOD audits,
    compile/tune the existing Apple-ARKit adapter, build its Epic-skeleton
    retarget assets, and enable wardrobe controls only after native LinuxArm64
    qualification.

## Resume checklist

Before resuming work:

1. Confirm the Git branch is clean and matches its GitHub remote.
2. Verify the v29 package seal and native executable hashes above.
3. Confirm Fay process identity/listeners without changing it.
4. Confirm the fixed live ARDY container is sealed image `0.2.0`, protocol v1,
   healthy on loopback, and reports exactly three embeddings. Do not point v29
   at a v2 service.
5. Confirm the fixed Voxtral user unit is active and no packaged Unreal process
   remains.
6. Use a new private evidence directory for every gate or media capture.
7. Re-run repository checks before any source sync, then run the ARM64-focused
   suite and a fresh-clone repository suite on Spark.

## Publication boundary

This repository may contain original source, tests, guards, architecture, and
sanitized evidence summaries. It must not contain Unreal Engine source or
binaries, MetaHuman/StreamingADA/Fab assets, cooked packages, ARDY checkpoints,
cached embeddings, private media, raw private logs, hostnames, private or
non-loopback listener addresses, OAuth artifacts, or credentials. Documented
loopback contracts remain part of the public architecture.
