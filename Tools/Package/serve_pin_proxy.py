"""PIN-gated archive download backed by a private loopback HTTP bridge.

The upstream must be an SSH reverse forward to the Windows archive source.
Only this PIN service may be exposed through the public HTTPS proxy.
"""

from __future__ import annotations

import argparse
from http import HTTPStatus
from http.client import HTTPConnection, HTTPException
from http.server import ThreadingHTTPServer
import os
from pathlib import Path

from serve_pin_download import CHUNK, make_handler


def make_proxy_handler(pin: str, archive_name: str, upstream_port: int = 8766):
    if not archive_name.endswith(".zip") or Path(archive_name).name != archive_name:
        raise ValueError("archive name must be a ZIP basename")

    class ProxyHandler(make_handler(Path(archive_name), pin)):
        server_version = "SaskartaHandoffProxy/1"

        def _download(self) -> None:
            if not self._session():
                self.send_response(HTTPStatus.SEE_OTHER)
                self.send_header("Location", "/")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return

            upstream = HTTPConnection("127.0.0.1", upstream_port, timeout=45)
            headers_sent = False
            try:
                headers = {}
                if self.headers.get("Range"):
                    headers["Range"] = self.headers["Range"]
                upstream.request(self.command, "/archive", headers=headers)
                response = upstream.getresponse()
                if response.status not in (200, 206, 416):
                    self.send_error(HTTPStatus.BAD_GATEWAY)
                    return
                length_text = response.getheader("Content-Length", "")
                if not length_text.isdecimal():
                    self.send_error(HTTPStatus.BAD_GATEWAY)
                    return
                self._headers(HTTPStatus(response.status), "application/zip", int(length_text))
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Disposition", f'attachment; filename="{archive_name}"')
                if response.getheader("Content-Range"):
                    self.send_header("Content-Range", response.getheader("Content-Range"))
                self.end_headers()
                headers_sent = True
                if self.command == "HEAD":
                    return
                while block := response.read(CHUNK):
                    self.wfile.write(block)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except (OSError, HTTPException):
                # A partial response must end as a truncated transfer so a client
                # can resume with Range. Never append a second HTTP response.
                if headers_sent:
                    self.close_connection = True
                else:
                    try:
                        self.send_error(HTTPStatus.BAD_GATEWAY)
                    except OSError:
                        pass
            finally:
                upstream.close()

    return ProxyHandler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive_name", help="ZIP basename shown to downloaders")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--upstream-port", type=int, default=8766)
    args = parser.parse_args()
    pin = os.environ.get("SASKARTA_DOWNLOAD_PIN", "")
    if not pin:
        parser.error("SASKARTA_DOWNLOAD_PIN must be set privately on the server")
    server = ThreadingHTTPServer(
        ("127.0.0.1", args.port),
        make_proxy_handler(pin, args.archive_name, args.upstream_port),
    )
    print(f"PIN proxy for {args.archive_name} on 127.0.0.1:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
