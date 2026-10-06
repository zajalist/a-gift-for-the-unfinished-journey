"""Set dressing V2, group 'hero villages and settlements': S07 Waiting Water, S13 Numbered Stop, L14 Old Town.

    python Tools/World/setdress_v2_groups/hero_villages.py                 # JSON + one plot per site
    python Tools/World/setdress_v2_groups/hero_villages.py --sites L14_OldTown --no-plot

Method: docs/world/SETDRESS_V2.md. The composer primitives (setdress_v2.Composer: block, wall_piece, collapse,
path, patch, door_spurs, road_link, yard, finish) are used as they are. setdress_v2.py and setdress_contact.py are
NOT changed; the two hand recipes below (s13, l14) are this group's, run through this module's own compose() and
build(), which do the same steps as setdress_v2.compose/build (so S07 comes out exactly as the composer makes it).

Output:
  Tools/World/setdress_v2_groups/hero_villages.json   the placement input (setdress_v2_sites.json schema)
  docs/world/setdress_v2/<site>.png                   a top-down + axonometric plot per site

S07_WaitingWater: the composer changed after the prototype capture (5d05c65f: V2.0 in the level; the working
composer makes V2.1), so S07 is re-run here through the composer's own S07 recipe, unchanged.
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
from setdress_v2 import PIECE_M, rect, seg_dist, in_quad  # noqa: E402

GROUP = 'hero_villages'
OUT_JSON = os.path.join(HERE, GROUP + '.json')
PLOTS = os.path.join(ROOT, 'docs', 'world', 'setdress_v2')
CAT = V.CAT
STONES, COBBLES, BRICKS, SHRUBS, TUFTS, POTS = V.STONES, V.COBBLES, V.BRICKS, V.SHRUBS, V.TUFTS, V.POTS


# ---------------------------------------------------------------------------- small shared grammar

def rigid(C, key, u, v, yaw, group, block, sink, scale=1.0, state='stone', mat='stone', **kw):
    """A plumb piece (z so no footprint sample floats; the uphill side is buried), with its visible height."""
    H = CAT[key]['size_cm'][2] / 100.0 * (max(scale) if isinstance(scale, (tuple, list)) else scale)
    return C.add(key, u, v, yaw, group, 'rigid', scale=scale, block=block, sink_cm=round(sink, 1), material_set=mat,
                 state=state, vis_h=round(H - sink / 100.0, 2), **kw)


def mass(C, key, u, v, yaw, group, block, sink, scale=1.0, state='house', **kw):
    """A large whole mesh (a village block, a tower house, a hall ruin) standing plumb and sunk into the slope.
    Its footprint joins the plan as an inert pseudo-room (its real rectangle, not the composer's circle), so rows,
    yards and lanes keep off its walls and fill up to them; the finishing passes skip it (no floor, no creep)."""
    it = rigid(C, key, u, v, yaw, group, block, sink, scale=scale, state=state, **kw)
    C.solids.pop()                                   # the circle add() recorded
    sz = CAT[key]['size_cm']
    sx, sy = sz[0] / 100.0 * scale, sz[1] / 100.0 * scale
    q = B.rect_corners(u, v, yaw, sx, sy)
    C.rooms.append(dict(block=block, name=block, cells=[q], centres=[], corners=[], centre=(u, v), w=sx, d=sy,
                        n_cells=0, rect=False, ang=yaw, group='landmark', court=True))
    C.meta.setdefault('masses', []).append(dict(key=key, quad=[tuple(p) for p in q], block=block))
    return it


def keep_out(C, quad):
    """Loose scatter (rubble, plants, fallen beams, heaps) is later cleared from inside this footprint."""
    C.meta.setdefault('keep_out', []).append([tuple(p) for p in quad])


def rect_clear(C, u, v, yaw, sx, sy, margin=0.3, lane_margin=0.3, door_r=1.0):
    """The whole footprint (corners, edge midpoints, centre) is clear of rooms, lanes, solids and the road core."""
    q = B.rect_corners(u, v, yaw, sx, sy)
    pts = q + [((q[i][0] + q[(i + 1) % 4][0]) / 2, (q[i][1] + q[(i + 1) % 4][1]) / 2) for i in range(4)] + [(u, v)]
    return all(C.point_clear(a, b, margin, lane_margin, door_r=door_r) for a, b in pts)


def robbed(C, a, b, blk):
    """A wall piece robbed for its stone: no standing piece, only the footing course and a low spill downhill."""
    u, v = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
    ang = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
    C.walls.append((a[0], a[1], b[0], b[1], 'gap', blk))
    du, dv = C.F.downhill(u, v)
    C.fans.append((u, v, du, dv, 0.35))
    for k in range(3):
        t = (k + 0.5) / 3 + C.rng.uniform(-0.1, 0.1)
        C.add(C.rng.choice(STONES + COBBLES), a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, C.rng.uniform(0, 360),
              'rubble_ism', scale=(0.8, 1.3), ism=True, settle_over=V.RUBBLE_SETTLE, block='base')
    C.scatter_fan(u, v, du, dv, ang, 5, 0.8, 35.0, 1.2, max_d=3.0)


def curtain(C, pts, states, blk, group='circuit', skip_quads=()):
    """A wall along a polyline (a contour, a bench edge), one 3 m piece per chord. states: list per piece of a
    decay state ('tall' = the Fort wall, 'low', 'damaged', 'gap' = a breach with its rubble heap, 'robbed').
    skip_quads: footprints (a quarter block built over the wall line) whose own wall IS the circuit there: a
    piece that would stand inside one, or within 0.5 m of it, is left out (no piece, no rubble)."""
    pts = V.resample(pts, PIECE_M)
    out = []
    for i, (a, b) in enumerate(zip(pts[:-1], pts[1:])):
        st = states[i] if i < len(states) else states[-1]
        if skip_quads and any(V.quad_dist((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t), q) < 0.5
                              for q in skip_quads for t in (0.0, 0.25, 0.5, 0.75, 1.0)):
            out.append((a, b, 'skip'))
            continue
        u, v = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        n = (-(b[1] - a[1]), b[0] - a[0])
        L = math.hypot(*n) or 1.0
        n = (n[0] / L, n[1] / L)
        if n[0] * (u - C.cu) + n[1] * (v - C.cv) < 0:          # the outward normal: away from the town
            n = (-n[0], -n[1])
        if st == 'robbed':
            robbed(C, a, b, blk)
        else:
            C.wall_piece(a, b, st, blk, group, n)
        out.append((a, b, st))
    return out


def run_states(rng, n, p_tall, breaches, rob=False):
    """Decay along a curtain: clustered breaches (2-3 pieces), broken ends either side, the rest standing."""
    st = ['tall' if rng.random() < p_tall else rng.choice(['damaged', 'low']) for _ in range(n)]
    for _ in range(breaches):
        if n < 6:
            break
        k = rng.randrange(1, n - 3)
        w = rng.choice((2, 2, 3))
        for j in range(k, min(n - 1, k + w)):
            st[j] = 'robbed' if rob else 'gap'
        if k - 1 >= 0 and st[k - 1] == 'tall':
            st[k - 1] = 'low'
        if k + w < n and st[k + w] == 'tall':
            st[k + w] = 'low'
    return st


def ism_terrace(C, pts, name='field', sink=35, gap_p=0.14):
    """A dry-stone field terrace along a contour as ONE ISM group (a far landmark's fields: dozens of courses
    that only read as lines from 300 m; rigid-ISM, trace-settled like S07's flags). Gaps come in slumped clusters."""
    key = V.DRYSTONE
    L = V.piece_dims(key)[0]
    in_gap = False
    for (u0, v0), (u1, v1) in zip(pts[:-1], pts[1:]):
        seg = math.hypot(u1 - u0, v1 - v0)
        k = max(1, int(round(seg / (L * 0.96))))
        ang = math.degrees(math.atan2(v1 - v0, u1 - u0))
        for i in range(k):
            t = (i + 0.5 + C.rng.uniform(-0.08, 0.08)) / k
            u, v = u0 + (u1 - u0) * t, v0 + (v1 - v0) * t
            in_gap = C.rng.random() < (0.55 if in_gap else gap_p)
            if in_gap:
                du, dv = C.F.downhill(u, v)
                C.fans.append((u, v, du, dv, 0.3))
                C.scatter_fan(u, v, du, dv, ang, 4, 0.7, 35.0, 1.2, max_d=2.5)
                continue
            C.add(key, u, v, ang + C.rng.uniform(-5, 5), name + '_ism', 'rigid', ism=True, block=name, sink_cm=sink,
                  material_set='stone', state='terrace', vis_h=round(V.piece_dims(key)[2] - sink / 100.0, 2))


def shoreline(F, cu, cv, z, bearings, r0=2.0, r1=40.0, step=0.5):
    """Where the ground first rises to height z walking out from (cu, cv) along each bearing (deg)."""
    out = []
    for b in bearings:
        c, s = math.cos(math.radians(b)), math.sin(math.radians(b))
        r = r0
        while r < r1:
            if F.g(cu + c * r, cv + s * r) >= z:
                out.append((cu + c * r, cv + s * r, b))
                break
            r += step
    return out


def clump(C, u, v, r, n, shrub_p=0.25):
    """Dry tufts and some dead shrubs in a loose clump (the old waterline, a wall foot)."""
    for _ in range(n):
        a = C.rng.uniform(0, 2 * math.pi)
        d = r * math.sqrt(C.rng.random())
        pu, pv = u + d * math.cos(a), v + d * math.sin(a)
        if C.on_lane(pu, pv, 0.4) or C.near_door(pu, pv, 1.0):
            continue
        if C.rng.random() < shrub_p:
            C.add(C.rng.choice(SHRUBS), pu, pv, C.rng.uniform(0, 360), 'creep', scale=(0.9, 1.5), ism=True, block='creep')
        else:
            C.add(C.rng.choice(TUFTS), pu, pv, C.rng.uniform(0, 360), 'creep_grass', scale=(0.8, 1.3), ism=True,
                  block='creep')


# ---------------------------------------------------------------------------- S13 the Numbered Stop

S13_LAYOUT = '''
  ============================ road (road 2,500-2,560 m; the carrier drives +u) ==========================
      verge apron   the worn path in            notice board   carts parked nose up-road (one lost its wheel)
  [west yard: manger]  +--tall outer wall--[ PORTAL: Broken_Arch_Wall ]--tall outer wall--+ corner tower (house03)
                      |  rooms face the court   passage + inner double arch   rooms   |  path down to the pools
                      |  stall        court: packed earth, worn cross      stall     |       crane + stair
                      |       well + trough        (the axis runs gate -> arcade)     |  quay revetment (Fort walls)
                      |  gallery walk  [ arcade: Side_Arch x5, one bay fallen ]      |  west pool | bund + sluice | east pool
                      +--back range: store rooms (clay jars)--------------------------+   (dry mud, dead reeds,
                                [ back hall: ruin01, the winter hall ]                    water gauge board)
                  (the dry wash runs behind, into the hollow)                  keeper's hut on the far rim
'''


def s13(C, sp):
    """Tfibaz Taflalut, the Numbered Stop (the Heron Pools caravanserai), left of the road.

    Anatolian caravanserai grammar: one rectangular court on the flat bench, a ring of rooms sharing the high
    blank outer wall, every room opening onto the court; a monumental portal (AB_Broken_Arch_Wall) on the side
    facing the road with an inner double arch where the passage meets the court; an arcade (riwaq) across the
    back of the court with a gallery walk behind it; the covered winter hall (ruin01) behind the back range; a
    corner tower bonded into a front corner. The well and its trough sit off the crossing of the worn paths.
    Left in order: carts parked in a row along the facade, noses up-road toward the platform, a departures board.

    The Heron Pools are the real hollow east of the bench (Gaea: a flat pan 4.8 m below it, the dry wash
    entering at its south-west): a stone bund with a sluice gate splits it into two pools; a quay wall of Fort
    pieces revets the west bank under the caravanserai, with a stair of cut blocks down to the pool and a
    hand-cranked hoist at its head; dry mud floors, dead reeds on the old waterline, a water-gauge board standing
    at 0 in the east pool (seen from the road through the pan's open north-east mouth), the pool keeper's
    one-room hut on the far rim (seen across the pan from the approach)."""
    F, rng = C.F, C.rng
    cw, cd = sp['court']
    assert (cw, cd) == (6, 5), 'the room plan below is authored for a 6 x 5 court'
    ang = sp['ang']
    ca, sa = math.cos(math.radians(ang)), math.sin(math.radians(ang))
    Uc, Vc = sp['centre']
    ox, oy = cw / 2.0, cd / 2.0                          # the outer box x -1..cw+1, y -1..cd+1 (cells)
    u0 = Uc - (ca * ox - sa * oy) * PIECE_M
    v0 = Vc - (sa * ox + ca * oy) * PIECE_M

    def P(x, y):
        return (u0 + (ca * x - sa * y) * PIECE_M, v0 + (sa * x + ca * y) * PIECE_M)

    def D(dx, dy):
        n = math.hypot(dx, dy) or 1.0
        return ((ca * dx - sa * dy) / n, (sa * dx + ca * dy) / n)
    C.cu, C.cv = P(cw / 2.0, cd / 2.0)
    g0, g1 = cw // 2 - 1, cw // 2                        # the gate passage cells of the front range (y = cd)
    # -- the lanes first, so collapse heaps and fans keep off them
    apron = P(cw / 2.0, cd + 1 + 1.3)
    axis = C.path([apron, P(cw / 2.0, cd + 0.5), P(cw / 2.0, 2.6), P(cw / 2.0 + 0.05, 0.97), P(cw / 2.0, 0.45)], 2.4,
                  wander=0.15)
    gallery = C.path([P(0.35, 0.45), P(cw / 2.0, 0.45), P(cw - 0.35, 0.47)], 1.5, wander=0.12, strength=0.9)
    cross = C.path([P(0.3, 2.6), P(cw / 2.0, 2.6), P(cw - 0.3, 2.62)], 1.8, wander=0.2)
    # the path to the pools: along the carts' outer side, round the north-east corner, down the east wall
    pools_path = C.path([apron, P(cw / 2.0 + 1.6, cd + 1 + 1.75), P(cw + 1.5, cd + 1 + 1.5), P(cw + 1.95, cd - 1.0),
                         P(cw + 2.0, 1.2)], 1.6, wander=0.3, strength=0.85)
    C.patch('packed_earth', apron[0], apron[1], ang, 12.0, 6.5, 0.95, order=1)      # the trodden gate apron
    # -- the ring of rooms: the back range (store rooms), the side ranges, the front range either side of the gate.
    #    Corner cells join a neighbour room (an L), so every room but the stores has a door on the court.
    rooms = [
        [(-1, -1), (0, -1)], [(1, -1), (2, -1)], [(3, -1)], [(4, -1), (5, -1)], [(6, -1), (6, 0)],
        [(-1, 0), (-1, 1)], [(-1, 2)], [(-1, 3), (-1, 4)],
        [(-1, 5), (0, 5)], [(1, 5)], [(4, 5)], [(5, 5), (6, 5)],
        [(6, 1), (6, 2)], [(6, 3), (6, 4)],
    ]
    court = {(i, j) for i in range(cw) for j in range(cd)}
    C.block('K', u0, v0, ang, rooms, sp['decay'], court=court, keep_back=0.5, tall_p=0.8, collapse_corners=2,
            lintel_p=0.5)
    blk = C.last_block
    # a fallen corner at the portal would bury the gate: the compose loop retries the seed
    for (fu_, fv_, _, _) in C.corner_falls:
        if min(math.hypot(fu_ - p[0], fv_ - p[1]) for p in (P(g0, cd + 1), P(g1 + 1, cd + 1), P(g0, cd), P(g1 + 1, cd))) < 1.0:
            C.meta['reject'] = 'a corner fell at the gate passage'
    # -- the portal, projecting a little from the facade, and the double arch on the court side of the passage
    mid, out = P(cw / 2.0, cd + 1), D(0, 1)
    rigid(C, 'AB_Broken_Arch_Wall', mid[0] + out[0] * 0.25, mid[1] + out[1] * 0.25, ang, 'gate', blk, 25, state='gate',
          landmark=True, note='the portal: the inn gate facing the road; the V5 plate slot is on its road face at ~4.2 m')
    C.walls.append(P(g0, cd + 1) + P(g1 + 1, cd + 1) + ('gate', blk))
    C.doors.append((mid[0], mid[1], 'K', -1, out[0], out[1]))
    for x in (g0 + 0.5, g1 + 0.5):
        a = P(x, cd)
        rigid(C, 'AB_Side_Arch', a[0], a[1], ang, 'gate', blk, 20, state='arcade', note='inner arch of the gate passage')
        C.walls.append(P(x - 0.5, cd) + P(x + 0.5, cd) + ('gate', blk))
    C.meta['story_slots'] = [dict(slot='V5_number_plate', owner='story set V5 (storyline.md)', on='the portal road face',
                                  at_uv=[round(mid[0] + out[0] * 0.75, 2), round(mid[1] + out[1] * 0.75, 2)], height_m=4.2,
                                  note='B08: the painted 6-8 board over the carved name; not placed here (story-owned)')]
    # -- the riwaq: five arches across the back of the court, one bay fallen, the end bays open
    fallen = rng.choice([1, 2, 4, 5])
    for x in range(1, cw):
        p = P(x, 0.97)
        if x == fallen:
            C.walls.append(P(x - 0.5, 0.97) + P(x + 0.5, 0.97) + ('gap', blk))
            C.collapse(p[0], p[1], D(0, 1), 1.0, ang)
            continue
        rigid(C, 'AB_Side_Arch', p[0], p[1], ang, 'arcade', blk, 20, state='arcade', note='the court arcade (riwaq)')
        C.walls.append(P(x - 0.5, 0.97) + P(x + 0.5, 0.97) + ('gate', blk))
    C.meta['arcade_fallen_bay'] = fallen
    # -- the winter hall behind the back range and the corner tower bonded into a standing front corner
    hall = P(cw / 2.0, -1)
    hd = CAT['B01_ruin01']['size_cm'][1] / 200.0 + 0.9
    hu, hv = hall[0] - D(0, 1)[0] * hd, hall[1] - D(0, 1)[1] * hd
    mass(C, 'B01_ruin01', hu, hv, ang + 180 + rng.uniform(-3, 3), 'backhall', 'backhall', 30, landmark=True,
         note='the winter hall behind the back range (the caravanserai silhouette from the road)')
    falls = [(f[0], f[1]) for f in C.corner_falls]
    for (cx_, cy_, dx, dy) in ((-1, cd + 1, -1, 1), (cw + 1, cd + 1, 1, 1), (-1, -1, -1, -1), (cw + 1, -1, 1, -1)):
        corner = P(cx_, cy_)
        if falls and min(math.hypot(corner[0] - f[0], corner[1] - f[1]) for f in falls) < 3.0:
            continue
        sz = CAT['B01_house03']['size_cm']
        off = 0.5 * math.hypot(sz[0], sz[1]) / 100.0 - 0.9
        d_ = D(dx, dy)
        mass(C, 'B01_house03', corner[0] + d_[0] * off, corner[1] + d_[1] * off, ang + 90 * rng.randrange(4), 'tower', blk,
             30, landmark=True, note='the corner tower, bonded into the outer wall')
        C.meta['tower_corner'] = (cx_, cy_)
        break
    C.door_spurs(width=1.2)
    # -- the court: packed earth, the well and its trough off the crossing, two stall awnings, the clay jars
    cc = P(cw / 2.0, cd / 2.0)
    C.patch('packed_earth', cc[0], cc[1], ang, cw * PIECE_M + 1.0, cd * PIECE_M + 1.0, 0.95, order=0)
    for (gx, gy) in ((cw / 2.0, cd + 0.5),):
        g = P(gx, gy)
        C.patch('path', g[0], g[1], ang + 90, 3.4, 5.2, 0.9, order=3)                 # the gate passage floor
    spot = C.find_spot([P(4.3, 3.6), P(1.7, 3.6), P(4.4, 1.9), P(1.6, 1.9)], 1.7, margin=0.4)
    if spot:
        rigid(C, 'MV_well', spot[0], spot[1], ang + rng.uniform(-10, 10), 'well', 'well', 10, state='well')
        C.patch('path', spot[0], spot[1], 0, 4.2, 4.2, 0.9, order=2)
        for sgn in (1, -1):
            tu, tv = spot[0] + D(1, 0)[0] * 2.3 * sgn, spot[1] + D(1, 0)[1] * 2.3 * sgn
            if rect_clear(C, tu, tv, ang, 4.2, 1.19, margin=0.2, lane_margin=0.1):
                rigid(C, 'B01_channel01', tu, tv, ang - 90, 'well', 'trough', 12, state='trough',
                      note='the stone trough by the well, dry')
                break
    for i in range(sp.get('stalls', 2)):
        s_ = C.find_spot([P(1.0, 4.1), P(5.0, 4.1), P(1.0, 1.75), P(5.0, 1.75)], 2.1, margin=0.25)
        if s_:
            C.awning_unit('stall%d' % i, s_[0], s_[1], ang + 180 + rng.uniform(-5, 5),
                          ('MV_table_02', 'AB_WoodenTable_B')[i % 2], ang + rng.uniform(-6, 6))
            for k in range(2):
                pu, pv = s_[0] + D(0, 1)[0] * 1.9 + rng.uniform(-0.8, 0.8), s_[1] + D(0, 1)[1] * 1.9 + rng.uniform(-0.8, 0.8)
                if C.point_clear(pu, pv, 0.3, 0.3):
                    C.add(rng.choice(POTS), pu, pv, rng.uniform(0, 360), 'stalls', 'rest', scale=(0.9, 1.2),
                          roll=(90 if k == 1 else 0))
    # the store room of the back range: clay jars against its back wall, one tipped
    for k, (x, y, roll) in enumerate(((3.22, -0.76, 0), (3.56, -0.74, 0), (3.72, -0.42, 90))):
        p = P(x, y)
        C.add('B01_tank01', p[0], p[1], rng.uniform(0, 360), 'store', 'rest', roll=roll, block='store_props',
              note='wood-hooped clay storage jar' + (', tipped' if roll else ''))
        keep_out(C, B.rect_corners(p[0], p[1], 0, 1.1, 1.1))
    p = P(1.5, -0.62)
    # The imported asset is a 2.26 m cluster; these are waist-high storage jars.
    jar_scale = 90.0 / V.CAT['T2_jars']['size_cm'][2]
    C.add('T2_jars', p[0], p[1], ang, 'store', 'rest', scale=jar_scale,
          block='store_props', note='S13 clay jar cluster, 0.9 m tall at measured import size')
    keep_out(C, B.rect_corners(p[0], p[1], ang, 2.4, 1.6))
    # -- outside the facade: the departures board by the portal, the carts parked nose up-road
    b = P(cw / 2.0 + 1.5, cd + 1 + 0.4)
    rigid(C, 'B01_sign03', b[0], b[1], ang, 'gate', 'board', 22, state='board', mat='wood',
          note='departures notice board (painted timber, the numbers only)')
    carts = (('AB_Cart_A_texturing', 4.75), ('MV_cart_01', 6.25), ('AB_Cart_A_texturing', 7.75))
    for k, (key, x) in enumerate(carts):
        p = P(x, cd + 1 + 0.72)
        sz = CAT[key]['size_cm']
        yaw = ang - 90 + rng.uniform(-4, 4)                  # the long axis (Y) up-road: noses toward the platform
        if not rect_clear(C, p[0], p[1], yaw, sz[0] / 100.0, sz[1] / 100.0, margin=0.3, lane_margin=0.2):
            continue
        C.add(key, p[0], p[1], yaw, 'carts', 'rest', block='cart%d' % k, material_set='wood',
              note='parked in a row along the facade, nose up-road to the platform' +
              ('; it lost a wheel' if key == 'MV_cart_01' else ''))
        keep_out(C, B.rect_corners(p[0], p[1], yaw, sz[0] / 100.0 + 0.2, sz[1] / 100.0 + 0.2))
        if key == 'MV_cart_01':
            w = P(x + 0.25, cd + 1 + 1.35)
            C.add('AB_Cart_Wheel', w[0], w[1], rng.uniform(0, 360), 'carts', 'lie', sink_cm=2, material_set='wood',
                  note='the lost wheel, lying')
        if k == 0:
            for j in range(2):
                q = P(x - 0.2 + 0.25 * j, cd + 1 + 0.12)
                C.add('MV_jute_bag_0%d' % (1 + 2 * j), q[0], q[1], rng.uniform(0, 360), 'carts', 'rest',
                      note='sacks set down by the cart')
    # -- the west yard for the pack animals, against the west wall
    y0 = [P(-1.25, 0.55), P(-3.6, 0.15), P(-3.95, 3.8), P(-1.3, 4.35)]
    if all(C.seg_clear(a, b_, margin=0.6, anchor=(y0[0], blk)) for a, b_ in zip(y0[:-1], y0[1:])):
        C.yard(y0, contents=('MV_Manger', 'MV_wash_tub'), anchor=blk)
    heron_pools(C, sp)
    C.road_link(3.0, max_len=45.0)
    # a lone room by the road west (the old toll room) and a wall stub on the wash rim
    lr = sp.get('toll_room', (-44.0, 25.0))
    a_ = F.contour_deg(*lr) + 8.0
    if C.fits(C.quads(lr[0], lr[1], a_, rect(0, 0, 1, 1)), 1.2):
        C.block('L', lr[0], lr[1], a_, [rect(0, 0, 1, 1)], min(3, sp['decay'] + 1), group='outskirts', collapse_corners=1)
    fr = sp.get('rim_fragment', (-31.0, -16.0))
    a_ = F.contour_deg(*fr) + 12.0
    q = (fr[0] + math.cos(math.radians(a_)) * 2 * PIECE_M, fr[1] + math.sin(math.radians(a_)) * 2 * PIECE_M)
    if C.seg_clear(fr, q, margin=1.0):
        C.nblock += 1
        C.wall_line(fr, q, ['damaged', 'low'], 'frag_%d' % C.nblock, 'outskirts', F.downhill(*fr))
    for (du, dv, name, k, fu, fv) in C.doors:                  # outlying doors: a faint footpath
        if name != 'L':
            continue
        best = min(((math.hypot(q_[0] - du, q_[1] - dv), q_) for ln in C.lanes for q_ in ln['pts']))
        C.path([(du, dv), best[1]], 1.0, strength=0.75)
    C.patch('packed_earth', cc[0], cc[1] + 2.0, ang, 44.0, 36.0, 0.6, order=0)     # the bench under the inn, trodden
    C.meta.update(frame=dict(ang=ang, O=(u0, v0)), court=[P(0, 0), P(cw, 0), P(cw, cd), P(0, cd)])


def heron_pools(C, sp):
    """The Heron Pools in the hollow east of the caravanserai (see s13)."""
    F, rng = C.F, C.rng
    win = sp['pan_window']                                  # u0, u1, v0, v1 of the pan floor search
    zf, pu, pv = min((F.g(u, v), u, v) for u in np.arange(win[0], win[1], 1.0) for v in np.arange(win[2], win[3], 1.0))
    pc = sp['pan_centre']
    C.meta['pools'] = dict(floor_z=round(zf, 2), deepest=(pu, pv))
    # -- the bund with its sluice: across the pan, bank to bank
    bu = sp['bund_u']
    nb = [p for p in shoreline(F, bu, pc[1], zf + 1.4, (88.0,), r0=0.5)]
    sb = [p for p in shoreline(F, bu, pc[1], zf + 1.4, (-92.0,), r0=0.5)]
    a, b = (nb[0][0], nb[0][1]), (sb[0][0], sb[0][1])
    L = math.hypot(b[0] - a[0], b[1] - a[1])
    tu, tv = (b[0] - a[0]) / L, (b[1] - a[1]) / L
    ang = math.degrees(math.atan2(tv, tu))
    m = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    C.nblock += 1
    bblk = 'bund_%d' % C.nblock
    Ld = V.piece_dims(V.DRYSTONE)[0]
    gate_w = CAT['B01_gate01']['size_cm'][0] / 100.0
    n_side = max(1, int(round((L / 2 - gate_w / 2) / Ld)))
    for s_ in (-1, 1):
        for k in range(n_side):
            d = s_ * (gate_w / 2 + 0.05 + Ld / 2 + k * Ld * 0.99)
            u, v = m[0] + tu * d, m[1] + tv * d
            rigid(C, V.DRYSTONE, u, v, ang + rng.uniform(-2, 2), 'pools', bblk, 30, state='drystone',
                  note='the bund between the two pools')
            C.walls.append((u - tu * Ld / 2, v - tv * Ld / 2, u + tu * Ld / 2, v + tv * Ld / 2, 'drystone', bblk))
    rigid(C, 'B01_gate01', m[0], m[1], ang, 'pools', bblk, 35, state='sluice', mat='wood',
          note='the sluice gate in the bund, wound open over nothing')
    C.walls.append((m[0] - tu * gate_w / 2, m[1] - tv * gate_w / 2, m[0] + tu * gate_w / 2, m[1] + tv * gate_w / 2,
                    'gate', bblk))
    C.meta['pools'].update(bund=[a, b], sluice=m)
    # -- the dry mud of both pools (the floor inside the old waterline)
    for (du, dv, L_, W_, yaw, s) in ((-6.5, 0.5, 13.0, 17.0, 80, 0.95), (6.0, 2.0, 12.0, 16.0, 100, 0.95),
                                     (-4.0, -4.5, 8.0, 6.0, 30, 0.9), (5.0, -5.0, 7.0, 6.0, -20, 0.9),
                                     (-9.0, 5.0, 6.0, 5.0, 60, 0.85)):
        C.patch('dry_mud', pc[0] + du, pc[1] + dv, yaw, L_, W_, s, order=0)
    # -- the quay: Fort pieces revet the west bank toe, a stair of cut blocks down through a gap
    toe = shoreline(F, pc[0], pc[1], zf + 0.45, np.arange(150.0, 222.0, 6.0))
    toe = [(u, v) for u, v, _ in sorted(toe, key=lambda p: p[2])]
    if len(toe) >= 3:
        pts = V.resample(toe, PIECE_M)
        C.nblock += 1
        qblk = 'quay_%d' % C.nblock
        k_stair = len(pts) // 2 - 1
        for i, (p, q) in enumerate(zip(pts[:-1], pts[1:])):
            n = (q[1] - p[1], -(q[0] - p[0]))
            nl = math.hypot(*n) or 1.0
            n = (n[0] / nl, n[1] / nl)
            if n[0] * (pc[0] - p[0]) + n[1] * (pc[1] - p[1]) < 0:
                n = (-n[0], -n[1])                        # the face toward the pool
            if i == k_stair:
                C.walls.append((p[0], p[1], q[0], q[1], 'opening', qblk))
                stair(C, p, q, n, qblk)
                continue
            C.wall_piece(p, q, 'tall' if rng.random() < 0.75 else 'damaged', qblk, 'pools', n)
        C.meta['pools']['quay'] = pts
    # -- the gauge board standing in the east pool (the pan's mouth shows it from the road) and one at the quay
    for (gu, gv, note) in ((m[0] + 4.5, m[1] + 3.0, 'water gauge board in the east pool, reading nothing'),):
        if C.point_clear(gu, gv, 0.5, 0.5):
            rigid(C, 'B01_scale01', gu, gv, ang + 90 + rng.uniform(-8, 8), 'pools', 'gauge', 35, state='gauge', mat='wood',
                  note=note)
    # -- dead reeds on the old waterline, round both pools (not on the quay, the bund or a path)
    for (u, v, bb) in shoreline(F, pc[0], pc[1], zf + 0.75, np.arange(0.0, 360.0, 9.0)):
        if seg_dist((u, v), a, b) < 2.0 or any(seg_dist((u, v), (w[0], w[1]), (w[2], w[3])) < 1.6 for w in C.walls):
            continue
        if rng.random() < 0.8:
            clump(C, u, v, 1.3, rng.randint(2, 5), shrub_p=0.2)
    C.add('MV_bucket_02', pc[0] - 5.0, pc[1] + 1.5, 0, 'pools', 'rest', roll=75, note='stranded where the water stood')
    # -- the pool keeper's one-room hut on the far (south) rim, its door toward the pools
    hk = sp['keeper_hut']
    a_ = F.contour_deg(*hk)
    if C.fits(C.quads(hk[0], hk[1], a_, rect(0, 0, 2, 1)), 1.2):
        C.block('P', hk[0], hk[1], a_, [rect(0, 0, 2, 1)], sp['decay'], group='outskirts', collapse_corners=1,
                lintel_p=0.8)
        # the keeper's own path (integration fix: no lane lay in front of its door, so it had no spur): out of
        # the door, then along the rim to the nearest lane
        for (du, dv, name, k, fu, fv) in list(C.doors):
            if name != 'P' or not C.lanes:
                continue
            o = (du + fu * 2.0, dv + fv * 2.0)
            q = min((q for ln in C.lanes for q in ln['pts']), key=lambda q: math.hypot(q[0] - o[0], q[1] - o[1]))
            C.path([(du, dv), o, q], 1.2, wander=0.2, strength=0.85)
    C.meta['pools']['keeper_hut'] = hk


def stair(C, p, q, n, blk):
    """Cut blocks stepping down the bank through a gap in the quay: each block plumb and sunk to its lowest
    sample, so the treads step down with the slope (the stair to the water)."""
    F = C.F
    mu, mv = (p[0] + q[0]) / 2, (p[1] + q[1]) / 2
    ang = math.degrees(math.atan2(q[1] - p[1], q[0] - p[0]))
    # walk up the bank (away from the pool) until the bench, laying a tread every 0.62 m
    tread = 0.62
    pts = []
    d = -1.2
    while d < 6.0:
        u, v = mu - n[0] * d, mv - n[1] * d
        pts.append((u, v, d))
        if d > 0.5 and F.g(u, v) - F.g(mu - n[0] * (d - tread), mv - n[1] * (d - tread)) < 0.08:
            break
        d += tread
    for (u, v, d) in pts:
        rigid(C, 'B01_brick01', u, v, ang, 'pools', blk, 8, state='step', note='stair to the pool, cut blocks')
    C.meta.setdefault('stair', []).append([(round(u, 2), round(v, 2)) for u, v, _ in pts])
    top = pts[-1]
    C.path([(top[0] - n[0] * 1.0, top[1] - n[1] * 1.0), (pts[0][0] + n[0] * 1.5, pts[0][1] + n[1] * 1.5)], 1.3,
           strength=0.8)
    # the hand-cranked hoist at the stair head, beside the path
    hu, hv = top[0] - n[0] * 1.6 + (q[0] - p[0]) / 3.0 * 0.95, top[1] - n[1] * 1.6 + (q[1] - p[1]) / 3.0 * 0.95
    if C.point_clear(hu, hv, 0.5, 0.4):
        rigid(C, 'B01_crane01', hu, hv, ang + 90, 'pools', 'hoist', 15, state='hoist', mat='wood',
              note='hand-cranked hoist at the head of the pool stair')


# ---------------------------------------------------------------------------- L14 the Old Town

L14_LAYOUT = '''
            (the road, 330 m up the slope: the track climbs out of the north gate toward it)
      field terraces (ISM courses along the contours above the town)
   NW  ~~robbed wall~~  fragment ~~~~   T3 tower house      [PORTAL + gate tower T1]  ~~ fragment ~~  NE
    |  [village01 A: the old quarter]   rows of shared-wall rooms (lanes along the terraces)   ruin01   |
    |        (upper rows)          main street bends down from the gate       [tall gable]          |  east wall
    |  rows ...  well plaza            rows ...           [village01 B, lower, turned]              |  (faces the
   SW ===== south curtain on the bench edge: Fort walls, breaches with rubble aprons, T4 mid tower ===== SE T2
            field terraces below the bench (ISM)                                                   (crest view)
'''


def l14(C, sp):
    """The Old Town on the Bench: a walled town ruin on the flat bench 330 m left of the road, a far landmark
    (read at 330-590 m from the road, 1.1 km from the crest). It must read as a silhouette: few, large pieces
    (two village01 blocks, four tower houses, the ruin01 hall, a tall gable) set in a continuous fabric of
    shared-wall rooms along the terraces, inside a Fort-wall circuit that follows the real bench edge.

    The town faces its road: the north wall (toward the road) was robbed for stone, only fragments stand, the
    portal and its gate tower remain and the worn track climbs out of it toward the road. The south curtain holds
    the bench edge (breaches spill rubble aprons down the slope) and the east wall faces the crest. Field
    terraces follow the contours above and below the town."""
    F, rng = C.F, C.rng
    ang = sp['ang']
    O = (0.0, 0.0)
    K = V.terrace_frame(ang, O)
    C.cu, C.cv = K(0.0, -4.0)

    def Kd(dx, dy):
        c, s = math.cos(math.radians(ang)), math.sin(math.radians(ang))
        n = math.hypot(dx, dy) or 1.0
        return ((c * dx - s * dy) / n, (s * dx + c * dy) / n)
    C.nblock += 1
    cblk = 'circuit_%d' % C.nblock
    # -- the circuit. South curtain on the bench edge (a computed contour), the east wall facing the crest.
    zs = F.g(*K(0.0, sp['curtain_y']))
    south = V.contour_k(C, K, zs, -47.0, 50.0, sp['curtain_y'] - 8.0, sp['curtain_y'] + 8.0, step=3.0)
    se, sw = south[-1], south[0]
    east = [se, K(53.0, -12.0), K(52.0, 10.0), K(48.0, 30.5)]
    ne = east[-1]
    gate = K(sp['gate_x'], 31.5)
    nw = K(-46.0, 28.5)
    north_e = [ne, K(36.0, 31.2), K(sp['gate_x'] + 3.6, 31.6)]
    north_w = [K(sp['gate_x'] - 3.6, 31.6), K(0.0, 31.0), K(-24.0, 30.2), nw]
    west = [nw, K(-49.5, 2.0), sw]
    # lanes first (heaps keep off them): the main street from the gate down to the south postern
    # (decal budget, integration fix: a far landmark's lanes wander in 6 m steps, not 3.5 m; 327 -> <= 300 decals)
    street = C.path(C.meander([K(sp['gate_x'], 36.0), gate, K(sp['gate_x'] - 7.0, 21.0), K(8.0, 8.0), K(5.0, -4.0),
                               K(2.5, -17.0), K(5.0, -29.0), K(6.0, sp['curtain_y'] + 0.5),
                               K(6.5, sp['curtain_y'] - 6.0)], 0.5, step=6.0), 3.0)
    # the track out of the gate, climbing toward the road (it fades out)
    tr = [K(sp['gate_x'], 36.0)]
    for k in range(9):
        p = tr[-1]
        tr.append((p[0] + sp['track_dir'][0] * 9.0, p[1] + sp['track_dir'][1] * 9.0))
    C.path(C.meander(tr, 1.2, step=6.0), 3.0, strength=0.8, lane=False)
    C.meta['track'] = tr
    # the well plaza: a widening of the main street, reserved before the rows fill in
    pa, pb = K(*sp['plaza'][0]), K(*sp['plaza'][1])
    C.path([pa, pb], 7.0, surface='packed_earth', strength=0.9, order=0)
    wl = K(*sp['plaza'][2])
    rigid(C, 'MV_well', wl[0], wl[1], ang + rng.uniform(-15, 15), 'well', 'well', 10, state='well')
    C.patch('path', wl[0], wl[1], 0, 4.4, 4.4, 0.9, order=2)
    rows = sp['rows']
    lanes = {}
    for t, (y, x0, x1) in enumerate(rows):
        pts = [K(x0, y - 1.8 + rng.uniform(-0.3, 0.3)), K((x0 + x1) / 2 + rng.uniform(-3, 3), y - 1.8 + rng.uniform(-0.4, 0.4)),
               K(x1, y - 1.8 + rng.uniform(-0.3, 0.3))]
        lanes[t] = C.path(C.meander(pts, 0.4, step=6.0), rng.uniform(1.8, 2.2))
    # the big masses' footprints, known before the circuit: where a quarter was built over the wall line, its
    # own outer wall is the circuit (integration fix: the lower quarter stood across the south curtain, 7 CLASHes)
    mq = []
    for (key, x, y, da, sc, sink, blkn, note) in sp['masses']:
        p = K(x, y)
        sz = CAT[key]['size_cm']
        mq.append(B.rect_corners(p[0], p[1], ang + da, sz[0] / 100.0 * sc, sz[1] / 100.0 * sc))
    n_s = len(V.resample(south, PIECE_M)) - 1
    curtain(C, south, run_states(rng, n_s, 0.75, 3), cblk, skip_quads=mq)
    n_e = len(V.resample(east, PIECE_M)) - 1
    curtain(C, east, run_states(rng, n_e, 0.8, 1), cblk, skip_quads=mq)
    # the north wall: robbed, only fragments stand (the side the town was quarried from for the road)
    for pts, keep in ((north_e, ((1, 4),)), (north_w, ((2, 4), (9, 11)))):
        n = len(V.resample(pts, PIECE_M)) - 1
        st = ['robbed'] * n
        for (i0, i1) in keep:
            for i in range(i0, min(n, i1)):
                st[i] = rng.choice(['tall', 'damaged', 'low'])
        curtain(C, pts, st, cblk)
    n_w = len(V.resample(west, PIECE_M)) - 1
    stw = ['robbed'] * n_w
    for i in range(3, 6):
        if i < n_w:
            stw[i] = rng.choice(['low', 'damaged'])
    curtain(C, west, stw, cblk)
    # the portal of the north gate and its tower (bonded into the circuit)
    ga = math.degrees(math.atan2(north_e[-1][1] - north_w[0][1], north_e[-1][0] - north_w[0][0])) + 180.0
    rigid(C, 'AB_Broken_Arch_Wall', gate[0], gate[1], ga, 'gate', cblk, 30, state='gate', landmark=True,
          note='the north gate of the Old Town, facing the road')
    C.walls.append(north_w[0] + north_e[-1] + ('gate', cblk))
    gd = Kd(0, 1)
    C.doors.append((gate[0], gate[1], 'G', -1, gd[0], gd[1]))
    t1 = K(sp['gate_x'] + 7.2, 30.2)
    mass(C, 'B01_house03', t1[0], t1[1], ang + 3, 'towers', cblk, 35, scale=1.15, landmark=True,
         note='T1 the gate tower')
    # tower houses on the curtain: the south-east bastion (the crest sees it) and a mid-curtain tower
    for (x, y, sc, name) in ((49.0, sp['curtain_y'] + 3.5, 1.1, 'T2 the south-east bastion'),
                             (-20.0, sp['curtain_y'] + 3.6, 1.0, 'T4 the mid-curtain tower')):
        p = K(x, y)
        mass(C, 'B01_house03', p[0], p[1], ang + 90 * rng.randrange(4) + rng.uniform(-4, 4), 'towers', cblk, 35,
             scale=sc, landmark=True, note=name)
    # -- the big masses: the old quarter (village01 A, upper west), the lower quarter (village01 B, turned),
    #    the hall ruin (east), the crowning tower house (T3, upper middle)
    for (key, x, y, da, sc, sink, blkn, note) in sp['masses']:
        p = K(x, y)
        mass(C, key, p[0], p[1], ang + da, 'masses', blkn, sink, scale=sc, landmark=True, note=note)
    # -- the fabric: rows of shared-wall rooms along the terraces, filling up to the masses and the circuit
    rsp = dict(cluster_rooms=(1, 2, 2, 3), max_depth=2, p_l=0.45, tall_p=0.55, lintel_p=0.35, corner_falls=(0, 1, 1),
               decay=sp['decay_core'])
    for t, (y, x0, x1) in enumerate(rows):
        half = (x1 - x0) / 2.0
        Kt = V.terrace_frame(ang, K((x0 + x1) / 2.0, 0.0))
        V.terrace_row(C, Kt, ang, t, y, half, rsp, lanes[t], tall_house=t in sp['tall_rows'])
    C.door_spurs()
    C.auto_yards(sp['yards'])
    # -- the edges: lone ruins outside the walls, field terraces above (toward the road) and below the bench
    for (x, y, da, cells) in sp['extramural']:
        p = K(x, y)
        if C.fits(C.quads(p[0], p[1], ang + da, cells), 1.5):
            C.block('L', p[0], p[1], ang + da, [cells], 3, group='outskirts', collapse_corners=1)
    for y in sp['fields_above']:
        z = F.g(*K(0.0, y))
        pts = V.contour_k(C, K, z, -40.0, 45.0, y - 8.0, y + 10.0, step=4.0)
        for run in V.runs_clear(C, pts):
            ism_terrace(C, run, name='field_up')
    for y in sp['fields_below']:
        z = F.g(*K(0.0, y))
        pts = V.contour_k(C, K, z, -45.0, 40.0, y - 8.0, y + 8.0, step=4.0)
        for run in V.runs_clear(C, pts):
            ism_terrace(C, run, name='field_down')
    for (du, dv, name, k, fu, fv) in C.doors:
        if name != 'L':
            continue
        best = min(((math.hypot(q[0] - du, q[1] - dv), q) for ln in C.lanes for q in ln['pts']))
        C.path([(du, dv), best[1]], 1.0, strength=0.75)
    # -- the town's own ground: one broad trodden patch (the footprint that reads from the road), rubble dust
    #    in the breaches' aprons comes from the collapse fans
    C.patch('packed_earth', *K(0.0, -3.0), ang, 104.0, 70.0, 0.6, order=0)
    C.patch('packed_earth', *K(sp['gate_x'], 36.0), ang, 12.0, 8.0, 0.9, order=1)
    C.meta.update(frame=dict(ang=ang, O=O), circuit=dict(south=south, east=east, north_e=north_e, north_w=north_w,
                                                          west=west, gate=gate))


# ---------------------------------------------------------------------------- per-site authoring

SITES = {
    'S07_WaitingWater': dict(composer=True),               # the composer's own S07 recipe (SETDRESS_V2.md, V2.1)
    'S13_NumberedStop': dict(
        archetype='caravanserai', recipe=s13, seed='S13v2', decay=2, burnt=1, mud=2, stalls=2, creep_edge=26,
        court=(6, 5), ang=-3.0, centre=(-16.0, 13.5), pan_window=(8.0, 28.0, -14.0, 4.0), pan_centre=(18.0, -5.0),
        bund_u=19.0, keeper_hut=(11.5, -27.5), toll_room=(-44.0, 25.0), rim_fragment=(-31.0, -16.0), radius_m=62,
        name='Tfibaz Taflalut, the Numbered Stop (the Heron Pools caravanserai)',
        story='B08 (radio 2,480 m) "The new signs gave the places numbers... We called it the Heron Pools." The painted '
              '6-8 board over the carved name is story set V5 (slot on the portal); CIN_P15_WORKS EXT frames the inn',
        style='BAZAAR STONE: walled court inn, high blank outer wall, portal, arcade, back hall, corner tower; the dry '
              'Heron Pools in the hollow with a bund, a sluice, a quay and a hoist',
        layout=S13_LAYOUT,
        notes='V2 (SETDRESS_V2.md), group hero_villages. The V5 number plate is story-owned: see v2.story_slots.'),
    'L14_OldTown': dict(     # seed L14v2a: the first of 8 seeds inside the budget (250 actors, 300 decals)
        archetype='village', recipe=l14, seed='L14v2a', decay=3, decay_core=2, burnt=1, mud=3, creep_edge=40, yards=2,
        ang=33.4, curtain_y=-37.0, gate_x=20.0, track_dir=(0.0, 1.0), radius_m=100,
        rows=[(-31.0, -44.0, 12.0), (-18.0, -44.0, 12.0), (-3.0, -12.0, 47.0), (9.0, -12.0, 30.0), (20.0, -44.0, 45.0)],
        tall_rows=(1, 3),
        masses=[('B01_village01', -29.0, 1.5, 4.0, 1.0, 60, 'quarterA', 'the old quarter (upper west): village01 A'),
                ('B01_village01', 28.0, -20.0, 176.0, 0.92, 60, 'quarterB', 'the lower quarter, turned: village01 B'),
                ('B01_ruin01', 38.0, 10.5, 8.0, 1.1, 40, 'hall', 'the hall ruin at the east end'),
                ('B01_house03', -3.0, 26.0, 12.0, 1.2, 35, 'towerT3', 'T3 the crowning tower house (upper middle)')],
        plaza=[(0.5, -9.5), (10.0, -9.5), (8.0, -10.5)],
        fields_above=(41.0, 50.0), fields_below=(-47.0, -56.0),
        extramural=[(33.0, 44.0, 14.0, rect(0, 0, 1, 1)), (-30.0, 40.0, -9.0, rect(0, 0, 2, 1))],
        name='The Old Town on the Bench',
        story="Seen from the valley road (G03 at 450 m frames it with the Promise Stones, 560 m) and back from the crest "
              "(1,980 m, 1.1 km): the valley's town",
        style='BAZAAR STONE: mud-brick quarters (village01), tower houses, a hall ruin, shared-wall rooms along the '
              'terraces, a Fort-wall circuit on the bench edge, the robbed north wall and its gate',
        layout=L14_LAYOUT,
        notes='V2 far landmark (SETDRESS_V2.md), group hero_villages: few large pieces for the silhouette, set in a '
              'composed fabric; field terraces are ISM (read only as lines at 300 m+).'),
}


# ---------------------------------------------------------------------------- compose / build (as setdress_v2)

def compose(W, sid, tries=12, **overrides):
    """Compose one site. S07 goes through the composer's own compose(); the others run this group's recipe with
    the same steps (V.BASE < the archetype's defaults < the V1 row < SITES[sid] < overrides). A recipe can reject
    its own result (C.meta['reject'], e.g. a corner fallen onto the gate); the seed then steps on."""
    if SITES[sid].get('composer'):
        s = V.compose(W, sid)
        s.v2.setdefault('seed', V.SITE_SPECS[sid].get('seed'))
        return s
    row = V.site_row(sid)
    ss = dict(SITES[sid])
    ss.update(overrides)
    arch = ss.get('archetype') or V.archetype_of(row)
    for k in range(tries):
        sp = dict(V.BASE)
        sp.update({a: b for a, b in V.ARCHETYPES.get(arch, {}).items() if a != 'recipe'})
        sp['decay'] = row.get('decay', sp['decay'])
        sp['side'] = row.get('side')
        sp.update(ss)
        sp['archetype'] = arch
        lat = row.get('lateral_m') or 0.0
        s = B.Site(sid, sp.get('name', row['name']), row['road_m'], lat, row['kind'], sp.get('role', row['role']),
                   sp.get('story', row.get('story') or ''), sp['decay'], sp.get('style', row.get('style') or ''),
                   sp.get('order', row.get('order', 2)), sp.get('radius_m', row.get('radius_m', 40)),
                   layout=sp.get('layout', row.get('layout') or ''), notes=sp.get('notes', row.get('notes') or ''),
                   story_owned=row.get('story_owned') or [])
        F = V.Frame(W, row['road_m'], lat)
        seed = str(sp.get('seed') or sid + 'v2') + ('' if k == 0 else '.%d' % k)
        C = V.Composer(s, F, zlib.crc32(seed.encode()))
        sp['recipe'](C, sp)
        if C.meta.get('reject'):
            continue
        s.spec = {a: b for a, b in sp.items() if not callable(b)}
        s.spec['seed'] = seed
        s = C.finish(sp)
        clear_keep_out(C)
        s.v2['seed'] = seed
        return s
    raise RuntimeError('%s: no acceptable composition in %d seeds (%s)' % (sid, tries, C.meta.get('reject')))


def clear_keep_out(C):
    """Drop the loose scatter (fans, base stones, creep, beams, heaps) the finishing passes laid inside a mass's
    footprint or a prop's keep-out (a tower bonded over a room corner, the jars, the parked carts)."""
    quads = [m['quad'] for m in C.meta.get('masses', [])] + C.meta.get('keep_out', [])
    if not quads:
        return
    keep = []
    for it in C.s.items:
        loose = it.get('block') in ('fan', 'base', 'creep', 'beam') or it.get('group') in ('rubble', 'beams')
        if loose and any(in_quad((it['u'], it['v']), q) for q in quads):
            continue
        keep.append(it)
    C.s.items[:] = keep
    C.beams[:] = [b for b in C.beams if not any(in_quad(((b[0] + b[2]) / 2, (b[1] + b[3]) / 2), q) for q in quads)]
    C.s.v2['beams'] = C.beams


def build(W, sids):
    S = [compose(W, sid) for sid in sids]
    out_sites, totals = B.build(W, S)
    by_id = {s.sid: s for s in S}
    for so in out_sites:
        s = by_id[so['id']]
        V.resolve_refs(so)
        V.correct_s07_wall_footing(so)
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


def rooms_overlap(L_):
    rooms = [r for r in L_['rooms'] if not r.get('court')]
    bad = []
    for i in range(len(rooms)):
        for j in range(i + 1, len(rooms)):
            if rooms[i]['block'] == rooms[j]['block']:
                continue
            if any(B.sat_overlap(a, b) > 0.3 for a in rooms[i]['cells'] for b in rooms[j]['cells']):
                bad.append((rooms[i]['block'], rooms[j]['block']))
    return bad


def soundness(so, s):
    """The rules test_archetype_composes_a_sound_site applies (and the budget), for this group's sites."""
    out = []
    L_ = so['v2']
    if so['offline_check']['violations']:
        out.append('offline violations: %s' % so['offline_check']['violations'][:6])
    for p in so['placements']:
        if p['road_clear_m'] < 5.0 or 'nudged' in p.get('note', ''):
            out.append('road core: %s %s %.2f %s' % (p['id'], p['key'], p['road_clear_m'], p.get('note', '')))
    if rooms_overlap(L_):
        out.append('rooms overlap: %s' % rooms_overlap(L_)[:4])
    lanes = [ln['pts'] for ln in L_['lanes']]
    F = s.frame
    if lanes:
        if min(F.road_dist(u, v) for pts in lanes for u, v in pts) > 9.0 and so['id'] != 'L14_OldTown':
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

def plot(W, so, path, axo_r=None):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import setdress_v2_plot as P
    F = V.Frame(W, so['road_m'], so.get('lateral_m') or 0.0)
    win = P.site_window(so, F, margin=6.0)
    cu, cv = so['v2']['core']
    R = axo_r or max(10.0, min(40.0, max(win[1] - win[0], win[3] - win[2]) / 2.6))
    fig, axs = plt.subplots(1, 2, figsize=(26, 12))
    c = so['counts']
    title = '%s (%s), top-down\n%d placements (%d actors, %d ISM), %d decals; offline check: %d violations' % (
        so['id'], so['archetype'], c['placements'], placed_actors(so), c['ism_instances'], c['decals'],
        len(so['offline_check']['violations']))
    sm = P.topdown(axs[0], so, F, title, window=win)
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
        print('%-18s %-12s placements %4d actors %3d ism %4d decals %3d offline violations %d %s' % (
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
        doc = dict(generated_by='Tools/World/setdress_v2_groups/hero_villages.py', group=GROUP,
                   method='docs/world/SETDRESS_V2.md', level='/Game/level/Saskarta_WP',
                   conventions=dict(xy='world cm; yaw = UE yaw deg', bounds='x_cm/y_cm is the mesh BOUNDS CENTRE',
                                    ground='decal patches: DecalActor pitch -90, yaw, size (depth/2, width/2, length/2)',
                                    contact='rigid | rest | lie | bear | carried | stack (SETDRESS_V2.md section 3)',
                                    optional='Tripo models still in production: placed only with --with-optional'),
                   notes=dict(S07_WaitingWater='re-run: the composer changed after the prototype capture (5d05c65f is '
                                               'V2.0 in the level); this is the composer\'s own S07 V2.1 recipe, unchanged'),
                   rejected=t['rejected'], checks=t['checks'], sites=sites)
        with open(OUT_JSON, 'w', encoding='utf8') as fh:
            json.dump(doc, fh, indent=1, ensure_ascii=False)
        print('wrote', OUT_JSON)
    if not args.no_plot:
        for so in out_sites:
            r = 44.0 if so['id'] == 'L14_OldTown' else None
            print('plot', plot(W, so, os.path.join(PLOTS, so['id'] + '.png'), axo_r=r))
    print('rejected', t['rejected'][:10])
    return bad


if __name__ == '__main__':
    sys.exit(1 if main() else 0)
