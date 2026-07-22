from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest


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

    def test_manifest_must_stay_outside_staging_root(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("manifest.is_relative_to(root)", source)
        self.assertIn("manifest must remain outside staging root", source)


if __name__ == "__main__":
    unittest.main()
