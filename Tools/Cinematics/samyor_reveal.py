"""Samyor's exterior hatch reveal (B19_REVEAL / CIN_19_HATCH, direction updated 2026-09-30).

An exterior drone frames the latch side while Samyor opens the lid, pulls himself up,
sits on the rim, takes his staff and stands. The 36-second action clock and authored
hand/foot contacts are retained. His full head remains visible.

The body motion uses a separate, uncut camera actor as an attachment anchor. Its
eye-shaped motion frame is only the rig used by the five authored animation clips;
the sole displayed camera is CIN19_ExteriorDrone. The arm IK targets the measured
latch, lid, rims and staff; the staff is fixed in world space until he grips it.

    python Tools/Cinematics/samyor_reveal.py emit-anims OUT   # python_run chunks: the five A_Samyor_* clips
    python Tools/Cinematics/samyor_reveal.py summary          # timeline, reach checks
The sequence itself is emitted by build_cinematics.py emit CIN_19_HATCH (plan_cin19 -> plan() here).
"""
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_cinematics as bc  # noqa: E402

REF = json.loads((HERE / "traveller_ref_pose.json").read_text(encoding="utf-8"))
FPS = 30
ANIM_DIR = "/Game/SaskartaGaea/Characters/Traveller/Anims"
SKEL = "/Game/SaskartaGaea/Characters/Traveller/SKEL_Traveller"
SK = "/Game/SaskartaGaea/Characters/Traveller/SK_Traveller"
DURATION = 36.0
CAM = "CIN19_BodyAnchor"
VIEW_CAM = "CIN19_ExteriorDrone"
HFOV = 84.0
T_OPEN = 8.2          # PlayOpenHatch cue; A_CarrierFull_OpenHatch holds the lid 1.2 s, then 105 deg by +4.0
T_RISE = 30.5         # the 'Rise.' prompt (pauses the sequence)
T_CLOSE = 34.4        # PlayCloseHatch cue (the carrier plays the close, the hiss, and the slam 2.6 s later)
CLIPS = [("A_Samyor_ReachLatch", 0.0, 7.0), ("A_Samyor_PushLid", 7.0, 13.5), ("A_Samyor_PullUp", 13.5, 21.5),
         ("A_Samyor_LegOver_Sit", 21.5, 27.5), ("A_Samyor_StaffStand", 27.5, 36.0)]
HATCH_ROLL = [-5.0] * 13 + [-5.39, -6.53, -8.36, -10.82, -13.85, -17.4, -21.41, -25.82, -30.57, -35.61, -40.88, -46.33,
                            -51.88, -57.5, -63.12, -68.67, -74.12, -79.39, -84.43, -89.18, -93.59, -97.6, -101.15,
                            -104.18, -106.64, -108.47, -109.61, -110.0]   # probed at 10 Hz, 2026-09-29

# ----------------------------------------------------------------------------- quaternions (x, y, z, w), UE's algebra


def qmul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz)


def qconj(q):
    return (-q[0], -q[1], -q[2], q[3])


def qrot(q, v):
    p = qmul(qmul(q, (v[0], v[1], v[2], 0.0)), qconj(q))
    return (p[0], p[1], p[2])


def qnorm(q):
    n = math.sqrt(sum(c * c for c in q)) or 1.0
    return tuple(c / n for c in q)


def qaxis(axis, deg):
    a = vnorm(axis)
    s = math.sin(math.radians(deg) / 2.0)
    return (a[0] * s, a[1] * s, a[2] * s, math.cos(math.radians(deg) / 2.0))


def qfromto(u, v):
    u, v = vnorm(u), vnorm(v)
    d = vdot(u, v)
    if d < -0.99999:
        ax = vcross((1.0, 0.0, 0.0), u)
        if vlen(ax) < 1e-6:
            ax = vcross((0.0, 1.0, 0.0), u)
        return qaxis(ax, 180.0)
    c = vcross(u, v)
    return qnorm((c[0], c[1], c[2], 1.0 + d))


def qslerp(a, b, t):
    d = sum(x * y for x, y in zip(a, b))
    if d < 0:
        b, d = tuple(-x for x in b), -d
    if d > 0.9995:
        return qnorm(tuple(x + (y - x) * t for x, y in zip(a, b)))
    th = math.acos(d)
    s = math.sin(th)
    wa, wb = math.sin((1 - t) * th) / s, math.sin(t * th) / s
    return tuple(wa * x + wb * y for x, y in zip(a, b))


def q_rotator(roll, pitch, yaw):
    """UE FRotator -> FQuat (FRotator::Quaternion)."""
    dr = math.pi / 360.0
    sp, cp = math.sin(pitch * dr), math.cos(pitch * dr)
    sy, cy = math.sin(yaw * dr), math.cos(yaw * dr)
    sr, cr = math.sin(roll * dr), math.cos(roll * dr)
    return (cr * sp * sy - sr * cp * cy, -cr * sp * cy - sr * cp * sy, cr * cp * sy - sr * sp * cy, cr * cp * cy + sr * sp * sy)


