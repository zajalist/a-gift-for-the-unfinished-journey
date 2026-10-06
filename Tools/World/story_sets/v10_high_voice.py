"""V10 the High Voice relay station (the hut, the mast foot and the guys): a story set, composed with the V2 method.

    python Tools/World/story_sets/v10_high_voice.py                 # write V10.json + the plot, print the checks
    python Tools/World/story_sets/v10_high_voice.py --no-plot       # data and checks only
    python Tools/World/story_sets/v10_high_voice.py editor <step> [place_setdress args]
          # runs Tools/World/place_setdress.py <step> V10_HighVoice --v2 against Tools/World/story_sets/V10.json
    python Tools/World/story_sets/v10_high_voice.py materials variants
          # runs Tools/World/build_setdress_materials.py variants V10_HighVoice against V10.json
    python Tools/World/story_sets/v10_high_voice.py mastcheck|doorcheck|level|lines|hooks|hooks-save [--dry-run] [--owner X]
    python Tools/World/story_sets/v10_high_voice.py --door-w W --door-h H [--plate-y Y]   # after doorcheck
          # this set's own editor steps (same Hayba runner, same 5 s / banned-word rules as place_setdress.py)

Story (docs/story/storyline.md section 2 and V10, story-events.json B23/B24, CINEMATICS.md CIN_23/CIN_24):
the road ends at the High Voice, a 40 m mast (the L2 beacon actor `HighVoice`, already in the level) beside a
small relay hut. The Keeper walks the last ~200 m, stops at road 4,990 for B23 (RADIO_B23_01, live), then
"Lay your hand on the mark.": the connection plate on the hut's road-facing wall, an open palm inside a ring.
CIN_24 snaps the Keeper to the plate's StandPoint, films the hand on the plate over the shoulder (50 mm), looks
straight up the mast from its foot (18 mm), and ends on the seated view at the mast foot, east over the valley
(24 mm, SeatPoint). The site is KEPT (decay 0): the one place on the road someone still tended.

The place: the road runs down its last 45 m (17 %) straight at the mast. The mast stands in a stone collar at
the road's end; three iron guys run from it to half-buried deadman blocks. The hut stands on the only flat
shelf, 9 m right of the road end, its front turned back up the road so the plate faces the walker; a brass
conduit runs from the collar to the plate. A path leaves the road 7 m before its end for the plate and the door.
Rocks close the view on the right (a rock face past the hut) and the left (a moss boulder on the valley verge).
The valley side east of the mast foot stays empty: that is the seated shot.

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
import build_road_profile as brp  # noqa: E402  (read-only: the heightmap and the road polyline)
import setdress_catalog  # noqa: E402  (read-only: asset paths and sizes)

OUT_JSON = os.path.join(HERE, 'V10.json')
OUT_PNG = os.path.join(ROOT, 'docs', 'world', 'story_sets', 'V10.png')
MEASURED_JSON = os.path.join(HERE, 'V10_measured.json')   # written only by --door-w/--door-h/--plate-y (after doorcheck)
SID = 'V10_HighVoice'
SET = 'V10'
CAT = setdress_catalog.load()

# ---------------------------------------------------------------------------- story constants
O_CM = (298079.6, 483050.0)          # spline point 0 = the mast base (L2 actor `HighVoice`, not spatially loaded)
P1_CM = (297579.6, 478550.0)         # spline point 1: the last road segment runs P1 -> O (straight)
YAW0 = math.degrees(math.atan2(O_CM[1] - P1_CM[1], O_CM[0] - P1_CM[0]))   # 83.66: travel heading at the end
PILLAR_HALF_CM = (25.0, 50.0)        # Tile_10MPillar 50 x 100 cm, the actor at rotation 0 (world-aligned)
MAST_SINK_CM = 50.0                  # L2 placed the actor 50 cm below the traced ground
GUY_ATTACH_M = 28.0                  # guys meet the mast 28 m up (70 % of 40 m)
HALF_HEIGHT_CM = 92.0                # BP_Saskarta_Traveller capsule half height (gen_ending_specs.py)
TETHER_M = 9.0                       # the traveller's CheckTether limit (900 cm)
BLOCK_M = 8.0                        # the V9 blocking volumes, 8 m either side of the road (4,790 m to the end)
B23_ROAD_M = 4990.0                  # B23 RoadPassHuman (UE 19.5 m before the end)
BOOM_M = 3.5                         # the traveller's third-person boom (CINEMATICS.md section 6)
SEAT_OFF_CM = (150.1, -9.2)          # probe_ending.json seat - mast_base (x, y): at the collar's east face
SEAT_EYE_CM = 100.0
SEAT_YAW, SEAT_PITCH = -3.5, -4.0    # toward the boot point (east)
C2_OFF_CM = (140.0, 90.0, 60.0)      # build_cinematics.py plan_cin24 TransmitCam: base + (140, 90, 60)
STAND_BACK_CM, STAND_RIGHT_CM, OTS_UP_CM = 95.0, 38.0, 168.0   # plan_cin24 shot 1 (over the right shoulder)
PLATE_HALF_M = 0.225                 # the connection plate: 45 x 45 cm, 6 cm thick (SM_ChamferCube scaled)
PLATE_UP_M = 1.30                    # plate centre above the door grade (S26 shell contract plate_z)
STAND_OUT_M = 0.6                    # StandPoint 60 cm in front of the plate (task-ENDING-brief.md step 6c)

# ---------------------------------------------------------------------------- the hut
# Site frame: u metres along the last road heading (YAW0) from the mast base, v metres to the RIGHT of travel.
# Left of travel (-v) is east: the valley, the boot point and the seated view.
# Hut frame = the S26 shell contract's (Tools/World/story_sets/s26_high_voice_hut.py SHELL): x from the front (door)
# wall to the back wall, y to the right of x, origin at the footprint centre; AB 300x400 pieces on a 3.0 m square
# of centre lines; the front is AB_Side_Arch_small on the x = -1.5 line (outer face -1.93, inner -1.07).
HUT_C = (1.5, 8.5)                   # the shelf right of the road end (searched: 0.24 m relief over the footprint)
HUT_PSI = 205.0                      # the front's outward normal (site deg): back up the road, 25 deg to the valley
HALF = 1.5                           # wall centre lines at x, y = +-1.5
SIDE_SCALE = 1.08                    # the side walls reach the outer corners (3.24 m; faces +-1.37 / +-1.63)
WALL_SINK_CM = 15
ARCH_OUT = -1.93                     # the arch piece's outer face (0.86 m thick on the x = -1.5 line)
PLATE_Y = -1.05                      # the plate on the door's LEFT jamb (the mast side); `--plate-y` after `doorcheck`
WINDOW_X, WINDOW_SILL = 0.35, 1.0    # the window on the left (valley) wall; here a closed shutter
# The door opening of AB_Side_Arch_small is NOT known offline (the piece is 3.03 x 0.86 x 3.26 m). These are the
# assumed values; the read-only `doorcheck` step measures it with complex traces, and `--door-w/--door-h` record
# the measured values in V10.json (S26 reads them). The plate needs >= 5 cm of jamb between it and the opening.
DOOR_W, DOOR_H = 1.10, 2.05
DOOR_MEASURED = False
# the plinth: one flagstone slab (B01_floor01) under the whole hut. The walls stand on it (contact `bear`), its top
# is the hut floor (S26's props stand on it) and the door sill. The `level` step Z-scales it so its top clears the
# highest ground under it by PLINTH_CLEAR_CM, so no terrain comes up through the floor and the door sill sits at
# the outside grade (before: one base at min - 15 cm put the floor ~0.4 m over the wall base and cut the door).
PLINTH_SINK_CM, PLINTH_CLEAR_CM, PLINTH_BACK_M = 3.0, 3.0, 0.08
# the collar: two courses of four blocks (a pinwheel, then a reversed pinwheel on it, joints broken). One course on
# the 0.89 m of relief under it left the uphill blocks under the terrain (verifier, 2026-09-28).
COLLAR_SINK_CM, COLLAR_SCALE = 25.0, 1.15
COLLAR_EXPOSE_M = 0.25               # the cap must stand >= 25 cm clear of the ground on its uphill (approach) side
CINE_FILMBACK_MM = 23.76             # CineCamera 16:9 digital film (CINEMATICS.md): for framing checks
ISM_ALLOW = dict(stone=0.05, shrub=0.10, ism=0.04)   # plan overlap allowed: ISM stone / shrub into a solid, ISM x ISM
EXT = {  # keys not in setdress_catalog (checked on disk; sizes from setdress_assets.json)
    'AB_Window_B': ('/Game/AshesOfBazaar/Meshes/SM_Window_B', 'prop', [16.0, 92.0, 121.0]),
}
EA_PIPE = '/Game/EasyAtmos/EpicContentDemo/DemoRoom/Meshes/Pipe'           # 1000 x 15 x 15 cm, long axis X
BRASS = '/Game/Pallbearer/PolyHaven/Lantern_01/Lantern_01_2k/Materials/Lantern_01_brass'
IRON = '/Game/MedievalVillage/Materials/MI_Metal'
PLATE_MESH = '/Game/LevelPrototyping/Meshes/SM_ChamferCube'
MARK_MESH = '/Game/LevelPrototyping/Interactable/JumpPad/Assets/Meshes/SM_CircularBand'

SURF_COL = dict(packed_earth='#b08a5a', path='#6b4d33', gravel='#9b9384', rubble_dust='#c8b79a', soot='#222222', dry_mud='#d9c9a8')


def rot(a_deg, x, y):
    c, s = math.cos(math.radians(a_deg)), math.sin(math.radians(a_deg))
    return x * c - y * s, x * s + y * c


def asset(key):
    if key in EXT:
        p, cat, size = EXT[key]
        return dict(path=p, cat=cat, size_cm=size, kind='SM', exists=os.path.exists(os.path.join(ROOT, 'Content', p[6:] + '.uasset')))
    return CAT[key]


def draw_distance_cm(max_dim_m):
    """The V1 table (never 0 = infinite: the PCG cull-distance memory note)."""
    for lim, d in ((0.6, 4000.0), (1.5, 6000.0), (4.0, 25000.0), (10.0, 80000.0)):
        if max_dim_m < lim:
            return d
    return 200000.0


class Ground:
    """The Gaea heightmap and the road polyline in the V10 site frame."""

    def __init__(self):
        self.T = brp.Terrain(brp.HEIGHTMAP)
        self.R = brp.Road(brp.SPLINE_POINTS_CM)
        self.P = self.R.P[:, :2] / 100.0
        a = math.radians(YAW0)
        self.f = np.array([math.cos(a), math.sin(a)])
        self.r = np.array([-math.sin(a), math.cos(a)])      # right of travel in UE's left-handed top view
        self.o = np.array(O_CM) / 100.0

    def world(self, u, v):
        q = self.o + self.f * u + self.r * v
        return float(q[0]), float(q[1])

    def site(self, x, y):
        d = np.array([x, y]) - self.o
        return float(d @ self.f), float(d @ self.r)

    def g(self, u, v):
        x, y = self.world(u, v)
        return float(self.T.height(x * 100.0, y * 100.0))

    def gw(self, x, y):
        return float(self.T.height(x * 100.0, y * 100.0))

    def road_dist(self, pts_uv):
        pts = [self.world(u, v) for u, v in pts_uv]
        a, b = self.P[:-1][None], self.P[1:][None]
        p = np.asarray(pts, float)[:, None, :]
        ab = b - a
        t = np.clip(np.sum((p - a) * ab, axis=2) / np.sum(ab * ab, axis=2), 0, 1)
        return float(np.min(np.linalg.norm(p - (a + ab * t[..., None]), axis=2)))

    def road_uv(self, road_m, lateral=0.0):
        x, y = (self.R.xy(road_m) / 100.0).tolist()
        u, v = self.site(x, y)
        return u, v + lateral


class Site:
    def __init__(self, G):
        self.G = G
        self.items = []
        self.ground = []
        self.rng = random.Random(1010)

    def add(self, key, u, v, yaw, group, contact, scale=1.0, block=None, sink=None, ism=False, mat=None, pitch=0.0,
            roll=0.0, note=None, **kw):
        it = dict(key=key, u=float(u), v=float(v), yaw=float(yaw), group=group, contact=contact, scale=float(scale),
                  block=block, sink=sink, ism=ism, material_set=mat, pitch=float(pitch), roll=float(roll), note=note)
        it.update(kw)
        self.items.append(it)
        return it

    def patch(self, surface, u, v, yaw, length, width, strength=1.0, shape='ellipse', order=0):
        self.ground.append(dict(surface=surface, u=u, v=v, yaw=yaw, length=length, width=width, strength=strength,
                                shape=shape, order=order))

    def path(self, pts, width, surface='path', strength=0.9, order=3):
        for (u0, v0), (u1, v1) in zip(pts[:-1], pts[1:]):
            L = math.hypot(u1 - u0, v1 - v0)
            self.patch(surface, (u0 + u1) / 2, (v0 + v1) / 2, math.degrees(math.atan2(v1 - v0, u1 - u0)), L + width,
                       width, strength, 'capsule', order)


# ---------------------------------------------------------------------------- hut geometry helpers

def hut_axes():
    """Unit vectors in the site frame: nf out of the front (door) face, X into the hut (front -> back), Y its right."""
    p = math.radians(HUT_PSI)
    nf = (math.cos(p), math.sin(p))
    X = (-nf[0], -nf[1])
    Y = (-X[1], X[0])                        # right of X in UE's left-handed top view
    return nf, X, Y


def hut_xy(x, y):
    """Hut frame (the S26 shell contract) -> site (u, v)."""
    _, X, Y = hut_axes()
    return HUT_C[0] + X[0] * x + Y[0] * y, HUT_C[1] + X[1] * x + Y[1] * y


def hut_ang(deg):
    """A direction given in the hut frame (0 = +X) -> site degrees."""
    return HUT_PSI - 180.0 + deg


def plate_uv(out_m=0.0):
    """The plate centre on the left jamb's outer face (+0.03 m, the plate's half thickness), pushed out_m."""
    return hut_xy(ARCH_OUT - 0.03 - out_m, PLATE_Y)


def grade_uv():
    """Three points just outside the door: the door grade (the S26 floor sits at it) is their highest ground."""
    return [hut_xy(ARCH_OUT - 0.3, y) for y in (-0.45, 0.0, 0.45)]


def mast_world_offsets_to_uv(G, dx_cm, dy_cm):
    x, y = O_CM[0] / 100.0 + dx_cm / 100.0, O_CM[1] / 100.0 + dy_cm / 100.0
    return G.site(x, y)


def collar_rect(scale=COLLAR_SCALE, course=1):
    """Pinwheel of four cut blocks round the pillar (world axes): centres (dx, dy) m and world yaw. Course 2 is the
    reversed pinwheel: the same square hole, every block spanning a joint of course 1 (both its ends carried)."""
    s = asset('B01_brick01')['size_cm']
    L, W = s[0] / 100.0 * scale, s[1] / 100.0 * scale
    if course == 2:
        return [((-W / 2, -L / 2), 0.0), ((L / 2, -W / 2), 90.0), ((W / 2, L / 2), 180.0), ((-L / 2, W / 2), 270.0)], L, W
    return [((W / 2, -L / 2), 0.0), ((L / 2, W / 2), 90.0), ((-W / 2, L / 2), 180.0), ((-L / 2, -W / 2), 270.0)], L, W


def plinth_dims():
    """The plinth under the hut (hut frame): x from the arch's outer face (flush) to the back wall + PLINTH_BACK_M,
    one uniform scale of B01_floor01 (310 x 307 cm), centred on y = 0."""
    t = asset('AB_300x400_Mid')['size_cm'][0] / 100.0
    fl = asset('B01_floor01')['size_cm']
    x0, x1 = ARCH_OUT, HALF + t / 2 + PLINTH_BACK_M
    sc = round((x1 - x0) / (fl[0] / 100.0), 3)
    return dict(x0=x0, x1=x1, xc=(x0 + x1) / 2, scale=sc, half_y=fl[1] / 200.0 * sc, h=fl[2] / 100.0 * sc)


# ---------------------------------------------------------------------------- composition

def compose(G):
    S = Site(G)
    rng = S.rng
    t = asset('AB_300x400_Mid')['size_cm'][0] / 100.0
    side_out = HALF + SIDE_SCALE * t / 2

    # 1. the mast foot: a stone collar of cut sandstone blocks round the pillar, two courses. Course 1 (the footing)
    #    is a pinwheel levelled as one block (one base: the lowest ground - 25 cm, so it is dug in on the uphill side);
    #    course 2 (the cap) is the reversed pinwheel laid on it by the `level` step, joints broken, so the collar top
    #    stands clear of the slope all round and the seated Keeper has a real stone back behind him.
    blocks, L, W = collar_rect()
    course1 = []
    for (dx, dy), wyaw in blocks:
        u, v = mast_world_offsets_to_uv(G, dx * 100, dy * 100)
        course1.append(S.add('B01_brick01', u, v, wyaw - YAW0, 'mastfoot', 'rigid', scale=COLLAR_SCALE, block='mastfoot',
                             sink=COLLAR_SINK_CM, mat='stone', course=1,
                             note='collar block, course 1 (the footing): the pillar stands in the %.2f m square hole' % (L - W)))
    course2 = []
    for (dx, dy), wyaw in collar_rect(course=2)[0]:
        u, v = mast_world_offsets_to_uv(G, dx * 100, dy * 100)
        course2.append(S.add('B01_brick01', u, v, wyaw - YAW0, 'mastfoot', 'bear', scale=COLLAR_SCALE, block='mastfoot',
                             mat='stone', bears=course1, course=2,
                             note='collar block, course 2 (the cap): the reversed pinwheel, each block across a joint of course 1'))
    # 2. the guys: three deadman blocks, half buried across the pull (uneven spacing keeps the seated frame clear)
    anchors = []
    for i, (theta, rad) in enumerate(((-10.0, 16.0), (110.0, 15.0), (-145.0, 16.0))):
        u, v = rad * math.cos(math.radians(theta)), rad * math.sin(math.radians(theta))
        a = S.add('B01_brick01', u, v, theta + 90.0, 'guys', 'rigid', block='anchor%d' % i, sink=30, mat='stone',
                  note='guy deadman %d: the cable runs to the mast 28 m up' % i)
        anchors.append(a)
        for k in range(3):   # a few stones heaved up round the block
            aa = rng.uniform(0, 360)
            d = rng.uniform(0.9, 1.4)
            S.add(rng.choice(['AB_Cobble_02', 'AB_Cobble_04', 'AB_Cobble_06', 'LF_Rock_08']), u + d * math.cos(math.radians(aa)),
                  v + d * math.sin(math.radians(aa)), rng.uniform(0, 360), 'base_ism', None, scale=rng.uniform(0.8, 1.2),
                  block='base', ism=True)
        S.patch('packed_earth', u, v, theta + 90, 2.6, 1.8, 0.55, 'ellipse', 0)

    # 3. the hut: one room, AB stone, intact (kept); the arched door faces back up the road, the plate on its left jamb.
    #    It stands on a flagstone plinth (the hut floor and the door sill), laid first and levelled so its top clears
    #    the ground everywhere under it; the walls bear on the plinth.
    ax_x, ax_y = hut_ang(0.0), hut_ang(90.0)          # site angles of the hut's X (front -> back) and Y axes
    pd = plinth_dims()
    p = hut_xy(pd['xc'], 0.0)
    plinth = S.add('B01_floor01', p[0], p[1], ax_x, 'hut_floor', 'rigid', scale=pd['scale'], block='plinth',
                   sink=PLINTH_SINK_CM, mat='stone',
                   note='plinth: the hut floor and the door sill (flush with the arch face, %.2f m past the back wall, '
                        '%.2f m past the sides); `level` Z-scales it to clear the ground' % (PLINTH_BACK_M, pd['half_y'] - side_out))
    walls = {}
    p = hut_xy(-HALF, 0.0)
    walls['front'] = S.add('AB_Side_Arch_small', p[0], p[1], ax_y, 'hut', 'bear', block='hut', mat='stone', bears=[plinth],
                           note='front: the arched door (its top sets the wall height); the plate is on its left jamb')
    p = hut_xy(HALF, 0.0)
    walls['back'] = S.add('AB_300x400_Mid', p[0], p[1], ax_y - 90.0 + 180.0, 'hut', 'bear', block='hut', mat='stone',
                          bears=[plinth], note='back wall (downhill): the S26 desk stands against it, seen through the door')
    for nm, y in (('left', -HALF), ('right', HALF)):
        p = hut_xy(0.0, y)
        walls[nm] = S.add('AB_300x400_Mid', p[0], p[1], ax_x - 90.0 + (0.0 if y < 0 else 180.0), 'hut', 'bear',
                          scale=SIDE_SCALE, block='hut', mat='stone', bears=[plinth],
                          note='%s wall%s' % (nm, ' (the valley side: the shuttered window and the bench)' if y < 0 else ''))
    # roof: one flagstone slab laid on the arch and the back wall (its local X spans front -> back)
    p = hut_xy(0.0, 0.0)
    roof = S.add('B01_floor01', p[0], p[1], ax_x, 'hut_roof', 'bear', scale=1.12, block='hut', mat='stone',
                 bears=[walls['front'], walls['back']], note='roof slab: rests on the arch top and the back wall')
    # the valley window, closed: a shutter on the left wall's outer face (look at it in the capture: verdict check)
    p = hut_xy(WINDOW_X, -side_out - 0.08)
    shutter = S.add('AB_Window_B', p[0], p[1], ax_y, 'hut', 'stack', block='hut', mat='wood', verdict='check',
                    note='the valley window, shuttered: fixed to the left wall face, sill %.1f m over the door grade' % WINDOW_SILL)

    # 4. kept details (few: the interior is S26's). All stand on the ground, clear of the plinth's edge.
    bw = asset('B01_brick01')['size_cm'][1] / 100.0
    p = hut_xy(WINDOW_X, -pd['half_y'] - 0.04 - bw / 2)
    bench = S.add('B01_brick01', p[0], p[1], ax_x, 'hut_yard', 'rigid', block='bench', sink=20, mat='stone',
                  note='stone bench under the shuttered valley window, against the plinth edge: it looks at the mast and the valley')
    jr = asset('B01_tank01')['size_cm'][0] / 200.0
    p = hut_xy(pd['x1'] + 0.04 + jr, -HALF + 0.35)
    S.add('B01_tank01', p[0], p[1], rng.uniform(0, 360), 'hut_yard', 'rest', mat='stone',
          note='rain jar at the back corner (valley side), its rim under the drip line of the roof slab (the eave '
               'overhangs the back wall by %.2f m)' % (asset('B01_floor01')['size_cm'][0] / 200.0 * 1.12 - (HALF + t / 2)))
    p = hut_xy(pd['x1'] + 0.35, -0.30)
    S.add('MV_bucket_01', p[0], p[1], rng.uniform(0, 360), 'hut_yard', 'rest', mat='wood',
          note='the bucket by the rain jar')

    # 5. rocks: the bedrock the shelf is cut from, and the rocks that frame the approach view
    for key, x, y, yaw, sink, note in (
            ('PH_rock_face', -0.2, HALF + 2.35, 65.0, 80, 'rock face past the hut: closes the approach view on the right'),
            ('LF_Rock_04', 3.5, 2.2, 10.0, 55, 'outcrop behind the hut'),):
        p = hut_xy(x, y)
        S.add(key, p[0], p[1], hut_ang(yaw), 'rocks', 'lie', sink=sink, mat='stone', note=note)
    S.add('PH_moss_rock_11', -6.0, -7.2, 35.0, 'rocks', 'lie', sink=45, mat='stone',
          note='boulder on the valley verge before the end: closes the approach view on the left')
    a1 = anchors[1]
    out = (math.cos(math.radians(110.0)), math.sin(math.radians(110.0)))
    S.add('LF_Rock_05', a1['u'] + out[0] * 2.1, a1['v'] + out[1] * 2.1, 140.0, 'rocks', 'lie', sink=45, mat='stone',
          note='the right guy anchor is set against a rock, on its far side')
    p = hut_xy(HALF + 0.9, -side_out - 0.9)
    S.add('LF_Rock_08', p[0], p[1], 20.0, 'rocks', 'lie', sink=10, mat='stone')

    # 6. base stones (ISM): along the plinth's downhill edges (back and valley side) and round the collar
    for x, y in ((pd['x1'] + 0.22, 0.45), (pd['x1'] + 0.25, 1.5), (1.5, -pd['half_y'] - 0.2), (pd['x1'] + 0.15, -pd['half_y'] - 0.1),
                 (pd['x1'] + 0.2, pd['half_y'] + 0.15), (-0.4, pd['half_y'] + 0.22)):
        p = hut_xy(x + rng.uniform(-0.15, 0.15), y + rng.uniform(-0.1, 0.1))
        S.add(rng.choice(['AB_Cobble_01', 'AB_Cobble_03', 'AB_Cobble_05', 'LF_Rock_07']), p[0], p[1], rng.uniform(0, 360),
              'base_ism', None, scale=rng.uniform(0.8, 1.3), block='base', ism=True)
    for ang in (125, 160, 205, 250):   # round the collar, never on its east (seated) side, the road or the conduit
        u, v = 1.75 * math.cos(math.radians(ang)), 1.75 * math.sin(math.radians(ang))
        S.add(rng.choice(['AB_Cobble_02', 'AB_Cobble_07', 'LF_Rock_07']), u, v, rng.uniform(0, 360), 'base_ism', None,
              scale=rng.uniform(0.8, 1.2), block='base', ism=True)

    # 7. creep: dead shrubs in the lee of the hut and the rocks (Z6: bare, wind-scoured; few)
    for x, y in ((pd['x1'] + 0.6, 1.1), (1.0, pd['half_y'] + 0.55), (2.6, 3.4), (-2.45, 2.0),
                 (-3.3, 1.2)):   # off the plinth, clear of the rain jar, the bucket, the rocks and the path to the door
        p = hut_xy(x + rng.uniform(-0.15, 0.15), y + rng.uniform(-0.15, 0.15))
        S.add(rng.choice(['FAB_Shrub_A', 'FAB_Shrub_C', 'FAB_Shrub_E', 'FAB_Shrub_G']), p[0], p[1], rng.uniform(0, 360),
              'creep_ism', None, scale=rng.uniform(0.8, 1.2), block='creep', ism=True)
    for an in anchors:
        S.add('FAB_Shrub_B', an['u'] - 0.9, an['v'] + 0.6, rng.uniform(0, 360), 'creep_ism', None, scale=0.9,
              block='creep', ism=True)

    # 8. ground: the tended yard, the path, the gravel ring and the conduit strip, dust in the lee
    S.patch('packed_earth', -1.8, 4.4, 20.0, 11.0, 7.5, 0.7, 'ellipse', 0)                     # the yard at the road end
    c = hut_xy(-0.3, 0.0)
    S.patch('packed_earth', c[0], c[1], ax_x, 6.4, 5.4, 0.6, 'ellipse', 0)                      # round the hut
    S.patch('gravel', 0.0, 0.0, 0.0, 4.4, 4.4, 0.8, 'ellipse', 2)                               # the collar's drainage ring
    pu, pv = plate_uv(0.0)
    S.path([(0.2, 1.3), (pu - 0.05, pv - 0.35)], 0.55, 'gravel', 0.8, 2)                         # the conduit trench
    su, sv = plate_uv(STAND_OUT_M)
    door = hut_xy(ARCH_OUT - 0.5, 0.0)
    S.path([(-7.5, 3.2), (-4.2, 4.8), (su - 0.2, sv - 0.25), door], 1.1, 'path', 0.9, 3)         # road -> plate -> door
    S.path([door, hut_xy(-0.6, 0.0)], 0.9, 'path', 0.7, 3)                                       # worn over the sill
    S.path([hut_xy(ARCH_OUT - 0.4, -HALF - 0.2), hut_xy(WINDOW_X - 0.9, -side_out - 0.75)], 0.9, 'path', 0.6, 3)  # to the bench
    back = hut_xy(HALF + 1.6, 0.3)
    S.patch('rubble_dust', back[0], back[1], ax_y, 5.0, 2.2, 0.35, 'ellipse', 1)                 # dust in the lee

    hooks = dict(walls=walls, roof=roof, shutter=shutter, anchors=anchors, bench=bench, plinth=plinth,
                 course1=course1, course2=course2)
    S.moved = declash(S)
    # an ISM piece that found no room within 0.6 m of where it was composed is left out, never forced
    S.dropped = [it for it in S.items if it['ism'] and (S.moved[id(it)] > 0.6 or
                                                        any(a is it or b is it for _, _, a, b in clash_pairs(S)))]
    if S.dropped:
        S.items = [it for it in S.items if all(it is not d for d in S.dropped)]
        S.moved = {k: m for k, m in S.moved.items() if any(id(it) == k for it in S.items)}
    return S, hooks


def path_clear(S, u, v):
    """Distance (m) from (u, v) to the nearest worn-path capsule's edge (negative = on it)."""
    best = 1e9
    for g in S.ground:
        if g['shape'] != 'capsule' or g['surface'] != 'path':
            continue
        a = math.radians(g['yaw'])
        L = (g['length'] - g['width']) / 2
        u0, v0 = g['u'] - math.cos(a) * L, g['v'] - math.sin(a) * L
        du, dv = 2 * math.cos(a) * L, 2 * math.sin(a) * L
        t = max(0.0, min(1.0, ((u - u0) * du + (v - v0) * dv) / (du * du + dv * dv + 1e-9)))
        best = min(best, math.hypot(u0 + t * du - u, v0 + t * dv - v) - g['width'] / 2)
    return best


