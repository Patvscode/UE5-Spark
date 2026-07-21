# UE5-Spark

UE5-Spark is an unofficial, source-only deployment kit for running a packaged
Unreal Engine 5.8 digital-human application natively on NVIDIA DGX Spark. It
contains a minimal Unreal project, a Fay speech/event bridge, and source for a
local MetaHuman facial-animation adapter.

> **Engineering-preview status:** the character-independent v12 pipeline has
> rebuilt the free female Ada MetaHuman, cooked it from a reviewed profile, and
> run it as a sealed native Linux ARM64 package on DGX Spark. Ada renders,
> speaks, and animates through the local StreamingADA model while the guarded
> Core27 body adapter consumes an isolated loopback pose service. The same Spark runs
> the x86-64 UE 5.8 Editor/cooker through rootless FEX. Fay audio/WebSocket
> integration, MCP readiness, learned facial motion, background-window
> operation, package integrity, generated-motion recovery, and repeated
> launch/teardown have been verified. Real ARDY prompt conditioning remains
> gated on approved Meta Llama access; deterministic gesture authoring and a
> second female-preset polish pass are the next implementation stages.

This repository does **not** redistribute Unreal Engine, MetaHuman assets,
Marketplace plugins, cooked packages, or private Epic source patches.

## What runs where

```text
DGX Spark
  x86-64 UE 5.8 Editor/Cooker through rootless FEX
              |
              | cook/package for LinuxArm64
              v
  Native packaged Unreal runtime <----> FayAvatarBridge
              |                              |
              +----------- localhost --------+
                         Fay + LLM + ASR/TTS + MCP tools
```

The Spark can now perform both roles. The development tools run as x86-64
processes through FEX, while the delivered application runs as native ARM64.
An ordinary x86-64 Linux builder remains an alternative, but it is no longer
required for this project.

## Verified status

| Capability | Status |
|---|---|
| UnrealBuildTool bootstraps natively on Spark ARM64 | Verified |
| Game, bridge, and direct facial adapter compile/link for Linux ARM64 | Verified; native AArch64 executable and receipt emitted |
| NVIDIA Vulkan initializes on the Spark | Verified |
| x86-64 UE 5.8 Editor/cooker runs through rootless FEX | Verified, experimental |
| Linux ARM64 cook/package completes entirely on Spark | Verified |
| Cooked project scene, display, and audio run on Spark | Verified |
| Live Fay WebSocket, WAV download, and playback | Verified |
| Fay HTTP/avatar and MCP administration/SSE readiness | Verified through guarded private-listener discovery |
| Direct local StreamingADA facial adapter | Verified in the native package: 81 solver curves, 251 raw controls, `FayAudio` Live Link subject |
| Free optimized Ada MetaHuman renders on Spark | Verified with skin, hair, clothing, and portrait lighting |
| MetaHuman learned speech motion | Verified visibly and at the complete 50 Hz solve cadence |
| Reviewed character profiles and repeatable profile-driven cooking | Verified with Ada and Aoi in sealed v13; unknown profiles fail closed |
| Fay-driven body gestures | Core27 transport/retarget/fallback verified with mock provider; polished clips pending |
| Native ARM64 Unreal Editor/cooker | Not required; x86 Editor uses FEX |

See [the detailed status](docs/status.md) for the exact boundary.

## How the Editor runs on Spark

The full graphical Editor now runs on the Spark as an x86-64 Linux process
through rootless FEX. This keeps Epic's normal Editor modules and third-party
libraries intact while forwarding Vulkan to the native ARM64 NVIDIA driver.
The packaged application itself does not use emulation.

The split is necessary because:

