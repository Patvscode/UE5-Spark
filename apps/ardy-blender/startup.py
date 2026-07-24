#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 Patrick Mello
# SPDX-License-Identifier: MIT

"""Interactive Blender startup for the DGX Spark desktop launcher.

The outer launcher supplies narrow container paths. This script enables the
real add-on, fills its native N-panel paths, imports missing character
collections once, and creates the private project file on first launch.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys
import traceback

import bpy


APP_ROOT = Path(__file__).resolve().parent
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

import ardy_blender  # noqa: E402
from ardy_blender import blender_adapter  # noqa: E402


def _register() -> None:
    if not hasattr(bpy.types.Scene, "ardy_nvidia_skin_path"):
        ardy_blender.register()


def _configure_scene() -> None:
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0
    scene.ardy_nvidia_skin_path = os.environ.get("ARDY_NVIDIA_SKIN", "")
    scene.ardy_casual_fbx_root = os.environ.get(
        "ARDY_CASUAL_GIRL_FBX_ROOT", ""
    )
    scene.ardy_casual_body_fbx = os.environ.get(
        "ARDY_CASUAL_GIRL_BODY_FBX", ""
    )
    scene.ardy_casual_manifest_root = os.environ.get(
        "ARDY_CASUAL_GIRL_ROOT",
        os.environ.get("ARDY_CASUAL_GIRL_MANIFEST_ROOT", ""),
    )
    scene.ardy_staging_root = os.environ.get(
        "ARDY_BLENDER_EXPORT_ROOT",
        os.environ.get("ARDY_BLENDER_STAGING_ROOT", ""),
    )
    scene["ardy_adapter_version"] = "1.1.0"
    scene["ardy_blender_target"] = "4.0.2+"
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == "VIEW_3D" and hasattr(area.spaces.active, "show_region_ui"):
                area.spaces.active.show_region_ui = True


def _import_missing() -> bool:
    changed = False
    scene = bpy.context.scene
    if blender_adapter.COLLECTION_NVIDIA not in bpy.data.collections:
        blender_adapter.load_nvidia_skin(scene.ardy_nvidia_skin_path)
        changed = True
    if blender_adapter.COLLECTION_CASUAL not in bpy.data.collections:
        blender_adapter.load_casual(
            fbx_root=scene.ardy_casual_fbx_root or None,
            manifest_root=scene.ardy_casual_manifest_root or None,
            body_fbx=scene.ardy_casual_body_fbx or None,
        )
        changed = True
    return changed


def _prepare_rig_views() -> bool:
    changed = False
    for collection_name in (
        blender_adapter.COLLECTION_NVIDIA,
        blender_adapter.COLLECTION_CASUAL,
    ):
        collection = bpy.data.collections.get(collection_name)
        if collection is None:
            continue
        armatures = tuple(
            item for item in collection.all_objects if item.type == "ARMATURE"
        )
        for armature in armatures:
            visible = set(blender_adapter._preview_mapping(armature).values())
            visible.add("root")
            expected_hidden = {
                bone.name for bone in armature.data.bones if bone.name not in visible
            }
            actual_hidden = {
                bone.name for bone in armature.data.bones if bone.hide
            }
            if (
                armature.data.display_type != "STICK"
                or not armature.data.show_names
                or not armature.show_in_front
                or actual_hidden != expected_hidden
            ):
                blender_adapter._clean_armature_view(armature)
                changed = True
    return changed


def _save_first_project(changed: bool) -> None:
    project = os.environ.get("ARDY_BLENDER_PROJECT", "")
    if not project:
        return
    destination = Path(project)
    if destination.suffix.casefold() != ".blend" or not destination.parent.is_dir():
        raise RuntimeError("ARDY_BLENDER_PROJECT must name a .blend in an existing directory")
    # An existing project was already opened by the launcher. Save only when a
    # character was newly installed or when creating the initial private file.
    if changed or not destination.exists():
        bpy.ops.wm.save_as_mainfile(filepath=str(destination), check_existing=False)


def main() -> None:
    _register()
    _configure_scene()
    try:
        changed = _import_missing()
        changed = _prepare_rig_views() or changed
        _save_first_project(changed)
        bpy.context.scene["ardy_startup_status"] = (
            "NVIDIA Original and Casual Girl are ready"
        )
        if "ardy_startup_error" in bpy.context.scene:
            del bpy.context.scene["ardy_startup_error"]
    except Exception as exc:
        # Keep Blender open so the user still has the native UI, path fields,
        # console log, and can correct/import manually.
        message = f"{type(exc).__name__}: {exc}"
        bpy.context.scene["ardy_startup_error"] = message
        print("ARDY Blender startup did not complete:", message, file=sys.stderr)
        traceback.print_exc()


main()
