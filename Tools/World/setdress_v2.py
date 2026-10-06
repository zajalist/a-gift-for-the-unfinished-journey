"""Set dressing V2: composed, ground-integrated sites (method: docs/world/SETDRESS_V2.md).

    python Tools/World/setdress_v2.py              # write Tools/World/setdress_v2_sites.json
    python Tools/World/setdress_v2.py --plot       # also the review plots (Tools/World/setdress_v2_plot.py)

V1 (build_setdress_sites.py) authored a site as independent props: `scatter` in a disc, `ring`, a
free-standing `hut`, and an overlap pass that pushed everything apart. That is exactly what the user saw:
"toys on an empty plain". V2 composes a site from a grammar instead:

  terrain  -> contour frame (blocks run along the contours, terraces step up the slope)
  blocks   -> rooms made of 3 m cells (rectangles, L shapes, missing corners) that SHARE party walls
  walls    -> one piece per cell edge, each with a decay state; standing pieces vary in height
              (4 m walls sunk by different depths, 1.4 m broken rubble walls, 1 m stumps, a tall Fort piece)
  doors    -> an arch piece, or a timber lintel carried by two stone jambs (a 'bear' piece, checked at both ends)
  collapse -> each broken piece drops a rubble fan DOWNHILL of it; whole corners come down in big fans
  beams    -> fallen roof beams inside the roofless rooms, never through a standing wall
  lanes    -> worn paths along each terrace, ramps at the ends, door spurs, a wide path from the road
  ground   -> deferred-decal patches under the site: packed earth, worn paths, door aprons, rubble dust fans
  rubble   -> dense small stones hugging every standing wall base and room corner
  creep    -> dry tufts and dead shrubs in room corners, inside the roofless rooms and at wall bases
  density  -> a dense core, lone rooms and terrace walls thinning out to the edges

The output uses V1's placement schema (so place_setdress.py places it) plus:
  site['ground']  the decal patches (place_setdress.py 'ground' step)
  site['units']   composite units (an awning kit: frame + cloth + its table) placed and checked as one
  site['v2']      layout metadata for the tests and plots (blocks, rooms, lanes, doors, fans, beams) in site metres
Nothing here talks to Unreal.
"""
import argparse
import json
import math
import os
import random
import sys
import zlib

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import build_setdress_sites as B  # noqa: E402
import setdress_catalog  # noqa: E402
import setdress_contact  # noqa: E402

OUT = os.path.join(HERE, 'setdress_v2_sites.json')
CAT = B.CATALOG

# ---------------------------------------------------------------------------- the kit

PIECE_M = 3.0
# Standing wall pieces per decay state: (catalog key, uniform scale, sink range cm). The sink is how the kit
# gets its HEIGHT VARIETY without stretching textures: a 4 m piece sunk 20-110 cm shows 2.9-3.8 m (the buried
# part is foundation), the broken rubble wall shows about 1.2 m, a stump 0.6-0.9 m, the Fort piece 3.9 m.
PALETTE = {
    'full': [('AB_300x400_Mid', 1.0, (20, 95))],
    'damaged': [('AB_300x400_Mid_Damaged_A', 1.0, (20, 115))],
    'low': [('B01_wall01', 0.75, (8, 24))],
    'stump': [('AB_300x100_Panel', 1.0, (10, 35)), ('AB_300x100_Panel_Damages_A', 1.0, (10, 30))],
    'tall': [('AB_Fort_Wall_Mid', 1.0, (10, 16))],
    'window': [('B01_window01', 1.35, (20, 40))],
    'door': [('AB_Side_Arch_small', 1.0, (14, 14))],
    'gate': [('AB_Side_Arch', 1.0, (20, 20))],
}
PIECE = {'full': 'AB_300x400_Mid', 'damaged': 'AB_300x400_Mid_Damaged_A', 'stump': 'AB_300x100_Panel',
         'stump_b': 'AB_300x100_Panel_Damages_A', 'door': 'AB_Side_Arch_small', 'window': 'B01_window01'}
STANDING = ('full', 'damaged', 'low', 'stump', 'tall', 'window', 'door', 'lintel', 'tallruin', 'drystone', 'gate')
SHED = {'full': 0.12, 'tall': 0.1, 'window': 0.15, 'door': 0.1, 'lintel': 0.12, 'damaged': 0.45, 'low': 0.6,
        'stump': 0.75, 'gap': 1.0, 'tallruin': 0.3, 'gate': 0.1}
TALL_RUIN = 'AB_Broken_Arch_Wall'          # a 7.2 m broken wall with an arch: the surviving gable of a tall house
JAMBS = ['AB_Pillar_A_01', 'AB_Pillar_A_02', 'AB_Pillar_A_03']
LINTEL = ('B01_beam01', 0.85)              # iron-banded timber, 2.63 m at 0.85: ends 0.1 m inside the jamb tops
JAMB_OFF = 1.1                             # jamb centres at +-1.1 m along the wall: a 1.58 m clear doorway
JAMB_SINK = 12.0                           # cm, the lower jamb; the upper one sinks by the ground step too
MAX_JAMB_STEP = 0.3                        # m of ground step between the jambs a lintel doorway accepts
DRYSTONE = 'B01_wall02'                    # the dry-stone course of field terraces and yard walls
BEAMS = [('MV_Beam_03', 90.0, 3.5), ('AB_Woden_Beam_A_low', 90.0, 3.0), ('B01_beam01', 0.0, 3.09),
         ('MV_Beam_06', 0.0, 3.0)]         # (key, pitch to lie it down, length m)
BRICKS = ['AB_Brick_A3', 'AB_Brick_A4', 'AB_Brick_A', 'AB_Brick_A1']      # the lighter Nanite bricks first
COBBLES = ['AB_Cobble_%02d' % i for i in range(1, 8)]
STONES = ['LF_Rock_07', 'LF_Rock_08']
CHUNKS = ['AB_Pillar_A_04', 'AB_Pillar_A_05', 'AB_Pillar_Part']
SHRUBS = ['FAB_Shrub_' + c for c in 'ABCDEFGH']
TUFTS = sorted(setdress_catalog.DRY_TUFT_MATERIAL)
POTS = ['AB_Clay_Pot_A', 'AB_Clay_Pot_B', 'AB_Clay_Pot_C', 'AB_Clay_Pot_D']
AWNING = ('AB_Tent_C_Frame', 'AB_Tent_C_Cloth')   # a kit: frame + cloth sharing one pivot (V1 S14 capture)

# Contact classes (the settle and the V2 checker both read them):
#   rigid : architecture. Plumb (no tilt), z so that NO footprint sample floats; the uphill side is buried.
#   rest  : a prop standing on the ground (3+ contacts within 5 cm), tilted to the slope.
#   lie   : a fallen piece lying on the ground, partly buried (bury_frac of its height).
#   bear  : a lintel carried at both ends by its named jambs (bears_on); physics settle onto them.
#   carried: a unit's cover (the awning cloth), copied onto its frame's pivot (attach, shares_pivot).
SETTLE = {
    'rigid': dict(mode='trace', max_tilt_deg=0, rand_tilt_deg=0, z_rule='min'),
    'rest': dict(mode='physics', max_tilt_deg=15, rand_tilt_deg=3, z_rule='max'),
    'lie': dict(mode='trace', max_tilt_deg=25, rand_tilt_deg=10, z_rule='mean'),
    'bear': dict(mode='physics', max_tilt_deg=8, rand_tilt_deg=0, z_rule='max', sink_cm=0),
}
RUBBLE_SETTLE = dict(sink_cm=5, rand_tilt_deg=30, max_tilt_deg=35)
CHUNK_SETTLE = dict(mode='trace', sink_cm=16, max_tilt_deg=25, rand_tilt_deg=12, z_rule='mean')


def long_axis_y(key):
    s = CAT[key]['size_cm']
    return s[1] > s[0]


def piece_dims(key, scale=1.0):
    s = CAT[key]['size_cm']
    L, T = (s[1], s[0]) if long_axis_y(key) else (s[0], s[1])
    return L / 100.0 * scale, T / 100.0 * scale, s[2] / 100.0 * scale


def rot(a_deg, x, y):
    c, s = math.cos(math.radians(a_deg)), math.sin(math.radians(a_deg))
    return x * c - y * s, x * s + y * c


def seg_dist(p, a, b):
    du, dv = b[0] - a[0], b[1] - a[1]
    L2 = du * du + dv * dv
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * du + (p[1] - a[1]) * dv) / L2))
    return math.hypot(a[0] + t * du - p[0], a[1] + t * dv - p[1])


def seg_seg_dist(a, b, c, d):
    """Plan distance between segments ab and cd (0 when they cross)."""
    def orient(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    o1, o2, o3, o4 = orient(a, b, c), orient(a, b, d), orient(c, d, a), orient(c, d, b)
    if o1 * o2 < 0 and o3 * o4 < 0:
        return 0.0
    return min(seg_dist(a, c, d), seg_dist(b, c, d), seg_dist(c, a, b), seg_dist(d, a, b))


def in_quad(p, q):
    """p inside the convex quad q (either winding)."""
    sgn = None
    for i in range(4):
        a, b = q[i], q[(i + 1) % 4]
        c = (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])
        if abs(c) < 1e-12:
            continue
        if sgn is None:
            sgn = c > 0
        elif (c > 0) != sgn:
            return False
    return True


def quad_dist(p, q):
    """Plan distance from p to the convex quad q (0 inside)."""
    if in_quad(p, q):
        return 0.0
    return min(seg_dist(p, q[i], q[(i + 1) % 4]) for i in range(4))


def quad_quad_dist(a, b):
    """Plan distance between two convex quads (0 when they overlap)."""
    if B.sat_overlap(a, b) > 0:
        return 0.0
    return min(seg_seg_dist(a[i], a[(i + 1) % 4], b[k], b[(k + 1) % 4]) for i in range(4) for k in range(4))


def quad_samples(q, step):
    """Points along the edges of a quad every ~step m, and its centre."""
    out = [(sum(p[0] for p in q) / 4.0, sum(p[1] for p in q) / 4.0)]
    for i in range(4):
        a, b = q[i], q[(i + 1) % 4]
        n = max(1, int(math.hypot(b[0] - a[0], b[1] - a[1]) / step))
        out += [(a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n) for k in range(n)]
    return out


def resample(pts, step):
    """Points along a polyline at a fixed chord step (wall pieces of one length follow a curve)."""
    out = [pts[0]]
    i, cur = 1, pts[0]
    while i < len(pts):
        d = math.hypot(pts[i][0] - cur[0], pts[i][1] - cur[1])
        if d >= step:
            t = step / d
            cur = (cur[0] + (pts[i][0] - cur[0]) * t, cur[1] + (pts[i][1] - cur[1]) * t)
            out.append(cur)
        else:
            i += 1
    return out


def rect(i0, j0, w, d, minus=()):
    """Cells of a w x d rectangle at (i0, j0), minus some cells (a missing corner makes an L)."""
    return [(i0 + i, j0 + j) for i in range(w) for j in range(d) if (i0 + i, j0 + j) not in set(minus)]


# ---------------------------------------------------------------------------- terrain in the site frame

class Frame:
    """Site-local metres: u along the road (player direction), v to the right; ground and slope from Gaea."""

    def __init__(self, W, road_m, v0=0.0):
        self.W = W
        p, f, r = W.frame(road_m)
        self.o = p + r * v0
        self.f, self.r = f, r

    def world(self, u, v):
        q = self.o + self.f * u + self.r * v
        return float(q[0]), float(q[1])

    def site(self, x, y):
        d = np.array([x, y]) - self.o
        return float(d @ self.f), float(d @ self.r)

    def g(self, u, v):
        return self.W.ground(*self.world(u, v))

    def grad(self, u, v, h=1.0):
        """(dz/du, dz/dv) in m per m."""
        return ((self.g(u + h, v) - self.g(u - h, v)) / (2 * h), (self.g(u, v + h) - self.g(u, v - h)) / (2 * h))

    def downhill(self, u, v):
        gu, gv = self.grad(u, v, 2.0)
        n = math.hypot(gu, gv)
        return (-gu / n, -gv / n) if n > 1e-4 else (0.0, -1.0)

    def contour_deg(self, u, v):
        """Direction (deg, site frame) along the contour with the uphill side on the LEFT (+90)."""
        du, dv = self.downhill(u, v)
        # the contour is perpendicular to the fall line; pick the one with uphill (= -downhill) on its left
        return math.degrees(math.atan2(du, -dv))

    def road_dist(self, u, v):
        d, _ = self.W.road_distance([self.world(u, v)])
        return d

    def contour_line(self, z, u0, u1, v_lo, v_hi, step=3.0):
        """Points (u, v) where the ground is at height z, scanning v for each u (the hillside rises with v)."""
        pts = []
        for u in np.arange(u0, u1 + 1e-6, step):
            lo, hi = v_lo, v_hi
            if (self.g(u, lo) - z) * (self.g(u, hi) - z) > 0:
                continue
            for _ in range(24):
                mid = 0.5 * (lo + hi)
                if (self.g(u, lo) - z) * (self.g(u, mid) - z) <= 0:
                    hi = mid
                else:
                    lo = mid
            pts.append((float(u), 0.5 * (lo + hi)))
        return pts

    def descent(self, u, v, stop, step=2.0, n=200):
        """Steepest-descent polyline from (u, v) until stop(u, v) is true (a channel follows the fall line)."""
        pts = [(u, v)]
        for _ in range(n):
            du, dv = self.downhill(u, v)
            u, v = u + du * step, v + dv * step
            pts.append((u, v))
            if stop(u, v):
                break
        return pts


# ---------------------------------------------------------------------------- the composer

