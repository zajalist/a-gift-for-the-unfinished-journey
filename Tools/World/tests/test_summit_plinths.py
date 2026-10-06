import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0,str(Path(__file__).parents[1]/'story_sets'))
import prepare_summit_plinths as plinths


def test_gate_stones_preserve_open_centre():
    contacts=[[-65,-184,1],[27,-183,1],[-66,72,1],[26,184,1]]
    rects=plinths.support_rects('Gate',contacts)
    assert len(rects)==2
    assert rects[0]['max'][1] <= -60
    assert rects[1]['min'][1] >= 60
    assert all(r['max'][axis]-r['min'][axis]>=40 for r in rects for axis in range(2))
    with pytest.raises(AssertionError,match='clear corridor'):
        plinths.support_rects('Gate',contacts+[[0,61,0]])


def test_plinth_covers_low_ground_and_prop_stays_upright_at_shared_top():
    contacts=[[-30,-30,0],[30,-30,1],[30,30,0],[-30,30,1]]
    rects=plinths.support_rects('Transmitter',contacts)
    hits=[[{'z':z} for z in [100,104,108,112,116,120,124,128,132]]]
    pads,body_z=plinths.support_geometry(rects,hits,contacts,plinths.FLOOR_BOUNDS)
    pad=pads[0]
    assert pad['bottom']==92
    assert pad['top']==137
    assert body_z==136.5
    assert math.isclose(pad['z']+plinths.FLOOR_BOUNDS[0][2]*pad['scale'][2],92)
    assert math.isclose(pad['z']+plinths.FLOOR_BOUNDS[1][2]*pad['scale'][2],137)


def test_incomplete_or_excessive_supports_refused():
    contacts=[[-1,-1,0],[1,1,0]]
    rects=plinths.support_rects('Fence',contacts)
    with pytest.raises(AssertionError,match='3x3'):
        plinths.support_geometry(rects,[[{'z':100}]],contacts,plinths.FLOOR_BOUNDS)
    with pytest.raises(AssertionError,match='75cm'):
        plinths.support_geometry(rects,[[{'z':0}]*8+[{'z':100}]],contacts,plinths.FLOOR_BOUNDS)


def test_gate_two_footings_share_a_level_top():
    contacts=[[-20,-180,1],[20,-180,1],[-20,180,0],[20,180,0]]
    rects=plinths.support_rects('Gate',contacts)
    pads,_=plinths.support_geometry(rects,[[{'z':100}]*9,[{'z':135}]*9],contacts,plinths.FLOOR_BOUNDS)
    assert pads[0]['top']==pads[1]['top']==140
    assert pads[0]['height']>pads[1]['height']


def test_apply_requires_receipt_and_explicit_upright_rotation():
    code=plinths.script({'id':'Transmitter'},10921)
    assert 'EXPECTED=None' in code
    assert "unreal.Rotator(pitch=0.0,yaw=ROW['yaw'],roll=0.0)" in code
    assert code.index("Current terrain changed since survey") < code.index('eas.spawn_actor_from_class')
    assert 'save_packages' not in code
    assert 'destroy_actor' not in code
    assert "TAG in [str(t) for t in matches[0].tags]" in code
    assert "a['xy']==b['xy']" in code
    assert "if PHASE=='verify':" in code
    assert "'surface_contact_pass'" in code
    assert "support in old_pads" in code
