"""Author27.5–36s from actual capsule-frame supports; missing data is fatal.

Offline only. Supports must come from the root's actual native survey, including
normals and heel/toe footprint checks. No source-heightmap or flat-floor default.
"""
from pathlib import Path
import math
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'Tools/Cinematics'),str(ROOT/'Tools/EndingFocus')]
import samyor_reveal as r
import samyor_final as m
import author_side_hatch_candidate as side
import author_capsule_exit_contacts as contact

REQUIRED=('left_initial','right_initial','left_mid','right_mid','left_final','right_final','staff_new')


def validate(supports):
    assert all(n in supports for n in REQUIRED),'Actual capsule-frame foot/staff supports are required'
    for name in REQUIRED:
        support=supports[name]
        assert support.get('actual_native_contact') is True,name+' must be a native Landscape/physical footing hit'
        assert support.get('footprint_reviewed') is True,name+' heel/toe/normal review missing'
        assert len(support['point_cm'])==3 and len(support['normal'])==3
        assert all(math.isfinite(x) for x in support['point_cm']+support['normal'])
        assert support['normal'][2]>.94,name+' needs actual foot tilt authoring for this steep landing'
    return supports


def foot_key(supports,name):
    return r.vadd(tuple(supports[name]['point_cm']),r.vmul(tuple(supports[name]['normal']),11.9))


def foot_trajectory(supports,side_name,t):
    prefix=side_name.lower(); a=foot_key(supports,prefix+'_initial')
    b=foot_key(supports,prefix+'_mid'); c=foot_key(supports,prefix+'_final')
    # Two deliberate transfers after the rise; the other foot stays on its
    # measured patch while the airborne one translates/turns above the terrain.
    windows=((31.4,32.8),(34.2,35.1)) if side_name=='Left' else ((32.8,34.2),(35.1,36.0))
    current=a
    normal=tuple(supports[prefix+'_initial']['normal'])
    for (start,end),target,next_name in zip(windows,(b,c),(prefix+'_mid',prefix+'_final')):
        next_normal=tuple(supports[next_name]['normal'])
        if t<start:return current,0.,normal
        if t<=end:
            u=r.smooth((t-start)/(end-start))
            p=r.vlerp(current,target,u)
            return r.vadd(p,(0,0,8.*math.sin(math.pi*u))),u,r.vnorm(r.vlerp(normal,next_normal,u))
        current=target;normal=next_normal
    return c,1.,normal


