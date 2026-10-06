"""Set dressing V2, group 'lone farms and hamlets, part 1': L01-L08, composed on the real terrain.

    python Tools/World/setdress_v2_groups/lone_farms_hamlets_1.py            # JSON + one plot per site
    python Tools/World/setdress_v2_groups/lone_farms_hamlets_1.py --sites L03_ThreshingFarm --no-write

Method: docs/world/SETDRESS_V2.md. The composer (setdress_v2.Composer) and the judge (setdress_contact) are used
as they are. The recipes below are this group's archetypes, one per site, each authored for its own ground
(read from the Gaea heightmap, Saved/TerrainRebuild/Current_u16.png, through setdress_v2.Frame):

  L01 farm      a stone farmhouse with a tall gable facing the road, a byre and a walled yard, the riveted cradle
                the farm is named for, a paddock, and field walls reaching down to the road
  L02 orchard   contour terrace walls stepping down the slope, dead apricot trees in rows on each terrace, the
                drying deck on its piers and the field house at the top, the dry feed channel and its sluice
  L03 farm      a farmhouse and byre on the west bench, the threshing floor on the ravine rim with its hoist
  L04 camp      the cart left at the foot of the grade, a trail of its load down to a dry-stone sheep fold
  L05 hamlet    two terraces of collapsed rooms on the only bench, one two-storey shell for the crest view
  L06 vignette  three carts broken on the steep descent, the verge parapet broken where one went over
  L07 camp      reed racks in rows on the dry reed bed, bundles in stooks, the plank walk, the cold camp
  L08 hamlet    a courtyard house and two tall shells, walled gardens of dead fruit trees, the dry garden pool

They are registered HERE, not in setdress_v2.ARCHETYPES (that table is pinned by the shared tests), so this
module runs its own compose() and build() with the same steps as setdress_v2.compose/build.

Output:
  Tools/World/setdress_v2_groups/lone_farms_hamlets_1.json   the placement input (setdress_v2_sites.json schema)
  docs/world/setdress_v2/<site>.png                          a top-down + axonometric plot per site
Tripo models (T2_*) are placed as optional slots (the composer marks them); the offline check leaves them out.
"""
import argparse
import json
import math
import os
import sys
import zlib

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
WORLD = os.path.dirname(HERE)
ROOT = os.path.dirname(os.path.dirname(WORLD))
sys.path.insert(0, WORLD)
import build_setdress_sites as B  # noqa: E402
import setdress_v2 as V  # noqa: E402
from setdress_v2 import PIECE_M, rect, terrace_frame, nearest_on, piece_dims, seg_dist  # noqa: E402

GROUP = 'lone_farms_hamlets_1'
OUT_JSON = os.path.join(HERE, GROUP + '.json')
PLOTS = os.path.join(ROOT, 'docs', 'world', 'setdress_v2')
STONES, COBBLES, BRICKS, SHRUBS, TUFTS, POTS = V.STONES, V.COBBLES, V.BRICKS, V.SHRUBS, V.TUFTS, V.POTS
FENCES = ['MV_Fence_01_V1', 'MV_Fence_01_V2', 'MV_Fence_01_V3']
BAGS = ['MV_jute_bag_%02d' % i for i in range(1, 11)]
BOXES = ['MV_box_01', 'MV_box_02', 'MV_box_03', 'MV_box_04', 'MV_box_05']
STUMPS = ['PH_stump_01', 'PH_stump_02', 'FAB_Stump']
BASE_SETTLE = V.RUBBLE_SETTLE
LIE = dict(mode='trace', max_tilt_deg=25, rand_tilt_deg=6, z_rule='mean')


# ---------------------------------------------------------------------------- small shared grammar

def rigid(C, key, u, v, yaw, group, block, sink, scale=1.0, state='stone', mat='stone', **kw):
    """A plumb architectural piece (z so no sample floats; the uphill side buried), with its visible height."""
    H = V.CAT[key]['size_cm'][2] / 100.0 * (max(scale) if isinstance(scale, (tuple, list)) else scale)
    return C.add(key, u, v, yaw, group, 'rigid', scale=scale, block=block, sink_cm=round(sink, 1), material_set=mat,
                 state=state, vis_h=round(H - sink / 100.0, 2), **kw)


def prop(C, key, u, v, yaw, group, mat='wood', **kw):
    """A loose prop standing on the ground (contact 'rest')."""
    return C.add(key, u, v, yaw, group, 'rest', material_set=mat, **kw)


def lie(C, key, u, v, yaw, group, sink=6, mat='wood', **kw):
    """A fallen or dropped piece lying on the ground, partly buried (contact 'lie')."""
    return C.add(key, u, v, yaw, group, 'lie', sink_cm=sink, material_set=mat, **kw)


