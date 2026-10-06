"""Install the approved Tripo02 V2 placements without replacing whole sites.

Use `load`/`unload` here and the set-dress `survey` around each site.
The `install`, `check`, and `save` steps are separate editor passes. A clean
subset contact check is required before saving only the Tripo actor packages.
This does not certify the rest of a site's set dressing or its visual design.
"""

import argparse
import ast
import json
import os
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Tools" / "World"))
import place_setdress as sd  # noqa: E402
import setdress_contact as contact  # noqa: E402


TRIPO_PREFIX = "/Game/SaskartaGaea/Environment/Tripo02/SM_T2_"
STATE_DIR = ROOT / "Saved" / "Tripo" / "placement_state"
EXCLUDED = {"SM_T2_brass_dome", "SM_T2_brass_telescope"}
# The imported jar rack is wider than its O14 single-jar stand-in. Its source
# pose clips house 001; this yard-side position keeps the rack clear.
POSITION_OVERRIDES = {
    "O14_GranaryHamlet_014": {"x_cm": 578063.0, "y_cm": 451487.0, "ground_z_cm": -36660.0},
    # Both imported distillation columns are much wider than their refinery
    # placeholders (roughly 10 m across versus 3 m). Put them on the clear
    # southwest bench, preserving the still/manifold cluster to the east.
    "O02_Refinery_000": {"x_cm": 505550.2, "y_cm": 267814.9, "ground_z_cm": -19474.8},
    "O02_Refinery_001": {"x_cm": 507150.2, "y_cm": 267414.9, "ground_z_cm": -19559.8},
}
# Standalone sites for imported models that had no approved V2 replacement slot.
# Each is a measured terrain candidate, kept separate from the existing story
# set so the accepted S08 ruin and caravanserai actors are untouched.
EXTRA_CANDIDATES = {
    "T2E_CollapsedHamlet": ("mudbrick_house_collapsed", 575606.0, 450120.0, -36595.1, 285.3, "stone"),
    "T2E_RidgeWatch": ("watchtower", 540434.0, 349138.0, -35183.1, 145.1, "wood"),
    "T2E_EastCourtyard": ("courtyard", 450256.0, 339850.0, -40287.9, 270.0, "stone"),
    "T2E_WaystationHut": ("stone_hut", 375865.5, 376200.0, -32186.2, 215.0, "stone"),
    "T2E_DryChannelBridge": ("rope_footbridge", 431045.4, 299409.5, -39442.5, 22.5, "wood"),
}


def extra_site(name, doc):
    mesh, x, y, z, yaw, material_set = EXTRA_CANDIDATES[name]
    path = TRIPO_PREFIX + mesh
    bounds = json.loads((ROOT / "Saved" / "Tripo" / "imported_bounds.json").read_text(encoding="utf8"))
    if path not in bounds:
        raise SystemExit("missing imported bounds for " + path)
    base = next(p for s in doc["sites"] for p in s["placements"]
                if p["id"] == "O14_GranaryHamlet_000")
    p = dict(base)
    p.update(id=name + "_000", key="T2_" + mesh, asset=path, x_cm=x, y_cm=y,
             ground_z_cm=z, yaw=yaw, pitch=0.0, roll=0.0, scale=1.0,
             size_m=[v / 100.0 for v in bounds[path]["size_cm"]],
             group="standalone", folder="Set/TripoV2Extras/" + name,
             material_set=material_set, material=bounds[path]["material"],
             draw_distance_cm=100000.0, optional=False, verdict="use",
             imported=True, requires_import=True)
    p["settle"] = dict(base["settle"])
    if mesh == "rope_footbridge":
        p["contact"] = "rigid"
        p["settle"]["sink_cm"] = 5
    return {"id": name, "centre_cm": [x, y], "radius_m": 30.0,
            "views": [], "placements": [p], "load_near_all": True}
# The generic clearance pass takes the first collision hit, including stale
# HLOD proxies. The Tripo actors are settled against landscape and check2
# measures that same support, so use the landscape-through trace here too.
assert sd.CHECK_BODY.count("trace_down(") == 2
TRIPO_CHECK_BODY = sd.CHECK_BODY.replace("trace_down(", "trace_ground(")


