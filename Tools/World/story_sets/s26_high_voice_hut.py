"""S26 the High Voice relay hut, interior: the story set as data, composed with the set-dressing V2 method.

    python Tools/World/story_sets/s26_high_voice_hut.py              # write S26.json + docs/world/story_sets/S26.png, print the checks
    python Tools/World/story_sets/s26_high_voice_hut.py --check      # checks only; exit 1 on a failed check
    python Tools/World/story_sets/s26_high_voice_hut.py editor <step> [place_setdress args]
          # runs Tools/World/place_setdress.py <step> S26_HighVoiceHut --v2 against Tools/World/story_sets/S26.json
    python Tools/World/story_sets/s26_high_voice_hut.py materials variants
          # runs Tools/World/build_setdress_materials.py variants S26_HighVoiceHut against S26.json

The shell is V10's (Tools/World/story_sets/V10.json, v10_high_voice.py): ONE room of AshesOfBazaar stone on the
flat shelf 9 m right of the road's end, its arched door (AB_Side_Arch_small) turned back up the road, the plate
OUTSIDE on the door's left jamb, a closed shutter on the valley wall, a flagstone roof. The hut stands on V10's
plinth (one B01_floor01 slab): the plinth top is the floor and the door sill. V10 publishes `interior_frame`
(the hut frame, the inner faces, the door opening, the floor actor and its predicted top); this script reads it
on every run, so the room follows the hut. If V10.json is missing, S26 waits: nothing is written.

Story (docs/story/storyline.md section 2, story-events.json B15/B23/B24, CINEMATICS.md CIN_23/CIN_24): nobody
answered the Keeper's call to the relay (B15), so the hut is kept, in order, empty and cold (decay 0). The Keeper
arrives on foot, speaks the last entry at 19.5 m from point 0 (B23), lays a hand on the palm-in-a-ring mark on the
plate beside the door (B24) and the mast transmits; CV_TRANSMIT_01 comes quietly from the hut speaker over the door.

The room (2.45 x 2.74 m), read through the door from the walk:
- straight through the doorway, against the back wall: the operator's desk, the relay set on it under its dust
  cloth, the cold brass lantern at its end; in front of it the chair, pulled back and turned, as if someone stood
  up and did not come back. This is what the prompt "Lay your hand on the mark" is looked at through.
- along the valley wall (under the shuttered window): the bench where a second person sat and listened, the tea
  pot left on its end; the lamp-oil jar in the corner behind the plate.
- by the door, right: the water jar and its jug. Back right: the record boxes, one on the other.
Ground integration inside: grit blown in over the threshold, dust worn in front of the desk.

Offline only: nothing here talks to Unreal. The `editor` sub-command runs place_setdress.py with the V2 site file
swapped for S26.json (place_setdress.py itself is not edited). It adds one rule for this interior: an item with
`support: own` settles only on the landscape, on this site's own actors, or on V10's plinth (site.support_labels),
so it can never land on V10's roof or on a wall top.
"""
import argparse
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
WORLD = os.path.dirname(HERE)
ROOT = os.path.dirname(os.path.dirname(WORLD))
sys.path.insert(0, os.path.join(ROOT, 'Tools', 'Story'))
sys.path.insert(0, WORLD)
import build_road_profile as brp  # noqa: E402  (read-only use: the heightmap and the road polyline)
import setdress_catalog  # noqa: E402  (read-only use: asset paths and sizes)

OUT_JSON = os.path.join(HERE, 'S26.json')
OUT_PNG = os.path.join(ROOT, 'docs', 'world', 'story_sets', 'S26.png')
V10_JSON = os.path.join(HERE, 'V10.json')
SID = 'S26_HighVoiceHut'   # the road site id of the V1 plan (SETDRESS_PLAN.md); actors carry SD_S26_HighVoiceHut
SET = 'S26'
MAST_CM = (298079.6, 483050.0)       # point 0; the L2 beacon actor HighVoice stands here (task-L2-report.md)
MAST_RADIUS_M = 0.45                 # the 0.5 x 1 m Tile_10MPillar as a sight occluder
B23_UE_M = 19.5                      # B23_LAST_ENTRY ue_distance_from_p0_m (the prompt fires here)
BOOM_M, WALK_EYE_M, KEEPER_EYE_M = 3.5, 1.9, 1.55   # the traveller's third-person boom (CINEMATICS.md section 6)
WALL_GAP = 0.04                      # furniture stands 4 cm off the inner wall faces
DECAL_DEPTH_M = 0.10                 # +-5 cm: floor decals never climb the furniture (verifier, 2026-09-28)
CAT = setdress_catalog.load()

# settle presets (SETDRESS_V2.md section 3; place_setdress.py settle config). No material_set: the stone ground
# blend samples the landscape RVT, and under the plinth that is the wrong ground (verifier, 2026-09-28).
S_REST = dict(mode='physics', sink_cm=1, max_tilt_deg=3, rand_tilt_deg=1, z_rule='max', drop_cm=0, z_offset_cm=0)


def stacked(drop_cm):
    return dict(mode='physics', sink_cm=0, max_tilt_deg=4, rand_tilt_deg=2, z_rule='max', drop_cm=drop_cm, z_offset_cm=0)


# ------------------------------------------------------------------------------------ the hut frame (from V10)

class Hut:
    """Hut frame, metres (V10 interior_frame): x from the front (door) wall to the back wall, y to the right of x,
    origin at the footprint centre. y < 0 is the valley wall (the plate is outside it at the front), y > 0 the far
    wall. The door is centred on y = 0 in the front."""

    def __init__(self, v10):
        self.T = brp.Terrain(brp.HEIGHTMAP)
        self.R = brp.Road(brp.SPLINE_POINTS_CM)
        self.L = self.R.length
        self.v10 = v10
        fr = v10['interior_frame']
        self.fr = fr
        self.o = np.array(fr['hut_centre_cm'], float)
        self.yaw = float(fr['hut_x_yaw_world'])
        self.f = self._dir(self.yaw)
        self.r = self._dir(self.yaw + 90.0)
        im = fr['inner_m']
        self.x0, self.x1, self.half_y = im['front'], im['back'], im['side']
        self.arch_outer, self.arch_inner = fr['arch_m']['outer'], fr['arch_m']['inner']
        d = fr['door_opening_m']
        self.door_w, self.door_h, self.door_y, self.door_measured = d['w'], d['h'], d.get('centre_y', 0.0), d['measured']
        self.plate_y = fr['plate']['local_y']
        self.window_x = fr['window']['local_x']
        self.floor = fr['floor']
        self.floor_top_cm = fr['floor']['top_cm_predicted']
        self.roof_bottom_cm = fr['roof_bottom_cm_predicted']
        self.grade_cm = max(fr['grade_z_cm'])
        site = v10['sites'][0]
        self.site = site
        self.recs = site['placements']
        self.walls = [p for p in self.recs if p['group'] == 'hut']
        self.hooks = v10['story_hooks']

    @staticmethod
    def _dir(yaw):
        return np.array([math.cos(math.radians(yaw)), math.sin(math.radians(yaw))])

    def g(self, x_cm, y_cm):
        return float(self.T.height(x_cm, y_cm)) * 100.0

    def hw(self, x, y):
        p = self.o + (self.f * x + self.r * y) * 100.0
        return float(p[0]), float(p[1])

    def hl(self, X, Y):
        d = (np.array([X, Y], float) - self.o) / 100.0
        return float(d @ self.f), float(d @ self.r)

    def road(self, s_m):
        k, _ = self.R.locate(s_m)
        d = self.R.P[k + 1, :2] - self.R.P[k, :2]
        d = d / np.linalg.norm(d)
        return self.R.xy(s_m), d, np.array([-d[1], d[0]])

    @staticmethod
    def footprint_world(rec):
        """The plan corners (world cm) of a V10 placement's scaled mesh box (size_m is already scaled)."""
        sx, sy = rec['size_m'][0] * 100.0, rec['size_m'][1] * 100.0
        c, sn = math.cos(math.radians(rec['yaw'])), math.sin(math.radians(rec['yaw']))
        return [(rec['x_cm'] + a * sx / 2 * c - b * sy / 2 * sn, rec['y_cm'] + a * sx / 2 * sn + b * sy / 2 * c)
                for a, b in ((-1, -1), (1, -1), (1, 1), (-1, 1))]

    @staticmethod
    def top_cm(rec):
        if rec.get('predicted'):
            return rec['predicted']['top_cm']
        return rec['ground_z_cm'] + rec['size_m'][2] * 100.0

    def plinth_rec(self):
        return [p for p in self.recs if p['id'] == self.floor['id']][0]


