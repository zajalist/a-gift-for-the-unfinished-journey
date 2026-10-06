"""Set dressing V2, group 'water and stone features': the recipes of the smaller sites (fold, convoy, signal post,
rest niche, cairn, hearth, seat, markers). The cistern (S17), the shared grammar and the build live in
water_stone_features.py, which imports this module and registers these recipes in its SITES table.
"""
import math

import numpy as np

import setdress_v2 as V
from setdress_v2 import rect, terrace_frame
from water_stone_grammar import (bed, clump, face, pebble_cap, rigid, road_pt, spill, standing_stone,  # noqa: F401
                                 verge_link)


# ---------------------------------------------------------------------------- S03 the Goat Fold

S03_LAYOUT = '''
  ==== road (24 m) ====   the goats' track from the verge to the fold gate (trampled, wide)
     ( fold: an irregular oval of dry-stone courses, slumped in places; gate posts, the gate swung open )
       inside: manger along the far wall, the last hay, the water trough by the gate, trampled earth
     [kid pen: fence panels]   field walls trailing off along the ground     [shepherd's hut: one room,
                                                                              door onto the fold]  cold hearth,
                                                                              pot, carafe, seat stone, log
'''


def s03(C, sp):
    """The Goat Fold: a dry-stone fold with its gate toward the road, the shepherd's hut facing it, a cold
    hearth beside the hut, a kid pen of fence panels and field walls trailing off: a working place, left."""
    O = (0.0, -2.0)
    C.cu, C.cv = O
    ru, rv = road_pt(C, *O)
    a0 = math.atan2(rv - O[1], ru - O[0])                  # toward the road: the gate
    rx, ry = 7.6, 6.2
    pts = []
    n = 9
    gate = math.radians(13.0)
    for k in range(n + 1):
        a = a0 + gate + (2 * math.pi - 2 * gate) * k / n
        r = rx * ry / math.hypot(ry * math.cos(a - a0), rx * math.sin(a - a0)) * C.rng.uniform(0.95, 1.05)
        pts.append((O[0] + r * math.cos(a), O[1] + r * math.sin(a)))
    g0, g1 = pts[-1], pts[0]
    G = ((g0[0] + g1[0]) / 2, (g0[1] + g1[1]) / 2)          # the gate
    gd = (math.cos(a0), math.sin(a0))
    G_out = (G[0] + gd[0] * 2.4, G[1] + gd[1] * 2.4)
    # -- lanes: the goats' track to the road, into the fold, round the fold to the hut
    verge_link(C, G_out, width=2.6, strength=0.95, apron=(7.5, 5.5))
    C.path([G_out, (G[0] - gd[0] * 2.5, G[1] - gd[1] * 2.5)], 2.2, strength=0.9)
    hut_path = C.path([G_out, (9.0, 6.6), (9.0, 1.8), (9.0, -3.2), (10.4, -5.4)], 1.3, wander=0.25, strength=0.85)
    # -- the fold
    fold = C.yard(pts, gap_every=0.14, contents=())
    C.patch('packed_earth', O[0], O[1], math.degrees(a0), 2 * rx, 2 * ry, 1.0, order=1)
    C.patch('path', G[0] - gd[0] * 1.5, G[1] - gd[1] * 1.5, math.degrees(a0), 6.0, 3.6, 0.9, order=2)
    for gp in (g0, g1):
        pu, pv = gp[0] + gd[0] * 0.4, gp[1] + gd[1] * 0.4
        rigid(C, 'MV_Fence_01_Log1', pu, pv, 0, 'gate', 'gate', 22, scale=1.25, mat='wood', state='post',
              note='gate post')
        bed(C, pu, pv, 0.2, 3)
    ga = math.degrees(a0) - 22.0                            # the gate swung open, outward (closed: a0 - 90)
    hu, hv = g1[0] + gd[0] * 0.4, g1[1] + gd[1] * 0.4
    L = V.CAT['MV_Fence_01_V2']['size_cm'][1] / 100.0
    rigid(C, 'MV_Fence_01_V2', hu + math.cos(math.radians(ga)) * (L / 2 + 0.2), hv + math.sin(math.radians(ga)) * (L / 2 + 0.2),
          ga - 90.0, 'gate', 'gate', 14, mat='wood', state='fence', note='the fold gate, swung open and left')
    # inside: the manger along the far side, the last hay, the trough by the gate
    far_a = a0 + math.pi
    mu, mv = O[0] + math.cos(far_a) * (rx - 2.0), O[1] + math.sin(far_a) * (ry - 2.0)
    C.add('MV_Manger', mu, mv, math.degrees(far_a) + 90.0, 'fold', 'rest', material_set='wood', block=fold + '_c')
    C.add('MV_Hay_Bale_02', mu + math.cos(far_a + 1.4) * 2.6, mv + math.sin(far_a + 1.4) * 2.6, C.rng.uniform(0, 360),
          'fold', 'rest', note='the last of the hay, half pulled apart')
    tu, tv = G[0] - gd[0] * 3.4 + gd[1] * 2.2, G[1] - gd[1] * 3.4 - gd[0] * 2.2
    C.add('MV_wash_tub', tu, tv, math.degrees(a0), 'fold', 'rest', material_set='wood', note='the water trough, dry')
    C.add('MV_bucket_03', tu - gd[0] * 1.2, tv - gd[1] * 1.2, 0, 'fold', 'rest', roll=85)
    clump(C, mu - math.cos(far_a) * 1.0, mv - math.sin(far_a) * 1.0, 1.2, 4, 0.2)
    # -- the shepherd's hut, its door onto the fold; the cold hearth beside it
    C.block('HUT', 10.6, 3.2, -90.0, [rect(0, 0, 2, 1)], 2, group='houses', collapse_corners=1, lintel_p=0.8)
    C.block_lane['HUT'] = hut_path
    C.door_spurs(width=1.2)
    fu, fv = 11.8, -7.6
    rigid(C, 'PH_fire_pit', fu, fv, 20, 'hearth', 'hearth', 8, state='hearth', note='the cold hearth')
    C.patch('soot', fu, fv, 30, 2.4, 2.0, 0.9, order=4)
    C.patch('packed_earth', fu - 0.4, fv + 0.4, 10, 5.5, 4.5, 0.9, order=1)
    C.add('PH_pot', fu + 0.1, fv - 0.1, 30, 'hearth', 'rest', note='the pot left on the hearth stones')
    C.add('MV_carafe_01', fu + 1.3, fv + 0.9, 0, 'hearth', 'rest', scale=0.8)
    rigid(C, 'FAB_TempleStones', fu - 1.9, fv - 0.6, 75, 'hearth', 'seat', 8, scale=0.45, state='seat',
          note='the seat stone')
    C.add('PH_trunk', fu + 0.4, fv - 2.1, 8, 'hearth', 'lie', sink_cm=4, material_set='wood', note='the log seat')
    # -- the kid pen (fence panels) off the fold's back, and field walls trailing off along the ground
    bu_, bv_ = O[0] + math.cos(far_a) * (rx + 3.4), O[1] + math.sin(far_a) * (ry + 3.4)
    pa = math.degrees(far_a) + 90.0
    Kp = terrace_frame(pa, (bu_, bv_))
    pen = [Kp(-2.2, 0.0), Kp(-2.4, -4.2), Kp(2.3, -4.4), Kp(2.2, 0.0)]
    if all(C.F.road_dist(*p) > 8.0 for p in pen):
        C.nblock += 1
        pblk = 'kidpen_%d' % C.nblock
        for i, (a, b) in enumerate(zip(pen[:-1], pen[1:])):
            Lr = math.hypot(b[0] - a[0], b[1] - a[1])
            m = max(1, int(Lr / 2.5))
            an = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
            for j in range(m):
                if i == 1 and j == m - 1:
                    continue                               # a panel fallen out
                t = (j + 0.5) / m
                rigid(C, C.rng.choice(['MV_Fence_01_V1', 'MV_Fence_01_V3']), a[0] + (b[0] - a[0]) * t,
                      a[1] + (b[1] - a[1]) * t, an - 90.0 + C.rng.uniform(-4, 4), 'kidpen', pblk, 12, mat='wood',
                      state='fence')
        cu_ = sum(p[0] for p in pen) / 4
        cv_ = sum(p[1] for p in pen) / 4
        C.patch('packed_earth', cu_, cv_, pa, 5.0, 4.6, 0.85, order=1)
        C.add('MV_Fence_01_V1', cu_ + 0.3, cv_ - 0.2, pa + 35, 'kidpen', 'lie', sink_cm=3, material_set='wood',
              note='the fallen panel lying in the pen')
    for fw in ([(-11.0, -9.0), (-14.8, -10.6), (-18.6, -12.0), (-22.4, -12.9), (-26.2, -14.4)],
               [(-12.0, 9.0), (-18.0, 10.5), (-23.0, 13.2)]):
        fw = [p for p in fw if C.F.road_dist(*p) > 7.0]
        if len(fw) >= 2:
            C.terrace_wall(fw, gap_every=0.06, name='fieldwall', sink=30)
    # plants the goats could not reach: along the outside of the fold walls, round the hut
    for k in range(9):
        a = a0 + gate + (2 * math.pi - 2 * gate) * (k + 0.5) / 9
        clump(C, O[0] + math.cos(a) * (rx + 1.4), O[1] + math.sin(a) * (ry + 1.4), 0.9, 3, 0.45)
    C.meta.update(frame=dict(ang=math.degrees(a0), O=O))


