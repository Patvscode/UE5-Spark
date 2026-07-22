from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
LOOSE_COOK_VERIFIER = REPO_ROOT / "scripts/verify-linux-arm64-cook.sh"


def contract_validator_source() -> str:
    source = LOOSE_COOK_VERIFIER.read_text(encoding="utf-8")
    start = "profile_contract_rows=$(python3 -c '\n"
    _, marker, remainder = source.partition(start)
    if not marker:
        raise AssertionError("loose-cook verifier has no embedded contract validator")
    validator, marker, _ = remainder.partition("\n' <<<\"$profile_json\")")
    if not marker:
        raise AssertionError("loose-cook contract validator is unterminated")
    return validator


def metahuman_profile() -> dict[str, object]:
    return {
        "id": "Ada",
        "adapter": "UE58MetaHuman",
        "actor_class": (
            "/Game/FayMetaHumans/Built/AdaFay/"
            "BP_AdaFay.BP_AdaFay_C"
        ),
        "package_asset": (
            "FayAvatarRuntime/Content/FayMetaHumans/Built/"
            "AdaFay/BP_AdaFay.uasset"
        ),
        "cook_directories": [
            "/Game/FayMetaHumans/Built/AdaFay",
            "/Game/FayMetaHumans/Common_UE58",
            "/StreamingADA",
        ],
    }


def casual_girl_profile() -> dict[str, object]:
    return {
        "id": "CasualGirl",
        "adapter": "UE5EpicArkit",
        "actor_class": (
            "/Game/FayFab/CasualGirl/Runtime/"
            "BP_CasualGirlFay.BP_CasualGirlFay_C"
        ),
        "package_asset": (
            "FayAvatarRuntime/Content/FayFab/CasualGirl/Runtime/"
            "BP_CasualGirlFay.uasset"
        ),
        "cook_directories": ["/Game/FayFab/CasualGirl", "/StreamingADA"],
    }


def validate(profiles: list[dict[str, object]]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        (sys.executable, "-c", contract_validator_source()),
        cwd=REPO_ROOT,
        check=False,
        text=True,
        input=json.dumps(profiles),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


class CookAdapterVerifierContractTests(unittest.TestCase):
    def test_accepts_reviewed_metahuman_and_casual_girl_contracts(self) -> None:
        result = validate([metahuman_profile(), casual_girl_profile()])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "Ada\tUE58MetaHuman\t"
                "FayAvatarRuntime/Content/FayMetaHumans/Built/"
                "AdaFay/BP_AdaFay.uasset",
                "CasualGirl\tUE5EpicArkit\t"
                "FayAvatarRuntime/Content/FayFab/CasualGirl/Runtime/"
                "BP_CasualGirlFay.uasset",
            ],
        )

    def test_casual_girl_contract_requires_streaming_ada_for_this_schema(self) -> None:
        profile = casual_girl_profile()
        profile["cook_directories"] = ["/Game/FayFab/CasualGirl"]
        result = validate([profile])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "current reviewed UE5EpicArkit cook contract requires StreamingADA",
            result.stderr,
        )

    def test_casual_girl_contract_rejects_unreviewed_ids_and_paths(self) -> None:
        mutations = {
            "ID": ("id", "OtherGirl", "unreviewed UE5EpicArkit"),
            "actor": (
                "actor_class",
                metahuman_profile()["actor_class"],
                "unsafe selected UE5EpicArkit profile paths",
            ),
            "package": (
                "package_asset",
                metahuman_profile()["package_asset"],
                "unsafe selected UE5EpicArkit profile paths",
            ),
        }
        for label, (key, value, error) in mutations.items():
            with self.subTest(label=label):
                profile = casual_girl_profile()
                profile[key] = value
                result = validate([profile])
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(error, result.stderr)

    def test_metahuman_contract_rejects_mismatched_paths_and_missing_roots(self) -> None:
        mismatch = metahuman_profile()
        mismatch["package_asset"] = (
            "FayAvatarRuntime/Content/FayMetaHumans/Built/"
            "AoiFay/BP_AoiFay.uasset"
        )
        result = validate([mismatch])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("mismatched MetaHuman profile paths", result.stderr)

        cross_adapter = metahuman_profile()
        cross_adapter["actor_class"] = casual_girl_profile()["actor_class"]
        cross_adapter["package_asset"] = casual_girl_profile()["package_asset"]
        result = validate([cross_adapter])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unsafe selected UE58MetaHuman profile paths", result.stderr)

        missing_common = metahuman_profile()
        missing_common["cook_directories"] = [
            "/Game/FayMetaHumans/Built/AdaFay",
            "/StreamingADA",
        ]
        result = validate([missing_common])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("omits its common assets", result.stderr)

    def test_content_checks_are_selected_adapter_conditional(self) -> None:
        source = LOOSE_COOK_VERIFIER.read_text(encoding="utf-8")
        for marker in (
            "if (( requires_metahuman == 1 )); then",
            "if (( requires_epic_arkit == 1 )); then",
            "if (( requires_streaming_ada == 1 )); then",
            "FayAvatarRuntime/Content/FayFab/CasualGirl/",
            "FayAvatarRuntime/Content/FayMetaHumans/Common_UE58/",
        ):
            self.assertIn(marker, source)


if __name__ == "__main__":
    unittest.main()
