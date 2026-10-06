import unreal

es = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
assert es.get_game_world() is None
unreal.LevelSequenceEditorBlueprintLibrary.close_level_sequence()
sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
owned = [actor for actor in sub.get_all_level_actors()
         if actor.get_actor_label() in ('Codex_StaffBody_ReviewV3', 'Codex_StaffMesh_ReviewV3')]
assert len(owned) == 2, 'Unexpected review actor inventory; inspect before cleanup'
for actor in owned:
    assert sub.destroy_actor(actor)
sub.set_selected_level_actors([])
print('ENDING_REVIEW_CLEAN', len(owned), 'preview actors destroyed; no world save')
