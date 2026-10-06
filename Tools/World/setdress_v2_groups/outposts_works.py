"""Set dressing V2, group 'outposts and works': S01 the Carrier Dock, S14 the Departure Platform,
S19 the Last Waystation, S15 the Works and S16 the Quarry (method: docs/world/SETDRESS_V2.md).

    python Tools/World/setdress_v2_groups/outposts_works.py                 # all five: JSON + plots
    python Tools/World/setdress_v2_groups/outposts_works.py --sites S16_Quarry --plot-dir <dir>   # iterate on one

Writes Tools/World/setdress_v2_groups/outposts_works.json (the setdress_v2_sites.json schema; a merge step
combines the group files) and one review plot per site, docs/world/setdress_v2/<site>.png.

The composer (Tools/World/setdress_v2.py) is used as it is: its grammar (blocks of rooms sharing party
walls, decay per piece, collapse fans downhill, lanes and door spurs, ground decals, the rubble band and the
creep) and its offline contact check. This file only adds the recipes these five places need, registered at
run time: three new archetypes ('dock', 'platform', 'quarry') and hand recipes for the waystation and the
works, whose generic recipes cannot hold the story-owned sets (V1, V7) or the works' apparatus yard.
Everything is authored in a terrace frame K(x, y) per site: x along the contour, y uphill, metres.
"""
import argparse
import json
import math
import os
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
WORLD = os.path.dirname(HERE)
ROOT = os.path.dirname(os.path.dirname(WORLD))
sys.path.insert(0, WORLD)
import build_setdress_sites as B  # noqa: E402
import setdress_v2 as V  # noqa: E402
from setdress_v2 import (BRICKS, COBBLES, PIECE_M, POTS, SHRUBS, STONES, TUFTS, rect,  # noqa: E402
                         seg_dist, terrace_frame)

GROUP = 'outposts_works'
OUT = os.path.join(HERE, GROUP + '.json')
PLOTS = os.path.join(ROOT, 'docs', 'world', 'setdress_v2')
SIDS = ('S01_CarrierDock', 'S14_DeparturePlatform', 'S19_LastWaystation', 'S15_Works', 'S16_Quarry')
BAGS = ['MV_jute_bag_%02d' % i for i in range(1, 11)]
CRATES = ['PH_wcrate', 'PH_mcrate', 'MV_box_01', 'MV_box_05', 'AB_Box_C', 'MV_box_03']
ROCKS_BIG = ['LF_Rock_04', 'LF_Rock_02', 'LF_Rock_05', 'LF_Rock_03', 'LF_Rock_01']


# ---------------------------------------------------------------------------- helpers

def ang_of(a, b):
    return math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))


def dims(key, scale=1.0):
    """(x, y, z) metres of a catalog mesh at a uniform scale (its local axes, not the long-axis swap)."""
    s = V.CAT[key]['size_cm']
    return s[0] / 100.0 * scale, s[1] / 100.0 * scale, s[2] / 100.0 * scale


def relief(C, u, v, ang, lx, ly):
    """Ground relief (m) under a plumb footprint: max - min of the 9 settle samples."""
    ca, sa = math.cos(math.radians(ang)), math.sin(math.radians(ang))
    zs = [C.F.g(u + ca * a * lx - sa * b * ly, v + sa * a * lx + ca * b * ly)
          for a in (-0.46, 0.0, 0.46) for b in (-0.46, 0.0, 0.46)]
    return max(zs) - min(zs)


def rigid(C, key, p, yaw, group, block, scale=1.0, sink=12.0, mat='stone', state='piece', landmark=False, **kw):
    """A plumb piece standing on the ground (contact 'rigid'), its visible height recorded for the plots."""
    H = dims(key, scale)[2]
    return C.add(key, p[0], p[1], yaw, group, 'rigid', scale=scale, sink_cm=round(sink, 1), material_set=mat,
                 block=block, state=state, vis_h=round(H - sink / 100.0, 2), landmark=landmark, **kw)


