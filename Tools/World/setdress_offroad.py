"""Layer 2 of the set-dressing plan: the OFF-ROAD points of interest (author, 2026-09-28:
"I don't just want set dressing along the road, I also want interest points OUTSIDE it").

15 POIs, 250-1,500 m from the road, placed by Tools/World/select_offroad_pois.py (terrain fit +
sightlines from the carrier eye) and dressed here. Six are REACHABLE: each gets a marked spur
from the road (way-markers every ~70 m) that the proposed tether change follows, and an
exploration zone around the POI. The rest are view-only landmarks.

Frames: 'road' = u points away from the nearest road point; 'downhill' = u points down the local
slope (rows along u step down, v runs along the contour); 'valley' = u points downstream along a
dry valley floor (a dam or a bridge spans v).
"""
import json
import math
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
LOCATIONS = os.path.join(HERE, 'offroad_poi_locations.json')
SPUR_MARK_M = 70.0
SEARCH_M = 30.0        # the centre may move this far to flatter ground (sightlines barely change)
IDS = {'O01': 'LowVoicePost', 'O02': 'Refinery', 'O03': 'BrokenBridge', 'O04': 'Airship', 'O05': 'CliffDwellings',
       'O06': 'OldDam', 'O07': 'Observatory', 'O08': 'WindPumps', 'O09': 'CartGraveyard', 'O10': 'ChemistWorkshop',
       'O11': 'MirrorHill', 'O12': 'OldRelay', 'O13': 'TerraceOrchards', 'O14': 'GranaryHamlet', 'O15': 'GreatQuarry'}
ZONE_PAD_M = 25.0


def downhill_dir(W, x, y, r=25.0):
    gx = (W.ground(x + r, y) - W.ground(x - r, y)) / (2 * r)
    gy = (W.ground(x, y + r) - W.ground(x, y - r)) / (2 * r)
    n = math.hypot(gx, gy)
    return (np.array([-gx / n, -gy / n]) if n > 1e-4 else np.array([1.0, 0.0])), math.degrees(math.atan(n))


def valley_dir(W, x, y, r=60.0):
    """Downstream direction of a valley floor: the lowest of 16 directions at r metres."""
    best, bd = None, None
    for k in range(16):
        a = 2 * math.pi * k / 16
        z = W.ground(x + r * math.cos(a), y + r * math.sin(a))
        if best is None or z < best:
            best, bd = z, a
    return np.array([math.cos(bd), math.sin(bd)])


def spur(W, x, y, road_m):
    """A foot/cart spur from the road to the POI: a straight line or one dogleg, lowest max grade."""
    def profile(pts):
        seg = []
        for a, b in zip(pts[:-1], pts[1:]):
            n = max(2, int(np.linalg.norm(b - a) / 10.0))
            for t in np.linspace(0, 1, n, endpoint=False):
                seg.append(a + (b - a) * t)
        seg.append(pts[-1])
        seg = np.array(seg)
        z = np.array([W.ground(*p) for p in seg])
        d = np.linalg.norm(np.diff(seg, axis=0), axis=1)
        g = np.abs(np.diff(z)) / np.maximum(d, 1e-3)
        # grade over 20 m windows
        g20 = np.convolve(g, np.ones(2) / 2, mode='same')
        return seg, z, float(d.sum()), float(g20.max()) * 100.0
    b = np.array([x, y], float)
    best = None
    s0 = road_m
    for js in np.arange(max(0.0, s0 - 400.0), min(W.R.length, s0 + 401.0), 50.0):
        a = np.asarray(W.frame(js)[0], float)
        for off in (0, -80, 80, -160, 160, -260, 260, -400, 400, -550, 550):
            mid = (a + b) / 2
            dirv = (b - a) / np.linalg.norm(b - a)
            mid = mid + np.array([-dirv[1], dirv[0]]) * off
            pts = [a, b] if off == 0 else [a, mid, b]
            seg, z, L, g = profile([np.asarray(p) for p in pts])
            score = g + 0.03 * L
            if best is None or score < best[0]:
                best = (score, pts, seg, z, L, g, js)
    _, pts, seg, z, L, g, js = best
    return dict(junction_road_m=round(float(js)), waypoints_cm=[[round(float(p[0]) * 100, 1), round(float(p[1]) * 100, 1)] for p in pts],
                length_m=round(L), max_grade_pct=round(g), samples=seg, z=z)


