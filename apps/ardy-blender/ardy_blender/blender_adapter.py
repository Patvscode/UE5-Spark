# SPDX-FileCopyrightText: Copyright (c) 2026 Patrick Mello
# SPDX-License-Identifier: MIT

"""Blender API layer for the ARDY Character Adapter.

All actual rig editing remains Blender-native: Edit Mode, Pose Mode, Weight
Paint, the Outliner, materials, and Blender's FBX importer/exporter.
"""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Iterable

import bpy
from bpy_extras.io_utils import ExportHelper
from mathutils import Matrix, Vector
import numpy as np

from . import formats


COLLECTION_NVIDIA = "ARDY · NVIDIA Original"
COLLECTION_CASUAL = "ARDY · Casual Girl"


def _deselect_all() -> None:
    for item in bpy.context.selected_objects:
        item.select_set(False)


def _new_top_collection(name: str, *, identifier: str, source_kind: str):
    old = bpy.data.collections.get(name)
    if old is not None:
        raise formats.ArdyFormatError(
            f"{name!r} already exists; remove it explicitly before importing again"
        )
    collection = bpy.data.collections.new(name)
    collection["ardy_identifier"] = identifier
    collection["ardy_category"] = "character"
    collection["ardy_source_kind"] = source_kind
    bpy.context.scene.collection.children.link(collection)
    return collection


def _part_collection(parent, part: formats.SkinPart):
    collection = bpy.data.collections.new(f"{part.category} · {part.label}")
    collection["ardy_identifier"] = part.identifier
    collection["ardy_category"] = part.category
    collection["ardy_source_kind"] = "npz"
    parent.children.link(collection)
    return collection


def _props(target, *, identifier: str, category: str, source_kind: str, source_name: str):
    target["ardy_identifier"] = identifier
    target["ardy_category"] = category
    target["ardy_source_kind"] = source_kind
    target["ardy_source_name"] = source_name


def _bone_lengths(matrices: np.ndarray, names: tuple[str, ...]) -> tuple[float, ...]:
    positions = matrices[:, :3, 3]
    by_parent: dict[int, list[float]] = {}
    if names == formats.CORE27_NAMES:
        for child, parent in enumerate(formats.CORE27_PARENTS):
            if parent >= 0:
                by_parent.setdefault(parent, []).append(
                    float(np.linalg.norm(positions[child] - positions[parent]))
                )
    result: list[float] = []
    for index in range(len(names)):
        candidates = [value for value in by_parent.get(index, ()) if value > 1e-4]
        result.append(max(0.025, min(candidates) if candidates else 0.05))
    return tuple(result)


def _create_armature(
    collection,
    *,
    name: str,
    bone_names: tuple[str, ...],
    bind_matrices_ardy: np.ndarray,
    identifier: str,
    source_name: str,
):
    armature_data = bpy.data.armatures.new(f"{name} Rig")
    armature_object = bpy.data.objects.new(f"{name} Armature", armature_data)
    collection.objects.link(armature_object)
    _props(
        armature_object,
        identifier=identifier,
        category="rig",
        source_kind="npz",
        source_name=source_name,
    )
    armature_data["ardy_coordinate_system"] = "ardy-y-up-z-forward-metres"
    armature_data["ardy_bone_order"] = "\n".join(bone_names)

    _deselect_all()
    armature_object.select_set(True)
    bpy.context.view_layer.objects.active = armature_object
    bpy.ops.object.mode_set(mode="EDIT")
    matrices = formats.convert_bind_matrices_to_blender(bind_matrices_ardy)
    lengths = _bone_lengths(matrices, bone_names)
    bones = []
    try:
        for index, bone_name in enumerate(bone_names):
            bone = armature_data.edit_bones.new(bone_name)
            # EditBone.matrix defines the rest transform while the length keeps
            # a real, selectable bone in Blender's native rigging tools.
            bone.matrix = Matrix(matrices[index].tolist())
            bone.length = lengths[index]
            bones.append(bone)
        if bone_names == formats.CORE27_NAMES:
            for child, parent in enumerate(formats.CORE27_PARENTS):
                if parent >= 0:
                    bones[child].parent = bones[parent]
                    bones[child].use_connect = False
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")
    return armature_object


