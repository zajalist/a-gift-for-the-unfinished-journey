"""Root-operated 30s Settings Apply trial through observed Slate controls only.

Default plan is offline. The open mode follows Settings > Audio from Title or
Pause. No setting setters, quality changes, start/stop/replay or asset operations.
"""
from pathlib import Path
import argparse
import ctypes
import json
import math
import re
import time

import gameplay_acceptance as capture
import pie_input_walkthrough as walk

profile = capture.profile
ROOT = profile.ROOT
PLAN = """From Title or Pause, open a fresh Settings > Audio page through real buttons:
  python Tools/Perf/settings_apply_capture.py open --owner OWNER --editor-pid PID --hwnd HWND
Open mode refuses an already-open Settings page, changes no values and starts no CSV.
Alternatively open Settings > Audio manually, with no unsaved user edits. Leave it open.
Run no-change first, then audio-only, with the same PID/HWND/root lease and values.
  python Tools/Perf/settings_apply_capture.py run --case no-change --owner OWNER --editor-pid PID --hwnd HWND
  python Tools/Perf/settings_apply_capture.py run --case audio-only --owner OWNER --editor-pid PID --hwnd HWND
No-change: 30s CSV; observed Apply clicks at >=8s and >=18s.
Audio-only: observed Master must be1.00; normal slider input lowers it to0.95
at >=5s, Apply at >=12s; after CSV stops, restore1.00 and Apply through the UI.
Exact dispatch times are recorded; polling/UI readback overhead is part of this trial.
Before/after screenshots are outside CSV. Success leaves the menu/PIE running.
Requires current PID/HWND, HB_PORT, root's existing150s global lease and >=15% freeRAM.
If the restore receipt is not confirmed, inspect the menu before another trial.
"""


def rows(result):
    widgets = result.get('widgets', [])
    if result.get('count') != len(widgets):
        raise RuntimeError('Widget inventory incomplete; no input allowed')
    return widgets


def master_value(widgets):
    # The native tree aggregates descendant text through four levels. The
    # smallest exact row is enough; do not guess from a global numeric label.
    found = []
    for item in widgets:
        match = re.fullmatch(r'Master\s+(0(?:\.\d+)?|1(?:\.0+)?)', item.get('text', '').strip())
        if match and item.get('enabled') is True:
            found.append((float(match.group(1)), item))
    if not found or len({value for value, _ in found}) != 1:
        raise RuntimeError('Cannot uniquely read the actual Master numeric label')
    return min(found, key=lambda pair: float(pair[1]['width']) * float(pair[1]['height']))


def master_slider(master_widgets, slider_widgets):
    labels = [item for item in master_widgets if item.get('type') == 'STextBlock' and
              item.get('text', '').strip() == 'Master' and item.get('enabled') is True]
    if len(labels) != 1:
        raise RuntimeError('Master label is absent or ambiguous')
    label = labels[0]
    found = [item for item in slider_widgets if item.get('type') == 'SSlider' and
             item.get('enabled') is True and float(item['width']) >= 50 and
             float(item['x']) > float(label['x']) and
             abs(float(item['center_y']) - float(label['center_y'])) <= max(4., float(label['height']) / 2)]
    if len(found) != 1:
        raise RuntimeError('No single observed slider shares the Master row')
    return found[0]


