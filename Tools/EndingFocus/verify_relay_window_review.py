"""Read-only clearance probes for the cut tower chamber and CIN24 lightwell."""
import bpy
import json
from pathlib import Path

root = Path(__file__).resolve().parents[2]
source = root / 'Saved/Ending/RelayTower/S26_RelayTower_ChamberWindow_ReviewOnly.blend'
bpy.ops.wm.open_mainfile(filepath=str(source))
tower = next(o for o in bpy.context.scene.objects if o.type == 'MESH'
             and 'tower masonry' in o.name)
room = next(o for o in bpy.context.scene.objects if o.type == 'MESH'
            and 'radio room' in o.name)

eye = (-0.008048546563727556, -0.22973237045229047, -0.3931243216576218)
ray = (-0.990306820839879, 0.13854663690617663, 0.0108)
distance = 1200.0 / 2027.0
seen = {}
for obj in (tower, room):
    hit, point, normal, face = obj.ray_cast(eye, ray, distance=distance)
    seen[obj.name] = {'hit': bool(hit), 'face': int(face) if hit else None,
                      'point': [round(v, 6) for v in point] if hit else None}
assert not any(row['hit'] for row in seen.values()), seen

portal = []
for z in (-0.44, -0.40, -0.36):
    for x in (-0.03, 0.0, 0.03):
        hit, point, _, face = tower.ray_cast((x, -0.55, z), (0, 1, 0), distance=0.86)
        portal.append((x, z, bool(hit), int(face) if hit else None))
assert all(not r[2] for r in portal), portal

print('RELAY_WINDOW_CHECK ' + json.dumps({
    'source': str(source), 'tower_faces': len(tower.data.polygons),
    'room_faces': len(room.data.polygons), 'cin24': seen,
    'portal': portal,
}, separators=(',', ':')))