def is_shrub(it):
    return asset(it['key'])['cat'] == 'shrub'


def plan_mtv(A, B):
    """Separating-axis test of two convex quads in plan: (overlap depth m, unit axis to push A out of B along), or
    (0, None) when they are apart. The axis is the one of least overlap (the minimum translation)."""
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


def plan_depth(A, B):
    return plan_mtv(A, B)[0]


def clash_pairs(S):
    """Every plan overlap the save judge (check2) cannot see: an ISM stone or shrub into a solid (walls, plinth,
    rocks, props, collar, deadmen), ISM into ISM, beyond ISM_ALLOW. Returns [(depth, allow, item, other)]."""
    solids = [it for it in S.items if not it['ism'] and it['contact'] in ('rigid', 'lie', 'rest', 'bear')
              and it['group'] != 'hut_roof']
    isms = [it for it in S.items if it['ism']]
    out = []
    for it in isms:
        allow = ISM_ALLOW['shrub' if is_shrub(it) else 'stone']
        for s in solids:
            d = plan_depth(footprint_uv(it), footprint_uv(s))
            if d > allow + 1e-6:
                out.append((d, allow, it, s))
    for i in range(len(isms)):
        for j in range(i + 1, len(isms)):
            d = plan_depth(footprint_uv(isms[i]), footprint_uv(isms[j]))
            if d > ISM_ALLOW['ism'] + 1e-6:
                out.append((d, ISM_ALLOW['ism'], isms[i], isms[j]))
    return out


def declash(S, rounds=60):
    """Push each ISM stone / shrub out of whatever it cuts into (the minimum translation), a few cm past
    the allowance, until nothing is left (the verifier found shrubs inside the rain jar and through the walls, a
    cobble inside the bench and one under the bucket). Deterministic. Returns {item id: moved m}."""
    start = {id(it): (it['u'], it['v']) for it in S.items if it['ism']}
    for _ in range(rounds):
        pairs = clash_pairs(S)
        if not pairs:
            break
        done = set()
        for d, allow, it, other in sorted(pairs, key=lambda p: -p[0]):
            mover = it if it['ism'] and id(it) not in done else (other if other['ism'] and id(other) not in done else None)
            if mover is None:
                continue
            fixed = other if mover is it else it
            dd, ax = plan_mtv(footprint_uv(mover), footprint_uv(fixed))
            if ax is None:
                continue
            step = dd - allow + 0.03
            mover['u'] += ax[0] * step
            mover['v'] += ax[1] * step
            done.add(id(mover))
    return {id(it): math.hypot(it['u'] - u0, it['v'] - v0) for it in S.items if it['ism']
            for u0, v0 in [start[id(it)]]}


# ---------------------------------------------------------------------------- records

SETTLE = {
    'rigid': dict(mode='trace', max_tilt_deg=0, rand_tilt_deg=0, z_rule='min'),
    'lie': dict(mode='trace', max_tilt_deg=25, rand_tilt_deg=6, z_rule='mean'),
    'rest': dict(mode='physics', max_tilt_deg=15, rand_tilt_deg=3, z_rule='max'),
    'stack': dict(mode='none', max_tilt_deg=0, rand_tilt_deg=0, z_rule='mean'),    # placed by this set's `level`
    'bear': dict(mode='none', max_tilt_deg=0, rand_tilt_deg=0, z_rule='mean'),     # placed by this set's `level`
}


def size_m(it):
    e = asset(it['key'])
    sz = [c / 100.0 * it['scale'] for c in e['size_cm']]
    if abs(it['pitch']) > 60:
        sz = [sz[2], sz[1], sz[0]]
    return sz


def footprint_uv(it, pad=0.0):
    sx, sy, _ = size_m(it)
    c, s = math.cos(math.radians(it['yaw'])), math.sin(math.radians(it['yaw']))
    pts = []
    for fx, fy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        ax, ay = fx * (sx / 2 + pad), fy * (sy / 2 + pad)
        pts.append((it['u'] + ax * c - ay * s, it['v'] + ax * s + ay * c))
    return pts


