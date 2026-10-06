"""Plan a finite, far-only pine layer from the live terrain and mask sources.

This does not call Unreal. The output is consumed by build_far_mountain_pcg.py;
regenerate after a terrain or ecology-mask change, then review before editor use.
"""

import argparse
import json
import math
import pathlib
import random
import sys

import numpy as np
from PIL import Image
from scipy.spatial import cKDTree

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "Tools" / "Story"))
import build_road_profile as road_profile  # noqa: E402

OUT = HERE / "far_mountain_trees.json"
ECOLOGY = ROOT / "Saved" / "Masks" / "T_Saskarta_Ecology.png"
ROAD_MASK = ROOT / "Saved" / "Masks" / "T_Saskarta_RoadInfluence.png"
SITES = ROOT / "Tools" / "World" / "setdress_sites.json"
MESHES = (
    "/Game/MedievalVillage/Demo/StaticMesh/Trees/Pine/SM_PineTree_01",
    "/Game/MedievalVillage/Demo/StaticMesh/Trees/Pine/SM_PineTree_02",
)
SEED = 20260929
ROAD_MARKERS_M = (450, 850, 1150, 1500, 1850, 2200, 2600, 3000, 3350, 4200, 4650)
MAX_CLUSTERS = 10
MAX_PER_CLUSTER = 12
MAX_TOTAL = 120
MIN_ROAD_M = 500.0
MAX_ROAD_M = 2100.0
MIN_SITE_BUFFER_M = 180.0
MIN_CLUSTER_SEPARATION_M = 350.0
MIN_TREE_SEPARATION_M = 19.0
MIN_SLOPE_DEG = 3.0
MAX_SLOPE_DEG = 24.0


def mask_pixel(image, x_cm, y_cm):
    px = int((x_cm - road_profile.LAND_X0_CM) / 816000.0 * image.shape[1])
    py = int((y_cm - road_profile.LAND_Y0_CM) / 816000.0 * image.shape[0])
    if px < 0 or py < 0 or px >= image.shape[1] or py >= image.shape[0]:
        return None
    return image[py, px].astype(float) / 255.0


def site_clearance(x_cm, y_cm, sites):
    for sx, sy, radius_m in sites:
        if math.hypot(x_cm - sx, y_cm - sy) < 100.0 * max(MIN_SITE_BUFFER_M, radius_m + 100.0):
            return False
    return True


def viable(x_cm, y_cm, terrain, ecology, road_mask, road_tree, sites):
    if not bool(terrain.inside(x_cm, y_cm)):
        return None
    if min(x_cm - road_profile.LAND_X0_CM, y_cm - road_profile.LAND_Y0_CM,
           road_profile.LAND_X0_CM + 816000 - x_cm,
           road_profile.LAND_Y0_CM + 816000 - y_cm) < 15000:
        return None
    road_m = float(road_tree.query([x_cm, y_cm])[0] / 100.0)
    if not MIN_ROAD_M <= road_m <= MAX_ROAD_M or not site_clearance(x_cm, y_cm, sites):
        return None
    eco = mask_pixel(ecology, x_cm, y_cm)
    rm = mask_pixel(road_mask, x_cm, y_cm)
    if eco is None or rm is None or eco[0] < 0.10 or eco[1] > 0.93 or eco[3] < 0.20 or rm[0] > 0.03:
        return None
    slope = math.degrees(math.atan(float(terrain.gradient(x_cm, y_cm))))
    if not MIN_SLOPE_DEG <= slope <= MAX_SLOPE_DEG:
        return None
    return dict(x_cm=x_cm, y_cm=y_cm, z_m=float(terrain.height(x_cm, y_cm)),
                slope_deg=slope, road_distance_m=road_m, moisture=float(eco[0]),
                exposure=float(eco[1]), macro=float(eco[3]))


def site_centres():
    rows = json.loads(SITES.read_text(encoding="utf8"))["sites"]
    return [(float(s["centre_cm"][0]), float(s["centre_cm"][1]), float(s["radius_m"])) for s in rows]


