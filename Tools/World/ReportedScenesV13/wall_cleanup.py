"""Prepare a root-reviewed, reversible visible-module removal from actual catalogs.

This never chooses modules from historical IDs alone. Root supplies exact GUIDs
after inspecting the current composition. Hidden collision-free pieces preserve
rollback packages and do not create new obstructions on the navigable road.
Overlapping HLOD descriptors remain explicit blockers until root verifies them.
"""
import argparse
import json
import shutil
from pathlib import Path
from prepare import ROOT, OUT, HEAD, EXCLUDED, receipt, write, sha


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--catalog',type=Path,action='append',required=True)
    p.add_argument('--hide-guid',action='append',required=True)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--reason',required=True,help='Root reviewed composition: retained anchors, gaps and protected landmarks')
    args=p.parse_args()
    rows=[];owners=[]
    for file in args.catalog:
        d=receipt(file,'REPORTED_CATALOG');rows+=d['rows'];owners+=d['owners']
    byguid={r['host']['guid']:r for r in rows};assert len(byguid)==len(rows)
    assert 1<=len(args.hide_guid)<=3 and len(args.hide_guid)==len(set(args.hide_guid))
    chosen=[byguid[g] for g in args.hide_guid]
    assert len(rows)>len(chosen),'At least one reviewed ruin anchor must remain visible'
    source=json.loads((ROOT/'Tools/World/setdress_v2_sites.json').read_bytes())
    authored={'SD_'+it['id']:it for site in source['sites'] for it in site['placements']}
    for r in chosen:
        h=r['host'];assert h['label'] not in EXCLUDED and h['class']=='StaticMeshActor'
        assert h['label'].startswith(('SD_S14_DeparturePlatform','SD_S15_Works','SD_L10_FootFarm'))
        assert not r['attached'] and len(r['components'])==1,'Do not remove a unique packed or attached assembly'
        e=r['components'][0];assert not e['is_ism'] and e['count']==1,'Actual current mesh must be a solo module'
        it=authored[h['label']];assert it.get('cat')=='wall' and not any(it.get(k) for k in ('unit','attach','bears_on','story_owned'))
        # Some actual wall meshes are named SM_300x400_Mid. Prove exact source
        # asset identity instead of assuming the asset name contains "wall".
        expected_asset=it['asset'];expected_object=expected_asset if '.' in expected_asset.rsplit('/',1)[-1] else expected_asset+'.'+expected_asset.rsplit('/',1)[-1]
        assert e['mesh']==expected_object,'Current installed mesh differs from the authored reviewed wall identity'
        assert not any(k in it['key'].lower() for k in ('arch','door','window','floor','fence','stele','marker','plinth')),'Protect entrances, platforms and unique landmarks'
        assert any(authored.get(k['host']['label'],{}).get('block')==it.get('block') for k in rows if k not in chosen),'Retain a reviewed anchor in the same authored block'
    args.out=args.out.resolve();assert args.out.is_relative_to(OUT.resolve())
    args.out.mkdir(parents=True,exist_ok=False)
    backups=[]
    for r in chosen:
        h=r['host'];file=ROOT/'Content'/(h['package'][6:]+'.uasset');assert file.is_file()
        dst=args.out/(h['guid']+'_before.uasset');shutil.copy2(file,dst)
        backups.append({'guid':h['guid'],'source':str(file),'source_sha256':sha(file),'backup':str(dst),'backup_sha256':sha(dst)})
    spec={'chosen':chosen,'retained':[r for r in rows if r not in chosen],'overlapping_hlod_candidates':owners,'composition_reason':args.reason}
    prefix=HEAD+'SPEC='+repr(spec)+'\n'+CHECK
    scripts=[write(args.out/'40_hide_redundant_wall_modules.py',prefix+APPLY),write(args.out/'50_readback_hidden_and_retained.py',prefix+READ),write(args.out/'60_force_save_exact_packages.py',prefix+SAVE),write(args.out/'70_unload_clean_wall_hosts.py',prefix+UNLOAD),write(args.out/'80_prove_absence.py',HEAD+'SPEC='+repr(spec)+'\n'+ABSENT),write(args.out/'90_reload_exact_guids.py',HEAD+'SPEC='+repr(spec)+'\n'+RELOAD),write(args.out/'95_readback_reloaded_walls.py',prefix+READ)]
    write(args.out/'plan.json',dict(spec,backups=backups,scripts=scripts,status='root_lit_and_hlod_review_required',source_receipts=[{'file':str(f.resolve()),'sha256':sha(f)} for f in args.catalog],calls_executed=0))
    print(json.dumps({'out':str(args.out),'scripts':scripts,'hlod_review_required':True}))


