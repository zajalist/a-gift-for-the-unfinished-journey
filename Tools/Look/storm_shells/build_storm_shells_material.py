"""Build the storm shells (task STORM-SHELLS): moving storm dust on 4 virtual cylinders around the camera,
one post-process pass.

    python Tools/Look/storm_shells/build_storm_shells_material.py check      # offline: HLSL pins, banned words
    python Tools/Look/storm_shells/build_storm_shells_material.py noise2d    # import the generated RGBA atlas
    python Tools/Look/storm_shells/build_storm_shells_material.py noise3d    # build the mipmapped volume texture
    python Tools/Look/storm_shells/build_storm_shells_material.py material   # M_PP_Saskarta_StormShells (saves it)
    python Tools/Look/storm_shells/build_storm_shells_material.py instance   # MI_PP_Saskarta_StormShells (saves it)
    python Tools/Look/storm_shells/build_storm_shells_material.py place      # PPV_Saskarta_StormShells in the open level (NOT saved)
    python Tools/Look/storm_shells/build_storm_shells_material.py save       # save only that PPV's package (a separate call)
    python Tools/Look/storm_shells/build_storm_shells_material.py verify     # read back the material, MI and PPV
    python Tools/Look/storm_shells/build_storm_shells_material.py set NAME X Y Z W   # an MI vector parameter (saves the MI)
    python Tools/Look/storm_shells/build_storm_shells_material.py toggle on|off      # editor A/B for captures (NOT saved)

User (2026-09-28): "Im not saying actual meshed cylinders im saying its a curved plane around the player as if
a cylinder with a decal projected on its internal faces and it follows the player position". The recipe
(docs/look/STORM_SHELLS.md) does exactly that without a mesh: the shells are analytic, the dust is a 3D field
fixed in the world and moved by the wind, sampled where the view ray crosses each shell.

- Shaders/StormShells.ush is the source of truth for the Custom node; this script inlines it (there is no
  shader directory mapping in this project; SensorCRT.hlsl and DustVolume.hlsl are inlined the same way).
- shells_model.PARAMS holds every parameter default; the preview (preview_storm_shells.py) uses the same.
- Blendable location Scene Color After DOF: it runs before TSR, bloom, the tonemapper and the sensor CRT
  (PPV_Saskarta_Sensor, After Tonemapping), so the sensor's glass sits on top of the dust.
- Its own unbound PPV, not spatially loaded, tagged Saskarta_StormShells. USaskartaStormShellsSubsystem
  (SaskartaCore) swaps the MI for a dynamic instance, writes the Tier from the saskarta.stormshells.* cvars
  and sets the volume's BlendWeight to 0 when MPC_Saskarta_Sky.StormIntensity is ~0, so the pass is skipped.

Editor calls go through Hayba python_run (5 s each, banned words checked). Wrap a session in
Tools/GameFlow/editor_gate.py acquire/release; python_run refuses while PIE runs. Place and save are separate
calls (memory: WP scripted load/save/unload). Check IsReadOnly on a committed .uasset before re-saving it.
"""
import argparse
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
LOOK = HERE.parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(LOOK))
sys.path.insert(0, str(HERE))
from apply_look import check_banned, python_run  # noqa: E402
from shells_model import PARAMS  # noqa: E402
from storm_dust_noise import ATLAS, NX, NY, NZ  # noqa: E402

FOLDER = "/Game/SaskartaGaea/Look/Storm"
MAT_NAME = "M_PP_Saskarta_StormShells"
MI_NAME = "MI_PP_Saskarta_StormShells"
MAT = f"{FOLDER}/{MAT_NAME}"
MI = f"{FOLDER}/{MI_NAME}"
MPC = "/Game/SaskartaGaea/Look/MPC_Saskarta_Sky.MPC_Saskarta_Sky"
NOISE_2D = f"{FOLDER}/T_Saskarta_StormDust_Atlas"
NOISE = f"{FOLDER}/VT_Saskarta_StormDust"
PPV = "PPV_Saskarta_StormShells"
PPV_TAG = "Saskarta_StormShells"
PPV_PRIORITY = 40.0   # below the sensor PPV (50); volume priority only orders settings overrides, not the passes
MAP_CENTER_CM = (389000.0, 408000.0, 0.0)  # where the unbound volume sits (its position does not matter)
HLSL_FILE = ROOT / "Shaders" / "StormShells.ush"
# Custom node pins, in order (Shaders/StormShells.ush header). Vector parameters come from PARAMS.
PINS = ["Scene", "Depth", "V", "Fwd", "Cam", "Time", "Vol", "Radii", "Edges", "Speed", "Band", "Wind", "Gust",
        "Shape", "Dens", "Tone", "Tint", "Wisp", "Haze", "HazeDir", "FogA", "FogB", "SunDir", "Storm", "Tier"]
