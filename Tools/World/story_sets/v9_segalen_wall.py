"""V9 the Segalen wall (road site S25_LastLookBack): the story set, composed with the set-dressing V2 method.

    python Tools/World/story_sets/v9_segalen_wall.py                  # write V9.json + the plot, print the checks
    python Tools/World/story_sets/v9_segalen_wall.py --no-plot        # data and checks only
    python Tools/World/story_sets/v9_segalen_wall.py glyph            # offline: the carved-inscription maps
          # writes SourceArt/Inscriptions/T_Inscription_V9.png, then Tools/Story/carve_inscription.py's chisel maps
    python Tools/World/story_sets/v9_segalen_wall.py editor <step> [place_setdress args]
          # runs Tools/World/place_setdress.py <step> S25_LastLookBack --v2 against Tools/World/story_sets/V9.json
    python Tools/World/story_sets/v9_segalen_wall.py materials variants
          # runs Tools/World/build_setdress_materials.py variants S25_LastLookBack against V9.json
    python Tools/World/story_sets/v9_segalen_wall.py inscription|glance|glance-save [--dry-run] [--owner X] [--greybox]
          # this set's own editor steps (place_setdress.py's Runner: PIE check, banned words, one 5 s script each)

Story (docs/story/storyline.md section 2.6 and V9, story-events.json B21_LAST_LOOK_BACK, CINEMATICS.md G21_LAST_LOOK):
after the collapse the Keeper walks the last 222 m. B21 (road 4,877, UE 133.4 m, pass:human) is the second rest, at
the road's high point: move input locked, BREATH_04B, and the glance G21 eases the view 90 deg left over a low
wall on the valley side and holds it 10 s. The boot point (road 0, 3.1 km east) is in line of sight. A stone set
upright in the wall carries Victor Segalen's lines (Steles, 1912, public domain): "In homage to your altitude,
Mountain. Weary my road: let it be harsh, let it be hard; let it go very high." No voice. Never cut.

The place: road 4,877 is spline point 3, a 47 deg LEFT bend on a crest. The road climbs 26 % to it and falls 16 %
after it, across a 24-27 deg side slope that drops east into the valley. A kept stone parapet runs round the
INSIDE of the bend (the valley side), raked to follow the road over the crest, and at the crest, where its two
runs meet, a tall dressed stele stands in the wall with its carved face turned to the bend. The parapet stands
on a rock nose: an outcrop shows under the stele, the two runs die into rocks at their ends, and footing stones,
dust and dead shrubs sit on the valley side. On the road side there is only a trodden bay and a short worn spur
to the stone's face. Z6 is "the fewest objects on the road": nothing else.

The camera at B21 is the Keeper's own third-person boom (README_Ending.md: 320 cm, socket (0, 45, 55), pawn
control rotation; the runner's glance lerps the control rotation to the target from the pawn view point). This
file models that camera for every place the Keeper can stop and moves the G21 target so the frame holds the
Keeper at the left, the valley and the boot point past his right shoulder, and the carved face on the right third.

Offline only: nothing here talks to Unreal except the `editor`, `materials` and custom-step subcommands, which
send Hayba python_run scripts (place_setdress.py itself is not edited).
"""
import argparse
import json
import math
import os
import random
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
WORLD = os.path.dirname(HERE)
ROOT = os.path.dirname(os.path.dirname(WORLD))
sys.path.insert(0, os.path.join(ROOT, 'Tools', 'Story'))
sys.path.insert(0, WORLD)
import build_road_profile as brp  # noqa: E402  (read-only use: the heightmap and the road polyline)
import setdress_catalog  # noqa: E402  (read-only use: asset paths and sizes)

OUT_JSON = os.path.join(HERE, 'V9.json')
OUT_PNG = os.path.join(ROOT, 'docs', 'world', 'story_sets', 'V9.png')
INSCR_DIR = os.path.join(ROOT, 'SourceArt', 'Inscriptions')
SID = 'S25_LastLookBack'   # the road site (setdress_sites.json: verify-only, 0 placements; the V1 lane placed nothing here)
SET = 'V9'
CAT = setdress_catalog.load()

# ---------------------------------------------------------------------------- story constants
P3_CM = (302079.6, 471550.0)          # spline point 3: the crest and the bend (road 4,876.6 m, UE 133.8 m)
P4_CM = (308579.6, 465550.0)          # spline point 4: leg A (the approach) runs P4 -> P3
P2_CM = (302079.6, 473550.0)          # spline point 2: leg B (after the bend) runs P3 -> P2
B21_ROAD_M, B21_UE_M = 4877.0, 133.4  # story-events.json B21_LAST_LOOK_BACK (pass:human on the UE distance)
BOOT_CM = (616580.0, 463550.0, -35328.0)          # Tools/GameFlow/glance_targets.json ValleyEast = the boot point
OLD_TARGET_CM = (302963.0, 472105.0, 11749.0)     # glance_targets.json SegalenWall today (LANE5 placeholder, 9e60d2cb)
GLANCE = dict(ease_in_s=2.0, hold_s=10.0)         # story-events.json G21_LAST_LOOK (move locked)
# the Keeper (Tools/GameFlow/specs/README_Ending.md, README_Carrier.md): capsule 32/88, BaseEyeHeight 64 (the pawn
# view point the glance aims from), CameraBoom 320 cm with SocketOffset (0, 45, 55), bUsePawnControlRotation.
HALF_M, EYE_OVER_CENTRE_M = 0.88, 0.64
CAMS = {
    'tp': dict(arm=3.2, socket=(0.0, 0.45, 0.55), note='third person, the live walk camera (ConfigureCamera)'),
    'fp': dict(arm=0.0, socket=(0.0, 0.0, 0.70), note="README_Ending's first-person option"),
    'drone': dict(arm=4.5, socket=(0.0, 0.45, 0.55), note='optional scene B: the boom re-tuned to 450 cm as the drone'),
}
HFOV = 90.0                           # the traveller's FollowCamera (engine default; PC_Saskarta's FOV setting)
PX_PER_TAN_1080 = 960.0               # 1920 px across tan(45 deg) * 2
WIDE24_CAM_CM = (365009.7, 348809.8, 13500.0)                    # probe_ending.json wide24 (provisional)
WIDE24_LOOK_CM = (298080.0, 483050.0, 10900.0 + 2600.0)          # mast base + 26 m (build_cinematics.plan_cin24)
WIDE24_HFOV = math.degrees(2 * math.atan(23.76 / 2 / 200.0))     # 200 mm on the 23.76 mm filmback
CLEAR_M = 5.0                         # road centreline -> footprint edge (build_setdress_sites.py CLEAR_M)
FACE_OFF_M = 5.05                     # the wall's road face and the stele's road-face corners, from each leg's centreline

# ---------------------------------------------------------------------------- the pieces
STELE_KEY, STELE_SCALE = 'AB_Pillar_A_02', 1.45   # AB dressed pillar, plain (A_01 carries a painted ornament)
STELE_ROAD_FACE_M = 1.85              # its carved face stands this high over the verge grade
WALL_KEY = 'MV_Foundation'            # 3.32 x 0.30 x 0.90 m course of flat stacked stones (MI_House_Foundation)
WALL_TOP_M = 0.50                     # parapet top over the road-side grade (the storyline's 0.48 m wall)
WALL_PIECES = 2                       # per run (two runs: the approach leg A and the leg after the bend)
ISM_ALLOW = dict(stone=0.05, shrub=0.10, ism=0.04)   # plan overlap allowed: stone / shrub into a solid, ISM x ISM

# ---------------------------------------------------------------------------- the inscription
TEXT = ['IN HOMAGE TO', 'YOUR ALTITUDE,', 'MOUNTAIN.', 'WEARY MY ROAD:', 'LET IT BE HARSH,', 'LET IT BE HARD;',
        'LET IT GO', 'VERY HIGH.']
TEXT_SOURCE = ('Victor Segalen, Steles (1912), public domain: "En hommage a ton altitude, Montagne. Fatigue ma route : '
               "qu'elle soit apre, qu'elle soit dure ; qu'elle aille tres haut.\" The English is storyline.md's.")
GLYPH_ID = 'V9'
GLYPH_MI = '/Game/SaskartaGaea/Inscriptions/MI_Glyph_V9_Carved'
FONT = 'DejaVuSerif-Bold.ttf'            # matplotlib's copy (Bitstream Vera licence; only its rendered outlines are used)
FONT_PX, SQUASH, LEADING, MARGIN_PX, CARVE_PAD_PX = 200, 0.74, 1.45, 30, 96   # carve_inscription.py PAD = 96
INK_W_M = CAT[STELE_KEY]['size_cm'][1] * STELE_SCALE / 100.0 - 0.14   # the widest line: 7 cm margins on the face
INSCR_TOP_BELOW_M = 0.16              # the first line's cap top under the stele's top
WEAR = 0.15                           # DecalColor alpha: kept, crisp (the way-stones run 0.1-0.85)


def asset(key):
    e = CAT[key]
    return e['path'], e['cat'], e['size_cm']


def draw_distance_cm(max_dim_m):
    """The V1 table (never 0 = infinite: the pcg-spawner-cull-distance-default memory note)."""
    for lim, d in ((0.6, 4000.0), (1.5, 6000.0), (4.0, 25000.0), (10.0, 80000.0)):
        if max_dim_m < lim:
            return d
    return 200000.0


def unit(v):
    v = np.asarray(v, float)
    return v / np.linalg.norm(v)


# ---------------------------------------------------------------------------- terrain and the site frame

class Ground:
    """Site frame: origin P3 (the bend), u along leg B (travel after the bend, world +Y), v LEFT of it (world +X:
    east, the valley). world(u, v) = (P3x + v, P3y + u) in metres."""

    def __init__(self):
        self.T = brp.Terrain(brp.HEIGHTMAP)
        self.R = brp.Road(brp.SPLINE_POINTS_CM)
        self.P = self.R.P[:, :2] / 100.0
        self.o = np.array(P3_CM) / 100.0
        self.f = unit(np.array(P2_CM) - np.array(P3_CM))
        self.l = np.array([self.f[1], -self.f[0]])
        self.road_yaw = math.degrees(math.atan2(self.f[1], self.f[0]))
        self.s_p3 = float(self.R.arc[[k for k in range(len(self.P)) if np.allclose(self.P[k], self.o, atol=0.02)][0]])
        dA = unit(np.array(P4_CM) - np.array(P3_CM))
        self.legA = np.array([dA @ self.f, dA @ self.l])          # (u, v): from the bend back down the approach
        self.legB = np.array([1.0, 0.0])
        b = self.legA + self.legB
        self.b = b / np.linalg.norm(b)                            # the bisector into the inside of the bend
        self.nA = np.array([-self.legA[1], self.legA[0]])
        if self.nA @ self.b < 0:
            self.nA = -self.nA
        self.nB = np.array([0.0, 1.0])

    def world(self, u, v):
        p = self.o + u * self.f + v * self.l
        return float(p[0]), float(p[1])

    def local(self, x, y):
        d = np.array([x, y]) - self.o
        return float(d @ self.f), float(d @ self.l)

    def z(self, x, y):
        return float(self.T.height(x * 100.0, y * 100.0))

    def zuv(self, u, v):
        return self.z(*self.world(u, v))

    def yaw_of_uv(self, du, dv):
        """World yaw of a (u, v) direction."""
        w = du * self.f + dv * self.l
        return math.degrees(math.atan2(w[1], w[0]))

    def uv_of_yaw(self, yaw):
        w = np.array([math.cos(math.radians(yaw)), math.sin(math.radians(yaw))])
        return float(w @ self.f), float(w @ self.l)

    def grad(self, x, y, h=0.5):
        return ((self.z(x + h, y) - self.z(x - h, y)) / (2 * h), (self.z(x, y + h) - self.z(x, y - h)) / (2 * h))

    def slope_deg(self, x, y):
        gx, gy = self.grad(x, y)
        return math.degrees(math.atan(math.hypot(gx, gy)))

    def fall_uv(self, u, v):
        gx, gy = self.grad(*self.world(u, v))
        return unit(np.array([-gy, -gx]))          # (u, v) of -grad: world (-gx, -gy) -> u = -gy, v = -gx

    def road_dist_xy(self, x, y):
        a, b = self.P[:-1], self.P[1:]
        ab = b - a
        p = np.array([x, y])
        t = np.clip(np.sum((p - a) * ab, axis=1) / np.sum(ab * ab, axis=1), 0, 1)
        q = a + ab * t[:, None]
        return float(np.min(np.linalg.norm(p - q, axis=1)))

    def road_dist(self, u, v):
        return self.road_dist_xy(*self.world(u, v))

    def ue_of_uv(self, u, v):
        """The runner's road distance for a pawn at (u, v): the UE spline distance at the closest polyline point."""
        x, y = self.world(u, v)
        a, b = self.P[:-1], self.P[1:]
        ab = b - a
        p = np.array([x, y])
        t = np.clip(np.sum((p - a) * ab, axis=1) / np.sum(ab * ab, axis=1), 0, 1)
        q = a + ab * t[:, None]
        k = int(np.argmin(np.linalg.norm(p - q, axis=1)))
        return float(self.R.ue_spline_distance(self.R.arc[k] + t[k] * self.R.seg[k]))


