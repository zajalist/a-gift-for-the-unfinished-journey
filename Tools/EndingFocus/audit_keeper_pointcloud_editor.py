"""Read-only editor audit for the existing loading Traveller capture.

Run through the guarded Hayba editor lease after filming, with PIE stopped.
This does not turn on the capture, move actors, or save assets.
"""
import json
import unreal

es = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
assert es.get_game_world() is None
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
actors = {actor.get_actor_label(): actor for actor in eas.get_all_level_actors()
          if actor.get_actor_label() in ('KeeperPointCloud_Traveller', 'KeeperPointCloud_Capture', 'KeeperPointCloud_Points')}
assert 'KeeperPointCloud_Traveller' in actors and 'KeeperPointCloud_Capture' in actors, 'Load both source/capture actors before this audit'
traveller = actors['KeeperPointCloud_Traveller']
capture = actors['KeeperPointCloud_Capture']
skeletal = traveller.skeletal_mesh_component
component = capture.capture_component2d
points = actors.get('KeeperPointCloud_Points')
animation = skeletal.get_editor_property('animation_data')
mesh = skeletal.get_editor_property('skeletal_mesh_asset')
target = component.get_editor_property('texture_target')
clip = animation.get_editor_property('anim_to_play')
location = traveller.get_actor_location()
camera = capture.get_actor_location()
out = {
    'traveller': traveller.get_path_name(),
    'traveller_package': traveller.get_package().get_name(),
    'mesh': mesh.get_path_name() if mesh else None,
    'animation_mode': str(skeletal.get_editor_property('animation_mode')),
    'visibility_tick': str(skeletal.get_editor_property('visibility_based_anim_tick_option')),
    'clip': clip.get_path_name() if clip else None,
    'saved_looping': animation.get_editor_property('saved_looping'),
    'saved_playing': animation.get_editor_property('saved_playing'),
    'saved_play_rate': animation.get_editor_property('saved_play_rate'),
    'traveller_location': [location.x, location.y, location.z],
    'capture': capture.get_path_name(),
    'capture_package': capture.get_package().get_name(),
    'capture_location': [camera.x, camera.y, camera.z],
    'target': target.get_path_name() if target else None,
    'fov': component.get_editor_property('fov_angle'),
    'every_frame': component.get_editor_property('capture_every_frame'),
    'render_mode': str(component.get_editor_property('primitive_render_mode')),
}
if points:
    niagara = points.get_component_by_class(unreal.NiagaraComponent)
    staff = points.get_editor_property('staff_source')
    system = niagara.get_editor_property('asset') if niagara else None
    staff_mesh = staff.get_editor_property('static_mesh') if staff else None
    out['points'] = {
        'actor': points.get_path_name(),
        'class': points.get_class().get_name(),
        'system': system.get_path_name() if system else None,
        'source_matches': points.get_editor_property('source_actor') == traveller,
        'capture_matches': points.get_editor_property('capture_actor') == capture,
        'staff_mesh': staff_mesh.get_path_name() if staff_mesh else None,
        'auto_activate': niagara.get_editor_property('auto_activate') if niagara else None,
    }
print('KEEPER_POINTCLOUD_EDITOR_AUDIT ' + json.dumps(out, separators=(',', ':')))
