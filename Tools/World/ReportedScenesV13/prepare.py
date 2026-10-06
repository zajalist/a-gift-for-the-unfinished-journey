"""Offline receipt-bound packets. Run generated native scripts only as root after PIE.

No editor imports here. No guessed GUID, heightmap, source-Z repair, or partial ISM
catalog is allowed. This prepares packets; it never changes Content itself.
"""
from __future__ import annotations
import argparse
import ast
import hashlib
import json
import math
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'Saved/Verification/reported_scenes_v13'
EXCLUDED = {'SD_S13_NumberedStop_037', 'SD_S13_NumberedStop_038'}


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def write(p, value):
    p = Path(p).resolve()
    assert p.is_relative_to(OUT.resolve()), 'Packet output must stay in owned Saved directory'
    p.parent.mkdir(parents=True, exist_ok=True)
    assert not p.exists(), 'Use a new phase directory; never overwrite reviewed packets'
    text = value if isinstance(value, str) else json.dumps(value, indent=2) + '\n'
    if p.suffix == '.py':
        ast.parse(text)
    p.write_text(text, encoding='utf-8', newline='\n')
    return {'script': str(p), 'sha256': sha(p)}


def receipt(p, marker):
    value = json.loads(Path(p).read_bytes())
    if 'rows' in value or 'samples' in value:
        raise ValueError('Use root transport envelope with script, sha256, status and output')
    assert value['status'] == 'ok' and sha(value['script']) == value['sha256']
    lines = [line.split(' ', 1)[1] for line in value['output'].splitlines() if line.startswith(marker + ' ')]
    assert len(lines) == 1, 'Missing/truncated/duplicate native marker'
    data = json.loads(lines[0])
    assert not value.get('_truncated') and not data.get('remaining'), 'Incomplete receipts cannot authorize a repair'
    return data


HEAD = '''import unreal,json,datetime,math
es=unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
assert not unreal.SystemLibrary.is_valid(es.get_game_world()),'ROOT ONLY: stop PIE before executing this packet'
world=es.get_editor_world();assert unreal.SystemLibrary.is_valid(world) and world.get_name()=='Saskarta_WP'
started=datetime.datetime.now(datetime.timezone.utc)
def expired():return (datetime.datetime.now(datetime.timezone.utc)-started).total_seconds()>=3.5
def path(o):return o.get_path_name() if unreal.SystemLibrary.is_valid(o) else None
def xyz(v):return [v.x,v.y,v.z]
def dirty():return {p.get_name() for p in list(unreal.EditorLoadingAndSavingUtils.get_dirty_map_packages())+list(unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages())}
def identity(a):return {'actor':path(a),'label':a.get_actor_label(),'guid':a.get_editor_property('actor_guid').export_text(),'package':a.get_package().get_name(),'class':a.get_class().get_name()}
def actor_of(e):
 a=unreal.find_object(None,e['actor']);assert unreal.SystemLibrary.is_valid(a) and a.get_world()==world
 assert identity(a)=={k:e[k] for k in ('actor','label','guid','package','class')},'Actor GUID/package/label changed'
 return a
def props(c):return {'materials':[path(c.get_material(i)) for i in range(c.get_num_materials())],'visible':bool(c.is_visible()),'hidden_in_game':bool(c.get_editor_property('hidden_in_game')),'collision':str(c.get_collision_enabled()),'mobility':str(c.get_editor_property('mobility')),'evaluate_wpo':bool(c.get_editor_property('evaluate_world_position_offset')),'wpo_disable_cm':c.get_editor_property('world_position_offset_disable_distance')}
def matches(actual,text,delta=0):
 b=unreal.Transform();assert b.import_text(text)
 p,q=actual.translation,b.translation
 if max(abs(p.x-q.x),abs(p.y-q.y))>.003 or abs(p.z-q.z-delta)>.008:return False
 p,q=actual.rotation,b.rotation
 if min(max(abs(p.x-q.x),abs(p.y-q.y),abs(p.z-q.z),abs(p.w-q.w)),max(abs(p.x+q.x),abs(p.y+q.y),abs(p.z+q.z),abs(p.w+q.w)))>.000002:return False
 p,q=actual.scale3d,b.scale3d
 return max(abs(p.x-q.x),abs(p.y-q.y),abs(p.z-q.z))<.000002
'''

