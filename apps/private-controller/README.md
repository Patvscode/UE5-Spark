# Private full-body stage controller

This responsive controller is the private iPhone/desktop trial surface for the
UE5-Spark digital human. It is intentionally served from the DGX Spark through
Tailscale rather than from a public host.

The current prototype provides:

- live, same-origin text conversation through Fay;
- device speech recognition and speech synthesis when the browser supports it;
- allowlisted `wave`, `explain`, and `listen` actions;
- verified private Ada and Aoi movement replays while Unreal is offline;
- sanitized Fay/ARDY/renderer status; and
- explicit `Portrait` versus pending `FullBody` camera state.

It never connects to Fay's avatar WebSocket as another `User`. All backend
origins, usernames, actions, duration, intensity, media paths, and request sizes
are fixed or bounded by `server/controller_server.py`.

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
./scripts/run-private-controller.sh \
  /private/media-root \
  /path/to/apps/private-controller/dist/client
```

Bind that loopback service to a private Tailscale Serve HTTPS listener. Do not
publish the operational controller through Sites because a public frontend
cannot reach the tailnet-only Fay backend.

## Current boundary

The conversation service is live. The stage is a measured renderer replay until
the reviewed full-body camera package and a private live-video bridge pass their
own reliability gates. The disabled Fab candidate is informational only; its
licensed files never belong in this public repository.