def size_m(key, scale):
    return [round(v * scale / 100.0, 3) for v in CAT[key]['size_cm']]


def footprint_local(x, y, a_deg, sx, sy):
    c, s = math.cos(math.radians(a_deg)), math.sin(math.radians(a_deg))
    return [(x + px * c - py * s, y + px * s + py * c) for px, py in ((-sx / 2, -sy / 2), (sx / 2, -sy / 2), (sx / 2, sy / 2), (-sx / 2, sy / 2))]


def sat_overlap(A, B):
    """Separating-axis test for two convex quads in the plane; the overlap depth (m) or 0."""
    best = 1e9
    for poly in (A, B):
        for i in range(4):
            p, q = poly[i], poly[(i + 1) % 4]
            n = (-(q[1] - p[1]), q[0] - p[0])
            L = math.hypot(*n)
            n = (n[0] / L, n[1] / L)
            pa = [v[0] * n[0] + v[1] * n[1] for v in A]
            pb = [v[0] * n[0] + v[1] * n[1] for v in B]
            o = min(max(pa), max(pb)) - max(min(pa), min(pb))
            if o <= 0:
                return 0.0
            best = min(best, o)
    return best


def seg_dist(p, a, b):
    p, a, b = np.array(p, float), np.array(a, float), np.array(b, float)
    t = np.clip(np.dot(p - a, b - a) / max(1e-9, np.dot(b - a, b - a)), 0, 1)
    return float(np.linalg.norm(a + (b - a) * t - p))


def pt_in_poly(p, poly):
    x, y = p
    inside = False
    for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1]):
        if (y0 > y) != (y1 > y) and x < x0 + (x1 - x0) * (y - y0) / (y1 - y0):
            inside = not inside
    return inside


# ------------------------------------------------------------------------------------ the composition

def compose(H):
    """The placements in the hut frame, with their support chain (on: floor | desk | bench | box)."""
    X0, X1, Y = H.x0, H.x1, H.half_y            # inner faces: front (the arch's inner face), back, sides
    items = []

    def add(key, x, y, a, scale, group, role, **kw):
        it = dict(key=key, x=x, y=y, a=a, scale=scale, group=group, role=role)
        it.update(kw)
        items.append(it)
        return it

    # -- the relay desk, square in the doorway against the back wall (seen through the door from the walk)
    dk = size_m('AB_WoodenTable_B', 1.0)
    desk_x = X1 - WALL_GAP - dk[1] / 2
    add('AB_WoodenTable_B', desk_x, 0.0, 90.0, 1.0, 'relay',
        'the operator\'s desk against the back wall, square in the doorway (the walk sees it through the door)',
        contact='rest', settle=S_REST, on='floor')
    add('AB_Table_Cloth', desk_x, -0.15, 87.0, 1.0, 'relay',
        'the relay set under its dust cloth on the desk: the covered shape reads as equipment, the brass conduit from '
        'the plate outside comes in behind it', contact='rest', settle=stacked(45), on='desk', stack=True)
    add('PH_lantern', desk_x + 0.12, 0.40, 30.0, 1.0, 'relay',
        'the cold brass lantern at the desk\'s end (unlit: the zone rule)', contact='rest', settle=stacked(40), on='desk',
        stack=True)
    ch = size_m('AB_Chair_A_low', 1.0)
    add('AB_Chair_A_low', desk_x - dk[1] / 2 - 0.30 - ch[0] / 2, 0.30, 180.0 + 25.0, 1.0, 'relay',
        'the chair pulled back 30 cm from the desk and turned: someone stood up and did not come back', contact='rest',
        settle=S_REST, on='floor', facing_verify='the seat must open toward the desk (hut +x) turned 25 deg; if the '
        'orbit_a / contact capture shows its back to the desk, change its "a" by 180 in compose() and `editor replace` it')
    # -- the valley wall: the bench under the shuttered window, the tea pot left on it, the oil jar behind the plate
    bn = size_m('MV_bench_03', 1.0)
    bench_y = -Y + WALL_GAP + bn[1] / 2
    add('MV_bench_03', H.window_x - 0.25, bench_y, 0.0, 1.0, 'relay',
        'the bench along the valley wall under the shuttered window, facing the desk: a second person sat here and listened',
        contact='rest', settle=S_REST, on='floor')
    add('PH_pot', H.window_x - 0.25 + bn[0] / 2 - 0.22, bench_y, 0.0, 1.0, 'relay',
        'the enamel tea pot left on the bench end ("we\'ll have tea while we wait")', contact='rest', settle=stacked(25),
        on='bench', stack=True)
    pot = size_m('AB_Clay_Pot_B', 1.0)
    add('AB_Clay_Pot_B', X0 + WALL_GAP + pot[0] / 2, -Y + WALL_GAP + pot[1] / 2, 0.0, 1.0, 'stores',
        'the lamp-oil jar in the front corner, behind the plate (the biofuel the lantern burned)', contact='rest',
        settle=S_REST, on='floor')
    # -- the far wall: the water jar and jug by the door, the record boxes in the back corner
    jar = size_m('B01_tank01', 0.62)
    add('B01_tank01', X0 + WALL_GAP + jar[0] / 2, Y - WALL_GAP - jar[1] / 2, 180.0, 0.62, 'stores',
        'the water jar in the corner by the door (wood-hooped clay)', contact='rest', settle=S_REST, on='floor')
    cf = size_m('MV_carafe_01', 0.5)
    add('MV_carafe_01', X0 + WALL_GAP + jar[0] + 0.06 + cf[0] / 2, Y - WALL_GAP - cf[1] / 2 - 0.02, 0.0, 0.5, 'stores',
        'the jug for drawing water', contact='rest', settle=S_REST, on='floor')
    bx = size_m('MV_box_03', 1.0)
    add('MV_box_03', X1 - WALL_GAP - bx[0] / 2, Y - WALL_GAP - bx[1] / 2, 0.0, 1.0, 'stores', 'record box (the relay logbooks)',
        contact='rest', settle=S_REST, on='floor')
    add('MV_box_03', X1 - WALL_GAP - bx[0] / 2 - 0.01, Y - WALL_GAP - bx[1] / 2 - 0.01, -9.0, 0.8, 'stores',
        'the second record box, on the first', contact='rest', settle=stacked(45), on='box', stack=True)
    return items, dict(desk_x=round(desk_x, 3), bench_y=round(bench_y, 3), plate_y=H.plate_y)


