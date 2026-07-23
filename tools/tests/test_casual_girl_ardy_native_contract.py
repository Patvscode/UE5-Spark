from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN = REPO_ROOT / "Project/FayAvatarRuntime/Plugins/FayBodyMotion/Source/FayBodyMotion"


class CasualGirlArdyNativeContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.header = (PLUGIN / "Public/FayCore27EpicAnimInstance.h").read_text()
        cls.source = (PLUGIN / "Private/FayCore27EpicAnimInstance.cpp").read_text()
        cls.motion = (PLUGIN / "Private/FayBodyMotionComponent.cpp").read_text()

    def test_adapter_is_limited_to_reviewed_epic_skeleton(self) -> None:
        self.assertIn('Skeleton->GetName() != TEXT("SK_Mannequin")', self.source)
        for bone in (
            "pelvis",
            "spine_05",
            "upperarm_l",
            "lowerarm_r",
            "thigh_l",
            "calf_r",
            "foot_l",
            "ball_r",
        ):
            self.assertIn(f'TEXT("{bone}")', self.source)
        self.assertIn("RequiredEpicParents", self.source)

    def test_core27_mapping_excludes_face_head_and_fingers(self) -> None:
        mapping = self.source[
            self.source.index("constexpr FFayEpicBoneMap EpicBoneMap[]") :
            self.source.index("constexpr const TCHAR* RequiredEpicBones[]")
        ]
        for forbidden in ("neck_01", "head", "index_01", "thumb_01"):
            self.assertNotIn(forbidden, mapping)
        self.assertIn("normal animation", self.header)
        self.assertIn("approximate rotational retarget", self.header)

    def test_body_motion_selects_native_adapter_only_without_binding(self) -> None:
        configure = self.motion[
            self.motion.index("bool UFayBodyMotionComponent::ConfigureGeneratedRetarget") :
            self.motion.index("void UFayBodyMotionComponent::TearDownGeneratedRetarget")
        ]
        self.assertIn("if (Bindings.Num() == 0)", configure)
        self.assertIn("ConfigureEpicNativeRetarget", configure)
        self.assertIn("SupportsExactEpicSkeleton", configure)
        self.assertIn(
            "BodyMesh->SetAnimInstanceClass(UFayCore27EpicAnimInstance::StaticClass())",
            configure,
        )
        self.assertIn("BodyMesh->SetAnimInstanceClass(OriginalBodyAnimClass)", configure)

    def test_ardy_pose_uses_bounded_blend_and_normal_proxy_evaluation(self) -> None:
        for marker in (
            "class FFayCore27EpicAnimProxy final : public FAnimInstanceProxy",
            "Output.ResetToRefPose();",
            "FQuat::Slerp(",
            "Pose.RootOffsetCentimetres * Weight",
            "Output.Pose.NormalizeRotations();",
            "FScopeLock Lock(&PoseMutex);",
        ):
            self.assertIn(marker, self.source)
        self.assertNotIn("GetComponentSpaceTransforms", self.source)
        self.assertNotIn("const_cast", self.source)

    def test_native_path_does_not_claim_postprocess_contact_offsets(self) -> None:
        self.assertIn(
            "bSafeProceduralReady = bGeneratedRetargetReady &&\n"
            "        !bGeneratedRetargetUsesEpicNative;",
            self.motion,
        )
        self.assertIn("ContactStabilizer.Reset();", self.motion)
        self.assertIn("EpicTargetAnimation->SubmitPose(", self.motion)


if __name__ == "__main__":
    unittest.main()
