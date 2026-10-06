"""Move the new S26 gate and both pads outward together; protected house stays fixed."""
from pathlib import Path
import ast
import hashlib
import json
import math

ROOT=Path(__file__).resolve().parents[3]
BASE=ROOT/'Saved/Tripo/20261001/station_plinths'

def read(path):
    e=json.loads(path.read_text(encoding='utf-8'));assert e['status']=='ok'
    return json.loads(next(s.split('S26_LEVEL_PLINTH ',1)[1] for s in e['output'].splitlines() if s.startswith('S26_LEVEL_PLINTH ')))

EDITOR=r'''import unreal,json,math,datetime
APPLY=__APPLY__
OLD=__OLD__
PRIOR=__PRIOR__
SHIFT=__SHIFT__
es=unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem);assert es.get_game_world() is None,'Stop PIE'
world=es.get_editor_world();assert world.get_name()=='Saskarta_WP'
actors=list(unreal.EditorLevelLibrary.get_all_level_actors());assert len(actors)<2500
targets=[]
for prior in PRIOR:
 matches=[a for a in actors if a.get_path_name()==prior['actor']];assert len(matches)==1
 a=matches[0];assert 'S26_LEVEL_PLINTH_20261001' in [str(t) for t in a.tags] and a.get_package().get_name()==prior['package']
 if APPLY:assert a.get_actor_transform().export_text()==prior['transform'],'Gate or pad moved after the measured contact correction'
 targets.append(a)
assert [a.get_actor_label() for a in targets]==['SD_S26_Upgrade_20261001_Gate_Stone0','SD_S26_Upgrade_20261001_Gate_Stone1','SD_S26_Upgrade_20261001_Gate']
assert all(a.static_mesh_component.static_mesh.get_path_name()=='/Game/SaskartaGaea/Environment/Batch01/SM_B01_floor01.SM_B01_floor01' for a in targets[:2])
assert targets[2].static_mesh_component.static_mesh.get_path_name()=='/Game/SaskartaGaea/Environment/Tripo02/SM_T2_s26_gate_open.SM_T2_s26_gate_open'
started=datetime.datetime.now(datetime.timezone.utc);calls=0
ignored=[a for a in actors if 'S26_LEVEL_PLINTH_20261001' in [str(t) for t in a.tags]]
def budget():assert calls<180 and (datetime.datetime.now(datetime.timezone.utc)-started).total_seconds()<4.5,'Bounded relocation trace budget exceeded'
def unpack(h):
 if isinstance(h,tuple) and len(h)==2 and not isinstance(h[0],unreal.HitResult):return h[1] if h[0] else None
 return h
def terrain(p):
 global calls
 skip=list(ignored)
 for layer in range(8):
  budget();calls+=1
  hit=unpack(unreal.SystemLibrary.line_trace_single(world,unreal.Vector(p[0],p[1],16000.),unreal.Vector(p[0],p[1],5000.),unreal.TraceTypeQuery.TRACE_TYPE_QUERY1,True,skip,unreal.DrawDebugTrace.NONE,True))
  assert hit is not None and hit.to_tuple()[0],'Current terrain unavailable'
  h=hit.to_tuple();a=h[9];assert a is not None
  if isinstance(a,unreal.LandscapeProxy):
   assert a.get_actor_label()=='LandscapeStreamingProxy_6_9_0'
   return {'xy':p,'z':h[5].z,'actor':a.get_path_name(),'transform':a.get_actor_transform().export_text()}
  skip.append(a)
 raise RuntimeError('No landscape through bounded occluders')
grounds=[]
for grid in OLD['terrain']:
 current=[]
 for old in grid:
  h=terrain(old['xy']);assert h['actor']==old['actor'] and h['transform']==old['transform'] and abs(h['z']-old['z'])<.5,'Prior terrain changed'
  h=terrain([old['xy'][i]+SHIFT[i] for i in range(2)]);assert h['actor']==old['actor'] and h['transform']==old['transform']
  current.append(h)
 grounds.append(current)
dz=min(min(h['z'] for h in fresh)-min(h['z'] for h in old) for fresh,old in zip(grounds,OLD['terrain']))
assert -15.<=dz<=1.,'Outward site needs more than the reviewed rigid seating change'
pads=[]
for old,grid in zip(OLD['pads'],grounds):
 p=dict(old);p['world_xy']=[old['world_xy'][i]+SHIFT[i] for i in range(2)]
 for k in ['z','top','bottom']:p[k]=old[k]+dz
 assert min(h['z'] for h in grid)-p['bottom']>=7. and p['top']-max(h['z'] for h in grid)>=3.,'Current terrain does not contain the entire translated pad'
 pads.append(p)
old_gate_xy=[297727.71693849546,483493.9758174929]
gate_xy=[old_gate_xy[i]+SHIFT[i] for i in range(2)];body_z=OLD['body_z']+dz
poses=[p['world_xy']+[p['z']] for p in pads]+[gate_xy+[body_z]]
for a,pos in zip(targets,poses):
 if APPLY:a.modify();a.set_actor_location(unreal.Vector(*pos),False,False)
 p=a.get_actor_location();r=a.get_actor_rotation()
 assert all(abs(v-w)<.02 for v,w in zip([p.x,p.y,p.z],pos)) and abs(r.pitch)<.01 and abs(r.roll)<.01 and abs((r.yaw-OLD['yaw']+180)%360-180)<.01,'Relocation changed more than intended position'
changed=[{'actor':a.get_path_name(),'package':a.get_package().get_name(),'transform':a.get_actor_transform().export_text()} for a in targets]
angle=math.radians(OLD['yaw']);c,s=math.cos(angle),math.sin(angle);surface=[]
started=datetime.datetime.now(datetime.timezone.utc)
for p in OLD['contacts']:
 budget();calls+=1;x=gate_xy[0]+p[0]*c-p[1]*s;y=gate_xy[1]+p[0]*s+p[1]*c;z=body_z+p[2]
 hit=unpack(unreal.SystemLibrary.line_trace_single(world,unreal.Vector(x,y,z+100.),unreal.Vector(x,y,z-200.),unreal.TraceTypeQuery.TRACE_TYPE_QUERY1,True,[targets[2]],unreal.DrawDebugTrace.NONE,True))
 assert hit is not None and hit.to_tuple()[0]
 h=hit.to_tuple();surface.append({'point':[x,y,z],'actor':h[9].get_path_name() if h[9] else None,'owned_footing':h[9] in targets[:2],'clearance_cm':z-h[5].z})
assert all(p['owned_footing'] and abs(p['clearance_cm']-old['clearance_cm'])<.05 for p,old in zip(surface,OLD['surface_contacts'])),'Rigid move did not preserve measured foot contacts'
print('S26_LEVEL_PLINTH '+json.dumps({'id':'Gate','label':'SD_S26_Upgrade_20261001_Gate','pads':pads,'body_z':body_z,'yaw':OLD['yaw'],'world_xy_cm':gate_xy,'contacts':OLD['contacts'],'terrain':grounds,'changed':changed,'surface_contacts':surface,'surface_contact_pass':all(p['owned_footing'] and -4<=p['clearance_cm']<=4 for p in surface),'verified_transforms':True,'applied':APPLY,'saved':False,'translation_cm':SHIFT+[dz],'trace_calls':calls,'gate_collision_acceptance_pending':True},separators=(',',':')))
'''

