"""Editor builder for the stele scan (task STELESCAN): POM-carved inscriptions and the scan sweep.

Design: docs/look/STELE_SCAN.md (runbook at its end). Every editor step is ONE small Hayba python_run
(5 s budget, none of python_run's banned words: no "try" anywhere, including inside words such as
geometry or entry), run from the repo root with the editor open, NO PIE, holding the editor gate
(Tools/GameFlow/editor_gate.py). If a step reports an HCR-NATIVE fault, stop and restart the editor.

    python Tools/Look/build_stele_scan.py check          # offline: atlas up to date, data, scripts, banned words, read-only flags
    python Tools/Look/build_stele_scan.py import-atlas   # T_Inscr_Atlas_H (G8) + T_Inscr_Atlas_N (BC5, flip green), one call each
    python Tools/Look/build_stele_scan.py material       # M_Saskarta_SteleFace: create, node chunks, links, compile (own calls)
    python Tools/Look/build_stele_scan.py instance       # MI_SteleFace (add --no-pom for the flat fallback)
    python Tools/Look/build_stele_scan.py load           # World Partition: load the 36 stele actors (own calls)
    python Tools/Look/build_stele_scan.py cpd            # tags + Custom Primitive Data defaults per stele (chunks, own calls)
    python Tools/Look/build_stele_scan.py save           # the stele actor packages only, chunks of 20 (own calls)
    python Tools/Look/build_stele_scan.py unload         # own call, after the save
    python Tools/Look/build_stele_scan.py assign         # Face slot (1) of the 4 stele meshes -> MI_SteleFace, one call each
    python Tools/Look/build_stele_scan.py verify         # resident, load, check, unload (own calls)
    python Tools/Look/build_stele_scan.py da             # DA_Saskarta_SteleScan <- docs/story/inscriptions.json (needs the C++ built)

Order: check, import-atlas, material, instance, load, cpd, save, unload, verify --face old, assign,
verify, da. `cpd` comes before `assign`: a stone whose Custom Primitive Data is not written yet would show
cell 0 at a zero-size rectangle (the material guards the divide, so it shows no glyph, but the order
keeps the glyphs on screen the whole way through).

M_Saskarta_SteleFace (opaque, Nanite usage), on the stele meshes' Face slot:
  rock      as M_Saskarta_Stele: RockColor/RockNormal on UV0 x RockTiling, Tint, vertex colour cavity
            (R), ground grime (G), worn edges (B)
  cell      cellUV = (UV1 - CellRect.xy) / max(CellRect.zw, 1e-4); inCell = the rectangle mask;
            origin = (fmod(Cell, 8), floor(Cell / 8)) x (1/8, 1/4); atlasUV = origin + clamp(cellUV) x (1/8, 1/4)
  POM       /Engine/.../ParallaxOcclusionMapping on InscrHeightObj (T_Inscr_Atlas_H), Heightmap Channel
            (1, 0, 0, 0), Reference Plane 1, no shadows; Height Ratio = GrooveDepthCm / 400 x (1 - 0.6 Wear) x k,
            Min/Max Steps = max(1, 8k) / max(1, 24k), k = inCell x (1 - fade(PixelDepth, 25 m -> 40 m))
            x graze(dot(VertexNormalWS, CameraVectorWS)); parallax UVs clamped to the cell minus half a
            texel; static switch UsePOM (off = the atlas normal and AO only)
  glyph     InscrNormal and InscrHeight at the parallax UVs; AO from InscrHeightBlur (mip bias 2);
            cut = saturate(3 (1 - H)) x inCell x (1 - Wear x noise) x GlyphDepth; darker grooves, dust
            fill, whiteout normal blend
  scan      t = Time - ScanStart; sweep = lerp(MatchSweepS, SweepS, ScanMode > 0.75); a thin amber line
            at v = t / sweep runs down the face (UV1 v: 0 top, 1 bottom; the script reads top to bottom);
            grooves it passed glow at GlowLevel until max(GlowHoldS, sweep + 0.3), then fade over GlowFadeS;
            Emissive = ScanColor x ScanGlow x ScanMode x (band (0.15 + 1.5 cut) + glow): exactly 0 when idle
  CPD       0 Wear, 1 Cell, 2 ScanStart, 3 ScanMode, 4-7 CellRect, 8 GlowHoldS. 0, 1, 4-7 are component
            defaults written by `cpd`; 2, 3, 8 are written at runtime by USaskartaSteleScanner.
"""
import argparse
import json
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Tools" / "Look"))
from apply_look import check_banned, python_run  # noqa: E402

DATA = ROOT / "docs" / "story" / "inscriptions.json"
ATLAS_DIR = ROOT / "SourceArt" / "Inscriptions" / "atlas"
STELE_DIR = "/Game/SaskartaGaea/Steles"
INSCR_DIR = "/Game/SaskartaGaea/Inscriptions"
MAT_NAME = "M_Saskarta_SteleFace"
MAT = f"{STELE_DIR}/{MAT_NAME}"
MI_NAME = "MI_SteleFace"
MI = f"{STELE_DIR}/{MI_NAME}"
TEX_H = f"{INSCR_DIR}/T_Inscr_Atlas_H"
TEX_N = f"{INSCR_DIR}/T_Inscr_Atlas_N"
DA_NAME = "DA_Saskarta_SteleScan"
DA = f"{INSCR_DIR}/{DA_NAME}"
POM_FN = "/Engine/Functions/Engine_MaterialFunctions01/Texturing/ParallaxOcclusionMapping"
ROCK_COLOR = "/Game/AshesOfBazaar/Textures/T_Rock_Sandstone_D"
ROCK_NORMAL = "/Game/AshesOfBazaar/Textures/T_Rock_Sandstone_N"
MESHES = ("SM_Stele_WayStone_A", "SM_Stele_WayStone_B", "SM_Stele_WayStone_C", "SM_Stele_DockPost")
LEVEL_ACTORS = ROOT / "Content" / "__ExternalActors__" / "level" / "Saskarta_WP"
NODE_CHUNK = 36          # nodes per python_run
LINK_CHUNK = 90          # links per python_run
LOAD_CHUNK = 24
CPD_CHUNK = 12
SAVE_CHUNK = 20
CPD_COUNT = 9            # 0 Wear, 1 Cell, 2 ScanStart, 3 ScanMode, 4-7 CellRect, 8 GlowHoldS


# ------------------------------------------------------------------------------------------------ values
class Code(str):
    """A Python expression emitted as is (enums, unreal structs)."""


