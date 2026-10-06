"""Cut a reversible CIN24 side lightwell into the playable tower review.

This is a geometry trial, not a runtime mesh. It preserves the approved 8K
master and the chamber-only derivative. Review new masonry faces and UVs before
exporting or importing anything into Unreal.
"""
import bpy
import math
from pathlib import Path

root = Path(__file__).resolve().parents[2]
source = root / 'Saved/Ending/RelayTower/S26_RelayTower_PlayableChamber_v2_ReviewOnly.blend'
output = root / 'Saved/Ending/RelayTower/S26_RelayTower_ChamberWindow_v2_ReviewOnly.blend'
bpy.ops.wm.open_mainfile(filepath=str(source))
tower = next(o for o in bpy.context.scene.objects if o.type == 'MESH'
             and 'tower masonry' in o.name)

# World-protected CIN24 ray transformed into this nominal tower frame by
# validate_cin24_window_ray.py. Two source-mesh intersections lie 1.07 and
# 1.85 m from the held eye. The oblique prism has margins around both hits.
ray_x, ray_y = -0.990306820839879, 0.13854663690617663
bpy.ops.mesh.primitive_cube_add(size=1, location=(-0.080, -0.2197, -0.3875))
cutter = bpy.context.object
cutter.name = 'TEMP CIN24 oblique side lightwell'
cutter.rotation_euler.z = math.atan2(ray_y, ray_x)
cutter.dimensions = (0.122, 0.070, 0.075)
bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
bpy.context.view_layer.objects.active = tower
mod = tower.modifiers.new('CIN24 side lightwell review cut', 'BOOLEAN')
mod.operation = 'DIFFERENCE'
mod.solver = 'EXACT'
mod.object = cutter
print('WINDOW_BOOLEAN_START', len(tower.data.polygons), flush=True)
bpy.ops.object.modifier_apply(modifier=mod.name)
print('WINDOW_BOOLEAN_DONE', len(tower.data.polygons), flush=True)
bpy.data.objects.remove(cutter, do_unlink=True)

# A protected sightline marker is retained in the editable .blend only.
eye = (-0.008048546563727556, -0.22973237045229047, -0.3931243216576218)
marker = bpy.data.objects.new('CIN24_EYE_REVIEW_ONLY', None)
marker.location = eye
bpy.context.collection.objects.link(marker)
bpy.context.preferences.filepaths.save_version = 0
bpy.ops.wm.save_as_mainfile(filepath=str(output))
print('RELAY_CHAMBER_WINDOW_REVIEW_ONLY', output, flush=True)
