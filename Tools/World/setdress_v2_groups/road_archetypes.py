"""Compose the road sites whose V2 archetype already matches their story role.

This deliberately excludes the waystation, camps, vignettes and off-road landmarks.
Those need site-specific recipes; assigning a generic building to them would repeat
the scattered V1 dressing that the V2 pass is replacing.
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WORLD = os.path.dirname(HERE)
sys.path.insert(0, WORLD)

import setdress_v2 as V  # noqa: E402


SITES = (
    'S10_CrestFort',
    'L03_ThreshingFarm',
    'L05_RidgeHamlet',
    'L08_BasinHamlet',
    'L10_FootFarm',
)
# L10 is a lone farmstead rather than a broad agricultural complex. Keep one
# contour field and use a site-specific layout seed so the approach-side yard
# breaks up the otherwise parallel terrace silhouette.
SITE_OVERRIDES = {
    'L10_FootFarm': {'fields': 1, 'seed': 'L10v2.1-3'},
}
OUTPUT = os.path.join(HERE, 'road_archetypes.json')


def build_sites(world, site_ids=SITES):
    """Build each site with only its own authored overrides applied."""
    sites = []
    totals = {'checks': [], 'rejected': []}
    for site_id in site_ids:
        built, result = V.build(world, [site_id], **SITE_OVERRIDES.get(site_id, {}))
        sites.extend(built)
        totals['checks'].extend(result['checks'])
        totals['rejected'].extend(result['rejected'])
    return sites, totals


def main():
    world = V.B.World()
    sites, totals = build_sites(world)
    for site in sites:
        counts = site['counts']
        problems = site['offline_check']['violations']
        actors = sum(not p['ism'] for p in site['placements'] if not p.get('optional'))
        actors += len({(p['group'], p['asset']) for p in site['placements'] if p['ism'] and not p.get('optional')})
        if problems or actors > 250 or counts['decals'] > 300:
            raise RuntimeError('%s: %d contact violations, %d actors, %d decals' % (
                site['id'], len(problems), actors, counts['decals']))
        print('%s: %d placements, %d actors, %d decals, 0 offline violations' % (
            site['id'], counts['placements'], actors, counts['decals']))
    with open(OUTPUT, 'w', encoding='utf8') as stream:
        json.dump(dict(generated_by='Tools/World/setdress_v2_groups/road_archetypes.py',
                       group='road_archetypes', method='docs/world/SETDRESS_V2.md',
                       level='/Game/level/Saskarta_WP', checks=totals['checks'],
                       rejected=totals['rejected'], sites=sites), stream, indent=1, ensure_ascii=False)
    print('wrote', OUTPUT)


if __name__ == '__main__':
    main()
