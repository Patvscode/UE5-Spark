# SPDX-FileCopyrightText: Copyright (c) 2026 Patrick Mello
# SPDX-License-Identifier: MIT

"""Live Casual Girl adapter for NVIDIA's official ARDY Viser character API."""

from __future__ import annotations

import threading

import numpy as np
import torch
import viser.transforms as tf

from ardy.viz.viser_utils import Character

from wardrobe import CATEGORIES, WardrobeManifest


def _normalise_quaternions(wxyzs: np.ndarray) -> np.ndarray:
    lengths = np.linalg.norm(wxyzs, axis=-1, keepdims=True)
    lengths = np.where(lengths > 1e-8, lengths, 1.0)
    return wxyzs / lengths


class CasualGirlWardrobeRig:
    """One Core27-driven Viser skinned mesh per visible wardrobe category."""

    def __init__(self, name: str, server, skeleton, manifest: WardrobeManifest):
        self.name = name
        self.server = server
        self.skeleton = skeleton
        self.manifest = manifest
        self.handles: dict[str, object] = {}
        self.selected: dict[str, str | None] = {}
        self.visible = True
        self.opacity = 1.0
        self.wireframe = False
        self._lock = threading.RLock()

        first_part = next(iter(manifest.parts.values()))
        self.bone_names = first_part.bone_names
        self.source_indices = self._resolve_source_indices()
        self.bind_positions = first_part.bind_bone_positions.copy()
        self.bind_wxyzs = _normalise_quaternions(first_part.bind_bone_wxyzs.copy())
        self.bind_rotations = tf.SO3(self.bind_wxyzs).as_matrix()
        # A wardrobe piece can be replaced while ARDY playback is paused. Keep
        # the most recently rendered global pose so a newly created skinned
        # mesh joins that frame immediately instead of briefly returning to
        # the export origin/bind pose.
        self.current_positions = self.bind_positions.copy()
        self.current_wxyzs = self.bind_wxyzs.copy()
        self.parent_indices = self._resolve_parent_indices()
        root_matches = np.flatnonzero(self.source_indices == int(self.skeleton.root_idx))
        if root_matches.shape != (1,):
            raise ValueError(
                "Casual Girl export must contain the ARDY Core27 root bone exactly once"
            )
        self.root_index = int(root_matches[0])
        if self.parent_indices[self.root_index] >= 0:
            raise ValueError("Casual Girl Core27 root bone cannot have an exported parent")
        disconnected = np.flatnonzero(
            (self.parent_indices < 0)
            & (np.arange(len(self.parent_indices)) != self.root_index)
        )
        if len(disconnected):
            names = ", ".join(self.bone_names[index] for index in disconnected)
            raise ValueError(
                "Casual Girl export contains bones disconnected from the Core27 root: "
                + names
            )
        self.pose_order = self._resolve_pose_order()

        for category in CATEGORIES:
            raw_default = manifest.defaults.get(category)
            if isinstance(raw_default, bool):
                choices = manifest.options(category)
                self.selected[category] = choices[0] if raw_default and choices else None
            else:
                self.selected[category] = raw_default
        self._rebuild_all()

    def _resolve_source_indices(self) -> np.ndarray:
        source_by_name = {
            str(name).lower(): index
            for index, name in enumerate(self.skeleton.bone_order_names)
        }
        missing = [name for name in self.bone_names if name.lower() not in source_by_name]
        if missing:
            raise ValueError(
                "Casual Girl export references bones not present in ARDY Core27: "
                + ", ".join(missing)
            )
        return np.asarray([source_by_name[name.lower()] for name in self.bone_names], dtype=np.int64)

    def _resolve_parent_indices(self) -> np.ndarray:
        source_parents = np.asarray(self.skeleton.joint_parents.detach().cpu(), dtype=np.int64)
        exported_by_source = {
            int(source_index): exported_index
            for exported_index, source_index in enumerate(self.source_indices)
        }
        parents = np.full(len(self.source_indices), -1, dtype=np.int64)
        for exported_index, source_index in enumerate(self.source_indices):
            parent = int(source_parents[source_index])
            while parent >= 0 and parent not in exported_by_source:
                next_parent = int(source_parents[parent])
                if next_parent == parent:
                    parent = -1
                    break
                parent = next_parent
            if parent in exported_by_source:
                parents[exported_index] = exported_by_source[parent]
        return parents

    def _resolve_pose_order(self) -> tuple[int, ...]:
        """Return a parent-first traversal independent of exported array order."""
        pending = set(range(len(self.parent_indices)))
        ordered: list[int] = []
        completed: set[int] = set()
        while pending:
            ready = sorted(
                index
                for index in pending
                if self.parent_indices[index] < 0
                or int(self.parent_indices[index]) in completed
            )
            if not ready:
                raise ValueError("Casual Girl exported skeleton contains a parent cycle")
            for index in ready:
                pending.remove(index)
                completed.add(index)
                ordered.append(index)
        return tuple(ordered)

    def _remove_handle(self, category: str) -> None:
        handle = self.handles.pop(category, None)
        if handle is not None:
            self.server.scene.remove_by_name(handle.name)

    def _apply_pose_to_handle(self, handle) -> None:
        if len(handle.bones) != len(self.current_positions):
            raise ValueError(
                "Casual Girl Viser mesh bone count changed after wardrobe rebuild"
            )
        for index, bone in enumerate(handle.bones):
            bone.position = self.current_positions[index]
            bone.wxyz = self.current_wxyzs[index]

    def _rebuild(self, category: str) -> None:
        self._remove_handle(category)
        part_id = self.selected.get(category)
        if part_id is None:
            return
        part = self.manifest.parts[part_id]
        handle = self.server.scene.add_mesh_skinned(
            f"/{self.name}/casual_girl/{category}",
            vertices=part.vertices,
            faces=part.faces,
            bone_wxyzs=part.bind_bone_wxyzs,
            bone_positions=part.bind_bone_positions,
            skin_weights=part.skin_weights,
            color=part.color,
            opacity=self.opacity if self.opacity < 1.0 else None,
            wireframe=self.wireframe,
            side="double",
            visible=self.visible,
        )
        self.handles[category] = handle
        self._apply_pose_to_handle(handle)

    def _rebuild_all(self) -> None:
        with self._lock:
            for category in CATEGORIES:
                self._rebuild(category)

    def set_category(self, category: str, part_id: str | None) -> None:
        if category not in CATEGORIES:
            raise ValueError(f"Unknown wardrobe category: {category}")
        if part_id is not None:
            part = self.manifest.parts.get(part_id)
            if part is None or part.category != category:
                raise ValueError(f"{part_id!r} is not a {category} wardrobe part")
        with self._lock:
            self.selected[category] = part_id
            self._rebuild(category)

    def _retarget_pose(
        self,
        joints_pos: torch.Tensor,
        joints_rot: torch.Tensor,
    ) -> tuple[np.ndarray, np.ndarray]:
        source_pos = joints_pos.detach().cpu().numpy()[self.source_indices]
        source_rot = joints_rot.detach().cpu().numpy()[self.source_indices]

        source_bind_all = self.skeleton.neutral_joints.detach().cpu().numpy()
        source_bind = source_bind_all[self.source_indices]
        target_pos = np.zeros_like(self.bind_positions)
        target_rot = np.zeros_like(self.bind_rotations)

        root = self.root_index
        target_pos[root] = self.bind_positions[root] + (
            source_pos[root] - source_bind[root]
        )
        # Core27's neutral global rotations are identity. Apply the generated
        # root delta after the target's authored bind orientation.
        target_rot[root] = self.bind_rotations[root] @ source_rot[root]

        for index in self.pose_order:
            if index == root:
                continue
            parent = int(self.parent_indices[index])
            bind_offset_world = self.bind_positions[index] - self.bind_positions[parent]
            parent_bind_inverse = self.bind_rotations[parent].T
            target_bind_offset = parent_bind_inverse @ bind_offset_world
            target_pos[index] = (
                target_pos[parent] + target_rot[parent] @ target_bind_offset
            )

            source_local_delta = source_rot[parent].T @ source_rot[index]
            target_bind_local = parent_bind_inverse @ self.bind_rotations[index]
            target_rot[index] = (
                target_rot[parent]
                @ target_bind_local
                @ source_local_delta
            )

        target_wxyz = tf.SO3.from_matrix(target_rot).wxyz
        return target_pos, _normalise_quaternions(target_wxyz)

    def set_pose(self, joints_pos: torch.Tensor, joints_rot: torch.Tensor) -> None:
        positions, wxyzs = self._retarget_pose(joints_pos, joints_rot)
        with self._lock:
            self.current_positions = positions.copy()
            self.current_wxyzs = wxyzs.copy()
            for handle in self.handles.values():
                if not handle.visible:
                    continue
                self._apply_pose_to_handle(handle)

    def set_visibility(self, visible: bool) -> None:
        self.visible = visible
        for handle in self.handles.values():
            handle.visible = visible

    def set_opacity(self, opacity: float) -> None:
        self.opacity = opacity
        for category in tuple(self.handles):
            self._rebuild(category)

    def set_wireframe(self, wireframe: bool) -> None:
        self.wireframe = wireframe
        for category in tuple(self.handles):
            self._rebuild(category)

    def set_color(self, _color) -> None:
        # Each modular part owns its reviewed material color.
        return

    def clear(self) -> None:
        for category in tuple(self.handles):
            self._remove_handle(category)


