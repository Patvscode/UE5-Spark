#!/usr/bin/env python3
"""Strict loopback qualification for the real UE5-Spark ARDY provider."""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SERVICE_ROOT = REPOSITORY_ROOT / "services" / "ardy" / "service"
sys.path.insert(0, str(SERVICE_ROOT))

from pose_protocol import (  # noqa: E402
    BATCH_FRAMES,
    COORDINATE_SYSTEM,
    CORE27_JOINTS,
    FPS,
    PROTOCOL_VERSION,
    PoseRequest,
    ProtocolError,
    source_descriptor,
    validate_batch,
)
from motion_catalog import GENERATED_BEHAVIORS  # noqa: E402


ALLOWED_PORTS = frozenset({8777, 18777})
EXPECTED_CHECKPOINT = "ARDY-Core-RP-20FPS-Horizon8"
EXPECTED_EMBEDDING_COUNT = len(GENERATED_BEHAVIORS)
EXPECTED_PROVIDER = "ardy"
EXPECTED_FACIAL_CONTROL = "excluded"
QUALIFICATION_BEHAVIORS = GENERATED_BEHAVIORS
MINIMUM_BATCHES = 30
MAXIMUM_BATCHES = 100
MAX_P95_GENERATION_MS = 400.0
IDENTITY_QUATERNION = [0.0, 0.0, 0.0, 1.0]


class ValidationError(RuntimeError):
    """The loopback ARDY service failed its qualification contract."""


def _finite_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValidationError(f"{label} must be finite")
    return result


def _nearest_rank_p95(values: list[float]) -> float:
    if not values:
        raise ValidationError("cannot calculate p95 without samples")
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


def validate_real_health(value: object, *, require_latency: bool) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValidationError("health response must be a JSON object")
    expected = {
        "status": "ready",
        "provider": EXPECTED_PROVIDER,
        "protocolVersion": PROTOCOL_VERSION,
        "fps": FPS,
        "bufferFrames": BATCH_FRAMES,
        "facialControl": EXPECTED_FACIAL_CONTROL,
        "coordinateSystem": COORDINATE_SYSTEM,
        "source": source_descriptor(),
        "motionCatalog": list(GENERATED_BEHAVIORS),
        "checkpoint": EXPECTED_CHECKPOINT,
        "embeddingCount": EXPECTED_EMBEDDING_COUNT,
    }
    if set(value) != {*expected, "p95GenerationMs"}:
        raise ValidationError("health response has an invalid envelope")
    for key, expected_value in expected.items():
        if value.get(key) != expected_value or type(value.get(key)) is not type(expected_value):
            raise ValidationError(f"health field {key} does not match the sealed contract")
    latency = _finite_number(value.get("p95GenerationMs"), "health p95GenerationMs")
    if latency < 0.0:
        raise ValidationError("health p95GenerationMs cannot be negative")
    if require_latency and not 0.0 < latency < MAX_P95_GENERATION_MS:
        raise ValidationError("provider p95 generation latency exceeds the 400 ms buffer")
    return value


def _validate_quaternion(value: object, label: str) -> None:
    if not isinstance(value, list) or len(value) != 4:
        raise ValidationError(f"{label} is not an XYZW quaternion")
    components = [_finite_number(component, label) for component in value]
    magnitude = math.sqrt(sum(component * component for component in components))
    if not 0.995 <= magnitude <= 1.005:
        raise ValidationError(f"{label} is not normalized")


def _quaternion_dot(left: list[float], right: list[float]) -> float:
    return sum(float(a) * float(b) for a, b in zip(left, right))


def validate_real_batch(
    value: object,
    *,
    after_sequence: int,
    previous_time: float | None,
    previous_quaternions: tuple[list[float], list[list[float]]] | None = None,
) -> tuple[
    dict[str, object],
    int,
    float,
    tuple[list[float], list[list[float]]],
]:
    try:
        batch = validate_batch(value)
    except ProtocolError as error:
        raise ValidationError(str(error)) from error
    if len(batch["frames"]) != BATCH_FRAMES:
        raise ValidationError("real provider must return exactly eight frames")
    sequence = batch["sequence"]
    if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence <= after_sequence:
        raise ValidationError("pose sequence did not advance beyond the consumer cursor")
    neck_index = CORE27_JOINTS.index("Neck")
    head_index = CORE27_JOINTS.index("Head")
    frames = batch["frames"]
    first_time = float(frames[0]["time"])
    if previous_time is not None and not math.isclose(
        first_time - previous_time, 1.0 / FPS, abs_tol=1e-5
    ):
        raise ValidationError("frame time did not advance by 50 ms across pose batches")
    if previous_quaternions is not None:
        previous_root, previous_joints = previous_quaternions
        if _quaternion_dot(frames[0]["root"][3:], previous_root) < -1e-8:
            raise ValidationError("root quaternion changed hemisphere across pose batches")
        if any(
            _quaternion_dot(current, previous) < -1e-8
            for current, previous in zip(frames[0]["joints"], previous_joints)
        ):
            raise ValidationError("joint quaternion changed hemisphere across pose batches")
    for frame_index, frame in enumerate(frames):
        if frame_index > 0 and not math.isclose(
            float(frame["time"]) - float(frames[frame_index - 1]["time"]),
            1.0 / FPS,
            abs_tol=1e-5,
        ):
            raise ValidationError("pose frames are not spaced at exactly 20 FPS")
        _validate_quaternion(frame["root"][3:], f"frame {frame_index} root rotation")
        for joint_index, rotation in enumerate(frame["joints"]):
            _validate_quaternion(
                rotation,
                f"frame {frame_index} joint {CORE27_JOINTS[joint_index]}",
            )
        if frame["joints"][neck_index] != IDENTITY_QUATERNION:
            raise ValidationError("ARDY attempted to control the StreamingADA neck joint")
        if frame["joints"][head_index] != IDENTITY_QUATERNION:
            raise ValidationError("ARDY attempted to control the StreamingADA head joint")
        if not all(type(contact) is float for contact in frame["contacts"]):
            raise ValidationError("contact flags must be serialized as protocol floats")
        if not all(0.0 <= contact <= 1.0 for contact in frame["contacts"]):
            raise ValidationError("contact confidence is outside the normalized range")
        if any(
            not math.isclose(
                float(root_component),
                float(position_component),
                abs_tol=1e-5,
            )
            for root_component, position_component in zip(
                frame["root"][:3], frame["positions"][0]
            )
        ):
            raise ValidationError("root translation does not match posed Hips position")
    last_frame = frames[-1]
    quaternion_state = (
        [float(value) for value in last_frame["root"][3:]],
        [[float(value) for value in rotation] for rotation in last_frame["joints"]],
    )
    return batch, sequence, float(last_frame["time"]), quaternion_state