# ---------------------------------------------------------------------------- the composition

SETTLE = {   # SETDRESS_V2.md section 3 contact classes -> the place_setdress settle config
    'rigid': dict(mode='trace', max_tilt_deg=0, rand_tilt_deg=0, z_rule='min'),
    'lie': dict(mode='trace', max_tilt_deg=25, rand_tilt_deg=6, z_rule='mean'),
    'ism_stone': dict(mode='trace', max_tilt_deg=35, rand_tilt_deg=25, z_rule='mean'),
    'ism_shrub': dict(mode='trace', max_tilt_deg=15, rand_tilt_deg=0, z_rule='mean'),
}


class Site:
    def __init__(self, G):
        self.G = G
        self.items = []
        self.ground = []
        self.lanes = []
        self.rng = random.Random(9)

    def add(self, key, u, v, group, contact, scale=1.0, yaw=0.0, pitch=0.0, sink_cm=6, ism=False, block=None,
            role='', material_set=None, settle_kind=None, rand_tilt=None):
        path, cat, size = asset(key)
        x, y = self.G.world(u, v)
        cfg = dict(SETTLE[settle_kind or contact])
        if rand_tilt is not None:
            cfg['rand_tilt_deg'] = rand_tilt
        settle = dict(mode=cfg['mode'], sink_cm=int(round(sink_cm)), max_tilt_deg=cfg['max_tilt_deg'],
                      rand_tilt_deg=cfg['rand_tilt_deg'], z_rule=cfg['z_rule'], drop_cm=0, z_offset_cm=0)
        it = dict(key=key, asset=path, cat=cat, u=u, v=v, x=x, y=y, yaw=round(yaw % 360.0, 2), pitch=round(pitch, 2),
                  roll=0.0, scale=round(scale, 3), size_m=[round(s * scale / 100.0, 3) for s in size], settle=settle,
                  group=group, ism=ism, contact=contact, block=block, role=role, material_set=material_set)
        self.items.append(it)
        return it

    def patch(self, surface, u, v, yaw_uv, length, width, strength, shape='ellipse', sort=0, role=''):
        """yaw_uv: the patch's long axis in the site frame (deg from +u toward +v)."""
        self.ground.append(dict(surface=surface, u=u, v=v, yaw=yaw_uv, length=length, width=width, strength=strength,
                                shape=shape, sort=sort, role=role))

    def path(self, pts, width, strength, surface='path', sort=3, role=''):
        if surface == 'path':
            self.lanes.append(dict(pts=pts, width=width))
        for (u0, v0), (u1, v1) in zip(pts[:-1], pts[1:]):
            L = math.hypot(u1 - u0, v1 - v0)
            self.patch(surface, (u0 + u1) / 2, (v0 + v1) / 2, math.degrees(math.atan2(v1 - v0, u1 - u0)), L + width,
                       width, strength, 'capsule', sort, role)

    def on_lane(self, u, v, margin=0.3):
        for ln in self.lanes:
            for (u0, v0), (u1, v1) in zip(ln['pts'][:-1], ln['pts'][1:]):
                du, dv = u1 - u0, v1 - v0
                t = max(0.0, min(1.0, ((u - u0) * du + (v - v0) * dv) / (du * du + dv * dv)))
                if math.hypot(u0 + t * du - u, v0 + t * dv - v) < ln['width'] / 2 + margin:
                    return True
        return False


def rot3(yaw, pitch, roll=0.0):
    """UE rotator -> matrix (columns = local X, Y, Z in world). Positive pitch lifts +X; yaw turns +X toward +Y."""
    cy, sy = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
    cp, sp = math.cos(math.radians(pitch)), math.sin(math.radians(pitch))
    cr, sr = math.cos(math.radians(roll)), math.sin(math.radians(roll))
    X = np.array([cp * cy, cp * sy, sp])
    Y = np.array([sr * sp * cy - cr * sy, sr * sp * sy + cr * cy, -sr * cp])
    Z = np.array([-(cr * sp * cy + sr * sy), cy * sr - cr * sp * sy, cr * cp])
    return np.stack([X, Y, Z], axis=1)


def half(it):
    return np.array(it['size_m']) / 2.0


def pose_rigid(G, it, sink_m=None):
    """place_setdress.settle_pose for a rigid piece (trace, z 'min', the given pitch kept): the bounds-centre z,
    plus the 9-sample check2 gaps (>0 = above the ground)."""
    Rm = rot3(it['yaw'], it['pitch'])
    h = half(it)
    sink = it['settle']['sink_cm'] / 100.0 if sink_m is None else sink_m
    cx, cy = it['x'], it['y']
    req = []
    for fx, fy in ((-1, -1), (1, -1), (1, 1), (-1, 1), (0, 0)):
        d = Rm @ np.array([fx * h[0], fy * h[1], -h[2]])
        req.append(G.z(cx + d[0], cy + d[1]) - d[2])
    zc = min(req) - sink
    gaps = []
    for fx in (-0.92, 0.0, 0.92):
        for fy in (-0.92, 0.0, 0.92):
            d = Rm @ np.array([fx * h[0], fy * h[1], -h[2]])
            gaps.append(zc + d[2] - G.z(cx + d[0], cy + d[1]))
    return zc, gaps


def box_world(G, it, zc=None):
    """8 world corners (m). Rigid: the predicted rigid pose; others: level on the ground at the centre less the sink."""
    h = half(it)
    if it['contact'] == 'rigid':
        if zc is None:
            zc = pose_rigid(G, it)[0]
        Rm = rot3(it['yaw'], it['pitch'])
    else:
        zc = G.z(it['x'], it['y']) - it['settle']['sink_cm'] / 100.0 + h[2]
        Rm = rot3(it['yaw'], 0.0)
    out = []
    for fx in (-1, 1):
        for fy in (-1, 1):
            for fz in (-1, 1):
                d = Rm @ np.array([fx * h[0], fy * h[1], fz * h[2]])
                out.append((it['x'] + d[0], it['y'] + d[1], zc + d[2]))
    return out


def footprint_uv(G, it, pad=0.0):
    """Plan corners (u, v) of the scaled bounds box (pitch ignored: < 17 deg changes the plan by < 5 %)."""
    a = math.radians(it['yaw'])
    ax = np.array([math.cos(a), math.sin(a)])
    ay = np.array([-math.sin(a), math.cos(a)])
    h = half(it) + pad
    out = []
    for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        w = np.array([it['x'], it['y']]) + sx * h[0] * ax + sy * h[1] * ay
        out.append(G.local(*w))
    return out


def inside(poly, p):
    s = None
    for i in range(4):
        (x0, y0), (x1, y1) = poly[i], poly[(i + 1) % 4]
        c = (x1 - x0) * (p[1] - y0) - (y1 - y0) * (p[0] - x0)
        if s is None:
            s = c > 0
        elif (c > 0) != s:
            return False
    return True


