"""Measure support from a whole bounded render mesh inside Unreal, returning only contacts.

The full render vertex buffer stays in the read-only editor script. Output never
relies on transport returning an unshortened native array. A prior mesh_get_info
count is mandatory and must match the GeometryScript conversion exactly.
"""
from pathlib import Path
import argparse
import ast
import json
from prepare_ground_contact_survey import MEASURE, OUT

CONTACTS = '''    expected_count = expected_counts[path(mesh)]
    dm = unreal.DynamicMesh()
    lod = unreal.GeometryScriptMeshReadLOD()
    lod.lod_type = unreal.GeometryScriptLODType.RENDER_DATA
    lod.lod_index = 0
    options = unreal.GeometryScriptCopyMeshFromAssetOptions()
    options.request_tangents = False
    dm, outcome = unreal.GeometryScript_AssetUtils.copy_mesh_from_static_mesh(mesh, dm, options, lod)
    if outcome != unreal.GeometryScriptOutcomePins.SUCCESS:
        raise RuntimeError('Render conversion failed')
    got = unreal.GeometryScript_MeshQueries.get_all_vertex_positions(dm, False)
    if got[2]:
        raise RuntimeError('Unexpected vertex ID gaps')
    vertices = unreal.GeometryScript_List.convert_vector_list_to_array(got[1])
    if len(vertices) != expected_count:
        raise RuntimeError('Full render count changed; do not trust contact selection')
    transformed = [pose.transform_location(v) for v in vertices]
    lo = [min(v.x for v in transformed), min(v.y for v in transformed)]
    span = [max(v.x for v in transformed)-lo[0], max(v.y for v in transformed)-lo[1]]
    bins = {}
    for vi, point in enumerate(transformed):
        cell = (min(2, int((point.x-lo[0])*3/max(span[0],0.001))), min(2, int((point.y-lo[1])*3/max(span[1],0.001))))
        if cell not in bins or point.z < transformed[bins[cell]].z:
            bins[cell] = vi
    item['local_contacts'] = [[vertices[bins[cell]].x,vertices[bins[cell]].y,vertices[bins[cell]].z] for cell in sorted(bins)]
    render_proofs.append({'mesh':path(mesh),'source':'RENDER_DATA','lod':0,'expected_vertices':expected_count,
        'actual_vertices':len(vertices),'contact_count':len(bins),
        'bounds':[[min(v.x for v in vertices),min(v.y for v in vertices),min(v.z for v in vertices)],
                  [max(v.x for v in vertices),max(v.y for v in vertices),max(v.z for v in vertices)]]})
'''


def render_contact_script(selected, expected_counts, max_render_vertices=12000):
    if not 1 <= len(selected) <= 2:
        raise ValueError('Use one or two exact current components')
    if not 3 <= max_render_vertices <= 20000:
        raise ValueError('Explicit render budget must stay within 3..20000 vertices')
    for row in selected:
        if set(row) != {'component', 'mesh', 'instance', 'transform'}:
            raise ValueError('Use only exact current catalog selection fields')
        if row['mesh'] not in expected_counts or not 3 <= expected_counts[row['mesh']] <= max_render_vertices:
            raise ValueError('Confirm render vertices within the explicit budget with mesh_get_info first')
    if sum(expected_counts[row['mesh']] for row in selected) > max_render_vertices:
        raise ValueError('Combined render conversions exceed this call budget')
    code = MEASURE.replace('__SELECTED__', repr(selected))
    code = code.replace('selected = ', 'render_proofs = []\nexpected_counts = ' + repr(expected_counts) + '\nselected = ', 1)
    needle = '    bb = mesh.get_bounding_box()\n'
    if code.count(needle) != 1:
        raise ValueError('Measurement source changed; inspect insertion point')
    code = code.replace(needle, CONTACTS + needle)
    code = code.replace("'trace_count': trace_count, 'rows': rows,", "'trace_count': trace_count, 'rows': rows, 'render_proofs': render_proofs,")
    tree = ast.parse(code)
    if any(isinstance(n, (ast.Try, ast.TryStar)) for n in ast.walk(tree)):
        raise ValueError('Do not hide editor failures')
    for token in ('getattr', 'open(', 'save_asset', 'set_actor_', 'set_editor_property', 'update_instance', 'generate_local'):
        if token in code:
            raise ValueError('Read-only contact probe rejected: ' + token)
    return code


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--selection', required=True, type=Path)
    ap.add_argument('--counts', required=True, type=Path, help='JSON map of exact mesh path to confirmed render vertex count')
    ap.add_argument('--name', required=True)
    ap.add_argument('--max-render-vertices', type=int, default=12000,
                    help='Total conversion budget; explicit increase up to20000 for confirmed small props')
    args = ap.parse_args()
    if not args.name.replace('_', '').isalnum():
        raise ValueError('Use a simple output name')
    code = render_contact_script(json.loads(args.selection.read_text(encoding='utf-8')),
                                 json.loads(args.counts.read_text(encoding='utf-8')), args.max_render_vertices)
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / (args.name + '.py')
    target.write_text(code, encoding='utf-8')
    print(target)


if __name__ == '__main__':
    main()