def rest(C, key, p, yaw, group, block=None, scale=1.0, mat='wood', **kw):
    """A loose prop set down on the ground (contact 'rest', physics settle)."""
    if block:
        kw['block'] = block
    return C.add(key, p[0], p[1], yaw, group, 'rest', scale=scale, material_set=mat, **kw)


def lie(C, key, p, yaw, group, block='fallen', scale=1.0, sink=8.0, mat='wood', pitch=0.0, roll=0.0, **kw):
    """A fallen piece lying on the ground, partly buried (contact 'lie')."""
    return C.add(key, p[0], p[1], yaw, group, 'lie', scale=scale, sink_cm=sink, material_set=mat, block=block,
                 pitch=pitch, roll=roll, **kw)


def loads(C, K, x0, y0, ang, cols, rows, keys, group, pitch_x=None, pitch_y=None, skip=0.0, jitter=6.0):
    """Loads set down in order: a tidy grid of crates, bags and trunks on the ground (never stacked: a stacked
    prop measures as floating in check2). Spacing from the largest footprint so nothing interpenetrates."""
    big = max(max(dims(k)[:2]) for k in keys)
    px = pitch_x or big + 0.15
    py = pitch_y or big + 0.15
    out = []
    n = 0
    for j in range(rows):
        for i in range(cols):
            if C.rng.random() < skip:
                continue
            key = keys[n % len(keys)]
            n += 1
            p = K(x0 + i * px + C.rng.uniform(-0.05, 0.05), y0 + j * py + C.rng.uniform(-0.05, 0.05))
            out.append(rest(C, key, p, ang + C.rng.uniform(-jitter, jitter), group))
    return out


def rock_ring(C, cu, cv, r0, r1, n, keys, group, block, scale=(0.9, 1.4), gap=0.25, avoid=None):
    """ISM plants or stones in a broken ring (the withered shrub ring round the poisoned works)."""
    k = 0
    for i in range(n * 3):
        if k >= n:
            break
        a = 2 * math.pi * C.rng.random()
        r = C.rng.uniform(r0, r1)
        u, v = cu + r * math.cos(a), cv + r * math.sin(a)
        if C.rng.random() < gap or C.on_lane(u, v, 0.4) or (avoid and avoid(u, v)):
            continue
        if math.hypot(u, v) > C.s.radius_m or C.F.road_dist(u, v) < 7.0:
            continue
        C.add(C.rng.choice(keys), u, v, C.rng.uniform(0, 360), group, scale=scale, ism=True, block=block)
        k += 1


def fence_line(C, pts, keys, group, block, sink=14.0, gate_first=False, step=None):
    """A timber fence along a polyline (rigid sections along each leg; the first section left out = the gate)."""
    L0 = V.piece_dims(keys[0])[0]
    step = step or L0 * 0.98
    first = True
    for a, b in zip(pts[:-1], pts[1:]):
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        m = max(1, int(round(L / step)))
        an = ang_of(a, b)
        for j in range(m):
            if first and gate_first:
                first = False
                continue
            first = False
            t = (j + 0.5) / m
            key = C.rng.choice(keys)
            yaw = an - (90.0 if V.long_axis_y(key) else 0.0) + C.rng.uniform(-2.5, 2.5)
            rigid(C, key, (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t), yaw, group, block, sink=sink,
                  mat='wood', state='fence')


def dust_fan(C, u, v, fu, fv, n, mean_d, keys=None, spread=40.0, lat=1.2, max_d=6.0, scale=(0.6, 1.3), block='fan'):
    """Stones spilling down a slope from a point (scree off a spoil heap, chips off a cut face)."""
    keys = keys or STONES + COBBLES
    for _ in range(n):
        d = min(max_d, 0.3 + C.rng.expovariate(1.0 / mean_d))
        a = math.radians(C.rng.uniform(-spread, spread))
        cu, cv = fu * math.cos(a) - fv * math.sin(a), fu * math.sin(a) + fv * math.cos(a)
        l_ = C.rng.uniform(-lat, lat)
        pu, pv = u + cu * d - fv * l_, v + cv * d + fu * l_
        if C.on_lane(pu, pv, 0.1) and C.rng.random() < 0.85:
            continue
        C.add(C.rng.choice(keys), pu, pv, C.rng.uniform(0, 360), 'rubble_ism', scale=scale, ism=True,
              settle_over=V.RUBBLE_SETTLE, block=block)


