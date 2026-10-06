"""Build the animated dust storm of task STORM: a moving volumetric dust volume, dust devils and sand streams.

    python Tools/Look/build_storm_fx.py check          # offline: HLSL present, editor scripts pass the banned-word check
    python Tools/Look/build_storm_fx.py volume         # create/rebuild M_Saskarta_DustVolume (saves it)
    python Tools/Look/build_storm_fx.py place          # spawn/update StormDust_Volume in Saskarta_WP (not saved)
    python Tools/Look/build_storm_fx.py save           # save only the volume's and the devils' external packages
    python Tools/Look/build_storm_fx.py set NAME R G B A   # set a vector parameter default on the volume material
    python Tools/Look/build_storm_fx.py devil / streams    # rebuild M_Saskarta_DustDevil / M_Saskarta_SandStreams (saves each)
    python Tools/Look/build_storm_fx.py devils-load        # FOG3B: load the placed devils' WP actors (a separate call)
    python Tools/Look/build_storm_fx.py devils             # spawn/update the devils at DEVIL_SPOTS (not saved)
    python Tools/Look/build_storm_fx.py devils-unload      # FOG3B: after `save`, unload and unpin them (a separate call)
    python Tools/Look/build_storm_fx.py check-devils       # FOG3B, offline: each devil spot's ground height, slope, road gap
    python Tools/Look/build_storm_fx.py remove-sheets  # FOG2: delete the curtain ring and the basin dust wall
    python Tools/Look/build_storm_fx.py save-removed PKG...  # FOG2: save the deleted actors' packages (a separate call)

Why this shape (user, 2026-09-27: "the distance fog also needs more animation (dust storm like) and more
intensity"):
- M_Saskarta_DustVolume (Volume domain, additive) on SM cube `StormDust_Volume`, a box over the whole map
  from 600 m below to 1,000 m above the valley floor. The volumetric fog voxelizes it into its froxel grid
  out to VOLUMETRIC_FOG_DISTANCE_CM (apply_look.py, 120 m since FOG2), so the near dust churns:
  domain-warped 3D noise (the engine's VT_PerlinWorley_Balanced) at ~400 m billows and ~60 m wisps,
  advected downwind, rolling density bands, gust pulses, and a near-ground layer that follows the camera.
  It is scaled by MPC_Saskarta_Sky.StormIntensity, so the look keys drive it along the road.
  Shaders/DustVolume.hlsl is the source of truth.
- FOG2 (user, 2026-09-28: "remove this plane thing that's supposed to be a storm, it looks fake"): the far
  storm-front ring (StormDust_Curtain) and the basin dust wall sheet (StormDust_Wall_Basin) are gone; a
  storm is thick air around the player, not a picture of one in the sky. Their materials and HLSL remain
  on disk, unused.
The volume is not spatially loaded, so it exists wherever the player is. No Blueprint, no Tick.

Editor calls go through Hayba python_run (5 s, banned words checked). Wrap them in
Tools/GameFlow/editor_gate.py acquire/release, and check that PIE is not running before each.
"""
import argparse
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
from apply_look import python_run, check_banned  # noqa: E402

FOLDER = "/Game/SaskartaGaea/Look/Storm"
VOLUME_MAT = "M_Saskarta_DustVolume"
MPC = "/Game/SaskartaGaea/Look/MPC_Saskarta_Sky.MPC_Saskarta_Sky"
NOISE = "/Engine/EngineSky/VolumetricClouds/VT_PerlinWorley_Balanced.VT_PerlinWorley_Balanced"
VOLUME_ACTOR = "StormDust_Volume"
# FOG2 (user: "remove this plane thing that's supposed to be a storm, it looks fake"): the storm-front ring
# (StormDust_Curtain, M_Saskarta_DustCurtain) and the basin dust wall (StormDust_Wall_Basin, M_Saskarta_DustWall)
# read as flat cards hung in the sky. They are removed from the level ("remove-sheets") and no longer built
# here; the close height fog and the volumetric dust carry the storm (look_keys.json, LOOK.md "FOG2").
REMOVED_ACTORS = ["StormDust_Curtain", "StormDust_Wall_Basin"]
# The Saskarta_WP landscape spans about -19,000..797,000 cm in X and 0..816,000 cm in Y; the valley floor (fog actor) is at -42,000 cm.
MAP_CENTER_CM = (389000.0, 408000.0)
FLOOR_Z_CM = -42000.0

