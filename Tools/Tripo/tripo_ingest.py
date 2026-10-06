"""Bring the user's Tripo Studio models onto this PC and describe them for the editor lane.

    python Tools/Tripo/tripo_ingest.py resolve    # project ids -> fresh signed URLs in Saved/Tripo/urls.tsv
    python Tools/Tripo/tripo_ingest.py download   # curl every URL in urls.tsv into SourceArt/Tripo/<key>/
    python Tools/Tripo/tripo_ingest.py decode     # <key>_meshopt.glb -> <key>.glb (meshopt decoded, dequantized)
    python Tools/Tripo/tripo_ingest.py prep       # <key>.glb -> <key>_ue.glb (pivot at base, real-world scale,
                                                  #   textures <= 2048, packed ORM, PNG/JPEG only) for the editor
    python Tools/Tripo/tripo_ingest.py stats      # tris, verts, textures, sizes -> SourceArt/Tripo/manifest.json
    python Tools/Tripo/tripo_ingest.py contact    # SourceArt/Tripo/contact_sheet.png from the studio previews
    python Tools/Tripo/tripo_ingest.py all        # the six steps in order (each skips files already present;
                                                  #   --force redoes them)

Inputs:
  Tools/Tripo/tripo_projects.json   one row per Tripo project: key, project id, task id, T2 slot, planned real size,
                                    scale basis, intended use, verdict. Hand-curated; the ids come from the Studio list.
  Saved/Tripo/urls.tsv              key <TAB> kind (model|cover) <TAB> signed URL, written by `resolve`. The URLs are
                                    CloudFront-signed and expire (~1 day); Saved/ is git-ignored, never commit them.

Where the files come from: every project is 'shareable', so `resolve` reads its detail
(api.tripo3d.ai/v2/studio/project/detail/v3/<project id>, the call a share link makes, no login) and takes the
project's `model_url` (tripo_pbr_model_<task>_meshopt.glb; output_mesh_<task>.fbx for the older image-to-model
projects) and the cover render (studio_mesh.webp, or studio_wireframe.webp when that is all there is). The list of
project ids needs the logged-in Studio (api .../v2/studio/assets/v2?asset_type=mine&type=all, read once in the
browser). The Studio's default Export (GLB/FBX/OBJ at native texture size) is a client-side conversion of that same
`model_url` file, so the meshopt GLB is the full-quality source. Nothing here calls a paid endpoint or spends credits.

Nothing in this script opens Unreal. Pure Python (numpy, Pillow) plus `npx @gltf-transform/cli` for the decode.
Reuses Tools/ModelReview/fbx_reader.py for the FBX rows.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import struct
import subprocess
import sys
import urllib.request

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
OUT = os.path.join(ROOT, 'SourceArt', 'Tripo')
PROJECTS = os.path.join(HERE, 'tripo_projects.json')
URLS = os.path.join(ROOT, 'Saved', 'Tripo', 'urls.tsv')
MANIFEST = os.path.join(OUT, 'manifest.json')
CONTACT = os.path.join(OUT, 'contact_sheet.png')
TEX_CAP = 2048          # the import plan's texture cap (Tools/Tripo/IMPORT.md)

sys.path.insert(0, os.path.join(ROOT, 'Tools', 'ModelReview'))


def load_projects():
    with open(PROJECTS, encoding='utf8') as fh:
        return json.load(fh)['projects']


def key_dir(key):
    d = os.path.join(OUT, key)
    os.makedirs(d, exist_ok=True)
    return d


# --------------------------------------------------------------------------------------------- resolve

DETAIL_API = 'https://api.tripo3d.ai/v2/studio/project/detail/v3/'
DETAILS = os.path.join(ROOT, 'Saved', 'Tripo', 'details')


def resolve(args):
    """Project id -> fresh signed URLs. The projects are 'shareable', so their detail is readable without a login
    (the same call a share link makes). The JSON (with the signed URLs) goes to Saved/, never to git."""
    os.makedirs(DETAILS, exist_ok=True)
    lines, fails = [], []
    projects = load_projects()
    for p in projects:
        pid = p.get('project_id')
        if not pid:
            fails.append(f'{p["key"]}: no project_id')
            continue
        try:
            with urllib.request.urlopen(urllib.request.Request(DETAIL_API + pid, headers={'User-Agent': 'Mozilla/5.0'}), timeout=30) as r:
                j = json.load(r)
        except Exception as e:  # noqa: BLE001
            fails.append(f'{p["key"]}: {e}')
            continue
        if j.get('code') != 0 or not j.get('data', {}).get('model_url'):
            fails.append(f'{p["key"]}: api code {j.get("code")} {j.get("message")}')
            continue
        d = j['data']
        with open(os.path.join(DETAILS, pid + '.json'), 'w', encoding='utf8') as fh:
            json.dump(d, fh, indent=1)
        task = (d.get('operator') or {}).get('operator_id')
        if p.get('task_id') and task and task != p['task_id']:
            print(f'  note {p["key"]}: task id changed {p["task_id"]} -> {task} (the project was edited)')
        lines.append(f'{p["key"]}\tmodel\t{d["model_url"]}')
        covers = d.get('cover_image') or []
        # the textured render; the older untextured image-to-model projects only have studio_wireframe.webp
        cover = next((c for c in covers if 'studio_mesh.webp' in c), covers[0] if covers else None)
        if cover:
            lines.append(f'{p["key"]}\tcover\t{cover}')
        print(f'  ok   {p["key"]:<28} {_basename(d["model_url"])}')
    os.makedirs(os.path.dirname(URLS), exist_ok=True)
    with open(URLS, 'w', encoding='utf8') as fh:
        fh.write('# key<TAB>kind<TAB>signed url; written by tripo_ingest.py resolve; expires in about a day\n')
        fh.write('\n'.join(lines) + '\n')
    print(f'  wrote {len(lines)} URLs for {len(projects) - len(fails)} of {len(projects)} projects')
    if fails:
        print('FAILED:\n  ' + '\n  '.join(fails))
    return not fails


# --------------------------------------------------------------------------------------------- download

def _basename(url):
    return url.split('?', 1)[0].rsplit('/', 1)[-1]


def download(args):
    if not os.path.exists(URLS):
        sys.exit(f'no URL list at {URLS}')
    rows = [ln.rstrip('\n').split('\t') for ln in open(URLS, encoding='utf8') if ln.strip() and not ln.startswith('#')]
    fails = []
    for key, kind, url in rows:
        d = key_dir(key)
        name = 'preview.webp' if kind == 'cover' else _basename(url)
        dst = os.path.join(d, name)
        if os.path.exists(dst) and os.path.getsize(dst) > 0 and not args.force:
            print(f'  have {key}/{name} ({os.path.getsize(dst) / 1e6:.1f} MB)')
            continue
        tmp = dst + '.part'
        # curl, not urllib: it retries and prints nothing of the URL (the signature stays off the console).
        r = subprocess.run(['curl', '-sS', '-L', '--fail', '--retry', '3', '-o', tmp, url], capture_output=True, text=True)
        if r.returncode != 0 or not os.path.exists(tmp) or os.path.getsize(tmp) == 0:
            fails.append(f'{key}/{name}: curl exit {r.returncode} {r.stderr.strip()[:120]}')
            if os.path.exists(tmp):
                os.remove(tmp)
            continue
        os.replace(tmp, dst)
        print(f'  got  {key}/{name} ({os.path.getsize(dst) / 1e6:.1f} MB)')
    if fails:
        print('FAILED:\n  ' + '\n  '.join(fails))
    return not fails


# --------------------------------------------------------------------------------------------- decode

def _npx():
    return 'npx.cmd' if os.name == 'nt' else 'npx'


def decode(args):
    ok = True
    for p in load_projects():
        d = key_dir(p['key'])
        src = [f for f in os.listdir(d) if f.endswith('_meshopt.glb')]
        if not src:
            continue
        dst = os.path.join(d, p['key'] + '.glb')
        if os.path.exists(dst) and not args.force:
            print(f'  have {p["key"]}.glb')
            continue
        # `copy` reads with the meshopt decoder and writes without EXT_meshopt_compression. KHR_mesh_quantization
        # would stay (int16/int8 attributes + a node scale), so `dequantize` then writes plain float32 attributes:
        # the importer sees an ordinary glTF. --keep-quantized skips that.
        cmd = [_npx(), '-y', '@gltf-transform/cli', 'copy', os.path.join(d, src[0]), dst]
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=d)
        if r.returncode != 0:
            ok = False
            print(f'  FAIL {p["key"]}: {r.stderr.strip()[-300:]}')
            continue
        if not args.keep_quantized:
            r = subprocess.run([_npx(), '-y', '@gltf-transform/cli', 'dequantize', dst, dst], capture_output=True, text=True, cwd=d)
            if r.returncode != 0:
                ok = False
                print(f'  FAIL dequantize {p["key"]}: {r.stderr.strip()[-300:]}')
                continue
        print(f'  decoded {p["key"]}.glb ({os.path.getsize(dst) / 1e6:.1f} MB)')
    return ok


# --------------------------------------------------------------------------------------------- GLB reading

_COMP = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
_NCOMP = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT4': 16}


def read_glb(path):
    data = open(path, 'rb').read()
    magic, _ver, length = struct.unpack_from('<4sII', data, 0)
    if magic != b'glTF':
        raise ValueError(f'{path}: not a GLB')
    off, gltf, binc = 12, None, b''
    while off < length:
        clen, ctype = struct.unpack_from('<I4s', data, off)
        off += 8
        chunk = data[off:off + clen]
        off += clen
        if ctype == b'JSON':
            gltf = json.loads(chunk)
        elif ctype == b'BIN\x00':
            binc = chunk
    return gltf, binc


def _view_bytes(gltf, binc, bv_index):
    bv = gltf['bufferViews'][bv_index]
    if 'extensions' in bv and 'EXT_meshopt_compression' in bv['extensions']:
        raise ValueError('meshopt-compressed buffer view: run the decode step first')
    o = bv.get('byteOffset', 0)
    return binc[o:o + bv['byteLength']], bv.get('byteStride')


def read_accessor(gltf, binc, index):
    acc = gltf['accessors'][index]
    dt = np.dtype(_COMP[acc['componentType']])
    n = _NCOMP[acc['type']]
    count = acc['count']
    raw, stride = _view_bytes(gltf, binc, acc['bufferView'])
    o = acc.get('byteOffset', 0)
    item = dt.itemsize * n
    stride = stride or item
    buf = np.frombuffer(raw, dtype=np.uint8, count=stride * (count - 1) + item, offset=o)
    rows = np.lib.stride_tricks.as_strided(buf, shape=(count, item), strides=(stride, 1))
    arr = np.ascontiguousarray(rows).view(dt).reshape(count, n).astype(np.float64)
    if acc.get('normalized'):
        arr /= float(np.iinfo(dt).max)
        arr = np.maximum(arr, -1.0)
    return arr


def _node_matrix(node):
    if 'matrix' in node:
        return np.array(node['matrix'], dtype=np.float64).reshape(4, 4).T
    t = np.array(node.get('translation', [0, 0, 0]), dtype=np.float64)
    x, y, z, w = node.get('rotation', [0, 0, 0, 1])
    s = np.array(node.get('scale', [1, 1, 1]), dtype=np.float64)
    r = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                  [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                  [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
    m = np.eye(4)
    m[:3, :3] = r * s
    m[:3, 3] = t
    return m


def _mesh_instances(gltf):
    """(mesh index, world matrix) for every node that carries a mesh, from the default scene."""
    out = []
    scene = gltf.get('scenes', [{}])[gltf.get('scene', 0)] if gltf.get('scenes') else {'nodes': list(range(len(gltf.get('nodes', []))))}

    def visit(i, parent):
        node = gltf['nodes'][i]
        m = parent @ _node_matrix(node)
        if 'mesh' in node:
            out.append((node['mesh'], m))
        for c in node.get('children', []):
            visit(c, m)
    for i in scene.get('nodes', []):
        visit(i, np.eye(4))
    return out


def image_size(content):
    from PIL import Image
    im = Image.open(io.BytesIO(content))
    return im.size, im.mode


def glb_stats(path):
    gltf, binc = read_glb(path)
    tris = verts = 0
    lo, hi = np.full(3, np.inf), np.full(3, -np.inf)
    for mesh_i, m in _mesh_instances(gltf):
        for prim in gltf['meshes'][mesh_i]['primitives']:
            if prim.get('mode', 4) != 4:
                continue
            pos = read_accessor(gltf, binc, prim['attributes']['POSITION'])
            verts += len(pos)
            tris += (gltf['accessors'][prim['indices']]['count'] if 'indices' in prim else len(pos)) // 3
            w = pos @ m[:3, :3].T + m[:3, 3]
            lo, hi = np.minimum(lo, w.min(0)), np.maximum(hi, w.max(0))
    # roles from the materials
    roles = {}
    for mat in gltf.get('materials', []):
        pbr = mat.get('pbrMetallicRoughness', {})
        for role, ref in (('base_color', pbr.get('baseColorTexture')), ('metal_rough', pbr.get('metallicRoughnessTexture')),
                          ('normal', mat.get('normalTexture')), ('occlusion', mat.get('occlusionTexture')),
                          ('emissive', mat.get('emissiveTexture'))):
            if ref is None:
                continue
            tex = gltf['textures'][ref['index']]
            src = tex.get('source')
            for ext in ('EXT_texture_webp', 'KHR_texture_basisu', 'EXT_texture_avif'):
                src = tex.get('extensions', {}).get(ext, {}).get('source', src)
            roles.setdefault(src, []).append(role)
    textures = []
    for i, img in enumerate(gltf.get('images', [])):
        if 'bufferView' not in img:
            textures.append(dict(index=i, role='+'.join(roles.get(i, ['unused'])), uri=img.get('uri')))
            continue
        raw, _ = _view_bytes(gltf, binc, img['bufferView'])
        (w, h), mode = image_size(raw)
        textures.append(dict(index=i, role='+'.join(roles.get(i, ['unused'])), mime=img.get('mimeType'), width=w,
                             height=h, mode=mode, kb=round(len(raw) / 1024)))
    # glTF is Y-up metres. Reported as width (glTF X), depth (glTF Z), height (glTF Y) in cm; UE's importer makes
    # the height its Z. Which of width/depth lands on UE X depends on the importer's axis convention: read the
    # imported bounds rather than assuming.
    size_m = (hi - lo) if np.isfinite(lo).all() else np.zeros(3)
    native_cm = [round(float(size_m[0]) * 100, 1), round(float(size_m[2]) * 100, 1), round(float(size_m[1]) * 100, 1)]
    base_offset_cm = round(float(lo[1]) * 100, 1) if np.isfinite(lo).all() else 0.0
    return dict(tris=int(tris), verts=int(verts), materials=len(gltf.get('materials', [])),
                textures=textures, native_size_cm_wdh=native_cm, min_up_cm=base_offset_cm,
                extensions=sorted(gltf.get('extensionsUsed', [])), generator=gltf.get('asset', {}).get('generator'))


def fbx_stats(path):
    """Same transform path as Tools/ModelReview/review_models.py: model world x geometric, unit scale, Z-up fix."""
    from fbx_reader import read_fbx, model_world_matrix, model_geometric_matrix, axis_to_zup_matrix
    sc = read_fbx(path)
    tris = verts = 0
    lo, hi = np.full(3, np.inf), np.full(3, -np.inf)
    B = axis_to_zup_matrix(sc.global_settings)
    for g in sc.geometries.values():
        _idx, _starts, sizes = g.polygons()
        tris += int(np.maximum(sizes - 2, 0).sum())
        verts += len(g.vertices)
        model = sc.model_of_geometry(g.id)
        M = np.eye(4)
        if model is not None:
            M = model_world_matrix(sc, model) @ model_geometric_matrix(model)
        A = B @ (M[:3, :3] * sc.unit_scale)
        t = B @ (M[:3, 3] * sc.unit_scale)
        v = g.vertices @ A.T + t                                  # cm, Z-up
        lo, hi = np.minimum(lo, v.min(0)), np.maximum(hi, v.max(0))
    textures = []
    for i, vid in enumerate(sc.videos.values()):
        name = os.path.basename(vid.relative_filename or vid.filename or vid.name)
        if not vid.content:
            textures.append(dict(index=i, role=name, external=True))
            continue
        (w, h), mode = image_size(vid.content)
        textures.append(dict(index=i, role=name, width=w, height=h, mode=mode, kb=round(len(vid.content) / 1024)))
    size = hi - lo
    return dict(tris=tris, verts=verts, materials=len(sc.materials), textures=textures,
                native_size_cm_wdh=[round(float(x), 1) for x in size], min_up_cm=round(float(lo[2]), 1),
                extensions=[], generator=f'FBX {sc.version}')


# --------------------------------------------------------------------------------------------- stats + manifest

def _import_scale(p, native):
    """Uniform scale that brings the file (native = w, d, h cm) to the planned real-world size (x, y, z m):
    largest axis to largest axis, or height to height when the row's scale_basis is 'h'."""
    real = p.get('real_size_m')
    if not real or not native or max(native) <= 0:
        return None
    if p.get('scale_basis') == 'h' and native[2] > 0:
        return round(real[2] * 100.0 / native[2], 3)
    return round(max(real) * 100.0 / max(native), 3)