def compose(G):
    S = Site(G)
    rng = S.rng
    b, t_b = G.b, np.array([-G.b[1], G.b[0]])
    stele_yaw = G.yaw_of_uv(-b[0], -b[1])            # local +X (the broad face's normal) turned to the bend
    sw = CAT[STELE_KEY]['size_cm']
    hx, hy = sw[0] * STELE_SCALE / 200.0, sw[1] * STELE_SCALE / 200.0

    # 1. the stele: on the bisector, as close to the bend as the road-core rule lets its road-face corners come
    d = 4.0
    while True:
        c = d * b
        corners = [c + sx * hx * (-b) + sy * hy * t_b for sx in (-1, 1) for sy in (-1, 1)]
        if min(G.road_dist(*q) for q in corners) >= FACE_OFF_M:
            break
        d += 0.01
    st = S.add(STELE_KEY, float(c[0]), float(c[1]), 'stele', 'rigid', scale=STELE_SCALE, yaw=stele_yaw, block='wall',
               role='FOCAL: the Segalen stele (carved face to the bend)', material_set='stone')
    # sink: its road face stands STELE_ROAD_FACE_M over the grade at the face (z 'min' puts the valley corner at grade)
    fc = c - hx * b
    z0, _ = pose_rigid(G, st, sink_m=0.0)
    top0 = z0 + st['size_m'][2] / 2
    st['settle']['sink_cm'] = int(round(100 * max(0.10, top0 - G.zuv(*fc) - STELE_ROAD_FACE_M)))
    S.stele = dict(item=st, centre=c, face_uv=fc, hx=hx, hy=hy, t=t_b)

    # 2. the parapet: two runs round the inside of the bend, raked with the road over the crest, road face on the
    #    FACE_OFF_M line of their own leg; each butts into the stele (one block, so the joint is no clash).
    wl, wt, wh = [s / 100.0 for s in CAT[WALL_KEY]['size_cm']]
    S.walls = {}
    for leg, dirv, n in (('A', G.legA, G.nA), ('B', G.legB, G.nB)):
        off = FACE_OFF_M + wt / 2
        # the run starts at the stele's road-face corner on its own side (that corner stands on this leg's 5.05 m
        # line), 5 cm back into the stele: the wall's end face then meets the stele's side, its valley corner 0.13 m
        # inside the stele (one block, no clash) and nothing crosses the road-core line.
        rc = [S.stele['centre'] - hx * b + sy * hy * t_b for sy in (-1, 1)]
        corner = min(rc, key=lambda q: abs(float((q - FACE_OFF_M * n) @ n)))
        t_start = float(corner @ dirv) - 0.05
        yaw = G.yaw_of_uv(*dirv)
        runs = []
        for k in range(WALL_PIECES):
            t0 = t_start + k * (wl - 0.02)
            t1 = t0 + wl
            tm = (t0 + t1) / 2
            cu, cv = off * n + tm * dirv
            # the rake: the verge grade along the road face over this piece (least squares)
            ts = np.linspace(t0, t1, 9)
            zs = [G.zuv(*(FACE_OFF_M * n + tt * dirv)) for tt in ts]
            slope = float(np.polyfit(ts, zs, 1)[0])
            it = S.add(WALL_KEY, float(cu), float(cv), 'wall', 'rigid', yaw=yaw, pitch=math.degrees(math.atan(slope)),
                       block='wall', role='parapet run %s, piece %d (raked %.1f deg with the verge)' % (
                           leg, k + 1, math.degrees(math.atan(slope))), material_set='stone')
            it['leg'], it['t'] = leg, (t0, t1)
            # sink: the road-side top stands WALL_TOP_M over the verge grade on average along the piece
            zc0, _ = pose_rigid(G, it, sink_m=0.0)
            clear0 = wall_top_clearance(G, it, zc0, n)
            it['settle']['sink_cm'] = int(round(100 * max(0.03, float(np.mean(clear0)) - WALL_TOP_M)))
            runs.append(it)
        S.walls[leg] = dict(items=runs, dir=dirv, n=n, off=off, t_end=t_start + WALL_PIECES * (wl - 0.02) + 0.02)

    # 3. the rock nose the wall is built on: an outcrop under the stele (valley side), a rock at each run's end
    #    (the wall dies into it), and one lower anchor down the fall line below run B. Natural rock, lie, buried.
    rocks = []
    rf = CAT['PH_rock_face']['size_cm']
    sc = 0.55
    r_out = c + b * (hx + 0.10 + rf[0] * sc / 200.0 + 0.05)
    rocks.append(('PH_rock_face', r_out, sc, stele_yaw + 12.0, 0.45, 'the outcrop the stele is founded on', b))
    for leg, key, sc_, dyaw in (('A', 'LF_Rock_05', 0.55, 25.0), ('B', 'LF_Rock_03', 0.50, -30.0)):
        W = S.walls[leg]
        r = CAT[key]['size_cm']
        p = W['off'] * W['n'] + (W['t_end'] + 0.12 + r[1] * sc_ / 200.0) * W['dir'] + 0.15 * W['n']
        rocks.append((key, p, sc_, G.yaw_of_uv(*W['dir']) + dyaw, 0.40, 'run %s ends against it' % leg, W['n']))
    WB = S.walls['B']
    p = WB['off'] * WB['n'] + 4.2 * WB['dir'] + 3.6 * WB['n']
    rocks.append(('LF_Rock_04', p, 0.50, G.yaw_of_uv(*G.fall_uv(*p)) + 20.0, 0.40,
                  'the lower anchor: leads the eye down the fall line', WB['n']))
    S.rocks = {}
    for key, p, sc_, yw, bury, role, out in rocks:
        h = CAT[key]['size_cm'][2] * sc_
        it = S.add(key, float(p[0]), float(p[1]), 'rocks', 'lie', scale=sc_, yaw=yw, sink_cm=bury * h, block='outcrop',
                   role='rock: ' + role, material_set='stone', rand_tilt=4)
        clear_road(G, it, out)
        S.rocks[role] = it

    # 4. ground: the trodden bay at the bend (road side), the short worn spur to the carved face, the gravel strip at
    #    the wall foot (road side), rubble dust along the footing (valley side) and under the outcrop's scree.
    bay = 4.15 * b
    S.patch('packed_earth', float(bay[0]), float(bay[1]), math.degrees(math.atan2(t_b[1], t_b[0])), 6.2, 2.4, 0.70,
            sort=0, role='the rest bay at the bend, where walkers stop to look')
    a0 = 3.6 * b
    a1 = fc - 0.25 * b
    S.path([(float(a0[0]), float(a0[1])), (float(a1[0]), float(a1[1]))], 0.8, 0.85,
           role='the worn spur to the carved face')
    for leg in ('A', 'B'):
        W = S.walls[leg]
        g0 = (FACE_OFF_M - 0.22) * W['n'] + (W['items'][0]['t'][0] + 0.1) * W['dir']
        g1 = (FACE_OFF_M - 0.22) * W['n'] + (W['t_end'] - 0.2) * W['dir']
        S.path([(float(g0[0]), float(g0[1])), (float(g1[0]), float(g1[1]))], 0.45, 0.55, surface='gravel', sort=2,
               role='the gravel strip where the road meets the wall (run %s)' % leg)
        d0 = (W['off'] + wt / 2 + 0.45) * W['n'] + (W['items'][0]['t'][0] + 0.2) * W['dir']
        d1 = (W['off'] + wt / 2 + 0.45) * W['n'] + (W['t_end'] - 0.1) * W['dir']
        S.path([(float(d0[0]), float(d0[1])), (float(d1[0]), float(d1[1]))], 0.9, 0.5, surface='rubble_dust', sort=1,
               role='dust along the footing, valley side (run %s)' % leg)
    fall = G.fall_uv(*r_out)
    sd = r_out + fall * 1.9
    S.patch('rubble_dust', float(sd[0]), float(sd[1]), math.degrees(math.atan2(fall[1], fall[0])), 3.0, 1.8, 0.5, sort=1,
            role='under the scree below the outcrop')

    # 5. footing stones on the valley face of every wall piece, packing stones at the stele's foot, scree below the
    #    outcrop (ISM, ground-only settle, 35-40 % buried). The road side is kept: no stones on it but the packing.
    for leg in ('A', 'B'):
        W = S.walls[leg]
        for it in W['items']:
            for f in (-0.72, -0.05, 0.62):
                tt = (it['t'][0] + it['t'][1]) / 2 + f * wl / 2 + rng.uniform(-0.2, 0.2)
                off = W['off'] + wt / 2 + rng.uniform(0.14, 0.34)
                p = off * W['n'] + tt * W['dir']
                key = rng.choice(['LF_Rock_08', 'LF_Rock_08', 'AB_Cobble_04'])
                sc_ = rng.uniform(0.65, 0.95) if key == 'LF_Rock_08' else rng.uniform(1.0, 1.3)
                h = CAT[key]['size_cm'][2] * sc_
                S.add(key, float(p[0]), float(p[1]), 'stones', 'lie', scale=sc_, yaw=rng.uniform(0, 360), sink_cm=0.38 * h,
                      ism=True, block='footing', settle_kind='ism_stone', role='footing stone, valley face of run %s' % leg,
                      material_set='stone')
    # packing stones at the stele's valley foot (along the face in half-widths, out from the back face in m); none on
    # the carved side: its foot is on the 5 m road-core line
    for s_t, s_n in ((-0.75, 0.16), (0.1, 0.20), (0.8, 0.14)):
        p = c + s_t * hy * t_b + (hx + s_n) * b
        key = rng.choice(['LF_Rock_08', 'AB_Cobble_04'])
        sc_ = rng.uniform(1.0, 1.25) if key == 'AB_Cobble_04' else rng.uniform(0.6, 0.8)
        h = CAT[key]['size_cm'][2] * sc_
        S.add(key, float(p[0]), float(p[1]), 'stones', 'lie', scale=sc_, yaw=rng.uniform(0, 360), sink_cm=0.40 * h,
              ism=True, block='footing', settle_kind='ism_stone', role='packing stone at the stele foot (valley side)',
              material_set='stone')
    for _ in range(6):
        a = math.radians(rng.uniform(-30, 30))
        r = 1.1 + min(3.0, rng.expovariate(1 / 1.0))
        dvec = np.array([fall[0] * math.cos(a) - fall[1] * math.sin(a), fall[0] * math.sin(a) + fall[1] * math.cos(a)])
        p = r_out + dvec * r + rng.uniform(-0.5, 0.5) * np.array([-fall[1], fall[0]])
        key = rng.choice(['LF_Rock_07', 'LF_Rock_07', 'LF_Rock_08'])
        sc_ = rng.uniform(0.8, 1.3) if key == 'LF_Rock_07' else rng.uniform(0.5, 0.75)
        h = CAT[key]['size_cm'][2] * sc_
        S.add(key, float(p[0]), float(p[1]), 'stones', 'lie', scale=sc_, yaw=rng.uniform(0, 360), sink_cm=0.36 * h,
              ism=True, block='scree', settle_kind='ism_stone', role='scree below the outcrop', material_set='stone')

    # 6. creep: dead shrubs in the lee of the wall (valley side), at the run ends against their rocks, and at the rock
    #    bases. None on the road side of the parapet: the place is kept.
    WA, WB = S.walls['A'], S.walls['B']
    creep = [
        ('FAB_Shrub_G', WA['off'] + 0.95, WA['items'][0]['t'][0] + 1.2, WA, 1.0, 'in the lee of run A'),
        ('FAB_Shrub_C', WA['off'] + 0.80, WA['items'][1]['t'][0] + 1.9, WA, 0.9, 'in the lee of run A, lower'),
        ('FAB_Shrub_D', WA['off'] + 0.55, WA['t_end'] + 0.25, WA, 0.9, 'where run A dies into its rock'),
        ('FAB_Shrub_E', WB['off'] + 0.95, WB['items'][0]['t'][0] + 1.6, WB, 0.9, 'in the lee of run B'),
        ('FAB_Shrub_C', WB['off'] + 1.10, WB['items'][1]['t'][0] + 1.1, WB, 1.0, 'in the lee of run B, lower'),
        ('FAB_Shrub_D', WB['off'] + 0.60, WB['t_end'] + 0.20, WB, 0.85, 'where run B dies into its rock'),
    ]
    for key, off, tt, W, sc_, where in creep:
        p = off * W['n'] + tt * W['dir']
        S.add(key, float(p[0]), float(p[1]), 'creep', 'lie', scale=sc_, yaw=rng.uniform(0, 360), sink_cm=5, ism=True,
              block='creep', settle_kind='ism_shrub', role='dead shrub ' + where)
    for extra, (dn, dt) in (('FAB_Shrub_G', (1.2, -0.6)), ('FAB_Shrub_E', (0.9, 0.8))):
        p = r_out + dn * G.fall_uv(*r_out) + dt * np.array([-fall[1], fall[0]])
        S.add(extra, float(p[0]), float(p[1]), 'creep', 'lie', scale=0.9, yaw=rng.uniform(0, 360), sink_cm=5, ism=True,
              block='creep', settle_kind='ism_shrub', role='dead shrub at the foot of the outcrop')

    S.moved = declash(G, S)
    S.dropped = [it for it in S.items if it['ism'] and (S.moved[id(it)] > 0.6 or S.on_lane(it['u'], it['v'], 0.2)
                                                        or min(G.road_dist(u, v) for u, v in footprint_uv(G, it)) < CLEAR_M
                                                        or any(a is it or bb is it for _, _, a, bb in clash_pairs(G, S)))]
    S.items = [it for it in S.items if all(it is not d for d in S.dropped)]
    return S


def clear_road(G, it, out, margin=FACE_OFF_M):
    """Move an item along the (u, v) direction `out` until its whole footprint is `margin` m off the road centreline."""
    out = unit(out)
    for _ in range(200):
        if min(G.road_dist(u, v) for u, v in footprint_uv(G, it)) >= margin:
            return
        it['u'] += 0.05 * out[0]
        it['v'] += 0.05 * out[1]
        it['x'], it['y'] = G.world(it['u'], it['v'])


def wall_top_clearance(G, it, zc, n):
    """Top of the wall's road-side face over the ground at that face, at 7 points along the piece (m)."""
    Rm = rot3(it['yaw'], it['pitch'])
    h = half(it)
    side = None
    for sy in (-1, 1):
        d = Rm @ np.array([0.0, sy * h[1], 0.0])
        du, dv = float(d[:2] @ G.f), float(d[:2] @ G.l)
        if du * n[0] + dv * n[1] < 0:            # this local Y side points back to the road
            side = sy
    out = []
    for fx in np.linspace(-0.95, 0.95, 7):
        d = Rm @ np.array([fx * h[0], side * h[1], h[2]])
        x, y = it['x'] + d[0], it['y'] + d[1]
        out.append(zc + d[2] - G.z(x, y))
    return out


# ---------------------------------------------------------------------------- ISM declash (as V8/V10)

def plan_mtv(A, B):
    """Separating-axis test of two convex quads in plan: (overlap depth m, unit axis to push A out of B), or (0, None)."""
    best, axis = 1e9, None
    ca = (sum(p[0] for p in A) / 4, sum(p[1] for p in A) / 4)
    cb = (sum(p[0] for p in B) / 4, sum(p[1] for p in B) / 4)
    for poly in (A, B):
        for i in range(4):
            (x0, y0), (x1, y1) = poly[i], poly[(i + 1) % 4]
            nn = (y0 - y1, x1 - x0)
            ln = math.hypot(*nn)
            nn = (nn[0] / ln, nn[1] / ln)
            pa = [x * nn[0] + y * nn[1] for x, y in A]
            pb = [x * nn[0] + y * nn[1] for x, y in B]
            o = min(max(pa), max(pb)) - max(min(pa), min(pb))
            if o <= 0:
                return 0.0, None
            if o < best:
                sgn = 1.0 if (ca[0] - cb[0]) * nn[0] + (ca[1] - cb[1]) * nn[1] >= 0 else -1.0
                best, axis = o, (nn[0] * sgn, nn[1] * sgn)
    return best, axis


def clash_pairs(G, S):
    solids = [it for it in S.items if not it['ism']]
    isms = [it for it in S.items if it['ism']]
    out = []
    for it in isms:
        allow = ISM_ALLOW['shrub' if it['cat'] == 'shrub' else 'stone']
        for sd in solids:
            d = plan_mtv(footprint_uv(G, it), footprint_uv(G, sd))[0]
            if d > allow + 1e-6:
                out.append((d, allow, it, sd))
    for i in range(len(isms)):
        for j in range(i + 1, len(isms)):
            d = plan_mtv(footprint_uv(G, isms[i]), footprint_uv(G, isms[j]))[0]
            if d > ISM_ALLOW['ism'] + 1e-6:
                out.append((d, ISM_ALLOW['ism'], isms[i], isms[j]))
    return out


