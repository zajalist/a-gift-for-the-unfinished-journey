"""Build the loading Keeper's capture stage and install its Niagara point replacement.

    python Tools/Look/build_keeper_pointcloud.py material   # M_Saskarta_PointCloudSkin + MI_UI_KeeperPointCloud (+ the RT)
    python Tools/Look/build_keeper_pointcloud.py stage      # the offstage traveller + its SceneCapture2D (saves both actors)
    python Tools/Look/build_keeper_pointcloud.py points     # after Niagara authoring/build, replace capture contents with real points
    python Tools/Look/build_keeper_pointcloud.py check      # offline: script sizes and banned words

User (CHAR brief): "maybe for the loading screen it can be a point cloud kinda animation of the main character?".
The original material step makes a masked-surface placeholder. The later points step requires a separately
authored two-emitter NS_LoadingKeeperPoints and replaces the capture contents with true, discrete sprites.
- Stage: KeeperPointCloud_Traveller + KeeperPointCloud_Capture, 2 km under the map centre, not spatially loaded,
  the capture showing only the traveller (show-only list, black background, most show flags off) into
  RT_Saskarta_LoadingTraveller (512 x 512, scene colour HDR).
- MI_UI_KeeperPointCloud: a UI material (additive-looking: opacity from the RT's brightness) for an Image on
  WBP_Saskarta_Loading's TravellerPointCloud slot. The loading widget's owner binds it, and turns the capture off
  (KeeperPointCloud_Capture's CaptureComponent2D bCaptureEveryFrame false) once loading ends, so it costs
  nothing in play.
"""
import argparse
import ast
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from apply_look import check_banned, python_run  # noqa: E402

DIR = "/Game/SaskartaGaea/Characters/Traveller/PointCloud"
MAT = "M_Saskarta_PointCloudSkin"
UI_MAT = "M_UI_KeeperPointCloud"
RT = "RT_Saskarta_LoadingTraveller"
STAGE = (389000.0, 408000.0, -250000.0)   # 2 km under the map centre

HLSL = r"""// PointCloudSkin: opacity mask and emissive of the Keeper point cloud (LANE4).
// Inputs: WP (absolute world position, cm), Obj (object position, cm), Time (s), P (x cell cm, y dot radius 0..0.5, z keep 0..1, w drift cm/s).
float3 p = (WP - Obj) / P.x;
p.z -= Time * P.w / P.x;
float3 cell = floor(p);
float3 f = frac(p) - 0.5;
uint3 u = uint3(int3(cell) + 4096);
u = u * 1664525u + 1013904223u;
u.x += u.y * u.z; u.y += u.z * u.x; u.z += u.x * u.y;
u ^= u >> 16u;
float3 r = float3(u & 0xffffu) / 65535.0;
float keep = step(r.x, P.z);
float dotm = 1.0 - smoothstep(P.y * 0.6, P.y, length(f));
float flick = 0.55 + 0.45 * sin(Time * (3.0 + r.y * 7.0) + r.z * 40.0);
float3 ember = lerp(float3(0.91, 0.69, 0.44), float3(0.78, 0.44, 0.23), r.y);
return float4(ember * flick * 2.0, keep * dotm);
"""

