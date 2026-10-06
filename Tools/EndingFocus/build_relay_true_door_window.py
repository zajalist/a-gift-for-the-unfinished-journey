"""Cut the measured CIN24 side view from the true-door tower derivative.

Source and output are review-only Blender files; the approved tower master is
untouched. The sightline follows validate_cin24_window_ray.py's corrected pose.
"""
import bpy
import math
from pathlib import Path

root = Path(__file__).resolve().parents[2]
source = root / 'Saved/Ending/RelayTower/S26_RelayTower_TrueDoorChamber_ReviewOnly.blend'
output = root / 'Saved/Ending/RelayTower/S26_RelayTower_TrueDoorWindow_ReviewOnly.blend'
bpy.ops.wm.open_mainfile(filepath=str(source))
tower = next(o for o in bpy.context.scene.objects if o.type == 'MESH'
             and 'tower masonry' in o.name)

eye_x, eye_y = 0.05043466924225656, -0.063262842538145
ray_x, ray_y = -0.8271019913546788, -0.5619653600508887
mid_distance = 385.0 / 2027.0
cx = eye_x + ray_x * mid_distance
cy = eye_y + ray_y * mid_distance
bpy.ops.mesh.primitive_cube_add(size=1, location=(cx, cy, -0.3875))
cutter = bpy.context.object
cutter.name = 'TEMP corrected CIN24 lightwell'
cutter.rotation_euler.z = math.atan2(ray_y, ray_x)
cutter.dimensions = (0.151, 0.070, 0.075)
bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
bpy.context.view_layer.objects.active = tower
mod = tower.modifiers.new('CIN24 true-door side-window review cut', 'BOOLEAN')
mod.operation = 'DIFFERENCE'
mod.solver = 'EXACT'
mod.object = cutter
print('TRUE_WINDOW_BOOLEAN_START', len(tower.data.polygons), flush=True)
bpy.ops.object.modifier_apply(modifier=mod.name)
print('TRUE_WINDOW_BOOLEAN_DONE', len(tower.data.polygons), flush=True)
bpy.data.objects.remove(cutter, do_unlink=True)
bpy.context.preferences.filepaths.save_version = 0
bpy.ops.wm.save_as_mainfile(filepath=str(output))
print('TRUE_DOOR_WINDOW_REVIEW_ONLY', output, flush=True)
