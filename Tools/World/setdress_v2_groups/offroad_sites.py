"""Prepare the fifteen authored off-road sites for the V2 placement contract.

The V1 coordinates are intentional compositions (bridge gap, dam, pump skyline,
cart rows, quarry cuts). This pass keeps those anchors and authors a different
ground/approach treatment for each. Tripo focal meshes are hard dependencies:
their old stand-ins are removed, and import bounds must be measured in-editor.

This is offline preparation only; check2 and visual acceptance are editor work.
"""

import copy
import json
import math
import os
import sys
from collections import defaultdict
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
WORLD = os.path.dirname(HERE)
sys.path.insert(0, WORLD)
import setdress_v2 as V  # noqa: E402

IDS = tuple(f'O{i:02d}_{name}' for i, name in enumerate((
    'LowVoicePost', 'Refinery', 'BrokenBridge', 'Airship', 'CliffDwellings',
    'OldDam', 'Observatory', 'WindPumps', 'CartGraveyard', 'ChemistWorkshop',
    'MirrorHill', 'OldRelay', 'TerraceOrchards', 'GranaryHamlet', 'GreatQuarry'), 1))
OUTPUT = os.path.join(HERE, 'offroad_sites.json')
MANIFEST = os.path.join(os.path.dirname(os.path.dirname(WORLD)), 'SourceArt', 'Tripo', 'manifest.json')
MEASURED = os.path.join(os.path.dirname(os.path.dirname(WORLD)), 'Saved', 'Tripo', 'imported_bounds.json')

# Different surfaces follow what happened on the ground at each place. Group
# extents come from authored positions, with capped pads so no giant decal
# washes over an entire slope. The second number is extra width in metres.
SURFACES = {
    'O01': {'post_office': ('packed_earth', 3), 'back_room': ('packed_earth', 2),
            'radio_room': ('rubble_dust', 2),
            'mast': ('gravel', 2), 'yard': ('packed_earth', 2), 'mail': ('path', 2)},
    'O02': {'columns': ('soot', 3), 'stills': ('soot', 3), 'pipes': ('gravel', 2),
            'vats': ('packed_earth', 2), 'hall': ('rubble_dust', 3),
            'track': ('path', 1), 'barrels': ('soot', 2), 'rubble': ('rubble_dust', 2)},
    'O03': {'span': ('gravel', 3), 'abutment': ('rubble_dust', 2),
            'fallen': ('rubble_dust', 3), 'riverbed': ('dry_mud', 3)},
    'O04': {'hull': ('rubble_dust', 5), 'canvas': ('rubble_dust', 3),
            'gondola': ('packed_earth', 2), 'engines': ('soot', 3), 'cargo': ('path', 2)},
    'O05': {'facades': ('rubble_dust', 2), 'bridge': ('path', 1),
            'ladders': ('packed_earth', 1), 'ledges': ('packed_earth', 1)},
    'O06': {'dam': ('rubble_dust', 3), 'sluices': ('gravel', 2),
            'mill': ('gravel', 2), 'channels': ('gravel', 1), 'reservoir': ('dry_mud', 4)},
    'O07': {'tower': ('gravel', 3), 'enclosure': ('packed_earth', 2),
            'instruments': ('packed_earth', 1)},
    'O08': {'pumps': ('gravel', 2), 'troughs': ('dry_mud', 2)},
    'O09': {'rows_0': ('packed_earth', 2), 'rows_1': ('packed_earth', 2),
            'rows_2': ('packed_earth', 2), 'cradles': ('rubble_dust', 2),
            'wheels': ('rubble_dust', 2), 'sacks': ('path', 2)},
    'O10': {'workshop': ('packed_earth', 3), 'benches': ('path', 2),
            'jars': ('packed_earth', 2), 'still': ('soot', 2),
            'rack': ('packed_earth', 2), 'yard': ('packed_earth', 2)},
    'O11': {'cairn': ('gravel', 2), 'mirror': ('packed_earth', 2)},
    'O12': {'tower': ('rubble_dust', 4), 'hut': ('packed_earth', 2),
            'rubble': ('rubble_dust', 2)},
    'O13': {'terraces': ('packed_earth', 2), 'stumps': ('dry_mud', 2),
            'hut': ('packed_earth', 2)},
    'O14': {'houses': ('packed_earth', 3), 'granary': ('packed_earth', 3),
            'dovecote': ('gravel', 3), 'yard': ('packed_earth', 3),
            'threshing': ('path', 2), 'pens': ('packed_earth', 2)},
    'O15': {'faces': ('rubble_dust', 3), 'hoists': ('packed_earth', 2),
            'blocks': ('rubble_dust', 2), 'track': ('path', 1),
            'spoil': ('rubble_dust', 3), 'sledges': ('packed_earth', 2)},
}