def thin_items(C, pred, keep):
    """Drop a share of the composed items matching pred (the rubble band of an intact place is lighter)."""
    out = []
    for it in C.s.items:
        if pred(it) and C.rng.random() > keep:
            continue
        out.append(it)
    C.s.items[:] = out


def lane_pts(C, pts, width, wander=0.3, strength=1.0):
    return C.path(pts, width, wander=wander, strength=strength)


# ---------------------------------------------------------------------------- S15 the works

S15_LAYOUT = '''
            withered shrub ring (nothing grows back inside it)
   feedstock: logs, bales   [FURNACE HALL: tall back gable | furnace hearth under the CHIMNEY STACK] [still room]  clay vessels x5
        dead pulley wheel in its pit     ===== yard lane ===== (hand-cart rails to the hall door)
   foreman's corner: cold fire pit,      [vat plinth: four fermentation vats, one toppled]  hoist   (still, manifold: Tripo)
   table, lamps, the tea pot                spill stain -> down the fall line into the gully (the basin was poisoned this way)
        [gutted store]   slag heaps on the gully lip                    danger board at the track
  ==== the cart track fades out toward the road (58 m) ====
'''


def works(C, sp):
    """The Works (the old forge / biofuel works): the furnace hall with its tall back gable, the furnace hearth
    and the chimney stack (the silhouette CIN_P15 frames from 360 m), the still room, the vat plinth and the
    apparatus yard downhill of the yard lane, the spill running down the fall line into the gully, slag heaps
    on the gully lip, feedstock, the foreman's corner (IDLE_MIDDLE_05's tea), a gutted store, the cart track to
    the road, and a withered shrub ring round the poisoned ground. Decay 3 overall; the hall holds at 2."""
    F, rng = C.F, C.rng
    O = sp.get('origin', (-8.0, -6.0))
    ang = F.contour_deg(*O)
    K = terrace_frame(ang, O)
    C.cu, C.cv = K(0.0, 2.0)
    # -- the yard lane in front of the hall, the track to the road (it fades out: the road is ~60 m off)
    lane = C.path([K(-17.0, -2.6), K(-2.0, -3.1), K(16.5, -2.5)], 2.8, wander=0.35)
    C.road_link(3.0, max_len=sp['road_link_max'], strength=0.95)
    # -- the furnace hall (9 x 6 m) and the still room (an L), one block sharing the party wall
    rooms = [rect(0, 0, 3, 2), rect(3, 0, 2, 2, minus=[(4, 1)])]
    P = C.block('W', *K(-7.5, 0.0), ang, rooms, 2, tall_back=(0, 2), keep_back=0.55, collapse_corners=1,
                lintel_p=0.8, tall_p=0.6)
    hall = C.last_block
    C.block_lane['W'] = lane
    # the chimney stack behind the furnace room's third cell, and the furnace hearth under it (same block)
    su, sv = P(2.5, 2.36)
    rigid(C, 'AB_Pillar_low', (su, sv), ang, 'hall', hall, sink=35, state='chimney', landmark=True,
          note='the furnace chimney stack: the works silhouette (CIN_P15_WORKS)')
    fu_, fv_ = P(2.5, 1.62)
    rigid(C, 'AB_Fireplace', (fu_, fv_), ang + 180.0, 'hall', hall, sink=18, state='hearth',
          note='the furnace mouth (cold)')
    C.patch('soot', *P(2.5, 1.2), ang, 4.6, 3.2, 1.0, order=4)
    C.patch('soot', *P(2.2, 0.5), ang + 20, 3.0, 2.0, 0.7, order=4)
    # -- the yard below the lane: the vat plinth (flags), four fermentation vats, one toppled; the hoist
    vy = -7.0
    for i in range(4):
        C.add('B01_floor01', *K(-0.2 + 3.05 * i, vy + rng.uniform(-0.1, 0.1)), ang + rng.uniform(-2, 2), 'vats',
              'rigid', sink_cm=14, material_set='stone', block='plinth', ism=True, state='flags')
    for i in range(4):
        x = -0.4 + 2.55 * i
        if i == 3:
            # the toppled vat: it lies downhill of the plinth, its mouth to the spill
            lie(C, 'B01_tank01', K(x + 2.0, vy - 3.4), ang + 75, 'vats', scale=2.0, sink=20, mat='stone', roll=90.0,
                note='the toppled vat; the spill ran from its mouth')
            continue
        rigid(C, 'B01_tank01', K(x, vy + rng.uniform(-0.15, 0.15)), ang + rng.uniform(0, 360), 'vats', 'vat%d' % i,
              scale=2.1, sink=10, state='vat', note='wood-hooped clay fermentation vat')
    rigid(C, 'B01_crane01', K(-4.6, vy - 0.3), ang + 90.0, 'vats', 'hoist', sink=12, mat='wood', state='hoist',
          note='hand-cranked hoist over the vats')
    # the Tripo apparatus (optional until imported): the still at the east end, the manifold behind the vats
    st = C.find_spot([K(14.0, -7.5), K(15.5, -5.0), K(13.0, -10.0)], 2.4, margin=0.4)
    if st:
        rigid(C, 'T2_biofuel_still', st, ang + 180.0, 'apparatus', 'still', sink=12, mat='stone', state='apparatus',
              note='S15 slot of the Tripo copper_still (biofuel still)')
    mf = C.find_spot([K(4.0, -11.2), K(7.5, -11.5)], 2.0, margin=0.3)
    if mf:
        rigid(C, 'T2_pipe_manifold', mf, ang, 'apparatus', 'manifold', sink=8, mat='stone', state='apparatus',
              note='S15 slot of the Tripo steam_pipe (the manifold)')
    # riveted pipe elbows fallen from the run between the still room and the vats
    for (x, y, yw) in ((6.2, -4.6, 30.0), (10.4, -10.8, 115.0), (-2.4, -10.6, 200.0)):
        lie(C, 'B01_pipe01', K(x, y), ang + yw, 'pipes', sink=10, mat='stone', note='riveted pipe elbow, fallen')
    # the hand-cart rails from the vat plinth up to the still-room door (ground covers)
    for i, y in enumerate((-4.6, -1.6)):
        C.add('B01_rail01', *K(8.2, y), ang + 90.0 + rng.uniform(-2, 2), 'rails', 'rigid', sink_cm=6,
              material_set='wood', block='rails', ism=True, state='rail')
    # -- the spill: from the toppled vat's mouth down the fall line (a dark stain, a pale crust at its edge)
    top = K(4.0, vy - 4.4)
    z0 = F.g(*top)
    spill = F.descent(top[0], top[1], lambda u, v: F.g(u, v) < z0 - 2.4 or F.road_dist(u, v) < 8.0, step=1.5, n=30)
    C.path(spill, 1.3, surface='soot', strength=0.75, order=4, lane=False)
    C.path(spill, 2.6, surface='dry_mud', strength=0.6, order=2, lane=False)
    C.meta['spill'] = spill
    # -- slag heaps on the lip beyond the spill (dark: soot under them)
    end = spill[-1]
    du, dv = F.downhill(*end)
    for k, (off, sc) in enumerate(((-5.5, 1.3), (-2.0, 1.0), (4.5, 1.15))):
        hu, hv = end[0] - dv * off - du * 2.0, end[1] + du * off - dv * 2.0
        if not C.point_clear(hu, hv, 1.0, 0.8):
            continue
        lie(C, 'B01_rubble01', (hu, hv), rng.uniform(0, 360), 'slag', block='slag', scale=sc, sink=30, mat='stone',
            note='slag heap')
        C.patch('soot', hu, hv, rng.uniform(0, 180), 5.5 * sc, 4.0 * sc, 0.8, order=1)
        dust_fan(C, hu, hv, du, dv, 10, 1.4, keys=STONES + ['LF_Rock_06'])
    # -- the store's end: a row of big clay vessels (the product), one tipped
    for i in range(5):
        key = POTS[i % 4]
        sc = rng.uniform(3.6, 4.6)
        p = K(8.4 + 1.55 * i, 7.6 + rng.uniform(-0.2, 0.2))
        if not C.point_clear(p[0], p[1], 0.5, 0.5):
            continue
        rest(C, key, p, rng.uniform(0, 360), 'vessels', block='vessels', scale=sc, mat='stone',
             roll=(88.0 if i == 3 else 0.0), note='storage vessel' + (', tipped' if i == 3 else ''))
    # -- the feedstock stacks at the hall's west end: log piles and bales
    for key, (x, y), yw in (('BPP_Logs_01', (-13.5, 3.2), 0.0), ('MV_Logs_Package', (-12.2, 6.4), 90.0),
                            ('MV_Hay_Bale_01', (-15.8, 0.6), 10.0), ('MV_Hay_Bale_02', (-14.3, 0.2), -8.0)):
        p = K(x, y)
        if C.point_clear(p[0], p[1], 0.4, 0.4):
            if key == 'MV_Logs_Package':
                lie(C, key, p, ang + yw, 'feedstock', pitch=90.0, sink=6, note='log bundle, lying')
            elif key.startswith('BPP'):
                rigid(C, key, p, ang + yw, 'feedstock', 'logpile', sink=6, mat='wood', state='pile')
            else:
                rest(C, key, p, ang + yw, 'feedstock')
    # -- the dead pulley: the mill wheel standing in its pit beside its support (the hoist drive)
    wu, wv = K(-10.8, -6.2)
    rigid(C, 'MV_Wm_wheel_support', (wu, wv), ang, 'pulley', 'pulley', scale=0.85, sink=20, mat='wood', state='wheel')
    rigid(C, 'MV_Woodmill_Wheel', K(-10.8, -8.2), ang + 90.0, 'pulley', 'pulley', scale=0.62, sink=45, mat='wood',
          state='wheel', note='the dead pulley wheel, standing in its pit')
    # -- the foreman's corner: a cold fire pit, the tea pot, a table and chair, two lamps (IDLE_MIDDLE_05)
    fc = C.find_spot([K(-15.0, -7.0), K(-16.0, -9.5), K(-13.5, -11.0)], 2.2, margin=0.4)
    if fc:
        rigid(C, 'PH_fire_pit', fc, rng.uniform(0, 360), 'foreman', 'firepit', sink=8, state='hearth')
        C.patch('soot', fc[0], fc[1], 0, 2.4, 2.4, 0.9, order=4)
        e = (math.cos(math.radians(ang)), math.sin(math.radians(ang)))
        n_ = (-e[1], e[0])
        rest(C, 'PH_pot', (fc[0] + e[0] * 1.2, fc[1] + e[1] * 1.2), 0, 'foreman', note='the tea pot, cold')
        rest(C, 'AB_Table', (fc[0] - n_[0] * 1.9, fc[1] - n_[1] * 1.9), ang + 8, 'foreman')
        rest(C, 'AB_Chair_A_low', (fc[0] - n_[0] * 1.9 + e[0] * 1.0, fc[1] - n_[1] * 1.9 + e[1] * 1.0), ang - 60,
             'foreman')
        for s_ in (-1, 1):
            rest(C, 'AB_Lamp_A', (fc[0] - n_[0] * 2.8 + e[0] * 0.5 * s_, fc[1] - n_[1] * 2.8 + e[1] * 0.5 * s_), 0,
                 'foreman', mat='stone')
        C.path([fc, V.nearest_on([lane], fc)], 1.2, strength=0.85)
    # -- the gutted store across the yard (decay 3: stumps and gaps)
    for (x, y, a_) in ((-6.0, -15.5, -6.0), (-12.0, -14.0, 4.0), (2.0, -16.5, 8.0)):
        u0, v0 = K(x, y)
        cells = rect(0, 0, 2, 1) + [(2, 0)]
        if C.fits(C.quads(u0, v0, ang + a_, cells), 1.2):
            C.block('S', u0, v0, ang + a_, [rect(0, 0, 2, 1), [(2, 0)]], 3, collapse_corners=1, lintel_p=0.3)
            C.block_lane['S'] = lane
            break
    C.door_spurs(width=1.3)
    outskirts_frag(C, 2, 3)
    # -- the danger board where the track leaves the road's reach
    trk = [ln for ln in C.lanes if ln['width'] == 3.0]
    if trk:
        a, b = trk[-1]['pts'][0], trk[-1]['pts'][1]
        d = ang_of(a, b)
        p = (a[0] - math.sin(math.radians(d)) * 2.4, a[1] + math.cos(math.radians(d)) * 2.4)
        if F.road_dist(*p) > 7.0 and math.hypot(*p) < C.s.radius_m:
            rigid(C, 'B01_sign02', p, d + 90.0, 'boards', 'board', scale=0.9, sink=22, mat='wood', state='board',
                  note='danger board I20 (painted wood)', verdict_check=True)
    # -- the ground: packed earth over the works, soot mottling, the withered ring round it
    C.patch('packed_earth', *K(0.0, -3.0), ang, 42.0, 30.0, 0.7, order=0)
    C.patch('rubble_dust', *K(4.0, -7.0), ang, 16.0, 7.0, 0.6, order=1)
    for (x, y) in ((-4.0, 3.0), (6.0, -9.0), (-9.0, -12.0)):
        C.patch('soot', *K(x, y), rng.uniform(0, 180), 4.0, 2.4, 0.45, order=4)
    rock_ring(C, C.cu, C.cv - 3.0, 24.0, 31.0, 22, SHRUBS, 'withered_ring', 'creep', scale=(0.8, 1.3), gap=0.2)
    C.meta.update(frame=dict(ang=ang, O=O))


