import gzip, struct, json, sys, numpy as np
def load_spz(path):
    d = gzip.open(path).read()
    magic, ver, n, sh, fb, flags, _ = struct.unpack('<IIIBBBB', d[:16]); o = 16
    p = np.frombuffer(d, np.uint8, 9*n, o).reshape(n, 3, 3).astype(np.int32); o += 9*n
    pos = (p[..., 0] | (p[..., 1] << 8) | (p[..., 2] << 16)); pos = np.where(pos & 0x800000, pos - (1 << 24), pos) / float(1 << fb)
    a = np.frombuffer(d, np.uint8, n, o).astype(np.float32) / 255.0; o += n
    col = np.frombuffer(d, np.uint8, 3*n, o).reshape(n, 3).astype(np.float32) / 255.0; o += 3*n
    col = 0.5 + ((col - 0.5) / 0.15) * 0.28209479   # spz colour -> SH DC -> rgb
    sc = np.exp(np.frombuffer(d, np.uint8, 3*n, o).reshape(n, 3).astype(np.float32) / 16.0 - 10.0); o += 3*n
    return pos, np.clip(col, 0, 1), a, sc
def main(src, dst, k=1.0, mx=340000):
    pos, col, a, sc = load_spz(src)
    ue = np.stack([-pos[:, 2], pos[:, 0], pos[:, 1]], 1) * 100.0 * k   # RUB metres -> UE cm, scaled to walkable size
    sig = np.cbrt(np.prod(sc, 1)) * 0.6 + sc.max(1) * 0.4
    keep = (a > 0.2) & (sig <= np.percentile(sig, 99.0))
    ue, col, a, sig = ue[keep], col[keep], a[keep], sig[keep]
    c = np.median(ue, 0); r = np.linalg.norm((ue - c)[:, :2], axis=1)
    keep = r <= np.percentile(r, 96); ue, col, a, sig = ue[keep], col[keep], a[keep], sig[keep]
    floor = np.percentile(ue[:, 2], 3)
    ue = ue - np.array([np.median(ue[:, 0]), np.median(ue[:, 1]), floor])
    if len(ue) > mx:
        score = a / np.sqrt(sig / np.median(sig))   # opaque and fine first: fine detail over big blur blobs
        idx = np.argsort(-score)[:mx]; ue, col, a, sig = ue[idx], col[idx], a[idx], sig[idx]
    size = np.clip(sig * 100.0 * k * 1.7, 1.5, 250.0)
    n = len(ue); corners = np.array([[-1, -1], [1, -1], [1, 1], [-1, 1]], np.float32)
    P = (ue[:, None, :] + np.concatenate([corners * 4.0, np.zeros((4, 1))], 1)[None]).reshape(-1, 3).astype(np.float32)
    G = np.stack([P[:, 0], P[:, 2], -P[:, 1]], 1).astype(np.float32) / 100.0
    C = np.concatenate([np.repeat(col ** 2.2, 4, 0), np.repeat(a, 4)[:, None]], 1).astype(np.float32)
    UV0 = np.tile(corners * 0.5 + 0.5, (n, 1)).astype(np.float32)
    # UV1: size, and a stable per-splat random (drives the hallucination motion)
    rnd = np.random.default_rng(7).random(n).astype(np.float32)
    UV1 = np.stack([np.repeat(size, 4), np.repeat(rnd, 4)], 1).astype(np.float32)
    lum = col @ np.array([0.2126, 0.7152, 0.0722])
    col = np.clip(col / max(np.percentile(lum, 97), 1e-3) * 0.9, 0, 1) ** 0.85   # auto-level the (very dark) Marble scenes
    lin = col ** 2.2
    UV2 = np.stack([np.repeat(lin[:, 0], 4), np.repeat(lin[:, 1], 4)], 1).astype(np.float32)   # colour R,G
    UV3 = np.stack([np.repeat(lin[:, 2], 4), np.repeat(a, 4)], 1).astype(np.float32)          # colour B, opacity
    I = ((np.arange(n) * 4)[:, None] + np.array([0, 1, 2, 0, 2, 3])).reshape(-1).astype(np.uint32)
    blobs = [G.tobytes(), UV0.tobytes(), UV1.tobytes(), UV2.tobytes(), UV3.tobytes(), I.tobytes()]; offs, buf = [], b''
    for b in blobs:
        offs.append(len(buf)); buf += b; buf += b'\0' * ((4 - len(buf) % 4) % 4)
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
    print(dst.split('/')[-1], 'splats', n, 'extent_m', np.round(ext / 100, 1).tolist(), 'size_cm_med', round(float(np.median(size)), 1))
import os
H = os.path.expanduser('~/mnt/saskartarad/')
S = H + 'SourceArt/Splats/'
for src, name, k in [('250822b0-Abandoned_Train_Tunnel.spz', 'DREAM_1_TrainTunnel', 4.0), ('b0f170c8-Futuristic_Space_Station_Interior.spz', 'DREAM_2_SpaceStation', 5.0), ('59cc767c-Ruined_Sanctuary_Apocalyptic_Aftermath.spz', 'DREAM_3_Sanctuary', 1.3)]:
    main(S + 'src/' + src, S + name + '.glb', k)
