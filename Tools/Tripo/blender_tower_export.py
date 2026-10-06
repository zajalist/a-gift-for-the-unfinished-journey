"""Assemble the relaid-out tower into a reviewable glTF PBR master."""
import bpy
import pathlib
import sys

src = pathlib.Path(sys.argv[sys.argv.index('--') + 1])
root = src.parent
maps = root / 'extracted'
stem = src.stem
bpy.ops.wm.open_mainfile(filepath=str(src))
obj = next(o for o in bpy.context.scene.objects if o.type == 'MESH')
mesh = obj.data
mesh.uv_layers.remove(mesh.uv_layers['SourceUV'])
mesh.uv_layers[0].name = 'UVMap'
mesh.uv_layers[0].active_render = True

mat = mesh.materials[0]
mat.use_nodes = True
nodes = mat.node_tree.nodes
nodes.clear()
links = mat.node_tree.links
out = nodes.new('ShaderNodeOutputMaterial')
shader = nodes.new('ShaderNodeBsdfPrincipled')
shader.inputs['Roughness'].default_value = 1.0
shader.inputs['Metallic'].default_value = 0.0
links.new(shader.outputs['BSDF'], out.inputs['Surface'])

def image_node(kind, colorspace):
    suffix = '_8k_refined.png' if kind == 'basecolor' else '_8k.png'
    p = maps / ('tower_' + kind + '_' + stem + suffix)
    if not p.is_file():
        raise FileNotFoundError(p)
    im = bpy.data.images.load(str(p), check_existing=False)
    im.colorspace_settings.name = colorspace
    n = nodes.new('ShaderNodeTexImage')
    n.image = im
    n.interpolation = 'Linear'
    return n

color = image_node('basecolor', 'sRGB')
orm = image_node('orm', 'Non-Color')
normal = image_node('normal', 'Non-Color')
links.new(color.outputs['Color'], shader.inputs['Base Color'])
split = nodes.new('ShaderNodeSeparateColor')
split.mode = 'RGB'
links.new(orm.outputs['Color'], split.inputs['Color'])
links.new(split.outputs['Green'], shader.inputs['Roughness'])
links.new(split.outputs['Blue'], shader.inputs['Metallic'])
normal_map = nodes.new('ShaderNodeNormalMap')
normal_map.space = 'TANGENT'
normal_map.uv_map = 'UVMap'
links.new(normal.outputs['Color'], normal_map.inputs['Color'])
links.new(normal_map.outputs['Normal'], shader.inputs['Normal'])

group = bpy.data.node_groups.get('glTF Material Output')
if group is None:
    group = bpy.data.node_groups.new('glTF Material Output', 'ShaderNodeTree')
    group.interface.new_socket(name='Occlusion', in_out='INPUT', socket_type='NodeSocketFloat')
    group.nodes.new('NodeGroupOutput')
gltf_node = nodes.new('ShaderNodeGroup')
gltf_node.node_tree = group
links.new(split.outputs['Red'], gltf_node.inputs['Occlusion'])

bpy.ops.object.select_all(action='DESELECT')
obj.select_set(True)
bpy.context.view_layer.objects.active = obj
bpy.context.preferences.filepaths.save_version = 0
blend = root / 'S26_RelayTower_8K_PBR_Review.blend'
glb = root / 'S26_RelayTower_8K_PBR_Review.glb'
bpy.ops.wm.save_as_mainfile(filepath=str(blend))
print('PBR_BLEND=' + str(blend), flush=True)
bpy.ops.export_scene.gltf(filepath=str(glb), export_format='GLB', use_selection=True,
                          export_materials='EXPORT', export_image_format='AUTO',
                          export_texcoords=True, export_normals=True,
                          export_tangents=False, export_apply=False)
print('PBR_GLB=' + str(glb), flush=True)