PASSAGE=r'''
expected_xy=__XY__
assert abs(origin.x-expected_xy[0])<.02 and abs(origin.y-expected_xy[1])<.02,'Expected the 40cm outward gate relocation'
PATHS=__PATHS__
rows=[]
def densify(points):
 result=[points[0]]
 for a,b in zip(points,points[1:]):
  length=math.hypot(b[0]-a[0],b[1]-a[1]);count=max(1,math.ceil(length/25.))
  for i in range(1,count+1):result.append([a[j]+(b[j]-a[j])*i/count for j in range(2)])
 return result
for route in PATHS:
 points=[];supports=[];segments=[]
 for along,offset in densify(route['points']):
  budget();x=origin.x+along*co-offset*si;y=origin.y+along*si+offset*co
  # Find the walking floor beneath the open frame. The subsequent full-height
  # Pawn sweeps include the gate, so its lintel and leaves still test headroom.
  hit=unpack(unreal.SystemLibrary.line_trace_single(world,unreal.Vector(x,y,origin.z+400.),unreal.Vector(x,y,origin.z-300.),unreal.TraceTypeQuery.TRACE_TYPE_QUERY1,True,[gate],unreal.DrawDebugTrace.NONE,True))
  assert hit is not None and hit.to_tuple()[0],'Current walking surface missing'
  h=hit.to_tuple();a=h[9]
  landscape=isinstance(a,unreal.LandscapeProxy) and a.get_actor_label()=='LandscapeStreamingProxy_6_9_0'
  valid=landscape or (route['name']=='courtyard_to_entry' and a is not None and 'S26_LEVEL_PLINTH_20261001' in [str(t) for t in a.tags])
  supports.append({'local_cm':[round(along,3),round(offset,3)],'z':h[5].z,'actor':a.get_actor_label() if a else None,'normal_z':h[7].z,'pass':valid and h[7].z>=math.cos(math.radians(44.))})
  points.append(unreal.Vector(x,y,h[5].z+90.+32.*(1./max(h[7].z,.01)-1.)))
 for start,end in zip(points,points[1:]):
  budget();hit=unpack(unreal.SystemLibrary.capsule_trace_single_by_profile(world,start,end,32.,88.,'Pawn',False,[],unreal.DrawDebugTrace.NONE,True))
  h=hit.to_tuple() if hit is not None and hit.to_tuple()[0] else None
  segments.append({'blocked':h is not None,'actor':h[9].get_actor_label() if h is not None and h[9] else None})
 rows.append({'name':route['name'],'supports':supports,'segments':segments,'pass':all(s['pass'] for s in supports) and not any(s['blocked'] for s in segments)})
print('S26_GATE_PASSAGE '+json.dumps({'gate':gate.get_path_name(),'gate_transform':gate.get_actor_transform().export_text(),'rows':rows,'pass':all(r['pass'] for r in rows),'max_floor_step_cm':25,'saved':False},separators=(',',':')))
'''

