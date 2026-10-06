"""Offline tests for the tether paths and zones (task TETHER; no editor).

    python -m pytest Tools/World/tests/test_tether_paths.py -q

The reference tether in make_tether_paths (tether_query, holds_road_progress) follows the same rules
as USaskartaTetherSubsystem: the distance is the minimum over the road and every tether path, 0 inside
an exploration zone, and road progress holds while the carrier is off the road on a path or in a zone.
"""
import math
import os
import sys

import numpy as np
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
WORLD = os.path.dirname(HERE)
sys.path.insert(0, WORLD)
import make_tether_paths as mt  # noqa: E402

REACHABLE = {'O01', 'O03', 'O06', 'O09', 'O10', 'O14'}


@pytest.fixture(scope='module')
def ground():
    return mt.Ground()


@pytest.fixture(scope='module')
def doc(ground):
    return mt.build(ground)


@pytest.fixture(scope='module')
def lines(doc):
    road = mt.road_polyline_m()
    paths = {p['id']: np.array(p['points_cm'], float)[:, :2] / 100.0 for p in doc['paths']}
    zones = {z['id']: (np.array(z['centre_cm'][:2]) / 100.0, z['radius_cm'] / 100.0) for z in doc['zones']}
    return road, paths, zones


def test_the_six_reachable_pois_have_a_path_and_a_zone(doc):
    assert {p['id'] for p in doc['paths']} == REACHABLE
    assert {z['id'] for z in doc['zones']} == REACHABLE


def test_the_committed_json_is_current(doc):
    import json
    committed = json.load(open(mt.OUT_JSON, encoding='utf8'))
    assert committed['paths'] == json.loads(json.dumps(doc['paths']))
    assert committed['zones'] == json.loads(json.dumps(doc['zones']))


def test_paths_start_on_the_road_and_end_inside_their_zone(lines):
    road, paths, zones = lines
    for pid, poly in paths.items():
        assert mt.dist_to_polyline(poly[0], road)[0] < 1.0, pid
        c, r = zones[pid]
        assert math.hypot(*(poly[-1] - c)) <= r - 5.0, pid


def test_every_path_is_at_most_20_percent_and_o01_switches_back(doc, ground):
    for p in doc['paths']:
        corners = np.array(p['corners_cm'], float) / 100.0
        assert mt.max_grade_pct(corners, ground) <= mt.MAX_GRADE_PCT + 1e-6, p['id']
        # the spline points (10 m apart, ground-snapped) carry the same line
        dense = np.array(p['points_cm'], float)[:, :2] / 100.0
        assert mt.max_grade_pct(dense, ground) <= mt.MAX_GRADE_PCT + 0.5, p['id']
    o01 = next(p for p in doc['paths'] if p['id'] == 'O01')
    assert o01['spur_grade_pct'] >= 45 and o01['rerouted']
    assert o01['length_m'] > 595            # longer than the straight 49 % spur: it zig-zags
    assert len(o01['markers_cm']) >= 8      # new way-marker spots for the rerouted line


def test_paths_are_ground_snapped_and_evenly_spaced(doc, ground):
    for p in doc['paths']:
        pts = np.array(p['points_cm'], float) / 100.0
        z = ground.z(pts[:, 0], pts[:, 1])
        assert np.max(np.abs(pts[:, 2] - z)) < 0.05, p['id']
        step = np.linalg.norm(np.diff(pts[:, :2], axis=0), axis=1)
        assert step.max() <= mt.SPLINE_STEP_M + 1e-6 and step.min() > 0.1, p['id']


def test_walking_a_path_never_warns(lines):
    """Distance to the nearest spline: every metre of every path is inside the 10 m band."""
    road, paths, zones = lines
    all_paths = list(paths.values())
    zl = list(zones.values())
    for pid, poly in paths.items():
        for p in mt.resample(poly, 1.0):
            d, _, _, _ = mt.tether_query(p, road, all_paths, zl)
            assert d < 0.5, (pid, p.tolist(), d)
        # and 8 m to either side of the line is still under the warning
        for a, b in zip(poly[:-1:3], poly[1::3]):
            n = np.array([-(b - a)[1], (b - a)[0]]) / (np.linalg.norm(b - a) or 1.0)
            for side in (-8.0, 8.0):
                d, _, _, _ = mt.tether_query((a + b) / 2 + n * side, road, all_paths, zl)
                assert d < mt.WARN_M, (pid, d)