LOAD_TARGETS_BODY = r'''
level_name = world.get_path_name().split('.')[0]
if level_name != '/Game/level/Saskarta_WP':
    raise RuntimeError('Tripo placement requires Saskarta_WP, got ' + level_name)
lib = unreal.WorldPartitionBlueprintLibrary
xs = [it['x_cm'] for it in ITEMS]
ys = [it['y_cm'] for it in ITEMS]
margin = 2500 if LOAD_NEAR_ALL else 1200
box = unreal.Box(V(min(xs) - margin, min(ys) - margin, -1000000),
                 V(max(xs) + margin, max(ys) + margin, 1000000))
r = lib.get_intersecting_actor_descs(box)
descs = r[1] if isinstance(r, tuple) else r
resident = {a.get_editor_property('actor_guid').export_text() for a in eas.get_all_level_actors()}
want = []
names = []
land = 0
for d in descs:
    cls = str(d.get_editor_property('native_class'))
    if 'HLOD' in cls or 'PCG' in cls:
        continue
    is_land = 'Landscape' in cls
    label = str(d.get_editor_property('label'))
    is_target = label in TARGET_LABELS
    is_site = label.startswith('SD_' + SITE + '_')
    if not (is_land or is_target or is_site or LOAD_NEAR_ALL):
        continue
    b = d.get_editor_property('bounds')
    near = False
    for it in ITEMS:
        x, y = it['x_cm'], it['y_cm']
        margin = 2500 if LOAD_NEAR_ALL else 900
        if b.max.x >= x - margin and b.min.x <= x + margin and b.max.y >= y - margin and b.min.y <= y + margin:
            near = True
            break
    if not near:
        continue
    if is_land:
        land += 1
        if land > 20:
            continue
    g = d.get_editor_property('guid')
    name = g.export_text()
    if name in ALREADY and name in resident:
        continue
    want.append(g)
    names.append(name)
    if len(want) >= LIMIT:
        break
if len(want) > 0:
    lib.load_actors(want)
print('T2LOADED ' + json_list(names))
print('T2LOAD landscape=' + str(land) + ' count=' + str(len(want)) + (' DONE' if len(want) < LIMIT else ' MORE'))
'''


AUDIT_BODY = r'''
level_name = world.get_path_name().split('.')[0]
if level_name != '/Game/level/Saskarta_WP':
    raise RuntimeError('Tripo placement requires Saskarta_WP, got ' + level_name)
have = site_actors(SITE)
for it in ITEMS:
    lab = 'SD_' + it['id']
    a = have.get(lab)
    if a is None:
        print('T2MISS ' + it['id'])
        continue
    comps = a.get_components_by_class(unreal.StaticMeshComponent)
    mesh = comps[0].static_mesh if len(comps) == 1 else None
    path = mesh.get_path_name().split('.')[0] if mesh is not None else 'NO_MESH'
    print('T2ACT ' + it['id'] + ' ' + path + ' ' + a.get_package().get_name())
for row in HOSTS:
    gid, expected = row
    lab = 'SD_' + gid
    a = have.get(lab)
    if a is None:
        print('T2HOSTMISS ' + gid)
        continue
    comps = a.get_components_by_class(unreal.InstancedStaticMeshComponent)
    mesh = comps[0].static_mesh if len(comps) == 1 else None
    path = mesh.get_path_name().split('.')[0] if mesh is not None else 'NO_MESH'
    count = comps[0].get_instance_count() if len(comps) == 1 else -1
    print('T2HOST ' + gid + ' ' + path + ' ' + str(count) + ' ' + a.get_package().get_name())
print('T2AUDIT DONE')
'''


MATERIAL_HOST_BODY = r'''
have = site_actors(SITE)
done = 0
for gid in HOST_IDS:
    a = have.get('SD_' + gid)
    if a is None:
        continue
    for comp in a.get_components_by_class(unreal.InstancedStaticMeshComponent):
        vals = [0.0, 0.0, 0.0, 0.0, 0.45, 0.96, 0.92, 0.88]
        for j in range(len(vals)):
            comp.set_default_custom_primitive_data_float(j, float(vals[j]))
    done += 1
print('T2MATERIAL hosts=' + str(done) + ' DONE')
'''


