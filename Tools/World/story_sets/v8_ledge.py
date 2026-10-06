"""V8 the ledge (road site S24_Ledge): the story set, composed with the set-dressing V2 method.

    python Tools/World/story_sets/v8_ledge.py                   # write V8.json + the plot, print the checks
    python Tools/World/story_sets/v8_ledge.py --no-plot         # data and checks only
    python Tools/World/story_sets/v8_ledge.py editor <step> [place_setdress args]
          # runs Tools/World/place_setdress.py <step> S24_Ledge --v2 against Tools/World/story_sets/V8.json
    python Tools/World/story_sets/v8_ledge.py materials variants
          # runs Tools/World/build_setdress_materials.py variants S24_Ledge against V8.json

Story (docs/story/storyline.md section 7, story-events.json B14_LOOK_BACK): the top of the climb. The Keeper
stopped here once, with the Visitor; B14's two archive lines were recorded here ("They have only seen this
mountain in my stories..." / "I will gather what can still be kept..."). Kit: two tixjegefa_tier_2 slabs lying
flat as a low ledge, a dead_tree_trunk_2k bench, a fallen, unlit Lantern_01.

The place: a log bench on the lip of the shoulder, with two slabs laid LEVEL in front of it as the ledge (the
only level lines on a 21-26 degree slope, so they read as made by hand). A band of partly buried rocks holds the
ledge's ends and runs down the slope; the slabs are chinked with small stones on their downhill faces, and a
thin spill of stones runs down the fall line under them. Dead shrubs grow in the lee of the log and the rocks and
from the slab joint; dry tufts (the landscape's own LGT_Saskarta_DryGrass meshes and MIs) gather where the slope
holds soil against stone. A trodden path leaves the road on the down-road side. Nothing else: Z6 is "the fewest
objects on the road".

Where: centred at road 4,476 m, 7-12 m left (the storyline's "4,460, left 6 m" moved 16 m up-road). The
B14 trigger stays at 4,460. G14_LOOK_BACK eases the POV left over 4,460-4,470 and holds 4,470-4,480 on
Saskarta.Glance.ValleyEast (the boot point, 3 km east). A ledge abeam 4,460 is never in that frame (it is 61-98
degrees off the look at every instant; the 90 deg frame reaches 45); centred at 4,476 it slides through the lower
third for the whole hold, always well below the look line, so it never covers the boot point. After the hold the
runner only gives the look back (no ease back), so the view stays put and the ledge leaves the frame lower left. On the approach
(4,420-4,458) the road climbs to it, so the ledge stands at eye level left of centre in the forward view (centre
third at 4,440, on the left-third line at 4,450, inside the left third by 4,456).

Offline only: nothing here talks to Unreal. The editor steps run place_setdress.py through `editor` (it swaps
the V2 site file for V8.json; place_setdress.py itself is not edited).
"""
import argparse
import json
import math
import os
import random
import re
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
WORLD = os.path.dirname(HERE)
ROOT = os.path.dirname(os.path.dirname(WORLD))
sys.path.insert(0, os.path.join(ROOT, 'Tools', 'Story'))
sys.path.insert(0, WORLD)
import build_road_profile as brp  # noqa: E402  (read-only use: the heightmap and the road polyline)
import setdress_catalog  # noqa: E402  (read-only use: asset paths and sizes)

OUT_JSON = os.path.join(HERE, 'V8.json')
OUT_PNG = os.path.join(ROOT, 'docs', 'world', 'story_sets', 'V8.png')
SID = 'S24_Ledge'          # the road site: the V1 stand-ins carry the tag SD_S24_Ledge, so `clear` removes them
SET = 'V8'
S0 = 4476.0                # site origin, road m
TRIGGER_M = 4460.0         # B14_LOOK_BACK pass trigger
GLANCE = dict(ease_in_s=2.0, hold_s=2.0, release_s=1.0)          # story-events.json G14_LOOK_BACK (5 s)
GLANCE_TARGET_CM = (616580.0, 463550.0, -35328.0)                # Tools/GameFlow/glance_targets.json ValleyEast
CARRIER_MS = 5.0           # story-events.json curves.carrier_speed_cms: 500 cm/s until 4,600
EYE_M = (1.22, 1.55)       # probe_ending.json carrier_eye_z (provisional) and CINEMATICS.md "POV at 155 cm"
HFOV = 90.0                # the carrier POV (build_cinematics.py pov = focal_for_hfov(90))
WIDE24_CAM_CM = (365009.7, 348809.8, 13500.0)                    # probe_ending.json wide24 (provisional)
WIDE24_LOOK_CM = (298080.0, 483050.0, 10900.0 + 2600.0)          # mast base + 26 m (build_cinematics.plan_cin24)
WIDE24_HFOV = math.degrees(2 * math.atan(23.76 / 2 / 200.0))     # 200 mm on the 23.76 mm filmback
CLEAR_M = 5.0              # road centreline -> footprint edge (build_setdress_sites.py CLEAR_M)
STANDINS = [               # the V1 stand-ins placed by LANE_SD (setdress_sites.json S24_Ledge_000..003)
    ('S24_Ledge_000', 'FAB_TempleStones', 320729.6, 438852.9),
    ('S24_Ledge_001', 'FAB_TempleStones', 320769.6, 439072.9),
    ('S24_Ledge_002', 'PH_trunk', 320929.6, 438952.9),
    ('S24_Ledge_003', 'PH_lantern', 320709.6, 439032.9),
]
CAT = setdress_catalog.load()
EXTRA = {   # meshes not in the catalog (size from Tools/World/setdress_assets.json)
    'PH_lantern_glass': dict(path='/Game/Pallbearer/PolyHaven/Lantern_01/Lantern_01_2k/StaticMeshes/Lantern_01_glass',
                             cat='prop', size_cm=[7.0, 7.0, 7.0]),
}
# The landscape's own dry tufts: LGT_Saskarta_DryGrass (Tools/Foliage/configure_grass.py) grows these four meshes
# with these four MIs on exposed ground, which the summit is. The V2 composer plants the same pairs as creep
# (setdress_catalog.DRY_TUFT_MATERIAL, setdress_v2.creep). Held here too, so this generator does not depend on the
# V2 lane's uncommitted catalog; checks() fails if the two tables ever disagree. Sizes: setdress_assets.json.
MVG = '/Game/MedievalVillage/Demo/StaticMesh/Grass/SM_Grass_'
TUFT_MI = '/Game/SaskartaGaea/Foliage/Materials/MI_Saskarta_DryTuft_'
TUFTS = {
    'MV_Grass_V1_02': (MVG + 'V1_02', [45.0, 68.0, 44.0], TUFT_MI + 'Straw'),
    'MV_Grass_V2_01': (MVG + 'V2_01', [36.0, 47.0, 54.0], TUFT_MI + 'Ochre'),
    'MV_Grass_V2_03': (MVG + 'V2_03', [61.0, 60.0, 53.0], TUFT_MI + 'Olive'),
    'MV_Grass_V5_05': (MVG + 'V5_05', [13.0, 15.0, 40.0], TUFT_MI + 'Rust'),
}
for _k, (_p, _s, _m) in TUFTS.items():
    EXTRA[_k] = dict(path=_p, cat='shrub', size_cm=_s, material=_m)


def asset(key):
    e = EXTRA.get(key) or CAT[key]
    return e['path'], e['cat'], e['size_cm']


def draw_distance_cm(max_dim_m):
    """Max draw distance (never 0 = infinite: pcg-spawner-cull-distance-default); build_setdress_sites.py table."""
    for lim, d in ((0.6, 4000.0), (1.5, 6000.0), (4.0, 25000.0), (10.0, 80000.0)):
        if max_dim_m < lim:
            return d
    return 200000.0


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

    def grad(self, x, y, h=1.0, r=0.0):
        """Ground gradient (dz/dx, dz/dy). r > 0: a least-squares plane over a disc of radius r m (a footprint's
        mean slope, not one 2 m difference)."""
        if r <= 0:
            gx = (self.z(x + h, y) - self.z(x - h, y)) / (2 * h)
            gy = (self.z(x, y + h) - self.z(x, y - h)) / (2 * h)
            return gx, gy
        g = np.arange(-r, r + 1e-6, 0.25)
        dx, dy = np.meshgrid(g, g)
        m = dx ** 2 + dy ** 2 <= r * r
        dx, dy = dx[m], dy[m]
        z = self.T.height((x + dx) * 100.0, (y + dy) * 100.0)
        A = np.stack([np.ones_like(dx), dx, dy], axis=1)
        c = np.linalg.lstsq(A, z, rcond=None)[0]
        return float(c[1]), float(c[2])

    def contour_yaw(self, u, v, r=0.0):
        """World yaw of the contour at (u, v), the direction closest to travel (r: plane fit radius, m)."""
        x, y = self.world(u, v)
        gx, gy = self.grad(x, y, r=r)
        c = np.array([-gy, gx])
        if c @ self.f < 0:
            c = -c
        return math.degrees(math.atan2(c[1], c[0]))

    def fall_yaw(self, u, v):
        x, y = self.world(u, v)
        gx, gy = self.grad(x, y)
        return math.degrees(math.atan2(-gy, -gx))

    def slope_deg(self, x, y):
        gx, gy = self.grad(x, y)
        return math.degrees(math.atan(math.hypot(gx, gy)))

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


