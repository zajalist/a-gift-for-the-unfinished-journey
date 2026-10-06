"""Reversible playable cut through the approved tower's painted main door.

The door centre and outward normal come from a ray probe using the approved
preview camera. This copies the 8K review .blend and saves a separate geometry
trial; the approved master is never overwritten.
"""
import bpy
import math
from pathlib import Path

root = Path(__file__).resolve().parents[2]
source = root / 'SourceArt/Tripo/20261003/S26_VictorianRadioStation/S26_RelayTower_8K_PBR_Review.blend'
output = root / 'Saved/Ending/RelayTower/S26_RelayTower_TrueDoorPortal_ReviewOnly.blend'
bpy.ops.wm.open_mainfile(filepath=str(source))
tower = next(o for o in bpy.context.scene.objects if o.type == 'MESH')
tower.name = 'Tripo tower masonry - true door portal review'

# A stable patch of the painted front door measures centre (.119,-.127) and
# outward normal (+.67,-.74). The route goes inward into the lower base.
cx, cy = 0.119, -0.127
nx, ny = -0.670, 0.742  # inward, normalized below
mag = math.hypot(nx, ny)
nx, ny = nx/mag, ny/mag
sx, sy = -ny, nx  # lateral axis across the door
half_width = 0.032  # 1.28 m at the nominal 20 m tower scale
bottom, spring, point = -0.520, -0.365, -0.350
def crown(u):
    return point + (spring-point)*abs(u/half_width)

outline = [(-half_width,bottom),(half_width,bottom),(half_width,spring)]
outline.extend((half_width-i*(2*half_width/16),
                crown(half_width-i*(2*half_width/16))) for i in range(1,17))
s0,s1 = -0.10,0.31
def vertex(u,z,s):
    return (cx+nx*s+sx*u,cy+ny*s+sy*u,z)
verts = [vertex(u,z,s0) for u,z in outline] + [vertex(u,z,s1) for u,z in outline]
n = len(outline)
faces = [tuple(reversed(range(n))),tuple(range(n,2*n))]
for i in range(n):
    j=(i+1)%n
    faces.append((i,j,n+j,n+i))
mesh=bpy.data.meshes.new('True painted-door pointed cutter')
mesh.from_pydata(verts,[],faces); mesh.update()
cutter=bpy.data.objects.new('TEMP true-door cutter',mesh)
bpy.context.collection.objects.link(cutter)
bpy.context.view_layer.objects.active=tower
mod=tower.modifiers.new('True-door pointed passage review cut','BOOLEAN')
mod.operation='DIFFERENCE'; mod.solver='EXACT'; mod.object=cutter
print('TRUE_DOOR_BOOLEAN_START',len(tower.data.polygons),flush=True)
bpy.ops.object.modifier_apply(modifier=mod.name)
print('TRUE_DOOR_BOOLEAN_DONE',len(tower.data.polygons),flush=True)
bpy.data.objects.remove(cutter,do_unlink=True)
bpy.context.preferences.filepaths.save_version=0
bpy.ops.wm.save_as_mainfile(filepath=str(output))
print('TRUE_DOOR_PORTAL_REVIEW_ONLY',output,flush=True)