def stats(args):
    rows, total_tris, total_mb = [], 0, 0.0
    for p in load_projects():
        d = key_dir(p['key'])
        files = os.listdir(d)
        decoded = p['key'] + '.glb'
        src = next((f for f in files if f.endswith('_meshopt.glb')), None) or next((f for f in files if f.lower().endswith('.fbx')), None)
        use = decoded if decoded in files else src
        row = dict(p)
        row['source_file'] = f'SourceArt/Tripo/{p["key"]}/{src}' if src else None
        row['file'] = f'SourceArt/Tripo/{p["key"]}/{use}' if use else None
        row['preview'] = f'SourceArt/Tripo/{p["key"]}/preview.webp' if 'preview.webp' in files else None
        if not use:
            row['status'] = 'missing'
            rows.append(row)
            continue
        path = os.path.join(d, use)
        try:
            s = glb_stats(path) if use.endswith('.glb') else fbx_stats(path)
        except Exception as e:  # noqa: BLE001 - report and keep going
            row['status'] = f'error: {e}'
            rows.append(row)
            continue
        row.update(s)
        if len(s['textures']) > 12:     # the segmented older models carry hundreds of small maps: summarise them
            summary = {}
            for t in s['textures']:
                k = f'{t["role"]} {t.get("width")}x{t.get("height")}'
                summary[k] = summary.get(k, 0) + 1
            row['textures'] = [dict(role=k.split(' ')[0], size=k.split(' ')[1], count=n) for k, n in sorted(summary.items())]
            row['texture_count'] = len(s['textures'])
        row['file_mb'] = round(os.path.getsize(path) / 1e6, 2)
        if src and src != use:
            row['source_mb'] = round(os.path.getsize(os.path.join(d, src)) / 1e6, 2)
        row['import_scale'] = _import_scale(p, s['native_size_cm_wdh'])
        ue = p['key'] + '_ue.glb'
        if ue in files:
            su = glb_stats(os.path.join(d, ue))
            row['import_file'] = f'SourceArt/Tripo/{p["key"]}/{ue}'
            row['import_mb'] = round(os.path.getsize(os.path.join(d, ue)) / 1e6, 2)
            row['import_size_cm_wdh'] = su['native_size_cm_wdh']
            row['import_textures'] = sorted({f'{t.get("width")}x{t.get("height")}' for t in su['textures']})
        row['max_texture'] = max([max(t.get('width', 0), t.get('height', 0)) for t in s['textures']] or [0])
        row['needs_texture_cap'] = row['max_texture'] > TEX_CAP
        row['status'] = 'ok'
        total_tris += s['tris']
        total_mb += row['file_mb']
        rows.append(row)
    doc = dict(
        generated_by='Tools/Tripo/tripo_ingest.py stats',
        source='studio.tripo3d.ai workspace (37 projects), model_url of each project; no credits spent',
        files='source_file = as served by the Studio; file = meshopt decoded + dequantized (stats are for it); '
              'import_file = pivot at base, import_scale baked, textures <= 2048, packed ORM (import this one)',
        units='native_size_cm_wdh = width (glTF X), depth (glTF Z), height (glTF Y, UE Z) in cm at scale 1, before import_scale; FBX rows use the file axes after the Z-up fix',
        import_plan='Tools/Tripo/IMPORT.md',
        totals=dict(models=len(rows), ok=sum(r.get('status') == 'ok' for r in rows), tris=total_tris,
                    file_mb=round(total_mb, 1),
                    use=sum(r.get('verdict') == 'use' for r in rows),
                    use_tris=sum(r.get('tris', 0) for r in rows if r.get('verdict') == 'use'),
                    import_mb=round(sum(r.get('import_mb', 0) for r in rows), 1)),
        models=rows)
    with open(MANIFEST, 'w', encoding='utf8') as fh:
        json.dump(doc, fh, indent=1)
        fh.write('\n')
    print(f'wrote {MANIFEST}: {doc["totals"]}')
    for r in rows:
        tex = ', '.join(f'{t.get("width")}x{t.get("height")} {t["role"]}' for t in r.get('textures', []))
        print(f'  {r["key"]:<28} {r.get("status"):<6} {r.get("tris", 0):>8,} tris  {r.get("file_mb", 0):>6} MB  '
              f'{r.get("native_size_cm_wdh")}  x{r.get("import_scale")}  [{tex}]')
    return all(r.get('status') == 'ok' for r in rows)


