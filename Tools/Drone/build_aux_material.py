"""Emit small editor chunks for the acoustic feed; saves only two new owned assets.

    python Tools/Drone/build_aux_material.py emit Saved/Drone/aux_material
    python Tools/GameFlow/editor/ending_editor.py run-dir Saved/Drone/aux_material

Root runs the chunks serially with the editor gate held, no PIE or standalone.
Compilation/readback precede the separate save chunk. Runtime owns the blendable;
no permanent actor or level package is needed.
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FOLDER = '/Game/SaskartaGaea/Look/AuxSensors'
MAT = FOLDER + '/M_PP_AuxSensors'
MI = FOLDER + '/MI_PP_AuxSensors'
# LiDAR-style point cloud: 60 m/s fronts, 7 s memory fade, isolated dots about 9 px apart.
# Runtime writes Clock, RoadHalfWidth, RoadCentre/Forward and the last three pings each step.
SCALARS = dict(Clock=0., PingSpeed=6000., Fade=7., RangeCm=9000., RoadHalfWidth=300., GridCm=2.,
               SpacingPx=9., DotPx=.95, Gain=1.)
EMPTY_PING = (0., 0., 0., -10000.)
VECTORS = dict(PingA=EMPTY_PING, PingB=EMPTY_PING, PingC=EMPTY_PING, RoadCentre=(0., 0., 0., 0.),
               RoadForward=(1., 0., 0., 0.), BlipA=(0., 0., 0., 0.), BlipB=(0., 0., 0., 0.),
               LightA=(0., 0., 0., 0.), LightB=(0., 0., 0., 0.))
SCENE_PINS = ['WP', 'Normal', 'Depth', 'Stencil', 'Cam']


def chunks():
    hlsl = (ROOT / 'Shaders/AuxSensors.hlsl').read_text(encoding='utf-8')
    pins = [*SCENE_PINS, *SCALARS, *VECTORS]
    setup = f'''import unreal
eal = unreal.EditorAssetLibrary
mel = unreal.MaterialEditingLibrary
mat = unreal.load_asset({MAT!r})
if mat is None:
    mat = unreal.AssetToolsHelpers.get_asset_tools().create_asset('M_PP_AuxSensors', {FOLDER!r}, unreal.Material, unreal.MaterialFactoryNew())
mat.set_editor_property('material_domain', unreal.MaterialDomain.MD_POST_PROCESS)
mat.set_editor_property('blendable_location', unreal.BlendableLocation.BL_SCENE_COLOR_BEFORE_BLOOM)
mat.set_editor_property('blendable_priority', 900)
n = 0
while mel.get_num_material_expressions(mat) > 0 and n < 16:
    mel.delete_all_material_expressions(mat)
    n += 1
q = unreal.PropertyAccessChangeNotifyMode.NEVER
cu = mel.create_material_expression(mat, unreal.MaterialExpressionCustom, 0, 0)
cu.set_editor_property('description', 'AcousticRanging', q)
cu.set_editor_property('output_type', unreal.CustomMaterialOutputType.CMOT_FLOAT3, q)
cu.set_editor_property('code', {hlsl!r}, q)
inputs = []
for name in {pins!r}:
    ci = unreal.CustomInput()
    ci.set_editor_property('input_name', name)
    inputs.append(ci)
cu.set_editor_property('inputs', inputs, q)
print('AUX_SETUP nodes=' + str(mel.get_num_material_expressions(mat)))
'''
    graph = f'''import unreal
mel = unreal.MaterialEditingLibrary
mat = unreal.load_asset({MAT!r})
cu = [n for n in mel.get_material_expressions(mat) if n.get_class() == unreal.MaterialExpressionCustom.static_class()][0]
links = []
wp = mel.create_material_expression(mat, unreal.MaterialExpressionWorldPosition, -800, -350)
links.append(mel.connect_material_expressions(wp, '', cu, 'WP'))
for name, kind, y in [('Normal', unreal.SceneTextureId.PPI_WORLD_NORMAL, -260), ('Depth', unreal.SceneTextureId.PPI_SCENE_DEPTH, -180), ('Stencil', unreal.SceneTextureId.PPI_CUSTOM_STENCIL, -100)]:
    node = mel.create_material_expression(mat, unreal.MaterialExpressionSceneTexture, -800, y)
    node.set_editor_property('scene_texture_id', kind)
    links.append(mel.connect_material_expressions(node, 'Color', cu, name))
cam = mel.create_material_expression(mat, unreal.MaterialExpressionCameraPositionWS, -800, -430)
links.append(mel.connect_material_expressions(cam, '', cu, 'Cam'))
for i, (name, value) in enumerate({SCALARS!r}.items()):
    node = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -800, i * 65)
    node.set_editor_property('parameter_name', name)
    node.set_editor_property('default_value', value)
    links.append(mel.connect_material_expressions(node, '', cu, name))
for i, (name, value) in enumerate({VECTORS!r}.items()):
    node = mel.create_material_expression(mat, unreal.MaterialExpressionVectorParameter, -1100, i * 80)
    node.set_editor_property('parameter_name', name)
    node.set_editor_property('default_value', unreal.LinearColor(*value))
    links.append(mel.connect_material_expressions(node, 'RGBA', cu, name))
links.append(mel.connect_material_property(cu, '', unreal.MaterialProperty.MP_EMISSIVE_COLOR))
if not all(links):
    raise RuntimeError('auxiliary material link failed')
errors = mel.recompile_material(mat)
print('AUX_COMPILE links=' + str(len(links)) + ' errors=' + str(errors))
if len(errors) != 0:
    raise RuntimeError('auxiliary material compile failed')
'''
    instance = f'''import unreal
mel = unreal.MaterialEditingLibrary
mi = unreal.load_asset({MI!r})
if mi is None:
    mi = unreal.AssetToolsHelpers.get_asset_tools().create_asset('MI_PP_AuxSensors', {FOLDER!r}, unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
mel.set_material_instance_parent(mi, unreal.load_asset({MAT!r}))
mel.update_material_instance(mi)
print('AUX_INSTANCE parent=' + mi.get_editor_property('parent').get_name())
'''
    save = f'''import unreal
mel = unreal.MaterialEditingLibrary
mat = unreal.load_asset({MAT!r})
mi = unreal.load_asset({MI!r})
if mat is None or mi is None or mi.get_editor_property('parent') != mat:
    raise RuntimeError('auxiliary material readback mismatch')
errors = mel.recompile_material(mat)
if len(errors) != 0:
    raise RuntimeError('auxiliary material is not ready to save')
print('AUX_SAVE ' + str(unreal.EditorLoadingAndSavingUtils.save_packages([mat.get_package(), mi.get_package()], True)))
'''
    return {'10_setup.py': setup, '20_graph.py': graph, '30_instance.py': instance, '90_save.py': save}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('step', choices=['emit', 'check'])
    ap.add_argument('out', nargs='?', default='Saved/Drone/aux_material')
    args = ap.parse_args()
    result = chunks()
    for name, source in result.items():
        compile(source, name, 'exec')
        if any(s in source for s in ('try', 'getattr', 'import time', 'open(', '.replace(', 'new_level(')):
            raise SystemExit('banned editor token in ' + name)
    if args.step == 'emit':
        dest = ROOT / args.out
        dest.mkdir(parents=True, exist_ok=True)
        for name, source in result.items():
            (dest / name).write_text(source, encoding='utf-8')
    print(json.dumps({'chunks': len(result), 'material': MAT, 'instance': MI}))


if __name__ == '__main__':
    main()
