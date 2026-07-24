# SPDX-FileCopyrightText: Copyright (c) 2026 Patrick Mello
# SPDX-License-Identifier: MIT

"""Small, Blender-independent client for live ARDY motion previews."""

from __future__ import annotations

import json
import math
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .formats import CORE27_NAMES


FPS = 20
BATCH_FRAMES = 8
MAX_PROMPT_CHARS = 512
MAX_DURATION_SECONDS = 10.0

# ARDY Core27 -> the deforming portion of the UE5 skeleton used by Casual Girl.
# Fingers, twist bones, breasts, IK helpers, and facial bones intentionally keep
# their authored pose while ARDY drives the larger body chains.
CASUAL_GIRL_BONE_MAP = {
    "Hips": "pelvis",
    "Spine": "spine_01",
    "Spine1": "spine_02",
    "Spine2": "spine_03",
    "Spine3": "spine_05",
    "Neck": "neck_01",
    "Head": "head",
    "RightShoulder": "clavicle_r",
    "RightArm": "upperarm_r",
    "RightForeArm": "lowerarm_r",
    "RightHand": "hand_r",
    "RightHandEnd": "middle_03_r",
    "RightHandThumb1": "thumb_01_r",
    "LeftShoulder": "clavicle_l",
    "LeftArm": "upperarm_l",
    "LeftForeArm": "lowerarm_l",
    "LeftHand": "hand_l",
    "LeftHandEnd": "middle_03_l",
    "LeftHandThumb1": "thumb_01_l",
    "RightUpLeg": "thigh_r",
    "RightLeg": "calf_r",
    "RightFoot": "foot_r",
    "RightToeBase": "ball_r",
    "LeftUpLeg": "thigh_l",
    "LeftLeg": "calf_l",
    "LeftFoot": "foot_l",
    "LeftToeBase": "ball_l",
}


class ArdyPreviewError(RuntimeError):
    """A live preview request or response was not usable."""


def normalize_endpoint(value: str) -> str:
    endpoint = value.strip().rstrip("/")
    parsed = urlparse(endpoint)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost"}
        or parsed.port != 8777
        or parsed.path not in {"", "/"}
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise ArdyPreviewError(
            "ARDY preview endpoint must be http://127.0.0.1:8777"
        )
    return "http://127.0.0.1:8777"


def normalize_prompt(value: str) -> str:
    prompt = value.strip()
    if not 1 <= len(prompt) <= MAX_PROMPT_CHARS:
        raise ArdyPreviewError("prompt must contain 1 to 512 characters")
    return prompt


def _json_request(
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    timeout: float = 120.0,
) -> dict[str, Any]:
    body = None
    headers = {
        "Accept": "application/json",
        "Connection": "close",
    }
    if payload is not None:
        body = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode(
            "utf-8"
        )
        headers["Content-Type"] = "application/json"
    request = Request(url, data=body, headers=headers, method="POST" if body else "GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("detail")
        except Exception:
            detail = None
        raise ArdyPreviewError(
            detail or f"ARDY returned HTTP {exc.code}"
        ) from exc
    except (URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ArdyPreviewError(f"ARDY is unavailable: {exc}") from exc
    if not isinstance(result, dict):
        raise ArdyPreviewError("ARDY returned a non-object response")
    return result


def _finite_vector(value: object, length: int) -> bool:
    return (
        isinstance(value, list)
        and len(value) == length
        and all(
            isinstance(component, (int, float))
            and not isinstance(component, bool)
            and math.isfinite(float(component))
            for component in value
        )
    )


def validate_batch(value: dict[str, Any]) -> tuple[int, list[dict[str, Any]]]:
    if value.get("version") != 2 or value.get("fps") != FPS:
        raise ArdyPreviewError("ARDY did not return protocol-v2 20 FPS motion")
    source = value.get("source")
    if (
        not isinstance(source, dict)
        or source.get("system") != "nv-tlabs/ardy"
        or tuple(source.get("jointOrder", ())) != CORE27_NAMES
        or source.get("quaternionOrder") != "xyzw"
        or source.get("rotationSpace") != "local"
        or source.get("positionSpace") != "global"
    ):
        raise ArdyPreviewError("ARDY returned an incompatible skeleton contract")
    sequence = value.get("sequence")
    frames = value.get("frames")
    if (
        isinstance(sequence, bool)
        or not isinstance(sequence, int)
        or sequence < 1
        or not isinstance(frames, list)
        or len(frames) != BATCH_FRAMES
    ):
        raise ArdyPreviewError("ARDY returned an invalid pose batch")
    for frame in frames:
        if (
            not isinstance(frame, dict)
            or not _finite_vector(frame.get("root"), 7)
            or not isinstance(frame.get("joints"), list)
            or len(frame["joints"]) != len(CORE27_NAMES)
            or not all(_finite_vector(item, 4) for item in frame["joints"])
            or not isinstance(frame.get("positions"), list)
            or len(frame["positions"]) != len(CORE27_NAMES)
            or not all(_finite_vector(item, 3) for item in frame["positions"])
        ):
            raise ArdyPreviewError("ARDY returned a malformed Core27 frame")
    return sequence, frames


def fetch_motion(
    endpoint: str,
    prompt: str,
    *,
    intensity: float,
    duration: float,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    endpoint = normalize_endpoint(endpoint)
    prompt = normalize_prompt(prompt)
    if not math.isfinite(intensity) or not 0.0 <= intensity <= 1.0:
        raise ArdyPreviewError("intensity must be between zero and one")
    if (
        not math.isfinite(duration)
        or not 0.2 <= duration <= MAX_DURATION_SECONDS
    ):
        raise ArdyPreviewError("duration must be between 0.2 and 10 seconds")

    health = _json_request(f"{endpoint}/healthz", timeout=5.0)
    if (
        health.get("status") != "ready"
        or health.get("provider") != "ardy"
        or health.get("protocolVersion") != 2
        or health.get("dynamicTextReady") is not True
    ):
        raise ArdyPreviewError(
            "the open-text ARDY service is still starting or is not ready"
        )

    _json_request(
        f"{endpoint}/v2/prompts",
        payload={"prompt": prompt},
        timeout=120.0,
    )
    batch_count = max(1, math.ceil(duration * FPS / BATCH_FRAMES))
    frames: list[dict[str, Any]] = []
    sequence = 0
    for _index in range(batch_count):
        response = _json_request(
            f"{endpoint}/v2/poses",
            payload={
                "behavior": "explain",
                "prompt": prompt,
                "intensity": intensity,
                "duration": duration,
                "afterSequence": sequence,
            },
            timeout=60.0,
        )
        sequence, batch_frames = validate_batch(response)
        frames.extend(batch_frames)
    wanted = max(1, round(duration * FPS))
    return health, frames[:wanted]
