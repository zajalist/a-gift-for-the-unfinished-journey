"""Prepare exact HLOD source-membership reads from complete real contacts."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import prepare


READ_MEMBERSHIP = '''
a=actor_of(HOST);assert 'HLOD' in a.get_class().get_name()
source=a.get_editor_property('source_actors');assert source is not None,'No current source-actors object; do not infer membership from bounds'
assert source.get_class().get_name()=='WorldPartitionHLODSourceActorsFromCell','Requires class-specific ownership read'
mappings=list(source.get_editor_property('actors'));assert len(mappings)<=4096,'Explicit membership pagination required'
matched=[];classes={}
for mapping in mappings:
 assert not expired(),'Membership scan exceeded bounded read budget'
 guid=mapping.get_editor_property('actor_instance_guid').export_text()
 cls=str(mapping.get_editor_property('native_class'))
 classes[cls]=classes.get(cls,0)+1
 if guid not in TARGET_GUIDS:continue
 matched.append({'guid':guid,'actor':str(mapping.get_editor_property('path')),'package':str(mapping.get_editor_property('package')),'native_class':cls,'container_transform':mapping.get_editor_property('container_transform').export_text(),'container_id':mapping.get_editor_property('container_id').export_text()})
comps=[]
for c in a.get_components_by_class(unreal.StaticMeshComponent):
 if c.static_mesh is None:continue
 assert len(comps)<16,'Split mesh-component read explicitly'
 comps.append({'component':path(c),'class':c.get_class().get_name(),'mesh':path(c.static_mesh),'transform':c.get_world_transform().export_text(),'materials':[path(c.get_material(i)) for i in range(c.get_num_materials())],'is_ism':isinstance(c,unreal.InstancedStaticMeshComponent),'count':c.get_instance_count() if isinstance(c,unreal.InstancedStaticMeshComponent) else 1})
data={'host':identity(a),'source_object':path(source),'source_class':source.get_class().get_name(),'hlod_layer':path(source.get_editor_property('hlod_layer')),'source_cell_guid':a.get_editor_property('source_cell_guid').export_text(),'lod_level':a.get_editor_property('lod_level'),'mapping_count':len(mappings),'complete_scan':True,'native_class_counts':classes,'target_guids':TARGET_GUIDS,'matched_sources':matched,'mesh_components':comps,'read_only':True,'loaded':False,'saved':False,'ownership_limit':'Direct mapping only; absence of bag GUID may mean another HLOD source level, not no ownership; no stale-proxy conclusion without child membership/build geometry evidence'}
encoded=json.dumps(data,separators=(',',':'));assert len(encoded)<7600,'Split metadata output without truncating'
print('REPORTED_HLOD_MEMBERSHIP '+encoded)
'''


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--contact',type=Path,action='append',required=True);parser.add_argument('--descriptor',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    descriptor=prepare.receipt(args.descriptor,'REPORTED_DESCRIPTORS')
    contacts=[prepare.receipt(p,'REPORTED_CONTACT') for p in args.contact]
    assert all(c['complete'] for c in contacts)
    targets={row['guid'] for row in descriptor['rows'] if row['label'].startswith('SD_R03_Verge3300_')}
    byguid={row['guid']:row for row in descriptor['rows']}
    occluders={hit['host']['guid'] for c in contacts for s in c['samples'] for hit in s['ground']['occluders'] if hit['kind']=='hlod'}
    assert len(occluders)==2
    targets|={row['guid'] for row in descriptor['rows'] if 'HLOD' in row['class']}
    commands=[];scripts=[];summaries=[]
    for guid in sorted(occluders):
        host=byguid[guid]
        commands.extend([{'command':'actor_inspect','params':{'actor_id':host['actor']}},{'command':'actor_get_components','params':{'actor_id':host['actor'],'include_internal':False}}])
        scripts.append(prepare.write(args.out/f'10_membership_{guid}.py',prepare.HEAD+'HOST='+repr(host)+'\nTARGET_GUIDS='+repr(sorted(targets))+'\n'+READ_MEMBERSHIP))
    for c in contacts:
        gaps=[s['ground']['landscape']['gap_cm'] for s in c['samples']]
        summaries.append({'host':c['host']['label'],'guid':c['host']['guid'],'samples':len(gaps),'min_gap_cm':min(gaps),'max_gap_cm':max(gaps),'decision':'KEEP_ACTUAL_SOURCE_POSE','reason':'Real Landscape contact exists; lowering would bury the currently grounded bag. HLOD ray collision does not itself prove older bag geometry.'})
    prepare.write(args.out/'native_inspections.json',{'commands':commands,'editor_calls':0})
    prepare.write(args.out/'manifest.json',{'status':'prepared_not_executed','scripts':scripts,'contact_evidence':[{'receipt':str(p.resolve()),'sha256':prepare.sha(p)} for p in args.contact],'grounded_sources':summaries,'next_other_sources':['R03_bags_001_004_actual_v1/10_load_exact_guids.py','R03_bag_005_cart_000_actual_v1/10_load_exact_guids.py'],'editor_calls':0})
    print(json.dumps({'scripts':scripts,'grounded_sources':summaries}))


if __name__=='__main__':main()
