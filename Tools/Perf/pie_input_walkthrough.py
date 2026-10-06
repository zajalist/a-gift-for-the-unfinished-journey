"""Root-only normal-input walkthrough. Default plan is offline; never starts PIE.

No actor calls, teleport, debug-state setters, native build or asset writes.
Rendered evidence and dispatched input are observations, never a gameplay pass.
"""
from pathlib import Path
import argparse
import ctypes
from ctypes import wintypes
import json
import os
import time

import gameplay_acceptance as capture

profile = capture.profile
ROOT = profile.ROOT
CASES = ('startup-skip', 'first-drive-controls', 'parked-motor')
LIMITS = {'startup-skip': 55, 'first-drive-controls': 90, 'parked-motor': 55}
DIRECTIVE_BEGIN = 'cinematic CIN_01_DIRECTIVE: begin '
DIRECTIVE_HANDBACK = 'cinematic CIN_01_DIRECTIVE: handed back'
PLAN = {
    'startup-skip': ['existing fresh PIE FlowState=None', 'capture current card/loading',
                     'SpaceBar200ms', 'wait for natural Title (max40s)', 'capture title'],
    'first-drive-controls': ['Title: arm fresh log offset, then click observed Begin',
                             'optional SpaceBar200ms during Booting', 'require new CIN01 begin marker',
                             'optional SpaceBar1400ms after1.2s to request directive skip',
                             'require new CIN01 handed-back marker (Playing alone is insufficient)',
                             'capture first control glyphs immediately', 'focus observed single SViewport',
                             'W900ms; release', 'MouseX=1 one-frame; neutralize', 'capture first drive'],
    'parked-motor': ['Playing/Carrier, parked and no prompt/map/cinematic', 'focus observed single SViewport',
                     'wait2.5s stationary', 'Tab200ms', 'require new begin tuning log',
                     'capture motor CRT', 'E200ms, A150ms, D150ms', 'capture feedback; no score claim'],
}


class OpeningEvidence:
    """Only bytes appended after this attempt was armed may prove CIN01 handback."""
    def __init__(self, path):
        self.tail = profile.LogTail(path)
        self.tail.carry = b''  # Discard any pre-arm partial line as well as old complete lines.
        self.start_offset = self.tail.offset
        self.text = ''

    def read(self):
        self.text += self.tail.read()

    @property
    def begun(self):
        return DIRECTIVE_BEGIN in self.text

    @property
    def handed_back(self):
        start = self.text.find(DIRECTIVE_BEGIN)
        return start >= 0 and self.text.find(DIRECTIVE_HANDBACK, start) >= 0


def windows(editor_pid):
    """Host-only identity/inventory; no focus or editor mutation."""
    if os.name != 'nt':
        raise RuntimeError('Window identity requires Windows')
    kernel, user = ctypes.windll.kernel32, ctypes.windll.user32
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    process = kernel.OpenProcess(0x1000, False, editor_pid)
    if not process:
        raise RuntimeError('Cannot inspect requested editor PID')
    try:
        image = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(image))
        if not kernel.QueryFullProcessImageNameW(process, 0, image, ctypes.byref(size)):
            raise RuntimeError('Cannot verify editor executable')
        if Path(image.value).name.casefold() != 'unrealeditor.exe':
            raise RuntimeError('Requested PID is not UnrealEditor.exe')
    finally:
        kernel.CloseHandle(process)
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    user.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    rows = []
    def visit(hwnd, _):
        pid = wintypes.DWORD()
        user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == editor_pid and user.IsWindowVisible(hwnd):
            title = ctypes.create_unicode_buffer(user.GetWindowTextLengthW(hwnd) + 1)
            user.GetWindowTextW(hwnd, title, len(title))
            if title.value:
                rows.append({'hwnd': hex(hwnd), 'pid': pid.value, 'title': title.value})
        return True
    callback = callback_type(visit)
    if not user.EnumWindows(callback, 0):
        raise RuntimeError('Window enumeration failed')
    return {'editor_pid': editor_pid, 'executable': image.value, 'windows': rows}


