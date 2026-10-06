import unreal

eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
actor = [item for item in eas.get_all_level_actors() if item.get_actor_label() == 'Codex_CIN19_V9_OriginPreview'][0]
player = actor.get_editor_property('sequence_player')
params = unreal.MovieSceneSequencePlaybackParams()
params.set_editor_property('time', 30.)
params.set_editor_property('position_type', unreal.MovieScenePositionType.TIME)
player.set_playback_position(params)
print('V9_WORLD_PLAYER', str(player.get_current_time()), str(player.is_playing()))
near = [item for item in eas.get_all_level_actors() if (item.get_actor_location() - actor.get_actor_location()).length() < 1500.]
for item in near[:24]:
    loc = item.get_actor_location()
    print('V9_WORLD_NEAR', item.get_actor_label(), item.get_class().get_name(), round(loc.x), round(loc.y), round(loc.z))
