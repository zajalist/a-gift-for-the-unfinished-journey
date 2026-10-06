# Tools/Terrain/tests/test_bake_masks.py
import sys, pathlib, numpy as np, pytest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import bake_masks as bm

GEO_SIZE = 4096  # R20: geometry tests need a texel small next to the 3.5-5.5 m road (~2 m/texel).

@pytest.fixture(scope="module")
def m():
    return bm.bake(None, size=1024, seed=1)   # 1024 keeps tests fast; production is 4096

@pytest.fixture(scope="module")
def m_geo():
    # Dedicated fixture for the road-geometry tests (on-spline, width, hairpins). At the cheap
    # 1024 fixture above (~8 m/texel) the 3.5-5.5 m road is sub-texel, so no distance field can
    # resolve it: a texel the road only clips at a corner cannot simultaneously read as core > 0.9
    # (needed for on-spline/hairpin) and count for less than its full area in the width sum
    # (needed for core_width). That is a texel-size problem, not something to fix by widening the
    # road or its edge feather (R20 controller ruling) -- so these three tests run at production
    # resolution instead, where a texel is small next to the road and the tension disappears.
    return bm.bake(None, size=GEO_SIZE, seed=1)

def test_ranges(m):
    for k, a in m.items():
        assert a.dtype == np.float32 and a.min() >= 0 and a.max() <= 1, k

def test_core_on_spline(m_geo):
    ij = bm.world_to_texel(bm.road_polyline_cm(step_m=4.0), GEO_SIZE)
    assert (m_geo["core"][ij[:, 1], ij[:, 0]] > 0.9).mean() > 0.99

def test_core_width(m_geo):
    px_m = bm.EXTENT_CM / 100 / GEO_SIZE
    width_m = (m_geo["core"] > 0.5).sum() * px_m * px_m / 5009.0
    assert 3.0 < width_m < 6.5

def test_hairpin_continuity(m_geo):
    for d in (3850, 4015):
        ij = bm.world_to_texel(bm.road_polyline_cm(step_m=1.0, lo_m=d - 60, hi_m=d + 60), GEO_SIZE)
        assert (m_geo["core"][ij[:, 1], ij[:, 0]] > 0.9).all(), d

def test_surface_transition_is_smooth(m):
    s = bm.surface_along(np.arange(2000, 2100, 1.0))
    assert np.abs(np.diff(s)).max() < 0.1 and s[0] < 0.1 and s[-1] > 0.9

def test_verge_monotone_outward(m):
    assert bm.verge_profile(np.array([0, 5, 10, 20, 25, 30])).tolist() == sorted(bm.verge_profile(np.array([0, 5, 10, 20, 25, 30])).tolist(), reverse=True)

def test_deterministic():
    a, b = bm.bake(None, size=256, seed=3), bm.bake(None, size=256, seed=3)
    assert all(np.array_equal(a[k], b[k]) for k in a)

def test_ecology_from_live_heightmap(m):
    # R21: ecology channels come from Current_u16.png (flow accumulation, hollows, altitude), not
    # the stale GAEA export. moisture should track flow accumulation: wherever a lot of upstream
    # area drains through a cell (top 5% by accumulation), moisture should read clearly higher on
    # average than elsewhere -- this is only true if moisture is actually derived from live
    # hydrology, not from a misaligned, unrelated mask.
    flow = bm.flow_accumulation(1024)                      # same resolution bake() used to build m
    thresh = np.percentile(flow, 95)
    wet = m["moisture"][flow >= thresh]
    dry = m["moisture"][flow < thresh]
    assert wet.mean() > dry.mean() + 0.05

def test_stale_gaea_refused():
    # R21: D:/GaeaBuilds/Saskarta_direct_16k is the known-stale, pre-2x2-fix export (see
    # height_mask_correlation's docstring). Passing it as --gaea-dir must refuse to bake at all,
    # not silently proceed -- this is the permanent guard for a future re-export.
    with pytest.raises(RuntimeError):
        bm.bake(None, size=256, seed=1, gaea_dir=bm.GAEA)