def activate(editor_pid, hwnd):
    inventory = windows(editor_pid)
    selected = [w for w in inventory['windows'] if int(w['hwnd'], 0) == hwnd]
    if len(selected) != 1:
        raise RuntimeError('Select an exact visible window from the verified PID inventory')
    user = ctypes.windll.user32
    user.IsIconic.argtypes = [wintypes.HWND]
    user.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user.SetForegroundWindow.argtypes = [wintypes.HWND]
    user.GetForegroundWindow.restype = wintypes.HWND
    if user.IsIconic(hwnd):
        user.ShowWindow(hwnd, 9)  # SW_RESTORE; only this explicitly selected window.
    accepted = bool(user.SetForegroundWindow(hwnd))
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and user.GetForegroundWindow() != hwnd:
        time.sleep(.1)
    actual = user.GetForegroundWindow()
    if actual != hwnd or not profile.host_sample(editor_pid)['editor_foreground']:
        raise RuntimeError('Windows did not activate the selected editor window; no input sent')
    return {'selected': selected[0], 'set_foreground_returned': accepted, 'verified_foreground_hwnd': hex(actual)}


class InputLedger:
    """Record intent before dispatch so an ambiguous response still gets neutralized."""
    def __init__(self, call):
        self.call, self.keys, self.axes = call, set(), set()

    def pulse(self, key, held_ms):
        if not 1 <= held_ms <= 1500:
            raise ValueError('Walkthrough key hold outside1..1500ms')
        self.keys.add(key)
        result = self.call('editor_pie_press_key', {'key': key, 'event': 'pressed_and_released', 'held_ms': held_ms})
        if result.get('dispatched') is not True or result.get('release_scheduled') is not True:
            raise RuntimeError('Key dispatch/deferred release was not confirmed')

    def axis(self, key, value):
        if key != 'MouseX' or not -1 <= value <= 1:
            raise ValueError('Only the bounded one-frame MouseX probe is allowed')
        self.axes.add(key)
        self.call('editor_pie_axis', {'key': key, 'value': value})

    def release_all(self, emergency_call):
        outcomes = []
        for command, params in ([('editor_pie_press_key', {'key': k, 'event': 'released'}) for k in sorted(self.keys)] +
                                [('editor_pie_axis', {'key': k, 'value': 0}) for k in sorted(self.axes)]):
            try:
                result = emergency_call(command, params, 2)
                confirmed = (result.get('dispatched') is True if command == 'editor_pie_press_key'
                             else result.get('key') == params['key'] and result.get('value') == 0)
                outcomes.append({'command': command, 'params': params, 'confirmed': confirmed, 'result': result})
            except BaseException as error:
                outcomes.append({'command': command, 'params': params, 'confirmed': False, 'error': str(error)})
        return outcomes


