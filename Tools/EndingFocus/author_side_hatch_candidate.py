"""Source draft for the real side opening; never auto-installed.

Carrier FBX hatch is a side panel, not the roof. The former up-and-over solver
raises the head through the fixed shell. This draft folds and swivels toward the
real opening, keeping the upper body low until outside. Exact curved crossings
are measured separately and any nonzero crossing rejects the production draft.
"""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'Tools/Cinematics'),str(ROOT/'Tools/EndingFocus')]
import samyor_reveal as r
import samyor_final as m
import author_capsule_exit_contacts as old


def pose(t,state,supports=None):
    legacy=old.transform_pose(r.pose_at(t,state),r.body_xf(t))
    if supports is not None:
        support=supports['staff_new']
        assert support.get('actual_native_contact') is True and support.get('footprint_reviewed') is True
        tip=r.vadd(tuple(support['point_cm']),(0,0,.4))
        shaft_q=r.qmul(r.qaxis((0,0,1),-180.),old.BASE_WORLD['staff011'][1])
        origin=r.vsub(tip,r.qrot(shaft_q,old.TIP_FROM_ORIGIN))
        m.set_position(legacy,'staff011',origin)
        r.set_world_rot(legacy,r.fk(legacy),'staff011',shaft_q)
    if t<=13.5:return legacy
    yaw=r.keyed([(13.5,-90.),(17.2,-150.),(19.8,-180.),(27.5,-180.)],t)
    q=r.qaxis((0,0,1),yaw)
    p=old.transform_pose(m.BASE,((-270.,0.,r.G0),q))
    hips=r.keyed([(13.5,(-270.,0.,54.)),(17.2,(-270.,0.,65.)),
                  (19.8,(-270.,-12.,75.)),(21.5,(-270.,-30.,82.)),
                  (23.5,(-270.,-48.,82.)),(26.,(-270.,-90.,88.)),
                  (27.5,(-270.,-105.,89.))],t)
    m.set_position(p,'Hips',r.vadd(hips,(0,0,r.G0)))
    fold=r.keyed([(13.5,25.),(17.2,38.),(21.5,50.),(23.5,35.),(26.,15.),(27.5,8.)],t)
    # Body +Y becomes road -Y after the swivel. Flexion tips the upper body
    # toward the opening while leaving the pelvis/legs independently supported.
    for b,w in [('Spine',.4),('Spine1',.35),('Spine2',.25)]:
        world=r.fk(p)
        r.set_world_rot(p,world,b,r.qmul(r.qaxis((1,0,0),fold*w),world[b][1]))
    for side,x,delay in [('Left',-285.,0.),('Right',-255.,1.6)]:
        feet=r.keyed([(13.5,(x,-5.,52.)),(17.2,(x,-15.,52.)),
                     (19.8+delay,(x,-28.,86.)),(21.5+delay,(x,-78.,86.)),
                     (25.+delay,(x,-110.,12.)),(27.5,(x,-118.,12.))],t)
        world=r.fk(p)
        m.limb_ik(p,side+'UpLeg',side+'Leg',side+'Foot',r.vadd(feet,(0,0,r.G0)),
                  r.vadd(world[side+'UpLeg'][0],(0.,-60.,35.)))
        r.set_world_rot(p,r.fk(p),side+'Foot',r.qmul(q,old.BASE_WORLD[side+'Foot'][1]))
    for side,x in [('Left',-292.),('Right',-289.)]:
        w=r.fk(p)
        target=(x,-r.RIM_Y,r.G0+106.)
        m.limb_ik(p,side+'Arm',side+'ForeArm',side+'Hand',target,
                  r.vadd(w[side+'Arm'][0],(0.,-45.,-20.)))
    w=r.fk(legacy)
    m.set_position(p,'staff011',w['staff011'][0]);r.set_world_rot(p,r.fk(p),'staff011',w['staff011'][1])
    m.attach_prop(p,'recorder011','Hips',m.RECORDER_GRIP)
    a=r.smooth((t-13.5)/2.)
    return {b:(r.vlerp(legacy[b][0],p[b][0],a),r.qslerp(legacy[b][1],p[b][1],a),legacy[b][2]) for b in r.ORDER}
