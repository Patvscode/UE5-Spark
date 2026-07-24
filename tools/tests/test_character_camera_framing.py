from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PROFILE_TOOL = REPO_ROOT / "scripts" / "character-profiles.py"
PROFILE_CONFIG = REPO_ROOT / "Project/FayAvatarRuntime/Config/DefaultGame.ini"
GAME_MODE_SOURCE = (
    REPO_ROOT
    / "Project/FayAvatarRuntime/Source/FayAvatarRuntime/Private/"
    "FayAvatarBootstrapGameMode.cpp"
)
PACKAGE_VERIFIER = REPO_ROOT / "scripts" / "verify-cooked-package.sh"
SOAK_WRAPPER = REPO_ROOT / "scripts" / "run-spark-avatar-soak.sh"
SOAK_HARNESS = REPO_ROOT / "scripts" / "soak-spark-avatar.sh"


def run_profile(config: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        (sys.executable, str(PROFILE_TOOL), "--config", str(config), *arguments),
        cwd=REPO_ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


class CharacterCameraFramingTests(unittest.TestCase):
    def test_reviewed_ada_and_aoi_presets_preserve_portrait_default(self) -> None:
        result = run_profile(
            PROFILE_CONFIG,
            "--character",
            "Ada",
            "--character",
            "Aoi",
            "json",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        profiles = {profile["id"]: profile for profile in json.loads(result.stdout)}
        self.assertEqual(set(profiles), {"Ada", "Aoi"})

        expected_portrait = {
            "id": "Portrait",
            "location": "X=0 Y=-220 Z=165",
            "rotation": "P=0 Y=90 R=0",
            "field_of_view": 42.0,
        }
        self.assertEqual(profiles["Ada"]["camera_framings"][0], expected_portrait)
        self.assertEqual(profiles["Aoi"]["camera_framings"][0], expected_portrait)
        self.assertEqual(
            profiles["Ada"]["camera_framings"][1],
            {
                "id": "FullBody",
                "location": "X=0 Y=-525 Z=100",
                "rotation": "P=0 Y=90 R=0",
                "field_of_view": 42.0,
            },
        )
        self.assertEqual(
            profiles["Aoi"]["camera_framings"][1],
            {
                "id": "FullBody",
                "location": "X=0 Y=-550 Z=105",
                "rotation": "P=0 Y=90 R=0",
                "field_of_view": 42.0,
            },
        )

    def test_manifest_v2_seals_default_and_available_framings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manifest_path = Path(temporary) / "characters.json"
            result = run_profile(
                PROFILE_CONFIG,
                "--character",
                "Ada",
                "--character",
                "Aoi",
                "manifest",
                "--output",
                str(manifest_path),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["schema"], 2)
        self.assertEqual(payload["defaultCameraFraming"], "Portrait")
        self.assertEqual(
            payload["profileConfigSha256"],
            hashlib.sha256(PROFILE_CONFIG.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            [character["id"] for character in payload["characters"]],
            ["Ada", "Aoi"],
        )
        for character in payload["characters"]:
            self.assertEqual(character["cameraFramings"], ["Portrait", "FullBody"])

    def test_profile_validation_fails_closed_on_incomplete_or_invalid_presets(self) -> None:
        original = PROFILE_CONFIG.read_text(encoding="utf-8")
        variants = {
            "wrong default": original.replace(
                "DefaultCameraFraming=Portrait", "DefaultCameraFraming=portrait", 1
            ),
            "missing full-body field": original.replace(
                "CameraFullBodyRelativeLocation=X=0 Y=-525 Z=100\n", "", 1
            ),
            "invalid full-body fov": original.replace(
                "CameraFullBodyFieldOfView=42", "CameraFullBodyFieldOfView=91", 1
            ),
        }
        with tempfile.TemporaryDirectory() as temporary:
            for label, value in variants.items():
                with self.subTest(label=label):
                    path = Path(temporary) / f"{label.replace(' ', '-')}.ini"
                    path.write_text(value, encoding="utf-8")
                    result = run_profile(path, "validate")
                    self.assertNotEqual(result.returncode, 0)

    def test_profile_validation_fails_closed_on_malformed_transforms(self) -> None:
        original = PROFILE_CONFIG.read_text(encoding="utf-8")
        variants = {
            "spawn location commas": (
                "SpawnLocation=X=0 Y=0 Z=0",
                "SpawnLocation=X=0,Y=0,Z=0",
                "SpawnLocation",
            ),
            "spawn rotation incomplete": (
                "SpawnRotation=P=0 Y=180 R=0",
                "SpawnRotation=P=0 Y=180",
                "SpawnRotation",
            ),
            "portrait location reordered": (
                "CameraPortraitRelativeLocation=X=0 Y=-220 Z=165",
                "CameraPortraitRelativeLocation=Y=-220 X=0 Z=165",
                "CameraPortraitRelativeLocation",
            ),
            "portrait rotation nonnumeric": (
                "CameraPortraitRelativeRotation=P=0 Y=90 R=0",
                "CameraPortraitRelativeRotation=P=0 Y=90 R=nan",
                "CameraPortraitRelativeRotation",
            ),
            "full-body location extra token": (
                "CameraFullBodyRelativeLocation=X=0 Y=-525 Z=100",
                "CameraFullBodyRelativeLocation=X=0 Y=-525 Z=100 W=1",
                "CameraFullBodyRelativeLocation",
            ),
            "full-body rotation exponent": (
                "CameraFullBodyRelativeRotation=P=0 Y=90 R=0",
                "CameraFullBodyRelativeRotation=P=0 Y=9e1 R=0",
                "CameraFullBodyRelativeRotation",
            ),
        }
        with tempfile.TemporaryDirectory() as temporary:
            for label, (reviewed, malformed, key) in variants.items():
                with self.subTest(label=label):
                    value = original.replace(reviewed, malformed, 1)
                    self.assertNotEqual(value, original)
                    path = Path(temporary) / f"{label.replace(' ', '-')}.ini"
                    path.write_text(value, encoding="utf-8")
                    result = run_profile(path, "validate")
                    self.assertNotEqual(result.returncode, 0, result.stdout)
                    self.assertIn(key, result.stderr)
                    self.assertIn("exact reviewed Unreal syntax", result.stderr)

    def test_profile_validation_accepts_canonical_decimal_transforms(self) -> None:
        value = PROFILE_CONFIG.read_text(encoding="utf-8")
        replacements = {
            "SpawnLocation=X=0 Y=0 Z=0": "SpawnLocation=X=-1.25 Y=2.5 Z=0.125",
            "SpawnRotation=P=0 Y=180 R=0": "SpawnRotation=P=-10.5 Y=180.25 R=0.5",
            "CameraPortraitRelativeLocation=X=0 Y=-220 Z=165": (
                "CameraPortraitRelativeLocation=X=0.5 Y=-220.25 Z=165.75"
            ),
            "CameraPortraitRelativeRotation=P=0 Y=90 R=0": (
                "CameraPortraitRelativeRotation=P=-0.5 Y=90.25 R=1.5"
            ),
            "CameraFullBodyRelativeLocation=X=0 Y=-525 Z=100": (
                "CameraFullBodyRelativeLocation=X=-0.25 Y=-525.5 Z=100.25"
            ),
            "CameraFullBodyRelativeRotation=P=0 Y=90 R=0": (
                "CameraFullBodyRelativeRotation=P=0.25 Y=90.5 R=-1.25"
            ),
        }
        for reviewed, decimal in replacements.items():
            updated = value.replace(reviewed, decimal, 1)
            self.assertNotEqual(updated, value)
            value = updated

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "canonical-decimals.ini"
            path.write_text(value, encoding="utf-8")
            result = run_profile(path, "validate")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_runtime_accepts_only_exact_ids_and_no_camera_values(self) -> None:
        source = GAME_MODE_SOURCE.read_text(encoding="utf-8")
        for marker in (
            'DefaultCameraFramingId[] = TEXT("Portrait")',
            'FullBodyCameraFramingId[] = TEXT("FullBody")',
            'TEXT("-FayCameraFraming=")',
            "ParseIntoArrayWS(CommandLineTokens)",
            "CameraFramingArgumentCount <= 1",
            "!bMalformedCameraFramingArgument",
            "RequestedCameraFraming = Token.RightChop",
            "ESearchCase::CaseSensitive",
            "if (!bReviewedCameraFraming)",
            'TEXT("CameraPortraitRelativeLocation")',
            'TEXT("CameraFullBodyRelativeLocation")',
            "ActiveCameraFramingId = RequestedCameraFraming",
            "camera_framing=%s",
        ):
            self.assertIn(marker, source)
        for forbidden in (
            "FayCameraLocation=",
            "FayCameraRotation=",
            "FayCameraFieldOfView=",
            "RequestedCameraFraming.TrimStartAndEndInline",
        ):
            self.assertNotIn(forbidden, source)

    def test_packaged_manifest_contract_is_strict_v2(self) -> None:
        syntax = subprocess.run(
            ("bash", "-n", str(PACKAGE_VERIFIER)),
            cwd=REPO_ROOT,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(syntax.returncode, 0, syntax.stderr)
        source = PACKAGE_VERIFIER.read_text(encoding="utf-8")
        self.assertIn("the packaged character manifest is missing", source)
        self.assertIn('payload["schema"] != 2', source)
        self.assertIn('payload["defaultCameraFraming"] != "Portrait"', source)
        self.assertIn(
            'character["cameraFramings"] != ["Portrait", "FullBody"]', source
        )

    def test_guarded_soak_seals_exact_framing_argument_and_evidence(self) -> None:
        wrapper = SOAK_WRAPPER.read_text(encoding="utf-8")
        harness = SOAK_HARNESS.read_text(encoding="utf-8")
        for marker in (
            "camera_framing=${FAY_SOAK_CAMERA_FRAMING:-Portrait}",
            '"-FayCameraFraming=$camera_framing"',
            'export FAY_SOAK_EXPECTED_CAMERA_FRAMING="$camera_framing"',
            "camera_framing=$camera_framing",
        ):
            self.assertIn(marker, wrapper)
        for marker in (
            "expected_camera_framing=${FAY_SOAK_EXPECTED_CAMERA_FRAMING:-Portrait}",
            '"-FayCameraFraming=$expected_camera_framing"',
            "camera_framing_selected_count",
            'payload.get("schema") != 2',
            'matches[0].get("cameraFramings") != ["Portrait", "FullBody"]',
        ):
            self.assertIn(marker, harness)


if __name__ == "__main__":
    unittest.main()
