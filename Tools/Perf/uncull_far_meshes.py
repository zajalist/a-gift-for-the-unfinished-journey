"""Stop placed buildings/props from popping in (user, 2026-10-06): raise per-actor LD max draw distances.

    python Tools/Perf/uncull_far_meshes.py load     # load every StaticMeshActor (chunks of 150)
    python Tools/Perf/uncull_far_meshes.py apply    # edit + save, 20 packages per editor call
    python Tools/Perf/uncull_far_meshes.py report   # distribution only

Rule: bounds radius >= 3 m -> 0 (never culled); smaller -> at least 200 m. 0 stays 0.
Skips SPLAT_*, StormDust_*, Saskarta_* (dream splats / storm / horizon set by hand).
Runs over Hayba's raw TCP python_run (5 s cooperative deadline per call). Actors stay loaded.
"""
import json, socket, struct, sys

PORT = 52342
SKIP = ('SPLAT_', 'StormDust_', 'Saskarta_')

def send(script, timeout=120):
    env = {"cmd": "python_run", "id": "uncull_far_meshes", "params": {"script": script}}
    payload = json.dumps(env).encode("utf-8")
    with socket.create_connection(("127.0.0.1", PORT), timeout=timeout) as s:
        s.sendall(struct.pack(">I", len(payload)) + payload)
        head = b""
        while len(head) < 4:
            head += s.recv(4 - len(head))
        size = struct.unpack(">I", head)[0]
        body = b""
        while len(body) < size:
            body += s.recv(size - len(body))
    r = json.loads(body.decode("utf-8"))
    if not r.get("ok"):
        raise RuntimeError(json.dumps(r)[:1500])
    d = r.get("data") or {}
    return (d.get("stdout") or "") + (d.get("stderr") or "")

LOAD = r'''
import unreal
L = unreal.WorldPartitionBlueprintLibrary
ds = L.get_intersecting_actor_descs(L.get_editor_world_bounds())
g = [d.guid for d in ds if d.native_class and d.native_class.get_name() == 'StaticMeshActor']
START = 0
L.load_actors(g[START:START + 150])
print('N', len(g))
'''

APPLY = r'''
import unreal
SKIP = ('SPLAT_', 'StormDust_', 'Saskarta_')
START = 0
COUNT = 8
w = unreal.EditorLevelLibrary.get_editor_world()
acts = sorted(unreal.GameplayStatics.get_all_actors_of_class(w, unreal.StaticMeshActor), key=lambda a: a.get_name())
pk = []
i = START
while i < len(acts) and len(pk) < COUNT:
    a = acts[i]
    i += 1
    lab = str(a.get_actor_label())
    if lab.startswith(SKIP):
        continue
    c = a.static_mesh_component
    d = float(c.get_editor_property('ld_max_draw_distance'))
    if d <= 0.0 or not c.static_mesh:
        continue
    s = a.get_actor_scale3d()
    r = c.static_mesh.get_bounds().sphere_radius * max(abs(s.x), abs(s.y), abs(s.z))
    n = 0.0 if r >= 300.0 else max(d, 20000.0)
    if n == d:
        continue
    a.modify()
    c.modify()
    c.set_editor_property('ld_max_draw_distance', n)
    pk.append(a.get_package())
ok = unreal.EditorLoadingAndSavingUtils.save_packages(pk, True) if pk else True
print('NEXT', i, 'OF', len(acts), 'SAVED', len(pk), 'OK', ok)
'''

REPORT = r'''
import unreal
from collections import Counter
w = unreal.EditorLevelLibrary.get_editor_world()
c = Counter(int(a.static_mesh_component.get_editor_property('ld_max_draw_distance')) for a in unreal.GameplayStatics.get_all_actors_of_class(w, unreal.StaticMeshActor))
print(sorted(c.items()))
'''

def fill(script, **kv):
    out = []
    for line in script.split("\n"):
        for k, v in kv.items():
            if line.startswith(k + " = "):
                line = f"{k} = {v!r}"
        out.append(line)
    return "\n".join(out)

def main(mode):
    if mode == "report":
        print(send(REPORT)); return
    if mode == "load":
        start, n = 0, None
        while n is None or start < n:
            out = send(fill(LOAD, START=start))
            n = int(out.split("N", 1)[1].split()[0])
            start += 150
            print("loaded through", min(start, n), "of", n, flush=True)
        return
    if mode == "apply":
        start = int(sys.argv[2]) if len(sys.argv) > 2 else 0
        counts = [6, 5, 4, 3]
        k = 0
        while True:
            try:
                out = send(fill(APPLY, START=start, COUNT=counts[k % len(counts)]))
            except RuntimeError as exc:
                if "HCR-TIME-001" not in str(exc) or k > 200:
                    raise
                k += 1
                print("deadline at", start, "- retrying with COUNT", counts[k % len(counts)], flush=True)
                continue
            print(out.strip(), flush=True)
            parts = out.split()
            nxt, total = int(parts[parts.index("NEXT") + 1]), int(parts[parts.index("OF") + 1])
            if "False" in out:
                print("SAVE FAILED, stopping"); return 1
            if nxt >= total:
                return 0
            start = nxt

if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "report") or 0)
