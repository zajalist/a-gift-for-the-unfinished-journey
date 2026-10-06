"""The material graph of M_Saskarta_SteleFace, evaluated numerically (Tools/Look/stele_scan_preview.py Graph).

These check what the graph computes, not the engine: that the scan emissive is exactly 0 when idle,
that the sweep line runs top to bottom at the right time, that grooves light only after the line has
passed and fade after the hold, that a stone without Custom Primitive Data (CellRect 0) shows no glyph
and no NaN, and that POM moves the carved texels only inside the cell.

Run: python -m pytest Tools/Look/tests/test_stele_scan_preview.py -q -p no:cacheprovider
"""
import pathlib
import sys

import numpy as np
import pytest

LOOK = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LOOK))

import build_stele_scan as bss  # noqa: E402
import stele_scan_preview as ssp  # noqa: E402


@pytest.fixture(scope="module")
def textures():
    return ssp.load_textures()


def face_env(v_rows=64, u_cols=24, time=10.0, scan=(0.0, 0.0, 0.0), rect=None, cell=1, wear=0.2):
    """A straight-on grid over the WayStone_A face: UV1 0..1, camera 3 m in front."""
    data = bss.load_data()
    rect = rect if rect is not None else data["meshes"]["SM_Stele_WayStone_A"]["cell_rect_uv1"]
    u, v = np.meshgrid((np.arange(u_cols) + 0.5) / u_cols, (np.arange(v_rows) + 0.5) / v_rows)
    shape = u.shape
    return {
        "uv1": np.stack([u, v], -1).astype(np.float32),
        "uv0": np.stack([u * 0.46, v * 1.36], -1).astype(np.float32),
        "depth": np.full(shape + (1,), 300.0, np.float32),
        "camv": np.broadcast_to(np.array([0.0, 0.0, 1.0], np.float32), shape + (3,)).copy(),
        "N": np.array([0, 0, 1.0], np.float32), "T": np.array([1.0, 0, 0], np.float32),
        "B": np.array([0, -1.0, 0], np.float32),
        "time": time,
        "cpd": [wear, float(cell), scan[0], scan[1]] + list(rect) + [scan[2]],
        "vc": np.zeros(shape + (3,), np.float32),
        "noise": np.full(shape + (1,), 0.5, np.float32),
    }


def emissive(textures, **kw):
    tex, mips = textures
    return ssp.Graph(face_env(**kw), tex, mips).get("emis")


def test_idle_emissive_is_exactly_zero(textures):
    e = emissive(textures, time=123.0, scan=(0.0, 0.0, 0.0))
    assert np.all(e == 0.0)


def test_sweep_runs_top_to_bottom(textures):
    rows = []
    for t in (0.2, 0.7, 1.2):
        e = emissive(textures, time=10.0 + t, scan=(10.0, 1.0, 7.4)).sum(-1)
        band = e[:, :2].mean(axis=1)                            # per row (v), at the face's left edge: no ink
        rows.append(int(np.argmax(band)))
        assert band.max() > 0
    assert rows[0] < rows[1] < rows[2], rows                    # v grows: the line moves down the face
    assert rows[1] / 64 == pytest.approx(0.7 / 1.4, abs=0.05)


def test_grooves_glow_after_the_line_and_fade_after_the_hold(textures):
    tex, mips = textures
    env = face_env(time=10.0 + 3.0, scan=(10.0, 1.0, 7.4))
    g = ssp.Graph(env, tex, mips)
    cut = g.get("cut")[..., 0]
    e = g.get("emis").sum(-1)
    assert cut.max() > 0.3
    assert e[cut > 0.3].mean() > 5 * max(e[cut < 0.01].mean(), 1e-6)   # held: only the grooves are lit
    late = emissive(textures, time=10.0 + 7.4 + 2.6, scan=(10.0, 1.0, 7.4))
    assert np.all(late == 0.0)                                  # after hold + fade: nothing


def test_match_is_dimmer_and_shorter(textures):
    full = emissive(textures, time=10.7, scan=(10.0, 1.0, 7.4)).max()      # both lines at v = 0.5
    match = emissive(textures, time=10.3, scan=(10.0, 0.5, 0.0)).max()
    assert 0 < match < full
    assert np.all(emissive(textures, time=10.0 + 0.6 + 0.3 + 2.6, scan=(10.0, 0.5, 0.0)) == 0.0)


def test_no_cpd_means_no_glyph_and_no_nan(textures):
    tex, mips = textures
    g = ssp.Graph(face_env(rect=[0.0, 0.0, 0.0, 0.0], cell=0), tex, mips)
    for key in ("bfin", "nnorm", "aol", "emis", "rl"):
        assert np.isfinite(g.get(key)).all(), key
    assert np.all(g.get("incell") == 0.0)
    assert np.all(g.get("cut") == 0.0)


def test_pom_moves_uvs_only_inside_the_cell(textures):
    tex, mips = textures
    env = face_env(v_rows=96, u_cols=36)
    env["camv"] = np.broadcast_to(np.array([0.5, 0.2, 0.84], np.float32) / np.linalg.norm([0.5, 0.2, 0.84]),
                                  env["uv1"].shape[:-1] + (3,)).copy()
    g = ssp.Graph(env, tex, mips)
    shift = np.abs(g.get("usepom") - g.get("auv")).sum(-1)
    inside = g.get("incell")[..., 0] > 0.5
    assert shift[~inside].max() < 1e-6
    assert shift[inside].max() > 0                              # oblique: carved texels move
    lo, hi = g.get("omin"), g.get("omax")
    puv = g.get("usepom")
    assert np.all(puv >= lo - 1e-7) and np.all(puv <= hi + 1e-7)  # never outside its own cell
