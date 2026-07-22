"""Read-only Unreal Editor audit for the locally acquired Casual Girl asset.

Run only after the Fab asset has been added to an isolated project directory.
The script does not save, rename, duplicate, or modify any package.  It emits a
machine-readable set of ``FAY_FAB_AUDIT_*`` log markers used to decide whether
the pending wardrobe profile can be promoted.
"""

from __future__ import annotations

import os
from pathlib import Path

import unreal


REVIEWED_ROOT = "/Game/FayFab/CasualGirl"
ASSET_ENVIRONMENT = "FAY_FAB_CHARACTER_ASSET"
BASELINE_ENVIRONMENT = "FAY_FAB_STAGING_BASELINE_VERIFIED"
ALLOWED_CONTENT_EXTENSIONS = {".uasset", ".umap", ".ubulk", ".uexp"}
EXPECTED_ARKIT = {
    "browdown_l", "browdown_r", "browinnerup", "browouterup_l",
    "browouterup_r", "cheekpuff", "cheeksquint_l", "cheeksquint_r",
    "eyeblink_l", "eyeblink_r", "eyelookdown_l", "eyelookdown_r",
    "eyelookin_l", "eyelookin_r", "eyelookout_l", "eyelookout_r",
    "eyelookup_l", "eyelookup_r", "eyesquint_l", "eyesquint_r",
    "eyewide_l", "eyewide_r", "jawforward", "jawleft", "jawopen",
    "jawright", "mouthclose", "mouthdimple_l", "mouthdimple_r",
    "mouthfrown_l", "mouthfrown_r", "mouthfunnel", "mouthleft",
    "mouthlowerdown_l", "mouthlowerdown_r", "mouthpress_l",
    "mouthpress_r", "mouthpucker", "mouthright", "mouthrolllower",
    "mouthrollupper", "mouthshruglower", "mouthshrugupper", "mouthsmile_l",
    "mouthsmile_r", "mouthstretch_l", "mouthstretch_r", "mouthupperup_l",
    "mouthupperup_r", "nosesneer_l", "nosesneer_r", "tongueout",
}


def emit(name, value):
    unreal.log(f"FAY_FAB_AUDIT_{name}={value}")


def fail(message):
    unreal.log_error(f"FAY_FAB_AUDIT_ERROR={message}")
    raise RuntimeError(message)


def stable_component_name(component):
    return component.get_name().removesuffix("_GEN_VARIABLE")


def skeletal_mesh_for(component):
    for property_name in ("skeletal_mesh_asset", "skeletal_mesh"):
        try:
            value = component.get_editor_property(property_name)
            if value is not None:
                return value
        except Exception:
            pass
    return None


def morph_names(mesh):
    try:
        targets = mesh.get_editor_property("morph_targets")
    except Exception as error:
        fail(f"UE 5.8 morph_targets reflection is unavailable: {error}")
    if targets is None:
        fail("UE 5.8 returned no morph_targets array")
    names = []
    for target in targets:
        if target is None:
            fail("morph_targets contains a null object")
        name = str(target.get_name()).strip().lower()
        if not name:
            fail("morph_targets contains an unnamed object")
        names.append(name)
    if len(names) != len(set(names)):
        fail("skeletal mesh contains duplicate morph target names")
    return sorted(names)


def dirty_packages():
    return {
        str(package.get_path_name())
        for package in (
            unreal.EditorLoadingAndSavingUtils.get_dirty_map_packages()
            + unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()
        )
    }


def package_dependencies(asset_paths):
    try:
        registry = unreal.AssetRegistryHelpers.get_asset_registry()
        options = unreal.AssetRegistryDependencyOptions(
            include_soft_package_references=True,
            include_hard_package_references=True,
            include_searchable_names=True,
            include_soft_management_references=True,
            include_hard_management_references=True,
        )
    except Exception as error:
        fail(f"Asset Registry dependency API is unavailable: {error}")

    packages = set()
    classes = set()
    for object_path in asset_paths:
        try:
            data = registry.get_asset_by_object_path(str(object_path))
            package_name = str(data.package_name)
            class_path = str(data.asset_class_path)
            dependencies = registry.get_dependencies(package_name, options)
        except Exception as error:
            fail(f"could not inspect dependencies for {object_path}: {error}")
        if not package_name.startswith(REVIEWED_ROOT + "/"):
            fail(f"asset package escaped the reviewed root: {package_name}")
        classes.add(class_path)
        packages.update(str(value) for value in dependencies)
    return sorted(packages), sorted(classes)


