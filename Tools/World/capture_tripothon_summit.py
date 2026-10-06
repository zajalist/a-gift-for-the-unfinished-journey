"""Render a temporary, unsaved Summit review image from the saved placements."""
from pathlib import Path
import unreal

OUTPUT = Path(r"D:\UnrealEngine\saskartarad\Saved\Verification\tripothon_summit.png")
SCENE_CENTER = unreal.Vector(297900.0, 481000.0, 12100.0)
CAMERA_LOCATION = unreal.Vector(298500.0, 474500.0, 18600.0)


def main():
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    if world.get_path_name() != "/Game/level/Saskarta_WP.Saskarta_WP":
        raise RuntimeError("Unexpected map for Summit review capture")
    descs = list(unreal.WorldPartitionBlueprintLibrary.get_actor_descs())
    summit_descs = [d for d in descs if str(d.label).startswith("ZY_SUM_")]
    if len(summit_descs) != 51 or len({str(d.label) for d in summit_descs}) != 51:
        raise RuntimeError("Expected exactly 51 unique Summit actor descriptors")
    unreal.WorldPartitionBlueprintLibrary.load_actors([d.guid for d in summit_descs])

    subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    actors = subsystem.get_all_level_actors()
    summit_actors = [a for a in actors if a.get_actor_label().startswith("ZY_SUM_")]
    if len(summit_actors) != 51:
        raise RuntimeError("Summit actor load did not resolve to 51 unique actors")

    rotation = unreal.MathLibrary.find_look_at_rotation(CAMERA_LOCATION, SCENE_CENTER)
    capture = subsystem.spawn_actor_from_class(unreal.SceneCapture2D, CAMERA_LOCATION, rotation, True)
    if capture is None:
        raise RuntimeError("Temporary SceneCapture2D creation failed")
    capture.set_editor_property("is_editor_only_actor", True)
    component = capture.get_component_by_class(unreal.SceneCaptureComponent2D)
    target = unreal.RenderingLibrary.create_render_target2d(
        world, 1280, 720, unreal.TextureRenderTargetFormat.RTF_RGBA8_SRGB)
    component.set_editor_property("texture_target", target)
    component.set_editor_property("capture_source", unreal.SceneCaptureSource.SCS_FINAL_COLOR_LDR)
    component.set_editor_property("capture_every_frame", False)
    component.set_editor_property("capture_on_movement", False)
    component.set_editor_property("always_persist_rendering_state", True)
    component.set_editor_property("fov_angle", 75.0)
    component.capture_scene()
    component.capture_scene()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    unreal.RenderingLibrary.export_render_target(
        world, target, OUTPUT.parent.as_posix(), OUTPUT.name)
    if not subsystem.destroy_actor(capture):
        raise RuntimeError("Temporary review capture actor cleanup failed")
    print("TRIPOTHON_SUMMIT_CAPTURE_EXPORTED", OUTPUT.as_posix())
    print("TRIPOTHON_SUMMIT_CAPTURE_ACTORS", len(summit_actors))
    print("TRIPOTHON_SUMMIT_CAPTURE_SAVED_TO_MAP", False)


main()
