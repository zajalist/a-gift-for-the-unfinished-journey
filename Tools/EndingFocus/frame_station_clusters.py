import unreal

es = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
assert es.get_game_world() is None and es.get_editor_world().get_name() == 'Saskarta_WP'
unreal.get_editor_subsystem(unreal.EditorActorSubsystem).set_selected_level_actors([])
es.set_level_viewport_camera_info(unreal.Vector(297310., 482730., 11140.),
                                  unreal.Rotator(roll=0., pitch=-17., yaw=51.))
print('ENDING_STATION_FRAMED', str(es.get_level_viewport_camera_info()))
