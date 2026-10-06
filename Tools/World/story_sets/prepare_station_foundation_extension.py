"""Prepare one measured rear extension beside the protected S26 foundation."""
from pathlib import Path
import argparse
import ast
import json

ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'Saved/Tripo/20261001/station_foundation_extension'
LABEL='SD_S26_Station_FoundationExtension_20261001'
TAG='S26_STATION_FOUNDATION_EXTENSION_20261001'

EDITOR='''import unreal,json,math,datetime
PHASE='__PHASE__'
EXPECTED=__EXPECTED__
LABEL='__LABEL__';TAG='__TAG__'
es=unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
assert es.get_game_world() is None,'Stop PIE'
world=es.get_editor_world();assert world.get_name()=='Saskarta_WP'
eas=unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
actors=list(eas.get_all_level_actors());assert len(actors)<2500
found=[a for a in actors if a.get_actor_label()=='SD_S26_HighVoiceTripo_000']
assert len(found)==1,'Load protected foundation'
foundation=found[0]
assert foundation.get_actor_transform().export_text()=='(Rotation=(X=-0.000000,Y=0.000000,Z=-0.986771,W=0.162121),Translation=(X=297254.031044,Y=483333.449775,Z=10893.593557),Scale3D=(X=1.500000,Y=1.500000,Z=2.809695))','Protected foundation changed'
existing=[a for a in actors if a.get_actor_label()==LABEL]
assert len(existing)<=1
old=existing[0] if existing else None
if old:assert TAG in [str(t) for t in old.tags],'Existing label is not our extension'
floor=unreal.load_asset('/Game/SaskartaGaea/Environment/Batch01/SM_B01_floor01.SM_B01_floor01')
assert isinstance(floor,unreal.StaticMesh)
bb=floor.get_bounding_box()
lo=[bb.min.x,bb.min.y,bb.min.z];hi=[bb.max.x,bb.max.y,bb.max.z]
known=[[-152.2162,-152.6798,-8.1794],[152.0206,151.9715,9.7597]]
assert all(abs(a-b)<.1 for row,want in zip([lo,hi],known) for a,b in zip(row,want)),'Existing floor bounds changed'
if old:assert old.static_mesh_component.static_mesh==floor
origin=[297342.918097,483375.261496]
yaw=288.66;angle=math.radians(yaw);co=math.cos(angle);si=math.sin(angle)
rect=[[-205.,120.],[205.,241.25]]
def xy(p):return [origin[0]+p[0]*co-p[1]*si,origin[1]+p[0]*si+p[1]*co]
started=datetime.datetime.now(datetime.timezone.utc);calls=0
def terrain(p):
 global calls
 ignored=[old] if old else []
 for layer in range(6):
  assert calls<72 and (datetime.datetime.now(datetime.timezone.utc)-started).total_seconds()<3.5,'Bounded terrain probe exhausted'
  calls+=1
  hit=unreal.SystemLibrary.line_trace_single(world,unreal.Vector(p[0],p[1],15921),unreal.Vector(p[0],p[1],921),unreal.TraceTypeQuery.TRACE_TYPE_QUERY1,True,ignored,unreal.DrawDebugTrace.NONE,True)
  if isinstance(hit,tuple) and len(hit)==2 and not isinstance(hit[0],unreal.HitResult):hit=hit[1] if hit[0] else None
  assert hit is not None and hit.to_tuple()[0],'Missing current support'
  data=hit.to_tuple();actor=data[9];assert actor is not None
  if isinstance(actor,unreal.LandscapeProxy):
   assert actor.get_actor_label()=='LandscapeStreamingProxy_6_9_0','Unexpected terrain source'
   return {'xy':p,'z':data[5].z,'actor':actor.get_path_name(),'transform':actor.get_actor_transform().export_text()}
  ignored.append(actor)
 raise RuntimeError('No current terrain behind bounded occluders')
grounds=[]
for u in (0.,.5,1.):
 for v in (0.,.5,1.):grounds.append(terrain(xy([rect[0][0]+410*u,rect[0][1]+121.25*v])))
top=10917.9;bottom=min(p['z'] for p in grounds)-8
assert max(p['z'] for p in grounds)<top-2,'Fixed foundation top would bury into terrain'
assert 12<top-bottom<90,'Unexpected support depth; do not stretch the stone farther'
scale=[410/(hi[0]-lo[0]),121.25/(hi[1]-lo[1]),(top-bottom)/(hi[2]-lo[2])]
local=[-(lo[0]+hi[0])*.5*scale[0],(120+241.25)*.5-(lo[1]+hi[1])*.5*scale[1]]
position=xy(local)+[top-hi[2]*scale[2]]
result={'phase':PHASE,'label':LABEL,'terrain':grounds,'rect':rect,'position':position,'scale':scale,'yaw':yaw,'top':top,'bottom':bottom,'saved':False}
if EXPECTED is not None:
 assert EXPECTED['rect']==rect and len(EXPECTED['terrain'])==len(grounds)
 for a,b in zip(EXPECTED['terrain'],grounds):
  assert a['xy']==b['xy'] and a['actor']==b['actor'] and a['transform']==b['transform'] and abs(a['z']-b['z'])<.5,'Current terrain changed since surveyed'
if PHASE=='apply':
 assert EXPECTED is not None,'Exact current terrain receipt required'
 rotation=unreal.Rotator(pitch=0.,yaw=yaw,roll=0.)
 old=old if old else eas.spawn_actor_from_class(unreal.StaticMeshActor,unreal.Vector(*position),rotation)
 assert old is not None
 old.modify();old.set_actor_label(LABEL);old.tags=[unreal.Name(TAG),unreal.Name('S26_UPGRADE_20261001')]
 old.static_mesh_component.set_static_mesh(floor);old.static_mesh_component.set_collision_profile_name('BlockAll')
 old.set_actor_location(unreal.Vector(*position),False,False);old.set_actor_rotation(rotation,False);old.set_actor_scale3d(unreal.Vector(*scale))
 old.set_folder_path('Set/S26_LevelSupports_20261001')
 result['actor']=old.get_path_name();result['package']=old.get_package().get_name()
if PHASE=='verify':
 assert old is not None and EXPECTED is not None
 p=old.get_actor_location();s=old.get_actor_scale3d();r=old.get_actor_rotation()
 assert all(abs(a-b)<.02 for a,b in zip([p.x,p.y,p.z],position))
 assert all(abs(a-b)<.0002 for a,b in zip([s.x,s.y,s.z],scale))
 assert abs(r.pitch)<.01 and abs(r.roll)<.01 and abs((r.yaw-yaw+180)%360-180)<.01
 supports=[]
 for x in (-195.,0.,195.):
  for y in (140.,185.,231.25):
   q=xy([x,y]);hit=unreal.SystemLibrary.line_trace_single(world,unreal.Vector(q[0],q[1],10930),unreal.Vector(q[0],q[1],10800),unreal.TraceTypeQuery.TRACE_TYPE_QUERY1,True,[],unreal.DrawDebugTrace.NONE,True)
   if isinstance(hit,tuple) and len(hit)==2 and not isinstance(hit[0],unreal.HitResult):hit=hit[1] if hit[0] else None
   assert hit is not None and hit.to_tuple()[0],'Extension has a physical support hole'
   data=hit.to_tuple();owner=data[9]
   supports.append({'xy':q,'actor':owner.get_actor_label() if owner else None,'z':data[5].z,'pass':owner in [old,foundation] and 10897.9<=data[5].z<=10921.5})
 result['supports']=supports;result['surface_contact_pass']=all(p['pass'] for p in supports)
 result['package']=old.get_package().get_name()
result['trace_calls']=calls
print('S26_STATION_EXTENSION '+json.dumps(result,separators=(',',':')))
'''

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--survey-result',type=Path)
    args=parser.parse_args()
    receipt=None
    if args.survey_result:
        text=args.survey_result.read_text(encoding='utf-8')
        if text.lstrip().startswith('{'):text=json.loads(text).get('output',text)
        rows=[json.loads(s.split('S26_STATION_EXTENSION ',1)[1]) for s in text.splitlines() if s.startswith('S26_STATION_EXTENSION ')]
        assert len(rows)==1 and rows[0]['phase']=='survey'
        receipt=rows[0]
    OUT.mkdir(parents=True,exist_ok=True)
    for phase in (('apply','verify') if receipt else ('survey',)):
        code=EDITOR.replace('__PHASE__',phase).replace('__EXPECTED__',repr(receipt)).replace('__LABEL__',LABEL).replace('__TAG__',TAG)
        ast.parse(code)
        for token in ('try','getattr','import time','open(','save_asset','save_packages','destroy_actor'):assert token not in code,token
        path=OUT/(phase+'.py');path.write_text(code,encoding='utf-8');print(path)

if __name__=='__main__':main()
