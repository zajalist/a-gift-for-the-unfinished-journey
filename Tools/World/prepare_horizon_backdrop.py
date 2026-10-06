"""Stage a reversible, low-cost atmosphere backdrop A/B; never contact Unreal.

Use only after the horizon identity probe. Existing scenery/fog/sky actors are
not changed. Material samples the existing SkyAtmosphere LUT, keeping its live
sun/sky lighting and replacing only below-horizon empty-world colour with haze.
"""
from pathlib import Path
import ast
from prepare_ground_contact_loading import HEAD

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'Saved/HorizonRepair'
ASSET = '/Game/SaskartaGaea/Look/M_Saskarta_HorizonHaze'
LABEL = 'Saskarta_HorizonHaze_Backdrop'
TAG = 'Saskarta_HorizonHaze_v1'

MATERIAL = HEAD + '''
asset_path = '__ASSET__'
eal = unreal.EditorAssetLibrary
mel = unreal.MaterialEditingLibrary
if eal.does_asset_exist(asset_path):
    raise RuntimeError('Horizon material already exists; inspect it before replacing anything')
mat = unreal.AssetToolsHelpers.get_asset_tools().create_asset('M_Saskarta_HorizonHaze',
      '/Game/SaskartaGaea/Look', unreal.Material, unreal.MaterialFactoryNew())
mat.set_editor_property('blend_mode', unreal.BlendMode.BLEND_MASKED)
mat.set_editor_property('shading_model', unreal.MaterialShadingModel.MSM_UNLIT)
mat.set_editor_property('two_sided', True)
mat.set_editor_property('is_sky', False)
mat.set_editor_property('dither_opacity_mask', True)
mat.set_editor_property('opacity_mask_clip_value', .5)
cv = mel.create_material_expression(mat, unreal.MaterialExpressionCameraVectorWS, -650, 0)
floor = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -650, 160)
floor.set_editor_property('parameter_name', 'HorizonSlope')
floor.set_editor_property('default_value', 0.02)
direction = mel.create_material_expression(mat, unreal.MaterialExpressionCustom, -390, 0)
direction.set_editor_property('description', 'Plain haze below the finite-world horizon')
direction.set_editor_property('output_type', unreal.CustomMaterialOutputType.CMOT_FLOAT3)
direction.set_editor_property('code', 'float3 v = normalize(-CV); float r = length(v.xy); float2 h = r > 0.0001 ? v.xy / r : float2(1,0); return normalize(float3(h, max(v.z / max(r,0.0001), max(Floor,0.001))));')
inputs = []
for name in ('CV', 'Floor'):
    pin = unreal.CustomInput()
    pin.set_editor_property('input_name', name)
    inputs.append(pin)
direction.set_editor_property('inputs', inputs)
sky = mel.create_material_expression(mat, unreal.MaterialExpressionSkyAtmosphereViewLuminance, -120, 0)
sky_inputs = mel.get_material_expression_input_names(sky)
if len(sky_inputs) != 1:
    raise RuntimeError('Expected the single WorldDirection sky input')
links = [mel.connect_material_expressions(cv, '', direction, 'CV'),
         mel.connect_material_expressions(floor, '', direction, 'Floor'),
         mel.connect_material_expressions(direction, '', sky, sky_inputs[0]),
         mel.connect_material_property(sky, '', unreal.MaterialProperty.MP_EMISSIVE_COLOR)]
if not all(links):
    raise RuntimeError('Horizon material connection failed; do not place or save')
mask_cv=mel.create_material_expression(mat,unreal.MaterialExpressionCameraVectorWS,-650,390)
mask=mel.create_material_expression(mat,unreal.MaterialExpressionCustom,-390,390)
mask.set_editor_property('description','Only below geometric horizon; native upper sky and sun remain visible')
mask.set_editor_property('output_type',unreal.CustomMaterialOutputType.CMOT_FLOAT1)
mask.set_editor_property('code','return smoothstep(0.0, 0.05, normalize(CV).z);')
pin=unreal.CustomInput();pin.set_editor_property('input_name','CV');mask.set_editor_property('inputs',[pin])
assert mel.connect_material_expressions(mask_cv,'',mask,'CV')
assert mel.connect_material_property(mask,'',unreal.MaterialProperty.MP_OPACITY_MASK)
errors=list(mel.recompile_material(mat));assert not errors,str(errors)
print('HORIZON_MATERIAL ' + json.dumps({'path': mat.get_path_name(), 'links': links,
      'nodes': mel.get_num_material_expressions(mat), 'saved': False}, separators=(',', ':')))
'''