def along(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def ang_of(a, b):
    return math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))


def clear_spot(C, cands, r, margin=0.6):
    """C.find_spot, but tolerant of an empty candidate list."""
    return C.find_spot(list(cands), r, margin) if cands else None


def fence_run(C, pts, group='fence', block=None, gaps=(), keys=FENCES, sink=12):
    """Timber fence panels (2.56 m) along a polyline, one block (panels butt, never clash); gaps = panel indices
    left out (a gate, a fallen panel). Fallen panels lie beside their gap."""
    C.nblock += 1
    blk = block or 'fence_%d' % C.nblock
    n = 0
    for a, b in zip(pts[:-1], pts[1:]):
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        m = max(1, int(L / 2.62))
        an = ang_of(a, b)
        for j in range(m):
            t = (j + 0.5) / m
            p = along(a, b, t)
            if n in gaps:
                n += 1
                continue
            n += 1
            C.add(C.rng.choice(keys), p[0], p[1], an - 90.0 + C.rng.uniform(-3, 3), group, 'rigid', sink_cm=sink,
                  material_set='wood', block=blk, state='fence', vis_h=1.0)
    return blk


def hedge(C, pts, every=2.2, side=0.7, shrub_p=0.45, skip_p=0.35):
    """Dead shrubs and dry tufts along a field wall's foot (the plough never reached it): an old field edge."""
    for a, b in zip(pts[:-1], pts[1:]):
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        n = max(1, int(L / every))
        nu, nv = -(b[1] - a[1]) / (L or 1.0), (b[0] - a[0]) / (L or 1.0)
        for k in range(n):
            if C.rng.random() < skip_p:
                continue
            t = (k + C.rng.uniform(0.2, 0.8)) / n
            s = C.rng.choice((-1, 1)) * side * C.rng.uniform(0.8, 1.4)
            u, v = a[0] + (b[0] - a[0]) * t + nu * s, a[1] + (b[1] - a[1]) * t + nv * s
            if C.on_lane(u, v, 0.4) or C.F.road_dist(u, v) < 7.0:
                continue
            if C.rng.random() < shrub_p:
                C.add(C.rng.choice(SHRUBS), u, v, C.rng.uniform(0, 360), 'creep', scale=(0.9, 1.6), ism=True,
                      block='creep')
            else:
                C.add(C.rng.choice(TUFTS), u, v, C.rng.uniform(0, 360), 'creep_grass', scale=(0.8, 1.3), ism=True,
                      block='creep')


def stubble(C, quad, row_ang, spacing=2.6, every=3.2, keep=0.45):
    """Old furrows: dry tufts in rows across a field (a quad in site metres), most of them gone."""
    cu = sum(p[0] for p in quad) / 4.0
    cv = sum(p[1] for p in quad) / 4.0
    R = max(math.hypot(p[0] - cu, p[1] - cv) for p in quad)
    ca, sa = math.cos(math.radians(row_ang)), math.sin(math.radians(row_ang))
    for r_ in np.arange(-R, R, spacing):
        for s_ in np.arange(-R, R, every):
            if C.rng.random() > keep:
                continue
            u = cu + ca * s_ - sa * r_ + C.rng.uniform(-0.4, 0.4)
            v = cv + sa * s_ + ca * r_ + C.rng.uniform(-0.25, 0.25)
            if not V.in_quad((u, v), quad) or C.on_lane(u, v, 0.3) or C.F.road_dist(u, v) < 7.0:
                continue
            C.add(C.rng.choice(TUFTS), u, v, C.rng.uniform(0, 360), 'creep_grass', scale=(0.7, 1.1), ism=True,
                  block='creep')


def dead_tree(C, key, u, v, scale, block, note='', group='trees'):
    """A standing dead tree, plumb and rooted (sunk, a few stones and tufts round the foot)."""
    H = V.CAT[key]['size_cm'][2] / 100.0 * scale
    C.add(key, u, v, C.rng.uniform(0, 360), group, 'rigid', scale=scale, block=block, sink_cm=25, material_set='wood',
          state='tree', vis_h=round(H - 0.25, 2), note=note or 'dead tree')
    for k in range(C.rng.randint(2, 4)):
        a = C.rng.uniform(0, 2 * math.pi)
        r = C.rng.uniform(0.6, 1.3) * max(1.0, scale)
        C.add(C.rng.choice(TUFTS), u + r * math.cos(a), v + r * math.sin(a), C.rng.uniform(0, 360), 'creep_grass',
              scale=(0.8, 1.2), ism=True, block='creep')


