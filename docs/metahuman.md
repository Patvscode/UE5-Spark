# MetaHuman plan

The sealed v29 Ada/Aoi package is the live reference. The Core27 IK Retargeter,
protocol-v2 body stream, full-body framing, and nine-motion catalog described
below are v30 source candidates until a new package passes visual and reliability
gates.

## Character cost

A test character does not need to be purchased. MetaHuman is included in the
standard Unreal Engine license and is free below Epic's stated revenue
threshold. Review the current
[MetaHuman license](https://www.metahuman.com/license?lang=en-US) for the terms
that apply to your use.

## Asset boundary

Create/import the character through MetaHuman Creator on the licensed Editor
host. This repository intentionally excludes character meshes, DNA, textures,
materials, grooms, clothing, animation data, and Fab packages.

It also excludes Epic's StreamingADA neural model. The model comes from the
authorized Unreal 5.8 installation and is added only to the user's local cook.
Generated Ada content, the model, and packages containing either are
Epic-licensed deployment artifacts and must never be committed or uploaded as
repository releases.

Epic's current setup instructions explain the additional MetaHuman Creator Core
Data required by source builds:
[Getting started with MetaHuman Creator](https://dev.epicgames.com/documentation/en-us/metahuman/getting-started-with-metahuman-creator).

## Assembly scaffold

The repository includes an Editor-only
[MetaHuman assembly helper](../Project/FayAvatarRuntime/Plugins/FayMetaHumanEditorTools/README.md).
It applies Epic's included Ada preset through the UE 5.8 editor API and assembles
an Optimized / High test character into a fresh project path. The project
enables the helper only for Editor targets, while the required
`MetaHumanCharacter` runtime plugin remains enabled for Game builds.

Auto-rigging and high-resolution texture generation use Epic's cloud services.
Complete the Epic account sign-in interactively in a graphical Editor before
attempting the documented unattended workflow. Credentials do not belong in
the project, command line, or repository.

Use this order: run the read-only MetaHuman preflight; complete Epic sign-in in
the graphical Editor if authentication is missing; run the Ada assembly helper;
confirm `/Game/FayMetaHumans` remains ignored; then cook, package, verify, and
run the LinuxArm64 application. Do not add generated assets to Git even when
testing or troubleshooting.

## First test character

Use an included female preset with:

- **UE Optimized** assembly rather than the Cine assembly
- hair cards instead of strand grooms for the first Spark package
- conservative texture sizes
- face/body LODs enabled
- simple included clothing
- a neutral idle and one clear reviewed body gesture for initial validation
- an unobstructed face for lip-sync evaluation

The appearance remains independent of Fay. Another reviewed MetaHuman preset can
be selected without changing the conversation bridge. A non-MetaHuman such as
Casual Girl requires its own face, skeleton/retarget, and wardrobe adapters.

## Direct local facial path

`FayMetaHumanRuntime` implements this source pipeline:

```text
decoded Fay PCM
  -> 16 kHz mono
  -> StreamingADA / NNERuntimeORTCpu
  -> learned facial GUI controls
  -> 251 MetaHuman raw controls
  -> local FayAudio Live Link subject
```

The adapter also supplies the solver's mood input from Fay sentiment/action
metadata. It has compiled with the complete enabled dependency tree for both the
x86-64 Editor and native LinuxArm64 Game targets. The complete path has passed a
fresh MetaHuman-aware cook/package, native Spark model initialization, exact Live
Link consumer checks, visible Ada speech animation, and complete 50 Hz
solve-frame accounting while the window was minimized.

## Animation quality stages

1. **Fallback timing check:** map `OnMouthAmplitude` to jaw-open with smoothing
   if the learned solver is unavailable.
2. **Learned face:** validate the direct StreamingADA controls on assembled Ada.
3. **Presence:** tune idle, breathing, gaze, head turns, solver mood, and blinks.
4. **Live v29 body reference:** retain mapped semantic behaviors such as `nod`,
   `invite`, `think`, and `warn` only as rollback evidence; do not extend its
   unsupported late transform writer.
5. **V30 body language:** build the reviewed Core27 source mesh, IK Rig/
   Retargeter, target post-process AnimBP, and profile/binding, then validate all
   nine catalog motions with full-body front and side views.

Amplitude-driven jaw motion proves timing and transport but is not presented as
final photorealistic speech. Realistic flesh deformation comes from the
MetaHuman face rig, materials, correct facial curves, lighting, and a stronger
audio-to-animation layer. The StreamingADA adapter is intended to provide that
learned facial layer and now does so in the verified native package.

The source contains conservative raw-control head mappings for `nod`, `shake`,
`think`, and `warn`, but they still need final visual tuning. No authored body
animations or montages are required for `wave` or `invite`; reviewed fallbacks
remain available.

The live v29 Horizon8 adapter drives nineteen body bones from pelvis through
both leg/foot chains as well as the spine and arms. It does so by mutating
finalized component-space transforms through unsupported access, using a first-
sample baseline instead of a source-rest/target-rest retarget. Although its
portrait captures show procedural wave and generated upper-body `explain`, the
camera crops the legs and cannot prove correct palms, elbows, knees, feet, root,
or ancestor isolation. V29 must not be described as a natural full-body result.

## V30 retarget candidate

The source-only replacement uses absolute Core27 local rotations and global
joint positions to evaluate a hidden Core27 skeletal mesh. A reviewed Unreal IK
Retargeter consumes that mesh through the target Body's post-process Animation
Blueprint. The main Body animation class remains untouched, and the binding
must prove that face, neck, and head are excluded and the existing detailed
finger pose is preserved. Missing or changed assets disable generated motion
and fall back; the legacy writer is not an acceptable fallback.

Protocol v2 also supplies ordered left-heel, left-toe, right-heel, and right-toe
contacts for foot planting, plus global hand/end/thumb positions for later IK
polish. Source carries sealed per-character full-body presets selected only by
`-FayCameraFraming=FullBody`. A new cook, wide front/side capture, speech overlap,
provider-failure test, Ada/Aoi comparison, and soak are still required before
any of this is called working on Spark. Receiving a Fay action or passing a
source-contract test is never sufficient motion evidence.

## Casual Girl boundary

The selected free Fab Casual Girl is a separate modular UE character, not a
MetaHuman and not yet installed. It declares an Epic-skeleton body and Apple
ARKit facial morphs, so it needs a private UE 5.8/LinuxArm64 import audit, its
own ARDY retarget profile, a 52-morph face adapter, reviewed garment/hair
component mappings, and native performance/reliability gates.

The public wardrobe profile contains only logical preset and slot IDs. Controls
remain disabled while it is `pending_asset_audit`. Full undress is forbidden
unless manual inspection confirms a complete body under every garment at every
LOD; hiding a clothing component does not establish that geometry exists. Fab
assets, private component paths, and cooked packages remain outside Git.

## Performance order

Tune in this order so each change is measurable:

1. Resolution and frame cap
2. Hair cards/groom choice
3. Character LODs
4. Texture resolution and streaming
5. Shadows and ray-tracing features
6. Skin/material quality
7. Background scene complexity
