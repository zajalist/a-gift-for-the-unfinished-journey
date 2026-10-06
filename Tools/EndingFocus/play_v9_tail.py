import unreal

lib = unreal.LevelSequenceEditorBlueprintLibrary
assert lib.get_current_level_sequence().get_name() == 'LS_CIN_19_Hatch_SideSupportedReviewV9'
lib.set_current_time(900)
lib.play()
print('CIN19_V9_PLAY', lib.get_current_time(), lib.is_playing())