# Narrative focus is named explicitly for editor review; never inferred from
# the mere presence of generic rubble or a fallback building.
FOCUS = {
    'O01': 'radio room and copper-timber mast', 'O02': 'two distillation columns',
    'O03': 'the absent middle bridge span', 'O04': 'the small scout airship wreck',
    'O05': 'cliff facade terraces and suspended crossing',
    'O06': 'dry reservoir, open sluices and wheel', 'O07': 'dome over the tower',
    'O08': 'five pumps along the ridge', 'O09': 'two empty carrier cradles behind cart rows',
    'O10': 'cold still and test benches', 'O11': 'single signal mirror beside the cairn',
    'O12': 'standing and fallen relay tower', 'O13': 'contour terraces and dead orchard',
    'O14': 'granary and dovecote across the threshing yard',
    'O15': 'cut faces, two hoists and spoil below the block rows',
}
PARTIAL_REPLANS = {'O01', 'O04', 'O05', 'O13', 'O14'}


def patch(F, x, y, surface, length, width, yaw=0.0, strength=0.65, shape='ellipse'):
    u, v = F.site(x, y)
    return dict(u=u, v=v, yaw=yaw, length=length, width=width,
                surface=surface, shape=shape, strength=strength,
                order=3 if surface == 'path' else 0)


def group_patches(F, site):
    out = []
    groups = defaultdict(list)
    for p in site['placements']:
        if p['group'] != 'spur_markers':
            groups[p['group']].append(p)
    recipe = SURFACES[site['id'][:3]]
    for group, (surface, apron) in recipe.items():
        ps = groups.get(group, [])
        if not ps:
            continue
        if group == 'terraces':
            runs = defaultdict(list)
            for p in ps:
                runs[p['run_id']].append(p)
            for run in runs.values():
                for i in range(0, len(run), 5):
                    seg = run[i:i+5]
                    a, b = seg[0], seg[-1]
                    ax, ay = a['x_cm']/100, a['y_cm']/100
                    bx, by = b['x_cm']/100, b['y_cm']/100
                    length = math.hypot(bx-ax, by-ay) + 5.0
                    yaw = math.degrees(math.atan2(by-ay, bx-ax)) - site['road_yaw']
                    out.append(patch(F, (ax+bx)/2, (ay+by)/2, surface,
                                     length, 5.0, yaw, 0.48, 'capsule'))
            continue
        if group in ('riverbed', 'reservoir', 'stumps', 'spoil'):
            xs = [p['x_cm']/100 for p in ps]
            ys = [p['y_cm']/100 for p in ps]
            pieces = {'riverbed': 3, 'reservoir': 2, 'stumps': 5, 'spoil': 3}[group]
            low, high = min(ys), max(ys)
            for i in range(pieces):
                out.append(patch(F, (min(xs)+max(xs))/2,
                                 low + (i+0.5)*(high-low)/pieces, surface,
                                 max(xs)-min(xs)+2*apron,
                                 (high-low)/pieces+2*apron+3,
                                 strength=0.5 if group == 'stumps' else 0.6))
            continue
        # Long lines are treated as a series of short connected pads. This
        # follows the dam, river, pump ridge, rail, and orchard contours.
        line = group in ('channels', 'track', 'pumps', 'troughs')
        buckets = [ps[i:i + 7] for i in range(0, len(ps), 7)] if line else [ps]
        for bucket in buckets:
            xs = [p['x_cm'] / 100 for p in bucket]
            ys = [p['y_cm'] / 100 for p in bucket]
            x, y = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
            length = max(3.0, max(xs) - min(xs) + 2 * apron)
            width = max(2.5, max(ys) - min(ys) + 2 * apron)
            # The decal primitive is an oriented ellipse. Avoid broad, flat
            # rectangles over the landscape when a group spreads diagonally.
            if length > 32 or width > 32:
                for p in bucket:
                    out.append(patch(F, p['x_cm']/100, p['y_cm']/100,
                                     surface, min(10, p['size_m'][0] + 2*apron),
                                     min(8, p['size_m'][1] + 2*apron),
                                     strength=0.48))
            else:
                out.append(patch(F, x, y, surface, length, width,
                                 strength=0.58 if surface == 'dry_mud' else 0.68))
    return out


