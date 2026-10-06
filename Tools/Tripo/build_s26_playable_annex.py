"""Build a reversible, playable S26 Victorian radio-room annex.

Run with Blender in background mode. This creates no Unreal assets or world edits.
Local origin is the protected CIN24 inside point; +Y points inward from the door.
"""
from __future__ import annotations

import bpy
import math
import os
import random
from pathlib import Path


OUT = Path(__file__).resolve().parents[2] / "SourceArt/Tripo/20261003/S26_VictorianRadioStation"
OUT.mkdir(parents=True, exist_ok=True)
random.seed(26)

bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)


def make_texture(name, kind, size=384):
    """Portable tileable, hand-shaped color/normal/ORM maps; UVs use metres."""
    image = bpy.data.images.new(name + "_BC", width=size, height=size, alpha=True)
    pixels = [0.0] * (size * size * 4)
    heights = [0.0] * (size * size)
    for j in range(size):
        v = j / size
        for i in range(size):
            u = i / size
            h = 0.0
            if kind == "brick":
                row = int(v * 8)
                fu = (u * 4 + (row % 2) * .5) % 1
                fv = (v * 8) % 1
                mortar = min(fu, 1-fu) < .025 or min(fv, 1-fv) < .048
                fleck = .5 * math.sin(i * .37 + j * .19) + .5 * math.sin(i * .09 - j * .33)
                shade = .045 * fleck + .055 * math.sin(row * 13 + int(u * 4) * 7)
                base = (.49+shade, .45+shade*.82, .36+shade*.70) if not mortar else (.25,.24,.20)
                h = .58 + shade if not mortar else .12
            elif kind == "wood":
                grain = math.sin(u*68 + 2.0*math.sin(v*16))*.025 + math.sin(u*211+v*7)*.012
                plank = (u*5) % 1
                seam = min(plank,1-plank)<.015
                stain = .04*math.sin(v*9+u*3) + .025*math.sin(v*37-u*2)
                base = (.18+grain+stain,.105+grain*.7+stain*.6,.067+grain*.5+stain*.45)
                if seam: base = tuple(x*.48 for x in base)
                h = .5 + grain*3 if not seam else .1
            elif kind == "copper":
                patina = .5 + .25*math.sin(u*11+v*7) + .15*math.sin(u*23-v*13)
                oxide = max(0,min(1,patina))
                base = (.28-.16*oxide,.29+.12*oxide,.23+.10*oxide)
                h = .45 + .04*math.sin(u*37+v*26)
            elif kind == "plaster":
                dust = .015*(math.sin(i*.17+j*.22)+math.sin(i*.36-j*.29))
                base = (.50+dust,.45+dust,.36+dust)
                h = .5+dust
            else:
                base = (.32,.27,.19); h=.5
            idx = j*size+i
            heights[idx] = h
            pixels[idx*4:idx*4+4] = [*base,1.0]
    image.pixels[:] = pixels
    image.filepath_raw = str(OUT / (name+"_BC.png"))
    image.file_format = 'PNG'; image.save()

    normal = bpy.data.images.new(name+"_N", width=size, height=size, alpha=True)
    orm = bpy.data.images.new(name+"_ORM", width=size, height=size, alpha=True)
    npix=[0.0]*(size*size*4); opix=[0.0]*(size*size*4)
    rough = {"brick":.86,"wood":.77,"copper":.55,"plaster":.94}[kind]
    metal = 1.0 if kind == "copper" else 0.0
    for j in range(size):
        for i in range(size):
            idx=j*size+i
            dx=heights[j*size+(i+1)%size]-heights[j*size+(i-1)%size]
            dy=heights[((j+1)%size)*size+i]-heights[((j-1)%size)*size+i]
            nx=-dx*2; ny=-dy*2; nz=1.0
            length=math.sqrt(nx*nx+ny*ny+nz*nz)
            npix[idx*4:idx*4+4]=[(nx/length+1)/2,(ny/length+1)/2,(nz/length+1)/2,1]
            opix[idx*4:idx*4+4]=[.92,rough,metal,1]
    normal.pixels[:]=npix; normal.filepath_raw=str(OUT/(name+"_N.png")); normal.file_format='PNG'; normal.save()
    orm.pixels[:]=opix; orm.filepath_raw=str(OUT/(name+"_ORM.png")); orm.file_format='PNG'; orm.save()
    return image,normal,orm