VECTOR_PINS = list(PARAMS)
COLOR_PINS = []

NOISE_2D_SCRIPT = r'''
import unreal
task = unreal.AssetImportTask()
task.set_editor_property("filename", __ATLAS__)
task.set_editor_property("destination_path", "__FOLDER__")
task.set_editor_property("destination_name", "T_Saskarta_StormDust_Atlas")
task.set_editor_property("automated", True)
task.set_editor_property("replace_existing", True)
task.set_editor_property("save", False)
unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
tex = unreal.load_asset("__NOISE2D__")
if tex is None:
    raise RuntimeError("storm dust atlas import failed")
tex.set_editor_property("srgb", False)
tex.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_VECTOR_DISPLACEMENTMAP)
tex.set_editor_property("mip_gen_settings", unreal.TextureMipGenSettings.TMGS_NO_MIPMAPS)
print("NOISE2D imported=" + str(tex.get_name()) + " saved=" + str(unreal.EditorAssetLibrary.save_loaded_asset(tex, False)))
'''

NOISE_3D_SCRIPT = r'''
import unreal
atlas = unreal.load_asset("__NOISE2D__")
if atlas is None:
    raise RuntimeError("import the storm dust atlas first")
vol = unreal.load_asset("__NOISE__")
if vol is None:
    factory = unreal.VolumeTextureFactory()
    vol = unreal.AssetToolsHelpers.get_asset_tools().create_asset("VT_Saskarta_StormDust", "__FOLDER__", unreal.VolumeTexture, factory)
if vol is None:
    raise RuntimeError("storm dust volume creation failed")
vol.set_editor_property("srgb", False)
vol.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_VECTOR_DISPLACEMENTMAP)
vol.set_editor_property("mip_gen_settings", unreal.TextureMipGenSettings.TMGS_FROM_TEXTURE_GROUP)
vol.set_editor_property("filter", unreal.TextureFilter.TF_TRILINEAR)
vol.set_editor_property("address_mode", unreal.TextureAddress.TA_WRAP)
vol.set_editor_property("source2d_texture", atlas)
vol.set_editor_property("source2d_tile_size_x", __NX__)
vol.set_editor_property("source2d_tile_size_y", __NY__)
print("NOISE3D tiles=" + str((vol.get_editor_property("source2d_tile_size_x"), vol.get_editor_property("source2d_tile_size_y"))) + " atlas=" + str(vol.get_editor_property("source2d_texture").get_name()) + " saved=" + str(unreal.EditorAssetLibrary.save_loaded_asset(vol, False)))
'''

