"""Prepare separate, read-only probes for the installed September 30 ending packet.

This only reads the original packet and writes a new acceptance directory. It never
imports, saves, compiles, plays or modifies an Unreal asset, nor rewrites a packet.
"""
import ast
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKET = ROOT / 'Saved/Verification/ending_voice_20260930'
OUT = PACKET / 'readback/installed_assets_v1'

COMMON = '''import json
import unreal
def require(ok, label, actual=None):
    if not ok:
        print('ENDING_ACCEPTANCE_FAIL ' + json.dumps({'check': label, 'actual': actual}, default=str))
        raise RuntimeError(label)
def near(a, b, tolerance=0.001):
    return abs(float(a) - float(b)) <= tolerance
'''

HATCH = '''for item in EXPECTED:
    clip = unreal.load_asset(item['asset'])
    require(isinstance(clip, unreal.AnimSequence), 'hatch asset type', item['asset'])
    model = clip.get_editor_property('data_model_interface')
    rate = model.get_frame_rate()
    tracks = [str(n).casefold() for n in unreal.AnimationLibrary.get_animation_track_names(clip)]
    actual = {'asset': item['asset'], 'length': clip.get_play_length(), 'source_frames': model.get_number_of_frames(),
              'source_keys': model.get_number_of_keys(), 'fps': [rate.numerator, rate.denominator], 'tracks': tracks}
    print('HATCH_METADATA ' + json.dumps(actual))
    require(near(actual['length'], item['frames'] / 30.0), 'hatch duration', actual)
    require(actual['source_frames'] == item['frames'] and actual['source_keys'] == item['frames'] + 1,
            'hatch source frames and keys', actual)
    require(actual['fps'] == [30, 1], 'hatch source frame rate', actual)
    require(len(tracks) == 42 and set(tracks) == set(item['tracks']), 'hatch exact bone tracks', actual)
    scales = []
    for at in [0.0, clip.get_play_length() / 2.0, clip.get_play_length()]:
        for bone in ['Neck', 'Head']:
            pose = unreal.AnimationLibrary.get_bone_pose_for_time(clip, bone, at, False)
            s = pose.get_editor_property('scale3d')
            values = [s.x, s.y, s.z]
            scales.append({'time': at, 'bone': bone, 'scale': values})
            require(all(near(v, 1.0, 0.0001) for v in values), 'full head scale', scales[-1])
    print('HATCH_HEAD_SCALES ' + json.dumps({'asset': item['asset'], 'samples': scales}))
print('ENDING_HATCH_ACCEPTANCE_OK clips 5 head_samples 30')
'''

