from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT_PATH = REPO_ROOT / "scripts" / "run-avatar-renderer-supervisor.py"
SPEC = importlib.util.spec_from_file_location("renderer_supervisor", SCRIPT_PATH)
SUPERVISOR = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = SUPERVISOR
SPEC.loader.exec_module(SUPERVISOR)


class RendererSupervisorTests(unittest.TestCase):
    def test_package_manifest_maps_only_reviewed_profiles_and_framing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "FayAvatarRuntime"
            executable = root / "Binaries/LinuxArm64/FayAvatarRuntime"
            executable.parent.mkdir(parents=True)
            executable.write_bytes(b"runtime")
            executable.chmod(0o700)
            launcher = root / "FayAvatarRuntime-Arm64.sh"
            launcher.write_text("#!/bin/sh\n", encoding="utf-8")
            launcher.chmod(0o700)
            (root / ".ue5-spark-characters.json").write_text(json.dumps({
                "schema": 2,
                "profileConfigSha256": "0" * 64,
                "defaultCameraFraming": "Portrait",
                "characters": [
                    {"id": "Ada", "cameraFramings": ["Portrait", "FullBody"]},
                    {"id": "Aoi", "cameraFramings": ["Portrait", "FullBody"]},
                    {"id": "CasualGirl", "cameraFramings": ["Portrait", "FullBody"]},
                    {"id": "Unreviewed", "cameraFramings": ["FullBody"]},
                ],
            }), encoding="utf-8")
            package = SUPERVISOR.load_package(executable, "v30")
            self.assertEqual(
                package.profiles,
                {"ada": "Ada", "aoi": "Aoi", "casual-girl": "CasualGirl"},
            )
            self.assertEqual(package.framings["casual-girl"], "FullBody")
            self.assertEqual(package.generation, "v30")
            self.assertEqual(package.launcher, launcher.resolve())

    def test_supervisor_launches_through_the_guarded_stack_launcher(self):
        source = SCRIPT_PATH.read_text(encoding="utf-8")
        self.assertIn("str(self.stack_launcher), str(package.launcher)", source)
        self.assertIn('f"-FayWardrobeCommandRoot={self.live_root}"', source)
        self.assertIn('default=Path(__file__).with_name("run-spark-digital-human.sh")', source)

    def test_request_reader_rejects_unreviewed_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            live_root = Path(directory)
            request_path = live_root / SUPERVISOR.REQUEST_FILE
            request = {
                "schemaVersion": 1,
                "character": "casual-girl",
                "requestId": "a" * 24,
                "requestedAtUnixMs": 1,
            }
            request_path.write_text(json.dumps(request), encoding="utf-8")
            request_path.chmod(0o600)
            self.assertEqual(SUPERVISOR.read_request(live_root)["character"], "casual-girl")
            request["character"] = "../../other"
            request_path.write_text(json.dumps(request), encoding="utf-8")
            request_path.chmod(0o600)
            self.assertIsNone(SUPERVISOR.read_request(live_root))

    def test_schema_one_casual_girl_defaults_to_full_body(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "FayAvatarRuntime"
            executable = root / "Binaries/LinuxArm64/FayAvatarRuntime"
            executable.parent.mkdir(parents=True)
            executable.write_bytes(b"runtime")
            executable.chmod(0o700)
            launcher = root / "FayAvatarRuntime-Arm64.sh"
            launcher.write_text("#!/bin/sh\n", encoding="utf-8")
            launcher.chmod(0o700)
            (root / ".ue5-spark-characters.json").write_text(json.dumps({
                "schema": 1,
                "characters": [{"id": "CasualGirl"}],
            }), encoding="utf-8")
            package = SUPERVISOR.load_package(executable, "v30")
            self.assertEqual(package.framings["casual-girl"], "FullBody")

    def test_supervisor_never_uses_broad_process_killers(self):
        source = SCRIPT_PATH.read_text(encoding="utf-8")
        for forbidden in ("killall", "pkill", "docker stop", "podman stop"):
            self.assertNotIn(forbidden, source)
        self.assertIn("an unmanaged FayAvatarRuntime is already running; nothing was stopped", source)
        self.assertIn("stop_renderer(previous)", source)


if __name__ == "__main__":
    unittest.main()
