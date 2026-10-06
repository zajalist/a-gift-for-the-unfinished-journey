"""Offline bounded S15 source-box descriptor discovery without assumed labels."""
import argparse
import json
from pathlib import Path
import prepare


BODY='''
box=unreal.Box(unreal.Vector(438000,342000,-1000000),unreal.Vector(441000,345000,1000000))
raw=unreal.WorldPartitionBlueprintLibrary.get_intersecting_actor_descs(box)
descs=raw[1] if isinstance(raw,tuple) else raw
assert len(descs)<=300,'Split source box, do not load or scan map'
relevant=[];classes={}
for d in descs:
 cls=d.native_class.get_name() if d.native_class else '';label=str(d.label)
 classes[cls]=classes.get(cls,0)+1
 if cls not in ('StaticMeshActor','PackedLevelActor') and not label.startswith('SD_'):continue
 relevant.append([d.guid.export_text(),str(d.actor_path),label,cls,str(d.actor_package),[[d.bounds.min.x,d.bounds.min.y,d.bounds.min.z],[d.bounds.max.x,d.bounds.max.y,d.bounds.max.z]],bool(d.actor_is_editor_only)])
relevant.sort(key=lambda row:row[0])
page=relevant[OFFSET:OFFSET+12]
payload={'source_box':[438000,342000,441000,345000],'source_cohort':'S15_Works_W_1','row_fields':['guid','actor','label','class','package','bounds','editor_only'],'rows':page,'offset':OFFSET,'page_size':12,'relevant_total':len(relevant),'descriptor_total':len(descs),'native_class_counts':classes,'next_offset':OFFSET+len(page) if OFFSET+len(page)<len(relevant) else None,'complete_page':True,'read_only':True,'loaded':False,'saved':False,'source_label_mismatch_unresolved':True}
encoded=json.dumps(payload,separators=(',',':'));assert len(encoded)<7800,'Reduce page size rather than clipping identities'
print('REPORTED_DESCRIPTOR_PAGE '+encoded)
'''


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    scripts=[]
    for page in range(4):scripts.append(prepare.write(args.out/f'00_sourcebox_page_{page:02d}.py',prepare.HEAD+f'OFFSET={page*12}\n'+BODY))
    prepare.write(args.out/'manifest.json',{'status':'prepared_not_executed','source_evidence':'setdress_v2_sites.json S15_Works W_1 x438104..438779/y342378..343736; place_setdress.py:516 builds SD_+placementid','prior_exact_query_result':'All12v2labels absent; no actual identities or wall-removal authorization','scripts':scripts,'root_order':'Run page00 first. Follow native next_offset only. Do not issue further pages when next_offset=null. Exact sourcebox only, no map load.','editor_calls':0})
    print(json.dumps({'scripts':scripts}))
