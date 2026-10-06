"""One bounded offline authoring round for actual surveyed side-hatch contacts."""
from pathlib import Path
import sys,json,hashlib,math
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'Tools/Cinematics'),str(ROOT/'Tools/EndingFocus')]
import samyor_reveal as r
import samyor_final as m
import author_capsule_exit_contacts as c
import author_supported_exit_tail as tail
import emit_inline_exit_imports as inline
import traveller_contacts as body
OUT=ROOT/'Saved/Verification/ending_focus_20261001/side_exit_supported_v7'
SOURCE=ROOT/'Saved/Verification/ending_focus_20261001/side_exit_review_v4'
SUPPORT_FILE=ROOT/'Saved/Verification/ending_focus_20261001/side_exit_actual_v6/actual_supports.json'
SUPPORTS=json.loads(SUPPORT_FILE.read_text())['supports']
SOURCES={n:json.loads((SOURCE/(n+'.json')).read_text()) for n in
         ['A_Samyor_PullUp_SideContactV4_ReviewOnly','A_Samyor_LegOver_SideContactV4_ReviewOnly']}

def source_pose(t):
    name,start=('A_Samyor_PullUp_SideContactV4_ReviewOnly',13.5) if t<21.5 else ('A_Samyor_LegOver_SideContactV4_ReviewOnly',21.5)
    data=SOURCES[name];ix=min(data['frames'],round((t-start)*30));p=dict(m.BASE)
    p.update({b:(tuple(P[ix]),tuple(Q[ix]),tuple(S)) for b,P,Q,S in data['tracks']})
    return c.transform_pose(p,r.body_xf(t))

START=source_pose(27.5)

def early_pose(t):
    if t>=20.5:return source_pose(t)
    raw=c.transform_pose(r.pose_at(t,{}),r.body_xf(t)) if t<=13.5 else source_pose(t)
    w=r.fk(raw)
    lift=r.keyed([(0.,31.),(13.5,31.),(14.5,12.),(15.5,12.),(17.2,12.),(19.5,6.),(20.5,0.),(21.5,0.)],t)
    p=c.transform_pose(raw,((0.,0.,lift),(0.,0.,0.,1.)))
    fold=r.keyed([(13.5,0.),(14.5,10.),(15.5,22.),(17.2,0.),(21.5,0.)],t) if t>=13.5 else 0.
    for bone,weight in [('Spine',.4),('Spine1',.35),('Spine2',.25)]:
        if fold:r.set_world_rot(p,r.fk(p),bone,r.qmul(r.qaxis((1.,0.,0.),fold*weight),r.fk(p)[bone][1]))
    # Contact hands follow actual latch/leaf rather than the lifted torso. The
    # resting hand rises with his supported body before and after the contact.
    for side in ['Left','Right']:
        contact=(r.smooth((t-2.2)/1.4)*(1.-r.smooth((t-10.9)/1.1))) if side=='Left' else (r.smooth((t-7.2)/1.)*(1.-r.smooth((t-10.9)/1.1)))
        if t>=13.5:contact=r.smooth((t-13.5)/1.)
        if contact<=0.:continue
        target=r.vadd(w[side+'Hand'][0],(0,0,lift*(1-contact)))
        if side=='Left' and t<13.5:target=r.vadd(target,(0.,5.*contact,-3.*contact))
        if side=='Right' and t<13.5:target=r.vadd(target,(0.,-5.*contact,0.))
        if t>=13.5:
            previous=c.transform_pose(r.pose_at(13.5,{}),r.body_xf(13.5))
            previous=r.vadd(r.fk(previous)[side+'Hand'][0],(0.,0.,31.))
            target=r.vlerp(previous,(-292. if side=='Left' else -289.,-r.RIM_Y,106.),contact)
        world=r.fk(p)
        m.limb_ik(p,side+'Arm',side+'ForeArm',side+'Hand',target,
                  r.vadd(world[side+'Arm'][0],(35.,35.,-10.)))
        r.set_world_rot(p,r.fk(p),side+'Hand',w[side+'Hand'][1])
    extra=r.keyed([(13.5,0.),(14.5,30.),(15.5,18.),(17.2,20.),(19.5,0.),(21.5,0.)],t) if t>13.5 else 0.
    if extra>0.:
        for side in ['Left','Right']:
            target=r.vadd(w[side+'Foot'][0],(0,0,lift+extra))
            floor=r.keyed([(13.5,87.4),(14.,95.),(14.5,95.),(15.5,88.),(17.2,84.),(19.5,0.),(21.5,0.)],t)
            target=(target[0],target[1],max(target[2],floor))
            world=r.fk(p)
            m.limb_ik(p,side+'UpLeg',side+'Leg',side+'Foot',target,
                      r.vadd(world[side+'UpLeg'][0],(0.,r.keyed([(13.5,20.),(14.5,20.),(15.5,-20.)],t),40.)))
            earlier=r.fk(c.transform_pose(r.pose_at(13.5,{}),r.body_xf(13.5)))[side+'Foot'][1]
            r.set_world_rot(p,r.fk(p),side+'Foot',r.qslerp(earlier,w[side+'Foot'][1],r.smooth((t-14.5)/1.)))
    m.set_position(p,'staff011',w['staff011'][0]);r.set_world_rot(p,r.fk(p),'staff011',w['staff011'][1])
    m.attach_prop(p,'recorder011','Hips',m.RECORDER_GRIP)
    if t>=19.5:
        blend=r.smooth((t-19.5)/1.)
        p={b:(r.vlerp(p[b][0],raw[b][0],blend),r.qslerp(p[b][1],raw[b][1],blend),raw[b][2]) for b in r.ORDER}
    return p

