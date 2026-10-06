"""Submission 2026-10-05: darker, moodier, storm-matched grade.

Run inside the Unreal editor (Saskarta_WP loaded):
    py "D:/UnrealEngine/saskartarad/Tools/Submission1005/look/apply_moody_grade.py"
Revert:
    py "D:/UnrealEngine/saskartarad/Tools/Submission1005/look/apply_moody_grade.py" revert

Touches only PPV_Saskarta_Mood (exposure) and the two grade volumes the runtime lighting
director blends (PPV_Saskarta_Grade_Storm / _Clear). The director only writes BlendWeight, so
these settings survive at runtime. Backs up every touched property before writing and saves
only those three actor packages.
"""
import json, os, sys
import unreal

ROOT = "D:/UnrealEngine/saskartarad"
BACKUP = ROOT + "/Saved/Backups/Submission1005/grade_backup.json"

# Mood: manual exposure compensation (EV). Was 11.25. -0.7 EV ~= 38 % darker overall.
MOOD_EV = 10.55

V = lambda r, g, b, a: (r, g, b, a)
GRADE = {
    # Everything up to the summit: push the existing storm look further.
    "PPV_Saskarta_Grade_Storm": {
        "color_saturation": V(1.0, 1.0, 1.0, 0.52),          # was 0.60
        "color_contrast": V(1.0, 1.0, 1.0, 1.24),            # was 1.15
        "color_gamma": V(1.0, 1.0, 1.0, 0.94),               # sink mid-tones
        "color_saturation_shadows": V(1.0, 1.0, 1.0, 0.6),   # was 0.7
        "color_gain_shadows": V(0.96, 1.0, 1.04, 1.0),       # cool, slightly teal shadows (split tone)
        "color_offset_shadows": V(0.0, 0.002, 0.004, 0.0),   # lift blacks toward blue-grey, not orange
        "color_gain_midtones": V(1.02, 1.0, 0.95, 1.0),
        "color_gain_highlights": V(1.12, 0.98, 0.80, 1.0),   # warm burnt-orange highlights (kept)
        "film_toe": 0.66,                                    # was 0.60: deeper blacks
        "film_shoulder": 0.24,                               # softer roll-off, less blown sky
        "film_black_clip": 0.0,
        "vignette_intensity": 0.5,                           # was 0.35
        "film_grain_intensity": 0.16,                        # was 0.10
        "bloom_intensity": 0.45,
    },
    # Pre-dawn / summit: keep it reading as "clearer" but in the same moody family.
    "PPV_Saskarta_Grade_Clear": {
        "color_saturation": V(1.0, 1.0, 1.0, 0.68),          # was 0.85
        "color_contrast": V(1.0, 1.0, 1.0, 1.12),            # was 0.92
        "color_gamma": V(1.0, 1.0, 1.0, 0.96),
        "color_gain_shadows": V(0.97, 1.0, 1.04, 1.0),
        "color_offset_shadows": V(0.0, 0.002, 0.004, 0.0),
        "color_gain_midtones": V(1.03, 1.0, 0.95, 1.0),
        "color_gain_highlights": V(1.12, 1.0, 0.82, 1.02),
        "film_toe": 0.62,                                    # was 0.55
        "film_shoulder": 0.24,
        "vignette_intensity": 0.45,
        "film_grain_intensity": 0.14,
        "bloom_intensity": 0.5,
    },
}

def _ser(v):
    if isinstance(v, unreal.Vector4):
        return [v.x, v.y, v.z, v.w]
    if isinstance(v, (bool, int, float, str)):
        return v
    return str(v)

def _deser(v):
    return unreal.Vector4(*v) if isinstance(v, list) else v

def _volumes():
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    return {a.get_actor_label(): a for a in eas.get_all_level_actors()
            if a.get_class().get_name() == "PostProcessVolume"}

def _save(actors):
    pk = [a.get_package() for a in actors]
    print("saved", unreal.EditorLoadingAndSavingUtils.save_packages(pk, True))

def apply():
    vols = _volumes()
    need = list(GRADE) + ["PPV_Saskarta_Mood"]
    missing = [n for n in need if n not in vols]
    if missing:
        print("MOODY_GRADE_ABORT missing volumes:", missing); return
    backup = {}
    if os.path.exists(BACKUP):
        backup = json.load(open(BACKUP))
        print("backup exists, keeping the original one")
    else:
        for label in need:
            s = vols[label].get_editor_property("settings")
            keys = list(GRADE.get(label, {})) + (["auto_exposure_bias"] if label == "PPV_Saskarta_Mood" else [])
            backup[label] = {k: [s.get_editor_property("override_" + k), _ser(s.get_editor_property(k))] for k in keys}
        os.makedirs(os.path.dirname(BACKUP), exist_ok=True)
        json.dump(backup, open(BACKUP, "w"), indent=1)
    for label, spec in GRADE.items():
        a = vols[label]; s = a.get_editor_property("settings")
        for k, v in spec.items():
            s.set_editor_property("override_" + k, True)
            s.set_editor_property(k, unreal.Vector4(*v) if isinstance(v, tuple) else v)
        a.set_editor_property("settings", s)
    m = vols["PPV_Saskarta_Mood"]; s = m.get_editor_property("settings")
    s.set_editor_property("override_auto_exposure_bias", True)
    s.set_editor_property("auto_exposure_bias", MOOD_EV)
    m.set_editor_property("settings", s)
    _save([vols[n] for n in need])
    print("MOODY_GRADE_OK mood_ev", MOOD_EV)

def revert():
    if not os.path.exists(BACKUP):
        print("no backup"); return
    vols = _volumes(); backup = json.load(open(BACKUP))
    for label, props in backup.items():
        a = vols[label]; s = a.get_editor_property("settings")
        for k, (ov, val) in props.items():
            s.set_editor_property("override_" + k, ov)
            s.set_editor_property(k, _deser(val))
        a.set_editor_property("settings", s)
    _save([vols[n] for n in backup])
    print("MOODY_GRADE_REVERTED")

if __name__ == "__main__":
    revert() if "revert" in sys.argv[1:] else apply()
