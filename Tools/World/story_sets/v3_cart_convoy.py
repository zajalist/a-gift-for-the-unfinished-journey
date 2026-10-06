"""V3 the cart convoy (road site S05_CartConvoy): the story set, composed with the set-dressing V2 method.

    python Tools/World/story_sets/v3_cart_convoy.py                 # write V3.json + the plot, print the checks
    python Tools/World/story_sets/v3_cart_convoy.py --no-plot       # data and checks only
    python Tools/World/story_sets/v3_cart_convoy.py editor <step> [place_setdress args]
          # runs Tools/World/place_setdress.py <step> S05_CartConvoy --v2 against Tools/World/story_sets/V3.json
    python Tools/World/story_sets/v3_cart_convoy.py materials variants
          # runs Tools/World/build_setdress_materials.py variants S05_CartConvoy against V3.json
    python Tools/World/story_sets/v3_cart_convoy.py facing --owner LANE_STORY [--dry-run]
          # read-only: which end of each placed cart carries the shafts; writes V3_measured.json (flips)
    python Tools/World/story_sets/v3_cart_convoy.py nodecal --owner LANE_STORY [--dry-run]
          # the ground decals must not smear up the carts and their loads: receives_decals off on every solo actor

Story (storyline.md section 7 V3, story-events.json B04_CART_CONVOY, POI_CINEMATICS.md PH_S05_CONVOY, RADIO_SHOW.md
PASSING_POI): a wordless vignette at road 810 m. Wheel-less carts and spilled bags, left facing up-road; "They left all
at once and never came back for their things". The HUD reads CARTS . 5 . LEFT LOADED at 790 m, and the station's host,
at the same metre, remembers "the carts lined up with a lamp on the last one". No voice, no event, no camera move.

The place: a column of carts that pulled onto the right verge in the shade of one tree and never pulled out again.
Four stand nose to tail facing up-road (the lead cart still on its wheels, the other three set down on their beds with
their wheels gone, one pair of wheels stood beside its cart); the fifth swerved out of the line to the left, climbed the
bank edge and tipped, spilling its bags toward the road. The LAST cart, the first one the carrier reaches, carries a
cold brass lantern on its load: the tail lamp of the column, never lit again. Under the tree, a cold hearth ring with
a pot. Wheel ruts show where each cart left the road; dust has drifted on the lee side of each; dead shrubs have grown
up against them. The road core stays clear: the carrier drives between the file and the tipped cart.

Offline only: nothing here talks to Unreal except the `editor`, `materials`, `facing` and `nodecal` wrappers, which
send Hayba-safe scripts through place_setdress.py's Runner (PIE check, banned words, one short call each).
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
import setdress_contact as sc  # noqa: E402  (read-only use: UE rotation axes and the check2 judge)

OUT_JSON = os.path.join(HERE, 'V3.json')
OUT_PNG = os.path.join(ROOT, 'docs', 'world', 'story_sets', 'V3.png')
MEASURED_JSON = os.path.join(HERE, 'V3_measured.json')     # written by the `facing` step only
V1_SITES_JSON = os.path.join(WORLD, 'setdress_sites.json')
SID = 'S05_CartConvoy'     # the road site: the V1 dressing carries the tag SD_S05_CartConvoy, so `clear` removes it
SET = 'V3'
S0 = 810.0                 # site origin, road m (B04_CART_CONVOY)
HUD_M = 790.0              # PH_S05_CONVOY "CARTS . 5 . LEFT LOADED" and the RADIO_SHOW PASSING_POI reaction
CIN_P04_M = 700.0          # CIN_P04_AIRSHIP: the carrier stops here; shots 1 and 4 look straight up the road
CIN_P04_PITCH = -3.0       # build_cinematics.plan_poi_airship: (0 s, pitch -3, yaw 0) and (9 s, pitch -3, yaw 0)
EYE_M = (1.22, 1.55)       # probe_ending.json carrier_eye_z (provisional) and CINEMATICS.md "POV at 155 cm"
HFOV = 90.0
CARRIER_MS = 5.0
CLEAR_M = 5.0              # road centreline -> footprint edge (build_setdress_sites.py CLEAR_M)
WIND_TO = (0.94, 0.34)     # MPC_Saskarta_Wind.WindDirection (Tools/Foliage/FOLIAGE.md): the way the wind blows TO
NEIGHBOURS = [             # placed by other lanes (Tools/Story/place_steles.py plan): keep clear, never touch
    ('Stele_WayStone_5', 562474.3, 414849.6),
    ('Stele_WayStone_6', 552121.4, 403421.2),
]
HUD_TEXT = 'CARTS · 5 · LEFT LOADED'
# The loads ARE the story ("left loaded"): the V1 table would cull the lamp at 40 m and the barrels at 60 m, so the
# carts would stand empty in CIN_P04's frame (102 m) and fill up in plain view on the straight. 120 m covers both.
STORY_PROP_DRAW_CM = 12000.0
CAT = setdress_catalog.load()

# Bed floors above the bed's own bounds bottom (m), and the part of the bed length a load can stand on whichever end
# carries the shafts (+- m from the bounds centre). Estimates from the pack thumbnails (the shafts take about a fifth of
# SM_cart_01, the handles an eighth of SM_cart_02, nearly half of the AB handcart); `facing` measures the shafts end.
BED = {
    'MV_cart_01': dict(floor_m=0.20, half_w_in=0.50, safe_len=0.90, note='slatted bed, ladder rails, short shafts'),
    'MV_cart_02': dict(floor_m=0.08, half_w_in=0.52, safe_len=1.10, note='plank box bed, two handles'),
    'AB_Cart_A_texturing': dict(floor_m=0.55, half_w_in=0.62, safe_len=0.25,
                                note='bazaar handcart on its two wheels, modelled resting on the wheels and shaft tips'),
}


def asset(key):
    e = CAT[key]
    return e['path'], e['cat'], e['size_cm']


def draw_distance_cm(max_dim_m):
    """Max draw distance (never 0 = infinite: pcg-spawner-cull-distance-default); build_setdress_sites.py table."""
    for lim, d in ((0.6, 4000.0), (1.5, 6000.0), (4.0, 25000.0), (10.0, 80000.0)):
        if max_dim_m < lim:
            return d
    return 200000.0


def unit(v):
    n = math.sqrt(sum(c * c for c in v))
    return tuple(c / n for c in v)


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


# ---------------------------------------------------------------------------- terrain and the site frame

class Ground:
    def __init__(self, s0=S0):
        self.T = brp.Terrain(brp.HEIGHTMAP)
        self.R = brp.Road(brp.SPLINE_POINTS_CM)
        self.P = self.R.P[:, :2] / 100.0
        k, _ = self.R.locate(s0)
        d = self.R.P[k + 1, :2] - self.R.P[k, :2]
        self.f = d / np.linalg.norm(d)                      # forward (travel)
        self.l = np.array([self.f[1], -self.f[0]])          # left of travel (UE: yaw - 90)
        self.o = self.R.xy(s0) / 100.0                      # site origin, world m
        self.road_yaw = math.degrees(math.atan2(self.f[1], self.f[0]))

    def world(self, u, v):
        p = self.o + u * self.f + v * self.l
        return float(p[0]), float(p[1])

    def local(self, x, y):
        d = np.array([x, y]) - self.o
        return float(d @ self.f), float(d @ self.l)

    def dir_uv(self, dx, dy):
        """A world plan vector in site (u, v)."""
        return float(dx * self.f[0] + dy * self.f[1]), float(dx * self.l[0] + dy * self.l[1])

    def z(self, x, y):
        return float(self.T.height(x * 100.0, y * 100.0))

    def zuv(self, u, v):
        return self.z(*self.world(u, v))

    def plane(self, x, y, r=1.6):
        """Least-squares ground plane over a disc of radius r m: (unit normal, dz/dx, dz/dy)."""
        g = np.arange(-r, r + 1e-6, 0.25)
        dx, dy = np.meshgrid(g, g)
        m = dx ** 2 + dy ** 2 <= r * r
        dx, dy = dx[m], dy[m]
        zz = self.T.height((x + dx) * 100.0, (y + dy) * 100.0)
        A = np.stack([np.ones_like(dx), dx, dy], axis=1)
        c = np.linalg.lstsq(A, zz, rcond=None)[0]
        return unit((-float(c[1]), -float(c[2]), 1.0)), float(c[1]), float(c[2])

    def slope_deg(self, x, y):
        n, _, _ = self.plane(x, y, r=1.0)
        return math.degrees(math.acos(max(-1.0, min(1.0, n[2]))))

    def road_eye(self, s, eye_m):
        x, y = (self.R.xy(s) / 100.0)
        return float(x), float(y), self.z(float(x), float(y)) + eye_m

    def heading(self, s):
        k, _ = self.R.locate(s)
        d = self.R.P[k + 1, :2] - self.R.P[k, :2]
        return math.degrees(math.atan2(d[1], d[0]))

    def road_dist(self, x, y):
        a, b = self.P[:-1], self.P[1:]
        ab = b - a
        p = np.array([x, y])
        t = np.clip(np.sum((p - a) * ab, axis=1) / np.sum(ab * ab, axis=1), 0, 1)
        q = a + ab * t[:, None]
        return float(np.min(np.linalg.norm(p - q, axis=1)))


# ---------------------------------------------------------------------------- geometry of one placement

def corners_local(it, pad=0.0):
    """The 8 corners of the scaled local bounds box, relative to its centre (m); pad grows every half extent."""
    hx, hy, hz = [s * it['scale'] / 200.0 + pad for s in it['size_cm']]
    return [(sx * hx, sy * hy, sz * hz) for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]


def corners_world_rel(it, pad=0.0):
    ax = sc.axes(it['yaw'], it['pitch'], it['roll'])
    return [sc.to_world(ax, (0.0, 0.0, 0.0), p) for p in corners_local(it, pad)]


def hull(pts):
    pts = sorted(set((round(p[0], 6), round(p[1], 6)) for p in pts))
    if len(pts) <= 2:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lo, hi = [], []
    for p in pts:
        while len(lo) >= 2 and cross(lo[-2], lo[-1], p) <= 0:
            lo.pop()
        lo.append(p)
    for p in reversed(pts):
        while len(hi) >= 2 and cross(hi[-2], hi[-1], p) <= 0:
            hi.pop()
        hi.append(p)
    return lo[:-1] + hi[:-1]


def footprint_uv(G, it, core=False, pad=0.0):
    """Plan hull (site u, v) of the rotated bounds box. core: the tree's trunk only (its box is the canopy)."""
    if core and it.get('core_m'):
        r = it['core_m'] / 2
        return [(it['u'] + a, it['v'] + b) for a, b in ((-r, -r), (r, -r), (r, r), (-r, r))]
    pts = []
    for dx, dy, _ in corners_world_rel(it, pad):
        du, dv = G.dir_uv(dx, dy)
        pts.append((it['u'] + du, it['v'] + dv))
    return hull(pts)


def height_m(it):
    zs = [p[2] for p in corners_world_rel(it)]
    return max(zs) - min(zs)


def poly_mtv(A, B):
    """Separating-axis test of two convex polygons in plan: (overlap depth, unit axis pushing A out of B) or (0, None)."""
    best, axis = 1e9, None
    ca = (sum(p[0] for p in A) / len(A), sum(p[1] for p in A) / len(A))
    cb = (sum(p[0] for p in B) / len(B), sum(p[1] for p in B) / len(B))
    for poly in (A, B):
        for i in range(len(poly)):
            (x0, y0), (x1, y1) = poly[i], poly[(i + 1) % len(poly)]
            n = (y0 - y1, x1 - x0)
            ln = math.hypot(*n)
            if ln < 1e-9:
                continue
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


