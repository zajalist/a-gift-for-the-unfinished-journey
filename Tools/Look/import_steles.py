"""Import the stele meshes, build their material, and swap them onto the placed steles (lane STELE).

The meshes are made offline by Tools/Look/stele_mesh.py (SourceArt/Steles/SM_Stele_*.glb and
steles.json). Every editor step below is ONE small Hayba python_run (5 s budget, no banned words),
run from the repo root with the editor open, no PIE, holding the editor gate
(Tools/GameFlow/editor_gate.py). Order:

    python Tools/Look/import_steles.py check                 # offline: files, manifest, banned words, read-only flags
    python Tools/Look/import_steles.py glyphmaps             # T_Inscription_<ID>_N: flip green (maps are OpenGL), save
    python Tools/Look/import_steles.py import                # the four GLBs -> /Game/SaskartaGaea/Steles (one call each)
    python Tools/Look/import_steles.py fixmesh               # read-only import settings and UV1 validation
    python Tools/Look/import_steles.py nanite                # verify Nanite + add a box collision if absent
    python Tools/Look/import_steles.py material              # M_Saskarta_Stele (rock on UV0, glyph on UV1); fails on compile errors
    python Tools/Look/import_steles.py instances             # MI_Stele_Body + MI_Stele_Face_<mesh>
    python Tools/Look/import_steles.py assign                # mesh slots: Stone -> MI_Stele_Body, Face -> MI_Stele_Face_<mesh>
    python Tools/Look/import_steles.py cleanup [--apply]     # list (then delete) the materials the glTF import made
    python Tools/Look/import_steles.py load                  # World Partition: load the Stele_* actors (own calls)
    python Tools/Look/import_steles.py swap [--glyph uv1|decal]   # fails if a stele is missing or an edit left a package clean
    python Tools/Look/import_steles.py save                  # stele + glyph actors, chunks of 20 (own calls); fails if any stay dirty
    python Tools/Look/import_steles.py unload                # own call, after the save
    python Tools/Look/import_steles.py verify [--glyph uv1|decal]  # reload from disk and check (see below)

verify is four own calls: resident (fails if a stele package is still dirty, i.e. unsaved), load,
the check itself (per stele: mesh, scale, overrides, wear, materials, the old decal's state, and that
the package is clean), unload. Run it after unload, so what it reads is what the save wrote. Stele
actors that the editor keeps loaded anyway (a loaded region) are read from memory; resident says how
many, and they are clean, so memory matches what was saved.

swap (default --glyph uv1): each Stele_WayStone_<i> gets SM_Stele_WayStone_A/B/C (no two neighbours
alike, uniform scale 0.92-1.08), each Stele_DockPost_<A|B> gets SM_Stele_DockPost; the per-actor
material overrides (the old MI_Rock_01) are cleared so the mesh's own slots draw; the stone's wear
(the old decal's DecalColor alpha, 0.1-0.85) goes into Custom Primitive Data 0, which the material
reads as Wear; the old Stele_*_Glyph decal is hidden (component invisible + hidden in game), not
deleted. --glyph decal instead keeps the decal, re-seats it on the new flat face (glyph centre from
steles.json, through the actor's transform) and swaps the Face slot to MI_Stele_Body (one glyph only).
Location, yaw and lean are kept (pivot at the base centre, as before; stones stay sunk 8 cm).
swap calls modify() on every actor and component it touches before it changes them: set_visibility,
set_actor_hidden_in_game, set_static_mesh and the scale/transform setters do not mark the actor's
package dirty on their own, and save only writes dirty packages, so without modify() the hidden
decals would come back on the next load.
"""
import argparse
import json
import os
import pathlib
import random
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Tools" / "Look"))
from apply_look import check_banned, python_run  # noqa: E402

SRC = ROOT / "SourceArt" / "Steles"
MANIFEST = SRC / "steles.json"
DEST = "/Game/SaskartaGaea/Steles"
INSCR = "/Game/SaskartaGaea/Inscriptions"
MAT = f"{DEST}/M_Saskarta_Stele"
BODY_MI = f"{DEST}/MI_Stele_Body"
ROCK_COLOR = "/Game/AshesOfBazaar/Textures/T_Rock_Sandstone_D"
ROCK_NORMAL = "/Game/AshesOfBazaar/Textures/T_Rock_Sandstone_N"
ROCK_TILING = 0.6            # rock texture repeats per metre of UV0 (UV0 is 1 unit per metre)
GLYPH_IDS = ("I05", "I02")
WAY_MESHES = ("WayStone_A", "WayStone_B", "WayStone_C")
OUR_PREFIXES = ("SM_Stele_", "MI_Stele_", "M_Saskarta_Stele")
LOAD_CHUNK = 24              # actors per load call (72 = 36 steles + 36 glyph decals)
SWAP_CHUNK = 12              # steles per swap call
SAVE_CHUNK = 20              # packages per save call (40 can pass the 5 s deadline)
LEVEL_ACTORS = ROOT / "Content" / "__ExternalActors__" / "level" / "Saskarta_WP"


def manifest():
    return json.loads(MANIFEST.read_text(encoding="utf-8"))["meshes"]


def fill(t, **kw):
    for k, v in kw.items():
        t = t.replace(f"__{k}__", str(v))
    if "__" in t.split("\n", 1)[1] and "__init__" not in t:
        left = [w for w in t.split() if w.count("__") >= 2 and not w.startswith("__init")]
        if left:
            raise SystemExit(f"unfilled placeholders: {left[:4]}")
    return check_banned(t)


def run(script):
    ok, out, err = python_run(script)
    print((out or "").strip() or err)
    if not ok:
        raise SystemExit(f"editor step failed: {err}")
    return out or ""


def require(out, step, *needles):
    """Fail the step unless every needle is in the editor's report (a pass condition, not a hope)."""
    miss = [n for n in needles if n not in out]
    if miss:
        raise SystemExit(f"{step}: FAILED, the report lacks {miss}")


