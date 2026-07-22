from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "cleanup-hf-ardy-authorization.py"
SPEC = importlib.util.spec_from_file_location("cleanup_hf_ardy_authorization", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class CleanupHfArdyAuthorizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="hf-ardy-cleanup-test-")
        self.root = Path(self.temporary.name).resolve()
        self.uid = os.getuid()
        self.key = b"k" * 32

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _make_auth(self, parent: Path | None = None) -> Path:
        parent = parent or self.root
        auth = parent / "hf-ardy-device"
        auth.mkdir(mode=0o700)
        temporary_token = b"hf" + b"_" + b"temporary_authorization_123456789"
        stored_token = b"hf" + b"_" + b"stored_authorization_987654321"
        values = {
            "token": temporary_token + b"\n",
            "stored_tokens": b"temporary = " + stored_token + b"\n",
            ".check_for_update_done": b"",
            ".agent_harnesses.json": b'{"tool":"huggingface"}\n',
        }
        for name, payload in values.items():
            destination = auth / name
            destination.write_bytes(payload)
            destination.chmod(MODULE.AUTH_INVENTORY[name])
        auth.chmod(0o700)
        return auth

    def test_exact_inventory_mismatch_fails_closed(self) -> None:
        auth = self._make_auth()
        (auth / "unexpected").write_text("not allowed", encoding="utf-8")
        (auth / "unexpected").chmod(0o600)
        with self.assertRaisesRegex(MODULE.CleanupError, "inventory is not exact"):
            MODULE.validate_auth_inventory(auth, self.uid, self.key)

    def test_symlink_root_and_entry_are_rejected(self) -> None:
        auth = self._make_auth()
        linked_root = self.root / "linked-auth"
        linked_root.symlink_to(auth, target_is_directory=True)
        with self.assertRaisesRegex(MODULE.CleanupError, "non-symlink directory"):
            MODULE.validate_auth_inventory(linked_root, self.uid, self.key)

        sidecar = auth / ".check_for_update_done"
        sidecar.unlink()
        sidecar.symlink_to(auth / "token")
        with self.assertRaisesRegex(MODULE.CleanupError, "missing or unsafe"):
            MODULE.validate_auth_inventory(auth, self.uid, self.key)

    def test_any_container_mount_overlap_is_rejected(self) -> None:
        auth = self.root / "workspace" / "secrets-private" / "hf-ardy-device"
        records = [
            {
                "Id": "1" * 64,
                "Mounts": [
                    {
                        "Type": "bind",
                        "Source": str(auth.parent.parent),
                        "Destination": "/workspace",
                    }
                ],
            }
        ]
        with self.assertRaisesRegex(MODULE.CleanupError, "mount overlaps"):
            MODULE.ensure_no_container_mount_overlap(records, (auth,))

        MODULE.ensure_no_container_mount_overlap(
            [{"Id": "2" * 64, "Mounts": [{"Source": "/unrelated"}]}],
            (auth,),
        )

    def test_same_default_and_temporary_token_is_rejected_without_output(self) -> None:
        secret = b"hf" + b"_" + b"same_credential_material_123456789"
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            with self.assertRaisesRegex(MODULE.CleanupError, "not distinct") as raised:
                MODULE.compare_token_fingerprints(
                    {"token": secret, "stored_tokens": b"other"}, secret, self.key
                )
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")
        self.assertNotIn(secret.decode("ascii"), str(raised.exception))
        self.assertNotIn(MODULE._hmac_hex(self.key, secret), str(raised.exception))

    def test_canary_failure_transaction_restores_exact_authorization(self) -> None:
        source = self._make_auth()
        destination = self.root / (".hf-ardy-device.quarantine." + "a" * 24)
        move = MODULE.QuarantineMove(
            source=source,
            destination=destination,
            expected_identity=MODULE._path_identity(source, "test authorization"),
        )

        def failed_canary() -> None:
            self.assertFalse(source.exists())
            self.assertTrue(destination.is_dir())
            raise MODULE.CleanupError("simulated canary failure")

        with self.assertRaisesRegex(MODULE.CleanupError, "simulated canary failure"):
            MODULE.run_quarantine_transaction(move, failed_canary)
        self.assertTrue(source.is_dir())
        self.assertFalse(destination.exists())
        self.assertFalse(move.moved)

    def test_production_identity_must_be_byte_for_byte_stable(self) -> None:
        expected = {
            "container_id": "1" * 64,
            "pid": 321,
            "started_at": "2026-07-21T00:00:00Z",
            "image_id": "sha256:" + "2" * 64,
            "configured_image": MODULE.TARGET_IMAGE,
        }
        MODULE.assert_production_identity_unchanged(expected, dict(expected))
        changed = dict(expected)
        changed["pid"] = 322
        with self.assertRaisesRegex(MODULE.CleanupError, "identity changed"):
            MODULE.assert_production_identity_unchanged(expected, changed)

    def test_private_state_is_atomic_hmac_sealed_and_contains_no_raw_token(self) -> None:
        evidence = self.root / "evidence"
        evidence.mkdir(mode=0o700)
        evidence.chmod(0o700)
        key_file = evidence / "fingerprint.key"
        key_file.write_bytes(self.key)
        key_file.chmod(0o600)
        state = {"schema_version": MODULE.SCHEMA_VERSION, "phase": "prepared"}
        MODULE._write_signed_state(evidence, state, self.key)
        loaded, loaded_key = MODULE._read_signed_state(evidence, self.uid)
        self.assertEqual(loaded, state)
        self.assertEqual(loaded_key, self.key)
        state_text = (evidence / "state.json").read_text(encoding="utf-8")
        token_prefix = "hf" + "_" + "temporary_authorization"
        self.assertNotIn(token_prefix, state_text)

        (evidence / "state.json").write_text(
            state_text.replace("prepared", "tampered"), encoding="utf-8"
        )
        (evidence / "state.json").chmod(0o600)
        with self.assertRaisesRegex(MODULE.CleanupError, "signature is invalid"):
            MODULE._read_signed_state(evidence, self.uid)

    def test_finalize_deletes_only_four_allowlisted_files_and_empty_auth_dir(self) -> None:
        secrets_parent = self.root / "secrets-private"
        models_parent = self.root / "models-private"
        secrets_parent.mkdir()
        models_parent.mkdir()
        protected_cache = models_parent / MODULE.ENCODER_CACHE_NAME
        protected_cache.mkdir()
        protected_marker = protected_cache / "keep-me"
        protected_marker.write_text("preserved", encoding="utf-8")
        quarantine = self._make_auth(secrets_parent)
        quarantine_destination = secrets_parent / (
            ".hf-ardy-device.quarantine." + "b" * 24
        )
        quarantine.rename(quarantine_destination)
        snapshot = MODULE.validate_auth_inventory(quarantine_destination, self.uid, self.key)
        record = {name: value for name, value in snapshot.items() if name != "secret_payloads"}

        MODULE.delete_exact_authorization_directory(
            quarantine_destination, record, self.uid, self.key
        )

        self.assertFalse(quarantine_destination.exists())
        self.assertEqual(protected_marker.read_text(encoding="utf-8"), "preserved")

    def test_source_has_no_broad_or_implicit_destructive_primitive(self) -> None:
        source = SCRIPT_PATH.read_text(encoding="utf-8")
        banned = (
            "rm -rf",
            "shutil.rmtree",
            "os.removedirs",
            "shell=True",
            "docker system prune",
            "docker image rm",
            "docker rm --force",
            "docker restart",
            "docker kill",
            "hf auth logout",
            "huggingface-cli logout",
            "find -delete",
        )
        for marker in banned:
            self.assertNotIn(marker, source)
        self.assertIn("os.unlink(name, dir_fd=directory_descriptor)", source)
        self.assertIn("os.rmdir(quarantine.name, dir_fd=parent_descriptor)", source)
        self.assertNotIn("os.rename(paths.encoder_cache", source)
        self.assertNotIn("os.unlink(paths.encoder_cache", source)

    def test_fixed_canary_is_immutable_isolated_and_validated_for_30_batches(self) -> None:
        source = SCRIPT_PATH.read_text(encoding="utf-8")
        for marker in (
            'CANARY_CONTAINER = "ue5-spark-ardy-auth-cleanup-canary"',
            "CANARY_PORT = 18777",
            "VALIDATION_BATCHES = 30",
            '"--read-only"',
            '"--cap-drop"',
            '"no-new-privileges:true"',
            'f"type=bind,src={models_root},dst=/models,readonly"',
            "image_id,",
            '_stop_remove_exact_canary(runner, canary_container_id)',
        ):
            self.assertIn(marker, source)
        self.assertNotIn('"--rm"', source)

    def test_production_and_cleanup_canary_have_distinct_auto_remove_contracts(self) -> None:
        image_id = "sha256:" + "2" * 64
        models_root = self.root / "models-private" / "ardy"

        def record(name: str, port: int, auto_remove: bool) -> dict[str, object]:
            return {
                "Id": "1" * 64,
                "Name": f"/{name}",
                "Image": image_id,
                "RestartCount": 0,
                "State": {
                    "Running": True,
                    "Dead": False,
                    "OOMKilled": False,
                    "Error": "",
                    "Pid": 321,
                    "StartedAt": "2026-07-21T00:00:00Z",
                },
                "Config": {
                    "Image": image_id,
                    "User": f"{self.uid}:{os.getgid()}",
                    "Cmd": [
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(port),
                        "--provider",
                        "ardy",
                        "--models-root",
                        "/models",
                    ],
                    "Env": ["HF_HOME=/tmp/huggingface"],
                },
                "HostConfig": {
                    "AutoRemove": auto_remove,
                    "NetworkMode": "host",
                    "ReadonlyRootfs": True,
                    "CapDrop": ["ALL"],
                    "SecurityOpt": ["no-new-privileges:true"],
                    "PidsLimit": 512,
                    "ShmSize": 4 * 1024**3,
                    "Tmpfs": {"/tmp": "rw,noexec,nosuid,size=1g"},
                    "DeviceRequests": [{"Capabilities": [["gpu"]]}],
                },
                "Mounts": [
                    {
                        "Type": "bind",
                        "Source": str(models_root),
                        "Destination": "/models",
                        "RW": False,
                    }
                ],
            }

        MODULE.validate_real_ardy_container(
            record(MODULE.PRODUCTION_CONTAINER, MODULE.PRODUCTION_PORT, True),
            expected_name=MODULE.PRODUCTION_CONTAINER,
            expected_image_id=image_id,
            expected_port=MODULE.PRODUCTION_PORT,
            expected_auto_remove=True,
            models_root=models_root,
            uid=self.uid,
            gid=os.getgid(),
        )
        MODULE.validate_real_ardy_container(
            record(MODULE.CANARY_CONTAINER, MODULE.CANARY_PORT, False),
            expected_name=MODULE.CANARY_CONTAINER,
            expected_image_id=image_id,
            expected_port=MODULE.CANARY_PORT,
            expected_auto_remove=False,
            models_root=models_root,
            uid=self.uid,
            gid=os.getgid(),
        )
        with self.assertRaisesRegex(MODULE.CleanupError, "sealed real-provider contract"):
            MODULE.validate_real_ardy_container(
                record(MODULE.PRODUCTION_CONTAINER, MODULE.PRODUCTION_PORT, True),
                expected_name=MODULE.PRODUCTION_CONTAINER,
                expected_image_id=image_id,
                expected_port=MODULE.PRODUCTION_PORT,
                expected_auto_remove=False,
                models_root=models_root,
                uid=self.uid,
                gid=os.getgid(),
            )

    def test_token_consumers_share_the_fixed_cleanup_lock(self) -> None:
        for relative in (
            "scripts/cache-ardy-embeddings.sh",
            "scripts/download-ardy-checkpoint.sh",
        ):
            source = (REPO_ROOT / relative).read_text(encoding="utf-8")
            self.assertIn("ue5-spark-hf-authorization-cleanup.lock", source)
            self.assertIn("flock -n 8", source)
            self.assertIn("readlink -f /proc/self/fd/8", source)

    def test_cli_has_strict_arity_before_platform_gate(self) -> None:
        result = subprocess.run(
            (sys.executable, str(SCRIPT_PATH)),
            cwd=REPO_ROOT,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(result.returncode, 64)
        self.assertIn("Usage:", result.stderr)


if __name__ == "__main__":
    unittest.main()
