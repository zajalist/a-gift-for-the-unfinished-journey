"""Build the story cinematics' Level Sequences (LANE5; CINEMATICS.md, README_Events.md section 5).

    python Tools/Cinematics/build_cinematics.py plan   CIN_01_DIRECTIVE     # print the camera plan (offline)
    python Tools/Cinematics/build_cinematics.py emit   CIN_01_DIRECTIVE OUT  # write python_run chunks to OUT/
    python Tools/Cinematics/build_cinematics.py check  CIN_19_HATCH [--strict] [--window]  # framing: targets in each key's view
    python Tools/Cinematics/build_cinematics.py terrain CIN_18_COLLAPSE     # heightmap: camera clearance, lines of sight
    python Tools/Cinematics/build_cinematics.py frames CIN_18_COLLAPSE      # world poses + FOV of every key (render_camera)
    python Tools/Cinematics/build_cinematics.py validate-ending             # the offline gate for CIN_15/18/19/24
    python Tools/Cinematics/build_cinematics.py merge-probe OUT.txt         # merge the probe chunk's PROBE_JSON line
    python Tools/Cinematics/build_cinematics.py credits [OUT.txt]           # the CIN_25 credits roll + its length
    python Tools/Cinematics/build_cinematics.py probe-ending OUT.py         # editor chunk that prints probe_ending.json

Ending (task ENDING): CIN_15_IN_RANGE, CIN_18_COLLAPSE, CIN_19_HATCH, CIN_24_TRANSMISSION have camera plans;
CIN_25_END_CARD keeps CIN_24's grounded drone camera for continuity behind the opaque end card;
`plan` prints its cue timeline and `credits` writes the roll text. Their numbers come from probe_ending.json (PROVISIONAL until the editor lane runs the
`probe-ending` chunk) and from docs/story/road-profile.json (the road frame at the road m each one plays at).

POI discovery beats (task CINEPOI, docs/story/POI_CINEMATICS.md): CIN_P04_AIRSHIP, CIN_P07_WAITING_WATER,
CIN_06F_CREST_FORT (CIN_06 + a 4 s fort prelude), CIN_P15_WORKS, CIN_P17_CISTERN (road-local) and CIN_PO01_LOW_VOICE
(world frame, off-road); plus the optional CIN_23_THE_MARK. Their targets come from Tools/World/setdress_sites.json
(site_point); their story-events.json entries from Tools/Cinematics/gen_poi_events.py.

The chunks are run one by one through the Hayba python_run bridge (each stays under its 5 s deadline):
  00_setup.py        create /Game/SaskartaGaea/GameFlow/Cinematics/LS_<name>, 30 fps, playback range
  10_cam_<n>.py      one spawnable CineCameraActor per camera: template lens + a transform track with keys
  70_fade.py         (only when the plan has "fade") a Fade track: colour + keyed 0..1 (black or white)
  80_cuts.py         the camera-cut track: one section per shot, bCanBlend, the last section's ease-out
                     (the hand-back into the pawn camera, blend_out_s). A shot (t0, t1, cam, blend_in)
                     blends in from the previous shot: the previous section is extended to t0 + blend_in
                     and this section gets a manual ease-in of blend_in (the camera-cut blend is the overlap).
  90_save.py         save the asset
  99_read.py         read-back: bindings, tracks, key counts, cut sections

Rules (README_Events.md section 5): spawnable CineCameras only (the level keeps exactly one
CineCameraActor); no audio, voice or letterbox keyed (the runner plays every cue on the sequence's clock);
the camera-cut track can blend, first section ease-in 0, last section ease-out = blend_out_s.

Frames:
  CIN_01 plays at the PlayerStart with an identity origin: its cameras are keyed in WORLD space,
    from the probe values below (PlayerStart, the carrier's eye height, ground heights).
  Road cinematics (CIN_06, CIN_11) get TransformOrigin = the pawn projected on the spline, yawed along
    the direction of travel: their cameras are keyed in that LOCAL frame (+X = up-road, +Y = right,
    +Z = up from the road surface).

POV shots put a camera at the carrier's eye (FOV 90 = 11.88 mm on the 23.76 mm filmback). The carrier is
not bound (the runner has no binding override for the spawned pawn), so a POV camera stands where the eye
is: fine while the pawn is stopped (stop_pawn) or, for CIN_01, standing at the PlayerStart.
"""
from __future__ import annotations

import json
import math
import ending_staging as dawn
import sys
from pathlib import Path

FPS = 30
TICKS = 24000                      # MovieScene tick resolution per second
FOLDER = "/Game/SaskartaGaea/GameFlow/Cinematics"
FILMBACK_W = 23.76


def focal_for_hfov(deg: float) -> float:
    return (FILMBACK_W / 2.0) / math.tan(math.radians(deg) / 2.0)


# ----------------------------------------------------------------------------- probe values
# From the editor (LANE5, 2026-09-28): PlayerStart and the carrier's camera. Filled by `probe`.
PROBE_FILE = Path(__file__).with_name("probe_cin01.json")


def probe() -> dict:
    return json.loads(PROBE_FILE.read_text(encoding="utf-8"))


def fwd(yaw_deg: float, dist: float):
    return (math.cos(math.radians(yaw_deg)) * dist, math.sin(math.radians(yaw_deg)) * dist)


def look_at(frm, to):
    dx, dy, dz = to[0] - frm[0], to[1] - frm[1], to[2] - frm[2]
    yaw = math.degrees(math.atan2(dy, dx))
    pitch = math.degrees(math.atan2(dz, math.hypot(dx, dy)))
    return pitch, yaw


# ----------------------------------------------------------------------------- plans
# A camera: {"name", "focal", "keys": [(t, x, y, z, roll, pitch, yaw, interp)]}; a shot: (t0, t1, camera)

SUMMIT = (287480.0, 444050.0, 20000.0)       # the High Voice summit (world cm; about +200 m)
SCAN_MPC = "/Game/SaskartaGaea/Look/Scan/MPC_Saskarta_Scan"
SCAN_PP = "/Game/SaskartaGaea/Look/Scan/M_PP_SensorScan.M_PP_SensorScan"
AMBER, RED, GREEN, CYAN = (0.95, 0.75, 0.4), (1.0, 0.2, 0.15), (0.4, 1.0, 0.55), (0.55, 0.95, 1.0)


def plan_cin01() -> dict:
    """CIN_01 v2 (the user's 6-shot plan, 2026-09-28), 36 s, world space, synced to the CV_ cues in story-events.json:
    1 boot POV from black (0-4); 2 "Directive: detect mountain": a 70 deg left-to-right POV pan with two scan pulses
    (4-9.5); 3 "Scanning / Candidate rejected": the reticle holds a near hill, a pulse lights its contours red, a
    whip-pan on (9.5-13.4); 4 "Mountain detected": the summit found, a 24 -> 85 mm push-in (a 2.5 s camera-cut blend
    + a 3 m dolly) while a long-range pulse races there and the summit lights green, RANGE / ÂLAAWB (13.4-22);
    5 an exterior crane rising behind the carrier and the capsule toward the mountain, handheld (22-30); 6 back to
    the POV (1.5 s blend), the reticle shrinks to a waypoint, the 2 s hand-back (30-36)."""
    p = probe()
    px, py, pz = p["start"]
    eye = (px + p["eye_offset"][0], py + p["eye_offset"][1], pz + p["eye_offset"][2])
    ground = p["ground_z"]
    ps, ys = look_at(eye, SUMMIT)                     # pitch / yaw to the summit
    yawA, yawB = ys - 105.0, ys - 35.0                # the pan: left to right, 70 deg
    yawH = ys - 30.0                                  # the rejected near hill
    hx, hy = fwd(yawH, 45000.0)
    hill = (px + hx, py + hy, ground)
    pov = focal_for_hfov(90.0)
    cams = []
    cams.append({"name": "CIN01_S1_Boot", "focal": pov, "keys": [
        (0.0, *eye, 0, -22, yawA - 6, "cubic"), (4.0, *eye, 0, -5, yawA, "cubic")]})
    cams.append({"name": "CIN01_S2_Pan", "focal": pov, "keys": [
        (4.0, *eye, 0, -5, yawA, "cubic"), (9.5, *eye, 0, -3, yawB, "cubic")]})
    cams.append({"name": "CIN01_S3_Hill", "focal": pov, "keys": [
        (9.5, *eye, 0, -3, yawB, "cubic"), (10.8, *eye, 0, -3.5, yawH, "cubic"), (12.6, *eye, 0, -3.5, yawH + 2, "linear"),
        (13.4, *eye, 0, 3, ys + 8, "cubic")]})
    cams.append({"name": "CIN01_S4_Wide", "focal": 24.0, "keys": [
        (13.4, *eye, 0, 3, ys + 8, "cubic"), (14.4, *eye, 0, ps, ys, "cubic")]})
    dx, dy = fwd(ys, 300.0)
    cams.append({"name": "CIN01_S4_Push", "focal": 85.0, "keys": [
        (15.5, *eye, 0, ps, ys, "cubic"), (21.5, eye[0] + dx, eye[1] + dy, eye[2] + 20, 0, ps - 0.3, ys + 0.2, "cubic")]})
    cap = p["capsule_back_m"] * 100.0
    b0x, b0y = fwd(ys, -(cap + 500.0))
    b1x, b1y = fwd(ys, -(cap + 500.0) + 700.0)
    crane = [(22.0 + i * 0.5, px + b0x + (b1x - b0x) * f, py + b0y + (b1y - b0y) * f, ground + 250.0 + 1350.0 * f * f * (3 - 2 * f),
              2.0 - 12.0 * f, ys + 4.0 * f) for i in range(17) for f in [i / 16.0]]
    keys5 = []
    for i, (t, x, y, z, pi_, ya) in enumerate(crane):   # a soft handheld wobble on top of the crane move
        wob = math.sin(t * 5.3) * 0.35 + math.sin(t * 8.9 + 1.3) * 0.2
        keys5.append((t, x + math.sin(t * 3.1) * 4.0, y + math.cos(t * 2.7) * 4.0, z + math.sin(t * 4.3) * 3.0,
                      wob * 0.5, pi_ + wob * 0.4, ya + math.cos(t * 4.1) * 0.35, "cubic"))
    cams.append({"name": "CIN01_S5_Crane", "focal": 24.0, "keys": keys5})
    cams.append({"name": "CIN01_S6_POV", "focal": pov, "keys": [
        (30.0, *eye, 0, ps, ys, "cubic"), (34.5, *eye, 0, -5, -160.0, "cubic"), (36.0, *eye, 0, -5, -160.0, "constant")]})
    for c in cams:
        c["blendables"] = [SCAN_PP]
    shots = [(0.0, 4.0, "CIN01_S1_Boot"), (4.0, 9.5, "CIN01_S2_Pan"), (9.5, 13.4, "CIN01_S3_Hill"),
             (13.4, 15.5, "CIN01_S4_Wide"), (15.5, 22.0, "CIN01_S4_Push", 2.5), (22.0, 30.0, "CIN01_S5_Crane"),
             (30.0, 36.0, "CIN01_S6_POV", 1.5)]
    # --- the scan (MPC_Saskarta_Scan): pulses (start, end, speed m/s, trail cm)
    sc = {"ScanRadius": [], "Intensity": [], "ScanWidth": [], "RetAlpha": [], "RetSize": [], "FocusAmount": [], "FocusRadius": []}
    vc = {"ScanOrigin": [(0.0, (px, py, pz))], "Tint": [(0.0, CYAN)], "RetColor": [], "FocusPos": [], "FocusColor": []}
    for t0, t1, speed, width in ((5.0, 7.4, 200.0, 25000.0), (7.5, 9.8, 200.0, 25000.0), (10.0, 13.0, 200.0, 30000.0),
                                 (14.2, 18.4, 900.0, 90000.0)):
        sc["ScanRadius"] += [(t0 - 0.02, 0.0)] + [(t0 + k * 0.25, speed * 100.0 * k * 0.25) for k in range(int((t1 - t0) / 0.25) + 1)]
        sc["Intensity"] += [(t0 - 0.02, 0.0), (t0 + 0.05, 1.0), (t1 - 0.6, 0.8), (t1, 0.0)]
        sc["ScanWidth"] += [(t0, width)]
    sc["RetAlpha"] = [(0.0, 0.0), (4.2, 0.0), (4.8, 0.85), (12.3, 0.85), (12.45, 0.25), (12.6, 0.9), (12.75, 0.25), (12.9, 0.9),
                      (13.2, 0.0), (14.4, 0.0), (14.9, 0.85), (30.0, 0.85), (33.0, 0.35), (34.5, 0.35), (35.5, 0.0)]
    sc["RetSize"] = [(0.0, 0.08), (16.8, 0.08), (17.3, 0.05), (30.0, 0.05), (33.0, 0.02)]
    vc["RetColor"] = [(0.0, AMBER), (12.25, AMBER), (12.3, RED), (13.2, RED), (13.3, AMBER), (16.85, AMBER), (16.9, GREEN),
                      (30.0, GREEN), (33.0, AMBER)]
    vc["FocusPos"] = [(0.0, hill), (13.9, hill), (14.0, SUMMIT)]
    vc["FocusColor"] = [(0.0, RED), (13.9, RED), (14.0, GREEN)]
    sc["FocusRadius"] = [(0.0, 15000.0), (13.9, 15000.0), (14.0, 40000.0)]
    sc["FocusAmount"] = [(0.0, 0.0), (12.2, 0.0), (12.35, 1.0), (12.9, 0.6), (13.3, 0.0), (17.7, 0.0), (18.0, 1.0), (21.5, 1.0), (23.0, 0.0)]
    return {"asset": "LS_CIN_01_Directive", "duration": 36.0, "blend_out": 2.0, "cams": cams, "shots": shots,
            "fade": {"color": (0, 0, 0), "keys": [(0.0, 1.0, "constant"), (0.4, 1.0, "cubic"), (2.6, 0.0, "cubic")]},
            "mpc": {"asset": SCAN_MPC, "scalars": sc, "vectors": vc}}


