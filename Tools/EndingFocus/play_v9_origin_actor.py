import unreal

eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
actor = [item for item in eas.get_all_level_actors() if item.get_actor_label() == 'Codex_CIN19_V9_OriginPreview'][0]
player = actor.get_editor_property('sequence_player')
player.play()
print('V9_WORLD_PLAY', str(player.is_playing()), str(player.get_current_time()))
