"""Offline checks for the ground material (world sprint, Task V2).

    python -m pytest Tools/Road/tests -q

M_Saskarta_Ground is built in the live editor by Tools/Road/build_ground_material.py,
sent through Hayba python_run by Tools/Road/prepare_ground_material.py. Two HLSL bodies
are pasted verbatim into its Custom nodes:

  Shaders/GroundAuto.hlsl  the RVT write pass: rock by slope, dry dirt, moisture-tinted
                           grass and snow by zone, macro tone, from T_Saskarta_Ecology
  Shaders/GroundRead.hlsl  the per-frame read pass: RVT colour plus a detail normal and a
                           near tone variation faded in within 30 m, and the DebugView
                           false-colour mask viewer (1..8)

Both must survive the python_run trip (ASCII, no quotes, backslashes or banned words) and
compile as function bodies. The grass-output density formulas live in the build script as
expression trees that become material nodes; they are evaluated here against the brief's
formulas (Step 3), including Review Focus 3: no grass in the road core where neglect is 0.
The mask UV mapping must come from Tools/Terrain/MASKS.md (Ruling R5), and no T_Gaea_*
texture may be used (Ruling R21).
"""
import math
import pathlib
import re
import shutil
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
AUTO = ROOT / "Shaders" / "GroundAuto.hlsl"
READ = ROOT / "Shaders" / "GroundRead.hlsl"
NOTILE = ROOT / "Shaders" / "GroundNoTile.hlsl"
NOTILE_N = ROOT / "Shaders" / "GroundNoTileNormal.hlsl"
BUILD = ROOT / "Tools" / "Road" / "build_ground_material.py"
sys.path.insert(0, str(ROOT / "Tools" / "Road"))

BANNED = ['"', "'", "\\", "#", "try", "getattr", "open(", ".replace(", "new_level(", "import time"]
AUTO_PINS = ("float4 Eco, float3 N, float2 WorldXY, "
             "float3 RockC, float3 RockM, float3 RockN, float3 DirtC, float3 DirtM, float3 DirtN, "
             "float3 GrassC, float3 GrassM, float3 GrassN, float3 SnowC, float3 SnowM, float3 SnowN, "
             "float3 DryTint, float3 GrassTint, float SlopeLo, float SlopeHi, float GrassLo, float GrassHi, "
             "float SnowLo, float SnowHi, float AlpineLo, float AlpineHi, float AlpineRock, float MacroTone, "
             "float NormalStrength, float ZoneSoft, float4 Road, float HueAmount, float ScreeAmount, "
             "float MottleTone, float MottleHue, float VergeDarken, inout float3 GroundNormal")
NOTILE_PINS = ("float2 UV, float2 DX, float2 DY, float Amount, float Seed, float Turn, "
               "inout float W, inout float4 DA, inout float4 DB, inout float4 RA")
NOTILE_N_PINS = "float3 NA, float3 NB, float W, float4 RA"
READ_PINS = ("float3 BaseColor, float Rough, float3 N, float3 Detail, float2 WorldXY, float Depth, "
             "float NearStart, float NearEnd, float DetailStrength, float MacroNearStrength, "
             "float MacroNearScale, float DebugView, float2 MaskUV, "
             "Texture2D Eco, SamplerState EcoSampler, Texture2D Road, SamplerState RoadSampler, "
             "float RoadLift, float RoadWetRough, float PuddleAmount, float PuddleCut, float RoadDesat, float3 RoadTone, "
             "inout float3 GroundN, inout float3 DebugEmissive")

# Build-script defaults the numeric checks use (they must match SCALARS in the script).
DEFAULTS = dict(SlopeLo=0.16, SlopeHi=0.33, GrassLo=0.42, GrassHi=0.72, SnowLo=0.78, SnowHi=0.85,
                AlpineLo=0.62, AlpineHi=0.78, AlpineRock=0.9, MacroTone=0.12, NormalStrength=1.0)


def code_lines(path):
    out = []
    for line in path.read_text(encoding="ascii").splitlines():
        code = line.split("//")[0].strip()
        if code:
            out.append(code)
    return out


# ---- Both bodies survive the trip and compile ----------------------------------------
@pytest.mark.parametrize("path", [AUTO, READ, NOTILE, NOTILE_N], ids=["auto", "read", "notile", "notile_n"])
def test_body_survives_python_run(path):
    text = path.read_text(encoding="ascii")
    for bad in BANNED:
        assert bad not in text, bad
    assert not re.search(r"(?<![A-Za-z_])(compile|eval|exec)[ ]*[(]", text)


def test_auto_returns_colour_and_roughness_last():
    lines = code_lines(AUTO)
    assert lines[-1] == "return float4(saturate(col), saturate(rough));"
    assert any(l.startswith("GroundNormal = normalize(") for l in lines[:-1])


def test_notile_returns_two_uvs_last():
    lines = code_lines(NOTILE)
    assert lines[-1] == "return float4(rA + Amount * offA, rB + Amount * offB);"
    assert any(l.startswith("W = smoothstep(") for l in lines[:-1])


def test_read_returns_colour_and_roughness_last():
    lines = code_lines(READ)
    assert lines[-1] == "return float4(col, rough);"