PLACE = HEAD + '''
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
actors = eas.get_all_level_actors()
if any(a.get_actor_label() == '__LABEL__' for a in actors):
    raise RuntimeError('Backdrop already exists; use its explicit on/off scripts')
mat = unreal.load_asset('__ASSET__')
if not isinstance(mat, unreal.Material) or mat.get_editor_property('is_sky') or mat.get_editor_property('blend_mode')!=unreal.BlendMode.BLEND_MASKED:
    raise RuntimeError('Prepared compiled lower-horizon material required')
mesh = unreal.load_asset('/Engine/BasicShapes/Sphere.Sphere')
if mesh is None:
    raise RuntimeError('Built-in sphere missing')
actor = eas.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(389079.6, 408050.0, 0))
actor.set_actor_label('__LABEL__')
actor.set_editor_property('tags', ['__TAG__'])
actor.set_editor_property('is_spatially_loaded', False)
actor.set_editor_property('enable_auto_lod_generation', False)
comp = actor.get_component_by_class(unreal.StaticMeshComponent)
comp.set_static_mesh(mesh)
comp.set_material(0, mat)
comp.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
comp.set_editor_property('cast_shadow', False)
comp.set_editor_property('enable_auto_lod_generation', False)
comp.set_editor_property('affect_distance_field_lighting', False)
comp.set_editor_property('affect_dynamic_indirect_lighting', False)
comp.set_editor_property('receives_decals', False)
comp.set_editor_property('visible_in_ray_tracing', False)
actor.set_actor_scale3d(unreal.Vector(400000, 400000, 400000))
actor.set_actor_enable_collision(False)
comp.set_collision_profile_name('NoCollision')
comp.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
comp.set_editor_property('generate_overlap_events',False)
assert not actor.get_actor_enable_collision() and comp.get_collision_enabled()==unreal.CollisionEnabled.NO_COLLISION
print('HORIZON_PLACED ' + json.dumps({'actor': actor.get_path_name(), 'package': actor.get_package().get_name(),
      'material': mat.get_path_name(), 'radius_cm': 20000000, 'saved': False}, separators=(',', ':')))
'''

VISIBILITY = HEAD + '''
actors = [a for a in unreal.EditorLevelLibrary.get_all_level_actors() if a.get_actor_label() == '__LABEL__']
if len(actors) != 1 or '__TAG__' not in [str(t) for t in actors[0].tags]:
    raise RuntimeError('Exactly one owned horizon actor required')
a = actors[0]
a.set_actor_hidden_in_game(__HIDDEN__)
a.set_is_temporarily_hidden_in_editor(__HIDDEN__)
print('HORIZON_VISIBILITY ' + json.dumps({'actor': a.get_path_name(), 'hidden': __HIDDEN__, 'saved': False}))
'''

