"""V7 the Last Waystation (road site S19_LastWaystation): the story set, composed with the set-dressing V2 method.

    python Tools/World/story_sets/v7_waystation.py                  # write V7.json + the plot, print the checks
    python Tools/World/story_sets/v7_waystation.py --no-plot        # data and checks only
    python Tools/World/story_sets/v7_waystation.py editor <step> [place_setdress args]
          # runs Tools/World/place_setdress.py <step> V7_LastWaystation --v2 against Tools/World/story_sets/V7.json
    python Tools/World/story_sets/v7_waystation.py materials variants
          # runs Tools/World/build_setdress_materials.py variants V7_LastWaystation against V7.json
    python Tools/World/story_sets/v7_waystation.py rig|rigcheck|cinshots [--owner O] [--dry-run]
          # this set's own editor steps: the dead spare (SK_Carrier, shutdown end pose), the plaque lettering,
          # the flag banner on its pole; a read-only measure of them; the three CIN_11 frames at their lenses

Story (docs/story/storyline.md section 7 V7, story-events.json B11_LAST_WAYSTATION, CINEMATICS.md section 3):
B11 fires on a pass at road 3,400 and plays CIN_11_WAYSTATION (18 s, the pawn stops). Shot 1 is the carrier's
POV turning 70 deg left with a digital zoom to 50 deg: "the lean-to, the empty eyes of the spare in its cradle,
the plaque legible" under CV_WAYSTATION_01 "Waystation three. Replacement carriers: none." Shot 2 looks from
behind the cradle, low, at our carrier and capsule by the road, the spare's shoulder soft in the foreground
(CV_WAYSTATION_03 "Unit in cradle. No response."). Shot 3 racks from the plaque, TAKE WHAT IT CARRIED., to the
palm-in-a-ring mark on the capsule. Then the Elder's tape (RADIO_B11_01..03, the hinge). CP2_WAYSTATION.

The place: the waystation's berth row. A dry-stone back wall (AB fort-wall pieces) retains the slope on the
inside of the bend; two tarp lean-tos stand against it. Under the down-road one, the spare stands dead in its
riveted iron cradle (B01_dock01), eyes dark, facing the road. Under the up-road one the second cradle is EMPTY
(no replacement), with the unclaimed loads (crates, a clay fuel jar, a rope coil) beside it. In the yard: a
cold fire ring with a log and a stone to sit on, the unlit lantern set down on the stone. At the spur mouth by
the road: the plaque, an iron-plated board between two posts, the rule on its road face and TAKE WHAT IT
CARRIED. on its back (read by whoever leaves the berth with the load; shot 3 reads it). A woodpile closes the
wall's up-road end, a rock outcrop its down-road end. The flag on its pole with a stone footing stands on the
rise at the bend, on the line of the long straight. Optional (after the Tripo import): the keeper's stone hut
on the terrace behind the wall.

Offline only: nothing here talks to Unreal unless an editor step is run (and those go through
place_setdress.py's Runner: PIE check, banned words, 5 s scripts, the editor gate).
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

OUT_JSON = os.path.join(HERE, 'V7.json')
OUT_PNG = os.path.join(ROOT, 'docs', 'world', 'story_sets', 'V7.png')
SITES_V1_JSON = os.path.join(WORLD, 'setdress_sites.json')
SID = 'V7_LastWaystation'       # own site id and tag (SD_V7_LastWaystation): the S19 outpost lanes never clear it
ROAD_SITE = 'S19_LastWaystation'
SET = 'V7'
S0 = 3400.0                     # B11_LAST_WAYSTATION pass trigger, road m (UE 1,705.7): the site origin
CARRIER_MS = 5.0                # story-events.json curves.carrier_speed_cms
EYE_M = (1.55, 1.22)            # probe_cin01 (95 cm over the capsule centre: the CIN plans' eye_z) / probe_ending + CameraBoom
POV_YAW_LOCAL = -70.0           # CIN_11 shot 1: the yaw eases 70 deg left (build_cinematics.plan_cin11)
POV_PITCH_PLAN = -4.0           # plan_cin11 CIN11_S1 pitch
FILMBACK = 23.76


def hfov_mm(f):
    return math.degrees(2 * math.atan(FILMBACK / 2 / f))


HFOV_POV, HFOV_ZOOM = 90.0, 50.0
HFOV_S2, HFOV_S3 = hfov_mm(50.0), hfov_mm(85.0)
# the carrier (task-CARRIER-report: 131 x 160 x 105 cm, eyes on mesh +Y, wheels r 25 at mesh z 0) and the capsule
# on its drawbar (SK_CarrierFull bounds 163 x 474 x 166 cm; probe_ending capsule_root_local -260 cm)
CARRIER = dict(half_len=0.80, half_wid=0.655, h=1.05)
CAPSULE = dict(c=-2.75, half_len=1.15, half_wid=0.815, z0=0.35, z1=1.66)
MARK = (-2.75, 0.83, 0.95)      # the palm-in-a-ring on the capsule's LEFT flank (the set side): u from the carrier, v, z
STOPS_M = (0.0, 2.0)            # stop_pawn from 5 m/s with BrakingDecelerationWalking 600 cm/s2: 0 .. 2.1 m past 3,400
LATERALS_M = (-2.0, 0.0, 2.0)   # where the player drove on the 9 m ribbon (the origin is the pawn projected on the spline)
CLEAR_M = 5.0                   # road centreline -> footprint edge (build_setdress_sites.py CLEAR_M)
V1_CLEAR = ['S19_LastWaystation_%03d' % i for i in (0, 1, 2, 3, 4, 5, 6, 7, 15)]   # stand-ins + the V7 context pieces
STELE_24 = (369999.2, 375365.2)  # Tools/Story/place_steles.py plan(): Stele_WayStone_24, on the bend

CAT = setdress_catalog.load()
EXTRA = {   # meshes not in the catalog
    'PH_lantern_glass': dict(path='/Game/Pallbearer/PolyHaven/Lantern_01/Lantern_01_2k/StaticMeshes/Lantern_01_glass',
                             cat='prop', size_cm=[7.0, 7.0, 7.0]),
    # SourceArt/Tripo/manifest.json stone_mud_hut (t2 stone_hut): import size 600 x 475.6 x 424.2 cm; Tools/Tripo/IMPORT.md path
    'T2_stone_hut': dict(path='/Game/SaskartaGaea/Environment/Tripo02/SM_T2_stone_hut', cat='building',
                         size_cm=[600.0, 475.6, 424.2]),
    'SK_Carrier': dict(path='/Game/SaskartaGaea/Characters/Carrier/SK_Carrier', cat='rig', size_cm=[131.0, 160.0, 105.0]),
}
SPARE_ANIM = '/Game/SaskartaGaea/Characters/Carrier/Anims/A_Carrier_Shutdown'   # 5.0 s: body drops, mast folds, eyes dark
SPARE_ANIM_POS = 4.95
TEXT_FRONT = [['LEAVE THE', 'BEARER'], ['WHERE IT', 'RESTS.'], ['TAKE WHAT', 'IT CARRIED.']]   # one pair per iron panel
TEXT_BACK = [None, None, ['TAKE WHAT', 'IT CARRIED.']]
TEXT_WORLD_CM = 9.0             # TextRender world size (cap height ~0.7 x): 6.3 cm capitals
TEXT_RGB = (226, 214, 190)      # pale paint on the dark iron plate
PANEL_Z = (0.745, 0.500, 0.255)  # panel centres, fraction of the board's height from its bottom (sign02 preview)
LINE_DZ_CM = 5.5                # half the spacing of a panel's two lines


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
    """The heightmap and the road polyline in a site frame: u m along travel from S0, v m LEFT of travel."""

    def __init__(self, s0=S0):
        self.T = brp.Terrain(brp.HEIGHTMAP)
        self.R = brp.Road(brp.SPLINE_POINTS_CM)
        self.P = self.R.P[:, :2] / 100.0
        k, _ = self.R.locate(s0)
        d = self.R.P[k + 1, :2] - self.R.P[k, :2]
        self.f = d / np.linalg.norm(d)
        self.l = np.array([self.f[1], -self.f[0]])          # left of travel (UE top view: right = (-dy, dx))
        self.o = self.R.xy(s0) / 100.0
        self.road_yaw = math.degrees(math.atan2(self.f[1], self.f[0]))
        self.z0 = self.z(*self.o)                           # the road surface at the origin (CIN local +Z = 0)

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

    def grad_uv(self, u, v, r=4.0):
        """Least-squares ground plane over a disc of radius r (m), as (dz/du, dz/dv)."""
        g = np.arange(-r, r + 1e-6, 0.5)
        du, dv = np.meshgrid(g, g)
        m = du ** 2 + dv ** 2 <= r * r
        du, dv = du[m], dv[m]
        z = np.array([self.zuv(u + a, v + b) for a, b in zip(du, dv)])
        A = np.stack([np.ones_like(du), du, dv], axis=1)
        c = np.linalg.lstsq(A, z, rcond=None)[0]
        return float(c[1]), float(c[2])

    def slope_deg(self, u, v):
        gu, gv = self.grad_uv(u, v, r=1.0)
        return math.degrees(math.atan(math.hypot(gu, gv)))

    def yaw_of(self, du, dv):
        """World yaw (deg) of the site-frame direction (du, dv)."""
        w = du * self.f + dv * self.l
        return math.degrees(math.atan2(w[1], w[0])) % 360.0

    def dir_of(self, yaw):
        """Site-frame unit vector of a world yaw."""
        w = np.array([math.cos(math.radians(yaw)), math.sin(math.radians(yaw))])
        return float(w @ self.f), float(w @ self.l)

    def road_dist(self, u, v):
        x, y = self.world(u, v)
        a, b = self.P[:-1], self.P[1:]
        ab = b - a
        p = np.array([x, y])
        t = np.clip(np.sum((p - a) * ab, axis=1) / np.sum(ab * ab, axis=1), 0, 1)
        q = a + ab * t[:, None]
        return float(np.min(np.linalg.norm(p - q, axis=1)))

    def road_uv(self, s):
        return self.local(*(self.R.xy(s) / 100.0))


# ---------------------------------------------------------------------------- the composition

SETTLE = {   # SETDRESS_V2.md section 3 contact classes -> the place_setdress settle config
    'rigid': dict(mode='trace', max_tilt_deg=0, rand_tilt_deg=0, z_rule='min'),
    'lie': dict(mode='trace', max_tilt_deg=25, rand_tilt_deg=6, z_rule='mean'),
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
        self.keep_clear = []        # site-frame rectangles (centre, axis, half extents) no stone or shrub may land in
        self.rng = random.Random(7)

    def add(self, key, u, v, group, contact, scale=1.0, yaw=0.0, sink_cm=6, ism=False, block=None, pitch=0.0,
            roll=0.0, stack=False, attach=False, drop_cm=0, rand_tilt=None, role='', material_set=None,
            settle_kind=None, optional=False, fallback=None, collision=None, rig=False):
        G = self.G
        path, cat, size = asset(key)
        x, y = G.world(u, v)
        cfg = dict(SETTLE[settle_kind or contact]) if not rig else dict(mode='none', max_tilt_deg=0, rand_tilt_deg=0,
                                                                          z_rule='mean')
        if rand_tilt is not None:
            cfg['rand_tilt_deg'] = rand_tilt
        if attach:
            cfg = dict(mode='none', max_tilt_deg=0, rand_tilt_deg=0, z_rule='mean')
        settle = dict(mode=cfg['mode'], sink_cm=int(round(sink_cm)), max_tilt_deg=cfg['max_tilt_deg'],
                      rand_tilt_deg=cfg['rand_tilt_deg'], z_rule=cfg['z_rule'], drop_cm=int(drop_cm), z_offset_cm=0)
        it = dict(key=key, asset=path, kind='SM', cat=cat, u=u, v=v, x=x, y=y, yaw=round(yaw % 360.0, 2), pitch=pitch,
                  roll=roll, scale=round(scale, 3), size_m=[round(s * scale / 100.0, 3) for s in size], settle=settle,
                  group=group, ism=ism, stack=stack, attach=attach, contact=contact, block=block, role=role,
                  material_set=material_set, optional=optional, fallback=fallback, collision=collision, rig=rig)
        self.items.append(it)
        return it

    def patch(self, surface, u, v, yaw_local, length, width, strength, shape='ellipse', sort=0, role=''):
        """yaw_local: degrees in the site frame (0 = +u, 90 = +v)."""
        self.ground.append(dict(surface=surface, u=u, v=v, yaw=yaw_local, length=length, width=width, strength=strength,
                                shape=shape, sort=sort, role=role))

    def path(self, pts, width, strength, role):
        self.lanes.append(dict(pts=pts, width=width, role=role))
        for (u0, v0), (u1, v1) in zip(pts[:-1], pts[1:]):
            L = math.hypot(u1 - u0, v1 - v0)
            self.patch('path', (u0 + u1) / 2, (v0 + v1) / 2, math.degrees(math.atan2(v1 - v0, u1 - u0)), L + width, width,
                       strength, 'capsule', 2, role)

    def on_lane(self, u, v, margin=0.3):
        for ln in self.lanes:
            for (u0, v0), (u1, v1) in zip(ln['pts'][:-1], ln['pts'][1:]):
                du, dv = u1 - u0, v1 - v0
                t = max(0.0, min(1.0, ((u - u0) * du + (v - v0) * dv) / (du * du + dv * dv)))
                if math.hypot(u0 + t * du - u, v0 + t * dv - v) < ln['width'] / 2 + margin:
                    return True
        return False

    def in_keep_clear(self, u, v, margin=0.0):
        for (cu, cv), (eu, ev), (hu, hv) in self.keep_clear:
            du, dv = u - cu, v - cv
            a = du * eu + dv * ev
            b = -du * ev + dv * eu
            if abs(a) <= hu + margin and abs(b) <= hv + margin:
                return True
        return False


def site_axes(G, it):
    """Site-frame unit vectors of the item's local X and Y (UE: Y is X turned +90 deg in yaw)."""
    return G.dir_of(it['yaw']), G.dir_of(it['yaw'] + 90.0)


def obb_uv(G, it, pad=0.0):
    ax, ay = site_axes(G, it)
    hx, hy = it['size_m'][0] / 2 + pad, it['size_m'][1] / 2 + pad
    if abs(it['roll']) > 45:
        hy = it['size_m'][2] / 2 + pad
    return [(it['u'] + sx * hx * ax[0] + sy * hy * ay[0], it['v'] + sx * hx * ax[1] + sy * hy * ay[1])
            for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]


