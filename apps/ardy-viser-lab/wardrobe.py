# SPDX-FileCopyrightText: Copyright (c) 2026 Patrick Mello
# SPDX-License-Identifier: MIT

"""Validated private wardrobe data for the ARDY Viser Character Lab."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import numpy as np

SCHEMA_VERSION = 1
CHARACTER_IDS = ("nvidia-original", "casual-girl")
CATEGORIES = ("body", "underwear", "hair", "top", "bottom", "feet")
REQUIRED_ARRAYS = (
    "vertices",
    "faces",
    "skin_weights",
    "bind_bone_positions",
    "bind_bone_wxyzs",
    "bone_names",
)
VISER_SKIN_INFLUENCES = 4


class WardrobeDataError(ValueError):
    """Raised when a private character export does not match the sealed schema."""


@dataclass(frozen=True)
class WardrobePart:
    part_id: str
    label: str
    category: str
    color: tuple[int, int, int]
    vertices: np.ndarray
    faces: np.ndarray
    skin_weights: np.ndarray
    bind_bone_positions: np.ndarray
    bind_bone_wxyzs: np.ndarray
    bone_names: tuple[str, ...]


@dataclass(frozen=True)
class WardrobeManifest:
    root: Path
    character_id: str
    display_name: str
    defaults: dict[str, str | bool]
    parts: dict[str, WardrobePart]

    def options(self, category: str) -> tuple[str, ...]:
        if category not in CATEGORIES:
            raise WardrobeDataError(f"Unknown wardrobe category: {category}")
        return tuple(
            part_id
            for part_id, part in self.parts.items()
            if part.category == category
        )


def _clean_relative_file(root: Path, value: Any) -> Path:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise WardrobeDataError("Each wardrobe part must name a non-empty file")
    rel = Path(value)
    if rel.is_absolute() or ".." in rel.parts:
        raise WardrobeDataError(f"Wardrobe file must stay inside its private root: {value}")
    path = (root / rel).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise WardrobeDataError(f"Wardrobe file escapes its private root: {value}") from exc
    return path


def _rgb(value: Any) -> tuple[int, int, int]:
    if not isinstance(value, list) or len(value) != 3:
        raise WardrobeDataError("Part color must be a three-value RGB list")
    result = tuple(int(channel) for channel in value)
    if any(channel < 0 or channel > 255 for channel in result):
        raise WardrobeDataError("Part RGB channels must be between 0 and 255")
    return result


def load_part(root: Path, raw: dict[str, Any]) -> WardrobePart:
    part_id = raw.get("id")
    label = raw.get("label")
    category = raw.get("category")
    if not isinstance(part_id, str) or not part_id:
        raise WardrobeDataError("Part id must be a non-empty string")
    if not isinstance(label, str) or not label:
        raise WardrobeDataError(f"Part {part_id} must have a label")
    if category not in CATEGORIES:
        raise WardrobeDataError(f"Part {part_id} has unsupported category: {category}")

    path = _clean_relative_file(root, raw.get("file"))
    if not path.is_file():
        raise WardrobeDataError(f"Part file is missing: {path}")

    with np.load(path, allow_pickle=False) as data:
        missing = [key for key in REQUIRED_ARRAYS if key not in data]
        if missing:
            raise WardrobeDataError(f"Part {part_id} is missing arrays: {', '.join(missing)}")
        vertices = np.asarray(data["vertices"], dtype=np.float32)
        faces_raw = np.asarray(data["faces"])
        weights = np.asarray(data["skin_weights"], dtype=np.float32)
        bind_positions = np.asarray(data["bind_bone_positions"], dtype=np.float32)
        bind_wxyzs = np.asarray(data["bind_bone_wxyzs"], dtype=np.float32)
        bone_names_arr = np.asarray(data["bone_names"])

    if vertices.ndim != 2 or vertices.shape[1] != 3 or len(vertices) == 0:
        raise WardrobeDataError(f"Part {part_id} vertices must have shape (V, 3)")
    if faces_raw.ndim != 2 or faces_raw.shape[1] != 3 or len(faces_raw) == 0:
        raise WardrobeDataError(f"Part {part_id} faces must have shape (F, 3)")
    if not np.issubdtype(faces_raw.dtype, np.integer):
        raise WardrobeDataError(f"Part {part_id} faces must contain integer indices")
    if np.any(faces_raw < 0) or faces_raw.max(initial=0) >= len(vertices):
        raise WardrobeDataError(f"Part {part_id} has a face index outside its vertex array")
    faces = np.asarray(faces_raw, dtype=np.uint32)
    if weights.ndim != 2 or weights.shape[0] != len(vertices):
        raise WardrobeDataError(f"Part {part_id} skin_weights must have shape (V, B)")
    bone_count = weights.shape[1]
    if bone_count < VISER_SKIN_INFLUENCES:
        raise WardrobeDataError(
            f"Part {part_id} must contain at least {VISER_SKIN_INFLUENCES} bones "
            "for Viser skinned-mesh compatibility"
        )
    if bone_count > np.iinfo(np.uint16).max:
        raise WardrobeDataError(f"Part {part_id} contains too many bones for Viser")
    if bind_positions.shape != (bone_count, 3):
        raise WardrobeDataError(f"Part {part_id} bind_bone_positions must have shape (B, 3)")
    if bind_wxyzs.shape != (bone_count, 4):
        raise WardrobeDataError(f"Part {part_id} bind_bone_wxyzs must have shape (B, 4)")
    if bone_names_arr.shape != (bone_count,):
        raise WardrobeDataError(f"Part {part_id} bone_names must have shape (B,)")
    bone_names = tuple(str(name) for name in bone_names_arr.tolist())
    if len(set(bone_names)) != len(bone_names):
        raise WardrobeDataError(f"Part {part_id} contains duplicate bone names")
    numeric_arrays = (vertices, weights, bind_positions, bind_wxyzs)
    if any(not np.all(np.isfinite(array)) for array in numeric_arrays):
        raise WardrobeDataError(f"Part {part_id} contains non-finite numeric values")
    if np.any(weights < 0):
        raise WardrobeDataError(f"Part {part_id} has negative skin weights")
    row_sums = weights.sum(axis=1)
    if np.any(row_sums <= 0):
        raise WardrobeDataError(f"Part {part_id} has vertices with no skin influence")
    weights = weights / row_sums[:, None]
    if bone_count > VISER_SKIN_INFLUENCES:
        # Viser 1.0.16 keeps only the four largest weights but does not
        # renormalise them. Do that here so vertices do not shrink toward the
        # origin when an Unreal export contains five or more influences.
        top_indices = np.argsort(weights, axis=1)[:, -VISER_SKIN_INFLUENCES:]
        top_weights = np.take_along_axis(weights, top_indices, axis=1)
        top_weights /= top_weights.sum(axis=1, keepdims=True)
        truncated = np.zeros_like(weights)
        np.put_along_axis(truncated, top_indices, top_weights, axis=1)
        weights = truncated

    quaternion_lengths = np.linalg.norm(bind_wxyzs, axis=1)
    if np.any(quaternion_lengths <= 1e-8):
        raise WardrobeDataError(f"Part {part_id} contains an invalid zero bind quaternion")
    bind_wxyzs = bind_wxyzs / quaternion_lengths[:, None]

    return WardrobePart(
        part_id=part_id,
        label=label,
        category=category,
        color=_rgb(raw.get("color", [180, 180, 180])),
        vertices=vertices,
        faces=faces,
        skin_weights=weights,
        bind_bone_positions=bind_positions,
        bind_bone_wxyzs=bind_wxyzs,
        bone_names=bone_names,
    )


def load_manifest(root: str | Path) -> WardrobeManifest:
    root_path = Path(root).expanduser().resolve()
    manifest_path = root_path / "manifest.json"
    if not root_path.is_dir() or not manifest_path.is_file():
        raise WardrobeDataError(f"Private Casual Girl manifest is missing: {manifest_path}")
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise WardrobeDataError(
            f"Unsupported wardrobe schema {raw.get('schema_version')!r}; expected {SCHEMA_VERSION}"
        )
    if raw.get("character_id") != "casual-girl":
        raise WardrobeDataError("The private manifest character_id must be casual-girl")
    raw_parts = raw.get("parts")
    if not isinstance(raw_parts, list) or not raw_parts:
        raise WardrobeDataError("The private manifest must contain at least one part")

    parts: dict[str, WardrobePart] = {}
    for raw_part in raw_parts:
        if not isinstance(raw_part, dict):
            raise WardrobeDataError("Each manifest part must be an object")
        part = load_part(root_path, raw_part)
        if part.part_id in parts:
            raise WardrobeDataError(f"Duplicate wardrobe part id: {part.part_id}")
        parts[part.part_id] = part

    bone_orders = {part.bone_names for part in parts.values()}
    if len(bone_orders) != 1:
        raise WardrobeDataError("All Casual Girl pieces must share the same exported bone order")
    reference = next(iter(parts.values()))
    for part in parts.values():
        if not np.allclose(
            part.bind_bone_positions,
            reference.bind_bone_positions,
            rtol=1e-5,
            atol=1e-6,
        ):
            raise WardrobeDataError(
                "All Casual Girl pieces must share the same bind bone positions"
            )
        # q and -q describe the same rotation, so compare quaternion alignment.
        quaternion_alignment = np.abs(
            np.sum(part.bind_bone_wxyzs * reference.bind_bone_wxyzs, axis=1)
        )
        if not np.allclose(quaternion_alignment, 1.0, rtol=1e-5, atol=1e-5):
            raise WardrobeDataError(
                "All Casual Girl pieces must share the same bind bone orientations"
            )

    if not any(part.category == "body" for part in parts.values()):
        raise WardrobeDataError("The Casual Girl manifest must contain a body part")

    defaults = raw.get("defaults", {})
    if not isinstance(defaults, dict):
        raise WardrobeDataError("Manifest defaults must be an object")
    for category, selected in defaults.items():
        if category not in CATEGORIES:
            raise WardrobeDataError(f"Unknown default category: {category}")
        if isinstance(selected, bool):
            continue
        if selected not in parts or parts[selected].category != category:
            raise WardrobeDataError(f"Default {category} points to an invalid part: {selected}")

    return WardrobeManifest(
        root=root_path,
        character_id="casual-girl",
        display_name=str(raw.get("display_name") or "Casual Girl"),
        defaults=dict(defaults),
        parts=parts,
    )
