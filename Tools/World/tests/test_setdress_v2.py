"""Offline tests for set dressing V2 (docs/world/SETDRESS_V2.md): composition, ground, contact judge, tooling.

    python -m pytest Tools/World/tests -q
"""
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WORLD = os.path.dirname(HERE)
ROOT = os.path.dirname(os.path.dirname(WORLD))
sys.path.insert(0, WORLD)
import build_setdress_materials as bm  # noqa: E402
import place_setdress as ps  # noqa: E402
import setdress_contact as sc  # noqa: E402
import setdress_v2 as v2  # noqa: E402

DOC = json.load(open(os.path.join(WORLD, 'setdress_v2_sites.json'), encoding='utf8'))
S07 = [s for s in DOC['sites'] if s['id'] == 'S07_WaitingWater'][0]
L = S07['v2']


def seg_dist(p, a, b):
    du, dv = b[0] - a[0], b[1] - a[1]
    L2 = du * du + dv * dv
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * du + (p[1] - a[1]) * dv) / L2))
    return math.hypot(a[0] + t * du - p[0], a[1] + t * dv - p[1])


def poly_dist(p, pts):
    return min(seg_dist(p, a, b) for a, b in zip(pts[:-1], pts[1:]))


# ---------------------------------------------------------------- the generated file is current

def test_json_is_regenerated():
    W = v2.B.World()
    out, _ = v2.build(W)
    assert len(out[0]['placements']) == len(S07['placements']), 'run: python Tools/World/setdress_v2.py'


def test_revised_l10_is_the_effective_placement_input():
    group_path = os.path.join(WORLD, 'setdress_v2_groups', 'road_archetypes.json')
    group = json.load(open(group_path, encoding='utf8'))
    revised = next(site for site in group['sites'] if site['id'] == 'L10_FootFarm')
    effective = next(site for site in ps.load_doc(True)['sites'] if site['id'] == 'L10_FootFarm')
    assert effective == revised, 'patch the L10 aggregate record before editor placement'


# ---------------------------------------------------------------- composition

def test_rooms_share_party_walls():
    """Inside a block, no wall piece is emitted twice (a shared wall is ONE line between two rooms)."""
    seen = {}
    for u0, v0, u1, v1, st, blk in L['walls']:
        k = (blk,) + tuple(sorted([(round(u0, 1), round(v0, 1)), (round(u1, 1), round(v1, 1))]))
        seen[k] = seen.get(k, 0) + 1
    assert max(seen.values()) == 1
    # and rows really have party walls: more rooms than end walls
    assert len(L['rooms']) >= 10 and len(L['rows']) >= 3


def rooms_overlap(layout):
    """Pairs of rooms of different blocks whose cells overlap by more than 0.3 m (a court and what stands in it,
    like a keep in a fort court, are one composition and exempt)."""
    import build_setdress_sites as B
    rooms = [r for r in layout['rooms'] if not r.get('court')]
    bad = []
    for i in range(len(rooms)):
        for j in range(i + 1, len(rooms)):
            if rooms[i]['block'] == rooms[j]['block']:
                continue
            if any(B.sat_overlap(a, b) > 0.3 for a in rooms[i]['cells'] for b in rooms[j]['cells']):
                bad.append((rooms[i]['block'], rooms[j]['block']))
    return bad


def test_rows_do_not_collide():
    """Rows of the core are parallel terraces: no room of one block overlaps a room of another."""
    assert rooms_overlap(L) == []


def test_not_a_ring_or_a_grid():
    """V1's failure: pieces at an even radius around the centre. Radii of the solids must spread widely, and
    the core must be denser than the edge (dense core thinning out)."""
    cu, cv = L['core']
    pts = [((w[0] + w[2]) / 2, (w[1] + w[3]) / 2) for w in L['walls'] if w[4] != 'gap']
    r = [math.hypot(u - cu, v - cv) for u, v in pts]
    mean = sum(r) / len(r)
    sd = math.sqrt(sum((x - mean) ** 2 for x in r) / len(r))
    assert sd / mean > 0.45
    core = sum(1 for x in r if x < 22) / (math.pi * 22 ** 2)
    edge = sum(1 for x in r if 22 <= x < 60) / (math.pi * (60 ** 2 - 22 ** 2))
    assert core > 4 * edge