# A partial IsSky dome disables the native full-screen sky for the whole view.
# The lower-only repair must be an ordinary masked surface, leaving native sky
# pixels (and their sun disks) untouched above the geometric horizon.
LOWER_ONLY = HEAD + '''
actors=[a for a in unreal.EditorLevelLibrary.get_all_level_actors() if a.get_actor_label()=='__LABEL__']
if len(actors)!=1 or '__TAG__' not in [str(t) for t in actors[0].tags]:
    raise RuntimeError('Exactly one owned unsaved horizon trial required')
mat=unreal.load_asset('__ASSET__')
comp=actors[0].get_component_by_class(unreal.StaticMeshComponent)
if comp.get_material(0)!=mat:
    raise RuntimeError('Owned backdrop material changed; inspect before editing')
mel=unreal.MaterialEditingLibrary
if mel.get_num_material_expressions(mat)!=4:
    raise RuntimeError('Expected the original four-node unsaved trial; do not duplicate mask nodes')
mat.set_editor_property('blend_mode',unreal.BlendMode.BLEND_MASKED)
mat.set_editor_property('is_sky',False)
cv=mel.create_material_expression(mat,unreal.MaterialExpressionCameraVectorWS,-650,390)
mask=mel.create_material_expression(mat,unreal.MaterialExpressionCustom,-390,390)
mask.set_editor_property('description','Only below geometric horizon; native upper sky and sun remain visible')
mask.set_editor_property('output_type',unreal.CustomMaterialOutputType.CMOT_FLOAT1)
mask.set_editor_property('code','return step(0.002, normalize(CV).z);')
pin=unreal.CustomInput();pin.set_editor_property('input_name','CV')
mask.set_editor_property('inputs',[pin])
links=[mel.connect_material_expressions(cv,'',mask,'CV'),
       mel.connect_material_property(mask,'',unreal.MaterialProperty.MP_OPACITY_MASK)]
if not all(links):
    raise RuntimeError('Lower hemisphere mask connection failed; no save')
mel.recompile_material(mat)
print('HORIZON_LOWER_ONLY '+json.dumps({'material':mat.get_path_name(),'nodes':mel.get_num_material_expressions(mat),
    'links':links,'is_sky':False,'saved':False,'native_upper_sky_preserved':True},separators=(',',':')))
'''

SOFT_EDGE = HEAD + '''
actors=[a for a in unreal.EditorLevelLibrary.get_all_level_actors() if a.get_actor_label()=='__LABEL__']
assert len(actors)==1 and '__TAG__' in [str(t) for t in actors[0].tags],'Exact owned trial required'
mat=unreal.load_asset('__ASSET__');mel=unreal.MaterialEditingLibrary
assert actors[0].get_component_by_class(unreal.StaticMeshComponent).get_material(0)==mat
assert mel.get_num_material_expressions(mat)==6 and not mat.get_editor_property('is_sky'),'Expected the six-node lower-only trial'
assert mat.get_editor_property('blend_mode')==unreal.BlendMode.BLEND_MASKED
masks=[e for e in unreal.ObjectIterator(unreal.MaterialExpressionCustom) if e.get_outer()==mat and e.get_editor_property('description')=='Only below geometric horizon; native upper sky and sun remain visible']
assert len(masks)==1 and masks[0].get_editor_property('code')=='return step(0.002, normalize(CV).z);','Inspect changed mask before editing'
# Native temporal opacity coverage expects clip .5 for exact zero/full endpoints.
# Smooth over 2.86 degrees below the horizon; the actual low dawn sun stays uncovered.
mat.set_editor_property('dither_opacity_mask',True)
mat.set_editor_property('opacity_mask_clip_value',.5)
masks[0].set_editor_property('code','return smoothstep(0.0, 0.05, normalize(CV).z);')
errors=list(mel.recompile_material(mat));assert not errors,str(errors)
print('HORIZON_SOFT_EDGE '+json.dumps({'material':mat.get_path_name(),'nodes':6,'is_sky':False,'dither_opacity_mask':True,'clip':.5,'sky_untouched_above_degrees':0.0,'saved':False},separators=(',',':')))
'''


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    bodies = [('10_material.py', MATERIAL), ('20_place.py', PLACE),
              ('21_lower_only_material.py', LOWER_ONLY),
              ('22_soft_horizon_edge.py', SOFT_EDGE),
              ('30_ab_off.py', VISIBILITY.replace('__HIDDEN__', 'True')),
              ('31_ab_on.py', VISIBILITY.replace('__HIDDEN__', 'False'))]
    for name, body in bodies:
        code = body.replace('__ASSET__', ASSET).replace('__LABEL__', LABEL).replace('__TAG__', TAG)
        ast.parse(code)
        for token in ('try', 'getattr', 'import time', 'open(', '.replace(', 'new_level(', 'save_asset', 'destroy_actor'):
            if token in code:
                raise ValueError(f'Editor policy token: {token}')
        path = OUT / name
        path.write_text(code, encoding='utf-8')
        print(path)


if __name__ == '__main__':
    main()
