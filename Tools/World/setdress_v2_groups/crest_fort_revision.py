"""A scoped skyline repair for the S10 fort's repeated full-height wall panels.

The generated site already has a gate, contact-checked debris and a useful path.
Changing the block grammar would renumber hundreds of pieces, so this revision
only swaps selected wall meshes at their existing centres and keeps their IDs.
"""

import copy


# Index -> (expected original key, replacement key).  The 1 m panels become
# buried stumps; the broken 1.38 m courses interrupt the otherwise regular
# 4 m silhouette.  A few high fragments remain around the gate and keep.
WALL_REPAIRS = {
    2: ('AB_300x400_Mid', 'B01_wall01'),
    27: ('AB_300x400_Mid', 'AB_300x100_Panel'),
    32: ('AB_Fort_Wall_Mid', 'B01_wall01'),
    37: ('AB_300x400_Mid', 'AB_300x100_Panel'),
    54: ('AB_Fort_Wall_Mid', 'B01_wall01'),
    72: ('AB_Fort_Wall_Mid', 'AB_300x100_Panel'),
    109: ('AB_Fort_Wall_Mid', 'B01_wall01'),
    304: ('AB_Fort_Wall_Mid', 'AB_300x100_Panel'),
    309: ('AB_Fort_Wall_Mid', 'B01_wall01'),
    314: ('AB_Fort_Wall_Mid', 'AB_300x100_Panel'),
    353: ('AB_Fort_Wall_Mid', 'B01_wall01'),
}


def revise_s10(site, catalog, offline_check, world):
    """Return an S10 site with a broken skyline and unchanged authored IDs.

    A source drift guard prevents this patch from silently modifying a changed
    fort.  The offline ground-contact judge is run again on the actual result.
    """
    if site['id'] != 'S10_CrestFort':
        return site
    site = copy.deepcopy(site)
    by_id = {p['id']: p for p in site['placements']}
    if len(by_id) != len(site['placements']):
        raise RuntimeError('S10 placement IDs are not unique')
    for index, (old_key, new_key) in WALL_REPAIRS.items():
        placement_id = 'S10_CrestFort_v2_%03d' % index
        p = by_id.get(placement_id)
        if not p or p['key'] != old_key or p['cat'] != 'wall' or p['scale'] != 1.0:
            raise RuntimeError('S10 wall source changed at ' + placement_id)
        asset = catalog[new_key]
        scale = 0.75 if new_key == 'B01_wall01' else 1.0
        # The Bazaar panels' length is local Y. B01's length is local X.
        if new_key == 'B01_wall01':
            p['yaw'] = round((p['yaw'] + 90.0) % 360.0, 1)
        sink = min(p['settle']['sink_cm'], 24.0 if new_key == 'B01_wall01' else 30.0)
        p['settle']['sink_cm'] = sink
        p.update(key=new_key, asset=asset['path'], scale=scale,
                 scale_range=[scale, scale], state='low' if scale < 1 else 'stump',
                 size_m=[round(n * scale / 100.0, 3) for n in asset['size_cm']],
                 vis_h=round(asset['size_cm'][2] * scale / 100.0 - sink / 100.0, 2),
                 note='S10 skyline repair: surviving broken course, not a repeated full-height slab')
    violations, waived = offline_check(world, site)
    site['offline_check'] = dict(violations=[list(v) for v in violations],
                                 waived=[list(v) for v in waived],
                                 note='estimated offline after scoped S10 wall repair; editor check2 required')
    if violations:
        raise RuntimeError('S10 wall repair lost ground contact: %s' % violations[:3])
    site['layout'] += '\nV2 skyline repair: irregular broken courses interrupt the repeated standing walls.'
    return site
