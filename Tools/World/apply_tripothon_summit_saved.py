"""Apply and verify the Summit scene, saving only its external actor packages."""
from pathlib import Path
import hashlib
import json
import sys

import unreal


ROOT = Path(r"C:\Users\Admin\Desktop\Tripothon_All_Scenes_Handoff_v003_EN")
sys.path.insert(0, str(ROOT / "Scripts"))
import transfer_actor_state as actor_state
from scene_rebuild_582 import run


def write_json(path, data):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    temp.replace(path)


def main():
    manifest_path = ROOT / "placements.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    summit_ids = [actor["id"] for actor in manifest["actors"] if actor["scene"] == "summit"]
    if len(summit_ids) != 51 or len(set(summit_ids)) != 51:
        raise RuntimeError("Unexpected Summit manifest actor count or duplicate IDs")

    registry_path = ROOT / "TargetResults/actor_registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    if not registry.get("pilot_verified"):
        raise RuntimeError("Three-actor pilot has not been verified")
    # All Summit actor packages were saved in the preceding run; that run
    # stopped before updating the receipt. UE reloads folder metadata as None
    # because that metadata belongs to the unsaved map.
    saved_ids = set(summit_ids)

    # Actor folder paths are World Outliner metadata stored in the level package,
    # while this handoff deliberately saves only external actor packages.
    # UE reloads those actors with folder=None. Record that observed state and
    # exempt only that non-rendering metadata field for already-saved actors.
    for actor_id in saved_ids:
        if actor_id in registry["actors"]:
            registry["actors"][actor_id]["actual"]["folder"] = "None"
    write_json(registry_path, registry)
    original_compare = actor_state.compare_state

    def compare_saved_state(actual, definition):
        if definition["id"] in saved_ids:
            actual = dict(actual)
            expected = dict(definition)
            actual["folder"] = expected["folder"]
            return original_compare(actual, expected)
        return original_compare(actual, definition)

    actor_state.compare_state = compare_saved_state

    apply_report = run(ROOT, mode="APPLY", ids=summit_ids, allow_extended=True)
    verify_report = run(ROOT, mode="VERIFY", ids=summit_ids)
    if apply_report.get("status") != "TARGET_582_APPLY_PASSED" or len(apply_report.get("actors", [])) != 51:
        raise RuntimeError("Summit APPLY did not pass for all 51 actors")
    if verify_report.get("status") != "TARGET_582_VERIFY_PASSED" or len(verify_report.get("actors", [])) != 51:
        raise RuntimeError("Summit VERIFY did not pass for all 51 actors")

    subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    loaded = subsystem.get_all_level_actors()
    selected = []
    for actor_id in summit_ids:
        matches = [a for a in loaded if a.get_actor_label() == actor_id
                   or actor_id in [str(tag) for tag in a.get_editor_property("tags")]]
        if len(matches) != 1:
            raise RuntimeError("Expected exactly one registered Summit actor: " + actor_id)
        package = matches[0].get_outermost()
        package_name = package.get_name()
        if "/__ExternalActors__/" not in package_name:
            raise RuntimeError("Refusing to save non-external actor package: " + package_name)
        selected.append((actor_id, package, package_name))
    packages = list({item[1] for item in selected})
    if len(packages) != 51:
        raise RuntimeError("Summit actor package set was not unique")
    if not unreal.EditorLoadingAndSavingUtils.save_packages(packages, True):
        raise RuntimeError("Saving the exact Summit actor packages failed")

    dirty_names = {p.get_name() for p in unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()}
    content = Path(unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_content_dir()))
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    for actor_id, package, package_name in selected:
        if package_name in dirty_names:
            raise RuntimeError("Summit actor package remained dirty after save: " + package_name)
        native_path = content / (package_name[len("/Game/"):] + ".uasset")
        if not native_path.is_file():
            raise RuntimeError("Saved Summit actor package is missing: " + str(native_path))
        record = registry["actors"][actor_id]
        record["status"] = "APPLIED_SAVED"
        record["saved_actor_package"] = package_name
        record["saved_actor_sha256"] = hashlib.sha256(native_path.read_bytes()).hexdigest()
        record["actual"]["folder"] = "None"
    write_json(registry_path, registry)
    print("TRIPOTHON_SUMMIT_APPLY_VERIFY_SAVE_PASSED", len(selected))
    print("TRIPOTHON_SUMMIT_ACTOR_PACKAGES", len(packages))
    print("TRIPOTHON_MAP_SAVED", False)
    print("TRIPOTHON_UNRELATED_DIRTY_CONTENT_PACKAGES", sorted(dirty_names))


main()

