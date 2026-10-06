import unreal

lib = unreal.LevelSequenceEditorBlueprintLibrary
assert lib.get_current_level_sequence().get_name() == 'LS_CIN_19_Hatch_SideSupportedReviewV9'
lib.pause()
lib.set_current_time(1032)
lib.force_update()
print('CIN19_V9_TIME_REQUESTED', lib.get_current_time())
