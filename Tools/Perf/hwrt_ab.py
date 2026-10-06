"""Hardware ray tracing on/off A/B: three fixed visual poses plus the streaming-stall trace (task PERF-URGENT).

    python Tools/Perf/hwrt_ab.py poses                     # print the three poses (no editor call)
    python Tools/Perf/hwrt_ab.py load    <pose>            # load the WP actors in the pose's box (one call)
    python Tools/Perf/hwrt_ab.py capture <pose> <on|off>   # Tools/Look/capture_look.py at the pose -> Saved/HWRT_AB/<pose>_<label>.png
    python Tools/Perf/hwrt_ab.py unload  <pose>            # unload what `load` loaded (one call)
    python Tools/Perf/hwrt_ab.py compose                   # side-by-side PNGs (on | off) for every pose captured both ways
    python Tools/Perf/hwrt_ab.py route-steps               # print the 12 Hayba python_run snippets for the PIE camera route
    python Tools/Perf/hwrt_ab.py stalls <export.csv> <t0> <t1>   # sum the D3D12 stall calls in an Insights timing export

Rules (Tools/Perf/HWRT_AB.md): hold the editor gate, never during PIE (apply_look.python_run refuses),
load / capture / unload as separate calls, one pose at a time (the site's load box from setdress_sites.json: 90-260 m
across, so a handful of landscape proxies, well under the 24-proxy rule). The capture uses capture_look's temporary SceneCapture2D
(Look_TempCapture), which destroys itself after the export; `unload` also removes a leftover one.
"""
import csv
import json
import math
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "Tools" / "Look"))
OUT = ROOT / "Saved" / "HWRT_AB"

# (x, y, eye z world cm, look-at x, y, z). From Tools/World/setdress_sites.json views / placements.
POSES = {
    # the carrier dock at PlayerStart: open daylight, the carrier and the cradle yard
    "spawn": dict(cam=(616579.6, 463550.0, -35506.2), look=(617642.6, 462638.9, -35425.9),
                  box=(613143, 458139, 622143, 467139)),
    # Waiting Water village (S07 orbit_a): houses, market roofs, bounce light between walls
    "waitingwater": dict(cam=(539386.3, 381414.8, -35905.5), look=(544613.7, 374335.7, -36249.3),
                         box=(531614, 361336, 557614, 387336)),
    # S13 Numbered Stop arcade, 8 m in front of the arch row (y 340400-340600) at standing height, looking
    # through the arches: arch shadows, occlusion under the arcade, indirect light on the back wall
    "arcade": dict(cam=(445400.0, 339700.0, -40305.0), look=(445636.0, 340520.0, -40225.0),
                   box=(437656, 331750, 453656, 347750)),
}

LOAD = """
import unreal
x0, y0, x1, y1 = __BOX__
gs = []
for d in unreal.WorldPartitionBlueprintLibrary.get_actor_descs():
    b = d.get_editor_property('bounds')
    if b.min.x < x1 and b.max.x > x0 and b.min.y < y1 and b.max.y > y0 and d.get_editor_property('is_spatially_loaded'):
        gs.append(d.get_editor_property('guid'))
unreal.WorldPartitionBlueprintLibrary.__OP__(gs)
print('__OP__', len(gs))
"""

CLEAN = """
import unreal
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
for a in eas.get_all_level_actors():
    if a.get_actor_label() == 'Look_TempCapture':
        eas.destroy_actor(a)
        print('removed a leftover Look_TempCapture')
"""

ROUTE = [(308297, 457935, 11167, -92), (320079, 439154, 9709, -90), (334218, 422657, 1569, -7),
         (352205, 413311, -6493, -95), (351416, 397730, -14597, -28), (361013, 382328, -28130, -23),
         (382974, 375050, -33061, 0), (402538, 362247, -37443, -44), (420414, 344626, -40119, -44),
         (442429, 336550, -40571, 0), (463586, 326853, -37589, -43), (485621, 320550, -31826, 0)]

