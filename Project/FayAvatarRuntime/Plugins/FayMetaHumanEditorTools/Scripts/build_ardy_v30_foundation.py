"""Build the sealed, source-only-safe ARDY v30 Unreal asset foundation.

This script intentionally stops after creating and validating the exact Core27
and MetaHuman IK assets, body Blend Mask, draft runtime profile, and isolated
Ada/Aoi candidate Blueprints.  It does *not* claim that a post-process AnimGraph
has been safely spliced.  The draft profile therefore keeps
``TargetPostProcessAnimClass`` unset and runtime ARDY remains fail-closed.

The only supported rebuild switch is the exact environment variable
``FAY_ARDY_V30_REVIEWED_REBUILD=1``.  A rebuild reuses and validates fixed
candidate assets; it never accepts arbitrary content paths and never deletes
or overwrites v29 assets.
"""

from __future__ import annotations

import os

import unreal


CANDIDATE_ROOT = "/Game/FayMetaHumans/Built/FayArdyV30"
SOURCE_MESH = f"{CANDIDATE_ROOT}/Source/SKM_FayArdyCore27"
SOURCE_IK_RIG = f"{CANDIDATE_ROOT}/Rigs/IK_FayArdyCore27"
TARGET_IK_RIG = f"{CANDIDATE_ROOT}/Rigs/IK_FayMetaHumanBody"
RETARGETER = f"{CANDIDATE_ROOT}/Rigs/RTG_FayArdyCore27_MetaHuman"
SHARED_PROFILE = f"{CANDIDATE_ROOT}/DA_FayArdyV30_MetaHuman"
POST_PROCESS_ANIM_BP = (
    f"{CANDIDATE_ROOT}/Animation/ABP_FayArdyV30_BodyPostProcess"
)

SOURCE_TARGET_BODY_MESH = (
    "/Game/FayMetaHumans/Built/AdaFay/Body/SKM_AdaFay_BodyMesh"
)
SOURCE_TARGET_BODY_SKELETON = (
    "/Game/FayMetaHumans/Common_UE58/Female/Medium/NormalWeight/Body/"
    "metahuman_base_skel"
)
CANDIDATE_TARGET_BODY_MESH = (
    f"{CANDIDATE_ROOT}/Target/SKM_AdaFay_BodyMesh_RetargetPreview"
)
CANDIDATE_TARGET_BODY_SKELETON = (
    f"{CANDIDATE_ROOT}/Target/metahuman_base_skel_ArdyV30"
)
CHARACTERS = {
    "Ada": {
        "source": "/Game/FayMetaHumans/Built/AdaFay/BP_AdaFay",
        "candidate": f"{CANDIDATE_ROOT}/Characters/Ada/BP_AdaFay_ArdyV30",
    },
    "Aoi": {
        "source": "/Game/FayMetaHumans/Built/AoiFay/BP_AoiFay",
        "candidate": f"{CANDIDATE_ROOT}/Characters/Aoi/BP_AoiFay_ArdyV30",
    },
}

SOURCE_CHAINS = (
    ("Spine", "Spine", "Spine3"),
    ("LeftClavicle", "LeftShoulder", "LeftShoulder"),
    ("LeftArm", "LeftArm", "LeftHand"),
    ("RightClavicle", "RightShoulder", "RightShoulder"),
    ("RightArm", "RightArm", "RightHand"),
    ("LeftLeg", "LeftUpLeg", "LeftToeBase"),
    ("RightLeg", "RightUpLeg", "RightToeBase"),
)
TARGET_CHAINS = (
    ("Spine", "spine_01", "spine_05"),
    ("LeftClavicle", "clavicle_l", "clavicle_l"),
    ("LeftArm", "upperarm_l", "hand_l"),
    ("RightClavicle", "clavicle_r", "clavicle_r"),
    ("RightArm", "upperarm_r", "hand_r"),
    ("LeftLeg", "thigh_l", "ball_l"),
    ("RightLeg", "thigh_r", "ball_r"),
)
TARGET_ALIGN_BONES = (
    "spine_01",
    "spine_02",
    "spine_03",
    "spine_04",
    "spine_05",
    "clavicle_l",
    "upperarm_l",
    "lowerarm_l",
    "hand_l",
    "clavicle_r",
    "upperarm_r",
    "lowerarm_r",
    "hand_r",
    "thigh_l",
    "calf_l",
    "foot_l",
    "ball_l",
    "thigh_r",
    "calf_r",
    "foot_r",
    "ball_r",
)
SOURCE_POSE = "ARDY_Core27_TPose"
TARGET_POSE = "MetaHuman_A_Pose"
PROFILE_ID = "FayArdyV30_MetaHumanBody"
REBUILD = os.environ.get("FAY_ARDY_V30_REVIEWED_REBUILD") == "1"


