# Security

## Supported version

Only the latest revision of the `main` branch is supported during this
engineering-preview phase.

## Deployment guidance

- Keep Fay's HTTP and WebSocket endpoints on `127.0.0.1` when Unreal and Fay
  run on the same Spark.
- Do not expose Fay or the avatar bridge directly to an untrusted network
  without authentication, TLS, and an outbound network policy.
- The bridge accepts audio only from its configured origin and simple `.wav`
  paths, but the trusted Fay endpoint must not redirect those requests.
- Never commit credentials, private keys, `.env` files, Unreal source, or
  licensed character assets.

Please report a suspected vulnerability privately through GitHub's security
advisory feature instead of opening a public issue with exploit details.