def main():
    initial=read(BASE/'gate_receipts/Gate/apply.readback.json')
    corrected=read(BASE/'gate_contact_apply_readbacks/Gate_supported.readback.json')
    old=read(BASE/'gate_contact_verify_readbacks/Gate_supported.readback.json')
    assert old['surface_contact_pass']
    prior={r['actor']:r for r in initial['changed']}
    for r in corrected['changed']:prior[r['actor']]=r
    prior=[prior[r['actor']] for r in initial['changed']]
    angle=math.radians(old['yaw']);shift=[-40.*math.cos(angle),-40.*math.sin(angle)]
    out=BASE/'gate_relocation_v1';out.mkdir(parents=True,exist_ok=True);manifest=[]
    for name,apply in [('apply',True),('verify',False)]:
        code=EDITOR.replace('__OLD__',repr(old)).replace('__PRIOR__',repr(prior)).replace('__SHIFT__',repr(shift)).replace('__APPLY__',str(apply));ast.parse(code)
        path=out/(name+'.py');path.write_text(code,encoding='utf-8');manifest.append({'path':str(path.relative_to(ROOT)),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    header=(ROOT/'Tools/World/story_sets/verify_summit_gate_passage.py').read_text(encoding='utf-8').split('rows=[]',1)[0].replace('<3.5','<4.5')
    paths=[{'name':'opening_'+str(int(offset)),'points':[[-150.,offset],[130.,offset]]+([[130.,0.]] if offset else [])} for offset in (-15.,0.,15.)]
    paths.append({'name':'courtyard_to_entry','points':[[130.,0.],[130.,303.],[514.63,303.05]]})
    xy=[297727.71693849546+shift[0],483493.9758174929+shift[1]]
    code=header+PASSAGE.replace('__XY__',repr(xy)).replace('__PATHS__',repr(paths));ast.parse(code)
    path=out/'passage.py';path.write_text(code,encoding='utf-8');manifest.append({'path':str(path.relative_to(ROOT)),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8');print(out)

if __name__=='__main__':main()