def declash(G, S, rounds=60):
    start = {id(it): (it['u'], it['v']) for it in S.items if it['ism']}
    for _ in range(rounds):
        pairs = clash_pairs(G, S)
        if not pairs:
            break
        done = set()
        for d, allow, a, bb in sorted(pairs, key=lambda p: -p[0]):
            mover = a if a['ism'] and id(a) not in done else (bb if bb['ism'] and id(bb) not in done else None)
            if mover is None:
                continue
            fixed = bb if mover is a else a
            dd, ax = plan_mtv(footprint_uv(G, mover), footprint_uv(G, fixed))
            if ax is None:
                continue
            mover['u'] += ax[0] * (dd - allow + 0.03)
            mover['v'] += ax[1] * (dd - allow + 0.03)
            mover['x'], mover['y'] = G.world(mover['u'], mover['v'])
            done.add(id(mover))
    return {id(it): math.hypot(it['u'] - start[id(it)][0], it['v'] - start[id(it)][1]) for it in S.items if it['ism']}


# ---------------------------------------------------------------------------- the inscription (face, decal, glyph)

def glyph_layout():
    """Pixel layout of the glyph canvas and its physical size. Returns dict (no files written)."""
    from PIL import ImageFont
    import matplotlib
    font = ImageFont.truetype(os.path.join(os.path.dirname(matplotlib.__file__), 'mpl-data', 'fonts', 'ttf', FONT), FONT_PX)
    cap = font.getbbox('H')
    cap_px = cap[3] - cap[1]
    widths = [(font.getbbox(s)[2] - font.getbbox(s)[0]) * SQUASH for s in TEXT]
    ink_w = max(widths)
    pitch = cap_px * LEADING
    ink_h = pitch * (len(TEXT) - 1) + cap_px
    m_per_px = INK_W_M / ink_w
    W = int(math.ceil(ink_w + 2 * MARGIN_PX))
    H = int(math.ceil(ink_h + 2 * MARGIN_PX))
    return dict(font=font, cap_px=cap_px, cap_top=cap[1], widths=widths, pitch=pitch, W=W, H=H, m_per_px=m_per_px,
                cap_m=cap_px * m_per_px, ink_w_m=ink_w * m_per_px, ink_h_m=ink_h * m_per_px,
                decal_w_m=(W + 2 * CARVE_PAD_PX) * m_per_px, decal_h_m=(H + 2 * CARVE_PAD_PX) * m_per_px)


def write_glyph():
    """SourceArt/Inscriptions/T_Inscription_V9.png (alpha = ink) + carve_inscription.py's chisel maps."""
    from PIL import Image, ImageDraw
    Lg = glyph_layout()
    font = Lg['font']
    big = Image.new('L', (int(math.ceil(Lg['W'] / SQUASH)) + 4, Lg['H']), 0)
    dr = ImageDraw.Draw(big)
    cx = big.size[0] / 2.0
    for i, s in enumerate(TEXT):
        bb = font.getbbox(s)
        w = bb[2] - bb[0]
        y = MARGIN_PX + i * Lg['pitch'] - Lg['cap_top']
        dr.text((cx - w / 2 - bb[0], y), s, font=font, fill=255)
    ink = big.resize((Lg['W'], Lg['H']), Image.LANCZOS)
    rgba = Image.new('RGBA', ink.size, (255, 255, 255, 0))
    rgba.putalpha(ink)
    os.makedirs(INSCR_DIR, exist_ok=True)
    out = os.path.join(INSCR_DIR, 'T_Inscription_%s.png' % GLYPH_ID)
    rgba.save(out)
    import carve_inscription
    carve_inscription.carve(GLYPH_ID)
    print('wrote', out, ink.size, '+ _H/_N/_AO and %s_carved_preview.png (carve_inscription.py)' % GLYPH_ID)
    print('cap height %.1f cm, ink %.2f x %.2f m, decal %.2f x %.2f m' % (Lg['cap_m'] * 100, Lg['ink_w_m'], Lg['ink_h_m'],
                                                                        Lg['decal_w_m'], Lg['decal_h_m']))


def inscription_frame(G, S):
    """The carved face: its plane, the decal box and the text band corners (world m), from the predicted stele pose."""
    st = S.stele['item']
    zc, _ = pose_rigid(G, st)
    b, t_b, hx = G.b, S.stele['t'], S.stele['hx']
    top = zc + st['size_m'][2] / 2
    Lg = glyph_layout()
    ink_top = top - INSCR_TOP_BELOW_M
    ink_bot = ink_top - Lg['ink_h_m']
    dz = (ink_top + ink_bot) / 2
    fc = S.stele['centre'] - hx * b
    fx, fy = G.world(*fc)
    grade = G.zuv(*fc)
    tw = [G.world(*(fc + s * t_b)) for s in (-Lg['ink_w_m'] / 2, Lg['ink_w_m'] / 2)]
    corners = [(tw[0][0], tw[0][1], ink_top), (tw[1][0], tw[1][1], ink_top), (tw[1][0], tw[1][1], ink_bot),
               (tw[0][0], tw[0][1], ink_bot)]
    normal_yaw = G.yaw_of_uv(-b[0], -b[1])
    return dict(face_centre=(fx, fy, dz), normal_yaw=normal_yaw, decal_yaw=(normal_yaw + 180.0) % 360.0,
                decal_size_cm=[12.0, round(Lg['decal_w_m'] * 50.0, 1), round(Lg['decal_h_m'] * 50.0, 1)],
                ink_corners=corners, cap_m=Lg['cap_m'], ink_w_m=Lg['ink_w_m'], ink_h_m=Lg['ink_h_m'],
                ink_top=ink_top, ink_bot=ink_bot, grade=grade, stele_top=top, stele_bottom=zc - st['size_m'][2] / 2,
                face_w_m=2 * S.stele['hy'])


# ---------------------------------------------------------------------------- the B21 camera

def cam_basis(yaw, pitch):
    cy, sy = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
    cp, sp = math.cos(math.radians(pitch)), math.sin(math.radians(pitch))
    F = np.array([cp * cy, cp * sy, sp])
    Rt = np.array([-sy, cy, 0.0])
    U = np.array([-sp * cy, -sp * sy, cp])
    return F, Rt, U


def project(eye, yaw, pitch, pts, hfov=HFOV, aspect=16 / 9):
    F, Rt, U = cam_basis(yaw, pitch)
    th = math.tan(math.radians(hfov) / 2)
    tv = th / aspect
    out = []
    for p in pts:
        d = np.array(p) - np.array(eye)
        z = d @ F
        if z <= 0.05:
            out.append(None)
            continue
        out.append(((d @ Rt) / z / th, (d @ U) / z / tv, z))
    return out


def look_at(eye, tgt):
    dx, dy, dz = tgt[0] - eye[0], tgt[1] - eye[1], tgt[2] - eye[2]
    return math.degrees(math.atan2(dy, dx)), math.degrees(math.atan2(dz, math.hypot(dx, dy)))


def stops(G):
    """Where the Keeper can be when B21 fires (UE distance first <= 133.4): on leg B 0.4 m past the bend for a
    walker on the centreline or right of it, on the bisector for one cutting the inside of the bend. Braking from
    1.1 m/s at 4 m/s2 adds 0.15 m."""
    out = []
    for v in (-3.0, -1.5, 0.0):
        out.append(('leg B, %+.1f m' % v, 0.55, v))
    for d in (1.5, 3.0, 4.0):
        p = d * G.b
        out.append(('inside, %.1f m' % d, float(p[0]) + 0.15, float(p[1])))
    return out


NOMINAL_STOPS = ('leg B, +0.0 m', 'inside, 3.0 m')


def keeper(G, u, v):
    x, y = G.world(u, v)
    feet = G.z(x, y)
    return dict(feet=(x, y, feet), centre=(x, y, feet + HALF_M), view=(x, y, feet + HALF_M + EYE_OVER_CENTRE_M))


def camera(G, K, yaw, pitch, mode):
    c = CAMS[mode]
    F, Rt, U = cam_basis(yaw, pitch)
    s = c['socket']
    p = np.array(K['centre']) - c['arm'] * F + s[1] * Rt + s[2] * U
    return tuple(float(q) for q in p)


def keeper_box(K):
    x, y, z = K['feet']
    out = []
    for dx in (-0.25, 0.25):
        for dy in (-0.25, 0.25):
            for dz in (0.0, 1.68):
                out.append((x + dx, y + dy, z + dz))
    return out


def glance_target(G):
    """The new G21 target: from the nominal (centreline) stop's view point, a look LOOK_LEFT_DEG left of the boot
    point and LOOK_DOWN_DEG under it, placed TARGET_M out along that ray (far: the look is the same for every stop)."""
    K = keeper(G, 0.55, 0.0)
    yb, pb = look_at(K['view'], tuple(c / 100.0 for c in BOOT_CM))
    yaw, pitch = yb - LOOK_LEFT_DEG, pb - LOOK_DOWN_DEG
    F, _, _ = cam_basis(yaw, pitch)
    p = np.array(K['view']) + F * TARGET_M
    return tuple(float(q) for q in p), yaw, pitch


LOOK_LEFT_DEG, LOOK_DOWN_DEG, TARGET_M = 12.0, 5.0, 120.0


def b21_frames(G, S, ins, target_m):
    """Every stop x camera mode at the G21 hold: the screen positions of the boot point, the text band and the
    Keeper, the cap height in px at 1920 x 1080, the carved face's angle to the camera, what covers the boot point."""
    rows = []
    boot = tuple(c / 100.0 for c in BOOT_CM)
    solids = [it for it in S.items if not it['ism']]
    for label, u, v in stops(G):
        K = keeper(G, u, v)
        yaw, pitch = look_at(K['view'], target_m)
        for mode in CAMS:
            eye = camera(G, K, yaw, pitch, mode)
            bq = project(eye, yaw, pitch, [boot])[0]
            tq = [q for q in project(eye, yaw, pitch, ins['ink_corners'])]
            text_in = all(q is not None and abs(q[0]) <= 1 and abs(q[1]) <= 1 for q in tq)
            dist = math.dist(eye, ins['face_centre'])
            to_cam = np.array(eye[:2]) - np.array(ins['face_centre'][:2])
            nrm = np.array([math.cos(math.radians(ins['normal_yaw'])), math.sin(math.radians(ins['normal_yaw']))])
            face_ang = math.degrees(math.acos(max(-1.0, min(1.0, float(nrm @ to_cam / np.linalg.norm(to_cam))))))
            F, _, _ = cam_basis(yaw, pitch)
            depth = (np.array(ins['face_centre']) - np.array(eye)) @ F
            cap_px = ins['cap_m'] * math.cos(math.radians(abs(look_at(eye, ins['face_centre'])[1]))) / depth * PX_PER_TAN_1080
            tbox = None
            if all(q is not None for q in tq):
                tbox = (min(q[0] for q in tq), max(q[0] for q in tq), min(q[1] for q in tq), max(q[1] for q in tq))
            kq = [q for q in project(eye, yaw, pitch, keeper_box(K)) if q is not None] if mode != 'fp' else []
            kbox = (min(q[0] for q in kq), max(q[0] for q in kq), min(q[1] for q in kq), max(q[1] for q in kq)) if kq else None
            covers = []
            for it in solids:
                q = [p for p in project(eye, yaw, pitch, box_world(G, it)) if p is not None]
                if len(q) == 8 and bq is not None:
                    if min(p[0] for p in q) <= bq[0] <= max(p[0] for p in q) and min(p[1] for p in q) <= bq[1] <= max(p[1] for p in q):
                        covers.append(it['key'])
            if kbox and bq is not None and kbox[0] <= bq[0] <= kbox[1] and kbox[2] <= bq[1] <= kbox[3]:
                covers.append('the Keeper')
            text_hidden = bool(kbox and tbox and kbox[1] > tbox[0] and kbox[0] < tbox[1] and kbox[3] > tbox[2] and kbox[2] < tbox[3])
            gz = G.z(eye[0], eye[1])
            rows.append(dict(stop=label, mode=mode, keeper_uv=[round(u, 2), round(v, 2)], ue_m=round(G.ue_of_uv(u, v), 2),
                             yaw=round(yaw, 1), pitch=round(pitch, 1), boot=None if bq is None else [round(float(bq[0]), 2), round(float(bq[1]), 2)],
                             boot_covered_by=covers, text_box=None if tbox is None else [round(float(t), 2) for t in tbox],
                             text_in_frame=text_in, text_hidden_by_keeper=text_hidden, keeper_box=None if kbox is None else [round(float(t), 2) for t in kbox],
                             text_dist_m=round(dist, 2), cap_px_1080=round(cap_px, 1), cap_px_1440=round(cap_px * 4 / 3, 1),
                             face_angle_deg=round(face_ang, 1), cam_clear_m=round(eye[2] - gz, 2)))
    return rows


