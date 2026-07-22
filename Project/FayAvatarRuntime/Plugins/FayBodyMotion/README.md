# Fay Body Motion

This source-only runtime plugin separates avatar intent, ARDY transport, and
character retargeting from Fay transport and StreamingADA facial animation.

## Production safety boundary

Generated motion no longer mutates `GetComponentSpaceTransforms()` after body
evaluation. There is no `const_cast`, first-frame local-rotation calibration,
or direct Core27-to-MetaHuman bone-axis guess in the production path.

The supported architecture is:

1. A hidden skeletal mesh with the exact ordered nv-tlabs/ardy Core27 hierarchy.
2. `UFayCore27SourceAnimInstance`, which evaluates the absolute Core27 local
   pose through Unreal's normal animation pipeline.
3. A reviewed character post-process Animation Blueprint containing **Retarget
   Pose From Mesh** and a reviewed `UIKRetargeter`.
4. A reviewed blend mask that keeps the ordinary input pose on the neck/head
   branch and all fingers. StreamingADA therefore retains exclusive facial and
   head ownership.

`UFayArdyRetargetBindingComponent` opts a character Blueprint into a reviewed
`UFayArdyRetargetProfile`. Runtime validation requires exactly one binding, the
exact 27-bone hierarchy, exact asset classes, the expected post-process class,
and these fixed post-process AnimBP variables:

- `FayArdyContractVersion` (`int32`, value `2`)
- `FayArdyExcludesNeckAndHead` (`bool`, true)
- `FayArdyPreservesFingerPose` (`bool`, true)
- `FayArdyUsesFootContactOffsets` (`bool`, true)
- `FayArdySourceMeshComponent` (`USkeletalMeshComponent`)
- `FayArdyBlendWeight` (`float`)
- `FayArdyLeftHeelOffset`, `FayArdyLeftToeOffset`,
  `FayArdyRightHeelOffset`, `FayArdyRightToeOffset` (`FVector`)
- `FayArdyLeftHeelContact`, `FayArdyLeftToeContact`,
  `FayArdyRightHeelContact`, `FayArdyRightToeContact` (`float`)
- `FayProceduralBehavior` (`FName`)
- `FayProceduralProgress` (`float`)
- `FayProceduralIntensity` (`float`)

If any part is absent or changes at runtime, ARDY and post-process procedural
motion fail closed. The visible Body's main animation class and evaluated pose
are not replaced or rewritten; a reviewed montage or ordinary idle remains.

## Required Unreal Editor asset gate

The runtime C++ is deliberately not allowed to invent retarget assets. Before a
character can enable generated motion, an Unreal Editor build must:

1. Import an exact Core27 source skeletal mesh from the pinned ARDY revision in
   the converted Unreal basis; its 27 names and parent indices must match the
   runtime contract exactly.
2. Create the source/target IK Rigs and `UIKRetargeter`, align the reviewed ARDY
   T-pose with the character's target pose, then review shoulder, elbow, palm,
   knee, and foot chains from front and side views.
3. Create a character post-process Animation Blueprint that retains its normal
   input pose and correctives, evaluates **Retarget Pose From Mesh**, and blends
   with a reviewed profile that excludes neck/head and all fingers. It must
   expose the fixed variables listed above. Its reviewed lower-body IK layer
   adds the four bounded offsets to the already-retargeted heel/toe locations;
   a zero contact weight disables that goal.
4. Create a `UFayArdyRetargetProfile` Data Asset and attach exactly one
   `UFayArdyRetargetBindingComponent` to each reviewed character Blueprint.
5. Compile/cook the assets and pass front/side wave, jog, jumping-jacks, face
   ownership, disconnect, and fallback validation.

Until all five steps pass, generated retargeting remains disabled by design.

## ARDY protocol

The client accepts only protocol v2 from `127.0.0.1:8777` and
`POST /v2/poses`. It validates:

- the exact official ARDY source revision and Core27 joint hierarchy;
- ARDY's right-handed +X-left/+Y-up/+Z-forward coordinate identity;
- local XYZW rotations and 27 global posed-joint positions;
- the exact contact order, 20 FPS timing, eight-frame batches, and monotonic
  sequence/time cursor;
- finite, normalized, hemisphere-stabilized quaternions and bounded roots;
- identity neck/head rotations; and
- the exact health motion catalog.

Conversion happens exactly once at the hidden source-pose boundary:

- position: `(z, -x, y)` metres to Unreal centimetres;
- quaternion: `(-z, x, -y, w)`, followed by normalization.

Root translation defaults to `LockedInPlace`. The only opt-in alternative is a
per-action origin with a maximum 20 cm displacement; actor/world locomotion is
not exposed by this profile.

### Bounded foot-contact stabilization

Protocol-v2 global positions and ordered contact values now feed an
action-scoped drift stabilizer. A heel or toe anchor is acquired at contact
`>= 0.65` and released at `<= 0.35`. The stabilizer publishes only a counter-
drift offset in Unreal's component basis, never an absolute cross-skeleton
target. Each offset is clamped to 6 cm; an 18 cm source-joint discontinuity
blocks that contact until a clean release. Weights are smoothed and decay on a
buffer underrun. Invalid counts, non-finite values, missing AnimBP variables,
or a changed contract clear all weights and disable ARDY.

This layer does not change actor/root translation, including under
`LockedInPlace`, and it never writes face, neck, head, or finger transforms.
The fixed lower-body post-process graph remains a reviewed private asset, so a
front/side foot-sliding gate is still required before deployment.

## Provider routing

The nine sealed generated actions—`idle`, `listen`, `explain`, `wave`,
`jog_in_place`, `run_in_place`, `jumping_jacks`, `stretch`, and
`dance_relaxed`—are ARDY-first whenever both the strict protocol-v2 provider and
the reviewed retarget contract are ready. A configured wave montage therefore
cannot silently replace healthy ARDY. Baked montages and the post-process
procedural gestures are failure fallbacks only; fallback state and reason are
reported explicitly. Non-generated timing actions such as `invite`, `think`,
`warn`, `nod`, and `shake` remain deterministic.

Licensed character assets, Animation Blueprints, IK Rigs/Retargeters, blend
masks, montages, checkpoints, embeddings, and cooked packages are intentionally
not part of this public repository.
