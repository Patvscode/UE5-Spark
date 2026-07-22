# Fay ARKit Runtime

`FayArkitRuntime` is a source-only runtime adapter for non-MetaHuman characters
that expose standard Apple ARKit facial morph targets. It consumes the trusted
message, speech-lifecycle, and mouth-amplitude events from `FayAvatarBridge` and
writes only eight fixed facial morphs on one reviewed skeletal-mesh component.

No vendor character, mesh, texture, animation, or binary library is included in
this plugin.

## Fixed face contract

`ConfigureAvatar(Avatar, FaceComponentName)` fails without changing the current
avatar unless it finds exactly one skeletal-mesh component with the requested
stable name and that mesh exposes every reviewed morph below:

- `jawOpen`
- `mouthClose`
- `mouthFunnel`
- `mouthPucker`
- `mouthSmileLeft` or Unreal Live Link's sealed `mouthSmile_L` alias
- `mouthSmileRight` or Unreal Live Link's sealed `mouthSmile_R` alias
- `eyeBlinkLeft` or Unreal Live Link's sealed `eyeBlink_L` alias
- `eyeBlinkRight` or Unreal Live Link's sealed `eyeBlink_R` alias

The strict contract accepts only the two common reviewed Apple/Unreal
left-right conventions above. It does not use the first skeletal mesh on an
actor or accept morph names from Fay messages.
Any actor/component/mesh swap after configuration invalidates the adapter and
stops all output without writing to the replacement mesh.

## Output

- `jawOpen` follows Fay's already-smoothed RMS mouth amplitude.
- Small `mouthClose`, `mouthFunnel`, and `mouthPucker` weights add conservative
  articulation without pretending RMS audio is a phoneme solver.
- Positive trusted sentiment/affect can add a short, symmetric smile.
- A deterministic local timer produces symmetric procedural blinks.
- Every driven weight is smoothed and clamped to `0..1`.

The driver never writes transforms, bones, poses, Control Rig controls,
animation-blueprint properties, body motion, gaze, head, or neck state. ARDY or
another reviewed provider remains the exclusive body-motion owner.

## Runtime use

Enable `FayArkitRuntime`, create `UFayArkitSpeechDriverComponent`, then connect
the already-created bridge and reviewed character:

```cpp
ArkitDriver->AttachBridge(Bridge);
if (!ArkitDriver->ConfigureAvatar(CharacterActor, TEXT("Face")))
{
    // Keep the existing diagnostic/rollback character active.
}
```

Call `ClearAvatar()` before removing the reviewed character. `EndPlay` also
unsubscribes from the bridge and publishes neutral weights to the still-reviewed
mesh. A different character must pass the same exact contract independently.

This adapter uses morph targets directly and does not require the Apple ARKit
runtime plugin or a camera feed. It is not a replacement for a learned phoneme
or facial-performance solver; it is a dependable local speech fallback for an
ARKit-compatible asset.

## Contract test

From the repository root:

```bash
python3 -m unittest \
  Project/FayAvatarRuntime/Plugins/FayArkitRuntime/Tests/test_arkit_runtime_contract.py
```
