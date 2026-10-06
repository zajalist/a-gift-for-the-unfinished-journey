"""Prepare/check current ending body assets; install one guarded save group.

Preparation and check are offline. Run mode is for the sole editor writer under
its existing exclusive global lease. Old ending packets and journals stay intact.
"""
from pathlib import Path
import argparse
import ast
import json
import sys

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PACKET = ROOT/'Saved/Verification/ending_body_fix_20261001_v2'
sys.path.insert(0,str(ROOT/'Tools/GameFlow/editor'))
import install_ending_folder as bounded
import samyor_reveal as hatch
import samyor_final as final
import samyor_notice as notice
import build_cinematics as bc
import prepare_ending_acceptance as acceptance

FOLDERS = ('hatch','final','notice','CIN_19_HATCH','CIN_24_TRANSMISSION','CIN_25_END_CARD')
SOURCES = ('Tools/Cinematics/install_body_contact_fix.py',
           'Tools/Cinematics/samyor_reveal.py','Tools/Cinematics/samyor_final.py',
           'Tools/Cinematics/samyor_notice.py','Tools/Cinematics/traveller_contacts.py',
           'Tools/Cinematics/build_cinematics.py','Tools/Cinematics/prepare_ending_acceptance.py',
           'Tools/Cinematics/traveller_ref_pose.json','Tools/Cinematics/traveller_pose_samples.json',
           'Tools/Cinematics/probe_ending.json','docs/story/CREDITS_SCREEN.md',
           'SourceArt/Characters/Traveller/traveller01_animated.fbx')


def sources():
    return {str(ROOT/name):bounded.digest(ROOT/name) for name in SOURCES}


def sequence_readback(folder):
    plan=bc.PLANS[folder.name]()
    bindings,transforms,animations=[],{},None
    for path in sorted(folder.glob('*.py')):
        tree=ast.parse(path.read_text())
        names=[ast.literal_eval(n.args[0]) for n in ast.walk(tree)
               if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)
               and n.func.attr=='set_display_name']
        bindings+=names
        for node in ast.walk(tree):
            if not isinstance(node,ast.For):continue
            target=ast.unparse(node.target)
            if target=='(tick, vals, mode)':
                keys=ast.literal_eval(node.iter)
                transforms[names[0]]=dict(key_count=len(keys),first=keys[0][1],last=keys[-1][1])
            elif target=='(clip, t0, t1)': animations=ast.literal_eval(node.iter)
    cuts=acceptance.literal_for((folder/'80_cuts.py').read_text(),'(t0, t1, cam, ease_in)')
    assert len(cuts)==1
    expected=dict(id=folder.name,asset=bc.FOLDER+'/'+plan['asset'],duration=plan['duration'],
                  body='Samyor_Hatch' if folder.name=='CIN_19_HATCH' else 'Samyor_FullHead',
                  camera=cuts[0][2],bindings=bindings,animations=animations,transforms=transforms,
                  fade_tracks=int(bool(plan.get('fade'))),
                  anchor='CIN19_BodyAnchor' if folder.name=='CIN_19_HATCH' else None)
    return acceptance.COMMON+'EXPECTED = '+repr(expected)+'\n'+acceptance.CINEMATIC


def prepare(packet):
    if packet.exists():
        raise ValueError('Preserve prepared packets; use a new --packet revision: '+str(packet))
    packet.mkdir(parents=True)
    hatch.emit_anims(packet/'hatch')
    final.emit_anims(packet/'final')
    notice.emit_anims(packet/'notice')
    expected=[dict(asset=hatch.ANIM_DIR+'/'+name,frames=n,tracks=[b.casefold() for b in tracks])
              for name,(n,tracks) in hatch.bake().items()]
    (packet/'hatch/99_read.py').write_text(acceptance.COMMON+'EXPECTED = '+repr(expected)+'\n'+acceptance.HATCH)
    for folder in FOLDERS[3:]:
        assert bc.emit(folder,packet/folder)==0
        (packet/folder/'99_read.py').write_text(sequence_readback(packet/folder))
    scripts={p.relative_to(packet).as_posix():bounded.digest(p) for p in packet.rglob('*.py')}
    manifest=dict(status='prepared_not_installed',source_sha256=sources(),script_sha256=scripts,
                  required_order=list(FOLDERS),scope='Animation/sequence metadata only; pose and viewport acceptance still required.')
    bounded.save_state(packet/'manifest.json',manifest)
    return [check(packet,folder) for folder in FOLDERS]


def check(packet,folder):
    if folder not in FOLDERS:raise ValueError(folder)
    manifest_path=packet/'manifest.json'
    manifest=json.loads(manifest_path.read_text())
    if manifest['source_sha256']!=sources():
        raise ValueError('Source changed since preparation. Coordinate a fresh packet revision before installing.')
    expected={Path(p).name:h for p,h in manifest['script_sha256'].items() if Path(p).parent.as_posix()==folder}
    if set(expected)!={p.name for p in (packet/folder).glob('*.py')}:
        raise ValueError('Prepared file list changed: '+folder)
    codes={}
    for name,digest in expected.items():
        path=packet/folder/name
        if bounded.digest(path)!=digest:raise ValueError('Prepared script changed: '+name)
        code=path.read_text();compile(code,name,'exec')
        if bounded.editor.banned(code):raise ValueError('Forbidden editor operation: '+name)
        codes[name]=code
    groups,pending=[],[]
    for name in sorted(codes):
        pending.append(name)
        if bounded.is_save(name):
            package=bounded.target_of_save(codes[name])
            bounded.require_writable(bounded.package_file(package,ROOT))
            groups.append(dict(id=name,steps=pending,package=package));pending=[]
    assert pending==['99_read.py'] and groups
    groups[-1]['steps']+=pending
    return dict(folder=folder,prepared=str(packet),audit_sha256=bounded.digest(manifest_path),
                script_sha256=expected,input_sha256=manifest['source_sha256'],groups=groups)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=('prepare','check','run'))
    parser.add_argument('--packet',type=Path,default=DEFAULT_PACKET)
    parser.add_argument('--folder',choices=FOLDERS)
    parser.add_argument('--owner')
    parser.add_argument('--max-groups',type=int,default=1)
    args=parser.parse_args();packet=args.packet.resolve()
    if args.mode=='prepare':plans=prepare(packet)
    else:plans=[check(packet,f) for f in ((args.folder,) if args.folder else FOLDERS)]
    if args.mode!='run':
        print(json.dumps(dict(packet=str(packet),folders=[dict(folder=p['folder'],groups=len(p['groups']),scripts=len(p['script_sha256'])) for p in plans]),indent=2));return
    if not args.owner or not args.folder:parser.error('run requires --folder and the existing lease --owner')
    connection=bounded.EditorConnection(args.owner)
    def guard():
        check(packet,args.folder)
        connection.guard()
    bounded.run_plan(plans[0],packet/'install_logs'/(args.folder+'.json'),connection.send,guard,max_groups=args.max_groups)


if __name__=='__main__':
    main()
