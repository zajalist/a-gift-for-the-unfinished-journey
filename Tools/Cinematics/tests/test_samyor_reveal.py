"""Offline checks for CIN_19's exterior reveal and its measured body motion. No editor.

    python -m pytest Tools/Cinematics/tests -q -p no:cacheprovider

The capsule (SK_Carrier, editor lane 2026-09-29): x -394..-200, |y| <= 45, floor 30, the lid's top 166 -> 89 toward
the rear, flat ~123 around the LidNotes plane at x -305. The eye and every hand target must be inside it, under the lid
while it is shut, and on the lid / rim where the hands hold them.
"""
import math
import sys
from pathlib import Path

import pytest

CIN = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CIN))
import samyor_reveal as sr  # noqa: E402

G0 = sr.G0
STEPS = [i / 10.0 for i in range(0, 361)]


def inside(p, slack=0.0, lid_closed=True):
    x, y, z = p[0], p[1], p[2] - G0
    if not (sr.CAP_X[0] - slack <= x <= sr.CAP_X[1] + slack and abs(y) <= sr.CAP_Y + slack and z >= sr.CAP_FLOOR - slack):
        return False
    return z <= sr.lid_under(x) + slack if lid_closed else True


def test_timing_is_kept():
    assert (sr.T_OPEN, sr.T_RISE, sr.T_CLOSE, sr.DURATION) == (8.2, 30.5, 34.4, 36.0)
    assert sr.CLIPS[0][1] == 0.0 and sr.CLIPS[-1][2] == sr.DURATION


def test_profile_matches_the_measurement():
    assert sr.lid_top(-394.0) == pytest.approx(89.0) and sr.lid_top(-200.0) == pytest.approx(166.0)
    assert sr.lid_under(sr.NOTES_X) == pytest.approx(123.0, abs=3.0)
    assert sr.SC["hinge"][2] - G0 == pytest.approx(sr.lid_under(sr.SC["hinge"][0]), abs=3.0)


def test_standing_pose_uses_ground_beside_capsule():
    stand_hip_z = sr.STAGES[-1][1][2] + G0
    assert stand_hip_z - sr.SC["g_stand"] == pytest.approx(92.0)


def test_first_view_is_the_notes():
    eye, (r, p, y) = sr.camera(0.0)
    gap = sr.lid_under(eye[0]) - (eye[2] - G0)
    assert -335.0 <= eye[0] <= -280.0, "under the flat of the lid"
    assert 25.0 <= gap <= 35.0, gap
    fwd = sr.qrot(sr.q_rotator(r, p, y), (1.0, 0.0, 0.0))
    k = (G0 + sr.lid_under(sr.NOTES_X) - eye[2]) / fwd[2]      # where the view's centre meets the lid
    assert abs(eye[0] + fwd[0] * k - sr.NOTES_X) < 25.0


def test_eye_inside_while_lying():
    for t in STEPS:
        if t > 13.5:
            break
        eye = sr.camera(t)[0]
        assert inside(eye), (t, eye)
        assert sr.lid_under(eye[0]) - (eye[2] - G0) >= 20.0, t


def test_hands_inside_the_capsule_until_he_leaves():
    for t in STEPS:
        if t > 22.0:
            break
        for side in "LR":
            h = sr.hand_world(side, t)
            assert inside(h, slack=4.0, lid_closed=t < 9.3), (side, t, h)


def test_contacts_lie_on_the_geometry():
    assert sr.LATCH == pytest.approx((-308.109021,-41.756520,G0+112.806404))
    assert sr.SC['hinge'][1] == -45.0
    assert inside(sr.LATCH, slack=0.5)
    for side, keys in sr.HANDS.items():
        for t, tg in keys:
            if tg[0] == "w" and abs(abs(tg[1][1]) - sr.RIM_Y) < 1e-6:   # a rim grip
                x, _, z = tg[1]
                assert sr.CAP_X[0] < x < sr.CAP_X[1] and z - G0 == pytest.approx(sr.rim_z(x)), (side, t)
            elif tg[0] == "lid":
                x, y = tg[1], tg[2]
                assert sr.CAP_X[0] < x < sr.CAP_X[1] and abs(y) < sr.CAP_Y
                assert sr.lid_point(0.0, x, y)[2] - G0 == pytest.approx(112.806404)
            elif tg[0] == "w":
                assert inside(tg[1], slack=1.0), (side, t, tg)


