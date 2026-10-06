"""V2 the Promise Stones (road site S04_PromiseStones): the story set, composed with the set-dressing V2 method.

    python Tools/World/story_sets/v2_promise_stones.py              # write V2.json + the plot, print the checks
    python Tools/World/story_sets/v2_promise_stones.py --no-plot    # data and checks only
    python Tools/World/story_sets/v2_promise_stones.py editor <step> [place_setdress args]
          # runs Tools/World/place_setdress.py <step> S04_PromiseStones --v2 against Tools/World/story_sets/V2.json
    python Tools/World/story_sets/v2_promise_stones.py materials variants
          # runs Tools/World/build_setdress_materials.py variants S04_PromiseStones against V2.json
    python Tools/World/story_sets/v2_promise_stones.py stand|standcheck|inscribe|hooks|hooks-save [--owner ..] [--dry-run]
          # this set's own editor steps (the upright stones, the greybox inscription, the glance target)

Story (docs/story/storyline.md B03 and section 7 V2; story-events.json B03_PROMISE; CINEMATICS.md G03_PROMISE):
at road 450 m the road aims at the mountain for 110 m. B03 fires on a pass at 450: the glance G03_PROMISE eases the
POV (1.5 s) onto the target tagged Saskarta.Glance.PromiseStones, "the gap between the stones, where the mast crown
sits", holds it 2 s, and the Keeper reads the inscription (RADIO_B03_01, Saskartan with English subtitles: "Homes
may empty; let names remain. ..."). Kit: two tixjegefa_tier_2 stones STOOD UPRIGHT, x2.2 (4.25 m) and x1.5 (2.9 m),
unequal, flanking the sight line so the crown sits in the notch above the gap; a TextRender with the first line only.

The place: two unequal inscribed stones set upright on the valley side of the road, 10-16 m left at road 490, a
5 m gap between them opened square to the carrier's eye at the G03 hold. Their bases are sunk and chocked with
packing stones; a small worn paving of flat stones in front is where people stood to read them, reached by a trodden
path that leaves the road at the way-stone (Stele_WayStone_3, the INSCR lane's). A pebble cairn at the outer foot of
each stone, the last flower at the tall one; two natural rocks seat the pair in the falling ground behind; dead
shrubs creep in at the backs. Decay 0: kept, tended, whole. Nothing tall besides the stones: the sightline IS the
dressing. The storyline's "left 8 m and right 6 m" cannot frame the crown (it is 25.5 deg left of the road here), so
both stones stand left, on the crown bearing from the hold eye (V2.md section 3).

Offline only: nothing here talks to Unreal. The editor steps run place_setdress.py through `editor` (it swaps the V2
site file for V2.json; place_setdress.py itself is not edited) and this file's own steps through its Runner.
"""
import argparse
import json
import math
import os
import random
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
WORLD = os.path.dirname(HERE)
ROOT = os.path.dirname(os.path.dirname(WORLD))
sys.path.insert(0, os.path.join(ROOT, 'Tools', 'Story'))
sys.path.insert(0, os.path.join(ROOT, 'Tools', 'Look'))
sys.path.insert(0, WORLD)
import build_road_profile as brp  # noqa: E402  (read-only use: the heightmap and the road polyline)
import setdress_catalog  # noqa: E402  (read-only use: asset paths and sizes)

OUT_JSON = os.path.join(HERE, 'V2.json')
OUT_PNG = os.path.join(ROOT, 'docs', 'world', 'story_sets', 'V2.png')
SITES_V1_JSON = os.path.join(WORLD, 'setdress_sites.json')
SID = 'S04_PromiseStones'   # the road site: its V1 cairns carry the tag SD_S04_PromiseStones, so `clear` removes them
SET = 'V2'
S0 = 490.0                  # site origin, road m (storyline: the stones at 490 m)
TRIGGER_M = 450.0           # B03_PROMISE pass trigger (story-events.json)
GLANCE = dict(ease_in_s=1.5, hold_s=2.0)                         # story-events.json glances.G03_PROMISE
CARRIER_MS = 5.0            # story-events.json curves.carrier_speed_cms: 500 cm/s until 4,600
EYE_M = (1.22, 1.55)        # probe_ending.json carrier_eye_z (provisional) and CINEMATICS.md "POV at 155 cm"
HFOV = 90.0                 # the carrier POV
MID_T = GLANCE['ease_in_s'] + GLANCE['hold_s'] / 2.0              # 2.5 s: mid-hold
CROWN_CM = (298079.6, 483050.0, 10818.7 + 4300.0)                # HighVoice actor (task-L2-report) + crown centre 43 m
OLD_TARGET_CM = (584321.0, 431130.0, -33983.0)                   # Tools/GameFlow/glance_targets.json (9e60d2cb)
TARGET_TAG = 'Saskarta.Glance.PromiseStones'
L14_CM = (532351.1, 428099.8, -35954.1)                          # setdress_sites.json L14_OldTown centre (r 80 m)
L14_R_M = 80.0
CLEAR_M = 5.0               # road centreline -> footprint edge (build_setdress_sites.py CLEAR_M)
D_GAP_M = 30.0              # the gap: horizontal distance from the mid-hold eye along the crown bearing
GAP_M = 5.5                 # clear gap between the stones' inner faces: the crown drifts 4.3 m across it over the hold
STAGGER_M = 0.5             # the tall stone stands this much further back than the short one
TALL = dict(scale=2.2, sink_cm=38.0)
SHORT = dict(scale=1.5, sink_cm=28.0)
TEXT_LINES = ('HOMES MAY EMPTY;', 'LET NAMES REMAIN.')           # storyline V2: the first line only
TEXT_SIZE_CM = 11.0
TEXT_UP_CM = (178.0, 162.0)  # line centres above the ground at the face foot
CAT = setdress_catalog.load()


def asset(key):
    e = CAT[key]
    return e['path'], e['cat'], e['size_cm']


def draw_distance_cm(max_dim_m):
    """Max draw distance (never 0 = infinite: pcg-spawner-cull-distance-default); build_setdress_sites.py table."""
    for lim, d in ((0.6, 4000.0), (1.5, 6000.0), (4.0, 25000.0), (10.0, 80000.0)):
        if max_dim_m < lim:
            return d
    return 200000.0


def unit(deg):
    return np.array([math.cos(math.radians(deg)), math.sin(math.radians(deg))])


def bearing(p, q):
    return math.degrees(math.atan2(q[1] - p[1], q[0] - p[0]))


def wrap(a):
    return (a + 180.0) % 360.0 - 180.0


# ---------------------------------------------------------------------------- terrain and the site frame

class Ground:
    def __init__(self):
        self.T = brp.Terrain(brp.HEIGHTMAP)
        self.R = brp.Road(brp.SPLINE_POINTS_CM)
        self.P = self.R.P[:, :2] / 100.0
        k, _ = self.R.locate(S0)
        d = self.R.P[k + 1, :2] - self.R.P[k, :2]
        self.f = d / np.linalg.norm(d)                      # forward (travel)
        self.l = np.array([self.f[1], -self.f[0]])          # left of travel (UE top view: right = (-dy, dx))
        self.o = self.R.xy(S0) / 100.0                      # site origin, world m
        self.road_yaw = math.degrees(math.atan2(self.f[1], self.f[0]))

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

    def grad(self, x, y, h=1.0):
        gx = (self.z(x + h, y) - self.z(x - h, y)) / (2 * h)
        gy = (self.z(x, y + h) - self.z(x, y - h)) / (2 * h)
        return gx, gy

    def fall_yaw(self, x, y):
        gx, gy = self.grad(x, y)
        return math.degrees(math.atan2(-gy, -gx))

    def slope_deg(self, x, y):
        gx, gy = self.grad(x, y)
        return math.degrees(math.atan(math.hypot(gx, gy)))

    def heading(self, s):
        k, _ = self.R.locate(s)
        d = self.R.P[k + 1, :2] - self.R.P[k, :2]
        return math.degrees(math.atan2(d[1], d[0]))

    def road_eye(self, s, eye_m):
        x, y = (self.R.xy(s) / 100.0)
        return float(x), float(y), self.z(float(x), float(y)) + eye_m

    def road_dist(self, x, y):
        a, b = self.P[:-1], self.P[1:]
        ab = b - a
        p = np.array([x, y])
        t = np.clip(np.sum((p - a) * ab, axis=1) / np.sum(ab * ab, axis=1), 0, 1)
        q = a + ab * t[:, None]
        return float(np.min(np.linalg.norm(p - q, axis=1)))

    def yaw_local(self, yaw):
        """World yaw -> the site-frame angle (counter-clockwise from +u toward +v, v = left)."""
        return self.road_yaw - yaw


def waystone():
    """Stele_WayStone_3 (Tools/Story/place_steles.py plan(), the INSCR lane's; read-only)."""
    import place_steles
    it = [i for i in place_steles.plan() if i['name'] == 'Stele_WayStone_3'][0]
    return dict(name=it['name'], x=it['x'] / 100.0, y=it['y'] / 100.0, z=it['z'] / 100.0, yaw=it['yaw'],
                size_m=(0.30, 0.20, 0.75))


def v1_standins():
    """The site's V1 dressing (LANE_SD, placed and saved): 10 cairn stones + 1 flower ISM. `clear` removes them."""
    doc = json.load(open(SITES_V1_JSON, encoding='utf8'))
    site = [s for s in doc['sites'] if s['id'] == SID][0]
    return [(p['id'], p['key'], p['x_cm'] / 100.0, p['y_cm'] / 100.0) for p in site['placements']]


# ---------------------------------------------------------------------------- the composition

SETTLE = {   # SETDRESS_V2.md section 3 contact classes -> the place_setdress settle config
    'stand': dict(mode='none', max_tilt_deg=0, rand_tilt_deg=0, z_rule='min'),     # this file's `stand` step
    'lie': dict(mode='trace', max_tilt_deg=25, rand_tilt_deg=6, z_rule='mean'),
    'rest': dict(mode='physics', max_tilt_deg=15, rand_tilt_deg=6, z_rule='max'),
    'ism_stone': dict(mode='trace', max_tilt_deg=35, rand_tilt_deg=25, z_rule='mean'),
    'ism_flag': dict(mode='trace', max_tilt_deg=9, rand_tilt_deg=2, z_rule='mean'),
    'ism_shrub': dict(mode='trace', max_tilt_deg=15, rand_tilt_deg=0, z_rule='mean'),
}


class Site:
    def __init__(self, G):
        self.G = G
        self.items = []
        self.ground = []
        self.lanes = []
        self.rng = random.Random(3)

    def add(self, key, x, y, group, contact, scale=1.0, yaw=0.0, pitch=0.0, roll=0.0, sink_cm=6.0, ism=False,
            block=None, stack=False, drop_cm=0, rand_tilt=None, role='', material_set=None, settle_kind=None,
            size_m=None):
        path, cat, size = asset(key)
        u, v = self.G.local(x, y)
        cfg = dict(SETTLE[settle_kind or contact])
        if rand_tilt is not None:
            cfg['rand_tilt_deg'] = rand_tilt
        if size_m is None:
            size_m = [round(s * scale / 100.0, 3) for s in size]
        settle = dict(mode=cfg['mode'], sink_cm=int(round(sink_cm)), max_tilt_deg=cfg['max_tilt_deg'],
                      rand_tilt_deg=cfg['rand_tilt_deg'], z_rule=cfg['z_rule'], drop_cm=int(drop_cm), z_offset_cm=0)
        it = dict(key=key, asset=path, cat=cat, u=u, v=v, x=float(x), y=float(y), yaw=round(yaw % 360.0, 2),
                  pitch=pitch, roll=roll, scale=round(scale, 3), size_m=size_m, settle=settle, group=group, ism=ism,
                  stack=stack, attach=False, contact=contact, block=block, role=role, material_set=material_set)
        self.items.append(it)
        return it

    def patch(self, surface, x, y, yaw, length, width, strength, shape='ellipse', sort=0, role=''):
        u, v = self.G.local(x, y)
        self.ground.append(dict(surface=surface, u=u, v=v, yaw=self.G.yaw_local(yaw), length=length, width=width,
                                strength=strength, shape=shape, sort=sort, role=role))

    def path(self, pts_xy, width, strength, role):
        pts = [self.G.local(x, y) for x, y in pts_xy]
        self.lanes.append(dict(pts=pts, width=width))
        for (u0, v0), (u1, v1) in zip(pts[:-1], pts[1:]):
            L = math.hypot(u1 - u0, v1 - v0)
            self.ground.append(dict(surface='path', u=(u0 + u1) / 2, v=(v0 + v1) / 2,
                                    yaw=math.degrees(math.atan2(v1 - v0, u1 - u0)), length=L + width, width=width,
                                    strength=strength, shape='capsule', sort=3, role=role))

    def on_lane(self, u, v, margin=0.4):
        for ln in self.lanes:
            for (u0, v0), (u1, v1) in zip(ln['pts'][:-1], ln['pts'][1:]):
                du, dv = u1 - u0, v1 - v0
                L2 = du * du + dv * dv
                t = max(0.0, min(1.0, ((u - u0) * du + (v - v0) * dv) / L2))
                if math.hypot(u0 + t * du - u, v0 + t * dv - v) < ln['width'] / 2 + margin:
                    return True
        return False