def _material(label: str, color: tuple[float, float, float, float]):
    material = bpy.data.materials.new(f"ARDY · {label}")
    material.diffuse_color = color
    material.use_nodes = True
    principled = material.node_tree.nodes.get("Principled BSDF")
    if principled is not None:
        principled.inputs["Base Color"].default_value = color
        principled.inputs["Roughness"].default_value = 0.58
    return material


def _create_mesh(collection, part: formats.SkinPart, armature):
    mesh_data = bpy.data.meshes.new(f"{part.label} Mesh")
    vertices = formats.ardy_points_to_blender(part.vertices)
    mesh_data.from_pydata(vertices.tolist(), [], part.faces.tolist())
    mesh_data.update(calc_edges=True)
    mesh_object = bpy.data.objects.new(part.label, mesh_data)
    collection.objects.link(mesh_object)
    _props(
        mesh_object,
        identifier=part.identifier,
        category=part.category,
        source_kind="npz",
        source_name=part.source_name,
    )
    mesh_object["ardy_character_id"] = (
        "nvidia-original" if part.identifier == "nvidia-original" else "casual-girl"
    )
    mesh_data.materials.append(_material(part.label, part.color))

    for bone_index, bone_name in enumerate(part.bone_names):
        group = mesh_object.vertex_groups.new(name=bone_name)
        influenced = np.flatnonzero(part.weights[:, bone_index] > 1e-7)
        for vertex_index in influenced.tolist():
            group.add(
                [vertex_index], float(part.weights[vertex_index, bone_index]), "REPLACE"
            )
    modifier = mesh_object.modifiers.new(name="ARDY Armature", type="ARMATURE")
    modifier.object = armature
    mesh_object.parent = armature
    mesh_object.matrix_parent_inverse = armature.matrix_world.inverted()
    return mesh_object


def import_npz_character(part_or_manifest):
    if isinstance(part_or_manifest, formats.SkinPart):
        top = _new_top_collection(
            COLLECTION_NVIDIA,
            identifier="nvidia-original",
            source_kind="nvidia-core27-npz",
        )
        part_collection = _part_collection(top, part_or_manifest)
        armature = _create_armature(
            top,
            name="NVIDIA Core27",
            bone_names=part_or_manifest.bone_names,
            bind_matrices_ardy=part_or_manifest.bind_matrices,
            identifier="nvidia-original",
            source_name=part_or_manifest.source_name,
        )
        meshes = (_create_mesh(part_collection, part_or_manifest, armature),)
    else:
        manifest: formats.WardrobeManifest = part_or_manifest
        top = _new_top_collection(
            COLLECTION_CASUAL,
            identifier=manifest.character_id,
            source_kind="wardrobe-manifest-npz",
        )
        first = manifest.parts[0]
        armature = _create_armature(
            top,
            name=manifest.display_name,
            bone_names=first.bone_names,
            bind_matrices_ardy=first.bind_matrices,
            identifier=manifest.character_id,
            source_name="manifest.json",
        )
        meshes = tuple(
            _create_mesh(_part_collection(top, part), part, armature)
            for part in manifest.parts
        )
    _deselect_all()
    armature.select_set(True)
    for mesh in meshes:
        mesh.select_set(True)
    bpy.context.view_layer.objects.active = armature
    return top, armature, meshes


def load_nvidia_skin(path: str | Path):
    return import_npz_character(formats.load_core27_skin(path))


def load_casual_npz(root: str | Path):
    return import_npz_character(formats.load_wardrobe_manifest(root))


def _import_fbx(path: Path) -> tuple[object, ...]:
    before = set(bpy.data.objects)
    # Blender 4.0 uses the official io_scene_fbx add-on. Blender 5 also
    # exposes a native WM operator in builds that enable the C++ importer.
    wm_import = getattr(bpy.ops.wm, "fbx_import", None)
    if wm_import is not None:
        wm_import(filepath=str(path))
    else:
        bpy.ops.import_scene.fbx(filepath=str(path), use_custom_normals=True)
    return tuple(item for item in bpy.data.objects if item not in before)