class Asset(str):
    """An asset path, loaded in the editor script."""


def color(r, g, b, a=1.0):
    return Code(f"unreal.LinearColor({r}, {g}, {b}, {a})")


def render(v):
    if isinstance(v, Asset):
        return f"eal.load_asset({str(v)!r})"
    if isinstance(v, Code):
        return str(v)
    return repr(v)


# ------------------------------------------------------------------------------------------------ graph
SAMPLER = "unreal.MaterialSamplerType."
N_CLASSES = {}


def graph(half_texel=0.5 / 2048):
    """The material graph: (nodes, links, properties). Nodes: (key, class, x, y, [(prop, value)])."""
    nodes, links = [], []

    def n(key, cls, x, y, *props):
        nodes.append((key, "MaterialExpression" + cls, x, y, list(props)))
        return key

    def param(key, name, v, x, y, group, cpd=None):
        props = [("parameter_name", name), ("default_value", float(v)), ("group", group)]
        if cpd is not None:
            props += [("use_custom_primitive_data", True), ("primitive_data_index", cpd)]
        return n(key, "ScalarParameter", x, y, *props)

    def vparam(key, name, c, x, y, group, cpd=None):
        props = [("parameter_name", name), ("default_value", color(*c)), ("group", group)]
        if cpd is not None:
            props += [("use_custom_primitive_data", True), ("primitive_data_index", cpd)]
        return n(key, "VectorParameter", x, y, *props)

    def tex(key, name, asset, stype, x, y, group, *extra):
        return n(key, "TextureSampleParameter2D", x, y, ("parameter_name", name), ("texture", Asset(asset)),
                 ("sampler_type", Code(SAMPLER + stype)), ("group", group), *extra)

    def mask(key, x, y, r, g, b, a):
        return n(key, "ComponentMask", x, y, ("r", r), ("g", g), ("b", b), ("a", a))

    def op(key, cls, x, y, a=None, b=None, ca=None, cb=None):
        props = []
        if ca is not None:
            props.append(("const_a", float(ca)))
        if cb is not None:
            props.append(("const_b", float(cb)))
        n(key, cls, x, y, *props)
        if a is not None:
            link(a, key, "A")
        if b is not None:
            link(b, key, "B")
        return key

    def un(key, cls, x, y, src, out=""):
        n(key, cls, x, y)
        link(src, key, "", out)
        return key

    def link(a, b, bi, ao=""):
        links.append((a, ao, b, bi))

    def const(key, v, x, y):
        return n(key, "Constant", x, y, ("r", float(v)))

    def c2(key, r, g, x, y):
        return n(key, "Constant2Vector", x, y, ("r", float(r)), ("g", float(g)))

    # ---- A: UV1 -> cell -> atlas UV -> POM ----------------------------------------------------
    n("tc1", "TextureCoordinate", -3600, 400, ("coordinate_index", 1))
    vparam("cellrect", "CellRect", (0.0, 0.0, 1.0, 1.0), -3600, 520, "Inscription", cpd=4)
    mask("rxy", -3400, 480, True, True, False, False)
    link("cellrect", "rxy", "", "RGBA")
    mask("rzw", -3400, 580, False, False, True, True)
    link("cellrect", "rzw", "", "RGBA")
    op("rzwsafe", "Max", -3250, 580, a="rzw", cb=0.0001)          # a stone without CPD: no divide by 0
    op("csub", "Subtract", -3250, 420, a="tc1", b="rxy")
    op("cuv", "Divide", -3100, 440, a="csub", b="rzwsafe")
    op("cen", "Subtract", -2950, 640, a="cuv", cb=0.5)
    un("cab", "Abs", -2820, 640, "cen")
    op("cinn", "Subtract", -2700, 640, b="cab", ca=0.5)
    op("cinsh", "Multiply", -2580, 640, a="cinn", cb=400.0)
    un("cinsat", "Saturate", -2460, 640, "cinsh")
    mask("cmu", -2340, 600, True, False, False, False)
    link("cinsat", "cmu", "")
    mask("cmv", -2340, 700, False, True, False, False)
    link("cinsat", "cmv", "")
    op("incell", "Multiply", -2220, 640, a="cmu", b="cmv")
    n("cclamp", "Clamp", -2950, 440, ("min_default", 0.004), ("max_default", 0.996))
    link("cuv", "cclamp", "")
    param("cell", "Cell", 0.0, -3600, 800, "Inscription", cpd=1)
    op("cellr", "Add", -3450, 800, a="cell", cb=0.25)
    un("cellf", "Floor", -3330, 800, "cellr")
    const("c8", 8.0, -3330, 880)
    op("ccol", "Fmod", -3200, 780, a="cellf", b="c8")
    op("crow", "Multiply", -3200, 880, a="cellf", cb=0.125)
    un("crowf", "Floor", -3080, 880, "crow")
    op("corg", "AppendVector", -2950, 820, a="ccol", b="crowf")
    c2("cellsz", 0.125, 0.25, -2950, 940)
    op("orig", "Multiply", -2820, 840, a="corg", b="cellsz")
    op("cscaled", "Multiply", -2820, 460, a="cclamp", b="cellsz")
    op("auv", "Add", -2680, 500, a="orig", b="cscaled")
    op("cmax", "Add", -2680, 900, a="orig", b="cellsz")
    c2("htex", half_texel, half_texel, -2680, 1000)
    op("omin", "Add", -2540, 840, a="orig", b="htex")
    op("omax", "Subtract", -2540, 940, a="cmax", b="htex")
    # POM strength k: inside the cell, near (fade 25 m -> 40 m), not grazing (off past ~70 deg)
    n("pdepth", "PixelDepth", -3600, 1100)
    param("pfs", "PomFadeStartCm", 2500.0, -3600, 1180, "Inscription")
    param("pfl", "PomFadeLengthCm", 1500.0, -3600, 1260, "Inscription")
    op("fsub", "Subtract", -3450, 1140, a="pdepth", b="pfs")
    op("fdiv", "Divide", -3330, 1160, a="fsub", b="pfl")
    un("fsat", "Saturate", -3210, 1160, "fdiv")
    un("fkeep", "OneMinus", -3090, 1160, "fsat")
    n("vnorm", "VertexNormalWS", -3600, 1380)
    n("camv", "CameraVectorWS", -3600, 1460)
    op("vdot", "DotProduct", -3450, 1400, a="vnorm", b="camv")
    op("gsub", "Subtract", -3330, 1400, a="vdot", cb=0.34)
    op("gmul", "Multiply", -3210, 1400, a="gsub", cb=5.0)
    un("gsat", "Saturate", -3090, 1400, "gmul")
    op("k1", "Multiply", -2950, 1200, a="incell", b="fkeep")
    op("kpom", "Multiply", -2820, 1260, a="k1", b="gsat")
    param("wear", "Wear", 0.25, -3600, 1600, "Inscription", cpd=0)
    op("wmul", "Multiply", -3450, 1600, a="wear", cb=0.6)
    un("wk", "OneMinus", -3330, 1600, "wmul")
    param("gdepth", "GrooveDepthCm", 0.8, -3600, 1700, "Inscription")
    op("hr1", "Multiply", -3450, 1700, a="gdepth", cb=1.0 / 400.0)      # 1 atlas UV = 400 cm
    op("hr2", "Multiply", -3330, 1680, a="hr1", b="wk")
    op("hr", "Multiply", -2700, 1300, a="hr2", b="kpom")
    op("mins0", "Multiply", -2700, 1400, a="kpom", cb=8.0)
    op("mins", "Max", -2580, 1400, a="mins0", cb=1.0)
    op("maxs0", "Multiply", -2700, 1480, a="kpom", cb=24.0)
    op("maxs", "Max", -2580, 1480, a="maxs0", cb=1.0)
    n("htexobj", "TextureObjectParameter", -2700, 1100, ("parameter_name", "InscrHeightObj"),
      ("texture", Asset(TEX_H)), ("sampler_type", Code(SAMPLER + "SAMPLERTYPE_LINEAR_GRAYSCALE")), ("group", "Inscription"))
    n("chan", "Constant4Vector", -2580, 1560, ("constant", color(1.0, 0.0, 0.0, 0.0)))
    const("refplane", 1.0, -2580, 1640)
    n("noshadow", "StaticBool", -2580, 1720, ("value", False))
    n("pom", "MaterialFunctionCall", -2380, 1100, ("material_function", Asset(POM_FN)))
    link("htexobj", "pom", "Heightmap Texture")
    link("hr", "pom", "Height Ratio")
    link("mins", "pom", "Min Steps")
    link("maxs", "pom", "Max Steps")
    link("auv", "pom", "UVs")
    link("chan", "pom", "Heightmap Channel")
    link("refplane", "pom", "Reference Plane")
    link("noshadow", "pom", "Render Shadows (Occlusion Mapping)")
    n("pclamp", "Clamp", -2100, 1000)
    link("pom", "pclamp", "", "Parallax UVs")
    link("omin", "pclamp", "Min")
    link("omax", "pclamp", "Max")
    n("usepom", "StaticSwitchParameter", -1950, 700, ("parameter_name", "UsePOM"), ("default_value", True),
      ("group", "Inscription"))
    link("pclamp", "usepom", "True")
    link("auv", "usepom", "False")

    # ---- B: shading ---------------------------------------------------------------------------
    tex("hs", "InscrHeight", TEX_H, "SAMPLERTYPE_LINEAR_GRAYSCALE", -1750, 600, "Inscription")
    tex("hb", "InscrHeightBlur", TEX_H, "SAMPLERTYPE_LINEAR_GRAYSCALE", -1750, 820, "Inscription",
        ("mip_value_mode", Code("unreal.TextureMipValueMode.TMVM_MIP_BIAS")), ("const_mip_value", 2))
    tex("ns", "InscrNormal", TEX_N, "SAMPLERTYPE_NORMAL", -1750, 380, "Inscription")
    for t in ("hs", "hb", "ns"):
        link("usepom", t, "UVs")
    n("tc0", "TextureCoordinate", -2200, -300, ("coordinate_index", 0))
    param("tiling", "RockTiling", 0.6, -2200, -200, "Rock")
    op("uv0", "Multiply", -2050, -260, a="tc0", b="tiling")
    tex("rockc", "RockColor", ROCK_COLOR, "SAMPLERTYPE_COLOR", -1850, -500, "Rock")
    tex("rockn", "RockNormal", ROCK_NORMAL, "SAMPLERTYPE_NORMAL", -1850, -200, "Rock")
    link("uv0", "rockc", "UVs")
    link("uv0", "rockn", "UVs")
    vparam("tint", "Tint", (1.0, 1.0, 1.0, 1.0), -1850, -660, "Rock")
    param("rns", "RockNormalStrength", 0.45, -1550, -60, "Rock")
    n("flat", "Constant3Vector", -1550, -140, ("constant", color(0.0, 0.0, 1.0, 1.0)))
    n("rnl", "LinearInterpolate", -1350, -160)
    link("flat", "rnl", "A")
    link("rockn", "rnl", "B", "RGB")
    link("rns", "rnl", "Alpha")
    n("vc", "VertexColor", -1850, -860)
    param("cavd", "CavityDark", 0.35, -1650, -1000, "Weathering")
    param("grime", "Grime", 0.55, -1650, -920, "Weathering")
    vparam("grimec", "GrimeColor", (0.2, 0.17, 0.12, 1.0), -1650, -1100, "Weathering")
    param("edgel", "EdgeLight", 0.12, -1650, -840, "Weathering")
    n("b0", "Multiply", -1550, -580)
    link("rockc", "b0", "A", "RGB")
    link("tint", "b0", "B", "RGB")
    n("cav", "Multiply", -1450, -960)
    link("vc", "cav", "A", "R")
    link("cavd", "cav", "B")
    un("cavk", "OneMinus", -1300, -960, "cav")
    op("b1", "Multiply", -1200, -660, a="b0", b="cavk")
    n("gra", "Multiply", -1450, -880)
    link("vc", "gra", "A", "G")
    link("grime", "gra", "B")
    n("b2", "LinearInterpolate", -1050, -720)
    link("b1", "b2", "A")
    link("grimec", "b2", "B", "RGB")
    link("gra", "b2", "Alpha")
    n("eda", "Multiply", -1450, -800)
    link("vc", "eda", "A", "B")
    link("edgel", "eda", "B")
    op("edk", "Add", -1300, -800, a="eda", cb=1.0)
    op("b3", "Multiply", -900, -700, a="b2", b="edk")
    param("gstr", "GlyphDepth", 1.0, -1550, 1100, "Inscription")
    n("noise", "Noise", -1550, 1200, ("scale", 0.2), ("output_min", 0.0), ("output_max", 1.0), ("levels", 3))
    op("wn", "Multiply", -1400, 1150, a="wear", b="noise")
    un("keep", "OneMinus", -1280, 1150, "wn")
    op("kg1", "Multiply", -1150, 1100, a="incell", b="keep")
    op("kg", "Multiply", -1030, 1100, a="kg1", b="gstr")
    un("groove", "OneMinus", -1550, 620, "hs", "R")
    op("g3", "Multiply", -1430, 620, a="groove", cb=3.0)
    un("g3s", "Saturate", -1310, 620, "g3")
    op("cut", "Multiply", -900, 640, a="g3s", b="kg")
    param("gdark", "GrooveDark", 0.8, -760, 460, "Inscription")
    const("one", 1.0, -760, 380)
    n("gl", "LinearInterpolate", -620, 420)
    link("one", "gl", "A")
    link("gdark", "gl", "B")
    link("cut", "gl", "Alpha")
    op("bg", "Multiply", -480, 0, a="b3", b="gl")
    param("dust", "Dust", 0.3, -620, 540, "Inscription")
    vparam("dustc", "DustColor", (0.55, 0.45, 0.33, 1.0), -480, 200, "Inscription")
    op("dcut", "Multiply", -480, 520, a="cut", b="dust")
    n("bfin", "LinearInterpolate", -300, 60)
    link("bg", "bfin", "A")
    link("dustc", "bfin", "B", "RGB")
    link("dcut", "bfin", "Alpha")
    n("gnl", "LinearInterpolate", -1250, 300)
    link("flat", "gnl", "A")
    link("ns", "gnl", "B", "RGB")
    link("kg", "gnl", "Alpha")
    mask("nxy1", -1150, -60, True, True, False, False)
    link("rnl", "nxy1", "")
    mask("nz1", -1150, 20, False, False, True, False)
    link("rnl", "nz1", "")
    mask("nxy2", -1050, 260, True, True, False, False)
    link("gnl", "nxy2", "")
    mask("nz2", -1050, 340, False, False, True, False)
    link("gnl", "nz2", "")
    op("nadd", "Add", -930, 80, a="nxy1", b="nxy2")
    op("nmul", "Multiply", -930, 200, a="nz1", b="nz2")
    op("napp", "AppendVector", -800, 120, a="nadd", b="nmul")
    un("nnorm", "Normalize", -680, 120, "napp")
    un("hbg", "OneMinus", -1550, 840, "hb", "R")
    op("hb3", "Multiply", -1430, 840, a="hbg", cb=0.3)
    un("hbao", "OneMinus", -1310, 840, "hb3")
    n("aol", "LinearInterpolate", -400, 760)
    link("one", "aol", "A")
    link("hbao", "aol", "B")
    link("kg", "aol", "Alpha")
    param("rough", "Roughness", 0.86, -400, 880, "Rock")
    const("r95", 0.95, -400, 960)
    n("rl", "LinearInterpolate", -250, 880)
    link("rough", "rl", "A")
    link("r95", "rl", "B")
    link("cut", "rl", "Alpha")

    # ---- C: scan sweep (emissive) -------------------------------------------------------------
    n("time", "Time", -1550, 1500)
    param("sstart", "ScanStart", 0.0, -1550, 1580, "Scan", cpd=2)
    param("smode", "ScanMode", 0.0, -1550, 1660, "Scan", cpd=3)
    param("shold", "GlowHoldS", 0.0, -1550, 1740, "Scan", cpd=8)
    param("sweepf", "SweepS", 1.4, -1550, 1820, "Scan")
    param("sweepm", "MatchSweepS", 0.6, -1550, 1900, "Scan")
    param("bandw", "ScanBandWidth", 0.015, -1550, 1980, "Scan")
    param("glowlvl", "GlowLevel", 0.35, -1550, 2060, "Scan")
    param("fades", "GlowFadeS", 2.5, -1550, 2140, "Scan")
    vparam("scol", "ScanColor", (0.95, 0.72, 0.42, 1.0), -1550, 2220, "Scan")
    param("sglow", "ScanGlow", 2.0, -1550, 2300, "Scan")
    op("st", "Subtract", -1400, 1520, a="time", b="sstart")
    op("sfull0", "Subtract", -1400, 1660, a="smode", cb=0.75)
    op("sfull1", "Multiply", -1280, 1660, a="sfull0", cb=1000.0)
    un("sfull", "Saturate", -1160, 1660, "sfull1")
    n("sweep", "LinearInterpolate", -1040, 1840)
    link("sweepm", "sweep", "A")
    link("sweepf", "sweep", "B")
    link("sfull", "sweep", "Alpha")
    op("linev", "Divide", -900, 1520, a="st", b="sweep")
    mask("uvv", -1400, 1420, False, True, False, False)
    link("tc1", "uvv", "")
    op("dv", "Subtract", -780, 1460, a="uvv", b="linev")
    un("adv", "Abs", -660, 1460, "dv")
    op("bnd0", "Divide", -540, 1460, a="adv", b="bandw")
    un("bnd1", "OneMinus", -420, 1460, "bnd0")
    un("bnd2", "Saturate", -300, 1460, "bnd1")
    op("band", "Multiply", -180, 1460, a="bnd2", b="bnd2")
    op("vs", "Multiply", -780, 1600, a="uvv", b="sweep")
    op("since", "Subtract", -660, 1600, a="st", b="vs")
    op("pass0", "Multiply", -540, 1600, a="since", cb=20.0)
    un("passed", "Saturate", -420, 1600, "pass0")
    op("sw3", "Add", -900, 1760, a="sweep", cb=0.3)
    op("holdt", "Max", -780, 1760, a="shold", b="sw3")
    op("th", "Subtract", -660, 1760, a="st", b="holdt")
    op("thm", "Max", -540, 1760, a="th", cb=0.0)
    op("thd", "Divide", -420, 1760, a="thm", b="fades")
    un("dec", "OneMinus", -300, 1760, "thd")
    un("decs", "Saturate", -180, 1760, "dec")
    op("glow1", "Multiply", -60, 1640, a="cut", b="passed")
    op("glow2", "Multiply", 60, 1680, a="glow1", b="decs")
    op("glow", "Multiply", 180, 1700, a="glow2", b="glowlvl")
    op("cutb", "Multiply", -60, 1380, a="cut", cb=1.5)
    op("cutb2", "Add", 60, 1380, a="cutb", cb=0.15)
    op("bandt", "Multiply", 180, 1420, a="band", b="cutb2")
    op("ssum", "Add", 300, 1540, a="bandt", b="glow")
    op("samp", "Multiply", 420, 1540, a="ssum", b="smode")
    n("e1", "Multiply", 300, 1900)
    link("scol", "e1", "A", "RGB")
    link("sglow", "e1", "B")
    op("emis", "Multiply", 540, 1600, a="e1", b="samp")

    props = [("bfin", "MP_BASE_COLOR"), ("nnorm", "MP_NORMAL"), ("rl", "MP_ROUGHNESS"),
             ("aol", "MP_AMBIENT_OCCLUSION"), ("emis", "MP_EMISSIVE_COLOR")]
    return nodes, links, props


