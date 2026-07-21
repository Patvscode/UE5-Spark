# Verified status

This page separates measured results from planned work. The latest evidence was
recorded on DGX Spark on 2026-07-20. The cooked package and all Epic-licensed
content remain private and are not part of this repository.

## Working end to end on DGX Spark

- UE 5.8's x86-64 graphical Editor and commandlets run through a pinned,
  rootless FEX userspace. This is the cooker and MetaHuman assembly environment;
  it does not install packages, register `binfmt_misc`, change services, or
  replace the NVIDIA driver.
- Epic's included female Ada preset was assembled as an Optimized / High
  MetaHuman and cooked for LinuxArm64 on the Spark.
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

- Visually validate and tune the source-level semantic head-control mappings for
  `nod`, `shake`, `think`, and `warn`.
- Add reviewed, MetaHuman-compatible body animations and explicit mappings for
  actions such as `wave` and `invite`. No body montages are included today.
- Tune gaze, breathing, idle motion, emotional range, lighting, LODs, and scene
  presentation for a polished long-running character experience.
- Turn the validated launch command into an optional user-level operational
  wrapper only after deciding how the avatar should be started and supervised.

## Publication boundary

The isolated source build uses private compatibility work against
Epic-licensed source. Publishing the Engine tree, its patches, MetaHuman
content, StreamingADA model, cooked packages, screenshots derived from licensed
content, or private validation logs would cross the repository boundary. This
repository contains only original project source, adapters, guards, and public
instructions.