VOLUME_PARAMS = {
    # xy wind direction (toward +X, a little +Y), z billow speed m/s, w wisp speed m/s
    "Wind": (1.0, 0.35, 10.0, 18.0),  # LANE4 "more intense": faster drift (was 8, 14)
    # x extinction 1/m at the valley floor, y floor world Z cm, z height halving m, w scale
    # FOG3 (user: "close to the player, but not dense"): 0.0012 halving 70 m -> 0.0006 halving 25 m, the analytic
    # ground dust's own values (look_keys.json second layer: ~0.0006 1/m in the lows, halving 25 m)
    # FOG3B: the analytic dust now halves every 14.3 m (apply_look.SECOND_FOG_FALLOFF 0.7), so the volume's does too
    "Shape": (0.0006, FLOOR_Z_CM, 14.3, 1.0),  # LANE4: 0.0015 -> 0.0012, the near layer below carries the close dust  # user 2026-09-27: "the fog is too intense i cant see anything"; motion, not density
    # x wall spacing m, y wall speed m/s, z wall contrast
    # FOG3B: contrast 0.6 -> 0.75, the gust fronts read as arriving bands (the storm shells' Gust.w, the streams' Gust.y speed)
    "Walls": (1500.0, 35.0, 0.75, 0.0),
    # x gust amplitude (+-25 %), y period s
    # z/w (LANE4): the dust bubble around the carrier, extinction 1/m at the camera and its radius m
    # FOG2: bubble 0.003 -> 0.005 over 40 m (the fog's volumetric start keeps the near 20 m clear, so this is dust at 20-60 m)
    # FOG3: bubble 0.005 over 40 m -> 0.0015 over 30 m (with Near below, ~10 % over the first 50 m at StormIntensity 0.8)
    # FOG3B (playtest: "not enough dust effect and storm visible"): +-35 % -> +-50 %, the same amplitude as the sand
    # streams' gust depth and the storm shells' Wind.w proposal (docs/look/STORM_SHELLS.md), so all three gust together
    "Gust": (0.5, 7.0, 0.0015, 30.0),  # LANE4 "more intense": +-35 % over ~7 s (was 0.25, 8)
    # LANE4 near-ground layer (user: "fog make it closer to the player"): x extinction 1/m at the ground
    # around the camera, y camera eye height m (the ground = camera Z - y), z halving height m, w wind speed x
    # FOG2 ("very intense fog / dust storm"): 0.0012 -> 0.004 1/m, halving 25 -> 35 m; about half the height fog's
    # extinction at the road in Act I, so the churn and the gust pulses read inside the near 120 m
    # FOG3: 0.004 1/m halving 35 m -> 0.0015 halving 20 m, a veil, not a wall
    "Near": (0.0015, 1.2, 20.0, 1.4),
    # dust albedo (ochre)
    "DustAlbedo": (0.62, 0.45, 0.30, 1.0),
    # self-glow per unit extinction: the lit dust's radiance when it is optically thick. The volumetric
    # fog's own sun/sky scattering alone left dense dust near black at this exposure, so the dust carries
    # the height fog's inscattering colour (#7E5434 x 0.2 luminance, linear), at 0.75 of it, as emissive.
    # LANE4: 0.032/0.014/0.005 left the volumetric dust reading as dark smoke in the valley's terrain
    # shadow (horizon 57/27/9 with it vs 139/103/61 without); the lit-haze radiance of the analytic fog
    # (#84502E x 0.22) is about 3x this, so the dust glows at that level
    "DustGlow": (0.09, 0.042, 0.018, 1.0),
}
# LANE4 dust devils: x height m, y top radius m, z spin rad/s, w strength
# FOG3B (playtest: "not enough dust effect and storm visible"): taller and wider (45 x 14 -> 55 x 17 m), a faster spin
# (1.6 -> 1.9 rad/s) and strength 1.35; the material now scales the opacity by the look keys' storm (DustDevil.hlsl
# stormK, 0.7x in Act I, 1x from the ridge on), so Act I's devils read about as before (1.35 x 0.71 = 0.96) and the
# storm stretch's are a third stronger. Placed with the Devil size below (the placement reads it).
DEVIL_PARAMS = {
    "Devil": (55.0, 17.0, 1.9, 1.35),
    "DevilColor": (0.2, 0.12, 0.06, 1.0),    # near the lit dust haze at this exposure; the first pass (0.34, 0.2, 0.1) glowed
}
DEVIL_MAT = "M_Saskarta_DustDevil"
# LANE4 ground sand streams (deferred decals along the road)
# FOG3B (playtest: "not enough dust effect and storm visible"): longer streaks (9 -> 11 m), more coverage (0.5 -> 0.6, plus
# 0.25 x the storm), strength 1.0 -> 1.25 and a fade-out at 70 m (was 50), so there is more, and more opaque, sand
# streaming around the carrier: about twice the mean opacity at every key, and the basin's streaks reach full opacity
# in a gust. The gust (SandStreams.hlsl, pin Gust): depth 0.75 (the lull keeps 25 %, a gust peak is 1.75x, was
# 0.1-1.0 clipped), travelling downwind at 35 m/s like the dust volume's walls and the storm shells' fronts, in step
# with them at the camera. Storm is now a pin (the storm scale moved into the node), so the storm also widens the
# streaming patches (Gust.w 0.1).
STREAM_PARAMS = {
    "Wind": (1.0, 0.35, 9.0, 7.0),          # the dust volume's wind direction; speed m/s; gust period s
    "Stream": (11.0, 0.6, 1.25, 70.0),      # streak length m, coverage, strength, fade-out distance m
    "Gust": (0.75, 35.0, 0.25, 0.1),        # gust depth, gust front speed m/s, storm coverage boost, storm patch boost
    "StreamColor": (0.46, 0.33, 0.2, 1.0),   # a dry ochre dust (base colour)
}
STREAM_MAT = "M_Saskarta_SandStreams"
STREAM_STEP_M = 55.0                          # one 70 x 70 m decal box every 55 m of road
STREAM_RANGES = [(0.0, 3300.0)]               # the valley, ridge, basin and cistern
# (road m, side m): open ground beside the road, the valley and the basin (Tools/Story/build_road_profile roads)
# FOG3B: 7 more in the storm stretch (the Ridge key at 1,500 m to the cistern at 2,950 m), 75-90 m off the road instead of
# 120-180, alternating sides, each on ground within 11 m of the road's height with a slope under 0.25 over 15 m (checked on
# the Gaea heightmap: `build_storm_fx.py check-devils`). The storm stretch goes from 4 devils to 11.
DEVIL_SPOTS = [(350, 140), (700, -180), (1250, 160), (1800, -130), (2200, 150), (2450, -170), (2650, 120), (3900, -150),
               (1550, 90), (1650, -90), (2150, -75), (2350, -90), (2550, 90), (2750, -75), (2900, 90)]
