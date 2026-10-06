"""Strict gsplat full-PLY -> KHR Gaussian GLB/glTF + local 3D Tiles export.

Only real, receipt-backed trained fields are accepted. XYZ/RGB point clouds,
compressed PLYs, incomplete SH, nonfinite parameters and oversized inputs fail.
No torch, renderer, GPU, Unreal, network or plugin resource writes are used.
"""
import argparse
import json
import math
import struct
from pathlib import Path

from common import GSPLAT_COMMIT, SCENES, TIERS, WORLD_FRAME, read_json, require_capture_receipt, scoped, sha256, write_json

SH_C0 = 0.2820947917738781


def read_gaussian_ply(path):
    with path.open("rb") as source:
        if source.readline().strip() != b"ply":
            raise ValueError("Expected a full Gaussian PLY")
        properties, count, format_name = [], None, None
        header_bytes = 4
        while True:
            raw = source.readline()
            header_bytes += len(raw)
            if not raw or header_bytes > 65536:
                raise ValueError("Malformed / oversized PLY header")
            line = raw.decode("ascii").strip().split()
            if not line or line[0] in ("comment", "obj_info"):
                continue
            if line[0] == "end_header":
                break
            if line[0] == "format":
                if len(line) != 3 or line[2] != "1.0":
                    raise ValueError("Unsupported PLY format")
                format_name = line[1]
            elif line[0] == "element":
                if len(line) != 3 or line[1] != "vertex" or count is not None:
                    raise ValueError("Only one uncompressed vertex element is accepted")
                count = int(line[2])
            elif line[0] == "property":
                if count is None or len(line) != 3 or line[1] not in ("float", "float32") or line[2] in properties:
                    raise ValueError("gsplat scalar float fields required; lists / packed data rejected")
                properties.append(line[2])
            else:
                raise ValueError("Unexpected PLY header field")
        if count is None or not 1 <= count <= 65000 or format_name not in ("ascii", "binary_little_endian"):
            raise ValueError("Need 1..65000 full Gaussians, ASCII or binary little endian")
        required = {"x", "y", "z", "opacity", *(f"scale_{i}" for i in range(3)),
                    *(f"rot_{i}" for i in range(4)), *(f"f_dc_{i}" for i in range(3))}
        if not required.issubset(properties):
            raise ValueError("Plain XYZ/RGB PLY rejected: need trained scales, quaternion, opacity and SH")
        rest = [p for p in properties if p.startswith("f_rest_")]
        if len(rest) not in (9, 24, 45) or set(rest) != {f"f_rest_{i}" for i in range(len(rest))}:
            raise ValueError("Require complete genuinely trained degree 1, 2 or 3 SH fields")
        allowed = required | set(rest) | {"nx", "ny", "nz"}
        if not set(properties).issubset(allowed):
            raise ValueError("Unknown PLY layout; no implicit field assumptions")
        rows = []
        if format_name == "binary_little_endian":
            record = struct.Struct("<" + "f"*len(properties))
            payload = source.read(record.size*count + 1)
            if len(payload) != record.size*count:
                raise ValueError("PLY payload length does not match its Gaussian count")
            rows = list(record.iter_unpack(payload))
        else:
            for _ in range(count):
                row = [float(v) for v in source.readline().split()]
                if len(row) != len(properties):
                    raise ValueError("Incomplete Gaussian PLY row")
                rows.append(row)
            if source.read().strip():
                raise ValueError("Unexpected trailing PLY records")
    indices = {name: i for i, name in enumerate(properties)}
    gaussians = []
    higher_count = len(rest)//3
    degree = {3: 1, 8: 2, 15: 3}[higher_count]
    for row in rows:
        if not all(math.isfinite(v) and abs(v) <= 3.4028234663852886e38 for v in row):
            raise ValueError("Nonfinite or non-float32 trained parameter")
        p = [row[indices[k]] for k in ("x", "y", "z")]
        logs = [row[indices[f"scale_{i}"]] for i in range(3)]
        if any(v < -80 or v > 20 for v in logs):
            raise ValueError("Unreviewed / pathological covariance scales")
        scales = [math.exp(v) for v in logs]
        q = [row[indices[f"rot_{i}"]] for i in range(4)]  # gsplat WXYZ
        norm = math.hypot(*q)
        if norm < 1e-12:
            raise ValueError("Zero quaternion")
        q = [v/norm for v in q]
        logit = row[indices["opacity"]]
        opacity = 1/(1+math.exp(-logit)) if logit >= 0 else math.exp(logit)/(1+math.exp(logit))
        sh0 = [row[indices[f"f_dc_{i}"]] for i in range(3)]
        # gsplat exporter is channel-major: all R, then all G, then all B.
        sh = [[row[indices[f"f_rest_{channel*higher_count+coefficient}"]]
               for channel in range(3)] for coefficient in range(higher_count)]
        gaussians.append({"position": p, "scales": scales, "rotation": q[1:]+q[:1],
                          "opacity": opacity, "sh0": sh0, "sh": sh})
    return gaussians, degree, properties