MATERIAL = r'''
import unreal
mel = unreal.MaterialEditingLibrary
eal = unreal.EditorAssetLibrary
QUIET = unreal.PropertyAccessChangeNotifyMode.NEVER
HLSL = __HLSL__
PARAMS = __PARAMS__
if not eal.does_directory_exist("__FOLDER__"):
    eal.make_directory("__FOLDER__")
m = unreal.load_asset("__MAT__")
if m is None:
    m = unreal.AssetToolsHelpers.get_asset_tools().create_asset("__MATNAME__", "__FOLDER__", unreal.Material, unreal.MaterialFactoryNew())
mel.delete_all_material_expressions(m)
m.set_editor_property("material_domain", unreal.MaterialDomain.MD_POST_PROCESS)
m.set_editor_property("blendable_location", unreal.BlendableLocation.BL_SCENE_COLOR_AFTER_DOF)
def add(cls, x, y):
    return mel.create_material_expression(m, cls, x, y)
fails = []
def link(a, ao, b, bi):
    if not mel.connect_material_expressions(a, ao, b, bi):
        fails.append(bi)
c = add(unreal.MaterialExpressionCustom, 0, 0)
c.set_editor_property("description", "StormShells", QUIET)
c.set_editor_property("output_type", unreal.CustomMaterialOutputType.CMOT_FLOAT4, QUIET)
c.set_editor_property("code", HLSL, QUIET)
arr = []
for p in __PINS__:
    ci = unreal.CustomInput()
    ci.set_editor_property("input_name", p)
    arr.append(ci)
c.set_editor_property("inputs", arr, QUIET)
s0 = add(unreal.MaterialExpressionSceneTexture, -900, -600)
s0.set_editor_property("scene_texture_id", unreal.SceneTextureId.PPI_POST_PROCESS_INPUT0, QUIET)
link(s0, "Color", c, "Scene")
sd = add(unreal.MaterialExpressionSceneTexture, -900, -520)
sd.set_editor_property("scene_texture_id", unreal.SceneTextureId.PPI_SCENE_DEPTH, QUIET)
link(sd, "Color", c, "Depth")
link(add(unreal.MaterialExpressionCameraVectorWS, -900, -440), "", c, "V")
f3 = add(unreal.MaterialExpressionConstant3Vector, -1100, -380)
f3.set_editor_property("constant", unreal.LinearColor(0.0, 0.0, 1.0, 1.0), QUIET)
fw = add(unreal.MaterialExpressionTransform, -900, -380)
fw.set_editor_property("transform_source_type", unreal.MaterialVectorCoordTransformSource.TRANSFORMSOURCE_VIEW)
fw.set_editor_property("transform_type", unreal.MaterialVectorCoordTransform.TRANSFORM_WORLD)
link(f3, "", fw, "")
link(fw, "", c, "Fwd")
link(add(unreal.MaterialExpressionCameraPositionWS, -900, -320), "", c, "Cam")
link(add(unreal.MaterialExpressionTime, -900, -260), "", c, "Time")
vol = add(unreal.MaterialExpressionTextureObject, -900, -200)
volume_texture = unreal.load_asset("__NOISE__")
if volume_texture is None:
    raise RuntimeError("import VT_Saskarta_StormDust before building the material")
vol.set_editor_property("texture", volume_texture, QUIET)
vol.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_COLOR, QUIET)
link(vol, "", c, "Vol")
y = -100
for n in __VECTORS__ + __COLORS__:
    v = PARAMS[n]
    e = add(unreal.MaterialExpressionVectorParameter, -900, y)
    e.set_editor_property("parameter_name", n, QUIET)
    e.set_editor_property("default_value", unreal.LinearColor(v[0], v[1], v[2], v[3]), QUIET)
    e.set_editor_property("group", "StormShells", QUIET)
    if n in __COLORS__:
        link(e, "RGB", c, n)
    else:
        link(e, "RGBA", c, n)
    y += 80
link(add(unreal.MaterialExpressionSkyAtmosphereLightDirection, -900, y), "", c, "SunDir")
st = add(unreal.MaterialExpressionCollectionParameter, -900, y + 80)
st.set_editor_property("collection", unreal.load_asset("__MPC__"), QUIET)
st.set_editor_property("parameter_name", "StormIntensity")
link(st, "", c, "Storm")
rgb = add(unreal.MaterialExpressionComponentMask, 220, 0)
rgb.set_editor_property("r", True, QUIET)
rgb.set_editor_property("g", True, QUIET)
rgb.set_editor_property("b", True, QUIET)
rgb.set_editor_property("a", False, QUIET)
link(c, "", rgb, "")
ok = mel.connect_material_property(rgb, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
errs = mel.recompile_material(m)
print("MAT nodes=" + str(mel.get_num_material_expressions(m)) + " fails=" + str(fails) + " emissive=" + str(ok) + " errors=" + str(len(errs)) + " " + " | ".join([str(e) for e in errs]))
print("MAT saved=" + str(eal.save_loaded_asset(m, False)))
'''