def plan_cin04(road_m: float = 650.0) -> dict:
    """Six-second dust-front reveal through the carrier's sensor.

    The pawn stops for this short camera beat. The sensor looks back at the approaching
    wall before its gust crosses the lens, then the view settles on the road for
    an immediate handback into the playable chase.
    """
    eye_z = probe()["eye_offset"][2] + probe()["start"][2] - probe()["ground_z"]
    eye = (0.0, 0.0, eye_z)
    cams = [{"name": "CIN04_InsideCarrier", "focal": focal_for_hfov(90.0), "keys": [
        (0.0, *eye, 0.0, -5.0, 0.0, "cubic"),
        (0.7, *eye, 0.0, -5.0, 0.0, "cubic"),
        (1.2, *eye, -1.0, 4.0, -70.0, "cubic"),
        (1.9, *eye, 0.0, 8.0, -138.0, "cubic"),
        (2.65, *eye, 0.0, 10.0, -148.0, "cubic"),
        (2.9, 0.0, -5.0, eye_z - 4.0, 4.0, 6.0, -151.0, "cubic"),
        (3.35, *eye, -1.0, 2.0, -85.0, "cubic"),
        (4.5, *eye, 0.0, -5.0, 0.0, "cubic"),
        (6.0, *eye, 0.0, -5.0, 0.0, "constant"),
    ]}]
    cams[0]["sensor_eye_cm"] = eye_z
    return {"asset": "LS_CIN_04_DustFront", "duration": 6.0, "blend_out": 0.5,
            "cams": cams, "shots": [(0.0, 6.0, "CIN04_InsideCarrier")],
            "frame": "local", "road_m": road_m, "window_m": (0.0, 470.0),
            "fade": {"color": (0.64, 0.40, 0.19), "keys": [
                (0.0, 0.0, "constant"), (2.4, 0.0, "cubic"),
                (2.65, 0.15, "cubic"), (2.95, 0.40, "cubic"),
                (3.5, 0.15, "cubic"), (4.65, 0.08, "cubic"),
                (6.0, 0.0, "cubic"),
            ]}}


def plan_cin06() -> dict:
    """Local frame (TransformOrigin): +X up-road, +Y right, +Z up from the road surface."""
    eye_z = probe()["eye_offset"][2] + probe()["start"][2] - probe()["ground_z"]
    pov = focal_for_hfov(90.0)
    cams = [
        {"name": "CIN06_S1_POV", "focal": pov, "keys": [(0.0, 0, 0, eye_z, 0, -5, 0, "cubic"), (2.0, 0, 0, eye_z, 0, 0, 0, "cubic")]},
        {"name": "CIN06_S2_Behind", "focal": 35.0, "keys": [
            (2.0, -600, 0, 400, 0, -18, 0, "cubic"), (6.0, -500, 0, 380, 0, -16, 0, "cubic")]},
        {"name": "CIN06_S3_Crane50", "focal": 50.0, "keys": [
            (6.0, -300, -900, 2000, 0, -9, 12, "cubic"), (10.0, -100, -900, 2750, 0, -10, 10, "cubic")]},
        {"name": "CIN06_S3_Crane85", "focal": 85.0, "keys": [
            (10.0, -100, -900, 2750, 0, -10, 10, "cubic"), (14.0, 100, -900, 3500, 0, -12, 8, "cubic")]},
        {"name": "CIN06_S4_POV", "focal": pov, "keys": [(14.0, 0, 0, eye_z, 0, -3, 0, "constant")]},
    ]
    shots = [(0.0, 2.0, "CIN06_S1_POV"), (2.0, 6.0, "CIN06_S2_Behind"), (6.0, 10.0, "CIN06_S3_Crane50"),
             (10.0, 14.0, "CIN06_S3_Crane85"), (14.0, 16.0, "CIN06_S4_POV")]
    for cam in cams:
        if "POV" in cam["name"]:
            cam["sensor_eye_cm"] = eye_z
    return {"asset": "LS_CIN_06_RoadAhead", "duration": 16.0, "blend_out": 2.0, "cams": cams, "shots": shots}


def plan_cin11() -> dict:
    """Road-relative exteriors, with each POV anchored to the carrier's actual stopped sensor.
    Exterior cradle/plaque framing still needs rendered acceptance against the current V7 dressing."""
    eye_z = probe()["eye_offset"][2] + probe()["start"][2] - probe()["ground_z"]
    pov = focal_for_hfov(90.0)
    cams = [
        {"name": "CIN11_S1_POV90", "focal": pov, "keys": [(0.0, 0, 0, eye_z, 0, -4, 0, "cubic"), (1.5, 0, 0, eye_z, 0, -4, -70, "cubic")]},
        {"name": "CIN11_S1_POV50", "focal": focal_for_hfov(50.0), "keys": [(2.5, 0, 0, eye_z, 0, -4, -70, "constant")]},
        {"name": "CIN11_S2_Cradle", "focal": 50.0, "keys": [
            (5.0, 700, -1100, 120, 0, 2, 130, "cubic"), (10.0, 650, -1050, 120, 0, 2, 132, "cubic")]},
        {"name": "CIN11_S3_Plaque", "focal": 85.0, "keys": [
            (10.0, 200, -700, 170, 0, -2, 150, "cubic"), (16.0, 180, -680, 170, 0, -2, 152, "cubic")]},
        {"name": "CIN11_S4_POV", "focal": pov, "keys": [(16.0, 0, 0, eye_z, 0, -3, 0, "constant")]},
    ]
    shots = [(0.0, 2.5, "CIN11_S1_POV90"), (2.5, 5.0, "CIN11_S1_POV50"), (5.0, 10.0, "CIN11_S2_Cradle"),
             (10.0, 16.0, "CIN11_S3_Plaque"), (16.0, 18.0, "CIN11_S4_POV")]
    for cam in cams:
        if "POV" in cam["name"]:
            cam["sensor_eye_cm"] = eye_z
    return {"asset": "LS_CIN_11_Waystation", "duration": 18.0, "blend_out": 2.0, "cams": cams, "shots": shots}


# ----------------------------------------------------------------------------- the ending (task ENDING)
# probe_ending.json: the carrier's eye and capsule (from a temporary BP_Saskarta_Carrier in the editor world),
# the High Voice set (the actor tagged Saskarta.HighVoice and its components) and the live spline frame at the
# road m each road cinematic plays at. `probe-ending` writes the editor chunk that prints those numbers.
PROBE_ENDING_FILE = Path(__file__).with_name("probe_ending.json")
ROAD_PROFILE = Path(__file__).resolve().parents[2] / "docs" / "story" / "road-profile.json"
REPO = Path(__file__).resolve().parents[2]


def probe_ending() -> dict:
    return json.loads(PROBE_ENDING_FILE.read_text(encoding="utf-8"))


STORY_EVENTS = REPO / "docs" / "story" / "story-events.json"


def collapse_stage() -> dict:
    """story-events.json "collapse_stage": where the runtime stages the carrier for CIN_18 (road_m, lateral_cm,
    yaw_offset_deg). {} when absent (the plan then uses probe_ending's cin18_road_m on the road centre)."""
    try:
        return json.loads(STORY_EVENTS.read_text(encoding="utf-8")).get("collapse_stage", {}) or {}
    except (OSError, ValueError):
        return {}


def _samples():
    return json.loads(ROAD_PROFILE.read_text(encoding="utf-8"))["samples"]


_SPLINE: list = []


def spline_points() -> list:
    """RoadSpline points 0..54 (world cm), the source road-profile.json was built from. The spline's tangents are
    zero at its points, so between two points it is the straight segment (xy and z share the same easing): the
    polyline is exact. Checked against all 102 profile samples to 5 cm (tests/test_ending_cinematics.py)."""
    if not _SPLINE:
        sys.path.insert(0, str(REPO / "Tools" / "Story"))
        import build_road_profile as brp  # noqa: E402  (numpy + PIL; only the constant is used)
        _SPLINE.extend(tuple(float(v) for v in p) for p in brp.SPLINE_POINTS_CM)
    return _SPLINE


def spline_frame_at_ue(ue_m: float) -> dict:
    """The point at UE spline distance `ue_m` from point 0 (3D arc length, as GetLocationAtDistanceAlongSpline) and
    the yaw of travel (toward point 0). This is what the runner's TransformOrigin is for a pawn on the spline centre:
    GetLocationAtSplineInputKey and -GetTangentAtSplineInputKey (the tangent is along the segment between points)."""
    pts = spline_points()
    rem = ue_m * 100.0
    for a, b in zip(pts, pts[1:]):
        seg = math.dist(a, b)
        if rem <= seg or b is pts[-1]:
            t = min(1.0, rem / seg)
            return {"x": a[0] + (b[0] - a[0]) * t, "y": a[1] + (b[1] - a[1]) * t, "z": a[2] + (b[2] - a[2]) * t,
                    "yaw": math.degrees(math.atan2(a[1] - b[1], a[0] - b[0])), "segment": (pts.index(b), pts.index(a))}
        rem -= seg
    raise ValueError(ue_m)


# ---- the origin's height. The runner's TransformOrigin (USaskartaEventRunner::StartSequence with
# FSaskartaEventLogic::RoadCineOrigin) is the pawn projected onto the spline in X/Y, yawed along -tangent there, and
# since 2026-09-28 (task ENDING-PREP) at the pawn's FEET in Z. Before that it sat at the spline's z, which is a straight
# chord between points ~100 m apart: the landscape the carrier walks on is 11.6 m below to 7.4 m above it along the road,
# and 7.3 m above to 3.3 m below inside CIN_15's own stop window, so one set of baked keys could not hold the POV eye at the
# carrier's eye wherever the pawn stopped. Offline the feet are the landscape under the spline point (the heightmap).
# ORIGIN_Z = "spline" (the --origin=spline flag) reproduces binaries built before the change.
ORIGIN_Z = "feet"


def origin_z(x: float, y: float, spline_z: float) -> float:
    if ORIGIN_Z == "feet":
        g = ground_z(x, y)
        if g is not None:
            return g
    return spline_z


def road_frame(road_m: float) -> dict:
    """The runner's TransformOrigin for a road cinematic at `road_m`: the spline point's x, y, the yaw of travel and
    z = origin_z (the carrier's feet; `spline_z` keeps the spline's). Offline it walks the spline polyline
    (spline_frame_at_ue); until 2026-09-28 it interpolated the 50 m profile samples, which cut the corners (6.4 m off
    at 4,790, 14 deg of yaw off at 4,575). A probed frame in probe_ending.json["frames"]["<road m>"] wins for x, y, yaw."""
    frames = probe_ending().get("frames", {})
    key = str(int(round(road_m)))
    f = frames[key] if key in frames and frames[key].get("probed") else spline_frame_at_ue(ue_m_for_road_m(road_m))
    return {"x": f["x"], "y": f["y"], "z": origin_z(f["x"], f["y"], f["z"]), "yaw": f["yaw"], "spline_z": f["z"]}


# ---- the ground. The origin is the carrier's feet, so a target on the carrier (its eye, the capsule) is keyed at its
# height over the feet; anything else "above the road" (the Keeper beside the capsule, a low camera) is measured from
# the ground under it (ground_local: that ground minus the origin's z). The ground is the Gaea heightmap the landscape
# was imported from (Saved/TerrainRebuild/Current_u16.png, the one build_road_profile.py reads); it matches an editor
# line trace to 0.1 cm at the High Voice (L2). Without it (another machine) the origin and the plans fall back to the
# spline z and `plan` says so.
HEIGHTMAP = REPO / "Saved" / "TerrainRebuild" / "Current_u16.png"
_TERRAIN: list = []


def terrain():
    """The heightmap sampler (build_road_profile.Terrain, heights in m), or None when the file is missing."""
    if not _TERRAIN:
        t = None
        if HEIGHTMAP.exists():
            sys.path.insert(0, str(REPO / "Tools" / "Story"))
            import build_road_profile as brp  # noqa: E402
            t = brp.Terrain(HEIGHTMAP)
        _TERRAIN.append(t)
    return _TERRAIN[0]


def ground_z(x: float, y: float) -> float | None:
    """Landscape height at world (x, y), cm; None without the heightmap."""
    t = terrain()
    return None if t is None else float(t.height(x, y)) * 100.0


def ground_local(frame: dict, lx: float = 0.0, ly: float = 0.0) -> float:
    """Height of the ground under the frame's local (lx, ly) above the frame origin (the carrier's feet; the spline z
    under --origin=spline), cm. 0 at the origin itself unless the origin is the spline's."""
    w = to_world(frame, (lx, ly, 0.0))
    g = ground_z(w[0], w[1])
    return 0.0 if g is None else g - frame["z"]


def to_local(frame: dict, p) -> tuple:
    """World cm -> the frame's local cm (+X up-road, +Y right, +Z up from the spline point)."""
    dx, dy = p[0] - frame["x"], p[1] - frame["y"]
    c, s_ = math.cos(math.radians(frame["yaw"])), math.sin(math.radians(frame["yaw"]))
    return (dx * c + dy * s_, -dx * s_ + dy * c, p[2] - frame["z"])


def to_world(frame: dict, p) -> tuple:
    c, s_ = math.cos(math.radians(frame["yaw"])), math.sin(math.radians(frame["yaw"]))
    return (frame["x"] + p[0] * c - p[1] * s_, frame["y"] + p[0] * s_ + p[1] * c, frame["z"] + p[2])


def handheld(t0: float, t1: float, pos, pitch: float, yaw: float, amp: float = 0.3, step: float = 0.5, seed: float = 1.7):
    """A deterministic ±amp degree drift (a sum of two sines, no random): keys every `step` s."""
    keys, t = [], t0
    while t <= t1 + 1e-6:
        dp = amp * (0.6 * math.sin(1.3 * t + seed) + 0.4 * math.sin(2.9 * t + 2 * seed))
        dy = amp * (0.6 * math.sin(1.1 * t + 3 * seed) + 0.4 * math.sin(2.3 * t + seed))
        keys.append((round(t, 3), *pos, 0, pitch + dp, yaw + dy, "cubic"))
        t += step
    return keys


def _cam(name, focal, keys, targets=None, want=(), only_at=None, rides=False):
    """`targets`: every named point of the scene; `want`: the ones this shot must frame (checked by `check`);
    `only_at`: {target: (key times,)} for a target the shot frames only at those keys (a tilt off a subject);
    `rides`: the camera stands on the carrier (its eye, the capsule): window_check fails it if, at any stop point, it
    is more than RIDE_TOL_CM from where the plan re-derived at that stop puts it."""
    tg = targets or {}
    c = {"name": name, "focal": focal, "keys": keys, "targets": {n: tg[n] for n in want}}
    if only_at:
        c["only_at"] = {n: tuple(ts) for n, ts in only_at.items()}
    if rides:
        c["rides"] = True
    return c


RIDE_TOL_CM = 25.0


def _wanted(c, n, t) -> bool:
    """Must camera c frame target n at key time t?"""
    ts = (c.get("only_at") or {}).get(n)
    return ts is None or any(abs(t - x) < 1e-6 for x in ts)


# The crown is the ending set's 8.4 m glow sphere (ending_editor.py place: Sphere at scale 8.4). A line of sight to its
# centre that grazes a crest still shows the top of it: the check passes while the crest's shadow reaches no more than
# a third of the radius above the centre, so at least the top third of the glow's height shows. Every other target is
# a point (its centre must be in sight).
TARGET_RADIUS_CM = {"crown": 420.0}


def _hidden_cm(n: str, over_cm: float, at_m: float, dist_cm: float) -> float:
    """How far above the target's centre the crest's shadow reaches at the target (cm), less the target's allowance
    (a third of its radius). > 0 is blocked."""
    if over_cm <= 0:
        return over_cm
    return over_cm * (dist_cm / 100.0) / max(at_m, 0.5) - TARGET_RADIUS_CM.get(n, 0.0) / 3.0


