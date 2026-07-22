"""Read-only inventory of the acquired Free Casual Girl Sample asset.

This script runs only in the sealed Fab acquisition project.  It inspects the
seller's fixed source paths and emits machine-readable ``FAY_FAB_INVENTORY_*``
markers.  It never saves, renames, duplicates, exports, or renders an asset.
"""

from __future__ import annotations

import os

import unreal


SOURCE_ROOT = "/Game/Sample"
PRODUCT_ROOTS = (
    f"{SOURCE_ROOT}/Meshes",
    f"{SOURCE_ROOT}/Mat",
    f"{SOURCE_ROOT}/Tex",
)
SOURCE_BLUEPRINT = (
    f"{SOURCE_ROOT}/Demo/ThirdPersonTemplate/ThirdPerson/Blueprints/"
    "BP_ThirdPersonCharacter"
)
BASELINE_ENVIRONMENT = "FAY_FAB_STAGING_BASELINE_VERIFIED"
EXPECTED_MESHES = (
    "AB_Jiggle",
    "PA_Coat",
    "PA_Gameplay",
    "PA_HairSim",
    "SK_Body",
    "SK_Complete",
    "SK_Hair_1",
    "SK_Hair_2",
    "SK_Pants",
    "SK_Shoes",
    "SK_Shoes_Socks",
    "SK_Shorts",
    "SK_Top_1",
    "SK_Top_2",
    "SK_Top_3",
    "SK_Top_4",
    "SK_Underwear",
    "Sk_Arms",
    "Sk_Legs",
)
EXPECTED_ARKIT = {
    "browdown_l",
    "browdown_r",
    "browinnerup",
    "browouterup_l",
    "browouterup_r",
    "cheekpuff",
    "cheeksquint_l",
    "cheeksquint_r",
    "eyeblink_l",
    "eyeblink_r",
    "eyelookdown_l",
    "eyelookdown_r",
    "eyelookin_l",
    "eyelookin_r",
    "eyelookout_l",
    "eyelookout_r",
    "eyelookup_l",
    "eyelookup_r",
    "eyesquint_l",
    "eyesquint_r",
    "eyewide_l",
    "eyewide_r",
    "jawforward",
    "jawleft",
    "jawopen",
    "jawright",
    "mouthclose",
    "mouthdimple_l",
    "mouthdimple_r",
    "mouthfrown_l",
    "mouthfrown_r",
    "mouthfunnel",
    "mouthleft",
    "mouthlowerdown_l",
    "mouthlowerdown_r",
    "mouthpress_l",
    "mouthpress_r",
    "mouthpucker",
    "mouthright",
    "mouthrolllower",
    "mouthrollupper",
    "mouthshruglower",
    "mouthshrugupper",
    "mouthsmile_l",
    "mouthsmile_r",
    "mouthstretch_l",
    "mouthstretch_r",
    "mouthupperup_l",
    "mouthupperup_r",
    "nosesneer_l",
    "nosesneer_r",
    "tongueout",
}


def emit(name: str, value: object) -> None:
    unreal.log(f"FAY_FAB_INVENTORY_{name}={value}")


def fail(message: str) -> None:
    unreal.log_error(f"FAY_FAB_INVENTORY_ERROR={message}")
    raise RuntimeError(message)


def dirty_packages() -> set[str]:
    return {
        str(package.get_path_name())
        for package in (
            unreal.EditorLoadingAndSavingUtils.get_dirty_map_packages()
            + unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()
        )
    }


def skeletal_mesh_for(component):
    for property_name in ("skeletal_mesh_asset", "skeletal_mesh"):
        try:
            value = component.get_editor_property(property_name)
            if value is not None:
                return value
        except Exception:
            pass
    return None


