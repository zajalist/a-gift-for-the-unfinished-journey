"""CPU checks for the acoustic point cloud (Shaders/AuxSensors.hlsl).

Tools/Drone/aux_feed_preview.py carries a line-by-line numpy port of the shader; these
tests run that port instead of Unreal's custom-material shader.
"""

import math
import re
from pathlib import Path

import numpy as np
import pytest

from Tools.Drone import aux_feed_preview as feed
from Tools.Drone import build_aux_material

ROOT = Path(__file__).resolve().parents[3]
SHADER_PATH = ROOT / "Shaders" / "AuxSensors.hlsl"
CPP = ROOT / "Plugins/SaskartaCore/Source/SaskartaCore/Private/SaskartaDroneSequence.cpp"
SPEED = build_aux_material.SCALARS["PingSpeed"]
FADE = build_aux_material.SCALARS["Fade"]


def energy_at(distance_cm, clock, ping_times):
    """Summed ping energy at a surface distance_cm from every (static) ping origin."""
    total = np.zeros_like(np.asarray(distance_cm, dtype=float))
    for t in sorted(ping_times, reverse=True)[:3]:
        total = total + feed.ping_energy(clock - t - np.asarray(distance_cm) / SPEED, FADE)
    return total


def test_runtime_cadence_is_steady_and_slow():
    body = re.search(r"float SaskartaDroneLogic::PingPeriodSeconds\(\)\s*\{\s*return ([\d.]+)f;", CPP.read_text())
    assert body, "PingPeriodSeconds() must be a fixed constant with no edge inputs"
    assert 2.5 <= float(body.group(1)) <= 4.0
    assert float(body.group(1)) == feed.PERIOD


def test_front_reveals_a_surface_only_when_it_arrives_at_60_m_per_s():
    assert SPEED == pytest.approx(6000.0)
    arrival = 3000.0 / SPEED
    assert energy_at(3000.0, arrival - 0.01, [0.0]) == pytest.approx(0.0, abs=1e-9)
    assert energy_at(3000.0, arrival + 0.03, [0.0]) > 0.8


def test_memory_fades_over_six_to_eight_seconds():
    ages = [0.05, 0.5, 1.5, 3.0, 6.0]
    values = [float(feed.ping_energy(np.array(a), FADE)) for a in ages]
    assert all(a > b for a, b in zip(values, values[1:]))
    assert values[-1] > 0.0
    assert float(feed.ping_energy(np.array(FADE + 0.01), FADE)) == pytest.approx(0.0, abs=1e-9)
    assert 6.0 <= FADE <= 8.0


def test_three_pings_accumulate():
    single = energy_at(2000.0, 6.8, [6.0])
    three = energy_at(2000.0, 6.8, [0.0, 3.0, 6.0])
    assert three > single


def test_view_never_pulses_as_a_whole():
    # Steady 3 s pings. Mean brightness over surfaces 0-90 m must never drop to black
    # between pings, nor jump frame to frame like the old strobe.
    distances = np.linspace(100.0, 9000.0, 400)
    times = np.arange(6.0, 15.0, 1 / 60)
    means = []
    for t in times:
        pings = [p for p in np.arange(0.0, 16.0, feed.PERIOD) if p <= t]
        means.append(float(feed.brightness(energy_at(distances, t, pings)).mean()))
    means = np.array(means)
    assert means.min() > 0.3 * means.max()
    assert np.abs(np.diff(means)).max() < 0.05 * means.max()


def test_zero_params_stay_finite():
    wp, normal, depth, stencil, cam = _wall_scene()
    params = dict(feed.PARAMS, PingSpeed=0.0, Fade=0.0, GridCm=0.0)
    out = feed.shade(wp, normal, depth, stencil, cam, 1.0, [(0, 0, 0, 0.0)] + [feed.EMPTY] * 2,
                     (0, 0, 0), (1, 0, 0), params)
    assert np.isfinite(out).all()


def _wall_scene(w=240, h=135):
    """A camera 10 m from a wall facing it, with sky above the wall."""
    cam = np.array([0.0, 0.0, 170.0])
    u = (np.arange(w) + 0.5) / w * 2 - 1
    v = ((np.arange(h) + 0.5) / h * 2 - 1) * h / w
    rays = np.stack(np.broadcast_arrays(np.ones((h, w)), -u[None, :] * 0.8, -v[:, None] * 0.8), -1)
    rays /= np.linalg.norm(rays, axis=-1, keepdims=True)
    t = 1000.0 / rays[..., 0]
    wp = cam + rays * t[..., None]
    sky = wp[..., 2] > 400.0
    depth = np.where(sky, 1e7, t)
    normal = np.broadcast_to(np.array([-1.0, 0.0, 0.0]), wp.shape).copy()
    return wp, normal, depth, np.zeros((h, w)), cam


def test_dots_are_small_round_and_skip_the_sky():
    wp, normal, depth, stencil, cam = _wall_scene()
    out = feed.shade(wp, normal, depth, stencil, cam, 0.3, [(0, 0, 170, 0.0)] + [feed.EMPTY] * 2,
                     (0, 0, 0), (1, 0, 0))
    lum = out.max(-1)
    lit = lum > 0.5 * lum.max()
    assert not lum[depth > 999000.0].any()
    assert 0.01 < lit[depth < 999000.0].mean() < 0.2
    # constant screen size: no lit run wider than ~3 px in either direction
    for grid in (lit, lit.T):
        runs = [len(m.group()) for row in grid for m in re.finditer("1+", "".join("1" if x else "0" for x in row))]
        assert max(runs) <= 3


def test_custom_material_input_contract_covers_shader_free_variables():
    shader = SHADER_PATH.read_text(encoding="utf-8")
    input_comment = re.search(r"// Inputs:(.*?)\n// PingA", shader, re.DOTALL).group(1)
    declared = set(re.findall(r"\b[A-Za-z_]\w*\b", input_comment))
    builder_pins = {*build_aux_material.SCENE_PINS, *build_aux_material.SCALARS, *build_aux_material.VECTORS}
    code = re.sub(r"//.*", "", shader)
    locals_ = set(re.findall(r"\b(?:float[234]?|int)\s+(\w+)\b", code))
    identifiers = set(re.findall(r"\b[A-Za-z_]\w*\b", code))
    known = builder_pins | locals_ | {
        "float", "float2", "float3", "float4", "int", "for", "if", "return", "max", "min", "length",
        "step", "smoothstep", "abs", "floor", "frac", "dot", "ddx", "lerp", "saturate", "exp", "exp2",
        "log2", "sqrt", "normalize", "sign", "cross", "ceil", "x", "y", "z", "w", "r", "xy", "yz", "xyz", "yzx", "zxy",
        "yxz", "xxy", "yxx", "zyx", "e",
    }
    assert declared == builder_pins
    assert identifiers - known == set()
    assert "Period" not in builder_pins and "PingTime" not in builder_pins
    assert all(len(v) == 4 and v[3] < -1000 for k, v in build_aux_material.VECTORS.items() if k.startswith("Ping"))
    assert not math.isnan(build_aux_material.SCALARS["DotPx"])
