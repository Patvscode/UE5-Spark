# Experimental Spark-local cooker

This is the bounded fallback for keeping the Unreal cook on DGX Spark. It runs
Epic's **x86-64** Linux Editor commandlet with FEX on the Spark's ARM64 CPU. It
does not attempt to turn the Engine into a native ARM64 Editor.

## What is and is not isolated

The setup scripts keep the downloaded FEX bundle, its x86-64 RootFS, FEX state,
Unreal's explicitly configured local Derived Data Cache, and project logs below
one user-selected workspace. They do not use `sudo`, register `binfmt_misc`,
install packages, change the NVIDIA driver, edit a service, or write to a
system directory.

This is privilege isolation, not a container or filesystem sandbox. The runner
inherits `HOME`, the ordinary XDG variables, the current directory, and the
invoking user's filesystem permissions. Run only trusted Epic and project
inputs, and use a dedicated user-owned workspace. A command can still write
outside that workspace anywhere the invoking user could normally write.

FEX portable mode is important here. Without a system `binfmt_misc` handler,
FEX handles a guest `execve` by re-executing its own interpreter. This is what
allows UnrealEditor-Cmd to launch x86-64 helpers such as ShaderCompileWorker.

## Inputs that are not redistributable here

The repository cannot provide Epic's Editor or MetaHuman content. Sign in at
the official [Unreal Engine Linux download](https://www.unrealengine.com/linux)
and obtain the Unreal Engine **5.8 x86-64 Linux** archive under your Epic
license.

Before proceeding, the extracted build must contain all three of these:

- `Engine/Binaries/Linux/UnrealEditor` (or `UnrealEditor-Cmd` when supplied)
- `Engine/Binaries/Linux/ShaderCompileWorker`
- a compiled `LinuxArm64` target-platform module under
  `Engine/Binaries/Linux`

The third item is decisive. If it is absent, the binary Editor can start but it
cannot cook for the Spark. Epic's Installed Build option is
`WithLinuxArm64=true`.

There is also an experimental source-build route for the Spark. It is pinned to
the tested Unreal Engine 5.8.0 base revision
`7deeb413d3dc1fc034f48d1aacc0861301829d32`; it is not a generic fresh-checkout
builder. The source tree must already have the licensed Spark preparation used
during the investigation: native AArch64 .NET and LLVM 20.1.8 under
`.spark-tools`, plus the private Engine compatibility work needed to bootstrap
that toolchain. This repository cannot redistribute those Epic-source changes.

The public adapter combines Epic's checksum-pinned v26 x86-64 sysroot with the
prepared native ARM64 clang. Native clang performs the expensive compilation
while the resulting x86-64 Editor and commandlets run through FEX. The scripts
fail early if the exact UE revision, native-tool profile, or generated build
profile does not match. Presence of those inputs is a prerequisite, not work
performed by these public scripts.

## Pinned rootless setup

Choose a user-owned directory with at least 250 GB free for the Editor, project,
DDC, cook output, and safety margin. Then run:

```bash
cooker_workspace="$PWD/../ue5-spark-cooker"
./scripts/setup-fex-rootless.sh "$cooker_workspace"
./scripts/run-fex-rootless.sh "$cooker_workspace" -- /usr/bin/uname -m
```

The expected architecture is `x86_64`.

The setup pins official FEX 2607 for ARMv8.4 and FEX's official Ubuntu 24.04
x86-64 RootFS. It verifies the package SHA-256 and the RootFS XXH64 before
extracting either one.

## Graphical Vulkan gate

FEX's Vulkan files being present is not sufficient by itself. The Vulkan entry
in FEX's thunk database must also be enabled. The rootless runner passes
[`scripts/fex-vulkan-thunks.json`](../scripts/fex-vulkan-thunks.json) through
`FEX_THUNKCONFIG` for that purpose. Without this activation, the x86-64 guest
loads its ordinary Mesa Vulkan loader and commonly reports only `llvmpipe`,
with failed probes from guest drivers such as `dzn`.

Before starting the graphical Editor, prove the forwarding path with the
guest's `vulkaninfo`:

```bash
DISPLAY=:1 \
VK_DRIVER_FILES=/usr/share/vulkan/icd.d/nvidia_icd.json \
./scripts/run-fex-rootless.sh \
  "$cooker_workspace" -- /usr/bin/vulkaninfo --summary
```

`VK_DRIVER_FILES` makes this diagnostic deterministic by asking the native
Vulkan loader to use only the Spark's NVIDIA manifest. The output must name the
NVIDIA GB10. Stop if it reports only `llvmpipe`, `dzn`, or another software or
guest driver.

Then prove actual X11 presentation with the guest's small Vulkan cube. A
rotating cube must appear on the Spark's physical display; close it after the
check:

```bash
DISPLAY=:1 \
XAUTHORITY=/run/user/$(id -u)/gdm/Xauthority \
VK_DRIVER_FILES=/usr/share/vulkan/icd.d/nvidia_icd.json \
./scripts/run-fex-rootless.sh "$cooker_workspace" -- \
  /usr/bin/vkcube --width 640 --height 480
```

Do not copy the ARM64 NVIDIA ICD into the guest RootFS and do not install a
proprietary x86-64 NVIDIA userspace. With the thunk enabled, FEX overlays the
guest's `libvulkan.so.1` with its x86-64 guest thunk; the matching ARM64 host
thunk opens the Spark's native Vulkan loader and native NVIDIA driver. Both the
x86-64 guest X11 libraries and ARM64 host X11 libraries are still required for
window-system integration.

After the gate passes, use the graphical adapter for the first bounded Editor
launch:

```bash
DISPLAY=:1 \
XAUTHORITY=/run/user/$(id -u)/gdm/Xauthority \
UE5_SPARK_EDITOR_TIMEOUT=30m \
./scripts/run-fex-editor.sh \
  "$cooker_workspace" \
  /absolute/path/to/UnrealEngine \
  "$PWD/Project/FayAvatarRuntime/FayAvatarRuntime.uproject"
```

The adapter pins the native NVIDIA ICD and defaults to two reported cores with
single-threaded Unreal rendering. That conservative combination completed the
Editor startup, created an X11 Vulkan swapchain, rendered the Open World
viewport, compiled shaders, and remained alive until a three-minute intentional
safety stop on the tested Spark. The ordinary render/RHI thread split rendered
one frame but then entered Unreal's signal handler under FEX. Keep safe mode on
for real work. `UE5_SPARK_EDITOR_SAFE_MODE=0` is available only for bounded
compatibility experiments; `UE5_SPARK_EDITOR_CORES` accepts one through eight.

This is still an FEX compatibility test, not a supported Epic Editor
configuration. Passing `vulkaninfo` proves loader and device enumeration; the
Editor must separately prove instance creation, presentation, shader
compilation, and the Vulkan features it requests. An open
[FEX library-forwarding issue](https://github.com/FEX-Emu/FEX/issues/2173#issuecomment-3814539488)
includes a DGX Spark report of one Wine/Proton Vulkan application failing only
with thunks enabled. That is not evidence that native Linux Unreal will fail,
but it is evidence that the application-level gate cannot be skipped.

## MetaHuman preflight and first sign-in

Run the read-only MetaHuman preflight before generating project content. It
loads the included Ada preset, checks the Editor subsystem and project helper's
Python reflection, verifies the UE 5.8 rig/pipeline enums, and confirms that it
did not change the Editor's dirty-package lists. It deliberately fails if
`/Game/FayMetaHumans` is not empty, so use it before the first assembly rather
than as a post-generation health check.

```bash
DISPLAY=:1 \
XAUTHORITY=/run/user/$(id -u)/gdm/Xauthority \
UE5_SPARK_EDITOR_UNATTENDED=1 \
UE5_SPARK_EDITOR_TIMEOUT=10m \
./scripts/run-fex-editor.sh \
  "$cooker_workspace" \
  /absolute/path/to/UnrealEngine \
  "$PWD/Project/FayAvatarRuntime/FayAvatarRuntime.uproject" \
  -- \
  "-ExecutePythonScript=$PWD/scripts/metahuman-preflight.py" \
  -ScriptErrorsAreFatal \
  -NoMetaHumanAccountPortalLoginFallback
```

Success ends with `MH_PREFLIGHT_COMPLETE_OK`. The probe never creates, saves,
deletes, or overwrites an asset and does not contact MetaHuman cloud services.
The normal Editor still writes generated logs and cache data below its existing
workspace locations.

MetaHuman's first cloud auto-rig request uses Epic's graphical Account Portal
when no persistent sign-in exists. The Linux EOS SDK opens that portal through
the guest's `/usr/bin/xdg-open`; the pinned minimal FEX RootFS does not include
that command. Install this repository's narrow portal adapter into the
user-owned guest RootFS:

```bash
./scripts/configure-fex-xdg-open.sh "$cooker_workspace"
```

The installer does not use `sudo` or modify the Spark host's `/usr/bin`. It
refuses an unexpected existing guest `xdg-open`. Its runtime adapter accepts
only one `http://` or `https://` URI, passes it without printing it to the
desktop's `org.freedesktop.portal.OpenURI` D-Bus service, and suppresses command
output so an authentication URI cannot enter the Editor log through the
adapter. A normal graphical desktop session and its session D-Bus must already
be active.

With the user present at the Spark display, run the guarded Ada helper. Do not
add `-unattended` or `-NoMetaHumanAccountPortalLoginFallback` on the first run:

```bash
DISPLAY=:1 \
XAUTHORITY=/run/user/$(id -u)/gdm/Xauthority \
XDG_RUNTIME_DIR=/run/user/$(id -u) \
DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus \
UE5_SPARK_EDITOR_TIMEOUT=none \
./scripts/run-fex-editor.sh \
  "$cooker_workspace" \
  /absolute/path/to/UnrealEngine \
  "$PWD/Project/FayAvatarRuntime/FayAvatarRuntime.uproject" \
  -- \
  "-ExecutePythonScript=$PWD/Project/FayAvatarRuntime/Plugins/FayMetaHumanEditorTools/Scripts/build_ada.py" \
  -ScriptErrorsAreFatal
```

Complete Epic sign-in only in the browser window opened by the desktop portal.
Never put an Epic email, password, exchange code, or token in a command line,
configuration file, or repository. Once persistent authentication has been
proven, unattended retries should add
`-NoMetaHumanAccountPortalLoginFallback` so missing or expired authentication
fails instead of attempting to open a browser.

If the Editor build does not already bundle the v26 Linux toolchain, install
Epic's official copy in the same isolated workspace:

```bash
./scripts/setup-unreal-toolchain-rootless.sh "$cooker_workspace"
```

This adds about 1.6 GB of download and 3.4 GB extracted. The compiler itself is
x86-64, runs under FEX, and contains the AArch64 target/sysroot used for the
small project-specific build step.

## Build the x86-64 cooker on Spark

If a complete UE 5.8 x86-64 Editor is not already available, prepare Epic's
v26 toolchain and a separate Engine build tree. The following commands require
the exact prepared source profile described above:

```bash
./scripts/setup-native-cross-toolchain.sh \
  "$cooker_workspace" /path/to/UnrealEngine-5.8-source

./scripts/create-isolated-engine-tree.sh \
  /path/to/UnrealEngine-5.8-source \
  "$cooker_workspace/engine-build/UnrealEngine-5.8-x86-cooker"

# In the private Epic-authorized workspace, apply the licensed
# TargetPlatform/Turnkey compatibility adjustment to the isolated tree.
# The public builder verifies that profile but cannot distribute the patch.

UE5_SPARK_BUILD_JOBS=2 ./scripts/build-spark-x86-cooker.sh \
  "$cooker_workspace" \
  "$cooker_workspace/engine-build/UnrealEngine-5.8-x86-cooker" \
  "$PWD/Project/FayAvatarRuntime/FayAvatarRuntime.uproject"
```

The isolation script rejects nested source/destination paths, records the exact
source revision in a non-secret profile file, and omits Git metadata. It
hard-links immutable Engine source and third-party inputs, makes a real copy of
every `Binaries` directory and `Engine/Programs`, excludes generated
`Intermediate` and `Saved` directories at all depths, and creates fresh Engine
root write directories. Only the generated `Engine/DerivedDataCache` path is
excluded; the real `Engine/Source/Developer/DerivedDataCache` source module is
retained. Do not run `Setup.sh` or `GenerateProjectFiles.sh` in the isolated
tree because those operations are outside the hard-link safety boundary.

The builder deliberately stops after each gate: a tiny x86-64 program,
ShaderCompileWorker, UnrealPak, and finally the project Editor target. It uses
two compile actions by default and accepts only one through four via
`UE5_SPARK_BUILD_JOBS`.

After the ordinary x86 ShaderCompileWorker passes, an optional hybrid probe can
put a native ARM64 worker in the project's preferred lookup location:

```bash
./scripts/configure-native-scw-adapter.sh \
  "$PWD/Project/FayAvatarRuntime/FayAvatarRuntime.uproject" \
  /path/to/LinuxArm64/ShaderCompileWorker
```

FEX hands a native AArch64 child executable back to the host kernel, while
Unreal's worker protocol uses files. This may remove most shader-compilation
emulation overhead, but it remains an explicit protocol-compatibility test.
Keep the known-working x86 worker in the Engine as the fallback.

## Bounded Unreal probe

Do not begin with a MetaHuman. First use the minimal project in this repository:

```bash
./scripts/smoke-fex-unreal.sh \
  "$cooker_workspace" \
  "$PWD/../ue-5.8-linux-x86_64" \
  "$PWD/Project/FayAvatarRuntime/FayAvatarRuntime.uproject"
```

The probe has two stop points:

1. FEX must report an x86-64 guest.
2. A minimal LinuxArm64 cook must finish within its bounded time limit.

The cook reports only four cores to Unreal. UE 5.8 then starts at most three
initial ShaderCompileWorker processes instead of treating all Spark cores as
independent emulated workers. Logs remain below the selected workspace.

Only after both gates pass should a full project cook be attempted.

## Fresh cook and native package

The final all-Spark path deliberately separates the emulated Editor cook from
native ARM64 build/stage/package work. Do not use the FEX process to create the
final archive.

First choose the exact project and create a fresh loose cook:

```bash
project="$PWD/Project/FayAvatarRuntime/FayAvatarRuntime.uproject"

./scripts/cook-linux-arm64-fex.sh \
  "$cooker_workspace" \
  /absolute/path/to/UnrealEngine \
  "$project"
```

The cook wrapper refuses a nonempty `Saved/Cooked/LinuxArm64` directory instead
of deleting or silently reusing it. It defaults to a 12-hour stop limit, uses at
most four reported cooker cores, avoids Zen Storage, verifies the loose Ada,
MetaHuman-common, and StreamingADA files, and records a private fingerprint of
the project/Engine inputs and every cooked output file. Override the limit only
when justified, for example `UE5_SPARK_COOK_TIMEOUT=18h`.

Then use native ARM64 .NET, UnrealBuildTool, and UnrealPak to create a new
archive:

```bash
archive="$PWD/../ue5-spark-package-new"

./scripts/package-linux-arm64-hybrid.sh \
  "$cooker_workspace" \
  /absolute/path/to/UnrealEngine \
  "$project" \
  "$archive"
```

The hybrid packager refuses a changed/missing cook fingerprint, a nonempty
LinuxArm64 staging directory, or a nonempty archive. After packaging it uses
UnrealPak privately to prove the archive contains Ada, MetaHuman common assets,
and the StreamingADA v2 model. It also requires an ARM64 ONNX Runtime library,
rejects the Editor-only helper, and writes a hash seal beside the launcher. The
seal contains only relative filenames and hashes, not asset contents or private
machine paths. Subsequent runtime verification recomputes it before launching.
Runtime-created files below the packaged Game and Engine `Saved` directories are
deliberately outside the immutable seal so logs, manifests, and user settings do
not break a second launch.

If either step is interrupted, inspect the generated directories and choose
fresh destinations. These scripts do not delete partial cook, stage, or archive
trees automatically.

## Optional native ShaderCompileWorker adapter

UE checks the project's `Binaries/Linux/ShaderCompileWorker` before using the
copy under the x86-64 Engine. FEX also recognizes a non-x86 ELF launched by a
guest process and passes it directly to the host kernel. Together, those two
behaviors allow an experimental hybrid: emulate UnrealEditor-Cmd while running
ShaderCompileWorker natively on the Spark.

First build ShaderCompileWorker as a normal LinuxArm64 Program target from the
matching 5.8 source revision. Do not proceed if that build or its native module
dependencies are incomplete. Then create a project-local link:

```bash
./scripts/configure-native-scw-adapter.sh \
  "$PWD/Project/FayAvatarRuntime/FayAvatarRuntime.uproject" \
  "$PWD/../ue-5.8-source/Engine/Binaries/LinuxArm64/ShaderCompileWorker"
```

This does not replace the Editor's Engine file. The worker protocol uses input
and output files, which makes the hybrid plausible across two little-endian
64-bit architectures. It is still an experiment: the Editor and worker must be
from the same source revision, and the first small cook must prove protocol and
shader-format compatibility. Use the ordinary x86-64 worker first if diagnosis
is more important than speed.

## Expected cost and limitations

FEX is a CPU instruction translator, not virtualization. The Editor commandlet
and every x86-64 ShaderCompileWorker still pay translation overhead. The Spark's
128 GB unified memory and fast local NVMe were sufficient for the complete Ada
MetaHuman cook. The validated result does not make FEX an Epic-supported path;
future Engine/plugin revisions can still expose different translation or
third-party-library failures, and large cooks remain slow.

Headless commandlet cooking and the graphical Editor have both passed bounded
tests. The graphical path additionally requires FEX Vulkan/window-system
forwarding and conservative Unreal thread settings. It remains experimental and
is not required to run the finished native digital-human package.

## Primary references

- [FEX official repository](https://github.com/FEX-Emu/FEX)
- [FEX library forwarding](https://wiki.fex-emu.com/index.php/Development:Setting_up_Library_Forwarding)
- [FEX guest exec handling](https://github.com/FEX-Emu/FEX/blob/FEX-2607/Source/Tools/LinuxEmulation/LinuxSyscalls/Syscalls.cpp)
- [FEX RootFS documentation](https://wiki.fex-emu.com/index.php/Development:Setting_up_RootFS)
- [Khronos Vulkan driver discovery](https://github.com/KhronosGroup/Vulkan-Loader/blob/main/docs/LoaderDriverInterface.md#driver-discovery)
- [Epic Linux development requirements](https://dev.epicgames.com/documentation/unreal-engine/linux-development-requirements-for-unreal-engine)
- [Epic Installed Build reference](https://dev.epicgames.com/documentation/en-us/unreal-engine/installed-build-reference-guide-for-unreal-engine)
- [Epic shader compilation overview](https://dev.epicgames.com/documentation/unreal-engine/shader-development-in-unreal-engine)