def test_every_door_reaches_the_road():
    """Doors connect to lanes, lanes connect to each other, and one lane reaches the road verge."""
    lanes = [ln['pts'] for ln in L['lanes']]
    F = v2.Frame(v2.B.World(), S07['road_m'])
    start = [i for i, p in enumerate(lanes) if min(F.road_dist(u, v) for u, v in p) < 8.0]
    assert start, 'no lane reaches the road'
    adj = {i: set() for i in range(len(lanes))}
    for i, a in enumerate(lanes):
        for j, b in enumerate(lanes):
            if i != j and (min(poly_dist(p, b) for p in (a[0], a[-1])) < 1.5 or min(poly_dist(p, a) for p in (b[0], b[-1])) < 1.5):
                adj[i].add(j)
    seen, todo = set(start), list(start)
    while todo:
        k = todo.pop()
        for j in adj[k] - seen:
            seen.add(j)
            todo.append(j)
    assert seen == set(range(len(lanes))), 'lanes not connected: %s' % (set(range(len(lanes))) - seen)
    for d in L['doors']:
        assert min(poly_dist(d[:2], p) for p in lanes) < 0.6


def test_collapse_runs_downhill():
    F = v2.Frame(v2.B.World(), S07['road_m'])
    down = 0
    for u, v, fu, fv, amount in L['fans']:
        du, dv = F.downhill(u, v)
        down += (fu * du + fv * dv) > 0.2
    assert down / len(L['fans']) > 0.9


def test_creep_and_rubble_keep_off_the_lanes():
    lanes = L['lanes']
    for p in S07['placements']:
        if p['cat'] != 'shrub':
            continue
    items = [it for it in v2.BUILT[0].items] if v2.BUILT else []
    for it in items:
        if v2.CAT[it['key']]['cat'] == 'shrub':
            for ln in lanes:
                assert poly_dist((it['u'], it['v']), ln['pts']) > ln['width'] / 2 + 0.3


def test_channel_runs_downhill_and_the_road_core_is_clear():
    F = v2.Frame(v2.B.World(), S07['road_m'])
    for line in L['channel']:
        z = [F.g(u, v) for u, v in line]
        assert all(b <= a + 0.25 for a, b in zip(z[:-1], z[1:]))
    for p in S07['placements']:
        assert p['road_clear_m'] >= 5.0, p['id']
        assert 'nudged' not in p.get('note', ''), (p['id'], p['note'])


def test_architecture_is_plumb_and_sunk():
    rigid = [p for p in S07['placements'] if p.get('contact') == 'rigid']
    assert rigid
    for p in rigid:
        assert p['settle']['max_tilt_deg'] == 0 and p['settle']['z_rule'] == 'min' and p['settle']['sink_cm'] >= 8


def test_ground_patches_cover_lanes_and_use_known_surfaces():
    g = S07['ground']
    assert {x['surface'] for x in g} <= set(bm.SURFACES)
    assert 20 <= len(g) <= 300      # meandering lanes are drawn as short capsules; V2.1 marks more ground
    paths = [x for x in g if x['surface'] == 'path']
    assert len(paths) >= len(L['lanes'])
    for x in g:
        assert x['depth_m'] >= 3.0 and x['length_m'] > 0 and x['width_m'] > 0


def placed_actors(site):
    """Actors the editor places by default: solo actors plus one per ISM group; optional (Tripo) slots out."""
    P = [p for p in site['placements'] if not p.get('optional')]
    return sum(1 for p in P if not p['ism']) + len({(p['group'], p['asset']) for p in P if p['ism']})


def test_budget():
    """V1 cap: 250 actors a site (an ISM group is one). V2.1 adds dense rubble and creep as ISM instances
    (small Nanite stones and bricks culled at 40 m, dry tufts): at most 2600 of them, and 300 decals."""
    c = S07['counts']
    assert placed_actors(S07) <= 250
    assert c['ism_instances'] <= 2600
    assert c['decals'] <= 300
    for p in S07['placements']:
        assert p['draw_distance_cm'] > 0


# ---------------------------------------------------------------- the contact judge

def rep(id_, loc, ext, rot=(0, 0, 0), gaps=None, hits=None):
    return dict(id=id_, loc=list(loc), rot=list(rot), scale=1.0, origin=[0, 0, 0], extent=list(ext),
                gaps=gaps or [0.0] * 9, hits=hits or ['landscape'] * 4)