@pytest.mark.parametrize("t", [4.8, 5.9, 6.6, 7.4, 8.5, 9.6, 14.6, 16.0, 19.8, 21.5, 24.5, 26.0, 30.5])
def test_hands_reach_what_they_hold(t):
    w = sr.fk(sr.pose_at(t, {}))
    for side, bone in (("L", "LeftHand"), ("R", "RightHand")):
        assert sr.vlen(sr.vsub(w[bone][0], sr.hand_target(side, t))) < 4.0, (side, t)


def test_body_anchor_faces_the_exit_side():
    # This is an uncut motion reference, not a first-person view. The drone's
    # view is tested independently; the body should face the door as it exits.
    for t in STEPS:
        if t < 21.5:
            continue
        _, (r,p,y) = sr.camera(t)
        f = sr.qrot(sr.q_rotator(r,p,y),(1.0,0.0,0.0))
        assert f[1] <= 0.05,t


def test_staff_waits_outside_the_rim():
    assert sr.STAFF_FOOT[1] < -sr.CAP_Y and sr.GRIP_PT[1] < -sr.CAP_Y
    assert sr.CAP_X[0] < sr.STAFF_FOOT[0] < sr.CAP_X[1]


def test_only_the_exterior_drone_is_cut_to_and_body_anchor_stays_separate():
    plan = sr.plan()
    assert plan['shots'] == [(0.0, sr.DURATION, sr.VIEW_CAM)]
    assert [c['name'] for c in plan['cams']] == [sr.VIEW_CAM]
    assert sr.CAM != sr.VIEW_CAM
    assert 'fade' not in plan
    assert sr.CAM in plan['extra']['10_body_anchor.py']
    assert sr.CAM in plan['extra']['20_body.py']
    for code in plan['extra'].values():
        compile(code, '<ending chunk>', 'exec')
    for t in STEPS:
        loc, _ = sr.exterior_camera(t)
        assert loc[1] < -sr.CAP_Y - 300.0
        assert loc[2] > sr.G0 + 200.0


def test_exterior_animation_preserves_full_head_at_every_stage():
    for t in (0.0, 8.2, 16.0, 23.5, 30.5, 36.0):
        pose = sr.pose_at(t, {})
        assert pose['Neck'][2] == sr.REF_LOCAL['Neck'][2]
        assert pose['Head'][2] == sr.REF_LOCAL['Head'][2]


def test_side_hatch_follows_the_imported_rotation_axis_and_sign():
    closed = sr.lid_point(0.0,-312.0,-56.0)
    opened = sr.lid_point(13.5,-312.0,-56.0)
    assert closed == pytest.approx((-312.0,-56.0,sr.G0+112.806404))
    # Sampled asset q=(.8192,0,0,.5736), relative to closed +5deg X.
    delta = sr.qaxis((0,-1,0),105.0)
    expected = sr.vadd(sr.SC['hinge'],sr.qrot(delta,sr.vsub(closed,sr.SC['hinge'])))
    assert opened == pytest.approx(expected,abs=0.001)


def test_closed_capsule_contains_the_full_body_and_clothing():
    import traveller_contacts as contacts
    for t in (0.0,4.8,6.6,8.2):
        points=contacts.skin(sr.pose_at(t,{}))
        transform=sr.body_xf(t)
        points=points@contacts.rotation(transform[1]).T+transform[0]
        assert points[:,1].min() >= -sr.CAP_Y
        assert points[:,1].max() <= sr.CAP_Y
        assert points[:,2].min() >= sr.G0+sr.CAP_FLOOR-1.0
        assert points[:,0].min() >= sr.CAP_X[0]
        assert points[:,0].max() <= sr.CAP_X[1]
