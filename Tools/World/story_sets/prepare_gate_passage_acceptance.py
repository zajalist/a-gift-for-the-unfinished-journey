"""Prepare final gate+entry passage proof from an actually passing bent probe."""
from pathlib import Path
import argparse
import ast
import hashlib
import json

ROOT=Path(__file__).resolve().parents[3]
BASE=ROOT/'Saved/Tripo/20261001/station_plinths'

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--bent-result',required=True,type=Path)
    args=ap.parse_args()
    env=json.loads(args.bent_result.read_text(encoding='utf-8'))
    assert env['status']=='ok'
    values=[json.loads(s.split('S26_GATE_BENT_APPROACH ',1)[1]) for s in env['output'].splitlines() if s.startswith('S26_GATE_BENT_APPROACH ')]
    assert len(values)==1
    result=values[0];passing=[r for r in result['routes'] if r['pass']]
    assert result['any_pass'] and passing,'A live passing bent approach is required; do not reduce the failed straight test arbitrarily'
    chosen=passing[0];assert all(p['pass'] for p in chosen['supports']) and not any(p['blocked'] for p in chosen['segments'])
    corrected=json.loads((BASE/'gate_contact_apply_readbacks/Gate_supported.readback.json').read_text(encoding='utf-8'))
    value=json.loads(next(s.split('S26_LEVEL_PLINTH ',1)[1] for s in corrected['output'].splitlines() if s.startswith('S26_LEVEL_PLINTH ')))
    gate=value['changed'][-1];assert gate['actor']==result['gate']
    source=(ROOT/'Tools/World/story_sets/verify_summit_gate_passage.py').read_text(encoding='utf-8')
    header=source.split('rows=[]',1)[0].replace('<3.5','<4.5')
    header+="\nassert gate.get_path_name()=="+repr(gate['actor'])+" and gate.get_actor_transform().export_text()=="+repr(gate['transform'])+",'Final accepted gate moved'\n"
    paths=[{'name':'opening_'+str(int(offset)),'require_landscape':True,'points':[[-150.,offset],[-75.,offset],[0.,offset],[75.,offset]]+([[75.,0.]] if offset else [])} for offset in (-15.,0.,15.)]
    paths.append({'name':'turn_to_authored_entry','require_landscape':False,'points':[p['local_cm'] for p in chosen['supports']]})
    body=r'''
PATHS=__PATHS__
rows=[]
for route in PATHS:
 points=[];supports=[];segments=[]
 for along,offset in route['points']:
  budget();x=origin.x+along*co-offset*si;y=origin.y+along*si+offset*co
  hit=unpack(unreal.SystemLibrary.line_trace_single(world,unreal.Vector(x,y,origin.z+400.),unreal.Vector(x,y,origin.z-300.),unreal.TraceTypeQuery.TRACE_TYPE_QUERY1,True,[],unreal.DrawDebugTrace.NONE,True))
  assert hit is not None and hit.to_tuple()[0],'Current path support missing'
  h=hit.to_tuple();a=h[9]
  landscape=isinstance(a,unreal.LandscapeProxy) and a.get_actor_label()=='LandscapeStreamingProxy_6_9_0'
  owned=a is not None and 'S26_LEVEL_PLINTH_20261001' in [str(t) for t in a.tags]
  valid=landscape or (not route['require_landscape'] and owned)
  supports.append({'local_cm':[along,offset],'actor':a.get_path_name() if a else None,'normal_z':h[7].z,'pass':valid and h[7].z>=math.cos(math.radians(44.))})
  points.append(unreal.Vector(x,y,h[5].z+90.+32.*(1./max(h[7].z,.01)-1.)))
 for start,end in zip(points,points[1:]):
  budget();hit=unpack(unreal.SystemLibrary.capsule_trace_single_by_profile(world,start,end,32.,88.,'Pawn',False,[],unreal.DrawDebugTrace.NONE,True))
  h=hit.to_tuple() if hit is not None and hit.to_tuple()[0] else None
  segments.append({'blocked':h is not None,'actor':h[9].get_path_name() if h is not None and h[9] else None})
 rows.append({'name':route['name'],'supports':supports,'segments':segments,'pass':all(s['pass'] for s in supports) and not any(s['blocked'] for s in segments)})
print('S26_GATE_PASSAGE '+json.dumps({'gate':gate.get_path_name(),'gate_transform':gate.get_actor_transform().export_text(),'rows':rows,'pass':all(r['pass'] for r in rows),'saved':False},separators=(',',':')))
'''
    code=header+body.replace('__PATHS__',repr(paths));ast.parse(code)
    path=BASE/'verify/Gate_passage_final_bent.py';path.write_text(code,encoding='utf-8')
    manifest={'script':str(path.relative_to(ROOT)),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'source_receipt':str(args.bent_result.resolve()),'source_receipt_sha256':hashlib.sha256(args.bent_result.read_bytes()).hexdigest(),'turn_x_cm':chosen['turn_x_cm'],'saved':False}
    path.with_suffix('.manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8');print(path)

if __name__=='__main__':main()