def build_sites(W, Site):
    locs = {p['id']: p for p in json.load(open(LOCATIONS, encoding='utf8'))['pois']}
    out = []

    def mk(pid, frame, role, story, decay, style, radius, layout, missing, name_roll=None, tape=None):
        L = locs[pid]
        s = Site(pid + '_' + IDS[pid],
                 L['name'], L['nearest_road_m'], 0.0, 'off-road POI', role, story, decay, style, 50 + int(pid[1:]),
                 radius, layout)
        s.layer = 'offroad'
        s.xy = (L['x_m'], L['y_m'])
        s.frame = frame
        s.search_m = 0.0 if frame == 'downhill' or pid in ('O05', 'O11') else SEARCH_M
        s.poi = dict(L, missing=missing, name_roll=name_roll, tape=tape, exploration_zone_radius_m=radius + ZONE_PAD_M)
        out.append(s)
        return s

    AB_BRICKS = ['AB_Brick_A', 'AB_Brick_A1', 'AB_Brick_A2', 'AB_Brick_A3', 'AB_Brick_A4', 'AB_Brick_A5']
    BAGS = ['MV_jute_bag_%02d' % i for i in range(1, 11)]
    POTS = ['AB_Clay_Pot_A', 'AB_Clay_Pot_B', 'AB_Clay_Pot_C', 'AB_Clay_Pot_D']
    ROCKS = ['LF_Rock_05', 'LF_Rock_06', 'LF_Rock_07', 'LF_Rock_08']

    # O01 the Low Voice post -------------------------------------------------------------------
    s = mk('O01', 'road', 'lore + tape pickup + story payoff (reachable)',
           "the valley radio's own room: the Keeper's last night on air was broadcast from here; its signal reaches the road below",
           1, 'mud-brick post office + a copper-and-timber mast (Tripo), radio desk', 30, '''
   (road ~320 m, below)
        yard wall (wall04)     [post office: mudbrick_house]  [back room: mudbrick_house x0.7]
           notice board   mail sacks, crates      radio desk, chair, lantern, log box (inside the back room)
                         small mast (relay_tower x0.45, 12 m) with guy ropes     way-marker at the gate
''', missing=['radio desk set (T2_radio_desk, or a bought transceiver + headphones + log book)',
              'the tape object (a gameplay pickup, later)'],
           name_roll='"the Low Voice" (later)', tape='the Keeper\'s own studio log (later)')
    s.add('T2_mudbrick_house', 0, 0, 'face_road', 1.0, 'post_office', landmark=True)
    s.add('T2_mudbrick_house', 2, 8.5, 'face_road', 0.7, 'back_room')
    s.add('T2_radio_desk', 2.4, 8.3, 'face_road', 1.0, 'back_room', note='inside the back room, against the far wall')
    s.add('AB_Chair_A_low', 1.4, 8.3, 'face_road', 1.0, 'back_room')
    s.add('PH_lantern', 2.4, 8.0, 0, 1.0, 'back_room', stack=True, drop_cm=120)
    s.add('MV_box_05', 3.2, 9.4, 20, 1.0, 'back_room')
    s.add('T2_relay_tower', 8, 6, 0, 0.45, 'mast', landmark=True, note='12 m copper-and-timber mast: the silhouette from the road')
    for a in (0, 120, 240):
        s.add('MV_Fence_01_Log1', 8 + 6 * math.cos(math.radians(a)), 6 + 6 * math.sin(math.radians(a)), 0, 1.0, 'mast',
              note='guy-rope stake')
    s.run('B01_wall04', [(-8, -8), (-8, 8), (-2, 14)], 'yard', 1.0, skip={2})
    s.add('MV_Fence_01_Log1', -9, -1, 0, 1.6, 'yard')
    s.add('B01_sign02', -9, -1, 'face_road', 0.8, 'yard', note='the post board (a painted name, later an inscription)')
    s.pile(BAGS, 8, 4, -4, 1.2, 'mail', note='mail sacks, never collected')
    s.pile(['MV_box_01', 'MV_box_02', 'PH_wcrate'], 3, 5.5, -5, 0.8, 'mail')
    s.add('T2_way_marker', -14, 0, 'face_road', 1.0, 'gate')

    # O12 the old relay ------------------------------------------------------------------------
    s = mk('O12', 'road', 'lore + view point (view-only)',
           'the first High Voice: a smaller relay the valley built before the mast on the summit; dead and leaning',
           3, 'Tripo relay tower (a predecessor), stone hut, rubble', 30, '''
     [relay tower, 26 m, leaning 7 deg]   fallen upper section lying downhill
        roofless relay hut (wall03)   rubble heaps   fallen pillar parts
''', missing=['T2_relay_tower (fallback: a stacked 10 m pillar)'], name_roll='"the Old Relay" (later)')
    s.add('T2_relay_tower', 0, 0, 0, 1.0, 'tower', roll=7, landmark=True)
    s.add('T2_relay_tower', 14, 3, 30, 0.45, 'tower', roll=86, note='the fallen upper section')
    s.add('B01_wall03', -8, 6, 'face_road', 1.0, 'hut')
    for u, v in ((6, -6), (-6, -8), (10, 10)):
        s.add('B01_rubble01', u, v, s.rng.uniform(0, 360), 1.2, 'rubble')
    s.add('AB_Pillar_Part', 4, 9, 40, 1.0, 'rubble')
    s.add('AB_Pillar_Part', -3, -12, 110, 1.0, 'rubble')
    s.scatter(AB_BRICKS, 20, 0, 0, 14, 'rubble', (0.9, 1.4))

    # O02 the hilltop biofuel refinery ---------------------------------------------------------
    s = mk('O02', 'road', 'landmark + lore (view-only; the works\' big sister, on the hill above the basin)',
           'where the valley made its biofuel; the still and the columns stand dead on the skyline above the basin',
           2, 'riveted iron, copper and clay: distillation columns, stills, vats, pipe manifolds (steampunk)', 45, '''
                 [column 22 m]   [column 18 m]
        still  still  still        pipe manifolds between the stills and the vats
     ring of clay vats (tank01 x12)      gutted hall (BrokenStructer) + U walls      crane
        hand-cart track (rail01)   barrels   rubble heaps
''', missing=['T2_distillation_column, T2_biofuel_still, T2_pipe_manifold (Tripo, in production)',
              'riveted pipe runs (pipe01 is a single elbow; a straight riveted pipe is missing)'])
    s.add('T2_distillation_column', 0, 0, 0, 1.0, 'columns', landmark=True)
    s.add('T2_distillation_column', 7, 3, 20, 0.8, 'columns', landmark=True)
    for i in range(3):
        s.add('T2_biofuel_still', -8 + 6 * i, 9, 'face_road', 1.0, 'stills')
        s.add('T2_pipe_manifold', -5 + 6 * i, 5, 0, 1.0, 'pipes')
    s.ring('B01_tank01', 12, -14, -8, 6.0, 'vats', 1.0)
    for i in range(6):
        s.add('B01_pipe01', -2 + 3 * i, -3 + (i % 2), s.rng.uniform(0, 360), 1.0, 'pipes', verdict_check=True)
    s.add('B01_pump01', 12, -6, 'face_road', 1.0, 'pipes', verdict_check=True)
    s.add('AB_BrokenStructer', 18, 12, 'face_road', 1.0, 'hall', landmark=True)
    s.hut('AB_300x400_Mid_Damaged_A', 22, -8, 9, 6, 0, 'hall', broken={1, 5})
    s.add('B01_crane01', 10, 16, 'face_road', 1.0, 'hall')
    s.run('B01_rail01', [(-20, 14), (10, 20)], 'track', 1.0, verdict_check=True)
    s.pile(['MV_barrel_01', 'MV_barrel_02', 'PH_barrel'], 6, -20, 6, 1.6, 'barrels')
    for u, v in ((-24, -18), (26, 20), (0, -20)):
        s.add('B01_rubble01', u, v, s.rng.uniform(0, 360), 1.3, 'rubble')

    # O03 the broken bridge over the dry river -------------------------------------------------
    s = mk('O03', 'valley', 'view point + lore (reachable by a spur)',
           'the old caravan road crossed the river here before the valley road was cut; the river is gone, the bridge broke',
           3, 'bazaar stone: arched bridge spans, abutment arches, a dry bed of stones', 35, '''
    (the dry river runs along u, downstream ->)
       abutment arch01        span bridge01 ===    GAP (fallen)    === span bridge01        abutment arch01
          fallen span pieces and rubble in the bed; river stones; dead trunks caught against the piers
''', missing=['a broken bridge-end piece (a snapped span); stand-in: rubble01 + pillar parts'])
    s.add('B01_bridge01', 0, -9, 90, 1.0, 'span', landmark=True, note='span across the valley (v)')
    s.add('B01_bridge01', 0, 11, 90, 1.0, 'span', landmark=True)
    s.add('B01_arch01', 0, -16, 90, 1.0, 'abutment')
    s.add('B01_arch01', 0, 18, 90, 1.0, 'abutment')
    s.add('B01_rubble01', 1.5, 1, 30, 1.4, 'fallen')
    s.add('B01_rubble01', -2, 3, 140, 1.1, 'fallen')
    s.add('AB_Pillar_Part', 3, -1, 70, 1.2, 'fallen')
    s.add('B01_brick01', -1, 5, 20, 1.0, 'fallen')
    s.scatter(ROCKS + ['LF_Rock_01', 'LF_Rock_03'], 26, 0, 0, 24, 'riverbed', (0.4, 1.0))
    s.add('PH_trunk', 5, -4, 80, 1.0, 'riverbed', note='caught against a pier')
    s.add('PH_trunk_02', -6, 8, 100, 1.0, 'riverbed')

    # O04 the downed airship --------------------------------------------------------------------
    s = mk('O04', 'road', 'landmark + lore (view-only)',
           'a brass-and-canvas airship that brought the last supplies, or tried to leave; its frame lies across the plain',
           2, 'retrofuturist: brass ribs, torn canvas, a gondola, engine wheels', 45, '''
      nose ->  ribs (arched beams, 9)  <- tail          torn canvas draped over the ribs
           gondola (cart) on its side   two engine wheels   spilled crates and ropes
''', missing=['T2_airship_hull (a 60 m brass rib frame + gondola: NOT in the Tripo list; request it)',
              'brass engine/propeller pieces'])
    s.add('T2_airship_hull', 0, 0, 20, 1.0, 'hull', landmark=True, note='replaces the stand-in ribs when it exists')
    for i in range(9):
        s.add('MV_Barn_roof_bean', 0, -20 + 5 * i, 90, 1.0, 'standin_ribs', roll=90 + s.rng.uniform(-25, 25),
              pitch=s.rng.uniform(-15, 15), note='stand-in rib (7.3 m beam stood as an arch leg); remove when the hull exists')
    s.add('AB_Tent_A', 2, -6, 20, 1.3, 'canvas', note='torn canvas over the ribs')
    s.add('AB_Damaged_Tent_A', -2, 8, 60, 1.6, 'canvas')
    s.add('AB_Cart_A_texturing', 7, 2, 0, 1.2, 'gondola', pitch=70, note='gondola stand-in (long along Y: the tip is a pitch; LANE_SD)')
    s.add('B01_wheel01', 9, -8, 30, 0.6, 'engines', roll=80)
    s.add('B01_wheel01', 8, 12, 150, 0.6, 'engines', roll=75)
    s.pile(['PH_mcrate', 'PH_wcrate', 'MV_box_01'], 6, 11, 4, 2.0, 'cargo')
    s.add('MV_Rope_Woven', 4, -14, 30, 1.0, 'cargo')

    # O05 the cliff dwellings -------------------------------------------------------------------
    s = mk('O05', 'downhill', 'landmark + lore (view-only)',
           'homes cut into the cliff above the upper road; ladders and a rope bridge between them',
           2, 'stone facades set into the rock: windows, arches, walls; ladders and a rope footbridge', 35, '''
   (u = down the cliff; rows step up the face)
    row 3:   window01    arch01
    row 2:   wall04   window01   arch01   wall04     rope footbridge between rows 2 and 3
    row 1:   arch01   window01   wall04               ladders (logs) leaning on the face; jars on the ledges
''', missing=['T2_rope_footbridge (Tripo, in production)', 'rope ladders'])
    rows = [(0, ['B01_arch01', 'B01_window01', 'B01_wall04']), (-6, ['B01_wall04', 'B01_window01', 'B01_arch01', 'B01_wall04']),
            (-12, ['B01_window01', 'B01_arch01'])]
    for u, keys in rows:
        for i, k in enumerate(keys):
            s.add(k, u, -8 + 6 * i, 'face_downhill', 1.0, 'facades', landmark=(u == -6))
    s.add('T2_rope_footbridge', -9, 2, 90, 1.0, 'bridge')
    for i in range(3):
        s.add('MV_Log_02', 2 - 6 * i, -4 + 5 * i, 'face_downhill', 1.0, 'ladders', pitch=-70,
              note='ladder stand-in leaning on the face')
    s.scatter(['T2_jars'] + POTS, 8, -6, 0, 10, 'ledges', (0.8, 1.1))

    # O06 the old dam ---------------------------------------------------------------------------
    s = mk('O06', 'valley', 'lore + view point (reachable by a spur)',
           'the dam that fed the Heron Pools: the reservoir is a cracked bowl, the sluices stand open over nothing',
           2, 'bazaar stone dam wall with timber sluices, a water wheel and stone channels', 45, '''
    reservoir bed (dry, stumps)          <- upstream
    ======== dam wall (Fort_Wall_Mid x10) ==== sluice gate01 == sluice gate01 ====
         winch posts (support01)     water wheel (dead)     crane
                 stone channels (channel01) run downstream toward the basin ->
''', missing=['cracked-mud decal for the reservoir bed', 'a dam spillway piece'])
    s.run('AB_Fort_Wall_Mid', [(0, -16), (0, 16)], 'dam', 1.0, skip={5, 6})
    s.add('B01_gate01', 0, 0.3, 90, 1.6, 'sluices')
    s.add('B01_gate01', 0, 3.3, 90, 1.6, 'sluices')
    s.add('B01_support01', 1.5, -1.6, 0, 1.0, 'sluices')
    s.add('B01_support01', 1.5, 5.2, 0, 1.0, 'sluices')
    s.add('T2_water_wheel', 8, -6, 90, 1.0, 'mill')
    s.add('MV_Wm_wheel_support', 8, -8, 0, 1.0, 'mill')
    s.run('B01_channel01', [(4, 1.8), (40, 2.5)], 'channels', 1.0, ism=True)
    s.add('B01_crane01', 3, 10, 0, 1.0, 'dam')
    s.scatter(['PH_stump_01', 'PH_stump_02', 'FAB_Stump'], 10, -22, 0, 16, 'reservoir', (0.9, 1.2))
    s.scatter(ROCKS, 20, -18, 0, 20, 'reservoir', (0.5, 1.0))

    # O07 the observatory -----------------------------------------------------------------------
    s = mk('O07', 'road', 'landmark + view point (view-only)',
           'the valley kept a star-watcher on the hill above the dock: a brass dome on a stone tower, its shutters open',
           2, 'stone tower + brass dome and telescope (retrofuturist)', 25, '''
       [tower house03 x1.1]  + brass dome on top, shutters open; telescope inside
        enclosure of fort-wall pieces, stair, two pillars (instrument stands)
''', missing=['T2_brass_dome and T2_brass_telescope (NOT in the Tripo list; request them)'],
           name_roll='"the Star-Watch" (later)')
    s.add('B01_house03', 0, 0, 'face_road', 1.1, 'tower', landmark=True)
    s.add('T2_brass_dome', 0, 0, 'face_road', 1.0, 'tower', attach=True, z_offset_cm=1000, landmark=True)
    s.add('T2_brass_telescope', 0, 0, 'face_road', 1.0, 'tower', attach=True, z_offset_cm=1050)
    s.ring('AB_Fort_Wall_Mid', 10, 0, 0, 11.0, 'enclosure', 1.0, gaps={2, 3, 7}, face=90)
    s.add('B01_pillar01', 6, -5, 0, 0.8, 'instruments')
    s.add('B01_pillar01', 6, 5, 0, 0.8, 'instruments')
    s.add('MV_Terrace_Stairs_02', -4, 4, 'face_road', 1.0, 'tower')

    # O08 the wind-pump ridge -------------------------------------------------------------------
    s = mk('O08', 'road', 'landmark (view-only)',
           'wind pumps that lifted water to the upper fields; a line of dead sails on the ridge',
           1, 'timber and riveted-iron wind pumps (steampunk), troughs', 90, '''
   along the ridge (v):  pump -- 40 m -- pump -- 40 m -- pump -- 40 m -- pump -- 40 m -- pump
        a trough (channel01) at each foot; fence posts
''', missing=['T2_wind_pump (NOT in the Tripo list; request it). Fallback: a tall stone pillar only'])
    for i in range(5):
        v = -80 + 40 * i
        s.add('T2_wind_pump', s.rng.uniform(-6, 6), v, s.rng.uniform(0, 360), 1.0, 'pumps', landmark=True)
        s.add('B01_channel01', 3, v + 3, 0, 0.7, 'troughs')
        s.add('MV_Fence_01_Log1', -3, v - 3, 0, 1.3, 'troughs')

    # O09 the caravan graveyard -----------------------------------------------------------------
    s = mk('O09', 'road', 'lore (reachable by a spur); later a tape pickup',
           'where the carts that could go no further were left in rows; two old carrier cradles among them',
           2, 'MedievalVillage and AshesOfBazaar carts, wheels, tarps, sacks', 45, '''
     rows of carts (noses to the mountain), some tipped, some without wheels
     wheels stacked and scattered      two carrier cradles (Tripo) in the last row
     a way-marker at the entrance, sacks and crates between the rows
''', missing=['T2_carrier_cradle (Tripo, in production)'], tape='a carter\'s tally (later)')
    carts = ['BPP_Cart_01', 'BPP_Cart_02', 'BPP_Cart_03', 'BPP_Cart_04', 'BPP_Cart_05', 'MV_cart_01', 'MV_cart_02',
             'AB_Cart_A_texturing']
    for row in range(3):
        for i in range(5):
            k = carts[(row * 5 + i) % len(carts)]
            roll = 75 if (row + i) % 4 == 3 and k.startswith(('MV', 'AB')) else 0
            # MV/AB carts are long along Y: tipping one on its side is a pitch (roll stood it on end; LANE_SD)
            s.add(k, -12 + 12 * row, -16 + 8 * i, 90 if k == 'AB_Cart_A_texturing' else 0, 1.0, 'rows_%d' % row, pitch=roll)
    s.add('T2_carrier_cradle', 24, -6, 0, 1.0, 'cradles', note='an older carrier cradle, empty')
    s.add('T2_carrier_cradle', 24, 2, 5, 1.0, 'cradles')
    s.scatter(['AB_Cart_Wheel', 'MV_cart_01_wheels', 'MV_cart_02_wheels'], 8, 6, 18, 6, 'wheels', (1.0, 1.0))
    s.pile(BAGS, 8, 0, -22, 1.6, 'sacks')
    s.add('T2_way_marker', -22, 0, 'face_road', 1.0, 'gate')

    # O10 the chemist's workshop ----------------------------------------------------------------
    s = mk('O10', 'road', 'lore (reachable by a spur); later a tape pickup',
           'a chemist who stayed longest, testing the water and the fuel; the benches are set out as if for the next test',
           1, 'mud-brick workshop, chemistry benches, jars, a small still', 22, '''
     [workshop: mudbrick_house]   chimney (Pillar_A_01)
       chemistry bench x2 (one outside under a tarp)   jars in rows   small still   clay vats
       drying rack (fence) with bundles    barrels    table with pots and a lamp
''', missing=['T2_chem_bench, T2_jars, T2_biofuel_still (Tripo, in production)'],
           tape='the chemist\'s readings (later)')
    s.add('T2_mudbrick_house', 0, 0, 'face_road', 1.0, 'workshop', landmark=True)
    s.add('AB_Pillar_A_01', 3, -3, 0, 1.2, 'workshop', note='chimney')
    s.add('T2_chem_bench', -6, 2, 'face_road', 1.0, 'benches')
    s.add('MV_Annex_Tarp_01', -6, 2, 'face_road', 0.7, 'benches', attach=True)
    s.add('T2_chem_bench', 1, 1, 'face_road', 1.0, 'benches', note='inside')
    for i in range(8):
        s.add('T2_jars', -9.5 + 0.7 * i, -5.0, 0, 1.0, 'jars')  # outside the 8 x 7 m workshop: at v -1.5 the row ran into it and jars landed on the stand-in's walls (LANE_SD)
    s.add('T2_biofuel_still', 6, 4, 0, 0.4, 'still')
    s.ring('B01_tank01', 4, 8, -4, 1.6, 'still', 0.9)
    s.run('MV_Fence_01_V1', [(-10, 6), (-2, 7)], 'rack', 1.0)
    s.add('MV_table_02', -3, -6, 0, 1.0, 'yard')
    s.scatter(POTS, 4, -3, -6, 0.8, 'yard', (0.8, 1.0))
    s.add('AB_Lamp_A', -2.6, -6, 0, 1.0, 'yard', stack=True, drop_cm=100)
    s.pile(['MV_barrel_01', 'MV_barrel_02'], 3, 7, -8, 1.0, 'yard')

    # O11 the signal-mirror hill ----------------------------------------------------------------
    s = mk('O11', 'road', 'view point (view-only): a glint that points toward the High Voice',
           'before the radio, the valley flashed messages from hill to hill with mirrors; the last mirror still turns in the wind',
           0, 'stone cairn, timber frame, a brass mirror', 12, '''
      big cairn (stacked rocks)   brass signal mirror on a timber frame   pillar   cloth strip on a post
''', missing=['T2_signal_mirror + a glint (emissive flash) material (NOT in the Tripo list; request it)'])
    for i, (k, sc) in enumerate((('LF_Rock_04', 1.0), ('LF_Rock_03', 1.0), ('LF_Rock_05', 1.0), ('LF_Rock_01', 0.7),
                                 ('LF_Rock_02', 0.6), ('LF_Rock_05', 0.5), ('LF_Rock_08', 2.0))):
        # base ring set on the ground as solids; only the upper stones are stacked (a stacked big base
        # cantilevered a rock into the air, as at S23; LANE_SD)
        if i < 3:
            s.add(k, 1.4 * math.cos(2.1 * i), 1.4 * math.sin(2.1 * i), 60 * i, sc * 0.75, 'cairn')
        else:
            r_ = 0.5 if i < 6 else 0.12
            s.add(k, r_ * math.cos(2.1 * i), r_ * math.sin(2.1 * i), 60 * i, sc, 'cairn', stack=True, drop_cm=60 + 80 * (i // 3))
    s.add('T2_signal_mirror', 4, 0, 'face_road', 1.0, 'mirror', landmark=True)
    s.add('AB_Pillar_A_03', -3, 3, 0, 1.0, 'mirror')
    s.add('MV_Fence_01_Log1', 3, -4, 0, 1.6, 'mirror')
    s.add('MV_Cloth_02', 3, -4, 0, 0.25, 'mirror', attach=True, z_offset_cm=140)

    # O13 the terrace orchards ------------------------------------------------------------------
    s = mk('O13', 'downhill', 'landmark (view-only): the hillside reads as stripes from the road',
           'terraces that fed the valley, walls still standing, the trees long dead',
           3, 'dry-stone terrace walls (Tripo terrace_wall, fallback wall02), stumps', 70, '''
   (u = downhill; each row runs along the contour, 8 m apart)
   row 1 ============================   stumps
   row 2 ==========================     stumps       field hut (wall03)
   row 3 ========================       stumps
   row 4 ... row 6
''', missing=['T2_terrace_wall (Tripo, in production)'])
    for row in range(6):
        u = 20 - 8 * row
        s.run('T2_terrace_wall', [(u, -40 + 3 * row), (u, 40 - 2 * row)], 'terraces', 1.0, skip={(row * 5) % 16},
              ism=True)
        for i in range(5):
            s.add(['PH_stump_01', 'PH_stump_02', 'FAB_Stump'][(row + i) % 3], u - 3, -32 + 16 * i + s.rng.uniform(-3, 3),
                  s.rng.uniform(0, 360), 1.0, 'stumps')
    s.add('B01_wall03', -30, 30, 'face_downhill', 1.0, 'hut')

    # O14 the granary hamlet --------------------------------------------------------------------
    s = mk('O14', 'road', 'lore + Name Roll entry (reachable by a spur)',
           'a farming hamlet: the granary and dovecote stand, the bread oven is cold, the pens are open',
           1, 'mud-brick houses, granary, dovecote, bread oven, pens (Tripo); MedievalVillage farm props', 40, '''
        [house]   [house]      [granary]      dovecote (8 m)
          bread oven   well   threshing floor (4 flagstones)
        pens x2 (open)   hay   cart   jars by the doors   way-marker at the lane
''', missing=['T2_mudbrick_house, T2_granary, T2_dovecote, T2_bread_oven, T2_animal_pen, T2_jars (Tripo, in production)'],
           name_roll='the hamlet\'s name (later)')
    s.add('T2_mudbrick_house', -10, -10, 'face_road', 1.0, 'houses', landmark=True)
    s.add('T2_mudbrick_house', -10, 4, 'face_road', 0.9, 'houses')
    s.add('T2_granary', 4, -14, 'face_road', 1.0, 'granary', landmark=True)
    s.add('T2_dovecote', 12, 8, 0, 1.0, 'dovecote', landmark=True)
    s.add('T2_bread_oven', 0, 6, 'face_road', 1.0, 'yard')
    s.add('MV_well', 2, -2, 0, 1.0, 'yard')
    for i, (a, b) in enumerate(((-1.5, -1.5), (1.5, -1.5), (-1.5, 1.5), (1.5, 1.5))):
        s.add('B01_floor01', 10 + a, -4 + b, 90 * i, 1.0, 'threshing')
    s.add('T2_animal_pen', 22, -8, 0, 1.0, 'pens')
    s.add('T2_animal_pen', 22, 6, 0, 1.0, 'pens')
    s.add('BPP_Hay_Bale', 16, 18, 20, 1.0, 'yard')
    s.add('BPP_Cart_02', -2, 16, 40, 1.0, 'yard')
    s.scatter(['T2_jars'], 6, -6, -3, 3, 'yard', (0.9, 1.1), min_sep=0.9)
    s.add('T2_way_marker', -24, 0, 'face_road', 1.0, 'lane')

    # O15 the great quarry ----------------------------------------------------------------------
    s = mk('O15', 'downhill', 'landmark (view-only): a pale cut scar on the mountain',
           'the builders cut the fort, the cistern and the way-stones from here: a stepped face, hoists and a cart track',
           2, 'cut rock faces, squared blocks, hand-cranked hoists, hand-cart track', 45, '''
   (u = downhill)   upper cut face (rock_face x2)   hoist
                    middle cut face (rock_face x2)   hoist        rows of squared blocks
                    spoil heaps (rubble01)   hand-cart track down the slope   sledges
''', missing=['scree and spoil piles (rubble01 stands in)'])
    for i, u in enumerate((-14, -14, -4, -4)):
        s.add('PH_rock_face', u, -8 + 16 * (i % 2), 'face_downhill', 1.5, 'faces', landmark=True)
    s.add('B01_crane01', -10, 0, 'face_downhill', 1.3, 'hoists')
    s.add('B01_crane01', 0, 10, 'face_downhill', 1.3, 'hoists')
    for r_ in range(2):
        for i in range(8):
            s.add('B01_brick01', 6 + 3 * r_, -12 + 3.2 * i, s.rng.uniform(-6, 6), 1.0, 'blocks', ism=True)
    s.run('B01_rail01', [(-6, -16), (16, -18)], 'track', 1.0, verdict_check=True)
    for u, v in ((14, 10), (18, -4), (10, 18), (20, 14)):
        s.add('B01_rubble01', u, v, s.rng.uniform(0, 360), 1.4, 'spoil')
    s.scatter(ROCKS, 30, 12, 4, 16, 'spoil', (0.5, 1.2))
    s.add('AB_Planks_150_B', 8, -16, 20, 1.0, 'sledges')
    return out


def frame_for(W, site):
    """(centre, f, r) for an off-road site."""
    c = np.array(site.xy, float)
    _, q = W.road_distance([c])
    if site.frame == 'downhill':
        f, _ = downhill_dir(W, c[0], c[1])
    elif site.frame == 'valley':
        f = valley_dir(W, c[0], c[1])
    else:
        f = (c - q) / (np.linalg.norm(c - q) or 1.0)
    return c, f, np.array([-f[1], f[0]]), q


def add_spur(W, site, q):
    """Marked spur for a reachable POI: way-markers every ~70 m, from the road verge to the zone edge."""
    sp = spur(W, site.xy[0], site.xy[1], float(site.road_m))
    seg = sp.pop('samples')
    sp.pop('z')
    site.poi['spur'] = sp
    d = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(seg, axis=0), axis=1))])
    stop = d[-1] - site.radius_m
    marks = []
    for m in np.arange(8.0, max(8.0, stop), SPUR_MARK_M):
        k = int(np.searchsorted(d, m))
        k = min(k, len(seg) - 1)
        p = seg[k]
        nxt = seg[min(k + 1, len(seg) - 1)] - seg[max(k - 1, 0)]
        nxt = nxt / (np.linalg.norm(nxt) or 1.0)
        side = np.array([-nxt[1], nxt[0]]) * 2.0
        marks.append((float(p[0] + side[0]), float(p[1] + side[1])))
    for i, (x, y) in enumerate(marks):
        site.add('T2_way_marker', 0, 0, 'face_road' if i == 0 else 0.0, 1.0, 'spur_markers', world_xy=(x, y),
                 note='spur marker %d (the tether corridor follows this line)' % i)
