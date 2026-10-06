"""Build DA_Saskarta_LookKeys from look_keys.json, and tag the lighting actors (Task L7).

    python Tools/Look/build_look_keys_asset.py build         # create/update the data asset and save it
    python Tools/Look/build_look_keys_asset.py tag-actors    # add the director's actor tags and save those actors
    python Tools/Look/build_look_keys_asset.py read          # print the asset's keys and the actors' tags
    python Tools/Look/build_look_keys_asset.py build --dry-run   # print the editor script only

Needs the SaskartaCore module built and loaded (USaskartaLookKeys / FSaskartaLookKey, exposed
to Python as unreal.SaskartaLookKeys / unreal.SaskartaLookKey), so it runs after the user's
editor restart. Spec: docs/superpowers/specs/2026-09-26-saskarta-world-sprint-design.md, section 6.

The asset (/Game/SaskartaGaea/Look/DA_Saskarta_LookKeys) holds one FSaskartaLookKey per JSON key,
sorted by road metre, in the JSON's units (degrees, lux, kelvin, km, m). The fog colour is stored
as its linear hue, unscaled; USaskartaLightingDirector multiplies it by the fog luminance scale,
exactly as apply_look.py does. Idempotent: an existing asset has its Keys array replaced.

USaskartaLightingDirector finds the lighting actors by tag. On 2026-09-27 none of the six tags
existed in Saskarta_WP (L7 read-only query), so `tag-actors` adds them by actor label:

    DirectionalLight          -> Saskarta_Sun
    SkyAtmosphere             -> Saskarta_Sky
    VolumetricCloud           -> Saskarta_Clouds
    ExponentialHeightFog      -> Saskarta_Fog
    PPV_Saskarta_Grade_Storm  -> Saskarta_GradeStorm
    PPV_Saskarta_Grade_Clear  -> Saskarta_GradeClear

All six actors are not spatially loaded, so they are always present at runtime.

Runs through Hayba python_run (5 s per call, banned words checked). Wrap it in
Tools/GameFlow/editor_gate.py acquire/release. It saves only the data asset (build) or only the
six tagged actors' external packages (tag-actors).
"""
import argparse
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from apply_look import FOG_LUMINANCE_SCALE, check_banned, hex_to_linear, load_keys, python_run  # noqa: E402

FOLDER = "/Game/SaskartaGaea/Look"
ASSET = "DA_Saskarta_LookKeys"

# Actor label -> the tag USaskartaLightingDirector looks for.
ACTOR_TAGS = {
    "DirectionalLight": "Saskarta_Sun",
    "SkyAtmosphere": "Saskarta_Sky",
    "VolumetricCloud": "Saskarta_Clouds",
    "ExponentialHeightFog": "Saskarta_Fog",
    "PPV_Saskarta_Grade_Storm": "Saskarta_GradeStorm",
    "PPV_Saskarta_Grade_Clear": "Saskarta_GradeClear",
}

# FSaskartaLookKey field (Python name) -> path in a look_keys.json key.
FIELD_PATHS = {
    "road_m": ("road_m",),
    "sun_pitch": ("sun", "pitch"),
    "sun_yaw": ("sun", "yaw"),
    "sun_intensity_lux": ("sun", "intensity_lux"),
    "sun_temperature_k": ("sun", "temperature_k"),
    "mie_scattering_scale": ("atmosphere", "mie_scattering_scale"),
    "mie_anisotropy": ("atmosphere", "mie_anisotropy"),
    "rayleigh_scattering_scale": ("atmosphere", "rayleigh_scale"),
    "cloud_coverage": ("clouds", "coverage"),
    "cloud_density": ("clouds", "density"),
    "cloud_base_km": ("clouds", "base_km"),
    "cloud_top_km": ("clouds", "top_km"),
    "fog_density": ("fog", "density"),
    "fog_falloff": ("fog", "falloff"),
    "fog_start_m": ("fog", "start_m"),
    "fog_second_density": ("fog", "second_density"),
    "fog_second_height_m": ("fog", "second_height_m"),
    "grade_storm_weight": ("grade", "storm_weight"),
    "grade_clear_weight": ("grade", "clear_weight"),
    "storm_intensity": ("storm_intensity",),
}


def _get(key, path):
    node = key
    for part in path:
        if not isinstance(node, dict) or part not in node:
            raise SystemExit(f"key {key.get('name', '?')!r} has no {'.'.join(path)}")
        node = node[part]
    return node