STORM_REF = 0.8  # StormIntensity of the Valley key: the effects are authored at this level

COMMON = r'''
import unreal
mel = unreal.MaterialEditingLibrary
eal = unreal.EditorAssetLibrary
QUIET = unreal.PropertyAccessChangeNotifyMode.NEVER
FOLDER = "__FOLDER__"
NAME = "__NAME__"
PATH = FOLDER + "/" + NAME
HLSL = __HLSL__
PARAMS = __PARAMS__
if eal.does_asset_exist(PATH):
    mat = eal.load_asset(PATH)
else:
    if not eal.does_directory_exist(FOLDER):
        eal.make_directory(FOLDER)
    mat = unreal.AssetToolsHelpers.get_asset_tools().create_asset(NAME, FOLDER, unreal.Material, unreal.MaterialFactoryNew())
for old in mel.get_material_expressions(mat):
    mel.delete_material_expression(mat, old)
def add(cls, x, y):
    return mel.create_material_expression(mat, cls, x, y)
def vparam(name, x, y):
    v = PARAMS[name]
    n = add(unreal.MaterialExpressionVectorParameter, x, y)
    n.set_editor_property("parameter_name", name, QUIET)
    n.set_editor_property("default_value", unreal.LinearColor(v[0], v[1], v[2], v[3]), QUIET)
    n.set_editor_property("group", "Storm", QUIET)
    return n
def custom(pins, out_type):
    c = add(unreal.MaterialExpressionCustom, -400, 0)
    c.set_editor_property("description", NAME, QUIET)
    c.set_editor_property("output_type", out_type, QUIET)
    c.set_editor_property("code", HLSL, QUIET)
    arr = []
    for p in pins:
        ci = unreal.CustomInput()
        ci.set_editor_property("input_name", p)
        arr.append(ci)
    c.set_editor_property("inputs", arr, QUIET)
    return c
fails = []
def link(a, ao, b, bi):
    if not mel.connect_material_expressions(a, ao, b, bi):
        fails.append(bi)
wp = add(unreal.MaterialExpressionWorldPosition, -900, -300)
tm = add(unreal.MaterialExpressionTime, -900, -220)
vol = add(unreal.MaterialExpressionTextureObject, -900, -140)
vol.set_editor_property("texture", unreal.load_asset("__NOISE__"), QUIET)
vol.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_COLOR, QUIET)
storm = add(unreal.MaterialExpressionCollectionParameter, -900, 300)
storm.set_editor_property("collection", unreal.load_asset("__MPC__"), QUIET)
# set with the default notify mode: the node's PostEditChangeProperty looks the parameter id up by name
# (never construct an unreal.Guid in python_run: it faults the editor)
storm.set_editor_property("parameter_name", "StormIntensity")
stormk = add(unreal.MaterialExpressionMultiply, -700, 300)
stormk.set_editor_property("const_b", 1.0 / __STORM_REF__, QUIET)
link(storm, "", stormk, "A")
'''