def spill_fan(C, u, v, keys, n, mean_d=1.4, spread=35.0, group='spill', max_d=6.0, du=None, dv=None, lying=False):
    """A load spilled downhill of (u, v): pieces at exponential distances down the fall line, each kept clear
    of the pieces already placed (they rolled apart, they do not interpenetrate)."""
    if du is None:
        du, dv = C.F.downhill(u, v)
    placed = []
    for _ in range(n * 6):
        if len(placed) >= n:
            break
        d = min(max_d, 0.4 + C.rng.expovariate(1.0 / mean_d))
        a = math.radians(C.rng.uniform(-spread, spread))
        cu, cv = du * math.cos(a) - dv * math.sin(a), du * math.sin(a) + dv * math.cos(a)
        pu, pv = u + cu * d, v + cv * d
        key = C.rng.choice(keys)
        r = 0.5 * max(V.CAT[key]['size_cm'][:2]) / 100.0
        if not C.point_clear(pu, pv, margin=r + 0.1, lane_margin=0.2, road_m=6.5):
            continue
        if any(math.hypot(pu - a_, pv - b_) < r + rr + 0.05 for a_, b_, rr in placed):
            continue
        placed.append((pu, pv, r))
        if lying:
            lie(C, key, pu, pv, C.rng.uniform(0, 360), group, sink=3, roll=C.rng.choice((0, 0, 90)))
        else:
            prop(C, key, pu, pv, C.rng.uniform(0, 360), group, roll=(90 if key in POTS and C.rng.random() < 0.5 else 0))
    return placed


def track_to_road(C, start, width=2.8, strength=0.9, bend=0.0, verge=6.5, apron=True):
    """A worn cart track from start (site m) to the road verge: it leaves the road square to it, bends once on
    the way (bend: metres of sideways offset at the middle), with a trodden apron where it meets the verge."""
    W = C.F.W
    _, q = W.road_distance([C.F.world(*start)])
    qu, qv = C.F.site(float(q[0]), float(q[1]))
    du, dv = start[0] - qu, start[1] - qv
    n = math.hypot(du, dv) or 1.0
    du, dv = du / n, dv / n
    end = (qu + du * verge, qv + dv * verge)
    mid = along(start, end, 0.5)
    mid = (mid[0] - dv * bend, mid[1] + du * bend)
    if apron:
        C.patch('packed_earth', end[0] + du * 1.6, end[1] + dv * 1.6, math.degrees(math.atan2(dv, du)), 6.5, 5.0, 0.85,
                order=1)
    return C.path([start, mid, end], width, wander=0.45, strength=strength)


def contour_runs(C, K, z, x0, x1, y_lo, y_hi, step=3.9, road_m=8.0):
    """The contour at height z in the terrace frame K, split into the runs clear of rooms, lanes and the road."""
    return V.runs_clear(C, V.contour_k(C, K, z, x0, x1, y_lo, y_hi, step=step), road_m=road_m)


def bales(C, u, v, yaw, n, group='hay'):
    """Hay (reed) bales stacked side by side on the ground (never on each other: no physics stacks)."""
    ca, sa = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
    out = []
    for k in range(n):
        key = C.rng.choice(['MV_Hay_Bale_01', 'MV_Hay_Bale_02'])
        o = (k - (n - 1) / 2.0) * 0.95
        pu, pv = u + ca * o, v + sa * o
        out.append(prop(C, key, pu + C.rng.uniform(-0.08, 0.08), pv + C.rng.uniform(-0.08, 0.08),
                        yaw + 90 + C.rng.uniform(-6, 6), group))
    return out


def fire_pit(C, u, v, group='camp', seats=2):
    """A cold hearth: the stone ring, soot and ash on the ground, trunk seats round it, a pot left by it."""
    rigid(C, 'PH_fire_pit', u, v, C.rng.uniform(0, 360), group, 'hearth', 8, state='hearth', mat='stone')
    C.patch('soot', u, v, C.rng.uniform(0, 180), 3.0, 2.6, 0.95, order=4)
    C.patch('soot', u + 0.9, v + 0.4, C.rng.uniform(0, 180), 1.6, 1.0, 0.6, order=4)
    C.patch('path', u, v, 0, 6.0, 6.0, 0.8, order=2)
    for k in range(seats):
        a = C.rng.uniform(0, 2 * math.pi) if k == 0 else a + math.radians(C.rng.uniform(110, 160))
        su, sv = u + 2.2 * math.cos(a), v + 2.2 * math.sin(a)
        lie(C, C.rng.choice(['PH_trunk', 'MV_Log_07', 'MV_Log_08']), su, sv, math.degrees(a) + 90 + C.rng.uniform(-12, 12),
            group, sink=4, note='a trunk seat by the hearth')
    prop(C, 'PH_pot', u + 1.05, v - 0.7, C.rng.uniform(0, 360), group, mat='stone', note='the pot left by the fire')