def grid_uv(it, n=3):
    sx, sy, _ = size_m(it)
    c, s = math.cos(math.radians(it['yaw'])), math.sin(math.radians(it['yaw']))
    out = []
    for fx in np.linspace(-0.92, 0.92, n):
        for fy in np.linspace(-0.92, 0.92, n):
            ax, ay = fx * sx / 2, fy * sy / 2
            out.append((it['u'] + ax * c - ay * s, it['v'] + ax * s + ay * c))
    return out


def predict_levels(G, S, Hk):
    """Offline prediction of this set's `level` step on the heightmap (the editor traces the landscape instead):
    the plinth (base = lowest ground - sink, Z-scaled until its top clears the highest ground), the hut on it (walls
    Z-scaled to the arch height, the roof on the wall tops), the collar (course 1 at the lowest ground - 25 cm,
    course 2 on it). Every levelled item gets `pz0` / `ph` (predicted bottom and height, m). Returns the levels."""
    pl = Hk['plinth']
    gs = [G.g(u, v) for u, v in grid_uv(pl, 7)]
    h0 = size_m(pl)[2]
    p_base = min(gs) - PLINTH_SINK_CM / 100.0
    p_h = max(h0, max(gs) + PLINTH_CLEAR_CM / 100.0 - p_base)
    pl['pz0'], pl['ph'] = p_base, p_h
    arch_h = asset('AB_Side_Arch_small')['size_cm'][2] / 100.0
    base = p_base + p_h
    for w in Hk['walls'].values():
        w['pz0'], w['ph'] = base, arch_h
    roof = Hk['roof']
    roof['pz0'], roof['ph'] = base + arch_h, size_m(roof)[2]
    c1 = Hk['course1']
    cg = [G.g(u, v) for it in c1 for u, v in grid_uv(it, 3)]
    c_base = min(cg) - COLLAR_SINK_CM / 100.0
    ch = size_m(c1[0])[2]
    for it in c1:
        it['pz0'], it['ph'] = c_base, ch
    for it in Hk['course2']:
        it['pz0'], it['ph'] = c_base + ch, ch
    cap_ground = [G.g(u, v) for it in Hk['course2'] for u, v in grid_uv(it, 7)]
    thr = max(G.g(*q) for q in grade_uv())
    return dict(plinth_base=p_base, plinth_top=base, plinth_h=p_h, plinth_zscale_ratio=p_h / h0,
                plinth_ground=(min(gs), max(gs)), wall_base=base, wall_top=base + arch_h, roof_bottom=base + arch_h,
                door_grade=thr, sill_minus_grade=base - thr, collar_base=c_base, collar_top=c_base + 2 * ch,
                collar_ground=(min(cg), max(cg)), cap_min_clear=c_base + 2 * ch - max(cap_ground),
                cap_max_face=c_base + 2 * ch - min(cap_ground))


def to_record(G, it, rid, idmap):
    e = asset(it['key'])
    sz = size_m(it)
    x, y = G.world(it['u'], it['v'])
    hs = [G.g(u, v) for u, v in grid_uv(it)]
    st = dict(SETTLE[it['contact']] if it['contact'] in SETTLE else dict(mode='trace', max_tilt_deg=35 if it['group'] == 'base_ism' else 15,
                                                                         rand_tilt_deg=30 if it['group'] == 'base_ism' else 0, z_rule='mean'))
    st.update(sink_cm=int(it['sink'] if it['sink'] is not None else (5 if it['ism'] else 2)), drop_cm=int(it.get('drop_cm', 0)),
              z_offset_cm=0)
    solid = it['contact'] is not None
    rec = dict(id=rid, key=it['key'], asset=e['path'], kind='SM', cat=e['cat'],
               x_cm=round(x * 100, 1), y_cm=round(y * 100, 1), ground_z_cm=round(G.g(it['u'], it['v']) * 100, 1),
               yaw=round((YAW0 + it['yaw']) % 360.0, 2), pitch=it['pitch'], roll=it['roll'], scale=round(it['scale'], 3),
               scale_range=[round(it['scale'], 3)] * 2, settle=st, group=it['group'], folder='Set/%s/%s' % (SID, it['group']),
               data_layer='DL_SetDress', ism=bool(it['ism']), stack=it['contact'] == 'rest' and it.get('drop_cm', 0) > 0,
               attach=False, run_id=None, collision=bool(solid), foliage_exclude=bool(solid and it['contact'] != 'lie' or it['group'] == 'hut'),
               draw_distance_cm=draw_distance_cm(max(sz)), cast_shadow=True, size_m=[round(v, 3) for v in sz],
               slope_deg=round(math.degrees(math.atan((max(hs) - min(hs)) / max(0.5, max(sz[0], sz[1])))), 1),
               relief_m=round(max(hs) - min(hs), 2), road_clear_m=round(G.road_dist(footprint_uv(it)), 2),
               site_uv=[round(it['u'], 2), round(it['v'], 2)])
    if it['block']:
        rec['block'] = it['block']
    if it['contact']:
        rec['contact'] = it['contact']
    if it.get('material_set'):
        rec['material_set'] = it['material_set']
    if it.get('bears'):
        rec['bears_on'] = [idmap[id(x)] for x in it['bears']]
    if e.get('batch01') and e.get('verdict'):
        rec.update(requires_import=True, verdict=e['verdict'], imported=bool(e.get('imported')))
        if e.get('fallback'):
            fk, fs = e['fallback']
            rec['fallback'] = dict(asset=CAT[fk]['path'], scale=round(fs * it['scale'], 3))
    if it.get('verdict'):
        rec['verdict'] = it['verdict']
    if 'pz0' in it:
        rec['predicted'] = dict(bottom_cm=round(it['pz0'] * 100, 1), top_cm=round((it['pz0'] + it['ph']) * 100, 1),
                                by='the level step (predicted on the heightmap)')
    if it.get('note'):
        rec['note'] = it['note']
    return rec


def ground_records(G, S):
    out = []
    for i, g in enumerate(S.ground):
        L, Wd = g['length'], g['width']
        c, s = math.cos(math.radians(g['yaw'])), math.sin(math.radians(g['yaw']))
        zs = [G.g(g['u'] + a * c - b * s, g['v'] + a * s + b * c) for a in (-L / 2, 0, L / 2) for b in (-Wd / 2, 0, Wd / 2)]
        x, y = G.world(g['u'], g['v'])
        out.append(dict(id='%s_g%03d' % (SID, i), surface=g['surface'], shape=g['shape'], x_cm=round(x * 100, 1),
                        y_cm=round(y * 100, 1), z_cm=round(sum(zs) / len(zs) * 100, 1), yaw=round((YAW0 + g['yaw']) % 360, 1),
                        length_m=round(L, 2), width_m=round(Wd, 2), depth_m=round(max(3.0, max(zs) - min(zs) + 2.0), 2),
                        strength=round(g['strength'], 2), sort=int(g['order']), site_uv=[round(g['u'], 2), round(g['v'], 2)]))
    return out


# ---------------------------------------------------------------------------- cameras, hooks, lines

def cam_basis(yaw, pitch):
    cy, sy = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
    cp, sp = math.cos(math.radians(pitch)), math.sin(math.radians(pitch))
    fwd = np.array([cp * cy, cp * sy, sp])
    right = np.array([-sy, cy, 0.0])
    up = np.cross(right, fwd)
    return fwd, right, -up if up[2] < 0 else up


def in_frustum(eye, yaw, pitch, hfov, p, aspect=16 / 9, far=80.0):
    fwd, right, up = cam_basis(yaw, pitch)
    d = np.asarray(p, float) - np.asarray(eye, float)
    z = float(d @ fwd)
    if z <= 0.05 or z > far:
        return False
    th = math.tan(math.radians(hfov / 2))
    return abs(float(d @ right)) / z <= th and abs(float(d @ up)) / z <= th / aspect


def look_at(eye, tgt):
    d = np.asarray(tgt, float) - np.asarray(eye, float)
    return math.degrees(math.atan2(d[2], math.hypot(d[0], d[1]))), math.degrees(math.atan2(d[1], d[0]))


def hfov_mm(mm):
    """Horizontal FOV on a 36 mm back: WIDER than the CineCamera's 23.76 mm, so a 'nothing in the frame' check made
    with it is conservative. Framing checks ('is it in the frame') use hfov_cine."""
    return math.degrees(2 * math.atan(18.0 / mm))


def hfov_cine(mm):
    return math.degrees(2 * math.atan(CINE_FILMBACK_MM / 2.0 / mm))


def cin23_frames(G, H):
    """build_cinematics.py plan_cin23 re-derived on this set's hooks: the local frame at road 4,990 is the Keeper's
    feet, +x up-road (the last straight, YAW0), +y right. Shot 1: 24 mm from (-450, -250) cm, 60 cm over the ground,
    on the Keeper's chest, tilting to the mast base + 15 m (pitch capped at 60). Shot 2: 100 mm, 2.5 m down-road of
    the plate, 10 cm over it, looking at it. (m, world)"""
    kx, ky, kz = H['b23_keeper']
    f = (math.cos(math.radians(YAW0)), math.sin(math.radians(YAW0)))
    r = (-f[1], f[0])
    cx, cy = kx - 4.5 * f[0] - 2.5 * r[0], ky - 4.5 * f[1] - 2.5 * r[1]
    c1 = (cx, cy, G.gw(cx, cy) + 0.6)
    pk, yk = look_at(c1, (kx, ky, kz + 1.0))
    mb = H['mast_base']
    pc, yc = look_at(c1, (mb[0], mb[1], mb[2] + 15.0))
    px, py, pz = H['plate']
    ci = (px - 2.5 * f[0], py - 2.5 * f[1], pz + 0.1)
    return dict(s1_start=dict(cam=c1, yaw=yk, pitch=pk + 2.0), s1_end=dict(cam=c1, yaw=yc, pitch=min(pc, 60.0)),
                s2=dict(cam=ci, yaw=look_at(ci, H['plate'])[1], pitch=look_at(ci, H['plate'])[0]))


def hooks_and_cams(G):
    """World poses (m) of the ending hooks and the cameras that frame this set (provisional z: heightmap)."""
    nf, _, _ = hut_axes()
    face_yaw = (YAW0 + math.degrees(math.atan2(nf[1], nf[0]))) % 360.0          # the plate's outward normal (world)
    pu, pv = plate_uv(0.0)
    su, sv = plate_uv(STAND_OUT_M)
    thr = max(G.g(*q) for q in grade_uv())                                        # the door grade (S26 floor level)
    px, py = G.world(pu, pv)
    sx, sy = G.world(su, sv)
    gz_o = G.gw(O_CM[0] / 100, O_CM[1] / 100)
    seat_x, seat_y = O_CM[0] / 100 + SEAT_OFF_CM[0] / 100, O_CM[1] / 100 + SEAT_OFF_CM[1] / 100
    stand_yaw = (face_yaw + 180.0) % 360.0
    bx, by = math.cos(math.radians(stand_yaw)), math.sin(math.radians(stand_yaw))
    rx, ry = -by, bx
    ots = (sx - bx * STAND_BACK_CM / 100 + rx * STAND_RIGHT_CM / 100, sy - by * STAND_BACK_CM / 100 + ry * STAND_RIGHT_CM / 100,
           G.gw(sx, sy) + OTS_UP_CM / 100)
    shoulder = (sx, sy, G.gw(sx, sy) + 1.4)
    plate = (px, py, thr + PLATE_UP_M)
    focus = tuple(plate[i] * 0.75 + shoulder[i] * 0.25 for i in range(3))
    ots_pitch, ots_yaw = look_at(ots, focus)
    c2 = (O_CM[0] / 100 + C2_OFF_CM[0] / 100, O_CM[1] / 100 + C2_OFF_CM[1] / 100, gz_o + C2_OFF_CM[2] / 100)
    _, c2_yaw = look_at(c2, (O_CM[0] / 100, O_CM[1] / 100, gz_o))
    bu, bv = G.road_uv(B23_ROAD_M)
    keeper = G.world(bu, bv)
    boom = G.world(bu - BOOM_M, bv + 0.4)
    b23_cam = (boom[0], boom[1], G.gw(*boom) + 2.1)
    return dict(
        mast_base=(O_CM[0] / 100, O_CM[1] / 100, gz_o),
        plate=plate, plate_yaw=face_yaw, plate_uv=(pu, pv),
        stand_feet=(sx, sy, G.gw(sx, sy)), stand_capsule=(sx, sy, G.gw(sx, sy) + HALF_HEIGHT_CM / 100), stand_yaw=stand_yaw,
        stand_uv=(su, sv),
        seat=(seat_x, seat_y, G.gw(seat_x, seat_y) + SEAT_EYE_CM / 100), seat_yaw=SEAT_YAW, seat_pitch=SEAT_PITCH,
        ots=ots, ots_yaw=ots_yaw, ots_pitch=ots_pitch,
        c2=c2, c2_yaw=c2_yaw, c2_pitch=88.0,
        b23_keeper=(keeper[0], keeper[1], G.gw(*keeper)), b23_cam=b23_cam,
        threshold_z=thr,
        speaker=(G.world(*hut_xy(ARCH_OUT - 0.15, 0.0)) + (thr + 2.55,)),
    )


def pillar_face_point(dx, dy):
    """Where a line from the pillar centre toward (dx, dy) leaves the 0.5 x 1 m section (world m offsets)."""
    hx, hy = PILLAR_HALF_CM[0] / 100, PILLAR_HALF_CM[1] / 100
    t = min(hx / abs(dx) if abs(dx) > 1e-6 else 1e9, hy / abs(dy) if abs(dy) > 1e-6 else 1e9)
    return dx * t, dy * t


def lines_data(G, H, recs_by_key):
    """Guys and the conduit: thin pieces with a non-uniform scale, placed by this set's `lines` step."""
    out = []
    mx, my = O_CM[0] / 100, O_CM[1] / 100
    for i, an in enumerate(H['anchors']):
        r = recs_by_key[id(an)]
        ax, ay = r['x_cm'] / 100, r['y_cm'] / 100
        fx, fy = pillar_face_point(ax - mx, ay - my)
        out.append(dict(id='%s_guy%d' % (SID, i), role='guy', asset=EA_PIPE, material=IRON, section_cm=3.0,
                        a=dict(on='actor_top', actor=r['id'], xy_cm=[r['x_cm'], r['y_cm']], sink_cm=3.0),
                        b=dict(on='mast', xy_cm=[round((mx + fx) * 100, 1), round((my + fy) * 100, 1)], up_cm=GUY_ATTACH_M * 100),
                        note='iron guy: deadman %d to the mast face 28 m up' % i))
    # conduit: collar face -> three ground-following runs -> the riser up the front wall to the plate
    pu, pv = plate_uv(0.0)
    foot = plate_uv(0.02)             # pipe centre 5 cm off the wall face (4 cm radius + 1 cm), under the plate
    fx, fy = G.world(*foot)
    _, L, W = collar_rect()
    half = (L + W) / 2
    dx, dy = fx - mx, fy - my
    t = min(half / abs(dx) if abs(dx) > 1e-6 else 1e9, half / abs(dy) if abs(dy) > 1e-6 else 1e9)
    sx_, sy_ = mx + dx * (t + 0.02 / max(abs(dx), abs(dy))), my + dy * (t + 0.02 / max(abs(dx), abs(dy)))
    pts = [(sx_ + (fx - sx_) * k / 3, sy_ + (fy - sy_) * k / 3) for k in range(4)]
    for k in range(3):
        out.append(dict(id='%s_conduit%d' % (SID, k), role='conduit', asset=EA_PIPE, material=BRASS, section_cm=8.0,
                        a=dict(on='ground', xy_cm=[round(pts[k][0] * 100, 1), round(pts[k][1] * 100, 1)], lift_cm=2.0),
                        b=dict(on='ground', xy_cm=[round(pts[k + 1][0] * 100, 1), round(pts[k + 1][1] * 100, 1)], lift_cm=2.0),
                        note='brass cable conduit, half sunk in its gravel strip'))
    out.append(dict(id='%s_riser' % SID, role='riser', asset=EA_PIPE, material=BRASS, section_cm=8.0,
                    a=dict(on='ground', xy_cm=[round(fx * 100, 1), round(fy * 100, 1)], lift_cm=-4.0),
                    b=dict(on='plate_bottom', xy_cm=[round(fx * 100, 1), round(fy * 100, 1)]),
                    note='the riser up the wall into the plate'))
    return out