SUPPORTS = {'desk': 'AB_WoodenTable_B', 'bench': 'MV_bench_03', 'box': 'MV_box_03'}


def predict(H, items):
    """Offline rest heights: each floor item on the plinth top; stacked items on their support's top."""
    tops = {}
    for it in items:
        sz = size_m(it['key'], it['scale'])
        it['size_m'] = sz
        it['corners'] = footprint_local(it['x'], it['y'], it['a'], sz[0], sz[1])
        if it['on'] == 'floor':
            it['bottom_cm'] = H.floor_top_cm - it['settle']['sink_cm']
        else:
            it['bottom_cm'] = tops[it['on']] - it['settle']['sink_cm']
        it['top_cm'] = it['bottom_cm'] + sz[2] * 100.0
        for k, key in SUPPORTS.items():
            if it['key'] == key and it['on'] == 'floor':
                tops[k] = it['top_cm']


def exterior_occluders(H):
    """V10's exterior solids that could stand between a camera outside and the door: plan box + top (cm)."""
    out = []
    for r in H.recs:
        if r.get('ism') or r['group'] in ('hut', 'hut_roof', 'hut_floor') or r.get('contact') not in ('rigid', 'lie', 'rest', 'bear'):
            continue
        out.append(([H.hl(*c) for c in H.footprint_world(r)], H.top_cm(r), r['key']))
    return out


def door_visibility(H, items, eye_cm, occ):
    """Share of each item (9 plan samples x 2 heights) seen through the doorway from one eye: the ray must pass the
    arch piece inside the opening (both its faces), clear the mast and V10's exterior solids. Lighting is NOT
    modelled: the room is lit through the door only (capture check)."""
    ex, ey = H.hl(eye_cm[0], eye_cm[1])
    ez = eye_cm[2]
    mast_l = H.hl(*MAST_CM)
    ft = H.floor_top_cm
    res = {}
    for it in items:
        c = it['corners']
        pts = [((c[0][0] + c[2][0]) / 2, (c[0][1] + c[2][1]) / 2)] + list(c) + \
              [((c[i][0] + c[(i + 1) % 4][0]) / 2, (c[i][1] + c[(i + 1) % 4][1]) / 2) for i in range(4)]
        seen = n = 0
        for (px, py) in pts:
            for pz in (it['bottom_cm'] + (it['top_cm'] - it['bottom_cm']) * 0.5, it['top_cm'] - 1.0):
                n += 1
                ok = True
                for wx in (H.arch_outer, H.arch_inner):
                    t = (wx - ex) / (px - ex) if abs(px - ex) > 1e-6 else -1
                    if not (0 < t < 1):
                        ok = False
                        break
                    yy = ey + (py - ey) * t
                    zz = ez + (pz - ez) * t
                    if abs(yy - H.door_y) > H.door_w / 2 - 0.03 or zz > ft + H.door_h * 100 or zz < ft:
                        ok = False
                        break
                if ok and seg_dist(mast_l, (ex, ey), (px, py)) < MAST_RADIUS_M:
                    ok = False
                if ok:
                    for poly, top, _ in occ:
                        for k in range(1, 30):
                            t = k / 30.0
                            q = (ex + (px - ex) * t, ey + (py - ey) * t)
                            if pt_in_poly(q, poly) and ez + (pz - ez) * t < top:
                                ok = False
                                break
                        if not ok:
                            break
                seen += ok
        res[it['id']] = round(seen / n, 2)
    return res


# ------------------------------------------------------------------------------------ decals (interior)

def decals(H, items):
    out = []

    def rec(surface, x, y, a, length, width, strength, sort, where):
        X, Y = H.hw(x, y)
        out.append(dict(id='%s_g%03d' % (SID, len(out)), surface=surface, shape='ellipse', x_cm=round(X, 1), y_cm=round(Y, 1),
                        z_cm=round(H.floor_top_cm, 1), yaw=round((H.yaw + a) % 360, 1), length_m=round(length, 2),
                        width_m=round(width, 2), depth_m=DECAL_DEPTH_M, strength=round(strength, 2), sort=sort, where=where,
                        local=dict(x=round(x, 2), y=round(y, 2))))
    rec('rubble_dust', H.x0 + 0.40, H.door_y, 0.0, 0.9, 0.85, 0.55, 2, 'grit blown in over the threshold')
    desk = [it for it in items if it['key'] == 'AB_WoodenTable_B'][0]
    rec('rubble_dust', desk['x'] - 0.95, -0.35, 0.0, 0.9, 0.7, 0.3, 2, 'dust worn in the floor between the door and the desk')
    return out


# ------------------------------------------------------------------------------------ checks

