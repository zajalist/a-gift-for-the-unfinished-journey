"""Offline layout/guard checks, not current terrain or editor acceptance."""
import math
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))
import prepare_summit_expansion as expansion


def distance(p,a,b):
    d=[b[i]-a[i] for i in range(2)]
    f=max(0,min(1,sum((p[i]-a[i])*d[i] for i in range(2))/sum(v*v for v in d)))
    return math.hypot(*(p[i]-a[i]-f*d[i] for i in range(2)))


def test_all_new_props_clear_the_protected_character_paths():
    plan=expansion.plan()
    for row in plan['rows']:
        size=row['expected_size_cm'] or [45,29,27]
        radius=math.hypot(*size[:2])/2
        for route in plan['protected_paths_local_cm']:
            for a,b in zip(route,route[1:]):
                assert distance(row['local_xy_cm'],a,b)-radius>=plan['corridor_radius_cm'],row['id']


def test_scope_has_exact_new_labels_same_biofuel_and_no_existing_shell_mutation():
    rows=expansion.plan()['rows']
    assert len(rows)==18 and len({r['label'] for r in rows})==18
    assert all(r['label'].startswith(expansion.PREFIX) for r in rows)
    assert len([r for r in rows if r['asset']==expansion.FUEL])==2
    assert not any(r['asset'].endswith('s26_radio_station') for r in rows)
    assert 'save_current_level' not in expansion.EDITOR
    assert 'destroy_actor' not in expansion.EDITOR
    assert 'heightmap' in expansion.EDITOR and 'No current collision hit' in expansion.EDITOR


def test_mesh_support_points_are_measured_source_points_at_the_base():
    for row in expansion.plan()['rows']:
        if row['kind']!='mesh':continue
        assert 3<=len(row['contacts'])<=8
        assert all(-.001<=p[2]<2.001 for p in row['contacts'])
        assert len(row['source_sha256'])==64
