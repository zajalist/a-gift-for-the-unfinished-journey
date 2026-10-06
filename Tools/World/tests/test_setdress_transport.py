"""Capture/export must survive the editor closing the previous command's socket."""
import json
import pathlib
import socketserver
import struct
import sys
import threading
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import place_setdress as ps


def test_commands_survive_server_disconnect_after_idle(tmp_path, monkeypatch):
    received = []

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            n = struct.unpack('>I', self.rfile.read(4))[0]
            req = json.loads(self.rfile.read(n))
            received.append(req['params']['script'])
            reply = json.dumps({'id': req['id'], 'ok': True,
                                'data': {'stdout': 'DONE'}}).encode()
            self.wfile.write(struct.pack('>I', len(reply)) + reply)
            # Returning closes this connection, like Hayba's idle deadline.

    monkeypatch.setattr(ps, 'SCRIPT_DIR', str(tmp_path))
    monkeypatch.setattr(ps, 'pie_running', lambda: False)
    ticks = iter([0.0, 6.0, 6.0])
    monkeypatch.setattr(ps.time, 'monotonic', lambda: next(ticks))
    with socketserver.TCPServer(('127.0.0.1', 0), Handler) as server:
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            runner = ps.Runner(SimpleNamespace(dry_run=False, port=server.server_address[1]))
            assert runner.send('capture', "print('capture')") == 'DONE'
            assert runner.send('export', "print('export')") == 'DONE'
        finally:
            server.shutdown()
            worker.join()
    assert received == ["print('capture')", "print('export')"]
