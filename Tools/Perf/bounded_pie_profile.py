"""Bounded PIE CSV captures through existing typed Hayba commands; default is offline.

See docs/performance/2026-09-30-bounded-pie-runbook.md before `capture`.
This helper never changes quality, teleports, loads cells, launches an editor,
or acquires a lease. The root operator owns the live editor and normal menus.
"""
from __future__ import annotations

import argparse
import csv
import ctypes
import json
import math
import os
from pathlib import Path
import re
import socket
import struct
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Tools/GameFlow"))
import editor_gate

CSV_DIR = ROOT / "Saved/Profiling/CSV"
LOG = ROOT / "Saved/Logs/saskartarad.log"
FAULT = re.compile(r"GPU timeout|GPU crash|DXGI_ERROR_DEVICE_(?:HUNG|REMOVED)|Fatal error:", re.I)
CSV_START = re.compile(r"Capture started\. CSV ID: ([0-9A-Fa-f-]+)")
START_REFUSED = re.compile(r"capture was already running|already a pending start command", re.I)
PLAN = """1. Keep 1080p High, screen percentage 66.7, cap 60, VT 2/1, AsyncCompute 0.
2. Root holds a global editor lease, confirms no other CSV capture, focuses PIE.
3. capture --phase startup --label cold --start-pie: observe normal cards/loading
   until Title (or Playing), maximum 90s. Successful startup leaves PIE running.
4. Root uses the normal Play action and waits for control; no debug skip/teleport.
5. capture --phase driving --label cold --hold-w: up to 90s normal W input;
   release input, stop CSV, request normal PIE shutdown on completion or failure.
6. Repeat 3-5 as label warm in the same editor process without editing assets.
7. Compare startup and driving CSVs separately; no driving frame may exceed 50ms.
The warm/cold labels are operator annotations, not cache-state measurements.
"""


def summarize(path):
    columns = {name: [] for name in ("FrameTime", "GameThreadTime", "RenderThreadTime", "GPUTime")}
    with Path(path).open(newline="", encoding="utf-8-sig") as stream:
        for row in csv.DictReader(stream):
            if row.get("EVENTS") == "EVENTS" or (row.get("EVENTS") or "").startswith("[HasHeaderRowAtEnd]"):
                break
            try:
                frame = float(row.get("FrameTime", ""))
            except (TypeError, ValueError):
                continue
            if not math.isfinite(frame):
                continue
            for name, values in columns.items():
                try:
                    value = float(row.get(name, ""))
                    if math.isfinite(value):
                        values.append(value)
                except (TypeError, ValueError):
                    pass
    if not columns["FrameTime"]:
        raise ValueError("CSV has no numeric FrameTime rows")
    result = {"frames": len(columns["FrameTime"]), "hitches_over_50_ms": sum(x > 50 for x in columns["FrameTime"])}
    for name, values in columns.items():
        if values:
            values.sort()
            result[name] = {"p50_ms": values[math.ceil(len(values) * .5) - 1],
                            "p95_ms": values[math.ceil(len(values) * .95) - 1], "max_ms": values[-1]}
    return result


def host_sample(editor_pid):
    if os.name != "nt":
        raise RuntimeError("live host safeguards require Windows")
    class MemoryStatus(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
            (name, ctypes.c_ulonglong) for name in
            ("total", "available", "total_page", "available_page", "total_virtual", "available_virtual", "extended")]
    memory = MemoryStatus()
    memory.length = ctypes.sizeof(memory)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
        raise OSError("GlobalMemoryStatusEx failed")
    user32 = ctypes.windll.user32
    user32.GetForegroundWindow.restype = ctypes.c_void_p
    user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    foreground_pid = ctypes.c_ulong()
    user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), ctypes.byref(foreground_pid))
    return {"available_ram_fraction": memory.available / memory.total,
            "editor_foreground": foreground_pid.value == editor_pid}


class LogTail:
    """Only new log bytes; retain a partial line so split fault text is caught."""
    def __init__(self, path):
        self.path = path
        stat = path.stat()  # this safeguard requires a real log before mutation
        self.identity = (stat.st_dev, stat.st_ino)
        self.offset = stat.st_size
        with path.open("rb") as stream:
            stream.seek(max(0, self.offset - 4096))
            self.carry = stream.read().rsplit(b"\n", 1)[-1]

    def read(self):
        stat = self.path.stat()
        if (stat.st_dev, stat.st_ino) != self.identity or stat.st_size < self.offset:
            raise RuntimeError("editor log was replaced or truncated during capture")
        with self.path.open("rb") as stream:
            stream.seek(self.offset)
            recent = stream.read()
            self.offset = stream.tell()
        if not recent:
            return ""
        combined = self.carry + recent
        self.carry = combined.rsplit(b"\n", 1)[-1][-4096:]
        return combined.decode("utf-8", errors="replace")