def material(name, kind, rgba=None, metal=0, rough=.65):
    mat=bpy.data.materials.new(name); mat.use_nodes=True
    bsdf=mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs['Metallic'].default_value=metal
    bsdf.inputs['Roughness'].default_value=rough
    if kind:
        bc,normal,orm=make_texture(name,kind)
        tex=mat.node_tree.nodes.new('ShaderNodeTexImage'); tex.image=bc
        mat.node_tree.links.new(tex.outputs['Color'],bsdf.inputs['Base Color'])
        ntex=mat.node_tree.nodes.new('ShaderNodeTexImage'); ntex.image=normal; normal.colorspace_settings.name='Non-Color'
        nmap=mat.node_tree.nodes.new('ShaderNodeNormalMap'); nmap.inputs['Strength'].default_value=.55
        mat.node_tree.links.new(ntex.outputs['Color'],nmap.inputs['Color'])
        mat.node_tree.links.new(nmap.outputs['Normal'],bsdf.inputs['Normal'])
        otex=mat.node_tree.nodes.new('ShaderNodeTexImage'); otex.image=orm; orm.colorspace_settings.name='Non-Color'
        sep=mat.node_tree.nodes.new('ShaderNodeSeparateColor')
        mat.node_tree.links.new(otex.outputs['Color'],sep.inputs['Color'])
        mat.node_tree.links.new(sep.outputs['Green'],bsdf.inputs['Roughness'])
        mat.node_tree.links.new(sep.outputs['Blue'],bsdf.inputs['Metallic'])
    else:
        bsdf.inputs['Base Color'].default_value=rgba
    return mat


BRICK=material('S26_Weathered_Stone_Ashlar_PBR','brick')
WOOD=material('S26_Dark_Oak_PBR','wood')
COPPER=material('S26_Oxidized_Copper_PBR','copper')
PLASTER=material('S26_Interior_Lime_Plaster_PBR','plaster')
BLACK=material('S26_Painted_Iron',None,(.045,.053,.05,1),metal=.65,rough=.52)
GLASS=material('S26_Frosted_Amber_Glass',None,(.45,.33,.15,1),rough=.13)
MATS=[BRICK,WOOD,COPPER,PLASTER,BLACK,GLASS]


class MeshBatch:
    def __init__(self): self.verts=[]; self.faces=[]; self.uv=[]; self.mats=[]
    def face(self,points,mat=0,uv=None):
        # UE yaw +26.6° maps +Y inward. Mirror the authored plan so the
        # protected CIN24 window is at local X=-1.22 without negative actor scale.
        start=len(self.verts); self.verts.extend([(-x,y,z) for x,y,z in reversed(points)])
        self.faces.append(tuple(range(start,start+len(points))))
        self.mats.append(mat)
        if uv is None: uv=[(p[0],p[1]) for p in points]
        self.uv.append(list(reversed(uv)))
    def box(self,lo,hi,mat=0):
        x0,y0,z0=lo; x1,y1,z1=hi
        v=[(x0,y0,z0),(x1,y0,z0),(x1,y1,z0),(x0,y1,z0),
           (x0,y0,z1),(x1,y0,z1),(x1,y1,z1),(x0,y1,z1)]
        for f in [(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)]:
            pts=[v[k] for k in f]
            self.face(pts,mat,[(0,0),(math.dist(pts[0],pts[1]),0),
                                (math.dist(pts[0],pts[1]),math.dist(pts[1],pts[2])),
                                (0,math.dist(pts[1],pts[2]))])
    def object(self,name,bevel=0):
        mesh=bpy.data.meshes.new(name); mesh.from_pydata(self.verts,[],self.faces); mesh.update()
        obj=bpy.data.objects.new(name,mesh); bpy.context.collection.objects.link(obj)
        for m in MATS: mesh.materials.append(m)
        layer=mesh.uv_layers.new(name='UVMap')
        for poly,mat,uvs in zip(mesh.polygons,self.mats,self.uv):
            poly.material_index=mat
            for li,uv in zip(poly.loop_indices,uvs): layer.data[li].uv=uv
        if bevel:
            mod=obj.modifiers.new('Soft machined arris','BEVEL'); mod.width=bevel; mod.segments=2
            mod.limit_method='ANGLE'; mod.angle_limit=math.radians(30)
            mod2=obj.modifiers.new('Weighted architectural normals','WEIGHTED_NORMAL')
        return obj