# ------------------------------------------------------------------------------------------------ scripts
CREATE = r'''
import unreal
mel = unreal.MaterialEditingLibrary
eal = unreal.EditorAssetLibrary
path = "__MAT__"
if eal.does_asset_exist(path):
    mat = eal.load_asset(path)
else:
    mat = unreal.AssetToolsHelpers.get_asset_tools().create_asset("__NAME__", "__DIR__", unreal.Material, unreal.MaterialFactoryNew())
mat.set_editor_property("blend_mode", unreal.BlendMode.BLEND_OPAQUE)
mel.set_base_material_usage(mat, unreal.MaterialUsage.MATUSAGE_NANITE, True)
n = 0
while mel.get_num_material_expressions(mat) > 0 and n < 16:
    mel.delete_all_material_expressions(mat)
    n += 1
print("SCANMAT create nodes=" + str(mel.get_num_material_expressions(mat)) + " nanite=" + str(mel.has_material_usage(mat, unreal.MaterialUsage.MATUSAGE_NANITE)))
'''

NODES_HEAD = r'''
import unreal
mel = unreal.MaterialEditingLibrary
eal = unreal.EditorAssetLibrary
mat = eal.load_asset("__MAT__")
if mat is None:
    raise RuntimeError("no material: run the create step first")
have = set([str(e.get_editor_property("desc")) for e in mel.get_material_expressions(mat)])
KEYS = __KEYS__
dup = [k for k in KEYS if k in have]
if dup:
    raise RuntimeError("nodes already there, rerun the material step from create: " + str(dup[:4]))
def add(cls, x, y, key):
    n = mel.create_material_expression(mat, cls, x, y)
    n.set_editor_property("desc", key)
    return n
'''

