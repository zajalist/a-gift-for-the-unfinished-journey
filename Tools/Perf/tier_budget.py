"""Editor-world frame budget at fixed poses (task PERF2 addendum, LANE3). Never starts PIE.

    python Tools/Perf/tier_budget.py measure --pose title|road:<m> [--tier high|medium] [--settle-s 6] [--csv-s 5]
    python Tools/Perf/tier_budget.py summarize <csv>

"measure" puts the active level viewport on the pose (the title camera at t=20 s of LS_Saskarta_Title, or
the road at <m> metres, eye height 170 cm, looking down the road heading from docs/story/road-profile.json),
optionally applies a tier from the console (scalability N plus the PERF-AUTO tier CVars, restored after),
settles, runs `CsvProfile Start` for --csv-s seconds and one `ProfileGPU`, restores the camera and prints
the CSV path plus a summary (game / render / GPU ms, draw calls, primitives, RT pool). The editor's
background throttle must already be off (unreal_editor set_cpu_throttle_override); this tool does not
touch it. Every editor call goes through Tools/Look/apply_look.python_run, which refuses while PIE runs.

Editor-world numbers include the editor's own viewport overhead; compare runs with each other, and treat
the render thread as an upper bound for the game.
"""
import argparse
import csv
import glob
import json
import os
import pathlib
import statistics
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "Tools" / "Look"))
CSV_DIR = ROOT / "Saved" / "Profiling" / "CSV"

TIERS = {  # scalability level + the PERF2 brief section 2 CVars
    "medium": (1, [("r.Shadow.Virtual.ResolutionLodBiasDirectional", "1"), ("r.Nanite.MaxPixelsPerEdge", "2"),
                   ("r.Lumen.HardwareRayTracing", "0"), ("grass.DensityScale", "0.6"), ("grass.CullDistanceScale", "0.75"),
                   ("r.VolumetricCloud", "0")]),
    "high": (2, [("r.Shadow.Virtual.ResolutionLodBiasDirectional", "0"), ("r.Nanite.MaxPixelsPerEdge", "1.5"),
                 ("r.Lumen.HardwareRayTracing", "1"), ("grass.DensityScale", "0.9"), ("grass.CullDistanceScale", "1.0"),
                 ("r.VolumetricCloud", "1")]),
}

PREP = """
import unreal
ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
info = ues.get_level_viewport_camera_info()
if info:
    l, r = info[0], info[1]
    print('CAM', l.x, l.y, l.z, r.pitch, r.yaw, r.roll)
ues.set_level_viewport_camera_info(unreal.Vector(__X__, __Y__, __Z__), unreal.Rotator(roll=0.0, pitch=__P__, yaw=__YAW__))
print('SG', unreal.SystemLibrary.get_console_variable_int_value('sg.ShadowQuality'))
for n, v in [__CVARS__]:
    print('CVAR', n, str(unreal.SystemLibrary.get_console_variable_float_value(n)))
for c in [__CMDS__]:
    unreal.SystemLibrary.execute_console_command(None, c)
unreal.SystemLibrary.execute_console_command(None, 'r.ProfileGPU.ShowUI 0')
print('prepared')
"""
CMD = """
import unreal
unreal.SystemLibrary.execute_console_command(None, '__C__')
print('ok')
"""
RESTORE = """
import unreal
ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
__CAMLINE__
for c in [__CMDS__]:
    unreal.SystemLibrary.execute_console_command(None, c)
print('restored')
"""


def sub(text, **kw):
    for k, v in kw.items():
        text = text.replace(f"__{k}__", str(v))
    return text


def pose(spec):
    if spec == "title":
        import build_title_sequence as bts
        pos, (pitch, yaw) = bts.pose_at(20.0)
        return pos[0], pos[1], pos[2], pitch, yaw
    m = float(spec.split(":", 1)[1])
    samples = json.loads((ROOT / "docs" / "story" / "road-profile.json").read_text(encoding="utf-8"))["samples"]
    s = min(samples, key=lambda x: abs(x["dist_m"] - m))
    return s["x_cm"], s["y_cm"], s["spline_z_m"] * 100.0 + 170.0, -2.0, s["heading_ue_yaw"]


