"""Prepare/check the two approved dawn-bearing fields; only root runs the packet.

Copies detached UE structs before editing and verifies every other field in the
containing arrays by normalized ExportText hashes. Does not reimport audio data.
"""
from pathlib import Path
import argparse
import ast
import json
import shutil

import install_ending_folder as bounded

ROOT = bounded.ROOT
PACKET = ROOT / 'Saved/Verification/dawn_bearing_20261001_v1'
TARGETS = {'story': '/Game/SaskartaGaea/Story/DA_Saskarta_Story',
           'look': '/Game/SaskartaGaea/Look/DA_Saskarta_LookKeys'}
FILES = ('Tools/GameFlow/editor/install_dawn_bearing.py',
         'Tools/GameFlow/editor/install_ending_folder.py', 'Tools/GameFlow/editor/ending_editor.py',
         'Tools/GameFlow/editor_gate.py', 'Tools/Look/apply_look.py', 'Tools/Perf/bounded_pie_profile.py',
         'Tools/GameFlow/gen_first_light_ending.py', 'docs/story/story-events.json', 'Tools/Look/look_keys.json',
         'Plugins/SaskartaCore/Source/SaskartaCore/Public/SaskartaEventTypes.h',
         'Plugins/SaskartaCore/Source/SaskartaCore/Public/SaskartaLookKeys.h')

HEAD = '''import unreal, json, struct, hashlib
def f32(value):
    return struct.unpack('<f',struct.pack('<f',float(value)))[0]
def locate(rows):
    field='id' if KIND=='story' else 'name'
    wanted='cin_24_transmission' if KIND=='story' else 'predawn'
    found=[i for i,row in enumerate(rows) if str(row.get_editor_property(field)).casefold()==wanted]
    assert len(found)==1,'Expected one target row'
    index=found[0]
    if KIND=='look':
        return index,-1,rows[index]
    cues=list(rows[index].get_editor_property('cues'))
    found=[i for i,cue in enumerate(cues) if cue.get_editor_property('type')==unreal.SaskartaActionType.PLAY_DAWN]
    assert len(found)==1,'Expected one PlayDawn cue'
    return index,found[0],cues[found[0]]
def revised(rows,value):
    # StructBase.copy is a detached copy; no asset property changes here.
    result=[row.copy() for row in rows]
    index,cue_index,target=locate(result)
    if KIND=='look':
        target.set_editor_property('sun_yaw',value)
    else:
        cues=[cue.copy() for cue in result[index].get_editor_property('cues')]
        cues[cue_index].set_editor_property('yaw',value)
        result[index].set_editor_property('cues',cues)
    return result
def fingerprint(rows):
    normalized=revised(rows,0.0)
    encoded=json.dumps([row.export_text() for row in normalized],separators=(',',':')).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()
def state(rows):
    index,cue_index,target=locate(rows)
    yaw=target.get_editor_property('yaw' if KIND=='story' else 'sun_yaw')
    return {'kind':KIND,'yaw':yaw,'other_fields_sha256':fingerprint(rows),'rows':len(rows)}
asset=unreal.load_asset(PACKAGE)
assert asset is not None
assert asset.get_class().get_name()==('SaskartaStoryAsset' if KIND=='story' else 'SaskartaLookKeys')
PROPERTY='cinematics' if KIND=='story' else 'keys'
rows=list(asset.get_editor_property(PROPERTY))
index,cue_index,target=locate(rows)
prior=state(rows)
assert prior['yaw'] in [f32(176.5),f32(18.66)],'Unexpected current bearing; inspect before changing'
if KIND=='story':
    assert rows[index].get_editor_property('duration_s')==f32(207.0)
    for name,value in [('at_s',0.0),('duration_s',120.0),('value',62.0),('pitch',-0.5)]:
        assert target.get_editor_property(name)==f32(value),name
    assert target.get_editor_property('keep_on_skip') is True
else:
    assert target.get_editor_property('road_m')==f32(4550.0)
    assert target.get_editor_property('sun_pitch')==f32(3.0)
'''

APPLY = '''updated=revised(rows,18.66)
assert fingerprint(updated)==prior['other_fields_sha256']
asset.set_editor_property(PROPERTY,updated)
rows=list(asset.get_editor_property(PROPERTY))
after=state(rows)
assert after['yaw']==f32(18.66)
assert after['other_fields_sha256']==prior['other_fields_sha256'],'Other fields changed'
assert [row.export_text() for row in rows]==[row.export_text() for row in updated]
print('DAWN_BEARING_STATE '+json.dumps(after))
'''


def source_hashes():
    return {str(ROOT/p):bounded.digest(ROOT/p) for p in FILES}


def source_bearing():
    story=json.loads((ROOT/'docs/story/story-events.json').read_text(encoding='utf-8'))
    cues=story['cinematics']['CIN_24_TRANSMISSION']['cues']
    dawn=[cue for cue in cues if cue['type']=='PlayDawn']
    looks=json.loads((ROOT/'Tools/Look/look_keys.json').read_text(encoding='utf-8'))
    before=[key for key in looks if key['name']=='PreDawn']
    assert len(dawn)==len(before)==1
    assert dawn[0]['yaw']==before[0]['sun']['yaw']==18.66
    return {'light_travel_yaw':18.66,'visible_disc_yaw':198.66}


