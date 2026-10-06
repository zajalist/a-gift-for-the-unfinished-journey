"""CIN24: notice the brightening dawn through the station window, then leave.

Play at 59.5..83.8 seconds. The final held keys extend to 24 1/3 seconds so
15-fps source frames remain exact; Sequencer trims the extra 1/30 second.
The original window glance is unchanged through the last spoken line at79.31.
He then loads the planted staff, recovers from the hunched stance and takes four
small turning steps. The existing actor yaw80..83.8 is compensated in the feet
and staff, and the last pose matches the actual SlowWalk start at83.8.
"""
import json
from pathlib import Path
import sys

import samyor_reveal as rig
import traveller_gaze as gaze
import samyor_final as motion
import ending_staging as staging
import math

NAME = 'A_Samyor_LightNotice'
FPS = 15
FRAMES = 365
SECTION_SECONDS = 24.3
TRACKS = [bone for bone in rig.ORDER if bone != 'traveller_rig']
_sample = json.loads(Path(__file__).with_name('traveller_pose_samples.json').read_text())['poses']['A_Traveller_Transmit']['bones']
BASE = {bone:(tuple(values[0][:3]),rig.qnorm(tuple(values[0][3:7])),tuple(values[0][7:]))
        for bone,values in _sample.items()}
_post = json.loads(Path(__file__).with_name('probe_ending.json').read_text())['radio_post']
_entry, _door = _post['entry_start'], _post['door']
BODY_YAW = math.degrees(math.atan2(_door[1]-_entry[1], _door[0]-_entry[0])) - 90 + 50
TARGET = gaze.direction(staging.SUN_BEARING-BODY_YAW, .62)
_samples = json.loads(Path(__file__).with_name('traveller_pose_samples.json').read_text())['poses']
WALK = {bone:(tuple(values[0][:3]),rig.qnorm(tuple(values[0][3:7])),tuple(values[0][7:]))
        for bone,values in _samples['A_Traveller_SlowWalk']['bones'].items()}
BASE_WORLD, WALK_WORLD = rig.fk(BASE), rig.fk(WALK)
RISE_START = 79.31 - 59.5
TURN_START = 80.0 - 59.5
_out_yaw = math.degrees(math.atan2(_door[1]-_post['inside'][1], _door[0]-_post['inside'][0])) - 90
TURN_DEGREES = (_out_yaw-BODY_YAW+180) % 360 - 180
STAFF_GRIP = rig.xcompose(rig.xinv(BASE_WORLD['RightHand'][:2]), BASE_WORLD['staff011'][:2])
RECORDER_GRIP = rig.xcompose(rig.xinv(BASE_WORLD['Hips'][:2]), BASE_WORLD['recorder011'][:2])


def limb_pole(local, upper, lower, end, blend):
    """Use measured bend-plane directions, not a knee point near the leg axis."""
    directions = []
    for world in (BASE_WORLD,WALK_WORLD):
        a,b,c = [world[bone][0] for bone in (upper,lower,end)]
        axis = rig.vnorm(rig.vsub(c,a))
        bend = rig.vsub(b,a)
        directions.append(rig.vnorm(rig.vsub(bend,rig.vmul(axis,rig.vdot(bend,axis)))))
    return rig.vadd(rig.fk(local)[upper][0],rig.vmul(rig.vlerp(*directions,blend),100.))


def actor_turn(seconds):
    """Exactly the existing CIN24 linear actor-yaw interval, in clip seconds."""
    return TURN_DEGREES * min(1., max(0., (seconds-TURN_START)/(SECTION_SECONDS-TURN_START)))


def support_target(bone, seconds, first, second, lift_cm):
    """Two short placements per foot/staff, in the actor's initial world frame."""
    start = BASE_WORLD[bone][0]
    half = rig.qrot(rig.qaxis((0,0,1),TURN_DEGREES*.5),start)
    end = rig.qrot(rig.qaxis((0,0,1),TURN_DEGREES),WALK_WORLD[bone][0])
    p = start
    for a,b,origin,dest in ((*first,start,half),(*second,half,end)):
        if seconds < a:
            break
        u = rig.smooth((seconds-a)/(b-a))
        p = rig.vadd(rig.vlerp(origin,dest,u),(0,0,lift_cm*math.sin(math.pi*u)))
        if seconds < b:
            break
    return p


