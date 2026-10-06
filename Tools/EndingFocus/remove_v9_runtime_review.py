"""Remove the disposable V9 PIE actor and save only its external actor package."""
import unreal

es = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
assert es.get_game_world() is None
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
actors = [item for item in eas.get_all_level_actors() if item.get_actor_label() == 'Codex_CIN19_V9_RuntimeReview']
assert len(actors) == 1
actor = actors[0]
package = actor.get_package()
path = package.get_name()
assert path == '/Game/__ExternalActors__/level/Saskarta_WP/7/1C/Q1UAQQA2UKVS8FIK9YGJ26'
removed = eas.destroy_actor(actor)
assert removed
saved = unreal.EditorLoadingAndSavingUtils.save_packages([package], False)
print('V9_RUNTIME_REVIEW_REMOVED', str(removed), str(saved), path)
