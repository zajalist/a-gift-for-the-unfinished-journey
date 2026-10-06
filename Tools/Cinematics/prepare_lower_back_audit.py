"""Bounded read-only poses covering the actual Traveller locomotion inputs.

No editor connection. Each output prints at most one complete pose. Existing
animation/install generators remain untouched while the root install is active.
"""
from pathlib import Path
import hashlib
import json

import prepare_hatch_visual_probe as original
import traveller_contacts as contacts

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'Saved/Verification/lower_back_audit_20261001'

LIVE='''import unreal,json
world=unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
assert world is not None,'PIE required for the actual possessed Traveller pose'
pc=unreal.GameplayStatics.get_player_controller(world,0)
actor=pc.get_pawn()
assert actor is not None
components=[c for c in actor.get_components_by_class(unreal.SkeletalMeshComponent)
            if c.get_skeletal_mesh_asset() is not None and c.get_skeletal_mesh_asset().get_name()=='SK_Traveller']
assert len(components)==1,'Possessed Traveller required'
comp=components[0]
def xf(t):
    p,q,s=t.translation,t.rotation,t.scale3d
    return [round(v,4) for v in (p.x,p.y,p.z,q.x,q.y,q.z,q.w,s.x,s.y,s.z)]
bones={}
for name in __BONES__:
    assert comp.get_bone_index(name)>=0,name
    bones[name]=dict(component=xf(comp.get_socket_transform(name,unreal.RelativeTransformSpace.RTS_COMPONENT)),hidden=comp.is_bone_hidden_by_name(name))
camera=unreal.GameplayStatics.get_player_camera_manager(world,0)
p=camera.get_camera_location()
q=camera.get_camera_rotation()
print('TRAVELLER_ACTUAL_SKIN_POSE '+json.dumps(dict(actor=actor.get_path_name(),mesh=comp.get_skeletal_mesh_asset().get_path_name(),component_world=xf(comp.get_world_transform()),
 animation_mode=str(comp.get_editor_property('animation_mode')),anim_mode=str(actor.get_editor_property('AnimMode')),
 hidden=comp.get_editor_property('hidden_in_game'),owner_no_see=comp.get_editor_property('owner_no_see'),only_owner_see=comp.get_editor_property('only_owner_see'),
 sections=[comp.is_material_section_shown(i,0) for i in range(comp.get_num_materials())],materials=[comp.get_material(i).get_path_name() if comp.get_material(i) else None for i in range(comp.get_num_materials())],
 camera=[p.x,p.y,p.z,q.roll,q.pitch,q.yaw],bones=bones),separators=(',',':')))
'''


def prepare():
    OUT.mkdir(parents=True,exist_ok=True)
    pre=original.IDLE_PROBE.split('trav =')[0]
    for index,(name,fraction) in enumerate((('A_Traveller_Rest',0),('A_Traveller_Rest',.5),
                                           ('A_Traveller_SlowWalk',.25),('A_Traveller_SlowWalk',.5),
                                           ('A_Traveller_SlowWalk',.75))):
        code=pre+f'''clip=unreal.load_asset(folder+'Traveller/Anims/{name}')
assert clip is not None
at=clip.get_play_length()*{fraction}
pose=unreal.AnimPoseExtensions.get_anim_pose_at_time(clip,at,unreal.AnimPoseEvaluationOptions())
print('TRAVELLER_POSE '+json.dumps(dict(clip={name!r},at=at,length=clip.get_play_length(),bones=pose_rows(pose)),separators=(',',':')))
'''
        compile(code,name,'exec')
        (OUT/f'0{index}_idle_pose.py').write_text(code)
    _,entries,_=contacts.source_body()
    live=LIVE.replace('__BONES__',repr([bone for bone,_,_,_ in entries]))
    compile(live,'live','exec')
    (OUT/'10_live_player_pose.py').write_text(live)
    manifest=dict(scope='Read-only metadata/pose evidence; no material, mesh or animation mutation',
                  source_body='SourceArt/Characters/Traveller/traveller01_animated.fbx',
                  scripts={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in OUT.glob('*.py')})
    (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('LOWER_BACK_PROBES_READY',len(manifest['scripts']),OUT)


if __name__=='__main__':prepare()
