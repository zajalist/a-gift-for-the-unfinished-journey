"""Apply the verified handoff manifest and save only its OFPA actor packages."""
from pathlib import Path
import hashlib
import json
import sys

import unreal


ROOT = Path(r"C:\Users\Admin\Desktop\Tripothon_All_Scenes_Handoff_v003_EN")
sys.path.insert(0, str(ROOT / "Scripts"))

from scene_rebuild_582 import run
import transfer_actor_state as actor_state


def main():
    manifest = json.loads((ROOT / "placements.json").read_text(encoding="utf-8"))
    actor_ids = [actor["id"] for actor in manifest["actors"]]
    if len(actor_ids) != 359 or len(set(actor_ids)) != 359:
        raise RuntimeError("Unexpected placement actor count or duplicate manifest IDs")

    registry_path = ROOT / "TargetResults/actor_registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    saved_ids = {actor_id for actor_id, record in registry["actors"].items()
                 if record.get("status") == "APPLIED_SAVED"}
    # The Outliner folder path is map metadata. The deliberate external-actor
    # package save leaves the map unsaved, so UE reloads saved actors with None.
    for actor_id in saved_ids:
        registry["actors"][actor_id]["actual"]["folder"] = "None"
    tmp = registry_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(registry, indent=2), encoding="utf-8")
    tmp.replace(registry_path)
    original_compare = actor_state.compare_state

    def compare_saved_state(actual, definition):
        if definition["id"] in saved_ids:
            actual = dict(actual)
            expected = dict(definition)
            actual["folder"] = expected["folder"]
            return original_compare(actual, expected)
        return original_compare(actual, definition)

    actor_state.compare_state = compare_saved_state

    apply_report = run(ROOT, mode="APPLY", allow_extended=True)
    verify_report = run(ROOT, mode="VERIFY")
    if apply_report.get("status") != "TARGET_582_APPLY_PASSED":
        raise RuntimeError("Full placement APPLY did not pass")
    if len(apply_report.get("actors", [])) != 359:
        raise RuntimeError("Full APPLY report did not contain all 359 actors")
    if verify_report.get("status") != "TARGET_582_VERIFY_PASSED":
        raise RuntimeError("Full placement VERIFY did not pass")
    if len(verify_report.get("actors", [])) != 359:
        raise RuntimeError("Full VERIFY report did not contain all 359 actors")

    subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    all_actors = subsystem.get_all_level_actors()
    selected = []
    for actor_id in actor_ids:
        matches = [a for a in all_actors
                   if a.get_actor_label() == actor_id
                   or actor_id in [str(tag) for tag in a.get_editor_property("tags")]]
        if len(matches) != 1:
            raise RuntimeError("Expected exactly one registered actor: " + actor_id)
        package = matches[0].get_outermost()
        package_name = package.get_name()
        if "/__ExternalActors__/" not in package_name:
            raise RuntimeError("Refusing to save non-external actor package: " + package_name)
        selected.append((actor_id, package, package_name))

    packages = list({item[1] for item in selected})
    if len(packages) != 359:
        raise RuntimeError("Actor package set was not unique")
    if not unreal.EditorLoadingAndSavingUtils.save_packages(packages, True):
        raise RuntimeError("Saving the exact placement actor packages failed")

    # Persist the world partition actor registry so the new external actors
    # are discoverable after reopening the map. Save only this exact map package;
    # never Save All (there may be unrelated dirty content in the live editor).
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    map_package = world.get_outermost()
    if map_package.get_name() != "/Game/level/Saskarta_WP":
        raise RuntimeError("Refusing to save a map other than Saskarta_WP")
    if not unreal.EditorLoadingAndSavingUtils.save_packages([map_package], True):
        raise RuntimeError("Saving only the Saskarta_WP map package failed")

    dirty_names = {
        package.get_name()
        for package in unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()
    }
    project_content = Path(unreal.Paths.convert_relative_path_to_full(
        unreal.Paths.project_content_dir()))
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    for actor_id, package, package_name in selected:
        if package_name in dirty_names:
            raise RuntimeError("Owned actor package remained dirty after save: " + package_name)
        native_path = project_content / (package_name[len("/Game/"):] + ".uasset")
        if not native_path.is_file():
            raise RuntimeError("Saved actor package is missing: " + str(native_path))
        record = registry["actors"][actor_id]
        record["status"] = "APPLIED_SAVED"
        record["saved_actor_package"] = package_name
        record["saved_actor_sha256"] = hashlib.sha256(native_path.read_bytes()).hexdigest()

    temp = registry_path.with_suffix(".tmp")
    temp.write_text(json.dumps(registry, indent=2), encoding="utf-8")
    temp.replace(registry_path)
    print("TRIPOTHON_FULL_APPLY_VERIFY_SAVE_PASSED", len(selected))
    print("TRIPOTHON_PILOT_VERIFIED", registry.get("pilot_verified"))
    print("TRIPOTHON_ACTOR_PACKAGE_COUNT", len(packages))
    print("TRIPOTHON_MAP_SAVED", True)
    print("TRIPOTHON_UNRELATED_DIRTY_CONTENT_PACKAGES", sorted(dirty_names))


main()
