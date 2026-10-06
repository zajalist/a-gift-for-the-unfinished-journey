"""Read-only CIN24 sun-window sightline survey for the integrated relay tower.

The true painted entrance is off-centre at source local (.119,-.127), with
outward face normal (.67,-.74). Rotate that normal to face opposite the
protected door-to-inside heading and translate the real door to its waypoint.
Local coordinates match the approved Tripo GLB after glTF Y-up conversion to
Blender Z-up. No UE or Blender write.

Run: python Tools/EndingFocus/validate_cin24_window_ray.py
     python Tools/EndingFocus/validate_cin24_window_ray.py --mesh-ray
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Tools" / "Tripo"))

GLB = ROOT / "SourceArt/Tripo/20261003/S26_VictorianRadioStation/S26_RelayTower_8K_PBR_Review.glb"
PROBE = ROOT / "Tools/Cinematics/probe_ending.json"
SCALE_CM = 2027.0  # 20.00 m from 0.986756-unit source height
PAINTED_DOOR_XY = np.array((0.119, -0.127))
PAINTED_DOOR_OUTWARD_XY = np.array((0.67, -0.74))
PAINTED_DOOR_CENTRE_Z = -0.437
FLOOR_Z = -0.469
EYE_CM = (297235.4, 483334.7, 11075.1)
SUN_RAY = (-0.9474, -0.3199, 0.0108)  # protected measured CIN24 sightline


def frame():
    post = json.loads(PROBE.read_text(encoding="utf8"))["radio_post"]
    door, inside = np.array(post["door"], float), np.array(post["inside"], float)
    route_inward = inside[:2] - door[:2]
    route_inward /= np.linalg.norm(route_inward)
    door_inward_local = -PAINTED_DOOR_OUTWARD_XY / np.linalg.norm(PAINTED_DOOR_OUTWARD_XY)
    theta = math.atan2(route_inward[1], route_inward[0]) - math.atan2(door_inward_local[1], door_inward_local[0])
    right = np.array((math.cos(theta), math.sin(theta)))
    inward = np.array((-math.sin(theta), math.cos(theta)))
    centre = door.copy()
    centre[:2] -= SCALE_CM * (PAINTED_DOOR_XY[0] * right + PAINTED_DOOR_XY[1] * inward)
    centre[2] = door[2] - SCALE_CM * FLOOR_Z
    return door, inside, centre, right, inward


def to_local(point_cm, centre, right, inward):
    relative = np.asarray(point_cm, float) - centre
    return np.array((np.dot(relative[:2], right), np.dot(relative[:2], inward), relative[2])) / SCALE_CM


def local_direction(vector, right, inward):
    vector = np.asarray(vector, float)
    return np.array((np.dot(vector[:2], right), np.dot(vector[:2], inward), vector[2]))


def gltf(point):
    """Blender XYZ to stored glTF XYZ."""
    return np.array((point[0], point[2], -point[1]), float)


def mesh_hits(origin, direction, max_cm=1200.0):
    """Intersect a bounded source-GLB ray; return distances in centimetres."""
    from audit_relay_portal_geometry import glb_arrays

    handle, blob, positions, indices = glb_arrays(GLB)
    origin = gltf(origin)
    unit = gltf(direction) / SCALE_CM
    end = origin + unit * max_cm
    lo, hi = np.minimum(origin, end) - 1e-5, np.maximum(origin, end) + 1e-5
    hits = []
    try:
        for first in range(0, len(indices), 50_000):
            tri = positions[indices[first:first + 50_000]]
            plausible = np.all(tri.min(axis=1) <= hi, axis=1) & np.all(tri.max(axis=1) >= lo, axis=1)
            if not plausible.any():
                continue
            tri = tri[plausible].astype(np.float64)
            e1, e2 = tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]
            pv = np.cross(np.broadcast_to(unit, e2.shape), e2)
            det = np.einsum("ij,ij->i", e1, pv)
            good = np.abs(det) > 1e-12
            if not good.any():
                continue
            inv = np.zeros_like(det)
            inv[good] = 1 / det[good]
            tv = origin - tri[:, 0]
            u = np.einsum("ij,ij->i", tv, pv) * inv
            qv = np.cross(tv, e1)
            v = qv @ unit * inv
            distance = np.einsum("ij,ij->i", e2, qv) * inv
            valid = good & (u >= -1e-7) & (v >= -1e-7) & (u + v <= 1 + 1e-7)
            valid &= (distance >= 0) & (distance <= max_cm)
            hits.extend(float(t) for t in distance[valid])
        return sorted(hits)
    finally:
        del positions, indices
        blob.close()
        handle.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mesh-ray", action="store_true", help="scan all source mesh triangles (read-only)")
    args = parser.parse_args()
    door, inside, centre, right, inward = frame()
    eye = to_local(EYE_CM, centre, right, inward)
    ray = local_direction(SUN_RAY, right, inward)
    # Chamber Boolean occupies approximately y=-.16..+.31. This compact
    # diagonal cut starts within that void, crosses its front-left masonry,
    # and ends beyond the one measured source hit. The cutter is a *proposal*.
    cut_start_cm, cut_end_cm = 240.0, 530.0
    horizontal = ray[:2] / np.linalg.norm(ray[:2])
    width_axis = np.array((-horizontal[1], horizontal[0]))
    crossings = []
    for t in (0.0, 100.0, 200.0, cut_start_cm, 300.0, 401.27, cut_end_cm):
        point = eye + ray * t / SCALE_CM
        crossings.append({"distance_cm": t,
                          "local": [round(float(value), 5) for value in point],
                          "height_above_floor_cm": round((point[2] - FLOOR_Z) * SCALE_CM, 1)})
    report = {
        "basis": {"right_world_xy": right.tolist(), "inward_world_xy": inward.tolist(),
                  "right_axis_yaw_deg": math.degrees(math.atan2(right[1], right[0]))},
        "scale_cm_per_source_unit": SCALE_CM,
        "tower_centre_cm": centre.tolist(),
        "protected_door_cm": door.tolist(), "protected_inside_cm": inside.tolist(),
        "protected_door_local": to_local(door, centre, right, inward).tolist(),
        "protected_inside_local": to_local(inside, centre, right, inward).tolist(),
        "painted_door_local_xy": PAINTED_DOOR_XY.tolist(),
        "painted_door_centre_above_protected_floor_cm": (PAINTED_DOOR_CENTRE_Z-FLOOR_Z)*SCALE_CM,
        "eye_local": eye.tolist(), "ray_local": ray.tolist(),
        "crossings": crossings,
        "proposed_cut": {"distance_cm": [cut_start_cm, cut_end_cm],
                         "horizontal_half_width_local": 0.035,
                         "horizontal_width_axis_local": width_axis.tolist(),
                         "z_range": [-0.425, -0.350],
                         "centreline": "eye_local + ray_local * distance_cm / 2027",
                         "note": "Short oblique chamber-to-exterior lancet recess in derivative mesh only; validate actual Boolean and UVs."},
    }
    if args.mesh_ray:
        hits = mesh_hits(eye, ray)
        report["source_mesh_hits_cm"] = [round(x, 2) for x in hits]
        report["source_hit_points_local"] = [
            [round(float(value), 5) for value in eye + ray * distance / SCALE_CM]
            for distance in hits
        ]
        report["source_hits_inside_proposed_cut"] = bool(hits) and all(
            cut_start_cm <= distance <= cut_end_cm
            and -0.425 <= (eye + ray * distance / SCALE_CM)[2] <= -0.350
            for distance in hits
        )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