NODES_TAIL = r'''
print("SCANMAT nodes chunk=__CHUNK__ made=" + str(len(KEYS)) + " total=" + str(mel.get_num_material_expressions(mat)))
'''

LINKS = r'''
import unreal
mel = unreal.MaterialEditingLibrary
eal = unreal.EditorAssetLibrary
mat = eal.load_asset("__MAT__")
byk = {}
for e in mel.get_material_expressions(mat):
    byk[str(e.get_editor_property("desc"))] = e
L = __LINKS__
bad = []
for a, ao, b, bi in L:
    na = byk.get(a)
    nb = byk.get(b)
    if na is None or nb is None or not mel.connect_material_expressions(na, ao, nb, bi):
        bad.append(a + ">" + b + "." + bi)
pin = []
if "pom" in byk:
    pin = [str(x) for x in mel.get_material_expression_input_names(byk["pom"])]
print("SCANMAT links chunk=__CHUNK__ n=" + str(len(L)) + " bad=" + str(bad) + " pom_inputs=" + str(pin))
'''

COMPILE = r'''
import unreal
mel = unreal.MaterialEditingLibrary
eal = unreal.EditorAssetLibrary
mat = eal.load_asset("__MAT__")
byk = {}
for e in mel.get_material_expressions(mat):
    byk[str(e.get_editor_property("desc"))] = e
P = unreal.MaterialProperty
PROPS = __PROPS__
ok = []
for key, prop in PROPS:
    node = byk.get(key)
    ok.append(node is not None and mel.connect_material_property(node, "", prop))
errs = [str(e) for e in mel.recompile_material(mat)]
print("SCANMAT compile nodes=" + str(len(byk)) + " props=" + str(ok) + " errors=" + str(len(errs)) + " first_errors=" + str(errs[:3]) + " saved=" + str(eal.save_loaded_asset(mat, False)))
'''

