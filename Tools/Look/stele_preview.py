"""Preview renders of the stele meshes, read back from the exported GLBs (lane STELE, 2026-09-28).

    python Tools/Look/stele_preview.py                 # every SourceArt/Steles/SM_Stele_*.glb
    python Tools/Look/stele_preview.py --dir <folder>  # another export folder

Per mesh, SM_Stele_<name>_preview.png with four panels:
  1. three-quarter view, lit: procedural sandstone on UV0, vertex-colour grime/cavity/edges, and the
     carved glyph on the Face slot through UV1 + the manifest's glyph rectangle (the chisel maps from
     SourceArt/Inscriptions, decoded as they are: OpenGL green, +G = up);
  2. front view under a low raking light (the glyph as the carrier camera would read it);
  3. a UV0 checker (5 cm squares) from the back three-quarter: square, same-size checks everywhere
     = even texel density, no stretch on the narrow sides;
  4. the UV layouts: UV0 charts, and UV1 (the face = 0..1, the glyph rectangle in red).
Plus steles_preview.png: all four side by side at their true relative size.

It is a small numpy z-buffer rasteriser (orthographic), so it proves the geometry, the axes after the
GLB round trip (UE: +X forward, +Y right, +Z up; a camera facing -X sees -Y on its right) and the UV
mapping. It is not a stand-in for UE's lighting.
"""
import argparse
import json
import pathlib
import sys

import numpy as np
from PIL import Image
from scipy import ndimage

LOOK = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(LOOK))
import stele_mesh as sm  # noqa: E402


def load_ue(path):
    """GLB -> UE-axis arrays (metres): pos, nrm, uv0, uv1, col, tris, slot (0 Stone, 1 Face)."""
    doc, prims = sm.read_glb(path)
    parts = []
    off = 0
    for i, p in enumerate(prims):
        pos = p["POSITION"].astype(np.float64)[:, [0, 2, 1]]
        nrm = p["NORMAL"].astype(np.float64)[:, [0, 2, 1]]
        parts.append(dict(pos=pos, nrm=nrm, uv0=p["TEXCOORD_0"].astype(np.float64),
                          uv1=p["TEXCOORD_1"].astype(np.float64), col=p["COLOR_0"].astype(np.float64) / 255.0,
                          tris=p["indices"].astype(np.int64) + off,
                          slot=np.full(len(p["indices"]), 1 if p["material"] == "Face" else 0)))
        off += len(pos)
    cat = lambda k: np.concatenate([q[k] for q in parts])
    return dict(pos=cat("pos"), nrm=cat("nrm"), uv0=cat("uv0"), uv1=cat("uv1"), col=cat("col"),
                tris=cat("tris"), slot=cat("slot"))


def camera(f):
    f = sm._unit(f)
    right = sm._unit(np.cross([0.0, 0.0, 1.0], f))      # UE: facing +X, +Y is on the right
    up = np.cross(f, right)
    return f, right, up