ROUTE_STEP = """import unreal
w = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
cam = unreal.GameplayStatics.get_player_controller(w, 0).get_view_target()
cam.set_actor_location_and_rotation(unreal.Vector(__X__, __Y__, __Z__), unreal.Rotator(roll=0.0, pitch=-5.0, yaw=__YAW__.0), False, True)
print(__I__)"""

STALL_CALLS = ("CreateDescriptorHeap", "CommitReservedResource", "ExecuteCommandLists", "Submission_Wait",
               "CreateCommittedResource", "FinishCompilation")


def yaw_pitch(cam, look):
    dx, dy, dz = (look[i] - cam[i] for i in range(3))
    return math.degrees(math.atan2(dy, dx)), math.degrees(math.atan2(dz, math.hypot(dx, dy)))


def run(script):
    from apply_look import python_run, check_banned
    ok, out, err = python_run(check_banned(script))
    print(out.strip())
    if not ok:
        raise SystemExit(f"python_run failed: {err}")


def capture(pose, label):
    p = POSES[pose]
    yaw, pitch = yaw_pitch(p["cam"], p["look"])
    OUT.mkdir(parents=True, exist_ok=True)
    # capture_look traces the ground under (x, y) and adds --eye; 170 cm is standing height.
    cmd = [sys.executable, str(ROOT / "Tools" / "Look" / "capture_look.py"), "spawn", str(OUT / f"{pose}_{label}.png"),
           "--at", str(p["cam"][0]), str(p["cam"][1]), "--yaw", f"{yaw:.2f}", "--pitch", f"{pitch:.2f}",
           "--eye", "170", "--fov", "70", "--settle-s", "8"]
    print(" ".join(cmd))
    return subprocess.call(cmd)


def compose():
    from PIL import Image  # noqa: WPS433 (offline only)
    for pose in POSES:
        a, b = OUT / f"{pose}_on.png", OUT / f"{pose}_off.png"
        if a.exists() and b.exists():
            ia, ib = Image.open(a), Image.open(b)
            out = Image.new("RGB", (ia.width + ib.width, max(ia.height, ib.height)))
            out.paste(ia, (0, 0))
            out.paste(ib, (ia.width, 0))
            out.save(OUT / f"{pose}_on_vs_off.png")
            print("wrote", OUT / f"{pose}_on_vs_off.png")


def stalls(path, t0, t1):
    tot = {}
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        for x in csv.DictReader(f):
            s = float(x["StartTime"])
            if not (t0 <= s <= t1) or x["Duration"] == "inf":
                continue
            for k in STALL_CALLS:
                if k in x["TimerName"]:
                    tot[k] = tot.get(k, 0.0) + float(x["Duration"])
    print(json.dumps({k: round(v, 2) for k, v in sorted(tot.items(), key=lambda kv: -kv[1])}, indent=1))


def main(argv):
    if not argv or argv[0] == "poses":
        for n, p in POSES.items():
            yaw, pitch = yaw_pitch(p["cam"], p["look"])
            print(n, p["cam"], f"yaw {yaw:.1f} pitch {pitch:.1f}", "box", p["box"])
        return 0
    step = argv[0]
    if step in ("load", "unload"):
        p = POSES[argv[1]]
        run(LOAD.replace("__BOX__", repr(p["box"])).replace("__OP__", "load_actors" if step == "load" else "unload_actors"))
        if step == "unload":
            run(CLEAN)
        return 0
    if step == "capture":
        return capture(argv[1], argv[2])
    if step == "compose":
        compose()
        return 0
    if step == "route-steps":
        for i, (x, y, z, yaw) in enumerate(ROUTE):
            print(f"# step {i}")
            print(ROUTE_STEP.replace("__X__", str(x)).replace("__Y__", str(y)).replace("__Z__", str(z + 300))
                  .replace("__YAW__", str(yaw)).replace("__I__", str(i)))
        return 0
    if step == "stalls":
        stalls(argv[1], float(argv[2]), float(argv[3]))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