def number(out, key):
    """The integer after 'key=' in an editor report."""
    m = re.search(rf"\b{re.escape(key)}=(-?\d+)", out)
    if not m:
        raise SystemExit(f"no '{key}=' in the editor report")
    return int(m.group(1))


def asset_file(path):
    """/Game/X/Y -> Content/X/Y.uasset on disk."""
    return ROOT / "Content" / (path[len("/Game/"):] + ".uasset")


# ------------------------------------------------------------------------------------------------
# editor scripts (each is one python_run; keep them small)
# ------------------------------------------------------------------------------------------------
GLYPHMAP = r'''
import unreal
eal = unreal.EditorAssetLibrary
t = eal.load_asset("__PATH__")
was = t.get_editor_property("flip_green_channel")
if not was:
    t.set_editor_property("flip_green_channel", True)
print("GLYPHMAP __PATH__ flip_green " + str(was) + " -> " + str(t.get_editor_property("flip_green_channel")) + " saved=" + str(eal.save_loaded_asset(t, False)))
'''

IMPORT = r'''
import unreal
eal = unreal.EditorAssetLibrary
if not eal.does_directory_exist("__DEST__"):
    eal.make_directory("__DEST__")
task = unreal.AssetImportTask()
task.set_editor_property("filename", "__FILE__")
task.set_editor_property("destination_path", "__DEST__")
task.set_editor_property("destination_name", "__NAME__")
task.set_editor_property("automated", True)
task.set_editor_property("replace_existing", True)
task.set_editor_property("save", False)
pipeline = unreal.InterchangeGenericAssetsPipeline()
pipeline.set_editor_property("asset_name", "__NAME__")
pipeline.set_editor_property("use_source_name_for_asset", False)
common = pipeline.get_editor_property("common_meshes_properties")
common.set_editor_property("recompute_normals", False)
common.set_editor_property("recompute_tangents", True)
common.set_editor_property("use_mikk_t_space", True)
common.set_editor_property("use_full_precision_u_vs", True)
common.set_editor_property("remove_degenerates", True)
mesh_pipeline = pipeline.get_editor_property("mesh_pipeline")
mesh_pipeline.set_editor_property("generate_lightmap_u_vs", False)
mesh_pipeline.set_editor_property("build_nanite", True)
mesh_pipeline.set_editor_property("nanite_triangle_threshold", 0)
override = unreal.InterchangePipelineStackOverride()
override.add_pipeline(pipeline)
task.set_editor_property("options", override)
unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
made = [str(p) for p in task.get_editor_property("imported_object_paths")]
print("IMPORT made " + str(made))
want = "__DEST__/__NAME__"
if not eal.does_asset_exist(want):
    for p in made:
        a = eal.load_asset(p)
        if a is not None and a.get_class().get_name() == "StaticMesh":
            print("IMPORT rename " + p + " -> " + want + " " + str(eal.rename_asset(p, want)))
m = eal.load_asset(want)
if m is None:
    raise RuntimeError("stele import did not produce " + want)
ses = unreal.get_editor_subsystem(unreal.StaticMeshEditorSubsystem)
b = m.get_bounding_box()
print("IMPORT __NAME__ uv=" + str(ses.get_num_uv_channels(m, 0)) + " slots=" + str([str(s.material_slot_name) for s in m.get_editor_property("static_materials")]) + " vcol=" + str(ses.has_vertex_colors(m)) + " min=" + str(b.min) + " max=" + str(b.max) + " saved=" + str(eal.save_loaded_asset(m, False)))
'''

FIXMESH = r'''
import unreal
ses = unreal.get_editor_subsystem(unreal.StaticMeshEditorSubsystem)
m = unreal.EditorAssetLibrary.load_asset("__DEST__/__NAME__")
if m is None:
    raise RuntimeError("stele mesh missing")
bs = ses.get_lod_build_settings(m, 0)
uv = ses.get_num_uv_channels(m, 0)
settings = {k: bs.get_editor_property(k) for k in ("generate_lightmap_u_vs", "recompute_normals", "recompute_tangents", "use_mikk_t_space", "use_full_precision_u_vs")}
print("FIXMESH __NAME__ uv=" + str(uv) + " settings=" + str(settings))
if uv != 2 or settings["generate_lightmap_u_vs"] or settings["recompute_normals"] or not settings["recompute_tangents"] or not settings["use_mikk_t_space"] or not settings["use_full_precision_u_vs"]:
    raise RuntimeError("stele import settings would damage UV1 or authored normals; configure the Interchange import before continuing")
b = m.get_bounding_box()
print("FIXMESH __NAME__ uv=" + str(uv) + " verts=" + str(ses.get_number_verts(m, 0)) + " min=" + str(b.min) + " max=" + str(b.max) + " settings_ok=True full_uv=" + str(settings["use_full_precision_u_vs"]))
'''

NANITE = r'''
import unreal
eal = unreal.EditorAssetLibrary
ses = unreal.get_editor_subsystem(unreal.StaticMeshEditorSubsystem)
m = eal.load_asset("__DEST__/__NAME__")
if m is None or ses.get_num_uv_channels(m, 0) != 2:
    raise RuntimeError("stele mesh missing or UV1 lost before Nanite check")
ns = ses.get_nanite_settings(m)
if not ns.get_editor_property("enabled"):
    ns.set_editor_property("enabled", True)
    ses.set_nanite_settings(m, ns, True)
    if ses.get_num_uv_channels(m, 0) != 2:
        raise RuntimeError("Nanite build lost the stele's glyph UV1 channel")
if ses.get_simple_collision_count(m) == 0:
    ses.add_simple_collisions_with_notification(m, unreal.ScriptCollisionShapeType.BOX, True)
if ses.get_num_uv_channels(m, 0) != 2:
    raise RuntimeError("stele glyph UV1 channel lost after collision setup")
print("NANITE __NAME__ nanite=" + str(ses.get_nanite_settings(m).get_editor_property("enabled")) + " collision=" + str(ses.get_simple_collision_count(m)) + " uv=" + str(ses.get_num_uv_channels(m, 0)) + " saved=" + str(eal.save_loaded_asset(m, False)))
'''