def plan_cin15(road_m: float | None = None) -> dict:
    """CIN_15_IN_RANGE (10 s), local frame at the road m where the queued beat lands (~4,575; the pawn stops).
    Shot 2 deviates from CINEMATICS.md: 200 mm cannot hold both the carrier (40 m) and the crown (~270 m, ~10 deg
    higher); the plan puts the camera 40 m back on the mast-carrier line, 3 deg round so the mast sits
    upper-right, and picks the longest lens that fits both (85 mm cap).
    Where it plays: B15 fires at 4,520 and queues behind B14's radio, so it lands anywhere from 4,520 (a player who
    stops) to ~4,610 (the mast drops behind the shoulder); window_m covers all of it. The runner's origin is the
    carrier's feet (since 2026-09-28), so the POV eye (carrier_eye_z over the origin) is the carrier's eye at every
    stop; with the old spline-z origin it was 1.5 m under the ground at 4,555 and 5.4 m over the carrier at 4,607.
    The frame turns 14 deg at spline point 6 (road ~4,589), so the stepped zoom ends at 45 deg, not 30:
    `window` keeps the crown in every POV step on both sides."""
    pe = probe_ending()
    road_m = pe["cin15_road_m"] if road_m is None else road_m
    fr = road_frame(road_m)
    g0 = ground_local(fr)
    eye = (0.0, 0.0, g0 + pe["carrier_eye_z"])
    crown = to_local(fr, pe["mast_crown"])
    pm, ym = look_at(eye, crown)
    pov = focal_for_hfov(90.0)
    tg = {"crown": crown, "carrier": (0.0, 0.0, g0 + 100.0)}
    cams = [
        _cam("CIN15_S1_POV90", pov, [(0.0, *eye, 0, -3, 0, "cubic"), (1.6, *eye, 0, pm, ym, "cubic")], tg, ("crown",), rides=True),
        _cam("CIN15_S1_POV70", focal_for_hfov(70.0), [(2.0, *eye, 0, pm, ym, "constant")], tg, ("crown",), rides=True),
        _cam("CIN15_S1_POV55", focal_for_hfov(55.0), [(2.8, *eye, 0, pm, ym, "constant")], tg, ("crown",), rides=True),
        _cam("CIN15_S1_POV45", focal_for_hfov(45.0), [(3.6, *eye, 0, pm, ym, "constant")], tg, ("crown",), rides=True),
    ]
    # shot 2: 40 m back along the crown->carrier line, rotated 3 deg about the carrier so the crown sits right of the
    # carrier, on a crane 8 m over its ground. The road crests behind the carrier: from 1.5 m (the shot list's "below")
    # the crest hides the carrier by 3.7 m. The camera rides with the frame, so the carrier sits in the same place in
    # its frame at every stop; `window` checks its clearance (lowest 5.7 m, at 4,600), the crown's framing and both
    # lines of sight from every stop point.
    back = math.degrees(math.atan2(-crown[1], -crown[0])) - 3.0
    bx, by = fwd(back, 4000.0)
    c2 = (bx, by, ground_local(fr, bx, by) + 800.0)
    target = ((crown[0] * 0.1), (crown[1] * 0.1), (crown[2] * 0.1 + tg["carrier"][2] * 0.9))  # between them, low
    p2, y2 = look_at(c2, target)
    # vertical spread carrier->crown seen from c2, plus 20 % margin, sets the lens (16:9 frame)
    pc, _ = look_at(c2, tg["carrier"])
    pk, _ = look_at(c2, crown)
    spread = abs(pk - pc) * 1.2
    focal2 = min(85.0, (FILMBACK_W / 2.0 * 9.0 / 16.0) / math.tan(math.radians(max(spread, 1.0)) / 2.0))
    p2 = (pc + pk) / 2.0
    cams.append(_cam("CIN15_S2_Long", focal2, [(5.0, *c2, 0, p2, y2, "linear"), (8.0, *c2, 0, p2 + 0.2, y2 + 0.3, "linear")], tg, ("carrier", "crown")))
    cams.append(_cam("CIN15_S3_POV", pov, [(8.0, *eye, 0, 0.0, ym, "constant")], tg, ("crown",), rides=True))
    shots = [(0.0, 2.0, "CIN15_S1_POV90"), (2.0, 2.8, "CIN15_S1_POV70"), (2.8, 3.6, "CIN15_S1_POV55"),
             (3.6, 5.0, "CIN15_S1_POV45"), (5.0, 8.0, "CIN15_S2_Long"), (8.0, 10.0, "CIN15_S3_POV")]
    return {"asset": "LS_CIN_15_InRange", "duration": 10.0, "blend_out": 2.0, "cams": cams, "shots": shots,
            "frame": "local", "road_m": road_m, "window_m": (-55.0, 35.0)}


def plan_cin18(road_m: float | None = None) -> dict:
    """CIN_18_COLLAPSE (28 s), local frame at collapse_stage road_m (4,790). The carrier is staged there when B18 starts,
    before the sequence takes its origin (USaskartaCollapseStageSubsystem: grounded, square to the road, hitch straight;
    the 3.2 s SnapToRoad cue is gone), so the EXT shot's local frame is the carrier's own and the stop is exact.
    Shot 3 deviates from CINEMATICS.md: "8 m ahead-right, looking back" cannot also show the High Voice behind
    the carrier (the mast is up-road). The camera is rear-right three-quarter, low: the mast folding and the
    eyes going dark in profile, the capsule rolling into the coupler, the crown small beyond.
    Heights are above the carrier's ground (g0 = landscape - spline z at the origin)."""
    pe = probe_ending()
    st = collapse_stage()
    road_m = (st["road_m"] if st.get("road_m") is not None else pe["cin18_road_m"]) if road_m is None else road_m
    fr = road_frame(road_m)
    # The staged carrier (USaskartaCollapseStageSubsystem): lat cm right of the spline point, yawed yo off the road.
    # The origin is the spline point (the runner projects the pawn onto the spline) at the carrier's feet.
    lat, yo = float(st.get("lateral_cm", 0.0)), float(st.get("yaw_offset_deg", 0.0))

    def on_carrier(lx: float, ly: float) -> tuple:
        c, s_ = math.cos(math.radians(yo)), math.sin(math.radians(yo))
        return (lx * c - ly * s_, lat + lx * s_ + ly * c)

    g0 = ground_local(fr, 0.0, lat)
    ez = g0 + pe["carrier_eye_z"]
    crown = to_local(fr, pe["mast_crown"])
    pm, ym = look_at((0, lat, ez), crown)
    pm *= 0.5          # the carrier looks level-ish at the mast; the lurches sag from there
    pov = focal_for_hfov(90.0)
    cx, cy, cz = pe["capsule_root_local"]
    kx, ky = on_carrier(cx, cy)
    tg = {"crown": crown, "carrier": (0.0, lat, g0 + 90.0), "capsule": (kx, ky, g0 + cz)}
    cams = [_cam("CIN18_S1_POVLurch", pov, [
        (0.0, 0, lat, ez, 0, pm, ym, "cubic"),
        (0.5, 0, lat, ez - 12, 2, pm - 8, ym, "cubic"),
        (1.0, 0, lat, ez - 8, 1, pm - 3, ym + 1, "cubic"),
        (1.4, 0, lat, ez - 30, 4, pm - 12, ym + 2, "cubic"),
        (2.0, 0, lat, ez - 32, 4, pm - 10, ym + 2, "cubic"),
        (3.5, 0, lat, ez - 32, 4, pm - 10, ym + 2, "constant")], tg, ("crown",), rides=True)]
    # low: 1 m over its own ground at the nominal stop. The ground there rises ~0.45 m against the carrier's over the
    # 6 m stop window, so at 70 cm (the first plan) a stop at 4,796 left the lens 27 cm off the verge.
    c3 = (-700.0, lat + 550.0, ground_local(fr, -700.0, lat + 550.0) + 100.0)
    p_car, _ = look_at(c3, (-60.0, lat, g0 + 90.0))
    _, y_capsule = look_at(c3, tg["capsule"])
    _, y_crown = look_at(c3, crown)
    # The measured capsule_root lies farther back than the provisional probe.
    # Center the exterior's yaw between capsule and crown; keep its position,
    # lens, shutdown timing and the carrier's vertical framing unchanged.
    y3 = y_capsule + _wrap(y_crown - y_capsule) * 0.5
    cams.append(_cam("CIN18_S3_ExtShutdown", 28.0, [(3.5, *c3, 0, p_car + 3.0, y3, "linear"),
                                                    (28.0, *c3, 0, p_car + 3.0, y3, "linear")], tg, ("carrier", "capsule", "crown")))
    shots = [(0.0, 3.5, "CIN18_S1_POVLurch"), (3.5, 28.0, "CIN18_S3_ExtShutdown")]
    return {"asset": "LS_CIN_18_Collapse", "duration": 28.0, "blend_out": 0.0, "cams": cams, "shots": shots,
            "frame": "local", "road_m": road_m, "window_m": (0.0, 0.0),
            "note": "9-28 s is black: WBP_Saskarta_BootLog (PC Cine_ShowBlack at 9.0) covers the frame; the camera holds. "
                    "The carrier is staged at story-events.json collapse_stage when B18 starts (no stop window since 2026-09-29)."}


def plan_cin19(road_m: float | None = None) -> dict:
    """CIN_19_HATCH: exterior drone view of the authored full-body capsule exit (2026-09-30).
    samyor_reveal preserves its measured hand/foot contacts and action clock; the old shot list below is archival."""
    import samyor_reveal  # noqa: E402  (imports this module)
    return samyor_reveal.plan()


def plan_cin19_exterior(road_m: float | None = None) -> dict:
    """SUPERSEDED 2026-09-29 by the first-person reveal. CIN_19_HATCH, local frame at 4,790 (the carrier was snapped onto the spline in CIN_18, so the capsule is at
    capsule_root_local). The sequence runs 0-19.8 s; the 'Rise.' prompt pauses it at 13.4. Shot 6 (the 1.6 s blend
    to the traveller's camera) is NOT in the sequence: the cut track ends with no ease-out, the final state
    possesses the traveller, and the runner blends SetViewTargetWithBlend(traveller, blend_out_s 1.6).
    The overexposure (+3 EV -> 0) is a white Fade track 1 -> 0 over 0.3-1.8 s.
    Shot 5 deviates from CINEMATICS.md ("6 m ahead-left"): the crown is up-road, so the one frame that holds the
    Keeper, the fallen carrier and the crown looks up-road from behind-right, low.
    The capsule heights are above the carrier's ground (g0), not the spline: a metre of spline-vs-landscape
    difference would put the interior camera through the capsule floor."""
    pe = probe_ending()
    road_m = pe["cin18_road_m"] if road_m is None else road_m
    fr = road_frame(road_m)
    g0 = ground_local(fr)
    crown = to_local(fr, pe["mast_crown"])
    cx, cy, cz = pe["capsule_root_local"]
    side = pe["keeper_side_cm"]
    keeper = (cx, cy - side, ground_local(fr, cx, cy - side) + 100.0)
    rim_z = g0 + pe["capsule_rim_z"]
    tg = {"crown": crown, "carrier": (60.0, 0.0, g0 + 60.0), "keeper": keeper, "rim_left": (cx, cy - 45.0, rim_z)}
    # 1 InteriorCam: lying in the lining, looking straight up; head toward the carrier (+X is the top of frame)
    inside = (cx, cy, g0 + pe["capsule_floor_z"] + 35.0)
    cams = [_cam("CIN19_S1_Interior", 18.0, [(0.0, *inside, 0, 89.0, 0.0, "cubic"), (5.4, inside[0], inside[1], inside[2] + 2, 0, 88.5, 0.0, "cubic")], tg, (), rides=True)]
    # 2 HalfRiseCam: at the rim, looking up-road; the crown upper-left, the fallen carrier in the lower frame
    rise = (cx - 30.0, cy, g0 + pe["half_rise_eye_z"])
    pk, yk = look_at(rise, crown)
    y2 = yk + 11.0
    p2 = 2.0
    keys2 = handheld(3.0, 13.4, rise, p2, y2)
    keys2.append((13.8, rise[0], rise[1], rise[2] - 5.0, 0, p2 - 3.0, y2, "cubic"))  # 3: the falter
    cams.append(_cam("CIN19_S2_HalfRise", 24.0, keys2, tg, ("crown", "carrier"), rides=True))
    # 4 insert: the hand on the left rim, 50 mm from the capsule's left side
    ins = (cx - 40.0, cy - 150.0, rim_z + 10.0)
    p4, y4 = look_at(ins, tg["rim_left"])
    cams.append(_cam("CIN19_S4_Hand", 50.0, [(13.8, *ins, 0, p4, y4, "linear"), (15.8, ins[0] + 8, ins[1] + 4, ins[2], 0, p4, y4, "linear")], tg, ("rim_left",), rides=True))
    # 5 wide, low, behind-right: Keeper left third, the carrier mid, the crown upper right
    c5 = (cx - 650.0, cy + 280.0, ground_local(fr, cx - 650.0, cy + 280.0) + 100.0)   # 60 cm was 14 cm at a 4,796 stop
    _, yke = look_at(c5, keeper)
    _, ycr = look_at(c5, crown)
    pke, _ = look_at(c5, keeper)
    y5 = (yke + ycr) / 2.0
    cams.append(_cam("CIN19_S5_Wide", 35.0, [(15.8, *c5, 0, pke + 4.0, y5, "linear"), (19.8, *c5, 0, pke + 4.0, y5 + 0.4, "linear")], tg, ("keeper", "carrier", "crown")))
    shots = [(0.0, 3.0, "CIN19_S1_Interior"), (3.0, 13.8, "CIN19_S2_HalfRise", 2.4),
             (13.8, 15.8, "CIN19_S4_Hand"), (15.8, 19.8, "CIN19_S5_Wide")]
    return {"asset": "LS_CIN_19_Hatch", "duration": 19.8, "blend_out": 0.0, "cams": cams, "shots": shots,
            "frame": "local", "road_m": road_m, "window_m": (0.0, 6.0),
            "fade": {"color": (1.0, 1.0, 1.0), "keys": [(0.0, 1.0, "constant"), (0.3, 1.0, "cubic"), (1.8, 0.0, "cubic")]}}


# ---- CIN_24: the companion drone settles outside the radio post. Samyor's live pawn is hidden by the
# runner at t=0; a full-head sequencer body enters, stays unseen inside, exits, then dies in frame.
# The voice and sound cues remain on the runner's clock (gen_first_light_ending.py).
FL_DAWNCAM_AT = 3.0         # retained cue clock constant; the grounded exterior shot is continuous
FL_SEATED_AT = 84.0         # Samyor finishes transmitting and comes back outside
FL_FADE_AT = 204.0          # fade to title black over 3 s, then reveal the same view under credits
FL_END_S = 207.0            # the cut: CIN_25 and the title track start here
FL_LAMP_FWD_CM, FL_LAMP_LEFT_CM, FL_LAMP_UP_CM = 250.0, 100.0, 150.0   # the hut-post lantern, from the StandPoint (ending_editor lamp)