# Plan: 5.30 m × 5.30 m, shifted toward the wide equipment side.
# CIN24 protected inside = (0,0), door = (0,-1.8), eye ray hits right wall x=+1.22.
XL=-4.08; XR=1.22; YF=-1.80; YB=3.50; T=.23; WALL_TOP=3.25
struct=MeshBatch(); finish=MeshBatch(); detail=MeshBatch()


def wall(axis,pos,a0,a1,zmax,openings):
    """Continuous thick wall topology with real open portal(s), exposed reveals."""
    starts={a0,a1,*(q[0] for q in openings),*(q[1] for q in openings)}
    heights={0.0,zmax,*(q[2] for q in openings),*(q[3] for q in openings)}
    aa=sorted(starts); zz=sorted(heights)
    inner=pos+T if (axis=='y' and pos==YF) or (axis=='x' and pos==XL) else pos-T
    def point(p,a,z): return (a,p,z) if axis=='y' else (p,a,z)
    def uv(a,z): return (a,z)
    for a,b in zip(aa,aa[1:]):
        for low,high in zip(zz,zz[1:]):
            mid=(a+b)/2; mz=(low+high)/2
            hole=any(q[0]<mid<q[1] and q[2]<mz<q[3] for q in openings)
            if hole: continue
            for p,mat,order in [(pos,0,(a,b,high,low)),(inner,3,(b,a,high,low))]:
                l,r,top,bot=order
                struct.face([point(p,l,bot),point(p,r,bot),point(p,r,top),point(p,l,top)],mat,
                            [uv(l,bot),uv(r,bot),uv(r,top),uv(l,top)])
            # All thickness/reveal faces at grid edges where adjacent cell is absent.
            for edge,na,nz in [('bottom',mid,low-.001),('top',mid,high+.001),
                               ('left',a-.001,mz),('right',b+.001,mz)]:
                outside=na<a0 or na>a1 or nz<0 or nz>zmax
                neigh_hole=any(q[0]<na<q[1] and q[2]<nz<q[3] for q in openings)
                if not (outside or neigh_hole): continue
                if edge=='bottom': points=[point(pos,a,low),point(pos,b,low),point(inner,b,low),point(inner,a,low)]
                elif edge=='top': points=[point(pos,b,high),point(pos,a,high),point(inner,a,high),point(inner,b,high)]
                elif edge=='left': points=[point(pos,a,high),point(pos,a,low),point(inner,a,low),point(inner,a,high)]
                else: points=[point(pos,b,low),point(pos,b,high),point(inner,b,high),point(inner,b,low)]
                struct.face(points,0,[(0,0),(math.dist(points[0],points[1]),0),
                                      (math.dist(points[0],points[1]),T),(0,T)])


wall('y',YF,XL,XR,WALL_TOP,[(-.64,.64,0,2.38)])
wall('y',YB,XL,XR,WALL_TOP,[(-3.25,-1.95,1.15,2.48)])
wall('x',XL,YF,YB,WALL_TOP,[(.62,1.82,1.03,2.32)])
wall('x',XR,YF,YB,WALL_TOP,[(-.48,.96,1.00,2.42)])

# Solid floor and low brick plinth, with a level protected threshold.
struct.box((XL,YF,-.23),(XR,YB,0),0)
finish.box((XL+T,YF+T,.005),(XR-T,YB-T,.037),1)
for x0,x1 in [(XL-.07,XL+.02),(XR-.02,XR+.07)]:
    detail.box((x0,YF-.07,-.28),(x1,YB+.07,.22),0)
for y0,y1 in [(YF-.07,YF+.02),(YB-.02,YB+.07)]:
    detail.box((XL-.07,y0,-.28),(XR+.07,y1,.22),0)

# Open, framed window on camera-facing right wall. No central mullion intersects CIN24.
for y0,y1,z0,z1,xwall in [(-.48,.96,1.00,2.42,XR),(.62,1.82,1.03,2.32,XL)]:
    for y in (y0-.085,y1+.035): detail.box((xwall-.08,y,z0-.12),(xwall+.08,y+.05,z1+.12),1)
    for z in (z0-.12,z1+.07): detail.box((xwall-.09,y0-.12,z),(xwall+.09,y1+.12,z+.055),1)
    # Exterior sill with a drip edge. The aperture is actually empty.
    detail.box((xwall-.18,y0-.15,z0-.13),(xwall+.18,y1+.15,z0-.075),0)