def _move_to_collection(item, destination) -> None:
    for collection in tuple(item.users_collection):
        collection.objects.unlink(item)
    destination.objects.link(item)


def _rebind_mesh(mesh, canonical_armature, duplicate_armatures: set) -> None:
    world = mesh.matrix_world.copy()
    armature_modifiers = [
        modifier for modifier in mesh.modifiers if modifier.type == "ARMATURE"
    ]
    if not armature_modifiers and any(
        group.name in canonical_armature.data.bones for group in mesh.vertex_groups
    ):
        armature_modifiers.append(mesh.modifiers.new("ARDY Armature", "ARMATURE"))
    for modifier in armature_modifiers:
        if modifier.object in duplicate_armatures or modifier.object is None:
            modifier.object = canonical_armature
    mesh.parent = canonical_armature
    mesh.matrix_world = world


def load_casual_fbx(
    root: str | Path,
    *,
    body_fbx: str | Path | None = None,
):
    paths = formats.discover_fbx(root)
    canonical_path = formats.choose_body_fbx(paths, body_fbx)
    ordered = (canonical_path,) + tuple(path for path in paths if path != canonical_path)
    top = _new_top_collection(
        COLLECTION_CASUAL,
        identifier="casual-girl",
        source_kind="native-fbx",
    )
    canonical_armature = None
    all_meshes: list[object] = []
    for path in ordered:
        category = formats.infer_fbx_category(path)
        identifier = formats.slug(path.stem)
        part_collection = bpy.data.collections.new(f"{category} · {path.stem}")
        part_collection["ardy_identifier"] = identifier
        part_collection["ardy_category"] = category
        part_collection["ardy_source_kind"] = "native-fbx"
        top.children.link(part_collection)
        imported = _import_fbx(path)
        armatures = tuple(item for item in imported if item.type == "ARMATURE")
        meshes = tuple(item for item in imported if item.type == "MESH")
        if path == canonical_path:
            if not armatures:
                raise formats.ArdyFormatError(
                    f"canonical body FBX {path.name!r} contains no armature"
                )
            canonical_armature = max(
                armatures, key=lambda item: len(item.data.bones)
            )
            canonical_armature.name = "Casual Girl Canonical Armature"
            _props(
                canonical_armature,
                identifier="casual-girl",
                category="rig",
                source_kind="native-fbx",
                source_name=path.name,
            )
        assert canonical_armature is not None
        duplicates = set(armatures).difference({canonical_armature})
        for mesh in meshes:
            _props(
                mesh,
                identifier=identifier,
                category=category,
                source_kind="native-fbx",
                source_name=path.name,
            )
            mesh["ardy_character_id"] = "casual-girl"
            _rebind_mesh(mesh, canonical_armature, duplicates)
            all_meshes.append(mesh)
        for item in imported:
            if item not in duplicates:
                _move_to_collection(item, part_collection)
        for duplicate in duplicates:
            for child in tuple(duplicate.children):
                if child.type != "MESH":
                    child.parent = None
            bpy.data.objects.remove(duplicate, do_unlink=True)

    if canonical_armature is None or not all_meshes:
        raise formats.ArdyFormatError("Casual Girl FBX set has no usable rigged meshes")
    _deselect_all()
    canonical_armature.select_set(True)
    for mesh in all_meshes:
        mesh.select_set(True)
    bpy.context.view_layer.objects.active = canonical_armature
    return top, canonical_armature, tuple(all_meshes)


def load_casual(
    *,
    fbx_root: str | Path | None,
    manifest_root: str | Path | None,
    body_fbx: str | Path | None = None,
):
    if fbx_root and Path(fbx_root).expanduser().is_dir():
        return load_casual_fbx(fbx_root, body_fbx=body_fbx)
    if not manifest_root:
        raise formats.ArdyFormatError(
            "set ARDY_CASUAL_GIRL_FBX_ROOT or choose a manifest root"
        )
    return load_casual_npz(manifest_root)


def _armature_for_mesh(mesh):
    for modifier in mesh.modifiers:
        if modifier.type == "ARMATURE" and modifier.object is not None:
            return modifier.object
    if mesh.parent is not None and mesh.parent.type == "ARMATURE":
        return mesh.parent
    return None


