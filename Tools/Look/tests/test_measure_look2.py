"""Offline checks for Tools/Look/measure_look2.py (world sprint, task LOOK2).

    python -m pytest Tools/Look/tests/test_measure_look2.py -q
"""
import math
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import measure_look2 as M  # noqa: E402


def test_projection_centre_and_axes():
    cam = dict(x=0.0, y=0.0, z=0.0, pitch=0.0, yaw=0.0, hfov=90.0, w=200, h=100)
    u, v, ok = M.project(np.array([[1000.0, 0.0, 0.0]]), cam)
    assert ok[0] and abs(u[0] - 100.0) < 1e-9 and abs(v[0] - 50.0) < 1e-9
    # +Y is to the right in UE (left-handed), +Z is up (smaller row)
    u, v, ok = M.project(np.array([[1000.0, 1000.0, 0.0], [1000.0, 0.0, 500.0]]), cam)
    assert abs(u[0] - 200.0) < 1e-9 and abs(v[1] - 0.0) < 1e-9
    # behind the camera is rejected
    assert not M.project(np.array([[-10.0, 0.0, 0.0]]), cam)[2][0]


def test_projection_with_yaw_and_pitch():
    cam = dict(x=0.0, y=0.0, z=0.0, pitch=10.0, yaw=90.0, hfov=70.0, w=1920, h=1080)
    # a point straight along the view direction lands in the centre
    f = (math.cos(math.radians(10)) * math.cos(math.radians(90)), math.cos(math.radians(10)) * math.sin(math.radians(90)),
         math.sin(math.radians(10)))
    u, v, ok = M.project(np.array([[f[0] * 5000, f[1] * 5000, f[2] * 5000]]), cam)
    assert ok[0] and abs(u[0] - 960) < 1e-6 and abs(v[0] - 540) < 1e-6


def test_circular_std_of_hue():
    assert M.circ_std_deg(np.array([30.0] * 50)) < 1e-3
    # wrapping: 350 and 10 are 20 degrees apart, not 340
    s = M.circ_std_deg(np.array([350.0, 10.0] * 50))
    assert 9.0 < s < 11.0


def test_chroma_and_hue_of_known_colours():
    img = np.zeros((2, 2, 3))
    img[0, 0] = (0.5, 0.5, 0.5)       # grey: chroma 0
    img[0, 1] = (1.0, 0.0, 0.0)       # sRGB red: Lab C* about 104, hue about 40 deg
    lab = M.srgb_to_lab(img)
    c = np.hypot(lab[..., 1], lab[..., 2])
    assert c[0, 0] < 0.05 and 100 < c[0, 1] < 108
    assert 35 < math.degrees(math.atan2(lab[0, 1, 2], lab[0, 1, 1])) < 45


def test_frame_metrics_see_more_spread_in_a_varied_frame():
    rng = np.random.default_rng(1)
    flat = np.full((60, 80, 3), (0.45, 0.35, 0.25))
    varied = flat.copy()
    varied[30:, :40] = (0.35, 0.42, 0.22)      # a green patch in the lower half
    varied[30:, 40:] = (0.5, 0.32, 0.2)        # a rust patch
    varied += rng.normal(0, 0.005, varied.shape)
    a, b = M.frame_metrics(flat), M.frame_metrics(np.clip(varied, 0, 1))
    assert b["hue_spread_deg"] > a["hue_spread_deg"] + 5
    assert b["chroma_lower"] >= a["chroma_lower"] - 1


def test_linear_luminance_ratio():
    img = np.zeros((10, 10, 3))
    img[:, :5] = 0.5
    img[:, 5:] = 0.25
    lin = M.linear_luminance(img)
    assert abs(lin[:, :5].mean() / lin[:, 5:].mean() - (M.srgb_to_linear(0.5) / M.srgb_to_linear(0.25))) < 1e-9


def test_cast_is_one_for_a_single_tint_and_low_for_opposing_hues():
    # LOOK2 fix round 1 (review 3): one warm tint over everything vs. varied colour
    import numpy as np
    red = np.zeros((4, 4, 3)); red[...] = (0.5, 0.2, 0.1)
    assert M.frame_metrics(red)["cast_frame"] > 0.99
    mixed = red.copy(); mixed[:, :2] = (0.2, 0.45, 0.25)     # half olive-green
    assert M.frame_metrics(mixed)["cast_frame"] < 0.7
    grey = np.full((4, 4, 3), 0.4)
    assert M.frame_metrics(grey)["cast_frame"] < 0.05