def checks(H, items, ground, vis, views, occ):
    notes, bad = [], []

    def need(cond, msg):
        (notes if cond else bad).append(('ok   ' if cond else 'FAIL ') + msg)

    X0, X1, Y = H.x0, H.x1, H.half_y
    for it in items:
        xs = [c[0] for c in it['corners']]
        ys = [c[1] for c in it['corners']]
        need(min(xs) >= X0 + 0.02 and max(xs) <= X1 - 0.02 and min(ys) >= -Y + 0.02 and max(ys) <= Y - 0.02,
             '%s inside the inner walls, 2 cm to spare (x %.2f..%.2f, y %.2f..%.2f)' % (it['id'], min(xs), max(xs), min(ys), max(ys)))
    pl = H.plinth_rec()
    pl_poly = [H.hl(*c) for c in H.footprint_world(pl)]
    for it in items:
        need(all(pt_in_poly(c, pl_poly) for c in it['corners']), '%s stands wholly on the plinth (%s)' % (it['id'], pl['id']))
    floor_items = [it for it in items if it['on'] == 'floor']
    for i in range(len(floor_items)):
        for j in range(i + 1, len(floor_items)):
            a, b = floor_items[i], floor_items[j]
            d = sat_overlap(a['corners'], b['corners'])
            need(d == 0.0, '%s and %s do not overlap in plan (%.2f m)' % (a['id'], b['id'], d))
    for it in items:
        if it['on'] in SUPPORTS:
            base = [x for x in items if x['key'] == SUPPORTS[it['on']] and x['on'] == 'floor'][0]
            cx = sum(c[0] for c in it['corners']) / 4
            cy = sum(c[1] for c in it['corners']) / 4
            bx = [c[0] for c in base['corners']]
            by = [c[1] for c in base['corners']]
            need(min(bx) + 0.03 < cx < max(bx) - 0.03 and min(by) + 0.03 < cy < max(by) - 0.03,
                 '%s: its centre is over its support (%s), so the drop lands on it' % (it['id'], base['id']))
            inside = all(min(bx) - 0.01 <= c[0] <= max(bx) + 0.01 and min(by) - 0.01 <= c[1] <= max(by) + 0.01 for c in it['corners'])
            need(inside, '%s: its whole footprint is on %s' % (it['id'], base['id']))
    stacked_on = {}
    for it in items:
        if it['on'] != 'floor':
            stacked_on.setdefault(it['on'], []).append(it)
    for grp in stacked_on.values():
        for i in range(len(grp)):
            for j in range(i + 1, len(grp)):
                need(sat_overlap(grp[i]['corners'], grp[j]['corners']) == 0.0, '%s and %s side by side' % (grp[i]['id'], grp[j]['id']))
    # the threshold stays clear (the door, the grit, the view in); the chair stands beyond it
    lane = [(X0, H.door_y - H.door_w / 2 - 0.05), (X0 + 0.45, H.door_y - H.door_w / 2 - 0.05),
            (X0 + 0.45, H.door_y + H.door_w / 2 + 0.05), (X0, H.door_y + H.door_w / 2 + 0.05)]
    for it in items:
        need(sat_overlap(lane, it['corners']) == 0.0, '%s keeps out of the threshold (0.45 m in from the arch)' % it['id'])
    # the chair is pulled back from the desk (a gap you can see), not tucked in
    desk = [it for it in items if it['key'] == 'AB_WoodenTable_B'][0]
    chair = [it for it in items if it['key'] == 'AB_Chair_A_low'][0]
    gap = min(c[0] for c in desk['corners']) - max(c[0] for c in chair['corners'])
    need(gap >= 0.12, 'the chair stands %.2f m back from the desk (pulled back, >= 0.12 m)' % gap)
    # headroom under V10's roof, the floor at the sill
    for it in items:
        need(it['top_cm'] <= H.roof_bottom_cm - 40.0, '%s top %.0f cm stays 40 cm under the roof (%.0f)' % (
            it['id'], it['top_cm'], H.roof_bottom_cm))
    need(abs(H.floor_top_cm - H.grade_cm) <= 15.0, 'the floor (V10 plinth top, predicted %.1f) is at the door grade (%.1f): '
         'no step down into the room' % (H.floor_top_cm, H.grade_cm))
    # the story reads: the covered set on the desk through the door from the B23 prompt or from 3 m out
    ids = {k: [i['id'] for i in items if i['key'] == k][0] for k in ('AB_WoodenTable_B', 'AB_Table_Cloth', 'AB_Chair_A_low')}
    setread = max(vis['b23'][ids['AB_Table_Cloth']], vis['b23'][ids['AB_WoodenTable_B']])
    need(setread >= 0.25 or vis['door3'][ids['AB_Table_Cloth']] >= 0.5,
         'the desk and the covered set read through the doorway (B23 desk %.0f %% / cloth %.0f %%, 3 m out cloth %.0f %%)'
         % (100 * vis['b23'][ids['AB_WoodenTable_B']], 100 * vis['b23'][ids['AB_Table_Cloth']], 100 * vis['door3'][ids['AB_Table_Cloth']]))
    need(vis['door3'][ids['AB_Chair_A_low']] >= 0.3, 'the pulled-back chair reads from 3 m out (%.0f %%)' % (100 * vis['door3'][ids['AB_Chair_A_low']]))
    pl_hook = H.hl(*H.hooks['Plate']['centre_cm'][:2])
    for it in items:
        ds = seg_dist((it['x'], it['y']), H.hl(*H.hooks['OTS_cam_cm'][:2]), pl_hook)
        need(ds > 0.3, '%s is not in the CIN24 S1 line (it is indoors, %.2f m from it)' % (it['id'], ds))
    # nothing of S26 in the held seated shot (CIN24 S5): the frame looks east, the hut is behind it
    sp = H.hooks['SeatPoint']
    sl = H.hl(*sp['cm'][:2])
    look = math.radians(sp['yaw'] - H.yaw)
    for it in items:
        d = (it['x'] - sl[0], it['y'] - sl[1])
        fwd = d[0] * math.cos(look) + d[1] * math.sin(look)
        need(fwd < 0, '%s is behind the SeatedCam (CIN24 S5 looks away from the hut)' % it['id'])
    # S26 runs inside V10's load: every view (but far300, which forces no tiles) in V10's load box
    box = H.site['load_box_cm']
    inside = [v['name'] for v in views if v['name'] != 'far300' and box[0] <= v['cam_cm'][0] <= box[2] and box[1] <= v['cam_cm'][1] <= box[3]]
    need(len(inside) == len([v for v in views if v['name'] != 'far300']),
         'every S26 capture view is inside V10\'s load box, so S26 runs inside V10\'s load (no load/unload of its own)')
    return notes, bad


# ------------------------------------------------------------------------------------ views

def make_views(H, items):
    ft = H.floor_top_cm
    views = []

    def v(name, cam, look, why):
        views.append(dict(name=name, cam_cm=[round(float(c), 1) for c in cam], look_cm=[round(float(c), 1) for c in look], why=why))
    desk = [it for it in items if it['key'] == 'AB_WoodenTable_B'][0]
    dx, dy = H.hw(desk['x'], desk['y'])
    door_look = (dx, dy, ft + 70.0)
    for name, ue in (('carrier_a', 40.0), ('carrier_b', B23_UE_M)):
        p, f, r = H.road(H.L - ue)
        cam = np.array(p) - f * BOOM_M * 100.0 + r * 40.0
        v(name, (cam[0], cam[1], H.g(cam[0], cam[1]) + WALK_EYE_M * 100.0), door_look,
          'the walk camera %.1f m from point 0 (%s), looking at the hut door' % (ue, 'the B23 prompt' if ue == B23_UE_M else 'approach'))
    cx, cy = H.hw(H.arch_outer - 3.0, H.door_y + 0.3)
    v('carrier_c', (cx, cy, H.g(cx, cy) + KEEPER_EYE_M * 100.0), door_look, '3 m out from the door, eye height: the read through the doorway')
    ox, oy = H.hw(H.x0 + 0.35, -0.55)
    v('orbit_a', (ox, oy, ft + 150.0), (dx, dy, ft + 60.0), 'inside, just past the threshold: the desk, the covered set, the chair pulled back')
    ox, oy = H.hw(H.x1 - 0.35, -H.half_y + 0.40)
    jx, jy = H.hw(H.x0 + 0.3, H.half_y - 0.3)
    v('orbit_b', (ox, oy, ft + 145.0), (jx, jy, ft + 50.0), 'reverse, from the back corner by the bench: across the room to the door, the jar and the jug')
    v('orbit_c', H.hooks['OTS_cam_cm'], H.hooks['Plate']['centre_cm'], 'CIN24 S1 over-the-shoulder at the plate (V10 story hook; 50 mm in the sequence)')
    chr_ = [it for it in items if it['key'] == 'AB_Chair_A_low'][0]
    cx, cy = H.hw(chr_['x'] - 0.3, chr_['y'] - 0.9)
    lx, ly = H.hw(chr_['x'] + 0.3, chr_['y'])
    v('contact', (cx, cy, ft + 35.0), (lx, ly, ft + 5.0), 'low close-up: the chair and the desk feet on the plinth')
    hx2, hy2 = H.hw(-7.0, -6.0)
    v('high34', (hx2, hy2, H.g(hx2, hy2) + 9.0 * 100.0), H.hw(0.0, 0.0) + (ft + 100.0,), '3/4 from above: the hut, the door, the mast foot')
    p, f, r = H.road(H.L - 219.0)
    v('far300', (p[0], p[1], H.g(p[0], p[1]) + 122.0), H.hw(0.0, 0.0) + (ft + 150.0,), 'the collapse point (4,790 m): the hut, 219 m away')
    sp = H.hooks['SeatPoint']
    look = (sp['cm'][0] + 1000.0 * math.cos(math.radians(sp['yaw'])), sp['cm'][1] + 1000.0 * math.sin(math.radians(sp['yaw'])),
            sp['cm'][2] - 1000.0 * math.tan(math.radians(-sp['pitch'])))
    v('seat', sp['cm'], look, 'CIN24 S5 held shot: nothing of S26 may show (the hut is behind it)')
    return views


# ------------------------------------------------------------------------------------ records and output

