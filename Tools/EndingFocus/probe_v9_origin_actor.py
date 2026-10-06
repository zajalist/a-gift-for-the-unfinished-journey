import unreal

es = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
assert es.get_game_world() is None
lib = unreal.LevelSequenceEditorBlueprintLibrary
assert lib.get_current_level_sequence().get_name() == 'LS_CIN_19_Hatch_SideSupportedReviewV9'
lib.close_level_sequence()
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
actor = eas.spawn_actor_from_class(unreal.LevelSequenceActor, unreal.Vector(616579.291369, 463550.827777, -35756.663961))
actor.set_actor_label('Codex_CIN19_V9_OriginPreview')
sequence = unreal.load_asset('/Game/SaskartaGaea/GameFlow/Cinematics/LS_CIN_19_Hatch_SideSupportedReviewV9')
actor.set_sequence(sequence)
data = unreal.new_object(unreal.DefaultLevelSequenceInstanceData, outer=actor)
frame = unreal.Transform()
frame.set_editor_property('rotation', unreal.Quat(0.068259, -0.012388, -0.907167, 0.415013))
frame.set_editor_property('translation', unreal.Vector(616579.291369, 463550.827777, -35756.663961))
frame.set_editor_property('scale3d', unreal.Vector(1., 1., 1.))
data.set_editor_property('transform_origin', frame)
actor.set_editor_property('default_instance_data', data)
actor.set_editor_property('override_instance_data', True)
player = actor.get_sequence_player()
print('V9_ORIGIN_PREVIEW', actor.get_path_name(), str(player), str(actor.get_editor_property('override_instance_data')))
