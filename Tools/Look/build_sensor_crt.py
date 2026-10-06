"""The carrier's camera sensor look (LANE4, 2026-09-28): an always-on, subtle CRT filter with a damaged glass.

    python Tools/Look/build_sensor_crt.py import     # the damage textures -> /Game/SaskartaGaea/UI/SensorDamage
    python Tools/Look/build_sensor_crt.py material   # M_PP_SensorCRT (+ MI_PP_SensorCRT), saves both
    python Tools/Look/build_sensor_crt.py place      # PPV_Saskarta_Sensor (unbound, the MI as blendable), saves it
    python Tools/Look/build_sensor_crt.py check      # offline: script sizes and banned words

User words: "keep an image-level post-process to make it look more CRT when you look around the world";
"the HUD must have normals effect that make it look like the sides of the camera screen are a tiny bit
broken"; "those cracks ... need to be normals so you see them behave weirdly with light"; "they shouldn't
be big circle cracks".

Shaders/SensorCRT.hlsl is the source of truth (scanlines, barrel, chromatic aberration, phosphor mask,
grain, flicker, gust roll, lightning interference, the broken rim lit from the scene, the storm on the glass,
dark dead pixels, vignette). One post-process material, blendable location Scene Color After Tonemapping,
one full-screen pass.

FOG2 (2026-09-28): the broken rim (T_SensorRim_N: per-shard facet normals and bevelled cracks, DirectX;
T_SensorRim_Mask: r crack lines, g dark frame and chips, b shard id, a region; from
Tools/UI/make_sensor_damage.py) and the storm layers (grit along the wind, settled dust, static and tearing,
radioactive speckle) driven by MPC_Saskarta_Sky.StormIntensity, which the lighting director sets per look key.

Wiring for the game (not this lane's assets):
- The Sensor filter setting (Off/Low/Medium/High) sets MI_PP_SensorCRT's Amount (0 / 0.35 / 0.6 / 0.85)
  through a dynamic instance on PPV_Saskarta_Sensor, or the volume's blend weight. Default Medium.
- PC_Saskarta should set the volume's BlendWeight to 0 while the title, menus and cards show, 1 in play.
"""
import argparse
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
from apply_look import check_banned, python_run  # noqa: E402

TEX_DIR = "/Game/SaskartaGaea/UI/SensorDamage"
SRC_DIR = (ROOT / "Saved" / "UI" / "SensorDamage").as_posix()
MAT = "/Game/SaskartaGaea/Look/M_PP_SensorCRT"
MI = "/Game/SaskartaGaea/Look/MI_PP_SensorCRT"
MPC = "/Game/SaskartaGaea/Look/MPC_Saskarta_Sky.MPC_Saskarta_Sky"
PPV = "PPV_Saskarta_Sensor"
GUST_PERIOD = 7.0  # Tools/Look/build_storm_fx.py VOLUME_PARAMS Gust.y
TEXTURES = {  # name: normal map?
    "T_SensorScratches_N": True, "T_SensorGrime": False, "T_SensorDeadPixels": False,
    # FOG2 broken rim (replaces T_SensorCrack_N / _Mask / _Region, which stay on disk unused)
    "T_SensorRim_N": True, "T_SensorRim_Mask": False,
}
RIM_MASK_UNCOMPRESSED = ("T_SensorRim_Mask",)  # RGBA8, so BC blocks do not smear the frame edge and shard ids
WIND_DIR = (1.0, 0.35, 0.0)  # Tools/Look/build_storm_fx.py VOLUME_PARAMS Wind.xy (the dust wind, world)

IMPORT = r'''
import unreal
at = unreal.AssetToolsHelpers.get_asset_tools()
tasks = []
for n in __NAMES__:
    t = unreal.AssetImportTask()
    t.set_editor_property('filename', '__SRC__/' + n + '_1024.png')
    t.set_editor_property('destination_path', '__DIR__')
    t.set_editor_property('destination_name', n)
    t.set_editor_property('replace_existing', True)
    t.set_editor_property('automated', True)
    t.set_editor_property('save', False)
    tasks.append(t)
at.import_asset_tasks(tasks)
NORMAL = __NORMAL__
out = []
for n in __NAMES__:
    tex = unreal.load_asset('__DIR__/' + n)
    if n in NORMAL:
        tex.set_editor_property('compression_settings', unreal.TextureCompressionSettings.TC_NORMALMAP)
        tex.set_editor_property('srgb', False)
        tex.set_editor_property('flip_green_channel', False)
    elif n in __RAW__:
        tex.set_editor_property('compression_settings', unreal.TextureCompressionSettings.TC_VECTOR_DISPLACEMENTMAP)
        tex.set_editor_property('srgb', False)
    elif n.endswith('_Mask') or n.endswith('_Region'):
        tex.set_editor_property('compression_settings', unreal.TextureCompressionSettings.TC_GRAYSCALE)
        tex.set_editor_property('srgb', False)
    tex.set_editor_property('lod_group', unreal.TextureGroup.TEXTUREGROUP_UI)
    tex.set_editor_property('never_stream', True)
    tex.set_editor_property('mip_gen_settings', unreal.TextureMipGenSettings.TMGS_NO_MIPMAPS)
    tex.set_editor_property('address_x', unreal.TextureAddress.TA_CLAMP)
    tex.set_editor_property('address_y', unreal.TextureAddress.TA_CLAMP)
    out.append(n + '=' + str(unreal.EditorAssetLibrary.save_loaded_asset(tex, False)))
print('IMPORTED ' + ' '.join(out))
'''

