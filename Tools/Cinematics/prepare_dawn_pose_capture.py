"""Prepare a transient actual-mesh/animation preview using the proven LDR route.

Root operates setup, one pose, two bounded pumps, export, then cleanup. No live
calls from this generator, no persistent body actor, no world or asset save.
"""
from pathlib import Path
import argparse
import hashlib
import json
import math
import sys

import samyor_reveal as rig
import samyor_final as final
import samyor_dawn_turn as turn
import ending_staging as staging
import build_cinematics as cinematic

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'Tools/World'))
import prepare_ground_capture as ground

TAG='Saskarta.DawnPoseVerification'
BODY='DawnPose_VerificationBody'
CAPTURE='DawnPose_VerificationCapture'
HEAD=ground.HEAD
POST=json.loads((Path(__file__).with_name('probe_ending.json')).read_text())['radio_post']
ORIGIN=POST['collapse']

BODY_SETUP=HEAD+f'''
eas=unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
helpers=[a for a in unreal.ObjectIterator(unreal.Actor) if a.get_world()==world and a.get_actor_label() in ({BODY!r},{CAPTURE!r},'GroundContact_VerificationCapture')]
assert not helpers,'Finish/cleanup the previous owned preview before setup'
sk=unreal.load_asset({rig.SK!r});assert isinstance(sk,unreal.SkeletalMesh)
assert sk.get_editor_property('skeleton').get_path_name()=={(rig.SKEL+'.SKEL_Traveller')!r}
assert len(sk.get_editor_property('materials'))==3,'Verified production material layout required'
body=eas.spawn_actor_from_class(unreal.SkeletalMeshActor,unreal.Vector(*{ORIGIN!r}),unreal.Rotator(pitch=0.,yaw=108.66,roll=0.),True)
assert body is not None,'Temporary body spawn failed'
body.set_actor_label({BODY!r});body.set_editor_property('tags',[{TAG!r}])
# The actor is already transient. SceneCapture uses Game show flags, which
# deliberately exclude editor-only actors in FPrimitiveSceneProxy::IsShown.
body.set_editor_property('is_editor_only_actor',False);body.set_actor_hidden_in_game(False)
mesh=body.get_component_by_class(unreal.SkeletalMeshComponent)
mesh.set_skeletal_mesh_asset(sk);mesh.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
mesh.set_simulate_physics(False);mesh.set_update_cloth_in_editor(False)
mesh.set_animation_mode(unreal.AnimationMode.ANIMATION_SINGLE_NODE)
mesh.set_update_animation_in_editor(True)
mesh.set_editor_property('visibility_based_anim_tick_option',unreal.VisibilityBasedAnimTickOption.ALWAYS_TICK_POSE_AND_REFRESH_BONES)
'''

OWNED=HEAD+f'''
eas=unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
def owned(cls,label):
 rows=[a for a in unreal.ObjectIterator(cls) if a.get_world()==world and a.get_actor_label()==label]
 assert len(rows)==1 and {TAG!r} in [str(t) for t in rows[0].tags],'Exactly one owned preview required: '+label
 return rows[0]
body=owned(unreal.SkeletalMeshActor,{BODY!r});cap=owned(unreal.SceneCapture2D,{CAPTURE!r})
mesh=body.get_component_by_class(unreal.SkeletalMeshComponent)
c=cap.get_component_by_class(unreal.SceneCaptureComponent2D)
'''

