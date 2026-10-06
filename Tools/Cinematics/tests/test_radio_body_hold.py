from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import build_cinematics as builder


def test_radio_actor_holds_until_notice_dialogue_finishes_then_turns_in_place():
    post=builder.radio_post()
    rows=builder.radio_body_transform(post,207)
    keys={row[0]:row for row in rows}
    assert keys[7.0][-1]=='constant'
    assert keys[80.0][1:7]==pytest.approx(keys[7.0][1:7])
    assert keys[80.0][-1]=='linear'
    assert keys[83.8][1:4]==pytest.approx(post['inside'])
    assert abs(keys[83.8][6]-keys[80.0][6])<180


def test_exit_moves_instead_of_holding_then_teleporting_to_door():
    rows=builder.radio_body_transform(builder.radio_post(),207)
    keys={row[0]:row for row in rows}
    assert keys[83.8][-1]=='linear'
    assert all(abs(b[6]-a[6])<180 for a,b in zip(rows,rows[1:]))
    still=builder.radio_body_transform(builder.radio_post(),108,True)
    assert rows[-1][1:7]==pytest.approx(still[0][1:7])


def test_grounded_drone_holds_after_landing_then_turns_as_samyor_exits():
    plan=builder.plan_cin24()
    keys={row[0]:row for row in plan['cams'][0]['keys']}
    assert keys[5.0][-1]=='constant'
    assert keys[builder.FL_SEATED_AT][-1]=='cubic'
    assert keys[5.0][1:4]==pytest.approx(keys[builder.FL_SEATED_AT][1:4])
