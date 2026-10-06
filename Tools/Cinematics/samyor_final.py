"""Bake Samyor's full-head summit collapse and held final pose for CIN_24/CIN_25.

The fall is baked in component space against the measured, skinned body surface.
The Sequencer actor stays upright on the measured ground plane. It must not add
an actor roll or a guessed vertical offset. The held pose is exactly the fall's
endpoint, including the staff and recorder.

    python Tools/Cinematics/samyor_final.py emit-anims OUT
"""
from __future__ import annotations

import math
import json
from functools import lru_cache
import sys
from pathlib import Path

import samyor_reveal as reveal
import traveller_contacts as contacts
import traveller_gaze as gaze
import traveller_terrain as terrain
import ending_staging as staging

FPS = 15  # slow collapse; Sequencer interpolates the bone keys at its 30 fps display rate
COLLAPSE_S = 3.8
STAFF_SETTLE_START_S = 2.0
STAFF_SETTLE_CM = 3.0  # measured final staff contact: -0.66..3.54 cm after settling
CLIPS = {"A_Samyor_FinalCollapse": int(round(COLLAPSE_S * FPS)),
         "A_Samyor_FinalStill": FPS}
TRACKS = [bone for bone in reveal.ORDER if bone != 'traveller_rig']
SAMPLES = json.loads((Path(__file__).with_name('traveller_pose_samples.json')).read_text())['poses']
BASE = {bone: (tuple(values[0][:3]), reveal.qnorm(tuple(values[0][3:7])), tuple(values[0][7:]))
        for bone, values in SAMPLES['A_Traveller_SupportedIdle']['bones'].items()}


def set_position(local, bone, position):
    world = reveal.fk(local)
    parent = world[reveal.PARENT[bone]]
    delta = reveal.qrot(reveal.qconj(parent[1]), reveal.vsub(position, parent[0]))
    delta = tuple(delta[i] / parent[2][i] for i in range(3))
    _, quat, scale = local[bone]
    local[bone] = (delta, quat, scale)


def limb_ik(local, upper, lower, end, target, pole):
    world = reveal.fk(local)
    start, elbow, tip = [world[name][0] for name in (upper, lower, end)]
    a, b = reveal.vlen(reveal.vsub(elbow,start)), reveal.vlen(reveal.vsub(tip,elbow))
    direction = reveal.vnorm(reveal.vsub(target,start))
    distance = min(max(reveal.vlen(reveal.vsub(target,start)),abs(a-b)+0.05),a+b-0.05)
    along = (a*a-b*b+distance*distance)/(2*distance)
    height = math.sqrt(max(0,a*a-along*along))
    side = reveal.vsub(pole,start)
    side = reveal.vnorm(reveal.vsub(side,reveal.vmul(direction,reveal.vdot(side,direction))))
    joint = reveal.vadd(start,reveal.vadd(reveal.vmul(direction,along),reveal.vmul(side,height)))
    reveal.aim(local,upper,lower,reveal.vsub(joint,start))
    reveal.aim(local,lower,end,reveal.vsub(reveal.vadd(start,reveal.vmul(direction,distance)),joint))


def attach_prop(local, prop, bone, grip):
    world = reveal.fk(local)
    parent = world[reveal.PARENT[prop]]
    target = reveal.xcompose((world[bone][0],world[bone][1]),grip)
    position = reveal.qrot(reveal.qconj(parent[1]),reveal.vsub(target[0],parent[0]))
    local[prop] = (tuple(position[i]/parent[2][i] for i in range(3)),
                   reveal.qnorm(reveal.qmul(reveal.qconj(parent[1]),target[1])),(1,1,1))


_BASE_WORLD = reveal.fk(BASE)
RECORDER_GRIP = reveal.xcompose(reveal.xinv((_BASE_WORLD['Hips'][0],_BASE_WORLD['Hips'][1])),
                               (_BASE_WORLD['recorder011'][0],_BASE_WORLD['recorder011'][1]))


