# Fay Avatar Runtime project

This is the minimal Unreal Engine 5.8 Game project used to package the
`FayAvatarBridge` for Linux ARM64. It contains a source-only smoke-scene
GameMode and deliberately contains no MetaHuman, Fab, Marketplace, or Engine
content.

## Target

`FayAvatarRuntime.Target.cs` is the packaged Game target, and
`FayAvatarRuntimeEditor.Target.cs` is the ordinary Editor target for the
supported x86-64 build/cook host. The Game module and bridge compiled and linked
as native Linux ARM64 code during the Spark source experiment. The public Game
target now uses standard Unreal build settings and still awaits its complete
x86-64-hosted cook.

The unsuccessful native-Editor and uncooked-Game experiments are intentionally
not included. They depended on private Epic-source patches and did not provide
a working cooker or visual avatar.

## Plugin layout

The bridge uses Unreal's standard project-plugin layout:

```text
FayAvatarRuntime/
  Plugins/
    FayAvatarBridge/
```

That lets the plugin build, cook, and stage with the project without a custom
plugin search path.

## First package

Use the root-level `scripts/cook-linux-arm64.sh` on an editor-capable x86-64
Linux Unreal 5.8 host. Create a small project-owned map before the first serious
rendering test; the current `/Engine/Maps/Entry` configuration is only a
source/bootstrap placeholder.

After a blank cooked package runs on the Spark, add a lightweight skeletal
character and then a UE Optimized MetaHuman. Bind the bridge events only after
the basic Vulkan, display, audio, and reconnect path is stable.

See the repository [README](../../README.md) and
[build/deploy guide](../../docs/build-and-deploy.md).
