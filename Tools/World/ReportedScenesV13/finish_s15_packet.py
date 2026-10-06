"""Offline S15 descriptor, mutation guard, save and native HLOD packets.

Every identity comes from a complete root receipt. This process never connects
to the editor. Existing phases are immutable; select a new --out for each bind.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import prepare
from unwrap_receipt import unwrap
import prepare_s15_install as install
from direct_source_membership import inner as property_result


DISCOVER = '''
box=unreal.Box(unreal.Vector(438000,342000,-1000000),unreal.Vector(441000,345000,1000000))
raw=unreal.WorldPartitionBlueprintLibrary.get_intersecting_actor_descs(box)
descs=raw[1] if isinstance(raw,tuple) else raw
assert descs is not None and len(descs)<=64,'Unexpected sourcebox growth; split the bounded query'
rows=[];classes={}
for d in descs:
 assert not expired(),'Descriptor query exceeded 3.5 seconds'
 cls=d.native_class.get_name() if unreal.SystemLibrary.is_valid(d.native_class) else ''
 classes[cls]=classes.get(cls,0)+1
 if cls not in ('Landscape','LandscapeStreamingProxy','WorldPartitionHLOD'):continue
 rows.append({'guid':d.guid.export_text(),'actor':str(d.actor_path),'label':str(d.label),'class':cls,'package':str(d.actor_package),'bounds':[xyz(d.bounds.min),xyz(d.bounds.max)],'editor_only':bool(d.actor_is_editor_only)})
assert len(rows)<=8,'Do not clip ownership/terrain identities'
encoded=json.dumps({'box':[438000,342000,441000,345000],'descriptor_total':len(descs),'native_class_counts':classes,'rows':rows,'complete':True,'read_only':True,'loaded':False,'saved':False},separators=(',',':'))
assert len(encoded)<7600
print('S15_TERRAIN_HLOD_DESCRIPTORS '+encoded)
'''

LOAD_TERRAIN = '''
raw=unreal.WorldPartitionBlueprintLibrary.get_intersecting_actor_descs(unreal.Box(unreal.Vector(438000,342000,-1000000),unreal.Vector(441000,345000,1000000)))
descs=raw[1] if isinstance(raw,tuple) else raw
assert descs is not None and len(descs)<=64
actual={d.guid.export_text():{'guid':d.guid.export_text(),'actor':str(d.actor_path),'label':str(d.label),'class':d.native_class.get_name(),'package':str(d.actor_package)} for d in descs if unreal.SystemLibrary.is_valid(d.native_class) and d.native_class.get_name() in ('Landscape','LandscapeStreamingProxy')}
assert actual=={h['guid']:{k:h[k] for k in ('guid','actor','label','class','package')} for h in TERRAIN},'Terrain descriptor changed since root read'
guids=[]
for h in TERRAIN:
 g=unreal.Guid();assert g.import_text(h['guid']);guids.append(g)
assert 1<=len(guids)<=2 and not expired()
unreal.WorldPartitionBlueprintLibrary.load_actors(guids)
print('S15_TERRAIN_LOAD_REQUESTED '+json.dumps({'guids':[h['guid'] for h in TERRAIN],'loaded_requested':True,'separate_residency_read_required':True,'saved':False},separators=(',',':')))
'''

READ_TERRAIN = '''
rows=[]
for h in TERRAIN:
 a=actor_of(h);assert isinstance(a,unreal.LandscapeProxy)
 rows.append({'host':identity(a),'transform':a.get_actor_transform().export_text(),'collision_mip':a.get_editor_property('collision_mip_level'),'simple_collision_mip':a.get_editor_property('simple_collision_mip_level'),'material':path(a.get_editor_property('landscape_material')),'dirty':a.get_package().get_name() in dirty()})
print('S15_TERRAIN_RESIDENT '+json.dumps({'rows':rows,'read_only':True,'saved':False},separators=(',',':')))
'''

GUARD = '''
a=actor_of(PIN['host']);c=unreal.find_object(None,PIN['before']['component'])
assert unreal.SystemLibrary.is_valid(c) and c.get_owner()==a
assert not a.get_attached_actors() and a.get_package().get_name() not in dirty()
assert matches(a.get_actor_transform(),PIN['before']['actor_transform']) and matches(c.get_world_transform(),PIN['before']['component_transform'])
assert path(c.static_mesh)==PIN['before']['mesh'] and props(c)==PIN['before']['properties']
assert [str(t) for t in a.tags]==PIN['before']['tags']
assert c.get_editor_property('body_instance').export_text()==PIN['before']['body_instance']
if 'geometry' in PIN:
 assert len(PIN['samples'])>=3 and PIN['complete'] and PIN['read_only']
 assert PIN['geometry']['dynamic_vertices']<=PIN['geometry']['render_vertices']
 assert PIN['old_geometry']['dynamic_vertices']<=PIN['old_geometry']['render_vertices']
 assert max(PIN['fitted_landscape_gap_cm'])<=-SINK+.001
 assert abs(PIN['fit_z_cm'])<=100
 for geo in (PIN['geometry'],PIN['old_geometry']):
  mesh=unreal.load_asset(geo['mesh']);assert unreal.SystemLibrary.is_valid(mesh) and mesh.get_package().get_name() not in dirty()
  assert unreal.get_editor_subsystem(unreal.StaticMeshEditorSubsystem).get_number_verts(mesh,0)==geo['render_vertices']
 for meta in PIN['contact_metadata']:
  actor_of(meta['host'])
print('S15_MUTATION_GUARD '+json.dumps({'host':identity(a),'fit_receipt_sha256':PROVENANCE['sha256'],'native_commands':PIN['native_commands'],'read_only':True,'saved':False,'run_commands_immediately_in_order':True},separators=(',',':')))
'''

CHECK_SAVED_STATE = '''
def check_saved_state():
 rows=[]
 for pin in PINS:
  a=actor_of(pin['host']);c=unreal.find_object(None,pin['before']['component'])
  assert unreal.SystemLibrary.is_valid(c) and c.get_owner()==a and not a.get_attached_actors()
  assert matches(a.get_actor_transform(),pin['expected_pose']) and matches(c.get_world_transform(),pin['expected_pose'])
  assert path(c.static_mesh)==pin['expected_mesh'] and props(c)==pin['expected_properties']
  assert [str(t) for t in a.tags]==pin['before']['tags']
  assert c.get_editor_property('body_instance').export_text()==pin['expected_body_instance']
  rows.append({'host':identity(a),'pose':a.get_actor_transform().export_text(),'mesh':path(c.static_mesh),'properties':props(c),'modified':pin['modified']})
  assert not expired(),'Identity check exceeded budget; split guard before saving'
 return rows
'''

SAVE = '''
rows=check_saved_state()
packages=[actor_of(pin['host']).get_package() for pin in PINS if pin['modified']]
assert len(packages)==5 and len({p.get_name() for p in packages})==5
before_dirty=dirty()
assert all(p.get_name() in before_dirty for p in packages),'Expected five unsaved source mutations; unexpected state requires root review'
assert unreal.EditorLoadingAndSavingUtils.save_packages(packages,False),'Exact five package save failed'
after_dirty=dirty();assert all(p.get_name() not in after_dirty for p in packages)
print('S15_EXACT_PACKAGES_SAVED '+json.dumps({'packages':[p.get_name() for p in packages],'rows':rows,'unrelated_dirty_before':sorted(before_dirty-{p.get_name() for p in packages}),'unrelated_dirty_after':sorted(after_dirty),'saved':True,'reload_and_fresh_lit_pending':True},separators=(',',':')))
'''


def marker(file, name):
    value=json.loads(file.read_bytes())
    output=prepare.receipt(file,name) if value.get('status')=='ok' else None
    if output is not None:return output
    lines=[line[len(name)+1:] for line in unwrap(value).splitlines() if line.startswith(name+' ')]
    assert len(lines)==1
    data=json.loads(lines[0]);assert data.get('read_only') is True
    return data


def discover(args):
    script=prepare.write(args.out/'00_terrain_hlod_descriptors.py',prepare.HEAD+DISCOVER)
    prepare.write(args.out/'manifest.json',{'status':'prepared_not_executed','scripts':[script],'editor_calls':0,'query':'Same exact S15 3,000cm source box as V15. V15 counted two LandscapeStreamingProxy + two WorldPartitionHLOD but excluded them from wall pages. No all-map get_actor_descs or load.'})


def terrain(args):
    data=marker(args.receipt,'S15_TERRAIN_HLOD_DESCRIPTORS');assert data['complete']
    terrain=[h for h in data['rows'] if h['class'] in ('Landscape','LandscapeStreamingProxy')]
    owners=[h for h in data['rows'] if h['class']=='WorldPartitionHLOD']
    assert 1<=len(terrain)<=2 and len(owners)<=2
    prefix=prepare.HEAD+'TERRAIN='+repr(terrain)+'\n'
    scripts=[prepare.write(args.out/'10_load_exact_terrain_guids.py',prefix+LOAD_TERRAIN),prepare.write(args.out/'20_read_exact_terrain_residency.py',prefix+READ_TERRAIN)]
    commands=[]
    for h in owners:
        commands += [{'command':'actor_inspect','params':{'actor_id':h['actor']},'expected_guid':h['guid'],'expected_package':h['package']},{'command':'object_get_property','params':{'path':h['actor'],'names':['SourceActors','SourceCellGuid','LODLevel','HLODHash']},'expected_guid':h['guid'],'role':'Exact SourceActors UObject path must be read before membership; bounds do not prove ownership.'}]
    prepare.write(args.out/'native_hlod_owner_reads.json',{'status':'prepared_not_executed','commands':commands,'editor_calls':0,'owners':owners})
    prepare.write(args.out/'manifest.json',{'status':'prepared_not_executed','scripts':scripts,'terrain':terrain,'hlod_candidates':owners,'receipt':str(args.receipt.resolve()),'receipt_sha256':prepare.sha(args.receipt),'editor_calls':0,'root_order':'Load terrain only; separate resident read; rerun seven V17 fits. HLOD candidate identity/property reads need residency and must not be used as terrain.'})


def fits(args):
    rows=[marker(p,'S15_WALL_FIT') if 'S15_WALL_FIT ' in (json.dumps(json.loads(p.read_bytes()))) else marker(p,'S15_WALL_SIMPLE') for p in args.fit]
    assert len(rows)==7 and {r['host']['label'][-3:] for r in rows}==set(install.PLANS)
    assert {r['host']['label'] for r in rows}=={'SD_S15_Works_'+suffix for suffix in install.PLANS}
    scripts=[]
    for file,row in zip(args.fit,rows):
        assert row['verified'] is False and row['read_only'] and not row['saved']
        suffix=row['host']['label'][-3:];plan=install.PLANS[suffix]
        provenance={'receipt':str(file.resolve()),'sha256':prepare.sha(file)}
        text=prepare.HEAD+'PIN='+repr(row)+'\nSINK='+repr(plan.get('sink_cm'))+'\nPROVENANCE='+repr(provenance)+'\n'+GUARD
        scripts.append(prepare.write(args.out/f'20_guard_{suffix}.py',text))
    prepare.write(args.out/'manifest.json',{'status':'prepared_not_executed','scripts':scripts,'editor_calls':0,'root_order':'Run one guard immediately before its emitted native commands, sequentially. Root owns fresh fit/Lit acceptance. Preserve every native mutation receipt.'})


def saves(args):
    fits_bylabel={}
    for p in args.fit:
        value=json.dumps(json.loads(p.read_bytes()));row=marker(p,'S15_WALL_FIT' if 'S15_WALL_FIT ' in value else 'S15_WALL_SIMPLE')
        assert row['verified'] is False;fits_bylabel[row['host']['label']]=row
    verified={}
    for p in args.verify:
        value=json.dumps(json.loads(p.read_bytes()));row=marker(p,'S15_WALL_FIT' if 'S15_WALL_FIT ' in value else 'S15_WALL_SIMPLE')
        assert row['verified'] is True and not row['native_commands'];verified[row['host']['label']]=row
    assert len(fits_bylabel)==len(verified)==7 and set(fits_bylabel)==set(verified)
    assert set(fits_bylabel)=={'SD_S15_Works_'+suffix for suffix in install.PLANS}
    pins=[]
    for label,fit in sorted(fits_bylabel.items()):
        check=verified[label];assert fit['host']==check['host']
        plan=install.PLANS[label[-3:]];mode=plan['mode'];props=dict(fit['before']['properties'])
        pose=fit['before']['actor_transform'];mesh=fit['before']['mesh']
        if mode in ('low','remnant'):
            assert fit['geometry']==check['geometry'] and fit['old_geometry']==check['old_geometry']
            assert fit['candidate_transform']==check['candidate_transform'] and fit['complete'] and check['complete']
            assert max(check['fitted_landscape_gap_cm'])<=-plan['sink_cm']+.001
            pose=fit['candidate_transform'];mesh=fit['geometry']['mesh']
        if mode=='gap':props.update(visible=False,hidden_in_game=True,collision=check['before']['properties']['collision'])
        assert check['before']['mesh']==mesh and check['before']['properties']==props
        assert check['before']['tags']==fit['before']['tags']
        pins.append({'host':fit['host'],'before':fit['before'],'mode':mode,'modified':mode!='retain','expected_pose':pose,'expected_mesh':mesh,'expected_properties':props,'expected_body_instance':check['before']['body_instance']})
    prefix=prepare.HEAD+'PINS='+repr(pins)+'\n'+CHECK_SAVED_STATE
    unload='''
check_saved_state();actors=[actor_of(pin['host']) for pin in PINS if pin['modified']]
assert all(a.get_package().get_name() not in dirty() for a in actors)
eas=unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
eas.set_selected_level_actors([a for a in eas.get_selected_level_actors() if a not in actors])
unreal.WorldPartitionBlueprintLibrary.unload_actors([a.get_editor_property('actor_guid') for a in actors])
print('S15_UNLOAD_REQUESTED '+json.dumps({'guids':[pin['host']['guid'] for pin in PINS if pin['modified']],'normal_gc_then_absence_read_required':True,'saved':False}))
'''
    absent='''
assert all(not unreal.SystemLibrary.is_valid(unreal.find_object(None,pin['host']['actor'])) for pin in PINS if pin['modified']),'Old wall UObject still resident; disk proof unavailable'
print('S15_OLD_OBJECTS_ABSENT '+json.dumps({'absent':True,'read_only':True,'saved':False}))
'''
    reload=absent+'''
guids=[]
for pin in PINS:
 if not pin['modified']:continue
 g=unreal.Guid();assert g.import_text(pin['host']['guid']);guids.append(g)
unreal.WorldPartitionBlueprintLibrary.load_actors(guids)
print('S15_RELOAD_REQUESTED '+json.dumps({'guids':[pin['host']['guid'] for pin in PINS if pin['modified']],'separate_readback_required':True,'saved':False}))
'''
    scripts=[prepare.write(args.out/'60_force_save_five_exact_packages.py',prefix+SAVE),prepare.write(args.out/'70_unload_five_clean_hosts.py',prefix+unload),prepare.write(args.out/'80_prove_old_objects_absent.py',prepare.HEAD+'PINS='+repr(pins)+'\n'+absent),prepare.write(args.out/'90_reload_five_exact_guids.py',prepare.HEAD+'PINS='+repr(pins)+'\n'+reload),prepare.write(args.out/'95_read_reloaded_seven_hosts.py',prefix+"print('S15_RELOADED_STATE '+json.dumps({'rows':check_saved_state(),'read_only':True,'saved':False},separators=(',',':')))\n")]
    prepare.write(args.out/'manifest.json',{'status':'prepared_not_executed','scripts':scripts,'modified_packages':[p['host']['package'] for p in pins if p['modified']],'editor_calls':0,'root_order':'Accept fresh Lit, then force save exactly five source packages. Keep native receipts and disk hashes. Root separately unloads clean modified hosts, normal GC, proves old UObjects absent, reloads exact GUIDs, reruns all seven V17 verification scripts plus this resident state read and fresh Lit. HLOD evidence remains separate.'})


def hlod_source(args):
    data=property_result(json.loads(args.receipt.read_bytes()))
    assert data['class']=='WorldPartitionHLOD'
    assert not data.get('_truncated'),'SourceActors pointer read must be complete'
    source=data['properties']['SourceActors']
    assert isinstance(source,str) and source and '...' not in source
    # Native UObject export may wrap its path in a class prefix and quotes.
    if "'" in source:source=source.split("'",1)[1].rsplit("'",1)[0]
    assert source.startswith(data['path']+'.') and source.endswith('.WorldPartitionHLODSourceActorsFromCell_0')
    outer=source.rsplit('.',1)[0]
    commands=[{'command':'object_get_property','params':{'path':source,'names':['HLODLayer','Actors']},'role':'Class/path and layer read. A clipped Actors value cannot establish membership.'},{'command':'editor_run_console_command','params':{'command':f'GETALL WorldPartitionHLODSourceActorsFromCell Actors OUTER={outer} NAME=WorldPartitionHLODSourceActorsFromCell_0'},'role':'One exact resident source object only; retain synchronous complete log output and use parse_console_membership.py. Direct GUID membership only; inspect parent source lists separately.'}]
    prepare.write(args.out/'native_source_membership.json',{'status':'prepared_not_executed','commands':commands,'source_object':source,'hlod_actor':data['path'],'receipt':str(args.receipt.resolve()),'receipt_sha256':prepare.sha(args.receipt),'editor_calls':0,'ownership':'Intersect complete mapping GUIDs with exact S15 wall GUIDs; no ownership claim from overlapping bounds or a 512 character Actors export.'})


def main():
    parser=argparse.ArgumentParser();sub=parser.add_subparsers(dest='mode',required=True)
    for name in ('discover','terrain','fits','saves','hlod_source'):
        p=sub.add_parser(name);p.add_argument('--out',type=Path,required=True)
        if name in ('terrain','hlod_source'):p.add_argument('--receipt',type=Path,required=True)
        if name in ('fits','saves'):p.add_argument('--fit',type=Path,action='append',required=True)
        if name=='saves':p.add_argument('--verify',type=Path,action='append',required=True)
    args=parser.parse_args();globals()[args.mode](args)
    print(json.dumps({'out':str(args.out.resolve()),'mode':args.mode,'editor_calls':0}))


if __name__=='__main__':main()