SAVE_TARGETS_BODY = r'''
have = site_actors(SITE)
pkgs = []
for lab in LABELS:
    a = have.get(lab)
    if a is None:
        print('T2SAVE missing=' + lab)
    else:
        pkgs.append(a.get_package())
if len(pkgs) != len(LABELS):
    print('T2SAVE count=' + str(len(pkgs)) + ' expected=' + str(len(LABELS)) + ' ok=False DONE')
else:
    ok = unreal.EditorLoadingAndSavingUtils.save_packages(pkgs, True)
    print('T2SAVE count=' + str(len(pkgs)) + ' expected=' + str(len(LABELS)) + ' ok=' + str(ok) + ' DONE')
'''


def selected(site, only_id=None):
    rows = [dict(p, **POSITION_OVERRIDES.get(p["id"], {}))
            for p in site["placements"] if p.get("asset", "").startswith(TRIPO_PREFIX)
            and p["asset"].rsplit("/", 1)[-1] not in EXCLUDED
            and (only_id is None or p["id"] == only_id)]
    bad = [p["id"] for p in rows if p.get("optional") or p.get("verdict") != "use"
           or not p.get("imported") or not p.get("requires_import")]
    if bad:
        raise SystemExit("Tripo source has unapproved placements: " + ", ".join(bad))
    missing = [p["asset"] for p in rows if not (ROOT / "Content" / (p["asset"][6:] + ".uasset")).is_file()]
    if missing:
        raise SystemExit("Tripo mesh packages missing: " + ", ".join(sorted(set(missing))))
    return rows


def canonical_jobs(site, rows):
    if not any(p["ism"] for p in rows):
        return []
    # Host IDs include the index of every mesh group in the full V2 site.
    # Deriving IDs from just the Tripo subset would collide with other hosts.
    defaults = argparse.Namespace(approve="", with_optional=False, skip_story=False, no_ism=False)
    full_items, _ = sd.select(site, defaults)
    wanted = {p["id"] for p in rows if p["ism"]}
    jobs = [(gid, asset, ps) for gid, asset, ps in sd.ism_jobs(site["id"], full_items, sd.BATCH["ism"])
            if any(p["id"] in wanted for p in ps)]
    covered = {p["id"] for _, _, ps in jobs for p in ps}
    if covered != wanted:
        raise SystemExit("Tripo ISM host grouping does not cover the current V2 placements")
    return jobs


def plan(doc):
    rows = [(s["id"], selected(s)) for s in doc["sites"]]
    rows = [(sid, ps) for sid, ps in rows if ps]
    for sid, ps in rows:
        print("%-24s %3d solo=%2d ism=%2d" %
              (sid, len(ps), sum(not p["ism"] for p in ps), sum(bool(p["ism"]) for p in ps)))
    print("PLAN sites=%d placements=%d solo=%d ism=%d" %
          (len(rows), sum(len(ps) for _, ps in rows),
           sum(not p["ism"] for _, ps in rows for p in ps),
           sum(bool(p["ism"]) for _, ps in rows for p in ps)))


def read_state(site_id):
    path = STATE_DIR / (site_id + ".json")
    return json.loads(path.read_text(encoding="utf8")) if path.exists() else {}


def write_state(site_id, state):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    (STATE_DIR / (site_id + ".json")).write_text(json.dumps(state, indent=2) + "\n", encoding="utf8")


