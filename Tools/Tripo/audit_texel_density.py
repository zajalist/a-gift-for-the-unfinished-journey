"""Measure relative UV texel density on a decoded, uncompressed triangle GLB.

Run on the derived tower after UV work, and compare it to the source only after
decoding/dequantizing both. This does not measure visual sharpness or seams.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import struct

import numpy as np


COMPONENT = {5121: np.uint8, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
WIDTH = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}


def read_glb(path: pathlib.Path):
    raw = path.read_bytes()
    if raw[:4] != b"glTF" or struct.unpack_from("<I", raw, 8)[0] != len(raw):
        raise ValueError("Invalid GLB header/length")
    json_len, json_type = struct.unpack_from("<II", raw, 12)
    if json_type != 0x4E4F534A:
        raise ValueError("First GLB chunk is not JSON")
    doc = json.loads(raw[20:20 + json_len])
    bin_header = 20 + json_len
    bin_len, bin_type = struct.unpack_from("<II", raw, bin_header)
    if bin_type != 0x004E4942:
        raise ValueError("Second GLB chunk is not BIN")
    return doc, memoryview(raw)[bin_header + 8:bin_header + 8 + bin_len]


def accessor(doc, blob, index):
    a = doc["accessors"][index]
    if "sparse" in a:
        raise ValueError("Sparse accessor unsupported; expand it before auditing")
    view = doc["bufferViews"][a["bufferView"]]
    if "EXT_meshopt_compression" in view.get("extensions", {}):
        raise ValueError("Meshopt-compressed GLB; decode it before auditing")
    dtype = np.dtype(COMPONENT[a["componentType"]]).newbyteorder("<")
    width = WIDTH[a["type"]]
    row_bytes = dtype.itemsize * width
    stride = view.get("byteStride", row_bytes)
    offset = view.get("byteOffset", 0) + a.get("byteOffset", 0)
    arr = np.ndarray((a["count"], width), dtype=dtype, buffer=blob,
                     offset=offset, strides=(stride, dtype.itemsize))
    return arr.copy()


def weighted_quantile(values, weights, q):
    order = np.argsort(values)
    v, w = values[order], weights[order]
    return float(np.interp(q * w.sum(), np.cumsum(w), v))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("glb", type=pathlib.Path)
    ap.add_argument("--texture-size", type=int, default=8192)
    args = ap.parse_args()
    doc, blob = read_glb(args.glb)
    if args.texture_size <= 0:
        raise ValueError("Texture size must be positive")
    densities, weights = [], []
    for mesh in doc.get("meshes", []):
        for p in mesh["primitives"]:
            if p.get("mode", 4) != 4 or "TEXCOORD_0" not in p["attributes"]:
                continue
            pos = accessor(doc, blob, p["attributes"]["POSITION"]).astype(np.float64)
            uv = accessor(doc, blob, p["attributes"]["TEXCOORD_0"]).astype(np.float64)
            if "indices" in p:
                ix = accessor(doc, blob, p["indices"]).reshape(-1).astype(np.int64)
            else:
                ix = np.arange(len(pos), dtype=np.int64)
            tri = ix.reshape(-1, 3)
            xyz = pos[tri]
            tc = uv[tri]
            world_area = np.linalg.norm(np.cross(xyz[:, 1] - xyz[:, 0],
                                                 xyz[:, 2] - xyz[:, 0]), axis=1) * 0.5
            du = tc[:, 1] - tc[:, 0]
            dv = tc[:, 2] - tc[:, 0]
            uv_area = np.abs(du[:, 0] * dv[:, 1] - du[:, 1] * dv[:, 0]) * 0.5
            good = (world_area > 1e-12) & (uv_area > 1e-12)
            densities.append(args.texture_size * np.sqrt(uv_area[good] / world_area[good]))
            weights.append(world_area[good])
    if not densities:
        raise ValueError("No textured triangle primitives")
    density = np.concatenate(densities)
    weight = np.concatenate(weights)
    q10 = weighted_quantile(density, weight, 0.10)
    q50 = weighted_quantile(density, weight, 0.50)
    q90 = weighted_quantile(density, weight, 0.90)
    report = {
        "glb": str(args.glb), "texture_size": args.texture_size,
        "measured_triangles": int(len(density)),
        "texels_per_model_unit_surface_weighted": {"p10": q10, "p50": q50, "p90": q90},
        "p90_over_p10": q90 / q10 if q10 else None,
        "surface_below_half_median_fraction": float(weight[density < q50 / 2].sum() / weight.sum()),
        "surface_above_double_median_fraction": float(weight[density > q50 * 2].sum() / weight.sum()),
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