# ---------------------------------------------------------------------------- the composition

SETTLE = {   # SETDRESS_V2.md section 3 contact classes -> the place_setdress settle config
    'rigid': dict(mode='trace', max_tilt_deg=0, rand_tilt_deg=0, z_rule='min'),
    'lie': dict(mode='trace', max_tilt_deg=25, rand_tilt_deg=8, z_rule='mean'),
    'rest': dict(mode='physics', max_tilt_deg=15, rand_tilt_deg=3, z_rule='max'),
    'ism_stone': dict(mode='trace', max_tilt_deg=35, rand_tilt_deg=25, z_rule='mean'),
    'ism_shrub': dict(mode='trace', max_tilt_deg=15, rand_tilt_deg=0, z_rule='mean'),
}


class Site:
    def __init__(self, G):
        self.G = G
        self.items = []
        self.ground = []
        self.lanes = []
        self.rng = random.Random(8)

    def add(self, key, u, v, group, contact, scale=1.0, yaw=None, yaw_off=0.0, sink_cm=None, ism=False,
            block=None, pitch=0.0, roll=0.0, stack=False, attach=False, drop_cm=0, rand_tilt=None, role='',
            material_set=None, settle_kind=None):
        G = self.G
        path, cat, size = asset(key)
        x, y = G.world(u, v)
        if yaw is None:
            yaw = G.contour_yaw(u, v)
        yaw = (yaw + yaw_off) % 360.0
        cfg = dict(SETTLE[settle_kind or contact])
        if rand_tilt is not None:
            cfg['rand_tilt_deg'] = rand_tilt
        size_m = [round(s * scale / 100.0, 3) for s in size]
        if sink_cm is None:
            sink_cm = 6
        if attach:
            cfg = dict(mode='none', max_tilt_deg=0, rand_tilt_deg=0, z_rule='mean')
        settle = dict(mode=cfg['mode'], sink_cm=int(round(sink_cm)), max_tilt_deg=cfg['max_tilt_deg'],
                      rand_tilt_deg=cfg['rand_tilt_deg'], z_rule=cfg['z_rule'], drop_cm=int(drop_cm), z_offset_cm=0)
        it = dict(key=key, asset=path, kind='SM', cat=cat, u=u, v=v, x=x, y=y, yaw=round(yaw, 1), pitch=pitch, roll=roll,
                  scale=round(scale, 3), size_m=size_m, settle=settle, group=group, ism=ism, stack=stack, attach=attach,
                  contact=contact, block=block, role=role, material_set=material_set,
                  material=(EXTRA.get(key) or {}).get('material'))
        self.items.append(it)
        return it

    def patch(self, surface, u, v, yaw, length, width, strength, shape='ellipse', sort=0, role=''):
        self.ground.append(dict(surface=surface, u=u, v=v, yaw=yaw, length=length, width=width, strength=strength,
                                shape=shape, sort=sort, role=role))

    def path(self, pts, width, strength):
        self.lanes.append(dict(pts=pts, width=width))
        for (u0, v0), (u1, v1) in zip(pts[:-1], pts[1:]):
            L = math.hypot(u1 - u0, v1 - v0)
            yaw_local = math.degrees(math.atan2(v1 - v0, u1 - u0))
            self.patch('path', (u0 + u1) / 2, (v0 + v1) / 2, yaw_local, L + width, width, strength, 'capsule', 3,
                       'the trodden way from the road down to the bench')

    def on_lane(self, u, v, margin=0.4):
        for ln in self.lanes:
            for (u0, v0), (u1, v1) in zip(ln['pts'][:-1], ln['pts'][1:]):
                du, dv = u1 - u0, v1 - v0
                L2 = du * du + dv * dv
                t = max(0.0, min(1.0, ((u - u0) * du + (v - v0) * dv) / L2))
                if math.hypot(u0 + t * du - u, v0 + t * dv - v) < ln['width'] / 2 + margin:
                    return True
        return False


def slab_face(G, it, side=+1):
    """Points along the downhill (side +1) long face of a slab, site frame: (u, v, outward unit (du, dv))."""
    a = math.radians(it['yaw'] - G.road_yaw)       # yaw relative to the site frame's +u
    ax_u = (math.cos(a), -math.sin(a))              # the slab's long axis in (u, v): v is LEFT, world yaw turns right
    n = (math.sin(a), math.cos(a))                  # +v-ish normal (downhill: the left of the road falls away)
    hl, hw = it['size_m'][0] / 2, it['size_m'][1] / 2
    return ax_u, (n[0] * side, n[1] * side), hl, hw