def audit(runner, site, rows, jobs, allow_mismatch=False):
    solo = [p for p in rows if not p["ism"]]
    out = runner.send(site["id"] + "_t2_audit", sd.build_script(
        AUDIT_BODY, SITE=site["id"], ITEMS=[sd.slim(p) for p in solo],
        HOSTS=[(gid, len(ps)) for gid, _, ps in jobs]))
    actors = {}
    hosts = {}
    for line in out.splitlines():
        parts = line.split()
        if parts[:1] == ["T2ACT"] and len(parts) == 4:
            actors[parts[1]] = (parts[2], parts[3])
        elif parts[:1] == ["T2HOST"] and len(parts) == 5:
            hosts[parts[1]] = (parts[2], int(parts[3]), parts[4])
    mismatches = [p["id"] for p in solo if p["id"] in actors and actors[p["id"]][0] != p["asset"]]
    mismatches += [gid for gid, asset, ps in jobs if gid in hosts
                   and (hosts[gid][0] != asset or hosts[gid][1] != len(ps))]
    if mismatches and not allow_mismatch:
        raise SystemExit("existing actors differ from Tripo V2 source: " + ", ".join(mismatches))
    if not runner.args.dry_run and "T2AUDIT DONE" not in out:
        raise SystemExit("Tripo actor audit missing completion receipt")
    return actors, hosts, mismatches


def require_loaded(site_id, dry_run):
    if not dry_run and not sd.read_state(site_id).get("loaded"):
        raise SystemExit("run Tripo load and set-dress survey for %s first" % site_id)


def load_site(runner, site, rows, jobs):
    other = [p.stem for p in Path(sd.STATE_DIR).glob("*.json") if p.stem != site["id"]
             and sd.read_state(p.stem).get("loaded")]
    if other:
        raise SystemExit("unload other set-dress sites first: " + ", ".join(other))
    state = sd.read_state(site["id"])
    loaded = state.get("loaded", [])
    target_labels = ["SD_" + p["id"] for p in rows if not p["ism"]]
    target_labels += ["SD_" + gid for gid, _, _ in jobs]
    for _ in range(20):
        out = runner.send(site["id"] + "_t2_load", sd.build_script(
            LOAD_TARGETS_BODY, SITE=site["id"], ITEMS=[sd.slim(p) for p in rows],
            TARGET_LABELS=target_labels, ALREADY=loaded, LIMIT=20,
            LOAD_NEAR_ALL=bool(site.get("load_near_all"))))
        for line in out.splitlines():
            if line.startswith("T2LOADED "):
                loaded = list(dict.fromkeys(loaded + json.loads(line[9:])))
        if not runner.args.dry_run:
            state["loaded"] = loaded
            # Road markers can lie hundreds of metres outside the named site
            # radius. Keep the unload query large enough to find their GUIDs.
            base = sd.load_box(site)
            xs = [p["x_cm"] for p in rows]
            ys = [p["y_cm"] for p in rows]
            state["box"] = [min(base[0], min(xs) - 1500), min(base[1], min(ys) - 1500),
                            max(base[2], max(xs) + 1500), max(base[3], max(ys) + 1500)]
            sd.write_state(site["id"], state)
        if runner.args.dry_run or "T2LOAD " in out and " DONE" in out:
            print("T2LOAD %s pinned=%d complete" % (site["id"], len(loaded)))
            return
    raise SystemExit("Tripo targeted load exceeded 400 actors; inspect before continuing")


def unload_site(runner, site):
    state = sd.read_state(site["id"])
    loaded = state.get("loaded", [])
    box = state.get("box") or sd.load_box(site)
    for i in range(0, len(loaded), 20):
        batch = loaded[i:i + 20]
        out = runner.send(site["id"] + "_t2_unload", sd.build_script(
            sd.UNLOAD_BODY, BOX=box, WANT=batch))
        if not runner.args.dry_run:
            receipt = re.search(r"UNLOAD (\d+) of (\d+) DONE", out)
            if receipt is None or int(receipt.group(2)) != len(batch):
                raise SystemExit("Tripo unload receipt incomplete; keep loaded-state record")
            # Replaced actors retain their old GUIDs in this load record, but
            # those descriptors no longer exist after their deletion is saved.
            # The unload body unpins every descriptor that still exists.
    if not runner.args.dry_run:
        state["loaded"] = []
        sd.write_state(site["id"], state)
    print("T2UNLOAD %s actors=%d complete" % (site["id"], len(loaded)))