def samples9(G, it):
    ax, ay = site_axes(G, it)
    hx, hy = it['size_m'][0] / 2, it['size_m'][1] / 2
    return [(it['u'] + fx * hx * ax[0] + fy * hy * ay[0], it['v'] + fx * hx * ax[1] + fy * hy * ay[1])
            for fx in (-0.92, 0.0, 0.92) for fy in (-0.92, 0.0, 0.92)]


def predicted(G, it):
    """The settle the editor will do (place_setdress.settle_pose / setdress_contact.offline_reports rules):
    rigid: plumb, bottom = lowest of the 9 footprint samples - sink; lie/rest: on the mean ground - sink."""
    gz = [G.zuv(u, v) for u, v in samples9(G, it)]
    s = it['settle']['sink_cm'] / 100.0
    if it['contact'] == 'rigid':
        bottom = min(gz) - s
    else:
        bottom = sum(gz) / len(gz) - s
    h = it['size_m'][1] if abs(it['roll']) > 45 else it['size_m'][2]
    return dict(bottom=bottom, top=bottom + h, gmin=min(gz), gmax=max(gz), gmean=sum(gz) / len(gz),
                buried_max=max(gz) - bottom, gaps=[round((bottom - g) * 100, 1) for g in gz])


def polar(bearing_deg, dist):
    """Site point at a bearing (deg, 0 = +u along travel, 90 = +v left) and a distance from the origin."""
    return dist * math.cos(math.radians(bearing_deg)), dist * math.sin(math.radians(bearing_deg))


# the layout parameters (tuned against the CIN_11 frames: see frames() and V7.md section 4)
LAYOUT = dict(
    spare_bearing=79.0, spare_dist=12.8,     # the spare's cradle centre from the shot-1 eye (the origin)
    plaque_bearing=58.5, plaque_dist=6.9,    # the plaque board centre
    fire_bearing=97.0, fire_dist=8.6,        # the cold fire ring
    flag_uv=(13.2, 8.6),                     # the flag pole on the rise at the bend
    wall_vis_m=2.40,                         # visible height of the back wall on the yard side
    sign_scale=1.20,
)
A1, A_GAP = -2.20, 0.40         # bay 1 centre along the row (a, m); the gap between the two canopies
BC, BS = 1.72, 1.82             # cradle and spare centres, m out from the wall face
TARP1, TARP2 = 'MV_Annex_Tarp_01', 'MV_Annex_Tarp_02'


