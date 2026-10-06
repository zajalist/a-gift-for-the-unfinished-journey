import unreal

lib = unreal.LevelSequenceEditorBlueprintLibrary
assert lib.get_current_level_sequence().get_name() == 'LS_CIN_19_Hatch_SideSupportedReviewV9'
lib.set_lock_camera_cut_to_viewport(True)
lib.set_current_time(900)
print('CIN19_V9_CAMERA_LOCK', lib.is_camera_cut_locked_to_viewport(), lib.get_current_time())
