"""Bake actual Traveller bone keys offline; emitted Unreal scripts are NOT executed.

The imported SupportedIdle pose, measured reference hierarchy, source skin weights,
two boot surfaces and the real staff surface define the support frame. No actor
lean, root scale, fake mesh or guessed ankle-ground distance is introduced.
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

OUT = ROOT / 'Saved/Verification/ending_focus_20261001/staff_contact_authoring_30fps'
FPS = 30
STAFF_MESH = 'tripo_mesh_88102862.001'
TRACKS = [bone for bone in rig.ORDER if bone != 'traveller_rig']
BASE = contacts.ground(motion.BASE, .4)
WORLD = rig.fk(BASE)
STAFF_WORLD = WORLD['staff011']
GRIP = rig.xcompose(rig.xinv(WORLD['RightHand'][:2]), STAFF_WORLD[:2])
STAFF_VERTICES = contacts.skin(BASE, STAFF_MESH)
STAFF_TIP = tuple(float(v) for v in STAFF_VERTICES[STAFF_VERTICES[:, 2].argmin()])
_tip_offset = rig.qrot(rig.qconj(STAFF_WORLD[1]), rig.vsub(STAFF_TIP, STAFF_WORLD[0]))
STAFF_TIP_BONE_LOCAL = tuple(_tip_offset[i] / STAFF_WORLD[2][i] for i in range(3))
_reconstructed_tip = rig.vadd(STAFF_WORLD[0], rig.qrot(
    STAFF_WORLD[1], tuple(STAFF_TIP_BONE_LOCAL[i] * STAFF_WORLD[2][i] for i in range(3))))
assert rig.vlen(rig.vsub(_reconstructed_tip, STAFF_TIP)) < 1e-6


def pose(weight=0., effort=0.):
    """Small weight transfer with the original boot/staff world contacts held."""
    local = dict(BASE)
    hips = WORLD['Hips'][0]
    motion.set_position(local, 'Hips', rig.vadd(hips, (weight * 2.4, -effort * 1.2, -effort * .8)))
    for side in ('Left', 'Right'):
        upper, lower, end = (side + bone for bone in ('UpLeg', 'Leg', 'Foot'))
        motion.limb_ik(local, upper, lower, end, WORLD[end][0], WORLD[lower][0])
        rig.set_world_rot(local, rig.fk(local), end, WORLD[end][1])
    # The hand solves toward the real, planted staff grip; the prop never follows a fake actor lean.
    hand = rig.xcompose(STAFF_WORLD[:2], rig.xinv(GRIP))
    motion.limb_ik(local, 'RightArm', 'RightForeArm', 'RightHand', hand[0], WORLD['RightForeArm'][0])
    rig.set_world_rot(local, rig.fk(local), 'RightHand', hand[1])
    motion.set_position(local, 'staff011', STAFF_WORLD[0])
    rig.set_world_rot(local, rig.fk(local), 'staff011', STAFF_WORLD[1])
    motion.attach_prop(local, 'recorder011', 'Hips', motion.RECORDER_GRIP)
    return local


def emit(name, poses):
    folder = OUT / name
    folder.mkdir(parents=True, exist_ok=True)
    code = rig.CREATE.format(dir=rig.ANIM_DIR, name=name, skel=rig.SKEL, fps=FPS, n=len(poses)-1)
    (folder / '00_create.py').write_text(code, encoding='utf-8')
    for offset in range(0, len(TRACKS), 8):
        data = []
        for bone in TRACKS[offset:offset+8]:
            keys = [frame[bone] for frame in poses]
            data.append((bone, [list(k[0]) for k in keys], [list(k[1]) for k in keys], list(keys[0][2])))
        (folder / f'10_keys_{offset//8:02d}.py').write_text(
            rig.KEYS.format(dir=rig.ANIM_DIR, name=name, data=json.dumps(data)), encoding='utf-8')
    (folder / '90_save.py').write_text(rig.SAVEA.format(dir=rig.ANIM_DIR, name=name), encoding='utf-8')


def main():
    if (OUT / 'manifest.json').exists():
        raise SystemExit('Preserve the existing authored packet; use a fresh revision directory')
    OUT.mkdir(parents=True, exist_ok=True)
    enter_frames = round(.35 * FPS)
    hold_frames = FPS
    recover_frames = round(.7 * FPS)
    authored = {
        'A_Traveller_StaffEnter': [pose(0, rig.smooth(i/enter_frames)) for i in range(enter_frames + 1)],
        'A_Traveller_StaffHoldLeft': [pose(-1, 1) for _ in range(hold_frames + 1)],
        'A_Traveller_StaffHoldCentre': [pose(0, 1) for _ in range(hold_frames + 1)],
        'A_Traveller_StaffHoldRight': [pose(1, 1) for _ in range(hold_frames + 1)],
        'A_Traveller_StaffRecover': [pose(0, 1-rig.smooth(i/recover_frames)) for i in range(recover_frames + 1)],
    }
    # Authoring measurements, not a test run or claim of rendered acceptance.
    measurements = []
    for name, poses in authored.items():
        for index in sorted(set((0, len(poses)//2, len(poses)-1))):
            frame = poses[index]
            world = rig.fk(frame)
            measurements.append(dict(clip=name, frame=index,
                body_min_cm=float(contacts.skin(frame)[:,2].min()),
                staff_min_cm=float(contacts.skin(frame, STAFF_MESH)[:,2].min()),
                boot_origin_drift_cm={side: rig.vlen(rig.vsub(world[side+'Foot'][0],WORLD[side+'Foot'][0])) for side in ('Left','Right')},
                staff_origin_drift_cm=rig.vlen(rig.vsub(world['staff011'][0],STAFF_WORLD[0]))))
        emit(name, poses)
    (OUT/'source_contact_measurements.json').write_text(json.dumps(dict(
        status='offline_source_measurements_not_imported_or_visually_accepted',
        staff_tip_component_cm=STAFF_TIP, staff_tip_bone_local=STAFF_TIP_BONE_LOCAL,
        boot_plane_clearance_cm=.4,
        source='SourceArt/Characters/Traveller/traveller01_animated.fbx', samples=measurements), indent=2), encoding='utf-8')
    (OUT/'90_create_unreviewed_profile.py').write_text(f'''import unreal
assert unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is None, 'Stop PIE'
folder='/Game/SaskartaGaea/Characters/Traveller'
path=folder+'/DA_Traveller_StaffContacts'
profile=unreal.load_asset(path)
if profile is None:
    factory=unreal.DataAssetFactory()
    factory.set_editor_property('data_asset_class',unreal.SaskartaElderWalkProfile)
    profile=unreal.AssetToolsHelpers.get_asset_tools().create_asset('DA_Traveller_StaffContacts',folder,unreal.SaskartaElderWalkProfile,factory)
assert isinstance(profile,unreal.SaskartaElderWalkProfile)
profile.set_editor_property('bContactsReviewed',False)
profile.set_editor_property('StaffEnter',unreal.load_asset('{rig.ANIM_DIR}/A_Traveller_StaffEnter'))
profile.set_editor_property('StaffHold',unreal.load_asset('{rig.ANIM_DIR}/BS_Traveller_StaffBrace'))
profile.set_editor_property('StaffRecover',unreal.load_asset('{rig.ANIM_DIR}/A_Traveller_StaffRecover'))
profile.set_editor_property('StaffTipComponent',unreal.Vector{STAFF_TIP!r})
profile.set_editor_property('StaffTipBoneLocal',unreal.Vector{STAFF_TIP_BONE_LOCAL!r})
profile.set_editor_property('MaxContactSlopeDegrees',4.)
profile.set_editor_property('MaxContactErrorCm',3.)
print('ELDER_STAFF_PROFILE_UNREVIEWED',profile.get_path_name(),'saved=False')
''', encoding='utf-8')
    instructions = '''# Staff contact installation

Native files need the root's next serial build before the profile class exists.
Root is sole Hayba/editor writer. Stop PIE and use the current exclusive editor
lease. Emit scripts are offline; run create -> bone-key chunks -> save per clip.
Do not replay create after writing keys. The five clips have no root motion,
retain full head/bone scales and actual fixed boots/staff. The mesh/actor remain
on their existing ground placement; neither is translated to fit the animation.

In Hayba's asset editor create a real **Blend Space 1D** named
`BS_Traveller_StaffBrace` on `SKEL_Traveller`; WeightShift axis -1..1,
three looping samples at -1,0,1 from StaffHoldLeft/Centre/Right. Smoothing is
already native at 3/s; leave axis scale-animation disabled. Same sample lengths
and stationary contact frame prevent A/D from sliding the support prop.
The profile generator intentionally leaves contact certification FALSE.

For the actual Hayba UMG row create WBP_Saskarta_ElderWalkHint with native
parent SaskartaElderWalkHint. Use a transparent canvas and down-scalable row
named ElderHintRow, an existing E texture Image named ElderStaffGlyph and a
TextBlock named ElderStaffCaption. Assign its class to profile HintWidgetClass.
Native code updates those bindings without rebuilding the authored layout.
The unassigned native fallback is temporary; no authored UI is installed here.

The entry starts at actual SupportedIdle. Current locomotion is single-node,
so rendered entry/exit handoff needs review for a footfall pop before enabling.
If it pops, root must author the normal locomotion-to-contact transition through
the actual AnimBP/Control Rig; do not introduce actor lean or hide the body.
Review actual mesh stance, staff surface, both boots, root/head scales and
staff-to-hand grip at entry 0/.15/.35, three hold weights, release .35/.7.
Also review interpolated weights -0.5/+0.5: linear blend can slightly move skin
even when both endpoint support bones are fixed. Runtime refuses unsupported
terrain or >4 degree slopes rather than forcing a flat pose into a steep hill.
Set ContactsReviewed TRUE only after imported pose + rendered review; save the
profile and all generated assets and include them in the existing cook labels.
Recheck cinematic/rest/pause handoff and held E release-to-rearm in the next
human playthrough. No live action or acceptance has occurred in this packet.
'''
    (OUT/'INSTALL.md').write_text(instructions, encoding='utf-8')
    files={str(p.relative_to(OUT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in OUT.rglob('*') if p.is_file()}
    (OUT/'manifest.json').write_text(json.dumps(dict(status='authored_offline_not_installed', fps=FPS,
        clips={name:dict(frames=len(poses)-1,seconds=(len(poses)-1)/FPS) for name,poses in authored.items()}, files=files),indent=2),encoding='utf-8')
    print('STAFF_CONTACT_PACKET_READY',OUT,len(files),'files')


if __name__=='__main__': main()