def _selected_armature(context):
    active = context.active_object
    if active is not None and active.type == "ARMATURE":
        return active
    if active is not None and active.type == "MESH":
        return _armature_for_mesh(active)
    for item in context.selected_objects:
        if item.type == "ARMATURE":
            return item
        if item.type == "MESH":
            armature = _armature_for_mesh(item)
            if armature is not None:
                return armature
    return None


def validate_core27_armature(armature) -> tuple[bool, str]:
    if armature is None or armature.type != "ARMATURE":
        return False, "Select a mesh or armature first"
    bones = armature.data.bones
    names = tuple(bone.name for bone in bones)
    if names != formats.CORE27_NAMES:
        missing = tuple(name for name in formats.CORE27_NAMES if name not in bones)
        extras = tuple(name for name in names if name not in formats.CORE27_NAMES)
        return False, (
            "Not exact Core27"
            + (f"; missing: {', '.join(missing)}" if missing else "")
            + (f"; extra/order mismatch: {', '.join(extras[:8])}" if extras else "")
        )
    for index, expected_parent in enumerate(formats.CORE27_PARENTS):
        actual = bones[index].parent
        actual_name = actual.name if actual else None
        expected_name = (
            formats.CORE27_NAMES[expected_parent] if expected_parent >= 0 else None
        )
        if actual_name != expected_name:
            return False, (
                f"Core27 parent mismatch at {bones[index].name}: "
                f"expected {expected_name!r}, found {actual_name!r}"
            )
    return True, "Exact NVIDIA Core27 names, order, and hierarchy"


def _export_fbx(filepath: str) -> None:
    kwargs = dict(
        filepath=filepath,
        use_selection=True,
        global_scale=1.0,
        apply_unit_scale=True,
        apply_scale_options="FBX_SCALE_UNITS",
        axis_forward="-Z",
        axis_up="Y",
        use_mesh_modifiers=True,
        add_leaf_bones=False,
        primary_bone_axis="Y",
        secondary_bone_axis="X",
        use_armature_deform_only=False,
        bake_anim=False,
        mesh_smooth_type="FACE",
        use_tspace=True,
        path_mode="AUTO",
    )
    wm_export = getattr(bpy.ops.wm, "fbx_export", None)
    if wm_export is not None:
        # The newer native exporter intentionally has a different option
        # surface; use its defaults after explicitly selecting the objects.
        wm_export(filepath=filepath, export_selected_objects=True)
    else:
        bpy.ops.export_scene.fbx(**kwargs)


def export_selected_fbx(context, filepath: str) -> None:
    meshes = tuple(item for item in context.selected_objects if item.type == "MESH")
    if not meshes and context.active_object and context.active_object.type == "MESH":
        meshes = (context.active_object,)
    if not meshes:
        raise formats.ArdyFormatError("select at least one mesh to export")
    armatures = {
        armature
        for armature in (_armature_for_mesh(mesh) for mesh in meshes)
        if armature is not None
    }
    if not armatures:
        raise formats.ArdyFormatError("selected meshes do not reference an armature")
    _deselect_all()
    for item in (*meshes, *armatures):
        item.select_set(True)
    context.view_layer.objects.active = next(iter(armatures))
    _export_fbx(filepath)


def _matrix_blender_to_ardy(matrix: Matrix) -> np.ndarray:
    source = np.asarray(matrix, dtype=np.float64)
    result = source.copy()
    result[:3, :3] = (
        formats.BLENDER_TO_ARDY @ source[:3, :3] @ formats.ARDY_TO_BLENDER
    )
    result[:3, 3] = formats.BLENDER_TO_ARDY @ source[:3, 3]
    return result


def _wxyz_from_rotation(rotation: np.ndarray) -> tuple[float, float, float, float]:
    quaternion = Matrix(rotation.tolist()).to_quaternion().normalized()
    return (quaternion.w, quaternion.x, quaternion.y, quaternion.z)


