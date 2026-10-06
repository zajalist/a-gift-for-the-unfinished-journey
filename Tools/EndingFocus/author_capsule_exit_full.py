"""Full 36-second offline contact draft. Root installs only after native survey.

The road-named coordinates are the capsule socket authoring frame, not the
runtime spline yaw. Every clip keys the real hierarchy, including root/hips.
Broad-envelope checks do not certify curved capsule triangle clearance.
"""
from pathlib import Path
import hashlib
import json
import math
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'Tools/Cinematics'), str(ROOT/'Tools/EndingFocus')]
import samyor_reveal as r
import samyor_final as m
import traveller_contacts as skin
import author_capsule_exit_contacts as tail

OUT = ROOT/'Saved/Verification/ending_focus_20261001/capsule_exit_full_v3'
FPS = 30
TRACKS = [b for b in r.ORDER if b != 'traveller_rig']
TRANSFORM = tail.transform_pose


def early(t, state):
    legacy = TRANSFORM(r.pose_at(t, state), r.body_xf(t))
    if t <= 13.5:
        return legacy
    q = r.qaxis((0,0,1), -90.)
    target = TRANSFORM(m.BASE, ((-310.,0.,r.G0),q))
    hips = r.keyed([(13.5, (-270.25,0.,53.7)), (17.2, (-285.,0.,88.)),
                    (19.8, (-303.,0.,115.)), (21.5, (-310.,0.,125.)),
                    (23.5, (-310.,-12.,131.)), (24.8, (-310.,-28.,131.)),
                    (26., (-310.,-48.,124.)), (27.5, (-310.,-52.,120.))], t)
    m.set_position(target, 'Hips', r.vadd(hips,(0,0,r.G0)))
    # Spine joints carry effort; the fixed root does not tip the whole body.
    effort = r.keyed([(13.5,18.),(17.2,20.),(19.8,13.),(21.5,7.),
                      (23.5,16.),(24.8,12.),(26.,8.),(27.5,8.)],t)
    for b,w in [('Spine',.4),('Spine1',.35),('Spine2',.25)]:
        world=r.fk(target)
        r.set_world_rot(target,world,b,r.qmul(r.qaxis((0,1,0),effort*w),world[b][1]))
    feet = {
        'Left': [(13.5,(-210.,-16.,42.)),(17.2,(-249.,-16.,42.)),
                 (19.8,(-271.,-16.,42.)),(21.5,(-278.,-18.,62.)),
                 (22.6,(-302.,-18.,161.)),(23.5,(-302.,-82.,160.)),
                 (25.,(-300.,-89.,112.)),(27.5,(-300.,-80.,62.))],
        'Right':[(13.5,(-210.,16.,42.)),(17.2,(-249.,16.,42.)),
                 (19.8,(-271.,16.,42.)),(23.,(-278.,12.,62.)),
                 (24.,(-292.,0.,164.)),(24.8,(-288.,-80.,160.)),
                 (26.,(-286.,-79.,106.)),(27.5,(-286.,-69.,62.))]}
    for side,keys in feet.items():
        goal=r.vadd(r.keyed(keys,t),(0,0,r.G0)); world=r.fk(target)
        pole=r.vadd(world[side+'UpLeg'][0],(60.,-35.,25.))
        m.limb_ik(target,side+'UpLeg',side+'Leg',side+'Foot',goal,pole)
        # Soles flatten on the pod floor. During each rim transfer the toe
        # rotates up by 18 degrees to clear the seam before lowering outside.
        lift=r.smooth((t-(21.5 if side=='Left' else 23.))/1.1)
        lower=r.smooth((t-(24. if side=='Left' else 25.))/1.5)
        boot=r.qmul(q,tail.BASE_WORLD[side+'Foot'][1])
        r.set_world_rot(target,r.fk(target),side+'Foot',
            r.qmul(r.qaxis((0,1,0),-18.*lift*(1.-lower)),boot))
    for side,key in [('Left','L'),('Right','R')]:
        # Preserve the actual latch/rim trajectory, but stop adding random
        # tremor to a load-bearing palm: measured contacts remain stationary.
        palm=r.hand_world(key,t)
        if t>=19.8:
            palm=r.keyed([(19.8,(-290.,-r.RIM_Y if key=='L' else r.RIM_Y,r.G0+r.rim_z(-290.))),
                         (21.5,(-290.,-r.RIM_Y if key=='L' else r.RIM_Y,r.G0+r.rim_z(-290.))),
                         (23.5,(-316. if key=='L' else -272.,-r.RIM_Y,r.G0+r.rim_z(-316. if key=='L' else -272.))),
                         (26.,(-322. if key=='L' else -282.,-r.RIM_Y,r.G0+r.rim_z(-322. if key=='L' else -282.)))],t)
        world=r.fk(target)
        m.limb_ik(target,side+'Arm',side+'ForeArm',side+'Hand',palm,
                  r.vadd(world[side+'Arm'][0],(25.,-50. if key=='L' else 50.,-20.)))
    # Keep the same pre-grip shaft position; its real tip needs native ground.
    w=r.fk(legacy)
    m.set_position(target,'staff011',w['staff011'][0])
    r.set_world_rot(target,r.fk(target),'staff011',w['staff011'][1])
    m.attach_prop(target,'recorder011','Hips',m.RECORDER_GRIP)
    for b in TRACKS:
        if 'Hand' in b and any(f in b for f in r.FINGERS):
            target[b]=legacy[b]
    # Acquire the new pelvis/boot solver while still inside. Once acquired,
    # whole-actor pitch and the old 151 cm drop never control anatomy again.
    a=r.smooth((t-13.5)/2.)
    return {b:(r.vlerp(legacy[b][0],target[b][0],a),
               r.qslerp(legacy[b][1],target[b][1],a),legacy[b][2]) for b in r.ORDER}


