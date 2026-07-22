from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts/generate-core27-source-glb.py"
SPEC = importlib.util.spec_from_file_location("generate_core27_source_glb", SCRIPT)
assert SPEC and SPEC.loader
GENERATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GENERATOR)


def parse_glb(payload: bytes) -> tuple[dict, bytes]:
    magic, version, total = struct.unpack_from("<III", payload)
    if magic != GENERATOR.GLB_MAGIC or version != 2 or total != len(payload):
        raise AssertionError("invalid GLB header")
    json_length, json_kind = struct.unpack_from("<II", payload, 12)
    if json_kind != GENERATOR.JSON_CHUNK:
        raise AssertionError("missing JSON chunk")
    json_start = 20
    json_end = json_start + json_length
    document = json.loads(payload[json_start:json_end].decode("utf-8"))
    binary_length, binary_kind = struct.unpack_from("<II", payload, json_end)
    if binary_kind != GENERATOR.BIN_CHUNK:
        raise AssertionError("missing binary chunk")
    binary_start = json_end + 8
    binary = payload[binary_start : binary_start + binary_length]
    return document, binary


def source_positions() -> np.ndarray:
    positions = np.zeros((27, 3), dtype=np.float64)
    positions[:, 1] = np.linspace(0.0, 1.7, 27)
    positions[7:13, 0] = np.linspace(-0.1, -0.8, 6)
    positions[13:19, 0] = np.linspace(0.1, 0.8, 6)
    positions[19:23, 0] = -0.1
    positions[23:27, 0] = 0.1
    return positions


class GenerateCore27SourceGlbTests(unittest.TestCase):
    def write_source(self, path: Path, *, wrong_name: bool = False) -> None:
        transforms = np.repeat(np.eye(4)[None, :, :], 27, axis=0)
        transforms[:, :3, 3] = source_positions() + (0.0, 0.97, 0.0)
        names = list(GENERATOR.CORE27_NAMES)
        if wrong_name:
            names[10] = "WrongHand"
        np.savez(
            path,
            bind_rig_transform=transforms,
            rig_joint_connections=np.asarray(GENERATOR.CORE27_CONNECTIONS),
            rig_joint_names=np.asarray(names),
        )

    def test_exact_hierarchy_basis_and_weighted_mesh(self) -> None:
        payload = GENERATOR.build_core27_glb(source_positions())
        document, binary = parse_glb(payload)

        self.assertEqual(document["asset"]["extras"]["ardyRevision"], GENERATOR.ARDY_REVISION)
        self.assertEqual(document["skins"][0]["joints"], list(range(27)))
        self.assertEqual(document["skins"][0]["skeleton"], 0)
        self.assertEqual(len(document["nodes"]), 28)
        self.assertEqual(
            [node["name"] for node in document["nodes"][:27]],
            list(GENERATOR.CORE27_NAMES),
        )
        for child, parent in enumerate(GENERATOR.CORE27_PARENTS):
            if parent >= 0:
                self.assertIn(child, document["nodes"][parent]["children"])

        attributes = document["meshes"][0]["primitives"][0]["attributes"]
        self.assertEqual(set(attributes), {"POSITION", "JOINTS_0", "WEIGHTS_0"})
        self.assertEqual(document["accessors"][0]["count"], 81)
        self.assertEqual(document["accessors"][4]["count"], 27)
        declared_binary_length = document["buffers"][0]["byteLength"]
        self.assertLessEqual(declared_binary_length, len(binary))
        self.assertLess(len(binary) - declared_binary_length, 4)
        self.assertEqual(binary[declared_binary_length:], b"\0" * (len(binary) - declared_binary_length))

        # ARDY left -> Unreal left after glTF import's Y/Z swap.
        self.assertEqual(GENERATOR.ardy_to_gltf((1.0, 2.0, 3.0)), (3.0, 2.0, -1.0))

    def test_sealed_source_validation_and_private_atomic_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            source = directory / "skin_standard.npz"
            output = directory / "Core27.glb"
            self.write_source(source)
            GENERATOR.write_private_glb(source, output)
            self.assertTrue(output.is_file())
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            document, _ = parse_glb(output.read_bytes())
            self.assertEqual(document["skins"][0]["name"], "Core27")
            with self.assertRaisesRegex(GENERATOR.Core27SourceError, "refuse to overwrite"):
                GENERATOR.write_private_glb(source, output)

    def test_mismatched_joint_order_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            source = directory / "bad.npz"
            self.write_source(source, wrong_name=True)
            with self.assertRaisesRegex(GENERATOR.Core27SourceError, "names/order"):
                GENERATOR._validate_source(source)


if __name__ == "__main__":
    unittest.main()
