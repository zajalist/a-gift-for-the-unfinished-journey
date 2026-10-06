import sys
from pathlib import Path


WORLD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORLD))
sys.path.insert(0, str(WORLD / 'setdress_v2_groups'))

import road_archetypes as road  # noqa: E402
import setdress_v2 as V  # noqa: E402


def test_fort_skyline_breaks_up_without_moving_or_floating_props():
    world = V.B.World()
    original, _ = V.B.build(world, [V.compose(world, 'S10_CrestFort')])
    revised, _ = road.build_sites(world, ['S10_CrestFort'])
    before = {p['id']: p for p in original[0]['placements']}
    after = {p['id']: p for p in revised[0]['placements']}

    assert set(before) == set(after)
    assert all(revised[0]['counts'][key] == original[0]['counts'][key]
               for key in ('placements', 'actors', 'ism_instances', 'physics', 'batch01'))
    assert revised[0]['offline_check']['violations'] == []
    assert revised[0]['offline_check']['waived'] == []
    changed = [id_ for id_ in before if before[id_]['key'] != after[id_]['key']]
    assert len(changed) == 11
    assert all((before[id_]['x_cm'], before[id_]['y_cm'], before[id_]['ground_z_cm']) ==
               (after[id_]['x_cm'], after[id_]['y_cm'], after[id_]['ground_z_cm']) for id_ in before
               if before[id_]['cat'] == 'wall')
    assert sum(p['vis_h'] >= 3.5 for p in before.values() if p['cat'] == 'wall') > \
           sum(p['vis_h'] >= 3.5 for p in after.values() if p['cat'] == 'wall')
    assert next(p for p in after.values() if p['id'].endswith('_000'))['key'] == 'AB_Side_Arch'
    assert next(p for p in after.values() if p['id'].endswith('_094'))['key'] == 'AB_Fort_Wall_Mid'