MATERIAL = r'''
import unreal
mel = unreal.MaterialEditingLibrary
eal = unreal.EditorAssetLibrary
at = unreal.AssetToolsHelpers.get_asset_tools()
QUIET = unreal.PropertyAccessChangeNotifyMode.NEVER
HLSL = __HLSL__
missing = [n for n in __NAMES__ if not eal.does_asset_exist('__TEXDIR__/' + n)]
if missing:
    raise RuntimeError('Import the CRT textures before rebuilding: ' + str(missing))
m = unreal.load_asset('__MAT__')
if m is None:
    m = at.create_asset('M_PP_SensorCRT', '/Game/SaskartaGaea/Look', unreal.Material, unreal.MaterialFactoryNew())
mel.delete_all_material_expressions(m)
m.set_editor_property('material_domain', unreal.MaterialDomain.MD_POST_PROCESS)
m.set_editor_property('blendable_location', unreal.BlendableLocation.BL_SCENE_COLOR_AFTER_TONEMAPPING)
def add(cls, x, y):
    return mel.create_material_expression(m, cls, x, y)
fails = []
def link(a, ao, b, bi):
    if not mel.connect_material_expressions(a, ao, b, bi):
        fails.append(bi)
pins = ['UV', 'ViewSize', 'Time', 'SceneColorDummy', 'Amount', 'GustPeriod', 'Flash', 'RimN', 'RimMask',
        'ScratchN', 'Grime', 'Dead', 'SunDirV', 'SunLum', 'Storm', 'WindV', 'Headlight', 'SunRef']
c = add(unreal.MaterialExpressionCustom, 0, 0)
c.set_editor_property('description', 'SensorCRT', QUIET)
c.set_editor_property('output_type', unreal.CustomMaterialOutputType.CMOT_FLOAT3, QUIET)
c.set_editor_property('code', HLSL, QUIET)
arr = []
for p in pins:
    ci = unreal.CustomInput()
    ci.set_editor_property('input_name', p)
    arr.append(ci)
c.set_editor_property('inputs', arr, QUIET)
sp = add(unreal.MaterialExpressionScreenPosition, -900, -400)
link(sp, 'ViewportUV', c, 'UV')
link(add(unreal.MaterialExpressionViewSize, -900, -330), '', c, 'ViewSize')
link(add(unreal.MaterialExpressionTime, -900, -260), '', c, 'Time')
st = add(unreal.MaterialExpressionSceneTexture, -900, -190)
st.set_editor_property('scene_texture_id', unreal.SceneTextureId.PPI_POST_PROCESS_INPUT0, QUIET)
link(st, 'Color', c, 'SceneColorDummy')
am = add(unreal.MaterialExpressionScalarParameter, -900, -120)
am.set_editor_property('parameter_name', 'Amount')
am.set_editor_property('default_value', 0.6)
link(am, '', c, 'Amount')
gp = add(unreal.MaterialExpressionScalarParameter, -900, -50)
gp.set_editor_property('parameter_name', 'GustPeriod')
gp.set_editor_property('default_value', __GUST__)
link(gp, '', c, 'GustPeriod')
for y, name, value in [(-760, 'Headlight', 1.0), (-680, 'SunRef', 1.5)]:
    p = add(unreal.MaterialExpressionScalarParameter, -900, y)
    p.set_editor_property('parameter_name', name)
    p.set_editor_property('default_value', value)
    link(p, '', c, name)
fl = add(unreal.MaterialExpressionCollectionParameter, -900, 20)
fl.set_editor_property('collection', unreal.load_asset('__MPC__'), QUIET)
fl.set_editor_property('parameter_name', 'LightningFlash')
link(fl, '', c, 'Flash')
stp = add(unreal.MaterialExpressionCollectionParameter, -900, 60)
stp.set_editor_property('collection', unreal.load_asset('__MPC__'), QUIET)
stp.set_editor_property('parameter_name', 'StormIntensity')
link(stp, '', c, 'Storm')
y = 100
for n, pin, out, normal in [('T_SensorRim_N', 'RimN', 'RGB', True), ('T_SensorRim_Mask', 'RimMask', 'RGBA', False),
                            ('T_SensorScratches_N', 'ScratchN', 'RGB', True),
                            ('T_SensorGrime', 'Grime', 'RGBA', False), ('T_SensorDeadPixels', 'Dead', 'RGBA', False)]:
    t = add(unreal.MaterialExpressionTextureSampleParameter2D, -600, y)
    t.set_editor_property('parameter_name', n)
    tex = unreal.load_asset('__TEXDIR__/' + n)
    t.set_editor_property('texture', tex)
    if normal:
        t.set_editor_property('sampler_type', unreal.MaterialSamplerType.SAMPLERTYPE_NORMAL)
    elif n in __RAW__:
        t.set_editor_property('sampler_type', unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_COLOR)
    elif n.endswith('_Mask') or n.endswith('_Region'):
        t.set_editor_property('sampler_type', unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_GRAYSCALE)
    link(sp, 'ViewportUV', t, 'UVs')
    link(t, out, c, pin)
    y += 120
sd = add(unreal.MaterialExpressionSkyAtmosphereLightDirection, -900, 900)
tv = add(unreal.MaterialExpressionTransform, -700, 900)
tv.set_editor_property('transform_source_type', unreal.MaterialVectorCoordTransformSource.TRANSFORMSOURCE_WORLD)
tv.set_editor_property('transform_type', unreal.MaterialVectorCoordTransform.TRANSFORM_VIEW)
link(sd, '', tv, '')
link(tv, '', c, 'SunDirV')
link(add(unreal.MaterialExpressionSkyAtmosphereLightIlluminance, -900, 1000), '', c, 'SunLum')
wv = add(unreal.MaterialExpressionConstant3Vector, -900, 1100)
wv.set_editor_property('constant', unreal.LinearColor(__WIND__[0], __WIND__[1], __WIND__[2], 1.0), QUIET)
wt = add(unreal.MaterialExpressionTransform, -700, 1100)
wt.set_editor_property('transform_source_type', unreal.MaterialVectorCoordTransformSource.TRANSFORMSOURCE_WORLD)
wt.set_editor_property('transform_type', unreal.MaterialVectorCoordTransform.TRANSFORM_VIEW)
link(wv, '', wt, '')
link(wt, '', c, 'WindV')
ok = mel.connect_material_property(c, '', unreal.MaterialProperty.MP_EMISSIVE_COLOR)
errs = mel.recompile_material(m)
print('MAT fails=' + str(fails) + ' emissive=' + str(ok) + ' errors=' + str(errs))
if fails or not ok or errs:
    raise RuntimeError('CRT material wiring or compile failed')
print('MAT saved=' + str(eal.save_loaded_asset(m, False)))
mi = unreal.load_asset('__MI__')
if mi is None:
    mi = at.create_asset('MI_PP_SensorCRT', '/Game/SaskartaGaea/Look', unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
mel.set_material_instance_parent(mi, m)
mel.set_material_instance_scalar_parameter_value(mi, 'Amount', 0.6)
mel.update_material_instance(mi)
print('MI saved=' + str(eal.save_loaded_asset(mi, False)))
'''

