import unreal

seq = unreal.LevelSequenceEditorBlueprintLibrary.get_current_level_sequence()
assert seq
binding = [item for item in seq.get_bindings() if str(item.get_display_name()) == 'Samyor_Hatch'][0]
identifier = unreal.MovieSceneObjectBindingID()
identifier.set_editor_property('guid', binding.get_id())
objects = unreal.LevelSequenceEditorBlueprintLibrary.get_bound_objects(identifier)
assert len(objects) == 1
body = objects[0]
mesh = body.skeletal_mesh_component
print('BINDING', str(body.get_actor_transform()), str(body.get_actor_bounds(False)),
      str(mesh.get_socket_transform('staff011', unreal.RelativeTransformSpace.RTS_WORLD)),
      str(mesh.get_socket_transform('RightHand', unreal.RelativeTransformSpace.RTS_WORLD)),
      str(mesh.get_socket_transform('RightFoot', unreal.RelativeTransformSpace.RTS_WORLD)))
