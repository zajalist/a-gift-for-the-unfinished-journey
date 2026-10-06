"""Generate PCG_Ecology_Trees region by region (world sprint, Task V5 redo, ruling R39).

    python Tools/Foliage/generate_tree_regions.py run [--max N] [--minutes M] [ix,iy ...]
    python Tools/Foliage/generate_tree_regions.py status

A region is a 2 x 2 block of landscape streaming proxies (1020 m x 1020 m), 8 x 8 regions
over the 8.16 km map. Each region gets its own partitioned PCG volume
`PCG_Ecology_Trees_R<ix>_<iy>` (graph PCG_Ecology_Trees, On Demand, 256 m partition cells)
in the outliner folder PCG/Ecology Trees. Per region, as separate python_run calls
(the wp-scripted-load-save-unload memory):

  1. memory gate: system commit must be <= 80 % (else wait, then stop);
  2. load the 4 proxies centred in the region and the PCG partition actors over it;
  3. create or update the region volume;
  4. generate (generate_local), then poll until the instance count is stable;
  5. save the volume and the partition actors that carry its local components (chunks of 20);
  6. unload the proxies and partition actors.

Hold the editor gate (Tools/GameFlow/editor_gate.py) as the owner given by --owner: the driver
renews it before each region and releases/re-acquires it every --hold-min minutes so other
lanes get a turn. Progress is appended to Tools/Foliage/tree_regions_done.json.
Never starts PIE, never builds HLODs, never saves the level or anything outside the region.
"""
import argparse
import json
import pathlib
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import check_pcg_culls  # noqa: E402
sys.path.insert(0, str(ROOT / "Tools" / "GameFlow"))
from editor_gate import pie_running  # noqa: E402

DONE = HERE / "tree_regions_done.json"
GATE = [sys.executable, str(ROOT / "Tools" / "GameFlow" / "editor_gate.py")]
X0, Y0, P = -18920.4, 50.0, 51000.0      # proxy grid: origin and size (cm), 16 x 16 proxies
GRAPH = "/Game/SaskartaGaea/PCG/PCG_Ecology_Trees"
ROAD_REGIONS = [(5, 3), (6, 4)]           # road_1050 and road_200 first

HEAD = """
import unreal
REGION = [0, 0]
X0 = -18920.4
Y0 = 50.0
P = 51000.0
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
wpl = unreal.WorldPartitionBlueprintLibrary
label = 'PCG_Ecology_Trees_R' + str(REGION[0]) + '_' + str(REGION[1])
x0 = X0 + 2 * REGION[0] * P
y0 = Y0 + 2 * REGION[1] * P
"""

LOAD = HEAD + """
MODE = 'load'
box = unreal.Box(unreal.Vector(x0 + 10.0, y0 + 10.0, -1.0e6), unreal.Vector(x0 + 2 * P - 10.0, y0 + 2 * P - 10.0, 1.0e6))
guids = []
counts = {}
raw = wpl.get_intersecting_actor_descs(box)
descs = raw[1] if isinstance(raw, tuple) else raw
region_volumes = [d for d in descs if d.native_class is not None and d.native_class.get_name() == 'PCGVolume' and str(d.label) == label]
if len(region_volumes) > 1:
    raise RuntimeError('Duplicate saved PCG region volumes; resolve exact provenance before regeneration: ' + label)
for d in descs:
    c = d.native_class.get_name() if d.native_class is not None else ''
    b = d.bounds
    cx = (b.min.x + b.max.x) * 0.5
    cy = (b.min.y + b.max.y) * 0.5
    inside = cx > x0 and cx < x0 + 2 * P and cy > y0 and cy < y0 + 2 * P
    if c == 'LandscapeStreamingProxy' and not inside:
        continue
    if c in ['LandscapeStreamingProxy', 'PCGPartitionActor'] or (c == 'PCGVolume' and str(d.label) == label):
        guids.append(d.guid)
        counts[c] = counts.get(c, 0) + 1
if MODE == 'load':
    wpl.load_actors(guids)
if MODE == 'unload':
    wpl.unload_actors(guids)
print('RESULT ' + MODE + ' ' + str(counts.get('LandscapeStreamingProxy', 0)) + ' ' + str(counts.get('PCGPartitionActor', 0)))
"""

