"""Prepare exact, bounded WP descriptor queries and selected prop/terrain loading.

Writes scripts only. Root executes them through the guarded editor route, with
PIE stopped and memory headroom checked immediately before each load.
"""
from __future__ import annotations
import argparse
import ast
import json
from pathlib import Path

from prepare_ground_contact_survey import ANCHORS, OUT

HEAD = '''import unreal, json
es = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
if es.get_game_world() is not None:
    raise RuntimeError('Stop PIE before ground contact streaming')
world = es.get_editor_world()
if world is None or world.get_name() != 'Saskarta_WP':
    raise RuntimeError('Expected Saskarta_WP editor world')
lib = unreal.WorldPartitionBlueprintLibrary
def xyz(p):
    return [p.x, p.y, p.z]
'''

QUERY = HEAD + '''
centre = __CENTRE__
radius = __RADIUS__
box = unreal.Box(unreal.Vector(centre[0]-radius, centre[1]-radius, -1000000),
                 unreal.Vector(centre[0]+radius, centre[1]+radius, 1000000))
raw = lib.get_intersecting_actor_descs(box)
descs = raw[1] if isinstance(raw, tuple) else raw
loaded = {a.get_editor_property('actor_guid').export_text() for a in unreal.EditorLevelLibrary.get_all_level_actors()}
rows = []
omitted_classes = {}
for d in descs:
    cls = d.native_class.get_name() if d.native_class else ''
    if __CONTACT_ONLY__ and ('HLOD' in cls or cls in ('DecalActor', 'AmbientSound', 'LocationVolume', 'RuntimeVirtualTextureVolume')):
        omitted_classes[cls] = omitted_classes.get(cls, 0) + 1
        continue
    rows.append({'guid': d.guid.export_text(), 'label': str(d.label),
                 'native_class': cls, 'class': d.class_.export_text(),
                 'actor_path': str(d.actor_path), 'package': str(d.actor_package),
                 'bounds': [xyz(d.bounds.min), xyz(d.bounds.max)],
                 'spatial': d.is_spatially_loaded, 'loaded': d.guid.export_text() in loaded,
                 'editor_only': d.actor_is_editor_only, 'runtime_grid': str(d.runtime_grid)})
rows.sort(key=lambda r: ('Landscape' not in r['native_class'], r['label']))
print('GROUND_DESCRIPTORS ' + json.dumps({'centre': centre, 'radius_cm': radius,
      'descriptor_count': len(descs), 'contact_scope': __CONTACT_ONLY__, 'omitted_classes': omitted_classes,
      'included_count': len(rows), 'truncated': len(rows)>100, 'rows': rows[:100]}, separators=(',', ':')))
'''

LOAD = HEAD + '''
selection = __SELECTION__
box = unreal.Box(unreal.Vector(*__MIN__), unreal.Vector(*__MAX__))
raw = lib.get_intersecting_actor_descs(box)
descs = raw[1] if isinstance(raw, tuple) else raw
by_guid = {d.guid.export_text(): d for d in descs}
resident = {a.get_editor_property('actor_guid').export_text() for a in unreal.EditorLevelLibrary.get_all_level_actors()}
pending = []
for item in selection:
    d = by_guid.get(item['guid'])
    if d is None or str(d.actor_path) != item['actor_path'] or str(d.actor_package) != item['package'] or [xyz(d.bounds.min), xyz(d.bounds.max)] != item['bounds']:
        raise RuntimeError('Descriptor changed; query this small region again')
    if item['guid'] not in resident:
        pending.append(d.guid)
if len(pending) > 4:
    raise RuntimeError('At most four explicit actors per call')
if pending:
    lib.load_actors(pending)
print('GROUND_LOADED ' + json.dumps({'requested': selection, 'new_guids': [g.export_text() for g in pending],
      'existing_residents_preserved': True}, separators=(',', ':')))
'''

RELEASE = HEAD + '''
selection = __SELECTION__
new_guids = set(__NEW_GUIDS__)
dirty = {p.get_name() for p in unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()}
dirty.update(p.get_name() for p in unreal.EditorLoadingAndSavingUtils.get_dirty_map_packages())
if any(item['package'] in dirty for item in selection if item['guid'] in new_guids):
    raise RuntimeError('A contact package is dirty; save or deliberately retain it before releasing')
box = unreal.Box(unreal.Vector(*__MIN__), unreal.Vector(*__MAX__))
raw = lib.get_intersecting_actor_descs(box)
descs = raw[1] if isinstance(raw, tuple) else raw
guids = [d.guid for d in descs if d.guid.export_text() in new_guids]
if guids:
    lib.unload_actors(guids)
print('GROUND_RELEASED ' + json.dumps({'guids': [g.export_text() for g in guids],
      'existing_residents_preserved': True}, separators=(',', ':')))
'''


