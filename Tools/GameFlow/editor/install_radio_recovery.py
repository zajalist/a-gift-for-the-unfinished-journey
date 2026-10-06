"""Prepare/check the radio recovery data packet offline; only the sole editor owner runs it.

Uses the established bounded ending transport/lease/PIE/fault/save guards. Native build
must precede run (new cinematic keep_station_playing field). Original ending packets
are untouched. Re-prepare if another story owner changes an importer input.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import install_cin19_story as story_packet
import install_ending_folder as bounded

ROOT = bounded.ROOT
PACKET = ROOT / 'Saved/Verification/radio_recovery_20261001/data_v3'
PANIC = ROOT / 'Saved/Verification/storm_panic_20261001'
STORY = story_packet.PACKAGE
STATION = '/Game/SaskartaGaea/Audio/Station/DA_Station'
POLICY = ('CIN_04_DUST_FRONT', 'CIN_06_ROAD_AHEAD', 'CIN_11_WAYSTATION',
          'CIN_P04_AIRSHIP', 'CIN_P07_WAITING_WATER', 'CIN_06F_CREST_FORT',
          'CIN_P15_WORKS', 'CIN_P17_CISTERN', 'CIN_PO01_LOW_VOICE')


def inputs():
    result = story_packet.inputs(ROOT)
    extra = [ROOT / 'docs/story/station.json', Path(__file__).resolve(),
             ROOT / 'Plugins/SaskartaCore/Source/SaskartaCore/Public/SaskartaEventTypes.h',
             ROOT / 'Plugins/SaskartaCore/Source/SaskartaCore/Private/SaskartaStoryImport.cpp']
    extra += sorted((ROOT / 'SourceArt/Audio/StationSongs').glob('*.json'))
    result.update({str(path): bounded.digest(path) for path in extra})
    return result


def prepare():
    data = json.loads((ROOT / 'docs/story/story-events.json').read_text(encoding='utf-8'))
    lines = json.loads((ROOT / 'docs/story/carrier-voice-lines.json').read_text(encoding='utf-8'))['lines']
    captions = {line['id']: line['text'] for line in lines if line['id'].startswith('CV_STORM_PANIC_')}
    assert len(captions) == 6
    assert {cid for cid, c in data['cinematics'].items() if c.get('keep_station_playing')} == set(POLICY)
    base = story_packet.scripts(data['cinematics']['CIN_19_HATCH'])
    names = {'00_apply.py': '10_story_apply.py', '90_save.py': '90_save_story.py', '99_read.py': '99_story_read.py'}
    scripts = {names[name]: code for name, code in base.items()}
    scripts['99_story_read.py'] = scripts['99_story_read.py'].replace(
        "str(c.get_editor_property('id')) == 'CIN_19_HATCH'", "str(c.get_editor_property('id')).casefold() == 'cin_19_hatch'").replace(
        "str(action.get_editor_property('id')) == row[1]", "str(action.get_editor_property('id')).casefold() == row[1].casefold()")
    scripts['99_story_read.py'] += f"""
policies={{str(c.get_editor_property('id')).casefold():c.get_editor_property('keep_station_playing') for c in asset.get_editor_property('cinematics')}}
assert {{k for k,v in policies.items() if v}}=={{k.casefold() for k in {POLICY!r}}},str(policies)
lines={{str(x.get_editor_property('id')).casefold():x for x in asset.get_editor_property('lines')}}
for key,text in {captions!r}.items():
    row=lines[key.casefold()]
    assert row.get_editor_property('english')==text,key
    assert row.get_editor_property('carrier') is True,key
print('RADIO_STORY_RECOVERY_OK nine continuous scenes, six English carrier captions, ending policy preserved')
"""
    timings = [(q['id'], q['at_s']) for q in data['cinematics']['CIN_24_TRANSMISSION']['cues']
               if q['type'] == 'PlayRadioLine']
    scripts['99_story_read.py'] += f"""
cinematics={{str(c.get_editor_property('id')).casefold():c for c in asset.get_editor_property('cinematics')}}
transmit=cinematics['cin_24_transmission']
assert abs(transmit.get_editor_property('duration_s')-207.0)<0.001
actual=[(str(q.get_editor_property('id')).casefold(),q.get_editor_property('at_s')) for q in transmit.get_editor_property('cues') if q.get_editor_property('type')==unreal.SaskartaActionType.PLAY_RADIO_LINE]
wanted={timings!r}
assert len(actual)==len(wanted)==33,str(actual)
for pair,want in zip(actual,wanted):
    assert pair[0]==want[0].casefold() and abs(pair[1]-want[1])<0.002,str((pair,want))
