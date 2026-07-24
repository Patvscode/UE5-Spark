#!/usr/bin/env python3
"""Relay one short-lived Epic device code to a tailnet-only phone page.

The URL arrives through a private FIFO and is retained only in memory.  This
server intentionally has no access log and never renders the full Epic URL into
an HTML page.  It displays only the validated eight-character device code and
links separately to Epic's fixed activation origin.
"""

from __future__ import annotations

import argparse
import html
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import threading
from urllib.parse import parse_qsl, urlsplit


TOKEN_PATTERN = re.compile(r"[a-f0-9]{48}\Z")
USER_CODE_PATTERN = re.compile(r"[A-Z0-9]{8}\Z")
MAX_URL_BYTES = 8192
LISTING_URL = "https://www.fab.com/listings/1da38c7b-c197-4cc4-a02f-9f63f480e300"


class RelayState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.url: str | None = None
        self.status = "waiting"

    def offer(self, candidate: str) -> None:
        with self.lock:
            if self.status != "waiting":
                return
            self.url = candidate
            self.status = "ready"

    def consume(self) -> str | None:
        with self.lock:
            if self.status != "ready" or self.url is None:
                return None
            result = self.url
            self.url = None
            self.status = "consumed"
            return result

    def read_status(self) -> str:
        with self.lock:
            return self.status

    def read_user_code(self) -> str | None:
        with self.lock:
            if self.status != "ready" or self.url is None:
                return None
            pairs = parse_qsl(
                urlsplit(self.url).query,
                keep_blank_values=True,
                strict_parsing=True,
            )
            if len(pairs) != 1 or pairs[0][0] != "userCode":
                return None
            return pairs[0][1]

    def reject(self) -> None:
        with self.lock:
            if self.status != "waiting":
                return
            self.url = None
            self.status = "rejected"


def validate_activation_url(value: str) -> str:
    encoded = value.encode("utf-8")
    if not encoded or len(encoded) > MAX_URL_BYTES or b"\x00" in encoded:
        raise ValueError("activation URL has an invalid length")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.hostname != "www.epicgames.com"
        or parsed.port not in (None, 443)
        or parsed.path != "/activate"
        or parsed.fragment
        or not parsed.query
    ):
        raise ValueError("activation URL is outside the reviewed Epic origin")
    pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
    if len(pairs) != 1 or pairs[0][0] != "userCode":
        raise ValueError("activation URL contains unexpected query parameters")
    if not USER_CODE_PATTERN.fullmatch(pairs[0][1]):
        raise ValueError("activation URL contains an invalid user code")
    return value


def redacted_url_shape(value: str) -> dict[str, object]:
    """Return URL structure only; never include query values or the full URL."""
    try:
        parsed = urlsplit(value)
        if "=" in parsed.query:
            query_shape = sorted(key for key, _ in parse_qsl(parsed.query, keep_blank_values=True))
        elif parsed.query:
            query_shape = ["bare-user-code"]
        else:
            query_shape = []
        return {
            "scheme": parsed.scheme[:16],
            "host": (parsed.hostname or "")[:255],
            "port": parsed.port,
            "path": parsed.path[:255],
            "queryKeys": query_shape[:32],
            "length": len(value.encode("utf-8", errors="replace")),
        }
    except ValueError:
        return {"parseError": True, "length": len(value.encode("utf-8", errors="replace"))}


def read_fifo(
    fifo: Path,
    state: RelayState,
    stop_event: threading.Event | None = None,
) -> None:
    """Drain every browser-open request so a later writer can never deadlock."""
    while stop_event is None or not stop_event.is_set():
        candidate = ""
        try:
            with fifo.open("r", encoding="utf-8", errors="strict") as stream:
                candidate = stream.readline(MAX_URL_BYTES + 2)
            if not candidate.endswith("\n"):
                raise ValueError("activation URL was incomplete")
            state.offer(validate_activation_url(candidate[:-1]))
        except (OSError, UnicodeError, ValueError) as exc:
            print(
                "rejected activation URL structure: "
                + json.dumps(
                    {"reason": str(exc), **redacted_url_shape(candidate.rstrip("\n"))},
                    sort_keys=True,
                ),
                file=os.sys.stderr,
                flush=True,
            )
            state.reject()


def security_headers(handler: BaseHTTPRequestHandler) -> None:
    handler.send_header("Cache-Control", "no-store, max-age=0")
    handler.send_header("Pragma", "no-cache")
    handler.send_header("Referrer-Policy", "no-referrer")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("X-Frame-Options", "DENY")
    handler.send_header("X-Robots-Tag", "noindex, nofollow")
    handler.send_header(
        "Content-Security-Policy",
        "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; "
        "base-uri 'none'; frame-ancestors 'none'",
    )


