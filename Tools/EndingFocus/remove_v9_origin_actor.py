import unreal

eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
actors = [item for item in eas.get_all_level_actors() if item.get_actor_label() == 'Codex_CIN19_V9_OriginPreview']
assert len(actors) == 1
player = actors[0].get_editor_property('sequence_player')
player.stop()
print('V9_REVIEW_ACTOR_REMOVED', str(eas.destroy_actor(actors[0])))