def covariance_extent(g):
    x, y, z, w = g["rotation"]
    r = [[1-2*(y*y+z*z), 2*(x*y-w*z), 2*(x*z+w*y)],
         [2*(x*y+w*z), 1-2*(x*x+z*z), 2*(y*z-w*x)],
         [2*(x*z-w*y), 2*(y*z+w*x), 1-2*(x*x+y*y)]]
    return [3*1.04*math.sqrt(sum((row[j]*g["scales"][j])**2 for j in range(3))) + 0.12 for row in r]


def make_asset(gaussians, degree):
    buffer = bytearray()
    accessors, views, attributes = [], [], {}

    def append(name, values, kind, include_bounds=False):
        width = {"SCALAR": 1, "VEC3": 3, "VEC4": 4}[kind]
        values = [list(v) if isinstance(v, (tuple, list)) else [v] for v in values]
        offset = len(buffer)
        flat = [v for row in values for v in row]
        buffer.extend(struct.pack("<" + "f"*len(flat), *flat))
        views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(flat)*4, "target": 34962})
        accessor = {"bufferView": len(views)-1, "componentType": 5126, "count": len(values), "type": kind}
        if include_bounds:
            accessor.update({"min": [min(row[j] for row in values) for j in range(width)],
                             "max": [max(row[j] for row in values) for j in range(width)]})
        accessors.append(accessor)
        attributes[name] = len(accessors)-1

    append("POSITION", [g["position"] for g in gaussians], "VEC3", True)
    append("KHR_gaussian_splatting:SCALE", [g["scales"] for g in gaussians], "VEC3")
    append("KHR_gaussian_splatting:ROTATION", [g["rotation"] for g in gaussians], "VEC4")
    append("KHR_gaussian_splatting:OPACITY", [g["opacity"] for g in gaussians], "SCALAR")
    append("KHR_gaussian_splatting:SH_DEGREE_0_COEF_0", [g["sh0"] for g in gaussians], "VEC3")
    # Cesium v2.29.1 reads COLOR_0 rather than explicit opacity and degree-zero SH.
    # Base glTF COLOR_0 must stay in [0,1]. Explicit degree-zero SH retains the
    # original trained values. Cesium's legacy DC path uses this clamped color.
    append("COLOR_0", [[max(0., min(1., SH_C0*v+0.5)) for v in g["sh0"]]+[g["opacity"]] for g in gaussians], "VEC4")
    index = 0
    for level in range(1, degree+1):
        for coefficient in range(2*level+1):
            append(f"KHR_gaussian_splatting:SH_DEGREE_{level}_COEF_{coefficient}",
                   [g["sh"][index] for g in gaussians], "VEC3")
            index += 1
    extension = {"kernel": "ellipse", "colorSpace": "srgb_rec709_display",
                 "projection": "perspective", "sortingMethod": "cameraDistance"}
    gltf = {"asset": {"version": "2.0", "generator": "Saskarta offline gsplat Gaussian exporter"},
            "extensionsUsed": ["KHR_gaussian_splatting"], "extensionsRequired": ["KHR_gaussian_splatting"],
            "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0}],
            "meshes": [{"primitives": [{"attributes": attributes, "mode": 0,
                        "extensions": {"KHR_gaussian_splatting": extension}}]}],
            "buffers": [{"byteLength": len(buffer)}], "bufferViews": views, "accessors": accessors}
    json_chunk = json.dumps(gltf, separators=(",", ":"), allow_nan=False).encode("utf-8")
    json_chunk += b" "*((-len(json_chunk)) % 4)
    binary_chunk = bytes(buffer) + b"\x00"*((-len(buffer)) % 4)
    glb = struct.pack("<III", 0x46546C67, 2, 12+8+len(json_chunk)+8+len(binary_chunk))
    glb += struct.pack("<II", len(json_chunk), 0x4E4F534A)+json_chunk
    glb += struct.pack("<II", len(binary_chunk), 0x004E4942)+binary_chunk
    return gltf, bytes(buffer), glb


