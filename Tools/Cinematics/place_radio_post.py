"""Emit one scoped editor chunk for the summit interaction and grounded drone anchor.

The measured radio_post values live in probe_ending.json. The chunk changes
only HighVoice_Ending's Plate/StandPoint and one TargetPoint tagged
Saskarta.DroneRest, then saves those two external-actor packages.

    python Tools/Cinematics/place_radio_post.py Saved/Cinematics/place_radio_post.py
    python Tools/GameFlow/editor/ending_editor.py run-file Saved/Cinematics/place_radio_post.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import build_cinematics as bc

CHUNK = """import unreal
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
actors = eas.get_all_level_actors()
hv = [a for a in actors if 'Saskarta.HighVoice' in [str(t) for t in a.tags]]
rests = [a for a in actors if 'Saskarta.DroneRest' in [str(t) for t in a.tags]]
if len(hv) != 1 or len(rests) > 1:
    print('STOP: expected exactly one HighVoice and at most one DroneRest', len(hv), len(rests))
else:
    a = hv[0]
    c = {{x.get_name(): x for x in a.get_components_by_class(unreal.SceneComponent)}}
    p = c['Plate']; s = c['StandPoint']
    # The interaction plate is a small weathered metal plaque on the hut wall.
    # Restore its mesh after BP construction and avoid the bright default cube.
    p.set_editor_property('static_mesh', unreal.load_asset('/Game/LevelPrototyping/Meshes/SM_ChamferCube'))
    p.set_editor_property('relative_scale3d', unreal.Vector(0.05, 0.4, 0.4))
    p.set_material(0, unreal.load_asset('/Game/SaskartaGaea/Environment/SetDress/Materials/MI_Metal_GB.MI_Metal_GB'))
    p.set_world_location(unreal.Vector(*{plate}), False, False)
    p.set_world_rotation(unreal.Rotator(0.0, 0.0, {plate_yaw}), False, False)
    s.set_world_location(unreal.Vector(*{stand}), False, False)
    s.set_world_rotation(unreal.Rotator(0.0, 0.0, {stand_yaw}), False, False)
    rest = rests[0] if rests else eas.spawn_actor_from_class(unreal.TargetPoint, unreal.Vector(*{drone_rest}))
    rest.set_actor_label('DroneRest_RadioPost')
    rest.set_folder_path('Story/HighVoice')
    rest.set_actor_location(unreal.Vector(*{drone_rest}), False, False)
    rest.set_actor_rotation(unreal.Rotator(0.0, {drone_pitch}, {drone_yaw}), False)
    rest.set_editor_property('tags', [unreal.Name('Saskarta.DroneRest')])
    rest.set_editor_property('is_spatially_loaded', False)
    packages = [a.get_package(), rest.get_package()]
    print('plate', str(p.get_world_location()), 'stand', str(s.get_world_location()), 'rest', str(rest.get_actor_location()))
    print('packages', [str(x.get_name()) for x in packages])
    print('saved', unreal.EditorLoadingAndSavingUtils.save_packages(packages, True))
"""


def emit(out: Path) -> None:
    post = bc.radio_post()
    for required in ("plate", "plate_yaw", "stand", "stand_yaw", "drone_rest"):
        if required not in post:
            raise SystemExit(f"radio_post.{required} needs measured editor placement before emitting")
    _, _, _, _, pitch, yaw = bc.grounded_final_camera()
    text = CHUNK.format(plate=tuple(post["plate"]), plate_yaw=post["plate_yaw"],
                        stand=tuple(post["stand"]), stand_yaw=post["stand_yaw"],
                        drone_rest=tuple(post["drone_rest"]),
                        drone_pitch=round(pitch, 3), drone_yaw=round(yaw, 3))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print("emitted", out)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: place_radio_post.py OUT.py")
    emit(Path(sys.argv[1]))