def views(G, H):
    def v(name, cam, look):
        return dict(name=name, cam_cm=[round(c * 100, 1) for c in cam], look_cm=[round(c * 100, 1) for c in look])
    hut = G.world(*HUT_C)
    hz = G.gw(*hut)
    mid = G.world(0.5, 4.5)
    mid3 = (mid[0], mid[1], G.gw(*mid) + 2.5)
    out = [v('carrier_a', H['b23_cam'], mid3)]
    for name, road_m in (('carrier_b', 4950.0), ('carrier_c', 4877.0)):
        u, vv = G.road_uv(road_m)
        x, y = G.world(u, vv)
        out.append(v(name, (x, y, G.gw(x, y) + 2.1), mid3))
    for name, (u, vv, up) in (('orbit_a', (-2.0, -16.0, 3.5)), ('orbit_b', (15.0, 14.0, 4.0)), ('orbit_c', (-9.0, 13.0, 6.0))):
        x, y = G.world(u, vv)
        out.append(v(name, (x, y, G.gw(x, y) + up), (hut[0], hut[1], hz + 1.8)))
    out.append(v('contact', H['ots'], H['plate']))
    x, y = G.world(-18.0, 20.0)
    out.append(v('high34', (x, y, G.gw(x, y) + 18.0), mid3))
    x, y = G.world(40.0, -300.0)
    out.append(v('far300', (x, y, G.gw(x, y) + 30.0), (O_CM[0] / 100, O_CM[1] / 100, H['mast_base'][2] + 10.0)))
    fwd, _, _ = cam_basis(SEAT_YAW, SEAT_PITCH)
    out.append(v('seat', H['seat'], tuple(np.array(H['seat']) + fwd * 20.0)))
    c2 = np.array(H['c2'])
    fwd2, _, _ = cam_basis(H['c2_yaw'], 88.0)
    out.append(v('mastup', tuple(c2), tuple(c2 + fwd2 * 10.0)))
    return out


# ---------------------------------------------------------------------------- checks

def obb_uv(it, pad=0.0):
    return footprint_uv(it, pad)


def pt_in_poly(p, poly):
    x, y = p
    inside = False
    for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1]):
        if (y0 > y) != (y1 > y) and x < x0 + (x1 - x0) * (y - y0) / (y1 - y0):
            inside = not inside
    return inside


def sat(A, B):
    for poly in (A, B):
        for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1]):
            nx, ny = y0 - y1, x1 - x0
            pa = [nx * x + ny * y for x, y in A]
            pb = [nx * x + ny * y for x, y in B]
            if max(pa) < min(pb) or max(pb) < min(pa):
                return False
    return True


def item_box_points(G, it, top_z=None):
    """Sample points of an item's predicted box (world m): the footprint corners, centre and edge mids at 3 heights."""
    h = it.get('ph', size_m(it)[2])
    base = it['pz0'] if 'pz0' in it else min(G.g(u, v) for u, v in grid_uv(it)) - (it['sink'] or 0) / 100.0
    pts = []
    for (u, v) in footprint_uv(it) + [(it['u'], it['v'])]:
        x, y = G.world(u, v)
        for fz in (0.0, 0.5, 1.0):
            pts.append((x, y, base + h * fz))
    return pts