def approach_frames(G, S, ins):
    """The walk up the approach (leg A): the third-person camera behind the Keeper looking up the road. Where the
    stele sits in frame and whether the terrain hides it. The carved face is edge-on from here: it is revealed at
    the rest."""
    rows = []
    st = S.stele['item']
    top = ins['stele_top']
    for s in (4840.0, 4850.0, 4860.0, 4868.0):
        x, y = G.R.xy(s) / 100.0
        u, v = G.local(float(x), float(y))
        K = keeper(G, u, v)
        yaw = G.yaw_of_uv(-G.legA[0], -G.legA[1])
        pitch = -5.0
        eye = camera(G, K, yaw, pitch, 'tp')
        q = [p for p in project(eye, yaw, pitch, box_world(G, st)) if p is not None]
        box = None
        if q:
            box = [round(float(f(p[i] for p in q)), 2) for f, i in ((min, 0), (max, 0), (min, 1), (max, 1))]
        sx, sy = G.world(*S.stele['centre'])
        dist = math.hypot(sx - eye[0], sy - eye[1])
        tan, _ = G.T.horizon_tan(np.array([eye[0] * 100]), np.array([eye[1] * 100]), np.array([eye[2]]),
                                 np.array([sx * 100]), np.array([sy * 100]), skip_far_m=1.5)
        visible = (top - 0.3 - eye[2]) / dist > float(tan[0])
        sky = sky_behind(G, eye, (sx, sy, top))
        rows.append(dict(road_m=s, dist_m=round(dist, 1), stele_box=box, terrain_los_top=bool(visible),
                         stele_top_against=sky))
    return rows


def sky_behind(G, eye, p):
    """'sky' if the ray from the eye through p clears the terrain beyond p for 3 km, else 'ground'."""
    d = np.array(p) - np.array(eye)
    L = np.linalg.norm(d[:2])
    ang = d[2] / L
    for r in np.arange(L + 2.0, L + 3000.0, 4.0):
        q = np.array(eye[:2]) + d[:2] / L * r
        if G.z(float(q[0]), float(q[1])) > eye[2] + ang * r:
            return 'ground'
    return 'sky'


def wide24_report(G, S):
    eye = tuple(c / 100.0 for c in WIDE24_CAM_CM)
    yw, pt = look_at(eye, tuple(c / 100.0 for c in WIDE24_LOOK_CM))
    st = S.stele['item']
    q = [p for p in project(eye, yw, pt, box_world(G, st), hfov=WIDE24_HFOV) if p is not None]
    cx, cy = st['x'], st['y']
    dist = math.dist(eye[:2], (cx, cy))
    px_m = 2 * dist * math.tan(math.radians(WIDE24_HFOV) / 2) / 1920.0
    box = [round(float(f(p[i] for p in q)), 3) for f, i in ((min, 0), (max, 0), (min, 1), (max, 1))] if q else None
    return dict(dist_m=round(dist), stele_screen_box=box, cm_per_px_1920=round(px_m * 100, 1),
                stele_px=[round(st['size_m'][1] / px_m), round(st['size_m'][2] * 0.7 / px_m)])


# ---------------------------------------------------------------------------- records

def to_record(G, i, it, zc=None):
    rid = '%s_v9_%03d' % (SID, i)
    rec = dict(id=rid, key=it['key'], asset=it['asset'], kind='SM', cat=it['cat'],
               x_cm=round(it['x'] * 100, 1), y_cm=round(it['y'] * 100, 1), ground_z_cm=round(G.z(it['x'], it['y']) * 100, 1),
               yaw=it['yaw'], pitch=float(it['pitch']), roll=0.0, scale=it['scale'], scale_range=[it['scale'], it['scale']],
               settle=it['settle'], group=it['group'], folder='Set/%s/%s' % (SID, it['group']), data_layer='DL_SetDress',
               ism=it['ism'], stack=False, attach=False, run_id=None, collision=not it['ism'],
               foliage_exclude=it['group'] in ('stele', 'wall', 'rocks'),
               draw_distance_cm=draw_distance_cm(max(it['size_m'])), cast_shadow=True, size_m=it['size_m'],
               slope_deg=round(G.slope_deg(it['x'], it['y']), 1), contact=it['contact'],
               site_uv=[round(it['u'], 2), round(it['v'], 2)], role=it['role'], story_set=SET)
    if it['block']:
        rec['block'] = it['block']
    if it['material_set']:
        rec['material_set'] = it['material_set']
    if it['key'] == STELE_KEY:
        rec['draw_distance_cm'] = 200000.0       # the landmark of the crest: CIN_24's wide and the approach see it
    rec['road_clear_m'] = round(min(G.road_dist(u, v) for u, v in footprint_uv(G, it)), 2)
    if zc is not None:
        rec['predicted_centre_z_cm'] = round(zc * 100, 1)
    return rec


def ground_records(G, S):
    out = []
    for i, g in enumerate(S.ground):
        x, y = G.world(g['u'], g['v'])
        a = math.radians(g['yaw'])
        ax = np.array([math.cos(a), math.sin(a)])
        ay = np.array([-math.sin(a), math.cos(a)])
        zs = [G.zuv(*(np.array([g['u'], g['v']]) + sl * g['length'] * ax + sw * g['width'] * ay))
              for sl in (-0.5, 0.0, 0.5) for sw in (-0.5, 0.0, 0.5)]
        relief = max(zs) - min(zs)
        out.append(dict(id='%s_v9_g%02d' % (SID, i), surface=g['surface'], shape=g['shape'], x_cm=round(x * 100, 1),
                        y_cm=round(y * 100, 1), z_cm=round((max(zs) + min(zs)) / 2 * 100, 1),
                        yaw=round(G.yaw_of_uv(*ax) % 360.0, 1), length_m=round(g['length'], 2), width_m=round(g['width'], 2),
                        depth_m=round(max(3.0, relief + 1.2), 1), strength=g['strength'], sort=g['sort'], role=g['role']))
    return out


def views(G, S, ins, target_m):
    """Capture views (place_setdress.py capture --v2, 60 deg; far300 50 deg). cam/look in world cm."""
    out = []

    def cm(p):
        return [round(p[0] * 100, 1), round(p[1] * 100, 1), round(p[2] * 100, 1)]

    def add(name, cam, look, note=''):
        out.append(dict(name=name, cam_cm=cm(cam), look_cm=cm(look), note=note))
    fc = ins['face_centre']
    mid = (fc[0], fc[1], fc[2] - 0.3)
    for name, s in (('carrier_a', 4850.0), ('carrier_b', 4866.0)):
        x, y = G.R.xy(s) / 100.0
        u, v = G.local(float(x), float(y))
        K = keeper(G, u, v)
        yaw = G.yaw_of_uv(-G.legA[0], -G.legA[1])
        add(name, camera(G, K, yaw, -5.0, 'tp'), mid, 'the walk up to the bend: the Keeper camera at road %d m' % s)
    K = keeper(G, 0.55, 0.0)
    yaw, pitch = look_at(K['view'], target_m)
    F, _, _ = cam_basis(yaw, pitch)
    eye = camera(G, K, yaw, pitch, 'tp')
    add('carrier_c', eye, tuple(np.array(eye) + F * 20.0), 'G21 hold, the Keeper on the centreline, third person '
        '(capture at 60 deg: the 90 deg frame is wider)')
    Ki = keeper(G, 3.0 * G.b[0] + 0.15, 3.0 * G.b[1])
    yaw, pitch = look_at(Ki['view'], target_m)
    F, _, _ = cam_basis(yaw, pitch)
    eye = camera(G, Ki, yaw, pitch, 'tp')
    add('glance_in', eye, tuple(np.array(eye) + F * 20.0), 'G21 hold, the Keeper cutting the inside of the bend')
    add('glance_face', eye, fc, 'the same eye, aimed at the carved face: can the lines be read')
    b = G.b
    t_b = S.stele['t']
    for name, (dt, dn, h) in (('orbit_a', (-9.0, -2.0, 2.4)), ('orbit_b', (8.0, 3.5, 2.0)), ('orbit_c', (1.0, 11.0, 1.2))):
        p = S.stele['centre'] + dt * t_b + dn * b
        x, y = G.world(*p)
        add(name, (x, y, max(G.z(x, y) + h, fc[2] - 1.0 + h)), mid)
    p = S.stele['centre'] + 3.2 * b + 1.5 * t_b
    x, y = G.world(*p)
    lp = S.walls['A']['items'][0]
    add('contact', (x, y, G.z(x, y) + 1.0), (lp['x'], lp['y'], G.z(lp['x'], lp['y']) + 0.2),
        'the valley face: footing stones, the outcrop under the stele, the wall base')
    p = S.stele['centre'] - 14.0 * b + 12.0 * t_b
    x, y = G.world(*p)
    add('high34', (x, y, G.z(x, y) + 16.0), mid)
    p = S.stele['centre'] + 300.0 * b
    x, y = G.world(*p)
    add('far300', (x, y, G.z(x, y) + 25.0), mid, 'from the valley side, 300 m out along the bisector')
    add('glance_fp', keeper(G, 0.55, 0.0)['centre'][:2] + (keeper(G, 0.55, 0.0)['centre'][2] + 0.70,), target_m,
        "G21 hold, README_Ending's first-person option")
    return out


# ---------------------------------------------------------------------------- checks

