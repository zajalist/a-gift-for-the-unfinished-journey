"""Tests for the stele meshes (Tools/Look/stele_mesh.py), their preview reader and the editor driver
(Tools/Look/import_steles.py), offline.

  - size, pivot at the base centre, a closed outward-facing surface;
  - the Face slot is exactly the plane x = +D/2 with normals +X, and its UV1 is the face in 0..1,
    the glyph rectangle fully covered (no break reaches it); everything else has UV1 = (-1, -1);
  - UV0 has the same texel density everywhere (no stretch on the narrow sides);
  - after the GLB round trip, a camera facing -X (UE) sees UV1 u growing to its right and v downward
    (the glyph is upright and not mirrored);
  - the GLB and FBX are well formed; the editor scripts compile and hold no word python_run refuses.

Run: python -m pytest Tools/Look/tests/test_stele_mesh.py -q -p no:cacheprovider --basetemp <scratch dir>
"""
import pathlib
import sys

import numpy as np
import pytest

LOOK = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LOOK))

import stele_mesh as sm  # noqa: E402
import stele_preview as sp  # noqa: E402
import import_steles as ist  # noqa: E402
from apply_look import BANNED  # noqa: E402

NAMES = list(sm.VARIANTS)


@pytest.fixture(scope="module")
def built():
    return {n: (lambda m: (m, sm.primitives(m)))(sm.build(n)) for n in NAMES}


@pytest.mark.parametrize("name", NAMES)
def test_size_and_pivot(built, name):
    m, prims = built[name]
    v = sm.VARIANTS[name]
    pos = np.concatenate([p["pos"] for p in prims])
    lo, hi = pos.min(0), pos.max(0)
    size = hi - lo
    assert abs(size[0] - v["D"]) < 0.03 * v["D"] + 0.004
    assert abs(size[1] - v["W"]) < 0.03 * v["W"] + 0.004
    assert abs(size[2] - v["H"]) < 0.02 * v["H"]
    base = pos[pos[:, 2] < 0.02]
    assert abs(base[:, 0].min() + base[:, 0].max()) / 2 < 0.015      # base centred on x = 0
    assert abs(base[:, 1].min() + base[:, 1].max()) / 2 < 0.015      # and on y = 0
    assert -0.008 < lo[2] < 0.002                                    # bottom at z = 0


@pytest.mark.parametrize("name", NAMES)
def test_closed_and_outward(built, name):
    m, _ = built[name]
    tris = np.concatenate([m["tri_band"], m["tri_front"], m["tri_back"]])
    e = np.sort(np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]]), 1)
    _, cnt = np.unique(e, axis=0, return_counts=True)
    assert (cnt == 2).all()
    v = sm.VARIANTS[name]
    vol = sm._signed_volume(m["V"], tris)
    assert 0.6 * v["W"] * v["D"] * v["H"] < vol < v["W"] * v["D"] * v["H"]


@pytest.mark.parametrize("name", NAMES)
def test_front_face_is_a_true_plane(built, name):
    m, prims = built[name]
    face = prims[1]
    assert face["name"] == "Face" and len(face["idx"]) > 1000
    assert np.abs(face["pos"][:, 0] - m["xf"]).max() == 0.0
    assert np.allclose(face["nrm"], [1.0, 0.0, 0.0])
    assert len(face["idx"]) >= 0.9 * len(m["tri_front"])             # breaks take little of the face


@pytest.mark.parametrize("name", NAMES)
def test_uv1_face_and_glyph_rect(built, name):
    m, prims = built[name]
    stone, face = prims
    uv = face["uv1"]
    assert uv.min() >= -1e-9 and uv.max() <= 1 + 1e-9
    assert np.all(stone["uv1"] == -1.0)
    u0, v0, su, sv = m["glyph_rect"]
    assert 0 < u0 and u0 + su < 1 and 0 < v0 and v0 + sv < 1
    # every point of the glyph rectangle lies on a Face triangle (UV1 space)
    gu, gv = np.meshgrid(np.linspace(u0, u0 + su, 41), np.linspace(v0, v0 + sv, 61))
    pts = np.stack([gu.ravel(), gv.ravel()], 1)
    a, b, c = uv[face["idx"][:, 0]], uv[face["idx"][:, 1]], uv[face["idx"][:, 2]]
    covered = np.zeros(len(pts), bool)
    for i in range(0, len(a), 2000):
        A, B, C = a[i:i + 2000], b[i:i + 2000], c[i:i + 2000]
        d = (B[:, 1] - C[:, 1]) * (A[:, 0] - C[:, 0]) + (C[:, 0] - B[:, 0]) * (A[:, 1] - C[:, 1])
        w0 = ((B[:, 1] - C[:, 1])[None] * (pts[:, 0:1] - C[:, 0][None]) + (C[:, 0] - B[:, 0])[None] * (pts[:, 1:2] - C[:, 1][None])) / d
        w1 = ((C[:, 1] - A[:, 1])[None] * (pts[:, 0:1] - C[:, 0][None]) + (A[:, 0] - C[:, 0])[None] * (pts[:, 1:2] - C[:, 1][None])) / d
        w2 = 1 - w0 - w1
        covered |= ((w0 >= -1e-9) & (w1 >= -1e-9) & (w2 >= -1e-9)).any(1)
    assert covered.all()