# --------------------------------------------------------------------------------------------- import-ready GLB

def write_glb(path, gltf, binc):
    js = json.dumps(gltf, separators=(',', ':')).encode('utf8')
    js += b' ' * (-len(js) % 4)
    binc += b'\x00' * (-len(binc) % 4)
    total = 12 + 8 + len(js) + (8 + len(binc) if binc else 0)
    with open(path, 'wb') as fh:
        fh.write(struct.pack('<4sII', b'glTF', 2, total))
        fh.write(struct.pack('<I4s', len(js), b'JSON') + js)
        if binc:
            fh.write(struct.pack('<I4s', len(binc), b'BIN\x00') + binc)


def _rebuild_buffer(gltf, binc, replace):
    """Re-pack every bufferView into one buffer; `replace` maps bufferView index -> new bytes."""
    out = bytearray()
    for i, bv in enumerate(gltf['bufferViews']):
        o = bv.get('byteOffset', 0)
        data = replace.get(i, binc[o:o + bv['byteLength']])
        out += b'\x00' * (-len(out) % 4)
        bv['byteOffset'] = len(out)
        bv['byteLength'] = len(data)
        bv['buffer'] = 0
        out += data
    gltf['buffers'] = [{'byteLength': len(out)}]
    return bytes(out)


def _encode(im, mime):
    b = io.BytesIO()
    if mime == 'image/jpeg':
        im.convert('RGB').save(b, 'JPEG', quality=93, subsampling=0)
    else:
        im.save(b, 'PNG', optimize=False, compress_level=6)
        mime = 'image/png'
    return b.getvalue(), mime


