"""Rebind saved real L06/S11 identities to fresh V13 catalog packets, offline only."""
import json
from prepare import ROOT, OUT, HEAD, CATALOG, EXCLUDED, write, sha

def old(p,marker):
    d=json.loads(p.read_bytes());text=d.get('output',d.get('stdout',''))
    rows=[s.split(' ',1)[1] for s in text.splitlines() if s.startswith(marker+' ')]
    assert len(rows)==1;return json.loads(rows[0])

def emit(name,rows,labels,owners,source):
    hosts=[r for r in rows if r['label'] in labels]
    terrain=[r for r in rows if 'Landscape' in r['class']]
    assert len(hosts)==len(labels) and len(terrain)==1
    folder=OUT/name;scripts=[]
    # At most two source hosts plus one terrain per load call.
    for start in range(0,len(hosts),2):
        batch=hosts[start:start+2]+terrain
        code=HEAD+'HOSTS='+repr(batch)+'\n'+'''
guids=[]
for e in HOSTS:
 assert e['package'] not in dirty(),'Unrelated dirty source'
 g=unreal.Guid();assert g.import_text(e['guid']);guids.append(g)
unreal.WorldPartitionBlueprintLibrary.load_actors(guids)
print('REPORTED_LOAD_REQUESTED '+json.dumps({'rows':HOSTS,'separate_catalog_required':True,'saved':False},separators=(',',':')))
'''
        scripts.append(write(folder/f'10_load_{start//2:02d}.py',code))
    for i,h in enumerate(hosts+terrain):
        scripts.append(write(folder/f'20_catalog_{i:02d}.py',HEAD+'HOSTS='+repr([h])+'\nOWNERS='+repr(owners)+'\nEXCLUDED='+repr(EXCLUDED)+'\n'+CATALOG))
    write(folder/'manifest.json',{'scripts':scripts,'source_receipt':str(source),'source_sha256':sha(source),'host_identities_from_real_saved_receipt':hosts,'terrain':terrain,'overlapping_hlod_candidates':owners,'poses_require_fresh_catalog':True,'editor_calls':0})

if __name__=='__main__':
    l06=ROOT/'Saved/Verification/live_completion_20261001/world_v12/L06_descriptors.json'
    emit('L06_exact_v1',old(l06,'FAST_WORLD_DESCRIPTORS')['rows'],['SD_L06_DescentCarts_000','SD_L06_DescentCarts_001','SD_L06_DescentCarts_002'],[],l06)
    s11=ROOT/'Saved/Verification/live_completion_20261001/signal_fire_actual_descriptors.json'
    raw=old(s11,'CAMPFIRE_WALL_CANDIDATES')['rows']
    rows=[{'label':r['label'],'guid':r['guid'],'actor':r['actor_path'],'package':r['package'],'class':r['native_class'],'bounds':r['bounds']} for r in raw]
    emit('S11_exact_v1',rows,['SD_S11_SignalFire_000','SD_S11_SignalFire_006'],[r for r in rows if 'HLOD' in r['class']],s11)
    print(json.dumps({'out':str(OUT),'known_l06_hosts':3,'known_s11_hosts':2,'calls_executed':0}))
