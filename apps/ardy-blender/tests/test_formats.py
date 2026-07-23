# SPDX-License-Identifier: MIT

from pathlib import Path
import sys

import numpy as np
import pytest


APP_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(APP_ROOT))

from ardy_blender import formats


def test_coordinate_conversion_round_trips_without_reflection():
    points = np.asarray(((1.0, 2.0, 3.0), (-4.0, 0.5, 8.0)))
    blender = formats.ardy_points_to_blender(points)
    assert np.linalg.det(formats.ARDY_TO_BLENDER) == pytest.approx(1.0)
    np.testing.assert_allclose(formats.blender_points_to_ardy(blender), points)


def test_sparse_weights_accumulate_duplicate_indices_and_normalise():
    dense = formats.dense_weights_from_sparse(
        np.asarray(((0, 1, 1), (1, 0, 1))),
        np.asarray(((0.5, 0.25, 0.25), (0.2, 0.3, 0.5))),
        vertex_count=2,
        bone_count=2,
    )
    np.testing.assert_allclose(dense, ((0.5, 0.5), (0.3, 0.7)))


def test_staging_destination_refuses_overwrite_and_escape(tmp_path):
    assert formats.staging_destination(tmp_path, "part.npz") == tmp_path / "part.npz"
    (tmp_path / "part.npz").touch()
    with pytest.raises(formats.ArdyFormatError, match="overwrite"):
        formats.staging_destination(tmp_path, "part.npz")
    with pytest.raises(formats.ArdyFormatError):
        formats.staging_destination(tmp_path, "../part.npz")


def test_body_fbx_selection_prefers_named_body(tmp_path):
    body = tmp_path / "SK_Casual_Body.fbx"
    hair = tmp_path / "SK_Casual_Hair.fbx"
    body.touch()
    hair.touch()
    assert formats.choose_body_fbx((hair, body)) == body


def test_staging_npz_is_loader_compatible_and_create_only(tmp_path):
    output = tmp_path / "body.npz"
    formats.write_staging_npz(
        output,
        vertices=np.asarray(((0, 0, 0), (1, 0, 0), (0, 1, 0))),
        faces=np.asarray(((0, 1, 2),)),
        skin_weights=np.asarray(((1, 0), (0.5, 0.5), (0, 1))),
        bind_bone_positions=np.asarray(((0, 0, 0), (0, 1, 0))),
        bind_bone_wxyzs=np.asarray(((1, 0, 0, 0), (1, 0, 0, 0))),
        bone_names=("Hips", "Spine"),
        identifier="body",
        category="body",
    )
    with np.load(output, allow_pickle=False) as archive:
        assert set(formats.WARDROBE_REQUIRED_ARRAYS).issubset(archive.files)
        assert archive["skin_weights"].shape == (3, 2)
    with pytest.raises(formats.ArdyFormatError, match="overwrite"):
        formats.write_staging_npz(
            output,
            vertices=np.asarray(((0, 0, 0), (1, 0, 0), (0, 1, 0))),
            faces=np.asarray(((0, 1, 2),)),
            skin_weights=np.asarray(((1, 0), (0.5, 0.5), (0, 1))),
            bind_bone_positions=np.asarray(((0, 0, 0), (0, 1, 0))),
            bind_bone_wxyzs=np.asarray(((1, 0, 0, 0), (1, 0, 0, 0))),
            bone_names=("Hips", "Spine"),
            identifier="body",
            category="body",
        )
