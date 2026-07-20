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
the delivered Game. The earlier diagnostic Game module, bridge, complete cook,
package, Vulkan runtime, audio, and Fay WebSocket/WAV loop were verified on
Spark.

The new `FayMetaHumanRuntime` source has now compiled as part of the x86-64 UE
5.8 Editor target through FEX and the native LinuxArm64 Game target. It has not
yet passed a MetaHuman-aware cook/package, run its model on the Spark, or been
visually verified on an assembled MetaHuman.

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
preset. The read-only Ada/MetaHuman preflight and both compile targets pass; Ada
assembly, cook, packaged runtime, and visual verification remain pending. Body
animation playback is not implemented.

## First package

Use the root-level Spark FEX scripts or `scripts/cook-linux-arm64.sh` on an
ordinary editor-capable x86-64 Linux UE 5.8 host. The current
`/Engine/Maps/Entry` startup configuration is a low-cost bootstrap placeholder.

The diagnostic cooked package already runs on the Spark. The MetaHuman sequence
is: run the read-only preflight, complete interactive Epic authentication if it
is required, build Ada, confirm generated Content remains ignored, and then
cook, package, verify, and run the LinuxArm64 application. In the all-Spark
workflow the FEX Editor creates only a fresh fingerprinted loose cook; native
ARM64 tools perform build/stage/package and deep-seal the resulting archive.

The generated Ada assets and the Engine-supplied StreamingADA model become
Epic-licensed content inside that user's local cooked package. Neither the
assets, model, nor package may be committed here or uploaded as a repository
release.

See the repository [README](../../README.md) and
[build/deploy guide](../../docs/build-and-deploy.md).
