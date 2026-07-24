#!/usr/bin/env python3
"""Small allowlisted progress/media server for a private Tailscale address."""

from __future__ import annotations

import argparse
import ipaddress
import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlparse


MAX_STATUS_BYTES = 256 * 1024
TAILSCALE_NET = ipaddress.ip_network((0x64400000, 10))


def load_status(path: Path, media_root: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_STATUS_BYTES:
        raise ValueError("status file must be a small regular file")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or set(payload) != {"title", "updated", "milestones"}:
        raise ValueError("invalid status document")
    if not isinstance(payload["title"], str) or not isinstance(payload["updated"], str):
        raise ValueError("invalid status heading")
    milestones = payload["milestones"]
    if not isinstance(milestones, list) or len(milestones) > 50:
        raise ValueError("invalid milestone count")
    allowed_media: set[str] = set()
    for milestone in milestones:
        if not isinstance(milestone, dict) or set(milestone) != {
            "id", "title", "status", "summary", "media"
        }:
            raise ValueError("invalid milestone")
        if milestone["status"] not in {"passed", "active", "blocked", "pending"}:
            raise ValueError("invalid milestone status")
        if not all(isinstance(milestone[key], str) for key in ("id", "title", "summary")):
            raise ValueError("invalid milestone text")
        if not isinstance(milestone["media"], list) or len(milestone["media"]) > 12:
            raise ValueError("invalid milestone media")
        for item in milestone["media"]:
            if not isinstance(item, dict) or set(item) != {"label", "file"}:
                raise ValueError("invalid media item")
            relative = PurePosixPath(item["file"])
            if relative.is_absolute() or ".." in relative.parts or not relative.parts:
                raise ValueError("unsafe media path")
            physical = media_root.joinpath(*relative.parts)
            current = media_root
            has_symlink = False
            for part in relative.parts:
                current /= part
                has_symlink = has_symlink or current.is_symlink()
            if has_symlink or not physical.is_file():
                raise ValueError(f"missing allowlisted media: {relative}")
            allowed_media.add(relative.as_posix())
    payload["allowedMedia"] = sorted(allowed_media)
    return payload


class HubServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, status_path: Path, media_root: Path, board_url: str):
        super().__init__(address, HubHandler)
        self.status_path = status_path
        self.media_root = media_root
        self.board_url = board_url


