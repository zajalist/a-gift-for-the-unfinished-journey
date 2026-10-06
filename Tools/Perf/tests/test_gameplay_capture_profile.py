"""Offline recorder ownership guards; no editor connection."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import gameplay_acceptance as capture


class RecorderOwnership(unittest.TestCase):
    def test_no_prior_capture_and_completed_capture_are_idle(self):
        capture.require_idle_csv('ordinary log')
        capture.require_idle_csv('LogCsvProfiler: Display: Capture Starting\n'
            'LogCsvProfiler: Display: Capture started. CSV ID: ABC\n'
            'LogCsvProfiler: Display: Capture Ended. Writing CSV to file : old.csv\n')

    def test_active_or_pending_capture_blocks_before_start(self):
        for text in ['LogCsvProfiler: Display: Capture Starting\n',
                     'LogCsvProfiler: Display: Capture started. CSV ID: ABC\n',
                     'LogCsvProfiler: Display: Capture Ended. Writing CSV to file : old.csv\n'
                     'LogCsvProfiler: Display: Capture Starting\n']:
            with self.assertRaises(RuntimeError):capture.require_idle_csv(text)

    def test_refused_start_never_owns_old_or_delayed_capture(self):
        for reason in ['Capture start requested, but a capture was already running',
                       'BeginCapture() called, but there is already a pending start command. Ignoring!']:
            report={'csv_ownership':'requested_unconfirmed'}
            with self.assertRaises(RuntimeError):
                capture.observe_csv(report,'Capture started. CSV ID: ABC\n'+reason)
            self.assertEqual(report['csv_ownership'],'refused_existing_capture')
            self.assertNotIn('csv_id',report)

    def test_delayed_guid_confirms_only_our_one_new_capture(self):
        report={'csv_ownership':'requested_unconfirmed'}
        capture.observe_csv(report,'no new evidence')
        self.assertEqual(report['csv_ownership'],'requested_unconfirmed')
        capture.observe_csv(report,'Capture started. CSV ID: ABC-123\n')
        self.assertEqual(report['csv_ownership'],'confirmed_new_guid')
        with self.assertRaises(RuntimeError):capture.observe_csv(report,'Capture started. CSV ID: DEF-456\n')
        self.assertEqual(report['csv_ownership'],'conflicting_new_capture')


class WalkthroughInputOwnership(unittest.TestCase):
    def test_ambiguous_press_still_releases_exact_owned_key(self):
        import pie_input_walkthrough as walk
        calls = []
        def fail(command, params):
            calls.append((command, params))
            raise TimeoutError('ambiguous input result')
        ledger = walk.InputLedger(fail)
        with self.assertRaises(TimeoutError):
            ledger.pulse('W', 900)
        clean = []
        result = ledger.release_all(lambda command, params, timeout: clean.append((command, params, timeout)) or {'dispatched': True})
        self.assertEqual(clean, [('editor_pie_press_key', {'key': 'W', 'event': 'released'}, 2)])
        self.assertTrue(result[0]['confirmed'])
        self.assertEqual(calls[0][1]['event'], 'pressed_and_released')

    def test_cleanup_failure_does_not_skip_other_owned_inputs(self):
        import pie_input_walkthrough as walk
        ledger = walk.InputLedger(lambda command, params: {'dispatched': True, 'release_scheduled': True})
        ledger.pulse('E', 200)
        ledger.pulse('A', 150)
        ledger.axis('MouseX', 1)
        calls = []
        def cleanup(command, params, timeout):
            calls.append((command, params))
            if params['key'] == 'A': raise TimeoutError('release failed')
            return {'dispatched': True, 'key': params['key'], 'value': 0}
        result = ledger.release_all(cleanup)
        self.assertEqual([r[1]['key'] for r in calls], ['A', 'E', 'MouseX'])
        self.assertEqual([r['confirmed'] for r in result], [False, True, True])

    def test_long_hold_and_unbounded_axis_are_rejected_before_dispatch(self):
        import pie_input_walkthrough as walk
        calls = []
        ledger = walk.InputLedger(lambda *args: calls.append(args))
        for ms in (0, 1501, 99999):
            with self.assertRaises(ValueError): ledger.pulse('W', ms)
        for key, value in [('MouseX', 2), ('Gamepad_LeftX', 1)]:
            with self.assertRaises(ValueError): ledger.axis(key, value)
        self.assertEqual(calls, [])
        self.assertEqual(ledger.keys, set())
        self.assertEqual(ledger.axes, set())

    def test_other_window_of_same_editor_pid_is_not_foreground_proof(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        import pie_input_walkthrough as walk
        trial = walk.Walkthrough.__new__(walk.Walkthrough)
        trial.args = SimpleNamespace(editor_pid=123, hwnd=10)
        trial.deadline = float('inf')
        trial.recent = ''
        trial.tail = SimpleNamespace(read=lambda: '')
        with patch.object(walk.profile, 'host_sample', return_value={'editor_foreground': True, 'available_ram_fraction': .5}), \
             patch.object(walk.ctypes.windll.user32, 'GetForegroundWindow', return_value=20):
            with self.assertRaisesRegex(RuntimeError, 'foreground'):
                trial.guard()

    def test_viewport_click_requires_actual_keyboard_focus(self):
        import pie_input_walkthrough as walk
        trial = walk.Walkthrough.__new__(walk.Walkthrough)
        calls = []
        def call(command, params):
            calls.append((command, params))
            if command == 'editor_pie_widget_tree':
                return {'count': 1, 'widgets': [{'type': 'SViewport', 'enabled': True}]}
            return {'clicked_type': 'SViewport', 'target_enabled': True, 'focused_widget_after': 'SButton'}
        trial.call = call
        with self.assertRaisesRegex(RuntimeError, 'keyboard focus'):
            trial.click('SViewport', 'SViewport')
        self.assertEqual(calls[-1][1]['prefer_type'], 'SViewport')


class OpeningHandbackEvidence(unittest.TestCase):
    def test_old_complete_and_partial_markers_cannot_prove_new_handback(self):
        from tempfile import TemporaryDirectory
        import pie_input_walkthrough as walk
        for ending in ('\n', ''):
            with self.subTest(ending=repr(ending)), TemporaryDirectory() as folder:
                path = Path(folder)/'editor.log'
                path.write_text(walk.DIRECTIVE_BEGIN + '(stop pawn 0)\n' + walk.DIRECTIVE_HANDBACK + ending)
                proof = walk.OpeningEvidence(path)
                with path.open('a') as stream: stream.write('\nFlowState=Playing\n')
                proof.read()
                self.assertFalse(proof.begun)
                self.assertFalse(proof.handed_back)
                with path.open('a') as stream: stream.write(walk.DIRECTIVE_HANDBACK + '\n')
                proof.read()
                self.assertFalse(proof.handed_back, 'A handback without this attempt\'s begin is insufficient')
                with path.open('a') as stream: stream.write(walk.DIRECTIVE_BEGIN + '(stop pawn 0)\n')
                proof.read()
                self.assertTrue(proof.begun)
                self.assertFalse(proof.handed_back, 'An earlier handback cannot follow a later begin')
                with path.open('a') as stream: stream.write(walk.DIRECTIVE_HANDBACK[:25])
                proof.read()
                self.assertFalse(proof.handed_back)
                with path.open('a') as stream: stream.write(walk.DIRECTIVE_HANDBACK[25:] + '\n')
                proof.read()
                self.assertTrue(proof.handed_back)

    def test_already_playing_is_rejected_before_any_input_or_observation(self):
        import pie_input_walkthrough as walk
        trial = walk.Walkthrough.__new__(walk.Walkthrough)
        with self.assertRaisesRegex(RuntimeError, 'requires Title'):
            trial.first_drive('Playing')

    def test_normal_and_skip_capture_immediately_after_proven_handback(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        import pie_input_walkthrough as walk
        for skip in (False, True):
            with self.subTest(skip=skip):
                events = []
                proof = SimpleNamespace(start_offset=123, tail=SimpleNamespace(identity=(1, 2)))
                trial = walk.Walkthrough.__new__(walk.Walkthrough)
                trial.args = SimpleNamespace(skip_boot=skip, skip_directive=skip)
                trial.report = {}
                trial.save = lambda: events.append(('save',))
                trial.click = lambda *args: events.append(('click',) + args)
                trial.wait_flow = lambda *args: events.append(('flow',) + args)
                trial.wait_directive = lambda value, handback=False: events.append(('marker', handback))
                trial.screenshot = lambda label: events.append(('screenshot', label))
                trial.wait = lambda seconds: events.append(('wait', seconds))
                trial.inputs = SimpleNamespace(
                    pulse=lambda *args: events.append(('key',) + args),
                    axis=lambda *args: events.append(('axis',) + args))
                with patch.object(walk, 'OpeningEvidence', return_value=proof):
                    trial.first_drive('Title')
                handback = events.index(('marker', True))
                self.assertEqual(events[handback + 1], ('screenshot', '01_controls_at_handoff'))
                self.assertLess(events.index(('click', 'Begin', 'SButton')), events.index(('marker', False)))
                self.assertGreater(events.index(('key', 'W', 900)), handback)
                self.assertFalse(any(event[:2] == ('flow', 'Playing') for event in events))
                self.assertEqual(trial.report['opening_evidence']['armed_offset'], 123)
                if skip:
                    self.assertLess(events.index(('marker', False)), events.index(('key', 'SpaceBar', 1400)))
                    self.assertLess(events.index(('key', 'SpaceBar', 1400)), handback)
                else:
                    self.assertFalse(any(event[:2] == ('key', 'SpaceBar') for event in events))

    def test_first_drive_budget_covers_boot_full_directive_blend_and_capture(self):
        import json
        import pie_input_walkthrough as walk
        story = json.loads((walk.ROOT/'docs/story/story-events.json').read_text(encoding='utf-8'))
        directive = story['cinematics']['CIN_01_DIRECTIVE']
        self.assertGreaterEqual(walk.LIMITS['first-drive-controls'],
                                30 + directive['duration_s'] + directive['blend_out_s'] + 15)
        self.assertFalse(directive['stop_pawn'])
        self.assertEqual(directive['skip'], 'HoldAlways')
        self.assertLessEqual(directive['skip_min_s'], 1.2)
        self.assertEqual(walk.LIMITS['parked-motor'], 55)


if __name__=='__main__':unittest.main()