def tile_box(gaussians):
    low, high = [math.inf]*3, [-math.inf]*3
    for g in gaussians:
        extent = covariance_extent(g)
        # glTF Y-up -> 3D Tiles right-handed Z-up, R_x(+90 degrees).
        p = [g["position"][0], -g["position"][2], g["position"][1]]
        e = [extent[0], extent[2], extent[1]]
        for i in range(3):
            low[i], high[i] = min(low[i], p[i]-e[i]), max(high[i], p[i]+e[i])
    c, h = [(a+b)/2 for a, b in zip(low, high)], [(b-a)/2 for a, b in zip(low, high)]
    return c+[h[0], 0, 0, 0, h[1], 0, 0, 0, h[2]]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ply", type=Path, required=True)
    parser.add_argument("--training-receipt", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True, help="Root's actual-data cleanup / license / fiducial review")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = scoped(args.out)
    training, review = read_json(args.training_receipt), read_json(args.review)
    if training.get("id") not in SCENES or training.get("trained") is not True or training.get("trainer_commit") != GSPLAT_COMMIT:
        raise ValueError("Exact official-trainer provenance required")
    if training.get("world_frame") != WORLD_FRAME or training.get("config", {}).get("normalize_world_space") is not False:
        raise ValueError("Exporter requires training directly in metric glTF axes; no implicit SH rotation")
    if training.get("source_ply_sha256") != sha256(args.ply):
        raise ValueError("PLY differs from the trained full PLY receipt")
    dataset = args.training_receipt.resolve().parent.parent
    capture, capture_path = require_capture_receipt(dataset)
    if capture["id"] != training["id"] or sha256(capture_path) != training["capture_receipt_sha256"]:
        raise ValueError("Original capture evidence differs from training provenance")
    if sha256(dataset/"colmap_receipt.json") != training["colmap_receipt_sha256"]:
        raise ValueError("Original reconstruction receipt changed")
    if review.get("id") != training["id"] or review.get("source_ply_sha256") != sha256(args.ply):
        raise ValueError("Actual-data review must identify this exact trained PLY")
    for gate in ("license_approved", "four_fiducials_verified", "source_bounds_verified", "sky_floor_floaters_removed", "walking_corridor_clear"):
        if review.get(gate) is not True:
            raise ValueError(f"Root's real-data review must establish {gate}")
    if not review.get("reviewed_by") or not training.get("asset_license"):
        raise ValueError("Reviewer and asset licensing must be recorded")
    gaussians, degree, fields = read_gaussian_ply(args.ply)
    order = sorted(range(len(gaussians)), key=lambda i: (-gaussians[i]["opacity"], i))
    if out.exists():
        raise ValueError("Refusing to overwrite a previous reviewed asset export")
    exported = []
    for tier in TIERS:
        selected_indices = sorted(order[:tier])
        selected = [gaussians[i] for i in selected_indices]
        folder = out if tier == 65000 else out/"tiers"/str(tier)
        folder.mkdir(parents=True, exist_ok=True)
        gltf, binary, glb = make_asset(selected, degree)
        (folder/"memory.glb").write_bytes(glb)
        (folder/"memory.bin").write_bytes(binary)
        gltf["buffers"][0]["uri"] = "memory.bin"
        write_json(folder/"memory.gltf", gltf)
        tileset = {"asset": {"version": "1.1"}, "geometricError": 0,
                   "root": {"boundingVolume": {"box": tile_box(selected)}, "geometricError": 0,
                            "refine": "ADD", "content": {"uri": "memory.glb"}}}
        write_json(folder/"tileset.json", tileset)
        manifest = {"id": training["id"], "representation": "KHR_gaussian_splatting", "trained": True,
                    "gaussian_count": len(selected), "tier_budget": tier, "sha256": sha256(folder/"memory.glb"),
                    "glb_sha256": sha256(folder/"memory.glb"), "source_ply_sha256": sha256(args.ply),
                    "license": training["asset_license"], "trainer_license": "Apache-2.0",
                    "units": "meters", "world_frame": WORLD_FRAME,
                    "fields": {"position": "POSITION float32 VEC3 meters", "rotation": "unit XYZW quaternion",
                               "scales": "linear exp(gsplat scale_i) meters", "opacity": "sigmoid(gsplat opacity) [0,1]",
                               "SH": {"degree": degree, "degree_zero": "f_dc_0..2", "higher_layout": "channel-major PLY to coefficient-major VEC3"}},
                    "source_ply_fields": fields, "capture_provenance": {"receipt_sha256": training["capture_receipt_sha256"], "capture": capture},
                    "training_provenance": training, "review_provenance": review,
                    "provenance": {"trainer_commit": training["trainer_commit"],
                                   "capture_receipt_sha256": training["capture_receipt_sha256"],
                                   "training_receipt_sha256": sha256(args.training_receipt),
                                   "review_sha256": sha256(args.review)},
                    "selection": {"method": "descending trained opacity then original index; no new Gaussians",
                                  "source_count": len(gaussians), "indices_sha256": __import__("hashlib").sha256(struct.pack("<"+"I"*len(selected_indices), *selected_indices)).hexdigest()},
                    "tileset": "tileset.json", "content": "memory.glb", "network_required": False,
                    "gltf_to_tile_z_up_rows": [[1,0,0,0],[0,0,-1,0],[0,1,0,0],[0,0,0,1]],
                    "engine_to_gltf": {"source_units": "centimeters", "source_handedness": "left",
                                       "origin_ue_cm": capture["origin_ue_cm"],
                                       "formula": "[(UE_X-origin_X)/100,(UE_Z-origin_Z)/100,(UE_Y-origin_Y)/100]"},
                    "cesium_legacy_dc": "COLOR_0 RGB clamps C0*SH0+0.5 to [0,1]; full SH0 retained explicitly",
                    "dream_displacement_bounds_padding_m": 0.12,
                    "dream_covariance_scale_bounds_multiplier": 1.04,
                    "status": "exported_requires_Cesium_load_visual_performance_review"}
        write_json(folder/"manifest.json", manifest)
        exported.append({"tier_budget": tier, "gaussian_count": len(selected), "path": str(folder.relative_to(out)),
                         "glb_sha256": manifest["glb_sha256"]})
    write_json(out/"export_receipt.json", {"id": training["id"], "tiers": exported,
               "status": "offline_export_complete_not_staged", "original_full_ply": str(args.ply.resolve()),
               "original_full_ply_sha256": sha256(args.ply)})
    print(f"Exported real Gaussian tiers for {training['id']} under {out}; plugin resources untouched")


if __name__ == "__main__":
    main()