# Rear-facing window and deliberately broad entrance portal.
for x0,x1,z0,z1,ywall in [(-3.25,-1.95,1.15,2.48,YB),(-.64,.64,0,2.38,YF)]:
    for x in (x0-.08,x1+.035): detail.box((x,ywall-.10,z0),(x+.045,ywall+.10,z1+.12),1)
    detail.box((x0-.10,ywall-.10,z1+.03),(x1+.10,ywall+.10,z1+.10),1)
    if z0>0: detail.box((x0-.11,ywall-.15,z0-.12),(x1+.11,ywall+.15,z0-.06),0)

# Victorian station cornice: three depth steps, exposed rafter tails, timber fascias.
for z,d,h in [(3.03,.09,.06),(3.13,.15,.055),(3.22,.24,.06)]:
    detail.box((XL-d,YF-d,z),(XR+d,YF+.025,z+h),1)
    detail.box((XL-d,YB-.025,z),(XR+d,YB+d,z+h),1)
    detail.box((XL-d,YF-d,z),(XL+.025,YB+d,z+h),1)
    detail.box((XR-.025,YF-d,z),(XR+d,YB+d,z+h),1)
for x in [XL+.25+i*.37 for i in range(14)]:
    for y in (YF-.30,YB+.20): detail.box((x,y,3.0),(x+.065,y+.12,3.28),1)

# Copper standing-seam pitched roof, 5.07 m ridge. Gable faces have true triangle topology.
ridge=(XL+XR)/2; eave=3.27; peak=5.07; over=.36
for y in (YF,YB):
    struct.face([(XL,y,eave),(XR,y,eave),(ridge,y,peak)],0,
                [(XL,eave),(XR,eave),(ridge,peak)])
for xedge in (XL-over,XR+over):
    pass
for side in (0,1):
    x0=XL-over if side==0 else ridge; x1=ridge if side==0 else XR+over
    z0=eave if side==0 else peak; z1=peak if side==0 else eave
    # Closed roof slab with visible fascia and underside.
    verts=[(x0,YF-over,z0),(x1,YF-over,z1),(x1,YB+over,z1),(x0,YB+over,z0)]
    under=[(x,y,z-.11) for x,y,z in verts]
    struct.face(verts,2,[(0,0),(math.dist(verts[0],verts[1]),0),
                             (math.dist(verts[0],verts[1]),YB-YF+2*over),(0,YB-YF+2*over)])
    struct.face(list(reversed(under)),1)
    for k in range(4): struct.face([verts[k],verts[(k+1)%4],under[(k+1)%4],under[k]],2)
    # Rolled copper seams run down-slope at ~0.47 m pitch.
    for yi in range(12):
        yy=YF-over+yi*((YB-YF+2*over)/11)
        for xa,xb,za,zb in [(x0,x1,z0,z1)]:
            detail.face([(xa,yy,za+.016),(xb,yy,zb+.016),(xb,yy+.012,zb+.022),(xa,yy+.012,za+.022)],2)

# Gable barge boards, ridge cap and guttering.
for y in (YF-over,YB+over):
    for xx,zz in [(XL-over,eave),(XR+over,eave)]:
        detail.box((xx-.035,y-.035,zz-.12),(xx+.035,y+.035,zz+.08),1)
    detail.box((ridge-.07,y-.055,peak-.12),(ridge+.07,y+.055,peak+.04),2)
for x in (XL-over,XR+over):
    detail.box((x-.045,YF-over,eave-.11),(x+.045,YB+over,eave-.015),2)

# Period facade joinery: pilasters, wainscot and raised timber panels, no route obstruction.
for x in (XL+.09,XR-.18):
    for y in (YF+.1,YB-.19):
        detail.box((x-.065,y-.065,.2),(x+.065,y+.065,3.02),1)
        for z,h,w in [(.17,.15,.19),(2.90,.13,.18)]:
            detail.box((x-w/2,y-w/2,z),(x+w/2,y+w/2,z+h),1)
for yy in (YF+.30,YB-.37):
    detail.box((XL+.25,yy,.90),(XR-.25,yy+.04,1.00),1)
for xx in (XL+.32,XR-.37):
    detail.box((xx,YF+.30,.90),(xx+.04,YB-.37,1.00),1)