def rasterize(mesh, f, px_per_m, pad=0.04):
    f, right, up = camera(f)
    P = mesh["pos"]
    sx, sy, dz = P @ right, P @ up, P @ f
    x0, x1, y0, y1 = sx.min() - pad, sx.max() + pad, sy.min() - pad, sy.max() + pad
    W, H = int((x1 - x0) * px_per_m), int((y1 - y0) * px_per_m)
    X = (sx - x0) * px_per_m
    Y = (y1 - sy) * px_per_m
    attrs = np.concatenate([P, mesh["nrm"], mesh["uv0"], mesh["uv1"], mesh["col"]], 1)
    zbuf = np.full((H, W), np.inf)
    out = np.zeros((H, W, attrs.shape[1]))
    slot = np.full((H, W), -1)
    tris = mesh["tris"]
    facing = (mesh["nrm"][tris].sum(1) @ f) < 0.3
    for ti in np.flatnonzero(facing):
        t = tris[ti]
        xa, xb, xc = X[t]
        ya, yb, yc = Y[t]
        xmin, xmax = max(0, int(np.floor(min(xa, xb, xc)))), min(W - 1, int(np.ceil(max(xa, xb, xc))))
        ymin, ymax = max(0, int(np.floor(min(ya, yb, yc)))), min(H - 1, int(np.ceil(max(ya, yb, yc))))
        if xmax < xmin or ymax < ymin:
            continue
        d = (yb - yc) * (xa - xc) + (xc - xb) * (ya - yc)
        if abs(d) < 1e-12:
            continue
        gx, gy = np.meshgrid(np.arange(xmin, xmax + 1) + 0.5, np.arange(ymin, ymax + 1) + 0.5)
        w0 = ((yb - yc) * (gx - xc) + (xc - xb) * (gy - yc)) / d
        w1 = ((yc - ya) * (gx - xc) + (xa - xc) * (gy - yc)) / d
        w2 = 1.0 - w0 - w1
        inside = (w0 >= -1e-4) & (w1 >= -1e-4) & (w2 >= -1e-4)
        z = w0 * dz[t[0]] + w1 * dz[t[1]] + w2 * dz[t[2]]
        sub = zbuf[ymin:ymax + 1, xmin:xmax + 1]
        upd = inside & (z < sub)
        if not upd.any():
            continue
        sub[upd] = z[upd]
        o = out[ymin:ymax + 1, xmin:xmax + 1]
        o[upd] = w0[upd, None] * attrs[t[0]] + w1[upd, None] * attrs[t[1]] + w2[upd, None] * attrs[t[2]]
        slot[ymin:ymax + 1, xmin:xmax + 1][upd] = mesh["slot"][ti]
    return out, slot, (f, right, up)


def value_noise_image(size, cells, seed):
    rng = np.random.default_rng(seed)
    g = rng.random((cells + 3, cells + 3))
    z = ndimage.zoom(g, size / cells, order=3)
    return z[:size, :size]


class Sandstone:
    """A procedural stand-in for the rock texture: 2 m x 2 m, sampled with UV0 (metres)."""

    def __init__(self, seed=5, size=1024, metres=2.0):
        self.size, self.metres = size, metres
        n = (0.45 * value_noise_image(size, 6, seed) + 0.3 * value_noise_image(size, 24, seed + 1)
             + 0.25 * value_noise_image(size, 96, seed + 2))
        strata = 0.5 + 0.5 * np.sin(np.linspace(0, 2 * np.pi * 9, size))[:, None] * value_noise_image(size, 5, seed + 3)
        self.lum = 0.72 + 0.28 * n * (0.8 + 0.2 * strata)

    def __call__(self, uv):
        px = (uv / self.metres * self.size) % self.size
        return self.lum[px[..., 1].astype(int), px[..., 0].astype(int)]


def load_glyph(gid):
    d = sm.INSCR_DIR
    n = np.array(Image.open(d / f"T_Inscription_{gid}_N.png")).astype(np.float64) / 255.0 * 2 - 1
    ao = np.array(Image.open(d / f"T_Inscription_{gid}_AO.png")).astype(np.float64) / 255.0
    return n, ao