# M_Saskarta_Stele: opaque, default lit. An empty output name means output 0, which for a
# VectorParameter is "RGB" (float3): GlyphRect must be read through "RGBA" or its .zw mask fails.
# recompile_material returns the translator's errors (synchronous); the step fails unless it is [].
#   rock    = RockColor(UV0 x RockTiling) x Tint; cavity (vertex R) darkens, ground grime (vertex G) blends
#             to GrimeColor, worn edges (vertex B) lighten
#   glyph   = UV1 -> (UV1 - GlyphRect.xy) / GlyphRect.zw, clamp-sampled, masked to the rect;
#             k = GlyphDepth x mask x (1 - Wear x noise), Wear = Custom Primitive Data 0 (per stone)
#   colour  = rock x lerp(1, GrooveDark, cut), toward DustColor by cut x Dust; cut = saturate(3 x (1 - AO)) x k
#   normal  = whiteout blend of the rock normal (x RockNormalStrength) and lerp(flat, GlyphNormal, k)
#   AO      = lerp(1, GlyphAO, k); roughness = lerp(Roughness, 0.95, cut)
MATERIAL = r'''
import unreal
mel = unreal.MaterialEditingLibrary
eal = unreal.EditorAssetLibrary
path = "__MAT__"
if eal.does_asset_exist(path):
    mat = eal.load_asset(path)
else:
    mat = unreal.AssetToolsHelpers.get_asset_tools().create_asset("M_Saskarta_Stele", "__DEST__", unreal.Material, unreal.MaterialFactoryNew())
mat.set_editor_property("blend_mode", unreal.BlendMode.BLEND_OPAQUE)
mel.set_material_usage(mat, unreal.MaterialUsage.MATUSAGE_NANITE)
for old in mel.get_material_expressions(mat):
    mel.delete_material_expression(mat, old)
def add(cls, x, y):
    return mel.create_material_expression(mat, cls, x, y)
def scalar(name, v, x, y, group):
    n = add(unreal.MaterialExpressionScalarParameter, x, y)
    n.set_editor_property("parameter_name", name)
    n.set_editor_property("default_value", v)
    n.set_editor_property("group", group)
    return n
def vec(name, c, x, y, group):
    n = add(unreal.MaterialExpressionVectorParameter, x, y)
    n.set_editor_property("parameter_name", name)
    n.set_editor_property("default_value", unreal.LinearColor(c[0], c[1], c[2], c[3]))
    n.set_editor_property("group", group)
    return n
def tex(name, asset, stype, x, y, group, clamp):
    n = add(unreal.MaterialExpressionTextureSampleParameter2D, x, y)
    n.set_editor_property("parameter_name", name)
    n.set_editor_property("texture", eal.load_asset(asset))
    n.set_editor_property("sampler_type", stype)
    n.set_editor_property("group", group)
    if clamp:
        n.set_editor_property("sampler_source", unreal.SamplerSourceMode.SSM_CLAMP_WORLD_GROUP_SETTINGS)
    return n
def mask(x, y, r, g, b, a):
    n = add(unreal.MaterialExpressionComponentMask, x, y)
    n.set_editor_property("r", r)
    n.set_editor_property("g", g)
    n.set_editor_property("b", b)
    n.set_editor_property("a", a)
    return n
def op(cls, x, y, cb):
    n = add(cls, x, y)
    if cb is not None:
        n.set_editor_property("const_b", cb)
    return n
def const(v, x, y):
    n = add(unreal.MaterialExpressionConstant, x, y)
    n.set_editor_property("r", v)
    return n
S = unreal.MaterialSamplerType
M = unreal.MaterialExpressionMultiply
L = unreal.MaterialExpressionLinearInterpolate
# rock
tc0 = add(unreal.MaterialExpressionTextureCoordinate, -2200, -200)
tc0.set_editor_property("coordinate_index", 0)
tiling = scalar("RockTiling", __TILING__, -2200, -100, "Rock")
uv0 = op(M, -2000, -160, None)
rockc = tex("RockColor", "__ROCKC__", S.SAMPLERTYPE_COLOR, -1800, -400, "Rock", False)
rockn = tex("RockNormal", "__ROCKN__", S.SAMPLERTYPE_NORMAL, -1800, -100, "Rock", False)
tint = vec("Tint", (1.0, 1.0, 1.0, 1.0), -1800, -560, "Rock")
rns = scalar("RockNormalStrength", 1.0, -1500, 40, "Rock")
flat = add(unreal.MaterialExpressionConstant3Vector, -1500, -40)
flat.set_editor_property("constant", unreal.LinearColor(0.0, 0.0, 1.0, 1.0))
rnl = add(L, -1300, -60)
vc = add(unreal.MaterialExpressionVertexColor, -1800, -760)
cavd = scalar("CavityDark", 0.35, -1600, -900, "Weathering")
grime = scalar("Grime", 0.55, -1600, -820, "Weathering")
grimec = vec("GrimeColor", (0.2, 0.17, 0.12, 1.0), -1600, -1000, "Weathering")
edgel = scalar("EdgeLight", 0.12, -1600, -740, "Weathering")
b0 = op(M, -1500, -480, None)
cav = op(M, -1400, -860, None)
cavk = add(unreal.MaterialExpressionOneMinus, -1250, -860)
b1 = op(M, -1150, -560, None)
gra = op(M, -1400, -780, None)
b2 = add(L, -1000, -620)
eda = op(M, -1400, -700, None)
edk = op(unreal.MaterialExpressionAdd, -1250, -700, 1.0)
b3 = op(M, -850, -600, None)
# glyph
tc1 = add(unreal.MaterialExpressionTextureCoordinate, -2200, 400)
tc1.set_editor_property("coordinate_index", 1)
rect = vec("GlyphRect", (__RECT__), -2200, 520, "Glyph")
rxy = mask(-2000, 480, True, True, False, False)
rzw = mask(-2000, 580, False, False, True, True)
gsub = op(unreal.MaterialExpressionSubtract, -1850, 420, None)
guv = op(unreal.MaterialExpressionDivide, -1700, 440, None)
cen = op(unreal.MaterialExpressionSubtract, -1700, 640, 0.5)
dab = add(unreal.MaterialExpressionAbs, -1560, 640)
inn = add(unreal.MaterialExpressionSubtract, -1430, 640)
inn.set_editor_property("const_a", 0.5)
insh = op(M, -1300, 640, 400.0)
insat = add(unreal.MaterialExpressionSaturate, -1180, 640)
mu = mask(-1060, 600, True, False, False, False)
mv = mask(-1060, 700, False, True, False, False)
inside = op(M, -930, 640, None)
gn = tex("GlyphNormal", "__GN__", S.SAMPLERTYPE_NORMAL, -1500, 260, "Glyph", True)
gao = tex("GlyphAO", "__GAO__", S.SAMPLERTYPE_LINEAR_GRAYSCALE, -1500, 500, "Glyph", True)
depth = scalar("GlyphDepth", 1.0, -930, 760, "Glyph")
wearp = scalar("Wear", 0.25, -1300, 900, "Glyph")
wearp.set_editor_property("use_custom_primitive_data", True)
wearp.set_editor_property("primitive_data_index", 0)
noise = add(unreal.MaterialExpressionNoise, -1300, 1000)
noise.set_editor_property("scale", 0.2)
noise.set_editor_property("output_min", 0.0)
noise.set_editor_property("output_max", 1.0)
noise.set_editor_property("levels", 3)
wn = op(M, -1100, 950, None)
keep = add(unreal.MaterialExpressionOneMinus, -960, 950)
k1 = op(M, -800, 700, None)
k = op(M, -680, 760, None)
groove = add(unreal.MaterialExpressionOneMinus, -1250, 520)
g3 = op(M, -1100, 520, 3.0)
g3s = add(unreal.MaterialExpressionSaturate, -980, 520)
cut = op(M, -560, 560, None)
gdark = scalar("GrooveDark", 0.8, -700, 380, "Glyph")
one = const(1.0, -700, 300)
gl = add(L, -520, 360)
bg = op(M, -380, 0, None)
dust = scalar("Dust", 0.3, -560, 460, "Glyph")
dustc = vec("DustColor", (0.55, 0.45, 0.33, 1.0), -380, 200, "Glyph")
dcut = op(M, -400, 460, None)
bfin = add(L, -220, 60)
gnl = add(L, -1200, 200)
nxy1 = mask(-1100, -60, True, True, False, False)
nz1 = mask(-1100, 20, False, False, True, False)
nxy2 = mask(-1000, 180, True, True, False, False)
nz2 = mask(-1000, 260, False, False, True, False)
nadd = op(unreal.MaterialExpressionAdd, -880, 60, None)
nmul = op(M, -880, 180, None)
napp = add(unreal.MaterialExpressionAppendVector, -760, 100)
nnorm = add(unreal.MaterialExpressionNormalize, -640, 100)
aol = add(L, -380, 700)
rough = scalar("Roughness", 0.86, -380, 820, "Rock")
r95 = const(0.95, -380, 900)
rl = add(L, -220, 820)
W = [(tc0, "", uv0, "A"), (tiling, "", uv0, "B"), (uv0, "", rockc, "UVs"), (uv0, "", rockn, "UVs"),
     (flat, "", rnl, "A"), (rockn, "RGB", rnl, "B"), (rns, "", rnl, "Alpha"),
     (rockc, "RGB", b0, "A"), (tint, "RGB", b0, "B"),
     (vc, "R", cav, "A"), (cavd, "", cav, "B"), (cav, "", cavk, ""), (b0, "", b1, "A"), (cavk, "", b1, "B"),
     (vc, "G", gra, "A"), (grime, "", gra, "B"), (b1, "", b2, "A"), (grimec, "RGB", b2, "B"), (gra, "", b2, "Alpha"),
     (vc, "B", eda, "A"), (edgel, "", eda, "B"), (eda, "", edk, "A"), (b2, "", b3, "A"), (edk, "", b3, "B"),
     (rect, "RGBA", rxy, ""), (rect, "RGBA", rzw, ""), (tc1, "", gsub, "A"), (rxy, "", gsub, "B"),
     (gsub, "", guv, "A"), (rzw, "", guv, "B"), (guv, "", gn, "UVs"), (guv, "", gao, "UVs"),
     (guv, "", cen, "A"), (cen, "", dab, ""), (dab, "", inn, "B"), (inn, "", insh, "A"), (insh, "", insat, ""),
     (insat, "", mu, ""), (insat, "", mv, ""), (mu, "", inside, "A"), (mv, "", inside, "B"),
     (wearp, "", wn, "A"), (noise, "", wn, "B"), (wn, "", keep, ""),
     (inside, "", k1, "A"), (keep, "", k1, "B"), (k1, "", k, "A"), (depth, "", k, "B"),
     (gao, "R", groove, ""), (groove, "", g3, "A"), (g3, "", g3s, ""), (g3s, "", cut, "A"), (k, "", cut, "B"),
     (one, "", gl, "A"), (gdark, "", gl, "B"), (cut, "", gl, "Alpha"), (b3, "", bg, "A"), (gl, "", bg, "B"),
     (cut, "", dcut, "A"), (dust, "", dcut, "B"), (bg, "", bfin, "A"), (dustc, "RGB", bfin, "B"), (dcut, "", bfin, "Alpha"),
     (flat, "", gnl, "A"), (gn, "RGB", gnl, "B"), (k, "", gnl, "Alpha"),
     (rnl, "", nxy1, ""), (rnl, "", nz1, ""), (gnl, "", nxy2, ""), (gnl, "", nz2, ""),
     (nxy1, "", nadd, "A"), (nxy2, "", nadd, "B"), (nz1, "", nmul, "A"), (nz2, "", nmul, "B"),
     (nadd, "", napp, "A"), (nmul, "", napp, "B"), (napp, "", nnorm, ""),
     (one, "", aol, "A"), (gao, "R", aol, "B"), (k, "", aol, "Alpha"),
     (rough, "", rl, "A"), (r95, "", rl, "B"), (cut, "", rl, "Alpha")]
bad = []
for a, ao_, b, bi in W:
    if not mel.connect_material_expressions(a, ao_, b, bi):
        bad.append(str(bi) + "@" + str(W.index((a, ao_, b, bi))))
P = unreal.MaterialProperty
ok = [mel.connect_material_property(bfin, "", P.MP_BASE_COLOR), mel.connect_material_property(nnorm, "", P.MP_NORMAL),
      mel.connect_material_property(rl, "", P.MP_ROUGHNESS), mel.connect_material_property(aol, "", P.MP_AMBIENT_OCCLUSION)]
errs = [str(e) for e in mel.recompile_material(mat)]
print("STELEMAT nodes=" + str(len(mel.get_material_expressions(mat))) + " bad_links=" + str(bad) + " props=" + str(ok) + " errors=" + str(len(errs)) + " first_errors=" + str(errs[:3]) + " saved=" + str(eal.save_loaded_asset(mat, False)))
'''

