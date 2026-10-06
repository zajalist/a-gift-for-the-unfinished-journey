"""Stage bounded, read-only Unreal Python surveys; never connect to the editor.

Catalog loaded static props and ISM/HISM/PCG components, then measure at most two
explicit samples against current landscape collision. Bounds are diagnostics,
not mesh support points and never an automatic placement prescription.
"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "Saved/GroundContactSurvey"
ANCHORS = {
    "crest_approx": [494665.618, 321335.133, -29635.187],
    "quarry_approx": [413558.739, 351325.047, -39891.485],
    "descent_carts_historical": [467661.41, 321615.8, -37024.33],
}

COMMON = r'''import unreal, json, datetime
es = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
if es.get_game_world() is not None:
    raise RuntimeError('Stop PIE before this editor-world survey')
world = es.get_editor_world()
if world is None or world.get_name() != 'Saskarta_WP':
    raise RuntimeError('Expected loaded Saskarta_WP editor world')
started = datetime.datetime.now(datetime.timezone.utc)
def expired():
    return (datetime.datetime.now(datetime.timezone.utc) - started).total_seconds() > 3.5
def vec(p):
    return [round(p.x, 4), round(p.y, 4), round(p.z, 4)]
def path(obj):
    return obj.get_path_name() if obj is not None else None
def identity(obj):
    return {'path': path(obj), 'class': path(obj.get_class()),
            'package': obj.get_package().get_name()}
def props(comp):
    return {'visible': comp.is_visible(),
            'hidden_in_game': comp.get_editor_property('hidden_in_game'),
            'collision': str(comp.get_collision_enabled()),
            'evaluate_wpo': comp.get_editor_property('evaluate_world_position_offset'),
            'wpo_disable_cm': comp.get_editor_property('world_position_offset_disable_distance'),
            'materials': [path(comp.get_material(i)) for i in range(comp.get_num_materials())]}
def instance_pose(comp, index):
    return comp.get_world_transform() if index is None else comp.get_instance_transform(index, True)
actors = sorted(unreal.EditorLevelLibrary.get_all_level_actors(), key=lambda a: a.get_path_name())
'''

CATALOG = COMMON + r'''
centre = unreal.Vector(*__CENTRE__)
radius = __RADIUS__
offset = __OFFSET__
after_component = __AFTER__
rows, pcg, omitted, landscape, caches, gpu_only = [], [], [], [], [], []
scanned, mesh_scanned, next_actor = 0, 0, None
last_component = None
ai = offset - 1
skip = ('Niagara', 'Emitter', 'Camera', 'SkyAtmosphere', 'SkyLight', 'Fog', 'VolumetricCloud')
for ai in range(offset, min(len(actors), offset + 500)):
    actor = actors[ai]
    last_component = None
    if expired() or len(rows) >= 60 or mesh_scanned >= 1500:
        next_actor = ai
        break
    scanned += 1
    cname = actor.get_class().get_name()
    label = actor.get_actor_label()
    if isinstance(actor, unreal.LandscapeProxy):
        landscape.append(dict(identity(actor), transform=actor.get_actor_transform().export_text(),
              collision_mip=actor.get_editor_property('collision_mip_level'),
              simple_collision_mip=actor.get_editor_property('simple_collision_mip_level'),
              material=path(actor.get_editor_property('landscape_material'))))
    if cname == 'PCGWorldActor':
        cache = actor.get_editor_property('landscape_cache_object')
        caches.append(dict(identity(actor), cache=path(cache),
              serialization_mode=str(cache.get_editor_property('serialization_mode')) if cache else None,
              cooked_contents=str(cache.get_editor_property('cooked_serialized_contents')) if cache else None))
    if any(term in cname for term in skip) or any(term in label for term in ('StormDust', 'DustDevil', 'CameraRig', 'SkySphere')):
        omitted.append(path(actor))
        continue
    for comp in actor.get_components_by_class(unreal.PCGComponent):
        graph = comp.get_graph()
        pcg.append(dict(identity(comp), graph=path(graph),
                        generation_trigger=str(comp.get_editor_property('generation_trigger'))))
    for comp in sorted(actor.get_components_by_class(unreal.StaticMeshComponent), key=lambda c: c.get_path_name()):
        if ai == offset and after_component and path(comp) <= after_component:
            continue
        if expired() or mesh_scanned >= 1500:
            next_actor = ai
            break
        last_component = path(comp)
        mesh_scanned += 1
        mesh = comp.static_mesh
        if mesh is None:
            continue
        if comp.get_class().get_name() == 'PCGProceduralISMComponent':
            gpu_only.append(dict(identity(comp), owner=identity(actor), mesh=path(mesh),
                                 count=comp.get_num_instances(), properties=props(comp),
                                 status='GPU transforms unavailable to this CPU survey'))
            continue
        samples = []
        is_ism = isinstance(comp, unreal.InstancedStaticMeshComponent)
        if is_ism:
            ids = comp.get_instances_overlapping_sphere(centre, radius, True)
            count = len(ids)
            for index in sorted(ids)[:8]:
                pose = instance_pose(comp, index)
                samples.append({'instance': index, 'transform': pose.export_text(),
                                'pivot': vec(pose.transform_location(unreal.Vector()))})
        else:
            pose = instance_pose(comp, None)
            bounds = mesh.get_bounding_box()
            p = pose.transform_location((bounds.min + bounds.max) * .5)
            count = int((p - centre).length() <= radius)
            if count:
                samples.append({'instance': None, 'transform': pose.export_text(),
                                'pivot': vec(pose.transform_location(unreal.Vector()))})
        if not count:
            continue
        bb = mesh.get_bounding_box()
        rows.append(dict(identity(comp), owner=identity(actor), label=label,
                         tags=[str(t) for t in actor.tags], mesh=path(mesh),
                         mesh_bounds=[vec(bb.min), vec(bb.max)], properties=props(comp),
                         instanced=is_ism, near_count=count, samples=samples,
                         samples_truncated=count > len(samples),
                         hlod_candidate='HLOD' in cname or '/HLOD/' in mesh.get_path_name()))
        if len(rows) >= 60 or expired():
            next_actor = ai
            break
    if next_actor is not None:
        break
if next_actor is None and offset + scanned < len(actors):
    next_actor = offset + scanned
print('GROUND_CATALOG ' + json.dumps({'schema': 1, 'utc': started.isoformat(),
      'world': path(world), 'anchor_is_approximate': True, 'centre': vec(centre),
      'radius_cm': radius, 'actor_offset': offset, 'actor_count_loaded': len(actors),
      'actors_scanned': scanned, 'mesh_components_scanned': mesh_scanned,
      'next_actor_offset': next_actor, 'repeat_boundary_actor_and_deduplicate': True,
      'after_component': last_component if next_actor == ai else None,
      'rows': rows, 'pcg': pcg[:100], 'landscape': landscape[:64], 'pcg_caches': caches,
      'gpu_only': gpu_only[:60],
      'omitted_effects': omitted[:50]}, separators=(',', ':')))
'''

MEASURE = COMMON + r'''
selected = __SELECTED__
if len(selected) > 2:
    raise RuntimeError('At most two explicit mesh samples per call')
want = {r['component'] for r in selected}
found = {}
for actor in actors:
    for comp in actor.get_components_by_class(unreal.StaticMeshComponent):
        if path(comp) in want:
            found[path(comp)] = comp
trace_count = 0
def hit_below(p, owner, above):
    global trace_count
    ignored, chain = [owner], []
    for layer in range(6):
        if expired() or trace_count >= 120:
            return {'status': 'budget', 'hits': chain}
        trace_count += 1
        raw = unreal.SystemLibrary.line_trace_single(world,
              unreal.Vector(p.x, p.y, above), unreal.Vector(p.x, p.y, p.z - 20000.),
              unreal.TraceTypeQuery.TRACE_TYPE_QUERY1, True, ignored,
              unreal.DrawDebugTrace.NONE, True)
        if isinstance(raw, tuple) and len(raw) == 2 and not isinstance(raw[0], unreal.HitResult):
            raw = raw[1] if raw[0] else None
        if raw is None or not raw.to_tuple()[0]:
            return {'status': 'no_landscape_hit', 'hits': chain}
        data = raw.to_tuple()
        point, normal, hit_actor = data[5], data[7], data[9]
        if hit_actor is None:
            return {'status': 'unresolved_hit', 'hits': chain}
        ground = 'Landscape' in hit_actor.get_class().get_name()
        chain.append(dict(identity(hit_actor), point=vec(point), normal=vec(normal),
                          clearance_cm=round(p.z - point.z, 4), landscape=ground))
        if ground:
            return {'status': 'landscape', 'hits': chain}
        ignored.append(hit_actor)
    return {'status': 'occluder_limit', 'hits': chain}
rows = []
for item in selected:
    comp = found.get(item['component'])
    if comp is None:
        rows.append({'selected': item, 'status': 'not_loaded'})
        continue
    mesh = comp.static_mesh
    index = item['instance']
    if comp.get_class().get_name() == 'PCGProceduralISMComponent':
        rows.append({'selected': item, 'status': 'gpu_only_no_cpu_pose'})
        continue
    if mesh is None or path(mesh) != item['mesh']:
        rows.append({'selected': item, 'status': 'mesh_changed'})
        continue
    if index is not None and (not isinstance(comp, unreal.InstancedStaticMeshComponent) or index < 0 or index >= comp.get_instance_count()):
        rows.append({'selected': item, 'status': 'instance_changed'})
        continue
    pose = instance_pose(comp, index)
    if pose.export_text() != item['transform']:
        rows.append({'selected': item, 'status': 'transform_changed_recatalog'})
        continue
    bb = mesh.get_bounding_box()
    lo, hi = bb.min, bb.max
    local = [('pivot', unreal.Vector()), ('bounds_base_centre', unreal.Vector((lo.x+hi.x)*.5, (lo.y+hi.y)*.5, lo.z))]
    for x in (lo.x, hi.x):
        for y in (lo.y, hi.y):
            for z in (lo.z, hi.z):
                local.append(('bounds_corner', unreal.Vector(x, y, z)))
    if 'local_contacts' in item:
        local = [('authored_contact', unreal.Vector(*p)) for p in item['local_contacts']]
    points = [(name, pose.transform_location(p)) for name, p in local]
    above = max(p.z for _, p in points) + 2000.
    samples = []
    for name, p in points:
        samples.append({'kind': name, 'point': vec(p), 'down': hit_below(p, comp.get_owner(), above)})
    rows.append({'selected': item, 'status': 'measured', 'owner': identity(comp.get_owner()),
                 'properties': props(comp), 'samples': samples,
                 'support_caveat': 'Own actor omitted, including sibling components and own ISM supports; noncolliding supports are unobservable'})
print('GROUND_MEASURE ' + json.dumps({'schema': 1, 'utc': started.isoformat(),
      'world': path(world), 'trace_count': trace_count, 'rows': rows,
      'bounds_are_not_contact_vertices': True, 'heightmap_fallback': False}, separators=(',', ':')))
'''


def checked(script: str) -> str:
    ast.parse(script)
    # Same conservative scanner used by existing project editor scripts.
    for word in ("try", "getattr", "import time", "open(", ".replace(", "new_level("):
        if word in script:
            raise ValueError(f"Editor policy token {word!r}")
    for word in ("set_editor_property", "set_actor_", "update_instance", "save_asset", "load_asset", "generate_local", "destroy_actor"):
        if word in script:
            raise ValueError(f"Survey must be read-only: {word}")
    return script


def catalog_script(centre, radius=12000, offset=0, after_component=None):
    if not 100 <= radius <= 25000 or offset < 0:
        raise ValueError("Radius must be 100..25000cm; offset must be nonnegative")
    return checked(CATALOG.replace("__CENTRE__", repr(centre)).replace("__RADIUS__", str(radius)).replace("__OFFSET__", str(offset)).replace("__AFTER__", repr(after_component)))


def measure_script(selected):
    if not 1 <= len(selected) <= 2:
        raise ValueError("Select one or two samples from the current catalog")
    required = {"component", "mesh", "instance", "transform"}
    if any(not required <= set(row) or set(row) - required - {"local_contacts"} for row in selected):
        raise ValueError(f"Each selection needs {sorted(required)} and optional local_contacts")
    for row in selected:
        if "local_contacts" in row:
            points = row["local_contacts"]
            if not 1 <= len(points) <= 10 or any(len(p) != 3 or not all(isinstance(v, (float, int)) and math.isfinite(v) for v in p) for p in points):
                raise ValueError("Supply1..10 finite mesh-local contact coordinates")
    return checked(MEASURE.replace("__SELECTED__", repr(selected)))


def file_info(file: Path):
    with file.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": str(file.resolve()), "bytes": file.stat().st_size,
            "mtime_utc": datetime.fromtimestamp(file.stat().st_mtime, timezone.utc).isoformat(),
            "sha256": digest}


def fingerprint_packages(result):
    """Fingerprint saved project packages referenced in an exported JSON result."""
    packages = set()
    def visit(value):
        if isinstance(value, dict):
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, str) and value.startswith("/Game/"):
            packages.add(value.split(".", 1)[0].split(":", 1)[0])
    visit(result)
    if len(packages) > 200:
        raise ValueError("Fingerprint one bounded result at a time (max200 packages)")
    rows = []
    for package in sorted(packages):
        stem = ROOT / "Content" / package.removeprefix("/Game/")
        if not stem.resolve().is_relative_to((ROOT / "Content").resolve()):
            raise ValueError("Package escaped Content")
        files = [stem.with_suffix(suffix) for suffix in (".uasset", ".umap", ".uexp", ".ubulk")]
        rows.append({"package": package, "saved_files": [file_info(f) for f in files if f.is_file()]})
    return {"utc": datetime.now(timezone.utc).isoformat(), "packages": rows,
            "unsaved_editor_changes_are_not_represented": True}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--anchor", choices=ANCHORS, default="quarry_approx")
    ap.add_argument("--radius-cm", type=float, default=12000)
    ap.add_argument("--actor-offset", type=int, default=0)
    ap.add_argument("--after-component", help="Resume boundary actor after this catalog component path")
    ap.add_argument("--select", type=Path, help="JSON array of exact catalog samples")
    ap.add_argument("--fingerprint", type=Path, help="Fingerprint saved packages in a result JSON; no editor access")
    ap.add_argument("--write", action="store_true", help="Write scripts only, never send")
    args = ap.parse_args()
    if args.fingerprint:
        result = fingerprint_packages(json.loads(args.fingerprint.read_text(encoding="utf-8")))
        destination = args.fingerprint.with_suffix(".packages.json")
        destination.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(destination)
        return
    script = measure_script(json.loads(args.select.read_text(encoding="utf-8"))) if args.select else catalog_script(ANCHORS[args.anchor], args.radius_cm, args.actor_offset, args.after_component)
    name = "measure.py" if args.select else f"catalog_{args.anchor}_{args.actor_offset}.py"
    if not args.write:
        print(script)
        return
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / name
    target.write_text(script, encoding="utf-8")
    evidence_dir = ROOT / "Saved/Verification/playtest_feedback_20261001"
    evidence = [file_info(p) for p in sorted(evidence_dir.glob("*")) if p.is_file()]
    manifest = {"prepared_utc": datetime.now(timezone.utc).isoformat(), "script": file_info(target),
                "anchors_are_approximate_not_image_poses": ANCHORS, "evidence": evidence,
                "editor_executed": False}
    (OUT / f"{target.stem}.manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()