def compose(G, L=LAYOUT, with_hut=True):
    S = Site(G)
    rng = S.rng
    J = polar(L['spare_bearing'], L['spare_dist'])
    gu, gv = G.grad_uv(J[0], J[1] - 1.0, r=5.0)
    th = math.atan2(gu, -gv)                          # the contour (perpendicular to the gradient), toward +u
    if math.cos(th) < 0:
        th += math.pi
    e = (math.cos(th), math.sin(th))                  # along the row (up-road)
    n = (math.sin(th), -math.cos(th))                 # out of the row, toward the road (downhill)
    if n[1] > 0:
        n = (-n[0], -n[1])
    W0 = (J[0] - A1 * e[0] - BC * n[0], J[1] - A1 * e[1] - BC * n[1])

    def Y(a, b):
        return W0[0] + a * e[0] + b * n[0], W0[1] + a * e[1] + b * n[1]
    yaw_e = G.yaw_of(*e)
    yaw_n = G.yaw_of(*n)
    S.frame = dict(W0=W0, e=e, n=n, Y=Y, yaw_e=yaw_e, yaw_n=yaw_n, J=J)

    # 1. the back wall: four AB fort-wall pieces in one straight run along the contour, plumb, sunk so ~2.4 m shows on
    #    the yard side; the uphill ground stands against their back (a retaining wall). One block: the joints are exempt.
    wl = CAT['AB_Fort_Wall_Mid']['size_cm']
    piece, thick = wl[1] / 100.0, wl[0] / 100.0
    a0 = -6.40
    S.frame['wall_a'] = (a0, a0 + 4 * piece)
    for i in range(4):
        a = a0 + (i + 0.5) * piece
        u, v = Y(a, -thick / 2)
        S.add('AB_Fort_Wall_Mid', u, v, 'wall', 'rigid', yaw=yaw_n, sink_cm=round((wl[2] / 100.0 - L['wall_vis_m']) * 100),
              block='wall', material_set='stone', role='back wall %d of 4 (retains the cut; the lean-tos lean on it)' % (i + 1))

    # 2. bay 1, down-road: the dead spare's berth. Tarp lean-to (4 posts) over the riveted iron cradle; the spare
    #    between the roller towers, facing the road. One block per bay (the canopy box holds the cradle by design).
    t1 = CAT[TARP1]['size_cm']
    b_t1 = 0.12 + t1[1] / 200.0
    S.add(TARP1, *Y(A1, b_t1), 'bay1', 'rigid', yaw=yaw_e, sink_cm=3, block='bay1', material_set='cloth', collision=False,
          role='lean-to over the spare\'s berth (canopy on four posts, backed on the wall)')
    S.add('B01_dock01', *Y(A1, BC), 'bay1', 'rigid', yaw=yaw_e, sink_cm=4, block='bay1', fallback=('MV_Manger', 1.0),
          role='FOCAL: the cradle (riveted iron frame, roller towers at its ends)')
    S.add('SK_Carrier', *Y(A1, BS), 'spare', 'rest', yaw=yaw_n - 90.0, rig=True, block='bay1',
          role='FOCAL: the dead spare (SK_Carrier, A_Carrier_Shutdown end pose: body dropped, mast folded, eyes dark)')
    S.add('MV_jute_bag_07', *Y(A1 - 1.20, BC + 1.25), 'bay1', 'rest', yaw=yaw_e + 23, sink_cm=2,
          role='an emptied bag by the cradle (the load was taken on)', material_set='cloth')
    S.add('MV_jute_bag_08', *Y(A1 + 0.95, 0.42), 'bay1', 'rest', yaw=yaw_e - 4, sink_cm=2,
          role='an emptied bag against the wall', material_set='cloth')
    S.keep_clear.append((Y(A1, b_t1), e, (t1[0] / 200.0, t1[1] / 200.0)))

    # 3. bay 2, up-road: the empty berth (no replacement) and the unclaimed loads.
    t2 = CAT[TARP2]['size_cm']
    A2 = A1 + t1[0] / 200.0 + A_GAP + t2[0] / 200.0
    b_t2 = 0.12 + t2[1] / 200.0
    S.frame['A2'] = A2
    S.add(TARP2, *Y(A2, b_t2), 'bay2', 'rigid', yaw=yaw_e, sink_cm=3, block='bay2', material_set='cloth', collision=False,
          role='lean-to over the empty berth')
    S.add('B01_dock01', *Y(A2 - 0.45, BC), 'bay2', 'rigid', yaw=yaw_e, sink_cm=4, block='bay2', fallback=('MV_Manger', 1.0),
          role='the second cradle, EMPTY: replacement carriers, none')
    S.add('PH_wcrate', *Y(A2 + 1.55, 0.72), 'bay2', 'rest', yaw=yaw_e, sink_cm=2, material_set='wood',
          role='an unclaimed crate against the wall')
    S.add('PH_mcrate', *Y(A2 + 1.55, 0.62), 'bay2', 'rest', yaw=yaw_e + 8, sink_cm=1, stack=True, drop_cm=40,
          material_set='wood', role='a second crate, stacked on it')
    S.add('B01_tank01', *Y(A2 + 1.55, 2.05), 'bay2', 'rest', scale=0.8, yaw=yaw_e + 40, sink_cm=3,
          role='a wood-hooped clay fuel jar, sealed')
    S.add('MV_jute_bag_03', *Y(A2 + 1.30, 3.05), 'bay2', 'rest', yaw=yaw_e + 65, sink_cm=2, material_set='cloth',
          role='a full bag nobody came for')
    S.add('MV_Rope_01', *Y(A2 - 0.45, BC + 1.15), 'bay2', 'rest', scale=2.5, sink_cm=1,
          role='the berth\'s tow rope, coiled in front of the empty cradle')
    S.keep_clear.append((Y(A2, b_t2), e, (t2[0] / 200.0, t2[1] / 200.0)))

    # 4. the wall's ends: a woodpile against the up-road end, a rock outcrop at the down-road end (the wall butts
    #    onto it), both part of the ground: the rock 40 % buried, scree below it.
    wlog = CAT['BPP_Logs_01']['size_cm']
    a_w1 = S.frame['wall_a'][1]
    a_wood = A2 + t2[0] / 200.0 + 0.14 + wlog[0] / 200.0
    S.frame['wood_a'] = (a_wood - wlog[0] / 200.0, a_wood + wlog[0] / 200.0)
    S.add('BPP_Logs_01', *Y(a_wood, 0.10 + wlog[1] / 200.0), 'woodpile', 'rigid', yaw=yaw_e, sink_cm=4,
          block='woodpile', material_set='wood', role='the woodpile against the wall\'s up-road end')
    r4 = CAT['LF_Rock_04']['size_cm']
    ra = S.frame['wall_a'][0] - 0.14 - r4[0] * 0.85 / 200.0
    rock = S.add('LF_Rock_04', *Y(ra, 0.15), 'rocks', 'lie', scale=0.85, yaw=yaw_e + 4, sink_cm=0.40 * r4[2] * 0.85,
                 block='rock', rand_tilt=4, material_set='stone', role='the outcrop the wall butts onto (40 % buried)')
    S.add('LF_Rock_05', *Y(ra - 0.9, 2.1), 'rocks', 'lie', scale=0.55, yaw=yaw_e - 35, sink_cm=0.40 * 129 * 0.55,
          block='rock2', rand_tilt=4, material_set='stone', role='a lower rock below the outcrop')

    # 5. the plaque at the spur mouth: an iron-plated board between two planted posts, its road face toward the
    #    shot-1 eye (and arrivals), its back toward the berths (TAKE WHAT IT CARRIED. for whoever leaves with the load).
    pq = polar(L['plaque_bearing'], L['plaque_dist'])
    face = (-pq[0], -pq[1])
    fl = math.hypot(*face)
    face = (face[0] / fl, face[1] / fl)
    yaw_board = G.yaw_of(*face) - 90.0                  # local +Y (the road face) toward the eye
    sc = L['sign_scale']
    board = S.add('B01_sign02', pq[0], pq[1], 'plaque', 'rigid', scale=sc, yaw=yaw_board, sink_cm=3, block='plaque',
                  material_set='wood', role='FOCAL: the plaque (rule on the road face, TAKE WHAT IT CARRIED. on the back)')
    bx = G.dir_of(yaw_board)
    half = CAT['B01_sign02']['size_cm'][0] * sc / 200.0
    for s_ in (-1, 1):
        u = pq[0] + bx[0] * s_ * (half + 0.13)
        v = pq[1] + bx[1] * s_ * (half + 0.13)
        S.add('MV_Fence_01_Log1', u, v, 'plaque', 'rigid', scale=1.6, yaw=yaw_board + rng.uniform(-8, 8), sink_cm=35,
              block='plaque', material_set='wood', role='plaque post (planted 35 cm; the board is nailed to it)')
    S.frame['plaque'] = dict(c=pq, face=face, yaw=yaw_board, half=half, board=board)

    # 6. the cold fire in the yard, a log and a flat stone to sit on (uphill of it, looking at the road and the
    #    valley), the unlit lantern set down on the stone, a tipped bucket.
    fp = polar(L['fire_bearing'], L['fire_dist'])
    S.add('PH_fire_pit', fp[0], fp[1], 'fire', 'lie', yaw=rng.uniform(0, 360), sink_cm=8, block='fire', rand_tilt=2,
          material_set='stone', role='the cold fire ring ("the fire at the waystation\'s gone out")')
    lg = (fp[0] - n[0] * 1.55 + e[0] * 0.25, fp[1] - n[1] * 1.55 + e[1] * 0.25)
    S.add('PH_trunk_02', lg[0], lg[1], 'fire', 'lie', scale=0.42, yaw=yaw_e + 6, sink_cm=12, block='seat_log', rand_tilt=2,
          material_set='wood', role='the log seat, uphill of the fire')
    st = (fp[0] - e[0] * 1.45 - n[0] * 0.55, fp[1] - e[1] * 1.45 - n[1] * 0.55)
    stone = S.add('FAB_TempleStones', st[0], st[1], 'fire', 'lie', scale=0.42, yaw=yaw_e + 70, sink_cm=9,
                  block='seat_stone', rand_tilt=2, material_set='stone', role='the stone seat, down-road of the fire')
    S.add('PH_lantern', st[0] + e[0] * 0.12, st[1] + e[1] * 0.12, 'fire', 'rest', yaw=yaw_e + 30, stack=True, drop_cm=25,
          sink_cm=1, role='the lantern, set down on the stone seat, cold (never lit)')
    S.add('PH_lantern_glass', st[0] + e[0] * 0.12, st[1] + e[1] * 0.12, 'fire', 'rest', yaw=yaw_e + 30, attach=True,
          role='its glass, sharing the lantern pivot')
    S.add('MV_bucket_02', fp[0] + e[0] * 1.1 - n[0] * 0.6, fp[1] + e[1] * 1.1 - n[1] * 0.6, 'fire', 'rest', roll=90.0,
          yaw=yaw_e - 50, sink_cm=2, role='a tipped bucket by the fire')
    S.frame['fire'] = fp
    S.frame['stone'] = stone

    # 7. the flag on the rise at the bend: a log pole in a footing of packed stones, the banner hung from its top
    #    (the rig step hangs it from the settled pole: the pole's pivot height is not known offline).
    fu, fv = L['flag_uv']
    S.add('MV_Log_01', fu, fv, 'flag', 'rigid', yaw=rng.uniform(0, 360), sink_cm=45, block='flag', material_set='wood',
          role='the flag pole (planted 45 cm)')
    S.add('TRIPO_Flag', fu, fv + 0.52, 'flag', 'rest', scale=6.0, yaw=G.yaw_of(0.0, 1.0), rig=True, collision=False,
          role='the banner, hung from the pole top by the rig step ("the flag stays")')

    # 8. optional (after the Tripo import, --with-optional): the keeper's stone hut on the terrace behind the wall
    if with_hut:
        hut = CAT.get('T2_stone_hut') or EXTRA['T2_stone_hut']
        hb = -(thick + 2.6 + hut['size_cm'][1] / 200.0)
        S.add('T2_stone_hut', *Y(A2 - 0.8, hb), 'hut', 'rigid', yaw=yaw_e, sink_cm=12, block='hut', optional=True,
              material_set='stone', role='OPTIONAL: the keeper\'s stone hut on the terrace behind the wall (Tripo stone_mud_hut)')

    # 9. ground: the yard, the bay floors, the spur from the road past the plaque, the trodden line along the bays,
    #    soot at the fire, a fuel stain under the spare, dust at the rock and along the wall's back foot.
    ce = math.degrees(math.atan2(e[1], e[0]))
    mid = (A1 + A2) / 2
    S.patch('packed_earth', *Y(mid - 0.6, 5.0), ce, 13.5, 7.8, 0.70, sort=0, role='the yard')
    S.patch('packed_earth', *Y(A1, 1.9), ce, 4.3, 3.7, 0.85, sort=0, role='bay 1 floor')
    S.patch('packed_earth', *Y(A2, 2.0), ce, 4.7, 3.9, 0.85, sort=0, role='bay 2 floor')
    S.patch('soot', fp[0], fp[1], ce + 20, 2.9, 2.6, 0.80, sort=3, role='soot and ash round the cold fire')
    S.patch('soot', *Y(A1, BS + 0.1), ce, 1.9, 1.5, 0.35, sort=3, role='the fuel stain where the spare stopped')
    S.patch('rubble_dust', *Y(ra - 0.6, 2.2), ce + 25, 3.4, 2.3, 0.60, sort=1, role='scree dust below the outcrop')
    S.patch('rubble_dust', *Y((S.frame['wall_a'][0] + a_w1) / 2, -thick - 0.7), ce, 12.8, 1.3, 0.45, sort=1,
            role='dust and stones along the wall\'s back foot')
    # the spur: from the road edge down-road of the plaque, past its road face, into the yard and to the fire
    p0 = (pq[0] - 1.9, 4.55)
    p1 = (pq[0] - 1.35, pq[1] + 0.2)
    p2 = Y(mid - 0.5, 4.4)
    S.path([p0, p1, p2, (fp[0] + e[0] * 0.9, fp[1] + e[1] * 0.9)], width=1.15, strength=0.85,
           role='the spur from the road, past the plaque, into the yard')
    S.path([Y(A1 - 0.8, 4.35), Y(A2 + 1.4, 4.45)], width=0.95, strength=0.6, role='the trodden line along the berths')
    wa_end = S.frame['wood_a'][1]
    S.path([Y(wa_end + 0.6, 2.0), Y(wa_end + 0.9, -0.6), Y(a_w1 + 0.4, -(thick + 1.7)), Y(A2 - 0.8, -(thick + 2.4))],
           width=0.8, strength=0.5,
           role='the way up round the wall end to the terrace behind')
    S.keep_clear.append((((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2), (1.0, 0.0), (0.2, 0.2)))

    # 10. stones: packed round the pole foot, at the plaque posts, along the wall's back foot, scree below the
    #     outcrop, a few cleared from the yard to its downhill edge, chinking at the cradles' front feet.
    def stone_(u, v, block, role, keys=('LF_Rock_08', 'LF_Rock_08', 'AB_Cobble_04'), scale=(0.7, 1.1), bury=0.36):
        if G.road_dist(u, v) < CLEAR_M + 0.4:
            return
        key = rng.choice(keys)
        sc_ = rng.uniform(*scale)
        h = CAT[key]['size_cm'][2] * sc_
        S.add(key, u, v, 'stones', 'lie', scale=sc_, yaw=rng.uniform(0, 360), sink_cm=bury * h, ism=True, block=block,
              settle_kind='ism_stone', role=role, material_set='stone')
    for k in range(6):
        ang = k * 2 * math.pi / 6 + rng.uniform(-0.15, 0.15)
        r = rng.uniform(0.30, 0.38)
        stone_(fu + r * math.cos(ang), fv + r * math.sin(ang), 'base', 'the flag pole footing', scale=(0.7, 0.95), bury=0.3)
    for it in [q for q in S.items if q['key'] == 'MV_Fence_01_Log1']:
        for k in range(3):
            ang = rng.uniform(0, 2 * math.pi)
            stone_(it['u'] + 0.24 * math.cos(ang), it['v'] + 0.24 * math.sin(ang), 'base', 'packed at a plaque post',
                   keys=('LF_Rock_08', 'AB_Cobble_04'), scale=(0.6, 0.9))
    wa0, wa1 = S.frame['wall_a']
    for k in range(9):
        a = wa0 + (k + 0.5) * (wa1 - wa0) / 9 + rng.uniform(-0.4, 0.4)
        stone_(*Y(a, -thick - rng.uniform(0.3, 0.75)), 'base', 'slumped at the wall\'s back foot')
    for k in range(6):
        stone_(*Y(ra - 0.3 + rng.uniform(-0.8, 0.8), 1.3 + rng.expovariate(1 / 0.9)), 'fan', 'scree below the outcrop',
               keys=('LF_Rock_07', 'LF_Rock_08'), scale=(0.7, 1.3))
    fp_ = S.frame['fire']
    for k in range(6):
        stone_(fp_[0] - 3.4 + k * 1.05 + rng.uniform(-0.3, 0.3), 6.25 + rng.uniform(-0.25, 0.35), 'base',
               'cleared from the yard to its downhill edge', keys=('LF_Rock_08', 'LF_Rock_07', 'AB_Cobble_04'))
    for a_c in (A1, A2 - 0.45):
        for s_ in (-1, 1):
            stone_(*Y(a_c + s_ * 1.25, BC + 0.655 + 0.16), 'base', 'packing at a cradle foot', keys=('AB_Cobble_04',),
                   scale=(0.9, 1.2))

    # 11. creep: dead shrubs on the retained bank behind the wall, at the wall ends, by the outcrop, at the plaque's
    #     down-road post, at the pole footing and on the yard's edges. Never on a path, never in a berth.
    creep = [('FAB_Shrub_G', Y(wa0 + 1.2, -thick - 1.4), 1.0), ('FAB_Shrub_C', Y(-1.5, -thick - 1.1), 0.9),
             ('FAB_Shrub_E', Y(2.6, -thick - 1.6), 1.0), ('FAB_Shrub_G', Y(wa1 - 1.0, -thick - 1.2), 0.9),
             ('FAB_Shrub_C', Y(ra + 0.2, 1.55), 1.0), ('FAB_Shrub_D', Y(ra - 1.6, 1.0), 1.1),
             ('FAB_Shrub_D', Y(wa0 + 0.35, 0.55), 0.9), ('FAB_Shrub_E', Y(S.frame['wood_a'][1] + 0.45, 1.1), 0.9),
             ('FAB_Shrub_D', (fu - 0.55, fv - 0.45), 0.8), ('FAB_Shrub_C', Y(mid + 4.4, 7.3), 1.0),
             ('FAB_Shrub_G', Y(mid - 6.3, 6.9), 0.9), ('FAB_Shrub_E', Y(mid + 1.2, 8.3), 0.8)]
    pst = [q for q in S.items if q['key'] == 'MV_Fence_01_Log1']
    dn = min(pst, key=lambda q: q['u'])
    creep.append(('FAB_Shrub_D', (dn['u'] - 0.35, dn['v'] + 0.15), 0.8))
    for key, (u, v), sc_ in creep:
        if S.on_lane(u, v) or S.in_keep_clear(u, v, 0.3) or G.road_dist(u, v) < CLEAR_M + 0.6:
            continue
        S.add(key, u, v, 'creep', 'lie', scale=sc_, yaw=rng.uniform(0, 360), sink_cm=5, ism=True, block='creep',
              settle_kind='ism_shrub', role='dead shrub')

    # the save judge (check2) measures only the solo actors; push every ISM piece out of the solids and out of each
    # other (the minimum translation), and leave out any that finds no room within 0.6 m, lands on a path or in a berth
    S.moved = declash(G, S)
    S.dropped = [it for it in S.items if it['ism'] and (S.moved[id(it)] > 0.6 or S.on_lane(it['u'], it['v'], 0.1)
                                                        or S.in_keep_clear(it['u'], it['v'])
                                                        or any(a is it or b is it for _, _, a, b in clash_pairs(G, S)))]
    S.items = [it for it in S.items if all(it is not d for d in S.dropped)]
    return S


ISM_ALLOW = dict(stone=0.05, shrub=0.10, ism=0.04)


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


def solids_of(S):
    return [it for it in S.items if not it['ism'] and not it['attach'] and not it['stack']
            and it['key'] not in ('TRIPO_Flag',) and it['cat'] not in ('cloth',)]


def canopy_posts(G, it, r=0.07):
    """A tarp lean-to is four posts and a roof: its plan footprint as solids is its four corner posts."""
    ax, ay = site_axes(G, it)
    hx, hy = it['size_m'][0] / 2 - 0.08, it['size_m'][1] / 2 - 0.08
    out = []
    for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        cu = it['u'] + sx * hx * ax[0] + sy * hy * ay[0]
        cv = it['v'] + sx * hx * ax[1] + sy * hy * ay[1]
        out.append([(cu - r, cv - r), (cu + r, cv - r), (cu + r, cv + r), (cu - r, cv + r)])
    return out


def plan_polys(G, it):
    if it['cat'] == 'cloth' and it['key'].startswith('MV_Annex_Tarp'):
        return canopy_posts(G, it)
    return [obb_uv(G, it)]


def clash_pairs(G, S):
    """Plan overlaps beyond ISM_ALLOW: ISM stones / shrubs into the solids (incl. the canopy posts) and each other."""
    sol = solids_of(S) + [it for it in S.items if it['key'].startswith('MV_Annex_Tarp')]
    isms = [it for it in S.items if it['ism']]
    out = []
    for it in isms:
        allow = ISM_ALLOW['shrub' if it['cat'] == 'shrub' else 'stone']
        A = obb_uv(G, it)
        for sd in sol:
            if sd.get('rig') and sd['key'] != 'SK_Carrier':
                continue
            for poly in plan_polys(G, sd):
                d = plan_mtv(A, poly)[0]
                if d > allow + 1e-6:
                    out.append((d, allow, it, sd))
    for i in range(len(isms)):
        for j in range(i + 1, len(isms)):
            d = plan_mtv(obb_uv(G, isms[i]), obb_uv(G, isms[j]))[0]
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
            best = None
            for poly in plan_polys(G, fixed):
                dd, ax = plan_mtv(obb_uv(G, mover), poly)
                if ax is not None and (best is None or dd > best[0]):
                    best = (dd, ax)
            if best is None:
                continue
            dd, ax = best
            mover['u'] += ax[0] * (dd - allow + 0.03)
            mover['v'] += ax[1] * (dd - allow + 0.03)
            mover['x'], mover['y'] = G.world(mover['u'], mover['v'])
            done.add(id(mover))
    return {id(it): math.hypot(it['u'] - start[id(it)][0], it['v'] - start[id(it)][1]) for it in S.items if it['ism']}


# ---------------------------------------------------------------------------- 3D boxes (predicted poses) for the frames

def box3(G, it, part=None):
    """(centre (x, y, z) world m, [(axis, half)] x3) of the predicted pose, or of a named part of it."""
    p = predicted(G, it)
    ax, ay = site_axes(G, it)
    X = np.array([*(ax[0] * G.f + ax[1] * G.l), 0.0])
    Yv = np.array([*(ay[0] * G.f + ay[1] * G.l), 0.0])
    Z = np.array([0.0, 0.0, 1.0])
    hx, hy, hz = it['size_m'][0] / 2, it['size_m'][1] / 2, (p['top'] - p['bottom']) / 2
    c = np.array([it['x'], it['y'], p['bottom'] + hz])
    if part is None:
        return [(c, [(X, hx), (Yv, hy), (Z, hz)])]
    out = []
    if part == 'canopy':             # the tarp lean-to: four posts + the roof (its top 0.45 m)
        for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            pc = c + X * sx * (hx - 0.08) + Yv * sy * (hy - 0.08)
            out.append((pc, [(X, 0.07), (Yv, 0.07), (Z, hz)]))
        out.append((c + Z * (hz - 0.22), [(X, hx), (Yv, hy), (Z, 0.22)]))
    elif part == 'dock':             # the iron cradle: two roller towers (0.55 m of each end) + the base beam
        for sx in (-1, 1):
            out.append((c + X * sx * (hx - 0.275), [(X, 0.275), (Yv, hy * 0.75), (Z, hz)]))
        out.append((c - Z * (hz - 0.13), [(X, hx), (Yv, 0.2), (Z, 0.13)]))
    return out


def ray_box(o, d, box):
    """Distance along the unit ray o + t d to an oriented box, or None."""
    c, axes_ = box
    t0, t1 = 0.0, 1e9
    for a, h in axes_:
        e = float(a @ (c - o))
        f = float(a @ d)
        if abs(f) < 1e-9:
            if abs(e) > h:
                return None
            continue
        ta, tb = (e - h) / f, (e + h) / f
        if ta > tb:
            ta, tb = tb, ta
        t0, t1 = max(t0, ta), min(t1, tb)
        if t0 > t1:
            return None
    return t0


def occluders(G, S, skip=()):
    out = []
    for it in S.items:
        if it['ism'] and it['cat'] == 'shrub':
            continue
        if it['attach'] or it['key'] in ('TRIPO_Flag',) or id(it) in skip or it.get('optional_off'):
            continue
        if it['ism'] and max(it['size_m']) < 0.3:
            continue
        part = 'canopy' if it['key'].startswith('MV_Annex_Tarp') else ('dock' if it['key'] == 'B01_dock01' else None)
        for b in box3(G, it, part):
            out.append((it, b))
    return out


def visible_fraction(eye, pts, occ, skip_items=()):
    n = 0
    eye = np.array(eye)
    for p in pts:
        p = np.array(p)
        d = p - eye
        L = float(np.linalg.norm(d))
        d = d / L
        hit = False
        for it, b in occ:
            if any(it is s for s in skip_items):
                continue
            t = ray_box(eye, d, b)
            if t is not None and 0.05 < t < L - 0.05:
                hit = True
                break
        n += 0 if hit else 1
    return n / max(1, len(pts))


# ---------------------------------------------------------------------------- cameras and frames

def cam_basis(yaw, pitch):
    cy, sy = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
    cp, sp = math.cos(math.radians(pitch)), math.sin(math.radians(pitch))
    F = np.array([cp * cy, cp * sy, sp])
    Rt = np.array([-sy, cy, 0.0])
    U = np.array([-sp * cy, -sp * sy, cp])
    return F, Rt, U


def project(eye, yaw, pitch, pts, hfov, aspect=16 / 9):
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
        out.append((float((d @ Rt) / z / th), float((d @ U) / z / tv)))
    return out


def look_at(eye, tgt):
    dx, dy, dz = tgt[0] - eye[0], tgt[1] - eye[1], tgt[2] - eye[2]
    return math.degrees(math.atan2(dy, dx)), math.degrees(math.atan2(dz, math.hypot(dx, dy)))


def corners(box):
    c, ax = box
    out = []
    for sx in (-1, 1):
        for sy in (-1, 1):
            for sz in (-1, 1):
                out.append(tuple(c + ax[0][0] * sx * ax[0][1] + ax[1][0] * sy * ax[1][1] + ax[2][0] * sz * ax[2][1]))
    return out


def screen_box(eye, yaw, pitch, pts, hfov):
    q = [p for p in project(eye, yaw, pitch, pts, hfov) if p is not None]
    if not q:
        return None
    return (min(p[0] for p in q), max(p[0] for p in q), min(p[1] for p in q), max(p[1] for p in q))


def inside(b, m=0.0):
    return b is not None and b[0] >= -1 + m and b[1] <= 1 - m and b[2] >= -1 + m and b[3] <= 1 - m


def rig_boxes(G, stop, lat):
    """Our carrier and its capsule (world boxes), stopped `stop` m past 3,400, `lat` m left of the centreline."""
    u0 = stop
    f3 = np.array([*G.f, 0.0])
    l3 = np.array([*G.l, 0.0])
    Z = np.array([0.0, 0.0, 1.0])

    def at(u, v, z):
        x, y = G.world(u, v)
        return np.array([x, y, G.zuv(u, v) + z])
    car = (at(u0, lat, CARRIER['h'] / 2), [(f3, CARRIER['half_len']), (l3, CARRIER['half_wid']), (Z, CARRIER['h'] / 2)])
    cap = (at(u0 + CAPSULE['c'], lat, (CAPSULE['z0'] + CAPSULE['z1']) / 2),
           [(f3, CAPSULE['half_len']), (l3, CAPSULE['half_wid']), (Z, (CAPSULE['z1'] - CAPSULE['z0']) / 2)])
    mark = tuple(at(u0 + MARK[0], lat + MARK[1], MARK[2]))
    eye = tuple(at(u0, lat, EYE_M[1]))
    return car, cap, mark, eye


def spare_face(G, S):
    """Sample points on the spare's front face (its upper part: the sensor head and the eyes)."""
    sp = [it for it in S.items if it['key'] == 'SK_Carrier'][0]
    p = predicted(G, sp)
    fw = G.dir_of(sp['yaw'] + 90.0)                       # the carrier's front is its mesh +Y
    rt = G.dir_of(sp['yaw'])
    pts = []
    for a in (-0.4, -0.2, 0.0, 0.2, 0.4):
        for zf in (0.55, 0.75, 0.9):
            u = sp['u'] + fw[0] * (sp['size_m'][1] / 2 + 0.02) + rt[0] * a
            v = sp['v'] + fw[1] * (sp['size_m'][1] / 2 + 0.02) + rt[1] * a
            x, y = G.world(u, v)
            pts.append((x, y, p['bottom'] + zf * sp['size_m'][2]))
    return pts


def board_text_points(G, S, face_sign, panel):
    """Sample points of one panel's two text lines on the board's road face (+1) or back face (-1)."""
    bd = S.frame['plaque']['board']
    p = predicted(G, bd)
    bx = G.dir_of(bd['yaw'])
    by = G.dir_of(bd['yaw'] + 90.0)
    h = bd['size_m'][2]
    zc = p['bottom'] + PANEL_Z[panel] * h
    out = []
    for a in (-0.30, -0.15, 0.0, 0.15, 0.30):
        for dz in (-LINE_DZ_CM / 100.0, LINE_DZ_CM / 100.0):
            u = bd['u'] + by[0] * face_sign * (bd['size_m'][1] / 2 + 0.012) + bx[0] * a * bd['scale'] / 1.2
            v = bd['v'] + by[1] * face_sign * (bd['size_m'][1] / 2 + 0.012) + bx[1] * a * bd['scale'] / 1.2
            x, y = G.world(u, v)
            out.append((x, y, zc + dz))
    return out, zc


def text_px(G, S, eye, face_sign, panel, hfov, width_px):
    """Capital height in pixels of one panel's lettering, and the angle between the face normal and the view."""
    bd = S.frame['plaque']['board']
    pts, zc = board_text_points(G, S, face_sign, panel)
    c = np.mean(np.array(pts), axis=0)
    dist = float(np.linalg.norm(c - np.array(eye)))
    by = G.dir_of(bd['yaw'] + 90.0)
    nrm = np.array([*(face_sign * by[0] * G.f + face_sign * by[1] * G.l), 0.0])
    view = (np.array(eye) - c) / dist
    inc = math.degrees(math.acos(max(-1.0, min(1.0, float(nrm @ view)))))
    px_per_m = width_px / (2 * dist * math.tan(math.radians(hfov) / 2))
    cap = TEXT_WORLD_CM * 0.7 / 100.0
    return dict(dist_m=round(dist, 2), incidence_deg=round(inc, 1), cap_px=round(cap * px_per_m, 1),
                cap_px_h=round(cap * px_per_m * math.cos(math.radians(min(inc, 89))), 1))


def shot1(G, S, eye_m, pitch, hfov=HFOV_ZOOM, yaw_local=POV_YAW_LOCAL):
    ox, oy = G.world(0.0, 0.0)
    eye = (ox, oy, G.z0 + eye_m)
    yaw = G.road_yaw + yaw_local
    occ = occluders(G, S)
    by = {k: [] for k in ('spare', 'cradle', 'bay1', 'bay2', 'plaque', 'wall', 'fire', 'hut')}
    for it in S.items:
        g = {'SK_Carrier': 'spare', 'B01_dock01': 'cradle'}.get(it['key'])
        if g is None:
            g = {'bay1': 'bay1', 'bay2': 'bay2', 'plaque': 'plaque', 'wall': 'wall', 'fire': 'fire', 'hut': 'hut'}.get(it['group'])
        if g is None or it['attach'] or it['ism']:
            continue
        if g == 'cradle' and it['group'] == 'bay2':
            continue
        for b in box3(G, it):
            by[g] += corners(b)
    boxes = {k: screen_box(eye, yaw, pitch, v, hfov) for k, v in by.items() if v}
    sp = [it for it in S.items if it['key'] == 'SK_Carrier'][0]
    face_vis = visible_fraction(eye, spare_face(G, S), occ, skip_items=[sp])
    bd = S.frame['plaque']['board']
    txt = []
    for panel in range(3):
        pts, _ = board_text_points(G, S, +1, panel)
        vis = visible_fraction(eye, pts, occ, skip_items=[bd])
        scr = screen_box(eye, yaw, pitch, pts, hfov)
        txt.append(dict(panel=panel, visible=round(vis, 2), in_frame=inside(scr, 0.02),
                        **text_px(G, S, eye, +1, panel, hfov, 1920)))
    return dict(eye=eye, yaw=yaw, pitch=pitch, hfov=hfov, boxes={k: tuple(round(x, 2) for x in v) if v else None
                                                                 for k, v in boxes.items()},
                spare_face_visible=round(face_vis, 2), text=txt)


def best_pitch1(G, S, eye_m):
    """The shot-1 pitch nearest the plan's -4 deg that frames the lean-to tops, the spare, the plaque and the cradle
    with a 5 % margin (the ground rises to the left of the road here)."""
    cands = sorted(np.arange(-6.0, 8.01, 0.5), key=lambda p: abs(p - POV_PITCH_PLAN))
    for p in cands:
        f = shot1(G, S, eye_m, float(p))
        b = f['boxes']
        if all(inside(b.get(k), 0.05) for k in ('spare', 'plaque', 'cradle')) and b['bay1'] and b['bay1'][3] <= 0.95:
            return float(p), f
    return POV_PITCH_PLAN, shot1(G, S, eye_m, POV_PITCH_PLAN)


def shot2_cam(G, S):
    """Behind the spare, low: 0.5 m out from the wall on the cradle's axis, 1.30 m over the ground there, aimed at
    the middle of our carrier + capsule (stopped at 3,401, on the centreline)."""
    Yf = S.frame['Y']
    cu, cv = Yf(A1, 0.50)
    x, y = G.world(cu, cv)
    cam = (x, y, G.zuv(cu, cv) + 1.30)
    car, cap, mark, _ = rig_boxes(G, 1.0, 0.0)
    tgt = tuple((car[0] + cap[0]) / 2 + np.array([0.0, 0.0, -0.05]))
    return cam, tgt


def shot2(G, S, cam, tgt):
    yaw, pitch = look_at(cam, tgt)
    occ = occluders(G, S)
    sp = [it for it in S.items if it['key'] == 'SK_Carrier'][0]
    rows = []
    for stop in STOPS_M:
        for lat in LATERALS_M:
            car, cap, mark, _ = rig_boxes(G, stop, lat)
            cb = screen_box(cam, yaw, pitch, corners(car), HFOV_S2)
            kb = screen_box(cam, yaw, pitch, corners(cap), HFOV_S2)
            pts = [tuple(car[0] + np.array([0, 0, dz])) for dz in (-0.3, 0.0, 0.3)] + \
                  [tuple(cap[0] + car[1][0][0] * du + np.array([0, 0, dz])) for du in (-0.8, 0.0, 0.8) for dz in (-0.3, 0.3)]
            vis = visible_fraction(cam, pts, occ)
            rows.append(dict(stop=stop, lat=lat, carrier=None if cb is None else tuple(round(v, 2) for v in cb),
                             capsule=None if kb is None else tuple(round(v, 2) for v in kb),
                             in_frame=inside(cb, 0.02) and inside(kb, 0.0), visible=round(vis, 2)))
    spb = screen_box(cam, yaw, pitch, corners(box3(G, sp)[0]), HFOV_S2)
    pl = [it for it in S.items if it['group'] == 'plaque']
    plb = screen_box(cam, yaw, pitch, [c for it in pl for c in corners(box3(G, it)[0])], HFOV_S2)
    near = min(float(np.linalg.norm(np.array(c) - np.array(cam))) for c in corners(box3(G, sp)[0]))
    return dict(cam=cam, yaw=yaw, pitch=pitch, hfov=HFOV_S2, rows=rows,
                spare=None if spb is None else tuple(round(v, 2) for v in spb), spare_near_m=round(near, 2),
                plaque=None if plb is None else tuple(round(v, 2) for v in plb))


def shot3_cam(G, S, stop=1.0, lat=0.0):
    """Search the insert camera behind the plaque (85 mm): its back lettering (TAKE WHAT IT CARRIED.) whole and in
    frame on one side, the capsule's palm mark clear of the board and posts on the other; the nearest such camera."""
    bd = S.frame['plaque']['board']
    pts, zc = board_text_points(G, S, -1, 2)
    tc = np.mean(np.array(pts), axis=0)
    _, _, mark, _ = rig_boxes(G, stop, lat)
    occ = occluders(G, S)
    back = G.dir_of(bd['yaw'] - 90.0)                     # the back face normal (local -Y)
    bw = np.array([*(back[0] * G.f + back[1] * G.l), 0.0])
    best = None
    for D in np.arange(2.0, 8.01, 0.25):
        if best is not None and D > best[1]['D'] + 0.5:
            break
        for phi in np.arange(-50.0, 50.1, 5.0):
            rot = math.radians(phi)
            dvec = np.array([bw[0] * math.cos(rot) - bw[1] * math.sin(rot), bw[0] * math.sin(rot) + bw[1] * math.cos(rot), 0.0])
            for dz in (0.0, 0.25):
                cam = tc + dvec * D + np.array([0.0, 0.0, dz])
                if cam[2] < G.z(cam[0], cam[1]) + 0.6:
                    continue
                hit = None
                for w in np.arange(0.2, 0.81, 0.05):     # aim between the lettering (weight 1-w) and the mark (w)
                    aim = tc * (1 - w) + np.array(mark) * w
                    yaw, pitch = look_at(tuple(cam), tuple(aim))
                    ts = screen_box(tuple(cam), yaw, pitch, pts, HFOV_S3)
                    ms = project(tuple(cam), yaw, pitch, [mark], HFOV_S3)[0]
                    if inside(ts, 0.03) and ms is not None and abs(ms[0]) <= 0.9 and abs(ms[1]) <= 0.85:
                        hit = (yaw, pitch, ts, ms)
                        break
                if hit is None:
                    continue
                tp = text_px(G, S, tuple(cam), -1, 2, HFOV_S3, 1920)
                if tp['incidence_deg'] > 45:
                    continue
                if visible_fraction(tuple(cam), [mark], occ) < 1.0:
                    continue
                if visible_fraction(tuple(cam), pts, occ, skip_items=[bd]) < 1.0:
                    continue
                yaw, pitch, ts, ms = hit
                score = D + 0.02 * abs(phi)
                if best is None or score < best[0]:
                    best = (score, dict(cam=tuple(float(c) for c in cam), yaw=yaw, pitch=pitch, D=float(D), phi=float(phi),
                                        text=tuple(round(v, 2) for v in ts), mark=tuple(round(v, 2) for v in ms),
                                        rack_near_m=round(float(np.linalg.norm(tc - cam)), 2),
                                        rack_far_m=round(float(np.linalg.norm(np.array(mark) - cam)), 2), lettering=tp))
    return None if best is None else best[1]


def shot3_rows(G, S, s3):
    """How the chosen insert holds the mark for the other stops and lateral positions."""
    occ = occluders(G, S)
    rows = []
    for stop in STOPS_M:
        for lat in LATERALS_M:
            _, _, mark, _ = rig_boxes(G, stop, lat)
            ms = project(s3['cam'], s3['yaw'], s3['pitch'], [mark], HFOV_S3)[0]
            vis = visible_fraction(s3['cam'], [mark], occ)
            rows.append(dict(stop=stop, lat=lat, mark=None if ms is None else tuple(round(v, 2) for v in ms),
                             in_frame=ms is not None and abs(ms[0]) <= 1 and abs(ms[1]) <= 1, visible=vis,
                             rack_far_m=round(float(np.linalg.norm(np.array(mark) - np.array(s3['cam']))), 2)))
    return rows


def to_local(G, p):
    """World m point -> the CIN_11 local frame (cm): +X up-road, +Y right, +Z up from the road at the origin."""
    u, v = G.local(p[0], p[1])
    return round(u * 100, 1), round(-v * 100, 1), round((p[2] - G.z0) * 100, 1)


def local_yaw(G, yaw):
    return round((yaw - G.road_yaw + 180.0) % 360.0 - 180.0, 1)


def approach_rows(G, S):
    """The set from the long straight (forward POV, eye 1.22 m): distance, screen box, terrain line of sight."""
    rows = []
    focal = [c for it in S.items if it['group'] in ('bay1', 'bay2', 'spare', 'flag', 'wall') and not it['attach']
             and not it['ism'] and not it['optional'] for b in box3(G, it) for c in corners(b)]
    cx, cy = G.world(*S.frame['Y'](0.0, 1.5))
    cz = G.zuv(*S.frame['Y'](0.0, 1.5)) + 1.4
    for s in (3250.0, 3300.0, 3350.0, 3380.0, 3395.0):
        u, _ = G.road_uv(s)
        x, y = G.world(u, 0.0)
        eye = (x, y, G.z(x, y) + EYE_M[1])
        b = screen_box(eye, G.road_yaw, 0.0, focal, HFOV_POV)
        dist = math.dist(eye[:2], (cx, cy))
        tan, _ = G.T.horizon_tan(np.array([eye[0] * 100]), np.array([eye[1] * 100]), np.array([eye[2]]),
                                 np.array([cx * 100]), np.array([cy * 100]), skip_far_m=3.0)
        rows.append(dict(road_m=s, dist_m=round(dist, 1), box=None if b is None else tuple(round(v, 2) for v in b),
                         terrain_los=bool((cz - eye[2]) / dist > float(tan[0]))))
    return rows


# ---------------------------------------------------------------------------- records

def v1_remaining():
    """The S19 V1 placements this set does not clear (they stay; V7 must not collide with them)."""
    d = json.load(open(SITES_V1_JSON, encoding='utf8'))
    s = [x for x in d['sites'] if x['id'] == ROAD_SITE][0]
    return [p for p in s['placements'] if p['id'] not in V1_CLEAR], [p for p in s['placements'] if p['id'] in V1_CLEAR]


def to_record(G, S, i, it):
    rid = '%s_%03d' % (SID, i)
    rec = dict(id=rid, key=it['key'], asset=it['asset'], kind='SM', cat=it['cat'],
               x_cm=round(it['x'] * 100, 1), y_cm=round(it['y'] * 100, 1), ground_z_cm=round(G.z(it['x'], it['y']) * 100, 1),
               yaw=it['yaw'], pitch=float(it['pitch']), roll=float(it['roll']), scale=it['scale'],
               scale_range=[it['scale'], it['scale']], settle=it['settle'], group=it['group'],
               folder='Set/%s/%s' % (SID, it['group']), data_layer='DL_SetDress', ism=it['ism'], stack=it['stack'],
               attach=it['attach'], run_id=None,
               collision=(it['collision'] if it['collision'] is not None else (not it['ism'])),
               foliage_exclude=not it['ism'] or it['cat'] != 'shrub',
               draw_distance_cm=draw_distance_cm(max(it['size_m'])), cast_shadow=True, size_m=it['size_m'],
               slope_deg=round(G.slope_deg(it['u'], it['v']), 1), road_clear_m=None, contact=it['contact'],
               site_uv=[round(it['u'], 2), round(it['v'], 2)], role=it['role'], story_set=SET)
    if it['block']:
        rec['block'] = it['block']
    if it['material_set']:
        rec['material_set'] = it['material_set']
    if it['optional']:
        rec['optional'] = True
        rec['requires_import'] = True
    if it['fallback']:
        k, sc = it['fallback']
        rec['fallback'] = dict(asset=CAT[k]['path'], scale=sc)
    cs = obb_uv(G, it)
    rec['road_clear_m'] = round(min(G.road_dist(u, v) for u, v in cs), 2)
    return rec


def ground_records(G, S):
    out = []
    for i, g in enumerate(S.ground):
        x, y = G.world(g['u'], g['v'])
        a = math.radians(g['yaw'])
        zs = []
        for sl in (-0.5, 0.0, 0.5):
            for sw in (-0.5, 0.0, 0.5):
                du = sl * g['length'] * math.cos(a) - sw * g['width'] * math.sin(a)
                dv = sl * g['length'] * math.sin(a) + sw * g['width'] * math.cos(a)
                zs.append(G.zuv(g['u'] + du, g['v'] + dv))
        relief = max(zs) - min(zs)
        out.append(dict(id='%s_g%02d' % (SID, i), surface=g['surface'], shape=g['shape'],
                        x_cm=round(x * 100, 1), y_cm=round(y * 100, 1), z_cm=round((max(zs) + min(zs)) / 2 * 100, 1),
                        yaw=round(G.yaw_of(math.cos(a), math.sin(a)), 1), length_m=round(g['length'], 2),
                        width_m=round(g['width'], 2), depth_m=round(max(3.0, relief + 1.2), 1),
                        strength=g['strength'], sort=g['sort'], role=g['role']))
    return out


def rig_records(G, S, recs):
    """This set's own editor pieces (the `rig` step): the spare, the banner, the plaque lettering."""
    by_key = {}
    for r in recs:
        by_key.setdefault(r['key'], []).append(r)
    dock1 = [r for r in by_key['B01_dock01'] if r['group'] == 'bay1'][0]
    board = by_key['B01_sign02'][0]
    pole = by_key['MV_Log_01'][0]
    sp = [it for it in S.items if it['key'] == 'SK_Carrier'][0]
    fl = [it for it in S.items if it['key'] == 'TRIPO_Flag'][0]
    lines = []
    for face, text in (('front', TEXT_FRONT), ('back', TEXT_BACK)):
        for panel, pair in enumerate(text):
            if not pair:
                continue
            for k, line in enumerate(pair):
                lines.append(dict(id='%s_txt_%s_%d%d' % (SID, face, panel, k), face=face, text=line,
                                  z_frac=PANEL_Z[panel], dz_cm=LINE_DZ_CM * (1 if k == 0 else -1)))
    return dict(
        spare=dict(id='%s_rig_spare' % SID, asset=EXTRA['SK_Carrier']['path'], anim=SPARE_ANIM, anim_pos=SPARE_ANIM_POS,
                   x_cm=round(sp['x'] * 100, 1), y_cm=round(sp['y'] * 100, 1), ground_z_cm=round(G.z(sp['x'], sp['y']) * 100, 1),
                   yaw=round(sp['yaw'], 2), cradle=dock1['id'],
                   size_m=sp['size_m'], folder='Set/%s/spare' % SID,
                   note='SkeletalMeshActor, single-node anim held at the end of A_Carrier_Shutdown (play rate 0). Lands on '
                        'the ground between the roller towers (traced at its 4 wheels, the highest wins, so no wheel is '
                        'buried), eyes (mesh +Y) toward the road'),
        banner=dict(id='%s_rig_banner' % SID, asset=CAT['TRIPO_Flag']['path'], scale=6.0, pole=pole['id'],
                    yaw=round(fl['yaw'], 2), drop_cm=8.0, gap_cm=4.0, folder='Set/%s/flag' % SID,
                    note='hung from the settled pole: bounds top 8 cm under the pole top, its pole-side edge 4 cm off the '
                         'pole, streaming to the left of the road (broadside to the long straight)'),
        lettering=dict(board=board['id'], world_size_cm=TEXT_WORLD_CM, rgb=list(TEXT_RGB), out_cm=1.2,
                       folder='Set/%s/plaque' % SID, lines=lines,
                       note='TextRender greybox until the inscriptions lane makes a painted-letter decal. front = the '
                            'board\'s local +Y face (toward the road), back = -Y. z_frac of the board\'s mesh bounds height'),
    )


# ---------------------------------------------------------------------------- the plot

def plot(G, S, recs, frames, remaining, cleared):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon, Ellipse
    fig = plt.figure(figsize=(21, 12.5))
    ax = fig.add_axes([0.025, 0.05, 0.47, 0.9])
    us = np.arange(-14, 22.01, 0.25)
    vs = np.arange(-6, 30.01, 0.25)
    UU, VV = np.meshgrid(us, vs)
    X = G.o[0] + UU * G.f[0] + VV * G.l[0]
    Y_ = G.o[1] + UU * G.f[1] + VV * G.l[1]
    Z = G.T.height(X * 100, Y_ * 100)
    cs = ax.contour(UU, VV, Z, levels=np.arange(np.floor(Z.min()), Z.max(), 0.25), colors='#c9bfae', linewidths=0.5)
    ax.clabel(cs, cs.levels[::4], fmt='%.0f m', fontsize=7, colors='#8a7f6c')
    # the road ribbon (9 m) along the true polyline, and the 5 m clearance
    rp = [G.road_uv(s) for s in np.arange(S0 - 20, S0 + 60, 1.0)]
    ax.plot([p[0] for p in rp], [p[1] for p in rp], color='#cfc6b8', lw=9 * 72 / 2.4 / 2.2, alpha=0.6, solid_capstyle='butt')
    ax.plot([p[0] for p in rp], [p[1] for p in rp], color='#8a8174', lw=1, ls='--')
    col = dict(packed_earth='#b08a5a', path='#6b4d33', rubble_dust='#c8b79a', soot='#3a342e')
    for g in S.ground:
        if g['shape'] == 'capsule':
            a = math.radians(g['yaw'])
            Lc = g['length'] - g['width']
            p0 = (g['u'] - Lc / 2 * math.cos(a), g['v'] - Lc / 2 * math.sin(a))
            p1 = (g['u'] + Lc / 2 * math.cos(a), g['v'] + Lc / 2 * math.sin(a))
            ax.plot([p0[0], p1[0]], [p0[1], p1[1]], color=col[g['surface']], lw=g['width'] * 19, alpha=0.3,
                    solid_capstyle='round')
        else:
            ax.add_patch(Ellipse((g['u'], g['v']), g['length'], g['width'], angle=g['yaw'], color=col[g['surface']],
                                 alpha=0.30 * g['strength'], lw=0))
    style = {'wall': ('#3d3a36', '#9d958a'), 'bay1': ('#5a3d22', '#d8cdb8'), 'bay2': ('#5a3d22', '#d8cdb8'),
             'spare': ('#1d1d1d', '#6a6f75'), 'plaque': ('#3b2a18', '#8a6a44'), 'fire': ('#3a342e', '#8c8378'),
             'rocks': ('#4f4a44', '#b3aca1'), 'woodpile': ('#5a3d22', '#a07a4c'), 'flag': ('#7a1f1a', '#b5473c'),
             'hut': ('#6b5a44', '#e6d9bf')}
    for it in S.items:
        if it['ism']:
            c = '#6d8f4e' if it['group'] == 'creep' else '#7d6e5f'
            ms = 6 if it['group'] == 'creep' else max(2.5, it['size_m'][0] * 8)
            ax.plot(it['u'], it['v'], 'o' if it['group'] == 'creep' else 's', ms=ms, color=c, alpha=0.85, mec='none')
            continue
        if it['attach']:
            continue
        ec, fc = style.get(it['group'], ('#333', '#aaa'))
        if it['key'].startswith('MV_Annex_Tarp'):
            ax.add_patch(Polygon(obb_uv(G, it), closed=True, ec=ec, fc=fc, lw=1.0, alpha=0.35, ls='--'))
            for poly in canopy_posts(G, it):
                ax.add_patch(Polygon(poly, closed=True, ec=ec, fc=ec, lw=0.5))
            continue
        ax.add_patch(Polygon(obb_uv(G, it), closed=True, ec=ec, fc=fc, lw=1.2,
                             alpha=0.45 if it['optional'] else 0.9, ls='--' if it['optional'] else '-'))
    for p in remaining:
        u, v = G.local(p['x_cm'] / 100, p['y_cm'] / 100)
        if -14 <= u <= 22 and -6 <= v <= 30:
            ax.plot(u, v, 'D', color='#888', ms=4)
    for p in cleared:
        u, v = G.local(p['x_cm'] / 100, p['y_cm'] / 100)
        ax.plot(u, v, 'x', color='#c33', ms=7, mew=1.5)
    ax.text(-13.5, 28.8, 'x = S19 V1 pieces this set clears (stand-ins, bags, lantern post, rope, flag)\n'
                         '◆ = S19 V1 pieces that stay (hut group, hay annex, logs; the corral across the road)',
            fontsize=8, color='#733')
    Yf = S.frame['Y']
    ann = [('FOCAL: the dead spare\nin its iron cradle (bay 1)', Yf(A1, BS), (-12.5, 21.0)),
           ('the EMPTY cradle, loads (bay 2)', Yf(S.frame['A2'], BC), (6.0, 24.0)),
           ('back wall (AB fort wall x4, 2.4 m showing)', Yf(4.5, -0.2), (7.5, 20.5)),
           ('plaque: rule on the road face,\nTAKE WHAT IT CARRIED. on the back', S.frame['plaque']['c'], (8.0, 3.4)),
           ('cold fire, log and stone seats,\nthe unlit lantern on the stone', S.frame['fire'], (-13.5, 3.5)),
           ('flag pole in a stone footing', LAYOUT['flag_uv'], (14.0, 13.5)),
           ('woodpile', Yf(S.frame['wall_a'][1] + 0.9, 0.8), (15.0, 17.5)),
           ('outcrop the wall butts onto', Yf(S.frame['wall_a'][0] - 1.0, 0.2), (-13.5, 16.0))]
    if any(it['key'] == 'T2_stone_hut' for it in S.items):
        ann.append(('OPTIONAL: keeper\'s hut (Tripo)', Yf(S.frame['A2'] - 0.8, -5.2), (6.0, 27.0)))
    for text, xy, xyt in ann:
        ax.annotate(text, xy=xy, xytext=xyt, fontsize=8.5, arrowprops=dict(arrowstyle='->', color='#333', lw=0.8))
    # the CIN_11 cameras in plan
    f1 = frames['shot1']
    for off, ls in ((-f1['hfov'] / 2, '--'), (0, '-'), (f1['hfov'] / 2, '--')):
        d = G.dir_of(f1['yaw'] + off)
        ax.plot([0, 22 * d[0]], [0, 22 * d[1]], color='#1f5fa8', lw=1.4 if off == 0 else 0.8, ls=ls)
    ax.text(0.4, -1.6, 'B11 3,400: shot 1 POV (yaw -70, %d deg)' % f1['hfov'], color='#1f5fa8', fontsize=8)
    for key, c in (('shot2', '#6a3fa0'), ('shot3', '#b0501a')):
        f = frames[key]
        if not f:
            continue
        cu, cv = G.local(f['cam'][0], f['cam'][1])
        ax.plot(cu, cv, 'o', color=c, ms=7)
        for off, ls in ((-f['hfov'] / 2, '--'), (0, '-'), (f['hfov'] / 2, '--')):
            d = G.dir_of(f['yaw'] + off)
            ax.plot([cu, cu + 16 * d[0]], [cv, cv + 16 * d[1]], color=c, lw=1.2 if off == 0 else 0.7, ls=ls)
        ax.text(cu + 0.3, cv + 0.3, key.replace('shot', 'shot '), color=c, fontsize=8)
    for stop in STOPS_M:
        car, cap, mark, _ = rig_boxes(G, stop, 0.0)
        for bx_, fc in ((car, '#444'), (cap, '#999')):
            cu, cv = G.local(bx_[0][0], bx_[0][1])
            hl, hw = bx_[1][0][1], bx_[1][1][1]
            ax.add_patch(Polygon([(cu - hl, cv - hw), (cu + hl, cv - hw), (cu + hl, cv + hw), (cu - hl, cv + hw)],
                                 closed=True, fc=fc, ec='k', lw=0.6, alpha=0.5 if stop else 0.8))
    ax.text(-4.6, -2.9, 'our carrier + capsule (stopped at 3,400 / 3,402)', fontsize=7.5)
    su, sv = G.local(*[c / 100 for c in STELE_24])
    ax.set_xlim(-14, 22)
    ax.set_ylim(-6, 30)
    ax.set_aspect('equal')
    ax.set_xlabel('u: metres along the road from 3,400 m (travel ->; the road bends left from 3,413)')
    ax.set_ylabel('v: metres LEFT of the road (the slope rises)')
    ax.set_title('V7 the Last Waystation: plan, 0.25 m contours (Current_u16); ISM stones = squares, shrubs = green')

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

    def draw(a2, eye, yaw, pitch, hfov, rig=None, hi=()):
        xs = np.linspace(-1, 1, 121)
        th = math.tan(math.radians(hfov) / 2)
        tv = th / (16 / 9)
        sky = []
        for sx in xs:
            az = yaw + math.degrees(math.atan(sx * th))
            d = np.arange(3.0, 3000.0, 3.0)
            px = eye[0] + d * math.cos(math.radians(az))
            py = eye[1] + d * math.sin(math.radians(az))
            h = G.T.height(px * 100, py * 100)
            el = np.max(np.degrees(np.arctan2(h - eye[2], d)))
            sky.append(math.tan(math.radians(el - pitch)) / tv)
        a2.fill_between(xs, -1, np.clip(sky, -1, 1), color='#c4b49a', lw=0)
        for uu in np.arange(-14, 22.1, 1.0):
            pts = [(*G.world(uu, vv), G.zuv(uu, vv)) for vv in np.arange(-5, 26.1, 0.5)]
            q = [p for p in project(eye, yaw, pitch, pts, hfov) if p is not None]
            if len(q) > 1:
                a2.plot([p[0] for p in q], [p[1] for p in q], color='#a8987e', lw=0.35)
        for vv in np.arange(-5, 26.1, 1.0):
            pts = [(*G.world(uu, vv), G.zuv(uu, vv)) for uu in np.arange(-14, 22.1, 0.5)]
            q = [p for p in project(eye, yaw, pitch, pts, hfov) if p is not None]
            if len(q) > 1:
                a2.plot([p[0] for p in q], [p[1] for p in q], color='#a8987e', lw=0.35)
        edges = [(0, 1), (2, 3), (4, 5), (6, 7), (0, 2), (1, 3), (4, 6), (5, 7), (0, 4), (1, 5), (2, 6), (3, 7)]
        colours = {'wall': '#3d3a36', 'bay1': '#6b4a2a', 'bay2': '#6b4a2a', 'spare': '#111', 'plaque': '#3b2a18',
                   'fire': '#3a342e', 'rocks': '#5c554d', 'woodpile': '#6b4a2a', 'flag': '#8a2a22', 'hut': '#8a7a5c',
                   'stones': '#7d6e5f', 'creep': '#56753c'}

        def box_draw(b, c, lw):
            q = project(eye, yaw, pitch, corners(b), hfov)
            for i0, i1 in edges:
                if q[i0] is not None and q[i1] is not None:
                    a2.plot([q[i0][0], q[i1][0]], [q[i0][1], q[i1][1]], color=c, lw=lw)
        for it in S.items:
            if it['attach'] or (it['ism'] and max(it['size_m']) < 0.35):
                continue
            part = 'canopy' if it['key'].startswith('MV_Annex_Tarp') else ('dock' if it['key'] == 'B01_dock01' else None)
            c = colours.get(it['group'], '#444')
            for b in box3(G, it, part):
                box_draw(b, c, 1.3 if it['group'] in hi else 0.6)
        if rig:
            for b in rig[:2]:
                box_draw(b, '#1f5fa8', 1.4)
            q = project(eye, yaw, pitch, [rig[2]], hfov)[0]
            if q:
                a2.plot(q[0], q[1], 'o', color='#c22', ms=6)
        for g in (-1 / 3, 1 / 3):
            a2.axvline(g, color='w', lw=0.5, alpha=0.6)
            a2.axhline(g, color='w', lw=0.5, alpha=0.6)
    f1 = frames['shot1']
    a1 = frame_ax([0.515, 0.515, 0.47, 0.44], 'CIN_11 shot 1 (0-5 s), POV at 3,400, yaw -70, zoom %d deg, pitch %+.1f, eye %.2f m: '
                  'the lean-to, the spare, the plaque' % (f1['hfov'], f1['pitch'], EYE_M[0]))
    draw(a1, f1['eye'], f1['yaw'], f1['pitch'], f1['hfov'], hi=('spare', 'plaque', 'bay1'))
    f2 = frames['shot2']
    rig = rig_boxes(G, 1.0, 0.0)
    a2 = frame_ax([0.515, 0.05, 0.225, 0.42], 'shot 2 (5-10 s): behind the spare, 50 mm, low')
    draw(a2, f2['cam'], f2['yaw'], f2['pitch'], f2['hfov'], rig=rig, hi=('spare',))
    f3 = frames['shot3']
    if f3:
        a3 = frame_ax([0.76, 0.05, 0.225, 0.42], 'shot 3 (10-16 s): the plaque\'s back, 85 mm, rack to the mark')
        draw(a3, f3['cam'], f3['yaw'], f3['pitch'], HFOV_S3, rig=rig, hi=('plaque',))
    fig.savefig(OUT_PNG, dpi=80)
    return OUT_PNG


# ---------------------------------------------------------------------------- build, checks, write

def build(with_hut=True):
    G = Ground()
    S = compose(G, with_hut=with_hut)
    recs = [to_record(G, S, i, it) for i, it in enumerate([q for q in S.items if not q['rig']])]
    grecs = ground_records(G, S)
    return G, S, recs, grecs


def frames_of(G, S):
    S_nohut = S
    for it in S.items:
        it['optional_off'] = it['optional']            # the frames are judged without the optional hut first
    p1, f1 = best_pitch1(G, S_nohut, EYE_M[0])
    f1_122 = shot1(G, S, EYE_M[1], p1)
    for it in S.items:
        it['optional_off'] = False
    f1_hut = shot1(G, S, EYE_M[0], p1)
    f1_plan = shot1(G, S, EYE_M[0], POV_PITCH_PLAN)
    f1_90 = shot1(G, S, EYE_M[0], p1, hfov=HFOV_POV)
    cam2, tgt2 = shot2_cam(G, S)
    f2 = shot2(G, S, cam2, tgt2)
    f3 = shot3_cam(G, S)
    if f3:
        f3['hfov'] = HFOV_S3
        f3['rows'] = shot3_rows(G, S, f3)
    return dict(shot1=f1, shot1_eye122=f1_122, shot1_with_hut=f1_hut, shot1_plan_pitch=f1_plan, shot1_90=f1_90,
                shot2=f2, shot3=f3, pitch1=p1)


def checks(G, S, recs, grecs, frames, remaining):
    notes, bad = [], []
    for r in recs:
        if r['road_clear_m'] < CLEAR_M:
            bad.append('ROAD %s %s %.2f m' % (r['id'], r['key'], r['road_clear_m']))
    sol = solids_of(S)
    # plan overlaps between solids of different blocks (the canopy counts as its posts)
    for i in range(len(sol)):
        for j in range(i + 1, len(sol)):
            a, b = sol[i], sol[j]
            if a['block'] and a['block'] == b['block']:
                continue
            for pa in plan_polys(G, a):
                for pb in plan_polys(G, b):
                    d = plan_mtv(pa, pb)[0]
                    if d > 0.10:
                        bad.append('CLASH (plan) %s x %s by %.2f m' % (a['role'][:40], b['role'][:40], d))
    tarps = [it for it in S.items if it['key'].startswith('MV_Annex_Tarp')]
    for t in tarps:
        for it in sol:
            if it['block'] == t['block'] or it['rig'] or it['contact'] != 'rigid':
                continue
            for pb in plan_polys(G, it):
                if plan_mtv(obb_uv(G, t), pb)[0] > 0.10 and it['group'] not in ('wall',):
                    bad.append('UNDER CANOPY of %s: %s' % (t['block'], it['role'][:40]))
    # the wall and a canopy must not interpenetrate (the canopy's back posts stand clear of the wall face)
    walls = [it for it in S.items if it['group'] == 'wall']
    for t in tarps:
        for w in walls:
            d = plan_mtv(obb_uv(G, t), obb_uv(G, w))[0]
            if d > 0.05:
                bad.append('CANOPY INTO WALL %s x %s %.2f m' % (t['block'], w['role'][:20], d))
    # the V1 pieces that stay (hut group, hay annex, logs, corral): nothing of V7 on them
    for p in remaining:
        pu, pv = G.local(p['x_cm'] / 100, p['y_cm'] / 100)
        ax_ = G.dir_of(p['yaw'])
        ay_ = G.dir_of(p['yaw'] + 90)
        hx, hy = p['size_m'][0] / 2, p['size_m'][1] / 2
        poly = [(pu + sx * hx * ax_[0] + sy * hy * ay_[0], pv + sx * hx * ax_[1] + sy * hy * ay_[1])
                for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
        for it in S.items:
            if it['attach']:
                continue
            if plan_mtv(obb_uv(G, it), poly)[0] > 0.02:
                (notes if it['optional'] else bad).append('V1 %s (%s) x V7 %s' % (p['id'], p['key'], it['role'][:40]))
    su, sv = G.local(STELE_24[0] / 100, STELE_24[1] / 100)
    near = min(math.hypot(it['u'] - su, it['v'] - sv) for it in S.items)
    notes.append('Stele_WayStone_24 (the I05 way-stone on the bend) is %.1f m from the nearest V7 piece' % near)
    for it in S.items:
        if it['group'] in ('creep', 'stones') and S.on_lane(it['u'], it['v'], 0.1):
            bad.append('ON PATH %s at (%.1f, %.1f)' % (it['key'], it['u'], it['v']))
    left = clash_pairs(G, S)
    for d, allow, a, b in left:
        bad.append('ISM OVERLAP %s into %s by %.2f m (allowed %.2f)' % (a['key'], b['key'], d, allow))
    mv = sorted(S.moved[id(it)] for it in S.items if it['ism'])
    notes.append('ISM declash: %d of %d ISM pieces moved (max %.2f m), %d left out; %d overlaps left beyond %s'
                 % (sum(1 for m in mv if m > 0.005), len(mv), max(mv) if mv else 0.0, len(S.dropped), len(left), ISM_ALLOW))
    # contact predictions (FLOAT rules): rigid pieces plumb with every sample at/below grade; the relief they bury
    for it in S.items:
        if it['ism'] or it['attach'] or it['rig']:
            continue
        p = predicted(G, it)
        if it['contact'] == 'rigid':
            if max(p['gaps']) > 5.0:
                bad.append('FLOAT %s: a sample %.0f cm over the ground' % (it['role'][:40], max(p['gaps'])))
            notes.append('%-44s rigid: bottom %.2f, ground %.2f..%.2f, uphill side buried %.2f m%s'
                         % (it['role'][:44], p['bottom'], p['gmin'], p['gmax'], p['buried_max'],
                            ' (optional)' if it['optional'] else ''))
        else:
            if min(abs(g) for g in p['gaps']) > 5.0 and min(p['gaps']) > 5.0:
                bad.append('FLOAT %s: nothing within 5 cm' % it['role'][:40])
    for w in walls:
        p = predicted(G, w)
        ax_, ay_ = site_axes(G, w)
        fu, fv = w['u'] + ax_[0] * w['size_m'][0] / 2, w['v'] + ax_[1] * w['size_m'][0] / 2
        front = [G.zuv(fu + ay_[0] * s_ * w['size_m'][1] / 2, fv + ay_[1] * s_ * w['size_m'][1] / 2) for s_ in (-0.9, 0, 0.9)]
        notes.append('%s: yard face shows %.2f..%.2f m, top at %.2f' % (w['role'][:16], p['top'] - max(front),
                                                                     p['top'] - min(front), p['top']))
    tops = [round(predicted(G, w)['top'], 2) for w in walls]
    notes.append('wall tops step %s (m; joint steps %s)' % (tops, [round(abs(a - b), 2) for a, b in zip(tops[:-1], tops[1:])]))
    # the story frames
    f1 = frames['shot1']
    for k in ('spare', 'cradle', 'plaque', 'bay1'):
        if not inside(f1['boxes'].get(k), 0.0 if k == 'bay1' else 0.03):
            (notes if k == 'bay1' else bad).append('SHOT 1: %s not wholly in frame %s' % (k, f1['boxes'].get(k)))
    if f1['spare_face_visible'] < 0.8:
        bad.append('SHOT 1: the spare\'s face is %.0f %% hidden' % (100 * (1 - f1['spare_face_visible'])))
    for t in f1['text']:
        if t['visible'] < 1.0 or not t['in_frame']:
            bad.append('SHOT 1: plaque panel %d lettering not wholly visible (%s)' % (t['panel'], t))
        if t['cap_px_h'] < 14.0:
            bad.append('SHOT 1: plaque panel %d capitals %.1f px at 1080p (< 14)' % (t['panel'], t['cap_px_h']))
    b = f1['boxes']
    if b['plaque'] and b['spare'] and not (b['plaque'][1] < b['spare'][0] or b['plaque'][0] > b['spare'][1]):
        bad.append('SHOT 1: the plaque overlaps the spare on screen')
    f2 = frames['shot2']
    for r in f2['rows']:
        if r['stop'] == 1.0 or (r['lat'] == 0.0):
            if not r['in_frame'] or r['visible'] < 0.8:
                bad.append('SHOT 2: rig not framed/visible at stop %.0f lat %.0f: %s' % (r['stop'], r['lat'], r))
    if f2['plaque'] and inside(f2['plaque']) and any(r['carrier'] and not (f2['plaque'][1] < r['carrier'][0] or
                                                                          f2['plaque'][0] > r['carrier'][1])
                                                     for r in f2['rows'] if r['lat'] == 0.0):
        bad.append('SHOT 2: the plaque stands in front of our carrier')
    if not frames['shot3']:
        bad.append('SHOT 3: no insert camera frames the back lettering and the capsule mark together')
    # the committed contact judge's working copy, when it carries the offline estimator: a cross-check only
    import setdress_contact as sc
    if hasattr(sc, 'offline_reports'):
        reps, items = sc.offline_reports([r for r in recs if not r.get('optional')],
                                         lambda x, y: G.z(x / 100.0, y / 100.0) * 100.0)
        v, w = sc.judge(reps, items)
        notes.append('setdress_contact.offline_reports + judge (working copy, cross-check): %d violations %s'
                     % (len(v), [tuple(x[:2]) for x in v][:8]))
    return notes, bad


def cin11_keys(G, frames):
    """plan_cin11-format camera keys (t, x, y, z, roll, pitch, yaw, interp) in the CIN_11 local frame."""
    f1, f2, f3 = frames['shot1'], frames['shot2'], frames['shot3']
    eye_z = round(EYE_M[0] * 100, 1)
    out = dict(
        note='Recommended re-aim of build_cinematics.plan_cin11 (its docstring: "positions are first-pass guesses until '
             'the V7 dressing exists"). Local frame: +X up-road, +Y right, +Z up from the road at the origin (the pawn '
             'projected on the spline, ~3,400). Not applied: build_cinematics.py is the cinematics lane\'s file.',
        CIN11_S1_POV90=[[0.0, 0, 0, eye_z, 0, round(f1['pitch'], 1), 0, 'cubic'],
                        [1.5, 0, 0, eye_z, 0, round(f1['pitch'], 1), POV_YAW_LOCAL, 'cubic']],
        CIN11_S1_POV50=[[2.5, 0, 0, eye_z, 0, round(f1['pitch'], 1), POV_YAW_LOCAL, 'constant']],
    )
    x, y, z = to_local(G, f2['cam'])
    yl = local_yaw(G, f2['yaw'])
    F, _, _ = cam_basis(f2['yaw'], f2['pitch'])
    x2, y2, z2 = to_local(G, tuple(np.array(f2['cam']) + F * 0.30))
    out['CIN11_S2_Cradle'] = [[5.0, x, y, z, 0, round(f2['pitch'], 1), yl, 'cubic'],
                              [10.0, x2, y2, z2, 0, round(f2['pitch'], 1), yl, 'cubic']]
    if f3:
        x, y, z = to_local(G, f3['cam'])
        yl = local_yaw(G, f3['yaw'])
        out['CIN11_S3_Plaque'] = [[10.0, x, y, z, 0, round(f3['pitch'], 1), yl, 'cubic'],
                                  [16.0, x, y, z, 0, round(f3['pitch'], 1), round(yl + 1.0, 1), 'cubic']]
        out['CIN11_S3_focus_cm'] = [[10.0, round(f3['rack_near_m'] * 100)], [12.0, round(f3['rack_near_m'] * 100)],
                                    [14.0, round(f3['rack_far_m'] * 100)]]
    return out


def views(G, S, frames):
    Yf = S.frame['Y']
    fx, fy = G.world(*Yf(A1, BS))
    focus = [round(fx * 100, 1), round(fy * 100, 1), round((G.zuv(*Yf(A1, BS)) + 0.7) * 100, 1)]
    out = []

    def cam(name, x, y, z, look=None, note=''):
        out.append(dict(name=name, cam_cm=[round(x * 100, 1), round(y * 100, 1), round(z * 100, 1)],
                        look_cm=look or focus, note=note))
    for name, s in (('carrier_a', 3300.0), ('carrier_b', 3350.0), ('carrier_c', 3385.0)):
        u, _ = G.road_uv(s)
        x, y = G.world(u, 0.0)
        cam(name, x, y, G.z(x, y) + 2.5, note='the long straight, carrier eye (capture_look EYE 2.5 m) at road %d m' % s)
    for name, (a, b, h) in (('orbit_a', (-9.0, 10.0, 2.2)), ('orbit_b', (8.0, 10.5, 2.4)), ('orbit_c', (0.0, 13.0, 1.7))):
        u, v = Yf(a, b)
        x, y = G.world(u, v)
        cam(name, x, y, G.zuv(u, v) + h)
    u, v = Yf(A1 + 1.6, BC + 2.3)
    x, y = G.world(u, v)
    lu, lv = Yf(A1 + 1.2, BC + 0.5)
    lx, ly = G.world(lu, lv)
    cam('contact', x, y, G.zuv(u, v) + 0.9, [round(lx * 100, 1), round(ly * 100, 1), round(G.zuv(lu, lv) * 100 + 10, 1)],
        note='the cradle feet and a canopy post at the ground: packing stones, sink, the bay floor')
    u, v = Yf(0.0, 22.0)
    x, y = G.world(u, v)
    cam('high34', x, y, G.zuv(u, v) + 18.0)
    u, v = G.road_uv(3120.0)
    x, y = G.world(u + 5, 60.0)
    cam('far300', x, y, G.z(x, y) + 25.0, note='from down the long straight, 280 m back and up the left slope')
    return out


def write(G, S, recs, grecs, frames, notes, bad, appr, cleared):
    cu, cv = S.frame['Y']((A1 + S.frame['A2']) / 2, 2.5)
    cx, cy = G.world(cu, cv)
    vw = views(G, S, frames)
    r = 20.0
    pts = [(cx * 100, cy * 100)] + [(v['cam_cm'][0], v['cam_cm'][1]) for v in vw if v['name'] not in ('far300', 'high34')]
    box = [min(p[0] for p in pts) - (r + 30) * 100, min(p[1] for p in pts) - (r + 30) * 100,
           max(p[0] for p in pts) + (r + 30) * 100, max(p[1] for p in pts) + (r + 30) * 100]
    solo = [x for x in recs if not x['ism']]
    ism = [x for x in recs if x['ism']]
    rig = rig_records(G, S, recs)
    # keep-out for the S19 outpost lanes: the V7 footprint + 1.5 m, and the three CIN_11 camera corridors
    hull = []
    for it in S.items:
        if it['attach'] or it['optional']:
            continue
        hull += obb_uv(G, it, pad=1.5)
    hull = convex_hull(hull)
    corridors = []
    for key in ('shot2', 'shot3'):
        f = frames[key]
        if f:
            c = G.local(f['cam'][0], f['cam'][1])
            corridors.append(dict(shot=key, from_uv=[round(c[0], 2), round(c[1], 2)], to_uv=[-3.0, 0.0], width_m=4.0))
    site = dict(
        id=SID, story_set=SET, road_site=ROAD_SITE, name='Nefr Rzag, the Last Waystation (V7)', kind='waystation berths',
        order=2, road_m=int(S0), side='left', lateral_m=-round(math.hypot(cu, cv)), centre_cm=[round(cx * 100, 1),
                                                                                                round(cy * 100, 1),
                                                                                                round(G.z(cx, cy) * 100, 1)],
        road_yaw=round(G.road_yaw, 1), radius_m=r, zone='Z4 Mountain foot',
        storm='the storm thins; wind rising; clearer light', role='rest (the hinge)',
        story='B11: CIN_11 (the spare dead in its cradle, the plaque), then the Elder\'s tape (RADIO_B11_01..03); CP2_WAYSTATION',
        decay=1, style='bazaar stone back wall + MedievalVillage timber and tarp lean-tos; riveted iron cradles (steampunk)',
        layout='\n'.join([
            '  (terrace behind the wall: dead shrubs, the way up round the wall end; optional keeper\'s hut)',
            '  outcrop | ====== back wall, AB fort wall x4 (2.4 m showing) ====== | woodpile',
            '          [bay 1: tarp lean-to | iron cradle + DEAD SPARE]  [bay 2: tarp | EMPTY cradle, crates, jar, rope]',
            '   cold fire ring, log + stone seats, lantern     .... trodden line along the berths ....      flag pole',
            '                      the spur  --> [PLAQUE, two posts]  (road face: the rule; back: TAKE WHAT IT CARRIED.)',
            '  ======================= road (3,390-3,413 m, then the bend left) ========================']),
        notes='Story set V7. Own site id (tag SD_V7_LastWaystation); the S19 V1 pieces it replaces are cleared with the V1 '
              'tool by id (clear_v1). The dead spare, the plaque lettering and the banner are this set\'s `rig` step. '
              'Nothing religious, nothing modern; the lantern and the fire are cold.',
        story_owned=['V7 the Last Waystation (this file is the story set)'], verify_only=False, layer='road', poi=None,
        load_box_cm=[round(v) for v in box],
        counts=dict(placements=len(recs), actors=len(solo) + len({(x['group'], x['asset']) for x in ism}) + 3,
                    ism_instances=len(ism), physics=sum(1 for x in solo if x['settle']['mode'] == 'physics'),
                    batch01=sum(1 for x in solo if '/Batch01/' in x['asset']), decals=len(grecs),
                    rig=3 + len(rig['lettering']['lines']), optional=sum(1 for x in recs if x.get('optional'))),
        views=[{k: v[k] for k in ('name', 'cam_cm', 'look_cm')} for v in vw],
        view_notes={v['name']: v['note'] for v in vw if v['note']},
        placements=recs, ground=grecs, units=[], waivers=[], rig=rig,
        clear_v1=dict(site=ROAD_SITE, ids=V1_CLEAR, what=[{'id': p['id'], 'key': p['key'], 'group': p['group']} for p in cleared],
                      why='000/001 are the V7 stand-ins; 002-007 (bags, lantern post, lantern, rope) and 015 (the flag) '
                          'were placed round the stand-in cradle and stand inside V7\'s berths; V7 remakes each role'),
        ambient_repoint=[dict(old='S19_LastWaystation_001', new=[x['id'] for x in recs if x['key'].startswith('MV_Annex_Tarp')],
                              method='wpo_cloth'),
                         dict(old='S19_LastWaystation_015', new=[rig['banner']['id']], method='wpo_cloth (pin pole)'),
                         dict(old='S19_LastWaystation_006/007', new=[], method='none: V7\'s lantern is set down, not hung')],
        keep_out=dict(uv=[[round(a, 2), round(b, 2)] for a, b in hull],
                      cm=[[round(G.world(a, b)[0] * 100, 1), round(G.world(a, b)[1] * 100, 1)] for a, b in hull],
                      camera_corridors=corridors,
                      note='for the S19 outpost lanes (V1/V2): place nothing inside this hull, nor in the CIN_11 corridors'),
        cin11=cin11_keys(G, frames),
        v2=dict(frame=dict(origin_road_m=S0, origin_cm=[round(G.o[0] * 100, 1), round(G.o[1] * 100, 1)],
                           u='along travel', v='left of travel',
                           row=dict(W0_uv=[round(c, 3) for c in S.frame['W0']], e_uv=[round(c, 4) for c in S.frame['e']],
                                    n_uv=[round(c, 4) for c in S.frame['n']],
                                    note='berth row frame: a along the wall (up-road), b out from the wall face')),
                lanes=S.lanes, frames=json.loads(json.dumps(frames, default=float)), approach=appr, checks=notes,
                violations=bad),
    )
    doc = dict(generated_by='Tools/World/story_sets/v7_waystation.py', method='docs/world/SETDRESS_V2.md',
               design='docs/world/story_sets/V7.md', level='/Game/level/Saskarta_WP',
               conventions=dict(xy='world cm; yaw = UE yaw deg', bounds='x_cm/y_cm is the mesh BOUNDS CENTRE',
                                ground='decal patches: DecalActor pitch -90, yaw, size (depth/2, width/2, length/2)',
                                contact='rigid | rest | lie | stack (SETDRESS_V2.md section 3)',
                                optional='Tripo models still to import: placed only with --with-optional',
                                site_uv='u m along travel from road 3,400, v m left of travel'),
               rejected=[], checks=[], sites=[site])
    with open(OUT_JSON, 'w', encoding='utf8') as fh:
        json.dump(doc, fh, indent=1, ensure_ascii=False, default=float)
    return site


def convex_hull(pts):
    pts = sorted(set((round(a, 3), round(b, 3)) for a, b in pts))
    if len(pts) < 3:
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


# ---------------------------------------------------------------------------- editor steps of this set

RIG_BODY = r'''
have = site_actors(SITE)
TAGS = ['SetDress', 'SD_' + SITE, 'SD_soft', 'PB_FoliageExclude']


def tagged(a, rid, folder):
    a.set_editor_property('tags', [unreal.Name(t) for t in TAGS + ['SDID_' + rid]])
    a.set_actor_label('SD_' + rid)
    a.set_folder_path(folder)


def mesh_box(a):
    """World centre, the actor's X / Y / Z axes and the scaled local half extents of a static mesh actor."""
    comp = a.static_mesh_component
    b = comp.static_mesh.get_bounds()
    s = a.get_actor_scale3d().x
    r = a.get_actor_rotation()
    ax = axes(r.yaw, r.pitch, r.roll)
    l = a.get_actor_location()
    o = apply(ax, (b.origin.x * s, b.origin.y * s, b.origin.z * s))
    return (l.x + o[0], l.y + o[1], l.z + o[2]), ax, (b.box_extent.x * s, b.box_extent.y * s, b.box_extent.z * s)


if DO_SPARE:
    sp = SPARE
    cr = have.get('SD_' + sp['cradle'])
    if cr is None:
        print('RIG no cradle ' + sp['cradle'] + ': place and settle first')
    elif ('SD_' + sp['id']) in have:
        print('RIG spare exists')
    else:
        ax = axes(sp['yaw'], 0.0, 0.0)
        hx, hy = sp['size_m'][0] * 50.0, sp['size_m'][1] * 50.0
        zs = []
        for sx in (-1, 1):
            for sy in (-1, 1):
                q = apply(ax, (sx * (hx - 20.0), sy * (hy - 25.0), 0.0))
                h = trace_ground(sp['x_cm'] + q[0], sp['y_cm'] + q[1], sp['ground_z_cm'] + 3000.0, sp['ground_z_cm'] - 3000.0, [])
                if h is not None:
                    zs.append(h[0])
        z = max(zs) if len(zs) > 0 else 0.0
        a = eas.spawn_actor_from_class(unreal.SkeletalMeshActor, V(sp['x_cm'], sp['y_cm'], z), unreal.Rotator(roll=0.0, pitch=0.0, yaw=sp['yaw']))
        comp = a.skeletal_mesh_component
        sk = unreal.load_asset(sp['asset'])
        if hasattr(comp, 'set_skeletal_mesh_asset'):
            comp.set_skeletal_mesh_asset(sk)
        else:
            comp.set_skeletal_mesh(sk)
        comp.set_animation_mode(unreal.AnimationMode.ANIMATION_SINGLE_NODE)
        comp.override_animation_data(unreal.load_asset(sp['anim']), False, False, sp['anim_pos'], 0.0)
        comp.set_editor_property('cast_shadow', True)
        tagged(a, sp['id'], sp['folder'])
        print('RIG spare at z ' + str(round(z, 1)) + ' wheel grounds ' + str([round(v, 1) for v in zs]))

if DO_BANNER:
    bn = BANNER
    pole = have.get('SD_' + bn['pole'])
    if pole is None:
        print('RIG no pole ' + bn['pole'])
    else:
        pc, pax, pe = mesh_box(pole)
        ptop = pc[2] + abs(pax[2][2]) * pe[2]
        a = have.get('SD_' + bn['id'])
        if a is None:
            a = eas.spawn_actor_from_object(unreal.load_asset(bn['asset']), V(pc[0], pc[1], ptop), unreal.Rotator(roll=0.0, pitch=0.0, yaw=bn['yaw']))
            a.set_actor_scale3d(V(bn['scale'], bn['scale'], bn['scale']))
            a.static_mesh_component.set_collision_profile_name('NoCollision')
            a.static_mesh_component.set_editor_property('ld_max_draw_distance', 25000.0)
            tagged(a, bn['id'], bn['folder'])
        bc, bax, be = mesh_box(a)
        d = (math.cos(math.radians(bn['yaw'])), math.sin(math.radians(bn['yaw'])))
        want = (pc[0] + d[0] * (max(pe[0], pe[1]) + bn['gap_cm'] + be[0]), pc[1] + d[1] * (max(pe[0], pe[1]) + bn['gap_cm'] + be[0]), ptop - bn['drop_cm'] - be[2])
        l = a.get_actor_location()
        a.set_actor_location(V(l.x + want[0] - bc[0], l.y + want[1] - bc[1], l.z + want[2] - bc[2]), False, True)
        print('RIG banner pole top ' + str(round(ptop, 1)) + ' banner bottom ' + str(round(want[2] - be[2], 1)))

if DO_TEXT:
    tx = TEXT
    bd = have.get('SD_' + tx['board'])
    if bd is None:
        print('RIG no board ' + tx['board'])
    else:
        bc, bax, be = mesh_box(bd)
        bottom = bc[2] - be[2]
        made = 0
        for ln in tx['lines']:
            if ('SD_' + ln['id']) in have:
                continue
            sgn = 1.0 if ln['face'] == 'front' else -1.0
            off = sgn * (be[1] + tx['out_cm'])
            z = bottom + ln['z_frac'] * 2.0 * be[2] + ln['dz_cm']
            p = (bc[0] + bax[1][0] * off, bc[1] + bax[1][1] * off, z)
            r = bd.get_actor_rotation()
            yaw = r.yaw + 90.0 if sgn > 0 else r.yaw - 90.0
            a = eas.spawn_actor_from_class(unreal.TextRenderActor, V(p[0], p[1], p[2]), unreal.Rotator(roll=0.0, pitch=0.0, yaw=yaw))
            t = a.text_render
            t.set_editor_property('text', ln['text'])
            t.set_editor_property('world_size', tx['world_size_cm'])
            t.set_editor_property('horizontal_alignment', unreal.HorizTextAligment.EHTA_CENTER)
            t.set_editor_property('vertical_alignment', unreal.VerticalTextAligment.EVRTA_TEXT_CENTER)
            t.set_editor_property('text_render_color', unreal.Color(r=tx['rgb'][0], g=tx['rgb'][1], b=tx['rgb'][2], a=255))
            t.set_editor_property('ld_max_draw_distance', 6000.0)
            tagged(a, ln['id'], tx['folder'])
            made += 1
        print('RIG lettering made ' + str(made) + ' board bottom ' + str(round(bottom, 1)) + ' half extents ' + str([round(v, 1) for v in be]))
print('RIG DONE')
'''

RIGCHECK_BODY = r'''
have = site_actors(SITE)
sp = have.get('SD_' + SPARE['id'])
cr = have.get('SD_' + SPARE['cradle'])
if sp is None or cr is None:
    print('RIGCHECK missing spare or cradle')
else:
    o, e = sp.get_actor_bounds(False)
    print('RIGCHECK spare bounds centre ' + str([round(o.x, 1), round(o.y, 1), round(o.z, 1)]) + ' ext ' + str([round(e.x, 1), round(e.y, 1), round(e.z, 1)]))
    r = cr.get_actor_rotation()
    ax = axes(r.yaw, 0.0, 0.0)
    l = cr.get_actor_location()
    oc, ec = cr.get_actor_bounds(False)
    hits = []
    for zc in (40.0, 100.0):
        for s in (-1, 1):
            a0 = (oc.x + ax[0][0] * s * 200.0, oc.y + ax[0][1] * s * 200.0, oc.z - ec.z + zc)
            h = hit_of(syslib.line_trace_single(world, V(a0[0], a0[1], a0[2]), V(oc.x, oc.y, a0[2]), unreal.TraceTypeQuery.TRACE_TYPE_QUERY1, True, [sp], unreal.DrawDebugTrace.NONE, True))
            d = None
            if h is not None:
                t = h.to_tuple()
                if t[0]:
                    p = t[IMPACT_POINT]
                    d = round(((p.x - oc.x) ** 2 + (p.y - oc.y) ** 2) ** 0.5, 1)
            hits.append(d)
    print('RIGCHECK cradle tower inner faces from its centre at 40 / 100 cm (cm): ' + str(hits) + ' spare half width ' + str(SPARE['size_m'][0] * 50.0))
    h = trace_down(oc.x, oc.y, oc.z + ec.z + 50.0, oc.z - ec.z - 50.0, [sp])
    print('RIGCHECK cradle beam top at its centre ' + (str(round(h[0], 1)) if h is not None else 'none') + ' spare bottom ' + str(round(o.z - e.z, 1)))
    comp = sp.skeletal_mesh_component
    mats = [comp.get_material(i) for i in range(comp.get_num_materials())]
    for m in mats:
        if m is not None and isinstance(m, unreal.MaterialInstance):
            names = unreal.MaterialEditingLibrary.get_scalar_parameter_names(m)
            print('RIGCHECK material ' + m.get_name() + ' scalars ' + str([str(n) for n in names][:24]))
print('RIGCHECK DONE')
'''


def custom_step(step, argv):
    import place_setdress as ps
    ap = argparse.ArgumentParser(prog='v7_waystation.py ' + step)
    ap.add_argument('--owner', default=os.environ.get('SETDRESS_OWNER', ''))
    ap.add_argument('--no-gate-check', action='store_true')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--only', default='spare,banner,text', help='rig: which pieces (spare,banner,text)')
    ap.add_argument('--size', default='1600x900')
    ap.add_argument('--port', type=int, default=int(os.environ.get('HAYBA_PORT', 52342)))
    args = ap.parse_args(argv)
    doc = json.load(open(OUT_JSON, encoding='utf8'))
    site = doc['sites'][0]
    rig = {k: ({kk: vv for kk, vv in v.items() if kk != 'note'} if isinstance(v, dict) else v)
           for k, v in site['rig'].items()}
    if step == 'rig':
        ps.gate_check(argparse.Namespace(owner=args.owner, dry_run=args.dry_run, no_gate_check=args.no_gate_check), 'place')
    R = ps.Runner(args)
    if step == 'rig':
        want = set(args.only.split(','))
        R.send('%s_rig' % SID, ps.build_script(RIG_BODY, SITE=SID, SPARE=rig['spare'], BANNER=rig['banner'],
                                               TEXT=rig['lettering'], DO_SPARE='spare' in want,
                                               DO_BANNER='banner' in want, DO_TEXT='text' in want))
        if not args.dry_run:
            st = ps.read_state(SID)
            st['dirty'] = True
            ps.write_state(SID, st)
        return
    if step == 'rigcheck':
        R.send('%s_rigcheck' % SID, ps.build_script(RIGCHECK_BODY, SITE=SID, SPARE=rig['spare']))
        return
    if step == 'cinshots':
        # the three CIN_11 frames at their own lenses (place_setdress capture fixes 60 deg): POV 50, 50 mm, 85 mm.
        import time
        if not args.dry_run and ps.editor_minimized():
            raise SystemExit('the editor window is minimized: every capture would be black. Capture when it is visible.')
        ps.SHOT_DIR_REL = 'Screenshots/SetDressV2'
        w, h = [int(v) for v in args.size.split('x')]
        for v in site['v2']['cin_views']:
            label = 'SD_CAPTURE_%s_%s' % (SID, v['name'])
            R.send('%s_shoot' % SID, ps.build_script(ps.CAPTURE_SHOOT_BODY, CAM=v['cam_cm'], LOOK=v['look_cm'], LABEL=label,
                                                     SIZE=[w, h], FOV=v['fov']))
            if not args.dry_run:
                time.sleep(ps.CAPTURE_SETTLE_S)
            R.send('%s_export' % SID, ps.build_script(ps.CAPTURE_EXPORT_BODY, LABEL=label, NAME=v['name'],
                                                      OUT_REL='%s/%s' % (ps.SHOT_DIR_REL, SID)))
        return


def run_editor(argv, materials=False):
    """Run a place_setdress.py step (or build_setdress_materials.py) with the V2 site file swapped for V7.json."""
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
    sys.argv = ['place_setdress.py', step] + ([] if step in ('list', 'probe') else [SID]) + rest
    ps.main()


def cin_views(G, frames):
    out = []
    f1 = frames['shot1']
    F, _, _ = cam_basis(f1['yaw'], f1['pitch'])
    e = np.array(f1['eye'])
    out.append(dict(name='cin11_s1', cam_cm=[round(c * 100, 1) for c in e], look_cm=[round(c * 100, 1) for c in e + F * 10],
                    fov=round(f1['hfov'], 2)))
    for key, name, fov in (('shot2', 'cin11_s2', HFOV_S2), ('shot3', 'cin11_s3', HFOV_S3)):
        f = frames[key]
        if not f:
            continue
        F, _, _ = cam_basis(f['yaw'], f['pitch'])
        c = np.array(f['cam'])
        out.append(dict(name=name, cam_cm=[round(x * 100, 1) for x in c], look_cm=[round(x * 100, 1) for x in c + F * 10],
                        fov=round(fov, 2)))
    return out


def main():
    if len(sys.argv) > 1 and sys.argv[1] == 'editor':
        return run_editor(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == 'materials':
        return run_editor(sys.argv[2:], materials=True)
    if len(sys.argv) > 1 and sys.argv[1] in ('rig', 'rigcheck', 'cinshots'):
        return custom_step(sys.argv[1], sys.argv[2:])
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--no-plot', action='store_true')
    args = ap.parse_args()
    G, S, recs, grecs = build()
    remaining, cleared = v1_remaining()
    frames = frames_of(G, S)
    appr = approach_rows(G, S)
    notes, bad = checks(G, S, recs, grecs, frames, remaining)
    site = write(G, S, recs, grecs, frames, notes, bad, appr, cleared)
    doc = json.load(open(OUT_JSON, encoding='utf8'))
    doc['sites'][0]['v2']['cin_views'] = cin_views(G, frames)
    with open(OUT_JSON, 'w', encoding='utf8') as fh:
        json.dump(doc, fh, indent=1, ensure_ascii=False)
    c = site['counts']
    print('%s (%s): %d placements (%d optional), %d actors, %d ISM instances, %d decals, %d rig pieces' % (
        SID, SET, c['placements'], c['optional'], c['actors'], c['ism_instances'], c['decals'], c['rig']))
    print('road clearance min %.2f m' % min(r['road_clear_m'] for r in recs))
    for n_ in notes:
        print(' ', n_)
    f1 = frames['shot1']
    print('shot 1 (pitch %+.1f, eye %.2f): boxes %s' % (f1['pitch'], EYE_M[0], f1['boxes']))
    print('   spare face visible %.2f; lettering %s' % (f1['spare_face_visible'], f1['text']))
    f = frames['shot1_eye122']
    print('shot 1 at eye 1.22: boxes %s face %.2f' % (f['boxes'], f['spare_face_visible']))
    print('shot 1 at the plan pitch %+.1f: boxes %s' % (POV_PITCH_PLAN, frames['shot1_plan_pitch']['boxes']))
    print('shot 1 with the optional hut: hut box %s' % frames['shot1_with_hut']['boxes'].get('hut'))
    f2 = frames['shot2']
    print('shot 2: cam local %s yaw %.1f pitch %.1f, spare box %s (nearest %.2f m), plaque %s' % (
        to_local(G, f2['cam']), local_yaw(G, f2['yaw']), f2['pitch'], f2['spare'], f2['spare_near_m'], f2['plaque']))
    for r in f2['rows']:
        print('   ', r)
    f3 = frames['shot3']
    if f3:
        print('shot 3: cam local %s yaw %.1f pitch %.1f D %.2f phi %.0f text %s mark %s rack %.2f -> %.2f m, lettering %s' % (
            to_local(G, f3['cam']), local_yaw(G, f3['yaw']), f3['pitch'], f3['D'], f3['phi'], f3['text'], f3['mark'],
            f3['rack_near_m'], f3['rack_far_m'], f3['lettering']))
        for r in f3['rows']:
            print('   ', r)
    print('approach:')
    for r in appr:
        print('   ', r)
    if not args.no_plot:
        print('plot', plot(G, S, recs, frames, remaining, cleared))
    print('wrote', OUT_JSON)
    if bad:
        print('VIOLATIONS:')
        for b in bad:
            print('  ', b)
        sys.exit(1)


if __name__ == '__main__':
    main()