INSTANCE = r'''
import unreal
eal = unreal.EditorAssetLibrary
mel = unreal.MaterialEditingLibrary
name = "__MI__"
path = "__DEST__/" + name
if eal.does_asset_exist(path):
    mi = eal.load_asset(path)
else:
    mi = unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, "__DEST__", unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
mel.set_material_instance_parent(mi, eal.load_asset("__MAT__"))
mel.set_material_instance_scalar_parameter_value(mi, "GlyphDepth", __DEPTH__)
mel.set_material_instance_scalar_parameter_value(mi, "RockNormalStrength", __RNS__)
if "__GID__" != "none":
    mel.set_material_instance_texture_parameter_value(mi, "GlyphNormal", eal.load_asset("__INSCR__/T_Inscription___GID___N"))
    mel.set_material_instance_texture_parameter_value(mi, "GlyphAO", eal.load_asset("__INSCR__/T_Inscription___GID___AO"))
    mel.set_material_instance_vector_parameter_value(mi, "GlyphRect", unreal.LinearColor(__RECT__))
mel.update_material_instance(mi)
print("MI " + name + " saved=" + str(eal.save_loaded_asset(mi, False)))
'''

ASSIGN = r'''
import unreal
eal = unreal.EditorAssetLibrary
m = eal.load_asset("__DEST__/__NAME__")
body = eal.load_asset("__BODY__")
face = eal.load_asset("__FACE__")
names = [str(s.material_slot_name) for s in m.get_editor_property("static_materials")]
si = m.get_material_index("Stone")
fi = m.get_material_index("Face")
if si < 0 or fi < 0:
    print("ASSIGN __NAME__ slot names " + str(names) + " not Stone/Face: using the order 0, 1")
    si, fi = 0, 1
m.set_material(si, body)
m.set_material(fi, face)
print("ASSIGN __NAME__ " + str(names) + " stone=" + str(si) + " face=" + str(fi) + " saved=" + str(eal.save_loaded_asset(m, False)))
'''