def vadd(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def vsub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def vmul(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def vdot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def vcross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def vlen(a):
    return math.sqrt(vdot(a, a))


def vnorm(a):
    n = vlen(a) or 1.0
    return (a[0] / n, a[1] / n, a[2] / n)


def vlerp(a, b, t):
    return tuple(x + (y - x) * t for x, y in zip(a, b))


def xf(t, q):
    return (tuple(t), tuple(q))


def xcompose(a, b):
    """a then b in a's space (UE: B * A): the child b expressed in the parent a."""
    return (vadd(a[0], qrot(a[1], b[0])), qmul(a[1], b[1]))


def xinv(a):
    qi = qconj(a[1])
    return (vmul(qrot(qi, a[0]), -1.0), qi)


def smooth(x):
    x = min(1.0, max(0.0, x))
    return x * x * (3.0 - 2.0 * x)


# ----------------------------------------------------------------------------- skeleton

BONES = REF["bones"]
ORDER = list(BONES)


def parent_of(n):
    fixed = {"traveller_rig": None, "root": "traveller_rig", "Hips": "root", "Spine": "Hips", "Spine1": "Spine",
             "Spine2": "Spine1", "Neck": "Spine2", "Head": "Neck", "HeadTop_End": "Head", "staff011": "root",
             "recorder011": "root"}
    if n in fixed:
        return fixed[n]
    for side in ("Left", "Right"):
        leg = [f"{side}UpLeg", f"{side}Leg", f"{side}Foot", f"{side}ToeBase", f"{side}Toe_End"]
        if n in leg:
            i = leg.index(n)
            return "Hips" if i == 0 else leg[i - 1]
        arm = [f"{side}Shoulder", f"{side}Arm", f"{side}ForeArm", f"{side}Hand"]
        if n in arm:
            i = arm.index(n)
            return "Spine2" if i == 0 else arm[i - 1]
        for f in ("Index", "Middle", "Pinky", "Ring", "Thumb"):
            pre = f"{side}Hand{f}"
            if n.startswith(pre):
                k = int(n[len(pre):])
                return f"{side}Hand" if k == 1 else f"{pre}{k - 1}"
    raise KeyError(n)


PARENT = {n: parent_of(n) for n in ORDER}
REF_LOCAL = {n: (tuple(v[0][0:3]), tuple(v[0][3:7]), tuple(v[0][7:10])) for n, v in BONES.items()}


def fk(local):
    w = {}
    for n in ORDER:
        t, q, s = local[n]
        p = PARENT[n]
        if p is None:
            w[n] = (t, q, s)
        else:
            pt, pq, ps = w[p]
            w[n] = (vadd(pt, qrot(pq, (t[0] * ps[0], t[1] * ps[1], t[2] * ps[2]))), qmul(pq, q),
                    (ps[0] * s[0], ps[1] * s[1], ps[2] * s[2]))
    return w


REF_W = fk(REF_LOCAL)
EYE_CS = (0.3, 11.0, 158.0)            # between the eyes, component space (Head 149.3 / HeadTop 174.3, face +Y)
HIP_TO_EYE = (10.0, 0.0, 66.0)         # the eye from the hips, camera frame (x fwd, z up), upright
OFF = ((0.0, 0.0, 0.0), q_rotator(0.0, 0.0, -90.0))   # body in the camera: mesh +Y -> camera +X
OFF = (vmul(qrot(OFF[1], EYE_CS), -1.0), OFF[1])
HELD = REF["held"]
SI_HAND = xf(HELD["SupportedIdle.RightHand.W"][0:3], HELD["SupportedIdle.RightHand.W"][3:7])
SI_STAFF = xf(HELD["SupportedIdle.staff011.W"][0:3], HELD["SupportedIdle.staff011.W"][3:7])
G_SI = xcompose(xinv(SI_HAND), SI_STAFF)
KEEP_BONES = ["LeftArm", "LeftForeArm", "LeftHand", "RightArm", "RightForeArm", "RightHand", "Neck", "staff011",
              "LeftUpLeg", "LeftLeg", "RightUpLeg", "RightLeg"] + \
             [f"{s}Hand{f}{k}" for s in ("Left", "Right") for f in ("Index", "Middle", "Ring", "Pinky", "Thumb") for k in (1, 2, 3)]


def fk_check():
    worst = 0.0
    for n, v in BONES.items():
        worst = max(worst, vlen(vsub(REF_W[n][0], tuple(v[1][0:3]))))
    return worst


# ----------------------------------------------------------------------------- the scene (road-local frame, cm)

def scene():
    pe = bc.probe_ending()
    fr = bc.road_frame(pe["cin18_road_m"])
    g0 = bc.ground_local(fr)
    cx = pe["capsule_root_local"][0]
    side = pe["keeper_side_cm"]
    gs = bc.ground_local(fr, cx, -side)
    hinge = (pe["capsule_hatch_local"][0], pe["capsule_hatch_local"][1], g0 + pe["capsule_rim_z"])
    return {"g0": g0, "cx": cx, "side": side, "g_stand": gs, "rim": g0 + pe["capsule_rim_z"], "hinge": hinge, "fr": fr}


SC = scene()
G0 = SC["g0"]
RIM = SC["rim"]


# The capsule as measured on SK_Carrier (editor lane, 2026-09-29, carrier-local cm above the feet): the pod runs from
# x -394 (rear, the head end) to -200; the closed lid's top slopes from 166 at the front to 89 at the rear and is flat
# around -335..-280 (~123-127, where the LidNotes plane sits at -305 / ~123); the side rims are the lid's seam, 45 cm
# either side of the centre line; the floor is at 30. Samyor lies on his back, head to the rear, under the flat part.
CAP_X = (-394.0, -97.3)
CAP_Y = 63.5
CAP_FLOOR = 30.0
LID_TOP = [(-394.0, 89.0), (-335.0, 124.0), (-280.0, 127.0), (-251.3, 145.0), (-200.0, 166.0)]
NOTES_X = -305.0


def lid_top(x):
    x = min(max(x, LID_TOP[0][0]), LID_TOP[-1][0])
    for (xa, za), (xb, zb) in zip(LID_TOP, LID_TOP[1:]):
        if x <= xb:
            return za + (zb - za) * (x - xa) / (xb - xa)
    return LID_TOP[-1][1]


def lid_under(x):
    """The closed lid's underside at x, above the carrier's feet (the shell is ~4 cm)."""
    return lid_top(x) - 4.0


def rim_z(x):
    """The top of the side rim at x, above the carrier's feet (the seam under the lid's edge)."""
    return lid_top(x) - 8.0


def lid_angle(t):
    """Opening angle (deg, 0 closed) of the lid at sequence time t (A_CarrierFull_OpenHatch from T_OPEN)."""
    u = (t - T_OPEN) * 10.0
    if u <= 0:
        return 0.0
    if u >= len(HATCH_ROLL) - 1:
        return 105.0
    i = int(u)
    r = HATCH_ROLL[i] + (HATCH_ROLL[i + 1] - HATCH_ROLL[i]) * (u - i)
    return -(r + 5.0)


def lid_point(t, x, y):
    """Measured side hatch contact, not the capsule roof.

    Imported OpenHatch rotates +105 degrees around mesh +X. With the actual
    carrier mesh's -90 degree yaw this is road -Y: the rear edge moves down
    and forward. The old solver used the opposite sign and a centreline hinge.
    """
    a = math.radians(lid_angle(t))
    hx, hy, hz = SC['hinge']
    dx, dz = x-hx, G0+112.806404-hz
    return (hx+dx*math.cos(a)-dz*math.sin(a), y,
            hz+dx*math.sin(a)+dz*math.cos(a))


# hip xyz above G0; camera pitch/yaw/roll; smoothstep between keys (the body rides the camera)
S_STAND = 92.0 + SC["g_stand"] - G0  # feet on measured ground beside the staged capsule
# lying: the eye 29 cm under the flat of the lid, head propped (pitch 64) so the notes at NOTES_X fill the view
EYE0_X, EYE0_GAP, LIE_PITCH = -325.0, 29.0, 64.0
_lp = math.radians(LIE_PITCH)
HIP0 = (EYE0_X - (HIP_TO_EYE[0] * math.cos(_lp) - HIP_TO_EYE[2] * math.sin(_lp)), 0.0,
        lid_under(EYE0_X) - EYE0_GAP - (HIP_TO_EYE[0] * math.sin(_lp) + HIP_TO_EYE[2] * math.cos(_lp)))
SEAT_X = -310.0                     # where he sits on the left rim, legs outside
SEAT_Z = rim_z(SEAT_X) + 5.0
STAGES = [
    (0.0, HIP0, LIE_PITCH, 0, 0), (13.5, HIP0, LIE_PITCH, 0, 0),
    (16.0, (HIP0[0] - 2, 0, HIP0[2] + 4), 44, -4, 0), (17.2, (HIP0[0] - 2, 0, HIP0[2] + 4), 42, -4, 1),
    (19.8, (HIP0[0] - 5, 0, HIP0[2] + 8), 8, -35, 0), (21.5, (HIP0[0] - 5, 0, HIP0[2] + 8), 4, -38, 0),
    (23.5, (-290, -22, SEAT_Z - 40), 22, -62, -3), (24.5, (-298, -24, SEAT_Z - 38), 20, -62, -2),
    (26.0, (SEAT_X, -50, SEAT_Z), -2, -55, 6), (27.5, (SEAT_X, -52, SEAT_Z - 2), -8, -40, 0),
    (29.0, (SEAT_X, -52, SEAT_Z - 2), -28, -62, -2), (30.5, (SEAT_X, -52, SEAT_Z - 2), -10, -42, 0),
    (32.5, (-335, -85, 100), 6, -25, 0), (34.0, (-356.5, -110, S_STAND), -6, -6, -2),
    (35.0, (-356.5, -110, S_STAND - 2), -9, -2, 2), (36.0, (-356.5, -110, S_STAND), -8, 0, 0),
]
# effort 0..1 (tremor amplitude): lying still, the latch, the push, the pulls, the rim, the stand
EFFORT = [(0.0, 0.25), (1.0, 0.5), (2.2, 0.9), (3.6, 0.5), (4.8, 1.0), (6.6, 0.6), (8.2, 1.0), (10.6, 0.7), (12.0, 0.3),
          (14.0, 0.9), (16.0, 1.0), (17.2, 0.5), (18.0, 1.0), (19.8, 0.6), (22.0, 1.0), (24.5, 0.7), (25.0, 1.0),
          (27.5, 0.4), (29.0, 0.8), (30.5, 0.4), (31.0, 1.0), (34.0, 0.8), (36.0, 0.5)]


def keyed(table, t):
    if t <= table[0][0]:
        return table[0][1]
    for a, b in zip(table, table[1:]):
        if t <= b[0]:
            u = smooth((t - a[0]) / (b[0] - a[0]))
            va, vb = a[1], b[1]
            if isinstance(va, tuple):
                return vlerp(va, vb, u)
            return va + (vb - va) * u
    return table[-1][1]


def effort(t):
    return keyed(EFFORT, t)


def camera(t):
    """(eye, (roll, pitch, yaw)) in the road-local frame at sequence time t."""
    tab = [(s[0], (s[1][0], s[1][1], s[1][2] + G0, s[2], s[3], s[4])) for s in STAGES]
    h = keyed(tab, t)
    hip, pitch, yaw, roll = h[0:3], h[3], h[4], h[5]
    e = effort(t)
    lying = 1.0 if t < 13.5 else 0.0
    breath = math.sin(2 * math.pi * t / (4.6 if t < 20 else 3.4))
    pitch += 0.35 * breath * (1 - lying) + 0.12 * e * math.sin(37.0 * t) + 0.08 * e * math.sin(23.0 * t + 1.1)
    yaw += 0.10 * e * math.sin(29.0 * t + 0.4) + 0.25 * math.sin(0.7 * t)
    q = q_rotator(roll, pitch, yaw)
    eye = vadd(hip, qrot(q, HIP_TO_EYE))
    eye = vadd(eye, (0.0, 0.0, 0.6 * breath * lying + 0.4 * breath * (1 - lying)))
    return eye, (roll, pitch, yaw)


def body_xf(t):
    eye, (r, p, y) = camera(t)
    return xcompose((eye, q_rotator(r, p, y)), OFF)


def to_body(t, p):
    return qrot(qconj(body_xf(t)[1]), vsub(p, body_xf(t)[0]))


# ----------------------------------------------------------------------------- hands, legs, staff

# a target is ('w', point) world-fixed, ('b', point) body-fixed, ('lid', r, y) on the moving lid, ('staff',) the grip
LATCH = (-308.109021, -41.756520, G0 + 112.806404)  # actual inner upper hatch vertex, reachable from the bed


def W(x, y, z):
    return ("w", (x, y, z))


def B(x, y, z):
    return ("b", (x, y, z))


def R(x, y):
    """A grip on the side rim at x (y = +-RIM_Y), world-fixed."""
    return ("w", (x, y, G0 + rim_z(x)))


REST_L, REST_R = B(30.0, 6.0, 94.0), B(-30.0, 6.0, 94.0)
BELLY_L, BELLY_R = B(12.0, 16.0, 100.0), B(-12.0, 16.0, 102.0)
RIM_Y = 45.0
# staff: propped against the capsule's left wall, its foot on the ground, leaning 16 deg in toward the capsule; it is
# placed so the grip point lies 45 cm from his right shoulder at T_GRIP (the hand closes ON the shaft, no gap)
T_GRIP = 29.8
STAFF_Q = qmul(qaxis((1.0, 0.0, 0.0), -16.0), q_rotator(0.0, 0.0, -90.0))
STAFF_ROT = qmul(STAFF_Q, SI_STAFF[1])
STAFF_UP = qrot(STAFF_ROT, (0.0, -1.0, 0.0))


def _grip_setup():
    bx = body_xf(T_GRIP)
    sh = xcompose(bx, (REF_W["RightArm"][0], (0.0, 0.0, 0.0, 1.0)))[0]
    fwd, left = qrot(bx[1], (0.0, 1.0, 0.0)), qrot(bx[1], (1.0, 0.0, 0.0))
    d = vnorm(vadd(vadd(vmul(fwd, 0.55), (0.0, 0.0, -0.8)), vmul(left, 0.05)))
    wrist = vadd(sh, vmul(d, 45.0))
    shaft = vadd(wrist, vmul(vnorm((fwd[0], fwd[1], 0.0)), 8.0))
    foot = vsub(shaft, vmul(STAFF_UP, (shaft[2] - G0) / STAFF_UP[2]))
    return wrist, foot


GRIP_PT, STAFF_FOOT = _grip_setup()
STAFF_PRE = (STAFF_FOOT, STAFF_ROT)


PUSH_X = LATCH[0]  # the near hand pushes the same measured panel contact
HANDS = {
    "L": [(0.0, BELLY_L), (1.0, BELLY_L), (2.2, B(14.0, 30.0, 118.0)), (3.6, B(14.0, 24.0, 112.0)),
          (4.8, W(LATCH[0], LATCH[1], LATCH[2])), (5.9, W(LATCH[0], LATCH[1], LATCH[2])), (6.6, W(LATCH[0], LATCH[1], LATCH[2])),
          (7.4, ("lid", PUSH_X, LATCH[1])), (9.6, ("lid", PUSH_X, LATCH[1])), (10.9, B(14.0, 44.0, 128.0)),
          (12.0, BELLY_L), (13.5, BELLY_L), (14.6, R(-318, -RIM_Y)), (16.0, R(-306, -RIM_Y)),
          (17.2, R(-306, -RIM_Y)), (19.8, R(-290, -RIM_Y)), (21.5, R(-290, -RIM_Y)),
          (23.5, R(-316, -RIM_Y)), (26.0, R(-322, -RIM_Y)), (32.0, R(-322, -RIM_Y)),
          (33.2, REST_L), (36.0, REST_L)],
    "R": [(0.0, BELLY_R), (7.0, BELLY_R), (8.2, W(-305.0,32.0,G0+80.0)),
          (10.9, W(-305.0,32.0,G0+80.0)), (12.0, BELLY_R), (13.5, BELLY_R), (14.6, R(-318, RIM_Y)),
          (16.0, R(-306, RIM_Y)), (17.2, R(-306, RIM_Y)), (19.8, R(-290, RIM_Y)),
          (21.5, R(-290, RIM_Y)), (22.6, R(-272, -RIM_Y)), (26.0, R(-282, -RIM_Y)),
          (27.8, R(-282, -RIM_Y)), (T_GRIP - 0.2, ("staff",)), (32.5, ("staff",)),
          (34.2, ("b", SI_HAND[0])), (36.0, ("b", SI_HAND[0]))],
}
CURL = {"L": [(0.0, 0.35), (4.6, 0.1), (5.2, 0.85), (6.8, 0.85), (7.3, 0.05), (10.4, 0.05), (11.6, 0.35),
              (14.4, 0.1), (15.6, 0.9), (32.0, 0.9), (32.8, 0.3), (36.0, 0.3)],
        "R": [(0.0, 0.35), (2.0, 0.1), (2.6, 0.5), (3.0, 0.2), (4.6, 0.1), (5.2, 0.85), (6.8, 0.85), (7.3, 0.05),
              (10.4, 0.05), (11.6, 0.35), (14.4, 0.1), (15.6, 0.9), (27.9, 0.9), (28.5, 0.05), (T_GRIP - 0.3, 0.1),
              (T_GRIP + 0.2, 0.95), (36.0, 0.95)]}
# legs: thigh and shin directions in body space; straight = the reference
STRAIGHT = ((0.0, 0.0, -1.0), (0.0, 0.0, -1.0))
SIT = ((0.0, 0.92, -0.38), (0.0, 0.2, -1.0))
# lying/sitting in the pod the legs lie along the floor (+X): (0, cos p, -sin p) in body space at camera pitch p
LIE = ((0.0, math.cos(_lp), -math.sin(_lp)), (0.0, math.cos(_lp) + 0.1, -math.sin(_lp)))
INPOD = ((0.0, 0.93, -0.36), (0.0, 0.8, -0.6))
LEGS = {"L": [(0.0, LIE), (13.5, LIE), (19.8, INPOD), (21.5, INPOD), (23.5, STRAIGHT), (24.6, ((0.1, 0.75, 0.35), (0.0, 0.45, -0.9))), (26.0, SIT),
              (30.8, SIT), (32.5, ((0.0, 0.4, -0.9), (0.0, 0.1, -1.0))), (34.0, STRAIGHT), (36.0, STRAIGHT)],
        "R": [(0.0, LIE), (13.5, LIE), (19.8, INPOD), (21.5, INPOD), (24.6, STRAIGHT), (26.4, SIT), (30.8, SIT), (32.5, ((0.0, 0.35, -0.94), (0.0, 0.1, -1.0))),
              (34.0, STRAIGHT), (36.0, STRAIGHT)]}


def resolve(t, tgt, staff_now):
    kind = tgt[0]
    if kind == "b":
        return tgt[1]
    if kind == "w":
        return to_body(t, tgt[1])
    if kind == "lid":
        return to_body(t, lid_point(t, tgt[1], tgt[2]))
    return to_body(t, GRIP_PT)


def hand_target(side, t):
    tab = HANDS[side]
    if t <= tab[0][0]:
        a = b = tab[0]
    else:
        a, b = tab[-1], tab[-1]
        for x, y in zip(tab, tab[1:]):
            if t <= y[0]:
                a, b = x, y
                break
    pa, pb = resolve(t, a[1], None), resolve(t, b[1], None)
    u = 1.0 if a is b else smooth((t - a[0]) / (b[0] - a[0]))
    p = vlerp(pa, pb, u)
    e = effort(t)
    k = 0.55 + 0.9 * e
    ph = 0.0 if side == "L" else 1.9
    trem = (k * math.sin(47.0 * t + ph) * 0.6 + k * math.sin(31.0 * t + 2 * ph) * 0.4,
            k * math.sin(41.0 * t + 3 * ph) * 0.5, k * math.sin(53.0 * t + ph) * 0.5)
    return vadd(p, trem)


# ----------------------------------------------------------------------------- the solver

FINGERS = ("Index", "Middle", "Ring", "Pinky", "Thumb")
CURL_DEG = (55.0, 75.0, 50.0)


def curl_axes():
    out = {}
    for side, n in (("Left", (-1.0, 0.0, 0.0)), ("Right", (1.0, 0.0, 0.0))):
        d = vsub(REF_W[f"{side}HandMiddle1"][0], REF_W[f"{side}Hand"][0])
        a = vnorm(vcross(vnorm(d), n))
        for f in FINGERS:
            for k in (1, 2, 3):
                b = f"{side}Hand{f}{k}"
                out[b] = qrot(qconj(REF_W[PARENT[b]][1]), a)
    return out


AX = curl_axes()


def set_world_rot(local, w, bone, qw):
    p = PARENT[bone]
    t, _, s = local[bone]
    local[bone] = (t, qnorm(qmul(qconj(w[p][1]), qw)), s)


def aim(local, bone, child, d):
    w = fk(local)
    cur = vsub(w[child][0], w[bone][0])
    set_world_rot(local, w, bone, qmul(qfromto(cur, d), w[bone][1]))


def arm_ik(local, side, target, pole):
    s = "Left" if side == "L" else "Right"
    w = fk(local)
    S, E0, H0 = w[f"{s}Arm"][0], w[f"{s}ForeArm"][0], w[f"{s}Hand"][0]
    a, b = vlen(vsub(E0, S)), vlen(vsub(H0, E0))
    v = vsub(target, S)
    d = min(max(vlen(v), abs(a - b) + 1.0), (a + b) * 0.995)
    dt = vnorm(v)
    along = (a * a - b * b + d * d) / (2 * d)
    h = math.sqrt(max(a * a - along * along, 0.0))
    pv = vsub(pole, S)
    perp = vsub(pv, vmul(dt, vdot(pv, dt)))
    perp = vnorm(perp) if vlen(perp) > 1e-3 else (0.0, -1.0, 0.0)
    E = vadd(vadd(S, vmul(dt, along)), vmul(perp, h))
    aim(local, f"{s}Arm", f"{s}ForeArm", vsub(E, S))
    aim(local, f"{s}ForeArm", f"{s}Hand", vsub(vadd(S, vmul(dt, d)), E))
    return d / (a + b)


def hand_world(side, t):
    """The hand target in the road-local frame (tremor included)."""
    bx = body_xf(t)
    return vadd(bx[0], qrot(bx[1], hand_target(side, t)))


def pose_at(t, staff_state):
    local = dict(REF_LOCAL)
    for side, sgn in (("L", 1.0), ("R", -1.0)):
        tgt = hand_target(side, t)
        pole = vadd(REF_W["LeftArm" if side == "L" else "RightArm"][0], (sgn * 55.0, -30.0, -35.0))
        arm_ik(local, side, tgt, pole)
        c = keyed(CURL[side], t)
        s = "Left" if side == "L" else "Right"
        for f in FINGERS:
            for k, deg in zip((1, 2, 3), CURL_DEG):
                b = f"{s}Hand{f}{k}"
                amt = c * deg * (0.55 if f == "Thumb" else 1.0)
                tt, q, sc = local[b]
                local[b] = (tt, qnorm(qmul(qaxis(AX[b], amt), q)), sc)
        if side == "L":
            # Keep the fingers along the side panel rather than through it.
            # The old wrist inherited the reaching arm's outward direction.
            contact = smooth((t-3.6)/1.2) * (1.0-smooth((t-9.6)/1.3))
            if contact > 0:
                w = fk(local)
                before = w['LeftHand'][1]
                panel_up = qrot(qaxis((0,-1,0),lid_angle(t)),(1,0,0))
                direction = qrot(qconj(body_xf(t)[1]),panel_up)
                aim(local,'LeftHand','LeftHandMiddle1',direction)
                w = fk(local)
                set_world_rot(local,w,'LeftHand',qslerp(before,w['LeftHand'][1],contact))
        th, sh = keyed([(x[0], x[1][0]) for x in LEGS[side]], t), keyed([(x[0], x[1][1]) for x in LEGS[side]], t)
        aim(local, f"{s}UpLeg", f"{s}Leg", th)
        aim(local, f"{s}Leg", f"{s}Foot", sh)
    # the right hand's final orientation: the SupportedIdle hold (continuity with the walker)
    wgt = smooth((t - 32.5) / 2.0)
    if wgt > 0:
        w = fk(local)
        set_world_rot(local, w, "RightHand", qslerp(w["RightHand"][1], SI_HAND[1], wgt))
    # the staff: world-fixed until the grip, then carried by the hand (grip offset blends to SupportedIdle's)
    w = fk(local)
    hand = (w["RightHand"][0], w["RightHand"][1])
    if t < T_GRIP:
        bx = body_xf(t)
        st = xcompose(xinv(bx), STAFF_PRE)
    else:
        if staff_state.get("G") is None:
            bx = body_xf(T_GRIP)
            staff_state["G"] = xcompose(xinv(hand), xcompose(xinv(bx), STAFF_PRE))
        g = staff_state["G"]
        u = smooth((t - 32.5) / 2.5)
        gg = (vlerp(g[0], G_SI[0], u), qslerp(g[1], G_SI[1], u))
        st = xcompose(hand, gg)
    rt = w["root"]
    lt = vmul(qrot(qconj(rt[1]), vsub(st[0], rt[0])), 1.0 / rt[2][0])
    local["staff011"] = (lt, qnorm(qmul(qconj(rt[1]), st[1])), (1.0, 1.0, 1.0))
    return local


def bake():
    """{clip: {bone: [(t, q, s) per key]}} for the five clips, 30 fps, keys at both ends."""
    out, staff_state = {}, {}
    for name, t0, t1 in CLIPS:
        n = int(round((t1 - t0) * FPS))
        tracks = {b: [] for b in KEEP_BONES}
        for i in range(n + 1):
            t = t0 + i / FPS
            local = pose_at(min(t, DURATION - 1e-3), staff_state)
            for b in KEEP_BONES:
                tracks[b].append(local[b])
        out[name] = (n, tracks)
    return out


# ----------------------------------------------------------------------------- the sequence plan (build_cinematics)

def anchor_keys():
    keys = []
    n = int(round(DURATION * FPS))
    for i in range(n + 1):
        t = i / FPS
        eye, (r, p, y) = camera(t)
        keys.append((round(t, 4), eye[0], eye[1], eye[2], r, p, y, "linear"))
    return keys


def exterior_camera(t):
    """One slow outside drift, aimed at the hatch and then Samyor's upper body."""
    u = smooth(t / DURATION)
    loc = (-640.0 - 20.0 * u, -500.0 - 20.0 * u, G0 + 240.0 - 15.0 * u)
    eye = camera(t)[0]
    follow = smooth((t - 13.5) / (DURATION - 13.5))
    target = vlerp((-305.0, -20.0, G0 + 110.0), (eye[0], eye[1], eye[2] - 35.0), follow)
    pitch, yaw = bc.look_at(loc, target)
    return loc, (0.0, pitch, yaw)


def plan() -> dict:
    keys = []
    for i in range(int(DURATION * 5) + 1):
        t = i / 5.0
        loc, rot = exterior_camera(t)
        keys.append((round(t, 4), *loc, *rot, "linear"))
    cams = [bc._cam(VIEW_CAM, bc.focal_for_hfov(62.0), keys, {}, ())]
    return {"asset": "LS_CIN_19_Hatch", "duration": DURATION, "blend_out": 0.0, "cams": cams,
            "shots": [(0.0, DURATION, VIEW_CAM)], "frame": "local", "road_m": bc.probe_ending()["cin18_road_m"],
            "window_m": None,
            "extra": {"10_body_anchor.py": anchor_chunk(), "20_body.py": body_chunk(), "30_light.py": light_chunk()}}


def anchor_chunk():
    keys = [(round(k[0] * bc.TICKS), [round(v, 3) for v in k[1:7]], k[7]) for k in anchor_keys()]
    return bc.CAMERA.format(folder=bc.FOLDER, asset="LS_CIN_19_Hatch", name=CAM,
                            focal=bc.focal_for_hfov(HFOV), t0=0.0, t1=DURATION, keys=keys, blendables=[])


BODY = """import unreal
seq = unreal.load_asset('{folder}/{asset}')
ids = {{}}
for b in seq.get_bindings():
    ids[str(b.get_display_name())] = b
b = seq.add_spawnable_from_class(unreal.SkeletalMeshActor)
b.set_display_name('Samyor_Hatch')
tmpl = unreal.MovieSceneBindingExtensions.get_object_template(b)
smc = tmpl.get_editor_property('skeletal_mesh_component')
smc.set_skeletal_mesh_asset(unreal.load_asset('{sk}'))
smc.set_editor_property('bounds_scale', 3.0)
at = b.add_track(unreal.MovieScene3DAttachTrack)
s = at.add_section()
s.set_range_seconds(0.0, {duration})
s.set_constraint_binding_id(seq.get_binding_id(ids['{cam}']))
tr = b.add_track(unreal.MovieScene3DTransformTrack)
sec = tr.add_section()
sec.set_range_seconds(0.0, {duration})
ch = sec.get_all_channels()
for i, v in enumerate({off}):
    ch[i].set_default(float(v))
an = b.add_track(unreal.MovieSceneSkeletalAnimationTrack)
for clip, t0, t1 in {clips}:
    s = an.add_section()
    s.set_range_seconds(t0, t1)
    p = s.get_editor_property('params')
    p.set_editor_property('animation', unreal.load_asset('{anims}/' + clip))
    s.set_editor_property('params', p)
print('body', str(b.get_display_name()), len(an.get_sections()), 'sections')
"""

LIGHT = """import unreal
seq = unreal.load_asset('{folder}/{asset}')
b = seq.add_spawnable_from_class(unreal.PointLight)
b.set_display_name('CapsuleGlow')
tmpl = unreal.MovieSceneBindingExtensions.get_object_template(b)
lc = tmpl.get_editor_property('point_light_component')
lc.set_editor_property('intensity_units', unreal.LightUnits.CANDELAS)
lc.set_editor_property('intensity', 2.5)
lc.set_editor_property('attenuation_radius', 160.0)
lc.set_editor_property('light_color', unreal.Color(186, 206, 255, 255))
lc.set_editor_property('cast_shadows', False)
tr = b.add_track(unreal.MovieScene3DTransformTrack)
sec = tr.add_section()
sec.set_range_seconds(0.0, {duration})
ch = sec.get_all_channels()
for i, v in enumerate({pos}):
    ch[i].set_default(float(v))
print('light ok')
"""


def body_chunk():
    off = [round(v, 3) for v in (*OFF[0], 0.0, 0.0, -90.0)]
    return BODY.format(folder=bc.FOLDER, asset="LS_CIN_19_Hatch", sk=SK, duration=DURATION, cam=CAM, off=off,
                       clips=[(c, a, b) for c, a, b in CLIPS], anims=ANIM_DIR)


def light_chunk():
    pos = [EYE0_X + 15.0, 0.0, round(G0 + lid_under(EYE0_X) - 6.0, 2), 0.0, 0.0, 0.0]
    return LIGHT.format(folder=bc.FOLDER, asset="LS_CIN_19_Hatch", duration=DURATION, pos=pos)


# ----------------------------------------------------------------------------- anim chunks

CREATE = """import unreal
AT = unreal.AssetToolsHelpers.get_asset_tools()
E = unreal.EditorAssetLibrary
full = '{dir}/{name}'
if E.does_asset_exist(full):
    an = unreal.load_asset(full)
else:
    f = unreal.AnimSequenceFactory()
    f.set_editor_property('target_skeleton', unreal.load_asset('{skel}'))
    an = AT.create_asset('{name}', '{dir}', unreal.AnimSequence, f)
c = an.get_editor_property('controller')
c.remove_all_bone_tracks(False)
c.set_frame_rate(unreal.FrameRate({fps}, 1), False)
c.set_number_of_frames(unreal.FrameNumber({n}), False)
print('{name}', 'frames', unreal.AnimationLibrary.get_num_frames(an))
"""

KEYS = """import unreal
an = unreal.load_asset('{dir}/{name}')
c = an.get_editor_property('controller')
V = unreal.Vector
Q = unreal.Quat
names = set(str(x) for x in unreal.AnimationLibrary.get_animation_track_names(an))
n = 0
c.open_bracket('samyor keys', False)
for bone, P, R, S in {data}:
    if bone not in names:
        c.add_bone_curve(bone, False)
    pos = [V(*P)] * len(R) if len(P) == 3 and not isinstance(P[0], list) else [V(*p) for p in P]
    c.set_bone_track_keys(bone, pos, [Q(*q) for q in R], [V(*S)] * len(R), False)
    n += 1
c.close_bracket(False)
print('{name}', 'bones', n, 'keys', len(R))
"""

SAVEA = """import unreal
an = unreal.load_asset('{dir}/{name}')
print('{name}', 'len', round(an.get_play_length(), 3), 'tracks', len(unreal.AnimationLibrary.get_animation_track_names(an)),
      'saved', unreal.EditorAssetLibrary.save_asset('{dir}/{name}', only_if_is_dirty=False))
"""


def emit_anims(out: Path, per_chunk=8):
    out.mkdir(parents=True, exist_ok=True)
    baked = bake()
    k = 0
    for ci, (name, (n, tracks)) in enumerate(baked.items()):
        (out / f"{ci}0_create_{name}.py").write_text(CREATE.format(dir=ANIM_DIR, name=name, skel=SKEL, fps=FPS, n=n), encoding="utf-8")
        bones = list(tracks)
        for j in range(0, len(bones), per_chunk):
            data = []
            for b in bones[j:j + per_chunk]:
                ks = tracks[b]
                pos = [list(map(lambda v: round(v, 5), x[0])) for x in ks]
                P = pos[0] if all(p == pos[0] for p in pos) else pos
                R = [[round(v, 5) for v in x[1]] for x in ks]
                data.append((b, P, R, [round(v, 4) for v in ks[0][2]]))
            (out / f"{ci}1_keys_{name}_{j // per_chunk}.py").write_text(KEYS.format(dir=ANIM_DIR, name=name, data=json.dumps(data)), encoding="utf-8")
            k += 1
        (out / f"{ci}2_save_{name}.py").write_text(SAVEA.format(dir=ANIM_DIR, name=name), encoding="utf-8")
    print("emitted", len(list(out.glob("*.py"))), "chunks to", out)


def summary():
    print("fk check (cm):", round(fk_check(), 3))
    print("g0", round(G0, 1), "rim", round(RIM, 1), "stand hips z", round(S_STAND + G0, 1), "ground at stand", round(SC["g_stand"], 1))
    for t in (0.0, 2.2, 4.8, 8.2, 10.2, 13.5, 16.0, 19.8, 23.5, 26.0, 29.6, 30.5, 34.0, 36.0):
        eye, rot = camera(t)
        reach = []
        local = dict(REF_LOCAL)
        for side in ("L", "R"):
            tg = hand_target(side, t)
            arm_ik(local, side, tg, (0, -30, 100))
            reach.append(round(vlen(vsub(fk(local)["LeftHand" if side == "L" else "RightHand"][0], tg)), 1))
        print(f"t {t:5.1f} eye {tuple(round(v, 1) for v in eye)} rot {tuple(round(v, 1) for v in rot)} gap L/R cm {reach} lid {lid_angle(t):.0f}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "summary"
    if cmd == "emit-anims":
        emit_anims(Path(sys.argv[2]))
    else:
        summary()