def checks(G, S, recs, ins, frames, appr):
    notes, bad = [], []
    for r in recs:
        if r['road_clear_m'] < CLEAR_M:
            bad.append('ROAD %s %s %.2f m' % (r['id'], r['key'], r['road_clear_m']))
    solids = [it for it in S.items if not it['ism']]
    for i in range(len(solids)):
        for j in range(i + 1, len(solids)):
            a, b = solids[i], solids[j]
            if a['block'] == b['block'] and a['block'] == 'wall':
                continue
            d = plan_mtv(footprint_uv(G, a), footprint_uv(G, b))[0]
            if d > 0.0:
                bad.append('PLAN OVERLAP %s x %s by %.2f m (different blocks)' % (a['role'][:40], b['role'][:40], d))
    for it in S.items:
        if it['ism'] and S.on_lane(it['u'], it['v'], 0.2):
            bad.append('ON PATH %s at (%.1f, %.1f)' % (it['key'], it['u'], it['v']))
    left = clash_pairs(G, S)
    for d, allow, a, b in left:
        bad.append('ISM OVERLAP %s into %s by %.2f m (allowed %.2f)' % (a['key'], b['key'], d, allow))
    mv = sorted(S.moved[id(it)] for it in S.items if it['ism'])
    notes.append('ISM declash: %d of %d moved (max %.2f m), %d left out (%s)' % (
        sum(1 for m in mv if m > 0.005), len(mv), max(mv) if mv else 0.0, len(S.dropped),
        ', '.join('%s (%s)' % (d['key'], d['role'][:28]) for d in S.dropped) or 'none'))
    for it in S.items:
        if it['contact'] != 'rigid':
            continue
        zc, gaps = pose_rigid(G, it)
        if max(gaps) > 0.05:
            bad.append('FLOAT %s: a check2 sample %.0f cm above the ground' % (it['role'][:40], max(gaps) * 100))
        if it['group'] == 'wall':
            W = S.walls[it['leg']]
            cl = wall_top_clearance(G, it, zc, W['n'])
            h = half(it)
            notes.append('%s: sink %d cm, road-side top over the verge %.2f..%.2f m (mean %.2f), valley face %.2f m, '
                         'check2 gap max %+.0f cm' % (it['role'], it['settle']['sink_cm'], min(cl), max(cl), float(np.mean(cl)),
                                                      2 * h[2] - it['settle']['sink_cm'] / 100.0, max(gaps) * 100))
            if min(cl) < 0.25:
                bad.append('WALL LOW %s: the road-side top is %.2f m over the verge' % (it['role'], min(cl)))
            if max(cl) > 0.85:
                bad.append('WALL HIGH %s: the road-side top is %.2f m over the verge' % (it['role'], max(cl)))
        else:
            notes.append('%s: sink %d cm, top %.2f m, carved face %.2f m over its grade, valley foot %.2f m under the top, '
                         'check2 gap max %+.0f cm' % (it['role'][:34], it['settle']['sink_cm'], ins['stele_top'],
                                                      ins['stele_top'] - ins['grade'], ins['stele_top'] - min(
                                                          G.z(*G.world(u, v)) for u, v in footprint_uv(G, it)),
                                                      max(gaps) * 100))
    notes.append('inscription: %d lines, cap %.1f cm, ink %.2f x %.2f m on a %.2f m face; ink %.2f..%.2f m over the '
                 'verge grade; decal box %s cm (half extents)' % (
                     len(TEXT), ins['cap_m'] * 100, ins['ink_w_m'], ins['ink_h_m'], ins['face_w_m'],
                     ins['ink_bot'] - ins['grade'], ins['ink_top'] - ins['grade'], ins['decal_size_cm']))
    if ins['ink_w_m'] > ins['face_w_m'] - 0.08:
        bad.append('INSCRIPTION WIDER than the face less 4 cm margins')
    if ins['ink_bot'] - ins['grade'] < 0.25:
        bad.append('INSCRIPTION reaches the ground (%.2f m)' % (ins['ink_bot'] - ins['grade']))
    for r in frames:
        tag = '%s / %s' % (r['stop'], r['mode'])
        if r['boot'] is None or abs(r['boot'][0]) > 1 or abs(r['boot'][1]) > 1:
            bad.append('G21 %s: the boot point is out of frame %s' % (tag, r['boot']))
        if r['boot_covered_by']:
            bad.append('G21 %s: the boot point is covered by %s' % (tag, r['boot_covered_by']))
        if r['mode'] == 'tp' and r['stop'] in NOMINAL_STOPS:
            if not r['text_in_frame']:
                bad.append('G21 %s: the carved lines leave the frame %s' % (tag, r['text_box']))
            if r['text_hidden_by_keeper']:
                bad.append('G21 %s: the Keeper stands in front of the carved lines' % tag)
            if r['cap_px_1080'] < 9.5:
                bad.append('G21 %s: the letters are %.1f px at 1080p (< 9.5)' % (tag, r['cap_px_1080']))
        if r['mode'] == 'tp' and r['cam_clear_m'] < 0.3:
            bad.append('G21 %s: the boom camera is %.2f m over the terrain (the arm would shorten)' % (tag, r['cam_clear_m']))
    tp = [r for r in frames if r['mode'] == 'tp']
    notes.append('G21 third person: letters %.1f..%.1f px at 1080p (%.1f..%.1f at 1440p), %.1f..%.1f m from the camera, '
                 'the face %.0f..%.0f deg off square' % (
                     min(r['cap_px_1080'] for r in tp), max(r['cap_px_1080'] for r in tp),
                     min(r['cap_px_1440'] for r in tp), max(r['cap_px_1440'] for r in tp),
                     min(r['text_dist_m'] for r in tp), max(r['text_dist_m'] for r in tp),
                     min(r['face_angle_deg'] for r in tp), max(r['face_angle_deg'] for r in tp)))
    for r in appr:
        notes.append('approach %d m: stele %.1f m from the camera, screen box %s, terrain LOS %s, top against %s' % (
            r['road_m'], r['dist_m'], r['stele_box'], r['terrain_los_top'], r['stele_top_against']))
    return notes, bad


# ---------------------------------------------------------------------------- the plot

def plot(G, S, recs, grecs, ins, frames, target_m, out_png=OUT_PNG):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon, Ellipse
    fig = plt.figure(figsize=(20, 11.5))
    ax = fig.add_axes([0.03, 0.05, 0.47, 0.88])
    U0, U1, V0, V1 = -12.0, 14.0, -6.0, 18.0
    us = np.arange(U0, U1 + 0.01, 0.25)
    vs = np.arange(V0, V1 + 0.01, 0.25)
    UU, VV = np.meshgrid(us, vs)
    X = G.o[0] + UU * G.f[0] + VV * G.l[0]
    Y = G.o[1] + UU * G.f[1] + VV * G.l[1]
    Z = G.T.height(X * 100, Y * 100)
    cs = ax.contour(UU, VV, Z, levels=np.arange(np.floor(Z.min()), Z.max(), 0.5), colors='#b9ad9a', linewidths=0.6)
    ax.clabel(cs, cs.levels[::4], fmt='%.0f m', fontsize=7, colors='#8a7f6c')
    # the road ribbons (9 m) of both legs and their centrelines
    for dirv, L in ((G.legA, 30.0), (G.legB, 20.0)):
        n = np.array([-dirv[1], dirv[0]])
        poly = [4.5 * n, 4.5 * n + L * dirv, -4.5 * n + L * dirv, -4.5 * n]
        ax.add_patch(Polygon([tuple(p) for p in poly], closed=True, fc='#cfc6b8', ec='none', alpha=0.55))
        ax.plot([0, L * dirv[0]], [0, L * dirv[1]], color='#8a8174', lw=1, ls='--')
        for sgn in (-1, 1):
            q = [CLEAR_M * sgn * n, CLEAR_M * sgn * n + L * dirv]
            ax.plot([q[0][0], q[1][0]], [q[0][1], q[1][1]], color='#c55', lw=0.7, ls=':')
    ax.text(-11.6, 12.4, 'road, leg A (the approach,\nclimbing 26 % to the bend)', fontsize=8, color='#5d564c')
    ax.text(8.0, -3.6, 'road, leg B (after the bend) ->', fontsize=8, color='#5d564c')
    ax.text(9.2, 5.6, 'road-core 5 m', fontsize=7, color='#c55')
    col = dict(packed_earth='#b08a5a', path='#6b4d33', rubble_dust='#c8b79a', gravel='#9b9384')
    for g in S.ground:
        a = math.radians(g['yaw'])
        if g['shape'] == 'capsule':
            L = g['length'] - g['width']
            p0 = (g['u'] - L / 2 * math.cos(a), g['v'] - L / 2 * math.sin(a))
            p1 = (g['u'] + L / 2 * math.cos(a), g['v'] + L / 2 * math.sin(a))
            ax.plot([p0[0], p1[0]], [p0[1], p1[1]], color=col[g['surface']], lw=g['width'] * 22, alpha=0.4,
                    solid_capstyle='round')
        else:
            ax.add_patch(Ellipse((g['u'], g['v']), g['length'], g['width'], angle=g['yaw'], color=col[g['surface']],
                                 alpha=0.38 * g['strength'], lw=0))
    style = {'stele': ('#222', '#8d8a84'), 'wall': ('#4a4238', '#a89a86'), 'rocks': ('#4f4a44', '#b3aca1')}
    for it in S.items:
        if it['ism']:
            c = '#6d8f4e' if it['group'] == 'creep' else '#7d6e5f'
            ms = 7 if it['group'] == 'creep' else max(2.5, it['size_m'][0] * 9)
            ax.plot(it['u'], it['v'], 'o' if it['group'] == 'creep' else 's', ms=ms, color=c, alpha=0.85, mec='none')
            continue
        ec, fc = style[it['group']]
        ax.add_patch(Polygon(footprint_uv(G, it), closed=True, ec=ec, fc=fc, lw=1.4, alpha=0.92))
    # the carved face
    fcu = S.stele['face_uv']
    t_b = S.stele['t']
    q0, q1 = fcu - 0.52 * t_b, fcu + 0.52 * t_b
    ax.plot([q0[0], q1[0]], [q0[1], q1[1]], color='#b8860b', lw=4)
    ax.annotate('FOCAL: the Segalen stele, AB_Pillar_A_02 x1.4\ncarved face (gold) turned to the bend; top %.1f m,\n'
                'face %.2f m over its grade; %d lines, caps %.1f cm' % (ins['stele_top'], ins['stele_top'] - ins['grade'],
                                                                       len(TEXT), ins['cap_m'] * 100),
                xy=(S.stele['centre'][0], S.stele['centre'][1]), xytext=(2.5, 15.5), fontsize=9,
                arrowprops=dict(arrowstyle='->', color='#333'))
    wa = S.walls['A']['items'][1]
    ax.annotate('parapet run A: 2 x MV_Foundation,\nraked with the verge (top ~%.1f m over it)' % WALL_TOP_M,
                xy=(wa['u'], wa['v']), xytext=(-11.5, 16.0), fontsize=9, arrowprops=dict(arrowstyle='->'))
    wb = S.walls['B']['items'][1]
    ax.annotate('parapet run B', xy=(wb['u'], wb['v']), xytext=(9.5, 9.5), fontsize=9, arrowprops=dict(arrowstyle='->'))
    ax.annotate('rest bay (packed earth)\n+ worn spur to the face', xy=(4.0 * G.b[0], 4.0 * G.b[1]), xytext=(4.5, 1.2),
                fontsize=8, color='#6b4d33', arrowprops=dict(arrowstyle='->', color='#6b4d33'))
    fall = G.fall_uv(4.0, 10.0)
    ax.arrow(10.5, 13.5, 2.0 * fall[0], 2.0 * fall[1], head_width=0.35, color='#a55')
    ax.text(10.2, 12.7, 'fall line', fontsize=8, color='#a55')
    # stops and the G21 look (third person) from the two nominal stops
    for label, u, v in stops(G):
        ax.plot(u, v, 'o', color='#1f5fa8' if label in NOMINAL_STOPS else '#8fb0d8', ms=6)
    for label, colr in ((NOMINAL_STOPS[0], '#1f5fa8'), (NOMINAL_STOPS[1], '#6a3fa0')):
        u, v = [(uu, vv) for l_, uu, vv in stops(G) if l_ == label][0]
        K = keeper(G, u, v)
        yaw, pitch = look_at(K['view'], target_m)
        eye = camera(G, K, yaw, pitch, 'tp')
        eu, ev = G.local(eye[0], eye[1])
        ax.plot(eu, ev, '^', color=colr, ms=8)
        du, dv = G.uv_of_yaw(yaw)
        for off in (-45, 0, 45):
            a = math.atan2(dv, du) - math.radians(off)
            ax.plot([eu, eu + 26 * math.cos(a)], [ev, ev + 26 * math.sin(a)], color=colr,
                    lw=1.5 if off == 0 else 0.7, ls='-' if off == 0 else '--', alpha=0.8)
        ax.text(eu + 0.3, ev - 1.0, 'G21 camera,\n%s' % label, fontsize=7, color=colr)
    bu, bv = G.uv_of_yaw(look_at(keeper(G, 0.55, 0.0)['view'], tuple(c / 100 for c in BOOT_CM))[0])
    ax.annotate('to the boot point, 3.1 km', xy=(0.55 + 16 * bu, 16 * bv), xytext=(0.55 + 9 * bu - 3, 9 * bv + 6.5),
                fontsize=8, color='#c22', arrowprops=dict(arrowstyle='->', color='#c22'))
    ou, ov = G.local(OLD_TARGET_CM[0] / 100, OLD_TARGET_CM[1] / 100)
    ax.plot(ou, ov, 'x', color='#c33', ms=9, mew=2)
    ax.text(ou + 0.3, ov + 0.3, 'old G21 target (moved)', fontsize=7, color='#c33')
    ax.plot(0, 0, 'k^', ms=8)
    ax.text(-4.2, -1.3, 'B21, the bend (4,877 m)', fontsize=8)
    ax.set_xlim(U0, U1)
    ax.set_ylim(V0, V1)
    ax.set_aspect('equal')
    ax.set_xlabel('u: metres along leg B from the bend (world +Y)')
    ax.set_ylabel('v: metres LEFT of leg B (world +X: east, the valley)')
    ax.set_title('V9 the Segalen wall (S25_LastLookBack), plan: 0.5 m contours; ISM stones = squares, shrubs = green')

    def frame_ax(rect, title):
        a2 = fig.add_axes(rect)
        a2.set_xlim(-1, 1)
        a2.set_ylim(-1, 1)
        a2.set_aspect(9 / 16)
        a2.set_xticks([])
        a2.set_yticks([])
        a2.set_title(title, fontsize=9.5)
        a2.set_facecolor('#dfe7ee')
        return a2

    def draw_frame(a2, eye, yw, pt, K=None):
        xs = np.linspace(-1, 1, 161)
        th = math.tan(math.radians(HFOV) / 2)
        tv = th / (16 / 9)
        sky = []
        for sx in xs:
            az = yw + math.degrees(math.atan(sx * th))
            d = np.arange(2.0, 3500.0, 3.0)
            px = eye[0] + d * math.cos(math.radians(az))
            py = eye[1] + d * math.sin(math.radians(az))
            h = G.T.height(px * 100, py * 100)
            el = np.max(np.degrees(np.arctan2(h - eye[2], d)))
            sky.append(math.tan(math.radians(el - pt)) / tv)
        a2.fill_between(xs, -1, np.clip(sky, -1, 1), color='#b8a88f', lw=0)
        for uu in np.arange(-10, 14.1, 1.0):
            pts = [(*G.world(uu, vv), G.zuv(uu, vv)) for vv in np.arange(-6, 20.1, 0.5)]
            q = [p for p in project(eye, yw, pt, pts) if p is not None]
            a2.plot([p[0] for p in q], [p[1] for p in q], color='#9c8c74', lw=0.35)
        for vv in np.arange(-6, 20.1, 1.0):
            pts = [(*G.world(uu, vv), G.zuv(uu, vv)) for uu in np.arange(-10, 14.1, 0.5)]
            q = [p for p in project(eye, yw, pt, pts) if p is not None]
            a2.plot([p[0] for p in q], [p[1] for p in q], color='#9c8c74', lw=0.35)
        edges = [(0, 1), (2, 3), (4, 5), (6, 7), (0, 2), (1, 3), (4, 6), (5, 7), (0, 4), (1, 5), (2, 6), (3, 7)]
        for it in S.items:
            if it['ism'] and max(it['size_m']) < 0.3:
                continue
            q = project(eye, yw, pt, box_world(G, it))
            ec = {'stele': '#222', 'wall': '#4a4238', 'rocks': '#5c554d', 'creep': '#56753c', 'stones': '#7d6e5f'}[it['group']]
            for i0, i1 in edges:
                if q[i0] is not None and q[i1] is not None:
                    a2.plot([q[i0][0], q[i1][0]], [q[i0][1], q[i1][1]], color=ec, lw=1.2 if it['group'] in ('stele', 'wall') else 0.6)
        tq = project(eye, yw, pt, ins['ink_corners'])
        if all(q is not None for q in tq):
            a2.add_patch(Polygon([(q[0], q[1]) for q in tq], closed=True, fc='#b8860b', ec='#8a6212', alpha=0.55))
            for i in range(len(TEXT)):
                f = (i + 0.5) / len(TEXT)
                y = tq[0][1] + (tq[3][1] - tq[0][1]) * f
                a2.plot([tq[0][0] + 0.01, tq[1][0] - 0.01], [y, y], color='#5a3d0a', lw=0.6)
        if K is not None:
            kq = [q for q in project(eye, yw, pt, keeper_box(K)) if q is not None]
            if kq:
                a2.add_patch(Polygon([(min(q[0] for q in kq), min(q[1] for q in kq)), (max(q[0] for q in kq), min(q[1] for q in kq)),
                                      (max(q[0] for q in kq), max(q[1] for q in kq)), (min(q[0] for q in kq), max(q[1] for q in kq))],
                                     closed=True, fc='#3b5d7a', ec='none', alpha=0.7))
        bq = project(eye, yw, pt, [tuple(c / 100.0 for c in BOOT_CM)])[0]
        if bq is not None and abs(bq[0]) <= 1 and abs(bq[1]) <= 1:
            a2.plot(bq[0], bq[1], '+', color='#c22', ms=13, mew=2)
            a2.text(bq[0] + 0.03, bq[1] + 0.05, 'boot point', fontsize=8, color='#c22')
        for gl in (-1 / 3, 1 / 3):
            a2.axvline(gl, color='w', lw=0.5, alpha=0.6)
            a2.axhline(gl, color='w', lw=0.5, alpha=0.6)
    for rect, label in (([0.52, 0.52, 0.46, 0.42], NOMINAL_STOPS[0]), ([0.52, 0.04, 0.46, 0.42], NOMINAL_STOPS[1])):
        u, v = [(uu, vv) for l_, uu, vv in stops(G) if l_ == label][0]
        K = keeper(G, u, v)
        yaw, pitch = look_at(K['view'], target_m)
        eye = camera(G, K, yaw, pitch, 'tp')
        r = [f for f in frames if f['stop'] == label and f['mode'] == 'tp'][0]
        a2 = frame_ax(rect, 'G21 hold, third person (boom 3.2 m), Keeper %s: 90 deg frame. Caps %.1f px @1080p, '
                            'text %.1f m away' % (label, r['cap_px_1080'], r['text_dist_m']))
        draw_frame(a2, eye, yaw, pitch, K)
    fig.savefig(out_png, dpi=80)
    plt.close(fig)
    return out_png