def _dxc(tmp_path, name, fn, call):
    src = tmp_path / (name + ".hlsl")
    src.write_text(fn + "\nfloat4 main(float4 p : TEXCOORD0, float4 q : TEXCOORD1) : SV_Target {\n" + call + "\n}\n",
                   encoding="ascii")
    r = subprocess.run(["dxc", "-T", "ps_6_0", "-E", "main", str(src), "-Fo", str(tmp_path / (name + ".bin"))],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


@pytest.mark.skipif(shutil.which("dxc") is None, reason="dxc not on PATH")
def test_auto_compiles_as_a_function(tmp_path):
    fn = "float4 GroundAuto(" + AUTO_PINS + ") {\n" + AUTO.read_text(encoding="ascii") + "\n}\n"
    call = ("  float3 n = float3(0, 0, 1);\n"
            "  float4 c = GroundAuto(p, q.xyz, q.zw * 1000.0, p.rgb, q.rgb, p.gbr, q.gbr, p.brg, q.brg, p.rrg, q.rrg, p.ggb,"
            " q.ggb, p.bbr, q.bbr, p.rgb, q.rgb, p.x, p.y, p.z, p.w, q.x, q.y, p.y, p.z, p.w, q.z, q.w, p.z,"
            " q, p.x, p.y, p.z, p.w, q.x, n);\n"
            "  return c + float4(n, 0);")
    _dxc(tmp_path, "auto", fn, call)


@pytest.mark.skipif(shutil.which("dxc") is None, reason="dxc not on PATH")
def test_notile_compiles_as_a_function(tmp_path):
    fn = "float4 GroundNoTile(" + NOTILE_PINS + ") {\n" + NOTILE.read_text(encoding="ascii") + "\n}\n"
    call = ("  float w = 0; float4 da = 0; float4 db = 0; float4 ra = 0;\n"
            "  float4 c = GroundNoTile(p.xy * 900.0, q.xy, q.zw, q.x, q.y, p.z, w, da, db, ra);\n  return c + w + da + db + ra;")
    _dxc(tmp_path, "notile", fn, call)
    fn = "float3 GroundNoTileNormal(" + NOTILE_N_PINS + ") {\n" + NOTILE_N.read_text(encoding="ascii") + "\n}\n"
    _dxc(tmp_path, "notile_n", fn, "  return float4(GroundNoTileNormal(p.xyz, q.xyz, p.w, q), 1);")


@pytest.mark.skipif(shutil.which("dxc") is None, reason="dxc not on PATH")
def test_read_compiles_as_a_function(tmp_path):
    fn = ("Texture2D EcoTex; SamplerState EcoS; Texture2D RoadTex; SamplerState RoadS;\n"
          "float4 GroundRead(" + READ_PINS + ") {\n" + READ.read_text(encoding="ascii") + "\n}\n")
    call = ("  float3 n = float3(0, 0, 1); float3 e = float3(0, 0, 0);\n"
            "  float4 c = GroundRead(p.rgb, p.a, q.xyz, p.gbr, q.xy, q.z, 2000.0, 3000.0, 0.4, 0.08, 600.0,"
            " q.w, p.xy, EcoTex, EcoS, RoadTex, RoadS, 1.6, 0.8, 0.8, 0.1, 0.5, float3(1.06, 1.0, 0.9), n, e);\n"
            "  return c + float4(n + e, 0);")
    _dxc(tmp_path, "read", fn, call)


# ---- Python port of GroundAuto.hlsl, for the numeric checks -------------------------
def smoothstep(a, b, x):
    t = min(max((x - a) / (b - a), 0.0), 1.0)
    return t * t * (3 - 2 * t)


def sat(x):
    return min(max(x, 0.0), 1.0)


def lerp(a, b, t):
    if isinstance(a, tuple):
        return tuple(a[i] + (b[i] - a[i]) * t for i in range(len(a)))
    return a + (b - a) * t


def norm(v):
    ln = math.sqrt(sum(c * c for c in v))
    return tuple(c / ln for c in v)


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


ROCK_C, DIRT_C, GRASS_C, SNOW_C = (0.30, 0.29, 0.28), (0.25, 0.16, 0.11), (0.14, 0.15, 0.08), (0.80, 0.82, 0.85)
ORM = lambda r: (1.0, r, 0.0)
FLAT = (0.0, 0.0, 1.0)
DRY_TINT, GRASS_TINT = (1.08, 1.02, 0.92), (0.85, 0.95, 0.70)


def auto(eco, n, rock_n=FLAT, dirt_n=FLAT, grass_n=FLAT, snow_n=FLAT, breakup=0.0, zone_soft=None,
         xy=(0.0, 0.0), road=(0.0, 0.0, 0.0, 0.0), **kw):
    # breakup: the shader's metre-scale noise term, zero mean; 0 unless a test sets it.
    # zone_soft: the ZoneSoft pin (Ecology zone at mip 2, about 8 m); the plain zone unless set.
    # xy (cm) and road (RoadInfluence RGBA) feed the LOOK2 colour terms, whose amounts default
    # to 0 here (LOOK2_OFF) so the placement checks see the V2 colours.
    p = dict(DEFAULTS, **dict(LOOK2_OFF, **kw))
    moisture, exposure, zone, macro = eco
    zs = zone if zone_soft is None else zone_soft
    m = macro - 0.5
    n = norm(n)
    slope = 1.0 - sat(n[2])
    slope_rock = smoothstep(p["SlopeLo"], p["SlopeHi"], slope + 0.08 * exposure + 0.06 * m)
    alpine = smoothstep(p["AlpineLo"], p["AlpineHi"], zs + 0.3 * m + 0.15 * breakup)
    rock = max(slope_rock, alpine * p["AlpineRock"])
    grass = smoothstep(p["GrassLo"], p["GrassHi"], moisture + 0.25 * m + 0.3 * breakup) * (1.0 - 0.7 * exposure) * (1.0 - rock)
    snow = smoothstep(p["SnowLo"], p["SnowHi"], zs + 0.8 * m - 0.2 * exposure + 0.5 * breakup) * (1.0 - 0.9 * slope_rock)
    dirt = tuple(DIRT_C[i] * lerp(1.0, DRY_TINT[i], sat(exposure * 1.5)) for i in range(3))
    grass_col = tuple(GRASS_C[i] * GRASS_TINT[i] * (0.75 + 0.5 * moisture) for i in range(3))
    col = lerp(dirt, grass_col, grass)
    col = lerp(col, ROCK_C, rock)
    col = look2_colour(col, moisture, exposure, grass, rock, snow, xy, road, p)
    col = lerp(col, SNOW_C, snow)
    col = tuple(c * (1.0 + p["MacroTone"] * 2.0 * m) for c in col)
    # the test layers have ORM = (1, r, 0): AO 1, so the shader's AO term is neutral here
    rough = lerp(0.9, 0.8, grass)
    rough = lerp(rough, 0.7, rock)
    rough = lerp(rough, 0.5, snow)
    t = lerp(dirt_n, grass_n, grass)
    t = lerp(t, rock_n, rock)
    t = lerp(t, snow_n, snow)
    t = (t[0] * p["NormalStrength"], t[1] * p["NormalStrength"], t[2])
    T = norm(tuple((1.0, 0.0, 0.0)[i] - n[i] * n[0] + (0.0, 0.0001, 0.0)[i] for i in range(3)))
    B = cross(n, T)
    tz = max(t[2], 0.05)
    gn = norm(tuple(t[0] * T[i] + t[1] * B[i] + tz * n[i] for i in range(3)))
    return dict(col=tuple(sat(c) for c in col), rough=sat(rough), normal=gn, rock=rock, grass=grass, snow=snow,
                alpine=alpine, slope_rock=slope_rock)


# ---- LOOK2 colour variation: port of the GroundAuto block between the rock and snow lerps ----
LOOK2_OFF = dict(HueAmount=0.0, ScreeAmount=0.0, MottleTone=0.0, MottleHue=0.0, VergeDarken=0.0)
LOOK2_ON = dict(HueAmount=1.8, ScreeAmount=0.35, MottleTone=0.12, MottleHue=1.0, VergeDarken=0.5)


def _vnoise(px, py):
    qi = (math.floor(px), math.floor(py))
    qf = (px - qi[0], py - qi[1])
    qf = tuple(t * t * (3 - 2 * t) for t in qf)
    hs = []
    for dx, dy in ((0, 0), (1, 0), (0, 1), (1, 1)):
        hh = frac((qi[0] + dx) * 0.1031 + (qi[1] + dy) * 0.1377)
        hs.append(frac(hh * (hh + 33.33) * 71.13))
    return lerp(lerp(hs[0], hs[1], qf[0]), lerp(hs[2], hs[3], qf[0]), qf[1])


def look2_noises(x, y):
    p1 = _vnoise(x / 9000.0 + 3.1, y / 9000.0 + 3.1)
    q1 = p1
    p2 = _vnoise(x / 3500.0 + 11.7, y / 3500.0 + 11.7)
    hp = 0.65 * (p1 - 0.5) + 0.35 * (p2 - 0.5)
    hq = sat(0.5 + 1.6 * (q1 - 0.5) + 0.8 * (p2 - 0.5))
    m1 = _vnoise(x / 800.0 + 5.9, y / 800.0 + 5.9)
    m2 = _vnoise(x / 300.0 + 2.3, y / 300.0 + 2.3)
    mv = 0.6 * (m1 - 0.5) + 0.4 * (m2 - 0.5)
    mh = 0.6 * (m1 - 0.5) - 0.4 * (m2 - 0.5)
    return hp, hq, mv, mh


def test_look2_hue_fields_have_no_contour_jumps():
    """A ten-centimetre camera movement must not cross a wrapped-noise colour seam."""
    for x in range(0, 300000, 7500):
        for y in range(0, 300000, 7500):
            a = look2_noises(float(x), float(y))
            b = look2_noises(float(x) + 10.0, float(y) + 10.0)
            assert 0.0 <= a[1] <= 1.0
            assert -0.5 <= a[3] <= 0.5
            assert abs(a[1] - b[1]) < 0.02
            assert abs(a[3] - b[3]) < 0.10


def look2_colour(col, moisture, exposure, grass, rock, snow, xy, road, p):
    hp, hq, mv, mh = look2_noises(xy[0], xy[1])
    dry_w = sat(1.6 * exposure - 1.2 * moisture + 0.2 + 2.5 * hp)
    dry_hue = lerp((1.18, 0.98, 0.70), (1.26, 0.82, 0.64), hq)
    wet_w = sat(2.5 * (moisture - 0.38) - 2.0 * hp)
    wet_hue = lerp((0.84, 0.97, 0.58), (0.58, 0.78, 0.48), sat(2.0 * moisture - 0.7))
    hue = lerp((1.0, 1.0, 1.0), dry_hue, dry_w * (1.0 - wet_w))
    hue = lerp(hue, wet_hue, wet_w)
    k = p["HueAmount"] * (1.0 - 0.7 * rock)
    col = tuple(col[i] * lerp(1.0, hue[i], k) for i in range(3))
    lum = col[0] * 0.2126 + col[1] * 0.7152 + col[2] * 0.0722
    scree_w = sat(3.0 * (exposure - 0.4) + 1.5 * (hq - 0.5)) * (1.0 - grass) * (1.0 - 0.5 * snow)
    grey = (lum * 0.97, lum * 0.99, lum * 1.04)
    col = lerp(col, grey, p["ScreeAmount"] * scree_w)
    tone = 1.0 + p["MottleTone"] * 2.0 * mv
    swing = (0.10, -0.01, -0.10)
    col = tuple(col[i] * tone * (1.0 + p["MottleHue"] * mh * swing[i]) for i in range(3))
    side = smoothstep(0.7, 0.97, road[1]) * sat(1.0 - 2.0 * road[0])
    vt = (0.72, 0.80, 0.66)
    return tuple(col[i] * lerp(1.0, vt[i], p["VergeDarken"] * side) for i in range(3))


def slope_normal(deg):
    r = math.radians(deg)
    return (math.sin(r), 0.0, math.cos(r))


def test_auto_port_matches_the_hlsl_text():
    # guard against the port drifting from the shader: every weight the port uses is in the body
    text = " ".join(code_lines(AUTO))
    for frag in ["slope + 0.08 * exposure + 0.06 * m", "moisture + 0.25 * m + 0.3 * breakup", "(1.0 - 0.7 * exposure)",
                 "smoothstep(AlpineLo, AlpineHi, ZoneSoft + 0.3 * m + 0.15 * breakup)", "max(slopeRock, alpine * AlpineRock)",
                 "ZoneSoft + 0.8 * m - 0.2 * exposure + 0.5 * breakup", "(1.0 - 0.9 * slopeRock)", "saturate(exposure * 1.5)",
                 "(0.75 + 0.5 * moisture)",
                 "1.0 + MacroTone * 2.0 * m", "max(t.z, 0.05)", "cross(n, T)"]:
        assert frag in text, frag


def test_flat_dry_lowland_is_dirt():
    r = auto((0.2, 0.2, 0.1, 0.5), FLAT)
    assert r["rock"] == 0.0 and r["snow"] == 0.0 and r["grass"] == 0.0
    assert math.dist(r["col"], DIRT_C) < 0.05


def test_steep_slope_is_rock_and_gentle_slope_is_not():
    assert auto((0.3, 0.3, 0.1, 0.5), slope_normal(50))["rock"] > 0.95
    assert auto((0.3, 0.3, 0.1, 0.5), slope_normal(25))["rock"] == 0.0


def test_moist_hollow_is_grass():
    r = auto((0.75, 0.1, 0.1, 0.5), FLAT)
    assert r["grass"] > 0.85
    assert math.dist(r["col"], GRASS_C) < math.dist(r["col"], DIRT_C)


def test_high_zone_is_rock_with_snow_patches_and_cliffs_shed_snow():
    # review finding 1 (fix round 1): above the clouds is rock with snow PATCHES, not a snow blanket.
    # zone ~0.83 and exposure ~0.62 are the Ecology values at 4700 m; macro 0.5 is its median.
    median = auto((0.25, 0.62, 0.83, 0.5), FLAT)
    assert median["snow"] < 0.1                 # the typical high-ground texel is not snow
    assert median["rock"] > 0.85                # it is rock (the alpine term), even on flat ground
    patch = auto((0.25, 0.62, 0.83, 0.7), FLAT, breakup=0.1)
    assert patch["snow"] > 0.9                  # but snow still settles where macro and breakup lift it
    assert auto((0.25, 0.62, 0.9, 0.7), slope_normal(55), breakup=0.1)["snow"] < 0.15   # cliffs shed it
    assert auto((0.3, 0.3, 0.25, 0.5), FLAT)["snow"] == 0.0      # the median map is not snow
    hairpin = auto((0.45, 0.65, 0.43, 0.5), FLAT)                  # the 3850 m hairpin band
    assert hairpin["snow"] == 0.0 and hairpin["alpine"] == 0.0    # neither snow nor alpine rock there


def test_snow_and_alpine_rock_read_the_soft_zone():
    # the Ecology zone steps by 0.3 at the 35-degree slope cut of its snow term; at 2 m texels that
    # step drew stair-stepped snow outlines, so snow and alpine rock read ZoneSoft (mip 2) instead
    hard_step = auto((0.25, 0.62, 0.9, 0.6), FLAT, zone_soft=0.7)
    assert hard_step["snow"] == 0.0            # the plain zone (0.9) would have put snow here
    assert auto((0.25, 0.62, 0.9, 0.6), FLAT)["snow"] == 1.0


def test_alpine_rock_rises_through_the_upper_switchbacks():
    zones = [0.44, 0.6, 0.7, 0.83]            # 3850 m, 4150 m, 4300 m, 4700 m
    rock = [auto((0.3, 0.6, z, 0.5), FLAT)["rock"] for z in zones]
    assert rock[0] == 0.0 and rock[-1] > 0.85
    assert rock == sorted(rock)


def test_snow_breaks_into_patches_with_the_macro_noise():
    # zone and exposure as sampled at 4700 m; the macro noise spans about 0.33..0.69 there
    lo = auto((0.25, 0.62, 0.83, 0.35), FLAT)["snow"]
    hi = auto((0.25, 0.62, 0.83, 0.69), FLAT, breakup=0.1)["snow"]
    assert lo == 0.0 and hi > 0.95
    # and the metre-scale breakup alone splits a mid-coverage field into snow and bare rock
    mid = (0.25, 0.62, 0.83, 0.6)
    assert auto(mid, FLAT, breakup=-0.15)["snow"] < 0.1 and auto(mid, FLAT, breakup=0.15)["snow"] > 0.9


def breakup_port(x_cm, y_cm):
    def octave(px, py):
        qi = (math.floor(px), math.floor(py))
        qf = (px - qi[0], py - qi[1])
        qf = tuple(t * t * (3 - 2 * t) for t in qf)
        hs = []
        for dx, dy in ((0, 0), (1, 0), (0, 1), (1, 1)):
            hh = frac((qi[0] + dx) * 0.1031 + (qi[1] + dy) * 0.1377)
            hs.append(frac(hh * (hh + 33.33) * 71.13))
        return lerp(lerp(hs[0], hs[1], qf[0]), lerp(hs[2], hs[3], qf[0]), qf[1])
    n1 = octave(x_cm / 600.0, y_cm / 600.0)
    n2 = octave(x_cm / 230.0 + 7.3, y_cm / 230.0 + 7.3)
    return 0.65 * (n1 - 0.5) + 0.35 * (n2 - 0.5)


def frac(x):
    return x - math.floor(x)


def test_breakup_noise_is_zero_mean_and_spread():
    vals = [breakup_port(x * 137.0, y * 91.0) for x in range(80) for y in range(80)]
    mean = sum(vals) / len(vals)
    assert abs(mean) < 0.03
    assert min(vals) < -0.2 and max(vals) > 0.2   # enough to split a mid-coverage field


def test_macro_tone_is_neutral_at_half_and_varies_either_side():
    base = auto((0.2, 0.2, 0.1, 0.5), FLAT)["col"]
    dark = auto((0.2, 0.2, 0.1, 0.2), FLAT)["col"]
    light = auto((0.2, 0.2, 0.1, 0.8), FLAT)["col"]
    assert sum(dark) < sum(base) < sum(light)


def test_flat_textures_give_the_geometric_normal_and_all_normals_are_unit():
    for deg in [0, 20, 45, 70]:
        n = auto((0.3, 0.3, 0.1, 0.5), slope_normal(deg))["normal"]
        assert math.dist(n, norm(slope_normal(deg))) < 1e-9
    for tn in [(0.3, -0.2, 0.93), (0.0, 0.0, 1.0), (0.7, 0.7, 0.1)]:
        n = auto((0.5, 0.3, 0.4, 0.3), slope_normal(30), rock_n=tn, dirt_n=tn, grass_n=tn, snow_n=tn)["normal"]
        assert abs(math.sqrt(sum(c * c for c in n)) - 1.0) < 1e-9


def test_texture_green_leans_the_world_normal_along_plus_y():
    # DirectX convention: +G is image-down, which is +V, which world-XY projection maps to +Y
    n = auto((0.2, 0.2, 0.1, 0.5), FLAT, dirt_n=(0.0, 0.5, 0.866))["normal"]
    assert n[1] > 0.4 and abs(n[0]) < 1e-3   # the frame's 1e-4 guard tilts T a hair


# ---- The 4700 m view on the real masks (review finding 1) ------------------------------
ECO_PNG = ROOT / "Saved" / "Masks" / "T_Saskarta_Ecology.png"
HEIGHT_PNG = ROOT / "Saved" / "TerrainRebuild" / "Current_u16.png"
PROFILE = ROOT / "docs" / "story" / "road-profile.json"
_VIEW_CACHE = {}


def _view_inputs(dist_m):
    """Ecology and slope over the ground a camera at road distance dist_m sees (10..160 m
    ahead, +-110 m to the side, 1 m grid), from the baked Ecology mask and the live heightmap."""
    if dist_m in _VIEW_CACHE:
        return _VIEW_CACHE[dist_m]
    np = pytest.importorskip("numpy")
    cv2 = pytest.importorskip("cv2")
    import json
    sys.path.insert(0, str(ROOT / "Tools" / "Story"))
    import build_road_profile as brp
    if "h" not in _VIEW_CACHE:
        _VIEW_CACHE["h"] = brp.Terrain(brp.HEIGHTMAP).h
        _VIEW_CACHE["eco"] = cv2.imread(str(ECO_PNG), cv2.IMREAD_UNCHANGED).astype(np.float32) / 65535.0  # BGRA
    h, eco = _VIEW_CACHE["h"], _VIEW_CACHE["eco"]
    x0, y0, ext = brp.LAND_X0_CM, brp.LAND_Y0_CM, 816000.0
    s = min(json.loads(PROFILE.read_text(encoding="utf-8"))["samples"], key=lambda q: abs(q["dist_m"] - dist_m))
    yaw = math.radians(s["heading_ue_yaw"])
    fw, rt = (math.cos(yaw), math.sin(yaw)), (-math.sin(yaw), math.cos(yaw))
    F, L = np.meshgrid(np.arange(10.0, 160.0), np.arange(-110.0, 110.0))
    X = (s["x_cm"] + 100 * (F * fw[0] + L * rt[0])).ravel()
    Y = (s["y_cm"] + 100 * (F * fw[1] + L * rt[1])).ravel()
    c = np.clip(((X - x0) / 100).astype(int), 1, h.shape[1] - 2)
    r = np.clip(((Y - y0) / 100).astype(int), 1, h.shape[0] - 2)
    nz = 1 / np.sqrt(1 + ((h[r, c + 1] - h[r, c - 1]) / 2) ** 2 + ((h[r + 1, c] - h[r - 1, c]) / 2) ** 2)
    e = eco[((Y - y0) / ext * eco.shape[0]).astype(int), ((X - x0) / ext * eco.shape[1]).astype(int)]
    if "eco2" not in _VIEW_CACHE:   # mip 2: 4x4 texel means, as ZoneSoft samples it
        _VIEW_CACHE["eco2"] = cv2.resize(eco, (eco.shape[1] // 4, eco.shape[0] // 4), interpolation=cv2.INTER_AREA)
    eco2 = _VIEW_CACHE["eco2"]
    zs = eco2[((Y - y0) / ext * eco2.shape[0]).astype(int), ((X - x0) / ext * eco2.shape[1]).astype(int), 0]

    def octave(px, py):
        qi, qf = (np.floor(px), np.floor(py)), [px - np.floor(px), py - np.floor(py)]
        qf = [t * t * (3 - 2 * t) for t in qf]
        hs = []
        for dx, dy in ((0, 0), (1, 0), (0, 1), (1, 1)):
            hh = np.mod((qi[0] + dx) * 0.1031 + (qi[1] + dy) * 0.1377, 1.0)
            hs.append(np.mod(hh * (hh + 33.33) * 71.13, 1.0))
        a, b = hs[0] + (hs[1] - hs[0]) * qf[0], hs[2] + (hs[3] - hs[2]) * qf[0]
        return a + (b - a) * qf[1]

    wx, wy = X - x0, Y - y0
    brk = 0.65 * (octave(wx / 600, wy / 600) - 0.5) + 0.35 * (octave(wx / 230 + 7.3, wy / 230 + 7.3) - 0.5)
    _VIEW_CACHE[dist_m] = (nz, e[:, 1], zs, e[:, 3], brk)   # nz, exposure, soft zone, macro, breakup
    return _VIEW_CACHE[dist_m]


def _view_placement(dist_m, params):
    """Mean snow and mean visible rock over that view: a vectorised port of GroundAuto's placement."""
    np = pytest.importorskip("numpy")
    nz, exposure, zone, macro, brk = _view_inputs(dist_m)   # zone here is ZoneSoft

    def ss(a, b, x):
        t = np.clip((x - a) / (b - a), 0, 1)
        return t * t * (3 - 2 * t)

    m = macro - 0.5
    slope_rock = ss(params["SlopeLo"], params["SlopeHi"], (1 - np.clip(nz, 0, 1)) + 0.08 * exposure + 0.06 * m)
    alpine = ss(params["AlpineLo"], params["AlpineHi"], zone + 0.3 * m + 0.15 * brk)
    rock = np.maximum(slope_rock, alpine * params["AlpineRock"])
    snow = ss(params["SnowLo"], params["SnowHi"], zone + 0.8 * m - 0.2 * exposure + 0.5 * brk) * (1 - 0.9 * slope_rock)
    return float(snow.mean()), float((rock * (1 - snow)).mean())


@pytest.mark.skipif(not (ECO_PNG.exists() and HEIGHT_PNG.exists()), reason="baked masks or heightmap absent")
def test_the_4700_m_view_is_rock_with_snow_patches():
    snow, rock = _view_placement(4700, DEFAULTS)
    assert 0.08 <= snow <= 0.3, snow          # patches, not a blanket (the old defaults gave 0.50)
    assert rock >= 0.6, rock                  # rock dominates
    for d in (4500, 4950):                    # the whole approach stays rock-dominant
        snow, rock = _view_placement(d, DEFAULTS)
        assert snow < 0.45 and rock > snow, (d, snow, rock)


@pytest.mark.skipif(not (ECO_PNG.exists() and HEIGHT_PNG.exists()), reason="baked masks or heightmap absent")
def test_the_old_snow_defaults_blanketed_4700_m():
    # the regression this fix round closes: the shipped defaults put snow on half the view
    old = dict(DEFAULTS, SnowLo=0.6, SnowHi=0.78, AlpineLo=5.0, AlpineHi=6.0)
    old_slope_damping = _view_placement(4700, old)[0]
    assert old_slope_damping > 0.4


# ---- Python port of GroundNoTile.hlsl (review finding 2: anti-tiling) -------------------
R2 = (0.7548776662, 0.5698402910)


def notile(u, v, amount=1.0, seed=0.0, turn=1.0):
    px, py = u * 1.25 + seed * 17.0, v * 1.25 + seed * 17.0
    i = (math.floor(px), math.floor(py))
    f = [px - i[0], py - i[1]]
    f = [t * t * (3 - 2 * t) for t in f]
    hs = []
    for dx, dy in ((0, 0), (1, 0), (0, 1), (1, 1)):
        hh = frac((i[0] + dx) * 0.1031 + (i[1] + dy) * 0.1377)
        hs.append(frac(hh * (hh + 33.33) * 71.13))
    k = lerp(lerp(hs[0], hs[1], f[0]), lerp(hs[2], hs[3], f[0]), f[1])
    l = k * 8.0
    ia = math.floor(l)
    fl = l - ia
    off_a = tuple(frac((ia + seed * 3.0) * g) for g in R2)
    off_b = tuple(frac((ia + 1.0 + seed * 3.0) * g) for g in R2)
    w = smoothstep(0.3, 0.7, fl)
    ang_a = 6.2831853 * frac(ia * 0.6180339887 + seed * 0.29) * amount * turn
    ang_b = 6.2831853 * frac((ia + 1.0) * 0.6180339887 + seed * 0.29) * amount * turn
    ra, rb = rot(ang_a, (u, v)), rot(ang_b, (u, v))
    return (ra[0] + amount * off_a[0], ra[1] + amount * off_a[1]), (rb[0] + amount * off_b[0], rb[1] + amount * off_b[1]), \
        w, ia, (ang_a, ang_b)


def rot(ang, v):
    c, s = math.cos(ang), math.sin(ang)
    return (c * v[0] - s * v[1], s * v[0] + c * v[1])


def unrot_normal(ang, n):
    # GroundNoTileNormal: a normal sampled on rotated UVs, back to the world-XY frame (R transposed)
    c, s = math.cos(ang), math.sin(ang)
    return (c * n[0] + s * n[1], -s * n[0] + c * n[1], n[2])


def test_notile_port_matches_the_hlsl_text():
    text = " ".join(code_lines(NOTILE))
    for frag in ["UV * 1.25 + Seed * 17.0", "float l = k * 8.0;", "float2(0.7548776662, 0.5698402910)",
                 "frac((ia + Seed * 3.0) * g)", "frac((ia + 1.0 + Seed * 3.0) * g)", "W = smoothstep(0.3, 0.7, fl);",
                 "6.2831853 * frac(ia * 0.6180339887 + Seed * 0.29) * Amount * Turn",
                 "6.2831853 * frac((ia + 1.0) * 0.6180339887 + Seed * 0.29) * Amount * Turn",
                 "float2(csA.x * UV.x - csA.y * UV.y, csA.y * UV.x + csA.x * UV.y)",
                 "DA = float4(csA.x * DX.x - csA.y * DX.y, csA.y * DX.x + csA.x * DX.y, csA.x * DY.x - csA.y * DY.y, "
                 "csA.y * DY.x + csA.x * DY.y);",
                 "RA = float4(csA, csB);"]:
        assert frag in text, frag
    ntext = " ".join(code_lines(NOTILE_N))
    for frag in ["float3(RA.x * NA.x + RA.y * NA.y, -RA.y * NA.x + RA.x * NA.y, NA.z)",
                 "float3(RA.z * NB.x + RA.w * NB.y, -RA.w * NB.x + RA.z * NB.y, NB.z)", "return lerp(a, b, W);"]:
        assert frag in ntext, frag


def test_notile_amount_zero_is_the_plain_tile():
    for u, v in [(0.3, 0.7), (12.25, -3.5), (901.1, 407.9)]:
        a, b, w, _, ang = notile(u, v, amount=0.0)
        assert a == (u, v) and b == (u, v) and ang == (0.0, 0.0)


def test_notile_switches_offsets_only_under_zero_weight():
    # Where the index ia changes, samples A and B jump to new offsets. The blend weight must then
    # be exactly 0 or 1, so the jumping sample never shows (no seams; the graph samples with the
    # un-offset UV's derivatives, so the jump cannot pick a wrong mip either).
    step = 0.004
    prev = notile(0.0, 5.0)
    switches = 0
    for n in range(1, 20000):
        cur = notile(n * step, 5.0)
        if cur[3] != prev[3]:
            switches += 1
            assert prev[2] in (0.0, 1.0) and cur[2] in (0.0, 1.0), (n, prev[2], cur[2])
            # the visible pattern is continuous: B before the switch is A after it, and back
            if cur[3] == prev[3] + 1:
                assert prev[2] == 1.0 and cur[2] == 0.0
            elif cur[3] == prev[3] - 1:
                assert prev[2] == 0.0 and cur[2] == 1.0
        prev = cur
    assert switches > 20   # 80 tiles along the line: the pattern changes copy many times


def test_notile_rotates_copies_and_normals_come_back_to_the_world_frame():
    # each copy is turned by its own angle, so the dirt's streaks do not all run one way
    angles = {round(notile(u * 0.37, v * 0.41)[4][0], 6) for u in range(60) for v in range(60)}
    assert len(angles) >= 6
    spread = sorted(a % math.pi for a in angles)
    assert max(b - a for a, b in zip(spread, spread[1:] + [spread[0] + math.pi])) < math.pi / 2.5
    # a world-frame normal tilt seen through a rotated copy (the texture holds R n) un-rotates exactly
    for ang in (0.3, 1.9, 4.4):
        n = (0.3, -0.2, 0.93)
        seen = rot(ang, n[:2]) + (n[2],)
        back = unrot_normal(ang, seen)
        assert all(abs(back[i] - n[i]) < 1e-12 for i in range(3))


def test_rock_copies_turn_only_a_little():
    # the rock set is stratified: turned freely, its strata read as fur (fix round 1 captures), so
    # rock turns by at most Turn * 360 degrees while dirt and grass turn freely
    text = build_text()
    turns = dict(re.findall(r"'(Rock|Dirt|Grass|Snow)': ([0-9.]+)", text[text.index("TURN = {"):]))
    assert float(turns["Rock"]) * 360.0 <= 30.0
    assert float(turns["Dirt"]) == 1.0 and float(turns["Grass"]) == 1.0
    angs = [notile(u * 0.37, v * 0.41, turn=float(turns["Rock"]))[4][0] for u in range(40) for v in range(40)]
    assert max(angs) <= math.radians(30.0) and max(angs) > 0.0


def test_notile_uses_many_offset_copies_and_differs_per_layer():
    seen = {notile(u * 0.37, v * 0.41)[3] for u in range(60) for v in range(60)}
    assert len(seen) >= 6
    a0 = notile(3.3, 4.4, seed=0.0)[0]
    a1 = notile(3.3, 4.4, seed=1.0)[0]
    assert a0 != a1


# ---- Python port of GroundRead.hlsl ----------------------------------------------------
def read_fade(depth, start=2000.0, end=3000.0):
    return sat((end - depth) / max(end - start, 1.0))


def debug_pick(debug_view, road, eco):
    k = math.floor(debug_view + 0.5)
    sel = road if k < 4.5 else eco
    kk = k if k < 4.5 else k - 4.0
    return sum(sel[i] * (1.0 if kk == i + 1 else 0.0) for i in range(4))


def jet(v):
    return tuple(sat(1.5 - abs(4.0 * v - c)) for c in (3.0, 2.0, 1.0))


def test_read_port_matches_the_hlsl_text():
    text = " ".join(code_lines(READ))
    for frag in ["saturate((NearEnd - Depth) / max(NearEnd - NearStart, 1.0))", "floor(DebugView + 0.5)",
                 "k < 4.5 ? r : e", "k < 4.5 ? k : k - 4.0", "1.5 - abs(4.0 * v - float3(3.0, 2.0, 1.0))",
                 "if (DebugView > 0.5)", "SampleGrad("]:
        assert frag in text, frag


def test_near_detail_fades_out_by_30_m():
    assert read_fade(500.0) == 1.0
    assert read_fade(2500.0) == 0.5
    assert read_fade(3000.0) == 0.0 and read_fade(90000.0) == 0.0


def test_debug_view_picks_each_mask_channel():
    road, eco = (0.11, 0.22, 0.33, 0.44), (0.55, 0.66, 0.77, 0.88)
    want = {1: 0.11, 2: 0.22, 3: 0.33, 4: 0.44, 5: 0.55, 6: 0.66, 7: 0.77, 8: 0.88}
    for k, v in want.items():
        assert debug_pick(k, road, eco) == v
        assert debug_pick(k + 0.3, road, eco) == v   # a slider left between integers still picks one


def test_false_colour_is_blue_to_red():
    assert jet(0.0)[2] > 0.4 and jet(0.0)[0] == 0.0
    assert jet(1.0)[0] > 0.4 and jet(1.0)[2] == 0.0
    assert jet(0.5)[1] == 1.0


# ---- The build script: grass densities, mapping, textures -------------------------
def build_text():
    return BUILD.read_text(encoding="utf-8")


def formulas():
    text = build_text()
    start = text.index("# ---- FORMULAS BEGIN")
    end = text.index("# ---- FORMULAS END")
    scope = {}
    exec(text[start:end], scope)
    return scope


def evaluate(tree, env):
    op = tree[0]
    if op == "in":
        return env[tree[1]]
    if op == "const":
        return tree[1]
    args = [evaluate(t, env) for t in tree[1:]]
    return {"add": lambda a, b: a + b, "sub": lambda a, b: a - b, "mul": lambda a, b: a * b,
            "om": lambda a: 1.0 - a, "sat": lambda a: sat(a)}[op](*args)


def crown(core, neglect):
    # LOOK2 (task-LOOK2-brief.md A.2): V2's crown term core * neglect^2 * 0.8 carpeted the whole
    # road at 200 m (neglect 0.72 -> 0.41). Only truly abandoned stretches (neglect > 0.8) grow
    # crown tufts, sparsely: 0 at neglect 0.8, rising to 0.15 at neglect 1.
    return core * sat((neglect - 0.8) / 0.2) * 0.15


def brief_near(m, e, core, verge, neglect):
    return (sat((0.25 + 0.75 * m) * (1 - e * 0.8)) * off_core(core) * shoulder(verge)
            * (1 - verge * (1 - neglect) * 0.85) + crown(core, neglect))


def shoulder(verge):
    # LOOK2 fix round 1 (review 4): no foliage within ~3 m of the centreline (verge >= 0.835),
    # full again from ~4.5 m (verge <= 0.74); the verge mask falls linearly with distance
    return sat((0.835 - verge) / (0.835 - 0.74))


def off_core(core):
    # Task V3 fix round 1 hardened the brief's (1 - core) to saturate(1 - 2 core). LOOK2 ("less
    # foliage inside the road"): the RVT road's noise-warped edge reaches out to core ~0.15, so
    # every foliage type is zero from core 0.3 inward and full again at core 0.
    return sat(1 - core / 0.3)


def grid():
    vals = [0.0, 0.1, 0.35, 0.5, 0.8, 1.0]
    for m in vals:
        for e in vals:
            for c in vals:
                for v in vals:
                    for n in vals:
                        yield dict(moisture=m, exposure=e, core=c, verge=v, neglect=n)


def test_grass_near_is_the_brief_formula():
    f = formulas()
    for env in grid():
        want = brief_near(env["moisture"], env["exposure"], env["core"], env["verge"], env["neglect"])
        assert abs(evaluate(f["GRASS_NEAR"], env) - want) < 1e-12, env


def test_reeds_are_moisture_squared_off_the_core():
    f = formulas()
    for env in grid():
        want = env["moisture"] ** 2 * off_core(env["core"]) * shoulder(env["verge"])
        assert abs(evaluate(f["REEDS"], env) - want) < 1e-12


def test_dry_grass_weights_exposure_up():
    f = formulas()
    base = dict(moisture=0.3, core=0.0, verge=0.0, neglect=0.5)
    lo = evaluate(f["GRASS_DRY"], dict(base, exposure=0.1))
    hi = evaluate(f["GRASS_DRY"], dict(base, exposure=0.8))
    assert hi > lo
    near_lo = evaluate(f["GRASS_NEAR"], dict(base, exposure=0.1))
    near_hi = evaluate(f["GRASS_NEAR"], dict(base, exposure=0.8))
    assert near_hi < near_lo   # near grass goes the other way


def test_no_grass_of_any_kind_in_the_road_core_where_neglect_is_zero():
    # Review Focus 3
    f = formulas()
    for m in [0.0, 0.5, 1.0]:
        for e in [0.0, 0.5, 1.0]:
            for v in [0.0, 1.0]:
                env = dict(moisture=m, exposure=e, core=1.0, verge=v, neglect=0.0)
                for name in ("GRASS_NEAR", "GRASS_DRY", "REEDS"):
                    assert evaluate(f[name], env) == 0.0, (name, env)


def test_no_off_core_grass_from_the_core_half_way_contour_inward():
    # Review Focus 3, Task V3 fix round 1: at neglect 0 nothing grows anywhere core >= 0.5,
    # the bilinear edge band included (the V3 probe found 11 tufts at core 0.50-0.63 at 4,350 m).
    f = formulas()
    for core in [0.5, 0.55, 0.6, 0.63, 0.7, 0.8, 0.9, 1.0]:
        for m in [0.0, 0.5, 1.0]:
            for e in [0.0, 0.5, 1.0]:
                for v in [0.0, 0.5, 1.0]:
                    env = dict(moisture=m, exposure=e, core=core, verge=v, neglect=0.0)
                    for name in ("GRASS_NEAR", "GRASS_DRY", "REEDS"):
                        assert evaluate(f[name], env) == 0.0, (name, env)


def test_off_core_grass_is_full_off_the_road():
    f = formulas()
    env = dict(moisture=0.6, exposure=0.2, core=0.0, verge=0.0, neglect=0.3)
    assert abs(evaluate(f["REEDS"], env) - 0.36) < 1e-12
    assert evaluate(f["GRASS_NEAR"], env) > 0.5


def test_crown_tufts_only_on_abandoned_core_and_sparse():
    # LOOK2 A.2: only neglect > 0.8 may grow crown tufts, never a full-width carpet
    f = formulas()
    for neglect in [0.0, 0.3, 0.57, 0.72, 0.8]:     # 0.57 is 1050 m, 0.72 is 200 m
        env = dict(moisture=0.8, exposure=0.0, core=1.0, verge=1.0, neglect=neglect)
        assert abs(evaluate(f["GRASS_NEAR"], env)) < 1e-12, neglect
    top = evaluate(f["GRASS_NEAR"], dict(moisture=0.8, exposure=0.0, core=1.0, verge=1.0, neglect=1.0))
    assert abs(top - 0.15) < 1e-12
    # 2,300 m (neglect 0.87): about 0.05, i.e. well under one blade per m2 at 12 per m2
    mid = evaluate(f["GRASS_NEAR"], dict(moisture=0.4, exposure=0.3, core=1.0, verge=1.0, neglect=0.87))
    assert 0.03 < mid < 0.06


def test_the_old_crown_carpeted_the_200_m_road():
    # the V2 term at the 200 m stretch, for the record: 0.8 * 0.72^2 = 0.41 (about 5 blades per m2)
    assert abs(0.8 * 0.72 * 0.72 - 0.41472) < 1e-9
    f = formulas()
    assert evaluate(f["GRASS_NEAR"], dict(moisture=0.37, exposure=0.19, core=1.0, verge=0.95, neglect=0.72)) == 0.0


def test_no_foliage_where_the_rvt_road_can_draw():
    # LOOK2: the RVT road draws where core + 0.55 (edgeNoise - 0.5) > 0.4..0.55, which reaches
    # core ~0.15 at the noise's top; nothing grows from core 0.3 inward below neglect 0.8
    f = formulas()
    for core in [0.3, 0.35, 0.45, 0.5, 0.7, 1.0]:
        for m in [0.0, 0.5, 1.0]:
            for e in [0.0, 0.5, 1.0]:
                for n in [0.0, 0.5, 0.8]:
                    env = dict(moisture=m, exposure=e, core=core, verge=0.97, neglect=n)
                    for name in ("GRASS_NEAR", "GRASS_DRY", "REEDS"):
                        assert evaluate(f[name], env) <= 1e-12, (name, env)


def test_no_foliage_on_the_road_shoulder_below_the_crown_neglect():
    # LOOK2 fix round 1 (review 4): at 1050 m tufts rooted at core 0.15-0.3, right on the visible
    # road edge. Within verge 0.835 (about 3 m of the centreline) nothing grows off the crown term,
    # even where core has already fallen to 0.
    f = formulas()
    for verge in [0.835, 0.85, 0.9, 0.97]:
        for core in [0.0, 0.05, 0.15, 0.3]:
            for m in [0.0, 0.5, 1.0]:
                for e in [0.0, 0.5, 1.0]:
                    for n in [0.0, 0.61, 0.8]:
                        env = dict(moisture=m, exposure=e, core=core, verge=verge, neglect=n)
                        for name in ("GRASS_NEAR", "GRASS_DRY", "REEDS"):
                            assert evaluate(f[name], env) <= 1e-12, (name, env)


def test_foliage_returns_over_the_next_1_5_m_of_verge():
    f = formulas()
    base = dict(moisture=0.6, exposure=0.3, core=0.0, neglect=0.6)
    w = [evaluate(f["GRASS_DRY"], dict(base, verge=v)) for v in (0.83, 0.80, 0.77, 0.74, 0.70)]
    assert w == sorted(w) and w[0] < 0.05 * w[-1]
    full = sat((0.25 + 0.75 * 0.3) * (1 - 0.8 * 0.6)) * (1 - 0.74 * 0.4 * 0.85)
    assert abs(w[3] - full) < 1e-9


def test_densities_stay_in_zero_one():
    f = formulas()
    for env in grid():
        for name in ("GRASS_NEAR", "GRASS_DRY", "REEDS"):
            assert -1e-12 <= evaluate(f[name], env) <= 1.0 + 1e-12, (name, env)


def test_grass_output_names_the_three_types():
    f = formulas()
    assert [g[0] for g in f["GRASS_OUTPUTS"]] == ["NearGrass", "DryGrass", "Reeds"]
    assert [g[1].rsplit("/", 1)[1] for g in f["GRASS_OUTPUTS"]] == [
        "LGT_Saskarta_NearGrass", "LGT_Saskarta_DryGrass", "LGT_Saskarta_Reeds"]


def test_build_script_markers_mapping_and_no_gaea():
    text = build_text()
    assert text.count("__AUTO__") == 1 and text.count("__READ__") == 1
    assert "816000" not in text and "815900" not in text
    assert "T_Gaea_" not in text   # Ruling R21
    assert "RVT_Saskarta_Terrain" in text


def test_build_uses_notile_sampling_not_the_transposed_self_blend():
    text = build_text()
    assert "AntiTile" not in text and "2.37" not in text          # the diamond-making mirror blend is gone
    assert "GroundNoTile" in text and "'DDX(UVs)'" in text and "'DDY(UVs)'" in text
    assert "GroundNoTileNormal" in text and text.count("__NOTILE_N__") == 1
    assert "TMVM_DERIVATIVE" in text
    assert "link(eco_soft, 'B', auto, 'ZoneSoft')" in text
    assert text.count("__NOTILE__") == 1


def test_layer_tiles_and_detail_source():
    text = build_text()
    rows = re.findall(r"\('(Rock|Dirt|Grass|Snow)', '[^']*', ([0-9.]+),", text)
    assert dict((k, float(v)) for k, v in rows) == {"Rock": 900.0, "Dirt": 520.0, "Grass": 400.0, "Snow": 700.0}
    # the near detail normal is the uniform forest-ground normal, not the blotchy aerial dirt one
    assert "DETAIL_TEXTURE = '/Game/Pallbearer/Terrain/Tex/T_PH_forest_ground_04_nor_gl'" in text
    assert "('DetailTile', 230.0, 'Near')" in text


def test_scalar_defaults_match_the_numeric_checks():
    text = build_text()
    for name, value in DEFAULTS.items():
        assert re.search(r"\('" + name + r"', " + re.escape(repr(value)) + r"\b", text), name


def test_prepared_script_survives_python_run():
    import prepare_ground_material as prep
    script = prep.prepare(ROOT)
    assert "__AUTO__" not in script and "__READ__" not in script and "__NOTILE__" not in script
    assert "return float4(rA + Amount * offA, rB + Amount * offB);" in script
    assert "return lerp(a, b, W);" in script and "__NOTILE_N__" not in script
    assert "MASK_EXTENT_CM = None" not in script and "MASK_EXTENT_CM = 816000.0" in script
    for bad in ["try", "getattr", "open(", ".replace(", "new_level(", "import time"]:
        assert bad not in script, bad
    assert not re.search(r"(?<![A-Za-z_])(compile|eval|exec)[ ]*[(]", script.replace("recompile_material(", ""))
    assert "GroundNormal = normalize(" in script and "DebugEmissive" in script
    compile(script, "build_ground_material", "exec")


# ---- LOOK2: colour variation (write pass) ------------------------------------------------
def _hue_deg(c):
    r, g, b = c
    mx, mn = max(c), min(c)
    if mx - mn < 1e-9:
        return None
    if mx == r:
        h = ((g - b) / (mx - mn)) % 6.0
    elif mx == g:
        h = (b - r) / (mx - mn) + 2.0
    else:
        h = (r - g) / (mx - mn) + 4.0
    return 60.0 * h


def _circ_std_deg(hues):
    s = sum(math.sin(math.radians(h)) for h in hues) / len(hues)
    c = sum(math.cos(math.radians(h)) for h in hues) / len(hues)
    return math.degrees(math.sqrt(-2.0 * math.log(max(math.hypot(s, c), 1e-12))))


def test_look2_port_matches_the_hlsl_text():
    text = " ".join(code_lines(AUTO))
    for frag in ["WorldXY / 9000.0 + 3.1", "WorldXY / 3500.0 + 11.7", "WorldXY / 800.0 + 5.9", "WorldXY / 300.0 + 2.3",
                 "saturate(1.6 * exposure - 1.2 * moisture + 0.2 + 2.5 * hp)", "float3(1.18, 0.98, 0.70)",
                 "float3(1.26, 0.82, 0.64)", "saturate(2.5 * (moisture - 0.38) - 2.0 * hp)", "float3(0.84, 0.97, 0.58)",
                 "float3(0.58, 0.78, 0.48)", "HueAmount * (1.0 - 0.7 * rock)", "saturate(3.0 * (exposure - 0.4) + 1.5 * (hq - 0.5))",
                 "lum * float3(0.97, 0.99, 1.04)", "(1.0 + MottleTone * 2.0 * mv)", "float3(0.10, -0.01, -0.10)",
                 "smoothstep(0.7, 0.97, Road.g) * saturate(1.0 - 2.0 * Road.r)", "float3(0.72, 0.80, 0.66)",
                 "0.6 * (m1 - 0.5) - 0.4 * (m2 - 0.5)", "float q1 = p1"]:
        assert frag in text, frag
    # the variation sits between the rock and snow lerps, so snow stays white
    assert text.index("col = lerp(col, RockC, rock);") < text.index("HueAmount") < text.index("col = lerp(col, SnowC, snow);")


def test_look2_off_is_the_v2_colour():
    for eco in [(0.2, 0.2, 0.1, 0.5), (0.75, 0.1, 0.1, 0.5), (0.3, 0.7, 0.3, 0.4)]:
        for xy in [(0.0, 0.0), (123456.0, 654321.0)]:
            a = auto(eco, FLAT, xy=xy, road=(0.0, 1.0, 0.5, 0.0))["col"]
            b = auto(eco, FLAT)["col"]
            assert math.dist(a, b) < 1e-12


def _field(eco_of, params, n=60, step=4700.0):
    out = []
    for i in range(n):
        for j in range(n):
            x, y = 40000.0 + i * step, 90000.0 + j * step * 1.3
            out.append(auto(eco_of(i, j), FLAT, xy=(x, y), **params)["col"])
    return out


def _eco_walk(i, j):
    # a spread of lowland ecology like the valley's: moisture 0.2-0.7, exposure 0.1-0.5
    return (0.2 + 0.5 * ((i * 7 + j * 3) % 11) / 10.0, 0.1 + 0.4 * ((i * 5 + j * 11) % 13) / 12.0, 0.1, 0.5)


def test_look2_widens_the_hue_spread_of_the_lowland_ground():
    before = [_hue_deg(c) for c in _field(_eco_walk, LOOK2_OFF)]
    after = [_hue_deg(c) for c in _field(_eco_walk, LOOK2_ON)]
    sb, sa = _circ_std_deg([h for h in before if h is not None]), _circ_std_deg([h for h in after if h is not None])
    assert sa > 1.3 * sb, (sb, sa)


def test_look2_hues_stay_earth_and_green_never_magenta_or_blue():
    for c in _field(_eco_walk, LOOK2_ON):
        h = _hue_deg(c)
        mx = max(c)
        if h is None or (mx - min(c)) / mx < 0.08:
            continue                         # near-grey scree: hue is meaningless
        assert 0.0 <= h <= 130.0, (h, c)     # red-orange through ochre to green


def test_look2_dry_is_warmer_and_moist_is_greener():
    xy = (250000.0, 300000.0)
    base = auto((0.25, 0.5, 0.1, 0.5), FLAT, xy=xy)["col"]
    dry = auto((0.25, 0.5, 0.1, 0.5), FLAT, xy=xy, HueAmount=1.0)["col"]
    assert dry[0] / dry[2] > base[0] / base[2]
    wb = auto((0.75, 0.1, 0.1, 0.5), FLAT, xy=xy)["col"]
    wet = auto((0.75, 0.1, 0.1, 0.5), FLAT, xy=xy, HueAmount=1.0)["col"]
    assert wet[1] / wet[0] > wb[1] / wb[0]


def test_look2_mottling_is_zero_mean_at_2_to_10_m():
    vals = [look2_noises(x * 97.0, y * 131.0)[2] for x in range(90) for y in range(90)]
    assert abs(sum(vals) / len(vals)) < 0.03 and min(vals) < -0.15 and max(vals) > 0.15
    # it varies within 10 m (it is not a large-patch term)
    a = [look2_noises(50000.0 + k * 100.0, 70000.0)[2] for k in range(10)]
    assert max(a) - min(a) > 0.05


def test_look2_hue_patches_are_large_scale():
    # neighbouring metres agree, patches 100 m apart differ
    hp = [look2_noises(80000.0 + k * 100.0, 120000.0)[0] for k in range(200)]
    steps = [abs(hp[k + 1] - hp[k]) for k in range(len(hp) - 1)]
    assert max(steps) < 0.05
    assert max(hp) - min(hp) > 0.3


def test_look2_roadside_is_darker_only_beside_the_road():
    eco, xy = (0.4, 0.2, 0.1, 0.5), (100000.0, 100000.0)
    far = auto(eco, FLAT, xy=xy, road=(0.0, 0.3, 0.7, 0.0), VergeDarken=0.5)["col"]
    side = auto(eco, FLAT, xy=xy, road=(0.0, 0.97, 0.7, 0.0), VergeDarken=0.5)["col"]
    plain = auto(eco, FLAT, xy=xy)["col"]
    assert math.dist(far, plain) < 1e-12
    assert sum(side) < 0.9 * sum(plain)
    assert side[1] / side[0] > plain[1] / plain[0]          # greener
    on_core = auto(eco, FLAT, xy=xy, road=(0.8, 1.0, 0.7, 0.0), VergeDarken=0.5)["col"]
    assert math.dist(on_core, plain) < 1e-12               # under the road it changes nothing


# ---- LOOK2: the road in the read pass -------------------------------------------------------
def luma(c):
    return c[0] * 0.2126 + c[1] * 0.7152 + c[2] * 0.0722


def read_road(base, rough, core, lum_cut=0.1, pn=0.9, lift=1.6, wet=0.8, amount=0.8, desat=0.0,
              tone=(1.06, 1.0, 0.9)):
    in_core = smoothstep(0.5, 0.85, core)
    lum = luma(base)
    dark = sat((lum_cut - lum) / max(0.25 * lum_cut, 0.001))
    puddle = in_core * amount * dark * smoothstep(0.55, 0.65, pn)
    lifted = tuple(c * lerp(1.0, lift, in_core) for c in base)
    tn = tuple(t / max(luma(tone), 0.001) for t in tone)
    grey = luma(lifted)
    col = tuple(lerp(c, grey * t, in_core * desat) * (1.0 - 0.45 * puddle) for c, t in zip(lifted, tn))
    r = lerp(rough * lerp(1.0, wet, in_core), 0.08, puddle)
    return col, r, puddle


def test_read_road_port_matches_the_hlsl_text():
    text = " ".join(code_lines(READ))
    for frag in ["smoothstep(0.5, 0.85, r.x)", "WorldXY / 160.0 + 4.7",
                 "saturate((PuddleCut - lum) / max(0.25 * PuddleCut, 0.001))",
                 "inCore * PuddleAmount * dark * smoothstep(0.55, 0.65, pn)", "col *= lerp(1.0, RoadLift, inCore);",
                 "float3 tone = RoadTone / max(dot(RoadTone, lw), 0.001);",
                 "col = lerp(col, dot(col, lw) * tone, inCore * RoadDesat);",
                 "rough *= lerp(1.0, RoadWetRough, inCore);", "col *= 1.0 - 0.45 * puddle;",
                 "rough = lerp(rough, 0.08, puddle);"]:
        assert frag in text, frag
    # one road-mask sample outside the DebugView branch, the Ecology one inside it
    assert text.count("Road.SampleGrad(") == 1 and text.count("Eco.SampleGrad(") == 1
    assert text.index("Road.SampleGrad(") < text.index("if (DebugView > 0.5)") < text.index("Eco.SampleGrad(")


def test_road_core_is_lifted_and_the_verge_is_not():
    ground = (0.12, 0.09, 0.07)
    col, r, _ = read_road(ground, 0.9, core=1.0, pn=0.0)
    assert abs(col[0] / ground[0] - 1.6) < 1e-9 and abs(r - 0.72) < 1e-9
    for core in [0.0, 0.3, 0.5]:
        col, r, pud = read_road(ground, 0.9, core=core)
        assert col == ground and r == 0.9 and pud == 0.0


def chroma_ratio(c):
    return (max(c) - min(c)) / max(max(c), 1e-9)


def test_road_core_turns_toward_warm_grey_stone_at_the_same_luminance():
    # LOOK2 fix round 1 (review 7): the lift alone kept the core the ground's own ochre
    ochre = (0.30, 0.20, 0.10)
    lifted, _, _ = read_road(ochre, 0.9, core=1.0, pn=0.0, lift=1.3, desat=0.0)
    toned, _, _ = read_road(ochre, 0.9, core=1.0, pn=0.0, lift=1.3, desat=0.5)
    assert abs(luma(toned) - luma(lifted)) < 1e-9
    assert chroma_ratio(toned) < 0.7 * chroma_ratio(lifted)
    assert toned[0] > toned[1] > toned[2]          # still warm: a warm grey, never blue
    for core in [0.0, 0.3, 0.5]:                   # the verge keeps its colour
        assert read_road(ochre, 0.9, core=core, desat=0.5)[0] == ochre


def test_puddles_stand_only_in_dark_core_texels():
    rut, paving = (0.06, 0.045, 0.035), (0.14, 0.124, 0.104)
    _, r, pud = read_road(rut, 0.85, core=1.0, pn=0.9)
    assert pud > 0.7 and r < 0.25
    assert read_road(paving, 0.86, core=1.0, pn=0.9)[2] == 0.0      # light paving: no water
    assert read_road(rut, 0.85, core=1.0, pn=0.3)[2] == 0.0         # outside the puddle blobs
    assert read_road(rut, 0.85, core=0.3, pn=0.9)[2] == 0.0         # never on the verge


def test_new_parameters_have_their_defaults():
    text = build_text()
    for name, value in dict(LOOK2_ON, RoadLift=1.5, RoadWetRough=0.8, PuddleAmount=0.8, PuddleCut=0.1,
                            RoadDesat=0.5).items():
        assert re.search(r"\('" + name + r"', " + re.escape(repr(value)) + r"\b", text), name
    assert "link(road, 'RGBA', auto, 'Road')" in text


def test_the_grass_layer_is_not_tinted_pink():
    # LOOK2 fix round 1 (review 3): the inherited Grass Tint (1.10, 0.62, 0.72) turned moist ground rust
    f = formulas_and_constants()
    r, g, b = f["LAYER_TINT_OVERRIDE"]["Grass"]
    assert g >= r and g >= b


def formulas_and_constants():
    text = build_text()
    start = text.index("LAYER_TINT_OVERRIDE = ")
    scope = {}
    exec(text[start:text.index(chr(10), start)], scope)
    return scope
