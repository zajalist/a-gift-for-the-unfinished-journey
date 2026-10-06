import unreal

es = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
assert es.get_game_world() is None
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
actors = [item for item in eas.get_all_level_actors() if item.get_actor_label() == 'Codex_CIN19_V9_RuntimeReview']
assert len(actors) == 1
actor = actors[0]
settings = actor.get_editor_property('playback_settings')
settings.set_editor_property('start_time', 27.5)
settings.set_editor_property('play_rate', 0.5)
actor.set_editor_property('playback_settings', settings)
saved = unreal.EditorLoadingAndSavingUtils.save_packages([actor.get_package()], False)
print('V9_RUNTIME_TAIL_SET', str(saved), str(settings.get_editor_property('start_time')), str(settings.get_editor_property('play_rate')))