STORY = dict(
    beats=[
        dict(id='B15_HIGH_VOICE_IN_RANGE', road_m=4520, why='the hut is empty: the Keeper called the relay late at night ("Is anyone at the relay? ... Do you still keep the old names up there? ... Please answer.") and only static came back'),
        dict(id='B18_COLLAPSE', road_m=4790, ue_from_p0_m=219, why='the carrier falls 219 m short; CIN_18 shot 3 frames the crown behind it (far300 view)'),
        dict(id='B23_LAST_ENTRY', road_m=4990, ue_from_p0_m=19.5, world_cm=[298219, 481257, 11191], trigger='pass:human',
             lines=['RADIO_B23_01 (Keeper, live and unfiltered: the mountain\'s old name, then "This belongs to you too, if one day you choose to come back to it.")'],
             prompt='Lay your hand on the mark.',
             optional_cinematic='CIN_23_THE_MARK (tag MarkCine, 12 s): 24 mm low wide of the Keeper by the hut tilting up the mast; 100 mm insert on the plate; hand-back',
             why='the prompt is not proximity-gated: most players see the hut from about 20 m and press'),
        dict(id='B24_TRANSMISSION', road_m=4990, trigger='prompt:poll_key', cinematic='CIN_24_TRANSMISSION (48 s)',
             lines=['CV_TRANSMIT_01 "Âlaawb. Transmitting." (quiet, from the hut speaker, spatial)', 'CHORUS_B24 (six archive lines)',
                    'CV_TRANSMIT_02 "Transmission complete."'],
             shots=['S1 0-4 s: over the right shoulder at the hut plate, 50 mm f/2.8, 0.4 m push: the hand on the palm-in-a-ring mark',
                    'S2 4-14 s: TransmitCam at the mast foot looking straight up, 18 mm', 'S3 14-24 s: extreme wide from ~1.5 km, 200 mm',
                    'S4 24-32 s: black, TRANSMISSION COMPLETE, hiss',
                    'S5 32-44 s: SeatedCam at the mast foot ~100 cm up, 24 mm, east over the valley, walking aid in the lower frame (12 s held)',
                    'S6 44-48 s: black, silence']),
    ],
    audio='CV_TRANSMIT_01 plays from V10\'s HutSpeaker hook (above the door); the relay set it speaks for is the covered shape on the desk',
    geiger_cps=8, look='Above: clear, calm, gold light; bare wind-scoured rock; the fewest objects on the road',
    rules='kept (decay 0), nothing religious (the High Voice is a radio relay), nothing modern; bazaar stone first; lanterns unlit',
)

EXISTS = [
    '/Game/SaskartaGaea/Story/HighVoice/BP_Saskarta_HighVoice (ending logic: MastBase, StandPoint, SeatPoint, Plate, Crown, Column; '
    'SnapKeeperToPlate, StartGlowAndColumn; compiled in commit 017afa0b); NOT placed yet (task ENDING 6c). V10\'s `hooks` step '
    'sets its Plate on the hut jamb',
    '/Game/SaskartaGaea/Story/BP_Saskarta_BP_HighVoice (the L2 beacon: 4 x Tile_10MPillar 40 m mast, 8 m crown, 400 m beam) placed as '
    'actor HighVoice at (298079.6, 483050, 10818.7), not spatially loaded',
    'The V10 hut exists as data only (Tools/World/story_sets/V10.json, not placed): the plinth (the floor), the walls, the door '
    'arch, the roof slab, the shutter, the plate/StandPoint/speaker hooks and the interior_frame S26 is laid out against',
    'V1 set dressing for S26 (6 props) planned but NOT placed (task-SETDRESS-report.md: "the V10 hut does not exist")',
]

MISSING = [
    dict(asset='the relay set itself: T2_radio_desk', stand_in='AB_Table_Cloth over AB_WoodenTable_B (the covered shape)',
         status='GENERATED, not imported: SourceArt/Tripo/radio_desk (manifest: 128 x 200 x 182 cm at import scale 2.043). '
                'Tools/Tripo/IMPORT.md imports it to /Game/SaskartaGaea/Environment/Tripo02/SM_T2_radio_desk. At 2.0 x 1.3 m it '
                'does not fit this 2.45 x 2.74 m room as sized: re-import at a 1.2 m width (scale ~1.2) or it needs its own layout pass',
         tripo_prompt=None),
    dict(asset='a small iron stove with a flue pipe through the roof (the kept hut is cold, but a stove says someone lived here)',
         stand_in='none (V10 models no chimney)', status='not generated',
         tripo_prompt='small cast-iron pot-belly stove with a riveted flue pipe and a brass door handle, cold, steampunk, 90 cm'),
    dict(asset='a brass horn loudspeaker for CV_TRANSMIT_01 (V10 lists it too; the HutSpeaker hook is above the door)',
         stand_in='none', status='not generated',
         tripo_prompt='weathered brass gramophone-horn loudspeaker on a riveted iron wall bracket, steampunk radio relay, 60 cm'),
    dict(asset='logbooks, loose papers and a pen on the desk', stand_in='the closed record boxes', status='not generated',
         tripo_prompt='stack of three leather-bound logbooks with brass corners and a dip pen, worn, 30 cm'),
    dict(asset='a blanket draped over the chair back (the V1 plan)', stand_in='none: the pack cloths are flat sheets the emulated physics cannot drape',
         status='not generated', tripo_prompt='coarse wool blanket draped over the back of a low wooden chair, folded, earth tones, 80 cm'),
    dict(asset='light in the room', stand_in='none: V10\'s valley window is a closed shutter, so the room is lit through the door only',
         status='capture check: if the room reads black, open the V10 shutter (AB_Window_B turned 70 deg) rather than light a lamp',
         tripo_prompt=None),
]


def records(H, items):
    out = []
    for i, it in enumerate(items):
        e = CAT[it['key']]
        X, Y = H.hw(sum(c[0] for c in it['corners']) / 4, sum(c[1] for c in it['corners']) / 4)
        cat = e['cat']
        r = dict(id='%s_%03d' % (SID, i), key=it['key'], asset=e['path'], kind=e['kind'], cat=cat,
                 x_cm=round(X, 1), y_cm=round(Y, 1), ground_z_cm=round(it['bottom_cm'], 1),
                 yaw=round((H.yaw + it['a']) % 360.0, 1), pitch=0.0, roll=0.0, scale=it['scale'],
                 scale_range=[it['scale'], it['scale']], settle=it['settle'], group=it['group'],
                 folder='Set/%s/%s' % (SID, it['group']), data_layer='DL_SetDress', ism=False,
                 stack=bool(it.get('stack')), attach=False, run_id=None, collision=cat != 'cloth', foliage_exclude=True,
                 draw_distance_cm=6000.0, cast_shadow=True, size_m=it['size_m'], contact=it['contact'], support='own',
                 role=it['role'], local=dict(x=round(it['x'], 3), y=round(it['y'], 3), yaw=round(it['a'], 1), on=it['on']),
                 predicted=dict(bottom_cm=round(it['bottom_cm'], 1), top_cm=round(it['top_cm'], 1), on=it['on']))
        if it.get('facing_verify') is not None:
            r['facing_verify'] = it['facing_verify']
        if e['batch01']:
            r['requires_import'] = not e.get('imported', False)
            r['verdict'] = e.get('verdict')
            r['imported'] = e.get('imported', False)
        out.append(r)
        it['id'] = r['id']
    return out


