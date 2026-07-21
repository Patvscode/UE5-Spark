"""Assemble one reviewed UE 5.8 MetaHuman preset without overwriting content."""

import os
import unreal


CONTENT_ROOT = "/Game/FayMetaHumans"
SOURCE_DIRECTORY = f"{CONTENT_ROOT}/Source"
BUILD_DIRECTORY = f"{CONTENT_ROOT}/Built"
COMMON_DIRECTORY = f"{CONTENT_ROOT}/Common_UE58"
REVIEWED_PRESETS = {
    "Ada": {
        "asset": "/MetaHumanCharacter/Optional/Presets/Ada.Ada",
        "name": "AdaFay",
    },
    "Aoi": {
        "asset": "/MetaHumanCharacter/Optional/Presets/Aoi.Aoi",
        "name": "AoiFay",
    },
}
SPARK_OPTIMIZATION_NOTICE = (
    "This Optimized/High assembly is a fidelity baseline, not a fully Spark-tuned "
    "asset. The script cannot require card-only hair or cap generated texture "
    "resolution through the reflected UE 5.8 API. Inspect hair representations, "
    "textures, materials, and LODs in the Editor before deployment."
)


def fail(message):
    unreal.log_error(f"Fay MetaHuman assembly stopped: {message}")
    raise RuntimeError(message)


def package_names(packages):
    return [str(package.get_path_name()) for package in packages]


def ensure_clean_editor_state():
    dirty_maps = unreal.EditorLoadingAndSavingUtils.get_dirty_map_packages()
    dirty_content = unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()
    if dirty_maps or dirty_content:
        dirty_names = package_names([*dirty_maps, *dirty_content])
        formatted_names = "\n  ".join(dirty_names)
        fail(
            "Save or discard the Editor's existing dirty packages before "
            f"assembly:\n  {formatted_names}"
        )


def ensure_fresh_destination(source_asset, build_character_directory):
    existing_assets = []
    if unreal.EditorAssetLibrary.does_asset_exist(source_asset):
        existing_assets.append(source_asset)
    existing_assets.extend(unreal.EditorAssetLibrary.list_assets(
        build_character_directory,
        recursive=True,
        include_folder=False,
    ))
    if existing_assets:
        formatted_assets = "\n  ".join(str(asset) for asset in existing_assets)
        fail(
            "The destination is not empty. This script never overwrites existing "
            f"assets. Move or remove these assets before retrying:\n  {formatted_assets}"
        )


def create_character(character_name, source_directory, source_asset):
    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
    factory = unreal.new_object(type=unreal.MetaHumanCharacterFactoryNew)
    character = asset_tools.create_asset(
        asset_name=character_name,
        package_path=source_directory,
        asset_class=unreal.MetaHumanCharacter,
        factory=factory,
    )
    if character is None:
        fail(f"Could not create {source_asset}.")
    return character


