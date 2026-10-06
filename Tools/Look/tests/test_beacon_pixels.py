"""Tests for Tools/Look/beacon_pixels.py: where the High Voice lands in a capture, and how bright.

Projection follows Unreal's camera convention: X forward at yaw 0, +Y to the right,
+Z up; horizontal field of view; square pixels.

Run: python -m pytest Tools/Look/tests -q -p no:cacheprovider --basetemp <scratch dir>
"""
import math
import pathlib
import sys

import numpy as np
import pytest
from PIL import Image

LOOK = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LOOK))

W, H = 400, 200


def test_point_straight_ahead_is_the_centre():
    from beacon_pixels import project
    cam = (0.0, 0.0, 0.0, 0.0, 0.0, 90.0)
    x, y = project(cam, (1000.0, 0.0, 0.0), W, H)
    assert x == pytest.approx(W / 2) and y == pytest.approx(H / 2)


def test_right_and_up_follow_unreal_axes():
    from beacon_pixels import project
    cam = (0.0, 0.0, 0.0, 0.0, 0.0, 90.0)
    # 45 deg to the right (+Y) lands on the right edge; above (+Z) is a smaller row index.
    x, _ = project(cam, (1000.0, 1000.0, 0.0), W, H)
    assert x == pytest.approx(W)
    _, y = project(cam, (1000.0, 0.0, 100.0), W, H)
    assert y == pytest.approx(H / 2 - 0.1 * W / 2)


def test_yaw_and_pitch_rotate_the_view():
    from beacon_pixels import project
    # Looking along +Y (yaw 90) and pitched up 10 deg: a point 10 deg up along +Y is centred.
    cam = (0.0, 0.0, 0.0, 10.0, 90.0, 60.0)
    p = (0.0, 1000.0, 1000.0 * math.tan(math.radians(10.0)))
    x, y = project(cam, p, W, H)
    assert x == pytest.approx(W / 2, abs=1e-6) and y == pytest.approx(H / 2, abs=1e-6)


def test_point_behind_the_camera_is_none():
    from beacon_pixels import project
    assert project((0.0, 0.0, 0.0, 0.0, 0.0, 90.0), (-10.0, 0.0, 0.0), W, H) is None


def test_peak_finds_a_bright_dot_and_its_contrast(tmp_path):
    from beacon_pixels import peak
    img = np.full((H, W, 3), 40, np.uint8)
    img[120:124, 300:304] = (250, 200, 150)
    f = tmp_path / "dot.png"
    Image.fromarray(img).save(f)
    arr = np.asarray(Image.open(f).convert("RGB"))
    r = peak(arr, 295, 118, radius=12)
    assert (r["x"], r["y"]) in {(x, y) for x in range(300, 304) for y in range(120, 124)}
    assert r["rgb"] == (250, 200, 150)
    assert r["luma"] > 0.8 and r["background_luma"] == pytest.approx(40 / 255, abs=0.01)
