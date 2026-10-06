"""Offline, actor-scoped repair proposal for the two worst ruin silhouettes.

This does not edit the level. Run ``plan`` before the editor pass, inspect the
live four-angle captures, then use ``emit`` to prepare a guarded Unreal script.
The emitted script requires the exact old actors to be loaded and refuses a
changed GUID, package, mesh, or bounds. It deliberately does not save: the
editor owner must visually approve and save only the reported actor packages.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Tools" / "Story"))
from build_road_profile import HEIGHTMAP, Terrain  # noqa: E402

DESCS = ROOT / "Saved" / "Grounding" / "descs.json"
OUT = ROOT / "Saved" / "Verification" / "world_placement"
TRIPO = "/Game/SaskartaGaea/Environment/Tripo02/SM_T2_"
O05_PREFIX = "SD_O05_CliffDwellings_"
S10_PREFIX = "SD_S10_CrestFort_v2_"
S10_REMOVE = ("002", "015", "032", "054", "109", "200")

# A 20-actor assemblage climbs a 53–62 degree face. The optional rope bridge
# was never saved, and the old jar rack is actually a B01 tank. Replace the
# whole unsupported assemblage with two complete existing Tripo buildings on
# independently measured ridge shelves, not 20 individually lowered props.
O05_NEW = (
    {"label": "WF_O05_CrestCollapsed", "mesh": TRIPO + "mudbrick_house_collapsed",
     "x_cm": 638900.0, "y_cm": 530400.0, "yaw": 130.0,
     "size_cm": (800.02, 752.89, 455.70)},
    {"label": "WF_O05_CrestHut", "mesh": TRIPO + "stone_hut",
     "x_cm": 640700.0, "y_cm": 529800.0, "yaw": 250.0,
     "size_cm": (600.03, 475.60, 424.17)},
)


def package_file(package: str) -> Path:
    assert package.startswith("/Game/__ExternalActors__/level/Saskarta_WP/")
    return ROOT / "Content" / (package[6:] + ".uasset")


def mesh_refs(blob: bytes) -> list[str]:
    refs = re.findall(rb"/Game/(?:SaskartaGaea|AshesOfBazaar|MedievalVillage)/[^\x00-\x1f ]+", blob)
    return sorted(set(x.decode("ascii").rstrip(".") for x in refs if b"/SM_" in x))


def saved_actor(row: list) -> dict:
    guid, _, _, label, *rest = row
    package = row[-1]
    path = package_file(package)
    blob = path.read_bytes()
    assert label.encode() in blob, (label, "package label mismatch")
    refs = mesh_refs(blob)
    assert len(refs) == 1, (label, refs)
    return {"label": label, "guid": guid, "object_path": row[-2],
            "package": package, "file": str(path.relative_to(ROOT)).replace("\\", "/"),
            "sha256": hashlib.sha256(blob).hexdigest(), "mesh": refs[0],
            "bounds_cm": [round(float(v), 2) for v in row[4:10]]}


def footprint(terrain: Terrain, entry: dict) -> dict:
    x, y, yaw = entry["x_cm"], entry["y_cm"], math.radians(entry["yaw"])
    hx, hy = entry["size_cm"][0] / 2, entry["size_cm"][1] / 2
    c, s = math.cos(yaw), math.sin(yaw)
    heights = [float(terrain.height(x + u * c - v * s, y + u * s + v * c) * 100)
               for u in (-hx, -hx / 2, 0, hx / 2, hx)
               for v in (-hy, -hy / 2, 0, hy / 2, hy)]
    low, high = min(heights), max(heights)
    # Bottom-centred pivots were verified on import. Embed the lowest edge by
    # 2 cm so no part of the footprint reads as detached; high edge burial is
    # bounded by the relief, which is checked below.
    base_z = low - 2.0
    return {"ground_min_cm": round(low, 1), "ground_max_cm": round(high, 1),
            "relief_cm": round(high - low, 1), "base_z_cm": round(base_z, 1),
            "max_above_ground_cm": round(base_z - low, 1),
            "max_burial_cm": round(high - base_z, 1)}


def road_visibility(terrain: Terrain, entry: dict) -> dict:
    start = (616579.6, 463550.0)
    eye = float(terrain.height(*start)) + 1.7
    x, y = entry["x_cm"], entry["y_cm"]
    top = entry["base_z_cm"] / 100 + entry["size_cm"][2] / 100
    margins = []
    for i in range(1, 100):
        f = i / 100
        ray = eye + (top - eye) * f
        ground = float(terrain.height(start[0] + (x - start[0]) * f,
                                      start[1] + (y - start[1]) * f))
        margins.append(ray - ground)
    return {"distance_from_start_m": round(math.hypot(x - start[0], y - start[1]) / 100, 1),
            "minimum_clearance_m": round(min(margins), 2)}


def build_plan() -> dict:
    rows = json.loads(DESCS.read_text(encoding="utf8"))
    o05 = sorted((saved_actor(r) for r in rows if r[3].startswith(O05_PREFIX)),
                 key=lambda a: a["label"])
    s10 = sorted((saved_actor(r) for r in rows if r[3] in
                  {S10_PREFIX + s for s in S10_REMOVE}), key=lambda a: a["label"])
    assert len(o05) == 20 and len(s10) == len(S10_REMOVE)
    assert not any("Tripo02" in a["mesh"] for a in o05), "a convincing Tripo asset would be removed"
    assert all(a["mesh"].endswith("/SM_B01_wall01") for a in s10)
    terrain = Terrain(HEIGHTMAP)
    new = []
    for src in O05_NEW:
        p = dict(src)
        p.update(footprint(terrain, p))
        p.update(road_visibility(terrain, p))
        assert p["relief_cm"] < 75, p
        assert p["minimum_clearance_m"] > 0, p
        new.append(p)
    spacing = math.hypot(new[0]["x_cm"] - new[1]["x_cm"],
                         new[0]["y_cm"] - new[1]["y_cm"])
    assert spacing > sum(math.hypot(*p["size_cm"][:2]) / 2 for p in new) + 300
    return {"basis": "Saved/Grounding/descs.json, saved actor package bytes, Current_u16.png",
            "live_unknowns": ["actor-desc snapshot may be stale; compare current loaded GUID, package, mesh, bounds",
                              "capture O05 and S10 from four distinct daytime/driving angles before apply",
                              "live landscape traces and collision with streamed foliage still required",
                              "new World Partition actor package paths are assigned only after spawn"],
            "o05": {"old_remove": o05, "new": new,
                    "note": "Do not run the old generated O05 placement recipe after this repair."},
            "s10": {"old_remove": s10,
                    "note": "Remove six repeated Batch01 perimeter wall modules; retain the arch, unique damaged panels, inner houses and rubble."}}


def write_plan(plan: dict) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "priority_sites_plan.json"
    path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf8")
    return path


EDITOR_BODY = r'''
import math
import re

assert world.get_path_name().split('.')[0] == '/Game/level/Saskarta_WP'
targets = PLAN['o05']['old_remove'] + PLAN['s10']['old_remove']
by_label = {}
for actor in eas.get_all_level_actors():
    by_label.setdefault(actor.get_actor_label(), []).append(actor)

if ACTION in ('validate', 'apply'):
    assets = {}
    for row in PLAN['o05']['new']:
        mesh = eal.load_asset(row['mesh'])
        material_path = ('/Game/SaskartaGaea/Environment/Tripo02/Materials/MI_T2_'
                         + row['mesh'].rsplit('SM_T2_', 1)[-1])
        material = eal.load_asset(material_path)
        if mesh is None or material is None:
            raise RuntimeError('imported Tripo mesh/material missing ' + row['label'])
        assets[row['label']] = (mesh, material)
    found = []
    for row in targets:
        actors = by_label.get(row['label'], [])
        if len(actors) != 1:
            raise RuntimeError('missing or duplicate loaded actor ' + row['label'])
        actor = actors[0]
        if actor.get_package().get_name() != row['package']:
            raise RuntimeError('package drift ' + row['label'])
        guid = re.sub('[^0-9A-F]', '', actor.get_editor_property('actor_guid').export_text().upper())
        if guid != row['guid']:
            raise RuntimeError('GUID drift ' + row['label'] + ' ' + guid)
        mesh = actor.static_mesh_component.static_mesh
        if mesh is None or mesh.get_path_name().split('.')[0] != row['mesh']:
            raise RuntimeError('mesh drift ' + row['label'])
        origin, extent = actor.get_actor_bounds(False)
        current = [origin.x - extent.x, origin.y - extent.y, origin.z - extent.z,
                   origin.x + extent.x, origin.y + extent.y, origin.z + extent.z]
        if max(abs(a - b) for a, b in zip(current, row['bounds_cm'])) > 15:
            raise RuntimeError('bounds drift ' + row['label'] + ' ' + str(current))
        found.append(actor)
    for row in PLAN['o05']['new']:
        if by_label.get(row['label']):
            raise RuntimeError('replacement already exists ' + row['label'])
        yaw = math.radians(row['yaw'])
        co, si = math.cos(yaw), math.sin(yaw)
        hx, hy = row['size_cm'][0] / 2, row['size_cm'][1] / 2
        zs = []
        for u in (-hx, 0, hx):
            for v in (-hy, 0, hy):
                x = row['x_cm'] + u * co - v * si
                y = row['y_cm'] + u * si + v * co
                hit = trace_ground(x, y, 100000, -100000, [])
                if hit is None:
                    raise RuntimeError('landscape cell not loaded at ' + row['label'])
                zs.append(hit[0])
        if abs(min(zs) - row['ground_min_cm']) > 20 or abs(max(zs) - row['ground_max_cm']) > 25:
            raise RuntimeError('heightmap/live terrain drift ' + row['label'] + ' ' + str(zs))
        if row['base_z_cm'] - min(zs) > 5 or max(zs) - row['base_z_cm'] > 80:
            raise RuntimeError('new footprint gap or burial ' + row['label'])
    print('PRIORITY_SITE_VALIDATE old=' + str(len(found)) + ' new=' + str(len(PLAN['o05']['new'])) + ' PASS')
    if ACTION == 'apply':
        # Record exact destroyed packages so the later save pass does not touch
        # any other World Partition actor. Do not save until four live views pass.
        for actor in found:
            print('PRIORITY_DELETE_PACKAGE ' + actor.get_package().get_name())
            eas.destroy_actor(actor)
        for row in PLAN['o05']['new']:
            mesh, material = assets[row['label']]
            actor = eas.spawn_actor_from_class(unreal.StaticMeshActor,
                V(row['x_cm'], row['y_cm'], row['base_z_cm']),
                unreal.Rotator(pitch=0.0, yaw=row['yaw'], roll=0.0))
            actor.set_actor_label(row['label'])
            actor.set_editor_property('tags', [unreal.Name('WF_O05_Crest')])
            comp = actor.static_mesh_component
            comp.set_static_mesh(mesh)
            comp.set_material(0, material)
            for index, value in enumerate((0.0, 0.0, 0.0, 0.0, 0.45, 0.96, 0.92, 0.88)):
                comp.set_default_custom_primitive_data_float(index, value)
            print('PRIORITY_NEW_PACKAGE ' + row['label'] + ' ' + actor.get_package().get_name())
        print('PRIORITY_SITE_APPLY unsaved; capture and inspect four distinct views before save')
elif ACTION == 'save':
    created = []
    for row in PLAN['o05']['new']:
        actors = by_label.get(row['label'], [])
        if len(actors) != 1 or actors[0].static_mesh_component.static_mesh.get_path_name().split('.')[0] != row['mesh']:
            raise RuntimeError('replacement missing or changed ' + row['label'])
        created.append(actors[0].get_package())
    gone = []
    for row in targets:
        if by_label.get(row['label']):
            raise RuntimeError('old actor still present ' + row['label'])
        pkg = unreal.find_package(row['package'])
        if pkg is None:
            raise RuntimeError('destroyed package not resident ' + row['package'])
        gone.append(pkg)
    all_packages = created + gone
    start = SAVE_BATCH_INDEX * 20
    packages = all_packages[start:start + 20]
    if not packages:
        raise RuntimeError('empty save batch ' + str(SAVE_BATCH_INDEX))
    if not unreal.EditorLoadingAndSavingUtils.save_packages(packages, True):
        raise RuntimeError('package save failed')
    remaining = max(0, len(all_packages) - start - len(packages))
    print('PRIORITY_SITE_SAVE batch=' + str(SAVE_BATCH_INDEX) + ' saved=' + str(len(packages)) +
          ' remaining=' + str(remaining) + (' MORE' if remaining else ' DONE') + ' PASS')
else:
    raise RuntimeError('bad action ' + ACTION)
'''


def write_editor_script(plan: dict, action: str, save_batch: int = 0) -> Path:
    if action not in ("validate", "apply", "save"):
        raise ValueError(action)
    sys.path.insert(0, str(ROOT / "Tools" / "World"))
    import place_setdress as sd
    count = len(plan['o05']['old_remove']) + len(plan['s10']['old_remove']) + len(plan['o05']['new'])
    if save_batch < 0 or (action == 'save' and save_batch * 20 >= count):
        raise ValueError('invalid save batch')
    source = sd.build_script(EDITOR_BODY, PLAN=plan, ACTION=action, SAVE_BATCH_INDEX=save_batch)
    sd.validate(source)
    OUT.mkdir(parents=True, exist_ok=True)
    suffix = f'_{save_batch + 1:02d}' if action == 'save' and save_batch else ''
    path = OUT / f"priority_sites_{action}{suffix}.py"
    path.write_text(source, encoding="utf8")
    return path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("action", choices=("plan", "emit"))
    args = ap.parse_args()
    if args.action == "plan":
        plan = build_plan()
        path = write_plan(plan)
        print(path)
        print(f"O05 old={len(plan['o05']['old_remove'])} new={len(plan['o05']['new'])}"
              f" S10 repeated walls={len(plan['s10']['old_remove'])}")
        for p in plan["o05"]["new"]:
            print(p["label"], (p["x_cm"], p["y_cm"], p["base_z_cm"]),
                  "footprint relief", p["relief_cm"], "cm, road LOS", p["minimum_clearance_m"], "m")
    elif args.action == "emit":
        plan = build_plan()
        for action in ("validate", "apply"):
            print(write_editor_script(plan, action))
        count = len(plan['o05']['old_remove']) + len(plan['s10']['old_remove']) + len(plan['o05']['new'])
        for batch in range(math.ceil(count / 20)):
            print(write_editor_script(plan, 'save', batch))


if __name__ == "__main__":
    main()