def summarize(path):
    with open(path, encoding="utf-8", errors="ignore") as f:
        r = csv.reader(f)
        hdr = next(r)
        rows = [row for row in r if len(row) >= len(hdr) and row[1].replace(".", "", 1).isdigit()]
    idx = {h: i for i, h in enumerate(hdr)}

    def col(k):
        out = []
        for row in rows:
            try:
                out.append(float(row[idx[k]]))
            except (KeyError, ValueError):
                pass
        return out

    res = {"frames": len(rows)}
    for k in ("FrameTime", "GameThreadTime", "RenderThreadTime", "GPUTime", "RHI/DrawCalls", "RHI/PrimitivesDrawn",
              "RenderTargetPoolSize", "Exclusive/GameThread/UI", "GPUMem/LocalUsedMB"):
        v = col(k)
        if v:
            res[k] = round(statistics.median(v), 2)
    return res


def measure(pose_spec, tier, settle_s, csv_s):
    from apply_look import python_run, check_banned

    def run(script):
        ok, out, err = python_run(check_banned(script))
        if not ok:
            raise SystemExit(f"python_run failed: {err}")
        return out

    x, y, z, p, yaw = pose(pose_spec)
    cmds, cvars = [], []
    if tier:
        level, cv = TIERS[tier]
        cmds = [f"scalability {level}"] + [f"{n} {v}" for n, v in cv]
        cvars = cv
    before = set(glob.glob(str(CSV_DIR / "*.csv")))
    out = run(sub(PREP, X=x, Y=y, Z=z, P=p, YAW=yaw, CVARS=", ".join(f"({n!r}, {v!r})" for n, v in cvars),
                  CMDS=", ".join(repr(c) for c in cmds)))
    cam, sg, old = None, None, []
    for line in out.splitlines():
        if line.startswith("CAM"):
            cam = [float(v) for v in line.split()[1:]]
        elif line.startswith("SG"):
            sg = line.split()[1]
        elif line.startswith("CVAR"):
            _, n, v = line.split()
            old.append((n, v))
    try:
        time.sleep(settle_s)
        run(sub(CMD, C="CsvProfile Start"))
        time.sleep(csv_s)
        run(sub(CMD, C="CsvProfile Stop"))
        time.sleep(1.0)
        run(sub(CMD, C="ProfileGPU"))
        time.sleep(2.0)
    finally:
        camline = "" if cam is None else (
            f"ues.set_level_viewport_camera_info(unreal.Vector({cam[0]}, {cam[1]}, {cam[2]}), "
            f"unreal.Rotator(roll={cam[5]}, pitch={cam[3]}, yaw={cam[4]}))")
        back = ([f"scalability {sg}"] if tier and sg is not None else []) + [f"{n} {v}" for n, v in old]
        run(sub(RESTORE, CAMLINE=camline, CMDS=", ".join(repr(c) for c in back)))
    time.sleep(2.0)
    new = sorted(set(glob.glob(str(CSV_DIR / "*.csv"))) - before, key=os.path.getmtime)
    rep = {"pose": pose_spec, "tier": tier or "current", "xyz_pitch_yaw": [x, y, z, p, yaw]}
    if new:
        rep["csv"] = new[-1]
        rep.update(summarize(new[-1]))
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("step", choices=["measure", "summarize"])
    ap.add_argument("path", nargs="?")
    ap.add_argument("--pose", default="title")
    ap.add_argument("--tier", choices=["high", "medium"], default=None)
    ap.add_argument("--settle-s", type=float, default=6.0)
    ap.add_argument("--csv-s", type=float, default=5.0)
    a = ap.parse_args(argv)
    if a.step == "summarize":
        print(json.dumps(summarize(a.path), indent=1))
    else:
        print(json.dumps(measure(a.pose, a.tier, a.settle_s, a.csv_s), indent=1))


if __name__ == "__main__":
    main()
