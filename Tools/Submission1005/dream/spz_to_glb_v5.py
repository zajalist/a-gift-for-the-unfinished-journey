"""Submission 2026-10-05 v5: oriented (anisotropic) Gaussian surfels from Marble SPZ, optional terrain drape.

Each splat becomes a flat quad spanning +-3 sigma along its two largest principal axes (so the material's
exp(-4.5 r^2) falloff is the true Gaussian). Positions are final object-space (cm); no camera billboard.
UV0 corner (0..1), UV1 (size_cm, rnd), UV2 (r,g linear), UV3 (b, alpha).
Terrain drape: --terrain <json> with {"origin":[x,y],"step":cm,"nx":..,"ny":..,"z":[...row-major y*nx+x],
"actor":{"loc":[x,y,z],"yaw":deg,"scale":s}}: splats whose world Z falls below the terrain are moved onto it
(+2 cm) and laid flat along the ground.
"""
import gzip, struct, json, sys, os, numpy as np

def load_spz(path):
    d = gzip.open(path).read()
    magic, ver, n, sh, fb, flags, _ = struct.unpack('<IIIBBBB', d[:16]); o = 16
    p = np.frombuffer(d, np.uint8, 9*n, o).reshape(n, 3, 3).astype(np.int32); o += 9*n
    pos = (p[..., 0] | (p[..., 1] << 8) | (p[..., 2] << 16)); pos = np.where(pos & 0x800000, pos - (1 << 24), pos) / float(1 << fb)
    a = np.frombuffer(d, np.uint8, n, o).astype(np.float32) / 255.0; o += n
    col = np.frombuffer(d, np.uint8, 3*n, o).reshape(n, 3).astype(np.float32) / 255.0; o += 3*n
    col = 0.5 + ((col - 0.5) / 0.15) * 0.28209479
    sc = np.exp(np.frombuffer(d, np.uint8, 3*n, o).reshape(n, 3).astype(np.float32) / 16.0 - 10.0); o += 3*n
    if ver >= 3:
        q = np.frombuffer(d, np.uint8, 4*n, o).reshape(n, 4); o += 4*n
        # smallest-three: 2 bits index, 3 x 10 bits (+sign); fall back to treating as xyzw bytes
        qq = q.astype(np.float32) / 127.5 - 1.0; quat = qq
    else:
        r = np.frombuffer(d, np.uint8, 3*n, o).reshape(n, 3).astype(np.float32) / 127.5 - 1.0; o += 3*n
        w = np.sqrt(np.clip(1.0 - (r*r).sum(1), 0, 1))
        quat = np.concatenate([r, w[:, None]], 1)   # x y z w
    quat = quat / np.linalg.norm(quat, axis=1, keepdims=True).clip(1e-6)
    return pos, np.clip(col, 0, 1), a, sc, quat, ver

def quat_mat(q):
    x, y, z, w = q[:, 0], q[:, 1], q[:, 2], q[:, 3]
    return np.stack([
        np.stack([1-2*(y*y+z*z), 2*(x*y-w*z), 2*(x*z+w*y)], -1),
        np.stack([2*(x*y+w*z), 1-2*(x*x+z*z), 2*(y*z-w*x)], -1),
        np.stack([2*(x*z-w*y), 2*(y*z+w*x), 1-2*(x*x+y*y)], -1)], 1)   # rows -> R[n,3,3]

def to_ue(v):   # RUB -> UE (forward=-back, right, up)
    return np.stack([-v[..., 2], v[..., 0], v[..., 1]], -1)

