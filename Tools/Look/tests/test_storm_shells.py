"""Storm shells (task STORM-SHELLS): the numpy port of Shaders/StormShells.ush and the editor builder's offline check."""
import pathlib
import sys

import numpy as np
import pytest

LOOK = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LOOK / "storm_shells"))
sys.path.insert(0, str(LOOK))
import shells_model as sm  # noqa: E402
import build_storm_shells_material as bsm  # noqa: E402


def rays(yaw_deg, pitch_deg):
    y, p = np.radians(yaw_deg), np.radians(pitch_deg)
    return np.stack([np.cos(p) * np.cos(y), np.cos(p) * np.sin(y), np.sin(p)], axis=-1)


def test_far_root_lies_on_the_shell_ahead():
    y, p = np.meshgrid(np.linspace(-180, 180, 13), np.linspace(-80, 80, 9))
    d = rays(y, p)
    for R in sm.PARAMS["Radii"]:
        t = sm.far_root_centered(d, R)
        assert (t > 0).all()
        assert np.allclose(np.hypot(t * d[..., 0], t * d[..., 1]), R, rtol=1e-6)
        assert np.allclose(sm.far_root_offset((0.0, 0.0), d, R), t, rtol=1e-6)
        o = (2.0, -1.5)
        to = sm.far_root_offset(o, d, R)
        assert (to > 0).all()
        assert np.allclose(np.hypot(o[0] + to * d[..., 0], o[1] + to * d[..., 1]), R, rtol=1e-6)


def test_zenith_and_nadir_stay_finite():
    d = np.array([[0.0, 0.0, 1.0], [0.0, 0.0, -1.0]])
    assert np.isfinite(sm.far_root_centered(d, 150.0)).all()


def test_height_band():
    assert sm.height_profile(0.0) == pytest.approx(1.0)
    assert sm.height_profile(sm.PARAMS["Band"][1]) == pytest.approx(0.5, abs=1e-3)
    assert sm.height_profile(45.0) == pytest.approx(0.0, abs=1e-6)
    assert sm.height_profile(-60.0) == pytest.approx(1.0)
    assert sm.height_profile(-160.0) == pytest.approx(0.0, abs=1e-6)
    h = np.linspace(0, 60, 121)
    assert (np.diff(sm.height_profile(h)) <= 1e-9).all()


def test_gust_drift_rate_is_the_gusting_speed():
    t = np.linspace(0, 120, 400)
    e = 1e-4
    rate = (sm.drift_m(t + e) - sm.drift_m(t - e)) / (2 * e)
    V, A = sm.PARAMS["Wind"][2], sm.PARAMS["Wind"][3]
    assert np.allclose(rate, V * (1 + A * sm.gust(t)), atol=1e-3)
    assert (rate > 0).all()


def test_per_layer_alpha_matches_the_doc():
    edges = sm.slab_edges()
    assert np.all(np.diff(edges) > 0)
    assert edges[0] == sm.PARAMS["Edges"][0]
    assert edges[-1] == sm.PARAMS["Edges"][1]
    alpha = [sm.layer_alpha(1.0, length, 1.0, 1.0, 1.0, 1.0) for length in np.diff(edges)]
    assert all(0.0 < a < sm.PARAMS["Dens"][3] for a in alpha)
    assert sm.slab_length(5.0, 0) == 0.0
    assert sm.slab_length(20.0, 0) == pytest.approx(12.0)
    assert sm.slab_length(200.0, 0) == pytest.approx(edges[1] - edges[0])


def test_height_weighted_slab_matches_reference_on_slope_and_sky():
    edges = sm.slab_edges()
    for elevation in (-0.5, -0.2, 0.0, 0.1, 0.25, 0.5):
        for i in range(4):
            for scene_xy in (edges[i] - 1, edges[i] + 0.25 * (edges[i + 1] - edges[i]), 1e7):
                length = sm.slab_length(scene_xy, i)
                xs = np.linspace(edges[i], edges[i] + length, 1001)
                expected = np.trapezoid(sm.height_profile(xs * elevation + sm.PARAMS["Band"][0]), xs)
                actual = sm.slab_profiled_length(scene_xy, elevation, i)
                assert actual == pytest.approx(expected, abs=0.18)
    # A scene point passing a slab edge does not produce an opacity jump.
    for edge in edges[1:-1]:
        totals = [sum(sm.slab_profiled_length(depth, 0.2, i) for i in range(4))
                  for depth in (edge - 1e-3, edge, edge + 1e-3)]
        assert max(np.diff(totals)) < 1e-3


