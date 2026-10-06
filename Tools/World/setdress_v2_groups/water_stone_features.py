"""Set dressing V2, group 'water and stone features': S17 Dry Cistern and the remaining small S* road sites.

    python Tools/World/setdress_v2_groups/water_stone_features.py            # JSON + one plot per site
    python Tools/World/setdress_v2_groups/water_stone_features.py --sites S17_DryCistern --no-plot

Method: docs/world/SETDRESS_V2.md. The composer primitives (setdress_v2.Composer) are used as they are; the
recipes below are this group's archetypes (cistern, fold, convoy, signal post, rest niche, hearth, seat,
cairn, marker). They are registered HERE, not in setdress_v2.ARCHETYPES (that table is pinned by the shared
tests), so this module runs its own compose() and build() with the same steps as setdress_v2.compose/build.

Output:
  Tools/World/setdress_v2_groups/water_stone_features.json   the placement input (setdress_v2_sites.json schema)
  docs/world/setdress_v2/<site>.png                          a top-down + axonometric plot per site

Sites NOT composed here (listed under 'skipped' in the JSON): S24_Ledge (story set V8, already composed in
Tools/World/story_sets), S25_LastLookBack (verify only: the story-owned V9 wall, add nothing), S26_HighVoiceHut
(story set, Tools/World/story_sets/S26.json). Other S* sites belong to the other groups.
"""
import argparse
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
WORLD = os.path.dirname(HERE)
ROOT = os.path.dirname(os.path.dirname(WORLD))
sys.path.insert(0, WORLD)
import build_setdress_sites as B  # noqa: E402
import setdress_v2 as V  # noqa: E402
from setdress_v2 import rect, terrace_frame, piece_dims, seg_dist  # noqa: E402
sys.path.insert(0, HERE)
from water_stone_grammar import (band, clump, rigid, ring_rect, road_pt, standing_stone,  # noqa: E402
                                 verge_link)
from water_stone_small import SMALL_SITES  # noqa: E402

GROUP = 'water_stone_features'
OUT_JSON = os.path.join(HERE, GROUP + '.json')
PLOTS = os.path.join(ROOT, 'docs', 'world', 'setdress_v2')
POTS = V.POTS

SKIPPED = {
    'S24_Ledge': 'story set V8 (Tools/World/story_sets/v8_ledge.py) already composed with the V2 method',
    'S25_LastLookBack': 'verify only: the story-owned V9 wall and Segalen stone; the plan says add NOTHING',
    'S26_HighVoiceHut': 'story set S26 (Tools/World/story_sets/S26.json), the relay room inside V10',
}


# ---------------------------------------------------------------------------- S17 the Dry Cistern

S17_LAYOUT = '''
  ==== road ====  apron + name stone at the verge, worn path down to the stair head
      well + trough + jars (Tripo, optional)   notice board | gauge column   keeper's room on the east flank
      R1 rim: low parapet (broken), pillars at the corners       stair: step blocks in each course gap,
        R2 course (1 m cut-stone steps)                          paved landings, rope-rail posts
          R3 course                                               broken jars lower and lower down
            R4 basin lip  | dry basin: cracked mud, the gauge staff, the dead trunk across, one whole jar
      far rim (downhill): a four-bay arcade, one collapsed span and uneven end piers = the silhouette
  the dry feed channel from the hill: culvert under the road (parapets), down the verge to the rim spout
  silt gradient: the lower the landing, the paler the mud ("full to the fourth step")
'''


