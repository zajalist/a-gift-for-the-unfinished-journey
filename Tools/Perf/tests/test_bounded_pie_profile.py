"""Offline controller checks; no editor connection is made."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import struct

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bounded_pie_profile as profile


class BoundedProfileTests(unittest.TestCase):
    def test_flow_accepts_both_native_observation_shapes(self):
        bridge = object.__new__(profile.Bridge)
        for response in ({"matched": True, "observed_value": "Playing"},
                         {"matched": False, "observed_value_last": "Title"}):
            with patch.object(bridge, "call", return_value=response):
                self.assertIn(bridge.flow("pc"), ("Playing", "Title"))
        with patch.object(bridge, "call", return_value={"reason": "pie_ended"}):
            with self.assertRaises(RuntimeError):
                bridge.flow("pc")

    def test_log_tail_ignores_old_faults_and_detects_split_new_fault(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "editor.log"
            path.write_text("GPU timeout from old run\n")
            tail = profile.LogTail(path)
            self.assertEqual(tail.read(), "")
            with path.open("a") as stream:
                stream.write("new GPU time")
            self.assertIsNone(profile.FAULT.search(tail.read()))
            with path.open("a") as stream:
                stream.write("out\n")
            self.assertIsNotNone(profile.FAULT.search(tail.read()))

    def test_log_tail_refuses_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "editor.log"
            path.write_text("same size original\n")
            tail = profile.LogTail(path)
            path.rename(path.with_suffix(".old"))
            path.write_text("same size original\n")
            with self.assertRaises(RuntimeError):
                tail.read()

    def test_rpc_uses_one_deadline_and_preserves_warning(self):
        for warning, delay in ((False, 1.1), (True, 0)):
            body = json.dumps({"ok": True, "data": {}, **({"lease_warning": {"lease_token": "expired"}} if warning else {})}).encode()
            wire = struct.pack(">I", len(body)) + body
            clock = [0.0]
            class FakeSocket:
                def __init__(self):
                    self.offset = 0
                def __enter__(self): return self
                def __exit__(self, *args): pass
                def settimeout(self, seconds): pass
                def sendall(self, data): pass
                def recv(self, size):
                    clock[0] += delay
                    chunk = wire[self.offset:self.offset + 1]
                    self.offset += len(chunk)
                    return chunk
            with patch.object(profile.socket, "create_connection", return_value=FakeSocket()), \
                 patch.object(profile.time, "monotonic", side_effect=lambda: clock[0]):
                with self.assertRaises(RuntimeError if warning else TimeoutError):
                    profile.hayba_deadline("lease_status", {}, "fixture", "fixture-token", 5)

    def test_live_lease_check_rejects_stale_mirror(self):
        mirror = {"holders": {"fixture": {"expires_at": profile.time.time() + 900}}}
        with patch.object(profile.editor_gate, "mirrored_token", return_value="fixture-token"), \
             patch.object(profile.editor_gate, "read_lock", return_value=mirror), \
             patch.object(profile, "hayba_deadline", return_value={"leases": []}):
            with self.assertRaises(RuntimeError):
                profile.Bridge("fixture")

    def test_bridge_paces_rpcs_and_rejects_truncation(self):
        bridge = object.__new__(profile.Bridge)
        bridge.owner, bridge.token, bridge._next_rpc_at = 'fixture', None, 0.
        clock, calls = [0.], []
        def respond(*args):
            calls.append(clock[0])
            return {'_truncated': True} if len(calls) == 3 else {}
        with patch.object(profile.time, 'monotonic', side_effect=lambda: clock[0]), \
             patch.object(profile.time, 'sleep', side_effect=lambda delay: clock.__setitem__(0, clock[0] + delay)), \
             patch.object(profile, 'hayba_deadline', side_effect=respond):
            bridge.call('one'); bridge.call('two')
            with self.assertRaisesRegex(RuntimeError, 'Truncated'):
                bridge.call('three')
        self.assertEqual(calls, [0., .6, 1.2])

    def test_six_second_start_response_requires_explicit_longer_deadline(self):
        # Exercise the real Bridge + socket deadline code, not a successful
        # whole-capture fixture. A6s native reply must fail the ordinary5s cap.
        body = json.dumps({'ok': True, 'data': {'pie_requested': True}}).encode()
        wire = struct.pack('>I', len(body)) + body
        for command, options, succeeds in (
                ('editor_start_pie', {}, False),
                ('editor_start_pie', {'timeout': 15}, True),
                ('editor_get_performance_stats', {}, False)):
            with self.subTest(command=command, options=options):
                clock = [0.]
                class DelayedSocket:
                    def __init__(self):
                        self.offset, self.timeout, self.waiting = 0, None, True
                    def __enter__(self): return self
                    def __exit__(self, *args): pass
                    def settimeout(self, seconds): self.timeout = seconds
                    def sendall(self, payload): pass
                    def recv(self, size):
                        if self.waiting:
                            self.waiting = False
                            clock[0] += min(6., self.timeout)
                            if self.timeout < 6.:
                                raise TimeoutError('native response exceeds socket deadline')
                        chunk = wire[self.offset:self.offset + size]
                        self.offset += len(chunk)
                        return chunk
                bridge = object.__new__(profile.Bridge)
                bridge.owner, bridge.token, bridge._next_rpc_at = 'fixture', None, 0.
                with patch.object(profile.socket, 'create_connection', return_value=DelayedSocket()), \
                     patch.object(profile.time, 'monotonic', side_effect=lambda: clock[0]):
                    if succeeds:
                        self.assertEqual(bridge.call(command, **options), {'pie_requested': True})
                        self.assertEqual(clock[0], 6.)
                    else:
                        with self.assertRaises(TimeoutError):
                            bridge.call(command, **options)
                        self.assertEqual(clock[0], 5.)

    def test_csv_preflight_rejects_pending_or_active_and_allows_completed(self):
        for event in ('Capture Starting', 'Capture started. CSV ID: AABBCCDD'):
            with self.assertRaisesRegex(RuntimeError, 'existing/pending'):
                profile.require_idle_csv('LogCsvProfiler: ' + event + '\n')
        self.assertTrue(profile.require_idle_csv('LogCsvProfiler: Capture started. CSV ID: AABBCCDD\n'
            'LogCsvProfiler: Capture Ended. Writing CSV to file\n')['last_start_precedes_end'])

    def test_csv_writer_lock_is_retried_then_same_guid_is_summarized(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'capture.csv'
            path.write_text('EVENTS,FrameTime\n,16.67\n[HasHeaderRowAtEnd],1,[csvid],AABBCCDD\n')
            real_open, attempts = Path.open, [0]
            def flaky(candidate, *args, **kwargs):
                if candidate == path:
                    attempts[0] += 1
                    if attempts[0] <= 2:
                        raise PermissionError('native writer still owns file')
                return real_open(candidate, *args, **kwargs)
            report = {'csv_id': 'AABBCCDD', 'cleanup': []}
            with patch.object(profile, 'CSV_DIR', Path(directory)), patch.object(Path, 'open', new=flaky), \
                 patch.object(profile.time, 'sleep'):
                result = profile.completed_csv(report, {})
            self.assertEqual(result[0]['summary']['frames'], 1)
            self.assertEqual(report['csv_finalization']['writer_lock_retries'], 2)
            self.assertEqual(report['csv_finalization']['status'], 'complete')
            self.assertEqual(report['cleanup'], [])

    def test_csv_persistent_permission_failure_is_explicit_after_deadline(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'capture.csv'; path.write_text('locked')
            report = {'csv_id': 'AABBCCDD', 'cleanup': []}
            with patch.object(profile, 'CSV_DIR', Path(directory)), \
                 patch.object(Path, 'open', side_effect=PermissionError('denied')), \
                 patch.object(profile.time, 'sleep') as sleep:
                self.assertEqual(profile.completed_csv(report, {}), [])
            self.assertEqual(sleep.call_count, 20)
            self.assertEqual(report['csv_finalization']['status'], 'deadline_writer_locked')
            self.assertIn('inaccessible', report['cleanup'][0]['error'])

    def test_rpc_owner_only_envelope_and_warning_detail(self):
        for token, warning in ((None, None), ("actual-token", None),
                               (None, {"lease_token": "unknown or expired", "caller_owner": "fixture"})):
            response = {"ok": True, "data": {"caller_owner": "fixture"}}
            if warning:
                response["lease_warning"] = warning
            body = json.dumps(response).encode()
            wire = struct.pack(">I", len(body)) + body
            sent = []
            class FakeSocket:
                def __init__(self): self.offset = 0
                def __enter__(self): return self
                def __exit__(self, *args): pass
                def settimeout(self, seconds): pass
                def sendall(self, payload): sent.append(json.loads(payload[4:]))
                def recv(self, size):
                    chunk = wire[self.offset:self.offset + size]
                    self.offset += len(chunk)
                    return chunk
            with patch.object(profile.socket, "create_connection", return_value=FakeSocket()):
                if warning:
                    with self.assertRaisesRegex(RuntimeError, "unknown or expired"):
                        profile.hayba_deadline("lease_status", {}, "fixture", token, 5)
                else:
                    self.assertEqual(profile.hayba_deadline("lease_status", {}, "fixture", token, 5),
                                     {"caller_owner": "fixture"})
            self.assertEqual(sent[0]["owner"], "fixture")
            self.assertEqual(sent[0].get("lease"), token)
            self.assertEqual("lease" in sent[0], bool(token))

    def exercise(self, phase, fault=None, timeouts=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            csv_dir = root / "csv"
            csv_dir.mkdir()
            log = root / "editor.log"
            log.write_text("")
            calls = []
            clock = [0.0]
            class FakeBridge:
                def __init__(self, owner):
                    self.play = phase == "driving"
                    self.requested = False
                    self.pending = phase == "startup"
                def call(self, command, params=None, timeout=5):
                    calls.append((command, params))
                    if timeouts is not None:
                        timeouts.append((command, timeout))
                    if command == "editor_get_state":
                        pending = self.requested and self.pending
                        if pending:
                            self.pending = False
                        return {"pie_running": self.play and not pending, "map": "/Game/level/Saskarta_WP"}
                    if command == "editor_start_pie":
                        self.play = self.requested = True
                    if command == "editor_get_performance_stats":
                        if fault == "timeout":
                            raise TimeoutError("native RPC timeout")
                        return {"frame_ms": 300 if fault == "slow" else 16.67}
                    if command == "editor_pie_press_key":
                        return {"handled_by_ui": fault == "ui", "dispatched": True}
                    return {}
                def console(self, command, timeout=5):
                    calls.append((command, None))
                    if command == "CsvProfile START":
                        if fault == 'start_unknown':
                            raise TimeoutError('START response ambiguous without GUID')
                        if fault == 'start_refused':
                            with log.open('a') as stream:
                                stream.write('LogCsvProfiler: capture was already running\n')
                            return {}
                        with log.open("a") as stream:
                            stream.write("LogCsvProfiler: Capture started. CSV ID: AABBCCDD\n")
                            if fault == 'start_conflicting':
                                stream.write('LogCsvProfiler: Capture started. CSV ID: BBAADDCC\n')
                        if fault == 'start_timeout_owned':
                            raise TimeoutError('START timed out after native capture queued')
                    if command == "CsvProfile START" and fault == "gpu":
                        with log.open("a") as stream:
                            stream.write("LogD3D12RHI: GPU timeout")
                    if command == "CsvProfile STOP":
                        (csv_dir / "capture.csv").write_text("EVENTS,FrameTime,GPUTime\n,16.67,8\n[HasHeaderRowAtEnd],1,[csvid],AABBCCDD\n")
                    return {}
                def actor(self, class_filter):
                    return {"path": "actor", "location": {"x": clock[0] * 100, "y": 0, "z": 0}}
                def flow(self, path):
                    return "Title" if phase == "startup" else "Playing"
            args = SimpleNamespace(phase=phase, start_pie=phase == "startup", hold_w=phase == "driving",
                                   owner="fixture", editor_pid=1, seconds=2, label="cold")
            with patch.multiple(profile, ROOT=root, CSV_DIR=csv_dir, LOG=log, Bridge=FakeBridge), \
                 patch.object(profile, "host_sample", return_value={"available_ram_fraction": .5, "editor_foreground": True}), \
                 patch.object(profile.time, "monotonic", side_effect=lambda: clock[0]), \
                 patch.object(profile.time, "sleep", side_effect=lambda seconds: clock.__setitem__(0, clock[0] + seconds)), \
                 contextlib.redirect_stdout(io.StringIO()):
                code = profile.capture(args)
            reports = list(root.glob("Saved/Verification/bounded_pie/*/report.json"))
            self.assertEqual(len(reports), 1)
            return code, json.loads(reports[0].read_text()), calls

    def test_startup_waits_for_queued_pie_and_leaves_title_running(self):
        code, report, calls = self.exercise("startup")
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "complete")
        self.assertEqual(report["acceptance"], "not_evaluated")
        self.assertNotIn("editor_stop_pie", [call[0] for call in calls])

    def test_capture_extends_only_start_pie_request_deadline(self):
        timeouts = []
        self.exercise('startup', timeouts=timeouts)
        self.assertEqual([seconds for command, seconds in timeouts if command == 'editor_start_pie'], [15])
        self.assertTrue(any(command == 'editor_get_performance_stats' for command, _ in timeouts))
        self.assertTrue(all(seconds == 5 for command, seconds in timeouts if command != 'editor_start_pie'))

    def test_driving_releases_input_and_requests_stop(self):
        code, report, calls = self.exercise("driving")
        self.assertEqual(code, 0)
        self.assertEqual(report["csv"][0]["summary"]["frames"], 1)
        self.assertIn(("editor_pie_press_key", {"key": "W", "event": "released"}), calls)
        self.assertIn("editor_stop_pie", [call[0] for call in calls])

    def test_faults_abort_and_preserve_cleanup(self):
        for fault in ("gpu", "timeout", "slow", "ui"):
            with self.subTest(fault=fault):
                code, report, calls = self.exercise("driving", fault)
                self.assertEqual(code, 2)
                self.assertEqual(report["status"], "aborted")
                self.assertEqual(report["acceptance"], "unverified")
                pressed = ("editor_pie_press_key", {"key": "W", "event": "pressed"}) in calls
                released = ("editor_pie_press_key", {"key": "W", "event": "released"}) in calls
                self.assertEqual(released, pressed)
                self.assertIn("CsvProfile STOP", [call[0] for call in calls])
                self.assertIn("editor_stop_pie", [call[0] for call in calls])

    def test_unowned_capture_never_starts_pie_moves_or_stops_existing_recorder(self):
        for fault in ('start_unknown', 'start_refused', 'start_conflicting'):
            with self.subTest(fault=fault):
                code, report, calls = self.exercise('startup', fault)
                self.assertEqual(code, 2)
                commands = [row[0] for row in calls]
                for command in ('editor_start_pie', 'editor_stop_pie', 'editor_pie_press_key', 'CsvProfile STOP'):
                    self.assertNotIn(command, commands)
                self.assertNotEqual(report['csv_ownership'], 'confirmed_new_guid')

    def test_ambiguous_start_resolves_fresh_guid_before_cleanup_but_never_starts_pie(self):
        code, report, calls = self.exercise('startup', 'start_timeout_owned')
        self.assertEqual(code, 2)
        self.assertEqual(report['csv_ownership'], 'confirmed_new_guid')
        commands = [row[0] for row in calls]
        self.assertIn('CsvProfile STOP', commands)
        self.assertNotIn('editor_start_pie', commands)
        self.assertNotIn('editor_stop_pie', commands)


if __name__ == "__main__":
    unittest.main()