def works_post(C, sp):
    """Poisoned ground: nothing green creeps back inside the works (dry tufts go; a few dead shrubs stay)."""
    cu, cv = C.cu, C.cv - 3.0
    thin_items(C, lambda it: it.get('block') == 'creep' and it['key'] in TUFTS and math.hypot(it['u'] - cu, it['v'] - cv) < 22.0,
               0.15)


def outskirts_frag(C, n, decay):
    """A few wall fragments beyond the core (the edge thins out)."""
    rng = C.rng
    made = 0
    for _ in range(n * 15):
        if made >= n:
            break
        a = rng.uniform(0, 2 * math.pi)
        d = rng.uniform(16.0, 24.0)
        u, v = C.cu + d * math.cos(a), C.cv + d * math.sin(a)
        ang = C.F.contour_deg(u, v) + rng.uniform(-14, 14)
        m = rng.choice((1, 2))
        q = (u + math.cos(math.radians(ang)) * PIECE_M * m, v + math.sin(math.radians(ang)) * PIECE_M * m)
        if C.seg_clear((u, v), q, margin=1.2):
            C.nblock += 1
            C.wall_line((u, v), q, [rng.choice(['damaged', 'low', 'stump', 'stump']) for _ in range(m)],
                        'frag_%d' % C.nblock, 'outskirts', C.F.downhill(u, v))
            made += 1


