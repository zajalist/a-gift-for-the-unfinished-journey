"""Stele meshes for the Saskartan inscriptions, built offline (lane STELE, 2026-09-28).

    python Tools/Look/stele_mesh.py                     # all four -> SourceArt/Steles (GLB, FBX, steles.json)
    python Tools/Look/stele_mesh.py --only WayStone_A   # one variant
    python Tools/Look/stele_preview.py                  # the preview PNGs (separate, slower)

Why: the 34 way-stones and 2 dock posts used a pack pillar (SM_Pillar_A_01) with no flat front, so
the glyph decal missed the face, and the rock texture stretched on the narrow sides. These bodies
have a FLAT, VERTICAL front face for the glyph.

Shape: a "rounded slab". A convex front silhouette S (in the Y-Z plane: tapered sides, arch / flat /
gable top, rounded corners) is extruded along X from the back face to the front face; every arris
is a quarter-circle bevel of radius rb. The back face leans in (depth taper). Then:
  - wear: fBm displacement (macro lumps + fine grain + pits + softer arrises) along the normals,
    weight 0 on the front face and ramping up across the front bevel, so the face stays a true plane;
  - chips: a few planar breaks at the top arrises (orthogonal projection onto the break plane, so the
    facets are flat, like conchoidal breaks); breaks never reach the glyph area.

Axes and units: UE's axes, +X forward (the front face looks down +X), +Y right, +Z up; metres here.
Pivot at the base centre (base footprint centred on x=y=0, bottom at z=0). The GLB is metres in glTF
axes (x, y, z)_gltf = (X, Z, Y)_ue, which UE's glTF importer maps back (x100 to cm).

Material slots (glTF materials, in this order): 0 "Stone" (everything else), 1 "Face" (the flat,
unchipped front face).
UV0: the rock texture, metric (UV0_PER_M UV units per metre) on every chart, so texel density is the
     same on the broad face, the narrow sides, the top and the back. Charts: the band (the bevels,
     sides, top and bottom as one strip around the silhouette, seam at the bottom centre, buried),
     the front face, the back face. Non-overlapping.
UV1: the glyph. On the Face slot, a planar map of the front face whose bounding rectangle is exactly
     0..1 (u to the viewer's right, v down, not mirrored). Everywhere else (-1, -1), outside.
     The glyph's own rectangle inside 0..1 is per mesh (steles.json "glyph_rect_uv1": u0, v0, su, sv),
     the material's GlyphRect parameter.
Vertex colour: R cavity (pits, low spots), G ground grime (1 at the ground, 0 by ~30 cm), B worn
edges (bevels, breaks), A 1.
"""
import argparse
import json
import math
import pathlib
import struct
import sys

import numpy as np
from scipy.spatial import ConvexHull, Delaunay, cKDTree

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "SourceArt" / "Steles"
INSCR_DIR = ROOT / "SourceArt" / "Inscriptions"
UV0_PER_M = 1.0

# padded chisel-map size (px) per glyph ID, for the glyph aspect; read from the PNG when present
GLYPH_PX = {"I05": (1230, 2240), "I02": (1008, 2240)}

# W: width (Y), D: depth (X), H: height (Z), metres. tw/td: width/depth lost at the top (fraction).
# rise: height of the top shape above the springline. rb: arris bevel radius. rc: silhouette corner
# radius (> rb). glyph_h: glyph box height on the face (padded map), glyph_zc: its centre height.
VARIANTS = {
    "WayStone_A": dict(kind="way", W=0.50, D=0.25, H=1.40, tw=0.10, td=0.16, top="arch", rise=0.17,
                       slope=0.0, rb=0.018, rc=0.034, seed=11, glyph="I05", glyph_h=0.60, glyph_zc=0.82,
                       chips=7, wear=1.0),
    "WayStone_B": dict(kind="way", W=0.47, D=0.24, H=1.32, tw=0.07, td=0.12, top="flat", rise=0.07,
                       slope=0.018, rb=0.020, rc=0.036, seed=23, glyph="I05", glyph_h=0.60, glyph_zc=0.80,
                       chips=8, wear=1.15),
    "WayStone_C": dict(kind="way", W=0.53, D=0.26, H=1.46, tw=0.12, td=0.20, top="gable", rise=0.14,
                       slope=0.0, rb=0.016, rc=0.032, seed=37, glyph="I05", glyph_h=0.60, glyph_zc=0.84,
                       chips=6, wear=0.85),
    "DockPost": dict(kind="dock", W=0.60, D=0.40, H=3.20, tw=0.06, td=0.08, top="gable", rise=0.17,
                     slope=0.0, rb=0.026, rc=0.046, seed=51, glyph="I02", glyph_h=1.00, glyph_zc=2.00,
                     chips=10, wear=1.3),
}
# sampling (metres): silhouette spacing, band spacing across the depth, bevel steps, face grid
RES = {"way": dict(ds=0.012, dband=0.014, k1=5, hface=0.018),
       "dock": dict(ds=0.02, dband=0.022, k1=6, hface=0.03)}
GLYPH_KEEPOUT = 0.025          # m around the glyph box that chips may not touch