# ---------------------------------------------------------------------------- S05 the Cart Convoy

S05_LAYOUT = '''
  L verge:            cart (AB)                          the hero dead tree 22 m out
  ===================== road (up-road ->) ==========================================
  R verge:  [last cart + lamp]  [cart, wheel off]  [cart]  [cart]    drawn up nose to tail, facing up-road
       loads left on the beds (bags), crates and a cracked pot on the ground, wheel ruts pulling off the road
'''


def s05(C, sp):
    """The Cart Convoy: five carts drawn up on the verges, nose to tail and facing up-road, left loaded; the
    ruts where they pulled off, the lamp by the last one, one wheel off, loads spilled from one."""
    C.cu, C.cv = (0.0, 6.0)
    # not a parade: bunched, angled as each pulled over, one pulled further off, a gap where one left
    carts = [('BPP_Cart_02', -18.0, 8.6, -13.0), ('AB_Cart_A_texturing', -11.2, 7.3, 5.0),
             ('BPP_Cart_01', -5.6, 7.9, -3.0), ('BPP_Cart_03', 5.2, 9.2, 16.0), ('AB_Cart_A_texturing', 0.8, -8.0, -9.0)]
    pos = []
    for i, (key, u, v, turn) in enumerate(carts):
        qu, qv = road_pt(C, u, v)
        side = 1.0 if v > 0 else -1.0
        v = qv + side * abs(v)
        pos.append((u, v))
        yaw = turn + C.rng.uniform(-3, 3) + (-90.0 if V.long_axis_y(key) else 0.0)
        C.add(key, u, v, yaw, 'carts', 'rest', material_set='wood', block='cart%d' % i,
              note='left loaded' if i != 1 else 'the cart with a wheel off')
        # its ruts: two wheel tracks curving off the road onto the verge, along the way it turned in
        t = math.radians(turn)
        for off in (-0.8, 0.8):
            a = (u - 7.5, qv + side * (5.0 + off * 0.2))
            b = (u - 3.4 * math.cos(t), v - 3.4 * math.sin(t) - side * 0.3 + off)
            c = (u - 1.4 * math.cos(t), v - 1.4 * math.sin(t) + off)
            C.path([a, b, c], 0.35, surface='path', strength=0.75, order=3, lane=False)
        # the load left on the bed: bags, settled by physics onto it
        for k in range(C.rng.randint(2, 3)):
            C.add(C.rng.choice(['MV_jute_bag_0%d' % j for j in range(1, 7)]), u + C.rng.uniform(-0.7, 0.7),
                  v + C.rng.uniform(-0.3, 0.3), C.rng.uniform(0, 360), 'loads', 'rest', stack=True,
                  drop_cm=190 + 30 * k, note='the load left on the cart')
    # the pull-off: packed earth along the right verge under the line, a patch under the lone left cart
    C.patch('packed_earth', -6.5, 9.2, 2, 30.0, 5.2, 0.75, 'capsule', order=1)
    C.patch('packed_earth', pos[4][0], pos[4][1] - 1.0, -9, 8.0, 4.5, 0.7, order=1)
    # the last cart's lamp, standing on the ground by its tail, cold
    C.add('AB_Lamp_B', pos[0][0] - 3.0, pos[0][1] + 1.6, 0, 'loads', 'rest', note='the lamp by the last cart (unlit)')
    # the wheel off cart 1, lying beside it
    C.add('AB_Cart_Wheel', pos[1][0] - 0.3, pos[1][1] + 3.4, 30, 'loads', 'lie', sink_cm=3, material_set='wood',
          note='the wheel that came off')
    # loads spilled from cart 2 onto the verge: bags, a crate, a cracked pot
    cu, cv = pos[2]
    for k, (du_, dv_) in enumerate(((0.8, 2.4), (-0.4, 2.9), (1.9, 2.8), (0.3, 3.8))):
        C.add(C.rng.choice(['MV_jute_bag_07', 'MV_jute_bag_08', 'MV_jute_bag_02']), cu + du_, cv + dv_,
              C.rng.uniform(0, 360), 'loads', 'lie', sink_cm=2)
    C.add('PH_wcrate', cu + 4.4, cv + 3.3, 20, 'loads', 'rest')
    C.add('AB_Box_C', cu + 5.6, cv + 3.0, 55, 'loads', 'rest')
    C.add('AB_Clay_Pot_B', cu + 4.0, cv + 4.3, 0, 'loads', 'rest', roll=90, note='a cracked pot')
    C.add('PH_mcrate', pos[4][0] + 1.4, pos[4][1] - 2.6, 12, 'loads', 'rest')
    C.add('AB_Clay_Pot_A', pos[4][0] - 1.2, pos[4][1] - 2.9, 0, 'loads', 'rest')
    # the verges: dead shrubs and tufts between and behind the carts, thicker away from the road
    for (u, v) in ((-11.8, 11.0), (-4.8, 12.6), (8.8, 10.9), (-20.0, 10.5), (12.0, 9.8), (-3.0, -10.8),
                   (6.5, -11.5), (-9.0, -9.8)):
        clump(C, u, v, 1.4, 5, 0.45)
    # the hero dead tree, 22 m left (skip when the story lane's V3 tree stands)
    C.add('FAB_DeadTree_qlEtl', -6.0, -22.0, 40, 'tree', 'rigid', sink_cm=30, block='tree', material_set='wood',
          state='tree', vis_h=6.0, skip_if_existing_within_m=15, note='hero dead tree (skip if the V3 one exists)')
    C.patch('rubble_dust', -6.0, -22.0, 0, 5.0, 4.0, 0.5, order=1)
    C.meta.update(frame=dict(ang=0.0, O=(0.0, 0.0)))