class Composer:
    def __init__(self, site, F, seed):
        self.s = site
        self.F = F
        self.rng = random.Random(seed)
        self.ground = []      # decal patches, site-local
        self.units = []
        self.lanes = []       # polylines (u, v) with a width
        self.doors = []       # (u, v, block name, room, face_u, face_v)
        self.fans = []        # rubble fans: (u, v, dir_u, dir_v, amount)
        self.corner_falls = []  # collapsed corners: (u, v, dir_u, dir_v)
        self.rows = []        # blocks (kept as 'rows' for the tools that read them)
        self.rooms = []       # rooms: cells (quads), corners (inset points), centre, size, angle
        self.walls = []       # (u0, v0, u1, v1, state, block) per piece, for base scatter, checks and plots
        self.beams = []       # fallen beams: (u0, v0, u1, v1)
        self.lintels = []     # (ref_beam, ref_jamb_a, ref_jamb_b, u, v, ang)
        self.yards = []       # walled yards: dict(pts, block)
        self.solids = []      # footprint circles of every placed solid actor: (u, v, r, block)
        self.block_lane = {}  # block name -> the lane its doors open onto (the recipes fill it)
        self.meta = {}        # recipe extras for site.v2 (the S07 channel, the terrace frame)
        self.nblock = 0
        self.nref = 0
        self.cu, self.cv = 0.0, 0.0

    # -- low level
    def add(self, key, u, v, yaw, group, contact=None, scale=1.0, **kw):
        kw.setdefault('composed', True)
        kw.setdefault('id_prefix', self.s.sid + '_v2')
        if contact in SETTLE:
            over = dict(SETTLE[contact])
            over.update(kw.pop('settle_over', {}) or {})
            if 'sink_cm' in kw:
                over['sink_cm'] = kw.pop('sink_cm')
            kw['settle_over'] = over
            kw['contact'] = contact
        elif contact:
            kw['contact'] = contact
        if key in setdress_catalog.DRY_TUFT_MATERIAL:
            kw['material'] = setdress_catalog.DRY_TUFT_MATERIAL[key]
        if CAT[key].get('pending') or not CAT[key].get('exists', True):
            # a Tripo model still in production: placed only with --with-optional, its fallback stands in
            kw.setdefault('optional', True)
            kw['note'] = (kw.get('note', '') + '; ' if kw.get('note') else '') + 'Tripo model, available later (optional)'
        if contact == 'channel' or (not kw.get('ism') and contact in ('rigid', 'rest', 'lie', 'bear', 'carried')):
            sz = CAT[key]['size_cm']
            sz = (sz[2], sz[1]) if abs(kw.get('pitch', 0.0)) > 60 else (sz[0], sz[1])
            sc = max(scale) if isinstance(scale, (tuple, list)) else scale
            self.solids.append((u, v, 0.5 * math.hypot(sz[0], sz[1]) / 100.0 * sc, kw.get('block')))
        return self.s.add(key, u, v, yaw, scale, group, **kw)

    def ref(self, stem):
        self.nref += 1
        return '%s_r%03d' % (stem, self.nref)

    def patch(self, surface, u, v, yaw, length, width, strength=1.0, shape='ellipse', order=0):
        self.ground.append(dict(surface=surface, u=u, v=v, yaw=yaw, length=length, width=width,
                                strength=min(1.0, strength), shape=shape, order=order))

    def path(self, pts, width, surface='path', strength=1.0, order=3, lane=True, wander=0.0):
        """A worn path: capsule decals along the polyline (overlapping), plus a lane record for keep-outs."""
        if wander > 0:
            pts = self.meander(pts, wander)
        if lane:
            self.lanes.append(dict(pts=pts, width=width))
        for (u0, v0), (u1, v1) in zip(pts[:-1], pts[1:]):
            L = math.hypot(u1 - u0, v1 - v0)
            if L < 0.2:
                continue
            k = max(1, int(math.ceil(L / 7.0)))
            for i in range(k):
                a, b = i / k, (i + 1) / k
                ua, va = u0 + (u1 - u0) * a, v0 + (v1 - v0) * a
                ub, vb = u0 + (u1 - u0) * b, v0 + (v1 - v0) * b
                self.patch(surface, (ua + ub) / 2, (va + vb) / 2, math.degrees(math.atan2(vb - va, ub - ua)),
                           math.hypot(ub - ua, vb - va) + width, width, strength, 'capsule', order)
        return pts

    def on_lane(self, u, v, margin=0.4):
        for ln in self.lanes:
            pts = ln['pts']
            for a, b in zip(pts[:-1], pts[1:]):
                if seg_dist((u, v), a, b) < ln['width'] / 2 + margin:
                    return True
        return False

    def near_door(self, u, v, r=1.1):
        return any(math.hypot(u - d[0], v - d[1]) < r for d in self.doors)

    def standing_segments(self):
        return [((w[0], w[1]), (w[2], w[3])) for w in self.walls if w[4] in STANDING]

    def clear_of_walls(self, a, b, clear):
        return all(seg_seg_dist(a, b, p, q) >= clear for p, q in self.standing_segments())

    # -- wall pieces
    def wall_piece(self, a, b, state, block, group, face_out, ref_stem='w'):
        """One 3 m piece on the edge a->b (site metres) in this decay state. face_out: unit normal outward."""
        u, v = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        ang = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
        if state == 'lintel' and not self.lintel_door(a, b, block, group, face_out, ref_stem):
            state = 'door'                   # the jambs could not be levelled on this slope: an arch instead
        self.walls.append((a[0], a[1], b[0], b[1], state, block))
        if state == 'opening':
            return
        if state == 'gap':
            self.collapse(u, v, face_out, 1.0, ang)
            return
        if state == 'lintel':
            self.collapse(u, v, face_out, SHED['lintel'], ang)
            return
        key, scale, (s0, s1) = self.rng.choice(PALETTE[state])
        flip = 180.0 if (self.rng.random() < 0.5 and state not in ('door', 'gate')) else 0.0
        yaw = ang - (90.0 if long_axis_y(key) else 0.0) + flip
        sink = self.rng.uniform(s0, s1)
        _, _, H = piece_dims(key, scale)
        self.add(key, u, v, yaw, group, 'rigid', scale=scale, block=block, sink_cm=round(sink, 1),
                 material_set='stone', state=state, vis_h=round(H - sink / 100.0, 2))
        self.collapse(u, v, face_out, SHED[state], ang)

    def wall_line(self, a, b, states, block, group, face_out):
        """Pieces along a->b (site metres), one per state (a free-standing run: yard walls, fragments).
        Pieces are the kit's fixed 3 m: on a line that is not a multiple of 3 m they stand with small broken
        joints between them, never overlapping (collinear overlapping faces z-fight)."""
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        n = min(len(states), max(1, int(L / PIECE_M + 0.02)))
        step, h = L / n, PIECE_M / 2.0 / L
        for i, stt in enumerate(states[:n]):
            tm = (i + 0.5) * step / L
            p = (a[0] + (b[0] - a[0]) * (tm - h), a[1] + (b[1] - a[1]) * (tm - h))
            q = (a[0] + (b[0] - a[0]) * (tm + h), a[1] + (b[1] - a[1]) * (tm + h))
            self.wall_piece(p, q, stt, block, group, face_out)

    def footprint_min(self, u, v, ang, lx, ly):
        """Lowest ground (m) under a plumb footprint lx x ly (m) at the settle's 9 samples (0.92 of the box)."""
        ca, sa = math.cos(math.radians(ang)), math.sin(math.radians(ang))
        zs = []
        for a in (-0.46, 0.0, 0.46):
            for b in (-0.46, 0.0, 0.46):
                zs.append(self.F.g(u + ca * a * lx - sa * b * ly, v + sa * a * lx + ca * b * ly))
        return min(zs)

    def lintel_door(self, a, b, block, group, face_out, ref_stem):
        """A doorway with a timber lintel: two stone jambs (rigid) and the beam carried by both (contact 'bear').
        The wall above the lintel has come down, so the doorway stands in the broken wall on its own.
        The jambs are sunk so that their TOPS are level (the uphill one deeper): a lintel on uneven jambs
        would see-saw. Where that needs more than MAX_JAMB_STEP of extra sink, there is no lintel (False)."""
        u, v = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        tu, tv = (b[0] - a[0]) / L, (b[1] - a[1]) / L
        ang = math.degrees(math.atan2(tv, tu))
        jkey = self.rng.choice(JAMBS)
        jx, jy, jh = [c / 100.0 for c in CAT[jkey]['size_cm']]
        pos = [(u + tu * JAMB_OFF * s_, v + tv * JAMB_OFF * s_) for s_ in (-1, 1)]
        g = [self.footprint_min(p[0], p[1], ang, jx, jy) for p in pos]
        if max(g) - min(g) > MAX_JAMB_STEP:
            return False
        refs = []
        for (pu, pv), gi in zip(pos, g):
            r = self.ref(ref_stem + '_jamb')
            refs.append(r)
            sink = JAMB_SINK + (gi - min(g)) * 100.0
            # the jamb's thin side (local X, 0.62 m) along the wall, so the opening stays wide
            self.add(jkey, pu, pv, ang, group, 'rigid', block=block, sink_cm=round(sink, 1), material_set='stone',
                     ref=r, state='jamb', vis_h=round(jh - sink / 100.0, 2))
        rb = self.ref(ref_stem + '_lintel')
        key, sc = LINTEL
        self.add(key, u, v, ang + self.rng.uniform(-1.5, 1.5), group, 'bear', scale=sc, block=block,
                 material_set='wood', ref=rb, bears_on=refs, state='lintel', drop_cm=0,
                 note='lintel carried by its two jambs (tops levelled offline)')
        self.lintels.append((rb, refs[0], refs[1], u, v, ang))
        return True

    def collapse(self, u, v, face_out, amount, wall_ang):
        """Rubble from a broken piece: it falls to the downhill side of the wall and fans down the slope."""
        du, dv = self.F.downhill(u, v)
        side = 1.0 if (face_out[0] * du + face_out[1] * dv) >= 0 else -1.0
        # a wall running down the fall line sheds to both sides; one that faces downhill sheds downhill
        fu, fv = face_out[0] * side + du * 0.8, face_out[1] * side + dv * 0.8
        n = math.hypot(fu, fv) or 1.0
        fu, fv = fu / n, fv / n
        self.fans.append((u, v, fu, fv, amount))
        grp = 'rubble'
        if amount >= 0.95:
            # the heap: one rubble01 block pile lying against the wall line (kept off the lanes)
            hu, hv = u + fu * 1.1, v + fv * 1.1
            if not self.on_lane(hu, hv, 0.9) and not self.near_door(hu, hv, 1.8):
                self.add('B01_rubble01', hu, hv, wall_ang + self.rng.uniform(-12, 12), grp, 'lie',
                         scale=self.rng.uniform(0.75, 1.0), sink_cm=30, material_set='stone', block='fan')
        if amount >= 0.45:
            for _ in range(1 + int(amount >= 0.95)):
                d = self.rng.uniform(1.2, 2.8)
                self.add(self.rng.choice(CHUNKS), u + fu * d + self.rng.uniform(-0.8, 0.8),
                         v + fv * d + self.rng.uniform(-0.8, 0.8), self.rng.uniform(0, 360), 'chunks_ism', ism=True,
                         scale=(0.8, 1.1), settle_over=CHUNK_SETTLE, block='fan')
        self.scatter_fan(u, v, fu, fv, wall_ang, int(round(3 + 11 * amount)), 0.6 + 1.6 * amount, 35.0, 1.4)
        if amount >= 0.45:
            L = 2.6 + 3.6 * amount
            self.patch('rubble_dust', u + fu * L * 0.38, v + fv * L * 0.38, math.degrees(math.atan2(fv, fu)), L,
                       2.3 + 1.6 * amount, 0.7 + 0.3 * amount, 'ellipse', order=1)

    def scatter_fan(self, u, v, fu, fv, wall_ang, n, mean_d, spread_deg, lat_m, max_d=4.5):
        """Bricks, cobbles and small stones in a fan: exponential fall-off, +-spread, lateral along the wall."""
        wu, wv = math.cos(math.radians(wall_ang)), math.sin(math.radians(wall_ang))
        for _ in range(n):
            d = min(max_d, 0.25 + self.rng.expovariate(1.0 / mean_d))
            a = math.radians(self.rng.uniform(-spread_deg, spread_deg))
            cu, cv = fu * math.cos(a) - fv * math.sin(a), fu * math.sin(a) + fv * math.cos(a)
            lat = self.rng.uniform(-lat_m, lat_m)
            pu, pv = u + cu * d + wu * lat, v + cv * d + wv * lat
            if (self.on_lane(pu, pv, 0.1) or self.near_door(pu, pv, 0.9)) and self.rng.random() < 0.85:
                continue     # swept off the used lanes and thresholds
            r = self.rng.random()
            key = self.rng.choice(BRICKS if r < 0.45 else (STONES if r < 0.75 else COBBLES))
            self.add(key, pu, pv, self.rng.uniform(0, 360), 'rubble_ism', scale=(0.7, 1.4), ism=True,
                     settle_over=RUBBLE_SETTLE, composed=True, block='fan')

    def collapse_corner(self, u, v, out_u, out_v, wall_ang):
        """A whole corner has come down: a big fan downhill of the corner (two heaps, chunks, a spray of
        bricks and stones, a large dust patch)."""
        du, dv = self.F.downhill(u, v)
        # the corner falls outward but the heap rolls on down the slope: downhill dominates (an uphill-facing
        # corner still spills downhill, past its own foot)
        fu, fv = out_u + du * 1.6, out_v + dv * 1.6
        n = math.hypot(fu, fv) or 1.0
        fu, fv = fu / n, fv / n
        self.fans.append((u, v, fu, fv, 1.4))
        self.corner_falls.append((u, v, fu, fv))
        for d, sc in ((1.3, (0.85, 1.1)), (3.0, (0.55, 0.75))):
            hu, hv = u + fu * d, v + fv * d
            if self.on_lane(hu, hv, 0.9) or self.near_door(hu, hv, 1.8):
                continue
            self.add('B01_rubble01', hu, hv, wall_ang + 45 + self.rng.uniform(-20, 20), 'rubble', 'lie',
                     scale=self.rng.uniform(*sc), sink_cm=32, material_set='stone', block='fan')
        for _ in range(3):
            d = self.rng.uniform(1.0, 3.5)
            self.add(self.rng.choice(CHUNKS), u + fu * d + self.rng.uniform(-1, 1), v + fv * d + self.rng.uniform(-1, 1),
                     self.rng.uniform(0, 360), 'chunks_ism', ism=True, scale=(0.8, 1.2), settle_over=CHUNK_SETTLE,
                     block='fan')
        self.scatter_fan(u, v, fu, fv, wall_ang, 22, 1.8, 50.0, 1.2, max_d=6.0)
        self.patch('rubble_dust', u + fu * 2.6, v + fv * 2.6, math.degrees(math.atan2(fv, fu)), 7.0, 4.8, 1.0,
                   'ellipse', order=1)

    # -- blocks of rooms
    def block(self, name, u0, v0, ang, rooms, decay, group='houses', keep_back=0.25, doors=True,
              collapse_corners=1, tall_back=None, front_fallen=False, lintel_p=0.45, tall_p=0.0,
              court=None, tall_all=False, door_state=None, open_court=False, breaches=None,
              foundation=False, foundation_keep=()):
        """Rooms of 3 m cells on one terrace frame (x along ang, y into the slope = uphill).
        rooms: a list of cell lists [(i, j), ...]; a room need not be a rectangle (an L, a missing corner).
        Every cell edge between a room and the outside or another room carries one wall piece; a party wall
        between two rooms is emitted once. tall_back=(i0, i1): the back edges x in [i0, i1) are ONE tall
        surviving wall (AB_Broken_Arch_Wall); front_fallen: the whole front has come down (the entrance).
        court: cells of an inner court (a caravanserai): edges onto it are the fronts (the doors open onto it),
        every other outside edge is a back wall. tall_all: standing pieces are the tall Fort wall (a keep, a
        curtain). door_state: the door piece ('gate' = the big arch). open_court: the rooms are yards, not
        roofless rooms (packed earth, no floor dust, no fallen roof beams)."""
        self.nblock += 1
        blk = '%s_%d' % (name, self.nblock)
        self.last_block = blk
        court = set(court or ())
        ca, sa = math.cos(math.radians(ang)), math.sin(math.radians(ang))
        bu, bv = -sa, ca                    # uphill (the back) is +90 deg from ang

        def P(x, y):                        # cell units -> site metres
            return (u0 + (ca * x + bu * y) * PIECE_M, v0 + (sa * x + bv * y) * PIECE_M)

        def D(dx, dy):                      # a cell-frame direction -> site unit vector
            return (ca * dx + bu * dy, sa * dx + bv * dy)
        own = {c: k for k, cells in enumerate(rooms) for c in cells}
        edges, order = {}, []
        for (i, j) in sorted(own):
            k = own[(i, j)]
            for di, dj, kind in ((0, -1, 'front'), (0, 1, 'back'), (-1, 0, 'end'), (1, 0, 'end')):
                kb = own.get((i + di, j + dj))
                if kb == k:
                    continue
                if dj == -1:
                    a, b = (i, j), (i + 1, j)
                elif dj == 1:
                    a, b = (i, j + 1), (i + 1, j + 1)
                elif di == -1:
                    a, b = (i, j), (i, j + 1)
                else:
                    a, b = (i + 1, j), (i + 1, j + 1)
                if (a, b) in edges:
                    continue
                if kb is None and court:
                    kind = 'front' if (i + di, j + dj) in court else 'back'
                edges[(a, b)] = dict(a=a, b=b, kind=kind if kb is None else 'party', ra=k, rb=kb, out=(di, dj))
                order.append((a, b))
        # corner vertices: where a horizontal and a vertical wall edge meet
        inc = {}
        for key in order:
            a, b = key
            o = 'h' if a[1] == b[1] else 'v'
            for p in (a, b):
                inc.setdefault(p, []).append((key, o))
        corner_v = {p for p, es in inc.items() if {'h', 'v'} <= {o for _, o in es}}
        # decay per edge: downhill-facing and site-edge pieces fall more, corners and back walls hold
        state = {}
        for key in order:
            e = edges[key]
            (ax_, ay_), (bx_, by_) = e['a'], e['b']
            mu, mv = P((ax_ + bx_) / 2, (ay_ + by_) / 2)
            fo = D(*e['out'])
            du, dv = self.F.downhill(mu, mv)
            downhill_face = max(0.0, fo[0] * du + fo[1] * dv) if e['kind'] != 'party' else 0.0
            corner = 1.0 if (e['a'] in corner_v or e['b'] in corner_v) else 0.0
            edge = min(1.0, max(0.0, (math.hypot(mu - self.cu, mv - self.cv) - 18.0) / 30.0))
            keep = {'back': keep_back, 'party': 0.1}.get(e['kind'], 0.0)
            p = 0.18 * decay + 0.3 * downhill_face + 0.25 * edge - 0.18 * corner - keep + self.rng.uniform(-0.2, 0.2)
            st = 'full' if p < 0.22 else 'damaged' if p < 0.42 else 'low' if p < 0.58 else 'stump' if p < 0.78 else 'gap'
            if st == 'full' and e['kind'] == 'back' and self.rng.random() < tall_p:
                st = 'tall'
            if tall_all and st in ('full', 'damaged'):
                st = 'tall'
            if front_fallen and e['kind'] == 'front':
                st = 'gap'
            state[key] = st
        # doors: one per room, on an outside front edge (else an end edge; else an opening to its neighbour)
        room_door = {}
        door_v = set()
        for k in range(len(rooms)):
            if not doors:
                break
            if front_fallen:
                fronts = [x for x in order if edges[x]['ra'] == k and edges[x]['kind'] == 'front']
                if fronts:
                    room_door[k] = fronts[len(fronts) // 2]
                continue
            cand = [x for x in order if edges[x]['ra'] == k and edges[x]['kind'] == 'front'] or \
                [x for x in order if edges[x]['ra'] == k and edges[x]['kind'] == 'end']
            if cand:
                # two doors never share a corner (an arch and a lintel doorway at one corner interpenetrate)
                free = [x for x in cand if not (set(x) & door_v)]
                d = self.rng.choice(free or cand)
                door_v |= set(d)
                room_door[k] = d
                state[d] = door_state or ('lintel' if self.rng.random() < lintel_p else 'door')
                wins = [x for x in cand if x != d and state[x] in ('full', 'damaged')]
                if wins and self.rng.random() < 0.6:
                    state[self.rng.choice(wins)] = 'window'
            else:
                party = [x for x in order if k in (edges[x]['ra'], edges[x]['rb']) and edges[x]['kind'] == 'party']
                if party:
                    state[self.rng.choice(party)] = 'opening'
        # collapsed corners: whole outside corners come down (downhill and edge-of-site corners first)
        protected = set(room_door.values())
        cands = []
        for p in corner_v:
            es = inc[p]
            if len(es) != 2 or any(edges[k_]['kind'] == 'party' or k_ in protected or state[k_] in ('door', 'lintel', 'window', 'gate')
                                   for k_, _ in es):
                continue
            # the corner's outward diagonal: away from the cells of the block that touch it
            touch = [c for c in ((p[0] - 1, p[1] - 1), (p[0], p[1] - 1), (p[0] - 1, p[1]), (p[0], p[1])) if c in own]
            if len(touch) != 1:
                continue
            ox, oy = p[0] - (touch[0][0] + 0.5), p[1] - (touch[0][1] + 0.5)
            o = D(ox, oy)
            vu, vv = P(*p)
            du, dv = self.F.downhill(vu, vv)
            score = (o[0] * du + o[1] * dv) / math.hypot(*o) + 0.02 * math.hypot(vu - self.cu, vv - self.cv) + \
                self.rng.uniform(0, 0.5)
            cands.append((score, p, o))
        cands.sort(reverse=True)
        falls = []
        for score, p, o in cands[:collapse_corners]:
            for k_, orient in inc[p]:
                state[k_] = 'gap'
                # the next piece along each wall line steps down (a stepped collapse, not a clean cut)
                a, b = k_
                far = b if a == p else a
                nxt = [x for x, o2 in inc.get(far, []) if o2 == orient and x != k_]
                for x in nxt:
                    if state.get(x) in ('full', 'damaged', 'tall'):
                        state[x] = self.rng.choice(['low', 'stump'])
            falls.append((p, o))
        # A ruin can lose a whole wall run while retaining its party walls and doorways.  The S07
        # prototype uses these authored breaches to interrupt the otherwise repeated box skyline.
        for a, b, replacement in breaches or ():
            key = (tuple(a), tuple(b))
            if key not in state or key in protected or replacement not in ('gap', 'low', 'stump'):
                raise ValueError('invalid or protected breach %s in %s' % (key, name))
            state[key] = replacement
        if foundation:
            # A whole terrace of full-height room shells reads as roofless cuboids from the road.
            # Preserve selected wall fragments as landmarks; the rest have slumped to low footings.
            keep = {(tuple(a), tuple(b)) for a, b in foundation_keep}
            for key, st in state.items():
                if key not in keep and st in ('full', 'damaged', 'tall', 'window'):
                    state[key] = 'low' if (key[0][0] + key[0][1]) % 2 else 'stump'
        # a lintel doorway needs thin walls at its corners: next to a perpendicular arch, window or Fort piece
        # (0.3-0.9 m thick) its jamb and beam end would sit inside that piece, so it becomes an arch door
        for key in order:
            if state[key] != 'lintel':
                continue
            horiz = key[0][1] == key[1][1]
            for p in key:
                for k2, o2 in inc.get(p, []):
                    if k2 != key and (o2 == 'h') != horiz and state.get(k2) in ('door', 'window', 'gate', 'lintel', 'tall'):
                        state[key] = 'door'
        # tall surviving back wall
        merged = set()
        if tall_back:
            i0, i1 = tall_back
            jb = max(j for (i, j) in own if i0 <= i < i1)
            for i in range(i0, i1):
                if ((i, jb + 1), (i + 1, jb + 1)) in edges:
                    merged.add(((i, jb + 1), (i + 1, jb + 1)))
        # emit
        for key in order:
            if key in merged:
                continue
            e = edges[key]
            fo = D(*e['out'])
            self.wall_piece(P(*e['a']), P(*e['b']), state[key], blk, group, fo, ref_stem='%s_e%d' % (blk, len(self.walls)))
        if merged:
            xs = sorted(k_[0][0] for k_ in merged)
            jb1 = min(merged)[0][1]
            a, b = P(xs[0], jb1), P(xs[-1] + 1, jb1)
            for key in sorted(merged):
                self.walls.append(P(*key[0]) + P(*key[1]) + ('tallruin', blk))
            u, v = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
            H = CAT[TALL_RUIN]['size_cm'][2] / 100.0
            self.add(TALL_RUIN, u, v, ang + (180.0 if self.rng.random() < 0.5 else 0.0), group, 'rigid', block=blk,
                     sink_cm=30, material_set='stone', state='tallruin', vis_h=round(H - 0.3, 2),
                     note='the surviving gable of a two-storey house')
            self.collapse(u, v, D(0, 1), SHED['tallruin'], ang)
        for p, o in falls:
            u, v = P(*p)
            n = math.hypot(*o)
            self.collapse_corner(u, v, o[0] / n, o[1] / n, ang)
        # doors (after emission: the lintel/arch piece is placed; spurs and aprons come later)
        for k, key in room_door.items():
            e = edges[key]
            (ax_, ay_), (bx_, by_) = e['a'], e['b']
            du_, dv_ = P((ax_ + bx_) / 2, (ay_ + by_) / 2)
            fo = D(*e['out'])
            self.doors.append((du_, dv_, name, k, fo[0], fo[1]))
        # rooms
        for k, cells in enumerate(rooms):
            quads = [[P(i, j), P(i + 1, j), P(i + 1, j + 1), P(i, j + 1)] for (i, j) in cells]
            cs = [P(i + 0.5, j + 0.5) for (i, j) in cells]
            bnd = [x for x in order if k in (edges[x]['ra'], edges[x]['rb'])]
            vs = {}
            for x in bnd:
                o = 'h' if x[0][1] == x[1][1] else 'v'
                for p in x:
                    vs.setdefault(p, set()).add(o)
            corners = []
            for p, os_ in sorted(vs.items()):
                if os_ != {'h', 'v'}:
                    continue
                touch = [c for c in ((p[0] - 1, p[1] - 1), (p[0], p[1] - 1), (p[0] - 1, p[1]), (p[0], p[1])) if own.get(c) == k]
                if not touch:
                    continue
                ix = sum(c[0] + 0.5 for c in touch) / len(touch) - p[0]
                iy = sum(c[1] + 0.5 for c in touch) / len(touch) - p[1]
                n = math.hypot(ix, iy) or 1.0
                corners.append(dict(at=P(*p), inset=P(p[0] + ix / n * 0.17, p[1] + iy / n * 0.17), concave=len(touch) == 3))
            ii = [c[0] for c in cells]
            jj = [c[1] for c in cells]
            self.rooms.append(dict(block=blk, name=name, cells=quads, centres=cs, corners=corners,
                                   centre=(sum(c[0] for c in cs) / len(cs), sum(c[1] for c in cs) / len(cs)),
                                   w=(max(ii) - min(ii) + 1) * PIECE_M, d=(max(jj) - min(jj) + 1) * PIECE_M,
                                   n_cells=len(cells), rect=len(cells) == (max(ii) - min(ii) + 1) * (max(jj) - min(jj) + 1),
                                   ang=ang, group=group, court=open_court))
        imin, jmin = min(i for i, _ in own), min(j for _, j in own)
        imax = max(i for i, _ in own) + 1
        jmax = max(j for _, j in own) + 1
        self.rows.append(dict(name=name, block=blk, u0=u0, v0=v0, ang=ang, cells=sorted(own), rooms=len(rooms),
                              group=group, front=[P(imin, jmin), P(imax, jmin)], back=[P(imin, jmax), P(imax, jmax)]))
        return P

    def row(self, name, u0, v0, ang, widths, depth, decay, doors_front=True, keep_back=0.25, group='houses', **kw):
        """Rectangular rooms side by side (widths: pieces wide, or (wide, deep)) as a block."""
        rooms, x = [], 0
        for w in widths:
            wd, dp = (w, depth) if isinstance(w, int) else w
            rooms.append(rect(x, 0, wd, dp))
            x += wd
        return self.block(name, u0, v0, ang, rooms, decay, group=group, keep_back=keep_back, doors=doors_front, **kw)

    def meander(self, pts, amp, step=3.5):
        """A lane is walked, not ruled: subdivide and wander sideways (smooth random walk, ends fixed)."""
        out = [pts[0]]
        off = 0.0
        for (u0, v0), (u1, v1) in zip(pts[:-1], pts[1:]):
            L = math.hypot(u1 - u0, v1 - v0)
            n = max(1, int(round(L / step)))
            nu, nv = -(v1 - v0) / (L or 1.0), (u1 - u0) / (L or 1.0)
            for i in range(1, n + 1):
                t = i / n
                last = (i == n)
                off = 0.0 if last else max(-amp, min(amp, 0.6 * off + self.rng.uniform(-amp, amp)))
                out.append((u0 + (u1 - u0) * t + nu * off, v0 + (v1 - v0) * t + nv * off))
        return out

    def terrace_wall(self, pts, group='terraces', gap_every=None, name='terrace', sink=35, record=False, state='terrace'):
        """A dry-stone terrace edge along a contour polyline: low wall02 courses, jittered, with gaps that come in
        clusters (a slumped stretch), not one every n pieces. record: also list the courses in self.walls (yard
        walls: the beams, rubble band and creep then know them; field terraces stay out of the core metrics)."""
        self.nblock += 1
        blk = '%s_%d' % (name, self.nblock)
        key = DRYSTONE
        L, _, _ = piece_dims(key)
        in_gap = False
        for (u0, v0), (u1, v1) in zip(pts[:-1], pts[1:]):
            seg = math.hypot(u1 - u0, v1 - v0)
            # a field terrace rounds to whole courses; a yard wall only lays courses that fit inside the run
            # (a course overhanging a short return would reach past the checked line, into the house it abuts)
            k = int(seg / (L * 0.98)) if record else max(1, int(round(seg / (L * 0.96))))
            ang = math.degrees(math.atan2(v1 - v0, u1 - u0))
            for i in range(k):
                t = (i + 0.5 + (self.rng.uniform(-0.08, 0.08) if not record else 0.0)) / k
                u, v = u0 + (u1 - u0) * t, v0 + (v1 - v0) * t
                if gap_every:
                    in_gap = self.rng.random() < (0.55 if in_gap else gap_every)
                ca_, sa_ = math.cos(math.radians(ang)), math.sin(math.radians(ang))
                if record:
                    self.walls.append((u - ca_ * L / 2, v - sa_ * L / 2, u + ca_ * L / 2, v + sa_ * L / 2,
                                       'gap' if in_gap else state, blk))
                if in_gap:
                    if self.rng.random() < 0.6:
                        self.collapse(u, v, self.F.downhill(u, v), 0.5, ang)
                    continue
                self.add(key, u, v, ang + self.rng.uniform(-5, 5), group, 'rigid', block=blk, sink_cm=sink,
                         material_set='stone', state=state, vis_h=round(piece_dims(key)[2] - sink / 100.0, 2))
        return blk

    # -- planning: does a footprint fit before anything is placed?
    def quads(self, u0, v0, ang, cells):
        """Cell quads (site m) of a planned block, the same frame as block()."""
        ca, sa = math.cos(math.radians(ang)), math.sin(math.radians(ang))

        def P(x, y):
            return (u0 + (ca * x - sa * y) * PIECE_M, v0 + (sa * x + ca * y) * PIECE_M)
        return [[P(i, j), P(i + 1, j), P(i + 1, j + 1), P(i, j + 1)] for (i, j) in cells]

    def point_clear(self, u, v, margin=0.6, lane_margin=0.6, road_m=7.0, ignore_block=None, door_r=1.6):
        """(u, v) is off every room (by margin), lane, threshold, placed solid, the road core, and inside the site."""
        if math.hypot(u, v) > self.s.radius_m:
            return False
        if self.F.road_dist(u, v) < road_m:
            return False
        if self.on_lane(u, v, lane_margin) or self.near_door(u, v, door_r):
            return False
        for rm in self.rooms:
            for q in rm['cells']:
                if quad_dist((u, v), q) < margin:
                    return False
        for (su, sv, r, blk) in self.solids:
            if ignore_block is not None and blk == ignore_block:
                continue
            if math.hypot(u - su, v - sv) < r + margin:
                return False
        return True

    def fits(self, quads, margin=1.0):
        """A planned block (its cell quads) keeps margin from every room, lane, solid and the road core."""
        for q in quads:
            for p in quad_samples(q, 0.75):
                if not self.point_clear(p[0], p[1], margin, 0.45):
                    return False
            for rm in self.rooms:
                for q2 in rm['cells']:
                    if quad_quad_dist(q, q2) < margin:
                        return False
        return True

    def seg_clear(self, a, b, skip_start=0.0, ignore_block=None, margin=0.6, anchor=None):
        """Samples along a->b are clear (point_clear). anchor=(p0, block): a wall that starts at a block's corner
        ignores that block's pieces only within 1.6 m of p0 (the stub leaving the corner), not beyond."""
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        n = max(2, int(L / 0.5))
        for k in range(n + 1):
            t = k / n
            if t * L < skip_start:
                continue
            x, y = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
            ib = ignore_block
            if anchor is not None:
                ib = anchor[1] if math.hypot(x - anchor[0][0], y - anchor[0][1]) < 1.6 else None
            if not self.point_clear(x, y, margin, 0.8, ignore_block=ib):
                return False
        for y in self.yards:
            for p, q in zip(y['pts'][:-1], y['pts'][1:]):
                if seg_seg_dist(a, b, p, q) < 1.2:
                    return False
        return True

    # -- yards: low dry-stone enclosures off the rooms, at angles off the block grid
    def yard(self, pts, gap_every=0.16, contents=(), group='yards', anchor=None):
        """A walled yard along the polyline pts (its open side is the gate): dry-stone courses (recorded as walls,
        so the beams, the rubble band and the creep know them), packed earth inside, a manger or a trough."""
        blk = self.terrace_wall(pts, group=group, gap_every=gap_every, name='yard', sink=25, record=True,
                                state='drystone')
        cu = sum(p[0] for p in pts) / len(pts)
        cv = sum(p[1] for p in pts) / len(pts)
        a = math.degrees(math.atan2(pts[1][1] - pts[0][1], pts[1][0] - pts[0][0]))
        span = max(math.hypot(p[0] - cu, p[1] - cv) for p in pts)
        self.patch('packed_earth', cu, cv, a, span * 1.5, span * 1.15, 0.8, order=1)
        self.yards.append(dict(pts=[tuple(p) for p in pts], block=blk, anchor=anchor))
        for i, key in enumerate(contents):
            # toward the far wall, turned with it, only where its whole footprint keeps 0.7 m off every course
            p, q = pts[1 + i % (len(pts) - 1)], pts[min(len(pts) - 1, 2 + i % (len(pts) - 1))]
            mu, mv = (p[0] + q[0]) / 2, (p[1] + q[1]) / 2
            wa = math.degrees(math.atan2(q[1] - p[1], q[0] - p[0]))
            sx, sy = piece_dims(key)[:2]
            for f in (0.35, 0.15, 0.0):
                x, y = cu + (mu - cu) * f, cv + (mv - cv) * f
                fp = B.rect_corners(x, y, wa, sx, sy)       # the long side along the wall
                if all(seg_dist(c, a, b) > 0.7 for c in fp + [(x, y)] for a, b in zip(pts[:-1], pts[1:])):
                    self.add(key, x, y, wa - (90.0 if long_axis_y(key) else 0.0), group, 'rest', block=blk + '_c',
                             material_set='wood')
                    break
        return blk

    def yard_shape(self, row, corner, back):
        """A candidate yard beside a block end (or behind it): leave the corner, run out at 8-30 deg off the
        block's grid, turn, and come partly back (the gap left is the gate)."""
        r = self.rng
        ca, sa = math.cos(math.radians(row['ang'])), math.sin(math.radians(row['ang']))
        ex, ey = (ca, sa), (-sa, ca)
        p = corner
        sx = -1.0 if corner in (row['front'][0], row['back'][0]) else 1.0
        sy = -1.0 if corner in (row['back'][0], row['back'][1]) else 1.0
        if back:                              # behind the block: out uphill, along, back down
            d1, d2 = (ey[0], ey[1]), (-ex[0] * sx, -ex[1] * sx)
            p = corner if sy < 0 else None
            if p is None:
                return None
        else:                                 # beside the end wall: out along x, then along the end wall
            d1, d2 = (ex[0] * sx, ex[1] * sx), (ey[0] * sy, ey[1] * sy)
        a1 = math.radians(r.choice((-1, 1)) * r.uniform(8.0, 30.0))
        a2 = math.radians(r.uniform(-12.0, 12.0))
        L1, L2 = r.uniform(4.5, 8.0), r.uniform(4.0, 7.0)
        p0 = (p[0] + d1[0] * 0.9, p[1] + d1[1] * 0.9)
        u1 = rot(math.degrees(a1), *d1)
        p1 = (p0[0] + u1[0] * L1, p0[1] + u1[1] * L1)
        u2 = rot(math.degrees(a2), *d2)
        p2 = (p1[0] + u2[0] * L2, p1[1] + u2[1] * L2)
        back_to = (p0[0] + d2[0] * L2, p0[1] + d2[1] * L2)
        f = r.uniform(0.35, 0.65)
        p3 = (p2[0] + (back_to[0] - p2[0]) * f, p2[1] + (back_to[1] - p2[1]) * f)
        return [p0, p1, p2, p3]

    def auto_yards(self, n, contents=('MV_Manger', 'MV_wash_tub'), groups=('houses',)):
        """Up to n walled yards off the ends and backs of the blocks, where they fit (off lanes, rooms, solids)."""
        made, rows = 0, [r for r in self.rows if r.get('group') in groups]
        self.rng.shuffle(rows)
        for row in rows:
            if made >= n:
                break
            for corner in (row['front'][0], row['front'][1], row['back'][0], row['back'][1]):
                done = False
                for back in (False, True):
                    for _ in range(6):
                        pts = self.yard_shape(row, corner, back)
                        if pts is None:
                            break
                        ok = all(self.seg_clear(a, b, anchor=(pts[0], row['block']))
                                 for a, b in zip(pts[:-1], pts[1:]))
                        cu = sum(p[0] for p in pts) / 4
                        cv = sum(p[1] for p in pts) / 4
                        inner = [(cu + (p[0] - cu) * 0.5, cv + (p[1] - cv) * 0.5) for p in pts] + [(cu, cv)]
                        ok = ok and all(self.point_clear(a, b, 0.3, 0.4, ignore_block=row['block']) for a, b in inner)
                        if ok:
                            self.yard(pts, contents=contents[made % len(contents):][:1], anchor=row['block'])
                            made += 1
                            done = True
                            break
                    if done:
                        break
                if done:
                    break
        return made

    def find_spot(self, cands, r, margin=0.8):
        """The first candidate (u, v) whose disc of radius r is clear of rooms, lanes, solids and the road."""
        for (u, v) in cands:
            ring = [(u, v)] + [(u + rr * math.cos(a), v + rr * math.sin(a))
                               for rr in (r * 0.5, r) for a in np.linspace(0, 2 * math.pi, 12, endpoint=False)]
            if all(self.point_clear(a, b, margin, 0.8) for a, b in ring):
                return (u, v)
        return None

    # -- links, ground marks
    def door_spurs(self, width=1.3, strength=0.95):
        """A worn spur from every door to its lane (the block's own lane, else the nearest lane point in front)."""
        for (du, dv, name, k, fu, fv) in list(self.doors):
            ln = self.block_lane.get(name)
            cands = [ln] if ln else [x['pts'] for x in self.lanes]
            best = None
            for pts in cands:
                for q in pts:
                    if (q[0] - du) * fu + (q[1] - dv) * fv < -0.3:
                        continue                 # never back through the room
                    d = math.hypot(q[0] - du, q[1] - dv)
                    if best is None or d < best[0]:
                        best = (d, q)
            if best is not None and best[0] > 0.3:
                self.path([(du, dv), best[1]], width, strength=strength)

    def road_link(self, width=3.0, max_len=45.0, strength=1.0):
        """The worn path from the road verge to the nearest lane, with a trodden apron where it leaves the road.
        A lone site far off the road gets a track that fades out toward it (max_len)."""
        W = self.F.W
        best = None
        for ln in self.lanes:
            for p in ln['pts']:
                d, q = W.road_distance([self.F.world(*p)])
                if best is None or d < best[0]:
                    best = (d, p, q)
        d, lp, q = best
        qu, qv = self.F.site(float(q[0]), float(q[1]))
        du, dv = lp[0] - qu, lp[1] - qv
        n = math.hypot(du, dv) or 1.0
        du, dv = du / n, dv / n
        far = d - 6.5 > max_len
        start = (lp[0] - du * max_len, lp[1] - dv * max_len) if far else (qu + du * 6.5, qv + dv * 6.5)
        if not far:
            self.patch('packed_earth', start[0] + du * 1.5, start[1] + dv * 1.5, math.degrees(math.atan2(dv, du)),
                       7.0, 5.5, 0.9, order=1)
        return self.path([start, lp], width, wander=0.5, strength=0.7 if far else strength)

    def soot_rooms(self, n):
        """Burnt rooms: soot on the floor against a wall and a smear out of the doorway."""
        rooms = [r for r in self.rooms if r['n_cells'] >= 2 and not r.get('court') and r.get('group') != 'outskirts']
        self.rng.shuffle(rooms)
        for rm in rooms[:n]:
            cu, cv = self.rng.choice(rm['centres'])
            self.patch('soot', cu + self.rng.uniform(-0.6, 0.6), cv + self.rng.uniform(-0.6, 0.6),
                       rm['ang'] + self.rng.uniform(-20, 20), 3.2, 2.2, 0.9, order=4)
            self.meta.setdefault('burnt', []).append(rm['block'])

    def low_mud(self, n=3):
        """Dry mud where rain water stood: the lowest points of the lanes (a dip lower than both sides)."""
        dips = []
        for ln in self.lanes:
            pts = ln['pts']
            if len(pts) < 3:
                continue
            z = [self.F.g(*p) for p in pts]
            for i in range(len(pts)):
                nb = [z[k] for k in (i - 1, i + 1) if 0 <= k < len(pts)]
                if z[i] <= min(nb) and all(math.hypot(pts[i][0] - d[1][0], pts[i][1] - d[1][1]) > 6.0 for d in dips):
                    dips.append((min(nb) - z[i] + (0.0 if len(nb) == 2 else -0.02), pts[i], ln['width']))
        dips.sort(reverse=True)
        for depth, (u, v), w in dips[:n]:
            self.patch('dry_mud', u, v, self.rng.uniform(0, 180), w + 2.2, w + 1.0, 0.85, order=2)

    def finish(self, sp):
        """The dressing passes every archetype shares, then the layout record (site.v2)."""
        self.floors()
        self.door_ground()
        self.soot_rooms(sp.get('burnt', 1))
        self.low_mud(sp.get('mud', 3))
        self.fallen_beams()
        self.base_band()
        self.creep(sp.get('creep_edge', 30))
        self.sweep(lambda u, v: self.on_lane(u, v, 0.05) or self.near_door(u, v, 0.8))
        s = self.s
        s.v2 = dict(rows=self.rows, lanes=self.lanes, doors=self.doors, fans=self.fans, walls=self.walls,
                    rooms=self.rooms, units=self.units, core=(self.cu, self.cv), beams=self.beams,
                    lintels=self.lintels, corner_falls=self.corner_falls, yards=self.yards,
                    core_blocks=sorted({r['block'] for r in self.rows if r.get('group') == 'houses'}),
                    archetype=sp.get('archetype'))
        s.v2.update(self.meta)
        s.ground = self.ground
        s.units = self.units
        s.frame = self.F
        return s

    # -- dressing passes (after the blocks and lanes)
    def fallen_beams(self):
        """Roof beams that came down with the roofs: lying inside the rooms (or out through a fallen wall),
        never through a standing piece, off the lanes and the thresholds."""
        for rm in self.rooms:
            if rm['n_cells'] < 2 or rm.get('group') == 'outskirts' or rm.get('court'):
                continue
            want = 1 if rm['n_cells'] == 2 else 2
            if self.rng.random() > 0.85:
                continue
            placed = 0
            for _ in range(60):
                if placed >= want:
                    break
                key, pitch, L = self.rng.choice(BEAMS)
                cu, cv = self.rng.choice(rm['centres'])
                cu += self.rng.uniform(-0.8, 0.8)
                cv += self.rng.uniform(-0.8, 0.8)
                th = math.radians(rm['ang'] + self.rng.choice([0.0, 90.0]) + self.rng.uniform(-28, 28))
                a = (cu - math.cos(th) * L / 2, cv - math.sin(th) * L / 2)
                b = (cu + math.cos(th) * L / 2, cv + math.sin(th) * L / 2)
                if not self.clear_of_walls(a, b, 0.45):
                    continue
                if any(seg_seg_dist(a, b, (x[0], x[1]), (x[2], x[3])) < 0.35 for x in self.beams):
                    continue
                if self.on_lane(cu, cv, 0.3) or self.near_door(cu, cv, 1.3):
                    continue
                self.beams.append((a[0], a[1], b[0], b[1]))
                self.add(key, cu, cv, math.degrees(th), 'beams', 'lie', pitch=pitch, roll=self.rng.uniform(-8, 8),
                         sink_cm=6, material_set='wood', block='beam', note='fallen roof beam')
                placed += 1

    def base_band(self):
        """Dense small stones hugging every standing wall base (mostly on the downhill face) and clumps in the
        inside corners of every room: the walls grow out of their own debris, not out of clean ground."""
        n_by = {'full': (3, 5), 'tall': (3, 5), 'window': (3, 5), 'door': (2, 3), 'lintel': (2, 3), 'tallruin': (6, 9),
                'damaged': (5, 8), 'low': (5, 8), 'stump': (6, 9), 'drystone': (2, 4), 'gate': (2, 3)}
        for (u0, v0, u1, v1, stt, blk) in self.walls:
            if stt not in n_by or blk.startswith('terrace'):
                continue
            ang = math.atan2(v1 - v0, u1 - u0)
            nu, nv = -math.sin(ang), math.cos(ang)
            du, dv = self.F.downhill((u0 + u1) / 2, (v0 + v1) / 2)
            bias = 1.0 if nu * du + nv * dv >= 0 else -1.0
            for _ in range(self.rng.randint(*n_by[stt])):
                t = self.rng.random()
                if stt in ('door', 'lintel', 'gate') and 0.2 < t < 0.8:
                    continue                 # the threshold stays clear
                side = bias if self.rng.random() < 0.7 else -bias
                off = side * min(0.8, 0.16 + self.rng.expovariate(1.0 / 0.2))
                u, v = u0 + (u1 - u0) * t + nu * off, v0 + (v1 - v0) * t + nv * off
                if self.on_lane(u, v, 0.0) or self.near_door(u, v, 0.8):
                    continue
                r = self.rng.random()
                key = self.rng.choice(STONES if r < 0.5 else (COBBLES if r < 0.8 else BRICKS))
                self.add(key, u, v, self.rng.uniform(0, 360), 'rubble_ism', scale=(0.6, 1.3), ism=True,
                         settle_over=RUBBLE_SETTLE, block='base')
        for rm in self.rooms:
            for c in rm['corners']:
                iu, iv = c['inset']
                for _ in range(self.rng.randint(3, 5)):
                    u, v = iu + self.rng.uniform(-0.35, 0.35), iv + self.rng.uniform(-0.35, 0.35)
                    if self.near_door(u, v, 0.8):
                        continue
                    self.add(self.rng.choice(STONES + COBBLES), u, v, self.rng.uniform(0, 360), 'rubble_ism',
                             scale=(0.6, 1.2), ism=True, settle_over=RUBBLE_SETTLE, block='base')

    def creep(self, n_edge=30):
        """Plants creeping back: dry tufts and dead shrubs in the room corners, across the floors of the roofless
        rooms, at the wall bases and over old rubble fans; never on a lane or a threshold."""
        placed = []

        def ok(u, v, sep):
            return (not self.on_lane(u, v, 0.4)) and not self.near_door(u, v, 1.0) and \
                all(math.hypot(u - a, v - b) > sep for a, b in placed)

        def plant(u, v, shrub):
            placed.append((u, v))
            if shrub:
                self.add(self.rng.choice(SHRUBS), u, v, self.rng.uniform(0, 360), 'creep', scale=(0.9, 1.6), ism=True,
                         block='creep')
            else:
                self.add(self.rng.choice(TUFTS), u, v, self.rng.uniform(0, 360), 'creep_grass', scale=(0.8, 1.3),
                         ism=True, block='creep')
        for rm in self.rooms:
            for c in rm['corners']:
                if self.rng.random() > 0.8:
                    continue
                iu, iv = c['inset']
                ax_, ay_ = c['at']
                du, dv = iu - ax_, iv - ay_
                n = math.hypot(du, dv) or 1.0
                du, dv = du / n, dv / n
                if self.rng.random() < 0.5 and ok(iu + du * 0.35, iv + dv * 0.35, 0.8):
                    plant(iu + du * 0.35, iv + dv * 0.35, True)
                for _ in range(self.rng.randint(2, 3)):
                    d = self.rng.uniform(0.25, 0.9)
                    u, v = iu + du * d + self.rng.uniform(-0.3, 0.3), iv + dv * d + self.rng.uniform(-0.3, 0.3)
                    if ok(u, v, 0.45):
                        plant(u, v, False)
            # across the floor: more in bigger rooms, clustered toward the walls (the lee holds the soil)
            for _ in range(int(round(rm['n_cells'] * self.rng.uniform(1.2, 2.0)))):
                cu, cv = self.rng.choice(rm['centres'])
                r = PIECE_M * 0.5 - 0.45
                u, v = cu + self.rng.uniform(-r, r), cv + self.rng.uniform(-r, r)
                if ok(u, v, 0.5):
                    plant(u, v, self.rng.random() < 0.2)
        walls = [w for w in self.walls if w[4] in ('full', 'damaged', 'low', 'stump', 'tall', 'tallruin', 'drystone')]
        for _ in range(n_edge):
            if not walls:
                break
            u0, v0, u1, v1, _, _ = self.rng.choice(walls)
            ang = math.atan2(v1 - v0, u1 - u0)
            t = self.rng.random()
            side = self.rng.choice((-1, 1)) * self.rng.uniform(0.35, 0.6)
            u, v = u0 + (u1 - u0) * t - math.sin(ang) * side, v0 + (v1 - v0) * t + math.cos(ang) * side
            if ok(u, v, 0.6):
                plant(u, v, self.rng.random() < 0.4)
        for (u, v, fu, fv, amount) in self.fans:
            if amount >= 0.95 and self.rng.random() < 0.6:
                d = self.rng.uniform(1.5, 3.5)
                pu, pv = u + fu * d + self.rng.uniform(-0.8, 0.8), v + fv * d + self.rng.uniform(-0.8, 0.8)
                if ok(pu, pv, 0.6):
                    plant(pu, pv, self.rng.random() < 0.5)

    def floors(self):
        """Rubble dust on every cell of every room (L shapes are covered cell by cell, not by one ellipse)."""
        for rm in self.rooms:
            if rm.get('court'):
                continue                     # a yard or a fort court: packed earth, laid by its recipe
            if rm['rect']:                   # a rectangle: one patch over the whole floor
                self.patch('rubble_dust', rm['centre'][0], rm['centre'][1], rm['ang'] + self.rng.uniform(-6, 6),
                           rm['w'] * 1.02, rm['d'] * 0.95, 0.82, 'ellipse', order=1)
                continue
            for (cu, cv) in rm['centres']:
                self.patch('rubble_dust', cu, cv, rm['ang'] + self.rng.uniform(-10, 10), PIECE_M * 1.05, PIECE_M * 0.95,
                           0.82, 'ellipse', order=1)

    def door_ground(self):
        """Trodden earth in front of every door (an apron) and a worn threshold inside it."""
        for (du, dv, name, k, fu, fv) in self.doors:
            a = math.degrees(math.atan2(fv, fu)) + 90.0
            self.patch('packed_earth', du + fu * 1.1, dv + fv * 1.1, a, 3.6, 2.6, 0.95, 'ellipse', order=2)
            self.patch('path', du - fu * 0.7, dv - fv * 0.7, a, 1.8, 1.5, 0.75, 'ellipse', order=3)

    def awning_unit(self, name, u, v, yaw, table_key, table_yaw):
        """A market awning: the Tent_C kit (frame + cloth, one pivot) with its table under it, as ONE unit.
        The frame settles on the landscape only (it can never land on a wall); the cloth copies the frame's
        transform (attach + shares_pivot, checked as DETACHED otherwise); the table is the unit's content."""
        grp = 'stall_' + name
        blk = 'unit_' + name
        frame, cloth = AWNING
        self.units.append(dict(name=name, u=u, v=v, yaw=yaw, members=[table_key, frame, cloth], clear_m=0.3))
        # order matters: select() gives an attach item the LAST solid of its group as its parent
        self.add(table_key, u + 0.1, v, table_yaw, grp, 'rest', unit=name, unit_role='content', block=blk)
        self.add(frame, u, v, yaw, grp, 'rigid', unit=name, unit_role='frame', block=blk, sink_cm=8,
                 material_set='cloth', collision=False)
        self.add(cloth, u, v, yaw, grp, 'carried', unit=name, unit_role='cover', block=blk, attach=True,
                 material_set='cloth', collision=False)

    def sweep(self, keep_out):
        """Drop scatter (ISM rubble and plants) lying on lanes and thresholds laid out after it was scattered."""
        out = []
        for it in self.s.items:
            if it.get('ism') and it.get('block') in ('fan', 'base', 'creep') and \
                    (keep_out(it['u'], it['v'])) and self.rng.random() < 0.9:
                continue
            out.append(it)
        self.s.items[:] = out


# ---------------------------------------------------------------------------- S07

S07_LAYOUT = '''
                         field terraces (dry-stone, along the contours, +7..+9 m)
                  lone room   [C1 L-room + store] tall house (gable)  --ramp--  TOWER yard (focal)
                 ramp--  [B1 P-room, hearth room, L-room]  [B2 store, L-hall]  -- lane B
      channel     lane A  [A1 L-room + store] [A2 L]   portico (3 arches), two awnings, well plaza
       (fall line)          plaza (packed earth, broken flags)   <- worn path from the road
  ============================ road (culvert parapets where the channel crosses) =========
           dry channel -> mill room + dead wheel -> the dry pool (cracked mud, stone lip)   (the hollow)
'''


def s07(C, sp):
    """The Waiting Water: a terraced hillside village right of the road, the dry channel that fed it, and the
    dry pool in the hollow on the left. Ladakh / High Atlas grammar: rooms share walls in blocks along the
    contours, lanes run along the terraces with ramps at the ends, the lookout tower crowns the core and is
    the road silhouette, field terraces step up behind, and collapse spills downhill. The blocks are authored
    by hand (the prototype the user reviews); everything else is the village archetype's grammar."""
    F = C.F
    # one terrace frame for the whole core: x along the contour, y uphill (blocks must share it, or they collide)
    ang = F.contour_deg(30.0, 26.0)
    ca, sa = math.cos(math.radians(ang)), math.sin(math.radians(ang))
    O = (18.0, 19.0)

    def K(x, y):
        return (O[0] + ca * x - sa * y, O[1] + sa * x + ca * y)
    C.cu, C.cv = K(10.0, 12.0)                  # the core, for decay-by-edge
    # The inhabited ledges follow the actual hillside contour.  Their broad, irregular earth
    # shoulders read as ground worked by feet and erosion around the rooms, even where walls fell.
    for y, x0, x1, width in ((-0.1, -4.0, 27.0, 8.0), (10.0, -8.0, 27.0, 9.0),
                            (21.5, 0.0, 23.0, 7.0)):
        height = F.g(*K((x0 + x1) / 2, y))
        pts = []
        for i in range(6):
            x = x0 + (x1 - x0) * i / 5
            yy = min((y - 3.0 + 0.25 * j for j in range(25)),
                     key=lambda candidate: abs(F.g(*K(x, candidate)) - height))
            pts.append(K(x, yy + (0.2 if i % 2 else -0.2)))
        C.path(pts, width, surface='packed_earth', strength=0.93, order=0, lane=False)
    # -- the lanes first, so collapse fans and heaps keep off them (door spurs come after the blocks)
    fa = C.path([K(-3.5, -1.4), K(26.5, -1.8)], 2.0, wander=0.45)
    fb = C.path([K(-7.5, 8.0), K(26.0, 8.4)], 1.9, wander=0.35)
    fc = C.path([K(1.0, 19.8), K(21.0, 19.7)], 1.7, wander=0.35)
    C.path([K(12.5, -15.0), K(11.0, -11.0), K(10.4, -6.5), K(10.3, -1.6)], 3.2, wander=0.5)   # road -> market -> lane A
    C.path([fa[0], K(-5.0, 2.0), K(-6.5, 5.0), fb[0]], 1.6)                          # west ramp, A -> B
    C.path([K(10.3, -1.6), K(10.6, 2.5), K(10.0, 5.2), K(10.4, 8.2), K(11.0, 12.0), K(10.2, 16.0), K(10.7, 19.8)],
           1.4, wander=0.2)                                                          # the bent alley, A -> B -> C
    C.path([fb[-1], K(27.5, 13.0), K(24.5, 17.0), fc[-1]], 1.6)                      # east ramp, B -> C
    C.path([fc[-1], K(21.8, 20.4), K(23.5, 22.5)], 1.4)                              # through the tower-yard gate
    lanes = {'A': fa, 'B': fb, 'C': fc, 'H': fc}
    # where the road path leaves the road: a trodden apron on the verge
    C.patch('packed_earth', *K(12.2, -13.6), ang + 10, 7.5, 5.5, 0.9, order=1)
    # -- the blocks: rooms of 3 m cells. L shapes and missing corners break the boxes; a corner of most
    #    blocks has come down; the rows are broken into clusters turned a few degrees off the contour
    C.block('A1', *K(0.0, 0.0), ang, [rect(0, 0, 2, 2, minus=[(1, 1)]), rect(2, 0, 1, 1)], 2,
            tall_p=0.3, breaches=[((0, 2), (1, 2), 'low'), ((3, 0), (3, 1), 'stump')],
            foundation=True, foundation_keep=[((1, 1), (2, 1))])
    C.block('A2', *K(11.5, 0.6), ang + 8, [rect(0, 0, 2, 2, minus=[(1, 0)])], 2,
            collapse_corners=1, breaches=[((0, 0), (0, 1), 'stump')],
            foundation=True, foundation_keep=[((0, 1), (0, 2))])
    C.block('B1', *K(-6.0, 10.0), ang, [rect(0, 0, 2, 2) + [(0, 2)], rect(2, 0, 1, 3), rect(3, 0, 2, 2, minus=[(4, 1)])],
            2, collapse_corners=2, tall_p=0.35,
            breaches=[((0, 3), (1, 3), 'low'), ((1, 2), (2, 2), 'stump'),
                      ((3, 2), (4, 2), 'gap'), ((4, 1), (5, 1), 'low'), ((5, 0), (5, 1), 'gap')])
    C.block('B2', *K(12.5, 10.6), ang - 6, [rect(0, 0, 1, 2), rect(1, 0, 3, 2, minus=[(3, 1)])], 2,
            tall_p=0.5, foundation=True, foundation_keep=[((0, 2), (1, 2)), ((1, 1), (1, 2))])
    C.block('C1', *K(3.0, 21.5), ang + 11, [rect(0, 0, 1, 2), rect(1, 0, 2, 1) + [(2, 1)]], 2,
            collapse_corners=1, breaches=[((0, 2), (1, 2), 'low'), ((2, 1), (2, 2), 'stump')],
            foundation=True, foundation_keep=[((0, 1), (0, 2))])
    # the tall house on the upper terrace: an L whose front came down, one tall gable standing at the back
    C.block('H', *K(13.4, 22.6), ang + 6, [[(1, 0), (0, 1), (1, 1)]], 2, tall_back=(0, 2), front_fallen=True,
            collapse_corners=0, keep_back=0.5)
    C.add('B01_house02', *K(22.0, 3.8), ang - 4 + 180, 'houses', 'rigid', scale=0.9, sink_cm=35,
          material_set='stone', block='tall1', state='house', vis_h=round(7.81 * 0.9 - 0.35, 2),
          note='two-storey ruin: the east end of the lower terrace')
    C.doors.append(K(21.0, -0.2) + ('tall1', 0, sa, -ca))                          # its door faces downhill
    # A surviving tower house crowns the eastern crest.  Its broken floors give the road silhouette
    # a domestic scale and asymmetry; the old isolated minaret read as a freestanding spike.
    tu, tv = K(27.0, 27.0)
    C.add('B01_house03', tu, tv, ang + 25, 'tower', 'rigid', scale=0.78, landmark=True, sink_cm=34,
          material_set='stone', block='tower', state='tower', vis_h=round(9.24 * 0.78 - 0.34, 2))
    yard = [K(20.5, 20.5), K(31.0, 20.0), K(32.0, 31.0)]
    for n_, (p, q) in enumerate(zip(yard[:-1], yard[1:])):
        n = max(1, int(round(math.hypot(q[0] - p[0], q[1] - p[1]) / PIECE_M)))
        st = [C.rng.choice(['stump', 'stump', 'low', 'gap']) for _ in range(n)]
        if n_ == 0:
            st[0] = 'gap'                                                            # the yard gate
        C.wall_line(p, q, st, 'toweryard', 'tower', F.downhill((p[0] + q[0]) / 2, (p[1] + q[1]) / 2))
    # -- door spurs and door aprons
    for (du, dv, rname, k, fu, fv) in list(C.doors):
        ln = lanes.get(rname[0], fa)
        best = min(((q[0] - du) ** 2 + (q[1] - dv) ** 2, q) for q in ln)[1]
        C.path([(du, dv), best], 1.3, strength=0.95)
    # -- the market in front of the portico: packed earth, broken flags (sunk flush, gaps), two awnings
    C.patch('packed_earth', *K(5.0, -6.5), ang + 7, 14.0, 8.5, 0.95, order=0)
    for i in range(4):
        for j in range(2):
            if C.rng.random() < 0.35:
                continue
            C.add('B01_floor01', *K(0.5 + 3.05 * i + C.rng.uniform(-0.3, 0.3), -9.2 + 3.05 * j), ang + C.rng.uniform(-4, 4),
                  'plaza', 'rigid', sink_cm=16, material_set='stone', block='flags', ism=True)
    # the portico: 3 arches 2.9 m in front of A1; lane A runs under them
    for i in range(3):
        C.add('AB_Side_Arch', *K(1.5 + 3.0 * i, -2.9), ang, 'portico', 'rigid', sink_cm=20, material_set='stone',
              block=C.rows[0]['block'], state='arcade', vis_h=round(4.49 - 0.2, 2))
    # two awnings with their cloth (the Tent_C kit), 4.2 m apart so the kits never touch; the third stall is bare
    for i, (x, tk) in enumerate(((1.4, 'MV_table_01'), (5.6, 'AB_WoodenTable_B'))):
        C.awning_unit('stall%d' % i, *K(x, -5.3), ang + 180 + C.rng.uniform(-5, 5), tk, ang + C.rng.uniform(-6, 6))
    C.add('MV_table_02', *K(8.9, -6.0), ang + C.rng.uniform(-8, 8), 'stalls', 'rest', note='the bare stall')
    C.add('MV_box_03', *K(9.4, -7.6), ang + 12, 'stalls', 'rest')
    for k in range(6):
        # pots stand on the ground in front of the awnings (clear of the kit boxes), never on a table edge
        C.add(C.rng.choice(POTS), *K(C.rng.uniform(0, 8.5), C.rng.uniform(-8.5, -7.6)), C.rng.uniform(0, 360), 'stalls',
              'rest', scale=(0.9, 1.2), roll=(90 if k % 3 == 0 else 0))
    C.add('MV_box_03', *K(-1.2, -4.0), ang + 12, 'stalls', 'rest')
    C.add('AB_Box_C', *K(-1.9, -5.4), ang - 20, 'stalls', 'rest')
    # -- the small open plaza by the well, west of the market: its own trodden ground, a bench, a trough
    wu, wv = K(-7.5, -8.5)
    C.patch('packed_earth', wu + 0.5, wv + 0.3, ang - 20, 10.0, 8.0, 0.95, order=0)
    C.patch('path', wu, wv, 0, 4.6, 4.6, 0.9, order=2)                                # the trodden ring at the well
    C.add('MV_well', wu, wv, ang + 10, 'well', 'rigid', sink_cm=10, material_set='stone', state='well', vis_h=2.58)
    C.add('AB_Clay_Pot_B', wu + 1.3, wv - 0.5, 0, 'well', 'rest', roll=95, note='broken at the lip')
    C.add('MV_carafe_02', wu - 1.2, wv + 0.2, 0, 'well', 'rest', scale=0.6, note='the one cup set upright')
    bu_, bv_ = K(-10.5, -6.0)
    C.add('MV_bench_02', bu_, bv_, ang - 25, 'well', 'rest', material_set='wood')
    tu_, tv_ = K(-4.5, -11.0)
    C.add('MV_wash_tub', tu_, tv_, ang + 5, 'well', 'rest', material_set='wood', note='the trough, dry')
    C.path([(wu, wv), K(3.0, -9.5), K(10.4, -8.0)], 1.4, strength=0.95, wander=0.3)
    # a hearth room (the deep one in B1): soot on the floor
    hb = [r for r in C.rooms if r['block'].startswith('B1')][1]
    hu, hv = hb['centre']
    C.patch('soot', hu, hv + 0.8, hb['ang'], 3.0, 2.2, 0.9, order=4)
    # -- the dry channel: it came down the fall line past the village's west end, under the road
    top = (6.0, 62.0)
    ch = F.descent(top[0], top[1], lambda u, v: F.road_dist(u, v) < 7.5, step=2.0)
    ch2_start = F.descent(ch[-1][0], ch[-1][1], lambda u, v: F.road_dist(u, v) > 7.5 and v < 0, step=1.0)[-1]
    ch2 = F.descent(ch2_start[0], ch2_start[1], lambda u, v: F.g(u, v) < F.g(8.0, -76.0) + 0.6, step=2.0)
    for line in (ch, ch2):
        simp = line[::2] + ([line[-1]] if len(line) % 2 == 0 else [])
        C.nblock += 1
        blk = 'channel_%d' % C.nblock
        L = piece_dims('B01_channel01')[0] * 0.97
        for (u0, v0), (u1, v1) in zip(simp[:-1], simp[1:]):
            seg = math.hypot(u1 - u0, v1 - v0)
            k = max(1, int(round(seg / L)))
            a_ = math.degrees(math.atan2(v1 - v0, u1 - u0))
            for i in range(k):
                t = (i + 0.5) / k
                if F.road_dist(u0 + (u1 - u0) * t, v0 + (v1 - v0) * t) < 6.2:
                    continue
                # a channel follows the fall line: it pitches with the slope (rigid pieces would staircase)
                C.add('B01_channel01', u0 + (u1 - u0) * t, v0 + (v1 - v0) * t, a_ - 90.0, 'channel', 'channel',
                      ism=True, block=blk, material_set='stone',
                      settle_over=dict(mode='trace', max_tilt_deg=9, rand_tilt_deg=0, z_rule='mean', sink_cm=38))
        C.path(simp, 2.2, surface='gravel', strength=0.8, order=1, lane=False)        # the dry bed, not a lane
    # culvert parapets at the road verges
    cr = ch[-1]
    for side in (-1, 1):
        C.add('AB_Broken_Walls', cr[0] + side * 1.6, cr[1] + 0.3, F.contour_deg(*cr), 'channel', 'rigid', sink_cm=10,
              material_set='stone', block='culvert', state='parapet', vis_h=0.38)
    # -- the hollow: the mill room and the dead wheel on the channel, then the dry pool
    mid = ch2[len(ch2) // 2]
    C.row('M', mid[0] + 3.0, mid[1] - 2.0, F.contour_deg(*mid) + 180, [2], 2, 3, doors_front=False, collapse_corners=1)
    C.add('B01_wheel01', mid[0] - 1.6, mid[1] + 0.5, F.contour_deg(*mid), 'mill', 'rigid', sink_cm=60,
          material_set='wood', note='the dead wheel stands in its pit on the channel', state='wheel', vis_h=3.4)
    C.add('MV_Wm_wheel_support', mid[0] - 1.6 - 2.3 * math.cos(math.radians(F.contour_deg(*mid))),
          mid[1] + 0.5 - 2.3 * math.sin(math.radians(F.contour_deg(*mid))), F.contour_deg(*mid), 'mill', 'rigid',
          scale=0.8, sink_cm=20, material_set='wood', state='wheel', vis_h=2.5)
    pool = ch2[-1]
    C.patch('dry_mud', pool[0], pool[1] - 3.0, 20.0, 22.0, 13.0, 0.95, order=0)
    C.patch('dry_mud', pool[0] + 5.0, pool[1] - 6.0, -30.0, 12.0, 8.0, 0.9, order=0)
    # the stone lip on the inflow side only (a revetment, not a ring)
    lip = [(pool[0] - 7.0, pool[1] + 3.5), (pool[0] - 1.0, pool[1] + 5.5), (pool[0] + 6.0, pool[1] + 4.5)]
    for (p, q) in zip(lip[:-1], lip[1:]):
        n = max(1, int(round(math.hypot(q[0] - p[0], q[1] - p[1]) / 1.4)))
        a_ = math.degrees(math.atan2(q[1] - p[1], q[0] - p[0]))
        for i in range(n):
            t = (i + 0.5) / n
            if C.rng.random() < 0.25:
                continue
            # one ISM group (rigid, trace-settled like the flags): the lip is 0.3 m of stone, it needs no own actor
            C.add('AB_Broken_Walls', p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t, a_ + C.rng.uniform(-6, 6), 'pool',
                  'rigid', sink_cm=18, material_set='stone', block='poollip', state='parapet', vis_h=0.3, ism=True)
    C.add('MV_bucket_02', pool[0] + 2.0, pool[1] - 1.0, 0, 'pool', 'rest', roll=70, note='stranded where the water was')
    C.add('AB_Planks_150_A', ch2[3][0], ch2[3][1], F.contour_deg(*ch2[3]), 'channel', 'lie', sink_cm=3,
          note='plank crossing over the dry bed')
    # -- the edges, NOT evenly spaced: field terraces of different reach, a lone room, a walled yard, fragments
    for z, (ua, ub) in ((F.g(40, 57), (-4.0, 70.0)), (F.g(40, 63) + 0.2, (8.0, 52.0)), (F.g(40, 70) + 0.4, (-8.0, 30.0))):
        pts = F.contour_line(z, ua, ub, 45.0, 98.0, step=4.0)
        if len(pts) >= 3:
            C.terrace_wall(pts, gap_every=0.14)
    C.block('L', 71.0, 27.0, F.contour_deg(71, 27) + 12, [rect(0, 0, 1, 1)], 3, group='outskirts', collapse_corners=1)
    C.block('Y', -9.0, 36.0, F.contour_deg(-9, 36) - 9, [rect(0, 0, 2, 2, minus=[(1, 1)])], 3, group='outskirts',
            doors=False, collapse_corners=1)
    # fragments: one standing corner uphill-east, one wall stub by the west ramp, a pair near the channel
    for (fu_, fv_, fa_, n) in ((58.0, 44.0, 20.0, 2), (-15.0, 18.0, -12.0, 1), (0.5, 46.0, 37.0, 2)):
        C.nblock += 1
        a_ = F.contour_deg(fu_, fv_) + fa_
        q = (fu_ + math.cos(math.radians(a_)) * PIECE_M * n, fv_ + math.sin(math.radians(a_)) * PIECE_M * n)
        C.wall_line((fu_, fv_), q, [C.rng.choice(['damaged', 'low', 'stump', 'full']) for _ in range(n)],
                    'frag_%d' % C.nblock, 'outskirts', F.downhill(fu_, fv_))
    for (du, dv, rname, k, fu, fv) in C.doors:                                       # outlying doors: a faint footpath
        if rname[0] in 'ABCHt':
            continue
        best = None
        for ln in C.lanes:
            for q in ln['pts']:
                d = math.hypot(q[0] - du, q[1] - dv)
                if best is None or d < best[0]:
                    best = (d, q)
        C.path([(du, dv), best[1]], 1.0, strength=0.75)
    C.add('MV_Manger', -8.0 + 3.0, 34.0 + 3.0, F.contour_deg(-8, 34), 'outskirts', 'rest', sink_cm=4)
    # yards off the block ends and backs, at angles off the grid (the V2.1 review: "boxes on a grid")
    C.auto_yards(sp.get('yards', 3))
    # Tripo (optional, placed only once imported): the collapsed mud-brick house on the lower west slope
    spot = C.find_spot([(-16.0, 28.0), (-18.0, 40.0), (-25.0, 20.0)], 5.2)          # west of the channel
    if spot:
        C.add('T2_mudbrick_house', spot[0], spot[1], ang + 14, 'outskirts', 'rigid', sink_cm=30, material_set='stone',
              block='tripo_house', state='house', vis_h=5.7, note='S07 slot of the Tripo mudbrick_house_ruined')
    # the core's own ground: one broad soft patch of trodden earth under the blocks, thinning outwards
    C.patch('packed_earth', *K(9.0, 11.0), ang, 50.0, 40.0, 0.65, order=0)
    C.meta.update(channel=[ch, ch2], frame=dict(ang=ang, O=O))


# ---------------------------------------------------------------------------- the archetype recipes

def terrace_frame(ang, O=(0.0, 0.0)):
    """K(x, y) -> site metres: the terrace frame at O (x along the contour at ang, y uphill)."""
    ca, sa = math.cos(math.radians(ang)), math.sin(math.radians(ang))

    def K(x, y):
        return (O[0] + ca * x - sa * y, O[1] + sa * x + ca * y)
    return K


def clear_origin(C, extent, side=None):
    """Where a layout of radius `extent` centres so it keeps 8 m off the road core: the site centre, pushed
    straight away from the road when it is too close (a centre on the road goes to `side`, else uphill)."""
    F = C.F
    d, q = F.W.road_distance([F.world(0.0, 0.0)])
    if d >= extent + 8.0:
        return (0.0, 0.0)
    qu, qv = F.site(float(q[0]), float(q[1]))
    n = math.hypot(qu, qv)
    if n > 0.5:
        away = (-qu / n, -qv / n)
    elif side in ('left', 'right'):
        away = (0.0, 1.0 if side == 'right' else -1.0)
    else:
        du, dv = F.downhill(0.0, 0.0)
        away = (-du, -dv)
    push = extent + 8.0 - d
    return (away[0] * push, away[1] * push)


def contour_k(C, K, z, x0, x1, y_lo, y_hi, step=4.0):
    """Points of the ground contour at height z in the terrace frame K: for each x, bisect y in [y_lo, y_hi]."""
    pts = []
    for x in np.arange(x0, x1 + 1e-6, step):
        lo, hi = y_lo, y_hi
        g_lo, g_hi = C.F.g(*K(x, lo)) - z, C.F.g(*K(x, hi)) - z
        if g_lo * g_hi > 0:
            continue
        for _ in range(22):
            mid = 0.5 * (lo + hi)
            g_mid = C.F.g(*K(x, mid)) - z
            if g_lo * g_mid <= 0:
                hi = mid
            else:
                lo, g_lo = mid, g_mid
        pts.append(K(x, 0.5 * (lo + hi)))
    return pts


def runs_clear(C, pts, road_m=7.0):
    """Split a polyline into the runs whose points keep off the road core, the rooms and the lanes."""
    runs, cur = [], []
    for p in pts:
        ok = C.F.road_dist(*p) >= road_m and math.hypot(*p) <= C.s.radius_m and \
            all(quad_dist(p, q) > 1.5 for rm in C.rooms for q in rm['cells']) and not C.on_lane(p[0], p[1], 1.0) and \
            all(math.hypot(p[0] - su, p[1] - sv) > r + 1.0 for su, sv, r, _ in C.solids)
        if ok:
            cur.append(p)
        elif cur:
            runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    return [r for r in runs if len(r) >= 2]


def cluster_rooms(rng, n_rooms, max_depth, p_l=0.4, p_store=0.2):
    """Rooms side by side for one cluster: widths 1-3 cells, depths 1-3, some Ls (a missing back corner)
    and some back stores (an extra cell behind: a T or an L). Returns (rooms, width in cells)."""
    rooms, x = [], 0
    for _ in range(n_rooms):
        w = rng.choice((1, 1, 2, 2, 2, 3))
        d = min(max_depth, rng.choice((1, 2, 2, 2, 3)))
        cells = rect(x, 0, w, d)
        if w >= 2 and d >= 2 and rng.random() < p_l:
            cells.remove(rng.choice([(x, d - 1), (x + w - 1, d - 1)]))
        elif d < max_depth and rng.random() < p_store:
            cells.append((x + rng.randrange(w), d))
        rooms.append(cells)
        x += w
    return rooms, x


def terrace_row(C, K, ang, t, y, half, sp, lane, tall_house=False):
    """One terrace: clusters of rooms along the contour, broken by alleys (2.5-5 m), each cluster turned 4-15 deg
    off the terrace and lifted so its lowest front corner stays on the terrace line (clear of the lane)."""
    rng = C.rng
    x = -half + rng.uniform(0.0, 2.5)
    k = 0
    while x < half - 3.0:
        rooms, wc = cluster_rooms(rng, rng.choice(sp['cluster_rooms']), sp['max_depth'], sp['p_l'])
        if x + wc * PIECE_M > half + 3.0:
            rooms, wc = [rect(0, 0, 1, 2)], 1
        wx = wc * PIECE_M
        placed = False
        for attempt in range(5):
            r_ = rng.choice((-1, 1)) * rng.uniform(4.0, 15.0) if rng.random() < 0.8 else rng.uniform(-3.0, 3.0)
            r_ *= (1.0, 1.0, 0.6, 0.4, 0.0)[attempt]
            lift = wx / 2.0 * abs(math.sin(math.radians(r_))) + rng.uniform(0.0, 0.6)
            fm = K(x + wx / 2.0, y + lift)
            a = ang + r_
            u0 = fm[0] - math.cos(math.radians(a)) * wx / 2.0
            v0 = fm[1] - math.sin(math.radians(a)) * wx / 2.0
            if not C.fits(C.quads(u0, v0, a, [c for rm in rooms for c in rm]), margin=1.0):
                continue
            name = 'T%d%s' % (t, 'abcdefghij'[k % 10])
            kw = dict(tall_p=sp['tall_p'], lintel_p=sp['lintel_p'], collapse_corners=rng.choice(sp['corner_falls']))
            if tall_house and len(rooms[0]) >= 2 and max(i for i, _ in rooms[0]) >= 1:
                kw.update(tall_back=(0, 2), keep_back=0.5)
                tall_house = False
            C.block(name, u0, v0, a, rooms, sp['decay'], **kw)
            C.block_lane[name] = lane
            placed = True
            break
        x += wx + rng.uniform(2.5, 5.0)
        k += int(placed)
    return tall_house


def lookout(C, cands, ang):
    """The lookout tower (the damaged minaret at x0.55, no religious dressing) in its own broken-walled yard."""
    spot = C.find_spot(cands, 5.5)
    if not spot:
        return None
    tu, tv = spot
    C.add('AB_Damaged_Minarate', tu, tv, ang + C.rng.uniform(10, 30), 'tower', 'rigid', scale=0.55, landmark=True,
          sink_cm=40, material_set='stone', block='tower', state='tower', vis_h=round(18.22 * 0.55 - 0.4, 2))
    K = terrace_frame(ang, (tu, tv))
    for n_, (p, q) in enumerate(((K(-5.5, -4.5), K(4.5, -5.0)), (K(4.5, -5.0), K(5.5, 5.0)))):
        if not C.seg_clear(p, q, margin=0.4, ignore_block='tower'):
            continue
        n = max(1, int(math.hypot(q[0] - p[0], q[1] - p[1]) / PIECE_M))
        st = [C.rng.choice(['stump', 'stump', 'low', 'gap']) for _ in range(n)]
        if n_ == 0:
            st[0] = 'gap'                                          # the yard gate
        C.wall_line(p, q, st, 'toweryard', 'tower', C.F.downhill((p[0] + q[0]) / 2, (p[1] + q[1]) / 2))
    return spot


def outskirts(C, n, ext, decay):
    """The edge thins out: lone one-room ruins and wall fragments at irregular spots beyond the core."""
    rng = C.rng
    made = 0
    for _ in range(n * 12):
        if made >= n:
            break
        a = rng.uniform(0, 2 * math.pi)
        d = rng.uniform(1.15, 1.6) * ext
        u, v = C.cu + d * math.cos(a), C.cv + d * math.sin(a)
        ang = C.F.contour_deg(u, v) + rng.uniform(-14, 14)
        if rng.random() < 0.5:
            cells = rect(0, 0, 1, 1) if rng.random() < 0.6 else rect(0, 0, 2, 1)
            if C.fits(C.quads(u, v, ang, cells), 1.5):
                C.block('L', u, v, ang, [cells], min(3, decay + 1), group='outskirts', collapse_corners=1)
                made += 1
        else:
            m = rng.choice((1, 2))
            q = (u + math.cos(math.radians(ang)) * PIECE_M * m, v + math.sin(math.radians(ang)) * PIECE_M * m)
            if C.seg_clear((u, v), q, margin=1.0):
                C.nblock += 1
                C.wall_line((u, v), q, [rng.choice(['damaged', 'low', 'stump', 'full']) for _ in range(m)],
                            'frag_%d' % C.nblock, 'outskirts', C.F.downhill(u, v))
                made += 1
    for (du, dv, name, k, fu, fv) in C.doors:                  # outlying doors: a faint footpath
        if name != 'L' or not C.lanes:
            continue
        best = min(((math.hypot(q[0] - du, q[1] - dv), q) for ln in C.lanes for q in ln['pts']))
        C.path([(du, dv), best[1]], 1.0, strength=0.75)


def fields(C, K, n, y_top, half):
    """Dry-stone field terraces along computed contour lines above the top terrace, of different reach."""
    rng = C.rng
    for k in range(n):
        yk = y_top + 8.0 + 6.5 * k + rng.uniform(-1.0, 1.0)
        z = C.F.g(*K(0.0, yk))
        reach = half + rng.uniform(4.0, 14.0)
        off = rng.uniform(-6.0, 6.0)
        pts = contour_k(C, K, z, off - reach, off + reach, yk - 8.0, yk + 12.0, step=4.0)
        for run in runs_clear(C, pts):
            C.terrace_wall(run, gap_every=0.14)


def nearest_on(pts_lists, p):
    return min(((math.hypot(q[0] - p[0], q[1] - p[1]), q) for pts in pts_lists for q in pts))[1]


def village(C, sp):
    """A terraced village or hamlet: lanes along the contours (switchback ramps at alternate ends), the path from
    the road, broken rows of turned clusters, a tall house, the lookout tower at the uphill end, a well plaza,
    yards, dry-stone field terraces above and a thinning edge of lone ruins."""
    F, rng = C.F, C.rng
    n_t, pitch, half = sp['terraces'], sp['terrace_pitch'], sp['width_m'] / 2.0
    ext = max(half, pitch * n_t / 2.0) + 6.0
    O = clear_origin(C, ext, sp.get('side'))
    ang = F.contour_deg(*O)
    K = terrace_frame(ang, O)
    y0 = -pitch * (n_t - 1) / 2.0
    C.cu, C.cv = K(0.0, 0.0)
    lanes = []
    for t in range(n_t):
        y = y0 + t * pitch - 1.8
        pts = [K(-half - 3.0, y + rng.uniform(-0.3, 0.3)), K(rng.uniform(-3, 3), y + rng.uniform(-0.4, 0.4)),
               K(half + 3.0, y + rng.uniform(-0.3, 0.3))]
        pts = [p for p in pts if F.road_dist(*p) > 7.0]
        lanes.append(C.path(pts, rng.uniform(1.7, 2.1), wander=0.4) if len(pts) >= 2 else None)
    for t in range(n_t - 1):
        if lanes[t] and lanes[t + 1]:
            e = -1 if t % 2 == 0 else 0
            sx = 2.5 if e == -1 else -2.5
            a, b = lanes[t][e], lanes[t + 1][e]
            ex = (math.cos(math.radians(ang)) * sx, math.sin(math.radians(ang)) * sx)
            C.path([a, ((a[0] + b[0]) / 2 + ex[0], (a[1] + b[1]) / 2 + ex[1]), b], 1.5, wander=0.2)
    C.road_link(sp['road_path_m'], max_len=sp['road_link_max'])
    if sp.get('plaza'):
        spot = C.find_spot([K(x, y0 - 7.5) for x in (0.0, -half / 2, half / 2)] +
                           [K(x, y0 + pitch - 4.5) for x in (-half - 6, half + 6)], 4.5)
        if spot:
            wu, wv = spot
            C.patch('packed_earth', wu, wv, ang + rng.uniform(-20, 20), 10.0, 8.0, 0.95, order=0)
            C.patch('path', wu, wv, 0, 4.6, 4.6, 0.9, order=2)
            C.add('MV_well', wu, wv, ang + rng.uniform(-15, 15), 'well', 'rigid', sink_cm=10, material_set='stone',
                  state='well', vis_h=2.58)
            C.add('MV_bench_02', wu + 3.0, wv + 1.0, ang - 25, 'well', 'rest', material_set='wood')
            C.path([(wu, wv), nearest_on([x['pts'] for x in C.lanes], (wu, wv))], 1.4, strength=0.95)
    tall = sp.get('tall_house', True)
    for t in range(n_t):
        if lanes[t]:
            tall = terrace_row(C, K, ang, t, y0 + t * pitch, half, sp, lanes[t], tall_house=tall and t >= n_t // 2)
    C.door_spurs()
    if sp.get('tower'):
        yt = y0 + (n_t - 1) * pitch + 3.0
        lookout(C, [K(half + 5.0, yt), K(-half - 5.0, yt), K(half + 6.0, yt - pitch), K(0.0, yt + 7.0)], ang)
    C.auto_yards(sp['yards'])
    outskirts(C, sp['outskirts'], ext, sp['decay'])
    fields(C, K, sp['fields'], y0 + (n_t - 1) * pitch + 3.0, half)
    C.patch('packed_earth', *K(0.0, 0.0), ang, 2 * half + 12.0, pitch * n_t + 8.0, 0.6, order=0)
    C.meta.update(frame=dict(ang=ang, O=O))


def farm(C, sp):
    """A farmstead: one house (an L, or a hall and a store) on the terrace, a walled yard beside it with a
    manger, a threshing floor downhill of the track, field terraces, and a cart track to the road."""
    F, rng = C.F, C.rng
    O = clear_origin(C, 18.0, sp.get('side'))
    ang = F.contour_deg(*O)
    K = terrace_frame(ang, O)
    C.cu, C.cv = K(0.0, 0.0)
    lane = C.path([K(-11.0, -2.3), K(0.0, -2.7), K(13.0, -2.1)], 2.2, wander=0.4)
    C.road_link(2.6, max_len=sp['road_link_max'], strength=0.9)
    shapes = [[rect(0, 0, 2, 2, minus=[(1, 1)]), rect(2, 0, 1, 1)], [rect(0, 0, 3, 2), rect(3, 0, 1, 2)],
              [rect(0, 0, 2, 2), rect(2, 0, 1, 2, minus=[(2, 1)])]]
    rooms = rng.choice(shapes)
    wc = max(i for rm in rooms for i, _ in rm) + 1
    for a in (rng.uniform(4, 10) * rng.choice((-1, 1)), 0.0):
        u0, v0 = K(-wc * PIECE_M / 2.0 - 3.0, abs(math.sin(math.radians(a))) * wc * 1.5)
        if C.fits(C.quads(u0, v0, ang + a, [c for rm in rooms for c in rm]), 1.0):
            C.block('F', u0, v0, ang + a, rooms, sp['decay'], tall_p=0.2, collapse_corners=1, lintel_p=0.6)
            C.block_lane['F'] = lane
            break
    C.door_spurs()
    # the yard: its own shape, the gate on the track side
    for sx in (1.0, -1.0):
        x0 = 4.5 if sx > 0 else -wc * PIECE_M / 2.0 - 4.5
        pts = [K(x0, 0.8), K(x0 + sx * rng.uniform(7, 9), 0.4), K(x0 + sx * rng.uniform(7.5, 9.5), rng.uniform(6.5, 8.5)),
               K(x0 + sx * rng.uniform(0.5, 1.5), rng.uniform(7, 9)), K(x0 + sx * 0.3, rng.uniform(3.5, 4.5))]
        if all(C.seg_clear(a, b, margin=0.6) for a, b in zip(pts[:-1], pts[1:])):
            C.yard(pts, contents=('MV_Manger', 'MV_wash_tub'))
            break
    C.auto_yards(max(0, sp['yards'] - 1))
    if sp.get('threshing'):
        spot = C.find_spot([K(0.0, -10.0), K(-8.0, -10.0), K(9.0, -10.0), K(0.0, 14.0)], 4.8)
        if spot:
            C.patch('packed_earth', spot[0], spot[1], 0.0, 9.0, 9.0, 1.0, order=1)
            for i in range(22):
                a = 2 * math.pi * i / 22
                if rng.random() < 0.2:
                    continue
                C.add(rng.choice(COBBLES), spot[0] + 4.3 * math.cos(a), spot[1] + 4.3 * math.sin(a), math.degrees(a),
                      'threshing', scale=(1.1, 1.4), ism=True, settle_over=RUBBLE_SETTLE, block='floorring')
            C.path([spot, nearest_on([lane], spot)], 1.5, strength=0.85)
    for i, key in enumerate(('MV_Hay_Bale_01', 'MV_Hay_Bale_02', 'MV_box_03')):
        p = C.find_spot([K(-wc * 1.5 - 5.0 - 1.4 * i, 3.0 + 1.2 * i), K(-wc * 1.5 - 4.0, -5.5 - i), K(6.0 + i, -6.0)], 1.0)
        if p:
            C.add(key, p[0], p[1], ang + rng.uniform(-30, 30), 'farm', 'rest', material_set='wood')
    fields(C, K, sp['fields'], 9.0, 14.0)
    C.patch('packed_earth', *K(0.0, 1.5), ang, 34.0, 18.0, 0.55, order=0)
    C.meta.update(frame=dict(ang=ang, O=O))


def caravanserai(C, sp):
    """One rectangular court: a ring of rooms sharing the outer wall, all doors onto the court, the gate arch
    on the side that faces the road, the well off the crossing of the worn paths, two stall awnings."""
    F, rng = C.F, C.rng
    cw, cd = sp['court']
    ext = (max(cw, cd) + 2) * PIECE_M / 2.0 + 4.0
    O = clear_origin(C, ext, sp.get('side'))
    ang = F.contour_deg(*O)
    K = terrace_frame(ang, O)
    C.cu, C.cv = K(0.0, 0.0)
    u0, v0 = K(-cw * PIECE_M / 2.0, -cd * PIECE_M / 2.0)
    # the side facing the road carries the gate
    d, q = F.W.road_distance([F.world(*O)])
    qu, qv = F.site(float(q[0]), float(q[1]))
    ca, sa = math.cos(math.radians(ang)), math.sin(math.radians(ang))
    rx, ry = (qu - O[0]) * ca + (qv - O[1]) * sa, -(qu - O[0]) * sa + (qv - O[1]) * ca
    if abs(ry) >= abs(rx):
        gate = (cw // 2, -1) if ry < 0 else (cw // 2, cd)
    else:
        gate = (-1, cd // 2) if rx < 0 else (cw, cd // 2)
    ring = [(i, -1) for i in range(-1, cw + 1)] + [(cw, j) for j in range(0, cd + 1)] + \
        [(i, cd) for i in range(cw - 1, -2, -1)] + [(-1, j) for j in range(cd - 1, -1, -1)]
    k0 = ring.index(gate)
    ring = ring[k0 + 1:] + ring[:k0]
    rooms, cur, want = [], [], rng.choice((1, 2, 2, 3))
    for c in ring:
        cur.append(c)
        if len(cur) >= want:
            rooms.append(cur)
            cur, want = [], rng.choice((1, 2, 2, 3))
    if cur:
        rooms.append(cur)
    court = {(i, j) for i in range(cw) for j in range(cd)}
    P = C.block('K', u0, v0, ang, rooms, sp['decay'], court=court, keep_back=0.45, collapse_corners=2, lintel_p=0.5)
    blk = C.last_block
    gi, gj = gate                           # the gate arch across the gate cell's outer edge
    if gj == -1:
        a, b = P(gi, gj), P(gi + 1, gj)
    elif gj == cd:
        a, b = P(gi, gj + 1), P(gi + 1, gj + 1)
    elif gi == -1:
        a, b = P(gi, gj), P(gi, gj + 1)
    else:
        a, b = P(gi + 1, gj), P(gi + 1, gj + 1)
    gc, cc = P(gi + 0.5, gj + 0.5), P(cw / 2.0, cd / 2.0)
    n_ = math.hypot(gc[0] - cc[0], gc[1] - cc[1]) or 1.0
    C.wall_piece(a, b, 'gate', blk, 'houses', ((gc[0] - cc[0]) / n_, (gc[1] - cc[1]) / n_))
    C.doors.append(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, 'K', -1, (gc[0] - cc[0]) / n_, (gc[1] - cc[1]) / n_))
    out = ((a[0] + b[0]) / 2 + (gc[0] - cc[0]) / n_ * 3.0, (a[1] + b[1]) / 2 + (gc[1] - cc[1]) / n_ * 3.0)
    C.patch('packed_earth', cc[0], cc[1], ang, cw * PIECE_M + 1.0, cd * PIECE_M + 1.0, 0.95, order=0)
    # worn paths: gate -> across the court, and the cross the doors' spurs join
    far = (2 * cc[0] - gc[0] + (gc[0] - cc[0]) * 0.25, 2 * cc[1] - gc[1] + (gc[1] - cc[1]) * 0.25)
    C.path([out, gc, cc, far], 2.2, wander=0.25)
    pu, pv = -(gc[1] - cc[1]) / n_, (gc[0] - cc[0]) / n_
    half_w = (cw if gj in (-1, cd) else cd) * PIECE_M / 2.0 - 1.4
    C.path([(cc[0] - pu * half_w, cc[1] - pv * half_w), cc, (cc[0] + pu * half_w, cc[1] + pv * half_w)], 1.8, wander=0.25)
    C.road_link(sp['road_path_m'], max_len=sp['road_link_max'])
    C.door_spurs(width=1.2)
    spot = C.find_spot([P(cw * f, cd * g) for f, g in ((0.25, 0.3), (0.75, 0.7), (0.75, 0.3), (0.25, 0.7))], 1.6,
                       margin=0.4)
    if spot:
        C.add('MV_well', spot[0], spot[1], ang, 'well', 'rigid', sink_cm=10, material_set='stone', state='well', vis_h=2.58)
        C.patch('path', spot[0], spot[1], 0, 4.2, 4.2, 0.9, order=2)
    for i in range(sp.get('stalls', 2)):
        s_ = C.find_spot([P(cw * f, cd * g) for f, g in ((0.22, 0.76), (0.78, 0.76), (0.22, 0.24), (0.78, 0.24))], 2.1,
                         margin=0.25)
        if s_:
            C.awning_unit('stall%d' % i, s_[0], s_[1], ang + 180 + rng.uniform(-5, 5), 'MV_table_02',
                          ang + rng.uniform(-6, 6))
    outskirts(C, sp['outskirts'], ext, sp['decay'])
    C.meta.update(frame=dict(ang=ang, O=O), court=[P(0, 0), P(cw, 0), P(cw, cd), P(0, cd)])


def fortress(C, sp):
    """A ruined fort: one walled court (the Fort-wall curtain tall on the uphill side, lower toward the road,
    the gate arch in it), the keep in the uphill corner (all tall), a rubble apron spilling downhill."""
    F, rng = C.F, C.rng
    cw, cd = sp['court']
    ext = max(cw, cd) * PIECE_M / 2.0 + 4.0
    O = clear_origin(C, ext, sp.get('side'))
    ang = F.contour_deg(*O)
    K = terrace_frame(ang, O)
    C.cu, C.cv = K(0.0, 0.0)
    u0, v0 = K(-cw * PIECE_M / 2.0, -cd * PIECE_M / 2.0)
    P = C.block('FORT', u0, v0, ang, [rect(0, 0, cw, cd)], sp['decay'], tall_p=0.9, keep_back=0.5,
                collapse_corners=2, door_state='gate', open_court=True, group='fort')
    ka = ang + rng.uniform(-3, 3)
    ko = P(cw - 2.2, cd - 2.2)
    kq = C.quads(ko[0], ko[1], ka, rect(0, 0, 2, 2))
    C.block('KEEP', ko[0], ko[1], ka, [rect(0, 0, 2, 2)], max(0, sp['decay'] - 1), tall_all=True,
            collapse_corners=1, keep_back=0.6)
    cc = P(cw / 2.0, cd / 2.0)
    C.patch('packed_earth', cc[0], cc[1], ang, cw * PIECE_M, cd * PIECE_M, 0.85, order=0)
    for (du, dv, name, k, fu, fv) in list(C.doors):
        if name == 'FORT':
            C.path([(du + fu * 3.0, dv + fv * 3.0), (du, dv), cc], 2.4, wander=0.3)
    C.road_link(sp['road_path_m'], max_len=sp['road_link_max'])
    C.door_spurs()
    outskirts(C, sp['outskirts'], ext, sp['decay'])
    C.meta.update(frame=dict(ang=ang, O=O), keep=kq)


def waystation(C, sp):
    """A waystation: a lean-to row of open stalls under one tall back wall, a fenced pen, a trodden ring round
    the carrier cradle (Tripo, optional), the spur from the road."""
    F, rng = C.F, C.rng
    O = clear_origin(C, 14.0, sp.get('side'))
    ang = F.contour_deg(*O)
    K = terrace_frame(ang, O)
    C.cu, C.cv = K(0.0, 0.0)
    lane = C.path([K(-9.0, -2.0), K(9.0, -2.2)], 2.4, wander=0.3)
    C.road_link(sp['road_path_m'], max_len=sp['road_link_max'])
    n = rng.choice((2, 3))
    rooms = [rect(i, 0, 1, 1) for i in range(n)]
    u0, v0 = K(-n * PIECE_M / 2.0, 0.4)
    if C.fits(C.quads(u0, v0, ang, [c for rm in rooms for c in rm]), 0.8):
        C.block('WS', u0, v0, ang, rooms, sp['decay'], tall_p=1.0, keep_back=0.8, front_fallen=True,
                collapse_corners=0)
        C.block_lane['WS'] = lane
    C.door_spurs()
    ring = C.find_spot([K(0.0, -8.5), K(-6.0, -8.5), K(6.0, -8.5), K(0.0, 9.0)], 3.5)
    if ring:
        C.patch('path', ring[0], ring[1], 0, 7.0, 7.0, 0.85, order=2)
        C.add('T2_carrier_cradle', ring[0], ring[1], ang, 'cradle', 'rigid', sink_cm=10, material_set='stone',
              state='cradle', vis_h=1.2, block='cradle')
        C.path([ring, nearest_on([lane], ring)], 1.6)
    # the pen: fence runs round a trodden patch, a gap for the gate
    for sx in (1.0, -1.0):
        x0 = sx * (n * PIECE_M / 2.0 + 3.0)
        pts = [K(x0, 1.0), K(x0 + sx * 7.0, 0.6), K(x0 + sx * 7.4, 6.5), K(x0 + sx * 0.4, 6.8)]
        if not all(C.seg_clear(a, b, margin=0.5) for a, b in zip(pts[:-1], pts[1:])):
            continue
        C.nblock += 1
        blk = 'pen_%d' % C.nblock
        for i, (a, b) in enumerate(zip(pts[:-1], pts[1:])):
            L = math.hypot(b[0] - a[0], b[1] - a[1])
            m = max(1, int(L / 2.6))
            an = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
            for j in range(m):
                if i == 0 and j == 0:
                    continue                                     # the gate
                t = (j + 0.5) / m
                C.add(rng.choice(['MV_Fence_01_V1', 'MV_Fence_01_V2', 'MV_Fence_01_V3']),
                      a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, an - 90.0 + rng.uniform(-4, 4), 'pen',
                      'rigid', sink_cm=12, material_set='wood', block=blk, state='fence', vis_h=1.0)
        cu = sum(p[0] for p in pts) / 4
        cv = sum(p[1] for p in pts) / 4
        C.patch('packed_earth', cu, cv, ang, 8.0, 6.5, 0.85, order=1)
        C.add('MV_Manger', cu, cv, ang, 'pen', 'rest', material_set='wood', block=blk + '_c')
        break
    C.meta.update(frame=dict(ang=ang, O=O))


def works(C, sp):
    """A traditional works (a forge): the long hall and its store, the hearth and chimney (AB_Fireplace) in the
    yard with soot all round it, the still and the pipe manifold (Tripo, optional), a cart track to the road."""
    F = C.F
    O = clear_origin(C, 20.0, sp.get('side'))
    ang = F.contour_deg(*O)
    K = terrace_frame(ang, O)
    C.cu, C.cv = K(0.0, 0.0)
    lane = C.path([K(-13.0, -2.4), K(0.0, -2.8), K(13.0, -2.3)], 2.6, wander=0.35)
    C.road_link(3.0, max_len=sp['road_link_max'])
    rooms = [rect(0, 0, 4, 2), rect(4, 0, 1, 2, minus=[(4, 1)])]
    u0, v0 = K(-7.5, 0.5)
    if C.fits(C.quads(u0, v0, ang, [c for rm in rooms for c in rm]), 1.0):
        C.block('W', u0, v0, ang, rooms, sp['decay'], tall_p=0.5, collapse_corners=1, lintel_p=0.7)
        C.block_lane['W'] = lane
    C.door_spurs()
    yard = C.find_spot([K(11.0, 3.5), K(-12.0, 3.5), K(0.0, -9.0)], 4.5)
    if yard:
        yu, yv = yard
        C.add('AB_Fireplace', yu, yv, ang + 180, 'forge', 'rigid', scale=0.8, sink_cm=15, material_set='stone',
              block='forge', state='hearth', vis_h=round(4.6 * 0.8 - 0.15, 2), note='the forge hearth and its chimney')
        C.patch('soot', yu, yv - 1.2, ang, 5.0, 3.6, 0.95, order=4)
        C.patch('soot', yu + 1.8, yv - 2.6, ang + 30, 3.0, 1.6, 0.7, order=4)
        C.patch('packed_earth', yu, yv - 1.0, ang, 10.0, 8.0, 0.9, order=1)
        C.path([(yu, yv - 2.0), nearest_on([lane], (yu, yv - 2.0))], 1.6)
        for key, (dx, dy) in (('T2_biofuel_still', (-4.4, 0.5)), ('T2_pipe_manifold', (-3.2, -3.4))):
            p = C.find_spot([(yu + dx, yv + dy)], 2.0, margin=0.3)
            if p:
                C.add(key, p[0], p[1], ang, 'forge', 'rigid', sink_cm=8, material_set='stone', block='apparatus',
                      state='apparatus', vis_h=2.0)
    C.auto_yards(sp['yards'])
    C.patch('packed_earth', *K(0.0, 0.0), ang, 36.0, 18.0, 0.6, order=0)
    C.meta.update(frame=dict(ang=ang, O=O))


# ---------------------------------------------------------------------------- the API: compose a site by archetype

BASE = dict(decay=2, road_path_m=3.0, road_link_max=45.0, yards=2, outskirts=3, fields=0, burnt=1, mud=3,
            creep_edge=30, tall_p=0.25, lintel_p=0.45, p_l=0.4, max_depth=2, cluster_rooms=(1, 2, 2, 3),
            corner_falls=(0, 1, 1, 2))
ARCHETYPES = {
    # name: the recipe and its parameter defaults (SETDRESS_V2.md section 1, the archetype table)
    'village': dict(recipe=village, terraces=3, terrace_pitch=11.0, width_m=30.0, tower=True, plaza=True, fields=2,
                    yards=3, outskirts=4),
    'hamlet': dict(recipe=village, terraces=2, terrace_pitch=10.5, width_m=20.0, tower=False, plaza=False, fields=1,
                   yards=2, outskirts=2, cluster_rooms=(1, 2, 2)),
    'farm': dict(recipe=farm, fields=2, yards=1, threshing=False, outskirts=1),
    'caravanserai': dict(recipe=caravanserai, court=(5, 4), stalls=2, outskirts=1, yards=0),
    'fortress': dict(recipe=fortress, court=(7, 5), outskirts=2, yards=0),
    'waystation': dict(recipe=waystation, decay=1, yards=0, outskirts=0, burnt=0),
    'works': dict(recipe=works, yards=1, burnt=2, outskirts=1),
}
# the V1 site 'kind' -> an archetype (first match wins)
KIND_ARCHETYPE = (('caravanserai', 'caravanserai'), ('fort', 'fortress'), ('town', 'village'),
                  ('village', 'village'), ('hamlet', 'hamlet'), ('farm', 'farm'), ('waystation', 'waystation'),
                  ('halt', 'waystation'), ('works', 'works'))
# per-site authoring: archetype overrides, parameters, or a hand recipe (S07, the reviewed prototype)
SITE_SPECS = {
    'S07_WaitingWater': dict(
        archetype='village', recipe=s07, seed='S07v2.1', yards=3, burnt=1,
        name='Dasef Abremu, the Waiting Water (village)', role='landmark', order=1, radius_m=110,
        story='B05 "We called this bend the Waiting Water..." (no water sound anywhere); B24 chorus',
        style='BAZAAR STONE: terraced village of shared-wall rooms, market portico, lookout tower, dry channel and pool',
        layout=S07_LAYOUT, notes='V2.1 (SETDRESS_V2.md). The tower is a lookout tower only, no religious dressing.',
        views=dict(target=(34.0, 26.0), orbits=((-12.0, 4.0), (70.0, 8.0), (40.0, 80.0)), high34=(-30.0, 60.0))),
    'L03_ThreshingFarm': dict(threshing=True),
    'L14_OldTown': dict(terraces=3, width_m=38.0, decay=3),
}
SITES_JSON = os.path.join(HERE, 'setdress_sites.json')
DEFAULT_SITES = ('S07_WaitingWater',)      # no rollout beyond the prototype until the user approves S07
_ROWS = {}


def site_row(sid):
    """The site's V1 record (road metre, side, lateral offset, decay, radius, story) from setdress_sites.json."""
    if not _ROWS:
        for r in json.load(open(SITES_JSON, encoding='utf8'))['sites']:
            _ROWS[r['id']] = {k: v for k, v in r.items() if k not in ('placements', 'views')}
    return _ROWS[sid]


def archetype_of(row):
    k = (row.get('kind') or '').lower()
    for word, arch in KIND_ARCHETYPE:
        if word in k:
            return arch
    raise KeyError('no archetype for %s (kind %r): pass archetype=' % (row['id'], row.get('kind')))


def spec_for(sid, archetype=None, **overrides):
    """The merged parameters for one site: BASE < the archetype's defaults < the V1 row (decay, side) <
    SITE_SPECS[sid] < overrides."""
    row = site_row(sid)
    ss = SITE_SPECS.get(sid, {})
    arch = archetype or ss.get('archetype') or archetype_of(row)
    sp = dict(BASE)
    sp.update(ARCHETYPES[arch])
    sp['decay'] = row.get('decay', sp['decay'])
    sp['side'] = row.get('side')
    sp.update(ss)
    sp.update(overrides)
    sp['archetype'] = arch
    return row, sp


def compose(W, sid, archetype=None, seed=None, **overrides):
    """Compose one road site by archetype. Returns the B.Site with .items (to be built into placements),
    .ground (decal patches), .units, .v2 (layout metadata), .frame and .spec.

        s = compose(W, 'L05_RidgeHamlet')                       # the archetype from the V1 kind ('hamlet')
        s = compose(W, 'S13_NumberedStop', court=(5, 4))       # override the archetype's defaults
        s = compose(W, 'L01_DockFarm', archetype='farm', seed='try2')

    The recipe lays out blocks, lanes and set pieces in the site's contour frame; Composer.finish() runs the
    passes every archetype shares (floor dust, door aprons, soot, dry mud, fallen beams, the rubble band, the
    creep, the sweep). build(W, sids) turns composed sites into placements and checks them."""
    row, sp = spec_for(sid, archetype, **overrides)
    lat = row.get('lateral_m') or 0.0
    s = B.Site(sid, sp.get('name', row['name']), row['road_m'], lat, row['kind'], sp.get('role', row['role']),
               sp.get('story', row.get('story') or ''), sp['decay'], sp.get('style', row.get('style') or ''),
               sp.get('order', row.get('order', 2)), sp.get('radius_m', row.get('radius_m', 40)),
               layout=sp.get('layout', row.get('layout') or ''), notes=sp.get('notes', row.get('notes') or ''))
    F = Frame(W, row['road_m'], lat)
    C = Composer(s, F, zlib.crc32(str(seed or sp.get('seed') or sid + 'v2.1').encode()))
    sp['recipe'](C, sp)
    s.spec = {k: v for k, v in sp.items() if not callable(v)}
    return C.finish(sp)


# ---------------------------------------------------------------------------- output

SURFACES = ('packed_earth', 'path', 'gravel', 'rubble_dust', 'soot', 'dry_mud')


def ground_records(site_out, s):
    F = s.frame
    ry = site_out['road_yaw']
    out = []
    for i, g in enumerate(s.ground):
        x, y = F.world(g['u'], g['v'])
        # the decal box is centred on the ground; its depth covers the relief under the patch
        L, Wd = g['length'], g['width']
        zs = [F.W.ground(*F.world(g['u'] + a, g['v'] + b)) for a in (-L / 2, 0, L / 2) for b in (-Wd / 2, 0, Wd / 2)]
        out.append(dict(id='%s_g%03d' % (site_out['id'], i), surface=g['surface'], shape=g['shape'],
                        x_cm=round(x * 100, 1), y_cm=round(y * 100, 1), z_cm=round(sum(zs) / len(zs) * 100, 1),
                        yaw=round((ry + g['yaw']) % 360, 1), length_m=round(L, 2), width_m=round(Wd, 2),
                        depth_m=round(max(3.0, max(zs) - min(zs) + 2.0), 2), strength=round(g['strength'], 2),
                        sort=int(g['order'])))
    return out


def resolve_refs(site_out):
    """bears_on holds composer refs (ids are only known after B.build): turn them into placement ids."""
    ids = {p['ref']: p['id'] for p in site_out['placements'] if p.get('ref')}
    for p in site_out['placements']:
        if p.get('bears_on'):
            p['bears_on'] = [ids[r] for r in p['bears_on']]
    return ids


def v2_views(W, site, F, placements=None):
    """Carrier eye at 3 road points (120, 70, 30 m before the site), 3 orbits, a wall-base close-up, high 3/4,
    far 300 m. The close-up is aimed at a standing front wall whose sight line is clear of every other solid
    (the V2.0 camera stood behind the portico). A site spec may pin the target, orbits and the high 3/4 (S07
    keeps the cameras of its first captures); otherwise they come from the layout's extent."""
    vs = getattr(site, 'spec', {}).get('views')
    cu, cv = site.v2['core']
    if vs:
        target, orbits, high = vs['target'], vs['orbits'], vs['high34']
    else:
        pts = [((w[0] + w[2]) / 2, (w[1] + w[3]) / 2) for w in site.v2['walls']] or [(cu, cv)]
        R = max(12.0, max(math.hypot(u - cu, v - cv) for u, v in pts))
        target = (cu, cv)
        orbits = [(cu + (R + 14.0) * math.cos(a), cv + (R + 14.0) * math.sin(a)) for a in (0.6, 2.7, 4.8)]
        du, dv = F.downhill(cu, cv)
        high = (cu + du * (R + 25.0) - dv * 20.0, cv + dv * (R + 25.0) + du * 20.0)
    cx, cy = F.world(*target)
    cz = W.ground(cx, cy)
    tgt = [round(cx * 100, 1), round(cy * 100, 1), round((cz + 3.0) * 100, 1)]
    views = []

    def cam(name, x, y, z_above, look=None):
        views.append(dict(name=name, cam_cm=[round(x * 100, 1), round(y * 100, 1), round((W.ground(x, y) + z_above) * 100, 1)],
                          look_cm=look or tgt))
    for k, back in (('carrier_a', 120.0), ('carrier_b', 70.0), ('carrier_c', 30.0)):
        p, _, _ = W.frame(max(0.0, site.road_m - back))
        cam(k, p[0], p[1], B.EYE_M)
    for k, (u, v) in zip(('orbit_a', 'orbit_b', 'orbit_c'), orbits):
        x, y = F.world(u, v)
        cam(k, x, y, 9.0)
    target_ = contact_target(site, F, placements or [])
    if target_:
        (mu, mv), (cu_, cv_) = target_
        x, y = F.world(cu_, cv_)
        lx, ly = F.world(mu, mv)
        cam('contact', x, y, 1.3, [round(lx * 100, 1), round(ly * 100, 1), round((W.ground(lx, ly) + 0.3) * 100, 1)])
    x, y = F.world(*high)
    cam('high34', x, y, 45.0)
    p, _, _ = W.frame(max(0.0, site.road_m - 300.0))
    cam('far300', p[0], p[1], B.EYE_M)
    return views


def contact_target(site, F, placements):
    """A standing wall piece of the core seen from 4 m in front of its downhill face, with nothing solid
    in between: ((wall u, v), (camera u, v))."""
    solids = []
    for p in placements:
        if p['ism'] or p['cat'] in ('rubble', 'shrub') or p['key'] in B.GROUND_COVERS:
            continue
        u, v = F.site(p['x_cm'] / 100.0, p['y_cm'] / 100.0)
        yaw = p['yaw'] - site_yaw(F)
        solids.append((B.rect_corners(u, v, yaw, max(p['size_m'][0], 0.3), max(p['size_m'][1], 0.3)), (u, v)))
    core = set(site.v2.get('core_blocks') or [])
    best = None
    for (u0, v0, u1, v1, st, blk) in site.v2['walls']:
        if st not in ('full', 'damaged', 'low') or blk not in core:
            continue
        mu, mv = (u0 + u1) / 2, (v0 + v1) / 2
        du, dv = F.downhill(mu, mv)
        a = math.atan2(v1 - v0, u1 - u0)
        nu, nv = -math.sin(a), math.cos(a)
        if nu * du + nv * dv < 0:
            nu, nv = -nu, -nv
        cam = (mu + nu * 4.0, mv + nv * 4.0)
        pts = [(mu + nu * t, mv + nv * t) for t in np.linspace(0.45, 4.0, 12)]
        blocked = any(in_quad(pt, q) for pt in pts for q, c in solids if math.hypot(c[0] - mu, c[1] - mv) > 0.2)
        if blocked:
            continue
        score = -math.hypot(mu - site.v2['core'][0], mv - site.v2['core'][1])
        if best is None or score > best[0]:
            best = (score, (mu, mv), cam)
    return best[1:] if best else None


def site_yaw(F):
    return math.degrees(math.atan2(F.f[1], F.f[0]))


def offline_check(W, site_out):
    """The strict physical check run offline on the composed placements (setdress_contact.offline_reports
    estimates what check2 will measure: plumb rigid pieces sunk under their lowest sample, lintels on their
    jamb tops, covers on their frames). Returns (violations, waived) from setdress_contact.judge."""
    reps, items = setdress_contact.offline_reports(
        [p for p in site_out['placements'] if not p.get('optional')],
        lambda x_cm, y_cm: W.ground(x_cm / 100.0, y_cm / 100.0) * 100.0)
    return setdress_contact.judge(reps, items, site_out.get('waivers', []))


BUILT = []


def correct_s07_wall_footing(so):
    """Keep the one S07 live check2 rubble correction in both supported build paths."""
    if so['id'] != 'S07_WaitingWater':
        return
    stones = [p for p in so['placements'] if p['key'] == 'B01_rubble01'
              and p.get('block') == 'fan' and abs(p['x_cm'] - 545980.4) < 0.1
              and abs(p['y_cm'] - 367787.5) < 0.1]
    if len(stones) != 1:
        raise RuntimeError('S07 live footing correction source changed: expected one rubble stone')
    stones[0].update(x_cm=546100.4, y_cm=367667.5, ground_z_cm=-35952.5,
                     note='Live contact correction 2026-09-28: rubble shifted 1.70 m away from the tower-yard wall footing.')


def correct_s10_wall_footing(so, W):
    """Keep the live fort correction when either supported generator is rerun."""
    if so['id'] != 'S10_CrestFort':
        return
    stones = [p for p in so['placements'] if p['key'] == 'B01_rubble01'
              and p.get('block') == 'fan' and abs(p['x_cm'] - 493538.7) < 0.1
              and abs(p['y_cm'] - 322608.6) < 0.1]
    if len(stones) != 1:
        raise RuntimeError('S10 live footing correction source changed: expected one rubble stone')
    stone = stones[0]
    stone['x_cm'] -= 200.0
    x, y = stone['x_cm'] / 100.0, stone['y_cm'] / 100.0
    stone.update(ground_z_cm=round(W.ground(x, y) * 100.0, 1), slope_deg=round(W.slope_deg(x, y), 1),
                 note='Live contact correction 2026-09-29: rubble shifted 2 m west, clear of the keep wall footing.')


def build(W, sids=DEFAULT_SITES, **overrides):
    """Compose the sites (by archetype), build their placements (B.build: ids, scales, settle rules, the road
    core), attach the V2 records (ground decals, units, views, layout) and run the offline physical check."""
    S = [compose(W, sid, **overrides) for sid in sids]
    from setdress_v2_groups.crest_fort_revision import revise_s10
    BUILT[:] = S
    out_sites, totals = B.build(W, S)
    by_id = {s.sid: s for s in S}
    for site_index, so in enumerate(out_sites):
        s = by_id[so['id']]
        resolve_refs(so)
        correct_s07_wall_footing(so)
        correct_s10_wall_footing(so, W)
        so['archetype'] = s.spec['archetype']
        so['ground'] = ground_records(so, s)
        so['units'] = s.units
        so['views'] = v2_views(W, s, s.frame, so['placements'])
        so['v2'] = s.v2
        so['counts']['decals'] = len(so['ground'])
        so['load_box_cm'] = [round(v) for v in so['load_box_cm']]
        so = revise_s10(so, CAT, offline_check, W)
        out_sites[site_index] = so
        v, w = offline_check(W, so)
        so['offline_check'] = dict(violations=[list(x) for x in v], waived=[list(x) for x in w],
                                   note='estimated offline (setdress_contact.offline_reports); check2 in the editor decides')
    return out_sites, totals


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--plot', action='store_true', help='also the review plots (setdress_v2_plot.py)')
    ap.add_argument('--sites', nargs='*', default=list(DEFAULT_SITES),
                    help='site ids to compose into the JSON (default: the S07 prototype only)')
    ap.add_argument('--preview', nargs='*', default=[],
                    help='compose these sites and plot them to docs/world/setdress_v2_<id>_top.png, without writing the JSON')
    args = ap.parse_args()
    W = B.World()
    if args.preview:
        out_sites, t = build(W, args.preview)
        import setdress_v2_plot
        for so in out_sites:
            c = so['counts']
            print('%s (%s) placements %d actors %d ism %d decals %d offline violations %d' % (
                so['id'], so['archetype'], c['placements'], c['actors'], c['ism_instances'], c['decals'],
                len(so['offline_check']['violations'])))
            setdress_v2_plot.preview(W, so)
        return
    out_sites, t = build(W, args.sites)
    doc = dict(generated_by='Tools/World/setdress_v2.py', method='docs/world/SETDRESS_V2.md', level='/Game/level/Saskarta_WP',
               conventions=dict(xy='world cm; yaw = UE yaw deg', bounds='x_cm/y_cm is the mesh BOUNDS CENTRE',
                                ground='decal patches: DecalActor pitch -90, yaw, size (depth/2, width/2, length/2)',
                                contact='rigid | rest | lie | bear | carried | stack (SETDRESS_V2.md section 3)',
                                optional='Tripo models still in production: placed only with --with-optional'),
               rejected=t['rejected'], checks=t['checks'], sites=out_sites)
    with open(OUT, 'w', encoding='utf8') as fh:
        json.dump(doc, fh, indent=1, ensure_ascii=False)
    for so in out_sites:
        c = so['counts']
        print('%s (%s) placements %d actors %d ism %d decals %d' % (so['id'], so['archetype'], c['placements'],
                                                                   c['actors'], c['ism_instances'], c['decals']))
        oc = so['offline_check']
        print('  offline check: %d violations, %d waived' % (len(oc['violations']), len(oc['waived'])))
        for x in oc['violations'][:20]:
            print('   ', x)
    print('rejected', t['rejected'][:10])
    print('checks', t['checks'][:10])
    print('wrote', OUT)
    if args.plot:
        import setdress_v2_plot
        setdress_v2_plot.main([])


if __name__ == '__main__':
    main()