LAYOUT = r'''
                       back wall (+x, downhill)
   +---------------------------------------------------------+
   | bench (tea pot)          [DESK: relay set under its     |  boxes x2
   |  under the shut window    cloth, cold lantern]          |
   |                         chair (pulled back, turned)     |
   | oil jar                   dust                  jug JAR |
   +=========[PLATE outside]====[ arch  door  arch ]=========+  front, turned back up the road
    valley wall (-y)                                   far wall (+y)
'''


def build(v10):
    H = Hut(v10)
    items, derived = compose(H)
    predict(H, items)
    recs = records(H, items)
    ground = decals(H, items)
    views = make_views(H, items)
    byname = {v['name']: v for v in views}
    occ = exterior_occluders(H)
    vis = dict(b23=door_visibility(H, items, byname['carrier_b']['cam_cm'], occ),
               approach=door_visibility(H, items, byname['carrier_a']['cam_cm'], occ),
               door3=door_visibility(H, items, byname['carrier_c']['cam_cm'], occ))
    notes, bad = checks(H, items, ground, vis, views, occ)
    return H, items, derived, recs, ground, views, vis, notes, bad


def write(H, items, derived, recs, ground, views, vis, notes, bad):
    near = [v for v in views if v['name'] not in ('far300', 'high34', 'carrier_a', 'carrier_b')]
    xs = [v['cam_cm'][0] for v in near] + [H.o[0]]
    ys = [v['cam_cm'][1] for v in near] + [H.o[1]]
    ft = H.floor_top_cm
    site = dict(
        id=SID, name='The High Voice relay hut (interior)', kind='hut interior', order=5, road_m=5009,
        side='right of the road end (V10 hut, 9 m)', lateral_m=9, centre_cm=[round(H.o[0], 1), round(H.o[1], 1), round(ft, 1)],
        road_yaw=83.66, radius_m=6, zone='Z6 Summit', storm=STORY['look'], role='landmark, story set',
        story='B23/B24: the mark, the transmission; the kept, empty relay room', decay=0,
        style='AshesOfBazaar / MedievalVillage furniture in V10\'s bazaar-stone hut; brass, clay, timber, cloth',
        layout=LAYOUT, notes='Interior only: V10 owns the shell, the plinth (the floor and the sill) and every exterior piece. '
              'Laid out from V10.json interior_frame on every run; `support: own` items settle on V10\'s plinth (support_labels). '
              'Runs inside V10\'s editor load (every view is in V10\'s load box): no load/unload of its own.',
        story_owned=['V10_HighVoice: plinth, walls, door arch, roof, shutter, plate, speaker hook, exterior dressing',
                     'BP_Saskarta_HighVoice (mast, crown, column, Plate / StandPoint / SeatPoint) and the L2 HighVoice beacon'],
        verify_only=False, layer='road', poi=None,
        load_box_cm=[round(min(xs) - 3000), round(min(ys) - 3000), round(max(xs) + 3000), round(max(ys) + 3000)],
        runs_inside_load_of='V10_HighVoice',
        counts=dict(placements=len(recs), actors=len(recs), ism_instances=0,
                    physics=sum(1 for r in recs if r['settle']['mode'] == 'physics'),
                    batch01=sum(1 for r in recs if r['key'].startswith('B01_')), decals=len(ground)),
        views=views, placements=recs, ground=ground, units=[], waivers=[],
        support_labels=[H.floor['label']],
        ism_candidates=[],
        hut_frame=dict(source='Tools/World/story_sets/V10.json interior_frame', origin_cm=[round(H.o[0], 1), round(H.o[1], 1)],
                       yaw=round(H.yaw, 2), x_axis='front (door) wall -> back wall', y_axis='right of x: - = valley wall, + = far wall',
                       inner_m=dict(front=H.x0, back=H.x1, side=H.half_y), door=dict(w=H.door_w, h=H.door_h, measured=H.door_measured),
                       floor=dict(label=H.floor['label'], top_cm_predicted=H.floor_top_cm), roof_bottom_cm_predicted=H.roof_bottom_cm,
                       derived=derived),
        doorway_read={k: {i['key'] + '_' + i['id'][-3:]: vv[i['id']] for i in items} for k, vv in vis.items()},
        v2=dict(method='docs/world/SETDRESS_V2.md', checks_ok=len(notes), checks_failed=bad),
    )
    doc = dict(generated_by='Tools/World/story_sets/s26_high_voice_hut.py', method='docs/world/SETDRESS_V2.md',
               design='docs/world/story_sets/S26.md', level='/Game/level/Saskarta_WP',
               conventions={'xy': 'world cm; yaw = UE yaw deg', 'bounds': 'x_cm/y_cm is the mesh BOUNDS CENTRE',
                            'ground_z_cm': 'the predicted bottom (the V10 plinth top or the support under it); the editor settle replaces it',
                            'local': 'hut frame metres (hut_frame): x front->back, y right; yaw relative to the hut',
                            'ground': 'decal patches: DecalActor pitch -90, yaw, size (depth/2, width/2, length/2)',
                            'contact': 'rest (SETDRESS_V2.md section 3; check2 measures a rest prop against the first hit under it: the plinth)',
                            'support': 'own = settle only on landscape, this site\'s actors, or support_labels (s26_high_voice_hut.py editor)'},
               story_set=dict(id=SET, site=SID, story=STORY, exists=EXISTS, missing=MISSING,
                              assets_used=sorted({r['asset'] for r in recs}),
                              ground_materials=sorted({'/Game/SaskartaGaea/Environment/SetDress/Ground/MI_SD_Ground_' + g['surface'] for g in ground})),
               rejected=[dict(asset='/Game/AshesOfBazaar/Meshes/SM_Fireplace', why='reads as a crude brick column (S15 V1 capture, orbit_a)'),
                         dict(asset='B01_brick01 as a hearth', why='with no chimney in V10 a hearth block reads as a bench or a step '
                                                                    '(verifier, 2026-09-28); a stove waits for a model')],
               checks=[], sites=[site])
    with open(OUT_JSON, 'w', encoding='utf8') as fh:
        json.dump(doc, fh, indent=1, ensure_ascii=False)
    return site


# ------------------------------------------------------------------------------------ the plot