def invalidate_full_site_check(site_id, dry_run):
    # A Tripo-only contact report cannot certify the rest of a V2 site.
    if dry_run:
        return
    site_state = sd.read_state(site_id)
    site_state["dirty"] = True
    site_state.pop("check2", None)
    sd.write_state(site_id, site_state)


def install(runner, site, rows, jobs, state):
    actors, hosts, mismatches = audit(runner, site, rows, jobs, allow_mismatch=True)
    if mismatches:
        invalidate_full_site_check(site["id"], runner.args.dry_run)
        state["dirty"] = True
        state.pop("check", None)
        if not runner.args.dry_run:
            write_state(site["id"], state)
        out = runner.send(site["id"] + "_t2_clear", sd.build_script(
            sd.CLEAR_BODY, SITE=site["id"], ONLY=["SD_" + name for name in mismatches], LIMIT=200))
        deleted = [line.split(" ", 1)[1].strip() for line in out.splitlines() if line.startswith("CLEARPKG ")]
        if not runner.args.dry_run and len(deleted) != len(mismatches):
            raise SystemExit("Tripo fallback deletion receipt incomplete; inspect editor before retry")
        if not runner.args.dry_run:
            state["deleted_pkgs"] = sorted(set(state.get("deleted_pkgs", []) + deleted))
            write_state(site["id"], state)
        for name in mismatches:
            actors.pop(name, None)
            hosts.pop(name, None)
    solo = [p for p in rows if not p["ism"] and p["id"] not in actors]
    new_jobs = [(gid, asset, ps) for gid, asset, ps in jobs if gid not in hosts]
    print("INSTALL %s replaced=%d new_solo=%d new_ism_hosts=%d" %
          (site["id"], len(mismatches), len(solo), len(new_jobs)))
    if not solo and not new_jobs:
        return
    invalidate_full_site_check(site["id"], runner.args.dry_run)
    state["dirty"] = True
    state.pop("check", None)
    if not runner.args.dry_run:
        write_state(site["id"], state)
    for i in range(0, len(solo), sd.BATCH["place"]):
        out = runner.send(site["id"] + "_t2_place", sd.build_script(
            sd.PLACE_BODY, SITE=site["id"], ITEMS=[sd.slim(p) for p in solo[i:i + sd.BATCH["place"]]]))
        if not runner.args.dry_run and "PLACE made=" not in out:
            raise SystemExit("missing Tripo placement receipt")
    for gid, asset, ps in new_jobs:
        out = runner.send(site["id"] + "_t2_ism", sd.build_script(
            sd.ISM_BODY, SITE=site["id"], GROUP_ID=gid, ASSET=asset, FALLBACK="",
            MAT=ps[0].get("material", ""), FOLDER=ps[0]["folder"], GROUND_ONLY=True,
            ITEMS=[sd.slim(p) for p in ps]))
        if not runner.args.dry_run and ("instances=%d" % len(ps)) not in out:
            raise SystemExit("Tripo ISM instance count mismatch for " + gid)
    order = {"trace": 0, "physics": 1, "none": 3}
    solo.sort(key=lambda p: (order[p["settle"]["mode"]], p["settle"].get("drop_cm", 0), p["id"]))
    for i in range(0, len(solo), sd.BATCH["settle"]):
        runner.send(site["id"] + "_t2_settle", sd.build_script(
            sd.SETTLE_BODY, SITE=site["id"], ITEMS=[sd.slim(p) for p in solo[i:i + sd.BATCH["settle"]]],
            LATER=[p["id"] for p in solo[i + sd.BATCH["settle"]:]],
            OVERHEAD=sd.overhead_ids(site), seed=1000 + i))
    for i in range(0, len(solo), 12):
        runner.send(site["id"] + "_t2_material", sd.build_script(
            sd.MATERIAL_BODY, SITE=site["id"], ITEMS=[sd.slim(p) for p in solo[i:i + 12]],
            MAP={}, MSET=sd.MATERIAL_SETS))
    if new_jobs:
        runner.send(site["id"] + "_t2_material_ism", sd.build_script(
            MATERIAL_HOST_BODY, SITE=site["id"], HOST_IDS=[gid for gid, _, _ in new_jobs]))
    audit(runner, site, rows, jobs)


