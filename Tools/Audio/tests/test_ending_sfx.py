import numpy as np
import pytest

import prepare_ending_sfx as ending


@pytest.mark.parametrize('name', ending.SOUNDS)
def test_prepared_cue_is_finite_bounded_and_correct_duration(name):
    audio = ending.render(name)
    duration, _, peak, _ = ending.SOUNDS[name]
    assert audio.shape == (round(duration*ending.RATE), 2)
    assert np.isfinite(audio).all()
    assert np.max(np.abs(audio)) == pytest.approx(peak)
    assert np.max(np.abs(audio)) < 1
    assert np.all(audio[0] == 0) and np.all(audio[-1] == 0)


def test_only_channel_hiss_loops_and_tape_room_finishes_before_cut(tmp_path):
    assert [name for name, spec in ending.SOUNDS.items() if spec[1]] == ['SFX_OpenChannelHiss']
    # Tape-room starts at 186 s and must end before the 207 s cinematic cut.
    assert ending.SOUNDS['SFX_TapeRoom_A5'][0] < 207-186
    for name in ending.SOUNDS:
        imported = ending.import_code(name, tmp_path/(name+'.wav'))
        saved = ending.save_code(name)
        compile(imported, name, 'exec')
        compile(saved, name, 'exec')
        assert 'save_loaded_asset' not in imported
        assert 'import_asset_tasks' not in saved
