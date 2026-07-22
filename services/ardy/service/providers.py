"""Motion providers for the loopback ARDY service."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import threading
import time

from embedding_contract import (
    APPROVED_EMBEDDING_BEHAVIORS,
    ARDY_SOURCE_COMMIT,
    BASE_ENCODER_REPOSITORY,
    EMBEDDING_SCHEMA_VERSION,
    EMBEDDING_WIDTH,
    ENCODER_REVISIONS,
    SUPERVISED_ENCODER_REPOSITORY,
    UPSTREAM_LLAMA_REPOSITORY,
    prompt_sha256,
)

from pose_protocol import (
    BATCH_FRAMES,
    CONTACT_ORDER,
    CORE27_HIERARCHY,
    CORE27_JOINTS,
    EXCLUDED_GENERATED_JOINTS,
    FPS,
    PoseRequest,
    ProtocolError,
    QuaternionHemisphereTracker,
    make_pose_batch,
    quaternion,
)


IDENTITY = [0.0, 0.0, 0.0, 1.0]
MAX_HISTORY_FRAMES = 192
MIN_CFG_WEIGHT = 1.25
MAX_CFG_WEIGHT = 2.75

# Deterministic source-basis standing positions for the protocol-only mock.
# ARDY +X points to the character's left, +Y is up, and +Z is forward.
MOCK_CORE27_POSITIONS = (
    (0.00, 1.00, 0.00),  # Hips
    (0.00, 1.10, 0.00),  # Spine
    (0.00, 1.20, 0.00),  # Spine1
    (0.00, 1.32, 0.00),  # Spine2
    (0.00, 1.44, 0.00),  # Spine3
    (0.00, 1.56, 0.00),  # Neck
    (0.00, 1.72, 0.00),  # Head
    (-0.14, 1.46, 0.00),  # RightShoulder
    (-0.31, 1.44, 0.00),  # RightArm
    (-0.55, 1.31, 0.00),  # RightForeArm
    (-0.75, 1.20, 0.00),  # RightHand
    (-0.86, 1.16, 0.00),  # RightHandEnd
    (-0.78, 1.17, 0.06),  # RightHandThumb1
    (0.14, 1.46, 0.00),  # LeftShoulder
    (0.31, 1.44, 0.00),  # LeftArm
    (0.55, 1.31, 0.00),  # LeftForeArm
    (0.75, 1.20, 0.00),  # LeftHand
    (0.86, 1.16, 0.00),  # LeftHandEnd
    (0.78, 1.17, 0.06),  # LeftHandThumb1
    (-0.10, 0.91, 0.00),  # RightUpLeg
    (-0.10, 0.51, 0.01),  # RightLeg
    (-0.10, 0.10, 0.05),  # RightFoot
    (-0.10, 0.04, 0.24),  # RightToeBase
    (0.10, 0.91, 0.00),  # LeftUpLeg
    (0.10, 0.51, 0.01),  # LeftLeg
    (0.10, 0.10, 0.05),  # LeftFoot
    (0.10, 0.04, 0.24),  # LeftToeBase
)


def cfg_weight_for_intensity(intensity: float) -> float:
    """Map reviewed request intensity to a bounded ARDY text-guidance weight."""

    if isinstance(intensity, bool) or not isinstance(intensity, (int, float)):
        raise ProtocolError("intensity must be numeric")
    value = float(intensity)
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ProtocolError("intensity must be between zero and one")
    return MIN_CFG_WEIGHT + (MAX_CFG_WEIGHT - MIN_CFG_WEIGHT) * value


def retained_history_for_behavior(
    history: object | None,
    previous_behavior: str | None,
    next_behavior: str,
) -> object | None:
    """Return the same ARDY history across an approved prompt transition."""

    if next_behavior not in APPROVED_EMBEDDING_BEHAVIORS:
        raise RuntimeError("behavior is not in the reviewed generated-motion catalog")
    # Naming both behaviors here makes the no-reset policy explicit: a prompt
    # transition changes conditioning, never the autoregressive pose context.
    _ = previous_behavior
    return history


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _serialize_contact_values(values: object) -> list[float]:
    """Normalize ARDY's [L heel, L toe, R heel, R toe] flags to floats."""

    try:
        result = [float(value) for value in values]  # type: ignore[union-attr]
    except (TypeError, ValueError) as error:
        raise RuntimeError("ARDY foot contacts are not a flat numeric vector") from error
    if len(result) != len(CONTACT_ORDER) or not all(
        math.isfinite(value) and 0.0 <= value <= 1.0 for value in result
    ):
        raise RuntimeError("ARDY foot contacts must contain four normalized values")
    return result


