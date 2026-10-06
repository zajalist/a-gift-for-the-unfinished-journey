"""Sky + fog + clouds GPU cost from the title camera's view, measured with ProfileGPU (task SKY).

    python Tools/Look/gpu_budget.py measure [--samples 3] [--t 20] [--settle-s 6] [--cvar NAME=VALUE ...]
    python Tools/Look/gpu_budget.py parse <log> [--from-line N]

"measure" puts the active level viewport on TitleCam's sequence pose (build_title_sequence.pose_at),
turns off the editor's background CPU throttle ("Use Less CPU when in Background") so the viewport
keeps rendering while the editor window is not focused (the reason the first attempt profiled only
Slate), lets the clouds and temporal history settle, then runs ProfileGPU --samples times and
reads each dump from Saved/Logs/saskartarad.log. The settings class is not exposed to Python and
the 'set' console command is refused in the editor, so the throttle is set on the class default
object by its C++ property name. --cvar values (for example a preset's volumetric fog grid) apply
to the measurement only. The viewport camera, the throttle and the cvars are restored afterwards.
It never starts PIE. Wrap it in Tools/GameFlow/editor_gate.py acquire/release.

The editor viewport renders at its own size with TSR (for example 1127x835 -> 1183x876, about
0.94 MP). That is close to the game's internal resolution at 1080p with r.ScreenPercentage 66.7
(1280x720, 0.92 MP); the JSON reports the resolution so the numbers can be scaled.

"parse" only reads a log. Both print JSON: per-sample milliseconds for each category, the frame
time, and the render resolution found in the pass names.

Categories (the top-most matching event is counted once; its children are not re-counted):
  clouds    VolumetricCloud and the volumetric render target reconstruct/compose passes
  fog       ExponentialHeightFog and VolumetricFog
  sky       SkyAtmosphere (its LUTs and the sky pass)
  skylight  the real-time SkyLight capture (re-renders sky + clouds into a cubemap); reported
            apart because the brief's budget names sky, fog and clouds, and it is shown both ways
"""
import argparse
import json
import pathlib
import re
import statistics
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
LOG = ROOT / "Saved" / "Logs" / "saskartarad.log"
BUDGET_MS = 1.0

CATEGORIES = (
    ("skylight", re.compile(r"skylight|captureconvolve|realtimecapture|reflectioncapture", re.I)),
    ("clouds", re.compile(r"cloud|volumetricrendertarget|volumetricrt", re.I)),
    ("fog", re.compile(r"fog", re.I)),
    ("sky", re.compile(r"skyatmosphere|skyview|sky ?lut|aerialperspective|multiscatter|transmittancelut", re.I)),
)
PIPE_RE = re.compile(r"(Graphics|Compute|Copy) pipeline")
FRAME_TIME_RE = re.compile(r"- Frame Time\s*:\s*([\d.]+)\s*ms")
RES_RE = re.compile(r"(\d{3,5})x(\d{3,5})")
SCENE_RE = re.compile(r"basepass|prepass|lights|postprocessing|lumen|nanite", re.I)


# ----------------------------------------------------------------------------- parsing (pure)

def parse_row(line):
    """(depth, name, inclusive_ms) for one ProfileGPU table row, or None."""
    if "┃" not in line:
        return None
    parts = line.split("┃")
    if len(parts) < 5:
        return None
    incl, raw = parts[2], parts[3]
    m = re.search(r"([\d.]+) ms\s*$", incl.strip())
    if not m or not raw.strip():
        return None
    name = raw.rstrip()
    depth = len(name) - len(name.lstrip(" "))
    return depth, name.strip(), float(m.group(1))


def categorize(name):
    for cat, rx in CATEGORIES:
        if rx.search(name):
            return cat
    return None


