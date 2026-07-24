# SPDX-License-Identifier: MIT

from pathlib import Path
import sys

import pytest


APP_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(APP_ROOT))

from ardy_blender import formats, motion_preview


def _frame():
    return {
        "time": 0.0,
        "root": [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0],
        "joints": [[0.0, 0.0, 0.0, 1.0] for _ in formats.CORE27_NAMES],
        "positions": [[0.0, 1.0, 0.0] for _ in formats.CORE27_NAMES],
        "contacts": [1.0, 1.0, 1.0, 1.0],
    }


def _batch(sequence=1):
    return {
        "version": 2,
        "sequence": sequence,
        "fps": 20,
        "coordinateSystem": "ardy-rh-x-left-y-up-z-forward-meters",
        "source": {
            "system": "nv-tlabs/ardy",
            "jointOrder": list(formats.CORE27_NAMES),
            "quaternionOrder": "xyzw",
            "rotationSpace": "local",
            "positionSpace": "global",
        },
        "frames": [_frame() for _ in range(8)],
    }


def test_endpoint_is_fixed_to_the_spark_loopback():
    assert (
        motion_preview.normalize_endpoint(" http://localhost:8777/ ")
        == "http://127.0.0.1:8777"
    )
    for value in (
        "https://127.0.0.1:8777",
        "http://127.0.0.1:2334",
        "http://example.com:8777",
        "http://127.0.0.1:8777/healthz",
    ):
        with pytest.raises(motion_preview.ArdyPreviewError):
            motion_preview.normalize_endpoint(value)


def test_batch_requires_exact_core27_local_xyzw_contract():
    sequence, frames = motion_preview.validate_batch(_batch())
    assert sequence == 1
    assert len(frames) == 8
    broken = _batch()
    broken["source"]["jointOrder"] = broken["source"]["jointOrder"][:-1]
    with pytest.raises(motion_preview.ArdyPreviewError, match="skeleton"):
        motion_preview.validate_batch(broken)


def test_fetch_accumulates_horizon8_batches_and_keeps_complete_prompt(monkeypatch):
    calls = []

    def fake_request(url, *, payload=None, timeout=120.0):
        calls.append((url, payload, timeout))
        if url.endswith("/healthz"):
            return {
                "status": "ready",
                "provider": "ardy",
                "protocolVersion": 2,
                "dynamicTextReady": True,
            }
        if url.endswith("/v2/prompts"):
            return {"ok": True, "promptId": "0" * 64, "cached": False}
        sequence = 1 + sum(
            1 for called_url, _payload, _timeout in calls if called_url.endswith("/v2/poses")
        )
        return _batch(sequence)

    monkeypatch.setattr(motion_preview, "_json_request", fake_request)
    prompt = "squat twice, then stand naturally"
    _health, frames = motion_preview.fetch_motion(
        "http://127.0.0.1:8777",
        prompt,
        intensity=0.65,
        duration=1.0,
    )
    pose_calls = [call for call in calls if call[0].endswith("/v2/poses")]
    assert len(pose_calls) == 3
    assert len(frames) == 20
    assert all(call[1]["prompt"] == prompt for call in pose_calls)
    assert [call[1]["afterSequence"] for call in pose_calls] == [0, 2, 3]


def test_casual_mapping_uses_the_reviewed_ue_deform_chain():
    assert motion_preview.CASUAL_GIRL_BONE_MAP["Hips"] == "pelvis"
    assert motion_preview.CASUAL_GIRL_BONE_MAP["RightArm"] == "upperarm_r"
    assert motion_preview.CASUAL_GIRL_BONE_MAP["LeftFoot"] == "foot_l"
    assert motion_preview.CASUAL_GIRL_BONE_MAP["RightHandEnd"] == "middle_03_r"
