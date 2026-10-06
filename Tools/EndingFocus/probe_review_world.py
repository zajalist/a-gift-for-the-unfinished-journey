import json
import unreal

es = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
world = es.get_editor_world()
actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors()
camera = es.get_level_viewport_camera_info()
labels = [actor.get_actor_label() for actor in actors]
print('ENDING_REVIEW_WORLD ' + json.dumps({
    'world': world.get_name() if world else None,
    'pie': es.get_game_world() is not None,
    'loaded_actors': len(actors),
    'preview_actors': [label for label in labels if label.startswith('Codex_Staff')],
    'shell_loaded': 'SD_S26_HighVoiceTripo_001' in labels,
    'camera': str(camera),
}, separators=(',', ':')))
