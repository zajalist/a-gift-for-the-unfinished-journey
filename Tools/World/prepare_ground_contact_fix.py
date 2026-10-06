"""Prepare a single prop's current-render-vertex survey or a measured vertical repair.

Offline only. Needs a current catalog selection and a non-truncated native
mesh_extract readback, then the resulting current-landscape GROUND_MEASURE.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from prepare_ground_contact_survey import OUT, measure_script
from prepare_ground_contact_loading import HEAD


def unwrap(path, marker=None):
    text = path.read_text(encoding='utf-8')
    if marker and marker in text:
        text = text.split(marker, 1)[1].splitlines()[0]
    value = json.loads(text)
    # Native transport envelopes are not assumed: accept the actual handler result
    # or its ordinary result/data field only when it contains the expected payload.
    for _ in range(3):
        if isinstance(value, dict) and any('vertices' in str(item.get('path', '')) for item in value.get('_truncated', []) if isinstance(item, dict)):
            raise ValueError('Transport truncated mesh vertices; handler truncated=false is not sufficient')
        if isinstance(value, dict) and ('vertices' in value or 'rows' in value):
            return value
        if isinstance(value, dict) and isinstance(value.get('result'), dict):
            value = value['result']
        elif isinstance(value, dict) and isinstance(value.get('data'), dict):
            value = value['data']
        else:
            break
    return value


def pose_parts(text):
    parts = []
    for name, axes in [('Rotation', 'XYZW'), ('Translation', 'XYZ'), ('Scale3D', 'XYZ')]:
        match = re.search(r'\b' + name + r'=\(([^)]+)\)', text)
        if not match:
            raise ValueError('Expected current Unreal transform export')
        fields = dict(re.findall(r'([XYZW])=([-+0-9.eE]+)', match.group(1)))
        parts.append([float(fields[a]) for a in axes])
    if not all(math.isfinite(v) for p in parts for v in p) or abs(sum(v*v for v in parts[0])-1) > 0.001:
        raise ValueError('Invalid transform')
    return parts


def world_point(local, pose):
    q, t, scale = pose
    v = [local[i] * scale[i] for i in range(3)]
    def cross(a, b):
        return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]
    twice = [2*x for x in cross(q, v)]
    again = cross(q, twice)
    return [v[i] + q[3]*twice[i] + again[i] + t[i] for i in range(3)]


def select_contacts(selection, extract):
    if selection['instance'] is not None:
        raise ValueError('First repair is one placed prop; instance groups need their owning pipeline')
    if extract.get('path') != selection['mesh'] or extract.get('lod') != 0 or extract.get('truncated', True):
        raise ValueError('Need complete LOD0 extraction of the exact current catalog mesh')
    points = extract.get('vertices', [])
    if any('vertices' in str(item.get('path', '')) for item in extract.get('_truncated', []) if isinstance(item, dict)):
        raise ValueError('Transport truncated mesh vertices')
    if extract.get('counts', {}).get('vertices') != len(points):
        raise ValueError('Extracted vertex count does not match the complete mesh count')
    if not 3 <= len(points) <= 12000 or any(len(p) != 3 or not all(math.isfinite(v) for v in p) for p in points):
        raise ValueError('Need 3..12000 finite render vertices')
    pose = pose_parts(selection['transform'])
    world = [world_point(p, pose) for p in points]
    lo = [min(p[i] for p in world) for i in (0, 1)]
    span = [max(p[i] for p in world)-lo[i] for i in (0, 1)]
    bins = {}
    for i, p in enumerate(world):
        cell = tuple(min(2, int((p[a]-lo[a])*3/max(span[a], 0.001))) for a in (0, 1))
        if cell not in bins or p[2] < world[bins[cell]][2]:
            bins[cell] = i
    contacts = [points[bins[cell]] for cell in sorted(bins)]
    return dict(selection, local_contacts=contacts)


def vertical_plan(measure, sink_cm=3, max_drop_cm=200):
    if not 0 <= sink_cm <= 10 or not 5 <= max_drop_cm <= 300:
        raise ValueError('Use 0..10 cm sink and 5..300 cm maximum drop')
    rows = measure['rows']
    if len(rows) != 1 or rows[0]['status'] != 'measured':
        raise ValueError('Need one currently measured prop')
    row = rows[0]
    selection = row['selected']
    if selection['instance'] is not None or len(selection.get('local_contacts', [])) < 3:
        raise ValueError('Need at least three real mesh-local contacts on a solo prop')
    if len(row['samples']) != len(selection['local_contacts']):
        raise ValueError('Every supplied contact must have its own trace')
    clearances = []
    for sample in row['samples']:
        down = sample['down']
        if sample['kind'] != 'authored_contact' or down['status'] != 'landscape' or not down['hits']:
            raise ValueError('Every real contact needs a current landscape hit')
        # A mesh support is a separate assembly decision, not permission to lower a stacked item.
        if not down['hits'][0]['landscape']:
            raise ValueError('Intervening support found; inspect the assembly before moving it')
        clearance = down['hits'][0]['clearance_cm']
        if not math.isfinite(clearance):
            raise ValueError('Every contact clearance must be finite')
        clearances.append(clearance)
    lowest = min(clearances)
    if lowest <= 5:
        raise ValueError('At least one actual contact already touches; do not automatically lower')
    drop = lowest + sink_cm
    if not math.isfinite(drop) or drop > max_drop_cm:
        raise ValueError('Measured drop exceeds this bounded repair')
    return {'selected': selection, 'owner': row['owner'], 'delta_z_cm': -drop,
            'clearances_cm': clearances, 'sink_cm': sink_cm,
            'source': 'current landscape traces at current render LOD0 vertices',
            'preserve_xy_rotation_scale': True}


APPLY = HEAD + '''
plan = __PLAN__
selected = plan['selected']
owner = None
comp = None
for a in unreal.EditorLevelLibrary.get_all_level_actors():
    if a.get_path_name() == plan['owner']['path']:
        owner = a
if owner is None or owner.get_class().get_name() != 'StaticMeshActor':
    raise RuntimeError('Expected the exact loaded StaticMeshActor')
comps = owner.get_components_by_class(unreal.StaticMeshComponent)
if len(comps) != 1:
    raise RuntimeError('Composite actor needs an assembly repair')
comp = comps[0]
if comp.get_path_name() != selected['component'] or comp.static_mesh.get_path_name() != selected['mesh'] or comp.get_world_transform().export_text() != selected['transform']:
    raise RuntimeError('Current mesh/pose changed; recatalog and remeasure')
pose = comp.get_world_transform()
for i, p in enumerate(selected['local_contacts']):
    point = pose.transform_location(unreal.Vector(*p))
    hit = unreal.SystemLibrary.line_trace_single(world, point + unreal.Vector(0, 0, 2000),
          point - unreal.Vector(0, 0, 20000), unreal.TraceTypeQuery.TRACE_TYPE_QUERY1,
          True, [owner], unreal.DrawDebugTrace.NONE, True)
    if isinstance(hit, tuple) and len(hit) == 2 and not isinstance(hit[0], unreal.HitResult):
        hit = hit[1] if hit[0] else None
    if hit is None or not hit.to_tuple()[0]:
        raise RuntimeError('Current terrain unavailable; no move')
    data = hit.to_tuple()
    if data[9] is None or 'Landscape' not in data[9].get_class().get_name() or abs((point.z-data[5].z)-plan['clearances_cm'][i]) > 1.0:
        raise RuntimeError('Support/terrain changed; no move')
before = owner.get_actor_transform().export_text()
location = owner.get_actor_location()
owner.modify()
owner.set_actor_location(location + unreal.Vector(0, 0, plan['delta_z_cm']), False, True)
print('GROUND_FIXED ' + json.dumps({'actor': owner.get_path_name(), 'package': owner.get_package().get_name(),
      'before': before, 'after': owner.get_actor_transform().export_text(),
      'delta_z_cm': plan['delta_z_cm'], 'saved': False}, separators=(',', ':')))
'''


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--selection', type=Path)
    ap.add_argument('--mesh-extract', type=Path)
    ap.add_argument('--measurement', type=Path)
    ap.add_argument('--sink-cm', type=float, default=3)
    ap.add_argument('--max-drop-cm', type=float, default=200)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if args.measurement:
        plan = vertical_plan(unwrap(args.measurement, 'GROUND_MEASURE '), args.sink_cm, args.max_drop_cm)
        (OUT / 'current_contact_fix.plan.json').write_text(json.dumps(plan, indent=2), encoding='utf-8')
        script = APPLY.replace('__PLAN__', repr(plan))
        # This stage intentionally allows this one actor mutation; normal query/loading checks reject it.
        import ast
        ast.parse(script)
        for token in ('try', 'getattr', 'import time', 'open(', '.replace(', 'new_level(', 'save_asset', 'destroy_actor'):
            if token in script:
                raise ValueError(f'Editor policy token {token}')
        target = OUT / 'apply_current_contact_fix.py'
    else:
        if not args.selection or not args.mesh_extract:
            ap.error('Supply selection + mesh-extract, or a completed measurement')
        selections = json.loads(args.selection.read_text(encoding='utf-8'))
        if len(selections) != 1:
            raise ValueError('One mesh support sample per contact extraction')
        selection = select_contacts(selections[0], unwrap(args.mesh_extract))
        (OUT / 'current_vertex_contacts.selection.json').write_text(json.dumps([selection], indent=2), encoding='utf-8')
        (OUT / 'current_vertex_contacts.provenance.json').write_text(json.dumps({
            'mesh_extract_file': str(args.mesh_extract.resolve()),
            'sha256': hashlib.sha256(args.mesh_extract.read_bytes()).hexdigest(),
            'selection': selection, 'sampling': 'Lowest real render vertex in each of nine XY cells'}, indent=2), encoding='utf-8')
        script = measure_script([selection])
        target = OUT / 'measure_current_vertex_contacts.py'
    target.write_text(script, encoding='utf-8')
    print(target)


if __name__ == '__main__':
    main()
