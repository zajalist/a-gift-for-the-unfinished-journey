"""Validate the derivative's actual weights against captured poses and blends."""
from pathlib import Path
import json
import numpy as np
import traveller_contacts as contacts
import samyor_reveal as rig
from audit_lower_back_geometry import coverage
from render_lower_back_geometry import read_pose
from repair_traveller_waist_weights import DEST, parse_binary

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'Saved/Verification/lower_back_audit_20261001'


def derivative_entries():
    points,entries,_=contacts.source_body()
    _,nodes,_,_=parse_binary(DEST.read_bytes())
    objects=next(n for n in nodes if n.name==b'Objects')
    by_name={n.values[1].split('\x00')[0].removeprefix('mixamorig:'):n for n in objects.children
             if n.name==b'Deformer' and len(n.values)>2 and n.values[2]=='Cluster'
             and n.values[1].split('\x00')[0].removeprefix('mixamorig:') in ('Hips','LeftUpLeg','RightUpLeg')}
    # Several meshes share bones: use only the known modified body clusters.
    targets=set()
    for path in json.loads((DEST.parent/'waist_weights_manifest.json').read_text())['changed_raw_property_paths']:
        targets.add(path[2])
    by_name={objects.children[i].values[1].split('\x00')[0].removeprefix('mixamorig:'):objects.children[i] for i in targets}
    result=[]
    for bone,indices,weights,offsets in entries:
        if bone in by_name:
            node=by_name[bone]
            indices=node.child('Indexes').values[0]
            weights=node.child('Weights').values[0]
            ref=rig.REF_W[bone]
            offsets=((points[indices]-ref[0]) @ contacts.rotation(ref[1]))/ref[2]
        result.append((bone,indices,weights,offsets))
    return result


def skin(pose,entries):
    world=rig.fk(pose)
    result=np.zeros((20588,3))
    for bone,indices,weights,offsets in entries:
        p,q,s=world[bone]
        result[indices]+=((offsets*s) @ contacts.rotation(q).T+p)*weights[:,None]
    return result


def samples():
    result={'reference':rig.REF_LOCAL}
    source=json.loads((ROOT/'Tools/Cinematics/traveller_pose_samples.json').read_text())['poses']
    for name,item in source.items():
        if 'FinalStill' not in name:
            result[name+'@0']={b:(tuple(v[0][:3]),tuple(v[0][3:7]),tuple(v[0][7:])) for b,v in item['bones'].items()}
    for path in sorted(OUT.glob('0*_idle_pose.readback.txt')):
        item,pose=read_pose(path)
        result[item['clip']+'@'+str(round(item['at'],3))]=pose
    return result


def main():
    points,_,triangles=contacts.source_body()
    entries=derivative_entries()
    source=samples()
    bind_error=float(np.linalg.norm(skin(rig.REF_LOCAL,entries)-contacts.skin(rig.REF_LOCAL),axis=1).max())
    assert bind_error<1e-10
    results=[]
    for name,pose in source.items():
        repaired=skin(pose,entries)
        counts=[coverage(repaired,triangles,angle)['missing_front_facing'] for angle in (0,20,40)]
        item=dict(pose=name,missing0_20_40=counts,
            lowest_body_change_cm=float(repaired[:,2].min()-contacts.skin(pose)[:,2].min()))
        results.append(item);print(json.dumps(item),flush=True)
    blend_results=[]
    rest=source['A_Traveller_Rest@3.0']
    walk=source['A_Traveller_SlowWalk@1.0']
    for alpha in (.25,.5,.75):
        pose={bone:(rig.vlerp(rest[bone][0],walk[bone][0],alpha),
                    rig.qslerp(rest[bone][1],walk[bone][1],alpha),
                    rig.vlerp(rest[bone][2],walk[bone][2],alpha)) for bone in rest}
        counts=[coverage(skin(pose,entries),triangles,angle)['missing_front_facing'] for angle in (0,20,40)]
        item=dict(synthetic_rest_walk_local_blend=alpha,missing0_20_40=counts)
        blend_results.append(item);print(json.dumps(item),flush=True)
    report=dict(bind_pose_max_vertex_delta_cm=bind_error,poses=results,synthetic_blends=blend_results,
                limits='Captured actual idle animation poses, plus explicit local TRS blends; live BlendSpace timing/rendered material still requires editor acceptance.')
    (OUT/'repaired-geometry-report.json').write_text(json.dumps(report,indent=2)+'\n')
    assert all(not any(row['missing0_20_40']) for row in results+blend_results),report


if __name__=='__main__':main()
