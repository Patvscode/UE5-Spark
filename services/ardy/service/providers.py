"""Motion providers for the loopback ARDY service."""

from __future__ import annotations

import math
from pathlib import Path
import threading
import time

from pose_protocol import (
    BATCH_FRAMES,
    COORDINATE_SYSTEM,
    CORE27_JOINTS,
    EXCLUDED_GENERATED_JOINTS,
    FPS,
    PROTOCOL_VERSION,
    PoseRequest,
    quaternion,
    validate_batch,
)


IDENTITY = [0.0, 0.0, 0.0, 1.0]


class MockPoseProvider:
    """Deterministic Core27 data for protocol, buffer, and failure testing."""

    name = "mock"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sequence = 0
        self._time = 0.0

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
            self._sequence = sequence
            self._time = frames[-1]["time"] + 1.0 / FPS
        return validate_batch(
            {
                "version": PROTOCOL_VERSION,
                "sequence": sequence,
                "fps": FPS,
                "coordinateSystem": COORDINATE_SYSTEM,
                "frames": frames,
            }
        )

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

        # StreamingADA retains exclusive ownership until explicit conflict tests pass.
        for joint in EXCLUDED_GENERATED_JOINTS:
            rotations[joint] = IDENTITY.copy()

        vertical = 0.002 * strength * (1.0 + math.sin(phase))
        return {
            "time": round(time_value, 6),
            "root": [0.0, vertical, 0.0, 0.0, 0.0, 0.0, 1.0],
            "joints": [rotations[name] for name in CORE27_JOINTS],
            "contacts": [1.0, 1.0, 1.0, 1.0],
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
        if len(self._model.skeleton.bone_order_names_with_parents) != len(CORE27_JOINTS):
            raise RuntimeError("ARDY model does not expose the sealed Core27 skeleton")
        self._embeddings = self._load_embeddings(self._models_root / "embeddings")
        self._history = None
        self._lock = threading.Lock()
        self._sequence = 0
        self._time = 0.0
        self._generation_times_ms: list[float] = []

    @property
    def ready(self) -> bool:
        return bool(self._embeddings)

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
        if not root.is_dir() or root.is_symlink():
            return {}
        result: dict[str, tuple[object, object]] = {}
        for behavior in sorted({"idle", "listen", "explain"}):
            path = root / f"{behavior}.npz"
            if not path.is_file() or path.is_symlink():
                continue
            with self._np.load(path, allow_pickle=False) as values:
                if set(values.files) != {"text_feat", "text_pad_mask"}:
                    raise RuntimeError(f"cached embedding {behavior} has an invalid envelope")
                features = self._np.asarray(values["text_feat"], dtype=self._np.float32)
                mask = self._np.asarray(values["text_pad_mask"], dtype=self._np.bool_)
            if (
                features.ndim != 2
                or not 1 <= features.shape[0] <= 256
                or features.shape[1] != 4096
                or mask.shape != (features.shape[0],)
                or not self._np.isfinite(features).all()
                or not mask.any()
            ):
                raise RuntimeError(f"cached embedding {behavior} has an invalid shape or value")
            result[behavior] = (
                self._torch.from_numpy(features).unsqueeze(0).to("cuda:0"),
                self._torch.from_numpy(mask).unsqueeze(0).to("cuda:0"),
            )
        return result

    def generate(self, request: PoseRequest) -> dict[str, object]:
        # Timing-critical actions remain deterministic Unreal-side clips.
        if request.behavior not in {"idle", "listen", "explain"}:
            raise RuntimeError("behavior is reserved for the baked provider")
        embedding = self._embeddings.get(request.behavior)
        if embedding is None:
            raise RuntimeError("approved cached embedding is unavailable")
        with self._lock, self._torch.inference_mode():
            text_feat, text_pad_mask = embedding
            started = time.perf_counter()
            samples = self._model.autoregressive_step(
                num_frames=BATCH_FRAMES,
                num_denoising_steps=int(self._model.diffusion.num_base_steps),
                motion_mask=None,
                observed_motion=None,
                cfg_weight=2.0,
                texts=None,
                text_feat=text_feat,
                text_pad_mask=text_pad_mask,
                init_history_sequence=self._history,
            )
            self._torch.cuda.synchronize()
            self._generation_times_ms.append((time.perf_counter() - started) * 1000.0)
            self._generation_times_ms = self._generation_times_ms[-256:]
            # Bound history to the trained ten-second window minus one horizon.
            self._history = samples[:, -192:].detach()
            unnormalized = self._model.motion_rep.unnormalize(samples)
            output = self._model.motion_rep.inverse(unnormalized, is_normalized=False)
            local_matrices = output["local_rot_mats"][:, -BATCH_FRAMES:].detach().cpu().numpy()
            root_matrices = (
                output["global_rot_mats"][:, -BATCH_FRAMES:, 0].detach().cpu().numpy()
            )
            roots = output["root_positions"][:, -BATCH_FRAMES:].detach().cpu().numpy()
            contacts = output["foot_contacts"][:, -BATCH_FRAMES:].detach().cpu().numpy()
            sequence = max(self._sequence + 1, request.after_sequence + 1)
            frames = self._serialize_frames(
                local_matrices[0], root_matrices[0], roots[0], contacts[0]
            )
            self._sequence = sequence
        return validate_batch(
            {
                "version": PROTOCOL_VERSION,
                "sequence": sequence,
                "fps": FPS,
                "coordinateSystem": COORDINATE_SYSTEM,
                "frames": frames,
            }
        )

    def _serialize_frames(
        self,
        matrices: object,
        root_matrices: object,
        roots: object,
        contacts: object,
    ) -> list[dict[str, object]]:
        from scipy.spatial.transform import Rotation

        quaternions = Rotation.from_matrix(matrices.reshape(-1, 3, 3)).as_quat().reshape(
            BATCH_FRAMES, len(CORE27_JOINTS), 4
        )
        root_quaternions = Rotation.from_matrix(root_matrices).as_quat()
        frames: list[dict[str, object]] = []
        excluded = {CORE27_JOINTS.index(name) for name in EXCLUDED_GENERATED_JOINTS}
        for index in range(BATCH_FRAMES):
            joints = quaternions[index].tolist()
            for joint_index in excluded:
                joints[joint_index] = IDENTITY.copy()
            frames.append(
                {
                    "time": round(self._time + index / FPS, 6),
                    "root": [*roots[index].tolist(), *root_quaternions[index].tolist()],
                    "joints": joints,
                    "contacts": contacts[index].tolist(),
                }
            )
        self._time = frames[-1]["time"] + 1.0 / FPS
        return frames
