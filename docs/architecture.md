# Architecture

## Runtime topology

```text
                           DGX Spark

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
                                  - face/body animation
                                  - MetaHuman rendering
```

The one-time x86-64 builder is outside this runtime diagram. It produces the
cooked Linux ARM64 package whenever project or character assets change.

## Responsibility split

| Component | Owns |
|---|---|
| Fay | Conversation state, memory, tool use, LLM routing, ASR/TTS coordination, sentiment and action metadata |
| MCP layer | Connections between Fay and external tools/systems |
| FayAvatarBridge | Socket registration/reconnect, bounded JSON/audio queues, WAV download/decoding, normalized Blueprint events |
| Unreal runtime | Avatar, camera, lighting, rendering, audio output, facial curves, gestures, LOD/performance |
| x86-64 cooker | Shader compilation and platform data for maps, textures, materials, meshes, rigs and MetaHuman assets |

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
