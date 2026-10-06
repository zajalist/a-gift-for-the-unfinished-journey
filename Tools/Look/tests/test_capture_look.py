"""Offline checks for capture_look.py's temporary skylight workaround."""
import pathlib
import sys

import pytest

LOOK = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LOOK))

import capture_look as cl  # noqa: E402


@pytest.mark.parametrize("failure_script", ["SETUP_SENTINEL", "EXPORT_SENTINEL"])
def test_original_realtime_skylight_flag_restored_after_capture_failure(monkeypatch, failure_script):
    calls = []

    def fake_python_run(script):
        calls.append(script)
        if "SKY_STATE" in script:
            return True, "SKY_STATE [('SkyLight', True)]", ""
        if "SKY_RESTORE" in script:
            assert "states = [('SkyLight', True)]" in script
            return True, "SKY_RESTORE restored=['SkyLight'] missing=[]", ""
        if "CAPTURE_CLEANUP" in script:
            return True, "CAPTURE_CLEANUP removed=[]", ""
        if failure_script in script:
            return False, "", "injected failure"
        return True, "", ""

    monkeypatch.setattr(cl, "python_run", fake_python_run)
    ok, out, err = cl.run_capture_scripts(
        "SETUP_SENTINEL", "PUMP_SENTINEL", "EXPORT_SENTINEL", 0.0, False)

    assert not ok
    assert "injected failure" in err
    assert "SKY_RESTORE restored=['SkyLight'] missing=[]" in out
    assert calls[-1].lstrip().startswith("import unreal") and 'print("SKY_RESTORE' in calls[-1]
    assert any("CAPTURE_CLEANUP" in script for script in calls)


def test_skylight_prepare_queues_static_recapture_and_reports_state_before_mutating():
    script = cl.SKY_PREPARE_SCRIPT
    assert cl.check_banned(script) == script
    assert script.index('print("SKY_STATE') < script.index("c.set_real_time_capture(False)")
    assert "c.recapture_sky()" in script
    restore = cl.SKY_RESTORE_SCRIPT.replace("__STATES__", repr([("SkyLight", True)]))
    assert cl.check_banned(restore) == restore
    assert "c.set_real_time_capture(was_realtime)" in restore