def _generation_window_frames(history: object | None) -> int:
    """Return ARDY's total visible window: retained history plus one horizon."""

    if history is None:
        return BATCH_FRAMES
    try:
        history_frames = int(history.shape[1])  # type: ignore[union-attr]
    except (AttributeError, IndexError, TypeError, ValueError) as error:
        raise RuntimeError("ARDY history has an invalid tensor shape") from error
    if (
        history_frames < BATCH_FRAMES
        or history_frames > MAX_HISTORY_FRAMES
        or history_frames % BATCH_FRAMES != 0
    ):
        raise RuntimeError("ARDY history length violates the sealed window contract")
    return history_frames + BATCH_FRAMES


def _validate_ardy_output_shapes(values: dict[str, object]) -> None:
    """Fail closed unless official inverse output has the reviewed Core27 shapes."""

    expected_shapes = {
        "local rotations": (1, BATCH_FRAMES, len(CORE27_JOINTS), 3, 3),
        "root rotations": (1, BATCH_FRAMES, 3, 3),
        "root positions": (1, BATCH_FRAMES, 3),
        "posed joints": (1, BATCH_FRAMES, len(CORE27_JOINTS), 3),
        "foot contacts": (1, BATCH_FRAMES, len(CONTACT_ORDER)),
    }
    if set(values) != set(expected_shapes):
        raise RuntimeError("ARDY inverse output has an invalid field envelope")
    for label, expected_shape in expected_shapes.items():
        try:
            actual_shape = tuple(values[label].shape)  # type: ignore[union-attr]
        except (AttributeError, TypeError) as error:
            raise RuntimeError(f"ARDY {label} has no tensor shape") from error
        if actual_shape != expected_shape:
            raise RuntimeError(
                f"ARDY {label} shape {actual_shape} does not match {expected_shape}"
            )


def load_embedding_cache(root: Path, np_module: object) -> dict[str, tuple[object, object]]:
    """Load only a complete, hash-sealed cache produced by cache_embeddings.py."""

    if not root.is_dir() or root.is_symlink():
        return {}
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        return {}
    if manifest_path.stat().st_size > 64 * 1024:
        raise RuntimeError("cached embedding manifest is too large")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError("cached embedding manifest is invalid") from error

    expected_files = {"manifest.json"} | {
        f"{behavior}.npz" for behavior in APPROVED_EMBEDDING_BEHAVIORS
    }
    if {path.name for path in root.iterdir()} != expected_files:
        raise RuntimeError("cached embedding directory has unexpected entries")
    if (
        manifest.get("schemaVersion") != EMBEDDING_SCHEMA_VERSION
        or manifest.get("ardySourceCommit") != ARDY_SOURCE_COMMIT
        or manifest.get("approvedBehaviors") != list(APPROVED_EMBEDDING_BEHAVIORS)
    ):
        raise RuntimeError("cached embedding manifest contract does not match this image")
    encoder = manifest.get("encoder")
    if not isinstance(encoder, dict) or (
        encoder.get("baseRepository") != BASE_ENCODER_REPOSITORY
        or encoder.get("supervisedRepository") != SUPERVISED_ENCODER_REPOSITORY
        or encoder.get("upstreamRepository") != UPSTREAM_LLAMA_REPOSITORY
        or encoder.get("revisions") != ENCODER_REVISIONS
        or encoder.get("precision") not in {"bfloat16", "float32"}
        or encoder.get("outputDtype") != "float32"
    ):
        raise RuntimeError("cached embedding encoder identity is invalid")
    entries = manifest.get("embeddings")
    if not isinstance(entries, dict) or set(entries) != set(APPROVED_EMBEDDING_BEHAVIORS):
        raise RuntimeError("cached embedding manifest behavior set is invalid")

    result: dict[str, tuple[object, object]] = {}
    for behavior in APPROVED_EMBEDDING_BEHAVIORS:
        entry = entries[behavior]
        filename = f"{behavior}.npz"
        if not isinstance(entry, dict) or entry != {
            "file": filename,
            "fileSha256": entry.get("fileSha256"),
            "promptSha256": prompt_sha256(behavior),
            "shape": [1, EMBEDDING_WIDTH],
        }:
            raise RuntimeError(f"cached embedding manifest entry {behavior} is invalid")
        expected_digest = entry.get("fileSha256")
        if not isinstance(expected_digest, str) or len(expected_digest) != 64:
            raise RuntimeError(f"cached embedding digest {behavior} is invalid")
        path = root / filename
        if not path.is_file() or path.is_symlink() or _sha256(path) != expected_digest:
            raise RuntimeError(f"cached embedding {behavior} failed its hash seal")
        with np_module.load(path, allow_pickle=False) as values:
            if set(values.files) != {"text_feat", "text_pad_mask"}:
                raise RuntimeError(f"cached embedding {behavior} has an invalid envelope")
            features = np_module.asarray(values["text_feat"], dtype=np_module.float32)
            mask = np_module.asarray(values["text_pad_mask"], dtype=np_module.bool_)
        if (
            features.shape != (1, EMBEDDING_WIDTH)
            or mask.shape != (1,)
            or mask.tolist() != [True]
            or not np_module.isfinite(features).all()
        ):
            raise RuntimeError(f"cached embedding {behavior} has an invalid shape or value")
        result[behavior] = (features, mask)
    return result