def checks(G, S, recs, grecs, H, lines):
    notes, bad = [], []
    solids = [it for it in S.items if it['contact'] in ('rigid', 'lie', 'rest', 'bear', 'stack')]
    # 1. road core: >= 5 m from the road centreline, except the collar at the road's end (by design)
    for it, r in zip(S.items, recs):
        if it['ism'] or it['block'] == 'mastfoot':
            continue
        if r['road_clear_m'] < 5.0:
            bad.append('ROAD %s %s clear %.2f m' % (r['id'], r['key'], r['road_clear_m']))
    notes.append('road core: min clearance %.2f m (collar excluded: it stands on the road end round the mast)'
                 % min(r['road_clear_m'] for it, r in zip(S.items, recs) if not it['ism'] and it['block'] != 'mastfoot'))
    # 2. the plinth, the door sill and the collar after the level step (predicted on the heightmap)
    lv = S.levels
    notes.append('plinth: ground %.2f..%.2f m under it; base %.2f, top %.2f (thickness %.2f m, Z %.2f x its plan scale); '
                 'the walls stand on it' % (lv['plinth_ground'][0], lv['plinth_ground'][1], lv['plinth_base'],
                                            lv['plinth_top'], lv['plinth_h'], lv['plinth_zscale_ratio']))
    if lv['plinth_zscale_ratio'] > 1.8:
        bad.append('PLINTH Z-scaled %.2f x: too much relief under the hut for one slab' % lv['plinth_zscale_ratio'])
    notes.append('door sill (the plinth top) %+.2f m against the outside grade; clear door height = the opening '
                 '(%.2f m %s)' % (lv['sill_minus_grade'], DOOR_H, 'measured' if DOOR_MEASURED else 'ASSUMED: run doorcheck'))
    if not -0.05 <= lv['sill_minus_grade'] <= 0.15:
        bad.append('DOOR SILL %+.2f m against the outside grade (want -0.05..+0.15)' % lv['sill_minus_grade'])
    notes.append('collar: 2 courses, base %.2f, top %.2f over ground %.2f..%.2f: the cap stands %.2f m clear on the uphill '
                 '(approach) side and shows %.2f m on the downhill face' % (lv['collar_base'], lv['collar_top'],
                                                                           lv['collar_ground'][0], lv['collar_ground'][1],
                                                                           lv['cap_min_clear'], lv['cap_max_face']))
    if lv['cap_min_clear'] < COLLAR_EXPOSE_M:
        bad.append('COLLAR the cap is only %.2f m clear of the ground uphill (want >= %.2f)' % (lv['cap_min_clear'], COLLAR_EXPOSE_M))
    seat_g = H['seat'][2] - SEAT_EYE_CM / 100.0
    notes.append('seated Keeper: %.2f m of collar face behind his back (collar top %.2f, ground at the seat %.2f)'
                 % (lv['collar_top'] - seat_g, lv['collar_top'], seat_g))
    if lv['collar_top'] - seat_g < 0.6:
        bad.append('SEAT the collar face behind the seat is only %.2f m' % (lv['collar_top'] - seat_g))
    # the plate on the jamb: at least 5 cm of stone between the plate and the (assumed or measured) opening
    jamb = abs(PLATE_Y) - PLATE_HALF_M - DOOR_W / 2
    arch_half = asset('AB_Side_Arch_small')['size_cm'][0] / 200.0
    notes.append('plate on the left jamb: %.2f m of stone between the plate and the opening (%s opening %.2f m), %.2f m to '
                 'the arch end' % (jamb, 'measured' if DOOR_MEASURED else 'ASSUMED', DOOR_W, arch_half - abs(PLATE_Y) - PLATE_HALF_M))
    if jamb < 0.05 or arch_half - abs(PLATE_Y) - PLATE_HALF_M < 0.05:
        bad.append('PLATE does not sit on the jamb (%.2f m to the opening): set --plate-y after doorcheck' % jamb)
    # 2a. nothing on the worn paths (the way to the plate, the door and the bench)
    for it in S.items:
        if it['ism'] and path_clear(S, it['u'], it['v']) < 0.15:
            bad.append('ON PATH %s at (%.2f, %.2f)' % (it['key'], it['u'], it['v']))
    # 2b. what the save judge cannot see: ISM stones / shrubs cut into solids or each other (declash() pushed them out)
    left = clash_pairs(S)
    for d, allow, a, b in left:
        bad.append('ISM OVERLAP %s into %s by %.2f m (allowed %.2f)' % (a['key'], b['key'], d, allow))
    mv = sorted(S.moved.values())
    notes.append('ISM declash: %d of %d ISM pieces moved (max %.2f m), %d left out (no room within 0.6 m: %s); %d overlaps '
                 'left beyond %s' % (sum(1 for m in mv if m > 0.005), len(mv), max(mv) if mv else 0.0, len(S.dropped),
                                     ', '.join(d['key'] for d in S.dropped) or 'none', len(left), ISM_ALLOW))
    # 3. overlaps between solids of different blocks (plan, 2 cm pad)
    for i in range(len(solids)):
        for j in range(i + 1, len(solids)):
            a, b = solids[i], solids[j]
            if a['block'] and a['block'] == b['block']:
                continue
            if a['contact'] in ('rest', 'stack', 'bear') or b['contact'] in ('rest', 'stack', 'bear'):
                continue       # props settle onto what they touch; the roof is 3 m up
            if sat(obb_uv(a, -0.02), obb_uv(b, -0.02)):
                bad.append('OVERLAP %s x %s' % (a['key'], b['key']))
    # 4. the seated frame (SeatPoint, 24 mm): no solid, no guy inside it
    seat = H['seat']
    hf = hfov_mm(24.0)
    for it in solids:
        if any(in_frustum(seat, SEAT_YAW, SEAT_PITCH, hf, p) for p in item_box_points(G, it)):
            bad.append('SEAT frame holds %s (%s)' % (it['key'], it['note'] or it['group']))
    for ln in lines:
        if ln['role'] != 'guy':
            continue
        a = [c / 100 for c in ln['a']['xy_cm']]
        b = [c / 100 for c in ln['b']['xy_cm']]
        za, zb = G.gw(*a), H['mast_base'][2] + GUY_ATTACH_M
        for k in range(41):
            t = k / 40
            p = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, za + (zb - za) * t)
            if in_frustum(seat, SEAT_YAW, SEAT_PITCH, hf, p):
                bad.append('SEAT frame holds %s' % ln['id'])
                break
    for ln in lines:
        if ln['role'] != 'guy':
            continue
        a = [c / 100 for c in ln['a']['xy_cm']]
        b = [c / 100 for c in ln['b']['xy_cm']]
        za, zb = G.gw(*a) + 0.4, H['mast_base'][2] + GUY_ATTACH_M
        for it in solids:
            if it['group'] == 'guys':
                continue
            top = (it['pz0'] + it['ph'] if 'pz0' in it else min(G.g(u, v) for u, v in grid_uv(it)) + size_m(it)[2]) + \
                (1.0 if it['block'] == 'hut' else 0.3)
            hit = False
            for k in range(1, 80):
                t = k / 80
                u, v = G.site(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
                if za + (zb - za) * t < top and pt_in_poly((u, v), obb_uv(it, 0.2)):
                    hit = True
                    break
            if hit:
                bad.append('GUY %s passes through %s' % (ln['id'], it['key']))
    notes.append('guys: clear of every solid (0.2 m pad; the hut roof counts 1 m above its walls)'
                 if not any(x.startswith('GUY') for x in bad) else 'guys: BLOCKED')
    notes.append('seated frame (24 mm, yaw %.1f, pitch %.1f): %s' % (SEAT_YAW, SEAT_PITCH,
                 'clear of every solid and guy' if not any(b.startswith('SEAT') for b in bad) else 'BLOCKED'))
    # 5. the stand point: room for the capsule, inside the tether and the blocking volumes
    su, sv = H['stand_uv']
    for it in solids:
        if it['contact'] in ('stack', 'bear'):
            continue
        if pt_in_poly((su, sv), obb_uv(it, 0.45)):
            bad.append('STAND point within 0.45 m of %s' % it['key'])
    sd = G.road_dist([(su, sv)])
    notes.append('StandPoint %.2f m from the road polyline (tether %.0f m, blocking volumes %.0f m)' % (sd, TETHER_M, BLOCK_M))
    if sd > BLOCK_M - 0.8:
        bad.append('STAND point %.2f m from the road: past the blocking volumes / tether' % sd)
    # 6. the OTS camera and its line to the plate
    ou, ov = G.site(H['ots'][0], H['ots'][1])
    for it in solids:
        if pt_in_poly((ou, ov), obb_uv(it, 0.15)):
            bad.append('OTS camera inside %s' % it['key'])
    pu, pv = H['plate_uv']
    for it in solids:
        if it['block'] == 'hut':
            continue
        for k in range(1, 20):
            t = k / 20
            if pt_in_poly((ou + (pu - ou) * t, ov + (pv - ov) * t), obb_uv(it)):
                bad.append('OTS line to the plate crosses %s' % it['key'])
                break
    # 7. TransmitCam (18 mm, straight up): nothing solid overhead
    c2 = H['c2']
    for it in solids:
        if any(in_frustum(c2, H['c2_yaw'], 88.0, hfov_mm(18.0), p, far=60.0) for p in item_box_points(G, it)):
            bad.append('MASTUP frame holds %s' % it['key'])
    # 8. B23: the walker's view (third-person boom) sees the plate: terrain ray + solids
    cam, plate = np.array(H['b23_cam']), np.array(H['plate'])
    clear = min(G.gw(*(cam[:2] + (plate[:2] - cam[:2]) * t)) - (cam[2] + (plate[2] - cam[2]) * t) for t in np.linspace(0.02, 0.97, 60))
    notes.append('B23 boom camera -> plate: terrain stays %.2f m under the sight line' % -clear)
    if clear > -0.3:
        bad.append('B23 sight line to the plate grazes the terrain (%.2f m)' % -clear)
    cu, cv = G.site(cam[0], cam[1])
    for it in solids:
        if it['block'] == 'hut':
            continue
        for k in range(1, 40):
            t = k / 40
            u, v = cu + (pu - cu) * t, cv + (pv - cv) * t
            z = cam[2] + (plate[2] - cam[2]) * t
            top = it['pz0'] + it['ph'] if 'pz0' in it else min(G.g(a, b) for a, b in grid_uv(it)) + size_m(it)[2]
            if pt_in_poly((u, v), obb_uv(it)) and z < top:
                bad.append('B23 sight line to the plate crosses %s' % it['key'])
                break
    # 8b. CIN_23_THE_MARK (optional, decided "yes" in CINEMATICS.md): build_cinematics.plan_cin23 re-derived here
    c23 = cin23_frames(G, H)
    walls = [it for it in S.items if it['block'] == 'hut' and it['group'] == 'hut']
    hf = hfov_cine(24.0)
    wpts = [p for it in walls for p in item_box_points(G, it)]
    s1 = c23['s1_start']
    share = sum(1 for p in wpts if in_frustum(s1['cam'], s1['yaw'], s1['pitch'], hf, p)) / len(wpts)
    plate_in = in_frustum(s1['cam'], s1['yaw'], s1['pitch'], hf, H['plate'])
    notes.append('CIN_23 shot 1 (24 mm low, from the B23 Keeper -4.5 m / 2.5 m left): the hut is %.0f %% in the opening '
                 'frame, the plate %s; the tilt ends at pitch %.0f on the mast' % (100 * share, 'in it' if plate_in else 'out of it',
                                                                                  c23['s1_end']['pitch']))
    if share < 0.25:
        bad.append('CIN23 shot 1 opens without the hut (%.0f %% of it in frame)' % (100 * share))
    s2 = c23['s2']
    cu2, cv2 = G.site(s2['cam'][0], s2['cam'][1])
    gz2 = G.gw(s2['cam'][0], s2['cam'][1])
    blockers = []
    for it in solids:
        top = it['pz0'] + it['ph'] if 'pz0' in it else min(G.g(a, b) for a, b in grid_uv(it)) + size_m(it)[2]
        if pt_in_poly((cu2, cv2), obb_uv(it, 0.1)) and s2['cam'][2] < top + 0.1:
            blockers.append('camera inside ' + it['key'])
        for k in range(1, 20):
            t = k / 20
            if pt_in_poly((cu2 + (pu - cu2) * t, cv2 + (pv - cv2) * t), obb_uv(it)) and s2['cam'][2] < top and it['block'] != 'hut':
                blockers.append('line crosses ' + it['key'])
                break
    dvec = np.array(H['plate'][:2]) - np.array(s2['cam'][:2])
    dvec /= np.linalg.norm(dvec)
    nfw = np.array([math.cos(math.radians(H['plate_yaw'])), math.sin(math.radians(H['plate_yaw']))])
    off_sq = math.degrees(math.acos(max(-1.0, min(1.0, float(-dvec @ nfw)))))
    notes.append('CIN_23 shot 2 (100 mm insert, 2.5 m down-road of the plate): %.0f deg off square, %.2f m over the ground, %s'
                 % (off_sq, s2['cam'][2] - gz2, 'clear' if not blockers else ', '.join(blockers)))
    if blockers or off_sq > 60.0 or s2['cam'][2] - gz2 < 0.3:
        bad.append('CIN23 shot 2 insert: %s, %.0f deg off square' % (', '.join(blockers) or 'low camera', off_sq))
    # the plate's angle to the walker at B23 (0 = square on)
    nf, _, _ = hut_axes()
    d = np.array([cu - pu, cv - pv])
    d /= np.linalg.norm(d)
    notes.append('B23: the plate faces the walker %.0f deg off square; the mast stands %.1f m left of the plate' % (
        math.degrees(math.acos(float(d @ np.array(nf)))), math.hypot(pu, pv)))
    # 9. decals cover their relief
    for g in grecs:
        if g['depth_m'] > 6:
            notes.append('decal %s depth %.1f m (steep)' % (g['id'], g['depth_m']))
    return notes, bad


# ---------------------------------------------------------------------------- plot

def plot(G, S, recs, grecs, H, lines, notes, out_png=OUT_PNG):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon, Ellipse

    fig = plt.figure(figsize=(17, 11))
    ax = fig.add_axes([0.03, 0.05, 0.58, 0.9])
    ax4 = fig.add_axes([0.65, 0.55, 0.33, 0.4])
    ax2 = fig.add_axes([0.66, 0.27, 0.32, 0.2])
    ax3 = fig.add_axes([0.65, 0.01, 0.34, 0.2])
    U, V = np.meshgrid(np.arange(-26, 22.01, 0.5), np.arange(-22, 22.01, 0.5))
    Z = np.vectorize(G.g)(U, V)
    z0 = G.g(0, 0)
    cs = ax.contour(U, V, Z - z0, levels=np.arange(-8, 8.01, 0.5), colors='#b9ad9a', linewidths=0.6)
    ax.clabel(cs, levels=np.arange(-8, 8.01, 1.0), fontsize=6, fmt='%+.0f')
    ax.fill_between([-26, 0], -4.5, 4.5, color='#8a8a8a', alpha=0.35, lw=0)
    ax.plot([-26, 0], [0, 0], color='#555', lw=0.8, ls='--')
    ax.plot([-26, 0], [BLOCK_M, BLOCK_M], color='#c55', lw=0.8, ls=':')
    ax.plot([-26, 0], [-BLOCK_M, -BLOCK_M], color='#c55', lw=0.8, ls=':')
    ax.add_patch(plt.Circle((0, 0), TETHER_M, fill=False, color='#c55', lw=0.8, ls=':'))
    ax.text(-25.5, -BLOCK_M + 0.3, 'V9 blocking volume (8 m)', fontsize=7, color='#c55')
    ax.text(-25.5, 0.4, 'road (last 45 m, 17 % down to the mast)', fontsize=7, color='#444')
    for g in S.ground:
        c = SURF_COL[g['surface']]
        if g['shape'] == 'capsule':
            a = math.radians(g['yaw'])
            L = g['length'] - g['width']
            ax.plot([g['u'] - math.cos(a) * L / 2, g['u'] + math.cos(a) * L / 2], [g['v'] - math.sin(a) * L / 2, g['v'] + math.sin(a) * L / 2],
                    color=c, lw=g['width'] * 9, alpha=0.35 * g['strength'] + 0.1, solid_capstyle='round')
        else:
            ax.add_patch(Ellipse((g['u'], g['v']), g['length'], g['width'], angle=g['yaw'], color=c, alpha=0.3 * g['strength'], lw=0))
    colours = dict(hut='#3d3d52', hut_roof='#77778f', hut_floor='#c9b98f', mastfoot='#5a4a3a', guys='#5a4a3a', hut_yard='#6b5b45',
                   woodpile='#8a5a2b', rocks='#6d6d6d')
    for it in S.items:
        if it['ism']:
            ax.plot(it['u'], it['v'], 'o', ms=2.5, color='#6a8a4a' if it['group'] == 'creep_ism' else '#8a6a5a')
            continue
        poly = obb_uv(it)
        if it['group'] == 'hut_roof' and it['key'] == 'B01_floor01':
            ax.add_patch(Polygon(poly, closed=True, fill=False, ec='#77778f', lw=0.8, ls='--'))
            continue
        if it['group'] == 'hut_floor':
            ax.add_patch(Polygon(poly, closed=True, fc='#c9b98f', ec='#8a7a55', lw=0.6, alpha=0.5))
            continue
        if it.get('course') == 2:
            ax.add_patch(Polygon(poly, closed=True, fill=False, ec='#2a1a0a', lw=0.7, ls=':'))
            continue
        ax.add_patch(Polygon(poly, closed=True, fc=colours.get(it['group'], '#556'), ec='k', lw=0.4, alpha=0.9))
    ax.add_patch(Polygon([mast_world_offsets_to_uv(G, sx * PILLAR_HALF_CM[0], sy * PILLAR_HALF_CM[1])
                          for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))], closed=True, fc='#c8703a', ec='k', lw=0.6))
    for ln in lines:
        a = G.site(*[c / 100 for c in ln['a']['xy_cm']])
        b = G.site(*[c / 100 for c in ln['b']['xy_cm']])
        if ln['role'] == 'guy':
            ax.plot([a[0], b[0]], [a[1], b[1]], color='#333', lw=0.9, ls=(0, (6, 3)))
        elif ln['role'] == 'conduit':
            ax.plot([a[0], b[0]], [a[1], b[1]], color='#b8862b', lw=2.4)
    # hooks and cameras
    pu, pv = H['plate_uv']
    su, sv = H['stand_uv']
    ax.plot(pu, pv, 's', ms=7, color='#e0b040', mec='k')
    ax.annotate('plate (palm in a ring)', (pu, pv), (pu - 9.5, pv + 3.2), fontsize=8, arrowprops=dict(arrowstyle='-', lw=0.6))
    ax.plot(su, sv, 'o', ms=6, color='#2a7', mec='k')
    ax.annotate('StandPoint', (su, sv), (su - 8.5, sv + 1.2), fontsize=8, arrowprops=dict(arrowstyle='-', lw=0.6))

    def wedge(pos_w, yaw_w, hfov, rng_m, col, label):
        u, v = G.site(pos_w[0], pos_w[1])
        a = yaw_w - YAW0
        pts = [(u, v)] + [(u + rng_m * math.cos(math.radians(a + d)), v + rng_m * math.sin(math.radians(a + d)))
                          for d in np.linspace(-hfov / 2, hfov / 2, 12)]
        ax.add_patch(Polygon(pts, closed=True, fc=col, alpha=0.12, ec=col, lw=0.8))
        ax.plot(u, v, '^', color=col, ms=6)
        ax.text(u + 0.3, v - 0.9, label, fontsize=7, color=col)
    wedge(H['seat'], SEAT_YAW, hfov_mm(24.0), 20.0, '#1f5fbf', 'SeatPoint 24 mm (CIN_24 shot 5)')
    wedge(H['ots'], H['ots_yaw'], hfov_mm(50.0), 3.0, '#bf1f5f', 'OTS 50 mm')
    c2u, c2v = G.site(H['c2'][0], H['c2'][1])
    ax.plot(c2u, c2v, 'x', color='#7a1fbf', ms=7)
    ax.text(c2u + 0.3, c2v + 0.3, 'TransmitCam (up)', fontsize=7, color='#7a1fbf')
    bu, bv = G.site(H['b23_cam'][0], H['b23_cam'][1])
    ax.plot([bu, pu], [bv, pv], color='#2a7', lw=0.8, ls='--')
    ax.plot(bu, bv, '>', color='#2a7', ms=7)
    ax.text(bu + 0.3, bv - 1.2, 'B23 (road 4,990) boom camera', fontsize=7, color='#2a7')
    for nm, (u, v, txt) in dict(hut=(HUT_C[0] - 1.2, HUT_C[1] + 0.3, 'relay hut'),
                                mast=(0.9, -0.9, 'mast (L2 HighVoice)')).items():
        ax.text(u, v, txt, fontsize=8, color='#222', weight='bold')
    door = hut_xy(ARCH_OUT - 0.6, 0.0)
    ax.text(door[0] - 0.5, door[1] + 0.3, 'door', fontsize=7)
    tags = {'guy deadman': 'deadman', 'rock face': 'rock face', 'outcrop': 'outcrop', 'boulder on the valley': 'moss boulder',
            'stone bench': 'bench', 'rain jar': 'rain jar', 'the valley window': 'shutter',
            'the right guy anchor': 'rock'}
    done = set()
    for it in S.items:
        for k, lab in tags.items():
            if it['note'] and it['note'].startswith(k) and (lab, round(it['u']), round(it['v'])) not in done:
                done.add((lab, round(it['u']), round(it['v'])))
                ax.text(it['u'] + 0.6, it['v'] + 0.5, lab, fontsize=7, color='#333')
    ax.text(-4.0, -2.6, 'stone collar', fontsize=7, color='#5a4a3a')
    cu_, cv_ = plate_uv(0.0)
    ax.text(cu_ + 0.5, (cv_ + 1.3) / 2, 'brass conduit', fontsize=7, color='#8a6a1b', rotation=85)
    ax.text(-12.0, -14.5, 'the seated shot looks east over the valley:' + chr(10) + 'kept empty (gravel ring only)', fontsize=7,
            color='#1f5fbf')
    ax.set_xlim(-26, 22)
    ax.set_ylim(22, -22)          # v grows DOWN: a true top view (facing +u, your right is down the page)
    ax.set_aspect('equal')
    ax.set_xlabel('u (m): along the last road heading (yaw %.2f), 0 = mast base = spline point 0' % YAW0)
    ax.set_ylabel('v (m): right of travel (up the page, -v, is left of travel: east, the valley)')
    ax.set_title('V10 the High Voice relay station: true top view, site frame (contours 0.5 m, relative to the mast base)',
                 fontsize=10)
    ax.arrow(18, -15.5, 3 * math.cos(math.radians(-YAW0)), 3 * math.sin(math.radians(-YAW0)), head_width=0.5, color='k')
    ax.text(12.5, -19.8, 'world +X (east)', fontsize=7)

    # the hut in the S26 shell-contract frame (x: front -> back, y: right of x; a true top view)
    def hxy(u, v):
        _, X, Y = hut_axes()
        du, dv = u - HUT_C[0], v - HUT_C[1]
        return du * X[0] + dv * X[1], du * Y[0] + dv * Y[1]
    for it in S.items:
        if it['ism']:
            x, y = hxy(it['u'], it['v'])
            if abs(x) < 4.5 and abs(y) < 4.5:
                ax4.plot(x, y, 'o', ms=3, color='#6a8a4a' if it['group'] == 'creep_ism' else '#8a6a5a')
            continue
        poly = [hxy(u, v) for u, v in obb_uv(it)]
        if max(abs(p[0]) for p in poly) > 6 or max(abs(p[1]) for p in poly) > 6:
            continue
        if it['group'] == 'hut_roof':
            ax4.add_patch(Polygon(poly, closed=True, fill=False, ec='#77778f', lw=1.0, ls='--'))
            continue
        if it['group'] == 'hut_floor':
            ax4.add_patch(Polygon(poly, closed=True, fc='#c9b98f', ec='#8a7a55', lw=0.8, ls='--', alpha=0.45))
            continue
        if it['key'] == 'AB_Side_Arch_small':
            (x0, x1), (y0, y1) = (min(p[0] for p in poly), max(p[0] for p in poly)), (min(p[1] for p in poly), max(p[1] for p in poly))
            for ya, yb in ((y0, -DOOR_W / 2), (DOOR_W / 2, y1)):
                ax4.add_patch(plt.Rectangle((x0, ya), x1 - x0, yb - ya, fc='#3d3d52', ec='k', lw=0.5))
            ax4.text(x0 - 0.05, 0, 'door (%.2f m %s)' % (DOOR_W, 'measured' if DOOR_MEASURED else 'ASSUMED'), fontsize=7,
                     ha='right', va='center')
            continue
        ax4.add_patch(Polygon(poly, closed=True, fc=colours.get(it['group'], '#556'), ec='k', lw=0.5, alpha=0.9))
        if it['note'] and it['group'] in ('hut_yard',) or it['key'] == 'AB_Window_B':
            cx, cy = np.mean([p[0] for p in poly]), np.mean([p[1] for p in poly])
            ax4.text(cx + 0.15, cy - 0.2, {'B01_brick01': 'bench', 'B01_tank01': 'rain jar', 'MV_bucket_01': 'bucket',
                                         'AB_Window_B': 'shutter (sill 1 m)'}.get(it['key'], ''), fontsize=7)
    inner = [(-1.07, -1.37), (1.38, -1.37), (1.38, 1.37), (-1.07, 1.37)]
    ax4.add_patch(Polygon(inner, closed=True, fc='#e9dcc0', ec='#a08a5a', lw=0.8, ls=':', alpha=0.6))
    ax4.text(0.15, 0.0, 'S26 interior' + chr(10) + '2.45 x 2.74 m' + chr(10) + '(on the plinth: desk,' + chr(10) + 'chair, bench, stores)',
             fontsize=7, ha='center', va='center', color='#6b5b35')
    px, py = hxy(*H['plate_uv'])
    sx, sy = hxy(*H['stand_uv'])
    ox, oy = hxy(*G.site(H['ots'][0], H['ots'][1]))
    ax4.plot(px, py, 's', ms=8, color='#e0b040', mec='k')
    ax4.text(px - 0.1, py - 0.35, 'plate (y %.2f, 1.30 m up)' % PLATE_Y, fontsize=7, ha='right')
    ax4.plot(sx, sy, 'o', ms=7, color='#2a7', mec='k')
    ax4.text(sx - 0.1, sy + 0.4, 'StandPoint', fontsize=7, ha='right')
    ax4.plot(ox, oy, '^', ms=7, color='#bf1f5f')
    ax4.text(ox - 0.1, oy + 0.45, 'OTS 50 mm', fontsize=7, ha='right', color='#bf1f5f')
    for q in grade_uv():
        gx, gy = hxy(*q)
        ax4.plot(gx, gy, '+', color='#555', ms=6)
    ax4.text(ARCH_OUT - 0.35, 0.95, 'grade points', fontsize=6, ha='right', color='#555')
    mx, my = hxy(0.0, 0.0)
    ax4.annotate('to the mast (%.1f m)' % math.hypot(mx, my), (max(-4.4, mx), max(-4.4, min(4.4, my))), fontsize=7)
    ax4.set_xlim(-4.6, 4.6)
    ax4.set_ylim(4.0, -4.0)
    ax4.set_aspect('equal')
    ax4.set_title('the hut frame (x front -> back, y right; S26 reads it from interior_frame)' + chr(10) +
                  'plinth (dashed): the floor and the sill; S26 lays its room out on it', fontsize=8)
    ax4.grid(alpha=0.2)

    # section along the approach (v = 0) and through the hut's plate line
    us = np.linspace(-60, 20, 161)
    ax2.plot(us, [G.g(u, 0) - z0 for u in us], color='#7a6a50', lw=1.4, label='ground on the road axis')
    ax2.plot(us, [G.g(u, H['plate_uv'][1]) - z0 for u in us], color='#b9ad9a', lw=1.0, ls='--', label='ground on the plate line')
    ax2.plot([0, 0], [G.g(0, 0) - z0, 40], color='#c8703a', lw=2)
    ax2.plot([0], [44], 'o', ms=9, color='#c8703a')
    lv = S.levels
    hu = [it['u'] for it in S.items if it['group'] == 'hut']
    ax2.add_patch(plt.Rectangle((min(hu) - 1.4, lv['wall_base'] - z0), max(hu) - min(hu) + 2.8, 3.26, fc='#3d3d52', alpha=0.6))
    ax2.add_patch(plt.Rectangle((min(hu) - 1.5, lv['plinth_base'] - z0), max(hu) - min(hu) + 3.0, lv['plinth_h'], fc='#c9b98f', alpha=0.8))
    ax2.add_patch(plt.Rectangle((-1.23, lv['collar_base'] - z0), 2.46, lv['collar_top'] - lv['collar_base'], fc='#5a4a3a', alpha=0.8))
    ax2.plot([H['b23_keeper'][0] and G.site(H['b23_keeper'][0], H['b23_keeper'][1])[0]], [H['b23_keeper'][2] - z0 + 1.6], 'o', color='#2a7')
    ax2.plot([bu, pu], [H['b23_cam'][2] - z0, H['plate'][2] - z0], color='#2a7', lw=0.8, ls='--')
    ax2.set_xlim(-60, 20)
    ax2.set_ylim(-6, 46)
    ax2.set_xlabel('u (m)')
    ax2.set_ylabel('m above the mast base')
    ax2.set_title('section: the approach, the mast (40 m + crown) in its 2-course collar, the hut (walls 3.26 m) on its plinth', fontsize=8)
    ax2.legend(fontsize=6, loc='upper left')
    ax3.axis('off')
    txt = 'Checks (offline, heightmap):\n' + '\n'.join('- ' + n for n in notes)
    ax3.text(0, 1, txt, fontsize=6.6, va='top', wrap=True, family='monospace')
    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    fig.savefig(out_png, dpi=85)
    return out_png


# ---------------------------------------------------------------------------- build and write

def build():
    G = Ground()
    S, Hk = compose(G)
    S.levels = predict_levels(G, S, Hk)
    idmap = {id(it): '%s_%03d' % (SID, i) for i, it in enumerate(S.items)}
    recs = [to_record(G, it, idmap[id(it)], idmap) for it in S.items]
    by_item = {id(it): r for it, r in zip(S.items, recs)}
    grecs = ground_records(G, S)
    H = hooks_and_cams(G)
    lines = lines_data(G, Hk, by_item)
    for ln in lines:
        ln['draw_cm'] = 30000.0 if ln['role'] == 'guy' else 6000.0
    return G, S, Hk, recs, by_item, grecs, H, lines


