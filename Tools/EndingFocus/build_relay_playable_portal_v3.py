"""Offline, reversible S26 relay-tower pointed-portal chamber derivative.

This starts from the throwaway *portal trial*, never the approved Tripo master.
It excavates a 3.8 m x 4.8 m chamber set deeper within the 20 m tower base,
then adds a thin vaulted radio-room shell. It deliberately does not export or
install in Unreal: placement, texture seams and collision still need review.

Run only after capture/filming is clear; the exact Boolean visits ~1.9M faces.
"""
from __future__ import annotations

import bpy
import math
import sys
from pathlib import Path

root=Path(__file__).resolve().parents[2]
source=root/'Saved/Ending/RelayTower/S26_RelayTower_PortalArch_v2.blend'
output=root/'Saved/Ending/RelayTower/S26_RelayTower_PlayableChamber_v3_ReviewOnly.blend'
bpy.ops.wm.open_mainfile(filepath=str(source))
tower=next(o for o in bpy.context.scene.objects if o.type=='MESH')
tower.name='Tripo tower masonry - derivative portal and chamber'

# The existing narrow passage spans x +/-.035, y -.55..+.23, z -.47..-.35.
# Keep the front buttressed facade intact; a narrow passage leads to the room.
bpy.ops.mesh.primitive_cube_add(size=1, location=(0,.10,-.392))
cutter=bpy.context.object
cutter.name='TEMP chamber cutter'
cutter.dimensions=(.19,.24,.170)  # 3.8 x 4.8 x 3.4 m at 20m/unit.
bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
bpy.context.view_layer.objects.active=tower
mod=tower.modifiers.new('Excavated playable radio chamber','BOOLEAN')
mod.operation='DIFFERENCE'; mod.solver='EXACT'; mod.object=cutter
print('CHAMBER_BOOLEAN_START',len(tower.data.polygons),flush=True)
bpy.ops.object.modifier_apply(modifier=mod.name)
print('CHAMBER_BOOLEAN_DONE',len(tower.data.polygons),flush=True)
bpy.data.objects.remove(cutter,do_unlink=True)

# Scale-free interior builder. Add only to the excavated area and keep a
# continuous 1.4 m portal-to-centre aisle. Materials use portable image maps.
def image_material(name,color_path,normal_path=None,orm_path=None):
    mat=bpy.data.materials.new(name); mat.use_nodes=True
    tree=mat.node_tree; nodes=tree.nodes; links=tree.links
    bsdf=nodes.get('Principled BSDF')
    image=nodes.new('ShaderNodeTexImage'); image.image=bpy.data.images.load(str(color_path),check_existing=True)
    links.new(image.outputs['Color'],bsdf.inputs['Base Color'])
    if normal_path:
        nimg=nodes.new('ShaderNodeTexImage'); nimg.image=bpy.data.images.load(str(normal_path),check_existing=True)
        nimg.image.colorspace_settings.name='Non-Color'
        nmap=nodes.new('ShaderNodeNormalMap'); nmap.inputs['Strength'].default_value=.55
        links.new(nimg.outputs['Color'],nmap.inputs['Color']); links.new(nmap.outputs['Normal'],bsdf.inputs['Normal'])
    if orm_path:
        orm=nodes.new('ShaderNodeTexImage'); orm.image=bpy.data.images.load(str(orm_path),check_existing=True)
        orm.image.colorspace_settings.name='Non-Color'
        sep=nodes.new('ShaderNodeSeparateColor'); links.new(orm.outputs['Color'],sep.inputs['Color'])
        links.new(sep.outputs['Green'],bsdf.inputs['Roughness'])
        links.new(sep.outputs['Blue'],bsdf.inputs['Metallic'])
    return mat

texdir=root/'SourceArt/Tripo/20261003/S26_VictorianRadioStation'
def pbr(label):
    return image_material(label,texdir/(label+'_BC.png'),texdir/(label+'_N.png'),texdir/(label+'_ORM.png'))
stone=pbr('S26_Weathered_Stone_Ashlar_PBR')
wood=pbr('S26_Dark_Oak_PBR')
copper=pbr('S26_Oxidized_Copper_PBR')
materials=[stone,wood,copper]

