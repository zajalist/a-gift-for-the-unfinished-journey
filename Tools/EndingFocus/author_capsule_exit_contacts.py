"""Author a full-bone, contact-led StaffStand revision offline.

The existing cinematic body anchor is retained, but the root track cancels its
pitch/yaw. Boots, pelvis, spine and props are authored independently in the road
frame. This packet requires a level exit landing: the present staged terrain is
123.64 cm below the carrier feet and is explicitly rejected for installation.
"""
from pathlib import Path
import hashlib
import json
import math
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'Tools/Cinematics'))
import samyor_reveal as rig
import samyor_final as motion
import traveller_contacts as contacts

OUT = ROOT / 'Saved/Verification/ending_focus_20261001/capsule_exit_contacts_v2'
NAME = 'A_Samyor_StaffStand_ContactV1'
FPS = 30
TRACKS = [b for b in rig.ORDER if b != 'traveller_rig']
BASE = dict(motion.BASE)
BASE_WORLD = rig.fk(BASE)
GRIP = rig.xcompose(rig.xinv(BASE_WORLD['RightHand'][:2]), BASE_WORLD['staff011'][:2])
STAFF_POINTS = contacts.skin(BASE, 'tripo_mesh_88102862.001')
STAFF_TIP = tuple(float(v) for v in STAFF_POINTS[STAFF_POINTS[:, 2].argmin()])
TIP_FROM_ORIGIN = rig.qrot(rig.qconj(BASE_WORLD['staff011'][1]),
    rig.vsub(STAFF_TIP, BASE_WORLD['staff011'][0]))


def transform_pose(local, transform):
    """Apply a rigid world transform through the real root; preserve bone scale."""
    local = dict(local)
    world = rig.fk(local)
    target = rig.xcompose(transform, world['root'][:2])
    motion.set_position(local, 'root', target[0])
    rig.set_world_rot(local, rig.fk(local), 'root', target[1])
    return local


def road_pose(t, state):
    legacy = transform_pose(rig.pose_at(t, state), rig.body_xf(t))
    if t <= 27.5:
        return legacy
    # The rear tyre becomes the first support, then the outside landing. Keep
    # both real boot surfaces horizontal; the rim hand bears weight until 32.8.
    q = rig.qaxis((0, 0, 1), -90.)
    local = transform_pose(BASE, ((-356.5, -110., rig.G0), q))
    hips = rig.keyed([(27.5, (-310., -52., 120.)),
                     (28.7, (-333., -75., 112.)),
                     (30.5, (-346., -99., 88.)),
                     (31.4, (-350., -107., 85.)),
                     (33.0, (-356.5, -110., 89.)),
                     (36., (-356.5, -110., 89.))], t)
    motion.set_position(local, 'Hips', rig.vadd(hips, (0, 0, rig.G0)))
    # Tyre support uses the measured rear wheel height (~60 cm). Actual mesh
    # collision and tread normal must be read back before approving this target.
    foot_targets = {
        'Left': rig.keyed([(27.5, (-300., -80., 62.)), (28.8, (-358., -65., 71.5)),
                           (30.5, (-358., -65., 71.5)), (32.3, (-352.5, -126., 11.9)),
                           (36., (-352.5, -126., 11.9))], t),
        'Right': rig.keyed([(27.5, (-286., -69., 62.)), (29.3, (-355., -99., 11.9)),
                            (32.5, (-359.5, -94., 11.9)),
                            (36., (-359.5, -94., 11.9))], t),
    }
    # Settle pelvis until both limbs are actually reachable, rather than letting
    # IK clamp drag planted soles above their supports.
    world = rig.fk(local)
    lower = 0.
    for side, target in foot_targets.items():
        a, b, c = [world[side + n][0] for n in ('UpLeg', 'Leg', 'Foot')]
        reach = rig.vlen(rig.vsub(b, a)) + rig.vlen(rig.vsub(c, b)) - .1
        horizontal = (a[0]-target[0])**2 + (a[1]-target[1])**2
        lower = max(lower, a[2]-target[2]-math.sqrt(max(0., reach*reach-horizontal)))
    if lower > 0:
        motion.set_position(local, 'Hips', rig.vadd(world['Hips'][0], (0, 0, -lower)))
    for side, target in foot_targets.items():
        target = rig.vadd(target, (0, 0, rig.G0))
        world = rig.fk(local)
        pole = rig.vadd(world[side + 'UpLeg'][0], (12., -60., -20.))
        motion.limb_ik(local, side+'UpLeg', side+'Leg', side+'Foot', target, pole)
        desired_q = rig.qmul(q, BASE_WORLD[side+'Foot'][1])
        rig.set_world_rot(local, rig.fk(local), side+'Foot', desired_q)
    # A fixed shaft, held by a solved anatomical hand, supports the transfer.
    staff_q = rig.qmul(q, BASE_WORLD['staff011'][1])
    tip = (-318.72, -72.22, rig.G0 + .4)
    origin = rig.vsub(tip, rig.qrot(staff_q, TIP_FROM_ORIGIN))
    hand = rig.xcompose((origin, staff_q), rig.xinv(GRIP))
    motion.limb_ik(local, 'RightArm', 'RightForeArm', 'RightHand', hand[0],
                   rig.vadd(rig.fk(local)['RightArm'][0], (-40., -10., -35.)))
    rig.set_world_rot(local, rig.fk(local), 'RightHand', hand[1])
    motion.set_position(local, 'staff011', origin)
    rig.set_world_rot(local, rig.fk(local), 'staff011', staff_q)
    # Left hand stays on the real side rim while seated weight transfers. Release
    # gradually only after both ground contacts are established.
    world = rig.fk(local)
    release = rig.smooth((t-32.3)/1.2)
    rim = (-322., -rig.RIM_Y, rig.G0 + rig.rim_z(-322.))
    rest = rig.vadd(world['Hips'][0], (18., 0., -15.))
    motion.limb_ik(local, 'LeftArm', 'LeftForeArm', 'LeftHand',
                   rig.vlerp(rim, rest, release), rig.vadd(world['LeftArm'][0], (35., 0., -30.)))
    # Torso effort comes from spine joints, never from pitching the whole actor.
    effort = rig.keyed([(27.5, 0.), (29.7, 1.), (30.5, 1.), (32.5, .6), (36., 0.)], t)
    for bone, weight in (('Spine', .45), ('Spine1', .35), ('Spine2', .2)):
        world = rig.fk(local)
        rig.set_world_rot(local, world, bone,
            rig.qmul(rig.qaxis((0, 1, 0), 8.*effort*weight), world[bone][1]))
    # Solve the contact again after torso articulation; a later spine key must
    # never pull the anatomical hand away from the planted shaft.
    motion.limb_ik(local, 'RightArm', 'RightForeArm', 'RightHand', hand[0],
                   rig.vadd(rig.fk(local)['RightArm'][0], (-40., -10., -35.)))
    rig.set_world_rot(local, rig.fk(local), 'RightHand', hand[1])
    motion.attach_prop(local, 'recorder011', 'Hips', motion.RECORDER_GRIP)
    # A soft 1.2 s acquisition preserves the seated clip boundary. No new cut,
    # instant upright pose or hide/reveal mask conceals the motion.
    alpha = rig.smooth((t-27.5)/1.2)
    return {b: (rig.vlerp(legacy[b][0], local[b][0], alpha),
                rig.qslerp(legacy[b][1], local[b][1], alpha),
                legacy[b][2]) for b in rig.ORDER}


