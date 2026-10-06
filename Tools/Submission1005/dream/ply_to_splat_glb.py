"""Gaussian-splat PLY (3DGS / World Labs Marble export) -> billboard-splat GLB for Unreal.

    python ply_to_splat_glb.py IN.ply OUT.glb [--max 60000] [--diameter_m 40]

Each Gaussian becomes one quad (4 verts, 2 tris) lying in the local XY plane:
  POSITION   = centre + corner * size   (real quad, so nothing is degenerate on import)
  COLOR_0    = SH-DC colour (linear) + opacity in alpha
  TEXCOORD_0 = corner in [-1,1]^2   (material: gaussian falloff + camera-facing WPO)
  TEXCOORD_1 = (size_cm, 0)
The material M_SplatBillboard rotates every quad to face the camera, so the actor must have
identity rotation and scale 1 (translation is free).
Coordinates: 3DGS/COLMAP (x right, y down, z forward, metres) -> UE (x fwd, y right, z up, cm).
"""
import json, struct, sys
import numpy as np

SH_C0 = 0.28209479177387814

def read_ply(path):
    with open(path, 'rb') as f:
        header = []
        while True:
            line = f.readline().decode('ascii', 'replace').strip()
            header.append(line)
            if line == 'end_header':
                break
        fmt = [l for l in header if l.startswith('format')][0]
        if 'binary_little_endian' not in fmt:
            raise SystemExit('only binary_little_endian PLY supported: ' + fmt)
        n = int([l for l in header if l.startswith('element vertex')][0].split()[-1])
        props = [l.split() for l in header if l.startswith('property')]
        tmap = {'float': 'f4', 'float32': 'f4', 'double': 'f8', 'uchar': 'u1', 'uint8': 'u1',
                'int': 'i4', 'int32': 'i4', 'uint': 'u4', 'short': 'i2', 'ushort': 'u2'}
        dt = np.dtype([(p[2], '<' + tmap[p[1]]) for p in props])
        return np.frombuffer(f.read(n * dt.itemsize), dtype=dt, count=n)

