import unreal

sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
body = [actor for actor in sub.get_all_level_actors() if actor.get_actor_label() == 'Codex_StaffBody_ReviewV3'][0]
mesh = body.skeletal_mesh_component
print('PREVIEW_ANIMATION', str(mesh.get_editor_property('animation_mode')),
      str(mesh.get_editor_property('animation_data')))
print('PREVIEW_METHODS', ','.join(name for name in dir(mesh)
      if any(term in name.lower() for term in ('animation', 'position', 'tick', 'bone', 'pose', 'refresh'))))