def hayba_deadline(command, params, owner, lease, timeout):
    """Same editor_gate wire contract, with one deadline across all socket I/O."""
    deadline = time.monotonic() + timeout
    def remaining():
        value = deadline - time.monotonic()
        if value <= 0:
            raise TimeoutError(f"native {command} exceeded {timeout}s RPC deadline")
        return value
    envelope = {"cmd": command, "id": f"bounded_pie_{os.getpid()}_{time.monotonic_ns()}",
                "params": params, "owner": owner}
    if lease:
        envelope["lease"] = lease
    if os.environ.get("HAYBA_AUTH"):
        envelope["auth"] = os.environ["HAYBA_AUTH"]
    payload = json.dumps(envelope).encode("utf-8")
    with socket.create_connection(("127.0.0.1", editor_gate.PORT), timeout=remaining()) as connection:
        connection.settimeout(remaining())
        connection.sendall(struct.pack(">I", len(payload)) + payload)
        def receive(size):
            chunks = bytearray()
            while len(chunks) < size:
                connection.settimeout(remaining())
                chunk = connection.recv(size - len(chunks))
                if not chunk:
                    raise ConnectionError("Hayba closed the connection")
                chunks.extend(chunk)
            remaining()
            return bytes(chunks)
        size = struct.unpack(">I", receive(4))[0]
        if size > 4 * 1024 * 1024:
            raise RuntimeError("unexpectedly large native response for bounded profiling")
        response = json.loads(receive(size))
    if not response.get("ok"):
        raise editor_gate.HaybaError(response.get("error") or "Hayba refused the request")
    if response.get("lease_warning"):
        raise RuntimeError("native lease warning: " + json.dumps(response["lease_warning"], sort_keys=True))
    return response.get("data") or {}


class Bridge:
    def __init__(self, owner):
        self._next_rpc_at = 0.0
        self.owner = owner
        mirrored = editor_gate.mirrored_token(owner)
        # Native final-envelope redaction hides even our own status/grant token.
        # The documented owner-only path is valid only after checking our live
        # claim below. Never forward the literal redaction marker as a token.
        self.token = None if mirrored == "[REDACTED:token]" else mirrored
        lock = editor_gate.read_lock() or {}
        held = lock.get("holders", {}).get(owner, {})
        if not mirrored or not held.get("expires_at", 0) >= time.time() + 150:
            raise RuntimeError("root must renew its editor lease first (at least 150s remaining)")
        status = self.call("lease_status")
        matching = [item for item in status.get("leases", [])
                    if item.get("owner") == owner and item.get("mine") is True]
        if status.get("caller_owner") != owner or len(matching) != 1 or not matching[0].get("expires_in_s", 0) >= 150 or not any(
                claim.get("resource") == "global" and claim.get("mode") == "exclusive"
                for claim in matching[0].get("resources", [])):
            raise RuntimeError("root mirror is not a live exclusive global lease with at least 150s remaining")
        live_token = matching[0].get("token")
        if self.token and live_token != "[REDACTED:token]" and live_token != self.token:
            raise RuntimeError("root mirror token does not match its live lease")

    def call(self, command, params=None, timeout=5):
        # Closed native clients remain counted for5s; keep below the16-client cap.
        # Separate state preserves compatibility with the observation wrapper.
        delay = self._next_rpc_at - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        self._next_rpc_at = time.monotonic() + .6
        result = hayba_deadline(command, params or {}, self.owner, self.token, timeout)
        if result.get('_truncated') or result.get('truncated'):
            raise RuntimeError('Truncated observation: ' + command)
        return result

    def console(self, command, timeout=5):
        return self.call("editor_run_console_command", {"command": command}, timeout)

    def actor(self, class_filter):
        result = self.call("editor_pie_actor_list", {"class_filter": class_filter, "limit": 2})
        actors = result.get("actors", [])
        if len(result.get("available_worlds", [])) != 1 or len(actors) > 1:
            raise RuntimeError("capture requires one PIE world and one matching actor")
        return actors[0] if actors else None

    def flow(self, path):
        result = self.call("editor_pie_assert", {"actor_path": path, "property_name": "FlowState",
                                                 "expected_value": "Playing", "timeout_ms": 0})
        if "observed_value" not in result and "observed_value_last" not in result:
            raise RuntimeError(f"FlowState query had no observation: {result.get('reason', 'unknown')}")
        return result.get("observed_value", result.get("observed_value_last"))