# ------------------------------------------------------------------------------------------------
# noise
# ------------------------------------------------------------------------------------------------
class Perlin3:
    """Gradient noise in 3D, vectorised; output roughly in [-1, 1]."""

    def __init__(self, seed):
        rng = np.random.default_rng(seed)
        p = rng.permutation(256)
        self.p = np.concatenate([p, p]).astype(np.int64)
        g = rng.normal(size=(256, 3))
        self.g = g / np.linalg.norm(g, axis=1, keepdims=True)

    def __call__(self, pts):
        pts = np.asarray(pts, dtype=np.float64)
        pi = np.floor(pts).astype(np.int64)
        pf = pts - pi
        u = pf * pf * pf * (pf * (pf * 6 - 15) + 10)
        xi, yi, zi = pi[:, 0] & 255, pi[:, 1] & 255, pi[:, 2] & 255
        p = self.p
        out = np.zeros(len(pts))
        for dx in (0, 1):
            wx = u[:, 0] if dx else 1 - u[:, 0]
            for dy in (0, 1):
                wy = u[:, 1] if dy else 1 - u[:, 1]
                for dz in (0, 1):
                    wz = u[:, 2] if dz else 1 - u[:, 2]
                    h = p[p[p[xi + dx] + yi + dy] + zi + dz]
                    d = pf - np.array([dx, dy, dz], dtype=np.float64)
                    out += wx * wy * wz * np.einsum("ij,ij->i", self.g[h], d)
        return out * 1.5


def fbm(noise, pts, octaves, lacunarity=2.03, gain=0.5):
    total, amp, freq, norm = 0.0, 1.0, 1.0, 0.0
    for o in range(octaves):
        total = total + amp * noise(pts * freq + o * 17.31)
        norm += amp
        amp *= gain
        freq *= lacunarity
    return total / norm


# ------------------------------------------------------------------------------------------------
# silhouette
# ------------------------------------------------------------------------------------------------
def top_profile(style, t):
    a = np.abs(t)
    if style == "arch":
        return np.sqrt(np.clip(1.0 - t * t, 0.0, 1.0))
    if style == "flat":
        return np.clip(1.0 - a ** 6, 0.0, 1.0) ** (1.0 / 6.0)
    if style == "gable":
        return 1.0 - a ** 1.35
    raise ValueError(style)


def half_width(v, z):
    return 0.5 * v["W"] * (1.0 - v["tw"] * z / v["H"])


def x_back(v, z):
    return -0.5 * v["D"] + v["td"] * v["D"] * z / v["H"]


def core_polygon(v):
    """The convex core Q (CCW in (y, z)); S = Q offset outward by rc. Starts at the bottom centre."""
    rc, H = v["rc"], v["H"]
    hs = H - v["rise"]
    yq, rq = half_width(v, hs) - rc, H - rc - hs
    sl = v["slope"]                        # a linear tilt of the top (adds no curvature: stays convex)
    pts = [(0.0, rc), (half_width(v, 0.0) - rc, rc), (yq, hs + sl)]
    for t in np.cos(np.linspace(0.0, math.pi, 72))[1:-1]:
        f = top_profile(v["top"], t)
        pts.append((yq * t, hs + rq * f + sl * t))
    pts += [(-yq, hs - sl), (-(half_width(v, 0.0) - rc), rc)]
    # the taper can leave a hair of concavity where a side meets the top: keep the convex hull
    # (moves nothing by more than a few microns), then put the bottom-centre start back in front
    hull = np.array(pts[1:])[ConvexHull(np.array(pts[1:])).vertices]          # CCW
    br = int(np.argmin(np.abs(hull[:, 0] - (half_width(v, 0.0) - rc)) + np.abs(hull[:, 1] - rc)))
    q = np.concatenate([[(0.0, rc)], np.roll(hull, -br, axis=0)])
    e = np.roll(q, -1, axis=0) - q
    cross = e[:, 0] * np.roll(e, -1, axis=0)[:, 1] - e[:, 1] * np.roll(e, -1, axis=0)[:, 0]
    if (cross < -1e-12).any():
        raise ValueError("silhouette core is not convex")
    return q


def sample_offset(q, rc, ds):
    """Sample S = offset(q, rc) uniformly by arc length. Returns base (N,2), normal (N,2), s (N,), L.
    A point of S is base + rc*normal; any inset curve with the same parametrisation is base + r*normal."""
    m = len(q)
    e = np.roll(q, -1, axis=0) - q
    ln = np.linalg.norm(e, axis=1)
    d = e / ln[:, None]
    nrm = np.stack([d[:, 1], -d[:, 0]], 1)                       # outward for a CCW polygon
    ang = np.arctan2(nrm[:, 1], nrm[:, 0])
    pieces = []                                                  # (kind, index, length on S)
    for i in range(m):
        pieces.append(("e", i, ln[i]))
        da = (ang[(i + 1) % m] - ang[i] + math.pi) % (2 * math.pi) - math.pi
        if da > 1e-9:
            pieces.append(("a", i, rc * da))
    lengths = np.array([p[2] for p in pieces])
    starts = np.concatenate([[0.0], np.cumsum(lengths)[:-1]])
    total = float(lengths.sum())
    n = max(8, int(round(total / ds)))
    s = np.arange(n) * total / n
    base, normal = np.zeros((n, 2)), np.zeros((n, 2))
    idx = np.searchsorted(starts, s, side="right") - 1
    for k in range(n):
        kind, i, _ = pieces[idx[k]]
        loc = s[k] - starts[idx[k]]
        if kind == "e":
            base[k] = q[i] + d[i] * loc
            normal[k] = nrm[i]
        else:
            a = ang[i] + loc / rc
            base[k] = q[(i + 1) % m]
            normal[k] = (math.cos(a), math.sin(a))
    return base, normal, s, total


def interior_grid(ring, h):
    """Grid points inside the convex CCW polygon `ring`, at least 0.55 h from its edges."""
    lo, hi = ring.min(0), ring.max(0)
    ys = np.arange(lo[0] + h * 0.5, hi[0], h)
    zs = np.arange(lo[1] + h * 0.5, hi[1], h)
    g = np.stack(np.meshgrid(ys, zs), -1).reshape(-1, 2)
    e = np.roll(ring, -1, axis=0) - ring
    en = e / np.linalg.norm(e, axis=1, keepdims=True)
    inward = np.stack([-en[:, 1], en[:, 0]], 1)                  # left of the edge = inside (CCW)
    dist = ((g[:, None, :] - ring[None, :, :]) * inward[None, :, :]).sum(-1).min(1)
    return g[dist >= 0.55 * h]


