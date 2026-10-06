"""Prepare bounded duplicate-only native review packets; no Unreal connection.

The analytic clearance receipt covers the camera centre and a 24 cm sphere
against source geometry. It does not certify installed meshes or playback.
"""
from pathlib import Path
import hashlib
import json
import math
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'Tools/ModelReview')]
from fbx_reader import read_fbx

OUT = ROOT / 'Saved/Verification/ending_focus_20261001/supported_review_v8'
SOURCE = ROOT / 'SourceArt/Characters/Carrier/carrier01_full.fbx'
PREVIEW = '/Game/SaskartaGaea/GameFlow/Cinematics/LS_CIN_19_Hatch_SideSupportedReviewV8'
BASE = '/Game/SaskartaGaea/GameFlow/Cinematics/LS_CIN_19_Hatch_SideSupportedReviewV7'
GUID = '16D68F0343FE7BEA273BBFBBF9346068'
ANIMS = '/Game/SaskartaGaea/Characters/Traveller/Anims/'
SWAPS = [(0., 7., 'A_Samyor_ReachLatch_SideSupportedV7_ReviewOnly_InlineV7'),
         (7., 13.5, 'A_Samyor_PushLid_SideSupportedV7_ReviewOnly_InlineV7'),
         (13.5, 21.5, 'A_Samyor_PullUp_SideSupportedV7_ReviewOnly_InlineV7'),
         (27.5, 36., 'A_Samyor_StaffStand_SideSupportedV7_ClearCarry_ReviewOnly_InlineV7')]
# Same first exterior eye. Every segment remains in the outside Y half-space.
# Targets follow the supported pose, rather than the archival attachment eye.
STAGES = [(0., (-640., -500., 240.), (-305., -20., 110.)),
          (13.5, (-635., -510., 250.), (-285., -50., 120.)),
          (27.5, (-590., -520., 230.), (-270., -105., 85.)),
          (31.4, (-600., -530., 215.), (-270., -105., 82.)),
          (36., (-650., -535., 225.), (-356.5, -110., 85.))]


def interpolate(t, axis):
    for a, b in zip(STAGES, STAGES[1:]):
        if t <= b[0]:
            u = max(0., (t-a[0])/(b[0]-a[0]))
            return tuple(x+(y-x)*u for x, y in zip(a[axis], b[axis]))
    return STAGES[-1][axis]


def camera_keys():
    times = sorted({i/5 for i in range(181)} | {s[0] for s in STAGES})
    keys = []
    for t in times:
        p = interpolate(t, 1)
        target = interpolate(t, 2)
        dx, dy, dz = [b-a for a, b in zip(p, target)]
        keys.append((t, *p, 0., math.degrees(math.atan2(dz, math.hypot(dx, dy))),
                     math.degrees(math.atan2(dy, dx))))
    return keys


COMMON = '''import unreal,json
assert unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is None,'Stop PIE'
BASE={base!r}
PREVIEW={preview!r}
PRODUCTION='/Game/SaskartaGaea/GameFlow/Cinematics/LS_CIN_19_Hatch'
BODY_GUID={guid!r}
def body(sequence):
    found=[b for b in sequence.get_bindings() if str(b.get_id()).replace('-','').upper()==BODY_GUID]
    assert len(found)==1,'Body GUID missing; inspect saved binding inventory'
    assert str(found[0].get_display_name())=='Skeletal Mesh Actor','Body binding changed'
    tracks=[t for t in found[0].get_tracks() if isinstance(t,unreal.MovieSceneSkeletalAnimationTrack)]
    assert len(tracks)==1
    return tracks[0].get_sections()
def body_fingerprint(sequence):
    return sorted([(round(s.get_start_frame_seconds(),3),round(s.get_end_frame_seconds(),3),
                    s.get_editor_property('params').animation.get_path_name()) for s in body(sequence)])
'''


