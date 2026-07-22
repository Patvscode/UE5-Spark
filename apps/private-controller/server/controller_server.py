#!/usr/bin/env python3
"""Private same-origin controller and narrow Fay proxy for UE5-Spark."""

from __future__ import annotations

import argparse
import ipaddress
import json
import mimetypes
import os
import re
import socket
import stat
import time
import urllib.error
import urllib.parse
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from typing import Any


TAILSCALE_NET = ipaddress.ip_network("100.64.0.0/10")
MAX_REQUEST_BYTES = 8 * 1024
MAX_MESSAGE_CHARS = 2_000
MAX_LIVE_FRAME_BYTES = 2 * 1024 * 1024
MAX_LIVE_FRAME_AGE_SECONDS = 2.0
SERVER_VERSION = "prototype-2"
THINK_BLOCK_PATTERN = re.compile(r"<think>.*?(?:</think>|$)", re.IGNORECASE | re.DOTALL)
ALLOWED_BEHAVIORS = frozenset({
    "idle", "listen", "wave", "invite", "think", "warn", "nod", "shake", "explain",
})
MEDIA_MAP = {
    "ada-idle.mp4": "v21/ada-v21-idle-isolation-8s-20260721T131806Z.mp4",
    "ada-wave.mp4": "v28/ada-20260721T212709Z/ada-v28-speaking-wave-front-8s.mp4",
    "ada-explain.mp4": "v28/ada-real-ardy-20260721T231312Z/ada-v28-real-ardy-explain-8s.mp4",
    "ada-listen.mp4": "v12/ada-v12-face-body.mp4",
    "ada-poster.png": "v28/ada-real-ardy-20260721T231312Z/ada-v28-real-ardy-explain.png",
    "aoi-motion.mp4": "v13/aoi-v13-speech-motion.mp4",
    "aoi-explain.mp4": "v13/aoi-v13-explain.mp4",
    "aoi-poster.png": "v13/aoi-v13-launch.png",
}


def checked_bind_host(value: str) -> str:
    address = ipaddress.ip_address(value)
    if not (address.is_loopback or address in TAILSCALE_NET):
        raise argparse.ArgumentTypeError("host must be loopback or a concrete Tailscale IPv4 address")
    return str(address)


def checked_upstream(value: str, *, loopback_only: bool = False) -> str:
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme != "http" or not parsed.hostname or parsed.username or parsed.password:
        raise argparse.ArgumentTypeError("upstream must be an unauthenticated HTTP origin")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("upstream host must be a concrete IP address") from exc
    if loopback_only and not address.is_loopback:
        raise argparse.ArgumentTypeError("upstream must be loopback")
    if not loopback_only and not (address.is_loopback or address in TAILSCALE_NET):
        raise argparse.ArgumentTypeError("upstream must be loopback or Tailscale")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise argparse.ArgumentTypeError("upstream must not include a path, query, or fragment")
    return value.rstrip("/")


def normalize_action(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict) or not set(payload).issubset({"behavior", "intensity", "duration"}):
        raise ValueError("action must be a small JSON object")
    behavior = str(payload.get("behavior", "")).strip().lower()
    if behavior not in ALLOWED_BEHAVIORS:
        raise ValueError("behavior is not allowlisted")
    try:
        intensity = float(payload.get("intensity", 0.5))
        duration = float(payload.get("duration", 1.0))
    except (TypeError, ValueError) as exc:
        raise ValueError("intensity and duration must be numbers") from exc
    if not 0 <= intensity <= 1 or not 0.2 <= duration <= 10:
        raise ValueError("action values are outside the reviewed bounds")
    return {"behavior": behavior, "intensity": intensity, "duration": duration, "user": "User"}


def normalize_message(payload: object) -> str:
    if not isinstance(payload, dict) or set(payload) != {"message"}:
        raise ValueError("chat request must contain only message")
    message = payload.get("message")
    if not isinstance(message, str):
        raise ValueError("message must be text")
    message = message.strip()
    if not message or len(message) > MAX_MESSAGE_CHARS:
        raise ValueError("message must contain 1 to 2000 characters")
    return message