def main(src, dst, k=1.0, mx=460000, terrain=None, lum_pct=97):
    pos, col, a, sc, quat, ver = load_spz(src)
    keep = (a > 0.08)
    sig = np.cbrt(np.prod(sc, 1)); keep &= sig <= np.percentile(sig[keep], 99.5)
    pos, col, a, sc, quat = pos[keep], col[keep], a[keep], sc[keep], quat[keep]
    ue = to_ue(pos) * 100.0 * k
    c = np.median(ue, 0); r = np.linalg.norm((ue - c)[:, :2], axis=1)
    keep = r <= np.percentile(r, 97.5)
    ue, col, a, sc, quat = ue[keep], col[keep], a[keep], sc[keep], quat[keep]
    floor = np.percentile(ue[:, 2], 3)
    ue = ue - np.array([np.median(ue[:, 0]), np.median(ue[:, 1]), floor])
    if len(ue) > mx:
        s = np.cbrt(np.prod(sc, 1)); score = a / np.sqrt(s / np.median(s))
        idx = np.argsort(-score)[:mx]; ue, col, a, sc, quat = ue[idx], col[idx], a[idx], sc[idx], quat[idx]
    n = len(ue)
    R = quat_mat(quat)                                  # columns are the local axes in RUB
    order = np.argsort(-sc, 1)                          # largest two axes
    ax = np.take_along_axis(R, order[:, None, :].repeat(3, 1), 2)   # [n,3,3] columns sorted
    s = np.take_along_axis(sc, order, 1)
    A1 = to_ue(ax[:, :, 0]) * (s[:, 0:1] * 100.0 * k * 3.0)
    A2 = to_ue(ax[:, :, 1]) * (np.maximum(s[:, 1:2], s[:, 0:1] * 0.18) * 100.0 * k * 3.0)
    # cap giant smears
    m1 = np.linalg.norm(A1, axis=1, keepdims=True); A1 *= np.minimum(1.0, 300.0 / np.maximum(m1, 1e-3))
    m2 = np.linalg.norm(A2, axis=1, keepdims=True); A2 *= np.minimum(1.0, 300.0 / np.maximum(m2, 1e-3))
    drape = np.zeros(n, bool)
    if terrain:
        T = json.load(open(terrain)); act = T['actor']; yaw = np.radians(act['yaw']); scl = act.get('scale', 1.0)
        cy, sy = np.cos(yaw), np.sin(yaw)
        wx = act['loc'][0] + (ue[:, 0]*cy - ue[:, 1]*sy) * scl
        wy = act['loc'][1] + (ue[:, 0]*sy + ue[:, 1]*cy) * scl
        wz = act['loc'][2] + ue[:, 2] * scl
        gx = (wx - T['origin'][0]) / T['step']; gy = (wy - T['origin'][1]) / T['step']
        Z = np.array(T['z'], np.float32).reshape(T['ny'], T['nx'])
        ix = np.clip(np.floor(gx).astype(int), 0, T['nx']-2); iy = np.clip(np.floor(gy).astype(int), 0, T['ny']-2)
        fx = np.clip(gx - ix, 0, 1); fy = np.clip(gy - iy, 0, 1)
        tz = (Z[iy, ix]*(1-fx)*(1-fy) + Z[iy, ix+1]*fx*(1-fy) + Z[iy+1, ix]*(1-fx)*fy + Z[iy+1, ix+1]*fx*fy)
        valid = tz > -1e8
        drape = valid & (wz < tz + 2.0)
        ue[drape, 2] = (tz[drape] + 2.0 + np.random.default_rng(3).random(drape.sum()) * 3.0 - act['loc'][2]) / scl
        # lay draped splats flat (ground plane), keep their footprint
        L1 = np.linalg.norm(A1[drape], axis=1); L2 = np.linalg.norm(A2[drape], axis=1)
        ang = np.random.default_rng(5).random(drape.sum()) * np.pi
        A1[drape] = np.stack([np.cos(ang)*L1, np.sin(ang)*L1, np.zeros_like(L1)], 1)
        A2[drape] = np.stack([-np.sin(ang)*L2, np.cos(ang)*L2, np.zeros_like(L2)], 1)
        print('  draped', int(drape.sum()), 'of', n)
    corners = np.array([[-1, -1], [1, -1], [1, 1], [-1, 1]], np.float32)
    P = ue[:, None, :] + corners[None, :, 0:1] * A1[:, None, :] + corners[None, :, 1:2] * A2[:, None, :]
    P = P.reshape(-1, 3).astype(np.float32)
    G = np.stack([P[:, 0], P[:, 2], -P[:, 1]], 1).astype(np.float32) / 100.0      # UE cm -> glTF m (Y up)
    UV0 = np.tile(corners * 0.5 + 0.5, (n, 1)).astype(np.float32)
    rnd = np.random.default_rng(7).random(n).astype(np.float32)
    size = np.linalg.norm(A1, axis=1) / 3.0
    UV1 = np.stack([np.repeat(size, 4), np.repeat(rnd, 4)], 1).astype(np.float32)
    lum = col @ np.array([0.2126, 0.7152, 0.0722])
    colL = np.clip(col / max(np.percentile(lum, lum_pct), 1e-3) * 0.9, 0, 1) ** 0.85
    lin = colL ** 2.2
    UV2 = np.stack([np.repeat(lin[:, 0], 4), np.repeat(lin[:, 1], 4)], 1).astype(np.float32)
    UV3 = np.stack([np.repeat(lin[:, 2], 4), np.repeat(a, 4)], 1).astype(np.float32)
    I = ((np.arange(n) * 4)[:, None] + np.array([0, 1, 2, 0, 2, 3])).reshape(-1).astype(np.uint32)
    blobs = [G.tobytes(), UV0.tobytes(), UV1.tobytes(), UV2.tobytes(), UV3.tobytes(), I.tobytes()]; offs, buf = [], b''
    parts = []
    off = 0
    for b in blobs:
        offs.append(off); pad = (4 - len(b) % 4) % 4; parts.append(b + b'\0'*pad); off += len(b) + pad
    buf = b''.join(parts)
    acc = [{'bufferView': 0, 'componentType': 5126, 'count': len(G), 'type': 'VEC3', 'min': G.min(0).tolist(), 'max': G.max(0).tolist()},
           {'bufferView': 1, 'componentType': 5126, 'count': len(UV0), 'type': 'VEC2'},
           {'bufferView': 2, 'componentType': 5126, 'count': len(UV1), 'type': 'VEC2'},
           {'bufferView': 3, 'componentType': 5126, 'count': len(UV2), 'type': 'VEC2'},
           {'bufferView': 4, 'componentType': 5126, 'count': len(UV3), 'type': 'VEC2'},
           {'bufferView': 5, 'componentType': 5125, 'count': len(I), 'type': 'SCALAR'}]
    gl = {'asset': {'version': '2.0'}, 'scene': 0, 'scenes': [{'nodes': [0]}], 'nodes': [{'mesh': 0, 'name': 'Splats'}],
          'meshes': [{'name': 'Splats', 'primitives': [{'attributes': {'POSITION': 0, 'TEXCOORD_0': 1, 'TEXCOORD_1': 2, 'TEXCOORD_2': 3, 'TEXCOORD_3': 4}, 'indices': 5, 'material': 0}]}],
          'materials': [{'name': 'M_Splat', 'doubleSided': True}], 'buffers': [{'byteLength': len(buf)}],
          'bufferViews': [{'buffer': 0, 'byteOffset': o, 'byteLength': len(b)} for o, b in zip(offs, blobs)], 'accessors': acc}
    js = json.dumps(gl).encode(); js += b' ' * ((4 - len(js) % 4) % 4)
    with open(dst, 'wb') as f:
        f.write(struct.pack('<III', 0x46546C67, 2, 28 + len(js) + len(buf)))
        f.write(struct.pack('<II', len(js), 0x4E4F534A)); f.write(js); f.write(struct.pack('<II', len(buf), 0x004E4942)); f.write(buf)
    ext = ue.max(0) - ue.min(0)
    print(os.path.basename(dst), 'spz v%d' % ver, 'splats', n, 'extent_m', np.round(ext / 100, 1).tolist(), 'axis_cm_med', round(float(np.median(size)), 1))

if __name__ == '__main__':
    H = os.path.expanduser('~/mnt/saskartarad/')
    S = H + 'SourceArt/Splats/'
    for src, name, k in [('250822b0-Abandoned_Train_Tunnel.spz', 'DREAM_1_TrainTunnel', 4.0), ('b0f170c8-Futuristic_Space_Station_Interior.spz', 'DREAM_2_SpaceStation', 5.0), ('59cc767c-Ruined_Sanctuary_Apocalyptic_Aftermath.spz', 'DREAM_3_Sanctuary', 1.3)]:
        t = S + 'terrain_' + name + '.json'
        main(S + 'src/' + src, S + name + '_v5.glb', k, terrain=t if os.path.exists(t) else None)