def emit_clip(name,start,end,fn,target_dir=None):
    poses=[c.transform_pose(fn(start+i/30.),r.xinv(r.body_xf(start+i/30.))) for i in range(round((end-start)*30)+1)]
    tracks=[]
    for b in r.ORDER:
        if b=='traveller_rig':continue
        keys=[p[b] for p in poses]
        tracks.append([b,[[round(v,6) for v in k[0]] for k in keys],[[round(v,7) for v in k[1]] for k in keys],[round(v,6) for v in keys[0][2]]])
    target=(target_dir or OUT)/(name+'.json');target.write_text(json.dumps(dict(name=name,frames=len(poses)-1,start_s=start,end_s=end,tracks=tracks),separators=(',',':')))
    return dict(name=name,start_s=start,end_s=end,frames=len(poses)-1,bone_tracks=len(tracks),sha256=hashlib.sha256(target.read_bytes()).hexdigest())

def main():
    assert not OUT.exists(),'Preserve prior outcome'
    OUT.mkdir(parents=True)
    samples=[]
    for i in range(256):
        t=27.5+i/30.;p=tail.pose(t,SUPPORTS,START);w=r.fk(p)
        if i%15==0 or i==255:
            grip=r.xcompose(w['RightHand'][:2],c.GRIP)
            tip=r.vadd(w['staff011'][0],r.qrot(w['staff011'][1],c.TIP_FROM_ORIGIN))
            feet={}
            for side in ['Left','Right']:
                target,phase,normal=tail.foot_trajectory(SUPPORTS,side,t)
                points=body.skin(p)
                feet[side]=dict(ankle_cm=w[side+'Foot'][0],target_cm=target,error_cm=r.vlen(r.vsub(w[side+'Foot'][0],target)))
            samples.append(dict(t_s=t,hips_cm=w['Hips'][0],feet=feet,staff_tip_cm=tip,
                staff_point_error_cm=r.vlen(r.vsub(tip,r.vadd(tuple(SUPPORTS['staff_new']['point_cm']),(0,0,.4)))),
                grip_error_cm=r.vlen(r.vsub(grip[0],w['staff011'][0])),body_min_z_cm=float(points[:,2].min())))
    clips=[emit_clip('A_Samyor_StaffStand_SideSupportedV7_ReviewOnly',27.5,36.,lambda t:tail.pose(t,SUPPORTS,START))]
    inline.emit(OUT,OUT/'inline','_InlineV7')
    boundary=r.fk(START)
    report=dict(status='OFFLINE_AUTHORED_NOT_RENDER_ACCEPTED',clips=clips,support_sha256=hashlib.sha256(SUPPORT_FILE.read_bytes()).hexdigest(),
                boundary='Exact saved V4 LegOver final local pose; no reconstructed side.pose boundary',
                start_pose_world={b:boundary[b] for b in ['Hips','LeftFoot','RightFoot','RightHand','staff011']},
                staff_planted_window_s=[28.3,31.4],staff_gripped_window_s=[29.8,36.],
                sample_measurements=samples,lateral_boot_corners_surveyed=False,production_accepted=False)
    (OUT/'contacts.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(dict(out=str(OUT),clips=len(clips),samples=len(samples),max_planted_grip_error_cm=max(s['grip_error_cm'] for s in samples if 29.8<=s['t_s']<=31.4),max_ankle_error_cm=max(f['error_cm'] for s in samples if s['t_s']>=28.3 for f in s['feet'].values()))))

def emit_early():
    import measure_capsule_segments_fast as geometry
    dest=OUT/'early';assert not dest.exists(),'Preserve prior outcome';dest.mkdir()
    sw=geometry.Sweep();rows=[]
    for t in [0.,2.2,3.6,5.,7.,8.2,9.,10.,11.,12.,13.5,14.,14.5,15.,15.5,16.3,17.2,18.3,19.5,20.,20.5,21.5]:
        row=sw.measure(t,early_pose(t));rows.append(row)
        print('EARLY_GEOMETRY',t,row['intersections'],flush=True)
    (dest/'geometry_early.json').write_text(json.dumps(rows,indent=2))
    assert not any(x['intersections'] for x in rows),'Unresolved geometry: preserve receipts, refuse inline packet'
    clips=[]
    for name,start,end in [('A_Samyor_ReachLatch_SideSupportedV7_ReviewOnly',0.,7.),('A_Samyor_PushLid_SideSupportedV7_ReviewOnly',7.,13.5),('A_Samyor_PullUp_SideSupportedV7_ReviewOnly',13.5,21.5)]:
        clips.append(emit_clip(name,start,end,early_pose,dest))
    inline.emit(dest,dest/'inline','_InlineV7')
    (dest/'receipt.json').write_text(json.dumps(dict(status='SOURCE_CLEARANCE_REVIEW_NOT_RENDER_ACCEPTED',clips=clips,
        sampled_finite_edge_crossings=0,geometry_sample_times=[x['t_s'] for x in rows],
        exact_saved_v4_boundary_s=21.5,production_accepted=False,
        limitation='Cushion contact, finger contacts, continuous motion and imported skin need rendered review; sampled zero crossings is not full sweep certification'),indent=2))
    print('EARLY_PACKET',dest,flush=True)

if __name__=='__main__':
    emit_early() if '--early' in sys.argv else main()