def compose(G):
    S = Site(G)
    rng = S.rng

    # Everything is laid out in a LEDGE FRAME: origin J at the joint between the slabs, e along the lip (the
    # contour, a plane fit over 2 m), n outward and downhill (toward the valley).
    J = (0.05, 8.65)
    ey = G.contour_yaw(*J, r=2.0)
    re_ = math.radians(ey - G.road_yaw)
    e = (math.cos(re_), -math.sin(re_))
    n = (math.sin(re_), math.cos(re_))

    def L(a, b):
        return J[0] + e[0] * a + n[0] * b, J[1] + e[1] * a + n[1] * b

    # 1. the ledge: two slabs laid LEVEL along the lip (each on its own plane-fit contour: the lip curves, so the
    #    joint opens a little, as laid stones do), a hand's-width joint, the second stepped 0.25 m further out.
    #    Rigid + plumb + z 'min': the uphill edge sits at grade (a shelf you step onto from the bench), the
    #    downhill face stands ~0.6-0.7 m proud. One block, so the joint is never a clash.
    hla = CAT['FAB_TempleStones']['size_cm'][0] * 1.10 / 200.0
    hwa = CAT['FAB_TempleStones']['size_cm'][1] * 1.10 / 200.0
    hlb = CAT['FAB_TempleStones']['size_cm'][0] * 0.95 / 200.0
    pa = L(-(hla + 0.06), 0.0)
    A = S.add('FAB_TempleStones', pa[0], pa[1], 'ledge', 'rigid', scale=1.10, yaw=G.contour_yaw(*pa, r=1.1), sink_cm=3,
              block='ledge', role='FOCAL: the ledge, slab A (the seat the lantern stood on)', material_set='stone')
    pb = L(hlb + 0.06, 0.25)
    B = S.add('FAB_TempleStones', pb[0], pb[1], 'ledge', 'rigid', scale=0.95, yaw=G.contour_yaw(*pb, r=1.0), sink_cm=3,
              block='ledge', role='FOCAL: the ledge, slab B (stepped out 0.25 m)', material_set='stone')

    # 2. the bench: the trunk on the ground uphill of slab A, parallel to the lip, 0.3 m behind it, so a sitter's
    #    feet rest on the ledge ~0.4 m below the seat. 'lie': it follows the ground; almost no random tilt on a
    #    3.5 m log (a pitched log would float one end).
    r_log = CAT['PH_trunk']['size_cm'][1] * 1.15 / 200.0
    hl_log = CAT['PH_trunk']['size_cm'][0] * 1.15 / 200.0
    plog = L(-0.30, -(hwa + 0.30 + r_log))
    S.add('PH_trunk', plog[0], plog[1], 'bench', 'lie', scale=1.15, yaw=ey + 1.5, sink_cm=6, rand_tilt=1,
          role='the bench (dead_tree_trunk_2k), behind the ledge', material_set='wood')

    # 3. the Keeper's lantern: set down on slab A near the joint, knocked over, cold. Glass on the same pivot.
    pl = L(-0.42, 0.12)
    S.add('PH_lantern', pl[0], pl[1], 'lantern', 'rest', scale=1.0, yaw=ey - 62.0, roll=90.0, stack=True,
          drop_cm=20, sink_cm=1, role='the fallen, unlit lantern (never lit; no light, no emissive)')
    S.add('PH_lantern_glass', pl[0], pl[1], 'lantern', 'rest', scale=1.0, yaw=ey - 62.0, roll=90.0,
          attach=True, role='its glass, sharing the lantern pivot')

    # 4. the rock band: natural rock, partly buried (38 % of its height), holding the ledge's two ends and stepping
    #    down the slope to the down-road side: the diagonal that leads the eye from the ledge into the valley.
    rocks = [
        ('LF_Rock_05', L(-(2 * hla + 0.06 + 1.25), 0.30), 0.72, ey + 70.0, 'holds the down-road end of the ledge'),
        ('LF_Rock_03', L(2 * hlb + 0.06 + 0.80, 0.60), 0.62, ey + 8.0, 'holds the up-road end of the ledge'),
        ('LF_Rock_02', L(0.25, hwa + 1.45), 0.48, ey - 15.0, 'the keel: a low rock under the joint'),
        ('LF_Rock_04', L(-4.6, 3.3), 0.70, ey + 25.0, 'the lower anchor, down-road and downhill'),
    ]
    for key, (u, v), sc, yw, role in rocks:
        h = CAT[key]['size_cm'][2] * sc
        S.add(key, u, v, 'rocks', 'lie', scale=sc, yaw=yw, sink_cm=0.38 * h, block='rockband', rand_tilt=6,
              role='rock band: ' + role, material_set='stone')
    S.frame = dict(J=J, e=e, n=n, yaw=ey, L=L, log_end=L(-0.30 - hl_log, -(hwa + 0.30 + r_log)), r_log=r_log, hwa=hwa)

    # 5. chinking: small stones wedged at the downhill face of each slab (the hand-levelling), 35-40 % buried.
    for sl in (A, B):
        ax_u, n, hl, hw = slab_face(G, sl)
        for f in (-0.75, -0.3, 0.2, 0.7):
            off = hw + rng.uniform(0.10, 0.28)
            u = sl['u'] + ax_u[0] * f * hl + n[0] * off
            v = sl['v'] + ax_u[1] * f * hl + n[1] * off
            key = rng.choice(['LF_Rock_08', 'LF_Rock_08', 'AB_Cobble_04'])
            sc = rng.uniform(0.65, 0.95) if key == 'LF_Rock_08' else rng.uniform(0.9, 1.25)
            h = CAT[key]['size_cm'][2] * sc
            S.add(key, u, v, 'stones', 'lie', scale=sc, yaw=rng.uniform(0, 360), sink_cm=0.38 * h, ism=True,
                  block='base', settle_kind='ism_stone', role='chinking under the downhill face', material_set='stone')

    # 6. the spill: a thin fan of stones down the fall line below the ledge (exponential fall-off, +-35 deg).
    for sl, n_st in ((A, 7), (B, 6)):
        ax_u, n, hl, hw = slab_face(G, sl)
        fall = math.radians(G.fall_yaw(sl['u'], sl['v']) - G.road_yaw)
        fu, fv = math.cos(fall), -math.sin(fall)
        for _ in range(n_st):
            a = rng.uniform(-35, 35)
            r = hw + 0.35 + min(3.4, rng.expovariate(1 / 1.1))
            du, dv = fu * math.cos(math.radians(a)) - fv * math.sin(math.radians(a)), fu * math.sin(math.radians(a)) + fv * math.cos(math.radians(a))
            s0 = rng.uniform(-0.7, 0.7) * hl
            u = sl['u'] + ax_u[0] * s0 + du * r
            v = sl['v'] + ax_u[1] * s0 + dv * r
            key = rng.choice(['LF_Rock_07', 'LF_Rock_07', 'LF_Rock_08', 'AB_Cobble_04'])
            sc = rng.uniform(0.5, 0.8) if key == 'LF_Rock_08' else rng.uniform(0.8, 1.3)
            h = CAT[key]['size_cm'][2] * sc
            S.add(key, u, v, 'stones', 'lie', scale=sc, yaw=rng.uniform(0, 360), sink_cm=0.35 * h, ism=True, block='fan',
                  settle_kind='ism_stone', role='the spill down the fall line', material_set='stone')
    # scree at the downhill foot of the two lower rocks
    Lf = S.frame['L']
    hla2 = 2 * CAT['FAB_TempleStones']['size_cm'][0] * 1.10 / 200.0
    for (ra, rb, k) in ((-(hla2 + 1.31), 0.30, 3), (-4.6, 3.3, 4)):
        for _ in range(k):
            u, v = Lf(ra + rng.uniform(-0.7, 0.7), rb + rng.uniform(0.95, 1.9))
            key = rng.choice(['LF_Rock_07', 'LF_Rock_08'])
            sc = rng.uniform(0.6, 1.2)
            h = CAT[key]['size_cm'][2] * sc
            S.add(key, u, v, 'stones', 'lie', scale=sc, yaw=rng.uniform(0, 360), sink_cm=0.35 * h, ism=True, block='fan',
                  settle_kind='ism_stone', role='scree under the rock band', material_set='stone')

    # 7. the ground: a trodden patch where people sat, the path down from the road, rubble dust under the spill.
    le = S.frame['log_end']
    S.path([(le[0] - 3.4, 4.7), (le[0] - 2.1, 5.75), (le[0] - 0.55, le[1] - 0.15)], width=0.9, strength=0.85)
    cy = S.frame['yaw'] - G.road_yaw
    pe = Lf(-0.35, -0.35)
    S.patch('packed_earth', pe[0], pe[1], -cy, 6.4, 3.2, 0.72, sort=0, role='where people sat: bench and ledge')
    pd = Lf(0.1, 1.9)
    S.patch('rubble_dust', pd[0], pd[1], -cy, 4.8, 2.4, 0.65, sort=1, role='under the spill below the ledge')
    pr = Lf(-4.5, 4.4)
    S.patch('rubble_dust', pr[0], pr[1], -cy + 20, 3.0, 2.0, 0.55, sort=1, role='under the scree of the lower rock')

    # 8. creep: dead shrubs in the lee of the log and the rocks, and one from the slab joint. Never on the path.
    hwa = S.frame['hwa']
    creep = [('FAB_Shrub_C', (-2.25, -1.45), 1.0, 'at the down-road end of the log'),
             ('FAB_Shrub_D', (0.12, -0.40), 0.85, 'from the slab joint'),
             ('FAB_Shrub_G', (1.75, -1.25), 0.8, 'at the up-road end of the log'),
             ('FAB_Shrub_C', (2.95, -0.35), 0.9, 'uphill of the up-road rock'),
             ('FAB_Shrub_G', (-3.35, -0.80), 0.9, 'uphill of the down-road rock'),
             ('FAB_Shrub_D', (0.10, hwa + 2.35), 1.2, 'below the keel rock'),
             ('FAB_Shrub_C', (-4.3, 2.2), 1.1, 'uphill of the lower anchor'),
             ('FAB_Shrub_D', (3.3, 1.5), 0.9, 'at the foot of the up-road rock')]
    for key, (a, b), sc, where in creep:
        u, v = Lf(a, b)
        if S.on_lane(u, v):
            continue
        S.add(key, u, v, 'creep', 'lie', scale=sc, yaw=rng.uniform(0, 360), sink_cm=5, ism=True, block='creep',
              settle_kind='ism_shrub', role='dead shrub ' + where)

    # 9. dry tufts: the grass the landscape grows around the set (LGT_Saskarta_DryGrass, same meshes, same MIs), in
    #    the places a slope gathers soil and water against stone: along the uphill face of slab B past the log end,
    #    one thin tuft from the mouth of the slab joint, across the old spill below the ledge, at the rocks' feet,
    #    and behind the log where nobody walks. Clumps of 1-3, never on the path or where the sitter's feet go (the
    #    gap between the log and slab A). So the set's own plants are the ground's plants, not a new species.
    hwb = B['size_m'][1] / 2
    bu = 0.25 - hwb                                          # slab B's uphill face, ledge frame b
    tufts = [('MV_Grass_V2_01', (1.52, bu - 0.20), 'against slab B, past the log end'),
             ('MV_Grass_V1_02', (1.98, bu - 0.26), 'against slab B, by the up-road rock'),
             ('MV_Grass_V5_05', (0.00, 0.34), 'from the mouth of the slab joint'),
             ('MV_Grass_V1_02', (-1.35, 1.50), 'in the old spill below slab A'),
             ('MV_Grass_V2_01', (-0.85, 1.80), 'in the old spill below slab A'),
             ('MV_Grass_V5_05', (1.05, 1.45), 'in the old spill below slab B'),
             ('MV_Grass_V2_03', (0.70, -1.52), 'behind the log (nobody walks there)'),
             ('MV_Grass_V5_05', (1.12, -1.45), 'behind the log, with the olive tuft'),
             ('MV_Grass_V2_01', (2.30, 1.40), 'at the downhill foot of the up-road rock'),
             ('MV_Grass_V1_02', (2.78, 1.62), 'at the downhill foot of the up-road rock'),
             ('MV_Grass_V2_03', (-5.20, 2.45), 'uphill of the lower anchor rock'),
             ('MV_Grass_V5_05', (-3.85, 2.60), 'uphill of the lower anchor rock'),
             ('MV_Grass_V2_01', (-3.60, -0.45), 'uphill of the down-road rock')]
    for key, (a, b), where in tufts:
        u, v = Lf(a, b)
        if S.on_lane(u, v):
            continue
        S.add(key, u, v, 'creep', 'lie', scale=rng.uniform(0.8, 1.2), yaw=rng.uniform(0, 360), sink_cm=4, ism=True,
              block='creep', settle_kind='ism_shrub', role='dry tuft ' + where)
    # the save judge (check2) measures only the solo actors: an ISM stone inside another, or a shrub through the log or
    # a rock, is never caught there (verifier, 2026-09-28). Push every ISM piece out (the minimum translation) and
    # leave out any that finds no room within 0.6 m or lands on the path.
    S.moved = declash(G, S)
    S.dropped = [it for it in S.items if it['ism'] and (S.moved[id(it)] > 0.6 or S.on_lane(it['u'], it['v'], 0.2) or
                                                        any(a is it or b is it for _, _, a, b in clash_pairs(G, S)))]
    S.items = [it for it in S.items if all(it is not d for d in S.dropped)]
    return S


