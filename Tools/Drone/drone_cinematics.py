"""Carrier-POV optics failure and the drone arrival, both staged natively.

    python Tools/Drone/drone_cinematics.py check
    python Tools/Drone/drone_cinematics.py emit
    python Tools/Drone/drone_cinematics.py ground     # the fall against the heightmap, 3,450-3,950 m

SaskartaDroneSequence stages the fall (a traced tip-over, impact, torn signal) and the
arrival (heard, dot clusters, lights, rise and sweep, sides, feed boot) in the carrier's
own view; these sequences carry only duration and fades. The event runner owns mode handoff.
"""
import argparse
import math
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Tools/Cinematics"))
import build_cinematics as cine  # noqa: E402

OUT = ROOT / "Saved/Drone/Cinematics"
NAMES = ("CIN_A1_OPTICS_FAIL", "CIN_B1_DRONE")
DURATIONS = {"CIN_A1_OPTICS_FAIL": 9.0, "CIN_B1_DRONE": 14.0}
# Mirrors SaskartaDroneSequence.cpp: the settled fall lens (carrier-local offset from the eye).
FALL_LENS_SETTLED = (38.0, -71.0, -98.0)
FALL_IMPACT_S = 1.45
ARRIVAL_BOOT_S = 12.05


def _z(frame, x, y, rise):
    return cine.ground_local(frame, x, y) + rise


def _aim(cam, target):
    return cine.look_at(cam, target)


def _key(t, camera, target, mode="cubic"):
    pitch, yaw = _aim(camera, target)
    return (t, *camera, 0.0, pitch, yaw, mode)


def plan_a1():
    """3700 m: the native fall owns the possessed carrier's actual view.

    0.40 knee gives, 1.45 impact (snap, bounce, lens dust), 2.30-2.40 three torn frames and
    OPTICS FAULT, black; aux vision at 5.0 and the first slow ping 1.8 s later.
    """
    return {"asset": "LS_CIN_A1_OpticsFail", "frame": "local", "road_m": 3700.0,
            "duration": DURATIONS["CIN_A1_OPTICS_FAIL"], "blend_out": 0.0, "cams": [], "shots": [],
            "fade": {"color": (0.0, 0.0, 0.0), "keys":
                     [(0.0, 0.0, "constant"), (2.30, 0.0, "constant"),
                      (2.33, 0.55, "constant"), (2.36, 0.1, "constant"),
                      (2.40, 1.0, "constant"), (4.9, 1.0, "constant"),
                      (5.2, 0.0, "linear")]}}


def plan_b1():
    """3770 m, 14 s, the carrier keeps driving. No sequence cameras: the carrier's point cloud
    hears the rotors, shows two dot clusters and two lights, the drones rise and one sweeps its
    light over the carrier, they take their sides, and the feed boots from drone 0 (FEED 1)."""
    return {"asset": "LS_CIN_B1_Drone", "frame": "local", "road_m": 3770.0,
            "duration": DURATIONS["CIN_B1_DRONE"], "blend_out": 0.0, "cams": [], "shots": [],
            "fade": {"color": (0.0, 0.0, 0.0), "keys":
                     [(0.0, 0.0, "constant"), (11.95, 0.0, "constant"),
                      (11.98, 1.0, "constant"), (12.10, 1.0, "constant"),
                      (12.14, 0.4, "constant"), (12.18, 1.0, "constant"),
                      (12.30, 0.0, "linear")]}}


def fall_ground(road_m: float = 3700.0) -> dict | None:
    """Heightmap check of the fall at `road_m`: lens clearance over the dirt when settled, and how
    far the ground on the falling (left) side rises; the runtime trace lifts the body by that much."""
    if cine.terrain() is None:
        return None
    frame = cine.road_frame(road_m)
    eye = cine._eye_z()
    lx, ly, lz = FALL_LENS_SETTLED
    lens = eye + lz - cine.ground_local(frame, lx, ly)
    left = [cine.ground_local(frame, x, y) for x in (-60.0, 0.0, 60.0) for y in (-60.0, -100.0, -150.0)]
    return {"road_m": road_m, "lens_clearance_cm": round(lens, 1),
            "left_rise_cm": round(max(left), 1), "left_drop_cm": round(min(left), 1)}


def register():
    cine.PLANS.update({NAMES[0]: plan_a1, NAMES[1]: plan_b1})


def validate():
    register()
    result = 0
    for name in NAMES:
        plan = cine.PLANS[name]()
        assert plan["duration"] == DURATIONS[name] and plan["frame"] == "local"
        assert all(0 <= k[0] <= plan["duration"] for k in plan["fade"]["keys"])
        framing = cine.check(name, strict=True, quiet=True)
        ground = cine.terrain_check(name, quiet=True)
        print(name, "framing", "ok" if framing == 0 else "FAIL",
              "terrain", "ok" if ground == 0 else "missing heightmap" if ground == 2 else "FAIL")
        result |= framing | (ground & 1)
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("step", choices=("check", "emit", "plan", "ground"))
    args = ap.parse_args()
    register()
    if args.step == "check":
        return validate()
    if args.step == "ground":
        for m in range(3450, 3951, 50):
            print(fall_ground(float(m)) or "missing heightmap")
        return 0
    if args.step == "plan":
        for name in NAMES:
            plan = cine.PLANS[name]()
            print(name, plan["asset"], "road", plan["road_m"])
            for c in plan["cams"]:
                print("  ", c["name"], "keys", len(c["keys"]), "focal", round(c["focal"], 2))
        return 0
    result = validate()
    if result:
        return result
    for name in NAMES:
        # Both scenes used to own camera actors/cuts. Remove obsolete emitted chunks so the
        # installer leaves the native carrier/drone views in control.
        if True:
            folder = OUT / name
            if folder.is_dir():
                for stale in folder.glob("10_cam_*.py"):
                    stale.unlink()
                cuts = folder / "80_cuts.py"
                if cuts.exists():
                    cuts.unlink()
        result |= cine.emit(name, OUT / name)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
