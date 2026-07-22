from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "run-spark-ardy-recovery-gate.sh"
ACTIVATOR_PATH = REPO_ROOT / "scripts" / "activate-ardy-provider.sh"


def function_source(source: str, name: str, next_name: str) -> str:
    start = source.index(f"{name}() {{")
    end = source.index(f"\n{next_name}() {{", start)
    return source[start:end]


class ArdyRecoveryGateStaticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = SCRIPT_PATH.read_text(encoding="utf-8")
        cls.activator = ACTIVATOR_PATH.read_text(encoding="utf-8")

    def test_bash_syntax_exact_arity_and_diagnostic_scope(self) -> None:
        for script in (SCRIPT_PATH, ACTIVATOR_PATH):
            result = subprocess.run(
                ("bash", "-n", str(script)),
                cwd=REPO_ROOT,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run(
            ("bash", str(SCRIPT_PATH)),
            cwd=REPO_ROOT,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(result.returncode, 64)
        self.assertIn("if (( $# != 3 )); then", self.source)
        self.assertIn("PACKAGE_LAUNCHER FAY_PID PRIVATE_GATE_DIR", self.source)
        self.assertIn("scope=diagnostic-only-not-production-qualification", self.source)

    def test_fixed_runtime_and_package_contract(self) -> None:
        required_commands = self.source[
            self.source.index("for command_name in ") : self.source.index(
                "done\n\nscript_dir=", self.source.index("for command_name in ")
            )
        ]
        self.assertIn(" cp ", required_commands)
        self.assertIn(" mv ", required_commands)
        for marker in (
            "readonly RUN_DURATION_SECONDS=180",
            "readonly RUN_TURN_COUNT=1",
            "export FAY_SOAK_CHARACTER=Ada",
            "export FAY_SOAK_EXPECTED_RES_X=1280",
            "export FAY_SOAK_EXPECTED_RES_Y=720",
            "export FAY_SOAK_EVIDENCE_MODE=diagnostic",
            "${package_launcher##*/} == FayAvatarRuntime-Arm64.sh",
            '"$package_verifier" "$package_launcher_dir"',
            "package_launcher_sha256",
            "unreal_executable_sha256",
            "package_seal_sha256",
            "verify_package_postflight",
        ):
            self.assertIn(marker, self.source)
        self.assertNotIn("20260721-v29", self.source)
        self.assertNotIn("592cd46a35a1a870", self.source)
        self.assertNotIn("75b024c4867cc866", self.source)

    def test_only_exact_captured_container_can_be_stopped(self) -> None:
        stop_calls = re.findall(r"docker\s+stop[^\n]*", self.source)
        self.assertEqual(stop_calls, ['docker stop --time 2 "$container_id"'])
        stop_helper = function_source(
            self.source, "docker_stop_exact_bounded", "capture_process_record"
        )
        self.assertIn('[[ $container_id =~ ^[0-9a-f]{64}$ ]]', stop_helper)
        self.assertIn(
            'run_bounded_isolated 30 docker stop --time 2 "$container_id"',
            stop_helper,
        )
        bounded_helper = function_source(
            self.source, "run_bounded_isolated", "docker_stop_exact_bounded"
        )
        self.assertIn("setsid --wait timeout --foreground", bounded_helper)
        self.assertIn("--signal=TERM --kill-after=5", bounded_helper)
        stop_function = function_source(
            self.source, "stop_exact_old_ardy", "verify_old_ardy_absent_without_claimant"
        )
        for marker in (
            "continuity_guard",
            "container_id_for_name",
            '[[ $current_ardy_id == "$old_container_id" ]]',
            'capture_real_ardy ardy_pre_stop "$current_ardy_id"',
            "ardy_immutable_snapshots_equal ardy_before ardy_pre_stop",
            'image_id "$ARDY_IMAGE"',
        ):
            self.assertIn(marker, stop_function)
            self.assertLess(
                stop_function.index(marker),
                stop_function.index("docker_stop_exact_bounded"),
            )
        self.assertIn(
            'docker_stop_exact_bounded "$old_container_id"', stop_function
        )
        self.assertNotIn("docker stop", stop_function)
        self.assertLess(
            stop_function.index("ardy_stop_in_progress=1"),
            stop_function.index("outage_committed=1"),
        )
        self.assertIn("loopback_listener_owned_by_pid", self.source)
        listener_function = function_source(
            self.source, "loopback_listener_owned_by_pid", "port_is_unused"
        )
        self.assertNotRegex(
            listener_function,
            r"listeners=\$\(ss[^\n]*\|\| true",
        )

    def test_container_mount_health_and_new_identity_are_exact(self) -> None:
        for marker in (
            'len(mounts) != 1',
            'mount.get("Destination") != "/models"',
            'mount.get("RW") is not False',
            'host.get("AutoRemove") is not True',
            'host.get("NetworkMode") != "host"',
            'host.get("ReadonlyRootfs") is not True',
            'record.get("RestartCount") != 0',
            'config.get("User") != expected_user',
            're.search(r"(?:TOKEN|PASSWORD|SECRET|CREDENTIAL|API_KEY)$"',
            're.search(r"(?:^|[^A-Za-z0-9])hf_[A-Za-z0-9]{10,}"',
            'loopback_listener_owned_by_pid "$ARDY_PORT" "$ardy_pid"',
            'value.get("checkpoint") != "ARDY-Core-RP-20FPS-Horizon8"',
            'value["embeddingCount"] != 3',
            '${ardy_recovered[1]} != "${ardy_before[1]}"',
            '${ardy_recovered[4]} != "${ardy_before[4]}"',
            '${ardy_recovered[14]} != "${ardy_before[14]}"',
            'activation_target_records_match "${ardy_recovered[1]}"',
        ):
            self.assertIn(marker, self.source)

    def test_original_real_reconciliation_requires_stable_exact_identity(self) -> None:
        stable_capture = function_source(
            self.source,
            "capture_exact_original_real_stably",
            "reconcile_recovery_endpoint",
        )
        for marker in (
            "for attempt in $(seq 1 5)",
            "container_id_for_name",
            '[[ $current_id == "$expected_id" ]]',
            'capture_real_ardy observed "$current_id"',
            "ardy_immutable_snapshots_equal ardy_before observed",
            "run_bounded_isolated 2 sleep 1",
        ):
            self.assertIn(marker, stable_capture)
        reconcile = function_source(
            self.source,
            "reconcile_recovery_endpoint",
            "prepare_emergency_activation_attempt",
        )
        self.assertIn(
            'capture_exact_original_real_stably reconciled_real "$current_id"',
            reconcile,
        )
        self.assertIn("exact-original-real-stable", reconcile)

    def test_action_api_is_fixed_typed_and_ordered(self) -> None:
        self.assertEqual(self.source.count("/api/avatar/action"), 1)
        self.assertNotIn("/transparent-pass", self.source)
        for marker in (
            "{\"behavior\":\"%s\",\"intensity\":%s,\"duration\":%s,\"user\":\"User\"}",
            'set(value) != {',
            '"ok", "behavior", "intensity", "duration"',
            'value["ok"] is not True',
            'value["behavior"] != sys.argv[2]',
            'isinstance(observed, bool)',
            "ARDY loopback service is unavailable; baked fallback remains active.",
            "began a bounded fallback to baked idle",
            "Completed bounded ARDY action 'explain' and returned to baked idle.",
            "Rejected ARDY pose batch",
            "unavailable_line < facial_summary_line",
            "unavailable_line < speech_finished_line",
            "first_action_cursor",
            "stop_cursor",
            "activation_cursor",
            "second_action_cursor",
            "idle_action_cursor",
            "listen_action_cursor",
            "generated retarget=ready",
            "Using ARDY generated motion provider for 'idle'",
            "Using ARDY generated motion provider for 'listen'",
        ):
            self.assertIn(marker, self.source)
        speech_start = self.source.index("speech_start_line=")
        first_post = self.source.index(
            'post_explain_action "$FIRST_ACTION_DURATION"', speech_start
        )
        first_marker = self.source.index("bounded_seconds=10.00", first_post)
        finished_check = self.source.index("finished_during_dispatch=", first_marker)
        stop = self.source.index("stop_exact_old_ardy", first_marker)
        recovery = self.source.index("attempt_recovery", stop)
        ready = self.source.index("recovered_ready_line=", recovery)
        second_post = self.source.index('post_explain_action "$SECOND_ACTION_DURATION"', ready)
        self.assertLess(speech_start, first_post)
        self.assertLess(first_post, first_marker)
        self.assertLess(first_marker, finished_check)
        self.assertLess(finished_check, stop)
        self.assertLess(stop, recovery)
        self.assertLess(recovery, ready)
        self.assertLess(ready, second_post)

    def test_timing_sensitive_guards_use_the_exact_runtime_snapshot(self) -> None:
        snapshot = function_source(
            self.source, "validate_fay_runtime_snapshot", "array_digest"
        )
        for marker in (
            'process_matches_identity "$fay_pid" "$fay_exe" "$fay_starttime"',
            "capture_fay_listener_bindings bindings",
            "arrays_are_equal fay_listener_bindings_before bindings",
        ):
            self.assertIn(marker, snapshot)
        self.assertNotIn("fay_http_ready", snapshot)
        self.assertNotIn("curl", snapshot)

        timing_sensitive_regions = (
            function_source(
                self.source, "wait_for_runner_completion", "find_marker_line_after"
            ),
            function_source(self.source, "continuity_guard", "wait_for_marker_after"),
            function_source(self.source, "post_motion_action", "post_explain_action"),
        )
        for region in timing_sensitive_regions:
            self.assertIn("validate_fay_runtime_snapshot", region)
            self.assertNotIn("validate_fay_identity", region)

        # Full HTTP health checks still protect preflight, final verification,
        # and exit cleanup, but must not consume the live speech/action window.
        self.assertEqual(
            self.source.count(
                'validate_fay_identity "$fay_exe" "$fay_starttime"'
            ),
            4,
        )

    def test_exit_image_identity_checks_are_shell_predicates(self) -> None:
        on_exit = function_source(self.source, "on_exit", "handle_signal")
        self.assertNotRegex(on_exit, r"(?m)^\s*\$\(image_id ")
        source_lines = self.source.splitlines()
        for index, line in enumerate(source_lines):
            if "$(image_id" not in line or not re.search(r"\)\s*(?:==|!=|=~)", line):
                continue
            logical_start = index
            while logical_start > 0 and source_lines[logical_start - 1].rstrip().endswith(
                "\\"
            ):
                logical_start -= 1
            logical_prefix = "\n".join(source_lines[logical_start : index + 1])
            comparison_offset = logical_prefix.index("$(image_id")
            before_comparison = logical_prefix[:comparison_offset]
            self.assertGreater(
                before_comparison.count("[["),
                before_comparison.count("]]"),
                f"image comparison is outside [[ ]] on line {index + 1}",
            )
        self.assertEqual(
            on_exit.count(
                '[[ $(image_id "$ARDY_IMAGE" || true) == '
                '"$ardy_expected_image_id" ]]'
            ),
            2,
        )
        self.assertIn(
            '[[ $(image_id "$ARDY_ROLLBACK_IMAGE" || true) == \\\n'
            '                "$ardy_rollback_image_id" ]]',
            on_exit,
        )
        self.assertEqual(on_exit.count("ensure_ardy_endpoint_on_exit"), 2)
        self.assertIn(
            "ardy_immutable_snapshots_equal ardy_rollback final_mock", on_exit
        )

    def test_runner_start_barrier_precedes_any_unreal_launch(self) -> None:
        for marker in (
            "mkfifo -m 600",
            'IFS= read -r observed_token <&7',
            "abort_runner_start_barrier",
            "start-barrier-aborted-without-signals",
            "release_runner_start_barrier",
            "runner_start_released=1",
            "runner_release_in_progress=1",
        ):
            self.assertIn(marker, self.source)
        capture_done = self.source.index("runner_identity_capture_in_progress=0")
        abort_on_failure = self.source.index("abort_runner_start_barrier", capture_done)
        release = self.source.index("release_runner_start_barrier", abort_on_failure)
        first_action = self.source.index("initial_ready_line=", release)
        self.assertLess(capture_done, abort_on_failure)
        self.assertLess(abort_on_failure, release)
        self.assertLess(release, first_action)
        release_function = function_source(
            self.source, "release_runner_start_barrier", "cancel_and_reap_runner"
        )
        self.assertLess(
            release_function.index("runner_start_released=1"),
            release_function.index("printf '%s\\n'"),
        )
        self.assertIn("runner_release_in_progress == 1", self.source)

    def test_activator_lifecycle_has_no_outer_kill_timeout(self) -> None:
        recovery = function_source(self.source, "attempt_recovery", "stop_exact_old_ardy")
        self.assertIn(
            'ARDY_ACTIVATION_LOCK_FD=8 "$activator" "$ardy_models_root"', recovery
        )
        self.assertNotIn("timeout", recovery)
        self.assertNotIn("kill-after", recovery)
        self.assertNotIn("kill -", recovery)

    def test_final_log_audit_rejects_all_late_degraded_states(self) -> None:
        post_recovery_function = function_source(
            self.source, "validate_post_recovery_log", "restore_voxtral"
        )
        marker_count_function = function_source(
            self.source, "marker_count_between", "post_motion_action"
        )
        for marker in (
            "late_rejected_count",
            "late_unavailable_count",
            "late_generated_fallback_count",
            "late_neutral_explain_count",
            "post_recovery_audit_end_line",
            "LogInit: Display: PreExit Game.",
            "validate_post_recovery_log \"$recovered_ready_line\" \"$listen_complete_line\"",
        ):
            self.assertIn(marker, self.source)
        self.assertIn(
            "(( last_runtime_line < post_recovery_audit_end_line ))",
            post_recovery_function,
        )
        self.assertIn(
            "NR > after && NR < before",
            marker_count_function,
        )
        for evidence in (
            '"post_recovery_audit_end_line=$post_recovery_audit_end_line"',
            '"post_recovery_rejected_pose_batches=$late_rejected_count"',
            '"post_recovery_unavailable_transitions=$late_unavailable_count"',
            '"post_recovery_generated_fallbacks=$late_generated_fallback_count"',
            '"post_recovery_neutral_explain_fallbacks=$late_neutral_explain_count"',
        ):
            self.assertEqual(self.source.count(evidence), 2)

    def test_voxtral_fay_locks_and_signal_cleanup_are_fixed(self) -> None:
        for marker in (
            "readonly VOXTRAL_UNIT='codex-studio-voxtral-realtime.service'",
            'systemctl --user stop "$VOXTRAL_UNIT"',
            'systemctl --user start "$VOXTRAL_UNIT"',
            'gate_lock_file="$private_root/.spark-avatar-gate.lock"',
            'activation_lock_file="$activation_lock_parent/ue5-spark-ardy.activation.lock"',
            "exec 8>&-",
            "exec 9>&-",
            "trap 'handle_signal HUP 129' HUP",
            "trap 'handle_signal INT 130' INT",
            "trap 'handle_signal TERM 143' TERM",
            "restore_voxtral",
            "validate_fay_identity",
            "unreal_absent_after=passed",
            '"outage_performed=$outage_performed"',
            "'outage_performed=1'",
            '"activation_started=$activation_started"',
            '"recovery_blocked=$recovery_blocked"',
        ):
            self.assertIn(marker, self.source)
        on_exit = function_source(self.source, "on_exit", "handle_signal")
        endpoint_cleanup = function_source(
            self.source, "ensure_ardy_endpoint_on_exit", "on_exit"
        )
        self.assertIn("cancel_and_reap_runner", on_exit)
        self.assertIn("ensure_ardy_endpoint_on_exit", on_exit)
        self.assertIn("restore_voxtral", on_exit)
        self.assertIn("reconcile_recovery_endpoint", endpoint_cleanup)
        self.assertIn("rollback_mock_verified != passed", endpoint_cleanup)
        self.assertIn("prepare_emergency_activation_attempt", endpoint_cleanup)
        self.assertIn("attempt_recovery", endpoint_cleanup)

    def test_inherited_activation_lock_is_exact_proc_fd(self) -> None:
        for marker in (
            "inherited_lock_fd=${ARDY_ACTIVATION_LOCK_FD:-}",
            '[[ -e /proc/self/fdinfo/$inherited_lock_fd ]]',
            'readlink -f "/proc/self/fd/$inherited_lock_fd"',
            '[[ $inherited_lock_path == "$lock_file" ]]',
            'flock -n "$inherited_lock_fd"',
            'flock -n 9',
            '"recovery_mode=$recovery_mode"',
        ):
            self.assertIn(marker, self.activator)
        self.assertIn("ARDY_ACTIVATION_LOCK_FD=8", self.source)

    def test_banned_mutations_are_absent(self) -> None:
        self.assertNotRegex(self.source, r"\bsudo\b")
        self.assertNotRegex(
            self.source,
            r"\bdocker\s+(?:rm|kill|prune|restart|start|pause|unpause|update|exec|system|volume|image\s+rm)\b",
        )
        self.assertNotRegex(
            self.source,
            r"\b(?:apt|apt-get|dnf|yum|pacman|pip|pip3|conda)\b",
        )
        self.assertNotRegex(self.source, r"(?m)^\s*systemctl\s+(?!--user)")
        self.assertNotIn("run-spark-avatar-gate.sh", self.source)


class ArdyRecoveryGateDecisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = SCRIPT_PATH.read_text(encoding="utf-8")
        cls.stop_function = function_source(
            cls.source, "stop_exact_old_ardy", "verify_old_ardy_absent_without_claimant"
        )
        cls.absence_function = function_source(
            cls.source, "verify_old_ardy_absent_without_claimant", "restore_voxtral"
        )
        cls.recovery_function = function_source(
            cls.source, "attempt_recovery", "stop_exact_old_ardy"
        )
        cls.reconcile_function = function_source(
            cls.source,
            "reconcile_recovery_endpoint",
            "prepare_emergency_activation_attempt",
        )
        cls.stable_original_function = function_source(
            cls.source,
            "capture_exact_original_real_stably",
            "reconcile_recovery_endpoint",
        )
        cls.bounded_function = function_source(
            cls.source, "run_bounded_isolated", "docker_stop_exact_bounded"
        )
        cls.stop_helper_function = function_source(
            cls.source, "docker_stop_exact_bounded", "capture_process_record"
        )
        cls.restore_function = function_source(
            cls.source, "restore_voxtral", "verify_package_postflight"
        )
        cls.abort_barrier_function = function_source(
            cls.source, "abort_runner_start_barrier", "release_runner_start_barrier"
        )
        cls.release_barrier_function = function_source(
            cls.source, "release_runner_start_barrier", "cancel_and_reap_runner"
        )
        cls.endpoint_cleanup_function = function_source(
            cls.source, "ensure_ardy_endpoint_on_exit", "on_exit"
        )
        cls.on_exit_function = function_source(cls.source, "on_exit", "handle_signal")
        handle_start = cls.source.index("handle_signal() {")
        handle_end = cls.source.index("\n\ntrap 'on_exit", handle_start)
        cls.handle_signal_function = cls.source[handle_start:handle_end]
        cls.package_function = function_source(
            cls.source, "verify_package_postflight", "validate_soak_result"
        )
        cls.arrays_equal_function = function_source(
            cls.source, "arrays_are_equal", "validate_fay_runtime_snapshot"
        )
        cls.fay_snapshot_function = function_source(
            cls.source, "validate_fay_runtime_snapshot", "array_digest"
        )
        cls.find_marker_function = function_source(
            cls.source, "find_marker_line_after", "refresh_recovery_log"
        )
        cls.marker_count_function = function_source(
            cls.source, "marker_count_between", "post_motion_action"
        )
        cls.post_recovery_function = function_source(
            cls.source, "validate_post_recovery_log", "restore_voxtral"
        )

    def run_bash(self, source: str, root: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ("bash", "-c", source),
            cwd=root,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def finalization_harness(
        self, root: Path, *, endpoint: str, image_matches: bool
    ) -> str:
        container_id = "c" * 64
        snapshot = (
            "name",
            container_id,
            "tag",
            "true",
            "123",
            "started",
            "true",
            "host",
            "true",
            "0",
            "/models",
            "false",
            "image",
            "python",
            "456",
            "ardy",
            "checkpoint",
            "3",
            "1.0",
        )
        snapshot_words = " ".join(snapshot)
        recovery_verified = 1 if endpoint == "real" else 0
        rollback_verified = "passed" if endpoint == "mock" else "not-required"
        main_completed = 1 if endpoint == "real" else 0
        outage_performed = 0 if endpoint == "original" else 1
        image_suffix = "" if image_matches else "-mismatch"
        return textwrap.dedent(
            f"""\
            set -uo pipefail
            ARDY_IMAGE=ue5-spark-ardy:0.2.0
            ARDY_ROLLBACK_IMAGE=ue5-spark-ardy:0.1.0
            ardy_expected_image_id=sha256:{'1' * 64}
            ardy_rollback_image_id=sha256:{'2' * 64}
            endpoint={endpoint}
            runtime_snapshot=({snapshot_words})
            ardy_before=({snapshot_words})
            ardy_recovered=({snapshot_words})
            ardy_rollback=({snapshot_words})
            ardy_final=()
            recovery_verified={recovery_verified}
            rollback_mock_verified={rollback_verified}
            recovery_blocked=none
            recovery_reconciliation=not-required
            outage_committed={outage_performed}
            outage_performed={outage_performed}
            pre_cleanup_recovery_verified=not-captured
            pre_cleanup_rollback_mock_verified=not-captured
            pre_cleanup_recovery_blocked=not-captured
            pre_cleanup_recovery_reconciliation=not-captured
            pre_cleanup_ardy_claim_kind=not-captured
            pre_cleanup_ardy_claim_container_id=not-captured
            pre_cleanup_ardy_claim_pid=not-captured
            pre_cleanup_ardy_claim_process_starttime=not-captured
            cleanup_ardy_validation_passes=0
            runner_started=0
            runner_reaped=0
            runner_exit_status=0
            runner_forced_kill=0
            runner_group_post_exit_policy=not-started
            package_preflight_ready=0
            package_postflight_verified=not-checked
            unreal_absent_after=not-checked
            voxtral_pause_verified=not-checked
            voxtral_pause_continuity=not-checked
            voxtral_restore_required=0
            voxtral_restore_verified=not-required
            fay_snapshot_ready=0
            ardy_snapshot_ready=1
            main_completed={main_completed}
            cleanup_errors=()
            mapfile() {{ remaining_unreal_pids=(); }}
            find_expected_unreal_pids() {{ return 0; }}
            ensure_ardy_endpoint_on_exit() {{ return 0; }}
            verify_package_postflight() {{ return 0; }}
            voxtral_is_fully_inactive() {{ return 0; }}
            restore_voxtral() {{ return 0; }}
            validate_fay_identity() {{ return 0; }}
            capture_fay_listener_bindings() {{ return 0; }}
            arrays_are_equal() {{ return 0; }}
            container_id_for_name() {{ printf '%s\n' {container_id}; }}
            capture_real_ardy() {{ ardy_final=("${{runtime_snapshot[@]}}"); }}
            capture_mock_ardy() {{ final_mock=("${{runtime_snapshot[@]}}"); }}
            ardy_immutable_snapshots_equal() {{ return 0; }}
            image_id() {{
                if [[ $1 == "$ARDY_IMAGE" ]]; then
                    printf '%s\n' "${{ardy_expected_image_id}}{image_suffix}"
                else
                    printf '%s\n' "${{ardy_rollback_image_id}}{image_suffix}"
                fi
            }}
            note_cleanup_error() {{ cleanup_errors+=("$*"); }}
            write_final_record() {{
                printf '%s|%s|%s|%s\n' "$1" "$2" "$ardy_final_state" \
                    "${{#cleanup_errors[@]}}" >{root / 'final.txt'}
            }}
            {self.on_exit_function}
            trap 'on_exit $?' EXIT
            exit 0
            """
        )

    def test_production_exit_finalization_executes_all_claim_branches(self) -> None:
        cases = (
            ("real", True, 0, "0|0|new-real-healthy|0"),
            ("mock", True, 1, "0|1|sealed-mock-after-failed-recovery|0"),
            ("original", True, 1, "0|1|original-real-unchanged|0"),
            ("real", False, 1, "0|1|failed|1"),
        )
        for endpoint, image_matches, returncode, expected in cases:
            with self.subTest(
                endpoint=endpoint, image_matches=image_matches
            ), tempfile.TemporaryDirectory(prefix="ardy-finalization-") as directory:
                root = Path(directory)
                result = self.run_bash(
                    self.finalization_harness(
                        root, endpoint=endpoint, image_matches=image_matches
                    ),
                    root,
                )
                self.assertEqual(result.returncode, returncode, result.stderr)
                self.assertNotIn("command not found", result.stderr)
                self.assertEqual(
                    (root / "final.txt").read_text(encoding="utf-8").strip(),
                    expected,
                )

    def test_exit_repairs_stale_claims_and_never_touches_unknown_claimants(self) -> None:
        cases = {
            "healthy": (1, "not-required", 0, 0, 1, 1, "none"),
            "real-absent": (1, "not-required", 1, 1, 1, 1, "none"),
            "mock-absent": (0, "passed", 1, 1, 1, 1, "none"),
            "second-real": (1, "not-required", 1, 0, 1, 1, "none"),
            "unknown": (
                1,
                "not-required",
                2,
                0,
                0,
                1,
                "unknown-container-claimant",
            ),
        }
        for mode, expected in cases.items():
            prior_recovery, prior_mock, errors, attempts, final_recovery, passes, blocked = (
                expected
            )
            with self.subTest(mode=mode), tempfile.TemporaryDirectory(
                prefix="ardy-exit-repair-"
            ) as directory:
                root = Path(directory)
                source = textwrap.dedent(
                    f"""\
                    set +e
                    mode={mode}
                    ardy_snapshot_ready=1
                    cleanup_ardy_validation_passes=0
                    outage_committed=0
                    outage_performed=1
                    recovery_verified={prior_recovery}
                    rollback_mock_verified={prior_mock}
                    recovery_blocked=none
                    recovery_reconciliation=exact-new-real
                    activation_in_progress=0
                    emergency_calls=0
                    reconciliation_calls=0
                    cleanup_errors=0
                    validate_previously_verified_ardy_endpoint() {{
                        [[ $mode == healthy ]]
                    }}
                    reconcile_recovery_endpoint() {{
                        reconciliation_calls=$((reconciliation_calls + 1))
                        case $mode in
                            real-absent|mock-absent) return 2 ;;
                            second-real)
                                recovery_verified=1
                                outage_committed=0
                                recovery_reconciliation=exact-new-real
                                return 0
                                ;;
                            unknown)
                                recovery_blocked=unknown-container-claimant
                                recovery_reconciliation=blocked-unqualified-fixed-name
                                return 1
                                ;;
                        esac
                        return 1
                    }}
                    prepare_emergency_activation_attempt() {{ return 0; }}
                    attempt_recovery() {{
                        emergency_calls=$((emergency_calls + 1))
                        recovery_verified=1
                        outage_committed=0
                        return 0
                    }}
                    note_cleanup_error() {{ cleanup_errors=$((cleanup_errors + 1)); }}
                    {self.endpoint_cleanup_function}
                    ensure_ardy_endpoint_on_exit
                    printf 'errors=%s\nattempts=%s\nrecovery=%s\npasses=%s\nblocked=%s\nreconciliations=%s\n' \
                        "$cleanup_errors" "$emergency_calls" "$recovery_verified" \
                        "$cleanup_ardy_validation_passes" "$recovery_blocked" \
                        "$reconciliation_calls"
                    """
                )
                result = self.run_bash(source, root)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(f"errors={errors}", result.stdout)
                self.assertIn(f"attempts={attempts}", result.stdout)
                self.assertIn(f"recovery={final_recovery}", result.stdout)
                self.assertIn(f"passes={passes}", result.stdout)
                self.assertIn(f"blocked={blocked}", result.stdout)
                if mode == "healthy":
                    self.assertIn("reconciliations=0", result.stdout)
                if mode == "unknown":
                    self.assertIn("reconciliations=1", result.stdout)

    def stop_harness(self, root: Path, *, identity: str, capture_status: int) -> str:
        old_id = "a" * 64
        return textwrap.dedent(
            f"""\
            set -euo pipefail
            ARDY_IMAGE=ue5-spark-ardy:0.2.0
            ardy_expected_image_id=sha256:{'1' * 64}
            old_container_id={old_id}
            current_identity={identity}
            gate_root={root}
            outage_committed=0
            outage_performed=0
            ardy_stop_in_progress=0
            deferred_signal_name=''
            deferred_signal_status=0
            stop_failure_reason=''
            ardy_before=(one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen)
            ardy_pre_stop=()
            continuity_guard() {{ return 0; }}
            container_id_for_name() {{ printf '%s\\n' "$current_identity"; }}
            capture_real_ardy() {{
                (( {capture_status} == 0 )) || return {capture_status}
                ardy_pre_stop=("${{ardy_before[@]}}")
            }}
            ardy_immutable_snapshots_equal() {{ return 0; }}
            image_id() {{ printf 'sha256:%s\\n' '{'1' * 64}'; }}
            capture_log_cursor() {{ printf '42\\n'; }}
            docker() {{ printf '%s\\n' "$*" >>{root / 'docker.log'}; }}
            docker_stop_exact_bounded() {{
                [[ $1 =~ ^[0-9a-f]{{64}}$ ]] || return 1
                docker stop --time 2 "$1"
            }}
            handle_signal() {{ return 99; }}
            {self.stop_function}
            status=0
            stop_exact_old_ardy || status=$?
            printf 'status=%s\\noutage=%s\\nperformed=%s\\nreason=%s\\n' \
                "$status" "$outage_committed" "$outage_performed" "$stop_failure_reason"
            """
        )

    def test_identity_mismatch_performs_zero_stops(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ardy-stop-mismatch-") as directory:
            root = Path(directory)
            result = self.run_bash(
                self.stop_harness(root, identity="b" * 64, capture_status=0), root
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("status=1", result.stdout)
            self.assertFalse((root / "docker.log").exists())

    def test_listener_revalidation_failure_performs_zero_stops(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ardy-stop-ss-failure-") as directory:
            root = Path(directory)
            result = self.run_bash(
                self.stop_harness(root, identity="a" * 64, capture_status=1), root
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("status=1", result.stdout)
            self.assertFalse((root / "docker.log").exists())

    @unittest.skipUnless(
        sys.platform.startswith("linux"),
        "the runtime snapshot harness requires Bash nameref support",
    )
    def test_fay_runtime_snapshot_is_exact_and_identity_is_bracketed(self) -> None:
        cases = {
            "stable": 0,
            "first-process-failure": 1,
            "second-process-failure": 1,
            "capture-failure": 1,
            "missing-listener": 1,
            "extra-listener": 1,
            "changed-listener": 1,
        }
        for mode, expected_status in cases.items():
            with self.subTest(mode=mode), tempfile.TemporaryDirectory(
                prefix="fay-runtime-snapshot-"
            ) as directory:
                root = Path(directory)
                source = textwrap.dedent(
                    f"""\
                    set -uo pipefail
                    fay_pid=123
                    fay_exe=/usr/bin/python3.12
                    fay_starttime=456
                    mode={mode}
                    process_calls=0
                    fay_listener_bindings_before=(
                        '5000|127.0.0.1:5000|0.0.0.0:*'
                        '5010|127.0.0.1:5010|0.0.0.0:*'
                    )
                    process_matches_identity() {{
                        process_calls=$((process_calls + 1))
                        [[ $mode != first-process-failure || $process_calls -ne 1 ]] || return 1
                        [[ $mode != second-process-failure || $process_calls -ne 2 ]] || return 1
                    }}
                    capture_fay_listener_bindings() {{
                        local -n destination=$1
                        [[ $mode != capture-failure ]] || return 1
                        destination=(
                            '5000|127.0.0.1:5000|0.0.0.0:*'
                            '5010|127.0.0.1:5010|0.0.0.0:*'
                        )
                        case $mode in
                            missing-listener) unset 'destination[1]' ;;
                            extra-listener) destination+=(
                                '8766|127.0.0.1:8766|0.0.0.0:*'
                            ) ;;
                            changed-listener) destination[1]=\
                                '5010|127.0.0.1:5010|127.0.0.1:9' ;;
                        esac
                    }}
                    {self.arrays_equal_function}
                    {self.fay_snapshot_function}
                    status=0
                    validate_fay_runtime_snapshot || status=$?
                    printf 'status=%s\nprocess_calls=%s\n' "$status" "$process_calls"
                    """
                )
                result = self.run_bash(source, root)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(f"status={expected_status}", result.stdout)
                if mode == "stable":
                    self.assertIn("process_calls=2", result.stdout)

    def test_success_stops_only_the_exact_64_hex_id(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ardy-stop-success-") as directory:
            root = Path(directory)
            result = self.run_bash(
                self.stop_harness(root, identity="a" * 64, capture_status=0), root
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("status=0", result.stdout)
            self.assertIn("outage=1", result.stdout)
            self.assertIn("performed=1", result.stdout)
            self.assertEqual(
                (root / "docker.log").read_text(encoding="utf-8").strip(),
                f"stop --time 2 {'a' * 64}",
            )

    def test_failed_stop_accepts_original_real_only_after_five_stable_samples(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ardy-original-stable-") as directory:
            root = Path(directory)
            old_id = "a" * 64
            models = root / "models"
            models.mkdir()
            source = textwrap.dedent(
                f"""\
                set -euo pipefail
                ARDY_PORT=8777
                ardy_models_root={models}
                old_container_id={old_id}
                outage_committed=1
                recovery_verified=0
                rollback_mock_verified=not-required
                recovery_blocked=none
                recovery_reconciliation=not-required
                capture_count=0
                sleep_count=0
                ardy_before=(name {old_id} tag true 100 started true host true 0 {models} false image python 500 ardy checkpoint 3 1.0)
                ardy_recovered=()
                container_id_for_name() {{
                    printf 'resolve\\n' >>{root / 'resolve.log'}
                    printf '%s\\n' {old_id}
                }}
                capture_real_ardy() {{
                    capture_count=$((capture_count + 1))
                    if [[ $1 == reconciled_real ]]; then
                        reconciled_real=("${{ardy_before[@]}}")
                    elif [[ $1 == observed ]]; then
                        observed=("${{ardy_before[@]}}")
                    else
                        return 1
                    fi
                }}
                capture_mock_ardy() {{ touch {root / 'mock-captured'}; return 1; }}
                ardy_immutable_snapshots_equal() {{ return 0; }}
                run_bounded_isolated() {{ sleep_count=$((sleep_count + 1)); return 0; }}
                port_is_unused() {{ return 0; }}
                {self.stable_original_function}
                {self.reconcile_function}
                reconcile_recovery_endpoint
                printf 'outage=%s\\nrecovery=%s\\nreconciliation=%s\\ncaptures=%s\\nsleeps=%s\\n' \
                    "$outage_committed" "$recovery_verified" \
                    "$recovery_reconciliation" "$capture_count" "$sleep_count"
                """
            )
            result = self.run_bash(source, root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("outage=0", result.stdout)
            self.assertIn("recovery=0", result.stdout)
            self.assertIn("reconciliation=exact-original-real-stable", result.stdout)
            self.assertIn("captures=6", result.stdout)
            self.assertIn("sleeps=4", result.stdout)
            self.assertEqual(
                len((root / "resolve.log").read_text(encoding="utf-8").splitlines()),
                6,
            )
            self.assertFalse((root / "mock-captured").exists())

    def test_original_disappearing_during_stability_enters_absent_recovery(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ardy-original-disappears-") as directory:
            root = Path(directory)
            old_id = "a" * 64
            models = root / "models"
            models.mkdir()
            source = textwrap.dedent(
                f"""\
                set -euo pipefail
                ARDY_PORT=8777
                ardy_models_root={models}
                outage_committed=1
                recovery_verified=0
                rollback_mock_verified=not-required
                recovery_blocked=none
                recovery_reconciliation=not-required
                ardy_before=(name {old_id} tag true 100 started true host true 0 {models} false image python 500 ardy checkpoint 3 1.0)
                ardy_recovered=()
                container_id_for_name() {{
                    local count=0
                    [[ ! -f {root / 'resolve-count'} ]] || count=$(<{root / 'resolve-count'})
                    printf '%s\\n' "$((count + 1))" >{root / 'resolve-count'}
                    (( count == 0 )) || return 1
                    printf '%s\\n' {old_id}
                }}
                capture_real_ardy() {{ reconciled_real=("${{ardy_before[@]}}"); }}
                capture_mock_ardy() {{ touch {root / 'mock-captured'}; return 1; }}
                ardy_immutable_snapshots_equal() {{ return 0; }}
                capture_exact_original_real_stably() {{ return 1; }}
                port_is_unused() {{ return 0; }}
                {self.reconcile_function}
                status=0
                reconcile_recovery_endpoint || status=$?
                printf 'status=%s\\noutage=%s\\nblocked=%s\\nreconciliation=%s\\n' \
                    "$status" "$outage_committed" "$recovery_blocked" \
                    "$recovery_reconciliation"
                """
            )
            result = self.run_bash(source, root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("status=2", result.stdout)
            self.assertIn("outage=1", result.stdout)
            self.assertIn("blocked=none", result.stdout)
            self.assertIn("reconciliation=absent-port-free", result.stdout)
            self.assertEqual(
                (root / "resolve-count").read_text(encoding="utf-8").strip(), "2"
            )
            self.assertFalse((root / "mock-captured").exists())

    def test_original_disappearing_between_resolve_and_capture_enters_absent_recovery(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="ardy-original-resolve-capture-") as directory:
            root = Path(directory)
            old_id = "a" * 64
            models = root / "models"
            models.mkdir()
            source = textwrap.dedent(
                f"""\
                set -euo pipefail
                ARDY_PORT=8777
                ardy_models_root={models}
                outage_committed=1
                recovery_verified=0
                rollback_mock_verified=not-required
                recovery_blocked=none
                recovery_reconciliation=not-required
                ardy_before=(name {old_id} tag true 100 started true host true 0 {models} false image python 500 ardy checkpoint 3 1.0)
                ardy_recovered=()
                container_id_for_name() {{
                    local count=0
                    [[ ! -f {root / 'resolve-count'} ]] || count=$(<{root / 'resolve-count'})
                    printf '%s\n' "$((count + 1))" >{root / 'resolve-count'}
                    (( count == 0 )) || return 1
                    printf '%s\n' {old_id}
                }}
                capture_real_ardy() {{
                    touch {root / 'capture-attempted'}
                    return 1
                }}
                capture_mock_ardy() {{ touch {root / 'mock-captured'}; return 1; }}
                ardy_immutable_snapshots_equal() {{ return 1; }}
                capture_exact_original_real_stably() {{ return 1; }}
                port_is_unused() {{ return 0; }}
                {self.reconcile_function}
                status=0
                reconcile_recovery_endpoint || status=$?
                printf 'status=%s\noutage=%s\nblocked=%s\nreconciliation=%s\n' \
                    "$status" "$outage_committed" "$recovery_blocked" \
                    "$recovery_reconciliation"
                """
            )
            result = self.run_bash(source, root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("status=2", result.stdout)
            self.assertIn("outage=1", result.stdout)
            self.assertIn("blocked=none", result.stdout)
            self.assertIn("reconciliation=absent-port-free", result.stdout)
            self.assertEqual(
                (root / "resolve-count").read_text(encoding="utf-8").strip(), "2"
            )
            self.assertTrue((root / "capture-attempted").is_file())
            self.assertFalse((root / "mock-captured").exists())

    def test_unknown_claimant_is_reported_and_never_stopped(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ardy-claimant-") as directory:
            root = Path(directory)
            source = textwrap.dedent(
                f"""\
                set -euo pipefail
                old_container_id={'a' * 64}
                ARDY_PORT=8777
                activation_started=0
                recovery_blocked=none
                absence_failure_reason=''
                docker() {{ printf '%s\\n' "$*" >>{root / 'docker.log'}; return 1; }}
                container_id_for_name() {{ printf '%s\\n' {'c' * 64}; }}
                port_is_unused() {{ return 0; }}
                sleep() {{ :; }}
                {self.absence_function}
                status=0
                verify_old_ardy_absent_without_claimant || status=$?
                printf 'status=%s\\nactivation_started=%s\\nblocked=%s\\nreason=%s\\n' \
                    "$status" "$activation_started" "$recovery_blocked" \
                    "$absence_failure_reason"
                """
            )
            result = self.run_bash(source, root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("status=1", result.stdout)
            self.assertIn("activation_started=0", result.stdout)
            self.assertIn("blocked=unknown-container-claimant", result.stdout)
            commands = (root / "docker.log").read_text(encoding="utf-8")
            self.assertNotIn("stop", commands)

    def test_unknown_port_claimant_or_ss_failure_never_starts_activation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ardy-port-claimant-") as directory:
            root = Path(directory)
            source = textwrap.dedent(
                f"""\
                set -euo pipefail
                old_container_id={'a' * 64}
                ARDY_PORT=8777
                activation_started=0
                recovery_blocked=none
                absence_failure_reason=''
                docker() {{ printf '%s\\n' "$*" >>{root / 'docker.log'}; return 1; }}
                container_id_for_name() {{ return 1; }}
                port_is_unused() {{ return 1; }}
                sleep() {{ :; }}
                {self.absence_function}
                status=0
                verify_old_ardy_absent_without_claimant || status=$?
                printf 'status=%s\\nactivation_started=%s\\nblocked=%s\\n' \
                    "$status" "$activation_started" "$recovery_blocked"
                """
            )
            result = self.run_bash(source, root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("status=1", result.stdout)
            self.assertIn("activation_started=0", result.stdout)
            self.assertIn("blocked=unknown-port-claimant-or-ss-failure", result.stdout)
            self.assertNotIn(
                "stop", (root / "docker.log").read_text(encoding="utf-8")
            )

    def test_failed_identity_commit_aborts_barrier_without_launch_or_signal(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ardy-runner-barrier-") as directory:
            root = Path(directory)
            source = textwrap.dedent(
                f"""\
                set -euo pipefail
                fifo={root / 'barrier'}
                mkfifo "$fifo"
                exec 7<>"$fifo"
                rm -f "$fifo"
                runner_barrier_fd_open=1
                runner_start_released=0
                runner_started=1
                runner_reaped=0
                runner_exit_status=not-started
                runner_group_post_exit_policy=not-started
                (
                    IFS= read -r token <&7
                    exec 7>&-
                    [[ $token != release-owned-runner ]] || touch {root / 'unreal-launched'}
                    exit 70
                ) &
                runner_pid=$!
                {self.abort_barrier_function}
                abort_runner_start_barrier
                printf 'reaped=%s\\npolicy=%s\\n' \
                    "$runner_reaped" "$runner_group_post_exit_policy"
                """
            )
            result = self.run_bash(source, root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("reaped=1", result.stdout)
            self.assertIn("start-barrier-aborted-without-signals", result.stdout)
            self.assertFalse((root / "unreal-launched").exists())

    def test_signal_during_runner_release_is_deferred_after_commit(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ardy-runner-release-") as directory:
            root = Path(directory)
            instrumented_release = self.release_barrier_function.replace(
                "printf '%s\\n' \"$runner_barrier_token\" >&7 || release_status=$?",
                "kill -TERM \"$$\"\n    builtin printf '%s\\n' "
                '"$runner_barrier_token" >&7 || release_status=$?',
            )
            source = textwrap.dedent(
                f"""\
                set -uo pipefail
                exec 7>{root / 'released-token'}
                runner_identity_committed=1
                runner_barrier_fd_open=1
                runner_start_released=0
                runner_release_in_progress=0
                ardy_stop_in_progress=0
                runner_barrier_token={'d' * 64}
                runner_identity_capture_in_progress=0
                deferred_signal_name=''
                deferred_signal_status=0
                last_error=none
                {instrumented_release}
                {self.handle_signal_function}
                trap 'handle_signal TERM 143' TERM
                status=0
                release_runner_start_barrier || status=$?
                trap - TERM
                printf 'status=%s\nreleased=%s\ndeferred=%s\nin_progress=%s\n' \
                    "$status" "$runner_start_released" "$deferred_signal_status" \
                    "$runner_release_in_progress"
                """
            )
            result = self.run_bash(source, root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("status=0", result.stdout)
            self.assertIn("released=1", result.stdout)
            self.assertIn("deferred=143", result.stdout)
            self.assertIn("in_progress=0", result.stdout)
            self.assertEqual(
                (root / "released-token").read_text(encoding="utf-8").strip(),
                "d" * 64,
            )

    def test_term_and_int_during_exact_stop_leave_verified_endpoint(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ardy-stop-signals-") as directory:
            root = Path(directory)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            endpoint = root / "endpoint-state"
            endpoint.write_text("real\n", encoding="utf-8")
            stop_started = root / "stop-started"
            docker_log = root / "docker.log"
            foreign_touch = root / "foreign-touch"
            final_record = root / "final-endpoint"
            old_id = "a" * 64

            fake_setsid = fake_bin / "setsid"
            fake_setsid.write_text(
                textwrap.dedent(
                    f"""\
                    #!{sys.executable}
                    import os
                    import sys

                    args = sys.argv[1:]
                    if args and args[0] == "--wait":
                        args.pop(0)
                    if not args:
                        raise SystemExit(64)
                    os.setsid()
                    os.execvp(args[0], args)
                    """
                ),
                encoding="utf-8",
            )
            fake_setsid.chmod(0o755)

            fake_timeout = fake_bin / "timeout"
            fake_timeout.write_text(
                textwrap.dedent(
                    f"""\
                    #!{sys.executable}
                    import os
                    import sys

                    args = sys.argv[1:]
                    while args and args[0].startswith("--"):
                        args.pop(0)
                    if not args:
                        raise SystemExit(64)
                    args.pop(0)
                    if not args:
                        raise SystemExit(64)
                    os.execvp(args[0], args)
                    """
                ),
                encoding="utf-8",
            )
            fake_timeout.chmod(0o755)

            fake_docker = fake_bin / "docker"
            fake_docker.write_text(
                textwrap.dedent(
                    f"""\
                    #!{sys.executable}
                    import os
                    import pathlib
                    import sys
                    import time

                    args = sys.argv[1:]
                    expected = ["stop", "--time", "2", os.environ["EXPECTED_ID"]]
                    if args != expected:
                        pathlib.Path(os.environ["FOREIGN_TOUCH"]).write_text(
                            " ".join(args), encoding="utf-8"
                        )
                        raise SystemExit(9)
                    pathlib.Path(os.environ["STOP_STARTED"]).touch()
                    time.sleep(0.6)
                    pathlib.Path(os.environ["ENDPOINT_STATE"]).write_text(
                        "absent\\n", encoding="utf-8"
                    )
                    pathlib.Path(os.environ["DOCKER_LOG"]).write_text(
                        " ".join(args) + "\\n", encoding="utf-8"
                    )
                    print(args[-1])
                    """
                ),
                encoding="utf-8",
            )
            fake_docker.chmod(0o755)

            source = textwrap.dedent(
                f"""\
                set -uo pipefail
                ARDY_IMAGE=ue5-spark-ardy:0.2.0
                ardy_expected_image_id=sha256:{'1' * 64}
                old_container_id={old_id}
                gate_root={root}
                outage_committed=0
                outage_performed=0
                ardy_stop_in_progress=0
                runner_identity_capture_in_progress=0
                runner_release_in_progress=0
                deferred_signal_name=''
                deferred_signal_status=0
                last_error=none
                stop_failure_reason=''
                ardy_before=(one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen)
                ardy_pre_stop=()
                continuity_guard() {{ return 0; }}
                container_id_for_name() {{ printf '%s\\n' {old_id}; }}
                capture_real_ardy() {{ ardy_pre_stop=("${{ardy_before[@]}}"); }}
                ardy_immutable_snapshots_equal() {{ return 0; }}
                image_id() {{ printf 'sha256:%s\\n' '{'1' * 64}'; }}
                capture_log_cursor() {{ printf '42\\n'; }}
                {self.bounded_function}
                {self.stop_helper_function}
                {self.stop_function}
                {self.handle_signal_function}
                on_exit() {{
                    local status=$?
                    local observed final_state
                    trap - EXIT
                    trap '' HUP INT TERM
                    observed=$(<{endpoint})
                    case $observed in
                        absent)
                            printf 'mock\\n' >{endpoint}
                            final_state=sealed-mock-after-failed-recovery
                            ;;
                        real)
                            final_state=original-real-unchanged
                            ;;
                        mock)
                            final_state=sealed-mock-after-failed-recovery
                            ;;
                        *)
                            final_state=failed
                            ;;
                    esac
                    printf 'state=%s\\ndeferred=%s\\nstop_in_progress=%s\\n' \
                        "$final_state" "$deferred_signal_status" \
                        "$ardy_stop_in_progress" >{final_record}
                    exit "$status"
                }}
                trap on_exit EXIT
                trap 'handle_signal HUP 129' HUP
                trap 'handle_signal INT 130' INT
                trap 'handle_signal TERM 143' TERM
                stop_exact_old_ardy
                """
            )
            environment = os.environ.copy()
            environment.update(
                {
                    "PATH": f"{fake_bin}:{environment['PATH']}",
                    "EXPECTED_ID": old_id,
                    "STOP_STARTED": str(stop_started),
                    "ENDPOINT_STATE": str(endpoint),
                    "DOCKER_LOG": str(docker_log),
                    "FOREIGN_TOUCH": str(foreign_touch),
                }
            )
            process = subprocess.Popen(
                ("bash", "-c", source),
                cwd=root,
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and not stop_started.exists():
                time.sleep(0.01)
            if not stop_started.exists():
                stdout, stderr = process.communicate(timeout=5)
                self.fail(
                    "isolated exact stop did not start; "
                    f"status={process.returncode}, stdout={stdout!r}, stderr={stderr!r}"
                )
            os.killpg(process.pid, signal.SIGTERM)
            time.sleep(0.03)
            os.killpg(process.pid, signal.SIGINT)
            stdout, stderr = process.communicate(timeout=10)
            self.assertNotEqual(process.returncode, 0, stdout + stderr)
            time.sleep(0.75)
            self.assertIn(
                endpoint.read_text(encoding="utf-8").strip(), {"real", "mock"}
            )
            final = final_record.read_text(encoding="utf-8")
            self.assertRegex(
                final,
                r"state=(?:original-real-unchanged|sealed-mock-after-failed-recovery)",
            )
            self.assertRegex(final, r"deferred=(?:129|130|143)")
            self.assertIn("stop_in_progress=0", final)
            self.assertEqual(
                docker_log.read_text(encoding="utf-8").strip(),
                f"stop --time 2 {old_id}",
            )
            self.assertFalse(foreign_touch.exists())

    def test_exit_recovery_retries_after_pre_exec_activation_gap(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ardy-activation-gap-") as directory:
            root = Path(directory)
            source = textwrap.dedent(
                f"""\
                set +e
                ardy_snapshot_ready=1
                outage_committed=1
                outage_performed=1
                recovery_verified=0
                rollback_mock_verified=not-required
                recovery_blocked=none
                activation_in_progress=1
                activation_requested=1
                activation_returned=0
                emergency_calls=0
                cleanup_errors=0
                validate_previously_verified_ardy_endpoint() {{ return 2; }}
                reconcile_recovery_endpoint() {{ return 2; }}
                prepare_emergency_activation_attempt() {{ return 0; }}
                attempt_recovery() {{
                    emergency_calls=$((emergency_calls + 1))
                    recovery_verified=1
                    outage_committed=0
                    return 0
                }}
                note_cleanup_error() {{ cleanup_errors=$((cleanup_errors + 1)); }}
                {self.endpoint_cleanup_function}
                ensure_ardy_endpoint_on_exit
                printf 'recovery=%s\noutage=%s\nin_progress=%s\ncalls=%s\nerrors=%s\n' \
                    "$recovery_verified" "$outage_committed" \
                    "$activation_in_progress" "$emergency_calls" "$cleanup_errors"
                """
            )
            result = self.run_bash(source, root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("recovery=1", result.stdout)
            self.assertIn("outage=0", result.stdout)
            self.assertIn("in_progress=0", result.stdout)
            self.assertIn("calls=1", result.stdout)
            self.assertIn("errors=0", result.stdout)

    def recovery_harness(self, root: Path, *, activator_status: int) -> str:
        activator = root / "fake-activator"
        activator.write_text(f"#!/usr/bin/env bash\nexit {activator_status}\n", encoding="utf-8")
        activator.chmod(0o755)
        return textwrap.dedent(
            f"""\
            set -euo pipefail
            activator={activator}
            ardy_models_root={root / 'models'}
            activation_evidence={root / 'activation'}
            activation_console={root / 'activation.log'}
            activation_started=0
            activation_requested=0
            activation_in_progress=0
            activation_returned=0
            activation_attempt_count=0
            activation_cursor=not-captured
            recovery_verified=0
            outage_committed=1
            rollback_mock_verified=not-required
            ardy_before=(name {'a' * 64} tag true 100 started true host true 0 {root / 'models'} false image python 500 ardy checkpoint 3 1.0)
            ardy_recovered=()
            validate_activation_success_records() {{ return 0; }}
            activation_target_records_match() {{ return 0; }}
            validate_activation_failure_rollback() {{ rollback_mock_verified=passed; return 0; }}
            container_id_for_name() {{ printf '%s\\n' {'b' * 64}; }}
            capture_real_ardy() {{
                ardy_recovered=(name {'b' * 64} tag true 200 started2 true host true 0 {root / 'models'} false image python 600 ardy checkpoint 3 2.0)
            }}
            capture_log_cursor() {{ printf '77\\n'; }}
            {self.recovery_function}
            status=0
            attempt_recovery || status=$?
            printf 'status=%s\\nactivation=%s\\nrecovery=%s\\noutage=%s\\nrollback=%s\\n' \
                "$status" "$activation_started" "$recovery_verified" \
                "$outage_committed" "$rollback_mock_verified"
            """
        )

    def test_success_requires_a_new_exact_real_provider(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ardy-recovery-success-") as directory:
            root = Path(directory)
            (root / "models").mkdir()
            result = self.run_bash(self.recovery_harness(root, activator_status=0), root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("status=0", result.stdout)
            self.assertIn("recovery=1", result.stdout)
            self.assertIn("outage=0", result.stdout)

    def test_activator_failure_with_verified_mock_still_fails(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ardy-recovery-failure-") as directory:
            root = Path(directory)
            (root / "models").mkdir()
            result = self.run_bash(self.recovery_harness(root, activator_status=7), root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("status=7", result.stdout)
            self.assertIn("recovery=0", result.stdout)
            self.assertIn("rollback=passed", result.stdout)

    def test_signal_during_recovery_allows_activator_rollback_to_finish(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ardy-recovery-signal-") as directory:
            root = Path(directory)
            activator = root / "fake-activator"
            activator.write_text(
                textwrap.dedent(
                    f"""\
                    #!/usr/bin/env bash
                    evidence=$2
                    trap 'mkdir -p "$evidence"; touch "$evidence/rollback-finished"; exit 143' TERM
                    touch {root / 'activator-started'}
                    while :; do sleep 1; done
                    """
                ),
                encoding="utf-8",
            )
            activator.chmod(0o755)
            source = textwrap.dedent(
                f"""\
                set -uo pipefail
                trap ':' TERM
                activator={activator}
                ardy_models_root={root / 'models'}
                activation_evidence={root / 'activation'}
                activation_console={root / 'activation.log'}
                activation_started=0
                activation_requested=0
                activation_in_progress=0
                activation_returned=0
                activation_attempt_count=0
                activation_cursor=not-captured
                recovery_verified=0
                outage_committed=1
                rollback_mock_verified=not-required
                ardy_before=(name {'a' * 64} tag true 100 started true host true 0 {root / 'models'} false image python 500 ardy checkpoint 3 1.0)
                ardy_recovered=()
                capture_log_cursor() {{ printf '91\\n'; }}
                validate_activation_success_records() {{ return 1; }}
                activation_target_records_match() {{ return 1; }}
                validate_activation_failure_rollback() {{
                    [[ -f $activation_evidence/rollback-finished ]] || return 1
                    rollback_mock_verified=passed
                }}
                container_id_for_name() {{ return 1; }}
                capture_real_ardy() {{ return 1; }}
                {self.recovery_function}
                status=0
                attempt_recovery || status=$?
                printf 'status=%s\\nstarted=%s\\nrollback=%s\\n' \
                    "$status" "$activation_started" "$rollback_mock_verified"
                """
            )
            process = subprocess.Popen(
                ("bash", "-c", source),
                cwd=root,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and not (root / "activator-started").exists():
                time.sleep(0.02)
            self.assertTrue((root / "activator-started").exists())
            os.killpg(process.pid, signal.SIGTERM)
            stdout, stderr = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 0, stderr)
            self.assertIn("status=143", stdout)
            self.assertIn("started=1", stdout)
            self.assertIn("rollback=passed", stdout)
            self.assertTrue((root / "activation" / "rollback-finished").exists())

    def test_signal_cleanup_restore_uses_only_the_fixed_user_unit(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ardy-voxtral-restore-") as directory:
            root = Path(directory)
            source = textwrap.dedent(
                f"""\
                set -euo pipefail
                VOXTRAL_UNIT=codex-studio-voxtral-realtime.service
                voxtral_before=("$VOXTRAL_UNIT" 100 /usr/bin/python3.12 500)
                voxtral_after=()
                voxtral_restore_verified=not-required
                timeout() {{
                    while [[ $1 == --* || $1 =~ ^[0-9]+$ ]]; do shift; done
                    printf '%s\\n' "$*" >>{root / 'systemctl.log'}
                    return 0
                }}
                capture_voxtral_snapshot() {{
                    voxtral_after=("$VOXTRAL_UNIT" 200 /usr/bin/python3.12 600)
                    return 0
                }}
                sleep() {{ :; }}
                {self.restore_function}
                restore_voxtral
                printf 'restore=%s\\n' "$voxtral_restore_verified"
                """
            )
            result = self.run_bash(source, root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("restore=passed", result.stdout)
            self.assertEqual(
                (root / "systemctl.log").read_text(encoding="utf-8").strip(),
                "systemctl --user start codex-studio-voxtral-realtime.service",
            )

    def test_voxtral_restore_failure_exits_failed_after_bounded_attempts(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ardy-voxtral-failure-") as directory:
            root = Path(directory)
            source = textwrap.dedent(
                f"""\
                set -euo pipefail
                VOXTRAL_UNIT=codex-studio-voxtral-realtime.service
                voxtral_before=("$VOXTRAL_UNIT" 100 /usr/bin/python3.12 500)
                voxtral_after=()
                voxtral_restore_verified=not-required
                timeout() {{
                    while [[ $1 == --* || $1 =~ ^[0-9]+$ ]]; do shift; done
                    printf '%s\\n' "$*" >>{root / 'systemctl.log'}
                    return 0
                }}
                capture_voxtral_snapshot() {{ return 1; }}
                sleep() {{ :; }}
                {self.restore_function}
                status=0
                restore_voxtral || status=$?
                printf 'status=%s\\nrestore=%s\\n' "$status" "$voxtral_restore_verified"
                """
            )
            result = self.run_bash(source, root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("status=1", result.stdout)
            self.assertEqual(
                len((root / "systemctl.log").read_text(encoding="utf-8").splitlines()),
                3,
            )

    def test_package_postflight_detects_mutated_executable(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ardy-package-mutation-") as directory:
            root = Path(directory)
            launcher = root / "FayAvatarRuntime-Arm64.sh"
            unreal = root / "FayAvatarRuntime"
            seal = root / ".ue5-spark-package.sha256"
            launcher.write_text("launcher\n", encoding="utf-8")
            unreal.write_text("unreal\n", encoding="utf-8")
            seal.write_text("seal\n", encoding="utf-8")
            source = textwrap.dedent(
                f"""\
                set -euo pipefail
                gate_root={root}
                package_verifier=/usr/bin/true
                package_launcher_dir={root}
                package_launcher={launcher}
                expected_unreal_exe={unreal}
                package_seal={seal}
                package_preflight_ready=1
                package_postflight_verified=not-checked
                package_launcher_sha256=$(sha256sum {launcher} | awk '{{print $1}}')
                unreal_executable_sha256=$(sha256sum {unreal} | awk '{{print $1}}')
                package_seal_sha256=$(sha256sum {seal} | awk '{{print $1}}')
                printf 'mutated\\n' >{unreal}
                {self.package_function}
                status=0
                verify_package_postflight || status=$?
                printf 'status=%s\\nverified=%s\\n' \
                    "$status" "$package_postflight_verified"
                """
            )
            result = self.run_bash(source, root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("status=1", result.stdout)
            self.assertIn("verified=not-checked", result.stdout)

    def test_fresh_cursor_ignores_stale_marker(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ardy-stale-marker-") as directory:
            root = Path(directory)
            log = root / "recovery.log"
            log.write_text("ready\nstale marker\ncursor line\nfresh marker\n", encoding="utf-8")
            source = textwrap.dedent(
                f"""\
                set -euo pipefail
                recovery_log={log}
                {self.find_marker_function}
                find_marker_line_after 'marker' 3
                """
            )
            result = self.run_bash(source, root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "4")

    def test_late_rejection_and_unavailable_transitions_fail_final_audit(self) -> None:
        degraded_lines = (
            "Rejected ARDY pose batch: bad.",
            "ARDY loopback service is unavailable; baked fallback remains active.",
            "ARDY action 'explain' began a bounded fallback to baked idle: unavailable.",
            "Using character-neutral procedural fallback for 'explain'.",
        )
        for degraded in degraded_lines:
            with self.subTest(degraded=degraded), tempfile.TemporaryDirectory(
                prefix="ardy-late-degraded-"
            ) as directory:
                root = Path(directory)
                log = root / "recovery.log"
                log.write_text(
                    f"recovered ready\nlisten complete\n{degraded}\n"
                    "LogInit: Display: PreExit Game.\n",
                    encoding="utf-8",
                )
                source = textwrap.dedent(
                    f"""\
                    set -euo pipefail
                    recovery_log={log}
                    refresh_recovery_log() {{ :; }}
                    {self.find_marker_function}
                    {self.marker_count_function}
                    {self.post_recovery_function}
                    status=0
                    validate_post_recovery_log 1 2 || status=$?
                    printf 'status=%s\\n' "$status"
                    """
                )
                result = self.run_bash(source, root)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("status=1", result.stdout)

    def test_teardown_degraded_markers_after_preexit_are_excluded(self) -> None:
        degraded_lines = (
            "Rejected ARDY pose batch: teardown.",
            "ARDY loopback service is unavailable; baked fallback remains active.",
            "ARDY action 'explain' began a bounded fallback to baked idle: teardown.",
            "Using character-neutral procedural fallback for 'explain'.",
        )
        for degraded in degraded_lines:
            with self.subTest(degraded=degraded), tempfile.TemporaryDirectory(
                prefix="ardy-teardown-degraded-"
            ) as directory:
                root = Path(directory)
                log = root / "recovery.log"
                log.write_text(
                    "recovered ready\nlisten complete\n"
                    f"LogInit: Display: PreExit Game.\n{degraded}\n",
                    encoding="utf-8",
                )
                source = textwrap.dedent(
                    f"""\
                    set -euo pipefail
                    recovery_log={log}
                    refresh_recovery_log() {{ :; }}
                    {self.find_marker_function}
                    {self.marker_count_function}
                    {self.post_recovery_function}
                    status=0
                    validate_post_recovery_log 1 2 || status=$?
                    printf 'status=%s\\nend=%s\\ncounts=%s,%s,%s,%s\\n' \
                        "$status" "$post_recovery_audit_end_line" \
                        "$late_rejected_count" "$late_unavailable_count" \
                        "$late_generated_fallback_count" "$late_neutral_explain_count"
                    """
                )
                result = self.run_bash(source, root)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("status=0", result.stdout)
                self.assertIn("end=3", result.stdout)
                self.assertIn("counts=0,0,0,0", result.stdout)

    def test_post_recovery_audit_requires_fresh_preexit_after_last_action(self) -> None:
        fixtures = (
            ("recovered ready\nlisten complete\n", 1, 2),
            (
                "LogInit: Display: PreExit Game.\nrecovered ready\nlisten complete\n",
                2,
                3,
            ),
            (
                "recovered ready\nLogInit: Display: PreExit Game.\n"
                "listen complete\nLogInit: Display: PreExit Game.\n",
                1,
                3,
            ),
        )
        for contents, cursor, last_runtime in fixtures:
            with self.subTest(contents=contents), tempfile.TemporaryDirectory(
                prefix="ardy-invalid-preexit-"
            ) as directory:
                root = Path(directory)
                log = root / "recovery.log"
                log.write_text(contents, encoding="utf-8")
                source = textwrap.dedent(
                    f"""\
                    set -euo pipefail
                    recovery_log={log}
                    refresh_recovery_log() {{ :; }}
                    {self.find_marker_function}
                    {self.marker_count_function}
                    {self.post_recovery_function}
                    status=0
                    validate_post_recovery_log {cursor} {last_runtime} || status=$?
                    printf 'status=%s\\n' "$status"
                    """
                )
                result = self.run_bash(source, root)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("status=1", result.stdout)

    def test_missing_preexit_preserves_not_captured_evidence(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ardy-missing-preexit-") as directory:
            root = Path(directory)
            log = root / "recovery.log"
            log.write_text("recovered ready\nlisten complete\n", encoding="utf-8")
            source = textwrap.dedent(
                f"""\
                set -euo pipefail
                recovery_log={log}
                post_recovery_audit_end_line=not-captured
                refresh_recovery_log() {{ :; }}
                {self.find_marker_function}
                {self.marker_count_function}
                {self.post_recovery_function}
                status=0
                validate_post_recovery_log 1 2 || status=$?
                printf 'status=%s\\nend=%s\\n' "$status" "$post_recovery_audit_end_line"
                """
            )
            result = self.run_bash(source, root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("status=1", result.stdout)
            self.assertIn("end=not-captured", result.stdout)

    def test_post_recovery_audit_rejects_malformed_or_nonincreasing_bounds(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ardy-invalid-bounds-") as directory:
            root = Path(directory)
            log = root / "recovery.log"
            log.write_text(
                "recovered ready\nlisten complete\nLogInit: Display: PreExit Game.\n",
                encoding="utf-8",
            )
            source = textwrap.dedent(
                f"""\
                set -euo pipefail
                recovery_log={log}
                refresh_recovery_log() {{ :; }}
                {self.find_marker_function}
                {self.marker_count_function}
                {self.post_recovery_function}
                for pair in 'x 2' '1 x' '2 2' '3 2'; do
                    read -r cursor last_runtime <<<"$pair"
                    status=0
                    validate_post_recovery_log "$cursor" "$last_runtime" || status=$?
                    printf '%s:%s=%s\\n' "$cursor" "$last_runtime" "$status"
                done
                """
            )
            result = self.run_bash(source, root)
            self.assertEqual(result.returncode, 0, result.stderr)
            for expected in ("x:2=1", "1:x=1", "2:2=1", "3:2=1"):
                self.assertIn(expected, result.stdout)

    def test_stale_pre_cursor_degradation_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ardy-stale-degraded-") as directory:
            root = Path(directory)
            log = root / "recovery.log"
            log.write_text(
                "ARDY loopback service is unavailable; baked fallback remains active.\n"
                "recovered ready\nlisten complete\nLogInit: Display: PreExit Game.\n"
                "ARDY loopback service is unavailable; baked fallback remains active.\n",
                encoding="utf-8",
            )
            source = textwrap.dedent(
                f"""\
                set -euo pipefail
                recovery_log={log}
                refresh_recovery_log() {{ :; }}
                {self.find_marker_function}
                {self.marker_count_function}
                {self.post_recovery_function}
                status=0
                validate_post_recovery_log 2 3 || status=$?
                printf 'status=%s\\nend=%s\\n' "$status" "$post_recovery_audit_end_line"
                """
            )
            result = self.run_bash(source, root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("status=0", result.stdout)
            self.assertIn("end=4", result.stdout)


if __name__ == "__main__":
    unittest.main()
