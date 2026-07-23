#!/usr/bin/env python3
"""Loopback-only, allowlisted pose service for UE5-Spark."""

from __future__ import annotations

import argparse
import json
import logging
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from socketserver import TCPServer

from motion_catalog import GENERATED_BEHAVIORS
from pose_protocol import (
    BATCH_FRAMES,
    COORDINATE_SYSTEM,
    FPS,
    PROTOCOL_VERSION,
    PoseRequest,
    ProtocolError,
    normalize_prompt,
    source_descriptor,
)
from providers import ArdyPoseProvider, MockPoseProvider


MAX_REQUEST_BYTES = 4096
LOGGER = logging.getLogger("ue5_spark_ardy")


class PoseServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], provider: object):
        super().__init__(address, PoseHandler)
        self.provider = provider

    def server_bind(self) -> None:
        """Bind without HTTPServer's unnecessary reverse-DNS lookup."""

        TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = str(host)
        self.server_port = int(port)


class PoseHandler(BaseHTTPRequestHandler):
    server: PoseServer
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/healthz":
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        self._json(
            HTTPStatus.OK,
            {
                "status": "ready" if self.server.provider.ready else "degraded",
                "provider": self.server.provider.name,
                "protocolVersion": PROTOCOL_VERSION,
                "fps": FPS,
                "bufferFrames": BATCH_FRAMES,
                "facialControl": "excluded",
                "coordinateSystem": COORDINATE_SYSTEM,
                "source": source_descriptor(),
                "motionCatalog": list(GENERATED_BEHAVIORS),
                **self.server.provider.health,
            },
        )

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/v2/prompts":
            self._prewarm_prompt()
            return
        if self.path != "/v2/poses":
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        try:
            request = PoseRequest.from_json(self._read_json())
            batch = self.server.provider.generate(request)
        except (ProtocolError, json.JSONDecodeError, UnicodeDecodeError) as error:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid_request", "detail": str(error)})
            return
        except Exception:
            LOGGER.exception("pose generation failed")
            self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "provider_unavailable"})
            return
        self._json(HTTPStatus.OK, batch)

    def _prewarm_prompt(self) -> None:
        try:
            payload = self._read_json()
            if not isinstance(payload, dict) or set(payload) != {"prompt"}:
                raise ProtocolError("prompt prewarm requires exactly one prompt")
            prompt = normalize_prompt(payload["prompt"])
        except (ProtocolError, json.JSONDecodeError, UnicodeDecodeError) as error:
            self._json(
                HTTPStatus.BAD_REQUEST,
                {"error": "invalid_request", "detail": str(error)},
            )
            return

        prewarm = getattr(self.server.provider, "prewarm_prompt", None)
        if not callable(prewarm):
            self._json(
                HTTPStatus.SERVICE_UNAVAILABLE,
                {"error": "dynamic_text_unavailable"},
            )
            return
        try:
            response = prewarm(prompt)
        except Exception:
            LOGGER.exception("prompt prewarm failed")
            self._json(
                HTTPStatus.SERVICE_UNAVAILABLE,
                {"error": "provider_unavailable"},
            )
            return
        self._json(HTTPStatus.OK, response)

    def _read_json(self) -> object:
        value = self.headers.get("Content-Length")
        if value is None or not value.isdecimal():
            raise ProtocolError("Content-Length is required")
        length = int(value)
        if not 1 <= length <= MAX_REQUEST_BYTES:
            raise ProtocolError("request body size is outside the supported range")
        if self.headers.get_content_type() != "application/json":
            raise ProtocolError("Content-Type must be application/json")
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _json(self, status: HTTPStatus, payload: object) -> None:
        body = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format_string: str, *args: object) -> None:
        LOGGER.info("client=%s " + format_string, self.client_address[0], *args)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8777)
    parser.add_argument("--provider", choices=("mock", "ardy"), default="mock")
    parser.add_argument("--models-root", type=Path, default=Path("/models"))
    parser.add_argument(
        "--model",
        choices=("ARDY-Core-RP-20FPS-Horizon8",),
        default="ARDY-Core-RP-20FPS-Horizon8",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.host != "127.0.0.1":
        raise SystemExit("the pose service may bind only to 127.0.0.1")
    if not 1024 <= args.port <= 65535:
        raise SystemExit("port is outside the supported range")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    provider = (
        MockPoseProvider()
        if args.provider == "mock"
        else ArdyPoseProvider(args.models_root, args.model)
    )
    server = PoseServer((args.host, args.port), provider)
    LOGGER.info("pose service ready on loopback port %d", args.port)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