def checked(script):
    ast.parse(script)
    for word in ('try', 'getattr', 'import time', 'open(', '.replace(', 'new_level(', 'save_asset', 'set_actor_', 'set_editor_property'):
        if word in script:
            raise ValueError(f'Editor policy token: {word}')
    return script


def read_result(path):
    text = path.read_text(encoding='utf-8')
    for marker in ('GROUND_DESCRIPTORS ', 'GROUND_LOADED '):
        if marker in text:
            text = text.split(marker, 1)[1].splitlines()[0]
            break
    return json.loads(text)


def selection_from(result, labels):
    if not 1 <= len(labels) <= 2 or len(set(labels)) != len(labels) or result['truncated']:
        raise ValueError('Use one/two exact labels and a complete small-region descriptor result')
    props = []
    for label in labels:
        matches = [r for r in result['rows'] if r['label'] == label]
        if len(matches) != 1:
            raise ValueError(f'Label must resolve exactly once: {label}')
        row = matches[0]
        if row['native_class'] != 'StaticMeshActor':
            raise ValueError('First contact batch must use placed StaticMeshActors; PCG/HLOD needs its own scoped plan')
        props.append(row)
    landscape = []
    for row in result['rows']:
        if 'Landscape' not in row['native_class']:
            continue
        if any(all(row['bounds'][0][axis] <= prop['bounds'][1][axis] + 500 and
                   row['bounds'][1][axis] >= prop['bounds'][0][axis] - 500 for axis in (0, 1)) for prop in props):
            landscape.append(row)
    # Prefer collision-bearing streaming proxies; the persistent Landscape actor alone is insufficient.
    proxies = [r for r in landscape if r['native_class'] == 'LandscapeStreamingProxy']
    if not proxies:
        raise ValueError('No current LandscapeStreamingProxy under the selected prop; refine the descriptor query')
    selected = proxies + props
    if len(selected) > 4:
        raise ValueError('More than four actors; split the contact sample before loading')
    return selected


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--anchor', choices=ANCHORS, default='descent_carts_historical')
    ap.add_argument('--radius-cm', type=float, default=12000)
    ap.add_argument('--contact-only', action='store_true', help='Omit decals, HLODs, sound and editor volumes; retain all terrain and source prop descriptors')
    ap.add_argument('--from-result', type=Path)
    ap.add_argument('--release-result', type=Path, help='GROUND_LOADED readback; release only actors added by that load')
    ap.add_argument('--label', action='append', default=[])
    args = ap.parse_args()
    if not 100 <= args.radius_cm <= 15000:
        raise ValueError('Descriptor query radius must be 1–150 m')
    OUT.mkdir(parents=True, exist_ok=True)
    if args.from_result and args.release_result:
        raise ValueError('Prepare a load or a release in one call')
    if args.from_result or args.release_result:
        result = read_result(args.from_result or args.release_result)
        selected = selection_from(result, args.label) if args.from_result else result['requested']
        if not 1 <= len(selected) <= 4:
            raise ValueError('Invalid selection count')
        lo = [min(r['bounds'][0][a] for r in selected) - 1 for a in range(3)]
        hi = [max(r['bounds'][1][a] for r in selected) + 1 for a in range(3)]
        if args.from_result:
            script = LOAD
            target = OUT / 'load_selected_contact.py'
            (OUT / 'load_selected_contact.selection.json').write_text(json.dumps(selected, indent=2), encoding='utf-8')
        else:
            if not set(result['new_guids']) <= {r['guid'] for r in selected}:
                raise ValueError('Release must name only actors from its load')
            script = RELEASE.replace('__NEW_GUIDS__', repr(result['new_guids']))
            target = OUT / 'release_selected_contact.py'
        script = script.replace('__SELECTION__', repr(selected)).replace('__MIN__', repr(lo)).replace('__MAX__', repr(hi))
    else:
        script = QUERY.replace('__CENTRE__', repr(ANCHORS[args.anchor])).replace('__RADIUS__', repr(args.radius_cm)).replace('__CONTACT_ONLY__', repr(args.contact_only))
        target = OUT / f'descriptors_{args.anchor}.py'
    target.write_text(checked(script), encoding='utf-8')
    print(target)


if __name__ == '__main__':
    main()
