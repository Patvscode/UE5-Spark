# UE5-Spark

UE5-Spark is an unofficial, source-only deployment kit for running a packaged
Unreal Engine 5.8 digital-human application natively on NVIDIA DGX Spark. It
contains a minimal Unreal project and a Fay bridge for speech, text, sentiment,
semantic actions, and first-pass mouth movement.

> **Engineering-preview status:** the Linux ARM64 runtime, NVIDIA Vulkan path,
> and bridge compilation have been verified on DGX Spark. A cooked scene and
> MetaHuman have not yet been rendered there. The next required milestone is a
> Linux ARM64 cook from an editor-capable x86-64 host.

This repository does **not** redistribute Unreal Engine, MetaHuman assets,
Marketplace plugins, cooked packages, or private Epic source patches.

## What runs where

```text
One-time x86-64 Linux builder
  Unreal Engine 5.8 Editor/Cooker
              |
              | cook/package for LinuxArm64
              v
DGX Spark
  Packaged Unreal runtime  <---->  FayAvatarBridge
              |                       |
              +---- localhost --------+
                       Fay + LLM + ASR/TTS + MCP tools
```

The x86-64 machine manufactures the platform-specific assets once. The DGX
Spark runs the finished interactive application and all of the AI services.

## Verified status

| Capability | Status |
|---|---|
| UnrealBuildTool bootstraps natively on Spark ARM64 | Verified |
| Game module and `FayAvatarBridge` compile/link for Linux ARM64 | Verified |
| NVIDIA Vulkan initializes on the Spark | Verified |
| Engine/plugin/object-system startup on ARM64 | Verified |
| Cooked project scene renders on Spark | Next milestone |
| Free optimized MetaHuman renders on Spark | Not yet tested |
| End-to-end talking avatar loop | Not yet tested |
| Native ARM64 Unreal Editor/cooker | Experimental and not working |

See [the detailed status](docs/status.md) for the exact boundary.

## Why the full Editor is not currently running on Spark

The blocker is the development toolchain, not the Spark's rendering hardware:

- DGX Spark uses a 20-core ARM64 processor. NVIDIA documents its Blackwell GPU,
  ray-tracing cores, and 128 GB of unified memory in the
  [DGX Spark system overview](https://docs.nvidia.com/dgx/dgx-spark/system-overview.html).
- Epic exposes `LinuxArm64` as a deployment target, so a packaged application
  can be built for the Spark.
- Epic's current Linux development documentation says its supported/tested
  Linux libraries and toolchains are for `Linux-x86_64`. The Editor/cooker also
  depends on native helper programs and third-party libraries that are not all
  supplied for Linux ARM64. See Epic's
  [Linux development requirements](https://dev.epicgames.com/documentation/unreal-engine/linux-development-requirements-for-unreal-engine).
- A Game target cannot substitute for the cooker. Materials, textures, shaders,
  maps, meshes, rigs, and MetaHuman content need cooked Linux ARM64 platform
  data before a runtime can load them.

We proved that the ARM64 runtime reaches Unreal initialization and Vulkan, then
stops when it needs the missing cooked shader/material data. Fixing that inside
the Game target would mean porting a large portion of the Editor/cooker and its
native dependencies—not changing one project setting.

The practical route is therefore to cook once on x86-64 and run permanently on
the Spark. The [native Editor notes](docs/native-editor.md) preserve what was
learned without presenting the experiment as a supported workflow.

## Repository layout

```text
Project/FayAvatarRuntime/                 Minimal UE 5.8 project
  Plugins/FayAvatarBridge/                Source-only runtime bridge
  Source/FayAvatarRuntimeEditor.Target.cs x86-64 Editor/cooker target
scripts/cook-linux-arm64.sh               Guarded x86-64 BuildCookRun wrapper
scripts/verify-cooked-package.sh          Verify AArch64 executable and content
scripts/verify-spark.sh                   Read-only Spark/Vulkan preflight
scripts/run-cooked-package.sh             Guarded packaged-app launcher
tools/fay-avatar-smoke-test.py            Test Fay without Unreal
docs/                                     Architecture and deployment guides
```

## Quick path to the next milestone

1. On an x86-64 Linux machine, prepare an editor-capable Unreal Engine 5.8
   source or Installed Build that includes the `LinuxArm64` target.
2. Clone this repository and create a small project-owned map in
   `Project/FayAvatarRuntime`.
3. Build and cook:

   ```bash
   ./scripts/cook-linux-arm64.sh /path/to/UnrealEngine /path/to/archive
   ./scripts/verify-cooked-package.sh /path/to/archive
   ```

4. Copy the verified archive to a user-owned directory on the Spark.
5. On the Spark, run the read-only preflight and then the packaged launcher:

   ```bash
   ./scripts/verify-spark.sh
   ./scripts/run-cooked-package.sh /path/to/FayAvatarRuntime.sh
   ```

6. Prove the blank scene and bridge first; then add an optimized MetaHuman.

Full instructions are in [build and deploy](docs/build-and-deploy.md). A
temporary builder can be covered by new-user cloud credit; see
[the free-builder notes](docs/free-builder.md).

## Fay, MCP, and the avatar bridge

Fay remains a separate process. Its MCP clients/server, memory, LLM routing,
ASR, and TTS stay on the backend side. Unreal receives a small normalized avatar
event stream over WebSocket and downloads local WAV audio over HTTP:

```text
Fay HTTP/audio       http://127.0.0.1:5000
Fay avatar socket    ws://127.0.0.1:10002
```

The source-only bridge replaces paid transport/JSON/runtime-WAV plugins. It
exposes Blueprint events for connection health, message text, sentiment,
semantic actions, speech start/finish, optional visemes, and RMS mouth
amplitude. See [the Fay protocol](docs/fay-protocol.md).

The companion backend work is in the
[`agent/dgx-spark` branch of Patvscode/Fay](https://github.com/Patvscode/Fay/tree/agent/dgx-spark).

## Free character path

No character purchase is required. MetaHuman is included under Epic's standard
Unreal Engine license and is free under the revenue threshold described on the
[official MetaHuman license page](https://www.metahuman.com/license?lang=en-US).
The first test should use an included female preset assembled as **UE
Optimized**, with hair cards and conservative texture/LOD settings.

MetaHuman assets are deliberately absent from this public repository. Import
and assemble them through Epic on the licensed Editor host. See
[the MetaHuman plan](docs/metahuman.md).

## Safety

- The included Spark scripts do not use `sudo`, install packages, replace
  drivers, modify services, or alter DGX OS.
- Fay defaults to loopback-only URLs when it shares the Spark with Unreal.
- Repository checks reject Engine/build outputs, licensed asset locations,
  private-key markers, common token forms, and machine-specific paths. Review
  every public commit as an additional safeguard.
- Keep experimental engine work in a private Epic-authorized workspace.

## Licensing and trademarks

Original source in this repository is licensed under the [MIT License](LICENSE).
Unreal Engine, MetaHuman, NVIDIA software, and Fay are separate dependencies
under their own licenses. See [third-party boundaries](THIRD_PARTY.md).

This is an unofficial community project and is not affiliated with or endorsed
by Epic Games, NVIDIA, or the Fay maintainers.