def test_rigid_floats_if_any_sample_floats():
    it = dict(key='AB_300x400_Mid', cat='wall', contact='rigid')
    assert sc.contact_violations(rep('a', (0, 0, 0), (12, 150, 200), gaps=[-20, -3, 0, 2, -8, -1, 4, 0, 0]), it) == []
    v = sc.contact_violations(rep('a', (0, 0, 0), (12, 150, 200), gaps=[-20, -3, 0, 2, -8, -1, 4, 0, 9]), it)
    assert [x[0] for x in v] == ['FLOAT']


def test_loose_prop_floats_only_when_nothing_touches():
    it = dict(key='AB_Clay_Pot_A', cat='prop', contact='rest')
    assert sc.contact_violations(rep('p', (0, 0, 0), (20, 20, 30), gaps=[30, 30, 30, 30, 2, 30, 30, 30, 30]), it) == []
    assert sc.contact_violations(rep('p', (0, 0, 0), (20, 20, 30), gaps=[30] * 9), it)[0][0] == 'FLOAT'


def test_unit_on_a_wall_top_is_caught():
    it = dict(key='AB_Tent_Cloth_B_frame', cat='cloth', contact='rigid', unit='stall0')
    v = sc.contact_violations(rep('t', (0, 0, 0), (80, 60, 100), hits=['landscape', 'SD_S07_v2_010', 'landscape', 'landscape']), it)
    assert [x[0] for x in v] == ['ON_ACTOR']


def test_obb_depth():
    A = sc.obb(rep('a', (0, 0, 0), (100, 10, 100)))
    B = sc.obb(rep('b', (0, 15, 0), (100, 10, 100)))
    assert abs(sc.obb_depth(A, B) - 5.0) < 1e-6
    C = sc.obb(rep('c', (0, 25, 0), (100, 10, 100)))
    assert sc.obb_depth(A, C) == 0.0
    D = sc.obb(rep('d', (0, 0, 0), (100, 10, 100), rot=(90, 0, 0)))
    assert sc.obb_depth(A, D) > 10


def test_pairs_same_block_exempt_other_blocks_clash_and_units():
    items = {'a': dict(key='AB_300x400_Mid', cat='wall', contact='rigid', block='A_1'),
             'b': dict(key='AB_300x400_Mid', cat='wall', contact='rigid', block='A_1'),
             'c': dict(key='AB_300x400_Mid', cat='wall', contact='rigid', block='B_2'),
             't': dict(key='AB_Tent_Cloth_B_frame', cat='cloth', contact='rigid', unit='stall0', block=None),
             'p': dict(key='AB_Clay_Pot_A', cat='prop', contact='rest')}
    reps = {'a': rep('a', (0, 0, 0), (150, 12, 200)), 'b': rep('b', (140, 0, 0), (150, 12, 200), rot=(90, 0, 0)),
            'c': rep('c', (0, 10, 0), (150, 12, 200)), 't': rep('t', (-100, 0, 50), (80, 60, 100)),
            'p': rep('p', (500, 500, 0), (20, 20, 30))}
    v = sc.pair_violations(reps, items)
    codes = sorted(x[0] for x in v)
    assert 'CLASH' in codes and 'UNIT_CLASH' in codes
    assert not any('a x b' in x[1] for x in v)
    reps['p'] = rep('p', (30, 0, 50), (20, 20, 30))
    assert any(x[0] == 'INSIDE' for x in sc.pair_violations(reps, items))


def test_judge_applies_waivers():
    items = {'a': dict(key='AB_300x400_Mid', cat='wall', contact='rigid')}
    reps = {'a': rep('a', (0, 0, 0), (150, 12, 200), gaps=[9] * 9)}
    v, w = sc.judge(reps, items)
    assert len(v) == 1 and not w
    v, w = sc.judge(reps, items, [dict(id='a', code='FLOAT', why='test')])
    assert not v and len(w) == 1


def test_grid_local_has_corners_first():
    pts = sc.grid_local((0, 0, 10), (100, 50, 10), 2.0)
    assert len(pts) == 9
    assert all(abs(abs(p[0]) - 184) < 1e-6 and abs(abs(p[1]) - 92) < 1e-6 for p in pts[:4])
    assert all(p[2] == 0.0 for p in pts)


# ---------------------------------------------------------------- tooling

