# Current state and handoff

This is the short operational checkpoint for the DGX Spark digital-human work.
It records what is actually working, what evidence supports it, what is still
missing, and the safest place to resume. Private packages, logs, credentials,
MetaHuman assets, and captured media are intentionally not stored in Git.

## Snapshot

- Recorded: 2026-07-22
- Source branch: `agent/dgx-spark-metahuman`
- Draft pull request: `Patvscode/UE5-Spark#1`
- Last runtime-safety source checkpoint before this document: `b273278`
- Current package: sealed v29 native Linux ARM64, Ada and Aoi included; latest
  Ada production-qualified package
- Current production character: Ada
- Current motion service: real ARDY Horizon8, three approved cached embeddings
- Immediate rollback: sealed v28
- Long-run and measured-30-FPS baseline: sealed v28
- Older functional rollback: v27, with its documented uncapped-frame limitation

## What works now

The complete packaged path runs on DGX Spark:

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
- The ARDY adapter maps nineteen reviewed body bones, including pelvis/root,
  spine, shoulders/arms, thighs, calves, feet, and toes.
- ARDY does not own the face, neck, head, or sparse finger endpoints. This keeps
  facial speech and the body provider from competing for the same controls.
- Provider loss crossfades to baked idle. A guarded external activator supplies
  a replacement when required, and Unreal automatically requalifies the returned
  real provider without restarting Fay or the packaged application.
- The same source and package route work for Aoi without character-specific C++.
- The package is created entirely on Spark: the x86-64 UE 5.8 Editor/cooker runs
  through rootless FEX and the shipped runtime runs natively on ARM64.

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

The three approved ARDY prompt embeddings were generated and sealed privately.
Ordinary ARDY runtime does not need the Hugging Face token or the Meta Llama
encoder cache. Temporary authorization/cache cleanup is intentionally separate:
preserve models, checkpoints, embeddings, and the default Hugging Face login;
quarantine project OAuth material first, and finalize deletion only after the
user revokes the connected application.

## What is not finished

- The private iPhone/desktop web controller is not built yet. Product design
  selection must happen before implementation; the next step presents exactly
  three visual directions.
- The existing private media page is a progress viewer, not the interaction UI.
- Current Ada framing is portrait/chest-up. It proves face and upper-body motion
  but does not visually prove the lower-body retarget path.
- A reviewed `FullBody` camera preset plus wide front/side capture is required.
- ARDY's current public runtime interface is deliberately limited to approved
  behavior names. Arbitrary prompts do not enter Unreal.
- Detailed fingers need reviewed hand poses or another compatible provider.
- Head/neck behavior and emotional/gaze polish still need visual tuning.
- Aoi proves portability but is male in the installed UE 5.8 preset set. A
  second reviewed female character remains pending.
- The deferred free Fab character is not part of the reliability-critical path.

## Next implementation order

1. Present three visual options for a responsive private controller and obtain
   an explicit selection before scaffolding UI code.
2. Build a loopback-only project BFF and expose only the UI through private
   Tailscale HTTPS.
3. Provide live avatar video, push-to-talk/text input, connection/voice state,
   and allowlisted gesture buttons. Keep diagnostics and milestone media
   secondary.
4. Do not register the web client as a second `User` on Fay's avatar WebSocket;
   that could mask the real Unreal renderer. Proxy only the reviewed control and
   sanitized status surfaces.
5. Add reviewed `Portrait` and `FullBody` presets to each character profile and
   select only by `-FayCameraFraming=<reviewed-id>`. Never accept transforms or
   FOV values from command line, MCP, or the web UI. Seal the available framing
   IDs in the package manifest, recook as a new package, and capture front plus
   side motion before calling lower-body quality proven.
6. Run mobile Safari and desktop browser acceptance through Tailscale, including
   reconnection, microphone permission, media playback, and safe failure states.
7. Run a longer v29 endurance gate after UI/camera changes settle; preserve v28
   until it passes.

## Resume checklist

Before resuming work:

1. Confirm the Git branch is clean and matches its GitHub remote.
2. Verify the v29 package seal and native executable hashes above.
3. Confirm Fay process identity/listeners without changing it.
4. Confirm the fixed ARDY container is the sealed Horizon8 image, healthy on
   loopback, and reports exactly three embeddings.
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