def fl_lamp(pe: dict | None = None) -> tuple:
    """The lantern's world position: FL_LAMP_* from the StandPoint, facing the seat's bearing (east over the valley)."""
    pe = pe or probe_ending()
    if pe.get("radio_post", {}).get("lamp"):
        return tuple(pe["radio_post"]["lamp"])
    hv = pe["high_voice"]
    stand, face = hv["stand"], hv["seat_yaw"]
    feet = stand[2] - pe.get("keeper_half_height_cm", 92.0)
    fx, fy = fwd(face, FL_LAMP_FWD_CM)
    lx, ly = fwd(face - 90.0, FL_LAMP_LEFT_CM)
    return (stand[0] + fx + lx, stand[1] + fy + ly, feet + FL_LAMP_UP_CM)


def radio_post(pe: dict | None = None) -> dict:
    """Measured summit staging; the editor lane updates these points after placing the hut."""
    pe = pe or probe_ending()
    return pe.get("radio_post", {
        "door": [297311.0, 483165.0, 10915.0],
        "inside": [297255.0, 483331.0, 10912.0],
        "drone_rest": [297407.0, 482881.0, 10997.0],
        "entry_start": [297225.0, 483025.0, 10920.0],
        "exit_mid": [297500.0, 483100.0, 10917.0],
        "collapse": [297700.0, 482700.0, 10971.0],
    })


def grounded_final_camera(pe: dict | None = None) -> tuple:
    post = radio_post(pe)
    rest, fall = post["drone_rest"], post["collapse"]
    centre = (fall[0], fall[1], fall[2] + 72.0)
    pitch, yaw = look_at(rest, centre)
    return (rest[0], rest[1], rest[2], 0.0, pitch - 1.0, yaw - 5.0)


RADIO_BODY = """import unreal
seq = unreal.load_asset('{folder}/{asset}')
b = seq.add_spawnable_from_class(unreal.SkeletalMeshActor)
b.set_display_name('Samyor_FullHead')
tmpl = unreal.MovieSceneBindingExtensions.get_object_template(b)
smc = tmpl.get_editor_property('skeletal_mesh_component')
smc.set_skeletal_mesh_asset(unreal.load_asset('/Game/SaskartaGaea/Characters/Traveller/SK_Traveller'))
smc.set_editor_property('bounds_scale', 3.0)
tr = b.add_track(unreal.MovieScene3DTransformTrack)
s = tr.add_section()
s.set_range_seconds(0.0, {duration})
ch = s.get_all_channels()
TR = unreal.MovieSceneTimeUnit.TICK_RESOLUTION
M = {{'linear': unreal.MovieSceneKeyInterpolation.LINEAR, 'constant': unreal.MovieSceneKeyInterpolation.CONSTANT, 'cubic': unreal.MovieSceneKeyInterpolation.AUTO}}
for tick, vals, mode in {keys}:
    for i in range(6):
        ch[i].add_key(unreal.FrameNumber(int(tick)), float(vals[i]), 0.0, TR, M[mode])
an = b.add_track(unreal.MovieSceneSkeletalAnimationTrack)
for clip, t0, t1 in {clips}:
    sec = an.add_section()
    sec.set_range_seconds(t0, t1)
    params = sec.get_editor_property('params')
    params.set_editor_property('animation', unreal.load_asset('/Game/SaskartaGaea/Characters/Traveller/Anims/' + clip))
    sec.set_editor_property('params', params)
print('Samyor_FullHead', len(an.get_sections()), 'clips', sum(c.get_num_keys() for c in ch), 'transform keys')
"""


def radio_body_transform(post: dict, duration: float, still: bool = False) -> list:
    """Mesh faces local +Y; turn it 90 degrees from the world travel bearing."""
    inside, door = post["inside"], post["door"]
    entry, mid, fall = post["entry_start"], post["exit_mid"], post["collapse"]

    def body_yaw(a, b):
        return math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) - 90.0

    y_in = body_yaw(entry, door)
    y_radio = y_in + 50.0

    def nearest_yaw(value, previous):
        return previous + (value - previous + 180.0) % 360.0 - 180.0

    y_out = nearest_yaw(body_yaw(inside, door), y_radio)
    y_mid = nearest_yaw(body_yaw(door, mid), y_out)
    y_end = nearest_yaw(body_yaw(mid, fall), y_mid)
    # The revised bone animation carries the weight shift and ground contact.
    # Rotating the whole actor about its foot pivot lifts the folded body in air.
    y_sun = y_end + dawn.turn_delta(post)
    fallen = (*fall, 0.0, 0.0, y_sun)
    if still:
        return [(0.0, *fallen, "constant"), (duration, *fallen, "constant")]
    approach = [(0.0, *entry, 0.0, 0.0, y_in, "cubic"),
            (3.4, *entry, 0.0, -22.0, y_in, "cubic"),
            (4.4, *door, 0.0, -22.0, y_in, "cubic"),
            (5.8, *inside, 0.0, -12.0, y_radio, "cubic"),
            # Interpolation belongs to the outgoing interval. Hold through
            # the window glance and the line ending79.31, then turn in place.
            (7.0, *inside, 0.0, 0.0, y_radio, "constant"),
            (80.0, *inside, 0.0, 0.0, y_radio, "linear"),
            (83.8, *inside, 0.0, 0.0, y_out, "linear"),
            (87.0, *door, 0.0, 0.0, y_out, "linear"),
            (92.0, *mid, 0.0, 0.0, y_mid, "linear")]
    # Match the30Hz compensated step animation: each support foot stays planted
    # while the other lifts. All protected world waypoints remain unchanged.
    turn = [(dawn.TURN_AT+i/30.0, *fall, 0.0, 0.0,
             y_end+dawn.turn_delta(post)*dawn.turn_fraction(i/30.0), "linear")
            for i in range(round(dawn.TURN_SECONDS*30)+1)]
    turn[-1] = (*turn[-1][:-1], "constant")
    return approach + turn + [(dawn.COLLAPSE_END, *fallen, "constant"),
                              (duration, *fallen, "constant")]


def radio_body_chunk(asset: str, duration: float, post: dict, still: bool = False) -> str:
    keys = [(round(t * TICKS), tuple(round(v, 3) for v in values), mode)
            for t, *values, mode in radio_body_transform(post, duration, still)]
    clips = ([("A_Samyor_FinalStill", 0.0, duration)] if still else
             [("A_Traveller_SupportedIdle", 0.0, 3.4),
              ("A_Traveller_SlowWalk", 3.4, 5.8),
              ("A_Traveller_Transmit", 5.8, 59.5),
              ("A_Samyor_LightNotice", 59.5, 83.8),
              ("A_Traveller_SlowWalk", 83.8, dawn.TURN_AT),
              ("A_Samyor_DawnTurn", dawn.TURN_AT, dawn.COLLAPSE_AT),
              ("A_Samyor_FinalCollapse", dawn.COLLAPSE_AT, dawn.COLLAPSE_END),
              ("A_Samyor_FinalStill", dawn.COLLAPSE_END, duration)])
    return RADIO_BODY.format(folder=FOLDER, asset=asset, duration=duration, keys=keys, clips=clips)


def plan_cin24() -> dict:
    """The landed drone sees the exit, turns to the dawn, then witnesses the fall."""
    post = radio_post()
    door, rest = post["door"], tuple(post["drone_rest"])
    entry, mid, fall = post["entry_start"], post["exit_mid"], post["collapse"]
    start = (rest[0], rest[1], rest[2] + 220.0)
    _, y0 = look_at(start, (entry[0], entry[1], entry[2] + 95.0))
    p0 = -23.0  # reveal the post and horizon while the drone descends, not a top-down slab of ground
    p1, y1 = look_at(rest, (door[0], door[1], door[2] + 130.0))
    pm, ym = look_at(rest, (mid[0], mid[1], mid[2] + 90.0))
    pf = grounded_final_camera()
    keys = [(0.0, *start, 0.0, p0, y0, "cubic"),
            (5.0, *rest, 0.0, p1, y1, "constant"),
            (FL_SEATED_AT, *rest, 0.0, p1, y1, "cubic"),
            (90.0, *rest, 0.0, pm, ym, "cubic"),
            (92.7, *rest, 0.0, 2.3, dawn.SUN_BEARING, "constant"),
            (94.0, *rest, 0.0, 2.3, dawn.SUN_BEARING, "cubic"),
            (dawn.TURN_AT, *pf, "constant"),
            (FL_END_S, *pf, "constant")]
    cams = [_cam("CIN24_GroundedDrone", 12.0, keys)]
    fade = [(0.0, 0.0, "constant"), (FL_FADE_AT, 0.0, "cubic"), (FL_END_S, 1.0, "constant")]
    return {"asset": "LS_CIN_24_Transmission", "duration": FL_END_S, "blend_out": 0.0,
            "cams": cams, "shots": [(0.0, FL_END_S, "CIN24_GroundedDrone")], "frame": "world",
            "fade": {"color": (0.0, 0.0, 0.0), "keys": fade},
            "extra": {"20_samyor.py": radio_body_chunk("LS_CIN_24_Transmission", FL_END_S, post)}}


# ---- CIN_25: UMG over a matching grounded-drone camera. The roll text lives in
# docs/story/CREDITS_SCREEN.md between the markers below.
CREDITS_MD = REPO / "docs" / "story" / "CREDITS_SCREEN.md"
ROLL_BEGIN, ROLL_END = "<!-- ROLL:BEGIN -->", "<!-- ROLL:END -->"
ROLL_S_PER_LINE = 0.75     # scroll: one 36 px line every 0.75 s (48 px/s) at 1080p; blank lines count
ROLL_LEAD_S = 4.0          # the first line enters from the bottom edge; the last leaves the top


def credits_roll() -> list[str]:
    text = CREDITS_MD.read_text(encoding="utf-8")
    body = text.split(ROLL_BEGIN, 1)[1].split(ROLL_END, 1)[0]
    lines = body.strip("\n").split("\n")
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].startswith("```"):
        lines = lines[:-1]
    return lines


def roll_seconds() -> float:
    return round(len(credits_roll()) * ROLL_S_PER_LINE + ROLL_LEAD_S, 1)


def plan_cin25() -> dict:
    roll = roll_seconds()
    t_roll = 17.0
    end = t_roll + roll + 3.0
    timeline = [(0.0, "SetFlowState End; the continuous eyetae_title player rises from the transmission mix, no new music player or wind bed"),
                (2.0, "ShowEndCard Title: T_Saskarta_TitleName_Ivory fades in 2 s, holds, fades out (8 s)"),
                (10.0, "ShowEndCard Credits: Made for Tripothon S1 / Made with Hayba / Voices: Badr Zejli (7 s)"),
                (t_roll, f"ShowEndCard CreditsRoll: {len(credits_roll())} lines, {roll} s scroll"),
                (t_roll + roll, "fade the continuing title score over 3 s while the end card stays black"),
                (end, "final state: OpenLevel Title")]
    # Keep the matching camera for continuity; the playtest-approved UMG black backing hides it throughout.
    pose = grounded_final_camera()
    cam = _cam("CIN25_GroundedDrone", 12.0, [(0.0, *pose, "constant"), (end, *pose, "constant")])
    fade = [(0.0, 1.0, "constant"), (10.0, 1.0, "constant"), (t_roll, 0.0, "cubic"),
            (end - 3.0, 0.0, "constant"), (end, 1.0, "constant")]
    return {"asset": "LS_CIN_25_EndCard", "widget": "WBP_Saskarta_Caption.EndCard", "duration": end, "timeline": timeline,
            "roll_at": t_roll, "roll_s": roll, "cams": [cam], "shots": [(0.0, end, "CIN25_GroundedDrone")],
            "frame": "world", "blend_out": 0.0, "fade": {"color": (0.0, 0.0, 0.0), "keys": fade},
            "extra": {"20_samyor.py": radio_body_chunk("LS_CIN_25_EndCard", end, radio_post(), still=True)}}


# ----------------------------------------------------------------------------- POI discovery beats (task CINEPOI)
# docs/story/POI_CINEMATICS.md. Road beats play in the local road frame at their trigger road m (like CIN_06/11);
# CIN_PO01 plays off-road in WORLD space (relative_to_pawn false: the spline projection is meaningless off-road).
# Targets are the placed set dressing (Tools/World/setdress_sites.json: a group's placement bounds centre, raised
# to mid-height). POV cameras carry the scan blendable; the scan pulse is an MPC track keyed in world cm.
SETDRESS = REPO / "Tools" / "World" / "setdress_sites.json"
_SITES: dict = {}


def site_point(site: str, group: str | None = None, key: str | None = None, rise: float = 0.5) -> tuple:
    """World cm of a placed group (mean of its placements) at `rise` x its tallest placement's height."""
    if not _SITES:
        _SITES.update({s["id"]: s for s in json.loads(SETDRESS.read_text(encoding="utf-8"))["sites"]})
    s = _SITES[site]
    ps = [p for p in s["placements"] if (group is None or p["group"] == group) and (key is None or p["key"] == key)]
    if not ps:
        raise KeyError(f"{site}: no placement in group {group} / key {key}")
    h = max(p["size_m"][2] * p["scale"] for p in ps) * 100.0
    n = len(ps)
    return (sum(p["x_cm"] for p in ps) / n, sum(p["y_cm"] for p in ps) / n, sum(p["ground_z_cm"] for p in ps) / n + h * rise)


def _eye_z() -> float:
    return probe()["eye_offset"][2] + probe()["start"][2] - probe()["ground_z"]


def _scan(origin_w, pulses, focus=None, focus_color=AMBER, focus_radius=3000.0, focus_keys=(), ret_keys=(),
          ret_color=AMBER, ret_size=0.06) -> dict:
    """MPC_Saskarta_Scan keys for a POI beat. pulses: (t0, t1, speed m/s, trail cm); focus: world cm."""
    sc = {"ScanRadius": [], "Intensity": [], "ScanWidth": [], "RetAlpha": list(ret_keys) or [(0.0, 0.0)],
          "RetSize": [(0.0, ret_size)], "FocusAmount": list(focus_keys) or [(0.0, 0.0)], "FocusRadius": [(0.0, focus_radius)]}
    vc = {"ScanOrigin": [(0.0, tuple(origin_w))], "Tint": [(0.0, CYAN)], "RetColor": [(0.0, ret_color)],
          "FocusPos": [(0.0, tuple(focus or origin_w))], "FocusColor": [(0.0, focus_color)]}
    for t0, t1, speed, width in pulses:
        sc["ScanRadius"] += [(max(0.0, t0 - 0.02), 0.0)] + [(t0 + k * 0.25, speed * 100.0 * k * 0.25) for k in range(int((t1 - t0) / 0.25) + 1)]
        sc["Intensity"] += [(max(0.0, t0 - 0.02), 0.0), (t0 + 0.05, 0.9), (t1 - 0.5, 0.7), (t1, 0.0)]
        sc["ScanWidth"] += [(t0, width)]
    return {"asset": SCAN_MPC, "scalars": sc, "vectors": vc}