# ---------------------------------------------------------------------------- S11 the Signal Fire

S11_LAYOUT = '''
  ==== road (steep descent, 8 m right) ====
     path up from the verge -> the signal platform (dry-stone retaining course on its downhill side):
        the fire ring, wood laid ready (never lit), the reserve woodpile against the back,
        the signal pillar at the outer corner (a cloth scrap caught at its foot)
     the watchman's hut above it (one room, broken)                   30 m down-road: the danger board
'''


def s11(C, sp):
    """The Signal Fire: a small terraced platform on the steep slope above the road with the fire laid ready
    and never lit, the reserve woodpile, the signal pillar, the watchman's hut above, the danger board."""
    F = C.F
    O = (0.0, -2.5)
    ang = F.contour_deg(*O)
    K = terrace_frame(ang, O)
    C.cu, C.cv = O
    ru, rv = road_pt(C, *O)
    tw = 1.0 if (K(1, 0)[0] - O[0]) * (ru - O[0]) + (K(1, 0)[1] - O[1]) * (rv - O[1]) > 0 else -1.0   # x toward the road
    fire = K(0.2, -0.4)
    lane = C.path([K(tw * 5.6, -1.0), K(tw * 2.2, -0.9), K(-tw * 1.8, 1.4)], 1.6, strength=0.85)
    verge_link(C, lane[0], width=1.8, strength=0.9, apron=(6.0, 4.0))
    # the platform's retaining course (downhill edge) and the far flank; open to the road and uphill
    C.yard([K(tw * 4.0, -3.1), K(-tw * 3.9, -3.3), K(-tw * 4.1, 0.9)], gap_every=0.1, contents=())
    rigid(C, 'PH_fire_pit', fire[0], fire[1], ang, 'fire', 'fire', 8, scale=1.2, state='hearth',
          note='the signal fire ring, laid and never lit')
    for k, a in enumerate((0, 90, 0, 90)):
        off = -0.18 if k in (0, 1) else 0.18
        du_, dv_ = math.cos(math.radians(ang + a + 90)) * off, math.sin(math.radians(ang + a + 90)) * off
        C.add('MV_Log_05', fire[0] + du_, fire[1] + dv_, ang + a, 'fire', 'rest', scale=0.35, pitch=90.0,
              stack=k >= 2, drop_cm=25 if k >= 2 else 0, material_set='wood', note='wood laid for lighting, never lit')
    C.patch('packed_earth', fire[0], fire[1], ang, 6.5, 5.0, 0.9, order=1)
    # the reserve woodpile against the back (uphill) side: logs lying side by side, two more on top
    wu, wv = K(-tw * 2.1, 2.0)
    for k in range(5):
        off = (k % 3 - 1) * 0.16
        C.add('MV_Log_01', wu + math.cos(math.radians(ang + 90)) * off, wv + math.sin(math.radians(ang + 90)) * off,
              ang, 'woodpile', 'rest', scale=0.55, pitch=90.0, stack=k >= 3, drop_cm=30 if k >= 3 else 0,
              material_set='wood', note='the reserve woodpile')
    # the signal pillar at the platform's outer corner, a cloth scrap caught at its foot
    pu, pv = K(tw * 3.3, -1.9)
    standing_stone(C, 'AB_Pillar_A_03', pu, pv, ang + 8, 1.0, 18, block='pillar', state='pillar',
                   note='the signal pillar')
    C.add('MV_Cloth_02', pu - math.cos(math.radians(ang)) * 0.9 * tw, pv - math.sin(math.radians(ang)) * 0.9 * tw,
          ang + 30, 'pillar', 'lie', scale=0.22, pitch=90.0, sink_cm=1, material_set='cloth',
          note='a cloth scrap caught at the pillar foot')
    # -- the watchman's hut above the platform: one room, its front (door) facing down to the fire
    hx0 = K(-1.5, 4.8)
    if C.fits(C.quads(hx0[0], hx0[1], ang, rect(0, 0, 1, 1)), margin=0.6):
        C.block('WH', hx0[0], hx0[1], ang, [rect(0, 0, 1, 1)], 2, group='houses', collapse_corners=1, lintel_p=0.9)
        C.block_lane['WH'] = lane
    C.door_spurs(width=1.1)
    # -- spill below the platform, plants in the lee of the course and round the hut
    for x in (-3.0, 0.0, 3.0):
        spill(C, *K(x, -3.8), 5, mean_d=1.4)
    clump(C, *K(-tw * 3.0, -2.2), 1.0, 4, 0.4)
    clump(C, *K(tw * 2.2, 4.0), 1.2, 4, 0.4)
    clump(C, *K(-tw * 4.8, 3.0), 1.2, 4, 0.5)
    # -- the danger board, 30 m down-road on the verge, facing up-road
    qu, qv = road_pt(C, 30.0, 0.0)
    bu, bv = 30.0, qv - 6.6
    rigid(C, 'B01_sign02', bu, bv, 90.0, 'board', 'board', 20, mat='wood', state='board',
          note='the first danger board (painted wood), facing up-road')
    bed(C, bu, bv, 0.45, 4)
    C.patch('packed_earth', bu, bv - 0.4, 0, 3.0, 2.2, 0.7, order=1)
    C.meta.update(frame=dict(ang=ang, O=O))


