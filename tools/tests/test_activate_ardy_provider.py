from __future__ import annotations

import json
import os
import platform
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
SCRIPT_PATH = REPO_ROOT / "scripts" / "activate-ardy-provider.sh"


def function_source(source: str, name: str, next_name: str) -> str:
    start = source.index(f"{name}() {{")
    end = source.index(f"\n{next_name}() {{", start)
    return source[start:end]


class ActivateArdyProviderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = SCRIPT_PATH.read_text(encoding="utf-8")

    def test_bash_syntax_and_exact_arity(self) -> None:
        result = subprocess.run(
            ("bash", "-n", str(SCRIPT_PATH)),
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
        self.assertIn("Usage:", result.stderr)
        self.assertIn("if (( $# != 2 )); then", self.source)

    def test_names_images_and_ports_are_fixed(self) -> None:
        for assignment in (
            "readonly PRODUCTION_CONTAINER='ue5-spark-ardy'",
            "readonly CANARY_CONTAINER='ue5-spark-ardy-canary'",
            "readonly TARGET_IMAGE='ue5-spark-ardy:0.3.0'",
            "readonly ROLLBACK_IMAGE='ue5-spark-ardy:0.2.0'",
            "readonly PRODUCTION_PORT=8777",
            "readonly CANARY_PORT=18777",
        ):
            self.assertEqual(self.source.count(assignment), 1)
        self.assertNotRegex(
            self.source,
            r"(?:PRODUCTION_CONTAINER|CANARY_CONTAINER|TARGET_IMAGE|ROLLBACK_IMAGE|"
            r"PRODUCTION_PORT|CANARY_PORT)=\$",
        )

    def test_lifecycle_is_confined_to_exact_owned_containers(self) -> None:
        self.assertNotIn("systemctl", self.source)
        self.assertNotRegex(
            self.source,
            r"\bdocker\s+(?:start|restart|kill|pause|unpause|update|exec|system|volume|image\s+rm)\b",
        )
        self.assertEqual(self.source.count("docker stop --time 20"), 1)
        self.assertEqual(self.source.count("docker rm"), 1)
        for lifecycle_call in (
            'docker_stop_bounded "$canary_container_id"',
            'docker_remove_bounded "$canary_container_id"',
            'docker_stop_bounded "$target_container_id"',
            'docker_stop_bounded "$old_container_id"',
        ):
            self.assertIn(lifecycle_call, self.source)
        self.assertNotIn("fay", self.source.lower())
        self.assertIn('[[ $container_id =~ ^[0-9a-f]{64}$', self.source)
        self.assertNotRegex(self.source, r"=\$\(launch_container\b")
        self.assertIn("capture_owned_run_container", self.source)

    def test_canary_passes_before_production_stop_and_rollback_is_armed(self) -> None:
        canary_validation = self.source.index(
            '"$validator" --port "$CANARY_PORT" --batches 30'
        )
        production_reverified = self.source.index(
            "capture_verified_container production_reverified"
        )
        rollback_arm = self.source.index("rollback_armed=1", production_reverified)
        production_stop = self.source.index(
            'docker_stop_bounded "$old_container_id"', rollback_arm
        )
        target_launch = self.source.index(
            'launch_container target_container_id "$PRODUCTION_CONTAINER"',
            production_stop,
        )
        production_validation = self.source.index(
            '"$validator" --port "$PRODUCTION_PORT" --batches 30', target_launch
        )
        self.assertLess(canary_validation, production_reverified)
        self.assertLess(production_reverified, rollback_arm)
        self.assertLess(rollback_arm, production_stop)
        self.assertLess(production_stop, target_launch)
        self.assertLess(target_launch, production_validation)
        self.assertIn("restore_rollback", self.source)
        self.assertIn("rollback_verified=1", self.source)

    def test_launches_use_captured_immutable_image_ids(self) -> None:
        for marker in (
            'launch_container canary_container_id "$CANARY_CONTAINER" "$target_image_id"',
            'launch_container target_container_id "$PRODUCTION_CONTAINER" "$target_image_id"',
            'launch_container rollback_id "$PRODUCTION_CONTAINER" "$rollback_image_id"',
            'current_runtime_image_id=$(docker_read_bounded inspect',
            'current_runtime_image_id == "$target_image_id"',
            'current_runtime_image_id == "$rollback_image_id"',
        ):
            self.assertIn(marker, self.source)


class ActivateArdyProviderOwnershipFunctionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        source = SCRIPT_PATH.read_text(encoding="utf-8")
        cls.source = source
        capture_owned = function_source(
            source, "capture_owned_run_container", "reconcile_pending_launch"
        )
        reconcile_pending = function_source(
            source, "reconcile_pending_launch", "launch_container"
        )
        launch = function_source(source, "launch_container", "capture_container_logs")
        # macOS ships Bash 3.2.  The production script is Linux/Bash 4+, but
        # these local ownership simulations use equivalent printf-v/while-read
        # forms so the daemon-output handoff is exercised on either platform.
        capture_owned = capture_owned.replace(
            "local -n destination=$1", "local destination_name=$1"
        ).replace(
            "destination=''", "printf -v \"$destination_name\" '%s' ''"
        ).replace(
            "destination=${owned_fields[0]}",
            "printf -v \"$destination_name\" '%s' \"${owned_fields[0]}\"",
        ).replace(
            "mapfile -t owned_fields < <(",
            "while IFS= read -r owned_field; do owned_fields+=(\"$owned_field\"); done < <(",
        ).replace("python3 - ", f'"{sys.executable}" - ')
        reconcile_pending = reconcile_pending.replace(
            "local -n destination=$1", "local destination_name=$1"
        ).replace(
            "destination=''", "printf -v \"$destination_name\" '%s' ''"
        ).replace(
            "destination=$owned_id",
            "printf -v \"$destination_name\" '%s' \"$owned_id\"",
        )
        launch = launch.replace(
            "local -n destination=$1", "local destination_name=$1"
        ).replace(
            "destination=''", "printf -v \"$destination_name\" '%s' ''"
        ).replace(
            "destination=$resolved_id",
            "printf -v \"$destination_name\" '%s' \"$resolved_id\"",
        )
        cls.capture_owned = capture_owned
        cls.reconcile_pending = reconcile_pending
        cls.launch = launch
        cls.cleanup_canary = function_source(source, "cleanup_canary", "restore_rollback")
        cls.on_exit = function_source(source, "on_exit", "handle_signal")
        handle_start = source.index("handle_signal() {")
        handle_end = source.index("\n\ntrap 'on_exit'", handle_start)
        cls.handle_signal = source[handle_start:handle_end]

    def _launch_harness(
        self,
        root: Path,
        *,
        role: str,
        run_status: int,
        stdout: str = "",
        wrong_label: bool = False,
        publication_delay: float = 0.0,
    ) -> str:
        container_id = "a" * 64 if role == "target" else "c" * 64
        name = "ue5-spark-ardy" if role == "target" else "ue5-spark-ardy-canary"
        image = "sha256:" + "1" * 64
        auto_remove = role == "target"
        run_id = "9" * 64
        labels = {
            "com.ue5-spark.ardy.activation-run": "f" * 64 if wrong_label else run_id,
            "com.ue5-spark.ardy.activation-role": role,
        }
        inspect_record = json.dumps(
            [
                {
                    "Id": container_id,
                    "Name": "/" + name,
                    "Image": image,
                    "Config": {"Image": image, "Labels": labels},
                    "HostConfig": {"AutoRemove": auto_remove},
                }
            ]
        )
        stdout_command = f"printf '%s\\n' {stdout!r}" if stdout else ":"
        publication_command = (
            f"( sleep {publication_delay}; printf '%s' {container_id} >\"$cidfile\"; "
            f"touch {root / 'container-visible'} ) &"
            if publication_delay
            else f"printf '%s' {container_id} >\"$cidfile\"; touch {root / 'container-visible'}"
        )
        return textwrap.dedent(
            f"""\
            set -uo pipefail
            PRODUCTION_CONTAINER=ue5-spark-ardy
            CANARY_CONTAINER=ue5-spark-ardy-canary
            PRODUCTION_PORT=8777
            CANARY_PORT=18777
            TARGET_PROVIDER=ardy
            ROLLBACK_PROVIDER=ardy
            RUN_LABEL_KEY=com.ue5-spark.ardy.activation-run
            ROLE_LABEL_KEY=com.ue5-spark.ardy.activation-role
            target_image_id={image}
            rollback_image_id=sha256:{'2' * 64}
            activation_run_id={run_id}
            evidence_root={root}
            models_root={root / 'models'}
            rollback_models_root={root / 'models'}
            pending_launch_active=0
            pending_launch_name=''
            pending_launch_image=''
            pending_launch_port=''
            pending_launch_provider=''
            pending_launch_auto_remove=''
            pending_launch_role=''
            pending_launch_cidfile=''
            canary_container_id=''
            target_container_id=''
            docker_run_bounded() {{
                local cidfile='' index=1
                while (( index <= $# )); do
                    if [[ ${{!index}} == --cidfile ]]; then
                        index=$((index + 1))
                        cidfile=${{!index}}
                        break
                    fi
                    index=$((index + 1))
                done
                {publication_command}
                {stdout_command}
                return {run_status}
            }}
            docker_read_bounded() {{
                [[ -e {root / 'container-visible'} ]] || return 1
                printf '%s\n' '{inspect_record}'
            }}
            sleep_isolated() {{ sleep 0.02; }}
            clear_stably_absent_auto_remove_launch() {{ return 1; }}
            {self.capture_owned}
            {self.reconcile_pending}
            {self.launch}
            status=0
            launch_container {role}_container_id {name} {image} \
                {'8777' if role == 'target' else '18777'} ardy \
                {'true' if auto_remove else 'false'} {role} || status=$?
            printf 'status=%s\nid=%s\npending=%s\n' \
                "$status" "${{{role}_container_id}}" "$pending_launch_active"
            """
        )

    def test_daemon_created_container_is_adopted_when_cli_output_is_lost(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ardy-owned-output-lost-") as directory:
            root = Path(directory)
            (root / "models").mkdir()
            result = subprocess.run(
                ("bash", "-c", self._launch_harness(root, role="target", run_status=125)),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("status=0", result.stdout)
            self.assertIn(f"id={'a' * 64}", result.stdout)
            self.assertIn("pending=0", result.stdout)

    def test_delayed_daemon_publication_is_adopted_within_bound(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ardy-owned-publish-delay-") as directory:
            root = Path(directory)
            (root / "models").mkdir()
            result = subprocess.run(
                (
                    "bash",
                    "-c",
                    self._launch_harness(
                        root,
                        role="canary",
                        run_status=125,
                        publication_delay=0.1,
                    ),
                ),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=5,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("status=0", result.stdout)
            self.assertIn(f"id={'c' * 64}", result.stdout)
            self.assertIn("pending=0", result.stdout)

    def test_malformed_stdout_is_ignored_in_favor_of_labeled_name(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ardy-owned-malformed-") as directory:
            root = Path(directory)
            (root / "models").mkdir()
            result = subprocess.run(
                (
                    "bash",
                    "-c",
                    self._launch_harness(
                        root, role="target", run_status=0, stdout="not-a-container-id"
                    ),
                ),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("status=0", result.stdout)
            self.assertIn(f"id={'a' * 64}", result.stdout)

    def test_wrong_run_label_cannot_be_adopted(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ardy-owned-wrong-label-") as directory:
            root = Path(directory)
            (root / "models").mkdir()
            result = subprocess.run(
                (
                    "bash",
                    "-c",
                    self._launch_harness(
                        root, role="canary", run_status=125, wrong_label=True
                    ),
                ),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("status=125", result.stdout)
            self.assertIn("id=", result.stdout)
            self.assertIn("pending=1", result.stdout)

    def test_second_and_third_signals_cannot_interrupt_exit_rollback(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ardy-exit-double-signal-") as directory:
            root = Path(directory)
            source = textwrap.dedent(
                f"""\
                set -uo pipefail
                last_error=forced-test-failure
                activation_complete=0
                rollback_armed=1
                rollback_verified=0
                canary_container_id=''
                target_container_id=''
                old_container_id=''
                evidence_root={root}
                recovery_mode=1
                rollback_attempted=0
                rollback_status=not-required
                cleanup_status=not-required
                exit_cleanup_signals_masked=0
                exit_cleanup_started_utc=not-started
                activation_run_id={'9' * 64}
                pending_launch_active=0
                pending_launch_role=''
                pending_launch_absence_verified=0
                pending_launch_absent_id=''
                target_image_id=sha256:{'1' * 64}
                rollback_image_id=sha256:{'2' * 64}
                cleanup_canary() {{ return 0; }}
                reconcile_pending_launch() {{ return 1; }}
                restore_rollback() {{
                    touch {root / 'rollback-started'}
                    sleep 1
                    rollback_verified=1
                    touch {root / 'rollback-finished'}
                    return 0
                }}
                write_record() {{
                    local destination=$1
                    shift
                    printf '%s\n' "$@" >"$destination"
                }}
                {self.on_exit}
                {self.handle_signal}
                trap 'on_exit' EXIT
                trap 'handle_signal HUP 129' HUP
                trap 'handle_signal INT 130' INT
                trap 'handle_signal TERM 143' TERM
                exit 7
                """
            )
            process = subprocess.Popen(
                ("bash", "-c", source),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and not (root / "rollback-started").exists():
                time.sleep(0.01)
            self.assertTrue((root / "rollback-started").exists())
            process.send_signal(signal.SIGTERM)
            process.send_signal(signal.SIGINT)
            stdout, stderr = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 7, stdout + stderr)
            self.assertTrue((root / "rollback-finished").exists())
            result = (root / "activation-result.txt").read_text(encoding="utf-8")
            self.assertIn("status=failed", result)
            self.assertIn("rollback_status=verified", result)
            self.assertIn("exit_cleanup_signals_masked=1", result)

    def test_unresolved_pending_launch_can_never_publish_verified_cleanup(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ardy-exit-pending-") as directory:
            root = Path(directory)
            source = textwrap.dedent(
                f"""\
                set -uo pipefail
                last_error=forced-test-failure
                activation_complete=0
                rollback_armed=0
                rollback_verified=0
                canary_container_id=''
                target_container_id=''
                old_container_id=''
                evidence_root={root}
                recovery_mode=1
                rollback_attempted=0
                rollback_status=not-required
                cleanup_status=not-required
                exit_cleanup_signals_masked=0
                exit_cleanup_started_utc=not-started
                activation_run_id={'9' * 64}
                pending_launch_active=1
                pending_launch_name=ue5-spark-ardy
                pending_launch_role=rollback
                pending_launch_absence_verified=0
                pending_launch_absent_id=''
                target_image_id=sha256:{'1' * 64}
                rollback_image_id=sha256:{'2' * 64}
                cleanup_canary() {{ return 0; }}
                reconcile_pending_launch_bounded() {{ return 1; }}
                clear_stably_absent_auto_remove_launch() {{ return 1; }}
                write_record() {{
                    local destination=$1
                    shift
                    [[ ! -e $destination ]] || return 1
                    printf '%s\n' "$@" >"$destination"
                }}
                {self.on_exit}
                trap 'on_exit' EXIT
                exit 7
                """
            )
            result = subprocess.run(
                ("bash", "-c", source),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(result.returncode, 7, result.stdout + result.stderr)
            record = (root / "activation-result.txt").read_text(encoding="utf-8")
            self.assertIn("cleanup_status=failed", record)
            self.assertIn("pending_launch_active=1", record)
            unresolved = root / "pending-launch-unresolved.txt"
            self.assertTrue(unresolved.is_file())
            self.assertIn(
                "daemon-publication-not-observed-within-bounded-reconciliation",
                unresolved.read_text(encoding="utf-8"),
            )


class ActivateArdyProviderAdditionalStaticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = SCRIPT_PATH.read_text(encoding="utf-8")

    def test_absent_service_fails_closed_without_touching_the_fixed_port(self) -> None:
        for marker in (
            'loopback_port_is_unused "$PRODUCTION_PORT"',
            "production ARDY is absent but its fixed loopback port is unexpectedly owned",
            "production ARDY 0.2.0 is absent; no exact live rollback can be captured",
            '"recovery_mode=$recovery_mode"',
        ):
            self.assertIn(marker, self.source)
        self.assertNotIn("recovery_mode=1", self.source)
        port_check = self.source[
            self.source.index("loopback_port_is_unused()") :
            self.source.index("capture_verified_container()")
        ]
        self.assertNotIn("|| true", port_check)

    def test_lock_and_exit_recovery_are_global_and_auditable(self) -> None:
        for marker in (
            'lock_file="$lock_parent/ue5-spark-ardy.activation.lock"',
            "rollback_attempted=1",
            "rollback_status='verified'",
            "rollback_status='failed'",
            "cleanup_status='failed'",
            "EMERGENCY: sealed ARDY rollback could not be verified",
            '"rollback_status=$rollback_status"',
            '"cleanup_status=$cleanup_status"',
            'rollback-blocked.txt',
            "trap '' HUP INT TERM",
            '"exit_cleanup_signals_masked=$exit_cleanup_signals_masked"',
            'timeout --foreground --signal=TERM --kill-after=5',
            'setsid --wait timeout --foreground',
        ):
            self.assertIn(marker, self.source)
        self.assertNotIn('lock_file="$private_root/.ardy-activation.lock"', self.source)

    def test_new_launches_use_exact_per_run_ownership_labels(self) -> None:
        for marker in (
            "readonly RUN_LABEL_KEY='com.ue5-spark.ardy.activation-run'",
            "readonly ROLE_LABEL_KEY='com.ue5-spark.ardy.activation-role'",
            "activation_run_id=$(python3 -c",
            '--cidfile "$cidfile"',
            '--label "$RUN_LABEL_KEY=$activation_run_id"',
            '--label "$ROLE_LABEL_KEY=$role"',
            'labels.get(run_label_key) != activation_run_id',
            'labels.get(role_label_key) != expected_role',
            'reconcile_pending_launch_bounded resolved_id',
            'pending-launch-unresolved.txt',
        ):
            self.assertIn(marker, self.source)
        self.assertNotIn('resolved_id=$(reconcile_pending_launch)', self.source)
        self.assertNotIn(
            'launch_container canary_container_id "$CANARY_CONTAINER" "$TARGET_IMAGE"',
            self.source,
        )

    def test_auto_removed_cidfile_is_only_read_only_absence_evidence(self) -> None:
        proof = function_source(
            self.source,
            "container_name_and_id_are_absent",
            "launch_container",
        )
        for marker in (
            'rows=$(docker_read_bounded container ls --all --no-trunc',
            '[[ $container_id != "$expected_id"',
            '$container_name != "$expected_name"',
            'for attempt in $(seq 1 5)',
            'loopback_port_is_unused "$pending_launch_port"',
            'sleep_isolated 1 || return 1',
            "lifecycle_action_from_cidfile=none",
            "pending_launch_absence_verified=1",
            "pending_launch_active=0",
        ):
            self.assertIn(marker, proof)
        self.assertNotRegex(proof, r"docker_(?:logs|stop|remove)_bounded")
        self.assertNotIn("target_container_id=$cidfile_id", proof)
        self.assertNotIn("canary_container_id=$cidfile_id", proof)

    def test_private_evidence_and_runtime_isolation_are_sealed(self) -> None:
        for marker in (
            "PRIVATE_EVIDENCE_DIR must not already exist",
            "PRIVATE_EVIDENCE_DIR must be below a logs-private root",
            'flock -n 9',
            'mkdir -m 700 -- "$evidence_root"',
            "--network host",
            "--read-only",
            "--cap-drop ALL",
            "--security-opt no-new-privileges:true",
            "--pids-limit 512",
            "--shm-size 4g",
            "--tmpfs /tmp:rw,noexec,nosuid,size=1g",
            'type=bind,src=$launch_models_root,dst=/models,readonly',
            '"$validator" --port "$CANARY_PORT" --batches 30',
            '"$validator" --port "$PRODUCTION_PORT" --batches 30',
            'qualify_v1_rollback "$PRODUCTION_PORT"',
            '"embeddingCount": 3',
            'urllib.request.ProxyHandler({})',
            '"protocolVersion": 1',
            '"treeSha256": aggregate.hexdigest()',
            '"huggingface_token"',
            '[[ $models_root != "$rollback_models_root" ]]',
            'the v2 candidate models cannot be nested below the v1 rollback models',
            'the v1 rollback models cannot be nested below the v2 candidate models',
            're.search(r"(?:TOKEN|PASSWORD|SECRET|CREDENTIAL|API_KEY)$"',
        ):
            self.assertIn(marker, self.source)

    def test_real_v1_rollback_is_strictly_qualified_and_content_sealed(self) -> None:
        for marker in (
            "readonly ROLLBACK_IMAGE='ue5-spark-ardy:0.2.0'",
            "readonly ROLLBACK_PROVIDER='ardy'",
            'behaviors = ("idle", "listen", "explain")',
            '"protocolVersion": 1',
            '"embeddingCount": 3',
            '"coordinateSystem", "frames"',
            'len(batch["frames"]) != 8',
            'len(joints) != 27',
            'joints[5] != identity',
            'joints[6] != identity',
            'for index in range(30)',
            'discover_readonly_models_root rollback_models_root',
            'seal_models_tree rollback_models_seal',
            '[[ $rollback_models_reverified == "$rollback_models_seal" ]]',
            '[[ $restored_models_seal == "$rollback_models_seal" ]]',
            '[[ $target_models_after == "$target_models_seal" ]]',
            '"$rollback_models_root" rollback',
            "production ARDY 0.2.0 is absent; no exact live rollback can be captured",
        ):
            self.assertIn(marker, self.source)
        self.assertNotIn("readonly ROLLBACK_PROVIDER='mock'", self.source)
        self.assertNotIn("readonly ROLLBACK_IMAGE='ue5-spark-ardy:0.1.0'", self.source)


@unittest.skipUnless(
    platform.system() == "Linux"
    and platform.machine() == "aarch64"
    and Path(f"/run/user/{os.getuid()}").is_dir(),
    "the activation state-machine harness requires Linux/aarch64 user runtime state",
)
class ActivateArdyProviderStateMachineTests(unittest.TestCase):
    target_image_id = "sha256:" + "1" * 64
    rollback_image_id = "sha256:" + "2" * 64

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="ardy-activation-test-")
        self.root = Path(self.temporary.name)
        self.test_repo = self.root / "repo"
        self.script = self.test_repo / "scripts" / SCRIPT_PATH.name
        self.validator = self.test_repo / "tools" / "validate_ardy_service.py"
        self.models = self.root / "models-private" / "ardy-v2-candidate"
        self.rollback_models = self.root / "models-private" / "ardy-v1-rollback"
        self.logs = self.root / "logs-private"
        self.fake_bin = self.root / "fake-bin"
        self.state_file = self.root / "docker-state.json"
        self.command_log = self.root / "docker-commands.jsonl"
        self.validator_count = self.root / "validator-count.txt"

        self.script.parent.mkdir(parents=True)
        self.validator.parent.mkdir(parents=True)
        (self.models / "embeddings").mkdir(parents=True)
        (self.rollback_models / "embeddings").mkdir(parents=True)
        (self.models / "embeddings" / "manifest.json").write_text(
            '{"schema":2,"embeddingCount":9}', encoding="utf-8"
        )
        (self.rollback_models / "embeddings" / "manifest.json").write_text(
            '{"schema":1,"embeddingCount":3}', encoding="utf-8"
        )
        self.logs.mkdir()
        self.fake_bin.mkdir()
        self.state_file.write_text(
            json.dumps(self._initial_v1_record()), encoding="utf-8"
        )
        self.script.write_text(SCRIPT_PATH.read_text(encoding="utf-8"), encoding="utf-8")
        self.script.chmod(0o755)
        self._write_executable("docker", self._fake_docker_source())
        self._write_executable("ss", self._fake_ss_source())
        self._write_executable("curl", self._fake_curl_source())
        (self.fake_bin / "sitecustomize.py").write_text(
            self._fake_urllib_sitecustomize_source(), encoding="utf-8"
        )
        self._write_executable(
            "sleep",
            "#!/usr/bin/env python3\n"
            "import sys, time\n"
            "time.sleep(min(float(sys.argv[1]), 0.02))\n",
        )
        self.validator.write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env python3
                import json
                import os
                from pathlib import Path

                counter = Path(os.environ["FAKE_VALIDATOR_COUNT"])
                count = int(counter.read_text(encoding="utf-8")) if counter.exists() else 0
                counter.write_text(str(count + 1), encoding="utf-8")
                statuses = [int(value) for value in os.environ.get(
                    "FAKE_VALIDATOR_STATUSES", "0"
                ).split(",")]
                status = statuses[min(count, len(statuses) - 1)]
                if status == 0:
                    print(json.dumps({"status": "passed", "batchCount": 30}))
                raise SystemExit(status)
                """
            ),
            encoding="utf-8",
        )
        self.validator.chmod(0o755)
        self.environment = os.environ.copy()
        self.environment.update(
            {
                "PATH": f"{self.fake_bin}:{self.environment['PATH']}",
                "FAKE_DOCKER_STATE": str(self.state_file),
                "FAKE_DOCKER_LOG": str(self.command_log),
                "FAKE_MODELS_ROOT": str(self.models.resolve()),
                "FAKE_VALIDATOR_COUNT": str(self.validator_count),
                "PYTHONPATH": str(self.fake_bin),
            }
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _initial_v1_record(self) -> dict[str, object]:
        rollback_image_id = "sha256:" + "2" * 64
        return {
            "ue5-spark-ardy": {
                "Id": "d" * 64,
                "Name": "/ue5-spark-ardy",
                "Image": rollback_image_id,
                "RestartCount": 0,
                "State": {
                    "Running": True,
                    "Dead": False,
                    "OOMKilled": False,
                    "Error": "",
                    "Pid": 4100,
                    "StartedAt": "2026-07-20T00:00:00Z",
                },
                "Config": {
                    "Image": rollback_image_id,
                    "User": f"{os.getuid()}:{os.getgid()}",
                    "Cmd": [
                        "--host", "127.0.0.1", "--port", "8777",
                        "--provider", "ardy", "--models-root", "/models",
                    ],
                    "Env": [],
                    "Labels": {},
                },
                "HostConfig": {
                    "AutoRemove": True,
                    "NetworkMode": "host",
                    "ReadonlyRootfs": True,
                    "CapDrop": ["ALL"],
                    "SecurityOpt": ["no-new-privileges:true"],
                    "PidsLimit": 512,
                    "ShmSize": 4 * 1024**3,
                    "Tmpfs": {"/tmp": "rw,noexec,nosuid,size=1g"},
                    "DeviceRequests": [{
                        "Driver": "",
                        "Count": -1,
                        "DeviceIDs": None,
                        "Capabilities": [["gpu"]],
                        "Options": {},
                    }],
                },
                "Mounts": [{
                    "Type": "bind",
                    "Source": str(self.rollback_models.resolve()),
                    "Destination": "/models",
                    "RW": False,
                    "Mode": "",
                    "Propagation": "rprivate",
                }],
                "FakePort": "8777",
                "FakeProvider": "ardy",
            }
        }

    def _write_executable(self, name: str, source: str) -> None:
        destination = self.fake_bin / name
        destination.write_text(source, encoding="utf-8")
        destination.chmod(0o755)

    @staticmethod
    def _fake_docker_source() -> str:
        return textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import json
            import os
            import sys
            import time
            from pathlib import Path

            state_path = Path(os.environ["FAKE_DOCKER_STATE"])
            log_path = Path(os.environ["FAKE_DOCKER_LOG"])
            target_image_id = "sha256:" + "1" * 64
            rollback_image_id = "sha256:" + "2" * 64
            args = sys.argv[1:]
            with log_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(args) + "\\n")

            def load():
                return json.loads(state_path.read_text(encoding="utf-8"))

            def save(value):
                state_path.write_text(json.dumps(value), encoding="utf-8")

            def locate(value, identifier):
                for name, record in value.items():
                    if identifier in {name, record["Id"], record["Name"].lstrip("/")}:
                        return name, record
                return None, None

            if args[:2] == ["image", "inspect"]:
                image = args[-1]
                identifiers = {
                    "ue5-spark-ardy:0.3.0": target_image_id,
                    "ue5-spark-ardy:0.2.0": rollback_image_id,
                    target_image_id: target_image_id,
                    rollback_image_id: rollback_image_id,
                }
                if image not in identifiers:
                    raise SystemExit(1)
                print(identifiers[image])
                raise SystemExit(0)

            if args[:2] == ["container", "ls"]:
                state = load()
                for name, record in state.items():
                    print(f'{record["Id"]} {name}')
                raise SystemExit(0)

            if args and args[0] == "inspect":
                identifier = args[-1]
                state = load()
                _name, record = locate(state, identifier)
                if record is None:
                    raise SystemExit(1)
                if "--format" in args:
                    template = args[args.index("--format") + 1]
                    values = {
                        "{{.Id}}": record["Id"],
                        "{{.Image}}": record["Image"],
                        "{{.Config.Image}}": record["Config"]["Image"],
                    }
                    if template not in values:
                        raise SystemExit(2)
                    print(values[template])
                else:
                    print(json.dumps([record]))
                raise SystemExit(0)

            if args and args[0] == "run":
                options = {}
                labels = {}
                auto_remove = False
                index = 1
                value_options = {
                    "--name", "--gpus", "--network", "--cap-drop", "--security-opt",
                    "--pids-limit", "--shm-size", "--tmpfs", "--user", "--mount",
                    "--cidfile",
                }
                flag_options = {"--detach", "--read-only"}
                while index < len(args):
                    item = args[index]
                    if item == "--rm":
                        auto_remove = True
                        index += 1
                    elif item == "--label":
                        key, value = args[index + 1].split("=", 1)
                        labels[key] = value
                        index += 2
                    elif item in flag_options:
                        options[item] = True
                        index += 1
                    elif item in value_options:
                        options[item] = args[index + 1]
                        index += 2
                    else:
                        break
                image = args[index]
                command = args[index + 1 :]
                name = options["--name"]
                provider = command[command.index("--provider") + 1]
                port = command[command.index("--port") + 1]
                role = labels.get("com.ue5-spark.ardy.activation-role", "")
                if os.environ.get("FAKE_DOCKER_PRECREATE_DELAY_ROLE") == role:
                    marker = os.environ.get("FAKE_DOCKER_DELAY_MARKER")
                    if marker:
                        Path(marker).touch()
                    time.sleep(float(os.environ.get("FAKE_DOCKER_DELAY_SECONDS", "1")))
                if name == "ue5-spark-ardy-canary":
                    container_id, pid = "c" * 64, 4101
                elif role == "target":
                    container_id, pid = "a" * 64, 4102
                else:
                    container_id, pid = "b" * 64, 4103
                state = load()
                if name in state:
                    raise SystemExit(125)
                mount = dict(
                    part.split("=", 1) if "=" in part else (part, "")
                    for part in options["--mount"].split(",")
                )
                record = {
                    "Id": container_id,
                    "Name": "/" + name,
                    "Image": image,
                    "RestartCount": 0,
                    "State": {
                        "Running": True,
                        "Dead": False,
                        "OOMKilled": False,
                        "Error": "",
                        "Pid": pid,
                        "StartedAt": "2026-07-21T00:00:00Z",
                    },
                    "Config": {
                        "Image": image,
                        "User": options["--user"],
                        "Cmd": command,
                        "Env": [],
                        "Labels": labels,
                    },
                    "HostConfig": {
                        "AutoRemove": auto_remove,
                        "NetworkMode": options["--network"],
                        "ReadonlyRootfs": True,
                        "CapDrop": [options["--cap-drop"]],
                        "SecurityOpt": [options["--security-opt"]],
                        "PidsLimit": int(options["--pids-limit"]),
                        "ShmSize": 4 * 1024**3,
                        "Tmpfs": {"/tmp": "rw,noexec,nosuid,size=1g"},
                        "DeviceRequests": [{
                            "Driver": "",
                            "Count": -1,
                            "DeviceIDs": None,
                            "Capabilities": [["gpu"]],
                            "Options": {},
                        }],
                    },
                    "Mounts": [{
                        "Type": "bind",
                        "Source": mount["src"],
                        "Destination": mount["dst"],
                        "RW": False,
                    }],
                    "FakePort": port,
                    "FakeProvider": provider,
                }
                if os.environ.get("FAKE_DOCKER_DEFERRED_PUBLICATION_ROLE") == role:
                    marker = os.environ.get("FAKE_DOCKER_DELAY_MARKER")
                    if marker:
                        Path(marker).touch()
                    child_pid = os.fork()
                    if child_pid == 0:
                        null_fd = os.open(os.devnull, os.O_RDWR)
                        for fd in (0, 1, 2):
                            os.dup2(null_fd, fd)
                        if null_fd > 2:
                            os.close(null_fd)
                        time.sleep(float(os.environ.get("FAKE_DOCKER_DELAY_SECONDS", "0.2")))
                        delayed_state = load()
                        if name not in delayed_state:
                            delayed_state[name] = record
                            save(delayed_state)
                            Path(options["--cidfile"]).write_text(
                                container_id, encoding="utf-8"
                            )
                        os._exit(0)
                    raise SystemExit(125)
                state[name] = record
                save(state)
                Path(options["--cidfile"]).write_text(container_id, encoding="utf-8")
                if os.environ.get("FAKE_DOCKER_AUTOREMOVE_BEFORE_INSPECT_ROLE") == role:
                    state = load()
                    del state[name]
                    save(state)
                    print(container_id)
                    raise SystemExit(0)
                if os.environ.get("FAKE_DOCKER_WRONG_LABEL_ROLE") == role:
                    state = load()
                    state[name]["Config"]["Labels"][
                        "com.ue5-spark.ardy.activation-run"
                    ] = "f" * 64
                    save(state)
                if os.environ.get("FAKE_DOCKER_DELAY_ROLE") == role:
                    marker = os.environ.get("FAKE_DOCKER_DELAY_MARKER")
                    if marker:
                        Path(marker).touch()
                    time.sleep(float(os.environ.get("FAKE_DOCKER_DELAY_SECONDS", "1")))
                if os.environ.get("FAKE_DOCKER_LOST_OUTPUT_ROLE") == role:
                    raise SystemExit(int(os.environ.get("FAKE_DOCKER_LOST_OUTPUT_STATUS", "125")))
                if os.environ.get("FAKE_DOCKER_MALFORMED_OUTPUT_ROLE") == role:
                    print("not-a-container-id")
                else:
                    print(container_id)
                raise SystemExit(0)

            if args and args[0] in {"logs", "stop", "rm"}:
                operation = args[0]
                identifier = args[-1]
                state = load()
                name, record = locate(state, identifier)
                if record is None:
                    raise SystemExit(1)
                if operation == "logs":
                    print("fake isolated ARDY container log")
                elif operation == "stop":
                    if record["HostConfig"]["AutoRemove"]:
                        del state[name]
                    else:
                        record["State"]["Running"] = False
                    save(state)
                    print(identifier)
                else:
                    del state[name]
                    save(state)
                    print(identifier)
                raise SystemExit(0)

            raise SystemExit(2)
            """
        )

    @staticmethod
    def _fake_ss_source() -> str:
        return textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import json
            import os
            import re
            import sys
            from pathlib import Path

            if os.environ.get("FAKE_SS_FAIL") == "1":
                raise SystemExit(2)
            match = re.search(r":([0-9]+)", " ".join(sys.argv[1:]))
            if match is None:
                raise SystemExit(2)
            port = match.group(1)
            state = json.loads(Path(os.environ["FAKE_DOCKER_STATE"]).read_text(
                encoding="utf-8"
            ))
            for record in state.values():
                if record["State"]["Running"] and record["FakePort"] == port:
                    suffix = ""
                    if any("p" in argument for argument in sys.argv[1:] if argument.startswith("-")):
                        suffix = f' users:(("python",pid={record["State"]["Pid"]},fd=3))'
                    print(f"LISTEN 0 128 127.0.0.1:{port} 0.0.0.0:*{suffix}")
            """
        )

    @staticmethod
    def _fake_curl_source() -> str:
        return textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import json
            import os
            import re
            import sys
            from pathlib import Path

            match = re.search(r":([0-9]+)/healthz$", sys.argv[-1])
            if match is None:
                raise SystemExit(2)
            port = match.group(1)
            state = json.loads(Path(os.environ["FAKE_DOCKER_STATE"]).read_text(
                encoding="utf-8"
            ))
            for record in state.values():
                if record["State"]["Running"] and record["FakePort"] == port:
                    if record["FakeProvider"] != "mock":
                        raise SystemExit(1)
                    print(json.dumps({
                        "status": "ready",
                        "provider": "mock",
                        "protocolVersion": 1,
                        "fps": 20,
                        "bufferFrames": 8,
                        "facialControl": "excluded",
                        "checkpoint": None,
                        "embeddingCount": 0,
                        "p95GenerationMs": 0.0,
                    }))
                    raise SystemExit(0)
            raise SystemExit(1)
            """
        )

    @staticmethod
    def _fake_urllib_sitecustomize_source() -> str:
        return textwrap.dedent(
            """\
            import io
            import json
            import os
            import urllib.parse
            import urllib.request
            from email.message import Message
            from pathlib import Path

            _real_urlopen = urllib.request.urlopen

            class FakeResponse:
                def __init__(self, value):
                    self.status = 200
                    self._body = json.dumps(value, separators=(",", ":")).encode()
                    self.headers = Message()
                    self.headers["Content-Type"] = "application/json"

                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    return False

                def read(self, amount=-1):
                    return self._body if amount < 0 else self._body[:amount]

            def fake_urlopen(request, *args, **kwargs):
                url = request.full_url if hasattr(request, "full_url") else str(request)
                parsed = urllib.parse.urlparse(url)
                if parsed.hostname != "127.0.0.1" or parsed.port != 8777:
                    return _real_urlopen(request, *args, **kwargs)
                state = json.loads(Path(os.environ["FAKE_DOCKER_STATE"]).read_text(
                    encoding="utf-8"
                ))
                record = state.get("ue5-spark-ardy")
                rollback_image_id = "sha256:" + "2" * 64
                if (
                    record is None
                    or record.get("Image") != rollback_image_id
                    or record.get("FakeProvider") != "ardy"
                    or record.get("FakePort") != "8777"
                    or record.get("State", {}).get("Running") is not True
                ):
                    raise OSError("sealed v1 endpoint is unavailable")
                if parsed.path == "/healthz":
                    return FakeResponse({
                        "status": "ready",
                        "provider": "ardy",
                        "protocolVersion": 1,
                        "fps": 20,
                        "bufferFrames": 8,
                        "facialControl": "excluded",
                        "checkpoint": "ARDY-Core-RP-20FPS-Horizon8",
                        "embeddingCount": 3,
                        "p95GenerationMs": 130.0,
                    })
                if parsed.path != "/v1/poses":
                    raise OSError("unsupported fake v1 path")
                payload = json.loads((request.data or b"{}").decode())
                sequence = int(payload.get("afterSequence", 0)) + 1
                identity = [0.0, 0.0, 0.0, 1.0]
                first_time = (sequence - 1) * 0.4
                frames = []
                for index in range(8):
                    frames.append({
                        "time": first_time + index * 0.05,
                        "root": [0.0, 0.0, 0.0, *identity],
                        "joints": [identity[:] for _ in range(27)],
                        "contacts": [0.0, 0.0, 0.0, 0.0],
                    })
                return FakeResponse({
                    "version": 1,
                    "sequence": sequence,
                    "fps": 20,
                    "coordinateSystem": "ardy-y-up-z-forward-meters",
                    "frames": frames,
                })

            class FakeOpener:
                def open(self, request, *args, **kwargs):
                    return fake_urlopen(request, *args, **kwargs)

            urllib.request.urlopen = fake_urlopen
            urllib.request.build_opener = lambda *_handlers: FakeOpener()
            """
        )

    def _run(
        self,
        name: str,
        statuses: str,
        *,
        ss_failure: bool = False,
        extra_environment: dict[str, str] | None = None,
    ):
        evidence = self.logs / name
        environment = self.environment.copy()
        environment["FAKE_VALIDATOR_STATUSES"] = statuses
        if ss_failure:
            environment["FAKE_SS_FAIL"] = "1"
        if extra_environment:
            environment.update(extra_environment)
        result = subprocess.run(
            ("bash", str(self.script), str(self.models), str(evidence)),
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            env=environment,
        )
        state = json.loads(self.state_file.read_text(encoding="utf-8"))
        commands = [
            json.loads(line)
            for line in self.command_log.read_text(encoding="utf-8").splitlines()
        ]
        return result, evidence, state, commands

    @staticmethod
    def _result_record(evidence: Path) -> dict[str, str]:
        return dict(
            line.split("=", 1)
            for line in (evidence / "activation-result.txt")
            .read_text(encoding="utf-8")
            .splitlines()
            if "=" in line
        )

    def test_ss_error_fails_before_any_container_launch(self) -> None:
        result, evidence, state, commands = self._run(
            "ss-failure", "0", ss_failure=True
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(set(state), {"ue5-spark-ardy"})
        self.assertEqual(
            state["ue5-spark-ardy"]["Config"]["Image"], self.rollback_image_id
        )
        self.assertFalse(any(command and command[0] == "run" for command in commands))
        record = self._result_record(evidence)
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["rollback_attempted"], "0")

    def test_canary_failure_leaves_the_exact_live_v1_provider_untouched(self) -> None:
        result, evidence, state, _commands = self._run("canary-failure", "1")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(set(state), {"ue5-spark-ardy"})
        production = state["ue5-spark-ardy"]
        self.assertEqual(production["FakeProvider"], "ardy")
        self.assertEqual(production["Config"]["Image"], self.rollback_image_id)
        record = self._result_record(evidence)
        self.assertEqual(record["rollback_attempted"], "0")
        self.assertEqual(record["rollback_verified"], "0")
        self.assertEqual(record["rollback_status"], "not-required")
        self.assertEqual(record["cleanup_status"], "verified")

    def test_target_failure_stops_exact_target_then_restores_real_v1(self) -> None:
        result, evidence, state, commands = self._run("target-failure", "0,1")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(set(state), {"ue5-spark-ardy"})
        self.assertEqual(
            state["ue5-spark-ardy"]["Config"]["Image"], self.rollback_image_id
        )
        stopped_ids = [
            command[-1] for command in commands if command and command[0] == "stop"
        ]
        self.assertIn("a" * 64, stopped_ids)
        record = self._result_record(evidence)
        self.assertEqual(record["rollback_status"], "verified")

    def test_rapid_auto_removed_target_restores_v1_without_cid_lifecycle(self) -> None:
        result, evidence, state, commands = self._run(
            "target-auto-removed-before-inspect",
            "0",
            extra_environment={
                "FAKE_DOCKER_AUTOREMOVE_BEFORE_INSPECT_ROLE": "target"
            },
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(set(state), {"ue5-spark-ardy"})
        self.assertEqual(
            state["ue5-spark-ardy"]["Config"]["Image"], self.rollback_image_id
        )
        lifecycle_ids = [
            command[-1]
            for command in commands
            if command and command[0] in {"logs", "stop", "rm"}
        ]
        self.assertNotIn("a" * 64, lifecycle_ids)
        record = self._result_record(evidence)
        self.assertEqual(record["rollback_status"], "verified")
        self.assertEqual(record["rollback_verified"], "1")
        self.assertEqual(record["pending_launch_active"], "0")
        self.assertEqual(record["pending_launch_absence_verified"], "1")
        absence = evidence / "target-auto-remove-absence.txt"
        self.assertIn(
            "lifecycle_action_from_cidfile=none",
            absence.read_text(encoding="utf-8"),
        )

    def test_successful_v1_migration_leaves_only_v2_provider(self) -> None:
        result, evidence, state, commands = self._run("migration-success", "0,0")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(set(state), {"ue5-spark-ardy"})
        production = state["ue5-spark-ardy"]
        self.assertEqual(production["FakeProvider"], "ardy")
        self.assertEqual(production["Config"]["Image"], self.target_image_id)
        run_images = [
            next(item for item in command if item.startswith("sha256:"))
            for command in commands
            if command and command[0] == "run"
        ]
        self.assertEqual(run_images, [self.target_image_id, self.target_image_id])
        record = self._result_record(evidence)
        self.assertEqual(record["status"], "passed")
        self.assertEqual(record["activation_complete"], "1")
        self.assertEqual(record["rollback_attempted"], "0")
        self.assertEqual(record["recovery_mode"], "0")

    def test_daemon_created_canary_with_lost_cli_output_is_adopted(self) -> None:
        result, evidence, state, _commands = self._run(
            "canary-output-lost",
            "0,0",
            extra_environment={"FAKE_DOCKER_LOST_OUTPUT_ROLE": "canary"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(set(state), {"ue5-spark-ardy"})
        self.assertEqual(state["ue5-spark-ardy"]["FakeProvider"], "ardy")
        record = self._result_record(evidence)
        self.assertEqual(record["status"], "passed")
        self.assertRegex(record["activation_run_id"], r"^[0-9a-f]{64}$")

    def test_delayed_daemon_publication_is_boundedly_adopted(self) -> None:
        publication_started = self.root / "deferred-canary-publication"
        result, evidence, state, _commands = self._run(
            "canary-publication-delayed",
            "0,0",
            extra_environment={
                "FAKE_DOCKER_DEFERRED_PUBLICATION_ROLE": "canary",
                "FAKE_DOCKER_DELAY_MARKER": str(publication_started),
                "FAKE_DOCKER_DELAY_SECONDS": "0.2",
            },
        )
        self.assertTrue(publication_started.exists())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(set(state), {"ue5-spark-ardy"})
        self.assertEqual(state["ue5-spark-ardy"]["FakeProvider"], "ardy")
        record = self._result_record(evidence)
        self.assertEqual(record["status"], "passed")
        self.assertEqual(record["pending_launch_active"], "0")

    def test_daemon_created_target_with_lost_cli_output_is_adopted(self) -> None:
        result, evidence, state, _commands = self._run(
            "target-output-lost",
            "0,0",
            extra_environment={"FAKE_DOCKER_LOST_OUTPUT_ROLE": "target"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(set(state), {"ue5-spark-ardy"})
        self.assertEqual(state["ue5-spark-ardy"]["FakeProvider"], "ardy")
        self.assertEqual(self._result_record(evidence)["pending_launch_active"], "0")

    def test_malformed_launch_stdout_never_becomes_a_lifecycle_target(self) -> None:
        result, _evidence, state, commands = self._run(
            "malformed-target-output",
            "0,1",
            extra_environment={"FAKE_DOCKER_MALFORMED_OUTPUT_ROLE": "target"},
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(
            state["ue5-spark-ardy"]["Config"]["Image"], self.rollback_image_id
        )
        lifecycle = [
            command[-1]
            for command in commands
            if command and command[0] in {"logs", "stop", "rm"}
        ]
        self.assertTrue(lifecycle)
        self.assertTrue(all(re.fullmatch(r"[0-9a-f]{64}", value) for value in lifecycle))
        self.assertNotIn("not-a-container-id", lifecycle)

    def test_foreign_run_label_is_never_logged_stopped_or_removed(self) -> None:
        result, evidence, state, commands = self._run(
            "foreign-canary-label",
            "0",
            extra_environment={"FAKE_DOCKER_WRONG_LABEL_ROLE": "canary"},
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ue5-spark-ardy-canary", state)
        foreign_id = state["ue5-spark-ardy-canary"]["Id"]
        lifecycle_ids = [
            command[-1]
            for command in commands
            if command and command[0] in {"logs", "stop", "rm"}
        ]
        self.assertNotIn(foreign_id, lifecycle_ids)
        record = self._result_record(evidence)
        self.assertEqual(record["cleanup_status"], "failed")

    def test_rollback_created_with_lost_output_is_still_verified(self) -> None:
        result, evidence, state, _commands = self._run(
            "rollback-output-lost",
            "0,1",
            extra_environment={"FAKE_DOCKER_LOST_OUTPUT_ROLE": "rollback"},
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(set(state), {"ue5-spark-ardy"})
        self.assertEqual(
            state["ue5-spark-ardy"]["Config"]["Image"], self.rollback_image_id
        )
        record = self._result_record(evidence)
        self.assertEqual(record["rollback_status"], "verified")
        self.assertEqual(record["rollback_verified"], "1")

    def test_repeated_signals_cannot_interrupt_exit_rollback(self) -> None:
        evidence = self.logs / "double-signal-rollback"
        rollback_started = self.root / "rollback-started"
        environment = self.environment.copy()
        environment.update(
            {
                "FAKE_VALIDATOR_STATUSES": "0,1",
                "FAKE_DOCKER_PRECREATE_DELAY_ROLE": "rollback",
                "FAKE_DOCKER_DELAY_MARKER": str(rollback_started),
                "FAKE_DOCKER_DELAY_SECONDS": "1.5",
            }
        )
        process = subprocess.Popen(
            ("bash", str(self.script), str(self.models), str(evidence)),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
            start_new_session=True,
        )
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not rollback_started.exists():
            time.sleep(0.02)
        self.assertTrue(rollback_started.exists())
        os.killpg(process.pid, signal.SIGTERM)
        os.killpg(process.pid, signal.SIGINT)
        stdout, stderr = process.communicate(timeout=15)
        self.assertNotEqual(process.returncode, 0, stdout + stderr)
        state = json.loads(self.state_file.read_text(encoding="utf-8"))
        self.assertEqual(set(state), {"ue5-spark-ardy"})
        self.assertEqual(
            state["ue5-spark-ardy"]["Config"]["Image"], self.rollback_image_id
        )
        record = self._result_record(evidence)
        self.assertEqual(record["rollback_status"], "verified")
        self.assertEqual(record["exit_cleanup_signals_masked"], "1")

    def test_inherited_lock_fd_succeeds_while_an_ordinary_claimant_is_rejected(self) -> None:
        import fcntl

        lock_path = Path(f"/run/user/{os.getuid()}/ue5-spark-ardy.activation.lock")
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_APPEND | os.O_RDWR, 0o600)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

            contended_evidence = self.logs / "ordinary-lock-contended"
            contended_environment = self.environment.copy()
            contended_environment["FAKE_VALIDATOR_STATUSES"] = "0,0"
            contended = subprocess.run(
                (
                    "bash",
                    str(self.script),
                    str(self.models),
                    str(contended_evidence),
                ),
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
                env=contended_environment,
            )
            self.assertNotEqual(contended.returncode, 0)
            self.assertIn("another guarded ARDY activation", contended.stderr)
            self.assertFalse(contended_evidence.exists())

            inherited_evidence = self.logs / "inherited-lock-success"
            inherited_environment = self.environment.copy()
            inherited_environment.update(
                {
                    "FAKE_VALIDATOR_STATUSES": "0,0",
                    "ARDY_ACTIVATION_LOCK_FD": str(lock_fd),
                }
            )
            inherited = subprocess.run(
                (
                    "bash",
                    str(self.script),
                    str(self.models),
                    str(inherited_evidence),
                ),
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
                env=inherited_environment,
                pass_fds=(lock_fd,),
            )
            self.assertEqual(inherited.returncode, 0, inherited.stderr)
            record = self._result_record(inherited_evidence)
            self.assertEqual(record["status"], "passed")
            self.assertEqual(record["recovery_mode"], "0")
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)


if __name__ == "__main__":
    unittest.main()