def fail(message: str) -> None:
    unreal.log_error(f"Fay ARDY v30 foundation stopped: {message}")
    raise RuntimeError(message)


def object_path(value) -> str:
    return str(value.get_path_name()) if value is not None else ""


def name_string(value) -> str:
    text = str(value)
    return "" if text in {"", "None", "NAME_None"} else text


def vector_is_zero(value) -> bool:
    return all(
        abs(float(component)) <= 1e-6
        for component in (value.x, value.y, value.z)
    )


def unpack_reason(result):
    """Normalize Unreal Python's return-plus-out-parameter convention."""

    if isinstance(result, tuple):
        if len(result) != 2:
            fail(f"unexpected Editor adapter return shape: {result!r}")
        return result[0], str(result[1])
    return result, ""


def require_asset(path: str, expected_type=None):
    asset = unreal.load_asset(path)
    if asset is None:
        fail(f"required reviewed asset is missing: {path}")
    if expected_type is not None and not isinstance(asset, expected_type):
        fail(f"{path} is not a {expected_type.__name__}")
    return asset


def ensure_clean_editor_state() -> None:
    dirty_maps = unreal.EditorLoadingAndSavingUtils.get_dirty_map_packages()
    dirty_content = unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()
    if dirty_maps or dirty_content:
        names = [
            str(package.get_path_name())
            for package in [*dirty_maps, *dirty_content]
        ]
        fail(
            "save or discard existing dirty packages before building the "
            "isolated candidate:\n  " + "\n  ".join(names)
        )


def ensure_destination_policy() -> None:
    destinations = [
        SOURCE_IK_RIG,
        TARGET_IK_RIG,
        RETARGETER,
        SHARED_PROFILE,
        POST_PROCESS_ANIM_BP,
        CANDIDATE_TARGET_BODY_MESH,
        CANDIDATE_TARGET_BODY_SKELETON,
        *(profile["candidate"] for profile in CHARACTERS.values()),
    ]
    existing = [
        path
        for path in destinations
        if unreal.EditorAssetLibrary.does_asset_exist(path)
    ]
    if existing and not REBUILD:
        fail(
            "candidate destinations already exist. This builder never "
            "overwrites them. Inspect the assets, then set the exact "
            "FAY_ARDY_V30_REVIEWED_REBUILD=1 flag to validate/reuse them:\n  "
            + "\n  ".join(existing)
        )
    if POST_PROCESS_ANIM_BP in existing and not REBUILD:
        fail("an unreviewed post-process candidate already occupies the sealed path")


def create_asset(path: str, asset_class, factory):
    package_path, asset_name = path.rsplit("/", 1)
    asset = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
        asset_name=asset_name,
        package_path=package_path,
        asset_class=asset_class,
        factory=factory,
    )
    if asset is None:
        fail(f"Unreal could not create {path}")
    return asset


def duplicate_or_validate_asset(source_path: str, candidate_path: str, asset_type):
    if unreal.EditorAssetLibrary.does_asset_exist(candidate_path):
        if not REBUILD:
            fail(f"candidate asset already exists: {candidate_path}")
        return require_asset(candidate_path, asset_type)
    candidate = unreal.EditorAssetLibrary.duplicate_asset(
        source_path, candidate_path
    )
    if candidate is None or not isinstance(candidate, asset_type):
        fail(f"could not duplicate {source_path} into the private v30 namespace")
    return candidate


def validate_ik_rig(controller, mesh, root: str, chains) -> None:
    if object_path(controller.get_skeletal_mesh()) != object_path(mesh):
        fail("IK Rig preview mesh differs from the sealed mesh")
    if name_string(controller.get_retarget_root()) != root:
        fail(f"IK Rig retarget root is not {root}")
    if name_string(controller.get_root_motion_bone()) != root:
        fail(f"IK Rig root-motion bone is not {root}")
    if len(controller.get_retarget_chains()) != len(chains):
        fail("IK Rig contains extra or missing retarget chains")
    for chain, start, end in chains:
        if name_string(controller.get_retarget_chain_start_bone(chain)) != start:
            fail(f"retarget chain {chain} has the wrong start bone")
        if name_string(controller.get_retarget_chain_end_bone(chain)) != end:
            fail(f"retarget chain {chain} has the wrong end bone")
        if name_string(controller.get_retarget_chain_goal(chain)):
            fail(f"retarget chain {chain} unexpectedly owns an IK goal")