def local_approach(F, site):
    """Worn final metres from a reachable spur's gate into its focal yard."""
    if site['id'][:3] not in ('O01', 'O03', 'O06', 'O09', 'O10', 'O14'):
        return []
    markers = [p for p in site['placements'] if p['group'] in ('gate', 'lane')]
    if not markers:
        destination = {'O03': 'abutment', 'O06': 'dam', 'O10': 'workshop'}
        group = destination.get(site['id'][:3])
        if not group:
            return []
        waymarks = [p for p in site['placements'] if p['group'] == 'spur_markers']
        targets = [p for p in site['placements'] if p['group'] == group]
        if not waymarks or not targets:
            return []
        centre = site['centre_cm']
        marker = min(waymarks, key=lambda p: math.hypot(p['x_cm']-centre[0], p['y_cm']-centre[1]))
        target = min(targets, key=lambda p: math.hypot(p['x_cm']-marker['x_cm'], p['y_cm']-marker['y_cm']))
        tx, ty = target['x_cm']/100, target['y_cm']/100
        dx, dy = tx-marker['x_cm']/100, ty-marker['y_cm']/100
        d = math.hypot(dx, dy) or 1.0
        fx, fy = tx-dx/d*3.0, ty-dy/d*3.0  # stop before the solid
        sx, sy = fx-dx/d*12.0, fy-dy/d*12.0
        yaw = math.degrees(math.atan2(dy, dx)) - site['road_yaw']
        return [patch(F, (sx+fx)/2, (sy+fy)/2, 'path', 12.0, 2.2,
                      yaw, 0.72, 'capsule')]
    x0, y0 = markers[0]['x_cm']/100, markers[0]['y_cm']/100
    x1, y1 = site['centre_cm'][0]/100, site['centre_cm'][1]/100
    dx, dy = x1-x0, y1-y0
    length = math.hypot(dx, dy)
    if length > 45:
        return []
    yaw = math.degrees(math.atan2(dy, dx)) - site['road_yaw']
    return [patch(F, (x0+x1)/2, (y0+y1)/2, 'path', length+2, 2.0, yaw, 0.72, 'capsule')]


def path_clearance(world, ground):
    """Minimum sampled distance of path decals to the 5 m road core.

    Sampling the full oriented decal boxes is conservative for the ellipse and
    capsule masks they contain. Spur markers remain on their separate path.
    """
    best = float('inf')
    for g in ground:
        if g['surface'] != 'path':
            continue
        a = math.radians(g['yaw'])
        ca, sa = math.cos(a), math.sin(a)
        x, y = g['x_cm']/100, g['y_cm']/100
        pts = [(x + ca*i*g['length_m']/10 - sa*k*g['width_m']/6,
                y + sa*i*g['length_m']/10 + ca*k*g['width_m']/6)
               for i in range(-5, 6) for k in range(-3, 4)]
        d, _ = world.road_distance(pts)
        best = min(best, d)
    return None if math.isinf(best) else round(best, 2)