CLEANUP = r'''
import unreal
eal = unreal.EditorAssetLibrary
APPLY = __APPLY__
KEEP = __KEEP__
gone, kept = [], []
for p in eal.list_assets("__DEST__", True, False):
    obj = str(p).split(".")[0]
    nm = obj.split("/")[-1]
    a = eal.find_asset_data(obj)
    cls = str(a.asset_class_path.asset_name)
    if nm.startswith(KEEP):
        kept.append(nm)
        continue
    if cls not in ("MaterialInstanceConstant", "Material", "Texture2D"):
        kept.append(nm + "(" + cls + ")")
        continue
    refs = [str(r) for r in eal.find_package_referencers_for_asset(obj, False)]
    if refs:
        kept.append(nm + "(used by " + str(len(refs)) + ")")
        continue
    gone.append(nm)
    if APPLY:
        eal.delete_asset(obj)
print("CLEANUP apply=" + str(APPLY) + " delete=" + str(gone) + " keep=" + str(kept))
'''

LOAD = r'''
import unreal
lib = unreal.WorldPartitionBlueprintLibrary
r = lib.get_intersecting_actor_descs(lib.get_editor_world_bounds())
descs = r[1] if isinstance(r, tuple) else r
want = [d.get_editor_property("guid") for d in descs if str(d.get_editor_property("label")).startswith("Stele_")]
part = want[__A__:__B__]
if part:
    lib.load_actors(part)
print("LOAD stele descs=" + str(len(want)) + " loaded_now=" + str(len(part)))
'''

UNLOAD = r'''
import unreal
lib = unreal.WorldPartitionBlueprintLibrary
r = lib.get_intersecting_actor_descs(lib.get_editor_world_bounds())
descs = r[1] if isinstance(r, tuple) else r
gs = [d.get_editor_property("guid") for d in descs if str(d.get_editor_property("label")).startswith("Stele_")]
if gs:
    lib.unload_actors(gs)
    lib.unpin_actors(gs)
print("UNLOAD " + str(len(gs)))
'''