def stone_dims(scale):
    """An upright tixjegefa_tier_2 (pitch 90: local X up, local Y across, local Z toward the back): the size in the
    stone's yaw frame (forward = thickness, right = face width, up = height), metres."""
    sx, sy, sz = CAT['FAB_TempleStones']['size_cm']
    return [round(sz * scale / 100.0, 3), round(sy * scale / 100.0, 3), round(sx * scale / 100.0, 3)]


def compose(G):
    S = Site(G)
    rng = S.rng
    ws = waystone()
    S.waystone = ws

    # 1. the frame of the place: the carrier eye at mid-hold, the crown bearing from it, the gap on that bearing.
    eye = G.road_eye(TRIGGER_M + CARRIER_MS * MID_T, EYE_M[0])
    cb = bearing(eye, (CROWN_CM[0] / 100.0, CROWN_CM[1] / 100.0))
    fc = unit(cb)                      # along the sightline, away from the road
    rc = unit(cb + 90.0)               # the viewer's right (toward the road side of the pair)
    gap = np.array(eye[:2]) + D_GAP_M * fc
    S.frame = dict(eye=eye, cb=cb, fc=fc, rc=rc, gap=gap)

    # 2. the stones: stood upright (pitch 90), each turned square to the mid-hold eye (its original top face, the
    #    scanned face, looks back at the road). The TALL one right of the gap, on the road side, where the ground is
    #    higher; the SHORT one left of it, downhill and 0.5 m further back. On this slope (the hollow falls away
    #    left) that is the only way round whose tops read unequal from the carrier: tall-left puts both tops at one
    #    height (the tall one stands 1.2 m lower). Placed by this file's `stand` step (plumb, base sunk below the
    #    LOWEST ground under the footprint, so no edge shows a gap), not by place_setdress settle.
    dt, ds = stone_dims(TALL['scale']), stone_dims(SHORT['scale'])
    ct = gap + rc * (GAP_M / 2 + dt[1] / 2) - fc * (STAGGER_M / 2)
    cs = gap - rc * (GAP_M / 2 + ds[1] / 2) + fc * (STAGGER_M / 2)
    stones = []
    for key, c, dims, cfg, name in (('FAB_TempleStones', ct, dt, TALL, 'tall'), ('FAB_TempleStones', cs, ds, SHORT, 'short')):
        yw = bearing(eye, c)
        it = S.add(key, c[0], c[1], 'stones', 'stand', scale=cfg['scale'], yaw=yw, pitch=90.0, sink_cm=cfg['sink_cm'],
                   block='stone_' + name, size_m=dims, material_set='stone',
                   role=('FOCAL: the tall promise stone x%.1f, inscribed' if name == 'tall' else
                         'FOCAL: the short promise stone x%.1f') % cfg['scale'])
        it['stone'] = name
        stones.append(it)
    S.tall, S.short = stones
    for st in stones:
        st['pred'] = predict_stand(G, st)

    # 3. packing: chock stones wedged against the four faces of each base (the multi-point contact that makes a
    #    set stone), 35-40 % buried; more on the downhill (left, valley) side, where the ground falls away.
    for st in stones:
        f, r, (ht, hw) = stone_axes(st)
        c = np.array([st['x'], st['y']])
        fall = unit(G.fall_yaw(*c))
        faces = [(f, ht, hw, r), (-f, ht, hw, r), (r, hw, ht, f), (-r, hw, ht, f)]
        for n, half_n, half_t, t in faces:
            k = 3 if half_t > 0.9 else 2
            if n @ fall > 0.3:
                k += 1
            for i in range(k):
                a = (i + 0.5) / k * 2 - 1
                key = rng.choice(['LF_Rock_08', 'LF_Rock_08', 'AB_Cobble_04'])
                sc = rng.uniform(0.62, 0.9) if key == 'LF_Rock_08' else rng.uniform(1.0, 1.3)
                rad = max(CAT[key]['size_cm'][:2]) * sc / 200.0
                p = c + n * (half_n + rad * 0.72) + t * (a * half_t * 0.85 + rng.uniform(-0.06, 0.06))
                h = CAT[key]['size_cm'][2] * sc
                S.add(key, p[0], p[1], 'packing', 'lie', scale=sc, yaw=rng.uniform(0, 360), sink_cm=0.38 * h, ism=True,
                      block='base', settle_kind='ism_stone', material_set='stone',
                      role='packing stone wedged at the base of the %s stone' % st['stone'])

    # 4. the standing place: a worn paving of flat stones from the crown line to the inscribed (tall) stone, where people
    #    stood to read it and, a step to the left, to see the High Voice standing IN the notch (up close the crown shows
    #    between the stones, below the tall one's top). A loose grid along the pair, cells missing at the worn edges; its back
    #    row stops a hand short of the tall stone's packing.
    P = gap + rc * 1.75 - fc * 2.35
    S.frame['paving'] = P
    ga = cb + 90.0
    cols, rows = 8, 4
    pa, pb = 0.50, 0.44                    # cell pitch across (the 49 cm side) and along the sightline (40 cm)
    for i in range(cols):
        for j in range(rows):
            x0 = (i - (cols - 1) / 2) * pa
            y0 = (j - (rows - 1) / 2) * pb + 0.2
            edge = max(abs(x0) / (cols * pa / 2), abs(y0 - 0.2) / (rows * pb / 2))
            if rng.random() < 0.08 + 0.55 * edge ** 3:
                continue
            p = P + rc * (x0 + rng.uniform(-0.04, 0.04)) + fc * (y0 + rng.uniform(-0.04, 0.04))
            key = rng.choice(['AB_Cobble_01', 'AB_Cobble_02', 'AB_Cobble_03', 'AB_Cobble_05'])
            if rng.random() < 0.18:
                key = 'AB_Cobble_04'
            S.add(key, p[0], p[1], 'paving', 'lie', scale=rng.uniform(0.95, 1.08), yaw=ga + rng.uniform(-9, 9),
                  sink_cm=7, ism=True, block='paving', settle_kind='ism_flag', material_set='stone',
                  role='the paving where people stood to read')
    # the trodden path: from the road verge beside the way-stone (it marks the turn-off) to the paving's road edge
    w = np.array([ws['x'], ws['y']])
    mouth = np.array(G.world(G.local(*w)[0] + 1.6, 4.3))
    front = P - fc * 1.0 - rc * 0.2
    mid = (mouth + front) / 2 + rc * 0.45
    S.path([tuple(mouth), tuple(mid), tuple(front)], width=1.0, strength=0.8,
           role='the trodden way from the way-stone to the stones')
    S.patch('packed_earth', P[0] - fc[0] * 0.15, P[1] - fc[1] * 0.15, ga, 5.0, 3.2, 0.78, sort=0,
            role='the standing place: packed earth under and round the paving')
    for st, L, W in ((S.tall, 3.2, 2.6), (S.short, 2.4, 2.0)):
        S.patch('rubble_dust', st['x'], st['y'], st['yaw'] + 90.0, L, W, 0.55, sort=1,
                role='the disturbed ground where the %s stone was set' % st['stone'])

    # 5. the cairns and the last flower: a pebble cairn at the OUTER foot of each stone (not in front of its face),
    #    stones added by passers-by; the flower (the one living thing) at the tall stone's front outer corner.
    for st, side, n in ((S.tall, +1.0, 5), (S.short, -1.0, 4)):
        f, r, (ht, hw) = stone_axes(st)
        base = np.array([st['x'], st['y']]) + r * side * (hw + 0.78) - f * 0.25
        blk = 'cairn_' + st['stone']
        S.add('LF_Rock_08', base[0], base[1], 'cairns', 'lie', scale=1.15, yaw=rng.uniform(0, 360), sink_cm=10,
              block=blk, rand_tilt=4, material_set='stone', role='cairn base at the %s stone' % st['stone'])
        stack = [('LF_Rock_08', 0.82, 34), ('LF_Rock_07', 1.35, 58), ('LF_Rock_08', 0.58, 78), ('LF_Rock_07', 0.95, 94)][:n - 1]
        for key, sc, drop in stack:
            q = base + np.array([rng.uniform(-0.05, 0.05), rng.uniform(-0.05, 0.05)])
            S.add(key, q[0], q[1], 'cairns', 'rest', scale=sc, yaw=rng.uniform(0, 360), sink_cm=0, stack=True, drop_cm=drop,
                  block=blk, material_set='stone', role='cairn stone at the %s stone' % st['stone'])
    f, r, (ht, hw) = stone_axes(S.tall)
    fl = np.array([S.tall['x'], S.tall['y']]) - f * (ht + 0.42) + r * (hw - 0.1)
    S.add('LF_Flowers_01', fl[0], fl[1], 'flower', 'lie', scale=0.35, yaw=rng.uniform(0, 360), sink_cm=3, ism=True,
          block='creep', settle_kind='ism_shrub', role='the last flower, at the tall stone')

    # 6. two natural rocks seat the pair in the ground falling to the valley: behind the stones, low, 40 % buried,
    #    never between the carrier and the gap.
    for st, key, sc, side, back, yoff in ((S.short, 'LF_Rock_05', 0.55, -1.0, 1.25, 30.0), (S.tall, 'LF_Rock_03', 0.44, 1.0, 1.0, -20.0)):
        f, r, (ht, hw) = stone_axes(st)
        p = np.array([st['x'], st['y']]) + f * (ht + back) + r * side * (hw * 0.55)
        h = CAT[key]['size_cm'][2] * sc
        S.add(key, p[0], p[1], 'rocks', 'lie', scale=sc, yaw=st['yaw'] + yoff, sink_cm=0.40 * h, block='rock_' + st['stone'],
              rand_tilt=5, material_set='stone', role='natural rock behind the %s stone' % st['stone'])

    # 7. creep: dead shrubs at the backs of the stones, at the rocks' feet and round the paving; never on the path.
    rocks = [it for it in S.items if it['group'] == 'rocks']
    spots = []
    for st in stones:
        f, r, (ht, hw) = stone_axes(st)
        c = np.array([st['x'], st['y']])
        spots += [(c + f * (ht + 0.45) - r * hw * 0.6, 'FAB_Shrub_C', 0.9), (c + f * (ht + 0.4) + r * hw * 0.7, 'FAB_Shrub_D', 1.1)]
    for rk in rocks:
        c = np.array([rk['x'], rk['y']])
        spots += [(c + fc * 0.9 + rc * 0.5, 'FAB_Shrub_G', 0.8), (c - rc * 0.95, 'FAB_Shrub_E', 0.9)]
    spots += [(P + rc * 2.3 - fc * 0.6, 'FAB_Shrub_C', 0.75), (P - fc * 1.5 + rc * 1.5, 'FAB_Shrub_D', 1.0),
              (P - rc * 2.4 - fc * 0.9, 'FAB_Shrub_E', 0.8)]
    for p, key, sc in spots:
        u, v = G.local(*p)
        if S.on_lane(u, v):
            continue
        S.add(key, p[0], p[1], 'creep', 'lie', scale=sc, yaw=rng.uniform(0, 360), sink_cm=5, ism=True, block='creep',
              settle_kind='ism_shrub', role='dead shrub creeping in')

    # the save judge (check2) measures only the solo actors; push every ISM piece out of the solids and of each other
    # (the minimum translation) and leave out any that finds no room within 0.6 m or lands on the path.
    S.moved = declash(G, S)
    left = clash_pairs(G, S)
    S.dropped = [it for it in S.items if it['ism'] and (S.moved[id(it)] > 0.6 or
                                                        (it['group'] != 'paving' and S.on_lane(it['u'], it['v'], 0.15)) or
                                                        any(a is it for _, _, a, b in left))]
    S.items = [it for it in S.items if all(it is not d for d in S.dropped)]
    return S