# ---------------------------------------------------------------------------- L01 the Dock Farm

L01_LAYOUT = '''
                 field walls (dry-stone, gaps, dead hedges)  stubble rows
     old tree  [HALL + tall gable][room][store]   yard (manger, tub)   [BYRE, big arch]  hay shelter, bales
          well + trough     lane ------------------ riveted cradle (the dock) + cart
   paddock (timber fence)        | cart track
          field walls reaching down to the road verge
  ======================================== road (95 m) ========================================
'''


def l01(C, sp):
    """The first farm the player passes, left in order (decay 1): the house faces the road across its fields."""
    F, rng = C.F, C.rng
    O = (2.0, -30.0)
    ang = 4.0                                     # the house front faces the road (-v); the ground falls gently east
    K = terrace_frame(ang, O)
    C.cu, C.cv = K(0.0, 0.0)
    lane = C.path([K(-15.0, -5.4), K(0.0, -5.8), K(18.0, -5.2), K(23.0, -3.0)], 2.2, wander=0.3)
    # the farmhouse: a hall whose back wall is the tall gable of a two-storey house, a room, and a low store
    rooms = [rect(0, 0, 2, 2), rect(2, 0, 1, 2), rect(3, 0, 2, 1)]
    C.block('F', *K(-7.5, -3.0), ang, rooms, sp['decay'], tall_back=(0, 2), keep_back=0.6, collapse_corners=0,
            lintel_p=0.8, tall_p=0.2)
    C.block_lane['F'] = lane
    # the byre across the yard: one long room, the big arch its door, facing the yard
    C.block('B', *K(10.5, 7.0), ang + 3, [rect(0, 0, 3, 1)], sp['decay'], door_state='gate', collapse_corners=0,
            keep_back=0.5)
    C.door_spurs()
    # the yard between them: dry-stone walls, the gate onto the lane, a manger and a tub
    yard = [K(8.0, -1.2), K(8.2, 5.2), K(19.6, 5.6), K(20.4, -0.8), K(16.5, -1.6)]
    if all(C.seg_clear(a, b, margin=0.5, anchor=(yard[0], C.rows[0]['block'])) for a, b in zip(yard[:-1], yard[1:])):
        C.yard(yard, gap_every=0.08, contents=('MV_Manger', 'MV_wash_tub'), anchor=C.rows[0]['block'])
    C.path([K(14.0, -5.4), K(12.5, -0.4), K(13.0, 3.2)], 1.6, strength=0.9)          # lane -> yard gate -> byre
    # the dock the farm is named for: the riveted cradle frame on the lane, a cart drawn up beside it
    dk = clear_spot(C, [K(24.5, -8.5), K(22.0, -9.5), K(26.0, -6.0)], 1.9, margin=0.4)
    if dk:
        rigid(C, 'B01_dock01', dk[0], dk[1], ang + 90 + rng.uniform(-4, 4), 'dock', 'dock', 12, state='dock',
              mat='wood', note='the riveted cradle frame the farm is named for')
        ct = clear_spot(C, [(dk[0] + 3.4, dk[1] - 0.6), (dk[0] + 3.0, dk[1] + 1.8), (dk[0] - 0.5, dk[1] - 3.6)], 2.1,
                        margin=0.3)
        if ct:
            prop(C, 'AB_Cart_A_texturing', ct[0], ct[1], ang + 92 + rng.uniform(-6, 6), 'dock',
                 note='the cart drawn up to the cradle')
        C.patch('packed_earth', dk[0] + 1.5, dk[1], ang, 9.0, 6.0, 0.9, order=1)
        C.patch('soot', dk[0] + 0.3, dk[1] + 0.2, ang + 20, 2.6, 1.6, 0.55, order=4)      # grease under the cradle
    # the well in front of the house, the stone trough, a trodden ring
    wl = clear_spot(C, [K(-12.5, -10.5), K(-10.5, -11.0), K(-14.0, -9.0)], 1.6)
    if wl:
        rigid(C, 'MV_well', wl[0], wl[1], ang + rng.uniform(-10, 10), 'well', 'well', 10, state='well')
        C.patch('path', wl[0], wl[1], 0, 4.6, 4.6, 0.9, order=2)
        # the trough lies along the paddock fence (its 4.2 m long axis on the contour), its near end 0.5 m clear of
        # the well (integration fix: at 2.9 m its end reached under the well, ON_ACTOR)
        tr = clear_spot(C, [(wl[0] + 3.65, wl[1] - 0.3), (wl[0] + 3.4, wl[1] + 1.4)], 1.1, margin=0.3)
        if tr:
            rigid(C, 'B01_channel01', tr[0], tr[1], ang + 90, 'well', 'trough', 20, state='trough',
                  note='the stone trough by the well, dry')
        C.path([wl, nearest_on([lane], wl)], 1.3, strength=0.9)
        prop(C, 'MV_bucket_02', wl[0] - 1.3, wl[1] + 0.4, rng.uniform(0, 360), 'well', roll=80, note='tipped bucket')
    # the old tree by the door (the one the letters mention) and the jars under it
    tr_ = clear_spot(C, [K(-11.0, -0.5), K(-11.5, 3.0), K(-10.5, -7.5)], 2.2)
    if tr_:
        dead_tree(C, 'FAB_DeadTree_rlthg', tr_[0], tr_[1], 0.85, 'oldtree', 'the old tree by the house, dead')
    jr = clear_spot(C, [K(-8.2, -4.0), K(-8.6, -4.6)], 0.6, margin=0.2)
    if jr:
        prop(C, 'B01_tank01', jr[0], jr[1], rng.uniform(0, 360), 'house', mat='stone', note='wood-hooped clay jar')
    # the hay shelter and bales at the byre's east end
    hs = clear_spot(C, [K(23.0, 8.5), K(23.5, 11.0), K(7.0, 9.0)], 1.8)
    if hs:
        rigid(C, 'MV_Annex_Hay', hs[0], hs[1], ang + 180 + rng.uniform(-5, 5), 'hay', 'hayshelter', 8, state='shelter',
              mat='wood')
        hb = clear_spot(C, [(hs[0] + 0.5, hs[1] - 3.0), (hs[0] + 2.8, hs[1] - 1.5)], 1.6, margin=0.3)
        if hb:
            bales(C, hb[0], hb[1], ang + rng.uniform(-10, 10), 2)
    # the bread oven in the yard corner (Tripo, optional)
    ov = clear_spot(C, [K(-4.0, 9.5), K(-8.0, 9.0), K(2.0, 9.5)], 1.6)
    if ov:
        C.add('T2_bread_oven', ov[0], ov[1], ang + 180, 'yard', 'rigid', sink_cm=10, material_set='stone',
              block='oven', state='oven', vis_h=2.1, note='clay bread oven behind the house')
    # the paddock below the house: timber fences, a fallen panel, the gate onto the track
    pad = [K(-5.0, -12.5), K(-24.0, -13.5), K(-25.5, -29.0), K(-4.5, -30.5)]
    blk = fence_run(C, pad, gaps=(3, 9))
    C.patch('packed_earth', *K(-15.0, -21.5), ang, 18.0, 14.0, 0.55, order=0)
    for i, a in enumerate(pad[:-1]):
        pass
    # the cart track: from the lane down through the fields to the road verge
    trk = track_to_road(C, K(3.0, -5.8), 2.9, 0.9, bend=-4.0)
    # field walls between the farm and the road, following the ground, broken, dead hedges at their feet
    z0 = F.g(*K(0.0, -38.0))
    walls = []
    for k, (dz, xr) in enumerate(((0.0, (-36, 34)), (-1.2, (-30, 40)), (-2.4, (-20, 46)))):
        for run in contour_runs(C, K, z0 + dz, xr[0], xr[1], -70.0, -26.0):
            C.terrace_wall(run, gap_every=0.18, sink=30)
            hedge(C, run)
            walls.append(run)
    # the fields between them: stubble rows along the contour
    for (x0, x1, y0, y1) in ((-30, -8, -44, -34), (8, 30, -48, -36), (-20, 2, -56, -46)):
        stubble(C, [K(x0, y0), K(x1, y0), K(x1, y1), K(x0, y1)], ang, keep=0.35)
    # the field hut far out: one lone room with its corner down
    C.block('L', *K(-38.0, -30.0), ang + 9, [rect(0, 0, 1, 1)], 2, group='outskirts', collapse_corners=1)
    for (du, dv, name, k, fu, fv) in C.doors:
        if name == 'L':
            C.path([(du, dv), nearest_on([x['pts'] for x in C.lanes], (du, dv))], 1.0, strength=0.7)
    C.patch('packed_earth', *K(4.0, 1.5), ang, 40.0, 24.0, 0.5, order=0)
    C.meta.update(frame=dict(ang=ang, O=O))


