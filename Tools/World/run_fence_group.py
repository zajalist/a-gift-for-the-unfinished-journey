"""Run one reviewed fence group under root's existing EditorConnection lease.

Check is offline. Run never retries or saves packages. Every prop/phase gets a
distinct receipt, written as started before the editor call. Any existing phase
receipt refuses replay, including an ambiguous or failed previous call.
"""
from pathlib import Path
import argparse
import ast
import hashlib
import json
import sys
import subprocess

ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/'Saved/Tripo/20261001/station_plinths'

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def select(args):
    path=(vars(args).get('manifest') or BASE/('gate_execution_manifest.json' if args.gate else 'fence_execution_manifest.json')).resolve()
    assert path.is_relative_to(BASE.resolve()),'Manifest must belong to the reviewed station packet'
    data=json.loads(path.read_text(encoding='utf-8'))
    rows=data['groups'] if args.gate else [r for r in data['groups'] if r['group']==args.group]
    if args.only_id:rows=[r for r in rows if r['id']==args.only_id]
    assert 1<=len(rows)<=3,'Choose an existing group of at most3props (or one --only-id)'
    for row in rows:
        phases=[s['phase'] for s in row['calls']]
        assert phases==(['apply','verify','passage'] if args.gate else ['apply','verify'])
        for step in row['calls']:
            file=(ROOT/step['path']).resolve()
            assert file.is_relative_to(BASE.resolve()) and file.suffix=='.py'
            assert digest(file)==step['sha256'],'Prepared script hash changed: '+str(file)
            ast.parse(file.read_text(encoding='utf-8'))
    return path,rows

def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8');temp.replace(path)

def result(output,step,name):
    marker='S26_GATE_PASSAGE ' if step=='passage' else 'S26_LEVEL_PLINTH '
    values=[json.loads(line.split(marker,1)[1]) for line in output.splitlines() if line.startswith(marker)]
    assert len(values)==1,'Expected one complete acceptance marker'
    value=values[0]
    if step=='passage':return bool(value.get('pass'))
    assert value.get('id')==name,'Receipt identifies another prop'
    if step=='apply':
        assert value.get('applied') is True and value.get('saved') is False
        assert len(value.get('changed',[]))==len(value.get('pads',[]))+1
        return True
    return value.get('surface_contact_pass') is True and value.get('verified_transforms') is True

def run(args,connection_factory=None):
    manifest,rows=select(args)
    manifest_sha=digest(manifest)
    receipts=(args.receipts or BASE/('gate_receipts' if args.gate else 'fence_receipts')).resolve()
    assert receipts.is_relative_to((ROOT/'Saved').resolve()),'Receipts must remain within project Saved'
    # Refuse the whole selected batch before doing anything if any step is old.
    for row in rows:
        for step in row['calls']:
            assert not (receipts/row['id']/(step['phase']+'.readback.json')).exists(),'Existing phase receipt: no automatic replay; inspect it and use --only-id for untouched props'
    if connection_factory is None:
        sys.path.insert(0,str(ROOT/'Tools/GameFlow/editor'))
        from install_ending_folder import EditorConnection
        connection_factory=EditorConnection
    connection=connection_factory(args.owner)
    for row in rows:
        for step in row['calls']:
            # Re-read every prepared hash before the next dependent call.
            assert digest(manifest)==manifest_sha,'Manifest changed during the reviewed batch'
            select(args)
            path=ROOT/step['path'];destination=receipts/row['id']/(step['phase']+'.readback.json')
            record={'script':str(path),'sha256':step['sha256'],'manifest':str(manifest),'manifest_sha256':manifest_sha,'id':row['id'],'phase':step['phase'],'status':'started'}
            write(destination,record)
            try:
                output=connection.send(path.read_text(encoding='utf-8'),row['id']+'_'+step['phase'])
                # Preserve successful script output even if a subsequent guard fails.
                record.update(status='ok',output=output);write(destination,record)
                connection.guard()
                accepted=result(output,step['phase'],row['id'])
                record['acceptance_passed']=accepted;write(destination,record)
                if not accepted:
                    raise RuntimeError('Contact/passage verification failed; inspect receipt and prepare measured correction. No next prop was applied.')
            except Exception as error:
                record['error']=str(error)
                if record['status']=='started':record['status']='failed_or_ambiguous'
                write(destination,record)
                raise
            print('FENCE_PHASE_OK',row['id'],step['phase'],destination,flush=True)
    return receipts

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('mode',choices=['check','run','prepare-save'])
    choose=ap.add_mutually_exclusive_group(required=True)
    choose.add_argument('--group',type=int);choose.add_argument('--gate',action='store_true')
    ap.add_argument('--only-id',help='Run one untouched prop in the selected group after reviewing another failure')
    ap.add_argument('--owner');ap.add_argument('--receipts',type=Path)
    ap.add_argument('--manifest',type=Path,help='Explicit revised packet; original manifest is preserved')
    args=ap.parse_args()
    if args.mode=='check':
        manifest,rows=select(args);print(json.dumps({'manifest':str(manifest),'sha256':digest(manifest),'ids':[r['id'] for r in rows],'editor_contacted':False}));return
    if args.mode=='prepare-save':
        manifest,rows=select(args)
        receipts=(args.receipts or BASE/('gate_receipts' if args.gate else 'fence_receipts')).resolve()
        assert receipts.is_relative_to((ROOT/'Saved').resolve())
        by_phase={}
        for row in rows:
            for step in row['calls']:
                path=receipts/row['id']/(step['phase']+'.readback.json')
                record=json.loads(path.read_text(encoding='utf-8'))
                assert record['status']=='ok' and record.get('acceptance_passed') is True,'Every reviewed phase must pass before save preparation'
                assert record['sha256']==step['sha256'] and Path(record['script']).resolve()==(ROOT/step['path']).resolve(),'Receipt script identity differs'
                by_phase.setdefault(step['phase'],[]).append(str(path))
        command=[sys.executable,str(ROOT/'Tools/World/story_sets/prepare_plinth_verified_save.py'),
                 '--name','save_'+'_'.join(r['id'] for r in rows)+'_after_visual_acceptance',
                 '--apply-results',*by_phase['apply'],'--verify-results',*by_phase['verify']]
        if args.gate:command+=['--gate-passage-result',by_phase['passage'][0]]
        subprocess.run(command,check=True)
        print('FENCE_SAVE_PREPARED_NO_EDITOR_CONTACT');return
    if not args.owner:ap.error('run requires root’s existing lease --owner')
    print('FENCE_GROUP_DONE',run(args))

if __name__=='__main__':main()
