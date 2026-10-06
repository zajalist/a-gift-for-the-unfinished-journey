import unreal

es = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
assert es.get_game_world() is None, 'Stop PIE'
seq = unreal.load_asset('/Game/SaskartaGaea/GameFlow/Cinematics/LS_CIN_19_Hatch_SideSupportedReviewV9')
assert seq
lib = unreal.LevelSequenceEditorBlueprintLibrary
assert lib.open_level_sequence(seq)
lib.set_current_time(900)
print('CIN19_V9_OPEN', str(lib.get_current_level_sequence()), str(lib.get_current_time()))
