from __future__ import annotations

import hashlib
import importlib.util
import math
import random
import sys
import unittest
from copy import deepcopy
from pathlib import Path

try:
    import numpy as np
    import torch
except ModuleNotFoundError:
    np = None  # type: ignore[assignment]
    torch = None  # type: ignore[assignment]


SERVICE_ROOT = Path(__file__).resolve().parents[1] / "service"
sys.path.insert(0, str(SERVICE_ROOT))

from motion_catalog import GENERATED_BEHAVIORS  # noqa: E402
from pose_protocol import (  # noqa: E402
    CONTACT_ORDER,
    COORDINATE_SYSTEM,
    CORE27_HIERARCHY,
    CORE27_JOINTS,
    PROTOCOL_VERSION,
    PoseRequest,
    ProtocolError,
    QuaternionHemisphereTracker,
    ardy_quaternion_to_unreal,
    ardy_translation_to_unreal_cm,
    quaternion,
    source_descriptor,
    validate_batch,
)
from providers import (  # noqa: E402
    ArdyPoseProvider,
    DYNAMIC_PROMPT_CACHE_SIZE,
    MAX_CFG_WEIGHT,
    MIN_CFG_WEIGHT,
    MockPoseProvider,
    PromptEmbeddingCache,
    _generation_window_frames,
    _serialize_contact_values,
    _validate_ardy_output_shapes,
    cfg_weight_for_intensity,
    retained_history_for_behavior,
)


EXPECTED_GENERATED_BEHAVIORS = (
    "idle",
    "listen",
    "explain",
    "wave",
    "jog_in_place",
    "run_in_place",
    "jumping_jacks",
    "stretch",
    "dance_relaxed",
)


class FakeHistory:
    def __init__(self, frames: int) -> None:
        self.shape = (1, frames, 148)


class ShapedValue:
    def __init__(self, shape: tuple[int, ...]) -> None:
        self.shape = shape


class FakeTextEncoder:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def __call__(self, prompts: list[str]):
        self.prompts.extend(prompts)
        value = float(len(self.prompts))
        return torch.full((1, 1, 4096), value), [1]


def _quaternion_matrix(value: list[float]) -> list[list[float]]:
    x_value, y_value, z_value, w_value = value
    magnitude = math.sqrt(sum(component * component for component in value))
    x_value /= magnitude
    y_value /= magnitude
    z_value /= magnitude
    w_value /= magnitude
    return [
        [
            1.0 - 2.0 * (y_value * y_value + z_value * z_value),
            2.0 * (x_value * y_value - z_value * w_value),
            2.0 * (x_value * z_value + y_value * w_value),
        ],
        [
            2.0 * (x_value * y_value + z_value * w_value),
            1.0 - 2.0 * (x_value * x_value + z_value * z_value),
            2.0 * (y_value * z_value - x_value * w_value),
        ],
        [
            2.0 * (x_value * z_value - y_value * w_value),
            2.0 * (y_value * z_value + x_value * w_value),
            1.0 - 2.0 * (x_value * x_value + y_value * y_value),
        ],
    ]


def _matrix_multiply(
    left: list[list[float]], right: list[list[float]]
) -> list[list[float]]:
    return [
        [sum(left[row][index] * right[index][column] for index in range(3)) for column in range(3)]
        for row in range(3)
    ]


def _transpose(value: list[list[float]]) -> list[list[float]]:
    return [[value[column][row] for column in range(3)] for row in range(3)]