CINEMATIC = '''seq = unreal.load_asset(EXPECTED['asset'])
require(isinstance(seq, unreal.LevelSequence), 'sequence asset type', EXPECTED['asset'])
rate = seq.get_display_rate()
require(near(seq.get_playback_start_seconds(), 0) and near(seq.get_playback_end_seconds(), EXPECTED['duration']),
        'sequence range', [seq.get_playback_start_seconds(), seq.get_playback_end_seconds()])
require([rate.numerator, rate.denominator] == [30, 1], 'sequence display rate')
bindings = list(seq.get_bindings())
names = [str(b.get_display_name()) for b in bindings]
require(len(names) == len(EXPECTED['bindings']) and set(names) == set(EXPECTED['bindings']), 'exact bindings', names)
by_name = dict(zip(names, bindings))
def tracks(binding, name):
    return [t for t in binding.get_tracks() if t.get_class().get_name() == name]
def one_section(binding, kind):
    found = tracks(binding, kind)
    require(len(found) == 1 and len(found[0].get_sections()) == 1, 'one track and section: ' + kind)
    return found[0].get_sections()[0]
def section_range(section):
    return [section.get_start_frame_seconds(), section.get_end_frame_seconds()]
def full_range(section, label):
    actual = section_range(section)
    require(near(actual[0], 0) and near(actual[1], EXPECTED['duration']), label, actual)
def same_binding(actual_id, binding):
    expected_id = seq.get_binding_id(binding)
    return (actual_id.get_editor_property('guid') == expected_id.get_editor_property('guid')
            and actual_id.get_editor_property('sequence_id') == expected_id.get_editor_property('sequence_id'))
master = list(seq.get_tracks())
cuts = [t for t in master if t.get_class().get_name() == 'MovieSceneCameraCutTrack']
require(len(cuts) == 1 and len(cuts[0].get_sections()) == 1, 'one camera cut track and section')
cut = cuts[0].get_sections()[0]
full_range(cut, 'camera cut range')
require(same_binding(cut.get_camera_binding_id(), by_name[EXPECTED['camera']]), 'camera cut binding', EXPECTED['camera'])
fade_tracks = [t for t in master if t.get_class().get_name() == 'MovieSceneFadeTrack']
require(len(fade_tracks) == EXPECTED['fade_tracks'], 'fade track count', len(fade_tracks))
body = by_name[EXPECTED['body']]
template = unreal.MovieSceneBindingExtensions.get_object_template(body)
mesh = template.get_editor_property('skeletal_mesh_component').get_skeletal_mesh_asset()
require(mesh is not None and mesh.get_path_name() == '/Game/SaskartaGaea/Characters/Traveller/SK_Traveller.SK_Traveller',
        'full Traveller mesh', mesh.get_path_name() if mesh else None)
anims = tracks(body, 'MovieSceneSkeletalAnimationTrack')
require(len(anims) == 1, 'one body animation track', len(anims))
sections = []
head_checked = set()
for section in anims[0].get_sections():
    params = section.get_editor_property('params')
    animation = params.get_editor_property('animation')
    require(animation is not None, 'animation section reference')
    sections.append([animation.get_name()] + section_range(section))
    if animation.get_path_name() not in head_checked:
        head_checked.add(animation.get_path_name())
        for at in [0.0, animation.get_play_length() / 2.0, animation.get_play_length()]:
            for bone in ['Neck', 'Head']:
                pose = unreal.AnimationLibrary.get_bone_pose_for_time(animation, bone, at, False)
                scale = pose.get_editor_property('scale3d')
                values = [scale.x, scale.y, scale.z]
                require(all(near(v, 1.0, 0.0001) for v in values), 'sequence animation full head scale',
                        {'animation': animation.get_name(), 'time': at, 'bone': bone, 'scale': values})
sections.sort(key=lambda row: row[1])
print('ENDING_SEQUENCE_ANIMATIONS ' + json.dumps({'asset': EXPECTED['asset'], 'actual': sections}))
require(len(sections) == len(EXPECTED['animations']), 'animation section count', sections)
for actual, wanted in zip(sections, EXPECTED['animations']):
    require(actual[0] == wanted[0] and near(actual[1], wanted[1]) and near(actual[2], wanted[2]),
            'animation section timing', {'actual': actual, 'expected': wanted})
for name, wanted in EXPECTED['transforms'].items():
    section = one_section(by_name[name], 'MovieScene3DTransformTrack')
    full_range(section, name + ' transform range')
    channels = section.get_all_channels()
    require(len(channels) >= 6, name + ' transform channels', len(channels))
    actual = []
    for index in range(6):
        keys = channels[index].get_keys()
        require(len(keys) == wanted['key_count'], name + ' channel key count', [index, len(keys)])
        first, last = keys[0].get_value(), keys[-1].get_value()
        actual.append([first, last])
        require(near(first, wanted['first'][index], 0.01) and near(last, wanted['last'][index], 0.01),
                name + ' first/last transform', [index, first, last])
    print('ENDING_SEQUENCE_TRANSFORM ' + json.dumps({'binding': name, 'keys_per_channel': wanted['key_count'], 'first_last': actual}))
if EXPECTED['anchor']:
    attach = one_section(body, 'MovieScene3DAttachTrack')
    full_range(attach, 'body anchor attachment range')
    require(same_binding(attach.get_constraint_binding_id(), by_name[EXPECTED['anchor']]), 'body anchor binding')
    require(not same_binding(cut.get_camera_binding_id(), by_name[EXPECTED['anchor']]), 'body anchor stays uncut')
print('ENDING_SEQUENCE_ACCEPTANCE_OK ' + EXPECTED['id'] + ' ' + json.dumps({'duration': EXPECTED['duration'], 'camera': EXPECTED['camera'], 'bindings': names}))
'''