def main():
    a = sys.argv[1:]
    src, dst = a[0], a[1]
    mx = int(a[a.index('--max') + 1]) if '--max' in a else 60000
    diam = float(a[a.index('--diameter_m') + 1]) if '--diameter_m' in a else 40.0
    v = read_ply(src)
    names = v.dtype.names
    pos = np.stack([v['x'], v['y'], v['z']], 1).astype(np.float64)
    if 'f_dc_0' in names:
        col = 0.5 + SH_C0 * np.stack([v['f_dc_0'], v['f_dc_1'], v['f_dc_2']], 1)
    elif 'red' in names:
        col = np.stack([v['red'], v['green'], v['blue']], 1) / 255.0
    else:
        col = np.full((len(v), 3), 0.8)
    col = np.clip(col, 0, 1) ** 2.2   # sRGB-ish -> linear
    op = 1 / (1 + np.exp(-v['opacity'])) if 'opacity' in names else np.ones(len(v))
    if 'scale_0' in names:
        sc = np.exp(np.stack([v['scale_0'], v['scale_1'], v['scale_2']], 1))
        sig = np.cbrt(np.prod(sc, 1)) * 0.6 + sc.max(1) * 0.4
    else:
        sig = np.full(len(v), 0.02)
    # drop near-invisible and huge floaters
    keep = (op > 0.25) & np.isfinite(pos).all(1) & (sig <= np.percentile(sig, 99.5))
    pos, col, op, sig = pos[keep], col[keep], op[keep], sig[keep]
    # centre on the dense core and drop distant outliers
    c = np.median(pos, 0)
    r = np.linalg.norm(pos - c, axis=1)
    keep = r <= np.percentile(r, 97)
    pos, col, op, sig, r = pos[keep], col[keep], op[keep], sig[keep], r[keep]
    # importance: opacity * footprint, keep the top mx
    if len(pos) > mx:
        idx = np.argsort(-(op * sig))[:mx]
        pos, col, op, sig = pos[idx], col[idx], op[idx], sig[idx]
    # COLMAP -> UE axes, scale to the requested diameter
    p = pos - c
    ue = np.stack([p[:, 2], p[:, 0], -p[:, 1]], 1)
    extent = np.percentile(np.linalg.norm(ue, axis=1), 95) * 2
    k = (diam * 100.0) / max(extent, 1e-6)
    ue *= k
    size = np.clip(sig * k * 3.0, 4.0, 400.0)  # 3 sigma in cm
    n = len(ue)
    corners = np.array([[-1, -1], [1, -1], [1, 1], [-1, 1]], np.float32)
    P = (ue[:, None, :] + np.concatenate([corners * 4.0, np.zeros((4, 1))], 1)[None]).reshape(-1, 3).astype(np.float32)  # 8 cm stub quad; the material builds the splat
    # glTF is Y-up right-handed; Interchange converts glTF (x, y, z) -> UE (x, -z, y) style. Pre-convert so UE ends up right:
    # write glTF as (x_ue, z_ue, -y_ue)
    G = np.stack([P[:, 0], P[:, 2], -P[:, 1]], 1).astype(np.float32) / 100.0  # glTF metres
    C = np.concatenate([np.repeat(col, 4, 0), np.repeat(op, 4)[:, None]], 1).astype(np.float32)
    UV0 = np.tile(corners * 0.5 + 0.5, (n, 1)).astype(np.float32)  # 0..1 so a V flip is harmless
    UV1 = np.stack([np.repeat(size, 4), np.zeros(n * 4)], 1).astype(np.float32)
    base = (np.arange(n) * 4)[:, None]
    I = (base + np.array([0, 1, 2, 0, 2, 3])).reshape(-1).astype(np.uint32)
    blobs = [G.tobytes(), C.tobytes(), UV0.tobytes(), UV1.tobytes(), I.tobytes()]
    offs, buf = [], b''
    for b in blobs:
        offs.append(len(buf)); buf += b
        buf += b'\0' * ((4 - len(buf) % 4) % 4)
    views = [{'buffer': 0, 'byteOffset': o, 'byteLength': len(b)} for o, b in zip(offs, blobs)]
    acc = [
        {'bufferView': 0, 'componentType': 5126, 'count': len(G), 'type': 'VEC3', 'min': G.min(0).tolist(), 'max': G.max(0).tolist()},
        {'bufferView': 1, 'componentType': 5126, 'count': len(C), 'type': 'VEC4'},
        {'bufferView': 2, 'componentType': 5126, 'count': len(UV0), 'type': 'VEC2'},
        {'bufferView': 3, 'componentType': 5126, 'count': len(UV1), 'type': 'VEC2'},
        {'bufferView': 4, 'componentType': 5125, 'count': len(I), 'type': 'SCALAR'},
    ]
    gl = {'asset': {'version': '2.0', 'generator': 'saskarta ply_to_splat_glb'},
          'scene': 0, 'scenes': [{'nodes': [0]}], 'nodes': [{'mesh': 0, 'name': 'Splats'}],
          'meshes': [{'name': 'Splats', 'primitives': [{'attributes': {'POSITION': 0, 'COLOR_0': 1, 'TEXCOORD_0': 2, 'TEXCOORD_1': 3}, 'indices': 4, 'material': 0}]}],
          'materials': [{'name': 'M_Splat', 'doubleSided': True}],
          'buffers': [{'byteLength': len(buf)}], 'bufferViews': views, 'accessors': acc}
    js = json.dumps(gl).encode()
    js += b' ' * ((4 - len(js) % 4) % 4)
    with open(dst, 'wb') as f:
        f.write(struct.pack('<III', 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(buf)))
        f.write(struct.pack('<II', len(js), 0x4E4F534A)); f.write(js)
        f.write(struct.pack('<II', len(buf), 0x004E4942)); f.write(buf)
    print(json.dumps({'in': src, 'splats': int(n), 'diameter_cm': float(diam * 100), 'size_cm_median': float(np.median(size)), 'out': dst}))

if __name__ == '__main__':
    main()