def create_or_validate_ik_rig(path: str, mesh, root: str, chains):
    existing = unreal.EditorAssetLibrary.does_asset_exist(path)
    if existing:
        if not REBUILD:
            fail(f"candidate IK Rig already exists: {path}")
        rig = require_asset(path, unreal.IKRigDefinition)
    else:
        rig = create_asset(
            path,
            unreal.IKRigDefinition,
            unreal.IKRigDefinitionFactory(),
        )
        controller = unreal.IKRigController.get_controller(rig)
        if controller is None:
            fail(f"IK Rig controller is unavailable for {path}")
        controller.set_skeletal_mesh(mesh)
        if not controller.set_retarget_root(root):
            fail(f"could not set retarget root {root} on {path}")
        if not controller.set_root_motion_bone(root):
            fail(f"could not set root-motion bone {root} on {path}")
        for chain, start, end in chains:
            created = name_string(
                controller.add_retarget_chain(chain, start, end, "")
            )
            if created != chain:
                fail(f"Unreal created unexpected chain name {created!r} for {chain}")

    controller = unreal.IKRigController.get_controller(rig)
    if controller is None:
        fail(f"IK Rig controller is unavailable for {path}")
    validate_ik_rig(controller, mesh, root, chains)
    return rig


def pose_names(controller, side) -> set[str]:
    poses = controller.get_retarget_poses(side)
    if hasattr(poses, "keys"):
        return {name_string(name) for name in poses.keys()}
    return {name_string(name) for name in poses}


def create_or_validate_retargeter(source_rig, target_rig, source_mesh, target_mesh):
    existing = unreal.EditorAssetLibrary.does_asset_exist(RETARGETER)
    if existing:
        if not REBUILD:
            fail(f"candidate IK Retargeter already exists: {RETARGETER}")
        asset = require_asset(RETARGETER, unreal.IKRetargeter)
    else:
        asset = create_asset(
            RETARGETER,
            unreal.IKRetargeter,
            unreal.IKRetargetFactory(),
        )

    controller = unreal.IKRetargeterController.get_controller(asset)
    if controller is None:
        fail("IK Retargeter controller is unavailable")
    source = unreal.RetargetSourceOrTarget.SOURCE
    target = unreal.RetargetSourceOrTarget.TARGET

    if not existing:
        controller.set_ik_rig(source, source_rig)
        controller.set_ik_rig(target, target_rig)
        controller.set_preview_mesh(source, source_mesh)
        controller.set_preview_mesh(target, target_mesh)
        controller.add_default_ops()
        controller.assign_ik_rig_to_all_ops(source, source_rig)
        controller.assign_ik_rig_to_all_ops(target, target_rig)
        for chain, _, _ in TARGET_CHAINS:
            if not controller.set_source_chain(chain, chain, ""):
                fail(f"could not map sealed source chain {chain}")

        controller.create_retarget_pose(SOURCE_POSE, source)
        controller.set_current_retarget_pose(SOURCE_POSE, source)
        controller.set_root_offset_in_retarget_pose(unreal.Vector(), source)
        controller.create_retarget_pose(TARGET_POSE, target)
        controller.set_current_retarget_pose(TARGET_POSE, target)
        controller.set_root_offset_in_retarget_pose(unreal.Vector(), target)
        controller.auto_align_bones(
            list(TARGET_ALIGN_BONES),
            unreal.RetargetAutoAlignMethod.CHAIN_TO_CHAIN,
            target,
        )

    if object_path(controller.get_ik_rig(source)) != object_path(source_rig):
        fail("retargeter source IK Rig differs from the sealed asset")
    if object_path(controller.get_ik_rig(target)) != object_path(target_rig):
        fail("retargeter target IK Rig differs from the sealed asset")
    if object_path(controller.get_preview_mesh(source)) != object_path(source_mesh):
        fail("retargeter source preview mesh differs from exact Core27")
    if object_path(controller.get_preview_mesh(target)) != object_path(target_mesh):
        fail("retargeter target preview mesh differs from reviewed MetaHuman")
    if controller.get_num_retarget_ops() != 5:
        fail("retargeter does not contain exactly UE 5.8's five default operations")
    for chain, _, _ in TARGET_CHAINS:
        if name_string(controller.get_source_chain(chain)) != chain:
            fail(f"retargeter chain mapping for {chain} is not exact")
    if SOURCE_POSE not in pose_names(controller, source):
        fail(f"retargeter is missing source pose {SOURCE_POSE}")
    if TARGET_POSE not in pose_names(controller, target):
        fail(f"retargeter is missing target pose {TARGET_POSE}")
    if name_string(controller.get_current_retarget_pose_name(source)) != SOURCE_POSE:
        fail("the reviewed source retarget pose is not current")
    if name_string(controller.get_current_retarget_pose_name(target)) != TARGET_POSE:
        fail("the reviewed target retarget pose is not current")
    if not vector_is_zero(controller.get_root_offset_in_retarget_pose(source)):
        fail("the source retarget pose root offset is not zero")
    if not vector_is_zero(controller.get_root_offset_in_retarget_pose(target)):
        fail("the target retarget pose root offset is not zero")
    return asset