def require_idle_csv(log_text):
    starts = list(re.finditer(r'LogCsvProfiler:.*Capture (?:Starting|started\. CSV ID:)', log_text))
    ends = list(re.finditer(r'LogCsvProfiler:.*Capture Ended\. Writing CSV to file', log_text))
    if starts and (not ends or starts[-1].start() > ends[-1].start()):
        raise RuntimeError('Log evidence shows an existing/pending CSV capture; finish it before this trial')
    return {'start_events': len(starts), 'end_events': len(ends), 'last_start_precedes_end': True}


def observe_csv(report, recent):
    if START_REFUSED.search(recent):
        report['csv_ownership'] = 'refused_existing_capture'
        raise RuntimeError('CSV START refused because an existing/pending capture owns the recorder')
    for identity in CSV_START.findall(recent):
        if report.get('csv_id') not in (None, identity):
            report['csv_ownership'] = 'conflicting_new_capture'
            raise RuntimeError('Another CSV capture started')
        report['csv_id'] = identity
        report['csv_ownership'] = 'confirmed_new_guid'


def completed_csv(report, before):
    """Wait10s for this GUID's stable footer; a writer lock is retried, never hidden."""
    previous, locked = {}, {}
    diagnostics = {'attempts': 0, 'writer_lock_retries': 0, 'status': 'waiting'}
    report['csv_finalization'] = diagnostics
    for attempt in range(20):
        diagnostics['attempts'] = attempt + 1
        for path in CSV_DIR.glob('*.csv'):
            try:
                stat = path.stat()
                signature = (stat.st_size, stat.st_mtime_ns)
                if before.get(path) == signature:
                    continue
                with path.open('rb') as stream:
                    stream.seek(max(0, signature[0] - 65536))
                    footer = stream.read().lower()
                capture_id = ('[csvid],' + report.get('csv_id', 'missing')).lower().encode()
                complete = b'[hasheaderrowatend]' in footer and capture_id in footer
                if complete and previous.get(path) == signature:
                    summary = summarize(path)  # This second open can also race the writer.
                    locked.pop(str(path), None)
                    diagnostics['status'] = 'complete'
                    return [{'path': str(path), 'summary': summary}]
                previous[path] = signature
                locked.pop(str(path), None)
            except PermissionError as error:
                diagnostics['writer_lock_retries'] += 1
                locked[str(path)] = str(error)
        time.sleep(.5)
    diagnostics['status'] = 'deadline_writer_locked' if locked else 'deadline_incomplete'
    if locked:
        diagnostics['locked_files'] = locked
        report.setdefault('cleanup', []).append({'action': 'finalize owned CSV',
            'error': 'CSV remained inaccessible after10s; permission/writer lock requires inspection',
            'files': locked})
    return []