def stone_axes(st):
    """(forward, right, (half thickness, half width)) of an upright stone in world metres."""
    f = unit(st['yaw'])
    r = unit(st['yaw'] + 90.0)
    return f, r, (st['size_m'][0] / 2.0, st['size_m'][1] / 2.0)


def stone_grid(st, n=4, inset=0.92):
    """n x n world points over an upright stone's footprint (the same grid the `stand` step traces)."""
    f, r, (ht, hw) = stone_axes(st)
    c = np.array([st['x'], st['y']])
    ks = np.linspace(-inset, inset, n)
    return [c + f * a * ht + r * b * hw for a in ks for b in ks]


def predict_stand(G, st):
    """The `stand` step offline: plumb, base = the lowest ground under the footprint - sink."""
    gz = [G.z(*p) for p in stone_grid(st)]
    base = min(gz) - st['settle']['sink_cm'] / 100.0
    top = base + st['size_m'][2]
    return dict(base=base, top=top, ground_min=min(gz), ground_max=max(gz), relief=max(gz) - min(gz),
                buried_min=min(gz) - base, buried_max=max(gz) - base, proud_min=top - max(gz), proud_max=top - min(gz))


# ---------------------------------------------------------------------------- ISM declash (as v8_ledge.py)

ISM_ALLOW = dict(stone=0.05, shrub=0.10, ism=0.04)   # plan overlap allowed: stone / shrub into a solid, ISM x ISM


def obb_xy(it, pad=0.0):
    a = math.radians(it['yaw'])
    ax = (math.cos(a), math.sin(a))
    ay = (-math.sin(a), math.cos(a))
    hx, hy = it['size_m'][0] / 2 + pad, it['size_m'][1] / 2 + pad
    return [(it['x'] + sx * hx * ax[0] + sy * hy * ay[0], it['y'] + sx * hx * ax[1] + sy * hy * ay[1])
            for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]


def plan_mtv(A, B):
    """Separating-axis test of two convex quads in plan: (overlap depth m, unit axis to push A out of B), or (0, None)."""
    best, axis = 1e9, None
    ca = (sum(p[0] for p in A) / 4, sum(p[1] for p in A) / 4)
    cb = (sum(p[0] for p in B) / 4, sum(p[1] for p in B) / 4)
    for poly in (A, B):
        for i in range(4):
            (x0, y0), (x1, y1) = poly[i], poly[(i + 1) % 4]
            n = (y0 - y1, x1 - x0)
            ln = math.hypot(*n)
            n = (n[0] / ln, n[1] / ln)
            pa = [x * n[0] + y * n[1] for x, y in A]
            pb = [x * n[0] + y * n[1] for x, y in B]
            o = min(max(pa), max(pb)) - max(min(pa), min(pb))
            if o <= 0:
                return 0.0, None
            if o < best:
                sgn = 1.0 if (ca[0] - cb[0]) * n[0] + (ca[1] - cb[1]) * n[1] >= 0 else -1.0
                best, axis = o, (n[0] * sgn, n[1] * sgn)
    return best, axis


def is_soft(it):
    return it['cat'] == 'shrub' or it['group'] in ('creep', 'flower')


def clash_pairs(G, S):
    """Plan overlaps beyond ISM_ALLOW: ISM stones / flags / shrubs into the solids and into each other."""
    solids = [it for it in S.items if not it['ism'] and not it['stack']]
    isms = [it for it in S.items if it['ism']]
    out = []
    for it in isms:
        allow = ISM_ALLOW['shrub' if is_soft(it) else 'stone']
        for sd in solids:
            d = plan_mtv(obb_xy(it), obb_xy(sd))[0]
            if d > allow + 1e-6:
                out.append((d, allow, it, sd))
    for i in range(len(isms)):
        for j in range(i + 1, len(isms)):
            d = plan_mtv(obb_xy(isms[i]), obb_xy(isms[j]))[0]
            if d > ISM_ALLOW['ism'] + 1e-6:
                out.append((d, ISM_ALLOW['ism'], isms[i], isms[j]))
    return out


def declash(G, S, rounds=80):
    start = {id(it): (it['x'], it['y']) for it in S.items if it['ism']}
    for _ in range(rounds):
        pairs = clash_pairs(G, S)
        if not pairs:
            break
        done = set()
        for d, allow, a, b in sorted(pairs, key=lambda p: -p[0]):
            mover = a if a['ism'] and id(a) not in done else (b if b['ism'] and id(b) not in done else None)
            if mover is None:
                continue
            fixed = b if mover is a else a
            dd, ax = plan_mtv(obb_xy(mover), obb_xy(fixed))
            if ax is None:
                continue
            mover['x'] += ax[0] * (dd - allow + 0.02)
            mover['y'] += ax[1] * (dd - allow + 0.02)
            mover['u'], mover['v'] = G.local(mover['x'], mover['y'])
            done.add(id(mover))
    return {id(it): math.hypot(it['x'] - start[id(it)][0], it['y'] - start[id(it)][1]) for it in S.items if it['ism']}


# ---------------------------------------------------------------------------- 3D boxes and the story frames

def box_points(G, it):
    """8 world corners (m) of the predicted pose (stones: the `stand` pose; others: on the ground, level)."""
    cs = obb_xy(it)
    if it['contact'] == 'stand':
        z0, z1 = it['pred']['base'], it['pred']['top']
    else:
        z0 = G.z(it['x'], it['y']) - it['settle']['sink_cm'] / 100.0
        z1 = z0 + it['size_m'][2]
    return [(x, y, z) for x, y in cs for z in (z0, z1)]


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
        d = np.array(p, dtype=float) - np.array(eye, dtype=float)
        z = d @ F
        if z <= 0.05:
            out.append(None)
            continue
        out.append(((d @ Rt) / z / th, (d @ U) / z / tv))
    return out


def look_at(eye, tgt):
    dx, dy, dz = tgt[0] - eye[0], tgt[1] - eye[1], tgt[2] - eye[2]
    return math.degrees(math.atan2(dy, dx)), math.degrees(math.atan2(dz, math.hypot(dx, dy)))


