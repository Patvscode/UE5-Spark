"""Read-only inventory of the acquired Free Casual Girl Sample asset.

This script runs only in the sealed Fab acquisition project.  It inspects the
seller's fixed source paths and emits machine-readable ``FAY_FAB_INVENTORY_*``
markers.  It never saves, renames, duplicates, exports, or renders an asset.
"""

from __future__ import annotations

import os
from pathlib import Path
import re

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
SOURCE_BLUEPRINT_OBJECT = f"{SOURCE_BLUEPRINT}.BP_ThirdPersonCharacter"
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
SKELETAL_MESHES = (
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
    "browdownleft",
    "browdownright",
    "browinnerup",
    "browouterupleft",
    "browouterupright",
    "cheekpuff",
    "cheeksquintleft",
    "cheeksquintright",
    "eyeblinkleft",
    "eyeblinkright",
    "eyelookdownleft",
    "eyelookdownright",
    "eyelookinleft",
    "eyelookinright",
    "eyelookoutleft",
    "eyelookoutright",
    "eyelookupleft",
    "eyelookupright",
    "eyesquintleft",
    "eyesquintright",
    "eyewideleft",
    "eyewideright",
    "jawforward",
    "jawleft",
    "jawopen",
    "jawright",
    "mouthclose",
    "mouthdimpleleft",
    "mouthdimpleright",
    "mouthfrownleft",
    "mouthfrownright",
    "mouthfunnel",
    "mouthleft",
    "mouthlowerdownleft",
    "mouthlowerdownright",
    "mouthpressleft",
    "mouthpressright",
    "mouthpucker",
    "mouthright",
    "mouthrolllower",
    "mouthrollupper",
    "mouthshruglower",
    "mouthshrugupper",
    "mouthsmileleft",
    "mouthsmileright",
    "mouthstretchleft",
    "mouthstretchright",
    "mouthupperupleft",
    "mouthupperupright",
    "nosesneerleft",
    "nosesneerright",
    "tongueout",
}
EXPECTED_BODY_BONES = {
    "root",
    "pelvis",
    "spine_01",
    "spine_02",
    "spine_03",
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
}
IDENTIFIER_PATTERN = re.compile(rb"[A-Za-z][A-Za-z0-9_]{2,63}")
MAX_PACKAGE_BYTES = 64 * 1024 * 1024


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


def asset_name(path: object) -> str:
    object_path = str(path).split(".", 1)[0]
    return object_path.rsplit("/", 1)[-1]


def package_identifiers(name: str) -> set[str]:
    content_root = Path(unreal.Paths.project_content_dir()).resolve()
    package = content_root / "Sample" / "Meshes" / f"{name}.uasset"
    if package.is_symlink() or not package.is_file():
        fail(f"required package file is missing or unsafe: {name}")
    size = package.stat().st_size
    if size <= 0 or size > MAX_PACKAGE_BYTES:
        fail(f"required package has an invalid size: {name}")
    try:
        data = package.read_bytes()
    except OSError as error:
        fail(f"could not read required package metadata for {name}: {error}")
    return {
        match.group(0).decode("ascii").lower()
        for match in IDENTIFIER_PATTERN.finditer(data)
    }


if os.environ.get(BASELINE_ENVIRONMENT) != "1":
    fail("the sealed non-content baseline was not verified")

if os.environ.get("FAY_FAB_EXPECT_OFFLINE") == "1":
    try:
        enabled_plugins = set(unreal.PluginBlueprintLibrary.get_enabled_plugin_names())
    except Exception as error:
        fail(f"could not inspect enabled plugins in offline mode: {error}")
    required_plugins = {"PythonScriptPlugin", "EditorScriptingUtilities", "ChaosCloth"}
    if "Fab" in enabled_plugins or not required_plugins.issubset(enabled_plugins):
        fail("offline plugin state is not the reviewed Fab-disabled set")
    emit("OFFLINE_PLUGINS", "OK")

