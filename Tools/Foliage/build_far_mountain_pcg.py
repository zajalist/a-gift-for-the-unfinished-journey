"""Build six small, finite-point far-mountain PCG graphs; never touch near-tree graphs.

Offline: python Tools/Foliage/build_far_mountain_pcg.py spec
Editor (gate owner only): python Tools/Foliage/build_far_mountain_pcg.py build --owner CODEX
The separate apply helper places one bounded PCGVolume at a time after graph creation.
"""

import argparse
import json
import math
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import build_pcg_trees as pcg  # noqa: E402

PLAN = HERE / "far_mountain_trees.json"
PATH_PREFIX = "/Game/SaskartaGaea/PCG/PCG_FarMountain_"
MIN_DRAW_CM = 45000.0
START_CULL_CM = 180000.0
END_CULL_CM = 220000.0


def plan():
    doc = json.loads(PLAN.read_text(encoding="utf8"))
    clusters = doc["clusters"]
    if (len(clusters) > doc["limits"]["max_clusters"] or
            sum(len(c["points"]) for c in clusters) != doc["instance_count"] or
            doc["instance_count"] > doc["limits"]["max_total"] or
            any(len(c["points"]) > doc["limits"]["max_per_cluster"] for c in clusters)):
        raise RuntimeError("far-mountain plan exceeds its hard instance budget")
    return doc


def point_text(p, seed):
    half = math.radians(p["yaw"]) / 2.0
    z, w = math.sin(half), math.cos(half)
    s = p["scale"]
    return ("(Transform=(Rotation=(X=0.0,Y=0.0,Z=%.8f,W=%.8f),"
            "Translation=(X=%.1f,Y=%.1f,Z=%.1f),Scale3D=(X=%.3f,Y=%.3f,Z=%.3f)),"
            "Density=1.000000,Steepness=0.500000,Seed=%d)" %
            (z, w, p["x_cm"], p["y_cm"], p["z_cm"], s, s, s, seed))


def spec(cluster):
    graph = pcg.Spec(PATH_PREFIX + cluster["id"])
    joined = graph.node("PCGMergeSettings", lane=1)
    for mi, mesh in enumerate(sorted({p["mesh"] for p in cluster["points"]})):
        points = [p for p in cluster["points"] if p["mesh"] == mesh]
        create = graph.node("PCGCreatePointsSettings", {"points_to_create": {
            "elem": "PCGPoint", "texts": [point_text(p, 1000 * (mi + 1) + i)
                                            for i, p in enumerate(points)]}}, lane=mi + 2)
        tagged = graph.add_const(create, "TreeMesh", "String", pcg.obj_path(mesh), lane=mi + 2)
        graph.edge(tagged, "Out", joined, "In")
    spawner = graph.node("PCGStaticMeshSpawnerSettings", {
        "mesh_selector_parameters/attribute_name": {"name": "TreeMesh"},
        "mesh_selector_parameters/template_descriptor": {"sub": {
            "body_instance": {"sub": {"collision_profile_name": {"name": "NoCollision"}}},
            "instance_min_draw_distance": MIN_DRAW_CM,
            "instance_start_cull_distance": START_CULL_CM,
            "instance_end_cull_distance": END_CULL_CM,
            "cast_shadow": False,
            "cast_far_shadow": False,
            "visible_in_ray_tracing": False,
            "affect_distance_field_lighting": False,
            "world_position_offset_disable_distance": 1}}},
        calls=[["set_mesh_selector_type", {"cls": "PCGMeshSelectorByAttribute"}]], lane=1)
    graph.edge(joined, "Out", spawner, "In")
    graph.edge(joined, "Out", "OUT", "Out")
    return graph


def gate(owner):
    if not owner:
        raise SystemExit("editor build requires --owner and the editor gate")
    result = subprocess.run([sys.executable, str(ROOT / "Tools" / "GameFlow" / "editor_gate.py"), "status"],
                            capture_output=True, text=True, timeout=30)
    if f'"{owner}"' not in result.stdout:
        raise SystemExit(f"editor gate is not held by {owner}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=("spec", "build"))
    ap.add_argument("--owner", default="")
    ap.add_argument("--cluster", default="", help="one FMxx graph; empty builds all")
    args = ap.parse_args()
    clusters = [c for c in plan()["clusters"] if not args.cluster or c["id"] == args.cluster]
    if not clusters:
        raise SystemExit(f"unknown far mountain cluster {args.cluster}")
    graphs = [spec(c) for c in clusters]
    if args.step == "spec":
        print(json.dumps([g.to_json() for g in graphs], indent=2))
        return
    gate(args.owner)
    for graph in graphs:
        ok, out = pcg.run(pcg.compile_spec(graph))
        lines = [line for line in out.splitlines() if not line.startswith("N ")]
        print("\n".join(lines))
        if not ok or "bad []" not in out:
            raise SystemExit(f"PCG graph build failed for {graph.path}; do not apply its volume")


if __name__ == "__main__":
    main()