def pt_in_poly(p, poly):
    inside = False
    for i in range(len(poly)):
        (x0, y0), (x1, y1) = poly[i], poly[(i + 1) % len(poly)]
        if (y0 > p[1]) != (y1 > p[1]) and p[0] < x0 + (p[1] - y0) * (x1 - x0) / (y1 - y0):
            inside = not inside
    return inside


def bottom_grid_uv(G, it):
    """The 9 bottom samples of an upright piece (place_setdress local_bounds order: 4 corners, centre, 4 edge mids)."""
    hx, hy = it['size_cm'][0] * it['scale'] / 200.0, it['size_cm'][1] * it['scale'] / 200.0
    a = math.radians(it['yaw'] - G.road_yaw)
    ex = (math.cos(a), -math.sin(a))                                  # local X in (u, v)
    ey = (math.cos(a + math.pi / 2), -math.sin(a + math.pi / 2))      # local Y (world yaw + 90) in (u, v)
    pts = [(sx, sy) for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))] + [(0, 0)] + \
          [(0, -1), (1, 0), (0, 1), (-1, 0)]
    return [(it['u'] + sx * hx * ex[0] + sy * hy * ey[0], it['v'] + sx * hx * ex[1] + sy * hy * ey[1]) for sx, sy in pts]


def rest_settle(G, it):
    """Offline estimate of place_setdress.settle_pose for an upright rest piece: tilt to the plane through its 4
    corner traces (clamped to max_tilt), then z so the highest requirement of the 9 samples is met (rule max).
    Returns the gaps (cm) before the sink: corners, centre, edge mids."""
    pts = bottom_grid_uv(G, it)
    xy = [G.world(u, v) for u, v in pts]
    gz = [G.z(x, y) for x, y in xy]
    A = np.array([[1.0, x - it['x'], y - it['y']] for x, y in xy[:4]])
    c = np.linalg.lstsq(A, np.array(gz[:4]), rcond=None)[0]
    gx, gy = float(c[1]), float(c[2])
    tilt = math.degrees(math.atan(math.hypot(gx, gy)))
    lim = math.tan(math.radians(it['settle']['max_tilt_deg']))
    if math.hypot(gx, gy) > lim:
        k = lim / math.hypot(gx, gy)
        gx, gy = gx * k, gy * k
    rel = [gx * (x - it['x']) + gy * (y - it['y']) for x, y in xy]
    z = max(g - r for g, r in zip(gz, rel))
    gaps = [(z + r - g) * 100.0 for g, r in zip(gz, rel)]
    return dict(gaps_cm=[round(q, 1) for q in gaps], corner_gap_max_cm=max(gaps[:4]), tilt_deg=round(tilt, 1),
                centre_gap_cm=round(gaps[4], 1))


def tipped_gaps(G, it, sgn):
    """cm between the 9 samples of the tipped cart's down face (local -sgn*X face) and the heightmap, with the bounds
    centre where PLACE puts it: the traced ground at (x, y) + size_m[2] / 2 + z_offset (mode none: no settle)."""
    ax = sc.axes(it['yaw'], it['pitch'], it['roll'])
    hx, hy, hz = [s * it['scale'] / 200.0 for s in it['size_cm']]
    cz = G.z(it['x'], it['y']) + it['size_m'][2] / 2 + it['settle']['z_offset_cm'] / 100.0
    out = []
    for fy in (-0.92, 0.0, 0.92):
        for fz in (-0.92, 0.0, 0.92):
            p = sc.to_world(ax, (it['x'], it['y'], cz), (-sgn * hx, fy * hy, fz * hz))
            out.append(round((p[2] - G.z(p[0], p[1])) * 100.0, 1))
    return out


def solve_tipped(nose_dir, n_up, toward):
    """A cart long along local Y lying on its side: local X along +-n_up (the ground normal), local Y along nose_dir
    (projected into the ground plane), local Z (the bed's open top) facing `toward`. Returns (yaw, pitch, roll, sgn)."""
    d = unit(tuple(nose_dir[k] - dot(nose_dir, n_up) * n_up[k] for k in range(3)))
    for sgn in (1.0, -1.0):
        X = tuple(sgn * c for c in n_up)
        pitch = math.degrees(math.asin(max(-1.0, min(1.0, X[2]))))
        yaw = math.degrees(math.atan2(X[1], X[0])) if math.hypot(X[0], X[1]) > 1e-9 else 0.0
        cy, sy = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
        cp, sp = math.cos(math.radians(pitch)), math.sin(math.radians(pitch))
        A = (sp * cy, sp * sy, -cp)
        B = (-sy, cy, 0.0)
        roll = math.degrees(math.atan2(dot(d, A), dot(d, B)))
        Xa, Ya, Za = sc.axes(yaw, pitch, roll)
        assert dot(Xa, X) > 0.9999 and dot(Ya, d) > 0.9999, 'tipped-pose solve failed'
        if dot(Za, toward) > 0:
            return yaw, pitch, roll, sgn
    raise AssertionError('no tipped pose faces the road')


# ---------------------------------------------------------------------------- the composition

SETTLE = {   # SETDRESS_V2.md section 3 contact classes -> the place_setdress settle config
    'rigid': dict(mode='trace', max_tilt_deg=0, rand_tilt_deg=0, z_rule='min'),
    'lie': dict(mode='trace', max_tilt_deg=25, rand_tilt_deg=6, z_rule='mean'),
    'cart': dict(mode='physics', max_tilt_deg=12, rand_tilt_deg=1, z_rule='max'),
    'load': dict(mode='physics', max_tilt_deg=20, rand_tilt_deg=3, z_rule='max'),
    'rest': dict(mode='physics', max_tilt_deg=15, rand_tilt_deg=3, z_rule='max'),
    'tipped': dict(mode='none', max_tilt_deg=0, rand_tilt_deg=0, z_rule='mean'),
    'ism_stone': dict(mode='trace', max_tilt_deg=35, rand_tilt_deg=25, z_rule='mean'),
    'ism_shrub': dict(mode='trace', max_tilt_deg=15, rand_tilt_deg=0, z_rule='mean'),
}
CONTACT_OF = {'rigid': 'rigid', 'lie': 'lie', 'cart': 'rest', 'load': 'rest', 'rest': 'rest', 'tipped': 'lie',
              'ism_stone': 'lie', 'ism_shrub': 'lie'}

# The column. rel = nose yaw relative to travel (+ = to the right, away from the road on this verge); gap_m = extra road
# clearance beyond the 5 m rule (irregular, as carts pull in); after = nose-to-tail gap to the cart ahead.
COLUMN = [   # lead first
    dict(cid='C1', key='AB_Cart_A_texturing', rel=-2.0, gap_m=0.45, after=0.0,
         role='the lead cart, a bazaar handcart: the only one still on its wheels, its shafts down on the verge'),
    dict(cid='C2', key='MV_cart_02', rel=3.0, gap_m=0.30, after=1.40,
         role='set down on its bed, wheels off: the pair stands beside it'),
    dict(cid='C4', key='MV_cart_01', rel=-1.5, gap_m=0.55, after=3.25,
         role='set down on its bed, wheels gone; the wide gap ahead of it is the place C3 swerved out of'),
    dict(cid='C5', key='MV_cart_02', rel=2.0, gap_m=0.35, after=1.25,
         role='FOCAL: the last cart, the tail lamp of the column (a cold brass lantern on its load)'),
]
LEAD_NOSE_U = 11.30          # the lead cart's nose, site u m


class Site:
    def __init__(self, G):
        self.G = G
        self.items = []
        self.ground = []
        self.lanes = []
        self.rng = random.Random(3)
        self.carts = {}
        self.flips = set()
        self.rut_pairs = []

    def add(self, key, u, v, group, kind, scale=1.0, yaw=None, pitch=0.0, roll=0.0, sink_cm=None, ism=False, block=None,
            stack=False, drop_cm=0, z_offset_cm=0, rand_tilt=None, role='', material_set=None, cart=None, layer=0,
            core_m=None, cid=None):
        G = self.G
        path, cat, size = asset(key)
        x, y = G.world(u, v)
        if yaw is None:
            yaw = G.road_yaw
        cfg = dict(SETTLE[kind])
        if rand_tilt is not None:
            cfg['rand_tilt_deg'] = rand_tilt
        settle = dict(mode=cfg['mode'], sink_cm=int(round(6 if sink_cm is None else sink_cm)),
                      max_tilt_deg=cfg['max_tilt_deg'], rand_tilt_deg=cfg['rand_tilt_deg'], z_rule=cfg['z_rule'],
                      drop_cm=int(drop_cm), z_offset_cm=int(round(z_offset_cm)))
        it = dict(key=key, asset=path, cat=cat, size_cm=list(size), u=u, v=v, x=x, y=y, yaw=round(yaw % 360.0, 2),
                  pitch=round(pitch, 2), roll=round(roll, 2), scale=round(scale, 3),
                  size_m=[round(s * scale / 100.0, 3) for s in size], settle=settle, group=group, ism=ism, stack=stack,
                  contact=CONTACT_OF[kind], kind=kind, block=block, role=role, material_set=material_set, cart=cart,
                  layer=layer, core_m=core_m, cid=cid)
        self.items.append(it)
        return it

    def patch(self, surface, u, v, yaw, length, width, strength, shape='ellipse', sort=0, role=''):
        """yaw: site-relative degrees, + turns from +u toward +v (the plot's convention)."""
        self.ground.append(dict(surface=surface, u=u, v=v, yaw=yaw, length=length, width=width, strength=strength,
                                shape=shape, sort=sort, role=role))

    def path(self, pts, width, strength, surface='path', role='', lane=True):
        if lane:
            self.lanes.append(dict(pts=pts, width=width, role=role))
        for (u0, v0), (u1, v1) in zip(pts[:-1], pts[1:]):
            L = math.hypot(u1 - u0, v1 - v0)
            yaw_local = math.degrees(math.atan2(v1 - v0, u1 - u0))
            self.patch(surface, (u0 + u1) / 2, (v0 + v1) / 2, yaw_local, L + width, width, strength, 'capsule', 3, role)

    def on_lane(self, u, v, margin=0.3):
        for ln in self.lanes:
            for (u0, v0), (u1, v1) in zip(ln['pts'][:-1], ln['pts'][1:]):
                du, dv = u1 - u0, v1 - v0
                L2 = du * du + dv * dv
                t = max(0.0, min(1.0, ((u - u0) * du + (v - v0) * dv) / L2))
                if math.hypot(u0 + t * du - u, v0 + t * dv - v) < ln['width'] / 2 + margin:
                    return True
        return False


def cart_frame(G, c):
    """(point(a, b) -> (u, v), long-axis unit (du, dv), left-of-cart unit): a m toward the nose, b m to the cart's left."""
    r = math.radians(c['rel'])
    ax = (math.cos(r), -math.sin(r))
    lf = (math.sin(r), math.cos(r))

    def P(a, b):
        return c['u'] + a * ax[0] + b * lf[0], c['v'] + a * ax[1] + b * lf[1]
    return P, ax, lf


def mesh_yaw(G, rel, flipped):
    """The meshes are long along local Y: yaw = the long-axis direction - 90 (+180 when `facing` found the shafts at -Y)."""
    return G.road_yaw + rel - 90.0 + (180.0 if flipped else 0.0)


def road_clear(G, it):
    return min(G.road_dist(*G.world(u, v)) for u, v in footprint_uv(G, it))


