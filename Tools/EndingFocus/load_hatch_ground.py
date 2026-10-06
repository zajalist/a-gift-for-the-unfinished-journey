import unreal

es = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
assert es.get_game_world() is None and es.get_editor_world().get_name() == 'Saskarta_WP'
box = unreal.Box(unreal.Vector(614500., 461500., -40000.),
                 unreal.Vector(618500., 465500., -30000.))
raw = unreal.WorldPartitionBlueprintLibrary.get_intersecting_actor_descs(box)
descs = raw[1] if isinstance(raw, tuple) else raw
selected = [desc for desc in descs if str(desc.label) == 'LandscapeStreamingProxy_12_9_0']
assert len(selected) == 1
assert selected[0].guid.export_text() == '04EB3D244440A4647149E484E079619C'
resident = {actor.get_editor_property('actor_guid').export_text()
            for actor in unreal.EditorLevelLibrary.get_all_level_actors()}
if selected[0].guid.export_text() not in resident:
    unreal.WorldPartitionBlueprintLibrary.load_actors([selected[0].guid])
print('HATCH_GROUND_LOADED', selected[0].guid.export_text())