# ---------------------------------------------------------------------------- L02 the Apricot Terraces

L02_LAYOUT = '''
  ============================= road (70 m) =============================
        path down  -> field house (roofless) + the drying deck on its piers, crates
      sluice -- dry feed channel along the top terrace ------------------------
    terrace walls stepping DOWN the slope (-u), dead apricot trees in rows on every terrace:
      standing dead trees, stumps, fallen trunks, roots; ramps at alternate ends
'''


def l02(C, sp):
    """A terraced apricot orchard, dead: the walls hold, the trees did not."""
    F, rng = C.F, C.rng
    O = (0.0, 6.0)
    ang = F.contour_deg(*O)
    K = terrace_frame(ang, O)                    # x along the contour, y uphill
    C.cu, C.cv = K(0.0, 0.0)
    z0 = F.g(*O)
    # the top: the path from the road, the field house and the drying deck, the channel
    top = F.contour_line
    levels = [z0 + 1.7 * k for k in (-3, -2, -1, 0, 1, 2)]
    # the ramp path first (the walls leave gaps for it): down the terraces at alternate ends
    ys = []
    for z in levels:
        pts = V.contour_k(C, K, z, -2.0, 2.0, -40.0, 40.0, step=2.0)
        ys.append(F.site(*F.world(*pts[0])) if pts else None)
    ramp = [K(18.0, 26.0), K(17.0, 16.0), K(-16.0, 13.0), K(-17.0, 4.0), K(15.0, 1.0), K(16.0, -8.0), K(-15.0, -10.5),
            K(-16.0, -19.0)]
    lanes = C.path(ramp, 1.5, wander=0.35, strength=0.85)
    track_to_road(C, ramp[0], 2.0, 0.85, bend=3.0)
    # the field house first (integration fix): the terrace walls then end at its walls instead of running through
    # them (the contour runs keep clear of rooms); it was laid after the walls and 5 courses CLASHed with it
    C.block('H', *K(-9.0, 20.5), ang + 4, [rect(0, 0, 2, 1), rect(2, 0, 1, 1)], sp['decay'], collapse_corners=1,
            lintel_p=0.7)
    C.block_lane['H'] = lanes
    C.door_spurs()
    # terrace walls on the contours, gaps where the ramp crosses, slumped stretches
    rows = []
    for k, z in enumerate(levels):
        reach = 26.0 + rng.uniform(-3.0, 4.0)
        runs = contour_runs(C, K, z, -reach, reach, -40.0, 40.0)
        for run in runs:
            C.terrace_wall(run, gap_every=0.1, sink=40)
        rows.append(runs)
    # orchard rows: between each pair of walls, trees at ~5.5 m along the terrace
    for k in range(len(levels) - 1):
        zmid = 0.5 * (levels[k] + levels[k + 1])
        pts = V.contour_k(C, K, zmid, -24.0, 24.0, -40.0, 40.0, step=5.5)
        for i, (u, v) in enumerate(pts):
            u += rng.uniform(-0.7, 0.7)
            if C.on_lane(u, v, 1.2) or not C.point_clear(u, v, margin=0.9, lane_margin=1.0):
                continue
            r = rng.random()
            if r < 0.3:
                dead_tree(C, 'FAB_DeadTree_qlEtl', u, v, rng.uniform(0.55, 0.72), 'tree%d_%d' % (k, i),
                          'dead apricot tree')
            elif r < 0.68:
                prop(C, rng.choice(STUMPS), u, v, rng.uniform(0, 360), 'orchard', sink_cm=6, note='apricot stump')
            elif r < 0.84:
                d = F.contour_deg(u, v) + rng.uniform(-25, 25)
                if C.point_clear(u + math.cos(math.radians(d)) * 1.6, v + math.sin(math.radians(d)) * 1.6, 0.6, 0.8):
                    lie(C, 'PH_trunk', u, v, d, 'orchard', sink=8, note='a fallen apricot tree along the terrace')
            else:
                lie(C, rng.choice(['PH_roots_a', 'PH_roots_b']), u, v, rng.uniform(0, 360), 'orchard', sink=4,
                    note='roots where a tree was pulled')
    # the field house and the drying deck at the top, near the path from the road
    zt = levels[-1]
    dk = clear_spot(C, [K(8.0, 24.0), K(6.0, 27.0), K(-18.0, 24.0)], 4.2, margin=0.4)
    if dk:
        rigid(C, 'B01_shelter01', dk[0], dk[1], ang + rng.uniform(-4, 4), 'deck', 'deck', 30, state='deck',
              note='the apricot drying deck on its stone piers')
        C.patch('packed_earth', dk[0], dk[1], ang, 10.0, 9.0, 0.85, order=1)
        for i, key in enumerate(('MV_box_01', 'MV_box_04', 'AB_Box_A', 'MV_box_02')):
            p = clear_spot(C, [(dk[0] - 4.6 + 0.9 * i, dk[1] - 4.3), (dk[0] + 4.7, dk[1] - 3.0 + 0.9 * i)], 0.55,
                           margin=0.15)
            if p:
                prop(C, key, p[0], p[1], ang + rng.uniform(-15, 15), 'crates', note='apricot crate')
        p = clear_spot(C, [(dk[0] - 4.5, dk[1] + 1.0), (dk[0] + 5.0, dk[1] + 2.0)], 1.8, margin=0.2)
        if p:
            lie(C, 'MV_Log_05', p[0], p[1], ang + 80, 'crates', sink=3, note='the fallen ladder (a pole stands in)')
    # the dry feed channel along the top terrace, from its sluice
    ch = V.contour_k(C, K, zt + 0.9, -24.0, 22.0, -40.0, 40.0, step=4.1)
    run = [p for p in ch if C.point_clear(p[0], p[1], margin=1.0, lane_margin=0.6)]
    if len(run) >= 3:
        C.nblock += 1
        blk = 'channel_%d' % C.nblock
        for a, b in zip(run[:-1], run[1:]):
            if math.hypot(b[0] - a[0], b[1] - a[1]) > 5.0:
                continue
            m = along(a, b, 0.5)
            C.add('B01_channel01', m[0], m[1], ang_of(a, b) - 90.0, 'channel', 'channel', ism=True, block=blk,
                  material_set='stone', settle_over=dict(mode='trace', max_tilt_deg=9, rand_tilt_deg=0, z_rule='mean',
                                                          sink_cm=38))
        C.path(run, 1.8, surface='gravel', strength=0.75, order=1, lane=False)
        s0 = run[0]
        rigid(C, 'B01_gate01', s0[0], s0[1], ang, 'channel', 'sluice', 30, state='sluice',
              note='the sluice that fed the orchard, shut')
    C.patch('packed_earth', *K(0.0, 5.0), ang, 56.0, 34.0, 0.35, order=0)
    C.meta.update(frame=dict(ang=ang, O=O))


