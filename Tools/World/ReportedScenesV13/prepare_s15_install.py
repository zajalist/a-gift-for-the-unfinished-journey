"""Prepare bounded S15 refinement packets from complete, actual V15 receipts.

Offline only. Root executes read-only fits, then their emitted native commands.
No v2 labels, source terrain heights or dynamic/render vertex-count equivalence.
"""
from __future__ import annotations
import hashlib
import json
import argparse
from pathlib import Path
import prepare
from unwrap_receipt import unwrap

OUT = prepare.OUT / 'S15_install_actual_v17'
OLD = '/Game/AshesOfBazaar/Meshes/SM_300x400_Mid_Damaged_A.SM_300x400_Mid_Damaged_A'
LOW = '/Game/AshesOfBazaar/Meshes/SM_300x100_Panel_Damages_A.SM_300x100_Panel_Damages_A'
PLANS = {
 '002': {'mode':'low','z_scale':1.0,'sink_cm':8.0,'role':'north low broken foundation'},
 '003': {'mode':'gap','role':'north 3m breach'},
 '004': {'mode':'retain','role':'west corner anchor'},
 '005': {'mode':'low','z_scale':1.0,'sink_cm':12.0,'role':'south low broken foundation'},
 '006': {'mode':'remnant','z_scale':0.55,'sink_cm':8.0,'role':'south 2.2m remnant'},
 '007': {'mode':'retain','role':'east corner anchor'},
 '008': {'mode':'low','z_scale':0.65,'sink_cm':6.0,'role':'east 0.65m broken stump'},
}

COMMON = '''
import hashlib
a=actor_of(SPEC['host'])
comps=[c for c in a.get_components_by_class(unreal.StaticMeshComponent) if unreal.SystemLibrary.is_valid(c.static_mesh)]
assert len(comps)==1 and not isinstance(comps[0],unreal.InstancedStaticMeshComponent)
assert not a.get_attached_actors(),'Protect attached/story assemblies'
c=comps[0]
assert a.get_package().get_name() not in dirty() if not VERIFY else True
original=unreal.Transform();assert original.import_text(SPEC['pose'])
if not VERIFY:
 assert matches(a.get_actor_transform(),SPEC['pose']) and matches(c.get_world_transform(),SPEC['pose'])
 assert path(c.static_mesh)==SPEC['old_mesh']
 assert [path(c.get_material(i)) for i in range(c.get_num_materials())]==SPEC['materials']
before={'actor_transform':a.get_actor_transform().export_text(),'component':path(c),'component_transform':c.get_world_transform().export_text(),'mesh':path(c.static_mesh),'properties':props(c),'tags':[str(t) for t in a.tags],'body_instance':c.get_editor_property('body_instance').export_text()}
plan=SPEC['plan'];mode=plan['mode'];commands=[]
'''

