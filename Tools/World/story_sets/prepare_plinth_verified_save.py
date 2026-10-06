"""Prepare an exact external-package save after contact and root visual acceptance."""
from pathlib import Path
import argparse
import ast
import json
import hashlib

ROOT=Path(__file__).resolve().parents[3]
BASE=ROOT/'Saved/Tripo/20261001/station_plinths'

def read(path,marker='S26_LEVEL_PLINTH '):
    envelope=json.loads(path.read_text(encoding='utf-8'))
    assert envelope['status']=='ok',path
    rows=[json.loads(line.split(marker,1)[1]) for line in envelope['output'].splitlines() if line.startswith(marker)]
    assert len(rows)==1,path
    return rows[0]

EDITOR='''import unreal,json,datetime
es=unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
assert es.get_game_world() is None,'Stop PIE before the accepted prop save'
world=es.get_editor_world();assert world.get_name()=='Saskarta_WP'
EXPECTED=__EXPECTED__
CONTACTS=__CONTACTS__
SUPPORT_REFERENCES=__SUPPORT_REFERENCES__
started=datetime.datetime.now(datetime.timezone.utc)
actors=list(unreal.EditorLevelLibrary.get_all_level_actors())
assert len(actors)<2500
packages=[];owners={}
for row in EXPECTED:
 matches=[a for a in actors if a.get_path_name()==row['actor']]
 assert len(matches)==1,'Exact accepted actor missing'
 a=matches[0]
 assert 'S26_LEVEL_PLINTH_20261001' in [str(t) for t in a.tags]
 assert a.get_package().get_name()==row['package'] and row['package'].startswith('/Game/__ExternalActors__/level/Saskarta_WP/'),'Package ownership differs'
 assert a.get_actor_transform().export_text()==row['transform'],'Actor moved since accepted contact verification'
 packages.append(a.get_package());owners[row['actor']]=a
assert len({p.get_name() for p in packages})==len(EXPECTED),'One exact external package per actor required'
supports=dict(owners)
for row in SUPPORT_REFERENCES:
 matches=[a for a in actors if a.get_path_name()==row['actor']];assert len(matches)==1,'Known corner support disappeared'
 a=matches[0]
 assert 'S26_LEVEL_PLINTH_20261001' in [str(t) for t in a.tags] and 'S26_FLAT_COPING_V1' in [str(t) for t in a.tags]
 assert a.get_package().get_name()==row['package'] and a.get_actor_transform().export_text()==row['transform'],'Referenced corner support changed'
 assert a.static_mesh_component.static_mesh.get_path_name()==row['mesh'] and a.static_mesh_component.get_material(0).get_path_name()==row['material']
 supports[row['actor']]=a
for row in CONTACTS:
 body=owners[row['body']]
 ignored=[body]
 for ref in row.get('body_references',[]):
  matches=[a for a in actors if a.get_path_name()==ref['actor']];assert len(matches)==1,'Joined fence body disappeared'
  a=matches[0]
  assert a.get_package().get_name()==ref['package'] and a.get_actor_transform().export_text()==ref['transform']
  assert 'S26_LEVEL_PLINTH_20261001' in [str(t) for t in a.tags] and 'S26_FLAT_COPING_V1' in [str(t) for t in a.tags]
  assert a.static_mesh_component.static_mesh.get_path_name()==ref['mesh'],'Joined fence geometry changed'
  ignored.append(a)
 for measured in row['points']:
  assert (datetime.datetime.now(datetime.timezone.utc)-started).total_seconds()<3.5,'Bounded contact save check exceeded'
  p=measured['point']
  # Accepted feet are within4cm of their own support. Stay around the foot so
  # a later overhead rail cannot be mistaken for the load-bearing surface.
  hit=unreal.SystemLibrary.line_trace_single(world,unreal.Vector(p[0],p[1],p[2]+5),unreal.Vector(p[0],p[1],p[2]-10),unreal.TraceTypeQuery.TRACE_TYPE_QUERY1,True,ignored,unreal.DrawDebugTrace.NONE,True)
  if isinstance(hit,tuple) and len(hit)==2 and not isinstance(hit[0],unreal.HitResult):hit=hit[1] if hit[0] else None
  assert hit is not None and hit.to_tuple()[0],'Current owned support missing before save'
  h=hit.to_tuple();support=h[9]
  assert support is not None and support.get_path_name()==measured['actor'] and support.get_path_name() in supports,'Support ownership changed'
  gap=p[2]-h[5].z
  assert -4<=gap<=4 and abs(gap-measured['clearance_cm'])<.25,'Actual surface contact changed since accepted verification'
__PASSAGE__
ok=unreal.EditorLoadingAndSavingUtils.save_packages(packages,True)
assert ok,'Scoped external-package save failed'
print('S26_VERIFIED_PROPS_SAVED '+json.dumps({'packages':[p.get_name() for p in packages],'saved':bool(ok),'actors':len(EXPECTED),'contacts':sum(len(c['points']) for c in CONTACTS)},separators=(',',':')))
'''

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--ids',nargs='+',default=['Transmitter','Biofuel00','Biofuel01'])
    ap.add_argument('--apply-results',nargs='+',type=Path,help='Initial then any correction receipts for at most3props')
    ap.add_argument('--verify-results',nargs='+',type=Path,help='One final passing verification receipt per prop')
    ap.add_argument('--gate-passage-result',type=Path,help='Passing actual capsule passage receipt required for Gate')
    ap.add_argument('--gate-passage-script',type=Path,help='Reviewed final passage script to repeat before save (for a measured bent approach)')
    ap.add_argument('--name',default='initial_three_after_visual_acceptance',help='Unique output script name; avoids overwriting earlier reviewed packets')
    args=ap.parse_args()
    merged={};contacts=[];sources={};support_references={}
    assert args.name.replace('_','').isalnum(),'Simple script name required'
    final_gate_body=None
    if args.apply_results or args.verify_results:
        assert args.apply_results and args.verify_results,'Apply and verified contact receipts both required'
        applies={};checks={}
        for path in args.apply_results:
            r=read(path);assert r['applied']
            applies.setdefault(r['id'],[]).append(r)
            sources[str(path.resolve().relative_to(ROOT))]=hashlib.sha256(path.read_bytes()).hexdigest()
        for path in args.verify_results:
            r=read(path)
            assert r['id'] not in checks and r['surface_contact_pass'] and r['verified_transforms'],'Unique passing final contact proof required'
            checks[r['id']]=r
            sources[str(path.resolve().relative_to(ROOT))]=hashlib.sha256(path.read_bytes()).hexdigest()
        assert set(applies)==set(checks) and 1<=len(checks)<=3,'At most3complete prop receipts per bounded save'
        args.ids=list(checks)
        for name,check in checks.items():
            chunks=applies[name]
            assert len(chunks[0]['changed'])==len(check['pads'])+1,'Initial complete prop+stone receipt required'
            assert abs(chunks[-1]['body_z']-check['body_z'])<.0001,'Final contact proof refers to another prop height'
            for r in chunks:
                for row in r['changed']:merged[row['actor']]=row
            body=chunks[-1]['changed'][-1]['actor']
            contacts.append({'body':body,'points':check['surface_contacts'],'body_references':check.get('contact_body_references',[])})
            assert all(p['owned_footing'] for p in check['surface_contacts'])
            for ref in check.get('support_references',[]):support_references[ref['actor']]=ref
            if name=='Gate':final_gate_body=body
            else:assert not check.get('gate_collision_acceptance_pending')
        assert len(merged)==sum(len(c['pads'])+1 for c in checks.values()),'Exact initial package set required'
    else:
      for name in args.ids:
        assert name.isalnum(),'Exact simple prop IDs only'
        initial=BASE/'initial_apply_readbacks'/f'{name}.readback.json'
        corrected=BASE/'contact_apply_readbacks'/f'{name}.readback.json'
        checked=BASE/'contact_verify_readbacks'/f'{name}.readback.json'
        receipts=[read(p) for p in (initial,corrected,checked)]
        assert all(r['id']==name for r in receipts)
        check=receipts[2]
        assert check['surface_contact_pass'] and check['verified_transforms'] and not check.get('gate_collision_acceptance_pending')
        for r in receipts[:2]:
            assert r['applied']
            for row in r['changed']:merged[row['actor']]=row
        assert len(receipts[1]['changed'])==1,'Narrow prop-only correction receipt required'
        contacts.append({'body':receipts[1]['changed'][0]['actor'],'points':check['surface_contacts']})
        for p in (initial,corrected,checked):sources[str(p.relative_to(ROOT))]=hashlib.sha256(p.read_bytes()).hexdigest()
      assert len(merged)==len(args.ids)*2,'This packet expects one prop and one stone each'
    passage=''
    if final_gate_body:
        assert args.gate_passage_result,'Gate save requires its actual capsule passage proof'
        gate=read(args.gate_passage_result,'S26_GATE_PASSAGE ')
        assert gate['pass'] and gate['gate']==final_gate_body,'Gate capsule passage proof failed or identifies another actor'
        path=args.gate_passage_result
        sources[str(path.resolve().relative_to(ROOT))]=hashlib.sha256(path.read_bytes()).hexdigest()
        source=args.gate_passage_script or ROOT/'Tools/World/story_sets/verify_summit_gate_passage.py'
        source=source.resolve()
        assert source.is_relative_to(ROOT) and source.suffix=='.py','Passage source must belong to this project'
        if args.gate_passage_script:
            proof=json.loads(args.gate_passage_result.read_text(encoding='utf-8'))
            assert Path(proof['script']).resolve()==source and proof['sha256']==hashlib.sha256(source.read_bytes()).hexdigest(),'Final passage receipt must identify the exact recheck script'
        lines=source.read_text(encoding='utf-8').splitlines()
        passage='def recheck_gate_passage():\n'+'\n'.join(' '+line for line in lines)+"\n assert all(r['pass'] for r in rows),'Gate passage changed before save'\nrecheck_gate_passage()\n"
        sources[str(source.relative_to(ROOT))]=hashlib.sha256(source.read_bytes()).hexdigest()
    code=EDITOR.replace('__EXPECTED__',repr(list(merged.values()))).replace('__CONTACTS__',repr(contacts)).replace('__SUPPORT_REFERENCES__',repr(list(support_references.values()))).replace('__PASSAGE__',passage)
    ast.parse(code)
    out=BASE/'save_verified';out.mkdir(parents=True,exist_ok=True)
    path=out/(args.name+'.py');path.write_text(code,encoding='utf-8')
    (out/(args.name+'_manifest.json')).write_text(json.dumps({'script':str(path.relative_to(ROOT)),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'ids':args.ids,'visual_acceptance_required_before_execution':True,'packages':[v['package'] for v in merged.values()],'receipts':sources},indent=2)+'\n',encoding='utf-8')
    print(path)

if __name__=='__main__':main()