@lru_cache(maxsize=512)
def flat_pose_at(seconds: float) -> dict:
    local = dict(BASE)
    t = min(COLLAPSE_S,max(0.0,seconds))
    # The actor has just turned toward the real dawn bearing. Preserve that
    # upward look at handoff, then let his gaze lower as his knees give way.
    # Compensate the measured terrain frame so the actual head still looks at
    # the authored sun elevation after the whole body is aligned below.
    target = reveal.qrot(reveal.qconj(terrain.local_tilt(staging.SUN_BEARING-90.0)),
                         gaze.direction(90.0, 2.7))
    local = gaze.aim(local, target, 1.0-reveal.smooth(t/1.3))
    kneel = reveal.smooth((t-0.35)/1.65)
    fall = reveal.smooth((t-1.65)/(COLLAPSE_S-1.65))
    cough = math.sin(math.pi*min(1.0,t/1.3)) if t < 1.3 else 0.0
    set_position(local,'Hips',(3.0*kneel,-5.0*kneel,89.0-45.0*kneel))
    # Both boots stay planted while his knees buckle. The side fall starts only
    # after the centre of mass has lowered, rather than pivoting at the feet.
    for side, x, y in (('Left',16.0,4.0),('Right',-16.0,-3.0)):
        ankle_x = x if side == 'Left' else x + 30.0*fall
        limb_ik(local,side+'UpLeg',side+'Leg',side+'Foot',
                (ankle_x,y,11.5),reveal.vlerp(_BASE_WORLD[side+'Leg'][0],(ankle_x,65.0,35.0),kneel))
        world = reveal.fk(local)
        reveal.set_world_rot(local,world,side+'Foot',_BASE_WORLD[side+'Foot'][1])
    for bone, amount in (('Spine',5.0*cough+6.0*kneel),
                         ('Spine1',8.0*cough+4.0*kneel),
                         ('Spine2',4.0*cough+2.0*kneel),('Neck',-5.0*cough)):
        world = reveal.fk(local)
        reveal.set_world_rot(local,world,bone,
            reveal.qmul(reveal.qaxis((1,0,0),-amount),world[bone][1]))
    # Left palm seeks support; the right hand keeps the existing staff grip.
    start_hand = _BASE_WORLD['LeftHand'][0]
    target = reveal.vlerp(start_hand,(12.0,36.0,59.0),kneel)
    reveal.arm_ik(local,'L',target,reveal.vlerp(_BASE_WORLD['LeftForeArm'][0],(10.0,65.0,72.0),kneel))
    right = reveal.vlerp(_BASE_WORLD['RightHand'][0],(-8.0,32.0,58.0),kneel)
    reveal.arm_ik(local,'R',right,reveal.vlerp(_BASE_WORLD['RightForeArm'][0],(-8.0,65.0,70.0),kneel))
    world = reveal.fk(local)
    reveal.set_world_rot(local,world,'Hips',
        reveal.qmul(reveal.qaxis((0,1,0),88.0*fall),world['Hips'][1]))
    # Root-level accessories require their own transforms after the torso moves.
    attach_prop(local,'staff011','RightHand',reveal.G_SI)
    attach_prop(local,'recorder011','Hips',RECORDER_GRIP)
    # Skin all 20,588 body vertices; ground the actual lowest surface each frame.
    local = contacts.ground(local,clearance=0.4)
    # The staff slips free as he settles. It lies beside him, not suspended in
    # a clenched hand; the fixed credits pose includes this same landed prop.
    release = reveal.smooth((t-2.0)/(COLLAPSE_S-2.0))
    if release > 0:
        world = reveal.fk(local)
        landed_q = reveal.qmul(reveal.qaxis((0,1,0),90),reveal.SI_STAFF[1])
        landed = ((-55.0,65.0,7.944),landed_q)
        current = (world['staff011'][0],world['staff011'][1])
        target = (reveal.vlerp(current[0],landed[0],release),reveal.qslerp(current[1],landed[1],release))
        parent = world['root']
        position = reveal.qrot(reveal.qconj(parent[1]),reveal.vsub(target[0],parent[0]))
        local['staff011'] = (tuple(position[i]/parent[2][i] for i in range(3)),
                             reveal.qnorm(reveal.qmul(reveal.qconj(parent[1]),target[1])),(1,1,1))
    return local


@lru_cache(maxsize=512)
def pose_at(seconds: float) -> dict:
    local = terrain.align(flat_pose_at(seconds), staging.SUN_BEARING-90.0)
    amount = reveal.smooth((seconds-STAFF_SETTLE_START_S)/(COLLAPSE_S-STAFF_SETTLE_START_S))
    if amount > 0:
        # Settle only the released prop vertically in the upright actor frame.
        # Keep body anatomy, staff XY/orientation and the shared terrain frame.
        position = reveal.fk(local)['staff011'][0]
        set_position(local, 'staff011', (position[0],position[1],position[2]-STAFF_SETTLE_CM*amount))
    return local