def assemble_character(profile_id="Ada"):
    profile = REVIEWED_PRESETS.get(profile_id)
    if profile is None:
        fail(f"Character {profile_id!r} is not in the reviewed preset allowlist.")
    character_name = profile["name"]
    preset_asset = profile["asset"]
    source_asset = f"{SOURCE_DIRECTORY}/{character_name}"
    build_character_directory = f"{BUILD_DIRECTORY}/{character_name}"
    expected_blueprint = (
        f"{build_character_directory}/BP_{character_name}"
    )

    ensure_clean_editor_state()
    ensure_fresh_destination(source_asset, build_character_directory)
    unreal.log_warning(f"Fay MetaHuman: {SPARK_OPTIMIZATION_NOTICE}")

    preset = unreal.load_asset(preset_asset)
    if preset is None:
        fail(
            f"Could not load {preset_asset}. Install the UE 5.8 MetaHuman "
            "Creator Core Data before running this script."
        )

    subsystem = unreal.get_editor_subsystem(
        unreal.MetaHumanCharacterEditorSubsystem
    )
    if subsystem is None:
        fail("The MetaHuman Character editor subsystem is unavailable.")

    adapter = getattr(unreal, "FayMetaHumanPresetLibrary", None)
    if adapter is None:
        fail("The Fay MetaHuman Editor Tools plugin is not loaded.")

    rig_type = getattr(
        unreal.MetaHumanRigType,
        "JOINTS_AND_BLEND_SHAPES",
        None,
    )
    if rig_type is None:
        fail("UE 5.8 did not expose the expected Joints and Blend Shapes rig type.")

    character = create_character(character_name, SOURCE_DIRECTORY, source_asset)
    registered = False

    try:
        if not subsystem.try_add_object_to_edit(character=character):
            fail("Could not register the new character for editing.")
        registered = True

        if not adapter.initialize_from_preset(
            target_character=character,
            preset_character=preset,
        ):
            fail(
                "The Editor adapter refused or failed to apply the "
                f"{profile_id} preset."
            )

        if adapter.has_face_dna(character=character):
            subsystem.remove_face_rig(character=character)
            if adapter.has_face_dna(character=character):
                fail("Could not clear the preset's existing face rig.")

        rig_request = unreal.MetaHumanCharacterAutoRiggingRequestParams()
        rig_request.rig_type = rig_type
        rig_request.report_progress = False
        rig_request.blocking = True
        subsystem.request_auto_rigging(
            character=character,
            params=rig_request,
        )

        if not adapter.has_face_dna_blend_shapes(character=character):
            fail(
                "Epic's auto-rig request did not return the requested face-DNA "
                "blend shapes."
            )

        texture_request = unreal.MetaHumanCharacterTextureRequestParams()
        texture_request.report_progress = False
        texture_request.blocking = True
        subsystem.request_texture_sources(
            character=character,
            params=texture_request,
        )

        if not character.has_high_resolution_textures:
            fail("Epic's texture-source request did not complete successfully.")

        if not subsystem.can_build_meta_human(character=character):
            fail("The character is not rigged and textured for assembly.")

        build_parameters = unreal.MetaHumanCharacterEditorBuildParameters()
        build_parameters.pipeline_type = (
            unreal.MetaHumanDefaultPipelineType.OPTIMIZED
        )
        build_parameters.pipeline_quality = unreal.MetaHumanQualityLevel.HIGH
        build_parameters.animation_system_name = "AnimBP"
        build_parameters.absolute_build_path = BUILD_DIRECTORY
        build_parameters.common_folder_path = COMMON_DIRECTORY
        build_parameters.name_override = character_name
        build_parameters.enable_wardrobe_item_validation = True

        subsystem.build_meta_human(
            character=character,
            params=build_parameters,
        )

        if unreal.load_asset(expected_blueprint) is None:
            fail(
                "Assembly returned without creating the expected Blueprint at "
                f"{expected_blueprint}."
            )

        dirty_maps = unreal.EditorLoadingAndSavingUtils.get_dirty_map_packages()
        if dirty_maps:
            formatted_maps = "\n  ".join(package_names(dirty_maps))
            fail(
                "Assembly unexpectedly dirtied map packages; nothing was saved:\n  "
                f"{formatted_maps}"
            )

        dirty_content = (
            unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()
        )
        unexpected_packages = [
            package_name
            for package_name in package_names(dirty_content)
            if not package_name.startswith(f"{CONTENT_ROOT}/")
        ]
        if unexpected_packages:
            formatted_packages = "\n  ".join(unexpected_packages)
            fail(
                "Assembly dirtied content outside its destination; nothing was "
                f"saved:\n  {formatted_packages}"
            )

        if not dirty_content:
            fail("Assembly produced no dirty content packages to save.")

        if not unreal.EditorLoadingAndSavingUtils.save_packages(
            dirty_content,
            True,
        ):
            fail("Unreal did not save every generated content package.")

        if not unreal.EditorAssetLibrary.does_asset_exist(expected_blueprint):
            fail(f"The saved Blueprint is missing at {expected_blueprint}.")

        unreal.log(
            "Fay MetaHuman assembly succeeded. Blueprint: "
            f"{expected_blueprint}"
        )
        unreal.log_warning(f"Fay MetaHuman: {SPARK_OPTIMIZATION_NOTICE}")
    finally:
        if registered and subsystem.is_object_added_for_editing(
            character=character
        ):
            subsystem.remove_object_to_edit(character=character)


if __name__ == "__main__":
    assemble_character(os.environ.get("FAY_METAHUMAN_CHARACTER", "Ada"))
