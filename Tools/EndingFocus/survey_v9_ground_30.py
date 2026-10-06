import json
import unreal

es = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
assert es.get_game_world() is None and es.get_editor_world().get_name() == 'Saskarta_WP'
world = es.get_editor_world()
seq = unreal.load_asset('/Game/SaskartaGaea/GameFlow/Cinematics/LS_CIN_19_Hatch_SideSupportedReviewV9')
assert seq
lib = unreal.LevelSequenceEditorBlueprintLibrary
assert lib.open_level_sequence(seq)
lib.set_current_time(900)
binding = [item for item in seq.get_bindings() if str(item.get_display_name()) == 'Samyor_Hatch'][0]
identifier = unreal.MovieSceneObjectBindingID()
identifier.set_editor_property('guid', binding.get_id())
objects = lib.get_bound_objects(identifier)
assert len(objects) == 1
mesh = objects[0].skeletal_mesh_component
frame = unreal.Transform()
frame.set_editor_property('rotation', unreal.Quat(0.068259,-0.012388,-0.907167,0.415013))
frame.set_editor_property('translation', unreal.Vector(616579.291369,463550.827777,-35756.663961))
frame.set_editor_property('scale3d', unreal.Vector(1.,1.,1.))
rows = []
for bone in ['LeftFoot','RightFoot','staff011','RightHand']:
    local = mesh.get_socket_transform(bone, unreal.RelativeTransformSpace.RTS_WORLD).translation
    position = unreal.MathLibrary.transform_location(frame, local)
    hit = unreal.SystemLibrary.line_trace_single(world,
        position + unreal.Vector(0.,0.,200.), position - unreal.Vector(0.,0.,200.),
        unreal.TraceTypeQuery.TRACE_TYPE_QUERY1, True, [], unreal.DrawDebugTrace.NONE, True)
    data = hit.to_tuple() if hit else None
    rows.append({'bone': bone, 'local': [local.x,local.y,local.z],
                 'world': [position.x,position.y,position.z],
                 'ground_z': data[5].z if data and data[0] else None,
                 'height_over_ground': position.z-data[5].z if data and data[0] else None,
                 'ground_actor': data[9].get_actor_label() if data and data[0] and data[9] else None})
print('CIN19_V9_GROUND30 ' + json.dumps(rows, separators=(',', ':')))
