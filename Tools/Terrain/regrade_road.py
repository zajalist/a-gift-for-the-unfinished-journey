#!/usr/bin/env python3
"""Prepare an offline candidate terrain regrade under the Saskarta road.

This tool never writes the authoritative heightmap or Unreal Content. It reads
``Saved/TerrainRebuild/Current_u16.png`` and emits a candidate, profile data,
plot, and report under ``Saved/TerrainRegrade``.

    python Tools/Terrain/regrade_road.py

The road XY comes from ``Tools/Story/build_road_profile.py``. The requested
segment is shaped between fixed-height blend anchors, then that vertical change
is feathered across the landscape rather than cut as a narrow trench.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter1d
from scipy.spatial import cKDTree


ROOT = Path(__file__).resolve().parents[2]
SOURCE_HEIGHTMAP = ROOT / "Saved" / "TerrainRebuild" / "Current_u16.png"
OUTPUT_DIR = ROOT / "Saved" / "TerrainRegrade"

START_M = 3450.0
END_M = 3950.0
TARGET_CAP_DEG = 42.0
HARD_CAP_DEG = 44.765
ROAD_HALF_WIDTH_M = 3.0
FEATHER_M = 20.0
CROSS_FALL_GRADE = 0.02
PROFILE_STEP_M = 1.0
PROFILE_SMOOTH_SIGMA_M = 4.0
END_EASE_M = 20.0

LAND_X0_CM = -18920.4
LAND_Y0_CM = 50.0
PIXEL_CM = 100.0
HEIGHT_SCALE_CM = 200.0


class InfeasibleRegradeError(ValueError):
    """Raised when fixed endpoint heights cannot satisfy a grade cap."""


def cap_profile_grade(
    distance_m: np.ndarray,
    elevation_m: np.ndarray,
    max_grade: float,
    smooth_sigma_m: float = PROFILE_SMOOTH_SIGMA_M,
) -> np.ndarray:
    """Return a smoothed profile under an absolute grade cap, fixing endpoints.

    ``max_grade`` is rise/run (0.70 means 70%). Repeated forward/backward
    projections enforce adjacent grade inequalities; feasibility is checked
    before changing any interior point.
    """
    s = np.asarray(distance_m, dtype=np.float64)
    z = np.asarray(elevation_m, dtype=np.float64)
    if s.ndim != 1 or z.ndim != 1 or s.shape != z.shape or len(s) < 2:
        raise ValueError("distance and elevation must be matching 1-D arrays")
    if not np.all(np.isfinite(s)) or not np.all(np.isfinite(z)):
        raise ValueError("distance and elevation must be finite")
    ds = np.diff(s)
    if np.any(ds <= 0):
        raise ValueError("distance samples must be strictly increasing")
    if not math.isfinite(max_grade) or max_grade <= 0:
        raise ValueError("max_grade must be positive and finite")

    start_z, end_z = float(z[0]), float(z[-1])
    rise = end_z - start_z
    available = max_grade * float(s[-1] - s[0])
    if abs(rise) > available + 1e-9:
        raise InfeasibleRegradeError(
            f"endpoint rise {rise:.3f} m over {s[-1] - s[0]:.1f} m exceeds "
            f"the grade cap's {available:.3f} m allowance"
        )

    if smooth_sigma_m > 0:
        sigma_samples = smooth_sigma_m / float(np.median(ds))
        shaped = gaussian_filter1d(z, sigma=sigma_samples, mode="nearest")
    else:
        shaped = z.copy()
    shaped[0], shaped[-1] = start_z, end_z

    # Alternating projections onto adjacent upper/lower grade constraints.
    # Each pass fixes one side of every violated edge; iteration handles the
    # neighboring edge affected by that correction. Endpoints remain exact.
    for _ in range(max(100, len(s) * 2)):
        previous = shaped.copy()
        for i, step in enumerate(ds, start=1):
            allowance = max_grade * step
            shaped[i] = np.clip(shaped[i], shaped[i - 1] - allowance,
                                shaped[i - 1] + allowance)
        shaped[-1] = end_z
        for i in range(len(shaped) - 2, -1, -1):
            allowance = max_grade * ds[i]
            shaped[i] = np.clip(shaped[i], shaped[i + 1] - allowance,
                                shaped[i + 1] + allowance)
        shaped[0] = start_z
        if np.max(np.abs(shaped - previous)) < 1e-10:
            break

    actual = np.abs(np.diff(shaped) / ds)
    if float(actual.max()) > max_grade + 1e-8:
        raise RuntimeError(f"grade projection did not converge (max {actual.max():.6f})")
    shaped[0], shaped[-1] = start_z, end_z
    return shaped


def _smoothstep01(x: np.ndarray) -> np.ndarray:
    x = np.clip(np.asarray(x, dtype=np.float64), 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


def ease_profile_delta(
    distance_m: np.ndarray,
    start_m: float,
    end_m: float,
    delta_m: np.ndarray,
    ease_m: float = END_EASE_M,
) -> np.ndarray:
    """Fade a profile change to zero at fixed-height window endpoints."""
    s = np.asarray(distance_m, dtype=np.float64)
    delta = np.asarray(delta_m, dtype=np.float64)
    if s.shape != delta.shape or np.any(np.diff(s) <= 0):
        raise ValueError("profile distance and delta must match and increase")
    if not start_m < end_m or ease_m <= 0 or 2 * ease_m > end_m - start_m:
        raise ValueError("invalid profile ease window")
    weight = _smoothstep01((s - start_m) / ease_m) * _smoothstep01((end_m - s) / ease_m)
    return delta * weight


def apply_corridor_delta(
    height_m: np.ndarray,
    origin_xy_m: tuple[float, float],
    center_xy_m: np.ndarray,
    center_s_m: np.ndarray,
    center_delta_m: np.ndarray,
    center_elevation_m: np.ndarray,
    road_half_width_m: float = ROAD_HALF_WIDTH_M,
    feather_m: float = FEATHER_M,
    crossfall_grade: float = 0.02,
) -> np.ndarray:
    """Apply a road-profile elevation delta with a smooth lateral feather.

    The input raster is a cropped heightmap. Its origin is the world XY of
    pixel [0, 0], and raster rows increase with world Y. The full drive width
    is formed into a shallow plane; the next ``feather_m`` fades smoothly to
    the original terrain.
    """
    h = np.asarray(height_m, dtype=np.float32)
    xy = np.asarray(center_xy_m, dtype=np.float64)
    s = np.asarray(center_s_m, dtype=np.float64)
    delta = np.asarray(center_delta_m, dtype=np.float64)
    center_z = np.asarray(center_elevation_m, dtype=np.float64)
    if (h.ndim != 2 or xy.ndim != 2 or xy.shape[1] != 2 or
            s.shape != delta.shape or s.shape != center_z.shape or s.shape != (len(xy),)):
        raise ValueError("invalid heightmap or centerline arrays")
    if len(s) < 2 or np.any(np.diff(s) <= 0):
        raise ValueError("centerline distance must strictly increase")
    if road_half_width_m <= 0 or feather_m <= 0:
        raise ValueError("road half-width and feather must be positive")
    if not math.isfinite(crossfall_grade) or abs(crossfall_grade) > 0.10:
        raise ValueError("crossfall_grade must be finite and within ±10%")

    x0, y0 = map(float, origin_xy_m)
    yy, xx = np.indices(h.shape, dtype=np.float64)
    points = np.column_stack((x0 + xx.ravel(), y0 + yy.ravel()))
    # A nearest *sample* creates stair steps on diagonal roads. Use the sample
    # tree only to find the neighboring polyline segments, then project every
    # raster pixel onto those exact segments and interpolate station there.
    _, nearest_sample = cKDTree(xy).query(points, k=1, workers=1)
    segment_a = np.maximum(nearest_sample - 1, 0)
    segment_b = np.minimum(nearest_sample, len(xy) - 2)

    def project(segment: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        a = xy[segment]
        vector = xy[segment + 1] - a
        length = np.maximum(np.linalg.norm(vector, axis=1), 1e-12)
        fraction = np.sum((points - a) * vector, axis=1) / np.maximum(np.sum(vector * vector, axis=1), 1e-12)
        fraction = np.clip(fraction, 0.0, 1.0)
        projected = a + fraction[:, None] * vector
        d = np.linalg.norm(points - projected, axis=1)
        station = s[segment] + fraction * (s[segment + 1] - s[segment])
        lateral = (vector[:, 0] * (points[:, 1] - projected[:, 1]) -
                   vector[:, 1] * (points[:, 0] - projected[:, 0])) / length
        return d, station, lateral

    distance_a, station_a, lateral_a = project(segment_a)
    distance_b, station_b, lateral_b = project(segment_b)
    choose_a = distance_a <= distance_b
    distance = np.where(choose_a, distance_a, distance_b)
    station = np.where(choose_a, station_a, station_b)
    lateral = np.where(choose_a, lateral_a, lateral_b)
    radius = road_half_width_m + feather_m
    active = distance < radius
    weight = np.zeros(len(points), dtype=np.float64)
    weight[active & (distance <= road_half_width_m)] = 1.0
    feathering = active & (distance > road_half_width_m)
    t = (distance[feathering] - road_half_width_m) / feather_m
    weight[feathering] = 1.0 - _smoothstep01(t)

    target_center_z = np.interp(station[active], s, center_z + delta)
    target_surface_z = target_center_z + crossfall_grade * lateral[active]
    result = h.copy().ravel()
    result[active] += (weight[active] * (target_surface_z - result[active])).astype(np.float32)
    return result.reshape(h.shape)


def _bilinear(values: np.ndarray, x_px: np.ndarray, y_px: np.ndarray) -> np.ndarray:
    rows, cols = values.shape
    x = np.clip(np.asarray(x_px, dtype=np.float64), 0, cols - 1.000001)
    y = np.clip(np.asarray(y_px, dtype=np.float64), 0, rows - 1.000001)
    x0, y0 = np.floor(x).astype(np.int64), np.floor(y).astype(np.int64)
    fx, fy = x - x0, y - y0
    a = values[y0, x0].astype(np.float64)
    b = values[y0, x0 + 1].astype(np.float64)
    c = values[y0 + 1, x0].astype(np.float64)
    d = values[y0 + 1, x0 + 1].astype(np.float64)
    return a * (1 - fx) * (1 - fy) + b * fx * (1 - fy) + c * (1 - fx) * fy + d * fx * fy


def _terrain_slope_summary(
    source_z: np.ndarray,
    candidate_z: np.ndarray,
    origin_xy_m: tuple[float, float],
    road_xy_m: np.ndarray,
    radii_m: tuple[float, ...] = (3.0, 10.0, ROAD_HALF_WIDTH_M + FEATHER_M),
) -> dict:
    """Compare combined terrain grades in nested buffers around the road."""
    if source_z.shape != candidate_z.shape or source_z.ndim != 2:
        raise ValueError("source and candidate crops must be matching 2-D arrays")
    if not np.all(np.isfinite(source_z)) or not np.all(np.isfinite(candidate_z)):
        raise ValueError("terrain crops must be finite")
    x0, y0 = map(float, origin_xy_m)
    rows, cols = source_z.shape
    yy, xx = np.indices((rows, cols), dtype=np.float64)
    world_points = np.column_stack((x0 + xx.ravel(), y0 + yy.ravel()))
    road_distance = cKDTree(np.asarray(road_xy_m, dtype=np.float64)).query(
        world_points, k=1, workers=1
    )[0].reshape((rows, cols))

    def angle_degrees(z: np.ndarray) -> np.ndarray:
        # One-metre central differences match the heightmap pixel spacing.
        dz_dy, dz_dx = np.gradient(np.asarray(z, dtype=np.float64), 1.0, 1.0)
        return np.degrees(np.arctan(np.hypot(dz_dx, dz_dy)))

    before_angle = angle_degrees(source_z)
    after_angle = angle_degrees(candidate_z)
    summary = {}
    for radius in radii_m:
        mask = road_distance <= radius
        before = before_angle[mask]
        after = after_angle[mask]
        summary[f"within_{radius:g}m"] = {
            "pixels": int(mask.sum()),
            "source_p95_degrees": float(np.percentile(before, 95)),
            "source_max_degrees": float(before.max()),
            "candidate_p95_degrees": float(np.percentile(after, 95)),
            "candidate_max_degrees": float(after.max()),
        }
    return summary


def _load_profile_dependencies():
    import sys

    sys.path.insert(0, str(ROOT / "Tools" / "Story"))
    import build_road_profile as brp  # noqa: E402

    return brp


def _write_plot(path: Path, distance: np.ndarray, before: np.ndarray, after: np.ndarray,
                target_cap_deg: float) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    grade_before = np.gradient(before, distance) * 100.0
    grade_after = np.gradient(after, distance) * 100.0
    fig, (ax_z, ax_grade) = plt.subplots(2, 1, figsize=(12, 7), sharex=True)
    ax_z.plot(distance, before, color="#9a6f55", label="Source height")
    ax_z.plot(distance, after, color="#287c78", label="Candidate height")
    ax_z.set_ylabel("Road elevation (m)")
    ax_z.legend(loc="upper left")
    ax_z.grid(alpha=0.25)
    ax_grade.plot(distance, grade_before, color="#9a6f55", alpha=0.75, label="Source grade")
    ax_grade.plot(distance, grade_after, color="#287c78", label="Candidate grade")
    hard = math.tan(math.radians(HARD_CAP_DEG)) * 100
    ax_grade.axhline(hard, color="#b5443f", linestyle="--", linewidth=1, label="35° cap")
    ax_grade.axhline(-hard, color="#b5443f", linestyle="--", linewidth=1)
    ax_grade.set_ylabel("Grade (%)")
    ax_grade.set_xlabel("Road distance from boot (m)")
    ax_grade.grid(alpha=0.25)
    ax_grade.legend(loc="upper left", ncol=3)
    fig.suptitle(f"Road regrade candidate — fixed endpoints, {target_cap_deg:g}° design cap")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def _write_corridor_plot(
    path: Path,
    source_z: np.ndarray,
    candidate_z: np.ndarray,
    pixel_bounds: tuple[int, int, int, int],
    origin_xy_m: tuple[float, float],
    road_xy_m: np.ndarray,
    start_m: float,
    end_m: float,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import TwoSlopeNorm

    col0, row0, col1, row1 = pixel_bounds
    before = source_z[row0:row1, col0:col1]
    after = candidate_z[row0:row1, col0:col1]
    delta = after - before
    x0, y0 = origin_xy_m
    extent = (x0 + col0, x0 + col1 - 1, y0 + row0, y0 + row1 - 1)
    vmin, vmax = np.percentile(source_z[row0:row1, col0:col1], (2, 98))
    max_cut = max(abs(float(delta.min())), 0.1)
    max_fill = max(float(delta.max()), 0.1)
    fig, axes = plt.subplots(1, 3, figsize=(17, 8), constrained_layout=True)
    for ax, image, title in zip(axes[:2], (before, after), ("Source terrain", "Candidate terrain")):
        plot = ax.imshow(image, origin="lower", extent=extent, cmap="terrain", vmin=vmin, vmax=vmax,
                         interpolation="nearest")
        ax.plot(road_xy_m[:, 0], road_xy_m[:, 1], color="white", linewidth=1.2, label="Road centerline")
        ax.scatter(road_xy_m[0, 0], road_xy_m[0, 1], marker="o",
                   color="#35e0ce", edgecolor="black", s=45, zorder=4, label=f"{start_m:.0f} m anchor")
        ax.scatter(road_xy_m[-1, 0], road_xy_m[-1, 1], marker="s", color="#f7c64b",
                   edgecolor="black", s=40, zorder=4, label=f"{end_m:.0f} m anchor")
        ax.set_title(title)
        ax.set_xlabel("World X (m)")
        ax.set_ylabel("World Y (m)")
        ax.legend(loc="best", fontsize=8)
        fig.colorbar(plot, ax=ax, shrink=0.78, label="Elevation (m)")
    norm = TwoSlopeNorm(vmin=-max_cut, vcenter=0.0, vmax=max_fill)
    plot = axes[2].imshow(delta, origin="lower", extent=extent, cmap="RdBu_r", norm=norm,
                          interpolation="nearest")
    axes[2].plot(road_xy_m[:, 0], road_xy_m[:, 1], color="black", linewidth=1.2)
    axes[2].set_title("Signed height change (candidate − source)")
    axes[2].set_xlabel("World X (m)")
    axes[2].set_ylabel("World Y (m)")
    fig.colorbar(plot, ax=axes[2], shrink=0.78, label="Height change (m); blue = cut")
    fig.suptitle("Road grade rework corridor — candidate only")
    fig.savefig(path, dpi=150)
    plt.close(fig)


def _cross_section_data(
    source_z: np.ndarray,
    candidate_z: np.ndarray,
    road_xy_cm: np.ndarray,
    distance_m: np.ndarray,
    center_index: int,
    origin_xy_cm: tuple[float, float],
    half_width_m: float = ROAD_HALF_WIDTH_M,
    feather_m: float = FEATHER_M,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    tangent = road_xy_cm[min(center_index + 1, len(road_xy_cm) - 1), :2] - \
              road_xy_cm[max(center_index - 1, 0), :2]
    tangent = tangent / max(float(np.linalg.norm(tangent)), 1e-9)
    normal = np.array([-tangent[1], tangent[0]])
    total_half_width = half_width_m + feather_m
    offsets = np.arange(-total_half_width, total_half_width + 0.01, 1.0)
    xy_cm = road_xy_cm[center_index, :2] + offsets[:, None] * 100.0 * normal
    px = (xy_cm[:, 0] - origin_xy_cm[0]) / PIXEL_CM
    py = (xy_cm[:, 1] - origin_xy_cm[1]) / PIXEL_CM
    return offsets, _bilinear(source_z, px, py), _bilinear(candidate_z, px, py)


def _write_cross_section_plot(
    path: Path,
    source_z: np.ndarray,
    candidate_z: np.ndarray,
    road_xy_cm: np.ndarray,
    distance_m: np.ndarray,
    origin_xy_cm: tuple[float, float],
    stations_m: tuple[float, float],
    half_width_m: float = ROAD_HALF_WIDTH_M,
    feather_m: float = FEATHER_M,
) -> list[dict]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, len(stations_m), figsize=(13, 5), squeeze=False)
    results = []
    for ax, station in zip(axes[0], stations_m):
        i = int(np.argmin(np.abs(distance_m - station)))
        offsets, before, after = _cross_section_data(
            source_z, candidate_z, road_xy_cm, distance_m, i, origin_xy_cm,
            half_width_m, feather_m,
        )
        ax.plot(offsets, before, color="#9a6f55", label="Source terrain")
        ax.plot(offsets, after, color="#287c78", label="Candidate")
        ax.axvspan(-half_width_m, half_width_m, color="#58b8b0", alpha=0.15,
                   label="6 m drive width")
        ax.axvline(-half_width_m, color="#477c76", linestyle=":", linewidth=0.8)
        ax.axvline(half_width_m, color="#477c76", linestyle=":", linewidth=0.8)
        ax.axvline(-(half_width_m + feather_m), color="#666", linestyle="--", linewidth=0.8)
        ax.axvline(half_width_m + feather_m, color="#666", linestyle="--", linewidth=0.8,
                   label=f"{feather_m:g} m feather edge")
        ax.set_title(f"Road {station:.0f} m")
        ax.set_xlabel("Offset across road (m)")
        ax.set_ylabel("Elevation (m)")
        ax.grid(alpha=0.25)
        ax.legend(loc="best", fontsize=8)
        core = np.flatnonzero((offsets >= -half_width_m) & (offsets <= half_width_m))
        lateral_grade = np.abs(np.diff(after[core]) / np.diff(offsets[core]))
        results.append({
            "road_m": float(distance_m[i]),
            "cross_grade_max_in_drive_width_pct": float(lateral_grade.max() * 100.0),
            "cross_angle_max_in_drive_width_degrees": math.degrees(math.atan(float(lateral_grade.max()))),
            "cross_grade_p95_over_full_feather_pct": float(np.percentile(np.abs(np.diff(after) / np.diff(offsets)), 95) * 100.0),
        })
    fig.suptitle("Terrain cross-sections: full-width road bed and feather")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return results


def prepare_candidate(
    source_path: Path = SOURCE_HEIGHTMAP,
    output_dir: Path = OUTPUT_DIR,
    start_m: float = START_M,
    end_m: float = END_M,
    target_cap_deg: float = TARGET_CAP_DEG,
    feather_m: float = FEATHER_M,
) -> dict:
    """Build candidate heightmap and supporting reports; never edits source."""
    if not 0 < start_m < end_m:
        raise ValueError("regrade window must have increasing positive road distances")
    if target_cap_deg <= 0 or target_cap_deg >= HARD_CAP_DEG:
        raise ValueError(f"design cap must be between 0 and the {HARD_CAP_DEG:g}° hard cap")
    if not math.isfinite(feather_m) or feather_m <= 0:
        raise ValueError("feather width must be positive and finite")

    brp = _load_profile_dependencies()
    Image.MAX_IMAGE_PIXELS = None
    with Image.open(source_path) as image:
        source_u16 = np.asarray(image)
    if source_u16.dtype != np.uint16 or source_u16.ndim != 2:
        raise ValueError(f"{source_path} must be a 16-bit grayscale heightmap")
    source_z = (source_u16.astype(np.float32) - 32768.0) / 64.0
    terrain = brp.Terrain(source_path)
    road = brp.Road(brp.SPLINE_POINTS_CM)
    if end_m > road.length:
        raise ValueError(f"end distance {end_m} exceeds road length {road.length:.1f} m")

    distance_m = np.arange(start_m, end_m + PROFILE_STEP_M * 0.5, PROFILE_STEP_M)
    center_xy_cm = road.xy(distance_m)
    center_xy_m = center_xy_cm / 100.0
    before_profile = terrain.height(center_xy_cm[:, 0], center_xy_cm[:, 1]).astype(np.float64)
    cap_grade = math.tan(math.radians(target_cap_deg))
    target_profile = cap_profile_grade(distance_m, before_profile, cap_grade)
    if len(target_profile) != len(distance_m):
        raise RuntimeError("grade profile length changed unexpectedly")

    # Extend the rasterized guide beyond both fixed anchors so bilinear pixel
    # support exists on each side of the endpoint samples. The extended guide
    # returns to the original centerline elevation outside the shaped window.
    patch_start = max(0.0, start_m - 5.0)
    patch_end = min(road.length, end_m + 5.0)
    patch_distance_m = np.arange(patch_start, patch_end + PROFILE_STEP_M * 0.5, PROFILE_STEP_M)
    patch_xy_cm = road.xy(patch_distance_m)
    patch_xy_m = patch_xy_cm / 100.0
    patch_before = terrain.height(patch_xy_cm[:, 0], patch_xy_cm[:, 1]).astype(np.float64)
    patch_target = patch_before.copy()
    shaped_delta = ease_profile_delta(
        distance_m,
        start_m=start_m,
        end_m=end_m,
        delta_m=target_profile - before_profile,
        ease_m=END_EASE_M,
    )
    eased_profile = before_profile + shaped_delta
    in_window = (patch_distance_m >= start_m) & (patch_distance_m <= end_m)
    patch_target[in_window] = np.interp(patch_distance_m[in_window], distance_m, eased_profile)
    patch_delta = patch_target - patch_before

    # Restrict image work to the road corridor plus two pixels for bilinear sampling.
    pad = ROAD_HALF_WIDTH_M + feather_m + 2.0
    x0_m = brp.LAND_X0_CM / 100.0
    y0_m = brp.LAND_Y0_CM / 100.0
    col0 = max(0, int(math.floor((patch_xy_m[:, 0].min() - pad - x0_m) / (brp.PX_CM / 100.0))))
    col1 = min(source_u16.shape[1], int(math.ceil((patch_xy_m[:, 0].max() + pad - x0_m) / (brp.PX_CM / 100.0))) + 1)
    row0 = max(0, int(math.floor((patch_xy_m[:, 1].min() - pad - y0_m) / (brp.PX_CM / 100.0))))
    row1 = min(source_u16.shape[0], int(math.ceil((patch_xy_m[:, 1].max() + pad - y0_m) / (brp.PX_CM / 100.0))) + 1)
    if col1 <= col0 or row1 <= row0:
        raise ValueError("regrade corridor falls outside source heightmap")

    candidate_u16 = source_u16.copy()
    crop_z = source_z[row0:row1, col0:col1]
    crop_origin_m = (x0_m + col0, y0_m + row0)
    candidate_crop_z = apply_corridor_delta(
        crop_z,
        origin_xy_m=crop_origin_m,
        center_xy_m=patch_xy_m,
        center_s_m=patch_distance_m,
        center_delta_m=patch_delta,
        center_elevation_m=patch_before,
        road_half_width_m=ROAD_HALF_WIDTH_M,
        feather_m=feather_m,
        crossfall_grade=CROSS_FALL_GRADE,
    )
    terrain_slope_summary = _terrain_slope_summary(
        crop_z,
        candidate_crop_z,
        crop_origin_m,
        center_xy_m,
        (3.0, 10.0, ROAD_HALF_WIDTH_M + feather_m),
    )
    encoded = np.rint(candidate_crop_z * 64.0 + 32768.0)
    if encoded.min() < 0 or encoded.max() > 65535:
        raise ValueError("candidate terrain exceeds the 16-bit heightmap range")
    candidate_u16[row0:row1, col0:col1] = encoded.astype(np.uint16)
    candidate_z = (candidate_u16.astype(np.float32) - 32768.0) / 64.0

    px = (center_xy_cm[:, 0] - brp.LAND_X0_CM) / brp.PX_CM
    py = (center_xy_cm[:, 1] - brp.LAND_Y0_CM) / brp.PX_CM
    after_profile = _bilinear(candidate_z, px, py)
    grade_before = np.diff(before_profile) / np.diff(distance_m)
    grade_after = np.diff(after_profile) / np.diff(distance_m)
    hard_cap = math.tan(math.radians(HARD_CAP_DEG))
    endpoint_error = np.abs(np.asarray((after_profile[0] - before_profile[0],
                                        after_profile[-1] - before_profile[-1])))
    if float(endpoint_error.max()) > 0.03:
        raise RuntimeError(f"candidate moved a fixed endpoint by {endpoint_error.max():.3f} m")
    if float(np.max(np.abs(grade_after))) > hard_cap + 1e-5:
        peak_i = int(np.argmax(np.abs(grade_after)))
        after_angle = math.degrees(math.atan(float(abs(grade_after[peak_i]))))
        raise RuntimeError(
            f"quantized candidate exceeds the hard grade cap: "
            f"{after_angle:.3f}° at {distance_m[peak_i]:.0f}–{distance_m[peak_i + 1]:.0f} m; "
            f"target={target_profile[peak_i]:.3f}->{target_profile[peak_i + 1]:.3f} m, "
            f"sampled={after_profile[peak_i]:.3f}->{after_profile[peak_i + 1]:.3f} m"
        )

    guard_start = max(0.0, start_m - 10.0)
    guard_end = min(road.length, end_m + 10.0)
    guard_s = np.arange(guard_start, guard_end + 0.5, 1.0)
    guard_xy_cm = road.xy(guard_s)
    guard_px = (guard_xy_cm[:, 0] - brp.LAND_X0_CM) / brp.PX_CM
    guard_py = (guard_xy_cm[:, 1] - brp.LAND_Y0_CM) / brp.PX_CM
    guard_z = _bilinear(candidate_z, guard_px, guard_py)
    guard_grade = np.diff(guard_z) / np.diff(guard_s)
    max_guard_angle = math.degrees(math.atan(float(np.max(np.abs(guard_grade)))))
    if max_guard_angle > HARD_CAP_DEG + 1e-3:
        raise RuntimeError(f"candidate blend boundary exceeds the grade cap: {max_guard_angle:.3f}°")

    # Report existing/candidate cross slope at the full 6 m drive width.
    tangent = np.gradient(center_xy_m, axis=0)
    tangent /= np.maximum(np.linalg.norm(tangent, axis=1, keepdims=True), 1e-9)
    normal = np.column_stack((-tangent[:, 1], tangent[:, 0]))
    lateral_offset_m = ROAD_HALF_WIDTH_M
    left_xy_cm = (center_xy_m - normal * lateral_offset_m) * 100.0
    right_xy_cm = (center_xy_m + normal * lateral_offset_m) * 100.0
    left_px = (left_xy_cm[:, 0] - brp.LAND_X0_CM) / brp.PX_CM
    left_py = (left_xy_cm[:, 1] - brp.LAND_Y0_CM) / brp.PX_CM
    right_px = (right_xy_cm[:, 0] - brp.LAND_X0_CM) / brp.PX_CM
    right_py = (right_xy_cm[:, 1] - brp.LAND_Y0_CM) / brp.PX_CM
    cross_slope_before = np.abs(_bilinear(source_z, right_px, right_py) -
                                _bilinear(source_z, left_px, left_py)) / (2 * lateral_offset_m)
    cross_slope_after = np.abs(_bilinear(candidate_z, right_px, right_py) -
                               _bilinear(candidate_z, left_px, left_py)) / (2 * lateral_offset_m)
    cross_slope_after_deg = np.degrees(np.arctan(cross_slope_after))

    output_dir.mkdir(parents=True, exist_ok=True)
    candidate_path = output_dir / "candidate_u16.png"
    Image.fromarray(candidate_u16).save(candidate_path)
    csv_path = output_dir / "road_grade_profile.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(("road_m", "source_z_m", "candidate_z_m", "source_grade_pct", "candidate_grade_pct"))
        writer.writerow((float(distance_m[0]), float(before_profile[0]), float(after_profile[0]), "", ""))
        for i in range(1, len(distance_m)):
            writer.writerow((float(distance_m[i]), float(before_profile[i]), float(after_profile[i]),
                             float(grade_before[i - 1] * 100.0), float(grade_after[i - 1] * 100.0)))
    plot_path = output_dir / "road_grade_profile.png"
    _write_plot(plot_path, distance_m, before_profile, after_profile, target_cap_deg)

    changed = candidate_u16 != source_u16
    delta_u16 = candidate_u16.astype(np.int32) - source_u16.astype(np.int32)
    largest_change_row, largest_change_col = np.unravel_index(np.argmax(np.abs(delta_u16)), delta_u16.shape)
    largest_change_xy_m = np.array((x0_m + largest_change_col, y0_m + largest_change_row))
    nearest_change = int(cKDTree(center_xy_m).query(largest_change_xy_m)[1])
    max_cut = float(delta_u16.min() / 64.0)
    max_fill = float(delta_u16.max() / 64.0)
    max_angle_before = math.degrees(math.atan(float(np.max(np.abs(grade_before)))))
    max_angle_after = math.degrees(math.atan(float(np.max(np.abs(grade_after)))))
    source_rise = float(before_profile[-1] - before_profile[0])
    corridor_plot = output_dir / "road_regrade_corridor.png"
    _write_corridor_plot(
        corridor_plot,
        source_z,
        candidate_z,
        (col0, row0, col1, row1),
        (x0_m, y0_m),
        center_xy_m,
        start_m,
        end_m,
    )
    max_change_station = float(distance_m[nearest_change])
    cross_section_plot = output_dir / "road_regrade_cross_sections.png"
    cross_section_results = _write_cross_section_plot(
        cross_section_plot,
        source_z,
        candidate_z,
        center_xy_cm,
        distance_m,
        (brp.LAND_X0_CM, brp.LAND_Y0_CM),
        (max_change_station, 3861.0),
        ROAD_HALF_WIDTH_M,
        feather_m,
    )
    report = {
        "source_heightmap": str(source_path.relative_to(ROOT) if source_path.is_relative_to(ROOT) else source_path),
        "candidate_heightmap": str(candidate_path.relative_to(ROOT) if candidate_path.is_relative_to(ROOT) else candidate_path),
        "candidate_only": True,
        "authoritative_source_overwritten": False,
        "content_or_editor_touched": False,
        "road_xy_changed": False,
        "story_anchor_xy_changed": False,
        "road_window_m": [float(start_m), float(end_m)],
        "fixed_endpoint_elevation_m": [float(before_profile[0]), float(before_profile[-1])],
        "candidate_endpoint_elevation_m": [float(after_profile[0]), float(after_profile[-1])],
        "endpoint_height_error_m": [float(endpoint_error[0]), float(endpoint_error[1])],
        "fixed_endpoint_rise_m": source_rise,
        "mean_grade_pct": source_rise / (end_m - start_m) * 100.0,
        "target_cap_degrees": float(target_cap_deg),
        "hard_cap_degrees": HARD_CAP_DEG,
        "max_local_grade_before_degrees": max_angle_before,
        "max_local_grade_after_degrees": max_angle_after,
        "max_abs_local_grade_before_pct": float(np.max(np.abs(grade_before)) * 100.0),
        "max_abs_local_grade_after_pct": float(np.max(np.abs(grade_after)) * 100.0),
        "blend_guard_m": [guard_start, guard_end],
        "max_blend_guard_grade_degrees": max_guard_angle,
        "crossfall_grade": CROSS_FALL_GRADE,
        "max_drive_width_cross_slope_before_degrees": math.degrees(math.atan(float(cross_slope_before.max()))),
        "p95_drive_width_cross_slope_before_degrees": math.degrees(math.atan(float(np.percentile(cross_slope_before, 95)))),
        "max_drive_width_cross_slope_after_degrees": math.degrees(math.atan(float(cross_slope_after.max()))),
        "max_cross_slope_road_m": float(distance_m[int(np.argmax(cross_slope_after_deg))]),
        "p95_drive_width_cross_slope_after_degrees": math.degrees(math.atan(float(np.percentile(cross_slope_after, 95)))),
        "cross_sections": cross_section_results,
        "combined_terrain_slope_by_road_buffer": terrain_slope_summary,
        "corridor": {
            "drive_width_m": 2.0 * ROAD_HALF_WIDTH_M,
            "feather_outside_drive_width_m": feather_m,
            "total_half_width_m": ROAD_HALF_WIDTH_M + feather_m,
            "changed_pixels": int(changed.sum()),
            "max_height_delta_m": float(np.max(np.abs(delta_u16[changed])) / 64.0) if changed.any() else 0.0,
            "minimum_signed_height_delta_m": max_cut,
            "maximum_signed_height_delta_m": max_fill,
            "estimated_cut_volume_m3": float(-np.minimum(delta_u16[changed], 0).sum() / 64.0),
            "estimated_fill_volume_m3": float(np.maximum(delta_u16[changed], 0).sum() / 64.0),
            "largest_change_world_xy_m": largest_change_xy_m.tolist(),
            "largest_change_nearest_road_m": max_change_station,
            "roi_pixel_bounds": [int(col0), int(row0), int(col1), int(row1)],
        },
        "artifacts": {
            "profile_csv": str(csv_path.relative_to(ROOT) if csv_path.is_relative_to(ROOT) else csv_path),
            "grade_plot": str(plot_path.relative_to(ROOT) if plot_path.is_relative_to(ROOT) else plot_path),
            "corridor_plot": str(corridor_plot.relative_to(ROOT) if corridor_plot.is_relative_to(ROOT) else corridor_plot),
            "cross_section_plot": str(cross_section_plot.relative_to(ROOT) if cross_section_plot.is_relative_to(ROOT) else cross_section_plot),
        },
    }
    report_path = output_dir / "regrade_report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE_HEIGHTMAP)
    parser.add_argument("--out", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--start-m", type=float, default=START_M)
    parser.add_argument("--end-m", type=float, default=END_M)
    parser.add_argument("--cap-deg", type=float, default=TARGET_CAP_DEG)
    parser.add_argument("--feather-m", type=float, default=FEATHER_M)
    args = parser.parse_args()
    report = prepare_candidate(args.source, args.out, args.start_m, args.end_m, args.cap_deg, args.feather_m)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
