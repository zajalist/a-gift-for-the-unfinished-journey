"""Tests for Tools/Look/build_ember_material.py and Shaders/EmberFire.hlsl (Task L5), offline.

  - the HLSL survives the trip into python_run (ASCII, no quotes/backslashes/defines, no text the
    policy scanner refuses, even after it strips whitespace and lowercases);
  - every Custom-node pin the material wires is read by the code, and the pin list is the
    order the builder connects;
  - at most 8 texture samples (the brief's budget stand-in);
  - the editor scripts carry the HLSL verbatim, the parameter names and #C8703A in linear;
  - the HLSL compiles under FXC ps_5_0 with warnings as errors inside a mock of UE's Custom
    wrapper (skipped when no fxc is installed).

Run: python -m pytest Tools/Look/tests -q -p no:cacheprovider --basetemp <scratch dir>
"""
import pathlib
import sys

import pytest

LOOK = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LOOK))

import build_ember_material as b  # noqa: E402
from apply_look import BANNED  # noqa: E402

HLSL = b.HLSL_PATH.read_text(encoding="utf-8")


def test_hlsl_is_clean_for_python_run():
    assert b.hlsl_problems(HLSL) == []


def test_hygiene_catches_bad_text():
    assert "double quote" in b.hlsl_problems(HLSL + ' "x" ')
    assert any("banned" in p for p in b.hlsl_problems(HLSL + "\nfloat Retry = 0;"))
    assert any("banned" in p for p in b.hlsl_problems(HLSL + "\nfloat q = e val (1);".replace(" ", "")))
    assert "backslash" in b.hlsl_problems(HLSL + "\\")


def test_samples_within_budget():
    assert b.texture_sample_count(HLSL) <= b.MAX_SAMPLES


def test_pins_and_parameters():
    assert b.CUSTOM_PINS == ["UV", "Tex", "Time", "Ignite", "Burn", "EmberColor", "Fade"]
    names = [n for n, _ in b.SCALARS]
    assert names == ["Ignite", "Burn", "Time", "TimeScale"]
    assert dict(b.SCALARS)["TimeScale"] == 1.0
    assert b.TEXTURE_PARAM == "Texture"


def test_ember_colour_is_board_accent_in_linear():
    r, g, bl = b.EMBER_LINEAR
    assert b.EMBER_HEX == "#C8703A"
    assert abs(r - 0.578) < 0.002 and abs(g - 0.162) < 0.002 and abs(bl - 0.0423) < 0.002


def test_editor_script_embeds_hlsl_verbatim_and_passes_banned_check():
    script = b.editor_script(HLSL)
    assert HLSL in script
    assert "__HLSL__" not in script and "__ASSET_PATH__" not in script
    assert not [w for w in BANNED if w in script]
    assert "/Game/SaskartaGaea/GameFlow/UI/M_UI_EmberFire" in script
    assert "BLEND_TRANSLUCENT" in script and "MD_UI" in script and "CMOT_FLOAT4" in script
    for pin in b.CUSTOM_PINS:
        assert repr(pin) in script


def test_side_scripts_pass_banned_check():
    for script in (b.fonts_script(), b.defaults_script(0.2, 0.5)):
        assert not [w for w in BANNED if w in script]
    assert "F_Cinzel" in b.fonts_script() and "F_Cormorant" in b.fonts_script()
    assert "0.2" in b.defaults_script(0.2, 0.5) and "0.5" in b.defaults_script(0.2, 0.5)


@pytest.mark.skipif(b.find_fxc() is None, reason="fxc not installed")
def test_hlsl_compiles_offline():
    ok, slots, log = b.fxc_stats(HLSL)
    assert ok, log
    assert slots is not None and slots <= b.MAX_INSTRUCTIONS
