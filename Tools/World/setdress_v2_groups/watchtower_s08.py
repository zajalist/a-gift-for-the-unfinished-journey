"""S08 Efkirekeb Zdaw, the Valley Watchtower: the V2 prototype of a hand-composed road landmark.

Replaces the V1 layout the author called ugly in the packaged game (2026-09-29): a clean tower block
(B01_house03) and three flat Fort-wall slabs standing on flat grass. The tower is now a broken shell built
from the bazaar kit, collapsed on its downhill (road) side, inside a stepped yard wall with a gate facing
the road, and everything grows out of its own debris (SETDRESS_V2.md sections 1-3).

    python Tools/World/setdress_v2_groups/watchtower_s08.py            # compose, check, plot, write + patch
    python Tools/World/setdress_v2_groups/watchtower_s08.py --dry-run  # compose, check and plot only

Writes setdress_v2_groups/watchtower_s08.json and replaces ONLY the S08 record in setdress_v2_sites.json
(the composer file wins over the group files in place_setdress.merge_v2_groups).

Frame: K(x, y) is the terrace frame at the tower (x along the contour, y uphill). Uphill is away from the
road here (the site sits on a low knoll 28 m right of the road, 3.6 deg fall toward it), so the collapsed
front, the gate and the rubble spill all face the road and the tall back wall stands against the sky.
"""

import argparse
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WORLD = os.path.dirname(HERE)
sys.path.insert(0, WORLD)
import build_setdress_sites as B  # noqa: E402
import setdress_v2 as V  # noqa: E402

SID = 'S08_Watchtower'
OUTPUT = os.path.join(HERE, 'watchtower_s08.json')
AGGREGATE = V.OUT

LAYOUT = r'''
  S08 top-down (K frame: x along the contour, y uphill; 1 char ~ 1 m; road ~28 m below the bottom edge)

   y+12            .  .  dry-stone terrace fragment (wall02, sunk 35, gaps)  .  .
   y +7       scrub in the lee      ##########      <- back wall: AB_Danaged_Wall_B, 8 m, the skyline
   y +3        |arch|  beam   ###  | dmg 3.7 m |
   y  0   T1   |wall|  rubble      |           |     tower shell 7 x 7 m, rotated 8 deg off the contour
   y -3   /    |6.9m| beam  ==  :  stump 1 m   /      right side steps down 3.7 -> 1 -> gone
   y -4  /     low 1.4 m    \  \  .  .  :  .  /       front-right corner COLLAPSED: heaps, chunks, blocks
   y -7 lean          beam out  \ fan . : . .  .      spilling downhill toward the road, dust decal
   y-11  [stump][low][dmg][JAMB=lintel=JAMB][low] gap [stump][low]  <- yard wall, stepped, gate faces road
   y-14  S1 stump    roots       path  |       fallen trunk     marker stone (half sunk)
                                         \_ worn track to the road verge
  ==================================== road (approach from the left) ====================================
  T1 = dead tree (qlEtl x0.72) leaning 14 deg over the west yard wall; S1 = stump; tufts + shrubs at every base
'''

# The verdict cameras from the road (carrier eye), metres of road BEFORE the site: ~35, ~55 and ~78 m away.
ROAD_CAMS = (('road30', 20.0), ('road55', 45.0), ('road80', 70.0))


def K_of(ang, O):
    return V.terrace_frame(ang, O)


