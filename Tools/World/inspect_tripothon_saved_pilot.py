"""Read-only comparison of reloaded pilot actor packages against their receipt."""
from pathlib import Path
import json
import sys

import unreal


ROOT = Path(r"C:\Users\Admin\Desktop\Tripothon_All_Scenes_Handoff_v003_EN")
sys.path.insert(0, str(ROOT / "Scripts"))
from transfer_actor_state import snapshot

PILOT = ["ZY_LOWLANDS_0034", "ZY_STATION_0001", "ZY_SUM_0203"]


def main():
    registry = json.loads((ROOT / "TargetResults/actor_registry.json").read_text(encoding="utf-8"))
    descs = list(unreal.WorldPartitionBlueprintLibrary.get_actor_descs())
    target_descs = [d for d in descs if str(d.label) in PILOT]
    unreal.WorldPartitionBlueprintLibrary.load_actors([d.guid for d in target_descs])
    actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors()
    output = {"descriptor_count": len(target_descs), "actors": {}}
    for actor_id in PILOT:
        found = [a for a in actors if a.get_actor_label() == actor_id
                 or actor_id in [str(t) for t in a.get_editor_property("tags")]]
        if len(found) != 1:
            output["actors"][actor_id] = {"found_count": len(found)}
            continue
        actual = snapshot(unreal, found[0])
        expected = registry["actors"][actor_id]["actual"]
        output["actors"][actor_id] = {
            "differences": {k: {"expected": expected[k], "actual": actual[k]}
                            for k in expected if expected[k] != actual[k]},
            "actual": actual,
        }
    result = Path(unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_saved_dir())) / "Verification" / "tripothon_pilot_reload_diff.json"
    result.parent.mkdir(parents=True, exist_ok=True)
    result.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print("TRIPOTHON_PILOT_RELOAD_DIFF", result)
    for actor_id, data in output["actors"].items():
        print("TRIPOTHON_PILOT_RELOAD_ACTOR", actor_id, json.dumps(data.get("differences", data)))


main()
