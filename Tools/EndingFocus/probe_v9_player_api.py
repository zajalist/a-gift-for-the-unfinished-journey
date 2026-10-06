import unreal

eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
actor = [item for item in eas.get_all_level_actors() if item.get_actor_label() == 'Codex_CIN19_V9_OriginPreview'][0]
player = actor.get_editor_property('sequence_player')
print('PLAYER_SET_POS_DOC', str(player.set_playback_position.__doc__))
print('PLAYER_PLAY_TO_DOC', str(player.play_to.__doc__))
print('PLAYER_PLAY_DOC', str(player.play.__doc__))
print('PLAYER_GET_POS_DOC', str(player.get_current_time.__doc__))
