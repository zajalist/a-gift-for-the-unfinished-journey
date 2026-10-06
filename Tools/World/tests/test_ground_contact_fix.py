import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
import prepare_ground_contact_fix as fix

POSE = '(Rotation=(X=0,Y=0,Z=0,W=1),Translation=(X=10,Y=20,Z=100),Scale3D=(X=2,Y=2,Z=2))'


def selection():
    return dict(component='/Game/Cart.Mesh', mesh='/Game/Cart', instance=None, transform=POSE)


def measurement(clearances, status='landscape'):
    return dict(rows=[dict(status='measured', selected=dict(selection(), local_contacts=[[0, 0, 0]]*len(clearances)),
        owner=dict(path='/Game/Cart', package='/Game/CartPackage'),
        samples=[dict(kind='authored_contact', down=dict(status=status,
            hits=[dict(landscape=True, clearance_cm=c)])) for c in clearances])])


def test_current_pose_transform_and_real_vertex_selection():
    pose = fix.pose_parts(POSE)
    assert fix.world_point([1, 2, 3], pose) == [12, 24, 106]
    points = [[x, y, z] for x in (-1, 0, 1) for y in (-1, 0, 1) for z in (-2, 2)]
    result = fix.select_contacts(selection(), dict(path='/Game/Cart', lod=0, truncated=False, vertices=points, counts={'vertices': len(points)}))
    assert len(result['local_contacts']) == 9
    assert all(p[2] == -2 and p in points for p in result['local_contacts'])


def test_incomplete_or_wrong_render_data_is_refused():
    with pytest.raises(ValueError, match='complete LOD0'):
        fix.select_contacts(selection(), dict(path='/Game/Cart', lod=0, truncated=True))


def test_transport_truncation_cannot_masquerade_as_complete_handler_result(tmp_path):
    import json
    extract = dict(path='/Game/Cart', lod=0, truncated=False, vertices=[[0, 0, 0]]*50,
                   counts={'vertices': 810}, _truncated=[{'path': 'vertices', 'kind': 'array', 'removed': 760}])
    with pytest.raises(ValueError, match='Transport truncated'):
        fix.select_contacts(selection(), extract)
    source = tmp_path / 'extract.json'
    source.write_text(json.dumps(extract), encoding='utf-8')
    with pytest.raises(ValueError, match='Transport truncated'):
        fix.unwrap(source)
    del extract['_truncated']
    with pytest.raises(ValueError, match='complete mesh count'):
        fix.select_contacts(selection(), extract)


def test_vertical_fix_preserves_pose_and_uses_lowest_current_clearance():
    plan = fix.vertical_plan(measurement([25, 30, 40]))
    assert plan['delta_z_cm'] == -28
    assert plan['preserve_xy_rotation_scale']
    with pytest.raises(ValueError, match='already touches'):
        fix.vertical_plan(measurement([0, 30, 40]))
    with pytest.raises(ValueError, match='current landscape hit'):
        fix.vertical_plan(measurement([25, 30, 40], status='no_landscape_hit'))


def test_supported_or_excessive_move_is_refused():
    supported = measurement([25, 30, 40])
    supported['rows'][0]['samples'][0]['down']['hits'][0]['landscape'] = False
    with pytest.raises(ValueError, match='Intervening support'):
        fix.vertical_plan(supported)
    with pytest.raises(ValueError, match='exceeds'):
        fix.vertical_plan(measurement([225, 230, 240]))
    assert 'pose changed' in fix.APPLY
    assert 'Support/terrain changed; no move' in fix.APPLY
    assert "'saved': False" in fix.APPLY