VOLUME = COMMON + r'''
mat.set_editor_property("material_domain", unreal.MaterialDomain.MD_VOLUME)
mat.set_editor_property("blend_mode", unreal.BlendMode.BLEND_ADDITIVE)
c = custom(["WP", "Time", "Vol", "Wind", "Shape", "Walls", "Gust", "Cam", "Near", "Storm"], unreal.CustomMaterialOutputType.CMOT_FLOAT1)
link(stormk, "", c, "Storm")
link(add(unreal.MaterialExpressionCameraPositionWS, -900, 380), "", c, "Cam")
link(wp, "", c, "WP")
link(tm, "", c, "Time")
link(vol, "", c, "Vol")
y = -40
for n in ["Wind", "Shape", "Walls", "Gust", "Near"]:
    link(vparam(n, -900, y), "RGBA", c, n)
    y += 80
ext = add(unreal.MaterialExpressionMultiply, -150, 0)
link(c, "", ext, "A")
ext.set_editor_property("const_b", 1.0, QUIET)
alb = vparam("DustAlbedo", -400, -250)
ok_e = mel.connect_material_property(ext, "", unreal.MaterialProperty.MP_SUBSURFACE_COLOR)
glow = add(unreal.MaterialExpressionMultiply, -150, 150)
link(ext, "", glow, "A")
link(vparam("DustGlow", -400, 200), "RGB", glow, "B")
ok_g = mel.connect_material_property(glow, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
ok_a = mel.connect_material_property(alb, "RGB", unreal.MaterialProperty.MP_BASE_COLOR)
errs = mel.recompile_material(mat)
print("VOL nodes=" + str(mel.get_num_material_expressions(mat)) + " fails=" + str(fails) + " ext=" + str(ok_e) + " alb=" + str(ok_a) + " glow=" + str(ok_g) + " errors=" + str(len(errs)) + " " + " | ".join([str(e) for e in errs]))
print("VOL saved=" + str(eal.save_loaded_asset(mat, False)))
'''

DEVIL = COMMON + r'''
mat.set_editor_property("material_domain", unreal.MaterialDomain.MD_SURFACE)
mat.set_editor_property("blend_mode", unreal.BlendMode.BLEND_TRANSLUCENT)
mat.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_UNLIT)
mat.set_editor_property("two_sided", True)
obj = add(unreal.MaterialExpressionObjectPositionWS, -900, 460)
nrm = add(unreal.MaterialExpressionVertexNormalWS, -900, 380)
c = custom(["WP", "Obj", "Time", "Vol", "P", "N", "V", "Storm"], unreal.CustomMaterialOutputType.CMOT_FLOAT1)
link(add(unreal.MaterialExpressionCameraVectorWS, -900, 540), "", c, "V")
link(stormk, "", c, "Storm")
link(wp, "", c, "WP")
link(obj, "", c, "Obj")
link(tm, "", c, "Time")
link(vol, "", c, "Vol")
link(vparam("Devil", -900, 60), "RGBA", c, "P")
link(nrm, "", c, "N")
df = add(unreal.MaterialExpressionDepthFade, 50, 0)
df.set_editor_property("fade_distance_default", 400.0, QUIET)
link(c, "", df, "Opacity")
col = vparam("DevilColor", -400, -250)
ok_o = mel.connect_material_property(df, "", unreal.MaterialProperty.MP_OPACITY)
ok_c = mel.connect_material_property(col, "RGB", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
errs = mel.recompile_material(mat)
print("DEV nodes=" + str(mel.get_num_material_expressions(mat)) + " fails=" + str(fails) + " op=" + str(ok_o) + " col=" + str(ok_c) + " errors=" + str(len(errs)) + " " + " | ".join([str(e) for e in errs]))
print("DEV saved=" + str(eal.save_loaded_asset(mat, False)))
'''