CLEANUP=HEAD+f'''
eas=unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
objects=[]
for cls,label in [(unreal.SkeletalMeshActor,{BODY!r}),(unreal.SceneCapture2D,{CAPTURE!r})]:
 rows=[a for a in unreal.ObjectIterator(cls) if a.get_world()==world and a.get_actor_label()==label]
 assert len(rows)<=1,'Duplicate preview ownership'
 assert not rows or {TAG!r} in [str(t) for t in rows[0].tags],'Refuse unowned helper'
 objects+=rows
restore=set(str(t).split('GroundCaptureSkyRestore:',1)[1] for a in objects for t in a.tags if str(t).startswith('GroundCaptureSkyRestore:'))
restored=[]
for sky in unreal.ObjectIterator(unreal.SkyLightComponent):
 if sky.get_world()==world and sky.get_path_name() in restore:
  sky.set_real_time_capture(True);restored.append(sky.get_path_name())
assert set(restored)==restore,'Keep ownership tags until every skylight flag is restored'
removed=[]
for actor in objects:
 label=actor.get_actor_label()
 if isinstance(actor,unreal.SkeletalMeshActor):
  mesh=actor.get_component_by_class(unreal.SkeletalMeshComponent)
  mesh.set_update_animation_in_editor(False);mesh.stop()
 else:
  c=actor.get_component_by_class(unreal.SceneCaptureComponent2D)
  rt=c.get_editor_property('texture_target');c.set_editor_property('texture_target',None)
  if rt is not None:unreal.RenderingLibrary.release_render_target2d(rt)
 assert eas.destroy_actor(actor),'Owned preview cleanup failed: '+label
 removed.append(label)
print('DAWN_POSE_CLEANUP '+json.dumps(dict(removed=removed,restored_skylights=restored,saved=False),separators=(',',':')))
'''


def cases():
    yaw=staging.SUN_BEARING-90
    rows=[dict(name='arrival',clip='A_Samyor_DawnTurn',at=0.,pose=turn.pose_at(0.),yaw=staging.arrival_yaw(POST),
               camera_offset=(180,290,155),focus=(0,0,80),fov=55.),
          dict(name='standing',clip='A_Samyor_FinalCollapse',at=0.,pose=final.pose_at(0.),yaw=yaw,
               camera_offset=(180,290,155),focus=(0,0,80),fov=55.),
          dict(name='final',clip='A_Samyor_FinalStill',at=0.,pose=final.pose_at(final.COLLAPSE_S),yaw=yaw,
               camera_offset=(150,210,85),focus=(15,10,25),fov=55.),
          dict(name='standing_back',clip='A_Samyor_FinalCollapse',at=0.,pose=final.pose_at(0.),yaw=yaw,
               camera_offset=(0,-340,145),focus=(0,0,85),fov=55.)]
    camera=cinematic.plan_cin24()['cams'][0]
    key=camera['keys'][-1]
    rows.append(dict(name='final_authored_camera',clip='A_Samyor_FinalStill',at=0.,pose=final.pose_at(final.COLLAPSE_S),yaw=yaw,
                     camera_world=list(key[1:4]),camera_rotation=list(key[4:7]),
                     fov=math.degrees(2*math.atan(cinematic.FILMBACK_W/(2*camera['focal'])))))
    return rows


def check_pose(row):
    world=rig.fk(row['pose'])
    expected={bone:list(world[bone][0]) for bone in ('root','Hips','Head','LeftFoot','RightFoot','staff011')}
    return f'''
assert not mesh.is_playing() and abs(mesh.get_position()-{row['at']!r})<.0001,'Preview animation advanced'
errors=[]
for bone,expected in {expected!r}.items():
 p=mesh.get_socket_transform(bone,unreal.RelativeTransformSpace.RTS_COMPONENT).get_editor_property('translation')
 error=sum((a-b)**2 for a,b in zip((p.x,p.y,p.z),expected))**.5
 errors.append(dict(bone=bone,error_cm=error))
assert max(r['error_cm'] for r in errors)<.25,('Wait for an editor tick; actual preview pose not yet evaluated',errors)
'''