# plan overlap allowed (bounds boxes): a stone / a plant into a solid, stone x stone, a plant x a stone, plant x plant.
# Plants are open (blades, twigs): a tuft leans over a pebble, and two clumps interleave, so their bounds may overlap
# more; pushing them 4 cm apart would space them out evenly, which is the V1 "toys on a plain" look.
ISM_ALLOW = dict(stone=0.05, shrub=0.10, ism=0.04, plant_stone=0.10, plants=0.20)


def pair_allow(a, b):
    pa, pb = a['cat'] == 'shrub', b['cat'] == 'shrub'
    return ISM_ALLOW['plants'] if pa and pb else (ISM_ALLOW['plant_stone'] if pa or pb else ISM_ALLOW['ism'])


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


def clash_pairs(G, S):
    """Plan overlaps beyond ISM_ALLOW: ISM stones / shrubs into the solids (slabs, log, rocks) and into each other."""
    solids = [it for it in S.items if not it['ism'] and not it['attach'] and not it['stack']]
    isms = [it for it in S.items if it['ism']]
    out = []
    for it in isms:
        allow = ISM_ALLOW['shrub' if it['cat'] == 'shrub' else 'stone']
        for sd in solids:
            d = plan_mtv(obb_uv(G, it), obb_uv(G, sd))[0]
            if d > allow + 1e-6:
                out.append((d, allow, it, sd))
    for i in range(len(isms)):
        for j in range(i + 1, len(isms)):
            d = plan_mtv(obb_uv(G, isms[i]), obb_uv(G, isms[j]))[0]
            allow = pair_allow(isms[i], isms[j])
            if d > allow + 1e-6:
                out.append((d, allow, isms[i], isms[j]))
    return out


def declash(G, S, rounds=60):
    """Deterministic: each round moves every clashing ISM piece once, out of its deepest overlap. {id: moved m}."""
    start = {id(it): (it['u'], it['v']) for it in S.items if it['ism']}
    for _ in range(rounds):
        pairs = clash_pairs(G, S)
        if not pairs:
            break
        done = set()
        for d, allow, a, b in sorted(pairs, key=lambda p: -p[0]):
            # the plant yields: grass and shrubs grow round a stone, a stone never moves for them (if the plant has
            # moved this round already, the pair waits for the next round)
            cands = [x for x in (a, b) if x['ism']]
            plants = [x for x in cands if x['cat'] == 'shrub']
            if plants and len(plants) < len(cands):
                cands = plants
            free = [x for x in cands if id(x) not in done]
            mover = free[0] if free else None
            if mover is None:
                continue
            fixed = b if mover is a else a
            dd, ax = plan_mtv(obb_uv(G, mover), obb_uv(G, fixed))
            if ax is None:
                continue
            mover['u'] += ax[0] * (dd - allow + 0.03)
            mover['v'] += ax[1] * (dd - allow + 0.03)
            mover['x'], mover['y'] = G.world(mover['u'], mover['v'])
            done.add(id(mover))
    return {id(it): math.hypot(it['u'] - start[id(it)][0], it['v'] - start[id(it)][1]) for it in S.items if it['ism']}


# ---------------------------------------------------------------------------- outputs

def obb_uv(G, it):
    """Footprint corners (u, v) of the scaled bounds box."""
    a = math.radians(it['yaw'] - G.road_yaw)
    ax = (math.cos(a), -math.sin(a))
    ay = (math.sin(a), math.cos(a))
    hx, hy = it['size_m'][0] / 2, it['size_m'][1] / 2
    if abs(it['roll']) > 45:               # lying on its side: local Z is horizontal
        hy = it['size_m'][2] / 2
    return [(it['u'] + sx * hx * ax[0] + sy * hy * ay[0], it['v'] + sx * hx * ax[1] + sy * hy * ay[1])
            for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]


def predicted_rigid(G, it):
    """The settle for a plumb piece with z 'min' (place_setdress.settle_pose): bottom = lowest ground sample - sink."""
    cs = obb_uv(G, it)
    pts = cs + [((cs[0][0] + cs[2][0]) / 2, (cs[0][1] + cs[2][1]) / 2)] + \
        [((cs[i][0] + cs[(i + 1) % 4][0]) / 2, (cs[i][1] + cs[(i + 1) % 4][1]) / 2) for i in range(4)]
    gz = [G.zuv(u, v) for u, v in pts]
    bottom = min(gz) - it['settle']['sink_cm'] / 100.0
    top = bottom + it['size_m'][2]
    return dict(bottom=bottom, top=top, ground_min=min(gz), ground_max=max(gz),
                proud_uphill=top - max(gz), proud_downhill=top - min(gz), buried_uphill=max(gz) - bottom)


def box_points(G, it):
    """8 world corners (m) of the predicted pose (rigid: level; others: on the ground at the centre, level)."""
    cs = obb_uv(G, it)
    if it['contact'] == 'rigid':
        p = predicted_rigid(G, it)
        z0, z1 = p['bottom'], p['top']
    else:
        z0 = G.zuv(it['u'], it['v']) - it['settle']['sink_cm'] / 100.0
        h = it['size_m'][1] if abs(it['roll']) > 45 else it['size_m'][2]
        z1 = z0 + h
        if it['stack']:                    # the lantern lies on slab A's top
            z0 = predicted_rigid(G, [q for q in ITEMS_CACHE if q['role'].startswith('FOCAL: the ledge, slab A')][0])['top']
            z1 = z0 + h
    out = []
    for u, v in cs:
        x, y = G.world(u, v)
        out += [(x, y, z0), (x, y, z1)]
    return out


ITEMS_CACHE = []


