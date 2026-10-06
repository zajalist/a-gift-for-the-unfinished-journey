#!/usr/bin/env python3
"""Find and ground floating props in Saskarta_WP (the author, packaged playtest 2026-09-29: "still a bunch of
floating props", an overturned cart hovering over the grass, two canopy shapes over a ridge).

    python Tools/World/ground_props.py survey            # read-only: every placed prop's actor desc -> Saved/Grounding/descs.json
    python Tools/World/ground_props.py judge             # offline: bottom of each desc box vs the heightmap -> candidates.json
    python Tools/World/ground_props.py load  N           # load candidate batch N (20 per batch)
    python Tools/World/ground_props.py measure N         # loaded batch: oriented mesh boxes -> measure_N.json
    python Tools/World/ground_props.py fix N             # offline plan (lower / tilt) + one python_run applying it
    python Tools/World/ground_props.py save N            # save the batch's changed actor packages
    python Tools/World/ground_props.py unload N

This is a legacy bounds/heightmap triage tool. The imported heightmap is not proof of current terrain.
Missing current landscape traces now remain unknown and cannot produce an accepted contact or movement.
For repairs use prepare_ground_contact_survey.py with explicitly loaded landscape proxies and actual mesh
contact points. Even a centre trace cannot validate the terrain slope across an entire wide prop.

Rules (setdress_contact.TOL_FLOAT): a prop floats when its LOWEST oriented-box corner clears the ground under it
by more than 5 cm. It is lowered so that corner sinks SINK cm (3..15 by size, rocks 20). Flat wide props (carts,
planks, tents, fire pits: the box's own up axis is its shortest) are first tilted so their base follows the plane
through the ground under their four base corners (at most 20 deg). A prop whose base sits on another prop's box
(within 10 cm of its top) is skipped: it rests on a mesh.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Tools" / "Cinematics"))
sys.path.insert(0, str(ROOT / "Tools" / "GameFlow" / "editor"))
sys.path.insert(0, str(ROOT / "Tools" / "Look"))
OUT = ROOT / "Saved" / "Grounding"
BATCH = 20
TOL = 5.0
SKIP_CLASS = ("Landscape", "PCG", "HLOD", "Volume", "Light", "Sky", "Fog", "Cloud", "Camera", "Player", "Note",
              "WorldPartition", "Niagara", "Audio", "Ambient", "Decal", "Spline", "Road", "Water", "Info", "Carrier",
              "Traveller", "Keeper", "Emitter", "Brush", "Reflection", "PostProcess", "Trigger", "Level", "Sequence")
FLAT_HINT = ("cart", "plank", "tent", "fire", "table", "crate", "bench", "cloth", "rug", "bed", "pallet", "board")
ROCK_HINT = ("rock", "stone", "boulder", "cliff")

SURVEY = r'''
import unreal, json
W = unreal.EditorLevelLibrary.get_editor_world()
L = unreal.WorldPartitionBlueprintLibrary
descs = L.get_intersecting_actor_descs(L.get_editor_world_bounds())
SKIP = __SKIP__
rows = []
for d in descs:
    c = str(d.native_class.get_name()) if d.native_class else ""
    cn = str(d.class_.export_text())
    if any(k in c or k in cn for k in SKIP):
        continue
    b = d.bounds
    rows.append([d.guid.export_text(), c, cn, str(d.label), round(b.min.x,1), round(b.min.y,1), round(b.min.z,1),
                 round(b.max.x,1), round(b.max.y,1), round(b.max.z,1), bool(d.is_spatially_loaded), str(d.actor_path), str(d.actor_package)])
print("N", len(descs), len(rows))
print("ROWS" + json.dumps(rows[__A__:__B__], separators=(",", ":")))
'''

LOAD = r'''
import unreal
L = unreal.WorldPartitionBlueprintLibrary
G = __GUIDS__
descs = L.get_intersecting_actor_descs(L.get_editor_world_bounds())
gs = [d.guid for d in descs if d.guid.export_text() in G]
L.load_actors(gs)
print("LOADED", len(gs))
'''

UNLOAD = LOAD.replace("L.load_actors(gs)", "L.unload_actors(gs)\nL.unpin_actors(gs)").replace('"LOADED"', '"UNLOADED"')

MEASURE = r'''
import unreal, json
W = unreal.EditorLevelLibrary.get_editor_world()
G = __PATHS__
out = []
for a in unreal.EditorLevelLibrary.get_all_level_actors():
    g = G.get(str(a.get_path_name()))
    if g is None:
        continue
    boxes = []
    for c in a.get_components_by_class(unreal.StaticMeshComponent):
        m = c.static_mesh
        if m is None or not c.is_visible():
            continue
        bb = m.get_bounding_box()
        ct = c.get_world_transform()
        corners = []
        for x in (bb.min.x, bb.max.x):
            for y in (bb.min.y, bb.max.y):
                for z in (bb.min.z, bb.max.z):
                    p = ct.transform_location(unreal.Vector(x, y, z))
                    corners.append([round(p.x,1), round(p.y,1), round(p.z,1)])
        boxes.append([str(m.get_name()), corners])
    o = a.get_actor_location()
    hits = []
    for p in [[o.x, o.y]]:
        r = unreal.SystemLibrary.line_trace_multi(W, unreal.Vector(p[0], p[1], o.z + 5000), unreal.Vector(p[0], p[1], o.z - 20000),
            unreal.TraceTypeQuery.TRACE_TYPE_QUERY1, False, [a], unreal.DrawDebugTrace.NONE, True)
        for h in r or []:
            ha = h.to_tuple()[9]
            if ha and "Landscape" in str(ha.get_class().get_name()):
                hits.append(round(h.to_tuple()[4].z, 1))
                break
    r = a.get_actor_rotation()
    out.append([g, str(a.get_actor_label()), str(a.get_path_name()), [round(o.x,2), round(o.y,2), round(o.z,2)],
                [round(r.roll,3), round(r.pitch,3), round(r.yaw,3)], boxes, hits, str(a.get_package().get_name())])
print("M" + json.dumps(out, separators=(",", ":")))
'''

APPLY = r'''
import unreal
P = __PLAN__
n = 0
for a in unreal.EditorLevelLibrary.get_all_level_actors():
    g = str(a.get_path_name())
    if g not in P:
        continue
    loc, rot = P[g]
    a.modify()
    a.set_actor_location_and_rotation(unreal.Vector(*loc), unreal.Rotator(roll=rot[0], pitch=rot[1], yaw=rot[2]), False, True)
    n += 1
print("APPLIED", n)
'''

SAVE = r'''
import unreal
P = __PKGS__
pk = [unreal.load_package(p) for p in P]
pk = [p for p in pk if p is not None]
print("SAVED", unreal.EditorLoadingAndSavingUtils.save_packages(pk, True), len(pk))
'''


def send(script, label):
    import ending_editor  # noqa: E402  (banned-word check, PIE refusal, fault watch)
    return ending_editor.send(script, label)


def ground(x, y):
    import build_cinematics as bc  # noqa: E402
    return bc.ground_z(x, y)


def survey():
    OUT.mkdir(parents=True, exist_ok=True)
    rows, a = [], 0
    while True:
        s = SURVEY.replace("__SKIP__", repr(SKIP_CLASS)).replace("__A__", str(a)).replace("__B__", str(a + 150))
        out = send(s, f"survey {a}")
        n_rows = int(out.split("N ", 1)[1].split()[1])
        part = json.loads(out.split("ROWS", 1)[1].strip())
        rows += part
        a += 150
        if a >= n_rows:
            break
    (OUT / "descs.json").write_text(json.dumps(rows), encoding="utf-8")
    print("descs", len(rows))


def judge():
    """Offline: every prop's desc box against the heightmap. 'own' = clears the lowest ground sample under its box by
    more than TOL and rests on no other box; 'follow' = rests on another box (bottom within 10 cm of its top) whose
    support chain ends at an 'own' prop: it moves by the same height as that root, so stacks stay together."""
    rows = json.loads((OUT / "descs.json").read_text(encoding="utf-8"))
    keep = [r for r in rows if r[10] and 1 < (r[7] - r[4]) < 6000 and (r[8] - r[5]) < 6000
            and "_ism_" not in r[3] and "StormDust" not in r[3]]
    info = {}
    for r in keep:
        x0, y0, z0, x1, y1, z1 = r[4:10]
        gs = [ground(x, y) for x, y in [(x0, y0), (x0, y1), (x1, y0), (x1, y1), ((x0 + x1) / 2, (y0 + y1) / 2)]]
        sup = None
        for q in keep:
            if q is r or not (q[9] - 10 <= z0 <= q[9] + 10) or q[9] >= z1:
                continue
            if q[4] < x1 and q[7] > x0 and q[5] < y1 and q[8] > y0 and (sup is None or q[9] > sup[9]):
                sup = q
        info[r[0]] = (r, z0 - max(gs), z0 - min(gs), sup[0] if sup else None)
    def root(g, depth=0):
        r, gap, gap_lo, sup = info[g]
        if sup is None or depth > 8:
            return g
        return root(sup, depth + 1)
    own, follow = [], []
    for g, (r, gap, gap_lo, sup) in info.items():
        c = {"guid": g, "path": r[11], "pkg": r[12], "cls": r[2], "label": r[3], "gap": round(gap, 1),
             "gap_lo": round(gap_lo, 1), "size": round(max(r[7] - r[4], r[8] - r[5], r[9] - r[6]), 1)}
        if sup is None:
            if gap_lo > TOL:
                own.append(c)
        else:
            rt = root(g)
            if rt != g and info[rt][3] is None and info[rt][2] > TOL:
                c["follow"] = rt
                follow.append(c)
    own.sort(key=lambda c: c["label"]); follow.sort(key=lambda c: c["label"])
    cands = own + follow
    (OUT / "candidates.json").write_text(json.dumps(cands, indent=1), encoding="utf-8")
    print("checked", len(keep), "own", len(own), "follow", len(follow), "batches", (len(cands) + BATCH - 1) // BATCH,
          "(skipped: ism/storm/huge/not spatial", len(rows) - len(keep), ")")


def batch(n):
    cands = json.loads((OUT / "candidates.json").read_text(encoding="utf-8"))
    return cands[n * BATCH:(n + 1) * BATCH]


def axes(roll, pitch, yaw):
    sys.path.insert(0, str(ROOT / "Tools" / "World"))
    import setdress_contact as sc  # noqa: E402
    return sc.axes(yaw, pitch, roll)


def rotator_from_axes(X, Z):
    """UE rotator (roll, pitch, yaw) of the frame with forward X and up Z (FRotationMatrix inverse)."""
    Y = (Z[1] * X[2] - Z[2] * X[1], Z[2] * X[0] - Z[0] * X[2], Z[0] * X[1] - Z[1] * X[0])
    pitch = math.degrees(math.atan2(X[2], math.hypot(X[0], X[1])))
    yaw = math.degrees(math.atan2(X[1], X[0]))
    cy, sy = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
    # roll from Y's vertical component: Y.z = -sr*cp, Z.z = cr*cp
    roll = math.degrees(math.atan2(-Y[2], Z[2]))
    _ = cy, sy
    return roll, pitch, yaw


def rotate(v, axis, ang):
    """Rodrigues rotation of v about unit axis by ang radians."""
    c, s = math.cos(ang), math.sin(ang)
    d = sum(v[i] * axis[i] for i in range(3))
    cr = (axis[1] * v[2] - axis[2] * v[1], axis[2] * v[0] - axis[0] * v[2], axis[0] * v[1] - axis[1] * v[0])
    return tuple(v[i] * c + cr[i] * s + axis[i] * d * (1 - c) for i in range(3))


def landscape_offset(trace_z, heightmap_z):
    """Return a measured correction; an unloaded/missing landscape is not a zero offset."""
    if trace_z is None or not math.isfinite(trace_z):
        raise ValueError("Current landscape trace required; no imported-heightmap fallback")
    return trace_z - heightmap_z


def plan(m):
    """One measured actor -> (new loc, new rot, note) or None when it already touches."""
    g, label, path, loc, rot, boxes, hits, pkg = m
    if not hits or not math.isfinite(hits[0]):
        return None, "unknown: current landscape not hit; load its proxy and remeasure"
    corners = [p for _, cs in boxes for p in cs]
    if not corners:
        return None, "no mesh"
    lname = label.lower() + " " + " ".join(b[0].lower() for b in boxes)
    gz = [ground(p[0], p[1]) for p in corners]
    # a landscape trace under the centre corrects the heightmap offset (regraded road)
    off = landscape_offset(hits[0] if hits else None, ground(loc[0], loc[1]))
    clear = [p[2] - (gz[i] + off) for i, p in enumerate(corners)]
    low = min(clear)
    base = sorted(clear)[:4]
    hang = base[-1] - base[0]
    flat_hint = any(k in lname for k in FLAT_HINT)
    if low <= TOL and not (flat_hint and hang > 10.0):
        return None, f"touches ({low:.1f})"
    xs = [p[0] for p in corners]; ys = [p[1] for p in corners]; zs = [p[2] for p in corners]
    size = max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))
    sink = 20.0 if any(k in lname for k in ROCK_HINT) else max(3.0, min(15.0, size * 0.03))
    new_rot = list(rot)
    new_loc = list(loc)
    note = "lowered"
    flat = any(k in lname for k in FLAT_HINT) and (max(zs) - min(zs)) < 0.8 * max(max(xs) - min(xs), max(ys) - min(ys))
    if flat:
        # plane through the ground under the box footprint (least squares over the corners' xy)
        n = len(corners)
        mx, my = sum(xs) / n, sum(ys) / n
        sxx = sum((x - mx) ** 2 for x in xs); syy = sum((y - my) ** 2 for y in ys)
        sxy = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
        sxz = sum((xs[i] - mx) * gz[i] for i in range(n)); syz = sum((ys[i] - my) * gz[i] for i in range(n))
        det = sxx * syy - sxy * sxy
        if det > 1e-6:
            a = (sxz * syy - syz * sxy) / det
            b = (syz * sxx - sxz * sxy) / det
            nrm = (-a, -b, 1.0); ln = math.sqrt(a * a + b * b + 1); nrm = tuple(v / ln for v in nrm)
            tilt = math.acos(max(-1, min(1, nrm[2])))
            X0, _Y0, Z0 = axes(*rot)
            if abs(Z0[2]) < 0.9:
                tilt = 0.0   # already on its side / overturned by design: no re-levelling, only lowering
            if 0.02 < tilt < math.radians(20):
                ax = (-nrm[1], nrm[0], 0.0); al = math.hypot(ax[0], ax[1]); ax = (ax[0] / al, ax[1] / al, 0.0)
                X, _Y, Z = axes(*rot)
                new_rot = list(rotator_from_axes(rotate(X, ax, tilt), rotate(Z, ax, tilt)))
                # re-evaluate the corners about the pivot
                corners = [[loc[j] + rotate(tuple(p[k] - loc[k] for k in range(3)), ax, tilt)[j] for j in range(3)] for p in corners]
                gz = [ground(p[0], p[1]) for p in corners]
                clear = [p[2] - (gz[i] + off) for i, p in enumerate(corners)]
                low = min(clear)
                note = f"tilted {math.degrees(tilt):.1f} + lowered"
    new_loc[2] = loc[2] - low - sink
    return (new_loc, new_rot, f"{note} {low + sink:.1f}"), "fix"


def main(argv):
    step = argv[0] if argv else ""
    if step == "survey":
        return survey()
    if step == "judge":
        return judge()
    n = int(argv[1]) if len(argv) > 1 else 0
    b = batch(n)
    guids = [c["guid"] for c in b]
    if not guids:
        print("empty batch", n)
        return 0
    if step == "load":
        return send(LOAD.replace("__GUIDS__", repr(guids)), f"load {n}") and 0
    if step == "unload":
        return send(UNLOAD.replace("__GUIDS__", repr(guids)), f"unload {n}") and 0
    if step == "measure":
        out = send(MEASURE.replace("__PATHS__", repr({c["path"]: c["guid"] for c in b})), f"measure {n}")
        ms = json.loads(out.split("M", 1)[1].strip()) if "\nM[" in "\n" + out or out.startswith("M[") else []
        (OUT / f"measure_{n}.json").write_text(json.dumps(ms), encoding="utf-8")
        print("measured", len(ms))
        return 0
    if step in ("plan", "fix"):
        ms = json.loads((OUT / f"measure_{n}.json").read_text(encoding="utf-8"))
        P, pk, log = {}, [], []
        dzf = OUT / "dz.json"
        DZ = json.loads(dzf.read_text(encoding="utf-8")) if dzf.exists() else {}
        byg = {c["guid"]: c for c in b}
        for m in ms:
            c = byg.get(m[0], {})
            if not m[6] or not math.isfinite(m[6][0]):
                r, why = None, "unknown: current landscape not hit; load its proxy and remeasure"
            elif c.get("follow"):
                dz = DZ.get(c["follow"])
                r, why = ((None, "root not moved") if not dz else
                          (([m[3][0], m[3][1], m[3][2] + dz], m[4], f"follows root {dz:.1f}"), "fix"))
                if r is None:
                    r = None
            else:
                r, why = plan(m)
                if r is not None:
                    DZ[m[0]] = round(r[0][2] - m[3][2], 2)
            log.append({"guid": m[0], "label": m[1], "loc": m[3], "rot": m[4], "trace": m[6], "result": why if r is None else r[2],
                        "new": None if r is None else [r[0], r[1]], "pkg": m[7]})
            print(f"  {m[1][:40]:40s} {why if r is None else r[2]}")
            if r is not None:
                P[m[2]] = [[round(v, 2) for v in r[0]], [round(v, 3) for v in r[1]]]
                pk.append(m[7])
        dzf.write_text(json.dumps(DZ), encoding="utf-8")
        (OUT / f"plan_{n}.json").write_text(json.dumps({"plan": P, "pkgs": pk, "log": log}, indent=1), encoding="utf-8")
        if step == "fix" and P:
            send(APPLY.replace("__PLAN__", repr(P)), f"apply {n}")
        return 0
    if step == "save":
        pk = json.loads((OUT / f"plan_{n}.json").read_text(encoding="utf-8"))["pkgs"]
        import os
        import stat
        for p in pk:
            f = ROOT / "Content" / (p[len("/Game/"):] + ".uasset")
            if f.exists() and not os.access(f, os.W_OK):
                print("read-only, made writable:", f.name)
                os.chmod(f, stat.S_IWRITE | stat.S_IREAD)
        if pk:
            send(SAVE.replace("__PKGS__", repr(pk)), f"save {n}")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]) or 0)