def prepare():
    assert not PACKET.exists(),'Preserve existing packet; prepare a new explicit revision'
    expected=source_bearing();before=source_hashes();PACKET.mkdir(parents=True)
    for kind,package in TARGETS.items():
        folder=PACKET/kind;folder.mkdir()
        header=f'KIND={kind!r}\nPACKAGE={package!r}\n'+HEAD
        scripts={'00_preflight.py':header+"print('DAWN_BEARING_STATE '+json.dumps(prior))\n",
                 '10_apply.py':header+APPLY,
                 '90_save.py':f"import unreal\nsaved=unreal.EditorAssetLibrary.save_asset({package!r},only_if_is_dirty=False)\nassert saved is True\nprint('saved',saved)\n",
                 '99_read.py':header+"assert prior['yaw']==f32(18.66)\nprint('DAWN_BEARING_STATE '+json.dumps(prior))\n"}
        for name,code in scripts.items():
            code+=f"print('DAWN_BEARING_OK {kind} {name}')\n"
            ast.parse(code);assert not bounded.editor.banned(code),name
            (folder/name).write_text(code,encoding='utf-8')
    assert before==source_hashes(),'Source changed during preparation'
    historical=[ROOT/'Saved/Verification/radio_recovery_20261001/data_v3/manifest.json',
                ROOT/'Saved/Verification/radio_recovery_20261001/install-0d7c9ce516d5.json']
    bounded.save_state(PACKET/'manifest.json',dict(status='prepared_not_installed',expected=expected,
        source_sha256=before,script_sha256={p.relative_to(PACKET).as_posix():bounded.digest(p) for p in PACKET.rglob('*.py')},
        preserved_audio_v3={str(p):bounded.digest(p) for p in historical},
        scope='Only PreDawn.sun_yaw and CIN24 PlayDawn.yaw; detached struct copies preserve other fields. No full Story/Look/audio reimport.'))


def check(kind):
    manifest_path=PACKET/'manifest.json';m=json.loads(manifest_path.read_text())
    assert source_bearing()==m['expected'] and source_hashes()==m['source_sha256'],'Source changed'
    assert all(bounded.digest(Path(p))==h for p,h in m['preserved_audio_v3'].items()),'Original audio receipt changed'
    scripts={Path(p).name:h for p,h in m['script_sha256'].items() if Path(p).parent.as_posix()==kind}
    assert set(scripts)=={p.name for p in (PACKET/kind).glob('*.py')}
    for name,h in scripts.items():
        p=PACKET/kind/name;assert bounded.digest(p)==h,name
        ast.parse(p.read_text());assert not bounded.editor.banned(p.read_text())
    bounded.require_writable(bounded.package_file(TARGETS[kind],ROOT))
    return dict(folder=kind,prepared=str(PACKET),audit_sha256=bounded.digest(manifest_path),script_sha256=scripts,
                input_sha256={**m['source_sha256'],str(manifest_path):bounded.digest(manifest_path)},
                groups=[dict(id=kind,steps=['00_preflight.py','10_apply.py','90_save.py','99_read.py'],package=TARGETS[kind])])


def run(kind,owner):
    plan=check(kind);connection=bounded.EditorConnection(owner)
    journal=PACKET/'install_logs'/(kind+'.json');backup=PACKET/'backups'/kind
    if not journal.exists() and not backup.exists():
        connection.guard();backup.mkdir(parents=True)
        original=bounded.package_file(TARGETS[kind],ROOT);hashes={}
        for suffix in ('.uasset','.uexp','.ubulk'):
            p=original.with_suffix(suffix)
            if p.is_file():shutil.copy2(p,backup/p.name);hashes[p.name]=bounded.digest(p)
        bounded.save_state(backup/'before.json',hashes)
    baseline=None
    def guard():
        check(kind);connection.guard()
    def send(code,name):
        nonlocal baseline
        output=connection.send(code,name)
        assert f'DAWN_BEARING_OK {kind} {name}' in output,'Missing output marker'
        if name!='90_save.py':
            lines=[line.removeprefix('DAWN_BEARING_STATE ') for line in output.splitlines() if line.startswith('DAWN_BEARING_STATE ')]
            assert len(lines)==1,'Missing state readback'
            value=json.loads(lines[0]);assert value['kind']==kind
            if name=='00_preflight.py':baseline=value['other_fields_sha256']
            assert baseline==value['other_fields_sha256'],'Unrelated containing-array fields changed across chunks'
        return output
    return bounded.run_plan(plan,journal,send,guard,max_groups=1)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['prepare','check','run'])
    parser.add_argument('--folder',choices=list(TARGETS));parser.add_argument('--owner')
    args=parser.parse_args()
    if args.mode=='prepare':prepare()
    if args.mode=='run':
        if not args.folder or not args.owner:parser.error('run requires one --folder and the existing root --owner')
        run(args.folder,args.owner)
    else:
        plans=[check(kind) for kind in ([args.folder] if args.folder else TARGETS)]
        print(json.dumps({'packet':str(PACKET),'manifest_sha256':bounded.digest(PACKET/'manifest.json'),
                          'folders':[p['folder'] for p in plans]},indent=2))


if __name__=='__main__':main()
