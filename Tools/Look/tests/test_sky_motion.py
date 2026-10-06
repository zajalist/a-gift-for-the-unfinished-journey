"""Tests for Tools/Look/sky_motion.py: the title-sky motion and variation metrics (task SKY).

Synthetic frames made here with numpy and Pillow; no editor.

Run: python -m pytest Tools/Look/tests -q -p no:cacheprovider --basetemp <scratch dir>
"""
import pathlib
import sys

import numpy as np
import pytest
from PIL import Image

LOOK = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LOOK))

import sky_motion as sm  # noqa: E402

H, W = 100, 200


def _frame(value, rgb=(1.0, 1.0, 1.0)):
    return np.ones((H, W, 3)) * np.array(rgb) * value


def test_sky_mask_is_the_top_band_without_the_beam_column():
    m = sm.sky_mask(H, W)
    assert m[: int(H * sm.SKY_BOTTOM_FRAC)].any() and not m[int(H * sm.SKY_BOTTOM_FRAC):].any()
    beam_x = int(W * (sm.BEAM_COLUMN_FRAC[0] + sm.BEAM_COLUMN_FRAC[1]) / 2)
    assert not m[:, beam_x].any()
    assert m[0, 0] and m[0, W - 1]


def test_frame_difference_counts_only_the_sky():
    m = sm.sky_mask(H, W)
    a = _frame(100.0)
    b = a.copy()
    b[int(H * 0.8):] = 0.0            # change below the sky only
    assert sm.frame_difference(a, b, m) == 0.0
    c = a + 10.0                      # uniform +10 on every channel = +10 luma
    assert sm.frame_difference(a, c, m) == pytest.approx(10.0)


def test_hue_of_primaries_and_grey():
    m = np.ones((H, W), dtype=bool)
    assert sm.mean_hue_deg(_frame(200.0, (1, 0, 0)), m) == pytest.approx(0.0, abs=1e-6)
    assert sm.mean_hue_deg(_frame(200.0, (0, 1, 0)), m) == pytest.approx(120.0, abs=1e-6)
    assert sm.mean_hue_deg(_frame(200.0, (0, 0, 1)), m) == pytest.approx(240.0, abs=1e-6)
    assert sm.mean_hue_deg(_frame(120.0), m) is None


def test_hue_spread_wraps_around_360():
    assert sm.hue_spread([350.0, 10.0]) == pytest.approx(20.0)
    assert sm.hue_spread([10.0, 20.0, 40.0]) == pytest.approx(30.0)
    assert sm.hue_spread([None, 30.0]) == 0.0


def test_variation_reports_luma_spread_and_pattern_change():
    m = sm.sky_mask(H, W)
    same = [_frame(100.0)] * 3
    v = sm.variation(same, m)
    assert v["luma_spread"] == 0.0 and v["pixel_luma_std"] == 0.0
    swing = [_frame(51.0), _frame(102.0), _frame(153.0)]
    v = sm.variation(swing, m)
    assert v["luma_spread"] == pytest.approx(0.4, abs=1e-3)


def test_wind_offset_follows_the_sequence_ramp_and_clamps():
    assert sm.wind_offset_at(0.0, 0.0, 3.0, 40.0) == 0.0
    assert sm.wind_offset_at(20.0, 0.0, 3.0, 40.0) == pytest.approx(1.5)
    assert sm.wind_offset_at(55.0, 0.0, 3.0, 40.0) == 3.0


def test_measure_and_strip_read_the_capture_files(tmp_path):
    for t in sm.TIMES:
        pa, pb = sm.pair_paths("x", t, tmp_path)
        Image.fromarray(np.full((H, W, 3), 80, np.uint8)).save(pa)
        Image.fromarray(np.full((H, W, 3), 90, np.uint8)).save(pb)
    r = sm.measure("x", tmp_path)
    assert r["motion_mean"] == pytest.approx(10.0)
    assert r["variation"]["luma_spread"] == 0.0
    s = sm.strip("x", tmp_path, width=50)
    assert Image.open(s).size == (150, 25)


def test_the_title_sequence_holds_wind_offset_flat():
    """Task SKY: the WindOffset ramp was the main speed driver (see build_title_sequence.py)."""
    sys.path.insert(0, str(LOOK.parents[1] / "Tools" / "Story"))
    import build_title_sequence as bts
    assert bts.WIND_OFFSET_START == bts.WIND_OFFSET_END
