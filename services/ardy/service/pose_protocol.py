"""Strict loopback pose protocol shared by the mock and ARDY providers."""

from __future__ import annotations

import math
from dataclasses import dataclass


PROTOCOL_VERSION = 1
FPS = 20
BATCH_FRAMES = 8
COORDINATE_SYSTEM = "ardy-y-up-z-forward-meters"
ALLOWED_BEHAVIORS = frozenset(
    {"idle", "listen", "wave", "invite", "think", "warn", "nod", "shake", "explain"}
)
CORE27_JOINTS = (
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
EXCLUDED_GENERATED_JOINTS = frozenset({"Neck", "Head"})


class ProtocolError(ValueError):
    """A request or generated batch violated the sealed protocol."""


@dataclass(frozen=True)
class PoseRequest:
    behavior: str
    intensity: float
    duration: float
    after_sequence: int

    @classmethod
    def from_json(cls, value: object) -> "PoseRequest":
        if not isinstance(value, dict):
            raise ProtocolError("request must be a JSON object")
        allowed_keys = {"behavior", "intensity", "duration", "afterSequence"}
        if set(value) - allowed_keys:
            raise ProtocolError("request contains unsupported fields")
        behavior = value.get("behavior", "idle")
        if not isinstance(behavior, str):
            raise ProtocolError("behavior must be a string")
        behavior = behavior.strip().lower()
        if behavior not in ALLOWED_BEHAVIORS:
            raise ProtocolError("behavior is not allowlisted")
        intensity = _finite_number(value.get("intensity", 0.5), "intensity")
        duration = _finite_number(value.get("duration", 1.0), "duration")
        after_sequence = value.get("afterSequence", 0)
        if isinstance(after_sequence, bool) or not isinstance(after_sequence, int):
            raise ProtocolError("afterSequence must be an integer")
        if not 0 <= intensity <= 1:
            raise ProtocolError("intensity must be between zero and one")
        if not 0.2 <= duration <= 10:
            raise ProtocolError("duration must be between 0.2 and 10 seconds")
        if not 0 <= after_sequence <= 2**63 - 1:
            raise ProtocolError("afterSequence is outside the supported range")
        return cls(behavior, intensity, duration, after_sequence)


def _finite_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProtocolError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ProtocolError(f"{label} must be finite")
    return result


def quaternion(axis: tuple[float, float, float], radians: float) -> list[float]:
    length = math.sqrt(sum(component * component for component in axis))
    if length <= 1e-8:
        return [0.0, 0.0, 0.0, 1.0]
    scale = math.sin(radians / 2.0) / length
    return [axis[0] * scale, axis[1] * scale, axis[2] * scale, math.cos(radians / 2.0)]


def validate_batch(batch: object) -> dict[str, object]:
    if not isinstance(batch, dict) or set(batch) != {
        "version",
        "sequence",
        "fps",
        "coordinateSystem",
        "frames",
    }:
        raise ProtocolError("pose batch has an invalid envelope")
    if batch["version"] != PROTOCOL_VERSION or batch["fps"] != FPS:
        raise ProtocolError("pose batch version or frame rate is unsupported")
    if batch["coordinateSystem"] != COORDINATE_SYSTEM:
        raise ProtocolError("pose batch coordinate system is unsupported")
    if isinstance(batch["sequence"], bool) or not isinstance(batch["sequence"], int):
        raise ProtocolError("pose batch sequence is invalid")
    frames = batch["frames"]
    if not isinstance(frames, list) or not 1 <= len(frames) <= BATCH_FRAMES:
        raise ProtocolError("pose batch contains an invalid frame count")
    previous_time = -1.0
    for frame in frames:
        if not isinstance(frame, dict) or set(frame) != {"time", "root", "joints", "contacts"}:
            raise ProtocolError("pose frame has an invalid envelope")
        time_value = _finite_number(frame["time"], "frame time")
        if time_value <= previous_time:
            raise ProtocolError("pose frame times must increase")
        previous_time = time_value
        if not _finite_vector(frame["root"], 7):
            raise ProtocolError("pose root must contain seven finite values")
        joints = frame["joints"]
        if not isinstance(joints, list) or len(joints) != len(CORE27_JOINTS):
            raise ProtocolError("pose frame must contain exactly 27 joints")
        if not all(_finite_vector(rotation, 4) for rotation in joints):
            raise ProtocolError("joint rotations must be finite XYZW quaternions")
        if not _finite_vector(frame["contacts"], 4):
            raise ProtocolError("pose contacts must contain four finite values")
    return batch


def _finite_vector(value: object, length: int) -> bool:
    return isinstance(value, list) and len(value) == length and all(
        isinstance(item, (int, float))
        and not isinstance(item, bool)
        and math.isfinite(float(item))
        for item in value
    )


def ardy_translation_to_unreal_cm(value: list[float]) -> list[float]:
    """Map ARDY X-right/Y-up/Z-forward metres to Unreal X-forward/Y-right/Z-up cm."""
    if not _finite_vector(value, 3):
        raise ProtocolError("translation must contain three finite values")
    return [float(value[2]) * 100.0, float(value[0]) * 100.0, float(value[1]) * 100.0]
