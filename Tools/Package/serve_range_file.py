"""Serve one verified archive by byte range on loopback for a private SSH tunnel.

The route has no PIN because it must only be reachable through an SSH remote
forward bound to the remote loopback interface. Never expose this port publicly.
"""

from __future__ import annotations

import argparse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
from urllib.parse import urlsplit


CHUNK = 1024 * 1024
RANGE = re.compile(r"bytes=(\d+)-(\d*)\Z")


def make_range_handler(archive: Path):
    class RangeHandler(BaseHTTPRequestHandler):
        server_version = "SaskartaArchiveBridge/1"

        def _archive(self) -> None:
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
            self.send_response(HTTPStatus.PARTIAL_CONTENT if requested else HTTPStatus.OK)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", str(length))
            self.send_header("Accept-Ranges", "bytes")
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
                pass

        def do_GET(self) -> None:
            if urlsplit(self.path).path == "/archive":
                self._archive()
            else:
                self.send_error(HTTPStatus.NOT_FOUND)

        def do_HEAD(self) -> None:
            self.do_GET()

    return RangeHandler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    archive = args.archive.resolve(strict=True)
    if not archive.is_file():
        parser.error("archive is not a file")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_range_handler(archive))
    print(f"Private archive bridge on 127.0.0.1:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