SFX = '''for item in EXPECTED:
    wave = unreal.load_asset(item['asset'])
    require(isinstance(wave, unreal.SoundWave), 'ending SFX asset type', item['asset'])
    duration = wave.get_editor_property('duration')
    looping = wave.get_editor_property('looping')
    sound_class = wave.get_editor_property('sound_class_object')
    chain = []
    while sound_class is not None and len(chain) < 16:
        path = sound_class.get_path_name()
        require(path not in chain, 'sound class parent cycle', chain)
        chain.append(path)
        sound_class = sound_class.get_editor_property('parent_class')
    require(sound_class is None, 'sound class depth bound', chain)
    actual = {'asset': item['asset'], 'duration': duration, 'looping': looping, 'sound_class_chain': chain,
              'loading_behavior': str(wave.get_editor_property('loading_behavior'))}
    print('ENDING_SFX_METADATA ' + json.dumps(actual))
    require(near(duration, item['duration_s'], 0.002), 'ending SFX duration', actual)
    require(looping == item['looping'], 'ending SFX loop flag', actual)
    require(not any(p.rsplit('/', 1)[-1].casefold().startswith('sc_voice.') for p in chain), 'SFX excluded from voice class', actual)
    if looping:
        require(wave.get_editor_property('loading_behavior') == unreal.SoundWaveLoadingBehavior.PRIME_ON_LOAD,
                'looping channel hiss primed', actual)
print('ENDING_SFX_ACCEPTANCE_OK waves 7 looped 1')
'''

TRAVELLER = '''cls = unreal.EditorAssetLibrary.load_blueprint_class('/Game/SaskartaGaea/Characters/Traveller/BP_Saskarta_Traveller')
require(cls is not None, 'Traveller generated class exists')
cdo = unreal.get_default_object(cls)
world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
require(world is not None, 'editor world exists')
actors = list(unreal.GameplayStatics.get_all_actors_of_class(world, cls))
for obj in [cdo] + actors:
    values = {name: obj.get_editor_property(name) for name in EXPECTED}
    print('TRAVELLER_CAMERA_DEFAULTS ' + json.dumps({'object': obj.get_path_name(), 'values': values}))
    require(all(near(values[name], value) for name, value in EXPECTED.items()), 'Traveller camera defaults or placed override', values)
print('ENDING_TRAVELLER_ACCEPTANCE_OK defaults 4 placed_actors ' + str(len(actors)))
'''