MATERIAL = r'''
import unreal
mel = unreal.MaterialEditingLibrary
eal = unreal.EditorAssetLibrary
at = unreal.AssetToolsHelpers.get_asset_tools()
QUIET = unreal.PropertyAccessChangeNotifyMode.NEVER
if not eal.does_directory_exist('__DIR__'):
    eal.make_directory('__DIR__')
m = unreal.load_asset('__DIR__/__MAT__')
if m is None:
    m = at.create_asset('__MAT__', '__DIR__', unreal.Material, unreal.MaterialFactoryNew())
mel.delete_all_material_expressions(m)
m.set_editor_property('blend_mode', unreal.BlendMode.BLEND_MASKED)
m.set_editor_property('shading_model', unreal.MaterialShadingModel.MSM_UNLIT)
m.set_editor_property('two_sided', True)
m.set_editor_property('used_with_skeletal_mesh', True)
m.set_editor_property('opacity_mask_clip_value', 0.5)
c = mel.create_material_expression(m, unreal.MaterialExpressionCustom, -300, 0)
c.set_editor_property('output_type', unreal.CustomMaterialOutputType.CMOT_FLOAT4, QUIET)
c.set_editor_property('code', __HLSL__, QUIET)
arr = []
for n in ['WP', 'Obj', 'Time', 'P']:
    ci = unreal.CustomInput()
    ci.set_editor_property('input_name', n)
    arr.append(ci)
c.set_editor_property('inputs', arr, QUIET)
mel.connect_material_expressions(mel.create_material_expression(m, unreal.MaterialExpressionWorldPosition, -700, -100), '', c, 'WP')
mel.connect_material_expressions(mel.create_material_expression(m, unreal.MaterialExpressionObjectPositionWS, -700, 0), '', c, 'Obj')
mel.connect_material_expressions(mel.create_material_expression(m, unreal.MaterialExpressionTime, -700, 100), '', c, 'Time')
pv = mel.create_material_expression(m, unreal.MaterialExpressionVectorParameter, -700, 200)
pv.set_editor_property('parameter_name', 'Cloud')
pv.set_editor_property('default_value', unreal.LinearColor(1.6, 0.32, 0.55, 3.0))
mel.connect_material_expressions(pv, 'RGBA', c, 'P')
rgb = mel.create_material_expression(m, unreal.MaterialExpressionComponentMask, 0, -50)
rgb.set_editor_property('r', True); rgb.set_editor_property('g', True); rgb.set_editor_property('b', True); rgb.set_editor_property('a', False)
mel.connect_material_expressions(c, '', rgb, '')
al = mel.create_material_expression(m, unreal.MaterialExpressionComponentMask, 0, 80)
al.set_editor_property('r', False); al.set_editor_property('g', False); al.set_editor_property('b', False); al.set_editor_property('a', True)
mel.connect_material_expressions(c, '', al, '')
mel.connect_material_property(rgb, '', unreal.MaterialProperty.MP_EMISSIVE_COLOR)
mel.connect_material_property(al, '', unreal.MaterialProperty.MP_OPACITY_MASK)
mel.recompile_material(m)
print('SKIN saved=' + str(eal.save_loaded_asset(m, False)))
rt = unreal.load_asset('__DIR__/__RT__')
if rt is None:
    rt = at.create_asset('__RT__', '__DIR__', unreal.TextureRenderTarget2D, unreal.TextureRenderTargetFactoryNew())
rt.set_editor_property('size_x', 512)
rt.set_editor_property('size_y', 512)
rt.set_editor_property('render_target_format', unreal.TextureRenderTargetFormat.RTF_RGBA16F)
rt.set_editor_property('clear_color', unreal.LinearColor(0.0, 0.0, 0.0, 1.0))
print('RT saved=' + str(eal.save_loaded_asset(rt, False)))
u = unreal.load_asset('__DIR__/__UI__')
if u is None:
    u = at.create_asset('__UI__', '__DIR__', unreal.Material, unreal.MaterialFactoryNew())
mel.delete_all_material_expressions(u)
u.set_editor_property('material_domain', unreal.MaterialDomain.MD_UI)
u.set_editor_property('blend_mode', unreal.BlendMode.BLEND_TRANSLUCENT)
t = mel.create_material_expression(u, unreal.MaterialExpressionTextureSampleParameter2D, -500, 0)
t.set_editor_property('parameter_name', 'Cloud')
t.set_editor_property('texture', rt)
lum = mel.create_material_expression(u, unreal.MaterialExpressionDotProduct, -250, 150)
mel.connect_material_expressions(t, 'RGB', lum, 'A')
k = mel.create_material_expression(u, unreal.MaterialExpressionConstant3Vector, -500, 250)
k.set_editor_property('constant', unreal.LinearColor(0.6, 0.6, 0.6, 1.0))
mel.connect_material_expressions(k, '', lum, 'B')
sat = mel.create_material_expression(u, unreal.MaterialExpressionSaturate, -100, 150)
mel.connect_material_expressions(lum, '', sat, '')
mel.connect_material_property(t, 'RGB', unreal.MaterialProperty.MP_EMISSIVE_COLOR)
mel.connect_material_property(sat, '', unreal.MaterialProperty.MP_OPACITY)
mel.recompile_material(u)
print('UI saved=' + str(eal.save_loaded_asset(u, False)))
'''