def pose(t,supports,start_pose=None):
    validate(supports)
    assert 27.5<=t<=36.
    start=start_pose if start_pose is not None else side.pose(27.5,{},supports)
    if t==27.5:return start
    yaw=r.keyed([(27.5,-180.),(31.4,-180.),(33.2,-130.),(35.5,-90.),(36.,-90.)],t)
    q=r.qaxis((0,0,1),yaw)
    p=contact.transform_pose(m.BASE,((-270.,-105.,0.),q))
    left,_,left_normal=foot_trajectory(supports,'Left',t)
    right,_,right_normal=foot_trajectory(supports,'Right',t)
    # Preserve the existing Rise prompt at30.5: staff is acquired first and
    # pelvis remains lowered until that cue. No early upright stand.
    xy=r.keyed([(27.5,(-270.,-105.,0.)),(31.4,(-270.,-105.,0.)),
                (32.8,(-296.,-118.,0.)),(34.2,(-329.,-111.,0.)),
                (35.55,(-350.,-110.,0.)),(36.,(-356.5,-110.,0.))],t)
    ground=.5*((left[2]-11.9)+(right[2]-11.9))
    height=r.keyed([(27.5,77.),(29.8,77.),(30.5,77.),(31.4,89.),(36.,89.)],t)
    m.set_position(p,'Hips',(xy[0],xy[1],ground+height))
    # Pelvis settles to keep every real limb reachable; it never drags the
    # opposite planted boot to follow the actor's turning root.
    for name,target,normal in [('Left',left,left_normal),('Right',right,right_normal)]:
        w=r.fk(p);a,b,c=[w[name+n][0] for n in ('UpLeg','Leg','Foot')]
        reach=r.vlen(r.vsub(b,a))+r.vlen(r.vsub(c,b))-.1
        dx=a[0]-target[0];dy=a[1]-target[1]
        assert dx*dx+dy*dy<reach*reach,'Landing XY exceeds anatomical leg reach'
        lower=a[2]-target[2]-math.sqrt(reach*reach-dx*dx-dy*dy)
        if lower>0:m.set_position(p,'Hips',r.vadd(w['Hips'][0],(0,0,-lower)))
    for name,target,normal in [('Left',left,left_normal),('Right',right,right_normal)]:
        w=r.fk(p)
        m.limb_ik(p,name+'UpLeg',name+'Leg',name+'Foot',target,
                  r.vadd(w[name+'UpLeg'][0],(0.,-60.,25.)))
        # Turn the boot only while it is airborne. Contacts keep their actual
        # prior planted orientation; a continuous root turn cannot twist soles.
        turn=0.
        if name=='Left':turn=r.smooth((t-31.4)/1.4)*.55+r.smooth((t-34.2)/.9)*.45
        else:turn=r.smooth((t-32.8)/1.4)*.55+r.smooth((t-35.1)/.9)*.45
        fq=r.qaxis((0,0,1),-180.+90.*turn)
        fq=r.qmul(r.qfromto((0,0,1),normal),fq)
        r.set_world_rot(p,r.fk(p),name+'Foot',r.qmul(fq,contact.BASE_WORLD[name+'Foot'][1]))
    fold=r.keyed([(27.5,16.),(29.8,21.),(30.5,21.),(31.4,8.),(36.,0.)],t)
    for b,weight in [('Spine',.4),('Spine1',.35),('Spine2',.25)]:
        w=r.fk(p);axis=r.qrot(q,(1.,0.,0.))
        r.set_world_rot(p,w,b,r.qmul(r.qaxis(axis,-fold*weight),w[b][1]))
    tip=tuple(supports['staff_new']['point_cm']);tip=r.vadd(tip,(0,0,.4))
    shaft_q=r.qmul(r.qaxis((0,0,1),-180.),contact.BASE_WORLD['staff011'][1])
    shaft_origin=r.vsub(tip,r.qrot(shaft_q,contact.TIP_FROM_ORIGIN))
    grip=r.xcompose((shaft_origin,shaft_q),r.xinv(contact.GRIP))
    # Acquire the actual shaft at29.8; it stays planted through the rising effort.
    w=r.fk(p);s=r.fk(start)
    acquire=r.smooth((t-27.8)/2.)
    hand=r.vlerp(s['RightHand'][0],grip[0],acquire)
    carry=r.smooth((t-31.4)/2.)
    hand=r.vlerp(hand,r.vadd(w['RightHand'][0],(0.,0.,4.)),carry)
    m.limb_ik(p,'RightArm','RightForeArm','RightHand',hand,
              r.vadd(w['RightArm'][0],(0,-35.,-35.)))
    carry_q=r.qmul(q,contact.BASE_WORLD['RightHand'][1])
    r.set_world_rot(p,r.fk(p),'RightHand',r.qslerp(grip[1],carry_q,carry))
    if t<=31.4:
        m.set_position(p,'staff011',shaft_origin)
        r.set_world_rot(p,r.fk(p),'staff011',shaft_q)
    else:
        # Walking carries the staff with the real hand. It is not falsely
        # described as planted while his body moves86cm away from its support.
        m.attach_prop(p,'staff011','RightHand',contact.GRIP)
    release=r.smooth((t-31.4)/1.2)
    w=r.fk(p);palm=r.vlerp(s['LeftHand'][0],r.vadd(w['Hips'][0],(15,0,-12)),release)
    m.limb_ik(p,'LeftArm','LeftForeArm','LeftHand',palm,r.vadd(w['LeftArm'][0],(20,-40,-20)))
    m.attach_prop(p,'recorder011','Hips',m.RECORDER_GRIP)
    # Exact boundary acquisition: no positional or anatomical pop at27.5.
    alpha=r.smooth((t-27.5)/.8)
    result={b:(r.vlerp(start[b][0],p[b][0],alpha),r.qslerp(start[b][1],p[b][1],alpha),start[b][2]) for b in r.ORDER}
    # Local-space blends alter the ancestors of contact bones. Re-solve in the
    # capsule frame after the blend so acquisition cannot drag the planted feet.
    for name,target,normal in [('Left',left,left_normal),('Right',right,right_normal)]:
        desired=r.vlerp(s[name+'Foot'][0],target,alpha)
        w=r.fk(result)
        m.limb_ik(result,name+'UpLeg',name+'Leg',name+'Foot',desired,
                  r.vadd(w[name+'UpLeg'][0],(0.,-60.,25.)))
        r.set_world_rot(result,r.fk(result),name+'Foot',
                        r.qslerp(s[name+'Foot'][1],r.fk(p)[name+'Foot'][1],alpha))
    if t<=31.4:
        m.set_position(result,'staff011',r.vlerp(s['staff011'][0],shaft_origin,alpha))
        r.set_world_rot(result,r.fk(result),'staff011',r.qslerp(s['staff011'][1],shaft_q,alpha))
    if t>=29.8:
        w=r.fk(result)
        m.limb_ik(result,'RightArm','RightForeArm','RightHand',hand,
                  r.vadd(w['RightArm'][0],(0,-35.,-35.)))
        r.set_world_rot(result,r.fk(result),'RightHand',r.qslerp(grip[1],carry_q,carry))
        if t>31.4:m.attach_prop(result,'staff011','RightHand',contact.GRIP)
    m.attach_prop(result,'recorder011','Hips',m.RECORDER_GRIP)
    return result
