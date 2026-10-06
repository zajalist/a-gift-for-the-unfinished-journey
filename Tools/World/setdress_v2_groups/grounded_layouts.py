"""V2 terrain/contact pass for authored outposts, camps and field layouts.

Unlike settlements, these sites already have specific story layouts in V1. Keep
their focal props and positions; repair run-piece overlaps, sink architecture,
and join nearby objects with continuous ground patches.
"""

import json
import math
import os
import sys
import copy
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
WORLD = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import small_vignettes as SMALL  # noqa: E402

V = SMALL.V
SITES = ('S01_CarrierDock', 'S08_Watchtower', 'S12_Checkpoint', 'S14_DeparturePlatform',
         'S16_Quarry', 'S19_LastWaystation', 'L04_ShepherdCamp', 'L07_ReedCutters',
         'L09_CaravanHalt', 'L11_BasinFields', 'L12_CloudHut', 'L15_FlankTerraces')
OUTPUT = os.path.join(HERE, 'grounded_layouts.json')


def separate_runs(world, site):
    """Move latter run piece along its axis until close butt joints stop intersecting."""
    for _ in range(12):
        issues, _ = V.offline_check(world, site)
        overlaps = [v for v in issues if v[1] == 'CLASH']
        if not overlaps:
            return
        by_id = {p['id']: p for p in site['placements']}
        for first, _, detail in overlaps:
            other = detail.split(' x ', 1)[1].split(' ', 1)[0]
            a, b = by_id[first], by_id[other]
            if a['cat'] not in ('wall', 'wood_post') or b['cat'] not in ('wall', 'wood_post'):
                raise RuntimeError('cannot automatically separate non-run objects: ' + detail)
            cm = float(detail.rsplit('(', 1)[1].split(' cm', 1)[0]) + 12.0
            dx, dy = b['x_cm'] - a['x_cm'], b['y_cm'] - a['y_cm']
            length = math.hypot(dx, dy) or 1.0
            b['x_cm'] += round(cm * dx / length, 1)
            b['y_cm'] += round(cm * dy / length, 1)
            b['note'] = (b.get('note') or '') + '; V2 seam spacing %.0f cm' % cm
    raise RuntimeError('run spacing did not converge: ' + site['id'])