def _pov(name, hfov, keys, tg, want=()):
    c = _cam(name, focal_for_hfov(hfov), keys, tg, want)
    c["blendables"] = [SCAN_PP]
    c["sensor_eye_cm"] = _eye_z()
    return c


def _aim(eye, p, dp=0.0, dy=0.0):
    pi_, ya = look_at(eye, p)
    return pi_ + dp, ya + dy


def plan_poi_airship() -> dict:
    """CIN_P04_AIRSHIP (9 s, road 700): the carrier's eyes find the downed airship (-90 deg, 790 m) and the
    observatory dome beyond it (-72 deg, 1.2 km). POV only; a stepped digital zoom; one long pulse. Both are in
    terrain sight only from about 550 to 710 m (the dome drops behind the bench after 710), hence 700."""
    road_m = 700.0
    fr = road_frame(road_m)
    eye = (0.0, 0.0, _eye_z())
    hull = to_local(fr, site_point("O04_Airship", "hull", rise=0.45))
    dome = to_local(fr, site_point("O07_Observatory", "tower", key="T2_brass_dome", rise=0.8))
    tg = {"airship": hull, "observatory": dome}
    pa, ya = _aim(eye, hull)
    po, yo = _aim(eye, dome)
    cams = [
        _pov("CINP04_S1_POV90", 90.0, [(0.0, *eye, 0, -3, 0, "cubic"), (2.0, *eye, 0, pa, ya, "cubic")], tg, ("airship",)),
        _pov("CINP04_S2_POV40", 40.0, [(2.4, *eye, 0, pa, ya, "constant")], tg, ("airship",)),
        _pov("CINP04_S2_POV15", 15.0, [(3.2, *eye, 0, pa, ya, "linear"), (5.4, *eye, 0, pa + 0.2, ya + 0.4, "linear")], tg, ("airship",)),
        _pov("CINP04_S3_POV25", 25.0, [(5.4, *eye, 0, pa, ya, "cubic"), (6.8, *eye, 0, po, yo, "cubic"), (7.0, *eye, 0, po, yo, "constant")], tg, ("observatory",)),
        _pov("CINP04_S4_POV90", 90.0, [(7.0, *eye, 0, po, yo, "cubic"), (9.0, *eye, 0, -3, 0, "cubic")], tg, ()),
    ]
    shots = [(0.0, 2.4, "CINP04_S1_POV90"), (2.4, 3.2, "CINP04_S2_POV40"), (3.2, 5.4, "CINP04_S2_POV15"),
             (5.4, 7.0, "CINP04_S3_POV25"), (7.0, 9.0, "CINP04_S4_POV90")]
    origin = to_world(fr, eye)
    mpc = _scan(origin, [(2.2, 3.4, 800.0, 60000.0)], focus=to_world(fr, hull), focus_radius=4000.0,
                focus_keys=[(0.0, 0.0), (3.0, 0.0), (3.2, 1.0), (5.2, 1.0), (5.6, 0.0)],
                ret_keys=[(0.0, 0.0), (2.4, 0.0), (2.8, 0.8), (5.3, 0.8), (5.5, 0.0), (6.8, 0.0), (7.0, 0.5), (8.0, 0.0)])
    return {"asset": "LS_CIN_P04_Airship", "duration": 9.0, "blend_out": 2.0, "cams": cams, "shots": shots,
            "frame": "local", "road_m": road_m, "mpc": mpc}


def plan_poi_waiting_water() -> dict:
    """CIN_P07_WAITING_WATER (10.5 s, road 1,060): the village 160-220 m ahead-right. POV pulse over the dry
    channel, ONE deliberate EXT crane (behind-left, rising) that shows the carrier small at the village edge with
    the tower and the dry channel, then a POV long look at the cold refinery on its hill (1.3 km, +8 deg)."""
    road_m = 1060.0
    fr = road_frame(road_m)
    eye = (0.0, 0.0, _eye_z())
    tower = to_local(fr, site_point("S07_WaitingWater", "tower", rise=0.8))
    sluice = to_local(fr, site_point("S07_WaitingWater", "sluice"))
    centre = to_local(fr, site_point("S07_WaitingWater", "houses", rise=0.3))
    refinery = to_local(fr, site_point("O02_Refinery", "columns", rise=0.95))  # the column tops clear the ridge by ~6 m
    tg = {"tower": tower, "sluice": sluice, "village": centre, "refinery": refinery, "carrier": (0.0, 0.0, 120.0)}
    ps, ys = _aim(eye, sluice)
    pr, yr = _aim(eye, refinery)
    c0 = (-1400.0, -700.0, 350.0)
    c1 = (-1100.0, -900.0, 2300.0)
    mid = tuple(tower[i] * 0.5 + centre[i] * 0.5 for i in range(3))
    p0, y0 = look_at(c0, mid)
    p1, y1 = look_at(c1, mid)
    cams = [
        _pov("CINP07_S1_POV90", 90.0, [(0.0, *eye, 0, -4, 0, "cubic"), (2.5, *eye, 0, ps + 1.0, ys - 4.0, "cubic")], tg, ("sluice", "tower")),
        _cam("CINP07_S2_Crane", 35.0, [(2.5, *c0, 0, p0 - 2.0, y0, "cubic"), (7.0, *c1, 0, p1 - 1.0, y1 + 2.0, "cubic")], tg, ("tower", "village", "carrier")),
        _pov("CINP07_S3_POV15", 15.0, [(7.0, *eye, 0, pr, yr, "linear"), (8.5, *eye, 0, pr + 0.1, yr + 0.3, "linear")], tg, ("refinery",)),
        _pov("CINP07_S4_POV90", 90.0, [(8.5, *eye, 0, pr, yr, "cubic"), (10.5, *eye, 0, -3, 0, "cubic")], tg, ()),
    ]
    shots = [(0.0, 2.5, "CINP07_S1_POV90"), (2.5, 7.0, "CINP07_S2_Crane"), (7.0, 8.5, "CINP07_S3_POV15"), (8.5, 10.5, "CINP07_S4_POV90")]
    mpc = _scan(to_world(fr, eye), [(0.4, 2.6, 150.0, 20000.0)], focus=to_world(fr, sluice), focus_radius=6000.0,
                focus_keys=[(0.0, 0.0), (1.2, 0.0), (1.5, 1.0), (2.5, 1.0), (2.6, 0.0)],
                ret_keys=[(0.0, 0.0), (7.1, 0.0), (7.4, 0.7), (8.4, 0.7), (8.6, 0.0)])
    return {"asset": "LS_CIN_P07_WaitingWater", "duration": 10.5, "blend_out": 2.0, "cams": cams, "shots": shots,
            "frame": "local", "road_m": road_m, "mpc": mpc}


def plan_cin06f() -> dict:
    """CIN_06F_CREST_FORT (20 s): CIN_06 with a 4 s fort prelude. The Crest Fortress's gate stands ~6 m left of
    the road at the crest (road 1,980), so the prelude is POV only: the eyes lift to the broken arch and the
    banner, a short pulse runs the curtain walls, then back to the road tangent where CIN_06's shot 1 begins.
    B06 plays this instead of CIN_06 when the PoiCine tag is on (CIN_06 is left exactly as built)."""
    base = plan_cin06()
    road_m = 1980.0
    fr = road_frame(road_m)
    eye = (0.0, 0.0, _eye_z())
    gate = to_local(fr, site_point("S10_CrestFort", "gate", rise=0.6))
    keep = to_local(fr, site_point("S10_CrestFort", "keep", rise=0.5))
    tg = {"gate": gate, "keep": keep}
    pg, yg = _aim(eye, gate)
    pk, yk = _aim(eye, keep)
    pre = [
        _pov("CIN06F_S0_Fort", 90.0, [(0.0, *eye, 0, -3, 0, "cubic"), (1.6, *eye, 0, min(pg, 18.0), yg + 12.0, "cubic"),
                                       (2.8, *eye, 0, pk + 4.0, yk, "cubic"), (4.0, *eye, 0, -5, 0, "cubic")], tg, ("gate", "keep")),
    ]
    shift = 4.0
    cams = pre
    for c in base["cams"]:
        c2 = dict(c)
        c2["name"] = c["name"].replace("CIN06_", "CIN06F_")
        c2["keys"] = [(k[0] + shift, *k[1:]) for k in c["keys"]]
        cams.append(c2)
    shots = [(0.0, shift, "CIN06F_S0_Fort")] + [(s[0] + shift, s[1] + shift, s[2].replace("CIN06_", "CIN06F_"), *s[3:]) for s in base["shots"]]
    mpc = _scan(to_world(fr, eye), [(1.4, 3.4, 120.0, 12000.0)], focus=to_world(fr, keep), focus_radius=4000.0,
                focus_keys=[(0.0, 0.0), (1.8, 0.0), (2.1, 1.0), (3.3, 1.0), (3.6, 0.0)])
    return {"asset": "LS_CIN_06F_CrestFort", "duration": base["duration"] + shift, "blend_out": 2.0, "cams": cams,
            "shots": shots, "frame": "local", "road_m": road_m, "mpc": mpc}


def plan_poi_works() -> dict:
    """CIN_P15_WORKS (10.5 s, road 2,260, the descent into the basin): the Works' hall and chimney stack 360 m
    ahead-right and below. POV stepped zoom + pulse, then an EXT high wide over the basin (the Works, the
    checkpoint on the road below, the caravanserai beyond; the carrier NOT in frame), then back to the POV."""
    road_m = 2260.0
    fr = road_frame(road_m)
    eye = (0.0, 0.0, _eye_z())
    hall = to_local(fr, site_point("S15_Works", "hall", key="AB_BrokenStructer", rise=0.6))
    stack = to_local(fr, site_point("S15_Works", "hall", key="AB_Pillar_low", rise=0.9))
    serai = to_local(fr, site_point("S13_NumberedStop", "walls", rise=0.4))
    check_ = to_local(fr, site_point("S12_Checkpoint", "barrier", rise=0.5))
    tg = {"hall": hall, "stack": stack, "serai": serai, "checkpoint": check_}
    ph, yh = _aim(eye, hall)
    cw = (hall[0] * 0.35, hall[1] * 0.35 + 2500.0, 3800.0)
    look = tuple(hall[i] * 0.6 + serai[i] * 0.4 for i in range(3))
    pw, yw = look_at(cw, look)
    cams = [
        _pov("CINP15_S1_POV90", 90.0, [(0.0, *eye, 0, -4, 0, "cubic"), (1.5, *eye, 0, ph, yh, "cubic")], tg, ("hall",)),
        _pov("CINP15_S2_POV40", 40.0, [(1.5, *eye, 0, ph, yh, "constant")], tg, ("hall", "stack")),
        _pov("CINP15_S2_POV18", 18.0, [(2.3, *eye, 0, ph + 0.5, yh, "linear"), (5.0, *eye, 0, ph + 0.7, yh + 0.3, "linear")], tg, ("hall", "stack")),
        _cam("CINP15_S3_BasinWide", 50.0, [(5.0, *cw, 0, pw, yw - 1.0, "linear"), (8.5, cw[0] + 250.0, cw[1], cw[2] + 100.0, 0, pw, yw + 1.0, "linear")],
             tg, ("hall", "serai")),
        _pov("CINP15_S4_POV90", 90.0, [(8.5, *eye, 0, ph, yh, "cubic"), (10.5, *eye, 0, -3, 0, "cubic")], tg, ()),
    ]
    shots = [(0.0, 1.5, "CINP15_S1_POV90"), (1.5, 2.3, "CINP15_S2_POV40"), (2.3, 5.0, "CINP15_S2_POV18"),
             (5.0, 8.5, "CINP15_S3_BasinWide"), (8.5, 10.5, "CINP15_S4_POV90")]
    mpc = _scan(to_world(fr, eye), [(1.6, 3.2, 300.0, 30000.0)], focus=to_world(fr, hall), focus_radius=3500.0,
                focus_keys=[(0.0, 0.0), (2.4, 0.0), (2.6, 1.0), (4.8, 1.0), (5.0, 0.0)],
                ret_keys=[(0.0, 0.0), (1.6, 0.0), (2.0, 0.8), (4.9, 0.8), (5.0, 0.0)])
    return {"asset": "LS_CIN_P15_Works", "duration": 10.5, "blend_out": 2.0, "cams": cams, "shots": shots,
            "frame": "local", "road_m": road_m, "mpc": mpc}


def plan_poi_cistern() -> dict:
    """CIN_P17_CISTERN (10.5 s, road 2,980): the terraced dry cistern 70-80 m ahead-right, sunk below the road.
    POV: a short pulse whose 2 m height contours land exactly on the dry terraces (the radio's "fourth step");
    EXT: a slow overhead rise looking straight down the stair into the empty bottom; POV: the notice board."""
    road_m = 2980.0
    fr = road_frame(road_m)
    eye = (0.0, 0.0, _eye_z())
    bottom = to_local(fr, site_point("S17_DryCistern", "bottom", rise=0.2))
    stair = to_local(fr, site_point("S17_DryCistern", "stair", rise=0.0))
    board = to_local(fr, site_point("S17_DryCistern", "board", key="B01_sign02", rise=1.0))
    tg = {"bottom": bottom, "stair": stair, "board": board}
    rim = to_local(fr, site_point("S17_DryCistern", "top", rise=0.6))   # from the road only the rim clears the edge
    tg["rim"] = rim
    pb, yb = _aim(eye, rim)
    pd, yd = _aim(eye, board)
    top0 = (stair[0] - 900.0, stair[1] - 600.0, 1500.0)
    top1 = (stair[0] - 700.0, stair[1] - 450.0, 2600.0)
    p0, y0 = look_at(top0, bottom)
    p1, y1 = look_at(top1, bottom)
    cams = [
        _pov("CINP17_S1_POV90", 90.0, [(0.0, *eye, 0, -4, 0, "cubic"), (2.0, *eye, 0, pb - 2.0, yb, "cubic")], tg, ("rim",)),
        _cam("CINP17_S2_Overhead", 24.0, [(2.0, *top0, 0, p0, y0, "cubic"), (7.0, *top1, 0, p1, y1 - 4.0, "cubic")], tg, ("bottom", "stair")),
        _pov("CINP17_S3_POV40", 40.0, [(7.0, *eye, 0, pd, yd, "linear"), (8.5, *eye, 0, pd, yd + 0.5, "linear")], tg, ("board",)),
        _pov("CINP17_S4_POV90", 90.0, [(8.5, *eye, 0, pd, yd, "cubic"), (10.5, *eye, 0, -3, 0, "cubic")], tg, ()),
    ]
    shots = [(0.0, 2.0, "CINP17_S1_POV90"), (2.0, 7.0, "CINP17_S2_Overhead"), (7.0, 8.5, "CINP17_S3_POV40"), (8.5, 10.5, "CINP17_S4_POV90")]
    mpc = _scan(to_world(fr, eye), [(0.6, 2.4, 60.0, 9000.0)], focus=to_world(fr, stair), focus_radius=2500.0,
                focus_color=AMBER, focus_keys=[(0.0, 0.0), (1.2, 0.0), (1.5, 1.0), (2.0, 1.0), (2.2, 0.0)])
    return {"asset": "LS_CIN_P17_Cistern", "duration": 10.5, "blend_out": 2.0, "cams": cams, "shots": shots,
            "frame": "local", "road_m": road_m, "mpc": mpc}


