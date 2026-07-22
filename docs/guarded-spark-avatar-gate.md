# Guarded DGX Spark avatar gate

`scripts/run-spark-avatar-gate.sh` is the outer supervisor for a rendered
qualification run when the Spark needs Voxtral's memory temporarily. It wraps
the existing `run-spark-avatar-soak.sh`; it does not replace the soak runner's
package, rendering, speech, motion, performance, or teardown checks.

The supervisor accepts exactly five arguments:

```text
run-spark-avatar-gate.sh PACKAGE_LAUNCHER FAY_PID PRIVATE_GATE_DIR DURATION_SECONDS TURN_COUNT
```

The private gate directory must be a new, single-component run directory below
an existing `logs-private` or `media-private` root. The supervisor refuses to
reuse it and serializes gates within that private root. A typical production
invocation is:

```bash
FAY_SOAK_CHARACTER=Ada \
FAY_SOAK_EVIDENCE_MODE=production \
./scripts/run-spark-avatar-gate.sh \
  /path/to/cooked/FayAvatarRuntime-Arm64.sh \
  FAY_PID \
  /path/below/logs-private/ada-gate-YYYYMMDDTHHMMSSZ \
  1800 20
```

All existing `FAY_SOAK_*` policy variables pass unchanged to the inner runner.
The supervisor has no extra Unreal-argument channel, so it cannot silently turn
a production gate into a custom launch.

## Exact lifecycle boundary

The only service this script can pause is the fixed user unit
`codex-studio-voxtral-realtime.service`. There is no service-name argument. The
script proves that the unit is active, its exact main process owns the healthy
loopback listener, then arms restoration before issuing the stop. It requires
the old process and listener to be gone before starting Unreal.
The supervisor also monitors that inactive state while the rendered runner is
alive; an unexpected unit or listener return cancels and fails the gate.

Fay and the fixed `ue5-spark-ardy` container are externally managed. The gate
never starts, stops, restarts, or reconfigures either one. It snapshots Fay's
PID, executable, Linux start time, listener bindings, and health. It snapshots
ARDY's container and image identities, host PID, Linux process identity,
restart count, isolation settings, read-only model mount, loopback listener,
and sealed real-provider health. Provider, Horizon8 checkpoint, three-embedding
count, and every immutable identity field must match after the run. The measured
p95 may change as Unreal requests poses, but every snapshot must remain finite,
positive, and below the 400 ms playback buffer.

The rendered-soak runner is launched as one owned process session. Normal exit,
runner failure, shell error, and `HUP`, `INT`, or `TERM` all enter the same
cleanup path. That path cancels and reaps the runner when necessary, confirms
the exact packaged Unreal executable is absent, restores and health-checks a
new Voxtral process, and only then revalidates Fay and ARDY. A forced runner
kill or any restoration/identity failure fails the outer gate.

Before that ownership is committed, two matching Linux process records must
prove the original direct child, start time, process group, session, and
canonical Bash executable. If this adoption fails, the gate does not signal or
wait on the untrusted numeric PID; it fails closed and restores Voxtral.

Once the exact runner PID and Linux start time disappear, the supervisor never
signals or scans that numeric process-group ID again because Linux may reuse
it. It checks the exact packaged Unreal executable separately; any residue
fails qualification and is reported without risking a signal to an unrelated
process.

The script deliberately has no Docker lifecycle call. ARDY recovery remains an
operator action so a failed gate cannot replace or delete private model state.

## Private evidence

The new gate directory keeps:

- `gate-before.txt` and `gate-after.txt`: sanitized identity snapshots and
  hashes of private paths or listener bindings.
- `package-preflight.log`: cooked-package verification before the pause.
- `voxtral-pause.txt`: proof that the fixed unit and listener were inactive,
  plus available unified memory at that point.
- `runner-console.log` and `runner-result.txt`: the owned runner's private
  console and reaping result.
- `soak/`: the complete evidence produced by `run-spark-avatar-soak.sh`.
- `gate-result.txt`: the final outer result, restoration status, Fay/ARDY
  continuity, Unreal absence, and runner status.

Only `gate-result.txt` with `status=passed` is an outer-gate pass. The script
does not print a success message until restoration and all post-run checks have
completed. If the terminal disconnects, inspect these private files rather
than reusing the directory.

## Explicit ARDY recovery diagnostic

`scripts/run-spark-ardy-recovery-gate.sh` is a separate diagnostic-only tool.
Unlike the normal gate, it is allowed to stop one container, but only after it
has repeatedly captured and matched the exact fixed-name real ARDY container,
immutable image ID, host PID/start time, isolation settings, model mount,
loopback port, and sealed health response. There is no container-name, image,
port, service, behavior, or duration argument.

The diagnostic starts a fixed Ada speech/action sequence, stops that one 64-hex
container ID inside a bounded helper, verifies that both its name and port are
unclaimed, and invokes the guarded activator while holding the project activation
lock. An unknown name or port claimant is never stopped or replaced. Every exit
path reconciles the fixed endpoint. Success requires the new real provider to
pass main-path and cleanup validation; a failed activation may safely preserve
only a verified sealed mock, in which case the diagnostic remains failed.

Success requires this ordered runtime evidence:

1. Speech and a generated ten-second `explain` action overlap.
2. Unreal observes ARDY unavailable and completes bounded baked-idle fallback
   while facial speech continues.
3. A new real Horizon8 provider becomes ready.
4. Generated `explain`, `idle`, and `listen` all start and complete.
5. No rejected pose, unavailable, or fallback marker occurs between recovered
   readiness and normal Unreal `PreExit`.

The operational log audit stops at the first `LogInit: Display: PreExit Game.`
after the final `listen` completion. This is deliberate: ARDY client `EndPlay`
clears readiness and emits an unavailable message during normal teardown.
Missing, stale, or early `PreExit` still fails closed, and final checks separately
require the recovered ARDY identity/health, exact Unreal absence, Fay continuity,
Voxtral restoration, and unchanged package seal.

This tool cannot qualify production. Its `recovery-result.txt` is explicitly
diagnostic; run a fresh normal production gate afterward.
