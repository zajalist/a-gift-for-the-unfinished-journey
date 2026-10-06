import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import gpu_budget as g  # noqa: E402

P = "[2026.09.27-17.21.59:381][624]LogRHI: Display:     "


def row(depth, name, ms):
    cols = "┃     0 │      0 │    0 │    0 │  1.0% ┊          │ 0.000 ms "
    incl = f"┃     0 │      0 │    0 │    0 │  1.0% ┊          │ {ms:.3f} ms "
    return P + cols + incl + "┃ " + " " * depth + name + "   ┃\n"


def dump(rows, frame_ms=5.0):
    lines = [P.rstrip() + " Copy pipeline 0 - GPU 0\n", P + "No recorded work for this queue.\n",
             P.rstrip() + " Compute pipeline 0 - GPU 0\n", row(0, "<root>", 0.01),
             "[x][1]LogRHI: Display: GPU Profile for Frame 7 - Graphics pipeline 0 - GPU 0\n",
             f"[x][1]LogRHI: Display:     - Frame Time                    : {frame_ms}ms\n"]
    return lines + [row(d, n, ms) for d, n, ms in rows]


SCENE = [(0, "<root>", 5.0), (3, "Frame 7", 5.0), (6, "Scene 1600x900", 4.8),
         (9, "BasePass", 1.2), (9, "VolumetricCloud", 0.5), (12, "CloudShadow", 0.1),
         (12, "RenderVolumetricCloud 800x450", 0.3), (9, "ExponentialHeightFog 1600x900", 0.08),
         (9, "VolumetricFog", 0.2), (9, "RenderSkyAtmosphereLUTs", 0.04),
         (9, "SkyAtmosphere 1600x900", 0.05), (9, "CaptureConvolveSkyEnvMap", 0.3),
         (9, "PostProcessing", 0.6)]


def test_parse_row_reads_inclusive_ms_and_depth():
    depth, name, ms = g.parse_row(row(6, "VolumetricFog", 0.2))
    assert name == "VolumetricFog" and ms == 0.2 and depth == 7


def test_summarize_counts_topmost_match_once():
    rep = g.report(g.split_dumps(dump(SCENE)))
    s = rep["samples"][0]
    assert s["scene_rendered"] is True
    assert s["ms"]["clouds"] == 0.5          # children of VolumetricCloud not re-counted
    assert s["ms"]["fog"] == 0.28
    assert s["ms"]["sky"] == 0.09
    assert s["ms"]["skylight"] == 0.3
    assert s["ms"]["sky_fog_clouds"] == 0.87
    assert s["ms"]["with_skylight"] == 1.17
    assert s["resolution"] == "1600x900"
    assert s["frame_ms"] == 5.0
    assert rep["within_budget"] is True


def test_several_dumps_take_the_median():
    lines = dump(SCENE) + dump([(0, "<root>", 5.0), (3, "BasePass", 1.0), (3, "VolumetricCloud", 0.9)]) \
        + dump([(0, "<root>", 5.0), (3, "BasePass", 1.0), (3, "VolumetricCloud", 2.0)])
    rep = g.report(g.split_dumps(lines))
    assert len(rep["samples"]) == 3
    assert rep["median_ms"]["clouds"] == 0.9
    assert rep["median_ms"]["sky_fog_clouds"] == 0.9


def test_slate_only_frame_gives_no_verdict():
    rep = g.report(g.split_dumps(dump([(0, "<root>", 0.23), (3, "RenderGraphExecute - Slate", 0.15)])))
    assert rep["scene_rendered"] is False
    assert rep["within_budget"] is None
    assert rep["median_ms"] == {}