# ---------------------------------------------------------------------------- registration and build

def recipes():
    return dict(works=works, works_post=works_post)


SPECS = {
    'S15_Works': dict(
        archetype='works', recipe=works, post=works_post, seed='S15v2.g1', radius_m=48, road_link_max=40.0,
        burnt=0, mud=0, creep_edge=10, origin=(-8.0, -6.0),
        name='Iphrib Khazb, the Works (the old forge)', role='landmark', layout=S15_LAYOUT,
        style='BAZAAR STONE + timber + clay: a traditional biofuel forge-works (hand hoist, riveted pipes, clay vats; '
              'nothing modern)',
        notes='V2 (setdress_v2_groups/outposts_works.py). The hall and the chimney stack are the landmarks CIN_P15_WORKS '
              'frames from road 2,260. Tripo slots (optional): copper_still -> T2_biofuel_still, steam_pipe -> '
              'T2_pipe_manifold. Optional smoke FX stays off (no one tends a fire here).'),
}


def register():
    V.SITE_SPECS.update(SPECS)


def compose(W, sid):
    """setdress_v2.compose, plus the recipe's post pass after the shared finish passes."""
    row, sp = V.spec_for(sid)
    lat = row.get('lateral_m') or 0.0
    s = B.Site(sid, sp.get('name', row['name']), row['road_m'], lat, row['kind'], sp.get('role', row['role']),
               sp.get('story', row.get('story') or ''), sp['decay'], sp.get('style', row.get('style') or ''),
               sp.get('order', row.get('order', 2)), sp.get('radius_m', row.get('radius_m', 40)),
               layout=sp.get('layout', row.get('layout') or ''), notes=sp.get('notes', row.get('notes') or ''),
               story_owned=row.get('story_owned') or [])
    F = V.Frame(W, row['road_m'], lat)
    C = V.Composer(s, F, zlib.crc32(str(sp.get('seed') or sid + 'v2.1').encode()))
    sp['recipe'](C, sp)
    s.spec = {k: v for k, v in sp.items() if not callable(v)}
    C.finish(sp)
    if sp.get('post'):
        sp['post'](C, sp)
    s.v2['group'] = GROUP
    return s


