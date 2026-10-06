"""Saskartan inscriptions in the world (task INSCR): import, the carved-glyph decal material, placement.

    python Tools/Story/import_inscriptions.py import I05 I02     # textures -> /Game/SaskartaGaea/Inscriptions
    python Tools/Story/import_inscriptions.py material            # M_Saskarta_CarvedGlyph (deferred decal)
    python Tools/Story/import_inscriptions.py instances I05 I02   # MI_Glyph_<ID>_Carved
    python Tools/Story/import_inscriptions.py check               # offline: banned words in the editor scripts

Generic by ID: a new name is SourceArt/Inscriptions/T_Inscription_<ID>.png, then
`python Tools/Story/carve_inscription.py <ID>` (the chisel maps), then `import <ID>` and `instances <ID>`.

Per ID the importer brings in (from SourceArt/Inscriptions):
  T_Inscription_<ID>      the glyph, alpha only (Alpha/Grayscale BC4, sRGB off, mips on)
  T_Inscription_<ID>_N    the chisel V-groove normal map (OpenGL green: imported with Flip Green) -> TC_Normalmap
  T_Inscription_<ID>_AO   groove occlusion + dust mask (grayscale, sRGB off)
The 16-bit height map (_H) is not imported: the steles are not Nanite-displaced, so the cut is the
normal map plus darkening (the brief's fallback). It stays in SourceArt for a later displacement pass.

M_Saskarta_CarvedGlyph is a deferred decal (DBuffer: colour, normal, roughness):
  groove  = 1 - AO                                  (0 on the stone face, 1 at the bottom of the cut)
  wear    = Wear x DecalColor.A-driven noise erosion (0 = crisp, 1 = nearly worn away)
  opacity = saturate(groove x 3) x (1 - wear x noise)
  colour  = Tint x lerp(1, GrooveDark, groove), then lerp toward DustColor by groove x Dust
            (stone-coloured, only slightly darker inside: never black paint)
  normal  = lerp(flat, N, Depth)
  roughness 0.92
Parameters: Glyph (texture, kept for the silhouette), GlyphNormal, GlyphAO, Depth, Wear, Tint,
GrooveDark, DustColor, Dust. Per-instance wear comes from the decal component's DecalColor alpha
(MaterialExpressionDecalColor), so 34 way-stones share one MI and still vary.
Hold the editor gate (Tools/GameFlow/editor_gate.py) for every editor step.
"""
import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Tools" / "Look"))
from apply_look import python_run, check_banned  # noqa: E402

SRC = ROOT / "SourceArt" / "Inscriptions"
DEST = "/Game/SaskartaGaea/Inscriptions"
MAT = f"{DEST}/M_Saskarta_CarvedGlyph"

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
unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
t = eal.load_asset("__DEST__/__NAME__")
kind = "__KIND__"
if kind == "normal":
    t.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_NORMALMAP)
    t.set_editor_property("srgb", False)
    t.set_editor_property("flip_green_channel", True)   # the chisel maps are OpenGL green (+G = up); UE wants DirectX
elif kind == "alpha":
    t.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_ALPHA)
    t.set_editor_property("srgb", False)
else:
    t.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_GRAYSCALE)
    t.set_editor_property("srgb", False)
t.set_editor_property("mip_gen_settings", unreal.TextureMipGenSettings.TMGS_FROM_TEXTURE_GROUP)
t.set_editor_property("lod_group", unreal.TextureGroup.TEXTUREGROUP_WORLD_NORMAL_MAP if kind == "normal" else unreal.TextureGroup.TEXTUREGROUP_WORLD)
print("INS " + "__NAME__" + " " + str(t.blueprint_get_size_x()) + "x" + str(t.blueprint_get_size_y()) + " saved=" + str(eal.save_loaded_asset(t, False)))
'''

MATERIAL = r'''
import unreal
mel = unreal.MaterialEditingLibrary
eal = unreal.EditorAssetLibrary
QUIET = unreal.MaterialEditingLibrary
path = "__MAT__"
if eal.does_asset_exist(path):
    mat = eal.load_asset(path)
