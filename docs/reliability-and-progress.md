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
be committed. The harness now fails when RSS grows by more than 256 MiB across
the latter half of a run; override that explicit limit only with
`FAY_SOAK_MAX_TAIL_RSS_GROWTH_KB`. DGX Spark does not expose a separate
`memory.used` value through `nvidia-smi` for its unified memory, so the report
records `-1` for that field and treats process RSS as the enforceable memory
signal. The harness snapshots the packaged runtime log at startup and requires
at least one new facial summary per requested turn. Every summary must contain
exactly 50 solver frames per speech second plus the configured 10-frame tail,
and facial p95 must remain at or below 20 ms. The p95 ceiling is explicitly
adjustable with `FAY_SOAK_MAX_FACE_P95_MS`; queue failures, render-driver
errors, and crashes still require log review.

Run long tests only when another project is not saturating the shared GPU. A
kernel NVIDIA Xid is an infrastructure failure even when Fay and the HTTP test
harness remain healthy; preserve the kernel and Unreal evidence and rerun after
the conflicting workload has ended. The harness records utilization and aborts
after three consecutive samples above 85 percent; that guard can be adjusted
explicitly with `FAY_SOAK_MAX_GPU_UTILIZATION_PERCENT`. The packaged avatar
launcher also refuses three consecutive startup samples above 85 percent
(`UE5_SPARK_MAX_START_GPU_UTILIZATION`) before it creates an Unreal process.
The packaged avatar caps rendering at 30 FPS to retain compute headroom for
speech and motion rather than rendering unused frames as quickly as possible.

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