def revise_l07(world, site):
    """Turn the old pair of 16 m fence rails into three working bays and a small cart drop.

    Coordinates are in the existing road frame, so the camp, terrain and road
    relationship stay authored. Stable IDs let the site replacement remove the
    old straight runs before putting the new pieces down.
    """
    if site['id'] != 'L07_ReedCutters':
        return
    frame = V.Frame(world, site['road_m'], site.get('lateral_m') or 0.0)
    by_id = {int(p['id'].rsplit('_', 1)[1]): p for p in site['placements']}
    if set(by_id) != set(range(28)):
        raise RuntimeError('L07 source changed: expected original 28 placements')

    def move(index, u, v, yaw, *, scale=None, note=None, run=None):
        p = by_id[index]
        x, y = frame.world(u, v)
        sx, sy = p['size_m'][:2]
        if scale is not None:
            ratio = scale / p['scale']
            p['size_m'] = [round(n * ratio, 3) for n in p['size_m']]
            p['scale'] = scale
            p['scale_range'] = [scale, scale]
            sx, sy = p['size_m'][:2]
        corners = V.B.rect_corners(x, y, yaw, sx, sy)
        heights = [world.ground(*q) for q in corners]
        road_clear, _ = world.road_distance(V.B.perimeter(corners))
        p.update(x_cm=round(x * 100, 1), y_cm=round(y * 100, 1),
                 ground_z_cm=round(world.ground(x, y) * 100, 1), yaw=round(yaw % 360, 1),
                 slope_deg=round(world.slope_deg(x, y), 1),
                 relief_m=round(max(heights) - min(heights), 2),
                 road_clear_m=round(road_clear, 2), run_id=run)
        if note:
            p['note'] = note
        if p['cat'] == 'wall':
            p['material_set'] = 'wood'
        return p

    # Drying racks are short, staggered bays with real working gaps. The last
    # pair sits where a cart could unload on the approach, not across the road.
    racks = {
        0: (-18.3, 14.0, 49, 11), 1: (-15.8, 14.4, 46, 11),
        7: (-17.0, 18.3, 39, 11),
        3: (-11.4, 15.0, 51, 12), 4: (-8.9, 15.8, 43, 12),
        8: (-9.7, 19.0, 57, 12),
        5: (-3.5, 16.2, 31, 13), 11: (-1.2, 17.8, 39, 13),
        9: (-17.1, -21.0, 68, 14), 10: (-14.5, -20.5, 61, 14),
    }
    for index, (u, v, yaw, run) in racks.items():
        move(index, u, v, yaw, run=run,
             note='Reed drying bay' if run != 14 else 'Small cart-drop rack at the worn approach')

    # Unevenly accumulated cut bundles: one left behind at the cart drop, a
    # close pair near the middle bay and another beside the stripped shelter.
    for index, spec in {
        12: (-16.1, 20.4, 213, 0.74), 13: (-10.7, 21.0, 247, 0.84),
        14: (-9.1, 22.0, 198, 0.71), 15: (-2.6, 19.7, 278, 0.92),
    }.items():
        move(index, *spec[:3], scale=spec[3], note='cut reed bundle, left where it was worked')
    drop = copy.deepcopy(by_id[12])
    drop['id'] = 'L07_ReedCutters_028'
    by_id[28] = drop
    move(28, -15.7, -18.2, 231, scale=0.88, note='last bundled load beside the cart-drop rack')

    # The plank walk survives only at damp spots; two pieces also mark the
    # start of the approach. There is no ruler-straight eight-piece boardwalk.
    for index, (u, v, yaw) in {
        18: (-20.1, 24.1, 139), 19: (-18.6, 24.9, 152),
        20: (-16.0, -15.2, 121), 21: (-14.7, 25.8, 127),
        22: (-13.2, 26.3, 148), 23: (-14.3, -13.5, 157),
        24: (-8.8, 24.5, 160), 25: (-6.9, 23.8, 132),
    }.items():
        move(index, u, v, yaw, note='broken plank patch on the worn reed-cutters path')
    site['placements'] = [by_id[i] for i in sorted(by_id) if i not in (2, 6)]
    site['counts']['placements'] = len(site['placements'])
    site['counts']['actors'] = len(site['placements'])
    site['counts']['physics'] = sum(p['settle']['mode'] == 'physics' for p in site['placements'])
    site['layout'] = ('Three short staggered reed-drying bays; a two-panel cart drop on the worn approach; '
                      'bundles accumulated unevenly, crooked plank patches, and a stripped shelter.')