def page(title: str, body: str, refresh: bool = False) -> bytes:
    refresh_tag = '<meta http-equiv="refresh" content="2">' if refresh else ""
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
{refresh_tag}<title>{html.escape(title)}</title><style>
body{{font:17px system-ui;background:#101216;color:#f5f5f5;max-width:34rem;margin:12vh auto;padding:1.5rem}}
.card{{background:#1a1e24;border:1px solid #343a44;border-radius:18px;padding:1.5rem}}
button,a.button{{display:block;box-sizing:border-box;width:100%;margin-top:1rem;padding:1rem;border:0;border-radius:12px;background:#48d7b0;color:#07120f;font-weight:700;text-align:center;text-decoration:none;font-size:1rem}}
p{{line-height:1.5;color:#cbd1d8}}</style></head><body><main class="card"><h1>{html.escape(title)}</h1>{body}</main></body></html>"""
    return document.encode("utf-8")


def make_handler(token: str, state: RelayState) -> type[BaseHTTPRequestHandler]:
    landing = f"/{token}"

    class Handler(BaseHTTPRequestHandler):
        server_version = ""
        sys_version = ""

        def log_message(self, _format: str, *_arguments: object) -> None:
            return

        def send_page(self, status: HTTPStatus, payload: bytes) -> None:
            self.send_response(status)
            security_headers(self)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            if getattr(self, "command", None) != "HEAD":
                self.wfile.write(payload)

        def send_error(
            self,
            code: int,
            message: str | None = None,
            explain: str | None = None,
        ) -> None:
            """Return a static, hardened error without reflecting request data."""
            del message, explain
            try:
                status = HTTPStatus(code)
            except ValueError:
                status = HTTPStatus.INTERNAL_SERVER_ERROR
            self.send_page(
                status,
                page(
                    "Request unavailable",
                    "<p>The requested relay route or method is unavailable.</p>",
                ),
            )

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            if self.path == "/healthz":
                payload = b"ok\n"
                self.send_response(HTTPStatus.OK)
                security_headers(self)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            if self.path != landing:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            status = state.read_status()
            if status == "waiting":
                payload = page(
                    "Preparing Epic sign-in",
                    "<p>The DGX Spark is starting Unreal and requesting a one-time Epic authorization link. This page refreshes automatically.</p>",
                    refresh=True,
                )
            elif status == "ready":
                user_code = state.read_user_code()
                if user_code is None:
                    payload = page(
                        "Authorization unavailable",
                        "<p>The Spark could not read the validated Epic device code. Ask Codex to start a fresh session.</p>",
                    )
                else:
                    payload = page(
                        "Epic sign-in is ready",
                        '<p>Open Epic Games, sign in, and enter this device code:</p>'
                        f'<p style="font:700 2rem ui-monospace,monospace;letter-spacing:.18em;text-align:center;color:#fff">{html.escape(user_code)}</p>'
                        '<a class="button" rel="noreferrer" href="https://www.epicgames.com/activate">Open Epic Games Activation</a>'
                        '<p>Keep this page available until the Spark confirms the login. The code expires shortly.</p>',
                    )
            elif status == "consumed":
                payload = page(
                    "Authorization opened",
                    f'<p>Complete Epic sign-in, then add the free character to your Fab library.</p><a class="button" href="{LISTING_URL}">Open Free Casual Girl Sample</a>',
                )
            else:
                payload = page(
                    "Authorization unavailable",
                    "<p>The Spark rejected or lost the one-time activation request. Ask Codex to start a fresh session.</p>",
                )
            self.send_page(HTTPStatus.OK, payload)

        def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            self.send_error(HTTPStatus.METHOD_NOT_ALLOWED)

    return Handler


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fifo", required=True, type=Path)
    parser.add_argument("--token-file", required=True, type=Path)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", default=18790, type=int)
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    if arguments.bind != "127.0.0.1" or not 1024 <= arguments.port <= 65535:
        raise SystemExit("error: relay must use an unprivileged IPv4 loopback socket")
    if arguments.fifo.is_symlink() or arguments.token_file.is_symlink():
        raise SystemExit("error: relay inputs must not be symlinks")
    fifo = arguments.fifo.resolve(strict=True)
    token_file = arguments.token_file.resolve(strict=True)
    if not fifo.is_fifo() or fifo.stat().st_uid != os.getuid():
        raise SystemExit("error: activation FIFO must be owned by the current user")
    if not token_file.is_file() or token_file.stat().st_uid != os.getuid():
        raise SystemExit("error: token file must be one owned regular file")
    token = token_file.read_text(encoding="ascii").strip()
    if not TOKEN_PATTERN.fullmatch(token):
        raise SystemExit("error: relay token is malformed")

    state = RelayState()
    reader = threading.Thread(target=read_fifo, args=(fifo, state), daemon=True)
    reader.start()
    server = ThreadingHTTPServer((arguments.bind, arguments.port), make_handler(token, state))
    server.serve_forever(poll_interval=0.25)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
