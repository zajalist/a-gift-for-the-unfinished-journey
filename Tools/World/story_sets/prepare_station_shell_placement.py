"""Prepare a guarded replacement of the old visual hut, preserving its actor.

The door/body/drone/plate/mast waypoints are not edited. Supporting extensions
must already cover the measured footprint before the replacement can run.
"""
from pathlib import Path
import json
import hashlib

ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'Saved/Tripo/20261001/station_shell_placement'
COMMON='''import unreal,json,math
assert unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is None,'PIE must be stopped'
world=unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
actors=unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors()
assert len(actors)<2500,'Bounded S26 region required'
found=[a for a in actors if a.get_actor_label()=='SD_S26_HighVoiceTripo_001']
assert len(found)==1,'Expected exactly one protected visual hut'
actor=found[0];component=actor.static_mesh_component
old_path='/Game/SaskartaGaea/Environment/Tripo02/SM_T2_stone_hut.SM_T2_stone_hut'
new_path='/Game/SaskartaGaea/Environment/Tripo02/SM_T2_s26_radio_station.SM_T2_s26_radio_station'
assert component.static_mesh.get_path_name() in (old_path,new_path),'Unexpected replacement mesh'
mesh=unreal.load_asset(new_path);assert isinstance(mesh,unreal.StaticMesh)
assert mesh.get_editor_property('body_setup').get_editor_property('collision_trace_flag')==unreal.CollisionTraceFlag.CTF_USE_COMPLEX_AS_SIMPLE
target=unreal.Vector(297342.918097,483375.261496,10897.9)
rotation=unreal.Rotator(pitch=0.,yaw=288.66,roll=0.)
scale=unreal.Vector(1.5,1.25,1.3)
def state():
 return dict(actor=actor.get_path_name(),mesh=component.static_mesh.get_path_name(),transform=actor.get_actor_transform().export_text(),
  materials=[m.get_path_name() if m else None for m in component.get_editor_property('override_materials')],
  collision=str(component.get_collision_enabled()),profile=str(component.get_collision_profile_name()),
  hidden=actor.get_editor_property('hidden'),component_hidden=component.get_editor_property('hidden_in_game'))
'''
APPLY='''before=state()
if component.static_mesh.get_path_name()==old_path:
 location=actor.get_actor_location();size=actor.get_actor_scale3d()
 assert abs(location.x-297254)<.05 and abs(location.y-483334)<.05 and abs(location.z-10917.869810)<.05,'Old hut moved since measurement'
 assert max(abs(size.x-.75),abs(size.y-.75),abs(size.z-.75))<.00001
# Confirm support at the larger upright footprint from current collision. The
# old hut has no collision; ignore it explicitly for repeatability after apply.
support=[];yaw=math.radians(288.66)
for x in (-130.,0.,130.):
 for y in (-185.,0.,185.):
  wx=target.x+x*scale.x*math.cos(yaw)-y*scale.y*math.sin(yaw)
  wy=target.y+x*scale.x*math.sin(yaw)+y*scale.y*math.cos(yaw)
  hit=unreal.SystemLibrary.line_trace_single(world,unreal.Vector(wx,wy,11000),unreal.Vector(wx,wy,10700),unreal.TraceTypeQuery.TRACE_TYPE_QUERY1,True,[actor],unreal.DrawDebugTrace.NONE,True)
  if isinstance(hit,tuple) and len(hit)==2 and not isinstance(hit[0],unreal.HitResult):hit=hit[1] if hit[0] else None
  assert hit is not None and hit.to_tuple()[0],'Missing station footing collision'
  data=hit.to_tuple();owner=data[9];z=data[5].z
  assert owner is not None and (owner.get_actor_label()=='SD_S26_HighVoiceTripo_000' or 'S26_UPGRADE_20261001' in [str(t) for t in owner.tags]),'Unrecognized station footing'
  assert 10897.9<=z<=10921.5,'Footing must meet the station base without covering the interior floor'
  support.append(dict(actor=owner.get_actor_label(),z=z))
component.set_static_mesh(mesh)
component.set_editor_property('override_materials',[])
component.set_collision_profile_name('BlockAll')
actor.set_actor_location(target,False,False);actor.set_actor_rotation(rotation,False);actor.set_actor_scale3d(scale)
print('S26_STATION_REPLACED '+json.dumps(dict(before=before,after=state(),support=support,saved=False),separators=(',',':')))
'''


def prepare():
    OUT.mkdir(parents=True,exist_ok=True)
    codes={'00_read_preflight.py':COMMON+"print('S26_STATION_REPLACEMENT_PREFLIGHT '+json.dumps(state(),separators=(',',':')))\n",
           '10_replace_visual_hut.py':COMMON+APPLY}
    manifest=dict(scope='Existing visual hut only; preserve all six actor identities, foundation, cinematic/world waypoints. No save included.',
        prerequisite='Level extension footing collision covering all9samples with S26_UPGRADE_20261001 tag; source-fit738rays and window sightline proved offline',scripts={})
    for name,code in codes.items():
        compile(code,name,'exec');path=OUT/name;path.write_text(code)
        manifest['scripts'][name]=hashlib.sha256(path.read_bytes()).hexdigest()
    (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('STATION_SHELL_REPLACEMENT_READY',OUT)


if __name__=='__main__':prepare()
