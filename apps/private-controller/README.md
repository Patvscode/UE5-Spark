# Private full-body stage controller

This responsive controller is the private iPhone/desktop trial surface for the
UE5-Spark digital human. It is intentionally served from the DGX Spark through
Tailscale rather than from a public host.

The current prototype provides:

- live, same-origin text conversation through Fay;
- device speech recognition and speech synthesis when the browser supports it;
- allowlisted `wave`, `explain`, and `listen` actions;
- a default-on, bounded Alive loop that autonomously selects packaged behaviors
  with varied timing and intensity while the live renderer is healthy;
- a separate free-text movement director backed by the shared reviewed catalog;
- deterministic movement duration, intensity, root mode, and renderer routing even
  when the optional local LLM supplies the catalog classification;
- a local, character-neutral AI-control selector: deterministic catalog matching,
  generic AI motion (the restart-safe default), or explicitly opted-in asset-aware
  architecture mode;
- honest `staged` results for jumping jacks, jogging/running in place, stretching,
  and relaxed dance until those ARDY motions are packaged in Unreal;
- disabled Casual Girl outfit/garment controls using sealed IDs while the
  asset profile and complete base body remain unreviewed;
- a private same-origin live-frame endpoint when the packaged renderer and
  guarded JPEG producer are both active;
- verified private Ada and Aoi movement replays while Unreal is offline;
- sanitized Fay/ARDY/renderer status; and
- explicit `Portrait` versus pending `FullBody` camera state.
- an explicit opt-in, browser-local front-camera preview that sends no frames to
  Fay or Unreal until a reviewed gaze bridge exists.

It never connects to Fay's avatar WebSocket as another `User`. All backend
origins, usernames, actions, duration, intensity, media paths, and request sizes
are fixed or bounded by `server/controller_server.py`.

The movement classifier defaults to the existing `--llm-model`. A separate
reviewed model can be A/B tested with `--motion-planner-model` without changing
chat. Its output is advisory: the server accepts only one catalog ID from
`config/motion-catalog.json` and never accepts model-provided timing, joints,
paths, URLs, or root behavior.

The mode contract is sealed by `config/character-ai-control.json` and its public
schema. `deterministic` adds `provider: "baked"` to each action and bypasses the
motion classifier. `ai_motion` sends user-authored intent to the classifier and
adds `provider: "hybrid"`. The controller-wide `asset_aware_ai` transition
requires explicit UI/API acknowledgement, uses the same hybrid renderer route,
and may additionally send
one versioned runtime-context object containing only the selected profile ID,
wardrobe preset ID, camera framing, bounded stage zoom, and renderer state.
Other modes reject that context object. The current v1 adapter does not contain
mesh, texture, skeleton, morph, image, animation, arbitrary asset path, or raw
renderer data; future adapters can expand the capability through a new
versioned, validated schema. A caller that omits `provider` keeps the historical
hybrid behavior. The switch resets to `ai_motion` when the controller restarts
and is character-neutral. Every connected phone or desktop reflects the same
selection, and disabling asset-aware mode from any client changes the shared
controller back to `ai_motion`:
license and tag information remains informational, the local user chooses which
capability to enable and is responsible for that use, and the runtime has no
character-specific license allowlist.

Wardrobe state is loaded fail-closed from
`config/wardrobe-profiles/CasualGirl.pending.json`. The API exposes only the
reviewed preset/slot IDs and audit state; the Fab URL and Unreal asset root are
not returned to the browser.

## Local verification

```bash
npm install --prefer-offline --no-audit --no-fund
npm run build
npm run test:server
npm run test:sites
```

Private media is required at runtime and is deliberately ignored by Git. On
Spark, run the built client with the guarded project launcher:

```bash
install -d -m 0700 "$XDG_RUNTIME_DIR/ue5-spark-avatar-live"
./scripts/run-private-controller.sh \
  /private/media-root \
  /path/to/apps/private-controller/dist/client \
  "$XDG_RUNTIME_DIR/ue5-spark-avatar-live"
```

After the exact 1280×720 packaged Unreal window is running, publish its private
view-only preview into that directory:

```bash
./scripts/run-avatar-live-preview.sh \
  /path/to/FayAvatarRuntime/Binaries/LinuxArm64/FayAvatarRuntime \
  "$XDG_RUNTIME_DIR/ue5-spark-avatar-live"
```

The producer captures only the one X11 window whose `_NET_WM_PID` matches the
reviewed executable. It writes an atomic 960×540 JPEG at 5–15 FPS, opens no
listener, records no audio, and stops only its own verified FFmpeg child. The
controller serves only `/live/frame.jpg`; `/api/status` reports `stream: true`
only while Fay confirms the renderer connection and the private JPEG is fresh.

Bind that loopback service to a private Tailscale Serve HTTPS listener. Do not
publish the operational controller through Sites because a public frontend
cannot reach the tailnet-only Fay backend.

## Current boundary

The conversation service is live. The stage must continue to fall back to a
measured renderer replay whenever the reviewed renderer or the live-frame
producer is unavailable. This JPEG path is a low-latency private trial surface,
not production Pixel Streaming: it has no embedded audio and its performance
still requires a rendered Spark diagnostic. The disabled Fab candidate is
informational only; its licensed files never belong in this public repository.
