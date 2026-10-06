from pathlib import Path
import sys
import math
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import samyor_dawn_turn as turn
import samyor_final as final
import samyor_reveal as rig
import traveller_contacts as contacts
import ending_staging as staging
import build_cinematics as builder
import traveller_terrain as terrain


def test_turn_actor_and_steps_share_one_clock_and_end_before_replies():
    keys=builder.radio_body_transform(builder.radio_post(),207)
    at={k[0]:k for k in keys}
    for i in range(turn.FRAMES+1):
        t=i/turn.FPS
        expected=at[staging.TURN_AT][6]+turn.DELTA*staging.turn_fraction(t)
        assert at[staging.TURN_AT+t][6]==pytest.approx(expected)
    assert at[staging.COLLAPSE_AT][6]+90==pytest.approx(staging.SUN_BEARING)
    assert staging.COLLAPSE_END<107


def test_support_foot_steps_are_planted_and_rigid_terrain_settle_is_bounded():
    base=rig.fk(final.flat_pose_at(0))
    for i in range(turn.FRAMES+1):
        t=i/turn.FPS
        pose=turn.pose_at(t);world=rig.fk(pose)
        flat=rig.fk(turn.flat_pose_at(t))
        spin=rig.qaxis((0,0,1),turn.DELTA*staging.turn_fraction(t))
        side='Left' if t<1.0 else 'Right'
        actual=rig.qrot(spin,world[side+'Foot'][0])
        planted=rig.qrot(spin,flat[side+'Foot'][0])
        expected=rig.fk(turn.START)[side+'Foot'][0]
        if side=='Right':expected=rig.qrot(rig.qaxis((0,0,1),turn.DELTA),base[side+'Foot'][0])
        assert planted[:2]==pytest.approx(expected[:2],abs=.003)
        # The complete rigid frame rolls the boot with the 5.264-degree slope;
        # its ankle follows an arc of at most 1.18 cm, rather than sliding a step.
        assert math.dist(actual[:2],planted[:2])<1.2
        yaw=staging.arrival_yaw(turn.POST)+turn.DELTA*staging.turn_fraction(t)
        clearance=terrain.clearances(contacts.skin(pose),yaw).min()
        if t>=.55:assert clearance==pytest.approx(.4,abs=.02)
        else:assert clearance> -1.5  # preserved measured walk handoff, then smooth contact


def test_turn_endpoint_meets_collapse_pose_without_a_height_or_hand_jump():
    a,b=rig.fk(turn.pose_at(staging.TURN_SECONDS)),rig.fk(final.pose_at(0))
    for bone in ('Head','Hips','LeftFoot','RightFoot','staff011','recorder011'):
        assert a[bone][0]==pytest.approx(b[bone][0],abs=.003)
        assert abs(sum(x*y for x,y in zip(a[bone][1],b[bone][1])))==pytest.approx(1,abs=1e-5)


def test_turn_begins_in_the_measured_actual_walk_exit_pose():
    import numpy as np
    a=contacts.skin(turn.pose_at(0));b=contacts.skin(contacts.ground(turn.START,.4))
    assert np.linalg.norm(a-b,axis=1).max()<.003


def test_camera_sees_the_sun_then_returns_before_the_turn_and_fall():
    keys=builder.plan_cin24()['cams'][0]['keys']
    sun=next(k for k in keys if k[0]==92.7)
    assert sun[6]==staging.SUN_BEARING
    assert sun[-1]=='constant'
    settled=next(k for k in keys if k[0]==staging.TURN_AT)
    assert settled[1:7]==keys[-1][1:7]
    assert settled[-1]=='constant'
    assert all(k[1:4]==keys[1][1:4] for k in keys[1:])