INSTANCE = r'''
import unreal
eal = unreal.EditorAssetLibrary
mel = unreal.MaterialEditingLibrary
path = "__MI__"
if eal.does_asset_exist(path):
    mi = eal.load_asset(path)
else:
    mi = unreal.AssetToolsHelpers.get_asset_tools().create_asset("__NAME__", "__DIR__", unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
mel.set_material_instance_parent(mi, eal.load_asset("__MAT__"))
POM = __POM__
if not POM:
    mel.set_material_instance_static_switch_parameter_value(mi, "UsePOM", False)
mel.update_material_instance(mi)
print("SCANMI parent=" + str(mi.get_editor_property("parent").get_name()) + " pom=" + str(POM) + " saved=" + str(eal.save_loaded_asset(mi, False)))
'''

TEXTURE = r'''
import unreal
eal = unreal.EditorAssetLibrary
if not eal.does_directory_exist("__DIR__"):
    eal.make_directory("__DIR__")
task = unreal.AssetImportTask()
task.set_editor_property("filename", "__FILE__")
task.set_editor_property("destination_path", "__DIR__")
task.set_editor_property("destination_name", "__NAME__")
task.set_editor_property("automated", True)
task.set_editor_property("replace_existing", True)
task.set_editor_property("save", False)
unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
t = eal.load_asset("__DIR__/__NAME__")
if t is None:
    raise RuntimeError("atlas import made nothing at __DIR__/__NAME__")
NORMAL = __NORMAL__
if NORMAL:
    t.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_NORMALMAP)
    t.set_editor_property("flip_green_channel", True)
    t.set_editor_property("lod_group", unreal.TextureGroup.TEXTUREGROUP_WORLD_NORMAL_MAP)
else:
    t.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_GRAYSCALE)
    t.set_editor_property("flip_green_channel", False)
    t.set_editor_property("lod_group", unreal.TextureGroup.TEXTUREGROUP_WORLD)
t.set_editor_property("srgb", False)
t.set_editor_property("address_x", unreal.TextureAddress.TA_CLAMP)
t.set_editor_property("address_y", unreal.TextureAddress.TA_CLAMP)
t.set_editor_property("mip_gen_settings", unreal.TextureMipGenSettings.TMGS_FROM_TEXTURE_GROUP)
print("ATLAS __NAME__ " + str(t.blueprint_get_size_x()) + "x" + str(t.blueprint_get_size_y()) + " comp=" + str(t.get_editor_property("compression_settings")) + " srgb=" + str(t.get_editor_property("srgb")) + " flip=" + str(t.get_editor_property("flip_green_channel")) + " clamp=" + str(t.get_editor_property("address_x") == unreal.TextureAddress.TA_CLAMP) + " saved=" + str(eal.save_loaded_asset(t, False)))
'''