def literal_for(source, target):
    tree = ast.parse(source)
    return next(ast.literal_eval(node.iter) for node in ast.walk(tree)
                if isinstance(node, ast.For) and ast.unparse(node.target) == target)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare():
    audit = json.loads((PACKET / 'preparation-audit.json').read_text(encoding='utf-8'))
    inputs = {}

    def read(relative):
        path = PACKET / relative
        digest = sha(path)
        if relative in audit['prepared_sha256']:
            if digest != audit['prepared_sha256'][relative]:
                raise ValueError('Original packet fingerprint changed: ' + relative)
        inputs[relative] = digest
        return path.read_text(encoding='utf-8')

    probes = {}

    def add(name, expected, source):
        # Python literals avoid requiring any helper imports or reading external data in the editor.
        code = COMMON + 'EXPECTED = ' + repr(expected) + '\n' + source
        compile(code, name, 'exec')
        probes[name] = code

    hatch = []
    for index, name, frames in [(0, 'ReachLatch', 210), (1, 'PushLid', 195), (2, 'PullUp', 240),
                                (3, 'LegOver_Sit', 180), (4, 'StaffStand', 255)]:
        asset_name = 'A_Samyor_' + name
        read(f'hatch_anims/{index}0_create_{asset_name}.py')
        bones = []
        for chunk in range(6):
            source = read(f'hatch_anims/{index}1_keys_{asset_name}_{chunk}.py')
            bones += [row[0].casefold() for row in literal_for(source, '(bone, P, R, S)')]
        assert len(bones) == len(set(bones)) == 42
        hatch.append({'asset': '/Game/SaskartaGaea/Characters/Traveller/Anims/' + asset_name,
                      'frames': frames, 'tracks': bones})
    add('01_hatch_animations.py', hatch, HATCH)

    for number, folder, asset, duration, body in [
        (2, 'CIN_19_HATCH', 'LS_CIN_19_Hatch', 36.0, 'Samyor_Hatch'),
        (3, 'CIN_24_TRANSMISSION', 'LS_CIN_24_Transmission', 207.0, 'Samyor_FullHead'),
        (4, 'CIN_25_END_CARD', 'LS_CIN_25_EndCard', 102.0, 'Samyor_FullHead')]:
        bindings, transforms, animations = [], {}, None
        for path in sorted((PACKET / folder).glob('*.py')):
            source = read(folder + '/' + path.name)
            tree = ast.parse(source)
            names = [ast.literal_eval(n.args[0]) for n in ast.walk(tree) if isinstance(n, ast.Call)
                     and isinstance(n.func, ast.Attribute) and n.func.attr == 'set_display_name']
            bindings += names
            for node in ast.walk(tree):
                if not isinstance(node, ast.For):
                    continue
                target = ast.unparse(node.target)
                if target == '(tick, vals, mode)':
                    keys = ast.literal_eval(node.iter)
                    transforms[names[0]] = {'key_count': len(keys), 'first': keys[0][1], 'last': keys[-1][1]}
                elif target == '(clip, t0, t1)':
                    animations = ast.literal_eval(node.iter)
        cuts = literal_for(read(folder + '/80_cuts.py'), '(t0, t1, cam, ease_in)')
        assert len(cuts) == 1 and cuts[0][0] == 0 and cuts[0][1] == duration
        add(f'{number:02d}_{folder}.py', {'id': folder, 'asset': '/Game/SaskartaGaea/GameFlow/Cinematics/' + asset,
            'duration': duration, 'body': body, 'camera': cuts[0][2], 'bindings': bindings,
            'animations': animations, 'transforms': transforms, 'fade_tracks': 0 if number == 2 else 1,
            'anchor': 'CIN19_BodyAnchor' if number == 2 else None}, CINEMATIC)

    effects = json.loads(read('sfx/manifest.json'))
    add('05_ending_sfx.py', [{key: row[key] for key in ('asset', 'duration_s', 'looping')} for row in effects], SFX)
    graph = json.loads(read('Traveller.third_person.json'))
    add('06_traveller_camera_defaults.py', {row['name']: float(row['default']) for row in graph['variables']}, TRAVELLER)
    OUT.mkdir(parents=True, exist_ok=True)
    for name, code in probes.items():
        (OUT / name).write_text(code, encoding='utf-8', newline='\n')
    evidence = {}
    for folder, groups in [('hatch_anims', 5), ('CIN_19_HATCH', 1), ('CIN_24_TRANSMISSION', 1),
                           ('CIN_25_END_CARD', 1), ('sfx', 7)]:
        path = PACKET / 'install_logs' / (folder + '.json')
        journal = json.loads(path.read_text(encoding='utf-8'))
        assert len(journal['completed']) == groups, folder
        evidence[folder] = {'journal_sha256': sha(path), 'completed_groups': groups,
                            'last_event_utc': journal['events'][-1]['utc']}
    traveller_receipt = PACKET / 'Traveller.third_person.install.json'
    receipt = json.loads(traveller_receipt.read_text(encoding='utf-8'))
    assert receipt['ok'] and receipt['assets'][0]['saved'] and receipt['assets'][0]['compile_ok']
    evidence['Traveller.third_person'] = {'receipt_sha256': sha(traveller_receipt)}
    manifest = {'scope': 'Prepared read-only metadata acceptance, not live pass or rendered/audio approval',
                'generator_sha256': sha(Path(__file__)), 'installation_evidence': evidence,
                'original_audit_sha256': sha(PACKET / 'preparation-audit.json'), 'inputs': inputs,
                'scripts': {name: sha(OUT / name) for name in probes},
                'expected_markers': ['ENDING_HATCH_ACCEPTANCE_OK clips 5 head_samples 30',
                    'ENDING_SEQUENCE_ACCEPTANCE_OK CIN_19_HATCH', 'ENDING_SEQUENCE_ACCEPTANCE_OK CIN_24_TRANSMISSION',
                    'ENDING_SEQUENCE_ACCEPTANCE_OK CIN_25_END_CARD', 'ENDING_SFX_ACCEPTANCE_OK waves 7 looped 1',
                    'ENDING_TRAVELLER_ACCEPTANCE_OK defaults 4 placed_actors']}
    (OUT / 'acceptance-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'directory': str(OUT), 'scripts': list(probes), 'original_packet_unchanged': True}))


if __name__ == '__main__':
    prepare()