def key_to_fields(key):
    """One JSON key -> {FSaskartaLookKey Python property name: value}."""
    fields = {"name": str(_get(key, ("name",)))}
    for field, path in FIELD_PATHS.items():
        fields[field] = float(_get(key, path))
    # LANE4: the director multiplies FogColor by its fixed FogLuminanceScale (0.08, the same as
    # apply_look's default); a key's own fog "luminance" is baked into the stored colour so the
    # director and apply_look.py give the fog the same brightness.
    lum = float(key["fog"].get("luminance", FOG_LUMINANCE_SCALE))
    fields["fog_color"] = tuple(c * lum / FOG_LUMINANCE_SCALE for c in hex_to_linear(_get(key, ("fog", "color"))))
    return fields


def validate_keys(keys):
    """Check every field is present and road metres are unique; return the keys sorted by road metre."""
    if not keys:
        raise SystemExit("look_keys.json has no keys")
    for k in keys:
        key_to_fields(k)
    ordered = sorted(keys, key=lambda k: float(k["road_m"]))
    metres = [float(k["road_m"]) for k in ordered]
    if len(set(metres)) != len(metres):
        raise SystemExit(f"duplicate road_m in look keys: {metres}")
    return ordered


BUILD = """
import unreal
E = unreal.EditorAssetLibrary
full = '__FOLDER__/__ASSET__'
if E.does_asset_exist(full):
    da = unreal.load_asset(full)
else:
    f = unreal.DataAssetFactory()
    f.set_editor_property('data_asset_class', unreal.SaskartaLookKeys)
    da = unreal.AssetToolsHelpers.get_asset_tools().create_asset('__ASSET__', '__FOLDER__', unreal.SaskartaLookKeys, f)
KEYS = __KEYS__
arr = []
for k in KEYS:
    s = unreal.SaskartaLookKey()
    for n in k:
        v = k[n]
        if n == 'fog_color':
            v = unreal.LinearColor(v[0], v[1], v[2], 1.0)
        s.set_editor_property(n, v)
    arr.append(s)
da.set_editor_property('keys', arr)
back = da.get_editor_property('keys')
print('class ' + da.get_class().get_name() + ', keys ' + str(len(back)))
for s in back:
    print('  ' + str(s.get_editor_property('name')) + ' @ ' + str(s.get_editor_property('road_m')) + ' m, storm ' + str(s.get_editor_property('storm_intensity')))
print('saved ' + str(E.save_loaded_asset(da, False)))
"""

TAG = """
import unreal
TAGS = __TAGS__
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
found = {}
pk = []
for a in eas.get_all_level_actors():
    lab = a.get_actor_label()
    if lab in TAGS:
        found[lab] = found.get(lab, 0) + 1
        t = TAGS[lab]
        tags = list(a.tags)
        if t not in [str(x) for x in tags]:
            tags.append(unreal.Name(t))
            a.set_editor_property('tags', tags)
        pk.append(a.get_package())
        print(lab + ' -> ' + str([str(x) for x in a.tags]))
missing = [lab for lab in TAGS if found.get(lab, 0) != 1]
print('labels not found exactly once: ' + str(missing))
if not missing:
    print('saved ' + str(unreal.EditorLoadingAndSavingUtils.save_packages(pk, False)))
"""

READ = """
import unreal
TAGS = __TAGS__
full = '__FOLDER__/__ASSET__'
if unreal.EditorAssetLibrary.does_asset_exist(full):
    da = unreal.load_asset(full)
    for s in da.get_editor_property('keys'):
        print(str(s.get_editor_property('name')) + ' @ ' + str(s.get_editor_property('road_m')))
else:
    print('no asset ' + full)
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
for a in eas.get_all_level_actors():
    if a.get_actor_label() in TAGS:
        print(a.get_actor_label() + ' tags ' + str([str(x) for x in a.tags]))
"""


def _sub(text, **kw):
    for k, v in kw.items():
        text = text.replace(f"__{k}__", str(v))
    return check_banned(text)


def build_script(keys):
    return _sub(BUILD, FOLDER=FOLDER, ASSET=ASSET, KEYS=repr([key_to_fields(k) for k in keys]))


def tag_script():
    return _sub(TAG, TAGS=repr(ACTOR_TAGS))


def read_script():
    return _sub(READ, TAGS=repr(ACTOR_TAGS), FOLDER=FOLDER, ASSET=ASSET)


def run(script, label, dry_run=False):
    if dry_run:
        print(script)
        return ""
    ok, out, err = python_run(script)
    print(f"--- {label}: {'ok' if ok else 'FAILED'}")
    if out.strip():
        print(out.rstrip())
    if not ok:
        print(err, file=sys.stderr)
        raise SystemExit(1)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("step", choices=["build", "tag-actors", "read"])
    ap.add_argument("--keys", default=str(HERE / "look_keys.json"))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    if a.step == "build":
        run(build_script(validate_keys(load_keys(a.keys))), "build " + ASSET, a.dry_run)
    elif a.step == "tag-actors":
        run(tag_script(), "tag actors", a.dry_run)
    else:
        run(read_script(), "read", a.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