def plan_poi_low_voice() -> dict:
    """CIN_PO01_LOW_VOICE (8 s, off-road, WORLD frame): entering the O01 zone (the Low Voice post, the old post
    office with its radio room). EXT only, the carrier never in frame (its position off-road is not known):
    a low slow push on the post office with the small mast behind, then a 50 mm look through the back-room
    doorway at the radio desk. blend_in 1.0 s from the carrier camera; hand-back 2.0 s."""
    post = site_point("O01_LowVoicePost", "post_office", rise=0.45)
    mast = site_point("O01_LowVoicePost", "mast", key="T2_relay_tower", rise=0.9)
    desk = site_point("O01_LowVoicePost", "back_room", key="T2_radio_desk", rise=0.6)
    tg = {"post": post, "mast": mast, "desk": desk}
    # the spur arrives from -X (tether_paths O01): stand the camera ~22 m out on that side of the post, low
    c0 = (post[0] - 2100.0, post[1] + 600.0, post[2] - 150.0)
    c1 = (post[0] - 1700.0, post[1] + 500.0, post[2] - 130.0)
    look = tuple(post[i] * 0.7 + mast[i] * 0.3 for i in range(3))
    p0, y0 = look_at(c0, look)
    p1, y1 = look_at(c1, look)
    d0 = (desk[0] + 450.0, desk[1] - 250.0, desk[2] + 60.0)
    pd, yd = look_at(d0, desk)
    cams = [
        _cam("CINPO01_S1_Push", 35.0, [(0.0, *c0, 0, p0 + 1.0, y0, "cubic"), (4.5, *c1, 0, p1 + 1.0, y1 + 1.0, "cubic")], tg, ("post", "mast")),
        _cam("CINPO01_S2_Desk", 50.0, [(4.5, *d0, 0, pd, yd, "linear"), (8.0, d0[0] - 30.0, d0[1] + 15.0, d0[2], 0, pd, yd, "linear")], tg, ("desk",)),
    ]
    shots = [(0.0, 4.5, "CINPO01_S1_Push"), (4.5, 8.0, "CINPO01_S2_Desk")]
    return {"asset": "LS_CIN_PO01_LowVoice", "duration": 8.0, "blend_out": 2.0, "cams": cams, "shots": shots, "frame": "world"}


def plan_cin23(road_m: float | None = None) -> dict:
    """CIN_23_THE_MARK (12 s, optional, tag MarkCine), local frame at road 4,990 (B23, RoadPassHuman UE 19.5: the
    Keeper stops there, the pawn; the runner puts the origin at his feet). 1 EXT 24 mm low: the Keeper, the tilt
    climbs the mast; 2 EXT 100 mm insert on the plate (the palm in a ring); 3 hand-back to the traveller camera.
    The Keeper is the pawn at the origin, NOT at the High Voice StandPoint: nothing moves him before CIN_24's
    SnapKeeperToPlate, and the StandPoint (the capsule centre at the plate, since the set moved onto the mast) is
    ~18 m further up-road. Until 2026-09-28 this plan framed the StandPoint + 100 cm (task ENDING-PREP).
    Numbers from probe_ending.json (PROVISIONAL)."""
    pe = probe_ending()
    road_m = 4990.0 if road_m is None else road_m
    fr = road_frame(road_m)
    hv = pe["high_voice"]
    plate = to_local(fr, hv["plate"])
    crown = to_local(fr, pe["mast_crown"])
    base = to_local(fr, pe["mast_base"])
    keeper = (0.0, 0.0, ground_local(fr) + 100.0)       # his chest, over his feet at the origin
    tg = {"keeper": keeper, "plate": plate, "crown": crown}
    c1 = (keeper[0] - 450.0, keeper[1] - 250.0, ground_local(fr, keeper[0] - 450.0, keeper[1] - 250.0) + 60.0)
    pk, yk = look_at(c1, keeper)
    pc, yc = look_at(c1, (base[0], base[1], base[2] + 1500.0))
    # 2 the insert: the plate is world-fixed and the camera rides with the frame, so it sits on the road axis through
    # the plate (the plate is on the mast's down-road face, on the axis), 2.5 m short of it, looking straight up-road:
    # a stop further along only brings it closer. The first plan (90 cm back, 60 cm left) lost the plate for a stop
    # 2 m on (task ENDING-PREP).
    ci = (plate[0] - 250.0, plate[1], plate[2] + 10.0)
    pp, yp = look_at(ci, plate)
    cams = [
        _cam("CIN23_S1_LowTilt", 24.0, [(0.0, *c1, 0, pk + 2.0, yk, "cubic"), (4.0, *c1, 0, min(pc, 60.0), yc, "cubic")], tg, ("keeper",),
             only_at={"keeper": (0.0,)}),
        _cam("CIN23_S2_Plate", 100.0, [(4.0, *ci, 0, pp, yp, "linear"), (10.0, ci[0] + 30.0, ci[1], ci[2], 0, pp, yp, "linear")], tg, ("plate",)),
        _cam("CIN23_S3_Back", 35.0, [(10.0, keeper[0] - 350.0, keeper[1], ground_local(fr, keeper[0] - 350.0, keeper[1]) + 160.0, 0, -5.0, 0.0, "constant")], tg, ()),
    ]
    shots = [(0.0, 4.0, "CIN23_S1_LowTilt"), (4.0, 10.0, "CIN23_S2_Plate"), (10.0, 12.0, "CIN23_S3_Back")]
    return {"asset": "LS_CIN_23_TheMark", "duration": 12.0, "blend_out": 2.0, "cams": cams, "shots": shots,
            "frame": "local", "road_m": road_m, "window_m": (0.0, 1.0)}


POI_PLANS = {"CIN_P04_AIRSHIP": plan_poi_airship, "CIN_P07_WAITING_WATER": plan_poi_waiting_water,
             "CIN_06F_CREST_FORT": plan_cin06f, "CIN_P15_WORKS": plan_poi_works, "CIN_P17_CISTERN": plan_poi_cistern,
             "CIN_PO01_LOW_VOICE": plan_poi_low_voice}

PLANS = {"CIN_01_DIRECTIVE": plan_cin01, "CIN_04_DUST_FRONT": plan_cin04,
         "CIN_06_ROAD_AHEAD": plan_cin06, "CIN_11_WAYSTATION": plan_cin11,
         "CIN_15_IN_RANGE": plan_cin15, "CIN_18_COLLAPSE": plan_cin18, "CIN_19_HATCH": plan_cin19,
         "CIN_24_TRANSMISSION": plan_cin24, "CIN_25_END_CARD": plan_cin25, "CIN_23_THE_MARK": plan_cin23, **POI_PLANS}


# ----------------------------------------------------------------------------- editor chunks

SETUP = """import unreal
AT = unreal.AssetToolsHelpers.get_asset_tools()
E = unreal.EditorAssetLibrary
full = '{folder}/{asset}'
if E.does_asset_exist(full):
    seq = unreal.load_asset(full)
    for b in list(seq.get_bindings()):
        b.remove()
    for t in list(seq.get_tracks()):
        seq.remove_track(t)
else:
    seq = AT.create_asset('{asset}', '{folder}', unreal.LevelSequence, unreal.LevelSequenceFactoryNew())
seq.set_display_rate(unreal.FrameRate({fps}, 1))
seq.set_playback_start_seconds(0.0)
seq.set_playback_end_seconds({duration})
print('setup', full, len(seq.get_bindings()))
"""

CAMERA = """import unreal
seq = unreal.load_asset('{folder}/{asset}')
b = seq.add_spawnable_from_class(unreal.CineCameraActor)
b.set_display_name('{name}')
tmpl = unreal.MovieSceneBindingExtensions.get_object_template(b)
comp = tmpl.get_editor_property('camera_component')  # get_cine_camera_component() is None on a spawnable template
comp.set_editor_property('current_focal_length', {focal})
fs = comp.get_editor_property('focus_settings')
fs.set_editor_property('focus_method', unreal.CameraFocusMethod.DISABLE)
comp.set_editor_property('focus_settings', fs)
for bl in {blendables}:
    pp = comp.get_editor_property('post_process_settings')
    wb = pp.get_editor_property('weighted_blendables')
    arr = list(wb.get_editor_property('array'))
    w = unreal.WeightedBlendable()
    w.set_editor_property('weight', 1.0)
    w.set_editor_property('object', unreal.load_asset(bl))
    arr.append(w)
    wb.set_editor_property('array', arr)
    pp.set_editor_property('weighted_blendables', wb)
    comp.set_editor_property('post_process_settings', pp)
    comp.set_editor_property('post_process_blend_weight', 1.0)
tr = b.add_track(unreal.MovieScene3DTransformTrack)
sec = tr.add_section()
sec.set_range_seconds({t0}, {t1})
ch = sec.get_all_channels()
TR = unreal.MovieSceneTimeUnit.TICK_RESOLUTION
M = {{'linear': unreal.MovieSceneKeyInterpolation.LINEAR, 'constant': unreal.MovieSceneKeyInterpolation.CONSTANT, 'cubic': unreal.MovieSceneKeyInterpolation.AUTO}}
for tick, vals, mode in {keys}:
    for i in range(6):
        ch[i].add_key(unreal.FrameNumber(int(tick)), float(vals[i]), 0.0, TR, M[mode])
print('{name}', round(comp.get_editor_property('current_focal_length'), 2), sum(c.get_num_keys() for c in ch))
"""

CUTS = """import unreal
seq = unreal.load_asset('{folder}/{asset}')
ids = {{}}
for b in seq.get_bindings():
    ids[str(b.get_display_name())] = b
for old in [t for t in seq.get_tracks() if t.get_class().get_name() == 'MovieSceneCameraCutTrack']:
    seq.remove_track(old)
track = seq.add_track(unreal.MovieSceneCameraCutTrack)
# bCanBlend is not Python-visible: set it afterwards with Hayba object_set_property on the printed track path
last = None
for t0, t1, cam, ease_in in {sections}:
    s = track.add_section()
    s.set_range_seconds(t0, t1)
    s.set_camera_binding_id(seq.get_binding_id(ids[cam]))
    if ease_in > 0:
        s.set_ease_in_duration(int(ease_in * {ticks}))
    last = s
if {ease_ticks} > 0:
    last.set_ease_out_duration({ease_ticks})
print('cuts', len(track.get_sections()), 'track', track.get_path_name())
"""

FADE = """import unreal
seq = unreal.load_asset('{folder}/{asset}')
tr = seq.add_track(unreal.MovieSceneFadeTrack)
sec = tr.add_section()
sec.set_range_seconds(0.0, {duration})
sec.set_editor_property('fade_color', unreal.LinearColor({r}, {g}, {b}, 1.0))
ch = sec.get_all_channels()[0]
TR = unreal.MovieSceneTimeUnit.TICK_RESOLUTION
M = {{'linear': unreal.MovieSceneKeyInterpolation.LINEAR, 'constant': unreal.MovieSceneKeyInterpolation.CONSTANT, 'cubic': unreal.MovieSceneKeyInterpolation.AUTO}}
for tick, v, mode in {keys}:
    ch.add_key(unreal.FrameNumber(int(tick)), float(v), 0.0, TR, M[mode])
print('fade keys', ch.get_num_keys(), 'colour', ({r}, {g}, {b}))
"""

MPCTRACK = """import unreal
seq = unreal.load_asset('{folder}/{asset}')
tr = seq.add_track(unreal.MovieSceneMaterialParameterCollectionTrack)
tr.set_editor_property('mpc', unreal.load_asset('{mpc}'))
sec = tr.add_section()
sec.set_range_seconds(0.0, {duration})
n = 0
for name, keys in {scalars}.items():
    for tick, v in keys:
        sec.add_scalar_parameter_key(name, unreal.FrameNumber(int(tick)), float(v))
        n += 1
for name, keys in {vectors}.items():
    for tick, v in keys:
        sec.add_color_parameter_key(name, unreal.FrameNumber(int(tick)), unreal.LinearColor(float(v[0]), float(v[1]), float(v[2]), 1.0))
        n += 1
print('mpc keys', n, 'channels', len(sec.get_all_channels()))
"""

SAVE = """import unreal
print('saved', unreal.EditorAssetLibrary.save_asset('{folder}/{asset}', only_if_is_dirty=False))
"""

READ = """import unreal
seq = unreal.load_asset('{folder}/{asset}')
print('range', seq.get_playback_start_seconds(), seq.get_playback_end_seconds(), 'fps', str(seq.get_display_rate().numerator))
for b in seq.get_bindings():
    keys = 0
    for t in b.get_tracks():
        for s in t.get_sections():
            keys += sum(c.get_num_keys() for c in s.get_all_channels())
    print('binding', str(b.get_display_name()), 'keys', keys)
for t in seq.get_tracks():
    print('track', t.get_class().get_name(), 'sections', len(t.get_sections()))
"""


def cut_sections(plan: dict) -> list:
    """(t0, t1, cam, ease_in) per shot. A shot with a 4th element blends in over that many seconds: the previous
    section is extended to t0 + blend_in so the two overlap (UE's camera-cut blend is the overlap)."""
    out = []
    for shot in plan["shots"]:
        t0, t1, cam = shot[:3]
        ease = shot[3] if len(shot) > 3 else 0.0
        if ease > 0 and out:
            p = out[-1]
            out[-1] = (p[0], max(p[1], t0 + ease), p[2], p[3])
        out.append((t0, t1, cam, ease))
    return out


def cam_ranges(plan: dict) -> dict:
    r = {}
    for t0, t1, cam, _ in cut_sections(plan):
        a, b = r.get(cam, (t0, t1))
        r[cam] = (min(a, t0), max(b, t1))
    return r