class SettingsTrial(walk.Walkthrough):
    # Reuse the proven screenshot, exact button matching and InputLedger methods;
    # this initializer keeps Settings evidence separate from driving walkthroughs.
    def __init__(self, args):
        self.args = args
        identity = walk.windows(args.editor_pid)
        instance = json.loads((ROOT/'Saved/HaybaMCP/instances'/f'{args.editor_pid}.json').read_text(encoding='utf-8'))
        if (instance.get('pid') != args.editor_pid or
                Path(instance.get('project_dir', '')).resolve() != ROOT.resolve() or
                instance.get('port') != profile.editor_gate.PORT):
            raise RuntimeError('PID/project/HB_PORT must match the current native instance')
        self.bridge = capture.Bridge(args.owner)
        live = self.bridge.call('editor_get_state')
        if not live.get('pie_running') or '/Game/level/Saskarta_WP' not in live.get('map', ''):
            raise RuntimeError('One existing Saskarta_WP PIE session is required')
        self.pc = self.bridge.actor('PC_Saskarta_C')
        if not self.pc:
            raise RuntimeError('One current PIE player controller is required')
        idle = profile.require_idle_csv(profile.LOG.read_text(encoding='utf-8', errors='replace'))
        self.out = ROOT/'Saved/Verification/settings_apply'/(
            time.strftime('%Y%m%d_%H%M%S') + '_' + args.case)
        self.out.mkdir(parents=True, exist_ok=False)
        self.report = {'case': args.case, 'status': 'running', 'seconds': 30,
                       'acceptance': 'not_assessed', 'host_identity': identity, 'instance': instance,
                       'events': [], 'samples': [], 'cleanup': [], 'csv': [],
                       'csv_ownership': 'not_requested', 'csv_preflight': idle,
                       'audio_restore': 'not_needed', 'quality_changes_requested': False}
        self.tail = profile.LogTail(profile.LOG)
        self.tail.carry = b''
        self.started = time.monotonic()
        self.deadline = self.started + 120
        self.window_at = None
        self.restore_needed = False
        self.transport_failed = False
        self.inputs = walk.InputLedger(self.call)
        self.before = {p: (p.stat().st_size, p.stat().st_mtime_ns) for p in profile.CSV_DIR.glob('*.csv')}

    def save(self):
        capture.save(self.out/'report.json', self.report)

    def read_log(self):
        recent = self.tail.read()
        if self.report['csv_ownership'] != 'not_requested':
            profile.observe_csv(self.report, recent)
        if capture.FAULT.search(recent):
            raise RuntimeError('New native/GPU fault')

    def guard(self):
        if time.monotonic() >= self.deadline:
            raise TimeoutError('120-second total Settings trial deadline reached')
        self.read_log()
        host = profile.host_sample(self.args.editor_pid)
        if (host['available_ram_fraction'] < .15 or not host['editor_foreground'] or
                ctypes.windll.user32.GetForegroundWindow() != self.args.hwnd):
            raise RuntimeError('Exact editor window lost foreground or available RAM below15%')

    def call(self, command, params=None):
        self.guard()
        now = time.monotonic()
        event = {'command': command, 'params': params or {}, 'status': 'requested',
                 'utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                 'trial_s': round(now-self.started, 4),
                 'window_s': None if self.window_at is None else round(now-self.window_at, 4)}
        self.report['events'].append(event)
        self.save()
        try:
            result = self.bridge.call(command, params)
        except BaseException:
            self.transport_failed = True
            raise
        event.update(status='returned', result=result, returned_trial_s=round(time.monotonic()-self.started, 4))
        self.save()
        if result.get('warning') or result.get('warnings'):
            raise RuntimeError('Native UI/observation warning; inspect receipt')
        return result

    def observe_master(self):
        observed = rows(self.call('editor_pie_widget_tree', {'filter': 'Master', 'max_depth': 60}))
        value, row = master_value(observed)
        return value, observed, row

    def require_apply(self):
        observed = rows(self.call('editor_pie_widget_tree', {'filter': 'Apply', 'max_depth': 60}))
        if len([w for w in observed if w.get('type') == 'SButton' and w.get('enabled') is True and
                w.get('text', '').strip().casefold() == 'apply']) != 1:
            raise RuntimeError('No unique enabled Apply button on current Settings page')

    def open_audio_menu(self):
        """Only normal menu navigation; leave settings drafts and CSV untouched."""
        self.report.update(seconds=0, settings_values_changed=False, csv_started=False)
        try:
            self.report['activation'] = walk.activate(self.args.editor_pid, self.args.hwnd)
            current = self.flow()
            self.report['initial_flow'] = current
            if current not in ('Title', 'Paused'):
                raise RuntimeError('Open requires Title or Paused; open the pause menu normally first')
            existing = rows(self.call('editor_pie_widget_tree', {'filter': 'Apply', 'max_depth': 60}))
            if any(w.get('type') == 'SButton' and w.get('text', '').strip().casefold() == 'apply'
                   for w in existing):
                raise RuntimeError('Settings is already open; inspect pending edits before a capture trial')
            self.click('Settings', 'SButton')
            self.click('Audio', 'SButton')
            value, _, _ = self.observe_master()
            self.report['baseline_master'] = value
            self.require_apply()
            self.screenshot('00_audio_open')
            self.report.update(status='complete', functional_acceptance='rendered_review_required')
        except (Exception, KeyboardInterrupt) as error:
            self.report.update(status='aborted', reason=str(error) or 'operator interruption')
        finally:
            self.report['cleanup'].extend(self.inputs.release_all(self.bridge.call))
            self.save()
        print(json.dumps({'report': str(self.out/'report.json'), 'status': self.report['status'],
                          'settings_values_changed': False, 'csv_started': False}))
        return 0 if self.report['status'] == 'complete' else 2

    def require_master(self, expected):
        value, observed, row = self.observe_master()
        if not math.isclose(value, expected, abs_tol=.001):
            raise RuntimeError(f'Actual Master label is{value}; expected{expected}')
        return observed

    def focus_master_endpoint(self):
        value, observed, _ = self.observe_master()
        sliders = rows(self.call('editor_pie_widget_tree', {'filter': 'SSlider', 'max_depth': 60}))
        slider = master_slider(observed, sliders)
        # Endpoint lies inside the observed widget and clamps through SSlider's
        # normal PositionToValue path. No value/property is written by this tool.
        self.restore_needed = True
        self.report['audio_restore'] = 'required'
        result = self.call('editor_pie_mouse', {'action': 'click', 'button': 'left',
            'x': float(slider['x']) + float(slider['width']) - 2., 'y': float(slider['center_y']),
            'coordinate_space': 'absolute'})
        if result.get('dispatched') is not True or result.get('focused_widget_after') != 'SSlider':
            raise RuntimeError('Master endpoint click did not confirm slider keyboard focus')
        if result.get('pressed_buttons') or result.get('mouse_captor'):
            raise RuntimeError('Mouse capture/buttons remained active after click')
        self.require_master(1.)

    def change_audio(self):
        self.require_master(1.)
        self.focus_master_endpoint()
        # Default SSlider RequiresControllerLock: Enter captures navigation,
        # then exactly one Left is one authored0.05 step. Every pulse releases.
        self.inputs.pulse('Enter', 80)
        self.inputs.pulse('Left', 80)
        self.require_master(.95)
        self.report['changed_master'] = .95

    def restore_audio(self):
        if not self.restore_needed:
            return
        if self.transport_failed:
            raise RuntimeError('RPC failed; audio restoration requires root inspection before further input')
        self.focus_master_endpoint()
        self.click('Apply', 'SButton')
        self.require_master(1.)
        self.restore_needed = False
        self.report['audio_restore'] = 'confirmed_1.00_via_ui_and_apply'
        self.save()

    def start_csv(self):
        self.report['csv_ownership'] = 'requested_unconfirmed'
        self.call('editor_run_console_command', {'command': 'CsvProfile START'})
        until = time.monotonic()+5
        while self.report['csv_ownership'] == 'requested_unconfirmed' and time.monotonic() < until:
            self.guard()
            time.sleep(.1)
        if self.report['csv_ownership'] != 'confirmed_new_guid':
            raise RuntimeError('CSV ownership must be confirmed before Apply or audio input')
        self.window_at = time.monotonic()
        self.report['window_started_trial_s'] = self.window_at-self.started

    def stop_owned_csv(self):
        # Resolve ambiguous START passively; never stop an unowned recorder.
        until = time.monotonic()+5
        while self.report['csv_ownership'] == 'requested_unconfirmed' and time.monotonic() < until:
            try:
                self.read_log()
            except Exception as error:
                self.report['cleanup'].append({'action': 'resolve CSV ownership', 'error': str(error)})
                break
            time.sleep(.1)
        if self.report['csv_ownership'] == 'confirmed_new_guid':
            try:
                self.read_log()
                result = self.bridge.console('CsvProfile STOP', 2)
                self.report['cleanup'].append({'action': 'stop owned CSV', 'result': result})
                self.report['window_stopped_trial_s'] = time.monotonic()-self.started
                self.window_at = None
            except Exception as error:
                self.transport_failed = True
                self.report['cleanup'].append({'action': 'stop owned CSV', 'error': str(error)})
        elif self.report['csv_ownership'] != 'not_requested':
            self.report['cleanup'].append({'action': 'leave unowned recorder unchanged',
                'error': 'Ownership unconfirmed/refused; root must inspect'})

    def run_window(self):
        self.start_csv()
        actions = ([(8., lambda: self.click('Apply', 'SButton')), (18., lambda: self.click('Apply', 'SButton'))]
                   if self.args.case == 'no-change' else
                   [(5., self.change_audio), (12., lambda: self.click('Apply', 'SButton'))])
        next_action = 0
        slow = 0
        while time.monotonic()-self.window_at < 30:
            self.guard()
            elapsed = time.monotonic()-self.window_at
            if next_action < len(actions) and elapsed >= actions[next_action][0]:
                actions[next_action][1]()
                next_action += 1
            stats = self.call('editor_get_performance_stats')
            frame = float(stats['frame_ms'])
            if not math.isfinite(frame) or frame <= 0:
                raise RuntimeError('Invalid frame sample')
            slow = slow+1 if frame > 250 else 0
            if slow >= 3:
                raise RuntimeError('Three consecutive smoothed frame samples above250ms')
            self.report['samples'].append({'window_s': round(time.monotonic()-self.window_at, 4), **stats})
            live = self.call('editor_get_state')
            if not live.get('pie_running'):
                raise RuntimeError('PIE ended during Settings trial')
        if next_action != len(actions):
            raise RuntimeError('Not all scheduled UI actions completed within the window')

    def run(self):
        try:
            self.report['activation'] = walk.activate(self.args.editor_pid, self.args.hwnd)
            value, _, row = self.observe_master()
            self.report['baseline_master'] = value
            if self.args.case == 'audio-only' and not math.isclose(value, 1., abs_tol=.001):
                raise RuntimeError('Audio-only trial supports observed Master1.00 only; baseline left unchanged')
            # Validate the real Apply target before CSV or audio mutation.
            self.require_apply()
            self.screenshot('00_before')
            self.run_window()
            self.report['status'] = 'complete'
        except (Exception, KeyboardInterrupt) as error:
            self.report.update(status='aborted', reason=str(error) or 'operator interruption')
        finally:
            self.stop_owned_csv()
            self.report['cleanup'].extend(self.inputs.release_all(self.bridge.call))
            try:
                self.restore_audio()
            except Exception as error:
                self.report['audio_restore'] = 'ROOT_INSPECTION_REQUIRED'
                self.report.update(status='aborted', reason='Original Master restoration was not confirmed')
                self.report['cleanup'].append({'action': 'restore original Master through UI', 'error': str(error)})
            self.save()
        if self.report.get('csv_id'):
            self.report['csv'] = profile.completed_csv(self.report, self.before)
        if self.report['status'] == 'complete' and not self.restore_needed:
            try:
                self.require_master(self.report['baseline_master'])
                self.screenshot('01_after_restoration')
            except Exception as error:
                self.report.update(status='aborted', reason='Final UI evidence: '+str(error))
        self.report['hitch_acceptance'] = ('fail' if any(c['summary']['hitches_over_50_ms'] for c in self.report['csv'])
            else 'zero_over50ms_in_this_window' if self.report['csv'] else 'unverified')
        self.report['functional_acceptance'] = 'rendered_review_required'
        self.save()
        print(json.dumps({'report': str(self.out/'report.json'), 'status': self.report['status'],
                          'audio_restore': self.report['audio_restore'], 'hitch_acceptance': self.report['hitch_acceptance']}))
        return 0 if (self.report['status'] == 'complete' and self.report['csv'] and not self.restore_needed and
                     not any('error' in item or item.get('confirmed') is False for item in self.report['cleanup'])) else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', nargs='?', default='plan', choices=['plan', 'open', 'run'])
    parser.add_argument('--case', choices=['no-change', 'audio-only'])
    parser.add_argument('--owner')
    parser.add_argument('--editor-pid', type=int)
    parser.add_argument('--hwnd', type=lambda value: int(value, 0))
    args = parser.parse_args()
    if args.mode == 'plan':
        print(PLAN)
        return 0
    if not args.owner or not args.editor_pid or not args.hwnd:
        parser.error('open/run require --owner, --editor-pid and exact --hwnd')
    if args.mode == 'open':
        args.case = 'open-audio'
        return SettingsTrial(args).open_audio_menu()
    if not args.case:
        parser.error('run requires --case')
    return SettingsTrial(args).run()


if __name__ == '__main__':
    raise SystemExit(main())
