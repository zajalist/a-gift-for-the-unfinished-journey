"""Pack every carved inscription into one height atlas and one normal atlas (task STELESCAN, 2026-09-28).

    python Tools/Story/build_inscription_atlas.py            # build from docs/story/inscriptions.json
    python Tools/Story/build_inscription_atlas.py --check    # rebuild in memory, compare with the files on disk

Design: docs/look/STELE_SCAN.md, section 1.2. The stele face material (M_Saskarta_SteleFace, built by
Tools/Look/build_stele_scan.py) runs ParallaxOcclusionMapping on the height atlas and reads the normal
atlas at the parallax UVs. Which cell a stone shows is Custom Primitive Data 1 (`Cell`); where the cell
sits on the face is CPD 4-7 (`CellRect`, per mesh, written into inscriptions.json by this script).

Inputs
  docs/story/inscriptions.json            the inscription rows (id, ink_cm, atlas_cell) and the atlas settings
  SourceArt/Inscriptions/T_Inscription_<ID>.png      the cleaned ink (its height is ink_cm[1])
  SourceArt/Inscriptions/T_Inscription_<ID>_H.png    the chisel height (carve_inscription.py): 1 = face, 0 = cut
  SourceArt/Steles/steles.json            the stele meshes' face rectangles and glyph centres (CellRect)

Outputs (SourceArt/Inscriptions/atlas/)
  T_Inscr_Atlas_H.png    8-bit grey height, 1 = stone face (import TC_Grayscale -> G8, sRGB off, clamp;
                         POM Heightmap Channel = (1, 0, 0, 0): a G8 texture samples into R)
  T_Inscr_Atlas_N.png    tangent normal, OpenGL green like carve_inscription.py (import TC_Normalmap,
                         Flip Green on). Built from the atlas height at groove_depth_cm, so the normal
                         map and the POM depth describe the same groove.
  T_Inscr_Atlas_AO.png   groove occlusion 1 - 0.3 x blur(depth). Preview and fallback only: the material
                         derives AO from the height atlas with a mip bias (not imported by default).
  atlas_manifest.json    id -> cell, col/row, the cell's atlas UV rect, the ink's atlas UV rect, physical
                         sizes, fit scale, smallest pad; per mesh the UV1 CellRect
  atlas_preview.png      contact sheet under a low raking light

Layout (the defaults; all from inscriptions.json "atlas")
  2048 x 2048, 8 x 4 cells of 256 x 512 px, one cell = 50 x 100 cm of stone at 5.12 px/cm. Texels are
  square and 1 atlas UV = 400 cm on both axes, so POM's Height Ratio is simply depth_cm / 400.
  Every glyph keeps a flat pad of at least pad_cm (6 cm) to its cell border: an ink box larger than the
  cell minus the pad is scaled down to fit (the fit scale is reported). Cells are powers of two and start
  on multiples of their size, so no mip texel mixes two cells up to mip log2(256) = 8.
Cells never move once used: an inscription keeps its atlas_cell; a new one takes the lowest free cell.
The script writes atlas_cell and mesh_cell_rect_uv1 back into inscriptions.json.
Inscriptions without a carved _H map (status awaiting_author) get no cell. The Segalen stone (V9) is
not a stele inscription and is not in inscriptions.json, so it is never packed.
"""
import argparse
import hashlib
import json
import pathlib
import sys

import numpy as np
from PIL import Image
from scipy import ndimage

ROOT = pathlib.Path(__file__).resolve().parents[2]
DATA = ROOT / "docs" / "story" / "inscriptions.json"
INSCR = ROOT / "SourceArt" / "Inscriptions"
OUT = INSCR / "atlas"
STELES = ROOT / "SourceArt" / "Steles" / "steles.json"
CARVE_PAD_PX = 96        # carve_inscription.py PAD: flat margin around the ink in every _H map

DEFAULT_ATLAS = {"size_px": [2048, 2048], "grid": [8, 4], "cell_cm": [50.0, 100.0], "pad_cm": 6.0,
                 "groove_depth_cm": 0.8}


