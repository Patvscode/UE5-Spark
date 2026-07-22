# Build and deploy

This is the conventional x86-64-builder path. It keeps all system-level changes
away from the DGX Spark. The project has also verified an experimental
all-on-Spark route; see [the rootless FEX guide](spark-fex-cooker.md).

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

For the first package, keep the scene intentionally small. The current reference
package has verified native Vulkan/audio, live Fay WebSocket/WAV playback, the
Ada assembly, and the learned facial path; adding a larger scene should remain a
separate performance change.

## 3. Preflight MetaHuman support

Run `scripts/metahuman-preflight.py` through the graphical UE 5.8 Editor before
creating content. It checks the Editor helper, MetaHuman subsystem, included Ada
preset, required enums, empty destination, and unchanged dirty-package state.
It does not authenticate, call Epic's cloud services, create assets, or save
packages.

The all-Spark invocation is documented in the
[Spark FEX cooker guide](spark-fex-cooker.md). Stop if any fixed preflight marker
fails.

## 4. Authenticate and build Ada locally

After the preflight, start the normal graphical Editor. If persistent Epic
authentication is missing or expired, complete sign-in only in the browser flow
the Editor opens. Never put an Epic email, password, exchange code, or token in
a command, log, config, or repository file.

Run the Editor-only `build_ada.py` helper described in the
[MetaHuman plan](metahuman.md). It creates an Optimized / High Ada assembly
below `/Game/FayMetaHumans` without overwriting existing content.

## 5. Verify the publication boundary

Before cooking, confirm a representative generated asset is ignored and the
public source still passes its checks:

```bash
git check-ignore -v \
  Project/FayAvatarRuntime/Content/FayMetaHumans/Built/AdaFay/BP_AdaFay.uasset
git status --short
./scripts/check-repository.sh
```

Do not force-add generated Content. Ada and the Engine-supplied StreamingADA
model are Epic-licensed content. The final cooked package contains that local
content and must not be uploaded to this repository or a GitHub release.

## 6. Cook and verify Linux ARM64

```bash
./scripts/cook-linux-arm64.sh /path/to/UnrealEngine /path/to/archive
./scripts/verify-cooked-package.sh /path/to/archive
```

The cook wrapper refuses to run on a non-Linux or non-x86-64 host, checks that
the Engine reports version 5.8, and requires an empty archive directory to
prevent stale results. It deep-inspects the Pak with that Engine's UnrealPak and
writes a relative-path/hash seal only after all required content passes. The
normal one-argument verifier rechecks that seal and requires all of the
following:

- the exact staged
  `FayAvatarRuntime/Binaries/LinuxArm64/FayAvatarRuntime` file to be an
  `ELF 64-bit` `ARM aarch64` executable; and
- every selected reviewed character Blueprint and the MetaHuman common content
  in the Pak;
- the StreamingADA v2 model in the Pak;
- Ada's Interchange garment material dependency in the Pak;
- at least one packaged ONNX Runtime shared library to be an ARM64 ELF;
- no `FayMetaHumanEditorTools` Editor module or content; and
- every immutable packaged regular file to still match the deep-verification
  seal. Runtime-created files below the packaged Game and Engine `Saved` trees
  are outside the seal.

Do not continue if either check fails.

`DefaultGame.ini` contains reviewed character profiles. Select one or more with
repeatable `--character <id>` arguments when cooking; the packager writes a
validated profile manifest into the archive. The runtime accepts only those
reviewed IDs through `-FayCharacter=<id>` and never accepts arbitrary asset
paths. Each profile keeps its generated assembly/common paths and
`/StreamingADA` in the cook. The runtime adapter converts Fay PCM to 16 kHz
mono, runs the model through `NNERuntimeORTCpu`, converts its output to 251 raw
MetaHuman controls, and publishes `FayAudio` through Live Link. The reference
package has passed the MetaHuman-aware cook, model initialization, exact Live
Link consumer, visible speech motion, and complete 50 Hz frame-count gates on
the Spark.

For the all-on-Spark path, do not use the conventional wrapper above. Follow
the two explicit steps in the [Spark FEX cooker guide](spark-fex-cooker.md):
`cook-linux-arm64-fex.sh` creates only a fresh fingerprinted loose cook, then
`package-linux-arm64-hybrid.sh` builds/stages/packages natively into a new
archive.

