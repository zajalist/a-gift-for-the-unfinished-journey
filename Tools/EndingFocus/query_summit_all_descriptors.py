"""Read-only exact summit descriptor census, including the HighVoice beam actor."""
import json
import unreal

es = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
assert es.get_game_world() is None and es.get_editor_world().get_name() == 'Saskarta_WP'
box = unreal.Box(unreal.Vector(296500., 482500., 8000.),
                 unreal.Vector(298300., 484300., 14000.))
raw = unreal.WorldPartitionBlueprintLibrary.get_intersecting_actor_descs(box)
descs = raw[1] if isinstance(raw, tuple) else raw
rows = []
for desc in descs:
    cls = desc.native_class.get_name() if desc.native_class else ''
    rows.append({'guid': desc.guid.export_text(), 'label': str(desc.label),
                 'class': cls, 'path': str(desc.actor_path),
                 'package': str(desc.actor_package)})
print('SUMMIT_ALL_DESCRIPTORS ' + json.dumps({'count': len(rows), 'rows': rows}, separators=(',', ':')))
