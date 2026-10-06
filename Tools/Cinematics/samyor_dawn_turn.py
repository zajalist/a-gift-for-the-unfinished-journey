"""Two small planted steps to face the dawn before the grounded collapse.

Actor yaw and foot compensation share the same sampled clock. The support foot
retains its world XY while the other foot lifts and turns; the actor stays at
the protected collapse waypoint. No root roll or guessed body-height offset.
"""
import json
import math
from pathlib import Path
import samyor_reveal as rig
import samyor_final as final
import traveller_contacts as contacts
import ending_staging as staging
import traveller_terrain as terrain

NAME = 'A_Samyor_DawnTurn'
FPS = 30
FRAMES = round(staging.TURN_SECONDS*FPS)
TRACKS = final.TRACKS
POST = json.loads(Path(__file__).with_name('probe_ending.json').read_text())['radio_post']
DELTA = staging.turn_delta(POST)
_walk = json.loads(Path(__file__).with_name('traveller_walk_exit_pose.json').read_text())
assert _walk['at']==1.4 and _walk['rate_scale']==1.0 and _walk['length']==4.0
START = {bone:(tuple(values[0][:3]),rig.qnorm(tuple(values[0][3:7])),tuple(values[0][7:]))
         for bone,values in _walk['bones'].items()}


def flat_pose_at(seconds):
    base = final.flat_pose_at(0.0)
    t = min(staging.TURN_SECONDS, max(0., seconds))
    settle = rig.smooth(t/.55)
    local = {bone:(rig.vlerp(START[bone][0],base[bone][0],settle),
                   rig.qslerp(START[bone][1],base[bone][1],settle),
                   rig.vlerp(START[bone][2],base[bone][2],settle)) for bone in rig.ORDER}
    first,world = rig.fk(START),rig.fk(base)
    yaw = DELTA*staging.turn_fraction(t)
    undo = rig.qaxis((0,0,1), -yaw)
    for side, start, end in (('Right',0.0,0.92),('Left',1.0,2.0)):
        step = rig.smooth((t-start)/(end-start))
        foot,end_foot = first[side+'Foot'],world[side+'Foot']
        turned = rig.qrot(rig.qaxis((0,0,1),DELTA),end_foot[0])
        planted = rig.vlerp(foot[0],turned,step)
        lift = 3.5*math.sin(math.pi*step)
        target = rig.qrot(undo,rig.vadd(planted,(0,0,lift)))
        knee=rig.vlerp(first[side+'Leg'][0],world[side+'Leg'][0],step)
        pole = rig.qrot(undo,rig.qrot(rig.qaxis((0,0,1),DELTA*step),knee))
        final.limb_ik(local,side+'UpLeg',side+'Leg',side+'Foot',target,pole)
        adjusted = rig.fk(local)
        foot_yaw = rig.qaxis((0,0,1),DELTA*step-yaw)
        orientation=rig.qslerp(foot[1],end_foot[1],step)
        rig.set_world_rot(local,adjusted,side+'Foot',rig.qmul(foot_yaw,orientation))
    final.attach_prop(local,'staff011','RightHand',rig.G_SI)
    final.attach_prop(local,'recorder011','Hips',final.RECORDER_GRIP)
    return contacts.ground(local,clearance=.4)


def pose_at(seconds):
    t = min(staging.TURN_SECONDS, max(0., seconds))
    yaw = staging.arrival_yaw(POST) + DELTA*staging.turn_fraction(t)
    # Preserve the measured walk handoff. Settle the complete body onto the
    # measured slope over the same 0.55 seconds as the arrival gesture.
    return terrain.align(flat_pose_at(t), yaw, rig.smooth(t/.55))


def emit_anims(out,per_chunk=4):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    poses=[pose_at(i/FPS) for i in range(FRAMES+1)]
    (out/'00_create.py').write_text(rig.CREATE.format(dir=rig.ANIM_DIR,name=NAME,skel=rig.SKEL,fps=FPS,n=FRAMES))
    for offset in range(0,len(TRACKS),per_chunk):
        data=[]
        for bone in TRACKS[offset:offset+per_chunk]:
            states=[pose[bone] for pose in poses]
            data.append((bone,[s[0] for s in states],[s[1] for s in states],states[0][2]))
        (out/f'10_keys_{offset//per_chunk:02d}.py').write_text(rig.KEYS.format(dir=rig.ANIM_DIR,name=NAME,data=data))
    (out/'90_save.py').write_text(rig.SAVEA.format(dir=rig.ANIM_DIR,name=NAME))
    checks=[(at,bone,pose_at(at)[bone]) for at in (0.,.55,1.,staging.TURN_SECONDS)
            for bone in ('root','LeftFoot','RightFoot','Head','staff011')]
    (out/'99_read.py').write_text(f"""import unreal
clip=unreal.load_asset('{rig.ANIM_DIR}/{NAME}')
model=clip.get_editor_property('data_model_interface')
assert model.get_number_of_frames()=={FRAMES} and model.get_number_of_keys()=={FRAMES+1}
rate=model.get_frame_rate()
assert rate.numerator=={FPS} and rate.denominator==1
assert set(str(n).casefold() for n in unreal.AnimationLibrary.get_animation_track_names(clip))=={set(n.casefold() for n in TRACKS)!r}
for at,bone,expected in {checks!r}:
 pose=unreal.AnimationLibrary.get_bone_pose_for_time(clip,bone,at,False)
 p=pose.get_editor_property('translation');q=pose.get_editor_property('rotation');s=pose.get_editor_property('scale3d')
 assert sum((a-b)**2 for a,b in zip((p.x,p.y,p.z),expected[0]))<.000025,(at,bone,'position')
 assert abs(sum(a*b for a,b in zip((q.x,q.y,q.z,q.w),expected[1])))>.9999,(at,bone,'rotation')
 assert max(abs(a-b) for a,b in zip((s.x,s.y,s.z),expected[2]))<.0001,(at,bone,'scale')
print('DAWN_TURN_METADATA_OK',clip.get_path_name(),clip.get_play_length())
""")
