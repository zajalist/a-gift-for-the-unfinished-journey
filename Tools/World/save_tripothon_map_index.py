"""Verify registered placements and save only their World Partition map index."""
from pathlib import Path
import json
import sys
import unreal

ROOT = Path(r"C:\Users\Admin\Desktop\Tripothon_All_Scenes_Handoff_v003_EN")
sys.path.insert(0, str(ROOT / "Scripts"))
from transfer_actor_state import snapshot, compare_state


def main():
    manifest = json.loads((ROOT / "placements.json").read_text(encoding="utf-8"))
    registry_path = ROOT / "TargetResults/actor_registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    defs = {a["id"]: a for a in manifest["actors"]}
    ids = set(defs)
    if len(ids) != 359 or len(registry["actors"]) != 359:
        raise RuntimeError("Expected exactly 359 placement IDs and receipt records")
    if any(registry["actors"][actor_id].get("status") != "APPLIED_SAVED" for actor_id in ids):
        raise RuntimeError("Every placement must already have a saved external actor package")

    descs = list(unreal.WorldPartitionBlueprintLibrary.get_actor_descs())
    selected_descs = [d for d in descs if str(d.label) in ids]
    counts = {actor_id: 0 for actor_id in ids}
    for d in selected_descs:
        counts[str(d.label)] += 1
    duplicates = {k: v for k, v in counts.items() if v != 1}
    if duplicates:
        raise RuntimeError("World Partition labels missing or duplicated: " + repr(duplicates))
    unreal.WorldPartitionBlueprintLibrary.load_actors([d.guid for d in selected_descs])

    subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    loaded = subsystem.get_all_level_actors()
    matched = {}
    for actor_id in sorted(ids):
        found = [a for a in loaded if a.get_actor_label() == actor_id
                 or actor_id in [str(t) for t in a.get_editor_property("tags")]]
        if len(found) != 1:
            raise RuntimeError("Expected exactly one loaded placement actor: " + actor_id)
        actor = found[0]
        record = registry["actors"][actor_id]
        if actor.get_path_name() != record["identity"]["path"]:
            raise RuntimeError("Placement actor identity differs from receipt: " + actor_id)
        actual = snapshot(unreal, actor)
        # Outliner folder is level metadata and is not part of the actor package.
        actual["folder"] = defs[actor_id]["folder"]
        compare_state(actual, defs[actor_id])
        package = actor.get_outermost()
        if "/__ExternalActors__/" not in package.get_name():
            raise RuntimeError("Refusing unexpected actor package: " + package.get_name())
        matched[actor_id] = actor

    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    map_package = world.get_outermost()
    if map_package.get_name() != "/Game/level/Saskarta_WP":
        raise RuntimeError("Refusing to save a map other than Saskarta_WP")
    if not unreal.EditorLoadingAndSavingUtils.save_packages([map_package], True):
        raise RuntimeError("Saving only the Saskarta_WP map package failed")
    print("TRIPOTHON_MAP_INDEX_SAVE_PASSED", len(matched))
    print("TRIPOTHON_MAP_PACKAGE", map_package.get_name())
    print("TRIPOTHON_ACTORS_VERIFIED", len(matched))
    print("TRIPOTHON_MAP_SAVE_ONLY", True)

main()