FIT = '''
mesh=unreal.load_asset(SPEC['low_mesh'] if mode=='low' else SPEC['old_mesh'])
assert unreal.SystemLibrary.is_valid(mesh) and mesh.get_package().get_name() not in dirty()
def geometry(asset):
 assert unreal.SystemLibrary.is_valid(asset)
 render_count=unreal.get_editor_subsystem(unreal.StaticMeshEditorSubsystem).get_number_verts(asset,0)
 assert 3<=render_count<=20000
 dm=unreal.DynamicMesh();lod=unreal.GeometryScriptMeshReadLOD();lod.lod_type=unreal.GeometryScriptLODType.RENDER_DATA;lod.lod_index=0
 options=unreal.GeometryScriptCopyMeshFromAssetOptions();options.request_tangents=False
 dm,outcome=unreal.GeometryScript_AssetUtils.copy_mesh_from_static_mesh(asset,dm,options,lod)
 assert outcome==unreal.GeometryScriptOutcomePins.SUCCESS
 got=unreal.GeometryScript_MeshQueries.get_all_vertex_positions(dm,False);assert not got[2]
 verts=unreal.GeometryScript_List.convert_vector_list_to_array(got[1])
 assert 3<=len(verts)<=render_count,'Welded dynamic vertices must be pinned independently'
 digest=hashlib.sha256(json.dumps([xyz(v) for v in verts],separators=(',',':')).encode()).hexdigest()
 lo=[min(v.x for v in verts),min(v.y for v in verts),min(v.z for v in verts)]
 hi=[max(v.x for v in verts),max(v.y for v in verts),max(v.z for v in verts)]
 return verts,{'mesh':path(asset),'render_vertices':render_count,'dynamic_vertices':len(verts),'vertex_sha256':digest,'local_min':lo,'local_max':hi}
verts,geo=geometry(mesh)
oldverts,oldgeo=geometry(unreal.load_asset(SPEC['old_mesh'])) if mode=='low' else (verts,geo)
assert not expired(),'Split geometry call if native rendering extraction exceeds budget'
if mode=='low':
 assert abs(geo['local_max'][2]-geo['local_min'][2]-100)<1
 # Map new X-long axis onto old Y-long axis. Compute local displacement from
 # actual rendered mesh centres, not registry bounds or a assumed pivot.
 yaw=90.0;zs=plan['z_scale'];oldcentre=[(x+y)/2 for x,y in zip(oldgeo['local_min'],oldgeo['local_max'])]
 newcentre=[(x+y)/2 for x,y in zip(geo['local_min'],geo['local_max'])]
 offset=unreal.Vector(oldcentre[0]+newcentre[1],oldcentre[1]-newcentre[0],oldgeo['local_min'][2]-geo['local_min'][2]*zs)
else:
 yaw=0.0;zs=plan['z_scale'];offset=unreal.Vector(0,0,geo['local_min'][2]*(1-zs))
local=unreal.Transform();local.translation=offset;local.rotation=unreal.Rotator(0,yaw,0).quaternion();local.scale3d=unreal.Vector(1,1,zs)
pose=unreal.MathLibrary.compose_transforms(local,original)
# compose_transforms(A,B) applies A then B. Explicitly prove it for each fit.
probe=verts[0];got=unreal.MathLibrary.transform_location(pose,probe)
want=unreal.MathLibrary.transform_location(original,unreal.MathLibrary.transform_location(local,probe))
assert (got-want).length()<.02,'Local delta composition order changed'
ws=[unreal.MathLibrary.transform_location(pose,v) for v in verts]
basal=[i for i,v in enumerate(verts) if v.z<=geo['local_min'][2]+max(1,(geo['local_max'][2]-geo['local_min'][2])*.025)]
assert len(basal)>=3,'Basal render geometry unavailable'
lo=[min(ws[i].x for i in basal),min(ws[i].y for i in basal)];hi=[max(ws[i].x for i in basal),max(ws[i].y for i in basal)]
bins={}
for i in basal:
 p=ws[i]
 b=tuple(min(2,int((value-lo[k])*3/max(hi[k]-lo[k],.001))) for k,value in enumerate((p.x,p.y)))
 if b not in bins or p.z<ws[bins[b]].z:bins[b]=i
samples=[]
for b in sorted(bins):
 i=bins[b];samples.append({'bin':list(b),'vertex_index':i,'local':xyz(verts[i]),'world':xyz(ws[i]),'ground':ground(ws[i])})
assert 3<=len(samples)<=9
assert all(s['ground']['first_real_support']['kind']=='landscape' for s in samples),'Stack/other mesh support needs root review'
gaps=[s['ground']['landscape']['gap_cm'] for s in samples]
assert max(gaps)-min(gaps)<=55,'Slope would bury too much of a low remnant'
shift=-max(gaps)-plan['sink_cm']
assert abs(shift)<=100,'Ground change exceeds scoped fit; no mutation commands emitted'
pose.translation=unreal.Vector(pose.translation.x,pose.translation.y,pose.translation.z+shift)
rot=pose.rotation.rotator()
params={'actor_id':SPEC['host']['actor'],'location':xyz(pose.translation),'rotation':[rot.pitch,rot.yaw,rot.roll],'scale':xyz(pose.scale3d)}
commands=[{'command':'object_set_property','params':{'path':path(c),'properties':{'StaticMesh':path(mesh)}}},{'command':'actor_transform','params':params}]
after_gaps=[g+shift for g in gaps]
assert max(after_gaps)<=-plan['sink_cm']+.001
if VERIFY:
 assert path(c.static_mesh)==path(mesh) and matches(a.get_actor_transform(),pose.export_text()) and matches(c.get_world_transform(),pose.export_text())
 assert [path(c.get_material(i)) for i in range(c.get_num_materials())]==SPEC['materials']
 assert c.is_visible() and not c.get_editor_property('hidden_in_game')
 commands=[]
metadata=[];meta_ids={}
def pack_hit(hit):
 meta={k:v for k,v in hit.items() if k not in ('point','normal','gap_cm')};key=json.dumps(meta,sort_keys=True,separators=(',',':'))
 if key not in meta_ids:meta_ids[key]=len(metadata);metadata.append(meta)
 return [meta_ids[key],hit['point'],hit['normal'],hit['gap_cm']]
packed=[]
for s in samples:
 g=s['ground'];packed.append({'bin':s['bin'],'vertex_index':s['vertex_index'],'local':s['local'],'world':s['world'],'landscape':pack_hit(g['landscape']),'first_real_support':pack_hit(g['first_real_support']),'occluders':[pack_hit(h) for h in g['occluders']]})
payload={'host':SPEC['host'],'role':plan['role'],'before':before,'candidate_transform':pose.export_text(),'geometry':geo,'old_geometry':oldgeo,'local_delta':local.export_text(),'samples':packed,'contact_metadata':metadata,'fit_z_cm':shift,'fitted_landscape_gap_cm':after_gaps,'native_commands':commands,'verified':VERIFY,'read_only':True,'saved':False,'complete':len(samples)==len(bins),'rays':trace_count,'basal_local_z_band_cm':max(1,(geo['local_max'][2]-geo['local_min'][2])*.025),'wpo_not_in_base_vertices':True}
encoded=json.dumps(payload,separators=(',',':'));assert len(encoded)<7800,'Lossless packet exceeded native transport bound'
print('S15_WALL_FIT '+encoded)
'''