def supported_recovery(local, seconds):
    """Retain real staff/boot contacts; no whole-actor pitch or body levitation."""
    t = seconds
    blend = rig.smooth((t-RISE_START)/(SECTION_SECONDS-RISE_START))
    local = {bone:(rig.vlerp(local[bone][0],WALK[bone][0],blend),
                   rig.qslerp(local[bone][1],WALK[bone][1],blend),
                   rig.vlerp(local[bone][2],WALK[bone][2],blend)) for bone in rig.ORDER}
    load = rig.keyed([(RISE_START,0.),(20.45,1.),(21.35,0.),(SECTION_SECONDS,0.)],t)
    rise = rig.keyed([(RISE_START,0.),(20.45,0.),(21.35,1.),(22.2,.6),(SECTION_SECONDS,0.)],t)
    hips = rig.fk(local)['Hips'][0]
    motion.set_position(local,'Hips',rig.vadd(hips,(-3.*load,2.*load,-2.*load+3.*rise)))
    for bone,weight in (('Spine',.45),('Spine1',.35),('Spine2',.2)):
        world = rig.fk(local)
        angle = (-6.*load+4.*rise)*weight
        rig.set_world_rot(local,world,bone,rig.qmul(rig.qaxis((1,0,0),angle),world[bone][1]))

    yaw = actor_turn(t)
    undo = rig.qaxis((0,0,1),-yaw)
    placements = (('Left',(20.5,21.3),(22.4,23.2)),('Right',(21.4,22.2),(23.4,24.2)))
    targets = {side:rig.qrot(undo,support_target(side+'Foot',t,first,second,3.))
               for side,first,second in placements}
    # A turn can lengthen the stance even with fixed ankle targets. Settle the
    # hips just enough to keep both legs reachable; never pull a planted boot
    # upward with the IK solver's maximum-extension clamp.
    world = rig.fk(local)
    lower = 0.
    for side,target in targets.items():
        upper,knee,foot = [world[side+bone][0] for bone in ('UpLeg','Leg','Foot')]
        reach = rig.vlen(rig.vsub(knee,upper))+rig.vlen(rig.vsub(foot,knee))-.1
        horizontal = (upper[0]-target[0])**2+(upper[1]-target[1])**2
        lower = max(lower,upper[2]-target[2]-math.sqrt(max(0.,reach*reach-horizontal)))
    if lower > 0:
        motion.set_position(local,'Hips',rig.vadd(world['Hips'][0],(0,0,-lower)))
    # While a boot is down its position stays fixed in world space. Each boot
    # takes two small placements, rather than sliding through a137-degree turn.
    for side,first,second in placements:
        bone = side+'Foot'
        target = targets[side]
        pole = limb_pole(local,side+'UpLeg',side+'Leg',bone,blend)
        motion.limb_ik(local,side+'UpLeg',side+'Leg',bone,target,pole)
        facing = 0.
        for a,b,start,end in ((*first,0.,.5),(*second,.5,1.)):
            if t >= a:
                facing = start+(end-start)*rig.smooth((t-a)/(b-a))
        orientation = rig.qslerp(BASE_WORLD[bone][1],WALK_WORLD[bone][1],blend)
        rig.set_world_rot(local,rig.fk(local),bone,
                          rig.qmul(rig.qaxis((0,0,1),TURN_DEGREES*facing-yaw),orientation))

    # The right hand stays on its measured grip. The staff remains planted
    # through the initial weight transfer, then is lifted twice to follow him.
    staff_pos = rig.qrot(undo,support_target('staff011',t,(21.2,22.1),(23.1,24.2),2.))
    staff_facing = .5*rig.smooth((t-21.2)/.9)+.5*rig.smooth((t-23.1)/1.1)
    staff_q = rig.qmul(rig.qaxis((0,0,1),TURN_DEGREES*staff_facing-yaw),BASE_WORLD['staff011'][1])
    hand = rig.xcompose((staff_pos,staff_q),rig.xinv(STAFF_GRIP))
    pole = limb_pole(local,'RightArm','RightForeArm','RightHand',blend)
    motion.limb_ik(local,'RightArm','RightForeArm','RightHand',hand[0],pole)
    rig.set_world_rot(local,rig.fk(local),'RightHand',hand[1])
    motion.set_position(local,'staff011',staff_pos)
    rig.set_world_rot(local,rig.fk(local),'staff011',staff_q)

    brace = rig.keyed([(RISE_START,0.),(20.45,1.),(21.35,1.),(22.2,0.)],t)
    world = rig.fk(local)
    thigh = rig.vadd(world['LeftUpLeg'][0],(3.,10.,-21.))
    pole = limb_pole(local,'LeftArm','LeftForeArm','LeftHand',blend)
    motion.limb_ik(local,'LeftArm','LeftForeArm','LeftHand',
                   rig.vlerp(world['LeftHand'][0],thigh,brace),pole)
    motion.attach_prop(local,'recorder011','Hips',RECORDER_GRIP)
    return local