def s17(C, sp):
    """The Dry Cistern: a stepped tank built into the slope right of the road, four nested courses of cut-stone
    steps down to a dry basin, the stair down the middle of the uphill side, an arcade on the far (downhill)
    rim as the skyline, the feed channel from the hill under the road, the well and the keeper's room."""
    F = C.F
    O = (0.0, 2.5)
    ang = F.contour_deg(*O)
    K = terrace_frame(ang, O)
    C.cu, C.cv = O
    rings = [(14.0, 11.0), (11.0, 8.0), (8.0, 5.0), (5.0, 2.5)]
    ST = (-1.55, 1.55)                                   # the stair opening (x), every course
    # -- lanes first (collapse fans, heaps and creep keep off them)
    C.path([K(0.0, 13.2), K(0.0, 1.2)], 2.6, strength=0.85)                       # down the stair
    C.path([K(-10.5, 14.2), K(-4.0, 13.4), K(0.0, 13.2), K(6.0, 13.3), K(12.0, 13.2), K(15.8, 12.0),
                  K(16.1, 4.0)], 1.7, wander=0.25)                                     # along the rim to the keeper
    road = verge_link(C, K(0.2, 13.4), width=2.8, strength=0.95, apron=(7.0, 5.0))
    far = C.path([K(15.8, 4.0), K(16.4, -9.0), K(16.0, -12.8), K(12.0, -13.6), K(4.0, -13.9)], 1.2, strength=0.55,
                 wander=0.3)                                   # from the keeper's room round to the arcade
    C.meta['lanes_named'] = dict(stair=0, rim=1)

    # -- R1: broken kerb; only two diagonal corner pillars survive. A four-bay far arcade lost an inner span.
    def rim_state(side, i, n):
        if side == 'd' and 1 <= i <= n - 2:
            return 'opening'                              # the arcade stands there
        return C.rng.choice(['stump', 'stump', 'stump', 'gap', 'low'])
    hx, hy = rings[0]
    blk_rim = ring_rect(C, O, ang, hx, hy, 'rim', rim_state, 'rim', stair=(-2.2, 2.2))
    for sx, sy in ((-1, 1), (1, -1)):
        rigid(C, 'B01_pillar01', *K(sx * (hx + 0.35), sy * (hy + 0.35)), ang, 'rim', blk_rim, 30,
              scale=0.85, state='pillar', note='surviving corner pillar of the rim')
    fallen = C.rng.choice((1, 1))  # consume the old draw, but put the collapse inside the formerly uniform row
    for i in range(4):
        x = -4.5 + 3.0 * i
        if i == fallen:
            # this arch came down outward (downhill): a heap, the voussoir chunks, a rubble-dust fan
            pu, pv = K(x, -hy - 0.2)
            C.walls.append(K(x - 1.5, -hy - 0.2) + K(x + 1.5, -hy - 0.2) + ('gap', blk_rim))
            C.collapse(pu, pv, F.downhill(pu, pv), 1.0, ang)
            continue
        rigid(C, 'AB_Side_Arch', *K(x, -hy - 0.2), ang, 'arcade', blk_rim, 22, state='arcade',
              note='the far-rim arcade: the silhouette from the road')
        C.walls.append(K(x - 1.5, -hy - 0.2) + K(x + 1.5, -hy - 0.2) + ('full', blk_rim))
    for sx, scale, sink in ((-1, 0.62, 55), (1, 0.48, 75)):
        rigid(C, 'AB_Damaged_Pillar_A' if sx < 0 else 'AB_Damaged_Pillar_A1', *K(sx * 7.35, -hy - 0.25),
              ang + (0 if sx < 0 else 180), 'arcade', blk_rim, sink, scale=scale, state='pier',
              note='uneven broken pier at the arcade end')

    # -- R2..R4: the steps (cut-stone courses), decayed; the stair runs down through a gap in each course
    def step_state(depth):
        def f(side, i, n):
            r = C.rng.random()
            if side in ('f', 'b') and depth == 1 and r < 0.25:
                return 'gap'
            if r < 0.12:
                return 'gap'
            if r < 0.3:
                return 'low'
            return 'stump'
        return f
    courses = []
    for k, (hx_, hy_) in enumerate(rings[1:], start=1):
        courses.append(ring_rect(C, O, ang, hx_, hy_, 'step%d' % k, step_state(k), 'steps', stair=ST))
    # one corner of the second course has slumped into the tank, and part of the west flank with it: big fans
    cu_, cv_ = K(rings[1][0], rings[1][1])
    C.collapse_corner(cu_, cv_, *F.downhill(cu_, cv_), ang)
    for y in (2.0, -3.5):
        pu, pv = K(-rings[1][0] - 0.3, y)
        C.collapse(pu, pv, F.downhill(pu, pv), 1.0, ang + 90.0)
    # the lowest course on the downhill side is silted over: mud laps over its stumps
    C.patch('dry_mud', *K(0.0, -rings[3][1] - 1.2), ang, 2 * rings[2][0] - 1.0, 3.0, 0.8, 'capsule', order=2)

    # -- the stair: two step blocks in each course gap, a paved landing between courses, rope-rail posts
    for k, (hx_, hy_) in enumerate(rings[1:], start=1):
        for row, sink in ((0.0, 18.0), (-0.62, 36.0)):
            for sx in (-0.78, 0.78):
                C.add('B01_brick01', *K(sx, hy_ + row), ang + C.rng.uniform(-2, 2), 'stair', 'rigid', block='stairs',
                      sink_cm=sink + C.rng.uniform(-4, 4), material_set='stone', ism=True, state='step')
    for k in range(3):
        y = (rings[k][1] + rings[k + 1][1]) / 2.0 - 0.25
        if C.rng.random() < 0.8:
            C.add('B01_floor01', *K(C.rng.uniform(-0.15, 0.15), y), ang + C.rng.uniform(-3, 3), 'stair', 'rigid',
                  scale=0.78, sink_cm=16, material_set='stone', block='landings', ism=True)
    for k in range(3):
        y = (rings[k][1] + rings[k + 1][1]) / 2.0 + 0.4
        rigid(C, 'MV_Fence_01_Log1', *K(1.35, y), ang, 'rail', 'rail', 22, state='post', mat='wood',
              note='rope-rail post (the rope is gone)')
    C.add('MV_Rope_01', *K(0.55, rings[3][1] - 1.0), 0, 'stair', 'rest', note='the rope rail, fallen to the bottom')
    # broken jars on lower and lower steps; one whole jar on the lowest step
    for k, (x, rl) in enumerate(((0.7, 90), (-0.6, 95), (0.5, 85))):
        y = (rings[k][1] + rings[k + 1][1]) / 2.0 + C.rng.uniform(-0.6, 0.6)
        C.add(C.rng.choice(POTS), *K(x, y), C.rng.uniform(0, 360), 'jars', 'rest', roll=rl, note='a broken jar')
    C.add('AB_Clay_Pot_A', *K(-0.9, rings[3][1] - 0.9), 0, 'jars', 'rest', note='the one whole jar, on the lowest step')

    # -- the dry basin: cracked mud, the gauge staff, the dead trunk across
    bx, by = rings[3]
    C.patch('dry_mud', *K(0, 0), ang, 2 * bx + 0.6, 2 * by + 0.6, 1.0, order=2)
    C.patch('dry_mud', *K(1.5, -0.4), ang + 8, 7.0, 3.6, 0.9, order=2)
    rigid(C, 'B01_scale01', *K(2.6, 1.4), ang, 'gauge', 'gauge', 25, mat='wood', state='gauge',
          note='the water-level staff standing in the dry basin: LEVEL 0 %')
    C.add('PH_trunk_02', *K(-0.6, -0.5), ang + 14, 'basin', 'lie', sink_cm=10, material_set='wood',
          note='the dead trunk lying across the bottom')
    clump(C, *K(-3.8, -1.4), 1.0, 5, 0.4)
    clump(C, *K(3.9, -1.5), 0.9, 4, 0.4)
    # the silt gradient: each landing band paler and weaker the higher it lies (the water went down step by step)
    for k, s in ((2, 0.75), (1, 0.5), (0, 0.3)):
        (hx0, hy0), (hx1, hy1) = rings[k], rings[k + 1]
        band(C, O, ang, hx0, hy0, hx1, hy1, 'dry_mud', s, order=1, skip_up=1.6)

    # -- the stair head: notice board, gauge column; the rim apron
    rigid(C, 'B01_sign02', *K(2.9, 12.7), ang, 'head', 'head', 18, mat='wood', state='board',
          note='the notice board at the top of the stair (CIN_P17 POV 40)')
    rigid(C, 'B01_pillar01', *K(-3.0, 12.7), ang, 'head', 'head_col', 25, scale=0.7, state='gauge_column',
          note='gauge column: the old level marks cut in it')
    C.patch('packed_earth', *K(0.0, 13.6), ang, 10.0, 4.2, 0.95, order=1)
    C.patch('packed_earth', *K(0.0, 1.0), ang, 30.0, 26.0, 0.5, order=0)             # the whole tank floor, faint

    # -- the well at the top, its trough, the jars (Tripo, optional)
    wu, wv = K(-10.5, 15.4)
    rigid(C, 'MV_well', wu, wv, ang + 10, 'well', 'well', 10, state='well', note='the well at the top of the tank')
    C.patch('path', wu, wv, 0, 4.4, 4.4, 0.85, order=2)
    tu, tv = K(-13.4, 14.0)
    C.add('MV_wash_tub', tu, tv, ang - 12, 'well', 'rest', material_set='wood', note='the dry trough')
    C.add('MV_bucket_03', *K(-8.9, 16.3), 0, 'well', 'rest', roll=80, note='a bucket on its side')
    jp = C.find_spot([K(-7.6, 16.8), K(-13.0, 17.0)], 1.4, margin=0.3)
    if jp:
        C.add('T2_jars', jp[0], jp[1], ang, 'well', 'rigid', sink_cm=8, material_set='stone', block='jars',
              state='jars', vis_h=2.2, note='clay water jars by the well')

    # -- the keeper's room on the east flank (a real tank had its keeper): one room, the door onto the rim path
    ra = ang
    ku, kv = K(17.5, 0.5)
    if C.fits(C.quads(ku, kv, ra, rect(0, 0, 2, 1)), margin=0.8):
        C.block('KR', ku, kv, ra, [rect(0, 0, 2, 1)], 2, group='houses', collapse_corners=1, lintel_p=0.6)
        C.block_lane['KR'] = far
    C.door_spurs(width=1.2)

    # -- the feed channel: from the hill down to the road (culvert), out on the far verge, down to the rim spout
    top = K(11.0, 40.0)
    ch = F.descent(top[0], top[1], lambda u, v: F.road_dist(u, v) < 7.4, step=2.0, n=60)
    cr = ch[-1]
    qu, qv = road_pt(C, *cr)
    n_ = math.hypot(cr[0] - qu, cr[1] - qv) or 1.0
    ex = (qu - (cr[0] - qu) / n_ * 7.4, qv - (cr[1] - qv) / n_ * 7.4)           # the culvert mouth, far verge
    spout = K(8.0, hy + 1.4)
    ch2 = [ex] + [(ex[0] + (spout[0] - ex[0]) * t, ex[1] + (spout[1] - ex[1]) * t) for t in np.linspace(0, 1, 7)[1:]]
    C.nblock += 1
    cblk = 'channel_%d' % C.nblock
    Lp = piece_dims('B01_channel01')[0] * 0.97
    for line in (ch, ch2):
        for (u0, v0), (u1, v1) in zip(line[:-1], line[1:]):
            seg = math.hypot(u1 - u0, v1 - v0)
            kk = max(1, int(round(seg / Lp)))
            a_ = math.degrees(math.atan2(v1 - v0, u1 - u0))
            for i in range(kk):
                t = (i + 0.5) / kk
                pu, pv = u0 + (u1 - u0) * t, v0 + (v1 - v0) * t
                if F.road_dist(pu, pv) < 8.4 or math.hypot(pu - spout[0], pv - spout[1]) < 1.2:
                    continue
                C.add('B01_channel01', pu, pv, a_ - 90.0, 'channel', 'channel', ism=True, block=cblk,
                      material_set='stone',
                      settle_over=dict(mode='trace', max_tilt_deg=9, rand_tilt_deg=0, z_rule='mean', sink_cm=38))
        bed_pts = [p for p in line if F.road_dist(*p) >= 6.6]
        if len(bed_pts) >= 2:
            C.path(bed_pts, 2.0, surface='gravel', strength=0.75, order=1, lane=False)
    for mouth in (cr, ex):
        ta = math.degrees(math.atan2(qv - mouth[1], qu - mouth[0])) + 90.0
        for side in (-1, 1):
            pu = mouth[0] + side * 1.5 * math.cos(math.radians(ta))
            pv = mouth[1] + side * 1.5 * math.sin(math.radians(ta))
            if F.road_dist(pu, pv) >= 6.4:
                rigid(C, 'AB_Broken_Walls', pu, pv, ta, 'channel', 'culvert', 10, state='parapet',
                      note='culvert parapet at the road verge')
    C.meta['channel'] = [ch, ch2]
    # -- the circuit's edge: dry-stone field terraces below the arcade (the fields the tank watered)
    # Two staggered remnants instead of parallel, evenly-spaced rows of short wall dashes.
    for z_off, (x0, x1) in ((-1.2, (-26.0, -3.0)), (-2.3, (2.0, 18.0))):
        z = F.g(*K(0.0, -hy - 6.0)) + z_off
        pts = V.contour_k(C, K, z, x0, x1, -hy - 22.0, -hy - 3.0, step=4.0)
        for run in V.runs_clear(C, pts):
            if sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(run[:-1], run[1:])) >= 6.0:
                C.terrace_wall(run, gap_every=0.22)
    # the entrance name stone where the path leaves the road
    if road:
        nu, nv = road[0]
        du_, dv_ = road[1][0] - nu, road[1][1] - nv
        n_ = math.hypot(du_, dv_) or 1.0
        standing_stone(C, 'B01_marker01', nu - dv_ / n_ * 1.8 + du_ / n_ * 0.6, nv + du_ / n_ * 1.8 + dv_ / n_ * 0.6,
                       ang, 1.2, 22, block='namestone', note='entrance name stone (I-series inscription later)')
    # creep along the rim and in the course corners (the lee holds the silt)
    for k, (hx_, hy_) in enumerate(rings[1:], start=1):
        for sx in (-1, 1):
            for sy in (-1, 1):
                if C.rng.random() < 0.7:
                    clump(C, *K(sx * (hx_ - 0.7), sy * (hy_ - 0.7)), 0.8, 3, 0.35)
    C.meta.update(frame=dict(ang=ang, O=O), rings=rings)


