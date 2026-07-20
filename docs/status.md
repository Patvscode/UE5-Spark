# Verified status

This page separates measured results from planned work. The evidence below was
recorded during the DGX Spark investigation completed on 2026-07-20.

## Verified on DGX Spark

- The host reports Linux `aarch64` and runs DGX OS with NVIDIA's ARM64 driver
  stack.
- Unreal Engine 5.8.0 source at commit
  `7deeb413d3dc1fc034f48d1aacc0861301829d32` bootstrapped
  UnrealBuildTool natively on ARM64.
- The `FayAvatarRuntime` Game module and source-only `FayAvatarBridge` plugin
  compiled and linked as Linux ARM64 code during the native source experiment.
- ARM64 ShaderConductor and DXC shared libraries loaded, and the required
  SPIR-V reflection code built.
- Unreal initialized the Spark's NVIDIA Vulkan device, SM6 feature path,
  ray-tracing extensions, and large unified-memory device heap.
- A diagnostic uncooked Game target mounted the plugin and reached Unreal's
  shader, target-platform, plugin, and object-system initialization paths.

## Exact stopping point

The diagnostic target was a compiler/runtime probe, not a cooker. With the real
Vulkan renderer it stopped because no cooked Global shader library existed.
With NullRHI it progressed farther, then failed while Unreal initialized default
materials and textures without cooked runtime exports.

The Engine asset source files were present. What was absent was their
Linux-ARM64 cooked platform data. Textures, materials, meshes, maps, shaders,
and MetaHuman assets all cross the same cook boundary.

## Not yet verified

- A cooked project-owned scene rendering on the Spark
- Display and audio from the same packaged build
- A live Fay WebSocket message received inside the packaged Unreal runtime
- WAV playback and amplitude-driven jaw motion on a skeletal character
- MetaHuman face/body rendering and performance
- Production facial curves or neural audio-to-face animation

## Why this repository omits the failed targets

The native-Editor and uncooked-Game targets depended on a private patch series
against Epic-licensed source. Neither target cooked content or displayed an
avatar. Publishing them would both expose the wrong workflow and risk leaking
licensed Engine-source context. This public repository keeps only the normal
Game target required by the supported deploy path.

## Next pass/fail milestone

Success is a package produced on an editor-capable x86-64 Unreal 5.8 host that:

1. Contains an AArch64 ELF and `.pak` or `.utoc` cooked content.
2. Passes `scripts/verify-cooked-package.sh`.
3. Launches with NVIDIA Vulkan on the Spark.
4. Displays the project map and plays test audio.
5. Connects to Fay on `ws://127.0.0.1:10002`.

Only after those five checks should MetaHuman content be added.

The public packaging target uses standard Unreal build settings so it remains
compatible with an x86-64 source or Installed Build. Its complete cook is part
of this next milestone and is not claimed as already verified.