def capture(args):
    if args.start_pie != (args.phase == "startup"):
        raise ValueError("startup requires --start-pie; driving requires an existing Playing session")
    if args.hold_w and args.phase != "driving":
        raise ValueError("--hold-w is only valid for driving")
    bridge = Bridge(args.owner)
    state = bridge.call("editor_get_state")
    if bool(state["pie_running"]) == args.start_pie:
        raise RuntimeError("startup needs idle editor; driving needs active PIE")
    if "/Game/level/Saskarta_WP" not in state.get("map", ""):
        raise RuntimeError("open Saskarta_WP before capture")
    host = host_sample(args.editor_pid)  # fail before any mutation if safeguards unavailable
    if host['available_ram_fraction'] < .15:
        raise RuntimeError('Available RAM is below15%')
    csv_preflight = require_idle_csv(LOG.read_text(encoding='utf-8', errors='replace'))
    pc = None if args.start_pie else bridge.actor("PC_Saskarta_C")
    if not args.start_pie and (not pc or bridge.flow(pc["path"]) != "Playing"):
        raise RuntimeError("driving capture requires FlowState=Playing")
    before = {p: (p.stat().st_size, p.stat().st_mtime_ns) for p in CSV_DIR.glob("*.csv")}
    stamp = time.strftime("%Y%m%d_%H%M%S")
    out = ROOT / "Saved/Verification/bounded_pie" / f"{stamp}_{args.label}_{args.phase}"
    out.mkdir(parents=True, exist_ok=False)
    report = {"label": args.label, "phase": args.phase, "limit_s": args.seconds, "input": "W" if args.hold_w else "operator",
              "status": "running", "samples": [], "cleanup": [], "csv": [],
              "csv_preflight": csv_preflight, "csv_ownership": "not_requested"}
    log_tail = LogTail(LOG)
    low_since = None
    slow_samples = 0
    csv_requested = False
    w_requested = False
    pie_owned = not args.start_pie
    started = time.monotonic()
    try:
        bridge.console("t.MaxFPS")  # query only; exact output is retained in Unreal's log
        if not args.start_pie:
            report["carrier_start"] = bridge.actor("BP_Saskarta_Carrier_C")
        csv_requested = True
        report['csv_ownership'] = 'requested_unconfirmed'
        bridge.console("CsvProfile START")
        # Establish recorder ownership before starting PIE or issuing movement.
        until = time.monotonic() + 5
        while not report.get('csv_id') and time.monotonic() < until:
            recent = log_tail.read()
            observe_csv(report, recent)
            if FAULT.search(recent):
                raise RuntimeError('New native/GPU fault before capture start')
            if not report.get('csv_id'):
                time.sleep(.25)
        if not report.get('csv_id'):
            raise RuntimeError('CSV start was not confirmed before PIE/input')
        if args.start_pie:
            pie_owned = True
            # Initial PIE creation can block on mandatory world-partition loads
            # (measured ~6s). Only this request gets a longer bounded deadline;
            # performance/state sampling retains the ordinary5s stall guard.
            bridge.call("editor_start_pie", timeout=15)
        if args.hold_w:
            w_requested = True
            sent = bridge.call("editor_pie_press_key", {"key": "W", "event": "pressed"})
            if sent.get("handled_by_ui"):
                raise RuntimeError("W was consumed by UI; driving sample is invalid")
        next_update = 0.0
        while time.monotonic() - started < args.seconds:
            now = time.monotonic()
            sample = host_sample(args.editor_pid)
            sample["elapsed_s"] = round(now - started, 3)
            low_since = (now if low_since is None else low_since) if sample["available_ram_fraction"] < .15 else None
            if low_since is not None and now - low_since >= 3:
                raise RuntimeError("available RAM below 15% for 3s")
            recent_log = log_tail.read()
            if FAULT.search(recent_log):
                raise RuntimeError("new GPU timeout/device failure/fatal log entry")
            observe_csv(report, recent_log)
            if now - started >= 5 and not report.get("csv_id"):
                raise RuntimeError("no native CSV start confirmation after 5s")
            # This native handler executes on the game thread. A 5s RPC timeout
            # aborts instead of queueing repeated sampling calls behind a stall.
            stats = bridge.call("editor_get_performance_stats")
            sample.update(stats)
            frame_ms = float(stats["frame_ms"])
            if not math.isfinite(frame_ms) or frame_ms <= 0:
                raise RuntimeError("native performance sample is invalid")
            slow_samples = slow_samples + 1 if frame_ms > 250 else 0
            if slow_samples >= 3:
                raise RuntimeError("three consecutive smoothed frame-time samples above 250ms")
            live = bridge.call("editor_get_state")
            if not live["pie_running"]:
                # RequestPlaySession is queued: the first response can precede
                # creation of the play world. Allow a short bounded transition.
                if args.start_pie and now - started < 5:
                    time.sleep(.5)
                    continue
                raise RuntimeError("PIE ended during capture")
            pc = pc or bridge.actor("PC_Saskarta_C")
            flow = bridge.flow(pc["path"]) if pc else None
            sample["flow"] = flow
            report["samples"].append(sample)
            (out / "checkpoint.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            if args.phase == "startup" and flow in ("Title", "Playing"):
                report["status"] = "complete"
                break
            if args.phase == "driving" and flow != "Playing":
                raise RuntimeError(f"driving window interrupted by FlowState={flow!r}")
            if now - started >= next_update:
                print(f"{args.label} {args.phase}: {now-started:.0f}s, flow={flow}, smoothed frame={stats.get('frame_ms')}ms", flush=True)
                next_update += 30
            time.sleep(.5)
        else:
            if args.phase == "startup":
                raise RuntimeError("startup exceeded bounded window before title/play")
            report["status"] = "complete"
        if args.phase == "driving":
            report["carrier_end"] = bridge.actor("BP_Saskarta_Carrier_C")
    except (Exception, KeyboardInterrupt) as exc:
        report.update(status="aborted", reason=str(exc) or "operator interrupt")
    finally:
        # Ordinary requests only. A hung editor may not process them; record
        # failure and return control to root rather than killing or retrying it.
        if report['csv_ownership'] == 'confirmed_new_guid':
            try:
                observe_csv(report, log_tail.read())
            except Exception as exc:
                if report['csv_ownership'] == 'confirmed_new_guid':
                    report['csv_ownership'] = 'unknown_after_log_error'
                report['cleanup'].append({'action': 'recheck CSV ownership', 'error': str(exc)})
        if csv_requested and report['csv_ownership'] == 'requested_unconfirmed':
            # A timed-out START may have queued successfully. Resolve passively;
            # never STOP a recorder without a fresh owned GUID.
            until = time.monotonic() + 5
            while time.monotonic() < until and report['csv_ownership'] == 'requested_unconfirmed':
                try:
                    observe_csv(report, log_tail.read())
                except Exception as exc:
                    report['cleanup'].append({'action': 'resolve CSV ownership', 'error': str(exc)})
                    break
                if report['csv_ownership'] == 'requested_unconfirmed':
                    time.sleep(.25)
        actions = []
        owned = report['csv_ownership'] == 'confirmed_new_guid'
        if w_requested:
            actions.append(("release W", lambda: bridge.call("editor_pie_press_key", {"key": "W", "event": "released"}, 2)))
        if owned:
            actions.append(("stop CSV", lambda: bridge.console("CsvProfile STOP", 2)))
        if owned and pie_owned and (args.phase == "driving" or report["status"] != "complete"):
            actions.append(("request PIE stop", lambda: bridge.call("editor_stop_pie", timeout=2)))
        if csv_requested and not owned:
            report['cleanup'].append({'action': 'leave unowned recorder and PIE unchanged',
                                      'error': 'CSV ownership unconfirmed/refused; root must inspect before another trial'})
        for name, action in actions:
            try:
                report["cleanup"].append({"action": name, "result": action()})
            except Exception as exc:
                report["cleanup"].append({"action": name, "error": str(exc)})
        report["elapsed_s"] = round(time.monotonic() - started, 3)
        (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    report['csv'] = completed_csv(report, before)
    report["focused_entire_sample"] = bool(report["samples"]) and all(x["editor_foreground"] for x in report["samples"])
    report["acceptance"] = "not_evaluated" if args.phase == "startup" else "unverified"
    if args.phase == "driving" and report["status"] == "complete" and report["csv"]:
        report["acceptance"] = "fail" if any(x["summary"]["hitches_over_50_ms"] for x in report["csv"]) else "hitch_threshold_met_in_this_sample"
    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(out / "report.json"), "status": report["status"], "acceptance": report["acceptance"], "csv_count": len(report["csv"])}))
    return 0 if report["status"] == "complete" and report["csv"] and not any("error" in x for x in report["cleanup"]) else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("plan")
    analyze = sub.add_parser("analyze")
    analyze.add_argument("csv")
    live = sub.add_parser("capture")
    live.add_argument("--phase", required=True, choices=("startup", "driving"))
    live.add_argument("--label", required=True, choices=("cold", "warm"))
    live.add_argument("--owner", required=True)
    live.add_argument("--editor-pid", required=True, type=int)
    live.add_argument("--seconds", type=float, default=90)
    live.add_argument("--start-pie", action="store_true")
    live.add_argument("--hold-w", action="store_true")
    args = parser.parse_args()
    if args.command in (None, "plan"):
        print(PLAN)
        return 0
    if args.command == "analyze":
        print(json.dumps(summarize(args.csv), indent=2))
        return 0
    if not math.isfinite(args.seconds) or not 1 <= args.seconds <= 90:
        parser.error("--seconds must be between 1 and 90")
    return capture(args)


if __name__ == "__main__":
    raise SystemExit(main())
