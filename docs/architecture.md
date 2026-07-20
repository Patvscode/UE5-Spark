# Architecture

## Runtime topology

```text
                           DGX Spark

  x86 UE Editor/Cooker --rootless FEX--> LinuxArm64 cooked package
                                                |
                                                v

  microphone --> ASR --> Fay conversation/runtime --> local LLM
                            |         |
                            |         +--> MCP clients and MCP server
                            |
                            +--> TTS --> WAV under HTTP :5000
                            |
                            +--> avatar events over WebSocket :10002
                                             |
                                             v
                                  Packaged Unreal LinuxArm64
                                  - FayAvatarBridge
                                  - audio playback
                                  - FayMetaHumanRuntime
                                  - MetaHuman rendering
```

The x86 Editor/cooker is a development-time process on the Spark. The packaged
runtime below it is native ARM64 and does not use FEX. A separate x86-64 Linux
builder can still produce the same package when preferred.

The implemented facial source path is:

```text
Fay WAV
  -> FayAvatarBridge PCM16 decode
  -> 16 kHz mono samples
  -> StreamingADA with NNERuntimeORTCpu
  -> learned GUI controls
  -> 251 MetaHuman raw controls
  -> local Live Link Basic subject: FayAudio
  -> assembled MetaHuman face
```

This is the intended direct, local runtime path; it does not use a microphone
or a cloud solve during playback. The adapter now compiles for the x86-64 Editor
and native LinuxArm64 Game targets. LinuxArm64 cooking/packaging, Spark model
runtime, and visual checks remain pending.

## Responsibility split

| Component | Owns |
|---|---|
| Fay | Conversation state, memory, tool use, LLM routing, ASR/TTS coordination, sentiment and action metadata |
| MCP layer | Connections between Fay and external tools/systems |
| FayAvatarBridge | Socket registration/reconnect, bounded JSON/audio queues, WAV download/decoding, normalized Blueprint events |
| FayMetaHumanRuntime | 16 kHz mono conversion, local StreamingADA solve, 251 raw-control conversion, and `FayAudio` Live Link publishing; x86 Editor and ARM64 Game compilation verified, runtime/visual pending |
| Unreal runtime | Avatar, camera, lighting, rendering, audio output, facial curves, and LOD/performance |
| x86-64 Editor/cooker through FEX | Asset editing plus LinuxArm64 shader/platform data for maps, textures, materials, meshes, rigs and MetaHumans |
| Native ARM build/package tools | LinuxArm64 Game compilation, staging, UnrealPak/IoStore, and archive verification |

Fay semantic body actions already cross the bridge, but no body montage/control
mapping is implemented. Body gestures remain a separate future layer.

## Why MCP does not belong inside the avatar plugin

The avatar renderer should receive small, deterministic presentation events. It
does not need credentials or direct access to every external tool. Fay invokes
MCP tools, converts the result into conversation/action state, and sends Unreal
only the output needed to speak and animate.

This keeps credentials out of the packaged renderer and lets other systems use
Fay's MCP interfaces without recompiling Unreal.

## Network defaults

When everything runs on the same Spark:

| Interface | Default |
|---|---|
| Fay HTTP/API/audio | `http://127.0.0.1:5000` |
| Fay avatar WebSocket | `ws://127.0.0.1:10002` |

Loopback avoids LAN exposure and unnecessary audio/network latency. Remote
renderers require a separately secured transport; do not change the bind host
to `0.0.0.0` as a shortcut.
