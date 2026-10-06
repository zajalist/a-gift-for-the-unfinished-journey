"""Prepare bounded read-only collision checks for the installed S26 station.

Run the small scripts separately through the sole editor writer. Actual rendered
window/light/body appearance is a separate acceptance step.
"""
from pathlib import Path
import argparse
import hashlib
import json
import math
import sys

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'Tools/Cinematics'))
import samyor_notice as notice
import samyor_reveal as rig
import traveller_gaze as gaze

POST=json.loads((ROOT/'Tools/Cinematics/probe_ending.json').read_text())['radio_post']
COMMON='''import unreal,json,math,datetime
editor=unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
assert editor.get_game_world() is None,'PIE must be stopped'
world=editor.get_editor_world();assert world.get_name()=='Saskarta_WP'
actors=list(unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors())
assert len(actors)<2500,'Bounded S26 region required'
matches=[a for a in actors if a.get_actor_label()=='SD_S26_HighVoiceTripo_001']
assert len(matches)==1,'Exact protected station actor required'
station=matches[0];component=station.static_mesh_component
assert component.static_mesh.get_path_name()=='/Game/SaskartaGaea/Environment/Tripo02/SM_T2_s26_radio_station.SM_T2_s26_radio_station'
position=station.get_actor_location();scale=station.get_actor_scale3d();rotation=station.get_actor_rotation()
assert max(abs(a-b) for a,b in zip((position.x,position.y,position.z),(297342.918097,483375.261496,10897.9)))<.001
assert max(abs(a-b) for a,b in zip((scale.x,scale.y,scale.z),(1.5,1.25,1.3)))<.00001
assert abs(rotation.pitch)<.001 and abs(rotation.roll)<.001 and abs((rotation.yaw-288.66+180)%360-180)<.001
assert str(component.get_collision_profile_name())=='BlockAll'
assert component.static_mesh.get_editor_property('body_setup').get_editor_property('collision_trace_flag')==unreal.CollisionTraceFlag.CTF_USE_COMPLEX_AS_SIMPLE
cls=unreal.load_object(None,'/Game/SaskartaGaea/Characters/Traveller/BP_Saskarta_Traveller.BP_Saskarta_Traveller_C')
capsule=unreal.get_default_object(cls).get_component_by_class(unreal.CapsuleComponent)
radius=capsule.get_scaled_capsule_radius();half=capsule.get_scaled_capsule_half_height()
assert abs(radius-32)<.001 and abs(half-88)<.001,'Traveller dimensions changed'
started=datetime.datetime.now(datetime.timezone.utc);calls=0
def budget():
 global calls
 calls+=1
 assert calls<=32 and (datetime.datetime.now(datetime.timezone.utc)-started).total_seconds()<3.5,'Bounded station probe exceeded'
def unpack(hit):
 if isinstance(hit,tuple) and len(hit)==2 and not isinstance(hit[0],unreal.HitResult):return hit[1] if hit[0] else None
 return hit
def describe(hit):
 hit=unpack(hit)
 if hit is None or not hit.to_tuple()[0]:return dict(blocked=False)
 h=hit.to_tuple();actor=h[9]
 return dict(blocked=True,actor=actor.get_path_name() if actor else None,label=actor.get_actor_label() if actor else None,
             point=[h[5].x,h[5].y,h[5].z],normal=[h[7].x,h[7].y,h[7].z],initial_overlap=bool(h[1]))
def line(a,b,ignored):
 budget()
 return describe(unreal.SystemLibrary.line_trace_single(world,unreal.Vector(*a),unreal.Vector(*b),unreal.TraceTypeQuery.TRACE_TYPE_QUERY1,True,ignored,unreal.DrawDebugTrace.NONE,True))
shell_only=[a for a in actors if a!=station]
# Idle placed character actors are not static obstacles to their own route.
ignore_characters=[a for a in actors if isinstance(a,unreal.Character)]
'''


