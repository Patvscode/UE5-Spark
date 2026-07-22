"""Read-only Unreal Editor audit for the locally acquired Casual Girl asset.

Run only after the Fab asset has been added to an isolated project directory.
The script does not save, rename, duplicate, or modify any package.  It emits a
machine-readable set of ``FAY_FAB_AUDIT_*`` log markers used to decide whether
the pending wardrobe profile can be promoted.
"""

from __future__ import annotations

import os

import unreal


REVIEWED_ROOT = "/Game/FayFab/CasualGirl"
ASSET_ENVIRONMENT = "FAY_FAB_CHARACTER_ASSET"
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
        return sorted(str(name).lower() for name in mesh.get_all_morph_target_names())
    except Exception:
        return []


asset_path = os.environ.get(ASSET_ENVIRONMENT, "").strip()
if not asset_path or not asset_path.startswith(REVIEWED_ROOT + "/"):
    fail(
        f"{ASSET_ENVIRONMENT} must name one Blueprint below "
        f"{REVIEWED_ROOT}/; nothing was inspected"
    )

asset = unreal.load_asset(asset_path)
if asset is None:
    fail(f"could not load {asset_path}")
generated_class = getattr(asset, "generated_class", lambda: None)()
if generated_class is None:
    fail("the reviewed asset is not a generated Blueprint class")
cdo = unreal.get_default_object(generated_class)
if cdo is None:
    fail("the reviewed Blueprint has no class default object")

dirty_before = {
    str(package.get_path_name())
    for package in (
        unreal.EditorLoadingAndSavingUtils.get_dirty_map_packages()
        + unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()
    )
}
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

components = sorted(
    cdo.get_components_by_class(unreal.SkeletalMeshComponent),
    key=stable_component_name,
)
if not components:
    fail("the Blueprint has no skeletal mesh components")
emit("SKELETAL_COMPONENT_COUNT", len(components))

all_morphs = set()
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
        try:
            emit(f"COMPONENT_{index}_LOD_COUNT", mesh.get_lod_num())
        except Exception:
            emit(f"COMPONENT_{index}_LOD_COUNT", "unavailable")

missing_arkit = sorted(EXPECTED_ARKIT - all_morphs)
emit("ARKIT_EXPECTED_COUNT", len(EXPECTED_ARKIT))
emit("ARKIT_FOUND_COUNT", len(EXPECTED_ARKIT & all_morphs))
emit("ARKIT_MISSING", ",".join(missing_arkit) if missing_arkit else "none")

dirty_after = {
    str(package.get_path_name())
    for package in (
        unreal.EditorLoadingAndSavingUtils.get_dirty_map_packages()
        + unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()
    )
}
if dirty_after != dirty_before:
    fail("read-only audit changed the Editor dirty-package set")

emit("BODY_COMPLETENESS", "manual_review_required")
emit("UNDERWEAR_IMPLEMENTATION", "manual_review_required")
emit("LINUX_ARM64_SUPPORT", "cook_required")
emit("COMPLETE", "OK")
