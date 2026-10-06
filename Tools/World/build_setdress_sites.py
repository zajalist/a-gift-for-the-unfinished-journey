"""Plan the Saskarta set dressing offline and write Tools/World/setdress_sites.json.

    python Tools/World/build_setdress_sites.py           # write the JSON and print the per-site table
    python Tools/World/build_setdress_sites.py --md      # also print the markdown count table for the plan

Every site is authored in a road frame: u metres along the road (+ = the player's direction),
v metres across it (+ = right of travel), at the site's road metre. This script turns that into
world XY with the road polyline from Tools/Story/build_road_profile.py, reads the planned ground
height and slope from the Gaea heightmap (Saved/TerrainRebuild/Current_u16.png), and checks:

- the road core: every footprint stays >= CLEAR_M from the road centreline (the 4.5 m ribbon
  half-width + 0.5 m); a violating item is nudged away from the nearest road point;
- keep-clear cones (the boot frame) and the collapse-set exclusion (nothing at 4,760-4,860 m);
- footprint overlap inside a site (oriented rectangles, separating axes), except items marked
  stack/attach and rubble; a violating item is nudged, then reported;
- slope under buildings (warning above 12 deg; the editor settle buries the uphill side).

Nothing here talks to Unreal. The editor lane runs Tools/World/place_setdress.py, which spawns,
settles (traces; emulated physics), checks and captures in the live editor.
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
sys.path.insert(0, os.path.join(ROOT, 'Tools', 'Story'))
sys.path.insert(0, HERE)
import build_road_profile as brp  # noqa: E402
import setdress_catalog  # noqa: E402
import setdress_offroad  # noqa: E402

OUT = os.path.join(HERE, 'setdress_sites.json')
CLEAR_M = 5.0            # road centreline -> footprint edge
EYE_M = 2.5              # carrier camera height (Tools/Look/capture_look.py EYE_CM)
SUMMIT_XY = (287480.0, 444050.0)
COLLAPSE_EXCLUSION = (4760.0, 4860.0, 30.0)   # road m from, to, half-width m: the B18-B20 set stays empty
ZONES = [(0, 1625, 'Z1 Valley'), (1625, 2050, 'Z2 Ridge'), (2050, 2755, 'Z3 Basin'),
         (2755, 3625, 'Z4 Mountain foot'), (3625, 4380, 'Z5 Cloud'), (4380, 5100, 'Z6 Summit')]
STORM = {
    'Z1 Valley': 'storm-dusk at its worst: dust sheets and gusts; cloth and tarps flap (WPO); dust drifts on the lee side of walls; landmarks must read as silhouettes through 3 km transmittance ~0.15 haze',
    'Z2 Ridge': 'the single crest gust (B06) catches the banner; strongest wind on the road; keep tall pieces off the vista side',
    'Z3 Basin': 'heavy, still, dusty air; low fog cards and heat shimmer at the platform and works; Geiger peak; the storm is worst here with the valley',
    'Z4 Mountain foot': 'the storm thins; wind rising; clearer light on the cistern stone',
    'Z5 Cloud': 'inside the cloud deck: drizzle and fog, 50-150 m visibility; dressing is near-road silhouettes only, nothing that needs to read from far',
    'Z6 Summit': 'above the cloud: clear, calm, gold light; bare wind-scoured rock; the fewest objects on the road',
}

# Category defaults: settle mode, sink cm, max tilt deg (normal alignment clamp), random tilt deg
# (emulated physics / scatter), z rule for trace ('min' buries the uphill side, 'mean' averages),
# ISM, collision, foliage exclusion tag.
CAT = {
    'building':   dict(settle='trace', sink=12, max_tilt=2, rand_tilt=0, z_rule='min', ism=False, collide=True, exclude=True),
    'wall':       dict(settle='trace', sink=8, max_tilt=4, rand_tilt=0, z_rule='min', ism=False, collide=True, exclude=True),
    'stone':      dict(settle='trace', sink=6, max_tilt=8, rand_tilt=0, z_rule='min', ism=False, collide=True, exclude=True),
    'rubble_big': dict(settle='physics', sink=4, max_tilt=30, rand_tilt=15, z_rule='max', ism=False, collide=True, exclude=True),
    'rubble':     dict(settle='trace', sink=3, max_tilt=30, rand_tilt=25, z_rule='mean', ism=True, collide=False, exclude=False),
    'prop':       dict(settle='physics', sink=2, max_tilt=15, rand_tilt=3, z_rule='max', ism=False, collide=True, exclude=True),
    'prop_static': dict(settle='trace', sink=2, max_tilt=6, rand_tilt=0, z_rule='mean', ism=False, collide=True, exclude=True),
    'wood':       dict(settle='physics', sink=2, max_tilt=20, rand_tilt=5, z_rule='max', ism=False, collide=True, exclude=False),
    'wood_post':  dict(settle='trace', sink=25, max_tilt=3, rand_tilt=0, z_rule='mean', ism=False, collide=True, exclude=False),
    'cloth':      dict(settle='trace', sink=0, max_tilt=10, rand_tilt=0, z_rule='mean', ism=False, collide=False, exclude=True),
    'veg':        dict(settle='trace', sink=8, max_tilt=12, rand_tilt=0, z_rule='mean', ism=False, collide=True, exclude=False),
    'hero_tree':  dict(settle='trace', sink=30, max_tilt=4, rand_tilt=0, z_rule='min', ism=False, collide=True, exclude=True),
    'shrub':      dict(settle='trace', sink=5, max_tilt=15, rand_tilt=0, z_rule='mean', ism=True, collide=False, exclude=False),
    'bpp':        dict(settle='trace', sink=3, max_tilt=3, rand_tilt=0, z_rule='min', ism=False, collide=True, exclude=True),
    'bp':         dict(settle='trace', sink=5, max_tilt=3, rand_tilt=0, z_rule='min', ism=False, collide=True, exclude=True),
    'fx':         dict(settle='none', sink=0, max_tilt=0, rand_tilt=0, z_rule='mean', ism=False, collide=False, exclude=False),
    'fx_card':    dict(settle='none', sink=-150, max_tilt=0, rand_tilt=0, z_rule='mean', ism=False, collide=False, exclude=False),
}


# Ground covers and overhead decks: other pieces sit on or under them by design.
GROUND_COVERS = {'B01_floor01', 'B01_shelter01', 'AB_Planks_150_A', 'AB_Planks_150_B', 'B01_rail01'}


def draw_distance_cm(max_dim_m, landmark):
    """Max draw distance (never 0 = infinite; see the PCG cull-distance memory note)."""
    if landmark:
        return 300000.0
    for lim, d in ((0.6, 4000.0), (1.5, 6000.0), (4.0, 25000.0), (10.0, 80000.0)):
        if max_dim_m < lim:
            return d
    return 200000.0


def zone_of(s):
    for a, b, name in ZONES:
        if a <= s < b:
            return name
    return ZONES[-1][2]


# ---------------------------------------------------------------------------- the road frame

class World:
    def __init__(self):
        self.T = brp.Terrain(brp.HEIGHTMAP)
        self.R = brp.Road(brp.SPLINE_POINTS_CM)
        self.P = self.R.P[:, :2] / 100.0      # polyline, metres

    def frame(self, s):
        k, _ = self.R.locate(s)
        d = self.R.P[k + 1, :2] - self.R.P[k, :2]
        d = d / np.linalg.norm(d)
        p = self.R.xy(s) / 100.0
        return p, d, np.array([-d[1], d[0]])     # right = (-dy, dx) in UE's left-handed top view

    def yaw(self, s):
        _, f, _ = self.frame(s)
        return math.degrees(math.atan2(f[1], f[0]))

    def turn_sign(self, s, half=35.0):
        """+1 when the road turns right around s (yaw increasing), -1 left."""
        a = self.yaw(max(0.0, s - half))
        b = self.yaw(min(self.R.length, s + half))
        d = (b - a + 540.0) % 360.0 - 180.0
        return 1 if d > 0 else -1

    def ground(self, x_m, y_m):
        return float(self.T.height(x_m * 100.0, y_m * 100.0))

    def slope_deg(self, x_m, y_m):
        return math.degrees(math.atan(float(self.T.gradient(x_m * 100.0, y_m * 100.0))))

    def road_distance(self, pts):
        """Min distance (m) from any of pts (N,2) to the road polyline, and the nearest road point."""
        a = self.P[:-1][None, :, :]
        b = self.P[1:][None, :, :]
        p = np.asarray(pts, float)[:, None, :]
        ab = b - a
        t = np.clip(np.sum((p - a) * ab, axis=2) / np.sum(ab * ab, axis=2), 0, 1)
        q = a + ab * t[..., None]
        d = np.linalg.norm(p - q, axis=2)
        i, j = np.unravel_index(int(np.argmin(d)), d.shape)
        return float(d[i, j]), q[i, j]

    def road_m_of(self, x_m, y_m):
        """Road metre nearest a world point (for the exclusion check)."""
        a, b = self.P[:-1], self.P[1:]
        ab = b - a
        p = np.array([x_m, y_m])
        t = np.clip(np.sum((p - a) * ab, axis=1) / np.sum(ab * ab, axis=1), 0, 1)
        q = a + ab * t[:, None]
        d = np.linalg.norm(p - q, axis=1)
        k = int(np.argmin(d))
        return float(self.R.arc[k] + t[k] * self.R.seg[k]), float(d[k])


# ---------------------------------------------------------------------------- site authoring

class Site:
    def __init__(self, sid, name, road_m, v, kind, role, story, decay, style, order, radius_m,
                 layout, notes='', search_m=0.0, poi=None, keep_clear=None, verify_only=False,
                 story_owned=None):
        self.__dict__.update(dict(sid=sid, name=name, road_m=road_m, v=v, kind=kind, role=role, story=story,
                                  decay=decay, style=style, order=order, radius_m=radius_m, layout=layout,
                                  notes=notes, search_m=search_m, poi=poi, keep_clear=keep_clear or [],
                                  verify_only=verify_only, story_owned=story_owned or []))
        self.items = []
        self.rng = random.Random(zlib.crc32(sid.encode()))

    def add(self, key, u, v, yaw=0.0, scale=1.0, group='main', pitch=0.0, roll=0.0, **kw):
        it = dict(key=key, u=float(u), v=float(v), yaw=(yaw if isinstance(yaw, str) else float(yaw)), scale=scale, group=group,
                  pitch=float(pitch), roll=float(roll))
        it.update(kw)
        self.items.append(it)
        return it

    def run(self, key, pts, group, scale=1.0, gap=0.0, skip=(), jitter=2.0, overlap=0.04, **kw):
        """Wall pieces end to end along a polyline of (u, v) points; skip = piece indices left out."""
        e = CATALOG[key]
        size = e['size_cm']
        long_m = (size[1] if key in setdress_catalog.LONG_AXIS_Y else size[0]) / 100.0 * _s(scale)
        step = long_m * (1.0 - overlap) + gap
        n = 0
        self._runs = getattr(self, '_runs', 0) + 1
        kw.setdefault('run_id', self._runs)
        for (u0, v0), (u1, v1) in zip(pts[:-1], pts[1:]):
            seg = math.hypot(u1 - u0, v1 - v0)
            ang = math.degrees(math.atan2(v1 - v0, u1 - u0))
            yaw = ang - (90.0 if key in setdress_catalog.LONG_AXIS_Y else 0.0)
            k = max(1, int(round(seg / step)))
            for i in range(k):
                t = (i + 0.5) / k
                if n not in skip:
                    self.add(key, u0 + (u1 - u0) * t, v0 + (v1 - v0) * t, yaw + self.rng.uniform(-jitter, jitter),
                             scale, group, **kw)
                n += 1

    def scatter(self, keys, n, cu, cv, r, group, scale=(0.8, 1.2), min_sep=0.0, **kw):
        placed = []
        tries = 0
        while len(placed) < n and tries < n * 40:
            tries += 1
            a = self.rng.uniform(0, 2 * math.pi)
            d = r * math.sqrt(self.rng.random())
            u, v = cu + d * math.cos(a), cv + d * math.sin(a)
            if any(math.hypot(u - pu, v - pv) < min_sep for pu, pv in placed):
                continue
            placed.append((u, v))
            key = keys[self.rng.randrange(len(keys))]
            self.add(key, u, v, self.rng.uniform(0, 360), scale, group, **kw)

    def pile(self, keys, n, cu, cv, r, group, scale=(0.9, 1.1), **kw):
        """Stacked props: physics settle in order, so later pieces land on earlier ones."""
        for i in range(n):
            a = self.rng.uniform(0, 2 * math.pi)
            d = r * math.sqrt(self.rng.random())
            key = keys[i % len(keys)]
            self.add(key, cu + d * math.cos(a), cv + d * math.sin(a), self.rng.uniform(0, 360), scale, group,
                     stack=True, drop_cm=40 + 35 * (i // 3), **kw)

    def ring(self, key, n, cu, cv, r, group, scale=1.0, gaps=(), face=0.0, **kw):
        for i in range(n):
            if i in gaps:
                continue
            a = 2 * math.pi * i / n
            self.add(key, cu + r * math.cos(a), cv + r * math.sin(a), math.degrees(a) + face, scale, group, **kw)

    def hut(self, key, cu, cv, w, d, yaw, group, broken=(), scale=1.0, **kw):
        """A roofless rectangular ruin: walls of one panel key around a w x d rectangle (m)."""
        c, s_ = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))

        def rot(a, b):
            return cu + a * c - b * s_, cv + a * s_ + b * c
        corners = [rot(-w / 2, -d / 2), rot(w / 2, -d / 2), rot(w / 2, d / 2), rot(-w / 2, d / 2), rot(-w / 2, -d / 2)]
        self.run(key, corners, group, scale, skip=broken, jitter=0.5, **kw)


def _s(scale):
    return (scale[0] + scale[1]) / 2.0 if isinstance(scale, (list, tuple)) else scale


CATALOG = setdress_catalog.load()


# ---------------------------------------------------------------------------- the sites

def sites(W):
    S = []
    AB_BRICKS = ['AB_Brick_A', 'AB_Brick_A1', 'AB_Brick_A2', 'AB_Brick_A3', 'AB_Brick_A4', 'AB_Brick_A5']
    COBBLES = ['AB_Cobble_%02d' % i for i in range(1, 8)]
    BAGS = ['MV_jute_bag_%02d' % i for i in range(1, 11)]
    POTS = ['AB_Clay_Pot_A', 'AB_Clay_Pot_B', 'AB_Clay_Pot_C', 'AB_Clay_Pot_D']
    CRATES = ['PH_wcrate', 'PH_mcrate', 'MV_box_01', 'MV_box_05', 'AB_Box_C', 'MV_box_03']
    SHRUBS = ['FAB_Shrub_' + c for c in 'ABCDEFGH']
    PEBBLES = ['LF_Rock_07', 'LF_Rock_08', 'LF_Rock_06']

    # ---- S01 the carrier dock (P01) ------------------------------------------------------
    s = Site('S01_CarrierDock', 'Ibret Wehm, the Carrier Dock', 0, 14, 'dock yard', 'landmark',
             'B01 boot handover: carrier 06 dead in its cradle; plaque and mast crown in the first frame', 1,
             'MedievalVillage props on stone', 1, 25,
             layout='''
  road ->  (heading -131, boot view yaw -160 must stay clear)
  ==========================================================
      [V1 dock: annex + cradle + plaque post]   (story-owned, not placed here)
        bags+crate by the cradle   wheel on post
           wall02 x3 (low yard wall)    crate/bag stack   cart (no wheels)
''', story_owned=['V1 boot dock (BPP_PLA_Annex_01, SM_Manger cradle, plaque post, Lantern_01)'],
             keep_clear=[dict(road_m=0, yaw_world=-160.0, half_angle=16.0, min_m=3.0, max_m=450.0)])
    s.add('MV_jute_bag_02', -3, -6, 20, 1.0, 'cradle', stack=True)
    s.add('MV_jute_bag_05', -2.4, -6.4, 70, 1.0, 'cradle', stack=True, drop_cm=60)
    s.add('PH_mcrate', -4, -5, 5, 1.0, 'cradle')
    # SM_Cart_Wheel is modelled LYING FLAT (118 x 118 x 31 cm): roll 0 = flat, roll 90 = stood on its rim (LANE_SD)
    s.add('AB_Cart_Wheel', 3.0, -8.0, 90, 1.0, 'cradle', roll=0, note='lies flat by the cradle (the V1 plaque post it was to lean on is not in the level yet); LANE_SD fix pass')
    s.run('B01_wall02', [(-14, 4), (-2, 6), (8, 5)], 'yard', 1.0, skip={1})
    s.pile(BAGS[:6] + ['MV_box_01', 'MV_box_05'], 9, 6, 1, 1.4, 'stack')
    s.add('MV_cart_01', -9, -1, 15, 1.0, 'cart', roll=6, note='wheels off, bed tilted onto its axle')
    s.add('MV_cart_01_wheels', -12, 2, 80, 1.0, 'cart', roll=80)
    s.add('MV_bucket_02', -7, 2.5, 0, 1.0, 'cart', roll=180)
    s.add('B01_dock01', 9, 7, 0, 1.0, 'yard', verdict_check=True,
          note='empty riveted cradle frame: a second dock bay no one came back to (retrofuturist; check it reads old)')
    s.scatter(SHRUBS, 5, 0, 2, 12, 'ground', (0.8, 1.3), min_sep=2.0)
    S.append(s)

    # ---- L01 the dock farm ---------------------------------------------------------------------
    s = Site('L01_DockFarm', 'The Dock Farm', 80, 95, 'farmstead (lone)', 'inhabited-then-abandoned',
             'none (visual): the first farm the player passes; the valley was farmed to the road', 1,
             'MedievalVillage wood (farm)', 20, 45, search_m=25,
             layout='''
             barn (BPP)          pen
      well    [house: foundation + chimney + 2 walls, roof gone]
   fence run ======  hay  cart   yard
                    (road 95 m left)
''')
    s.add('BPP_Barn', 10, 12, 90, 1.0, 'barn')
    s.add('BPP_Wooden_Pen_01', -14, 14, 0, 1.0, 'pen')
    s.add('MV_Foundation', -8, -6, 0, 1.0, 'house')
    s.add('MV_Foundation', -8, -1.5, 180, 1.0, 'house')
    s.add('MV_Chimney', -11, -4, 0, 1.2, 'house')
    s.add('MV_Wall_01', -8, -7.5, 0, 1.0, 'house')
    s.add('MV_Wall_03', -4.5, -4, 90, 1.0, 'house')
    s.add('MV_Beam_03', -7, -3, 30, 1.0, 'house', roll=12, note='fallen rafter across the floor')
    s.add('MV_Beam_06', -9, -2, 110, 1.0, 'house')
    s.add('MV_well', 2, -10, 0, 1.0, 'yard')
    s.add('MV_bucket_01', 3.4, -9, 0, 1.0, 'yard')
    s.add('BPP_Hay_Bale', 18, -4, 30, 1.0, 'yard')
    s.add('BPP_Cart_03', 6, -3, 200, 1.0, 'yard')
    s.run('MV_Fence_01_V1', [(-25, -16), (25, -16)], 'fence', 1.0, skip={3, 9, 10})
    s.run('MV_Fence_01_V2', [(25, -16), (25, 22)], 'fence', 1.0, skip={5})
    s.add('MV_wash_tub', -2, -6, 0, 1.0, 'yard')
    s.add('PH_trunk', 22, 18, 40, 1.0, 'yard')
    s.scatter(SHRUBS, 6, 0, 0, 22, 'ground', (0.9, 1.4), min_sep=3)
    S.append(s)

    # ---- S02 the way-stone (P02) ---------------------------------------------------------------
    s = Site('S02_WayStone', 'Rzag Zrir, the Way-Stone', 150, 6.2, 'marker', 'guidance',
             'B02 archive opens: "For whoever carries this road after me"', 1, 'stone', 3, 20,
             layout='''
  ==== road ====
        |  way-stone (leans 8 deg to the road), pebble cairn on top; nothing else within 20 m
''', notes='The INSCR lane may swap the stone for SM_Stele_WayStone_A + the I04/I05 glyphs.')
    s.add('B01_marker01', 0, 0.4, 90, 1.25, 'stone', roll=-8, note='road face = mesh -Y side; I04 decal later')
    for i, k in enumerate(['LF_Rock_08', 'LF_Rock_08', 'LF_Rock_07', 'LF_Rock_07', 'LF_Rock_06']):
        s.add(k, 0.05 * i, 0.4, 37 * i, 0.9, 'cairn', stack=True, drop_cm=120 + 25 * i)
    S.append(s)

    # ---- S03 the goat fold (P03) ---------------------------------------------------------------
    s = Site('S03_GoatFold', 'Zyal Shebbarban, the Goat Fold', 300, -24, 'farmstead', 'rest',
             'EARLY idle pool: goats, bread, water shares', 2, 'bazaar stone fold + MV gate', 3, 20,
             layout='''
  ==== road ====   (24 m right of the fold)
        ( fold: ring of Broken_Walls, r 6 m, gate gap toward the road, fence gate swung open )
        [hut: wall03 U, tarp half fallen]  hearth, pot, carafe   hay bale + shrubs inside the fold
''')
    s.ring('AB_Broken_Walls', 26, 0, 0, 6.0, 'fold', 1.0, gaps={6, 7, 18}, face=90)
    s.add('MV_Fence_01_V2', 1.2, 5.6, 60, 0.7, 'fold', note='gate swung open toward the road')
    s.add('MV_Fence_01_Log1', -0.6, 6.2, 0, 1.2, 'fold')
    s.add('MV_bucket_03', -0.6, 6.2, 0, 1.0, 'fold', roll=180, stack=True, drop_cm=160, note='upside down on the gate post, left to dry')
    s.add('B01_wall03', -9, -5, 20, 1.0, 'hut')
    s.add('MV_Annex_Tarp_01', -9, -5, 20, 0.8, 'hut', pitch=-18, note='half fallen into the hut')
    s.add('PH_fire_pit', -10, -3, 0, 0.8, 'hut')
    s.add('PH_pot', -10, -3, 0, 1.0, 'hut', stack=True, drop_cm=60)
    s.add('MV_carafe_01', -8.6, -3.2, 0, 1.0, 'hut')
    s.add('MV_Hay_Bale_02', 2, -1, 20, 1.0, 'fold', roll=4)
    s.scatter(SHRUBS, 8, 0, 0, 5, 'fold', (0.9, 1.4), min_sep=1.2)
    s.scatter(AB_BRICKS, 14, 0, 0, 7.5, 'rubble', (0.9, 1.3))
    S.append(s)

    # ---- S04 the promise stones (P04) ----------------------------------------------------------
    s = Site('S04_PromiseStones', 'Zrir Siziman, the Promise Stones', 490, 0, 'marker pair', 'landmark',
             'B03 "Homes may empty; let names remain" + G03 glance; the notch frames the mast crown', 0,
             'stone', 2, 15, layout='''
  ==== road (aims at the mountain for 110 m) ====
   [left stone 4.2 m, V2]  cairn + flower          cairn   [right stone 2.9 m, V2]
   (nothing else: the sightline is the dressing)
''', story_owned=['V2 promise stones (two upright tixjegefa_tier_2)', 'Saskarta.Glance.PromiseStones'])
    for side, v in ((-1, -8.9), (1, 7.0)):
        for i in range(5):
            s.add(PEBBLES[i % 3], 1.2 + 0.1 * i, v, 50 * i, 1.1, 'cairn', stack=True, drop_cm=80 + 25 * i)
    s.add('LF_Flowers_01', 0.6, -8.4, 0, 0.35, 'flower', note='desaturated MI: the one last living thing in the valley')
    S.append(s)

    # ---- L02 the apricot terraces --------------------------------------------------------------
    s = Site('L02_ApricotTerraces', 'The Apricot Terraces', 650, -70, 'orchard ruin (lone)', 'inhabited-then-abandoned',
             'IDLE "Take an apricot. For the road." gets a place', 2, 'stone terraces + dead wood', 21, 35, search_m=20,
             layout='''
   terrace walls (wall02) x3 rows, stepping up away from the road
     stumps, roots, trunks in rows = the dead orchard
   field shed (wall03)   fallen ladder   boxes
''')
    for row in range(3):
        s.run('B01_wall02', [(-16, -6 - 7 * row), (16, -6 - 7 * row)], 'terraces', 1.0, skip={row + 1, 6 - row}, ism=True)
        for i in range(5):
            k = ['PH_stump_01', 'PH_stump_02', 'FAB_Stump', 'PH_roots_a', 'PH_trunk'][(i + row) % 5]
            s.add(k, -12 + 6 * i + s.rng.uniform(-1, 1), -9.5 - 7 * row, s.rng.uniform(0, 360), 1.0, 'orchard')
    s.add('B01_wall03', 14, -20, 250, 0.9, 'shed')
    s.add('MV_Log_02', 11, -18, 20, 0.7, 'shed', roll=85, note='fallen ladder rail')
    s.add('MV_Log_05', 11.5, -18.5, 22, 0.7, 'shed', roll=85)
    s.pile(['MV_box_02', 'MV_box_04', 'AB_Box_A'], 4, 9, -24.5, 1.0, 'shed')  # clear of the wall03 shed: at (12,-22) three landed on its wall tops (LANE_SD)
    s.add('PH_branches_a', -6, -16, 30, 1.0, 'orchard')
    s.add('PH_branches_b', 4, -23, 200, 1.0, 'orchard')
    S.append(s)

    # ---- S05 the cart convoy (P05) -------------------------------------------------------------
    s = Site('S05_CartConvoy', 'Taflalut Deighim, the Cart Convoy', 810, 0, 'caravan vignette', 'reveal',
             'B04 (no voice): a wordless departure; foreshadows the platform', 2,
             'AshesOfBazaar + MedievalVillage carts and props', 2, 40,
             layout='''
  L verge:        cart2 tipped(tarp snag)        cart4
  ============ road (up-road ->) ============================
  R verge:  cart1 (BPP)          cart3 (AB)
       bags spilled, crates, pots (one cracked), lamp on a crate; wheels leaning 3-6 m off
       hero dead tree qlEtl 22 m left (skip if the V3 one exists)
''', story_owned=['V3 convoy (stretch; survey first)'])
    s.add('BPP_Cart_01', -12, 7.8, 0, 1.0, 'carts')
    # MV_cart_01 is long along Y: tipping it onto its side is a PITCH (about Y); roll stood it on its tail (LANE_SD)
    s.add('MV_cart_01', 0, -7.6, 4, 1.0, 'carts', pitch=-78, note='tipped on its side, bed toward the road')
    s.add('MV_cart_tarp', 0.5, -7.0, 10, 1.0, 'carts', pitch=-60, attach=True, note='torn tarp snagged on the rail')
    s.add('AB_Cart_A_texturing', 14, 8.2, 88, 1.0, 'carts', note='mesh length is along Y: yaw 88 = nose up-road')
    s.add('MV_cart_02', 26, -7.6, -3, 1.0, 'carts', pitch=-4)
    s.add('MV_cart_01_wheels', -6, -11, 30, 1.0, 'wheels', roll=78)
    s.add('AB_Cart_Wheel', 20, 12, 120, 1.0, 'wheels', roll=8, note='the mesh is modelled flat: roll 8 = nearly flat (was 82, which stood it on its rim)')
    s.add('MV_cart_02_wheels', 30, -12, 200, 1.0, 'wheels', roll=5)
    s.pile(BAGS, 10, -10, 11, 1.6, 'spill')
    s.pile(['PH_mcrate', 'PH_wcrate', 'AB_Box_A', 'AB_Box_C'], 5, 15, 11.5, 1.2, 'spill')
    s.add('AB_Lamp_B', 15, 11.5, 0, 1.0, 'spill', stack=True, drop_cm=160, note='unlit, set down neatly')
    s.scatter(POTS, 5, 2, -11.5, 1.8, 'spill', (0.9, 1.1))
    s.add('AB_Clay_Pot_B', 3.5, -10.2, 0, 1.0, 'spill', roll=90, note='tipped; the cracked one (broken-jar mesh missing)')
    s.add('FAB_DeadTree_qlEtl', 10, -22, 30, 1.0, 'tree', landmark=True, skip_if_existing_within_m=40,
          note='hero dead tree #1 of 4')
    s.scatter(SHRUBS, 6, 8, 0, 18, 'ground', (0.9, 1.3), min_sep=3)
    S.append(s)

    # ---- L03 threshing farm --------------------------------------------------------------------
    s = Site('L03_ThreshingFarm', 'The Threshing Floor Farm', 1000, 95, 'farmstead (lone)', 'inhabited-then-abandoned',
             'none (visual): the valley fed the caravans', 1, 'stone house + MV farm wood', 22, 40, search_m=25,
             layout='''
   [house02 ruin]     hay shed (annex)       pen
        threshing floor (4 flagstones, rock ring)   well  cart  barrels
''')
    s.add('B01_house02', -12, 8, 15, 1.0, 'house')
    s.add('BPP_Annex_02', 8, 10, 180, 1.0, 'shed')
    s.add('BPP_Hay_Bale', 9, 7, 0, 1.0, 'shed')
    s.add('BPP_Wooden_Pen_02', 22, 2, 90, 1.0, 'pen')
    for i, (a, b) in enumerate(((-1.5, -1.5), (1.5, -1.5), (-1.5, 1.5), (1.5, 1.5))):
        s.add('B01_floor01', a, -8 + b, 90 * i, 1.0, 'threshing')
    s.ring('LF_Rock_05', 12, 0, -8, 4.2, 'threshing', 0.35)
    s.add('MV_well', -6, -3, 0, 1.0, 'yard')
    s.add('BPP_Cart_04', 12, -6, 70, 1.0, 'yard')
    s.add('BPP_Barrels_01', -3, 3, 0, 1.0, 'yard')
    s.add('MV_bucket_01', -5, -1.5, 0, 1.0, 'yard', roll=95)
    s.scatter(AB_BRICKS, 12, -12, 8, 6, 'rubble', (0.9, 1.3))
    s.scatter(SHRUBS, 6, 0, 0, 20, 'ground', (0.9, 1.4), min_sep=3)
    S.append(s)

    # ---- S06 the mountain seat (P06) -----------------------------------------------------------
    s = Site('S06_MountainSeat', 'Sleb Yeggar, the Mountain Seat', 1150, -9, 'rest seat', 'rest',
             'no voice (the quiet stretch); invites an idle stop; mirrors the Ledge at 4,460 m', 1, 'stone', 3, 15,
             layout='''
  ==== road ====
      [slab bench on two blocks, facing the switchbacks]  backrest stone   carafe
      hero dead tree rlthg framing the left of the view
''')
    ybench = 'face_summit'
    s.add('AB_Pillar_A_04', -0.9, 0, ybench, 0.8, 'bench')
    s.add('AB_Pillar_A_04', 0.9, 0, ybench, 0.8, 'bench')
    s.add('FAB_TempleStones', 0, 0, ybench, 1.0, 'bench', stack=True, drop_cm=80, note='slab seat, lying flat')
    s.add('B01_monument01', 0, -1.0, ybench, 0.45, 'bench', note='backrest; I09 later')
    s.add('MV_carafe_02', 1.0, 0.1, 0, 0.7, 'bench', stack=True, drop_cm=130)
    s.add('FAB_DeadTree_rlthg', -7, -6, 200, 1.0, 'tree', landmark=True, note='hero dead tree #2 of 4')
    S.append(s)

    # ---- S07 the Waiting Water village (P07 + P08) ----------------------------------------------
    s = Site('S07_WaitingWater', 'Dasef Abremu, the Waiting Water (village)', 1220, 0, 'village', 'landmark',
             'B05 "We called this bend the Waiting Water..." (no water sound anywhere); B24 chorus', 2,
             'BAZAAR STONE: arcaded empty market, small lookout tower, stone channels and aqueduct', 1, 110,
             layout='''
                     (right, higher, +3..+9 m)
        house02        [aqueduct bridge01 x2 on the channel line]      lookout tower (Damaged_Minarate x0.55)
            wall04 yard     market square: 3x3 flagstones, arcade of 4 Side_Arch stalls
     window01 stub          torn awnings, tables, pots, boxes, lamps   house02
        well + broken jar + cup (P08)     sluice gate01 + winch posts + rota board
  ======================= road  (channel passes under it; parapet stubs both verges) =======
        plank crossing   stepping stones   bucket stranded   (dry reed marsh: PCG)
        water wheel (dead)  house02 ruin    wall03 corners
                     (left, the hollow, -5..-11 m)
''', notes='Content rule: the tower is a lookout/watch tower silhouette only, no religious dressing.')
    # the channel, perpendicular to the road, broken where the road crosses it
    s.run('B01_channel01', [(0, -62), (0, -7.5)], 'channel', 1.0, ism=True)
    s.run('B01_channel01', [(0, 7.5), (0, 36)], 'channel', 1.0, ism=True)
    s.add('AB_Broken_Walls', -2.5, -6.2, 0, 1.0, 'channel', note='parapet stub at the road edge')
    s.add('AB_Broken_Walls', 2.5, -6.2, 0, 1.0, 'channel')
    s.add('AB_Broken_Walls', -2.5, 6.2, 0, 1.0, 'channel')
    s.add('AB_Broken_Walls', 2.5, 6.2, 0, 1.0, 'channel')
    s.run('B01_bridge01', [(0, 38), (0, 58)], 'aqueduct', 1.0)
    s.add('B01_gate01', 0, 12, 0, 1.0, 'sluice', verdict_check=True, note='sluice gate raised over nothing (I10 lintel later)')
    s.add('B01_support01', -1.4, 12, 0, 1.0, 'sluice', verdict_check=True)
    s.add('B01_support01', 1.4, 12, 180, 1.0, 'sluice', verdict_check=True)
    s.add('B01_sign02', 2.8, 13.5, 90, 1.0, 'sluice', verdict_check=True, note='the water rota board (I11 later)')
    s.add('MV_bucket_02', 0.2, -20, 0, 1.0, 'channel', roll=70, note='stranded mid-channel')
    s.add('AB_Planks_150_A', 0, -24, 90, 1.0, 'channel', note='plank crossing over the dry bed')
    for i in range(4):
        s.add('LF_Rock_05', 1.3 * (i - 1.5), -30, 40 * i, 0.3, 'channel')
    s.add('B01_wheel01', -3.2, -40, 90, 1.0, 'mill', roll=0, note='dead water wheel beside the channel')
    s.add('MV_Wm_wheel_support', -4.9, -40, 0, 0.8, 'mill', note='at the axle end (the wheel axle runs along u at yaw 90); at v -41.6 it stood inside the disc and landed on the wheel (LANE_SD fix)')
    # the market square (right, ahead)
    for i in range(3):
        for j in range(3):
            s.add('B01_floor01', 22 + 3 * i, 30 + 3 * j, 90 * ((i + j) % 4), 1.0, 'market', ism=True)
    s.run('AB_Side_Arch', [(16, 42), (32, 42)], 'market')
    for i, u in enumerate((17.5, 21.5, 25.5, 29.5)):
        s.add(['AB_Damaged_Tent_A', 'AB_Tent_B_Cloth_low', 'AB_Damaged_Tent_A', 'AB_Tent_B_Cloth_low'][i],
              u, 39.5, 180, 1.0, 'stalls', note='torn awning')
        s.add(['AB_Table', 'AB_WoodenTable_B', 'AB_Table', 'MV_table_01'][i], u, 38, 0, 1.0, 'stalls',
              roll=(80 if i == 2 else 0), note='one table knocked over' if i == 2 else '')
    s.scatter(POTS, 8, 24, 36, 5, 'stalls', (0.9, 1.2), min_sep=0.8)
    s.pile(['AB_Box_A', 'AB_Box_B', 'AB_Box_C', 'MV_box_03'], 4, 30, 35, 1.2, 'stalls')
    s.add('AB_Lamp_C', 21.5, 38, 0, 1.0, 'stalls', stack=True, drop_cm=110)
    s.add('AB_Chair_A_low', 26, 36.5, 40, 1.0, 'stalls')
    s.add('AB_Chair_A_low', 18, 35.5, 200, 1.0, 'stalls', roll=85)
    s.scatter(COBBLES, 18, 26, 33, 9, 'market_rubble', (0.9, 1.2))
    # the lookout tower (small minaret, x0.55 = 10 m) — readable at 200-500 m
    s.add('AB_Damaged_Minarate', 44, 58, 30, 0.55, 'tower', landmark=True)
    s.scatter(AB_BRICKS, 16, 44, 58, 9, 'tower_rubble', (0.9, 1.4))
    # houses
    s.add('B01_house02', -24, 42, 10, 1.0, 'houses')
    s.add('B01_house02', -4, 72, 95, 0.9, 'houses')
    s.add('B01_house02', 58, 28, 200, 1.0, 'houses')
    s.hut('AB_300x400_Mid_Damaged_A', -30, 22, 9, 6, 5, 'houses', broken={1, 6})
    s.add('B01_window01', 12, 22, 0, 1.0, 'houses')
    s.add('B01_window01', 38, 18, 90, 1.0, 'houses')
    s.run('B01_wall04', [(-18, 55), (-4, 55), (6, 62)], 'yards', 1.0, skip={2})
    # the well of the broken jar (P08), 15 m right
    s.add('MV_well', 5, 16, 0, 1.0, 'well')
    s.add('AB_Clay_Pot_B', 6.2, 15.2, 0, 1.0, 'well', roll=95, note='broken at the lip (shard set missing)')
    s.add('MV_carafe_02', 3.4, 16.2, 0, 0.6, 'well', note='one cup set upright at the foot of the well (the rim is under the well roof: a trace lands it on the roof; LANE_SD fix)')
    s.add('MV_Rope_01', 5.2, 15.6, 0, 1.0, 'well', attach=True)
    # the left hollow
    s.add('B01_house02', -18, -60, 170, 0.9, 'hollow')
    s.add('B01_wall03', 10, -52, 80, 1.0, 'hollow')
    s.add('B01_wall03', 18, -64, 150, 1.0, 'hollow')
    s.scatter(AB_BRICKS, 24, -8, 20, 45, 'rubble', (0.9, 1.4))
    s.scatter(SHRUBS, 10, 0, -30, 30, 'ground', (1.0, 1.5), min_sep=3)
    S.append(s)

    # ---- S08 the valley watchtower (P09) --------------------------------------------------------
    s = Site('S08_Watchtower', 'Efkirekeb Zdaw, the Valley Watchtower', 1500, 28, 'watch post', 'landmark',
             'none (quiet stretch): the silhouette seen from the Waiting Water; marks the ridge grade', 2,
             'bazaar stone', 3, 30, search_m=12,
             layout='''
  ==== road ====
        (knoll, 28 m right)   [tower house03, door to the road]  fort-wall stubs x3
          fallen ladder at the door   rubble skirt downhill   pennant on a stub pole
''')
    s.add('B01_house03', 0, 0, 'face_road', 1.0, 'tower', landmark=True)
    s.run('AB_Fort_Wall_Mid', [(-10, -6), (-4, -9), (4, -9)], 'walls', 1.0, skip={2})
    s.add('MV_Log_01', -1, -5.5, 10, 0.8, 'door', roll=80)
    s.add('MV_Log_02', -0.2, -5.8, 12, 0.8, 'door', roll=82)
    s.add('B01_rubble01', 5, -4, 30, 1.0, 'rubble')
    s.add('B01_rubble01', -6, 5, 200, 0.8, 'rubble')
    s.scatter(AB_BRICKS, 20, 0, 0, 9, 'rubble', (0.9, 1.4))
    s.add('MV_Fence_01_Log1', 3.5, 3.5, 0, 2.0, 'pennant', roll=6)
    s.add('TRIPO_Flag', 3.5, 3.5, 0, 5.0, 'pennant', stack=True, drop_cm=0, attach=True, note='torn pennant stand-in (banner mesh missing)')
    S.append(s)

    # ---- L04 the shepherd camp at the foot of the ridge grade ------------------------------------
    s = Site('L04_ShepherdCamp', 'The Shepherd Camp at the Ridge Foot', 1650, -30, 'camp (lone)', 'inhabited-then-abandoned',
             'none: a cart left at the foot of the grade (too steep); the carriers walked on', 2,
             'AshesOfBazaar tent frames + props', 23, 30, search_m=10,
             layout='''
  ==== road ====   cart on the left verge, load half unloaded (bags, crates)
           tent frame stripped    cloth frame   cold fire pit, trunk seats   rope-line posts
''')
    s.add('MV_cart_01', 10, 22.4, 0, 1.0, 'cart', note='on the left verge (v -7.6 from the road)')
    s.pile(BAGS[:6], 6, 13, 21.5, 1.4, 'cart')
    s.add('PH_wcrate', 7, 21, 30, 1.0, 'cart')
    s.add('AB_Tent_C_Frame', 0, -4, 20, 1.0, 'camp', note='stripped: no cloth')
    s.add('AB_Tent_Cloth_B_frame', 5, -8, 150, 1.0, 'camp')
    s.add('PH_fire_pit', 2, 2, 0, 1.0, 'camp')
    s.add('PH_trunk', 2, 4.2, 5, 0.6, 'camp')
    s.add('PH_trunk_02', -0.8, 1.2, 80, 0.6, 'camp')
    s.add('MV_bucket_01', 3.5, 1, 0, 1.0, 'camp')
    s.scatter(POTS, 3, 1, 3, 2, 'camp')
    s.add('MV_Fence_01_Log1', -6, 2, 0, 1.4, 'camp')
    s.add('MV_Fence_01_Log1', -6, 8, 0, 1.4, 'camp')
    s.scatter(SHRUBS, 6, 0, 0, 14, 'ground', (0.9, 1.3), min_sep=2)
    S.append(s)

    # ---- S09 the camel route-stone (P10) --------------------------------------------------------
    s = Site('S09_CaravanRoute', 'Qamish-aal, the Caravan-Route stone', 1750, 7.5, 'marker', 'reveal',
             'pre-echoes RADIO_B11_01 "Leave the bearer where it rests. Take what it carried."', 2, 'stone', 4, 10,
             layout='''
  ==== road ====
     route-stone   (camel skeleton + pack saddle: MISSING, bought later)   two emptied flat bags
     ring of dead shrubs
''', notes='The skeleton is an animal, never human; the site is incomplete until it is bought.')
    s.add('B01_marker01', 0, 0, 90, 0.9, 'stone')
    s.add('MV_jute_bag_07', 2, 1.4, 40, 1.0, 'bags')
    s.add('MV_jute_bag_09', 2.8, 0.6, 130, 1.0, 'bags')
    s.ring('FAB_Shrub_G', 8, 2.5, 1.5, 3.0, 'shrubs', 1.1)
    S.append(s)

    # ---- L05 the ridge hamlet ------------------------------------------------------------------
    s = Site('L05_RidgeHamlet', 'The Ridge Hamlet', 1850, -150, 'hamlet ruin (lone)', 'inhabited-then-abandoned',
             'seen from the crest looking back; the valley had more than one village', 3,
             'bazaar stone', 24, 40, search_m=30,
             layout='''
      house02   wall03    house02
         field walls wall02 x6 (terraces)   rubble heap   dead trunk
''')
    s.add('B01_house02', -8, 0, 20, 1.0, 'houses', search_local_m=8)
    s.add('B01_house02', 10, -6, 110, 0.9, 'houses', search_local_m=8)
    s.add('B01_wall03', 2, 10, 200, 1.0, 'houses')
    s.add('B01_wall03', -14, 12, 60, 0.9, 'houses')
    s.run('B01_wall02', [(-20, -18), (20, -16)], 'fields', 1.0, skip={4}, ism=True)
    s.run('B01_wall02', [(-18, -26), (18, -25)], 'fields', 1.0, skip={1, 7}, ism=True)
    s.add('B01_rubble01', 0, 4, 40, 1.0, 'rubble')
    s.scatter(AB_BRICKS, 16, 0, 0, 16, 'rubble', (0.9, 1.4))
    s.add('PH_trunk_02', 16, 8, 30, 1.0, 'rubble')
    S.append(s)

    # ---- S10 the crest fortress (P11) -----------------------------------------------------------
    s = Site('S10_CrestFort', 'Itset Itset, the Crest Fortress', 1980, -9, 'ruined fort', 'landmark',
             'B06 road ahead, 2,450 m in view; the single crest gust catches the torn banner', 2,
             'BAZAAR STONE (fort walls, broken arch gate, pillars) + ruin01 keep', 1, 70, search_m=0,
             layout='''
  R side: NOTHING (the vista must stay open)
  ======================== road (crest) ==========================
  L:  [gate: Broken_Arch_Wall, face to the road, frames the view back]  torn banner on a pole
        curtain wall (Fort_Wall_Mid) runs step down the slope on both sides of the gate
            pillars    hero dead tree inside    rubble drifts    fallen pillar parts
                  [keep: ruin01, 13 m, ~40 m left]
''', notes='Banner = TRIPO_Flag x8 + SM_Cloth_02 on a log pole until the torn banner mesh (I17) exists.')
    s.add('AB_Broken_Arch_Wall', 0, 0.2, 0, 1.0, 'gate', landmark=True, note='face parallel to the road; look left through it')
    s.run('AB_Fort_Wall_Mid', [(-4, -0.5), (-12, -8), (-20, -18), (-26, -30)], 'curtain_w', 1.0, skip={3, 7})
    s.run('AB_Fort_Wall_Mid', [(4, -0.5), (12, -9), (18, -20), (22, -32)], 'curtain_e', 1.0, skip={2, 6})
    s.add('B01_ruin01', 0, -32, 'face_road', 1.0, 'keep', landmark=True, search_local_m=16)
    s.add('AB_Damaged_Pillar_A', -6, -10, 20, 0.6, 'pillars')
    s.add('B01_pillar01', 6, -12, 0, 1.0, 'pillars')
    s.add('B01_pillar01', -3, -20, 45, 1.0, 'pillars')
    s.add('AB_Pillar_Part', 8, -16, 70, 1.0, 'pillars', note='fallen pillar')
    s.add('AB_Pillar_Part', -10, -24, 150, 0.9, 'pillars')
    s.add('FAB_DeadTree_rlthg', -8, -14, 60, 0.9, 'tree', landmark=True, note='hero dead tree #3 of 4')
    s.add('MV_Log_01', 3.8, -1.2, 0, 1.6, 'banner', note='banner pole (SM_Log_01 is modelled vertical, 3.5 m)')
    s.add('TRIPO_Flag', 3.8, -1.2, 0, 8.0, 'banner', attach=True, note='torn banner stand-in (I17 later)')
    s.add('MV_Cloth_02', 4.1, -1.2, 90, 0.5, 'banner', attach=True)
    for cu, cv in ((-14, -12), (14, -14), (0, -22)):
        s.add('B01_rubble01', cu, cv, s.rng.uniform(0, 360), 1.0, 'rubble')
    s.scatter(AB_BRICKS, 40, 0, -16, 20, 'rubble', (0.9, 1.5))
    s.scatter(COBBLES, 12, 0, -4, 6, 'rubble', (0.9, 1.2))
    S.append(s)

    # ---- S11 the signal fire (P12) --------------------------------------------------------------
    s = Site('S11_SignalFire', 'Thebaqet Ghafeth, the Signal Fire', 2120, -8, 'signal post', 'guidance',
             'the mast drops out of view; Geiger starts rising (B07); a signal nobody lit', 2, 'stone', 4, 35,
             layout='''
  ==== road (steep descent) ====
     fire ring (unlit) + wood stack laid ready   signal pillar (A_03) + cloth scrap
                        30 m down-road: first danger board (painted wood, facing up-road)
''')
    s.add('PH_fire_pit', 0, 0, 0, 1.2, 'fire')
    for i in range(4):
        s.add('MV_Log_05', 0.2 * (i % 2), 0.2 * (i // 2), 90 * i, 0.35, 'fire', stack=True, drop_cm=40 + 20 * i,
              note='wood laid for lighting, never lit')
    s.add('AB_Pillar_A_03', 2.4, -1.0, 0, 1.0, 'pillar')
    s.add('MV_Cloth_02', 2.6, -1.0, 0, 0.25, 'pillar', attach=True)
    s.add('MV_Fence_01_Log1', 30, 1.2, 0, 1.6, 'board')
    s.add('B01_sign02', 30, 1.2, 180, 0.8, 'board', verdict_check=True, note='danger board I20 (painted wood); fallback: fence board')
    S.append(s)

    # ---- L06 descent carts ---------------------------------------------------------------------
    s = Site('L06_DescentCarts', 'Two Carts on the Descent', 2250, 0, 'caravan vignette (lone)', 'reveal',
             'the steep descent broke carts: two nose-down, one on its side', 2, 'carts + props', 25, 20,
             layout='''
  L verge: cart on its side, wheel off           R verge: cart nose-down, bags slid forward
  ==================== road (steep, down ->) =====================
''')
    s.add('MV_cart_02', 0, 7.8, 0, 1.0, 'carts', pitch=-10)
    s.add('AB_Cart_A_texturing', 6, -8.4, 92, 1.0, 'carts', pitch=78, note='on its side: the mesh is long along Y, so the tip is a pitch (LANE_SD)')
    s.add('AB_Cart_Wheel', 10, -12, 20, 1.0, 'carts', roll=0, note='the mesh is modelled flat; a lone upright wheel would lean on nothing')
    s.pile(BAGS[4:], 5, 4, 9.5, 1.2, 'load')
    s.scatter(POTS, 2, 8, -11, 1.5, 'load')
    S.append(s)

    # ---- S12 the evacuation checkpoint (P13) ----------------------------------------------------
    s = Site('S12_Checkpoint', 'Egdir Tuleym, the Evacuation Checkpoint', 2330, 0, 'checkpoint', 'guidance',
             'sets up B08: the new signs gave places numbers; MIDDLE idle pool (loads, departure notices)', 2,
             'MedievalVillage props, sack walls, painted boards (no sandbags, no metal)', 2, 30,
             layout='''
  L: rope-line posts along the verge        boards: checkpoint (I19) + danger (I20), painted wood
  ============= road ==== [barrier pole raised, left on its post] ===============
  R: sack wall bay (jute bag piles + BPP jute bags)   trestle table, stool, lamp, bags beneath
       heap of bags behind: the bags that could not go     guard shelter (cloth frame)
''', notes='FAB_Sandbags are skipped by default (may read modern/military). The editor lane may try one and keep it only if it reads as old cloth/earth sacks.')
    s.add('MV_Fence_01_Log1', 0, 5.6, 0, 1.3, 'barrier')
    s.add('MV_Log_01', 0, 5.6, 0, 1.0, 'barrier', pitch=62, note='barrier pole raised and left (pivot at the post)', stack=True)
    s.add('MV_Fence_01_Log1', 0, -5.6, 0, 1.3, 'barrier')
    for i, k in enumerate(['BPP_Jute_Bags', 'BPP_Jute_Bags_02', 'BPP_Jute_Bags_03', 'BPP_Jute_Bags_04']):
        s.add(k, -6 + 3.6 * i, 10.5, 0, 1.0, 'sackwall')
    s.add('MV_table_01', 3, 8.2, 0, 1.0, 'table')
    s.pile(BAGS[:5], 5, 3, 8.2, 0.6, 'table')
    s.add('AB_Chair_A_low', 3.2, 7.2, 170, 1.0, 'table')
    s.add('AB_Lamp_C', 2.6, 8.3, 0, 1.0, 'table', stack=True, drop_cm=120, note='unlit')
    s.pile(BAGS, 16, 8, 13.5, 2.4, 'left_behind', note='the bags that could not go (one bag each)')
    s.add('PH_barrel', 10, 9, 0, 1.0, 'table')
    s.add('MV_barrel_02', 11, 10, 30, 1.0, 'table', roll=90)
    s.add('AB_Tent_Cloth_B_frame', -9, 14, 90, 1.0, 'shelter')
    for u in (-12, -8, -4, 4, 8, 12):
        s.add('MV_Fence_01_Log2', u, -6.4, 0, 1.2, 'rope_line', note='rope-line post (rope mesh between posts missing)')
    s.add('MV_Fence_01_Log1', -3, -7.4, 0, 1.6, 'boards')
    s.add('B01_sign03', -3, -7.4, 90, 1.0, 'boards', verdict_check=True, note='checkpoint board I19 (painted wood)')
    s.add('MV_Fence_01_Log1', 6, -7.6, 0, 1.6, 'boards')
    s.add('B01_sign02', 6, -7.6, 90, 0.8, 'boards', verdict_check=True, note='danger board I20')
    S.append(s)

    # ---- L08 the basin hamlet (Heron Pools outskirts) --------------------------------------------
    s = Site('L08_BasinHamlet', 'The Heron Pools Outskirts', 2450, -120, 'hamlet ruin (lone)', 'inhabited-then-abandoned',
             'the basin was a lived-in place before it was a stop', 2, 'bazaar stone', 26, 40, search_m=25,
             layout='''
     house02    AB panel ruin (U)     house02
        garden walls (wall04)    dry pool (wall03 basin + floor01)   rubble
''')
    s.add('B01_house02', -12, 0, 30, 1.0, 'houses')
    s.add('B01_house02', 14, 6, 160, 0.9, 'houses')
    s.hut('AB_300x400_Mid_Damaged_A', 0, 16, 9, 6, 0, 'houses', broken={2, 5})
    s.run('B01_wall04', [(-20, -12), (-4, -14), (10, -12)], 'gardens', 1.0, skip={1})
    s.add('B01_wall03', 6, -6, 0, 1.0, 'pool')
    s.add('B01_floor01', 6, -5.5, 0, 1.0, 'pool')
    s.scatter(AB_BRICKS, 20, 0, 4, 18, 'rubble', (0.9, 1.4))
    s.scatter(SHRUBS, 8, 0, 0, 22, 'ground', (1.0, 1.4), min_sep=3)
    S.append(s)

    # ---- S13 the Numbered Stop / Heron Pools caravanserai (P14) ----------------------------------
    s = Site('S13_NumberedStop', 'Tfibaz Taflalut, the Numbered Stop (Heron Pools caravanserai)', 2540, -40,
             'caravanserai (settlement)', 'landmark',
             'B08 "The new signs gave the places numbers... We called it the Heron Pools." The painted 6-8 board over the carved name', 2,
             'BAZAAR STONE: walled courtyard inn, arcaded stalls, broken arch gate', 1, 60, search_m=8,
             layout='''
                    [ruin01 back range]
      +--wall--+---arcade: Side_Arch x6, torn awnings---+--wall--+
      |  well        trough (channel01)                          |
      |        courtyard: cobble drifts, rubble                  |
      +--wall----[ GATE: Broken_Arch_Wall, painted 6-8 board ]---+   notice board (departures)
                   carts parked in a row, noses to the platform ->
  ============================ road ===================================
      R: the dry Heron Pools (wall03 basins + floor01 + channel01 runs)
''', story_owned=['V5 arch/number plate if already placed (survey)'])
    W_, D_ = 26.0, 20.0
    s.run('AB_300x400_Mid_Damaged_A', [(-W_ / 2, D_ / 2 - 20 + 0), (-W_ / 2, -D_ / 2)], 'walls', skip={2})
    s.run('AB_300x400_Mid', [(-W_ / 2, -D_ / 2), (W_ / 2, -D_ / 2)], 'walls', skip={3, 5})
    s.run('AB_300x400_Mid_Damaged_A', [(W_ / 2, -D_ / 2), (W_ / 2, D_ / 2)], 'walls', skip={4})
    s.run('AB_300x400_Mid', [(W_ / 2, D_ / 2), (4.5, D_ / 2)], 'walls', skip={1})
    s.run('AB_300x400_Mid', [(-4.5, D_ / 2), (-W_ / 2, D_ / 2)], 'walls', skip={0})
    s.add('AB_300x400_Corner_90d', -W_ / 2, -D_ / 2, 0, 1.0, 'walls')
    s.add('AB_300x400_Corner_90d', W_ / 2, D_ / 2, 180, 1.0, 'walls')
    s.add('AB_Broken_Arch_Wall', 0, D_ / 2, 0, 1.0, 'gate', landmark=True, note='the inn gate, facing the road')
    s.add('B01_sign02', 0, D_ / 2 + 0.6, 0, 0.45, 'gate', verdict_check=True, z_offset_cm=520, attach=True,
          note="painted '6-8' number board over the carved name (I21); no metal plate")
    s.add('B01_sign03', 5.5, D_ / 2 + 2.5, 0, 1.0, 'gate', verdict_check=True, note='departures notice board (I22)')
    s.add('MV_Fence_01_Log1', 5.5, D_ / 2 + 2.5, 0, 1.6, 'gate')
    s.run('AB_Side_Arch', [(-9, -D_ / 2 + 1.5), (9, -D_ / 2 + 1.5)], 'arcade')
    for i, u in enumerate((-7, -2, 3, 8)):
        s.add(['AB_Damaged_Tent_A', 'AB_Tent_B_Cloth_low'][i % 2], u, -D_ / 2 + 3.5, 0, 1.0, 'arcade', note='torn awning')
    s.add('MV_well', -4, 1, 0, 1.0, 'court')
    s.add('B01_channel01', 4, 0, 0, 0.7, 'court', note='stone trough stand-in')
    s.add('B01_ruin01', 0, -D_ / 2 - 12, 180, 0.8, 'back', landmark=True, search_local_m=8, note='the back range, behind the arcade wall')
    for i, (k, u) in enumerate((('BPP_Cart_02', 18), ('BPP_Cart_05', 24), ('MV_cart_01', 30))):
        s.add(k, u, 31.5, 0, 1.0, 'carts', note='parked in a row outside, noses up-road to the platform')
    s.scatter(COBBLES, 30, 0, 0, 11, 'court_rubble', (0.9, 1.2))
    s.scatter(AB_BRICKS, 40, 0, 0, 16, 'court_rubble', (0.9, 1.5))
    s.add('B01_rubble01', 9, 4, 30, 1.0, 'court_rubble')
    s.add('B01_rubble01', -10, -5, 200, 0.9, 'court_rubble')
    s.add('AB_FogCard', 0, 22, 0, 1.0, 'fog', optional=True, note='low fog card, ~1.5 m above ground; optional: in the editor capture it reads as a glowing white orb (LANE_SD)')
    # the dry Heron Pools, across the road (right)
    for i, u in enumerate((-8, 4)):
        s.add('B01_wall03', u, 64, 90 * i, 1.0, 'pools')
        s.add('B01_floor01', u, 64.5, 0, 1.0, 'pools')
    s.run('B01_channel01', [(-14, 60), (12, 60)], 'pools', 1.0, ism=True)
    S.append(s)

    # ---- S14 the departure platform (P15) -------------------------------------------------------
    s = Site('S14_DeparturePlatform', 'Wehm Aburde, the Departure Platform (evacuation outpost)', 2575, 24,
             'evacuation outpost', 'reveal',
             'B09 "...asked the name of this stop" (G09 glance); Geiger peak 10 cps; the platform in mist', 1,
             'stone platform + AshesOfBazaar tents + MedievalVillage carts, sacks, crates (no military kit)', 1, 45,
             search_m=6,
             layout='''
  ============================ road ===================================
   rope-line rails (queue)   loaded carts x2 + wheel-less cart     name board on two posts
   [ stone platform: 8 flagstones ]  under two shade decks (shelter01)
      two rows of trunk seats + plank benches; luggage groups at seat ends (crates, boxes, sacks, cloth)
   stacked sacks (BPP jute bags), boxes, barrels ready to leave
        tent camp: big tent, 2 torn tents, frame+cloth x2, cold fire pits, pots, buckets
''', story_owned=['Saskarta.Glance.Platform (G09 target)', 'V5 platform (BPP_PLA_Terrace_01) if already placed'])
    for i in range(4):
        for j in range(2):
            s.add('B01_floor01', -4.5 + 3 * i, -1.5 + 3 * j, 0, 1.0, 'platform', ism=True)
    s.add('B01_shelter01', -3, 0, 0, 1.0, 'platform', note='shade deck over the seats')
    s.add('B01_shelter01', 3.5, 0, 0, 1.0, 'platform')
    for row in (-1.6, 1.4):
        for i, u in enumerate((-4.5, -1, 2.5, 6)):
            s.add('PH_trunk' if i % 2 == 0 else 'PH_trunk_02', u, row, 0, 0.55, 'seats', note='log seat')
    s.add('MV_bench_02', -2, 3.6, 0, 1.0, 'seats')
    s.add('MV_bench_03', 4, 3.6, 0, 1.0, 'seats')
    s.add('B01_bench01', -7.5, 4.2, 0, 1.0, 'seats', verdict_check=True, note='cast-iron bench; fallback MV_bench_02')
    s.add('B01_bench01', 7.5, 4.2, 180, 1.0, 'seats', verdict_check=True)
    for g, (cu, cv) in enumerate(((-7, -1.5), (8, -1.5), (-7, 1.5), (8, 1.8), (0.5, 4.8), (-3, -4.2))):
        s.pile([CRATES[(g + i) % len(CRATES)] for i in range(3)] + [BAGS[g % 10]], 4, cu, cv, 0.7, 'luggage_%d' % g)
    s.add('MV_Cloth_01', 8, -1.5, 0, 0.35, 'luggage_1', stack=True, drop_cm=160, note='cloth over a bundle')
    s.add('MV_Cloth_02', -7, 1.5, 40, 0.3, 'luggage_2', stack=True, drop_cm=160)
    for i in range(6):
        s.add('MV_Fence_03_V1', -10 + 3.2 * i, -10.5, 0, 1.0, 'queue_rails', note='rope-barrier stand-in (timber rail)')
    s.add('BPP_Cart_03', -14, -12, 0, 1.0, 'carts')
    s.add('BPP_Cart_04', 14, -12.5, 0, 1.0, 'carts')
    s.add('MV_cart_02', 20, -9, 20, 1.0, 'carts', roll=4, note='wheels off')
    s.add('MV_Fence_01_Log1', -6, -7.5, 0, 1.6, 'nameboard')
    s.add('MV_Fence_01_Log1', -3.5, -7.5, 0, 1.6, 'nameboard')
    s.add('B01_sign02', -4.75, -7.5, 90, 1.0, 'nameboard', verdict_check=True, note='platform name board I23 (painted wood, no metal)')
    for i, k in enumerate(['BPP_Jute_Bags', 'BPP_Jute_Bags_03', 'BPP_Boxes', 'BPP_Boxes_02', 'BPP_Barrels_03']):
        s.add(k, -12 + 3.2 * i, 8.5, 0, 1.0, 'stacked')
    s.add('AB_Tent_A', 2, 20, 90, 0.8, 'tents')
    s.add('AB_Damaged_Tent_A', -9, 18, 30, 1.0, 'tents')
    s.add('AB_Damaged_Tent_A', 12, 16, 250, 1.0, 'tents')
    s.add('AB_Tent_C_Frame', -14, 26, 10, 1.0, 'tents')
    s.add('AB_Tent_C_Cloth', -14, 26, 10, 1.0, 'tents', attach=True)
    s.add('AB_Tent_C_Frame', 14, 27, 170, 1.0, 'tents')
    s.add('AB_Tent_C_Cloth', 14, 27, 170, 1.0, 'tents', attach=True)
    s.add('AB_Tent_B_Cloth_low', -4, 28, 80, 1.0, 'tents')
    s.add('PH_fire_pit', -3, 13, 0, 1.0, 'camp')
    s.add('PH_fire_pit', 9, 24, 0, 0.9, 'camp')
    s.scatter(POTS + ['MV_bucket_01', 'MV_bucket_03', 'MV_carafe_01'], 10, 2, 16, 8, 'camp', (0.9, 1.1), min_sep=1.0)
    s.add('AB_FogCard', 0, 5, 0, 1.2, 'fog', optional=True, note='optional: reads as a glowing white orb (LANE_SD)')
    s.add('AB_FogCard', 10, 14, 30, 1.0, 'fog', optional=True)
    S.append(s)

    # ---- S15 the works (P16) --------------------------------------------------------------------
    s = Site('S15_Works', 'Iphrib Khazb, the Works (the old forge)', 2615, -58, 'works ruin', 'landmark',
             'the Geiger peak is bound here; AMB_V5_WorksInfra; IDLE_MIDDLE_05 "we\'ll have tea while we wait"', 3,
             'bazaar stone + timber: a traditional forge (no modern industry)', 2, 45, search_m=8,
             layout='''
  ==== road (58 m right) ====
     [gutted U-building]   [furnace hall: BrokenStructer]  chimney stack (Pillar_low)   [gutted U-building]
        dead pulley: mill wheel on its support + beams + rope
        spill yard: clay storage jars, pots, barrels, logs   slag heaps (rubble01)
        foreman's corner: cold hearth (Fireplace), pot on it, table, two lamps
''', notes='Optional: one smouldering ground FX (NS_Fire_Floor_01_Smoke) "the ground is still hot"; off by default (no one tends a fire here).')
    s.add('AB_BrokenStructer', 0, 0, 'face_road', 1.0, 'hall', landmark=True)
    s.add('AB_Pillar_low', 5, -4, 0, 1.0, 'hall', landmark=True, note='furnace chimney stack')
    s.hut('AB_300x400_Mid_Damaged_A', -15, 2, 9, 6, 0, 'gutted_w', broken={0, 3, 6})
    s.hut('AB_300x400_Mid_Damaged_A', 15, 3, 9, 6, 0, 'gutted_e', broken={1, 4})
    s.add('MV_Wm_wheel_support', 0, 12, 0, 1.0, 'pulley')
    s.add('MV_Woodmill_Wheel', 0, 12, 0, 0.7, 'pulley', attach=True, note='dead pulley')
    s.add('MV_Beam_03', 2, 12, 0, 1.0, 'pulley', roll=90, pitch=80)
    s.add('MV_Rope_01', 0.5, 12.5, 0, 2.0, 'pulley', attach=True)
    s.scatter(['B01_tank01', 'B01_tank01', 'AB_Clay_Pot_A', 'AB_Clay_Pot_D', 'MV_barrel_01', 'PH_barrel'], 12, -8, 16, 6,
              'spill_yard', (0.9, 1.2), min_sep=1.2)
    s.add('MV_Logs_Package', 8, 18, 30, 1.0, 'spill_yard')
    s.add('MV_Logs_Package', 8.6, 18.4, 32, 1.0, 'spill_yard', stack=True)
    for cu, cv in ((20, 14), (-22, 12), (12, -12)):
        s.add('B01_rubble01', cu, cv, s.rng.uniform(0, 360), 1.2, 'slag')
    s.add('AB_Fireplace', -6, 10, 180, 0.8, 'foreman', note='cold hearth (4.6 m with its chimney at x1)')
    s.add('PH_pot', -6, 9.2, 0, 1.0, 'foreman', stack=True, drop_cm=90, note='kettle stand-in (kettle + tea glasses missing)')
    s.add('AB_Table', -4.5, 8, 0, 1.0, 'foreman')
    s.add('AB_Lamp_A', -4.4, 8, 0, 1.0, 'foreman', stack=True, drop_cm=70)
    s.add('AB_Lamp_A', -4.7, 7.8, 0, 1.0, 'foreman', stack=True, drop_cm=70)
    s.scatter(AB_BRICKS, 40, 0, 4, 22, 'rubble', (0.9, 1.5))
    s.scatter(SHRUBS, 10, 0, 0, 28, 'withered_ring', (0.9, 1.3), min_sep=3)
    s.add('MV_Fence_01_Log1', 22, 22, 0, 1.6, 'boards')
    s.add('B01_sign02', 22, 22, 90, 0.8, 'boards', verdict_check=True, note='danger board I20')
    s.add('VFX_Fire_Floor_01_Smoke', 3, -2, 0, 1.0, 'fx', optional=True, note='OFF by default')
    s.add('B01_crane01', -9, -6, 'face_road', 1.0, 'hall', note='hand-cranked hoist at the hall')
    s.add('B01_pump01', -3, 8.6, 180, 1.0, 'foreman', verdict_check=True, note='brass-gauge pressure pump (biofuel works); keep only if it reads retrofuturist')
    for i, (cu, cv, yw) in enumerate(((-12, 18, 20), (-6, 21, 110), (-14, 13, 250))):
        s.add('B01_pipe01', cu, cv, yw, 1.0, 'spill_yard', verdict_check=True, note='riveted pipe elbow, lying')
    s.run('B01_rail01', [(4, 3), (6, 17)], 'handcart_track', 1.0, verdict_check=True)
    S.append(s)

    # ---- L07 the reed-cutters' camp -------------------------------------------------------------
    s = Site('L07_ReedCutters', "The Reed-Cutters' Camp", 2800, 70, 'camp (lone)', 'inhabited-then-abandoned',
             'none: basin work camp; reed bundles left drying', 2, 'timber racks + AshesOfBazaar frames', 27, 25,
             search_m=15, layout='''
    drying racks (fence runs) with bundles   stripped tent frame   fire pit   plank walk   bucket
''')
    s.run('MV_Fence_01_V1', [(-8, 0), (8, 0)], 'racks', 1.0)
    s.run('MV_Fence_01_V3', [(-8, 3), (4, 3)], 'racks', 1.0)
    for i in range(4):
        s.add('MV_Hay_Bale_0%d' % (1 + i % 2), -6 + 4 * i, 1.5, 90, 0.8, 'bundles', note='reed bundles')
    s.add('AB_Tent_C_Frame', 10, 8, 30, 1.0, 'camp')
    s.add('PH_fire_pit', 6, 10, 0, 0.9, 'camp')
    s.run('AB_Planks_150_B', [(-12, 10), (0, 12)], 'walk', 1.0)
    s.add('MV_bucket_03', 7, 11.5, 0, 1.0, 'camp')
    s.add('MV_Logs_Package', 12, 4, 60, 1.0, 'camp')
    S.append(s)

    # ---- S16 the quarry (P17) -------------------------------------------------------------------
    s = Site('S16_Quarry', 'Egdiber, the Quarry', 2900, -70, 'quarry', 'rest',
             'no voice: breaks up the 480 m long straight where the ground tilts up', 2, 'cut stone', 3, 30, search_m=20,
             layout='''
  ==== road (70 m right) ====
        scree fan   sledge on log rollers + rope   bucket
     squared blocks in rows (brick01 x8), half-cut block
     [cut face: rock_face x2 + temple stones stepped]
''')
    s.add('PH_rock_face', -4, -10, 'face_road', 1.0, 'face')
    s.add('PH_rock_face', 6, -11, 'face_road', 0.9, 'face')
    for i in range(3):
        s.add('FAB_TempleStones', -6 + 5 * i, -7, 'face_road', 1.0, 'face')
    for r in range(2):
        for i in range(4):
            s.add('B01_brick01', -6 + 3.5 * i, -1 + 3 * r, s.rng.uniform(-4, 4), 1.0, 'blocks',
                  note='squared block; mason mark I28 on 3 of them later')
    s.add('B01_brick01', 7, -5, 5, 1.0, 'blocks', note='half-cut block (chisel + mallet missing)')
    s.add('AB_Planks_150_B', 2, 6, 10, 1.0, 'sledge', stack=True, drop_cm=40)
    s.add('MV_Log_07', 1.4, 6, 95, 0.6, 'sledge')
    s.add('MV_Log_08', 2.8, 6, 95, 0.6, 'sledge')
    s.add('MV_Rope_01', 3, 7, 0, 3.0, 'sledge', attach=True)
    s.add('MV_bucket_03', 4, 5, 0, 1.0, 'sledge')
    s.add('B01_crane01', -2, -4, 'face_road', 1.0, 'face', note='hand-cranked hoist over the cut face')
    s.run('B01_rail01', [(-4, 5), (6, 8)], 'handcart_track', 1.0, verdict_check=True)
    s.add('B01_rubble01', -8, -3, 30, 1.0, 'scree')
    s.add('B01_rubble01', 9, -2, 130, 0.8, 'scree')
    s.scatter(PEBBLES + ['LF_Rock_05'], 24, 0, -4, 10, 'scree', (0.6, 1.4))
    S.append(s)

    # ---- L15 the flank terraces -----------------------------------------------------------------
    s = Site('L15_FlankTerraces', 'The Dead Fields on the Flank', 2950, -150, 'field terraces (lone)',
             'inhabited-then-abandoned', 'the fields "fell quiet, one by one" (B10)', 2, 'dry-stone walls', 28, 40,
             search_m=30, layout='''
    four terrace walls (wall02 runs) stepping up the flank, a field hut (wall03), dead shrubs
''')
    for row in range(4):
        s.run('B01_wall02', [(-18, -8 * row), (18, -8 * row + 2)], 'terraces', 1.0, skip={(row * 3) % 9}, ism=True)
    s.add('B01_wall03', 20, -12, 250, 1.0, 'hut')
    s.scatter(SHRUBS, 10, 0, -12, 20, 'ground', (1.0, 1.5), min_sep=3)
    S.append(s)

    # ---- S17 the dry cistern (P18) --------------------------------------------------------------
    s = Site('S17_DryCistern', 'Zudh Akhetr, the Dry Cistern', 3050, 22, 'cistern', 'landmark',
             'B10 "The water came later each year..." + "Keep them together"; Geiger bump to ~4 cps', 2,
             'BAZAAR STONE: stepped terraces, an arcade of arches and pillars on the rim', 1, 35, search_m=6,
             layout='''
  ==== road ====
      entrance name stone (marker01)   well at the top   gauge column (pillar01) at the stair head
      terrace 1 (Broken_Walls)  ----------------------
         terrace 2  ----------------   broken jars on lower and lower steps
            terrace 3  ----------      central stair (floor01 landings + brick01 steps)
               bottom: dead trunk across; one whole jar on the lowest step
      far rim: arcade Side_Arch x4 + Damaged_Pillar_A x2 + pillar01 x4 at the corners
''')
    for level in range(4):
        half = 9.0 - 1.6 * level
        s.run('AB_Broken_Walls', [(-half, -8 + 3.2 * level), (half, -8 + 3.2 * level)], 'terraces', 1.0,
              skip={2 + level} if level % 2 else set())
    for level in range(4):
        s.add('B01_floor01', 0, -6.4 + 3.2 * level, 0, 0.6, 'stair', note='landing')
        s.add('B01_brick01', 0, -8 + 3.2 * level, 90, 0.6, 'stair', note='step')
    s.add('MV_well', -7, -12, 0, 1.0, 'top')
    s.add('B01_pillar01', 2.2, -9.5, 0, 0.6, 'top', note='water gauge column (I30 later)')
    s.add('B01_marker01', -2.5, -12.5, 90, 0.9, 'top', note='entrance name stone (I31 later)')
    s.add('B01_scale01', 2.2, -8.6, 0, 1.0, 'top', verdict_check=True, note='timber water gauge beside the column; keep only if the marks read hand-cut')
    for level in range(4):
        s.add(POTS[level % 4], -1.6 + 0.4 * level, -6.8 + 3.2 * level, 0, 1.0, 'jars', roll=(85 if level < 3 else 0),
              note='broken jar' if level < 3 else 'the one whole jar, lowest step')
    s.add('PH_trunk_02', 0, 4.8, 80, 1.0, 'bottom')
    s.run('AB_Side_Arch', [(-9, 8.5), (9, 8.5)], 'arcade', 1.0)
    s.add('AB_Damaged_Pillar_A', -11, 8.5, 0, 0.55, 'arcade', landmark=True)
    s.add('AB_Damaged_Pillar_A1', 11, 8.5, 90, 0.55, 'arcade', landmark=True)
    for cu, cv in ((-11, -11), (11, -11), (-13, 0), (13, 0)):
        s.add('B01_pillar01', cu, cv, s.rng.uniform(0, 30), 1.0, 'corners')
    s.scatter(AB_BRICKS, 18, 0, 0, 13, 'rubble', (0.9, 1.4))
    s.add('MV_Fence_01_Log1', -12, -14, 0, 1.6, 'board')
    s.add('B01_sign02', -12, -14, 90, 0.8, 'board', verdict_check=True, note='danger board I20')
    S.append(s)

    # ---- L09 the caravan halt on the long straight ----------------------------------------------
    s = Site('L09_CaravanHalt', 'The Caravan Halt', 3120, -40, 'halt (lone)', 'inhabited-then-abandoned',
             'none: where caravans watered animals before the climb', 2, 'bazaar stone arcade + MV manger', 29, 25,
             search_m=12, layout='''
  ==== road (40 m right) ====
     arcade wall (Side_aRCH_WALL)   trough (channel01)   manger + tethering posts   enclosure (wall04 x3)
''')
    s.add('AB_Side_aRCH_WALL', 0, -6, 'face_road', 1.0, 'arcade', landmark=True)
    s.add('B01_channel01', -2, 0, 90, 0.8, 'trough')
    s.add('MV_Manger', 5, 1, 0, 1.0, 'manger')
    for i in range(4):
        s.add('MV_Fence_01_Log1', 3 + 2.2 * i, 3.5, 0, 1.3, 'posts', roll=s.rng.uniform(-6, 6))
    s.run('B01_wall04', [(-12, -2), (-12, 10), (0, 12)], 'enclosure', 1.0, skip={2})
    s.scatter(AB_BRICKS, 12, 0, 2, 10, 'rubble', (0.9, 1.4))
    S.append(s)

    # ---- S18 the tea hearth (P19) ---------------------------------------------------------------
    s = Site('S18_TeaHearth', 'Ghafeth Ethris, the Tea Hearth', 3220, -9, 'hearth', 'rest',
             'IDLE_MIDDLE_05 / _08 (tea, apricots): visual only; the last easy ground before the climb', 1,
             'stones + cloth', 3, 12, layout='''
  ==== road ====
     ring of 8 fist stones, pot on three stones, a flat stone, folded cloth; hero dead tree leaning over
''')
    s.ring('LF_Rock_08', 8, 0, 0, 0.6, 'hearth', 0.9)
    for i in range(3):
        s.add('LF_Rock_07', 0.15 * math.cos(2.1 * i), 0.15 * math.sin(2.1 * i), 60 * i, 1.0, 'hearth')
    s.add('PH_pot', 0, 0, 0, 1.0, 'hearth', stack=True, drop_cm=50, note='kettle stand-in (kettle, tea glasses, apricots missing)')
    s.add('FAB_TempleStones', 1.4, -0.4, 30, 0.3, 'hearth', note='flat stone for the glasses')
    s.add('MV_Cloth_02', -1.2, 0.8, 0, 0.18, 'hearth', stack=True, drop_cm=30, note='folded blanket stand-in')
    s.add('FAB_DeadTree_qlEtl', -3.5, -2.5, 140, 0.9, 'tree', roll=8, landmark=True, note='hero dead tree #4 of 4')
    S.append(s)

    # ---- L10 the foot-of-the-climb farm ---------------------------------------------------------
    s = Site('L10_FootFarm', 'The Last Farm below the Climb', 3300, 45, 'farmstead (lone)', 'inhabited-then-abandoned',
             'none: the highest farm; above it only the road', 1, 'MedievalVillage wood (farm)', 30, 30, search_m=25,
             layout='''
     annex shed   pen   hay x3   fence runs   well   log pile   cart
''')
    s.add('BPP_Annex_03', -6, 4, 0, 1.0, 'shed', search_local_m=6)
    s.add('BPP_Wooden_Pen_01', 10, 4, 0, 1.0, 'pen', search_local_m=6)
    for i in range(3):
        s.add('MV_Hay_Bale_01', -2 + 1.6 * i, -3, 90, 1.0, 'hay', roll=(4 if i == 1 else 0))
    s.run('MV_Fence_03_V2', [(-14, -8), (14, -8)], 'fence', 1.0, skip={2, 7})
    s.add('MV_well', 4, -4, 0, 1.0, 'yard')
    s.add('BPP_Logs_03', -12, -2, 20, 1.0, 'yard')
    s.add('BPP_Cart_05', 16, -4, 110, 1.0, 'yard')
    S.append(s)

    # ---- S19 the last waystation (P20) ----------------------------------------------------------
    s = Site('S19_LastWaystation', 'Nefr Rzag, the Last Waystation', 3400, -14, 'waystation outpost', 'rest (the hinge)',
             'B11: the lean-to, the empty cradle with the dead spare, the plaque "Leave the bearer where it rests..."', 1,
             'MedievalVillage WOOD (the one timber outpost on the road)', 1, 35, search_m=0,
             layout='''
  L (rising):  [roofless timber hut: foundation + walls + rafters]  hay annex   log pile
               [V7 core: tarp lean-to, cradle with the dead spare, plaque, flag, cold fire pit]  (story-owned; 12 m kept clear)
               opened jute bags by the cradle   lantern post (cold)   rope coil
  ======================= road (the bend) ========================
  R (flat):    corral (wooden pen)   manger for animals   well   buckets   second lean-to (annex_01)
''', story_owned=['V7 waystation (SM_Annex_Tarp_01 on log posts, SM_Manger cradle with the dead spare, plaque, Tripo Flag, stone_fire_pit)'],
             notes='If V7 is missing, place the cradle placeholder group (flagged story_owned_if_missing) and tell the story lane.')
    s.add('MV_Manger', 0, 0, 0, 1.0, 'v7_placeholder', story_owned_if_missing=True, note='the cradle (V7)')
    s.add('MV_Annex_Tarp_01', 0, -1.2, 0, 1.0, 'v7_placeholder', story_owned_if_missing=True)
    s.pile(['MV_jute_bag_07', 'MV_jute_bag_08', 'MV_jute_bag_10'], 3, 2.6, 0.5, 0.6, 'bags', note='opened and emptied: loads taken on')
    s.add('MV_Fence_01_Log1', 4, 2, 0, 1.7, 'lantern')
    s.add('PH_lantern', 4, 2, 0, 1.0, 'lantern', stack=True, drop_cm=200, note='cold lantern hung on the post')
    s.add('MV_Rope_01', 3, 2.5, 0, 2.5, 'lantern', note='rope coil')
    s.add('MV_Foundation', -6, -14, 0, 1.0, 'hut')
    s.add('MV_Foundation_Corner', -9, -14, 0, 1.0, 'hut')
    s.add('MV_Wall_01', -6, -15.5, 0, 1.0, 'hut')
    s.add('MV_Wall_03', -3, -12.5, 90, 1.0, 'hut')
    s.add('MV_Roof_Beams_Middle', -6, -13, 0, 1.0, 'hut', stack=True, drop_cm=300, note='bare rafters')
    s.add('MV_Annex_Hay', 6, -14, 180, 1.0, 'hut', search_local_m=5)
    s.add('BPP_Logs_01', -12, -8, 30, 1.0, 'hut')
    s.add('TRIPO_Flag', -2, 5.4, 0, 6.0, 'flag', note='banner I33 stand-in over the bend (V7 flag may already exist)')
    s.add('BPP_Wooden_Pen_02', 8, 30, 0, 1.0, 'corral')
    s.add('MV_Manger', 2, 26, 90, 1.0, 'corral', note='manger for animals')
    s.add('MV_well', -6, 25, 0, 1.0, 'corral')
    s.add('MV_bucket_01', -4.6, 24.5, 0, 1.0, 'corral')
    s.add('MV_bucket_02', -4.8, 26, 0, 1.0, 'corral', roll=90)
    s.add('BPP_Annex_01', -14, 30, 180, 1.0, 'corral')
    s.scatter(['MV_Hay_Bale_01', 'MV_Hay_Bale_02'], 3, 10, 26, 3, 'corral')
    S.append(s)

    # ---- S20 the Long Stair / the Knees ---------------------------------------------------------
    s = Site('S20_LongStair', 'The Long Stair (the Knees)', 3650, 0, 'switchback fortifications', 'landmark',
             'B12 knee fault on the 79 % pitch (3,600) and the steep bursts: slumped paving (RVT), retaining walls', 2,
             'BAZAAR STONE: fort-wall retaining walls, pillars, way-stones on each outer apex', 1, 90,
             layout='''
      outer apex 3,605: retaining wall run (Fort_Wall_Mid x4) + pillar + way-stone + rockfall fan below
      outer apex 3,695: same
      3,560-3,720: a way-stone every ~20 m on the outer verge (the stair of stones)
''', notes='Positions are per-apex in world space (computed from the turn direction).')
    S.append(s)

    # ---- S21 the cloud niche (P21, not a shrine) ------------------------------------------------
    s = Site('S21_CloudNiche', "Tabaad Se'hk, the Cloud Niche (rest niche)", 3850, 0, 'rest niche', 'landmark',
             'enters the cloud (AMB_Z5 wind + drizzle start); pre-echoes RADIO_B15_01', 2, 'stone', 3, 12,
             layout='''
  outer apex of the first hairpin: a niche built of temple stones + broken walls against the slope
     three unlit lamps, two clay bowls, a water jar; a way-stone on the apex; cloth strips on a post fading into cloud
''', notes='Content rule: no shrine, votive tablets, bell or prayer flags; it is a travellers\' rest niche.')
    S.append(s)

    # ---- S22 the vow-stone (P22) ----------------------------------------------------------------
    s = Site('S22_VowStone', 'Zrir Jaezen, the Vow-Stone', 4015, 0, 'marker', 'reveal',
             'B13 second knee fault at the same bend: a human vow beside the machine\'s', 1, 'stone', 4, 8,
             layout='''
  inner apex of the second hairpin: one knee-high rough stone leaning into the slope, three pebbles on top
  (worn sandals + cloth tie: MISSING)
''')
    S.append(s)

    # ---- L12 the cloud goatherd hut -------------------------------------------------------------
    s = Site('L12_CloudHut', "The Goatherd's Hut in the Cloud", 4150, -28, 'hut (lone)', 'inhabited-then-abandoned',
             'none: a silhouette in the fog, 28 m off the road', 2, 'stone', 31, 20, search_m=12,
             layout='''
     roofless hut (wall03)   dry-stone pen ring (Broken_Walls)   posts   bucket
''')
    s.add('B01_wall03', 0, 0, 'face_road', 1.0, 'hut')
    s.ring('AB_Broken_Walls', 16, 6, 6, 4.5, 'pen', 1.0, gaps={3, 11}, face=90)
    s.add('MV_Fence_01_Log1', 4, 2, 0, 1.3, 'pen')
    s.add('MV_bucket_02', 0, 3.0, 0, 1.0, 'hut', roll=100, note='tipped outside the hut (at 1,1 it landed on the wall03 wall top; LANE_SD)')
    S.append(s)

    # ---- S23 the pass cairn (P23) ---------------------------------------------------------------
    s = Site('S23_PassCairn', 'Tfedrimet, the Pass Cairn', 4300, -7.5, 'cairn', 'guidance',
             'mood transition "storm dusk -> clear above" (look key 4,350 m)', 0, 'stacked stone + cloth strips', 3, 15,
             layout='''
  ==== road ====
     2.5 m cairn (3 big + 3 mid + 3 small stones, physics-stacked), stele set in its road face
     three low poles with plain cloth strips fanned downhill (no prayer flags)
''')
    for i, (k, sc) in enumerate((('LF_Rock_04', 0.8), ('LF_Rock_03', 0.8), ('LF_Rock_05', 0.8),
                                 ('LF_Rock_01', 0.55), ('LF_Rock_02', 0.5), ('PH_moss_rock_09', 0.6),
                                 ('LF_Rock_08', 1.6), ('LF_Rock_08', 1.3), ('LF_Rock_07', 2.0))):
        # the base ring is set on the ground as solids (not stacked): with big stacked base rocks the emulated
        # drop perched them on each other and cantilevered one into the air (LANE_SD)
        if i < 3:
            s.add(k, 1.0 * math.cos(2.1 * i), 1.0 * math.sin(2.1 * i), 70 * i, sc * 0.7, 'cairn')
        else:
            r = 0.45 if i < 6 else 0.12
            s.add(k, r * math.cos(2.1 * i), r * math.sin(2.1 * i), 70 * i, sc, 'cairn', stack=True, drop_cm=60 + 70 * (i // 3))
    s.add('FAB_TempleStones', 0, 2.4, 'face_road', 0.7, 'cairn', pitch=90, note='pass stele I38 (upright), clear of the cairn base: at 1.4 m the base stones landed on its top (LANE_SD)')
    for i in range(3):
        s.add('MV_Fence_01_Log1', -4 - 3 * i, -3 + 3 * i, 0, 1.2, 'poles', roll=s.rng.uniform(-5, 5))
        s.add('MV_Cloth_02', -4 - 3 * i, -3 + 3 * i, 30 * i, 0.2, 'poles', attach=True, z_offset_cm=110)
    S.append(s)

    # ---- S24 the ledge (P24) --------------------------------------------------------------------
    s = Site('S24_Ledge', 'Sleb Zdaw, the Ledge', 4460, -6.5, 'rest seat', 'rest',
             'B14 the look back (G14); then B15', 1, 'stone', 3, 10,
             layout='''
  L 6 m, facing east over the valley: two flat slabs, a trunk bench, a fallen unlit lantern (V8)
''', story_owned=['V8 ledge (stretch S4): place only if missing'])
    s.add('FAB_TempleStones', 0, 0, 'face_valley', 1.0, 'v8', story_owned_if_missing=True)
    s.add('FAB_TempleStones', 2.2, -0.4, 'face_valley', 0.9, 'v8', story_owned_if_missing=True)
    s.add('PH_trunk', 1, -2, 'face_valley', 0.6, 'v8', story_owned_if_missing=True)
    s.add('PH_lantern', 1.8, 0.2, 0, 1.0, 'v8', roll=90, story_owned_if_missing=True, stack=True, drop_cm=60)
    S.append(s)

    # ---- L13 the shoulder cairn line (replaces the cable poles: no modern infrastructure) ---------
    s = Site('L13_ShoulderCairns', 'The Cairn Line on the Shoulder', 4640, 0, 'cairn line (lone)', 'guidance',
             'B15/B16: the road\'s nearest pass to the summit; cairns lead the eye to the mast', 0, 'stacked stone',
             32, 60, layout='''
  every ~40 m, alternating verges: a cairn of 4 stones; a cloth strip on the first
''', notes='Replaces the road bible\'s cable-pole line (P25): the author ruled out poles and wires.')
    S.append(s)

    # ---- S25 the last look back (P27): verify only -----------------------------------------------
    s = Site('S25_LastLookBack', 'Ibartegh, the Last Look Back', 4877, -2, 'wall + inscribed stone', 'rest',
             'B21 held 10 s; the Segalen stone (never cut)', 0, 'stone', 5, 10, verify_only=True,
             layout='  story-owned V9 wall and Segalen stone: add NOTHING; capture only',
             story_owned=['V9 low wall + Segalen stone', 'Saskarta.Glance.SegalenWall'])
    S.append(s)

    # ---- S26 the High Voice hut (P28): interior only ---------------------------------------------
    s = Site('S26_HighVoiceHut', 'The High Voice relay hut (interior)', 4995, 8, 'hut interior', 'landmark',
             'B23/B24: the mark, the transmission, the held seated shot', 0, 'AshesOfBazaar furniture', 5, 8,
             layout='''
  inside the V10 hut: desk (table), chair with a blanket over its back, cold lantern, water jar, a box of logs/papers
  (radio desk set: MISSING; no modern equipment beyond the story's own mast and crown)
''', story_owned=['V10 hut + BP_Saskarta_HighVoice (mast, crown)'],
             notes='Anchor on the hut actor: the editor lane shifts this group to the hut interior before settling.')
    s.add('AB_Table', 0, 0, 'face_road', 1.4, 'interior')
    s.add('AB_Chair_A_low', -0.8, 0.2, 'face_road', 1.0, 'interior')
    s.add('MV_Cloth_01', -0.8, 0.2, 0, 0.3, 'interior', stack=True, drop_cm=120)
    s.add('PH_lantern', 0.3, 0, 0, 1.0, 'interior', stack=True, drop_cm=90)
    s.add('AB_Clay_Pot_C', 1.2, 0.8, 0, 1.0, 'interior')
    s.add('MV_box_05', 1.4, -0.8, 20, 1.0, 'interior')
    S.append(s)

    # ---- L14 the old town on the east bench (far landmark) ---------------------------------------
    s = Site('L14_OldTown', 'The Old Town on the Bench', 900, -330, 'town ruin (lone, far landmark)',
             'inhabited-then-abandoned', 'seen from the valley road and back from the crest (1,980 m): the valley\'s town', 3,
             'BAZAAR STONE: mud-brick blocks, tower houses, fort-wall circuit', 12, 80, search_m=60,
             layout='''
        tower house03        village01 block        tower house03
     fort-wall circuit (Fort_Wall_Mid runs, broken)      village01 block    ruin01
''', notes='Far landmark: draw distance 3 km; it must read at 300-2,000 m as a silhouette, so few, large pieces.')
    s.add('B01_village01', -18, 0, 20, 1.0, 'blocks', landmark=True)
    s.add('B01_village01', 22, 8, 200, 0.9, 'blocks', landmark=True)
    s.add('B01_house03', -40, 20, 10, 1.1, 'towers', landmark=True)
    s.add('B01_house03', 45, -18, 60, 1.0, 'towers', landmark=True)
    s.add('B01_ruin01', 5, -30, 90, 1.0, 'blocks', landmark=True)
    s.run('AB_Fort_Wall_Mid', [(-55, 35), (0, 45), (55, 30)], 'circuit', 1.0, skip={2, 3, 8, 12, 13}, ism=True)
    s.run('AB_Fort_Wall_Mid', [(-55, -35), (0, -50), (55, -38)], 'circuit', 1.0, skip={0, 5, 6, 11}, ism=True)
    S.append(s)

    # ---- L11 the basin fields -------------------------------------------------------------------
    s = Site('L11_BasinFields', 'The Basin Fields', 2700, 60, 'fields (lone)', 'inhabited-then-abandoned',
             'none: the fields the works poisoned; dead shrub rings where nothing grows back', 3, 'dry-stone + MV shed',
             33, 30, search_m=20, layout='''
     field walls (wall02) in two lines, a field shelter (annex), dead shrub rings
''')
    s.run('B01_wall02', [(-20, 0), (20, 2)], 'walls', 1.0, skip={3, 6}, ism=True)
    s.run('B01_wall02', [(-20, 14), (16, 16)], 'walls', 1.0, skip={1}, ism=True)
    s.add('BPP_Annex_03', 18, 8, 270, 1.0, 'shelter')
    s.ring('FAB_Shrub_C', 10, -6, 7, 4.5, 'dead_ring', 1.2)
    s.ring('FAB_Shrub_E', 8, 8, 8, 3.5, 'dead_ring', 1.2)
    S.append(s)

    # ---- roadside caravan echoes ----------------------------------------------------------------
    for sid, m, v, name, spec in (
            ('R01_Verge620', 620, -8, 'Tipped cart and bags', 'cart'),
            ('R02_Verge1080', 1080, 7.5, 'Two boxes and a pot at a verge stone', 'boxes'),
            ('R03_Verge3300', 3300, -8, 'A handcart and a stack of bags', 'handcart'),
            ('R04_Verge3750', 3750, 0, 'A single dropped bundle', 'bundle'),
            ('R05_Verge4150', 4150, 6.5, 'A water jar on a verge stone', 'jar')):
        s = Site(sid, name, m, v, 'roadside vignette', 'reveal', 'the caravan echoes (road bible layer)', 2, 'props', 40, 8,
                 layout='  ' + name)
        if spec == 'cart':
            s.add('MV_cart_02', 0, 0, 10, 1.0, 'v', pitch=-75, note='on its side: long along Y, so the tip is a pitch (LANE_SD)')
            s.pile(BAGS[:3], 3, 2, -1.5, 0.8, 'v')
        elif spec == 'boxes':
            s.add('B01_marker01', 0, 0.5, 90, 1.0, 'v')
            s.pile(['AB_Box_A', 'AB_Box_C'], 2, 1.4, 0.3, 0.5, 'v')
            s.add('AB_Clay_Pot_A', 2.2, 0.9, 0, 1.0, 'v')
        elif spec == 'handcart':
            s.add('AB_Cart_A_texturing', 0, 0, 90, 0.7, 'v', pitch=-6)
            s.pile(BAGS[5:], 5, 2.5, -1, 1.0, 'v')
        elif spec == 'bundle':
            s.add('MV_jute_bag_03', 0, 0, 0, 1.0, 'v', note='placed on the outer verge by the resolver')
            s.add('MV_Cloth_02', 0, 0, 30, 0.25, 'v', stack=True, drop_cm=60)
        else:
            s.add('B01_marker01', 0, 0, 90, 1.0, 'v')
            s.add('AB_Clay_Pot_B', 0, 0, 0, 1.0, 'v', stack=True, drop_cm=120, note='canteen stand-in (canteen missing)')
        S.append(s)
    return S


def apex_items(W, S):
    """Per-apex dressing for the switchbacks, placed in world-relative road frames."""
    by = {s.sid: s for s in S}
    # the Long Stair: two apexes plus the way-stone stair
    s = by['S20_LongStair']
    for apex in (3605.0, 3695.0):
        side = -W.turn_sign(apex)          # outer side of the bend
        du = apex - s.road_m
        s.run('AB_Fort_Wall_Mid', [(du - 6, side * 6.6), (du + 6, side * 6.6)], 'retaining_%d' % apex, 1.0, skip={1})
        s.add('AB_Damaged_Pillar_A', du, side * 9.5, 0, 0.45, 'apex_%d' % apex)
        s.add('B01_marker01', du + 2, side * 5.8, 90, 1.0, 'apex_%d' % apex)
        s.add('B01_rubble01', du - 2, side * 14, 30, 1.2, 'rockfall_%d' % apex)
        s.scatter(['LF_Rock_05', 'LF_Rock_08', 'LF_Rock_07'], 10, du, side * 14, 5, 'rockfall_%d' % apex, (0.4, 1.2))
    for m in range(3560, 3730, 20):
        side = -W.turn_sign(m)
        s.add('B01_marker01', m - s.road_m, side * 5.8, 90, s.rng.uniform(0.85, 1.1), 'stair_of_stones',
              roll=s.rng.uniform(-10, 10))
    # the cloud niche on the outer apex of the first hairpin
    s = by['S21_CloudNiche']
    side = -W.turn_sign(3850)
    s.add('FAB_TempleStones', 0, side * 7.2, 'face_road', 1.2, 'niche', pitch=90)
    s.add('FAB_TempleStones', 2.4, side * 7.4, 'face_road', 1.1, 'niche', pitch=90)
    s.add('FAB_TempleStones', 1.2, side * 7.6, 'face_road', 1.3, 'niche', stack=True, drop_cm=250, note='lintel stone (I34 later)')
    s.run('AB_Broken_Walls', [(-2, side * 6.2), (-2, side * 8.4)], 'niche', 1.0)
    s.run('AB_Broken_Walls', [(4, side * 6.2), (4, side * 8.4)], 'niche', 1.0)
    for i, k in enumerate(('AB_Lamp_A', 'AB_Lamp_B', 'AB_Lamp_C')):
        s.add(k, 0.4 + 0.6 * i, side * 7.0, 0, 0.8 if k == 'AB_Lamp_B' else 1.0, 'niche', note='unlit')
    s.add('AB_Clay_Pot_D', 2.4, side * 6.9, 0, 0.8, 'niche')
    s.add('AB_Clay_Pot_D', 2.9, side * 7.0, 0, 0.7, 'niche')
    s.add('B01_tank01', -1.0, side * 7.0, 0, 0.8, 'niche', note='water jar')
    s.add('B01_marker01', 6, side * 5.8, 90, 1.0, 'apex')
    s.add('MV_Fence_01_Log1', 7, side * 9, 0, 1.4, 'cloth')
    s.add('MV_Cloth_02', 7, side * 9, 0, 0.2, 'cloth', attach=True, z_offset_cm=120)
    # the vow-stone on the inner apex of the second hairpin
    s = by['S22_VowStone']
    side = W.turn_sign(4015)
    s.add('PH_moss_rock_09', 0, side * 6.0, 0, 0.45, 'stone', pitch=-10, note='leaning into the slope; I37 scratched later')
    for i in range(3):
        s.add('LF_Rock_07', 0.1 * i, side * 6.0, 60 * i, 1.0, 'stone', stack=True, drop_cm=120 + 20 * i)
    # the shoulder cairn line
    s = by['L13_ShoulderCairns']
    for i, m in enumerate((4600, 4640, 4680, 4720)):
        v = 6.5 if i % 2 else -6.5
        for j, (k, sc) in enumerate((('LF_Rock_05', 0.45), ('LF_Rock_01', 0.35), ('LF_Rock_08', 1.2), ('LF_Rock_07', 1.5))):
            s.add(k, m - s.road_m + 0.05 * j, v, 70 * j, sc, 'cairn_%d' % i, stack=True, drop_cm=60 + 50 * j)
        if i == 0:
            s.add('MV_Fence_01_Log1', m - s.road_m + 1.2, v, 0, 1.2, 'cairn_0')
            s.add('MV_Cloth_02', m - s.road_m + 1.2, v, 0, 0.2, 'cairn_0', attach=True, z_offset_cm=110)
    # the dropped bundle sits on the outer verge
    s = by['R04_Verge3750']
    side = -W.turn_sign(3750)
    for it in s.items:
        it['v'] = side * 6.3


# ---------------------------------------------------------------------------- resolve

def rect_corners(x, y, yaw_deg, sx, sy):
    c, s_ = math.cos(math.radians(yaw_deg)), math.sin(math.radians(yaw_deg))
    hx, hy = sx / 2.0, sy / 2.0
    return [(x + a * c - b * s_, y + a * s_ + b * c) for a, b in ((-hx, -hy), (hx, -hy), (hx, hy), (-hx, hy))]


def perimeter(corners, n=4):
    pts = []
    for i in range(4):
        a, b = corners[i], corners[(i + 1) % 4]
        for t in range(n):
            pts.append((a[0] + (b[0] - a[0]) * t / n, a[1] + (b[1] - a[1]) * t / n))
    return pts


def sat_overlap(A, B):
    """Minimum penetration depth (m) of two convex quads, 0 when separated."""
    best = 1e9
    for poly in (A, B):
        for i in range(4):
            ex, ey = poly[(i + 1) % 4][0] - poly[i][0], poly[(i + 1) % 4][1] - poly[i][1]
            L = math.hypot(ex, ey) or 1.0
            nx, ny = -ey / L, ex / L
            pa = [p[0] * nx + p[1] * ny for p in A]
            pb = [p[0] * nx + p[1] * ny for p in B]
            o = min(max(pa), max(pb)) - max(min(pa), min(pb))
            if o <= 0:
                return 0.0
            best = min(best, o)
    return best


def resolve_yaw(W, site, it, x, y, road_yaw):
    y_ = it['yaw']
    if y_ == 'face_summit':
        return math.degrees(math.atan2(SUMMIT_XY[1] / 100.0 - y, SUMMIT_XY[0] / 100.0 - x))
    if y_ == 'face_road':
        _, q = W.road_distance([(x, y)])
        return math.degrees(math.atan2(q[1] - y, q[0] - x))
    if y_ in ('face_downhill', 'face_uphill'):
        d, _ = setdress_offroad.downhill_dir(W, x, y)
        a = math.degrees(math.atan2(d[1], d[0]))
        return a if y_ == 'face_downhill' else a + 180.0
    if y_ == 'face_valley':
        return math.degrees(math.atan2(4635.5 - y, 6165.8 - x))   # toward the boot point
    return road_yaw + y_


V2_KEYS = ('block', 'unit', 'unit_role', 'contact', 'material_set', 'fade_m', 'dust', 'bury_frac', 'layer_role',
           'ref', 'bears_on', 'material', 'state', 'vis_h')


def build(W, S=None):
    """S: the sites to build (default: every V1 site). Tools/World/setdress_v2.py passes its composed sites."""
    if S is None:
        S = sites(W)
        apex_items(W, S)
        S += setdress_offroad.build_sites(W, Site)
    out_sites, totals = [], dict(placements=0, ism_instances=0, actors=0, by_pack={}, by_cat={}, missing=set(),
                                 checks=[], rejected=[])
    for site in S:
        offroad = getattr(site, 'layer', 'road') == 'offroad'
        if offroad:
            centre, f, r, q = setdress_offroad.frame_for(W, site)
            if site.poi.get('reachable'):
                setdress_offroad.add_spur(W, site, q)
        else:
            p0, f, r = W.frame(site.road_m)
            centre = p0 + r * site.v
        road_yaw = math.degrees(math.atan2(f[1], f[0]))
        # site search: nudge the centre (same side) to the flattest ground for its buildings
        if site.search_m > 0 and site.items:
            best, best_c = None, centre
            big = [it for it in site.items if CATALOG[it['key']]['cat'] in ('building', 'wall', 'bpp')] or site.items
            for du in np.linspace(-site.search_m, site.search_m, 7):
                for dv in np.linspace(-site.search_m, site.search_m, 7):
                    c = centre + f * du + r * dv
                    dist, _ = W.road_distance([c])
                    if abs(site.v) > 1 and dist < abs(site.v) * 0.6:
                        continue
                    if offroad and dist < 150.0:
                        continue
                    sl = [W.slope_deg(*(c + f * it['u'] + r * it['v'])) for it in big]
                    score = float(np.mean(sl)) + 0.02 * math.hypot(du, dv)
                    if best is None or score < best:
                        best, best_c = score, c
            centre = best_c
        cx, cy = float(centre[0]), float(centre[1])
        site_z = W.ground(cx, cy)
        pls, idx = [], 0
        placed_rects = []
        for it in site.items:
            e = CATALOG[it['key']]
            cat = e['cat']
            d = CAT[cat]
            lo, hi = (it['scale'] if isinstance(it['scale'], (list, tuple)) else (it['scale'], it['scale']))
            sc = round(site.rng.uniform(lo, hi) * e.get('placement_scale_mult', 1.0), 3)
            if it.get('world_xy'):
                x, y = it['world_xy']
            else:
                x = cx + f[0] * it['u'] + r[0] * it['v']
                y = cy + f[1] * it['u'] + r[1] * it['v']
            yaw = resolve_yaw(W, site, it, x, y, road_yaw)
            size = [v_ / 100.0 * sc / e.get('placement_scale_mult', 1.0) for v_ in e['size_cm']]
            # a stood-up slab (pitch 90) swaps its X and Z footprint
            if abs(it.get('pitch', 0)) > 60:
                size = [size[2], size[1], size[0]]
            if abs(it.get('roll', 0)) > 60:
                size = [size[0], size[2], size[1]]
            fx, fy = max(size[0], 0.2), max(size[1], 0.2)
            notes = []
            # the road core
            for _ in range(8):
                corners = rect_corners(x, y, yaw, fx, fy)
                dist, q = W.road_distance(perimeter(corners) + [(x, y)])
                if dist >= CLEAR_M:
                    break
                away = np.array([x, y]) - q
                n_ = np.linalg.norm(away) or 1.0
                push = CLEAR_M - dist + 0.3
                x += away[0] / n_ * push
                y += away[1] / n_ * push
                notes.append('nudged %.1f m off the road core' % push)
            corners = rect_corners(x, y, yaw, fx, fy)
            dist, _ = W.road_distance(perimeter(corners) + [(x, y)])
            # the collapse set and keep-clear cones
            rm, rd = W.road_m_of(x, y)
            if COLLAPSE_EXCLUSION[0] <= rm <= COLLAPSE_EXCLUSION[1] and rd < COLLAPSE_EXCLUSION[2]:
                totals['rejected'].append('%s/%s: inside the collapse-set exclusion' % (site.sid, it['key']))
                continue
            blocked = False
            for kc in site.keep_clear:
                o, _, _ = W.frame(kc['road_m'])
                dx, dy = x - o[0], y - o[1]
                dd = math.hypot(dx, dy)
                ang = (math.degrees(math.atan2(dy, dx)) - kc['yaw_world'] + 540) % 360 - 180
                if kc['min_m'] < dd < kc['max_m'] and abs(ang) < kc['half_angle'] and size[2] > 0.6:
                    blocked = True
            if blocked:
                totals['rejected'].append('%s/%s: inside the boot-frame keep-clear cone' % (site.sid, it['key']))
                continue
            # overlap inside the site (solids only)
            # composed (V2) items: the composer owns the layout (shared walls overlap by design) and
            # the V2 checker validates it; nudging them apart is what made V1 read as evenly spaced toys
            soft = (it.get('stack') or it.get('attach') or cat in ('rubble', 'shrub', 'fx', 'fx_card', 'cloth', 'wood_post')
                    or it['key'] in GROUND_COVERS or it.get('composed'))
            if not soft:
                for _ in range(4):
                    corners = rect_corners(x, y, yaw, fx, fy)
                    worst, wc = 0.0, None
                    for other_c, other_xy, other_run in placed_rects:
                        if it.get('run_id') and other_run == it.get('run_id'):
                            continue    # pieces of one wall run butt into each other by design
                        o = sat_overlap(corners, other_c)
                        if o > worst:
                            worst, wc = o, other_xy
                    tol = max(0.15, 0.1 * min(fx, fy))
                    if worst <= tol:
                        break
                    away = np.array([x - wc[0], y - wc[1]])
                    n_ = np.linalg.norm(away)
                    away = away / n_ if n_ > 1e-3 else np.array([f[0], f[1]])
                    x += away[0] * (worst - tol + 0.05)
                    y += away[1] * (worst - tol + 0.05)
                    notes.append('nudged %.2f m out of an overlap' % (worst - tol + 0.05))
                corners = rect_corners(x, y, yaw, fx, fy)
                placed_rects.append((corners, (x, y), it.get('run_id')))
            if it.get('search_local_m'):
                # a big footprint: move it (not the site) to the least relief within the radius
                R_ = float(it['search_local_m'])
                best = None
                for du in np.linspace(-R_, R_, 9):
                    for dv in np.linspace(-R_, R_, 9):
                        cc = rect_corners(x + du, y + dv, yaw, fx, fy)
                        dd, _ = W.road_distance(perimeter(cc))
                        if dd < CLEAR_M + 2:
                            continue
                        zz = [W.ground(px, py) for px, py in cc] + [W.ground(x + du, y + dv)]
                        sc_ = max(zz) - min(zz) + 0.05 * math.hypot(du, dv)
                        if best is None or sc_ < best[0]:
                            best = (sc_, du, dv)
                if best and (best[1] or best[2]):
                    x, y = x + best[1], y + best[2]
                    corners = rect_corners(x, y, yaw, fx, fy)
                    notes.append('moved %.1f m to flatter ground' % math.hypot(best[1], best[2]))
            gz = W.ground(x, y)
            slope = W.slope_deg(x, y)
            cz = [W.ground(px, py) for px, py in corners]
            relief = max(cz) - min(cz)
            if cat in ('building', 'bpp') and (slope > 12 or relief > 1.5):
                totals['checks'].append('%s/%s: slope %.0f deg, relief %.1f m under the footprint' % (
                    site.sid, it['key'], slope, relief))
            max_dim = max(size)
            landmark = bool(it.get('landmark'))
            # stacked pieces must be single actors with a physics settle: an ISM instance is trace-settled
            # alone onto the ground, so a 5-stone cairn spread flat as pebbles (LANE_SD)
            ism = bool(it.get('ism', d['ism'])) and not it.get('stack')
            st = dict(mode=('physics' if it.get('stack') else d['settle']), sink_cm=d['sink'], max_tilt_deg=d['max_tilt'],
                      rand_tilt_deg=d['rand_tilt'], z_rule=d['z_rule'],
                      drop_cm=it.get('drop_cm', 0), z_offset_cm=it.get('z_offset_cm', 0))
            st.update(it.get('settle_over') or {})
            pl = dict(
                id='%s_%03d' % (site.sid, idx), key=it['key'], asset=e['path'], kind=e['kind'], cat=cat,
                x_cm=round(x * 100, 1), y_cm=round(y * 100, 1), ground_z_cm=round(gz * 100, 1),
                yaw=round(yaw % 360.0, 1), pitch=it.get('pitch', 0.0), roll=it.get('roll', 0.0),
                scale=sc, scale_range=[lo, hi],
                settle=st,
                group=it['group'], folder='Set/%s/%s' % (site.sid, it['group']),
                data_layer='DL_SetDress', ism=ism, stack=bool(it.get('stack')), attach=bool(it.get('attach')),
                run_id=it.get('run_id'),
                collision=it.get('collision', d['collide']), foliage_exclude=d['exclude'],
                draw_distance_cm=draw_distance_cm(max_dim, landmark), cast_shadow=True,
                size_m=[round(v_, 2) for v_ in size], slope_deg=round(slope, 1), relief_m=round(relief, 2),
                road_clear_m=round(dist, 2),
            )
            if e.get('batch01'):
                pl['requires_import'] = True
                pl['verdict'] = e['verdict']
                pl['imported'] = bool(e.get('imported'))
                if e.get('fallback'):
                    fk, fs = e['fallback']
                    pl['fallback'] = dict(asset=CATALOG[fk]['path'], scale=round(sc / e.get('placement_scale_mult', 1.0) * fs, 3))
            if it.get('id_prefix'):
                pl['id'] = '%s_%03d' % (it['id_prefix'], idx)
            for k in ('optional', 'story_owned_if_missing', 'skip_if_existing_within_m', 'verdict_check', 'search_local_m') + V2_KEYS:
                if it.get(k):
                    pl[k] = it[k]
            if it.get('note') or notes:
                pl['note'] = '; '.join([n for n in [it.get('note', '')] + notes if n])
            pls.append(pl)
            idx += 1
            pack = e['path'].split('/')[2]
            if e.get('batch01'):
                pack = 'Batch01 (SaskartaGaea)'
            totals['by_pack'][pack] = totals['by_pack'].get(pack, 0) + 1
            totals['by_cat'][cat] = totals['by_cat'].get(cat, 0) + 1
            totals['placements'] += 1
            if ism:
                totals['ism_instances'] += 1
        # ISM groups count as one actor each
        ism_groups = {(p['group'], p['asset']) for p in pls if p['ism']}
        actors = sum(1 for p in pls if not p['ism']) + len(ism_groups)
        totals['actors'] += actors
        views = offroad_views(W, site, cx, cy, site_z) if offroad else site_views(W, site, cx, cy, site_z)
        zone = zone_of(site.road_m)
        out_sites.append(dict(
            id=site.sid, name=site.name, kind=site.kind, order=site.order, road_m=site.road_m,
            side=(site.poi['side'] if offroad else ('right' if site.v > 1 else ('left' if site.v < -1 else 'on/both'))),
            lateral_m=(site.poi['distance_m'] if offroad else site.v),
            centre_cm=[round(cx * 100, 1), round(cy * 100, 1), round(site_z * 100, 1)],
            road_yaw=round(road_yaw, 1), radius_m=site.radius_m, zone=zone, storm=STORM[zone],
            role=site.role, story=site.story, decay=site.decay, style=site.style, layout=site.layout,
            notes=site.notes, story_owned=site.story_owned, verify_only=site.verify_only,
            layer=getattr(site, 'layer', 'road'), poi=getattr(site, 'poi', None) if offroad else None,
            load_box_cm=[round((cx - site.radius_m - 20) * 100), round((cy - site.radius_m - 20) * 100),
                         round((cx + site.radius_m + 20) * 100), round((cy + site.radius_m + 20) * 100)],
            counts=dict(placements=len(pls), actors=actors, ism_instances=sum(1 for p in pls if p['ism']),
                        physics=sum(1 for p in pls if p['settle']['mode'] == 'physics'),
                        batch01=sum(1 for p in pls if p.get('requires_import'))),
            views=views, placements=pls))
    out_sites.sort(key=lambda s_: (s_['order'], s_['road_m']))
    return out_sites, totals


def offroad_views(W, site, cx, cy, cz):
    """Off-road POI views: from the road where it reads best, from the nearest road point, 2 orbits, high 3/4."""
    top = site.poi['top_m']
    tgt = [round(cx * 100, 1), round(cy * 100, 1), round((cz + 0.6 * top) * 100, 1)]
    views = []

    def cam(name, x, y, z_above, look=tgt):
        views.append(dict(name=name, cam_cm=[round(x * 100, 1), round(y * 100, 1), round((W.ground(x, y) + z_above) * 100, 1)],
                          look_cm=look))
    run = site.poi.get('best_view_run') or [site.road_m, site.road_m]
    p, _, _ = W.frame((run[0] + run[1]) / 2.0)
    cam('road_best', p[0], p[1], EYE_M)
    p, _, _ = W.frame(site.road_m)
    cam('road_near', p[0], p[1], EYE_M)
    _, q = W.road_distance([(cx, cy)])
    base = math.atan2(q[1] - cy, q[0] - cx)
    orbit = site.radius_m + 25.0
    for k, da in (('orbit_a', -0.7), ('orbit_b', 0.7)):
        cam(k, cx + orbit * math.cos(base + da), cy + orbit * math.sin(base + da), 8.0)
    cam('high34', cx + (orbit + 60) * math.cos(base + 0.3), cy + (orbit + 60) * math.sin(base + 0.3), 70.0)
    return views


def site_views(W, site, cx, cy, cz):
    """Capture viewpoints: carrier eye on the road before the site, 30 m orbit (2), high 3/4, far 300 m."""
    tgt = [cx * 100, cy * 100, (cz + 2.0) * 100]
    views = []

    def cam(name, x, y, z_above):
        z = W.ground(x, y) + z_above
        views.append(dict(name=name, cam_cm=[round(x * 100, 1), round(y * 100, 1), round(z * 100, 1)],
                          look_cm=[round(t, 1) for t in tgt]))
    approach = max(0.0, site.road_m - (60.0 if site.radius_m < 50 else 120.0))
    p, _, _ = W.frame(approach)
    cam('carrier', p[0], p[1], EYE_M)
    _, q = W.road_distance([(cx, cy)])
    away = np.array([cx, cy]) - q
    n_ = np.linalg.norm(away)
    away = away / n_ if n_ > 1e-3 else W.frame(site.road_m)[2]
    base = math.atan2(away[1], away[0]) + math.pi     # from the road side
    orbit = max(30.0, site.radius_m * 0.8)
    for k, da in (('orbit_a', -0.6), ('orbit_b', 0.6)):
        a = base + da
        cam(k, cx + orbit * math.cos(a), cy + orbit * math.sin(a), 8.0)
    a = base + 0.3
    cam('high34', cx + (orbit + 50) * math.cos(a), cy + (orbit + 50) * math.sin(a), 60.0)
    far = max(0.0, site.road_m - 300.0)
    p, _, _ = W.frame(far)
    cam('far300', p[0], p[1], EYE_M)
    return views


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--md', action='store_true')
    args = ap.parse_args()
    W = World()
    out_sites, t = build(W)
    budget = dict(placements=t['placements'], actors=t['actors'], ism_instances=t['ism_instances'],
                  by_pack=t['by_pack'], by_cat=t['by_cat'])
    doc = dict(
        generated_by='Tools/World/build_setdress_sites.py', level='/Game/level/Saskarta_WP',
        conventions=dict(xy='world cm; yaw = UE yaw deg; ground_z_cm = heightmap height at the bounds centre (the editor settle replaces it)',
                         bounds='x_cm/y_cm is where the mesh BOUNDS CENTRE goes (the tool corrects for pivots)',
                         settle='trace = 4-corner footprint traces, plane fit, clamp to max_tilt, z by z_rule, minus sink; physics = emulated drop (random tilt candidates, lowest stable pose); none = as planned',
                         road_core='every footprint >= %.1f m from the road centreline' % CLEAR_M),
        budget=budget, rejected=t['rejected'], checks=t['checks'], sites=out_sites)
    with open(OUT, 'w', encoding='utf8') as fh:
        json.dump(doc, fh, indent=1, ensure_ascii=False)
    print('%-26s %6s %4s %-7s %5s %5s %4s %4s' % ('site', 'road_m', 'ord', 'side', 'place', 'actor', 'ism', 'phys'))
    for s_ in out_sites:
        c = s_['counts']
        print('%-26s %6d %4d %-7s %5d %5d %4d %4d' % (s_['id'], s_['road_m'], s_['order'], s_['side'], c['placements'],
                                                     c['actors'], c['ism_instances'], c['physics']))
    print('TOTAL placements %d, actors %d, ISM instances %d' % (t['placements'], t['actors'], t['ism_instances']))
    print('by pack', json.dumps(t['by_pack']))
    print('rejected', len(t['rejected']), 'checks', len(t['checks']))
    for c in t['checks'][:40]:
        print('  CHECK', c)
    for c in t['rejected'][:40]:
        print('  REJECTED', c)
    if args.md:
        print()
        print('| Site | Road m | Side | World XY (m) | Placements | Actors | ISM | Physics | Batch01 |')
        print('|---|---:|---|---|---:|---:|---:|---:|---:|')
        for s_ in out_sites:
            c = s_['counts']
            print('| %s | %d | %s | %.0f, %.0f | %d | %d | %d | %d | %d |' % (
                s_['id'], s_['road_m'], s_['side'], s_['centre_cm'][0] / 100, s_['centre_cm'][1] / 100,
                c['placements'], c['actors'], c['ism_instances'], c['physics'], c['batch01']))
    print('wrote', OUT)


if __name__ == '__main__':
    main()