STREAMS = COMMON + r'''
mat.set_editor_property("material_domain", unreal.MaterialDomain.MD_DEFERRED_DECAL)
mat.set_editor_property("blend_mode", unreal.BlendMode.BLEND_TRANSLUCENT)
cam = add(unreal.MaterialExpressionCameraPositionWS, -900, 460)
c = custom(["WP", "Cam", "Time", "Vol", "Wind", "P", "Gust", "Storm"], unreal.CustomMaterialOutputType.CMOT_FLOAT1)
link(wp, "", c, "WP")
link(cam, "", c, "Cam")
link(tm, "", c, "Time")
link(vol, "", c, "Vol")
link(vparam("Wind", -900, 60), "RGBA", c, "Wind")
link(vparam("Stream", -900, 140), "RGBA", c, "P")
link(vparam("Gust", -900, 220), "RGBA", c, "Gust")
link(stormk, "", c, "Storm")
col = vparam("StreamColor", -400, -250)
ok_o = mel.connect_material_property(c, "", unreal.MaterialProperty.MP_OPACITY)
ok_c = mel.connect_material_property(col, "RGB", unreal.MaterialProperty.MP_BASE_COLOR)
rgh = add(unreal.MaterialExpressionConstant, -150, 200)
rgh.set_editor_property("r", 0.95, QUIET)
mel.connect_material_property(rgh, "", unreal.MaterialProperty.MP_ROUGHNESS)
errs = mel.recompile_material(mat)
print("STR nodes=" + str(mel.get_num_material_expressions(mat)) + " fails=" + str(fails) + " op=" + str(ok_o) + " col=" + str(ok_c) + " errors=" + str(len(errs)) + " " + " | ".join([str(e) for e in errs]))
print("STR saved=" + str(eal.save_loaded_asset(mat, False)))
'''

PLACE_STREAMS = r'''
import unreal
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
SPOTS = __SPOTS__
MAT = unreal.load_asset("__MAT__")
have = {}
for a in eas.get_all_level_actors():
    if a.get_actor_label().startswith("StormDust_Streams_"):
        have[a.get_actor_label()] = a
FIRST = __FIRST__
n = 0
for i in range(len(SPOTS)):
    x, y, z = SPOTS[i]
    label = "StormDust_Streams_" + str(FIRST + i)
    a = have.get(label)
    if a is None:
        a = eas.spawn_actor_from_class(unreal.DecalActor, unreal.Vector(x, y, z))
        a.set_actor_label(label)
    a.set_actor_location(unreal.Vector(x, y, z), False, False)
    a.set_actor_rotation(unreal.Rotator(roll=0.0, pitch=-90.0, yaw=0.0), False)
    a.set_folder_path("Sky & Light/Storm/Streams")
    d = a.decal
    d.set_decal_material(MAT)
    d.set_editor_property("decal_size", unreal.Vector(1500.0, 3500.0, 3500.0))
    d.set_editor_property("fade_screen_size", 0.0)
    n += 1
print("STREAMS " + str(n))
'''

