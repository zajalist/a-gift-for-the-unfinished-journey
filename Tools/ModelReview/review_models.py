"""Review a folder of binary FBX models: stats, embedded textures, previews.

    python review_models.py [--src C:/Users/Admin/Desktop/models] [--out docs/models]
                            [--jobs 6] [--only bench01,house01]

Writes (under --out):
    stats.json, stats.md
    textures/<model>_<n>.<ext>        embedded images, raw bytes (not re-encoded)
    previews/<model>.png              1024x512, 3/4 front + 3/4 back, orthographic
    contact_<n>.png                   6 previews per sheet

Source FBX files are only read, never modified.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fbx_reader import (axis_to_zup_matrix, model_geometric_matrix,  # noqa: E402
                        model_world_matrix, read_fbx)

REPO = Path(__file__).resolve().parents[2]
DEFAULT_SRC = Path("C:/Users/Admin/Desktop/models")
DEFAULT_OUT = REPO / "docs" / "models"

VIEW_W, VIEW_H = 512, 512
SSAA = 2                    # supersampling factor for previews
PREVIEW_TRI_LIMIT = 600_000  # above this, the preview mesh is vertex-clustered
BG = (118, 118, 118)
QUANT_CM = 0.01             # 0.1 mm weld tolerance for topology metrics

ROLE_NAMES = {
    "DiffuseColor": "base_color", "NormalMap": "normal", "Bump": "normal",
    "ShininessExponent": "roughness", "ReflectionFactor": "metallic",
    "SpecularColor": "specular", "EmissiveColor": "emissive",
    "TransparentColor": "opacity", "TransparencyFactor": "opacity",
}
AXIS = "XYZ"


# ======================================================================= mesh

class Mesh:
    """One geometry instance flattened to Z-up centimetres, per corner."""

    def __init__(self, scene, geo):
        self.geo = geo
        model = scene.model_of_geometry(geo.id)
        M = np.eye(4)
        if model is not None:
            M = model_world_matrix(scene, model) @ model_geometric_matrix(model)
        B = axis_to_zup_matrix(scene.global_settings)
        A = B @ (M[:3, :3] * scene.unit_scale)
        t = B @ (M[:3, 3] * scene.unit_scale)
        self.model = model
        self.model_scaling = model.scaling.tolist() if model is not None else [1, 1, 1]
        self.verts = geo.vertices @ A.T + t                      # (V,3) cm, Z-up
        self.corner_vid, self.corner_uv, nrm = geo.corner_attributes()
        if nrm is not None:
            n = nrm @ np.linalg.inv(A)
            n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
            self.corner_nrm = n
        else:
            self.corner_nrm = None
        self.tri_corner, self.poly_of_tri = geo.triangulate()
        _, _, self.poly_sizes = geo.polygons()
        self.tri_vid = self.corner_vid[self.tri_corner]          # (T,3)


def tri_areas(v, tri):
    a, b, c = v[tri[:, 0]], v[tri[:, 1]], v[tri[:, 2]]
    return 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)


def connected_components(n, edges):
    """Union-find by min-label propagation with pointer jumping (vectorised)."""
    if n == 0:
        return 0
    lab = np.arange(n)
    a, b = edges[:, 0], edges[:, 1]
    for _ in range(200):
        la, lb = lab[a], lab[b]
        m = np.minimum(la, lb)
        new = lab.copy()
        np.minimum.at(new, la, m)
        np.minimum.at(new, lb, m)
        # pointer jumping
        while True:
            nn = new[new]
            if np.array_equal(nn, new):
                break
            new = nn
        if np.array_equal(new, lab):
            break
        lab = new
    return len(np.unique(lab))


def mesh_quality(mesh: Mesh):
    v, tri = mesh.verts, mesh.tri_vid
    q = np.round(v / QUANT_CM).astype(np.int64)
    _, uid = np.unique(q, axis=0, return_inverse=True)
    uid = uid.ravel()
    nuniq = int(uid.max()) + 1 if len(uid) else 0
    t = uid[tri]
    areas = tri_areas(v, tri)
    med = float(np.median(areas)) if len(areas) else 0.0
    collapsed = (t[:, 0] == t[:, 1]) | (t[:, 1] == t[:, 2]) | (t[:, 0] == t[:, 2])
    degenerate = collapsed | (areas < 1e-4 * med)
    # edges on welded positions
    e = np.concatenate([t[:, [0, 1]], t[:, [1, 2]], t[:, [2, 0]]])
    e = e[e[:, 0] != e[:, 1]]
    e.sort(axis=1)
    ue, cnt = np.unique(e, axis=0, return_counts=True)
    ncomp = connected_components(nuniq, ue)
    # isolated welded vertices (unused) would count as components; remove them
    used = np.zeros(nuniq, bool)
    used[t.ravel()] = True
    ncomp -= int((~used).sum())
    # GPU vertex estimate: corners unique by (position, uv, normal), as UE splits seams
    key = [mesh.corner_vid[:, None].astype(np.int64)]
    if mesh.corner_uv is not None:
        key.append(np.round(mesh.corner_uv * 1e5).astype(np.int64))
    if mesh.corner_nrm is not None:
        key.append(np.round(mesh.corner_nrm * 1e3).astype(np.int64))
    render_verts = len(np.unique(np.concatenate(key, axis=1), axis=0))
    good = areas[~degenerate]
    p1, p99 = (np.percentile(good, [1, 99]) if len(good) else (0, 0))
    return {
        "degenerate_tri_share": float(degenerate.mean()) if len(tri) else 0.0,
        "duplicate_vertex_ratio": float(1 - nuniq / max(len(v), 1)),
        "welded_vertices": nuniq,
        "render_vertices": int(render_verts),
        "components": int(ncomp),
        "open_edge_share": float((cnt == 1).mean()) if len(cnt) else 0.0,
        "nonmanifold_edge_share": float((cnt > 2).mean()) if len(cnt) else 0.0,
        "tri_area_cm2_median": med,
        "tri_area_p99_over_p1": float(p99 / p1) if p1 > 0 else None,
        "tri_area_cv": float(good.std() / good.mean()) if len(good) and good.mean() > 0 else None,
        "surface_area_m2": float(areas.sum() / 1e4),
    }


def uv_metrics(mesh: Mesh, tex_px):
    if mesh.corner_uv is None:
        return {"uv_all_polys": False}
    uv = mesh.corner_uv
    tc = mesh.tri_corner
    a, b, c = uv[tc[:, 0]], uv[tc[:, 1]], uv[tc[:, 2]]
    uva = 0.5 * np.abs((b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (c[:, 0] - a[:, 0]) * (b[:, 1] - a[:, 1]))
    area3 = tri_areas(mesh.verts, mesh.tri_vid)
    out = {
        "uv_all_polys": bool(np.isfinite(uv).all() and len(uv) == len(mesh.corner_vid)),
        "uv_in_0_1_share": float(((uv >= -1e-3) & (uv <= 1 + 1e-3)).all(axis=1).mean()),
        "uv_area_sum": float(uva.sum()),   # >1 => overlapping / mirrored islands
    }
    if tex_px and area3.sum() > 0:
        out["texel_density_px_per_cm"] = float(np.sqrt(uva.sum() * tex_px / area3.sum()))
    return out


# ================================================================= rendering

def load_texture(content, max_side=2048):
    im = Image.open(io.BytesIO(content)).convert("RGB")
    if max(im.size) > max_side:
        f = max(im.size) / max_side
        im = im.resize((round(im.size[0] / f), round(im.size[1] / f)), Image.LANCZOS)
    return np.asarray(im)


def sample_bilinear(tex, uv):
    h, w = tex.shape[:2]
    u = np.mod(uv[:, 0], 1.0) * w - 0.5
    v = (1.0 - np.mod(uv[:, 1], 1.0)) * h - 0.5
    x0 = np.floor(u).astype(np.int64)
    y0 = np.floor(v).astype(np.int64)
    fx = (u - x0)[:, None]
    fy = (v - y0)[:, None]
    x0m, x1m = np.mod(x0, w), np.mod(x0 + 1, w)
    y0m, y1m = np.mod(y0, h), np.mod(y0 + 1, h)
    t = tex.astype(np.float32) if tex.dtype != np.float32 else tex
    c00 = t[y0m, x0m]
    c10 = t[y0m, x1m]
    c01 = t[y1m, x0m]
    c11 = t[y1m, x1m]
    return (c00 * (1 - fx) + c10 * fx) * (1 - fy) + (c01 * (1 - fx) + c11 * fx) * fy


def view_basis(az_deg, el_deg):
    az, el = np.radians(az_deg), np.radians(el_deg)
    # direction from target to camera; az=0 looks from -Y (front) toward +Y
    d = np.array([np.sin(az) * np.cos(el), -np.cos(az) * np.cos(el), np.sin(el)])
    fwd = -d
    right = np.cross(fwd, [0, 0, 1.0])
    right /= np.linalg.norm(right)
    up = np.cross(right, fwd)
    return right, up, fwd


class Canvas:
    def __init__(self, w, h):
        self.w, self.h = w, h
        self.z = np.full(w * h, np.inf)
        self.rgb = np.zeros((w * h, 3), np.float32)
        self.rgb[:] = BG
        self.cover = np.zeros(w * h, bool)


def rasterize(canvas, sx, sy, sz, tri, shade_fn, max_candidates=3_000_000):
    """sx,sy: per-corner pixel coords; sz: depth (smaller=closer); tri: (T,3)
    corner indices.  shade_fn(tri_ids, l0, l1, l2) -> (N,3) colours."""
    W, H = canvas.w, canvas.h
    X = sx[tri]
    Y = sy[tri]
    Z = sz[tri]
    xmin = np.clip(np.floor(X.min(1) - 0.5).astype(np.int64), 0, W - 1)
    xmax = np.clip(np.ceil(X.max(1) - 0.5).astype(np.int64), 0, W - 1)
    ymin = np.clip(np.floor(Y.min(1) - 0.5).astype(np.int64), 0, H - 1)
    ymax = np.clip(np.ceil(Y.max(1) - 0.5).astype(np.int64), 0, H - 1)
    denom = (Y[:, 1] - Y[:, 2]) * (X[:, 0] - X[:, 2]) + (X[:, 2] - X[:, 1]) * (Y[:, 0] - Y[:, 2])
    bw = xmax - xmin + 1
    bh = ymax - ymin + 1
    valid = (np.abs(denom) > 1e-12) & (X.max(1) >= 0) & (X.min(1) < W) & (Y.max(1) >= 0) & (Y.min(1) < H)
    ids = np.nonzero(valid)[0]
    area = (bw * bh)[ids]
    csum = np.cumsum(area)
    start = 0
    while start < len(ids):
        base = csum[start - 1] if start > 0 else 0
        stop = int(np.searchsorted(csum, base + max_candidates, side="right"))
        stop = max(stop, start + 1)
        cid = ids[start:stop]
        cnt = bw[cid] * bh[cid]
        rep = np.repeat(np.arange(len(cid)), cnt)
        off = np.arange(int(cnt.sum())) - np.repeat(np.cumsum(cnt) - cnt, cnt)
        t = cid[rep]
        px = xmin[t] + off % bw[t]
        py = ymin[t] + off // bw[t]
        fx = px + 0.5
        fy = py + 0.5
        x0, x1, x2 = X[t, 0], X[t, 1], X[t, 2]
        y0, y1, y2 = Y[t, 0], Y[t, 1], Y[t, 2]
        d = denom[t]
        l0 = ((y1 - y2) * (fx - x2) + (x2 - x1) * (fy - y2)) / d
        l1 = ((y2 - y0) * (fx - x2) + (x0 - x2) * (fy - y2)) / d
        l2 = 1.0 - l0 - l1
        eps = -1e-6
        inside = (l0 >= eps) & (l1 >= eps) & (l2 >= eps)
        if inside.any():
            t, px, py, l0, l1, l2 = t[inside], px[inside], py[inside], l0[inside], l1[inside], l2[inside]
            z = l0 * Z[t, 0] + l1 * Z[t, 1] + l2 * Z[t, 2]
            pix = py * W + px
            order = np.lexsort((z, pix))
            pix_o = pix[order]
            first = np.ones(len(order), bool)
            first[1:] = pix_o[1:] != pix_o[:-1]
            sel = order[first]
            pix, z = pix[sel], z[sel]
            closer = z < canvas.z[pix]
            if closer.any():
                sel = sel[closer]
                pix = pix[closer]
                canvas.z[pix] = z[closer]
                canvas.rgb[pix] = shade_fn(t[sel], l0[sel], l1[sel], l2[sel])
                canvas.cover[pix] = True
        start = stop


def cluster_decimate(verts, tri_vid, target):
    """Vertex clustering on a grid; returns (verts_rep_index per vertex, kept tri mask)."""
    lo, hi = verts.min(0), verts.max(0)
    ext = (hi - lo).max()
    cells = max(8, int(np.sqrt(target / 2)))
    for _ in range(12):
        q = np.floor((verts - lo) / (ext / cells + 1e-9)).astype(np.int64)
        _, cl = np.unique(q, axis=0, return_inverse=True)
        cl = cl.ravel()
        t = cl[tri_vid]
        keep = (t[:, 0] != t[:, 1]) & (t[:, 1] != t[:, 2]) & (t[:, 0] != t[:, 2])
        if keep.sum() <= target:
            break
        cells = int(cells * 0.85)
    return cl, keep


def render_preview(name, meshes, textures_by_mesh, total_tris, out_path):
    W, H = VIEW_W * SSAA, VIEW_H * SSAA
    views = [(35, 22), (215, 22)]
    allv = np.concatenate([m.verts for m in meshes])
    center = (allv.min(0) + allv.max(0)) / 2
    # common scale across both views
    spans = []
    for az, el in views:
        r, u, _ = view_basis(az, el)
        p = allv - center
        spans.append((np.ptp(p @ r), np.ptp(p @ u)))
    sw = max(s[0] for s in spans)
    sh = max(s[1] for s in spans)
    scale = min(W * 0.84 / max(sw, 1e-6), H * 0.80 / max(sh, 1e-6))
    light_cam = np.array([-0.45, 0.65, -0.62])   # in camera space (right, up, fwd)
    light_cam /= np.linalg.norm(light_cam)
    preview_tris = 0
    panels = []
    for vi, (az, el) in enumerate(views):
        r, u, f = view_basis(az, el)
        # direction toward the light: upper-left of the camera, slightly toward it
        L = light_cam[0] * r + light_cam[1] * u + light_cam[2] * f
        L /= np.linalg.norm(L)
        canvas = Canvas(W, H)
        for mi, m in enumerate(meshes):
            cv = m.verts[m.corner_vid] - center          # per-corner positions
            sx = (cv @ r) * scale + W / 2
            sy = -(cv @ u) * scale + H / 2 + H * 0.02
            sz = cv @ f
            tri = m.tri_corner
            if len(tri) > PREVIEW_TRI_LIMIT:
                cl, keep = cluster_decimate(m.verts, m.tri_vid, PREVIEW_TRI_LIMIT)
                # snap corner positions to cluster centroid
                cent = np.zeros((cl.max() + 1, 3))
                np.add.at(cent, cl, m.verts)
                cent /= np.bincount(cl)[:, None]
                cv = cent[cl[m.corner_vid]] - center
                sx = (cv @ r) * scale + W / 2
                sy = -(cv @ u) * scale + H / 2 + H * 0.02
                sz = cv @ f
                tri = tri[keep]
            if vi == 0:
                preview_tris += len(tri)
            tex = textures_by_mesh[mi]
            uv = m.corner_uv
            nrm = m.corner_nrm
            if nrm is None:
                a, b, c = cv[tri[:, 0]], cv[tri[:, 1]], cv[tri[:, 2]]
                fn = np.cross(b - a, c - a)
                fn /= np.linalg.norm(fn, axis=1, keepdims=True) + 1e-12
            else:
                fn = None

            def shade(t, l0, l1, l2, tri=tri, uv=uv, nrm=nrm, tex=tex, fn=fn, f=f, L=L):
                if tex is not None and uv is not None:
                    c = tri[t]
                    tuv = uv[c[:, 0]] * l0[:, None] + uv[c[:, 1]] * l1[:, None] + uv[c[:, 2]] * l2[:, None]
                    col = sample_bilinear(tex, tuv)
                else:
                    col = np.full((len(t), 3), 180.0, np.float32)
                if nrm is not None:
                    c = tri[t]
                    n = nrm[c[:, 0]] * l0[:, None] + nrm[c[:, 1]] * l1[:, None] + nrm[c[:, 2]] * l2[:, None]
                    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
                else:
                    n = fn[t]
                facing = n @ f
                n = np.where(facing[:, None] > 0, -n, n)       # two-sided
                lam = np.clip(n @ L, 0, 1)
                sky = 0.5 + 0.5 * n[:, 2]                     # hemisphere ambient
                k = 0.30 + 0.16 * sky + 0.72 * lam
                return np.clip(col * k[:, None], 0, 255).astype(np.float32)

            rasterize(canvas, sx, sy, sz, tri, shade)
        img = canvas.rgb.reshape(H, W, 3)
        # subtle contact shadow-free ground line: none; keep neutral
        pim = Image.fromarray(img.astype(np.uint8)).resize((VIEW_W, VIEW_H), Image.LANCZOS)
        panels.append(pim)
    out = Image.new("RGB", (VIEW_W * 2, VIEW_H), BG)
    out.paste(panels[0], (0, 0))
    out.paste(panels[1], (VIEW_W, 0))
    d = ImageDraw.Draw(out)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 22)
        small = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 15)
    except OSError:
        font = small = ImageFont.load_default()
    label = f"{name}   {total_tris:,} tris"
    if preview_tris != total_tris:
        label += f"  (preview {preview_tris:,})"
    d.text((12, 10), label, fill=(255, 255, 255), font=font, stroke_width=2, stroke_fill=(30, 30, 30))
    d.text((12, VIEW_H - 24), "3/4 front", fill=(235, 235, 235), font=small)
    d.text((VIEW_W + 12, VIEW_H - 24), "3/4 back", fill=(235, 235, 235), font=small)
    d.line([(VIEW_W, 0), (VIEW_W, VIEW_H)], fill=(95, 95, 95), width=1)
    out.save(out_path)
    return preview_tris


# ================================================================= per model

def axis_text(gs):
    up = int(gs.get("UpAxis", 1)); ups = int(gs.get("UpAxisSign", 1))
    fr = int(gs.get("FrontAxis", 2)); frs = int(gs.get("FrontAxisSign", 1))
    co = int(gs.get("CoordAxis", 0)); cos_ = int(gs.get("CoordAxisSign", 1))
    s = lambda v: "+" if v > 0 else "-"
    return f"{s(ups)}{AXIS[up]} up, {s(frs)}{AXIS[fr]} front, {s(cos_)}{AXIS[co]} right"


def image_info(content):
    im = Image.open(io.BytesIO(content))
    info = {"format": im.format, "width": im.size[0], "height": im.size[1], "mode": im.mode}
    try:
        th = im.convert("RGB")
        th.thumbnail((128, 128))
        a = np.asarray(th, dtype=np.float32)
        info["mean_rgb"] = [round(float(x), 1) for x in a.reshape(-1, 3).mean(0)]
        info["std"] = round(float(a.std()), 2)
        info["constant"] = bool(a.std() < 1.5)
    except Exception:  # noqa: BLE001 - header info still useful
        pass
    return info


def texture_memory(w, h, role):
    px = w * h * 4 / 3   # full mip chain
    rgba = px * 4
    bc7 = px * 1
    bc1 = px * 0.5
    # UE default compression per role (single-channel masks -> BC4, normal -> BC5)
    ue = {"base_color": 0.5, "normal": 1.0, "roughness": 0.5, "metallic": 0.5}.get(role, 1.0) * px
    return rgba, bc7, bc1, ue


def process(path: Path, out_dir: Path):
    t0 = time.time()
    name = path.stem
    scene = read_fbx(path)
    t_parse = time.time() - t0
    meshes = [Mesh(scene, g) for g in scene.geometries.values()]
    gs = scene.global_settings

    # ------------------------------------------------ textures
    tex_dir = out_dir / "textures"
    tex_dir.mkdir(parents=True, exist_ok=True)
    video_role = {}
    for mat in scene.materials.values():
        for tex, prop in scene.textures_of_material(mat.id):
            vid = scene.video_of_texture(tex.id)
            if vid is not None:
                video_role.setdefault(vid.id, ROLE_NAMES.get(prop, prop or "unknown"))
    textures = []
    mem = np.zeros(4)
    n = 0
    for vid in scene.videos.values():
        if not vid.content:
            continue
        info = image_info(vid.content)
        ext = (info["format"] or "bin").lower().replace("jpeg", "jpg")
        fname = f"{name}_{n}.{ext}"
        (tex_dir / fname).write_bytes(vid.content)
        role = video_role.get(vid.id, "unknown")
        m = texture_memory(info["width"], info["height"], role)
        mem += m
        textures.append({"file": f"textures/{fname}", "source_name": vid.relative_filename or vid.name,
                         "role": role, "bytes": len(vid.content), **info})
        n += 1

    # base colour per mesh
    def base_tex_for(mesh):
        if mesh.model is None:
            return None
        for mat in scene.materials_of_model(mesh.model.id):
            tl = scene.textures_of_material(mat.id)
            tl.sort(key=lambda x: 0 if x[1] == "DiffuseColor" else 1)
            for tex, _prop in tl:
                vid = scene.video_of_texture(tex.id)
                if vid is not None and vid.content:
                    return vid
        return None

    tex_arrays, base_px = [], 0
    for m in meshes:
        vid = base_tex_for(m)
        if vid is not None:
            arr = load_texture(vid.content)
            tex_arrays.append(arr)
            im = Image.open(io.BytesIO(vid.content))
            base_px = max(base_px, im.size[0] * im.size[1])
        else:
            tex_arrays.append(None)

    # ------------------------------------------------ stats
    all_sizes = np.concatenate([m.poly_sizes for m in meshes]) if meshes else np.zeros(0, int)
    npoly = max(len(all_sizes), 1)
    allv = np.concatenate([m.verts for m in meshes]) if meshes else np.zeros((1, 3))
    bmin, bmax = allv.min(0), allv.max(0)
    ntris = int(sum(len(m.tri_corner) for m in meshes))
    quality = [mesh_quality(m) for m in meshes]
    uvq = [uv_metrics(m, base_px) for m in meshes]

    def agg(key, how="wmean"):
        vals = [(q.get(key), len(m.tri_corner)) for q, m in zip(quality, meshes) if q.get(key) is not None]
        if not vals:
            return None
        if how == "sum":
            return sum(v for v, _ in vals)
        if how == "max":
            return max(v for v, _ in vals)
        tw = sum(w for _, w in vals) or 1
        return sum(v * w for v, w in vals) / tw

    mats = set()
    for m in meshes:
        if m.model is not None:
            mats.update(x.id for x in scene.materials_of_model(m.model.id))

    stats = {
        "name": name,
        "file": str(path),
        "file_size_mb": round(path.stat().st_size / 2**20, 2),
        "fbx_version": scene.version,
        "creator": (scene.root.value("Creator") or ""),
        "geometries": len(meshes),
        "vertices": int(sum(len(m.geo.vertices) for m in meshes)),
        "render_vertices_est": int(agg("render_vertices", "sum")),
        "polygons": int(len(all_sizes)),
        "triangles": ntris,
        "quad_share": round(float((all_sizes == 4).sum() / npoly), 4),
        "tri_share": round(float((all_sizes == 3).sum() / npoly), 4),
        "ngon_share": round(float((all_sizes > 4).sum() / npoly), 4),
        "uv_sets": max((len(m.geo.uv_layers) for m in meshes), default=0),
        "uv_all_polys": all(u.get("uv_all_polys", False) for u in uvq),
        "uv_in_0_1_share": round(min((u.get("uv_in_0_1_share", 0) for u in uvq), default=0), 4),
        "uv_area_sum": round(sum(u.get("uv_area_sum", 0) for u in uvq), 3),
        "texel_density_px_per_cm_native": (round(uvq[0]["texel_density_px_per_cm"], 2)
                                          if uvq and "texel_density_px_per_cm" in uvq[0] else None),
        "normals": all(m.corner_nrm is not None for m in meshes),
        "materials": len(mats),
        "embedded_textures": len(textures),
        "textures": textures,
        "texture_mem_mb": {
            "rgba8_mips": round(mem[0] / 2**20, 1), "bc7_mips": round(mem[1] / 2**20, 1),
            "bc1_mips": round(mem[2] / 2**20, 1), "ue_default_mips": round(mem[3] / 2**20, 1)},
        "bbox_min_cm": [round(float(x), 1) for x in bmin],
        "bbox_max_cm": [round(float(x), 1) for x in bmax],
        "size_cm": [round(float(x), 1) for x in (bmax - bmin)],
        "unit_scale_factor": scene.unit_scale,
        "model_scaling": meshes[0].model_scaling if meshes else None,
        "axis": axis_text(gs),
        "degenerate_tri_share": round(agg("degenerate_tri_share"), 5),
        "duplicate_vertex_ratio": round(agg("duplicate_vertex_ratio"), 4),
        "components": int(agg("components", "sum")),
        "open_edge_share": round(agg("open_edge_share"), 5),
        "nonmanifold_edge_share": round(agg("nonmanifold_edge_share"), 5),
        "tri_area_p99_over_p1": (round(agg("tri_area_p99_over_p1", "max"), 1)
                                 if agg("tri_area_p99_over_p1", "max") else None),
        "tri_area_cv": round(agg("tri_area_cv"), 3) if agg("tri_area_cv") is not None else None,
        "surface_area_m2": round(agg("surface_area_m2", "sum"), 3),
    }

    # ------------------------------------------------ preview
    prev_dir = out_dir / "previews"
    prev_dir.mkdir(parents=True, exist_ok=True)
    t1 = time.time()
    stats["preview_triangles"] = render_preview(name, meshes, tex_arrays, ntris, prev_dir / f"{name}.png")
    stats["preview"] = f"previews/{name}.png"
    stats["timing_s"] = {"parse": round(t_parse, 2), "render": round(time.time() - t1, 2),
                         "total": round(time.time() - t0, 2)}
    return stats


# ================================================================= reports

def contact_sheets(out_dir, names, per=6, cols=2):
    sheets = []
    for i in range(0, len(names), per):
        chunk = names[i:i + per]
        rows = (len(chunk) + cols - 1) // cols
        sheet = Image.new("RGB", (VIEW_W * 2 * cols + (cols - 1) * 8, VIEW_H * rows + (rows - 1) * 8), (60, 60, 60))
        for j, n in enumerate(chunk):
            im = Image.open(out_dir / "previews" / f"{n}.png")
            sheet.paste(im, ((j % cols) * (VIEW_W * 2 + 8), (j // cols) * (VIEW_H + 8)))
        p = out_dir / f"contact_{i // per + 1}.png"
        sheet.save(p)
        sheets.append(p.name)
    return sheets


def write_markdown(out_dir, rows, totals):
    L = ["# Model review — Desktop/models FBX set", "",
         "Generated by `Tools/ModelReview/review_models.py`. Sizes are the file's native size in cm "
         "(after UnitScaleFactor, Model Lcl Scaling and the Y-up -> Z-up axis fix), W x D x H.",
         "",
         "**Scale note:** every file stores vertices normalised to a ~1.9 m longest axis "
         "(Blender export, UnitScaleFactor 1 = cm, Model Lcl Scaling 100, vertices in +/-0.95 m). "
         "The parse is correct; the source assets are simply not authored at real-world size, so each "
         "one needs a per-asset import scale (a house at 190 cm is ~4x too small). Texel density "
         "drops by the same factor.",
         "", "## Totals", ""]
    for k, v in totals.items():
        L.append(f"- **{k}**: {v}")
    L += ["", "## Per model (sorted by triangle count)", "",
          "| model | tris | verts | GPU verts est | quad % | UVs | normals | mats | textures | size cm (W x D x H) | "
          "texel px/cm | degenerate % | dup vert % | components | open edge % | area p99/p1 | "
          "tex MB RGBA / BC7 / BC1 | file MB | preview |",
          "|---|---:|---:|---:|---:|---|---|---:|---|---|---:|---:|---:|---:|---:|---:|---|---:|---|"]
    for s in rows:
        tex = ", ".join(sorted({f"{t['width']}² {t['role']}" + (" (flat)" if t.get("constant") else "")
                                for t in s["textures"]}))
        m = s["texture_mem_mb"]
        L.append(
            f"| {s['name']} | {s['triangles']:,} | {s['vertices']:,} | {s['render_vertices_est']:,} | {s['quad_share'] * 100:.0f} | "
            f"{s['uv_sets']}{'' if s['uv_all_polys'] else ' (partial)'} | {'yes' if s['normals'] else 'no'} | "
            f"{s['materials']} | {tex} | {' x '.join(f'{x:.0f}' for x in s['size_cm'])} | "
            f"{s['texel_density_px_per_cm_native'] or '-'} | {s['degenerate_tri_share'] * 100:.2f} | "
            f"{s['duplicate_vertex_ratio'] * 100:.1f} | {s['components']} | {s['open_edge_share'] * 100:.2f} | "
            f"{s['tri_area_p99_over_p1'] or '-'} | {m['rgba8_mips']:.0f} / {m['bc7_mips']:.0f} / {m['bc1_mips']:.0f} | "
            f"{s['file_size_mb']:.1f} | [png]({s['preview']}) |")
    L += ["", "## Columns", "",
          "- **GPU verts est**: corners unique by (position, UV, normal) - roughly what UE builds after splitting seams.",
          "- **degenerate %**: triangles whose welded corners collapse or whose area is < 1e-4 x the median.",
          "- **dup vert %**: 1 - (positions unique at 0.1 mm) / vertices. UV/normal seams make this non-zero by design.",
          "- **components**: connected pieces after welding positions at 0.1 mm (union-find).",
          "- **open edge %**: welded edges used by exactly one triangle (holes / boundaries).",
          "- **area p99/p1**: spread of triangle areas (uniform remesh -> small; mixed detail -> large).",
          "- **texel px/cm**: base-colour texels per cm at the file's native size; divide by the import scale.",
          "- **tex MB**: all embedded maps with full mips. BC1 = 0.5 B/px, BC7 = 1 B/px.", ""]
    (out_dir / "stats.md").write_text("\n".join(L), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(DEFAULT_SRC))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    src, out = Path(args.src), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    files = sorted(src.glob("*.fbx"))
    if args.only:
        keep = set(args.only.split(","))
        files = [f for f in files if f.stem in keep]
    rows, errors = [], {}
    with ProcessPoolExecutor(max_workers=max(1, args.jobs)) as ex:
        futs = {ex.submit(process, f, out): f for f in files}
        for fu in as_completed(futs):
            f = futs[fu]
            try:
                s = fu.result()
                rows.append(s)
                print(f"{s['name']:<12} {s['triangles']:>8,} tris  {s['size_cm']} cm  "
                      f"{s['timing_s']['total']:.1f}s", flush=True)
            except Exception as e:  # noqa: BLE001 - keep going, report at end
                errors[f.stem] = repr(e)
                print(f"{f.stem}: ERROR {e!r}", flush=True)
    rows.sort(key=lambda s: s["triangles"])
    if args.only:
        return
    sheets = contact_sheets(out, [r["name"] for r in sorted(rows, key=lambda s: s["name"])])
    mem = {k: sum(r["texture_mem_mb"][k] for r in rows) for k in rows[0]["texture_mem_mb"]} if rows else {}
    totals = {
        "models": len(rows),
        "triangles": f"{sum(r['triangles'] for r in rows):,}",
        "vertices": f"{sum(r['vertices'] for r in rows):,}",
        "embedded textures": sum(r["embedded_textures"] for r in rows),
        "texture memory RGBA8 + mips (MB)": round(mem.get("rgba8_mips", 0), 1),
        "texture memory BC7 + mips (MB)": round(mem.get("bc7_mips", 0), 1),
        "texture memory BC1 + mips (MB)": round(mem.get("bc1_mips", 0), 1),
        "texture memory UE defaults (BC1 base, BC5 normal, BC4 masks) + mips (MB)": round(mem.get("ue_default_mips", 0), 1),
        "FBX on disk (MB)": round(sum(r["file_size_mb"] for r in rows), 1),
        "contact sheets": ", ".join(sheets),
        "errors": errors or "none",
    }
    (out / "stats.json").write_text(json.dumps({"totals": totals, "models": rows}, indent=1), encoding="utf-8")
    write_markdown(out, rows, totals)
    print(json.dumps(totals, indent=1))


if __name__ == "__main__":
    main()