def pose_at(seconds):
    if seconds >= SECTION_SECONDS:
        return dict(WALK)
    local = dict(BASE)
    # "Hold on" at59.5: attention catches, then the head follows the window's
    # brightening at62. He keeps looking while telling the listener to see it.
    notice = rig.keyed([(0.0,0.0),(0.8,0.18),(2.5,0.72),(4.5,1.0),
                       (19.8,1.0),(22.5,0.45),(24.0,0.0)],seconds)
    if seconds > RISE_START:
        local = supported_recovery(local, seconds)
        target = rig.qrot(rig.qaxis((0,0,1),-actor_turn(seconds)),TARGET)
        return gaze.aim(local,target,notice)
    return gaze.aim(local, TARGET, notice)


def emit_anims(out, per_chunk=4):
    out = Path(out)
    out.mkdir(parents=True,exist_ok=True)
    poses = [pose_at(i/FPS) for i in range(FRAMES+1)]
    (out/'00_create.py').write_text(rig.CREATE.format(dir=rig.ANIM_DIR,name=NAME,skel=rig.SKEL,fps=FPS,n=FRAMES))
    for offset in range(0,len(TRACKS),per_chunk):
        data=[]
        for bone in TRACKS[offset:offset+per_chunk]:
            states=[pose[bone] for pose in poses]
            data.append((bone,[s[0] for s in states],[s[1] for s in states],states[0][2]))
        (out/f'10_keys_{offset//per_chunk:02d}.py').write_text(rig.KEYS.format(dir=rig.ANIM_DIR,name=NAME,data=data))
    (out/'90_save.py').write_text(rig.SAVEA.format(dir=rig.ANIM_DIR,name=NAME))
    (out/'99_read.py').write_text(f"""import unreal
clip = unreal.load_asset('{rig.ANIM_DIR}/{NAME}')
assert clip is not None
model = clip.get_editor_property('data_model_interface')
assert model.get_number_of_frames() == {FRAMES}
assert model.get_number_of_keys() == {FRAMES+1}
rate = model.get_frame_rate()
assert rate.numerator == {FPS} and rate.denominator == 1
tracks = [str(n).casefold() for n in unreal.AnimationLibrary.get_animation_track_names(clip)]
assert len(tracks) == {len(TRACKS)} and set(tracks) == {set(n.casefold() for n in TRACKS)!r}
print('LIGHT_NOTICE_METADATA_OK', clip.get_path_name(), clip.get_play_length())
""")


if __name__ == '__main__':
    if len(sys.argv)==3 and sys.argv[1]=='emit-anims':
        emit_anims(sys.argv[2])
    else:
        raise SystemExit('usage: samyor_notice.py emit-anims OUT')