ASSIGN = r'''
import unreal
eal = unreal.EditorAssetLibrary
m = eal.load_asset("__STELES__/__MESH__")
face = eal.load_asset("__MI__")
if m is None or face is None:
    raise RuntimeError("mesh or MI_SteleFace missing")
names = [str(s.material_slot_name) for s in m.get_editor_property("static_materials")]
fi = m.get_material_index("Face")
if fi < 0:
    print("ASSIGN __MESH__ no slot named Face in " + str(names) + ": using slot 1")
    fi = 1
before = m.get_material(fi).get_name() if m.get_material(fi) else "none"
m.set_material(fi, face)
print("ASSIGN __MESH__ slots=" + str(names) + " face=" + str(fi) + " " + before + " -> " + m.get_material(fi).get_name() + " saved=" + str(eal.save_loaded_asset(m, False)))
'''

# Only the 36 stele actors (label Stele_*, not the old *_Glyph decals: this lane never touches those).
LOAD = r'''
import unreal
lib = unreal.WorldPartitionBlueprintLibrary
r = lib.get_intersecting_actor_descs(lib.get_editor_world_bounds())
descs = r[1] if isinstance(r, tuple) else r
want = [d.get_editor_property("guid") for d in descs if str(d.get_editor_property("label")).startswith("Stele_") and not str(d.get_editor_property("label")).endswith("_Glyph")]
part = want[__A__:__B__]
if part:
    lib.load_actors(part)
print("LOAD steles descs=" + str(len(want)) + " loaded_now=" + str(len(part)))
'''

UNLOAD = r'''
import unreal
lib = unreal.WorldPartitionBlueprintLibrary
r = lib.get_intersecting_actor_descs(lib.get_editor_world_bounds())
descs = r[1] if isinstance(r, tuple) else r
gs = [d.get_editor_property("guid") for d in descs if str(d.get_editor_property("label")).startswith("Stele_") and not str(d.get_editor_property("label")).endswith("_Glyph")]
if gs:
    lib.unload_actors(gs)
    lib.unpin_actors(gs)
print("UNLOAD " + str(len(gs)))
'''

RESIDENT = r'''
import unreal
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
dirty = set([p.get_name() for p in unreal.EditorLoadingAndSavingUtils.get_dirty_map_packages()])
st = [a for a in eas.get_all_level_actors() if a.get_actor_label().startswith("Stele_") and not a.get_actor_label().endswith("_Glyph")]
dl = [a.get_actor_label() for a in st if a.get_package().get_name() in dirty]
print("RESIDENT loaded=" + str(len(st)) + " dirty=" + str(len(dl)) + " dirty_labels=" + str(dl[:6]))
'''

# modify() first: set_default_custom_primitive_data_float does not dirty the external actor package on
# its own, and save writes only dirty packages. Tags go through set_editor_property (which also dirties).
CPD = r'''
import unreal
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
ITEMS = __ITEMS__
have = {}
for a in eas.get_all_level_actors():
    lb = a.get_actor_label()
    if lb.startswith("Stele_") and not lb.endswith("_Glyph"):
        have[lb] = a
done, missing, touched = 0, [], []
for it in ITEMS:
    s = have.get(it["id"])
    if s is None:
        missing.append(it["id"])
        continue
    c = s.static_mesh_component
    s.modify()
    c.modify()
    touched.append(s)
    keep = [t for t in s.get_editor_property("tags") if not str(t).startswith("Stele")]
    s.set_editor_property("tags", keep + [unreal.Name(t) for t in it["tags"]])
    for i, v in enumerate(it["cpd"]):
        c.set_default_custom_primitive_data_float(i, v)
    done += 1
dirty = set([p.get_name() for p in unreal.EditorLoadingAndSavingUtils.get_dirty_map_packages()])
clean = [a.get_actor_label() for a in touched if a.get_package().get_name() not in dirty]
print("CPD done=" + str(done) + " missing=" + str(missing) + " not_dirty=" + str(clean))
'''

SAVE = r'''
import unreal
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
els = unreal.EditorLoadingAndSavingUtils
pk = sorted([a.get_package() for a in eas.get_all_level_actors() if a.get_actor_label().startswith("Stele_") and not a.get_actor_label().endswith("_Glyph")], key=lambda p: p.get_name())
part = pk[__CHUNK__ * __SIZE__:(__CHUNK__ + 1) * __SIZE__]
before = set([p.get_name() for p in els.get_dirty_map_packages()])
nd = len([p for p in part if p.get_name() in before])
ok = els.save_packages(part, True) if part else True
after = set([p.get_name() for p in els.get_dirty_map_packages()])
left = [p.get_name().split("/")[-1] for p in part if p.get_name() in after]
print("SAVE total=" + str(len(pk)) + " chunk=__CHUNK__ n=" + str(len(part)) + " dirty=" + str(nd) + " ok=" + str(ok) + " left_dirty=" + str(left))
'''

VERIFY = r'''
import unreal
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
ITEMS = __ITEMS__
FACE = "__FACE__"
have = {}
for a in eas.get_all_level_actors():
    lb = a.get_actor_label()
    if lb.startswith("Stele_") and not lb.endswith("_Glyph"):
        have[lb] = a
dirty = set([p.get_name() for p in unreal.EditorLoadingAndSavingUtils.get_dirty_map_packages()])
bad, count = [], 0
for it in ITEMS:
    s = have.get(it["id"])
    if s is None:
        bad.append(it["id"] + " not loaded")
        continue
    count += 1
    c = s.static_mesh_component
    cpd = [round(x, 4) for x in c.get_editor_property("custom_primitive_data").get_editor_property("data")]
    tags = [str(t) for t in s.get_editor_property("tags")]
    mats = [(c.get_material(i).get_name() if c.get_material(i) else "none") for i in range(c.get_num_materials())]
    print("VERIFY " + it["id"] + " tags=" + str(tags) + " cpd=" + str(cpd) + " mats=" + str(mats))
    if [t for t in tags if t.startswith("Stele")] != it["tags"]:
        bad.append(it["id"] + " tags " + str(tags))
    if len(cpd) < len(it["cpd"]) or max([abs(a - b) for a, b in zip(cpd, it["cpd"])] + [0.0]) > 0.001:
        bad.append(it["id"] + " cpd " + str(cpd))
    if len(mats) < 2 or not mats[1].startswith(FACE):
        bad.append(it["id"] + " face " + str(mats[1:2]))
    if s.get_package().get_name() in dirty:
        bad.append(it["id"] + " unsaved (package dirty)")
print("VERIFY count=" + str(count) + " problems=" + str(len(bad)) + " first=" + str(bad[:8]))
'''

