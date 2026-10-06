"""Ambience 2 spot emitters (README_Ambience.md step 4): one AmbientSound per manifest placement row with a loop.

    python Tools/Audio/place_ambience2_spots.py plan     # offline: the rows
    python Tools/Audio/place_ambience2_spots.py place    # spawn (skips labels already in the level), 4 per call
    python Tools/Audio/place_ambience2_spots.py save     # save the spawned actors' external packages
    python Tools/Audio/place_ambience2_spots.py read     # print what is in the level

Label and Actor Tag = the row's label (the director finds the actor by tag). Auto Activate off (the director
starts and stops it). Attenuation override: sphere inner radius, falloff, Natural Sound, air absorption (LPF),
non-spatialized radius = inner. Spawn and save are separate calls (World Partition, see memory
wp-scripted-load-save-unload). Every call checks for PIE first (apply_look.python_run).
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Tools" / "Look"))
from apply_look import python_run, check_banned  # noqa: E402

MANIFEST = ROOT / "Saved" / "GameAudio" / "Ambience2" / "manifest.json"
DEST = "/Game/SaskartaGaea/Audio/Ambience2"

PLACE = r'''
import unreal
eal = unreal.EditorAssetLibrary
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
have = set()
for a in unreal.GameplayStatics.get_all_actors_of_class(unreal.EditorLevelLibrary.get_editor_world(), unreal.AmbientSound):
    if True:
        have.add(a.get_actor_label())
rows = __ROWS__
for label, snd, xyz, inner, falloff in rows:
    if label in have:
        print("SKIP " + label)
        continue
    a = eas.spawn_actor_from_class(unreal.AmbientSound, unreal.Vector(*xyz))
    a.set_actor_label(label)
    a.tags = [label]
    c = a.get_editor_property("audio_component")
    c.set_editor_property("sound", eal.load_asset(snd))
    c.set_editor_property("auto_activate", False)
    c.set_editor_property("override_attenuation", True)
    s = c.get_editor_property("attenuation_overrides")
    s.set_editor_property("attenuation_shape", unreal.AttenuationShape.SPHERE)
    s.set_editor_property("attenuation_shape_extents", unreal.Vector(inner * 100, 0, 0))
    s.set_editor_property("falloff_distance", falloff * 100)
    s.set_editor_property("distance_algorithm", unreal.AttenuationDistanceModel.NATURAL_SOUND)
    s.set_editor_property("attenuate_with_lpf", True)
    s.set_editor_property("non_spatialized_radius_start", inner * 100)
    c.set_editor_property("attenuation_overrides", s)
    print("PLACED " + label + " " + str(a.get_actor_location()))
'''

SAVE = r'''
import unreal
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
pk = []
for a in unreal.GameplayStatics.get_all_actors_of_class(unreal.EditorLevelLibrary.get_editor_world(), unreal.AmbientSound):
    if a.get_actor_label().startswith("A2_"):
        pk.append(a.get_package())
print("SAVED " + str(unreal.EditorLoadingAndSavingUtils.save_packages(pk, True)) + " n=" + str(len(pk)))
'''

READ = r'''
import unreal
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
n = 0
for a in unreal.GameplayStatics.get_all_actors_of_class(unreal.EditorLevelLibrary.get_editor_world(), unreal.AmbientSound):
    if a.get_actor_label().startswith("A2_"):
        c = a.get_editor_property("audio_component")
        s = c.get_editor_property("attenuation_overrides")
        n += 1
        print(a.get_actor_label() + " tags=" + str([str(t) for t in a.tags]) + " snd=" + c.get_editor_property("sound").get_name() + " auto=" + str(c.get_editor_property("auto_activate")) + " inner=" + str(round(s.get_editor_property("attenuation_shape_extents").x)) + " falloff=" + str(round(s.get_editor_property("falloff_distance"))) + " dirty=" + str(a.get_package().is_dirty()))
print("A2 actors " + str(n))
'''


def rows():
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    out = []
    for r in m["placement"]:
        if not r["asset"].endswith("_Loop"):
            continue  # A2_WW_GateCreak: a pool anchor only
        out.append((r["label"], f"{DEST}/{r['asset']}", (r["x"], r["y"], r["z"]), r["inner_radius_m"], r["falloff_m"]))
    return out


def main():
    step = sys.argv[1] if len(sys.argv) > 1 else "plan"
    if step == "plan":
        for r in rows():
            print(r)
        print(len(rows()), "rows")
    elif step == "place":
        rs = rows()
        for i in range(0, len(rs), 4):
            ok, out, err = python_run(check_banned(PLACE.replace("__ROWS__", repr(rs[i:i + 4]))))
            print(out.strip())
            if not ok:
                raise SystemExit(f"place batch {i // 4} failed: {err}")
    elif step in ("save", "read"):
        ok, out, err = python_run(check_banned(SAVE if step == "save" else READ))
        print(out.strip() or err)
    return 0


if __name__ == "__main__":
    sys.exit(main())
