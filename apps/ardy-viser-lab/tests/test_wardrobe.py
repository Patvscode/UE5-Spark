from __future__ import annotations

import json
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wardrobe import WardrobeDataError, load_manifest


def write_part(
    path: Path,
    bone_names=("pelvis", "spine1", "neck", "head"),
    *,
    skin_weights: np.ndarray | None = None,
    bind_positions: np.ndarray | None = None,
) -> None:
    bone_count = len(bone_names)
    if skin_weights is None:
        skin_weights = np.zeros((3, bone_count), dtype=np.float32)
        skin_weights[0, 0] = 1.0
        skin_weights[1, :2] = 0.5
        skin_weights[2, min(1, bone_count - 1)] = 1.0
    if bind_positions is None:
        bind_positions = np.stack(
            [np.asarray([0, index, 0], dtype=np.float32) for index in range(bone_count)]
        )
    np.savez_compressed(
        path,
        vertices=np.asarray([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32),
        faces=np.asarray([[0, 1, 2]], dtype=np.uint32),
        skin_weights=skin_weights,
        bind_bone_positions=bind_positions,
        bind_bone_wxyzs=np.tile(
            np.asarray([[1, 0, 0, 0]], dtype=np.float32),
            (bone_count, 1),
        ),
        bone_names=np.asarray(bone_names),
    )


def write_manifest(root: Path, file_name="body.npz") -> None:
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "character_id": "casual-girl",
                "defaults": {"body": "body"},
                "parts": [
                    {
                        "id": "body",
                        "label": "Body",
                        "category": "body",
                        "file": file_name,
                        "color": [100, 110, 120],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_loads_and_normalises_weights(tmp_path: Path) -> None:
    write_part(tmp_path / "body.npz")
    write_manifest(tmp_path)
    manifest = load_manifest(tmp_path)
    assert manifest.options("body") == ("body",)
    assert np.allclose(manifest.parts["body"].skin_weights.sum(axis=1), 1.0)


def test_rejects_path_escape(tmp_path: Path) -> None:
    write_part(tmp_path / "body.npz")
    write_manifest(tmp_path, "../body.npz")
    with pytest.raises(WardrobeDataError, match="stay inside"):
        load_manifest(tmp_path)


def test_rejects_mismatched_bone_order(tmp_path: Path) -> None:
    write_part(tmp_path / "body.npz")
    write_part(
        tmp_path / "hair.npz",
        bone_names=("pelvis", "spine1", "neck", "jaw"),
    )
    payload = {
        "schema_version": 1,
        "character_id": "casual-girl",
        "defaults": {"body": "body", "hair": "hair"},
        "parts": [
            {"id": "body", "label": "Body", "category": "body", "file": "body.npz"},
            {"id": "hair", "label": "Hair", "category": "hair", "file": "hair.npz"},
        ],
    }
    (tmp_path / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(WardrobeDataError, match="same exported bone order"):
        load_manifest(tmp_path)


def test_truncates_and_renormalises_to_visers_four_influences(
    tmp_path: Path,
) -> None:
    weights = np.asarray(
        [
            [0.05, 0.10, 0.15, 0.20, 0.50],
            [0.20, 0.20, 0.20, 0.20, 0.20],
            [0.01, 0.02, 0.03, 0.04, 0.90],
        ],
        dtype=np.float32,
    )
    write_part(
        tmp_path / "body.npz",
        bone_names=("pelvis", "spine1", "neck", "head", "jaw"),
        skin_weights=weights,
    )
    write_manifest(tmp_path)
    loaded = load_manifest(tmp_path).parts["body"].skin_weights
    assert np.allclose(loaded.sum(axis=1), 1.0)
    assert np.all(np.count_nonzero(loaded, axis=1) <= 4)


def test_rejects_mismatched_bind_pose(tmp_path: Path) -> None:
    write_part(tmp_path / "body.npz")
    changed_bind = np.stack(
        [np.asarray([0, index, 0], dtype=np.float32) for index in range(4)]
    )
    changed_bind[2, 0] = 0.25
    write_part(tmp_path / "hair.npz", bind_positions=changed_bind)
    payload = {
        "schema_version": 1,
        "character_id": "casual-girl",
        "defaults": {"body": "body", "hair": "hair"},
        "parts": [
            {"id": "body", "label": "Body", "category": "body", "file": "body.npz"},
            {"id": "hair", "label": "Hair", "category": "hair", "file": "hair.npz"},
        ],
    }
    (tmp_path / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(WardrobeDataError, match="same bind bone positions"):
        load_manifest(tmp_path)