def main():
    assert not OUT.exists(), 'Preserve previous packet; inspect before retrying authoring'
    OUT.mkdir(parents=True)
    scene = read_fbx(str(SOURCE))
    inventory = []
    hinge = (-251.3, -45., 139.6)
    swept_hatch_min_y = None
    for geometry in scene.geometries.values():
        model = scene.model_of_geometry(geometry.id)
        assert abs(model.rotation[2]-180.) < .001
        assert max(abs(model.scaling-100.)) < .001 and max(abs(model.translation)) < .001
        p = geometry.vertices[:, [1, 0, 2]] * [-100., -100., 100.]
        inventory.append(dict(model=model.name,vertices=len(p),min_cm=p.min(axis=0).tolist(),max_cm=p.max(axis=0).tolist()))
        if model.name == 'full_pod_hatch01':
            # Rotation is about local -Y: every vertex keeps its Y coordinate.
            # The stronger all-axis sphere envelope also handles the conservative
            # case of a wrong hinge-axis assumption, within the measured hinge.
            radius = max(math.dist(v, hinge) for v in p)
            swept_hatch_min_y = hinge[1]-radius
    assert len(inventory)==15 and swept_hatch_min_y is not None
    static_min_y = min(row['min_cm'][1] for row in inventory)
    conservative_min_y = min(static_min_y, swept_hatch_min_y)
    keys = camera_keys()
    camera_max_y = max(k[2] for k in keys)
    clearance = conservative_min_y-camera_max_y-24.
    assert clearance > 150.
    receipt = dict(production_accepted=False,source=str(SOURCE),source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
                   meshes=inventory,measured_hinge_cm=hinge,all_angle_hatch_min_y_cm=swept_hatch_min_y,
                   conservative_car_min_y_cm=conservative_min_y,camera_max_y_cm=camera_max_y,
                   camera_sphere_radius_cm=24.,continuous_source_sphere_clearance_lower_bound_cm=clearance,
                   proof='Every linear camera segment is in Y <= -500. Every static source vertex and its triangle interior is in the opposite half-space; an all-angle hinge-centred sphere contains the moving source hatch. The separating Y gap minus 24 cm bounds camera-sphere clearance for the entire 36 seconds.',
                   limits=['Source-space mapping only; current native component transforms and imported geometry need readback.',
                           'No terrain, set dressing, drone flight smoothing, blend-in, handback or camera near-plane acceptance implied.',
                           'Line of sight can intersect the closed shell while Samyor reclines; frame review decides visibility.',
                           'The existing source camera also clears this envelope. This patch improves supported-pose framing and does not identify the cause of native clipping.'])
    (OUT/'camera_source_clearance.json').write_text(json.dumps(receipt,indent=2))
    (OUT/'camera_plan.json').write_text(json.dumps(dict(stages=STAGES,keys=keys,hfov_deg=62.,interp='linear',camera='CIN19_ExteriorDrone',body_anchor_unchanged=True),indent=2))
    common = COMMON.format(base=BASE,preview=PREVIEW,guid=GUID)
    swap = common + '''
base=unreal.load_asset(BASE);assert base
original=unreal.load_asset(PRODUCTION);assert original
before=body_fingerprint(base);protected=body_fingerprint(original)
expected_ranges=[(0.,7.),(7.,13.5),(13.5,21.5),(21.5,27.5),(27.5,36.)]
assert [(a,b) for a,b,_ in before]==expected_ranges,'Saved V7 ranges changed'
assert before[3][2].endswith('.A_Samyor_LegOver_SideContactV4_ReviewOnly_InlineV5'),'Retained supported LegOver changed'
assert not unreal.EditorAssetLibrary.does_asset_exist(PREVIEW),'Inspect existing V8; do not blindly replay duplication'
swaps=''' + repr(SWAPS) + '''
assets={}
for a,b,name in swaps:
    anim=unreal.load_asset(''' + repr(ANIMS) + '''+name);assert anim,name
    names=[str(n).casefold() for n in unreal.AnimationLibrary.get_animation_track_names(anim)]
    assert len(names)==68 and len(set(names))==68,name
    assert abs(anim.get_play_length()-(b-a))<.001,name
    assets[(a,b)]=anim
seq=unreal.EditorAssetLibrary.duplicate_asset(BASE,PREVIEW);assert seq
changed=[]
for section in body(seq):
    pair=(round(section.get_start_frame_seconds(),3),round(section.get_end_frame_seconds(),3))
    if pair in assets:
        params=section.get_editor_property('params')
        params.set_editor_property('animation',assets[pair]);section.set_editor_property('params',params)
        changed.append(pair)
assert set(changed)==set(assets)
after=body_fingerprint(seq)
assert after[3]==before[3] and body_fingerprint(base)==before and body_fingerprint(original)==protected
assert unreal.EditorAssetLibrary.save_asset(PREVIEW,only_if_is_dirty=False)
saved=unreal.load_asset(PREVIEW);assert body_fingerprint(saved)==after
print('CIN19_V8_BODY_REVIEW '+json.dumps(dict(asset=PREVIEW,body_guid=BODY_GUID,sections=after,base_sections_unchanged=True,production_sections_unchanged=True,production_accepted=False),separators=(',',':')))
'''
    (OUT/'00_duplicate_swap_supported_clips.py').write_text(swap)
    camera = common + '''
seq=unreal.load_asset(PREVIEW);assert seq
base=unreal.load_asset(BASE);assert base
protected=body_fingerprint(seq);original=unreal.load_asset(PRODUCTION);production_body=body_fingerprint(original)
bindings=[b for b in seq.get_bindings() if str(b.get_display_name())=='CIN19_ExteriorDrone']
assert len(bindings)==1,'Inspect exterior camera name; do not touch BodyAnchor'
b=bindings[0]
template=unreal.MovieSceneBindingExtensions.get_object_template(b)
assert template and isinstance(template,unreal.CineCameraActor)
comp=template.get_editor_property('camera_component');assert comp
before_focal=comp.get_editor_property('current_focal_length')
assert abs(before_focal-23.76/(2*0.6008606190275604))<.1,'Expected 62 degree exterior lens'
tracks=[t for t in b.get_tracks() if isinstance(t,unreal.MovieScene3DTransformTrack)]
assert len(tracks)==1,'Unexpected camera transform construction'
assert not any(isinstance(t,unreal.MovieScene3DAttachTrack) for t in b.get_tracks()),'Exterior camera has an unexpected parent; inspect native construction'
sections=tracks[0].get_sections();assert len(sections)==1
old=sections[0];assert abs(old.get_start_frame_seconds())<.001 and abs(old.get_end_frame_seconds()-36.)<.001
old_first=[float(c.get_keys()[0].get_value()) for c in old.get_all_channels()[:6]]
assert all(abs(old_first[i]-v)<.01 for i,v in enumerate([-640.,-500.,240.])),'First native exterior eye differs; inspect origin/attachment before replacing'
# Keep the binding ID and camera cut reference; replace only its transform section.
tracks[0].remove_section(old)
sec=tracks[0].add_section();sec.set_range_seconds(0.,36.)
ch=sec.get_all_channels();assert len(ch)>=6
rate=seq.get_tick_resolution();assert rate.denominator>0
tick_hz=rate.numerator/rate.denominator
keys=''' + repr(keys) + '''
for key in keys:
    tick=unreal.FrameNumber(round(key[0]*tick_hz))
    for axis in range(6):
        ch[axis].add_key(tick,float(key[axis+1]),0.,unreal.MovieSceneTimeUnit.TICK_RESOLUTION,unreal.MovieSceneKeyInterpolation.LINEAR)
assert all(c.get_num_keys()==len(keys) for c in ch[:6])
assert body_fingerprint(seq)==protected and body_fingerprint(original)==production_body
assert abs(comp.get_editor_property('current_focal_length')-before_focal)<.00001
assert unreal.EditorAssetLibrary.save_asset(PREVIEW,only_if_is_dirty=False)
read=unreal.load_asset(PREVIEW)
for axis in range(6):
    observed=ch[axis].get_keys();assert len(observed)==len(keys)
    assert all(abs(float(k.get_value())-keys[i][axis+1])<.001 for i,k in enumerate(observed)),'Native key value mismatch'
print('CIN19_V8_CAMERA_REVIEW '+json.dumps(dict(asset=PREVIEW,camera_guid=str(b.get_id()),keys_per_channel=[c.get_num_keys() for c in ch[:6]],old_first=old_first,first=keys[0],last=keys[-1],duration_s=36.,interp='LINEAR',all_key_values_read_back=True,camera_binding_and_cut_retained=True,body_sections_unchanged=body_fingerprint(read)==protected,production_accepted=False),separators=(',',':')))
'''
    (OUT/'10_replace_exterior_camera.py').write_text(camera)
    files = {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in OUT.iterdir() if p.is_file()}
    (OUT/'manifest.json').write_text(json.dumps(dict(status='ROOT_NATIVE_REVIEW_NOT_EXECUTED',base=BASE,preview=PREVIEW,per_call_budget_s=5,call_count=2,animation_import_prerequisite_calls=38,files=files,production_accepted=False),indent=2))
    print(json.dumps(dict(packet=str(OUT),camera_keys=len(keys),continuous_source_sphere_gap_cm=clearance,production_accepted=False)))


if __name__ == '__main__':
    main()