# ---------------------------------------------------------------------------- S21 the Cloud Niche

S21_LAYOUT = '''
  the first hairpin, outer apex: the niche cut into the bank, facing the approaching carrier
     rock face at the back, two broken side walls, a kerb across the mouth with the way in
     inside: a bench stone; three unlit lamps, two clay bowls, the water jar (a travellers' rest, no shrine)
     the way-stone on the apex verge; two bare poles (their cloth strips gone); a dry-stone course retaining
     the bank along the verge, rockfall at its foot
'''


def s21(C, sp):
    """The Cloud Niche: a travellers' rest niche cut into the bank at the outer apex of the first hairpin."""
    F = C.F
    N = (14.2, 6.4)                                          # the niche mouth, in the bank at the apex
    ang = F.contour_deg(*N)
    K = terrace_frame(ang, N)
    C.cu, C.cv = N
    lane = C.path([K(0.0, -3.6), K(0.0, 0.4)], 1.5, strength=0.9)
    verge_link(C, lane[0], width=1.8, strength=0.9, apron=(6.5, 4.5))
    # the back: a rock face set into the bank; the side walls running into the slope; the kerb
    rigid(C, 'PH_rock_face', *K(0.0, 2.6), ang + 180.0, 'niche', 'niche_back', 60, scale=0.9, state='rockface',
          note='the rock the niche is cut into')
    C.nblock += 1
    blk = 'niche_%d' % C.nblock
    for sx in (-1, 1):
        C.wall_line(K(sx * 2.1, -1.3), K(sx * 2.1, 1.7), [C.rng.choice(['low', 'stump'])], blk, 'niche',
                    (-sx * math.cos(math.radians(ang)), -sx * math.sin(math.radians(ang))))
    for x in (-1.35, 1.35):
        rigid(C, 'AB_Broken_Walls', *K(x, -1.7), ang + C.rng.uniform(-6, 6), 'niche', 'kerb', 12, scale=0.7,
              state='kerb')
    rigid(C, 'FAB_TempleStones', *K(-1.15, 0.6), ang + 90.0, 'niche', 'bench', 22, scale=0.6, state='bench',
          note='the bench stone inside the niche')
    for key, x, y in (('AB_Lamp_A', -0.35, -0.9), ('AB_Lamp_C', 0.25, -1.0), ('AB_Lamp_B', 1.25, 0.6)):
        C.add(key, *K(x, y), ang + C.rng.uniform(0, 360), 'niche', 'rest', scale=0.8 if key == 'AB_Lamp_B' else 1.0,
              note='unlit lamp')
    C.add('AB_Clay_Pot_D', *K(0.9, -0.3), 0, 'niche', 'rest', scale=0.7, note='clay bowl')
    C.add('AB_Clay_Pot_D', *K(0.45, 0.9), 0, 'niche', 'rest', scale=0.6, note='clay bowl')
    C.add('AB_Clay_Pot_A', *K(-0.3, 1.25), 0, 'niche', 'rest', note='the water jar')
    C.patch('packed_earth', *K(0.0, -1.0), ang, 5.0, 4.0, 0.95, order=1)
    C.patch('rubble_dust', *K(0.0, 0.8), ang, 3.6, 2.6, 0.7, order=2)
    # the way-stone on the apex verge, the two bare poles
    for p in (K(3.8, -3.2), K(4.6, -2.0)):
        if F.road_dist(*p) >= 5.8:
            standing_stone(C, 'B01_marker01', p[0], p[1], ang, 1.0, 20, block='waystone',
                           note='the way-stone on the apex (inscription later)')
            break
    for x, y in ((-3.9, -2.7), (-5.0, -1.4)):
        p = K(x, y)
        if F.road_dist(*p) >= 5.6:
            rigid(C, 'MV_Fence_01_Log1', p[0], p[1], ang, 'poles', 'poles', 30, scale=1.3, mat='wood', state='post',
                  note='bare pole (its cloth strips missing)')
            bed(C, p[0], p[1], 0.2, 3)
    # the retaining course along the verge on the bank side, rockfall at its foot
    ret = []
    for s_ in np.arange(C.s.road_m - 12.0, C.s.road_m + 28.0, 3.0):
        _, f, r = F.W.frame(s_)
        x = F.W.R.xy(s_) / 100.0
        best = None
        for sgn in (-1, 1):
            q = (x[0] + r[0] * sgn * 6.6, x[1] + r[1] * sgn * 6.6)
            qu, qv = F.site(float(q[0]), float(q[1]))
            gz = F.g(qu, qv)
            if best is None or gz > best[0]:
                best = (gz, (qu, qv))
        qx = F.site(float(x[0]), float(x[1]))
        # only where the verge is a real bank (the ground at the course stands clear above the road)
        ret.append(best[1] if best[0] - F.g(*qx) > 1.2 else None)
    run = [p for p in ret if p is not None and 5.0 < math.hypot(p[0] - N[0], p[1] - N[1]) < 16.0
           and F.road_dist(*p) >= 6.3 and C.point_clear(p[0], p[1], 0.8, 0.6, road_m=6.0)]
    runs, cur = [], []
    for p in run:
        if cur and math.hypot(p[0] - cur[-1][0], p[1] - cur[-1][1]) > 3.8:
            runs.append(cur)
            cur = []
        cur.append(p)
    runs.append(cur)
    for r_ in runs:
        if len(r_) >= 2:
            C.terrace_wall(r_, gap_every=0.15, name='bankwall', sink=25)
            for p in r_[::2]:
                spill(C, p[0], p[1], 3, mean_d=0.8, max_d=2.0)
    clump(C, *K(-3.0, 1.4), 1.0, 4, 0.4)
    clump(C, *K(3.1, 1.0), 1.0, 4, 0.4)
    clump(C, *K(0.0, 4.4), 1.5, 5, 0.3)
    C.meta.update(frame=dict(ang=ang, O=N))