def prep_one(p, src, dst):
    """Pivot at the base centre, uniform scale to the planned real size, textures <= TEX_CAP, packed ORM,
    no webp (UE's glTF importer reads PNG/JPEG). Writes a plain GLB the editor imports at scale 1."""
    from PIL import Image
    gltf, binc = read_glb(src)
    # bounds in the file's own space (Y-up metres)
    lo, hi = np.full(3, np.inf), np.full(3, -np.inf)
    for mesh_i, m in _mesh_instances(gltf):
        for prim in gltf['meshes'][mesh_i]['primitives']:
            pos = read_accessor(gltf, binc, prim['attributes']['POSITION'])
            w = pos @ m[:3, :3].T + m[:3, 3]
            lo, hi = np.minimum(lo, w.min(0)), np.maximum(hi, w.max(0))
    size_m = hi - lo
    native_cm = [size_m[0] * 100, size_m[2] * 100, size_m[1] * 100]
    s = _import_scale(p, native_cm) or 1.0
    cx, cz = (lo[0] + hi[0]) / 2, (lo[2] + hi[2]) / 2
    scene_i = gltf.get('scene', 0)
    scene = gltf['scenes'][scene_i]
    gltf['nodes'].append({'name': 'SM_T2_' + p.get('t2', p['key']), 'children': scene['nodes'], 'scale': [s, s, s],
                          'translation': [float(-cx * s), float(-lo[1] * s), float(-cz * s)]})
    scene['nodes'] = [len(gltf['nodes']) - 1]

    # images: decode once, cap, pack ORM, re-encode
    imgs = {}
    for i, img in enumerate(gltf.get('images', [])):
        raw, _ = _view_bytes(gltf, binc, img['bufferView'])
        imgs[i] = Image.open(io.BytesIO(raw))
        imgs[i].load()
    tex_src = []
    for tex in gltf.get('textures', []):
        src_i = tex.get('source')
        for ext in ('EXT_texture_webp',):
            if ext in tex.get('extensions', {}):
                src_i = tex['extensions'][ext]['source']
                del tex['extensions'][ext]
        if 'extensions' in tex and not tex['extensions']:
            del tex['extensions']
        tex['source'] = src_i
        tex_src.append(src_i)
    for mat in gltf.get('materials', []):
        pbr = mat.get('pbrMetallicRoughness', {})
        mr, occ = pbr.get('metallicRoughnessTexture'), mat.get('occlusionTexture')
        if mr is None:
            continue
        mr_i = tex_src[mr['index']]
        orm = imgs[mr_i].convert('RGB')
        r = Image.new('L', orm.size, 255)
        if occ is not None and tex_src[occ['index']] != mr_i:
            r = imgs[tex_src[occ['index']]].convert('L').resize(orm.size, Image.LANCZOS)
        _, g, b = orm.split()
        imgs[mr_i] = Image.merge('RGB', (r, g, b))
        mat['occlusionTexture'] = {'index': mr['index'], 'texCoord': mr.get('texCoord', 0)}
    replace = {}
    for i, img in enumerate(gltf.get('images', [])):
        im = imgs[i]
        if max(im.size) > TEX_CAP:
            f = TEX_CAP / max(im.size)
            im = im.resize((max(1, round(im.width * f)), max(1, round(im.height * f))), Image.LANCZOS)
        mime = img.get('mimeType', 'image/png')
        data, mime = _encode(im, 'image/jpeg' if mime == 'image/jpeg' else 'image/png')
        img['mimeType'] = mime
        replace[img['bufferView']] = data
    for k in ('extensionsUsed', 'extensionsRequired'):
        if k in gltf:
            gltf[k] = [e for e in gltf[k] if e not in ('EXT_texture_webp', 'EXT_meshopt_compression')]
            if not gltf[k]:
                del gltf[k]
    binc = _rebuild_buffer(gltf, binc, replace)
    write_glb(dst, gltf, binc)
    return s