class HubHandler(BaseHTTPRequestHandler):
    server: HubServer

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/":
            self._send(HTTPStatus.OK, "text/html; charset=utf-8", self._page().encode())
            return
        if self.path == "/api/status":
            try:
                status = load_status(self.server.status_path, self.server.media_root)
            except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
                self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "status_unavailable"})
                return
            status["agentBoardUrl"] = self.server.board_url
            self._json(HTTPStatus.OK, status)
            return
        if self.path.startswith("/media/"):
            self._media(unquote(self.path.removeprefix("/media/")))
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_HEAD(self) -> None:  # noqa: N802
        if self.path.startswith("/media/"):
            self._media(unquote(self.path.removeprefix("/media/")), head_only=True)
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"}, head_only=True)

    def _media(self, requested: str, head_only: bool = False) -> None:
        try:
            status = load_status(self.server.status_path, self.server.media_root)
            relative = PurePosixPath(requested)
            if relative.as_posix() not in status["allowedMedia"]:
                raise ValueError("media is not allowlisted")
            path = self.server.media_root.joinpath(*relative.parts)
            size = path.stat().st_size
        except (OSError, ValueError, json.JSONDecodeError):
            self._json(HTTPStatus.NOT_FOUND, {"error": "media_not_found"})
            return
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        start = 0
        end = size - 1
        status = HTTPStatus.OK
        range_header = self.headers.get("Range")
        if range_header:
            if not range_header.startswith("bytes=") or "," in range_header:
                self._send(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE, content_type, b"", head_only)
                return
            first, separator, last = range_header.removeprefix("bytes=").partition("-")
            try:
                if not separator or not first:
                    raise ValueError
                start = int(first)
                end = int(last) if last else size - 1
                if not 0 <= start <= end < size:
                    raise ValueError
            except ValueError:
                self._send(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE, content_type, b"", head_only)
                return
            status = HTTPStatus.PARTIAL_CONTENT
        length = end - start + 1
        body = b""
        if not head_only:
            with path.open("rb") as stream:
                stream.seek(start)
                body = stream.read(length)
        headers = {"Accept-Ranges": "bytes", "Content-Length": str(length)}
        if status == HTTPStatus.PARTIAL_CONTENT:
            headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        self._send(status, content_type, body, head_only, headers)

    def _json(self, status: HTTPStatus, payload: object, head_only: bool = False) -> None:
        self._send(status, "application/json", json.dumps(payload, separators=(",", ":")).encode(), head_only)

    def _send(self, status: HTTPStatus, content_type: str, body: bytes,
              head_only: bool = False, extra_headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        headers = extra_headers or {}
        self.send_header("Content-Length", headers.pop("Content-Length", str(len(body))))
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self'; media-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'")
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

    def log_message(self, format_string: str, *args: object) -> None:
        return

    @staticmethod
    def _page() -> str:
        return """<!doctype html><html><head><meta name=viewport content='width=device-width,initial-scale=1'><title>UE5-Spark Progress</title><style>
body{margin:0;background:#0b0d10;color:#edf2f7;font:16px system-ui}.wrap{max-width:920px;margin:auto;padding:28px}a{color:#77b7ff}.top{display:flex;justify-content:space-between;gap:16px;align-items:center}.card{background:#151920;border:1px solid #29303a;border-radius:14px;padding:18px;margin:14px 0}.tag{padding:4px 9px;border-radius:999px;background:#26303b}.passed{color:#7ee787}.active{color:#f2cc60}.blocked{color:#ff7b72}.media{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px}.media img,.media video{width:100%;border-radius:10px;background:#000}</style></head><body><main class=wrap><div class=top><div><h1 id=title>UE5-Spark</h1><div id=updated></div></div><a id=board>Agent board</a></div><section id=list></section></main><script>
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));fetch('/api/status').then(r=>r.json()).then(s=>{title.textContent=s.title;updated.textContent='Updated '+s.updated;board.href=s.agentBoardUrl;list.innerHTML=s.milestones.map(m=>`<article class=card><div class=top><h2>${esc(m.title)}</h2><span class="tag ${esc(m.status)}">${esc(m.status)}</span></div><p>${esc(m.summary)}</p><div class=media>${m.media.map(x=>{let u='/media/'+x.file.split('/').map(encodeURIComponent).join('/');return /[.](mp4|webm)$/i.test(x.file)?`<div><video controls src="${u}"></video><small>${esc(x.label)}</small></div>`:`<div><img loading=lazy src="${u}" alt="${esc(x.label)}"><small>${esc(x.label)}</small></div>`}).join('')}</div></article>`).join('')}).catch(()=>list.textContent='Progress data is temporarily unavailable.');</script></body></html>"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=8474)
    parser.add_argument("--status", required=True, type=Path)
    parser.add_argument("--media-root", required=True, type=Path)
    parser.add_argument("--agent-board-url", required=True)
    args = parser.parse_args()
    if ipaddress.ip_address(args.host) not in TAILSCALE_NET:
        raise SystemExit("host must be a concrete Tailscale IPv4 address")
    if not 1024 <= args.port <= 65535:
        raise SystemExit("port is outside the unprivileged range")
    media_root = args.media_root.resolve(strict=True)
    if not media_root.is_dir() or media_root.is_symlink():
        raise SystemExit("media root must be a real directory")
    board = urlparse(args.agent_board_url)
    board_is_tailnet = bool(board.hostname and board.hostname.endswith(".ts.net"))
    try:
        board_is_tailnet = board_is_tailnet or ipaddress.ip_address(board.hostname) in TAILSCALE_NET
    except ValueError:
        pass
    if (board.scheme not in {"http", "https"} or not board.hostname or board.username
            or not board_is_tailnet):
        raise SystemExit("agent board URL is invalid")
    load_status(args.status, media_root)
    server = HubServer((args.host, args.port), args.status.resolve(strict=True), media_root, args.agent_board_url)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
