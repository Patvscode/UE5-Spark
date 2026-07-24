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

The runtime facial adapter also depends on Epic's StreamingADA model from the
authorized Unreal installation. The generated Ada assets and that model may be
cooked into the user's local application, but neither the source assets/model
nor a package containing them is distributed by this repository. Do not attach
such a package to a public GitHub release.

- [MetaHuman licensing](https://www.metahuman.com/license?lang=en-US)
- [Getting started with MetaHuman Creator](https://dev.epicgames.com/documentation/en-us/metahuman/getting-started-with-metahuman-creator)

The optional second female test character is the free Fab listing
[Free Casual Girl Sample (Modular)](https://www.fab.com/listings/1da38c7b-c197-4cc4-a02f-9f63f480e300).
It uses the Fab Standard License and carries Fab's `NoAI` tag. The asset is
acquired into the user's private Epic library and is never committed here.
The license and tag are documented for information; the user is responsible
for deciding which optional AI-control capabilities to enable and for complying
with the terms that apply to their use. See [the isolated integration gate](docs/fab-casual-girl.md).

## Fay

[Fay](https://github.com/xszyou/Fay) is a separate GPL-3.0 application. This
repository does not vendor or link Fay code. `FayAvatarBridge` interoperates
with the running service over its HTTP and WebSocket interfaces.

The tested companion integration is maintained in
[`Patvscode/Fay`](https://github.com/Patvscode/Fay/tree/agent/dgx-spark).
