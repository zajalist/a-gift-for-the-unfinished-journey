"""Offline tests for Tools/Story/build_inscription_atlas.py and the data it packs (docs/story/inscriptions.json).

1. layout: power-of-two cells, square texels, 1 atlas UV = 400 cm, cells start on multiples of their size.
2. packing: every carved inscription gets a stable cell, a flat pad of at least pad_cm, the ink inside
   its cell minus the pad, nothing outside the used cells; an oversized ink is scaled down to fit.
3. mip safety: box mips 0..5 keep every cell's outer ring flat (no ink reaches a neighbour through
   filtering), and no mip texel straddles two cells up to mip 8.
4. the normal atlas describes the same surface as the height atlas.
5. the committed atlas files are up to date (--check), and inscriptions.json keeps its rules: 36 steles,
   known inscriptions, no Saskartan text in a row still waiting for the author.

Run: python -m pytest Tools/Story/tests/test_build_inscription_atlas.py -q -p no:cacheprovider
"""
import json
import pathlib
import re
import sys

import numpy as np
import pytest
from PIL import Image

STORY = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(STORY))

import build_inscription_atlas as bia  # noqa: E402

ROOT = STORY.parents[1]


@pytest.fixture(scope="module")
def real():
    data = bia.load_json(bia.DATA)
    H, N, AO, manifest, new_data, L = bia.build(data, bia.load_json(bia.STELES))
    return data, H, N, AO, manifest, new_data, L


# ------------------------------------------------------------------------------------------------ 1
def test_layout_constants():
    L = bia.layout(bia.DEFAULT_ATLAS)
    assert (L["cw"], L["ch"]) == (256, 512)
    assert L["px_per_cm"] == pytest.approx(5.12)
    assert L["cm_per_uv"] == pytest.approx(400.0)            # the same on both axes: Height Ratio = depth / 400
    assert L["cells"] == 32


@pytest.mark.parametrize("bad", [{"size_px": [2000, 2048]}, {"grid": [8, 3]}, {"cell_cm": [50.0, 90.0]}])
def test_layout_refuses_bad_atlases(bad):
    with pytest.raises(SystemExit):
        bia.layout({**bia.DEFAULT_ATLAS, **bad})


def test_cells_are_stable_and_new_ones_take_the_lowest_free():
    rows = [{"id": "A", "atlas_cell": 5}, {"id": "B"}, {"id": "C"}, {"id": "D", "atlas_cell": None}]
    got = bia.assign_cells(rows, ["A", "B", "C"], 32, previous={"C": 0})
    assert got == {"A": 5, "C": 0, "B": 1}
    with pytest.raises(SystemExit):
        bia.assign_cells([{"id": "A", "atlas_cell": 3}, {"id": "B", "atlas_cell": 3}], ["A", "B"], 32)
    with pytest.raises(SystemExit):
        bia.assign_cells([{"id": "A", "atlas_cell": 40}], ["A"], 32)


# ------------------------------------------------------------------------------------------------ 2
def test_real_inscriptions_are_packed(real):
    data, H, N, AO, manifest, new_data, L = real
    cells = manifest["cells"]
    # every text with the author's Saskartan is carved (W rows from a placeholder until his scan exists)
    assert {"I02", "I05"} <= set(cells)
    assert set(cells) == {r["id"] for r in data["inscriptions"] if r["status"] != "awaiting_author"}
    assert len({e["cell"] for e in cells.values()}) == len(cells)
    for gid, e in cells.items():
        assert e["pad_min_cm"] >= data["atlas"]["pad_cm"] - 1e-6, gid
        assert e["min_height"] < 0.2, f"{gid}: the cut lost its depth in the resample"
        u0, v0, su, sv = e["cell_uv_rect"]
        iu, iv, isu, isv = e["ink_uv_rect"]
        assert u0 <= iu and iu + isu <= u0 + su and v0 <= iv and iv + isv <= v0 + sv, gid
    assert cells["I05"]["fit_scale"] == 1.0                     # the way-stone ink fits as carved
    assert 0.9 < cells["I02"]["fit_scale"] < 1.0                # the dock ink is shrunk to keep the pad
    used = np.zeros(H.shape, bool)
    for e in cells.values():
        x0, y0 = bia.cell_origin_px(e["cell"], L)
        used[y0:y0 + L["ch"], x0:x0 + L["cw"]] = True
    assert np.all(H[~used] == 1.0), "ink outside the used cells"


def test_oversized_ink_is_scaled_to_keep_the_pad():
    L = bia.layout(bia.DEFAULT_ATLAS)
    src = np.ones((2240, 1400), np.float32)
    src[96:-96, 96:-96] = 0.0                                   # ink fills the whole map inside the carve pad
    cell, s, ink = bia.fit_glyph(src, (1208, 2048), [60.0, 110.0], L, 6.0)
    assert s < 1.0
    pad = min(ink[0], ink[1], L["cw"] - ink[2], L["ch"] - ink[3]) / L["px_per_cm"]
    assert pad >= 6.0
    border = np.concatenate([cell[:25, :].ravel(), cell[-25:, :].ravel(), cell[:, :25].ravel(), cell[:, -25:].ravel()])  # pad minus the filter reach
    assert border.min() > 0.99