def complete_pose(t,state):
    if t<=27.5:return early(t,state)
    # Re-use the contact-led descent's target, acquiring from the corrected
    # seated boundary instead of blending back into the old leg-over pose.
    old=tail.rig.pose_at
    # This helper module shares r; use a constant local pose representing the
    # newly authored seat for the tail's legacy-side blend, without recursion.
    seat=early(27.5,{})
    local_seat=TRANSFORM(seat,r.xinv(r.body_xf(t)))
    try:
        tail.rig.pose_at=lambda at, st: local_seat
        return tail.road_pose(t,state)
    finally:tail.rig.pose_at=old


def main():
    assert not OUT.exists(), 'Preserve prior revision'
    OUT.mkdir(parents=True)
    state={}; poses=[]; measures=[]
    for i in range(1081):
        t=i/FPS; road=complete_pose(t,state)
        poses.append(TRANSFORM(road,r.xinv(r.body_xf(t))))
        if i%15==0:
            pts=skin.skin(road); w=r.fk(road)
            interior=(abs(pts[:,1])<=r.CAP_Y)&(pts[:,0]>=r.CAP_X[0])&(pts[:,0]<=r.CAP_X[1])
            measures.append(dict(t_s=t,body_min_cm=float(pts[:,2].min()),
                interior_min_cm=float(pts[interior,2].min()) if interior.any() else None,
                below_capsule_floor_vertices=int(((pts[:,2]<r.G0+r.CAP_FLOOR)&interior).sum()),
                hips_cm=w['Hips'][0],boots_cm={s:w[s+'Foot'][0] for s in ('Left','Right')}))
    for legacy,t0,t1 in r.CLIPS:
        name=legacy+'_FullContactV3'; folder=OUT/name;folder.mkdir()
        pp=poses[round(t0*FPS):round(t1*FPS)+1]
        (folder/'00_create.py').write_text(r.CREATE.format(dir=r.ANIM_DIR,name=name,skel=r.SKEL,fps=FPS,n=len(pp)-1))
        for off in range(0,len(TRACKS),8):
            data=[]
            for b in TRACKS[off:off+8]:
                kk=[p[b] for p in pp]
                data.append((b,[list(k[0]) for k in kk],[list(k[1]) for k in kk],list(kk[0][2])))
            (folder/f'10_keys_{off//8:02d}.py').write_text(r.KEYS.format(dir=r.ANIM_DIR,name=name,data=json.dumps(data)))
        (folder/'90_save.py').write_text(r.SAVEA.format(dir=r.ANIM_DIR,name=name))
    report=dict(status='OFFLINE_FULL_BODY_CANDIDATE_NOT_RENDER_ACCEPTED',tracks=len(TRACKS),frames=1081,
        duration_s=36.,samples=measures,exact_timings=[list(x) for x in r.CLIPS],
        floor_envelope_failure_samples=[x['t_s'] for x in measures if x['below_capsule_floor_vertices']],
        requires='Actual capsule socket frame, shell triangles, tread normals, supported outside landing and full pose readback before install')
    (OUT/'measurements.json').write_text(json.dumps(report,indent=2))
    (OUT/'manifest.json').write_text(json.dumps({str(p.relative_to(OUT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in OUT.rglob('*') if p.is_file()},indent=2))
    print(json.dumps(dict(out=str(OUT),tracks=len(TRACKS),files=len(list(OUT.rglob('*.py'))),floor_failures=report['floor_envelope_failure_samples'])))


if __name__=='__main__':main()
