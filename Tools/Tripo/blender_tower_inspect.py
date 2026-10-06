"""Inspect the decoded relay tower in Blender without modifying source assets."""
import bpy
import json
import pathlib
import sys

src = pathlib.Path(sys.argv[sys.argv.index('--') + 1])
out = src.parent / 'S26_RelayTower_Working.blend'
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
bpy.ops.import_scene.gltf(filepath=str(src))
meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
report = []
for obj in meshes:
    mesh = obj.data
    report.append({
        'name': obj.name,
        'vertices': len(mesh.vertices),
        'polygons': len(mesh.polygons),
        'uv_layers': [uv.name for uv in mesh.uv_layers],
        'materials': [m.name if m else None for m in mesh.materials],
        'dimensions': list(obj.dimensions),
    })
print('TOWER_INSPECTION=' + json.dumps(report))
bpy.ops.wm.save_as_mainfile(filepath=str(out))
print('TOWER_BLEND=' + str(out))
