"""Tests for Tools/Look/measure_look.py, the palette gate for look captures.

The concept board is dark and desaturated. A capture passes when:
  - mean luminance (Rec.709 luma of the sRGB 8-bit values, 0..1) is in 0.14..0.26;
  - the median HSV saturation of its mid-tone pixels (luma 0.25..0.75) is at most 0.30.

Synthetic captures made here with numpy and Pillow:
  - "board": charcoal, umber and taupe in board-like proportions -> passes both;
  - "sepia": everything in the accent orange -> too bright and too saturated;
  - "black": no light at all -> too dark, with no mid-tones (median reported as 0).

Run: python -m pytest Tools/Look/tests -q -p no:cacheprovider --basetemp <scratch dir>
"""
import pathlib
import subprocess
import sys

import numpy as np
import pytest
from PIL import Image

LOOK = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = LOOK / "measure_look.py"
sys.path.insert(0, str(LOOK))

W, H = 200, 100
CHARCOAL = (0x2A, 0x28, 0x26)
UMBER = (0x3B, 0x31, 0x2B)
TAUPE = (0x6E, 0x5F, 0x55)
ACCENT = (0xC8, 0x70, 0x3A)


def luma(c):
    return (0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]) / 255.0


def _save(tmp_path, name, array):
    path = tmp_path / name
    Image.fromarray(array.astype(np.uint8), "RGB").save(path)
    return path


@pytest.fixture
def board_png(tmp_path):
    img = np.zeros((H, W, 3), dtype=np.uint8)
    img[:60] = CHARCOAL   # 60 %
    img[60:85] = UMBER    # 25 %
    img[85:] = TAUPE      # 15 %
    return _save(tmp_path, "board.png", img)


@pytest.fixture
def sepia_png(tmp_path):
    return _save(tmp_path, "sepia.png", np.full((H, W, 3), ACCENT, dtype=np.uint8))


@pytest.fixture
def black_png(tmp_path):
    return _save(tmp_path, "black.png", np.zeros((H, W, 3), dtype=np.uint8))


def test_board_values_match_hand_computation(board_png):
    import measure_look
    m = measure_look.measure(board_png)
    expected_mean = 0.60 * luma(CHARCOAL) + 0.25 * luma(UMBER) + 0.15 * luma(TAUPE)
    assert m["mean_luminance"] == pytest.approx(expected_mean, abs=1e-4)
    # only taupe (luma ~0.38) is a mid-tone; its HSV saturation is (max - min) / max
    assert m["midtone_saturation_median"] == pytest.approx((0x6E - 0x55) / 0x6E, abs=1e-4)
    assert m["midtone_fraction"] == pytest.approx(0.15, abs=1e-4)
    assert m["pass"] is True


def test_sepia_fails_both_rules(sepia_png):
    import measure_look
    m = measure_look.measure(sepia_png)
    assert m["mean_luminance"] > 0.26
    assert m["midtone_saturation_median"] > 0.30
    assert m["pass"] is False


def test_black_fails_and_has_no_midtones(black_png):
    import measure_look
    m = measure_look.measure(black_png)
    assert m["mean_luminance"] < 0.14
    assert m["midtone_fraction"] == 0.0
    assert m["midtone_saturation_median"] == 0.0
    assert m["pass"] is False


def test_cli_prints_both_numbers_and_exit_code(board_png, sepia_png):
    r = subprocess.run([sys.executable, str(SCRIPT), str(board_png)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "L=" in r.stdout and "S_mid=" in r.stdout and "PASS" in r.stdout
    r = subprocess.run([sys.executable, str(SCRIPT), str(board_png), str(sepia_png)],
                       capture_output=True, text=True)
    assert r.returncode == 1
    assert "FAIL" in r.stdout


def test_alpha_channel_is_ignored(tmp_path):
    import measure_look
    rgba = np.zeros((H, W, 4), dtype=np.uint8)
    rgba[..., :3] = TAUPE
    rgba[..., 3] = 0          # a render-target export can carry alpha 0
    p = tmp_path / "rgba.png"
    Image.fromarray(rgba, "RGBA").save(p)
    assert measure_look.measure(p)["mean_luminance"] == pytest.approx(luma(TAUPE), abs=1e-4)