def test_pie_detection(tmp_path):
    log = tmp_path / 'x.log'
    log.write_text('a\nPlay in editor total start\nb\n', encoding='utf8')
    assert ps.pie_running(str(log))
    log.write_text('Creating play world package\nShutting down PIE\n', encoding='utf8')
    assert not ps.pie_running(str(log))
    log.write_text('Shutting down PIE\nCreating play world package\n', encoding='utf8')
    assert ps.pie_running(str(log))


def test_material_scripts_validate_and_pins_match_the_hlsl():
    for name, s in bm.scripts():
        compile(s, name, 'exec')
    for fname, body in (('PropGroundBlend.hlsl', bm.BLENDFN), ('SetDressGround.hlsl', bm.DECAL)):
        code = bm.hlsl(fname)
        pins = re.findall(r"'([A-Za-z0-9]+)'", body.split('pins = ')[-1].split(']')[0]) if 'pins = ' in body else \
            re.findall(r"'([A-Za-z0-9]+)'", body.split("for p in [")[1].split(']')[0])
        for p in pins:
            assert re.search(r'\b%s\b' % p, code), (fname, p)


def test_organic_not_uniform():
    """Controller review: varied room sizes, rooms turned 4-15 deg off the row, tall ruins, meandering lanes."""
    sizes = {(round(r['w']), round(r['d'])) for r in L['rooms']}
    assert len(sizes) >= 4
    angs = sorted({round(r['ang'], 1) for r in L['rooms'] if r['block'][0] in 'ABC'})
    assert max(angs) - min(angs) >= 10
    keys = {p['key'] for p in S07['placements']}
    assert 'B01_house02' in keys and v2.TALL_RUIN in keys
    lane = max(L['lanes'], key=lambda ln: len(ln['pts']))['pts']
    a, b = lane[0], lane[-1]
    assert max(seg_dist(p, a, b) for p in lane) > 0.15


# ---------------------------------------------------------------- V2.1: the S07 review (top-down "boxes on a grid")

P07 = {p['id']: p for p in S07['placements']}
CORE = set(L['core_blocks'])


def in_any_room(pt, pad=0.0):
    return any(v2.quad_dist(pt, q) <= pad for rm in L['rooms'] for q in rm['cells'])


def test_rooms_are_not_all_boxes():
    """L shapes, missing corners and back stores: at least 40 % of the core's rooms are not rectangles, and
    whole corners have come down in big fans that run downhill."""
    core = [r for r in L['rooms'] if r['block'] in CORE]
    assert sum(1 for r in core if not r['rect']) >= 0.4 * len(core)
    F = v2.Frame(v2.B.World(), S07['road_m'])
    assert len(L['corner_falls']) >= 4
    for u, v, fu, fv in L['corner_falls']:
        du, dv = F.downhill(u, v)
        assert fu * du + fv * dv > 0.2


def test_partial_walls_and_height_variety():
    """Every decay state stands somewhere, and the core's visible wall heights spread (stumps to the gable)."""
    states = {w[4] for w in L['walls']}
    assert {'full', 'damaged', 'low', 'stump', 'gap', 'tallruin', 'lintel'} <= states
    hs = [p['vis_h'] for p in S07['placements'] if p.get('block') in CORE and p.get('contact') == 'rigid'
          and p.get('vis_h') is not None]
    mean = sum(hs) / len(hs)
    sd = math.sqrt(sum((h - mean) ** 2 for h in hs) / len(hs))
    assert max(hs) - min(hs) >= 5.0 and sd >= 0.8


def test_lintels_rest_level_on_their_two_jambs():
    """A lintel doorway: the beam is carried by two named stone jambs of its own block, whose tops the composer
    levelled (the uphill jamb sunk deeper), and it spans both with its ends on the jamb tops."""
    W = v2.B.World()
    lintels = [p for p in S07['placements'] if p.get('contact') == 'bear']
    assert len(lintels) >= 3
    for ln in lintels:
        js = [P07[j] for j in ln['bears_on']]
        assert len(js) == 2 and all(j['contact'] == 'rigid' and j['block'] == ln['block'] for j in js)
        tops = []
        for j in js:
            ext = [s * 50.0 for s in j['size_m']]
            ax = v2.setdress_contact.axes(j['yaw'], 0, 0)
            g = [W.ground(*[c / 100.0 for c in v2.setdress_contact.to_world(ax, (j['x_cm'], j['y_cm'], 0), (fx * ext[0], fy * ext[1], 0))[:2]])
                 for fx in (-0.92, 0, 0.92) for fy in (-0.92, 0, 0.92)]
            tops.append(min(g) * 100.0 - j['settle']['sink_cm'] + j['size_m'][2] * 100.0)
        assert abs(tops[0] - tops[1]) < 4.0, (ln['id'], tops)
        span = math.hypot(js[0]['x_cm'] - js[1]['x_cm'], js[0]['y_cm'] - js[1]['y_cm']) / 100.0
        assert ln['size_m'][0] > span + 0.3 and ln['size_m'][0] < span + js[0]['size_m'][0]


