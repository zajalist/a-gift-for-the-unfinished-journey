"""The far PCG layer has a deterministic finite budget and stays off road/story ground."""

import ast
import math
import pathlib
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import apply_far_mountain_pcg as apply  # noqa: E402
import build_far_mountain_pcg as build  # noqa: E402
import plan_far_mountain_trees as planner  # noqa: E402


def test_plan_reproduces_the_committed_finite_points():
    assert planner.plan() == build.plan()


def test_points_have_road_site_slope_and_spacing_clearance():
    doc = build.plan()
    assert 4 <= len(doc["clusters"]) <= planner.MAX_CLUSTERS
    assert doc["instance_count"] <= planner.MAX_TOTAL
    sites = planner.site_centres()
    for cluster in doc["clusters"]:
        points = cluster["points"]
        assert 7 <= len(points) <= planner.MAX_PER_CLUSTER
        xy = np.array([[p["x_cm"], p["y_cm"]] for p in points])
        assert all(planner.MIN_ROAD_M <= p["road_distance_m"] <= planner.MAX_ROAD_M for p in points)
        assert all(planner.MIN_SLOPE_DEG <= p["slope_deg"] <= planner.MAX_SLOPE_DEG for p in points)
        assert all(planner.site_clearance(p["x_cm"], p["y_cm"], sites) for p in points)
        for i in range(len(xy)):
            for j in range(i + 1, len(xy)):
                assert math.dist(xy[i], xy[j]) >= planner.MIN_TREE_SEPARATION_M * 100 - 1
    centres = [c["centre_cm"] for c in doc["clusters"]]
    for i in range(len(centres)):
        for j in range(i + 1, len(centres)):
            assert math.dist(centres[i], centres[j]) >= planner.MIN_CLUSTER_SEPARATION_M * 100 - 1


def test_graphs_contain_exact_points_static_meshes_and_far_only_culls():
    for cluster in build.plan()["clusters"]:
        graph = build.spec(cluster)
        code = build.pcg.compile_spec(graph)
        ast.parse(code)
        point_nodes = [n for n in graph.nodes if n["cls"] == "PCGCreatePointsSettings"]
        assert sum(len(n["props"]["points_to_create"]["texts"]) for n in point_nodes) == len(cluster["points"])
        spawners = [n for n in graph.nodes if n["cls"] == "PCGStaticMeshSpawnerSettings"]
        assert len(spawners) == 1
        descriptor = spawners[0]["props"]["mesh_selector_parameters/template_descriptor"]["sub"]
        assert descriptor["instance_min_draw_distance"] >= 30000.0
        assert descriptor["instance_start_cull_distance"] < descriptor["instance_end_cull_distance"] <= 220000.0
        assert descriptor["cast_shadow"] is False
        assert descriptor["body_instance"]["sub"]["collision_profile_name"] == {"name": "NoCollision"}
        assert descriptor["visible_in_ray_tracing"] is False
        assert descriptor["world_position_offset_disable_distance"] == 1
        assert any(edge[2] == "OUT" for edge in graph.edges)
        assert all(p["mesh"] in planner.MESHES for p in cluster["points"])
        ast.parse(apply.script("place", cluster))
        ast.parse(apply.script("prepare", cluster))
        ast.parse(apply.script("save", cluster))


def test_far_hosts_are_always_loaded_and_save_is_read_only_until_receipt():
    code = apply.script("place", build.plan()["clusters"][0])
    assert "set_editor_property('is_spatially_loaded', False)" in code
    assert "set_editor_property('enable_auto_lod_generation', False)" in code
    save = apply.script("save", build.plan()["clusters"][0])
    assert "if STEP == 'prepare' and not busy:" in save
    assert "and not busy:" in save
    assert "unmatched.pop(match)" in save