# ---------------------------------------------------------------------------- S23 the Pass Cairn

S23_LAYOUT = '''
  ==== road (7.5 m) ====   a short worn path to the cairn and a trodden ring round it
     the cairn: three big bedded stones, three mid and three small stacked by physics (~2.5 m),
     the stele set upright in its road face; the scree it sheds downhill; stones travellers added round its foot
     three low poles fanned downhill (their cloth strips gone)
'''


def s23(C, sp):
    F = C.F
    C.cu, C.cv = (0.0, 0.0)
    ru, rv = road_pt(C, 0.0, 0.0)
    to_road = face(0, 0, ru, rv)
    tr = (math.cos(math.radians(to_road)), math.sin(math.radians(to_road)))
    dist = math.hypot(ru, rv)
    lane = C.path([(tr[0] * (dist - 6.3), tr[1] * (dist - 6.3)), (tr[0] * 2.2, tr[1] * 2.2)], 1.5, strength=0.85)
    verge_link(C, lane[0], width=1.5, strength=0.85, apron=(5.5, 4.0))
    C.patch('path', 0.0, 0.0, 0, 5.2, 5.2, 0.8, order=2)           # the trodden ring round the cairn
    C.patch('packed_earth', 0.0, 0.0, to_road, 7.5, 6.5, 0.8, order=1)
    for key, a in (('LF_Rock_04', 0), ('LF_Rock_03', 120), ('LF_Rock_05', 240)):
        r = 0.55
        C.add(key, r * math.cos(math.radians(a + 20)), r * math.sin(math.radians(a + 20)), a + 30, 'cairn', 'lie',
              scale=0.56, sink_cm=18, material_set='stone', note='cairn base stone, bedded')
    for k, (key, sc) in enumerate((('LF_Rock_01', 0.55), ('LF_Rock_02', 0.48), ('PH_moss_rock_09', 0.55),
                                   ('LF_Rock_08', 1.7), ('LF_Rock_08', 1.4), ('LF_Rock_07', 2.0))):
        a = C.rng.uniform(0, 360)
        r = 0.25 if k < 3 else 0.08
        C.add(key, r * math.cos(math.radians(a)), r * math.sin(math.radians(a)), C.rng.uniform(0, 360), 'cairn', 'rest',
              scale=sc, stack=True, drop_cm=110 + 45 * k, material_set='stone', note='stacked by physics')
    sx, sy = tr[0] * 1.5, tr[1] * 1.5
    C.add('FAB_TempleStones', sx, sy, to_road + 90.0, 'cairn', 'rigid', scale=0.7, pitch=90.0, sink_cm=25,
          block='stele', material_set='stone', state='stele', vis_h=1.1,
          note='the pass stele, set upright in the road face (I38 later)')
    bed(C, sx, sy, 0.45, 5)
    # stones travellers added round the foot, the scree it sheds downhill
    bed(C, 0.0, 0.0, 1.25, 9, keys=['LF_Rock_08', 'LF_Rock_07', 'AB_Cobble_04'], scale=(0.8, 1.4))
    spill(C, 0.0, 0.0, 12, mean_d=1.6, spread=35, lat=0.9, max_d=5.0)
    du, dv = F.downhill(0.0, 0.0)
    for k, d in enumerate((3.4, 5.3, 7.2)):
        a = math.radians(-24 + 24 * k)
        pu, pv = du * math.cos(a) - dv * math.sin(a), du * math.sin(a) + dv * math.cos(a)
        p = (pu * d, pv * d)
        if F.road_dist(*p) >= 5.6:
            rigid(C, 'MV_Fence_01_Log1', p[0], p[1], 0, 'poles', 'poles', 28, mat='wood', state='post',
                  note='low pole, fanned downhill (its cloth strip gone)')
            bed(C, p[0], p[1], 0.2, 3)
    clump(C, -du * 2.0 + dv * 1.2, -dv * 2.0 - du * 1.2, 1.0, 4, 0.2)
    clump(C, du * 2.6 - dv * 2.0, dv * 2.6 + du * 2.0, 1.0, 3, 0.3)
    C.meta.update(frame=dict(ang=to_road, O=(0.0, 0.0)))