class MockPoseProvider:
    """Deterministic Core27 data for protocol, buffer, and failure testing."""

    name = "mock"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sequence = 0
        self._time = 0.0
        self._hemispheres = QuaternionHemisphereTracker()

    @property
    def ready(self) -> bool:
        return True

    @property
    def health(self) -> dict[str, object]:
        return {"checkpoint": None, "embeddingCount": 0, "p95GenerationMs": 0.0}

    def generate(self, request: PoseRequest) -> dict[str, object]:
        with self._lock:
            sequence = max(self._sequence + 1, request.after_sequence + 1)
            frames = [self._frame(request, self._time + index / FPS) for index in range(BATCH_FRAMES)]
            tracker = self._hemispheres.clone()
            for frame in frames:
                stable_root, stable_joints = tracker.stabilize(
                    frame["root"][3:], frame["joints"]  # type: ignore[index]
                )
                frame["root"][3:] = stable_root  # type: ignore[index]
                frame["joints"] = stable_joints
            batch = make_pose_batch(sequence, frames)
            self._sequence = sequence
            self._time = frames[-1]["time"] + 1.0 / FPS
            self._hemispheres = tracker
        return batch

    @staticmethod
    def _frame(request: PoseRequest, time_value: float) -> dict[str, object]:
        phase = 2.0 * math.pi * time_value / max(request.duration, 0.2)
        strength = request.intensity
        rotations = {joint: IDENTITY.copy() for joint in CORE27_JOINTS}

        breathing = math.radians(1.5) * strength * math.sin(phase)
        rotations["Spine1"] = quaternion((1.0, 0.0, 0.0), breathing)
        rotations["Spine2"] = quaternion((0.0, 0.0, 1.0), breathing * 0.35)
        if request.behavior in {"wave", "explain", "invite"}:
            lift = math.radians(35.0 + 35.0 * strength)
            rotations["RightArm"] = quaternion((0.0, 0.0, 1.0), -lift)
            rotations["RightForeArm"] = quaternion(
                (1.0, 0.0, 0.0), math.radians(25.0) * math.sin(phase)
            )
            rotations["RightHand"] = quaternion(
                (0.0, 1.0, 0.0), math.radians(20.0) * math.sin(phase * 2.0)
            )
        elif request.behavior in {"think", "warn"}:
            rotations["LeftArm"] = quaternion((0.0, 0.0, 1.0), math.radians(25.0) * strength)
            rotations["LeftForeArm"] = quaternion((1.0, 0.0, 0.0), math.radians(55.0) * strength)
        elif request.behavior in {"jog_in_place", "run_in_place"}:
            stride_degrees = 22.0 if request.behavior == "jog_in_place" else 38.0
            stride = math.radians(stride_degrees) * strength * math.sin(phase)
            rotations["RightUpLeg"] = quaternion((1.0, 0.0, 0.0), stride)
            rotations["LeftUpLeg"] = quaternion((1.0, 0.0, 0.0), -stride)
            rotations["RightArm"] = quaternion((1.0, 0.0, 0.0), -stride * 0.75)
            rotations["LeftArm"] = quaternion((1.0, 0.0, 0.0), stride * 0.75)
        elif request.behavior == "jumping_jacks":
            spread = (1.0 - math.cos(phase)) * 0.5 * strength
            rotations["RightArm"] = quaternion((0.0, 0.0, 1.0), -math.radians(145.0) * spread)
            rotations["LeftArm"] = quaternion((0.0, 0.0, 1.0), math.radians(145.0) * spread)
            rotations["RightUpLeg"] = quaternion((0.0, 0.0, 1.0), -math.radians(22.0) * spread)
            rotations["LeftUpLeg"] = quaternion((0.0, 0.0, 1.0), math.radians(22.0) * spread)
        elif request.behavior == "stretch":
            extension = math.radians(110.0) * strength
            rotations["RightArm"] = quaternion((0.0, 0.0, 1.0), -extension)
            rotations["LeftArm"] = quaternion((0.0, 0.0, 1.0), extension)
            rotations["Spine2"] = quaternion((1.0, 0.0, 0.0), math.radians(-8.0) * strength)
        elif request.behavior == "dance_relaxed":
            sway = math.radians(14.0) * strength * math.sin(phase)
            rotations["Spine1"] = quaternion((0.0, 0.0, 1.0), sway)
            rotations["RightArm"] = quaternion((1.0, 0.0, 0.0), -sway * 1.8)
            rotations["LeftArm"] = quaternion((1.0, 0.0, 0.0), sway * 1.8)
            rotations["RightUpLeg"] = quaternion((1.0, 0.0, 0.0), sway * 0.8)
            rotations["LeftUpLeg"] = quaternion((1.0, 0.0, 0.0), -sway * 0.8)

        # StreamingADA retains exclusive ownership until explicit conflict tests pass.
        for joint in EXCLUDED_GENERATED_JOINTS:
            rotations[joint] = IDENTITY.copy()

        vertical_scale = 0.002
        if request.behavior == "jog_in_place":
            vertical_scale = 0.025
        elif request.behavior in {"run_in_place", "jumping_jacks"}:
            vertical_scale = 0.05
        vertical = vertical_scale * strength * (1.0 + math.sin(phase))
        positions = [
            [x_value, y_value + vertical, z_value]
            for x_value, y_value, z_value in MOCK_CORE27_POSITIONS
        ]
        contacts = [1.0, 1.0, 1.0, 1.0]
        if request.behavior in {"jog_in_place", "run_in_place"}:
            right_planted = 1.0 if math.sin(phase) >= 0.0 else 0.0
            left_planted = 1.0 - right_planted
            contacts = [left_planted, left_planted, right_planted, right_planted]
        elif request.behavior == "jumping_jacks" and math.sin(phase) > 0.0:
            contacts = [0.0, 0.0, 0.0, 0.0]
        return {
            "time": round(time_value, 6),
            "root": [*positions[0], 0.0, 0.0, 0.0, 1.0],
            "joints": [rotations[name] for name in CORE27_JOINTS],
            "positions": positions,
            "contacts": contacts,
        }