# FOG3B: the devils are spatially loaded, so a devil in an unloaded cell is not among the level's actors; spawning it
# again by label would duplicate it. So a label that exists as a World Partition actor desc but is not loaded is
# skipped (and reported); run devils-load first so every existing devil is updated.
PLACE_DEVILS = r'''
import unreal
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
SPOTS = __SPOTS__
MAT = unreal.load_asset("__MAT__")
cone = unreal.load_asset("/Engine/BasicShapes/Cone.Cone")
lib = unreal.WorldPartitionBlueprintLibrary
got = lib.get_intersecting_actor_descs(lib.get_editor_world_bounds())
descs = got[1] if isinstance(got, tuple) else got
known = [str(d.get_editor_property("label")) for d in descs]
have = {}
for a in eas.get_all_level_actors():
    if a.get_actor_label().startswith("StormDust_Devil_"):
        have[a.get_actor_label()] = a
out = []
skipped = []
for i in range(len(SPOTS)):
    x, y, z, h, r = SPOTS[i]
    label = "StormDust_Devil_" + str(i)
    a = have.get(label)
    if a is None and label in known:
        skipped.append(label)
        continue
    if a is None:
        a = eas.spawn_actor_from_object(cone, unreal.Vector(x, y, z))
        a.set_actor_label(label)
    a.set_actor_location(unreal.Vector(x, y, z + h * 50.0), False, False)
    a.set_actor_rotation(unreal.Rotator(roll=180.0, pitch=0.0, yaw=0.0), False)
    a.set_actor_scale3d(unreal.Vector(r * 2.0, r * 2.0, h))
    a.set_folder_path("Sky & Light/Storm")
    c = a.static_mesh_component
    c.set_material(0, MAT)
    c.set_collision_profile_name("NoCollision")
    a.set_actor_enable_collision(False)
    c.set_editor_property("cast_shadow", False)
    c.set_editor_property("visible_in_ray_tracing", False)
    c.set_editor_property("affect_distance_field_lighting", False)
    c.set_editor_property("ld_max_draw_distance", 250000.0)
    out.append(label)
print("DEVILS " + str(len(out)) + " skipped (placed but not loaded: run devils-load) " + str(skipped))
'''

DEVILS_LOAD = r'''
import unreal
lib = unreal.WorldPartitionBlueprintLibrary
got = lib.get_intersecting_actor_descs(lib.get_editor_world_bounds())
descs = got[1] if isinstance(got, tuple) else got
gs = [d.get_editor_property("guid") for d in descs if str(d.get_editor_property("label")).startswith("StormDust_Devil_")]
if gs:
    lib.__OP__(gs)
__UNPIN__
print("DEVILS __OP__ " + str(len(gs)))
'''

PLACE = r'''
import unreal
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
SPEC = __SPEC__
have = {}
for a in eas.get_all_level_actors():
    if a.get_actor_label() in SPEC:
        have[a.get_actor_label()] = a
for label in SPEC:
    s = SPEC[label]
    a = have.get(label)
    loc = unreal.Vector(s["loc"][0], s["loc"][1], s["loc"][2])
    if a is None:
        a = eas.spawn_actor_from_object(unreal.load_asset(s["mesh"]), loc)
        a.set_actor_label(label)
    a.set_actor_location(loc, False, False)
    a.set_actor_scale3d(unreal.Vector(s["scale"][0], s["scale"][1], s["scale"][2]))
    a.set_editor_property("is_spatially_loaded", False)
    a.set_folder_path("Sky & Light/Storm")
    c = a.static_mesh_component
    c.set_material(0, unreal.load_asset(s["mat"]))
    c.set_editor_property("cast_shadow", False)
    # The collision PROFILE, not set_collision_enabled: the setter did not persist and the saved actors
    # kept BlockAll, so the 10 km dust box blocked every trace and pushed the carrier out under the map
    # (user's PIE, 2026-09-27). Actor collision off as well.
    c.set_collision_profile_name("NoCollision")
    c.set_editor_property("generate_overlap_events", False)
    a.set_actor_enable_collision(False)
    c.set_editor_property("bounds_scale", s["bounds"])
    c.set_editor_property("affect_distance_field_lighting", False)
    c.set_editor_property("visible_in_ray_tracing", False)
    c.set_editor_property("affect_dynamic_indirect_lighting", False)
    print(label + " at " + str(a.get_actor_location()) + " mesh " + str(c.static_mesh.get_name()) + " mat " + str(c.get_material(0).get_name()))
'''

SAVE = r'''
import unreal
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
pk = []
for a in eas.get_all_level_actors():
    if a.get_actor_label() in __LABELS__:
        pk.append(a.get_package())
print("packages " + str([p.get_name() for p in pk]))
print("saved " + str(unreal.EditorLoadingAndSavingUtils.save_packages(pk, True)))
'''

REMOVE = r'''
import unreal
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
gone = []
for a in eas.get_all_level_actors():
    if a.get_actor_label() in __LABELS__:
        pk = a.get_package().get_name()
        eas.destroy_actor(a)
        gone.append(pk)
print("REMOVED " + str(gone))
'''