def test_fallen_beams_lie_in_rooms_clear_of_standing_walls():
    standing = [((w[0], w[1]), (w[2], w[3])) for w in L['walls'] if w[4] in v2.STANDING]
    assert len(L['beams']) >= 6
    for u0, v0, u1, v1 in L['beams']:
        assert min(v2.seg_seg_dist((u0, v0), (u1, v1), a, b) for a, b in standing) >= 0.4
        assert in_any_room(((u0 + u1) / 2, (v0 + v1) / 2), pad=1.0)


def test_rubble_hugs_the_wall_bases():
    """The walls grow out of their own debris: dense stones within 0.9 m of the standing walls."""
    items = v2.BUILT[0].items if v2.BUILT else []
    base = [it for it in items if it.get('block') == 'base']
    standing = [((w[0], w[1]), (w[2], w[3])) for w in L['walls'] if w[4] in v2.STANDING]
    near = sum(1 for it in base if min(seg_dist((it['u'], it['v']), a, b) for a, b in standing) < 0.9)
    assert len(base) >= 2.5 * len(standing) and near >= 0.6 * len(base)


def test_creep_grows_in_the_roofless_rooms():
    items = v2.BUILT[0].items if v2.BUILT else []
    plants = [(it['u'], it['v']) for it in items if it.get('block') == 'creep']
    inside = [p for p in plants if in_any_room(p)]
    assert len(inside) >= 40
    for rm in L['rooms']:
        if rm['n_cells'] >= 2:
            assert any(any(v2.quad_dist(p, q) == 0 for q in rm['cells']) for p in plants), rm['block']


def test_ground_marks_doors_fans_road_and_ruin():
    """Trodden earth in front of every door, dust under every big fan, a wide worn path from the road with an
    apron on the verge, soot in burnt rooms, dry mud where water stood."""
    F = v2.Frame(v2.B.World(), S07['road_m'])
    site = v2.BUILT[0]
    G = site.ground
    earth = [g for g in G if g['surface'] == 'packed_earth']
    for (du, dv, name, k, fu, fv) in L['doors']:
        assert min(math.hypot(g['u'] - (du + fu * 1.1), g['v'] - (dv + fv * 1.1)) for g in earth) < 0.5
    dust = [g for g in G if g['surface'] == 'rubble_dust']
    for u, v, fu, fv, amount in L['fans']:
        if amount >= 0.45:
            assert min(math.hypot(g['u'] - u, g['v'] - v) for g in dust) < 4.5
    wide = [g for g in G if g['surface'] == 'path' and g['width'] >= 3.0]
    assert wide and min(F.road_dist(g['u'], g['v']) for g in wide) < 9.0
    assert any(g['surface'] == 'packed_earth' and F.road_dist(g['u'], g['v']) < 10.0 for g in G)
    assert sum(1 for g in G if g['surface'] == 'soot') >= 2
    assert sum(1 for g in G if g['surface'] == 'dry_mud') >= 3


def test_no_monolith_and_the_awnings_carry_their_cloth():
    """The V2.0 review: the BrokenStructer monolith is gone; the stall awnings are the Tent_C kit, the cloth
    sharing the frame's pivot (attach, same position and yaw), never a bare frame."""
    keys = [p['key'] for p in S07['placements']]
    assert 'AB_BrokenStructer' not in keys and 'AB_Tent_Cloth_B_frame' not in keys
    assert len(S07['units']) >= 2
    for u in S07['units']:
        mem = [p for p in S07['placements'] if p.get('unit') == u['name']]
        fr = [p for p in mem if p.get('unit_role') == 'frame']
        cl = [p for p in mem if p.get('unit_role') == 'cover']
        assert len(fr) == 1 and len(cl) == 1 and cl[0]['attach']
        assert (fr[0]['x_cm'], fr[0]['y_cm'], fr[0]['yaw']) == (cl[0]['x_cm'], cl[0]['y_cm'], cl[0]['yaw'])


