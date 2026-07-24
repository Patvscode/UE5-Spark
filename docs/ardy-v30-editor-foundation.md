# ARDY v30 Editor asset foundation

The v30 Editor builder creates only the deterministic, automatable portion of
the Core27-to-MetaHuman retarget pipeline. It is intentionally separate from
the live v29 package and writes new candidate assets below:

```text
/Game/FayMetaHumans/Built/FayArdyV30
```

It never accepts user-supplied Unreal asset paths. Ada, Aoi, the imported
Core27 mesh, the MetaHuman target mesh/skeleton, the IK assets, and the shared
profile all have fixed reviewed paths in
`build_ardy_v30_foundation.py`.

## What the foundation builder creates

- a source IK Rig rooted at `Hips` with explicit spine, clavicle, arm, and leg
  chains;
- a target IK Rig rooted at `pelvis` with explicit MetaHuman body chains;
- a UE 5.8 IK Retargeter with exactly the five default operations, explicit
  one-to-one chain mappings, `ARDY_Core27_TPose`, and
  `MetaHuman_A_Pose`;
- a private duplicate of Ada's target-preview body mesh and the shared body
  skeleton, rebound entirely below the v30 namespace;
- the `FayArdyV30_BodyOnly` Blend Mask on that private skeleton duplicate;
- a shared, deliberately incomplete `UFayArdyRetargetProfile`;
- isolated Ada and Aoi Blueprint duplicates with exactly one
  `UFayArdyRetargetBindingComponent` each.

The source Ada mesh and shared v29 skeleton are read-only inputs. The builder
does not add a mask to or save either original package. The mask on the private
clone gives weight 1 only to the reviewed pelvis, spine, clavicle, arm,
hand, leg, foot, and ball bones. `root`, the neck/head branch, fingers, face,
and corrective branches stay at weight 0. Hands are retained as the arm-chain
endpoints, while finger performance remains owned by the ordinary character
pose.

The imported source is accepted only when its reference skeleton exactly
matches all 27 ARDY bone names, order, and parents. The source rig omits
`Neck`, `Head`, hand-end, and thumb bones, so it cannot take ownership of the
face/head/finger branches.

## Why the command exits nonzero

UE 5.8 exposes supported scripting APIs for creating IK Rigs, chains,
retargeters, mappings, operations, and poses. Safely rewriting an existing
MetaHuman post-process AnimGraph is different: it requires graph topology and
evaluation-order review. A superficially valid node graph could bypass body
correctives, steal StreamingADA head/face control, or apply contact correction
to the wrong skeleton space.

The foundation builder therefore saves its isolated safe outputs, emits
`FAY_ARDY_V30_FOUNDATION_BUILT=1`, and then deliberately raises an error. It
leaves `TargetPostProcessAnimClass` unset, which causes the runtime profile to
fail closed. This is expected and must not be described as a runtime-ready
v30 build.

The reviewed post-process AnimBP must retain the ordinary linked input pose and
correctives; layer `Retarget Pose From Mesh` through the body-only mask; and
consume the foot-contact offset inputs only in a lower-body IK layer after
retargeting. It must compile with these exact v2 inputs/defaults:

```text
int32 FayArdyContractVersion = 2
bool FayArdyExcludesNeckAndHead = true
bool FayArdyPreservesFingerPose = true
bool FayArdyUsesFootContactOffsets = true
USkeletalMeshComponent FayArdySourceMeshComponent
float FayArdyBlendWeight = 0
FName FayProceduralBehavior
float FayProceduralProgress = 0
float FayProceduralIntensity = 0
FVector FayArdyLeftHeelOffset = (0,0,0)
FVector FayArdyLeftToeOffset = (0,0,0)
FVector FayArdyRightHeelOffset = (0,0,0)
FVector FayArdyRightToeOffset = (0,0,0)
float FayArdyLeftHeelContact = 0
float FayArdyLeftToeContact = 0
float FayArdyRightHeelContact = 0
float FayArdyRightToeContact = 0
```

The four offsets are component-basis counter-drift vectors, clamped to 6 cm.
The lower-body IK layer adds them to the currently retargeted heel/toe
locations. A zero contact weight disables that goal. The graph must never feed
these values into neck, head, face, or finger controls.

## Running the foundation gate

First generate and privately import the exact Core27 GLB at the fixed source
mesh path. Generated source files and `.uasset` files stay private. Then run:

```bash
"$ENGINE_ROOT/Engine/Binaries/Linux/UnrealEditor-Cmd" \
  "$PROJECT_ROOT/FayAvatarRuntime.uproject" \
  -run=PythonScript \
  -script="$PROJECT_ROOT/Plugins/FayMetaHumanEditorTools/Scripts/build_ardy_v30_foundation.py" \
  -unattended -nop4 -nosplash
```

The first build refuses any occupied output destination. To re-validate and
reuse an already reviewed candidate without deleting it:

```bash
FAY_ARDY_V30_REVIEWED_REBUILD=1 \
  "$ENGINE_ROOT/Engine/Binaries/Linux/UnrealEditor-Cmd" \
  "$PROJECT_ROOT/FayAvatarRuntime.uproject" \
  -run=PythonScript \
  -script="$PROJECT_ROOT/Plugins/FayMetaHumanEditorTools/Scripts/build_ardy_v30_foundation.py" \
  -unattended -nop4 -nosplash
```

The rebuild flag does not authorize deletion, arbitrary paths, overwriting
v29, or automatic post-process finalization. After the AnimGraph is built and
reviewed, use `ValidateV30PostProcessInputs` as one preflight. It validates the
reflected contract but does not replace front/side motion capture, face
ownership, contact/foot-slide, disconnect fallback, cook, and soak gates.