STAGE_SCRIPT = r'''
import unreal
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
X, Y, Z = __STAGE__
have = {}
for a in eas.get_all_level_actors():
    if a.get_actor_label().startswith('KeeperPointCloud_'):
        have[a.get_actor_label()] = a
t = have.get('KeeperPointCloud_Traveller')
if t is None:
    t = eas.spawn_actor_from_class(unreal.SkeletalMeshActor, unreal.Vector(X, Y, Z))
    t.set_actor_label('KeeperPointCloud_Traveller')
t.set_actor_location(unreal.Vector(X, Y, Z), False, False)
t.set_actor_rotation(unreal.Rotator(roll=0.0, pitch=0.0, yaw=-60.0), False)
t.set_editor_property('is_spatially_loaded', False)
t.set_folder_path('Loading/KeeperPointCloud')
sk = t.skeletal_mesh_component
sk.set_skeletal_mesh_asset(unreal.load_asset('/Game/SaskartaGaea/Characters/Traveller/SK_Traveller'))
mat = unreal.load_asset('__DIR__/__MAT__')
for i in range(sk.get_num_materials()):
    sk.set_material(i, mat)
sk.set_editor_property('animation_mode', unreal.AnimationMode.ANIMATION_SINGLE_NODE)
# The actor is intentionally offstage and only appears in a show-only scene capture.
# Keep evaluating bones even when ordinary player-camera visibility says it is hidden.
sk.set_editor_property('visibility_based_anim_tick_option', unreal.VisibilityBasedAnimTickOption.ALWAYS_TICK_POSE_AND_REFRESH_BONES)
sk.override_animation_data(unreal.load_asset('/Game/SaskartaGaea/Characters/Traveller/Anims/A_Traveller_SlowWalk'), True, True, 0.0, 1.0)
sk.set_editor_property('cast_shadow', False)
sk.set_editor_property('visible_in_ray_tracing', False)
c = have.get('KeeperPointCloud_Capture')
if c is None:
    c = eas.spawn_actor_from_class(unreal.SceneCapture2D, unreal.Vector(X + 330.0, Y, Z + 95.0))
    c.set_actor_label('KeeperPointCloud_Capture')
c.set_actor_location(unreal.Vector(X + 330.0, Y, Z + 95.0), False, False)
c.set_actor_rotation(unreal.Rotator(roll=0.0, pitch=-2.0, yaw=180.0), False)
c.set_editor_property('is_spatially_loaded', False)
c.set_folder_path('Loading/KeeperPointCloud')
cc = c.capture_component2d
cc.set_editor_property('texture_target', unreal.load_asset('__DIR__/__RT__'))
cc.set_editor_property('fov_angle', 40.0)
cc.set_editor_property('capture_source', unreal.SceneCaptureSource.SCS_SCENE_COLOR_HDR)
cc.set_editor_property('primitive_render_mode', unreal.SceneCapturePrimitiveRenderMode.PRM_USE_SHOW_ONLY_LIST)
cc.clear_show_only_components()
cc.show_only_actor_components(t, False)
# Start dormant; the runtime guard enables capture only for a visible point-cloud consumer.
cc.set_editor_property('capture_every_frame', False)
cc.set_editor_property('capture_on_movement', False)
off = ['Atmosphere', 'Fog', 'VolumetricFog', 'Lighting', 'DynamicShadows', 'GlobalIllumination', 'LumenGlobalIllumination', 'LumenReflections', 'AmbientOcclusion', 'Bloom', 'MotionBlur', 'Cloud', 'SkyLighting', 'PostProcessing', 'TemporalAA', 'AntiAliasing', 'EyeAdaptation']
cc.set_editor_property('show_flag_settings', [unreal.EngineShowFlagsSetting(show_flag_name=n, enabled=False) for n in off])
print('STAGE traveller ' + t.get_actor_label() + ' capture ' + c.get_actor_label())
print('saved ' + str(unreal.EditorLoadingAndSavingUtils.save_packages([t.get_package(), c.get_package()], True)))
'''

