import unreal

sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
sub.set_selected_level_actors([])
print('ENDING_REVIEW_SELECTION_CLEARED')
