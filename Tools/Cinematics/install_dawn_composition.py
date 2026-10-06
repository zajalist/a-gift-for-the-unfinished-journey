"""Prepare and install only the coordinated dawn gestures and CIN24/25.

Offline preparation is separate from the root writer's guarded install. Preserve
all previous packets and import journals; choose a new directory per revision.
"""
from pathlib import Path
import argparse
import ast
import json
import install_body_contact_fix as body
import samyor_final as final
import samyor_notice as notice
import samyor_dawn_turn as turn
import prepare_transform_diagnostic as transforms
import prepare_body_acceptance_v3 as binding_fix
import prepare_body_acceptance_v4 as precision

ROOT=body.ROOT
bounded=body.bounded
FOLDERS=('final','notice','turn','CIN_24_TRANSMISSION','CIN_25_END_CARD')
SOURCES=body.SOURCES+('Tools/Cinematics/install_dawn_composition.py',
    'Tools/Cinematics/samyor_dawn_turn.py','Tools/Cinematics/traveller_gaze.py',
    'Tools/Cinematics/ending_staging.py','Tools/Cinematics/prepare_transform_diagnostic.py',
    'Tools/Cinematics/traveller_walk_exit_pose.json',
    'Tools/Cinematics/traveller_terrain.py',
    'Tools/Cinematics/prepare_body_acceptance_v3.py','Tools/Cinematics/prepare_body_acceptance_v4.py')


def sources():
    return {str(ROOT/name):bounded.digest(ROOT/name) for name in SOURCES}


def sequence_readback(folder):
    code=body.sequence_readback(folder)
    assert code.count(binding_fix.OLD)==1
    code=code.replace(binding_fix.OLD,binding_fix.NEW)
    rows=dict(row for path in folder.glob('*.py') if (row:=transforms.transform_rows(path)) is not None)
    code=code.replace('import json\n','import json\nimport struct\n',1)
    code=code.replace('EXPECTED = ',precision.HELPER+'ALL_TRANSFORMS = '+repr(rows)+'\nEXPECTED = ',1)
    old="near(first, wanted['first'][index], 0.01) and near(last, wanted['last'][index], 0.01)"
    assert code.count(old)==1
    code=code.replace(old,"key_near(first, wanted['first'][index]) and key_near(last, wanted['last'][index])")
    line="        first, last = keys[0].get_value(), keys[-1].get_value()"
    code=code.replace(line,"""        for key_index, key in enumerate(keys):
            authored=ALL_TRANSFORMS[name][key_index][1][index]
            require(key_near(key.get_value(), authored), name+' exact observable transform key', [index,key_index,key.get_value(),authored])
"""+line)
    return code


def prepare(packet):
    if packet.exists():raise ValueError('Preserve packets; select a new revision: '+str(packet))
    packet.mkdir(parents=True)
    final.emit_anims(packet/'final');notice.emit_anims(packet/'notice');turn.emit_anims(packet/'turn')
    for folder in FOLDERS[:3]:
        for script in (packet/folder).glob('*create*.py'):
            script.write_text(script.read_text()+"\nan.set_editor_property('rate_scale',1.0)\n")
    for folder in FOLDERS[3:]:
        assert body.bc.emit(folder,packet/folder)==0
        (packet/folder/'99_read.py').write_text(sequence_readback(packet/folder))
    scripts={p.relative_to(packet).as_posix():bounded.digest(p) for p in packet.rglob('*.py')}
    manifest=dict(status='prepared_not_installed',source_sha256=sources(),script_sha256=scripts,
                  required_order=list(FOLDERS),scope='Dawn head/steps/collapse/camera metadata. Actual terrain contact and rendered framing still require acceptance.')
    bounded.save_state(packet/'manifest.json',manifest)
    return [check(packet,folder) for folder in FOLDERS]


def check(packet,folder):
    if folder not in FOLDERS:raise ValueError(folder)
    path=packet/'manifest.json';manifest=json.loads(path.read_text())
    if manifest['source_sha256']!=sources():raise ValueError('Prepared source changed; use a new packet revision')
    expected={Path(p).name:h for p,h in manifest['script_sha256'].items() if Path(p).parent.as_posix()==folder}
    if set(expected)!={p.name for p in (packet/folder).glob('*.py')}:raise ValueError('Packet file list changed')
    codes={}
    for name,digest in expected.items():
        script=packet/folder/name
        if bounded.digest(script)!=digest:raise ValueError('Packet changed: '+name)
        code=script.read_text();compile(code,name,'exec')
        if bounded.editor.banned(code):raise ValueError('Forbidden editor operation: '+name)
        codes[name]=code
    groups,pending=[],[]
    for name in sorted(codes):
        pending.append(name)
        if bounded.is_save(name):
            package=bounded.target_of_save(codes[name]);bounded.require_writable(bounded.package_file(package,ROOT))
            groups.append(dict(id=name,steps=pending,package=package));pending=[]
    assert pending==['99_read.py'] and groups
    groups[-1]['steps']+=pending
    return dict(folder=folder,prepared=str(packet),audit_sha256=bounded.digest(path),
                script_sha256=expected,input_sha256=manifest['source_sha256'],groups=groups)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode',choices=('prepare','check','run'))
    p.add_argument('--packet',type=Path,required=True)
    p.add_argument('--folder',choices=FOLDERS);p.add_argument('--owner');p.add_argument('--max-groups',type=int,default=1)
    args=p.parse_args();packet=args.packet.resolve()
    plans=prepare(packet) if args.mode=='prepare' else [check(packet,f) for f in ((args.folder,) if args.folder else FOLDERS)]
    if args.mode!='run':
        print(json.dumps(dict(packet=str(packet),folders=[dict(folder=x['folder'],groups=len(x['groups']),scripts=len(x['script_sha256'])) for x in plans]),indent=2));return
    if not args.owner or not args.folder:p.error('run requires the existing --owner and --folder')
    connection=bounded.EditorConnection(args.owner)
    def guard():check(packet,args.folder);connection.guard()
    bounded.run_plan(plans[0],packet/'install_logs'/(args.folder+'.json'),connection.send,guard,max_groups=args.max_groups)


if __name__=='__main__':main()