def normalize_reply(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("invalid reply")
    reply = THINK_BLOCK_PATTERN.sub("", value)
    reply = re.sub(r"</?think>", "", reply, flags=re.IGNORECASE)
    reply = re.sub(r"[ \t]+", " ", reply)
    reply = re.sub(r"\n{3,}", "\n\n", reply).strip()
    return reply or "I’m ready—please try that again."


def safe_root(path: Path, label: str) -> Path:
    if path.is_symlink():
        raise ValueError(f"{label} must not be a symlink")
    resolved = path.resolve(strict=True)
    if not resolved.is_dir():
        raise ValueError(f"{label} must be a directory")
    return resolved


def safe_private_root(path: Path, label: str) -> Path:
    resolved = safe_root(path, label)
    metadata = resolved.stat()
    if metadata.st_uid != os.geteuid():
        raise ValueError(f"{label} must be owned by the current user")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise ValueError(f"{label} must not be accessible by group or other users")
    return resolved


def read_live_frame(live_root: Path, *, now_ns: int | None = None) -> bytes | None:
    """Read one fresh, private JPEG without following a replaceable symlink."""
    frame_path = live_root / "frame.jpg"
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(frame_path, flags)
    except (FileNotFoundError, OSError):
        return None
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            return None
        if metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) & 0o077:
            return None
        if not 4 <= metadata.st_size <= MAX_LIVE_FRAME_BYTES:
            return None
        current_ns = time.time_ns() if now_ns is None else now_ns
        age_ns = current_ns - metadata.st_mtime_ns
        if age_ns < 0 or age_ns > int(MAX_LIVE_FRAME_AGE_SECONDS * 1_000_000_000):
            return None
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            payload = stream.read(MAX_LIVE_FRAME_BYTES + 1)
        if len(payload) != metadata.st_size:
            return None
        if not payload.startswith(b"\xff\xd8") or not payload.endswith(b"\xff\xd9"):
            return None
        return payload
    finally:
        os.close(descriptor)


def live_stream_ready(renderer: bool, live_root: Path) -> bool:
    return renderer and read_live_frame(live_root) is not None


class ControllerServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], dist: Path, media_root: Path,
                 live_root: Path, fay_base: str, ardy_base: str):
        super().__init__(address, ControllerHandler)
        self.dist = dist
        self.media_root = media_root
        self.live_root = live_root
        self.fay_base = fay_base
        self.ardy_base = ardy_base