def prepare(out):
    assert not out.exists(),'Preserve previous capture packets; choose a new revision'
    out.mkdir(parents=True)
    images=out/'images';images.mkdir()
    first=cases()[0];spin=rig.qaxis((0,0,1),first['yaw'])
    eye=rig.vadd(ORIGIN,rig.qrot(spin,first['camera_offset']))
    focus=rig.vadd(ORIGIN,rig.qrot(spin,first['focus']))
    frame=f'location=unreal.Vector(*{list(eye)!r})\nrotation=unreal.MathLibrary.find_look_at_rotation(location,unreal.Vector(*{list(focus)!r}))\n'
    capture=ground.SETUP[len(HEAD):].replace('__FRAME__',frame).replace('__LABEL__',CAPTURE).replace('__TAG__',TAG).replace('__FOV__','55.0')
    # First capture happens only after a selected animation has evaluated.
    capture=capture.replace('c.capture_scene()\n','')
    capture += "\nbody.set_editor_property('tags',restore_tags)\nprint('DAWN_POSE_SETUP_READY body '+body.get_path_name())\n"
    codes={'00_setup.py':BODY_SETUP+capture,'99_cleanup.py':CLEANUP}
    manifest=dict(status='prepared_not_run',scope='Temporary actual repaired Traveller and one1280x720 LDR SceneCapture; no save or native gameplay',
                  prerequisites=['Dawn v2 clips installed/read back','Production Traveller weights verified/saved','PIE stopped','Previous ground capture cleaned up'],
                  order='00_setup; for each chosen case: pose, allow editor ticks, pump twice in separate calls, export;99_cleanup even after failure',cases=[],scripts={})
    for i,row in enumerate(cases(),1):
        prefix=f'{i}0_{row["name"]}'
        code=OWNED+f'''
clip=unreal.load_asset({(rig.ANIM_DIR+'/'+row['clip'])!r});assert isinstance(clip,unreal.AnimSequence)
assert abs(clip.get_editor_property('rate_scale')-1.)<.0001
body.set_actor_location(unreal.Vector(*{ORIGIN!r}),False,False)
body.set_actor_rotation(unreal.Rotator(pitch=0.,yaw={row['yaw']!r},roll=0.),False)
mesh.set_animation(clip);mesh.set_play_rate(0.);mesh.stop();mesh.set_position({row['at']!r},False)
# UE5.8 OverrideAnimationData explicitly ticks at zero delta and refreshes bones.
# SetPosition alone changes the clock without evaluating an editor preview pose.
mesh.override_animation_data(clip,False,False,{row['at']!r},0.)
mesh.set_update_animation_in_editor(False)
'''
        if 'camera_world' in row:
            roll,pitch,yaw=row['camera_rotation']
            code+=f'location=unreal.Vector(*{row["camera_world"]!r})\nrotation=unreal.Rotator(pitch={pitch!r},yaw={yaw!r},roll={roll!r})\n'
        else:
            spin=rig.qaxis((0,0,1),row['yaw'])
            eye=rig.vadd(ORIGIN,rig.qrot(spin,row['camera_offset']));focus=rig.vadd(ORIGIN,rig.qrot(spin,row['focus']))
            code+=f'location=unreal.Vector(*{list(eye)!r})\nrotation=unreal.MathLibrary.find_look_at_rotation(location,unreal.Vector(*{list(focus)!r}))\n'
        code+=f'''cap.set_actor_location(location,False,False);cap.set_actor_rotation(rotation,False)
c.set_editor_property('fov_angle',{row['fov']!r})
print('DAWN_POSE_SELECTED '+json.dumps(dict(case={row['name']!r},clip=clip.get_path_name(),at={row['at']!r},body_transform=body.get_actor_transform().export_text(),camera_transform=cap.get_actor_transform().export_text(),saved=False),separators=(',',':')))
'''
        codes[prefix+'_pose.py']=code
        check=check_pose(row)
        codes[prefix+'_pump.py']=OWNED+check+f"c.capture_scene()\nprint('DAWN_POSE_CAPTURE_PUMP {row['name']} '+json.dumps(errors))\n"
        codes[prefix+'_export.py']=OWNED+check+f"unreal.RenderingLibrary.export_render_target(world,c.get_editor_property('texture_target'),{images.as_posix()!r},{(row['name']+'.png')!r})\nprint('DAWN_POSE_EXPORTED {images.as_posix()}/{row['name']}.png')\n"
        manifest['cases'].append({k:v for k,v in row.items() if k!='pose'})
    for name,code in codes.items():
        ground.checked(code)
        path=out/name;path.write_text(code,encoding='utf-8')
        manifest['scripts'][name]=hashlib.sha256(path.read_bytes()).hexdigest()
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(dict(packet=str(out),scripts=len(codes),cases=[r['name'] for r in manifest['cases']]),indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('out',type=Path)
    prepare(p.parse_args().out.resolve())