# The deleted external-actor packages are saved in a second call (FOG2: WP edit and save apart). A deleted
# package is no longer found by name; it is still in the editor's dirty map packages, so match it there and
# save only those (never the other lanes' dirty packages).
SAVE_REMOVED = r'''
import unreal
L = unreal.EditorLoadingAndSavingUtils
W = __PKGS__
d = list(L.get_dirty_map_packages()) + list(L.get_dirty_content_packages())
pk = [p for p in d if p.get_name() in W]
print("packages " + str([p.get_name() for p in pk]))
if pk:
    print("saved " + str(L.save_packages(pk, True)))
'''

SET = r'''
import unreal
mel = unreal.MaterialEditingLibrary
eal = unreal.EditorAssetLibrary
done = []
for path in __PATHS__:
    mat = eal.load_asset(path)
    for n in mel.get_material_expressions(mat):
        if isinstance(n, unreal.MaterialExpressionVectorParameter) and str(n.get_editor_property("parameter_name")) == "__PNAME__":
            n.set_editor_property("default_value", unreal.LinearColor(__R__, __G__, __B__, __A__))
            mel.recompile_material(mat)
            done.append(mat.get_name() + " saved=" + str(eal.save_loaded_asset(mat, False)))
print("SET __PNAME__: " + str(done))
'''


def _fill(t, **kw):
    for k, v in kw.items():
        t = t.replace(f"__{k}__", str(v))
    return check_banned(t)


def material_script(which):
    name, hlsl_file, params, body = {
        "volume": (VOLUME_MAT, "DustVolume.hlsl", VOLUME_PARAMS, VOLUME),
        "devil": (DEVIL_MAT, "DustDevil.hlsl", DEVIL_PARAMS, DEVIL),
        "streams": (STREAM_MAT, "SandStreams.hlsl", STREAM_PARAMS, STREAMS),
    }[which]
    hlsl = (ROOT / "Shaders" / hlsl_file).read_text(encoding="utf-8")
    return _fill(body, FOLDER=FOLDER, NAME=name, HLSL=repr(hlsl), PARAMS=repr(params), NOISE=NOISE,
                 MPC=MPC, STORM_REF=STORM_REF)


def devils_script(spots):
    return _fill(PLACE_DEVILS, SPOTS=repr(spots), MAT=f"{FOLDER}/{DEVIL_MAT}.{DEVIL_MAT}")


def devils_load_script(load):
    return _fill(DEVILS_LOAD, OP="load_actors" if load else "unload_actors",
                 UNPIN="" if load else "if gs:" + chr(10) + "    lib.unpin_actors(gs)")


def devil_spot_report():
    """FOG3B, offline: for each DEVIL_SPOTS entry, (ground height minus the road's at that metre m, the steepest rise
    over a 15 m ring / 15, the nearest road polyline point m) on the Gaea heightmap."""
    import numpy as np
    sys.path.insert(0, str(ROOT / "Tools" / "Story"))
    from build_road_profile import SPLINE_POINTS_CM, Road, Terrain, HEIGHTMAP
    road, ter = Road(SPLINE_POINTS_CM), Terrain(HEIGHTMAP)
    out = []
    for m, side in DEVIL_SPOTS:
        p, q = road.xy(m), road.xy(m + 20.0)
        dx, dy = q[0] - p[0], q[1] - p[1]
        n = (dx * dx + dy * dy) ** 0.5 or 1.0
        x, y = p[0] - dy / n * side * 100.0, p[1] + dx / n * side * 100.0
        z = float(ter.height(x, y))
        ang = np.radians(np.arange(0.0, 360.0, 30.0))
        slope = float(np.max(np.abs(ter.height(x + np.cos(ang) * 1500.0, y + np.sin(ang) * 1500.0) - z))) / 15.0
        pts = np.array([road.xy(k) for k in np.arange(max(0.0, m - 400.0), m + 400.0, 5.0)])
        gap = float(np.min(np.hypot(pts[:, 0] - x, pts[:, 1] - y))) / 100.0
        out.append((z - float(ter.height(p[0], p[1])), slope, gap))
    return out