def test_yards_break_the_grid():
    """Walled yards leave their block at 8-30 deg off the block's own grid."""
    assert len(L['yards']) >= 2
    rows = {r['block']: r for r in L['rows']}
    for y in L['yards']:
        a, b = y['pts'][0], y['pts'][1]
        t = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
        off = abs((t - rows[y['anchor']]['ang'] + 45.0) % 90.0 - 45.0)
        assert 7.0 <= off <= 31.0, (y['block'], off)


def assert_tripo_import_state(p):
    asset = v2.CAT[p['key']]
    assert bool(p.get('imported')) == bool(asset.get('imported')), p['id']
    if asset.get('imported'):
        assert p['verdict'] == 'use', p['id']
        measured = [v * p['scale'] / 100.0 for v in asset['size_cm']]
        assert all(abs(a - b) <= 0.02 for a, b in zip(p['size_m'], measured)), p['id']
    else:
        assert p.get('optional'), p['id']


def test_tripo_slots_track_import_state():
    """Pending meshes stay optional; imported meshes use their measured collision footprint."""
    for p in S07['placements']:
        if p['key'].startswith('T2_'):
            assert_tripo_import_state(p)


def test_offline_physical_check_is_clean():
    """The strict judge, run offline on the composed placements: no violation before the editor pass."""
    assert S07['offline_check']['violations'] == []
    v, w = v2.offline_check(v2.B.World(), S07)
    assert v == []


def test_watch_stops_on_pie_and_on_a_fault(tmp_path):
    """place_setdress.py watch: 2 when PIE runs or starts, 3 on a native fault line, 0 when the time is up."""
    import threading
    log = tmp_path / 'saskartarad.log'
    log.write_text('LogInit: boot\nPlay in editor total start\n', encoding='utf8')
    assert ps.watch(str(log), period=0.05, max_s=1.0, out=lambda m: None) == 2
    log.write_text('LogInit: boot\n', encoding='utf8')
    assert ps.watch(str(log), period=0.05, max_s=0.2, out=lambda m: None) == 0
    for line, code in (('LogPython: Error: HCR-NATIVE-002 access violation', 3),
                       ('LogPlayLevel: Creating play world package: /Game/level/UEDPIE_0_Saskarta_WP', 2)):
        def later():
            import time as t
            t.sleep(0.2)
            with open(log, 'a', encoding='utf8') as fh:
                fh.write(line + '\n')
        threading.Thread(target=later).start()
        assert ps.watch(str(log), period=0.05, max_s=5.0, out=lambda m: None) == code


def test_merged_v2_input_every_site_is_clean():
    """The placement input place_setdress.py --v2 reads (setdress_v2_sites.json + setdress_v2_groups/*.json):
    one record per site, no story set (S24-S26 are placed by their own lane), unique placement ids, and every
    site clean under the strict judge (re-run here, not trusted from the file), off the road core, Tripo
    slots consistent with actual imports, within 250 actors and 300 decals."""
    doc = ps.load_doc(True)
    ids = [s['id'] for s in doc['sites']]
    assert ids[0] == 'S07_WaitingWater' and len(ids) == len(set(ids))
    assert not set(ids) & ps.V2_STORY_SITES
    # a story wrapper swaps the V2 file for its own (story_sets/v8_ledge.py editor ...): read as is, no merge
    story = os.path.join(WORLD, 'story_sets', 'V8.json')
    if os.path.exists(story):
        keep = ps.SITES_V2_JSON
        try:
            ps.SITES_V2_JSON = story
            assert [s['id'] for s in ps.load_doc(True)['sites']] == ['S24_Ledge']
        finally:
            ps.SITES_V2_JSON = keep
    pids = [p['id'] for s in doc['sites'] for p in s['placements']]
    assert len(pids) == len(set(pids))
    W = v2.B.World()
    for s in doc['sites']:
        v, w = v2.offline_check(W, s)
        assert v == [], (s['id'], v[:3])
        P = [p for p in s['placements'] if not p.get('optional')]
        for p in P:
            assert p['road_clear_m'] >= 5.0, (s['id'], p['id'])
        for p in s['placements']:
            if p['key'].startswith('T2_'):
                assert_tripo_import_state(p)
        actors = sum(1 for p in P if not p['ism']) + len({(p['group'], p['asset']) for p in P if p['ism']})
        assert actors <= 250 and s['counts']['decals'] <= 300, (s['id'], actors, s['counts']['decals'])


