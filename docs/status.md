# Verified status

This page separates measured results from planned work. The evidence below was
recorded on DGX Spark on 2026-07-20.

## Verified on DGX Spark

- The host reports Linux `aarch64` and runs DGX OS with NVIDIA's ARM64 driver
  stack.
- Unreal Engine 5.8.0 source at commit
  `7deeb413d3dc1fc034f48d1aacc0861301829d32` bootstrapped
  UnrealBuildTool natively on ARM64.
- The earlier `FayAvatarRuntime` Game module and source-only `FayAvatarBridge`
  plugin compiled and linked as Linux ARM64 code during the native source
  experiment. This verification predates `FayMetaHumanRuntime`.
- ARM64 ShaderConductor and DXC shared libraries loaded, and the required
  SPIR-V reflection code built.
- Unreal initialized the Spark's NVIDIA Vulkan device, SM6 feature path,
  ray-tracing extensions, and large unified-memory device heap.
- A diagnostic uncooked Game target mounted the plugin and reached Unreal's
  shader, target-platform, plugin, and object-system initialization paths.
- A rootless FEX 2607 environment ran the x86-64 UE 5.8 Editor and commandlets
  without installing packages, registering `binfmt_misc`, changing services,
  or replacing the NVIDIA driver.
- FEX Vulkan forwarding selected the native NVIDIA GB10 and driver. A guest
  `vkcube` presented to the Spark's physical X11 display.
- The graphical Editor created an NVIDIA Vulkan swapchain and rendered the Open
  World viewport. With two reported cores, `-onethread`, and `-norhithread`, it
  remained operational until the intentional three-minute safety stop.
- The x86 Editor commandlet cooked the project for LinuxArm64: 195 packages and
  roughly 15,000 material shaders completed with zero cook errors.
- Native ARM64 UnrealBuildTool, AutomationTool, the Game target, and UnrealPak
  completed the build/stage/package path. The resulting archive contained an
  AArch64 executable plus nonempty cooked Pak/IoStore content.
- The native package rendered through the NVIDIA Vulkan SM6 path and played
  audio on the Spark.
- A live Fay WebSocket event was accepted by the packaged runtime; its local
  PCM WAV was downloaded, decoded, and played through completion.
- The hardened project, bridge, and `FayMetaHumanRuntime` compiled under the
  x86-64 UE 5.8 Editor target through FEX and under the native LinuxArm64 Game
  target. The latter emitted an AArch64 executable and target receipt.
- The read-only MetaHuman preflight found the UE 5.8 helper/subsystem, included
  Ada preset, required enums, empty destination, and unchanged dirty-package
  state. It created and saved no character assets.

## Compile-verified, runtime not yet verified

`FayMetaHumanRuntime` now contains a direct adapter intended to convert decoded
Fay PCM to 16 kHz mono, run Epic's local StreamingADA model with
`NNERuntimeORTCpu`, convert the learned GUI output to 251 MetaHuman raw controls,
and publish a local Live Link Basic subject named `FayAudio`. It also maps Fay
sentiment/action metadata to solver mood input.

This source was added after the verified diagnostic package above. Its x86-64
Editor and native LinuxArm64 Game compiles now pass, but it has not yet passed a
fresh MetaHuman-aware LinuxArm64 cook/package, Spark model initialization, or
visible Ada-animation test. None of those outcomes is implied by compilation or
the earlier bridge/audio verification.

## Important boundary

The earlier uncooked diagnostic target stopped because no cooked Global shader
library existed. That result established that a Game target cannot replace a
cooker. The later FEX commandlet supplied the missing LinuxArm64 platform data
and removed that runtime blocker; no unsupported uncooked-asset workaround is
used in the delivered package.

The graphical Editor also has a measured compatibility boundary. Its normal
render/RHI thread split rendered an initial frame and then entered the signal
handler under FEX. Conservative single-threaded rendering completed the full
bounded test and is now the adapter default. This is an experimental workflow,
not an Epic-supported native ARM64 Editor installation.

## Not yet verified

- A generated MetaHuman Blueprint assembled from the included Ada preset
- LinuxArm64 cook and runtime validation of the enabled MetaHuman dependency tree
- MetaHuman face/body rendering quality and performance
- StreamingADA model loading and solve performance through `NNERuntimeORTCpu`
- `FayAudio` Live Link delivery of all 251 raw controls to the actual face rig
- Learned mouth, expression, mood, and blink motion synchronized with Fay audio
- Fay semantic-action mapping to visible body gestures; the required body
  animations and mappings are not implemented

## Why this repository omits Engine patches and generated assets

The isolated source build uses private compatibility work against
Epic-licensed source. Publishing that Engine tree, its patches, MetaHuman
content, StreamingADA model, cooked packages, or generated character assets
would cross licensing and repository-safety boundaries. This repository
contains only the original project source, adapters, guards, and reproducible
public setup instructions.

## Next pass/fail milestone

Success now requires the included free female MetaHuman preset to be assembled
through the Editor-only helper, kept outside Git, cooked for LinuxArm64 with the
local StreamingADA model, and rendered by the native package. The same run must
initialize the local solver, publish `FayAudio`, and visibly synchronize learned
mouth/expression motion with speech. Body gestures are a later pass/fail gate
because their animations and mappings do not yet exist. Until those checks
pass, this is a working Unreal/Fay runtime foundation—not yet a completed
digital human.
