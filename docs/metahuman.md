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

Epic's current setup instructions explain the additional MetaHuman Creator Core
Data required by source builds:
[Getting started with MetaHuman Creator](https://dev.epicgames.com/documentation/en-us/metahuman/getting-started-with-metahuman-creator).

## First test character

Use an included female preset with:

- **UE Optimized** assembly rather than the Cine assembly
- hair cards instead of strand grooms for the first Spark package
- conservative texture sizes
- face/body LODs enabled
- simple included clothing
- one neutral idle and one clear gesture
- an unobstructed face for lip-sync evaluation

The appearance remains independent of Fay. A different preset can be selected
later without changing the backend protocol or bridge.

## Animation quality stages

1. **Presence:** idle, blink, breathing, gaze, and head turns.
2. **Portable mouth test:** map `OnMouthAmplitude` to jaw-open with smoothing.
3. **Expression:** map Fay sentiment/action to a small set of facial poses.
4. **Body language:** map semantic behaviors such as `nod`, `invite`, `think`,
   and `warn` to Animation Montages.
5. **Detailed lip sync:** consume timestamped visemes or add a supported
   audio-to-face system after the basic package is stable.

Amplitude-driven jaw motion proves timing and transport but is not presented as
final photorealistic speech. Realistic flesh deformation comes from the
MetaHuman face rig, materials, correct facial curves, lighting, and a stronger
audio-to-animation layer.

## Performance order

Tune in this order so each change is measurable:

1. Resolution and frame cap
2. Hair cards/groom choice
3. Character LODs
4. Texture resolution and streaming
5. Shadows and ray-tracing features
6. Skin/material quality
7. Background scene complexity
