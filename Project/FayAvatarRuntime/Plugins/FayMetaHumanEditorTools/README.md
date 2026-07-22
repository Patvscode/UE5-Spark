# Fay MetaHuman Editor Tools

This Editor-only plugin provides the one small UE 5.8 API adapter
needed to reproduce Epic's preset-to-assembly sequence from Python. It contains
no MetaHuman assets, Engine source, credentials, or generated content. The
project enables it only for Editor targets; packaged Game targets exclude it.

The plugin also contains a sealed ARDY v30 retarget **foundation** builder.
It creates and validates the exact Core27/source-target IK assets, a body-only
mask, a fail-closed draft profile, and isolated Ada/Aoi Blueprint candidates.
It deliberately does not invent or silently splice the MetaHuman post-process
AnimGraph. See `docs/ardy-v30-editor-foundation.md` for its fixed paths,
expected nonzero completion gate, v2 foot-contact inputs, and review boundary.

The adapter reflects
`UMetaHumanCharacterEditorSubsystem::InitializeFromPreset`, which is public C++
in UE 5.8 but is not exposed directly to Blueprint or Python. The accompanying
`Scripts/build_ada.py` is the fail-closed reviewed-preset builder. It defaults
to Epic's included Ada preset; `Scripts/build_aoi.py` selects Aoi through the
same implementation. Both request the face rig and texture sources and
assemble an **Optimized / High** MetaHuman using **Joints and Blend Shapes**.
The builder validates key copied preset state, removes any inherited rig,
confirms that the new cloud rig returned blend shapes, never overwrites an
existing character destination, and does not accept arbitrary preset paths.

## Spark optimization boundary

`Optimized / High` is the MetaHuman assembly pipeline requested from UE 5.8;
it is not a promise that the result is already tuned for DGX Spark. The public
Python API used here does not provide a reliable way to require card-only hair
or cap every generated texture's resolution. Groom choices and source texture
characteristics can also be inherited from the Ada preset and Epic's current
assembly defaults.

The script therefore logs this limitation but deliberately does not claim to
enforce it. Before treating the output as a deployment asset, inspect the
assembled Blueprint and its referenced assets in the Editor, select supported
card-based hair representations where available, choose conservative texture
sizes and LODs with the MetaHuman tools, and test the cooked Linux ARM64 build
on Spark. Keep the first unmodified assembly as a fidelity baseline so visual
changes can be compared after optimization.

## Prerequisites

- Unreal Engine 5.8 source with MetaHuman Creator Core Data installed
- The `MetaHumanCharacter` and `PythonScriptPlugin` Engine plugins
- A rendering-capable Editor session; do not assume `-nullrhi` works for the
  MetaHuman material and texture pipeline
- An Epic account authorized for MetaHuman cloud services

Auto-rigging and high-resolution texture synthesis use Epic's cloud services.
Sign into Epic interactively in a normal graphical Editor session before using
the unattended command. Never place an Epic email, password, token, or exchange
code in this repository or a shell command.

The project uses this Editor-only entry. Rebuild the x86-64 Editor target after
cloning or changing the adapter:

```json
{
  "Name": "FayMetaHumanEditorTools",
  "Enabled": true,
  "TargetAllowList": [
    "Editor"
  ]
}
```

Its plugin dependencies request MetaHuman Character and Python support only for
Editor targets. Keep that restriction in place so the adapter stays out of
packaged Game targets. The project
separately enables the Engine's `MetaHumanCharacter` plugin without an Editor
target restriction because generated MetaHumans need its runtime modules and
declared transitive plugin dependencies when cooking and running a Game target.

## Output and overwrite policy

The script uses only these project paths:

```text
/Game/FayMetaHumans/Source/AdaFay
/Game/FayMetaHumans/Built/AdaFay/BP_AdaFay
/Game/FayMetaHumans/Common_UE58
```

It aborts if any asset already exists below `/Game/FayMetaHumans`; it never
deletes or overwrites content. It also refuses to start with dirty Editor
packages and saves only dirty packages below `/Game/FayMetaHumans`. An
interrupted Engine assembly can leave partial packages, so inspect that
directory manually before deciding whether to remove anything and retry.

## First run

Run the script from a normal graphical Editor after interactive Epic sign-in:

```bash
"$ENGINE_ROOT/Engine/Binaries/Linux/UnrealEditor" \
  "$PROJECT_ROOT/FayAvatarRuntime.uproject" \
  -vulkan \
  -ExecutePythonScript="$PROJECT_ROOT/Plugins/FayMetaHumanEditorTools/Scripts/build_ada.py" \
  -ScriptErrorsAreFatal
```

After that succeeds and persistent authentication is proven, an unattended run
can use the Python commandlet:

```bash
"$ENGINE_ROOT/Engine/Binaries/Linux/UnrealEditor-Cmd" \
  "$PROJECT_ROOT/FayAvatarRuntime.uproject" \
  -run=PythonScript \
  -script="$PROJECT_ROOT/Plugins/FayMetaHumanEditorTools/Scripts/build_ada.py" \
  -unattended -nop4 -nosplash \
  -NoMetaHumanAccountPortalLoginFallback
```

Keep a working Vulkan/display context for the initial commandlet experiment.
`-NoMetaHumanAccountPortalLoginFallback` makes missing authentication fail
instead of attempting an interactive account portal from an unattended job.