# ---------------------------------------------------------------------------- S18 the Tea Hearth

S18_LAYOUT = '''
  ==== road (9 m) ====   a path up the bank to a small levelled hearth terrace (a dry-stone course holds it)
     ring of fist stones with soot inside, the pot on three stones, the flat stone for the glasses, the folded
     cloth, a log to sit on, brushwood gathered; the hero dead tree leaning over from uphill
'''


def s18(C, sp):
    F = C.F
    O = (0.0, -1.5)
    ang = F.contour_deg(*O)
    K = terrace_frame(ang, O)
    C.cu, C.cv = O
    lane = C.path([K(-0.6, -3.6), K(-0.4, -2.3), K(0.4, -1.5), K(1.4, -1.25)], 1.2, strength=0.85)
    verge_link(C, lane[0], width=1.4, strength=0.85, apron=(5.5, 4.0))
    # the course that holds the hearth terrace, broken where the path steps up through it
    for x0, x1 in ((-5.4, -1.45), (0.65, 4.6)):
        C.terrace_wall([K(x0, -2.4), K(x1, -2.3)], gap_every=0.0, name='hearthterrace', sink=35, record=True,
                       state='drystone')
    C.add('B01_brick01', *K(-0.4, -2.35), ang + 4, 'hearth', 'rigid', block='step', sink_cm=40, material_set='stone',
          ism=True, state='step', note='a step block in the gap')
    C.patch('packed_earth', *K(0.2, 0.2), ang, 6.0, 4.4, 0.95, order=1)
    hu, hv = K(0.3, 0.3)
    for k in range(8):
        a = 2 * math.pi * k / 8 + C.rng.uniform(-0.18, 0.18)
        r = 0.62 * C.rng.uniform(0.9, 1.12)
        C.add('LF_Rock_08', hu + r * math.cos(a), hv + r * math.sin(a), C.rng.uniform(0, 360), 'hearth', 'lie',
              scale=(0.8, 1.0), sink_cm=6, material_set='stone', note='hearth ring stone')
    C.patch('soot', hu, hv, 0, 1.6, 1.5, 0.95, order=4)
    du, dv = F.downhill(hu, hv)
    C.patch('soot', hu + du * 1.3, hv + dv * 1.3, math.degrees(math.atan2(dv, du)), 2.0, 0.9, 0.55, order=4)
    for k in range(3):
        a = 2 * math.pi * k / 3
        C.add('LF_Rock_07', hu + 0.14 * math.cos(a), hv + 0.14 * math.sin(a), C.rng.uniform(0, 360), 'hearth', 'rest',
              note='pot stand')
    C.add('PH_pot', hu, hv, 0, 'hearth', 'rest', stack=True, drop_cm=25, note='kettle stand-in on its three stones')
    rigid(C, 'FAB_TempleStones', *K(1.7, 0.45), ang + 10, 'hearth', 'flatstone', 6, scale=0.3, state='flat',
          note='the flat stone for the glasses')
    C.add('MV_Cloth_02', *K(-1.3, 0.9), ang + 12, 'hearth', 'lie', scale=0.18, pitch=90.0, sink_cm=1,
          material_set='cloth', note='the folded cloth')
    C.add('PH_trunk', *K(0.2, 1.6), ang + 4, 'hearth', 'lie', sink_cm=6, material_set='wood', note='the log to sit on')
    C.add('PH_branches_a', *K(-2.4, 0.2), ang + 60, 'hearth', 'lie', sink_cm=2, material_set='wood', note='brushwood')
    C.add('PH_branches_b', *K(-2.1, -0.5), ang + 20, 'hearth', 'lie', sink_cm=2, material_set='wood')
    C.add('FAB_DeadTree_qlEtl', *K(-2.7, 3.5), ang + 150, 'tree', 'rigid', scale=0.9, sink_cm=30, block='tree',
          material_set='wood', state='tree', vis_h=5.3, note='hero dead tree #4, leaning over the hearth')
    clump(C, *K(-3.3, -1.5), 0.9, 4, 0.4)
    clump(C, *K(3.5, -1.3), 0.9, 4, 0.4)
    clump(C, *K(2.6, 2.4), 1.2, 4, 0.3)
    C.meta.update(frame=dict(ang=ang, O=O))


# ---------------------------------------------------------------------------- S06 the Mountain Seat

S06_LAYOUT = '''
  ==== road (9 m) ====   a trodden patch and a short path from the verge
     [slab bench on two bedded blocks, facing out over the valley]  backrest stone behind, carafe beside
     on the lip of an old field terrace (a dry-stone course below it); hero dead tree rlthg framing the left
'''


