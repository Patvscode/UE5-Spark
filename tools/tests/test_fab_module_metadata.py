from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts/fab-module-metadata.py"
SPEC = importlib.util.spec_from_file_location("fab_module_metadata", SCRIPT)
assert SPEC and SPEC.loader
METADATA = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(METADATA)


class FabModuleMetadataTests(unittest.TestCase):
    def make_inputs(self, root: Path) -> tuple[Path, Path, Path, Path]:
        plugin = root / "Engine/Plugins/Fab/Binaries/Linux"
        plugin.mkdir(parents=True)
        binary = plugin / "libUnrealEditor-Fab.so"
        binary.write_bytes(b"elf")
        manifest = plugin / "UnrealEditor.modules"

        version = root / "Engine/Binaries/Linux/UnrealEditor.version"
        version.parent.mkdir(parents=True)
        version.write_text(json.dumps({"BuildId": "editor-build-id"}), encoding="utf-8")

        source = root / "EngineMetadata.json"
        source.write_text(
            json.dumps(
                {
                    "VersionFile": str(version),
                    "Version": {"BuildId": None, "MajorVersion": 5, "MinorVersion": 8},
                    "FileToManifest": {
                        str(manifest): {
                            "BuildId": "",
                            "ModuleNameToFileName": {
                                "Fab": "libUnrealEditor-Fab.so"
                            },
                            "LibraryDependencies": {},
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        return source, manifest, binary, version

    def test_build_id_is_pinned_even_when_existing_manifest_is_stale(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            source, manifest, binary, version = self.make_inputs(root)
            manifest.write_text(
                json.dumps(
                    {
                        "BuildId": "editor-build-id",
                        "Modules": {"Fab": binary.name},
                    }
                ),
                encoding="utf-8",
            )
            binary.write_bytes(b"newer rebuilt elf")

            reduced = METADATA.build_reduced_metadata(
                source, manifest, binary, version
            )
            self.assertIsNone(reduced["VersionFile"])
            self.assertEqual(reduced["Version"]["BuildId"], "editor-build-id")
            reduced_manifest = next(iter(reduced["FileToManifest"].values()))
            self.assertEqual(
                reduced_manifest["ModuleNameToFileName"],
                {"Fab": binary.name},
            )

    def test_unexpected_module_contract_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            source, manifest, binary, version = self.make_inputs(root)
            payload = json.loads(source.read_text(encoding="utf-8"))
            payload["FileToManifest"][str(manifest)]["ModuleNameToFileName"][
                "Unexpected"
            ] = "bad.so"
            source.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(
                METADATA.FabMetadataError, "unexpected Fab manifest"
            ):
                METADATA.build_reduced_metadata(source, manifest, binary, version)

    def test_private_output_is_exclusive_and_mode_0600(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            output = Path(directory_name) / "reduced.json"
            METADATA.write_new_private(output, {"ok": True})
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            with self.assertRaisesRegex(METADATA.FabMetadataError, "already exists"):
                METADATA.write_new_private(output, {"ok": False})


if __name__ == "__main__":
    unittest.main()
