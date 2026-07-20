# Fay MetaHuman Runtime

This source-only runtime plugin connects the decoded PCM already trusted by
`FayAvatarBridge` to Unreal Engine 5.8's local Streaming Audio Driven Animation
model. The model produces learned face controls, mood, and blinks; the adapter
converts them to MetaHuman raw controls and publishes a local Live Link Basic
subject named `FayAudio`.

The adapter intentionally bypasses UE 5.8's higher-level
`MetaHumanLocalLiveLinkSource` module. Despite being labelled Runtime, that
module depends on the Editor-only `MetaHumanPipelineCore` module and is not a
safe LinuxArm64 Game dependency. The lower-level `SpeechAnimationSolver`,
`StreamingADA`, `NNERuntimeORT`, and Live Link modules used here are runtime
modules, and UE 5.8 ships the ONNX Runtime shared library for LinuxArm64.

Generated MetaHuman assets and Epic model content are never copied into this
plugin or repository. They are loaded from each licensed Unreal installation
and included only in that user's cooked package.
