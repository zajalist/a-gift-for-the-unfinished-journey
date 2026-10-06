"""Tests for Tools/Look/build_look_keys_asset.py (Task L7).

The script turns Tools/Look/look_keys.json into DA_Saskarta_LookKeys, an asset of the C++
class USaskartaLookKeys (Plugins/SaskartaCore/.../SaskartaLookKeys.h), and tags the level's
lighting actors for USaskartaLightingDirector. These tests run offline:
  - each JSON key maps to exactly the UPROPERTYs of FSaskartaLookKey (read from the header),
    in the units the director expects;
  - keys are validated (sorted, unique road metres, every field present);
  - the editor scripts pass python_run's banned-word check and carry every key and tag;
  - the tag map covers exactly the tags the director looks for (read from the .cpp).

Run: python -m pytest Tools/Look/tests -q -p no:cacheprovider --basetemp <scratch dir>
"""
import copy
import pathlib
import re
import sys

import pytest

LOOK = pathlib.Path(__file__).resolve().parents[1]
ROOT = LOOK.parents[1]
SRC = ROOT / "Plugins" / "SaskartaCore" / "Source" / "SaskartaCore"
sys.path.insert(0, str(LOOK))

import build_look_keys_asset as b  # noqa: E402
from apply_look import BANNED, load_keys  # noqa: E402


def snake(name):
    """UE Python's name conversion for these properties: CamelCase -> snake_case."""
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name).lower()


def header_fields():
    text = (SRC / "Public" / "SaskartaLookKeys.h").read_text(encoding="utf-8")
    struct = text.split("struct SASKARTACORE_API FSaskartaLookKey", 1)[1].split("};", 1)[0]
    names = re.findall(r"UPROPERTY\([^)]*\)\s*\n\s*[\w<>]+\s+(\w+)", struct)
    return {snake(n) for n in names}


def test_fields_match_the_cpp_struct():
    keys = load_keys()
    fields = b.key_to_fields(keys[0])
    assert set(fields) == header_fields()
    assert len(fields) == 22


def test_valley_values_and_units():
    valley = b.key_to_fields(load_keys()[0])
    assert valley["name"] == "Valley"
    assert valley["road_m"] == 0.0
    assert valley["sun_pitch"] == -8.0
    # Act I keeps its calmer lighting and storm values while the distance veil starts at 650 m.
    assert valley["sun_intensity_lux"] == 2.6
    assert valley["sun_temperature_k"] == 3000.0
    assert valley["mie_scattering_scale"] == 0.009
    assert valley["rayleigh_scattering_scale"] == 0.0331
    assert valley["cloud_base_km"] == 0.95 and valley["cloud_top_km"] == 4.0
    # The second ground dust layer keeps its valley anchor; the main layer hides distant terrain.
    assert valley["fog_start_m"] == 650.0 and valley["fog_second_height_m"] == 55.2
    assert valley["fog_density"] == pytest.approx(0.06) and valley["fog_falloff"] == 0.0
    assert valley["grade_storm_weight"] == 1.0 and valley["grade_clear_weight"] == 0.0
    assert valley["storm_intensity"] == 0.28
    # FOG2 ochre #8C7040 as linear x (luminance 0.156 / 0.08): the director multiplies by 0.08, so the key's luminance is baked in
    r, g, bb = valley["fog_color"]
    assert r == pytest.approx(0.26225 * 0.156 / 0.08, abs=5e-3)
    assert g == pytest.approx(0.16203 * 0.156 / 0.08, abs=5e-3)
    assert bb == pytest.approx(0.05127 * 0.156 / 0.08, abs=5e-3)


def test_validate_accepts_the_real_keys_in_road_order():
    keys = b.validate_keys(load_keys())
    assert [k["name"] for k in keys] == ["Valley", "ValleyHold", "Ridge", "BasinPeak", "BasinHold", "Cistern", "CisternHold", "Stair", "InCloud", "PreDawn"]


def test_validate_sorts_by_road_m():
    keys = load_keys()
    shuffled = list(reversed(keys))
    assert [k["road_m"] for k in b.validate_keys(shuffled)] == [0, 900, 1500, 2150, 2700, 2950, 3250, 3650, 4350, 4550]


def test_validate_rejects_duplicate_road_m():
    keys = load_keys()
    keys[1]["road_m"] = 0
    with pytest.raises(SystemExit):
        b.validate_keys(keys)


def test_validate_rejects_a_missing_field():
    keys = copy.deepcopy(load_keys())
    del keys[2]["fog"]["second_density"]
    with pytest.raises(SystemExit):
        b.validate_keys(keys)


def test_build_script_is_python_run_safe_and_carries_every_key():
    script = b.build_script(b.validate_keys(load_keys()))
    assert not [w for w in BANNED if w in script]
    for name in ("Valley", "ValleyHold", "Ridge", "BasinPeak", "BasinHold", "Cistern", "CisternHold", "Stair", "InCloud", "PreDawn"):
        assert f"'{name}'" in script
    assert "unreal.SaskartaLookKeys" in script
    assert "unreal.SaskartaLookKey()" in script
    assert "DA_Saskarta_LookKeys" in script
    compile(script, "build_script", "exec")


def test_tag_map_covers_exactly_the_director_tags():
    cpp = (SRC / "Private" / "SaskartaLightingDirector.cpp").read_text(encoding="utf-8")
    tags = set(re.findall(r'USaskartaLightingDirector::Tag\w+\(TEXT\("(\w+)"\)\)', cpp))
    assert len(tags) == 6
    assert set(b.ACTOR_TAGS.values()) == tags


def test_tag_script_is_python_run_safe():
    script = b.tag_script()
    assert not [w for w in BANNED if w in script]
    for label, tag in b.ACTOR_TAGS.items():
        assert label in script and tag in script
    compile(script, "tag_script", "exec")