# The scanner's data asset. Needs the SaskartaCore build with USaskartaSteleScanAsset (C++, closed editor).
DATA_ASSET = r'''
import unreal
E = unreal.EditorAssetLibrary
full = "__DA__"
if E.does_asset_exist(full):
    da = unreal.load_asset(full)
else:
    f = unreal.DataAssetFactory()
    f.set_editor_property("data_asset_class", unreal.SaskartaSteleScanAsset)
    da = unreal.AssetToolsHelpers.get_asset_tools().create_asset("__NAME__", "__DIR__", unreal.SaskartaSteleScanAsset, f)
r = unreal.SaskartaSteleScanImport.import_stele_scan_from_files(da, unreal.Paths.project_dir())
ok = r[0] if isinstance(r, tuple) else (r is not None)
rep = r[1] if isinstance(r, tuple) else r
print("SCANDA ok=" + str(ok) + " steles=" + str(len(da.get_editor_property("steles"))) + " inscriptions=" + str(len(da.get_editor_property("inscriptions"))) + " saved=" + str(E.save_loaded_asset(da, False)) + " report=" + str(rep)[:400])
'''


def fill(t, **kw):
    for k, v in kw.items():
        t = t.replace(f"__{k}__", str(v))
    left = re.findall(r"__[A-Z][A-Z_]*__", t)
    if left:
        raise SystemExit(f"unfilled placeholders: {left[:4]}")
    return check_banned(t)


def node_code(key, cls, x, y, props):
    lines = [f"n = add(unreal.{cls}, {x}, {y}, {key!r})"]
    lines += [f"n.set_editor_property({p!r}, {render(v)})" for p, v in props]
    return "\n".join(lines)


