"""Catch free HLSL identifiers that lack a Custom-node input before an editor build."""

import ast
import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
ENGINE_SYMBOLS = {"SceneTextureLookup", "ViewportUVToSceneTextureUV", "View", "ViewToClip"}


def assigned_literal(source, name):
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"no literal {name} found in material builder")


def free_capitalized_names(shader):
    code = re.sub(r"/\*.*?\*/|//[^\n]*", "", shader, flags=re.S)
    names = set(re.findall(r"\b[A-Z][A-Za-z0-9_]*\b", code))
    declared = set(re.findall(
        r"\b(?:float[1-4]?|uint[1-4]?|int[1-4]?|void|struct|FSensor|FGlass)\s+([A-Z][A-Za-z0-9_]*)\b",
        code,
    ))
    return names - declared - ENGINE_SYMBOLS


@pytest.mark.parametrize(
    "shader_path,builder_path,pins_name,embedded",
    [
        ("Shaders/SensorCRT.hlsl", "Tools/Look/build_sensor_crt.py", "pins", "MATERIAL"),
        ("Shaders/SensorGlass.ush", "Tools/Look/build_sensor_glass.py", "PINS", None),
    ],
)
def test_shader_free_inputs_have_custom_pins(shader_path, builder_path, pins_name, embedded):
    builder = (ROOT / builder_path).read_text(encoding="utf-8")
    if embedded:
        builder = assigned_literal(builder, embedded)
    pins = set(assigned_literal(builder, pins_name))
    used = free_capitalized_names((ROOT / shader_path).read_text(encoding="utf-8"))
    assert not (used - pins), f"{shader_path}: unbound Custom inputs {sorted(used - pins)}"
