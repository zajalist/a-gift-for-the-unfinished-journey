# Second half of Tools/Foliage/capture.py: export the V4_CAPTURE render target
# to Saved/Screenshots/V4/<NAME>.png and destroy the capture actor.
import unreal

NAME = 'capture'

OUT_DIR = unreal.Paths.project_saved_dir() + 'Screenshots/V4'
world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
done = 0
for actor in sub.get_all_level_actors():
    if actor.get_actor_label() == 'V4_CAPTURE':
        rt = actor.capture_component2d.get_editor_property('texture_target')
        if done == 0 and rt is not None:
            unreal.RenderingLibrary.export_render_target(world, rt, OUT_DIR, NAME + '.png')
            done = 1
        sub.destroy_actor(actor)
print('CAPTURE ' + OUT_DIR + '/' + NAME + '.png exported=' + str(done))