SETUP = HEAD + """
box = unreal.Box(unreal.Vector(x0 + 10.0, y0 + 10.0, -1.0e6), unreal.Vector(x0 + 2 * P - 10.0, y0 + 2 * P - 10.0, 1.0e6))
raw = wpl.get_intersecting_actor_descs(box)
descs = raw[1] if isinstance(raw, tuple) else raw
saved = [d for d in descs if d.native_class is not None and d.native_class.get_name() == 'PCGVolume' and str(d.label) == label]
if len(saved) > 1:
    raise RuntimeError('Duplicate saved PCG region volumes; stop before generation: ' + label)
vol = None
resident = [a for a in eas.get_all_level_actors() if a.get_actor_label() == label]
if len(resident) > 1:
    raise RuntimeError('Duplicate loaded PCG region volumes; stop before generation: ' + label)
if resident:
    vol = resident[0]
if saved and (vol is None or vol.get_path_name() != str(saved[0].actor_path)):
    raise RuntimeError('The exact saved region volume must be loaded before setup: ' + label)
cx = x0 + P
cy = y0 + P
if vol is None:
    vol = eas.spawn_actor_from_class(unreal.PCGVolume, unreal.Vector(cx, cy, 0.0))
    vol.set_actor_label(label)
vol.set_actor_location(unreal.Vector(cx, cy, 0.0), False, False)
vol.set_actor_scale3d(unreal.Vector(P / 100.0, P / 100.0, 2000.0))
vol.set_folder_path('PCG/Ecology Trees')
c = vol.get_component_by_class(unreal.PCGComponent)
c.set_graph(unreal.load_asset('__GRAPH__'))
c.set_editor_property('generation_trigger', unreal.PCGComponentGenerationTrigger.GENERATE_ON_DEMAND)
c.set_editor_property('is_component_partitioned', True)
c.generate_local(True)
print('RESULT generate ' + label)
""".replace("__GRAPH__", GRAPH)

COUNT = HEAD + """
n = 0
pas = 0
for a in eas.get_all_level_actors():
    if isinstance(a, unreal.PCGPartitionActor):
        l = a.get_actor_location()
        if l.x < x0 - 25600.0 or l.x > x0 + 2 * P + 25600.0 or l.y < y0 - 25600.0 or l.y > y0 + 2 * P + 25600.0:
            continue
        mine = False
        for c in a.get_components_by_class(unreal.PCGComponent):
            g = c.get_graph()
            if g is not None and g.get_name() == 'PCG_Ecology_Trees':
                mine = True
        if mine:
            pas += 1
            for c in a.get_components_by_class(unreal.InstancedStaticMeshComponent):
                m = c.get_editor_property('static_mesh')
                if m is not None and (m.get_name().startswith('SM_Saskarta_TreeFar_') or m.get_name().startswith('SM_PineTree_')):
                    k = c.get_instance_count()
                    for i in range(k):
                        p = c.get_instance_transform(i, True).translation
                        if p.x >= x0 and p.x < x0 + 2 * P and p.y >= y0 and p.y < y0 + 2 * P:
                            n += 1
print('RESULT count ' + str(n) + ' ' + str(pas))
"""

SAVE = HEAD + """
CHUNK = 0
pk = []
for a in eas.get_all_level_actors():
    if a.get_actor_label() == label:
        pk.append(a.get_package())
    if isinstance(a, unreal.PCGPartitionActor):
        mine = False
        for c in a.get_components_by_class(unreal.PCGComponent):
            g = c.get_graph()
            if g is not None and g.get_name() == 'PCG_Ecology_Trees':
                mine = True
        if mine:
            pk.append(a.get_package())
part = pk[CHUNK * 20:(CHUNK + 1) * 20]
ok = True
if len(part) > 0:
    ok = unreal.EditorLoadingAndSavingUtils.save_packages(part, True)
print('RESULT save ' + str(len(part)) + ' ' + str(len(pk)) + ' ' + str(ok))
"""


LOADED = HEAD + """
k = {}
for a in eas.get_all_level_actors():
    n = a.get_class().get_name()
    if n in ['LandscapeStreamingProxy', 'PCGPartitionActor']:
        k[n] = k.get(n, 0) + 1
print('RESULT loaded ' + str(k.get('LandscapeStreamingProxy', 0)) + ' ' + str(k.get('PCGPartitionActor', 0)))
"""