else:
    mat = unreal.AssetToolsHelpers.get_asset_tools().create_asset("M_Saskarta_CarvedGlyph", "__DEST__", unreal.Material, unreal.MaterialFactoryNew())
mat.set_editor_property("material_domain", unreal.MaterialDomain.MD_DEFERRED_DECAL)
mat.set_editor_property("blend_mode", unreal.BlendMode.BLEND_TRANSLUCENT)
for old in mel.get_material_expressions(mat):
    mel.delete_material_expression(mat, old)
def add(cls, x, y):
    return mel.create_material_expression(mat, cls, x, y)
def scalar(name, v, x, y):
    n = add(unreal.MaterialExpressionScalarParameter, x, y)
    n.set_editor_property("parameter_name", name)
    n.set_editor_property("default_value", v)
    n.set_editor_property("group", "Carve")
    return n
def vec(name, c, x, y):
    n = add(unreal.MaterialExpressionVectorParameter, x, y)
    n.set_editor_property("parameter_name", name)
    n.set_editor_property("default_value", unreal.LinearColor(c[0], c[1], c[2], 1.0))
    n.set_editor_property("group", "Carve")
    return n
def tex(name, asset, stype, x, y):
    n = add(unreal.MaterialExpressionTextureSampleParameter2D, x, y)
    n.set_editor_property("parameter_name", name)
    n.set_editor_property("texture", eal.load_asset(asset))
    n.set_editor_property("sampler_type", stype)
    n.set_editor_property("group", "Carve")
    return n
S = unreal.MaterialSamplerType
nrm = tex("GlyphNormal", "__DEST__/T_Inscription_I05_N", S.SAMPLERTYPE_NORMAL, -1400, 0)
ao = tex("GlyphAO", "__DEST__/T_Inscription_I05_AO", S.SAMPLERTYPE_LINEAR_GRAYSCALE, -1400, 300)
depth = scalar("Depth", 1.0, -1100, -120)
wear = scalar("Wear", 0.0, -1400, 560)
dark = scalar("GrooveDark", 0.78, -900, 420)
dust = scalar("Dust", 0.35, -900, 520)
tint = vec("Tint", (0.42, 0.38, 0.33), -900, 300)
dustc = vec("DustColor", (0.55, 0.45, 0.33), -900, 620)
flat = add(unreal.MaterialExpressionConstant3Vector, -1100, -220)
flat.set_editor_property("constant", unreal.LinearColor(0.0, 0.0, 1.0, 1.0))
nlerp = add(unreal.MaterialExpressionLinearInterpolate, -800, -100)
groove = add(unreal.MaterialExpressionOneMinus, -1100, 300)
g3 = add(unreal.MaterialExpressionMultiply, -800, 200)
g3.set_editor_property("const_b", 3.0)
gsat = add(unreal.MaterialExpressionSaturate, -650, 200)
# wear: world-position noise, scaled by Wear x DecalColor.A (per-instance)
noise = add(unreal.MaterialExpressionNoise, -1400, 700)
noise.set_editor_property("scale", 0.08)
noise.set_editor_property("output_min", 0.0)
noise.set_editor_property("output_max", 1.0)
noise.set_editor_property("levels", 3)
dcol = add(unreal.MaterialExpressionDecalColor, -1400, 860)
wa = add(unreal.MaterialExpressionMultiply, -1150, 620)
wn = add(unreal.MaterialExpressionMultiply, -950, 700)
keep = add(unreal.MaterialExpressionOneMinus, -800, 700)
op = add(unreal.MaterialExpressionMultiply, -500, 260)
dl = add(unreal.MaterialExpressionLinearInterpolate, -650, 360)
one = add(unreal.MaterialExpressionConstant, -800, 360)
one.set_editor_property("r", 1.0)
col = add(unreal.MaterialExpressionMultiply, -500, 380)
dmix = add(unreal.MaterialExpressionMultiply, -650, 560)
cfin = add(unreal.MaterialExpressionLinearInterpolate, -350, 420)
rough = add(unreal.MaterialExpressionConstant, -350, 560)
rough.set_editor_property("r", 0.92)
L = [(flat, "", nlerp, "A"), (nrm, "RGB", nlerp, "B"), (depth, "", nlerp, "Alpha"),
     (ao, "R", groove, ""), (groove, "", g3, "A"), (g3, "", gsat, ""),
     (wear, "", wa, "A"), (dcol, "A", wa, "B"), (wa, "", wn, "A"), (noise, "", wn, "B"), (wn, "", keep, ""),
     (gsat, "", op, "A"), (keep, "", op, "B"),
     (one, "", dl, "A"), (dark, "", dl, "B"), (groove, "", dl, "Alpha"),
     (tint, "RGB", col, "A"), (dl, "", col, "B"),
     (groove, "", dmix, "A"), (dust, "", dmix, "B"),
     (col, "", cfin, "A"), (dustc, "RGB", cfin, "B"), (dmix, "", cfin, "Alpha")]