def smooth(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def glance_pose(G, t, eye_m, target_m):
    """The G03 camera t s after the trigger: carrier at 5 m/s, the view eased from the road heading (pitch 0) onto the
    target (SaskartaEventRunner::GlanceTick re-aims from the pawn's view point every tick), held, then left where the
    hold ended (EndGlance gives the look input back; nothing eases the view back)."""
    tt = min(t, GLANCE['ease_in_s'] + GLANCE['hold_s'])
    s = TRIGGER_M + CARRIER_MS * tt
    eye = G.road_eye(s, eye_m)
    y0 = G.heading(TRIGGER_M)
    yT, pT = look_at(eye, target_m)
    a = smooth(tt / GLANCE['ease_in_s'])
    if t > tt:
        eye = G.road_eye(TRIGGER_M + CARRIER_MS * t, eye_m)
    return TRIGGER_M + CARRIER_MS * t, eye, y0 + a * wrap(yT - y0), a * pT, a


def screen_box(q):
    q = [p for p in q if p is not None]
    if not q:
        return None
    xs, ys = [p[0] for p in q], [p[1] for p in q]
    return (min(xs), max(xs), min(ys), max(ys))


def fmt_box(b):
    return None if b is None else tuple(round(float(v), 3) for v in b)


def target_point(G, S):
    """The new glance target: in the gap, at a height between the tall stone's top and the crown line, so the crown
    sits just above the frame centre and the stones' tops just below it at mid-hold."""
    eye = S.frame['eye']
    gx, gy = S.frame['gap']
    d = math.hypot(gx - eye[0], gy - eye[1])
    cy_, cp = look_at(eye, tuple(c / 100.0 for c in CROWN_CM))
    tp = math.degrees(math.atan2(S.tall['pred']['top'] - eye[2], d))
    p = tp + 0.55 * (cp - tp)
    return (float(gx), float(gy), eye[2] + d * math.tan(math.radians(p)))


def frame_row(G, S, eye, yw, pt):
    """One frame: crown, the stones' screen boxes, the inner edges of the gap, the Old Town, the target."""
    crown = project(eye, yw, pt, [tuple(c / 100.0 for c in CROWN_CM)])[0]
    bt = screen_box(project(eye, yw, pt, box_points(G, S.tall)))
    bs = screen_box(project(eye, yw, pt, box_points(G, S.short)))
    town = project(eye, yw, pt, [(L14_CM[0] / 100.0, L14_CM[1] / 100.0, L14_CM[2] / 100.0 + 4.0)])[0]
    # the gap on screen: from the right edge of the left-hand stone to the left edge of the right-hand one
    ingap = False
    if crown is not None and bt is not None and bs is not None:
        lb, rb = (bt, bs) if bt[0] + bt[1] < bs[0] + bs[1] else (bs, bt)
        ingap = lb[1] < crown[0] < rb[0] and crown[1] > max(bt[3], bs[3])
    above = crown is not None and all(b is None or not (b[0] < crown[0] < b[1]) or crown[1] > b[3] for b in (bt, bs))
    return dict(crown=None if crown is None else fmt_box(crown), tall=fmt_box(bt), short=fmt_box(bs),
                town=None if town is None else fmt_box(town), crown_in_gap=bool(ingap), crown_clear=bool(above))


def glance_report(G, S, target_m, eye_m=EYE_M[0]):
    rows = []
    for t in np.arange(0.0, 5.01, 0.25):
        s, eye, yw, pt, a = glance_pose(G, float(t), eye_m, target_m)
        r = frame_row(G, S, eye, yw, pt)
        r.update(t=round(float(t), 2), road_m=round(s, 2), yaw=round(yw, 2), pitch=round(pt, 2), ease=round(a, 2))
        rows.append(r)
    return rows


def approach_report(G, S):
    rows = []
    for s in (380.0, 400.0, 420.0, 430.0, 440.0, 450.0):
        eye = G.road_eye(s, EYE_M[0])
        yw = G.heading(s)
        r = frame_row(G, S, eye, yw, 0.0)
        c = S.frame['gap']
        dist = math.dist(eye[:2], c)
        tan, _ = G.T.horizon_tan(np.array([eye[0] * 100]), np.array([eye[1] * 100]), np.array([eye[2]]),
                                 np.array([c[0] * 100]), np.array([c[1] * 100]), skip_far_m=3.0)
        r.update(road_m=s, dist_m=round(dist, 1),
                 terrain_los=bool((S.tall['pred']['top'] - 1.0 - eye[2]) / dist > float(tan[0])))
        rows.append(r)
    return rows


def crown_occlusion(G, S):
    """Along the road 380-540 m (every 2 m, both eyes): is the crown ever behind a dressing piece? The crown direction
    against each piece's projected box, in a view aimed at the crown."""
    hits = []
    tg = tuple(c / 100.0 for c in CROWN_CM)
    for eye_m in EYE_M:
        for s in np.arange(380.0, 541.0, 2.0):
            eye = G.road_eye(float(s), eye_m)
            yw, pt = look_at(eye, tg)
            for it in S.items:
                if it['ism'] and max(it['size_m']) < 0.5:
                    continue
                b = screen_box(project(eye, yw, pt, box_points(G, it)))
                if b is not None and b[0] < 0.0 < b[1] and b[2] < 0.0 < b[3]:
                    hits.append((float(s), eye_m, it['key']))
    return hits


def town_occlusion(G, S, target_m):
    """Over the G03 hold: does a stone cover the Old Town's centre (L14, 560 m, 'a far silhouette' in G03's frame)?"""
    worst = []
    for eye_m in EYE_M:
        for t in np.arange(GLANCE['ease_in_s'], GLANCE['ease_in_s'] + GLANCE['hold_s'] + 0.01, 0.25):
            s, eye, yw, pt, a = glance_pose(G, float(t), eye_m, target_m)
            town = project(eye, yw, pt, [(L14_CM[0] / 100.0, L14_CM[1] / 100.0, L14_CM[2] / 100.0 + 4.0)])[0]
            for it in (S.tall, S.short):
                b = screen_box(project(eye, yw, pt, box_points(G, it)))
                if town is not None and b is not None and b[0] < town[0] < b[1] and b[2] < town[1] < b[3]:
                    worst.append((round(float(t), 2), eye_m, it['stone']))
    return worst


def standing_frame(G, S, eye_m=1.6):
    """A walker on the paving, on the crown line (2.8 m before the gap), looking at the crown: the crown must show
    between the stones' inner faces and below the tall stone's top, IN the notch (the promise seen on site; the short
    stone stands downhill, so its top is below a walker's eye)."""
    p = S.frame['gap'] - S.frame['fc'] * 2.8
    eye = (float(p[0]), float(p[1]), G.z(*p) + eye_m)
    yw, pt = look_at(eye, tuple(c / 100.0 for c in CROWN_CM))
    r = frame_row(G, S, eye, yw, pt)
    bt, bs, c = r['tall'], r['short'], r['crown']
    lb, rb = (bt, bs) if bt[0] + bt[1] < bs[0] + bs[1] else (bs, bt)
    r['framed'] = bool(lb[1] < c[0] < rb[0] and c[1] < max(bt[3], bs[3]))
    r['eye_cm'] = [round(v * 100, 1) for v in eye]
    return r


def town_hidden(G, S, target_m, eye_m=EYE_M[0]):
    """Share of the Old Town's screen width (its 80 m radius, at its centre height) behind a stone at mid-hold."""
    s, eye, yw, pt, a = glance_pose(G, MID_T, eye_m, target_m)
    tc = np.array([L14_CM[0] / 100.0, L14_CM[1] / 100.0])
    side = unit(bearing(eye, tc) + 90.0)
    ends = [project(eye, yw, pt, [(*(tc + side * k * L14_R_M), L14_CM[2] / 100.0 + 4.0)])[0] for k in (-1.0, 1.0)]
    x0, x1 = sorted(e[0] for e in ends)
    y = (ends[0][1] + ends[1][1]) / 2
    xs = np.linspace(x0, x1, 200)
    hid = np.zeros_like(xs, dtype=bool)
    for it in (S.tall, S.short):
        b = screen_box(project(eye, yw, pt, box_points(G, it)))
        if b is not None and b[2] < y < b[3]:
            hid |= (xs > b[0]) & (xs < b[1])
    return float(hid.mean())


# ---------------------------------------------------------------------------- records

STORY_FRAME_CULL_CM = 6000.0   # the G03 hold sees the set from 25-40 m: nothing may pop or fade inside that frame


def set_draw_distance(it):
    """The V1 table (never 0), with two exceptions: the pair culls together at the tall stone's distance (a lone tall
    stone from the first 240 m would read as one stone), and every small piece of the set stays drawn to 60 m, beyond
    the G03 hold (25-40 m) and the approach from 430 m."""
    if it['group'] == 'stones':
        return draw_distance_cm(max(stone_dims(TALL['scale'])))
    return max(draw_distance_cm(max(it['size_m'])), STORY_FRAME_CULL_CM)


def to_record(G, S, i, it):
    x, y = it['x'], it['y']
    gz = G.z(x, y)
    rid = '%s_v2_%03d' % (SID, i)
    it['id'] = rid
    rec = dict(id=rid, key=it['key'], asset=it['asset'], kind='SM', cat=it['cat'],
               x_cm=round(x * 100, 1), y_cm=round(y * 100, 1), ground_z_cm=round(gz * 100, 1),
               yaw=round(it['yaw'], 2), pitch=float(it['pitch']), roll=float(it['roll']), scale=it['scale'],
               scale_range=[it['scale'], it['scale']], settle=it['settle'], group=it['group'],
               folder='Set/%s/%s' % (SID, it['group']), data_layer='DL_SetDress', ism=it['ism'], stack=it['stack'],
               attach=False, run_id=None, collision=not it['ism'],
               foliage_exclude=it['group'] in ('stones', 'rocks', 'cairns'),
               draw_distance_cm=set_draw_distance(it), cast_shadow=it['group'] not in ('paving',),
               size_m=it['size_m'], slope_deg=round(G.slope_deg(x, y), 1), road_clear_m=None, contact=it['contact'],
               site_uv=[round(it['u'], 2), round(it['v'], 2)], role=it['role'], story_set=SET)
    if it['block']:
        rec['block'] = it['block']
    if it['material_set']:
        rec['material_set'] = it['material_set']
    if it['contact'] == 'stand':
        p = it['pred']
        rec['stand'] = dict(base_z_cm=round(p['base'] * 100, 1), top_z_cm=round(p['top'] * 100, 1),
                            sink_cm=it['settle']['sink_cm'], relief_cm=round(p['relief'] * 100, 1),
                            proud_m=[round(p['proud_min'], 2), round(p['proud_max'], 2)])
    rec['road_clear_m'] = round(min(G.road_dist(*c) for c in obb_xy(it)), 2)
    return rec


def ground_records(G, S):
    out = []
    for i, g in enumerate(S.ground):
        x, y = G.world(g['u'], g['v'])
        zs = []
        a = math.radians(-g['yaw'])
        for sl in (-0.5, 0.0, 0.5):
            for sw in (-0.5, 0.0, 0.5):
                du = sl * g['length'] * math.cos(a) - sw * g['width'] * math.sin(a)
                dv = -(sl * g['length'] * math.sin(a) + sw * g['width'] * math.cos(a))
                zs.append(G.zuv(g['u'] + du, g['v'] + dv))
        relief = max(zs) - min(zs)
        out.append(dict(id='%s_v2_g%02d' % (SID, i), surface=g['surface'], shape=g['shape'],
                        x_cm=round(x * 100, 1), y_cm=round(y * 100, 1), z_cm=round((max(zs) + min(zs)) / 2 * 100, 1),
                        yaw=round((G.road_yaw - g['yaw']) % 360.0, 1), length_m=round(g['length'], 2),
                        width_m=round(g['width'], 2), depth_m=round(max(3.0, relief + 1.2), 1),
                        strength=g['strength'], sort=g['sort'], role=g['role']))
    return out


def inscription(G, S):
    """The greybox inscription: two TextRender lines on the tall stone's road-facing face (the `inscribe` step
    computes the face from the placed actor; these are the offline predictions for the plot and the checks)."""
    st = S.tall
    f, r, (ht, hw) = stone_axes(st)
    c = np.array([st['x'], st['y']])
    foot = c - f * (ht + 0.05)
    gz = G.z(*foot)
    lines = []
    for k, (txt, up) in enumerate(zip(TEXT_LINES, TEXT_UP_CM)):
        p = c - f * (ht + 0.03)
        lines.append(dict(id='%s_v2_t%02d' % (SID, k), text=txt, x_cm=round(p[0] * 100, 1), y_cm=round(p[1] * 100, 1),
                          z_cm=round((gz + up / 100.0) * 100, 1), yaw=round((st['yaw'] + 180.0) % 360.0, 2),
                          world_size_cm=TEXT_SIZE_CM, up_from_face_foot_cm=up))
    return dict(stone_id=st['id'], face='the stone local +Z face (its original top), facing the road', lines=lines,
                color_rgb=[38, 30, 24], out_cm=3.0,
                final='a carved-glyph decal (M_Saskarta_CarvedGlyph + a new T_Inscription texture), inscriptions lane')


def views(G, S, target_m):
    """V2 capture views (place_setdress.py capture --v2) plus the story frames. cam/look in world cm."""
    gx, gy = S.frame['gap']
    focus = [round(gx * 100, 1), round(gy * 100, 1), round((G.z(gx, gy) + 1.6) * 100, 1)]
    fc, rc = S.frame['fc'], S.frame['rc']
    out = []

    def cam(name, x, y, z, look=None, note=''):
        out.append(dict(name=name, cam_cm=[round(x * 100, 1), round(y * 100, 1), round(z * 100, 1)],
                        look_cm=look or focus, note=note))
    for name, s in (('carrier_a', 420.0), ('carrier_b', 440.0), ('carrier_c', 455.0)):
        x, y, z = G.road_eye(s, 2.5)
        cam(name, x, y, z, note='approach, carrier eye (capture_look EYE 2.5 m) at road %d m' % s)
    x, y, z = G.road_eye(TRIGGER_M + CARRIER_MS * MID_T, EYE_M[0])
    cam('glance_hold', x, y, z, [round(c * 100, 1) for c in target_m],
        note='G03 mid-hold at road %.1f, eye 1.22 m, on the new target (capture at 60 deg; the POV is 90)'
             % (TRIGGER_M + CARRIER_MS * MID_T))
    for name, (a, b, h) in (('orbit_a', (-9.0, 6.0, 2.6)), ('orbit_b', (7.0, 7.0, 3.2)), ('orbit_c', (9.0, -5.0, 2.2))):
        p = S.frame['gap'] - fc * a + rc * b
        cam(name, p[0], p[1], G.z(*p) + h)
    f, r, (ht, hw) = stone_axes(S.tall)
    c = np.array([S.tall['x'], S.tall['y']])
    p = c - f * (ht + 2.2) - r * (hw + 1.2)
    lk = c - f * ht - r * hw * 0.5
    cam('contact', p[0], p[1], G.z(*p) + 0.9, [round(lk[0] * 100, 1), round(lk[1] * 100, 1), round((S.tall['pred']['ground_min'] + 0.15) * 100, 1)],
        note="the tall stone's front outer corner at the ground: packing, sink, the flower and cairn")
    P = S.frame['paving']
    tz = S.tall['pred']['ground_min'] + 1.7
    cam('reading', P[0] - fc[0] * 0.4, P[1] - fc[1] * 0.4, G.z(*P) + 1.6, [round(c[0] * 100, 1), round(c[1] * 100, 1), round(tz * 100, 1)],
        note='a walker on the paving reading the inscription (the TextRender greybox)')
    sp = S.frame['gap'] - fc * 2.8
    cam('standing', sp[0], sp[1], G.z(*sp) + 1.6, [round(v, 1) for v in CROWN_CM],
        note='a walker on the paving, on the crown line: the High Voice stands in the gap between the stones')
    p = S.frame['gap'] - fc * 16.0 - rc * 12.0
    cam('high34', p[0], p[1], G.z(*p) + 18.0)
    p = S.frame['gap'] + fc * 300.0
    cam('far300', p[0], p[1], G.z(*p) + 30.0, note='from the valley side, 300 m out on the crown bearing, looking back')
    return out


# ---------------------------------------------------------------------------- checks

def checks(G, S, recs, grecs, target_m):
    out, bad = [], []
    for r in recs:
        if r['road_clear_m'] < CLEAR_M:
            bad.append('ROAD %s %s %.2f m' % (r['id'], r['key'], r['road_clear_m']))
    solids = [it for it in S.items if not it['ism'] and not it['stack']]
    for i in range(len(solids)):
        for j in range(i + 1, len(solids)):
            a, b = solids[i], solids[j]
            if a['block'] and a['block'] == b['block']:
                continue
            d = plan_mtv(obb_xy(a), obb_xy(b))[0]
            if d > 0:
                bad.append('PLAN OVERLAP %s x %s by %.2f m' % (a['role'][:36], b['role'][:36], d))
    ws = S.waystone
    wbox = dict(x=ws['x'], y=ws['y'], yaw=ws['yaw'], size_m=list(ws['size_m']))
    near = min(plan_gap(obb_xy(it), obb_xy(wbox)) for it in S.items)
    out.append('Stele_WayStone_3 (INSCR lane, road 482.9, 4.8 m left): nearest dressing footprint %.2f m away' % near)
    if near < 0.6:
        bad.append('WAYSTONE: dressing within %.2f m of Stele_WayStone_3' % near)
    lane_w = min(seg_dist((ws['x'], ws['y']), G.world(*a), G.world(*b)) - S.lanes[0]['width'] / 2
                 for a, b in zip(S.lanes[0]['pts'][:-1], S.lanes[0]['pts'][1:]))
    out.append('path edge to the way-stone centre: %.2f m' % lane_w)
    if lane_w < 0.45:
        bad.append('PATH over the way-stone (%.2f m)' % lane_w)
    for it in S.items:
        if it['group'] in ('creep', 'packing') and S.on_lane(it['u'], it['v'], 0.15):
            bad.append('ON PATH %s at (%.1f, %.1f)' % (it['key'], it['u'], it['v']))
    left = clash_pairs(G, S)
    for d, allow, a, b in left:
        bad.append('ISM OVERLAP %s into %s by %.2f m (allowed %.2f)' % (a['key'], b['key'], d, allow))
    mv = sorted(S.moved[id(it)] for it in S.items if it['ism'])
    out.append('ISM declash: %d of %d ISM pieces moved (max %.2f m), %d left out; %d overlaps left beyond %s'
               % (sum(1 for m in mv if m > 0.005), len(mv), max(mv) if mv else 0.0, len(S.dropped), len(left), ISM_ALLOW))
    for st in (S.tall, S.short):
        p = st['pred']
        out.append('%s stone x%.1f: base %.2f m, top %.2f m; ground %.2f..%.2f under the footprint (relief %.2f); '
                   'buried %.2f..%.2f m; stands %.2f..%.2f m proud'
                   % (st['stone'], st['scale'], p['base'], p['top'], p['ground_min'], p['ground_max'], p['relief'],
                      p['buried_min'], p['buried_max'], p['proud_min'], p['proud_max']))
        if p['buried_min'] < 0.15:
            bad.append('STONE %s: buried only %.2f m on its low side' % (st['stone'], p['buried_min']))
        if p['relief'] > 0.6:
            bad.append('STONE %s: %.2f m of relief under the footprint (a stone on a step)' % (st['stone'], p['relief']))
    # the story frames
    for eye_m in EYE_M:
        rows = glance_report(G, S, target_m, eye_m)
        hold = [r for r in rows if GLANCE['ease_in_s'] <= r['t'] <= GLANCE['ease_in_s'] + GLANCE['hold_s']]
        share = sum(1 for r in hold if r['crown_in_gap']) / float(len(hold))
        clear = all(r['crown_clear'] for r in rows)
        marg = []
        for r in hold:
            if r['crown'] and r['tall'] and r['short']:
                lb, rb = (r['tall'], r['short']) if r['tall'][0] + r['tall'][1] < r['short'][0] + r['short'][1] else (r['short'], r['tall'])
                marg.append(min(r['crown'][0] - lb[1], rb[0] - r['crown'][0]))
        out.append('G03 hold, eye %.2f m: the crown is in the notch above the gap in %d %% of the hold (nearest inner edge '
                   '%.3f frame-halves, %.1f deg); never behind a stone: %s'
                   % (eye_m, round(share * 100), min(marg), math.degrees(math.atan(min(marg))), clear))
        if min(marg) < 0.012:
            bad.append('G03: the crown grazes a stone edge in the hold (eye %.2f m, margin %.3f)' % (eye_m, min(marg)))
        if share < 0.99:
            bad.append('G03: the crown leaves the gap during the hold (eye %.2f m, %d %%)' % (eye_m, round(share * 100)))
        if not clear:
            bad.append('G03: a stone covers the crown (eye %.2f m)' % eye_m)
        old = glance_report(G, S, tuple(c / 100.0 for c in OLD_TARGET_CM), eye_m)
        oh = [r for r in old if GLANCE['ease_in_s'] <= r['t'] <= GLANCE['ease_in_s'] + GLANCE['hold_s']]
        out.append('  with the OLD target (glance_targets.json, 16 m up): pitch %.1f..%.1f deg, crown in the gap in %d %% '
                   'of the hold, crown screen x %.2f..%.2f'
                   % (min(r['pitch'] for r in oh), max(r['pitch'] for r in oh),
                      round(100 * sum(1 for r in oh if r['crown_in_gap']) / float(len(oh))),
                      min(r['crown'][0] for r in oh if r['crown']), max(r['crown'][0] for r in oh if r['crown'])))
    sf = standing_frame(G, S)
    out.append('standing on the paving on the crown line (eye 1.6 m, 2.8 m before the gap): the crown at %s is framed in '
               'the notch (between the inner faces, below the tall top): %s (short %s, tall %s)' % (sf['crown'], sf['framed'], sf['short'], sf['tall']))
    if not sf['framed']:
        bad.append('STANDING: the crown is not framed in the gap from the paving')
    occ = crown_occlusion(G, S)
    out.append('crown occluded by the dressing anywhere on 380-540 m (both eyes): %s' % (occ[:4] or 'never'))
    if occ:
        bad.append('CROWN OCCLUDED %s' % occ[:4])
    tw = town_occlusion(G, S, target_m)
    out.append('Old Town (L14) centre covered by a stone during the G03 hold: %s; at mid-hold a stone hides %d %% of '
               "its width (the site's 80 m radius at 560 m)" % (tw[:4] or 'never', round(100 * town_hidden(G, S, target_m))))
    if tw:
        bad.append('TOWN OCCLUDED %s' % tw[:4])
    tz = target_m[2] - G.z(target_m[0], target_m[1])
    out.append('new glance target: (%.0f, %.0f, %.0f) cm, %.2f m above the ground in the gap; it moves %.1f m from the old one'
               % (target_m[0] * 100, target_m[1] * 100, target_m[2] * 100, tz,
                  math.dist(target_m, tuple(c / 100.0 for c in OLD_TARGET_CM))))
    return out, bad


def hull2d(pts):
    """Convex hull (monotone chain) of 2D points, counter-clockwise."""
    P = sorted(set((round(p[0], 6), round(p[1], 6)) for p in pts))
    if len(P) < 3:
        return P

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lo, hi = [], []
    for p in P:
        while len(lo) >= 2 and cross(lo[-2], lo[-1], p) <= 0:
            lo.pop()
        lo.append(p)
    for p in reversed(P):
        while len(hi) >= 2 and cross(hi[-2], hi[-1], p) <= 0:
            hi.pop()
        hi.append(p)
    return lo[:-1] + hi[:-1]


def plan_gap(A, B):
    """Plan clearance (m) between two convex quads (0 when they overlap)."""
    if plan_mtv(A, B)[0] > 0:
        return 0.0
    best = 1e9
    for P, Q in ((A, B), (B, A)):
        for p in P:
            for i in range(4):
                best = min(best, seg_dist(p, Q[i], Q[(i + 1) % 4]))
    return best


def seg_dist(p, a, b):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L2))
    return math.hypot(ax + t * dx - p[0], ay + t * dy - p[1])