def split_dumps(lines):
    """Group the log lines into ProfileGPU dumps: a dump starts at 'r.ProfileGPU' / first table
    after a gap and holds (pipeline, rows) tables plus the graphics frame time."""
    dumps, cur, pipe = [], None, None
    for line in lines:
        if "LogRHI: Display:" not in line:
            continue
        pm = PIPE_RE.search(line)
        if pm:
            pipe = pm.group(1)
            if cur is None or (pipe == "Copy" and cur["rows"]):
                cur = {"rows": [], "frame_ms": None}
                dumps.append(cur)
            continue
        fm = FRAME_TIME_RE.search(line)
        if fm and cur is not None and pipe == "Graphics":
            cur["frame_ms"] = float(fm.group(1))
            continue
        row = parse_row(line)
        if row and cur is not None and pipe in ("Graphics", "Compute"):
            cur["rows"].append((pipe,) + row)
    return dumps


def summarize(rows):
    """Milliseconds per category, counting each top-most matching event once."""
    out = {cat: 0.0 for cat, _ in CATEGORIES}
    events = {cat: [] for cat, _ in CATEGORIES}
    res = {}
    matched_depth = None
    scene = False
    for pipe, depth, name, ms in rows:
        scene = scene or (pipe == "Graphics" and ms >= 0.05 and bool(SCENE_RE.search(name)))
        for w, h in RES_RE.findall(name):
            res[(int(w), int(h))] = res.get((int(w), int(h)), 0) + 1
        if matched_depth is not None and depth > matched_depth:
            continue  # inside an already counted event
        matched_depth = None
        cat = categorize(name)
        if cat:
            out[cat] += ms
            events[cat].append(f"{pipe[0]}:{name} {ms:.3f}")
            matched_depth = depth
    out = {k: round(v, 3) for k, v in out.items()}
    out["sky_fog_clouds"] = round(out["sky"] + out["fog"] + out["clouds"], 3)
    out["with_skylight"] = round(out["sky_fog_clouds"] + out["skylight"], 3)
    return out, events, res, scene


def report(dumps):
    samples = []
    for d in dumps:
        ms, events, res, scene = summarize(d["rows"])
        top_res = max(res, key=res.get) if res else None
        samples.append({"frame_ms": d["frame_ms"], "scene_rendered": scene, "ms": ms,
                        "events": events,
                        "resolution": f"{top_res[0]}x{top_res[1]}" if top_res else None})
    samples = [s for s in samples if s["scene_rendered"]] or samples
    rendered = bool(samples) and samples[0]["scene_rendered"]
    agg = {}
    if rendered:
        for key in samples[0]["ms"]:
            agg[key] = round(statistics.median(s["ms"][key] for s in samples), 3)
    # No scene passes in the dump means the level viewport did not render (a Slate-only frame):
    # no verdict rather than a false "0 ms, within budget".
    return {"samples": samples, "scene_rendered": rendered, "median_ms": agg, "budget_ms": BUDGET_MS,
            "within_budget": (agg["sky_fog_clouds"] <= BUDGET_MS) if agg else None}


def read_lines(path, from_line=0):
    with pathlib.Path(path).open(encoding="utf-8", errors="replace") as f:
        return f.readlines()[from_line:]


# ----------------------------------------------------------------------------- editor side

PREP = """
import unreal
ps = unreal.get_default_object(unreal.load_class(None, '/Script/UnrealEd.EditorPerformanceSettings'))
print('THROTTLE', str(ps.get_editor_property('bThrottleCPUWhenNotForeground')))
ps.set_editor_property('bThrottleCPUWhenNotForeground', False)
ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
info = ues.get_level_viewport_camera_info()
if info:
    l, r = info[0], info[1]
    print('CAM', l.x, l.y, l.z, r.pitch, r.yaw, r.roll)
ues.set_level_viewport_camera_info(unreal.Vector(__X__, __Y__, __Z__), unreal.Rotator(roll=0.0, pitch=__P__, yaw=__YAW__))
for n, v in [__CVARS__]:
    print('CVAR', n, str(unreal.SystemLibrary.get_console_variable_float_value(n)))
    unreal.SystemLibrary.execute_console_command(None, n + ' ' + v)
unreal.SystemLibrary.execute_console_command(None, 'r.ProfileGPU.ShowUI 0')
print('prepared')
"""

