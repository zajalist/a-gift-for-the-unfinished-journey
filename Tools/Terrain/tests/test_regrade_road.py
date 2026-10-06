import numpy as np
import pytest
from scipy.ndimage import map_coordinates

from Tools.Terrain.regrade_road import (
    InfeasibleRegradeError,
    apply_corridor_delta,
    cap_profile_grade,
    ease_profile_delta,
    _terrain_slope_summary,
)


def test_profile_cap_keeps_end_heights_and_limits_every_local_grade():
    # A narrow 2 m rise spike must be redistributed without moving either endpoint.
    distance = np.arange(7, dtype=float)
    source_z = np.array([0.0, 0.1, 1.8, 2.4, 2.8, 3.0, 3.4])

    target_z = cap_profile_grade(distance, source_z, max_grade=0.70)

    assert target_z[0] == source_z[0]
    assert target_z[-1] == source_z[-1]
    assert np.max(np.abs(np.diff(target_z) / np.diff(distance))) <= 0.70 + 1e-9
    assert target_z[2] < source_z[2]


def test_profile_cap_rejects_endpoint_rise_that_cannot_fit_the_grade_limit():
    with pytest.raises(InfeasibleRegradeError, match="endpoint rise"):
        cap_profile_grade(
            np.array([0.0, 1.0, 2.0]),
            np.array([0.0, 0.5, 2.0]),
            max_grade=0.70,
        )


def test_endpoint_ease_fixes_delta_at_anchors_and_reaches_full_shape_inside():
    distance = np.arange(0.0, 101.0)
    delta = np.full(len(distance), 10.0)

    eased = ease_profile_delta(distance, start_m=0.0, end_m=100.0, delta_m=delta, ease_m=20.0)

    assert eased[0] == 0.0
    assert eased[20] == 10.0
    assert eased[-1] == 0.0
    assert eased[-21] == 10.0
    assert np.all(np.diff(eased[:21]) >= 0.0)
    assert np.all(np.diff(eased[-21:]) <= 0.0)


def test_corridor_delta_covers_drive_width_and_fades_without_a_ditch():
    height = np.zeros((55, 55), dtype=np.float32)
    center_xy_m = np.column_stack((np.arange(10.0, 45.0), np.full(35, 27.0)))
    center_s_m = np.arange(35, dtype=float)
    center_delta_m = np.full(35, 2.0)

    candidate = apply_corridor_delta(
        height,
        origin_xy_m=(0.0, 0.0),
        center_xy_m=center_xy_m,
        center_s_m=center_s_m,
        center_delta_m=center_delta_m,
        center_elevation_m=np.zeros(35),
        road_half_width_m=3.0,
        feather_m=20.0,
    )

    assert candidate[27, 27] == pytest.approx(2.0)
    assert candidate[30, 27] - candidate[24, 27] == pytest.approx(0.12, abs=0.02)
    lateral = candidate[:, 27]
    assert lateral[3] == pytest.approx(0.0)
    assert lateral[23] >= 1.88
    assert np.all(np.diff(lateral[3:24]) >= -1e-8)
    assert np.all(np.diff(lateral[31:51]) <= 1e-8)
    assert lateral[51] == pytest.approx(0.0)


def test_diagonal_corridor_interpolates_profile_between_road_samples():
    height = np.zeros((80, 80), dtype=np.float32)
    station = np.arange(40, dtype=float)
    center_xy_m = np.column_stack((20.0 + 0.8 * station, 15.0 + 0.6 * station))
    expected = 0.40 * station

    candidate = apply_corridor_delta(
        height,
        origin_xy_m=(0.0, 0.0),
        center_xy_m=center_xy_m,
        center_s_m=station,
        center_delta_m=expected,
        center_elevation_m=np.zeros(40),
        road_half_width_m=3.0,
        feather_m=20.0,
    )
    sampled = map_coordinates(
        candidate,
        (center_xy_m[:, 1], center_xy_m[:, 0]),
        order=1,
        mode="nearest",
    )

    assert np.max(np.abs(np.diff(sampled))) <= 0.41


def test_drive_width_is_crossfall_controlled_over_steep_source_terrain():
    y, x = np.indices((60, 60), dtype=np.float32)
    height = y * 0.5
    center_xy_m = np.column_stack((np.arange(10.0, 50.0), np.full(40, 30.0)))
    center_s_m = np.arange(40, dtype=float)
    center_z_m = np.full(40, 15.0)

    candidate = apply_corridor_delta(
        height,
        origin_xy_m=(0.0, 0.0),
        center_xy_m=center_xy_m,
        center_s_m=center_s_m,
        center_delta_m=np.zeros(40),
        center_elevation_m=center_z_m,
        road_half_width_m=3.0,
        feather_m=20.0,
        crossfall_grade=0.02,
    )

    cross_section = candidate[27:34, 30]
    assert np.max(np.abs(np.diff(cross_section))) <= 0.021
    assert cross_section[-1] - cross_section[0] == pytest.approx(0.12, abs=0.02)


def test_terrain_slope_summary_compares_source_and_candidate_inside_road_buffer():
    y, x = np.indices((25, 25), dtype=np.float32)
    source = x * 0.1
    candidate = x * 0.2
    road_xy = np.column_stack((np.arange(5.0, 20.0), np.full(15, 12.0)))

    summary = _terrain_slope_summary(source, candidate, (0.0, 0.0), road_xy, (3.0,))

    near = summary["within_3m"]
    assert near["pixels"] > 0
    assert near["source_p95_degrees"] == pytest.approx(np.degrees(np.arctan(0.1)), abs=0.1)
    assert near["candidate_max_degrees"] == pytest.approx(np.degrees(np.arctan(0.2)), abs=0.1)
