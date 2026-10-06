#!/usr/bin/env python3
"""Read-only Landscape road-grade gate; never imports or changes terrain.

    python Tools/Terrain/diagnose_road_traversability.py

Writes a JSON report under Saved/TerrainRegrade and exits 1 if a sampled
full-width barrier exceeds the configured 50-degree carrier floor angle.
The 44.765-degree engine default is reported separately. These finite-
difference normals are an offline approximation to Landscape collision.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from Tools.Story import build_road_profile as road_profile  # noqa: E402


DEFAULT_REPORT = ROOT / "Saved/TerrainRegrade/traversability_current.json"
BASELINE_DEG = 44.765
CONFIGURED_DEG = 50.0  # Tools/GameFlow/gen_carrier_drive.py StartCarrierExtras
CORE_HALF_WIDTH_M = 2.25  # Tools/Road/ROAD.md RoadHalfWidth


def _spans(mask: np.ndarray, stations: np.ndarray, values: np.ndarray) -> list[dict]:
    indices = np.flatnonzero(mask)
    if not len(indices):
        return []
    result = []
    for group in np.split(indices, np.flatnonzero(np.diff(indices) > 1) + 1):
        peak = group[int(np.argmax(values[group]))]
        result.append({
            "start_m": float(stations[group[0]]),
            "end_m": float(stations[group[-1]]),
            "peak_m": float(stations[peak]),
            "peak_deg": round(float(values[peak]), 3),
        })
    return result


def diagnose(source: Path, start_m: float, end_m: float) -> dict:
    road = road_profile.Road(road_profile.SPLINE_POINTS_CM)
    if not 0 <= start_m < end_m <= road.length:
        raise ValueError(f"invalid road window {start_m}..{end_m}; length {road.length:.1f} m")
    terrain = road_profile.Terrain(source)
    stations = np.arange(start_m, end_m + 0.5, 1.0)
    xy_cm = road.xy(stations)
    tangent = np.gradient(xy_cm, axis=0)
    tangent /= np.maximum(np.linalg.norm(tangent, axis=1, keepdims=True), 1e-9)
    normal = np.column_stack((-tangent[:, 1], tangent[:, 0]))
    offsets_m = np.linspace(-CORE_HALF_WIDTH_M, CORE_HALF_WIDTH_M, 19)
    x = xy_cm[:, 0, None] + normal[:, 0, None] * offsets_m[None, :] * 100.0
    y = xy_cm[:, 1, None] + normal[:, 1, None] * offsets_m[None, :] * 100.0
    z = terrain.height(x, y)
    center_z = z[:, len(offsets_m) // 2]
    longitudinal_deg = np.degrees(np.arctan(np.diff(center_z) / np.diff(stations)))
    # One-metre central differences in world X/Y approximate the floor normal.
    grad_x = (terrain.height(x + 100.0, y) - terrain.height(x - 100.0, y)) / 2.0
    grad_y = (terrain.height(x, y + 100.0) - terrain.height(x, y - 100.0)) / 2.0
    floor_deg = np.degrees(np.arctan(np.hypot(grad_x, grad_y)))
    center_floor = floor_deg[:, len(offsets_m) // 2]
    least_steep_across_core = np.min(floor_deg, axis=1)
    intervals = []
    for a, b in ((3450, 3600), (3600, 3700), (3700, 3860), (3860, 3950), (3950, 4200)):
        lo, hi = max(float(a), start_m), min(float(b), end_m)
        if hi <= lo:
            continue
        edges = (stations[:-1] >= lo) & (stations[:-1] < hi)
        points = (stations >= lo) & (stations < hi)
        intervals.append({
            "road_m": [lo, hi],
            "center_rise_m": round(float(np.interp(hi, stations, center_z) - np.interp(lo, stations, center_z)), 3),
            "max_center_uphill_deg": round(float(np.max(longitudinal_deg[edges])), 3),
            "max_center_floor_deg": round(float(np.max(center_floor[points])), 3),
            "center_uphill_edges_over_44_765": int(np.count_nonzero(longitudinal_deg[edges] > BASELINE_DEG)),
            "center_floor_points_over_50": int(np.count_nonzero(center_floor[points] > CONFIGURED_DEG)),
            "full_core_barrier_points_over_50": int(np.count_nonzero(least_steep_across_core[points] > CONFIGURED_DEG)),
        })
    thresholds = {}
    for name, cap in (("default_44_765_deg", BASELINE_DEG), ("configured_50_deg", CONFIGURED_DEG)):
        thresholds[name] = {
            "center_uphill_edge_spans": _spans(longitudinal_deg > cap, stations[:-1], longitudinal_deg),
            "center_floor_spans": _spans(center_floor > cap, stations, center_floor),
            "full_core_barrier_spans": _spans(least_steep_across_core > cap, stations, least_steep_across_core),
            "center_uphill_edge_count": int(np.count_nonzero(longitudinal_deg > cap)),
            "center_floor_point_count": int(np.count_nonzero(center_floor > cap)),
            "full_core_barrier_point_count": int(np.count_nonzero(least_steep_across_core > cap)),
        }
    at_3670 = int(np.argmin(abs(stations - 3670.0)))
    return {
        "source": str(source),
        "heightmap_pixels": [terrain.cols, terrain.rows],
        "heightmap_origin_cm": [road_profile.LAND_X0_CM, road_profile.LAND_Y0_CM],
        "xy_cm_per_pixel": road_profile.PX_CM,
        "z_cm_per_u16_step": road_profile.Z_SCALE / 128.0,
        "road_window_m": [start_m, end_m],
        "station_step_m": 1.0,
        "road_core_half_width_m": CORE_HALF_WIDTH_M,
        "lateral_step_m": float(offsets_m[1] - offsets_m[0]),
        "normal_method": "bilinear height at XY +/-1m central differences; approximate collision normal",
        "configured_walkable_floor_deg": CONFIGURED_DEG,
        "default_walkable_floor_deg": BASELINE_DEG,
        "at_3670_m": {
            "center_floor_deg": round(float(center_floor[at_3670]), 3),
            "core_floor_min_deg": round(float(least_steep_across_core[at_3670]), 3),
            "core_floor_max_deg": round(float(np.max(floor_deg[at_3670])), 3),
        },
        "intervals": intervals,
        "thresholds": thresholds,
        "red": thresholds["configured_50_deg"]["full_core_barrier_point_count"] > 0,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", type=Path, default=road_profile.HEIGHTMAP)
    ap.add_argument("--out", type=Path, default=DEFAULT_REPORT)
    ap.add_argument("--start-m", type=float, default=3450.0)
    ap.add_argument("--end-m", type=float, default=4200.0)
    args = ap.parse_args()
    report = diagnose(args.source, args.start_m, args.end_m)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    status = "RED" if report["red"] else "PASS"
    print(f"{status}: {report['thresholds']['configured_50_deg']['full_core_barrier_point_count']} "
          f"full-core impassable station(s) at 50 degrees; report={args.out}")
    return 1 if report["red"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