# ---------------------------------------------------------------------------- the group's archetype table

SITES = {
    'S17_DryCistern': dict(archetype='cistern', recipe=s17, seed='S17v2', layout=S17_LAYOUT, burnt=1, mud=2,
                           creep_edge=26, radius_m=40,
                           notes='V2 (SETDRESS_V2.md): stepped tank in the slope; far-rim arcade = the silhouette.'),
}
SITES.update(SMALL_SITES)


# ---------------------------------------------------------------------------- compose / build (as setdress_v2)

def compose(W, sid, **overrides):
    row = V.site_row(sid)
    sp = dict(V.BASE)
    sp['decay'] = row.get('decay', sp['decay'])
    sp['side'] = row.get('side')
    sp.update(SITES[sid])
    sp.update(overrides)
    lat = row.get('lateral_m') or 0.0
    s = B.Site(sid, sp.get('name', row['name']), row['road_m'], lat, row['kind'], sp.get('role', row['role']),
               sp.get('story', row.get('story') or ''), sp['decay'], sp.get('style', row.get('style') or ''),
               sp.get('order', row.get('order', 2)), sp.get('radius_m', row.get('radius_m', 40)),
               layout=sp.get('layout', row.get('layout') or ''), notes=sp.get('notes', row.get('notes') or ''),
               story_owned=row.get('story_owned') or [])
    F = V.Frame(W, row['road_m'], lat)
    import zlib
    C = V.Composer(s, F, zlib.crc32(str(sp.get('seed') or sid + 'v2').encode()))
    sp['recipe'](C, sp)
    s.spec = {k: v for k, v in sp.items() if not callable(v)}
    C.finish(sp)
    # scatter (rubble, packing stones, plants) never reaches the road core: sweep it off the verge edge
    s.items[:] = [it for it in s.items if not (it.get('ism') and it.get('block') in ('fan', 'base', 'creep')
                                               and F.road_dist(it['u'], it['v']) < 5.9)]
    return s


