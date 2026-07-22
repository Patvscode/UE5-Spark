#!/usr/bin/env python3
"""Build a private, exact Core27 glTF skeleton source for Unreal retargeting.

The generated mesh is deliberately only a set of tiny weighted triangles.  It
exists to make Unreal import and retain every bone in the official ARDY Core27
hierarchy; it is never rendered in the shipped avatar.  The ARDY source asset
is read at build time and neither it nor the generated GLB is committed.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import struct
import tempfile
from typing import Iterable, Sequence

import numpy as np


ARDY_REVISION = "693f74d13b3d04a0a22ce127ee79c929dd89756b"
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
    -1,
    0,
    1,
    2,
    3,
    4,
    5,
    4,
    7,
    8,
    9,
    10,
    10,
    4,
    13,
    14,
    15,
    16,
    16,
    0,
    19,
    20,
    21,
    0,
    23,
    24,
    25,
)
CORE27_CONNECTIONS = tuple(
    (parent, child)
    for child, parent in enumerate(CORE27_PARENTS)
    if parent >= 0
)

GLB_MAGIC = 0x46546C67
GLB_VERSION = 2
JSON_CHUNK = 0x4E4F534A
BIN_CHUNK = 0x004E4942


class Core27SourceError(RuntimeError):
    """Raised when the pinned source asset does not satisfy our sealed contract."""


def _as_strings(values: np.ndarray) -> tuple[str, ...]:
    result: list[str] = []
    for value in values.tolist():
        if isinstance(value, bytes):
            result.append(value.decode("utf-8"))
        else:
            result.append(str(value))
    return tuple(result)


def _validate_source(source: Path) -> np.ndarray:
    if not source.is_file() or source.is_symlink():
        raise Core27SourceError("source must be a real skin_standard.npz file")

    try:
        archive = np.load(source, allow_pickle=False)
    except (OSError, ValueError) as exc:
        raise Core27SourceError(f"could not read the Core27 source: {exc}") from exc

    required = {
        "bind_rig_transform",
        "rig_joint_connections",
        "rig_joint_names",
    }
    missing = sorted(required.difference(archive.files))
    if missing:
        raise Core27SourceError(f"source is missing fields: {', '.join(missing)}")

    names = _as_strings(archive["rig_joint_names"])
    if names != CORE27_NAMES:
        raise Core27SourceError("source joint names/order do not match exact Core27")

    connections = tuple(
        tuple(int(component) for component in row)
        for row in np.asarray(archive["rig_joint_connections"]).tolist()
    )
    if connections != CORE27_CONNECTIONS:
        raise Core27SourceError("source parent connections do not match exact Core27")

    transforms = np.asarray(archive["bind_rig_transform"], dtype=np.float64)
    if transforms.shape != (len(CORE27_NAMES), 4, 4):
        raise Core27SourceError("bind_rig_transform must have shape (27, 4, 4)")
    if not np.isfinite(transforms).all():
        raise Core27SourceError("bind_rig_transform contains a non-finite number")
    if not np.allclose(transforms[:, 3, :], (0.0, 0.0, 0.0, 1.0), atol=1e-6):
        raise Core27SourceError("bind transforms are not affine matrices")

    positions = transforms[:, :3, 3].copy()
    positions -= positions[0]
    height = float(np.max(positions[:, 1]) - np.min(positions[:, 1]))
    if not 1.5 <= height <= 2.2:
        raise Core27SourceError("Core27 neutral skeleton is outside the expected metre scale")
    if not np.allclose(positions[0], 0.0, atol=1e-8):
        raise Core27SourceError("could not root-center the Core27 skeleton")
    return positions


def ardy_to_gltf(position: Sequence[float]) -> tuple[float, float, float]:
    """Convert ARDY (+X left,+Y up,+Z forward) to glTF before UE import.

    Unreal's glTF importer swaps glTF Y/Z.  The resulting Unreal vector is
    therefore (ARDY Z, -ARDY X, ARDY Y), matching the sole runtime conversion.
    """

    x, y, z = (float(component) for component in position)
    return (z, y, -x)


def _align(value: int, alignment: int = 4) -> int:
    return (value + alignment - 1) & ~(alignment - 1)


class _BinaryBuilder:
    def __init__(self) -> None:
        self.data = bytearray()
        self.views: list[dict[str, int]] = []

    def add(self, payload: bytes, *, target: int | None = None) -> int:
        while len(self.data) % 4:
            self.data.append(0)
        offset = len(self.data)
        self.data.extend(payload)
        view: dict[str, int] = {
            "buffer": 0,
            "byteOffset": offset,
            "byteLength": len(payload),
        }
        if target is not None:
            view["target"] = target
        self.views.append(view)
        return len(self.views) - 1


def _pack_floats(values: Iterable[float]) -> bytes:
    flattened = tuple(float(value) for value in values)
    return struct.pack(f"<{len(flattened)}f", *flattened)


def _identity_inverse_bind(global_position: Sequence[float]) -> tuple[float, ...]:
    x, y, z = (float(component) for component in global_position)
    # glTF matrices are column-major.  With identity bone rotations, inverse
    # bind is simply translation by the negated global joint position.
    return (
        1.0,
        0.0,
        0.0,
        0.0,
        0.0,
        1.0,
        0.0,
        0.0,
        0.0,
        0.0,
        1.0,
        0.0,
        -x,
        -y,
        -z,
        1.0,
    )


def build_core27_glb(positions_ardy: np.ndarray) -> bytes:
    if positions_ardy.shape != (len(CORE27_NAMES), 3):
        raise Core27SourceError("positions must have shape (27, 3)")
    if not np.isfinite(positions_ardy).all():
        raise Core27SourceError("positions contain a non-finite number")

    global_positions = tuple(ardy_to_gltf(row) for row in positions_ardy)
    local_positions: list[tuple[float, float, float]] = []
    for joint, parent in enumerate(CORE27_PARENTS):
        current = global_positions[joint]
        if parent < 0:
            local_positions.append(current)
        else:
            ancestor = global_positions[parent]
            local_positions.append(
                tuple(current[axis] - ancestor[axis] for axis in range(3))
            )

    nodes: list[dict[str, object]] = []
    for joint, (name, translation) in enumerate(zip(CORE27_NAMES, local_positions)):
        node: dict[str, object] = {
            "name": name,
            "translation": [float(component) for component in translation],
            "rotation": [0.0, 0.0, 0.0, 1.0],
        }
        children = [
            child
            for child, parent in enumerate(CORE27_PARENTS)
            if parent == joint
        ]
        if children:
            node["children"] = children
        nodes.append(node)

    # Give every bone a small, non-degenerate weighted triangle.  The hidden
    # source mesh is never visible, but these weights prevent importer pruning.
    triangle_radius = 0.002
    vertices: list[tuple[float, float, float]] = []
    joints: list[tuple[int, int, int, int]] = []
    weights: list[tuple[float, float, float, float]] = []
    indices: list[int] = []
    for joint, center in enumerate(global_positions):
        base = len(vertices)
        vertices.extend(
            (
                (center[0] + triangle_radius, center[1], center[2]),
                (center[0], center[1] + triangle_radius, center[2]),
                (center[0], center[1], center[2] + triangle_radius),
            )
        )
        joints.extend(((joint, 0, 0, 0),) * 3)
        weights.extend(((1.0, 0.0, 0.0, 0.0),) * 3)
        indices.extend((base, base + 1, base + 2))

    binary = _BinaryBuilder()
    position_view = binary.add(
        _pack_floats(component for vertex in vertices for component in vertex),
        target=34962,
    )
    joints_view = binary.add(
        struct.pack(
            f"<{len(joints) * 4}H",
            *(component for group in joints for component in group),
        ),
        target=34962,
    )
    weights_view = binary.add(
        _pack_floats(component for group in weights for component in group),
        target=34962,
    )
    indices_view = binary.add(
        struct.pack(f"<{len(indices)}H", *indices),
        target=34963,
    )
    inverse_bind_view = binary.add(
        _pack_floats(
            component
            for position in global_positions
            for component in _identity_inverse_bind(position)
        )
    )

    minimum = [min(vertex[axis] for vertex in vertices) for axis in range(3)]
    maximum = [max(vertex[axis] for vertex in vertices) for axis in range(3)]
    accessors = [
        {
            "bufferView": position_view,
            "componentType": 5126,
            "count": len(vertices),
            "type": "VEC3",
            "min": minimum,
            "max": maximum,
        },
        {
            "bufferView": joints_view,
            "componentType": 5123,
            "count": len(joints),
            "type": "VEC4",
        },
        {
            "bufferView": weights_view,
            "componentType": 5126,
            "count": len(weights),
            "type": "VEC4",
        },
        {
            "bufferView": indices_view,
            "componentType": 5123,
            "count": len(indices),
            "type": "SCALAR",
            "min": [0],
            "max": [max(indices)],
        },
        {
            "bufferView": inverse_bind_view,
            "componentType": 5126,
            "count": len(CORE27_NAMES),
            "type": "MAT4",
        },
    ]

    mesh_node = len(nodes)
    nodes.append({"name": "Core27SourceMesh", "mesh": 0, "skin": 0})
    document = {
        "asset": {
            "version": "2.0",
            "generator": "UE5-Spark exact Core27 source generator",
            "extras": {
                "ardyRevision": ARDY_REVISION,
                "sourceSkeleton": "Core27",
                "sourceCoordinateSystem": "ardy-right-handed-x-left-y-up-z-forward-metres",
                "gltfConversion": "x=z_ardy,y=y_ardy,z=-x_ardy",
                "renderPolicy": "hidden-retarget-source-only",
            },
        },
        "scene": 0,
        "scenes": [{"name": "Core27Source", "nodes": [0, mesh_node]}],
        "nodes": nodes,
        "skins": [
            {
                "name": "Core27",
                "inverseBindMatrices": 4,
                "skeleton": 0,
                "joints": list(range(len(CORE27_NAMES))),
            }
        ],
        "meshes": [
            {
                "name": "Core27SourceMesh",
                "primitives": [
                    {
                        "attributes": {
                            "POSITION": 0,
                            "JOINTS_0": 1,
                            "WEIGHTS_0": 2,
                        },
                        "indices": 3,
                        "mode": 4,
                    }
                ],
            }
        ],
        "accessors": accessors,
        "bufferViews": binary.views,
        "buffers": [{"byteLength": len(binary.data)}],
    }

    json_payload = json.dumps(
        document, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    json_payload += b" " * (_align(len(json_payload)) - len(json_payload))
    binary_payload = bytes(binary.data)
    binary_payload += b"\0" * (_align(len(binary_payload)) - len(binary_payload))
    total_length = 12 + 8 + len(json_payload) + 8 + len(binary_payload)
    return b"".join(
        (
            struct.pack("<III", GLB_MAGIC, GLB_VERSION, total_length),
            struct.pack("<II", len(json_payload), JSON_CHUNK),
            json_payload,
            struct.pack("<II", len(binary_payload), BIN_CHUNK),
            binary_payload,
        )
    )


def write_private_glb(source: Path, output: Path) -> None:
    positions = _validate_source(source)
    payload = build_core27_glb(positions)
    if output.suffix.lower() != ".glb":
        raise Core27SourceError("output must end in .glb")
    if output.exists() or output.is_symlink():
        raise Core27SourceError("output already exists; refuse to overwrite it")
    if not output.parent.is_dir() or output.parent.is_symlink():
        raise Core27SourceError("output parent must be an existing real directory")

    descriptor: int | None = None
    temporary: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{output.name}.", dir=output.parent
        )
        temporary = Path(temporary_name)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = None
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, output)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "source",
        type=Path,
        help="pinned ARDY cskel27/skin_standard.npz",
    )
    parser.add_argument(
        "output",
        type=Path,
        help="new private .glb path (must not already exist)",
    )
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    try:
        write_private_glb(arguments.source, arguments.output)
    except Core27SourceError as exc:
        print(f"error: {exc}", file=os.sys.stderr)
        return 1
    print(f"wrote private exact Core27 source: {arguments.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