class PoseProtocolTests(unittest.TestCase):
    def test_generation_window_includes_bounded_history(self) -> None:
        self.assertEqual(_generation_window_frames(None), 8)
        self.assertEqual(_generation_window_frames(FakeHistory(8)), 16)
        self.assertEqual(_generation_window_frames(FakeHistory(192)), 200)
        with self.assertRaises(RuntimeError):
            _generation_window_frames(FakeHistory(200))

    def test_official_inverse_output_shapes_are_sealed(self) -> None:
        values = {
            "local rotations": ShapedValue((1, 8, 27, 3, 3)),
            "root rotations": ShapedValue((1, 8, 3, 3)),
            "root positions": ShapedValue((1, 8, 3)),
            "posed joints": ShapedValue((1, 8, 27, 3)),
            "foot contacts": ShapedValue((1, 8, 4)),
        }
        _validate_ardy_output_shapes(values)
        values["posed joints"] = ShapedValue((1, 8, 26, 3))
        with self.assertRaises(RuntimeError):
            _validate_ardy_output_shapes(values)
        del values["posed joints"]
        with self.assertRaises(RuntimeError):
            _validate_ardy_output_shapes(values)

    def test_behavior_change_retains_same_history_object(self) -> None:
        history = FakeHistory(32)
        retained = retained_history_for_behavior(history, "idle", "jumping_jacks")
        self.assertIs(retained, history)
        with self.assertRaises(RuntimeError):
            retained_history_for_behavior(history, "idle", "not_reviewed")

    def test_intensity_controls_bounded_cfg_weight(self) -> None:
        self.assertEqual(cfg_weight_for_intensity(0.0), MIN_CFG_WEIGHT)
        self.assertEqual(cfg_weight_for_intensity(1.0), MAX_CFG_WEIGHT)
        self.assertEqual(cfg_weight_for_intensity(0.5), 2.0)
        self.assertLess(cfg_weight_for_intensity(0.25), cfg_weight_for_intensity(0.75))
        for invalid in (-0.1, 1.1, float("nan"), True):
            with self.subTest(invalid=invalid), self.assertRaises(ProtocolError):
                cfg_weight_for_intensity(invalid)  # type: ignore[arg-type]

    def test_boolean_contacts_are_serialized_in_explicit_order(self) -> None:
        self.assertEqual(CONTACT_ORDER, ("left_heel", "left_toe", "right_heel", "right_toe"))
        values = _serialize_contact_values([True, False, True, False])
        self.assertEqual(values, [1.0, 0.0, 1.0, 0.0])
        self.assertTrue(all(type(value) is float for value in values))
        with self.assertRaises(RuntimeError):
            _serialize_contact_values([[True], [False], [True], [False]])
        with self.assertRaises(RuntimeError):
            _serialize_contact_values([0.0, 0.0, 0.0, 1.1])

    def test_core27_hierarchy_is_exact_and_ordered(self) -> None:
        self.assertEqual(len(CORE27_HIERARCHY), 27)
        self.assertEqual(tuple(name for name, _ in CORE27_HIERARCHY), CORE27_JOINTS)
        self.assertEqual(CORE27_HIERARCHY[0], ("Hips", None))
        self.assertEqual(CORE27_HIERARCHY[-1], ("LeftToeBase", "LeftFoot"))

    def test_shared_catalog_is_the_generated_behavior_authority(self) -> None:
        self.assertEqual(GENERATED_BEHAVIORS, EXPECTED_GENERATED_BEHAVIORS)
        for behavior in GENERATED_BEHAVIORS:
            self.assertEqual(PoseRequest.from_json({"behavior": behavior}).behavior, behavior)

    def test_request_keeps_internal_behavior_allowlist_and_accepts_open_prompt(self) -> None:
        request = PoseRequest.from_json({
            "behavior": " WAVE ",
            "intensity": 0.8,
            "duration": 2,
            "prompt": "  squat twice, then stand naturally  ",
        })
        self.assertEqual(request.behavior, "wave")
        self.assertEqual(request.prompt, "squat twice, then stand naturally")
        with self.assertRaises(ProtocolError):
            PoseRequest.from_json({"behavior": "execute arbitrary prompt"})
        with self.assertRaises(ProtocolError):
            PoseRequest.from_json({"behavior": "idle", "prompt": "   "})
        with self.assertRaises(ProtocolError):
            PoseRequest.from_json({"behavior": "idle", "prompt": "x" * 513})
        with self.assertRaises(ProtocolError):
            PoseRequest.from_json({"behavior": "idle", "prompt": 3})

    @unittest.skipIf(torch is None, "torch is unavailable")
    def test_dynamic_prompt_cache_is_sha256_keyed_bounded_and_idempotent(self) -> None:
        encoder = FakeTextEncoder()
        cache = PromptEmbeddingCache(encoder, torch, "cpu")
        first, prompt_id, cached = cache.resolve("squat")
        second, repeated_id, repeated_cached = cache.resolve("squat")
        self.assertFalse(cached)
        self.assertTrue(repeated_cached)
        self.assertEqual(prompt_id, hashlib.sha256(b"squat").hexdigest())
        self.assertEqual(repeated_id, prompt_id)
        self.assertIs(second, first)
        self.assertEqual(encoder.prompts, ["squat"])

        for index in range(DYNAMIC_PROMPT_CACHE_SIZE):
            cache.resolve(f"movement {index}")
        self.assertEqual(cache.count, DYNAMIC_PROMPT_CACHE_SIZE)
        cache.resolve("squat")
        self.assertEqual(encoder.prompts.count("squat"), 2)

    @unittest.skipIf(
        np is None or importlib.util.find_spec("scipy") is None,
        "numpy/scipy are unavailable",
    )
    def test_serialization_locks_root_and_hips_rotations_to_identity(self) -> None:
        provider = object.__new__(ArdyPoseProvider)
        provider._hemispheres = QuaternionHemisphereTracker()
        provider._time = 0.0
        identity_matrix = np.eye(3, dtype=np.float32)
        tilted_matrix = np.asarray(
            [[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]],
            dtype=np.float32,
        )
        matrices = np.tile(identity_matrix, (8, 27, 1, 1))
        matrices[:, 0] = tilted_matrix
        root_matrices = np.tile(tilted_matrix, (8, 1, 1))
        roots = np.zeros((8, 3), dtype=np.float32)
        positions = np.zeros((8, 27, 3), dtype=np.float32)
        contacts = np.zeros((8, 4), dtype=np.float32)

        frames, _tracker, _next_time = provider._serialize_frames(
            matrices,
            root_matrices,
            roots,
            positions,
            contacts,
        )
        for frame in frames:
            self.assertEqual(frame["root"][3:], [0.0, 0.0, 0.0, 1.0])
            self.assertEqual(frame["joints"][0], [0.0, 0.0, 0.0, 1.0])

    def test_mock_batch_is_v2_core27_with_positions_and_face_exclusion(self) -> None:
        provider = MockPoseProvider()
        batch = provider.generate(PoseRequest("wave", 1.0, 1.0, 0))
        self.assertEqual(batch["version"], PROTOCOL_VERSION)
        self.assertEqual(batch["coordinateSystem"], COORDINATE_SYSTEM)
        self.assertEqual(batch["source"], source_descriptor())
        self.assertEqual(len(batch["frames"]), 8)
        self.assertEqual(len(batch["frames"][0]["joints"]), 27)
        self.assertEqual(len(batch["frames"][0]["positions"]), 27)
        self.assertEqual(batch["frames"][0]["root"][:3], batch["frames"][0]["positions"][0])
        neck = CORE27_JOINTS.index("Neck")
        head = CORE27_JOINTS.index("Head")
        for frame in batch["frames"]:
            self.assertEqual(frame["joints"][neck], [0.0, 0.0, 0.0, 1.0])
            self.assertEqual(frame["joints"][head], [0.0, 0.0, 0.0, 1.0])

    def test_sequence_advances_past_consumer(self) -> None:
        provider = MockPoseProvider()
        first = provider.generate(PoseRequest("idle", 0.5, 1.0, 0))
        second = provider.generate(PoseRequest("idle", 0.5, 1.0, first["sequence"] + 9))
        self.assertEqual(second["sequence"], first["sequence"] + 10)

    def test_translation_and_golden_axis_rotations(self) -> None:
        self.assertEqual(ardy_translation_to_unreal_cm([2, 3, 4]), [400.0, -200.0, 300.0])
        sine = math.sqrt(0.5)
        cosine = math.sqrt(0.5)
        golden = (
            (quaternion((1.0, 0.0, 0.0), math.pi / 2.0), [0.0, sine, 0.0, cosine]),
            (quaternion((0.0, 1.0, 0.0), math.pi / 2.0), [0.0, 0.0, -sine, cosine]),
            (quaternion((0.0, 0.0, 1.0), math.pi / 2.0), [-sine, 0.0, 0.0, cosine]),
        )
        for source, expected in golden:
            converted = ardy_quaternion_to_unreal(source)
            for actual_component, expected_component in zip(converted, expected):
                self.assertAlmostEqual(actual_component, expected_component, places=12)

    def test_random_quaternion_conversion_matches_basis_matrix(self) -> None:
        # Vector map (z, -x, y). Its determinant is -1, which is why rotation
        # quaternions cannot use the same component permutation directly.
        basis = [[0.0, 0.0, 1.0], [-1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
        generator = random.Random(0xA7D2)
        for sample_index in range(512):
            source = [generator.uniform(-1.0, 1.0) for _ in range(4)]
            if sum(component * component for component in source) < 1e-8:
                source[3] = 1.0
            expected = _matrix_multiply(
                _matrix_multiply(basis, _quaternion_matrix(source)),
                _transpose(basis),
            )
            actual = _quaternion_matrix(ardy_quaternion_to_unreal(source))
            for row in range(3):
                for column in range(3):
                    self.assertAlmostEqual(
                        actual[row][column],
                        expected[row][column],
                        places=11,
                        msg=f"sample={sample_index} row={row} column={column}",
                    )

    def test_hemisphere_tracker_stabilizes_across_batches(self) -> None:
        tracker = QuaternionHemisphereTracker()
        root = quaternion((0.2, 0.7, -0.1), 1.1)
        joints = [[0.0, 0.0, 0.0, 1.0] for _ in CORE27_JOINTS]
        first_root, first_joints = tracker.stabilize(root, joints)
        second_root, second_joints = tracker.stabilize(
            [-component for component in root],
            [[-component for component in rotation] for rotation in joints],
        )
        self.assertEqual(second_root, first_root)
        self.assertEqual(second_joints, first_joints)

    def test_malformed_source_positions_quaternions_and_times_fail_closed(self) -> None:
        provider = MockPoseProvider()
        batch = provider.generate(PoseRequest("idle", 0.5, 1.0, 0))

        repeated_time = deepcopy(batch)
        repeated_time["frames"][1]["time"] = repeated_time["frames"][0]["time"]
        with self.assertRaises(ProtocolError):
            validate_batch(repeated_time)

        wrong_joint_count = deepcopy(batch)
        wrong_joint_count["frames"][0]["joints"].pop()
        with self.assertRaises(ProtocolError):
            validate_batch(wrong_joint_count)

        wrong_position_count = deepcopy(batch)
        wrong_position_count["frames"][0]["positions"].pop()
        with self.assertRaises(ProtocolError):
            validate_batch(wrong_position_count)

        inconsistent_root_position = deepcopy(batch)
        inconsistent_root_position["frames"][0]["positions"][0][0] += 0.01
        with self.assertRaises(ProtocolError):
            validate_batch(inconsistent_root_position)

        inconsistent_root_rotation = deepcopy(batch)
        inconsistent_root_rotation["frames"][0]["joints"][0] = quaternion(
            (1.0, 0.0, 0.0), 0.1
        )
        with self.assertRaises(ProtocolError):
            validate_batch(inconsistent_root_rotation)

        wrong_source = deepcopy(batch)
        wrong_source["source"]["contactOrder"][0] = "right_heel"
        with self.assertRaises(ProtocolError):
            validate_batch(wrong_source)

        non_finite = deepcopy(batch)
        non_finite["frames"][0]["root"][0] = float("nan")
        with self.assertRaises(ProtocolError):
            validate_batch(non_finite)

        non_normalized = deepcopy(batch)
        non_normalized["frames"][0]["joints"][0] = [0.0, 0.0, 0.0, 0.5]
        with self.assertRaises(ProtocolError):
            validate_batch(non_normalized)

        sign_jump = deepcopy(batch)
        sign_jump["frames"][1]["joints"][0] = [
            -component for component in sign_jump["frames"][1]["joints"][0]
        ]
        with self.assertRaises(ProtocolError):
            validate_batch(sign_jump)


if __name__ == "__main__":
    unittest.main()
