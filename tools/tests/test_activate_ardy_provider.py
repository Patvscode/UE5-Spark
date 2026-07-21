from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "activate-ardy-provider.sh"


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
            "readonly TARGET_IMAGE='ue5-spark-ardy:0.2.0'",
            "readonly ROLLBACK_IMAGE='ue5-spark-ardy:0.1.0'",
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
        stop_targets = re.findall(r'docker stop --time 20 "\$([A-Za-z0-9_]+)"', self.source)
        self.assertEqual(
            sorted(stop_targets),
            sorted(["canary_container_id", "target_container_id", "old_container_id"]),
        )
        self.assertEqual(
            re.findall(r'docker rm "\$([A-Za-z0-9_]+)"', self.source),
            ["canary_container_id"],
        )
        self.assertNotIn("fay", self.source.lower())
        self.assertIn('[[ $container_id =~ ^[0-9a-f]{64}$', self.source)

    def test_canary_passes_before_production_stop_and_rollback_is_armed(self) -> None:
        canary_validation = self.source.index(
            '"$validator" --port "$CANARY_PORT" --batches 30'
        )
        production_reverified = self.source.index(
            "capture_verified_container production_reverified"
        )
        rollback_arm = self.source.index("rollback_armed=1", production_reverified)
        production_stop = self.source.index(
            'docker stop --time 20 "$old_container_id"', rollback_arm
        )
        target_launch = self.source.index(
            'target_container_id=$(launch_container "$PRODUCTION_CONTAINER"',
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
            'launch_container "$CANARY_CONTAINER" "$target_image_id"',
            'launch_container "$PRODUCTION_CONTAINER" "$target_image_id"',
            'launch_container "$PRODUCTION_CONTAINER" "$rollback_image_id"',
            'current_runtime_image_id=$(docker inspect',
            'current_runtime_image_id == "$target_image_id"',
            'current_runtime_image_id == "$rollback_image_id"',
        ):
            self.assertIn(marker, self.source)
        self.assertNotIn(
            'launch_container "$CANARY_CONTAINER" "$TARGET_IMAGE"',
            self.source,
        )

    def test_absent_service_recovery_requires_an_unused_fixed_port(self) -> None:
        for marker in (
            "recovery_mode=1",
            'loopback_port_is_unused "$PRODUCTION_PORT"',
            "production ARDY is absent but its fixed loopback port is unexpectedly owned",
            "If the real canary or relaunch fails, restore the sealed mock endpoint.",
            "the production container name was claimed during recovery qualification",
            "the production loopback port was claimed during recovery qualification",
            '"recovery_mode=$recovery_mode"',
        ):
            self.assertIn(marker, self.source)
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
        ):
            self.assertIn(marker, self.source)
        self.assertNotIn('lock_file="$private_root/.ardy-activation.lock"', self.source)

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
            'type=bind,src=$models_root,dst=/models,readonly',
            '"$validator" --port "$CANARY_PORT" --batches 30',
            '"$validator" --port "$PRODUCTION_PORT" --batches 30',
            're.search(r"(?:TOKEN|PASSWORD|SECRET|CREDENTIAL|API_KEY)$"',
        ):
            self.assertIn(marker, self.source)


if __name__ == "__main__":
    unittest.main()