def level_blocks(S, Hk, by_item):
    walls = Hk['walls']
    hut_members = [by_item[id(walls[k])]['id'] for k in ('front', 'back', 'left', 'right')]
    r = by_item[id(Hk['roof'])]
    sup = [dict(id=r['id'], rule='on_members', x=r['x_cm'], y=r['y_cm'], yaw=r['yaw'], pitch=0.0)]
    r = by_item[id(Hk['shutter'])]
    sup.append(dict(id=r['id'], rule='grade', offset_cm=WINDOW_SILL * 100.0, x=r['x_cm'], y=r['y_cm'], yaw=r['yaw'], pitch=0.0,
                    optional=True))
    collar = [by_item[id(it)]['id'] for it in Hk['course1']]
    cap = []
    for it in Hk['course2']:
        r = by_item[id(it)]
        cap.append(dict(id=r['id'], rule='on_members', x=r['x_cm'], y=r['y_cm'], yaw=r['yaw'], pitch=0.0))
    pl = by_item[id(Hk['plinth'])]['id']
    return [dict(block='plinth', members=[pl], sink_cm=PLINTH_SINK_CM, match=None, supports=[], base_on=None,
                 clear_cm=PLINTH_CLEAR_CM,
                 why='the plinth first: base = the lowest ground under it - 3 cm, then Z-scaled until its top clears the '
                     'highest ground under it (5 x 5 traces) by 3 cm: the hut floor and the door sill, no terrain through it'),
            dict(block='mastfoot', members=collar, sink_cm=COLLAR_SINK_CM, match=None, supports=cap, base_on=None,
                 clear_cm=None,
                 why='course 1 of the collar shares one base (the lowest ground - 25 cm, dug in uphill); course 2 lies on '
                     'its top (on_members), the reversed pinwheel, so the cap stands clear of the slope all round'),
            dict(block='hut', members=hut_members, sink_cm=0.0, match=by_item[id(walls['front'])]['id'],
                 supports=sup, base_on='plinth', clear_cm=None,
                 why='the walls stand on the plinth top (base_on); the plain walls take the door arch height (3.26 m, a Z '
                     'scale), the roof slab lies on the arch and the back wall, the shutter hangs on the valley wall with '
                     'its sill 1 m over the door grade')]


def interior_frame(G, H, S=None, by_item=None, Hk=None):
    """What S26 (s26_high_voice_hut.py) lays its room out against: the hut frame, the inner faces, the door, the
    floor it stands on (V10's plinth) and the predicted heights. S26 reads this on every run."""
    t_half = asset('AB_300x400_Mid')['size_cm'][0] / 200.0
    side_in = HALF - SIDE_SCALE * t_half
    front_in, back_in = ARCH_OUT + asset('AB_Side_Arch_small')['size_cm'][1] / 100.0, HALF - t_half
    corners = [G.world(*hut_xy(x, y)) for x, y in ((front_in, -side_in), (front_in, side_in), (back_in, side_in), (back_in, -side_in))]

    def w(x, y):
        return [round(c * 100, 1) for c in G.world(*hut_xy(x, y))]
    hut_yaw = (YAW0 + HUT_PSI - 180.0) % 360.0
    out = dict(
        for_set='S26_HighVoiceHut (Tools/World/story_sets/s26_high_voice_hut.py): one room, AB 300x400 walls on a 3.0 m '
                'square of centre lines, the AB_Side_Arch_small front; the frame, the floor and the openings below',
        frame='hut frame, metres: origin hut_centre_cm, +x = hut_x_yaw_world (front/door wall -> back wall), +y = '
              'hut_x_yaw_world + 90 (right of +x); the door is centred on y = 0 in the front',
        hut_centre_cm=w(0.0, 0.0), hut_x_yaw_world=round(hut_yaw, 2),
        corners_cm=[[round(x * 100, 1), round(y * 100, 1)] for x, y in corners],
        inner_m=dict(front=round(front_in, 3), back=round(back_in, 3), side=round(side_in, 3)),
        arch_m=dict(outer=ARCH_OUT, inner=round(front_in, 3)),
        door_cm=w(-HALF, 0.0),
        door_opening_m=dict(w=DOOR_W, h=DOOR_H, centre_y=0.0, measured=DOOR_MEASURED,
                            note='measured by `v10_high_voice.py doorcheck` (complex traces through the arch piece); '
                                 'until then these are assumptions'),
        plate=dict(local_y=PLATE_Y, where='outside, on the arch face (the left jamb)'),
        window=dict(local_x=WINDOW_X, sill_above_grade_m=WINDOW_SILL, state='a CLOSED shutter on the left wall\'s outer face; '
                    'the wall behind it is solid, so the room is lit through the door only'),
        door_grade='the highest ground at grade_points_cm (the `level` and `hooks` steps trace it)',
        grade_points_cm=[[round(c * 100, 1) for c in G.world(*q)] for q in grade_uv()],
        grade_z_cm=[round(G.g(*q) * 100, 1) for q in grade_uv()],
        floor_owner='V10: the plinth (B01_floor01) is the hut floor and the door sill; S26 places no floor, only the '
                    'room, and its props settle on the plinth (support_labels)',
        no_stove='V10 places no chimney, stove or hearth (none is modelled; see missing_assets)',
        keep_clear='the door passage and 0.6 m in front of the plate (StandPoint)',
    )
    if S is not None:
        lv = S.levels
        pid = by_item[id(Hk['plinth'])]['id']
        out['floor'] = dict(id=pid, label='SD_' + pid, top_cm_predicted=round(lv['plinth_top'] * 100, 1),
                            note='predicted on the heightmap; the `level` step sets the real top (LEVEL plinth ... top)')
        out['wall_base_cm_predicted'] = round(lv['wall_base'] * 100, 1)
        out['roof_bottom_cm_predicted'] = round(lv['roof_bottom'] * 100, 1)
    return out


MISSING = [
    dict(asset="the palm-in-a-ring mark (the teammate's mark: a decal or relief texture for the plate)",
         stand_in='SM_CircularBand ring at 34 cm on the plate (hooks --mark), no palm', needed_for='B23, CIN_23 shot 2, CIN_24 shot 1',
         tripo_prompt=None, note='a 2D mark, not a Tripo model: the capsule lid carries the same mark (teammate)'),
    dict(asset='brass horn loudspeaker on an iron wall bracket (the hut speaker CV_TRANSMIT_01 plays from)',
         stand_in='none; the sound hook HutSpeaker is above the door', needed_for='CIN_24 shot 1 (the spatial line)',
         tripo_prompt='weathered brass gramophone-horn loudspeaker on a riveted iron wall bracket, steampunk radio relay, 60 cm'),
    dict(asset='a guy cable with a turnbuckle, and an iron eye for the deadman',
         stand_in='EasyAtmos Pipe scaled to 3 cm with MI_Metal', needed_for='the mast reading as a built mast; CIN_24 shot 2',
         tripo_prompt='forged iron turnbuckle with two eye bolts and a short twisted cable end, weathered, 50 cm'),
    dict(asset='a riveted iron junction box with a brass dial at the mast foot (where the conduit leaves the collar)',
         stand_in='none (the conduit butts into the collar block)', needed_for='detail only',
         tripo_prompt='small riveted iron junction box with a brass dial and a cable gland, steampunk, 40 cm'),
    dict(asset='a mast that reads as riveted iron (Tile_10MPillar read as a modern white monolith: LANE_SD)',
         stand_in='the L2 beacon pillars; give Mast0-3 MI_Metal. The Tripo relay_tower (SourceArt/Tripo/relay_tower, '
                  '16.8 x 16.8 x 26 m, slot O12 "the first High Voice, dead and leaning") is the OLD relay, not this mast',
         needed_for='every mast view',
         tripo_prompt='tall slender riveted iron lattice radio mast section, 4 m, square, cross-braced, brass insulators, '
                      'steampunk; tileable vertically'),
    dict(asset='T2_radio_desk: the relay set for the S26 interior',
         stand_in='S26: AB_WoodenTable_B under AB_Table_Cloth',
         needed_for='the S26 interior (the doorway read)',
         tripo_prompt=None, note='GENERATED (SourceArt/Tripo/radio_desk, 128 x 200 x 182 cm at import): waits for the '
                                 'Tools/Tripo/IMPORT.md editor import; at that size it needs its own S26 layout pass'),
]


def write(G, S, Hk, recs, by_item, grecs, H, lines, notes, bad):
    solo = [r for r in recs if not r['ism']]
    ism = [r for r in recs if r['ism']]
    groups = sorted({(r['group'], r['asset']) for r in ism})
    c = G.world(0.5, 4.5)
    centre = [round(c[0] * 100, 1), round(c[1] * 100, 1), round(G.gw(*c) * 100, 1)]
    vs = views(G, H)
    radius = 22.0
    xs = [centre[0]] + [v['cam_cm'][0] for v in vs if v['name'] != 'far300']
    ys = [centre[1]] + [v['cam_cm'][1] for v in vs if v['name'] != 'far300']
    rr = (radius + 30) * 100
    waivers = [dict(id=by_item[id(it)]['id'], code='ON_ACTOR',
                    why="the collar stands on the road's end by design (the road ribbon ends at the mast): a first hit "
                        "on the road actor is the road, not a prop") for it in Hk['course1']]
    waivers.append(dict(id=by_item[id(Hk['shutter'])]['id'], code='FLOAT',
                        why='a shutter fixed to the valley wall face: the wall carries it, its sill is 1 m up by design '
                            '(the level step puts its back face on the wall face and prints SHUTTER_ON_WALL)'))
    site = dict(
        id=SID, story_set=SET, name='The High Voice relay station (V10)', kind='relay station', order=1,
        road_m=int(round(G.R.length)), side='on/right', lateral_m=4.5, centre_cm=centre, road_yaw=round(YAW0, 2),
        radius_m=radius, zone='Z6 Summit',
        storm='above the cloud: clear, calm, gold light; bare wind-scoured rock; the fewest objects on the road',
        role='landmark, story set',
        story='B23 the last entry and the mark; B24/CIN_24 the transmission, the mast up-shot, the held seated shot; '
              'CIN_23 (optional) the Keeper at the hut', decay=0,
        style='BAZAAR STONE hut (AB walls, flagstone roof), cut sandstone collar and deadmen, brass conduit and plate, iron guys',
        layout=('\n  road (down 17 %) ====> [collar + MAST] . . . guy -> deadman (ahead-left, 16 m)'
                '\n        path -> plate (StandPoint) -> door      [HUT 6.2 x 3.2 m, front turned back up the road]'
                '\n  moss boulder (valley verge)          bench on the valley gable     rock face past the hut'
                '\n  seated view: east from the collar, empty to the valley; deadmen behind-left and right'),
        notes='Story-owned: the L2 HighVoice actor (mast, crown, beam) and BP_Saskarta_HighVoice (ending hooks) are not '
              'placed here. S26 dresses the interior against interior_frame, on the plinth of this set.',
        story_owned=['HighVoice (L2 beacon actor)', 'BP_Saskarta_HighVoice (tag Saskarta.HighVoice, task ENDING 6c)'],
        verify_only=False, layer='road', poi=None,
        load_box_cm=[round(min(xs) - rr), round(min(ys) - rr), round(max(xs) + rr), round(max(ys) + rr)],
        counts=dict(placements=len(recs), actors=len(solo) + len(groups) + len(lines) + 1, ism_instances=len(ism),
                    physics=sum(1 for r in recs if r.get('contact') == 'rest'),
                    batch01=sum(1 for r in recs if r['key'].startswith('B01_')), decals=len(grecs), lines=len(lines)),
        views=vs, placements=recs, ground=grecs, units=[], waivers=waivers,
        v2=dict(frame=dict(origin_cm=list(O_CM), yaw=round(YAW0, 3), u='along the last road heading', v='right of travel'),
                hut=dict(centre_uv=list(HUT_C), front_psi=HUT_PSI)),
    )

    def cm(p):
        return [round(v * 100, 1) for v in p]
    doc = dict(
        generated_by='Tools/World/story_sets/v10_high_voice.py', method='docs/world/SETDRESS_V2.md',
        design='docs/world/story_sets/V10.md', level='/Game/level/Saskarta_WP',
        conventions=dict(xy='world cm; yaw = UE yaw deg', bounds='x_cm/y_cm is the mesh BOUNDS CENTRE',
                         ground='decal patches: DecalActor pitch -90, yaw, size (depth/2, width/2, length/2)',
                         contact='rigid | rest | lie | stack | bear (SETDRESS_V2.md section 3; bear = rests on bears_on)',
                         site_uv='u m along the last road heading (yaw %.2f) from spline point 0 (the mast base), v m right of travel' % YAW0),
        rejected=[], checks=bad, sites=[site],
        story_set=dict(
            id=SET, road_m=[4950, 5009],
            beats=['B23_LAST_ENTRY (road 4,990, UE 19.5 m: RADIO_B23_01 live, then "Lay your hand on the mark.")',
                   'B24 / CIN_24_TRANSMISSION (48 s): shot 1 OTS 50 mm on the plate, shot 2 TransmitCam up the mast 18 mm, '
                   'shot 5 SeatPoint 24 mm east over the valley',
                   'CIN_23_THE_MARK (optional): low 24 mm at the hut, tilt up the mast; 100 mm insert on the plate'],
            sources=['docs/story/storyline.md (section 2, B23/B24, V10)', 'docs/story/CINEMATICS.md (CIN_23, CIN_24)',
                     'Tools/Cinematics/probe_ending.json (provisional)', 'Tools/GameFlow/specs/README_Ending.md',
                     '.superpowers/sdd/2026-09-26-saskarta-world-sprint/task-ENDING-brief.md step 6',
                     'task-L2-report.md (the HighVoice actor)', 'task-SETDRESS-report.md (S26 waits for V10)']),
        level_blocks=level_blocks(S, Hk, by_item),
        lines=lines,
        story_hooks=dict(
            actor='BP_Saskarta_HighVoice (/Game/SaskartaGaea/Story/HighVoice/, tag Saskarta.HighVoice)',
            MastBase_cm=cm(H['mast_base']),
            Plate=dict(centre_cm=cm(H['plate']), yaw=round(H['plate_yaw'], 2), size_cm=[6, 45, 45], mesh=PLATE_MESH,
                       material=BRASS, z_rule='door grade + 130 cm (hooks step traces the grade)'),
            StandPoint=dict(feet_cm=cm(H['stand_feet']), capsule_cm=cm(H['stand_capsule']), yaw=round(H['stand_yaw'], 2),
                            set_at='capsule centre (K2_TeleportTo moves the capsule centre)'),
            SeatPoint=dict(cm=cm(H['seat']), yaw=SEAT_YAW, pitch=SEAT_PITCH),
            HutSpeaker_cm=cm(H['speaker']),
            TransmitCam_c2_cm=cm(H['c2']),
            OTS_cam_cm=cm(H['ots']),
            b23_boom_cam_cm=cm(H['b23_cam']),
            camera_plan_flag='resolved in build_cinematics.py (ENDING-PREP, RUNBOOK_Ending.md gap 3): plan_cin24 takes the '
                             'StandPoint as the capsule centre and subtracts keeper_half_height_cm for the feet, which is '
                             'what hooks sets; plan_cin23 frames the pawn at road 4,990 and inserts 2.5 m down-road of the '
                             'probed plate (re-derived in this file: CIN_23 offline_checks). Re-probe after hooks.'),
        interior_frame=interior_frame(G, H, S, by_item, Hk),
        ism_candidates=[dict(group=g, asset=a, instances=sum(1 for r in ism if r['group'] == g and r['asset'] == a))
                        for g, a in groups],
        missing_assets=MISSING,
        offline_checks=notes,
        editor_steps=EDITOR_STEPS,
    )
    with open(OUT_JSON, 'w', encoding='utf8') as fh:
        json.dump(doc, fh, indent=1, ensure_ascii=False)
    return site


