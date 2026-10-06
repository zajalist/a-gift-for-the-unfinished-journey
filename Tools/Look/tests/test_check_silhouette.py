"""Tests for Tools/Look/check_silhouette.py.

Two synthetic captures are made here with numpy and Pillow:
  - a flat image, where the mountain box and the sky box have the same
    luminance, which must print a difference below 0.08 and fail;
  - a contrasted image, dark mountain under a brighter sky, which must pass.

Run: python -m pytest Tools/Look/tests -q
"""
import pathlib
import subprocess
import sys

import numpy as np
import pytest
from PIL import Image

LOOK = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = LOOK / "check_silhouette.py"
sys.path.insert(0, str(LOOK))

W, H = 320, 180
MOUNTAIN_BOX = "120,100,200,160"
SKY_BOX = "120,40,200,90"


def _save(tmp_path, name, array):
    path = tmp_path / name
    Image.fromarray(array.astype(np.uint8), "RGB").save(path)
    return path


def _run(png):
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(png), MOUNTAIN_BOX, SKY_BOX],
        capture_output=True, text=True,
    )


def _printed_diff(stdout):
    first = stdout.strip().splitlines()[0]
    return float(first.split()[0])


@pytest.fixture
def flat_png(tmp_path):
    img = np.full((H, W, 3), (0x3B, 0x31, 0x2B), dtype=np.uint8)
    return _save(tmp_path, "flat.png", img)


@pytest.fixture
def contrasted_png(tmp_path):
    img = np.zeros((H, W, 3), dtype=np.uint8)
    img[:95] = (0x6E, 0x5F, 0x55)   # taupe sky
    img[95:] = (0x2A, 0x28, 0x26)   # charcoal mountain
    return _save(tmp_path, "contrast.png", img)


def test_flat_image_prints_below_threshold_and_fails(flat_png):
    r = _run(flat_png)
    assert _printed_diff(r.stdout) < 0.08
    assert "FAIL" in r.stdout
    assert r.returncode == 1


def test_contrasted_image_passes(contrasted_png):
    r = _run(contrasted_png)
    assert _printed_diff(r.stdout) >= 0.08
    assert "PASS" in r.stdout
    assert r.returncode == 0


def test_luminance_difference_matches_hand_value(contrasted_png):
    import check_silhouette
    diff = check_silhouette.luminance_difference(
        contrasted_png, check_silhouette.parse_box(MOUNTAIN_BOX),
        check_silhouette.parse_box(SKY_BOX))
    luma = lambda c: (0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]) / 255.0
    expected = abs(luma((0x6E, 0x5F, 0x55)) - luma((0x2A, 0x28, 0x26)))
    assert diff == pytest.approx(expected, abs=1e-6)


def test_box_outside_image_is_rejected(contrasted_png):
    r = subprocess.run(
        [sys.executable, str(SCRIPT), str(contrasted_png), "300,100,400,160", SKY_BOX],
        capture_output=True, text=True,
    )
    assert r.returncode == 2