def capsule_script(route):
    segments=[]
    for a_name,b_name in zip(route,route[1:]):
        a,b=POST[a_name],POST[b_name]
        for i in range(4):
            start=[float(a[k]+(b[k]-a[k])*i/4) for k in range(3)]
            end=[float(a[k]+(b[k]-a[k])*(i+1)/4) for k in range(3)]
            segments.append(dict(start=start,end=end,part=a_name+'->'+b_name,index=i))
    return COMMON+f'''rows=[]
for source in {segments!r}:
 a=source['start'];b=source['end']
 start=unreal.Vector(a[0],a[1],a[2]+half);end=unreal.Vector(b[0],b[1],b[2]+half)
 result=dict(source)
 for name,ignored in [('shell',shell_only),('loaded_world',ignore_characters)]:
  budget()
  result[name]=describe(unreal.SystemLibrary.capsule_trace_single_by_profile(world,start,end,radius,half,'Pawn',False,ignored,unreal.DrawDebugTrace.NONE,True))
 rows.append(result)
print('S26_STATION_CAPSULE '+json.dumps(dict(route={route!r},radius_cm=radius,half_height_cm=half,rows=rows,calls=calls,shell_clear=not any(r['shell']['blocked'] for r in rows),loaded_world_clear=not any(r['loaded_world']['blocked'] for r in rows),saved=False),separators=(',',':')))
'''


def prepare(out):
    assert not out.exists(),'Preserve historical packets; choose a new revision'
    out.mkdir(parents=True)
    floor_points=[dict(anchor=name,point=POST[name]) for name in ('entry_start','door','inside','exit_mid','collapse')]
    floor=COMMON+f'''rows=[]
for source in {floor_points!r}:
 p=source['point']
 hit=line([p[0],p[1],p[2]+40],[p[0],p[1],p[2]-100],ignore_characters)
 rows.append(dict(source,hit=hit,body_anchor_clearance_cm=p[2]-hit['point'][2] if hit['blocked'] else None))
print('S26_STATION_CURRENT_FLOOR '+json.dumps(dict(transform=station.get_actor_transform().export_text(),collision=str(component.get_collision_enabled()),rows=rows,calls=calls,saved=False),separators=(',',':')))
'''
    eye_rows=[]
    spin=rig.qaxis((0,0,1),notice.BODY_YAW)
    for seconds in (2.5,4.5,19.8):
        posed=rig.fk(notice.pose_at(seconds))
        eye=rig.vadd(posed['Head'][0],rig.qrot(posed['Head'][1],gaze.EYE_LOCAL))
        eye=rig.vadd(POST['inside'],rig.qrot(spin,eye))
        direction=rig.qrot(spin,rig.qrot(posed['Head'][1],gaze.HEAD_FORWARD))
        eye_rows.append(dict(sequence_seconds=seconds+59.5,start=list(eye),end=list(rig.vadd(eye,rig.vmul(direction,600)))))
    camera_rows=[dict(target=target,start=POST['drone_rest'],end=[POST[target][0],POST[target][1],POST[target][2]+height])
                 for target,height in (('door',130),('exit_mid',90),('collapse',72))]
    view=COMMON+f'''eyes=[];camera=[]
for source in {eye_rows!r}:
 eyes.append(dict(source,shell=line(source['start'],source['end'],shell_only),loaded_world=line(source['start'],source['end'],ignore_characters)))
for source in {camera_rows!r}:
 camera.append(dict(source,shell=line(source['start'],source['end'],shell_only),loaded_world=line(source['start'],source['end'],ignore_characters)))
print('S26_STATION_WINDOW_CAMERA '+json.dumps(dict(eyes=eyes,camera=camera,calls=calls,limits='Authored pose eye rays against actual installed collision; not a rendered/whole-horizon or imported-animation acceptance.',saved=False),separators=(',',':')))
'''
    codes={'00_current_floor.py':floor,'10_entry_capsule.py':capsule_script(['entry_start','door','inside']),
           '11_exit_capsule.py':capsule_script(['inside','door','exit_mid','collapse']),'20_window_camera.py':view}
    manifest=dict(status='prepared_not_run',scope='Read-only installed station collision; no actor changes or saves',scripts={})
    for name,code in codes.items():
        compile(code,name,'exec');path=out/name;path.write_text(code,encoding='utf-8')
        manifest['scripts'][name]=hashlib.sha256(path.read_bytes()).hexdigest()
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(dict(directory=str(out),scripts=list(codes)),indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('out',type=Path)
    prepare(p.parse_args().out.resolve())