# How many stele actors are loaded right now, and how many of their packages are dirty (unsaved).
RESIDENT = r'''
import unreal
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
dirty = set([p.get_name() for p in unreal.EditorLoadingAndSavingUtils.get_dirty_map_packages()])
st = [a for a in eas.get_all_level_actors() if a.get_actor_label().startswith("Stele_")]
dl = [a.get_actor_label() for a in st if a.get_package().get_name() in dirty]
print("RESIDENT loaded=" + str(len(st)) + " dirty=" + str(len(dl)) + " dirty_labels=" + str(dl[:6]))
'''

# modify() first on everything this touches: the setters below (set_static_mesh, set_actor_scale3d,
# set_visibility, set_actor_hidden_in_game, set_actor_location/rotation, set_material,
# set_default_custom_primitive_data_float) do not mark the external actor package dirty, and save writes
# only dirty packages. The report lists any touched actor whose package is still clean.
SWAP = r'''
import unreal
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
ITEMS = __ITEMS__
MODE = "__MODE__"
have = {}
for a in eas.get_all_level_actors():
    lb = a.get_actor_label()
    if lb.startswith("Stele_"):
        have[lb] = a
body = unreal.load_asset("__BODY__")
done, missing, touched = 0, [], []
for it in ITEMS:
    s = have.get(it["name"])
    if s is None:
        missing.append(it["name"])
        continue
    c = s.static_mesh_component
    g = have.get(it["name"] + "_Glyph")
    s.modify()
    c.modify()
    touched.append(s)
    if g is not None:
        g.modify()
        g.decal.modify()
        touched.append(g)
    c.set_static_mesh(unreal.load_asset(it["mesh"]))
    s.set_actor_scale3d(unreal.Vector(it["scale"], it["scale"], it["scale"]))
    c.set_editor_property("override_materials", [])
    wear = 0.3
    if g is not None:
        wear = g.decal.get_editor_property("decal_color").a
    # Runtime Custom Primitive Data is transient. Use the component default so wear survives
    # external actor package save/unload/reload and is available before gameplay code runs.
    c.set_default_custom_primitive_data_float(0, wear)
    if g is not None and MODE == "uv1":
        g.decal.set_visibility(False, False)
        g.set_actor_hidden_in_game(True)
    if g is not None and MODE == "decal":
        c.set_material(1, body)
        t = s.get_actor_transform()
        g.set_actor_location(unreal.MathLibrary.transform_location(t, unreal.Vector(it["face_x"] + 2.0, 0.0, it["gz"])), False, False)
        g.set_actor_rotation(unreal.MathLibrary.compose_rotators(unreal.Rotator(roll=0.0, pitch=0.0, yaw=180.0), s.get_actor_rotation()), False)
        g.set_actor_scale3d(unreal.Vector(1.0, 1.0, 1.0))
        g.decal.set_editor_property("decal_size", unreal.Vector(6.0, it["gw"] * it["scale"] * 0.5, it["gh"] * it["scale"] * 0.5))
        g.decal.set_visibility(True, False)
        g.set_actor_hidden_in_game(False)
    done += 1
dirty = set([p.get_name() for p in unreal.EditorLoadingAndSavingUtils.get_dirty_map_packages()])
clean = [a.get_actor_label() for a in touched if a.get_package().get_name() not in dirty]
print("SWAP mode=" + MODE + " done=" + str(done) + " touched=" + str(len(touched)) + " missing=" + str(missing) + " not_dirty=" + str(clean))
'''

# Stele and glyph actors (the labels start with Stele_), sorted by package so the chunks are stable
# across calls. Reports how many were dirty and which are still dirty after the save.
SAVE = r'''
import unreal
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
els = unreal.EditorLoadingAndSavingUtils
pk = sorted([a.get_package() for a in eas.get_all_level_actors() if a.get_actor_label().startswith("Stele_")], key=lambda p: p.get_name())
part = pk[__CHUNK__ * __SIZE__:(__CHUNK__ + 1) * __SIZE__]
before = set([p.get_name() for p in els.get_dirty_map_packages()])
nd = len([p for p in part if p.get_name() in before])
ok = els.save_packages(part, True) if part else True
after = set([p.get_name() for p in els.get_dirty_map_packages()])
left = [p.get_name().split("/")[-1] for p in part if p.get_name() in after]
print("SAVE total=" + str(len(pk)) + " chunk=__CHUNK__ n=" + str(len(part)) + " dirty=" + str(nd) + " ok=" + str(ok) + " left_dirty=" + str(left))
'''

# One line per stele (what it draws, and the state of its old decal), then the expected-state check.
# A dirty package is a problem: verify must read what the save wrote.
VERIFY = r'''
import unreal
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
ITEMS = __ITEMS__
MODE = "__MODE__"
have = {}
for a in eas.get_all_level_actors():
    lb = a.get_actor_label()
    if lb.startswith("Stele_"):
        have[lb] = a
dirty = set([p.get_name() for p in unreal.EditorLoadingAndSavingUtils.get_dirty_map_packages()])
bad, count = [], 0
for it in ITEMS:
    nm = it["name"]
    s = have.get(nm)
    if s is None:
        bad.append(nm + " not loaded")
        continue
    count += 1
    c = s.static_mesh_component
    mesh = c.get_editor_property("static_mesh")
    mn = mesh.get_name() if mesh else "none"
    mats = [(c.get_material(i).get_name() if c.get_material(i) else "none") for i in range(c.get_num_materials())]
    cpd = [round(x, 2) for x in c.get_editor_property("custom_primitive_data").get_editor_property("data")]
    ov = len([m for m in c.get_editor_property("override_materials") if m])
    sc = s.get_actor_scale3d().x
    g = have.get(nm + "_Glyph")
    gvis, ghid = None, None
    if g is not None:
        gvis = g.decal.is_visible()
        ghid = g.get_editor_property("hidden")
    print("VERIFY " + nm + " mesh=" + mn + " scale=" + str(round(sc, 3)) + " overrides=" + str(ov) + " wear=" + str(cpd) + " mats=" + str(mats) + " glyph_visible=" + str(gvis) + " glyph_hidden_in_game=" + str(ghid))
    if mn != it["mesh_name"]:
        bad.append(nm + " mesh " + mn)
    if abs(sc - it["scale"]) > 0.002:
        bad.append(nm + " scale " + str(round(sc, 3)))
    if len(cpd) < 1:
        bad.append(nm + " no wear in custom primitive data")
    if mats != it["want_mats"]:
        bad.append(nm + " mats " + str(mats))
    if ov != it["want_overrides"]:
        bad.append(nm + " overrides " + str(ov))
    if g is not None and (gvis != it["glyph_on"] or ghid == it["glyph_on"]):
        bad.append(nm + "_Glyph visible=" + str(gvis) + " hidden_in_game=" + str(ghid))
    if g is None and it["glyph_on"]:
        bad.append(nm + "_Glyph missing")
    for x in [s, g]:
        if x is not None and x.get_package().get_name() in dirty:
            bad.append(x.get_actor_label() + " unsaved (package dirty)")
print("VERIFY count=" + str(count) + " problems=" + str(len(bad)) + " first=" + str(bad[:8]))
'''