def to_record(G, S, i, it):
    x, y = it['x'], it['y']
    gz = G.z(x, y)
    rid = '%s_v8_%03d' % (SID, i)
    rec = dict(id=rid, key=it['key'], asset=it['asset'], kind='SM', cat=it['cat'],
               x_cm=round(x * 100, 1), y_cm=round(y * 100, 1), ground_z_cm=round(gz * 100, 1),
               yaw=it['yaw'], pitch=float(it['pitch']), roll=float(it['roll']), scale=it['scale'],
               scale_range=[it['scale'], it['scale']], settle=it['settle'], group=it['group'],
               folder='Set/%s/%s' % (SID, it['group']), data_layer='DL_SetDress', ism=it['ism'], stack=it['stack'],
               attach=it['attach'], run_id=None, collision=not it['ism'] or it['group'] == 'rocks',
               foliage_exclude=it['group'] in ('ledge', 'bench', 'rocks', 'lantern'),
               draw_distance_cm=draw_distance_cm(max(it['size_m'])), cast_shadow=True, size_m=it['size_m'],
               slope_deg=round(G.slope_deg(x, y), 1), road_clear_m=None, contact=it['contact'],
               site_uv=[round(it['u'], 2), round(it['v'], 2)], role=it['role'], story_set=SET)
    if it['block']:
        rec['block'] = it['block']
    if it['material_set']:
        rec['material_set'] = it['material_set']
    if it.get('material'):
        rec['material'] = it['material']     # the ISM host's slot 0 (place_setdress.py ISM_BODY MAT): the tuft's MI
    # footprint clearance from the road centreline, the V1 road-core rule. The RoadSpline has zero tangents at its
    # points, so the polyline IS the road (build_cinematics.spline_points, checked to 5 cm).
    cs = [G.world(u, v) for u, v in obb_uv(G, it)]
    rec['road_clear_m'] = round(min(G.road_dist(*c) for c in cs), 2)
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
        out.append(dict(id='%s_v8_g%02d' % (SID, i), surface=g['surface'], shape=g['shape'],
                        x_cm=round(x * 100, 1), y_cm=round(y * 100, 1), z_cm=round((max(zs) + min(zs)) / 2 * 100, 1),
                        yaw=round((G.road_yaw - g['yaw']) % 360.0, 1), length_m=round(g['length'], 2),
                        width_m=round(g['width'], 2), depth_m=round(max(3.0, relief + 1.2), 1),
                        strength=g['strength'], sort=g['sort'], role=g['role']))
    return out


def views(G):
    """V2 capture views (place_setdress.py capture --v2) plus the story frames. cam/look in world cm."""
    fx, fy = G.world(-0.1, 8.6)
    focus = [round(fx * 100, 1), round(fy * 100, 1), round((G.z(fx, fy) + 0.6) * 100, 1)]
    out = []

    def cam(name, x, y, z, look=None, note=''):
        out.append(dict(name=name, cam_cm=[round(x * 100, 1), round(y * 100, 1), round(z * 100, 1)],
                        look_cm=look or focus, note=note))
    for name, s in (('carrier_a', 4420.0), ('carrier_b', 4440.0), ('carrier_c', 4456.0)):
        x, y, z = G.road_eye(s, 2.5)
        cam(name, x, y, z, note='approach, carrier eye (capture_look EYE 2.5 m) at road %d m' % s)
    x, y, z = G.road_eye(4475.0, EYE_M[0])
    cam('glance_hold', x, y, z, [round(c, 1) for c in GLANCE_TARGET_CM],
        note='G14 hold at road 4,475, eye 1.22 m, looking at ValleyEast (capture at 60 deg: the ledge is below it)')
    cam('glance_low', x, y, z, focus, note='same eye, looking at the ledge (what the 90 deg hold frame holds low)')
    for name, (u, v, h) in (('orbit_a', (-9.0, 13.0, 3.0)), ('orbit_b', (8.0, 14.0, 3.5)), ('orbit_c', (0.5, 17.5, 1.8))):
        x, y = G.world(u, v)
        cam(name, x, y, G.z(x, y) + h)
    x, y = G.world(-2.0, 11.4)
    lx, ly = G.world(-1.5, 8.95)
    cam('contact', x, y, G.z(x, y) + 1.1, [round(lx * 100, 1), round(ly * 100, 1), round((G.z(lx, ly) + 0.2) * 100, 1)],
        note='the downhill face of slab A: chinking, sink, spill')
    x, y = G.world(-18.0, 30.0)
    cam('high34', x, y, G.z(x, y) + 22.0)
    x, y = G.world(-60.0, 290.0)
    cam('far300', x, y, G.z(x, y) + 30.0, note='from the valley side, 300 m east')
    return out


# ---------------------------------------------------------------------------- story-frame checks

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
        out.append(((d @ Rt) / z / th, (d @ U) / z / tv))
    return out


def look_at(eye, tgt):
    dx, dy, dz = tgt[0] - eye[0], tgt[1] - eye[1], tgt[2] - eye[2]
    return math.degrees(math.atan2(dy, dx)), math.degrees(math.atan2(dz, math.hypot(dx, dy)))