def triangulate_convex(ring, inner):
    """Triangulate a convex polygon (CCW ring, all ring points kept, boundary = the ring edges) with
    interior points. Plain 2D Delaunay: collinear ring points (the straight sides) lift onto a
    parabola, so they stay hull vertices; the checks below prove it for every mesh built."""
    pts = np.concatenate([ring, inner])
    c = pts.mean(0)
    dl = Delaunay(pts - c)
    if len(dl.coplanar):
        raise ValueError("Delaunay dropped points")
    tri = dl.simplices.copy()
    a, b, cc = pts[tri[:, 0]], pts[tri[:, 1]], pts[tri[:, 2]]
    ao = (b[:, 0] - a[:, 0]) * (cc[:, 1] - a[:, 1]) - (b[:, 1] - a[:, 1]) * (cc[:, 0] - a[:, 0])
    if (np.abs(ao) < 1e-10).any():
        raise ValueError("degenerate face triangle")
    flip = ao < 0
    tri[flip] = tri[flip][:, [0, 2, 1]]
    # the boundary must be exactly the ring edges
    n = len(ring)
    edges = np.sort(np.concatenate([tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]]), axis=1)
    uniq, cnt = np.unique(edges, axis=0, return_counts=True)
    bnd = {tuple(e) for e in uniq[cnt == 1]}
    want = {tuple(sorted((j, (j + 1) % n))) for j in range(n)}
    if bnd != want:
        raise ValueError("face boundary is not the ring")
    return tri


# ------------------------------------------------------------------------------------------------
# the stele
# ------------------------------------------------------------------------------------------------
def glyph_aspect(gid):
    png = INSCR_DIR / f"T_Inscription_{gid}_N.png"
    if png.exists():
        from PIL import Image
        with Image.open(png) as im:
            return im.size[0] / im.size[1]
    w, h = GLYPH_PX[gid]
    return w / h