class Walkthrough:
    def __init__(self, args):
        self.args = args
        host_identity = windows(args.editor_pid)
        instance_path = ROOT/'Saved/HaybaMCP/instances'/f'{args.editor_pid}.json'
        instance = json.loads(instance_path.read_text(encoding='utf-8'))
        if instance.get('pid') != args.editor_pid or Path(instance.get('project_dir', '')).resolve() != ROOT.resolve():
            raise RuntimeError('Editor PID instance file does not identify this project')
        if instance.get('port') != profile.editor_gate.PORT:
            raise RuntimeError('Set HB_PORT to the observed instance port before running this helper')
        self.bridge = capture.Bridge(args.owner)
        state = self.bridge.call('editor_get_state')
        if not state.get('pie_running') or '/Game/level/Saskarta_WP' not in state.get('map', ''):
            raise RuntimeError('Start one Saskarta_WP PIE session first')
        self.pc = self.bridge.actor('PC_Saskarta_C')
        if not self.pc:
            raise RuntimeError('Exactly one current PIE controller is required')
        self.out = ROOT/'Saved/Verification/pie_input_walkthrough'/(
            time.strftime('%Y%m%d_%H%M%S') + '_' + args.case)
        self.out.mkdir(parents=True, exist_ok=False)
        self.report = {'case': args.case, 'status': 'running', 'acceptance': 'not_assessed',
                       'host_identity': host_identity, 'instance': instance, 'events': [], 'cleanup': []}
        self.tail = profile.LogTail(profile.LOG)
        self.recent = ''
        self.limit_s = LIMITS[args.case]
        self.deadline = time.monotonic() + self.limit_s
        self.inputs = InputLedger(self.call)

    def save(self):
        capture.save(self.out/'walkthrough.json', self.report)

    def guard(self):
        if time.monotonic() >= self.deadline:
            raise TimeoutError(f'{self.limit_s}-second walkthrough budget reached')
        self.recent += self.tail.read()
        if capture.FAULT.search(self.recent):
            raise RuntimeError('New native/GPU fault; stop this walkthrough')
        host = profile.host_sample(self.args.editor_pid)
        if (host['available_ram_fraction'] < .15 or not host['editor_foreground'] or
                ctypes.windll.user32.GetForegroundWindow() != self.args.hwnd):
            raise RuntimeError('Editor lost foreground or available RAM dropped below15%')

    def call(self, command, params=None):
        self.guard()
        event = {'command': command, 'params': params or {}, 'status': 'requested'}
        self.report['events'].append(event)
        self.save()
        result = self.bridge.call(command, params)
        event.update(status='returned', result=result)
        self.save()
        if result.get('warning') or result.get('warnings'):
            raise RuntimeError('Input/observation warning; inspect recorded response')
        return result

    def wait(self, seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.guard()
            time.sleep(min(.1, max(0., end-time.monotonic())))

    def flow(self):
        result = self.call('editor_pie_assert', {'actor_path': self.pc['path'], 'property_name': 'FlowState',
                                               'expected_value': 'Playing', 'timeout_ms': 0})
        value = result.get('observed_value', result.get('observed_value_last'))
        if value is None:
            raise RuntimeError('Flow observation missing')
        return value

    def wait_flow(self, target, seconds=40):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if self.flow() == target:
                return
        raise TimeoutError('Natural transition to ' + target + ' did not occur')

    def wait_directive(self, opening, handback=False):
        # Host log polling adds no editor round trips. The screenshot must be the
        # first RPC after handback, while the five-second controls cue is visible.
        while True:
            self.guard()
            opening.read()
            if opening.handed_back if handback else opening.begun:
                marker = DIRECTIVE_HANDBACK if handback else DIRECTIVE_BEGIN.rstrip()
                self.report.setdefault('opening_evidence', {})['handback' if handback else 'begin'] = marker
                print('PIE_OPENING_MARKER', marker, flush=True)
                return
            time.sleep(.1)

    def first_drive(self, current):
        if current != 'Title':
            raise RuntimeError('First-drive observation requires Title before this attempt clicks Begin')
        opening = OpeningEvidence(profile.LOG)
        self.report['opening_evidence'] = {'armed_offset': opening.start_offset,
            'log_identity': opening.tail.identity, 'readiness': 'new_begin_then_handback'}
        self.save()
        self.click('Begin', 'SButton')
        if self.args.skip_boot:
            self.wait_flow('Booting', 5)
            self.inputs.pulse('SpaceBar', 200)
        self.wait_directive(opening)
        if self.args.skip_directive:
            # CIN01 stop_pawn=false starts playback in the same begin call;
            # authored skip_min_s=1 and native SkipHoldS=1. Never call a skip API.
            self.wait(1.2)
            self.inputs.pulse('SpaceBar', 1400)
        self.wait_directive(opening, handback=True)
        self.screenshot('01_controls_at_handoff')
        self.click('SViewport', 'SViewport')
        self.inputs.pulse('W', 900)
        self.wait(1.3)
        self.inputs.axis('MouseX', 1.)
        self.wait(.2)
        self.screenshot('02_first_drive')

    def screenshot(self, label):
        path = self.out/(label+'.png')
        result = self.call('editor_pie_screenshot', {'filename': str(path), 'show_ui': True})
        if result.get('pie_world_count') != 1 or result.get('ambiguous_target_warning'):
            raise RuntimeError('Screenshot has ambiguous PIE target')
        if Path(result.get('filename', '')).resolve() != path.resolve():
            raise RuntimeError('Screenshot path differs')
        end = time.monotonic() + 8
        while time.monotonic() < end:
            result = self.call('editor_pie_screenshot', {'filename': str(path), 'check_only': True})
            if result.get('captured') is True and path.is_file() and path.stat().st_size:
                print('PIE_IMAGE', path, flush=True)
                return
        raise TimeoutError('Screenshot did not complete')

    def click(self, match, kind):
        inventory = self.call('editor_pie_widget_tree', {'filter': match, 'max_depth': 60})
        widgets = inventory.get('widgets', [])
        if inventory.get('count') != len(widgets):
            raise RuntimeError('Widget inventory truncated')
        exact = [w for w in widgets if w.get('type') == kind and w.get('enabled') is True and
                 (kind == 'SViewport' or w.get('text', '').strip().casefold() == match.casefold())]
        if len(exact) != 1:
            raise RuntimeError('Click target is not one exact enabled ' + kind)
        # Native PIEClickWidget explicitly supports prefer_type (its catalog
        # summary omits it); keep dispatch aligned with the exact observed kind.
        result = self.call('editor_pie_click_widget', {'match': match, 'prefer_type': kind})
        if result.get('clicked_type') != kind or result.get('target_enabled') is not True:
            raise RuntimeError('Native click picked a different/disabled control')
        if kind == 'SButton' and result.get('clicked_text', '').strip().casefold() != match.casefold():
            raise RuntimeError('Native click label differs')
        if kind == 'SViewport' and result.get('focused_widget_after') != 'SViewport':
            raise RuntimeError('Game viewport click did not acquire keyboard focus')

    def run(self):
        try:
            self.report['activation'] = activate(self.args.editor_pid, self.args.hwnd)
            current = self.flow()
            self.report['initial_flow'] = current
            if self.args.case == 'startup-skip':
                if current != 'None':
                    raise RuntimeError('Startup skip requires fresh opening FlowState=None')
                self.screenshot('01_opening')
                self.inputs.pulse('SpaceBar', 200)
                self.wait_flow('Title')
                self.screenshot('02_title_after_skip')
            elif self.args.case == 'first-drive-controls':
                self.first_drive(current)
            else:
                if current not in ('Playing', 'Carrier'):
                    raise RuntimeError('Motor observation requires carrier gameplay')
                self.click('SViewport', 'SViewport')
                self.wait(2.5)
                self.recent = ''
                self.tail.read()  # Discard prior tuning starts; require this attempt's marker.
                self.inputs.pulse('Tab', 200)
                end = time.monotonic() + 4
                while 'LogSaskartaMotorResonance: begin tuning' not in self.recent and time.monotonic() < end:
                    self.wait(.1)
                if 'LogSaskartaMotorResonance: begin tuning' not in self.recent:
                    raise RuntimeError('Tab did not begin tuning; inspect parked/cinematic/prompt/focus conditions')
                self.screenshot('01_parked_motor')
                for key, ms in [('E', 200), ('A', 150), ('D', 150)]:
                    self.inputs.pulse(key, ms)
                    self.wait(.3)
                self.screenshot('02_motor_input_feedback')
            self.report['status'] = 'observations_recorded_not_functionally_accepted'
        except BaseException as error:
            self.report.update(status='aborted', error=str(error))
            raise
        finally:
            self.report['cleanup'] = self.inputs.release_all(self.bridge.call)
            self.report['cleanup_confirmed'] = all(row['confirmed'] for row in self.report['cleanup'])
            if not self.report['cleanup_confirmed']:
                self.report['status'] = 'aborted_cleanup_incomplete'
            self.save()
            print('PIE_WALKTHROUGH_REPORT', self.out/'walkthrough.json', flush=True)
            if not self.report['cleanup_confirmed']:
                raise RuntimeError('Input release could not be confirmed; inspect receipt before further input')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', nargs='?', choices=('plan', 'windows', 'run'), default='plan')
    parser.add_argument('--case', choices=CASES, default='startup-skip')
    parser.add_argument('--owner')
    parser.add_argument('--editor-pid', type=int)
    parser.add_argument('--hwnd', type=lambda value: int(value, 0))
    parser.add_argument('--skip-boot', action='store_true')
    parser.add_argument('--skip-directive', action='store_true')
    args = parser.parse_args()
    if args.mode == 'plan':
        print(json.dumps({'case': args.case, 'steps': PLAN[args.case], 'limit_s': LIMITS[args.case],
                          'no_live_calls': True, 'acceptance': 'requires rendered/audio review'}, indent=2))
        return
    if not args.editor_pid:
        parser.error('windows/run requires exact editor PID')
    if args.mode == 'windows':
        print(json.dumps(windows(args.editor_pid), indent=2))
        return
    if not args.owner or not args.hwnd:
        parser.error('run requires current root owner and exact observed window handle')
    if (args.skip_boot or args.skip_directive) and args.case != 'first-drive-controls':
        parser.error('--skip-boot/--skip-directive are only for first-drive-controls')
    Walkthrough(args).run()


if __name__ == '__main__':
    main()