def export_selected_npz(context, staging_root: str | Path) -> Path:
    mesh = context.active_object
    if mesh is None or mesh.type != "MESH":
        candidates = [item for item in context.selected_objects if item.type == "MESH"]
        mesh = candidates[0] if candidates else None
    if mesh is None:
        raise formats.ArdyFormatError("make one mesh active before staging an NPZ")
    armature = _armature_for_mesh(mesh)
    if armature is None:
        raise formats.ArdyFormatError("active mesh does not reference an armature")

    bones = tuple(armature.data.bones)
    bone_indices = {bone.name: index for index, bone in enumerate(bones)}
    weights = np.zeros((len(mesh.data.vertices), len(bones)), dtype=np.float32)
    group_names = {
        group.index: group.name for group in mesh.vertex_groups
    }
    for vertex in mesh.data.vertices:
        for assignment in vertex.groups:
            bone_index = bone_indices.get(group_names.get(assignment.group, ""))
            if bone_index is not None:
                weights[vertex.index, bone_index] += assignment.weight

    world_vertices = np.asarray(
        [tuple(mesh.matrix_world @ vertex.co) for vertex in mesh.data.vertices],
        dtype=np.float64,
    )
    vertices_ardy = formats.blender_points_to_ardy(world_vertices)
    mesh.data.calc_loop_triangles()
    faces = np.asarray(
        [tuple(triangle.vertices) for triangle in mesh.data.loop_triangles],
        dtype=np.uint32,
    )

    bind_matrices = np.asarray(
        [
            _matrix_blender_to_ardy(armature.matrix_world @ bone.matrix_local)
            for bone in bones
        ],
        dtype=np.float64,
    )
    positions = bind_matrices[:, :3, 3]
    wxyzs = np.asarray(
        [_wxyz_from_rotation(matrix[:3, :3]) for matrix in bind_matrices],
        dtype=np.float64,
    )
    identifier = str(mesh.get("ardy_identifier") or mesh.name)
    category = str(mesh.get("ardy_category") or "body")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    filename = f"{formats.slug(identifier)}-{stamp}.npz"
    destination = formats.staging_destination(staging_root, filename)
    formats.write_staging_npz(
        destination,
        vertices=vertices_ardy,
        faces=faces,
        skin_weights=weights,
        bind_bone_positions=positions,
        bind_bone_wxyzs=wxyzs,
        bone_names=(bone.name for bone in bones),
        identifier=identifier,
        category=category,
    )
    return destination


class ARDY_OT_load_nvidia(bpy.types.Operator):
    bl_idname = "ardy.load_nvidia"
    bl_label = "Load NVIDIA Original"
    bl_description = "Import NVIDIA's actual Core27 skin_standard.npz"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            load_nvidia_skin(context.scene.ardy_nvidia_skin_path)
        except (formats.ArdyFormatError, OSError, RuntimeError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, "Loaded NVIDIA Original Core27")
        return {"FINISHED"}


class ARDY_OT_load_casual(bpy.types.Operator):
    bl_idname = "ardy.load_casual"
    bl_label = "Load Casual Girl"
    bl_description = "Prefer native modular FBXs; fall back to the reviewed NPZ manifest"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            load_casual(
                fbx_root=context.scene.ardy_casual_fbx_root,
                manifest_root=context.scene.ardy_casual_manifest_root,
                body_fbx=context.scene.ardy_casual_body_fbx or None,
            )
        except (formats.ArdyFormatError, OSError, RuntimeError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, "Loaded Casual Girl")
        return {"FINISHED"}


class ARDY_OT_validate_core27(bpy.types.Operator):
    bl_idname = "ardy.validate_core27"
    bl_label = "Validate Selected Core27"
    bl_options = {"REGISTER"}

    def execute(self, context):
        valid, message = validate_core27_armature(_selected_armature(context))
        self.report({"INFO"} if valid else {"ERROR"}, message)
        return {"FINISHED"} if valid else {"CANCELLED"}


class ARDY_OT_export_fbx(bpy.types.Operator, ExportHelper):
    bl_idname = "ardy.export_unreal_fbx"
    bl_label = "Export Selected for Unreal"
    filename_ext = ".fbx"
    filter_glob: bpy.props.StringProperty(default="*.fbx", options={"HIDDEN"})

    def execute(self, context):
        try:
            export_selected_fbx(context, self.filepath)
        except (formats.ArdyFormatError, OSError, RuntimeError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, f"Exported {Path(self.filepath).name}")
        return {"FINISHED"}