SIMPLE = '''
if mode=='gap':
 if VERIFY:
  assert not c.is_visible() and c.get_editor_property('hidden_in_game') and c.get_collision_enabled()==unreal.CollisionEnabled.NO_COLLISION
 else:
  commands=[{'command':'object_set_property','params':{'path':path(c),'properties':{'bVisible':False,'bHiddenInGame':True,'BodyInstance':{'CollisionEnabled':'NoCollision'}}}}]
else:
 assert path(c.static_mesh)==SPEC['old_mesh'] and matches(a.get_actor_transform(),SPEC['pose']) and matches(c.get_world_transform(),SPEC['pose'])
 assert [path(c.get_material(i)) for i in range(c.get_num_materials())]==SPEC['materials']
print('S15_WALL_SIMPLE '+json.dumps({'host':SPEC['host'],'role':plan['role'],'before':before,'native_commands':commands,'verified':VERIFY,'read_only':True,'saved':False},separators=(',',':')))
'''

def main():
    global OUT
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,default=OUT);args=parser.parse_args()
    OUT=args.out.resolve()
    assert OUT.is_relative_to(prepare.OUT.resolve())
    paths=[prepare.ROOT/'Saved/Verification/live_completion_20261001'/name for name in ('S15_discovery_v15.json','S15_discovery_page12_v15.json','S15_wall_catalog_v15.json')]
    receipts=[unwrap(json.loads(p.read_bytes())) for p in paths]
    desc=[]
    for output in receipts[:2]:
        data=json.loads(output.split('REPORTED_DESCRIPTOR_PAGE ',1)[1]);assert data['complete_page'] and data['relevant_total']==19
        desc.extend(dict(zip(data['row_fields'],row)) for row in data['rows'])
    catalog=json.loads(receipts[2].split('WALL_CATALOG ',1)[1]);assert len(catalog)==7
    bylabel={d['label']:d for d in desc}; scripts=[]
    for row in sorted(catalog,key=lambda r:r['label']):
        suffix=row['label'][-3:];assert suffix in PLANS and row['mesh']==OLD
        host={k:bylabel[row['label']][k] for k in ('guid','actor','label','class','package')}
        assert host['actor']==row['actor'] and host['package']==row['package'] and host['class']=='StaticMeshActor'
        spec={'host':host,'pose':row['pose'],'old_mesh':OLD,'low_mesh':LOW,'materials':row['materials'],'plan':PLANS[suffix]}
        for verify in (False,True):
            stage='30_verify' if verify else '10_fit'
            body=FIT if spec['plan']['mode'] in ('low','remnant') else SIMPLE
            script=prepare.write(OUT/f'{stage}_{suffix}.py',prepare.HEAD+f'SPEC={spec!r}\nVERIFY={verify!r}\n'+COMMON+(prepare.TRACE if body==FIT else '')+body)
            scripts.append(dict(script,label=row['label'],mode=spec['plan']['mode'],phase=stage))
    prepare.write(OUT/'manifest.json',{'status':'prepared_not_executed','source_receipts':[{'path':str(p),'sha256':prepare.sha(p)} for p in paths],'cohort':list(PLANS),'plans':PLANS,'scripts':scripts,'root_only':True,'editor_calls':0,'save':'Root saves only five modified exact external actor packages after fresh Lit review; retain actors and asset packages are excluded.','order':'Load exact cohort + Landscape2 proxies using prior root identities. Execute fit scripts individually. Store complete receipts. Execute each emitted native command sequentially after identity/fit review. Execute verify scripts individually, then capture fresh Lit and save exact actor packages. Source HLOD ownership and resulting fresh render must be checked by root.','ground_contact':'Actual RenderLOD0 lowest vertex per occupied 3x3 footprint bin, real Landscape only, max gap <= -sink. Dynamic mesh count separately pinned from render count. WPO not evaluated.'})
    print(json.dumps({'out':str(OUT),'fit_calls':7,'native_mutations':9,'verified_calls':7,'editor_calls':0}))

if __name__=='__main__':main()
