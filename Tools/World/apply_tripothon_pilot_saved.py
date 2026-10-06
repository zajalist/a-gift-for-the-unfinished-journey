"""Apply, verify, and save only the three supplied Tripothon pilot actors."""
from pathlib import Path
import json
import sys

import unreal


ROOT = Path(r"C:\Users\Admin\Desktop\Tripothon_All_Scenes_Handoff_v003_EN")
sys.path.insert(0, str(ROOT / "Scripts"))

from scene_rebuild_582 import run


PILOT = ["ZY_LOWLANDS_0034", "ZY_STATION_0001", "ZY_SUM_0203"]


def main():
    apply_report = run(ROOT, mode="APPLY", ids=PILOT)
    verify_report = run(ROOT, mode="VERIFY", ids=PILOT)
    if apply_report.get("status") != "TARGET_582_APPLY_PASSED":
        raise RuntimeError("Pilot APPLY did not pass")
    if verify_report.get("status") != "TARGET_582_VERIFY_PASSED":
        raise RuntimeError("Pilot VERIFY did not pass")

    subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    selected = []
    for actor_id in PILOT:
        matches = [a for a in subsystem.get_all_level_actors()
                   if a.get_actor_label() == actor_id
                   or actor_id in [str(tag) for tag in a.get_editor_property("tags")]]
        if len(matches) != 1:
            raise RuntimeError("Expected exactly one registered pilot actor: " + actor_id)
        package = matches[0].get_outermost()
        package_name = package.get_name()
        if "/__ExternalActors__/" not in package_name:
            raise RuntimeError("Refusing to save non-external actor package: " + package_name)
        selected.append((actor_id, package, package_name))

    packages = list({item[1] for item in selected})
    if not unreal.EditorLoadingAndSavingUtils.save_packages(packages, True):
        raise RuntimeError("Saving the exact pilot actor packages failed")

    registry_path = ROOT / "TargetResults/actor_registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    for actor_id, package, package_name in selected:
        record = registry["actors"][actor_id]
        record["status"] = "APPLIED_SAVED"
        record["saved_actor_package"] = package_name
        record["actor_package_dirty_after_save"] = bool(package.is_dirty())
        if record["actor_package_dirty_after_save"]:
            raise RuntimeError("Pilot actor package remained dirty after save: " + package_name)
    temp = registry_path.with_suffix(".tmp")
    temp.write_text(json.dumps(registry, indent=2), encoding="utf-8")
    temp.replace(registry_path)
    print("TRIPOTHON_PILOT_APPLY_VERIFY_SAVE_PASSED", PILOT)
    print("TRIPOTHON_PILOT_ACTOR_PACKAGES", [item[2] for item in selected])
    print("TRIPOTHON_MAP_SAVED", False)


main()
