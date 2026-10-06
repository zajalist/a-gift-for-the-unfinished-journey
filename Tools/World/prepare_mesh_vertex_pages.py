"""Emit small render-LOD vertex stdout pages and combine verified readbacks offline."""
from pathlib import Path
import argparse
import json
import math
from prepare_ground_contact_loading import HEAD

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'Saved/GroundContactSurvey'
PAGE_SIZE = 900

PAGE = HEAD + '''
mesh = unreal.load_asset(__PATH__)
if not isinstance(mesh, unreal.StaticMesh):
    raise RuntimeError('Expected the selected StaticMesh')
dm = unreal.DynamicMesh()
lod = unreal.GeometryScriptMeshReadLOD()
lod.lod_type = unreal.GeometryScriptLODType.RENDER_DATA
lod.lod_index = 0
options = unreal.GeometryScriptCopyMeshFromAssetOptions()
options.request_tangents = False
dm, outcome = unreal.GeometryScript_AssetUtils.copy_mesh_from_static_mesh(mesh, dm, options, lod)
if outcome != unreal.GeometryScriptOutcomePins.SUCCESS:
    raise RuntimeError('Render-data mesh conversion failed')
got = unreal.GeometryScript_MeshQueries.get_all_vertex_positions(dm, False)
if got[2]:
    raise RuntimeError('Unexpected vertex ID gaps')
positions = unreal.GeometryScript_List.convert_vector_list_to_array(got[1])
total = len(positions)
if not 3 <= total <= 12000:
    raise RuntimeError('Unexpected render vertex count; stop bounded extraction')
vertices = [[round(v.x, 4), round(v.y, 4), round(v.z, 4)] for v in positions]
bounds = [[min(v[i] for v in vertices) for i in range(3)], [max(v[i] for v in vertices) for i in range(3)]]
offset = __OFFSET__
if offset >= total:
    raise RuntimeError('Page begins beyond the mesh')
page = vertices[offset:offset+900]
print('MESH_VERTEX_PAGE ' + json.dumps({'path': mesh.get_path_name(), 'source': 'render_data_geometry_script',
      'lod': 0, 'total': total, 'bounds': bounds, 'offset': offset, 'page_size': 900,
      'vertices': page, 'next_offset': offset+len(page) if offset+len(page)<total else None}, separators=(',', ':')))
'''


def page_script(path, offset):
    import ast
    if not path.startswith('/Game/') or not 0 <= offset < 12000 or offset % PAGE_SIZE:
        raise ValueError('Use an exact project mesh path and 900-vertex page offset')
    script = PAGE.replace('__PATH__', repr(path)).replace('__OFFSET__', str(offset))
    tree = ast.parse(script)
    if any(isinstance(node, (ast.Try, ast.TryStar)) for node in ast.walk(tree)):
        raise ValueError('Editor scripts must not hide failures')
    for token in ('getattr', 'import time', 'open(', '.replace(', 'new_level(', 'save_asset', 'set_actor_'):
        if token in script:
            raise ValueError(f'Editor policy token {token}')
    return script


def combine(pages):
    if not pages:
        raise ValueError('Need at least one vertex page')
    pages = sorted(pages, key=lambda p: p['offset'])
    first = pages[0]
    if first['source'] != 'render_data_geometry_script' or first['lod'] != 0 or not 3 <= first['total'] <= 12000:
        raise ValueError('Need bounded explicit render LOD0 pages')
    vertices = []
    for page in pages:
        if any(page[k] != first[k] for k in ('path', 'source', 'lod', 'total', 'bounds', 'page_size')):
            raise ValueError('Mesh identity/count/bounds changed between pages')
        if page['offset'] != len(vertices) or page['page_size'] != PAGE_SIZE:
            raise ValueError('Missing, overlapping or invalid vertex page')
        expected = min(PAGE_SIZE, first['total']-len(vertices))
        if len(page['vertices']) != expected:
            raise ValueError('Vertex page was truncated')
        vertices.extend(page['vertices'])
        next_offset = len(vertices) if len(vertices) < first['total'] else None
        if page['next_offset'] != next_offset:
            raise ValueError('Vertex page continuation does not match count')
    if len(vertices) != first['total'] or pages[-1]['next_offset'] is not None:
        raise ValueError('Mesh extraction is incomplete')
    if any(len(v) != 3 or not all(math.isfinite(x) for x in v) for v in vertices):
        raise ValueError('Invalid render vertex')
    actual = [[min(v[a] for v in vertices) for a in range(3)], [max(v[a] for v in vertices) for a in range(3)]]
    if actual != first['bounds']:
        raise ValueError('Combined vertices do not cover the full render bounds')
    return dict(path=first['path'], lod=first['lod'], source=first['source'],
                counts={'vertices': len(vertices)}, vertices=vertices, bounds=actual, truncated=False)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--mesh')
    ap.add_argument('--name', default='mesh')
    ap.add_argument('--offset', type=int, default=0)
    ap.add_argument('--readbacks', nargs='+', type=Path)
    args = ap.parse_args()
    if not args.name.replace('_', '').isalnum():
        raise ValueError('Use a simple output name')
    OUT.mkdir(parents=True, exist_ok=True)
    if args.readbacks:
        pages = [json.loads(p.read_text(encoding='utf-8').split('MESH_VERTEX_PAGE ', 1)[1].splitlines()[0]) for p in args.readbacks]
        target = OUT / f'{args.name}.complete_mesh.json'
        target.write_text(json.dumps(combine(pages)), encoding='utf-8')
    else:
        target = OUT / f'{args.name}_vertices_{args.offset:04d}.py'
        target.write_text(page_script(args.mesh, args.offset), encoding='utf-8')
    print(target)


if __name__ == '__main__':
    main()
