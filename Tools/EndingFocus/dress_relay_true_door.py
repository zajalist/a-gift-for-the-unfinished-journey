"""Dress the approved tower's true-door *review derivative* without recutting it.

Loads the separate true-door + CIN24-window Blender review file. Adds only
separable stone/wood/copper geometry: pointed archivolt, deep jambs, a level
playable threshold, passage arcade and period radio-station fixtures. The
approved Tripo master and the existing cutter scripts are never written.
"""
from __future__ import annotations

import bpy
import math
from pathlib import Path

root=Path(__file__).resolve().parents[2]
source=root/'Saved/Ending/RelayTower/S26_RelayTower_TrueDoorWindow_ReviewOnly.blend'
output=root/'Saved/Ending/RelayTower/S26_RelayTower_TrueDoorDressed_ReviewOnly.blend'
bpy.ops.wm.open_mainfile(filepath=str(source))

def existing(name):
    mat=bpy.data.materials.get(name)
    if mat is None: raise RuntimeError('Required review PBR material missing: '+name)
    return mat

stone=existing('S26_Weathered_Stone_Ashlar_PBR')
wood=existing('S26_Dark_Oak_PBR')
copper=existing('S26_Oxidized_Copper_PBR')
materials=[stone,wood,copper]

# Exactly the same oblique portal frame as build_relay_true_door_portal.py.
cx,cy=.119,-.127
nx,ny=-.670,.742
m=math.hypot(nx,ny); nx/=m; ny/=m
sx,sy=-ny,nx
def P(u,s,z): return (cx+nx*s+sx*u,cy+ny*s+sy*u,z)

class Batch:
    def __init__(self): self.verts=[];self.faces=[];self.mats=[];self.uvs=[]
    def face(self,points,mat=0,uv=None):
        base=len(self.verts);self.verts.extend(points)
        self.faces.append(tuple(range(base,base+len(points))))
        self.mats.append(mat)
        if uv is None:
            coords=[]
            for x,y,z in points:
                dx=x-cx;dy=y-cy
                coords.append((dx*sx+dy*sy,dx*nx+dy*ny,z))
            spans=[max(v[k] for v in coords)-min(v[k] for v in coords) for k in range(3)]
            axes=sorted(range(3),key=lambda k:spans[k],reverse=True)[:2]
            uv=[(v[axes[0]]*20.27,v[axes[1]]*20.27) for v in coords]
        self.uvs.append(uv)
    def prism(self,u0,u1,s0,s1,z0,z1,mat=0):
        a=P(u0,s0,z0);b=P(u1,s0,z0);c=P(u1,s1,z0);d=P(u0,s1,z0)
        e=P(u0,s0,z1);f=P(u1,s0,z1);g=P(u1,s1,z1);h=P(u0,s1,z1)
        for ids in [(a,d,c,b),(e,f,g,h),(a,b,f,e),(b,c,g,f),(c,d,h,g),(d,a,e,h)]:
            p=list(ids)
            w=math.dist(p[0],p[1])*20.27; v=math.dist(p[1],p[2])*20.27
            self.face(p,mat,[(0,0),(w,0),(w,v),(0,v)])
    def object(self,name):
        mesh=bpy.data.meshes.new(name);mesh.from_pydata(self.verts,[],self.faces);mesh.update()
        obj=bpy.data.objects.new(name,mesh);bpy.context.collection.objects.link(obj)
        for mat in materials: mesh.materials.append(mat)
        layer=mesh.uv_layers.new(name='UVMap')
        for poly,index,uv in zip(mesh.polygons,self.mats,self.uvs):
            poly.material_index=index
            for loop,co in zip(poly.loop_indices,uv): layer.data[loop].uv=co
        return obj

portal=Batch(); entry=Batch(); fittings=Batch()
HALF=.032
def inner(t): return HALF*t,-.350-.015*abs(t)
def outer(t): return .043*t,-.335-.019*abs(t)

# Two carved jambs are set just outside the 1.28m cut. Their reveals deepen
# into the actual passage, instead of hiding its edges behind a flat patch.
for sign in (-1,1):
    u0,u1=sorted((sign*.032,sign*.043))
    portal.prism(u0,u1,-.020,.030,-.476,-.355,0)
    # restrained carved arris; masonry courses align to the existing facade
    portal.prism(u0-.001,u1+.001,-.022,.031,-.477,-.472,0)
    portal.prism(u0-.001,u1+.001,-.022,.031,-.378,-.375,0)
    for z in (-.454,-.430,-.406,-.382):
        portal.prism(u0,u1,-.022,-.020,z,z+.001,0)

