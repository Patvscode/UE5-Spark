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
                            +--> allowlisted avatar intent over WebSocket :10002
                                             |
                                             v
                                  Packaged Unreal LinuxArm64
                                  - FayAvatarBridge
                                  - audio playback
                                  - FayMetaHumanRuntime
                                  - FayBodyMotion
                                  - MetaHuman rendering
                                             |
                                             +--> ARDY health/poses :8777
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

This direct, local runtime path does not use a microphone or a cloud solve
during playback. It is verified in the native LinuxArm64 package: Ada assembly,
model load, exact Live Link consumption, visible learned speech motion,
minimized-window 50 Hz solving, and cold relaunch checks pass.

## Responsibility split

| Component | Owns |
|---|---|
| Fay | Conversation state, memory, tool use, LLM routing, ASR/TTS coordination, sentiment and action metadata |
| MCP layer | Connections between Fay and external tools/systems |
| FayAvatarBridge | Socket registration/reconnect, bounded JSON/audio queues, WAV download/decoding, normalized Blueprint events |
| FayMetaHumanRuntime | Verified 16 kHz mono conversion, local StreamingADA solve, 251 raw-control conversion, `FayAudio` publishing, and Ada Live Link consumption in the native package |
| FayBodyMotion | Behavior allowlist, provider selection, eight-frame interpolation, post-evaluation Core27-to-MetaHuman retarget, face/head mask, cached-pose fade, and baked fallback |
| ARDY service | Token-free Horizon8 generation for the three sealed `idle`, `listen`, and `explain` embeddings on loopback |
| Unreal runtime | Avatar, camera, lighting, rendering, audio output, facial curves, and LOD/performance |
| x86-64 Editor/cooker through FEX | Asset editing plus LinuxArm64 shader/platform data for maps, textures, materials, meshes, rigs and MetaHumans |
| Native ARM build/package tools | LinuxArm64 Game compilation, staging, Pak-only packaging, deep content verification, and immutable-file sealing |

Fay semantic actions already cross the bridge. Conservative raw-control head
mappings for `nod`, `shake`, `think`, and `warn` are live-MCP verified but not
yet visually tuned. The body-motion plugin supplies a character-neutral
procedural fallback for `wave`, `invite`, `think`, `warn`, and `explain` when a
compatible private montage or generated provider is unavailable. With a
reviewed generated provider ready, conversational `explain` takes that route;
timing-critical actions remain deterministic. The sealed production Horizon8
provider now serves only the approved cached `idle`, `listen`, and `explain`
embeddings; its runtime container has no Hugging Face credential or text
encoder. The post-evaluation adapter maps pelvis/root, spine, shoulder/arm, and
leg/foot chains across nineteen reviewed MetaHuman body bones. Face, neck,
head, and sparse hand endpoints remain excluded so StreamingADA and reviewed
hand/head controls retain ownership. The current portrait camera proves face
and upper-body behavior; wide front/side full-body visual tuning remains a
separate acceptance milestone.

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
| ARDY health/pose service | `http://127.0.0.1:8777` |

Loopback avoids LAN exposure and unnecessary audio/network latency. Remote
renderers require a separately secured transport; do not change the bind host
to `0.0.0.0` as a shortcut.
