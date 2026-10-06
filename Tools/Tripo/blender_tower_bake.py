"""Bake source tower textures to the equalized UV map as unlit 8K PBR maps."""
import bpy
import pathlib
import sys
import time

argv = sys.argv[sys.argv.index('--') + 1:]
blend = pathlib.Path(argv[0])
kind = argv[1]
if kind not in {'basecolor', 'orm', 'normal'}:
    raise ValueError(kind)
bpy.ops.wm.open_mainfile(filepath=str(blend))
obj = next(o for o in bpy.context.scene.objects if o.type == 'MESH')
mesh = obj.data
mesh.uv_layers.active = mesh.uv_layers['GameUV']
mesh.uv_layers['GameUV'].active_render = True
bpy.ops.object.select_all(action='DESELECT')
obj.select_set(True)
bpy.context.view_layer.objects.active = obj

root = blend.parent / 'extracted'
src = root / (kind + ('.png' if kind == 'normal' else '.jpg'))
image = bpy.data.images.load(str(src), check_existing=False)
image.colorspace_settings.name = 'sRGB' if kind == 'basecolor' else 'Non-Color'
target = bpy.data.images.new('Tower_' + kind + '_8K', width=8192, height=8192,
                             alpha=False, float_buffer=False)
target.colorspace_settings.name = 'sRGB' if kind == 'basecolor' else 'Non-Color'
material = mesh.materials[0]
material.use_nodes = True
nodes = material.node_tree.nodes
nodes.clear()
links = material.node_tree.links
old_uv = nodes.new('ShaderNodeUVMap')
old_uv.uv_map = 'SourceUV'
source = nodes.new('ShaderNodeTexImage')
source.image = image
source.interpolation = 'Linear'
links.new(old_uv.outputs['UV'], source.inputs['Vector'])
target_node = nodes.new('ShaderNodeTexImage')
target_node.image = target
for n in nodes:
    n.select = False
target_node.select = True
nodes.active = target_node
out = nodes.new('ShaderNodeOutputMaterial')
if kind == 'normal':
    normal_map = nodes.new('ShaderNodeNormalMap')
    normal_map.space = 'TANGENT'
    normal_map.uv_map = 'SourceUV'
    normal_map.inputs['Strength'].default_value = 1.0
    links.new(source.outputs['Color'], normal_map.inputs['Color'])
    shader = nodes.new('ShaderNodeBsdfPrincipled')
    links.new(normal_map.outputs['Normal'], shader.inputs['Normal'])
    links.new(shader.outputs['BSDF'], out.inputs['Surface'])
else:
    emission = nodes.new('ShaderNodeEmission')
    links.new(source.outputs['Color'], emission.inputs['Color'])
    links.new(emission.outputs['Emission'], out.inputs['Surface'])

scene = bpy.context.scene
scene.render.engine = 'CYCLES'
scene.cycles.device = 'CPU'
scene.cycles.samples = 1
scene.render.bake.use_clear = True
scene.render.bake.margin = 4
scene.render.bake.target = 'IMAGE_TEXTURES'
scene.render.bake.use_selected_to_active = False
scene.render.bake.normal_space = 'TANGENT'
print('BAKE_START=' + kind + ' ' + str(time.time()), flush=True)
bpy.ops.object.bake(type='NORMAL' if kind == 'normal' else 'EMIT')
print('BAKE_DONE=' + kind + ' ' + str(time.time()), flush=True)
dst = root / ('tower_' + kind + '_' + blend.stem + '_8k.png')
target.filepath_raw = str(dst)
target.file_format = 'PNG'
target.save()
print('BAKE_IMAGE=' + str(dst), flush=True)
