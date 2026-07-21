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

## Bounded runtime diagnostics

The default command line preserves the production path: a neutral Live Link
heartbeat is published at 10 Hz while the configured avatar is awake and idle,
and the exact consumer/source contract is audited every frame. Reviewed
idle-dormancy mode suppresses the neutral heartbeat and bounds the same full
health audit to at most one second while frozen. Accepted Fay messages and body
motion state changes still wake the avatar synchronously; a failed periodic
health audit fails open and restores the saved actor/component state. Reviewed
packages also expose two narrow diagnostic overrides:

- `-FayLiveLinkIdleHeartbeat=0` stops only the configured-idle heartbeat.
  Bootstrap neutral frames, speech frames, and action head frames remain
  enabled.
- `-FayLiveLinkHealthInterval=1.0` audits the complete consumer/source contract
  once per second while awake and idle. `0` retains the every-frame awake
  default. Dormancy always caps this interval at one second.

These switches isolate downstream Live Link, MetaHuman deformer, and renderer
allocation behavior. They do not disable StreamingADA or weaken the initial
configuration contract, and they are not production defaults until the
rendered regression and endurance gates pass.

## Fail-closed recovery

The adapter publishes allocation-free state transitions instead of making the
GameMode poll the exact Live Link subject. A lost consumer or a subject that
remains pending is restored once, then may retry only the same reviewed avatar
captured by the first configuration. The retry API accepts no actor, subject,
or asset path. GameMode applies a bounded `1/2/4/8/16` second backoff and waits
for both speech and body motion to become idle before each of five attempts.
The attempt count resets only after ten continuous healthy seconds.

Configuration timeout and attachment pause while Fay speech is pending, so the
jaw fallback owns the complete skipped utterance. Its morph is explicitly
zeroed before learned Live Link takes facial ownership. Source collisions,
invalid schemas, a destroyed configured avatar, and exhausted recovery are
terminal. Every rejected candidate setup reports whether its immediate rollback
was proven. If that rollback or a later configured-avatar restoration fails, the
adapter enters `RestoreFailed` and blocks all later avatar writes—including
EndPlay restoration—instead of repeatedly mutating an unverified actor.