def plot(H, items, recs, ground, views, vis):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon, Ellipse, Rectangle
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(17, 8.8), gridspec_kw=dict(width_ratios=[1.0, 1.25]))
    colours = dict(relay='#8a5a33', stores='#c49a6c')
    surf = dict(rubble_dust='#e6dcc6')

    def P(x, y):
        return (y, x)          # plot: hut y to the right, hut x up (the back wall at the top)

    # ---- left: the road end, the mast, V10's hut and its exterior (faint), the story hooks, the door sight lines
    xs = np.linspace(-16.0, 10.0, 105)
    ys = np.linspace(-15.0, 11.0, 105)
    Z = np.array([[H.g(*H.hw(x, y)) / 100.0 for y in ys] for x in xs])
    cs = ax1.contour(ys, xs, Z, levels=np.arange(np.floor(Z.min()), np.ceil(Z.max()) + 0.01, 0.5), colors='#cfcfcf', linewidths=0.6)
    ax1.clabel(cs, cs.levels[::4], fmt='%.0f m', fontsize=6)
    road = [H.hl(*H.R.xy(s)) for s in np.linspace(H.L - 45, H.L, 30)]
    ax1.plot([p[1] for p in road], [p[0] for p in road], color='#999', lw=26, alpha=0.2, solid_capstyle='butt')
    ax1.plot([p[1] for p in road], [p[0] for p in road], color='#666', lw=1.0, ls='--')
    for r in H.recs:
        if not r.get('size_m') or r['group'] == 'hut_roof' or r.get('ism'):
            continue
        corners = [H.hl(*c) for c in H.footprint_world(r)]
        col = '#3d3d52' if r['group'] == 'hut' else ('#d8cfb8' if r['group'] == 'hut_floor' else '#b9b3a6')
        ax1.add_patch(Polygon([P(*c) for c in corners], closed=True, facecolor=col, edgecolor='none',
                              alpha=0.85 if r['group'] == 'hut' else 0.35))
    ml = H.hl(*MAST_CM)
    ax1.add_patch(Rectangle((ml[1] - 0.4, ml[0] - 0.4), 0.8, 0.8, color='#222'))
    ax1.annotate('mast (point 0, road end)', (ml[1] + 0.6, ml[0] - 0.2), fontsize=7)
    hk = H.hooks
    for key, mk, lab in (('Plate', 's', 'plate (mark), outside'), ('StandPoint', 'o', 'StandPoint'), ('OTS_cam_cm', '^', 'CIN24 S1 camera')):
        pt = hk[key]['centre_cm'] if key == 'Plate' else (hk[key]['feet_cm'] if key == 'StandPoint' else hk[key])
        l = H.hl(*pt[:2])
        ax1.plot(l[1], l[0], marker=mk, color='#1f5fa8', ms=4)
        ax1.annotate(lab, (l[1] - 0.25, l[0] - 0.5), fontsize=6.5, color='#1f5fa8', ha='right')
    sp = hk['SeatPoint']
    sl = H.hl(*sp['cm'][:2])
    ax1.plot(sl[1], sl[0], marker='v', color='#b03030')
    for da in (-26.3, 26.3):
        ang = math.radians(sp['yaw'] + da - H.yaw)
        ax1.plot([sl[1], sl[1] + 9 * math.sin(ang)], [sl[0], sl[0] + 9 * math.cos(ang)], color='#b03030', lw=0.7, alpha=0.6)
    ax1.annotate('SeatedCam (CIN24 S5), looks east', (sl[1] - 0.5, sl[0] - 1.6), fontsize=6.5, color='#b03030', ha='right')
    for v in views:
        if v['name'] not in ('carrier_b', 'carrier_c'):
            continue
        e = H.hl(*v['cam_cm'][:2])
        for yy in (H.door_y - H.door_w / 2, H.door_y + H.door_w / 2):
            tb = (H.x1 - e[0]) / (H.arch_outer - e[0])
            ax1.plot([e[1], e[1] + (yy - e[1]) * tb], [e[0], H.x1], color='#2a8a2a', lw=0.6, alpha=0.7)
        ax1.plot(e[1], e[0], marker='D', color='#2a8a2a', ms=4)
        ax1.annotate(v['name'] + (' (B23 prompt, walk camera)' if v['name'] == 'carrier_b' else ''), (e[1] + 0.3, e[0]), fontsize=6.5, color='#2a8a2a')
    ax1.set_title('S26 in context: the road end, the mast, V10\'s hut on its plinth (hut frame, m)', fontsize=9)

    # ---- both: the room
    pl = H.plinth_rec()
    for ax in (ax1, ax2):
        ax.add_patch(Polygon([P(*H.hl(*c)) for c in H.footprint_world(pl)], closed=True, facecolor='#e9e3d6', edgecolor='#9a9385',
                             lw=0.6, ls='--'))
        for g in ground:
            gl = (g['local']['x'], g['local']['y'])
            a = math.radians(g['yaw'] - H.yaw)
            w_, h_ = (g['width_m'], g['length_m']) if abs(math.sin(a)) < 0.5 else (g['length_m'], g['width_m'])
            ax.add_patch(Ellipse(P(*gl), w_, h_, color=surf[g['surface']], alpha=0.55))
        for it in items:
            ax.add_patch(Polygon([P(*c) for c in it['corners']], closed=True, facecolor=colours[it['group']], edgecolor='black',
                                 lw=0.5, alpha=0.95 if it['on'] != 'floor' else 0.8))
    for r in H.walls:
        cs_ = [H.hl(*c) for c in H.footprint_world(r)]
        ax2.add_patch(Polygon([P(*c) for c in cs_], closed=True, facecolor='#d9cdb8', edgecolor='#7a6a55', lw=0.8, hatch='////'))
    ax2.add_patch(Rectangle((H.door_y - H.door_w / 2, H.arch_outer), H.door_w, H.arch_inner - H.arch_outer, facecolor='white', edgecolor='none'))
    for it in items:
        c = (sum(p[0] for p in it['corners']) / 4, sum(p[1] for p in it['corners']) / 4)
        if it['key'] == 'MV_box_03' and it['scale'] != 1.0:
            continue
        label = '%s %s' % (it['id'][-3:], it['key'].split('_', 1)[1])
        if it['key'] == 'MV_box_03':
            label = '%s/%03d box_03 x2' % (it['id'][-3:], int(it['id'][-3:]) + 1)
        off = {'AB_Table_Cloth': (-0.2, -0.12), 'AB_WoodenTable_B': (0.0, 0.3), 'PH_lantern': (0.12, 0.1), 'PH_pot': (0.0, 0.18)}.get(it['key'], (0, 0))
        ax2.annotate(label, (c[1] + off[0], c[0] + off[1]), fontsize=6.3, ha='center', va='center')
    plh = H.hl(*H.hooks['Plate']['centre_cm'][:2])
    ax2.plot(plh[1], plh[0], marker='s', color='#1f5fa8', ms=7)
    ax2.annotate('plate (mark), outside on the jamb', (plh[1], plh[0] - 0.22), fontsize=6.5, color='#1f5fa8', ha='center')
    st = H.hl(*H.hooks['StandPoint']['feet_cm'][:2])
    ax2.plot(st[1], st[0], marker='o', color='#1f5fa8', ms=4)
    ax2.annotate('StandPoint', (st[1] + 0.12, st[0]), fontsize=6.5, color='#1f5fa8', va='center')
    ax2.add_patch(Rectangle((H.door_y - H.door_w / 2 - 0.05, H.x0), H.door_w + 0.1, 0.45, facecolor='none', edgecolor='#2a8a2a', ls=':', lw=1.0))
    ax2.annotate('threshold (clear)', (H.door_y, H.x0 + 0.22), fontsize=6.3, color='#2a8a2a', ha='center')
    ax2.annotate('shuttered window (closed, outside)', (-H.half_y - 0.16, H.window_x), fontsize=6, color='#555', rotation=90, va='center', ha='center')
    v = [x for x in views if x['name'] == 'carrier_b'][0]
    e = H.hl(*v['cam_cm'][:2])
    for yy in (H.door_y - H.door_w / 2 + 0.03, H.door_y + H.door_w / 2 - 0.03):
        t1 = (H.x1 - e[0]) / (H.arch_outer - e[0])
        ax2.plot([yy, e[1] + (yy - e[1]) * t1], [H.arch_outer, H.x1], color='#2a8a2a', lw=0.8, alpha=0.7)
    ids = {k: [it['id'] for it in items if it['key'] == k][0] for k in ('AB_WoodenTable_B', 'AB_Table_Cloth', 'AB_Chair_A_low')}
    ax2.annotate('through the door from the B23 prompt (19.5 m, walk camera): desk %d %%, covered set %d %%, chair %d %%; '
                 'from 3 m: %d / %d / %d %%' % tuple([100 * vis['b23'][ids[k]] for k in ('AB_WoodenTable_B', 'AB_Table_Cloth', 'AB_Chair_A_low')] +
                                                     [100 * vis['door3'][ids[k]] for k in ('AB_WoodenTable_B', 'AB_Table_Cloth', 'AB_Chair_A_low')]),
                 (0.0, H.arch_outer - 0.55), fontsize=6.8, color='#2a8a2a', ha='center')
    ax2.set_title('The room (hut frame, m): floor = V10 plinth top %.2f m (predicted), roof %.2f m; door %.2f x %.2f m %s'
                  % (H.floor_top_cm / 100, H.roof_bottom_cm / 100, H.door_w, H.door_h, 'measured' if H.door_measured else '(ASSUMED)'), fontsize=9)
    for ax, (x0, x1, y0, y1) in ((ax1, (-15.0, 11.0, -16.0, 10.0)), (ax2, (-2.3, 2.3, -2.9, 2.0))):
        ax.set_xlim(x0, x1)
        ax.set_ylim(y0, y1)
        ax.set_aspect('equal')
        ax.set_xlabel('hut y (m): - = valley wall, + = far wall', fontsize=7)
        ax.set_ylabel('hut x (m): - = the front (door, plate), + = the back wall', fontsize=7)
        ax.tick_params(labelsize=6)
        ax.grid(alpha=0.15)
    fig.suptitle('S26 The High Voice relay hut, interior (V2 method): %d placements, %d decals, in V10\'s one-room hut (walls hatched)' % (len(recs), len(ground)),
                 fontsize=10)
    fig.tight_layout()
    os.makedirs(os.path.dirname(OUT_PNG), exist_ok=True)
    fig.savefig(OUT_PNG, dpi=130)
    plt.close(fig)


