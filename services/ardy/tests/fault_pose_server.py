#!/usr/bin/env python3
"""Test-only loopback service for Unreal malformed/stale-batch recovery checks."""

from __future__ import annotations

import argparse
import json
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


SERVICE_ROOT = Path(__file__).resolve().parents[1] / "service"
sys.path.insert(0, str(SERVICE_ROOT))

from pose_protocol import PoseRequest  # noqa: E402
from providers import MockPoseProvider  # noqa: E402


class FaultServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, fault: str):
        super().__init__(("127.0.0.1", 8777), FaultHandler)
        self.fault = fault
        self.provider = MockPoseProvider()


class FaultHandler(BaseHTTPRequestHandler):
    server: FaultServer

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/healthz":
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        self._json(HTTPStatus.OK, {
            "status": "ready", "provider": "fault-test", "protocolVersion": 1,
            "fps": 20, "bufferFrames": 8, "facialControl": "excluded"
        })

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/v1/poses":
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        request = PoseRequest.from_json(json.loads(self.rfile.read(length)))
        if self.server.fault == "malformed":
            self._json(HTTPStatus.OK, {"version": 1, "sequence": 1, "frames": "invalid"})
            return
        batch = self.server.provider.generate(request)
        batch["sequence"] = 1
        self._json(HTTPStatus.OK, batch)

    def _json(self, status: HTTPStatus, payload: object) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format_string: str, *args: object) -> None:
        return


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fault", choices=("malformed", "stale"), required=True)
    args = parser.parse_args()
    server = FaultServer(args.fault)
    try:
        server.serve_forever(poll_interval=0.1)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