def baked() -> dict:
    out = {}
    for name, n in CLIPS.items():
        tracks = {bone: [] for bone in TRACKS}
        for i in range(n + 1):
            t = COLLAPSE_S * i / n if name.endswith("Collapse") else COLLAPSE_S
            pose = pose_at(t)
            for bone in TRACKS:
                tracks[bone].append(pose[bone])
        out[name] = (n, tracks)
    return out


def readback_chunk() -> str:
    checks = []
    for name, n in CLIPS.items():
        samples = (0.0, 1.0, 2.0, COLLAPSE_S) if name.endswith('Collapse') else (0.0, 0.5, 1.0)
        for at in samples:
            pose = pose_at(at if name.endswith('Collapse') else COLLAPSE_S)
            for bone in ('root', 'staff011', 'RightHand', 'Neck'):
                checks.append((name, at, bone, pose[bone]))
    return f"""import unreal
clips = {{}}
for name, frames in {CLIPS!r}.items():
    clip = unreal.load_asset({reveal.ANIM_DIR!r} + '/' + name)
    assert clip is not None, name
    assert abs(clip.get_play_length() - frames / {FPS}) < 0.001, name
    model = clip.get_editor_property('data_model_interface')
    rate = model.get_frame_rate()
    print('FINAL_VERIFIED_METADATA', name, 'length', clip.get_play_length(), 'source_frames', model.get_number_of_frames(), 'source_keys', model.get_number_of_keys(), 'source_fps', rate.numerator, rate.denominator, 'sampled_frames', unreal.AnimationLibrary.get_num_frames(clip))
    assert model.get_number_of_frames() == frames, name
    assert model.get_number_of_keys() == frames + 1, name
    assert rate.numerator == {FPS} and rate.denominator == 1, name
    tracks = [str(b).casefold() for b in unreal.AnimationLibrary.get_animation_track_names(clip)]
    expected_tracks = {[bone.casefold() for bone in TRACKS]!r}
    assert len(tracks) == len(expected_tracks) and set(tracks) == set(expected_tracks), name
    clips[name] = clip
for name, at, bone, expected in {checks!r}:
    pose = unreal.AnimationLibrary.get_bone_pose_for_time(clips[name], bone, at, False)
    p = pose.get_editor_property('translation')
    q = pose.get_editor_property('rotation')
    s = pose.get_editor_property('scale3d')
    assert sum((a-b)**2 for a,b in zip((p.x,p.y,p.z),expected[0])) < 0.000025, (name, at, bone, 'position')
    assert abs(sum(a*b for a,b in zip((q.x,q.y,q.z,q.w),expected[1]))) > 0.9999, (name, at, bone, 'rotation')
    assert max(abs(a-b) for a,b in zip((s.x,s.y,s.z),expected[2])) < 0.0001, (name, at, bone, 'scale')
print('FINAL_STAFF_SOURCE_READBACK_OK clips 2 samples {len(checks)}')
"""


def emit_anims(out: Path, per_chunk: int = 4) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for ci, (name, (n, tracks)) in enumerate(baked().items()):
        (out / f"{ci}0_create_{name}.py").write_text(
            reveal.CREATE.format(dir=reveal.ANIM_DIR, name=name, skel=reveal.SKEL, fps=FPS, n=n),
            encoding="utf-8")
        bones = list(tracks)
        for j in range(0, len(bones), per_chunk):
            data = []
            for bone in bones[j:j + per_chunk]:
                states = tracks[bone]
                positions = [state[0] for state in states]
                rotations = [state[1] for state in states]
                scale = states[0][2]
                data.append((bone, positions, rotations, scale))
            (out / f"{ci}1_keys_{j // per_chunk:02d}_{name}.py").write_text(
                reveal.KEYS.format(dir=reveal.ANIM_DIR, name=name, data=data),
                encoding="utf-8")
        (out / f"{ci}9_save_{name}.py").write_text(
            reveal.SAVEA.format(dir=reveal.ANIM_DIR, name=name), encoding="utf-8")
    (out / '99_read.py').write_text(readback_chunk(), encoding='utf-8')


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "emit-anims":
        emit_anims(Path(sys.argv[2]))
    else:
        raise SystemExit("usage: samyor_final.py emit-anims OUT")