# ---------------------------------------------------------------------------- the sites of this group

SITES = {
    'L01_DockFarm': dict(archetype='farm', recipe=l01, seed='L01v2', layout=L01_LAYOUT, burnt=0, mud=2, creep_edge=26,
                         style='BAZAAR STONE farmhouse + MedievalVillage timber (fences, hay, cart), the riveted cradle'),
    'L02_ApricotTerraces': dict(archetype='orchard', recipe=l02, seed='L02v2', layout=L02_LAYOUT, burnt=0, mud=1,
                                creep_edge=16, style='dry-stone contour terraces + dead fruit trees, a drying deck'),
}
BASE_ARCH = 'farm'          # the setdress_v2.ARCHETYPES entry whose defaults every recipe here starts from


def compose(W, sid, **overrides):
    """setdress_v2.compose for this group's recipes: BASE < the farm defaults < the V1 row < SITES[sid]."""
    row = V.site_row(sid)
    sp = dict(V.BASE)
    sp.update(V.ARCHETYPES[BASE_ARCH])
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
    C = V.Composer(s, F, zlib.crc32(str(sp.get('seed') or sid + 'v2').encode()))
    sp['recipe'](C, sp)
    s.spec = {k: v for k, v in sp.items() if not callable(v)}
    return C.finish(sp)


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
        so['views'] = V.v2_views(W, s, s.frame, so['placements']) + extra_views(W, s)
        so['v2'] = s.v2
        so['v2']['archetype'] = s.spec['archetype']
        so['counts']['decals'] = len(so['ground'])
        so['load_box_cm'] = [round(v) for v in so['load_box_cm']]
        v, w = V.offline_check(W, so)
        so['offline_check'] = dict(violations=[list(x) for x in v], waived=[list(x) for x in w],
                                   note='estimated offline (setdress_contact.offline_reports); check2 in the editor decides')
    return out_sites, totals, by_id


