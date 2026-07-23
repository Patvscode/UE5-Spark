import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "config_workspace.py"
SPEC = importlib.util.spec_from_file_location("config_workspace", MODULE_PATH)
WORKSPACE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = WORKSPACE
SPEC.loader.exec_module(WORKSPACE)
REPO_ROOT = MODULE_PATH.parents[3]


class ConfigWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "config-workspace"
        self.workspace = WORKSPACE.ConfigWorkspace(
            REPO_ROOT, self.root, project_root=REPO_ROOT
        )

    def tearDown(self):
        self.temporary.cleanup()

    def file(self, snapshot, name):
        return next(item for item in snapshot["files"] if item["name"] == name)

    def test_inventory_has_api_contract_paths_options_and_apply_semantics(self):
        snapshot = self.workspace.snapshot()
        self.assertEqual(snapshot["schemaVersion"], 1)
        self.assertEqual(snapshot["workspacePath"], str(self.root.resolve()))
        self.assertEqual(
            snapshot["backupPath"], str((self.root / "backups").resolve())
        )
        self.assertEqual(
            {directory["id"] for directory in snapshot["directories"]},
            {
                "controller-config",
                "unreal-config",
                "wardrobe-profiles",
                "project-assets",
                "wardrobe-runtime",
                "workspace-backups",
            },
        )
        self.assertTrue(
            next(
                directory for directory in snapshot["directories"]
                if directory["id"] == "wardrobe-profiles"
            )["addable"]
        )
        for item in snapshot["files"]:
            self.assertRegex(item["id"], r"^cfg_[0-9a-f]{24}$")
            self.assertIn(item["applyMode"], {"live", "rebuild"})
            self.assertTrue(item["validation"]["valid"])
            self.assertNotIn("content", item)
        self.assertEqual(
            set(snapshot["options"]["characters"]), {"Ada", "Aoi", "CasualGirl"}
        )
        self.assertIn("wave", snapshot["options"]["motionPresets"])
        self.assertEqual(
            snapshot["options"]["aiControlModes"],
            ["deterministic", "ai_motion", "asset_aware_ai"],
        )
        self.assertIn("casual-girl", {
            item["profileId"]
            for item in snapshot["options"]["wardrobeProfiles"]
        })
        self.assertTrue(any("cannot add an uncooked" in line for line in snapshot["guidance"]))

    def test_read_returns_only_selected_content_and_revision(self):
        inventory = self.workspace.snapshot()
        target = self.file(inventory, "motion-catalog.json")
        selected = self.workspace.snapshot(target["id"])
        self.assertEqual(selected["file"]["id"], target["id"])
        self.assertIn('"catalogId"', selected["file"]["content"])
        self.assertEqual(
            self.workspace.read_file(target["id"]),
            selected["file"],
        )
        self.assertRegex(selected["file"]["revision"], r"^[0-9a-f]{64}$")
        self.assertEqual(
            sum("content" in item for item in selected["files"]),
            1,
        )
        with self.assertRaises(WORKSPACE.ConfigWorkspaceNotFound):
            self.workspace.snapshot("cfg_" + "0" * 24)

    def test_save_validates_backs_up_atomically_and_checks_revision(self):
        inventory = self.workspace.snapshot()
        target = self.file(inventory, "motion-catalog.json")
        opened = self.workspace.snapshot(target["id"])["file"]
        value = json.loads(opened["content"])
        value["items"]["wave"]["label"] = "Friendly wave"
        result = self.workspace.save_file(
            target["id"],
            opened["revision"],
            json.dumps(value, indent=2) + "\n",
        )
        self.assertTrue(result["backup"]["created"])
        backup = Path(result["backup"]["path"])
        self.assertTrue(backup.is_file())
        self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
        self.assertEqual(result["file"]["validation"]["valid"], True)
        self.assertEqual(
            json.loads(result["file"]["content"])["items"]["wave"]["label"],
            "Friendly wave",
        )
        self.assertIn("ready to apply live", result["message"])
        with self.assertRaises(WORKSPACE.ConfigWorkspaceConflict):
            self.workspace.save_file(
                target["id"], opened["revision"], opened["content"]
            )

        invalid = json.loads(result["file"]["content"])
        del invalid["items"]["wave"]
        with self.assertRaises(WORKSPACE.ConfigWorkspaceValidationError):
            self.workspace.save_file(
                target["id"],
                result["file"]["revision"],
                json.dumps(invalid),
            )

    def test_create_and_delete_user_wardrobe_profile_but_not_baseline(self):
        snapshot = self.workspace.snapshot()
        baseline = self.file(snapshot, "CasualGirl.pending.json")
        self.assertTrue(baseline["builtIn"])
        self.assertFalse(baseline["removable"])
        baseline_content = self.workspace.snapshot(baseline["id"])["file"]["content"]
        value = json.loads(baseline_content)
        value["id"] = "casual-girl-alt"
        value["reviewedAssetRoot"] = "/Game/FayFab/CasualGirlAlt"
        created = self.workspace.create_file(
            "wardrobe-profiles",
            "CasualGirlAlt.pending.json",
            json.dumps(value, indent=2) + "\n",
        )
        self.assertFalse(created["backup"]["created"])
        self.assertFalse(created["file"]["builtIn"])
        self.assertTrue(created["file"]["removable"])
        self.assertEqual(created["file"]["applyMode"], "rebuild")

        with self.assertRaises(WORKSPACE.ConfigWorkspaceConflict):
            self.workspace.create_file(
                "wardrobe-profiles",
                "Another.pending.json",
                json.dumps(value),
            )
        with self.assertRaises(WORKSPACE.ConfigWorkspaceSecurityError):
            self.workspace.delete_file(baseline["id"], baseline["revision"])

        deleted = self.workspace.delete_file(
            created["file"]["id"], created["file"]["revision"]
        )
        self.assertTrue(deleted["backup"]["created"])
        self.assertTrue(Path(deleted["backup"]["path"]).is_file())
        self.assertFalse((self.root / "wardrobe/CasualGirlAlt.pending.json").exists())
        self.assertNotIn(
            created["file"]["id"],
            {item["id"] for item in self.workspace.snapshot()["files"]},
        )

    def test_path_traversal_symlinks_and_oversize_content_fail_closed(self):
        baseline = self.file(
            self.workspace.snapshot(), "CasualGirl.pending.json"
        )
        content = self.workspace.snapshot(baseline["id"])["file"]["content"]
        for name in ("../escape.json", ".hidden.json", "bad/name.json"):
            with self.assertRaises(WORKSPACE.ConfigWorkspaceSecurityError):
                self.workspace.create_file("wardrobe-profiles", name, content)
        with self.assertRaises(WORKSPACE.ConfigWorkspaceValidationError):
            self.workspace.create_file(
                "wardrobe-profiles",
                "Oversize.json",
                "x" * (WORKSPACE.MAX_JSON_BYTES + 1),
            )

        outside = Path(self.temporary.name) / "outside.json"
        outside.write_text(content, encoding="utf-8")
        link = self.root / "wardrobe/Evil.json"
        os.symlink(outside, link)
        with self.assertRaises(WORKSPACE.ConfigWorkspaceSecurityError):
            self.workspace.snapshot()

    def test_duplicate_json_keys_and_invalid_ini_are_rejected_without_write(self):
        motion = self.file(self.workspace.snapshot(), "motion-catalog.json")
        opened = self.workspace.snapshot(motion["id"])["file"]
        duplicate = opened["content"].replace(
            '"schemaVersion": 1,',
            '"schemaVersion": 1,\\n  "schemaVersion": 1,',
            1,
        )
        with self.assertRaises(WORKSPACE.ConfigWorkspaceValidationError):
            self.workspace.save_file(motion["id"], opened["revision"], duplicate)
        self.assertEqual(
            self.workspace.snapshot(motion["id"])["file"]["revision"],
            opened["revision"],
        )

        profiles = self.file(self.workspace.snapshot(), "DefaultGame.ini")
        opened_profiles = self.workspace.snapshot(profiles["id"])["file"]
        invalid = opened_profiles["content"].replace(
            "DefaultCharacter=Ada", "DefaultCharacter=Unknown"
        )
        with self.assertRaises(WORKSPACE.ConfigWorkspaceValidationError):
            self.workspace.save_file(
                profiles["id"], opened_profiles["revision"], invalid
            )

    def test_post_action_dispatch_is_exact_and_returns_updated_workspace(self):
        target = self.file(self.workspace.snapshot(), "motion-catalog.json")
        opened = self.workspace.snapshot(target["id"])["file"]
        result = self.workspace.apply_action({
            "action": "save",
            "fileId": opened["id"],
            "revision": opened["revision"],
            "content": opened["content"],
        })
        self.assertEqual(result["file"]["id"], opened["id"])
        self.assertEqual(result["workspace"]["schemaVersion"], 1)
        for payload in (
            {"action": "unknown"},
            {
                "action": "save",
                "fileId": opened["id"],
                "revision": result["file"]["revision"],
                "content": opened["content"],
                "path": "/tmp/escape",
            },
            {"action": "delete", "fileId": opened["id"]},
        ):
            with self.assertRaises(WORKSPACE.ConfigWorkspaceValidationError):
                self.workspace.apply_action(payload)


if __name__ == "__main__":
    unittest.main()