def build(W, sids):
    S = [compose(W, sid) for sid in sids]
    out_sites, totals = B.build(W, S)
    by_id = {s.sid: s for s in S}
    for so in out_sites:
        s = by_id[so['id']]
        V.resolve_refs(so)
        so['archetype'] = s.spec['archetype']
        so['group'] = GROUP
        so['ground'] = V.ground_records(so, s)
        so['units'] = s.units
        so['views'] = V.v2_views(W, s, s.frame, so['placements'])
        so['v2'] = s.v2
        so['counts']['decals'] = len(so['ground'])
        so['load_box_cm'] = [round(v) for v in so['load_box_cm']]
        v, w = V.offline_check(W, so)
        so['offline_check'] = dict(violations=[list(x) for x in v], waived=[list(x) for x in w],
                                   note='estimated offline (setdress_contact.offline_reports); check2 in the editor decides')
    return out_sites, totals, by_id


# ---------------------------------------------------------------------------- soundness (the archetype test's rules)

def poly_dist(p, pts):
    return min(seg_dist(p, a, b) for a, b in zip(pts[:-1], pts[1:]))


def placed_actors(so):
    P = [p for p in so['placements'] if not p.get('optional')]
    return sum(1 for p in P if not p['ism']) + len({(p['group'], p['asset']) for p in P if p['ism']})


