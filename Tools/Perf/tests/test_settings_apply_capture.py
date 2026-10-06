"""Offline UI matching/input/recorder safeguards; no editor connection."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import settings_apply_capture as settings


def widget(kind, text='', x=10, y=20, width=100, height=20, **extra):
    return dict(type=kind, text=text, x=x, y=y, width=width, height=height,
                center_y=y+height/2, enabled=True, **extra)


class SettingsCaptureContracts(unittest.TestCase):
    def open_trial(self, flow='Title', existing=None):
        trial = settings.SettingsTrial.__new__(settings.SettingsTrial)
        trial.args = SimpleNamespace(editor_pid=123, hwnd=456)
        trial.out = Path('unused-offline-report')
        trial.report = {'cleanup': [], 'csv_ownership': 'not_requested'}
        trial.flow = Mock(return_value=flow)
        trial.call = Mock(return_value={'count': len(existing or []), 'widgets': existing or []})
        trial.click = Mock()
        trial.observe_master = Mock(return_value=(.8, [], {}))
        trial.require_apply = Mock()
        trial.screenshot = Mock()
        trial.save = Mock()
        trial.bridge = SimpleNamespace(call=Mock(side_effect=AssertionError('No direct bridge input')))
        trial.inputs = SimpleNamespace(release_all=Mock(return_value=[]))
        trial.start_csv = Mock(side_effect=AssertionError('Open must not start CSV'))
        trial.restore_audio = Mock(side_effect=AssertionError('Open must not change audio'))
        return trial

    def test_open_follows_exact_normal_buttons_without_changing_values_or_csv(self):
        for flow in ('Title', 'Paused'):
            with self.subTest(flow=flow):
                trial = self.open_trial(flow)
                with patch.object(settings.walk, 'activate', return_value={}), patch('builtins.print'):
                    self.assertEqual(trial.open_audio_menu(), 0)
                self.assertEqual(trial.click.call_args_list,
                                 [unittest.mock.call('Settings', 'SButton'), unittest.mock.call('Audio', 'SButton')])
                self.assertEqual(trial.report['baseline_master'], .8)
                self.assertEqual(trial.report['csv_ownership'], 'not_requested')
                self.assertFalse(trial.report['settings_values_changed'])
                trial.start_csv.assert_not_called()
                trial.restore_audio.assert_not_called()

    def test_open_refuses_playing_before_any_input(self):
        trial = self.open_trial('Playing')
        with patch.object(settings.walk, 'activate', return_value={}), patch('builtins.print'):
            self.assertEqual(trial.open_audio_menu(), 2)
        trial.click.assert_not_called()
        trial.call.assert_not_called()

    def test_open_refuses_existing_settings_even_if_apply_is_disabled(self):
        apply = widget('SButton', 'Apply')
        apply['enabled'] = False
        trial = self.open_trial(existing=[apply])
        with patch.object(settings.walk, 'activate', return_value={}), patch('builtins.print'):
            self.assertEqual(trial.open_audio_menu(), 2)
        trial.click.assert_not_called()
        self.assertIn('already open', trial.report['reason'])

    def test_open_failure_preserves_menu_and_reports_incomplete(self):
        trial = self.open_trial()
        trial.click.side_effect = [None, RuntimeError('Audio button ambiguous')]
        with patch.object(settings.walk, 'activate', return_value={}), patch('builtins.print'):
            self.assertEqual(trial.open_audio_menu(), 2)
        self.assertEqual(trial.report['status'], 'aborted')
        trial.restore_audio.assert_not_called()
        trial.screenshot.assert_not_called()
        trial.inputs.release_all.assert_called_once()

    def test_master_value_uses_exact_row_and_rejects_conflicting_or_missing(self):
        outer = widget('SBox', 'Master 1.00', width=600)
        inner = widget('SHorizontalBox', 'Master 1.00', width=300)
        self.assertEqual(settings.master_value([outer, inner]), (1., inner))
        for rows in ([widget('STextBlock', '1.00')], [inner, widget('SBox', 'Master 0.95')],
                     [widget('SBox', 'Master 1.00 Ambience 1.00')]):
            with self.subTest(rows=rows), self.assertRaises(RuntimeError):
                settings.master_value(rows)

    def test_master_slider_requires_one_same_row_not_first_slider(self):
        label = widget('STextBlock', 'Master')
        correct = widget('SSlider', x=130, width=250)
        elsewhere = widget('SSlider', x=130, y=60, width=250)
        self.assertEqual(settings.master_slider([label], [elsewhere, correct]), correct)
        with self.assertRaises(RuntimeError):
            settings.master_slider([label], [correct, dict(correct)])
        with self.assertRaises(RuntimeError):
            settings.master_slider([label], [elsewhere])

    def test_truncation_is_not_valid_widget_inventory(self):
        with self.assertRaises(RuntimeError):
            settings.rows({'count': 2, 'widgets': [{}]})

    def test_endpoint_requires_slider_focus_before_any_keyboard_input(self):
        trial = settings.SettingsTrial.__new__(settings.SettingsTrial)
        trial.report = {}
        label = widget('STextBlock', 'Master')
        trial.observe_master = lambda: (1., [label], {})
        calls = []
        def call(command, params):
            calls.append((command, params))
            if command == 'editor_pie_widget_tree':
                return {'count': 1, 'widgets': [widget('SSlider', x=130, width=250)]}
            return {'dispatched': True, 'focused_widget_after': 'SButton'}
        trial.call = call
        trial.require_master = lambda _: self.fail('Should reject wrong focus before next observation')
        with self.assertRaisesRegex(RuntimeError, 'keyboard focus'):
            trial.focus_master_endpoint()
        self.assertTrue(trial.restore_needed, 'Ambiguous click must leave restoration outstanding')
        self.assertEqual(calls[-1][1]['x'], 378.)
        self.assertFalse(any(command == 'editor_pie_press_key' for command, _ in calls))

    def test_audio_change_requires_one_then_exact_step(self):
        trial = settings.SettingsTrial.__new__(settings.SettingsTrial)
        trial.report = {}
        events = []
        trial.require_master = lambda value: events.append(('read', value))
        trial.focus_master_endpoint = lambda: events.append(('focus', 1.))
        trial.inputs = SimpleNamespace(pulse=lambda key, ms: events.append(('pulse', key, ms)))
        trial.change_audio()
        self.assertEqual(events, [('read', 1.), ('focus', 1.), ('pulse', 'Enter', 80),
                                  ('pulse', 'Left', 80), ('read', .95)])

    def test_no_blind_restore_after_transport_failure(self):
        trial = settings.SettingsTrial.__new__(settings.SettingsTrial)
        trial.restore_needed = True
        trial.transport_failed = True
        trial.focus_master_endpoint = lambda: self.fail('Do not send input after ambiguous transport failure')
        with self.assertRaisesRegex(RuntimeError, 'root inspection'):
            trial.restore_audio()

    def test_refused_csv_never_stops_recorder(self):
        trial = settings.SettingsTrial.__new__(settings.SettingsTrial)
        trial.report = {'csv_ownership': 'refused_existing_capture', 'cleanup': []}
        trial.bridge = SimpleNamespace(console=lambda *_: self.fail('Recorder is unowned'))
        trial.stop_owned_csv()
        self.assertIn('unowned', trial.report['cleanup'][0]['action'])

    def test_conflicting_guid_prevents_owned_stop(self):
        trial = settings.SettingsTrial.__new__(settings.SettingsTrial)
        trial.report = {'csv_ownership': 'confirmed_new_guid', 'cleanup': []}
        trial.bridge = SimpleNamespace(console=lambda *_: self.fail('Conflicting recorder must not stop'))
        def conflict():
            trial.report['csv_ownership'] = 'conflicting_new_capture'
            raise RuntimeError('Conflicting GUID')
        trial.read_log = conflict
        trial.stop_owned_csv()
        self.assertIn('Conflicting', trial.report['cleanup'][0]['error'])


if __name__ == '__main__':
    unittest.main()