class Mesh:
    def __init__(self): self.verts=[]; self.faces=[]; self.uvs=[]; self.materials=[]
    def face(self,points,material=0,uv=None):
        offset=len(self.verts); self.verts.extend(points)
        self.faces.append(tuple(range(offset,offset+len(points))))
        self.materials.append(material)
        self.uvs.append(uv or [(x*20,y*20) for x,y,z in points])
    def box(self,lo,hi,material=0):
        x0,y0,z0=lo; x1,y1,z1=hi
        v=[(x0,y0,z0),(x1,y0,z0),(x1,y1,z0),(x0,y1,z0),
           (x0,y0,z1),(x1,y0,z1),(x1,y1,z1),(x0,y1,z1)]
        for ids in [(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)]:
            pts=[v[i] for i in ids]
            a=math.dist(pts[0],pts[1])*20; b=math.dist(pts[1],pts[2])*20
            self.face(pts,material,[(0,0),(a,0),(a,b),(0,b)])
    def object(self,name):
        data=bpy.data.meshes.new(name); data.from_pydata(self.verts,[],self.faces); data.update()
        obj=bpy.data.objects.new(name,data); bpy.context.collection.objects.link(obj)
        for m in materials: data.materials.append(m)
        layer=data.uv_layers.new(name='UVMap')
        for face,mat,uv in zip(data.polygons,self.materials,self.uvs):
            face.material_index=mat
            for li,coord in zip(face.loop_indices,uv): layer.data[li].uv=coord
        return obj

shell=Mesh()
# Genuine level floor / threshold: at z=-.469, only 1 cm above passage.
shell.box((-.088,-.015,-.476),(.088,.213,-.469),1)
# Stone side walls and end wall remain within the Boolean void.
shell.box((-.095,-.012,-.469),(-.088,.208,-.380),0)
shell.box((.088,-.012,-.469),(.095,.208,-.380),0)
shell.box((-.095,.208,-.469),(.095,.217,-.380),0)
# Ribbed Gothic barrel vault: 2.5 m at spring, >4 m at apex. No aisle intrusion.
n=16
xs=[-.088+i*.176/n for i in range(n+1)]
def crown(x): return -.380+.055*math.sqrt(max(0,1-(x/.088)**2))
for i in range(n):
    xa,xb=xs[i],xs[i+1]
    shell.face([(xa,-.009,crown(xa)),(xb,-.009,crown(xb)),
                (xb,.210,crown(xb)),(xa,.210,crown(xa))],0,
               [(xa*20,0),(xb*20,0),(xb*20,4.38),(xa*20,4.38)])
for y in (0,.055,.11,.165,.205):
    for i in range(n):
        xa,xb=xs[i],xs[i+1]
        shell.face([(xa,y,crown(xa)-.004),(xb,y,crown(xb)-.004),
                    (xb,y+.004,crown(xb)-.004),(xa,y+.004,crown(xa)-.004)],1)
# Walnut lower panelling, allowing the portal itself to stay unblocked.
for x in (-.087,.083):
    shell.box((x,-.009,-.463),(x+.004,.204,-.425),1)
    for y in (0,.055,.11,.165,.200):
        shell.box((x-.003,y,-.466),(x+.007,y+.004,-.422),1)
shell.box((-.083,.205,-.467),(.083,.210,-.425),1)
# Integrated radio desk on the left; wide centre aisle and right wall stay clear.
shell.box((-.084,.055,-.432),(-.030,.175,-.423),1)
shell.box((-.084,.052,-.467),(-.079,.180,-.432),1)
shell.box((-.035,.052,-.467),(-.030,.180,-.432),1)
shell.box((-.084,.172,-.467),(-.030,.179,-.432),1)
for i in range(5):
    x=-.080+i*.010
    shell.box((x,.175,-.451),(x+.005,.180,-.446),2)
shell_obj=shell.object('Playable vaulted radio room - separate PBR shell')

# Reference anchors stay in the editable source, excluded from later GLB export.
for name,point in [('PORTAL_FLOOR',(0,-.323,-.469)),
                   ('STUDIO_CENTRE',(0,.10,-.469)),
                   ('WINDOW_RAY_PENDING',(0,0,-.390))]:
    empty=bpy.data.objects.new(name,None); empty.location=point
    bpy.context.collection.objects.link(empty)

# Boolean topology, exterior UV paint and siting must be checked before use.
bpy.context.preferences.filepaths.save_version=0
bpy.ops.wm.save_as_mainfile(filepath=str(output))
print('PLAYABLE_CHAMBER_REVIEW_ONLY',str(output),len(shell_obj.data.polygons),flush=True)
