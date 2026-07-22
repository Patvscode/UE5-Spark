from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_VERIFIER = REPO_ROOT / "scripts/verify-cooked-package.sh"
PACKAGE_LAUNCHER = REPO_ROOT / "scripts/run-cooked-package.sh"


def manifest_validator_source() -> str:
    source = PACKAGE_VERIFIER.read_text(encoding="utf-8")
    _, marker, remainder = source.partition("<<'PY'\n")
    if not marker:
        raise AssertionError("package verifier has no embedded manifest validator")
    validator, marker, _ = remainder.partition("\nPY\n")
    if not marker:
        raise AssertionError("package verifier manifest validator is unterminated")
    return validator


def character(camera_framings: bool) -> dict[str, object]:
    result: dict[str, object] = {
        "id": "Ada",
        "adapter": "UE58MetaHuman",
        "actorClass": (
            "/Game/FayMetaHumans/Built/AdaFay/"
            "BP_AdaFay.BP_AdaFay_C"
        ),
        "packageAsset": (
            "FayAvatarRuntime/Content/FayMetaHumans/Built/"
            "AdaFay/BP_AdaFay.uasset"
        ),
    }
    if camera_framings:
        result["cameraFramings"] = ["Portrait", "FullBody"]
    return result


def manifest(schema: int) -> dict[str, object]:
    result: dict[str, object] = {
        "schema": schema,
        "profileConfigSha256": "a" * 64,
        "characters": [character(camera_framings=schema == 2)],
    }
    if schema == 2:
        result["defaultCameraFraming"] = "Portrait"
    return result


def run_manifest_validator(
    payload: object,
    framing: str,
    *,
    allow_legacy_portrait: bool,
) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "characters.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return subprocess.run(
            (
                sys.executable,
                "-c",
                manifest_validator_source(),
                str(path),
                framing,
                "1" if allow_legacy_portrait else "0",
            ),
            cwd=REPO_ROOT,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )


class PackageManifestCompatibilityTests(unittest.TestCase):
    def test_manifestless_legacy_boundary_is_portrait_only_and_never_resealed(self) -> None:
        source = PACKAGE_VERIFIER.read_text(encoding="utf-8")
        self.assertIn(
            "if (( allow_legacy_portrait_manifest == 1 )) && \\",
            source,
        )
        self.assertIn("[[ $expected_camera_framing == Portrait ]]", source)
        self.assertIn(
            "only sealed legacy Portrait packages may omit it",
            source,
        )

    def test_legacy_schema_one_remains_launchable_only_in_portrait(self) -> None:
        portrait = run_manifest_validator(
            manifest(1), "Portrait", allow_legacy_portrait=True
        )
        self.assertEqual(portrait.returncode, 0, portrait.stderr)
        self.assertEqual(
            portrait.stdout,
            "Ada\tFayAvatarRuntime/Content/FayMetaHumans/Built/"
            "AdaFay/BP_AdaFay.uasset\n",
        )

        full_body = run_manifest_validator(
            manifest(1), "FullBody", allow_legacy_portrait=True
        )
        self.assertNotEqual(full_body.returncode, 0)
        self.assertIn("support only Portrait", full_body.stderr)

    def test_legacy_schema_one_cannot_be_used_to_seal_a_new_package(self) -> None:
        result = run_manifest_validator(
            manifest(1), "Portrait", allow_legacy_portrait=False
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cannot be used to seal new packages", result.stderr)

    def test_schema_two_strictly_supports_both_reviewed_framings(self) -> None:
        for framing in ("Portrait", "FullBody"):
            with self.subTest(framing=framing):
                result = run_manifest_validator(
                    manifest(2), framing, allow_legacy_portrait=False
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_each_schema_rejects_fields_from_the_other_contract(self) -> None:
        legacy_with_v2_fields = copy.deepcopy(manifest(1))
        legacy_with_v2_fields["defaultCameraFraming"] = "Portrait"
        legacy_with_v2_fields["characters"][0]["cameraFramings"] = [
            "Portrait",
            "FullBody",
        ]
        result = run_manifest_validator(
            legacy_with_v2_fields, "Portrait", allow_legacy_portrait=True
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid legacy character manifest keys", result.stderr)

        v2_without_camera_contract = copy.deepcopy(manifest(2))
        del v2_without_camera_contract["characters"][0]["cameraFramings"]
        result = run_manifest_validator(
            v2_without_camera_contract, "Portrait", allow_legacy_portrait=False
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid character manifest entry", result.stderr)

    def test_guarded_launcher_passes_one_exact_framing_to_verifier(self) -> None:
        source = PACKAGE_LAUNCHER.read_text(encoding="utf-8")
        for marker in (
            "camera_framing=Portrait",
            "camera_framing_argument_count",
            "-faycameraframing|-faycameraframing=*",
            "-FayCameraFraming=Portrait",
            "-FayCameraFraming=FullBody",
            '"$launcher_dir" --camera-framing "$camera_framing"',
        ):
            self.assertIn(marker, source)


if __name__ == "__main__":
    unittest.main()