# ------------------------------------------------------------------------------------ the editor runner

OLD_TR = ("    def tr(x, y):\n"
          "        h = trace_ground(x, y, top, gz - 3000, ign) if ground_only else trace_down(x, y, top, gz - 3000, ign)\n")
NEW_TR = ("    def tr(x, y):\n"
          "        if ground_only:\n"
          "            h = trace_ground(x, y, top, gz - 3000, ign)\n"
          "        elif it.get('support') == 'own':\n"
          "            h = trace_own(x, y, top, gz - 3000, ign)\n"
          "        else:\n"
          "            h = trace_down(x, y, top, gz - 3000, ign)\n")
TRACE_OWN = r'''
def trace_own(x, y, ztop, zbot, ignore):
    """The first hit straight down that is the landscape, an actor of this site, or a listed support (V10's
    plinth): the roof and the wall tops of the hut are passed through, so an interior prop never lands on them."""
    ign = list(ignore)
    for _ in range(8):
        h = trace_down(x, y, ztop, zbot, ign)
        if h is None:
            return None
        if is_land(h[2]) or ('SD_' + SITE) in [str(t) for t in h[2].tags] or h[2].get_actor_label() in SUPPORT_LABELS:
            return h
        ign.append(h[2])
    return None
'''


def run_editor(argv, materials=False):
    """Run a place_setdress.py step (or build_setdress_materials.py) with the V2 site file swapped for S26.json."""
    import place_setdress as ps
    ps.SITES_V2_JSON = OUT_JSON
    if OLD_TR not in ps.SETTLE_BODY:
        raise SystemExit('place_setdress.SETTLE_BODY changed: the support=own patch no longer applies; stop and re-check')
    labels = json.load(open(OUT_JSON, encoding='utf8'))['sites'][0]['support_labels']
    ps.SETTLE_BODY = ('SUPPORT_LABELS = %r\n' % labels) + TRACE_OWN + ps.SETTLE_BODY.replace(OLD_TR, NEW_TR)
    slim0 = ps.slim

    def slim(p):
        q = slim0(p)
        if 'support' in p:
            q['support'] = p['support']
        return q
    ps.slim = slim
    if materials:
        import build_setdress_materials as bm
        sys.argv = ['build_setdress_materials.py'] + argv[:1] + ([SID] if argv[:1] == ['variants'] else []) + argv[1:]
        bm.main()
        return
    step = argv[0]
    rest = argv[1:]
    if step in ('load', 'unload') and '--own-load' not in rest:
        raise SystemExit('S26 runs inside V10\'s load (every S26 view is in V10\'s load box): run its steps while '
                         'V10_HighVoice is loaded. Pass --own-load to load S26 on its own anyway.')
    rest = [a for a in rest if a != '--own-load']
    if '--v2' not in rest:
        rest.append('--v2')
    if step == 'capture' and '--views' not in rest:
        rest += ['--views', 'carrier_a,carrier_b,carrier_c,orbit_a,orbit_b,orbit_c,contact,high34,far300,seat']
    sys.argv = ['place_setdress.py', step] + ([] if step in ('list', 'probe') else [SID]) + rest
    ps.main()


def main():
    if len(sys.argv) > 1 and sys.argv[1] == 'editor':
        return run_editor(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == 'materials':
        return run_editor(sys.argv[2:], materials=True)
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--check', action='store_true')
    ap.add_argument('--no-plot', action='store_true')
    ap.add_argument('--v10', default=V10_JSON, help='the V10 hut data (interior_frame, the plinth, hooks)')
    args = ap.parse_args()
    if not os.path.exists(args.v10):
        raise SystemExit('%s is missing: S26 is laid out inside V10\'s hut and waits for it' % args.v10)
    v10 = json.load(open(args.v10, encoding='utf8'))
    need = ('hut_centre_cm', 'hut_x_yaw_world', 'inner_m', 'arch_m', 'door_opening_m', 'plate', 'window', 'floor',
            'roof_bottom_cm_predicted', 'grade_z_cm')
    miss = [k for k in need if k not in v10.get('interior_frame', {})]
    if miss:
        raise SystemExit('V10.json interior_frame lacks %s: regenerate V10 (v10_high_voice.py) first' % ', '.join(miss))
    H, items, derived, recs, ground, views, vis, notes, bad = build(v10)
    if not args.check:
        site = write(H, items, derived, recs, ground, views, vis, notes, bad)
        if not args.no_plot:
            plot(H, items, recs, ground, views, vis)
        c = site['counts']
        print('%s (%s): %d placements, %d actors, %d physics, %d decals -> %s' % (
            SID, SET, c['placements'], c['actors'], c['physics'], c['decals'], os.path.relpath(OUT_JSON, ROOT)))
    print('hut frame origin (%.1f, %.1f) cm, yaw %.2f; inner x %.2f..%.2f, y +-%.2f m; door %.2f x %.2f m (%s); floor top %.1f '
          '(V10 plinth, predicted); roof bottom %.1f' % (H.o[0], H.o[1], H.yaw, H.x0, H.x1, H.half_y, H.door_w, H.door_h,
                                                          'measured' if H.door_measured else 'assumed', H.floor_top_cm, H.roof_bottom_cm))
    for it in items:
        print('  %-24s %-18s on %-6s bottom %8.1f top %8.1f  local (%5.2f, %5.2f) a %6.1f' % (
            it['id'], it['key'], it['on'], it['bottom_cm'], it['top_cm'], it['x'], it['y'], it['a']))
    for k, v in vis.items():
        print('  doorway read from %-8s %s' % (k, ', '.join('%s %.2f' % (i['key'], v[i['id']]) for i in items if v[i['id']] > 0)))
    print('%d checks ok, %d failed' % (len(notes), len(bad)))
    for b in bad:
        print('  ' + b)
    if bad:
        sys.exit(1)


if __name__ == '__main__':
    main()