def check(runner, site, rows, jobs, state):
    actors, hosts, _ = audit(runner, site, rows, jobs)
    solo = [p for p in rows if not p["ism"]]
    if len(actors) != len(solo) or len(hosts) != len(jobs):
        raise SystemExit("Tripo placements missing; finish install before check")
    out = runner.send(site["id"] + "_t2_clearance", sd.build_script(
        TRIPO_CHECK_BODY, SITE=site["id"], ITEMS=[sd.slim(p) for p in solo],
        ROAD=sd.road_near(site), OVERHEAD=sd.overhead_ids(site),
        CLEAR_CM=sd.CLEAR_M * 100.0, TOL_CM=8.0)) if solo else "CHECK actors=0 no_mesh=0 issues=0 DONE"
    match = re.search(r"CHECK actors=(\d+) no_mesh=(\d+) issues=(\d+) DONE", out)
    if not runner.args.dry_run and not match:
        raise SystemExit("missing Tripo clearance receipt")
    issues = int(match.group(3)) if match else 0
    reports = {}
    for i in range(0, len(solo), 10):
        out = runner.send(site["id"] + "_t2_contact", sd.build_script(
            sd.CHECK2_BODY, SITE=site["id"], ITEMS=[sd.slim(p) for p in solo[i:i + 10]]))
        for line in out.splitlines():
            if line.startswith("C2 {"):
                report = ast.literal_eval(line[3:])
                reports[report["id"]] = report
    instance_reports = {}
    host_counts = {}
    for gid, _, ps in jobs:
        indexed = list(enumerate(ps))
        for i in range(0, len(indexed), sd.ISM_CHECK_BATCH):
            out = runner.send(site["id"] + "_t2_contact_ism", sd.build_script(
                sd.ISM_CHECK_BODY, SITE=site["id"], GROUP_ID=gid, EXPECTED=len(ps),
                ITEMS=[(j, sd.slim(p)) for j, p in indexed[i:i + sd.ISM_CHECK_BATCH]]))
            for line in out.splitlines():
                if line.startswith("C2IHOST {"):
                    report = ast.literal_eval(line[8:])
                    host_counts[gid] = report["count"]
                elif line.startswith("C2I {"):
                    report = ast.literal_eval(line[4:])
                    instance_reports[report["id"]] = report
    if runner.args.dry_run:
        return
    violations, _ = contact.judge(reports, {p["id"]: p for p in solo}, [])
    for p in solo:
        report = reports.get(p["id"])
        if report is None:
            violations.append((p["id"], "MISSING", "no actor contact report"))
        else:
            problem = sd.solo_scatter_gap_violation(report, p)
            if problem:
                violations.append((p["id"], problem[0], problem[1]))
    for gid, _, ps in jobs:
        if host_counts.get(gid) != len(ps):
            violations.append((gid, "ISM_COUNT", "expected %d instances" % len(ps)))
        for p in ps:
            report = instance_reports.get(p["id"])
            problem = ("MISSING", "no instance contact report") if report is None else sd.ism_gap_violation(report["gaps"], p)
            if problem:
                violations.append((p["id"], problem[0], problem[1]))
    if issues:
        violations.append((site["id"], "CLEARANCE", "%d clearance issues" % issues))
    state["check"] = {"time": time.time(), "selection": sd.selection_token(rows, True),
                      "solo": len(reports), "solo_expected": len(solo),
                      "ism": len(instance_reports), "ism_expected": sum(len(ps) for _, _, ps in jobs),
                      "hosts": len(host_counts), "hosts_expected": len(jobs),
                      "violations": [list(v) for v in violations]}
    state["dirty"] = bool(violations)
    write_state(site["id"], state)
    for violation in violations:
        print("VIOLATION", *violation)
    print("T2CHECK solo=%d/%d ism=%d/%d hosts=%d/%d violations=%d" %
          (len(reports), len(solo), len(instance_reports), sum(len(ps) for _, _, ps in jobs),
           len(host_counts), len(jobs), len(violations)))
    if violations:
        raise SystemExit("Tripo contact/clearance check failed; do not save this site")


