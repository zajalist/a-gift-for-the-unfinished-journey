"""Offline preparation only: the missing, authored O01 optional cinematic.

Does not connect to Unreal. Root must stop PIE and review the manifest before
running the separate chunks with its guarded editor connection.
"""
import ast
import hashlib
import json
from pathlib import Path

import build_cinematics as bc

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'Saved/Verification/poi_low_voice_20261001'
ID = 'CIN_PO01_LOW_VOICE'
ASSET = '/Game/SaskartaGaea/GameFlow/Cinematics/LS_CIN_PO01_LowVoice'

PREFLIGHT = '''import json
import unreal
path = '/Game/SaskartaGaea/GameFlow/Cinematics/LS_CIN_PO01_LowVoice'
assert not unreal.EditorAssetLibrary.does_asset_exist(path), 'Expected missing package; inspect any existing or partial asset before resetting it'
assert unreal.load_asset('/Game/SaskartaGaea/Audio/Story/SFX_TapeClick') is not None, 'Missing authored tape click'
story = unreal.load_asset('/Game/SaskartaGaea/Story/DA_Saskarta_Story')
assert story is not None, 'Missing Story asset'
cines = [c for c in story.get_editor_property('cinematics') if str(c.get_editor_property('id')).casefold() == 'cin_po01_low_voice']
assert len(cines) == 1 and abs(cines[0].get_editor_property('duration_s') - 8.0) < 0.001
assert not cines[0].get_editor_property('relative_to_pawn'), 'O01 must remain in world space'
world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
volumes = [a for a in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.SaskartaEventVolume)
           if str(a.get_editor_property('trigger_id')).casefold() == 'poi_o01']
print('LOW_VOICE_PREFLIGHT ' + json.dumps({'asset_missing': True,
    'enabled_tags': [str(t) for t in story.get_editor_property('enabled_tags')],
    'volume_count': len(volumes), 'volume_paths': [a.get_path_name() for a in volumes]}))
'''