def s06(C, sp):
    F = C.F
    yaw = -101.0                                            # the bench faces out over the valley (as V1)
    C.cu, C.cv = (0.0, 0.0)
    fx, fy = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
    sx, sy = -fy, fx
    lane = C.path([(-fx * 2.8 + sx * 1.8, -fy * 2.8 + sy * 1.8), (fx * 1.2 + sx * 1.6, fy * 1.2 + sy * 1.6)], 1.4,
                  strength=0.85)
    verge_link(C, lane[0], width=1.5, strength=0.85, apron=(6.0, 4.0))
    for s_ in (-1, 1):
        rigid(C, 'AB_Pillar_A_04', sx * 0.62 * s_, sy * 0.62 * s_, yaw, 'bench', 'bench', 10, scale=0.6,
              state='bench_block')
    C.add('FAB_TempleStones', 0.0, 0.0, yaw + 90.0, 'bench', 'rest', scale=0.72, stack=True, drop_cm=60,
          material_set='stone', note='the slab seat, settled onto its two blocks')
    rigid(C, 'B01_monument01', -fx * 0.95, -fy * 0.95, yaw + 90.0, 'bench', 'backrest', 14, scale=0.45,
          state='backrest', note='backrest stone (I09 later)')
    bed(C, -fx * 0.95, -fy * 0.95, 0.4, 4)
    C.add('MV_carafe_02', sx * 1.35 + fx * 0.3, sy * 1.35 + fy * 0.3, 0, 'bench', 'rest', scale=0.7)
    C.patch('packed_earth', fx * 0.6, fy * 0.6, yaw + 90.0, 4.4, 3.2, 0.95, order=1)
    C.patch('path', fx * 0.9, fy * 0.9, yaw + 90.0, 2.4, 1.3, 0.8, order=2)
    # the old field terrace below the seat: a dry-stone course along the contour, slumped in places
    c0 = (fx * 3.6, fy * 3.6)
    K = terrace_frame(F.contour_deg(*c0), c0)
    pts = V.contour_k(C, K, F.g(*c0), -10.0, 10.0, -3.0, 3.0, step=3.0)
    for run in V.runs_clear(C, pts, road_m=6.5):
        C.terrace_wall(run, gap_every=0.18, name='terrace', sink=38)
    C.add('FAB_DeadTree_rlthg', -7.0, -6.0, 40, 'tree', 'rigid', sink_cm=35, block='tree', material_set='wood',
          state='tree', vis_h=8.4, note='hero dead tree #2, framing the left of the view')
    clump(C, sx * 1.2 - fx * 0.3, sy * 1.2 - fy * 0.3, 0.6, 3, 0.2)
    clump(C, -sx * 1.3 - fx * 0.4, -sy * 1.3 - fy * 0.4, 0.6, 3, 0.2)
    clump(C, -7.0, -6.0, 1.6, 5, 0.4)
    C.meta.update(frame=dict(ang=yaw, O=(0.0, 0.0)))


# ---------------------------------------------------------------------------- markers: S02, S04, S09, S22

S02_LAYOUT = '''
  ==== road ====
        |  the way-stone set in the verge, leaning 8 deg to the road, packing stones at its foot, pebbles on top;
           the trodden verge where travellers stopped (ground only); nothing else within 20 m
'''


def s02(C, sp):
    C.cu, C.cv = (0.0, 0.0)
    P = (0.0, 0.6)
    ru, rv = road_pt(C, *P)
    to_road = face(P[0], P[1], ru, rv)
    standing_stone(C, 'B01_marker01', P[0], P[1], to_road, 1.25, 24, lean=8.0, lean_dir=to_road,
                   note='the way-stone, leaning 8 deg to the road (INSCR may swap it for SM_Stele_WayStone_A)')
    pebble_cap(C, P[0], P[1], 3, top_drop=120.0)
    C.patch('packed_earth', P[0] + (ru - P[0]) * 0.3, P[1] + (rv - P[1]) * 0.3, to_road + 90, 4.2, 3.0, 0.8, order=1)
    C.patch('path', P[0] + 0.1, P[1] - 0.4, to_road + 90, 1.8, 1.4, 0.7, order=2)
    clump(C, P[0] + 0.4, P[1] + 0.7, 0.5, 3, 0.0, avoid=0.0)
    clump(C, P[0] - 0.6, P[1] + 0.6, 0.4, 2, 0.0, avoid=0.0)
    C.meta.update(frame=dict(ang=to_road, O=P))


S04_LAYOUT = '''
  ==== road (aims at the mountain for 110 m) ====
   [left stone, V2 story-owned]  a pebble cairn and the flower at its foot, trodden ground where people stood
   [right stone, V2 story-owned] a pebble cairn at its foot, trodden ground
   nothing tall: the sightline between the stones (the mast crown, G03) is the dressing
'''


def s04(C, sp):
    C.cu, C.cv = (1.4, 0.0)
    for (u, v) in ((1.4, -9.0), (1.4, 7.1)):
        qu, qv = road_pt(C, u, v)
        side = 1.0 if v > qv else -1.0
        v = qv + side * abs(v)
        bed(C, u, v, 0.28, 3, keys=['LF_Rock_08'], scale=(1.0, 1.2))
        pebble_cap(C, u, v, 4, top_drop=40.0, group='cairn', note='a pebble cairn at the foot of the promise stone')
        C.patch('packed_earth', u - 0.6, v - side * 0.6, 0, 4.5, 3.4, 0.85, order=1)
        C.patch('path', u - 0.8, (qv + side * 5.2 + v) / 2.0, 90.0, max(1.0, abs(v - qv) - 5.2), 1.2, 0.55, 'capsule',
                order=2)
        clump(C, u + 1.2, v + side * 1.0, 0.6, 3, 0.0, avoid=0.0)
        if side < 0:
            C.add('LF_Flowers_01', u - 0.6, v + 0.5, 195, 'flower', 'rest', scale=0.35,
                  note='desaturated MI: the one last living thing in the valley')
    C.meta.update(frame=dict(ang=0.0, O=(0.0, 0.0)))


