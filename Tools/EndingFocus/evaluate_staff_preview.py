import unreal

sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
body = [actor for actor in sub.get_all_level_actors()
        if actor.get_actor_label() == 'Codex_StaffBody_ReviewV3'][0]
mesh = body.skeletal_mesh_component
mesh.set_update_animation_in_editor(True)
mesh.set_position(.5, False)
print('STAFF_PREVIEW_EVALUATE',
      str(mesh.get_socket_transform('staff011', unreal.RelativeTransformSpace.RTS_WORLD)),
      str(mesh.get_socket_transform('RightHand', unreal.RelativeTransformSpace.RTS_WORLD)))