def create_or_validate_profile(adapter, source_mesh, retargeter, mask):
    existing = unreal.EditorAssetLibrary.does_asset_exist(SHARED_PROFILE)
    if existing:
        if not REBUILD:
            fail(f"candidate profile already exists: {SHARED_PROFILE}")
        profile = require_asset(SHARED_PROFILE, unreal.FayArdyRetargetProfile)
    else:
        factory = unreal.DataAssetFactory()
        factory.set_editor_property(
            "data_asset_class", unreal.FayArdyRetargetProfile
        )
        profile = create_asset(
            SHARED_PROFILE,
            unreal.FayArdyRetargetProfile,
            factory,
        )
        profile.set_editor_property("profile_id", unreal.Name(PROFILE_ID))
        profile.set_editor_property("core27_source_mesh", source_mesh)
        profile.set_editor_property("ik_retargeter_asset", retargeter)
        profile.set_editor_property("target_body_blend_mask", mask)
        profile.set_editor_property("source_retarget_pose", unreal.Name(SOURCE_POSE))
        profile.set_editor_property("target_retarget_pose", unreal.Name(TARGET_POSE))
        profile.set_editor_property("maximum_root_offset_centimetres", 20.0)
        # Deliberately absent: the foundation builder never claims the brittle
        # post-process AnimGraph splice is complete or safe.
        profile.set_editor_property("target_post_process_anim_class", None)

    checks = {
        "profile_id": PROFILE_ID,
        "core27_source_mesh": object_path(source_mesh),
        "ik_retargeter_asset": object_path(retargeter),
        "target_body_blend_mask": object_path(mask),
        "source_retarget_pose": SOURCE_POSE,
        "target_retarget_pose": TARGET_POSE,
    }
    for property_name, expected in checks.items():
        value = profile.get_editor_property(property_name)
        actual = (
            object_path(value)
            if property_name.endswith("mesh")
            or property_name.endswith("asset")
            or property_name.endswith("mask")
            else name_string(value)
        )
        if actual != expected:
            fail(f"shared profile {property_name} differs from sealed value")
    if profile.get_editor_property("target_post_process_anim_class") is not None:
        fail(
            "the foundation profile unexpectedly claims a post-process class; "
            "use the separate reviewed graph gate"
        )
    if "LOCKED_IN_PLACE" not in str(
        profile.get_editor_property("root_motion_policy")
    ).upper():
        fail("the shared profile must keep root motion locked in place")
    if abs(
        float(profile.get_editor_property("maximum_root_offset_centimetres"))
        - 20.0
    ) > 1e-6:
        fail("the shared profile root-offset bound differs from 20 cm")
    return profile


def validate_unfinalized_postprocess_if_present(adapter) -> None:
    if not unreal.EditorAssetLibrary.does_asset_exist(POST_PROCESS_ANIM_BP):
        return
    blueprint = require_asset(POST_PROCESS_ANIM_BP, unreal.AnimBlueprint)
    generated_class = blueprint.generated_class()
    if generated_class is None:
        fail("the reviewed post-process candidate has no generated class")
    valid, reason = unpack_reason(
        adapter.validate_v30_post_process_inputs(
            post_process_anim_class=generated_class
        )
    )
    if not valid:
        fail(f"the reviewed post-process input preflight failed: {reason}")
    unreal.log_warning(
        "The candidate post-process inputs passed the reflected v2 preflight; "
        "AnimGraph topology and evaluation order still require manual review."
    )


def duplicate_and_bind_characters(adapter, profile):
    candidates = []
    for name, paths in CHARACTERS.items():
        require_asset(paths["source"], unreal.Blueprint)
        exists = unreal.EditorAssetLibrary.does_asset_exist(paths["candidate"])
        if exists:
            if not REBUILD:
                fail(f"candidate {name} Blueprint already exists")
            candidate = require_asset(paths["candidate"], unreal.Blueprint)
        else:
            candidate = unreal.EditorAssetLibrary.duplicate_asset(
                paths["source"], paths["candidate"]
            )
            if candidate is None or not isinstance(candidate, unreal.Blueprint):
                fail(f"could not duplicate the reviewed {name} Blueprint")

        ok, reason = unpack_reason(
            adapter.ensure_exactly_one_retarget_binding(
                candidate_blueprint=candidate,
                shared_profile=profile,
                reviewed_rebuild=REBUILD,
            )
        )
        if not ok:
            fail(f"{name} binding failed: {reason}")
        candidates.append(candidate)
    return candidates