def recipe(C, sp):
    F, rng = C.F, C.rng
    ang0 = F.contour_deg(0.0, 0.0)
    ang = ang0 + 8.0                                   # the tower turns off the contour: not ruled
    K = K_of(ang, (0.0, 0.0))
    Ky = K_of(ang0, (0.0, 0.0))                        # the yard follows the contour itself

    def D(k, dx, dy):
        a, b = k(dx, dy), k(0.0, 0.0)
        return (a[0] - b[0], a[1] - b[1])
    C.cu, C.cv = K(0.0, 0.0)

    # ---- the tower shell: four sides of different survival, one block (the corners interlock by design)
    H = 3.4

    def side(key, a, b, state, sink, scale=1.0, face=(0.0, -1.0), shed=None):
        pa, pb = K(*a), K(*b)
        u, v = (pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2
        wang = math.degrees(math.atan2(pb[1] - pa[1], pb[0] - pa[0]))
        yaw = wang - (90.0 if V.long_axis_y(key) else 0.0) + rng.choice((0.0, 180.0))
        _, _, h = V.piece_dims(key, scale)
        C.walls.append((pa[0], pa[1], pb[0], pb[1], state, 'TOWER'))
        C.add(key, u, v, yaw, 'tower', 'rigid', scale=scale, block='TOWER', sink_cm=sink, material_set='stone',
              state=state, vis_h=round(h - sink / 100.0, 2), landmark=True,
              note='tower shell, %s side' % state)
        if shed:
            C.collapse(u, v, D(K, *face), shed, wang)
    side('AB_Danaged_Wall_B', (-3.55, H), (3.55, H), 'tallruin', 45, face=(0, 1), shed=0.3)      # back: the skyline
    side('AB_Broken_Arch_Wall', (-H, -3.3), (-H, 3.3), 'tallruin', 35, face=(-1, 0), shed=0.35)  # west: 6.9 m
    side('AB_300x400_Mid_Damaged_A', (H, 0.3), (H, 3.3), 'damaged', 40, face=(1, 0), shed=0.45)  # east, upper
    side('AB_300x100_Panel_Damages_A', (H, -2.9), (H, -0.3), 'stump', 18, face=(1, 0), shed=0.75)  # east, lower
    side('B01_wall01', (-3.1, -H), (-0.1, -H), 'low', 12, scale=0.75, face=(0, -1), shed=0.6)    # front, west half
    gp, gq = K(0.1, -H), K(3.1, -H)
    C.walls.append((gp[0], gp[1], gq[0], gq[1], 'gap', 'TOWER'))
    cu_, cv_ = K(H, -H)
    ou, ov = D(K, 0.7071, -0.7071)
    C.collapse_corner(cu_, cv_, ou, ov, ang)                  # the collapsed corner: heaps, chunks, the spray
    bu, bv = K(1.6, -H)
    C.doors.append((bu, bv, 'TOWER', 0, *D(K, 0.0, -1.0)))   # the breach is the way in (kept swept)

    # the room record: floors (rubble dust), fallen roof beams inside, corner rubble and creep
    corners, centres = [], []
    for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        at = K(sx * H, sy * H)
        corners.append(dict(at=at, inset=K(sx * (H - 0.55), sy * (H - 0.55))))
        centres.append(K(sx * 1.6, sy * 1.6))
    C.rooms.append(dict(block='TOWER', name='TOWER', cells=[[K(-H, -H), K(H, -H), K(H, H), K(-H, H)]],
                        centres=centres, corners=corners, centre=K(0, 0), w=2 * H, d=2 * H, n_cells=4, rect=True,
                        ang=ang, group='tower', court=False))
    C.rows.append(dict(name='TOWER', block='TOWER', u0=K(-H, -H)[0], v0=K(-H, -H)[1], ang=ang, cells=[], rooms=1,
                       group='houses'))
    # the upper floor came down through the breach: beams lying out over the corner heap, pointing downhill
    for (x, y, rot_, key, pitch, roll) in ((2.6, -5.2, -62, 'MV_Beam_03', 90.0, 6.0),
                                           (4.9, -6.8, -38, 'B01_beam01', 0.0, -9.0),
                                           (-1.2, -5.9, 12, 'AB_Woden_Beam_A_low', 90.0, 4.0)):
        u, v = K(x, y)
        C.add(key, u, v, ang + rot_, 'beams', 'lie', pitch=pitch, roll=roll, sink_cm=8, material_set='wood',
              block='beam', note='floor beam fallen out of the tower')
    # dressed blocks from the tower's upper courses, thrown furthest down the slope, half sunk in the soil
    for (x, y) in ((6.2, -8.4), (3.4, -9.0), (7.8, -5.6)):
        u, v = K(x, y)
        C.add('B01_brick01', u, v, rng.uniform(0, 360), 'rubble', 'lie', roll=rng.uniform(-14, 14),
              sink_cm=22, material_set='stone', block='fan', note='tower block, half sunk')

    # ---- the yard wall on the contour below the tower: stepped plumb pieces, broken runs, the gate
    yard_y = -11.0
    front = [(-13.5, yard_y + 0.6), (-1.6, yard_y), (13.0, yard_y - 0.9)]      # a slight bend with the ground
    C.wall_line(Ky(*front[0]), Ky(*front[1]), ['stump', 'low', 'damaged', 'low'], 'YARD', 'yard',
                D(Ky, 0.0, -1.0))
    C.wall_line(Ky(*front[1]), Ky(*front[2]), ['lintel', 'low', 'gap', 'stump', 'low'], 'YARD', 'yard',
                D(Ky, 0.0, -1.0))
    gu, gv = Ky(-1.6 + 1.45, yard_y - 0.1)
    C.doors.append((gu, gv, 'YARD', 0, *D(Ky, 0.0, -1.0)))
    # the west return runs up the fall line: each piece plumb and sunk on its own, so the run steps
    C.wall_line(Ky(-13.5, yard_y + 0.6), Ky(-12.2, -1.0), ['damaged', 'low', 'stump'], 'YARD_W', 'yard',
                D(Ky, -1.0, 0.0))
    # the east return is only a fragment; the rest has gone
    C.wall_line(Ky(13.0, yard_y - 0.9), Ky(11.6, -5.0), ['low', 'stump'], 'YARD_E', 'yard', D(Ky, 1.0, 0.0))
    # behind: a dry-stone terrace edge of the old watch garden, partly buried, slumped in places
    C.terrace_wall([Ky(-10.0, 11.5), Ky(-2.0, 12.3), Ky(9.0, 11.2)], group='terrace', gap_every=0.3,
                   name='terrace', sink=38, record=True, state='drystone')

    # ---- worn ground: the trodden yard, the path gate -> breach, the track to the road
    yc = Ky(0.0, -5.0)
    C.patch('packed_earth', yc[0], yc[1], ang0, 27.0, 13.0, 0.62, order=0)
    tc = K(0.0, 0.0)
    C.patch('packed_earth', tc[0], tc[1], ang, 11.5, 11.0, 0.9, order=0)          # darker soil at the foot
    C.path([Ky(-0.15, yard_y - 2.5), (gu, gv), K(1.0, -6.0), K(1.4, -2.2)], 1.6, wander=0.25, strength=0.8)
    C.road_link(2.2, max_len=30.0, strength=0.8)

    # ---- trees with intent: few, short, gnarled; never a picket of poles
    tu, tv = Ky(-15.6, -6.0)
    lean = math.degrees(math.atan2(*reversed(D(Ky, 1.0, 0.0))))
    C.add('FAB_DeadTree_qlEtl', tu, tv, lean, 'trees', None, scale=0.72, pitch=-14.0, collision=True,
          settle_over=dict(mode='trace', max_tilt_deg=0, rand_tilt_deg=0, z_rule='min', sink_cm=35),
          note='dead tree leaning 14 deg over the west yard wall (the storm side)')
    for dx, dy, key in ((0.9, 0.4, 'PH_roots_a'), (-0.7, -0.6, 'PH_roots_b')):
        C.add(key, tu + dx, tv + dy, rng.uniform(0, 360), 'trees', 'lie', sink_cm=4, note='exposed roots')
    for (x, y, key, sc) in ((-8.5, -15.0, 'PH_stump_01', 0.9), (9.0, 2.5, 'FAB_Stump', 1.1)):
        u, v = Ky(x, y)
        C.add(key, u, v, rng.uniform(0, 360), 'trees', 'rest', scale=sc, sink_cm=10, note='old stump')
    u, v = Ky(6.5, -16.0)
    C.add('PH_trunk_02', u, v, ang0 + 18.0, 'trees', 'lie', sink_cm=14, note='fallen trunk: the foreground layer')
    u, v = Ky(-3.6, -17.5)
    C.add('B01_marker01', u, v, ang0 + 100.0, 'marker', 'rigid', scale=1.2, sink_cm=28, material_set='stone',
          block='marker', pitch=6.0, note='way-stone at the track, half sunk and leaning')
    # scrub clusters in the lee of the back wall and at the gate (creep adds the tufts along every base)
    for (x, y, n) in ((-2.0, 4.6, 4), (2.6, 4.4, 3), (-1.9, -12.3, 2), (-14.6, -2.5, 3), (12.4, -7.4, 2)):
        for _ in range(n):
            u, v = K(x + rng.uniform(-0.8, 0.8), y + rng.uniform(-0.5, 0.5))
            C.add(rng.choice(V.SHRUBS if rng.random() < 0.5 else V.TUFTS), u, v, rng.uniform(0, 360), 'creep',
                  scale=(0.9, 1.5), ism=True, block='creep')
    C.meta.update(frame=dict(ang=ang, ang_yard=ang0), keep=[])


SPEC = dict(
    archetype='fortress', recipe=recipe, seed='S08v2.proto1', burnt=0, mud=0, creep_edge=44,
    name='Efkirekeb Zdaw, the Valley Watchtower', role='landmark', order=3, radius_m=30,
    story='none (quiet stretch): the silhouette seen from the Waiting Water; marks the ridge grade',
    style='BAZAAR STONE: a broken watchtower shell in a stepped yard; collapse spills toward the road',
    layout=LAYOUT,
    notes=('V2 prototype 2026-09-29 (the author: V1 "looks ugly": clean tower block + flat slabs on grass). '
           'Kit-built shell of uneven height, collapsed road-side corner, stepped yard wall with a lintel gate, '
           'every base in rubble and creep, one leaning dead tree and stumps. Editor follow-up: the landscape '
           'dead-tree scatter inside radius_m must be cleared by the PB_FoliageExclude tags or by hand.'),
    views=dict(target=(0.0, 0.0), orbits=((-24.0, -18.0), (24.0, -14.0), (6.0, 26.0)), high34=(-26.0, -34.0)),
)


def road_views(W, so):
    cx, cy, cz = [c / 100.0 for c in so['centre_cm']]
    look = [round(cx * 100, 1), round(cy * 100, 1), round((W.ground(cx, cy) + 4.0) * 100, 1)]
    out = []
    for name, back in ROAD_CAMS:
        p, _, _ = W.frame(so["road_m"] - back)
        p = [float(p[0]), float(p[1])]
        z = W.ground(p[0], p[1]) + B.EYE_M
        out.append(dict(name=name, cam_cm=[round(p[0] * 100, 1), round(p[1] * 100, 1), round(z * 100, 1)],
                        look_cm=look, dist_m=round(math.hypot(p[0] - cx, p[1] - cy), 1),
                        note='verdict screenshot from the road (carrier eye)'))
    return out


def compose_site(W):
    V.SITE_SPECS[SID] = SPEC
    out_sites, totals = V.build(W, [SID])
    so = out_sites[0]
    so['group'] = 'watchtower_s08'
    so['views'] = road_views(W, so) + so['views']
    so['counts']['placements'] = len(so['placements'])
    return so, totals


def patch_aggregate(record):
    """Replace only the S08 record of the composer JSON (every other byte kept)."""
    raw = open(AGGREGATE, 'rb').read()
    text = raw.decode('utf-8')
    m = list(re.finditer(r'(?m)^  \{\r?\n   "id": "' + SID + r'",', text))
    if len(m) != 1:
        raise RuntimeError('expected one %s record in the aggregate, found %d' % (SID, len(m)))
    start = m[0].start()
    old, length = json.JSONDecoder().raw_decode(text[start + 2:])
    new = json.dumps(record, indent=1, ensure_ascii=False)
    new = '\n'.join(('  ' + ln) if i else ln for i, ln in enumerate(new.split('\n')))
    revised = text[:start + 2] + new + text[start + 2 + length:]
    before, after = json.loads(text), json.loads(revised)
    a, b = {s['id']: s for s in before['sites']}, {s['id']: s for s in after['sites']}
    if a.keys() != b.keys() or any(a[k] != b[k] for k in a if k != SID) or b[SID] != json.loads(json.dumps(record)):
        raise RuntimeError('aggregate patch changed more than S08')
    if open(AGGREGATE, 'rb').read() != raw:
        raise RuntimeError('aggregate changed concurrently')
    open(AGGREGATE, 'wb').write(revised.encode('utf-8'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()
    W = B.World()
    so, t = compose_site(W)
    oc = so['offline_check']
    c = so['counts']
    print('%s placements %d actors %d ism %d decals %d | offline violations %d waived %d' % (
        SID, c['placements'], c['actors'], c['ism_instances'], c['decals'], len(oc['violations']), len(oc['waived'])))
    for x in oc['violations'][:20]:
        print('  ', x)
    print('rejected', t['rejected'][:10])
    for vw in so['views'][:3]:
        print('  view', vw['name'], vw['dist_m'], 'm', vw['cam_cm'])
    import setdress_v2_plot
    setdress_v2_plot.preview(W, so)
    if args.dry_run:
        return
    if oc['violations'] or c['actors'] > 250 or c['decals'] > 300:
        raise SystemExit('not written: violations or over budget')
    with open(OUTPUT, 'w', encoding='utf8') as fh:
        json.dump(dict(generated_by='Tools/World/setdress_v2_groups/watchtower_s08.py', group='watchtower_s08',
                       level='/Game/level/Saskarta_WP', sites=[so]), fh, indent=1, ensure_ascii=False)
    patch_aggregate(so)
    print('wrote', OUTPUT, 'and patched', AGGREGATE)


if __name__ == '__main__':
    main()
