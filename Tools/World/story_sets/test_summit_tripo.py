"""Offline clearance checks for the High Voice hut's scripted doorway shot."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import summit_tripo as summit  # noqa: E402


def test_relay_anchors_and_baked_meshes():
    doc = summit.make()
    a = doc['anchor']
    placements = doc['sites'][0]['placements']
    assert a['hut_yaw'] == a['outward_yaw'] == placements[1]['yaw']
    assert 2 <= a['plinth_top_cm'] - summit.ground(*a['doorway_cm'][:2]) <= 12
    assert a['plinth_height_cm'] < 65
    assert 50 <= a['floor_camera_cm'][2] - summit.ground(*a['floor_camera_cm'][:2]) <= 60
    for item in placements:
        assert item['material_set'] in ('stone', 'wood')
        asset_file = Path(summit.ROOT, 'Content', item['asset'].removeprefix('/Game/') + '.uasset')
        assert asset_file.is_file(), item['asset']


def test_doorway_and_walk_line_remain_clear():
    doc = summit.make()
    items = doc['sites'][0]['placements']
    # The doorway's central lane stays empty from the door to the desk.
    # The chair and storage stay on its sides; the desk begins well behind it.
    for item in items[2:]:
        xy = (item['x_cm'], item['y_cm'])
        dx, dy = xy[0] - summit.C[0], xy[1] - summit.C[1]
        import math
        theta = math.radians(summit.YAW)
        x = dx * math.cos(theta) + dy * math.sin(theta)
        y = -dx * math.sin(theta) + dy * math.cos(theta)
        assert abs(x) + item['size_m'][0] * 50 < 225
        assert abs(y) + item['size_m'][1] * 50 < 178.35
        if y > -65:
            assert x - item['size_m'][0] * 50 > 60 or x + item['size_m'][0] * 50 < -60


def test_look_points_and_mesh_budget():
    doc = summit.make()
    views = {v['name']: v for v in doc['sites'][0]['views']}
    assert {'walk_far', 'walk_near', 'front', 'rear', 'left', 'right', 'floor'} <= set(views)
    assert len(doc['sites'][0]['placements']) <= 8
    assert all(not p['ism'] for p in doc['sites'][0]['placements'])
