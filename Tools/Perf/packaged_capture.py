"""Offline preparation or read-only monitoring of a root-launched Development game.

Never launches/stops a process, sends input, acquires a lease or changes settings.
See docs/performance/2026-10-01-packaged-capture.md. No Hayba calls are made.
"""
from __future__ import annotations
import argparse
import csv
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import time
import uuid

import bounded_pie_profile as shared

BASE = shared.ROOT / 'Saved/Verification/packaged_capture_preparation_20261001'
PLAN = '''Root-only sequence (this helper does not launch or send input):
1. prepare --exe ACTUAL_BINARY_EXE --settings ORIGINAL_GameUserSettings.ini --label cold
2. Root runs generated launch.ps1 visibly; note actual binary PID, not bootstrap PID.
3. monitor --manifest MANIFEST --pid PID --phase startup --seconds 120
4. At Title root uses normal console `CsvProfile STOP` if boot capture is active.
5. After finalized startup, root begins normally. Arm monitor first for driving or
   Settings, then enter `CsvProfile FRAMES=1800`, close console and operate normally.
6. Root stops via `CsvProfile STOP` after30s (Settings) or60s (driving), if still active.
7. Root captures screenshots through approved computer-use after CSV stops.
8. Normal quit, prepare --label warm with SAME original settings, repeat startup.
No quality overrides, old saves/settings changes, input automation or process killing.
RAM<15% for3s/fault/deadline aborts observation and asks root for normal stop.
Capture completion is not gameplay/visual acceptance. Cold/warm are operator labels.
'''


def utc():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2), encoding='utf-8')


def ps_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def prepare(args):
    exe, settings = Path(args.exe).resolve(strict=True), Path(args.settings).resolve(strict=True)
    if exe.suffix.lower() != '.exe' or 'unrealeditor' in exe.name.lower():
        raise ValueError('Supply the actual packaged game binary, not UnrealEditor')
    if settings.name.lower() != 'gameusersettings.ini':
        raise ValueError('Supply the intended existing GameUserSettings.ini baseline')
    token = uuid.uuid4().hex
    out = BASE / (time.strftime('%Y%m%d_%H%M%S') + '_' + args.label + '_' + token[:8])
    config = out/'profile/Saved/Config/Windows/GameUserSettings.ini'
    config.parent.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(settings, config)
    assert digest(settings) == digest(config)
    log = out/'runtime.log'
    arguments = [f'-UserDir={out / "profile"}', f'-abslog={log}',
                 '-csvCaptureFrames=1800', '-csvCompression=0', f'-csvMetadata=runid={token}']
    manifest = {'created_utc': utc(), 'runid': token, 'label': args.label,
                'exe': str(exe), 'exe_sha256': digest(exe), 'arguments': arguments,
                'user_dir': str(out/'profile'), 'log': str(log),
                'csv_dir': str(out/'profile/Saved/Profiling/CSV'),
                'original_settings': str(settings), 'original_settings_sha256': digest(settings),
                'copied_settings': str(config), 'savegames_seeded': False}
    save(out/'manifest.json', manifest)
    # Root invokes this deliberately. Call operator preserves each argument as
    # one literal even when paths contain spaces. No shell expansion in values.
    command = '& ' + ps_quote(exe) + ' ' + ' '.join(ps_quote(a) for a in arguments)
    (out/'launch.ps1').write_text(
        'if (Test-Path -LiteralPath ' + ps_quote(log) +
        ") { throw 'This prepared run was already launched; prepare a new run.' }\n" + command + '\n',
        encoding='utf-8')
    print(json.dumps({'manifest': str(out/'manifest.json'), 'root_launch_script': str(out/'launch.ps1'),
                      'arguments': arguments, 'baseline_sha256': digest(settings)}, indent=2))
    return 0


def windows_argv(commandline):
    shell = ctypes.WinDLL('shell32', use_last_error=True)
    shell.CommandLineToArgvW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
    shell.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)
    count = ctypes.c_int()
    values = shell.CommandLineToArgvW(commandline, ctypes.byref(count))
    if not values:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return [values[i] for i in range(count.value)]
    finally:
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree(values)


