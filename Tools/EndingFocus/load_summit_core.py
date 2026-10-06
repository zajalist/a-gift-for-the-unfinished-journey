import json
import unreal

es = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
assert es.get_game_world() is None and es.get_editor_world().get_name() == 'Saskarta_WP'
lib = unreal.WorldPartitionBlueprintLibrary
box = unreal.Box(unreal.Vector(296500., 482500., 8000.),
                 unreal.Vector(298300., 484300., 14000.))
raw = lib.get_intersecting_actor_descs(box)
descs = raw[1] if isinstance(raw, tuple) else raw
want = {
    'LandscapeStreamingProxy_6_9_0': '97D2EE5C444803BCCF5B8F886DA33CE6',
    'SD_S26_HighVoiceTripo_001': '22CF4B90403488BA0A805B96A77FE219',
    'SD_S26_Station_FoundationExtension_20261001': '753A041A48924FDE0F811C86A05D865F',
}
selected = [desc for desc in descs if str(desc.label) in want]
assert len(selected) == len(want)
for desc in selected:
    assert desc.guid.export_text() == want[str(desc.label)]
resident = {actor.get_editor_property('actor_guid').export_text()
            for actor in unreal.EditorLevelLibrary.get_all_level_actors()}
pending = [desc.guid for desc in selected if desc.guid.export_text() not in resident]
assert len(pending) <= 3
if pending:
    lib.load_actors(pending)
print('SUMMIT_CORE_LOADED ' + json.dumps({
    'requested': list(want), 'new_guids': [guid.export_text() for guid in pending],
}, separators=(',', ':')))
