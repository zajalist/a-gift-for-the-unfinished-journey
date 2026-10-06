"""Build the separate optical sensor-glass pass. Run `check`, then each editor step separately.

Editor order: import-crack, import-frost, import-drop, import-flat, import-zero,
material, mi, legacy, place, readback. Requires the dual-MID SaskartaSensorFilter build.
"""
import argparse
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "Tools" / "UI"))
from apply_look import check_banned, python_run  # noqa: E402
from make_sensor_glass import DEFAULTS  # noqa: E402

SRC = ROOT / "Saved" / "UI" / "SensorGlass"
TEXDIR = "/Game/SaskartaGaea/UI/SensorGlass"
MAT = "/Game/SaskartaGaea/Look/M_PP_SensorGlass"
MI = "/Game/SaskartaGaea/Look/MI_PP_SensorGlass"
CRT = "/Game/SaskartaGaea/Look/MI_PP_SensorCRT"
MPC = "/Game/SaskartaGaea/Look/MPC_Saskarta_Sky.MPC_Saskarta_Sky"
PPV = "PPV_Saskarta_Sensor"
HLSL = ROOT / "Shaders" / "SensorGlass.ush"
MAPS = {
    "crack": ("T_SensorGlass_CrackN", "T_SensorGlass_CrackN_1024.png", False),
    "frost": ("T_SensorGlass_Frost", "T_SensorGlass_Frost.png", False),
    "drop": ("T_SensorGlass_DropQ", "T_SensorGlass_DropQ.png", True),
    "flat": ("T_SensorGlass_FlatN", "T_SensorGlass_FlatN.png", False),
    "zero": ("T_SensorGlass_Zero", "T_SensorGlass_Zero.png", False),
}
PINS = ["UV", "ViewSize", "Time", "SceneColorDummy", "Amount", "GustPeriod", "Flash", "Storm",
        "SunDirV", "SunLum", "CrackN", "FrostM", "DropQ", "P0", "P1", "P2"]
PARAMS = {
    "P0": tuple(DEFAULTS[k] for k in ("CrackSpread", "DropSpread", "DropDensity", "DropCycle")),
    "P1": tuple(DEFAULTS[k] for k in ("DispDrops", "FrostPx", "FrostLift", "GlintK")),
    "P2": tuple(DEFAULTS[k] for k in ("Humidity", "Headlight", "SunRef", "RunnerRate")),
}

IMPORT = r'''
import unreal
t = unreal.AssetImportTask()
t.set_editor_property("filename", __SOURCE__)
t.set_editor_property("destination_path", "__DIR__")
t.set_editor_property("destination_name", "__NAME__")
t.set_editor_property("replace_existing", True)
t.set_editor_property("automated", True)
t.set_editor_property("save", False)
unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([t])
tex = unreal.load_asset("__DIR__/__NAME__")
if tex is None:
    raise RuntimeError("glass texture import failed: __NAME__")
tex.set_editor_property("srgb", False)
if "__NAME__" == "T_SensorGlass_FlatN":
    tex.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_NORMALMAP)
    tex.set_editor_property("flip_green_channel", False)
else:
    tex.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_VECTOR_DISPLACEMENTMAP)
tex.set_editor_property("lod_group", unreal.TextureGroup.TEXTUREGROUP_UI)
tex.set_editor_property("never_stream", True)
tex.set_editor_property("mip_gen_settings", unreal.TextureMipGenSettings.TMGS_NO_MIPMAPS)
tex.set_editor_property("address_x", unreal.TextureAddress.__ADDR__)
tex.set_editor_property("address_y", unreal.TextureAddress.__ADDR__)
tex.set_editor_property("filter", unreal.TextureFilter.__FILTER__)
print("GLASS_TEXTURE __NAME__ saved=" + str(unreal.EditorAssetLibrary.save_loaded_asset(tex, False)))
'''

