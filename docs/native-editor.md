# Native ARM64 Editor status

## Short answer

The Spark can run the packaged Unreal application. It does not currently have a
supported, complete native Linux ARM64 Unreal Editor/cooker workflow.

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

## Experimental alternatives

- FEX or QEMU can emulate an x86-64 userspace on ARM64 without replacing DGX OS,
  but Unreal cooking is CPU-, filesystem-, process-, and memory-intensive. It
  launches helpers such as ShaderCompileWorker, making emulation slow and
  fragile.
- A bounded FEX launch test is reasonable only after a compatible prebuilt
  x86-64 Editor/cooker is available. It is not the reliability path for the
  first MetaHuman.

Private engine-port experiments should remain in an Epic-authorized workspace.
This public repository intentionally contains no Engine patches or source
context.

The project's `FayAvatarRuntimeEditor.Target.cs` is a normal Editor target for
the supported **x86-64 builder**. Its presence does not opt the Editor into
Linux ARM64 or claim native Spark support.
