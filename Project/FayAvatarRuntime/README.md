# Fay Avatar Runtime project

This is the minimal Unreal Engine 5.8 Game project used to package the
`FayAvatarBridge` and MetaHuman runtime adapter for Linux ARM64. It contains a
source-only diagnostic GameMode and an Editor-only MetaHuman assembly helper,
but deliberately tracks no MetaHuman, Fab, Marketplace, generated character,
StreamingADA model, or Engine content.

## Target

`FayAvatarRuntime.Target.cs` is the packaged Game target, and
`FayAvatarRuntimeEditor.Target.cs` is the x86-64 Editor/cooker target. On the
Spark it runs through rootless FEX while native ARM64 build/package tools create
the delivered Game. The complete Ada-aware cook, sealed native ARM64 package,
NVIDIA Vulkan runtime, audio, Fay WebSocket/WAV loop, local StreamingADA solve,
and visible learned facial motion have been verified on Spark.

The native-ARM Editor and uncooked-Game experiments are intentionally not
included. The working route uses the x86 Editor through FEX and a normal cooked
LinuxArm64 Game target.

## Plugin layout

The project uses Unreal's standard project-plugin layout:

```text
FayAvatarRuntime/
  Plugins/
    FayAvatarBridge/
    FayMetaHumanRuntime/
    FayMetaHumanEditorTools/
```

`FayAvatarBridge` owns transport, WAV decoding, and playback.
`FayMetaHumanRuntime` converts decoded PCM to 16 kHz mono, runs StreamingADA
through `NNERuntimeORTCpu`, converts the learned output into 251 MetaHuman raw
controls, and publishes the controls as the local `FayAudio` Live Link subject.
`FayMetaHumanEditorTools` is restricted to Editor targets and assembles the Ada
preset. The read-only preflight, Ada assembly, both compile targets, model load
(81 solver curves), exact Live Link consumer, complete 50 Hz speech-frame
accounting, and visual runtime checks pass. Conservative semantic head mappings
exist but are not visually verified; authored body animations such as wave and
invite are not implemented.

## First package

Use the root-level Spark FEX scripts or `scripts/cook-linux-arm64.sh` on an
ordinary editor-capable x86-64 Linux UE 5.8 host. The current
`/Engine/Maps/Entry` startup configuration is a low-cost bootstrap placeholder.

The Ada package already runs on the Spark. To rebuild it, run the read-only
preflight, complete interactive Epic authentication if required, assemble Ada,
confirm generated Content remains ignored, and then cook, package, verify, and
run the LinuxArm64 application. In the all-Spark workflow the FEX Editor creates
only a fresh fingerprinted loose cook; native ARM64 tools perform
build/stage/package and deep-seal the resulting archive.

The generated Ada assets and the Engine-supplied StreamingADA model become
Epic-licensed content inside that user's local cooked package. Neither the
assets, model, nor package may be committed here or uploaded as a repository
release.

See the repository [README](../../README.md) and
[build/deploy guide](../../docs/build-and-deploy.md).
