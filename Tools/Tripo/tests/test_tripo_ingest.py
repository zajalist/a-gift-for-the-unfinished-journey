"""Offline checks for the Tripo ingest (Tools/Tripo/IMPORT.md). No editor, no network.

    python -m pytest Tools/Tripo/tests/test_tripo_ingest.py -q
"""
import io
import json
import os
import sys

import numpy as np
import pytest
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
TRIPO = os.path.dirname(HERE)
ROOT = os.path.dirname(os.path.dirname(TRIPO))
sys.path.insert(0, TRIPO)
import tripo_ingest as ti  # noqa: E402

PROJECTS = json.load(open(os.path.join(TRIPO, 'tripo_projects.json'), encoding='utf8'))['projects']
MANIFEST = os.path.join(ROOT, 'SourceArt', 'Tripo', 'manifest.json')


def _png(size, rgb):
    b = io.BytesIO()
    Image.new('RGB', (size, size), rgb).save(b, 'PNG')
    return b.getvalue()


def _synthetic_glb(path, tex=4096):
    """A 2 m x 1 m x 0.5 m quad pair off the origin (Y-up), with base colour and metallic-roughness maps."""
    pos = np.array([[-1, 0.3, -0.25], [1, 0.3, -0.25], [1, 1.3, 0.25], [-1, 1.3, 0.25]], np.float32) + [5, 0, 2]
    pos = pos.astype(np.float32)
    uv = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], np.float32)
    idx = np.array([0, 1, 2, 0, 2, 3], np.uint16)
    chunks = [pos.tobytes(), uv.tobytes(), idx.tobytes() + b'\0\0', _png(tex, (200, 100, 50)), _png(tex, (0, 180, 40))]
    bvs, binc = [], b''
    for c in chunks:
        binc += b'\0' * (-len(binc) % 4)
        bvs.append({'buffer': 0, 'byteOffset': len(binc), 'byteLength': len(c)})
        binc += c
    gltf = {
        'asset': {'version': '2.0'}, 'scene': 0, 'scenes': [{'nodes': [0]}], 'nodes': [{'mesh': 0}],
        'meshes': [{'primitives': [{'attributes': {'POSITION': 0, 'TEXCOORD_0': 1}, 'indices': 2, 'material': 0}]}],
        'accessors': [
            {'bufferView': 0, 'componentType': 5126, 'count': 4, 'type': 'VEC3',
             'min': pos.min(0).tolist(), 'max': pos.max(0).tolist()},
            {'bufferView': 1, 'componentType': 5126, 'count': 4, 'type': 'VEC2'},
            {'bufferView': 2, 'componentType': 5123, 'count': 6, 'type': 'SCALAR'}],
        'bufferViews': bvs, 'buffers': [{'byteLength': len(binc)}],
        'images': [{'bufferView': 3, 'mimeType': 'image/png'}, {'bufferView': 4, 'mimeType': 'image/png'}],
        'textures': [{'source': 0}, {'source': 1}],
        'materials': [{'pbrMetallicRoughness': {'baseColorTexture': {'index': 0},
                                                'metallicRoughnessTexture': {'index': 1}}}]}
    ti.write_glb(path, gltf, binc)


def test_stats_reads_size_tris_textures(tmp_path):
    f = str(tmp_path / 't.glb')
    _synthetic_glb(f)
    s = ti.glb_stats(f)
    assert s['tris'] == 2 and s['verts'] == 4
    assert s['native_size_cm_wdh'] == [200.0, 50.0, 100.0]
    assert s['min_up_cm'] == 30.0
    assert {t['role'] for t in s['textures']} == {'base_color', 'metal_rough'}
    assert all(t['width'] == 4096 for t in s['textures'])


def test_prep_pivot_scale_cap_orm(tmp_path):
    src, dst = str(tmp_path / 't.glb'), str(tmp_path / 't_ue.glb')
    _synthetic_glb(src)
    s = ti.prep_one({'key': 't', 't2': 't', 'real_size_m': [4, 1, 2]}, src, dst)
    assert s == pytest.approx(2.0)
    st = ti.glb_stats(dst)
    assert st['native_size_cm_wdh'] == [400.0, 100.0, 200.0]       # largest axis 2 m -> 4 m
    assert st['min_up_cm'] == 0.0                                   # base on the origin
    g, b = ti.read_glb(dst)
    lo = np.full(3, np.inf)
    hi = -lo
    for mesh_i, m in ti._mesh_instances(g):
        p = ti.read_accessor(g, b, g['meshes'][mesh_i]['primitives'][0]['attributes']['POSITION'])
        w = p @ m[:3, :3].T + m[:3, 3]
        lo, hi = np.minimum(lo, w.min(0)), np.maximum(hi, w.max(0))
    assert abs(lo[0] + hi[0]) < 1e-5 and abs(lo[2] + hi[2]) < 1e-5  # centred in X and Z
    assert all(t['width'] <= ti.TEX_CAP for t in st['textures'])
    mat = g['materials'][0]
    assert mat['occlusionTexture']['index'] == mat['pbrMetallicRoughness']['metallicRoughnessTexture']['index']
    raw, _ = ti._view_bytes(g, b, g['images'][1]['bufferView'])
    assert Image.open(io.BytesIO(raw)).getpixel((3, 3)) == (255, 180, 40)   # R = AO (white), G/B kept


def test_import_scale_basis():
    assert ti._import_scale({'real_size_m': [4, 1, 2]}, [100, 50, 25]) == 4.0
    assert ti._import_scale({'real_size_m': [4, 1, 2], 'scale_basis': 'h'}, [100, 50, 25]) == 8.0
    assert ti._import_scale({}, [100, 50, 25]) is None


def test_projects_table():
    keys = [p['key'] for p in PROJECTS]
    assert len(PROJECTS) == 37 and len(set(keys)) == 37
    for p in PROJECTS:
        assert p['project_id'] and len(p['project_id']) == 36, p['key']
        assert p['verdict'] in ('use', 'review', 'skip'), p['key']
        assert len(p['real_size_m']) == 3 and min(p['real_size_m']) > 0, p['key']
        assert p['scale_basis'] in ('max', 'h'), p['key']
    # every TRIPO2 slot the author listed is filled by a 'use' model, except the brass dome and telescope (O07)
    sys.path.insert(0, os.path.join(ROOT, 'Tools', 'World'))
    import setdress_catalog as sc
    filled = {p['t2'] for p in PROJECTS if p['verdict'] == 'use'}
    assert set(sc.TRIPO2) - filled == {'brass_dome', 'brass_telescope'}


@pytest.mark.skipif(not os.path.exists(MANIFEST), reason='run tripo_ingest.py all first')
def test_manifest_has_no_signed_urls_and_matches_projects():
    text = open(MANIFEST, encoding='utf8').read()
    assert 'Signature' not in text and 'Key-Pair-Id' not in text
    m = json.loads(text)
    assert [r['key'] for r in m['models']] == [p['key'] for p in PROJECTS]
    for r in m['models']:
        assert r['status'] == 'ok', r['key']
        if r['verdict'] == 'use':
            assert r.get('import_file'), r['key']
            assert r['import_textures'] == ['2048x2048'], r['key']
