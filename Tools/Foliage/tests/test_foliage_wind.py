"""Offline checks for Shaders/FoliageWind.hlsl (world sprint, Task V4).

    python -m pytest Tools/Foliage/tests -q

The file is pasted verbatim into a Custom node by Tools/Foliage/build_wind_nodes.py,
through Hayba python_run, so it must survive that trip: ASCII, no quotes or
backslashes, no words the python_run policy scanner refuses. It must also compile
as a function body (checked with dxc when the Vulkan SDK's dxc is on PATH), and
its maths must keep the plant base planted and the sway bounded.
"""
import math
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
HLSL = ROOT / "Shaders" / "FoliageWind.hlsl"

# The brief's function body, verbatim (task-V4-brief.md, Step 2).
BRIEF_BODY = [
    "float3 dir = normalize(float3(WindDir.xy, 0) + 1e-4);",
    "float phase = dot(WorldPos.xy, dir.xy) * 0.002 + PerInstanceRandom * 6.2831;",
    "float gust = 0.6 + 0.4 * sin(Time * 0.35 + phase * 0.5 + Gust);",
    "float sway = sin(Time * 1.3 + phase) * Strength * gust * Height01 * Height01;",
    "float flutter = sin(Time * 7.0 + dot(LocalPos, float3(0.07, 0.05, 0.11)) + phase * 3.0) * 0.15 * Strength * Height01;",
    "return dir * (sway * 35.0) + float3(0, 0, -abs(sway) * 6.0) + dir.yxz * float3(1, -1, 0) * flutter * 12.0;",
]
PINS = "float3 WorldPos, float3 LocalPos, float Height01, float PerInstanceRandom, float Time, float3 WindDir, float Strength, float Gust"


def code_lines():
    return [l.strip() for l in HLSL.read_text(encoding="ascii").splitlines() if l.strip() and not l.strip().startswith("//")]


def test_body_is_the_brief_verbatim():
    assert code_lines() == BRIEF_BODY


def test_body_survives_python_run():
    text = HLSL.read_text(encoding="ascii")
    for bad in ['"', "'", "\\", "#", "try", "getattr", "open(", ".replace(", "new_level(", "import time"]:
        assert bad not in text, bad


@pytest.mark.skipif(shutil.which("dxc") is None, reason="dxc not on PATH")
def test_body_compiles_as_a_function(tmp_path):
    src = tmp_path / "wind.hlsl"
    src.write_text(
        "float3 SaskartaWind(" + PINS + ") {\n" + HLSL.read_text(encoding="ascii") + "\n}\n"
        "float4 main(float4 p : POSITION, float4 q : TEXCOORD0) : SV_Position {\n"
        "  return float4(SaskartaWind(p.xyz, q.xyz, q.w, p.w, q.x, float3(1, 0.3, 0), 0.5, 0.2), 1);\n}\n",
        encoding="ascii")
    r = subprocess.run(["dxc", "-T", "vs_6_0", "-E", "main", str(src), "-Fo", str(tmp_path / "w.bin")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def wind(world, local, h01, rnd, t, wdir, strength, gust):
    """Python port of the body (float3 as tuples), for the numeric checks."""
    d = (wdir[0], wdir[1], 0.0)
    d = tuple(c + 1e-4 for c in d)
    n = math.sqrt(sum(c * c for c in d))
    d = tuple(c / n for c in d)
    phase = (world[0] * d[0] + world[1] * d[1]) * 0.002 + rnd * 6.2831
    g = 0.6 + 0.4 * math.sin(t * 0.35 + phase * 0.5 + gust)
    sway = math.sin(t * 1.3 + phase) * strength * g * h01 * h01
    flutter = math.sin(t * 7.0 + local[0] * 0.07 + local[1] * 0.05 + local[2] * 0.11 + phase * 3.0) * 0.15 * strength * h01
    swz = (d[1], d[0], d[2])
    return tuple(d[i] * sway * 35.0 + (0, 0, -abs(sway) * 6.0)[i] + swz[i] * (1, -1, 0)[i] * flutter * 12.0 for i in range(3))


def samples():
    for t in [0.0, 0.37, 1.0, 2.5, 13.0, 600.0]:
        for rnd in [0.0, 0.5, 0.93]:
            yield (381000.0 + rnd * 900, 412000.0, -3000.0), (20.0, -5.0, 150.0), rnd, t


def test_base_stays_planted():
    for world, local, rnd, t in samples():
        assert max(abs(c) for c in wind(world, local, 0.0, rnd, t, (1, 0.3, 0), 1.0, 0.7)) < 1e-9


def test_no_wind_no_motion():
    for world, local, rnd, t in samples():
        assert max(abs(c) for c in wind(world, local, 1.0, rnd, t, (1, 0.3, 0), 0.0, 0.7)) < 1e-9


def test_full_wind_is_bounded_and_moves():
    peak = 0.0
    for world, local, rnd, t in samples():
        o = wind(world, local, 1.0, rnd, t, (1, 0.3, 0), 1.0, 0.7)
        peak = max(peak, math.sqrt(sum(c * c for c in o)))
    # sway <= 35 cm, dip <= 6 cm, flutter <= 1.8 cm
    assert 5.0 < peak < 43.0


def test_offset_changes_over_one_second():
    a = wind((381000.0, 412000.0, 0.0), (0, 0, 150), 1.0, 0.3, 10.0, (1, 0.3, 0), 0.6, 0.0)
    b = wind((381000.0, 412000.0, 0.0), (0, 0, 150), 1.0, 0.3, 11.0, (1, 0.3, 0), 0.6, 0.0)
    assert math.dist(a, b) > 1.0
