import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import cloud_flicker as cf  # noqa: E402


def test_box_blur_keeps_constant_and_mean():
    img = np.full((20, 30), 7.0)
    assert np.allclose(cf.box_blur(img, 5), 7.0)
    rng = np.random.default_rng(1)
    noise = rng.normal(0, 10, (64, 64))
    assert cf.box_blur(noise, 9).std() < noise.std() / 5


def test_grain_counts_as_flicker_not_drift():
    rng = np.random.default_rng(2)
    base = np.tile(np.linspace(0, 200, 128), (96, 1))
    a = base + rng.normal(0, 8, base.shape)
    b = base + rng.normal(0, 8, base.shape)
    mask = cf.cloud_mask(*a.shape, bottom_frac=1.0)
    raw, flicker, drift = cf.split_difference(a, b, mask)
    assert flicker > 5 * drift
    assert raw > 5


def test_smooth_shift_counts_as_drift_not_flicker():
    x = np.linspace(0, 6 * np.pi, 256)
    a = np.tile(100 + 60 * np.sin(x / 4), (64, 1))
    b = np.tile(100 + 60 * np.sin((x + 0.4) / 4), (64, 1))
    mask = cf.cloud_mask(*a.shape, bottom_frac=1.0)
    _, flicker, drift = cf.split_difference(a, b, mask)
    assert drift > 3 * flicker
    assert drift > 1


def test_cloud_mask_rows():
    m = cf.cloud_mask(100, 10, bottom_frac=0.85)
    assert m[:85].all() and not m[85:].any()