# ------------------------------------------------------------------------------------------------
def swap_items(meshes, mode):
    """The 34 way-stones and 2 dock posts: which mesh, which scale, and what verify expects after the
    swap in this glyph mode. Deterministic (seed 505)."""
    rng = random.Random(505)
    items, prev = [], None
    for i in range(34):
        choice = rng.choice([w for w in WAY_MESHES if w != prev])
        prev = choice
        items.append((f"Stele_WayStone_{i}", choice, round(rng.uniform(0.92, 1.08), 3)))
    items += [("Stele_DockPost_A", "DockPost", 1.0), ("Stele_DockPost_B", "DockPost", 0.97)]
    body = BODY_MI.split("/")[-1]
    out = []
    for name, mesh, scale in items:
        info = meshes[mesh]
        face = f"MI_Stele_Face_{mesh}" if mode == "uv1" else body
        out.append({"name": name, "mesh": f"{DEST}/{info['mesh']}", "mesh_name": info["mesh"], "scale": scale,
                    "face_x": info["front_face_x_cm"], "gz": info["glyph_centre_cm"][2],
                    "gw": info["glyph_size_cm"][0], "gh": info["glyph_size_cm"][1],
                    "want_mats": [body, face],                      # slot 0 Stone, slot 1 Face
                    "want_overrides": 0 if mode == "uv1" else 1,    # decal mode overrides the Face slot
                    "glyph_on": mode == "decal"})                   # the old decal draws only in decal mode
    return out


def scripts_for_check():
    meshes = manifest()
    first = next(iter(meshes.values()))
    yield "glyphmap", fill(GLYPHMAP, PATH=f"{INSCR}/T_Inscription_I05_N")
    yield "import", fill(IMPORT, DEST=DEST, FILE="D:/x.glb", NAME="SM_Stele_X")
    yield "fixmesh", fill(FIXMESH, DEST=DEST, NAME="SM_Stele_X")
    yield "nanite", fill(NANITE, DEST=DEST, NAME="SM_Stele_X")
    yield "material", fill(MATERIAL, DEST=DEST, MAT=MAT, TILING=ROCK_TILING, ROCKC=ROCK_COLOR, ROCKN=ROCK_NORMAL,
                           RECT=", ".join(str(x) for x in first["glyph_rect_uv1"]),
                           GN=f"{INSCR}/T_Inscription_I05_N", GAO=f"{INSCR}/T_Inscription_I05_AO")
    yield "instance", fill(INSTANCE, DEST=DEST, MAT=MAT, MI="MI_Stele_X", DEPTH=1.0, RNS=0.45, GID="I05", INSCR=INSCR,
                           RECT="0.1, 0.2, 0.7, 0.4")
    yield "assign", fill(ASSIGN, DEST=DEST, NAME="SM_Stele_X", BODY=BODY_MI, FACE=f"{DEST}/MI_Stele_Face_X")
    yield "cleanup", fill(CLEANUP, DEST=DEST, APPLY=False, KEEP=repr(OUR_PREFIXES))
    yield "load", fill(LOAD, A=0, B=LOAD_CHUNK)
    yield "unload", fill(UNLOAD)
    yield "resident", fill(RESIDENT)
    for mode in ("uv1", "decal"):
        items = swap_items(meshes, mode)
        yield f"swap_{mode}", fill(SWAP, ITEMS=repr(items[:SWAP_CHUNK]), MODE=mode, BODY=BODY_MI)
        yield f"verify_{mode}", fill(VERIFY, ITEMS=repr(items), MODE=mode)
    yield "save", fill(SAVE, CHUNK=0, SIZE=SAVE_CHUNK)


def readonly_level_actors():
    """Read-only external actor packages of Saskarta_WP. Saving a read-only package through python_run
    crashed the editor once (committed-uassets-are-read-only), so save refuses while there are any."""
    if not LEVEL_ACTORS.exists():
        return []
    return [p for p in LEVEL_ACTORS.rglob("*.uasset") if not os.access(p, os.W_OK)]


def check():
    problems = []
    meshes = manifest()
    for name, info in meshes.items():
        f = SRC / info["file"]
        if not f.exists():
            problems.append(f"missing {f}")
        u0, v0, su, sv = info["glyph_rect_uv1"]
        if not (0 <= u0 and u0 + su <= 1 and 0 <= v0 and v0 + sv <= 1):
            problems.append(f"{name}: glyph rect outside 0..1")
    for gid in GLYPH_IDS:
        p = asset_file(f"{INSCR}/T_Inscription_{gid}_N")
        if p.exists() and not os.access(p, os.W_OK):
            problems.append(f"read-only: {p} (make it writable before 'glyphmaps')")
    for label, s in scripts_for_check():
        if len(s) > 60000:
            problems.append(f"{label}: script too long")
        compile(s, label, "exec")                     # a syntax error must fail here, not in the editor
    for path in (ROCK_COLOR, ROCK_NORMAL):
        if not asset_file(path).exists():
            problems.append(f"missing rock texture {path}")
    ro = readonly_level_actors()
    if ro:
        problems.append(f"{len(ro)} read-only actor packages under {LEVEL_ACTORS} (e.g. {ro[0]}): 'save' would fail on them")
    print("\n".join(problems) if problems else "ok: manifest, files, scripts clean")
    return 1 if problems else 0


