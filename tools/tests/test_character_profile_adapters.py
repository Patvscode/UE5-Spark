from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PROFILE_TOOL = REPO_ROOT / "scripts" / "character-profiles.py"
PROFILE_CONFIG = REPO_ROOT / "Project/FayAvatarRuntime/Config/DefaultGame.ini"

CASUAL_GIRL_ACTOR_CLASS = (
    "/Game/FayFab/CasualGirl/Runtime/"
    "BP_CasualGirlFay.BP_CasualGirlFay_C"
)
CASUAL_GIRL_PROJECT_ASSET = (
    "Content/FayFab/CasualGirl/Runtime/BP_CasualGirlFay.uasset"
)
CASUAL_GIRL_PACKAGE_ASSET = (
    "FayAvatarRuntime/Content/FayFab/CasualGirl/Runtime/"
    "BP_CasualGirlFay.uasset"
)
def run_profile(config: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        (sys.executable, str(PROFILE_TOOL), "--config", str(config), *arguments),
        cwd=REPO_ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


class CharacterProfileAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base_config = PROFILE_CONFIG.read_text(encoding="utf-8")
        self.reviewed_config = self.base_config

    def replace_in_casual_girl_section(
        self, reviewed: str, replacement: str
    ) -> str:
        prefix, marker, section = self.reviewed_config.partition(
            "[FayCharacter.CasualGirl]"
        )
        self.assertTrue(marker)
        updated = section.replace(reviewed, replacement, 1)
        self.assertNotEqual(updated, section)
        return prefix + marker + updated

    def run_config(
        self, value: str, *arguments: str
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "DefaultGame.ini"
            path.write_text(value, encoding="utf-8")
            return run_profile(path, *arguments)

    def test_metahuman_and_epic_arkit_profiles_are_independently_sealed(self) -> None:
        result = self.run_config(
            self.reviewed_config,
            "--character",
            "Ada",
            "--character",
            "CasualGirl",
            "json",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        profiles = {profile["id"]: profile for profile in json.loads(result.stdout)}

        self.assertEqual(profiles["Ada"]["adapter"], "UE58MetaHuman")
        self.assertEqual(
            profiles["Ada"]["actor_class"],
            "/Game/FayMetaHumans/Built/AdaFay/BP_AdaFay.BP_AdaFay_C",
        )
        self.assertEqual(profiles["CasualGirl"]["adapter"], "UE5EpicArkit")
        self.assertEqual(
            profiles["CasualGirl"]["actor_class"], CASUAL_GIRL_ACTOR_CLASS
        )
        self.assertEqual(profiles["CasualGirl"]["face_component"], "Face")
        self.assertEqual(profiles["CasualGirl"]["body_component"], "Body")
        self.assertEqual(
            profiles["CasualGirl"]["cook_directories"],
            ["/Game/FayFab/CasualGirl", "/StreamingADA"],
        )
        self.assertEqual(
            profiles["CasualGirl"]["project_asset"], CASUAL_GIRL_PROJECT_ASSET
        )
        self.assertEqual(
            profiles["CasualGirl"]["package_asset"], CASUAL_GIRL_PACKAGE_ASSET
        )

    def test_epic_arkit_streaming_ada_cook_root_is_optional(self) -> None:
        without_streaming_ada = self.reviewed_config.replace(
            "CookDirectories=/Game/FayFab/CasualGirl;/StreamingADA",
            "CookDirectories=/Game/FayFab/CasualGirl",
            1,
        )
        result = self.run_config(without_streaming_ada, "validate")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_epic_arkit_profile_rejects_unreviewed_adapter_and_asset_paths(self) -> None:
        variants = {
            "unknown adapter": (
                "Adapter=UE5EpicArkit",
                "Adapter=UE5EpicArkitExperimental",
                "unsupported adapter",
            ),
            "cross-adapter actor": (
                f"ActorClass={CASUAL_GIRL_ACTOR_CLASS}",
                "ActorClass=/Game/FayMetaHumans/Built/AdaFay/"
                "BP_AdaFay.BP_AdaFay_C",
                "ActorClass",
            ),
            "alternate actor": (
                f"ActorClass={CASUAL_GIRL_ACTOR_CLASS}",
                "ActorClass=/Game/FayFab/CasualGirl/Runtime/"
                "BP_Unreviewed.BP_Unreviewed_C",
                "ActorClass",
            ),
            "actor traversal": (
                f"ActorClass={CASUAL_GIRL_ACTOR_CLASS}",
                "ActorClass=/Game/FayFab/CasualGirl/../Private/"
                "BP_CasualGirlFay.BP_CasualGirlFay_C",
                "ActorClass",
            ),
            "wrong face component": (
                "FaceComponent=Face",
                "FaceComponent=UnreviewedFace",
                "exact Face and Body",
            ),
            "wrong body component": (
                "BodyComponent=Body",
                "BodyComponent=UnreviewedBody",
                "exact Face and Body",
            ),
            "nested cook root": (
                "CookDirectories=/Game/FayFab/CasualGirl;/StreamingADA",
                "CookDirectories=/Game/FayFab/CasualGirl/Runtime;/StreamingADA",
                "requires /Game/FayFab/CasualGirl",
            ),
            "extra cook root": (
                "CookDirectories=/Game/FayFab/CasualGirl;/StreamingADA",
                "CookDirectories=/Game/FayFab/CasualGirl;/Game/Unreviewed",
                "cook directory is outside",
            ),
            "missing primary cook root": (
                "CookDirectories=/Game/FayFab/CasualGirl;/StreamingADA",
                "CookDirectories=/StreamingADA",
                "requires /Game/FayFab/CasualGirl",
            ),
            "alternate project asset": (
                f"ProjectAsset={CASUAL_GIRL_PROJECT_ASSET}",
                "ProjectAsset=Content/FayFab/CasualGirl/Runtime/Unreviewed.uasset",
                "ProjectAsset",
            ),
            "project asset traversal": (
                f"ProjectAsset={CASUAL_GIRL_PROJECT_ASSET}",
                "ProjectAsset=Content/FayFab/CasualGirl/../Private/"
                "BP_CasualGirlFay.uasset",
                "ProjectAsset",
            ),
            "alternate package asset": (
                f"PackageAsset={CASUAL_GIRL_PACKAGE_ASSET}",
                "PackageAsset=FayAvatarRuntime/Content/FayFab/CasualGirl/"
                "Runtime/Unreviewed.uasset",
                "PackageAsset",
            ),
        }

        for label, (reviewed, malicious, error_marker) in variants.items():
            with self.subTest(label=label):
                value = self.replace_in_casual_girl_section(reviewed, malicious)
                result = self.run_config(value, "validate")
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn(error_marker, result.stderr)


if __name__ == "__main__":
    unittest.main()
