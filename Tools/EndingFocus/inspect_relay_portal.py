"""Probe the Tripo relay tower's apparent front door for actual passable geometry."""
import bpy
import pathlib
import sys
from mathutils import Vector

src = pathlib.Path(sys.argv[sys.argv.index('--') + 1])
bpy.ops.wm.open_mainfile(filepath=str(src))
obj = next(o for o in bpy.context.scene.objects if o.type == 'MESH')
for z in (-0.43, -0.38, -0.32, -0.25, -0.18):
    row = []
    for x in (-0.12, -0.06, 0, 0.06, 0.12):
        hit, point, _normal, _index = obj.ray_cast(Vector((x, -1.5, z)), Vector((0, 1, 0)), distance=3)
        row.append(None if not hit else round(point.y, 3))
    print(f'DOOR_RAY z={z}: {row}', flush=True)
