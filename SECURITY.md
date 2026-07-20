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
- Generated Ada assets, the StreamingADA model, and cooked packages containing
  them are local Epic-licensed deployment content. Never upload them to this
  repository, an issue, an artifact, or a GitHub release.
- Treat Editor/cooker logs, crash dumps, screenshots, and diagnostic captures as
  private until they have been reviewed for credentials, account details,
  machine paths, and network addresses. This source-only repository rejects
  those artifact types.
- Complete Epic authentication only through the interactive browser flow. Do
  not place credentials or exchange tokens in command lines or captured logs.

Please report a suspected vulnerability privately through GitHub's security
advisory feature instead of opening a public issue with exploit details.