S09_LAYOUT = '''
  ==== road ====   the old caravan track leaves the road here, climbing away past the route-stone and fading
     the route-stone set in the verge, packing stones; two emptied flat bags by it; the bearer's place (the
     animal skeleton + pack saddle: MISSING, a slot only); trail stones up the track; dead shrubs in the lee
'''


def s09(C, sp):
    F = C.F
    C.cu, C.cv = (0.0, 0.0)
    track = [(-9.0, -1.0), (-4.2, 0.6), (1.8, 2.2), (6.6, 5.4), (10.6, 10.2), (13.6, 16.8), (15.4, 24.0)]
    track = [p for p in track if F.road_dist(*p) >= 5.8]
    lane = C.path(track[:4], 1.7, strength=0.85, wander=0.3)
    C.path(track[3:5], 1.5, strength=0.55, wander=0.4)
    C.path(track[4:], 1.3, strength=0.32, wander=0.5)             # the old route fades out up the slope
    verge_link(C, lane[0], width=1.8, strength=0.85, apron=(6.0, 4.5))
    ru, rv = road_pt(C, 0.0, -0.4)
    standing_stone(C, 'B01_marker01', 0.0, -0.4, face(0, -0.4, ru, rv), 1.0, 20, block='routestone',
                   note='the caravan-route stone')
    for key, (u, v), a in (('MV_jute_bag_07', (1.9, -1.3), 40), ('MV_jute_bag_09', (2.8, -0.3), 110)):
        C.add(key, u, v, a, 'bags', 'lie', sink_cm=2, note='an emptied flat bag')
    C.patch('rubble_dust', 3.8, -2.0, 30, 3.2, 1.8, 0.45, order=1)
    C.meta['missing'] = dict(slot=(3.8, -2.0), what='animal skeleton (camel) + pack saddle: MISSING, bought later')
    for (u, v) in ((6.9, 6.8), (13.9, 14.8)):
        if F.road_dist(u, v) >= 6.0:
            standing_stone(C, 'B01_marker01', u, v, C.rng.uniform(0, 360), 0.55, 12, block='trail_%d' % int(u),
                           note='trail stone of the old route')
    clump(C, -1.2, -1.5, 0.9, 5, 0.6)
    clump(C, 5.6, -0.6, 1.2, 5, 0.6)
    clump(C, 11.8, 7.2, 1.4, 5, 0.5)
    clump(C, 10.2, 13.8, 1.2, 4, 0.5)
    clump(C, 3.0, 5.2, 1.3, 4, 0.5)
    spill(C, 0.0, -0.4, 6, mean_d=1.2)
    C.meta.update(frame=dict(ang=0.0, O=(0.0, 0.0)))


S22_LAYOUT = '''
  inner apex of the second hairpin: one knee-high rough stone set leaning into the slope, three pebbles on top,
  packing stones, a small trodden patch; (worn sandals + cloth tie: MISSING)
'''


def s22(C, sp):
    F = C.F
    P = (10.4, 7.0)
    C.cu, C.cv = P
    du, dv = F.downhill(*P)
    up = math.degrees(math.atan2(-dv, -du))
    C.add('PH_moss_rock_09', P[0], P[1], up, 'stone', 'rigid', scale=0.5, pitch=78.0, sink_cm=20, block='vow',
          material_set='stone', state='stone', vis_h=0.62,
          note='the vow-stone: knee-high, set leaning into the slope (I37 scratched later)')
    bed(C, P[0], P[1], 0.32, 5)
    pebble_cap(C, P[0], P[1], 3, top_drop=80.0)
    C.patch('packed_earth', P[0] + du * 1.0, P[1] + dv * 1.0, up + 90, 2.6, 2.0, 0.75, order=1)
    clump(C, P[0] - dv * 0.9, P[1] + du * 0.9, 0.5, 3, 0.0, avoid=0.0)
    C.meta.update(frame=dict(ang=up, O=P))


SMALL_SITES = {
    'S03_GoatFold': dict(archetype='fold', recipe=s03, seed='S03v2', layout=S03_LAYOUT, burnt=1, mud=1, radius_m=34),
    'S05_CartConvoy': dict(archetype='convoy', recipe=s05, seed='S05v2', layout=S05_LAYOUT, burnt=0, mud=0,
                           radius_m=40),
    'S11_SignalFire': dict(archetype='signal_post', recipe=s11, seed='S11v2', layout=S11_LAYOUT, burnt=0, mud=0,
                           radius_m=36),
    'S21_CloudNiche': dict(archetype='rest_niche', recipe=s21, seed='S21v2', layout=S21_LAYOUT, burnt=0, mud=0,
                           radius_m=22, notes='Content rule: no shrine, votive tablets, bell or prayer flags.'),
    'S23_PassCairn': dict(archetype='cairn', recipe=s23, seed='S23v2', layout=S23_LAYOUT, burnt=0, mud=0, radius_m=15),
    'S18_TeaHearth': dict(archetype='hearth', recipe=s18, seed='S18v2', layout=S18_LAYOUT, burnt=0, mud=0, radius_m=15),
    'S06_MountainSeat': dict(archetype='seat', recipe=s06, seed='S06v2', layout=S06_LAYOUT, burnt=0, mud=0,
                             radius_m=15),
    'S02_WayStone': dict(archetype='marker', recipe=s02, seed='S02v2', layout=S02_LAYOUT, burnt=0, mud=0, radius_m=20),
    'S04_PromiseStones': dict(archetype='marker', recipe=s04, seed='S04v2', layout=S04_LAYOUT, burnt=0, mud=0,
                              radius_m=15),
    'S09_CaravanRoute': dict(archetype='marker', recipe=s09, seed='S09v2', layout=S09_LAYOUT, burnt=0, mud=0,
                             radius_m=30),
    'S22_VowStone': dict(archetype='marker', recipe=s22, seed='S22v2', layout=S22_LAYOUT, burnt=0, mud=0, radius_m=12),
}
