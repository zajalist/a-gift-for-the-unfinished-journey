import unreal

es = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
assert es.get_game_world() is None
assert unreal.LevelSequenceEditorBlueprintLibrary.get_current_level_sequence().get_name() == 'LS_CIN_19_Hatch_SideSupportedReviewV9'
unreal.LevelSequenceEditorBlueprintLibrary.set_lock_camera_cut_to_viewport(False)
es.set_level_viewport_camera_info(unreal.Vector(-650., -330., 125.),
                                  unreal.Rotator(roll=0., pitch=-6., yaw=31.9))
print('CIN19_V9_FRAMED', str(es.get_level_viewport_camera_info()))