## 7. Copy only the finished package

Copy the verified archive into a new user-owned directory on the Spark, for
example `~/Applications/UE5-Spark/`. Do not copy the Engine checkout, builder
cache, or private patch workspace.

No root access is required for the packaged application.

## 8. Read-only Spark preflight

From this repository on the Spark:

```bash
./scripts/verify-spark.sh
```

The script checks Linux ARM64, normal-user execution, NVIDIA driver access, and
Vulkan enumeration. It prints memory/filesystem information. It never invokes
`sudo`, installs a package, changes a driver, or edits a service.

If `vulkaninfo` is absent, stop and decide separately whether installing the
diagnostic package is acceptable; the script will not do it automatically.

## 9. Launch the cooked application

```bash
./scripts/run-cooked-package.sh \
  ~/Applications/UE5-Spark/FayAvatarRuntime-Arm64.sh
```

The launcher validates that an AArch64 ELF and cooked content exist beside the
package launcher before starting Unreal with `-vulkan -log`.

If Fay is already running and the complete local stack should be checked before
launch, use:

```bash
./scripts/run-spark-digital-human.sh \
  ~/Applications/UE5-Spark/FayAvatarRuntime-Arm64.sh
```

The guarded normal-user stack launcher discovers existing non-global Fay HTTP,
avatar, and MCP listeners, probes readiness, exports the discovered `FAY_*`
runtime endpoints, and then delegates to `run-cooked-package.sh`. It does not
print or bake the discovered addresses, start or stop a service, or change
service/system configuration. For Vulkan launches from SSH, it reuses the
existing local desktop's `DISPLAY` only when the matching X11 socket exists and
the socket, runtime directory, user-session bus, and GDM authority file are
owned by the same user. It never starts or
reconfigures a display server. Before a Vulkan launch it also requires at least
48 GiB of available unified memory so idle model reservations cannot produce a
stuck NVIDIA device-creation dialog. The reserve is configurable with
`UE5_SPARK_MIN_AVAILABLE_MEMORY_GIB`; headless `-nullrhi` diagnostics bypass
that graphics-only check. MCP administration/SSE checks are required by
default; disable only those checks with:

```bash
UE5_SPARK_REQUIRE_MCP=0 ./scripts/run-spark-digital-human.sh \
  ~/Applications/UE5-Spark/FayAvatarRuntime-Arm64.sh
```

On a new package or machine, reconfirm:

1. A window or fullscreen frame appears through NVIDIA Vulkan.
2. The project-owned map is loaded.
3. Audio output works.
4. Repeated launch/exit is clean.

For a promotion candidate, use `run-spark-avatar-gate.sh` around the rendered
soak rather than launching it by hand. It owns the one packaged process,
temporarily pauses only the fixed allowlisted Voxtral user unit when needed,
observes (but does not manage) Fay and ARDY, verifies teardown and the package
seal, and restores Voxtral on every exit path. A production result must declare
`FAY_SOAK_EVIDENCE_MODE=production`.

Use `run-spark-ardy-recovery-gate.sh` only as a separate diagnostic after a
steady-state production gate. It can stop only the exact repeatedly captured
project ARDY container and must publish a new sealed real provider, prove
bounded fallback/recovery, preserve Fay, restore Voxtral, and leave no Unreal
process. Its result is always diagnostic and cannot replace production or
endurance qualification. See
[the guarded gate contract](guarded-spark-avatar-gate.md).

## 10. Validate Fay separately

Install the smoke-test-only dependency in an isolated Python environment:

```bash
python3 -m venv .venv-tools
.venv-tools/bin/pip install -r tools/requirements.txt
.venv-tools/bin/python tools/fay-avatar-smoke-test.py
```

This registers a temporary renderer, submits a chat turn, and verifies that the
returned WAV URL is fetchable. It lets backend failures be separated from
Unreal failures.

## 11. Verify animation in controlled stages

1. Reconfirm Fay connection and ordered speech playback.
2. Verify assembled Ada renders with stable LOD, hair, materials, and lighting.
3. Verify the local model loads and the `FayAudio` subject publishes controls.
4. Compare 16 kHz mono solve timing with audible playback and confirm visible
   learned mouth/expression motion.
5. Use RMS jaw-open only as a diagnostic fallback.
6. Add and verify body animations later; none are implemented in this source.

Each stage should remain independently testable before the next is added.