- DGX Spark uses a 20-core ARM64 processor. NVIDIA documents its Blackwell GPU,
  ray-tracing cores, and 128 GB of unified memory in the
  [DGX Spark system overview](https://docs.nvidia.com/dgx/dgx-spark/system-overview.html).
- Epic exposes `LinuxArm64` as a deployment target, so a packaged application
  can be built for the Spark.
- Epic's current Linux development documentation says its supported/tested
  Linux libraries and toolchains are for `Linux-x86_64`. See Epic's
  [Linux development requirements](https://dev.epicgames.com/documentation/unreal-engine/linux-development-requirements-for-unreal-engine).
- A Game target cannot substitute for the cooker. Materials, textures, shaders,
  maps, meshes, rigs, and MetaHuman content need cooked Linux ARM64 platform
  data before a runtime can load them.

The adapter pins the NVIDIA ICD and defaults to two emulated cores with
single-threaded Unreal rendering. That mode created an X11 Vulkan swapchain,
rendered the Open World viewport, compiled shaders, and stayed alive until its
intentional three-minute safety stop. The ordinary render/RHI thread split is
not stable under the tested FEX configuration, so the conservative mode is the
working default. See [the Spark FEX cooker](docs/spark-fex-cooker.md) and the
[native Editor notes](docs/native-editor.md).

## Repository layout

```text
Project/FayAvatarRuntime/                 Minimal UE 5.8 project
  Plugins/FayAvatarBridge/                Source-only runtime bridge
  Plugins/FayBodyMotion/                  Allowlisted baked/ARDY motion boundary
  Plugins/FayMetaHumanRuntime/            Source-only local facial adapter
  Plugins/FayMetaHumanEditorTools/        Editor-only Ada assembly helper
  Source/FayAvatarRuntimeEditor.Target.cs x86-64 Editor/cooker target
scripts/cook-linux-arm64.sh               Guarded x86-64 BuildCookRun wrapper
scripts/setup-fex-rootless.sh              Rootless x86 userspace on Spark
scripts/setup-native-cross-toolchain.sh    Native ARM clang -> x86 UE adapter
scripts/create-isolated-engine-tree.sh     Guarded hard-link build tree
scripts/build-spark-x86-cooker.sh          Bounded x86 cooker source build
scripts/configure-native-scw-adapter.sh    Optional native shader-worker bridge
scripts/cook-linux-arm64-fex.sh            Fresh fingerprinted FEX content cook
scripts/package-linux-arm64-hybrid.sh      Native ARM64 build/stage/package
scripts/character-profiles.py              Validate/select sealed character profiles
scripts/verify-linux-arm64-cook.sh         Verify selected character/model cook inputs
scripts/verify-cooked-package.sh           Deep-check and hash-seal the package
scripts/verify-spark.sh                   Read-only Spark/Vulkan preflight
scripts/run-cooked-package.sh             Guarded packaged-app launcher
scripts/run-spark-digital-human.sh        Discover Fay/MCP and launch the stack
scripts/build-ardy-container.sh           Build isolated ARM64 PyTorch service
scripts/run-ardy-container.sh             Run loopback-only hardened pose service
services/ardy/                            Strict Core27 protocol and providers
tools/fay-avatar-smoke-test.py            Test Fay without Unreal
tools/progress_hub.py                     Private allowlisted milestone/media page
docs/                                     Architecture and deployment guides
```

The included UE 5.8 `Aoi` preset is male in the tested installation. It is kept
as the second v13 portability fixture because it proved that the runtime,
speech adapter, and body retargeter are character-independent. Ada remains the
female demonstration character; another reviewed female preset can use the
same guarded builder and profile path.

For the optional Tailscale progress page and the guarded 30-minute reliability
runner, see [reliability and private progress](docs/reliability-and-progress.md).

## Quick path

1. In a dedicated user-owned Spark workspace, prepare the pinned rootless FEX
   bundle, Epic toolchain, and isolated UE 5.8 source build described in
   [the Spark FEX guide](docs/spark-fex-cooker.md).
2. Build the x86 Editor/cooker, then run the read-only MetaHuman preflight.
3. If Epic authentication is not already valid, complete it interactively in
   the graphical Editor. Run the Editor-only helper to assemble Ada locally.
4. Confirm the generated `/Game/FayMetaHumans` files remain ignored. On Spark,
   run `cook-linux-arm64-fex.sh --character Ada` to create only a fresh
   fingerprinted loose cook,
   then run `package-linux-arm64-hybrid.sh` with a new empty archive path. The
   FEX step never creates the final package; native ARM64 tools do that.
5. Verify the archive. Packaging records the reviewed profile IDs and
   deep-inspects Ada, MetaHuman common content,
   the StreamingADA model, Ada's Interchange garment material dependency, ARM64
   ONNX Runtime, and Editor-helper exclusion before writing a
   relative-path/hash seal. The normal verifier rechecks that seal:

   ```bash
   ./scripts/verify-cooked-package.sh /path/to/archive
   ```

   The runtime selects only a reviewed packaged profile with
   `-FayCharacter=Ada`. Unknown IDs and arbitrary asset paths fail closed to the
   diagnostic avatar.

6. Run the read-only Spark preflight and native packaged launcher:

   ```bash
   ./scripts/verify-spark.sh
   ./scripts/run-cooked-package.sh /path/to/FayAvatarRuntime-Arm64.sh
   ```

   When the existing Fay and MCP services should be checked first, use the
   stack launcher instead:

   ```bash
   ./scripts/run-spark-digital-human.sh \
     /path/to/FayAvatarRuntime-Arm64.sh
   ```

   The guarded normal-user wrapper discovers and probes existing non-global
   listeners without printing or baking their addresses, exports the runtime
   `FAY_*` endpoints, and delegates to `run-cooked-package.sh`. It does not
   start, stop, or reconfigure a service or change system configuration. Set
   `UE5_SPARK_REQUIRE_MCP=0` only when the MCP readiness checks are intentionally
   unnecessary.

Full instructions are in [build and deploy](docs/build-and-deploy.md). The
experimental all-Spark source-build route is documented in
[Spark FEX cooker](docs/spark-fex-cooker.md). A temporary builder can be
covered by new-user cloud credit; see [the free-builder notes](docs/free-builder.md).

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

The runtime adapter takes the bridge's decoded PCM, converts it to 16 kHz mono
audio, runs Epic's local StreamingADA model through `NNERuntimeORTCpu`, converts
the result into 251 MetaHuman raw controls, and publishes them on a local Live
Link Basic subject named `FayAudio`. The native package has visibly driven Ada's
face while Fay speech played, including the complete expected 50 Hz solve frame
count while the window was minimized. Semantic action events reach Unreal and
the source contains conservative head-control mappings for a small action set,
but those head gestures have not been visually verified. Authored body mappings
and montages for actions such as wave and invite are not implemented.

The `FayBodyMotion` plugin routes the same semantic intent through a strict
allowlist and interchangeable baked/ARDY providers. Its ARDY client validates
versioned Core27 batches from `127.0.0.1:8777`, buffers eight 20 FPS frames, and
interpolates poses at render rate. Generated motion deliberately remains behind
the retarget safety gate until the MetaHuman post-evaluation rig proves it does
not replace or fight the verified StreamingADA Body/Face path.

The [MCP integration boundary](docs/mcp-integration.md) explains how Fay owns
tools and credentials while Unreal receives presentation-only events.

The companion backend work is in the
[`agent/dgx-spark` branch of Patvscode/Fay](https://github.com/Patvscode/Fay/tree/agent/dgx-spark).

## Free character path

No character purchase is required. MetaHuman is included under Epic's standard
Unreal Engine license and is free under the revenue threshold described on the
[official MetaHuman license page](https://www.metahuman.com/license?lang=en-US).
The first test should use an included female preset assembled as **UE
Optimized**, with hair cards and conservative texture/LOD settings.

MetaHuman assets and the StreamingADA model are deliberately absent from this
public repository. They are Epic-licensed content obtained from the user's
authorized Unreal installation, assembled/cooked locally, and never uploaded to
this repository or its releases. See [the MetaHuman plan](docs/metahuman.md).

## Safety

- The included Spark scripts do not use `sudo`, install packages, replace
  drivers, modify services, or alter DGX OS.
- The rootless FEX runner isolates its installed files and state paths, but it
  is not a container or filesystem sandbox; it inherits the invoking user's
  home-directory access and should run only trusted Epic/project inputs.
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