# Pointed, faceted Gothic archivolt. Its inner profile follows the *real*
# boolean outline; radial voussoirs sit outside the opening at every station.
N=20
for i in range(N):
    a=-1+2*i/N;b=-1+2*(i+1)/N
    iu0,iz0=inner(a);iu1,iz1=inner(b)
    ou0,oz0=outer(a);ou1,oz1=outer(b)
    # front stone voussoir with its own UV island and dark joint gap
    gap=.0010
    ua=a+gap;ub=b-gap
    ia,za=inner(ua);ib,zb=inner(ub);oa,oa_z=outer(ua);ob,ob_z=outer(ub)
    portal.face([P(ia,-.026,za),P(ib,-.026,zb),P(ob,-.026,ob_z),P(oa,-.026,oa_z)],0,
                [(0,0),(.18,0),(.18,.30),(0,.30)])
    # deep cut face: inner reveal connects exterior archivolt to passage wall
    portal.face([P(iu0,-.025,iz0),P(iu1,-.025,iz1),
                 P(iu1,.047,iz1),P(iu0,.047,iz0)],0,
                [(0,0),(.18,0),(.18,1.46),(0,1.46)])
    # outer arris gives a projecting silhouette in approach views
    portal.face([P(ou0,-.026,oz0),P(ou1,-.026,oz1),
                 P(ou1,.004,oz1),P(ou0,.004,oz0)],0)

# Short stone sill blocks cover the Boolean's lower exposed edge without
# introducing a horizontal slab across the approved facade.
for sign in (-1,1):
    u0,u1=sorted((sign*.032,sign*.051))
    portal.prism(u0,u1,-.018,.020,-.482,-.476,0)

# Clear walk surface: fill the overdeep raw boolean at the base while giving
# the player a continuous 1.28m-wide threshold into the carved studio.
entry.prism(-.031,.031,-.043,.175,-.477,-.468,0)
entry.prism(-.043,.043,-.056,-.025,-.484,-.476,0)
# Slim walnut threshold nosing, intentionally outside the capsule's feet.
entry.prism(-.051,.051,-.042,-.036,-.468,-.465,1)

# An arcade in the passage aligns with the stone chamber vault. Openings stay
# full width and 2.3m high. It breaks up the long raw Boolean tunnel.
def rib(s):
    for sign in (-1,1):
        u0,u1=sorted((sign*.032,sign*.037))
        entry.prism(u0,u1,s,s+.006,-.468,-.359,0)
        entry.prism(u0-.003,u1+.003,s-.002,s+.008,-.408,-.404,0)
    n=12
    for i in range(n):
        a=-1+2*i/n;b=-1+2*(i+1)/n
        u0,z0=inner(a);u1,z1=inner(b)
        entry.face([P(u0,s,z0),P(u1,s,z1),P(u1,s+.006,z1),P(u0,s+.006,z0)],0)
for s in (.052,.125,.198): rib(s)

# Radio-station identity at human scale: copper conduit, porcelain-like
# standoffs, wall lamps and a timber label plate (lettering added in UE).
for sign in (-1,1):
    u=sign*.051
    fittings.prism(u-.002,u+.002,-.015,.016,-.445,-.387,2)
    for z in (-.437,-.405):
        fittings.prism(u-.005,u+.005,-.018,-.010,z,z+.006,0)
    fittings.prism(u-.006,u+.006,-.027,-.016,-.400,-.386,2)

objs=[portal.object('S26 Gothic true-door carved archivolt and stone reveals'),
      entry.object('S26 true-door playable threshold and passage arcade'),
      fittings.object('S26 door radio fittings and sign board')]
for obj in objs: obj['review_only']=True

# This derivative still needs contact, UV, capsule and CIN24 ray validation.
bpy.context.preferences.filepaths.save_version=0
bpy.ops.wm.save_as_mainfile(filepath=str(output))
print('DRESSED_TRUE_DOOR_REVIEW',output,'added_faces',sum(len(o.data.polygons) for o in objs),flush=True)
