"""Drone-feed camera alternatives for CIN_15 and CIN_18, preserving source cues.

    python Tools/Drone/later_cinematics.py check
    python Tools/Drone/later_cinematics.py emit

This overlays the existing camera plans in memory; it never edits the common
cinematics builder or story sources. CIN_19 and CIN_24 are deliberately excluded.
"""
import argparse
import copy
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Tools/Cinematics"))
import build_cinematics as cine  # noqa: E402

NAMES = ("CIN_15_IN_RANGE", "CIN_18_COLLAPSE")
OUT = ROOT / "Saved/Drone/LaterCinematics"
DRONE_FOCAL = cine.focal_for_hfov(75.0)


def _key(t, pos, target, mode="cubic"):
    pitch, yaw = cine.look_at(pos, target)
    return (t, *pos, 0.0, pitch, yaw, mode)


def plan_cin15(road_m=None):
    base = copy.deepcopy(cine.plan_cin15(road_m))
    fr = cine.road_frame(base["road_m"])
    pe = cine.probe_ending()
    carrier = (0.0, 0.0, cine.ground_local(fr) + 100.0)
    crown = cine.to_local(fr, pe["mast_crown"])
    # A crane from the relay eye, rising past the carrier toward the mast.
    # Every position stays within 12 m of the carrier and the nominal follow
    # view is (-650,+60,+250) cm. No stepped carrier-POV zoom or scan HUD.
    path = [(-650.0, 60.0, 250.0), (-600.0, 60.0, 320.0),
            (-520.0, 80.0, 520.0), (-420.0, 80.0, 850.0)]
    crane = cine._cam("CIN15_S1_DroneCrane", 24.0,
                      [_key(0.0, path[0], carrier), _key(1.2, path[1], carrier),
                       _key(2.4, path[2], crown), _key(5.0, path[3], crown)],
                      {"carrier": carrier, "crown": crown}, ("carrier", "crown"),
                      only_at={"carrier": (0.0, 1.2), "crown": (2.4, 5.0)}, rides=True)
    eye = (-650.0, 60.0, 250.0)
    last = cine._cam("CIN15_S3_DroneRelay", DRONE_FOCAL,
                     [_key(8.0, eye, crown, "constant"),
                      _key(10.0, eye, crown, "constant")],
                     {"crown": crown}, ("crown",), rides=True)
    # Sensor-camera correction supplies the physical live eye at playback.
    # Store only displacement from the old relay anchor, so the nominal
    # (-650,+60,+250) position is not added a second time by the road frame.
    for camera in (crane, last):
        camera["keys"] = [(key[0], *(key[axis + 1] - eye[axis] for axis in range(3)), *key[4:])
                          for key in camera["keys"]]
        camera["sensor_eye_cm"] = 0.0
    base["cams"] = [crane, base["cams"][4], last]
    base["shots"] = [(0.0, 5.0, crane["name"]),
                     (5.0, 8.0, base["cams"][1]["name"]),
                     (8.0, 10.0, last["name"])]
    base["note"] = "Shot 1 cranes from the drone, shot 2 remains EXT, shot 3 returns to the relay eye. Voice/radio timing unchanged."
    return base


def plan_cin18(road_m=None):
    base = copy.deepcopy(cine.plan_cin18(road_m))
    fr = cine.road_frame(base["road_m"])
    carrier = (0.0, 0.0, cine.ground_local(fr) + 90.0)
    # Two relay shots show the carrier lurching below; the native breach glitch
    # and CRT dropout own the feed treatment. Exterior shutdown at 3.5 s and
    # the log/black interval at 9–28 s remain exactly as authored.
    a = cine._cam("CIN18_S1_DroneLurch", DRONE_FOCAL,
                  [_key(0.0, (-650.0, 60.0, 250.0), carrier),
                   _key(0.6, (-660.0, 72.0, 235.0), carrier),
                   _key(1.5, (-655.0, 68.0, 225.0), carrier)],
                  {"carrier": carrier}, ("carrier",), rides=True)
    b = cine._cam("CIN18_S2_DroneDropout", DRONE_FOCAL,
                  [_key(1.5, (-655.0, 68.0, 225.0), carrier),
                   _key(2.0, (-665.0, 75.0, 220.0), carrier),
                   _key(3.5, (-665.0, 75.0, 220.0), carrier, "constant")],
                  {"carrier": carrier}, ("carrier",), rides=True)
    exterior = base["cams"][1]
    base["cams"] = [a, b, exterior]
    base["shots"] = [(0.0, 1.5, a["name"]), (1.5, 3.5, b["name"]),
                     (3.5, 28.0, exterior["name"])]
    return base


def register():
    cine.PLANS.update({NAMES[0]: plan_cin15, NAMES[1]: plan_cin18})


def check():
    register()
    result = 0
    for name in NAMES:
        plan = cine.PLANS[name]()
        strict = cine.check(name, strict=True, quiet=True)
        terrain = cine.terrain_check(name, quiet=True)
        window = cine.window_check(name, quiet=True)
        print(name, "framing", "ok" if strict == 0 else "FAIL",
              "terrain", "ok" if terrain == 0 else "FAIL",
              "stop window", "ok" if window == 0 else "FAIL")
        # A missing heightmap returns 2. That is a failed terrain gate here,
        # rather than permission to emit shots without a clearance check.
        result |= strict | terrain | window
        if plan["duration"] != (10.0 if name == NAMES[0] else 28.0):
            result |= 1
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("step", choices=("check", "emit"))
    args = ap.parse_args()
    result = check()
    if result or args.step == "check":
        return result
    for name in NAMES:
        result |= cine.emit(name, OUT / name)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