def load_all():
    """Load every Stele_* actor, LOAD_CHUNK per call (own calls, nothing else in them)."""
    lo, total = 0, 1
    while lo < total:
        out = run(fill(LOAD, A=lo, B=lo + LOAD_CHUNK))
        total = number(out, "descs")
        lo += LOAD_CHUNK
    return total


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("step", choices=["check", "glyphmaps", "import", "fixmesh", "nanite", "material", "instances",
                                     "assign", "cleanup", "load", "swap", "save", "unload", "verify"])
    ap.add_argument("names", nargs="*", help="mesh keys (WayStone_A ...), default all")
    ap.add_argument("--apply", action="store_true", help="cleanup: really delete")
    ap.add_argument("--glyph", choices=["uv1", "decal"], default="uv1")
    a = ap.parse_args(argv)
    if a.step == "check":
        return check()
    meshes = manifest()
    names = a.names or list(meshes)
    if a.step == "glyphmaps":
        for gid in GLYPH_IDS:
            p = asset_file(f"{INSCR}/T_Inscription_{gid}_N")
            if p.exists() and not os.access(p, os.W_OK):
                raise SystemExit(f"{p} is read-only: make it writable first (never save a read-only package)")
            out = run(fill(GLYPHMAP, PATH=f"{INSCR}/T_Inscription_{gid}_N"))
            require(out, f"glyphmaps {gid}", "-> True saved=True")
    elif a.step in ("import", "fixmesh", "nanite"):
        tmpl = {"import": IMPORT, "fixmesh": FIXMESH, "nanite": NANITE}[a.step]
        want = {"import": ("uv=2 ", "vcol=True", "saved=True"), "fixmesh": ("uv=2 ", "settings_ok=True"),
                "nanite": ("nanite=True", "uv=2 ", "saved=True")}[a.step]
        for n in names:
            info = meshes[n]
            out = run(fill(tmpl, DEST=DEST, NAME=info["mesh"], FILE=(SRC / info["file"]).as_posix()))
            require(out, f"{a.step} {n}", *want)
    elif a.step == "material":
        first = meshes[WAY_MESHES[0]]
        out = run(fill(MATERIAL, DEST=DEST, MAT=MAT, TILING=ROCK_TILING, ROCKC=ROCK_COLOR, ROCKN=ROCK_NORMAL,
                       RECT=", ".join(str(x) for x in first["glyph_rect_uv1"]),
                       GN=f"{INSCR}/T_Inscription_I05_N", GAO=f"{INSCR}/T_Inscription_I05_AO"))
        # the translator's errors come back synchronously; a material that did not compile draws the
        # default material on every MI_Stele_*, so this is the pass condition, not bad_links alone
        require(out, "material", "bad_links=[]", "props=[True, True, True, True]", "errors=0 ", "saved=True")
    elif a.step == "instances":
        out = run(fill(INSTANCE, DEST=DEST, MAT=MAT, MI="MI_Stele_Body", DEPTH=0.0, RNS=1.0, GID="none", INSCR=INSCR,
                       RECT="0, 0, 1, 1"))
        require(out, "instances MI_Stele_Body", "saved=True")
        for n in names:
            info = meshes[n]
            out = run(fill(INSTANCE, DEST=DEST, MAT=MAT, MI=f"MI_Stele_Face_{n}", DEPTH=1.0, RNS=0.45, GID=info["glyph"],
                           INSCR=INSCR, RECT=", ".join(str(x) for x in info["glyph_rect_uv1"])))
            require(out, f"instances MI_Stele_Face_{n}", "saved=True")
    elif a.step == "assign":
        for n in names:
            out = run(fill(ASSIGN, DEST=DEST, NAME=meshes[n]["mesh"], BODY=BODY_MI, FACE=f"{DEST}/MI_Stele_Face_{n}"))
            require(out, f"assign {n}", "saved=True")
    elif a.step == "cleanup":
        run(fill(CLEANUP, DEST=DEST, APPLY=bool(a.apply), KEEP=repr(OUR_PREFIXES)))
    elif a.step == "load":
        load_all()
    elif a.step == "unload":
        run(fill(UNLOAD))
    elif a.step == "swap":
        items = swap_items(meshes, a.glyph)
        for i in range(0, len(items), SWAP_CHUNK):
            out = run(fill(SWAP, ITEMS=repr(items[i:i + SWAP_CHUNK]), MODE=a.glyph, BODY=BODY_MI))
            require(out, "swap", "missing=[]", "not_dirty=[]")
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
        print(f"save: {total} stele/glyph packages checked, none left dirty")
    elif a.step == "verify":
        out = run(fill(RESIDENT))
        if number(out, "dirty"):
            raise SystemExit("verify: stele packages are still dirty (unsaved): run 'save' first, then 'unload'")
        if number(out, "loaded"):
            print(f"verify: {number(out, 'loaded')} stele actors were still loaded (an editor region keeps them);"
                  " they are clean, so they match what was saved")
        load_all()
        out = run(fill(VERIFY, ITEMS=repr(swap_items(meshes, a.glyph)), MODE=a.glyph))
        run(fill(UNLOAD))
        if number(out, "count") != 36 or number(out, "problems"):
            raise SystemExit("verify: FAILED (see the VERIFY lines above)")
        print("verify: 36 steles as expected, read back after the save")
    return 0


if __name__ == "__main__":
    sys.exit(main())