dirty_before = dirty_packages()
registry = unreal.AssetRegistryHelpers.get_asset_registry()
try:
    registry.scan_paths_synchronous(
        [SOURCE_ROOT],
        force_rescan=True,
        ignore_deny_list_scan_filters=False,
    )
except Exception as error:
    fail(f"could not rescan the acquired asset root: {error}")

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
emit("MESH_REGISTRY_NAMES", ",".join(sorted(mesh_names)))
missing_meshes = sorted(set(EXPECTED_MESHES) - mesh_names)
if missing_meshes:
    fail(f"expected product assets are missing: {missing_meshes}")
emit("EXPECTED_PRODUCT_ASSETS", "OK")

try:
    blueprint_data = registry.get_asset_by_object_path(SOURCE_BLUEPRINT_OBJECT)
    blueprint_class = str(blueprint_data.asset_class_path)
    blueprint_package = str(blueprint_data.package_name)
except Exception as error:
    fail(f"could not inspect the source character Blueprint metadata: {error}")
if not blueprint_package or "Blueprint" not in blueprint_class:
    fail("the fixed source character Blueprint is absent from the asset registry")
emit("SOURCE_BLUEPRINT", SOURCE_BLUEPRINT_OBJECT)
emit("SOURCE_BLUEPRINT_PACKAGE", blueprint_package)
emit("SOURCE_BLUEPRINT_CLASS", blueprint_class)
emit("SOURCE_BLUEPRINT_COMPONENTS", "graphical_review_required")

for index, name in enumerate(SKELETAL_MESHES):
    object_path = f"{SOURCE_ROOT}/Meshes/{name}.{name}"
    try:
        data = registry.get_asset_by_object_path(object_path)
        asset_class = str(data.asset_class_path)
    except Exception as error:
        fail(f"could not inspect skeletal mesh registry data for {name}: {error}")
    if "SkeletalMesh" not in asset_class:
        fail(f"registered product asset is not a SkeletalMesh: {name}")
    emit(f"MESH_{index}_NAME", name)
    emit(f"MESH_{index}_CLASS", asset_class)
    emit(f"MESH_{index}_LOD_COUNT", "graphical_review_required")
    emit(f"MESH_{index}_PHYSICS", "graphical_review_required")
    emit(f"MESH_{index}_MATERIAL_COUNT", "graphical_review_required")

body_identifiers = package_identifiers("SK_Body")
complete_identifiers = package_identifiers("SK_Complete")
missing_body = sorted(EXPECTED_ARKIT - body_identifiers)
missing_complete = sorted(EXPECTED_ARKIT - complete_identifiers)
emit("ARKIT_EXPECTED_COUNT", len(EXPECTED_ARKIT))
emit("ARKIT_BODY_FOUND_COUNT", len(EXPECTED_ARKIT & body_identifiers))
emit("ARKIT_COMPLETE_FOUND_COUNT", len(EXPECTED_ARKIT & complete_identifiers))
emit("ARKIT_BODY_MISSING", ",".join(missing_body) if missing_body else "none")
emit(
    "ARKIT_COMPLETE_MISSING",
    ",".join(missing_complete) if missing_complete else "none",
)
missing_bones = sorted(EXPECTED_BODY_BONES - body_identifiers)
emit("EPIC_BODY_BONE_NAMES_EXPECTED", len(EXPECTED_BODY_BONES))
emit("EPIC_BODY_BONE_NAMES_FOUND", len(EXPECTED_BODY_BONES & body_identifiers))
emit("EPIC_BODY_BONE_NAMES_MISSING", ",".join(missing_bones) if missing_bones else "none")
emit("EPIC_BODY_HIERARCHY", "graphical_review_required")
emit("SHARED_SKELETON", "graphical_review_required")

if dirty_packages() != dirty_before:
    fail("read-only inventory changed the Editor dirty-package set")

emit("BODY_COMPLETENESS", "manual_review_required")
emit("FULLY_UNCLOTHED", "disabled")
emit("NOAI_BOUNDARY", "deterministic_retarget_only")
emit("COMPLETE", "OK")
