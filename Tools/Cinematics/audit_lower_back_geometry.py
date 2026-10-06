"""Compare source body coverage in loaded animation samples / actual player pose.

The imported source vertices and weights were independently matched by the root
editor probe. This is geometry evidence, not proof of rendered material output.
"""
from pathlib import Path
import argparse
import json
import math
import numpy as np

import samyor_reveal as rig
import traveller_contacts as contacts

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'Saved/Verification/lower_back_audit_20261001'


def coverage(vertices,triangles,angle=0.,camera=None):
    # Source -> Unreal reflection reverses source polygon winding. This sign
    # agrees with authored normals on 36,828/37,145 triangles; 316 disagree.
    tris=vertices[triangles[:,[0,2,1]]]
    e1,e2=tris[:,1]-tris[:,0],tris[:,2]-tris[:,0]
    rows=[]
    for z in range(82,113):
        for x in range(-14,15,2):
            origin=np.array(camera if camera is not None else [x,-150,z+150*math.tan(math.radians(angle))])
            target=np.array([x,0,z]);direction=target-origin;direction/=np.linalg.norm(direction)
            h=np.cross(np.broadcast_to(direction,e2.shape),e2)
            det=np.einsum('ij,ij->i',e1,h)
            valid=det>1e-8
            inv=np.zeros_like(det);inv[valid]=1/det[valid]
            s=origin-tris[:,0];u=inv*np.einsum('ij,ij->i',s,h)
            q=np.cross(s,e1);v=inv*np.einsum('j,ij->i',direction,q)
            distance=inv*np.einsum('ij,ij->i',e2,q)
            hits=valid&(u>=0)&(v>=0)&(u+v<=1)&(distance>0)
            point=(origin+direction*distance[hits].min()).round(4).tolist() if hits.any() else None
            rows.append(dict(x=x,z=z,front_facing_hit=point))
    absent=[r for r in rows if r['front_facing_hit'] is None]
    return dict(camera_cm=None if camera is None else list(camera),down_angle_degrees=angle,
        ray_count=len(rows),missing_front_facing=len(absent),missing_samples=absent,
        centre_samples=[r for r in rows if r['x']==0 and 94<=r['z']<=101])


def actual_skin(data):
    points,entries,_=contacts.source_body();result=np.zeros_like(points)
    for bone,indices,weights,offsets in entries:
        row=data['bones'][bone];xf=row['component']
        result[indices]+=((offsets*np.array(xf[7:]))@contacts.rotation(xf[3:7]).T+xf[:3])*weights[:,None]
    xf=data['component_world']
    camera=(np.array(data['camera'][:3])-xf[:3])@contacts.rotation(xf[3:7])/xf[7:]
    return result,camera


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--readback',type=Path,action='append',default=[])
    args=parser.parse_args()
    _,_,triangles=contacts.source_body()
    poses={'reference':rig.REF_LOCAL}
    source=json.loads((ROOT/'Tools/Cinematics/traveller_pose_samples.json').read_text())['poses']
    for name,item in source.items():
        if 'FinalStill' not in name:poses[name+'@0']={b:(tuple(v[0][:3]),tuple(v[0][3:7]),tuple(v[0][7:])) for b,v in item['bones'].items()}
    actual=[]
    for path in args.readback:
        for line in path.read_text().splitlines():
            if line.startswith('TRAVELLER_POSE '):
                item=json.loads(line.split(' ',1)[1]);poses[item['clip']+'@'+str(round(item['at'],3))]={b:(tuple(v[0][:3]),tuple(v[0][3:7]),tuple(v[0][7:])) for b,v in item['bones'].items()}
            elif line.startswith('TRAVELLER_ACTUAL_SKIN_POSE '):
                item=json.loads(line.split(' ',1)[1]);vertices,camera=actual_skin(item)
                actual.append(dict(source=str(path),metadata=item,coverage=coverage(vertices,triangles,camera=camera)))
    results=[]
    for name,pose in poses.items():
        vertices=contacts.skin(pose)
        results.append(dict(pose=name,angles=[coverage(vertices,triangles,angle) for angle in (0.,20.,40.)]))
    OUT.mkdir(parents=True,exist_ok=True)
    report=dict(scope='Source-skinned surface coverage only. Dynamic player/BlendSpace coverage requires live pose readback; no visibility or material fix inferred.',
        source_mesh_vertices=20588,source_mesh_triangles=37145,poses=results,actual=actual)
    (OUT/'geometry-report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps([dict(pose=r['pose'],missing_by_angle=[a['missing_front_facing'] for a in r['angles']]) for r in results]))


if __name__=='__main__':main()
