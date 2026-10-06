import json
import unreal

es = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
world = es.get_game_world()
assert world, 'PIE world not ready'
actors = unreal.GameplayStatics.get_all_actors_of_class(world, unreal.SkeletalMeshActor)
found = [actor for actor in actors if actor.get_actor_label() == 'Codex_StaffBody_ReviewV3']
assert len(found) == 1, 'Review body missing in PIE'
body = found[0]
mesh = body.skeletal_mesh_component
staff = [actor for actor in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.StaticMeshActor)
         if actor.get_actor_label() == 'Codex_StaffMesh_ReviewV3']
assert len(staff) == 1, 'Review staff missing in PIE'
print('STAFF_PIE ' + json.dumps({
    'body': body.get_path_name(),
    'animation': str(mesh.get_editor_property('animation_data')),
    'staff_socket': str(mesh.get_socket_transform('staff011', unreal.RelativeTransformSpace.RTS_WORLD)),
    'right_hand': str(mesh.get_socket_transform('RightHand', unreal.RelativeTransformSpace.RTS_WORLD)),
    'right_foot': str(mesh.get_socket_transform('RightFoot', unreal.RelativeTransformSpace.RTS_WORLD)),
    'staff_bounds': str(staff[0].get_actor_bounds(False)),
    'body_bounds': str(body.get_actor_bounds(False)),
}, separators=(',', ':')))