ACCEPTANCE = '''import json
import unreal
def need(ok, label, value=None):
    if not ok:
        print('LOW_VOICE_ACCEPTANCE_FAIL ' + json.dumps({'check': label, 'actual': value}, default=str))
        raise RuntimeError(label)
seq = unreal.load_asset('/Game/SaskartaGaea/GameFlow/Cinematics/LS_CIN_PO01_LowVoice')
need(isinstance(seq, unreal.LevelSequence), 'sequence exists')
rate = seq.get_display_rate()
need([rate.numerator, rate.denominator] == [30, 1], 'display rate')
need(abs(seq.get_playback_start_seconds()) < 0.001 and abs(seq.get_playback_end_seconds() - 8.0) < 0.001, '8 second range')
bindings = list(seq.get_bindings())
names = [str(b.get_display_name()) for b in bindings]
expected = [('CINPO01_S1_Push', 0.0, 4.5, 35.0), ('CINPO01_S2_Desk', 4.5, 8.0, 50.0)]
need(len(names) == 2 and set(names) == {e[0] for e in expected}, 'exact two camera bindings', names)
by_name = dict(zip(names, bindings))
tracks = list(seq.get_tracks())
need(len(tracks) == 1 and tracks[0].get_class().get_name() == 'MovieSceneCameraCutTrack', 'only camera cuts at sequence level')
cuts = sorted(tracks[0].get_sections(), key=lambda s: s.get_start_frame_seconds())
need(len(cuts) == 2, 'two cut sections', len(cuts))
actual = []
for cut, (name, start, end, lens) in zip(cuts, expected):
    times = [cut.get_start_frame_seconds(), cut.get_end_frame_seconds()]
    need(abs(times[0] - start) < 0.001 and abs(times[1] - end) < 0.001, 'cut times', times)
    binding = by_name[name]
    a, b = cut.get_camera_binding_id(), seq.get_binding_id(binding)
    need(a.get_editor_property('guid') == b.get_editor_property('guid')
         and a.get_editor_property('sequence_id') == b.get_editor_property('sequence_id'), 'cut target', name)
    template = unreal.MovieSceneBindingExtensions.get_object_template(binding)
    camera = template.get_editor_property('camera_component')
    need(abs(camera.get_editor_property('current_focal_length') - lens) < 0.001, 'camera lens', name)
    transforms = [t for t in binding.get_tracks() if t.get_class().get_name() == 'MovieScene3DTransformTrack']
    need(len(transforms) == 1 and len(transforms[0].get_sections()) == 1, 'camera transform section', name)
    counts = [c.get_num_keys() for c in transforms[0].get_sections()[0].get_all_channels()[:6]]
    need(counts == [2] * 6, 'camera transform keys', counts)
    actual.append({'camera': name, 'range': times, 'lens_mm': lens, 'keys': counts})
print('LOW_VOICE_CAMERA_BLEND_TARGET ' + tracks[0].get_path_name())
print('LOW_VOICE_SEQUENCE_ACCEPTANCE_OK ' + json.dumps(actual))
'''


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    story_path = ROOT / 'docs/story/story-events.json'
    story = json.loads(story_path.read_text(encoding='utf-8'))
    cine = story['cinematics'][ID]
    beat = next(b for b in story['optional_beats'] if b['id'] == 'PZ_O01')
    plan = bc.plan_poi_low_voice()
    assert cine['sequence'] == ASSET and plan['asset'] == ASSET.rsplit('/', 1)[1]
    assert cine['duration_s'] == plan['duration'] == 8.0
    assert cine['relative_to_pawn'] is False and plan['frame'] == 'world'
    assert beat['trigger'] == 'volume:POI_O01' and beat['actions'] == [{'type': 'PlayCinematic', 'id': ID}]
    if OUT.exists():
        raise SystemExit('Preserve existing packet; choose a new explicit revision before regenerating: ' + str(OUT))
    assert bc.check(ID, strict=True) == 0
    bc.emit(ID, OUT)
    (OUT / '00_preflight.py').write_text(PREFLIGHT, encoding='utf-8')
    # This is a missing-asset install, not an authorization to reset some later-created asset.
    setup = OUT / '00_setup.py'
    source = setup.read_text(encoding='utf-8')
    setup.write_text("import unreal\nassert not unreal.EditorAssetLibrary.does_asset_exist(" + repr(ASSET) +
                     "), 'Refusing to reset existing optional cinematic'\n" + source, encoding='utf-8')
    save = "import unreal\nasset = unreal.load_asset(" + repr(ASSET) + ")\nassert asset is not None\nsaved = unreal.EditorAssetLibrary.save_loaded_asset(asset, False)\nprint('LOW_VOICE_SAVED', saved)\nassert saved is True, 'Optional cinematic save failed'\n"
    (OUT / '90_save.py').write_text(save, encoding='utf-8')
    (OUT / '100_acceptance.py').write_text(ACCEPTANCE, encoding='utf-8')
    files = ['00_preflight.py', '00_setup.py', '10_cam_00.py', '10_cam_01.py', '80_cuts.py',
             '90_save.py', '99_read.py', '100_acceptance.py']
    for name in files:
        ast.parse((OUT / name).read_text(encoding='utf-8'), filename=name)
    missing = {key: c['sequence'] for key, c in story['cinematics'].items() if c.get('sequence')
               and not (ROOT / ('Content' + c['sequence'].removeprefix('/Game') + '.uasset')).exists()}
    manifest = {
        'scope': 'Prepared only. NO editor execution, asset installation or gameplay acceptance.',
        'target': ASSET, 'ordered_python_steps': files,
        'script_sha256': {name: sha(OUT / name) for name in files},
        'source_sha256': {str(path.relative_to(ROOT)).replace('\\', '/'): sha(path) for path in
            [Path(__file__), Path(bc.__file__), story_path, bc.SETDRESS, ROOT / 'Tools/Cinematics/gen_poi_events.py']},
        'cinematic': cine, 'beat': beat, 'plan': plan, 'all_missing_cinematic_packages': missing,
        'bridge_step_between_80_and_90': {
            'target': 'Use the exact track path printed by 80_cuts.py; require it belongs to the target LevelSequence package.',
            'set_command': 'object_set_property', 'set_args': {'path': '<observed camera cut track path>', 'properties': {'bCanBlend': True}},
            'require_set_result': 'ok true, applied contains bCanBlend, no failed properties',
            'get_command': 'object_get_property', 'get_args': {'path': '<same observed path>', 'names': ['bCanBlend']},
            'require_readback': 'properties.bCanBlend is True (native text export)',
            'reason': 'Authored final 2-second camera-cut ease-out requires bCanBlend; native property is not Python-visible.'},
        'integration_notes': [
            'Only root may run after PIE is stopped, with live lease, log watchdog and bounded one-step calls.',
            'Require saved True, the standalone acceptance marker, and native bCanBlend=True readback after save.',
            'No Story reimport or ID rename is required: current authoritative reference already matches.',
            'Preflight reports enabled tags and POI_O01 volume count. Do not enable PoiCine globally just for this install.',
            'Missing/duplicate event volume is a separate integration failure: authored centre/extent is pinned in beat.volume.',
            'Current set dressing, doorway visibility, WP streaming and handback need a later live detour playback.'
        ]}
    (OUT / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print('LOW_VOICE_PREPARED_ONLY ' + str(OUT))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