CHECK='''
def check(hidden):
 output=[]
 for row in SPEC['chosen']+SPEC['retained']:
  a=actor_of(row['host']);assert a.get_actor_transform().export_text()==row['host']['transform']
  assert [str(t) for t in a.tags]==row['host']['tags']
  for e in row['components']:
   c=unreal.find_object(None,e['component']);assert unreal.SystemLibrary.is_valid(c) and c.get_owner()==a and path(c.static_mesh)==e['mesh']
   assert c.get_world_transform().export_text()==e['component_transform'] and (c.get_instance_count() if e['is_ism'] else 1)==e['count']
   for pin in e['poses']:assert (c.get_instance_transform(pin['index'],True) if e['is_ism'] else c.get_world_transform()).export_text()==pin['transform']
   expected=dict(e['properties'])
   if hidden and row in SPEC['chosen']:expected.update(visible=False,hidden_in_game=True,collision=str(unreal.CollisionEnabled.NO_COLLISION))
   assert props(c)==expected,'Unexpected component change'
   output.append({'guid':row['host']['guid'],'component':path(c),'properties':props(c),'transform':c.get_world_transform().export_text(),'retained':row in SPEC['retained']})
 return output
'''
APPLY='''
check(False)
for row in SPEC['chosen']:
 a=actor_of(row['host']);assert a.get_package().get_name() not in dirty(),'Unrelated dirty wall package'
for row in SPEC['chosen']:
 a=actor_of(row['host']);c=unreal.find_object(None,row['components'][0]['component']);a.modify();c.modify()
 c.set_visibility(False,True);c.set_hidden_in_game(True,True);c.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
print('REPORTED_WALL_APPLIED '+json.dumps({'rows':check(True),'saved':False,'lit_and_overlapping_hlod_review_pending':True},separators=(',',':')))
'''
READ='''
print('REPORTED_WALL_VERIFIED '+json.dumps({'rows':check(True),'overlapping_hlod_candidates':SPEC['overlapping_hlod_candidates'],'read_only':True,'saved':False,'fresh_render_review_required':True},separators=(',',':')))
'''
SAVE='''
check(True)
packages=[actor_of(r['host']).get_package() for r in SPEC['chosen']]
assert unreal.EditorLoadingAndSavingUtils.save_packages(packages,False),'Exact package save failed'
assert all(p.get_name() not in dirty() for p in packages)
print('REPORTED_WALL_SAVED '+json.dumps({'packages':[p.get_name() for p in packages],'saved':True,'fresh_reload_pending':True}))
'''
UNLOAD='''
check(True);actors=[actor_of(r['host']) for r in SPEC['chosen']]
assert all(a.get_package().get_name() not in dirty() for a in actors)
eas=unreal.get_editor_subsystem(unreal.EditorActorSubsystem);selected=list(eas.get_selected_level_actors())
eas.set_selected_level_actors([a for a in selected if a not in actors])
unreal.WorldPartitionBlueprintLibrary.unload_actors([a.get_editor_property('actor_guid') for a in actors])
print('REPORTED_WALL_UNLOAD_REQUESTED '+json.dumps({'guids':[r['host']['guid'] for r in SPEC['chosen']],'normal_gc_then_absence_proof_required':True}))
'''
ABSENT='''
assert all(not unreal.SystemLibrary.is_valid(unreal.find_object(None,r['host']['actor'])) for r in SPEC['chosen']),'Old wall UObject still present'
print('REPORTED_WALL_OLD_OBJECTS_ABSENT '+json.dumps({'absent':True}))
'''
RELOAD=ABSENT+'''
guids=[]
for r in SPEC['chosen']:
 g=unreal.Guid();assert g.import_text(r['host']['guid']);guids.append(g)
unreal.WorldPartitionBlueprintLibrary.load_actors(guids)
print('REPORTED_WALL_RELOAD_REQUESTED '+json.dumps({'separate_readback_required':True}))
'''


if __name__=='__main__':main()
