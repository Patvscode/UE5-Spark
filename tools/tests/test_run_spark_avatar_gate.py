from __future__ import annotations

import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "run-spark-avatar-gate.sh"


class SparkAvatarGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = SCRIPT_PATH.read_text(encoding="utf-8")

    def test_bash_syntax_and_exact_arity(self) -> None:
        syntax = subprocess.run(
            ("bash", "-n", str(SCRIPT_PATH)),
            cwd=REPO_ROOT,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(syntax.returncode, 0, syntax.stderr)

        for arguments in ((), ("a", "1", "b", "2", "3", "extra")):
            with self.subTest(arguments=arguments):
                result = subprocess.run(
                    ("bash", str(SCRIPT_PATH), *arguments),
                    cwd=REPO_ROOT,
                    check=False,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                self.assertEqual(result.returncode, 64)
                self.assertIn("Usage:", result.stderr)

        self.assertIn("if (( $# != 5 )); then", self.source)

    @unittest.skipUnless(
        sys.platform.startswith("linux")
        and Path("/proc/self/stat").is_file()
        and shutil.which("setsid") is not None,
        "Linux /proc and setsid are required",
    )
    def test_linux_double_read_proves_direct_session_child(self) -> None:
        function_start = self.source.index("capture_process_record() {")
        function_end = self.source.index("\n\nread_process_starttime() {", function_start)
        capture_function = self.source[function_start:function_end]
        harness = f"""
set -euo pipefail
{capture_function}
supervisor_pid=$BASHPID
runner_bash_exe=$(readlink -f "$(command -v bash)")
setsid bash -c 'sleep 2; :' &
runner_pid=$!
declare -a initial=() candidate=() confirm=()
capture_process_record initial "$runner_pid"
[[ ${{initial[0]}} != Z && ${{initial[1]}} == "$supervisor_pid" ]]
provisional_starttime=${{initial[4]}}
adopted=0
for _ in $(seq 1 50); do
    capture_process_record candidate "$runner_pid" || break
    [[ ${{candidate[1]}} == "$supervisor_pid" && \
        ${{candidate[4]}} == "$provisional_starttime" ]] || break
    if [[ ${{candidate[2]}} == "$runner_pid" && \
        ${{candidate[3]}} == "$runner_pid" ]]; then
        candidate_exe=$(readlink -f "/proc/$runner_pid/exe")
        capture_process_record confirm "$runner_pid"
        if [[ ${{confirm[1]}} == "$supervisor_pid" && \
            ${{confirm[2]}} == "$runner_pid" && \
            ${{confirm[3]}} == "$runner_pid" && \
            ${{confirm[4]}} == "$provisional_starttime" && \
            $candidate_exe == "$runner_bash_exe" ]]; then
            adopted=1
            break
        fi
    fi
    sleep 0.02
done
wait "$runner_pid"
(( adopted == 1 ))
"""
        result = subprocess.run(
            ("bash", "-c", harness),
            cwd=REPO_ROOT,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_only_fixed_voxtral_unit_can_receive_lifecycle_calls(self) -> None:
        assignment = "readonly VOXTRAL_UNIT='codex-studio-voxtral-realtime.service'"
        self.assertEqual(self.source.count(assignment), 1)
        self.assertNotRegex(self.source, r"VOXTRAL_UNIT=\$|VOXTRAL_UNIT=\$\{")

        lifecycle_calls = re.findall(
            r"systemctl\s+--user\s+"
            r"(start|stop|restart|enable|disable|mask|unmask)\s+"
            r"([^\s;]+)",
            self.source,
        )
        self.assertEqual(
            lifecycle_calls,
            [("start", '"$VOXTRAL_UNIT"'), ("stop", '"$VOXTRAL_UNIT"')],
        )

    def test_ardy_and_fay_are_observed_without_lifecycle_calls(self) -> None:
        self.assertIn('docker inspect --type container "$ARDY_CONTAINER"', self.source)
        self.assertNotRegex(
            self.source,
            r"\bdocker\s+(?:run|start|stop|restart|rm|kill|pause|unpause|update|exec)\b",
        )
        self.assertNotRegex(
            self.source,
            r"systemctl[^\n]*(?:fay|ardy)",
        )
        for marker in (
            'process_matches_identity "$fay_pid"',
            "capture_fay_listener_bindings fay_listener_bindings_after",
            "arrays_are_equal fay_listener_bindings_before fay_listener_bindings_after",
            "other_owner=$(grep -oE 'pid=[0-9]+,'",
            "capture_ardy_snapshot ardy_after",
            "arrays_are_equal ardy_before ardy_after",
            "loopback_listener_owned_by_pid 8777",
        ):
            self.assertIn(marker, self.source)

    def test_restore_and_runner_ownership_are_on_every_exit_path(self) -> None:
        restore_arm = self.source.index("voxtral_restore_required=1")
        stop_call = self.source.index('systemctl --user stop "$VOXTRAL_UNIT"')
        self.assertLess(restore_arm, stop_call)
        self.assertIn("trap 'on_exit $?' EXIT", self.source)
        self.assertIn("trap '' HUP INT TERM", self.source)
        self.assertIn('exec setsid "$soak_runner"', self.source)
        self.assertIn('kill -TERM -- "-$runner_session_id"', self.source)
        self.assertIn('wait "$runner_pid"', self.source)
        self.assertIn("runner_reaped=1", self.source)
        self.assertIn("runner_identity_capture_in_progress=1", self.source)
        self.assertIn("deferred_signal_status", self.source)
        self.assertIn("Deferring %s until the owned runner identity is committed.", self.source)
        for marker in (
            'capture_process_record runner_initial_record "$runner_pid"',
            '${runner_initial_record[1]} == "$supervisor_pid"',
            '${runner_candidate_record[2]} == "$runner_pid"',
            '${runner_candidate_record[3]} == "$runner_pid"',
            '$runner_candidate_exe == "$runner_bash_exe"',
            '${runner_confirm_record[4]} == "$runner_provisional_starttime"',
            "runner_identity_committed=1",
        ):
            self.assertIn(marker, self.source)
        self.assertIn("while runner_leader_is_live; do", self.source)
        self.assertIn("if ! voxtral_is_fully_inactive; then", self.source)
        self.assertIn("voxtral_pause_continuity=failed", self.source)
        self.assertIn(
            "runner_group_post_exit_policy=not-scanned-after-exact-leader-exit",
            self.source,
        )
        self.assertNotIn("process_group_has_live_members", self.source)
        self.assertNotIn("clear_residual_runner_group", self.source)
        self.assertIn("the allowlisted Voxtral unit or listener returned before restoration", self.source)

        exit_handler = self.source[
            self.source.index("on_exit() {") : self.source.index("handle_signal() {")
        ]
        for marker in (
            "cancel_and_reap_runner",
            "restore_voxtral",
            "validate_fay_identity",
            "capture_ardy_snapshot ardy_after",
            "write_after_record",
            "write_final_record",
        ):
            self.assertIn(marker, exit_handler)
        self.assertLess(
            exit_handler.index("restore_voxtral"),
            exit_handler.index("Guarded DGX Spark avatar gate passed"),
        )

        cancel_handler = self.source[
            self.source.index("cancel_and_reap_runner() {") :
            self.source.index("restore_voxtral() {")
        ]
        self.assertEqual(cancel_handler.count('kill -TERM -- "-$runner_session_id"'), 1)
        self.assertEqual(cancel_handler.count('kill -KILL -- "-$runner_session_id"'), 1)
        self.assertNotIn('kill -TERM "$runner_pid"', cancel_handler)
        self.assertNotIn('kill -KILL "$runner_pid"', cancel_handler)
        self.assertIn("runner_identity_committed == 1", cancel_handler)
        self.assertIn("if (( session_is_owned == 1 )) && runner_leader_is_live; then", cancel_handler)
        self.assertIn("if runner_leader_is_live; then", cancel_handler)
        self.assertIn("runner_exit_status=kill-timeout", cancel_handler)
        self.assertIn(
            "the rendered-soak runner changed executable while remaining live",
            self.source,
        )

        final_record = self.source[
            self.source.index("write_final_record() {") :
            self.source.index("write_after_record() {")
        ]
        self.assertEqual(final_record.count("voxtral_restore_verified="), 1)

    def test_private_evidence_is_unique_and_policy_is_passed_through(self) -> None:
        for marker in (
            "PRIVATE_GATE_DIR must not already exist",
            'flock -n 9',
            'mkdir -m 700 -- "$gate_root"',
            '"$gate_root/gate-before.txt"',
            '"$gate_root/gate-after.txt"',
            '"$gate_root/gate-result.txt"',
            '"$gate_root/runner-result.txt"',
            '"$gate_root/runner-console.log"',
        ):
            self.assertIn(marker, self.source)
        self.assertNotRegex(self.source, r"(?m)^\s*FAY_SOAK_[A-Z0-9_]+=")
        self.assertIn(
            'exec setsid "$soak_runner" "$package_launcher" "$fay_pid" "$soak_output"',
            self.source,
        )
        self.assertNotIn('"$turn_count" "$@"', self.source)


if __name__ == "__main__":
    unittest.main()