# ---------------------------------------------------------------------------- the plot

def plot(G, S, recs, grecs, target_m, out_png=OUT_PNG):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon, Ellipse
    fig = plt.figure(figsize=(21, 12.5))
    col = dict(packed_earth='#b08a5a', path='#6b4d33', rubble_dust='#c8b79a', gravel='#9b9384')
    style = {'stones': ('#26231f', '#77736b'), 'rocks': ('#4f4a44', '#b3aca1'), 'cairns': ('#5d564c', '#a39a8c')}

    def draw_plan(ax, U0, U1, V0, V1, step, lwscale):
        us = np.arange(U0, U1 + 0.01, 0.2)
        vs = np.arange(V0, V1 + 0.01, 0.2)
        UU, VV = np.meshgrid(us, vs)
        X = G.o[0] + UU * G.f[0] + VV * G.l[0]
        Y = G.o[1] + UU * G.f[1] + VV * G.l[1]
        Z = G.T.height(X * 100, Y * 100)
        cs = ax.contour(UU, VV, Z, levels=np.arange(np.floor(Z.min()), Z.max(), step), colors='#b9ad9a', linewidths=0.6)
        ax.clabel(cs, cs.levels[::4], fmt='%.1f m', fontsize=7, colors='#8a7f6c')
        ax.fill_between([U0, U1], -4.5, 4.5, color='#cfc6b8', alpha=0.55, lw=0)
        ax.axhline(0, color='#8a8174', lw=1, ls='--')
        ax.axhline(CLEAR_M, color='#c55', lw=0.8, ls=':')
        for g in S.ground:
            if g['shape'] == 'capsule':
                a = math.radians(g['yaw'])
                L = g['length'] - g['width']
                p0 = (g['u'] - L / 2 * math.cos(a), g['v'] - L / 2 * math.sin(a))
                p1 = (g['u'] + L / 2 * math.cos(a), g['v'] + L / 2 * math.sin(a))
                ax.plot([p0[0], p1[0]], [p0[1], p1[1]], color=col[g['surface']], lw=g['width'] * lwscale, alpha=0.35,
                        solid_capstyle='round')
            else:
                ax.add_patch(Ellipse((g['u'], g['v']), g['length'], g['width'], angle=g['yaw'], color=col[g['surface']],
                                     alpha=0.38 * g['strength'], lw=0))
        for it in S.items:
            uv = [G.local(*p) for p in obb_xy(it)]
            if it['ism']:
                c = {'creep': '#6d8f4e', 'flower': '#b0508c', 'paving': '#9a8a74', 'packing': '#6d5f50'}[it['group']]
                ax.add_patch(Polygon(uv, closed=True, ec='#4a4038' if it['group'] == 'paving' else 'none', lw=0.3, fc=c,
                                     alpha=0.85 if it['group'] != 'creep' else 0.6))
                continue
            ec, fc_ = style[it['group']]
            ax.add_patch(Polygon(uv, closed=True, ec=ec, fc=fc_, lw=1.4 if it['group'] == 'stones' else 0.8, alpha=0.95))
        for sid_, key, x, y in v1_standins():
            u, v = G.local(x, y)
            ax.plot(u, v, 'x', color='#c33', ms=7, mew=1.4)
        ws = S.waystone
        wu, wv = G.local(ws['x'], ws['y'])
        ax.plot(wu, wv, 's', color='#2b5d8a', ms=7)
        tu, tv = G.local(target_m[0], target_m[1])
        ax.plot(tu, tv, '+', color='#c22', ms=14, mew=2)
        ax.set_xlim(U0, U1)
        ax.set_ylim(V0, V1)
        ax.set_aspect('equal')

    # ---- the context plan
    ax = fig.add_axes([0.03, 0.06, 0.46, 0.86])
    U0, U1, V0, V1 = -34.0, 12.0, -6.0, 27.0
    draw_plan(ax, U0, U1, V0, V1, 0.25, 14)
    ax.text(U0 + 0.4, -3.9, 'road (9 m ribbon), travel ->   the road aims at the mountain 430-540 m', fontsize=9, color='#5d564c')
    ax.text(U1 - 8.2, CLEAR_M - 0.6, 'road-core clearance 5 m', fontsize=8, color='#c55')
    for t, c, lab, dy in ((GLANCE['ease_in_s'], '#1f5fa8', 'hold start', -1.3), (MID_T, '#b0302a', 'MID-HOLD', -2.3),
                          (GLANCE['ease_in_s'] + GLANCE['hold_s'], '#6a3fa0', 'hold end', -1.3)):
        s, eye, yw, pt, a = glance_pose(G, t, EYE_M[0], target_m)
        eu, ev = G.local(eye[0], eye[1])
        cb = bearing(eye, (CROWN_CM[0] / 100.0, CROWN_CM[1] / 100.0))
        for off, lw, ls in ((0.0, 1.5, '-'), (-45.0, 0.7, '--'), (45.0, 0.7, '--')):
            if off and t != MID_T:
                continue
            aa = math.radians(G.yaw_local(yw + off if off else cb))
            ax.plot([eu, eu + 48 * math.cos(aa)], [ev, ev + 48 * math.sin(aa)], color=c, lw=lw, ls=ls, alpha=0.8)
        ax.plot(eu, ev, 'o', color=c, ms=6)
        ax.text(eu - 1.6, ev + dy, '%s\n%.1f m' % (lab, s), fontsize=8, color=c)
    ax.text(-33.5, 5.6, 'G03 eyes (carrier at 5 m/s) and their\ncrown bearings; dashed: the 90 deg\nframe at mid-hold',
            fontsize=8, color='#b0302a')
    eu, ev = G.local(*G.road_eye(TRIGGER_M, 1.0)[:2])
    ax.plot(eu, ev, 'k^', ms=8)
    ax.text(eu - 3.2, ev + 0.6, 'B03 trigger 450', fontsize=8)
    tu, tv = G.local(target_m[0], target_m[1])
    ax.text(tu - 9.5, tv + 1.4, 'NEW glance target: in the gap, %.1f m up' % (target_m[2] - G.z(target_m[0], target_m[1])),
            fontsize=8, color='#c22')
    ou, ov = G.local(OLD_TARGET_CM[0] / 100, OLD_TARGET_CM[1] / 100)
    ax.plot(ou, ov, '+', color='#999', ms=12, mew=1.6)
    ax.text(ou - 8.5, ov + 0.6, 'old target (16 m up, 9e60d2cb)', fontsize=8, color='#888')
    ws = S.waystone
    wu, wv = G.local(ws['x'], ws['y'])
    ax.text(wu - 6.2, wv + 0.5, 'Stele_WayStone_3\n(INSCR lane, kept)', fontsize=8, color='#2b5d8a')
    u, v = G.local(*v1_standins()[0][2:])
    ax.text(u + 1.2, v - 1.2, 'V1 cairns (x): removed by clear', fontsize=8, color='#c33')
    tb = G.local(S.tall['x'], S.tall['y'])
    ax.annotate('FOCAL: the tall stone x2.2 (4.25 m), inscribed\n"HOMES MAY EMPTY; LET NAMES REMAIN."',
                xy=tb, xytext=(-33.0, 23.5), fontsize=9, arrowprops=dict(arrowstyle='->', color='#333'))
    sb = G.local(S.short['x'], S.short['y'])
    ax.annotate('the short stone x1.5 (2.9 m), downhill', xy=sb, xytext=(-16.0, 20.0), fontsize=9,
                arrowprops=dict(arrowstyle='->'))
    town_b = bearing(G.road_eye(MID_T * CARRIER_MS + TRIGGER_M, 1.0), (L14_CM[0] / 100.0, L14_CM[1] / 100.0))
    eu, ev = G.local(*G.road_eye(TRIGGER_M + CARRIER_MS * MID_T, 1.0)[:2])
    aa = math.radians(G.yaw_local(town_b))
    ax.annotate('', xy=(eu + 30 * math.cos(aa), ev + 30 * math.sin(aa)), xytext=(eu, ev),
                arrowprops=dict(arrowstyle='->', color='#7a6a3a', lw=1.0, ls=':'))
    ax.text(eu + 30 * math.cos(aa) + 0.3, ev + 30 * math.sin(aa) - 0.4, 'L14 Old Town, 560 m', fontsize=8, color='#7a6a3a')
    ax.text(-6.0, 25.6, 'the crown bearing: the High Voice, 2.9 km', fontsize=8, color='#b0302a')
    fall = math.radians(G.yaw_local(G.fall_yaw(*S.frame['gap'])))
    ax.arrow(8.0, 21.0, 2.2 * math.cos(fall), 2.2 * math.sin(fall), head_width=0.35, color='#a55')
    ax.text(8.2, 20.0, 'fall line', fontsize=8, color='#a55')
    ax.set_xlabel('u: metres along the road from 490 m (travel ->)')
    ax.set_ylabel('v: metres LEFT of the road (the hollow; the mountain beyond)')
    ax.set_title('V2 the Promise Stones (S04_PromiseStones): plan, 0.25 m contours from Current_u16')

    # ---- the close-up of the stones
    gu, gv = G.local(*S.frame['gap'])
    axc = fig.add_axes([0.515, 0.05, 0.235, 0.44])
    draw_plan(axc, gu - 6.5, gu + 5.5, gv - 6.5, gv + 5.0, 0.1, 40)
    axc.set_title('Close-up: stones, packing, paving, cairns (0.1 m contours)', fontsize=10)
    for it, lab in ((S.tall, 'TALL x2.2\ninscribed face'), (S.short, 'SHORT x1.5')):
        u, v = G.local(it['x'], it['y'])
        axc.text(u + 0.9, v + 0.3, lab, fontsize=8, color='#222')
    f, r, (ht, hw) = stone_axes(S.tall)
    c = np.array([S.tall['x'], S.tall['y']]) - f * (ht + 0.03)
    e0, e1 = G.local(*(c - r * 0.6)), G.local(*(c + r * 0.6))
    axc.plot([e0[0], e1[0]], [e0[1], e1[1]], color='#c22', lw=2.5)
    pu, pv = G.local(*S.frame['paving'])
    axc.text(pu - 3.2, pv - 1.9, 'worn paving\n(where people stood to read)', fontsize=8, color='#5a4a35')
    for it in S.items:
        if it['group'] == 'cairns' and not it['stack']:
            u, v = G.local(it['x'], it['y'])
            axc.text(u + 0.35, v - 0.2, 'cairn', fontsize=8, color='#5d564c')
        if it['group'] == 'flower':
            u, v = G.local(it['x'], it['y'])
            axc.text(u - 1.4, v - 0.55, 'the last flower', fontsize=8, color='#b0508c')
        if it['group'] == 'rocks':
            u, v = G.local(it['x'], it['y'])
            axc.text(u + 0.5, v + 0.5, 'rock, 40 % buried', fontsize=8, color='#4f4a44')
    axc.text(gu - 6.3, gv + 4.0, 'red bar: the inscription (TextRender, 2 lines)\nbrown squares: packing stones at the bases',
             fontsize=8, color='#555')

    def frame_ax(rect, title):
        a2 = fig.add_axes(rect)
        a2.set_xlim(-1, 1)
        a2.set_ylim(-1, 1)
        a2.set_xticks([])
        a2.set_yticks([])
        a2.set_title(title, fontsize=10)
        a2.set_facecolor('#dfe7ee')
        a2.set_aspect(9 / 16)
        return a2

    def draw_frame(a2, eye, yw, pt, hfov=HFOV, labels=True):
        xs = np.linspace(-1, 1, 161)
        th = math.tan(math.radians(hfov) / 2)
        tv = th / (16 / 9)
        sky = []
        for sx in xs:
            az = yw + math.degrees(math.atan(sx * th))
            d = np.arange(3.0, 3500.0, 3.0)
            px = eye[0] + d * math.cos(math.radians(az))
            py = eye[1] + d * math.sin(math.radians(az))
            h = G.T.height(px * 100, py * 100)
            el = np.max(np.degrees(np.arctan2(h - eye[2], d)))
            sky.append(math.tan(math.radians(el - pt)) / tv)
        a2.fill_between(xs, -1, np.clip(sky, -1, 1), color='#b8a88f', lw=0)
        for uu in np.arange(-34, 12.1, 2.0):
            pts = [(*G.world(uu, vv), G.zuv(uu, vv)) for vv in np.arange(4.5, 40.1, 0.5)]
            q = [p for p in project(eye, yw, pt, pts, hfov) if p is not None]
            if q:
                a2.plot([p[0] for p in q], [p[1] for p in q], color='#9c8c74', lw=0.4)
        edges = [(0, 2), (2, 4), (4, 6), (6, 0), (1, 3), (3, 5), (5, 7), (7, 1), (0, 1), (2, 3), (4, 5), (6, 7)]
        for it in S.items:
            if it['ism'] and it['group'] in ('packing', 'paving'):
                continue
            q = project(eye, yw, pt, box_points(G, it), hfov)
            ec = {'stones': '#1d1a17', 'rocks': '#5c554d', 'cairns': '#7d6e5f', 'creep': '#56753c', 'flower': '#b0508c'}[it['group']]
            if it['group'] == 'stones':
                poly = [p for p in q if p is not None]
                if len(poly) == 8:
                    a2.add_patch(Polygon(hull2d(poly), closed=True, fc='#6f6a61', ec=ec, lw=1.2))
                continue
            for i0, i1 in edges:
                if q[i0] is not None and q[i1] is not None:
                    a2.plot([q[i0][0], q[i1][0]], [q[i0][1], q[i1][1]], color=ec, lw=0.6)
        c = project(eye, yw, pt, [tuple(v / 100.0 for v in CROWN_CM)], hfov)[0]
        if c is not None and abs(c[0]) <= 1 and abs(c[1]) <= 1:
            a2.plot(c[0], c[1], 'o', color='#ff9a3c', ms=9, mec='#b0302a')
            if labels:
                a2.text(c[0] + 0.03, c[1] + 0.05, 'crown (8 m sphere, 2.9 km)', fontsize=8, color='#b0302a')
        tq = project(eye, yw, pt, [(L14_CM[0] / 100.0, L14_CM[1] / 100.0, L14_CM[2] / 100.0 + 4.0)], hfov)[0]
        if tq is not None and abs(tq[0]) <= 1 and abs(tq[1]) <= 1:
            w = (L14_R_M / 560.0) / th
            a2.plot([tq[0] - w, tq[0] + w], [tq[1], tq[1]], color='#7a6a3a', lw=3, alpha=0.6)
            if labels:
                a2.text(tq[0] - 0.05, tq[1] + 0.05, 'L14 Old Town (560 m)', fontsize=8, color='#7a6a3a')
        for g in (-1 / 3, 1 / 3):
            a2.axvline(g, color='w', lw=0.5, alpha=0.6)
            a2.axhline(g, color='w', lw=0.5, alpha=0.6)
    s, eye, yw, pt, _ = glance_pose(G, MID_T, EYE_M[0], target_m)
    a2 = frame_ax([0.52, 0.53, 0.46, 0.41], 'G03_PROMISE mid-hold, t=%.1f s (road %.1f m): the 90 deg POV, eye 1.22 m, on the NEW target'
                  % (MID_T, s))
    draw_frame(a2, eye, yw, pt)
    a2.plot(0, 0, '+', color='#c22', ms=10)
    s = 440.0
    eye = G.road_eye(s, EYE_M[0])
    a3 = frame_ax([0.765, 0.285, 0.215, 0.19], 'Approach, road %.0f m: forward POV' % s)
    draw_frame(a3, eye, G.heading(s), 0.0, labels=False)
    s, eye, yw, pt, _ = glance_pose(G, MID_T, EYE_M[0], tuple(c / 100.0 for c in OLD_TARGET_CM))
    a4 = frame_ax([0.765, 0.05, 0.215, 0.19], 'G03 mid-hold on the OLD target: sky')
    draw_frame(a4, eye, yw, pt, labels=False)
    fig.savefig(out_png, dpi=80)
    plt.close(fig)
    return out_png