# ---------------------------------------------------------------------------- main

def build():
    G = Ground()
    S = compose(G)
    recs = []
    for i, it in enumerate(S.items):
        zc = pose_rigid(G, it)[0] if it['contact'] == 'rigid' else None
        recs.append(to_record(G, i, it, zc))
    grecs = ground_records(G, S)
    ins = inscription_frame(G, S)
    target, tyaw, tpitch = glance_target(G)
    return G, S, recs, grecs, ins, target, tyaw, tpitch


def write(G, S, recs, grecs, ins, target, tyaw, tpitch, frames, appr, wide, notes, bad):
    vw = views(G, S, ins, target)
    cx, cy = G.world(*S.stele['centre'])
    r = 14.0
    near = [v for v in vw if v['name'] not in ('far300', 'high34')]
    xs = [cx * 100] + [v['cam_cm'][0] for v in near]
    ys = [cy * 100] + [v['cam_cm'][1] for v in near]
    box = [min(xs) - (r + 30) * 100, min(ys) - (r + 30) * 100, max(xs) + (r + 30) * 100, max(ys) + (r + 30) * 100]
    solo = [x for x in recs if not x['ism']]
    ism = [x for x in recs if x['ism']]
    st_rec = [x for x in recs if x['key'] == STELE_KEY][0]
    site = dict(
        id=SID, story_set=SET, name='Ibartegh, the Last Look Back: the Segalen wall (V9)', kind='wall + inscribed stone',
        order=5, road_m=int(B21_ROAD_M), side='left', lateral_m=round(-float(S.stele['centre'] @ G.b), 1),
        centre_cm=[round(cx * 100, 1), round(cy * 100, 1), round(G.z(cx, cy) * 100, 1)], road_yaw=round(G.road_yaw, 1),
        radius_m=r, zone='Z6 Summit',
        storm='above the cloud: clear, calm, gold light; bare wind-scoured rock; the fewest objects on the road',
        role='rest', story='B21 the last look back (G21_LAST_LOOK, 10 s, move locked); the Segalen stone (never cut)',
        decay=0, style='kept stone: a raked parapet round the inside of the crest bend, a dressed stele at its crown',
        layout='\n'.join([
            '  road leg A (climbing 26 %) ====\\            /==== road leg B (falling 16 %)',
            '                                  \\  B21   /   (the bend, 4,877 m, the high point)',
            '        rest bay (packed earth) + spur to the carved face',
            '   parapet run A (2 x MV_Foundation, raked) --[STELE]-- parapet run B (2 x MV_Foundation, raked)',
            '   rock (run A dies into it)      outcrop under the stele        rock (run B ends on it)',
            '        footing stones, dust, dead shrubs on the valley side        lower anchor rock',
            '                         ... the valley, the boot point 3.1 km east ...']),
        notes='Story set V9 on the road site S25_LastLookBack (the V1 lane placed nothing here: verify-only). Runs '
              'inside V10\'s load (window B, after B12). The carved lines are a decal (MI_Glyph_V9_Carved from '
              'SourceArt/Inscriptions/T_Inscription_V9*), placed by this set\'s `inscription` step after the settle. '
              'The G21 target moves (`glance`). Nothing religious, nothing modern.',
        story_owned=['V9 the Segalen wall (this file is the story set)', 'Saskarta.Glance.SegalenWall (moved by `glance`)'],
        verify_only=False, layer='road', poi=None, load_box_cm=[round(v) for v in box],
        counts=dict(placements=len(recs), actors=len(solo) + len({(x['group'], x['asset']) for x in ism}),
                    ism_instances=len(ism), physics=0, batch01=0, decals=len(grecs), inscription_decals=1),
        views=[{k: v[k] for k in ('name', 'cam_cm', 'look_cm')} for v in vw],
        view_notes={v['name']: v['note'] for v in vw if v['note']},
        check_views=dict(cin24_wide=dict(cam_cm=list(WIDE24_CAM_CM), look_cm=list(WIDE24_LOOK_CM), hfov_deg=round(WIDE24_HFOV, 2),
                                         note='CIN_24 shot 3 (probe_ending.json wide24, PROVISIONAL): judge with build_cinematics.py')),
        placements=recs, ground=grecs, units=[], waivers=[],
        v2=dict(frame=dict(origin='spline point 3 (the bend)', origin_cm=list(P3_CM), u='along leg B (world +Y)',
                           v='left of leg B (world +X, east)'),
                lanes=S.lanes, b21_frames=frames, approach=appr, wide24=wide, checks=notes, violations=bad),
    )
    doc = dict(
        generated_by='Tools/World/story_sets/v9_segalen_wall.py', method='docs/world/SETDRESS_V2.md',
        design='docs/world/story_sets/V9.md', level='/Game/level/Saskarta_WP', story_set=SET,
        conventions=dict(xy='world cm; yaw/pitch = UE degrees (pitch lifts local +X)', bounds='x_cm/y_cm is the mesh BOUNDS CENTRE',
                         ground='decal patches: DecalActor pitch -90, yaw, size (depth/2, width/2, length/2)',
                         contact='rigid | lie (SETDRESS_V2.md section 3); the wall pieces are rigid with a fixed pitch (the rake)',
                         site_uv='u m along leg B from the bend (spline point 3), v m left of it'),
        rejected=[
            'AB_Broken_Walls (the storyline\'s wall, 0.71 m deep, 0.48 m tall): on the 24-27 deg cross slope a plumb '
            'piece of that depth stands only ~0.1 m over the road-side grade (a kerb); two courses need a bearing '
            'settle this pipeline lacks, and its broken top does not read as kept',
            'tixjegefa_tier_2 upright (the storyline\'s stone): a rough temple block with a raised boss, no flat face '
            'for the lines, and upright needs a 90 deg roll that check2 cannot judge',
            'the storyline\'s 6 lines at ~5 cm: from the third-person boom (6-12 m away) they are 5-8 px tall at 1080p',
            'the old G21 target (10 m out, 3.5 m down): it centred a point on the slope, with the Keeper beside it '
            'and the boot point near the left edge'],
        checks=[], sites=[site],
        inscription=dict(
            text=TEXT, source=TEXT_SOURCE, glyph_id=GLYPH_ID, material=GLYPH_MI,
            textures=['/Game/SaskartaGaea/Inscriptions/T_Inscription_V9' + s for s in ('', '_N', '_AO')],
            source_png='SourceArt/Inscriptions/T_Inscription_V9.png', font=FONT + ' (matplotlib), squashed x%.2f' % SQUASH,
            cap_cm=round(ins['cap_m'] * 100, 1), ink_m=[round(ins['ink_w_m'], 3), round(ins['ink_h_m'], 3)],
            on=st_rec['id'], face_normal_yaw=round(ins['normal_yaw'], 2), decal_yaw=round(ins['decal_yaw'], 2),
            decal_size_cm=ins['decal_size_cm'], top_below_stele_top_cm=round(INSCR_TOP_BELOW_M * 100, 1),
            predicted_centre_cm=[round(c * 100, 1) for c in ins['face_centre']], wear=WEAR,
            greybox='TextRender fallback (the storyline\'s): one per line, world size = the cap height, dark stone colour'),
        glance_target=dict(
            tag='Saskarta.Glance.SegalenWall', old_cm=list(OLD_TARGET_CM), new_cm=[round(c * 100, 1) for c in target],
            look_yaw=round(tyaw, 2), look_pitch=round(tpitch, 2), left_of_boot_deg=LOOK_LEFT_DEG, under_boot_deg=LOOK_DOWN_DEG,
            distance_m=TARGET_M, follow_up='Tools/GameFlow/glance_targets.json (GameFlow lane) still holds old_cm: copy new_cm there'),
    )
    with open(OUT_JSON, 'w', encoding='utf8') as fh:
        json.dump(doc, fh, indent=1, ensure_ascii=False)
    return site