def build(name, v=None):
    """Build one stele. Returns a dict with the shared-vertex mesh, per-chart data and the metadata."""
    v = dict(VARIANTS[name] if v is None else v)
    r = RES[v["kind"]]
    rng = np.random.default_rng(v["seed"])
    xf = 0.5 * v["D"]
    rb, rc = v["rb"], v["rc"]

    q = core_polygon(v)
    base, n2, s, perim = sample_offset(q, rc, r["ds"])
    n = len(base)
    outer = base + rc * n2                 # S: the side band
    ring = base + (rc - rb) * n2           # the face outline (front and back)

    # cross profile: front bevel (k1+1), side band, back bevel (k1+1)
    k1 = r["k1"]
    xb_ring = x_back(v, ring[:, 1])
    band_len = (xf - rb) - (xb_ring + rb)
    k2 = max(2, int(math.ceil(band_len.max() / r["dband"])))
    alpha = np.linspace(0.0, math.pi / 2, k1 + 1)
    beta = np.linspace(math.pi / 2, math.pi, k1 + 1)
    kk = 2 * (k1 + 1) + (k2 - 1)
    B = np.zeros((n, kk, 3))
    BN = np.zeros((n, kk, 3))
    wgt = np.zeros((n, kk))                # wear weight
    edge = np.zeros((n, kk))               # arris indicator (0..1)
    for j in range(n):
        col = []
        for a in alpha:
            yz = ring[j] + rb * math.sin(a) * n2[j]
            col.append(((xf - rb + rb * math.cos(a), yz[0], yz[1]),
                        (math.cos(a), math.sin(a) * n2[j][0], math.sin(a) * n2[j][1]),
                        math.sin(a) ** 2, math.sin(2 * a)))
        x0, x1 = xf - rb, xb_ring[j] + rb
        for t in np.linspace(0, 1, k2 + 1)[1:-1]:
            col.append(((x0 + (x1 - x0) * t, outer[j][0], outer[j][1]), (0.0, n2[j][0], n2[j][1]), 1.0, 0.0))
        for b in beta:
            yz = ring[j] + rb * math.sin(b) * n2[j]
            col.append(((xb_ring[j] + rb + rb * math.cos(b), yz[0], yz[1]),
                        (math.cos(b), math.sin(b) * n2[j][0], math.sin(b) * n2[j][1]),
                        1.0, math.sin(2 * (b - math.pi / 2))))
        B[j] = [c[0] for c in col]
        BN[j] = [c[1] for c in col]
        wgt[j] = [c[2] for c in col]
        edge[j] = [c[3] for c in col]

    # faces: one triangulation of the ring outline, used front and back
    inner2 = interior_grid(ring, r["hface"])
    ftri = triangulate_convex(ring, inner2)
    mi = len(inner2)
    nb = n * kk
    V = np.concatenate([B.reshape(-1, 3),
                        np.column_stack([np.full(mi, xf), inner2]),
                        np.column_stack([x_back(v, inner2[:, 1]), inner2])])
    N0 = np.concatenate([BN.reshape(-1, 3),
                         np.tile([1.0, 0.0, 0.0], (mi, 1)),
                         np.tile(_unit([-1.0, 0.0, v["td"] * v["D"] / v["H"]]), (mi, 1))])
    W = np.concatenate([wgt.reshape(-1), np.zeros(mi), np.ones(mi)])
    EDGE = np.concatenate([edge.reshape(-1), np.zeros(mi), np.zeros(mi)])
    part = np.concatenate([np.zeros(nb, int), np.ones(mi, int), np.full(mi, 2)])    # 0 band, 1 front, 2 back
    col_j = np.concatenate([np.repeat(np.arange(n), kk), np.full(2 * mi, -1)])
    col_k = np.concatenate([np.tile(np.arange(kk), n), np.full(2 * mi, -1)])

    def fmap(t, which):
        out = np.empty_like(t)
        ringpart = t < n
        if which == 1:
            out[ringpart] = t[ringpart] * kk
            out[~ringpart] = nb + (t[~ringpart] - n)
        else:
            out[ringpart] = t[ringpart] * kk + (kk - 1)
            out[~ringpart] = nb + mi + (t[~ringpart] - n)
        return out

    tri_front = fmap(ftri, 1)
    tri_back = fmap(ftri, 2)[:, [0, 2, 1]]
    quads = []
    wrap = []
    for j in range(n):
        j1 = (j + 1) % n
        for k in range(kk - 1):
            quads.append((j * kk + k, j1 * kk + k, j1 * kk + k + 1, j * kk + k + 1))
            wrap.append(j1 == 0)
    quads = np.array(quads)
    wrap = np.array(wrap)
    tri_band = np.concatenate([quads[:, [0, 1, 2]], quads[:, [0, 2, 3]]])
    wrap_band = np.concatenate([wrap, wrap])

    # orient every part outward (reference: the analytic normals)
    def orient(tris, ref):
        a, b, c = V[tris[:, 0]], V[tris[:, 1]], V[tris[:, 2]]
        fn = np.cross(b - a, c - a)
        d = np.einsum("ij,ij->i", fn, ref)
        return d < 0

    fl = orient(tri_front, np.tile([1.0, 0, 0], (len(tri_front), 1)))
    if fl.any():
        tri_front = tri_front[:, [0, 2, 1]] if fl.all() else _bad("front winding mixed")
    fl = orient(tri_back, np.tile([-1.0, 0, 0], (len(tri_back), 1)))
    if fl.any():
        tri_back = tri_back[:, [0, 2, 1]] if fl.all() else _bad("back winding mixed")
    fl = orient(tri_band, N0[tri_band].sum(1))
    if fl.any():
        tri_band = tri_band[:, [0, 2, 1]] if fl.mean() > 0.99 else _bad("band winding mixed")

    # ---- wear
    wear = v["wear"]
    noise_a, noise_b, noise_c = Perlin3(v["seed"]), Perlin3(v["seed"] + 1), Perlin3(v["seed"] + 2)
    lump = fbm(noise_c, V / 0.5 + 3.7, 2) * 0.006 * wear         # broad unevenness of the rough sides
    macro = fbm(noise_a, V / 0.16, 4) * 0.005 * wear
    fine = fbm(noise_b, V / 0.028, 3) * 0.0016 * wear
    arris = -0.0022 * wear * EDGE * (0.55 + 0.45 * fbm(noise_c, V / 0.05, 2))
    pits = np.zeros(len(V))
    cand = np.flatnonzero(W > 0.9)
    area_est = perim * v["D"] + 2 * _poly_area(ring)
    npits = int(30 * area_est * wear)
    kd = cKDTree(V)
    for ci in rng.choice(cand, size=min(npits, len(cand)), replace=False):
        rad = rng.uniform(0.006, 0.022) * (1.4 if v["kind"] == "dock" else 1.0)
        dep = rng.uniform(0.0012, 0.004) * wear
        ids = kd.query_ball_point(V[ci], rad)
        dd = np.linalg.norm(V[ids] - V[ci], axis=1) / rad
        pits[ids] -= dep * np.clip(1 - dd * dd, 0, 1) ** 2
    disp = (lump + macro + fine + arris + pits) * W
    V = V + N0 * disp[:, None]

    # ---- chips (planar breaks at the top arrises)
    g_aspect = glyph_aspect(v["glyph"])
    gh = v["glyph_h"]
    gw = gh * g_aspect
    gzc = v["glyph_zc"]
    keep = (np.array([-gw / 2, gzc - gh / 2]) - GLYPH_KEEPOUT, np.array([gw / 2, gzc + gh / 2]) + GLYPH_KEEPOUT)
    chipped = np.zeros(len(V), bool)
    front_verts = (part == 1) | ((part == 0) & (col_k == 0))
    top_js = np.flatnonzero((n2[:, 1] > 0.3) & (outer[:, 1] > v["H"] * 0.6))
    side_js = np.flatnonzero((np.abs(n2[:, 0]) > 0.85) & (outer[:, 1] > v["H"] * 0.4))
    corner_js = np.flatnonzero((np.abs(n2[:, 0]) > 0.45) & (n2[:, 1] > 0.45) & (outer[:, 1] > v["H"] * 0.6))
    made, tries = 0, 0
    scale = 1.15 if v["kind"] == "dock" else 1.0
    while made < v["chips"] and tries < 200:
        tries += 1
        # corner: one plane across a silhouette corner (front/back face + side + top: localised by
        # itself); edge: a wedge of two planes leaning apart along the arris, so the break is a
        # short bite out of the edge, not a strip down its whole length
        kind = "corner" if (made == 0 and len(corner_js)) else rng.choice(["edge", "edge", "edge", "side", "corner"])
        js = {"corner": corner_js, "side": side_js}.get(kind, top_js)
        if not len(js):
            continue
        j = int(rng.choice(js))
        sx = 1.0 if rng.random() < 0.55 else -1.0
        xa = xf if sx > 0 else x_back(v, outer[j][1])
        anchor = np.array([xa, outer[j][0], outer[j][1]])
        nj = np.array([0.0, n2[j][0], n2[j][1]])
        tj = np.array([0.0, -n2[j][1], n2[j][0]])              # along the arris
        a, b = rng.uniform(0.5, 1.0), rng.uniform(0.5, 1.0)
        depth = (rng.uniform(0.012, 0.032) * (1.25 if kind == "corner" else 1.0) + 0.4 * rb) * scale
        if kind == "corner":
            planes = [_unit(np.array([sx * a, 0, 0]) + b * nj + rng.normal(0, 0.12, 3))]
        else:
            c1, c2 = rng.uniform(0.45, 0.95), rng.uniform(0.45, 0.95)
            planes = [_unit(np.array([sx * a, 0, 0]) + b * nj + c1 * tj),
                      _unit(np.array([sx * a, 0, 0]) + b * nj - c2 * tj)]
        sd = np.stack([(V - (anchor - p * depth)) @ p for p in planes], 1)
        m = (sd > 0).all(1)
        if m.sum() < 6:
            continue
        hit = m & front_verts
        yz = V[hit][:, 1:]
        if len(yz) and ((yz > keep[0]) & (yz < keep[1])).all(1).any():
            continue
        near = np.argmin(sd[m], axis=1)                          # onto the nearest break facet
        pn = np.array(planes)[near]
        V[m] -= np.take_along_axis(sd[m], near[:, None], 1) * pn
        chipped |= m
        made += 1

    # ---- normals: area-weighted, the unchipped front face exactly +X
    tris_all = np.concatenate([tri_band, tri_front, tri_back])
    VN = _vertex_normals(V, tris_all)
    on_face = front_verts & ~chipped
    VN[on_face] = (1.0, 0.0, 0.0)
    if np.abs(V[on_face, 0] - xf).max() > 1e-9:
        raise ValueError("front face is not flat")

    # ---- vertex colour
    zr = V[:, 2] + 0.03 * fbm(noise_c, V / 0.07, 2)
    grime_top = 0.30 if v["kind"] == "way" else 0.45
    grime = np.clip((grime_top - zr) / (grime_top - 0.06), 0, 1) ** 1.5
    cav = np.clip(-(fine + pits) / 0.0035, 0, 1) * W
    edge_c = np.clip(EDGE * (0.6 + 0.4 * fbm(noise_a, V / 0.04, 2)) + chipped * 0.7, 0, 1)
    COL = np.stack([cav, grime, edge_c, np.ones(len(V))], 1)

    # ---- face rectangle, glyph rectangle in UV1
    ymin, ymax = ring[:, 0].min(), ring[:, 0].max()
    zbot, ztop = ring[:, 1].min(), ring[:, 1].max()
    fw, fh = ymax - ymin, ztop - zbot
    u0 = (ymax - gw / 2) / fw
    v0 = (ztop - (gzc + gh / 2)) / fh
    grect = [u0, v0, gw / fw, gh / fh]

    return dict(name=name, spec=v, V=V, VN=VN, COL=COL, part=part, col_j=col_j, col_k=col_k, kk=kk, n=n,
                s=s, perim=perim, tri_band=tri_band, wrap_band=wrap_band, tri_front=tri_front,
                tri_back=tri_back, chipped=chipped, on_face=on_face, xf=xf,
                face_rect=(ymin, ymax, zbot, ztop), glyph_rect=grect, glyph_size=(gw, gh), glyph_zc=gzc,
                ring=ring)