# ---------------------------------------------------------------------------- main

def build():
    G = Ground()
    S = compose(G)
    recs = [to_record(G, S, i, it) for i, it in enumerate(S.items)]
    grecs = ground_records(G, S)
    target_m = target_point(G, S)
    return G, S, recs, grecs, target_m


def write(G, S, recs, grecs, target_m, notes, bad):
    gx, gy = S.frame['gap']
    gz = G.z(gx, gy)
    vw = views(G, S, target_m)
    r = 16.0
    solo = [x for x in recs if not x['ism']]
    ism = [x for x in recs if x['ism']]
    rows = glance_report(G, S, target_m, EYE_M[0])
    ins = inscription(G, S)
    site = dict(
        id=SID, story_set=SET, name='Zrir Siziman, the Promise Stones (V2)', kind='marker pair', order=3, road_m=int(S0),
        side='left', lateral_m=-13.0, centre_cm=[round(gx * 100, 1), round(gy * 100, 1), round(gz * 100, 1)],
        road_yaw=round(G.road_yaw, 1), radius_m=r, zone='Z1 Emptied Valley',
        storm='storm-dusk at its worst: dust sheets and gusts; landmarks read as silhouettes through the haze',
        role='landmark', story='B03 the promise: G03_PROMISE frames the High Voice crown in the notch above the gap; '
                               'the Keeper reads the inscription (RADIO_B03_01)',
        decay=0, style='bazaar stone: two unequal inscribed stones stood upright, chocked, with a worn paving before them',
        layout='\n'.join([
            '  ==== road (aims at the mountain 430-540 m) ====  way-stone at 482.9 (left 4.8 m): the path leaves the road beside it',
            '        path -> [worn paving: where people stood to read]',
            '   cairn [SHORT x1.5, downhill]  <- 5 m gap, square to the G03 eye; the crown in the notch ->  [TALL x2.2, inscribed] cairn',
            '        packing stones round both bases; the last flower at the tall stone',
            '     rock (behind, downhill)                                   rock (behind)',
            '   ... the hollow falls away left; the High Voice 2.9 km beyond the gap ...']),
        notes='Story set V2 on the road site S04_PromiseStones. The V1 cairns (S04_PromiseStones_000..010) are removed by '
              '`clear`. The stones stand left of the road on the crown bearing from the G03 mid-hold eye, not the '
              "storyline's left 8 m / right 6 m (which cannot frame the crown). The glance target moves into the gap "
              '(`hooks`). Nothing religious, nothing modern.',
        story_owned=['V2 the Promise Stones (this file is the story set)', TARGET_TAG + ' (moved by `hooks`)'],
        verify_only=False, layer='road', poi=None,
        counts=dict(placements=len(recs), actors=len(solo) + len({(x['group'], x['asset']) for x in ism}) + len(ins['lines']),
                    ism_instances=len(ism), physics=sum(1 for x in solo if x['settle']['mode'] == 'physics'),
                    batch01=0, decals=len(grecs), text=len(ins['lines'])),
        views=[{k: v[k] for k in ('name', 'cam_cm', 'look_cm')} for v in vw],
        view_notes={v['name']: v['note'] for v in vw if v['note']},
        placements=recs, ground=grecs, units=[], waivers=[],
        inscription=ins,
        story_hooks=dict(GlanceTarget=dict(tag=TARGET_TAG, old_cm=list(OLD_TARGET_CM),
                                           new_cm=[round(c * 100, 1) for c in target_m],
                                           why='the gap between the stones at the height between the tall top and the crown line '
                                               '(the old point is 16 m up: the hold would look 18-29 deg into the sky)')),
        v2=dict(frame=dict(origin_road_m=S0, origin_cm=[round(G.o[0] * 100, 1), round(G.o[1] * 100, 1)],
                           u='along travel', v='left of travel',
                           hold_eye_road_m=TRIGGER_M + CARRIER_MS * MID_T, crown_bearing_deg=round(S.frame['cb'], 2),
                           gap_distance_m=D_GAP_M, gap_m=GAP_M),
                lanes=[dict(pts=[[round(a, 2), round(b, 2)] for a, b in ln['pts']], width=ln['width']) for ln in S.lanes],
                glance=rows, approach=approach_report(G, S), checks=notes, violations=bad),
    )
    # load box: the site and every capture view but far300, with margin (place_setdress.load_box rule)
    xs = [site['centre_cm'][0]] + [v['cam_cm'][0] for v in vw if v['name'] != 'far300']
    ys = [site['centre_cm'][1]] + [v['cam_cm'][1] for v in vw if v['name'] != 'far300']
    m = (r + 30) * 100.0
    site['load_box_cm'] = [round(min(xs) - m), round(min(ys) - m), round(max(xs) + m), round(max(ys) + m)]
    doc = dict(generated_by='Tools/World/story_sets/v2_promise_stones.py', method='docs/world/SETDRESS_V2.md',
               design='docs/world/story_sets/V2.md', level='/Game/level/Saskarta_WP',
               conventions=dict(xy='world cm; yaw = UE yaw deg', bounds='x_cm/y_cm is the mesh BOUNDS CENTRE',
                                ground='decal patches: DecalActor pitch -90, yaw, size (depth/2, width/2, length/2)',
                                contact='stand | lie | rest (SETDRESS_V2.md section 3; stand = an upright stone set by '
                                        'this file\'s `stand` step and judged by `standcheck`)',
                                size_m='stones: in the stone yaw frame (forward = thickness, right = face width, up = height)',
                                site_uv='u m along travel from road 490, v m left of travel'),
               rejected=[], checks=[], sites=[site])
    with open(OUT_JSON, 'w', encoding='utf8') as fh:
        json.dump(doc, fh, indent=1, ensure_ascii=False)
    return site