# ---------------------------------------------------------------- the judge: bearing pieces, covers, loose pieces

def test_bear_needs_both_ends_on_its_named_supports():
    it = dict(key='B01_beam01', cat='wood', contact='bear', bears_on=['j1', 'j2'])
    ok = rep('l', (0, 0, 200), (130, 14, 16), gaps=[0, 0, 0, 40, 40, 40, 1, 2, 0],
             hits=['SD_j1'] * 3 + ['landscape'] * 3 + ['SD_j2'] * 3)
    assert sc.contact_violations(ok, it) == []
    seesaw = rep('l', (0, 0, 200), (130, 14, 16), gaps=[0, 0, 0, 40, 40, 40, 30, 30, 30],
                 hits=['SD_j1'] * 3 + ['landscape'] * 6)
    assert [x[0] for x in sc.contact_violations(seesaw, it)] == ['FLOAT']
    wrong = rep('l', (0, 0, 200), (130, 14, 16), gaps=[0] * 9, hits=['SD_j1'] * 3 + ['landscape'] * 3 + ['SD_w9'] * 3)
    assert [x[0] for x in sc.contact_violations(wrong, it)] == ['ON_ACTOR']


def test_bear_clash_counts_inside_its_own_block():
    items = {'l': dict(key='B01_beam01', cat='wood', contact='bear', bears_on=['j1'], block='A_1'),
             'j1': dict(key='AB_Pillar_A_01', cat='stone', contact='rigid', block='A_1'),
             'w': dict(key='AB_Side_Arch_small', cat='wall', contact='rigid', block='A_1')}
    reps = {'l': rep('l', (0, 0, 200), (130, 14, 16)), 'j1': rep('j1', (-110, 0, 100), (31, 42, 102)),
            'w': rep('w', (120, 0, 160), (43, 150, 163))}
    v = sc.pair_violations(reps, items)
    assert [x[0] for x in v] == ['CLASH'] and 'w' in v[0][1] and 'j1' not in v[0][1]


def test_cover_detached_from_its_frame():
    items = {'f': dict(key='AB_Tent_C_Frame', cat='cloth', contact='rigid', unit='s0', unit_role='frame'),
             'c': dict(key='AB_Tent_C_Cloth', cat='cloth', contact='carried', unit='s0', unit_role='cover')}
    reps = {'f': rep('f', (0, 0, 0), (150, 150, 180)), 'c': rep('c', (0, 0, 0), (140, 130, 70))}
    assert sc.unit_violations(reps, items) == []
    reps['c'] = rep('c', (40, 0, 0), (140, 130, 70), rot=(12, 0, 0))
    assert [x[1] for x in sc.unit_violations(reps, items)] == ['DETACHED']


def test_a_loose_piece_through_a_wall_is_a_clash():
    items = {'w': dict(key='AB_300x400_Mid', cat='wall', contact='rigid', block='A_1'),
             'b': dict(key='MV_Beam_06', cat='wood', contact='lie', block='beam')}
    reps = {'w': rep('w', (0, 0, 200), (12, 150, 200)), 'b': rep('b', (60, 0, 10), (150, 8, 10))}
    assert [x[0] for x in sc.pair_violations(reps, items)] == ['CLASH']
    reps['b'] = rep('b', (200, 0, 10), (150, 8, 10))
    assert sc.pair_violations(reps, items) == []


def test_offline_reports_level_and_stepped_jambs():
    """offline_reports puts a lintel on the higher jamb top: level jambs pass, a 20 cm step floats one end."""
    def pl(id_, key, x, z_sink, size, contact, **kw):
        d = dict(id=id_, key=key, cat='stone', x_cm=x, y_cm=0.0, yaw=0.0, size_m=size, contact=contact,
                 settle=dict(sink_cm=z_sink), ism=False, block='A_1')
        d.update(kw)
        return d
    flat = lambda x, y: 0.0                                                          # noqa: E731
    js = [pl('j1', 'AB_Pillar_A_01', -110.0, 12.0, [0.62, 0.84, 2.04], 'rigid'),
          pl('j2', 'AB_Pillar_A_01', 110.0, 12.0, [0.62, 0.84, 2.04], 'rigid')]
    ln = pl('l', 'B01_beam01', 0.0, 0.0, [2.63, 0.28, 0.32], 'bear', cat='wood', bears_on=['j1', 'j2'])
    reps, items = sc.offline_reports(js + [ln], flat)
    assert sc.judge(reps, items)[0] == []
    js[1]['settle']['sink_cm'] = 32.0
    reps, items = sc.offline_reports(js + [ln], flat)
    assert [x[1] for x in sc.judge(reps, items)[0]] == ['FLOAT']


