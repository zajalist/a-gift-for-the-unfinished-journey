"""Prepare a small, read-only contact investigation at screenshot candidate sites.

No editor connection, actor loading, placement, correction or saving occurs here.
The source layout identifies candidates; only returned live identities/contacts
can establish which screenshot object is affected.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from prepare_ground_contact_loading import QUERY
from prepare_ground_contact_survey import COMMON, checked, file_info

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "Saved/GroundContactSurvey/float_followup_20261001_v1"
SITES = {
    "S09_CaravanRoute": {
        "images": ["2946b540-6643-452b-ab25-345c947f7765", "2fee4c82-a550-4dcd-be3a-562618596512"],
        "reason": "Marker with crosspieces, two jute-bag bundles and eight dead shrubs; strongest source candidate, not an established screenshot identity.",
    },
    "L10_FootFarm": {
        "images": ["b0e5d2c2-11fb-41c9-820a-54906b8f9681"],
        "reason": "Roofed annex beside a wooden pen and fences; candidate for the fenced scene, not an established screenshot identity.",
    },
}

CATALOG = COMMON + r'''
site = __SITE__
centre = __CENTRE__
after = __AFTER__
prefix = 'SD_' + site
site_actors = [a for a in actors if a.get_actor_label().startswith(prefix + '_') or prefix in [str(t) for t in a.tags]]
if len(site_actors) > 64:
    raise RuntimeError('Site exceeds64 loaded actors; refine the explicit scope')
components = []
for actor in site_actors:
    if expired():
        raise RuntimeError('Site inventory exceeded3.5-second budget; no partial acceptance')
    for comp in actor.get_components_by_class(unreal.StaticMeshComponent):
        if comp.static_mesh is not None:
            components.append((path(comp), actor, comp))
components.sort(key=lambda row: row[0])
if len(components) > 2048:
    raise RuntimeError('Site exceeds2048 mesh components; refine the scope')
if after and after not in [row[0] for row in components]:
    raise RuntimeError('Continuation component disappeared; recatalog loaded set')
pending = [row for row in components if row[0] > after]
rows, used_samples = [], 0
last = after
for component_path, actor, comp in pending[:6]:
    if expired():
        raise RuntimeError('Site inventory exceeded3.5-second budget; no partial acceptance')
    mesh = comp.static_mesh
    is_gpu = comp.get_class().get_name() == 'PCGProceduralISMComponent'
    is_ism = isinstance(comp, unreal.InstancedStaticMeshComponent)
    count = comp.get_num_instances() if is_gpu else comp.get_instance_count() if is_ism else 1
    limit = min(count, 8, 16 - used_samples)
    if not is_gpu and count > 0 and limit < 1:
        break
    samples = []
    if not is_gpu:
        for index in range(limit):
            instance = index if is_ism else None
            pose = instance_pose(comp, instance)
            samples.append({'instance': instance, 'transform': pose.export_text(),
                            'pivot': vec(pose.transform_location(unreal.Vector()))})
    used_samples += len(samples)
    bb = mesh.get_bounding_box()
    row = {'component': component_path, 'component_class': comp.get_class().get_name(),
           'actor': path(actor), 'package': actor.get_package().get_name(),
           'label': actor.get_actor_label(), 'actor_class': actor.get_class().get_name(),
           'mesh': path(mesh), 'mesh_bounds': [vec(bb.min), vec(bb.max)],
           'visible': comp.is_visible(), 'hidden_in_game': comp.get_editor_property('hidden_in_game'),
           'collision': str(comp.get_collision_enabled()),
           'evaluate_wpo': comp.get_editor_property('evaluate_world_position_offset'),
           'wpo_disable_cm': comp.get_editor_property('world_position_offset_disable_distance'),
           'materials': [path(comp.get_material(i)) for i in range(min(comp.get_num_materials(), 4))],
           'materials_truncated': comp.get_num_materials() > 4,
           'instanced': is_ism, 'instance_count': count, 'samples': samples,
           'samples_truncated': count > len(samples),
           'gpu_only': is_gpu}
    # Keep the result well below the native stdout limit without losing a cursor.
    if len(json.dumps(rows + [row], separators=(',', ':'))) > 18000:
        if not rows:
            raise RuntimeError('One component exceeds output budget; refine the scope')
        break
    rows.append(row)
    last = component_path
landscape = []
for actor in actors:
    if isinstance(actor, unreal.LandscapeProxy):
        origin, extent = actor.get_actor_bounds(False)
        if abs(origin.x - centre[0]) <= extent.x + 4000 and abs(origin.y - centre[1]) <= extent.y + 4000:
            landscape.append({'actor': path(actor), 'label': actor.get_actor_label(),
                              'package': actor.get_package().get_name(),
                              'transform': actor.get_actor_transform().export_text(),
                              'collision_mip': actor.get_editor_property('collision_mip_level'),
                              'simple_collision_mip': actor.get_editor_property('simple_collision_mip_level')})
if len(landscape) > 8:
    raise RuntimeError('Unexpected landscape scope; refine the site')
print('FLOAT_SITE_CATALOG ' + json.dumps({'schema': 1, 'utc': started.isoformat(),
      'world': path(world), 'site': site, 'candidate_image_identity_only': True,
      'source_centre_cm': centre, 'site_actor_count_loaded': len(site_actors),
      'loaded_labels': sorted(a.get_actor_label() for a in site_actors),
      'component_count': len(components), 'after_component': after,
      'next_after_component': last if any(row[0] > last for row in components) else None,
      'rows': rows, 'landscape': landscape,
      'contact_measured': False, 'bounds_and_pivots_are_not_contact_proof': True,
      'gpu_instances_require_separate_native_render_evidence': True}, separators=(',', ':')))
'''


def site_source(site_id: str) -> dict:
    if site_id not in SITES:
        raise ValueError("Only the two explicit screenshot candidate sites are in scope")
    source = json.loads((ROOT / "Tools/World/setdress_sites.json").read_text(encoding="utf-8"))
    site = next(row for row in source["sites"] if row["id"] == site_id)
    return site


def catalog_script(site_id: str, after: str = "") -> str:
    site = site_source(site_id)
    return checked(CATALOG.replace("__SITE__", repr(site_id))
                   .replace("__CENTRE__", repr(site["centre_cm"]))
                   .replace("__AFTER__", repr(after)))


def descriptor_script(site_id: str) -> str:
    site = site_source(site_id)
    # A35m region is large enough for each authored vignette. Truncation must be
    # resolved before selecting/loading; it never means absent objects are clear.
    script = QUERY.replace("__CENTRE__", repr(site["centre_cm"]))
    script = script.replace("__RADIUS__", "3500.0").replace("__CONTACT_ONLY__", "True")
    script = script.replace("len(rows)>100", "len(rows)>24").replace("rows[:100]", "rows[:24]")
    return checked(script)


def prepare(out: Path = OUT, site_id: str | None = None, after: str = "") -> dict:
    out.mkdir(parents=True, exist_ok=True)
    scripts, candidates = [], []
    for sid in [site_id] if site_id else SITES:
        site = site_source(sid)
        if not after:
            target = out / f"00_descriptors_{sid}.py"
            target.write_text(descriptor_script(sid), encoding="utf-8")
            scripts.append(file_info(target))
        suffix = "_" + hashlib.sha256(after.encode()).hexdigest()[:10] if after else ""
        target = out / f"10_loaded_{sid}{suffix}.py"
        target.write_text(catalog_script(sid, after), encoding="utf-8")
        scripts.append(file_info(target))
        candidates.append(dict(SITES[sid], site=sid, road_m=site["road_m"], centre_cm=site["centre_cm"],
            authored_items=[{key: p[key] for key in ("id", "key", "asset", "kind", "ism", "group")}
                            for p in site["placements"]]))
    manifest = {"schema": 1, "editor_executed": False, "scripts": scripts, "candidates": candidates,
                "source": file_info(ROOT / "Tools/World/setdress_sites.json"),
                "constraints": ["Read only; root owns editor, loading, contact measurement and any correction.",
                    "No loaded actor does not mean no saved actor. Query descriptors first.",
                    "A completed catalog is not terrain contact acceptance.",
                    "Current full render geometry/current landscape needed before moving objects.",
                    "Do not regenerate existing ISM/PCG hosts or load all site dependencies blindly."]}
    name = "manifest.json" if not after else "continuation_" + hashlib.sha256(after.encode()).hexdigest()[:10] + ".json"
    (out / name).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", choices=SITES)
    parser.add_argument("--after-component", default="")
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    if args.after_component and not args.site:
        parser.error("Continuation needs one exact site")
    result = prepare(args.out, args.site, args.after_component)
    print(json.dumps({"scripts": [r["path"] for r in result["scripts"]], "editor_executed": False}, indent=2))


if __name__ == "__main__":
    main()
