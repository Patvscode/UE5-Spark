# Fay Avatar Bridge for Unreal Engine 5.8

This is a source-only Unreal runtime plugin for connecting a packaged avatar
application to Fay without the paid BlueprintWebSocket, JSON Pro, or Runtime
Audio Importer plugins.

It uses only Unreal Engine modules:

- `WebSockets` for Fay's digital-human socket on port `10002`
- `HTTP` for the audio URL supplied by Fay
- `Json` for the Fay message and registration payloads
- `USoundWaveProcedural` for runtime PCM16 WAV playback

There are no bundled libraries, precompiled binaries, editor modules, or
platform-specific build rules in this plugin. UE 5.8's WebSockets and HTTP
modules select their Unix libraries through `Target.Architecture.LinuxName`,
including the `aarch64-unknown-linux-gnueabi` Linux ARM64 target.

## Add it to a project

1. Copy the `FayAvatarBridge` directory into `<Project>/Plugins/`.
2. Regenerate project files or open the project and allow Unreal to build it.
3. Add **Fay Avatar Bridge Component** to the actor that owns the avatar.
4. Keep `WebSocketUrl` as `ws://127.0.0.1:10002` when Fay and the packaged
   application run on the same machine.
5. Keep the component `Username` identical to the user used when submitting a
   request to Fay. The default is `User`.

The component sends this registration after the socket opens:

```json
{"Username":"User","Output":true}
```

It accepts Fay messages with `Topic=human` and `Data.Key=audio`, queues them in
arrival order, downloads one `HttpValue` at a time, and plays each result. The
pending queue and duplicate-key history are bounded by
`MaximumPendingAudioMessages` and `MaximumRememberedMessageKeys`; when the
pending queue is full, the bridge preserves already-queued speech and drops new
audio with one `On Bridge Error` notification until the queue drains.

## Blueprint events

- `On Message Received`: text, sentiment, semantic action, conversation
  sequence, and any server-provided visemes
- `On Speech Started`: the message and decoded audio duration
- `On Speech Finished`: completion of the finite WAV segment
- `On Mouth Amplitude`: a smoothed 0–1 RMS value suitable for a first-pass jaw
  control
- `On Connection State Changed` and `On Bridge Error`: health reporting

For a first MetaHuman test, map `On Mouth Amplitude` to a jaw-open Control Rig
input. Map `Message.Action.Behavior` from `On Message Received` to local
Animation Montages such as `nod`, `invite`, or `think`.

If Fay supplies its optional `Lips` array, each `FFayAvatarViseme` contains an
OVR viseme name and duration in milliseconds. The plugin intentionally exposes
that timing rather than binding it to a particular MetaHuman rig. Fay currently
generates those detailed visemes only through its Windows OVR helper, so the
amplitude event is the portable Linux ARM64 fallback, not final photorealistic
lip sync.

## Current audio contract

The minimal decoder intentionally accepts a narrow, deterministic format:

- RIFF/WAVE, little endian
- PCM format tag 1 (including PCM `WAVE_FORMAT_EXTENSIBLE`)
- signed 16-bit interleaved samples
- mono or stereo
- 8–192 kHz

Current Fay WAV output is PCM16 mono. MP3, compressed WAV, RF64, and floating
point WAV are rejected with an `On Bridge Error` event. Add another source
decoder only if a selected TTS backend actually emits one of those formats.

`USoundWaveProcedural` pads an empty FIFO with silence instead of reporting
end-of-stream. The component appends one engine-sized procedural callback of
silence, waits for that PCM byte queue to drain, allows `PlaybackTailSeconds`
for the render buffer, requests `UAudioComponent::Stop`, and advances the queue
from Unreal's native `OnAudioFinished` event. The silent callback prevents a
zero-byte FIFO observation from cutting off speech that has only just entered
the mixer buffer, including at low sample rates. `PlaybackWatchdogGraceSeconds`
is a fallback if PCM never drains or the audio device never acknowledges that
stop; a watchdog expiry raises `On Bridge Error` and does not claim a normal
`On Speech Finished` event. It also replaces the audio component so a stale
audio-thread active count cannot poison later utterances. An unexpected native
finish is treated as an error rather than successful speech. The sound wave
remains referenced as a `UPROPERTY` until playback stops so garbage collection
cannot remove it.

## Network safety and deployment

An audio URL is accepted only when its normalized scheme, host, and port match
`AudioBaseUrl`, and when its path contains one simple `.wav` filename directly
below that base. Userinfo, query strings, fragments, percent escapes, nested
paths, and traversal-like filenames are rejected. The all-on-Spark default is
`http://127.0.0.1:5000/audio/`.

Responses stream into a bounded buffer instead of Unreal's ordinary
unrestricted response array. A body chunk or declared `Content-Length` beyond
`MaximumAudioBytes` aborts the request before the bridge decodes it. The bridge
also requires the final effective URL to equal the requested URL exactly.

UE 5.8's public `IHttpRequest` API does not expose a per-request switch that
turns libcurl redirect following off. Effective-URL validation therefore occurs
after the backend may have contacted the redirect target. The strict
`AudioBaseUrl` and single-filename rule make the normal local Fay file route the
only request entry point, but that trusted endpoint still must not issue
redirects. When Fay is not local, enforce the same origin rule at an outbound
proxy or network policy as defense in depth.

UE 5.8 also applies its engine-level `Online.HttpManager` URL filter to both
HTTP and libwebsockets. An empty filter allows requests. If the project already
defines an allowlist, include Fay explicitly in the project's
`Config/DefaultEngine.ini` instead of disabling the filter:

```ini
[Online.HttpManager http]
+AllowedDomains=127.0.0.1
+AllowedDomains=localhost

[Online.HttpManager ws]
+AllowedDomains=127.0.0.1
+AllowedDomains=localhost
```

Use matching `https` and `wss` sections when TLS is enabled.

For the all-on-Spark layout:

```text
Fay HTTP       http://127.0.0.1:5000
Fay avatar WS  ws://127.0.0.1:10002
Unreal runtime packaged for LinuxArm64
```

Build the plugin as part of the packaged project. Do not copy an x86-64 plugin
binary into the ARM64 package; there should be no `Binaries/` directory in this
source plugin before the Unreal build.

## Deliberate non-goals

- It does not include or redistribute paid Fab plugins.
- It does not create or license a MetaHuman character.
- It does not perform neural audio-to-face inference.
- It does not require the Unreal Editor at runtime.

The next facial-quality layer should consume the same `On Speech Started`
audio/message boundary and drive MetaHuman facial curves without changing the
Fay transport.
