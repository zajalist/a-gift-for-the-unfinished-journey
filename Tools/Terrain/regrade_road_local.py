#!/usr/bin/env python3
"""Build a review-only, localized 42-degree road heightmap candidate.

    python Tools/Terrain/regrade_road_local.py

Never writes Current_u16.png, Unreal Content, or the live Landscape. The
candidate is deliberately not approved for import until live collision and
visual checks pass. See ROAD_TRAVERSABILITY.md.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter
from scipy.optimize import linprog
from scipy.sparse import lil_matrix
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from Tools.Story import build_road_profile as road_profile  # noqa: E402
from Tools.Terrain.diagnose_road_traversability import diagnose  # noqa: E402
from Tools.Terrain.regrade_road import apply_corridor_delta, _terrain_slope_summary  # noqa: E402


WINDOWS_M = ((3508, 3532), (3548, 3668), (3680, 3720), (3908, 3942))
PROFILE_CAP_DEG = 42.0
BED_HALF_WIDTH_M = 2.75
FEATHER_M = 20.0
END_TAPER_M = 8.0
FIELD_SMOOTH_SIGMA_M = 4.0
SMOOTH_BEGIN_M = 2.5
SMOOTH_BLEND_M = 2.0
FIELD_FADE_START_M = 23.0
FIELD_FADE_END_M = 31.0
DEFAULT_OUT = ROOT / "Saved/TerrainRegrade/local42_review_u16.png"


def _smoothstep01(x: np.ndarray) -> np.ndarray:
    v = np.clip(x, 0.0, 1.0)
    return v * v * (3.0 - 2.0 * v)


def minimax_profile_delta(stations: np.ndarray, original_m: np.ndarray, cap_deg: float) -> np.ndarray:
    """Smallest possible max centerline correction under a one-metre grade cap.

    Fixed endpoints keep adjacent untouched profile heights continuous. This
    linear program is only the longitudinal target; the raster is gated again.
    """
    s, z = np.asarray(stations, float), np.asarray(original_m, float)
    if s.ndim != 1 or z.shape != s.shape or len(s) < 2 or np.any(np.diff(s) <= 0):
        raise ValueError("invalid ordered profile")
    cap = math.tan(math.radians(cap_deg))
    n = len(s)
    matrix = lil_matrix((4 * n - 2, n + 1))
    rhs = np.zeros(4 * n - 2)
    for i in range(1, n):
        allowance = cap * (s[i] - s[i - 1])
        rise = z[i] - z[i - 1]
        matrix[i - 1, i], matrix[i - 1, i - 1] = 1, -1
        rhs[i - 1] = allowance - rise
        opposite = n + i - 2
        matrix[opposite, i], matrix[opposite, i - 1] = -1, 1
        rhs[opposite] = allowance + rise
    for i in range(n):
        upper, lower = 2 * n - 2 + i, 3 * n - 2 + i
        matrix[upper, i], matrix[upper, n] = 1, -1
        matrix[lower, i], matrix[lower, n] = -1, -1
    objective = np.zeros(n + 1)
    objective[-1] = 1.0
    bounds = [(None, None)] * n + [(0, None)]
    bounds[0] = bounds[n - 1] = (0, 0)
    result = linprog(objective, A_ub=matrix.tocsr(), b_ub=rhs, bounds=bounds, method="highs")
    if not result.success:
        raise ValueError(f"no feasible fixed-endpoint profile: {result.message}")
    delta = result.x[:-1]
    if abs(delta[0]) > 1e-7 or abs(delta[-1]) > 1e-7:
        raise RuntimeError("profile endpoints moved")
    if max(abs(np.diff(z + delta) / np.diff(s))) > cap + 1e-6:
        raise RuntimeError("profile grade cap not met")
    return delta


def _crop_bounds(xy_m: np.ndarray, pad_m: float, shape: tuple[int, int]) -> tuple[int, int, int, int]:
    x0, y0 = road_profile.LAND_X0_CM / 100.0, road_profile.LAND_Y0_CM / 100.0
    left = max(0, int(math.floor(xy_m[:, 0].min() - pad_m - x0)))
    right = min(shape[1], int(math.ceil(xy_m[:, 0].max() + pad_m - x0)) + 1)
    top = max(0, int(math.floor(xy_m[:, 1].min() - pad_m - y0)))
    bottom = min(shape[0], int(math.ceil(xy_m[:, 1].max() + pad_m - y0)) + 1)
    if left >= right or top >= bottom:
        raise ValueError("candidate crop outside source heightmap")
    return left, top, right, bottom


def _first_pass(source_u16: np.ndarray, terrain: road_profile.Terrain,
                road: road_profile.Road) -> tuple[np.ndarray, list[dict]]:
    out = source_u16.copy()
    windows = []
    x0, y0 = road_profile.LAND_X0_CM / 100.0, road_profile.LAND_Y0_CM / 100.0
    for start, end in WINDOWS_M:
        stations = np.arange(float(start), float(end) + 1.0)
        xy_cm = road.xy(stations)
        xy_m = xy_cm / 100.0
        before = terrain.height(xy_cm[:, 0], xy_cm[:, 1])
        delta = minimax_profile_delta(stations, before, PROFILE_CAP_DEG)
        left, top, right, bottom = _crop_bounds(xy_m, BED_HALF_WIDTH_M + FEATHER_M + 3.0, out.shape)
        # Compose from the preceding window, because footprints overlap at the
        # switchback. Starting each crop from source would erase an earlier cut.
        original_crop = (out[top:bottom, left:right].astype(np.float32) - 32768.0) / 64.0
        flat = apply_corridor_delta(
            original_crop, (x0 + left, y0 + top), xy_m, stations, delta, before,
            road_half_width_m=BED_HALF_WIDTH_M, feather_m=FEATHER_M, crossfall_grade=0.02,
        )
        rows, cols = np.indices(original_crop.shape)
        pixels = np.column_stack((x0 + left + cols.ravel(), y0 + top + rows.ravel()))
        nearest = cKDTree(xy_m).query(pixels, k=1)[1]
        near_station = stations[nearest].reshape(original_crop.shape)
        weight = (_smoothstep01((near_station - start) / END_TAPER_M) *
                  _smoothstep01((end - near_station) / END_TAPER_M))
        encoded = np.rint((original_crop + weight * (flat - original_crop)) * 64.0 + 32768.0)
        if encoded.min() < 0 or encoded.max() > 65535:
            raise ValueError("height outside uint16 range")
        out[top:bottom, left:right] = encoded.astype(np.uint16)
        windows.append({"road_m": [start, end], "max_profile_correction_m": round(float(max(abs(delta))), 3)})
    return out, windows


def _smooth_switchback_field(source_u16: np.ndarray, first_pass_u16: np.ndarray,
                             road: road_profile.Road) -> np.ndarray:
    changed = source_u16 != first_pass_u16
    rows, cols = np.nonzero(changed)
    if not len(rows):
        raise RuntimeError("first pass made no correction")
    left = max(0, int(cols.min()) - 25)
    right = min(source_u16.shape[1], int(cols.max()) + 26)
    top = max(0, int(rows.min()) - 25)
    bottom = min(source_u16.shape[0], int(rows.max()) + 26)
    base = (source_u16[top:bottom, left:right].astype(np.float32) - 32768.0) / 64.0
    staged = (first_pass_u16[top:bottom, left:right].astype(np.float32) - 32768.0) / 64.0
    delta = staged - base
    yy, xx = np.indices(base.shape)
    x0, y0 = road_profile.LAND_X0_CM / 100.0, road_profile.LAND_Y0_CM / 100.0
    xy = np.column_stack((x0 + left + xx.ravel(), y0 + top + yy.ravel()))
    stations = np.arange(3450.0, 3951.0)
    distance = cKDTree(road.xy(stations) / 100.0).query(xy, k=1)[0].reshape(base.shape)
    # Hard nearest-road ownership creates a seam where switchback arms compete.
    # Blend their delta field outside the drive bed, preserving the center core.
    blend = _smoothstep01((distance - SMOOTH_BEGIN_M) / SMOOTH_BLEND_M)
    fade = _smoothstep01((FIELD_FADE_END_M - distance) /
                         (FIELD_FADE_END_M - FIELD_FADE_START_M))
    smoothed = gaussian_filter(delta, sigma=FIELD_SMOOTH_SIGMA_M, mode="nearest")
    final = base + (delta * (1.0 - blend) + smoothed * blend) * fade
    encoded = np.rint(final * 64.0 + 32768.0)
    if encoded.min() < 0 or encoded.max() > 65535:
        raise ValueError("smoothed height outside uint16 range")
    out = source_u16.copy()
    out[top:bottom, left:right] = encoded.astype(np.uint16)
    return out


def prepare(source: Path, output: Path) -> dict:
    Image.MAX_IMAGE_PIXELS = None
    with Image.open(source) as image:
        source_u16 = np.asarray(image)
    if source_u16.dtype != np.uint16 or source_u16.shape != (8161, 8161):
        raise ValueError("expected current 8161x8161 uint16 Landscape mapping")
    terrain = road_profile.Terrain(source)
    road = road_profile.Road(road_profile.SPLINE_POINTS_CM)
    first_pass, windows = _first_pass(source_u16, terrain, road)
    final_u16 = _smooth_switchback_field(source_u16, first_pass, road)
    output.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(final_u16).save(output)
    gate = diagnose(output, 3450.0, 4200.0)

    changed = source_u16 != final_u16
    yy, xx = np.nonzero(changed)
    left, right = max(0, int(xx.min()) - 2), min(source_u16.shape[1], int(xx.max()) + 3)
    top, bottom = max(0, int(yy.min()) - 2), min(source_u16.shape[0], int(yy.max()) + 3)
    source_crop = (source_u16[top:bottom, left:right].astype(np.float32) - 32768.0) / 64.0
    final_crop = (final_u16[top:bottom, left:right].astype(np.float32) - 32768.0) / 64.0
    summary = _terrain_slope_summary(
        source_crop, final_crop,
        (road_profile.LAND_X0_CM / 100.0 + left, road_profile.LAND_Y0_CM / 100.0 + top),
        road.xy(np.arange(3450.0, 3951.0)) / 100.0, (3.0, 10.0, 23.0, 31.0),
    )
    delta_u16 = final_u16.astype(np.int32) - source_u16.astype(np.int32)
    report = {
        "candidate_only": True,
        "approved_for_import": False,
        "editor_or_content_touched": False,
        "road_xy_changed": False,
        "source": str(source),
        "candidate": str(output),
        "windows_m": windows,
        "profile_cap_deg": PROFILE_CAP_DEG,
        "bed_half_width_m": BED_HALF_WIDTH_M,
        "lateral_feather_m": FEATHER_M,
        "field_sigma_m": FIELD_SMOOTH_SIGMA_M,
        "changed_pixels": int(changed.sum()),
        "max_cut_m": float(delta_u16.min() / 64.0),
        "max_fill_m": float(delta_u16.max() / 64.0),
        "road_gate": gate,
        "terrain_slope_by_road_buffer": summary,
    }
    report_path = output.with_name(output.stem.removesuffix("_u16") + "_report.json")
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    source_max = summary["within_31m"]["source_max_degrees"]
    candidate_max = summary["within_31m"]["candidate_max_degrees"]
    if (gate["red"] or gate["thresholds"]["configured_50_deg"]["center_floor_point_count"] or
            gate["thresholds"]["default_44_765_deg"]["full_core_barrier_point_count"] or
            candidate_max > source_max + 0.1):
        raise RuntimeError(f"candidate failed offline traversability/flank gate; inspect {report_path}")
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", type=Path, default=road_profile.HEIGHTMAP)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()
    report = prepare(args.source, args.out)
    print(f"REVIEW ONLY: {report['changed_pixels']} pixels, cut {report['max_cut_m']:.2f} m, "
          f"fill {report['max_fill_m']:.2f} m; offline road/flank gates passed; "
          f"runtime acceptance and import approval pending")


if __name__ == "__main__":
    main()