def build(W, sids):
    """setdress_v2.build with this group's compose: placements, ground decals, units, views, offline check."""
    S = [compose(W, sid) for sid in sids]
    out_sites, totals = B.build(W, S)
    by_id = {s.sid: s for s in S}
    for so in out_sites:
        s = by_id[so['id']]
        V.resolve_refs(so)
        so['archetype'] = s.spec['archetype']
        so['ground'] = V.ground_records(so, s)
        so['units'] = s.units
        so['views'] = V.v2_views(W, s, s.frame, so['placements'])
        so['v2'] = s.v2
        so['counts']['decals'] = len(so['ground'])
        so['load_box_cm'] = [round(v) for v in so['load_box_cm']]
        v, w = V.offline_check(W, so)
        so['offline_check'] = dict(violations=[list(x) for x in v], waived=[list(x) for x in w],
                                   note='estimated offline (setdress_contact.offline_reports); check2 in the editor decides')
    return out_sites, totals


def review_plot(W, so, path):
    """The review sheet: top-down over the composed site (walls shaded by visible height, the decal ground,
    1 m terrain contours, the road) and an axonometric seen from the carrier's side of the road."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    import setdress_v2_plot as PL
    F = V.Frame(W, so['road_m'], so.get('lateral_m') or 0.0)
    cu, cv = so['v2']['core']
    core = [p for p in so['placements'] if not (p['ism'] and p.get('block') == 'creep')]
    uv = np.array([F.site(p['x_cm'] / 100.0, p['y_cm'] / 100.0) for p in core])
    win = (uv[:, 0].min() - 5, uv[:, 0].max() + 5, uv[:, 1].min() - 5, uv[:, 1].max() + 5)
    fig, axs = plt.subplots(1, 2, figsize=(30, 14), gridspec_kw=dict(width_ratios=[1.0, 1.15]))
    c = so['counts']
    title = '%s (%s): %d placements, %d actors, %d ISM, %d decals; offline contact check: %d violations' % (
        so['id'], so['archetype'], c['placements'], placed_actors(so), c['ism_instances'], c['decals'],
        len(so['offline_check']['violations']))
    sm = PL.topdown(axs[0], so, F, title, window=win)
    us = np.arange(win[0], win[1], 1.0)
    vs = np.arange(win[2], win[3], 1.0)
    Z = np.array([[F.g(u, v) for u in us] for v in vs])
    cs = axs[0].contour(us, vs, Z, levels=np.arange(math.floor(Z.min()), Z.max() + 1, 1.0), colors='#6b5a45',
                        linewidths=0.35, alpha=0.6, zorder=0.8)
    axs[0].clabel(cs, cs.levels[::2], fontsize=6, fmt='%.0f')
    fig.colorbar(sm, ax=axs[0], shrink=0.35, label='visible wall height (m)')
    groups = {}
    for p in so['placements']:
        if p['ism'] or p['group'] in ('rubble', 'beams', 'houses', 'outskirts'):
            continue
        groups.setdefault(p['group'], []).append(F.site(p['x_cm'] / 100.0, p['y_cm'] / 100.0))
    for g, pts in groups.items():
        a = np.array(pts)
        axs[0].text(a[:, 0].mean(), a[:, 1].mean() + 1.2, g, fontsize=8, color='#1b2a4a', zorder=9, ha='center',
                    bbox=dict(fc='white', ec='none', alpha=0.55, pad=0.5))
    # the axonometric: from the side the carrier approaches (the road point 60-90 m before the site)
    p, _, _ = W.frame(max(0.0, so['road_m'] - so.get('view_back_m', 70.0)))
    ru, rv = F.site(p[0], p[1])
    look = math.atan2(cv - rv, cu - ru)
    R =max(16.0, min(34.0, max(win[1] - win[0], win[3] - win[2]) / 2.6))
    PL.axo(axs[1], so, F, W, '%s, axonometric from the road side (looking %.0f deg in the site frame)' % (
        so['id'], math.degrees(look)), window=(cu - R, cu + R, cv - R, cv + R), cam=PL.Axo(az=az_of(look), el=32.0))
    fig.savefig(path, dpi=62, bbox_inches='tight')
    plt.close(fig)
    print('plot', path)


def az_of(look):
    """Axo azimuth (0 = looking along +v, see setdress_v2_plot.Axo) for a look direction (radians, site frame)."""
    return math.degrees(math.atan2(math.cos(look), math.sin(look)))


def placed_actors(so):
    P = [p for p in so['placements'] if not p.get('optional')]
    return sum(1 for p in P if not p['ism']) + len({(p['group'], p['asset']) for p in P if p['ism']})


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--sites', nargs='*', default=list(SIDS))
    ap.add_argument('--plot-dir', default=PLOTS, help='where the review plots go')
    ap.add_argument('--no-json', action='store_true', help='plots only (iteration)')
    args = ap.parse_args(argv)
    register()
    W = B.World()
    out_sites, t = build(W, args.sites)
    os.makedirs(args.plot_dir, exist_ok=True)
    for so in out_sites:
        c = so['counts']
        nudged = sum(1 for p in so['placements'] if 'nudged' in p.get('note', ''))
        print('%s (%s) placements %d actors %d ism %d decals %d nudged %d offline violations %d' % (
            so['id'], so['archetype'], c['placements'], placed_actors(so), c['ism_instances'], c['decals'], nudged,
            len(so['offline_check']['violations'])))
        for x in so['offline_check']['violations'][:12]:
            print('    ', x)
        review_plot(W, so, os.path.join(args.plot_dir, '%s.png' % so['id']))
    for r in t['rejected']:
        print('rejected', r)
    for r in t['checks']:
        print('check', r)
    if not args.no_json:
        doc = dict(generated_by='Tools/World/setdress_v2_groups/outposts_works.py', group=GROUP,
                   method='docs/world/SETDRESS_V2.md', level='/Game/level/Saskarta_WP',
                   conventions=dict(xy='world cm; yaw = UE yaw deg', bounds='x_cm/y_cm is the mesh BOUNDS CENTRE',
                                    ground='decal patches: DecalActor pitch -90, yaw, size (depth/2, width/2, length/2)',
                                    contact='rigid | rest | lie | bear | carried | stack (SETDRESS_V2.md section 3)',
                                    optional='Tripo models still in production: placed only with --with-optional'),
                   rejected=t['rejected'], checks=t['checks'], sites=out_sites)
        with open(OUT, 'w', encoding='utf8') as fh:
            json.dump(doc, fh, indent=1, ensure_ascii=False)
        print('wrote', OUT)


if __name__ == '__main__':
    main()