def emit(cin: str, out: Path) -> int:
    plan = PLANS[cin]()
    if not plan.get("asset"):
        print(f"{cin} has no Level Sequence ({plan.get('widget')}); run `credits` for its roll text")
        return 1
    out.mkdir(parents=True, exist_ok=True)
    common = {"folder": FOLDER, "asset": plan["asset"], "fps": FPS, "duration": plan["duration"]}
    (out / "00_setup.py").write_text(SETUP.format(**common), encoding="utf-8")
    ranges = cam_ranges(plan)
    for i, cam in enumerate(plan["cams"]):
        t0, t1 = ranges[cam["name"]]
        keys = [(round(k[0] * TICKS), [round(v, 3) for v in (k[1], k[2], k[3], k[4], k[5], k[6])], k[7]) for k in cam["keys"]]
        chunk = CAMERA.format(**common, name=cam["name"], focal=round(cam["focal"], 3),
                              t0=t0, t1=t1, keys=keys, blendables=cam.get("blendables", []))
        if "sensor_eye_cm" in cam:
            chunk = chunk.replace("seq.add_spawnable_from_class(unreal.CineCameraActor)",
                                  "seq.add_spawnable_from_class(unreal.SaskartaSensorCamera)")
            chunk = chunk.replace("comp = tmpl.get_editor_property('camera_component')",
                f"tmpl.set_editor_property('authored_eye_height_cm', {cam['sensor_eye_cm']!r})\n"
                "comp = tmpl.get_editor_property('camera_component')")
        (out / f"10_cam_{i:02d}.py").write_text(chunk, encoding="utf-8")
    if plan.get("fade"):
        f = plan["fade"]
        fk = [(round(t * TICKS), v, m) for t, v, m in f["keys"]]
        r, g, b = f["color"]
        (out / "70_fade.py").write_text(FADE.format(**common, r=r, g=g, b=b, keys=fk), encoding="utf-8")
    if plan.get("mpc"):
        m = plan["mpc"]
        sk = {n: [(round(t * TICKS), v) for t, v in ks] for n, ks in m["scalars"].items()}
        vk = {n: [(round(t * TICKS), tuple(v)) for t, v in ks] for n, ks in m["vectors"].items()}
        (out / "60_mpc.py").write_text(MPCTRACK.format(**common, mpc=m["asset"], scalars=sk, vectors=vk), encoding="utf-8")
    if plan["shots"]:
        (out / "80_cuts.py").write_text(CUTS.format(**common, sections=cut_sections(plan), ticks=TICKS,
                                                    ease_ticks=int(plan["blend_out"] * TICKS)), encoding="utf-8")
    for fname, text in plan.get("extra", {}).items():   # CIN_19: the attached body, the capsule glow
        (out / fname).write_text(text, encoding="utf-8")
    (out / "90_save.py").write_text(SAVE.format(**common), encoding="utf-8")
    (out / "99_read.py").write_text(READ.format(**common), encoding="utf-8")
    print("emitted", len(list(out.glob("*.py"))), "chunks to", out)
    return 0


# ----------------------------------------------------------------------------- check (offline framing)
FILMBACK_H = FILMBACK_W * 9.0 / 16.0


def _wrap(a):
    return (a + 180.0) % 360.0 - 180.0


def _frame_xy(c, pos, pitch, yaw, p):
    """Where world/local point p sits in camera c's frame: (x, y) as fractions of the half-width / half-height."""
    hh = math.degrees(math.atan((FILMBACK_W / 2.0) / c["focal"]))
    vh = math.degrees(math.atan((FILMBACK_H / 2.0) / c["focal"]))
    tp, ty = look_at(pos, p)
    return _wrap(ty - yaw) / hh, (tp - pitch) / vh


def check(cin: str, strict: bool = False, window: bool = False, quiet: bool = False) -> int:
    """Every key of every camera: where each named target sits in the frame, as a fraction of the half-width /
    half-height (|x| <= 1 and |y| <= 1 is in frame; + is right / up). Pitch and yaw offsets are treated as
    independent (fine away from the poles; straight-up keys are skipped). Exit 1 if a target listed for a
    camera is never in frame; with `strict`, if it leaves the frame at any key.
    `window` (local plans with window_m) adds window_check: the same keys from every stop point, with heights.
    Terrain is checked by `terrain` (offline heightmap); set dressing is not: render_camera in the editor lane."""
    plan = PLANS[cin]()
    say = (lambda *a: None) if quiet else print
    bad = 0
    for c in plan["cams"]:
        tg = c.get("targets") or {}
        if not tg:
            continue
        hh = math.degrees(math.atan((FILMBACK_W / 2.0) / c["focal"]))
        vh = math.degrees(math.atan((FILMBACK_H / 2.0) / c["focal"]))
        say(f"{c['name']}  {c['focal']:.1f} mm  (half-fov {hh:.1f} x {vh:.1f} deg)")
        seen = {k: False for k in tg}
        always = {k: True for k in tg}
        for k in c["keys"]:
            t, pos, pitch, yaw = k[0], k[1:4], k[5], k[6]
            if abs(pitch) > 80:
                say(f"   t={t:5.1f}  looking straight up: skipped")
                seen = {n: True for n in seen}
                continue
            row = []
            for n, p in tg.items():
                if not _wanted(c, n, t):
                    continue
                x, y = _frame_xy(c, pos, pitch, yaw, p)
                inside = abs(x) <= 1.0 and abs(y) <= 1.0
                seen[n] |= inside
                always[n] &= inside
                row.append(f"{n} ({x:+.2f}, {y:+.2f}){'' if inside else ' OUT'}")
            say(f"   t={t:5.1f}  " + "  ".join(row))
        for n in tg:
            if not seen[n]:
                say(f"   ! {n} is never in frame")
                bad += 1
            elif strict and not always[n]:
                say(f"   ! {n} leaves the frame (strict)")
                bad += 1
    if window and plan.get("frame") == "local" and plan.get("window_m"):
        bad += window_check(cin, quiet=quiet)
    return 1 if bad else 0


WINDOW_STEP_M = 1.0


def window_stops(plan: dict, step_m: float = WINDOW_STEP_M) -> list:
    lo, hi = plan["window_m"]
    n = int(round((hi - lo) / step_m))
    return [plan["road_m"] + lo + i * step_m for i in range(n + 1)]


def _los(t, np, a, b) -> tuple:
    """Terrain over the straight line a -> b (world cm), sampled every metre from 0.5 m out to 3 m short of b (a
    target on the ground is not hidden by its own footing): (the most the terrain rises over the line in cm, where in
    m). <= 0 is a clear line."""
    dist = math.dist(a, b)
    s = np.arange(0.5, max(0.5, dist / 100.0 - 3.0), 1.0) * 100.0
    if len(s) == 0:
        return (-1.0, 0.0)
    f = s / dist
    lx, ly, lz = a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f
    over = t.height(lx, ly) * 100.0 - lz
    i = int(np.argmax(over))
    return (float(over[i]), float(s[i] / 100.0))


def window_report(cin: str, step_m: float = WINDOW_STEP_M) -> dict:
    """The numbers window_check judges (see there): per camera the lowest clearance, per (camera, target) the worst
    framing and the worst terrain over the line of sight, each with the stop point and key time it happens at."""
    plan = PLANS[cin]()
    t = terrain()
    np = None
    if t is not None:
        import numpy as np  # noqa: F811  (only with the heightmap)
    stops = window_stops(plan, step_m)
    low, out, hid, graze, drift = {}, {}, {}, {}, {}
    for m in stops:
        fr = road_frame(m)
        truth = {c["name"]: c for c in PLANS[cin](road_m=m)["cams"]}
        for c in plan["cams"]:
            tg = {n: to_world(fr, p) for n, p in (truth[c["name"]].get("targets") or {}).items()}
            if c.get("rides"):
                for k, kt in zip(c["keys"], truth[c["name"]]["keys"]):
                    dv = math.dist(k[1:4], kt[1:4])
                    if dv > drift.get(c["name"], (-1.0,))[0]:
                        drift[c["name"]] = (dv, m, k[0])
            for k in c["keys"]:
                w = to_world(fr, k[1:4])
                pitch, yaw = k[5], k[6] + fr["yaw"]
                if t is not None:
                    clear = w[2] - float(t.height(w[0], w[1])) * 100.0
                    if clear < low.get(c["name"], (1e18,))[0]:
                        low[c["name"]] = (clear, m, k[0])
                for n, p in tg.items():
                    if not _wanted(c, n, k[0]):
                        continue
                    if abs(pitch) <= 80:
                        x, y = _frame_xy(c, w, pitch, yaw, p)
                        v = max(abs(x), abs(y))
                        if v > out.get((c["name"], n), (-1.0,))[0]:
                            out[(c["name"], n)] = (v, m, k[0], x, y)
                    if t is not None:
                        o, at = _los(t, np, w, p)
                        h = _hidden_cm(n, o, at, math.dist(w, p))
                        if h > hid.get((c["name"], n), (-1e18,))[0]:
                            hid[(c["name"], n)] = (h, m, k[0], at, o)
                        if o > 0 and o > graze.get((c["name"], n), (0.0,))[0]:
                            graze[(c["name"], n)] = (o, m, k[0], at)
    return {"stops": stops, "low": low, "out": out, "hid": hid, "graze": graze, "drift": drift}


def window_check(cin: str, min_clear_cm: float = 40.0, quiet: bool = False, step_m: float = WINDOW_STEP_M) -> int:
    """The runner's origin is wherever the pawn stops (a queued beat, a slow or a fast player), but the sequence is
    baked once from the plan at its nominal road m. For every stop point over road_m + window_m (every `step_m`), the
    NOMINAL keys are placed in that stop's frame (road_frame: the spline point, the yaw of travel, the carrier's feet)
    and checked against the scene as it is at that stop: the plan re-derived there (PLANS[cin](road_m=stop)), so the
    crown and the plate stay where they are in the world, the carrier and the capsule ride with the frame, and the
    Keeper stands on the ground beside the capsule. For every camera (not only the POV) and every key:
      1. clearance: the camera is at least min_clear_cm over the landscape under it (heightmap);
      2. framing: every target the camera must frame is inside it (strict: at every key);
      3. line of sight: no terrain between the camera and each of those targets.
    Exit 1 on any failure. Without the heightmap only 2 runs (and the origin falls back to the spline z)."""
    plan = PLANS[cin]()
    say = (lambda *a: None) if quiet else print
    if plan.get("frame") != "local" or not plan.get("window_m"):
        return 0
    r = window_report(cin, step_m)
    stops = r["stops"]
    say(f"{cin}: window {stops[0]:.0f}-{stops[-1]:.0f} m, {len(stops)} stops every {step_m:g} m, origin z = {ORIGIN_Z}")
    bad = 0
    for c in plan["cams"]:
        n = c["name"]
        row = []
        if n in r["low"]:
            clear, m, tk = r["low"][n]
            ok = clear >= min_clear_cm
            bad += 0 if ok else 1
            row.append(f"lowest {clear / 100.0:.2f} m over the ground (stop {m:.0f}, t={tk:g}){'' if ok else '  LOW'}")
        if n in r["drift"]:
            dv, m, tk = r["drift"][n]
            ok = dv <= RIDE_TOL_CM
            bad += 0 if ok else 1
            row.append(f"on the carrier: {dv:.0f} cm off at worst (stop {m:.0f}){'' if ok else '  ADRIFT'}")
        for (cn, tn), (v, m, tk, x, y) in r["out"].items():
            if cn == n:
                ok = v <= 1.0
                bad += 0 if ok else 1
                row.append(f"{tn} worst ({x:+.2f}, {y:+.2f}) at stop {m:.0f} t={tk:g}{'' if ok else '  OUT'}")
        for (cn, tn), (h, m, tk, at, o) in r["hid"].items():
            if cn == n and h > 0:
                bad += 1
                row.append(f"{tn} BLOCKED from stop {m:.0f} t={tk:g} ({o:.0f} cm of terrain over the line at {at:.0f} m)")
        for (cn, tn), (o, m, tk, at) in r["graze"].items():
            if cn == n and r["hid"][(cn, tn)][0] <= 0:
                row.append(f"{tn} grazed from stop {m:.0f} ({o:.0f} cm of crest over its centre line at {at:.0f} m; the top of its "
                           f"{2 * TARGET_RADIUS_CM.get(tn, 0.0) / 100:.1f} m shows)")
        say(f"   {n}: " + ("; ".join(row) if row else "no targets"))
    return 1 if bad else 0


def world_pose(plan: dict, key) -> tuple:
    """A camera key (t, x, y, z, roll, pitch, yaw, interp) as a world pose (x, y, z, roll, pitch, yaw): local plans go
    through their road frame (road_frame at plan['road_m']), world plans are returned as they are."""
    x, y, z, roll, pitch, yaw = key[1:7]
    if plan.get("frame") != "local":
        return (x, y, z, roll, pitch, yaw)
    fr = road_frame(plan["road_m"])
    w = to_world(fr, (x, y, z))
    return (w[0], w[1], w[2], roll, pitch, yaw + fr["yaw"])


def world_point(plan: dict, p) -> tuple:
    if plan.get("frame") != "local":
        return tuple(p)
    return to_world(road_frame(plan["road_m"]), p)


def terrain_check(cin: str, min_clear_cm: float = 40.0, quiet: bool = False) -> int:
    """Offline, against the landscape heightmap: every camera key's clearance above the ground under it, and a
    line of sight from each key to each target the camera must frame (sampled every metre; the last 3 m before the
    target and the first 0.5 m are skipped, so a target on the ground is not hidden by its own footing).
    Exit 1 if a camera sits under min_clear_cm of ground or a target is behind terrain. Returns 2 without the
    heightmap. Set dressing, the carrier and the hut are not in the heightmap: render_camera still decides."""
    t = terrain()
    say = (lambda *a: None) if quiet else print
    if t is None:
        say(f"no heightmap at {HEIGHTMAP}: terrain check skipped")
        return 2
    import numpy as np  # noqa: E402  (only with the heightmap)
    plan = PLANS[cin]()
    bad = 0
    for c in plan["cams"]:
        tg = {n: world_point(plan, p) for n, p in (c.get("targets") or {}).items()}
        say(f"{c['name']}")
        for k in c["keys"]:
            x, y, z, _r, pitch, yaw = world_pose(plan, k)
            g = float(t.height(x, y)) * 100.0
            clear = z - g
            row = [f"clear {clear / 100.0:6.2f} m{'  LOW' if clear < min_clear_cm else ''}"]
            bad += 1 if clear < min_clear_cm else 0
            for n, p in tg.items():
                if not _wanted(c, n, k[0]):
                    continue
                o, at = _los(t, np, (x, y, z), p)
                if _hidden_cm(n, o, at, math.dist((x, y, z), p)) > 0:
                    row.append(f"{n} BLOCKED at {at:.0f} m (terrain {o / 100.0:.1f} m over the line)")
                    bad += 1
                else:
                    row.append(f"{n} ok")
            if c["name"].endswith("_Seated"):
                row.append(_valley(t, np, x, y, z, pitch, yaw, c["focal"]))
            say(f"   t={k[0]:5.1f}  " + "  ".join(row))
    return 1 if bad else 0


