# Architecture

This document separates deployed architecture from source candidates. The
sealed v29 package and ARDY protocol-v1 service are live. Protocol v2, the
Core27-to-IK-retarget path, nine-motion cache, movement director, and wardrobe
adapter are v30 source candidates until they are cooked, deployed, and gated.

## Live v29 runtime topology

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
                                             +--> ARDY v1 health/poses :8777
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

V29 body motion is not the intended final architecture. It reconstructs a
nineteen-bone component-space pose and mutates finalized Body transforms through
unsupported access after ordinary evaluation. Its first-frame calibration and
source-axis handling are not a real source-rest/target-rest IK retarget. Portrait
captures verify a narrow result only; they do not qualify hands, legs, feet, or
the absence of ancestor-driven head/face displacement.

## Source-only v30 motion candidate

```text
reviewed motion ID
        |
        v
ARDY 0.3 / protocol v2 on loopback
  - nine reviewed cache slots (private cache pending)
  - 8 frames at 20 FPS
  - local Core27 XYZW rotations
  - global Core27 positions
  - L-heel/L-toe/R-heel/R-toe contacts
        |
        v
strict Unreal v2 client and interpolation buffer
        |
        v
hidden absolute Core27 source SkeletalMesh
        |
        v
reviewed IK Rig + IK Retargeter
        |
        v
target post-process AnimBP on Ada or Aoi Body
  - preserves ordinary Body animation
  - excludes face, neck, and head
  - preserves the existing detailed finger pose
  - blends to reviewed baked idle on failure
```

Protocol v2 identifies the exact official ARDY revision and Core27 layout. ARDY
is right-handed with +X toward the character's left, +Y up, and +Z forward;
Unreal vector conversion is `(z, -x, y)`, while reflected-basis quaternion
conversion is `(-z, x, -y, w)`. Global positions provide end-effector data for
later hand/foot IK and contacts provide the foot-plant signal. Quaternion signs
remain in one hemisphere across frames and batches.

The candidate validates one reviewed binding/profile, source mesh, post-process
AnimBP, and retargeter per character. It fails closed when any asset or runtime
input changes. None of those content assets, a v30 binary, or a real v2
nine-embedding run has yet passed the Spark deployment gates.

## Responsibility split

| Component | Owns |
|---|---|
| Fay | Conversation state, memory, tool use, LLM routing, ASR/TTS coordination, sentiment and action metadata |
| MCP layer | Connections between Fay and external tools/systems |
| FayAvatarBridge | Socket registration/reconnect, bounded JSON/audio queues, WAV download/decoding, normalized Blueprint events |
| FayMetaHumanRuntime | Verified 16 kHz mono conversion, local StreamingADA solve, 251 raw-control conversion, `FayAudio` publishing, and Ada Live Link consumption in the native package |
| FayBodyMotion in live v29 | Behavior allowlist, provider selection, eight-frame interpolation, unsupported legacy post-evaluation component-transform writer, face/head intent mask, cached-pose fade, and baked fallback |
| FayBodyMotion v30 candidate | Strict protocol-v2 client, hidden Core27 source pose, reviewed IK Retargeter/post-process binding, root policy, face/neck/head exclusion, finger preservation, and baked fallback |
| ARDY live service | Token-free Horizon8 `0.2.0` / protocol-v1 generation for the three sealed `idle`, `listen`, and `explain` embeddings on loopback |
| ARDY v30 candidate | `0.3.0` / protocol v2, exact source descriptor, global joints and contacts, plus nine reviewed cached motions; not deployed and missing its private schema-2 cache |
| Unreal runtime | Avatar, camera, lighting, rendering, audio output, facial curves, and LOD/performance |
| x86-64 Editor/cooker through FEX | Asset editing plus LinuxArm64 shader/platform data for maps, textures, materials, meshes, rigs and MetaHumans |
| Native ARM build/package tools | LinuxArm64 Game compilation, staging, Pak-only packaging, deep content verification, and immutable-file sealing |

Fay semantic actions already cross the bridge. Conservative raw-control head
mappings for `nod`, `shake`, `think`, and `warn` are live-MCP verified but not
yet visually tuned. The body-motion plugin supplies a character-neutral
procedural fallback for `wave`, `invite`, `think`, `warn`, and `explain` when a
compatible private montage or generated provider is unavailable. With a
reviewed generated provider ready, conversational `explain` takes that route;
timing-critical actions remain deterministic. The live sealed Horizon8
provider serves only the approved cached `idle`, `listen`, and `explain`
embeddings; its runtime container has no Hugging Face credential or text
encoder. The post-evaluation adapter maps pelvis/root, spine, shoulder/arm, and
leg/foot chains across nineteen reviewed MetaHuman body bones. Face, neck,
head, and sparse hand endpoints remain excluded so StreamingADA and reviewed
hand/head controls retain ownership. The current portrait camera proves face
and upper-body behavior; wide front/side full-body visual tuning remains a
separate acceptance milestone.

The v30 source path removes that late writer. It advertises the shared reviewed
catalog only after strict health qualification, routes generated `wave` as well
as conversational and in-place motions when packaged, and uses the hidden
Core27/IK path for both generated and procedural body input. These are design
and source-contract statements, not current runtime claims.

## Direct movement planning boundary

The private controller has a source-only `POST /api/motion-command` director.
Deterministic alias matching runs first. If no direct alias matches, an optional
local Qwen model may return exactly one advisory `catalogId`. The server then
reloads the authoritative catalog entry and owns duration, intensity, locked
root mode, and renderer route. The model can never provide ARDY prompts, pose
frames, constraints, paths, URLs, asset names, or timing.

The catalog contains `idle`, `listen`, `explain`, `wave`, `jog_in_place`,
`run_in_place`, `jumping_jacks`, `stretch`, and `dance_relaxed`. The controller
routes only items marked `rendererPackaged=true`; other matches return an honest
staged response and send nothing to Fay or Unreal. Those flags may be promoted
only after the corresponding motion exists in a sealed, qualified package.

## Modular-character and wardrobe boundary

The free Fab Casual Girl candidate is not installed and is not a MetaHuman. Its
pending public profile exposes logical outfit, garment, feet, and hair IDs but
no Unreal component or asset paths. The controller keeps every control disabled
while the profile status is `pending_asset_audit`. The content-free Unreal
wardrobe component applies complete reviewed presets transactionally and
restores prior visibility on failure or teardown.

Full undress remains unavailable unless manual inspection proves that every
body region, material, and LOD is complete beneath the clothing. Importing the
asset also requires private UE 5.8/LinuxArm64 validation, an Epic-skeleton ARDY
retarget profile, an Apple-ARKit 52-morph face adapter, and reviewed clothing/
hair component mappings. Fab content and mappings derived from private asset
paths do not belong in this repository.

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
| Live v29 ARDY health/pose service | `http://127.0.0.1:8777` with `POST /v1/poses` |
| Candidate v30 ARDY health/pose service | same loopback origin with `POST /v2/poses`, only after a coordinated switch |

Loopback avoids LAN exposure and unnecessary audio/network latency. Remote
renderers require a separately secured transport; do not change the bind host
to `0.0.0.0` as a shortcut.
