#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 Patrick Mello
# SPDX-License-Identifier: MIT

"""Convert an Unreal skeletal FBX into the sealed Casual Girl wardrobe NPZ.

The native ufbx helper performs lossless FBX parsing into a private raw
directory. This script then collapses the UE5 mannequin skeleton to the exact
27-joint ARDY Core27 order and writes the arrays consumed by wardrobe.py.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Final

import numpy as np


CORE27: Final[tuple[str, ...]] = (
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

# Bind transforms are sampled from these real UE5 mannequin joints. Extra
# twist/spine/finger weights are collapsed below without changing the bind rig.
CORE_BIND_SOURCE: Final[dict[str, str]] = {
    "Hips": "pelvis",
    "Spine": "spine_01",
    "Spine1": "spine_02",
    "Spine2": "spine_03",
    "Spine3": "spine_05",
    "Neck": "neck_01",
    "Head": "head",
    "RightShoulder": "clavicle_r",
    "RightArm": "upperarm_r",
    "RightForeArm": "lowerarm_r",
    "RightHand": "hand_r",
    "RightHandEnd": "middle_03_r",
    "RightHandThumb1": "thumb_01_r",
    "LeftShoulder": "clavicle_l",
    "LeftArm": "upperarm_l",
    "LeftForeArm": "lowerarm_l",
    "LeftHand": "hand_l",
    "LeftHandEnd": "middle_03_l",
    "LeftHandThumb1": "thumb_01_l",
    "RightUpLeg": "thigh_r",
    "RightLeg": "calf_r",
    "RightFoot": "foot_r",
    "RightToeBase": "ball_r",
    "LeftUpLeg": "thigh_l",
    "LeftLeg": "calf_l",
    "LeftFoot": "foot_l",
    "LeftToeBase": "ball_l",
}

DIRECT_SOURCE_TO_CORE: Final[dict[str, str]] = {
    source.lower(): target for target, source in CORE_BIND_SOURCE.items()
}
DIRECT_SOURCE_TO_CORE.update(
    {
        "root": "Hips",
        "spine_04": "Spine3",
        "neck_02": "Neck",
    }
)
for side, label in (("r", "Right"), ("l", "Left")):
    for prefix in ("index", "middle", "ring", "pinky"):
        for suffix in ("metacarpal", "01", "02", "03"):
            DIRECT_SOURCE_TO_CORE[f"{prefix}_{suffix}_{side}"] = f"{label}HandEnd"
    for suffix in ("02", "03"):
        DIRECT_SOURCE_TO_CORE[f"thumb_{suffix}_{side}"] = f"{label}HandThumb1"


@dataclass(frozen=True)
class RawSkin:
    vertices: np.ndarray
    faces: np.ndarray
    influence_indices: np.ndarray
    influence_weights: np.ndarray
    cluster_names: tuple[str, ...]
    cluster_parents: tuple[str, ...]
    cluster_bind_matrices: np.ndarray
    node_parents: dict[str, str]
    node_matrices: dict[str, np.ndarray]
    metadata: dict[str, str]


def _parse_metadata(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if not separator:
            raise ValueError(f"Malformed metadata line: {line!r}")
        result[key] = value
    if result.get("schema_version") != "1":
        raise ValueError(f"Unsupported raw skin schema: {result.get('schema_version')!r}")
    return result


def _read_tsv(path: Path) -> list[list[str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise ValueError(f"Empty TSV file: {path}")
    return [line.split("\t") for line in lines[1:]]


def load_raw_skin(root: Path) -> RawSkin:
    metadata = _parse_metadata(root / "metadata.txt")
    vertex_count = int(metadata["vertex_count"])
    triangle_count = int(metadata["triangle_count"])
    bone_count = int(metadata["bone_count"])
    influence_count = int(metadata["influence_count"])

    vertices = np.fromfile(root / "vertices.f32", dtype="<f4").reshape(vertex_count, 3)
    faces = np.fromfile(root / "faces.u32", dtype="<u4").reshape(triangle_count, 3)
    influence_indices = np.fromfile(
        root / "influence_indices.i32", dtype="<i4"
    ).reshape(vertex_count, influence_count)
    influence_weights = np.fromfile(
        root / "influence_weights.f32", dtype="<f4"
    ).reshape(vertex_count, influence_count)
    bind_matrices = np.fromfile(
        root / "bind_matrices.f32", dtype="<f4"
    ).reshape(bone_count, 4, 4)

    bone_rows = _read_tsv(root / "bones.tsv")
    if len(bone_rows) != bone_count:
        raise ValueError("bones.tsv does not match metadata bone_count")
    cluster_names = tuple(row[1] for row in bone_rows)
    cluster_parents = tuple(row[2] for row in bone_rows)

    node_parents: dict[str, str] = {}
    node_matrices: dict[str, np.ndarray] = {}
    for row in _read_tsv(root / "nodes.tsv"):
        if len(row) != 19:
            raise ValueError(f"Malformed node row for {row[0] if row else '<empty>'}")
        name, parent = row[0], row[1]
        node_parents[name.lower()] = parent.lower()
        node_matrices[name.lower()] = np.asarray(row[3:], dtype=np.float32).reshape(4, 4)

    return RawSkin(
        vertices=vertices,
        faces=faces,
        influence_indices=influence_indices,
        influence_weights=influence_weights,
        cluster_names=cluster_names,
        cluster_parents=cluster_parents,
        cluster_bind_matrices=bind_matrices,
        node_parents=node_parents,
        node_matrices=node_matrices,
        metadata=metadata,
    )


def _target_for_source(source_name: str, parents: dict[str, str]) -> str | None:
    current = source_name.lower()
    visited: set[str] = set()
    while current and current not in visited:
        visited.add(current)
        direct = DIRECT_SOURCE_TO_CORE.get(current)
        if direct is not None:
            return direct
        current = parents.get(current, "")
    return None


def collapse_weights(raw: RawSkin) -> tuple[np.ndarray, dict[str, str]]:
    target_indices = {name: index for index, name in enumerate(CORE27)}
    source_targets: dict[str, str] = {}
    cluster_target_indices = np.empty(len(raw.cluster_names), dtype=np.int64)
    for index, source_name in enumerate(raw.cluster_names):
        target = _target_for_source(source_name, raw.node_parents)
        if target is None:
            raise ValueError(
                f"Skin cluster {source_name!r} has no UE5-to-Core27 mapping or mapped ancestor"
            )
        source_targets[source_name] = target
        cluster_target_indices[index] = target_indices[target]

    result = np.zeros((len(raw.vertices), len(CORE27)), dtype=np.float32)
    valid = raw.influence_indices >= 0
    vertex_grid = np.broadcast_to(
        np.arange(len(raw.vertices), dtype=np.int64)[:, None],
        raw.influence_indices.shape,
    )
    np.add.at(
        result,
        (
            vertex_grid[valid],
            cluster_target_indices[raw.influence_indices[valid]],
        ),
        raw.influence_weights[valid],
    )
    sums = result.sum(axis=1)
    if np.any(sums <= 1e-8):
        bad = np.flatnonzero(sums <= 1e-8)[:10].tolist()
        raise ValueError(f"Vertices have no surviving skin weights: {bad}")
    result /= sums[:, None]
    return result, source_targets


def _orthonormal_rotation(matrix: np.ndarray) -> np.ndarray:
    u, _, vh = np.linalg.svd(matrix.astype(np.float64), full_matrices=False)
    rotation = u @ vh
    if np.linalg.det(rotation) < 0:
        u[:, -1] *= -1
        rotation = u @ vh
    return rotation


def _matrix_to_wxyz(matrix: np.ndarray) -> np.ndarray:
    m = _orthonormal_rotation(matrix[:3, :3])
    trace = float(np.trace(m))
    if trace > 0.0:
        scale = np.sqrt(trace + 1.0) * 2.0
        w = 0.25 * scale
        x = (m[2, 1] - m[1, 2]) / scale
        y = (m[0, 2] - m[2, 0]) / scale
        z = (m[1, 0] - m[0, 1]) / scale
    else:
        diagonal = np.diag(m)
        axis = int(np.argmax(diagonal))
        if axis == 0:
            scale = np.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2.0
            w = (m[2, 1] - m[1, 2]) / scale
            x = 0.25 * scale
            y = (m[0, 1] + m[1, 0]) / scale
            z = (m[0, 2] + m[2, 0]) / scale
        elif axis == 1:
            scale = np.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2.0
            w = (m[0, 2] - m[2, 0]) / scale
            x = (m[0, 1] + m[1, 0]) / scale
            y = 0.25 * scale
            z = (m[1, 2] + m[2, 1]) / scale
        else:
            scale = np.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2.0
            w = (m[1, 0] - m[0, 1]) / scale
            x = (m[0, 2] + m[2, 0]) / scale
            y = (m[1, 2] + m[2, 1]) / scale
            z = 0.25 * scale
    quaternion = np.asarray((w, x, y, z), dtype=np.float64)
    quaternion /= np.linalg.norm(quaternion)
    if quaternion[0] < 0:
        quaternion *= -1
    return quaternion.astype(np.float32)


def build_bind_pose(raw: RawSkin) -> tuple[np.ndarray, np.ndarray]:
    cluster_matrices = {
        name.lower(): raw.cluster_bind_matrices[index]
        for index, name in enumerate(raw.cluster_names)
    }
    positions = np.zeros((len(CORE27), 3), dtype=np.float32)
    rotations = np.zeros((len(CORE27), 4), dtype=np.float32)
    missing: list[str] = []
    for index, target_name in enumerate(CORE27):
        source_name = CORE_BIND_SOURCE[target_name].lower()
        matrix = cluster_matrices.get(source_name)
        if matrix is None:
            matrix = raw.node_matrices.get(source_name)
        if matrix is None:
            missing.append(f"{target_name} <- {source_name}")
            continue
        positions[index] = matrix[:3, 3]
        rotations[index] = _matrix_to_wxyz(matrix)
    if missing:
        raise ValueError("FBX is missing required UE5 bind joints: " + ", ".join(missing))
    return positions, rotations


def convert(raw: RawSkin, output: Path, source_path: Path) -> dict[str, object]:
    weights, source_targets = collapse_weights(raw)
    positions, rotations = build_bind_pose(raw)
    output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        output,
        vertices=np.asarray(raw.vertices, dtype=np.float32),
        faces=np.asarray(raw.faces, dtype=np.uint32),
        skin_weights=weights,
        bind_bone_positions=positions,
        bind_bone_wxyzs=rotations,
        bone_names=np.asarray(CORE27),
        schema_version=np.asarray(1, dtype=np.uint32),
        coordinate_system=np.asarray("right-handed-y-up-z-forward-meters"),
    )
    return {
        "output": str(output),
        "source": str(source_path),
        "mesh": raw.metadata.get("mesh_name", ""),
        "vertices": int(len(raw.vertices)),
        "triangles": int(len(raw.faces)),
        "source_bones": int(len(raw.cluster_names)),
        "target_bones": len(CORE27),
        "source_to_core27": source_targets,
        "bytes": output.stat().st_size,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_fbx", type=Path)
    parser.add_argument("output_npz", type=Path)
    parser.add_argument(
        "--dumper",
        type=Path,
        default=Path(os.environ.get("UFBX_DUMP_SKIN", "ufbx_dump_skin")),
        help="compiled ufbx_dump_skin binary",
    )
    parser.add_argument("--mesh", help="optional exact FBX mesh name")
    parser.add_argument("--keep-raw", type=Path, help="retain the private raw interchange here")
    args = parser.parse_args()

    input_path = args.input_fbx.expanduser().resolve()
    output_path = args.output_npz.expanduser().resolve()
    if not input_path.is_file():
        parser.error(f"FBX does not exist: {input_path}")
    dumper = shutil.which(str(args.dumper))
    if dumper is None:
        parser.error(
            f"ufbx dumper not found: {args.dumper}; run tools/build_ufbx_dumper.sh first"
        )

    if args.keep_raw:
        raw_root = args.keep_raw.expanduser().resolve()
        raw_root.mkdir(parents=True, exist_ok=True)
        temporary = None
    else:
        temporary = tempfile.TemporaryDirectory(prefix="ardy-fbx-")
        raw_root = Path(temporary.name)
    try:
        command = [dumper, str(input_path), str(raw_root)]
        if args.mesh:
            command.append(args.mesh)
        subprocess.run(command, check=True)
        raw = load_raw_skin(raw_root)
        report = convert(raw, output_path, input_path)
        print("CASUAL_GIRL_NPZ_OK=" + json.dumps(report, sort_keys=True))
    finally:
        if temporary is not None:
            temporary.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