def _unit(x):
    x = np.asarray(x, dtype=np.float64)
    return x / np.linalg.norm(x)


def _bad(msg):
    raise ValueError(msg)


def _poly_area(p):
    return 0.5 * abs(np.dot(p[:, 0], np.roll(p[:, 1], -1)) - np.dot(p[:, 1], np.roll(p[:, 0], -1)))


def _vertex_normals(V, tris):
    fn = np.cross(V[tris[:, 1]] - V[tris[:, 0]], V[tris[:, 2]] - V[tris[:, 0]])
    vn = np.zeros_like(V)
    for c in range(3):
        np.add.at(vn, tris[:, c], fn)
    ln = np.linalg.norm(vn, axis=1, keepdims=True)
    return vn / np.maximum(ln, 1e-20)


# ------------------------------------------------------------------------------------------------
# charts, UVs, primitives
# ------------------------------------------------------------------------------------------------
def primitives(m):
    """Split the shared mesh into the two export primitives with per-chart UVs.
    Returns [stone, face], each dict(pos, nrm, uv0, uv1, col, idx)."""
    V, n, kk = m["V"], m["n"], m["kk"]
    ymin, ymax, zbot, ztop = m["face_rect"]
    fw, fh = ymax - ymin, ztop - zbot
    # band UV0: u = arc length along S, v = distance along each column (final geometry)
    Bv = V[: n * kk].reshape(n, kk, 3)
    colv = np.concatenate([np.zeros((n, 1)), np.cumsum(np.linalg.norm(np.diff(Bv, axis=1), axis=2), axis=1)], 1)
    vmax = colv.max()
    gap = 0.06
    off_front = np.array([0.0, vmax + gap])
    off_back = np.array([fw + gap, vmax + gap])

    def uv0_of(vi, chart, wrapped):
        out = np.zeros((len(vi), 2))
        b = chart == 0
        j, k = np.divmod(vi[b], kk)
        out[b] = np.stack([m["s"][j] + np.where(wrapped[b], m["perim"], 0.0), colv[j, k]], -1)
        f = chart == 1
        p = V[vi[f]]
        out[f] = np.stack([ymax - p[:, 1], ztop - p[:, 2]], -1) + off_front
        k2 = chart == 2
        p = V[vi[k2]]
        out[k2] = np.stack([p[:, 1] - ymin, ztop - p[:, 2]], -1) + off_back
        return out

    face_tri = m["on_face"][m["tri_front"]].all(1)
    band_wrap = m["wrap_band"][:, None] & ((m["tri_band"] // kk) == 0)
    groups = {
        "stone": [(m["tri_band"], 0, band_wrap), (m["tri_front"][~face_tri], 1, None), (m["tri_back"], 2, None)],
        "face": [(m["tri_front"][face_tri], 1, None)],
    }
    out = []
    for gname in ("stone", "face"):
        tris = np.concatenate([g[0] for g in groups[gname]])
        chart = np.concatenate([np.full(g[0].shape, g[1]) for g in groups[gname]])
        wrapped = np.concatenate([g[2] if g[2] is not None else np.zeros(g[0].shape, bool) for g in groups[gname]])
        key = (tris.astype(np.int64) * 4 + chart) * 2 + wrapped
        uk, inv = np.unique(key.reshape(-1), return_inverse=True)
        vi, rest = np.divmod(uk, 8)
        ch, wr = np.divmod(rest, 2)
        wr = wr.astype(bool)
        pos = V[vi]
        if gname == "face":
            uv1 = np.stack([(ymax - pos[:, 1]) / fw, (ztop - pos[:, 2]) / fh], -1)
        else:
            uv1 = np.full((len(vi), 2), -1.0)
        out.append(dict(name="Stone" if gname == "stone" else "Face",
                        pos=pos, nrm=m["VN"][vi], uv0=uv0_of(vi, ch, wr) * UV0_PER_M,
                        uv1=uv1, col=m["COL"][vi], idx=inv.reshape(-1, 3).astype(np.int64)))
    return out


# ------------------------------------------------------------------------------------------------
# writers
# ------------------------------------------------------------------------------------------------
def _signed_volume(pos, idx):
    a, b, c = pos[idx[:, 0]], pos[idx[:, 1]], pos[idx[:, 2]]
    return float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)


def write_glb(path, name, prims):
    """glTF 2.0 binary. Axes (x, y, z)_gltf = (X, Z, Y)_ue, a mirror, so the winding flips too."""
    to_gltf = lambda a: np.ascontiguousarray(a[:, [0, 2, 1]], dtype=np.float32)
    total_pos = np.concatenate([to_gltf(p["pos"]) for p in prims])
    offs = np.cumsum([0] + [len(p["pos"]) for p in prims])[:-1]
    total_idx = np.concatenate([p["idx"][:, [0, 2, 1]] + o for p, o in zip(prims, offs)])
    if _signed_volume(total_pos.astype(np.float64), total_idx) <= 0:
        raise ValueError("glTF winding is inside-out")
    blob = bytearray()
    views, accessors = [], []

    def add(arr, comp, typ, target, minmax=False, normalized=False):
        while len(blob) % 4:
            blob.append(0)
        data = arr.tobytes()
        views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": len(data), "target": target})
        blob.extend(data)
        acc = {"bufferView": len(views) - 1, "componentType": comp, "count": int(len(arr)), "type": typ}
        if normalized:
            acc["normalized"] = True
        if minmax:
            acc["min"] = [float(x) for x in arr.min(0)]
            acc["max"] = [float(x) for x in arr.max(0)]
        accessors.append(acc)
        return len(accessors) - 1

    gprims = []
    for mat, p in enumerate(prims):
        nr = to_gltf(p["nrm"])
        nr /= np.linalg.norm(nr, axis=1, keepdims=True)
        attrs = {
            "POSITION": add(to_gltf(p["pos"]), 5126, "VEC3", 34962, minmax=True),
            "NORMAL": add(nr.astype(np.float32), 5126, "VEC3", 34962),
            "TEXCOORD_0": add(np.ascontiguousarray(p["uv0"], dtype=np.float32), 5126, "VEC2", 34962),
            "TEXCOORD_1": add(np.ascontiguousarray(p["uv1"], dtype=np.float32), 5126, "VEC2", 34962),
            "COLOR_0": add(np.ascontiguousarray(np.round(np.clip(p["col"], 0, 1) * 255), dtype=np.uint8),
                           5121, "VEC4", 34962, normalized=True),
        }
        ind = add(np.ascontiguousarray(p["idx"][:, [0, 2, 1]].reshape(-1), dtype=np.uint32), 5125, "SCALAR", 34963)
        gprims.append({"attributes": attrs, "indices": ind, "material": mat, "mode": 4})
    while len(blob) % 4:
        blob.append(0)
    doc = {
        "asset": {"version": "2.0", "generator": "saskartarad Tools/Look/stele_mesh.py"},
        "scene": 0, "scenes": [{"nodes": [0]}],
        "nodes": [{"name": name, "mesh": 0}],
        "meshes": [{"name": name, "primitives": gprims}],
        "materials": [
            {"name": "Stone", "pbrMetallicRoughness": {"baseColorFactor": [0.52, 0.44, 0.34, 1.0], "metallicFactor": 0.0, "roughnessFactor": 0.9}},
            {"name": "Face", "pbrMetallicRoughness": {"baseColorFactor": [0.58, 0.5, 0.39, 1.0], "metallicFactor": 0.0, "roughnessFactor": 0.85}},
        ],
        "buffers": [{"byteLength": len(blob)}],
        "bufferViews": views, "accessors": accessors,
    }
    js = json.dumps(doc, separators=(",", ":")).encode("utf-8")
    js += b" " * ((4 - len(js) % 4) % 4)
    out = struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(blob))
    out += struct.pack("<II", len(js), 0x4E4F534A) + js
    out += struct.pack("<II", len(blob), 0x004E4942) + bytes(blob)
    pathlib.Path(path).write_bytes(out)