def place_script():
    spec = {
        VOLUME_ACTOR: {"mesh": "/Engine/BasicShapes/Cube.Cube", "mat": f"{FOLDER}/{VOLUME_MAT}.{VOLUME_MAT}",
                       # 10 km square, from 600 m below to 1,000 m above the valley floor (cube is 100 cm)
                       "loc": (MAP_CENTER_CM[0], MAP_CENTER_CM[1], FLOOR_Z_CM + 20000.0),
                       "scale": (10000.0, 10000.0, 1600.0), "bounds": 1.0},
    }
    return _fill(PLACE, SPEC=repr(spec))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("step", choices=["check", "volume", "devil", "devils", "streams", "place-streams", "place", "save", "set",
                                     "remove-sheets", "save-removed", "devils-load", "devils-unload", "check-devils"])
    ap.add_argument("values", nargs="*")
    a = ap.parse_args(argv)
    if a.step == "check":
        for s in (material_script("volume"), material_script("devil"), material_script("streams"), place_script(),
                  _fill(REMOVE, LABELS=repr(REMOVED_ACTORS)), devils_script([(0.0, 0.0, 0.0, 1.0, 1.0)]),
                  devils_load_script(True), devils_load_script(False)):
            print(len(s), "chars ok")
        return 0
    if a.step == "check-devils":
        for (m, side), (dz, slope, gap) in zip(DEVIL_SPOTS, devil_spot_report()):
            print(f"road {m:5.0f} m side {side:+5.0f} m: ground {dz:+6.1f} m vs the road, slope {slope:.2f}, nearest road {gap:4.0f} m")
        return 0
    if a.step in ("devils-load", "devils-unload"):
        ok, out, err = python_run(devils_load_script(a.step == "devils-load"))
        print(out.strip(), err if not ok else "")
        return 0 if ok else 1
    if a.step == "devils":
        sys.path.insert(0, str(ROOT / "Tools" / "Story"))
        from build_road_profile import SPLINE_POINTS_CM, Road, Terrain, HEIGHTMAP
        road, ter = Road(SPLINE_POINTS_CM), Terrain(HEIGHTMAP)
        spots = []
        for m, side in DEVIL_SPOTS:
            p, q = road.xy(m), road.xy(m + 20.0)
            dx, dy = q[0] - p[0], q[1] - p[1]
            n = (dx * dx + dy * dy) ** 0.5 or 1.0
            x, y = p[0] - dy / n * side * 100.0, p[1] + dx / n * side * 100.0
            spots.append((round(float(x), 1), round(float(y), 1), round(float(ter.height(x, y)) * 100.0, 1), DEVIL_PARAMS["Devil"][0], DEVIL_PARAMS["Devil"][1]))
        script = devils_script(spots)
        ok, out, err = python_run(script)
        print(out.strip(), err if not ok else "")
        return 0 if ok else 1
    if a.step == "place-streams":
        sys.path.insert(0, str(ROOT / "Tools" / "Story"))
        from build_road_profile import SPLINE_POINTS_CM, Road, Terrain, HEIGHTMAP
        import math as _m
        road, ter = Road(SPLINE_POINTS_CM), Terrain(HEIGHTMAP)
        spots = []
        for lo, hi in STREAM_RANGES:
            m = lo
            while m <= hi:
                p = road.xy(m)
                spots.append((round(float(p[0]), 1), round(float(p[1]), 1), round(float(ter.height(p[0], p[1])) * 100.0 + 200.0, 1)))
                m += STREAM_STEP_M
        for i in range(0, len(spots), 20):
            print(python_run(_fill(PLACE_STREAMS, SPOTS=repr(spots[i:i + 20]), FIRST=i, MAT=f"{FOLDER}/{STREAM_MAT}.{STREAM_MAT}"))[1].strip())
        return 0
    if a.step in ("volume", "devil", "streams"):
        script = material_script(a.step)
    elif a.step == "place":
        script = place_script()
    elif a.step == "save":
        script = _fill(SAVE, LABELS=repr([VOLUME_ACTOR] + [f"StormDust_Devil_{i}" for i in range(len(DEVIL_SPOTS))]))
    elif a.step == "remove-sheets":
        script = _fill(REMOVE, LABELS=repr(REMOVED_ACTORS))
    elif a.step == "save-removed":
        script = _fill(SAVE_REMOVED, PKGS=repr(a.values))
    else:
        name, r, g, b, al = a.values
        script = _fill(SET, PATHS=repr([f"{FOLDER}/{VOLUME_MAT}"]), PNAME=name,
                       R=float(r), G=float(g), B=float(b), A=float(al))
    ok, out, err = python_run(script)
    print(out.rstrip())
    if not ok or err:
        print("python_run failed:", err, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
