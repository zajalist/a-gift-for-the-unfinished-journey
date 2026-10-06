import json
import unreal

sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
found = {actor.get_actor_label(): actor for actor in sub.get_all_level_actors()
         if actor.get_actor_label() in ('Codex_StaffBody_ReviewV3', 'Codex_StaffMesh_ReviewV3')}
body = found['Codex_StaffBody_ReviewV3']
staff = found['Codex_StaffMesh_ReviewV3']
mesh = body.skeletal_mesh_component
root = staff.root_component
result = {
    'body': str(body.get_actor_transform()),
    'body_bounds': str(body.get_actor_bounds(False)),
    'mesh_location': str(mesh.get_world_location()),
    'staff': str(staff.get_actor_transform()),
    'staff_bounds': str(staff.get_actor_bounds(False)),
    'attach_socket': str(root.get_attach_socket_name()),
    'attach_parent': str(root.get_attach_parent().get_path_name()),
    'relative_location': str(root.get_editor_property('relative_location')),
    'relative_rotation': str(root.get_editor_property('relative_rotation')),
    'relative_scale3d': str(root.get_editor_property('relative_scale3d')),
}
for bone in ['staff011', 'RightHand', 'RightForeArm', 'RightFoot', 'Hips']:
    result[bone] = str(mesh.get_socket_transform(bone, unreal.RelativeTransformSpace.RTS_WORLD))
print('STAFF_TRANSFORMS ' + json.dumps(result, separators=(',', ':')))