def extra_views(W, s):
    """Site-specific cameras beyond the V2 set (a spec's extra_views: name -> (road m, look target u, v))."""
    out = []
    for name, (road_m, (tu, tv)) in (s.spec.get('extra_views') or {}).items():
        p, _, _ = W.frame(road_m)
        x, y = s.frame.world(tu, tv)
        out.append(dict(name=name, cam_cm=[round(float(p[0]) * 100, 1), round(float(p[1]) * 100, 1),
                                           round((W.ground(float(p[0]), float(p[1])) + B.EYE_M) * 100, 1)],
                        look_cm=[round(x * 100, 1), round(y * 100, 1), round((W.ground(x, y) + 3.0) * 100, 1)]))
    return out


# ---------------------------------------------------------------------------- soundness (the archetype test's rules)

def poly_dist(p, pts):
    return min(seg_dist(p, a, b) for a, b in zip(pts[:-1], pts[1:]))


def placed_actors(so):
    P = [p for p in so['placements'] if not p.get('optional')]
    return sum(1 for p in P if not p['ism']) + len({(p['group'], p['asset']) for p in P if p['ism']})


def rooms_overlap(L_):
    """Cells of different blocks that overlap in plan (the shared test's rule)."""
    out = []
    rooms = L_['rooms']
    for i in range(len(rooms)):
        for j in range(i + 1, len(rooms)):
            if rooms[i]['block'] == rooms[j]['block']:
                continue
            for qa in rooms[i]['cells']:
                for qb in rooms[j]['cells']:
                    if B.sat_overlap(qa, qb) > 0.05:
                        out.append((rooms[i]['block'], rooms[j]['block']))
    return out


