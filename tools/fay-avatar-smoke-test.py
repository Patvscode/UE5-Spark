#!/usr/bin/env python3
"""Exercise Fay's avatar WebSocket with a real end-to-end reply.

The test registers as an avatar renderer, submits one OpenAI-compatible chat
request, and verifies that Fay delivers playable audio metadata to that same
renderer.  It deliberately has no Unreal dependency, so it can validate the
backend before a packaged renderer is available.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from urllib.parse import urlparse

import websocket


def default_ws_url(http_base: str) -> str:
    parsed = urlparse(http_base)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    host = parsed.hostname or "127.0.0.1"
    return f"{scheme}://{host}:10002"


def submit_chat(http_base: str, username: str, prompt: str, timeout: float) -> dict:
    payload = {
        "model": "fay",
        "user": username,
        "messages": [{"role": "user", "content": prompt}],
    }
    request = urllib.request.Request(
        f"{http_base.rstrip('/')}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def audio_is_fetchable(url: str, timeout: float) -> bool:
    try:
        request = urllib.request.Request(url, headers={"Range": "bytes=0-31"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status in (200, 206) and bool(response.read(32))
    except Exception:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--http-base", default="http://127.0.0.1:5000")
    parser.add_argument("--ws-url", help="Defaults to ws(s)://<HTTP host>:10002")
    parser.add_argument("--username", default="AvatarSmokeTest")
    parser.add_argument(
        "--prompt",
        default="Reply with exactly: Avatar connection verified.",
    )
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args()

    ws_url = args.ws_url or default_ws_url(args.http_base)
    summary: dict[str, object] = {
        "ok": False,
        "http_base": args.http_base,
        "ws_url": ws_url,
        "username": args.username,
        "message_count": 0,
        "keys": [],
        "audio_url": None,
        "audio_fetchable": False,
        "errors": [],
    }

    connection = None
    try:
        connection = websocket.create_connection(ws_url, timeout=5)
        connection.send(json.dumps({"Username": args.username, "Output": True}))
        time.sleep(0.2)

        submit_chat(args.http_base, args.username, args.prompt, args.timeout)

        deadline = time.monotonic() + args.timeout
        observed_keys: list[str] = []
        audio_message = None
        while time.monotonic() < deadline:
            connection.settimeout(max(0.1, min(5.0, deadline - time.monotonic())))
            try:
                raw_message = connection.recv()
            except websocket.WebSocketTimeoutException:
                continue
            if not raw_message:
                continue

            message = json.loads(raw_message)
            summary["message_count"] = int(summary["message_count"]) + 1
            if message.get("Topic") != "human":
                continue
            data = message.get("Data") or {}
            key = data.get("Key")
            if key and key not in observed_keys:
                observed_keys.append(key)
            if key == "audio" and data.get("HttpValue"):
                audio_message = data
                if data.get("IsEnd"):
                    break

        summary["keys"] = observed_keys
        if audio_message is None:
            summary["errors"].append("No avatar audio message was received")
        else:
            audio_url = audio_message["HttpValue"]
            summary["audio_url"] = audio_url
            summary["text"] = audio_message.get("Text", "")
            summary["duration_seconds"] = audio_message.get("Time")
            summary["sentiment"] = audio_message.get("Sentiment")
            summary["action"] = audio_message.get("Action")
            summary["has_lips"] = bool(audio_message.get("Lips"))
            summary["audio_fetchable"] = audio_is_fetchable(audio_url, 10)
            if not summary["audio_fetchable"]:
                summary["errors"].append("The supplied audio URL was not fetchable")

        summary["ok"] = not summary["errors"]
    except Exception as exc:
        summary["errors"].append(f"{type(exc).__name__}: {exc}")
    finally:
        if connection is not None:
            connection.close()

    print(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