def shade(buf, slot, cam, info, glyph, rock, light, checker=False, depth_strength=1.0, wear=0.25):
    H, W, _ = buf.shape
    mask = slot >= 0
    P, N = buf[..., 0:3], buf[..., 3:6]
    uv0, uv1, col = buf[..., 6:8], buf[..., 8:10], buf[..., 10:14]
    N = N / np.maximum(np.linalg.norm(N, axis=-1, keepdims=True), 1e-9)
    if checker:
        c = (np.floor(uv0[..., 0] / 0.05) + np.floor(uv0[..., 1] / 0.05)) % 2
        base = np.where(c[..., None] > 0, [0.82, 0.8, 0.74], [0.32, 0.36, 0.44])
        lam = np.clip((N * light).sum(-1), 0, 1)
        img = base * (0.45 + 0.55 * lam)[..., None]
    else:
        lum = rock(uv0)
        base = np.stack([0.60 * lum, 0.50 * lum, 0.38 * lum], -1)
        base *= (1 - 0.3 * col[..., 0:1])
        base = base * (1 - 0.6 * col[..., 1:2]) + np.array([0.26, 0.22, 0.16]) * 0.6 * col[..., 1:2]
        base *= (1 + 0.14 * col[..., 2:3])
        ao_px = np.ones((H, W))
        face = slot == 1
        if glyph is not None and face.any():
            gn, gao = glyph
            u0, v0, su, sv = info["glyph_rect_uv1"]
            gu = (uv1[..., 0] - u0) / su
            gv = (uv1[..., 1] - v0) / sv
            inside = face & (gu >= 0) & (gu <= 1) & (gv >= 0) & (gv <= 1)
            gh, gw = gao.shape
            ix = np.clip((gu * (gw - 1)).astype(int), 0, gw - 1)
            iy = np.clip((gv * (gh - 1)).astype(int), 0, gh - 1)
            tn = gn[iy, ix]
            groove = 1 - gao[iy, ix]
            k = depth_strength * (1 - wear * (0.5 + 0.5 * np.sin(P[..., 1] * 97 + P[..., 2] * 61))) * inside
            # tangent frame of the front face as UV1 lays it: +u = -Y (right), +v = -Z (down), out = +X
            # the chisel maps are OpenGL green (+G = up = +Z)
            tw = tn[..., 0:1] * np.array([0, -1.0, 0]) + tn[..., 1:2] * np.array([0, 0, 1.0]) + tn[..., 2:3] * np.array([1.0, 0, 0])
            N = np.where(inside[..., None], sm_norm(N * (1 - k[..., None]) + tw * k[..., None]), N)
            cut = np.clip(groove * 3.3, 0, 1) * k
            base *= (1 - 0.22 * cut)[..., None]
            ao_px = 1 - (1 - gao[iy, ix]) * k
        lam = np.clip((N * light).sum(-1), 0, 1)
        img = base * (0.22 * (1 - 0.4 * col[..., 0]) * ao_px + 1.05 * lam * ao_px)[..., None]
    img = np.clip(img, 0, 1) ** (1 / 2.2)
    bg = np.array([0.93, 0.92, 0.9])
    return np.where(mask[..., None], img, bg)


def sm_norm(x):
    return x / np.maximum(np.linalg.norm(x, axis=-1, keepdims=True), 1e-9)


def uv_panel(ax, mesh, info):
    t = mesh["tris"]
    for s_, colr in ((0, "#8a7a66"), (1, "#2f6f8f")):
        tt = t[mesh["slot"] == s_]
        uv = mesh["uv0"]
        segs = np.concatenate([uv[tt[:, [0, 1]]], uv[tt[:, [1, 2]]]])
        from matplotlib.collections import LineCollection
        ax.add_collection(LineCollection(segs[::3], colors=colr, linewidths=0.15))
    ax.set_title("UV0 (metres; blue = Face slot)", fontsize=8)
    ax.autoscale()
    ax.set_aspect("equal")
    ax.invert_yaxis()
    ax.tick_params(labelsize=6)


def uv1_panel(ax, mesh, info):
    from matplotlib.collections import LineCollection
    from matplotlib.patches import Rectangle
    t = mesh["tris"][mesh["slot"] == 1]
    uv = mesh["uv1"]
    ax.add_collection(LineCollection(np.concatenate([uv[t[:, [0, 1]]], uv[t[:, [1, 2]]]])[::2], colors="#2f6f8f", linewidths=0.15))
    u0, v0, su, sv = info["glyph_rect_uv1"]
    ax.add_patch(Rectangle((u0, v0), su, sv, fill=False, ec="#c0392b", lw=1.2))
    ax.add_patch(Rectangle((0, 0), 1, 1, fill=False, ec="k", lw=0.6, ls="--"))
    ax.set_xlim(-0.05, 1.05)
    ax.set_ylim(1.05, -0.05)
    ax.set_aspect("equal")
    ax.set_title("UV1: face = 0..1, glyph rect (red)", fontsize=8)
    ax.tick_params(labelsize=6)