def prep(args):
    ok = True
    for p in load_projects():
        d = key_dir(p['key'])
        src = os.path.join(d, p['key'] + '.glb')
        if not os.path.exists(src):
            continue
        dst = os.path.join(d, p['key'] + '_ue.glb')
        if os.path.exists(dst) and not args.force:
            print(f'  have {p["key"]}_ue.glb')
            continue
        try:
            s = prep_one(p, src, dst)
            st = glb_stats(dst)
            print(f'  prepped {p["key"]}_ue.glb x{s}: {st["native_size_cm_wdh"]} cm, base {st["min_up_cm"]} cm, '
                  f'{os.path.getsize(dst) / 1e6:.1f} MB')
        except Exception as e:  # noqa: BLE001
            ok = False
            print(f'  FAIL prep {p["key"]}: {e}')
    return ok


# --------------------------------------------------------------------------------------------- contact sheet

def contact(args):
    from PIL import Image, ImageDraw, ImageFont
    projects = load_projects()
    manifest = {}
    if os.path.exists(MANIFEST):
        manifest = {m['key']: m for m in json.load(open(MANIFEST, encoding='utf8'))['models']}
    cols, cell, pad, label_h = 7, 300, 8, 58
    rows_n = (len(projects) + cols - 1) // cols
    W = cols * (cell + pad) + pad
    H = 70 + rows_n * (cell + label_h + pad) + pad
    sheet = Image.new('RGB', (W, H), (24, 22, 20))
    dr = ImageDraw.Draw(sheet)

    def font(sz, bold=False):
        for f in (('arialbd.ttf' if bold else 'arial.ttf'), 'DejaVuSans.ttf'):
            try:
                return ImageFont.truetype(os.path.join('C:/Windows/Fonts', f) if os.name == 'nt' else f, sz)
            except OSError:
                continue
        return ImageFont.load_default()
    f_title, f_name, f_small = font(26, True), font(15, True), font(13)
    total = sum(m.get('tris', 0) for m in manifest.values())
    dr.text((pad + 4, 18), f'Tripo Studio models on this PC: {len(projects)} projects, {total:,} triangles '
                           f'(SourceArt/Tripo, manifest.json)', fill=(236, 226, 206), font=f_title)
    for i, p in enumerate(projects):
        cx, cy = pad + (i % cols) * (cell + pad), 70 + (i // cols) * (cell + label_h + pad)
        dr.rectangle([cx, cy, cx + cell - 1, cy + cell - 1], fill=(44, 40, 36))
        pv = os.path.join(OUT, p['key'], 'preview.webp')
        if os.path.exists(pv):
            im = Image.open(pv).convert('RGBA')
            im.thumbnail((cell, cell), Image.LANCZOS)
            bg = Image.new('RGBA', (cell, cell), (44, 40, 36, 255))
            bg.alpha_composite(im, ((cell - im.width) // 2, (cell - im.height) // 2))
            sheet.paste(bg.convert('RGB'), (cx, cy))
        else:
            dr.text((cx + 10, cy + cell // 2), 'no preview', fill=(160, 150, 140), font=f_small)
        m = manifest.get(p['key'], {})
        tex = m.get('max_texture') or 0
        dr.text((cx + 2, cy + cell + 4), f'{i + 1:02d} {p["key"]}'[:34], fill=(236, 226, 206), font=f_name)
        meta = f'{m.get("tris", 0):,} tris  {tex}px  {p.get("slot", "")}'
        dr.text((cx + 2, cy + cell + 24), meta[:44], fill=(190, 178, 160), font=f_small)
        use = p.get('verdict', '')
        dr.text((cx + 2, cy + cell + 40), use[:44], fill=(150, 170, 140) if use.startswith('use') else (200, 150, 120), font=f_small)
    sheet.save(CONTACT, optimize=True)
    print(f'wrote {CONTACT} ({W}x{H})')
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('step', choices=['resolve', 'download', 'decode', 'prep', 'stats', 'contact', 'all'])
    ap.add_argument('--force', action='store_true', help='redo files that already exist')
    ap.add_argument('--keep-quantized', action='store_true', help='decode: keep KHR_mesh_quantization attributes')
    args = ap.parse_args()
    steps = {'resolve': resolve, 'download': download, 'decode': decode, 'prep': prep, 'stats': stats, 'contact': contact}
    order = ['resolve', 'download', 'decode', 'prep', 'stats', 'contact'] if args.step == 'all' else [args.step]
    ok = True
    for s in order:
        print(f'== {s}')
        ok = steps[s](args) and ok
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
