"""Export the source FBX's weighted staff in its staff011 bone-local space."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'Tools/Cinematics'))
from traveller_contacts import source_mesh
sys.path.insert(0, str(ROOT / 'Tools/ModelReview'))
from fbx_reader import read_fbx

vertices, entries, triangles = source_mesh('tripo_mesh_88102862.001')
scene = read_fbx(str(ROOT / 'SourceArt/Characters/Traveller/traveller01_animated.fbx'))
source = next(g for g in scene.geometries.values() if g.name == 'tripo_mesh_88102862.001')
_, corner_uv, _ = source.corner_attributes()
triangle_corners, _ = source.triangulate()
assert corner_uv is not None and len(triangle_corners) == len(triangles)
assert len(entries) == 1 and entries[0][0] == 'staff011'
_, indices, weights, offsets = entries[0]
assert len(indices) == len(vertices) and min(weights) > .999
local = offsets[indices.argsort()]
out = ROOT / 'SourceArt/Characters/Traveller/Props/SM_Traveller_Staff.obj'
out.parent.mkdir(parents=True, exist_ok=True)
with out.open('w', encoding='ascii') as handle:
    handle.write('# Source staff, staff011 bone-local coordinates; parent bone scale is 100.\n')
    handle.write('o SM_Traveller_Staff\n')
    for x, y, z in local:
        handle.write(f'v {x:.8f} {y:.8f} {z:.8f}\n')
    for u, v in corner_uv[triangle_corners].reshape(-1, 2):
        handle.write(f'vt {u:.8f} {1.0-v:.8f}\n')
    for index, (a, b, c) in enumerate(triangles):
        vt = index*3
        handle.write(f'f {a+1}/{vt+1} {c+1}/{vt+3} {b+1}/{vt+2}\n')
print(out, len(local), len(triangles))