def morph_names(mesh) -> list[str]:
    try:
        targets = mesh.get_editor_property("morph_targets")
    except Exception as error:
        fail(f"could not inspect morph targets for {mesh.get_path_name()}: {error}")
    if targets is None:
        fail(f"morph target array is missing for {mesh.get_path_name()}")
    names = [str(target.get_name()).strip().lower() for target in targets]
    if any(not name for name in names) or len(names) != len(set(names)):
        fail(f"invalid morph target names on {mesh.get_path_name()}")
    return sorted(names)


def load_required(path: str, expected_class):
    asset = unreal.load_asset(path)
    if asset is None or not isinstance(asset, expected_class):
        fail(f"required {expected_class.__name__} is missing: {path}")
    return asset


def asset_name(path: object) -> str:
    object_path = str(path).split(".", 1)[0]
    return object_path.rsplit("/", 1)[-1]


def verify_epic_hierarchy(mesh) -> int:
    expected = {
        "pelvis": "root",
        "spine_01": "pelvis",
        "spine_02": "spine_01",
        "spine_03": "spine_02",
        "clavicle_l": "spine_03",
        "upperarm_l": "clavicle_l",
        "lowerarm_l": "upperarm_l",
        "hand_l": "lowerarm_l",
        "clavicle_r": "spine_03",
        "upperarm_r": "clavicle_r",
        "lowerarm_r": "upperarm_r",
        "hand_r": "lowerarm_r",
        "thigh_l": "pelvis",
        "calf_l": "thigh_l",
        "foot_l": "calf_l",
        "ball_l": "foot_l",
        "thigh_r": "pelvis",
        "calf_r": "thigh_r",
        "foot_r": "calf_r",
        "ball_r": "foot_r",
    }
    subsystem = unreal.get_editor_subsystem(unreal.SkeletalMeshEditorSubsystem)
    if subsystem is None:
        fail("SkeletalMeshEditorSubsystem is unavailable")
    for bone, expected_parent in expected.items():
        try:
            actual_parent = str(subsystem.get_bone_parent(mesh, bone)).lower()
        except Exception as error:
            fail(f"could not inspect parent of {bone}: {error}")
        if actual_parent != expected_parent:
            fail(
                f"Epic Skeleton mismatch for {bone}: expected "
                f"{expected_parent}, found {actual_parent}"
            )
    return len(expected)


if os.environ.get(BASELINE_ENVIRONMENT) != "1":
    fail("the sealed non-content baseline was not verified")

dirty_before = dirty_packages()
root_assets: dict[str, list[str]] = {}
for root in PRODUCT_ROOTS:
    paths = sorted(
        str(value)
        for value in unreal.EditorAssetLibrary.list_assets(
            root, recursive=True, include_folder=False
        )
    )
    if not paths:
        fail(f"acquired product root is empty: {root}")
    root_assets[root] = paths
    emit(f"{root.rsplit('/', 1)[-1].upper()}_ASSET_COUNT", len(paths))

mesh_names = {asset_name(path) for path in root_assets[f"{SOURCE_ROOT}/Meshes"]}
missing_meshes = sorted(set(EXPECTED_MESHES) - mesh_names)
if missing_meshes:
    fail(f"expected product assets are missing: {missing_meshes}")
emit("EXPECTED_PRODUCT_ASSETS", "OK")

blueprint = load_required(SOURCE_BLUEPRINT, unreal.Blueprint)
generated_class = blueprint.generated_class()
if generated_class is None:
    fail("the source character Blueprint has no generated class")
cdo = unreal.get_default_object(generated_class)
if cdo is None:
    fail("the source character Blueprint has no class default object")
emit("SOURCE_BLUEPRINT", blueprint.get_path_name())
emit("SOURCE_CLASS", generated_class.get_path_name())

components = sorted(
    cdo.get_components_by_class(unreal.SkeletalMeshComponent),
    key=lambda value: value.get_name().removesuffix("_GEN_VARIABLE"),
)
if not components:
    fail("the source character Blueprint has no skeletal mesh components")