def plan():
    terrain = road_profile.Terrain(road_profile.HEIGHTMAP)
    road = road_profile.Road(road_profile.SPLINE_POINTS_CM)
    ecology = np.asarray(Image.open(ECOLOGY).convert("RGBA"))
    road_mask = np.asarray(Image.open(ROAD_MASK).convert("RGBA"))
    road_tree = cKDTree(road.xy(np.arange(0.0, road.length + 10.0, 10.0)))
    sites = site_centres()
    rng = random.Random(SEED)
    clusters = []
    for marker in ROAD_MARKERS_M:
        ox, oy = map(float, road.xy(np.array([marker]))[0])
        eye = float(terrain.height(ox, oy)) + 1.7
        candidates = []
        for radius_m in (700, 950, 1200, 1450, 1700):
            for bearing in range(0, 360, 20):
                x_cm = ox + math.cos(math.radians(bearing)) * radius_m * 100.0
                y_cm = oy + math.sin(math.radians(bearing)) * radius_m * 100.0
                row = viable(x_cm, y_cm, terrain, ecology, road_mask, road_tree, sites)
                if row is None or not 20.0 <= row["z_m"] - eye <= 350.0:
                    continue
                if any(math.hypot(x_cm - c["centre_cm"][0], y_cm - c["centre_cm"][1])
                       < MIN_CLUSTER_SEPARATION_M * 100.0 for c in clusters):
                    continue
                horizon, _ = terrain.horizon_tan(np.array([ox]), np.array([oy]), np.array([eye]),
                                                 np.array([x_cm]), np.array([y_cm]), step_m=10.0)
                angle = (row["z_m"] + 12.0 - eye) / radius_m
                if angle <= float(horizon[0]) + 0.004:
                    continue
                # Sparse pockets on readable shoulders, with enough moisture for a few pines.
                score = (row["moisture"] * 0.8 + row["macro"] * 0.4 - row["exposure"] * 0.25
                         + min(row["z_m"] - eye, 220.0) / 450.0 - abs(radius_m - 1150.0) / 5000.0)
                candidates.append((score, row))
        for _, centre in sorted(candidates, key=lambda r: r[0], reverse=True):
            if len(clusters) >= MAX_CLUSTERS:
                break
            if any(math.hypot(centre["x_cm"] - c["centre_cm"][0],
                              centre["y_cm"] - c["centre_cm"][1]) < MIN_CLUSTER_SEPARATION_M * 100.0
                   for c in clusters):
                continue
            points = []
            for attempt in range(600):
                if len(points) >= MAX_PER_CLUSTER:
                    break
                radius = 100.0 * math.sqrt(rng.random())
                angle = rng.random() * math.tau
                x_cm = centre["x_cm"] + math.cos(angle) * radius * 100.0
                y_cm = centre["y_cm"] + math.sin(angle) * radius * 100.0
                row = viable(x_cm, y_cm, terrain, ecology, road_mask, road_tree, sites)
                if row is None or abs(row["z_m"] - centre["z_m"]) > 42.0:
                    continue
                if any(math.hypot(x_cm - p["x_cm"], y_cm - p["y_cm"]) < MIN_TREE_SEPARATION_M * 100.0
                       for p in points):
                    continue
                points.append(dict(x_cm=round(x_cm, 1), y_cm=round(y_cm, 1),
                                   z_cm=round(row["z_m"] * 100.0 - 15.0, 1),
                                   mesh=MESHES[len(points) % len(MESHES)],
                                   yaw=round(rng.uniform(0, 360), 1), scale=round(rng.uniform(0.65, 0.9), 3),
                                   slope_deg=round(row["slope_deg"], 1),
                                   road_distance_m=round(row["road_distance_m"], 1)))
            if len(points) < 7:
                continue
            clusters.append(dict(id=f"FM{len(clusters) + 1:02d}", road_marker_m=marker,
                                 centre_cm=[round(centre["x_cm"], 1), round(centre["y_cm"], 1)],
                                 centre_height_m=round(centre["z_m"], 1), points=points))
            break  # at most one pocket per route marker; keep mountains sparse
    total = sum(len(c["points"]) for c in clusters)
    if total > MAX_TOTAL or not clusters:
        raise RuntimeError(f"invalid far-tree plan: {len(clusters)} clusters, {total} instances")
    return dict(generated_by="Tools/Foliage/plan_far_mountain_trees.py", seed=SEED,
                source_heightmap=str(road_profile.HEIGHTMAP.relative_to(ROOT)).replace('\\', '/'),
                source_masks=["Saved/Masks/T_Saskarta_Ecology.png", "Saved/Masks/T_Saskarta_RoadInfluence.png"],
                mesh_paths=list(MESHES), limits=dict(max_clusters=MAX_CLUSTERS, max_per_cluster=MAX_PER_CLUSTER,
                                                    max_total=MAX_TOTAL, road_distance_m=[MIN_ROAD_M, MAX_ROAD_M],
                                                    slope_deg=[MIN_SLOPE_DEG, MAX_SLOPE_DEG]),
                instance_count=total, clusters=clusters)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="compare the committed plan without changing it")
    args = ap.parse_args()
    doc = plan()
    encoded = json.dumps(doc, indent=2) + "\n"
    if args.check:
        if OUT.read_text(encoding="utf8") != encoded:
            raise SystemExit("far mountain plan is stale; regenerate after reviewing terrain/mask changes")
    else:
        OUT.write_text(encoded, encoding="utf8")
    print(f"far mountain clusters={len(doc['clusters'])} trees={doc['instance_count']} cap={MAX_TOTAL}")


if __name__ == "__main__":
    main()