# Tapered stone corner buttresses tie the annex to the approved Gothic tower.
for x in (XL-.09,XR+.09):
    for y in (YF-.09,YB+.09):
        signx = -1 if x<0 else 1
        signy = -1 if y<0 else 1
        a=(x,y,.13); b=(x+signx*.31,y,.13)
        c=(x+signx*.31,y+signy*.31,.13); d=(x,y+signy*.31,.13)
        e=(x+signx*.055,y+signy*.055,2.94)
        f=(x+signx*.19,y+signy*.055,2.94)
        g=(x+signx*.19,y+signy*.19,2.94)
        h=(x+signx*.055,y+signy*.19,2.94)
        for face in [(a,b,f,e),(b,c,g,f),(c,d,h,g),(d,a,e,h),(e,f,g,h)]:
            detail.face(face,0)
        detail.box((min(x,x+signx*.34),min(y,y+signy*.34),.72),
                   (max(x,x+signx*.34),max(y,y+signy*.34),.79),0)

# Shallow pointed archivolts echo the tower, while openings themselves stay generous.
for xc,y,z,width in [(0,YF-.055,2.48,1.54),(-2.60,YB+.055,2.57,1.54)]:
    pts=[(xc-width/2,y,z),(xc,y,z+.36),(xc+width/2,y,z),
         (xc+width/2-.08,y,z),(xc,y,z+.24),(xc-width/2+.08,y,z)]
    for k in range(2):
        detail.face([pts[k],pts[k+1],pts[5-k],pts[4-k]],0)
for y0,y1,z0,z1,xwall in [(-.48,.96,1.00,2.42,XR),(.62,1.82,1.03,2.32,XL)]:
    mid=(y0+y1)/2
    detail.face([(xwall+.02,y0-.08,z1+.14),(xwall+.02,mid,z1+.42),
                 (xwall+.02,y1+.08,z1+.14)],0)

# Front entry hood with a hipped copper cover, tapered oak brackets and sign board.
detail.box((-.92,YF-.43,2.60),(.92,YF+.04,2.69),1)
detail.box((-.99,YF-.51,2.70),(.99,YF+.09,2.81),2)
for x in (-.83,.76): detail.box((x,YF-.36,2.36),(x+.07,YF+.015,2.69),1)
detail.box((-.76,YF-.065,2.89),(.76,YF-.015,3.09),1)

# Interior radio studio: raised panel strips and a clean 1.28 m centre aisle.
# The equipment zone on the wide left side is deliberately kept free for existing desk actors.
for x in [XL+.4+i*.68 for i in range(6)]:
    detail.box((x,YB-.19,.26),(x+.038,YB-.155,1.11),1)
for y in [YF+.42+i*.64 for i in range(8)]:
    detail.box((XL+.21,y,.26),(XL+.245,y+.038,1.11),1)
detail.box((XL+.30,YB-.22,1.10),(XR-.28,YB-.17,1.16),1)
detail.box((XL+.21,YF+.27,1.10),(XL+.27,YB-.27,1.16),1)
finish.box((XL+.35,YF+.46,2.90),(XL+.44,YB-.30,2.97),1)

# Airy, non-colliding exterior antenna lead and porcelain standoff detail.
for z in (2.55,2.77):
    detail.box((XL-.25,YB-.36,z),(XL+.06,YB-.29,z+.045),4)
detail.box((XL-.30,YB-.36,2.57),(XL-.265,YB-.325,3.28),4)

objects=[struct.object('S26_Annex_Continuous_Walls_Roof_Floor',.008),
         finish.object('S26_Annex_Studio_Finish'),
         detail.object('S26_Annex_Joinery_Copper_Radio_Details',.004)]

# Floor-anchor empties are excluded from GLB but remain in the editable .blend.
for name,location in [('CIN24_INSIDE',(0,0,0)),('CIN24_DOOR',(0,YF,0)),
                      ('CIN24_WINDOW_RAY',(-XR,.24,1.55)),('RADIO_DESK_ZONE',(2.65,1.92,0))]:
    obj=bpy.data.objects.new(name,None); obj.location=location
    bpy.context.collection.objects.link(obj)

bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'S26_PlayableRadioAnnex_v1.blend'))
bpy.ops.object.select_all(action='DESELECT')
for obj in objects: obj.select_set(True)
bpy.context.view_layer.objects.active=objects[0]
bpy.ops.export_scene.gltf(filepath=str(OUT/'S26_PlayableRadioAnnex_v1.glb'),
                          export_format='GLB',use_selection=True,
                          export_apply=True,export_image_format='AUTO')
print('ANNEX_DONE',len(objects),sum(len(o.data.polygons) for o in objects))