# ---------------------------------------------------------------------------- editor steps (this set's own)

GRID_SRC = r'''
def stand_bottom(a, pitch, yaw):
    """World offsets from the pivot of an n x n grid on the face that points DOWN (pitch 90: local -X), scaled."""
    sc = a.get_actor_scale3d().x
    b = a.static_mesh_component.static_mesh.get_bounds()
    o = (b.origin.x * sc, b.origin.y * sc, b.origin.z * sc)
    e = (b.box_extent.x * sc, b.box_extent.y * sc, b.box_extent.z * sc)
    ax = axes(yaw, pitch, 0.0)
    k = 0
    best = -1.0
    for i in range(3):
        if abs(ax[i][2]) > best:
            best = abs(ax[i][2])
            k = i
    sgn = 1.0 if ax[k][2] > 0 else -1.0
    js = [i for i in range(3) if i != k]
    pts = []
    for fa in (-0.92, -0.307, 0.307, 0.92):
        for fb in (-0.92, -0.307, 0.307, 0.92):
            p = [0.0, 0.0, 0.0]
            p[k] = o[k] - sgn * e[k]
            p[js[0]] = o[js[0]] + fa * e[js[0]]
            p[js[1]] = o[js[1]] + fb * e[js[1]]
            pts.append(apply(ax, (p[0], p[1], p[2])))
    oc = apply(ax, o)
    top = apply(ax, tuple(o[i] + (sgn * e[i] if i == k else 0.0) for i in range(3)))
    return pts, oc, top
'''

STAND_BODY = r'''
have = site_actors(SITE)
isms = [x for x in have.values() if 'SD_ism' in [str(t) for t in x.tags]]
for s in STONES:
    a = have.get('SD_' + s['id'])
    if a is None:
        print('STAND missing ' + s['id'])
        continue
    pts, oc, top = stand_bottom(a, s['pitch'], s['yaw'])
    lx, ly = s['x_cm'] - oc[0], s['y_cm'] - oc[1]
    gz = []
    first = []
    for q in pts:
        h = trace_ground(lx + q[0], ly + q[1], s['ground_z_cm'] + 1500.0, s['ground_z_cm'] - 1500.0, [a] + isms)
        if h is not None:
            gz.append(h[0])
            first.append(h[2])
    if len(gz) < 12:
        print('STAND no-ground ' + s['id'] + ' samples=' + str(len(gz)))
        continue
    base = min(gz) - s['sink_cm']
    lz = base - pts[0][2]
    a.set_actor_location_and_rotation(V(lx, ly, lz), unreal.Rotator(roll=0.0, pitch=s['pitch'], yaw=s['yaw']), False, True)
    # a standing stone is architecture: the ground decals must not smear up its faces
    a.static_mesh_component.set_editor_property('receives_decals', False)
    r = a.get_actor_rotation()
    print('STAND ' + s['id'] + ' base=' + str(round(base, 1)) + ' top=' + str(round(lz + top[2], 1)) + ' ground=' +
          str(round(min(gz), 1)) + '..' + str(round(max(gz), 1)) + ' rot=' + str([round(r.yaw, 2), round(r.pitch, 2), round(r.roll, 2)]) +
          ' first=' + str(sorted(set(first))))
print('STAND DONE')
'''

STANDCHECK_BODY = r'''
have = site_actors(SITE)
isms = [x for x in have.values() if 'SD_ism' in [str(t) for t in x.tags]]
for s in STONES:
    a = have.get('SD_' + s['id'])
    if a is None:
        print('SC ' + str(dict(id=s['id'], missing=True)))
        continue
    r = a.get_actor_rotation()
    l = a.get_actor_location()
    pts, oc, top = stand_bottom(a, r.pitch, r.yaw)
    gaps, hits = [], []
    for k, q in enumerate(pts):
        x, y, z = l.x + q[0], l.y + q[1], l.z + q[2]
        h = trace_ground(x, y, z + 1500.0, z - 3000.0, [a] + isms)
        gaps.append(None if h is None else round(z - h[0], 1))
        if k in (0, 3, 12, 15):
            ign2 = [a] + isms
            h2 = trace_down(x, y, z + 1500.0, z - 3000.0, ign2)
            # World Partition HLOD proxies (old merged meshes) are not real support: pass through them
            for _ in range(4):
                if h2 is None or 'HLOD' not in h2[2].get_class().get_name():
                    break
                ign2.append(h2[2])
                h2 = trace_down(x, y, z + 1500.0, z - 3000.0, ign2)
            hits.append('none' if h2 is None else ('landscape' if is_land(h2[2]) else h2[2].get_actor_label()))
    print('SC ' + str(dict(id=s['id'], rot=[r.yaw, r.pitch, r.roll], loc=[l.x, l.y, l.z], top=l.z + top[2],
                           base=l.z + pts[0][2], gaps=gaps, hits=hits)))
txt = []
for lab, x in have.items():
    if 'SD_text' in [str(t) for t in x.tags]:
        p = x.get_actor_location()
        txt.append([lab, round(p.x, 1), round(p.y, 1), round(p.z, 1)])
print('SC ' + str(dict(id='text', lines=txt)))
print('SC DONE')
'''

INSCRIBE_BODY = r'''
have = site_actors(SITE)
a = have.get('SD_' + STONE)
if a is None:
    print('INSCRIBE missing ' + STONE)
else:
    r = a.get_actor_rotation()
    l = a.get_actor_location()
    pts, oc, top = stand_bottom(a, r.pitch, r.yaw)
    sc = a.get_actor_scale3d().x
    b = a.static_mesh_component.static_mesh.get_bounds()
    ax = axes(r.yaw, r.pitch, r.roll)
    face = apply(ax, (b.origin.x * sc, b.origin.y * sc, (b.origin.z + b.box_extent.z) * sc))
    n = ax[2]
    fx, fy = l.x + face[0] + n[0] * OUT, l.y + face[1] + n[1] * OUT
    h = trace_ground(fx + n[0] * 15.0, fy + n[1] * 15.0, l.z + 2000.0, l.z - 2000.0, [a])
    gz = h[0] if h is not None else l.z + pts[0][2] + SINK
    made = 0
    for ln in LINES:
        lab = 'SD_' + ln['id']
        t = have.get(lab)
        loc = V(fx, fy, gz + ln['up_from_face_foot_cm'])
        rot = unreal.Rotator(roll=0.0, pitch=0.0, yaw=r.yaw + 180.0)
        if t is None:
            t = eas.spawn_actor_from_class(unreal.TextRenderActor, loc, rot)
            made += 1
        t.set_actor_location_and_rotation(loc, rot, False, True)
        c = t.text_render
        c.set_text(ln['text'])
        c.set_editor_property('world_size', float(ln['world_size_cm']))
        c.set_text_render_color(unreal.Color(r=COLOR[0], g=COLOR[1], b=COLOR[2], a=255))
        if hasattr(unreal, 'HorizTextAligment'):
            c.set_horizontal_alignment(unreal.HorizTextAligment.EHTA_CENTER)
        if hasattr(unreal, 'VerticalTextAligment'):
            c.set_vertical_alignment(unreal.VerticalTextAligment.EVRTA_TEXT_CENTER)
        t.set_editor_property('tags', [unreal.Name(x) for x in ['SetDress', 'SD_' + SITE, 'SDID_' + ln['id'], 'SD_soft', 'SD_text']])
        t.set_actor_label(lab)
        t.set_folder_path('Set/' + SITE + '/inscription')
        print('INSCRIBE ' + ln['id'] + ' at ' + str([round(fx, 1), round(fy, 1), round(gz + ln['up_from_face_foot_cm'], 1)]))
    print('INSCRIBE made=' + str(made) + ' ground=' + str(round(gz, 1)) + ' DONE')
'''

