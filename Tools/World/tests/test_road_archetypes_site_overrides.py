import sys
from pathlib import Path


WORLD_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORLD_DIR))
sys.path.insert(0, str(WORLD_DIR / 'setdress_v2_groups'))

import road_archetypes as road_group  # noqa: E402
import setdress_v2 as V  # noqa: E402


def test_l10_override_reduces_field_terrace_runs_and_keeps_contact_clean():
    world = V.B.World()
    candidate, totals = road_group.build_sites(world, ['L10_FootFarm'])
    default, _ = V.build(world, ['L10_FootFarm'])
    candidate = candidate[0]
    default = default[0]

    candidate_terraces = [p for p in candidate['placements'] if p.get('group') == 'terraces']
    default_terraces = [p for p in default['placements'] if p.get('group') == 'terraces']
    candidate_yard = [p for p in candidate['placements'] if p.get('group') == 'yards']

    assert road_group.SITE_OVERRIDES == {
        'L10_FootFarm': {'fields': 1, 'seed': 'L10v2.1-3'}
    }
    assert len(candidate_terraces) < len(default_terraces)
    assert candidate_yard
    assert candidate['counts']['placements'] == 254
    assert candidate['offline_check']['violations'] == []
    assert candidate['offline_check']['waived'] == []
    assert totals['rejected'] == []


def test_unoverridden_road_site_keeps_default_composition():
    world = V.B.World()
    generated, _ = road_group.build_sites(world, ['L05_RidgeHamlet'])
    direct, _ = V.build(world, ['L05_RidgeHamlet'])

    assert generated[0]['placements'] == direct[0]['placements']
    assert generated[0]['offline_check'] == direct[0]['offline_check']