def material_scripts():
    """[(label, script)] in order: create, node chunks, link chunks, compile."""
    nodes, links, props = graph()
    out = [("create", fill(CREATE, MAT=MAT, NAME=MAT_NAME, DIR=STELE_DIR))]
    for i in range(0, len(nodes), NODE_CHUNK):
        part = nodes[i:i + NODE_CHUNK]
        body = "\n".join(node_code(*nd) for nd in part)
        s = fill(NODES_HEAD, MAT=MAT, KEYS=repr([nd[0] for nd in part])) + body + "\n" + fill(NODES_TAIL, CHUNK=i // NODE_CHUNK)
        out.append((f"nodes{i // NODE_CHUNK}", check_banned(s)))
    for i in range(0, len(links), LINK_CHUNK):
        out.append((f"links{i // LINK_CHUNK}", fill(LINKS, MAT=MAT, LINKS=repr(links[i:i + LINK_CHUNK]), CHUNK=i // LINK_CHUNK)))
    prop_code = "[" + ", ".join(f"({k!r}, P.{p})" for k, p in props) + "]"
    out.append(("compile", fill(COMPILE, MAT=MAT, PROPS=prop_code)))
    return out


# ------------------------------------------------------------------------------------------------ data
def load_data():
    return json.loads(DATA.read_text(encoding="utf-8"))


def cpd_items(data=None):
    """Per stele: tags and the Custom Primitive Data defaults [Wear, Cell, 0, 0, CellRect x4, 0]."""
    data = data or load_data()
    cells = {r["id"]: r.get("atlas_cell") for r in data["inscriptions"]}
    out = []
    for s in data["steles"]:
        cell = cells.get(s["inscription"])
        rect = data["meshes"][s["mesh"]].get("cell_rect_uv1")
        if cell is None or not rect:
            raise SystemExit(f"{s['id']}: {s['inscription']} has no atlas cell or {s['mesh']} no cell rect "
                             "(run Tools/Story/build_inscription_atlas.py)")
        out.append({"id": s["id"], "tags": list(s["tags"]),
                    "cpd": [float(s["wear"]), float(cell), 0.0, 0.0] + [float(x) for x in rect] + [0.0]})
    return out


def asset_file(path):
    return ROOT / "Content" / (path[len("/Game/"):] + ".uasset")


def readonly(paths):
    return [p for p in paths if p.exists() and not os.access(p, os.W_OK)]


def readonly_level_actors():
    if not LEVEL_ACTORS.exists():
        return []
    return [p for p in LEVEL_ACTORS.rglob("*.uasset") if not os.access(p, os.W_OK)]


# ------------------------------------------------------------------------------------------------ runner
def run(script):
    ok, out, err = python_run(script)
    print((out or "").strip() or err)
    if not ok:
        raise SystemExit(f"editor step failed: {err}")
    return out or ""


def require(out, step, *needles):
    miss = [n for n in needles if n not in out]
    if miss:
        raise SystemExit(f"{step}: FAILED, the report lacks {miss}")


def number(out, key):
    m = re.search(rf"\b{re.escape(key)}=(-?\d+)", out)
    if not m:
        raise SystemExit(f"no '{key}=' in the editor report")
    return int(m.group(1))


def all_scripts():
    """Every editor script with sample values, for the offline check and the tests."""
    items = cpd_items()
    yield from material_scripts()
    yield "instance", fill(INSTANCE, MI=MI, NAME=MI_NAME, DIR=STELE_DIR, MAT=MAT, POM=True)
    yield "texture_h", fill(TEXTURE, DIR=INSCR_DIR, NAME="T_Inscr_Atlas_H", FILE="D:/x.png", NORMAL=False)
    yield "texture_n", fill(TEXTURE, DIR=INSCR_DIR, NAME="T_Inscr_Atlas_N", FILE="D:/x.png", NORMAL=True)
    yield "assign", fill(ASSIGN, STELES=STELE_DIR, MESH=MESHES[0], MI=MI)
    yield "load", fill(LOAD, A=0, B=LOAD_CHUNK)
    yield "unload", fill(UNLOAD)
    yield "resident", fill(RESIDENT)
    yield "cpd", fill(CPD, ITEMS=repr(items[:CPD_CHUNK]))
    yield "save", fill(SAVE, CHUNK=0, SIZE=SAVE_CHUNK)
    yield "verify", fill(VERIFY, ITEMS=repr(items), FACE=MI_NAME)
    yield "da", fill(DATA_ASSET, DA=DA, NAME=DA_NAME, DIR=INSCR_DIR)


def check():
    problems = []
    sys.path.insert(0, str(ROOT / "Tools" / "Story"))
    import build_inscription_atlas as bia
    if bia.main(["--check"]) != 0:
        problems.append("the atlas is stale: run python Tools/Story/build_inscription_atlas.py")
    for name in ("T_Inscr_Atlas_H.png", "T_Inscr_Atlas_N.png"):
        if not (ATLAS_DIR / name).exists():
            problems.append(f"missing {ATLAS_DIR / name}")
    for label, s in all_scripts():
        compile(s, label, "exec")
        if len(s) > 60000:
            problems.append(f"{label}: script too long")
    ro = readonly([asset_file(f"{STELE_DIR}/{m}") for m in MESHES] + [asset_file(p) for p in (MAT, MI, TEX_H, TEX_N, DA)])
    if ro:
        problems.append(f"read-only assets (make them writable before the editor steps): {[p.name for p in ro]}")
    ro = readonly_level_actors()
    if ro:
        problems.append(f"{len(ro)} read-only actor packages under {LEVEL_ACTORS}: 'save' would fail on them")
    print("\n".join(problems) if problems else "ok: atlas, data, scripts clean, nothing read-only")
    return 1 if problems else 0


def load_all():
    lo, total = 0, 1
    while lo < total:
        out = run(fill(LOAD, A=lo, B=lo + LOAD_CHUNK))
        total = number(out, "descs")
        lo += LOAD_CHUNK
    return total


def refuse_readonly(paths, step):
    ro = readonly(paths)
    if ro:
        raise SystemExit(f"{step}: read-only {[str(p) for p in ro]}: make them writable first (never save a read-only package)")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("step", choices=["check", "import-atlas", "material", "instance", "assign", "load", "cpd",
                                     "save", "unload", "verify", "da"])
    ap.add_argument("--no-pom", action="store_true", help="instance: UsePOM off (the flat fallback)")
    ap.add_argument("--face", choices=["scan", "old"], default="scan",
                    help="verify: expect MI_SteleFace (scan) or the old MI_Stele_Face_* (old) on slot 1")
    a = ap.parse_args(argv)
    if a.step == "check":
        return check()
    if a.step == "import-atlas":
        for name, normal in (("T_Inscr_Atlas_H", False), ("T_Inscr_Atlas_N", True)):
            refuse_readonly([asset_file(f"{INSCR_DIR}/{name}")], "import-atlas")
            out = run(fill(TEXTURE, DIR=INSCR_DIR, NAME=name, FILE=(ATLAS_DIR / f"{name}.png").as_posix(), NORMAL=normal))
            require(out, f"import-atlas {name}", "2048x2048", "srgb=False", f"flip={normal}", "clamp=True", "saved=True")
    elif a.step == "material":
        refuse_readonly([asset_file(MAT)], "material")
        for label, s in material_scripts():
            out = run(s)
            if label.startswith("links"):
                require(out, f"material {label}", "bad=[]")
            elif label == "compile":
                # the translator's errors come back synchronously: a material that does not compile would
                # draw the default material on every stele face, so errors=0 is the pass condition
                require(out, "material compile", "props=[True, True, True, True, True]", "errors=0 ", "saved=True")
            elif label == "create":
                require(out, "material create", "nodes=0 ", "nanite=True")
    elif a.step == "instance":
        refuse_readonly([asset_file(MI)], "instance")
        out = run(fill(INSTANCE, MI=MI, NAME=MI_NAME, DIR=STELE_DIR, MAT=MAT, POM=not a.no_pom))
        require(out, "instance", f"parent={MAT_NAME}", "saved=True")
    elif a.step == "assign":
        refuse_readonly([asset_file(f"{STELE_DIR}/{m}") for m in MESHES], "assign")
        for m in MESHES:
            out = run(fill(ASSIGN, STELES=STELE_DIR, MESH=m, MI=MI))
            require(out, f"assign {m}", f"-> {MI_NAME} saved=True")
    elif a.step == "load":
        load_all()
    elif a.step == "unload":
        run(fill(UNLOAD))
    elif a.step == "cpd":
        items = cpd_items()
        for i in range(0, len(items), CPD_CHUNK):
            out = run(fill(CPD, ITEMS=repr(items[i:i + CPD_CHUNK])))
            require(out, "cpd", "missing=[]", "not_dirty=[]")
    elif a.step == "save":
        ro = readonly_level_actors()
        if ro:
            raise SystemExit(f"save: {len(ro)} read-only actor packages (e.g. {ro[0]}): make them writable first")
        chunk, total = 0, 1
        while chunk * SAVE_CHUNK < total:
            out = run(fill(SAVE, CHUNK=chunk, SIZE=SAVE_CHUNK))
            total = number(out, "total")
            require(out, "save", "ok=True", "left_dirty=[]")
            chunk += 1
        print(f"save: {total} stele packages checked, none left dirty")
    elif a.step == "verify":
        out = run(fill(RESIDENT))
        if number(out, "dirty"):
            raise SystemExit("verify: stele packages are still dirty (unsaved): run 'save' first, then 'unload'")
        load_all()
        face = MI_NAME if a.face == "scan" else "MI_Stele_Face_"
        out = run(fill(VERIFY, ITEMS=repr(cpd_items()), FACE=face))
        run(fill(UNLOAD))
        if number(out, "count") != 36 or number(out, "problems"):
            raise SystemExit("verify: FAILED (see the VERIFY lines above)")
        print("verify: 36 steles carry their tags and scan data, read back after the save")
    elif a.step == "da":
        refuse_readonly([asset_file(DA)], "da")
        out = run(fill(DATA_ASSET, DA=DA, NAME=DA_NAME, DIR=INSCR_DIR))
        require(out, "da", "ok=True", "steles=36 ", "saved=True")
    return 0


if __name__ == "__main__":
    sys.exit(main())
