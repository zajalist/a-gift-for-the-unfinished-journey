"""Reversible pointed-arch portal cut in the approved tower copy.

The approved 8K review .blend is read-only. This makes a new geometry-only
derivative; it does not export or install an Unreal asset.
"""
import bpy
import math
from pathlib import Path

root = Path(__file__).resolve().parents[2]
source = root / 'SourceArt/Tripo/20261003/S26_VictorianRadioStation/S26_RelayTower_8K_PBR_Review.blend'
output = root / 'Saved/Ending/RelayTower/S26_RelayTower_PortalArch_v2.blend'
bpy.ops.wm.open_mainfile(filepath=str(source))
tower = next(o for o in bpy.context.scene.objects if o.type == 'MESH')
tower.name = 'Tripo tower masonry - pointed portal review'

# At the nominal 20 m tower scale this is 1.4 m wide and 2.6 m high at the
# point. A central 1 m-wide capsule has >2.1 m vertical clearance. The arch
# is continuous with the original lower masonry, not an added rectangular kit.
half_width = 0.035
bottom = -0.520
spring = -0.365
point = -0.350
def crown(x):
    return point + (spring - point) * abs(x / half_width)

outline = [(-half_width, bottom), (half_width, bottom),
           (half_width, spring)]
outline.extend((half_width - i * (2 * half_width / 16),
                crown(half_width - i * (2 * half_width / 16)))
               for i in range(1, 17))
y0, y1 = -0.55, 0.23
verts = [(x, y0, z) for x, z in outline] + [(x, y1, z) for x, z in outline]
n = len(outline)
faces = [tuple(reversed(range(n))), tuple(range(n, 2*n))]
for i in range(n):
    j = (i + 1) % n
    faces.append((i, j, n+j, n+i))
mesh = bpy.data.meshes.new('Pointed portal cutter mesh')
mesh.from_pydata(verts, [], faces)
mesh.update()
cutter = bpy.data.objects.new('TEMP pointed portal cutter', mesh)
bpy.context.collection.objects.link(cutter)
bpy.context.view_layer.objects.active = tower
mod = tower.modifiers.new('Pointed playable entrance review cut', 'BOOLEAN')
mod.operation = 'DIFFERENCE'
mod.solver = 'EXACT'
mod.object = cutter
print('ARCH_BOOLEAN_START', len(tower.data.polygons), flush=True)
bpy.ops.object.modifier_apply(modifier=mod.name)
print('ARCH_BOOLEAN_DONE', len(tower.data.polygons), flush=True)
bpy.data.objects.remove(cutter, do_unlink=True)
bpy.context.preferences.filepaths.save_version = 0
bpy.ops.wm.save_as_mainfile(filepath=str(output))
print('RELAY_ARCH_PORTAL_REVIEW_ONLY', output, flush=True)