def read_glb(path):
    """Minimal reader (for tests): returns (doc, list of primitives as dicts of numpy arrays)."""
    data = pathlib.Path(path).read_bytes()
    magic, ver, length = struct.unpack_from("<III", data, 0)
    assert magic == 0x46546C67 and ver == 2 and length == len(data)
    jl, jt = struct.unpack_from("<II", data, 12)
    doc = json.loads(data[20:20 + jl])
    bl, bt = struct.unpack_from("<II", data, 20 + jl)
    blob = data[28 + jl:28 + jl + bl]
    comp = {5126: np.float32, 5125: np.uint32, 5121: np.uint8}
    ncomp = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}

    def acc(i):
        a = doc["accessors"][i]
        bv = doc["bufferViews"][a["bufferView"]]
        arr = np.frombuffer(blob, dtype=comp[a["componentType"]], count=a["count"] * ncomp[a["type"]],
                            offset=bv["byteOffset"])
        return arr.reshape(a["count"], ncomp[a["type"]]) if ncomp[a["type"]] > 1 else arr

    prims = []
    for p in doc["meshes"][0]["primitives"]:
        d = {k: acc(v) for k, v in p["attributes"].items()}
        d["indices"] = acc(p["indices"]).reshape(-1, 3)
        d["material"] = doc["materials"][p["material"]]["name"]
        prims.append(d)
    return doc, prims


