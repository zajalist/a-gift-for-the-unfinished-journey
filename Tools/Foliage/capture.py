# One still from a SceneCapture2D, exported as PNG (Task V4 verification).
# Sent through Tools/Foliage/run_foliage.mjs py, which rewrites the CAM, LOOK,
# NAME and SIZE lines. Writes Saved/Screenshots/V4/<NAME>.png. The capture actor
# is transient-labelled V4_CAPTURE and is destroyed before the call returns.
# Used instead of the editor viewport, which returns black while the editor
# window is not being drawn.
import unreal

CAM = [0.0, 0.0, 0.0]
LOOK = [100.0, 0.0, 0.0]
NAME = 'capture'
SIZE = [1280, 720]
FOV = 60.0
SOURCE = 'SCS_FINAL_COLOR_LDR'

SOURCES = {'SCS_FINAL_COLOR_LDR': unreal.SceneCaptureSource.SCS_FINAL_COLOR_LDR,
           'SCS_BASE_COLOR': unreal.SceneCaptureSource.SCS_BASE_COLOR,
           'SCS_WORLD_NORMAL': unreal.SceneCaptureSource.SCS_NORMAL}
OUT_DIR = unreal.Paths.project_saved_dir() + 'Screenshots/V4'
world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
cam = unreal.Vector(CAM[0], CAM[1], CAM[2])
rot = unreal.MathLibrary.find_look_at_rotation(cam, unreal.Vector(LOOK[0], LOOK[1], LOOK[2]))
actor = sub.spawn_actor_from_class(unreal.SceneCapture2D, cam, rot)
actor.set_actor_label('V4_CAPTURE')
comp = actor.capture_component2d
rt = unreal.RenderingLibrary.create_render_target2d(world, SIZE[0], SIZE[1], unreal.TextureRenderTargetFormat.RTF_RGBA8)
comp.set_editor_property('texture_target', rt)
comp.set_editor_property('capture_source', SOURCES[SOURCE])
comp.set_editor_property('capture_every_frame', False)
comp.set_editor_property('capture_on_movement', False)
comp.set_editor_property('fov_angle', FOV)
# The level's unbound PPV_Saskarta_Mood carries the game-flow post-process
# blendables (carrier vision), which paint the frame black outside a play
# session; the capture turns post-process materials off.
flag = unreal.EngineShowFlagsSetting()
flag.set_editor_property('show_flag_name', 'PostProcessMaterial')
flag.set_editor_property('enabled', False)
comp.set_editor_property('show_flag_settings', [flag])
comp.capture_scene()
print('CAPTURE queued ' + NAME + ' (run capture_export.py next)')
