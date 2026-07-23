"""Strict loopback pose protocol shared by the mock and ARDY providers."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

from motion_catalog import GENERATED_BEHAVIORS


PROTOCOL_VERSION = 2
FPS = 20
BATCH_FRAMES = 8

# ARDY is right-handed with +X pointing to the character's left, +Y up, and
# +Z forward. Unreal is left-handed with +X forward, +Y right, and +Z up.
# Source vectors therefore map to Unreal as (z, -x, y). Pose batches remain in
# the source basis so the retargeter can apply its reviewed rest-pose mapping.
COORDINATE_SYSTEM = "ardy-rh-x-left-y-up-z-forward-meters"
UNREAL_COORDINATE_SYSTEM = "unreal-lh-x-forward-y-right-z-up-centimeters"
SOURCE_SYSTEM = "nv-tlabs/ardy"
SOURCE_REVISION = "693f74d13b3d04a0a22ce127ee79c929dd89756b"
SOURCE_SKELETON = "Core27"
ROTATION_SPACE = "local"
QUATERNION_ORDER = "xyzw"
POSITION_SPACE = "global"

CORE27_HIERARCHY = (
    ("Hips", None),
    ("Spine", "Hips"),
    ("Spine1", "Spine"),
    ("Spine2", "Spine1"),
    ("Spine3", "Spine2"),
    ("Neck", "Spine3"),
    ("Head", "Neck"),
    ("RightShoulder", "Spine3"),
    ("RightArm", "RightShoulder"),
    ("RightForeArm", "RightArm"),
    ("RightHand", "RightForeArm"),
    ("RightHandEnd", "RightHand"),
    ("RightHandThumb1", "RightHand"),
    ("LeftShoulder", "Spine3"),
    ("LeftArm", "LeftShoulder"),
    ("LeftForeArm", "LeftArm"),
    ("LeftHand", "LeftForeArm"),
    ("LeftHandEnd", "LeftHand"),
    ("LeftHandThumb1", "LeftHand"),
    ("RightUpLeg", "Hips"),
    ("RightLeg", "RightUpLeg"),
    ("RightFoot", "RightLeg"),
    ("RightToeBase", "RightFoot"),
    ("LeftUpLeg", "Hips"),
    ("LeftLeg", "LeftUpLeg"),
    ("LeftFoot", "LeftLeg"),
    ("LeftToeBase", "LeftFoot"),
)
CORE27_JOINTS = tuple(name for name, _parent in CORE27_HIERARCHY)
CONTACT_ORDER = ("left_heel", "left_toe", "right_heel", "right_toe")
EXCLUDED_GENERATED_JOINTS = frozenset({"Neck", "Head"})

# These behaviors have reviewed cached text embeddings. The separate baked
# set remains available for deterministic, timing-critical Unreal fallbacks.
BAKED_BEHAVIORS = ("invite", "nod", "shake", "think", "warn")
ALLOWED_BEHAVIORS = frozenset((*GENERATED_BEHAVIORS, *BAKED_BEHAVIORS))

_BATCH_FIELDS = {
    "version",
    "sequence",
    "fps",
    "coordinateSystem",
    "source",
    "frames",
}
_SOURCE_FIELDS = {
    "system",
    "revision",
    "skeleton",
    "jointOrder",
    "rotationSpace",
    "quaternionOrder",
    "positionSpace",
    "contactOrder",
}
_FRAME_FIELDS = {"time", "root", "joints", "positions", "contacts"}
_QUATERNION_EPSILON = 1e-12
_NORMALIZED_QUATERNION_TOLERANCE = 5e-3


class ProtocolError(ValueError):
    """A request or generated batch violated the sealed protocol."""


@dataclass(frozen=True)
class PoseRequest:
    behavior: str
    intensity: float
    duration: float
    after_sequence: int
    prompt: str | None = None

    @classmethod
    def from_json(cls, value: object) -> "PoseRequest":
        if not isinstance(value, dict):
            raise ProtocolError("request must be a JSON object")
        allowed_keys = {
            "behavior",
            "intensity",
            "duration",
            "afterSequence",
            "prompt",
        }
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
        prompt = value.get("prompt")
        if prompt is not None:
            prompt = normalize_prompt(prompt)
        return cls(behavior, intensity, duration, after_sequence, prompt)


def normalize_prompt(value: object) -> str:
    """Normalize one user-authored ARDY prompt without semantic filtering."""

    if not isinstance(value, str):
        raise ProtocolError("prompt must be a string")
    prompt = value.strip()
    if not 1 <= len(prompt) <= 512:
        raise ProtocolError("prompt must contain 1 to 512 characters")
    return prompt


def _finite_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProtocolError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ProtocolError(f"{label} must be finite")
    return result


def _finite_vector(value: object, length: int) -> bool:
    return isinstance(value, list) and len(value) == length and all(
        isinstance(item, (int, float))
        and not isinstance(item, bool)
        and math.isfinite(float(item))
        for item in value
    )


def normalize_quaternion(value: Iterable[float]) -> list[float]:
    """Return a finite, normalized XYZW quaternion or fail closed."""

    try:
        result = [float(component) for component in value]
    except (TypeError, ValueError) as error:
        raise ProtocolError("quaternion must contain four finite values") from error
    if len(result) != 4 or not all(math.isfinite(component) for component in result):
        raise ProtocolError("quaternion must contain four finite values")
    magnitude = math.sqrt(sum(component * component for component in result))
    if magnitude <= _QUATERNION_EPSILON:
        raise ProtocolError("quaternion magnitude is too small")
    return [component / magnitude for component in result]


def stabilize_quaternion(
    value: Iterable[float],
    previous: Iterable[float] | None = None,
) -> list[float]:
    """Normalize XYZW and select a stable representative of q/-q.

    With a preceding sample, the representative in the same hemisphere is
    selected. The first sample uses a deterministic canonical hemisphere so
    independent service starts serialize the same orientation consistently.
    """

    result = normalize_quaternion(value)
    if previous is not None:
        reference = normalize_quaternion(previous)
        dot = sum(left * right for left, right in zip(result, reference))
        if dot < 0.0:
            return [-component for component in result]
        if dot > 0.0:
            return result

    # Prefer positive W. For a 180-degree rotation, choose the first non-zero
    # vector component positive to make the canonical choice deterministic.
    for component in (result[3], result[0], result[1], result[2]):
        if abs(component) > _QUATERNION_EPSILON:
            return result if component > 0.0 else [-item for item in result]
    raise ProtocolError("quaternion magnitude is too small")


def quaternion(axis: tuple[float, float, float], radians: float) -> list[float]:
    length = math.sqrt(sum(component * component for component in axis))
    if length <= 1e-8:
        return [0.0, 0.0, 0.0, 1.0]
    scale = math.sin(radians / 2.0) / length
    return stabilize_quaternion(
        [axis[0] * scale, axis[1] * scale, axis[2] * scale, math.cos(radians / 2.0)]
    )


def ardy_translation_to_unreal_cm(value: list[float]) -> list[float]:
    """Map ARDY (left, up, forward) metres to Unreal (forward, right, up) cm."""

    if not _finite_vector(value, 3):
        raise ProtocolError("translation must contain three finite values")
    return [float(value[2]) * 100.0, -float(value[0]) * 100.0, float(value[1]) * 100.0]


def ardy_quaternion_to_unreal(
    value: Iterable[float],
    previous: Iterable[float] | None = None,
) -> list[float]:
    """Convert an ARDY XYZW orientation into Unreal's reflected basis.

    The vector mapping ``(x, y, z) -> (z, -x, y)`` changes handedness. A
    quaternion's imaginary vector is an axial vector, so it must additionally
    receive the determinant sign. Thus ``(x, y, z, w)`` becomes
    ``(-z, x, -y, w)``. This is equivalent to ``R_u = C R_a C^-1`` for the
    source-to-Unreal basis matrix C.
    """

    source = normalize_quaternion(value)
    converted = [-source[2], source[0], -source[1], source[3]]
    return stabilize_quaternion(converted, previous)


class QuaternionHemisphereTracker:
    """Carry stable quaternion representatives across frames and batches."""

    def __init__(
        self,
        root: Iterable[float] | None = None,
        joints: Iterable[Iterable[float]] | None = None,
    ) -> None:
        self._root = stabilize_quaternion(root) if root is not None else None
        self._joints = (
            [stabilize_quaternion(rotation) for rotation in joints]
            if joints is not None
            else None
        )
        if self._joints is not None and len(self._joints) != len(CORE27_JOINTS):
            raise ProtocolError("hemisphere tracker requires exactly 27 joints")

    def stabilize(
        self,
        root: Iterable[float],
        joints: Iterable[Iterable[float]],
    ) -> tuple[list[float], list[list[float]]]:
        joint_values = list(joints)
        if len(joint_values) != len(CORE27_JOINTS):
            raise ProtocolError("pose frame must contain exactly 27 joints")
        stable_root = stabilize_quaternion(root, self._root)
        if self._joints is None:
            stable_joints = [stabilize_quaternion(rotation) for rotation in joint_values]
        else:
            stable_joints = [
                stabilize_quaternion(rotation, previous)
                for rotation, previous in zip(joint_values, self._joints)
            ]
        self._root = stable_root
        self._joints = stable_joints
        return stable_root.copy(), [rotation.copy() for rotation in stable_joints]

    def clone(self) -> "QuaternionHemisphereTracker":
        """Copy state so a failed serialization cannot advance the live tracker."""

        return QuaternionHemisphereTracker(self._root, self._joints)


def source_descriptor() -> dict[str, object]:
    """Return a fresh, JSON-safe copy of the strict source-layout identity."""

    return {
        "system": SOURCE_SYSTEM,
        "revision": SOURCE_REVISION,
        "skeleton": SOURCE_SKELETON,
        "jointOrder": list(CORE27_JOINTS),
        "rotationSpace": ROTATION_SPACE,
        "quaternionOrder": QUATERNION_ORDER,
        "positionSpace": POSITION_SPACE,
        "contactOrder": list(CONTACT_ORDER),
    }


def make_pose_batch(sequence: int, frames: list[dict[str, object]]) -> dict[str, object]:
    """Create and validate a complete protocol-v2 pose batch."""

    return validate_batch(
        {
            "version": PROTOCOL_VERSION,
            "sequence": sequence,
            "fps": FPS,
            "coordinateSystem": COORDINATE_SYSTEM,
            "source": source_descriptor(),
            "frames": frames,
        }
    )


def validate_batch(batch: object) -> dict[str, object]:
    if not isinstance(batch, dict) or set(batch) != _BATCH_FIELDS:
        raise ProtocolError("pose batch has an invalid envelope")
    if batch["version"] != PROTOCOL_VERSION or type(batch["version"]) is not int:
        raise ProtocolError("pose batch version is unsupported")
    if batch["fps"] != FPS or type(batch["fps"]) is not int:
        raise ProtocolError("pose batch frame rate is unsupported")
    if batch["coordinateSystem"] != COORDINATE_SYSTEM:
        raise ProtocolError("pose batch coordinate system is unsupported")
    source = batch["source"]
    if (
        not isinstance(source, dict)
        or set(source) != _SOURCE_FIELDS
        or source != source_descriptor()
    ):
        raise ProtocolError("pose batch source layout is unsupported")
    if (
        isinstance(batch["sequence"], bool)
        or not isinstance(batch["sequence"], int)
        or not 1 <= batch["sequence"] <= 2**63 - 1
    ):
        raise ProtocolError("pose batch sequence is invalid")
    frames = batch["frames"]
    if not isinstance(frames, list) or not 1 <= len(frames) <= BATCH_FRAMES:
        raise ProtocolError("pose batch contains an invalid frame count")

    previous_time = -1.0
    previous_root: list[float] | None = None
    previous_joints: list[list[float]] | None = None
    for frame in frames:
        if not isinstance(frame, dict) or set(frame) != _FRAME_FIELDS:
            raise ProtocolError("pose frame has an invalid envelope")
        time_value = _finite_number(frame["time"], "frame time")
        if time_value < 0.0 or time_value <= previous_time:
            raise ProtocolError("pose frame times must be non-negative and increase")
        previous_time = time_value
        if not _finite_vector(frame["root"], 7):
            raise ProtocolError("pose root must contain seven finite values")
        root_rotation = _validated_normalized_quaternion(frame["root"][3:], "pose root")
        joints = frame["joints"]
        if not isinstance(joints, list) or len(joints) != len(CORE27_JOINTS):
            raise ProtocolError("pose frame must contain exactly 27 joints")
        joint_rotations = [
            _validated_normalized_quaternion(rotation, "joint rotation") for rotation in joints
        ]
        positions = frame["positions"]
        if (
            not isinstance(positions, list)
            or len(positions) != len(CORE27_JOINTS)
            or not all(_finite_vector(position, 3) for position in positions)
        ):
            raise ProtocolError("pose frame must contain exactly 27 finite global positions")
        if any(
            not math.isclose(
                float(root_component),
                float(hips_component),
                abs_tol=1e-5,
            )
            for root_component, hips_component in zip(frame["root"][:3], positions[0])
        ):
            raise ProtocolError("pose root translation must match the global Hips position")
        if _quaternion_dot(root_rotation, joint_rotations[0]) < 1.0 - 1e-5:
            raise ProtocolError("pose root rotation must match the local Hips rotation")
        contacts = frame["contacts"]
        if not _finite_vector(contacts, len(CONTACT_ORDER)):
            raise ProtocolError("pose contacts must contain four finite values")
        if not all(0.0 <= float(contact) <= 1.0 for contact in contacts):
            raise ProtocolError("pose contacts must be normalized confidences")
        if previous_root is not None and _quaternion_dot(root_rotation, previous_root) < -1e-8:
            raise ProtocolError("pose root quaternion changed hemisphere")
        if previous_joints is not None and any(
            _quaternion_dot(current, previous) < -1e-8
            for current, previous in zip(joint_rotations, previous_joints)
        ):
            raise ProtocolError("joint quaternion changed hemisphere")
        previous_root = root_rotation
        previous_joints = joint_rotations
    return batch


def _validated_normalized_quaternion(value: object, label: str) -> list[float]:
    if not _finite_vector(value, 4):
        raise ProtocolError(f"{label} must be a finite XYZW quaternion")
    result = [float(component) for component in value]
    magnitude = math.sqrt(sum(component * component for component in result))
    if abs(magnitude - 1.0) > _NORMALIZED_QUATERNION_TOLERANCE:
        raise ProtocolError(f"{label} must be normalized")
    return result


def _quaternion_dot(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))
