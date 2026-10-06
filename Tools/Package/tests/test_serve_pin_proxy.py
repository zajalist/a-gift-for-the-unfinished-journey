"""Checks the private archive bridge behind the existing PIN gate."""

from http.client import HTTPConnection, IncompleteRead
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import socket
import sys
from tempfile import TemporaryDirectory
from threading import Thread
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from serve_pin_proxy import make_proxy_handler  # noqa: E402
from serve_range_file import make_range_handler  # noqa: E402


class ProxyDownloadTest(unittest.TestCase):
    def test_gate_range_and_head(self):
        with TemporaryDirectory() as temp:
            archive = Path(temp) / "project.zip"
            archive.write_bytes(b"0123456789")
            raw = ThreadingHTTPServer(("127.0.0.1", 0), make_range_handler(archive))
            proxy = ThreadingHTTPServer(
                ("127.0.0.1", 0),
                make_proxy_handler("test-pin", archive.name, raw.server_port),
            )
            workers = [Thread(target=s.serve_forever, daemon=True) for s in (raw, proxy)]
            for worker in workers:
                worker.start()
            try:
                client = HTTPConnection("127.0.0.1", proxy.server_port)
                client.request("GET", "/download")
                response = client.getresponse()
                self.assertEqual(response.status, 303)
                self.assertEqual(response.getheader("Location"), "/")
                response.read()

                client.request("POST", "/unlock", "pin=test-pin", {"Content-Type": "application/x-www-form-urlencoded"})
                response = client.getresponse()
                self.assertEqual(response.status, 303)
                cookie = re.search(r"saskarta_session=[^;]+", response.getheader("Set-Cookie"))[0]
                response.read()

                client.request("GET", "/download", headers={"Cookie": cookie, "Range": "bytes=3-6"})
                response = client.getresponse()
                self.assertEqual(response.status, 206)
                self.assertEqual(response.getheader("Content-Range"), "bytes 3-6/10")
                self.assertEqual(response.getheader("Content-Length"), "4")
                self.assertEqual(response.read(), b"3456")

                client.request("HEAD", "/download", headers={"Cookie": cookie})
                response = client.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(response.getheader("Content-Length"), "10")
                response.read()

                client.request("GET", "/download", headers={"Cookie": cookie, "Range": "bytes=10-20"})
                response = client.getresponse()
                self.assertEqual(response.status, 416)
                self.assertEqual(response.getheader("Content-Range"), "bytes */10")
                response.read()
                client.close()
            finally:
                for server in (proxy, raw):
                    server.shutdown()
                    server.server_close()
                for worker in workers:
                    worker.join(timeout=2)

    def test_upstream_failure_is_gateway_error(self):
        with socket.socket() as unused:
            unused.bind(("127.0.0.1", 0))
            closed_port = unused.getsockname()[1]
        proxy = ThreadingHTTPServer(
            ("127.0.0.1", 0), make_proxy_handler("test-pin", "project.zip", closed_port)
        )
        worker = Thread(target=proxy.serve_forever, daemon=True)
        worker.start()
        try:
            client = HTTPConnection("127.0.0.1", proxy.server_port)
            client.request("POST", "/unlock", "pin=test-pin", {"Content-Type": "application/x-www-form-urlencoded"})
            response = client.getresponse()
            cookie = re.search(r"saskarta_session=[^;]+", response.getheader("Set-Cookie"))[0]
            response.read()
            client.request("GET", "/download", headers={"Cookie": cookie})
            response = client.getresponse()
            self.assertEqual(response.status, 502)
            response.read()
            client.close()
        finally:
            proxy.shutdown()
            proxy.server_close()
            worker.join(timeout=2)

    def test_truncated_upstream_does_not_append_second_response(self):
        class TruncatedHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", "10")
                self.end_headers()
                self.wfile.write(b"012")

        upstream = ThreadingHTTPServer(("127.0.0.1", 0), TruncatedHandler)
        proxy = ThreadingHTTPServer(
            ("127.0.0.1", 0), make_proxy_handler("test-pin", "project.zip", upstream.server_port)
        )
        workers = [Thread(target=s.serve_forever, daemon=True) for s in (upstream, proxy)]
        for worker in workers:
            worker.start()
        try:
            client = HTTPConnection("127.0.0.1", proxy.server_port)
            client.request("POST", "/unlock", "pin=test-pin", {"Content-Type": "application/x-www-form-urlencoded"})
            response = client.getresponse()
            cookie = re.search(r"saskarta_session=[^;]+", response.getheader("Set-Cookie"))[0]
            response.read()
            client.request("GET", "/download", headers={"Cookie": cookie})
            response = client.getresponse()
            self.assertEqual(response.status, 200)
            with self.assertRaises(IncompleteRead) as error:
                response.read()
            self.assertEqual(error.exception.partial, b"012")
            client.close()
        finally:
            for server in (proxy, upstream):
                server.shutdown()
                server.server_close()
            for worker in workers:
                worker.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
