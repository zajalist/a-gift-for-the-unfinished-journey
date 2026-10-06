"""Export a geometry-only GLB for the texel-density checker."""
import bpy
import pathlib
import sys

src = pathlib.Path(sys.argv[sys.argv.index('--') + 1])
dst = src.with_suffix('.uv-audit.glb')
bpy.ops.wm.open_mainfile(filepath=str(src))
obj = next(o for o in bpy.context.scene.objects if o.type == 'MESH')
obj.data.uv_layers.remove(obj.data.uv_layers['SourceUV'])
obj.data.materials.clear()
bpy.ops.object.select_all(action='DESELECT')
obj.select_set(True)
bpy.context.view_layer.objects.active = obj
bpy.ops.export_scene.gltf(filepath=str(dst), export_format='GLB', use_selection=True,
                          export_materials='NONE', export_texcoords=True,
                          export_normals=False, export_tangents=False)
print('UV_AUDIT=' + str(dst), flush=True)