def run(template, region, **kw):
    # The user may start PIE while the gate is held; saving and actor loading fail in play
    # mode, so every call waits until PIE is over (up to 30 min), then goes ahead.
    waited = 0
    while pie_running():
        if waited == 0:
            print(time.strftime("%H:%M:%S"), f"{region}: PIE is running, waiting", flush=True)
        time.sleep(5)
        waited += 5
        if waited > 1800:
            raise RuntimeError(f"{region}: PIE still running after 30 min")
    if waited:
        time.sleep(10)
    s = check_pcg_culls.fill(template, "REGION", list(region))
    for k, v in kw.items():
        s = check_pcg_culls.fill(s, k, v)
    reply = check_pcg_culls.send(s, timeout=180)
    data = reply.get("data") or {}
    out = data.get("stdout") or ""
    for line in out.splitlines():
        if line.startswith("RESULT "):
            return line[len("RESULT "):].split()
    raise RuntimeError(f"{region}: no RESULT: {out[-500:]} {data.get('stderr', '')[-800:]} {reply.get('error', '')}")


def commit_pct():
    ps = ("$o=Get-CimInstance Win32_OperatingSystem; "
          "[math]::Round((($o.TotalVirtualMemorySize-$o.FreeVirtualMemory)/$o.TotalVirtualMemorySize)*100,1)")
    out = subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps], capture_output=True, text=True).stdout
    return float(out.strip())


def region_scope(r):
    """LANE4: a narrow lease on the region's box (proxy grid) instead of the whole editor."""
    x0, y0 = X0 + 2 * r[0] * P, Y0 + 2 * r[1] * P
    return f"wp-region:/Game/level/Saskarta_WP:{int(x0 + 100)},{int(y0 + 100)},{int(x0 + 2 * P - 100)},{int(y0 + 2 * P - 100)}"


def gate(cmd, owner, timeout_min=9.0, scopes=()):
    args = GATE + [cmd, "--owner", owner]
    if cmd == "acquire":
        args += ["--timeout-min", str(timeout_min), "--ttl-min", "15"]
        for sc in scopes:
            args += ["--scope", sc]
    return subprocess.run(args, capture_output=True, text=True).returncode == 0


def load_done():
    return json.loads(DONE.read_text(encoding="utf-8")) if DONE.exists() else {"regions": {}}


def order():
    """Road regions first, then the rest by distance from them."""
    rest = [(i, j) for i in range(8) for j in range(8) if (i, j) not in ROAD_REGIONS]
    rest.sort(key=lambda r: min((r[0] - a) ** 2 + (r[1] - b) ** 2 for a, b in ROAD_REGIONS))
    return ROAD_REGIONS + rest


