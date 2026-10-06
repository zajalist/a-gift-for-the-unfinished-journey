"""Read-only GLB front-ray survey of the approved S26 relay tower.

Uses the standard GLB position/index buffers; it never opens Blender or
modifies the source. Coordinates printed below are Blender-style metres before
real-world scaling: X across the facade, Y toward the back, Z vertical.
"""

from __future__ import annotations

import argparse
import json
import mmap
import struct
from pathlib import Path

import numpy as np


def glb_arrays(path: Path):
    handle = path.open('rb')
    blob = mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ)
    magic, version, total, json_size, json_type = struct.unpack_from('<5I', blob, 0)
    assert magic == 0x46546C67 and version == 2 and total == len(blob)
    assert json_type == 0x4E4F534A
    data = json.loads(blob[20:20 + json_size])
    assert len(data['meshes']) == 1 and len(data['meshes'][0]['primitives']) == 1
    primitive = data['meshes'][0]['primitives'][0]
    assert len(data['nodes']) == 1 and data['nodes'][0].get('mesh') == 0
    binary_header = 20 + json_size
    binary_size, binary_type = struct.unpack_from('<2I', blob, binary_header)
    assert binary_type == 0x004E4942
    binary_start = binary_header + 8
    assert binary_start + binary_size <= len(blob)

    def array(accessor_id, kind, components):
        accessor = data['accessors'][accessor_id]
        view = data['bufferViews'][accessor['bufferView']]
        assert accessor.get('byteOffset', 0) == 0 and 'byteStride' not in view
        assert accessor['componentType'] == kind
        size = accessor['count'] * components
        offset = binary_start + view.get('byteOffset', 0)
        dtype = np.float32 if kind == 5126 else np.uint32
        assert size * np.dtype(dtype).itemsize <= view['byteLength']
        return np.frombuffer(blob, dtype=dtype, count=size, offset=offset).reshape(-1, components)

    positions = array(primitive['attributes']['POSITION'], 5126, 3)
    indices = array(primitive['indices'], 5125, 1).reshape(-1, 3)
    return handle, blob, positions, indices


def candidates(positions, indices, x_min=-.22, x_max=.22, z_min=-.45, z_max=-.10):
    """Keep triangles whose X/vertical AABB touches the proposed portal."""
    parts = []
    for start in range(0, len(indices), 100_000):
        tri = positions[indices[start:start + 100_000]]
        x = tri[:, :, 0]
        z = tri[:, :, 1]  # glTF Y becomes Blender Z
        keep = ((x.min(axis=1) <= x_max) & (x.max(axis=1) >= x_min)
                & (z.min(axis=1) <= z_max) & (z.max(axis=1) >= z_min))
        if keep.any():
            parts.append(tri[keep].copy())
    return np.concatenate(parts, axis=0) if parts else np.empty((0, 3, 3), np.float32)


def front_hits(tri, x: float, z: float):
    """All intersections on an X/height ray; larger glTF Z is nearer front."""
    ax, ay, az = tri[:, 0, 0], tri[:, 0, 1], tri[:, 0, 2]
    bx, by, bz = tri[:, 1, 0], tri[:, 1, 1], tri[:, 1, 2]
    cx, cy, cz = tri[:, 2, 0], tri[:, 2, 1], tri[:, 2, 2]
    den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
    valid = np.abs(den) > 1e-11
    u = np.zeros(len(tri), np.float32)
    v = np.zeros(len(tri), np.float32)
    u[valid] = ((by[valid] - cy[valid]) * (x - cx[valid])
                + (cx[valid] - bx[valid]) * (z - cy[valid])) / den[valid]
    v[valid] = ((cy[valid] - ay[valid]) * (x - cx[valid])
                + (ax[valid] - cx[valid]) * (z - cy[valid])) / den[valid]
    inside = valid & (u >= -1e-6) & (v >= -1e-6) & (u + v <= 1 + 1e-6)
    depth = u[inside] * az[inside] + v[inside] * bz[inside]
    depth += (1 - u[inside] - v[inside]) * cz[inside]
    return sorted((-float(p) for p in depth), reverse=False)  # Blender Y=-glTF Z; front first


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('glb', type=Path)
    args = parser.parse_args()
    handle, blob, positions, indices = glb_arrays(args.glb)
    try:
        tri = candidates(positions, indices)
        print(json.dumps({'vertices': len(positions), 'triangles': len(indices),
                          'portal_candidate_triangles': len(tri),
                          'gltf_bounds': [positions.min(axis=0).tolist(), positions.max(axis=0).tolist()]}))
        for z in (-.43, -.38, -.32, -.25, -.18):
            row = []
            for x in (-.12, -.06, 0, .06, .12):
                hits = front_hits(tri, x, z)
                row.append({'x': x, 'front_y': round(hits[0], 4) if hits else None,
                            'hits': len(hits), 'back_y': round(hits[-1], 4) if hits else None})
            print(json.dumps({'blender_z': z, 'row': row}))
    finally:
        del positions, indices
        blob.close()
        handle.close()


if __name__ == '__main__':
    main()