def soundness(so, s):
    """The rules test_archetype_composes_a_sound_site applies, for this group's sites. Returns a list of problems."""
    out = []
    L_ = so['v2']
    if so['offline_check']['violations']:
        out.append('offline violations: %s' % so['offline_check']['violations'][:4])
    for p in so['placements']:
        if p['road_clear_m'] < 5.0 or 'nudged' in p.get('note', ''):
            out.append('road core: %s %s %.2f %s' % (p['id'], p['key'], p['road_clear_m'], p.get('note', '')))
    if rooms_overlap(L_):
        out.append('rooms overlap: %s' % rooms_overlap(L_)[:3])
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

def plot(W, so, path, cam_az=None):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import setdress_v2_plot as P
    F = V.Frame(W, so['road_m'], so.get('lateral_m') or 0.0)
    win = P.site_window(so, F, margin=6.0)
    cu, cv = so['v2']['core']
    R = max(12.0, min(36.0, max(win[1] - win[0], win[3] - win[2]) / 2.6))
    fig, axs = plt.subplots(1, 2, figsize=(24, 11))
    c = so['counts']
    title = '%s (%s), top-down\n%d placements (%d actors, %d ISM), %d decals; offline check: %d violations' % (
        so['id'], so['archetype'], c['placements'], placed_actors(so), c['ism_instances'], c['decals'],
        len(so['offline_check']['violations']))
    sm = P.topdown(axs[0], so, F, title, window=win)
    fig.colorbar(sm, ax=axs[0], shrink=0.4, label='visible wall height (m)')
    # the axonometric looks from the road side: the road is at -v for a site right of it, at +v for one left of it
    if cam_az is None:
        cam_az = -28.0 if (so.get('lateral_m') or 0.0) >= 0 else 152.0
    P.axo(axs[1], so, F, W, '%s, axonometric from the road side' % so['id'], window=(cu - R, cu + R, cv - R, cv + R),
          cam=P.Axo(az=cam_az))
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
    ap.add_argument('--plot-dir', default=PLOTS, help='where the review plots go')
    args = ap.parse_args(argv)
    W = B.World()
    out_sites, t, by_id = build(W, args.sites)
    bad = 0
    for so in out_sites:
        c = so['counts']
        probs = soundness(so, by_id[so['id']])
        bad += len(probs)
        print('%-20s %-9s placements %4d actors %3d ism %4d decals %3d offline violations %d %s' % (
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
        doc = dict(generated_by='Tools/World/setdress_v2_groups/%s.py' % GROUP, group=GROUP,
                   method='docs/world/SETDRESS_V2.md', level='/Game/level/Saskarta_WP',
                   conventions=dict(xy='world cm; yaw = UE yaw deg', bounds='x_cm/y_cm is the mesh BOUNDS CENTRE',
                                    ground='decal patches: DecalActor pitch -90, yaw, size (depth/2, width/2, length/2)',
                                    contact='rigid | rest | lie | bear | carried | stack (SETDRESS_V2.md section 3)',
                                    optional='Tripo models still in production: placed only with --with-optional'),
                   skipped={}, rejected=t['rejected'], checks=t['checks'], sites=sites)
        with open(OUT_JSON, 'w', encoding='utf8') as fh:
            json.dump(doc, fh, indent=1, ensure_ascii=False)
        print('wrote', OUT_JSON)
    if not args.no_plot:
        for so in out_sites:
            print('plot', plot(W, so, os.path.join(args.plot_dir, so['id'] + '.png'), SITES[so['id']].get('cam_az')))
    print('rejected', t['rejected'][:10])
    return bad


if __name__ == '__main__':
    sys.exit(1 if main() else 0)