# ---------------------------------------------------------------- the archetype API

ARCH_SITES = {'village': 'L14_OldTown', 'hamlet': 'L05_RidgeHamlet', 'farm': 'L03_ThreshingFarm',
              'caravanserai': 'S13_NumberedStop', 'fortress': 'S10_CrestFort', 'waystation': 'S19_LastWaystation',
              'works': 'S15_Works'}
_ARCH = {}


def arch_site(arch):
    if arch not in _ARCH:
        W = v2.B.World()
        out, _ = v2.build(W, [ARCH_SITES[arch]])
        _ARCH[arch] = (out[0], v2.BUILT[0], W)
    return _ARCH[arch]


def test_archetype_of_the_v1_kinds():
    assert v2.archetype_of(v2.site_row('S13_NumberedStop')) == 'caravanserai'
    assert v2.archetype_of(v2.site_row('S10_CrestFort')) == 'fortress'
    assert v2.archetype_of(v2.site_row('L05_RidgeHamlet')) == 'hamlet'
    assert v2.archetype_of(v2.site_row('L14_OldTown')) == 'village'
    assert v2.archetype_of(v2.site_row('L03_ThreshingFarm')) == 'farm'
    assert v2.archetype_of(v2.site_row('S19_LastWaystation')) == 'waystation'
    assert v2.archetype_of(v2.site_row('S15_Works')) == 'works'
    assert set(ARCH_SITES) == set(v2.ARCHETYPES)


def test_compose_is_deterministic_and_takes_overrides():
    W = v2.B.World()
    a = v2.compose(W, 'L03_ThreshingFarm')
    b = v2.compose(W, 'L03_ThreshingFarm')
    assert [(i['key'], round(i['u'], 3)) for i in a.items] == [(i['key'], round(i['u'], 3)) for i in b.items]
    c = v2.compose(W, 'L03_ThreshingFarm', seed='another')
    assert [i['key'] for i in c.items] != [i['key'] for i in a.items]
    assert v2.compose(W, 'S13_NumberedStop', court=(6, 4)).spec['court'] == (6, 4)


def pytest_generate_tests(metafunc):
    if 'arch' in metafunc.fixturenames:
        metafunc.parametrize('arch', sorted(ARCH_SITES))


def test_archetype_composes_a_sound_site(arch):
    """Every archetype, on its V1 site: physically clean offline, off the road core, rooms apart, doors on
    lanes, lanes connected, collapse downhill, within the actor budget."""
    so, site, W = arch_site(arch)
    L_ = so['v2']
    assert so['archetype'] == arch and len(so['placements']) >= 60
    assert so['offline_check']['violations'] == [], so['offline_check']['violations'][:5]
    for p in so['placements']:
        assert p['road_clear_m'] >= 5.0 and 'nudged' not in p.get('note', ''), p['id']
    assert rooms_overlap(L_) == []
    lanes = [ln['pts'] for ln in L_['lanes']]
    assert lanes and L_['doors']
    for d in L_['doors']:
        assert min(poly_dist(d[:2], p) for p in lanes) < 0.6
    # lanes join where they meet or cross anywhere along them (a court's paths cross at its centre)
    adj = {i: set() for i in range(len(lanes))}
    for i, a in enumerate(lanes):
        for j, b in enumerate(lanes):
            if i != j and min(v2.seg_seg_dist(p, q, r, t) for p, q in zip(a[:-1], a[1:]) for r, t in zip(b[:-1], b[1:])) < 1.5:
                adj[i].add(j)
    seen, todo = {0}, [0]
    while todo:
        k = todo.pop()
        for j in adj[k] - seen:
            seen.add(j)
            todo.append(j)
    assert seen == set(range(len(lanes)))
    F = site.frame
    fans = L_['fans']
    assert sum((fu * F.downhill(u, v)[0] + fv * F.downhill(u, v)[1]) > 0.2 for u, v, fu, fv, a in fans) >= 0.85 * len(fans)
    assert placed_actors(so) <= 250 and so['counts']['decals'] <= 300
