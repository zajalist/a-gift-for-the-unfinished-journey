"""Source triangle/body-edge intersections, bounded offline CPU authoring.

This is geometry measurement, not an automation test or installed-mesh proof.
The imported FBX shell source is mapped into the measured capsule frame.
"""
import os
os.environ['OPENBLAS_NUM_THREADS']='1'
os.environ['OMP_NUM_THREADS']='1'
from pathlib import Path
import json
import hashlib
import sys
import numpy as np
import trimesh

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'Tools/Cinematics'),str(ROOT/'Tools/ModelReview'),str(ROOT/'Tools/EndingFocus')]
import samyor_reveal as r
import traveller_contacts as body
import author_capsule_exit_full as draft
from fbx_reader import read_fbx

OUT=ROOT/'Saved/Verification/ending_focus_20261001/capsule_triangles_v4'
SOURCE=ROOT/'SourceArt/Characters/Carrier/carrier01_full.fbx'
MODELS=('full_pod_capsule01','full_pod_capsule_panel','full_pod_hatch01','full_pod_lining01','full_pod_padding01')


def pieces():
    scene=read_fbx(str(SOURCE)); out=[]
    for geometry in scene.geometries.values():
        model=scene.model_of_geometry(geometry.id)
        if model.name not in MODELS:continue
        # FBX model 180-degree Z / 100 cm scale, UE handedness and imported
        # mesh -90 yaw combine to (-sourceY,-sourceX,sourceZ)*100.
        assert abs(model.rotation[2]-180.)<.001 and np.max(np.abs(model.scaling-100.))<.001
        p=geometry.vertices[:,[1,0,2]]*[-100.,-100.,100.]
        p[:,2]+=r.G0
        idx,_,_=geometry.polygons();corners,_=geometry.triangulate()
        out.append((model.name,p,idx[corners]))
    assert len(out)==len(MODELS)
    return out


def at_time(parts,t):
    verts=[];faces=[]; labels=[];base=0
    for label,p,f in parts:
        pp=p.copy()
        if label=='full_pod_hatch01':
            pp=np.array([r.vadd(r.SC['hinge'],r.qrot(r.qaxis((0,-1,0),r.lid_angle(t)),r.vsub(x,r.SC['hinge']))) for x in pp])
        verts.append(pp);faces.append(f+base);labels.extend([label]*len(f));base+=len(pp)
    return trimesh.Trimesh(vertices=np.concatenate(verts),faces=np.concatenate(faces),process=False),labels


def measure(parts,t):
    road=draft.complete_pose(t,{})
    vertices=body.skin(road);_,_,faces=body.source_body()
    edges=np.unique(np.sort(np.concatenate([faces[:,[0,1]],faces[:,[1,2]],faces[:,[2,0]]]),axis=1),axis=0)
    origins=vertices[edges[:,0]];delta=vertices[edges[:,1]]-origins
    length=np.linalg.norm(delta,axis=1);valid=length>1e-5
    origins=origins[valid];directions=delta[valid]/length[valid,None];length=length[valid];edges=edges[valid]
    mesh,labels=at_time(parts,t)
    # Exact ray/triangle intersections, clipped to each finite body edge.
    loc,rays,tris=mesh.ray.intersects_location(origins,directions,multiple_hits=True)
    along=np.einsum('ij,ij->i',loc-origins[rays],directions[rays])
    crossing=(along>.02)&(along<length[rays]-.02)
    loc=loc[crossing];rays=rays[crossing];tris=tris[crossing]
    grouping={}
    for label in MODELS:
        select=np.array([labels[k]==label for k in tris],dtype=bool)
        grouping[label]=dict(intersections=int(select.sum()),
            unique_body_edges=int(len(np.unique(rays[select]))),
            samples=[dict(point_cm=x.tolist(),body_edge=edges[rr].tolist(),source_triangle=int(tr))
                     for x,rr,tr in zip(loc[select][:12],rays[select][:12],tris[select][:12])])
    return dict(t_s=t,lid_angle_deg=r.lid_angle(t),body_edges=len(edges),
        source_triangles=len(mesh.faces),intersections=int(len(loc)),by_mesh=grouping)


def main():
    assert not OUT.exists(),'Preserve previous geometry measurement'
    OUT.mkdir(parents=True);parts=pieces()
    inventory=[dict(model=n,vertices=len(p),triangles=len(f),min_cm=p.min(axis=0).tolist(),max_cm=p.max(axis=0).tolist()) for n,p,f in parts]
    (OUT/'source_inventory.json').write_text(json.dumps(dict(source=str(SOURCE),sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),meshes=inventory),indent=2))
    # Four critical earlier poses first. Each is a source authoring diagnostic;
    # collisions are not concealed by dropping tiny intersections from report.
    for t in [19.5,21.5,23.5,24.8,27.5]:
        row=measure(parts,t);(OUT/f'pose_{t:04.1f}.json').write_text(json.dumps(row,indent=2))
        print(json.dumps(dict(t_s=t,intersections=row['intersections'],meshes={n:x['intersections'] for n,x in row['by_mesh'].items()})),flush=True)


if __name__=='__main__':main()