def verify_epic_body_hierarchy(mesh):
    expected_parents = {
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
    try:
        subsystem = unreal.get_editor_subsystem(unreal.SkeletalMeshEditorSubsystem)
    except Exception as error:
        fail(f"SkeletalMeshEditorSubsystem is unavailable: {error}")
    if subsystem is None:
        fail("SkeletalMeshEditorSubsystem is unavailable")
    for bone, expected_parent in expected_parents.items():
        try:
            actual_parent = str(subsystem.get_bone_parent(mesh, bone))
        except Exception as error:
            fail(f"could not inspect Epic Skeleton bone {bone}: {error}")
        if actual_parent.lower() != expected_parent:
            fail(
                f"Epic Skeleton hierarchy mismatch for {bone}: "
                f"expected {expected_parent}, found {actual_parent}"
            )
    return tuple(expected_parents)


def verify_reviewed_content_files():
    content_root = Path(unreal.Paths.project_content_dir()).resolve()
    reviewed = content_root / "FayFab" / "CasualGirl"
    if not reviewed.is_dir() or reviewed.is_symlink():
        fail("reviewed project Content directory is missing or symlinked")
    file_count = 0
    for directory, directory_names, file_names in os.walk(reviewed, followlinks=False):
        directory_path = Path(directory)
        for name in tuple(directory_names):
            if (directory_path / name).is_symlink():
                fail("reviewed Content contains a symlinked directory")
        for name in file_names:
            candidate = directory_path / name
            if candidate.is_symlink() or not candidate.is_file():
                fail("reviewed Content contains a non-regular file")
            if candidate.suffix.lower() not in ALLOWED_CONTENT_EXTENSIONS:
                fail(f"reviewed Content contains unexpected file type: {candidate.name}")
            file_count += 1
    if file_count == 0:
        fail("reviewed project Content directory is empty")
    return file_count


asset_path = os.environ.get(ASSET_ENVIRONMENT, "").strip()
if not asset_path or not asset_path.startswith(REVIEWED_ROOT + "/"):
    fail(
        f"{ASSET_ENVIRONMENT} must name one Blueprint below "
        f"{REVIEWED_ROOT}/; nothing was inspected"
    )
if os.environ.get(BASELINE_ENVIRONMENT) != "1":
    fail(
        "the disposable staging non-content manifest must pass verification "
        f"before setting {BASELINE_ENVIRONMENT}=1"
    )

# Snapshot before loading any imported package so a 5.8 upgrade/compile mutation
# cannot hide inside the audit's own initial state.
dirty_before = dirty_packages()

asset = unreal.load_asset(asset_path)
if asset is None:
    fail(f"could not load {asset_path}")
generated_class = getattr(asset, "generated_class", lambda: None)()
if generated_class is None:
    fail("the reviewed asset is not a generated Blueprint class")
cdo = unreal.get_default_object(generated_class)
if cdo is None:
    fail("the reviewed Blueprint has no class default object")

all_assets = unreal.EditorAssetLibrary.list_assets(
    REVIEWED_ROOT,
    recursive=True,
    include_folder=False,
)
if not all_assets:
    fail(f"no assets were found below {REVIEWED_ROOT}")
outside = [path for path in all_assets if not str(path).startswith(REVIEWED_ROOT + "/")]
if outside:
    fail("asset registry returned a path outside the reviewed root")

emit("ASSET", asset.get_path_name())
emit("CLASS", generated_class.get_path_name())
emit("ASSET_COUNT", len(all_assets))
emit("CONTENT_FILE_COUNT", verify_reviewed_content_files())

dependencies, asset_classes = package_dependencies(all_assets)
outside_game = sorted(
    value
    for value in dependencies
    if value.startswith("/Game/") and not value.startswith(REVIEWED_ROOT + "/")
)
if outside_game:
    fail(f"reviewed assets depend on packages outside their /Game root: {outside_game}")
plugin_dependencies = sorted(
    value
    for value in dependencies
    if not value.startswith((REVIEWED_ROOT + "/", "/Engine/", "/Script/"))
)
emit("DEPENDENCY_COUNT", len(dependencies))
emit("PLUGIN_DEPENDENCIES", ",".join(plugin_dependencies) if plugin_dependencies else "none")
emit("ASSET_CLASSES", ",".join(asset_classes))

components = sorted(
    cdo.get_components_by_class(unreal.SkeletalMeshComponent),
    key=stable_component_name,
)
if not components:
    fail("the Blueprint has no skeletal mesh components")
emit("SKELETAL_COMPONENT_COUNT", len(components))

all_morphs = set()
skeleton_paths = set()
hierarchy_candidate = None
for index, component in enumerate(components):
    name = stable_component_name(component)
    mesh = skeletal_mesh_for(component)
    mesh_path = mesh.get_path_name() if mesh is not None else "missing"
    names = morph_names(mesh) if mesh is not None else []
    all_morphs.update(names)
    emit(f"COMPONENT_{index}_NAME", name)
    emit(f"COMPONENT_{index}_MESH", mesh_path)
    emit(f"COMPONENT_{index}_MORPH_COUNT", len(names))
    if mesh is not None:
        try:
            skeleton = mesh.get_editor_property("skeleton")
        except Exception:
            skeleton = None
        emit(
            f"COMPONENT_{index}_SKELETON",
            skeleton.get_path_name() if skeleton is not None else "missing",
        )
        if skeleton is None:
            fail(f"skeletal component {name} has no skeleton")
        skeleton_paths.add(str(skeleton.get_path_name()))
        try:
            lod_count = unreal.SkeletalMeshEditorSubsystem.get_lod_count(mesh)
        except Exception as error:
            fail(f"could not read LOD count for {mesh_path}: {error}")
        if lod_count <= 0:
            fail(f"skeletal mesh has no LODs: {mesh_path}")
        emit(f"COMPONENT_{index}_LOD_COUNT", lod_count)
        try:
            physics_asset = mesh.get_editor_property("physics_asset")
            materials = mesh.get_editor_property("materials")
        except Exception as error:
            fail(f"could not inspect physics/material properties for {mesh_path}: {error}")
        emit(
            f"COMPONENT_{index}_PHYSICS_ASSET",
            physics_asset.get_path_name() if physics_asset is not None else "none",
        )
        emit(f"COMPONENT_{index}_MATERIAL_COUNT", len(materials))
        if hierarchy_candidate is None or len(names) > hierarchy_candidate[0]:
            hierarchy_candidate = (len(names), mesh)

if len(skeleton_paths) != 1:
    fail(f"modular skeletal components do not share one skeleton: {sorted(skeleton_paths)}")
if hierarchy_candidate is None:
    fail("no skeletal mesh was available for hierarchy inspection")
epic_bones = verify_epic_body_hierarchy(hierarchy_candidate[1])
emit("EPIC_BODY_BONES_VERIFIED", len(epic_bones))

missing_arkit = sorted(EXPECTED_ARKIT - all_morphs)
emit("ARKIT_EXPECTED_COUNT", len(EXPECTED_ARKIT))
emit("ARKIT_FOUND_COUNT", len(EXPECTED_ARKIT & all_morphs))
emit("ARKIT_MISSING", ",".join(missing_arkit) if missing_arkit else "none")

dirty_after = dirty_packages()
if dirty_after != dirty_before:
    fail("read-only audit changed the Editor dirty-package set")

emit("BODY_COMPLETENESS", "manual_review_required")
emit("UNDERWEAR_IMPLEMENTATION", "manual_review_required")
emit("LINUX_ARM64_SUPPORT", "cook_required")
emit("COMPLETE", "OK")