def do_region(r, log):
    t0 = time.time()
    base = run(LOADED, r)                                  # other lanes may hold their own actors loaded
    res = run(LOAD, r, MODE="load")
    log(f"{r} loaded proxies {res[1]} partition actors {res[2]}")
    run(SETUP, r)
    last, stable = -1, 0
    for poll in range(60):                                 # up to about 3 min
        time.sleep(3)
        n = int(run(COUNT, r)[1])
        stable = stable + 1 if n == last else 0
        last = n
        if stable >= 2 and (n > 0 or poll >= 10):          # a region may hold no trees at all
            break
    chunk, saved = 0, 0
    while True:
        res = run(SAVE, r, CHUNK=chunk)
        saved += int(res[1])
        if res[3] != "True":
            raise RuntimeError(f"{r}: save chunk {chunk} failed")
        if (chunk + 1) * 20 >= int(res[2]):
            break
        chunk += 1
    res = run(LOAD, r, MODE="unload")                     # a separate call from the save
    time.sleep(3)                                          # the unload lands on a later frame (LANE4)
    left = run(LOADED, r)
    if int(left[1]) > int(base[1]) or int(left[2]) > int(base[2]):
        raise RuntimeError(f"{r}: still loaded after unload: proxies {left[1]} partition actors {left[2]}")
    return {"trees": last, "saved_packages": saved, "seconds": round(time.time() - t0, 1),
            "at": time.strftime("%Y-%m-%d %H:%M:%S")}


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "status"])
    ap.add_argument("regions", nargs="*")
    ap.add_argument("--owner", default="V5R")
    ap.add_argument("--max", type=int, default=64)
    ap.add_argument("--minutes", type=float, default=120.0)
    ap.add_argument("--hold-min", type=float, default=15.0)
    ap.add_argument("--max-commit", type=float, default=80.0)
    ap.add_argument("--redo", default="", help="progress key: regenerate regions already done, tracked under this key (e.g. pines)")
    ap.add_argument("--scoped", action="store_true", help="lease each region's box (wp-region) instead of the whole editor")
    a = ap.parse_args(argv)
    done = load_done()
    if a.cmd == "status":
        todo = [r for r in order() if f"{r[0]},{r[1]}" not in done["regions"]]
        print(json.dumps(done, indent=1))
        print(f"done {len(done['regions'])} of 64; remaining: {' '.join(f'{i},{j}' for i, j in todo)}")
        return 0
    todo = [tuple(int(v) for v in s.split(",")) for s in a.regions] or order()
    key = "regions_" + a.redo if a.redo else "regions"
    done.setdefault(key, {})
    if a.redo:
        todo = [r for r in todo if f"{r[0]},{r[1]}" in done["regions"] and f"{r[0]},{r[1]}" not in done[key]][: a.max]
    else:
        todo = [r for r in todo if f"{r[0]},{r[1]}" not in done["regions"]][: a.max]

    def log(msg):
        print(time.strftime("%H:%M:%S"), msg, flush=True)

    start = time.time()
    tries = 0
    if a.scoped:
        # one narrow lease per region: acquire, do the region, release (LANE4)
        for r in todo:
            if time.time() - start > a.minutes * 60:
                log("time budget used")
                break
            pct = commit_pct()
            if pct > a.max_commit:
                log(f"commit {pct}% > {a.max_commit}%: stopping")
                break
            granted = gate("acquire", a.owner, 1.0, [region_scope(r)])
            for _ in range(15):                               # overlapping leases expire (15 min TTL)
                if granted:
                    break
                log(f"{r}: lease not granted yet, retrying in 60 s")
                time.sleep(60)
                granted = gate("acquire", a.owner, 1.0, [region_scope(r)])
            if not granted:
                log(f"{r}: lease not granted: stopping")
                return 4
            try:
                info = do_region(r, log)
            finally:
                gate("release", a.owner)
            info["commit_pct_before"] = pct
            done[key][f"{r[0]},{r[1]}"] = info
            DONE.write_text(json.dumps(done, indent=1), encoding="utf-8")
            log(f"{r} trees {info['trees']} saved {info['saved_packages']} in {info['seconds']} s (commit {pct}%)")
            time.sleep(5)                                     # a breather for the user's editor
        return 0
    while not gate("acquire", a.owner):
        tries += 1
        log("waiting for the gate")
        if tries >= 26:                                    # about 4 h (R37)
            return 4
    held_since = time.time()
    try:
        for r in todo:
            if time.time() - start > a.minutes * 60:
                log("time budget used")
                break
            if time.time() - held_since > a.hold_min * 60:
                gate("release", a.owner)
                log("released the gate for other lanes")
                time.sleep(20)
                while not gate("acquire", a.owner):
                    log("waiting for the gate")
                held_since = time.time()
            else:
                gate("acquire", a.owner, 0.1)               # renew in place
            pct = commit_pct()
            waited = 0
            while pct > a.max_commit and waited < 10:
                log(f"commit {pct}% > {a.max_commit}%: waiting")
                time.sleep(30)
                waited += 1
                pct = commit_pct()
            if pct > a.max_commit:
                log(f"commit still {pct}%: stopping")
                break
            info = do_region(r, log)
            info["commit_pct_before"] = pct
            done["regions"][f"{r[0]},{r[1]}"] = info
            DONE.write_text(json.dumps(done, indent=1), encoding="utf-8")
            log(f"{r} trees {info['trees']} saved {info['saved_packages']} in {info['seconds']} s (commit {pct}%)")
    finally:
        gate("release", a.owner)
        log("gate released")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
