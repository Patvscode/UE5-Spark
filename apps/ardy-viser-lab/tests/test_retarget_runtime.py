from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys

import numpy as np
import pytest
import torch

pytest.importorskip("viser")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ardy.skeleton import CoreSkeleton27
import viser.transforms as tf

from casual_girl import CasualGirlWardrobeRig
from wardrobe import WardrobeManifest, WardrobePart


def test_neutral_core27_pose_preserves_target_bind_pose() -> None:
    skeleton = CoreSkeleton27(device="cpu")
    bone_count = len(skeleton.bone_order_names)

    rig = CasualGirlWardrobeRig.__new__(CasualGirlWardrobeRig)
    rig.skeleton = skeleton
    rig.source_indices = np.arange(bone_count, dtype=np.int64)
    rig.bind_positions = skeleton.neutral_joints.detach().cpu().numpy().copy()
    bind_angles = np.linspace(0.0, 0.2, bone_count)
    rig.bind_rotations = tf.SO3.from_y_radians(bind_angles).as_matrix()
    rig.parent_indices = np.asarray(
        skeleton.joint_parents.detach().cpu(),
        dtype=np.int64,
    )
    rig.root_index = int(skeleton.root_idx)
    rig.pose_order = tuple(range(bone_count))
    rig.bone_names = tuple(skeleton.bone_order_names)

    neutral_rotations = torch.eye(3).repeat(bone_count, 1, 1)
    positions, wxyzs = rig._retarget_pose(
        skeleton.neutral_joints,
        neutral_rotations,
    )

    assert np.allclose(positions, rig.bind_positions, rtol=1e-5, atol=1e-6)
    assert np.allclose(
        tf.SO3(wxyzs).as_matrix(),
        rig.bind_rotations,
        rtol=1e-5,
        atol=1e-6,
    )


def test_rebuilt_wardrobe_piece_inherits_current_ardy_frame() -> None:
    bone_count = 27
    current_positions = np.arange(bone_count * 3, dtype=np.float32).reshape(
        bone_count, 3
    )
    current_wxyzs = np.zeros((bone_count, 4), dtype=np.float32)
    current_wxyzs[:, 0] = 1.0
    bones = [
        SimpleNamespace(
            position=np.full(3, -1.0, dtype=np.float32),
            wxyz=np.asarray((0.0, 1.0, 0.0, 0.0), dtype=np.float32),
        )
        for _ in range(bone_count)
    ]
    handle = SimpleNamespace(name="/character/casual_girl/hair", bones=bones)

    class FakeScene:
        def add_mesh_skinned(self, *_args, **_kwargs):
            return handle

        def remove_by_name(self, _name):
            return None

    part = WardrobePart(
        part_id="hair_2",
        label="Hair Style 2",
        category="hair",
        color=(1, 2, 3),
        vertices=np.zeros((3, 3), dtype=np.float32),
        faces=np.asarray([[0, 1, 2]], dtype=np.uint32),
        skin_weights=np.full((3, bone_count), 1.0 / bone_count, dtype=np.float32),
        bind_bone_positions=np.zeros((bone_count, 3), dtype=np.float32),
        bind_bone_wxyzs=current_wxyzs.copy(),
        bone_names=tuple(f"bone_{index}" for index in range(bone_count)),
    )
    rig = CasualGirlWardrobeRig.__new__(CasualGirlWardrobeRig)
    rig.name = "character"
    rig.server = SimpleNamespace(scene=FakeScene())
    rig.manifest = WardrobeManifest(
        root=Path("."),
        character_id="casual-girl",
        display_name="Casual Girl",
        defaults={},
        parts={"hair_2": part},
    )
    rig.handles = {}
    rig.selected = {"hair": "hair_2"}
    rig.visible = True
    rig.opacity = 1.0
    rig.wireframe = False
    rig.current_positions = current_positions
    rig.current_wxyzs = current_wxyzs

    rig._rebuild("hair")

    assert rig.handles["hair"] is handle
    for index, bone in enumerate(bones):
        assert np.array_equal(bone.position, current_positions[index])
        assert np.array_equal(bone.wxyz, current_wxyzs[index])