def save_foundation() -> None:
    dirty_maps = unreal.EditorLoadingAndSavingUtils.get_dirty_map_packages()
    if dirty_maps:
        fail("the ARDY foundation unexpectedly dirtied a map package")
    dirty = unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()
    unexpected = [
        str(package.get_path_name())
        for package in dirty
        if not str(package.get_path_name()).startswith(f"{CANDIDATE_ROOT}/")
    ]
    if unexpected:
        fail(
            "the builder dirtied content outside the sealed candidate:\n  "
            + "\n  ".join(unexpected)
        )
    if not dirty and REBUILD:
        return
    if not dirty:
        fail("the fresh foundation produced no dirty packages")
    if not unreal.EditorLoadingAndSavingUtils.save_packages(dirty, True):
        fail("Unreal did not save every candidate foundation package")


def build_foundation() -> None:
    ensure_clean_editor_state()
    ensure_destination_policy()

    adapter = getattr(unreal, "FayArdyRetargetAssetLibrary", None)
    if adapter is None:
        fail("the Fay MetaHuman Editor Tools v30 adapter is not loaded")
    validate_unfinalized_postprocess_if_present(adapter)

    source_mesh = require_asset(SOURCE_MESH, unreal.SkeletalMesh)
    source_target_mesh = require_asset(
        SOURCE_TARGET_BODY_MESH, unreal.SkeletalMesh
    )
    source_target_skeleton = require_asset(
        SOURCE_TARGET_BODY_SKELETON, unreal.Skeleton
    )
    if object_path(source_target_mesh.get_editor_property("skeleton")) != object_path(
        source_target_skeleton
    ):
        fail("Ada's reviewed body mesh does not use the sealed shared body skeleton")
    for paths in CHARACTERS.values():
        require_asset(paths["source"], unreal.Blueprint)

    valid, reason = unpack_reason(
        adapter.validate_exact_core27_source(source_mesh=source_mesh)
    )
    if not valid:
        fail(f"imported Core27 source is not exact: {reason}")

    target_skeleton = duplicate_or_validate_asset(
        SOURCE_TARGET_BODY_SKELETON,
        CANDIDATE_TARGET_BODY_SKELETON,
        unreal.Skeleton,
    )
    target_mesh = duplicate_or_validate_asset(
        SOURCE_TARGET_BODY_MESH,
        CANDIDATE_TARGET_BODY_MESH,
        unreal.SkeletalMesh,
    )
    rebound, reason = unpack_reason(
        adapter.rebind_private_target_mesh_skeleton(
            candidate_body_mesh=target_mesh,
            candidate_skeleton=target_skeleton,
        )
    )
    if not rebound:
        fail(f"could not isolate the target preview mesh/skeleton: {reason}")

    source_rig = create_or_validate_ik_rig(
        SOURCE_IK_RIG, source_mesh, "Hips", SOURCE_CHAINS
    )
    target_rig = create_or_validate_ik_rig(
        TARGET_IK_RIG, target_mesh, "pelvis", TARGET_CHAINS
    )
    retargeter = create_or_validate_retargeter(
        source_rig, target_rig, source_mesh, target_mesh
    )

    mask, reason = unpack_reason(
        adapter.ensure_body_only_blend_mask(
            target_body_mesh=target_mesh,
            reviewed_rebuild=REBUILD,
        )
    )
    if mask is None:
        fail(f"could not create/validate the body-only Blend Mask: {reason}")

    profile = create_or_validate_profile(adapter, source_mesh, retargeter, mask)
    duplicate_and_bind_characters(adapter, profile)
    save_foundation()

    unreal.log_warning(
        "FAY_ARDY_V30_FOUNDATION_BUILT=1: exact Core27/source-target IK Rigs, "
        "five-op retargeter, named poses, body-only mask, fail-closed draft "
        "profile, and isolated Ada/Aoi candidates were saved."
    )
    fail(
        "the safe foundation is complete, but v30 is intentionally NOT runtime "
        "ready. The fixed post-process AnimBP graph has not been built and "
        "topology-reviewed; TargetPostProcessAnimClass remains unset."
    )


if __name__ == "__main__":
    build_foundation()