class ProcessReader:
    def __init__(self, pid, manifest):
        if os.name != 'nt':
            raise RuntimeError('Live monitoring requires Windows')
        # One read-only identity query. Do not enumerate/control other processes.
        code = (f"$p=Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}'; "
                "if(!$p){throw 'PID absent'}; "
                "$p|Select-Object ProcessId,ExecutablePath,CommandLine|ConvertTo-Json -Compress")
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', code],
                                capture_output=True, text=True, check=True, timeout=8,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        self.identity = json.loads(result.stdout)
        if Path(self.identity.get('ExecutablePath') or '').resolve() != Path(manifest['exe']).resolve():
            raise RuntimeError('PID executable differs from prepared actual packaged binary')
        argv = windows_argv(self.identity.get('CommandLine') or '')
        for wanted in manifest['arguments']:
            if argv.count(wanted) != 1:
                raise RuntimeError('PID command line lacks unique prepared argument: ' + wanted)
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        self.handle = self.kernel.OpenProcess(0x1010, False, pid)  # query + read only
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        self.pid = pid

    def sample(self):
        exitcode = wintypes.DWORD()
        if not self.kernel.GetExitCodeProcess(self.handle, ctypes.byref(exitcode)) or exitcode.value != 259:
            raise RuntimeError('The observed game process exited')
        class Counters(ctypes.Structure):
            _fields_ = [('cb', wintypes.DWORD), ('faults', wintypes.DWORD)] + [
                (name, ctypes.c_size_t) for name in ('peak_working_set', 'working_set', 'peak_paged',
                'paged', 'peak_nonpaged', 'nonpaged', 'pagefile', 'peak_pagefile', 'private')]
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        psapi = ctypes.WinDLL('psapi', use_last_error=True)
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
        if not psapi.GetProcessMemoryInfo(self.handle, ctypes.byref(counters), counters.cb):
            raise ctypes.WinError(ctypes.get_last_error())
        host = shared.host_sample(self.pid)
        return {'utc': utc(), 'available_ram_fraction': host['available_ram_fraction'],
                'game_foreground': host['editor_foreground'], 'working_set_bytes': counters.working_set,
                'private_bytes': counters.private}

    def close(self):
        self.kernel.CloseHandle(self.handle)


def read_ready_csv(report, directory, before, runid):
    shared.CSV_DIR = directory
    result = shared.completed_csv(report, before)
    if not result:
        raise RuntimeError('Owned CSV did not finalize within10s; inspect writer/error receipt')
    path = Path(result[0]['path'])
    with path.open('rb') as stream:
        stream.seek(max(0, path.stat().st_size - 65536))
        footer = stream.read().lower()
    if ('[runid],' + runid).lower().encode() not in footer:
        raise RuntimeError('CSV footer runid differs from prepared process')
    duration = 0.
    with path.open(newline='', encoding='utf-8-sig') as stream:
        for row in csv.DictReader(stream):
            if (row.get('EVENTS') or '').startswith('[HasHeaderRowAtEnd]'):
                break
            try:
                value = float(row.get('FrameTime', ''))
            except (ValueError, TypeError):
                continue
            if math.isfinite(value) and value >= 0:
                duration += value / 1000
    result[0].update(frame_time_sum_s=duration, sha256=digest(path))
    return result