bad = []
for a, ao_, b, bi in L:
    if not mel.connect_material_expressions(a, ao_, b, bi):
        bad.append(str(bi))
P = unreal.MaterialProperty
ok = [mel.connect_material_property(cfin, "", P.MP_BASE_COLOR), mel.connect_material_property(nlerp, "", P.MP_NORMAL),
      mel.connect_material_property(rough, "", P.MP_ROUGHNESS), mel.connect_material_property(op, "", P.MP_OPACITY)]
errs = mel.recompile_material(mat)
print("CG bad_links=" + str(bad) + " props=" + str(ok) + " errors=" + str(len(errs)) + " saved=" + str(eal.save_loaded_asset(mat, False)))
'''

INSTANCE = r'''
import unreal
eal = unreal.EditorAssetLibrary
mel = unreal.MaterialEditingLibrary
name = "MI_Glyph___ID___Carved"
path = "__DEST__/" + name
if eal.does_asset_exist(path):
    mi = eal.load_asset(path)
else:
    fac = unreal.MaterialInstanceConstantFactoryNew()
    mi = unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, "__DEST__", unreal.MaterialInstanceConstant, fac)
mel.set_material_instance_parent(mi, eal.load_asset("__MAT__"))
mel.set_material_instance_texture_parameter_value(mi, "GlyphNormal", eal.load_asset("__DEST__/T_Inscription___ID___N"))
mel.set_material_instance_texture_parameter_value(mi, "GlyphAO", eal.load_asset("__DEST__/T_Inscription___ID___AO"))
mel.update_material_instance(mi)
print("MI " + name + " saved=" + str(eal.save_loaded_asset(mi, False)))
'''


def fill(t, **kw):
    for k, v in kw.items():
        t = t.replace(f"__{k}__", v)
    return check_banned(t)


def run(script):
    ok, out, err = python_run(script)
    print(out.strip() or err)
    if not ok:
        raise SystemExit(f"editor step failed: {err}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("step", choices=["import", "material", "instances", "check"])
    ap.add_argument("ids", nargs="*")
    a = ap.parse_args(argv)
    if a.step == "check":
        fill(IMPORT, DEST=DEST, FILE="x", NAME="x", KIND="x")
        fill(MATERIAL, DEST=DEST, MAT=MAT)
        fill(INSTANCE, DEST=DEST, MAT=MAT, ID="I05")
        print("ok")
    elif a.step == "import":
        for gid in a.ids:
            for suffix, kind in (("", "alpha"), ("_N", "normal"), ("_AO", "gray")):
                name = f"T_Inscription_{gid}{suffix}"
                run(fill(IMPORT, DEST=DEST, FILE=(SRC / f"{name}.png").as_posix(), NAME=name, KIND=kind))
    elif a.step == "material":
        run(fill(MATERIAL, DEST=DEST, MAT=MAT))
    else:
        for gid in a.ids:
            run(fill(INSTANCE, DEST=DEST, MAT=MAT, ID=gid))


if __name__ == "__main__":
    main()
