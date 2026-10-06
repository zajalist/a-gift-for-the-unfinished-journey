"""Fast metadata gate for an optimized S26 relay-tower GLB candidate.

Reads GLB JSON and PNG headers only. This cannot prove visual fidelity or
portal/collision quality; those require all-side art review and Unreal checks.

  python Tools/Tripo/audit_relay_tower_candidate.py \
    Saved/Ending/RelayTower/SM_S26_RelayTower_Candidate80.glb \
    --report Saved/Ending/RelayTower/SM_S26_RelayTower_Candidate80.audit.json \
    --max-triangles 1250000
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from stage_relay_tower import REVIEW, ROOT, glb_json, validate


def audit(candidate: Path, report_path: Path, ceiling: int) -> dict:
    if candidate.resolve() == REVIEW.resolve():
        raise ValueError("The full-resolution review GLB is not an optimized candidate")
    candidate_data = validate(candidate, ceiling)
    if not candidate_data["optimized_gate_pass"]:
        raise ValueError("Candidate failed the optimized triangle gate")
    original_data = validate(REVIEW)
    doc = glb_json(candidate)
    if len(doc.get("extensionsRequired", [])):
        raise ValueError("Runtime candidate requires a GLB extension")
    if doc.get("images") or doc.get("textures"):
        raise ValueError("Mesh-only derivative unexpectedly embeds textures")
    primitive = doc["meshes"][0]["primitives"][0]
    accessors = doc["accessors"]
    uv = accessors[primitive["attributes"]["TEXCOORD_0"]]
    position = accessors[primitive["attributes"]["POSITION"]]
    if uv["count"] != position["count"]:
        raise ValueError("Candidate UV0 vertex count differs from position count")
    uv_min, uv_max = uv.get("min"), uv.get("max")
    # Blender's GLB exporter commonly omits UV accessor bounds. When present,
    # reject corrupt values; otherwise leave texel-density review explicit.
    if uv_min is not None and uv_max is not None:
        if any(not math.isfinite(v) for v in uv_min + uv_max):
            raise ValueError("Candidate UV0 has non-finite bounds")
        if any(b-a < 0.5 for a,b in zip(uv_min, uv_max)):
            raise ValueError("Candidate UV0 occupies less than half the atlas")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if Path(report.get("candidate_glb", "")).resolve() != candidate.resolve():
        raise ValueError("Candidate report names a different GLB")
    if report.get("candidate_triangles") != candidate_data["triangle_count"]:
        raise ValueError("Candidate triangle count differs from Blender report")
    if report.get("approved_review_triangles") != original_data["triangle_count"]:
        raise ValueError("Approved review triangle count differs from Blender report")
    cut_source_triangles = report.get("cut_source_triangles")
    if not isinstance(cut_source_triangles, int) or not 1_000_000 <= cut_source_triangles < original_data["triangle_count"]:
        raise ValueError("Report does not identify a plausible portal+window cut source")
    if candidate_data["triangle_count"] >= cut_source_triangles:
        raise ValueError("Candidate did not reduce the cut source")
    for size, baseline in zip(candidate_data["imported_local_size_cm_expected"],
                              original_data["imported_local_size_cm_expected"]):
        if abs(size - baseline) > 0.01 * baseline:
            raise ValueError(f"Candidate silhouette bounds drifted over 1%: {size} vs {baseline}")
    fraction = 1 - candidate_data["triangle_count"] / cut_source_triangles
    if fraction < 0.05 or fraction > 0.4:
        raise ValueError(f"Candidate reduction must stay 5-40% for this visual review: {fraction:.3f}")
    return {
        "candidate_glb": str(candidate),
        "triangles": candidate_data["triangle_count"],
        "cut_source_triangles": cut_source_triangles,
        "reduction_fraction": round(fraction, 6),
        "silhouette_bounds_within_one_percent": True,
        "uv0_and_normals_present": True,
        "bottom_pivot": True,
        "single_material_section": True,
        "external_8k_pbr_maps": candidate_data["maps"],
        "ready_for_art_review": True,
        "ready_for_unreal_import": False,
        "remaining_gates": ["UV seam and texel-density review", "all-side art review", "supported placement", "portal and CIN24 window ray", "collision and camera test"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--max-triangles", type=int, required=True)
    args = parser.parse_args()
    candidate = args.candidate if args.candidate.is_absolute() else ROOT / args.candidate
    report = args.report if args.report.is_absolute() else ROOT / args.report
    print(json.dumps(audit(candidate, report, args.max_triangles), indent=2))


if __name__ == "__main__":
    main()