_S = 'python Tools/World/story_sets/v10_high_voice.py '
EDITOR_STEPS = [
    'python Tools/GameFlow/editor_gate.py acquire --owner LANE_V10   # one editor lane at a time; PIE must be off',
    _S + '--no-plot                          # regenerate V10.json offline; exit 0 = no offline violation',
    _S + 'editor load --owner LANE_V10       # its own call (WP pinning rule); S26 later runs inside this load',
    _S + 'editor survey                      # expect HighVoice (L2) and nothing tagged SD_V10_HighVoice',
    _S + 'mastcheck                          # read-only: the pillar vs the collar hole (>= 3 cm) and the ground at point 0',
    _S + 'editor place --owner LANE_V10      # solids (15 per call), then the ISM hosts',
    _S + 'editor settle --owner LANE_V10     # rigid/lie by trace, rest by emulated physics; bear/stack wait for level',
    _S + 'level --owner LANE_V10             # plinth (Z to clear the ground), collar course 1 + cap, hut on the plinth, roof, shutter',
    _S + 'doorcheck                          # read-only: the arch opening and the plate on its jamb (PLATE ON_JAMB OK)',
    'if doorcheck printed OVERHANGS or other DOOR_ARGS: ' + _S + '--door-w W --door-h H [--plate-y Y]; rerun s26 offline',
    _S + 'lines --owner LANE_V10             # 3 guys + the conduit + the riser (non-uniform scale, NoCollision)',
    _S + 'editor ground --owner LANE_V10     # the decal patches (MI_SD_Ground_* exist: built for S07)',
    _S + 'editor matsurvey --owner LANE_V10',
    _S + 'materials variants                 # _GB copies of any material not yet in setdress_material_map.json',
    _S + 'editor material --owner LANE_V10',
    _S + 'hooks --owner LANE_V10 --mark      # only once BP_Saskarta_HighVoice is placed (task ENDING 6c); else it says so',
    _S + 'editor check2 --owner LANE_V10     # must print violations=0 (walls, cap and roof need the V2 lane bear class)',
    _S + 'editor capture --owner LANE_V10    # carrier_a..c, orbit_a..c, contact, high34, far300, seat, mastup',
    'review Saved/Screenshots/SetDressV2/V10_HighVoice/ with the user; fix in this generator, then editor replace <ids>, level, lines, check2',
    _S + 'editor save --owner LANE_V10       # refuses while check2 is stale or has violations (level/lines mark it stale)',
    _S + 'hooks-save --owner LANE_V10        # the ending actor package; refuses if the file is read-only on disk',
    'S26 (s26_high_voice_hut.py) now, inside this load: place .. save (docs/world/story_sets/RUNBOOK.md)',
    _S + 'editor unload --owner LANE_V10',
    'python Tools/GameFlow/editor_gate.py release --owner LANE_V10; commit the new external actor packages by pathspec',
    'then task ENDING step 7: probe-ending reads Plate/StandPoint/SeatPoint from the placed actor; re-emit CIN_24 and CIN_23',
]


# ---------------------------------------------------------------------------- editor steps of this set

MASTCHECK_BODY = r'''
hv = None
ending = None
for a in eas.get_all_level_actors():
    if a.get_actor_label() == 'HighVoice':
        hv = a
    for t in a.tags:
        if str(t) == 'Saskarta.HighVoice':
            ending = a
if hv is None:
    print('MAST no actor labelled HighVoice (task L2)')
else:
    l = hv.get_actor_location()
    print('MAST actor ' + str(round(l.x, 1)) + ',' + str(round(l.y, 1)) + ',' + str(round(l.z, 1)) + ' yaw ' + str(round(hv.get_actor_rotation().yaw, 2)))
    for c in hv.get_components_by_class(unreal.StaticMeshComponent):
        m = c.static_mesh
        if m is None or 'Pillar' not in m.get_name():
            continue
        b = m.get_bounds()
        p = c.get_world_location()
        s = c.get_world_scale()
        r = c.get_world_rotation()
        q = apply(axes(r.yaw, r.pitch, r.roll), (b.origin.x * s.x, b.origin.y * s.y, b.origin.z * s.z))
        cx, cy = p.x + q[0], p.y + q[1]
        hx, hy = b.box_extent.x * s.x, b.box_extent.y * s.y
        print('PILLAR ' + c.get_name() + ' centre ' + str(round(cx, 1)) + ',' + str(round(cy, 1)) + ' half ' + str(round(hx, 1)) + ',' + str(round(hy, 1)) + ' zbot ' + str(round(p.z + q[2] - b.box_extent.z * s.z, 1)) + ' yaw ' + str(round(r.yaw, 2)))
        print('COLLAR clearance x ' + str(round(HOLE / 2.0 - abs(cx - O[0]) - hx, 1)) + ' y ' + str(round(HOLE / 2.0 - abs(cy - O[1]) - hy, 1)) + ' cm (>= 3 needed; a pillar yaw other than 0 needs the collar turned)')
h = trace_ground(O[0], O[1], O[2] + 5000.0, O[2] - 5000.0, [])
print('GROUND at point 0: ' + str(None if h is None else round(h[0], 1)) + ' (heightmap ' + str(round(O[2], 1)) + ')')
print('ENDING ' + ('none yet: task ENDING 6c places BP_Saskarta_HighVoice (tag Saskarta.HighVoice)' if ending is None else ending.get_actor_label()))
print('MASTCHECK DONE')
'''

GRID9_SRC = r'''
def gridn(a, f, n):
    b = a.static_mesh_component.static_mesh.get_bounds()
    s = a.get_actor_scale3d()
    r = a.get_actor_rotation()
    l = a.get_actor_location()
    ax = axes(r.yaw, r.pitch, r.roll)
    out = []
    ks = [-f + 2.0 * f * k / (n - 1) for k in range(n)]
    for fx in ks:
        for fy in ks:
            q = apply(ax, ((b.origin.x + fx * b.box_extent.x) * s.x, (b.origin.y + fy * b.box_extent.y) * s.y, 0.0))
            out.append((l.x + q[0], l.y + q[1]))
    return out


def grid9(a, f):
    return gridn(a, f, 3)


def door_grade():
    g = -1e12
    for q in GRADE:
        h = trace_ground(q[0], q[1], q[2] + 3000.0, q[2] - 3000.0, [])
        if h is not None:
            g = max(g, h[0])
    return g
'''

LEVEL_BODY = r'''
have = site_actors(SITE)
block_top = {}
for blk in BLOCKS:
    mem = []
    for i in blk['members']:
        a = have.get('SD_' + i)
        if a is None:
            print('LEVEL missing ' + i)
        else:
            mem.append((i, a))
    if len(mem) < len(blk['members']):
        print('LEVEL skip ' + blk['block'] + ': place and settle it first')
        continue
    on = blk.get('base_on')
    if on is not None and on not in block_top:
        print('LEVEL skip ' + blk['block'] + ': its base block ' + on + ' was not levelled in this call')
        continue
    acts = [a for i, a in mem]
    ref = None
    if blk['match'] is not None:
        am = have['SD_' + blk['match']]
        bm = am.static_mesh_component.static_mesh.get_bounds()
        ref = 2.0 * bm.box_extent.z * am.get_actor_scale3d().z
    clear = blk.get('clear_cm')
    zmin = 1e12
    zmax = -1e12
    if on is None:
        for i, a in mem:
            z = a.get_actor_location().z
            for (x, y) in gridn(a, 0.95 if clear is not None else 0.92, 5 if clear is not None else 3):
                h = trace_ground(x, y, z + 3000.0, z - 5000.0, acts)
                if h is not None:
                    zmin = min(zmin, h[0])
                    zmax = max(zmax, h[0])
        base = zmin - blk['sink_cm']
    else:
        base = block_top[on]
    tops = []
    for i, a in mem:
        s = a.get_actor_scale3d()
        b = a.static_mesh_component.static_mesh.get_bounds()
        zs = s.z
        if ref is not None and i != blk['match']:
            zs = ref / (2.0 * b.box_extent.z)
        if clear is not None:
            zs = max(zs, (zmax + clear - base) / (2.0 * b.box_extent.z))
        a.set_actor_scale3d(V(s.x, s.y, zs))
        l = a.get_actor_location()
        a.set_actor_location(V(l.x, l.y, base - (b.origin.z - b.box_extent.z) * zs), False, True)
        tops.append(base + 2.0 * b.box_extent.z * zs)
        piv = 'base' if abs(b.origin.z - b.box_extent.z) < 1.0 else 'offset (check2 z0 is off by ' + str(round((s.x - zs) * (b.origin.z - b.box_extent.z), 1)) + ' cm)'
        print('LEVEL ' + i + ' zscale ' + str(round(zs, 4)) + ' pivot ' + piv)
    top = max(tops)
    block_top[blk['block']] = top
    print('LEVEL ' + blk['block'] + ' base ' + str(round(base, 1)) + ' top ' + str(round(top, 1)) + ' spread ' + str(round(max(tops) - min(tops), 1)))
    if clear is not None:
        print('LEVEL_CHECK ' + blk['block'] + ' top clears the highest ground by ' + str(round(top - zmax, 1)) + ' cm' + (' OK' if top - zmax >= 0.0 else ' BURIED'))
    placed = {}
    for sp in blk['supports']:
        a = have.get('SD_' + sp['id'])
        if a is None:
            print('LEVEL ' + ('skip optional ' if sp.get('optional') else 'missing support ') + sp['id'])
            continue
        a.set_actor_rotation(unreal.Rotator(roll=0.0, pitch=float(sp['pitch']), yaw=float(sp['yaw'])), False)
        o, e = a.get_actor_bounds(False)
        if sp['rule'] == 'on_members':
            zb = top
        elif sp['rule'] == 'on':
            zb = max(placed[k] for k in sp['of'])
        elif sp['rule'] == 'grade':
            zb = door_grade() + sp['offset_cm']
        else:
            gz = -1e12
            for fx in (-0.6, 0.0, 0.6):
                for fy in (-0.6, 0.0, 0.6):
                    h = trace_ground(sp['x'] + fx * e.x, sp['y'] + fy * e.y, top + 500.0, base - 3000.0, [])
                    if h is not None:
                        gz = max(gz, h[0])
            zb = gz - sp['sink_cm']
        l = a.get_actor_location()
        a.set_actor_location(V(l.x + sp['x'] - o.x, l.y + sp['y'] - o.y, l.z + zb + e.z - o.z), False, True)
        placed[sp['id']] = zb + 2.0 * e.z
        print('LEVEL support ' + sp['id'] + ' ' + sp['rule'] + ' bottom ' + str(round(zb, 1)) + ' top ' + str(round(zb + 2.0 * e.z, 1)))
        if sp['rule'] == 'grade':
            # the shutter hangs on the wall face (its xy is the data's): report where it ended up
            o, e = a.get_actor_bounds(False)
            print('SHUTTER_ON_WALL centre ' + str([round(o.x, 1), round(o.y, 1), round(o.z, 1)]) + ' grade ' + str(round(zb - sp['offset_cm'], 1)))
    worst = -1e12
    for i, a in mem:
        l = a.get_actor_location()
        b = a.static_mesh_component.static_mesh.get_bounds()
        zb = l.z + (b.origin.z - b.box_extent.z) * a.get_actor_scale3d().z
        for (x, y) in grid9(a, 0.92):
            if on is None:
                h = trace_ground(x, y, zb + 300.0, zb - 3000.0, acts)
            else:
                h = trace_down(x, y, zb + 30.0, zb - 3000.0, acts)
            if h is not None:
                worst = max(worst, zb - h[0])
    print('LEVEL_CHECK ' + blk['block'] + (' OK' if worst <= 5.0 else ' FLOAT') + ' worst_gap ' + str(round(worst, 1)) + ' cm' + ('' if on is None else ' (on ' + on + ')'))
print('LEVEL DONE')
'''

LINES_BODY = r'''
have = site_actors(SITE)
hv = None
for a in eas.get_all_level_actors():
    if a.get_actor_label() == 'HighVoice':
        hv = a
pil = None
if hv is not None:
    for c in hv.get_components_by_class(unreal.StaticMeshComponent):
        m = c.static_mesh
        if m is not None and 'Pillar' in m.get_name():
            p = c.get_world_location()
            if pil is None or p.z < pil[2]:
                b = m.get_bounds()
                s = c.get_world_scale()
                pil = (p.x + b.origin.x * s.x, p.y + b.origin.y * s.y, p.z + (b.origin.z - b.box_extent.z) * s.z, b.box_extent.x * s.x, b.box_extent.y * s.y)
if pil is None:
    pil = tuple(MAST)
    print('LINES no HighVoice pillar found: using the design values')
gz = door_grade()
mesh = unreal.load_asset(PIPE)
mb = mesh.get_bounds()
mo, me = mb.origin, mb.box_extent


def endp(sp, other):
    x, y = sp['xy_cm']
    if sp['on'] == 'actor_top':
        o, e = have['SD_' + sp['actor']].get_actor_bounds(False)
        return (o.x, o.y, o.z + e.z - sp['sink_cm'])
    if sp['on'] == 'mast':
        dx, dy = other[0] - pil[0], other[1] - pil[1]
        t = min(pil[3] / max(abs(dx), 0.001), pil[4] / max(abs(dy), 0.001))
        return (pil[0] + dx * t, pil[1] + dy * t, pil[2] + sp['up_cm'])
    if sp['on'] == 'plate_bottom':
        return (x, y, gz + PLATE_UP - PLATE_HALF)
    h = trace_ground(x, y, gz + 3000.0, gz - 5000.0, [])
    return (x, y, h[0] + sp['lift_cm'])


for ln in LINES:
    a0 = endp(ln['a'], None)
    p1 = endp(ln['b'], a0)
    dx, dy, dz = p1[0] - a0[0], p1[1] - a0[1], p1[2] - a0[2]
    L = math.sqrt(dx * dx + dy * dy + dz * dz)
    yaw = math.degrees(math.atan2(dy, dx))
    pitch = math.degrees(math.asin(max(-1.0, min(1.0, dz / L))))
    sx = L / (2.0 * me.x)
    sc = ln['section_cm'] / (2.0 * me.y)
    label = 'SD_' + ln['id']
    act = have.get(label)
    if act is None:
        act = eas.spawn_actor_from_object(mesh, V(a0[0], a0[1], a0[2]), unreal.Rotator())
    act.set_actor_rotation(unreal.Rotator(roll=0.0, pitch=pitch, yaw=yaw), False)
    act.set_actor_scale3d(V(sx, sc, sc))
    q = apply(axes(yaw, pitch, 0.0), ((mo.x - me.x) * sx, mo.y * sc, mo.z * sc))
    act.set_actor_location(V(a0[0] - q[0], a0[1] - q[1], a0[2] - q[2]), False, True)
    comp = act.static_mesh_component
    if eal.does_asset_exist(ln['material']):
        comp.set_material(0, unreal.load_asset(ln['material']))
    comp.set_collision_profile_name('NoCollision')
    comp.set_editor_property('ld_max_draw_distance', float(ln['draw_cm']))
    comp.set_editor_property('affect_distance_field_lighting', False)
    act.set_editor_property('tags', [unreal.Name(t) for t in ['SetDress', 'SD_' + SITE, 'SDID_' + ln['id'], 'SDC_line']])
    act.set_actor_label(label)
    act.set_folder_path('Set/' + SITE + '/lines')
    msg = 'LINE ' + ln['id'] + ' L ' + str(round(L, 1)) + ' pitch ' + str(round(pitch, 1)) + ' from ' + str([round(v) for v in a0]) + ' to ' + str([round(v) for v in p1])
    if ln['role'] == 'conduit':
        gaps = []
        for t in (0.1, 0.5, 0.9):
            x, y, z = a0[0] + dx * t, a0[1] + dy * t, a0[2] + dz * t
            h = trace_ground(x, y, z + 300.0, z - 3000.0, [act])
            if h is not None:
                gaps.append(round(z - ln['section_cm'] / 2.0 - h[0], 1))
        msg = msg + ' bottom_gaps ' + str(gaps) + (' OK' if len(gaps) > 0 and max(gaps) <= 5.0 else ' FLOAT')
    print(msg)
print('LINES DONE')
'''

