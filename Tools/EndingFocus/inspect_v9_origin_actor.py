import unreal

eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
actors = [actor for actor in eas.get_all_level_actors() if actor.get_actor_label() == 'Codex_CIN19_V9_OriginPreview']
assert len(actors) == 1
actor = actors[0]
print('V9_ACTOR_CLASS', str(actor.get_class().get_name()))
print('V9_ACTOR_SEQUENCE', str(actor.get_editor_property('level_sequence_asset')))
print('V9_ACTOR_PLAYER', str(actor.get_editor_property('sequence_player')))
print('V9_ACTOR_DATA', str(actor.get_editor_property('default_instance_data')))
print('V9_ACTOR_OVERRIDE', str(actor.get_editor_property('override_instance_data')))
