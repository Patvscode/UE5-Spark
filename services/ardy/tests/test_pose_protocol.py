from __future__ import annotations

import sys
import unittest
from copy import deepcopy
from pathlib import Path


SERVICE_ROOT = Path(__file__).resolve().parents[1] / "service"
sys.path.insert(0, str(SERVICE_ROOT))

from pose_protocol import (  # noqa: E402
    CORE27_HIERARCHY,
    CORE27_JOINTS,
    PoseRequest,
    ProtocolError,
    ardy_translation_to_unreal_cm,
    validate_batch,
)
from providers import MockPoseProvider  # noqa: E402


class PoseProtocolTests(unittest.TestCase):
    def test_core27_hierarchy_is_exact_and_ordered(self) -> None:
        self.assertEqual(len(CORE27_HIERARCHY), 27)
        self.assertEqual(tuple(name for name, _ in CORE27_HIERARCHY), CORE27_JOINTS)
        self.assertEqual(CORE27_HIERARCHY[0], ("Hips", None))
        self.assertEqual(CORE27_HIERARCHY[-1], ("LeftToeBase", "LeftFoot"))

    def test_request_is_allowlisted(self) -> None:
        request = PoseRequest.from_json({"behavior": " WAVE ", "intensity": 0.8, "duration": 2})
        self.assertEqual(request.behavior, "wave")
        with self.assertRaises(ProtocolError):
            PoseRequest.from_json({"behavior": "execute arbitrary prompt"})
        with self.assertRaises(ProtocolError):
            PoseRequest.from_json({"behavior": "idle", "prompt": "not allowed"})

    def test_mock_batch_is_core27_and_excludes_head(self) -> None:
        provider = MockPoseProvider()
        batch = provider.generate(PoseRequest("wave", 1.0, 1.0, 0))
        self.assertEqual(len(batch["frames"]), 8)
        self.assertEqual(len(batch["frames"][0]["joints"]), 27)
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

    def test_coordinate_mapping(self) -> None:
        self.assertEqual(ardy_translation_to_unreal_cm([2, 3, 4]), [400, 200, 300])

    def test_malformed_and_out_of_order_frames_fail_closed(self) -> None:
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

        non_finite = deepcopy(batch)
        non_finite["frames"][0]["root"][0] = float("nan")
        with self.assertRaises(ProtocolError):
            validate_batch(non_finite)


if __name__ == "__main__":
    unittest.main()