emit("SKELETAL_COMPONENT_COUNT", len(components))
for index, component in enumerate(components):
    name = component.get_name().removesuffix("_GEN_VARIABLE")
    mesh = skeletal_mesh_for(component)
    emit(f"COMPONENT_{index}_NAME", name)
    emit(
        f"COMPONENT_{index}_MESH",
        mesh.get_path_name() if mesh is not None else "none",
    )

mesh_subsystem = unreal.get_editor_subsystem(unreal.SkeletalMeshEditorSubsystem)
if mesh_subsystem is None:
    fail("SkeletalMeshEditorSubsystem is unavailable")

product_mesh_paths = sorted(
    path
    for path in root_assets[f"{SOURCE_ROOT}/Meshes"]
    if isinstance(unreal.load_asset(path), unreal.SkeletalMesh)
)
if len(product_mesh_paths) != 15:
    fail(f"expected 15 product skeletal meshes, found {len(product_mesh_paths)}")

skeletons: set[str] = set()
arkit_union: set[str] = set()
for index, path in enumerate(product_mesh_paths):
    mesh = load_required(path, unreal.SkeletalMesh)
    names = morph_names(mesh)
    arkit_union.update(EXPECTED_ARKIT.intersection(names))
    try:
        skeleton = mesh.get_editor_property("skeleton")
        physics_asset = mesh.get_editor_property("physics_asset")
        materials = mesh.get_editor_property("materials")
        lod_count = mesh_subsystem.get_lod_count(mesh)
    except Exception as error:
        fail(f"could not inspect skeletal mesh metadata for {path}: {error}")
    if skeleton is None or lod_count <= 0:
        fail(f"skeletal mesh has no skeleton or LOD: {path}")
    skeletons.add(str(skeleton.get_path_name()))
    emit(f"MESH_{index}_NAME", mesh.get_name())
    emit(f"MESH_{index}_MORPH_COUNT", len(names))
    emit(f"MESH_{index}_LOD_COUNT", lod_count)
    emit(
        f"MESH_{index}_PHYSICS",
        physics_asset.get_path_name() if physics_asset is not None else "none",
    )
    emit(f"MESH_{index}_MATERIAL_COUNT", len(materials))

if len(skeletons) != 1:
    fail(f"product skeletal meshes do not share one skeleton: {sorted(skeletons)}")
emit("SHARED_SKELETON", next(iter(skeletons)))

body = load_required(f"{SOURCE_ROOT}/Meshes/SK_Body", unreal.SkeletalMesh)
complete = load_required(f"{SOURCE_ROOT}/Meshes/SK_Complete", unreal.SkeletalMesh)
body_morphs = set(morph_names(body))
complete_morphs = set(morph_names(complete))
missing_body = sorted(EXPECTED_ARKIT - body_morphs)
missing_complete = sorted(EXPECTED_ARKIT - complete_morphs)
emit("ARKIT_EXPECTED_COUNT", len(EXPECTED_ARKIT))
emit("ARKIT_BODY_FOUND_COUNT", len(EXPECTED_ARKIT & body_morphs))
emit("ARKIT_COMPLETE_FOUND_COUNT", len(EXPECTED_ARKIT & complete_morphs))
emit("ARKIT_UNION_FOUND_COUNT", len(arkit_union))
emit("ARKIT_BODY_MISSING", ",".join(missing_body) if missing_body else "none")
emit(
    "ARKIT_COMPLETE_MISSING",
    ",".join(missing_complete) if missing_complete else "none",
)
emit("EPIC_BODY_BONES_VERIFIED", verify_epic_hierarchy(body))

if dirty_packages() != dirty_before:
    fail("read-only inventory changed the Editor dirty-package set")

emit("BODY_COMPLETENESS", "manual_review_required")
emit("FULLY_UNCLOTHED", "disabled")
emit("NOAI_BOUNDARY", "deterministic_retarget_only")
emit("COMPLETE", "OK")