def _request_json(
    port: int,
    path: str,
    *,
    payload: object | None = None,
    timeout: float,
) -> object:
    url = f"http://127.0.0.1:{port}{path}"
    body = None
    headers = {"Accept": "application/json"}
    method = "GET"
    if payload is not None:
        body = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
        method = "POST"
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                raise ValidationError(f"{path} returned HTTP {response.status}")
            content_type = response.headers.get_content_type()
            if content_type != "application/json":
                raise ValidationError(f"{path} did not return application/json")
            response_body = response.read(8 * 1024 * 1024 + 1)
    except (urllib.error.URLError, TimeoutError) as error:
        raise ValidationError(f"{path} request failed: {error}") from error
    if len(response_body) > 8 * 1024 * 1024:
        raise ValidationError(f"{path} response exceeded the size bound")
    try:
        return json.loads(response_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValidationError(f"{path} returned invalid JSON") from error


def wait_for_real_health(port: int, startup_timeout: int) -> dict[str, object]:
    deadline = time.monotonic() + startup_timeout
    last_error = "service did not answer"
    while time.monotonic() < deadline:
        try:
            return validate_real_health(
                _request_json(port, "/healthz", timeout=5.0),
                require_latency=False,
            )
        except ValidationError as error:
            last_error = str(error)
            time.sleep(1.0)
    raise ValidationError(f"real provider was not ready before timeout: {last_error}")


def qualify_service(port: int, batches: int, startup_timeout: int) -> dict[str, object]:
    if port not in ALLOWED_PORTS:
        raise ValidationError("port must be the production or fixed canary loopback port")
    if not MINIMUM_BATCHES <= batches <= MAXIMUM_BATCHES:
        raise ValidationError("batch count must be between 30 and 100")
    initial_health = wait_for_real_health(port, startup_timeout)
    after_sequence = 0
    previous_time: float | None = None
    previous_quaternions: tuple[list[float], list[list[float]]] | None = None
    elapsed_ms: list[float] = []
    behavior_counts = {behavior: 0 for behavior in QUALIFICATION_BEHAVIORS}
    for batch_index in range(batches):
        behavior = QUALIFICATION_BEHAVIORS[batch_index % len(QUALIFICATION_BEHAVIORS)]
        request = PoseRequest(behavior, 0.65, 1.0, after_sequence)
        started = time.perf_counter()
        response = _request_json(
            port,
            "/v2/poses",
            payload={
                "behavior": request.behavior,
                "intensity": request.intensity,
                "duration": request.duration,
                "afterSequence": request.after_sequence,
            },
            timeout=30.0,
        )
        elapsed_ms.append((time.perf_counter() - started) * 1000.0)
        _, after_sequence, previous_time, previous_quaternions = validate_real_batch(
            response,
            after_sequence=after_sequence,
            previous_time=previous_time,
            previous_quaternions=previous_quaternions,
        )
        behavior_counts[behavior] += 1
    final_health = validate_real_health(
        _request_json(port, "/healthz", timeout=5.0),
        require_latency=True,
    )
    steady_elapsed = elapsed_ms[1:]
    steady_p95 = _nearest_rank_p95(steady_elapsed)
    if steady_p95 >= MAX_P95_GENERATION_MS:
        raise ValidationError("observed steady p95 request latency exceeds the 400 ms buffer")
    return {
        "schemaVersion": 2,
        "status": "passed",
        "host": "127.0.0.1",
        "port": port,
        "batches": batches,
        "frames": batches * BATCH_FRAMES,
        "behaviorCounts": behavior_counts,
        "firstRequestMs": round(elapsed_ms[0], 3),
        "steadyMeanMs": round(sum(steady_elapsed) / len(steady_elapsed), 3),
        "steadyP95Ms": round(steady_p95, 3),
        "steadyMaxMs": round(max(steady_elapsed), 3),
        "finalSequence": after_sequence,
        "finalFrameTime": previous_time,
        "initialHealth": initial_health,
        "finalHealth": final_health,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, choices=sorted(ALLOWED_PORTS), default=8777)
    parser.add_argument("--batches", type=int, default=MINIMUM_BATCHES)
    parser.add_argument("--startup-timeout", type=int, default=180)
    args = parser.parse_args()
    if not 1 <= args.startup_timeout <= 300:
        parser.error("--startup-timeout must be between 1 and 300 seconds")
    return args


def main() -> int:
    args = parse_args()
    try:
        result = qualify_service(args.port, args.batches, args.startup_timeout)
    except ValidationError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
