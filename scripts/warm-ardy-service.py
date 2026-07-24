#!/usr/bin/env python3
"""Wait for and warm the fixed loopback ARDY service before Unreal starts."""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
import urllib.error
import urllib.request
from typing import Callable


ARDY_BASE_URL = "http://127.0.0.1:8777"
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
WARM_POSE = {
    "behavior": "idle",
    "intensity": 0.35,
    "duration": 1.0,
    "afterSequence": 0,
}
LOOPBACK_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def bounded_timeout(value: str) -> int:
    try:
        seconds = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("timeout must be an integer") from exc
    if not 30 <= seconds <= 600:
        raise argparse.ArgumentTypeError("timeout must be between 30 and 600 seconds")
    return seconds


def request_json(
    method: str,
    path: str,
    payload: dict[str, object] | None = None,
) -> dict[str, object]:
    if method not in {"GET", "POST"} or path not in {"/healthz", "/v2/poses"}:
        raise ValueError("ARDY readiness request is not allowlisted")
    data = (
        None
        if payload is None
        else json.dumps(payload, separators=(",", ":")).encode("utf-8")
    )
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"{ARDY_BASE_URL}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    with LOOPBACK_OPENER.open(request, timeout=10) as response:
        if response.status != 200:
            raise ValueError(f"ARDY returned HTTP {response.status}")
        body = response.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise ValueError("ARDY response exceeded the readiness bound")
    value = json.loads(body.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("ARDY response was not a JSON object")
    return value


def qualified_health(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    latency = value.get("p95GenerationMs")
    return (
        value.get("status") == "ready"
        and value.get("provider") == "ardy"
        and value.get("protocolVersion") == 2
        and value.get("dynamicTextReady") is True
        and not isinstance(latency, bool)
        and isinstance(latency, (int, float))
        and math.isfinite(float(latency))
        and 0.0 < float(latency) < 400.0
    )


def valid_warm_batch(value: object, previous_sequence: int) -> int | None:
    if not isinstance(value, dict):
        return None
    sequence = value.get("sequence")
    frames = value.get("frames")
    if (
        value.get("version") != 2
        or value.get("fps") != 20
        or type(sequence) is not int
        or sequence <= previous_sequence
        or not isinstance(frames, list)
        or len(frames) != 8
    ):
        return None
    return sequence


def wait_until_ready(
    timeout_seconds: int,
    *,
    requester: Callable[
        [str, str, dict[str, object] | None], dict[str, object]
    ] = request_json,
    monotonic: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, object]:
    deadline = monotonic() + timeout_seconds
    after_sequence = 0
    last_detail = "ARDY has not answered yet"
    while monotonic() < deadline:
        try:
            health = requester("GET", "/healthz", None)
            if qualified_health(health):
                return health
            if (
                health.get("status") == "ready"
                and health.get("provider") == "ardy"
                and health.get("protocolVersion") == 2
                and health.get("dynamicTextReady") is True
            ):
                pose = dict(WARM_POSE)
                pose["afterSequence"] = after_sequence
                batch = requester("POST", "/v2/poses", pose)
                next_sequence = valid_warm_batch(batch, after_sequence)
                if next_sequence is None:
                    last_detail = "ARDY returned an invalid cached idle pose batch"
                else:
                    after_sequence = next_sequence
                    last_detail = "waiting for ARDY p95 generation latency to qualify"
            else:
                last_detail = (
                    "waiting for ARDY dynamic text initialization and protocol v2"
                )
        except (
            OSError,
            ValueError,
            json.JSONDecodeError,
            UnicodeError,
            urllib.error.URLError,
        ) as exc:
            last_detail = str(exc)[:240]
        sleeper(1.0)
    raise TimeoutError(
        "ARDY did not become ready within the startup window: " + last_detail
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout-seconds", type=bounded_timeout, default=240)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        health = wait_until_ready(args.timeout_seconds)
    except TimeoutError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(
        "ARDY is warmed and ready: "
        f"dynamicTextReady=true, p95GenerationMs={health['p95GenerationMs']}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
