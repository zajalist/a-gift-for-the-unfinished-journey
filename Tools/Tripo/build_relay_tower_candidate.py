"""Build a reversible, mesh-only relay tower optimization candidate in Blender.

Run after capture is clear, using the saved chamber + CIN24 window Blender
derivative. Never run on the approved master or the chamber-only file:

  blender -b -P Tools/Tripo/build_relay_tower_candidate.py -- \
    --source Saved/Ending/RelayTower/S26_RelayTower_ChamberWindow_ReviewOnly.blend \
    --ratio 0.80 --output Saved/Ending/RelayTower/SM_S26_RelayTower_Candidate80.glb

This is a *candidate*, not an automatic art approval. Blender's collapse
decimator can alter silhouette and narrow aerial members. The original 8K PBR
maps stay external and untouched; review four sides, door, aerial and texture
seams before generating an Unreal import packet.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy
from mathutils import Matrix


ROOT = Path(__file__).resolve().parents[2]
REVIEW_TRIANGLES = 1_861_164
ALLOWED_CUT_SOURCE = "S26_RelayTower_ChamberWindow_ReviewOnly.blend"


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True,
                        help="Reviewed Blender derivative with portal and CIN24 side window cut")
    parser.add_argument("--ratio", type=float, default=0.80)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    if not 0.65 <= args.ratio <= 0.95:
        parser.error("Candidate ratio must be 0.65..0.95; inspect mild reductions first")
    args.source = args.source if args.source.is_absolute() else ROOT / args.source
    if not args.source.is_file() or args.source.name != ALLOWED_CUT_SOURCE:
        parser.error(f"Source must be the saved chamber+window derivative: {ALLOWED_CUT_SOURCE}")
    args.output = args.output if args.output.is_absolute() else ROOT / args.output
    args.report = args.report or args.output.with_suffix(".audit.json")
    args.report = args.report if args.report.is_absolute() else ROOT / args.report
    if args.output.exists() or args.report.exists():
        parser.error("Candidate output exists; choose a new name to preserve review history")
    if args.output.suffix.lower() != ".glb":
        parser.error("--output must be a .glb")
    return args


def count_triangles(mesh):
    mesh.calc_loop_triangles()
    return len(mesh.loop_triangles)


def bounds(mesh):
    return [[min(v.co[i] for v in mesh.vertices) for i in range(3)],
            [max(v.co[i] for v in mesh.vertices) for i in range(3)]]


def main():
    args = arguments()
    bpy.ops.wm.open_mainfile(filepath=str(args.source))
    meshes = [obj for obj in bpy.data.objects if obj.type == "MESH"]
    tower_meshes = [obj for obj in meshes if obj.name.startswith("Tripo tower masonry")]
    if len(tower_meshes) != 1:
        raise RuntimeError(f"Expected one cut tower mesh, found {len(tower_meshes)} among {len(meshes)} meshes")
    source = tower_meshes[0]
    original_triangles = count_triangles(source.data)
    if not 1_000_000 <= original_triangles < REVIEW_TRIANGLES:
        raise RuntimeError(f"Cut derivative topology outside expected range: {original_triangles} triangles")
    if not source.data.uv_layers:
        raise RuntimeError("Source review mesh has no UV0")

    candidate = source.copy()
    candidate.data = source.data.copy()
    candidate.name = "S26_RelayTower_Optimized_Candidate"
    bpy.context.collection.objects.link(candidate)
    bpy.ops.object.select_all(action="DESELECT")
    candidate.select_set(True)
    bpy.context.view_layer.objects.active = candidate

    # A restrained single pass preserves the original triangulated sculpt as
    # the comparison baseline. No Boolean, smoothing, remesh, or material bake.
    modifier = candidate.modifiers.new("Mild QEM candidate", "DECIMATE")
    modifier.decimate_type = "COLLAPSE"
    modifier.ratio = args.ratio
    bpy.ops.object.modifier_apply(modifier=modifier.name)
    optimized_triangles = count_triangles(candidate.data)
    if optimized_triangles >= original_triangles or optimized_triangles < original_triangles * 0.60:
        raise RuntimeError(f"Candidate triangle count outside mild reduction: {optimized_triangles}")
    if not candidate.data.uv_layers or len(candidate.data.uv_layers[0].data) != len(candidate.data.loops):
        raise RuntimeError("Candidate UV0 was lost")

    old_lo, old_hi = bounds(source.data)
    new_lo, new_hi = bounds(candidate.data)
    # Geometry stays in source coordinates until the export-only pivot shift.
    if max(abs(a-b) for a,b in zip(old_lo+old_hi, new_lo+new_hi)) > 0.006:
        raise RuntimeError("Candidate lost a >0.006 source-unit extremity")
    bottom = new_lo[2]
    candidate.data.transform(Matrix.Translation((0, 0, -bottom)))
    candidate.data.materials.clear()
    candidate.data.update()

    # Export exactly one local, bottom-centre mesh. Geometry remains near one
    # source unit high; stage_relay_tower.py computes the 20 m actor scale.
    bpy.ops.object.select_all(action="DESELECT")
    candidate.select_set(True)
    bpy.context.view_layer.objects.active = candidate
    args.output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=str(args.output), export_format="GLB",
                              use_selection=True, export_materials="NONE",
                              export_texcoords=True, export_normals=True,
                              export_tangents=False)
    report = {
        "source_blend": str(args.source), "candidate_glb": str(args.output),
        "approved_review_triangles": REVIEW_TRIANGLES,
        "cut_source_triangles": original_triangles,
        "candidate_triangles": optimized_triangles,
        "reduction_fraction": round(1 - optimized_triangles/original_triangles, 6),
        "ratio_requested": args.ratio,
        "source_bounds_blender": {"min": old_lo, "max": old_hi},
        "candidate_bounds_before_pivot_blender": {"min": new_lo, "max": new_hi},
        "bottom_pivot_shift_blender": -bottom,
        "uv_layers": len(candidate.data.uv_layers),
        "materials_embedded": 0,
        "requires_visual_approval": ["aerial", "counterweights", "buttresses", "portal", "CIN24 side window", "texture seams", "all four sides"],
        "maps": "Approved external 8K BaseColor, Normal, ORM are not modified",
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("RELAY_CANDIDATE", json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