def main():
    if (OUT / 'manifest.json').exists():
        raise SystemExit('Preserve packet; choose a new revision')
    OUT.mkdir(parents=True, exist_ok=True)
    state, poses, measurements = {}, [], []
    # Warm the prior authoring state so the staff acquisition is deterministic.
    for i in range(int(27.5*FPS)):
        rig.pose_at(i/FPS, state)
    for i in range(int(8.5*FPS)+1):
        t = 27.5+i/FPS
        road = road_pose(t, state)
        local = transform_pose(road, rig.xinv(rig.body_xf(t)))
        poses.append(local)
        if i % 15 == 0:
            body = contacts.skin(road)
            staff = contacts.skin(road, 'tripo_mesh_88102862.001')
            world = rig.fk(road)
            measurements.append(dict(t_s=t, hips_cm=world['Hips'][0],
                body_min_cm=float(body[:,2].min()), staff_min_cm=float(staff[:,2].min()),
                boot_centres_cm={side:world[side+'Foot'][0] for side in ('Left','Right')},
                actual_hand_to_shaft_cm=rig.vlen(rig.vsub(
                    rig.xcompose(world['RightHand'][:2],GRIP)[0],world['staff011'][0]))))
    (OUT/'00_create.py').write_text(rig.CREATE.format(dir=rig.ANIM_DIR,name=NAME,
        skel=rig.SKEL,fps=FPS,n=len(poses)-1),encoding='utf-8')
    for offset in range(0,len(TRACKS),8):
        data=[]
        for bone in TRACKS[offset:offset+8]:
            keys=[p[bone] for p in poses]
            data.append((bone,[list(k[0]) for k in keys],[list(k[1]) for k in keys],list(keys[0][2])))
        (OUT/f'10_keys_{offset//8:02d}.py').write_text(rig.KEYS.format(
            dir=rig.ANIM_DIR,name=NAME,data=json.dumps(data)),encoding='utf-8')
    (OUT/'90_save.py').write_text(rig.SAVEA.format(dir=rig.ANIM_DIR,name=NAME),encoding='utf-8')
    report=dict(status='DRAFT_SOURCE_CONTACT_AUTHORING_NOT_INSTALLABLE_AT_CURRENT_TERRAIN',
        exact_existing_start_s=27.5,end_s=36.,rise_prompt_s=30.5,
        current_exit_ground_cm=rig.SC['g_stand'],required_exit_ground_cm=rig.G0,
        current_rim_to_exit_ground_cm=rig.G0+rig.rim_z(-310.)-rig.SC['g_stand'],
        requirement='Root must provide and measure a supported level landing, tyre tread collision and every planted support; no floating invented foothold',
        original_tracks=len(rig.KEEP_BONES),full_tracks=len(TRACKS),samples=measurements,
        source_fbx='SourceArt/Characters/Traveller/traveller01_animated.fbx')
    (OUT/'contact_measurements.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    manifest={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in OUT.iterdir() if p.is_file()}
    (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print('CAPSULE_EXIT_PACKET',OUT,'files',len(manifest),'tracks',len(TRACKS),
          'samples',len(measurements),'terrain_requires_restaging',round(rig.SC['g_stand'],2))


if __name__=='__main__':
    main()