def soundness(so, s):
    """The rules test_archetype_composes_a_sound_site applies, for this group's sites. Returns a list of problems."""
    out = []
    L_ = so['v2']
    if so['offline_check']['violations']:
        out.append('offline violations: %s' % so['offline_check']['violations'][:4])
    for p in so['placements']:
        if p['road_clear_m'] < 5.0 or 'nudged' in p.get('note', ''):
            out.append('road core: %s %s %.2f %s' % (p['id'], p['key'], p['road_clear_m'], p.get('note', '')))
    lanes = [ln['pts'] for ln in L_['lanes']]
    F = s.frame
    if lanes:
        if min(F.road_dist(u, v) for pts in lanes for u, v in pts) > 9.0:
            out.append('no lane reaches the road verge')
        adj = {i: set() for i in range(len(lanes))}
        for i, a in enumerate(lanes):
            for j, b in enumerate(lanes):
                if i != j and min(V.seg_seg_dist(p, q, r, t) for p, q in zip(a[:-1], a[1:])
                                  for r, t in zip(b[:-1], b[1:])) < 1.5:
                    adj[i].add(j)
        seen, todo = {0}, [0]
        while todo:
            k = todo.pop()
            for j in adj[k] - seen:
                seen.add(j)
                todo.append(j)
        if seen != set(range(len(lanes))):
            out.append('lanes not connected: %s' % sorted(set(range(len(lanes))) - seen))
        for d in L_['doors']:
            if min(poly_dist(d[:2], p) for p in lanes) >= 0.6:
                out.append('door off its lane %s' % (d[:3],))
    fans = L_['fans']
    if fans:
        down = sum((fu * F.downhill(u, v)[0] + fv * F.downhill(u, v)[1]) > 0.2 for u, v, fu, fv, a in fans)
        if down < 0.85 * len(fans):
            out.append('fans downhill %d/%d' % (down, len(fans)))
    if placed_actors(so) > 250 or so['counts']['decals'] > 300:
        out.append('budget: %d actors, %d decals' % (placed_actors(so), so['counts']['decals']))
    return out