@pytest.mark.parametrize("name", NAMES)
def test_uv0_even_texel_density(built, name):
    _, prims = built[name]
    r, w = [], []
    for p in prims:
        P, U, I = p["pos"], p["uv0"], p["idx"]
        a3 = np.linalg.norm(np.cross(P[I[:, 1]] - P[I[:, 0]], P[I[:, 2]] - P[I[:, 0]]), axis=1)
        e1, e2 = U[I[:, 1]] - U[I[:, 0]], U[I[:, 2]] - U[I[:, 0]]
        au = np.abs(e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0])
        ok = a3 > 1e-8
        r.append(np.sqrt(au[ok] / a3[ok]) / sm.UV0_PER_M)
        w.append(a3[ok])
    r, w = np.concatenate(r), np.concatenate(w)
    # per triangle (small bevel and break triangles count as much as big ones): measured 0.99-1.12
    lo, hi = np.percentile(r, [2, 98])
    assert 0.85 < lo and hi < 1.2, (lo, hi)
    # by surface area, which is what the eye sees: measured 0.98-1.02 on all four meshes
    o = np.argsort(r)
    c = np.cumsum(w[o]) / w.sum()
    alo, ahi = r[o][np.searchsorted(c, 0.02)], r[o][np.searchsorted(c, 0.98)]
    assert 0.97 < alo and ahi < 1.03, (alo, ahi)


def test_glb_roundtrip_and_glyph_upright(built, tmp_path):
    name = "WayStone_A"
    m, prims = built[name]
    path = tmp_path / "s.glb"
    sm.write_glb(path, "SM_Stele_" + name, prims)
    doc, gp = sm.read_glb(path)
    assert [p["material"] for p in gp] == ["Stone", "Face"]
    for p, q in zip(gp, prims):
        assert {"POSITION", "NORMAL", "TEXCOORD_0", "TEXCOORD_1", "COLOR_0"} <= set(p)
        assert np.allclose(p["POSITION"][:, [0, 2, 1]], q["pos"], atol=1e-6)     # glTF (x, z, y) = UE (x, y, z)
        assert np.allclose(p["TEXCOORD_1"], q["uv1"], atol=1e-6)
    allp = np.concatenate([p["POSITION"] for p in gp]).astype(np.float64)
    off = np.cumsum([0] + [len(p["POSITION"]) for p in gp])[:-1]
    alli = np.concatenate([p["indices"].astype(np.int64) + o for p, o in zip(gp, off)])
    assert sm._signed_volume(allp, alli) > 0                           # CCW outward in glTF's own frame
    # front view as UE draws it: camera facing -X, its right is -Y; u must grow to the right, v downward
    mesh = sp.load_ue(path)
    buf, slot, _ = sp.rasterize(mesh, [-1.0, 0.0, 0.0], 300)
    face = slot == 1
    ys, xs = np.nonzero(face)
    assert np.corrcoef(buf[..., 8][face], xs)[0, 1] > 0.99
    assert np.corrcoef(buf[..., 9][face], ys)[0, 1] > 0.99


def test_fbx_is_consistent(built, tmp_path):
    m, prims = built["WayStone_B"]
    path = tmp_path / "s.fbx"
    sm.write_fbx_ascii(path, "SM_Stele_WayStone_B", prims)
    text = path.read_text(encoding="ascii")
    nv = sum(len(p["pos"]) for p in prims)
    nt = sum(len(p["idx"]) for p in prims)
    assert text.startswith("; FBX 7.4.0 project file")
    assert f"Vertices: *{3 * nv} " in text and f"PolygonVertexIndex: *{3 * nt} " in text
    assert text.count("LayerElementUV:") == 2 and f"Materials: *{nt} " in text
    idx = text.split("PolygonVertexIndex: *")[1].split("a: ")[1].split("}")[0]
    vals = np.array([int(x) for x in idx.split(",")]).reshape(-1, 3)
    assert (vals[:, :2] >= 0).all() and (vals[:, 2] < 0).all()


def test_editor_scripts_are_clean():
    assert ist.check() == 0
    for label, s in ist.scripts_for_check():
        assert not [w for w in BANNED if w in s], label
        compile(s, label, "exec")


def test_swap_plan():
    items = ist.swap_items(ist.manifest(), "uv1")
    names = [it["name"] for it in items]
    assert len(items) == 36 and len(set(names)) == 36
    way = [it for it in items if "WayStone" in it["name"]]
    assert all(a["mesh"] != b["mesh"] for a, b in zip(way, way[1:]))
    assert all(0.9 <= it["scale"] <= 1.1 for it in items)
    assert all(it["mesh"].endswith("SM_Stele_DockPost") for it in items if "DockPost" in it["name"])
