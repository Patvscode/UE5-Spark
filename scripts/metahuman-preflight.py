"""Read-only UE 5.8 MetaHuman and project-helper preflight."""

import unreal


CONTENT_ROOT = "/Game/FayMetaHumans"
PRESET_ASSET = "/MetaHumanCharacter/Optional/Presets/Ada.Ada"

PYTHON_MARKER = "MH_PREFLIGHT_PYTHON"
HELPER_MARKER = "MH_PREFLIGHT_HELPER"
SUBSYSTEM_MARKER = "MH_PREFLIGHT_SUBSYSTEM"
ADA_PRESET_MARKER = "MH_PREFLIGHT_ADA_PRESET"
ADA_TYPE_MARKER = "MH_PREFLIGHT_ADA_TYPE"
ENUMS_MARKER = "MH_PREFLIGHT_ENUMS"
DESTINATION_MARKER = "MH_PREFLIGHT_DESTINATION_EMPTY"
DIRTY_MARKER = "MH_PREFLIGHT_DIRTY_PACKAGES_UNCHANGED"
COMPLETE_MARKER = "MH_PREFLIGHT_COMPLETE"
FAILED_MARKER = "MH_PREFLIGHT_FAILED"

failed = False


def report(marker, passed):
    global failed
    if passed:
        unreal.log(f"{marker}_OK")
    else:
        unreal.log_error(f"{marker}_FAILED")
        failed = True


def package_snapshot():
    maps = tuple(
        sorted(
            str(package.get_path_name())
            for package in unreal.EditorLoadingAndSavingUtils.get_dirty_map_packages()
        )
    )
    content = tuple(
        sorted(
            str(package.get_path_name())
            for package in unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()
        )
    )
    return maps, content


def safe_call(callback, fallback=None):
    try:
        return callback()
    except Exception:
        return fallback


dirty_before = safe_call(package_snapshot)
report(PYTHON_MARKER, True)

adapter = getattr(unreal, "FayMetaHumanPresetLibrary", None)
report(
    HELPER_MARKER,
    adapter is not None
    and callable(getattr(adapter, "initialize_from_preset", None)),
)

subsystem_type = getattr(unreal, "MetaHumanCharacterEditorSubsystem", None)
subsystem = None
if subsystem_type is not None:
    subsystem = safe_call(lambda: unreal.get_editor_subsystem(subsystem_type))
report(SUBSYSTEM_MARKER, subsystem is not None)

meta_human_type = getattr(unreal, "MetaHumanCharacter", None)
preset = safe_call(lambda: unreal.load_asset(PRESET_ASSET))
report(ADA_PRESET_MARKER, preset is not None)
ada_type_matches = safe_call(
    lambda: meta_human_type is not None
    and isinstance(preset, meta_human_type),
    False,
)
report(
    ADA_TYPE_MARKER,
    preset is not None and ada_type_matches,
)

rig_type = getattr(unreal, "MetaHumanRigType", None)
pipeline_type = getattr(unreal, "MetaHumanDefaultPipelineType", None)
quality_type = getattr(unreal, "MetaHumanQualityLevel", None)
report(
    ENUMS_MARKER,
    rig_type is not None
    and getattr(rig_type, "JOINTS_AND_BLEND_SHAPES", None) is not None
    and pipeline_type is not None
    and getattr(pipeline_type, "OPTIMIZED", None) is not None
    and quality_type is not None
    and getattr(quality_type, "HIGH", None) is not None,
)

destination_assets = safe_call(
    lambda: unreal.EditorAssetLibrary.list_assets(
        CONTENT_ROOT,
        recursive=True,
        include_folder=False,
    )
)
report(
    DESTINATION_MARKER,
    destination_assets is not None and len(destination_assets) == 0,
)

dirty_after = safe_call(package_snapshot)
report(
    DIRTY_MARKER,
    dirty_before is not None
    and dirty_after is not None
    and dirty_before == dirty_after,
)

if failed:
    raise RuntimeError(FAILED_MARKER)

unreal.log(f"{COMPLETE_MARKER}_OK")
