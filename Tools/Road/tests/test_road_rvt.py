"""Offline checks for the road RVT writer (world sprint, Tasks V1, V1b and ROADNOISE).

    python -m pytest Tools/Road/tests -q

Shaders/RoadRVT.hlsl is pasted into the Custom node of M_Saskarta_RoadRVT by
Tools/Road/build_road_material.py, through Hayba python_run, after
prepare_road_material.py fills in the road polyline. It must survive that trip
(ASCII, no quotes or backslashes, no word the python_run policy scanner refuses)
and compile as a function body with two extra outputs.

The look checks run on road_model.py, a numpy port of the HLSL, line for line:
  - V1b 1, paving: irregular slabs (not a grid), tone within +-10 percent, thin dark
    joints, 40-70 percent buried, missing in clusters, broken toward the verge;
  - V1b 2, dirt: ruts and crown deep and contrasted enough to read at eye height;
  - V1b 3, caps and seams: the surface is a function of world position only, and
    the road frame is the exact distance to the polyline, so ribbon segments and
    joint caps write the same texels (mitred inner corners, round outer corners);
  - V1b 4, the edge: noise-warped and feathered, following the mask's core;
  - ROADNOISE: the breakage is driven by a domain-warped decay fBm (15 m, 3 m, 0.5 m):
    missing stones in irregular patches with crumbled edges, potholes and mud, stones
    that tilt, sink and scatter at the verge, stone size drifting along the road,
    cracks, value and hue per stone, a noise-modulated neglect transition, and no
    repetition from 2 to 60 m.
"""
import math
import pathlib
import re
import shutil
import subprocess
import sys

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
HLSL = ROOT / "Shaders" / "RoadRVT.hlsl"
BUILD = ROOT / "Tools" / "Road" / "build_road_material.py"
sys.path.insert(0, str(ROOT / "Tools" / "Road"))
sys.path.insert(0, str(ROOT / "Tools" / "Road" / "tests"))

import prepare_road_material as prep  # noqa: E402
import road_model as rm  # noqa: E402

BANNED = ['"', "'", "\\", "#", "try", "getattr", "open(", ".replace(", "new_level(", "import time"]
PINS = ("float3 P, float Core, float Surface, float Neglect, float Wear, float HalfWidth, "
        "float3 DirtColor, float3 GravelColor, float3 PavingColor, float3 CrownGrassColor, "
        "inout float3 RoadNormalWS, inout float RoadOpacity")
HW = 2.25
ORIGIN, EXTENT = prep.mask_mapping(ROOT / "Tools" / "Terrain" / "MASKS.md")
ROAD = np.array(prep.road_polyline_m(ORIGIN))


def lum(c):
    c = np.asarray(c)
    return c[..., 0] * 0.2126 + c[..., 1] * 0.7152 + c[..., 2] * 0.0722


def station(seg, frac, across_m, pts=ROAD):
    """A point at fraction frac along segment seg, across_m metres to its left."""
    a, b = pts[seg, :2], pts[seg + 1, :2]
    d = (b - a) / np.linalg.norm(b - a)
    return a + (b - a) * frac + np.array([-d[1], d[0]]) * across_m


# A long straight stretch (segment 26, 491 m) and the 76 deg hairpin at point 17 (3,850 m).
STRAIGHT = ROAD[24:30]
STRAIGHT_SEG = 2          # ROAD segment 26 inside STRAIGHT
HAIRPIN = ROAD[14:21]
HAIRPIN_J = 3             # ROAD point 17 inside HAIRPIN


def cross2(a, b):
    return a[0] * b[1] - a[1] * b[0]


def strip(seg, frac0, frac1, n_along, across, pts):
    rows = []
    for f in np.linspace(frac0, frac1, n_along):
        for x in across:
            rows.append(station(seg, f, x, pts))
    return np.array(rows)


# ---- The shader text -------------------------------------------------------------------
def test_body_survives_python_run():
    for text in (HLSL.read_text(encoding="ascii"), prep.prepared_hlsl(ROOT)):
        for bad in BANNED:
            assert bad not in text, bad


def test_polyline_markers_are_filled_from_the_road_spline():
    hlsl = prep.prepared_hlsl(ROOT)
    assert "ROAD_POINTS" not in hlsl and "ROAD_NPTS" not in hlsl
    got = re.findall(r"float3\((-?[\d.]+), (-?[\d.]+), (-?[\d.]+)\)", hlsl.split("const float3 RP[")[1].split(";")[0])
    assert len(got) == 55
    assert "const float3 RP[55]" in hlsl
    import build_road_profile as brp
    for (x, y, z), (xc, yc, zc) in zip(got, brp.SPLINE_POINTS_CM):
        assert abs(float(x) - (xc - ORIGIN[0]) / 100) < 1e-3
        assert abs(float(y) - (yc - ORIGIN[1]) / 100) < 1e-3
        assert abs(float(z) - zc / 100) < 1e-3