def build_site(world, old, import_sizes, measured_keys):
    site = copy.deepcopy(old)
    sid = site['id']
    F = V.Frame(world, site['road_m'], site.get('lateral_m') or 0.0)
    dependencies = []
    placements = []
    for p in site['placements']:
        key = p['key']
        serial = int(p['id'].rsplit('_', 1)[1])
        # The old 60 m rib array belongs to a different airship. The approved
        # Tripo hull is 14 m long: leave an asymmetric wreck and spilled cargo.
        if sid.startswith('O04') and p['group'] == 'standin_ribs':
            continue
        if sid.startswith('O01') and serial == 1:
            # The imported house has a rubble apron, not a usable interior.
            # The radio room below is a roofless U of authored stone walls.
            continue
        if sid.startswith('O02') and p['group'] == 'vats' and serial in (10, 13, 17):
            # The western vat court has three failed positions, with debris
            # below the gaps. The machinery reads as a stopped process.
            continue
        if sid.startswith('O13') and p['group'] == 'terraces' and serial % 13 == 4:
            # Slumped intervals break the continuous contour courses.
            continue
        if sid.startswith('O10') and key == 'T2_jars' and serial not in (5, 10):
            # This approved model is a complete 14-jar rack. Two racks read
            # as the chemist's sorted samples; eight would interpenetrate.
            continue
        if sid.startswith('O14') and key == 'T2_jars' and serial not in (14, 15):
            continue
        if sid.startswith('O13') and p['group'] == 'terraces' and serial % 3:
            # Explicit low dry-stone infill between the tall Tripo sluice
            # blocks. This is a mixed terrace course, not an asset fallback.
            low = V.CAT['B01_wall02']
            p.update(key='B01_wall02', asset=low['path'], kind=low['kind'],
                     cat=low['cat'], scale=1.25,
                     size_m=[round(v/100*1.25, 3) for v in low['size_cm']],
                     note='low dry-stone infill between required Tripo terrace blocks')
            for field in ('fallback', 'requires_import', 'verdict', 'imported'):
                p.pop(field, None)
            key = p['key']
        if sid.startswith('O09') and p['group'].startswith('rows_'):
            row = int(p['group'][-1])
            slot = serial % 5
            p['x_cm'] += (-90, 45, 140, -55, 105)[slot] + row * 22
            p['y_cm'] += (70, -60, 30, 125, -85)[slot] - row * 18
            p['yaw'] += (-11, 8, 17, -6, 13)[slot]
            p['ground_z_cm'] = round(world.ground(p['x_cm']/100, p['y_cm']/100)*100, 1)
        if sid.startswith('O01') and serial in (8, 9):
            # The imported house aprons are wider than V1's. Guy anchors
            # move outside the rooms while keeping the mast triangle legible.
            p['x_cm'] += 300 if serial == 8 else -100
            p['y_cm'] += 100 if serial == 8 else -300
            p['ground_z_cm'] = round(world.ground(p['x_cm']/100, p['y_cm']/100)*100, 1)
        if sid.startswith('O01') and serial in (6, 7, 8, 9):
            # The tower's measured 7.6 m base (at 0.45 scale) needs its own
            # spur-side plinth away from the roofless radio room.
            p['x_cm'] += 250
            p['y_cm'] -= 630
            p['ground_z_cm'] = round(world.ground(p['x_cm']/100, p['y_cm']/100)*100, 1)
        if sid.startswith('O01') and serial in (2, 3, 4, 5):
            room_items = {2: (6078.2, 3819.7), 3: (6076.6, 3820.4),
                          4: (6078.4, 3821.3), 5: (6077.8, 3817.8)}
            x, y = room_items[serial]
            p['x_cm'], p['y_cm'] = x*100, y*100
            p['ground_z_cm'] = round(world.ground(x, y)*100, 1)
        if sid.startswith('O05') and key == 'T2_rope_footbridge':
            # Eight real metres bridge the two nearest ledges. The old V1
            # 16 m crossing floated past the row of cliff rooms.
            a, b = (6371.19, 5212.66), (6375.90, 5205.60)
            p['x_cm'], p['y_cm'] = (a[0]+b[0])*50, (a[1]+b[1])*50
            p['yaw'] = math.degrees(math.atan2(b[1]-a[1], b[0]-a[0])) % 360
            p['ground_z_cm'] = round(world.ground(p['x_cm']/100, p['y_cm']/100)*100, 1)
        if sid.startswith('O14') and key == 'T2_animal_pen':
            # Real pens are 5 m wide gated enclosures, not the old 8 m low
            # fence squares. Face their gates into a shared working lane.
            x, y, yaw = ((5777.0, 4541.0, 100.0) if serial == 10
                         else (5769.5, 4541.0, 110.0))
            p['x_cm'], p['y_cm'], p['yaw'] = x*100, y*100, yaw
            p['ground_z_cm'] = round(world.ground(x, y)*100, 1)
        if key.startswith('T2_'):
            p.pop('fallback', None)
            p['requires_import'] = True
            asset = V.CAT[key]
            imported = bool(asset.get('imported'))
            p['imported'] = imported
            p['verdict'] = asset['verdict']
            if imported:
                p.pop('optional', None)
                # The catalog is the placement contract's measured inventory.
                p['size_m'] = [round(v * p['scale'] / 100, 3) for v in asset['size_cm']]
                p['bounds_basis'] = 'measured_import'
            else:
                # O07's dome and telescope are owned design dependencies but
                # absent from this import batch. Skip them, without a pillar
                # or unrelated mesh standing in for either focal silhouette.
                p['optional'] = True
                if key in import_sizes:
                    p['size_m'] = [round(v * p['scale'], 3) for v in import_sizes[key]]
                    p['bounds_basis'] = 'prepared_glb_manifest'
            dependencies.append(key)
        cfg = p['settle']
        cat = p['cat']
        if p.get('ism'):
            p['contact'] = 'lie'
            cfg.update(mode='trace', z_rule='mean', max_tilt_deg=25,
                       rand_tilt_deg=5, sink_cm=max(9, cfg['sink_cm']))
        elif cat in ('building', 'wall', 'wood_post', 'stone', 'prop_static') and not (abs(p['pitch']) > 30 or abs(p['roll']) > 30):
            p['contact'] = 'rigid'
            cfg.update(mode='trace', z_rule='min', max_tilt_deg=0,
                       rand_tilt_deg=0, sink_cm=max(15, cfg['sink_cm']))
        elif abs(p['pitch']) > 30 or abs(p['roll']) > 30:
            p['contact'] = 'lie'
            cfg.update(mode='trace', z_rule='mean', max_tilt_deg=25,
                       rand_tilt_deg=8, sink_cm=max(8, cfg['sink_cm']))
        else:
            p['contact'] = 'rest'
            cfg.update(mode='physics', z_rule='max', max_tilt_deg=15,
                       rand_tilt_deg=3, sink_cm=max(3, cfg['sink_cm']))
        p['material_set'] = 'wood' if cat in ('wood', 'wood_post', 'cloth') else 'stone'
        # The contact judge exempts touching pieces of one deliberate solid
        # structure. These are authored joints, not arbitrary nearby props.
        if sid.startswith('O01') and p['group'] == 'yard' and key != 'B01_sign02':
            p['block'] = 'post_yard_wall'
        if sid.startswith('O02') and p['group'] == 'hall' and key.startswith('AB_300'):
            p['block'] = 'refinery_ruined_hall'
        if sid.startswith('O03') and p['group'] == 'riverbed' and key.startswith('LF_Rock'):
            p['block'] = 'dry_river_stone_bed'
        if sid.startswith('O06') and p['group'] == 'dam' and key == 'AB_Fort_Wall_Mid':
            p['block'] = 'dam_curtain'
        if sid.startswith('O06') and p['group'] == 'reservoir' and key.startswith('LF_Rock'):
            p['block'] = 'reservoir_stone_bed'
        if sid.startswith('O10') and p['group'] == 'workshop':
            p['block'] = 'chemist_house_chimney'
        if sid.startswith('O11') and p['group'] == 'cairn':
            p['block'] = 'stacked_signal_cairn'
        if sid.startswith('O13') and p['group'] == 'terraces':
            p['block'] = 'orchard_course_' + str(p['run_id'])
        if sid.startswith('O01') and key == 'T2_radio_desk':
            # A desk belongs inside the second room; its centre overlaps the
            # house footprint by design. Its support is checked in-editor.
            p['contact'] = 'rest'
            cfg.update(mode='physics', z_rule='max', max_tilt_deg=15, sink_cm=3)
        if sid.startswith('O10') and key == 'T2_chem_bench':
            p['contact'] = 'rest'
            cfg.update(mode='physics', z_rule='max', max_tilt_deg=15, sink_cm=3)
        if sid.startswith('O01') and key == 'B01_sign02':
            p['contact'] = 'rest'
            cfg.update(mode='physics', z_rule='max', max_tilt_deg=15, sink_cm=3)
        if sid.startswith('O08') and key == 'B01_channel01':
            # A dry trough sits against each pump, with a visible maintenance
            # gap. The old V1 gap was only 11 cm in two cases.
            pump = min((q for q in placements if q['key'] == 'T2_wind_pump'),
                       key=lambda q: math.hypot(q['x_cm']-p['x_cm'], q['y_cm']-p['y_cm']))
            dx, dy = p['x_cm']-pump['x_cm'], p['y_cm']-pump['y_cm']
            d = math.hypot(dx, dy) or 1.0
            p['x_cm'] += round(120*dx/d, 1)
            p['y_cm'] += round(120*dy/d, 1)
            p['ground_z_cm'] = round(world.ground(p['x_cm']/100, p['y_cm']/100)*100, 1)
        placements.append(p)
    site['placements'] = placements
    if sid.startswith('O01'):
        wall_asset = V.CAT['AB_300x400_Mid_Damaged_A']
        template = next(p for p in placements if p['key'] == 'B01_wall04')
        cx, cy, ang = 6077.0, 3819.7, math.radians(109.2)
        for n, (lx, ly, turn) in enumerate(((-1.5, -3.15, 0), (1.5, -3.15, 0),
                                            (-3.15, -1.5, 90), (-3.15, 1.5, 90),
                                            (3.15, -1.5, 90), (3.15, 1.5, 90))):
            x = cx + math.cos(ang)*lx - math.sin(ang)*ly
            y = cy + math.sin(ang)*lx + math.cos(ang)*ly
            wall = copy.deepcopy(template)
            wall.update(id=sid + '_v2_radio_wall_%d' % n,
                        key='AB_300x400_Mid_Damaged_A', asset=wall_asset['path'],
                        kind=wall_asset['kind'], cat=wall_asset['cat'],
                        x_cm=round(x*100, 1), y_cm=round(y*100, 1),
                        ground_z_cm=round(world.ground(x, y)*100, 1),
                        yaw=(109.2+turn)%360, scale=1.0,
                        size_m=[v/100 for v in wall_asset['size_cm']],
                        group='radio_room', folder='Set/'+sid+'/radio_room',
                        block='roofless_radio_room', contact='rigid',
                        note='roofless U room, open toward the post office')
            wall['settle'].update(mode='trace', z_rule='min', max_tilt_deg=0,
                                  rand_tilt_deg=0, sink_cm=25)
            wall['road_clear_m'], _ = world.road_distance([(x, y)])
            site['placements'].append(wall)
    if sid.startswith('O04'):
        hull = next(p for p in placements if p['key'] == 'T2_airship_hull')
        hull['note'] = 'approved 14 m scout airship; measure imported bounds before placement'
        # The old canvas tents represented a 60 m envelope and would read as
        # two unrelated camps beside the 14 m wreck.
        site['placements'] = [p for p in placements if p['group'] != 'canvas']
    site['required_assets'] = sorted(set(dependencies))
    site['reference_bounds_m'] = {key: import_sizes[key] for key in site['required_assets'] if key in import_sizes}
    site['measured_asset_bounds'] = sorted(set(dependencies) & measured_keys)
    site['unavailable_focal_assets'] = [key for key in site['required_assets'] if key not in import_sizes]
    site['composition_status'] = ('partial_replan_offline_review_required' if sid[:3] in PARTIAL_REPLANS
                                  else 'ground_contact_adapted_review_required')
    site['review_blockers'] = ['run editor check2 and inspect contact and road views']
    if set(dependencies) - measured_keys:
        site['review_blockers'].append('measure missing imported mesh bounds: ' +
                                       ', '.join(sorted(set(dependencies) - measured_keys)))
    if site['unavailable_focal_assets']:
        site['review_blockers'].append('dedicated focal meshes absent from owned inventory and import batch: ' + ', '.join(site['unavailable_focal_assets']))
    if sid.startswith('O05'):
        site['review_blockers'].append('mount facade and footbridge to the cliff; terrain-only contact estimate is insufficient')
    if sid.startswith('O01'):
        site['review_blockers'].append('seat radio desk, chair, lamp and log box within the imported back room')
    if sid.startswith('O07'):
        site['review_blockers'].append('mount dome and telescope on tower; verify their actual support elevations')
    if sid.startswith('O11'):
        site['review_blockers'].append('verify cairn stone bearing and mirror glint from the road')
    if sid.startswith('O13'):
        site['review_blockers'].append('resize/re-space terrace rows against measured 4 x 3.7 x 3 m wall bounds')
    if sid.startswith('O14'):
        site['review_blockers'].append('confirm both tall pen gates face the shared working lane')
    site['prepared_state'] = 'offline_prepared_editor_check_and_visual_review_pending'
    site['composition_focus'] = FOCUS[sid[:3]]
    ground = group_patches(F, site) + local_approach(F, site)
    if sid.startswith('O14'):
        a, b = (5777.3, 4532.0), (5773.2, 4540.8)
        yaw = math.degrees(math.atan2(b[1]-a[1], b[0]-a[0])) - site['road_yaw']
        ground.append(patch(F, (a[0]+b[0])/2, (a[1]+b[1])/2,
                            'path', math.hypot(b[0]-a[0], b[1]-a[1])+1.5,
                            2.0, yaw, 0.72, 'capsule'))
    core = F.site(site['centre_cm'][0]/100, site['centre_cm'][1]/100)
    proxy = SimpleNamespace(frame=F, ground=ground, road_m=site['road_m'],
                            v2=dict(core=core, walls=[], rows=[], lanes=[], doors=[],
                                    fans=[], rooms=[], units=[], focus=FOCUS[sid[:3]]), spec={})
    site['ground'] = V.ground_records(site, proxy)
    site['path_road_clearance_m'] = path_clearance(world, site['ground'])
    if site['path_road_clearance_m'] is not None and site['path_road_clearance_m'] <= V.B.CLEAR_M:
        raise RuntimeError(sid + ': path decal intersects the road core')
    site['v2'] = proxy.v2
    site['units'] = []
    site['views'] = V.v2_views(world, proxy, F, site['placements'])
    site['archetype'] = 'offroad_' + sid[4:].lower()
    site['counts']['placements'] = len(site['placements'])
    site['counts']['actors'] = (sum(not p['ism'] for p in site['placements']) +
                                len({(p['group'], p['asset']) for p in site['placements'] if p['ism']}))
    site['counts']['ism_instances'] = sum(bool(p['ism']) for p in site['placements'])
    site['counts']['physics'] = sum(p['settle']['mode'] == 'physics' for p in site['placements'])
    site['counts']['batch01'] = sum('/Batch01/' in p['asset'] for p in site['placements'])
    site['counts']['decals'] = len(site['ground'])
    issues, waived = V.offline_check(world, site)
    site['offline_check'] = dict(violations=[list(x) for x in issues],
                                 waived=[list(x) for x in waived],
                                 note='estimated against planned bounds; imported bounds and check2 required')
    return site