# ------------------------------------------------------------------------------------------------ layout
def layout(atlas):
    """Derived atlas constants; fails on a layout that breaks the square-texel / power-of-two rules."""
    w, h = atlas["size_px"]
    cols, rows = atlas["grid"]
    cw, ch = w // cols, h // rows
    ccm_w, ccm_h = atlas["cell_cm"]
    if w % cols or h % rows:
        raise SystemExit(f"atlas {w}x{h} does not divide into {cols}x{rows} cells")
    for n in (w, h, cw, ch):
        if n & (n - 1):
            raise SystemExit(f"atlas size and cell size must be powers of two (got {n})")
    pxcm_u, pxcm_v = cw / ccm_w, ch / ccm_h
    if abs(pxcm_u - pxcm_v) > 1e-6:
        raise SystemExit(f"texels are not square: {pxcm_u:.4f} vs {pxcm_v:.4f} px/cm")
    return {"w": w, "h": h, "cols": cols, "rows": rows, "cw": cw, "ch": ch, "px_per_cm": pxcm_u,
            "cm_per_uv": w / pxcm_u, "pad_px": atlas["pad_cm"] * pxcm_u, "cells": cols * rows}


def cell_origin_px(cell, L):
    return (cell % L["cols"]) * L["cw"], (cell // L["cols"]) * L["ch"]


def cell_uv_rect(cell, L):
    x, y = cell_origin_px(cell, L)
    return [x / L["w"], y / L["h"], L["cw"] / L["w"], L["ch"] / L["h"]]


def mesh_cell_rects(steles_manifest, cell_cm):
    """Per mesh, the UV1 rectangle (u0, v0, su, sv) that one cell of cell_cm covers on the face, centred
    on the glyph centre. UV1 on the face is ((ymax - y) / fw, (ztop - z) / fh) (stele_mesh.py)."""
    out = {}
    for info in steles_manifest["meshes"].values():
        ymin, ymax = info["face_rect_cm"]["y"]
        zbot, ztop = info["face_rect_cm"]["z"]
        fw, fh = ymax - ymin, ztop - zbot
        yc, zc = info["glyph_centre_cm"][1], info["glyph_centre_cm"][2]
        cw, ch = cell_cm
        out[info["mesh"]] = [round((ymax - (yc + cw / 2)) / fw, 6), round((ztop - (zc + ch / 2)) / fh, 6),
                             round(cw / fw, 6), round(ch / fh, 6)]
    return out


# ------------------------------------------------------------------------------------------------ cells
def assign_cells(rows, carved_ids, cells_total, previous=None):
    """Keep every cell already used (inscriptions.json atlas_cell, else the previous manifest); give each
    newly carved inscription the lowest free cell. Returns {id: cell}."""
    previous = previous or {}
    used, out = {}, {}
    for r in rows:
        c = r.get("atlas_cell")
        if c is None:
            c = previous.get(r["id"])
        if c is None:
            continue
        if not 0 <= c < cells_total:
            raise SystemExit(f"{r['id']}: atlas_cell {c} outside 0..{cells_total - 1}")
        if c in used:
            raise SystemExit(f"atlas_cell {c} used by both {used[c]} and {r['id']}")
        used[c] = r["id"]
        out[r["id"]] = c
    free = [c for c in range(cells_total) if c not in used]
    for gid in carved_ids:
        if gid in out:
            continue
        if not free:
            raise SystemExit(f"the atlas is full ({cells_total} cells): raise the grid or the size")
        out[gid] = free.pop(0)
    return {k: v for k, v in out.items() if k in carved_ids}


def load_height(gid):
    """The chisel height (0..1) and the physical source scale (px per cm) from the cleaned ink height."""
    hp = INSCR / f"T_Inscription_{gid}_H.png"
    h = np.array(Image.open(hp)).astype(np.float32)
    h = h / (65535.0 if h.max() > 255 else 255.0)
    return h, hp


def fit_glyph(h_src, ink_px, ink_cm, L, pad_cm):
    """Resample one _H map into a cell: scale to px_per_cm, shrink to keep pad_cm if needed, centre.
    Returns the cell (ch x cw, 1 = flat face), the fit scale and the ink box in cell px (x0, y0, x1, y1)."""
    src_pxcm = ink_px[1] / ink_cm[1]                          # the ink's height sets the scale
    ink_w_cm = ink_px[0] / src_pxcm                            # its width follows the scan's aspect
    ccm_w, ccm_h = L["cw"] / L["px_per_cm"], L["ch"] / L["px_per_cm"]
    slack = 2.0 / L["px_per_cm"]                               # 2 px for rounding the resampled size
    s = min(1.0, (ccm_w - 2 * pad_cm - slack) / ink_w_cm, (ccm_h - 2 * pad_cm - slack) / ink_cm[1])
    k = L["px_per_cm"] * s / src_pxcm                          # dst px per src px
    tw = max(1, int(round(h_src.shape[1] * k)))
    th = max(1, int(round(h_src.shape[0] * k)))
    img = Image.fromarray(h_src, mode="F").resize((tw, th), Image.Resampling.LANCZOS)
    g = np.clip(np.asarray(img, dtype=np.float32), 0.0, 1.0)
    cell = np.ones((L["ch"], L["cw"]), np.float32)
    ox, oy = (L["cw"] - tw) // 2, (L["ch"] - th) // 2
    # paste centred, cropping the flat carve margin where the map is larger than the cell
    sx0, sy0 = max(0, -ox), max(0, -oy)
    dx0, dy0 = max(0, ox), max(0, oy)
    wv, hv = min(tw - sx0, L["cw"] - dx0), min(th - sy0, L["ch"] - dy0)
    cell[dy0:dy0 + hv, dx0:dx0 + wv] = g[sy0:sy0 + hv, sx0:sx0 + wv]
    pad = CARVE_PAD_PX * k
    ink = (ox + pad, oy + pad, ox + tw - pad, oy + th - pad)
    return cell, s, ink


def normals_from_height(h, px_per_cm, depth_cm):
    """OpenGL-green tangent normals of the carved surface z = (h - 1) x depth_cm (carve_inscription.py's
    convention: n = (-dh/dcol, +dh/drow, 1) scaled to cm)."""
    gy, gx = np.gradient(h.astype(np.float64))
    s = depth_cm * px_per_cm
    n = np.dstack([-gx * s, gy * s, np.ones_like(h, dtype=np.float64)])
    n /= np.linalg.norm(n, axis=2, keepdims=True)
    return n


def ao_from_height(h):
    return 1.0 - 0.3 * ndimage.gaussian_filter(1.0 - h, 2.0)


def box_mip(a, level):
    f = 2 ** level
    if f == 1:
        return a
    hh, ww = a.shape[0] // f, a.shape[1] // f
    return a[:hh * f, :ww * f].reshape(hh, f, ww, f).mean(axis=(1, 3))


# ------------------------------------------------------------------------------------------------ build
def build(data, steles_manifest, previous_manifest=None):
    """Everything in memory: (height float32, normals float64, ao float32, manifest dict, data dict)."""
    atlas = dict(DEFAULT_ATLAS)
    atlas.update(data.get("atlas", {}))
    L = layout(atlas)
    rows = data["inscriptions"]
    by_id = {r["id"]: r for r in rows}
    if len(by_id) != len(rows):
        raise SystemExit("duplicate inscription ids in inscriptions.json")
    carved = [r["id"] for r in rows if (INSCR / f"T_Inscription_{r['id']}_H.png").exists()]
    prev = {k: v["cell"] for k, v in (previous_manifest or {}).get("cells", {}).items()}
    cells = assign_cells(rows, carved, L["cells"], prev)
    H = np.ones((L["h"], L["w"]), np.float32)
    entries, warnings = {}, []
    mesh_rects = mesh_cell_rects(steles_manifest, atlas["cell_cm"])
    glyph_box = {i["mesh"]: i["glyph_size_cm"] for i in steles_manifest["meshes"].values()}
    for gid in sorted(cells, key=lambda g: cells[g]):
        r = by_id[gid]
        h_src, hp = load_height(gid)
        ink_png = INSCR / f"T_Inscription_{gid}.png"
        ink_px = Image.open(ink_png).size if ink_png.exists() else (h_src.shape[1] - 2 * CARVE_PAD_PX,
                                                                      h_src.shape[0] - 2 * CARVE_PAD_PX)
        ink_cm = r.get("ink_cm")
        if not ink_cm:
            raise SystemExit(f"{gid}: ink_cm missing in inscriptions.json")
        cell_img, s, ink = fit_glyph(h_src, ink_px, ink_cm, L, atlas["pad_cm"])
        x0, y0 = cell_origin_px(cells[gid], L)
        H[y0:y0 + L["ch"], x0:x0 + L["cw"]] = cell_img
        pad_min_cm = min(ink[0], ink[1], L["cw"] - ink[2], L["ch"] - ink[3]) / L["px_per_cm"]
        fitted = [round((ink[2] - ink[0]) / L["px_per_cm"], 2), round((ink[3] - ink[1]) / L["px_per_cm"], 2)]
        used_on = sorted({st["mesh"] for st in data.get("steles", []) if st.get("inscription") == gid})
        for mesh in used_on:
            box = glyph_box.get(mesh)
            if box and (fitted[0] > box[0] + 0.05 or fitted[1] > box[1] + 0.05):
                warnings.append(f"{gid}: ink {fitted} cm is larger than {mesh}'s flat glyph box {box} cm "
                                "(the face may be chipped outside that box)")
        entries[gid] = {
            "cell": cells[gid], "col": cells[gid] % L["cols"], "row": cells[gid] // L["cols"],
            "cell_uv_rect": [round(v, 6) for v in cell_uv_rect(cells[gid], L)],
            "ink_uv_rect": [round((x0 + ink[0]) / L["w"], 6), round((y0 + ink[1]) / L["h"], 6),
                            round((ink[2] - ink[0]) / L["w"], 6), round((ink[3] - ink[1]) / L["h"], 6)],
            "ink_cm": [float(ink_cm[0]), float(ink_cm[1])], "ink_cm_fitted": fitted, "fit_scale": round(s, 4),
            "pad_min_cm": round(pad_min_cm, 2), "min_height": round(float(cell_img.min()), 3),
            "source": hp.relative_to(ROOT).as_posix(),
            "source_sha1": hashlib.sha1(hp.read_bytes()).hexdigest()[:16],
            "used_on_meshes": used_on,
        }
    N = normals_from_height(H, L["px_per_cm"], atlas["groove_depth_cm"])
    AO = ao_from_height(H).astype(np.float32)
    manifest = {
        "version": 1,
        "generated_by": "Tools/Story/build_inscription_atlas.py",
        "atlas": {"size_px": [L["w"], L["h"]], "grid": [L["cols"], L["rows"]], "cell_px": [L["cw"], L["ch"]],
                  "cell_cm": list(atlas["cell_cm"]), "px_per_cm": L["px_per_cm"], "cm_per_uv": L["cm_per_uv"],
                  "pad_cm": atlas["pad_cm"], "groove_depth_cm": atlas["groove_depth_cm"],
                  "pom_height_ratio": round(atlas["groove_depth_cm"] / L["cm_per_uv"], 6),
                  "half_texel_uv": [0.5 / L["w"], 0.5 / L["h"]],
                  "mip_safe_levels": int(np.log2(min(L["cw"], L["ch"]))),
                  "height_png": "T_Inscr_Atlas_H.png", "normal_png": "T_Inscr_Atlas_N.png",
                  "ao_png": "T_Inscr_Atlas_AO.png"},
        "cells": entries,
        "free_cells": [c for c in range(L["cells"]) if c not in cells.values()],
        "mesh_cell_rect_uv1": mesh_rects,
        "warnings": warnings,
    }
    new_data = json.loads(json.dumps(data))
    new_data["atlas"] = {**new_data.get("atlas", {}), "size_px": [L["w"], L["h"]], "grid": [L["cols"], L["rows"]],
                         "cell_cm": list(atlas["cell_cm"]), "pad_cm": atlas["pad_cm"],
                         "groove_depth_cm": atlas["groove_depth_cm"], "px_per_cm": L["px_per_cm"],
                         "cm_per_uv": L["cm_per_uv"]}
    for m, rect in mesh_rects.items():
        new_data.setdefault("meshes", {}).setdefault(m, {})["cell_rect_uv1"] = rect
    for r in new_data["inscriptions"]:
        if r["id"] in cells:
            r["atlas_cell"] = cells[r["id"]]
            if r.get("status") in ("scanned", "carved"):
                r["status"] = "in_atlas"
    return H, N, AO, manifest, new_data, L


def encode(H, N, AO):
    h8 = np.round(np.clip(H, 0, 1) * 255).astype(np.uint8)
    n8 = np.round((N * 0.5 + 0.5) * 255).clip(0, 255).astype(np.uint8)
    ao8 = np.round(np.clip(AO, 0, 1) * 255).astype(np.uint8)
    return h8, n8, ao8


def preview(h8, n8, L, manifest):
    """Contact sheet of the used cells: low raking light from the upper left, warm stone."""
    used = sorted(manifest["cells"].items(), key=lambda kv: kv[1]["cell"])
    if not used:
        return Image.new("RGB", (L["cw"], L["ch"]), (90, 80, 70))
    tiles = []
    Ld = np.array([-0.62, 0.55, 0.56])
    Ld /= np.linalg.norm(Ld)
    for _gid, e in used:
        x0, y0 = cell_origin_px(e["cell"], L)
        n = n8[y0:y0 + L["ch"], x0:x0 + L["cw"]].astype(np.float32) / 255 * 2 - 1
        h = h8[y0:y0 + L["ch"], x0:x0 + L["cw"]].astype(np.float32) / 255
        lam = np.clip((n * Ld).sum(2), 0, 1)
        lum = 0.6 * (0.25 + 0.95 * lam) * (1 - 0.3 * ndimage.gaussian_filter(1 - h, 2.0))
        tile = np.dstack([lum, lum * 0.86, lum * 0.68])
        tile[0, :] = tile[-1, :] = tile[:, 0] = tile[:, -1] = (0.95, 0.72, 0.42)      # cell border
        tiles.append(tile)
    sheet = np.concatenate(tiles, axis=1)
    img = Image.fromarray((np.clip(sheet, 0, 1) * 255).astype(np.uint8))
    return img.resize((img.width * 2, img.height * 2), Image.Resampling.NEAREST)


def load_json(p):
    return json.loads(p.read_text(encoding="utf-8"))


def dump_json(obj):
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="rebuild in memory and compare with the files on disk")
    ap.add_argument("--data", default=str(DATA))
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args(argv)
    data_p, out = pathlib.Path(a.data), pathlib.Path(a.out)
    data = load_json(data_p)
    prev_p = out / "atlas_manifest.json"
    prev = load_json(prev_p) if prev_p.exists() else None
    H, N, AO, manifest, new_data, L = build(data, load_json(STELES), prev)
    h8, n8, ao8 = encode(H, N, AO)
    if a.check:
        problems = []
        for name, arr in (("T_Inscr_Atlas_H.png", h8), ("T_Inscr_Atlas_N.png", n8)):
            p = out / name
            if not p.exists() or not np.array_equal(np.array(Image.open(p)), arr):
                problems.append(f"{name} is stale or missing")
        if prev != manifest:
            problems.append("atlas_manifest.json is stale or missing")
        if data != new_data:
            problems.append("inscriptions.json lacks the atlas cells / cell rects (run without --check)")
        print("\n".join(problems) if problems else f"ok: {len(manifest['cells'])} inscriptions in the atlas")
        return 1 if problems else 0
    out.mkdir(parents=True, exist_ok=True)
    Image.fromarray(h8, mode="L").save(out / "T_Inscr_Atlas_H.png", optimize=True)
    Image.fromarray(n8, mode="RGB").save(out / "T_Inscr_Atlas_N.png", optimize=True)
    Image.fromarray(ao8, mode="L").save(out / "T_Inscr_Atlas_AO.png", optimize=True)
    preview(h8, n8, L, manifest).save(out / "atlas_preview.png")
    prev_p.write_text(dump_json(manifest), encoding="utf-8")
    if new_data != data:
        data_p.write_text(dump_json(new_data), encoding="utf-8")
    for gid, e in sorted(manifest["cells"].items(), key=lambda kv: kv[1]["cell"]):
        print(f"{gid}: cell {e['cell']} (col {e['col']}, row {e['row']}), ink {e['ink_cm_fitted']} cm "
              f"(fit {e['fit_scale']}), pad >= {e['pad_min_cm']} cm, deepest {e['min_height']}")
    for w in manifest["warnings"]:
        print("WARNING " + w)
    print(f"atlas {L['w']}x{L['h']}, {len(manifest['free_cells'])} free cells -> {out.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
