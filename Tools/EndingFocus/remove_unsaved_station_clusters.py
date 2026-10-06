import unreal

es = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
assert es.get_game_world() is None
sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
owned = [actor for actor in sub.get_all_level_actors()
         if actor.get_actor_label().startswith('SD_S26_EndFocus_')]
assert len(owned) == 4
for actor in owned:
    assert 'S26_ENDING_FOCUS_20261001' in [str(tag) for tag in actor.tags]
for actor in owned:
    assert sub.destroy_actor(actor)
print('ENDING_STATION_UNSAVED_REMOVED', len(owned))
