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
    def test_native_actor_uses_one_reviewed_complete_body(self) -> None:
        for marker in (
            "class FAYAVATARRUNTIME_API AFayCasualGirlActor",
            'CreateDefaultSubobject<USkeletalMeshComponent>(TEXT("Body"))',
            'TEXT("/Game/Sample/Meshes/SK_Complete.SK_Complete")',
            "AlwaysTickPoseAndRefreshBones",
        ):
            self.assertIn(marker, PUBLIC_HEADER + PRIVATE_SOURCE)

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
