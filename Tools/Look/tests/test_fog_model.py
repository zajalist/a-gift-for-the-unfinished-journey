"""Tests for Tools/Look/fog_model.py, the offline model of the level's exponential height fog (task SKY).

The closed-form line integral must match a brute-force numeric integral of the density along the
ray, honour StartDistance, FogMaxOpacity and FogCutoffDistance. FOG3: the keys' fog, blended along the
road as the director does, has an opaque distance cutoff: clear nearby route through 200 m, then near
a faint ridge by 1 km. The older Fog 3 fitting functions remain as historical calibration helpers.

Run: python -m pytest Tools/Look/tests -q -p no:cacheprovider --basetemp <scratch dir>
"""
import math
import pathlib
import sys

import numpy as np
import pytest

LOOK = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LOOK))
sys.path.insert(0, str(LOOK.parents[1] / "Tools" / "Story"))

import fog_model as fm  # noqa: E402

LAYERS = [{"density": 0.3, "falloff": 0.4, "height_cm": -42000.0},
          {"density": 0.002, "falloff": 0.25, "height_cm": -22000.0}]


def _numeric(cam, tgt, layers, start_cm=0.0, n=200000):
    """ln 2 x the physical integral of the density along the ray: the engine's line integral uses
    (1 - 2^-x) / x (Taylor limit ln 2) and then 2^-integral, so its integral is ln 2 x the true one."""
    cam, tgt = np.asarray(cam, float), np.asarray(tgt, float)
    length = np.linalg.norm(tgt - cam)
    s = np.linspace(min(start_cm, length), length, n)
    pts = cam + (tgt - cam) / length * s[:, None]
    return math.log(2.0) * float(np.trapezoid(fm.density_at(pts[:, 2], layers), s))


@pytest.mark.parametrize("tgt", [(300000.0, 0.0, -35000.0), (300000.0, 0.0, 19000.0),
                                 (50000.0, 20000.0, -41000.0), (0.0, 0.0, 100000.0)])
def test_closed_form_matches_numeric_integral(tgt):
    cam = (0.0, 0.0, -35100.0)
    got = float(fm.line_integral(cam, tgt, LAYERS))
    assert got == pytest.approx(_numeric(cam, tgt, LAYERS), rel=1e-3)


def test_start_distance_skips_the_first_stretch():
    cam, tgt = (0.0, 0.0, -35100.0), (300000.0, 0.0, -30000.0)
    got = float(fm.line_integral(cam, tgt, LAYERS, start_cm=50000.0))
    assert got == pytest.approx(_numeric(cam, tgt, LAYERS, start_cm=50000.0), rel=1e-3)
    assert float(fm.line_integral(cam, (40000.0, 0.0, -35100.0), LAYERS, start_cm=50000.0)) == 0.0


def test_max_opacity_floors_and_cutoff_clears():
    cam, far = (0.0, 0.0, -41000.0), (2.0e6, 0.0, -41000.0)
    assert float(fm.transmittance(cam, far, LAYERS, 0.0, max_opacity=0.8)) == pytest.approx(0.2)
    assert float(fm.transmittance(cam, far, LAYERS, 0.0, max_opacity=0.8, cutoff_cm=1.0e6)) == 1.0


def test_density_halves_every_ten_over_falloff_metres():
    one = [{"density": 1.0, "falloff": 0.5, "height_cm": 0.0}]
    assert float(fm.density_at(0.0, one)) == pytest.approx(1e-3)
    assert float(fm.density_at(2000.0, one)) == pytest.approx(0.5e-3)   # 10 / 0.5 = 20 m


def test_fog_top_is_where_density_falls_to_five_percent():
    one = [{"density": 1.0, "falloff": 0.5, "height_cm": 0.0}]
    # 5 % = 2^-4.32 -> 4.32 halvings of 20 m above the floor
    assert fm.fog_top_m(one, 0.0) == pytest.approx(20.0 * math.log2(20.0), abs=1.0)


@pytest.fixture(scope="module")
def keys():
    import apply_look
    return apply_look.load_keys()


@pytest.fixture(scope="module")
def terrain():
    from build_road_profile import HEIGHTMAP
    if not HEIGHTMAP.exists():
        pytest.skip(f"no heightmap at {HEIGHTMAP}")
    return fm.load_terrain()


@pytest.fixture(scope="module")
def road(keys):
    return fm.road_report(step_m=50.0, keys=keys)


def _storm(keys, m):
    """The storm keys' stretch: the director's blended storm intensity (Ridge 0.7, the basin 1.0) >= 0.5."""
    import apply_look
    return apply_look.blend_keys(keys, m)["storm_intensity"] >= 0.5


def test_distance_fog_hides_the_unbuilt_world(keys, road):
    """The road stays legible nearby and becomes effectively opaque beyond the authored terrain."""
    for key in keys:
        fog = key["fog"]
        assert fog["density"] == pytest.approx(0.06)
        assert fog["falloff"] == pytest.approx(0.0)
        assert fog["start_m"] == pytest.approx(650.0)
        assert fog["max_opacity"] == pytest.approx(0.98)
    for row in road:
        assert row["T150"] == pytest.approx(1.0), row
        assert row["T300"] == pytest.approx(1.0), row
        assert row["T1000"] <= 0.37, row
        assert row["T2000"] <= 0.03, row


def test_fog3_climb_rises_out_of_the_dust(keys):
    """From Stair on the dust stays on the basin floor (the road's lowest ground) with the Cistern key's ground
    density, and the haze is the last valley key's: one field, so the basin below reads as it did from inside."""
    ks = sorted(keys, key=lambda k: k["road_m"])
    floor_m = float(fm._profile()[3].min())
    last_valley = [k for k in ks if k["road_m"] < fm.FOG3_CLIMB_FROM_M][-1]
    source = [k for k in ks if k["name"] == fm.FOG3_CLIMB_DUST_FROM][0]
    for k in ks:
        if k["road_m"] >= fm.FOG3_CLIMB_FROM_M:
            assert fm.FOG_ACTOR_Z_CM / 100.0 + k["fog"]["second_height_m"] <= floor_m, k["name"]
            assert k["fog"]["second_density"] == source["fog"]["second_density"], k["name"]
            assert k["fog"]["density"] == last_valley["fog"]["density"], k["name"]


def test_distance_fog_level_and_keys_agree(keys):
    """The runtime director blends key values but leaves maximum opacity on the fog actor."""
    import apply_look
    assert apply_look.FOG_MAX_OPACITY == 0.98
    for key in keys:
        fog = key["fog"]
        assert fog["max_opacity"] == apply_look.FOG_MAX_OPACITY
        assert 0.0 < fog["density"] <= 10.0
        assert 0.0 <= fog["falloff"] <= 2.0
        assert 0.0 < fog["second_density"] <= 10.0
        assert 0.0 < fog["second_falloff"] <= 2.0
        assert "visibility_m" not in fog


def test_dust_anchor_blend_stays_under_the_road(keys):
    """The dust layer's blended height never sits more than the tolerance above the road (checked on the 10 m
    grid the anchors are fitted on; key metres and profile samples lie on it, so the blend and the road are
    linear between its points), so the director's blend cannot sink the carrier into the dense bottom."""
    ks = sorted(keys, key=lambda k: k["road_m"])
    for m in np.arange(0.0, 5010.0, 10.0):
        f = fm.blend_key_fog(ks, float(m))
        anchor_m = fm.FOG_ACTOR_Z_CM / 100.0 + f["second_height_m"]
        assert anchor_m <= float(fm.road_point(m)[2]) / 100.0 + fm.FOG3_ENVELOPE_TOL_M + 1e-3, m
