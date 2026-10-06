"""Source checks for the deliberate window glance before the station exit."""
from pathlib import Path
import math
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import samyor_notice as notice
import samyor_reveal as rig
import build_cinematics as cinematics
import ast
import traveller_gaze as gaze
import ending_staging as staging


def test_notice_returns_to_loaded_transmit_pose_before_exit():
    for t in (0.0, 24.0, notice.SECTION_SECONDS):
        pose = notice.pose_at(t)
        for bone in notice.TRACKS:
            assert pose[bone][0] == notice.BASE[bone][0]
            assert abs(sum(a*b for a,b in zip(pose[bone][1], notice.BASE[bone][1]))) == pytest.approx(1.0)
            assert pose[bone][2] == notice.BASE[bone][2]


def test_notice_is_a_head_gesture_with_the_transmit_grip_preserved():
    baseline = rig.fk(notice.BASE)
    world = rig.fk(notice.pose_at(4.5))
    assert abs(sum(a*b for a,b in zip(world['Head'][1], baseline['Head'][1]))) < 0.98
    for bone in ('root', 'Hips', 'LeftHand', 'RightHand', 'staff011', 'recorder011'):
        assert world[bone] == baseline[bone]
    for i in range(notice.FRAMES+1):
        assert all(math.isfinite(v) for state in notice.pose_at(i/notice.FPS).values() for values in state for v in values)


def test_notice_packet_frames_tracks_and_generated_code(tmp_path):
    notice.emit_anims(tmp_path)
    assert notice.FRAMES / notice.FPS >= notice.SECTION_SECONDS
    assert notice.FRAMES / notice.FPS - notice.SECTION_SECONDS < 1 / notice.FPS
    assert set(notice.TRACKS) == set(rig.ORDER) - {'traveller_rig'}
    assert {'Neck', 'Head'} <= set(notice.TRACKS)
    for script in tmp_path.glob('*.py'):
        compile(script.read_text(), str(script), 'exec')


def test_cin24_notice_and_grounded_turn_cover_the_whole_exit():
    code=cinematics.plan_cin24()['extra']['20_samyor.py']
    rows=next(ast.literal_eval(n.iter) for n in ast.walk(ast.parse(code))
              if isinstance(n,ast.For) and ast.unparse(n.target)=='(clip, t0, t1)')
    assert ('A_Traveller_Transmit',5.8,59.5) in rows
    assert ('A_Samyor_LightNotice',59.5,83.8) in rows
    assert ('A_Traveller_SlowWalk',83.8,97.2) in rows
    assert ('A_Samyor_DawnTurn',staging.TURN_AT,staging.COLLAPSE_AT) in rows
    assert ('A_Samyor_FinalCollapse',staging.COLLAPSE_AT,staging.COLLAPSE_END) in rows
    assert all(a[2]==b[1] for a,b in zip(rows,rows[1:]))


def test_notice_looks_at_the_actual_visible_sun_above_the_window_horizon():
    pose=rig.fk(notice.pose_at(4.5))
    forward=rig.qrot(pose['Head'][1],gaze.HEAD_FORWARD)
    assert forward==pytest.approx(notice.TARGET,abs=1e-7)
    assert math.degrees(math.atan2(forward[1],forward[0]))+notice.BODY_YAW==pytest.approx(staging.SUN_BEARING)
    assert math.degrees(math.asin(forward[2]))==pytest.approx(.62)
