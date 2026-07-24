# SPDX-FileCopyrightText: Copyright (c) 2026 Patrick Mello
# SPDX-License-Identifier: MIT

"""Pure data helpers shared by the ARDY Blender add-on and its tests.

This module intentionally does not import :mod:`bpy`.  The Blender-facing
adapter is thin; validation and path policy remain testable with ordinary
CPython plus NumPy.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Iterable

import numpy as np


CORE27_NAMES = (
    "Hips",
    "Spine",
    "Spine1",
    "Spine2",
    "Spine3",
    "Neck",
    "Head",
    "RightShoulder",
    "RightArm",
    "RightForeArm",
    "RightHand",
    "RightHandEnd",
    "RightHandThumb1",
    "LeftShoulder",
    "LeftArm",
    "LeftForeArm",
    "LeftHand",
    "LeftHandEnd",
    "LeftHandThumb1",
    "RightUpLeg",
    "RightLeg",
    "RightFoot",
    "RightToeBase",
    "LeftUpLeg",
    "LeftLeg",
    "LeftFoot",
    "LeftToeBase",
)

CORE27_PARENTS = (
    -1, 0, 1, 2, 3, 4, 5, 4, 7, 8, 9, 10, 10, 4, 13, 14, 15, 16, 16,
    0, 19, 20, 21, 0, 23, 24, 25,
)

CORE27_CONNECTIONS = tuple(
    (parent, child)
    for child, parent in enumerate(CORE27_PARENTS)
    if parent >= 0
)

WARDROBE_CATEGORIES = ("body", "underwear", "hair", "top", "bottom", "feet")
WARDROBE_REQUIRED_ARRAYS = (
    "vertices",
    "faces",
    "skin_weights",
    "bind_bone_positions",
    "bind_bone_wxyzs",
    "bone_names",
)

# ARDY is Y-up. Blender is Z-up. This is a proper rotation (not a mirror):
# (x, y, z)_ardy -> (x, -z, y)_blender.
ARDY_TO_BLENDER = np.asarray(
    ((1.0, 0.0, 0.0), (0.0, 0.0, -1.0), (0.0, 1.0, 0.0)),
    dtype=np.float64,
)
BLENDER_TO_ARDY = ARDY_TO_BLENDER.T


class ArdyFormatError(ValueError):
    """An input does not satisfy the documented ARDY adapter contract."""


@dataclass(frozen=True)
class SkinPart:
    identifier: str
    label: str
    category: str
    vertices: np.ndarray
    faces: np.ndarray
    weights: np.ndarray
    bone_names: tuple[str, ...]
    bind_matrices: np.ndarray
    color: tuple[float, float, float, float]
    source_name: str


@dataclass(frozen=True)
class WardrobeManifest:
    character_id: str
    display_name: str
    root: Path
    parts: tuple[SkinPart, ...]


def _strings(values: np.ndarray) -> tuple[str, ...]:
    result: list[str] = []
    for value in np.asarray(values).tolist():
        if isinstance(value, bytes):
            result.append(value.decode("utf-8"))
        else:
            result.append(str(value))
    return tuple(result)


def _real_file(path: str | Path, label: str) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_file() or candidate.is_symlink():
        raise ArdyFormatError(f"{label} must be an existing regular file")
    return candidate.resolve()


def _triangles(values: np.ndarray, vertex_count: int, label: str) -> np.ndarray:
    faces = np.asarray(values)
    if faces.ndim != 2 or faces.shape[1] != 3 or not len(faces):
        raise ArdyFormatError(f"{label} faces must have shape (F, 3)")
    if not np.issubdtype(faces.dtype, np.integer):
        raise ArdyFormatError(f"{label} faces must contain integer indices")
    if np.any(faces < 0) or int(faces.max(initial=0)) >= vertex_count:
        raise ArdyFormatError(f"{label} has a face index outside its vertex array")
    return np.asarray(faces, dtype=np.uint32)


def _normalise_dense_weights(values: np.ndarray, vertex_count: int, bone_count: int) -> np.ndarray:
    weights = np.asarray(values, dtype=np.float32)
    if weights.shape != (vertex_count, bone_count):
        raise ArdyFormatError(
            f"skin_weights must have shape ({vertex_count}, {bone_count})"
        )
    if not np.isfinite(weights).all() or np.any(weights < 0.0):
        raise ArdyFormatError("skin_weights must be finite and non-negative")
    totals = weights.sum(axis=1)
    if np.any(totals <= 0.0):
        raise ArdyFormatError("every vertex must have at least one skin influence")
    return weights / totals[:, None]


def dense_weights_from_sparse(
    indices: np.ndarray,
    weights: np.ndarray,
    *,
    vertex_count: int,
    bone_count: int,
) -> np.ndarray:
    indices = np.asarray(indices)
    sparse = np.asarray(weights, dtype=np.float32)
    if indices.shape != sparse.shape or indices.ndim != 2:
        raise ArdyFormatError("lbs_indices and lbs_weights must share shape (V, W)")
    if indices.shape[0] != vertex_count:
        raise ArdyFormatError("sparse skin arrays do not match bind_vertices")
    if not np.issubdtype(indices.dtype, np.integer):
        raise ArdyFormatError("lbs_indices must contain integer indices")
    if np.any(indices < 0) or np.any(indices >= bone_count):
        raise ArdyFormatError("lbs_indices references a bone outside Core27")
    if not np.isfinite(sparse).all() or np.any(sparse < 0.0):
        raise ArdyFormatError("lbs_weights must be finite and non-negative")

    dense = np.zeros((vertex_count, bone_count), dtype=np.float32)
    rows = np.broadcast_to(np.arange(vertex_count)[:, None], indices.shape)
    np.add.at(dense, (rows, indices), sparse)
    return _normalise_dense_weights(dense, vertex_count, bone_count)


def _validate_affine(matrices: np.ndarray, count: int, label: str) -> np.ndarray:
    result = np.asarray(matrices, dtype=np.float64)
    if result.shape != (count, 4, 4):
        raise ArdyFormatError(f"{label} must have shape ({count}, 4, 4)")
    if not np.isfinite(result).all():
        raise ArdyFormatError(f"{label} contains a non-finite value")
    expected = np.asarray((0.0, 0.0, 0.0, 1.0))
    if not np.allclose(result[:, 3, :], expected, atol=1e-6):
        raise ArdyFormatError(f"{label} contains a non-affine matrix")
    return result


def matrix_from_position_wxyz(position: np.ndarray, wxyz: np.ndarray) -> np.ndarray:
    """Return homogeneous global bind matrices from positions and quaternions."""
    positions = np.asarray(position, dtype=np.float64)
    quaternions = np.asarray(wxyz, dtype=np.float64)
    if positions.ndim != 2 or positions.shape[1] != 3:
        raise ArdyFormatError("bind_bone_positions must have shape (B, 3)")
    if quaternions.shape != (len(positions), 4):
        raise ArdyFormatError("bind_bone_wxyzs must have shape (B, 4)")
    lengths = np.linalg.norm(quaternions, axis=1)
    if not np.isfinite(quaternions).all() or np.any(lengths <= 1e-8):
        raise ArdyFormatError("bind_bone_wxyzs contains an invalid quaternion")
    q = quaternions / lengths[:, None]
    w, x, y, z = (q[:, index] for index in range(4))
    rotations = np.empty((len(q), 3, 3), dtype=np.float64)
    rotations[:, 0, 0] = 1 - 2 * (y * y + z * z)
    rotations[:, 0, 1] = 2 * (x * y - z * w)
    rotations[:, 0, 2] = 2 * (x * z + y * w)
    rotations[:, 1, 0] = 2 * (x * y + z * w)
    rotations[:, 1, 1] = 1 - 2 * (x * x + z * z)
    rotations[:, 1, 2] = 2 * (y * z - x * w)
    rotations[:, 2, 0] = 2 * (x * z - y * w)
    rotations[:, 2, 1] = 2 * (y * z + x * w)
    rotations[:, 2, 2] = 1 - 2 * (x * x + y * y)
    result = np.broadcast_to(np.eye(4), (len(q), 4, 4)).copy()
    result[:, :3, :3] = rotations
    result[:, :3, 3] = positions
    return result


def convert_bind_matrices_to_blender(matrices: np.ndarray) -> np.ndarray:
    """Convert ARDY global transforms to Blender global transforms."""
    source = np.asarray(matrices, dtype=np.float64)
    result = source.copy()
    result[:, :3, :3] = (
        ARDY_TO_BLENDER[None] @ source[:, :3, :3] @ BLENDER_TO_ARDY[None]
    )
    result[:, :3, 3] = source[:, :3, 3] @ ARDY_TO_BLENDER.T
    return result


def ardy_points_to_blender(points: np.ndarray) -> np.ndarray:
    return np.asarray(points, dtype=np.float64) @ ARDY_TO_BLENDER.T


def blender_points_to_ardy(points: np.ndarray) -> np.ndarray:
    return np.asarray(points, dtype=np.float64) @ BLENDER_TO_ARDY.T


def local_rotation_matrix_from_xyzw(value: Iterable[float]) -> np.ndarray:
    """Return an ARDY local quaternion as a 3x3 matrix without a world-basis change."""
    quaternion = np.asarray(tuple(value), dtype=np.float64)
    if quaternion.shape != (4,) or not np.isfinite(quaternion).all():
        raise ArdyFormatError("local joint rotation must contain four finite values")
    length = float(np.linalg.norm(quaternion))
    if length <= 1e-8:
        raise ArdyFormatError("local joint rotation quaternion cannot be zero")
    x, y, z, w = quaternion / length
    return np.asarray(
        (
            (1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)),
            (2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)),
            (2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)),
        ),
        dtype=np.float64,
    )


def load_core27_skin(path: str | Path) -> SkinPart:
    source = _real_file(path, "NVIDIA skin_standard.npz")
    try:
        archive = np.load(source, allow_pickle=False)
    except (OSError, ValueError) as exc:
        raise ArdyFormatError(f"could not read NVIDIA Core27 skin: {exc}") from exc
    required = {
        "bind_rig_transform",
        "bind_vertices",
        "faces",
        "lbs_indices",
        "lbs_weights",
        "rig_joint_names",
        "rig_joint_connections",
    }
    missing = sorted(required.difference(archive.files))
    if missing:
        raise ArdyFormatError(f"Core27 skin is missing arrays: {', '.join(missing)}")
    names = _strings(archive["rig_joint_names"])
    if names != CORE27_NAMES:
        raise ArdyFormatError("Core27 joint names/order differ from NVIDIA's exact Core27")
    connections = tuple(
        tuple(int(component) for component in row)
        for row in np.asarray(archive["rig_joint_connections"]).tolist()
    )
    if connections != CORE27_CONNECTIONS:
        raise ArdyFormatError("Core27 parent connections differ from NVIDIA's exact Core27")
    vertices = np.asarray(archive["bind_vertices"], dtype=np.float32)
    if vertices.ndim != 2 or vertices.shape[1] != 3 or not len(vertices):
        raise ArdyFormatError("bind_vertices must have shape (V, 3)")
    if not np.isfinite(vertices).all():
        raise ArdyFormatError("bind_vertices contains a non-finite value")
    matrices = _validate_affine(archive["bind_rig_transform"], len(names), "bind_rig_transform")
    faces = _triangles(archive["faces"], len(vertices), "Core27")
    weights = dense_weights_from_sparse(
        archive["lbs_indices"],
        archive["lbs_weights"],
        vertex_count=len(vertices),
        bone_count=len(names),
    )
    return SkinPart(
        identifier="nvidia-original",
        label="NVIDIA Original",
        category="body",
        vertices=vertices,
        faces=faces,
        weights=weights,
        bone_names=names,
        bind_matrices=matrices,
        color=(0.62, 0.68, 0.72, 1.0),
        source_name=source.name,
    )


def _safe_manifest_file(root: Path, value: Any) -> Path:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ArdyFormatError("every manifest part must name a file")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ArdyFormatError("manifest part files must stay inside the manifest root")
    target = (root / relative).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ArdyFormatError("manifest part file escapes its manifest root") from exc
    return _real_file(target, "wardrobe part")


def _color(raw: Any) -> tuple[float, float, float, float]:
    if not isinstance(raw, list) or len(raw) != 3:
        raw = [180, 180, 180]
    channels = tuple(int(component) for component in raw)
    if any(component < 0 or component > 255 for component in channels):
        raise ArdyFormatError("wardrobe RGB values must be between 0 and 255")
    return tuple(component / 255.0 for component in channels) + (1.0,)


def load_wardrobe_manifest(root: str | Path) -> WardrobeManifest:
    root_path = Path(root).expanduser()
    manifest_path = _real_file(root_path / "manifest.json", "Casual Girl manifest")
    root_path = manifest_path.parent.resolve()
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArdyFormatError(f"could not read Casual Girl manifest: {exc}") from exc
    if raw.get("schema_version") != 1 or raw.get("character_id") != "casual-girl":
        raise ArdyFormatError("expected Casual Girl manifest schema_version 1")
    raw_parts = raw.get("parts")
    if not isinstance(raw_parts, list) or not raw_parts:
        raise ArdyFormatError("Casual Girl manifest has no parts")

    parts: list[SkinPart] = []
    identifiers: set[str] = set()
    reference_names: tuple[str, ...] | None = None
    reference_matrices: np.ndarray | None = None
    for raw_part in raw_parts:
        if not isinstance(raw_part, dict):
            raise ArdyFormatError("each Casual Girl manifest part must be an object")
        identifier = raw_part.get("id")
        category = raw_part.get("category")
        if not isinstance(identifier, str) or not identifier or identifier in identifiers:
            raise ArdyFormatError("Casual Girl part identifiers must be unique strings")
        if category not in WARDROBE_CATEGORIES:
            raise ArdyFormatError(f"unsupported Casual Girl category: {category!r}")
        identifiers.add(identifier)
        part_path = _safe_manifest_file(root_path, raw_part.get("file"))
        with np.load(part_path, allow_pickle=False) as archive:
            missing = sorted(set(WARDROBE_REQUIRED_ARRAYS).difference(archive.files))
            if missing:
                raise ArdyFormatError(
                    f"part {identifier} is missing arrays: {', '.join(missing)}"
                )
            vertices = np.asarray(archive["vertices"], dtype=np.float32)
            names = _strings(archive["bone_names"])
            positions = np.asarray(archive["bind_bone_positions"], dtype=np.float64)
            wxyzs = np.asarray(archive["bind_bone_wxyzs"], dtype=np.float64)
            weights = _normalise_dense_weights(
                archive["skin_weights"], len(vertices), len(names)
            )
            faces = _triangles(archive["faces"], len(vertices), identifier)
        if vertices.ndim != 2 or vertices.shape[1] != 3 or not len(vertices):
            raise ArdyFormatError(f"part {identifier} vertices must have shape (V, 3)")
        if not np.isfinite(vertices).all():
            raise ArdyFormatError(f"part {identifier} contains non-finite vertices")
        matrices = matrix_from_position_wxyz(positions, wxyzs)
        if reference_names is None:
            reference_names = names
            reference_matrices = matrices
        elif names != reference_names or not np.allclose(
            matrices, reference_matrices, atol=1e-5, rtol=1e-5
        ):
            raise ArdyFormatError("all Casual Girl NPZ parts must share one bind skeleton")
        parts.append(
            SkinPart(
                identifier=identifier,
                label=str(raw_part.get("label") or identifier),
                category=category,
                vertices=vertices,
                faces=faces,
                weights=weights,
                bone_names=names,
                bind_matrices=matrices,
                color=_color(raw_part.get("color")),
                source_name=part_path.name,
            )
        )
    return WardrobeManifest(
        character_id="casual-girl",
        display_name=str(raw.get("display_name") or "Casual Girl"),
        root=root_path,
        parts=tuple(parts),
    )


def slug(value: str, fallback: str = "mesh") -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip("._-")
    return cleaned[:80] or fallback


def infer_fbx_category(path: str | Path) -> str:
    # Parent folders often carry the useful modular category even when the
    # seller's FBX filename is only an opaque asset identifier.
    value = str(Path(path)).casefold()
    rules = (
        ("hair", ("hair", "brow", "lash")),
        ("feet", ("shoe", "boot", "foot", "sock")),
        ("underwear", ("underwear", "bra", "brief", "panty")),
        ("top", ("shirt", "top", "jacket", "coat", "blouse", "sweater")),
        ("bottom", ("pant", "jean", "skirt", "short", "trouser")),
        ("body", ("body", "base", "skin", "character")),
    )
    for category, tokens in rules:
        if any(token in value for token in tokens):
            return category
    return "body"


def discover_fbx(root: str | Path) -> tuple[Path, ...]:
    root_path = Path(root).expanduser()
    if not root_path.is_dir() or root_path.is_symlink():
        raise ArdyFormatError("Casual Girl FBX root must be a real directory")
    root_path = root_path.resolve()
    files = tuple(
        sorted(
            (
                item.resolve()
                for item in root_path.rglob("*")
                if item.is_file() and not item.is_symlink() and item.suffix.casefold() == ".fbx"
            ),
            key=lambda path: str(path.relative_to(root_path)).casefold(),
        )
    )
    if not files:
        raise ArdyFormatError("Casual Girl FBX root contains no FBX files")
    return files


def choose_body_fbx(paths: Iterable[Path], explicit: str | Path | None = None) -> Path:
    candidates = tuple(paths)
    if not candidates:
        raise ArdyFormatError("no Casual Girl FBX candidates were supplied")
    if explicit:
        requested = Path(explicit).expanduser().resolve()
        if requested not in candidates:
            raise ArdyFormatError("explicit body FBX is outside the discovered FBX set")
        return requested

    def score(path: Path) -> tuple[int, str]:
        stem = path.stem.casefold()
        value = 0
        for token, points in (
            ("body", 100), ("base", 80), ("character", 60), ("skin", 50),
            ("combined", 20), ("hair", -80), ("shoe", -80), ("top", -60),
            ("pant", -60), ("skirt", -60),
        ):
            if token in stem:
                value += points
        return value, str(path).casefold()

    return max(candidates, key=score)


def staging_destination(staging_root: str | Path, filename: str) -> Path:
    root = Path(staging_root).expanduser()
    if not root.is_dir() or root.is_symlink():
        raise ArdyFormatError("staging root must be an existing real directory")
    root = root.resolve()
    if Path(filename).name != filename or not filename.casefold().endswith(".npz"):
        raise ArdyFormatError("staging filename must be a simple .npz name")
    destination = root / filename
    if destination.exists() or destination.is_symlink():
        raise ArdyFormatError("staging export refuses to overwrite an existing file")
    return destination


def write_staging_npz(
    destination: Path,
    *,
    vertices: np.ndarray,
    faces: np.ndarray,
    skin_weights: np.ndarray,
    bind_bone_positions: np.ndarray,
    bind_bone_wxyzs: np.ndarray,
    bone_names: Iterable[str],
    identifier: str,
    category: str,
) -> None:
    """Atomically create, but never replace, a wardrobe-compatible NPZ."""
    destination = staging_destination(destination.parent, destination.name)
    names = tuple(str(name) for name in bone_names)
    vertices_array = np.asarray(vertices, dtype=np.float32)
    weights_array = _normalise_dense_weights(
        skin_weights, len(vertices_array), len(names)
    )
    faces_array = _triangles(faces, len(vertices_array), identifier)
    if category not in WARDROBE_CATEGORIES:
        raise ArdyFormatError("staging export category is unsupported")
    matrices = matrix_from_position_wxyz(bind_bone_positions, bind_bone_wxyzs)
    _validate_affine(matrices, len(names), "staging bind matrices")

    descriptor = tempfile.NamedTemporaryFile(
        mode="wb", prefix=".ardy-blender-", suffix=".npz", dir=destination.parent,
        delete=False,
    )
    temporary = Path(descriptor.name)
    try:
        with descriptor:
            np.savez_compressed(
                descriptor,
                vertices=vertices_array,
                faces=faces_array,
                skin_weights=weights_array,
                bind_bone_positions=np.asarray(bind_bone_positions, dtype=np.float32),
                bind_bone_wxyzs=np.asarray(bind_bone_wxyzs, dtype=np.float32),
                bone_names=np.asarray(names),
                source_identifier=np.asarray(str(identifier)),
                category=np.asarray(category),
            )
            descriptor.flush()
            os.fsync(descriptor.fileno())
        # Hard-link publication is atomic and fails if another writer won.
        os.link(temporary, destination)
    except FileExistsError as exc:
        raise ArdyFormatError("staging export refuses to overwrite an existing file") from exc
    finally:
        temporary.unlink(missing_ok=True)