INSTANCE = r'''
import unreal
mel = unreal.MaterialEditingLibrary
eal = unreal.EditorAssetLibrary
m = unreal.load_asset("__MAT__")
mi = unreal.load_asset("__MI__")
if mi is None:
    mi = unreal.AssetToolsHelpers.get_asset_tools().create_asset("__MINAME__", "__FOLDER__", unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
mel.set_material_instance_parent(mi, m)
mel.update_material_instance(mi)
print("MI parent=" + str(mi.get_editor_property("parent").get_name()) + " saved=" + str(eal.save_loaded_asset(mi, False)))
'''

PLACE = r'''
import unreal
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
v = None
for a in eas.get_all_level_actors():
    if a.get_actor_label() == "__PPV__":
        v = a
if v is None:
    v = eas.spawn_actor_from_class(unreal.PostProcessVolume, unreal.Vector(__LOC__[0], __LOC__[1], __LOC__[2]))
    v.set_actor_label("__PPV__")
# spatial loading first: an unbound volume refuses to change the flag (PostProcessVolume.h CanChangeIsSpatiallyLoadedFlag)
v.set_editor_property("is_spatially_loaded", False)
v.set_editor_property("unbound", True)
v.set_editor_property("priority", __PRIO__)
v.set_editor_property("blend_weight", 1.0)
v.set_editor_property("enabled", True)
v.set_editor_property("tags", [unreal.Name("__TAG__")])
v.set_folder_path("Post Process")
s = v.get_editor_property("settings")
wb = s.get_editor_property("weighted_blendables")
wb.set_editor_property("array", [unreal.WeightedBlendable(weight=1.0, object=unreal.load_asset("__MI__"))])
s.set_editor_property("weighted_blendables", wb)
v.set_editor_property("settings", s)
print("PPV " + v.get_actor_label() + " package=" + str(v.get_package().get_name()))
'''

SAVE = r'''
import unreal
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
pk = [a.get_package() for a in eas.get_all_level_actors() if a.get_actor_label() == "__PPV__"]
print("packages " + str([p.get_name() for p in pk]))
if pk:
    print("saved " + str(unreal.EditorLoadingAndSavingUtils.save_packages(pk, True)))
'''

VERIFY = r'''
import unreal
m = unreal.load_asset("__MAT__")
mi = unreal.load_asset("__MI__")
print("MAT " + str(m is not None) + (" domain=" + str(m.get_editor_property("material_domain")) + " loc=" + str(m.get_editor_property("blendable_location")) + " nodes=" + str(unreal.MaterialEditingLibrary.get_num_material_expressions(m)) if m else ""))
print("MI " + str(mi is not None) + (" parent=" + str(mi.get_editor_property("parent").get_name()) if mi else ""))
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
for a in eas.get_all_level_actors():
    if a.get_actor_label() == "__PPV__":
        s = a.get_editor_property("settings")
        arr = s.get_editor_property("weighted_blendables").get_editor_property("array")
        print("PPV unbound=" + str(a.get_editor_property("unbound")) + " weight=" + str(a.get_editor_property("blend_weight")) + " spatial=" + str(a.get_editor_property("is_spatially_loaded")) + " tags=" + str([str(t) for t in a.tags]) + " blendables=" + str([(str(b.weight), b.object.get_name() if b.object else "None") for b in arr]))
'''

SET = r'''
import unreal
mel = unreal.MaterialEditingLibrary
mi = unreal.load_asset("__MI__")
ok = mel.set_material_instance_vector_parameter_value(mi, "__PNAME__", unreal.LinearColor(__X__, __Y__, __Z__, __W__))
mel.update_material_instance(mi)
print("SET __PNAME__=" + str(ok) + " now=" + str(mel.get_material_instance_vector_parameter_value(mi, "__PNAME__")) + " saved=" + str(unreal.EditorAssetLibrary.save_loaded_asset(mi, False)))
'''

# Editor A/B for look captures: the subsystem only runs in game worlds, so the editor viewport and
# capture_look.py's SceneCapture2D see the PPV as saved. This flips its enabled flag in memory only.
TOGGLE = r'''
import unreal
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
n = 0
for a in eas.get_all_level_actors():
    if a.get_actor_label() == "__PPV__":
        a.set_editor_property("enabled", __ON__)
        n += 1
print("TOGGLE __PPV__ enabled=__ON__ actors=" + str(n))
'''