HOOKS_BODY = r'''
have = site_actors(SITE)
hv = None
for a in eas.get_all_level_actors():
    for t in a.tags:
        if str(t) == 'Saskarta.HighVoice':
            hv = a
gz = door_grade()
if hv is None:
    print('HOOKS no actor tagged Saskarta.HighVoice: task ENDING step 6c places BP_Saskarta_HighVoice first. Nothing set.')
elif gz < -1e11:
    print('HOOKS no ground under the door grade points: load the site first. Nothing set.')
else:
    hv.modify()
    comps = {}
    for c in hv.get_components_by_class(unreal.SceneComponent):
        comps[c.get_name()] = c
    print('HOOKS components ' + str(sorted(comps.keys())))
    h = trace_ground(MB[0], MB[1], MB[2] + 3000.0, MB[2] - 3000.0, [])
    if 'MastBase' in comps:
        comps['MastBase'].set_world_location_and_rotation(V(MB[0], MB[1], MB[2] if h is None else h[0]), unreal.Rotator(), False, False)
    pz = gz + PLATE_UP
    pl = comps.get('Plate')
    if pl is not None:
        if pl.static_mesh is None:
            pl.set_static_mesh(unreal.load_asset(PLATE_MESH))
        b = pl.static_mesh.get_bounds()
        s = (PLATE_SIZE[0] / (2.0 * b.box_extent.x), PLATE_SIZE[1] / (2.0 * b.box_extent.y), PLATE_SIZE[2] / (2.0 * b.box_extent.z))
        pl.set_world_scale3d(V(s[0], s[1], s[2]))
        q = apply(axes(PLATE_YAW, 0.0, 0.0), (b.origin.x * s[0], b.origin.y * s[1], b.origin.z * s[2]))
        pl.set_world_location_and_rotation(V(PLATE[0] - q[0], PLATE[1] - q[1], pz - q[2]), unreal.Rotator(roll=0.0, pitch=0.0, yaw=PLATE_YAW), False, False)
        if eal.does_asset_exist(BRASS):
            pl.set_material(0, unreal.load_asset(BRASS))
        print('HOOKS Plate centre ' + str([round(PLATE[0], 1), round(PLATE[1], 1), round(pz, 1)]) + ' yaw ' + str(PLATE_YAW))
    hs = trace_ground(STAND[0], STAND[1], pz + 3000.0, pz - 3000.0, [])
    sz = (pz - PLATE_UP) if hs is None else hs[0]
    if 'StandPoint' in comps:
        comps['StandPoint'].set_world_location_and_rotation(V(STAND[0], STAND[1], sz + HALF), unreal.Rotator(roll=0.0, pitch=0.0, yaw=STAND_YAW), False, False)
        print('HOOKS StandPoint feet ' + str([round(STAND[0], 1), round(STAND[1], 1), round(sz, 1)]) + ' capsule +' + str(HALF) + ' yaw ' + str(STAND_YAW))
    hq = trace_ground(SEAT[0], SEAT[1], pz + 3000.0, pz - 3000.0, [])
    if 'SeatPoint' in comps and hq is not None:
        comps['SeatPoint'].set_world_location_and_rotation(V(SEAT[0], SEAT[1], hq[0] + SEAT_EYE), unreal.Rotator(roll=0.0, pitch=SEAT_PITCH, yaw=SEAT_YAW), False, False)
        print('HOOKS SeatPoint ' + str([round(SEAT[0], 1), round(SEAT[1], 1), round(hq[0] + SEAT_EYE, 1)]))
    print('HOOKS package ' + hv.get_package().get_name())
    if MARK:
        label = 'SD_' + SITE + '_mark'
        mk = have.get(label)
        mesh = unreal.load_asset(MARK_MESH)
        if mk is None:
            mk = eas.spawn_actor_from_object(mesh, V(PLATE[0], PLATE[1], pz), unreal.Rotator())
        mb = mesh.get_bounds()
        e = mb.box_extent
        yaw, pitch = PLATE_YAW, 0.0
        thin = min(e.x, e.y, e.z)
        if thin == e.z:
            pitch = 90.0
            dia = max(e.x, e.y)
        elif thin == e.y:
            yaw = PLATE_YAW - 90.0
            dia = max(e.x, e.z)
        else:
            dia = max(e.y, e.z)
        sc = MARK_CM / (2.0 * dia)
        mk.set_actor_rotation(unreal.Rotator(roll=0.0, pitch=pitch, yaw=yaw), False)
        mk.set_actor_scale3d(V(sc, sc, sc))
        n = (math.cos(math.radians(PLATE_YAW)), math.sin(math.radians(PLATE_YAW)))
        off = PLATE_SIZE[0] / 2.0 + thin * sc
        q = apply(axes(yaw, pitch, 0.0), (mb.origin.x * sc, mb.origin.y * sc, mb.origin.z * sc))
        mk.set_actor_location(V(PLATE[0] + n[0] * off - q[0], PLATE[1] + n[1] * off - q[1], pz - q[2]), False, True)
        mk.static_mesh_component.set_collision_profile_name('NoCollision')
        if eal.does_asset_exist(BRASS):
            mk.static_mesh_component.set_material(0, unreal.load_asset(BRASS))
        mk.set_editor_property('tags', [unreal.Name(t) for t in ['SetDress', 'SD_' + SITE, 'SDID_' + SITE + '_mark', 'SDC_line']])
        mk.set_actor_label(label)
        mk.set_folder_path('Set/' + SITE + '/lines')
        print('HOOKS mark: greybox ring ' + str(MARK_CM) + ' cm on the plate')
print('HOOKS DONE')
'''

DOORCHECK_BODY = r"""
have = site_actors(SITE)
a = have.get('SD_' + ARCH)


def through(p0, p1, target):
    ign = []
    for _ in range(4):
        h = hit_of(syslib.line_trace_single(world, V(p0[0], p0[1], p0[2]), V(p1[0], p1[1], p1[2]),
                                            unreal.TraceTypeQuery.TRACE_TYPE_QUERY1, True, ign,
                                            unreal.DrawDebugTrace.NONE, True))
        if h is None:
            return False
        t = h.to_tuple()
        if not t[0]:
            return False
        if t[HIT_ACTOR] == target:
            return True
        ign.append(t[HIT_ACTOR])
    return False


if a is None:
    print('DOOR no actor SD_' + ARCH + ': place and level the hut first')
else:
    b = a.static_mesh_component.static_mesh.get_bounds()
    s = a.get_actor_scale3d()
    r = a.get_actor_rotation()
    l = a.get_actor_location()
    ax = axes(r.yaw, r.pitch, r.roll)
    ex, ey, ez = b.box_extent.x * s.x, b.box_extent.y * s.y, b.box_extent.z * s.z
    ox, oy, oz = b.origin.x * s.x, b.origin.y * s.y, b.origin.z * s.z

    def ray(u, z):
        q0 = apply(ax, (ox + u, oy - ey - 20.0, oz - ez + z))
        q1 = apply(ax, (ox + u, oy + ey + 20.0, oz - ez + z))
        return (l.x + q0[0], l.y + q0[1], l.z + q0[2]), (l.x + q1[0], l.y + q1[1], l.z + q1[2])
    run = {}
    for zc in HEIGHTS:
        opens = []
        k = -ex + 2.5
        while k < ex:
            p0, p1 = ray(k, zc)
            if not through(p0, p1, a):
                opens.append(k)
            k += 5.0
        lo, hi = None, None
        for u in sorted(opens, key=lambda v: abs(v)):
            if lo is None and abs(u) <= 5.0:
                lo, hi = u, u
        if lo is not None:
            while lo - 5.0 in opens:
                lo = lo - 5.0
            while hi + 5.0 in opens:
                hi = hi + 5.0
            run[zc] = (lo - 2.5, hi + 2.5)
        print('DOOR row ' + str(zc) + ' cm up: ' + ('solid across the centre' if lo is None else 'open ' + str(round(lo - 2.5, 1)) + ' .. ' + str(round(hi + 2.5, 1)) + ' cm'))
    top = None
    zc = 2.5
    while zc < 2.0 * ez:
        p0, p1 = ray(0.0, zc)
        if not through(p0, p1, a):
            top = zc
        elif top is not None:
            break
        zc += 5.0
    print('DOOR centre open up to ' + str(top) + ' cm over the arch bottom (the plinth top, the floor)')
    bad = 0
    n = 0
    PZ = door_grade() + PLATE_UP - (l.z + oz - ez)
    u = PU - PH - 5.0
    while u <= PU + PH + 5.01:
        z = PZ - PH - 5.0
        while z <= PZ + PH + 5.01:
            p0, p1 = ray(u, z)
            n += 1
            if not through(p0, p1, a):
                bad += 1
            z += 10.0
        u += 5.0
    print('PLATE ' + ('ON_JAMB OK' if bad == 0 else 'OVERHANGS the opening at ' + str(bad) + ' of ' + str(n) + ' samples') + ' (plate u ' + str(PU) + ' +- ' + str(PH) + ' cm, 5 cm margin)')
    w100 = run.get(100.0)
    if w100 is not None and top is not None:
        print('DOOR_ARGS --door-w ' + str(round((w100[1] - w100[0]) / 100.0, 2)) + ' --door-h ' + str(round(top / 100.0, 2)) + ' (opening centre u ' + str(round((w100[0] + w100[1]) / 2.0, 1)) + ' cm)')
print('DOORCHECK DONE')
"""

HOOKS_SAVE_BODY = r'''
hv = None
for a in eas.get_all_level_actors():
    for t in a.tags:
        if str(t) == 'Saskarta.HighVoice':
            hv = a
if hv is None:
    print('HOOKS_SAVE no ending actor')
else:
    ok = unreal.EditorLoadingAndSavingUtils.save_packages([hv.get_package()], True)
    print('HOOKS_SAVE ' + hv.get_package().get_name() + ' ok=' + str(ok))
print('HOOKS_SAVE DONE')
'''


def custom_step(step, argv):
    """This set's own editor steps, sent through place_setdress.py's Runner (PIE check, banned words, 5 s scripts)."""
    import place_setdress as ps
    ap = argparse.ArgumentParser(prog='v10_high_voice.py ' + step)
    ap.add_argument('--owner', default=os.environ.get('SETDRESS_OWNER', ''))
    ap.add_argument('--no-gate-check', action='store_true')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--mark', action='store_true', help='hooks: also place the greybox ring on the plate')
    ap.add_argument('--port', type=int, default=int(os.environ.get('HAYBA_PORT', 52342)))
    args = ap.parse_args(argv)
    doc = json.load(open(OUT_JSON, encoding='utf8'))
    hk = doc['story_hooks']
    grade = [p + [z] for p, z in zip(doc['interior_frame']['grade_points_cm'], doc['interior_frame']['grade_z_cm'])]
    if step in ('level', 'lines', 'hooks', 'hooks-save'):
        ps.gate_check(argparse.Namespace(owner=args.owner, dry_run=args.dry_run, no_gate_check=args.no_gate_check), 'place')
    R = ps.Runner(args)
    st = ps.read_state(SID)
    mb = hk['MastBase_cm']
    if step == 'mastcheck':
        _, L, W = collar_rect()
        R.send('%s_mastcheck' % SID, ps.build_script(MASTCHECK_BODY, O=mb, HOLE=round((L - W) * 100, 1)))
        return
    if step == 'doorcheck':
        arch = [b for b in doc['level_blocks'] if b['block'] == 'hut'][0]['match']
        R.send('%s_doorcheck' % SID, ps.build_script(GRID9_SRC + DOORCHECK_BODY, SITE=SID, ARCH=arch, GRADE=grade,
                                                     HEIGHTS=[30.0, 100.0, 160.0, 200.0, 240.0, 280.0],
                                                     PU=round(doc['interior_frame']['plate']['local_y'] * 100.0, 1),
                                                     PH=PLATE_HALF_M * 100.0, PLATE_UP=PLATE_UP_M * 100.0))
        print('doorcheck: if PLATE OVERHANGS or DOOR_ARGS differ from the assumed %.2f x %.2f m, regenerate with '
              '`v10_high_voice.py --door-w W --door-h H [--plate-y Y]` (and rerun s26_high_voice_hut.py) before lines, '
              'ground and hooks' % (DOOR_W, DOOR_H))
        return
    if step == 'level':
        R.send('%s_level' % SID, ps.build_script(GRID9_SRC + LEVEL_BODY, SITE=SID, BLOCKS=doc['level_blocks'], GRADE=grade))
    elif step == 'lines':
        lines = [{k: v for k, v in ln.items() if k != 'note'} for ln in doc['lines']]
        mast = [O_CM[0], O_CM[1], mb[2] - MAST_SINK_CM, PILLAR_HALF_CM[0], PILLAR_HALF_CM[1]]
        for i in range(0, len(lines), 4):
            R.send('%s_lines' % SID, ps.build_script(GRID9_SRC + LINES_BODY, SITE=SID, LINES=lines[i:i + 4], GRADE=grade,
                                                     PIPE=EA_PIPE, MAST=mast, PLATE_UP=PLATE_UP_M * 100, PLATE_HALF=PLATE_HALF_M * 100))
    elif step == 'hooks':
        pl, sp, se = hk['Plate'], hk['StandPoint'], hk['SeatPoint']
        out = R.send('%s_hooks' % SID, ps.build_script(
            GRID9_SRC + HOOKS_BODY, SITE=SID, GRADE=grade, MB=mb, PLATE=pl['centre_cm'], PLATE_YAW=pl['yaw'],
            PLATE_SIZE=pl['size_cm'], PLATE_UP=PLATE_UP_M * 100, PLATE_MESH=PLATE_MESH, BRASS=BRASS, STAND=sp['feet_cm'],
            STAND_YAW=sp['yaw'], HALF=HALF_HEIGHT_CM, SEAT=se['cm'], SEAT_EYE=SEAT_EYE_CM, SEAT_YAW=SEAT_YAW,
            SEAT_PITCH=SEAT_PITCH, MARK=bool(args.mark), MARK_MESH=MARK_MESH, MARK_CM=34.0))
        for line in (out or '').splitlines():
            if line.startswith('HOOKS package '):
                st['ending_package'] = line.split(' ', 2)[2].strip()
    elif step == 'hooks-save':
        pkg = st.get('ending_package')
        if not pkg:
            raise SystemExit('run hooks first (it records the ending actor package)')
        path = os.path.join(ROOT, 'Content', pkg[len('/Game/'):] + '.uasset')
        if os.path.exists(path) and not os.access(path, os.W_OK):
            raise SystemExit('%s is read-only on disk (committed-uassets-are-read-only memory note): make it writable '
                             'first; nothing sent' % path)
        R.send('%s_hooks_save' % SID, ps.build_script(HOOKS_SAVE_BODY))
        return
    if not args.dry_run:
        st['dirty'] = True          # check2 must run again before `save`
        ps.write_state(SID, st)


def run_editor(argv, materials=False):
    """Run a place_setdress.py step (or build_setdress_materials.py) with the V2 site file swapped for V10.json."""
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
    if step == 'capture' and '--views' not in rest:
        rest += ['--views', 'carrier_a,carrier_b,carrier_c,orbit_a,orbit_b,orbit_c,contact,high34,far300,seat,mastup']
    sys.argv = ['place_setdress.py', step] + ([] if step in ('list', 'probe') else [SID]) + rest
    ps.main()


def main():
    if len(sys.argv) > 1 and sys.argv[1] == 'editor':
        return run_editor(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == 'materials':
        return run_editor(sys.argv[2:], materials=True)
    if len(sys.argv) > 1 and sys.argv[1] in ('mastcheck', 'doorcheck', 'level', 'lines', 'hooks', 'hooks-save'):
        return custom_step(sys.argv[1], sys.argv[2:])
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--no-plot', action='store_true')
    ap.add_argument('--png', default=OUT_PNG, help='where the plot goes (default docs/world/story_sets/V10.png)')
    ap.add_argument('--door-w', type=float, help='the measured door opening width, m (doorcheck DOOR_ARGS)')
    ap.add_argument('--door-h', type=float, help='the measured clear door height over the plinth, m (doorcheck DOOR_ARGS)')
    ap.add_argument('--plate-y', type=float, help='the plate centre on the arch, hut y m (default -1.05, the left jamb)')
    args = ap.parse_args()
    global DOOR_W, DOOR_H, DOOR_MEASURED, PLATE_Y
    meas = json.load(open(MEASURED_JSON, encoding='utf8')) if os.path.exists(MEASURED_JSON) else {}
    if args.door_w is not None:
        meas['door_w'] = args.door_w
    if args.door_h is not None:
        meas['door_h'] = args.door_h
    if args.plate_y is not None:
        meas['plate_y'] = args.plate_y
    if args.door_w is not None or args.door_h is not None or args.plate_y is not None:
        meas['source'] = 'v10_high_voice.py doorcheck (DOOR_ARGS), recorded by --door-w/--door-h/--plate-y'
        with open(MEASURED_JSON, 'w', encoding='utf8') as fh:
            json.dump(meas, fh, indent=1)
    if 'door_w' in meas or 'door_h' in meas:
        DOOR_W, DOOR_H, DOOR_MEASURED = meas.get('door_w', DOOR_W), meas.get('door_h', DOOR_H), True
    PLATE_Y = meas.get('plate_y', PLATE_Y)
    G, S, Hk, recs, by_item, grecs, H, lines = build()
    notes, bad = checks(G, S, recs, grecs, H, lines)
    site = write(G, S, Hk, recs, by_item, grecs, H, lines, notes, bad)
    c = site['counts']
    print('%s (%s): %d placements, %d actors (ISM groups and lines counted once each), %d ISM instances, %d decals, %d lines'
          % (SID, SET, c['placements'], c['actors'], c['ism_instances'], c['decals'], c['lines']))
    for n in notes:
        print(' ', n)
    if not args.no_plot:
        print('plot', plot(G, S, recs, grecs, H, lines, notes, args.png))
    print('wrote', OUT_JSON)
    if bad:
        print('VIOLATIONS:')
        for b in bad:
            print('  ', b)
        sys.exit(1)


if __name__ == '__main__':
    main()