MATERIAL = r'''
import unreal
mel = unreal.MaterialEditingLibrary
eal = unreal.EditorAssetLibrary
QUIET = unreal.PropertyAccessChangeNotifyMode.NEVER
m = unreal.load_asset("__MAT__")
if m is None:
    m = unreal.AssetToolsHelpers.get_asset_tools().create_asset("M_PP_SensorGlass", "/Game/SaskartaGaea/Look", unreal.Material, unreal.MaterialFactoryNew())
mel.delete_all_material_expressions(m)
m.set_editor_property("material_domain", unreal.MaterialDomain.MD_POST_PROCESS)
m.set_editor_property("blendable_location", unreal.BlendableLocation.BL_SCENE_COLOR_BEFORE_BLOOM)
def add(cls, x, y):
    return mel.create_material_expression(m, cls, x, y)
fails = []
def link(a, ao, b, bi):
    if not mel.connect_material_expressions(a, ao, b, bi):
        fails.append(bi)
c = add(unreal.MaterialExpressionCustom, 0, 0)
c.set_editor_property("description", "SensorGlass", QUIET)
c.set_editor_property("output_type", unreal.CustomMaterialOutputType.CMOT_FLOAT3, QUIET)
c.set_editor_property("code", __HLSL__, QUIET)
arr = []
for p in __PINS__:
    ci = unreal.CustomInput()
    ci.set_editor_property("input_name", p)
    arr.append(ci)
c.set_editor_property("inputs", arr, QUIET)
sp = add(unreal.MaterialExpressionScreenPosition, -1000, -480)
link(sp, "ViewportUV", c, "UV")
vs = add(unreal.MaterialExpressionViewSize, -1000, -400)
link(vs, "", c, "ViewSize")
link(add(unreal.MaterialExpressionTime, -1000, -320), "", c, "Time")
sc = add(unreal.MaterialExpressionSceneTexture, -1000, -240)
sc.set_editor_property("scene_texture_id", unreal.SceneTextureId.PPI_POST_PROCESS_INPUT0, QUIET)
link(sc, "Color", c, "SceneColorDummy")
am = add(unreal.MaterialExpressionScalarParameter, -1000, -160)
am.set_editor_property("parameter_name", "Amount")
am.set_editor_property("default_value", 0.6)
link(am, "", c, "Amount")
gp = add(unreal.MaterialExpressionScalarParameter, -1000, -80)
gp.set_editor_property("parameter_name", "GustPeriod")
gp.set_editor_property("default_value", __GUST__)
link(gp, "", c, "GustPeriod")
for y, pin, name in ((0, "Flash", "LightningFlash"), (80, "Storm", "StormIntensity")):
    e = add(unreal.MaterialExpressionCollectionParameter, -1000, y)
    e.set_editor_property("collection", unreal.load_asset("__MPC__"), QUIET)
    e.set_editor_property("parameter_name", name)
    link(e, "", c, pin)
sun = add(unreal.MaterialExpressionSkyAtmosphereLightDirection, -1000, 160)
tv = add(unreal.MaterialExpressionTransform, -800, 160)
tv.set_editor_property("transform_source_type", unreal.MaterialVectorCoordTransformSource.TRANSFORMSOURCE_WORLD)
tv.set_editor_property("transform_type", unreal.MaterialVectorCoordTransform.TRANSFORM_VIEW)
link(sun, "", tv, "")
link(tv, "", c, "SunDirV")
link(add(unreal.MaterialExpressionSkyAtmosphereLightIlluminance, -1000, 240), "", c, "SunLum")
dropuv = add(unreal.MaterialExpressionCustom, -600, 560)
dropuv.set_editor_property("output_type", unreal.CustomMaterialOutputType.CMOT_FLOAT2, QUIET)
dropuv.set_editor_property("code", "return float2(UV.x * ViewSize.x / ViewSize.y * 0.5, UV.y);", QUIET)
darr = []
for p in ("UV", "ViewSize"):
    ci = unreal.CustomInput()
    ci.set_editor_property("input_name", p)
    darr.append(ci)
dropuv.set_editor_property("inputs", darr, QUIET)
link(sp, "ViewportUV", dropuv, "UV")
link(vs, "", dropuv, "ViewSize")
for y, pin, name in ((340, "CrackN", "T_SensorGlass_CrackN"), (460, "FrostM", "T_SensorGlass_Frost"), (580, "DropQ", "T_SensorGlass_DropQ")):
    tex = unreal.load_asset("__DIR__/" + name)
    if tex is None:
        raise RuntimeError("import the glass maps before material: " + name)
    node = add(unreal.MaterialExpressionTextureSampleParameter2D, -300, y)
    node.set_editor_property("parameter_name", name)
    node.set_editor_property("texture", tex)
    node.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_COLOR)
    link(dropuv if pin == "DropQ" else sp, "" if pin == "DropQ" else "ViewportUV", node, "UVs")
    link(node, "RGBA", c, pin)
for y, name in ((700, "P0"), (800, "P1"), (900, "P2")):
    v = __PARAMS__[name]
    node = add(unreal.MaterialExpressionVectorParameter, -400, y)
    node.set_editor_property("parameter_name", name, QUIET)
    node.set_editor_property("default_value", unreal.LinearColor(v[0], v[1], v[2], v[3]), QUIET)
    link(node, "RGBA", c, name)
ok = mel.connect_material_property(c, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
errs = mel.recompile_material(m)
print("GLASS_MATERIAL fails=" + str(fails) + " emissive=" + str(ok) + " errors=" + str(errs))
if fails or not ok or errs:
    raise RuntimeError("glass material wiring or compile failed")
print("GLASS_MATERIAL saved=" + str(eal.save_loaded_asset(m, False)))
'''

MI_SCRIPT = r'''
import unreal
mel = unreal.MaterialEditingLibrary
mat = unreal.load_asset("__MAT__")
mi = unreal.load_asset("__MI__")
if mi is None:
    mi = unreal.AssetToolsHelpers.get_asset_tools().create_asset("MI_PP_SensorGlass", "/Game/SaskartaGaea/Look", unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
mel.set_material_instance_parent(mi, mat)
mel.set_material_instance_scalar_parameter_value(mi, "Amount", 0.6)
for name, values in __PARAMS__.items():
    mel.set_material_instance_vector_parameter_value(mi, name, unreal.LinearColor(*values))
mel.update_material_instance(mi)
print("GLASS_MI saved=" + str(unreal.EditorAssetLibrary.save_loaded_asset(mi, False)))
'''

