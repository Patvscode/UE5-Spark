from __future__ import annotations

import math
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = REPO_ROOT / "Project/FayAvatarRuntime/Plugins/FayBodyMotion"
PUBLIC = PLUGIN_ROOT / "Source/FayBodyMotion/Public"
PRIVATE = PLUGIN_ROOT / "Source/FayBodyMotion/Private"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class ArdyUnrealRetargetContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.coordinate = read(PRIVATE / "FayArdyCoordinateConversion.cpp")
        cls.source_anim = read(PRIVATE / "FayCore27SourceAnimInstance.cpp")
        cls.source_anim_header = read(PUBLIC / "FayCore27SourceAnimInstance.h")
        cls.contact = read(PRIVATE / "FayArdyContactStabilizer.cpp")
        cls.contact_header = read(PUBLIC / "FayArdyContactStabilizer.h")
        cls.skeleton = read(PRIVATE / "FayCore27Skeleton.cpp")
        cls.profile_header = read(PUBLIC / "FayArdyRetargetProfile.h")
        cls.profile_source = read(PRIVATE / "FayArdyRetargetProfile.cpp")
        cls.motion = read(PRIVATE / "FayBodyMotionComponent.cpp")
        cls.plugin_sources = "\n".join(
            read(path)
            for path in sorted((PLUGIN_ROOT / "Source").rglob("*"))
            if path.suffix in {".h", ".cpp"}
        )

    def test_ardy_handedness_conversion_is_exact_and_single_boundary(self) -> None:
        self.assertIn(
            "FVector(PositionMetres.Z, -PositionMetres.X, PositionMetres.Y) * 100.0",
            self.coordinate,
        )
        self.assertIn(
            "FQuat Converted(-Rotation.Z, Rotation.X, -Rotation.Y, Rotation.W)",
            self.coordinate,
        )
        self.assertIn("Converted.Normalize();", self.coordinate)
        self.assertEqual(
            self.plugin_sources.count("FayConvertArdyQuaternionToUnreal("),
            4,
            "declaration, definition, Core27 source, and native Epic adapter are expected",
        )

        # Source unit axes must become Unreal forward, left, and up exactly.
        convert_position = lambda value: (value[2], -value[0], value[1])
        self.assertEqual(convert_position((0.0, 0.0, 1.0)), (1.0, -0.0, 0.0))
        self.assertEqual(convert_position((1.0, 0.0, 0.0)), (0.0, -1.0, 0.0))
        self.assertEqual(convert_position((0.0, 1.0, 0.0)), (0.0, -0.0, 1.0))

        # For the improper basis C, an axial quaternion vector transforms as
        # det(C)C: (-z,x,-y). Verify C*R*C^-1 for non-trivial rotations.
        basis = ((0.0, 0.0, 1.0), (-1.0, 0.0, 0.0), (0.0, 1.0, 0.0))

        def multiply(left, right):
            return tuple(
                tuple(sum(left[row][k] * right[k][column] for k in range(3)) for column in range(3))
                for row in range(3)
            )

        def transpose(value):
            return tuple(tuple(value[column][row] for column in range(3)) for row in range(3))

        def rotation_matrix(quaternion):
            x, y, z, w = quaternion
            return (
                (1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)),
                (2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)),
                (2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)),
            )

        for axis in ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, 2.0, 3.0)):
            length = math.sqrt(sum(component * component for component in axis))
            sine = math.sin(0.37) / length
            source_quaternion = (
                axis[0] * sine,
                axis[1] * sine,
                axis[2] * sine,
                math.cos(0.37),
            )
            converted_quaternion = (
                -source_quaternion[2],
                source_quaternion[0],
                -source_quaternion[1],
                source_quaternion[3],
            )
            expected = multiply(multiply(basis, rotation_matrix(source_quaternion)), transpose(basis))
            actual = rotation_matrix(converted_quaternion)
            for expected_row, actual_row in zip(expected, actual):
                for expected_value, actual_value in zip(expected_row, actual_row):
                    self.assertAlmostEqual(expected_value, actual_value, places=12)

    def test_hidden_core27_pose_uses_normal_animation_evaluation(self) -> None:
        for marker in (
            "class FFayCore27SourceAnimProxy final : public FAnimInstanceProxy",
            "Output.ResetToRefPose();",
            "Output.Pose.NormalizeRotations();",
            "JointIndex == Core27SourceNeckJointIndex ||",
            "JointIndex == Core27SourceHeadJointIndex",
            "UFayCore27SourceAnimInstance::SubmitPose",
            "UFayCore27SourceAnimInstance::ResetPose",
            "FScopeLock Lock(&PoseMutex);",
        ):
            self.assertIn(marker, self.source_anim)
        self.assertIn("struct FAnimInstanceProxy;", self.source_anim_header)
        self.assertNotIn("class FAnimInstanceProxy;", self.source_anim_header)

    def test_unsafe_finalized_pose_mutation_and_first_frame_delta_are_absent(self) -> None:
        for forbidden in (
            "const_cast",
            "RegisterOnBoneTransformsFinalizedDelegate",
            "GetComponentSpaceTransforms",
            "ArdyBaselineLocalRotations",
            "FirstFrameLocal",
        ):
            self.assertNotIn(forbidden, self.plugin_sources)

    def test_core27_source_mesh_must_match_exact_hierarchy(self) -> None:
        for marker in (
            "ReferenceSkeleton.GetNum() != Expected.Num()",
            "ReferenceSkeleton.GetBoneName(Index)",
            "ReferenceSkeleton.GetParentIndex(Index)",
            "ActualName != Expected[Index].Name",
            "ActualParent != Expected[Index].ParentIndex",
        ):
            self.assertIn(marker, self.skeleton)
        self.assertEqual(self.skeleton.count("{TEXT("), 27)

    def test_retarget_assets_and_face_ownership_fail_closed(self) -> None:
        for marker in (
            "Bindings.Num() != 1",
            "FayValidateExactCore27Mesh(SourceAsset, FailureReason)",
            'TEXT("/Script/IKRig.IKRetargeter")',
            'TEXT("/Script/Engine.BlendProfile")',
            "BodyMesh->GetPostProcessInstance()",
            "FayArdyExcludesNeckAndHead",
            "FayArdyPreservesFingerPose",
            "BodyMesh->GetAnimClass() != OriginalBodyAnimClass",
            "BodyMesh->AddTickPrerequisiteComponent(ArdySourceMesh)",
            "Generated retarget contract changed at runtime",
        ):
            self.assertIn(marker, self.motion)

    def test_root_origin_is_action_scoped_and_default_is_locked(self) -> None:
        for marker in (
            "EFayArdyRootMotionPolicy::LockedInPlace",
            'meta = (ClampMin = "0.0", ClampMax = "20.0")',
            "float MaximumRootOffsetCentimetres = 20.0f;",
        ):
            self.assertIn(marker, self.profile_header)
        self.assertIn(
            "MaximumRootOffsetCentimetres > 20.0f",
            self.profile_source,
        )
        reset = self.motion[
            self.motion.index("void UFayBodyMotionComponent::ResetGeneratedRetargetState") :
            self.motion.index("void UFayBodyMotionComponent::StartGeneratedAction")
        ]
        self.assertIn("bHasGeneratedRootOrigin = false;", reset)
        self.assertIn("GeneratedRootOriginMetres = FVector3f::ZeroVector;", reset)
        start = self.motion[
            self.motion.index("void UFayBodyMotionComponent::StartGeneratedAction") :
            self.motion.index("void UFayBodyMotionComponent::BeginGeneratedActionBlendOut")
        ]
        self.assertIn("ResetGeneratedRetargetState();", start)

    def test_real_ardy_catalog_drives_wave_and_full_body_actions(self) -> None:
        for behavior in (
            "idle",
            "listen",
            "explain",
            "wave",
            "jog_in_place",
            "run_in_place",
            "jumping_jacks",
            "stretch",
            "dance_relaxed",
        ):
            self.assertIn(f'TEXT("{behavior}")', self.motion)
        self.assertIn("Client->SupportsBehavior(Request.Behavior)", self.motion)
        self.assertIn("ArdyProvider->CanPerform(Request)", self.motion)
        dispatch = self.motion[self.motion.index("bool UFayBodyMotionComponent::Dispatch") :]
        self.assertIn(
            "ReviewedGeneratedBehaviors().Contains(Request.Behavior)",
            dispatch,
        )
        self.assertIn(
            "!bDeterministicOnly && bReviewedGeneratedAction &&",
            dispatch,
        )
        self.assertIn("ArdyProvider != nullptr &&", dispatch)
        self.assertNotIn("bReviewedMontageWins", dispatch)
        self.assertIn("bUsedBakedFailureFallback", dispatch)
        self.assertIn("strict ARDY v2 or the reviewed retarget was unavailable", dispatch)

    def test_contact_stabilizer_is_bounded_and_fail_closed(self) -> None:
        for marker in (
            "constexpr int32 FayContactJointIndices[FayContactCount] = {25, 26, 21, 22};",
            "constexpr float FayContactAcquireThreshold = 0.65f;",
            "constexpr float FayContactReleaseThreshold = 0.35f;",
            "constexpr float FayMaximumContactCorrectionCentimetres = 6.0f;",
            "constexpr float FayMaximumContactAnchorDriftCentimetres = 18.0f;",
            "State.bBlockedUntilRelease = true;",
            "FayConvertArdyPositionToUnrealCentimetres(",
            "(-DriftCentimetres).GetClampedToMaxSize(",
            "FFayArdyContactStabilizer::FadeOut",
        ):
            self.assertIn(marker, self.contact)
        for forbidden in ("RootOffset", "Neck", "Head", "Face", "Finger"):
            self.assertNotIn(forbidden, self.contact)

    def test_contact_postprocess_contract_is_exact(self) -> None:
        self.assertIn("constexpr int32 RetargetContractVersion = 2;", self.motion)
        for variable in (
            "FayArdyUsesFootContactOffsets",
            "FayArdyLeftHeelOffset",
            "FayArdyLeftToeOffset",
            "FayArdyRightHeelOffset",
            "FayArdyRightToeOffset",
            "FayArdyLeftHeelContact",
            "FayArdyLeftToeContact",
            "FayArdyRightHeelContact",
            "FayArdyRightToeContact",
        ):
            self.assertIn(variable, self.motion)
        for marker in (
            "OffsetInput->Struct == TBaseStructure<FVector>::Get()",
            "!ContactUsageProperty->GetPropertyValue_InContainer(",
            "ContactStabilizer.Update(Pose, DeltaSeconds, ContactOutput)",
            "ContactStabilizer.FadeOut(DeltaSeconds, ContactOutput)",
            "ClearFootContactOutput();",
        ):
            self.assertIn(marker, self.motion)
        self.assertIn("No root, neck, head, face, or finger transform", self.contact_header)
        locked_root = self.motion[
            self.motion.index("FVector UFayBodyMotionComponent::ComputeBoundedRootOffset") :
            self.motion.index("bool UFayBodyMotionComponent::SetTargetObjectInput")
        ]
        self.assertIn("EFayArdyRootMotionPolicy::LockedInPlace", locked_root)
        self.assertIn("return FVector::ZeroVector;", locked_root)


if __name__ == "__main__":
    unittest.main()