# ---------------------------------------------------------------------------- plots

def plot(W, so, path):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import setdress_v2_plot as P
    F = V.Frame(W, so['road_m'], so.get('lateral_m') or 0.0)
    win = P.site_window(so, F, margin=6.0)
    cu, cv = so['v2']['core']
    R = max(10.0, min(34.0, max(win[1] - win[0], win[3] - win[2]) / 2.6))
    fig, axs = plt.subplots(1, 2, figsize=(24, 11))
    c = so['counts']
    title = '%s (%s), top-down\n%d placements (%d actors, %d ISM), %d decals; offline check: %d violations' % (
        so['id'], so['archetype'], c['placements'], placed_actors(so), c['ism_instances'], c['decals'],
        len(so['offline_check']['violations']))
    sm = P.topdown(axs[0], so, F, title, window=win)
    # the road band, from the spline sampled every 2 m (the plot module's own band skips long spline segments)
    from matplotlib.patches import Polygon
    ss = np.arange(max(0.0, so['road_m'] - 220.0), min(W.R.length, so['road_m'] + 220.0), 2.0)
    RP = np.array([F.site(*(W.R.xy(s_) / 100.0)) for s_ in ss])
    for a, b in zip(RP[:-1], RP[1:]):
        d = b - a
        nrm = np.array([-d[1], d[0]]) / (np.hypot(*d) or 1.0) * 4.5
        axs[0].add_patch(Polygon([a + nrm, b + nrm, b - nrm, a - nrm], closed=True, fc='#8a8580', ec='none', alpha=0.55,
                                 zorder=0.8))
    axs[0].set_xlim(win[0], win[1])
    axs[0].set_ylim(win[2], win[3])
    fig.colorbar(sm, ax=axs[0], shrink=0.4, label='visible wall height (m)')
    P.axo(axs[1], so, F, W, '%s, axonometric from the road side' % so['id'], window=(cu - R, cu + R, cv - R, cv + R))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fig.savefig(path, dpi=60, bbox_inches='tight')
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------- main

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--sites', nargs='*', default=list(SITES))
    ap.add_argument('--no-plot', action='store_true')
    ap.add_argument('--no-write', action='store_true', help='compose and check only (no JSON)')
    args = ap.parse_args(argv)
    W = B.World()
    out_sites, t, by_id = build(W, args.sites)
    bad = 0
    for so in out_sites:
        c = so['counts']
        probs = soundness(so, by_id[so['id']])
        bad += len(probs)
        print('%-18s %-10s placements %4d actors %3d ism %4d decals %3d offline violations %d %s' % (
            so['id'], so['archetype'], c['placements'], placed_actors(so), c['ism_instances'], c['decals'],
            len(so['offline_check']['violations']), 'OK' if not probs else 'PROBLEMS'))
        for p in probs[:12]:
            print('    ', p)
    if not args.no_write:
        old = {}
        if os.path.exists(OUT_JSON) and set(args.sites) != set(SITES):
            old = {s['id']: s for s in json.load(open(OUT_JSON, encoding='utf8'))['sites']}
        for so in out_sites:
            old[so['id']] = so
        sites = [old[k] for k in SITES if k in old]
        doc = dict(generated_by='Tools/World/setdress_v2_groups/water_stone_features.py', group=GROUP,
                   method='docs/world/SETDRESS_V2.md', level='/Game/level/Saskarta_WP',
                   conventions=dict(xy='world cm; yaw = UE yaw deg', bounds='x_cm/y_cm is the mesh BOUNDS CENTRE',
                                    ground='decal patches: DecalActor pitch -90, yaw, size (depth/2, width/2, length/2)',
                                    contact='rigid | rest | lie | bear | carried | stack (SETDRESS_V2.md section 3)',
                                    optional='Tripo models still in production: placed only with --with-optional'),
                   skipped=SKIPPED, rejected=t['rejected'], checks=t['checks'], sites=sites)
        with open(OUT_JSON, 'w', encoding='utf8') as fh:
            json.dump(doc, fh, indent=1, ensure_ascii=False)
        print('wrote', OUT_JSON)
    if not args.no_plot:
        for so in out_sites:
            print('plot', plot(W, so, os.path.join(PLOTS, so['id'] + '.png')))
    print('rejected', t['rejected'][:10])
    return bad


if __name__ == '__main__':
    sys.exit(1 if main() else 0)