def smooth(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def glance_pose(G, t, eye_m):
    """The G14 camera at t s after the trigger: carrier at 5 m/s, yaw/pitch eased from the road heading, held on the
    target, then left where the hold ended (the runner does not ease back; `release_s` is not a camera move)."""
    s = TRIGGER_M + CARRIER_MS * t
    eye = G.road_eye(s, eye_m)
    k, _ = G.R.locate(s)
    d = G.R.P[k + 1, :2] - G.R.P[k, :2]
    y0 = math.degrees(math.atan2(d[1], d[0]))
    tg = tuple(c / 100.0 for c in GLANCE_TARGET_CM)
    yT, pT = look_at(eye, tg)
    e, h = GLANCE['ease_in_s'], GLANCE['hold_s']
    if t > e + h:
        # after the hold the runner only gives the look input back (SaskartaEventRunner::GlanceTick -> EndGlance):
        # nothing eases the view back, so the control rotation stays where the hold left it until the player moves it
        _, _, yH, pH, _ = glance_pose(G, e + h, eye_m)
        return s, eye, yH, pH, 1.0
    a = smooth(t / e) if t < e else 1.0
    dy = (yT - y0 + 540) % 360 - 180
    return s, eye, y0 + a * dy, a * pT, a


def frame_report(G, groups, eye_m=EYE_M[0]):
    """Where the ledge sits in the G14 frame over the 5 s glance: screen box of the focal group and the target."""
    rows = []
    tg = tuple(c / 100.0 for c in GLANCE_TARGET_CM)
    for t in np.arange(0.0, 5.01, 0.5):
        s, eye, yw, pt, a = glance_pose(G, float(t), eye_m)
        scr = [q for q in project(eye, yw, pt, groups['focal']) if q is not None]
        inside = [q for q in scr if abs(q[0]) <= 1 and abs(q[1]) <= 1]
        tq = project(eye, yw, pt, [tg])[0]
        box = None
        if inside:
            xs, ys = [q[0] for q in inside], [q[1] for q in inside]
            box = fmt_box((min(xs), max(xs), min(ys), max(ys)))
        rows.append(dict(t=round(float(t), 1), road_m=round(s, 1), yaw=round(yw, 1), pitch=round(pt, 1), ease=round(a, 2),
                         focal_in_frame=round(len(inside) / max(1, len(scr)), 2), focal_box=box,
                         target=None if tq is None else fmt_box(tq)))
    return rows


def occludes_target(G, S, eye_m):
    """Over the G14 hold: the smallest screen gap (in frame-halves) between the ValleyEast target and any dressing
    point that stands within +-0.2 of it horizontally (the boot point must stay clear), and the item that comes
    nearest. A point below the target has a positive gap."""
    tg = tuple(c / 100.0 for c in GLANCE_TARGET_CM)
    worst, who = 9.0, ''
    for t in np.arange(GLANCE['ease_in_s'], GLANCE['ease_in_s'] + GLANCE['hold_s'] + 0.01, 0.25):
        s, eye, yw, pt, a = glance_pose(G, float(t), eye_m)
        tq = project(eye, yw, pt, [tg])[0]
        for it in S.items:
            if it['attach']:
                continue
            for q in project(eye, yw, pt, box_points(G, it)):
                if q is not None and abs(q[0] - tq[0]) <= 0.2 and abs(q[1]) <= 1 and tq[1] - q[1] < worst:
                    worst, who = tq[1] - q[1], '%s at %.1f s' % (it['key'], t)
    return worst, who


def fmt_box(b):
    return None if b is None else tuple(round(float(v), 2) for v in b)


def approach_report(G, groups):
    rows = []
    for s in (4400.0, 4420.0, 4440.0, 4450.0, 4456.0):
        eye = G.road_eye(s, EYE_M[0])
        k, _ = G.R.locate(s)
        d = G.R.P[k + 1, :2] - G.R.P[k, :2]
        yw = math.degrees(math.atan2(d[1], d[0]))
        scr = [q for q in project(eye, yw, 0.0, groups['focal']) if q is not None]
        inside = [q for q in scr if abs(q[0]) <= 1 and abs(q[1]) <= 1]
        cx, cy, cz = groups['centre']
        dist = math.dist(eye[:2], (cx, cy))
        box = None
        if inside:
            xs, ys = [q[0] for q in inside], [q[1] for q in inside]
            box = fmt_box((min(xs), max(xs), min(ys), max(ys)))
        tan, _ = G.T.horizon_tan(np.array([eye[0] * 100]), np.array([eye[1] * 100]), np.array([eye[2]]),
                                 np.array([cx * 100]), np.array([cy * 100]), skip_far_m=3.0)
        visible = (cz + 0.6 - eye[2]) / dist > float(tan[0])
        rows.append(dict(road_m=s, dist_m=round(dist, 1), focal_in_frame=round(len(inside) / max(1, len(scr)), 2),
                         focal_box=box, elev_deg=round(math.degrees(math.atan2(cz + 0.6 - eye[2], dist)), 1),
                         terrain_los=bool(visible)))
    return rows


def wide24_report(G, groups):
    eye = tuple(c / 100.0 for c in WIDE24_CAM_CM)
    yw, pt = look_at(eye, tuple(c / 100.0 for c in WIDE24_LOOK_CM))
    scr = [q for q in project(eye, yw, pt, groups['all'], hfov=WIDE24_HFOV) if q is not None]
    inside = [q for q in scr if abs(q[0]) <= 1 and abs(q[1]) <= 1]
    cx, cy, cz = groups['centre']
    q = project(eye, yw, pt, [(cx, cy, cz)], hfov=WIDE24_HFOV)[0]
    dist = math.dist(eye, (cx, cy, cz))
    px_m = 2 * dist * math.tan(math.radians(WIDE24_HFOV) / 2) / 1920.0
    return dict(dist_m=round(dist, 0), centre_screen=None if q is None else fmt_box(q),
                in_frame=round(len(inside) / max(1, len(scr)), 2), cm_per_px_1920=round(px_m * 100, 1))


# ---------------------------------------------------------------------------- the plot

def plot(G, S, recs, grecs, glance_rows, groups):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon, Ellipse
    fig = plt.figure(figsize=(19, 11.5))
    ax = fig.add_axes([0.03, 0.05, 0.50, 0.88])
    # contours (site frame) from the heightmap
    us = np.arange(-16, 16.01, 0.25)
    vs = np.arange(-8, 22.01, 0.25)
    UU, VV = np.meshgrid(us, vs)
    X = G.o[0] + UU * G.f[0] + VV * G.l[0]
    Y = G.o[1] + UU * G.f[1] + VV * G.l[1]
    Z = G.T.height(X * 100, Y * 100)
    cs = ax.contour(UU, VV, Z, levels=np.arange(np.floor(Z.min()), Z.max(), 0.5), colors='#b9ad9a', linewidths=0.6)
    ax.clabel(cs, cs.levels[::4], fmt='%.0f m', fontsize=7, colors='#8a7f6c')
    # road ribbon and centreline
    ax.fill_between([-16, 16], -4.5, 4.5, color='#cfc6b8', alpha=0.55, lw=0)
    ax.axhline(0, color='#8a8174', lw=1, ls='--')
    ax.text(-15.6, -3.9, 'road (9 m ribbon), travel ->', fontsize=9, color='#5d564c')
    ax.axhline(CLEAR_M, color='#c55', lw=0.8, ls=':')
    ax.text(10.0, CLEAR_M - 0.55, 'road-core clearance 5 m', fontsize=8, color='#c55')
    col = dict(packed_earth='#b08a5a', path='#6b4d33', rubble_dust='#c8b79a', gravel='#9b9384')
    for g in S.ground:
        if g['shape'] == 'capsule':
            a = math.radians(-g['yaw'])
            L = g['length'] - g['width']
            p0 = (g['u'] - L / 2 * math.cos(a), g['v'] + L / 2 * math.sin(a))
            p1 = (g['u'] + L / 2 * math.cos(a), g['v'] - L / 2 * math.sin(a))
            ax.plot([p0[0], p1[0]], [p0[1], p1[1]], color=col[g['surface']], lw=g['width'] * 26, alpha=0.35,
                    solid_capstyle='round')
        else:
            ax.add_patch(Ellipse((g['u'], g['v']), g['length'], g['width'], angle=g['yaw'], color=col[g['surface']],
                                 alpha=0.35 * g['strength'], lw=0))
    style = {'ledge': ('#3b3b3b', '#8d8a84'), 'bench': ('#5a3d22', '#9c7a52'), 'rocks': ('#4f4a44', '#b3aca1'),
             'lantern': ('#a57a1c', '#e0b64a')}
    for it in S.items:
        if it['ism']:
            c = ('#c9a24a' if it['key'] in TUFTS else '#6d8f4e') if it['group'] == 'creep' else '#7d6e5f'
            ms = (5 if it['key'] in TUFTS else 7) if it['group'] == 'creep' else max(2.5, it['size_m'][0] * 9)
            ax.plot(it['u'], it['v'], 'o' if it['group'] == 'creep' else 's', ms=ms, color=c, alpha=0.85, mec='none')
            continue
        if it['attach']:
            continue
        ec, fc = style[it['group']]
        ax.add_patch(Polygon(obb_uv(G, it), closed=True, ec=ec, fc=fc, lw=1.4, alpha=0.9))
    for sid, key, x, y in STANDINS:
        u, v = G.local(x / 100, y / 100)
        ax.plot(u, v, 'x', color='#c33', ms=8, mew=1.6)
    ax.text(G.local(STANDINS[0][2] / 100, STANDINS[0][3] / 100)[0] + 0.3,
            G.local(STANDINS[0][2] / 100, STANDINS[0][3] / 100)[1] - 0.9, 'V1 stand-ins (x, removed)',
            fontsize=8, color='#c33')
    # annotations
    A = [i for i in S.items if i['role'].startswith('FOCAL: the ledge, slab A')][0]
    pA = predicted_rigid(G, A)
    ax.annotate('FOCAL: two slabs laid level\n(top %.2f m; downhill face %.2f m proud,\nuphill edge %.2f m proud)'
                % (pA['top'], pA['proud_downhill'], pA['proud_uphill']),
                xy=(A['u'], A['v'] + 0.3), xytext=(-15.5, 17.5), fontsize=9,
                arrowprops=dict(arrowstyle='->', color='#333'))
    ax.annotate('log bench (3.5 m)', xy=(1.2, 7.55), xytext=(5.5, 5.8), fontsize=9, arrowprops=dict(arrowstyle='->'))
    ax.annotate('fallen lantern', xy=(A['u'] + 0.62, A['v'] + 0.12), xytext=(-9.0, 15.0), fontsize=9, color='#8a6212',
                arrowprops=dict(arrowstyle='->', color='#8a6212'))
    ax.annotate('trodden path\nfrom the road', xy=(-4.0, 5.9), xytext=(-12.5, 7.0), fontsize=9,
                arrowprops=dict(arrowstyle='->', color='#6b4d33'))
    fall = math.radians(G.fall_yaw(0, 9.5) - G.road_yaw)
    ax.arrow(8.0, 13.0, 2.2 * math.cos(fall), -2.2 * math.sin(fall), head_width=0.35, color='#a55')
    ax.text(8.4, 12.2, 'fall line', fontsize=8, color='#a55')
    # glance: carrier positions and the look rays (hold start / end), and the approach sightline
    for t, c in ((2.0, '#1f5fa8'), (4.0, '#6a3fa0')):
        s, eye, yw, pt, a = glance_pose(G, t, EYE_M[0])
        eu, ev = G.local(eye[0], eye[1])
        rel = math.radians(yw - G.road_yaw)
        for off in (-45, 0, 45):
            r2 = rel + math.radians(off)
            ax.plot([eu, eu + 30 * math.cos(r2)], [ev, ev - 30 * math.sin(r2)], color=c, lw=1.6 if off == 0 else 0.8,
                    ls='-' if off == 0 else '--', alpha=0.8)
        ax.plot(eu, ev, 'o', color=c, ms=7)
        ax.text(eu + 0.3, ev - 1.2, 'G14 %s\n%.0f m' % ('hold start' if t == 2.0 else 'hold end', s), fontsize=8, color=c)
    eu, ev = G.local(*G.road_eye(TRIGGER_M, 1.0)[:2])
    ax.plot(eu, ev, 'k^', ms=8)
    ax.text(eu - 3.5, ev - 1.6, 'B14 trigger 4,460', fontsize=8)
    ax.set_xlim(-16, 16)
    ax.set_ylim(-8, 22)
    ax.set_aspect('equal')
    ax.set_xlabel('u: metres along the road from 4,476 m (travel ->)')
    ax.set_ylabel('v: metres LEFT of the road (the valley, east)')
    ax.set_title('V8 the ledge (S24_Ledge), plan: 0.5 m contours from Current_u16; ISM stones = squares, '
                 'dead shrubs = green, dry tufts = straw')

    # simulated frames
    def frame_ax(rect, title):
        a2 = fig.add_axes(rect)
        a2.set_xlim(-1, 1)
        a2.set_ylim(-1, 1)
        a2.set_aspect(9 / 16)
        a2.set_xticks([])
        a2.set_yticks([])
        a2.set_title(title, fontsize=10)
        a2.set_facecolor('#dfe7ee')
        return a2

    def draw_frame(a2, eye, yw, pt, hfov=HFOV):
        # skyline of the far terrain: per screen column, the highest terrain elevation angle out to 3.5 km
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
        # near ground mesh (site frame lines)
        for uu in np.arange(-14, 14.1, 1.0):
            pts = [(*G.world(uu, vv), G.zuv(uu, vv)) for vv in np.arange(4.5, 22.1, 0.5)]
            q = [p for p in project(eye, yw, pt, pts, hfov) if p is not None]
            if q:
                a2.plot([p[0] for p in q], [p[1] for p in q], color='#9c8c74', lw=0.4)
        for vv in np.arange(5.0, 22.1, 1.0):
            pts = [(*G.world(uu, vv), G.zuv(uu, vv)) for uu in np.arange(-14, 14.1, 0.5)]
            q = [p for p in project(eye, yw, pt, pts, hfov) if p is not None]
            if q:
                a2.plot([p[0] for p in q], [p[1] for p in q], color='#9c8c74', lw=0.4)
        edges = [(0, 2), (2, 4), (4, 6), (6, 0), (1, 3), (3, 5), (5, 7), (7, 1), (0, 1), (2, 3), (4, 5), (6, 7)]
        for it in S.items:
            if it['attach'] or (it['ism'] and it['group'] != 'creep' and max(it['size_m']) < 0.3):
                continue
            bp = box_points(G, it)
            q = project(eye, yw, pt, bp, hfov)
            ec = {'ledge': '#222', 'bench': '#5a3d22', 'rocks': '#5c554d', 'lantern': '#c08a10', 'creep': '#56753c',
                  'stones': '#7d6e5f'}[it['group']]
            for i0, i1 in edges:
                if q[i0] is not None and q[i1] is not None:
                    a2.plot([q[i0][0], q[i1][0]], [q[i0][1], q[i1][1]], color=ec, lw=1.2 if it['group'] in ('ledge', 'bench', 'lantern') else 0.6)
        tq = project(eye, yw, pt, [tuple(c / 100.0 for c in GLANCE_TARGET_CM)], hfov)[0]
        if tq is not None and abs(tq[0]) <= 1 and abs(tq[1]) <= 1:
            a2.plot(tq[0], tq[1], '+', color='#c22', ms=14, mew=2)
            a2.text(tq[0] + 0.03, tq[1] + 0.05, 'ValleyEast (boot point, 3 km)', fontsize=8, color='#c22')
        for g in (-1 / 3, 1 / 3):
            a2.axvline(g, color='w', lw=0.5, alpha=0.6)
            a2.axhline(g, color='w', lw=0.5, alpha=0.6)
    t_mid = GLANCE['ease_in_s'] + 1.0
    s, eye, yw, pt, _ = glance_pose(G, t_mid, EYE_M[0])
    a2 = frame_ax([0.56, 0.52, 0.42, 0.42], 'G14_LOOK_BACK, t=%.1f s (road %.1f m, mid-hold): 90 deg POV, eye 1.22 m' % (t_mid, s))
    draw_frame(a2, eye, yw, pt)
    s = 4444.0
    eye = G.road_eye(s, EYE_M[0])
    k, _ = G.R.locate(s)
    d = G.R.P[k + 1, :2] - G.R.P[k, :2]
    a3 = frame_ax([0.56, 0.04, 0.42, 0.42], 'Approach, road %.0f m: forward 90 deg POV, eye 1.22 m (the ledge left of centre)' % s)
    draw_frame(a3, eye, math.degrees(math.atan2(d[1], d[0])), 0.0)
    fig.savefig(OUT_PNG, dpi=80)
    return OUT_PNG


# ---------------------------------------------------------------------------- main

def build():
    G = Ground()
    S = compose(G)
    ITEMS_CACHE[:] = S.items
    recs = [to_record(G, S, i, it) for i, it in enumerate(S.items)]
    grecs = ground_records(G, S)
    focal = [p for it in S.items if it['group'] in ('ledge', 'bench', 'lantern') and not it['attach'] for p in box_points(G, it)]
    allp = [p for it in S.items if not it['attach'] for p in box_points(G, it)]
    A = [i for i in S.items if i['role'].startswith('FOCAL: the ledge, slab A')][0]
    cx, cy = G.world(-0.1, 8.6)
    groups = dict(focal=focal, all=allp, centre=(cx, cy, predicted_rigid(G, A)['top']))
    return G, S, recs, grecs, groups


def checks(G, S, recs, grecs, groups):
    out = []
    bad = []
    for r in recs:
        if r['road_clear_m'] < CLEAR_M:
            bad.append('ROAD %s %s %.2f m' % (r['id'], r['key'], r['road_clear_m']))
    # footprint overlap between the solids that are not one block (the V2 CLASH idea, in plan)
    solids = [it for it in S.items if not it['ism'] and not it['attach'] and not it['stack']]

    def sat(a, b):
        for poly in (a, b):
            for i in range(4):
                e = (poly[(i + 1) % 4][0] - poly[i][0], poly[(i + 1) % 4][1] - poly[i][1])
                n = (-e[1], e[0])
                pa = [p[0] * n[0] + p[1] * n[1] for p in a]
                pb = [p[0] * n[0] + p[1] * n[1] for p in b]
                if max(pa) <= min(pb) or max(pb) <= min(pa):
                    return False
        return True
    for i in range(len(solids)):
        for j in range(i + 1, len(solids)):
            a, b = solids[i], solids[j]
            if a['block'] and a['block'] == b['block'] and a['group'] == 'ledge':
                continue
            if sat(obb_uv(G, a), obb_uv(G, b)):
                out.append('plan overlap (bounds boxes; natural rocks are irregular): %s x %s' % (a['role'][:40], b['role'][:40]))
    for it in S.items:
        if it['group'] in ('creep', 'stones') and S.on_lane(it['u'], it['v'], 0.2):
            bad.append('ON PATH %s at (%.1f, %.1f)' % (it['key'], it['u'], it['v']))
    left = clash_pairs(G, S)
    for d, allow, a, b in left:
        bad.append('ISM OVERLAP %s into %s by %.2f m (allowed %.2f)' % (a['key'], b['key'], d, allow))
    mv = sorted(S.moved[id(it)] for it in S.items if it['ism'])
    out.append('ISM declash: %d of %d ISM pieces moved (max %.2f m), %d left out (%s); %d overlaps left beyond %s'
               % (sum(1 for m in mv if m > 0.005), len(mv), max(mv) if mv else 0.0, len(S.dropped),
                  ', '.join('%s (%s)' % (d['key'], d['role'][:30]) for d in S.dropped) or 'none', len(left), ISM_ALLOW))
    for it in S.items:
        if it['contact'] == 'rigid':
            p = predicted_rigid(G, it)
            out.append('%s: top %.2f m, ground %.2f..%.2f, downhill face %.2f m proud, uphill %.2f m proud, buried %.2f m uphill'
                       % (it['role'][:34], p['top'], p['ground_min'], p['ground_max'], p['proud_downhill'], p['proud_uphill'],
                          p['buried_uphill']))
            if p['proud_uphill'] < 0.05:
                bad.append('SLAB BURIED %s: the uphill edge is below the ground' % it['role'])
    for eye_m in EYE_M:
        w, who = occludes_target(G, S, eye_m)
        out.append('G14 hold, eye %.2f m: under the boot point (+-0.2 wide), the nearest dressing is %.2f frame-halves below it (%s)'
                   % (eye_m, w, who))
        if w < 0.1:
            bad.append('G14: dressing covers the ValleyEast target (eye %.2f)' % eye_m)
    out.append(strict_judge(G, recs, bad))
    # the tufts must stay the landscape's own pairs (mesh -> MI): compare with the V2 lane's table when it has one
    ref = setdress_catalog.__dict__.get('DRY_TUFT_MATERIAL')
    for k, (_, _, mi) in TUFTS.items():
        if ref is not None and ref.get(k) != mi:
            bad.append('TUFT MI %s: %s here, %s in setdress_catalog.DRY_TUFT_MATERIAL' % (k, mi, ref.get(k)))
    for r in recs:
        if r['key'] in TUFTS and r.get('material') != TUFTS[r['key']][2]:
            bad.append('TUFT MI missing on %s' % r['id'])
    return out, bad


def strict_judge(G, recs, bad):
    """The V2 composer's strict offline check (setdress_contact.offline_reports + judge, as setdress_v2.offline_check
    runs it): what check2 will measure, estimated from the placements and the heightmap. Violations fail the run."""
    import setdress_contact as sc
    fn = sc.__dict__.get('offline_reports')
    if fn is None:
        return 'strict offline judge: skipped (this setdress_contact has no offline_reports yet)'
    reps, items = fn([r for r in recs if not r.get('optional')], lambda x_cm, y_cm: G.z(x_cm / 100.0, y_cm / 100.0) * 100.0)
    v, w = sc.judge(reps, items, [])
    for i, code, why in v:
        bad.append('STRICT %s %s: %s' % (code, i, why))
    return ('strict offline judge (setdress_contact.offline_reports + judge, the composer\'s rule): %d solo actors, '
            '%d violations, %d waived' % (len(reps), len(v), len(w)))


def write(G, S, recs, grecs, glance_rows, appr, wide, notes, bad):
    cx, cy = G.world(0.0, 9.0)
    cz = G.z(cx, cy)
    vw = views(G)
    r = 18.0
    pts = [(cx * 100, cy * 100)] + [(v['cam_cm'][0], v['cam_cm'][1]) for v in vw if v['name'] not in ('far300', 'high34')]
    box = [min(p[0] for p in pts) - (r + 30) * 100, min(p[1] for p in pts) - (r + 30) * 100,
           max(p[0] for p in pts) + (r + 30) * 100, max(p[1] for p in pts) + (r + 30) * 100]
    solo = [x for x in recs if not x['ism']]
    ism = [x for x in recs if x['ism']]
    site = dict(
        id=SID, story_set=SET, name='Sleb Zdaw, the Ledge (V8)', kind='rest seat', order=3, road_m=int(S0),
        side='left', lateral_m=-9.0, centre_cm=[round(cx * 100, 1), round(cy * 100, 1), round(cz * 100, 1)],
        road_yaw=round(G.road_yaw, 1), radius_m=r, zone='Z6 Summit',
        storm='above the cloud: clear, calm, gold light; bare wind-scoured rock; the fewest objects on the road',
        role='rest', story='B14 the look back (G14_LOOK_BACK over it); the Keeper stopped here once; then B15',
        decay=1, style='stone: a log bench behind two slabs laid level on the lip, held by a band of buried rock',
        layout='\n'.join([
            '  ==== road (4,466-4,488 m, climbing 14 %) ====   path leaves the road at 4,471',
            '     [log bench 3.5 m, along the contour]  shrubs in its lee',
            '  rock  [slab A x1.10][slab B x0.95, stepped out]  rock      <- the ledge, level, facing east',
            '        chinking stones at the downhill faces; the lantern fallen on slab A by the joint',
            '            keel rock          spill of stones down the fall line (rubble dust)',
            '   lower anchor rock + scree (down-road, downhill)            ... the valley, 3 km east ...']),
        notes='Story set V8 on the road site S24_Ledge. The V1 stand-ins (S24_Ledge_000..003) are removed by `clear`. '
              'The B14 trigger stays at 4,460; the set is centred 16 m up-road so the G14 hold frames it. '
              'Nothing religious, nothing modern; the lantern is never lit.',
        story_owned=['V8 the ledge (this file is the story set)'], verify_only=False, layer='road', poi=None,
        load_box_cm=[round(v) for v in box],
        counts=dict(placements=len(recs), actors=len(solo) + len({(x['group'], x['asset']) for x in ism}),
                    ism_instances=len(ism), physics=sum(1 for x in solo if x['settle']['mode'] == 'physics'),
                    batch01=0, decals=len(grecs)),
        views=[{k: v[k] for k in ('name', 'cam_cm', 'look_cm')} for v in vw],
        view_notes={v['name']: v['note'] for v in vw if v['note']},
        check_views=dict(cin24_wide=dict(cam_cm=list(WIDE24_CAM_CM), look_cm=list(WIDE24_LOOK_CM), hfov_deg=round(WIDE24_HFOV, 2),
                                          note='CIN_24 shot 3 (probe_ending.json wide24, PROVISIONAL): not a capture view '
                                               '(it would widen the load box by 1 km); judge it with build_cinematics.py')),
        placements=recs, ground=grecs, units=[], waivers=[],
        v2=dict(frame=dict(origin_road_m=S0, origin_cm=[round(G.o[0] * 100, 1), round(G.o[1] * 100, 1)],
                           u='along travel', v='left of travel'),
                lanes=S.lanes, glance=glance_rows, approach=appr, wide24=wide, checks=notes, violations=bad),
    )
    doc = dict(generated_by='Tools/World/story_sets/v8_ledge.py', method='docs/world/SETDRESS_V2.md',
               design='docs/world/story_sets/V8.md', level='/Game/level/Saskarta_WP',
               conventions=dict(xy='world cm; yaw = UE yaw deg', bounds='x_cm/y_cm is the mesh BOUNDS CENTRE',
                                ground='decal patches: DecalActor pitch -90, yaw, size (depth/2, width/2, length/2)',
                                contact='rigid | rest | lie | stack (SETDRESS_V2.md section 3)',
                                site_uv='u m along travel from road 4,476, v m left of travel'),
               rejected=[], checks=[], sites=[site])
    with open(OUT_JSON, 'w', encoding='utf8') as fh:
        json.dump(doc, fh, indent=1, ensure_ascii=False)
    return site


def run_editor(argv, materials=False):
    """Run a place_setdress.py step (or build_setdress_materials.py) with the V2 site file swapped for V8.json."""
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
    if step in ('place', 'replace') and not re.search(r'\bMAT\b', ps.ISM_BODY):
        tinted = [p['id'] for s in json.load(open(OUT_JSON, encoding='utf8'))['sites'] for p in s['placements']
                  if p.get('ism') and p.get('material')]
        if tinted:
            sys.exit('V8 gate: %d ISM pieces (the dry tufts) carry a `material`, but this place_setdress.py ISM_BODY '
                     'does not apply one (the V2 lane\'s ISM material override is not in it). Placing now would give '
                     'them the pack\'s own grass material. Wait for that change, then rerun.' % len(tinted))
    sys.argv = ['place_setdress.py', step] + ([] if step in ('list', 'probe') else [SID]) + rest
    ps.main()


def main():
    if len(sys.argv) > 1 and sys.argv[1] == 'editor':
        return run_editor(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == 'materials':
        return run_editor(sys.argv[2:], materials=True)
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--no-plot', action='store_true')
    args = ap.parse_args()
    G, S, recs, grecs, groups = build()
    glance_rows = frame_report(G, groups)
    appr = approach_report(G, groups)
    wide = wide24_report(G, groups)
    notes, bad = checks(G, S, recs, grecs, groups)
    site = write(G, S, recs, grecs, glance_rows, appr, wide, notes, bad)
    print('%s (%s): %d placements, %d actors, %d ISM instances, %d decals' % (
        SID, SET, site['counts']['placements'], site['counts']['actors'], site['counts']['ism_instances'], site['counts']['decals']))
    print('road clearance min %.2f m' % min(r['road_clear_m'] for r in recs))
    for n in notes:
        print(' ', n)
    print('G14 glance (eye 1.22 m): t, road m, yaw, pitch, focal share in frame, focal screen box (x0 x1 y0 y1), target')
    for r in glance_rows:
        print('  %4.1f %7.1f %6.1f %5.1f %4.2f %s %s' % (r['t'], r['road_m'], r['yaw'], r['pitch'], r['focal_in_frame'],
                                                    r['focal_box'], r['target']))
    print('approach (forward POV):')
    for r in appr:
        print('  ', r)
    print('CIN_24 shot 3 wide (provisional camera):', wide)
    if not args.no_plot:
        print('plot', plot(G, S, recs, grecs, glance_rows, groups))
    print('wrote', OUT_JSON)
    if bad:
        print('VIOLATIONS:')
        for b in bad:
            print('  ', b)
        sys.exit(1)


if __name__ == '__main__':
    main()