HOOKS_BODY = r'''
got = unreal.GameplayStatics.get_all_actors_with_tag(world, TAG)
print('HOOKS found ' + str(len(got)) + ' tagged ' + TAG)
if len(got) == 1:
    a = got[0]
    p = a.get_actor_location()
    print('HOOKS old ' + str([round(p.x, 1), round(p.y, 1), round(p.z, 1)]))
    a.set_actor_location(V(NEW[0], NEW[1], NEW[2]), False, False)
    p = a.get_actor_location()
    print('HOOKS new ' + str([round(p.x, 1), round(p.y, 1), round(p.z, 1)]))
    print('HOOKS package ' + a.get_package().get_name())
print('HOOKS DONE')
'''

HOOKS_SAVE_BODY = r'''
pk = unreal.find_package(PKG)
if pk is None:
    print('HOOKS_SAVE package not loaded ' + PKG)
else:
    print('HOOKS_SAVE ok=' + str(unreal.EditorLoadingAndSavingUtils.save_packages([pk], True)))
print('HOOKS_SAVE DONE')
'''


def judge_stand(reps, doc):
    """The strict rule for the upright stones (the `stand` contact): plumb, every footprint sample buried by at least
    8 cm (no edge shows a gap), none by more than sink + relief + 10 cm, the corners on the landscape, the top within
    15 cm of the offline prediction (the frames were judged on it), and the inscription on the tall stone."""
    site = doc['sites'][0]
    stones = {p['id']: p for p in site['placements'] if p['contact'] == 'stand'}
    viol = []
    for sid_, p in stones.items():
        r = reps.get(sid_)
        if r is None or r.get('missing'):
            viol.append((sid_, 'MISSING', 'not in the level'))
            continue
        if abs(r['rot'][1] - 90.0) > 0.5 or abs(r['rot'][2]) > 0.5:
            viol.append((sid_, 'TILT', 'rot %s: the stone must stand plumb' % r['rot']))
        g = [x for x in r['gaps'] if x is not None]
        if len(g) < 12:
            viol.append((sid_, 'NO_GROUND', '%d of 16 samples hit the landscape' % len(g)))
        elif max(g) > -8.0:
            viol.append((sid_, 'FLOAT', 'a footprint sample is only %.0f cm below the ground (must be <= -8)' % max(g)))
        elif min(g) < -(p['stand']['sink_cm'] + p['stand']['relief_cm'] + 10.0):
            viol.append((sid_, 'SUNK', 'buried %.0f cm deep somewhere' % -min(g)))
        bad = [h for h in r['hits'] if h not in ('landscape', 'none')]
        if bad:
            viol.append((sid_, 'ON_ACTOR', 'a corner lands on %s' % sorted(set(bad))))
        if abs(r['top'] - p['stand']['top_z_cm']) > 15.0:
            viol.append((sid_, 'TOP', 'top %.0f cm vs %.0f predicted: re-run the offline frames' % (r['top'], p['stand']['top_z_cm'])))
    t = reps.get('text', {}).get('lines', [])
    if len(t) != len(site['inscription']['lines']):
        viol.append(('text', 'INSCRIPTION', '%d of %d lines placed (run inscribe)' % (len(t), len(site['inscription']['lines']))))
    return viol


def custom_step(step, argv):
    """This set's own editor steps, sent through place_setdress.py's Runner (PIE check, banned words, 5 s scripts)."""
    import ast
    import place_setdress as ps
    ap = argparse.ArgumentParser(prog='v2_promise_stones.py ' + step)
    ap.add_argument('--owner', default=os.environ.get('SETDRESS_OWNER', ''))
    ap.add_argument('--no-gate-check', action='store_true')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--port', type=int, default=int(os.environ.get('HAYBA_PORT', 52342)))
    args = ap.parse_args(argv)
    doc = json.load(open(OUT_JSON, encoding='utf8'))
    site = doc['sites'][0]
    if step in ('stand', 'inscribe', 'hooks', 'hooks-save'):
        ps.gate_check(argparse.Namespace(owner=args.owner, dry_run=args.dry_run, no_gate_check=args.no_gate_check), 'place')
    R = ps.Runner(args)
    st = ps.read_state(SID)
    stones = [dict(id=p['id'], x_cm=p['x_cm'], y_cm=p['y_cm'], yaw=p['yaw'], pitch=p['pitch'],
                   sink_cm=float(p['settle']['sink_cm']), ground_z_cm=p['ground_z_cm'])
              for p in site['placements'] if p['contact'] == 'stand']
    if step == 'stand':
        R.send('%s_stand' % SID, ps.build_script(GRID_SRC + STAND_BODY, SITE=SID, STONES=stones))
    elif step == 'inscribe':
        ins = site['inscription']
        tall = [p for p in site['placements'] if p['id'] == ins['stone_id']][0]
        R.send('%s_inscribe' % SID, ps.build_script(GRID_SRC + INSCRIBE_BODY, SITE=SID, STONE=ins['stone_id'],
                                                    LINES=[{k: ln[k] for k in ('id', 'text', 'world_size_cm', 'up_from_face_foot_cm')}
                                                           for ln in ins['lines']],
                                                    OUT=float(ins['out_cm']), COLOR=ins['color_rgb'],
                                                    SINK=float(tall['settle']['sink_cm'])))
    elif step == 'standcheck':
        out = R.send('%s_standcheck' % SID, ps.build_script(GRID_SRC + STANDCHECK_BODY, SITE=SID, STONES=stones))
        if args.dry_run:
            return
        reps = {}
        for line in (out or '').splitlines():
            if line.startswith('SC {'):
                r = ast.literal_eval(line[3:])
                reps[r['id']] = r
        viol = judge_stand(reps, doc)
        for v in viol:
            print('VIOLATION %s %s: %s' % v)
        st['v2_standcheck'] = dict(time=time.time(), ok=not viol, violations=[list(v) for v in viol])
        ps.write_state(SID, st)
        print('STANDCHECK stones=%d violations=%d' % (len(stones), len(viol)))
        return
    elif step == 'hooks':
        hk = site['story_hooks']['GlanceTarget']
        out = R.send('%s_hooks' % SID, ps.build_script(HOOKS_BODY, TAG=hk['tag'], NEW=hk['new_cm']))
        for line in (out or '').splitlines():
            if line.startswith('HOOKS package '):
                st['glance_package'] = line.split(' ', 2)[2].strip()
        if not args.dry_run:
            ps.write_state(SID, st)
        return
    elif step == 'hooks-save':
        pkg = st.get('glance_package')
        if not pkg and not args.dry_run:
            raise SystemExit('run hooks first (it records the glance target package)')
        pkg = pkg or '/Game/__ExternalActors__/level/Saskarta_WP/dry/run'
        path = os.path.join(ROOT, 'Content', pkg[len('/Game/'):] + '.uasset')
        if os.path.exists(path) and not os.access(path, os.W_OK):
            raise SystemExit('%s is read-only on disk (committed-uassets-are-read-only memory note): make it writable '
                             'first; nothing sent' % path)
        R.send('%s_hooks_save' % SID, ps.build_script(HOOKS_SAVE_BODY, PKG=pkg))
        return
    if not args.dry_run:
        st['dirty'] = True          # check2 and standcheck must run again before `save`
        st['v2_standcheck'] = dict(time=time.time(), ok=False, violations=[['*', 'STALE', step]])
        ps.write_state(SID, st)


def run_editor(argv, materials=False):
    """Run a place_setdress.py step (or build_setdress_materials.py) with the V2 site file swapped for V2.json."""
    import place_setdress as ps
    ps.SITES_V2_JSON = OUT_JSON
    if materials:
        import build_setdress_materials as bm
        sys.argv = ['build_setdress_materials.py'] + argv + ([SID] if len(argv) == 1 and argv[0] == 'variants' else [])
        bm.main()
        return
    step = argv[0]
    rest = argv[1:]
    if '--v2' not in rest:
        rest.append('--v2')
    if step == 'save' and '--dry-run' not in rest:
        # the stones are judged by standcheck (check2 only sees their loose rule): it must be clean and newer than check2
        st = ps.read_state(SID)
        sc, c2 = st.get('v2_standcheck'), st.get('check2')
        if not sc or not sc.get('ok') or not c2 or sc['time'] < c2['time']:
            raise SystemExit('refusing to save %s: run `standcheck` after the last check2 (and fix its violations)' % SID)
    if step == 'capture' and '--views' not in rest:
        rest += ['--views', 'carrier_a,carrier_b,carrier_c,glance_hold,orbit_a,orbit_b,orbit_c,contact,reading,standing,high34,far300']
    sys.argv = ['place_setdress.py', step] + ([] if step in ('list', 'probe') else [SID]) + rest
    ps.main()


def main():
    if len(sys.argv) > 1 and sys.argv[1] == 'editor':
        return run_editor(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == 'materials':
        return run_editor(sys.argv[2:], materials=True)
    if len(sys.argv) > 1 and sys.argv[1] in ('stand', 'standcheck', 'inscribe', 'hooks', 'hooks-save'):
        return custom_step(sys.argv[1], sys.argv[2:])
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--no-plot', action='store_true')
    ap.add_argument('--png', default=OUT_PNG)
    args = ap.parse_args()
    G, S, recs, grecs, target_m = build()
    notes, bad = checks(G, S, recs, grecs, target_m)
    site = write(G, S, recs, grecs, target_m, notes, bad)
    c = site['counts']
    print('%s (%s): %d placements, %d actors (ISM groups counted once, 2 text lines), %d ISM instances, %d decals'
          % (SID, SET, c['placements'], c['actors'], c['ism_instances'], c['decals']))
    print('road clearance min %.2f m' % min(r['road_clear_m'] for r in recs))
    for n in notes:
        print(' ', n)
    print('G03 glance (eye 1.22 m, new target): t, road m, yaw, pitch, crown (x, y), tall box, short box, town, in gap')
    for r in site['v2']['glance']:
        print('  %4.2f %7.2f %7.2f %5.2f %s %s %s %s %s' % (r['t'], r['road_m'], r['yaw'], r['pitch'], r['crown'], r['tall'],
                                                         r['short'], r['town'], r['crown_in_gap']))
    print('approach (forward POV):')
    for r in site['v2']['approach']:
        print('  ', {k: r[k] for k in ('road_m', 'dist_m', 'crown', 'tall', 'short', 'crown_in_gap', 'terrain_los')})
    if not args.no_plot:
        print('plot', plot(G, S, recs, grecs, target_m, args.png))
    print('wrote', OUT_JSON)
    if bad:
        print('VIOLATIONS:')
        for b in bad:
            print('  ', b)
        sys.exit(1)


if __name__ == '__main__':
    main()
