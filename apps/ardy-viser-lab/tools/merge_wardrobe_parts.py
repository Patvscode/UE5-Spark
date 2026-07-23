#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 Patrick Mello
# SPDX-License-Identifier: MIT

"""Merge several sealed skinned NPZ pieces into one wardrobe part."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np


REQUIRED = (
    "vertices",
    "faces",
    "skin_weights",
    "bind_bone_positions",
    "bind_bone_wxyzs",
    "bone_names",
)


def load_part(path: Path) -> dict[str, np.ndarray]:
    with np.load(path, allow_pickle=False) as data:
        missing = [key for key in REQUIRED if key not in data]
        if missing:
            raise ValueError(f"{path} is missing: {', '.join(missing)}")
        return {key: np.asarray(data[key]).copy() for key in REQUIRED}


def merge(output: Path, inputs: list[Path], coverage: str) -> None:
    parts = [load_part(path) for path in inputs]
    base = parts[0]
    for path, part in zip(inputs[1:], parts[1:]):
        if not np.array_equal(base["bone_names"], part["bone_names"]):
            raise ValueError(f"{path} has a different bone order")
        position_delta = float(
            np.abs(base["bind_bone_positions"] - part["bind_bone_positions"]).max()
        )
        if position_delta > 1e-5:
            raise ValueError(f"{path} bind positions differ by {position_delta:g}m")
        # q and -q encode the same rotation, so compare absolute quaternion dots.
        rotation_dot = np.abs(
            (base["bind_bone_wxyzs"] * part["bind_bone_wxyzs"]).sum(axis=1)
        )
        if float(rotation_dot.min()) < 0.99999:
            raise ValueError(f"{path} has an incompatible bind rotation")

    vertices: list[np.ndarray] = []
    faces: list[np.ndarray] = []
    weights: list[np.ndarray] = []
    vertex_offset = 0
    for part in parts:
        vertices.append(np.asarray(part["vertices"], dtype=np.float32))
        faces.append(np.asarray(part["faces"], dtype=np.uint32) + vertex_offset)
        weights.append(np.asarray(part["skin_weights"], dtype=np.float32))
        vertex_offset += len(part["vertices"])

    output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        output,
        vertices=np.concatenate(vertices),
        faces=np.concatenate(faces),
        skin_weights=np.concatenate(weights),
        bind_bone_positions=np.asarray(base["bind_bone_positions"], dtype=np.float32),
        bind_bone_wxyzs=np.asarray(base["bind_bone_wxyzs"], dtype=np.float32),
        bone_names=base["bone_names"],
        schema_version=np.asarray(1, dtype=np.uint32),
        coordinate_system=np.asarray("right-handed-y-up-z-forward-meters"),
        coverage=np.asarray(coverage),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("inputs", type=Path, nargs="+")
    parser.add_argument(
        "--coverage",
        default="merged modular wardrobe part",
        help="human-readable private build provenance",
    )
    args = parser.parse_args()
    if len(args.inputs) < 2:
        parser.error("at least two inputs are required")
    merge(
        args.output.expanduser().resolve(),
        [path.expanduser().resolve() for path in args.inputs],
        args.coverage,
    )
    print(f"MERGED_WARDROBE_OK={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
