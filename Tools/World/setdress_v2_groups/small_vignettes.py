"""Grounded V2 treatment for small road vignettes and marker lines.

These sites have few intentional objects. Preserve their narrative positions,
then give every object V2 contact and shared terrain patches.
"""

import copy
import json
import os
import sys
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
WORLD = os.path.dirname(HERE)
sys.path.insert(0, WORLD)
import setdress_v2 as V  # noqa: E402

SITES = ('R01_Verge620', 'R02_Verge1080', 'R03_Verge3300', 'R04_Verge3750',
         'R05_Verge4150', 'L06_DescentCarts', 'L13_ShoulderCairns', 'S20_LongStair')
OUTPUT = os.path.join(HERE, 'small_vignettes.json')


def build_site(world, old):
    site = copy.deepcopy(old)
    frame = V.Frame(world, site['road_m'], site.get('lateral_m') or 0.0)
    for placement in site['placements']:
        cfg = placement['settle']
        cat = placement['cat']
        if cat in ('wall', 'building') and abs(placement.get('pitch', 0)) < 10:
            placement['contact'] = 'rigid'
            cfg.update(mode='trace', max_tilt_deg=0, rand_tilt_deg=0, z_rule='min', sink_cm=max(12, cfg['sink_cm']))
        elif abs(placement.get('pitch', 0)) > 45 or abs(placement.get('roll', 0)) > 45:
            placement['contact'] = 'lie'
            cfg.update(mode='trace', max_tilt_deg=25, rand_tilt_deg=10, z_rule='mean', sink_cm=max(8, cfg['sink_cm']))
        else:
            placement['contact'] = 'rest'
            cfg.update(mode='physics', max_tilt_deg=15, rand_tilt_deg=3, z_rule='max', sink_cm=max(3, cfg['sink_cm']))
        placement['material_set'] = 'wood' if cat in ('wood', 'wood_post', 'cloth') else 'stone'
    patches = []
    # One irregular dusty footprint per focal object, clustered objects share overlapping patches.
    for index, p in enumerate(site['placements']):
        if p.get('ism') and index % 3:
            continue
        u, v = frame.site(p['x_cm'] / 100.0, p['y_cm'] / 100.0)
        extent = max(p['size_m'][0], p['size_m'][1], 1.0)
        patches.append(dict(u=u, v=v, yaw=p['yaw'] - site['road_yaw'],
                            length=min(8.0, extent + 2.0), width=min(5.0, extent * 0.65 + 1.5),
                            surface='rubble_dust' if p['cat'] in ('stone', 'rubble') else 'packed_earth',
                            shape='ellipse', strength=0.45, order=0))
    core = frame.site(site['centre_cm'][0] / 100.0, site['centre_cm'][1] / 100.0)
    carrier = SimpleNamespace(frame=frame, ground=patches, road_m=site['road_m'],
                              v2=dict(core=core, walls=[], rows=[], lanes=[], doors=[], fans=[], rooms=[], units=[]),
                              spec={})
    site['ground'] = V.ground_records(site, carrier)
    site['v2'] = carrier.v2
    site['units'] = []
    site['views'] = V.v2_views(world, carrier, frame, site['placements'])
    site['archetype'] = 'vignette'
    site['counts']['decals'] = len(site['ground'])
    violations, waived = V.offline_check(world, site)
    site['offline_check'] = dict(violations=[list(v) for v in violations], waived=[list(v) for v in waived])
    return site


def main():
    world = V.B.World()
    source = {s['id']: s for s in json.load(open(V.SITES_JSON, encoding='utf8'))['sites']}
    sites = [build_site(world, source[sid]) for sid in SITES]
    for site in sites:
        n = len(site['offline_check']['violations'])
        print(site['id'], len(site['placements']), 'placements,', n, 'violations')
        if n:
            for issue in site['offline_check']['violations'][:5]:
                print(' ', issue)
            raise RuntimeError('V2 contact check failed: ' + site['id'])
    with open(OUTPUT, 'w', encoding='utf8') as stream:
        json.dump(dict(generated_by='Tools/World/setdress_v2_groups/small_vignettes.py',
                       group='small_vignettes', level='/Game/level/Saskarta_WP', sites=sites),
                  stream, indent=1, ensure_ascii=False)
    print('wrote', OUTPUT)


if __name__ == '__main__':
    main()
