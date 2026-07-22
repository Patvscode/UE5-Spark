from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
OFFLINE_TEMPLATE = REPO_ROOT / "staging/fab-offline-template/FayFabAcquisition.uproject"
CONTENT_MANIFEST_PATH = REPO_ROOT / "scripts/fab-content-manifest.py"


def load_content_manifest_module():
    spec = importlib.util.spec_from_file_location(
        "fab_content_manifest", CONTENT_MANIFEST_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FabOfflineContractTests(unittest.TestCase):
    def test_offline_descriptor_disables_fab_and_enables_fixed_tools(self) -> None:
        project = json.loads(OFFLINE_TEMPLATE.read_text(encoding="utf-8"))
        self.assertIs(project.get("DisableEnginePluginsByDefault"), True)
        self.assertNotIn("Modules", project)
        self.assertEqual(
            project.get("Plugins"),
            [
                {"Name": "Fab", "Enabled": False, "TargetAllowList": ["Editor"]},
                {
                    "Name": "PythonScriptPlugin",
                    "Enabled": True,
                    "TargetAllowList": ["Editor"],
                },
                {
                    "Name": "EditorScriptingUtilities",
                    "Enabled": True,
                    "TargetAllowList": ["Editor"],
                },
                {
                    "Name": "ChaosCloth",
                    "Enabled": True,
                    "TargetAllowList": ["Editor"],
                },
            ],
        )

    def test_content_manifest_detects_content_changes_and_symlinks(self) -> None:
        module = load_content_manifest_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "FayFabAcquisition"
            content = root / "Content/Sample"
            content.mkdir(parents=True)
            (root / "FayFabAcquisition.uproject").write_text("{}\n", encoding="utf-8")
            asset = content / "SK_Body.uasset"
            asset.write_bytes(b"first")
            manifest = Path(temporary) / "content.json"
            module._write_new_private(manifest, module.snapshot(root))
            module.verify(root, manifest)
            asset.write_bytes(b"changed")
            with self.assertRaises(module.ContentManifestError):
                module.verify(root, manifest)
            asset.write_bytes(b"first")
            link = content / "unsafe.uasset"
            try:
                link.symlink_to(asset)
            except OSError:
                self.skipTest("symlinks are unavailable")
            with self.assertRaises(module.ContentManifestError):
                module.snapshot(root)

    def test_transition_is_backed_up_atomic_and_fail_closed(self) -> None:
        script = REPO_ROOT / "scripts/transition-fex-fab-offline.sh"
        source = script.read_text(encoding="utf-8")
        self.assertTrue(os.access(script, os.X_OK))
        for marker in (
            'flock -n 9',
            'python3 "$non_content_tool" verify',
            'python3 "$content_tool" create',
            'cp -a --reflink=auto "$project_dir/." "$temporary_backup/"',
            'cmp -s "$offline_template" "$project"',
            'install -m 0644 "$offline_template" "$temporary_descriptor"',
            'mv -f "$temporary_descriptor" "$project"',
            'backup="$backup_parent/acquisition-v1"',
            'FULLY_UNCLOTHED": "disabled"',
            'NOAI_BOUNDARY": "deterministic_retarget_only"',
            'systemctl --user is-active ue5-spark-avatar-live.service',
        ):
            self.assertIn(marker, source)
        self.assertNotIn("sudo", source)
        self.assertNotIn("systemctl stop", source)
        self.assertNotIn("systemctl restart", source)
        self.assertNotIn("ln ", source)

    def test_offline_runner_uses_auth_free_state_and_blocks_ip_sockets(self) -> None:
        script = REPO_ROOT / "scripts/run-fex-fab-offline-review.sh"
        source = script.read_text(encoding="utf-8")
        self.assertTrue(os.access(script, os.X_OK))
        for marker in (
            'private_state="$workspace/state/fab-offline"',
            'private_logs="$workspace/logs-private/fab-offline"',
            "RestrictAddressFamilies=AF_UNIX",
            "NoNewPrivileges=yes",
            'unset DISPLAY XAUTHORITY DBUS_SESSION_BUS_ADDRESS',
            'export FAY_FAB_EXPECT_OFFLINE=1',
            'python3 "$content_tool" verify',
            'python3 "$non_content_tool" verify',
            "FAY_FAB_INVENTORY_OFFLINE_PLUGINS=OK",
            "FAY_FAB_INVENTORY_COMPLETE=OK",
            "systemctl --user is-active ue5-spark-avatar-live.service",
        ):
            self.assertIn(marker, source)
        self.assertNotIn('state/fab-acquisition"', source)
        self.assertNotIn("-EnablePlugins=", source)
        self.assertNotIn("-DisablePlugins=", source)
        self.assertNotIn("sudo", source)

    def test_acquisition_review_writes_a_hashed_private_receipt(self) -> None:
        source = (REPO_ROOT / "scripts/run-fex-fab-review.sh").read_text(
            encoding="utf-8"
        )
        for marker in (
            'receipt="$private_logs/casual-girl-inventory.json"',
            '"inventoryScriptSha256"',
            '"logSha256"',
            '"ARKIT_BODY_FOUND_COUNT": "52"',
            '"EPIC_BODY_BONE_NAMES_FOUND": "21"',
            'os.replace(name, output)',
        ):
            self.assertIn(marker, source)


if __name__ == "__main__":
    unittest.main()
