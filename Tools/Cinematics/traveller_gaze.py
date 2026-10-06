"""Aim the measured anatomical head forward without changing hands or hips."""
import math
import samyor_reveal as rig

HEAD_FORWARD = rig.vnorm(rig.qrot(rig.qconj(rig.REF_W['Head'][1]), (0, 1, 0)))
EYE_LOCAL = rig.qrot(rig.qconj(rig.REF_W['Head'][1]),
                    rig.vsub(rig.EYE_CS, rig.REF_W['Head'][0]))


def direction(bearing, elevation):
    yaw, pitch = math.radians(bearing), math.radians(elevation)
    return (math.cos(yaw)*math.cos(pitch), math.sin(yaw)*math.cos(pitch), math.sin(pitch))


def aim(local, target, amount=1.0):
    if amount <= 0:
        return local
    local = dict(local)
    world = rig.fk(local)
    delta = rig.qfromto(rig.qrot(world['Head'][1], HEAD_FORWARD), target)
    neck_delta = rig.qslerp((0, 0, 0, 1), delta, .7*amount)
    rig.set_world_rot(local, world, 'Neck', rig.qmul(neck_delta, world['Neck'][1]))
    world = rig.fk(local)
    delta = rig.qfromto(rig.qrot(world['Head'][1], HEAD_FORWARD), target)
    head_delta = rig.qslerp((0, 0, 0, 1), delta, amount)
    rig.set_world_rot(local, world, 'Head', rig.qmul(head_delta, world['Head'][1]))
    return local
