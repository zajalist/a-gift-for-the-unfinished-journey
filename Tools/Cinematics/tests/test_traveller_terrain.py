"""Measured terrain rotation must preserve body shape and the authored sun look."""
from pathlib import Path
import math
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import samyor_final as final
import samyor_reveal as rig
import traveller_contacts as contacts
import traveller_gaze as gaze
import traveller_terrain as terrain
import ending_staging as staging


def test_measured_frame_is_small_and_does_not_lift_the_waypoint():
    assert terrain.SLOPE_DEGREES == pytest.approx(5.2641645, abs=.000001)
    assert abs(terrain.ORIGIN_LIFT_CM)<.003
    assert terrain.ORIGIN == (297700., 482700., 10971.)


@pytest.mark.parametrize('at', (0., 1., 2., 3.8))
def test_alignment_is_one_rigid_transform_for_all_body_vertices_and_props(at):
    flat, posed=final.flat_pose_at(at),final.pose_at(at)
    for bone in rig.ORDER:
        if bone!='root':assert posed[bone]==flat[bone]
    for mesh in ('tripo_mesh_8efd9b8d.001','tripo_mesh_88102862.001'):
        original=contacts.skin(flat,mesh)
        recovered=terrain.untilted_points(contacts.skin(posed,mesh),staging.SUN_BEARING-90)
        assert np.linalg.norm(original-recovered,axis=1).max()<.00001


def test_head_still_points_at_the_visible_sun_after_ground_alignment():
    head=rig.fk(final.pose_at(0))['Head']
    local=rig.qrot(head[1],gaze.HEAD_FORWARD)
    world=rig.qrot(rig.qaxis((0,0,1),staging.SUN_BEARING-90),local)
    assert world==pytest.approx(gaze.direction(staging.SUN_BEARING,2.7),abs=1e-7)
