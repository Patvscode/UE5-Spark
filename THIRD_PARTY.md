# Third-party boundaries

No third-party source, binaries, or assets are vendored in this repository.

## Unreal Engine

Users obtain Unreal Engine directly from Epic and accept Epic's license. Do not
add Engine source, Editor binaries, downloaded dependencies, private engine
patches, or packaged Engine Tools to this public repository.

- [Unreal Engine EULA](https://www.unrealengine.com/eula/unreal)
- [Accessing Unreal Engine source](https://dev.epicgames.com/documentation/unreal-engine/downloading-source-code-in-unreal-engine)

## MetaHuman and Fab content

Users obtain and assemble their own MetaHuman through Epic. Do not commit
MetaHuman meshes, DNA, textures, grooms, animations, or paid/free Fab assets to
this repository unless their specific license expressly permits redistribution.

- [MetaHuman licensing](https://www.metahuman.com/license?lang=en-US)
- [Getting started with MetaHuman Creator](https://dev.epicgames.com/documentation/en-us/metahuman/getting-started-with-metahuman-creator)

## Fay

[Fay](https://github.com/xszyou/Fay) is a separate GPL-3.0 application. This
repository does not vendor or link Fay code. `FayAvatarBridge` interoperates
with the running service over its HTTP and WebSocket interfaces.

The tested companion integration is maintained in
[`Patvscode/Fay`](https://github.com/Patvscode/Fay/tree/agent/dgx-spark).