def test_distance_is_the_minimum_over_road_and_paths(lines):
    road, paths, zones = lines
    poly = paths['O06']
    mid = poly[len(poly) // 2]
    a, b = poly[len(poly) // 2 - 1], poly[len(poly) // 2 + 1]
    n = np.array([-(b - a)[1], (b - a)[0]]) / np.linalg.norm(b - a)
    p = mid + n * 15.0                     # 15 m off the spur, far from the road
    d, rd, on_path, in_zone = mt.tether_query(p, road, list(paths.values()), [])
    assert 13.0 < d < 16.0 and rd > 100.0 and on_path and not in_zone
    # the road alone would breach here; the spur keeps it in the warning band
    assert rd > mt.BREACH_M and mt.WARN_M < d < mt.BREACH_M


def test_zone_override(lines):
    """Inside an exploration zone the tether reads 0, however far from any line."""
    road, paths, zones = lines
    rng = np.random.default_rng(5)
    for pid, (c, r) in zones.items():
        for _ in range(40):
            ang, rad = rng.uniform(0, 2 * math.pi), r * math.sqrt(rng.uniform(0, 0.98))
            p = c + rad * np.array([math.cos(ang), math.sin(ang)])
            d, _, _, in_zone = mt.tether_query(p, road, list(paths.values()), list(zones.values()))
            assert in_zone and d == 0.0, pid
        # just outside the zone, away from the path, it breaches again
        poly = paths[pid]
        away = c + (c - poly[-2]) / np.linalg.norm(c - poly[-2]) * (r + 30.0)
        d, _, _, in_zone = mt.tether_query(away, road, list(paths.values()), list(zones.values()))
        assert not in_zone and d > mt.BREACH_M, (pid, d)


def test_respawn_selection_picks_the_nearest_line(lines):
    """The respawn goes to the line that won the minimum: the spur when breaching off a spur."""
    road, paths, zones = lines
    poly = paths['O09']
    k = len(poly) // 2
    n = np.array([-(poly[k + 1] - poly[k])[1], (poly[k + 1] - poly[k])[0]])
    n = n / np.linalg.norm(n)
    breach = poly[k] + n * 21.0
    d_road = mt.dist_to_polyline(breach, road)[0]
    best = min(((mt.dist_to_polyline(breach, pl)[0], pid) for pid, pl in paths.items()))
    assert best[1] == 'O09' and best[0] < d_road
    # near the junction, the road is nearer: the respawn is on the road
    j = poly[0] + (poly[1] - poly[0]) / np.linalg.norm(poly[1] - poly[0]) * 2.0
    side = np.array([-(poly[1] - poly[0])[1], (poly[1] - poly[0])[0]])
    side = side / np.linalg.norm(side)
    # a point 21 m from the road, straight off it on the far side from the spur
    q, _, _, rp = mt.dist_to_polyline(j, road)
    off = (j - rp) / (np.linalg.norm(j - rp) or 1.0)
    p = rp - off * 21.0
    assert mt.dist_to_polyline(p, road)[0] <= mt.dist_to_polyline(p, poly)[0]


def _walk(points, road, paths, zones, high_water):
    """The event runner's road progress (road metres, forward = up): the high-water mark only moves
    when the pawn is not on a detour (USaskartaEventRunner::PollRoad + the tether hook)."""
    for p in points:
        _, rd, on_path, in_zone = mt.tether_query(p, road, paths, zones)
        if mt.holds_road_progress(rd, on_path, in_zone):
            continue
        high_water = max(high_water, mt.road_m_at(p, road))
    return high_water


def test_road_m_is_unaffected_by_path_travel(lines, doc):
    """Walking out along each spur to its POI, round the zone and back never moves the story on:
    road_m after the detour equals road_m at the junction (a beat ahead would otherwise fire)."""
    road, paths, zones = lines
    pl, zl = list(paths.values()), list(zones.values())
    for p in doc['paths']:
        poly = paths[p['id']]
        at_junction = mt.road_m_at(poly[0], road)
        c, r = zones[p['id']]
        loop = [c + 0.8 * r * np.array([math.cos(a), math.sin(a)]) for a in np.linspace(0, 2 * math.pi, 24)]
        trip = list(mt.resample(poly, 2.0)) + loop + list(mt.resample(poly[::-1], 2.0))
        hw = _walk(trip, road, pl, zl, at_junction)
        assert hw <= at_junction + mt.WARN_M, (p['id'], at_junction, hw)
        # without the hold, the projection would have run far ahead for most spurs
        free = max(mt.road_m_at(q, road) for q in trip)
        if free > at_junction + 50.0:
            assert hw < free - 40.0


def test_editor_scripts_are_hayba_safe(doc):
    scripts = mt.scripts_for(doc)
    assert len(scripts) == 2 * len(REACHABLE) + 1
    for name, s in scripts:
        for bad in mt.BANNED:
            assert bad not in s, (name, bad)
        compile(s, name, 'exec')
        if name.endswith('_path'):
            assert 'Saskarta.TetherPath' in s and 'SaskartaTetherPath' in s
        if name.endswith('_zone'):
            assert 'Saskarta.ExploreZone' in s and 'radius_cm' in s