def save(runner, site, rows, jobs, state):
    checked = state.get("check") or {}
    if (state.get("dirty", True) or checked.get("selection") != sd.selection_token(rows, True)
            or checked.get("violations") or checked.get("solo") != checked.get("solo_expected")
            or checked.get("ism") != checked.get("ism_expected")
            or checked.get("hosts") != checked.get("hosts_expected")):
        raise SystemExit("run a clean Tripo check on the current source before saving")
    actors, hosts, _ = audit(runner, site, rows, jobs)
    if len(actors) != sum(not p["ism"] for p in rows) or len(hosts) != len(jobs):
        raise SystemExit("Tripo actor readback incomplete before save")
    labels = ["SD_" + p["id"] for p in rows if not p["ism"]] + ["SD_" + gid for gid, _, _ in jobs]
    for i in range(0, len(labels), sd.BATCH["save"]):
        batch = labels[i:i + sd.BATCH["save"]]
        out = runner.send(site["id"] + "_t2_save", sd.build_script(
            SAVE_TARGETS_BODY, SITE=site["id"], LABELS=batch))
        receipt = "T2SAVE count=%d expected=%d ok=True DONE" % (len(batch), len(batch))
        if not runner.args.dry_run and receipt not in out:
            raise SystemExit("missing or failed Tripo package-save receipt; keep editor loaded")
    deletions = state.get("deleted_pkgs", [])
    if runner.args.only_id:
        package = runner.args.delete_package
        if not package or package not in deletions:
            raise SystemExit("partial save requires --delete-package matching a pending fallback package")
        deletions = [package]
    for package in deletions:
        out = runner.send(site["id"] + "_t2_delete_save", sd.build_script(
            sd.SAVE_BODY, SITE=site["id"], OFFSET=100000, LIMIT=0, DELETED=[package]))
        if not runner.args.dry_run:
            sd.save_receipt(out, deleted=1)
    if not runner.args.dry_run:
        deleted_history = sorted(set((state.get("saved") or {}).get("deleted_packages", [])
                                     + deletions))
        state["saved"] = {"time": time.time(), "selection": checked["selection"],
                          "actor_packages": {p["id"]: actors[p["id"]][1] for p in rows if not p["ism"]},
                          "host_packages": {gid: hosts[gid][2] for gid, _, _ in jobs},
                          "deleted_packages": deleted_history}
        state["deleted_pkgs"] = sorted(set(state.get("deleted_pkgs", [])) - set(deletions))
        write_state(site["id"], state)
    print("T2SAVE %s labels=%d complete" % (site["id"], len(labels)))


def verify(runner, site, rows, jobs, state):
    saved = state.get("saved") or {}
    if saved.get("selection") != sd.selection_token(rows, True):
        raise SystemExit("no save receipt for the current Tripo source")
    actors, hosts, _ = audit(runner, site, rows, jobs)
    packages = [actors[p["id"]][1] for p in rows if not p["ism"] and p["id"] in actors]
    packages += [hosts[gid][2] for gid, _, _ in jobs if gid in hosts]
    if len(packages) != sum(not p["ism"] for p in rows) + len(jobs):
        raise SystemExit("Tripo package readback count differs from plan")
    missing = [name for name in packages if not (ROOT / "Content" / (name[6:] + ".uasset")).is_file()]
    if missing:
        raise SystemExit("saved actor package files missing: " + ", ".join(missing))
    expected = [(actors[p["id"]][1], p["asset"].rsplit("/", 1)[-1])
                for p in rows if not p["ism"]]
    expected += [(hosts[gid][2], asset.rsplit("/", 1)[-1]) for gid, asset, _ in jobs]
    unsaved_refs = [package for package, mesh in expected
                    if mesh.encode("ascii") not in (ROOT / "Content" / (package[6:] + ".uasset")).read_bytes()]
    if unsaved_refs:
        raise SystemExit("saved actor packages lack Tripo mesh references: " + ", ".join(unsaved_refs))
    print("T2VERIFY %s actors=%d hosts=%d instances=%d saved_packages=%d" %
          (site["id"], len(actors), len(hosts), sum(len(ps) for _, _, ps in jobs), len(packages)))


