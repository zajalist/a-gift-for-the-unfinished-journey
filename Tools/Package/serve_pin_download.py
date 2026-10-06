"""PIN-gated, resumable download backend for a single Saskarta handoff ZIP.

Bind to loopback and put HTTPS (for example Tailscale Funnel) in front of it.
Set SASKARTA_DOWNLOAD_PIN in the server's private service environment; never
put the PIN in the project or a public URL.
"""

from __future__ import annotations

import argparse
from collections import defaultdict, deque
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import os
from pathlib import Path
import re
import secrets
import threading
import time
from urllib.parse import parse_qs, urlsplit


WINDOW_S = 15 * 60
MAX_FAILURES = 8
MAX_GLOBAL_FAILURES = 40
SESSION_S = 24 * 60 * 60
CHUNK = 1024 * 1024
RANGE = re.compile(r"bytes=(\d+)-(\d*)\Z")


def make_handler(archive: Path, pin: str):
    sessions: dict[str, float] = {}
    failures: dict[str, deque[float]] = defaultdict(deque)
    global_failures: deque[float] = deque()
    lock = threading.Lock()

    class DownloadHandler(BaseHTTPRequestHandler):
        server_version = "SaskartaHandoff/1"

        def _client(self) -> str:
            # Only a local HTTPS reverse proxy can connect to this backend.
            forwarded = self.headers.get("X-Forwarded-For", "")
            return forwarded.split(",", 1)[0].strip() or self.client_address[0]

        def _session(self) -> bool:
            cookie = SimpleCookie()
            try:
                cookie.load(self.headers.get("Cookie", ""))
                token = cookie["saskarta_session"].value
            except (KeyError, ValueError):
                return False
            with lock:
                expires = sessions.get(token, 0)
                if expires <= time.time():
                    sessions.pop(token, None)
                    return False
                return True

        def _headers(self, status: HTTPStatus, content_type: str, length: int) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(length))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "private, no-store")

        def _page(self, status: HTTPStatus, message: str = "") -> None:
            if self._session():
                body = b'<!doctype html><title>Saskarta project</title><h1>Saskarta project</h1><p><a href="/download">Download full Unreal project</a></p>'
            else:
                note = b"<p>Incorrect PIN or too many attempts.</p>" if message else b""
                body = (b'<!doctype html><title>Saskarta project</title><h1>Saskarta project</h1>'
                        + note + b'<form method="post" action="/unlock"><label>PIN <input name="pin" type="password" required autocomplete="off"></label><button>Unlock download</button></form>')
            self._headers(status, "text/html; charset=utf-8", len(body))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _download(self) -> None:
            if not self._session():
                self.send_response(HTTPStatus.SEE_OTHER)
                self.send_header("Location", "/")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            size = archive.stat().st_size
            start, end = 0, size - 1
            requested = self.headers.get("Range")
            if requested:
                match = RANGE.fullmatch(requested)
                if match:
                    start = int(match.group(1))
                    end = int(match.group(2)) if match.group(2) else size - 1
                if not match or start >= size or end < start or end >= size:
                    self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
            length = end - start + 1
            self._headers(HTTPStatus.PARTIAL_CONTENT if requested else HTTPStatus.OK,
                          "application/zip", length)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Disposition", f'attachment; filename="{archive.name}"')
            if requested:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            if self.command == "HEAD":
                return
            try:
                with archive.open("rb") as source:
                    source.seek(start)
                    remaining = length
                    while remaining:
                        block = source.read(min(CHUNK, remaining))
                        if not block:
                            break
                        self.wfile.write(block)
                        remaining -= len(block)
            except (BrokenPipeError, ConnectionResetError):
                pass  # Browser paused or cancelled its download.

        def do_GET(self) -> None:
            path = urlsplit(self.path).path
            if path == "/":
                self._page(HTTPStatus.OK)
            elif path == "/download":
                self._download()
            elif path == "/healthz":
                self._headers(HTTPStatus.OK, "text/plain", 2)
                self.end_headers()
                self.wfile.write(b"ok")
            else:
                self.send_error(HTTPStatus.NOT_FOUND)

        def do_HEAD(self) -> None:
            path = urlsplit(self.path).path
            if path == "/":
                self._page(HTTPStatus.OK)
            elif path == "/download":
                self._download()
            else:
                self.send_error(HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:
            if urlsplit(self.path).path != "/unlock":
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            if not 0 < length <= 1024:
                self.send_error(HTTPStatus.BAD_REQUEST)
                return
            supplied = parse_qs(self.rfile.read(length).decode("utf-8", "replace")).get("pin", [""])[0]
            client = self._client()
            now = time.time()
            with lock:
                attempts = failures[client]
                while attempts and attempts[0] < now - WINDOW_S:
                    attempts.popleft()
                while global_failures and global_failures[0] < now - WINDOW_S:
                    global_failures.popleft()
                if len(attempts) >= MAX_FAILURES or len(global_failures) >= MAX_GLOBAL_FAILURES:
                    limited = True
                    valid = False
                else:
                    limited = False
                    valid = hmac.compare_digest(supplied, pin)
                    if not valid:
                        attempts.append(now)
                        global_failures.append(now)
                    else:
                        attempts.clear()
                        token = secrets.token_urlsafe(32)
                        sessions[token] = now + SESSION_S
            if limited:
                self._page(HTTPStatus.TOO_MANY_REQUESTS, "limited")
            elif not valid:
                self._page(HTTPStatus.UNAUTHORIZED, "incorrect")
            else:
                self.send_response(HTTPStatus.SEE_OTHER)
                self.send_header("Location", "/")
                self.send_header("Set-Cookie", f"saskarta_session={token}; Max-Age={SESSION_S}; Path=/; Secure; HttpOnly; SameSite=Lax")
                self.send_header("Content-Length", "0")
                self.end_headers()

    return DownloadHandler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    pin = os.environ.get("SASKARTA_DOWNLOAD_PIN", "")
    if not pin:
        parser.error("SASKARTA_DOWNLOAD_PIN must be set privately on the server")
    archive = args.archive.resolve(strict=True)
    if not archive.is_file():
        parser.error("archive is not a file")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(archive, pin))
    print(f"Serving {archive.name} on 127.0.0.1:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
