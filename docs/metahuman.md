# MetaHuman plan

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
- a neutral idle, with one clear body gesture to be added later
- an unobstructed face for lip-sync evaluation

The appearance remains independent of Fay. A different preset can be selected
later without changing the backend protocol or bridge.

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
x86-64 Editor and native LinuxArm64 Game targets. A fresh MetaHuman-aware cook
and package, Spark model initialization, and visible Ada animation remain open
gates.

## Animation quality stages

1. **Fallback timing check:** map `OnMouthAmplitude` to jaw-open with smoothing
   if the learned solver is unavailable.
2. **Learned face:** validate the direct StreamingADA controls on assembled Ada.
3. **Presence:** tune idle, breathing, gaze, head turns, solver mood, and blinks.
4. **Body language:** later map semantic behaviors such as `nod`, `invite`,
   `think`, and `warn` to reviewed animations.

Amplitude-driven jaw motion proves timing and transport but is not presented as
final photorealistic speech. Realistic flesh deformation comes from the
MetaHuman face rig, materials, correct facial curves, lighting, and a stronger
audio-to-animation layer. The StreamingADA adapter is intended to provide that
learned facial layer, but it is not yet a verified result.

No gesture animations, montages, or semantic-to-body mappings are currently
included. Receiving a Fay action event is not evidence that the body moved.

## Performance order

Tune in this order so each change is measurable:

1. Resolution and frame cap
2. Hair cards/groom choice
3. Character LODs
4. Texture resolution and streaming
5. Shadows and ray-tracing features
6. Skin/material quality
7. Background scene complexity
