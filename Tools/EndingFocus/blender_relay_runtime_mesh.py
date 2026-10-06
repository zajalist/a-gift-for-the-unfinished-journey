"""Make a bottom-pivot mesh-only relay tower for guarded Unreal review import.

The art-review GLB and 8K texture files remain unchanged. This file is still
the full-resolution mesh; use Nanite only after in-editor inspection.
"""
import bpy
import pathlib
import sys
from mathutils import Matrix

src = pathlib.Path(sys.argv[sys.argv.index('--') + 1])
dst = pathlib.Path(sys.argv[sys.argv.index('--') + 2])
dst.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.open_mainfile(filepath=str(src))
obj = next(o for o in bpy.context.scene.objects if o.type == 'MESH')
mesh = obj.data
bottom = min(v.co.z for v in mesh.vertices)
mesh.transform(Matrix.Translation((0, 0, -bottom)))
mesh.materials.clear()
bpy.ops.object.select_all(action='DESELECT')
obj.select_set(True)
bpy.context.view_layer.objects.active = obj
bpy.ops.export_scene.gltf(filepath=str(dst), export_format='GLB', use_selection=True,
                          export_materials='NONE', export_texcoords=True,
                          export_normals=True, export_tangents=False)
print('RELAY_RUNTIME_MESH=' + str(dst), 'bottom_offset=' + str(-bottom), flush=True)
