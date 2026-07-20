# MCP integration boundary

MCP belongs in Fay, not in the Unreal runtime. Fay is the conversation and
tool gateway: it connects to upstream MCP servers, decides when a tool may be
called, keeps credentials and mutable tool state, and exposes selected tools to
other MCP clients. Unreal remains a renderer and receives only normalized
presentation events.

```text
MCP servers (stdio or SSE) <----> Fay <----> external MCP clients
                                  |
                                  +-- avatar WebSocket --> Unreal
                                  +-- local WAV/HTTP ----> Unreal
```

This boundary keeps API keys, MCP arguments, raw tool results, and tool
authorization out of the packaged application. Fay turns an approved result
into text, speech, sentiment, an optional semantic action, and optional lip
data; the `FayAvatarBridge` turns those fields into presentation behavior.
Unreal should never execute a tool merely because an avatar event contains
text that resembles a command.

## Companion Fay deployment

The public companion implementation is the
[`agent/dgx-spark` branch of Patvscode/Fay](https://github.com/Patvscode/Fay/tree/agent/dgx-spark).
Its example deployment uses these interfaces:

| Interface | Default port | Consumer |
|---|---:|---|
| Fay HTTP/API and audio | `5000` | Unreal audio fetches and API clients |
| MCP connection administration | `5010` | Backend operator only |
| Fay MCP SSE endpoint | `8766` | External MCP clients |
| Fay avatar WebSocket | `10002` | Unreal renderer |

Fay's SSE paths are configurable; the example uses `/sse` and `/messages`.
Upstream stdio/SSE connections are defined in the deployment's
`mcp_servers.json`, while the SSE listener is configured with the documented
`FAY_MCP_SSE_*` environment variables. Enabled upstream tools are exposed by
Fay with namespaced names such as `server_<id>__<tool>`, avoiding collisions
between servers.

When Fay and the packaged application share the Spark, keep the avatar and
audio connections on loopback:

```text
http://127.0.0.1:5000
ws://127.0.0.1:10002
http://127.0.0.1:8766/sse
```

Keep secrets in Fay's user-owned configuration, never in this repository or a
cooked Unreal package. Do not expose these unauthenticated example endpoints
on `0.0.0.0` or the public Internet. If a renderer or MCP client must be
remote, use a private authenticated network and apply authentication at the
service boundary.

## Guarded Spark stack launch

With Fay and its optional MCP endpoints already running, launch the packaged
avatar through the repository's discovery wrapper:

```bash
./scripts/run-spark-digital-human.sh \
  /path/to/FayAvatarRuntime-Arm64.sh
```

The normal-user wrapper discovers existing non-global Fay HTTP, avatar, MCP
administration, and MCP SSE listeners; probes them without printing or baking
their addresses into configuration; exports the `FAY_*` endpoints needed by
Unreal; and delegates to `run-cooked-package.sh`. It does not start, stop, or
reconfigure Fay/MCP and does not change service or system configuration.

MCP readiness is required by default. For an intentionally MCP-free run, skip
only the MCP probes:

```bash
UE5_SPARK_REQUIRE_MCP=0 ./scripts/run-spark-digital-human.sh \
  /path/to/FayAvatarRuntime-Arm64.sh
```

See [the Fay protocol](fay-protocol.md) for the renderer event contract.
