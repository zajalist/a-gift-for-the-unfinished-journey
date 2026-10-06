"""Measure the imported-source station shell against protected ending anchors.

No editor connection or level edits. Segment intersections are two-sided source
geometry evidence; capsule dimensions are provisional until CDO readback.
"""
from pathlib import Path
import json
import math
import sys
import numpy as np

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'Tools/Tripo'))
import tripo_ingest as ti
SOURCE=ROOT/'SourceArt/Tripo/20261001/S26_radio_station_shell/S26_radio_station_shell_open_window_ue.glb'
OUT=ROOT/'Saved/Tripo/20261001/station_shell_fit'


class Surface:
    def __init__(self):
        doc,blob=ti.read_glb(SOURCE)
        instances=ti._mesh_instances(doc);assert len(instances)==1
        mesh,xf=instances[0];prim=doc['meshes'][mesh]['primitives'][0]
        pos=ti.read_accessor(doc,blob,prim['attributes']['POSITION'])
        self.points=((pos@xf[:3,:3].T+xf[:3,3])*100)[:,[0,2,1]]
        ids=ti.read_accessor(doc,blob,prim['indices']).astype(int).reshape(-1,3)
        self.tris=self.points[ids]
        self.lo=self.tris.min(1);self.hi=self.tris.max(1)

    def segment(self,start,end):
        a,b=np.array(start),np.array(end)
        mask=np.all(self.hi>=np.minimum(a,b)-1e-6,axis=1)&np.all(self.lo<=np.maximum(a,b)+1e-6,axis=1)
        tris=self.tris[mask]
        if not len(tris):return []
        direction=b-a;e1=tris[:,1]-tris[:,0];e2=tris[:,2]-tris[:,0]
        h=np.cross(np.broadcast_to(direction,e2.shape),e2);det=np.einsum('ij,ij->i',e1,h)
        valid=np.abs(det)>1e-9;inv=np.zeros_like(det);inv[valid]=1/det[valid]
        s=a-tris[:,0];u=inv*np.einsum('ij,ij->i',s,h)
        q=np.cross(s,e1);v=inv*np.einsum('j,ij->i',direction,q)
        t=inv*np.einsum('ij,ij->i',e2,q)
        found=t[valid&(u>=0)&(v>=0)&(u+v<=1)&(t>=0)&(t<=1)]
        return [a+direction*x for x in sorted(found)]


def main():
    surface=Surface();post=json.loads((ROOT/'Tools/Cinematics/probe_ending.json').read_text())['radio_post']
    yaw=math.radians(post['hut_yaw']);c,s=math.cos(yaw),math.sin(yaw)
    rot=np.array([[c,-s,0],[s,c,0],[0,0,1.]])
    local_door=np.array([126.,-58.,18.]);door=np.array(post['door'])
    report=[]
    for scale in ((1.5,1.25,1.1),(1.5,1.25,1.2),(1.5,1.25,1.25),(1.5,1.25,1.3)):
        scale=np.array(scale);origin=door-(local_door*scale)@rot.T
        def local(world):return ((np.array(world)-origin)@rot)/scale
        def world(point):return (point*scale)@rot.T+origin
        inside=local(post['inside']);collisions=[];tested=0
        # Root's actual BP_Saskarta_Traveller CDO readback:32cm /88cm.
        radius=32.;height=176.
        for part,(a,b) in enumerate(((post['entry_start'],post['door']),(post['door'],post['inside']))):
            for t in np.linspace(0,1,9):
                base=np.array(a)*(1-t)+np.array(b)*t
                # Radial slices alone can miss a horizontal ceiling. Include
                # the capsule's top pole along its complete vertical axis.
                hits=surface.segment(local(base+[0,0,.5]),local(base+[0,0,height]));tested+=1
                if hits:collisions.append(dict(part=part,t=round(float(t),3),height='vertical_pole',hit_world=world(hits[0]).round(3).tolist()))
                for z in (10.,35.,85.,height-35.,height-10.):
                    reach=radius if radius<=z<=height-radius else math.sqrt(radius**2-(radius-min(z,height-z))**2)
                    centre=base+[0,0,z]
                    for angle in np.arange(8)*math.pi/4:
                        end=centre+[reach*math.cos(angle),reach*math.sin(angle),0]
                        hits=surface.segment(local(centre),local(end));tested+=1
                        if hits:collisions.append(dict(part=part,t=round(float(t),3),height=z,hit_world=world(hits[0]).round(3).tolist()))
        floors=[]
        for name in ('entry_start','door','inside'):
            at=np.array(post[name]);hits=surface.segment(local(at+[0,0,60]),local(at-[0,0,50]))
            floors.append(dict(anchor=name,surfaces_z_cm=[round(float(world(p)[2]),3) for p in hits]))
        window=[]
        # Four real pane centres, measured after the intentional source cut.
        for x in (-28.5,23.):
            for z in (104.5,153.5):
                window.append(world(np.array([x,-175.,z])).round(3).tolist())
        row=dict(scale=scale.tolist(),origin_cm=origin.round(6).tolist(),yaw=post['hut_yaw'],inside_in_source_cm=inside.round(3).tolist(),
            capsule_assumption=dict(radius_cm=radius,height_cm=height),segments=tested,intersections=len(collisions),
            first_intersections=collisions[:20],floor_surfaces=floors,window_centres_world_cm=window,
            bounds_world_cm=[world(v).round(3).tolist() for v in surface.points[[surface.points[:,0].argmin(),surface.points[:,0].argmax()]]])
        report.append(row);print(json.dumps({k:row[k] for k in ('scale','origin_cm','inside_in_source_cm','intersections','floor_surfaces')}),flush=True)
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'source_fit.json').write_text(json.dumps(dict(source=str(SOURCE.relative_to(ROOT)),protected_anchors=post,candidates=report,
        limitations='Source triangle evidence; no Unreal collision/placement. Capsule dimensions and current foundation support require root readback.'),indent=2)+'\n')


if __name__=='__main__':main()