def test_camera_riding_the_wind_sees_a_stable_field(mips):
    d, fwd = small_view(h=24, w=32)
    scene = np.full(d.shape, 0.2)
    sky = np.full(d.shape[:2], 1e7)
    params = {"Wind": (1.0, 0.0, 12.0, 0.0), "Gust": (7.0, 1500.0, 12.0, 0.0),
              "Tier": (4, 0, 0, 0)}
    cam = np.array([100.0, 200.0, -380.0])
    a = sm.shells(scene, sky, d, fwd, cam, 0.0, 1.0, mips, params)
    b = sm.shells(scene, sky, d, fwd, cam + np.array([12.0, 0.0, 0.0]), 1.0, 1.0, mips, params)
    lateral = sm.shells(scene, sky, d, fwd, cam + np.array([0.0, 12.0, 0.0]), 0.0, 1.0, mips, params)
    assert np.allclose(a, b, atol=1e-8)
    assert np.max(np.abs(a - lateral)) > 1e-4


def small_view(h=48, w=64, pitch_deg=-2.0):
    f_px = (w / 2) / np.tan(np.radians(45))
    xs = (np.arange(w) + 0.5 - w / 2) / f_px
    ys = (h / 2 - (np.arange(h) + 0.5)) / f_px
    p = np.radians(pitch_deg)
    fwd = np.array([0.0, np.cos(p), np.sin(p)])
    right = np.array([1.0, 0.0, 0.0])
    up = np.cross(right, fwd)
    d = fwd + xs[None, :, None] * right + ys[:, None, None] * up
    d /= np.linalg.norm(d, axis=-1, keepdims=True)
    return d, fwd


@pytest.fixture(scope="module")
def mips():
    return sm.mip_chain(sm.load_noise(), 3)


def test_whole_pass_is_finite_bounded_and_off_at_storm_zero(mips):
    d, fwd = small_view()
    scene = np.full(d.shape, 0.2)
    depth = np.full(d.shape[:2], 1e7)         # sky everywhere
    off = sm.shells(scene, depth, d, fwd, np.array([3000.0, 4000.0, -400.0]), 10.0, 0.0, mips)
    assert np.array_equal(off, scene)
    out, layers = sm.shells(scene, depth, d, fwd, np.array([3000.0, 4000.0, -400.0]), 10.0, 1.0, mips, return_layers=True)
    assert np.isfinite(out).all()
    for a in layers["alpha"]:
        assert (a >= 0).all() and (a <= sm.PARAMS["Dens"][3]).all()
    assert any((a > 0).any() for a in layers["alpha"])


def test_scene_in_front_of_the_shells_hides_them(mips):
    d, fwd = small_view()
    scene = np.full(d.shape, 0.2)
    near = np.full(d.shape[:2], 5.0)           # the cabin, 5 m away
    out = sm.shells(scene, near, d, fwd, np.array([0.0, 0.0, 0.0]), 3.0, 1.0, mips)
    assert np.allclose(out, scene)


def test_tier_zero_and_layer_count(mips):
    d, fwd = small_view()
    scene = np.full(d.shape, 0.2)
    depth = np.full(d.shape[:2], 1e7)
    cam = np.array([0.0, 0.0, 0.0])
    off = sm.shells(scene, depth, d, fwd, cam, 3.0, 1.0, mips, params={"Tier": (0, 0, 0, 0)})
    assert np.array_equal(off, scene)
    _, lay = sm.shells(scene, depth, d, fwd, cam, 3.0, 1.0, mips, params={"Tier": (3, 2, 0, 0)}, return_layers=True)
    assert not (lay["alpha"][3] > 0).any()


def test_builder_offline_check_passes():
    assert bsm.check() == 0
    assert bsm.PINS[0] == "Scene" and "Storm" in bsm.PINS
    for n in bsm.VECTOR_PINS + bsm.COLOR_PINS:
        assert n in sm.PARAMS