PLACE = r'''
import unreal
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
v = None
for a in eas.get_all_level_actors():
    if a.get_actor_label() == '__PPV__':
        v = a
if v is None:
    v = eas.spawn_actor_from_class(unreal.PostProcessVolume, unreal.Vector(389000.0, 408000.0, 0.0))
    v.set_actor_label('__PPV__')
v.set_editor_property('unbound', True)
v.set_editor_property('priority', 50.0)
v.set_editor_property('blend_weight', 1.0)
v.set_editor_property('is_spatially_loaded', False)
v.set_folder_path('Post Process')
s = v.get_editor_property('settings')
wb = s.get_editor_property('weighted_blendables')
arr = [unreal.WeightedBlendable(weight=1.0, object=unreal.load_asset('__MI__'))]
wb.set_editor_property('array', arr)
s.set_editor_property('weighted_blendables', wb)
v.set_editor_property('settings', s)
print('PPV ' + v.get_actor_label() + ' saved=' + str(unreal.EditorLoadingAndSavingUtils.save_packages([v.get_package()], True)))
'''


def fill(t, **kw):
    for k, v in kw.items():
        t = t.replace(f"__{k}__", str(v))
    return check_banned(t)


def script(step):
    if step == "import":
        return fill(IMPORT, NAMES=repr(list(TEXTURES)), NORMAL=repr([n for n, v in TEXTURES.items() if v]),
                    RAW=repr(list(RIM_MASK_UNCOMPRESSED)), SRC=SRC_DIR, DIR=TEX_DIR)
    if step == "material":
        hlsl = (ROOT / "Shaders" / "SensorCRT.hlsl").read_text(encoding="utf-8")
        return fill(MATERIAL, HLSL=repr(hlsl), MAT=MAT, MI=MI, MPC=MPC, TEXDIR=TEX_DIR, GUST=GUST_PERIOD,
                    NAMES=repr(list(TEXTURES)), RAW=repr(list(RIM_MASK_UNCOMPRESSED)), WIND=repr(WIND_DIR))
    if step == "place":
        return fill(PLACE, PPV=PPV, MI=MI)
    raise SystemExit(step)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("step", choices=["import", "material", "place", "check"])
    a = ap.parse_args(argv)
    if a.step == "check":
        for s in ("import", "material", "place"):
            print(s, len(script(s)), "chars ok")
        return 0
    ok, out, err = python_run(script(a.step))
    print(out.strip())
    if not ok:
        print("failed:", err, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