DESCRIPTORS = '''
x0,y0,x1,y1=BOX;assert x1-x0<=4000 and y1-y0<=4000
raw=unreal.WorldPartitionBlueprintLibrary.get_intersecting_actor_descs(unreal.Box(unreal.Vector(x0,y0,-1000000),unreal.Vector(x1,y1,1000000)))
descs=raw[1] if isinstance(raw,tuple) else raw
assert len(descs)<=180,'Split the query; do not load the map or truncate identities'
rows=[];omitted={}
for d in descs:
 cls=d.native_class.get_name() if d.native_class else '';label=str(d.label)
 if not (label.startswith('SD_') or 'Landscape' in cls or 'HLOD' in cls):
  omitted[cls]=omitted.get(cls,0)+1;continue
 lo,hi=d.bounds.min,d.bounds.max
 rows.append({'actor':str(d.actor_path),'guid':d.guid.export_text(),'package':str(d.actor_package),'label':label,'class':cls,'bounds':[xyz(lo),xyz(hi)],'editor_only':bool(d.actor_is_editor_only)})
assert len(rows)<=128,'Split cell query; preserve every authored descriptor'
print('REPORTED_DESCRIPTORS '+json.dumps({'box':BOX,'source_cohort':COHORT,'query_grid_cm':3000,'wp_runtime_cells':'not exposed by ActorDesc; never substitute query grid for runtime cell name','rows':rows,'omitted':omitted,'read_only':True,'loaded':False,'saved':False},separators=(',',':')))
'''

CATALOG = '''
rows=[]
for host in HOSTS:
 a=actor_of(host);assert host['label'] not in EXCLUDED
 comps=[]
 for c in a.get_components_by_class(unreal.StaticMeshComponent):
  if c.static_mesh is None:continue
  ism=isinstance(c,unreal.InstancedStaticMeshComponent);count=c.get_instance_count() if ism else 1
  assert count<=128,'Split catalog instances explicitly; do not take first eight'
  assert c.get_class().get_name()!='PCGProceduralISMComponent','GPU PCG requires its owner lane'
  comps.append({'component':path(c),'class':c.get_class().get_name(),'mesh':path(c.static_mesh),'component_transform':c.get_world_transform().export_text(),'properties':props(c),'is_ism':ism,'count':count,'render_vertices':unreal.get_editor_subsystem(unreal.StaticMeshEditorSubsystem).get_number_verts(c.static_mesh,0),'poses':[{'index':i,'transform':(c.get_instance_transform(i,True) if ism else c.get_world_transform()).export_text()} for i in range(count)]})
 row={'host':dict(identity(a),transform=a.get_actor_transform().export_text(),tags=[str(t) for t in a.tags]),'components':comps,'attached':[identity(ch) for ch in a.get_attached_actors()]}
 if isinstance(a,unreal.LandscapeProxy):row['terrain']={'collision_mip':a.get_editor_property('collision_mip_level'),'simple_collision_mip':a.get_editor_property('simple_collision_mip_level'),'material':path(a.get_editor_property('landscape_material'))}
 rows.append(row)
 assert not expired(),'Catalog exceeded 3.5s; use one host per call'
print('REPORTED_CATALOG '+json.dumps({'rows':rows,'owners':OWNERS,'read_only':True,'saved':False,'all_component_instances_pinned':True},separators=(',',':')))
'''

TRACE = '''
trace_count=0
def ground(point):
 global trace_count
 ignored=[a];chain=[];support=None
 for layer in range(6):
  assert not expired() and trace_count<96,'Bounded support call expired; no mutation/save'
  trace_count+=1
  raw=unreal.SystemLibrary.line_trace_single(world,unreal.Vector(point.x,point.y,point.z+2000),unreal.Vector(point.x,point.y,point.z-4000),unreal.TraceTypeQuery.TRACE_TYPE_QUERY1,True,ignored,unreal.DrawDebugTrace.NONE,True)
  if isinstance(raw,tuple) and len(raw)==2 and not isinstance(raw[0],unreal.HitResult):raw=raw[1] if raw[0] else None
  assert raw is not None and raw.to_tuple()[0],'Real Landscape missing; no source-Z fallback'
  h=raw.to_tuple();p,n,hit=h[5],h[7],h[9];assert unreal.SystemLibrary.is_valid(hit)
  kind='landscape' if isinstance(hit,unreal.LandscapeProxy) else ('hlod' if 'HLOD' in hit.get_class().get_name() else 'actor')
  item={'host':identity(hit),'point':xyz(p),'normal':xyz(n),'gap_cm':point.z-p.z,'kind':kind}
  if kind=='landscape':
   item['transform']=hit.get_actor_transform().export_text();item['collision_mip']=hit.get_editor_property('collision_mip_level');item['simple_collision_mip']=hit.get_editor_property('simple_collision_mip_level');item['material']=path(hit.get_editor_property('landscape_material'))
   return {'landscape':item,'first_real_support':support or item,'occluders':chain}
  if kind=='actor' and support is None:support=item
  chain.append(item);ignored.append(hit)
 raise AssertionError('Occluder limit; support unknown')
'''