def main():
    world = V.B.World()
    source = {s['id']: s for s in json.load(open(V.SITES_JSON, encoding='utf8'))['sites']}
    manifest = json.load(open(MANIFEST, encoding='utf8'))['models']
    sizes = {'T2_' + p['t2']: [v/100 for v in p['import_size_cm_wdh']]
             for p in manifest if p['verdict'] == 'use'}
    measured = json.load(open(MEASURED, encoding='utf8')) if os.path.isfile(MEASURED) else {}
    # The report's `key` is the Studio project name (airship), while the
    # placement key is the catalog slot (T2_airship_hull). Resolve via path.
    measured_sizes = {'T2_' + p['path'].rsplit('/SM_T2_', 1)[1]: [v/100 for v in p['size_cm']]
                      for p in measured.values() if p.get('saved') and '/SM_T2_' in p['path']}
    measured_keys = set(measured_sizes)
    sizes.update(measured_sizes)
    sites = [build_site(world, source[sid], sizes, measured_keys) for sid in IDS]
    assert len(sites) == len(IDS) == len({s['id'] for s in sites})
    all_placement_ids = [p['id'] for s in sites for p in s['placements']]
    assert len(all_placement_ids) == len(set(all_placement_ids))
    for s in sites:
        if s['offline_check']['violations'] or s['counts']['actors'] > 250 or s['counts']['decals'] > 300:
            raise RuntimeError('offline contact or budget failure: ' + s['id'])
        print(s['id'], len(s['placements']), 'placements,', len(s['ground']),
              'decals,', len(s['offline_check']['violations']), 'estimated issues')
    with open(OUTPUT, 'w', encoding='utf8') as f:
        json.dump(dict(generated_by='Tools/World/setdress_v2_groups/offroad_sites.py',
                       group='offroad_sites', level='/Game/level/Saskarta_WP',
                       status='prepared_offline_not_saved_or_visually_accepted', sites=sites),
                  f, indent=1, ensure_ascii=False)
    print('wrote', OUTPUT)


if __name__ == '__main__':
    main()