def compose(G, flips=()):
    S = Site(G)
    S.flips = set(flips)
    rng = S.rng

    # 1. the file on the right verge, lead first, nose to tail. Each cart's lateral offset is solved so its footprint
    #    edge stands CLEAR_M + gap_m from the centreline (the road core stays clear: the carrier drives past).
    nose = LEAD_NOSE_U
    for c in COLUMN:
        key = c['key']
        L = CAT[key]['size_cm'][1] / 100.0
        nose -= c['after']
        u = nose - L / 2
        nose = u - L / 2
        it = None
        v = -(CLEAR_M + 1.0)
        for _ in range(40):
            it = S.add(key, u, v, 'carts', 'cart', yaw=mesh_yaw(G, c['rel'], c['cid'] in S.flips), sink_cm=3,
                       role='%s: %s' % (c['cid'], c['role']), material_set='wood', cid=c['cid'])
            err = road_clear(G, it) - (CLEAR_M + c['gap_m'])
            S.items.pop()
            if abs(err) < 0.005:
                break
            v += err                # v < 0 on this verge: too close (err < 0) moves it further right
        it = S.add(key, u, v, 'carts', 'cart', yaw=mesh_yaw(G, c['rel'], c['cid'] in S.flips), sink_cm=3,
                   role='%s: %s' % (c['cid'], c['role']), material_set='wood', cid=c['cid'])
        # the physics settle tilts the bed to the plane of its 4 corner traces and lets the highest of its 9 bottom
        # samples carry it (z rule max). On a hump that leaves the ends in the air: sink it until they touch.
        rs = rest_settle(G, it)
        it['settle']['sink_cm'] = int(max(3, min(10, math.ceil(rs['corner_gap_max_cm'] - 1.0))))
        S.carts[c['cid']] = dict(c, u=u, v=v, item=it, L=L)

    # 2. C3, the fifth cart: out of the line to the left, nose up the bank edge (20 deg out), tipped over toward the
    #    road, its open top facing the road. Offline settle (mode none): local X along the ground normal, lying on its
    #    road-side rail, sunk 3 cm; z_offset puts the bounds centre half a bed width above the ground plane.
    c3 = dict(cid='C3', key='MV_cart_01', rel=-20.0, u=0.9, v=7.95, L=CAT['MV_cart_01']['size_cm'][1] / 100.0,
              role='C3: swerved out of the line to the left, climbed the bank edge and tipped toward the road; '
                   'its load spilled out of the open top')
    x3, y3 = G.world(c3['u'], c3['v'])
    n_up, _, _ = G.plane(x3, y3, r=2.0)
    th = math.radians(G.road_yaw + c3['rel'])
    nose3 = (math.cos(th), math.sin(th), 0.0)
    if 'C3' in S.flips:
        nose3 = tuple(-q for q in nose3)
    tr = math.radians(G.road_yaw + 90.0)                    # the right of travel: from the left verge, toward the road
    yaw3, pitch3, roll3, sgn3 = solve_tipped(nose3, n_up, (math.cos(tr), math.sin(tr), 0.0))
    size3 = CAT['MV_cart_01']['size_cm']
    half_x = size3[0] / 200.0
    zoff3 = (half_x / n_up[2]) * 100.0 - size3[2] * 50.0 / 100.0
    it3 = S.add('MV_cart_01', c3['u'], c3['v'], 'carts', 'tipped', yaw=yaw3, pitch=pitch3, roll=roll3, sink_cm=0,
                z_offset_cm=zoff3, role=c3['role'], material_set='wood', cid='C3')
    c3.update(item=it3, n_up=n_up, sgn=sgn3)
    # lower it until the highest sample of its down face is 2 cm up: the rail beds into the bank's crown
    g0 = tipped_gaps(G, it3, sgn3)
    drop = max(g0) - 2.0
    it3['settle']['z_offset_cm'] = int(round(zoff3 - drop))
    it3['settle']['sink_cm'] = int(round(drop))
    S.carts['C3'] = c3

    # 3. the loads. Each stands on its bed inside the part of the bed that is floor whichever end carries the shafts
    #    (BED safe_len), clear of the rails; layer 2 lands on layer 1 (physics settle, bottom layer first).
    #    (key, a m toward the nose, b m to the cart's left, layer, yaw offset vs the cart's long axis, role)
    loads = {
        'C1': [('MV_jute_bag_01', 0.00, 0.30, 1, 90.0, 'grain sack, lashed on the bed'),
               ('MV_jute_bag_03', 0.02, -0.30, 1, 85.0, 'grain sack'),
               ('MV_jute_bag_06', 0.00, 0.02, 2, 95.0, 'a third sack on top')],
        'C2': [('AB_Box_A', -0.45, 0.00, 1, 90.0, 'the family chest (bazaar box), along the bed'),
               ('MV_jute_bag_07', 0.55, 0.01, 1, 88.0, 'a long sack across the bed in front of the chest'),
               ('MV_jute_bag_02', -0.70, 0.04, 2, 80.0, 'sack on the chest'),
               ('AB_Clay_Pot_A', -0.12, -0.08, 2, 0.0, 'a water jar stood on the chest lid')],
        'C4': [('MV_barrel_02', -0.45, 0.00, 1, 0.0, 'oil barrel'),
               ('MV_barrel_01', 0.40, 0.02, 1, 30.0, 'water barrel'),
               ('MV_bucket_03', -0.45, 0.02, 2, 0.0, 'a bucket left on the barrel head')],
        'C5': [('MV_barrel_01', -0.55, 0.00, 1, 0.0, 'the lamp barrel, at the tail'),
               ('MV_box_01', 0.25, 0.00, 1, 90.0, 'a box along the bed'),
               ('MV_jute_bag_05', 0.78, 0.02, 1, 90.0, 'a flat sack at the front board'),
               ('MV_box_03', 0.25, 0.04, 2, 10.0, 'a small box on the box'),
               ('AB_Lamp_A', -0.55, 0.03, 3, 20.0, 'FOCAL: the cold brass tail lamp, stood on the barrel head')],
    }
    for cid, lst in loads.items():
        c = S.carts[cid]
        P, ax, lf = cart_frame(G, c)
        for key, a, b, layer, yoff, role in lst:
            u, v = P(a, b)
            ms = None if key == 'AB_Lamp_A' else ('cloth' if 'jute' in key else ('stone' if 'Clay' in key else 'wood'))
            S.add(key, u, v, 'loads', 'load', yaw=G.road_yaw + c['rel'] - 90.0 + yoff, sink_cm=1, stack=True,
                  drop_cm=40 + 60 * layer, role='%s load: %s' % (cid, role), material_set=ms, cart=cid, layer=layer)

    # 4. what lies off the carts. C2's wheels stand beside it (axle along the cart); C3's spill fans toward the road
    #    in front of its open top; a lone AB wheel lies flat behind C3; the cold hearth under the tree has a pot.
    c2 = S.carts['C2']
    P2, ax2, lf2 = cart_frame(G, c2)
    w_half = CAT['MV_cart_02_wheels']['size_cm'][1] / 200.0
    b_out = -(CAT['MV_cart_02']['size_cm'][0] / 200.0 + 0.30 + w_half)
    wu, wv = P2(0.15, b_out)
    wp = S.add('MV_cart_02_wheels', wu, wv, 'wheels', 'rest', yaw=G.road_yaw + c2['rel'] + 2.0, sink_cm=2,
               role="C2's wheels, off and stood beside it on the verge", material_set='wood')
    wp['settle']['sink_cm'] = int(max(2, min(8, math.ceil(rest_settle(G, wp)['corner_gap_max_cm'] - 1.0))))
    # the spill, in C3's frame (a toward its nose, b to its left; the road is on its right, b < 0): out of the open
    # top, fanning down the bank toward the road, the heavy things nearest the bed
    P3s, _, _ = cart_frame(G, c3)
    spill = [('MV_box_02', -0.55, -0.90, 'a box, still shut, just out of the bed'),
             ('MV_jute_bag_02', 0.55, -0.84, 'sack, just out of the bed'),
             ('AB_Clay_Pot_D', 1.45, -0.72, 'a jar that stayed upright'),
             ('MV_jute_bag_08', -1.50, -1.42, 'flat sack'),
             ('MV_jute_bag_10', 0.05, -1.62, 'flat sack'),
             ('MV_jute_bag_03', 1.25, -1.55, 'sack'),
             ('MV_jute_bag_04', -0.75, -2.15, 'burst sack at the foot of the spill, nearest the road'),
             ('AB_Lamp_C', 0.75, -2.35, 'a brass ewer rolled furthest')]
    for key, a, b, role in spill:
        u, v = P3s(a, b)
        ms = None if key == 'AB_Lamp_C' else ('cloth' if 'jute' in key else ('stone' if 'Clay' in key else 'wood'))
        S.add(key, u, v, 'spill', 'rest', yaw=rng.uniform(0, 360), sink_cm=2, drop_cm=10, role='C3 spill: ' + role,
              material_set=ms)
    S.add('AB_Cart_Wheel', -2.05, 8.55, 'wheels', 'lie', yaw=rng.uniform(0, 360), sink_cm=3, rand_tilt=2,
          role='a lone wheel lying flat behind the tipped cart', material_set='wood')

    # 5. the tree the column halted by, and the hearth in its shade. The tree is rigid (plumb, rooted 25 cm); its
    #    bounds box is the canopy, so the ISM declash uses the trunk (core_m).
    c5 = S.carts['C5']
    tu, tv = c5['u'] - 3.9, -11.6
    S.add('FAB_DeadTree_qlEtl', tu, tv, 'tree', 'rigid', yaw=G.road_yaw + 35.0, sink_cm=25, block='tree', core_m=0.9,
          role='the shade tree the column halted by (dead now)', material_set='wood')
    hu, hv = c5['u'] - 1.6, -8.55
    S.add('PH_pot', hu, hv, 'hearth', 'rest', yaw=rng.uniform(0, 360), sink_cm=2, drop_cm=10,
          role='a pot left on the cold hearth', material_set=None)
    S.hearth = (hu, hv)
    S.tree = (tu, tv)

    # 6. the ground.
    #    a. wheel ruts: where each cart left the road, a pair from the road edge to its wheel track (the MV beds carried
    #       one axle mid-bed, PLA_Cart_01's wheels are at the bed's middle). Narrow `path` capsules.
    def ruts(start, end, end_dir, half_track, lead_m, role):
        """The two wheel tracks of a cart that turned off the road: its axle centre follows a quadratic Bezier from a
        point on the road (heading up-road) to where the axle stopped (heading end_dir); each wheel is offset half a
        track to either side. Only the part off the ribbon (|v| >= 4.6) is drawn, as 3 capsules per track."""
        P1 = (end[0] - end_dir[0] * lead_m, end[1] - end_dir[1] * lead_m)
        pts, tans = [], []
        for s in np.linspace(0.0, 1.0, 25):
            s = float(s)
            pts.append(((1 - s) ** 2 * start[0] + 2 * (1 - s) * s * P1[0] + s * s * end[0],
                        (1 - s) ** 2 * start[1] + 2 * (1 - s) * s * P1[1] + s * s * end[1]))
            tans.append(unit((2 * (1 - s) * (P1[0] - start[0]) + 2 * s * (end[0] - P1[0]),
                              2 * (1 - s) * (P1[1] - start[1]) + 2 * s * (end[1] - P1[1]))))
        pair = []
        for side in (1, -1):
            w = [(p[0] - t[1] * side * half_track, p[1] + t[0] * side * half_track) for p, t in zip(pts, tans)]
            w = [q for q in w if abs(q[1]) >= 4.6]
            if len(w) < 2:
                continue
            k = [w[0], w[len(w) // 3], w[2 * len(w) // 3], w[-1]]
            S.path(k, 0.24, 0.62, role=role, lane=True)
            pair.append(k)
        S.rut_pairs.append(dict(pair=pair, crown=pts[int(0.72 * (len(pts) - 1))]))
    for cid in ('C1', 'C2', 'C4', 'C5'):
        c = S.carts[cid]
        P, ax, lf = cart_frame(G, c)
        half_track = 0.95 if c['key'] == 'AB_Cart_A_texturing' else 0.72
        a_axle = -1.1 if c['key'] == 'AB_Cart_A_texturing' else -0.35
        e = P(a_axle, 0.0)
        ruts((e[0] - 7.5, -2.9), e, ax, half_track, 3.2, '%s wheel rut, off the road' % cid)
    #    b. C3's tracks: across from the column, up the bank to where its wheels were (mid-bed, before it went over
    #       toward the road); the road-side track runs on under the fallen cart.
    P3, ax3, _ = cart_frame(G, c3)
    e = P3(0.0, 0.47)
    ruts((e[0] - 6.5, 1.5), e, ax3, 0.72, 2.6, 'C3 wheel rut, up the bank')
    #    c. the trodden way: from the road through the gap behind C5 to the hearth, and along the file's outer side.
    #       Both stop short of the hearth ring.
    def short_of(p, q, r):
        d = unit((q[0] - p[0], q[1] - p[1]))
        return (p[0] + d[0] * r, p[1] + d[1] * r)
    w1 = (c5['u'] - 2.35, -6.9)
    S.path([(c5['u'] - 2.0, -4.6), w1, short_of((hu, hv), w1, 1.3)], 0.8, 0.8,
           role='the trodden way from the road to the hearth')
    w2 = (c5['u'] + 2.2, -8.75)
    S.path([short_of((hu, hv), w2, 1.3), w2, (S.carts['C4']['u'], -8.5),
            (S.carts['C2']['u'] - 1.9, -8.95), (S.carts['C1']['u'], -8.75)], 0.7, 0.62,
           role='the way along the outer side of the file')
    #    d. the halt: packed earth along the file and under the tree; soot at the hearth.
    S.patch('packed_earth', 1.2, -7.25, 0.0, 23.0, 5.0, 0.55, sort=0, role='the halt: the verge the column stood on')
    S.patch('packed_earth', tu + 0.9, tv + 2.0, 20.0, 6.5, 5.0, 0.6, sort=0, role='the shade under the tree')
    S.patch('soot', hu, hv, 0.0, 1.25, 1.1, 0.8, sort=4, role='the cold hearth')
    #    e. dust drifted on the lee side of every cart (the wind blows toward WIND_TO), and C3's spilled grain.
    wu_, wv_ = G.dir_uv(*WIND_TO)
    wn = math.hypot(wu_, wv_)
    wu_, wv_ = wu_ / wn, wv_ / wn
    wyaw = math.degrees(math.atan2(wv_, wu_))
    for cid in ('C1', 'C2', 'C4', 'C5', 'C3'):
        c = S.carts[cid]
        du = c['u'] + wu_ * (c['L'] * 0.45 + 1.2)
        dv = c['v'] + wv_ * (c['L'] * 0.45 + 1.2) * 0.55
        if cid in ('C1', 'C2', 'C4', 'C5') and dv > -5.3:
            dv = -5.3
        S.patch('rubble_dust', du, dv, wyaw, 3.4, 1.35, 0.55, sort=1, role='%s: dust drifted in its lee' % cid)
    S.patch('rubble_dust', 0.4, 6.55, 8.0, 3.6, 1.5, 0.7, sort=1, role="C3's spilled grain, pale in the dust")

    # 7. stones: a hearth ring, verge-edge gravel in clumps between the carts, stones ploughed up where C3 left the
    #    road, half-buried field rocks at the tree foot and out on the flat. ISM, ground-only, 30-40 % buried.
    for k in range(7):
        a = 2 * math.pi * k / 7 + rng.uniform(-0.2, 0.2)
        r = 0.62 + rng.uniform(-0.04, 0.05)
        key = 'LF_Rock_08'
        scl = rng.uniform(0.55, 0.72)
        h = CAT[key]['size_cm'][2] * scl
        S.add(key, hu + r * math.cos(a), hv + r * math.sin(a), 'hearth', 'ism_stone', scale=scl, yaw=rng.uniform(0, 360),
              sink_cm=0.35 * h, ism=True, block='base', role='hearth ring stone', material_set='stone')
    clumps = [(S.carts['C1']['u'] + 2.6, -5.45, 3, 0.8, 'verge-edge gravel'), (-17.0, -5.6, 3, 0.8, 'verge-edge gravel'),
              (14.2, -5.5, 3, 0.8, 'verge-edge gravel'), (-6.0, 5.5, 2, 0.8, 'verge-edge gravel'),
              (4.6, 5.45, 3, 0.8, 'verge-edge gravel')]
    for rp in S.rut_pairs[:4]:
        # the crown between a cart's two tracks, where the axle centre passed near the end of its turn
        clumps.append((rp['crown'][0], rp['crown'][1], 2, 0.22, 'gravel on the crown between the ruts'))
    for cu, cv, n, spread, role in clumps:
        for _ in range(n):
            key = rng.choice(['LF_Rock_07', 'LF_Rock_07', 'LF_Rock_08', 'AB_Cobble_04'])
            scl = rng.uniform(0.8, 1.3) if key != 'LF_Rock_08' else rng.uniform(0.45, 0.75)
            h = CAT[key]['size_cm'][2] * scl
            S.add(key, cu + rng.uniform(-spread, spread), cv + math.copysign(rng.uniform(0.0, spread * 0.6), cv), 'stones',
                  'ism_stone', scale=scl, yaw=rng.uniform(0, 360), sink_cm=0.35 * h, ism=True, block='base',
                  role=role, material_set='stone')
    for k in range(5):
        e = P3(rng.uniform(0.1, 1.0), 1.55 + rng.uniform(0.0, 0.5))     # pushed up ahead of its bank-side wheel
        key = rng.choice(['LF_Rock_08', 'LF_Rock_07', 'AB_Cobble_04'])
        scl = rng.uniform(0.6, 1.0)
        h = CAT[key]['size_cm'][2] * scl
        S.add(key, e[0], e[1], 'stones', 'ism_stone', scale=scl,
              yaw=rng.uniform(0, 360), sink_cm=0.3 * h, ism=True, block='fan', role='stone ploughed up by C3',
              material_set='stone')
    rocks = [('LF_Rock_03', tu + 1.35, tv + 0.55, 0.42, 'at the tree foot'),
             ('LF_Rock_05', tu - 1.2, tv + 0.9, 0.36, 'at the tree foot'),
             ('LF_Rock_02', 5.8, 11.4, 0.5, 'on the bank above the tipped cart'),
             ('LF_Rock_04', -3.2, -15.8, 0.46, 'out on the flat, behind the file'),
             ('LF_Rock_05', 12.4, -14.6, 0.4, 'out on the flat, beyond the lead cart')]
    for key, u, v, scl, where in rocks:
        h = CAT[key]['size_cm'][2] * scl
        S.add(key, u, v, 'rocks', 'ism_stone', scale=scl, yaw=rng.uniform(0, 360), sink_cm=0.4 * h, ism=True,
              block='base', rand_tilt=8, role='half-buried field rock ' + where, material_set='stone')

    # 8. creep: dead shrubs grown up against the carts (their outer sides and lee ends), round the wheels, at the tree
    #    foot, through C3's old spill, and in loose clumps on the flat. Never on a rut or path.
    creep = []
    for cid in ('C1', 'C2', 'C4', 'C5'):
        c = S.carts[cid]
        P, ax, lf = cart_frame(G, c)
        hw = CAT[c['key']]['size_cm'][0] / 200.0
        creep += [(P(-c['L'] * 0.30, -(hw + 0.35)), 'against the outer side of ' + cid),
                  (P(c['L'] * 0.25, -(hw + 0.30)), 'against the outer side of ' + cid),
                  (P(-(c['L'] / 2 + 0.35), -0.25), 'in the lee of the tail of ' + cid)]
    creep += [((wu + 0.9, wv - 0.75), "round C2's wheels"), ((tu + 0.8, tv - 0.6), 'at the tree foot'),
              ((tu - 0.7, tv - 0.8), 'at the tree foot'), ((tu + 0.1, tv + 1.25), 'at the tree foot'),
              ((-0.6, 8.75), 'against the bottom of the tipped cart'), ((2.3, 9.05), 'against the bottom of the tipped cart'),
              ((1.9, 6.1), 'through the old spill'), ((-0.35, 5.85), 'through the old spill'),
              ((-3.4, 7.6), 'on the bank edge'), ((6.5, 9.6), 'on the bank')]
    for cu, cv in ((-15.5, -9.5), (8.5, -13.0), (-9.5, 11.0), (12.5, 8.6), (-19.0, 6.8)):
        for _ in range(3):
            creep.append(((cu + rng.uniform(-1.4, 1.4), cv + rng.uniform(-1.1, 1.1)), 'a clump on the flat'))
    shrub_keys = ['FAB_Shrub_C', 'FAB_Shrub_D', 'FAB_Shrub_E', 'FAB_Shrub_F', 'FAB_Shrub_G', 'FAB_Shrub_H']
    for (u, v), where in creep:
        if S.on_lane(u, v) or abs(v) < CLEAR_M + 0.5:
            continue
        key = rng.choice(shrub_keys)
        S.add(key, u, v, 'creep', 'ism_shrub', scale=rng.uniform(0.8, 1.2), yaw=rng.uniform(0, 360), sink_cm=5, ism=True,
              block='creep', role='dead shrub ' + where)

    # ISM stones and shrubs are pushed out of the solids and each other (check2 does not measure ISM instances), and
    # left out if they find no room within 0.6 m, land on a rut or path, or come within the road clearance.
    S.moved = declash(G, S)
    left = clash_pairs(G, S)
    S.dropped = [it for it in S.items if it['ism'] and (S.moved[id(it)] > 0.6 or S.on_lane(it['u'], it['v'], 0.15) or
                                                        road_clear(G, it) < CLEAR_M or
                                                        any(a is it or b is it for _, _, a, b in left))]
    S.items = [it for it in S.items if all(it is not d for d in S.dropped)]
    for it in S.items:
        it['x'], it['y'] = G.world(it['u'], it['v'])
    return S


ISM_ALLOW = dict(stone=0.05, shrub=0.08, ism=0.04)
PHYSICS_PAD_M = 0.04   # ISM keep this far clear of a physics-settled piece: its settle traces hit ISM, so a shrub under
                       # a cart's corner would lift that corner onto the shrub


def solids_for_declash(S):
    """The pieces ISM must keep out of: every solo actor on the ground (carts, wheels, spill, pot, tree trunk)."""
    return [it for it in S.items if not it['ism'] and not it['stack']]


def solid_fp(G, it):
    if it['settle']['mode'] == 'physics':
        return footprint_uv(G, it, pad=PHYSICS_PAD_M)
    return footprint_uv(G, it, core=True)


def clash_pairs(G, S):
    solids = solids_for_declash(S)
    isms = [it for it in S.items if it['ism']]
    fp = {id(it): footprint_uv(G, it) for it in isms}
    fp.update({id(it): solid_fp(G, it) for it in solids})
    out = []
    for it in isms:
        for sd in solids:
            allow = 0.0 if sd['settle']['mode'] == 'physics' else ISM_ALLOW['shrub' if it['cat'] == 'shrub' else 'stone']
            d = poly_mtv(fp[id(it)], fp[id(sd)])[0]
            if d > allow + 1e-6:
                out.append((d, allow, it, sd))
    for i in range(len(isms)):
        for j in range(i + 1, len(isms)):
            d = poly_mtv(fp[id(isms[i])], fp[id(isms[j])])[0]
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
        for d, allow, a, b in sorted(pairs, key=lambda p: -p[0]):
            mover = a if a['ism'] and id(a) not in done else (b if b['ism'] and id(b) not in done else None)
            if mover is None:
                continue
            fixed = b if mover is a else a
            fa = footprint_uv(G, mover) if mover['ism'] else solid_fp(G, mover)
            fb = footprint_uv(G, fixed) if fixed['ism'] else solid_fp(G, fixed)
            dd, ax = poly_mtv(fa, fb)
            if ax is None:
                continue
            mover['u'] += ax[0] * (dd - allow + 0.03)
            mover['v'] += ax[1] * (dd - allow + 0.03)
            done.add(id(mover))
    return {id(it): math.hypot(it['u'] - start[id(it)][0], it['v'] - start[id(it)][1]) for it in S.items if it['ism']}


# ---------------------------------------------------------------------------- predicted poses (offline settle)

def predict(G, S):
    """Predicted pose per item: bottom z (world m) and the ground plane under it. Carts and loose props rest on the
    ground plane under their footprint (the physics settle tilts them to it, max rule); loads stand on their bed floor
    (BED floor_m) or on the top of the layer below; the tipped cart as solved; the tree plumb with z min."""
    pr = {}
    for it in S.items:
        if it['ism'] or it['stack']:
            continue
        fp = footprint_uv(G, it)
        gz = [G.zuv(u, v) for u, v in fp] + [G.zuv(it['u'], it['v'])]
        if it['kind'] == 'rigid':
            bottom = min(gz) - it['settle']['sink_cm'] / 100.0
        elif it['kind'] == 'tipped':
            bottom = None
        else:
            bottom = max(gz) - it['settle']['sink_cm'] / 100.0
        pr[id(it)] = dict(bottom=bottom, ground=gz, top=None if bottom is None else bottom + height_m(it))
    # the tipped cart: its 9 bottom-face samples against the heightmap
    for it in S.items:
        if it['kind'] != 'tipped':
            continue
        c = [cc for cc in S.carts.values() if cc['item'] is it][0]
        ax = sc.axes(it['yaw'], it['pitch'], it['roll'])
        cz = G.z(it['x'], it['y']) + it['size_m'][2] / 2 + it['settle']['z_offset_cm'] / 100.0
        gaps = tipped_gaps(G, it, c['sgn'])
        zs = [sc.to_world(ax, (it['x'], it['y'], cz), q)[2] for q in corners_local(it)]
        pr[id(it)] = dict(bottom=min(zs), top=max(zs), gaps_cm=gaps, centre_z=cz, ground=[])
    # loads: bottom layer on the bed floor, then upward
    for it in sorted([i for i in S.items if i['stack']], key=lambda i: i['layer']):
        cart = S.carts[it['cart']]['item']
        base = pr[id(cart)]['bottom'] + BED[cart['key']]['floor_m']
        fp = footprint_uv(G, it)
        for q in S.items:
            if q['stack'] and q['cart'] == it['cart'] and q['layer'] < it['layer'] and id(q) in pr:
                d = poly_mtv(fp, footprint_uv(G, q))[0]
                if d > 0.02:
                    base = max(base, pr[id(q)]['top'])
        pr[id(it)] = dict(bottom=base, top=base + height_m(it), ground=[])
    return pr


def box_points(G, S, pr, it):
    """8 world corners (m) of the predicted pose."""
    if it['ism']:
        z0 = G.zuv(it['u'], it['v']) - it['settle']['sink_cm'] / 100.0
        rel = corners_world_rel(it)
        zmin = min(p[2] for p in rel)
        return [(it['x'] + p[0], it['y'] + p[1], z0 + p[2] - zmin) for p in rel]
    p = pr[id(it)]
    rel = corners_world_rel(it)
    zmin = min(q[2] for q in rel)
    return [(it['x'] + q[0], it['y'] + q[1], p['bottom'] + q[2] - zmin) for q in rel]


# ---------------------------------------------------------------------------- records

def to_record(G, S, i, it):
    x, y = it['x'], it['y']
    gz = G.z(x, y)
    rid = '%s_v3_%03d' % (SID, i)
    it['id'] = rid
    rec = dict(id=rid, key=it['key'], asset=it['asset'], kind='SM', cat=it['cat'],
               x_cm=round(x * 100, 1), y_cm=round(y * 100, 1), ground_z_cm=round(gz * 100, 1),
               yaw=round(it['yaw'], 2), pitch=float(it['pitch']), roll=float(it['roll']), scale=it['scale'],
               scale_range=[it['scale'], it['scale']], settle=it['settle'], group=it['group'],
               folder='Set/%s/%s' % (SID, it['group']), data_layer='DL_SetDress', ism=it['ism'], stack=it['stack'],
               attach=False, run_id=None, collision=not it['ism'] or it['group'] == 'rocks',
               foliage_exclude=it['group'] in ('carts', 'wheels', 'tree', 'hearth', 'spill'),
               draw_distance_cm=max(draw_distance_cm(max(it['size_m'])),
                                    STORY_PROP_DRAW_CM if it['group'] in ('loads', 'spill', 'wheels') else 0.0),
               cast_shadow=True, size_m=it['size_m'],
               slope_deg=round(G.slope_deg(x, y), 1), road_clear_m=round(road_clear(G, it), 2), contact=it['contact'],
               site_uv=[round(it['u'], 2), round(it['v'], 2)], role=it['role'], story_set=SET)
    if it['block']:
        rec['block'] = it['block']
    if it['material_set']:
        rec['material_set'] = it['material_set']
    if it['cid']:
        rec['cart'] = it['cid']
    if it['cart']:
        rec['on_cart'] = it['cart']
        rec['layer'] = it['layer']
    return rec


def ground_records(G, S):
    out = []
    for i, g in enumerate(S.ground):
        x, y = G.world(g['u'], g['v'])
        zs = []
        a = math.radians(g['yaw'])
        for sl in (-0.5, 0.0, 0.5):
            for sw in (-0.5, 0.0, 0.5):
                du = sl * g['length'] * math.cos(a) - sw * g['width'] * math.sin(a)
                dv = sl * g['length'] * math.sin(a) + sw * g['width'] * math.cos(a)
                zs.append(G.zuv(g['u'] + du, g['v'] + dv))
        relief = max(zs) - min(zs)
        out.append(dict(id='%s_v3_g%02d' % (SID, i), surface=g['surface'], shape=g['shape'],
                        x_cm=round(x * 100, 1), y_cm=round(y * 100, 1), z_cm=round((max(zs) + min(zs)) / 2 * 100, 1),
                        yaw=round((G.road_yaw - g['yaw']) % 360.0, 1), length_m=round(g['length'], 2),
                        width_m=round(g['width'], 2), depth_m=round(max(2.0, relief + 1.2), 1),
                        strength=g['strength'], sort=g['sort'], role=g['role']))
    return out


# ---------------------------------------------------------------------------- views and story frames

def lamp_point(G, S, pr):
    it = [i for i in S.items if i['key'] == 'AB_Lamp_A'][0]
    return (it['x'], it['y'], pr[id(it)]['bottom'] + 0.19), it


def views(G, S, pr):
    lp, _ = lamp_point(G, S, pr)
    lamp = [round(lp[0] * 100, 1), round(lp[1] * 100, 1), round(lp[2] * 100, 1)]
    fx, fy = G.world(1.5, -5.0)
    file_c = [round(fx * 100, 1), round(fy * 100, 1), round((G.z(fx, fy) + 0.8) * 100, 1)]
    out = []

    def cam(name, x, y, z, look, note=''):
        out.append(dict(name=name, cam_cm=[round(x * 100, 1), round(y * 100, 1), round(z * 100, 1)], look_cm=look, note=note))
    for name, s, look, note in (('carrier_a', 740.0, file_c, 'approach, 70 m out: the file, the tree and C3 across the road'),
                                ('carrier_b', HUD_M, lamp, 'road 790: the HUD line and the host\'s "lamp on the last one"'),
                                ('carrier_c', 803.0, file_c, 'road 803: abeam the last cart, looking up the file')):
        x, y, z = G.road_eye(s, 2.5)
        cam(name, x, y, z, look, note + ' (capture_look eye 2.5 m)')
    x, y, z = G.road_eye(CIN_P04_M, EYE_M[0])
    h = math.radians(G.heading(CIN_P04_M))
    d = 100.0
    look = [round((x + d * math.cos(h)) * 100, 1), round((y + d * math.sin(h)) * 100, 1),
            round((z + d * math.tan(math.radians(CIN_P04_PITCH))) * 100, 1)]
    cam('cinp04', x, y, z, look, 'CIN_P04 shots 1 and 4: road 700, eye 1.22 m, straight up the road, pitch -3')
    for name, (u, v, hh), tgt in (('orbit_a', (-5.0, -21.0, 3.2), file_c), ('orbit_b', (9.0, 17.0, 3.0), file_c),
                                  ('orbit_c', (23.0, -2.5, 2.2), None)):
        x, y = G.world(u, v)
        if tgt is None:
            cx, cy = G.world(-2.0, -6.5)
            tgt = [round(cx * 100, 1), round(cy * 100, 1), round((G.z(cx, cy) + 0.6) * 100, 1)]
        cam(name, x, y, G.z(x, y) + hh, tgt)
    c5 = S.carts['C5']
    x, y = G.world(c5['u'] - 1.2, c5['v'] - 3.0)
    cam('contact', x, y, G.z(x, y) + 1.0, lamp, 'the last cart from its outer side: bed on the ground, dust, the lamp')
    x, y = G.world(1.2, 3.6)
    cx, cy = G.world(0.9, 7.6)
    cam('contact_b', x, y, G.z(x, y) + 0.8, [round(cx * 100, 1), round(cy * 100, 1), round((G.z(cx, cy) + 0.3) * 100, 1)],
        'the tipped cart on the bank edge: its rail on the ground, the spill')
    x, y = G.world(-24.0, -26.0)
    cam('high34', x, y, G.z(x, y) + 20.0, file_c)
    x, y = G.world(-230.0, -190.0)
    cam('far300', x, y, G.z(x, y) + 30.0, file_c, 'from the flat 300 m down-road and right')
    return out


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
        out.append(((d @ Rt) / z / th, (d @ U) / z / tv, float(z)))
    return out


def frame_report(G, S, pr, s, pitch=0.0, eye_m=EYE_M[0]):
    """At road s, forward POV: where the lamp and the last cart are on screen, their distance and whether anything
    nearer covers the lamp (screen hull test against every nearer solid's projected box) or terrain hides it."""
    eye = G.road_eye(s, eye_m)
    yaw = G.heading(s)
    lp, lamp = lamp_point(G, S, pr)
    q = project(eye, yaw, pitch, [lp])[0]
    c5 = S.carts['C5']['item']
    c5s = [p for p in project(eye, yaw, pitch, box_points(G, S, pr, c5)) if p is not None]
    covered = []
    if q is not None:
        for it in S.items:
            if it is lamp or it['ism'] and max(it['size_m']) < 0.5:
                continue
            bp = box_points(G, S, pr, it)
            pp = [p for p in project(eye, yaw, pitch, bp) if p is not None]
            if len(pp) < 8:
                continue
            if min(p[2] for p in pp) >= q[2] - 0.05:
                continue
            if pt_in_poly((q[0], q[1]), hull([(p[0], p[1]) for p in pp])):
                covered.append(it['key'] + ('(' + it['cid'] + ')' if it['cid'] else ''))
    tan, _ = G.T.horizon_tan(np.array([eye[0] * 100]), np.array([eye[1] * 100]), np.array([eye[2]]),
                             np.array([lp[0] * 100]), np.array([lp[1] * 100]), skip_far_m=1.0)
    dist = math.dist(eye[:2], lp[:2])
    los = (lp[2] - eye[2]) / dist > float(tan[0])
    box = None
    if c5s:
        xs, ys = [p[0] for p in c5s], [p[1] for p in c5s]
        box = [round(float(min(xs)), 2), round(float(max(xs)), 2), round(float(min(ys)), 2), round(float(max(ys)), 2)]
    px_cm = 2 * dist * math.tan(math.radians(HFOV) / 2) / 1920.0 * 100.0
    # the lowest height above its own ground that shows over the terrain, at the last cart and at the tree
    hidden = {}
    for nm, it in (('last_cart', c5), ('tree', [i for i in S.items if i['group'] == 'tree'][0])):
        t2, _ = G.T.horizon_tan(np.array([eye[0] * 100]), np.array([eye[1] * 100]), np.array([eye[2]]),
                                np.array([it['x'] * 100]), np.array([it['y'] * 100]), skip_far_m=3.0)
        dd = math.dist(eye[:2], (it['x'], it['y']))
        hidden[nm] = round(max(0.0, eye[2] + float(t2[0]) * dd - G.z(it['x'], it['y'])), 2)
    return dict(road_m=s, pitch=pitch, eye_m=eye_m, lamp_dist_m=round(dist, 1),
                hidden_below_m=hidden,
                lamp_screen=None if q is None else [round(float(q[0]), 3), round(float(q[1]), 3)],
                lamp_in_frame=bool(q is not None and abs(q[0]) <= 1 and abs(q[1]) <= 1),
                lamp_covered_by=covered, lamp_terrain_los=bool(los), last_cart_box=box,
                cm_per_px_1920=round(px_cm, 1))


# ---------------------------------------------------------------------------- checks

def checks(G, S, recs, grecs, pr):
    notes, bad = [], []
    carts = [it for it in S.items if it['group'] == 'carts']
    if len(carts) != 5:
        bad.append('HUD says %s but the set has %d carts' % (HUD_TEXT, len(carts)))
    for r in recs:
        if r['road_clear_m'] < CLEAR_M:
            bad.append('ROAD %s %s %.2f m' % (r['id'], r['key'], r['road_clear_m']))
    # solids on the ground must not overlap in plan (the judge does not test loose-vs-loose; carts and spill are loose)
    ground_solids = [it for it in S.items if not it['ism'] and not it['stack']]
    for i in range(len(ground_solids)):
        for j in range(i + 1, len(ground_solids)):
            a, b = ground_solids[i], ground_solids[j]
            d = poly_mtv(footprint_uv(G, a, core=True), footprint_uv(G, b, core=True))[0]
            if d > 0.02:
                bad.append('PLAN OVERLAP %s x %s by %.2f m' % (a['role'][:40], b['role'][:40], d))
    # loads: on their bed's safe floor, clear of the rails; each upper layer carried by the one below; same-layer
    # loads apart
    for it in S.items:
        if not it['stack']:
            continue
        c = S.carts[it['cart']]
        bed = BED[c['key']]
        P, ax, lf = cart_frame(G, c)
        for u, v in footprint_uv(G, it):
            du, dv = u - c['u'], v - c['v']
            a = du * ax[0] + dv * ax[1]
            b = du * lf[0] + dv * lf[1]
            if abs(a) > bed['safe_len'] + 0.12 or abs(b) > bed['half_w_in']:
                bad.append('LOAD OFF BED %s on %s: corner at a=%.2f b=%.2f (floor +-%.2f x +-%.2f)'
                           % (it['key'], it['cart'], a, b, bed['safe_len'], bed['half_w_in']))
                break
        if it['layer'] > 1:
            below = [q for q in S.items if q['stack'] and q['cart'] == it['cart'] and q['layer'] < it['layer']]
            if not any(pt_in_poly((it['u'], it['v']), footprint_uv(G, q)) for q in below):
                bad.append('LOAD UNSUPPORTED %s on %s: its centre is over no lower load' % (it['key'], it['cart']))
        for q in S.items:
            if q is not it and q['stack'] and q['cart'] == it['cart'] and q['layer'] == it['layer'] and id(q) > id(it):
                d = poly_mtv(footprint_uv(G, it), footprint_uv(G, q))[0]
                if d > 0.03:
                    bad.append('LOAD CLASH %s x %s on %s by %.2f m' % (it['key'], q['key'], it['cart'], d))
    lp, lamp = lamp_point(G, S, pr)
    bar = [q for q in S.items if q['cart'] == 'C5' and q['key'] == 'MV_barrel_01'][0]
    r_top = CAT['MV_barrel_01']['size_cm'][0] * bar['scale'] / 200.0 * 0.8
    if math.hypot(lamp['u'] - bar['u'], lamp['v'] - bar['v']) + 0.08 > r_top:
        bad.append('LAMP OFF THE BARREL HEAD')
    # the tipped cart: every sample of its down face within [-6, +4] cm of the heightmap
    tip = [it for it in S.items if it['kind'] == 'tipped'][0]
    g = pr[id(tip)]['gaps_cm']
    notes.append('C3 tipped: yaw %.1f pitch %.1f roll %.1f; down-face gaps %s cm (bed top faces the road)'
                 % (tip['yaw'], tip['pitch'], tip['roll'], g))
    if max(g) > 4.0 or min(g) < -8.0:
        bad.append('TIPPED C3 does not lie on the ground: gaps %s cm' % g)
    for it in S.items:
        if it['group'] in ('creep', 'stones', 'hearth', 'rocks') and S.on_lane(it['u'], it['v'], 0.15):
            bad.append('ON PATH %s at (%.1f, %.1f)' % (it['key'], it['u'], it['v']))
    left = clash_pairs(G, S)
    for d, allow, a, b in left:
        bad.append('ISM OVERLAP %s into %s by %.2f m (allowed %.2f)' % (a['key'], b['key'], d, allow))
    mv = sorted(S.moved.values())
    notes.append('ISM declash: %d of %d pieces moved (max %.2f m), %d left out, %d overlaps left'
                 % (sum(1 for m in mv if m > 0.005), len(mv), max(mv) if mv else 0.0, len(S.dropped), len(left)))
    for nm, x, y in NEIGHBOURS:
        d = min(math.hypot(x / 100 - it['x'], y / 100 - it['y']) for it in S.items)
        notes.append('%s: nearest V3 piece %.1f m away' % (nm, d))
        if d < 3.0:
            bad.append('NEIGHBOUR %s within 3 m' % nm)
    # the ground-standing pieces through the V2 judge (setdress_contact.offline_reports; stacks are not modelled there)
    solo_ground = [r for r in recs if not r['ism'] and not r['stack'] and r['settle']['mode'] != 'none']
    reps, items = sc.offline_reports(solo_ground, lambda xc, yc: G.z(xc / 100.0, yc / 100.0) * 100.0)
    viol, _ = sc.judge(reps, items, [])
    notes.append('offline judge (setdress_contact) on %d ground pieces: %d violations %s'
                 % (len(solo_ground), len(viol), viol[:4]))
    bad += ['JUDGE %s %s %s' % v for v in viol]
    # upright carts and the wheel pair: the predicted physics settle (corner plane, rule max) less the sink. Every
    # corner (the wheels / shaft tips of the AB cart, the bed ends of the MV beds) must reach the ground (<= 3 cm).
    for it in S.items:
        if it['kind'] != 'cart' and it['key'] != 'MV_cart_02_wheels':
            continue
        rs = rest_settle(G, it)
        sink = it['settle']['sink_cm']
        after = [g - sink for g in rs['gaps_cm']]
        notes.append('%s settle: ground tilt %.1f deg, sink %d cm, corner gaps %s cm, centre %+.0f cm'
                     % (it['cid'] or it['key'], rs['tilt_deg'], sink, [round(g) for g in after[:4]], after[4]))
        if max(after[:4]) > 3.0:
            bad.append('%s: a corner stays %.0f cm off the ground after the settle' % (it['cid'] or it['key'], max(after[:4])))
        if rs['tilt_deg'] > it['settle']['max_tilt_deg']:
            bad.append('%s: the ground tilts %.1f deg, more than its settle allows' % (it['cid'] or it['key'], rs['tilt_deg']))
    return notes, bad


# ---------------------------------------------------------------------------- the plot

def plot(G, S, recs, grecs, pr, frames):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon, Ellipse, Circle
    fig = plt.figure(figsize=(20, 12.5))
    ax = fig.add_axes([0.03, 0.30, 0.58, 0.66])
    us = np.arange(-24, 24.01, 0.25)
    vs = np.arange(-18, 14.01, 0.25)
    UU, VV = np.meshgrid(us, vs)
    X = G.o[0] + UU * G.f[0] + VV * G.l[0]
    Y = G.o[1] + UU * G.f[1] + VV * G.l[1]
    Z = G.T.height(X * 100, Y * 100)
    cs = ax.contour(UU, VV, Z, levels=np.arange(np.floor(Z.min() * 10) / 10, Z.max(), 0.1), colors='#c9bfae', linewidths=0.5)
    ax.clabel(cs, cs.levels[::5], fmt='%.1f', fontsize=6, colors='#9a8f7c')
    ax.fill_between([-24, 24], -4.5, 4.5, color='#cfc6b8', alpha=0.55, lw=0)
    ax.axhline(0, color='#8a8174', lw=1, ls='--')
    ax.text(-23.6, -4.1, 'road (9 m ribbon), travel ->  (road 786 .. 834 m)', fontsize=9, color='#5d564c')
    for s in (-1, 1):
        ax.axhline(s * CLEAR_M, color='#c55', lw=0.8, ls=':')
    ax.text(15.0, CLEAR_M + 0.15, 'road-core clearance 5 m', fontsize=8, color='#c55')
    col = dict(packed_earth='#b08a5a', path='#6b4d33', rubble_dust='#d8c9aa', soot='#2d2926')
    for g in S.ground:
        if g['shape'] == 'capsule':
            a = math.radians(g['yaw'])
            L = g['length'] - g['width']
            p0 = (g['u'] - L / 2 * math.cos(a), g['v'] - L / 2 * math.sin(a))
            p1 = (g['u'] + L / 2 * math.cos(a), g['v'] + L / 2 * math.sin(a))
            ax.plot([p0[0], p1[0]], [p0[1], p1[1]], color=col[g['surface']], lw=max(1.0, g['width'] * 19), alpha=0.45,
                    solid_capstyle='round')
        else:
            ax.add_patch(Ellipse((g['u'], g['v']), g['length'], g['width'], angle=g['yaw'], color=col[g['surface']],
                                 alpha=0.4 * g['strength'] + 0.1, lw=0))
    style = {'carts': ('#3d2a17', '#a27a4c'), 'loads': ('#4a3a24', '#d9c39a'), 'wheels': ('#3d2a17', '#8a6a44'),
             'spill': ('#4a3a24', '#d9c39a'), 'tree': ('#3a3a30', '#8f8f78'), 'hearth': ('#222', '#666')}
    for it in sorted(S.items, key=lambda i: (i['stack'], i['layer'])):
        if it['ism']:
            c = '#6d8f4e' if it['group'] == 'creep' else '#7d6e5f'
            ms = 6 if it['group'] == 'creep' else max(2.5, max(it['size_m'][:2]) * 8)
            ax.plot(it['u'], it['v'], 'o' if it['group'] == 'creep' else 's', ms=ms, color=c, alpha=0.85, mec='none')
            continue
        ec, fc = style[it['group']]
        if it['group'] == 'tree':
            ax.add_patch(Circle((it['u'], it['v']), 1.6, fc='#8f8f78', ec='#55554a', alpha=0.25, lw=1, ls='--'))
            ax.add_patch(Circle((it['u'], it['v']), 0.35, fc='#55554a', ec='#333', lw=1))
            continue
        if it['key'] == 'AB_Lamp_A':
            ax.plot(it['u'], it['v'], '*', ms=18, color='#e0a21a', mec='#6b4a00', zorder=9)
            continue
        ax.add_patch(Polygon(footprint_uv(G, it), closed=True, ec=ec, fc=fc, lw=1.3 if it['group'] == 'carts' else 0.8,
                             alpha=0.92 if not it['stack'] else 0.75, zorder=4 + it['layer']))
    for cid, c in S.carts.items():
        P, axc, lf = cart_frame(G, c)
        if cid == 'C3':
            continue
        t = P(c['L'] / 2 - 0.3, 0)
        ax.annotate('', xy=(t[0] + 0.9 * axc[0], t[1] + 0.9 * axc[1]), xytext=t,
                    arrowprops=dict(arrowstyle='-|>', color='#3d2a17', lw=1.4), zorder=8)
        ax.text(c['u'] - 0.5, c['v'] - 1.55 - (0.2 if cid == 'C1' else 0), cid, fontsize=11, weight='bold', color='#3d2a17')
    c3 = S.carts['C3']
    ax.text(c3['u'] - 0.3, c3['v'] + 0.8, 'C3 (tipped)', fontsize=11, weight='bold', color='#3d2a17')
    v1 = [p for s in json.load(open(V1_SITES_JSON, encoding='utf8'))['sites'] if s['id'] == SID for p in s['placements']]
    for p in v1:
        u, v = G.local(p['x_cm'] / 100, p['y_cm'] / 100)
        if -24 < u < 24 and -18 < v < 14:
            ax.plot(u, v, 'x', color='#c33', ms=6, mew=1.2, alpha=0.7)
    ax.text(-23.6, 12.9, 'x = V1 S05 dressing (37 placements), cleared before V3 is placed', fontsize=8, color='#c33')
    lp, lamp = lamp_point(G, S, pr)
    ax.annotate('FOCAL: the last cart, a cold brass lamp\non its barrel (lamp top %.2f m above the ground)'
                % (lp[2] + 0.19 - G.z(lamp['x'], lamp['y'])), xy=(lamp['u'], lamp['v']), xytext=(-23.0, -16.5),
                fontsize=9.5, arrowprops=dict(arrowstyle='->', color='#6b4a00'), color='#6b4a00')
    ax.annotate('the shade tree (dead)\nand the cold hearth', xy=(S.tree[0], S.tree[1]), xytext=(-23.0, -12.4), fontsize=9,
                arrowprops=dict(arrowstyle='->', color='#55554a'))
    ax.annotate('wheel ruts where each cart\nleft the road', xy=(-5.0, -4.9), xytext=(-18.8, -2.3), fontsize=8.5,
                arrowprops=dict(arrowstyle='->', color='#6b4d33'))
    ax.annotate("C2's wheels, stood aside", xy=(S.carts['C2']['u'] + 0.15, -7.9), xytext=(6.5, -16.2), fontsize=8.5,
                arrowprops=dict(arrowstyle='->', color='#3d2a17'))
    ax.annotate('the spill, toward the road', xy=(0.4, 6.4), xytext=(8.0, 3.2), fontsize=8.5,
                arrowprops=dict(arrowstyle='->', color='#4a3a24'))
    wu_, wv_ = G.dir_uv(*WIND_TO)
    wn = math.hypot(wu_, wv_)
    ax.arrow(19.0, 11.0, 3.0 * wu_ / wn, 3.0 * wv_ / wn, head_width=0.45, color='#6a86a8')
    ax.text(16.3, 11.9, 'wind (dust drifts in the lee)', fontsize=8, color='#6a86a8')
    eu, ev = G.local(*G.road_eye(HUD_M, 1.0)[:2])
    ax.plot(eu, ev, 'k^', ms=8, zorder=9)
    ax.text(eu - 1.0, ev + 0.6, 'HUD + host line, 790', fontsize=8)
    ax.set_xlim(-24, 24)
    ax.set_ylim(-18, 14)
    ax.set_aspect('equal')
    ax.set_xlabel('u: metres along the road from 810 m (travel ->)')
    ax.set_ylabel('v: metres LEFT of the road')
    ax.set_title('V3 the cart convoy (S05_CartConvoy), plan: 0.1 m contours; ISM stones = squares, dead shrubs = green; '
                 'loads light; arrows = noses')

    def frame_ax(rect, title):
        a2 = fig.add_axes(rect)
        a2.set_xlim(-1, 1)
        a2.set_ylim(-1, 1)
        a2.set_aspect(9 / 16)
        a2.set_xticks([])
        a2.set_yticks([])
        a2.set_title(title, fontsize=9.5)
        a2.set_facecolor('#dfe2e4')
        return a2

    def draw_frame(a2, eye, yw, pt, hfov=HFOV):
        xs = np.linspace(-1, 1, 161)
        th = math.tan(math.radians(hfov) / 2)
        tv = th / (16 / 9)
        sky = []
        for sx in xs:
            az = yw + math.degrees(math.atan(sx * th))
            d = np.arange(3.0, 4000.0, 3.0)
            px = eye[0] + d * math.cos(math.radians(az))
            py = eye[1] + d * math.sin(math.radians(az))
            h = G.T.height(px * 100, py * 100)
            el = np.max(np.degrees(np.arctan2(h - eye[2], d)))
            sky.append(math.tan(math.radians(el - pt)) / tv)
        a2.fill_between(xs, -1, np.clip(sky, -1, 1), color='#c2ae8e', lw=0)
        for vv in (-4.5, 4.5):
            pts = [(*G.world(uu, vv), G.zuv(uu, vv)) for uu in np.arange(-120, 60, 1.0)]
            q = [p for p in project(eye, yw, pt, pts, hfov) if p is not None]
            if q:
                a2.plot([p[0] for p in q], [p[1] for p in q], color='#8c7f6a', lw=0.7)
        edges = [(0, 1), (2, 3), (4, 5), (6, 7), (0, 2), (1, 3), (4, 6), (5, 7), (0, 4), (1, 5), (2, 6), (3, 7)]
        colr = {'carts': '#3d2a17', 'loads': '#8a6a2a', 'wheels': '#3d2a17', 'spill': '#8a6a2a', 'tree': '#55554a',
                'hearth': '#333', 'stones': '#8a7d6c', 'creep': '#56753c', 'rocks': '#6d6356'}
        for it in S.items:
            if it['ism'] and it['group'] != 'rocks':
                continue
            q = project(eye, yw, pt, box_points(G, S, pr, it), hfov)
            for i0, i1 in edges:
                if q[i0] is not None and q[i1] is not None:
                    a2.plot([q[i0][0], q[i1][0]], [q[i0][1], q[i1][1]], color=colr[it['group']],
                            lw=1.2 if it['group'] in ('carts', 'tree') else 0.6)
        lp_, _ = lamp_point(G, S, pr)
        tq = project(eye, yw, pt, [lp_], hfov)[0]
        if tq is not None and abs(tq[0]) <= 1 and abs(tq[1]) <= 1:
            a2.plot(tq[0], tq[1], '*', color='#e0a21a', ms=12, mec='#6b4a00')
        for g in (-1 / 3, 1 / 3):
            a2.axvline(g, color='w', lw=0.5, alpha=0.6)
            a2.axhline(g, color='w', lw=0.5, alpha=0.6)
    fr = {(f['road_m'], f['pitch']): f for f in frames}
    s = CIN_P04_M
    a2 = frame_ax([0.63, 0.66, 0.35, 0.30], 'CIN_P04 end frame: road 700, 90 deg POV, pitch -3 (the convoy %.0f m ahead)'
                  % fr[(s, CIN_P04_PITCH)]['lamp_dist_m'])
    draw_frame(a2, G.road_eye(s, EYE_M[0]), G.heading(s), CIN_P04_PITCH)
    s = HUD_M
    a3 = frame_ax([0.63, 0.34, 0.35, 0.30], 'Road 790: HUD "%s" + the host\'s line; forward POV' % HUD_TEXT)
    draw_frame(a3, G.road_eye(s, EYE_M[0]), G.heading(s), 0.0)
    s = 765.0
    a4 = frame_ax([0.63, 0.02, 0.35, 0.30], 'Road 765: the reveal, 45 m out: the tree over the tail, the lamp cart, C3 left')
    draw_frame(a4, G.road_eye(s, EYE_M[0]), G.heading(s), 0.0)
    tx = fig.add_axes([0.03, 0.02, 0.58, 0.24])
    tx.axis('off')
    lines = ['Frames (eye 1.22 m; star = the lamp):']
    for f in frames:
        lines.append('  road %5.0f pitch %+.0f: lamp %5.1f m away, screen %s, in frame %s, covered by %s, terrain LOS %s, '
                     '%.1f cm/px' % (f['road_m'], f['pitch'], f['lamp_dist_m'], f['lamp_screen'], f['lamp_in_frame'],
                                     f['lamp_covered_by'] or 'nothing', f['lamp_terrain_los'], f['cm_per_px_1920']))
    solo = [r for r in recs if not r['ism']]
    lines.append('Counts: %d placements: %d solo actors, %d ISM instances in %d hosts, %d decals. 5 carts (HUD).'
                 % (len(recs), len(solo), len(recs) - len(solo), len({(r['group'], r['asset']) for r in recs if r['ism']}),
                    len(grecs)))
    tx.text(0, 1, '\n'.join(lines), va='top', fontsize=9, family='monospace')
    fig.savefig(OUT_PNG, dpi=80)
    return OUT_PNG


# ---------------------------------------------------------------------------- main

def load_flips():
    if os.path.exists(MEASURED_JSON):
        return json.load(open(MEASURED_JSON, encoding='utf8')).get('flip', [])
    return []


def build(flips=None):
    G = Ground()
    S = compose(G, load_flips() if flips is None else flips)
    recs = [to_record(G, S, i, it) for i, it in enumerate(S.items)]
    grecs = ground_records(G, S)
    pr = predict(G, S)
    return G, S, recs, grecs, pr


def all_frames(G, S, pr):
    out = [frame_report(G, S, pr, CIN_P04_M, CIN_P04_PITCH)]
    for s in (740.0, 770.0, HUD_M, 798.0):
        out.append(frame_report(G, S, pr, s, 0.0))
    return out


def write(G, S, recs, grecs, pr, frames, notes, bad):
    cx, cy = G.world(1.0, -3.0)
    cz = G.z(cx, cy)
    vw = views(G, S, pr)
    r = 26.0
    solo = [x for x in recs if not x['ism']]
    ism = [x for x in recs if x['ism']]
    probe = [dict(id=S.carts[c]['item']['id'], cart=c, key=S.carts[c]['key'],
                  want_nose_yaw=round((G.road_yaw + S.carts[c]['rel']) % 360.0, 1),
                  flipped=c in S.flips) for c in ('C1', 'C2', 'C3', 'C4', 'C5')]
    site = dict(
        id=SID, story_set=SET, name='Taflalut Deighim, the Cart Convoy (V3)', kind='caravan vignette', order=2,
        road_m=int(S0), side='on/both', lateral_m=0, centre_cm=[round(cx * 100, 1), round(cy * 100, 1), round(cz * 100, 1)],
        road_yaw=round(G.road_yaw, 1), radius_m=r, zone='Z1 Valley',
        storm='storm-dusk at its worst: dust sheets and gusts; dust drifts on the lee side of every cart',
        role='reveal', story='B04 (no voice): the carts they left all at once; HUD %s at 790; the host remembers "the '
                             'carts lined up with a lamp on the last one" at 790' % HUD_TEXT,
        decay=2, style='MedievalVillage cart beds + the AshesOfBazaar handcart, chest, lamp and jars',
        layout='\n'.join([
            '   bank:            C3 tipped toward the road, its spill fanned out below it   (a lone wheel behind)',
            '  ======== road 786-834 m, a 230 m straight, travel -> ======== the core stays clear ========',
            '  tail lamp  C5 [barrel+lamp]  C4 [barrels]   <gap>   C2 [chest, sacks]  C1 AB handcart on its wheels ->',
            '     ruts from the road edge to each cart; dust in the lee (down-road, outward); shrubs against them',
            '  the dead shade tree + the cold hearth and its pot            C2\'s wheels stood beside it',
        ]),
        notes='Story set V3 on the road site S05_CartConvoy. The V1 dressing (setdress_sites.json S05_CartConvoy_000..036) '
              'is removed by `clear` first. Five carts because the HUD counts five. Nothing religious, nothing modern; no '
              'people; the lamp is never lit (no light, no emissive).',
        story_owned=['V3 the cart convoy (this file is the story set)'], verify_only=False, layer='road', poi=None,
        counts=dict(placements=len(recs), actors=len(solo) + len({(x['group'], x['asset']) for x in ism}),
                    ism_instances=len(ism), physics=sum(1 for x in solo if x['settle']['mode'] == 'physics'),
                    batch01=0, decals=len(grecs)),
        views=[{k: v[k] for k in ('name', 'cam_cm', 'look_cm')} for v in vw],
        view_notes={v['name']: v['note'] for v in vw if v['note']},
        placements=recs, ground=grecs, units=[], waivers=[],
        facing_probe=probe,
        v2=dict(frame=dict(origin_road_m=S0, origin_cm=[round(G.o[0] * 100, 1), round(G.o[1] * 100, 1)],
                           u='along travel', v='left of travel'),
                lanes=S.lanes, frames=frames, checks=notes, violations=bad,
                flips=sorted(S.flips), facing_measured=os.path.exists(MEASURED_JSON)),
    )
    pts = [(site['centre_cm'][0], site['centre_cm'][1])] + [(v['cam_cm'][0], v['cam_cm'][1]) for v in vw
                                                             if v['name'] not in ('far300', 'high34')]
    site['load_box_cm'] = [round(min(p[0] for p in pts) - (r + 30) * 100), round(min(p[1] for p in pts) - (r + 30) * 100),
                           round(max(p[0] for p in pts) + (r + 30) * 100), round(max(p[1] for p in pts) + (r + 30) * 100)]
    doc = dict(generated_by='Tools/World/story_sets/v3_cart_convoy.py', method='docs/world/SETDRESS_V2.md',
               design='docs/world/story_sets/V3.md', level='/Game/level/Saskarta_WP',
               conventions=dict(xy='world cm; yaw = UE yaw deg', bounds='x_cm/y_cm is the mesh BOUNDS CENTRE',
                                ground='decal patches: DecalActor pitch -90, yaw, size (depth/2, width/2, length/2)',
                                contact='rigid | rest | lie (SETDRESS_V2.md section 3); loads are rest + stack',
                                site_uv='u m along travel from road 810, v m left of travel',
                                facing='cart meshes are long along local Y; yaw = nose direction - 90, assuming the shafts '
                                       'at local +Y until `facing` measures them (V3_measured.json flips)'),
               rejected=[], checks=[], sites=[site])
    with open(OUT_JSON, 'w', encoding='utf8') as fh:
        json.dump(doc, fh, indent=1, ensure_ascii=False)
    return site


# ---------------------------------------------------------------------------- editor steps of this set

FACING_BODY = r'''
have = site_actors(SITE)
others = [have[k] for k in have]
for p in PROBE:
    a = have.get('SD_' + p['id'])
    if a is None:
        print('FACING missing ' + p['id'])
        continue
    comp = a.static_mesh_component
    b = comp.static_mesh.get_bounds()
    o, e = b.origin, b.box_extent
    s = a.get_actor_scale3d().x
    r = a.get_actor_rotation()
    ax = axes(r.yaw, r.pitch, r.roll)
    l = a.get_actor_location()
    ign = [q for q in others if q != a]
    hits = {}
    for side in (-1, 1):
        n = 0
        for f in (0.84, 0.92, 0.97):
            for g in (-0.15, 0.0, 0.15):
                p0 = apply(ax, ((o.x + g * e.x) * s, (o.y + side * f * e.y) * s, (o.z + e.z) * s + 40.0))
                p1 = apply(ax, ((o.x + g * e.x) * s, (o.y + side * f * e.y) * s, (o.z - e.z) * s - 40.0))
                h = hit_of(syslib.line_trace_single(world, V(l.x + p0[0], l.y + p0[1], l.z + p0[2]),
                                                    V(l.x + p1[0], l.y + p1[1], l.z + p1[2]),
                                                    unreal.TraceTypeQuery.TRACE_TYPE_QUERY1, True, ign,
                                                    unreal.DrawDebugTrace.NONE, True))
                if h is not None:
                    t = h.to_tuple()
                    if t[0] and t[HIT_ACTOR] == a:
                        n += 1
        hits[side] = n
    if hits[-1] + 3 <= hits[1]:
        shafts = '-Y'
    elif hits[1] + 3 <= hits[-1]:
        shafts = '+Y'
    else:
        shafts = '?'
    print('FACING ' + p['id'] + ' ' + p['cart'] + ' hits_minusY=' + str(hits[-1]) + ' hits_plusY=' + str(hits[1]) +
          ' shafts=' + shafts + ' yaw=' + str(round(r.yaw, 1)))
print('FACING DONE')
'''

NODECAL_BODY = r'''
have = site_actors(SITE)
n = 0
for lab in sorted(have.keys()):
    a = have[lab]
    if not isinstance(a, unreal.StaticMeshActor):
        continue
    if 'SD_ism' in [str(t) for t in a.tags]:
        continue
    if 'SD_ground' in [str(t) for t in a.tags]:
        continue
    a.static_mesh_component.set_editor_property('receives_decals', False)
    n += 1
print('NODECAL ' + str(n) + ' DONE')
'''


def custom_step(step, argv):
    """This set's own editor steps, sent through place_setdress.py's Runner (PIE check, banned words, one short call)."""
    import place_setdress as ps
    ap = argparse.ArgumentParser(prog='v3_cart_convoy.py ' + step)
    ap.add_argument('--owner', default=os.environ.get('SETDRESS_OWNER', ''))
    ap.add_argument('--no-gate-check', action='store_true')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--port', type=int, default=int(os.environ.get('HAYBA_PORT', 52342)))
    args = ap.parse_args(argv)
    doc = json.load(open(OUT_JSON, encoding='utf8'))
    site = doc['sites'][0]
    R = ps.Runner(args)
    if step == 'facing':
        out = R.send('%s_facing' % SID, ps.build_script(FACING_BODY, SITE=SID, PROBE=[
            {k: p[k] for k in ('id', 'cart')} for p in site['facing_probe']]))
        if args.dry_run:
            return
        meas = json.load(open(MEASURED_JSON, encoding='utf8')) if os.path.exists(MEASURED_JSON) else {}
        flips = set(meas.get('flip', []))
        raw = {}
        for line in (out or '').splitlines():
            if not line.startswith('FACING ') or line.startswith('FACING DONE') or ' missing ' in line:
                continue
            parts = line.split()
            cid = parts[2]
            shafts = [q for q in parts if q.startswith('shafts=')][0][7:]
            raw[cid] = line
            # the generator points local +Y at the nose (or -Y when already flipped): the shafts must be there
            want = '-Y' if cid in flips else '+Y'
            if shafts == '?':
                print('FACING %s: unclear from the traces; judge it in the captures (orbit_c looks at the noses)' % cid)
            elif shafts != want:
                flips ^= {cid}
                print('FACING %s: the shafts are at %s, so it faces down-road: flip recorded' % (cid, shafts))
        meas.update(flip=sorted(flips), raw=raw, source='v3_cart_convoy.py facing (centreline traces at each bed end)')
        with open(MEASURED_JSON, 'w', encoding='utf8') as fh:
            json.dump(meas, fh, indent=1)
        print('facing: flips now %s -> rerun `python Tools/World/story_sets/v3_cart_convoy.py --no-plot`, then '
              '`v3_cart_convoy.py editor replace <the flipped carts\' ids>` (the loads stay: they are centred on the '
              'beds) before settle' % sorted(flips))
        return
    if step == 'nodecal':
        ps.gate_check(argparse.Namespace(owner=args.owner, dry_run=args.dry_run, no_gate_check=args.no_gate_check), 'place')
        R.send('%s_nodecal' % SID, ps.build_script(NODECAL_BODY, SITE=SID))
        if not args.dry_run:
            st = ps.read_state(SID)
            st['dirty'] = True
            ps.write_state(SID, st)
        return


def run_editor(argv, materials=False):
    """Run a place_setdress.py step (or build_setdress_materials.py) with the V2 site file swapped for V3.json."""
    import place_setdress as ps
    ps.SITES_V2_JSON = OUT_JSON
    if materials:
        import build_setdress_materials as bm
        argv = list(argv)
        if argv and argv[0] == 'variants' and SID not in argv:
            argv.insert(1, SID)
        sys.argv = ['build_setdress_materials.py'] + argv
        bm.main()
        return
    step = argv[0]
    rest = argv[1:]
    if '--v2' not in rest:
        rest.append('--v2')
    if step == 'capture' and '--views' not in rest:
        rest += ['--views', 'carrier_a,carrier_b,carrier_c,cinp04,orbit_a,orbit_b,orbit_c,contact,contact_b,high34,far300']
    sys.argv = ['place_setdress.py', step] + ([] if step in ('list', 'probe') else [SID]) + rest
    ps.main()


def main():
    if len(sys.argv) > 1 and sys.argv[1] == 'editor':
        return run_editor(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == 'materials':
        return run_editor(sys.argv[2:], materials=True)
    if len(sys.argv) > 1 and sys.argv[1] in ('facing', 'nodecal'):
        return custom_step(sys.argv[1], sys.argv[2:])
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--no-plot', action='store_true')
    args = ap.parse_args()
    G, S, recs, grecs, pr = build()
    frames = all_frames(G, S, pr)
    notes, bad = checks(G, S, recs, grecs, pr)
    site = write(G, S, recs, grecs, pr, frames, notes, bad)
    c = site['counts']
    print('%s (%s): %d placements, %d actors (ISM groups once each), %d ISM instances, %d decals'
          % (SID, SET, c['placements'], c['actors'], c['ism_instances'], c['decals']))
    print('road clearance min %.2f m; flips %s (%s)' % (min(r['road_clear_m'] for r in recs), sorted(S.flips),
                                                      'measured' if os.path.exists(MEASURED_JSON) else 'NOT measured: run facing'))
    for n in notes:
        print(' ', n)
    for f in frames:
        print('  frame', f)
    if not args.no_plot:
        print('plot', plot(G, S, recs, grecs, pr, frames))
    print('wrote', OUT_JSON)
    if bad:
        print('VIOLATIONS:')
        for b in bad:
            print('  ', b)
        sys.exit(1)


if __name__ == '__main__':
    main()