credits=cinematics['cin_25_end_card']
fade=[q for q in credits.get_editor_property('cues') if q.get_editor_property('type')==unreal.SaskartaActionType.STOP_SFX and str(q.get_editor_property('id')).casefold()=='eyetae_title']
assert len(fade)==1
assert abs(fade[0].get_editor_property('at_s')-99.0)<0.001 and abs(fade[0].get_editor_property('duration_s')-3.0)<0.001
print('FINAL_AUDIO_TIMING_OK all 33 full recorded lines, 207s ending, one 3s music fade at99')
"""
    header = f"import unreal\nasset=unreal.load_asset({STATION!r})\nassert asset is not None\n"
    scripts['20_station_apply.py'] = header + "report=unreal.SaskartaStationImport.import_station_from_files(asset,unreal.Paths.project_dir())\nassert report is not None\nprint('RADIO_STATION_IMPORTED',str(report))\n"
    scripts['90_save_station.py'] = header + "assert unreal.EditorAssetLibrary.save_loaded_asset(asset,False) is True\nprint('RADIO_STATION_SAVED saved True')\n"
    scripts['99_station_read.py'] = header + """c=asset.get_editor_property('config')
assert str(c.get_editor_property('start_event')).casefold()=='b01_boot_handover'
assert c.get_editor_property('start_road_m')==0
assert len(c.get_editor_property('segments'))==269
assert len(c.get_editor_property('songs'))==3
print('RADIO_STATION_RECOVERY_OK B01 start, 269 segments, 3 songs')
"""
    PACKET.mkdir(parents=True, exist_ok=True)
    for name, code in scripts.items():
        compile(code, name, 'exec')
        assert not bounded.editor.banned(code), name
        (PACKET / name).write_text(code, encoding='utf-8')
    bounded.save_state(PACKET / 'manifest.json', {
        'status': 'prepared_not_installed', 'source_sha256': inputs(),
        'script_sha256': {name: bounded.digest(PACKET / name) for name in scripts},
        'continuous_radio_cinematics': POLICY, 'panic_captions': captions,
    })
    return check()


def check():
    manifest_path = PACKET / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    if manifest['source_sha256'] != inputs():
        raise ValueError('Importer inputs changed: coordinate and re-prepare before installation')
    expected = manifest['script_sha256']
    assert set(expected) == {p.name for p in PACKET.glob('*.py')}
    for name, digest in expected.items():
        assert bounded.digest(PACKET / name) == digest, name
    return {'folder': PACKET.name, 'prepared': str(PACKET.parent),
            'audit_sha256': bounded.digest(manifest_path), 'script_sha256': expected,
            'input_sha256': {p: h for p, h in manifest['source_sha256'].items() if h is not None},
            'groups': [{'id': 'story', 'steps': ['10_story_apply.py', '90_save_story.py', '99_story_read.py'], 'package': STORY},
                       {'id': 'station', 'steps': ['20_station_apply.py', '90_save_station.py', '99_station_read.py'], 'package': STATION}]}


def check_panic():
    manifest_path = PANIC / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    folder = PANIC / manifest['install_folder']
    expected = manifest['scripts_sha256']
    assert set(expected) == {p.name for p in folder.glob('*.py')}
    source = {str(ROOT / name): digest for name, digest in manifest['source_sha256'].items()}
    source.update({row['wav']: row['wav_sha256'] for row in manifest['rows']})
    for path, digest in source.items():
        assert bounded.digest(Path(path)) == digest, path
    for name, digest in expected.items():
        assert bounded.digest(folder / name) == digest, name
    groups = []
    for i, row in enumerate(manifest['rows']):
        steps = [row['import_step'], row['save_step']]
        if i == 0: steps.insert(0, '00_preflight.py')
        if i == len(manifest['rows'])-1: steps.append('99_readback.py')
        groups.append({'id': row['id'], 'steps': steps, 'package': row['asset']})
    return {'folder': folder.name, 'prepared': str(PANIC), 'audit_sha256': bounded.digest(manifest_path),
            'script_sha256': expected, 'input_sha256': source, 'groups': groups}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('prepare', 'check', 'run'))
    parser.add_argument('--owner')
    parser.add_argument('--panic', action='store_true', help='Use the separately prepared existing panic WAV packet')
    args = parser.parse_args()
    if args.panic and args.mode == 'prepare':
        parser.error('Prepare panic WAVs with Tools/Audio/prepare_storm_panic.py --allow-partial')
    check_selected = check_panic if args.panic else check
    plan = prepare() if args.mode == 'prepare' else check_selected()
    if args.mode != 'run':
        print(json.dumps(plan, indent=2))
        return
    if not args.owner:
        parser.error('run requires the existing global lease owner')
    connection = bounded.EditorConnection(args.owner)
    def guard():
        check_selected()
        connection.guard()
    journal_root = PANIC if args.panic else PACKET.parent
    bounded.run_plan(plan, journal_root / ('install-' + plan['audit_sha256'][:12] + '.json'), connection.send, guard)


if __name__ == '__main__':
    main()
