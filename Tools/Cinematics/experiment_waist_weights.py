"""Offline hypotheses only; never changes an FBX or Unreal asset."""
from pathlib import Path
import json
import numpy as np
import matplotlib.pyplot as plt
import traveller_contacts as contacts
import samyor_reveal as rig
from audit_lower_back_geometry import coverage
from render_lower_back_geometry import draw, read_pose

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'Saved/Verification/lower_back_audit_20261001'


def transfer_leg_weights(pose, start, end):
    points, entries, _ = contacts.source_body()
    original = contacts.skin(pose)
    world = rig.fk(pose)
    hips = rig.REF_W['Hips']
    offsets = ((points-hips[0]) @ contacts.rotation(hips[1]))/hips[2]
    hp,hq,hs = world['Hips']
    hip_points = (offsets*hs) @ contacts.rotation(hq).T+hp
    alpha = np.clip((points[:,2]-start)/(end-start),0,1)
    alpha *= (np.abs(points[:,0])<22)&(np.abs(points[:,1])<22)
    alpha = alpha*alpha*(3-2*alpha)
    changed = np.zeros(len(points))
    for bone,indices,weights,local in entries:
        if bone not in ('LeftUpLeg','RightUpLeg'):
            continue
        bp,bq,bs = world[bone]
        before=(local*bs) @ contacts.rotation(bq).T+bp
        amount=weights*alpha[indices]
        original[indices]+=(hip_points[indices]-before)*amount[:,None]
        changed[indices]+=amount
    return original, changed


def main():
    _,_,triangles=contacts.source_body()
    samples=[]
    for name in ('01_idle_pose.readback.txt','02_idle_pose.readback.txt'):
        data,pose=read_pose(OUT/name)
        samples.append((data['clip']+'@'+str(data['at']),pose))
    variants=[('original',None),('leg-to-hips 84..96',(84,96)),
              ('leg-to-hips 90..102',(90,102)),('leg-to-hips 80..110',(80,110))]
    fig,axes=plt.subplots(len(samples),len(variants),figsize=(18,8),layout='constrained')
    report=[]
    for row,(name,pose) in enumerate(samples):
        for col,(label,span) in enumerate(variants):
            points,changed=transfer_leg_weights(pose,*span) if span else (contacts.skin(pose),np.zeros(20588))
            counts=[coverage(points,triangles,angle)['missing_front_facing'] for angle in (20,40)]
            item=dict(pose=name,variant=label,missing20_40=counts,changed_vertices=int(np.count_nonzero(changed)),max_transferred_weight=float(changed.max()))
            report.append(item);print(json.dumps(item),flush=True)
            draw(axes[row,col],points,triangles)
            axes[row,col].set_ylim(63,100)
            axes[row,col].set_title(name+'\n'+label+' missing '+str(counts))
    (OUT/'weight-hypothesis-report.json').write_text(json.dumps(report,indent=2)+'\n')
    fig.savefig(OUT/'weight-hypotheses.png',dpi=150)


if __name__=='__main__':main()