def render_one(glb, info, out_png, px=420):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    mesh = load_ue(glb)
    glyph = load_glyph(info["glyph"])
    rock = Sandstone()
    tall = info["size_cm"][2] > 200
    ppm = px / (3.25 if tall else 1.5)
    sun = sm._unit([0.62, 0.5, 0.6])
    rake = sm._unit([0.32, 0.62, 0.72])
    b1, s1, c1 = rasterize(mesh, [-1.0, -0.72, -0.32], ppm)
    img1 = shade(b1, s1, c1, info, glyph, rock, sun)
    b2, s2, c2 = rasterize(mesh, [-1.0, 0.0, 0.0], ppm * 1.25)
    img2 = shade(b2, s2, c2, info, glyph, rock, rake)
    b3, s3, c3 = rasterize(mesh, [0.8, 0.85, -0.45], ppm)
    img3 = shade(b3, s3, c3, info, None, rock, sun, checker=True)
    fig = plt.figure(figsize=(15, 7.5 if not tall else 10), dpi=110)
    gs = fig.add_gridspec(2, 4, height_ratios=[1, 1])
    for k, (img, title) in enumerate([(img1, "three-quarter (sun)"), (img2, "front, raking light"),
                                      (img3, "UV0 checker, 5 cm (back three-quarter)")]):
        ax = fig.add_subplot(gs[:, k])
        ax.imshow(img)
        ax.set_title(title, fontsize=9)
        ax.axis("off")
    uv_panel(fig.add_subplot(gs[0, 3]), mesh, info)
    uv1_panel(fig.add_subplot(gs[1, 3]), mesh, info)
    fig.suptitle(f"{info['mesh']}  {info['size_cm'][1]:.0f} x {info['size_cm'][0]:.0f} x {info['size_cm'][2]:.0f} cm (W x D x H), "
                 f"{info['triangles']} tris, glyph {info['glyph']} {info['glyph_size_cm'][0]:.0f} x {info['glyph_size_cm'][1]:.0f} cm",
                 fontsize=10)
    fig.tight_layout()
    fig.savefig(out_png)
    plt.close(fig)
    return img1


def contact_sheet(imgs, heights_m, out_png, px_per_m=300):
    tiles = []
    for img, h in zip(imgs, heights_m):
        im = Image.fromarray((img * 255).astype(np.uint8))
        scale = (h * px_per_m) / im.size[1]
        tiles.append(im.resize((max(1, int(im.size[0] * scale)), int(h * px_per_m)), Image.LANCZOS))
    W = sum(t.size[0] for t in tiles) + 40 * (len(tiles) + 1)
    H = max(t.size[1] for t in tiles) + 80
    sheet = Image.new("RGB", (W, H), (237, 235, 230))
    x = 40
    for t in tiles:
        sheet.paste(t, (x, H - 40 - t.size[1]))
        x += t.size[0] + 40
    sheet.save(out_png)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", default=str(sm.OUT_DIR))
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args(argv)
    d = pathlib.Path(a.dir)
    manifest = json.loads((d / "steles.json").read_text(encoding="utf-8"))
    names = a.only or list(manifest["meshes"])
    imgs, hs = [], []
    for name in names:
        info = manifest["meshes"][name]
        img = render_one(d / info["file"], info, d / f"{info['mesh']}_preview.png")
        imgs.append(img)
        hs.append(info["size_cm"][2] / 100.0 * 1.08)
        print("preview", d / f"{info['mesh']}_preview.png")
    if not a.only:
        contact_sheet(imgs, hs, d / "steles_preview.png")
        print("preview", d / "steles_preview.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
