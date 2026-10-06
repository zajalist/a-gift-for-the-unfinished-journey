import json
import unreal

es = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
assert es.get_game_world() is None
seq = unreal.LevelSequenceEditorBlueprintLibrary.get_current_level_sequence()
assert seq and seq.get_name() == 'LS_CIN_19_Hatch_SideSupportedReviewV9'
lib = unreal.LevelSequenceEditorBlueprintLibrary
binding = [item for item in seq.get_bindings() if str(item.get_display_name()) == 'Samyor_Hatch'][0]
identifier = unreal.MovieSceneObjectBindingID()
identifier.set_editor_property('guid', binding.get_id())
objects = lib.get_bound_objects(identifier)
assert len(objects) == 1
body = objects[0]
mesh = body.skeletal_mesh_component
frame = unreal.Transform()
frame.set_editor_property('rotation', unreal.Quat(0.068259,-0.012388,-0.907167,0.415013))
frame.set_editor_property('translation', unreal.Vector(616579.291369,463550.827777,-35756.663961))
frame.set_editor_property('scale3d', unreal.Vector(1.,1.,1.))
rows = {}
for bone in ('root','Hips','LeftFoot','RightFoot','staff011','RightHand'):
    local = mesh.get_socket_transform(bone, unreal.RelativeTransformSpace.RTS_WORLD).translation
    position = unreal.MathLibrary.transform_location(frame, local)
    hit = unreal.SystemLibrary.line_trace_single(es.get_editor_world(),
        position + unreal.Vector(0.,0.,200.), position - unreal.Vector(0.,0.,200.),
        unreal.TraceTypeQuery.TRACE_TYPE_QUERY1, True, [], unreal.DrawDebugTrace.NONE, True)
    data = hit.to_tuple() if hit else None
    rows[bone] = {'local': [round(local.x,3),round(local.y,3),round(local.z,3)],
                  'above_ground_cm': round(position.z-data[5].z,3) if data and data[0] else None}
actor = body.get_actor_location()
print('CIN19_V9_POSE_CURRENT ' + json.dumps({
    'frame': lib.get_current_time(),
    'actor': [actor.x,actor.y,actor.z],
    'bones': rows,
}, separators=(',', ':')))
