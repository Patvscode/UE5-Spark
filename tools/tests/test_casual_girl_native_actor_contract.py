from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PUBLIC_HEADER = (
    REPO_ROOT
    / "Project/FayAvatarRuntime/Source/FayAvatarRuntime/Public/"
    "FayCasualGirlActor.h"
).read_text(encoding="utf-8")
PRIVATE_SOURCE = (
    REPO_ROOT
    / "Project/FayAvatarRuntime/Source/FayAvatarRuntime/Private/"
    "FayCasualGirlActor.cpp"
).read_text(encoding="utf-8")
GAME_MODE = (
    REPO_ROOT
    / "Project/FayAvatarRuntime/Source/FayAvatarRuntime/Private/"
    "FayAvatarBootstrapGameMode.cpp"
).read_text(encoding="utf-8")


class CasualGirlNativeActorContractTests(unittest.TestCase):
    def test_native_actor_uses_reviewed_complete_body_as_driver(self) -> None:
        for marker in (
            "class FAYAVATARRUNTIME_API AFayCasualGirlActor",
            'CreateDefaultSubobject<USkeletalMeshComponent>(TEXT("Body"))',
            'TEXT("/Game/Sample/Meshes/SK_Complete.SK_Complete")',
            "AlwaysTickPoseAndRefreshBones",
        ):
            self.assertIn(marker, PUBLIC_HEADER + PRIVATE_SOURCE)

    def test_default_modular_outfit_uses_only_reviewed_sample_meshes(self) -> None:
        expected = {
            "Hair1": "/Game/Sample/Meshes/SK_Hair_1.SK_Hair_1",
            "Top1": "/Game/Sample/Meshes/SK_Top_1.SK_Top_1",
            "Pants": "/Game/Sample/Meshes/SK_Pants.SK_Pants",
            "Shoes_Socks": (
                "/Game/Sample/Meshes/SK_Shoes_Socks.SK_Shoes_Socks"
            ),
        }
        for component, asset_path in expected.items():
            self.assertIn(
                f'CreateDefaultSubobject<USkeletalMeshComponent>(TEXT("{component}"))',
                PRIVATE_SOURCE,
            )
            self.assertIn(f'TEXT("{asset_path}")', PRIVATE_SOURCE)

        self.assertEqual(PRIVATE_SOURCE.count("/Game/Sample/Meshes/"), 5)

    def test_outfit_follows_body_without_competing_animation(self) -> None:
        for marker in (
            "Follower->SetupAttachment(Leader);",
            "Follower->SetCollisionEnabled(ECollisionEnabled::NoCollision);",
            "Follower->SetGenerateOverlapEvents(false);",
            "Follower->bUseAttachParentBound = true;",
            "Follower->SetLeaderPoseComponent(Leader, true, false);",
        ):
            self.assertIn(marker, PRIVATE_SOURCE)

        self.assertEqual(PRIVATE_SOURCE.count("SetRootComponent("), 1)
        self.assertNotIn("SetAnimInstanceClass", PRIVATE_SOURCE)

    def test_actor_does_not_guess_an_animation_or_private_wrapper(self) -> None:
        for forbidden in (
            "SetAnimInstanceClass",
            "SetAnimation(",
            "BP_CasualGirlFay",
            "/Game/FayFab/",
        ):
            self.assertNotIn(forbidden, PUBLIC_HEADER + PRIVATE_SOURCE)

    def test_arkit_face_and_body_share_the_visible_complete_mesh(self) -> None:
        self.assertIn(
            'TEXT("/Script/FayAvatarRuntime.FayCasualGirlActor")',
            GAME_MODE,
        )
        self.assertIn(
            'FaceComponent == TEXT("Body") && BodyComponent == TEXT("Body")',
            GAME_MODE,
        )


if __name__ == "__main__":
    unittest.main()