def fill(t, **kw):
    for k, v in kw.items():
        t = t.replace(f"__{k}__", str(v))
    return check_banned(t)


def hlsl():
    return HLSL_FILE.read_text(encoding="utf-8")


def script(step, values=()):
    if step == "noise2d":
        return fill(NOISE_2D_SCRIPT, ATLAS=repr(str(ATLAS)), FOLDER=FOLDER, NOISE2D=NOISE_2D)
    if step == "noise3d":
        return fill(NOISE_3D_SCRIPT, FOLDER=FOLDER, NOISE2D=NOISE_2D, NOISE=NOISE, NX=NX, NY=NY)
    if step == "material":
        return fill(MATERIAL, HLSL=repr(hlsl()), PARAMS=repr(PARAMS), PINS=repr(PINS), VECTORS=repr(VECTOR_PINS),
                    COLORS=repr(COLOR_PINS), FOLDER=FOLDER, MAT=MAT, MATNAME=MAT_NAME, NOISE=NOISE, MPC=MPC)
    if step == "instance":
        return fill(INSTANCE, MAT=MAT, MI=MI, MINAME=MI_NAME, FOLDER=FOLDER)
    if step == "place":
        return fill(PLACE, PPV=PPV, TAG=PPV_TAG, PRIO=PPV_PRIORITY, LOC=repr(MAP_CENTER_CM), MI=MI)
    if step == "save":
        return fill(SAVE, PPV=PPV)
    if step == "verify":
        return fill(VERIFY, MAT=MAT, MI=MI, PPV=PPV)
    if step == "toggle":
        if list(values) not in (["on"], ["off"]):
            raise SystemExit("toggle on|off")
        return fill(TOGGLE, PPV=PPV, ON=values[0] == "on")
    if step == "set":
        name, x, y, z, w = values
        if name not in PARAMS:
            raise SystemExit(f"unknown parameter {name}; one of {sorted(PARAMS)}")
        return fill(SET, MI=MI, PNAME=name, X=float(x), Y=float(y), Z=float(z), W=float(w))
    raise SystemExit(step)


def check():
    """Offline: every pin is used by the HLSL, the header lists them in order, every script is python_run-safe."""
    code = hlsl()
    header = code.split("float4 inC =", 1)[0]
    pos = [header.find(f"//   {p} ") for p in PINS]
    missing = [p for p, i in zip(PINS, pos) if i < 0]
    if missing:
        raise SystemExit(f"StormShells.ush header does not document pins {missing}")
    if pos != sorted(pos):
        raise SystemExit("StormShells.ush header lists the pins in a different order than PINS")
    body = code[len(header):]
    unused = [p for p in PINS if p not in body]
    if unused:
        raise SystemExit(f"pins not used in the HLSL body: {unused}")
    for n in VECTOR_PINS + COLOR_PINS:
        if len(PARAMS[n]) != 4:
            raise SystemExit(f"PARAMS[{n}] must have 4 components")
    if (NX, NY, NZ) != (32, 64, 64):
        raise SystemExit("storm dust volume dimensions differ from the shader recipe")
    if not ATLAS.is_file():
        raise SystemExit(f"missing storm dust atlas: run storm_dust_noise.py first ({ATLAS})")
    for s in ("noise2d", "noise3d", "material", "instance", "place", "save", "verify"):
        print(s, len(script(s)), "chars ok")
    print("set", len(script("set", ("Dens", 0.0055, 0.2, 2, 0.35))), "chars ok")
    print("toggle", len(script("toggle", ("off",))), "chars ok")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("step", choices=["check", "noise2d", "noise3d", "material", "instance", "place", "save", "verify", "set", "toggle"])
    ap.add_argument("values", nargs="*")
    a = ap.parse_args(argv)
    if a.step == "check":
        return check()
    ok, out, err = python_run(script(a.step, a.values))
    print(out.rstrip())
    if not ok or err:
        print("python_run failed:", err, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