class ArdyPoseProvider:
    """Eager-PyTorch Horizon8 provider driven only by cached approved embeddings."""

    name = "ardy"

    def __init__(
        self,
        models_root: Path,
        model_name: str = "ARDY-Core-RP-20FPS-Horizon8",
    ) -> None:
        import numpy as np
        import torch
        from ardy.model import load_model

        self._np = np
        self._torch = torch
        self._models_root = models_root.resolve(strict=True)
        self._model_name = model_name
        self._model = load_model(
            model_name,
            device="cuda:0",
            checkpoints_dir=str(self._models_root),
            text_encoder=False,
        )
        if self._model.gen_horizon_len != BATCH_FRAMES or self._model.motion_rep.fps != FPS:
            raise RuntimeError("ARDY model does not match the sealed 8-frame/20-FPS contract")
        model_hierarchy = tuple(
            tuple(entry) for entry in self._model.skeleton.bone_order_names_with_parents
        )
        if model_hierarchy != CORE27_HIERARCHY:
            raise RuntimeError("ARDY model does not expose the exact sealed Core27 skeleton")
        self._embeddings = self._load_embeddings(self._models_root / "embeddings")
        self._history = None
        self._lock = threading.Lock()
        self._sequence = 0
        self._time = 0.0
        self._generation_times_ms: list[float] = []
        self._hemispheres = QuaternionHemisphereTracker()
        self._last_behavior: str | None = None

    @property
    def ready(self) -> bool:
        return set(self._embeddings) == set(APPROVED_EMBEDDING_BEHAVIORS)

    @property
    def health(self) -> dict[str, object]:
        ordered = sorted(self._generation_times_ms)
        rank = max(0, math.ceil(0.95 * len(ordered)) - 1) if ordered else 0
        return {
            "checkpoint": self._model_name,
            "embeddingCount": len(self._embeddings),
            "p95GenerationMs": round(ordered[rank], 3) if ordered else 0.0,
        }

    def _load_embeddings(self, root: Path) -> dict[str, tuple[object, object]]:
        cached = load_embedding_cache(root, self._np)
        result: dict[str, tuple[object, object]] = {}
        for behavior, (features, mask) in cached.items():
            result[behavior] = (
                self._torch.from_numpy(features).unsqueeze(0).to("cuda:0"),
                self._torch.from_numpy(mask).unsqueeze(0).to("cuda:0"),
            )
        return result

    def generate(self, request: PoseRequest) -> dict[str, object]:
        # Timing-critical actions remain deterministic Unreal-side clips.
        if request.behavior not in set(APPROVED_EMBEDDING_BEHAVIORS):
            raise RuntimeError("behavior is reserved for the baked provider")
        embedding = self._embeddings.get(request.behavior)
        if embedding is None:
            raise RuntimeError("approved cached embedding is unavailable")
        with self._lock, self._torch.inference_mode():
            text_feat, text_pad_mask = embedding
            # Behavior changes intentionally retain the autoregressive motion
            # history. This lets ARDY generate a transition from the current
            # pose instead of snapping back to a fresh prompt baseline.
            history = retained_history_for_behavior(
                self._history, self._last_behavior, request.behavior
            )
            started = time.perf_counter()
            samples = self._model.autoregressive_step(
                num_frames=_generation_window_frames(history),
                num_denoising_steps=int(self._model.diffusion.num_base_steps),
                motion_mask=None,
                observed_motion=None,
                cfg_weight=cfg_weight_for_intensity(request.intensity),
                texts=None,
                text_feat=text_feat,
                text_pad_mask=text_pad_mask,
                init_history_sequence=history,
            )
            self._torch.cuda.synchronize()
            self._generation_times_ms.append((time.perf_counter() - started) * 1000.0)
            self._generation_times_ms = self._generation_times_ms[-256:]
            # Bound history to the trained ten-second window minus one horizon.
            next_history = samples[:, -MAX_HISTORY_FRAMES:].detach()
            unnormalized = self._model.motion_rep.unnormalize(samples)
            output = self._model.motion_rep.inverse(unnormalized, is_normalized=False)
            local_matrices = output["local_rot_mats"][:, -BATCH_FRAMES:].detach().cpu().numpy()
            root_matrices = (
                output["global_rot_mats"][:, -BATCH_FRAMES:, 0].detach().cpu().numpy()
            )
            roots = output["root_positions"][:, -BATCH_FRAMES:].detach().cpu().numpy()
            contacts = output["foot_contacts"][:, -BATCH_FRAMES:].detach().cpu().numpy()
            posed_joints = output["posed_joints"][:, -BATCH_FRAMES:].detach().cpu().numpy()
            actual_values = {
                "local rotations": local_matrices,
                "root rotations": root_matrices,
                "root positions": roots,
                "posed joints": posed_joints,
                "foot contacts": contacts,
            }
            _validate_ardy_output_shapes(actual_values)
            sequence = max(self._sequence + 1, request.after_sequence + 1)
            frames, tracker, next_time = self._serialize_frames(
                local_matrices[0],
                root_matrices[0],
                roots[0],
                posed_joints[0],
                contacts[0],
            )
            batch = make_pose_batch(sequence, frames)
            self._sequence = sequence
            self._last_behavior = request.behavior
            self._history = next_history
            self._time = next_time
            self._hemispheres = tracker
        return batch

    def _serialize_frames(
        self,
        matrices: object,
        root_matrices: object,
        roots: object,
        posed_joints: object,
        contacts: object,
    ) -> tuple[list[dict[str, object]], QuaternionHemisphereTracker, float]:
        from scipy.spatial.transform import Rotation

        quaternions = Rotation.from_matrix(matrices.reshape(-1, 3, 3)).as_quat().reshape(
            BATCH_FRAMES, len(CORE27_JOINTS), 4
        )
        root_quaternions = Rotation.from_matrix(root_matrices).as_quat()
        frames: list[dict[str, object]] = []
        excluded = {CORE27_JOINTS.index(name) for name in EXCLUDED_GENERATED_JOINTS}
        tracker = self._hemispheres.clone()
        for index in range(BATCH_FRAMES):
            joints = quaternions[index].tolist()
            for joint_index in excluded:
                joints[joint_index] = IDENTITY.copy()
            stable_root, stable_joints = tracker.stabilize(
                root_quaternions[index].tolist(), joints
            )
            frames.append(
                {
                    "time": round(self._time + index / FPS, 6),
                    "root": [*roots[index].tolist(), *stable_root],
                    "joints": stable_joints,
                    "positions": posed_joints[index].tolist(),
                    "contacts": _serialize_contact_values(contacts[index]),
                }
            )
        next_time = float(frames[-1]["time"]) + 1.0 / FPS
        return frames, tracker, next_time