class ControllerHandler(BaseHTTPRequestHandler):
    server: ControllerServer

    def do_GET(self) -> None:  # noqa: N802
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/status":
            self._status()
        elif path == "/live/frame.jpg":
            self._live_frame()
        elif path.startswith("/media/"):
            self._media(path.removeprefix("/media/"))
        elif path.startswith("/api/") or path.startswith("/live/"):
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
        else:
            self._static(path)

    def do_HEAD(self) -> None:  # noqa: N802
        path = urllib.parse.urlparse(self.path).path
        if path == "/live/frame.jpg":
            self._live_frame(head_only=True)
        elif path.startswith("/media/"):
            self._media(path.removeprefix("/media/"), head_only=True)
        elif not path.startswith("/api/") and not path.startswith("/live/"):
            self._static(path, head_only=True)
        else:
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"}, head_only=True)

    def do_POST(self) -> None:  # noqa: N802
        path = urllib.parse.urlparse(self.path).path
        try:
            payload = self._request_json()
            if path == "/api/chat":
                self._chat(payload)
            elif path == "/api/action":
                self._action(payload)
            else:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
        except ValueError as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._json(HTTPStatus.METHOD_NOT_ALLOWED, {"error": "same_origin_only"})

    def _request_json(self) -> object:
        if self.headers.get_content_type() != "application/json":
            raise ValueError("Content-Type must be application/json")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("invalid Content-Length") from exc
        if not 1 <= length <= MAX_REQUEST_BYTES:
            raise ValueError("request body is outside the allowed size")
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("request body must be valid JSON") from exc

    def _status(self) -> None:
        fay = False
        renderer = False
        ardy = False
        try:
            status = self._upstream_json(
                f"{self.server.fay_base}/api/get-system-status?username=User", timeout=3,
            )
            fay = status.get("server") is True
            renderer = status.get("digital_human") is True
        except (OSError, ValueError, urllib.error.URLError):
            pass
        try:
            status = self._upstream_json(f"{self.server.ardy_base}/healthz", timeout=3)
            ardy = status.get("status") == "ready"
        except (OSError, ValueError, urllib.error.URLError):
            pass
        stream = live_stream_ready(renderer, self.server.live_root)
        self._json(HTTPStatus.OK, {
            "fay": fay, "ardy": ardy, "renderer": renderer, "stream": stream,
            "mode": (
                "live-preview" if stream else
                "renderer-unstreamed" if renderer else
                "verified-replay"
            ),
            "version": SERVER_VERSION,
        })

    def _live_frame(self, head_only: bool = False) -> None:
        payload = read_live_frame(self.server.live_root)
        if payload is None:
            self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "live_frame_unavailable"},
                       head_only=head_only)
            return
        self.send_response(HTTPStatus.OK)
        self._security_headers("image/jpeg", {"Content-Length": str(len(payload))})
        self.end_headers()
        if not head_only:
            self.wfile.write(payload)

    def _chat(self, payload: object) -> None:
        message = normalize_message(payload)
        upstream_payload = {
            "model": "fay", "user": "User",
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Reply in concise, natural English. Never expose hidden reasoning, "
                        "analysis, or <think> tags. Do not claim the avatar performed an "
                        "action unless the user used an available movement control."
                    ),
                },
                {"role": "user", "content": message},
            ],
        }
        try:
            response = self._upstream_json(
                f"{self.server.fay_base}/v1/chat/completions", upstream_payload, timeout=180,
            )
            reply = normalize_reply(response["choices"][0]["message"]["content"])
        except urllib.error.HTTPError as exc:
            self._json(HTTPStatus.BAD_GATEWAY, {"error": f"Fay returned HTTP {exc.code}"})
            return
        except (KeyError, IndexError, TypeError, ValueError, OSError, urllib.error.URLError, socket.timeout):
            self._json(HTTPStatus.BAD_GATEWAY, {"error": "Fay conversation is temporarily unavailable"})
            return
        self._json(HTTPStatus.OK, {"reply": reply, "liveRenderer": self._renderer_online()})

    def _action(self, payload: object) -> None:
        action = normalize_action(payload)
        try:
            response = self._upstream_json(
                f"{self.server.fay_base}/api/avatar/action", action, timeout=5,
            )
        except urllib.error.HTTPError as exc:
            if exc.code == HTTPStatus.SERVICE_UNAVAILABLE:
                self._json(HTTPStatus.OK, {
                    "ok": True, "live": False, "replay": True,
                    "behavior": action["behavior"], "detail": "renderer_offline",
                })
                return
            self._json(HTTPStatus.BAD_GATEWAY, {"error": "avatar action failed"})
            return
        except (OSError, ValueError, urllib.error.URLError, socket.timeout):
            self._json(HTTPStatus.BAD_GATEWAY, {"error": "avatar action service is unavailable"})
            return
        self._json(HTTPStatus.OK, {
            "ok": response.get("ok") is True, "live": response.get("ok") is True,
            "replay": False, "behavior": action["behavior"],
        })

    def _renderer_online(self) -> bool:
        try:
            status = self._upstream_json(
                f"{self.server.fay_base}/api/get-system-status?username=User", timeout=2,
            )
            return status.get("digital_human") is True
        except (OSError, ValueError, urllib.error.URLError):
            return False

    def _upstream_json(self, url: str, payload: dict[str, Any] | None = None,
                       *, timeout: float) -> dict[str, Any]:
        data = None if payload is None else json.dumps(payload, separators=(",", ":")).encode()
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != HTTPStatus.OK:
                raise ValueError("unexpected upstream status")
            body = response.read(1024 * 1024)
        parsed = json.loads(body.decode("utf-8"))
        if not isinstance(parsed, dict):
            raise ValueError("upstream JSON must be an object")
        return parsed

    def _media(self, name: str, head_only: bool = False) -> None:
        relative = MEDIA_MAP.get(name)
        if relative is None or PurePosixPath(name).name != name:
            self._json(HTTPStatus.NOT_FOUND, {"error": "media_not_found"}, head_only=head_only)
            return
        path = self.server.media_root.joinpath(*PurePosixPath(relative).parts)
        if path.is_symlink() or not path.is_file():
            self._json(HTTPStatus.NOT_FOUND, {"error": "media_not_found"}, head_only=head_only)
            return
        self._file(path, head_only=head_only, allow_range=True)

    def _static(self, requested: str, head_only: bool = False) -> None:
        decoded = urllib.parse.unquote(requested)
        relative = PurePosixPath(decoded.lstrip("/") or "index.html")
        if relative.is_absolute() or ".." in relative.parts:
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"}, head_only=head_only)
            return
        path = self.server.dist.joinpath(*relative.parts)
        if path.is_symlink() or not path.is_file():
            if path.suffix:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"}, head_only=head_only)
                return
            path = self.server.dist / "index.html"
        self._file(path, head_only=head_only, allow_range=False)

    def _file(self, path: Path, *, head_only: bool, allow_range: bool) -> None:
        size = path.stat().st_size
        start, end = 0, size - 1
        status = HTTPStatus.OK
        range_header = self.headers.get("Range") if allow_range else None
        if range_header:
            match = re.fullmatch(r"bytes=(\d+)-(\d*)", range_header.strip())
            if not match:
                self._empty(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                return
            start = int(match.group(1))
            end = int(match.group(2)) if match.group(2) else size - 1
            if not 0 <= start <= end < size:
                self._empty(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                return
            status = HTTPStatus.PARTIAL_CONTENT
        length = end - start + 1
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        headers = {"Content-Length": str(length)}
        if allow_range:
            headers["Accept-Ranges"] = "bytes"
        if status == HTTPStatus.PARTIAL_CONTENT:
            headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        self.send_response(status)
        self._security_headers(content_type, headers)
        self.end_headers()
        if not head_only:
            with path.open("rb") as stream:
                stream.seek(start)
                remaining = length
                while remaining:
                    block = stream.read(min(1024 * 1024, remaining))
                    if not block:
                        break
                    self.wfile.write(block)
                    remaining -= len(block)

    def _json(self, status: HTTPStatus, payload: object, *, head_only: bool = False) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self._security_headers("application/json; charset=utf-8", {"Content-Length": str(len(body))})
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

    def _empty(self, status: HTTPStatus) -> None:
        self.send_response(status)
        self._security_headers("text/plain; charset=utf-8", {"Content-Length": "0"})
        self.end_headers()

    def _security_headers(self, content_type: str, extra: dict[str, str]) -> None:
        self.send_header("Content-Type", content_type)
        for key, value in extra.items():
            self.send_header(key, value)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Permissions-Policy", "camera=(), geolocation=(), payment=(), usb=()")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; base-uri 'none'; connect-src 'self'; font-src 'self'; "
            "form-action 'self'; frame-ancestors 'none'; img-src 'self' blob:; media-src 'self'; "
            "object-src 'none'; script-src 'self'; style-src 'self'",
        )

    def log_message(self, _format: str, *_args: object) -> None:
        return


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1", type=checked_bind_host)
    parser.add_argument("--port", type=int, default=8475)
    parser.add_argument("--dist", required=True, type=Path)
    parser.add_argument("--media-root", required=True, type=Path)
    parser.add_argument("--live-root", required=True, type=Path)
    parser.add_argument("--fay-base", required=True)
    parser.add_argument("--ardy-base", default="http://127.0.0.1:8777")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not 1024 <= args.port <= 65535:
        raise SystemExit("port must be unprivileged")
    try:
        dist = safe_root(args.dist, "dist")
        media_root = safe_root(args.media_root, "media root")
        live_root = safe_private_root(args.live_root, "live root")
        fay_base = checked_upstream(args.fay_base)
        ardy_base = checked_upstream(args.ardy_base, loopback_only=True)
    except (ValueError, argparse.ArgumentTypeError) as exc:
        raise SystemExit(str(exc)) from exc
    missing = [relative for relative in MEDIA_MAP.values() if not (media_root / relative).is_file()]
    if missing:
        raise SystemExit(f"missing private media: {', '.join(missing)}")
    server = ControllerServer(
        (args.host, args.port), dist, media_root, live_root, fay_base, ardy_base,
    )
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
