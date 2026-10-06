"""Offline tests for the set-dressing plan and tool (no editor).

    python -m pytest Tools/World/tests -q
"""
import json
import math
import os
import random
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
WORLD = os.path.dirname(HERE)
sys.path.insert(0, WORLD)
import place_setdress as ps  # noqa: E402

M = {}
exec(ps.MATH_SRC, M)
DOC = json.load(open(os.path.join(WORLD, 'setdress_sites.json'), encoding='utf8'))


def angle(a, b):
    d = sum(x * y for x, y in zip(a, b)) / math.sqrt(sum(x * x for x in a) * sum(y * y for y in b))
    return math.degrees(math.acos(max(-1.0, min(1.0, d))))


def box_bottom(hx, hy, z0=0.0):
    pts = [(sx * hx, sy * hy, z0) for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    return (0.0, 0.0, 25.0), pts + [(0.0, 0.0, z0)]


def test_align_angles_follow_the_normal():
    rng = random.Random(3)
    for _ in range(300):
        tilt, az, yaw = rng.uniform(0, 18), rng.uniform(0, 360), rng.uniform(-180, 180)
        n = (math.sin(math.radians(tilt)) * math.cos(math.radians(az)),
             math.sin(math.radians(tilt)) * math.sin(math.radians(az)), math.cos(math.radians(tilt)))
        p, r = M['align_angles'](n, yaw)
        assert angle(M['axes'](yaw, p, r)[2], n) < 1.5


def test_plane_normal_and_clamp():
    pts = [(x, y, 0.2 * x) for x in (-50, 50) for y in (-50, 50)]
    n = M['plane_normal'](pts)
    assert abs(math.degrees(math.atan2(-n[0], n[2])) - math.degrees(math.atan(0.2))) < 0.1
    c = M['clamp_normal'](n, 5.0)
    assert abs(math.degrees(math.acos(c[2])) - 5.0) < 0.01


def slope(x, y):
    return (0.2 * x, (-0.19611613513818404, 0.0, 0.9805806756909202))


def test_trace_settle_aligns_to_a_slope():
    c, pts = box_bottom(50, 50)
    cfg = dict(mode='trace', sink=0.0, max_tilt=15.0, rand_tilt=0.0, z_rule='mean')
    lx, ly, lz, yw, pt, rl, info = M['settle_pose'](0.0, 0.0, c, pts, 0.0, 0.0, 0.0, cfg, slope, random.Random(1))
    assert abs(pt - math.degrees(math.atan(0.2))) < 0.5 and abs(rl) < 0.5
    assert info['gap_max'] < 2.0 and info['gap_min'] > -2.0


def test_min_rule_buries_the_uphill_side_of_a_building():
    c, pts = box_bottom(400, 300)
    cfg = dict(mode='trace', sink=12.0, max_tilt=2.0, rand_tilt=0.0, z_rule='min')
    lx, ly, lz, yw, pt, rl, info = M['settle_pose'](0.0, 0.0, c, pts, 0.0, 0.0, 0.0, cfg, slope, random.Random(1))
    assert abs(pt) <= 2.01
    assert info['gap_max'] <= -12.0 + 0.5      # no corner floats
    assert info['gap_min'] < -50.0             # the uphill side is buried


def test_physics_rests_on_a_block_without_penetrating():
    def ground(x, y):
        return (30.0, (0, 0, 1)) if 0 <= x <= 60 else (0.0, (0, 0, 1))
    c, pts = box_bottom(50, 30)
    cfg = dict(mode='physics', sink=2.0, max_tilt=15.0, rand_tilt=6.0, z_rule='max', candidates=7)
    res = M['settle_pose'](0.0, 0.0, c, pts, 0.0, 0.0, 0.0, cfg, ground, random.Random(5))
    lx, ly, lz, yw, pt, rl, info = res
    assert info['gap_min'] >= -2.0 - 0.5      # nothing sinks through the block beyond the sink


def test_every_step_script_is_valid_for_every_site():
    args = types.SimpleNamespace(approve='', with_optional=False, no_ism=False)
    for site in DOC['sites']:
        items, _ = ps.select(site, args)
        solo = [ps.slim(p) for p in items if not p['ism']]
        ps.validate(ps.build_script(ps.PLACE_BODY, SITE=site['id'], ITEMS=solo[:15]))
        ps.validate(ps.build_script(ps.SETTLE_BODY, SITE=site['id'], ITEMS=solo[:8]))
        ps.validate(ps.build_script(ps.CHECK_BODY, SITE=site['id'], ITEMS=solo, ROAD=[[0, 0], [1, 1]],
                                    CLEAR_CM=500.0, TOL_CM=8.0))
        isms = [ps.slim(p) for p in items if p['ism']]
        if isms:
            ps.validate(ps.build_script(ps.ISM_BODY, SITE=site['id'], GROUP_ID='g', ASSET=isms[0]['asset'],
                                        FALLBACK='', FOLDER='Set/x', ITEMS=isms[:60]))
        for v in site['views']:
            ps.validate(ps.build_script(ps.CAPTURE_SHOOT_BODY, CAM=v['cam_cm'], LOOK=v['look_cm'], LABEL='x',
                                        SIZE=[16, 9], FOV=60.0))
    for body in (ps.PROBE_BODY, ps.LOAD_BODY, ps.UNLOAD_BODY, ps.SAVE_BODY, ps.CLEAR_BODY, ps.STATUS_BODY,
                 ps.SURVEY_BODY, ps.CAPTURE_EXPORT_BODY):
        ps.validate(ps.build_script(body, BATCH01_KEYS=[], BOX=[0, 0, 1, 1], ALREADY=[], LIMIT=20, MAX_LAND=20,
                                    CLASS_FIELD='native_class', WANT=[], SITE='S', OFFSET=0, DELETIONS=False,
                                    ONLY=[], CENTRE=[0, 0], RADIUS=1.0, LABEL='x', NAME='n', OUT_REL='a/b'))


def test_validate_refuses_banned_text():
    for bad in ('try:\n    pass\nexcept Exception:\n    pass', 'x = getattr(unreal, "a")', 'open("f")',
                's.replace("a", "b")', 'unreal.Guid()'):
        try_ok = False
        try:
            ps.validate(bad)
        except SystemExit:
            try_ok = True
        assert try_ok, bad


def test_plan_rules():
    banned_paths = ('SM_PalmTree', 'SM_Mashrabiya', 'SM_Carpet_A', 'SM_SandMound', 'Military_Trenches', 'sign01',
                    'Megaplant_Library')
    n = 0
    for site in DOC['sites']:
        for p in site['placements']:
            n += 1
            assert p['road_clear_m'] >= ps.CLEAR_M - 0.01, (p['id'], p['road_clear_m'])
            assert not any(b in p['asset'] for b in banned_paths), p['asset']
            assert p['draw_distance_cm'] > 0
            assert p.get('verdict') != 'reject'
            assert 'try' not in json.dumps(ps.slim(p))
    assert 1000 <= n <= 2500
    assert not DOC['rejected']
    lone = [s for s in DOC['sites'] if s['id'].startswith('L')]
    assert 10 <= len(lone) <= 20


def test_offroad_layer():
    pois = [s for s in DOC['sites'] if s.get('layer') == 'offroad']
    assert 12 <= len(pois) <= 18
    reach = [s for s in pois if s['poi']['reachable']]
    assert len(reach) == 6
    for s in pois:
        p = s['poi']
        assert 200 <= p['distance_m'] <= 2000, s['id']
        assert p['visible_road_m'] > 0, s['id']          # every POI is seen from the road somewhere
        if p['reachable']:
            sp = p['spur']
            assert sp['max_grade_pct'] < 100, s['id']    # under the 44.8 deg walkable floor
            assert any(pl['group'] == 'spur_markers' for pl in s['placements'])
        assert all(pl['draw_distance_cm'] > 0 for pl in s['placements'])
