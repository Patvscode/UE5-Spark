# Native ARM64 Editor status

## Short answer

The Spark can run the packaged Unreal application natively. It does not have a
supported, complete **native ARM64** Editor workflow, but the x86-64 UE 5.8
Editor and cooker now run on it experimentally through rootless FEX.

Those are different targets:

- **Game runtime:** loads already-cooked platform data and renders/interacts.
- **Editor/cooker:** imports source assets, builds meshes/textures/materials,
  compiles global/project shaders, runs editor-only tools, and emits packages.

## What was attempted

A source build was used to probe native ARM64 UnrealBuildTool, the Game target,
shader libraries, Vulkan initialization, and an experimental Editor target. The
Game and bridge compiled. The Editor target reached native dependency blockers,
including editor-only third-party libraries without ARM64 Linux binaries.

An uncooked Game target was also tried. It could initialize substantial Engine
infrastructure but could not construct the cooked texture, material, mesh, and
shader data needed by a runtime.

## Why this is not a project-setting fix

Epic currently states that it supports, tests, and supplies Linux development
libraries/toolchains for Linux x86-64. The Editor contains many more native
programs and dependencies than the runtime, including ShaderCompileWorker,
asset importers, build/cook commandlets, and editor-only plugins.

Making the full Editor reliable on Spark would require an ongoing ARM64 port of
those components and replacements for any binary-only dependency. It is a
separate engine-porting project, not an avatar adapter.

## Working experimental alternative

- Rootless FEX runs the x86-64 Editor and ShaderCompileWorker without replacing
  DGX OS or installing a system `binfmt_misc` handler.
- The x86 commandlet completed a LinuxArm64 cook on the Spark. Native ARM64
  UnrealBuildTool, AutomationTool, and UnrealPak then built and packaged the
  Game target.
- Vulkan forwarding and a pinned NVIDIA ICD created a real X11 swapchain. The
  graphical Editor rendered the Open World viewport for a bounded three-minute
  stability test.
- The tested FEX path requires conservative settings: two reported cores and
  single-threaded Unreal rendering. The normal render/RHI thread split is not
  stable in this configuration.

Private engine-port experiments should remain in an Epic-authorized workspace.
This public repository intentionally contains no Engine patches or source
context.

The project's `FayAvatarRuntimeEditor.Target.cs` remains an **x86-64** Editor
target. Its presence does not opt the Editor into LinuxArm64. See the
[Spark FEX guide](spark-fex-cooker.md) for the isolated setup and launcher.
