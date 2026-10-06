"""Read-only geometry check for the S26 playable tower review derivative."""
import bpy
import json
from pathlib import Path

root = Path(__file__).resolve().parents[2]
source = root / 'Saved/Ending/RelayTower/S26_RelayTower_PlayableChamber_ReviewOnly.blend'
bpy.ops.wm.open_mainfile(filepath=str(source))
meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
assert len(meshes) == 2, [(o.name, len(o.data.polygons)) for o in meshes]
tower = next(o for o in meshes if 'tower masonry' in o.name)
room = next(o for o in meshes if 'radio room' in o.name)

def hit_at(obj, x, z, start_y=-0.55, length=0.86):
    hit, loc, normal, index = obj.ray_cast((x, start_y, z), (0, 1, 0), distance=length)
    return None if not hit else [round(float(loc.y), 5), int(index)]

ray_rows = []
for z in (-0.44, -0.40, -0.36, -0.32):
    for x in (-0.03, 0.0, 0.03):
        ray_rows.append({'x': x, 'z': z, 'tower_hit': hit_at(tower, x, z),
                         'room_hit': hit_at(room, x, z)})

assert all(r['tower_hit'] is None and
           (r['room_hit'] is None or r['room_hit'][0] >= 0.28)
           for r in ray_rows if r['z'] in (-0.44, -0.40, -0.36)), ray_rows
for mat in room.data.materials:
    assert mat and mat.use_nodes
    images = [n.image for n in mat.node_tree.nodes if n.type == 'TEX_IMAGE']
    assert len(images) == 3 and all(img and Path(bpy.path.abspath(img.filepath)).exists()
                                    for img in images), mat.name

print('RELAY_CHAMBER_CHECK ' + json.dumps({
    'source': str(source),
    'tower_faces': len(tower.data.polygons),
    'room_faces': len(room.data.polygons),
    'clearance_rays': ray_rows,
    'materials': [m.name for m in room.data.materials],
}, separators=(',', ':')))