PROFILE = """
import unreal
unreal.SystemLibrary.execute_console_command(None, 'ProfileGPU')
print('profiled')
"""

RESTORE = """
import unreal
ps = unreal.get_default_object(unreal.load_class(None, '/Script/UnrealEd.EditorPerformanceSettings'))
ps.set_editor_property('bThrottleCPUWhenNotForeground', __THROTTLE__)
ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
__CAMLINE__
for n, v in [__CVARS__]:
    unreal.SystemLibrary.execute_console_command(None, n + ' ' + v)
print('restored')
"""


def _sub(text, **kw):
    for k, v in kw.items():
        text = text.replace(f"__{k}__", str(v))
    return text


def _cvar_list(pairs):
    return ", ".join(f"({n!r}, {v!r})" for n, v in pairs)


def _num(v):
    f = float(v)
    return str(int(f)) if f == int(f) else repr(f)


def measure(samples=3, t=20.0, settle_s=6.0, log=LOG, cvars=()):
    """cvars: (name, value) pairs set for the measurement only and restored afterwards."""
    sys.path.insert(0, str(HERE))
    import build_title_sequence as bts
    from apply_look import python_run, check_banned

    def run(script):
        ok, out, err = python_run(check_banned(script))
        if not ok:
            raise SystemExit(f"python_run failed: {err}")
        return out

    pos, (pitch, yaw) = bts.pose_at(t)
    start_line = len(read_lines(log))
    out = run(_sub(PREP, X=pos[0], Y=pos[1], Z=pos[2], P=pitch, YAW=yaw, CVARS=_cvar_list(cvars)))
    throttle, cam, old = "True", None, []
    for line in out.splitlines():
        if line.startswith("THROTTLE"):
            throttle = line.split()[1]
        elif line.startswith("CAM"):
            cam = [float(v) for v in line.split()[1:]]
        elif line.startswith("CVAR"):
            _, n, v = line.split()
            old.append((n, _num(v)))
    try:
        time.sleep(settle_s)
        for _ in range(samples):
            run(PROFILE)
            time.sleep(3.0)
    finally:
        camline = "" if cam is None else (
            f"ues.set_level_viewport_camera_info(unreal.Vector({cam[0]}, {cam[1]}, {cam[2]}), "
            f"unreal.Rotator(roll={cam[5]}, pitch={cam[3]}, yaw={cam[4]}))")
        run(_sub(RESTORE, THROTTLE=throttle, CAMLINE=camline, CVARS=_cvar_list(old)))
    time.sleep(1.0)
    rep = report(split_dumps(read_lines(log, start_line)))
    rep.update({"pose_t": t, "pose": [pos[0], pos[1], pos[2], pitch, yaw],
                "log_from_line": start_line, "throttle_was": throttle,
                "cvars": dict(cvars), "cvars_restored": dict(old)})
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("step", choices=["measure", "parse"])
    ap.add_argument("log", nargs="?", default=str(LOG))
    ap.add_argument("--from-line", type=int, default=0)
    ap.add_argument("--samples", type=int, default=3)
    ap.add_argument("--t", type=float, default=20.0)
    ap.add_argument("--settle-s", type=float, default=6.0)
    ap.add_argument("--events", action="store_true", help="keep the matched event names")
    ap.add_argument("--cvar", action="append", default=[], metavar="NAME=VALUE",
                    help="set for the measurement only, restored afterwards (repeatable)")
    a = ap.parse_args(argv)
    if a.step == "measure":
        rep = measure(a.samples, a.t, a.settle_s, cvars=[tuple(c.split("=", 1)) for c in a.cvar])
    else:
        rep = report(split_dumps(read_lines(a.log, a.from_line)))
    if not a.events:
        for s in rep["samples"]:
            s.pop("events")
    print(json.dumps(rep, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
