"""Emit guarded editor chunks for the actual relay-hut interaction volume.

    python Tools/GameFlow/editor/summit_approach.py place
    python Tools/GameFlow/editor/summit_approach.py read
    python Tools/GameFlow/editor/summit_approach.py save

Output is Unreal Python for ending_editor.py run-file, under the editor gate.
The saved S26 doorway anchor defines the trigger, so moving the hut moves it too.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ANCHORS = ROOT / "Tools/World/story_sets/S26_Tripo.json"
TRIGGER_ID = "SUMMIT_HUT_APPROACH"
LABEL = "Summit_Hut_Approach"


def placement(anchor: dict) -> dict:
    door = anchor["doorway_cm"]
    yaw = anchor["outward_yaw"]
    radians = math.radians(yaw)
    return {"location": (door[0] + 110 * math.cos(radians), door[1] + 110 * math.sin(radians), door[2] + 95),
            "yaw": yaw, "extent": (180, 200, 170)}


def chunk(step: str, anchor: dict | None = None) -> str:
    anchor = anchor or json.loads(ANCHORS.read_text(encoding="utf-8"))["anchor"]
    p = placement(anchor)
    base = f"""import unreal
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
actors = [a for a in eas.get_all_level_actors() if a.get_actor_label() == {LABEL!r}]
assert len(actors) <= 1, 'Duplicate summit approach volumes'
"""
    if step == "place":
        return base + f"""loc = unreal.Vector{p['location']!r}
rot = unreal.Rotator(pitch=0.0, yaw={p['yaw']!r}, roll=0.0)
a = actors[0] if actors else eas.spawn_actor_from_class(unreal.SaskartaEventVolume, loc, rot)
assert a is not None
a.set_actor_label({LABEL!r})
a.set_actor_location_and_rotation(loc, rot, False, True)
a.set_editor_property('trigger_id', {TRIGGER_ID!r})
a.set_editor_property('pawn_only', True)
a.set_editor_property('is_spatially_loaded', False)
a.set_folder_path('Story/HighVoice')
a.tags = [unreal.Name('Saskarta.HutApproach')]
box = a.get_editor_property('box')
box.set_box_extent(unreal.Vector{p['extent']!r}, False)
box.set_editor_property('generate_overlap_events', True)
print('SUMMIT_APPROACH_PLACED', str(a.get_actor_location()), str(box.get_unscaled_box_extent()), a.get_package().get_name())
"""
    if step == "read":
        return base + f"""assert len(actors) == 1
a = actors[0]
assert str(a.get_editor_property('trigger_id')) == {TRIGGER_ID!r}
assert a.get_editor_property('pawn_only')
assert not a.get_editor_property('is_spatially_loaded')
print('SUMMIT_APPROACH_READ', str(a.get_actor_location()), str(a.get_actor_rotation()), str(a.get_editor_property('box').get_unscaled_box_extent()), a.get_package().get_name())
"""
    if step == "save":
        return base + """assert len(actors) == 1
print('SUMMIT_APPROACH_SAVED', unreal.EditorLoadingAndSavingUtils.save_packages([actors[0].get_package()], True))
"""
    raise ValueError(step)


if __name__ == "__main__":
    print(chunk(sys.argv[1]))
