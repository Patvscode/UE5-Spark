from __future__ import annotations

import importlib.util
import math
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "tools" / "validate_ardy_service.py"
SPEC = importlib.util.spec_from_file_location("validate_ardy_service", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)

from pose_protocol import PoseRequest  # noqa: E402
from providers import MockPoseProvider  # noqa: E402


class ArdyServiceValidatorTests(unittest.TestCase):
    def test_real_health_requires_exact_identity_and_bounded_latency(self) -> None:
        health = {
            "status": "ready",
            "provider": "ardy",
            "protocolVersion": 1,
            "fps": 20,
            "bufferFrames": 8,
            "facialControl": "excluded",
            "checkpoint": "ARDY-Core-RP-20FPS-Horizon8",
            "embeddingCount": 3,
            "p95GenerationMs": 212.343,
        }
        self.assertIs(VALIDATOR.validate_real_health(health, require_latency=True), health)
        for key, invalid in (
            ("provider", "mock"),
            ("checkpoint", "ARDY-Core-RP-20FPS-Horizon40"),
            ("embeddingCount", 2),
            ("p95GenerationMs", 400.0),
            ("p95GenerationMs", float("nan")),
        ):
            changed = dict(health)
            changed[key] = invalid
            with self.subTest(key=key, invalid=invalid), self.assertRaises(
                VALIDATOR.ValidationError
            ):
                VALIDATOR.validate_real_health(changed, require_latency=True)

    def test_batch_requires_exact_frames_times_float_contacts_and_face_exclusion(self) -> None:
        batch = MockPoseProvider().generate(PoseRequest("idle", 0.5, 1.0, 0))
        validated, sequence, final_time = VALIDATOR.validate_real_batch(
            batch,
            after_sequence=0,
            previous_time=None,
        )
        self.assertIs(validated, batch)
        self.assertGreater(sequence, 0)
        self.assertTrue(math.isfinite(final_time))

        batch["frames"][0]["contacts"][0] = True
        with self.assertRaises(VALIDATOR.ValidationError):
            VALIDATOR.validate_real_batch(batch, after_sequence=0, previous_time=None)

    def test_batch_rejects_face_control_and_cross_batch_time_regression(self) -> None:
        batch = MockPoseProvider().generate(PoseRequest("idle", 0.5, 1.0, 0))
        neck_index = VALIDATOR.CORE27_JOINTS.index("Neck")
        batch["frames"][0]["joints"][neck_index] = [0.0, 0.0, 0.1, 0.994987]
        with self.assertRaises(VALIDATOR.ValidationError):
            VALIDATOR.validate_real_batch(batch, after_sequence=0, previous_time=None)

        batch = MockPoseProvider().generate(PoseRequest("idle", 0.5, 1.0, 0))
        with self.assertRaises(VALIDATOR.ValidationError):
            VALIDATOR.validate_real_batch(
                batch,
                after_sequence=0,
                previous_time=float(batch["frames"][0]["time"]),
            )

    def test_p95_uses_nearest_rank(self) -> None:
        samples = [float(value) for value in range(1, 21)]
        self.assertEqual(VALIDATOR._nearest_rank_p95(samples), 19.0)


if __name__ == "__main__":
    unittest.main()
