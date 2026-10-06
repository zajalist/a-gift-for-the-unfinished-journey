"""Checks PIN gate and resumable byte ranges without exposing a network port."""

from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from threading import Thread
import unittest

from Tools.Package.serve_pin_download import make_handler


class PinDownloadTest(unittest.TestCase):
    def test_gate_and_byte_range(self):
        with TemporaryDirectory() as temp:
            archive = Path(temp) / "project.zip"
            archive.write_bytes(b"0123456789")
            server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(archive, "test-pin"))
            worker = Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                client = HTTPConnection("127.0.0.1", server.server_port)
                client.request("GET", "/download")
                response = client.getresponse()
                self.assertEqual(response.status, 303)
                response.read()

                client.request("POST", "/unlock", "pin=wrong", {"Content-Type": "application/x-www-form-urlencoded"})
                response = client.getresponse()
                self.assertEqual(response.status, 401)
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
                self.assertEqual(response.read(), b"3456")

                client.request("HEAD", "/download", headers={"Cookie": cookie})
                response = client.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(response.getheader("Content-Length"), "10")
                response.read()

                client.request("GET", "/download", headers={"Cookie": cookie, "Range": "bytes=10-20"})
                response = client.getresponse()
                self.assertEqual(response.status, 416)
                response.read()

                headers = {"Content-Type": "application/x-www-form-urlencoded", "X-Forwarded-For": "203.0.113.1"}
                for _ in range(8):
                    client.request("POST", "/unlock", "pin=wrong", headers)
                    response = client.getresponse()
                    self.assertEqual(response.status, 401)
                    response.read()
                client.request("POST", "/unlock", "pin=test-pin", headers)
                response = client.getresponse()
                self.assertEqual(response.status, 429)
                response.read()
                client.close()
            finally:
                server.shutdown()
                server.server_close()
                worker.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