class CasualGirlCharacter(Character):
    """Character-compatible wrapper used by the unmodified ARDY playback loop."""

    def __init__(self, *args, wardrobe_manifest: WardrobeManifest, **kwargs):
        visible_skinned_mesh = kwargs.pop("visible_skinned_mesh", True)
        skinned_mesh_opacity = kwargs.pop("skinned_mesh_opacity", 1.0)
        super().__init__(
            *args,
            create_skinned_mesh=False,
            visible_skinned_mesh=False,
            skinned_mesh_opacity=skinned_mesh_opacity,
            **kwargs,
        )
        self.wardrobe_rig = CasualGirlWardrobeRig(
            self.name,
            self.server,
            self.skeleton,
            wardrobe_manifest,
        )
        # Reuse the G1-rig branch of the official Character interface. This
        # keeps all upstream playback and visualization callbacks unchanged.
        self.g1_mesh_rig = self.wardrobe_rig
        self.set_skinned_mesh_visibility(visible_skinned_mesh)
        self.set_skinned_mesh_opacity(skinned_mesh_opacity)

    def set_pose(
        self,
        joints_pos: torch.Tensor,
        joints_rot: torch.Tensor,
        foot_contacts=None,
        frame_idx=None,
        root_velocity=None,
    ):
        if self.skeleton_mesh is not None:
            current_contacts = foot_contacts if self.show_foot_contacts else None
            self.skeleton_mesh.set_pose(
                joints_pos,
                foot_contacts=current_contacts,
                frame_idx=frame_idx,
                root_velocity=root_velocity,
            )
            self.cur_foot_contacts = current_contacts
        self.wardrobe_rig.set_pose(joints_pos, joints_rot)
        self.cur_joints_pos = joints_pos
        self.cur_joints_rot = joints_rot

    def set_wardrobe(self, category: str, part_id: str | None) -> None:
        self.wardrobe_rig.set_category(category, part_id)