# Run only after NS_LoadingKeeperPoints has been authored and SaskartaCore rebuilt.
# The old skinned actor remains the animation source; only the Niagara actor is
# captured. ASaskartaKeeperPointActor binds User.KeeperMesh again in cooked play.
POINTS_SCRIPT = r'''
import unreal
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
actors = {a.get_actor_label(): a for a in eas.get_all_level_actors()
          if a.get_actor_label().startswith('KeeperPointCloud_')}
t = actors.get('KeeperPointCloud_Traveller')
c = actors.get('KeeperPointCloud_Capture')
assert isinstance(t, unreal.SkeletalMeshActor) and isinstance(c, unreal.SceneCapture2D)
system = unreal.load_asset('__DIR__/NS_LoadingKeeperPoints')
assert isinstance(system, unreal.NiagaraSystem), 'Author NS_LoadingKeeperPoints before installation'
handles = system.get_editor_property('emitter_handles')
assert len(handles) == 2, 'Keeper Niagara system must have exactly Body and Staff emitters'
staff_mesh = unreal.load_asset('/Game/SaskartaGaea/Characters/Traveller/SM_Traveller_Staff')
assert isinstance(staff_mesh, unreal.StaticMesh), 'Imported Traveller staff mesh missing'
assert hasattr(unreal, 'SaskartaKeeperPointActor'), 'Build SaskartaCore before installing Keeper points'
p = actors.get('KeeperPointCloud_Points')
if p is None:
    p = eas.spawn_actor_from_class(unreal.SaskartaKeeperPointActor, t.get_actor_location())
    p.set_actor_label('KeeperPointCloud_Points')
assert isinstance(p, unreal.SaskartaKeeperPointActor), 'Existing point actor has wrong class'
p.set_actor_location(t.get_actor_location(), False, False)
p.set_actor_rotation(t.get_actor_rotation(), False)
p.set_editor_property('is_spatially_loaded', False)
p.set_folder_path('Loading/KeeperPointCloud')
p.set_editor_property('source_actor', t)
p.set_editor_property('capture_actor', c)
component = p.get_component_by_class(unreal.NiagaraComponent)
assert component is not None
component.set_asset(system)
component.set_editor_property('auto_activate', False)
staff = p.get_editor_property('staff_source')
assert isinstance(staff, unreal.StaticMeshComponent)
staff.set_static_mesh(staff_mesh)
capture = c.capture_component2d
capture.clear_show_only_components()
capture.show_only_actor_components(p, False)
print('KEEPER_POINTS_STAGED ' + p.get_path_name())
print('saved ' + str(unreal.EditorLoadingAndSavingUtils.save_packages([p.get_package(), c.get_package()], True)))
'''


def fill(t, **kw):
    for k, v in kw.items():
        t = t.replace(f"__{k}__", str(v))
    return check_banned(t)


def script(step):
    if step == "material":
        return fill(MATERIAL, DIR=DIR, MAT=MAT, RT=RT, UI=UI_MAT, HLSL=repr(HLSL))
    if step == "points":
        return fill(POINTS_SCRIPT, DIR=DIR)
    return fill(STAGE_SCRIPT, DIR=DIR, MAT=MAT, RT=RT, STAGE=repr(STAGE))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("step", choices=["material", "stage", "points", "check"])
    a = ap.parse_args(argv)
    if a.step == "check":
        for s in ("material", "stage", "points"):
            source = script(s)
            ast.parse(source, filename=f"keeper-{s}.py")
            print(s, len(source), "chars and Python syntax ok")
        return 0
    ok, out, err = python_run(script(a.step))
    print(out.strip())
    if not ok:
        print("failed:", err, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
