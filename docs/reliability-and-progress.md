# Reliability and private progress

The reliability runner and progress hub are optional project tools. Neither one
starts, stops, reconfigures, or supervises Fay, and neither modifies DGX OS,
drivers, CUDA, or system services.

## Guarded soak test

`scripts/soak-spark-avatar.sh` accepts the exact Unreal PID, exact externally
managed Fay PID, a private output directory, duration, and turn count. It
refuses unrelated processes, discovers Fay's concrete private listener without
printing it, checks both PIDs throughout the run, and records Unreal resident
memory plus available `nvidia-smi` memory data after every turn.

The required validation invocation is 1,800 seconds and 20 turns. Logs must be
written below a private `logs-private` or `media-private` directory and must not
be committed. A passing harness run does not itself prove bounded memory; review
the first, last, and maximum RSS values and the Unreal log for queue, crash, and
facial-solver failures.

## Tailscale progress hub

`scripts/run-progress-hub.sh` binds `tools/progress_hub.py` only to the Spark's
Tailscale IPv4 address on unprivileged port 8474. It requires a private JSON
status document, a real private media root, and a Tailscale agent-board URL.

The server validates a narrow status schema and serves only files explicitly
listed in that document. Absolute paths, traversal, symlinks, directory
listing, arbitrary board hosts, and non-Tailscale binds are rejected. Images
and videos support `HEAD` and single byte ranges for mobile playback. Responses
disable caching, MIME sniffing, and framing and use a restrictive content
security policy.

The source repository contains no private hostname, listener address, media,
status data, authentication material, or licensed MetaHuman capture. Keep the
status document, process log, screenshots, and videos outside Git.

The hub is deliberately a small visibility aid rather than a dependency of the
avatar stack. Unreal, Fay, StreamingADA, and ARDY continue to run if the hub is
stopped.