# ------------------------------------------------------------------------------------------------ 3
def test_mips_keep_cells_apart(real):
    _data, H, _N, _AO, manifest, _new, L = real
    for level in range(0, 6):
        m = bia.box_mip(H, level)
        f = 2 ** level
        cw, ch = L["cw"] // f, L["ch"] // f
        for gid, e in manifest["cells"].items():
            x0, y0 = bia.cell_origin_px(e["cell"], L)
            c = m[y0 // f:y0 // f + ch, x0 // f:x0 // f + cw]
            ring = np.concatenate([c[0], c[-1], c[:, 0], c[:, -1]])
            assert ring.min() > 0.98, f"mip {level}: {gid}'s border texels are not flat ({ring.min():.3f})"
    assert manifest["atlas"]["mip_safe_levels"] == 8            # 256-px cells: aligned to every mip up to 8


# ------------------------------------------------------------------------------------------------ 4
def test_normals_follow_the_height(real):
    _data, H, N, _AO, _m, _new, L = real
    flat = H == 1.0
    assert np.allclose(N[flat & (np.roll(H, 1, 0) == 1) & (np.roll(H, -1, 0) == 1)
                         & (np.roll(H, 1, 1) == 1) & (np.roll(H, -1, 1) == 1)][:, 2], 1.0)
    gy, gx = np.gradient(H.astype(np.float64))
    sel = np.abs(gx) > 0.02
    assert np.corrcoef(-gx[sel], N[..., 0][sel])[0, 1] > 0.95   # +R where the surface falls to the right
    sel = np.abs(gy) > 0.02
    assert np.corrcoef(gy[sel], N[..., 1][sel])[0, 1] > 0.95    # OpenGL green: +G = up (import with Flip Green)


# ------------------------------------------------------------------------------------------------ 5
def test_committed_atlas_is_up_to_date():
    assert bia.main(["--check"]) == 0


def test_mesh_cell_rects_centre_on_the_glyph(real):
    _data, _H, _N, _AO, manifest, new_data, _L = real
    meshes = bia.load_json(bia.STELES)["meshes"]
    for info in meshes.values():
        cu0, cv0, csu, csv = manifest["mesh_cell_rect_uv1"][info["mesh"]]
        gu0, gv0, gsu, gsv = info["glyph_rect_uv1"]
        assert cu0 + csu / 2 == pytest.approx(gu0 + gsu / 2, abs=2e-3), info["mesh"]
        assert cv0 + csv / 2 == pytest.approx(gv0 + gsv / 2, abs=2e-3), info["mesh"]
        assert new_data["meshes"][info["mesh"]]["cell_rect_uv1"] == [cu0, cv0, csu, csv]


def test_inscriptions_json_rules():
    data = bia.load_json(bia.DATA)
    ins = {r["id"]: r for r in data["inscriptions"]}
    assert len(ins) == len(data["inscriptions"])
    for r in data["inscriptions"]:
        if r["status"] == "awaiting_author":
            assert r["saskartan"] == "AUTHOR", f"{r['id']}: Saskartan text in a row still waiting for the author"
            assert r["atlas_cell"] is None
        else:
            assert r["saskartan"] not in ("AUTHOR", "", None), r["id"]
        assert r["voice_line_id"] == f"INSCR_{r['id']}"
        assert re.fullmatch(rf"Saved/RadioRecordings/selected/INSCR_{r['id']}\.wav", r["voice_wav"])
        assert r["voice_asset"].endswith(f"/VO_Carrier_INSCR_{r['id']}")
        assert r["voice_policy"] in ("first_full_read", "never")
        assert r["voice_style"] in ("system", "failing")
    assert ins["I05"]["saskartan"] == "rzag-zrîrit" and ins["I02"]["saskartan"] == "dînîgaradzah"
    cells = [r["atlas_cell"] for r in data["inscriptions"] if r["atlas_cell"] is not None]
    assert len(cells) == len(set(cells))
    steles = data["steles"]
    assert len(steles) == 36 and len({s["id"] for s in steles}) == 36
    assert sum(s["id"].startswith("Stele_WayStone_") for s in steles) == 34
    for s in steles:
        assert s["tags"] == ["Stele", s["id"]]
        assert s["inscription"] in ins and ins[s["inscription"]]["atlas_cell"] is not None, s["id"]
        assert s["planned_inscription"] in ins, s["id"]
        assert s["mesh"] in data["meshes"]
        assert 0.0 <= s["wear"] <= 1.0 and 0 <= s["road_m"] <= 4800
        assert s["planned_read"] in ("full", "match")
    firsts = [s for s in steles if s["planned_read"] == "full"]
    assert all(s["planned_wear"] <= 0.35 for s in firsts), "a first reading on a worn stone"
