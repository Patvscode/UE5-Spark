from __future__ import annotations

import ast
from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN = (
    REPO_ROOT
    / "Project/FayAvatarRuntime/Plugins/FayMetaHumanEditorTools"
)
SCRIPT_PATH = PLUGIN / "Scripts/build_ardy_v30_foundation.py"
HEADER_PATH = (
    PLUGIN
    / "Source/FayMetaHumanEditorTools/Public/FayArdyRetargetAssetLibrary.h"
)
SOURCE_PATH = (
    PLUGIN
    / "Source/FayMetaHumanEditorTools/Private/FayArdyRetargetAssetLibrary.cpp"
)
DOC_PATH = REPO_ROOT / "docs/ardy-v30-editor-foundation.md"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class ArdyEditorAssetBuilderContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.script = read(SCRIPT_PATH)
        cls.header = read(HEADER_PATH)
        cls.source = read(SOURCE_PATH)
        cls.docs = read(DOC_PATH)
        cls.tree = ast.parse(cls.script, filename=str(SCRIPT_PATH))

    def test_candidate_namespace_and_all_inputs_are_sealed(self) -> None:
        for marker in (
            'CANDIDATE_ROOT = "/Game/FayMetaHumans/Built/FayArdyV30"',
            'SOURCE_MESH = f"{CANDIDATE_ROOT}/Source/SKM_FayArdyCore27"',
            '"/Game/FayMetaHumans/Built/AdaFay/BP_AdaFay"',
            '"/Game/FayMetaHumans/Built/AoiFay/BP_AoiFay"',
            'SOURCE_TARGET_BODY_MESH = (',
            '"/Game/FayMetaHumans/Built/AdaFay/Body/SKM_AdaFay_BodyMesh"',
            '"metahuman_base_skel"',
            'CANDIDATE_TARGET_BODY_MESH = (',
            'CANDIDATE_TARGET_BODY_SKELETON = (',
        ):
            self.assertIn(marker, self.script)

        getenv_keys = []
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr != "get" or not node.args:
                continue
            if not isinstance(node.func.value, ast.Attribute):
                continue
            if (
                isinstance(node.func.value.value, ast.Name)
                and node.func.value.value.id == "os"
                and node.func.value.attr == "environ"
                and isinstance(node.args[0], ast.Constant)
            ):
                getenv_keys.append(node.args[0].value)
        self.assertEqual(getenv_keys, ["FAY_ARDY_V30_REVIEWED_REBUILD"])

    def test_source_and_target_ik_chains_are_explicit_and_body_only(self) -> None:
        expected_source = (
            '("Spine", "Spine", "Spine3")',
            '("LeftClavicle", "LeftShoulder", "LeftShoulder")',
            '("LeftArm", "LeftArm", "LeftHand")',
            '("RightClavicle", "RightShoulder", "RightShoulder")',
            '("RightArm", "RightArm", "RightHand")',
            '("LeftLeg", "LeftUpLeg", "LeftToeBase")',
            '("RightLeg", "RightUpLeg", "RightToeBase")',
        )
        expected_target = (
            '("Spine", "spine_01", "spine_05")',
            '("LeftClavicle", "clavicle_l", "clavicle_l")',
            '("LeftArm", "upperarm_l", "hand_l")',
            '("RightClavicle", "clavicle_r", "clavicle_r")',
            '("RightArm", "upperarm_r", "hand_r")',
            '("LeftLeg", "thigh_l", "ball_l")',
            '("RightLeg", "thigh_r", "ball_r")',
        )
        for marker in (*expected_source, *expected_target):
            self.assertIn(marker, self.script)
        for excluded in (
            '("Neck",',
            '("Head",',
            '("Finger",',
            '"RightHandEnd")',
            '"LeftHandThumb1")',
        ):
            self.assertNotIn(excluded, self.script)
        self.assertIn('SOURCE_IK_RIG, source_mesh, "Hips"', self.script)
        self.assertIn('TARGET_IK_RIG, target_mesh, "pelvis"', self.script)

    def test_retargeter_uses_fixed_ops_mappings_and_named_poses(self) -> None:
        for marker in (
            "controller.add_default_ops()",
            "controller.assign_ik_rig_to_all_ops(source, source_rig)",
            "controller.assign_ik_rig_to_all_ops(target, target_rig)",
            'controller.set_source_chain(chain, chain, "")',
            'SOURCE_POSE = "ARDY_Core27_TPose"',
            'TARGET_POSE = "MetaHuman_A_Pose"',
            "controller.create_retarget_pose(SOURCE_POSE, source)",
            "controller.create_retarget_pose(TARGET_POSE, target)",
            "controller.auto_align_bones(",
            "controller.get_num_retarget_ops() != 5",
        ):
            self.assertIn(marker, self.script)
        self.assertNotIn("auto_map_chains", self.script)
        self.assertNotIn("FUZZY", self.script)

    def test_exact_source_mask_and_single_binding_are_native_gates(self) -> None:
        for marker in (
            "FayValidateExactCore27Mesh(SourceMesh, OutReason)",
            "RebindPrivateTargetMeshSkeleton",
            "the mesh and skeleton must both be private FayArdyV30 duplicates",
            "CandidateBodyMesh->SetSkeleton(CandidateSkeleton)",
            'const FName BodyMaskName(TEXT("FayArdyV30_BodyOnly"));',
            'TEXT("root")',
            'TEXT("neck_01")',
            'TEXT("hand_l")',
            'TEXT("hand_r")',
            "ApprovedBodyBones().Contains(BoneName) ? 1.0f : 0.0f",
            "CountBindingsInBlueprintHierarchy",
            "ExistingCount > 1",
            "CreateNode(",
            "UFayArdyRetargetBindingComponent::StaticClass()",
            "CountBindingsInBlueprintHierarchy(CandidateBlueprint, LocalTemplate) != 1",
        ):
            self.assertIn(marker, self.source)
        self.assertNotIn(
            "ClearEntries()",
            self.source,
            "UBlendProfile::ClearEntries is not exported from UE 5.8's Engine module",
        )

    def test_postprocess_v2_contact_contract_is_sealed_but_not_faked(self) -> None:
        for marker in (
            "constexpr int32 V30ContractVersion = 2;",
            "FayArdyExcludesNeckAndHead",
            "FayArdyPreservesFingerPose",
            "FayArdyUsesFootContactOffsets",
            "FayArdyLeftHeelOffset",
            "FayArdyLeftToeOffset",
            "FayArdyRightHeelOffset",
            "FayArdyRightToeOffset",
            "FayArdyLeftHeelContact",
            "FayArdyLeftToeContact",
            "FayArdyRightHeelContact",
            "FayArdyRightToeContact",
            "ValidateZeroVectorProperty",
            "ValidateZeroFloatProperty",
        ):
            self.assertIn(marker, self.source)

        self.assertIn("validate_v30_post_process_inputs(", self.script)
        self.assertIn('"LOCKED_IN_PLACE" not in str(', self.script)
        self.assertIn("root-offset bound differs from 20 cm", self.script)

        self.assertIn(
            'profile.set_editor_property("target_post_process_anim_class", None)',
            self.script,
        )
        self.assertIn("FAY_ARDY_V30_FOUNDATION_BUILT=1", self.script)
        self.assertIn("intentionally NOT runtime ", self.script)
        self.assertIn('"ready. The fixed post-process AnimBP graph', self.script)
        self.assertIn("exits nonzero", self.docs)
        self.assertIn("does not replace front/side motion capture", self.docs)

    def test_existing_destinations_require_exact_reviewed_rebuild(self) -> None:
        for marker in (
            'FAY_ARDY_V30_REVIEWED_REBUILD=1',
            "candidate destinations already exist",
            "This builder never ",
            '"overwrites them. Inspect the assets',
            "if existing and not REBUILD:",
            "if (ExistingCount == 1)",
            "if (!bReviewedRebuild)",
        ):
            self.assertTrue(
                marker in self.script or marker in self.source or marker in self.docs,
                marker,
            )
        for forbidden in ("delete_asset", "delete_directory", "rename_asset"):
            self.assertNotIn(forbidden, self.script)


if __name__ == "__main__":
    unittest.main()