@pytest.mark.skipif(shutil.which("dxc") is None, reason="dxc not on PATH")
def test_body_compiles_as_a_function(tmp_path):
    src = tmp_path / "road.hlsl"
    src.write_text(
        "float4 RoadRVT(" + PINS + ") {\n" + prep.prepared_hlsl(ROOT) + "\n}\n"
        "float4 main(float4 p : TEXCOORD0, float4 q : TEXCOORD1) : SV_Target {\n"
        "  float3 n = float3(0, 0, 1); float o = 0;\n"
        "  float4 c = RoadRVT(p.xyz, q.x, q.y, q.z, q.w, 2.25, p.rgb, q.rgb, p.gbr, q.gbr, n, o);\n"
        "  return c + float4(n, o);\n}\n",
        encoding="ascii")
    r = subprocess.run(["dxc", "-T", "ps_6_0", "-E", "main", str(src), "-Fo", str(tmp_path / "r.bin")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_surface_depends_on_world_position_only():
    """No mesh UV reaches the shader, so ribbons and caps cannot disagree (V1b item 3)."""
    text = BUILD.read_text(encoding="utf-8")
    pins = re.search(r"ROAD_PINS = \[(.*?)\]", text, re.S).group(1)
    names = re.findall(r"'(\w+)'", pins)
    assert names == ["P", "Core", "Surface", "Neglect", "Wear", "HalfWidth",
                     "DirtColor", "GravelColor", "PavingColor", "CrownGrassColor"]
    assert "MaterialExpressionTextureCoordinate" not in text
    code = "\n".join(l.split("//")[0] for l in HLSL.read_text(encoding="ascii").splitlines())
    assert not re.search(r"\bUV\b|RoadU|RoadV", code)


def test_model_constants_match_the_shader():
    code = HLSL.read_text(encoding="ascii")
    src = {3: "cW", 4: "cW"}
    scales = ", ".join(src.get(i, "q") + " / " + repr(s) for i, s in enumerate(rm.NOISE_SCALES))
    assert "{ " + scales + " }" in code
    assert "float2(ox, oy) + 0.5 + 0.9 * (float2(jx, jy) - 0.5)" in code and "floor(qw / 0.9)" in code
    assert "(lq - lp) * 0.9" in code and "(bestC + 0.5 + 0.9 * (bestJ - 0.5)) * 0.9" in code
    assert "float2 slabW = %r * wA + %r * wB;" % rm.SLAB_WARP in code
    assert "float2 decW = %r * wB;" % rm.DECAY_WARP in code and "cW + %r * nz.warp3(cW)" % rm.DECAY_WARP in code
    fbm = " + ".join("%r * vn(x / %r, %du)" % (w, s, n) for s, n, w in rm.FBM)
    assert "return " + fbm + ";" in code
    assert rm.SLAB_JITTER == 0.9 and rm.SLAB_PITCH == 0.9
    assert "0.0992 * jw" in code and rm.SLAB_WEIGHT == 0.0992
    build = BUILD.read_text(encoding="utf-8")
    for name, rgb in [("DirtColor", rm.DIRT), ("GravelColor", rm.GRAVEL), ("PavingColor", rm.PAVING),
                      ("CrownGrassColor", rm.GRASS)]:
        assert "('%s', (%.3f, %.3f, %.3f))" % ((name,) + tuple(rgb)) in build, name
    T = rm.TUNING
    for literal in ["smoothstep(0.48, 0.6, bur + 0.1 * fineK * (nv[2] - 0.5))", "smoothstep(0.4, 0.55, ev)",
                    "0.45 + 0.12 * (nv[0] - 0.5)", "PavingColor * (0.9 + 0.2 * rTone) * (0.94 + 0.12 * nz.vn(cW / 12.0, 21u)) * hue",
                    "float dBias = %r * (Neglect - 0.63) + %r * (Wear - 0.6);" % (T["DEC_NEG"], T["DEC_WEAR"]),
                    "+ dBias + %r * rutsC * Wear + %r * smoothstep(0.75, 1.2, uc);" % (T["DEC_RUT"], T["DEC_VERGE"]),
                    "float gone = dSlab > %r ?" % T["DEC_GONE"],
                    "(dPix + 0.16 * (crumble - 0.5)) > %r ?" % T["DEC_CHIP"],
                    "%r * (Neglect - 0.5)" % T["BUR_NEG"], "smoothstep(0.8, 1.2, uc) - %r;" % T["BUR_OFF"],
                    "float pit = smoothstep(%r, %r + 0.06, pitE);" % (T["PIT_LO"], T["PIT_LO"]),
                    "Core + %r * (edgeN - 0.5) - %r * (dPix - 0.45)" % (T["EDGE_AMP"], T["EDGE_DEC"])]:
        assert literal in code, literal


# ---- V1b 3: seams and joint caps -----------------------------------------------------------
def test_road_frame_is_the_exact_polyline_distance_and_continuous_at_the_hairpin():
    j = HAIRPIN[HAIRPIN_J, :2]
    xs = np.arange(-6.0, 6.0, 0.05)
    grid = np.array([(j[0] + x, j[1] + y) for y in xs for x in xs])
    dist, _, _, _ = rm.polyline_frame(grid, HAIRPIN)
    u = (dist / HW).reshape(len(xs), len(xs))
    # a distance field is 1-Lipschitz: no jump anywhere, so no seam between segments or caps
    assert np.abs(np.diff(u, axis=0)).max() <= 0.05 / HW + 1e-9
    assert np.abs(np.diff(u, axis=1)).max() <= 0.05 / HW + 1e-9


def test_outer_corner_is_radial_and_inner_corner_is_mitred():
    a, j, b = HAIRPIN[HAIRPIN_J - 1, :2], HAIRPIN[HAIRPIN_J, :2], HAIRPIN[HAIRPIN_J + 1, :2]
    da, db = (j - a) / np.linalg.norm(j - a), (b - j) / np.linalg.norm(b - j)
    # outer wedge: beyond the end of both segments, the cap's surface is the radial distance to the joint
    bis_out = (da - db) / np.linalg.norm(da - db)
    for r in [0.5, 1.0, 2.0, 3.0]:
        p = j + bis_out * r
        dist, _, _, _ = rm.polyline_frame(p[None], HAIRPIN)
        assert abs(dist[0] - r) < 1e-6
    # inner side: on the bisector the distances to both segments agree (a mitre, no step)
    bis_in = -bis_out
    for r in [0.5, 1.0, 2.0]:
        p = j + bis_in * r
        d_a = abs(cross2(da, p - j))
        d_b = abs(cross2(db, p - j))
        assert abs(d_a - d_b) < 1e-6
        dist, _, _, _ = rm.polyline_frame(p[None], HAIRPIN)
        assert abs(dist[0] - d_a) < 1e-6


def test_hairpin_surface_has_no_fan_outline():
    """The written colour around the joint depends on distance only, never on the angle around the cap."""
    j = HAIRPIN[HAIRPIN_J, :2]
    a = HAIRPIN[HAIRPIN_J - 1, :2]
    da = (j - a) / np.linalg.norm(j - a)
    b = HAIRPIN[HAIRPIN_J + 1, :2]
    db = (b - j) / np.linalg.norm(b - j)
    bis_out = (da - db) / np.linalg.norm(da - db)
    # sweep a small arc inside the outer wedge at a fixed radius: u stays constant (no fan)
    ang0 = math.atan2(bis_out[1], bis_out[0])
    pts = np.array([j + 1.0 * np.array([math.cos(ang0 + t), math.sin(ang0 + t)]) for t in np.linspace(-0.3, 0.3, 61)])
    res = rm.evaluate(pts, HAIRPIN, core=1.0, surface=0.0, neglect=0.4, wear=0.45)
    assert np.ptp(res["u"]) < 1e-6


# ---- V1b 2: dirt stretches ----------------------------------------------------------------
def dirt_section(u_values, n_along=400, wear=0.45, neglect=0.4):
    across = np.array(u_values) * HW
    p = strip(STRAIGHT_SEG, 0.2, 0.8, n_along, across, STRAIGHT)
    res = rm.evaluate(p, STRAIGHT, core=1.0, surface=0.0, neglect=neglect, wear=wear)
    return res, len(across)


def test_dirt_stretch_never_shows_paving():
    res, _ = dirt_section(np.linspace(-1.2, 1.2, 49), n_along=100)
    assert res["slab_vis"].max() == 0.0 and res["present"].max() == 0.0


def test_ruts_and_crown_read_at_eye_height():
    us = [0.0, 0.45]
    res, n = dirt_section(us)
    h = res["h"].reshape(-1, n)
    assert (h[:, 0] - h[:, 1]).mean() > 0.05          # crown top to rut bottom: over 5 cm
    l = lum(res["col"]).reshape(-1, n)
    assert (l[:, 1] / l[:, 0]).mean() < 0.85          # ruts clearly darker than the crown


def test_crown_sheds_outward_and_rut_walls_face_in():
    us = [0.17, 0.36, 0.56]
    res, n = dirt_section(us)
    lean = (res["normal"][:, :2] * res["across"]).sum(-1).reshape(-1, n).mean(0)
    assert lean[0] > 0.02      # crown falls away from the centre
    assert lean[1] > 0.0       # inner rut wall faces outward
    assert lean[2] < 0.0       # outer rut wall faces the centre


def test_normals_are_unit_and_gentle():
    res, _ = dirt_section(np.linspace(-1.2, 1.2, 49), n_along=100, wear=1.0)
    n = res["normal"]
    assert np.allclose(np.linalg.norm(n, axis=1), 1.0)
    z = n @ np.array([0, 0, 1.0])
    assert (z > 0.8).mean() > 0.99                     # gentle ground ...
    assert z.min() > 0.6                               # ... and pothole lips are the only steep texels


def test_ruts_wander_and_vary():
    res, n = dirt_section(np.linspace(0.3, 0.6, 31), n_along=200)
    h = res["h"].reshape(-1, n)
    rut_at = np.linspace(0.3, 0.6, 31)[np.argmin(h, axis=1)]
    assert np.std(rut_at) > 0.02      # the rut line wanders along the road


def test_crown_grass_only_where_neglected():
    bare, _ = dirt_section([0.0], neglect=0.0)
    grassy, _ = dirt_section([0.0], neglect=1.0)
    assert bare["grass"].max() == 0.0
    assert 0.1 < (grassy["grass"] > 0.2).mean() < 0.9      # tufts, not a solid strip


# ---- V1b 1: paving -------------------------------------------------------------------------
def paving_area(half_len=8.0, step=0.03, neglect=0.6, wear=0.78, u_max=1.2):
    mid = STRAIGHT_SEG
    a, b = STRAIGHT[mid, :2], STRAIGHT[mid + 1, :2]
    d = (b - a) / np.linalg.norm(b - a)
    n = np.array([-d[1], d[0]])
    c = (a + b) / 2
    al = np.arange(-half_len, half_len, step)
    ac = np.arange(-u_max * HW, u_max * HW, step)
    p = np.array([c + d * x + n * y for x in al for y in ac])
    res = rm.evaluate(p, STRAIGHT, core=1.0, surface=1.0, neglect=neglect, wear=wear)
    return res


def slab_sizes(ids):
    _, counts = np.unique(ids, axis=0, return_counts=True)
    return counts


def test_slabs_are_irregular_not_a_grid():
    step = 0.02
    xs = np.arange(0, 16, step) + 3000.0
    p = np.array([(x, y) for y in np.arange(0, 16, step) + 2000.0 for x in xs])
    pt, _ = rm.slab_site(np.zeros((1, 2)))
    cell = np.floor(p / rm.SLAB_PITCH)
    best = np.full(len(p), 1e9)
    ids = np.zeros_like(p)
    for j in range(9):
        c = cell + np.array([j % 3 - 1, j // 3 - 1], dtype=float)
        site, w = rm.slab_site(c)
        pd = ((p - site) ** 2).sum(-1) - w
        m = pd < best
        best = np.where(m, pd, best)
        ids = np.where(m[:, None], c, ids)
    counts = slab_sizes(ids)
    counts = counts[counts > 200]                      # drop cells clipped by the sample window
    size = np.sqrt(counts) * step                      # equivalent square side, metres
    cv = size.std() / size.mean()
    assert 0.5 <= size.mean() <= 1.2, size.mean()
    assert np.percentile(size, 10) >= 0.4 and np.percentile(size, 90) <= 1.3
    assert cv > 0.15, cv
    # control: the V1 regular grid has no size variance at all
    grid_counts = slab_sizes(np.floor(p / 0.8 + 1e-6))     # V1-like regular grid, aligned to the window
    grid_counts = grid_counts[grid_counts > 200]
    grid_size = np.sqrt(grid_counts) * step
    assert grid_size.std() / grid_size.mean() < 0.01
    assert pt.shape == (1, 2)


@pytest.mark.parametrize("neglect,lo,hi", [(0.52, 0.5, 0.75), (0.63, 0.35, 0.6), (0.75, 0.2, 0.45), (0.9, 0.05, 0.3)])
def test_paving_wears_with_neglect(neglect, lo, hi):
    """Paving stretches run neglect 0.52-0.9 (median 0.63). Well kept: mostly intact paving;
    neglected: large exposed-dirt patches (ROADNOISE item 4)."""
    res = paving_area(half_len=40.0, step=0.05, neglect=neglect, u_max=0.8)   # 80 m: many patches
    vis = (res["slab_vis"] > 0.5).mean()
    assert lo <= vis <= hi, vis


def test_slab_tone_and_hue_vary_and_joints_are_thin_and_dark():
    res = paving_area(u_max=0.6)
    inner = (res["slab_vis"] > 0.99) & (res["edge_d"] > 0.12) & (res["crack"] < 0.01)
    ratio = lum(res["col"][inner]) / lum(rm.PAVING)
    assert ratio.min() >= 0.8 and ratio.max() <= 1.2  # per stone +-10 percent, times a +-6 percent 12 m drift
    assert ratio.std() > 0.03                          # but it does vary
    rb = res["col"][inner][:, 0] / res["col"][inner][:, 2]
    assert rb.std() > 0.03                             # warm and cool stones, not one tint
    joint = (res["present"] > 0.5) & (res["cover"] < 0.01) & (res["edge_d"] < 0.008)
    assert joint.sum() > 0
    assert lum(res["col"][joint]).mean() < 0.6 * lum(res["col"][inner]).mean()
    thin = ((res["present"] > 0.5) & (res["edge_d"] < 0.02)).sum() / max((res["present"] > 0.5).sum(), 1)
    assert thin < 0.1


def test_missing_slabs_come_in_clusters():
    res = paving_area(half_len=30.0, step=0.1, u_max=0.6)
    ids = res["slab_id"]
    keys, first = np.unique(ids, axis=0, return_index=True)
    miss = res["missing"][first] > 0.5
    site = res["slab_site"][first]
    base = miss.mean()
    assert 0.1 < base < 0.6, base
    near = []
    for i in np.where(miss)[0]:
        d = np.linalg.norm(site - site[i], axis=1)
        nb = (d > 1e-6) & (d < 1.3)
        if nb.any():
            near.append(miss[nb].mean())
    assert np.mean(near) > base + 0.15, (np.mean(near), base)


def test_slabs_break_up_toward_the_verge():
    res = paving_area(half_len=20.0, step=0.05, u_max=1.3)
    u = res["u"]
    centre = res["present"][(u < 0.4) & (res["exists"] > 0.5)].mean()
    verge = res["present"][(u > 1.05) & (res["exists"] > 0.5)].mean()
    assert verge < 0.5 * centre, (verge, centre)


# ---- V1b 4: the edge ----------------------------------------------------------------------
def core_like_mask(dist, half=2.4):
    """A stand-in for T_Saskarta_RoadInfluence.R: 1 on the road, soft 2 m falloff."""
    return 1.0 - rm.smoothstep(half - 1.3, half + 1.3, dist)


def edge_positions(half=2.4, n_along=300):
    across = np.arange(0.5, 4.5, 0.02)
    p = strip(STRAIGHT_SEG, 0.2, 0.8, n_along, across, STRAIGHT)
    dist, _, _, _ = rm.polyline_frame(p, STRAIGHT)
    res = rm.evaluate(p, STRAIGHT, core=core_like_mask(dist, half), surface=0.0, neglect=0.4, wear=0.45)
    op = res["opac"].reshape(n_along, len(across))
    first_out = np.argmax(op < 0.5, axis=1)              # first texel out from the centre below 0.5
    return across[first_out], op, across


def test_edge_is_noise_warped():
    edge, _, _ = edge_positions()
    assert np.std(edge) > 0.15, np.std(edge)             # the edge line wanders, it is not a ruled strip


def test_edge_is_feathered_not_crisp():
    _, op, across = edge_positions()
    widths = []
    for row in op:
        hi = np.argmax(row < 0.9)
        lo = np.argmax(row < 0.1)
        widths.append((lo - hi) * (across[1] - across[0]))
    assert np.median(widths) >= 0.1
    # gravel spills unevenly: in some rows, covered texels lie well beyond the first gap
    spill = 0
    for row in op:
        first = np.argmax(row < 0.5)
        spill += (row[first + 8:] > 0.5).any()           # 16 cm or more past the edge
    assert 0.05 < spill / len(op) < 0.9, spill / len(op)


def test_edge_follows_the_mask_core():
    narrow, _, _ = edge_positions(half=2.0)
    wide, _, _ = edge_positions(half=2.6)
    assert 0.4 < wide.mean() - narrow.mean() < 0.8


def test_fine_detail_fades_on_coarse_mips():
    p = strip(STRAIGHT_SEG, 0.3, 0.7, 200, [0.0], STRAIGHT)
    fine = rm.evaluate(p, STRAIGHT, core=1.0, wear=0.45, ts=0.03)
    coarse = rm.evaluate(p, STRAIGHT, core=1.0, wear=0.45, ts=0.2)
    assert lum(coarse["col"]).std() < lum(fine["col"]).std()


# ---- ROADNOISE: noise-driven breakage --------------------------------------------------------
def along_line(length=300.0, step=0.05, across_m=0.0, seg=STRAIGHT_SEG, pts=STRAIGHT):
    """Points along the long straight (segment 26, 491 m), across_m to its left."""
    a, b = pts[seg, :2], pts[seg + 1, :2]
    d = (b - a) / np.linalg.norm(b - a)
    n = np.array([-d[1], d[0]])
    s = np.arange(0.0, length, step)
    return a + d[None] * (s[:, None] + 60.0) + n[None] * across_m, s


def band_share(signal, step, lo_m, hi_m):
    """Share of the variance of signal at wavelengths between lo_m and hi_m."""
    x = signal - signal.mean()
    power = np.abs(np.fft.rfft(x)) ** 2
    wl = 1.0 / np.maximum(np.fft.rfftfreq(len(x), step), 1e-12)
    return power[(wl >= lo_m) & (wl < hi_m)].sum() / power[1:].sum()


def test_decay_field_has_three_octaves_and_is_domain_warped():
    """ROADNOISE item 1: the breakage is driven by fBm at about 0.5 m, 3 m and 15 m."""
    assert [s for s, _, _ in rm.FBM] == [15.0, 3.0, 0.5]
    p, _ = along_line(length=400.0, step=0.05)
    d = rm.fbm(p + rm.DECAY_WARP * rm.warp3(p))
    # value noise with a lattice of s metres puts its power at wavelengths of about 1-5 s
    for lo, hi in [(0.3, 2.0), (2.0, 10.0), (10.0, 80.0)]:
        assert band_share(d, 0.05, lo, hi) > 0.04, (lo, hi, band_share(d, 0.05, lo, hi))
    # the warp bends the octaves: the warped field differs from the plain fBm by a real amount
    plain = rm.fbm(p)
    assert np.abs(d - plain).mean() > 0.03


def test_missing_stones_form_irregular_patches_not_per_stone_dice():
    res = paving_area(half_len=40.0, step=0.1, neglect=0.75, u_max=0.7)
    keys, first = np.unique(res["slab_id"], axis=0, return_index=True)
    gone = res["missing"][first] > 0.5
    site = res["slab_site"][first]
    # patches: at 10 m scale the share of missing stones swings (the 15 m octave), not a flat rate
    d = STRAIGHT[STRAIGHT_SEG + 1, :2] - STRAIGHT[STRAIGHT_SEG, :2]
    along = (site - site.mean(0)) @ (d / np.linalg.norm(d))
    bins = np.floor(along / 10.0)
    share = np.array([gone[bins == b].mean() for b in np.unique(bins) if (bins == b).sum() > 20])
    assert share.std() > 0.1, share
    # and a missing stone's neighbours are mostly missing too
    near = []
    for i in np.where(gone)[0]:
        dd = np.linalg.norm(site - site[i], axis=1)
        nb = (dd > 1e-6) & (dd < 1.3)
        if nb.any():
            near.append(gone[nb].mean())
    assert np.mean(near) > gone.mean() + 0.2, (np.mean(near), gone.mean())


def test_patch_edges_crumble_through_the_stones():
    """Stones along a patch edge are chipped by the pixel decay plus the 12 cm crumble noise,
    so the patch outline cuts through stones raggedly instead of following the joints."""
    res = paving_area(half_len=30.0, step=0.03, neglect=0.75, u_max=0.6)
    keys, inv = np.unique(res["slab_id"], axis=0, return_inverse=True)
    inv = inv.ravel()
    kept = (res["exists"] > 0.5) & (res["missing"] < 0.5)
    chipped = (res["chip"] > 0.5) & kept
    n_kept = np.bincount(inv, weights=kept, minlength=len(keys))
    chip_share = np.bincount(inv, weights=chipped, minlength=len(keys)) / np.maximum(n_kept, 1)
    partial = (chip_share > 0.05) & (chip_share < 0.95)
    assert partial.sum() >= 10, partial.sum()          # many stones are partly broken away
    # the chipped stones sit at the patch edges: their decay is near the threshold
    d_slab = np.bincount(inv, weights=res["d_slab"], minlength=len(keys)) / np.bincount(inv, minlength=len(keys))
    intact = (chip_share == 0) & (n_kept > 0)
    assert np.median(d_slab[partial]) > np.median(d_slab[intact])


def test_neglect_transition_is_noise_modulated_not_a_step():
    """ROADNOISE item 4: a neglect ramp 0.5 to 0.9 over 300 m: the paving thins out, but
    patchily, with no hard step anywhere."""
    p, s = along_line(length=300.0, step=0.1)
    offs = [(0, 0), (0.0, 0.6), (0.6, 0.0), (-0.5, -0.4), (0.3, -0.9), (-0.9, 0.2)]
    rows = np.concatenate([p + np.array(o)[None] for o in offs])
    ss = np.tile(s, len(offs))
    neg = 0.5 + 0.4 * ss / 300.0
    res = rm.evaluate(rows, STRAIGHT, core=1.0, surface=1.0, neglect=neg, wear=0.78)
    vis = (res["slab_vis"] > 0.5).astype(float)
    win = np.floor(ss / 10.0)
    share = np.array([vis[win == w].mean() for w in np.unique(win)])
    mid = np.array([neg[win == w].mean() for w in np.unique(win)])
    assert np.corrcoef(share, mid)[0, 1] < -0.5         # it does wear with neglect
    assert (np.diff(share) > 0.02).sum() >= 3           # but not monotonically: noise modulates it
    assert share[:6].mean() > share[-6:].mean() + 0.3


def test_potholes_and_mud_follow_neglect_on_dirt():
    bare, n = dirt_section(np.linspace(-0.9, 0.9, 19), n_along=600, neglect=0.2)
    worn, _ = dirt_section(np.linspace(-0.9, 0.9, 19), n_along=600, neglect=0.8)
    assert (bare["pit"] > 0.5).mean() < 0.01
    share = (worn["pit"] > 0.5).mean()
    assert 0.03 < share < 0.3, share
    deep = worn["pit"] > 0.99
    assert deep.any()
    # the pothole floor is dark, damp mud
    assert worn["mud"][deep].mean() > 0.3
    assert lum(worn["col"][deep]).mean() < 0.85 * lum(worn["col"][worn["pit"] < 0.01]).mean()
    assert worn["rough"][deep].mean() < worn["rough"][worn["pit"] < 0.01].mean()


def test_edge_stones_tilt_sink_and_scatter():
    res = paving_area(half_len=30.0, step=0.04, neglect=0.63, u_max=1.35)
    vis = res["slab_vis"] > 0.99
    tilt = np.abs(res["h_tilt"])                       # the per-stone tilt, metres of lift across the stone
    inner = vis & (res["uc"] < 0.5) & (res["edge_d"] > 0.1)
    outer = vis & (res["uc"] > 0.9) & (res["edge_d"] > 0.1)
    assert outer.sum() > 50 and inner.sum() > 50
    assert np.median(tilt[outer]) > 2.0 * np.median(tilt[inner])
    assert np.percentile(tilt[outer], 90) > 0.01       # a centimetre and more: it reads in the normal
    # and they sink: the stone surface drops toward the verge (crown excluded)
    assert res["cover"][res["exists"] > 0.5][res["uc"][res["exists"] > 0.5] > 0.9].mean() > \
        res["cover"][res["exists"] > 0.5][res["uc"][res["exists"] > 0.5] < 0.5].mean()
    # a few stones lie out past the edge, shrunken and scattered, not a continued pavement
    scat = res["scat"] > 0.5
    band = (res["u"] > 1.05) & (res["u"] < 1.3) & (res["exists"] > 0.5)
    share = scat[band].mean()
    assert 0.01 < share < 0.2, share


def test_stone_size_drifts_along_the_road():
    """ROADNOISE item 3: the domain-warped lattice stretches and squeezes the stones."""
    p, s = along_line(length=400.0, step=0.06)
    ys = np.arange(-2.0, 2.0, 0.06)
    rows = np.concatenate([p + np.array([0.0, y])[None] for y in ys])
    ss = np.tile(s, len(ys))
    slab_w, _ = rm.lattice_warp(rows)

    def size_drift(q):
        best_c, _, _, _ = rm.slab_cells(q)
        win = np.floor(ss / 8.0)
        sizes = []
        for w in np.unique(win):
            m = win == w
            sizes.append(m.sum() / len(np.unique(best_c[m], axis=0)))
        sizes = np.array(sizes)
        return sizes.std() / sizes.mean()

    warped, plain = size_drift(rows + slab_w), size_drift(rows)
    assert warped > 0.07 and warped > 1.5 * plain, (warped, plain)   # plain: window sampling noise only


def test_cracks_are_thin_and_follow_decay():
    kept = paving_area(half_len=30.0, step=0.02, neglect=0.52, u_max=0.6)
    worn = paving_area(half_len=30.0, step=0.02, neglect=0.8, u_max=0.6)

    def cracked_share(res):
        ok = res["present"] > 0.5
        keys, inv = np.unique(res["slab_id"][ok], axis=0, return_inverse=True)
        per = np.bincount(inv.ravel(), weights=res["crack"][ok] > 0.5)
        return (per > 3).mean(), (res["crack"][ok] > 0.5).mean()

    ks, kpix = cracked_share(kept)
    ws, _ = cracked_share(worn)
    assert 0.1 < ks < 0.6, ks                          # well kept: some stones carry thin cracks
    assert ws > ks                                     # neglected: more of them
    assert kpix < 0.05                                 # cracks are thin lines, not blotches


def test_no_repetition_from_2_to_60_m():
    """ROADNOISE item 5: no tiling or ladder along the road. Once the luminance along the road
    has decorrelated (patches are up to about 15 m), it never correlates again at any lag up
    to 60 m: a repeat or a ladder would show as a second autocorrelation peak."""
    for surface, neglect, wear in [(1.0, 0.63, 0.78), (0.0, 0.75, 0.45)]:
        for across in [0.0, 1.0]:
            p, _ = along_line(length=400.0, step=0.05, across_m=across)
            res = rm.evaluate(p, STRAIGHT, core=1.0, surface=surface, neglect=neglect, wear=wear)
            x = lum(res["col"]) - lum(res["col"]).mean()
            ac = np.correlate(x, x, "full")[len(x) - 1:] / (x.var() * np.arange(len(x), 0, -1))
            lags = np.arange(len(x)) * 0.05
            first_zero = lags[np.argmax(ac < 0.05)]
            assert first_zero < 30.0, (surface, across, first_zero)
            later = (lags >= max(first_zero, 2.0)) & (lags <= 60.0)
            assert ac[later].max() < 0.3, (surface, across, ac[later].max())


# ---- The build script ----------------------------------------------------------------------
def test_build_script_has_one_marker_and_no_hardcoded_extent():
    text = BUILD.read_text(encoding="utf-8")
    assert text.count("__HLSL__") == 1
    assert "816000" not in text


def test_mask_mapping_comes_from_masks_md():
    origin, extent = prep.mask_mapping(ROOT / "Tools" / "Terrain" / "MASKS.md")
    assert origin == (-18920.4, 50.0)
    assert extent == 816000.0


def test_prepared_script_survives_python_run():
    script = prep.prepare(ROOT)
    assert "__HLSL__" not in script and "MASK_EXTENT_CM = None" not in script
    for bad in ["try", "getattr", "open(", ".replace(", "new_level(", "import time"]:
        assert bad not in script, bad
    assert "RoadNormalWS = normalize" in script and "const float3 RP[55]" in script
    # the scanner also refuses a call-shaped "compile (" / "eval (" / "exec (" anywhere, comments included
    assert not re.search(r"(?<![A-Za-z_])(compile|eval|exec)[ ]*[(]", script.replace("recompile_material(", "")), \
        "call-shaped banned word"
    compile(script, "build_road_material", "exec")


# ---- Joint caps ------------------------------------------------------------------------------
def test_joint_cap_covers_the_road_core_around_a_joint(tmp_path):
    import make_joint_cap as cap
    path = tmp_path / "cap.obj"
    cap.write_obj(path)
    verts, uvs, faces = cap.read_obj(path)
    assert len(faces) > 0
    r = max(math.hypot(x, y) for x, y, _ in verts)
    # the core (<= 2.75 m) plus its warped feather lies inside the disc
    assert r >= 450.0 - 1e-3
    assert all(z == 0.0 for _, _, z in verts)


def test_joint_cap_faces_point_up(tmp_path):
    import make_joint_cap as cap
    path = tmp_path / "cap.obj"
    cap.write_obj(path)
    verts, _, faces = cap.read_obj(path)
    for a, b, c in faces:
        (ax, ay, _), (bx, by, _), (cx, cy, _) = verts[a], verts[b], verts[c]
        cross_z = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
        assert cross_z > 0.0   # counter-clockwise seen from +Z in the file's right-handed frame