def _valley(t, np, x, y, z, pitch, yaw, focal) -> str:
    """For the seated shot: the elevation of the near skyline (the highest terrain angle within 150 m) along the
    view's centre and edges, against the frame's lower edge. Below the edge, the frame is all valley and sky."""
    vh = math.degrees(math.atan((FILMBACK_H / 2.0) / focal))
    hh = math.degrees(math.atan((FILMBACK_W / 2.0) / focal))
    out = []
    for dy in (-hh, 0.0, hh):
        d = np.arange(2.0, 150.0, 1.0) * 100.0
        cx, cy = x + np.cos(np.radians(yaw + dy)) * d, y + np.sin(np.radians(yaw + dy)) * d
        ang = np.degrees(np.arctan2(t.height(cx, cy) * 100.0 - z, d)).max()
        out.append(round(float(ang), 1))
    edge = pitch - vh
    return f"near skyline {out} deg vs frame bottom {edge:.1f} ({'valley fills the frame' if max(out) <= edge else 'near ground in the lower frame'})"


# ----------------------------------------------------------------------------- probe (editor chunk)
PROBE_ENDING_CHUNK = r'''# python_run (Hayba). Read-only apart from one temporary carrier it spawns far below the map and destroys.
# Prints one line "PROBE_JSON {...}": save the output and run `build_cinematics.py merge-probe <file>`.
# No exception handler (python_run bans that keyword): the carrier is labelled Tmp_ProbeCarrier, and a leftover
# one from a failed run is destroyed first.
import unreal, math, json
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
for a in eas.get_all_level_actors():
    if a.get_actor_label() == 'Tmp_ProbeCarrier':
        a.destroy_actor()
out = {}
cls = unreal.load_object(None, '/Game/SaskartaGaea/Characters/Carrier/BP_Saskarta_Carrier.BP_Saskarta_Carrier_C')
tmp = eas.spawn_actor_from_class(cls, unreal.Vector(0, 0, -900000), unreal.Rotator(0, 0, 0))
tmp.set_actor_label('Tmp_ProbeCarrier')
root = tmp.get_actor_location()
half = tmp.get_component_by_class(unreal.CapsuleComponent).get_scaled_capsule_half_height()
cam = tmp.get_component_by_class(unreal.CameraComponent)
mesh = tmp.get_component_by_class(unreal.SkeletalMeshComponent)
ground = root.z - half
out['carrier_eye_z'] = round(cam.get_world_location().z - ground, 1)
for key, bone in (('capsule_root_local', 'capsule_root'), ('capsule_hatch_local', 'capsule_hatch')):
    v = mesh.get_socket_location(bone)
    out[key] = [round(v.x - root.x, 1), round(v.y - root.y, 1), round(v.z - ground, 1)]
tmp.destroy_actor()
acts = eas.get_all_level_actors()
tcls = unreal.load_object(None, '/Game/SaskartaGaea/Characters/Traveller/BP_Saskarta_Traveller.BP_Saskarta_Traveller_C')
trav = [a for a in acts if a.get_class() == tcls]
out['travellers_in_level'] = len(trav)
if trav:
    out['keeper_half_height_cm'] = round(trav[0].get_component_by_class(unreal.CapsuleComponent).get_scaled_capsule_half_height(), 1)
hv = [a for a in acts if 'Saskarta.HighVoice' in [str(t) for t in a.tags]]
out['high_voice_actors'] = len(hv)
if hv:
    comps = {c.get_name(): c for c in hv[0].get_components_by_class(unreal.SceneComponent)}
    def loc(n):
        v = comps[n].get_world_location()
        return [round(v.x, 1), round(v.y, 1), round(v.z, 1)]
    def rot(n):
        return comps[n].get_world_rotation()
    out['high_voice'] = {'stand': loc('StandPoint'), 'stand_yaw': round(rot('StandPoint').yaw, 1), 'plate': loc('Plate'),
                         'seat': loc('SeatPoint'), 'seat_yaw': round(rot('SeatPoint').yaw, 1), 'seat_pitch': round(rot('SeatPoint').pitch, 1)}
    out['mast_base'] = loc('MastBase')
    out['mast_crown'] = loc('Crown')
else:
    print('no actor tagged Saskarta.HighVoice: keep the provisional high_voice / mast values')
# The road is BP_Saskarta_Road (its RoadSpline). The actor TAGGED Saskarta.Road is BP_Saskarta_RouteTrace (LANE5,
# the StartRouteTrace hook target), which has no spline: never take the first tagged actor blindly.
spl = None
for a in acts:
    if a.get_class().get_name().startswith('BP_Saskarta_Road') and spl is None:
        spl = a.get_component_by_class(unreal.SplineComponent)
out['road_found'] = spl is not None
frames = {}
for road_m, ue_m in FRAMES:
    if not spl:
        break
    d = ue_m * 100.0
    W = unreal.SplineCoordinateSpace.WORLD
    k = spl.find_input_key_closest_to_world_location(spl.get_location_at_distance_along_spline(d, W))
    p = spl.get_location_at_spline_input_key(k, W)
    tan = spl.get_tangent_at_spline_input_key(k, W)
    # the runner's origin: GetLocationAtSplineInputKey, yaw of -GetTangentAtSplineInputKey (toward point 0). z here is
    # the SPLINE's; the runner takes the origin's z from the pawn's feet (RoadCineOrigin), offline the heightmap ground
    frames[str(road_m)] = {'x': round(p.x, 1), 'y': round(p.y, 1), 'z': round(p.z, 1),
                           'yaw': round(math.degrees(math.atan2(-tan.y, -tan.x)), 2), 'key': round(k, 3), 'probed': True}
out['frames'] = frames
print('PROBE_JSON ' + json.dumps(out))
'''


PROBE_MERGE_KEYS = ("carrier_eye_z", "capsule_root_local", "capsule_hatch_local", "keeper_half_height_cm",
                    "high_voice", "mast_base", "mast_crown", "frames")


def merge_probe(text: str, today: str) -> dict:
    """Merge a probe chunk's PROBE_JSON line into probe_ending.json's values (returned, not written). The capsule
    floor and rim follow the sockets; the half-rise eye stays 25 cm over the rim; frames merge per road m."""
    line = next((ln for ln in text.splitlines() if ln.strip().startswith("PROBE_JSON ")), None)
    if line is None:
        raise SystemExit("no PROBE_JSON line in the probe output")
    got = json.loads(line.strip()[len("PROBE_JSON "):])
    pe = probe_ending()
    for k in PROBE_MERGE_KEYS:
        if k == "frames":
            pe.setdefault("frames", {}).update(got.get("frames", {}))
        elif k in got:
            pe[k] = got[k]
    if "capsule_root_local" in got:
        pe["capsule_floor_z"] = got["capsule_root_local"][2]
    if "capsule_hatch_local" in got:
        pe["capsule_rim_z"] = got["capsule_hatch_local"][2]
        pe["half_rise_eye_z"] = round(got["capsule_hatch_local"][2] + 25.0, 1)
    missing = [k for k in ("high_voice", "frames") if not got.get(k)]
    pe["note"] = f"PROBED {today}" + (f" (still provisional: {', '.join(missing)})" if missing else "")
    return pe


def ue_m_for_road_m(road_m: float) -> float:
    s = _samples()
    for a, b in zip(s, s[1:]):
        if a["dist_m"] <= road_m <= b["dist_m"]:
            t = (road_m - a["dist_m"]) / max(1e-6, b["dist_m"] - a["dist_m"])
            return a["ue_spline_distance_m"] + (b["ue_spline_distance_m"] - a["ue_spline_distance_m"]) * t
    raise ValueError(road_m)


def emit_probe_ending(out: Path):
    pe = probe_ending()
    ms = sorted({int(pe["cin15_road_m"]), int(pe["cin18_road_m"])})
    frames = [(m, round(ue_m_for_road_m(m), 2)) for m in ms]
    out.write_text(f"FRAMES = {frames}\n" + PROBE_ENDING_CHUNK, encoding="utf-8")
    print("wrote", out, "- run it through python_run, save its output, then `merge-probe <output file>`")


ENDING = ("CIN_15_IN_RANGE", "CIN_18_COLLAPSE", "CIN_19_HATCH", "CIN_24_TRANSMISSION")
ENDING_OPTIONAL = ("CIN_23_THE_MARK",)


def frames_report(cin: str) -> list:
    """The render_camera poses for the editor lane's frame check (brief step 9): every key of every camera, in
    WORLD space, with the horizontal FOV. Local plans use the probed (or polyline) road frame."""
    plan = PLANS[cin]()
    out = []
    for c in plan["cams"]:
        hfov = math.degrees(2 * math.atan((FILMBACK_W / 2.0) / c["focal"]))
        for k in c["keys"]:
            x, y, z, roll, pitch, yaw = world_pose(plan, k)
            out.append({"cin": cin, "cam": c["name"], "t": k[0], "loc": [round(x, 1), round(y, 1), round(z, 1)],
                        "rot": {"roll": round(roll, 2), "pitch": round(pitch, 2), "yaw": round(yaw, 2)}, "hfov": round(hfov, 2)})
    return out


def validate_ending(say=print) -> int:
    """The offline gate for the ending sequences (CIN_15/18/19/24): framing at every key (strict), the stop-point
    window (clearance, framing and lines of sight from every stop), and terrain at the nominal stop. CIN_23 (optional,
    MarkCine) is reported but does not gate."""
    rc = 0
    for cin in ENDING + ENDING_OPTIONAL:
        a = check(cin, strict=True, quiet=True)
        plan = PLANS[cin]()
        w = window_check(cin, quiet=True)
        b = terrain_check(cin, quiet=True)
        win = "-" if not plan.get("window_m") else (
            f"{'ok' if w == 0 else 'FAIL'} ({len(window_stops(plan))} stops {window_stops(plan)[0]:.0f}-{window_stops(plan)[-1]:.0f} m)")
        opt = cin in ENDING_OPTIONAL
        say(f"{cin:22s} framing {'ok' if a == 0 else 'FAIL'}   window {win}   terrain "
            f"{'ok' if b == 0 else ('skipped (no heightmap)' if b == 2 else 'FAIL')}{'   (optional: not gating)' if opt else ''}")
        if not opt:
            rc |= a | w | (b & 1)
    say(f"origin z: {ORIGIN_Z}" + ("  (the runner before RoadCineOrigin: binaries built before 2026-09-28's ENDING-PREP)" if ORIGIN_Z == "spline" else
                                 "  (FSaskartaEventLogic::RoadCineOrigin: needs the SaskartaCore build with it)"))
    say("note: " + probe_ending()["note"][:60])
    return rc


def main():
    global ORIGIN_Z
    cmds = ("plan", "emit", "check", "terrain", "frames", "credits", "probe-ending", "merge-probe", "validate-ending")
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    if "--origin=spline" in flags:
        ORIGIN_Z = "spline"
    if not args or args[0] not in cmds or (args[0] in ("plan", "emit", "check", "terrain", "frames", "merge-probe") and len(args) < 2):
        print(__doc__)
        return 2
    cmd = args[0]
    if cmd == "credits":
        lines = credits_roll()
        text = "\n".join(lines) + "\n"
        if len(args) > 1:
            Path(args[1]).write_text(text, encoding="utf-8")
            print("wrote", args[1])
        else:
            sys.stdout.buffer.write(text.encode("utf-8"))
        print(f"{len(lines)} lines -> roll {roll_seconds()} s at {ROLL_S_PER_LINE} s/line; CIN_25 duration {plan_cin25()['duration']} s")
        return 0
    if cmd == "probe-ending":
        emit_probe_ending(Path(args[1]) if len(args) > 1 else Path("probe_ending_chunk.py"))
        return 0
    if cmd == "merge-probe":
        import datetime
        pe = merge_probe(Path(args[1]).read_text(encoding="utf-8", errors="replace"), datetime.date.today().isoformat())
        PROBE_ENDING_FILE.write_text(json.dumps(pe, indent=2) + "\n", encoding="utf-8")
        print("merged into", PROBE_ENDING_FILE.name, "-", pe["note"])
        return 0
    if cmd == "validate-ending":
        return validate_ending()
    if cmd == "emit" and ORIGIN_Z != "feet":
        print("refusing to emit with --origin=spline: the sequences are keyed for the runner's feet origin")
        return 2
    cin = args[1]
    if cmd == "check":
        return check(cin, strict="--strict" in flags, window="--window" in flags)
    if cmd == "terrain":
        return terrain_check(cin)
    if cmd == "frames":
        print(json.dumps(frames_report(cin), indent=1))
        return 0
    if cmd == "plan":
        plan = PLANS[cin]()
        if plan.get("timeline"):
            print(cin, plan["asset"], "with UMG overlay", plan["widget"], f"{plan['duration']} s")
            for t, what in plan["timeline"]:
                print("   t=%5.1f  %s" % (t, what))
        else:
            print(cin, plan["asset"], f"{plan['duration']} s", "frame", plan.get("frame", "-"),
                  f"road m {plan['road_m']}" if plan.get("road_m") else "", f"blend_out {plan['blend_out']} s")
        fr = road_frame(plan["road_m"]) if plan.get("frame") == "local" else None
        if fr:
            g = ground_z(fr["x"], fr["y"])
            print("   origin (%.0f, %.0f, %.0f) yaw %.1f (z = %s); the ground is %s" % (fr["x"], fr["y"], fr["z"], fr["yaw"], ORIGIN_Z,
                  "missing (heightmap not found: the origin falls back to the spline z)" if g is None
                  else "%+.0f cm vs the spline" % (g - fr["spline_z"])))
            if plan.get("window_m"):
                st = window_stops(plan)
                print("   stop window %.0f-%.0f m (`check --window`)" % (st[0], st[-1]))
        for c in plan["cams"]:
            print(c["name"], round(c["focal"], 1), "mm")
            for k in c["keys"]:
                line = "   t=%.1f loc=(%.0f, %.0f, %.0f) roll %.1f pitch %.1f yaw %.1f %s" % (k[0], k[1], k[2], k[3], k[4], k[5], k[6], k[7])
                if fr:  # the world pose for render_camera (frame from probe_ending.json or the spline polyline)
                    w = world_pose(plan, k)
                    line += "   world (%.0f, %.0f, %.0f) yaw %.1f" % (w[0], w[1], w[2], w[5])
                print(line)
        for sec in cut_sections(plan):
            print("   cut %5.1f-%5.1f %s%s" % (sec[0], sec[1], sec[2], f" (blend in {sec[3]} s)" if sec[3] else ""))
        if plan.get("fade"):
            print("   fade", plan["fade"]["color"], [(t, v) for t, v, _ in plan["fade"]["keys"]])
        return 0
    return emit(cin, Path(args[2]))


if __name__ == "__main__":
    sys.exit(main())
