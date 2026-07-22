from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
TRANSITION_SCRIPT = REPO_ROOT / "scripts/transition-fex-fab-offline.sh"
VERIFIER_PATH = REPO_ROOT / "scripts/verify-fab-offline-transition.py"
NON_CONTENT_TOOL = REPO_ROOT / "scripts/fab-staging-manifest.py"
CONTENT_TOOL = REPO_ROOT / "scripts/fab-content-manifest.py"
ACQUISITION_TEMPLATE = (
    REPO_ROOT / "staging/fab-acquisition-template/FayFabAcquisition.uproject"
)
OFFLINE_TEMPLATE = REPO_ROOT / "staging/fab-offline-template/FayFabAcquisition.uproject"
INVENTORY_SCRIPT = REPO_ROOT / "scripts/inspect-fab-casual-girl.py"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_private_json(path: Path, value: dict[str, object]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    path.chmod(0o600)


def load_verifier():
    spec = importlib.util.spec_from_file_location("test_fab_transition_verifier", VERIFIER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FabOfflineTransitionVerifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name).resolve() / "workspace"
        self.workspace.mkdir(mode=0o700)
        self.engine = self.workspace / "engine/UnrealEngine"
        self.engine.mkdir(parents=True)
        self.project_dir = (
            self.workspace / "fab-acquisition-staging/FayFabAcquisition"
        )
        (self.project_dir / "Content/Sample").mkdir(parents=True)
        self.project = self.project_dir / "FayFabAcquisition.uproject"
        shutil.copyfile(ACQUISITION_TEMPLATE, self.project)
        self.project.chmod(0o644)
        (self.project_dir / "Content/Sample/SK_Body.uasset").write_bytes(
            b"fixed-private-content"
        )

        self.private_logs = self.workspace / "logs-private/fab-acquisition"
        (self.workspace / "logs-private").mkdir(mode=0o700)
        self.private_logs.mkdir(mode=0o700)
        phase_lock_root = self.workspace / "state/fab-phase"
        (self.workspace / "state").mkdir(mode=0o700)
        phase_lock_root.mkdir(mode=0o700)
        self.phase_lock = phase_lock_root / "operation.lock"
        self.phase_lock.write_bytes(b"")
        self.phase_lock.chmod(0o600)

        self.acquisition_manifest = self.private_logs / "before-import.json"
        self.content_manifest = (
            self.private_logs / "casual-girl-content-before-migration.json"
        )
        subprocess.run(
            [
                sys.executable,
                str(NON_CONTENT_TOOL),
                "create",
                str(self.project_dir),
                str(self.acquisition_manifest),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [
                sys.executable,
                str(CONTENT_TOOL),
                "create",
                str(self.project_dir),
                str(self.content_manifest),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        self.review_log = self.private_logs / "review-session.A1b2C3.log"
        self.review_log.write_text("fixed inventory evidence\n", encoding="utf-8")
        self.review_log.chmod(0o600)
        content_value = json.loads(self.content_manifest.read_text(encoding="utf-8"))
        self.review_receipt = self.private_logs / "casual-girl-inventory.json"
        write_private_json(
            self.review_receipt,
            {
                "schema": 2,
                "status": "passed",
                "inventoryScriptSha256": sha256(INVENTORY_SCRIPT),
                "inventoryLogPath": str(self.review_log),
                "logSha256": sha256(self.review_log),
                "contentManifestPath": str(self.content_manifest),
                "contentManifestSha256": sha256(self.content_manifest),
                "contentRootDigestSha256": content_value["rootDigestSha256"],
                "identifierEvidence": {
                    "method": "raw_uasset_ascii_identifier_presence",
                    "scope": "identifier_presence_only",
                    "doesNotProve": [
                        "morph_target_attachment",
                        "bone_hierarchy",
                        "deformation_quality",
                        "retarget_compatibility",
                    ],
                },
                "markers": {
                    "MESHES_ASSET_COUNT": "19",
                    "MAT_ASSET_COUNT": "31",
                    "TEX_ASSET_COUNT": "97",
                    "EXPECTED_PRODUCT_ASSETS": "OK",
                    "ARKIT_EXPECTED_COUNT": "52",
                    "ARKIT_BODY_FOUND_COUNT": "52",
                    "ARKIT_COMPLETE_FOUND_COUNT": "52",
                    "ARKIT_BODY_MISSING": "none",
                    "ARKIT_COMPLETE_MISSING": "none",
                    "EPIC_BODY_BONE_NAMES_EXPECTED": "21",
                    "EPIC_BODY_BONE_NAMES_FOUND": "21",
                    "EPIC_BODY_BONE_NAMES_MISSING": "none",
                    "FULLY_UNCLOTHED": "disabled",
                    "COMPLETE": "OK",
                },
            },
        )
        self.verifier = load_verifier()
        self.layout = self.verifier.resolve_layout(
            self.workspace,
            self.engine,
            self.project,
            self.acquisition_manifest,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def seal_offline_transition(self) -> None:
        backups_root = self.workspace / "backups-private"
        backup_parent = backups_root / "fab-casual-girl"
        backup_generation = backup_parent / "acquisition-v1"
        backups_root.mkdir(mode=0o700)
        backup_parent.mkdir(mode=0o700)
        backup_generation.mkdir(mode=0o700)
        shutil.copytree(
            self.project_dir,
            backup_generation / "FayFabAcquisition",
        )
        shutil.copyfile(OFFLINE_TEMPLATE, self.project)
        self.project.chmod(0o644)
        subprocess.run(
            [
                sys.executable,
                str(NON_CONTENT_TOOL),
                "create",
                str(self.project_dir),
                str(self.layout.offline_manifest),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        write_private_json(
            self.layout.transition_receipt,
            self.verifier.expected_transition_payload(self.layout),
        )

    def test_exact_review_and_complete_transition_verify(self) -> None:
        self.verifier.verify_review(self.layout)
        review_cli = subprocess.run(
            [
                sys.executable,
                str(VERIFIER_PATH),
                "--workspace",
                str(self.workspace),
                "--engine",
                str(self.engine),
                "--project",
                str(self.project),
                "--acquisition-manifest",
                str(self.acquisition_manifest),
                "--review-only",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(review_cli.returncode, 0, review_cli.stderr)
        self.seal_offline_transition()
        self.verifier.verify_transition(self.layout)
        transition_cli = subprocess.run(
            [
                sys.executable,
                str(VERIFIER_PATH),
                "--workspace",
                str(self.workspace),
                "--engine",
                str(self.engine),
                "--project",
                str(self.project),
                "--acquisition-manifest",
                str(self.acquisition_manifest),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(transition_cli.returncode, 0, transition_cli.stderr)
        payload = json.loads(self.layout.transition_receipt.read_text(encoding="utf-8"))
        self.assertNotIn("licenseReviewPath", payload)
        self.assertNotIn("licenseReviewSha256", payload)

    def test_review_receipt_rejects_extra_keys_and_stale_content(self) -> None:
        receipt = json.loads(self.review_receipt.read_text(encoding="utf-8"))
        receipt["unexpected"] = True
        write_private_json(self.review_receipt, receipt)
        with self.assertRaises(self.verifier.TransitionVerificationError):
            self.verifier.verify_review(self.layout)

        receipt.pop("unexpected")
        write_private_json(self.review_receipt, receipt)
        (self.project_dir / "Content/Sample/SK_Body.uasset").write_bytes(b"changed")
        with self.assertRaises(self.verifier.TransitionVerificationError):
            self.verifier.verify_review(self.layout)

    def test_transition_rejects_corrupt_reusable_recovery_copy(self) -> None:
        self.seal_offline_transition()
        recovery_descriptor = (
            self.layout.recovery_project / "FayFabAcquisition.uproject"
        )
        recovery_descriptor.write_text("{}\n", encoding="utf-8")
        with self.assertRaises(self.verifier.TransitionVerificationError):
            self.verifier.verify_transition(self.layout)

    def test_descriptor_temp_recovery_is_exact_and_fail_closed(self) -> None:
        residue = self.project_dir / ".FayFabAcquisition.uproject.deadbeef"
        residue.write_bytes(OFFLINE_TEMPLATE.read_bytes())
        residue.chmod(0o644)
        self.assertEqual(self.verifier.recover_descriptor_temps(self.layout), 1)
        self.assertFalse(residue.exists())

        residue.write_bytes(b"not-a-reviewed-descriptor")
        residue.chmod(0o600)
        with self.assertRaises(self.verifier.TransitionVerificationError):
            self.verifier.recover_descriptor_temps(self.layout)
        self.assertTrue(residue.exists())

    def test_transition_receipt_is_exact(self) -> None:
        self.seal_offline_transition()
        transition_value = json.loads(
            self.layout.transition_receipt.read_text(encoding="utf-8")
        )
        transition_value["unexpected"] = "not allowed"
        write_private_json(self.layout.transition_receipt, transition_value)
        with self.assertRaises(self.verifier.TransitionVerificationError):
            self.verifier.verify_transition(self.layout)

    def test_transition_rejects_symlinked_private_receipt(self) -> None:
        self.seal_offline_transition()
        target = self.private_logs / "not-the-transition.json"
        shutil.copyfile(self.layout.transition_receipt, target)
        target.chmod(0o600)
        self.layout.transition_receipt.unlink()
        try:
            self.layout.transition_receipt.symlink_to(target)
        except OSError:
            self.skipTest("symlinks are unavailable")
        with self.assertRaises(self.verifier.TransitionVerificationError):
            self.verifier.verify_transition(self.layout)

    def test_transition_script_closes_signal_and_lock_windows(self) -> None:
        source = TRANSITION_SCRIPT.read_text(encoding="utf-8")
        verifier_source = VERIFIER_PATH.read_text(encoding="utf-8")
        self.assertTrue(os.access(TRANSITION_SCRIPT, os.X_OK))
        lock = source.index('fab_phase_lock_acquire "$workspace"')
        trap = source.index("trap cleanup EXIT")
        process_check = source.index('if ps -u "$(id -u)"')
        rollback_obligation = source.index("switched=1")
        descriptor_swap = source.index(
            'atomic_replace_descriptor "$offline_template" "$project"'
        )
        self.assertLess(lock, trap)
        self.assertLess(trap, process_check)
        self.assertLess(rollback_obligation, descriptor_swap)
        self.assertIn("trap '' HUP INT TERM", source)
        for marker in (
            'expected_acquisition_manifest="$private_logs/before-import.json"',
            'backup="$backup_generation/FayFabAcquisition"',
            'host_python=/usr/bin/python3',
            '"$host_python" "$transition_verifier" "${verifier_args[@]}" --review-only',
            '"$host_python" "$transition_verifier" "${verifier_args[@]}"',
            'sync -f "$temporary_project"',
            'sync -f "$backup_generation"',
            'recover_descriptor_temps',
            'fsync_directory "$backup_parent"',
            'Recovered an interrupted Fab transition to the sealed acquisition phase.',
            'if [[ ! -e $transition_receipt && ! -L $transition_receipt ]]',
        ):
            self.assertIn(marker, source)
        self.assertLess(process_check, source.index("recover_descriptor_temps", process_check))
        recovery_branch = source.index(
            'if [[ ! -e $transition_receipt && ! -L $transition_receipt ]]'
        )
        self.assertLess(
            source.index('verify_recovery_copy', recovery_branch),
            source.index(
                'atomic_replace_descriptor "$acquisition_template" "$project"',
                recovery_branch,
            ),
        )
        self.assertLess(
            source.index('remove_transition_evidence', recovery_branch),
            source.index(
                'atomic_replace_descriptor "$acquisition_template" "$project"',
                recovery_branch,
            ),
        )
        self.assertGreaterEqual(
            source.count('"$host_python" "$transition_verifier" "${verifier_args[@]}"'),
            2,
        )
        for forbidden in (
            "casual-girl-license-review",
            "license_review",
            "licenseReview",
            "NOAI_BOUNDARY",
            "AI_CONTROL_MODE_SELECTION",
        ):
            self.assertNotIn(forbidden, source)
            self.assertNotIn(forbidden, verifier_source)


if __name__ == "__main__":
    unittest.main()