def monitor(args):
    manifest_path = Path(args.manifest).resolve(strict=True)
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if digest(manifest['exe']) != manifest['exe_sha256']:
        raise RuntimeError('Packaged executable changed after preparation')
    if digest(manifest['original_settings']) != manifest['original_settings_sha256']:
        raise RuntimeError('Original settings changed after preparation; establish a new baseline')
    reader = ProcessReader(args.pid, manifest)
    out = manifest_path.parent / (time.strftime('%H%M%S') + '_' + args.phase)
    out.mkdir(exist_ok=False)
    report = {'phase': args.phase, 'status': 'observing', 'acceptance': 'unverified',
              'started_utc': utc(), 'pid': args.pid, 'process': reader.identity, 'manifest': str(manifest_path),
              'samples': [], 'csv': [], 'cleanup': [], 'csv_ownership': 'not_requested',
              'ram_coverage': 'From monitor attachment only; earlier boot RAM is unobserved',
              'operator_action': 'None; monitor never sends input or stops the game/recorder'}
    log, directory = Path(manifest['log']), Path(manifest['csv_dir'])
    before = {} if args.phase == 'startup' else {
        p: (p.stat().st_size, p.stat().st_mtime_ns) for p in directory.glob('*.csv')}
    started, low_since, unfocused_since, seen_foreground = time.monotonic(), None, None, False
    tail = None
    try:
        if reader.sample()['available_ram_fraction'] < .15:
            raise RuntimeError('Available RAM is below15% before observation')
        if args.phase != 'startup':
            shared.require_idle_csv(log.read_text(encoding='utf-8', errors='replace'))
            tail = shared.LogTail(log)
            tail.carry = b''
        print('MONITOR_READY ' + str(out/'report.json'), flush=True)
        if args.phase != 'startup':
            print('ROOT: start CsvProfile FRAMES=1800 normally, then close console and operate.', flush=True)
        while time.monotonic() - started < args.seconds:
            now = time.monotonic()
            sample = reader.sample()
            sample['elapsed_s'] = now-started
            report['samples'].append(sample)
            low_since = (now if low_since is None else low_since) if sample['available_ram_fraction'] < .15 else None
            if low_since is not None and now-low_since >= 3:
                raise RuntimeError('Available RAM below15% for3s')
            seen_foreground |= sample['game_foreground']
            unfocused_since = (now if unfocused_since is None else unfocused_since) if not sample['game_foreground'] else None
            if seen_foreground and unfocused_since is not None and now-unfocused_since >= 3:
                raise RuntimeError('Game lost foreground for3s; sample is not comparable')
            if tail is None and log.is_file():
                tail = shared.LogTail(log)
                tail.offset, tail.carry = 0, b''  # unique prepared log, include boot GUID
            recent = tail.read() if tail else ''
            if shared.FAULT.search(recent):
                raise RuntimeError('New native/GPU fault in this process log')
            shared.observe_csv(report, recent)
            if report.get('csv_id'):
                report.setdefault('csv_first_observed_s', now-started)
            if 'Capture Ended. Writing CSV to file' in recent:
                if not report.get('csv_id'):
                    raise RuntimeError('CSV ended without a newly observed start GUID')
                report['csv'] = read_ready_csv(report, directory, before, manifest['runid'])
                if args.phase != 'startup' and report['csv'][0]['frame_time_sum_s'] < 28:
                    raise RuntimeError('Less than28s of finalized frames; not a30s trial')
                if not seen_foreground:
                    raise RuntimeError('No observed foreground game window; capture is unverified')
                report['status'] = 'captured'
                break
            if args.phase != 'startup' and not report.get('csv_id') and now-started > 20:
                raise RuntimeError('No new CSV start GUID within20s of arming')
            save(out/'report.json', report)
            time.sleep(1)
        else:
            raise TimeoutError('Bounded observation deadline expired without a finalized CSV')
    except (Exception, KeyboardInterrupt) as error:
        report.update(status='aborted', reason=str(error) or 'operator interruption',
                      operator_action='ROOT: inspect process; if capture is active, normal CsvProfile STOP, then normal quit if needed. No automatic input was sent.')
    finally:
        reader.close()
        report['elapsed_s'] = time.monotonic()-started
        report['original_settings_unchanged'] = digest(manifest['original_settings']) == manifest['original_settings_sha256']
        save(out/'report.json', report)
    print(json.dumps({'report': str(out/'report.json'), 'status': report['status'],
                      'operator_action': report['operator_action']}), flush=True)
    return 0 if report['status'] == 'captured' and report['original_settings_unchanged'] else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='mode')
    sub.add_parser('plan')
    prep = sub.add_parser('prepare')
    prep.add_argument('--exe', required=True)
    prep.add_argument('--settings', required=True)
    prep.add_argument('--label', choices=['cold', 'warm'], required=True)
    watch = sub.add_parser('monitor')
    watch.add_argument('--manifest', required=True)
    watch.add_argument('--pid', type=int, required=True)
    watch.add_argument('--phase', choices=['startup', 'driving', 'settings-no-change', 'settings-audio'], required=True)
    watch.add_argument('--seconds', type=int, default=120)
    args = parser.parse_args()
    if args.mode in (None, 'plan'):
        print(PLAN)
        return 0
    if args.mode == 'prepare':
        return prepare(args)
    if not 30 <= args.seconds <= 120 or args.pid <= 0:
        parser.error('Monitor requires positive PID and30..120 seconds')
    return monitor(args)


if __name__ == '__main__':
    raise SystemExit(main())
