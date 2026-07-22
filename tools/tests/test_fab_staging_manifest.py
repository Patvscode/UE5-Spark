from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts/fab-staging-manifest.py"
SPEC = importlib.util.spec_from_file_location("fab_staging_manifest", SCRIPT)
assert SPEC and SPEC.loader
MANIFEST = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MANIFEST)


class FabStagingManifestTests(unittest.TestCase):
    def make_project(self, root: Path) -> None:
        (root / "Content").mkdir()
        (root / "Config").mkdir()
        (root / "Plugins").mkdir()
        (root / "Stage.uproject").write_text("{}\n", encoding="utf-8")
        (root / "Config/DefaultEngine.ini").write_text("[test]\n", encoding="utf-8")
        (root / "Plugins/ready.txt").write_text("built\n", encoding="utf-8")

    def test_content_changes_are_expected_but_project_changes_fail(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            private = Path(directory_name)
            root = private / "stage"
            root.mkdir()
            self.make_project(root)
            manifest = private / "before.json"
            MANIFEST._write_new_private(manifest, MANIFEST.snapshot(root))
            self.assertEqual(manifest.stat().st_mode & 0o777, 0o600)

            (root / "Content/NewAsset.uasset").write_bytes(b"private")
            MANIFEST.verify(root, manifest)
            (root / "Stage.uproject").write_text('{"changed":true}\n', encoding="utf-8")
            with self.assertRaisesRegex(MANIFEST.StagingManifestError, "changed="):
                MANIFEST.verify(root, manifest)

    def test_added_plugin_binary_and_symlink_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name) / "stage"
            root.mkdir()
            self.make_project(root)
            before = MANIFEST.snapshot(root)
            (root / "Plugins/new.so").write_bytes(b"native")
            self.assertNotEqual(before, MANIFEST.snapshot(root))
            (root / "Plugins/link").symlink_to("new.so")
            with self.assertRaisesRegex(MANIFEST.StagingManifestError, "symlink"):
                MANIFEST.snapshot(root)

    def test_ignored_content_symlinks_fail_closed_without_hashing_assets(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            private = Path(directory_name)
            root = private / "stage"
            root.mkdir()
            self.make_project(root)
            outside = private / "outside"
            outside.mkdir()

            (root / "Content/Asset.uasset").write_bytes(b"licensed")
            before = MANIFEST.snapshot(root)
            (root / "Content/Asset.uasset").write_bytes(b"changed")
            self.assertEqual(before, MANIFEST.snapshot(root))

            (root / "Content/escape").symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(MANIFEST.StagingManifestError, "symlink"):
                MANIFEST.snapshot(root)

    def test_ignored_top_level_directory_cannot_be_replaced_by_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            private = Path(directory_name)
            root = private / "stage"
            root.mkdir()
            self.make_project(root)
            outside = private / "outside"
            outside.mkdir()
            (root / "Content").rmdir()
            (root / "Content").symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(MANIFEST.StagingManifestError, "top-level"):
                MANIFEST.snapshot(root)

    def test_ignored_tree_walk_error_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name) / "stage"
            root.mkdir()
            self.make_project(root)

            def fail_walk(*_args, onerror=None, **_kwargs):
                error = PermissionError("denied")
                error.filename = str(root / "Content/hidden")
                assert onerror is not None
                onerror(error)
                return iter(())

            with mock.patch.object(MANIFEST.os, "walk", side_effect=fail_walk):
                with self.assertRaisesRegex(
                    MANIFEST.StagingManifestError, "could not inspect"
                ):
                    MANIFEST._validate_ignored_trees(root)

    def test_manifest_must_stay_outside_staging_root(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("manifest.is_relative_to(root)", source)
        self.assertIn("manifest must remain outside staging root", source)


if __name__ == "__main__":
    unittest.main()
