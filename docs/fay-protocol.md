# Fay avatar protocol

`FayAvatarBridge` connects to Fay's digital-human WebSocket and registers the
renderer:

```json
{"Username":"User","Output":true}
```

The same username must be used when a chat request is submitted so Fay routes
the response to that renderer.

## Accepted avatar event

The bridge accepts `Topic: human` messages whose `Data.Key` is `audio`:

```json
{
  "Topic": "human",
  "Data": {
    "Key": "audio",
    "Text": "Hello.",
    "HttpValue": "http://127.0.0.1:5000/audio/example.wav",
    "CONV_ID": "conversation-id",
    "CONV_MSG_NO": 1,
    "Time": 0.8,
    "Sentiment": 0.25,
    "IsFirst": true,
    "IsEnd": true,
    "Action": {
      "code": "greet",
      "behavior": "wave",
      "affect": "friendly",
      "intensity": 0.7,
      "priority": 1,
      "sentimentHint": 0.25
    },
    "Lips": [
      {"Lip": "viseme_aa", "Time": 90}
    ]
  }
}
```

Fields beyond `Topic`, `Data`, and `Key` are optional. An audio URL is required
only for a message that should play speech.

It also accepts a constrained action-only event. This does not fetch audio or
interrupt speech that is already playing:

```json
{
  "Topic": "human",
  "Data": {
    "Key": "action",
    "Time": 1.5,
    "Action": {
      "code": "mcp.wave",
      "behavior": "wave",
      "affect": "neutral",
      "intensity": 0.7,
      "priority": 50,
      "sentimentHint": 0.0
    }
  },
  "Username": "User"
}
```

The body-motion component independently revalidates the behavior allowlist and
bounds intensity and duration. Arbitrary prompts and pose arrays are rejected
at this public boundary.

## Blueprint events

| Event | Purpose |
|---|---|
| `OnConnectionStateChanged` | Display/monitor reconnect state |
| `OnMessageReceived` | Text, sentiment, action, sequence, and optional visemes |
| `OnSpeechStarted` | Begin face/body speech animation |
| `OnMouthAmplitude` | Portable smoothed 0–1 jaw-open signal |
| `OnSpeechFinished` | Return to idle and advance conversation animation |
| `OnBridgeError` | Surface bounded queue, transport, URL, decode, or playback failures |

## Audio contract

The minimal decoder accepts RIFF/WAVE PCM16, mono or stereo, at 8–192 kHz.
Compressed WAV, MP3, float WAV, and RF64 are rejected deliberately. Add another
decoder only if the chosen TTS backend actually requires it.

The default trusted audio base is:

```text
http://127.0.0.1:5000/audio/
```

URLs must use the same normalized scheme, host, and port and contain one simple
`.wav` filename beneath that path. Query strings, fragments, user information,
percent escapes, traversal-like names, and nested paths are rejected.

See the plugin's own
[README](../Project/FayAvatarRuntime/Plugins/FayAvatarBridge/README.md) for the
full queue, playback, and network-safety behavior.