def capture_extra(runner, site, rows):
    if not site.get("load_near_all"):
        raise SystemExit("capture-extra is only for standalone Tripo candidates")
    p = rows[0]
    distance = max(2400.0, max(p["size_m"][:2]) * 230.0)
    cam = [p["x_cm"] + distance * .85, p["y_cm"] + distance * .65,
           p["ground_z_cm"] + distance * .6]
    look = [p["x_cm"], p["y_cm"], p["ground_z_cm"] + p["size_m"][2] * 55.0]
    label = "SD_CAPTURE_" + site["id"]
    setup = sd.build_script(sd.CAPTURE_SHOOT_BODY, CAM=cam, LOOK=look,
                            LABEL=label, SIZE=[1400, 900], FOV=55.0)
    export = sd.build_script(sd.CAPTURE_EXPORT_BODY,
                             OUT_REL="Screenshots/TripoExtras/" + site["id"],
                             LABEL=label, NAME="overview")
    if runner.args.dry_run:
        runner.send(site["id"] + "_t2_capture", setup)
        runner.send(site["id"] + "_t2_export", export)
        return
    sys.path.insert(0, str(ROOT / "Tools" / "Look"))
    import capture_look
    if sd.editor_minimized():
        raise SystemExit("visible editor needed for standalone visual capture")
    ok, out, err = capture_look.run_capture_scripts(
        setup, capture_look.PUMP_SCRIPT.replace("__LABEL__", label), export,
        sd.CAPTURE_SETTLE_S, True, capture_label=label)
    print(out)
    if not ok:
        raise SystemExit(err or "standalone visual capture failed")
    print("T2CAPTURE Saved/Screenshots/TripoExtras/" + site["id"] + "/overview.png")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("step", choices=["plan", "load", "audit", "install", "check", "save", "verify", "unload", "capture-extra"])
    parser.add_argument("site", nargs="?")
    parser.add_argument("--owner", default=os.environ.get("SETDRESS_OWNER", ""))
    parser.add_argument("--port", type=int, default=int(os.environ.get("HAYBA_PORT", "52342")))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--only-id", help="work on one approved solo placement in this site")
    parser.add_argument("--delete-package", help="exact pending fallback package for --only-id save")
    args = parser.parse_args()
    args.no_gate_check = False
    doc = sd.load_doc(True)
    if args.step == "plan":
        plan(doc)
        return
    if not args.site:
        raise SystemExit("provide a site ID after the step")
    site = extra_site(args.site, doc) if args.site in EXTRA_CANDIDATES else sd.site_of(doc, args.site)
    rows = selected(site, args.only_id)
    if not rows:
        raise SystemExit("no approved Tripo placements in " + site["id"])
    jobs = canonical_jobs(site, rows)
    if args.step in ("load", "install", "save", "unload"):
        sd.gate_check(args, {"load": "load", "install": "place", "save": "save", "unload": "unload"}[args.step])
    if args.step in ("install", "check", "save", "verify", "capture-extra"):
        require_loaded(site["id"], args.dry_run)
    runner = sd.Runner(args)
    state = read_state(site["id"])
    if args.step == "load":
        load_site(runner, site, rows, jobs)
    elif args.step == "unload":
        unload_site(runner, site)
    elif args.step == "audit":
        audit(runner, site, rows, jobs, allow_mismatch=True)
    elif args.step == "install":
        install(runner, site, rows, jobs, state)
    elif args.step == "check":
        check(runner, site, rows, jobs, state)
    elif args.step == "save":
        save(runner, site, rows, jobs, state)
    elif args.step == "capture-extra":
        capture_extra(runner, site, rows)
    else:
        verify(runner, site, rows, jobs, state)


if __name__ == "__main__":
    main()