def patch_ground(world, site):
    frame = V.Frame(world, site['road_m'], site.get('lateral_m') or 0.0)
    patches = []
    if site['id'] == 'L07_ReedCutters':
        # A worn, bending route joins the modest road-side cart drop to the
        # work bays. Separate pads keep the three bays distinct from above.
        for u, v, yaw, length, width, surface, strength in (
            (-15.8, -19.5, 0, 6.5, 4.5, 'packed_earth', .55),
            (-14.7, -12.5, 81, 15.5, 1.7, 'path', .34),
            (-13.9, 0.5, 94, 12.0, 1.5, 'path', .32),
            (-15.7, 10.5, 107, 11.0, 1.6, 'path', .30),
            (-17.2, 16.1, 0, 7.0, 6.0, 'packed_earth', .51),
            (-10.0, 17.7, 0, 7.0, 6.5, 'packed_earth', .55),
            (-2.4, 17.4, 0, 5.8, 5.0, 'packed_earth', .48),
            (-11.1, 23.7, -8, 17.0, 2.1, 'path', .29),
            (-1.5, 23.2, 0, 9.0, 8.0, 'packed_earth', .46),
        ):
            patches.append(dict(u=u, v=v, yaw=yaw, length=length, width=width,
                                surface=surface, shape='capsule' if surface == 'path' else 'ellipse',
                                strength=strength, order=0))
        core = frame.site(site['centre_cm'][0] / 100.0, site['centre_cm'][1] / 100.0)
        proxy = SimpleNamespace(frame=frame, ground=patches, road_m=site['road_m'],
                                v2=dict(core=core, walls=[], rows=[], lanes=[], doors=[], fans=[], rooms=[], units=[]),
                                spec={})
        site['ground'] = V.ground_records(site, proxy)
        site['counts']['decals'] = len(site['ground'])
        return
    groups = {}
    for p in site['placements']:
        if p['cat'] in ('shrub', 'veg'):
            continue
        u, v = frame.site(p['x_cm'] / 100.0, p['y_cm'] / 100.0)
        groups.setdefault(p['group'], []).append((u, v, p))
    for name, points in groups.items():
        clusters = []
        for point in points:
            # Group connected objects but cap each patch to a manageable terrain area.
            candidates = [c for c in clusters if min(math.hypot(point[0]-p[0], point[1]-p[1]) for p in c) < 9.0]
            if candidates and len(candidates[0]) < 18:
                candidates[0].append(point)
            else:
                clusters.append([point])
        for cluster in clusters:
            us, vs = [p[0] for p in cluster], [p[1] for p in cluster]
            u, v = (min(us)+max(us))/2, (min(vs)+max(vs))/2
            length = min(30.0, max(us)-min(us)+4.0)
            width = min(24.0, max(vs)-min(vs)+4.0)
            patches.append(dict(u=u, v=v, yaw=0.0, length=length, width=width,
                                surface='rubble_dust' if name in ('rubble', 'scree') else 'packed_earth',
                                shape='ellipse', strength=0.52, order=0))
    core = frame.site(site['centre_cm'][0] / 100.0, site['centre_cm'][1] / 100.0)
    proxy = SimpleNamespace(frame=frame, ground=patches, road_m=site['road_m'],
                            v2=dict(core=core, walls=[], rows=[], lanes=[], doors=[], fans=[], rooms=[], units=[]),
                            spec={})
    site['ground'] = V.ground_records(site, proxy)
    site['counts']['decals'] = len(site['ground'])


def main():
    world = V.B.World()
    source = {s['id']: s for s in json.load(open(V.SITES_JSON, encoding='utf8'))['sites']}
    sites = []
    for sid in SITES:
        site = SMALL.build_site(world, source[sid])
        if sid == 'L07_ReedCutters':
            revise_l07(world, site)
        if sid == 'S19_LastWaystation':
            # V7 owns the flag as well as the cradle and tarp. The I33 banner is
            # only a stand-in when that story set has not been installed.
            flags = [p for p in site['placements'] if p['key'] == 'TRIPO_Flag' and p['group'] == 'flag']
            if len(flags) != 1:
                raise RuntimeError('S19 V7 flag stand-in changed')
            flags[0]['story_owned_if_missing'] = True
        separate_runs(world, site)
        patch_ground(world, site)
        violations, waived = V.offline_check(world, site)
        site['offline_check'] = dict(violations=[list(v) for v in violations], waived=[list(v) for v in waived])
        if violations or site['counts']['actors'] > 250 or site['counts']['decals'] > 300:
            raise RuntimeError('%s: %d violations, %d actors, %d decals' % (
                sid, len(violations), site['counts']['actors'], site['counts']['decals']))
        sites.append(site)
        print(sid, len(site['placements']), 'placements,', len(site['ground']), 'ground patches, 0 violations')
    with open(OUTPUT, 'w', encoding='utf8') as stream:
        json.dump(dict(generated_by='Tools/World/setdress_v2_groups/grounded_layouts.py',
                       group='grounded_layouts', level='/Game/level/Saskarta_WP', sites=sites),
                  stream, indent=1, ensure_ascii=False)
    print('wrote', OUTPUT)


if __name__ == '__main__':
    main()