def write_fbx_ascii(path, name, prims):
    """FBX 7.4 ASCII, Z up, centimetres, UE's own axis system (so no scene conversion): a UE point
    (X, Y, Z) is written as (X, -Y, Z) (UE's FBX import negates Y); UVs have V flipped (FBX V is up).
    One mesh, two materials (Stone, Face), two UV sets (UVMap = UV0, Glyph = UV1), vertex colours."""
    pos = np.concatenate([p["pos"] for p in prims]) * 100.0
    nrm = np.concatenate([p["nrm"] for p in prims])
    uv0 = np.concatenate([p["uv0"] for p in prims])
    uv1 = np.concatenate([p["uv1"] for p in prims])
    col = np.concatenate([p["col"] for p in prims])
    offs = np.cumsum([0] + [len(p["pos"]) for p in prims])[:-1]
    idx = np.concatenate([p["idx"] + o for p, o in zip(prims, offs)])
    mats = np.concatenate([np.full(len(p["idx"]), i) for i, p in enumerate(prims)])
    fpos = pos * np.array([1.0, -1.0, 1.0])
    fnrm = nrm * np.array([1.0, -1.0, 1.0])
    # the Y negation mirrors: flip the winding so the faces stay outward (FBX is right-handed, CCW)
    fidx = idx[:, [0, 2, 1]]
    if _signed_volume(fpos, fidx) <= 0:
        raise ValueError("FBX winding is inside-out")
    pvi = fidx.copy()
    pvi[:, 2] = -pvi[:, 2] - 1                      # last corner of each polygon is stored as ~index

    def arr(a, fmt):
        flat = np.asarray(a).reshape(-1)
        body = ",".join(fmt % x for x in flat)
        return f"*{len(flat)} {{\n\t\t\t\ta: {body}\n\t\t\t}}"

    def uvs(u):
        return np.column_stack([u[:, 0], 1.0 - u[:, 1]])

    gid, mid, m0, m1 = 1000001, 1000002, 1000003, 1000004
    lines = [
        "; FBX 7.4.0 project file", "; generated by saskartarad Tools/Look/stele_mesh.py", "",
        "FBXHeaderExtension:  {", "\tFBXHeaderVersion: 1003", "\tFBXVersion: 7400", "}",
        "GlobalSettings:  {", "\tVersion: 1000", "\tProperties70:  {",
        '\t\tP: "UpAxis", "int", "Integer", "",2', '\t\tP: "UpAxisSign", "int", "Integer", "",1',
        '\t\tP: "FrontAxis", "int", "Integer", "",1', '\t\tP: "FrontAxisSign", "int", "Integer", "",-1',
        '\t\tP: "CoordAxis", "int", "Integer", "",0', '\t\tP: "CoordAxisSign", "int", "Integer", "",1',
        '\t\tP: "OriginalUpAxis", "int", "Integer", "",2', '\t\tP: "OriginalUpAxisSign", "int", "Integer", "",1',
        '\t\tP: "UnitScaleFactor", "double", "Number", "",1', '\t\tP: "OriginalUnitScaleFactor", "double", "Number", "",1',
        "\t}", "}", "",
        "Definitions:  {", "\tVersion: 100", "\tCount: 4",
        '\tObjectType: "GlobalSettings" {', "\t\tCount: 1", "\t}",
        '\tObjectType: "Model" {', "\t\tCount: 1", "\t}",
        '\tObjectType: "Geometry" {', "\t\tCount: 1", "\t}",
        '\tObjectType: "Material" {', "\t\tCount: 2", "\t}",
        "}", "",
        "Objects:  {",
        f'\tGeometry: {gid}, "Geometry::{name}", "Mesh" {{',
        f"\t\tVertices: {arr(fpos, '%.5f')}",
        f"\t\tPolygonVertexIndex: {arr(pvi, '%d')}",
        "\t\tGeometryVersion: 124",
        "\t\tLayerElementNormal: 0 {", "\t\t\tVersion: 101", '\t\t\tName: ""',
        '\t\t\tMappingInformationType: "ByVertice"', '\t\t\tReferenceInformationType: "Direct"',
        f"\t\t\tNormals: {arr(fnrm, '%.6f')}", "\t\t}",
        "\t\tLayerElementColor: 0 {", "\t\t\tVersion: 101", '\t\t\tName: "Col"',
        '\t\t\tMappingInformationType: "ByVertice"', '\t\t\tReferenceInformationType: "Direct"',
        f"\t\t\tColors: {arr(col, '%.4f')}", "\t\t}",
        "\t\tLayerElementUV: 0 {", "\t\t\tVersion: 101", '\t\t\tName: "UVMap"',
        '\t\t\tMappingInformationType: "ByVertice"', '\t\t\tReferenceInformationType: "Direct"',
        f"\t\t\tUV: {arr(uvs(uv0), '%.6f')}", "\t\t}",
        "\t\tLayerElementUV: 1 {", "\t\t\tVersion: 101", '\t\t\tName: "Glyph"',
        '\t\t\tMappingInformationType: "ByVertice"', '\t\t\tReferenceInformationType: "Direct"',
        f"\t\t\tUV: {arr(uvs(uv1), '%.6f')}", "\t\t}",
        "\t\tLayerElementMaterial: 0 {", "\t\t\tVersion: 101", '\t\t\tName: ""',
        '\t\t\tMappingInformationType: "ByPolygon"', '\t\t\tReferenceInformationType: "IndexToDirect"',
        f"\t\t\tMaterials: {arr(mats, '%d')}", "\t\t}",
        "\t\tLayer: 0 {", "\t\t\tVersion: 100",
        '\t\t\tLayerElement:  {', '\t\t\t\tType: "LayerElementNormal"', "\t\t\t\tTypedIndex: 0", "\t\t\t}",
        '\t\t\tLayerElement:  {', '\t\t\t\tType: "LayerElementColor"', "\t\t\t\tTypedIndex: 0", "\t\t\t}",
        '\t\t\tLayerElement:  {', '\t\t\t\tType: "LayerElementUV"', "\t\t\t\tTypedIndex: 0", "\t\t\t}",
        '\t\t\tLayerElement:  {', '\t\t\t\tType: "LayerElementMaterial"', "\t\t\t\tTypedIndex: 0", "\t\t\t}",
        "\t\t}",
        "\t\tLayer: 1 {", "\t\t\tVersion: 100",
        '\t\t\tLayerElement:  {', '\t\t\t\tType: "LayerElementUV"', "\t\t\t\tTypedIndex: 1", "\t\t\t}",
        "\t\t}",
        "\t}",
        f'\tModel: {mid}, "Model::{name}", "Mesh" {{', "\t\tVersion: 232", "\t\tProperties70:  {",
        '\t\t\tP: "Lcl Translation", "Lcl Translation", "", "A",0,0,0',
        '\t\t\tP: "Lcl Rotation", "Lcl Rotation", "", "A",0,0,0',
        '\t\t\tP: "Lcl Scaling", "Lcl Scaling", "", "A",1,1,1',
        "\t\t}", '\t\tShading: T', '\t\tCulling: "CullingOff"', "\t}",
    ]
    for mid_, mname, rgb in ((m0, "Stone", (0.52, 0.44, 0.34)), (m1, "Face", (0.58, 0.5, 0.39))):
        lines += [f'\tMaterial: {mid_}, "Material::{mname}", "" {{', "\t\tVersion: 102", '\t\tShadingModel: "lambert"',
                  "\t\tMultiLayer: 0", "\t\tProperties70:  {",
                  '\t\t\tP: "DiffuseColor", "Color", "", "A",%.3f,%.3f,%.3f' % rgb, "\t\t}", "\t}"]
    lines += ["}", "", "Connections:  {",
              f'\tC: "OO",{mid},0', f'\tC: "OO",{gid},{mid}', f'\tC: "OO",{m0},{mid}', f'\tC: "OO",{m1},{mid}',
              "}", ""]
    pathlib.Path(path).write_text("\n".join(lines), encoding="ascii")


