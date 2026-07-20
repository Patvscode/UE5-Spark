# Build and deploy

This is the shortest supported path to the first visible Spark scene. It keeps
all system-level changes away from the DGX Spark.

## 1. Prepare the x86-64 builder

Use an x86-64 Linux machine with:

- Ubuntu 22.04 or another Unreal-compatible distribution
- At least 32 GB RAM; 64 GB is more comfortable
- At least 300 GB free storage; 500 GB is safer for Engine source, dependencies,
  build intermediates, Derived Data Cache, project assets, and an archive
- No GPU requirement for a headless cook; a GPU is useful only if editing and
  visually inspecting the project on the same host
- An Epic account authorized to access Unreal Engine source/content

Epic lists current Linux development requirements in
[its official documentation](https://dev.epicgames.com/documentation/unreal-engine/linux-development-requirements-for-unreal-engine).

Prepare an editor-capable Unreal Engine **5.8** source or Installed Build that
includes the `LinuxArm64` target. Epic's Installed Build system exposes
`WithLinuxArm64`; see the
[Installed Build guide](https://dev.epicgames.com/documentation/en-us/unreal-engine/installed-build-reference-guide-for-unreal-engine).

Do not upload Epic source or dependencies to this repository.

## 2. Validate the public project

```bash
git clone https://github.com/Patvscode/UE5-Spark.git
cd UE5-Spark
./scripts/check-repository.sh
```

Open `Project/FayAvatarRuntime/FayAvatarRuntime.uproject` with the matching
Editor. Create a small project-owned map, make it the Game Default Map, and
confirm the `FayAvatarBridge` plugin is enabled.

For the first package, keep the scene intentionally small. Do not import a
MetaHuman yet.

## 3. Cook and verify Linux ARM64

```bash
./scripts/cook-linux-arm64.sh /path/to/UnrealEngine /path/to/archive
./scripts/verify-cooked-package.sh /path/to/archive
```

The cook wrapper refuses to run on a non-Linux or non-x86-64 host, checks that
the Engine reports version 5.8, and requires an empty archive directory to
prevent stale results. The verifier requires both:

- the exact staged `FayAvatarRuntime/Binaries/Linux/FayAvatarRuntime` file to be
  an `ELF 64-bit` `ARM aarch64` executable; and
- at least one `.pak` or `.utoc` under the staged project's `Content/Paks`.

Do not continue if either check fails.

## 4. Copy only the finished package

Copy the verified archive into a new user-owned directory on the Spark, for
example `~/Applications/UE5-Spark/`. Do not copy the Engine checkout, builder
cache, or private patch workspace.

No root access is required for the packaged application.

## 5. Read-only Spark preflight

From this repository on the Spark:

```bash
./scripts/verify-spark.sh
```

The script checks Linux ARM64, normal-user execution, NVIDIA driver access, and
Vulkan enumeration. It prints memory/filesystem information. It never invokes
`sudo`, installs a package, changes a driver, or edits a service.

If `vulkaninfo` is absent, stop and decide separately whether installing the
diagnostic package is acceptable; the script will not do it automatically.

## 6. Launch the cooked application

```bash
./scripts/run-cooked-package.sh \
  ~/Applications/UE5-Spark/FayAvatarRuntime.sh
```

The launcher validates that an AArch64 ELF and cooked content exist beside the
package launcher before starting Unreal with `-vulkan -log`.

First prove:

1. A window or fullscreen frame appears through NVIDIA Vulkan.
2. The project-owned map is loaded.
3. Audio output works.
4. Repeated launch/exit is clean.

## 7. Validate Fay separately

Install the smoke-test-only dependency in an isolated Python environment:

```bash
python3 -m venv .venv-tools
.venv-tools/bin/pip install -r tools/requirements.txt
.venv-tools/bin/python tools/fay-avatar-smoke-test.py
```

This registers a temporary renderer, submits a chat turn, and verifies that the
returned WAV URL is fetchable. It lets backend failures be separated from
Unreal failures.

## 8. Add animation in controlled stages

1. Basic skeletal character
2. Idle, blink, breathing, and one gesture montage
3. Fay connection and ordered speech playback
4. RMS amplitude mapped to jaw-open
5. Sentiment/action mapped to expression and body gestures
6. UE Optimized MetaHuman
7. Higher-quality facial animation

Each stage should remain independently testable before the next is added.
