"""Map the approved preview's painted main door pixels to tower local space."""
import bpy
import json
from pathlib import Path
from mathutils import Vector

root = Path(__file__).resolve().parents[2]
source = root / 'SourceArt/Tripo/20261003/S26_VictorianRadioStation/S26_RelayTower_8K_PBR_Review.blend'
bpy.ops.wm.open_mainfile(filepath=str(source))
tower = next(o for o in bpy.context.scene.objects if o.type == 'MESH')
cam_loc = Vector((1.4, -2.0, 0.8))
rot = (Vector((0, 0, 0)) - cam_loc).to_track_quat('-Z', 'Y')
right = rot @ Vector((1, 0, 0))
up = rot @ Vector((0, 1, 0))
forward = rot @ Vector((0, 0, -1))
inverse = tower.matrix_world.inverted()
rows = []
for px, py in ((420, 875), (420, 850), (395, 870), (445, 870),
               (420, 900), (280, 865), (505, 850)):
    origin = cam_loc + right*((px/800-.5)*1.0) + up*((.5-py/1000)*1.25)
    local_origin = inverse @ origin
    local_end = inverse @ (origin + forward*5)
    local_dir = (local_end-local_origin).normalized()
    hit, loc, normal, face = tower.ray_cast(local_origin, local_dir, distance=5)
    rows.append({'pixel': [px,py], 'hit': bool(hit),
                 'local': [round(float(v), 6) for v in loc] if hit else None,
                 'normal': [round(float(v), 6) for v in normal] if hit else None,
                 'face': int(face) if hit else None})
print('RELAY_DOOR_PIXELS '+json.dumps(rows,separators=(',',':')))