MEASURE = '''
a=actor_of(SPEC['host']);e=SPEC['component'];c=unreal.find_object(None,e['component'])
assert matches(a.get_actor_transform(),SPEC['host']['transform'])
assert unreal.SystemLibrary.is_valid(c) and c.get_owner()==a and path(c.static_mesh)==e['mesh']
assert props(c)==e['properties'] and c.get_world_transform().export_text()==e['component_transform']
assert (c.get_instance_count() if e['is_ism'] else 1)==e['count']
assert c.static_mesh.get_package().get_name() not in dirty()
assert 3<=e['render_vertices']<=20000,'Separate geometry extraction required; do not use bounds as feet'
pose=c.get_instance_transform(SPEC['pin']['index'],True) if e['is_ism'] else c.get_world_transform()
assert pose.export_text()==SPEC['pin']['transform']
dm=unreal.DynamicMesh();lod=unreal.GeometryScriptMeshReadLOD();lod.lod_type=unreal.GeometryScriptLODType.RENDER_DATA;lod.lod_index=0
opt=unreal.GeometryScriptCopyMeshFromAssetOptions();opt.request_tangents=False
dm,outcome=unreal.GeometryScript_AssetUtils.copy_mesh_from_static_mesh(c.static_mesh,dm,opt,lod)
assert outcome==unreal.GeometryScriptOutcomePins.SUCCESS
got=unreal.GeometryScript_MeshQueries.get_all_vertex_positions(dm,False);assert not got[2]
verts=unreal.GeometryScript_List.convert_vector_list_to_array(got[1]);assert len(verts)==e['render_vertices']
ws=[pose.transform_location(v) for v in verts]
lo=[min(v.x for v in ws),min(v.y for v in ws)];hi=[max(v.x for v in ws),max(v.y for v in ws)]
bins={}
for i,p in enumerate(ws):
 b=tuple(min(2,int((value-lo[k])*3/max(hi[k]-lo[k],.001))) for k,value in enumerate((p.x,p.y)))
 if b not in bins or p.z<ws[bins[b]].z:bins[b]=i
assert not expired(),'Render geometry extraction exceeded budget'
samples=[]
for b in sorted(bins):
 i=bins[b];samples.append({'bin':list(b),'vertex_index':i,'local':xyz(verts[i]),'world':xyz(ws[i]),'ground':ground(ws[i])})
assert pose.export_text()==SPEC['pin']['transform'] and props(c)==e['properties']
print('REPORTED_CONTACT '+json.dumps({'host':SPEC['host'],'component':e,'pin':SPEC['pin'],'samples':samples,'complete':len(samples)==len(bins),'rays':trace_count,'geometry':'RENDER_DATA_LOD0 world-space lower vertex per 3x3 footprint bin','wpo_not_in_base_vertices':True,'read_only':True,'saved':False},separators=(',',':')))
'''