class ARDY_OT_export_npz(bpy.types.Operator):
    bl_idname = "ardy.export_staging_npz"
    bl_label = "Stage Active Mesh as NPZ"
    bl_description = "Create a new NPZ in staging; source/live inputs are never overwritten"
    bl_options = {"REGISTER"}

    def execute(self, context):
        try:
            destination = export_selected_npz(context, context.scene.ardy_staging_root)
        except (formats.ArdyFormatError, OSError, RuntimeError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, f"Created {destination.name}")
        return {"FINISHED"}


class ARDY_PT_character_adapter(bpy.types.Panel):
    bl_label = "ARDY Character Adapter"
    bl_idname = "ARDY_PT_character_adapter"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "ARDY"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        box = layout.box()
        box.label(text="NVIDIA Original", icon="ARMATURE_DATA")
        box.prop(scene, "ardy_nvidia_skin_path", text="Core27 NPZ")
        box.operator("ardy.load_nvidia", icon="IMPORT")

        box = layout.box()
        box.label(text="Casual Girl", icon="OUTLINER_OB_ARMATURE")
        box.prop(scene, "ardy_casual_fbx_root", text="Native FBX Root")
        box.prop(scene, "ardy_casual_body_fbx", text="Body FBX (optional)")
        box.prop(scene, "ardy_casual_manifest_root", text="NPZ Fallback")
        box.operator("ardy.load_casual", icon="IMPORT")

        box = layout.box()
        box.label(text="Blender-native rigging", icon="POSE_HLT")
        box.label(text="Use Edit, Pose, and Weight Paint modes")
        box.operator("ardy.validate_core27", icon="CHECKMARK")

        box = layout.box()
        box.label(text="Interchange", icon="EXPORT")
        box.operator("ardy.export_unreal_fbx", icon="EXPORT")
        box.prop(scene, "ardy_staging_root", text="NPZ Staging")
        box.operator("ardy.export_staging_npz", icon="PACKAGE")


CLASSES = (
    ARDY_OT_load_nvidia,
    ARDY_OT_load_casual,
    ARDY_OT_validate_core27,
    ARDY_OT_export_fbx,
    ARDY_OT_export_npz,
    ARDY_PT_character_adapter,
)


def register() -> None:
    for value in CLASSES:
        bpy.utils.register_class(value)
    bpy.types.Scene.ardy_nvidia_skin_path = bpy.props.StringProperty(
        name="NVIDIA Core27 skin",
        subtype="FILE_PATH",
        default=os.environ.get("ARDY_NVIDIA_SKIN", ""),
    )
    bpy.types.Scene.ardy_casual_fbx_root = bpy.props.StringProperty(
        name="Casual Girl FBX root",
        subtype="DIR_PATH",
        default=os.environ.get("ARDY_CASUAL_GIRL_FBX_ROOT", ""),
    )
    bpy.types.Scene.ardy_casual_body_fbx = bpy.props.StringProperty(
        name="Canonical body FBX",
        subtype="FILE_PATH",
        default=os.environ.get("ARDY_CASUAL_GIRL_BODY_FBX", ""),
    )
    bpy.types.Scene.ardy_casual_manifest_root = bpy.props.StringProperty(
        name="Casual Girl NPZ manifest root",
        subtype="DIR_PATH",
        default=os.environ.get("ARDY_CASUAL_GIRL_MANIFEST_ROOT", ""),
    )
    bpy.types.Scene.ardy_staging_root = bpy.props.StringProperty(
        name="Safe staging root",
        subtype="DIR_PATH",
        default=os.environ.get("ARDY_BLENDER_STAGING_ROOT", ""),
    )


def unregister() -> None:
    for name in (
        "ardy_staging_root",
        "ardy_casual_manifest_root",
        "ardy_casual_body_fbx",
        "ardy_casual_fbx_root",
        "ardy_nvidia_skin_path",
    ):
        if hasattr(bpy.types.Scene, name):
            delattr(bpy.types.Scene, name)
    for value in reversed(CLASSES):
        bpy.utils.unregister_class(value)