# ------------------------------------------------------------------------------------------------
def summary(m, prims):
    v = m["spec"]
    allpos = np.concatenate([p["pos"] for p in prims])
    lo, hi = allpos.min(0), allpos.max(0)
    ymin, ymax, zbot, ztop = m["face_rect"]
    return {
        "mesh": "SM_Stele_" + m["name"],
        "file": "SM_Stele_" + m["name"] + ".glb",
        "kind": v["kind"], "top": v["top"], "glyph": v["glyph"],
        "size_cm": [round(float(x) * 100, 1) for x in (hi - lo)],
        "bounds_cm": {"min": [round(float(x) * 100, 2) for x in lo], "max": [round(float(x) * 100, 2) for x in hi]},
        "front_face_x_cm": round(m["xf"] * 100, 3),
        "face_rect_cm": {"y": [round(ymin * 100, 2), round(ymax * 100, 2)], "z": [round(zbot * 100, 2), round(ztop * 100, 2)]},
        "glyph_rect_uv1": [round(float(x), 5) for x in m["glyph_rect"]],
        "glyph_size_cm": [round(m["glyph_size"][0] * 100, 1), round(m["glyph_size"][1] * 100, 1)],
        "glyph_centre_cm": [round(m["xf"] * 100, 2), 0.0, round(m["glyph_zc"] * 100, 1)],
        "triangles": int(sum(len(p["idx"]) for p in prims)),
        "vertices": int(sum(len(p["pos"]) for p in prims)),
        "face_triangles": int(len(prims[1]["idx"])),
        "uv0_per_m": UV0_PER_M,
        "slots": ["Stone", "Face"],
    }


def generate(names, out_dir=OUT_DIR, fbx=True):
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "steles.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    manifest.setdefault("meshes", {})
    built = {}
    for name in names:
        m = build(name)
        prims = primitives(m)
        mesh_name = "SM_Stele_" + name
        write_glb(out_dir / f"{mesh_name}.glb", mesh_name, prims)
        if fbx:
            write_fbx_ascii(out_dir / f"{mesh_name}.fbx", mesh_name, prims)
        manifest["meshes"][name] = summary(m, prims)
        built[name] = (m, prims)
        s = manifest["meshes"][name]
        print(f"{mesh_name}: {s['triangles']} tris, {s['vertices']} verts, size {s['size_cm']} cm, "
              f"glyph rect {s['glyph_rect_uv1']}")
    manifest["axes"] = "UE: +X forward (front face), +Y right, +Z up; pivot at the base centre; GLB in metres"
    manifest["uv"] = {"uv0": f"rock, metric, {UV0_PER_M} UV per metre", "uv1": "glyph: front face bbox = 0..1, else -1"}
    manifest["vertex_color"] = {"r": "cavity", "g": "ground grime", "b": "worn edges"}
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return built


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--only", nargs="*", choices=list(VARIANTS))
    ap.add_argument("--out", default=str(OUT_DIR))
    ap.add_argument("--no-fbx", action="store_true")
    a = ap.parse_args(argv)
    generate(a.only or list(VARIANTS), a.out, fbx=not a.no_fbx)
    return 0


if __name__ == "__main__":
    sys.exit(main())