def seed(args):
    data = json.loads((ROOT/'Tools/World/setdress_v2_sites.json').read_bytes())
    sites = {s['id']: s for s in data['sites']}
    wanted = ['R03_Verge3300', 'L10_FootFarm', 'S18_TeaHearth', 'S19_LastWaystation', 'S14_DeparturePlatform', 'S15_Works', 'L06_DescentCarts', 'S11_SignalFire']
    groups = {}
    for sid in wanted:
        for it in sites[sid]['placements']:
            key = it['key'].lower()
            if not (any(w in key for w in ('bag','flour','sand','rock','rubble','cart','fire')) or it.get('cat')=='wall'):
                continue
            if sid=='L10_FootFarm' and math.hypot(it['x_cm']-383844.4697,it['y_cm']-374909.3154)>11000:
                continue
            cell = (int(it['x_cm']//3000), int(it['y_cm']//3000))
            groups.setdefault((sid,cell),[]).append(it)
    rows=[]
    for (sid,cell),items in sorted(groups.items(),key=lambda g:(wanted.index(g[0][0]),g[0][1])):
        x,y=cell;name=f'{sid}_{x}_{y}';folder=args.out/name
        code=HEAD+f'BOX={[x*3000,y*3000,(x+1)*3000,(y+1)*3000]!r}\nCOHORT={sid!r}\n'+DESCRIPTORS
        script=write(folder/'00_descriptors.py',code)
        rows.append({'cohort':sid,'road_m':sites[sid]['road_m'],'query_grid':[x,y],'query_grid_is_not_wp_runtime_cell':True,'historical_candidates':items,'script':script,'actor_guid_status':'requires_actual_descriptor_receipt','hlod_owner_status':'requires_actual_descriptors; HLOD overlap is candidate owner, never support'})
    write(args.out/'manifest.json',{'status':'prepared_not_executed','carrier_actual_cm':[383844.4697,374909.3154,-33341.0680],'excluded_saved_labels':sorted(EXCLUDED),'rows':rows,'calls_executed':0})
    print(json.dumps({'out':str(args.out),'descriptor_packets':len(rows),'candidate_placements':sum(len(r['historical_candidates']) for r in rows),'next':rows[0]['script']['script']}))


def bind(args):
    data=receipt(args.receipt,'REPORTED_DESCRIPTORS')
    byguid={r['guid']:r for r in data['rows']}
    hosts=[byguid[g] for g in args.guid]
    assert 1<=len(hosts)<=2 and len(hosts)==len(set(args.guid))
    assert all(h['label'] not in EXCLUDED and 'HLOD' not in h['class'] and 'Landscape' not in h['class'] for h in hosts)
    terrain=[r for r in data['rows'] if 'Landscape' in r['class']]
    assert 1<=len(terrain)<=2,'Need exact nearby terrain descriptors; do not all-map load'
    owners=[r for r in data['rows'] if 'HLOD' in r['class']]
    load=HEAD+'HOSTS='+repr(hosts+terrain)+'\n'+'''
guids=[]
for e in HOSTS:
 assert e['package'] not in dirty(),'Unrelated dirty source; stop before load'
 g=unreal.Guid();assert g.import_text(e['guid']);guids.append(g)
unreal.WorldPartitionBlueprintLibrary.load_actors(guids)
print('REPORTED_LOAD_REQUESTED '+json.dumps({'rows':HOSTS,'separate_catalog_required':True,'saved':False},separators=(',',':')))
'''
    scripts=[write(args.out/'10_load_exact_guids.py',load)]
    for i,h in enumerate(hosts+terrain):
        scripts.append(write(args.out/f'20_catalog_{i:02d}.py',HEAD+'HOSTS='+repr([h])+'\nOWNERS='+repr(owners)+'\nEXCLUDED='+repr(EXCLUDED)+'\n'+CATALOG))
    write(args.out/'manifest.json',{'descriptor_receipt':str(args.receipt.resolve()),'sha256':sha(args.receipt),'hosts':hosts,'terrain':terrain,'overlapping_hlod_candidates':owners,'scripts':scripts,'editor_calls':0})
    print(json.dumps({'scripts':scripts}))


def measure(args):
    data=receipt(args.receipt,'REPORTED_CATALOG');scripts=[];unresolved=[]
    for row in data['rows']:
        assert row['host']['label'] not in EXCLUDED
        for e in row['components']:
            if not 3<=e['render_vertices']<=20000:
                unresolved.append({'component':e['component'],'reason':'needs separate bounded full render geometry extraction'});continue
            assert e['count']==len(e['poses']), 'Every actual ISM instance is required'
            for pin in e['poses']:
                spec={'host':row['host'],'component':e,'pin':pin}
                name=hashlib.sha256((e['component']+str(pin['index'])).encode()).hexdigest()[:12]
                scripts.append(write(args.out/f'30_contact_{name}.py',HEAD+'SPEC='+repr(spec)+'\n'+TRACE+MEASURE))
    write(args.out/'manifest.json',{'catalog_receipt':str(args.receipt.resolve()),'sha256':sha(args.receipt),'scripts':scripts,'unresolved':unresolved,'every_measurable_instance':True,'editor_calls':0})
    print(json.dumps({'scripts':len(scripts),'unresolved':unresolved}))


def fix(args):
    cat=receipt(args.catalog,'REPORTED_CATALOG');assert len(cat['rows'])==1
    row=cat['rows'][0];host=row['host'];assert host['label'] not in EXCLUDED
    assert not any(k in host['label'].lower() or k in e['mesh'].lower() for e in row['components'] for k in ('signalfire','fire_pit','firepit','campfire')),'Fire ring/logs require root-reviewed whole assembly support, including unattached nearby fuel'
    assert not row['attached'],'Attached children need an explicitly pinned shared assembly packet'
    assert len(row['components'])==1,'Packed carts/firewood need the existing shared-actor assembly flow'
    e=row['components'][0]
    contacts=[receipt(p,'REPORTED_CONTACT') for p in args.contact]
    assert all(d['host']==host and d['component']==e and d['complete'] for d in contacts)
    assert {d['pin']['index'] for d in contacts}==set(range(e['count'])) and len(contacts)==e['count'],'Measure all actual component instances'
    assert 0<=args.sink<=3 and 5<args.max_drop<=300
    changes=[]
    for d in contacts:
        samples=d['samples'];assert 3<=len(samples)<=9
        assert all(s['ground']['first_real_support']['kind']=='landscape' for s in samples),'Stack/platform support: do not lower an individual bag to Landscape'
        gaps=[s['ground']['landscape']['gap_cm'] for s in samples]
        assert all(math.isfinite(g) for g in gaps)
        if min(gaps)<=5:continue
        delta=-min(gaps)-args.sink
        assert -args.max_drop<=delta<-5,'Large drop requires separate root review'
        changes.append({'pin':d['pin'],'delta_z_cm':delta,'samples':samples})
    assert changes,'No fully floating measured instances'
    assert sum(len(r['samples']) for r in changes)<=16,'Split approved changes into <=96 worst-case rays; retain whole-host pose pins'
    file=ROOT/'Content'/(host['package'][6:]+'.uasset');assert file.is_file()
    args.out=args.out.resolve();assert args.out.is_relative_to(OUT.resolve())
    args.out.mkdir(parents=True,exist_ok=False);backup=args.out/'host_before.uasset';shutil.copy2(file,backup)
    plan={'host':host,'component':e,'changes':changes,'source_before_sha256':sha(file),'backup':str(backup),'backup_sha256':sha(backup),'reviewed_contact_receipts':[{'file':str(p.resolve()),'sha256':sha(p)} for p in args.contact],'root_support_and_lit_review_pending':True}
    pins=HEAD+'PLAN='+repr(plan)+'\n'+TRACE+CHECK
    scripts=[write(args.out/'40_apply_z_only.py',pins+APPLY),write(args.out/'50_verify_contacts_before_save.py',pins+VERIFY),write(args.out/'60_force_save_exact_package.py',pins+SAVE),write(args.out/'70_unload_clean_host.py',pins+UNLOAD),write(args.out/'80_prove_old_object_absent.py',HEAD+'PLAN='+repr(plan)+'\n'+ABSENT),write(args.out/'90_reload_exact_guid.py',HEAD+'PLAN='+repr(plan)+'\n'+RELOAD),write(args.out/'95_verify_reloaded_contacts.py',pins+VERIFY)]
    write(args.out/'plan.json',dict(plan,scripts=scripts,editor_calls=0,saved=False,fresh_reload_required=True,lit_evidence_required=True))
    print(json.dumps({'out':str(args.out),'changes':len(changes),'next':scripts[0]}))


CHECK = '''
a=actor_of(PLAN['host']);e=PLAN['component'];c=unreal.find_object(None,e['component'])
assert unreal.SystemLibrary.is_valid(c) and c.get_owner()==a and path(c.static_mesh)==e['mesh']
assert props(c)==e['properties'] and (c.get_instance_count() if e['is_ism'] else 1)==e['count']
changes={r['pin']['index']:r for r in PLAN['changes']}
def check(after,contacts):
 if e['is_ism']:assert a.get_actor_transform().export_text()==PLAN['host']['transform'] and c.get_world_transform().export_text()==e['component_transform']
 rows=[]
 for pin in e['poses']:
  pose=c.get_instance_transform(pin['index'],True) if e['is_ism'] else c.get_world_transform()
  delta=changes[pin['index']]['delta_z_cm'] if after and pin['index'] in changes else 0
  assert matches(pose,pin['transform'],delta),'An actual instance changed outside reviewed Z delta'
 if contacts:
  for r in PLAN['changes']:
   pose=c.get_instance_transform(r['pin']['index'],True) if e['is_ism'] else c.get_world_transform()
   for s in r['samples']:
    got=ground(pose.transform_location(unreal.Vector(*s['local'])));before=s['ground']['landscape'];now=got['landscape']
    assert got['first_real_support']['kind']=='landscape','New real support; stop'
    assert now['host']==before['host'] and all(now[k]==before[k] for k in ('transform','collision_mip','simple_collision_mip','material'))
    want=before['gap_cm']+(r['delta_z_cm'] if after else 0)
    assert abs(now['gap_cm']-want)<=.05,'Measured support changed; stop'
    rows.append({'index':r['pin']['index'],'vertex_index':s['vertex_index'],'gap_cm':now['gap_cm'],'expected_gap_cm':want})
 return rows
'''
APPLY = '''
assert PLAN['host']['package'] not in dirty(),'Preserve unrelated dirty edits'
check(False,True)
a.modify();c.modify()
for r in PLAN['changes']:
 pose=c.get_instance_transform(r['pin']['index'],True) if e['is_ism'] else a.get_actor_transform()
 v=pose.translation;pose.translation=unreal.Vector(v.x,v.y,v.z+r['delta_z_cm'])
 if e['is_ism']:
  local=unreal.MathLibrary.make_relative_transform(pose,c.get_world_transform())
  assert c.update_instance_transform(r['pin']['index'],local,False,True,True)
 else:
  root=a.get_editor_property('root_component');assert root is not None;root.modify();a.set_actor_transform(pose,False,False)
check(True,False)
print('REPORTED_APPLIED '+json.dumps({'host':identity(a),'changes':PLAN['changes'],'saved':False,'contact_and_lit_acceptance_pending':True},separators=(',',':')))
'''
VERIFY = '''
rows=check(True,True)
print('REPORTED_VERIFIED '+json.dumps({'host':identity(a),'rows':rows,'read_only':True,'saved':False,'lit_acceptance_is_separate':True},separators=(',',':')))
'''
SAVE = '''
check(True,False)
assert unreal.EditorLoadingAndSavingUtils.save_packages([a.get_package()],False),'Exact force save failed'
assert PLAN['host']['package'] not in dirty()
print('REPORTED_SAVED '+json.dumps({'host':identity(a),'only_dirty':False,'saved':True,'fresh_reload_pending':True},separators=(',',':')))
'''
UNLOAD = '''
check(True,False);assert PLAN['host']['package'] not in dirty()
eas=unreal.get_editor_subsystem(unreal.EditorActorSubsystem);selected=list(eas.get_selected_level_actors())
if a in selected:eas.set_selected_level_actors([v for v in selected if v!=a])
unreal.WorldPartitionBlueprintLibrary.unload_actors([a.get_editor_property('actor_guid')])
print('REPORTED_UNLOAD_REQUESTED '+json.dumps({'host':PLAN['host'],'clean':True,'normal_gc_then_absence_proof_required':True}))
'''
ABSENT = '''
assert not unreal.SystemLibrary.is_valid(unreal.find_object(None,PLAN['host']['actor'])),'Old UObject still resident; fresh disk proof unavailable'
print('REPORTED_OLD_OBJECT_ABSENT '+json.dumps({'host':PLAN['host'],'absent':True}))
'''
RELOAD = '''
assert not unreal.SystemLibrary.is_valid(unreal.find_object(None,PLAN['host']['actor'])),'Prove old object absent first'
g=unreal.Guid();assert g.import_text(PLAN['host']['guid'])
unreal.WorldPartitionBlueprintLibrary.load_actors([g])
print('REPORTED_RELOAD_REQUESTED '+json.dumps({'host':PLAN['host'],'separate_verification_call_required':True}))
'''


if __name__=='__main__':
    p=argparse.ArgumentParser();s=p.add_subparsers(dest='mode',required=True)
    a=s.add_parser('seed');a.add_argument('--out',type=Path,default=OUT/'discovery_v1')
    a=s.add_parser('bind');a.add_argument('--receipt',type=Path,required=True);a.add_argument('--guid',action='append',required=True);a.add_argument('--out',type=Path,required=True)
    a=s.add_parser('measure');a.add_argument('--receipt',type=Path,required=True);a.add_argument('--out',type=Path,required=True)
    a=s.add_parser('fix');a.add_argument('--catalog',type=Path,required=True);a.add_argument('--contact',type=Path,action='append',required=True);a.add_argument('--sink',type=float,default=1);a.add_argument('--max-drop',type=float,default=200);a.add_argument('--out',type=Path,required=True)
    args=p.parse_args();globals()[args.mode](args)
