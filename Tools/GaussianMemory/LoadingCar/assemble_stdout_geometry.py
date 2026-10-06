"""Assemble persisted actual editor stdout chunks, never invent missing geometry."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCOPE = ROOT/'Saved/Verification/gaussian_memory_20261001/loading_car'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--chunks', nargs='+', type=Path, required=True)
    args = parser.parse_args()
    chunks = [json.loads(path.read_text(encoding='utf-8')) for path in args.chunks]
    chunks.sort(key=lambda c: c['chunk'])
    first = chunks[0]
    if [c['chunk'] for c in chunks] != list(range(first['chunks'])):
        raise ValueError('Need every unique bounded chunk')
    for item in chunks:
        if {k:v for k,v in item.items() if k not in ('chunk','offset','rows')} != {k:v for k,v in first.items() if k not in ('chunk','offset','rows')}:
            raise ValueError('Actual geometry changed between reads')
    rows = []
    for chunk in chunks:
        if chunk['offset'] != len(rows):
            raise ValueError('Missing or repeated actual source triangles')
        rows.extend(chunk['rows'])
    if len(rows) != first['sample_triangles'] or any(len(row)!=10 or any(type(v)!=int for v in row) for row in rows):
        raise ValueError('Actual direct JSON triangle count/layout mismatch')
    vertices, triangles, material_ids = [], [], []
    for row in rows:
        start = len(vertices)
        for i in (0,3,6):
            vertices.append([row[i+j]*first['quantum_cm']+first['origin_cm'][j] for j in range(3)])
        triangles.append([start,start+1,start+2])
        material_ids.append(row[9])
    target = SCOPE/'carrier_geometry.json'
    if target.exists():
        raise ValueError('Retain original actual geometry export; refuse overwrite')
    SCOPE.mkdir(parents=True, exist_ok=True)
    data = {'representation':'actual_mesh_surface_source', 'trained':False,
        'source_asset':first['source_asset'], 'source_lod':first['source_lod'], 'source_kind':first['source_kind'],
        'units':'UE_local_centimeters', 'vertices':vertices, 'triangles':triangles,
        'triangle_material_ids':material_ids, 'materials':first['materials'],
        'source_mesh_modified':False, 'actors_spawned':False, 'sampling':first['sampling'],
        'source_counts':[first['source_vertices'],first['source_triangles']],
        'source_bounds_cm':first['source_bounds_cm'], 'maximum_quantization_error_cm':first['quantum_cm']/2,
        'direct_surface_sha256':hashlib.sha256(json.dumps(rows,separators=(',',':')).encode('utf-8')).hexdigest()}
    target.write_text(json.dumps(data,separators=(',',':'),allow_nan=False),encoding='utf-8')
    print(str(target))


if __name__ == '__main__':
    main()