LEGACY = r'''
import unreal
mel = unreal.MaterialEditingLibrary
mi = unreal.load_asset("__CRT__")
flat = unreal.load_asset("__DIR__/T_SensorGlass_FlatN")
zero = unreal.load_asset("__DIR__/T_SensorGlass_Zero")
if mi is None or flat is None or zero is None:
    raise RuntimeError("CRT and neutral glass maps must exist")
for name in ("T_SensorRim_N", "T_SensorScratches_N"):
    mel.set_material_instance_texture_parameter_value(mi, name, flat)
for name in ("T_SensorRim_Mask", "T_SensorGrime", "T_SensorDeadPixels"):
    mel.set_material_instance_texture_parameter_value(mi, name, zero)
mel.update_material_instance(mi)
print("GLASS_LEGACY saved=" + str(unreal.EditorAssetLibrary.save_loaded_asset(mi, False)))
'''

PLACE = r'''
import unreal
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
mi = unreal.load_asset("__MI__")
v = None
for a in eas.get_all_level_actors():
    if a.get_actor_label() == "__PPV__":
        v = a
if v is None or mi is None:
    raise RuntimeError("sensor PPV or glass MI missing")
s = v.get_editor_property("settings")
wb = s.get_editor_property("weighted_blendables")
arr = list(wb.get_editor_property("array"))
if not any(b.object and "MI_PP_SensorCRT" in b.object.get_name() for b in arr):
    raise RuntimeError("sensor CRT blendable missing; preserving it is required")
arr = [b for b in arr if not (b.object and "SensorGlass" in b.object.get_name())]
for b in arr:
    if b.object and "MI_PP_SensorCRT" in b.object.get_name():
        b.weight = 0.0
arr.append(unreal.WeightedBlendable(weight=0.0, object=mi))
wb.set_editor_property("array", arr)
s.set_editor_property("weighted_blendables", wb)
v.set_editor_property("settings", s)
v.set_editor_property("enabled", True)
print("GLASS_PLACE package=" + v.get_package().get_name() + " blendables=" + str([(b.weight, b.object.get_name()) for b in arr]))
'''

SAVE = r'''
import unreal
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
pk = [a.get_package() for a in eas.get_all_level_actors() if a.get_actor_label() == "__PPV__"]
print("GLASS_SAVE packages=" + str([p.get_name() for p in pk]))
if pk:
    print("GLASS_SAVE saved=" + str(unreal.EditorLoadingAndSavingUtils.save_packages(pk, True)))
'''

READBACK = r'''
import unreal
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
for a in eas.get_all_level_actors():
    if a.get_actor_label() == "__PPV__":
        arr = a.get_editor_property("settings").get_editor_property("weighted_blendables").get_editor_property("array")
        print("GLASS_READBACK " + str([(b.weight, b.object.get_name()) for b in arr]))
'''


def fill(template, **values):
    for name, value in values.items():
        template = template.replace("__" + name + "__", str(value))
    return check_banned(template)


def script(step):
    if step.startswith("import-"):
        key = step.split("-", 1)[1]
        name, source, wrap = MAPS[key]
        return fill(IMPORT, SOURCE=repr(str(SRC / source)), DIR=TEXDIR, NAME=name,
                    ADDR="TA_WRAP" if wrap else "TA_CLAMP", FILTER="TF_NEAREST" if wrap else "TF_BILINEAR")
    if step == "material":
        return fill(MATERIAL, HLSL=repr(HLSL.read_text(encoding="utf-8")), PINS=repr(PINS),
                    PARAMS=repr(PARAMS), MAT=MAT, DIR=TEXDIR, MPC=MPC, GUST=DEFAULTS["GustPeriod"])
    if step == "mi":
        return fill(MI_SCRIPT, MAT=MAT, MI=MI, PARAMS=repr(PARAMS))
    if step == "legacy":
        return fill(LEGACY, CRT=CRT, DIR=TEXDIR)
    if step == "place":
        return fill(PLACE, MI=MI, PPV=PPV)
    if step == "save":
        return fill(SAVE, PPV=PPV)
    if step == "readback":
        return fill(READBACK, PPV=PPV)
    raise ValueError(step)


def check():
    missing = [str(SRC / source) for _, source, _ in MAPS.values() if not (SRC / source).is_file()]
    if missing:
        raise SystemExit("bake the glass maps first: " + ", ".join(missing))
    code = HLSL.read_text(encoding="utf-8")
    absent = [p for p in PINS if p not in code]
    if absent:
        raise SystemExit("HLSL pins missing: " + str(absent))
    for step in [*("import-" + key for key in MAPS), "material", "mi", "legacy", "place", "save", "readback"]:
        print(step, len(script(step)), "chars ok")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("step", choices=["check", *("import-" + key for key in MAPS), "material", "mi", "legacy", "place", "save", "readback"])
    a = ap.parse_args()
    if a.step == "check":
        return check()
    ok, out, err = python_run(script(a.step))
    print(out.rstrip())
    if not ok or err:
        print("python_run failed:", err, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
