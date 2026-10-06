"""Rigid ending pose alignment to the measured October 1 collapse terrain.

The 31 current-landscape collision samples fit this plane with 0.197 cm RMS
and 0.732 cm maximum residual. This rotates the complete skeleton and props;
it does not change the actor waypoint, joint lengths or individual contacts.
Evidence: Saved/Verification/dawn_composition_20261001/terrain_readbacks.
"""
import math

import numpy as np

import samyor_reveal as rig

ORIGIN = (297700.0, 482700.0, 10971.0)
# z relative to ORIGIN = A * world_dx + B * world_dy + INTERCEPT_CM.
A, B, INTERCEPT_CM = -0.02643804, -0.08826181, 0.00406738
NORMAL = rig.vnorm((-A, -B, 1.0))
WORLD_TILT = rig.qfromto((0, 0, 1), NORMAL)
SLOPE_DEGREES = math.degrees(math.acos(NORMAL[2]))
# The original clearance is vertical on a flat plane. Preserve 0.4 cm vertical
# clearance after rotation, rather than lifting the character by the slope.
ORIGIN_LIFT_CM = INTERCEPT_CM + 0.4 - 0.4 / NORMAL[2]


def local_tilt(actor_yaw, amount=1.0):
    spin = rig.qaxis((0, 0, 1), actor_yaw)
    tilt = rig.qslerp((0, 0, 0, 1), WORLD_TILT, amount)
    return rig.qnorm(rig.qmul(rig.qmul(rig.qconj(spin), tilt), spin))


def align(pose, actor_yaw, amount=1.0):
    """Rotate the entire hierarchy in component space, blended from identity."""
    if amount <= 0:
        return dict(pose)
    amount = min(1.0, amount)
    local = dict(pose)
    world = rig.fk(local)
    root, parent = world['root'], world[rig.PARENT['root']]
    tilt = local_tilt(actor_yaw, amount)
    target = rig.vadd(rig.qrot(tilt, root[0]), (0, 0, ORIGIN_LIFT_CM * amount))
    delta = rig.qrot(rig.qconj(parent[1]), rig.vsub(target, parent[0]))
    position = tuple(delta[i] / parent[2][i] for i in range(3))
    rotation = rig.qmul(rig.qconj(parent[1]), rig.qmul(tilt, root[1]))
    local['root'] = (position, rig.qnorm(rotation), local['root'][2])
    return local


def clearances(points, actor_yaw):
    """Vertical centimetres above the fitted current-terrain plane."""
    yaw = math.radians(actor_yaw)
    x = points[:, 0] * math.cos(yaw) - points[:, 1] * math.sin(yaw)
    y = points[:, 0] * math.sin(yaw) + points[:, 1] * math.cos(yaw)
    return points[:, 2] - (A*x + B*y + INTERCEPT_CM)


def untilted_points(points, actor_yaw, amount=1.0):
    """Read-only inverse for checking that no anatomy changed during alignment."""
    rotation = np.array([rig.qrot(local_tilt(actor_yaw, amount), axis)
                         for axis in ((1, 0, 0), (0, 1, 0), (0, 0, 1))]).T
    return (points - (0, 0, ORIGIN_LIFT_CM * amount)) @ rotation