# ---------------------------------------------------------------------------- editor steps

INSCRIPTION_BODY = r'''
have = site_actors(SITE)
st = have.get('SD_' + STELE)
if st is None:
    print('INSCRIPTION no stele ' + STELE + ': run place and settle first')
else:
    b = st.static_mesh_component.static_mesh.get_bounds()
    sc = st.get_actor_scale3d().x
    l = st.get_actor_location()
    r = st.get_actor_rotation()
    ax = axes(r.yaw, r.pitch, r.roll)
    # the bounds face whose normal points to the bend (NORMAL_YAW), and the stele's real top
    best = None
    for sgn in (1.0, -1.0):
        nrm = apply(ax, (sgn, 0.0, 0.0))
        d = nrm[0] * math.cos(math.radians(NORMAL_YAW)) + nrm[1] * math.sin(math.radians(NORMAL_YAW))
        if best is None or d > best[0]:
            best = (d, sgn, nrm)
    d, sgn, nrm = best
    c = apply(ax, (b.origin.x * sc, b.origin.y * sc, b.origin.z * sc))
    top = l.z + c[2] + b.box_extent.z * sc
    f = apply(ax, (sgn * b.box_extent.x * sc, 0.0, 0.0))
    fx, fy = l.x + c[0] + f[0], l.y + c[1] + f[1]
    zc = top - TOP_BELOW - SIZE[2] + PAD_Z
    old = [a for a in site_actors(SITE).values() if a.get_actor_label().startswith('SD_' + STELE + '_carve')]
    for a in old:
        eas.destroy_actor(a)
    nyaw = math.degrees(math.atan2(nrm[1], nrm[0]))
    mi = eal.does_asset_exist(MI)
    if mi and not GREYBOX:
        g = eas.spawn_actor_from_class(unreal.DecalActor, V(fx, fy, zc), unreal.Rotator(roll=0.0, pitch=0.0, yaw=nyaw + 180.0))
        g.set_actor_label('SD_' + STELE + '_carve')
        dc = g.decal
        dc.set_decal_material(unreal.load_asset(MI))
        dc.set_editor_property('decal_size', V(SIZE[0], SIZE[1], SIZE[2]))
        dc.set_editor_property('decal_color', unreal.LinearColor(1.0, 1.0, 1.0, WEAR))
        dc.set_editor_property('fade_screen_size', 0.0008)
        dc.set_editor_property('sort_order', 5)
        made = [g]
    else:
        made = []
        for i in range(len(LINES)):
            z = top - TOP_BELOW - CAP * 0.5 - i * CAP * LEADING
            t = eas.spawn_actor_from_class(unreal.TextRenderActor, V(fx + nrm[0] * 0.6, fy + nrm[1] * 0.6, z), unreal.Rotator(roll=0.0, pitch=0.0, yaw=nyaw))
            t.set_actor_label('SD_' + STELE + '_carve%d' % i)
            tr = t.text_render
            tr.set_text(LINES[i])
            tr.set_editor_property('world_size', CAP * 1.3)
            tr.set_editor_property('horizontal_alignment', unreal.HorizTextAligment.EHTA_CENTER)
            tr.set_editor_property('vertical_alignment', unreal.VerticalTextAligment.EVRTA_TEXT_CENTER)
            tr.set_editor_property('text_render_color', unreal.Color(r=58, g=50, b=42, a=255))
            made.append(t)
    for a in made:
        a.set_folder_path('Set/' + SITE + '/inscription')
        a.tags = [unreal.Name('SD_' + SITE), unreal.Name('SD_' + SITE + '_inscription')]
    print('INSCRIPTION ' + ('decal ' + MI if (mi and not GREYBOX) else 'greybox TextRender x' + str(len(made))) + ' on ' + STELE + ' face_yaw=' + str(round(nyaw, 1)) + ' top=' + str(round(top, 1)) + ' at ' + str(round(fx, 1)) + ',' + str(round(fy, 1)) + ',' + str(round(zc, 1)) + ' facing_dot=' + str(round(d, 3)))
'''

GLANCE_BODY = r'''
tp = [a for a in eas.get_all_level_actors() if TAG in [str(t) for t in a.tags]]
if len(tp) != 1:
    print('GLANCE found ' + str(len(tp)) + ' actors tagged ' + TAG + ': nothing moved')
else:
    a = tp[0]
    was = a.get_actor_location()
    a.modify()
    a.set_actor_location(V(NEW[0], NEW[1], NEW[2]), False, False)
    print('GLANCE ' + a.get_actor_label() + ' ' + str(round(was.x, 1)) + ',' + str(round(was.y, 1)) + ',' + str(round(was.z, 1)) + ' -> ' + str(NEW))
    print('GLANCE package ' + a.get_package().get_name())
'''

GLANCE_SAVE_BODY = r'''
tp = [a for a in eas.get_all_level_actors() if TAG in [str(t) for t in a.tags]]
ok = unreal.EditorLoadingAndSavingUtils.save_packages([tp[0].get_package()], True) if len(tp) == 1 else False
print('GLANCE_SAVE ' + str(len(tp)) + ' ok=' + str(ok))
'''


def custom_step(step, argv):
    import place_setdress as ps
    ap = argparse.ArgumentParser(prog='v9_segalen_wall.py ' + step)
    ap.add_argument('--owner', default=os.environ.get('SETDRESS_OWNER', ''))
    ap.add_argument('--no-gate-check', action='store_true')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--greybox', action='store_true', help='inscription: TextRender lines even if the MI exists')
    ap.add_argument('--port', type=int, default=int(os.environ.get('HAYBA_PORT', 52342)))
    args = ap.parse_args(argv)
    doc = json.load(open(OUT_JSON, encoding='utf8'))
    ps.gate_check(argparse.Namespace(owner=args.owner, dry_run=args.dry_run, no_gate_check=args.no_gate_check), 'place')
    R = ps.Runner(args)
    ins = doc['inscription']
    gt = doc['glance_target']
    if step == 'inscription':
        Lg = glyph_layout()
        R.send('%s_inscription' % SID, ps.build_script(
            INSCRIPTION_BODY, SITE=SID, STELE=ins['on'], NORMAL_YAW=ins['face_normal_yaw'], MI=ins['material'],
            SIZE=ins['decal_size_cm'], TOP_BELOW=ins['top_below_stele_top_cm'],
            PAD_Z=round((CARVE_PAD_PX + MARGIN_PX) * Lg['m_per_px'] * 100.0, 1), WEAR=ins['wear'], GREYBOX=bool(args.greybox),
            LINES=ins['text'], CAP=round(ins['cap_cm'], 1), LEADING=LEADING))
        st = ps.read_state(SID)
        if not args.dry_run:
            st['dirty'] = True
            ps.write_state(SID, st)
    elif step == 'glance':
        out = R.send('%s_glance' % SID, ps.build_script(GLANCE_BODY, TAG=gt['tag'], NEW=gt['new_cm']))
        st = ps.read_state(SID)
        for line in (out or '').splitlines():
            if line.startswith('GLANCE package '):
                st['glance_package'] = line.split(' ', 2)[2].strip()
        ps.write_state(SID, st)
    elif step == 'glance-save':
        st = ps.read_state(SID)
        pkg = st.get('glance_package')
        if not pkg and not args.dry_run:
            raise SystemExit('run `glance` first (it records the target point\'s package)')
        if pkg:
            path = os.path.join(ROOT, 'Content', pkg[len('/Game/'):] + '.uasset')
            if os.path.exists(path) and not os.access(path, os.W_OK):
                raise SystemExit('%s is read-only on disk (committed-uassets-are-read-only memory note): make it writable '
                                 'first; nothing sent' % path)
        R.send('%s_glance_save' % SID, ps.build_script(GLANCE_SAVE_BODY, TAG=gt['tag']))


def run_editor(argv, materials=False):
    """Run a place_setdress.py step (or build_setdress_materials.py) with the V2 site file swapped for V9.json."""
    import place_setdress as ps
    ps.SITES_V2_JSON = OUT_JSON
    # the V2 lane's place_setdress.py drops the story sites (V2_STORY_SITES, S25 among them) and merges its group
    # files when it reads the V2 site file: read V9.json as it is.
    ps.merge_v2_groups = lambda sites, groups_dir=None: list(sites)
    if materials:
        import build_setdress_materials as bm
        argv = list(argv)
        if argv and argv[0] == 'variants' and SID not in argv:
            argv.insert(1, SID)
        sys.argv = ['build_setdress_materials.py'] + argv
        bm.main()
        return
    step = argv[0]
    rest = list(argv[1:])
    if step in ('load', 'unload') and '--own-load' not in rest:
        raise SystemExit('V9 runs inside V10\'s load (RUNBOOK.md window B): S25 lies in V10_HighVoice\'s load box. '
                         'Pass --own-load to load it on its own (then no other site may be loaded).')
    rest = [a for a in rest if a != '--own-load']
    if '--v2' not in rest:
        rest.append('--v2')
    if step == 'capture' and '--views' not in rest:
        rest += ['--views', 'carrier_a,carrier_b,carrier_c,glance_in,glance_face,orbit_a,orbit_b,orbit_c,contact,high34,far300,glance_fp']
    sys.argv = ['place_setdress.py', step] + ([] if step in ('list', 'probe') else [SID]) + rest
    ps.main()


def main():
    if len(sys.argv) > 1 and sys.argv[1] == 'editor':
        return run_editor(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == 'materials':
        return run_editor(sys.argv[2:], materials=True)
    if len(sys.argv) > 1 and sys.argv[1] in ('inscription', 'glance', 'glance-save'):
        return custom_step(sys.argv[1], sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == 'glyph':
        return write_glyph()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--no-plot', action='store_true')
    ap.add_argument('--png', default=OUT_PNG)
    args = ap.parse_args()
    G, S, recs, grecs, ins, target, tyaw, tpitch = build()
    frames = b21_frames(G, S, ins, target)
    appr = approach_frames(G, S, ins)
    wide = wide24_report(G, S)
    notes, bad = checks(G, S, recs, ins, frames, appr)
    site = write(G, S, recs, grecs, ins, target, tyaw, tpitch, frames, appr, wide, notes, bad)
    c = site['counts']
    print('%s (%s): %d placements, %d actors (ISM groups once), %d ISM instances, %d decals + the carved lines' % (
        SID, SET, c['placements'], c['actors'], c['ism_instances'], c['decals']))
    print('road clearance min %.2f m' % min(r['road_clear_m'] for r in recs))
    for n in notes:
        print(' ', n)
    print('G21 target: %s (look yaw %.1f, pitch %.1f)' % ([round(t * 100, 1) for t in target], tyaw, tpitch))
    print('G21 frames: stop / camera: boot point (x, y), text box (x0 x1 y0 y1), caps px @1080, text m, face deg, covered')
    for r in frames:
        print('  %-15s %-5s boot %s text %s %5.1f px %5.1f m %4.0f deg %s%s' % (
            r['stop'], r['mode'], r['boot'], r['text_box'], r['cap_px_1080'], r['text_dist_m'], r['face_angle_deg'],
            r['boot_covered_by'] or '', ' TEXT BEHIND KEEPER' if r['text_hidden_by_keeper'] else ''))
    print('CIN_24 shot 3 wide (provisional camera):', wide)
    if not args.no_plot:
        print('plot', plot(G, S, recs, grecs, ins, frames, target, args.png))
    print('wrote', OUT_JSON)
    if bad:
        print('VIOLATIONS:')
        for b in bad:
            print('  ', b)
        sys.exit(1)


if __name__ == '__main__':
    main()
