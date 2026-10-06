"""Metro-style sensor glass, purely optical: the baked maps and an offline preview that really refracts.

    python Tools/UI/make_sensor_glass.py bake          # maps -> Saved/UI/SensorGlass/ (+ manifest.json, _maps.png)
    python Tools/UI/make_sensor_glass.py preview       # the numpy port of Shaders/SensorGlass.ush over game frames
    python Tools/UI/make_sensor_glass.py gif           # a short GIF of the side band: drops condensing, runners sliding
    python Tools/UI/make_sensor_glass.py --selftest    # invariants: clean centre, Amount 0 identity, no chroma on cracks

User: "like this but purely refractions" (docs/look/refs/metro_glass_ref_3.jpg); "it's not a colour texture -
it is all driven by normals and refraction of light". Recipe: docs/look/SENSOR_GLASS.md.

Every map is data for the optics, never a colour (numpy, scipy, Pillow; fixed seed; nothing downloaded):

  T_SensorGlass_CrackN[_1024].png  2048x1152 (and 1024x576), screen-stretched, clamp, raw RGBA8:
      rg  the crack normal, screen space (x right, y down: the DirectX convention), sqrt-encoded:
          byte = 128 + round(127 * e), e = sign(n) * sqrt(|n|); the shader decodes n = e * |e|. Shard tilts
          (0.004-0.02) and fracture faces (0.35-0.9) share the field two decades apart.
      b   mist on the faces near the impacts (mirror-mist-hackle), 1 in the crushed star centres
      a   shard id (0 = intact glass): the per-shard glint twinkle
  T_SensorGlass_Frost.png          1024x576, clamp, raw RGBA8: r frost (crush halo, corner haze, top strip),
                                   g crush (the star centres), b a 0
  T_SensorGlass_DropQ.png          2048x1024, WRAP, raw RGBA8 (1024 texels = one screen height):
      rg  q / 2, the drop-local position normalised to the drop outline (|q| = 1 on it), byte 128 = 0,
          dilated 3 px outward; background q = (2, 2)
      b   life phase (0..1)
      a   radius code (radius / 1.5 px at 1080p, 1..15) * 16 + low code: 0..11 contact-angle variation,
          12..15 a dust fleck with absorption 0.5..0.9 (flecks never fade)
  T_SensorGlass_FlatN.png / T_SensorGlass_Zero.png  4x4 neutral maps that switch off the old CRT damage layer
  manifest.json, _maps.png (contact sheet), previews/ (preview panels, GIF)

Layout (from ref 3): nine damage sites, all on the border (four corners, two top stars, the sagging top arc,
the left and right edges); long, thin, mostly straight rays; concentric pieces only as short chords near a
star; shards enclosed between rays tilt a little; the centre (superellipse edge < 0.25) is exactly clean and
only two designated long rays pass edge 0.42.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "Saved" / "UI" / "SensorGlass"
VW, VH = 1920.0, 1080.0             # the virtual 1080p frame the layout is authored in (px)
CRACK_SETS = ((2048, 1152, ""), (1024, 576, "_1024"))
FROST_WH = (1024, 576)
DROP_WH = (2048, 1024)
SEED = 20260928
CLEAN = 0.25                        # edge below this: every crack map is exactly 0
LONG_ONLY = 0.42                    # edge below this: only the designated long rays

# damage sites (UV, y down), crush radius r0 (px at 1080p), ray count, angle range (deg, screen, y down)
SITES = [
    dict(name="TL", uv=(0.01, 0.03), r0=26, rays=12, rng=(2, 88)),
    dict(name="Top", uv=(0.37, -0.005), r0=16, rays=9, rng=(8, 172)),
    dict(name="TopR", uv=(0.71, -0.005), r0=16, rays=10, rng=(8, 172)),
    dict(name="TR", uv=(0.99, 0.02), r0=14, rays=6, rng=(92, 178)),
    dict(name="Right", uv=(1.005, 0.52), r0=18, rays=8, rng=(98, 262)),
    dict(name="Left", uv=(-0.005, 0.47), r0=14, rays=6, rng=(-82, 82)),
    dict(name="BL", uv=(0.02, 0.98), r0=28, rays=12, rng=(-88, -2)),
    dict(name="BR", uv=(0.982, 0.955), r0=22, rays=10, rng=(182, 268)),
]
DESIGNATED = {"BL": -38.0, "TopR": 118.0}   # the two long rays (site: heading, deg) that may pass edge 0.42
ARC = ((0.50, 0.0), (0.63, 0.0), 0.10)      # the long sagging crack along the top edge


# --------------------------------------------------------------------------- helpers
def smoothstep(e0, e1, x):
    t = np.clip((np.asarray(x, np.float64) - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def saturate(x):
    return np.clip(x, 0.0, 1.0)


def edge_metric(u, v):
    cx = np.abs(np.asarray(u, np.float64) - 0.5) * 2.0
    cy = np.abs(np.asarray(v, np.float64) - 0.5) * 2.0
    return np.sqrt(np.sqrt(cx ** 4 + cy ** 4))


def wrap_pi(a):
    return (a + np.pi) % (2.0 * np.pi) - np.pi


def noise1d(rng, n):
    knots = rng.random(int(n) + 3)

    def f(s):
        s = np.asarray(s, np.float64)
        i = np.clip(np.floor(s).astype(int), 0, len(knots) - 2)
        t = np.clip(s - i, 0.0, 1.0)
        t = t * t * (3.0 - 2.0 * t)
        return knots[i] * (1.0 - t) + knots[i + 1] * t
    return f


def value_noise(rng, shape, cells):
    """Smooth value noise in [0, 1] of the given shape with about `cells` cells across the height."""
    h, w = shape
    gh, gw = int(cells) + 2, int(cells * w / h) + 2
    grid = rng.random((gh, gw))
    return np.clip(ndimage.zoom(grid, (h / (gh - 1), w / (gw - 1)), order=3)[:h, :w], 0.0, 1.0)


def fbm(rng, shape, base=4, octaves=4):
    acc = np.zeros(shape)
    amp, tot = 1.0, 0.0
    for o in range(octaves):
        acc += amp * value_noise(rng, shape, base * 2 ** o)
        tot += amp
        amp *= 0.5
    return acc / tot


def enc_signed(x):
    """-1..1 -> byte, 128 exactly 0 (decode: (byte - 128) / 127)."""
    return np.clip(128.0 + np.round(127.0 * np.clip(x, -1.0, 1.0)), 1, 255).astype(np.uint8)


def save_rgba(path, arr_u8):
    Image.fromarray(arr_u8, "RGBA").save(path, optimize=True)


# --------------------------------------------------------------------------- crack layout
class Layout:
    """Crack polylines in the virtual 1080p frame, with per-vertex width, face magnitude, slant sign and mist."""

    def __init__(self, rng):
        self.rng = rng
        self.cracks = []            # dicts: pts, w, m, sign, mist, sid, designated, site, kind
        self.occ = np.zeros((int(VH / 3) + 3, int(VW / 3) + 3), bool)
        self.sites = []             # dicts: c, inward, r0, primary [(pts, maxr)], chords [(wedge, th, r)]

    def hit(self, p):
        i, j = int(p[1] // 3), int(p[0] // 3)
        if 0 <= i < self.occ.shape[0] and 0 <= j < self.occ.shape[1]:
            return bool(self.occ[i, j])
        return False

    def mark(self, pts):
        for a, b in zip(pts[:-1], pts[1:]):
            n = int(np.ceil(np.linalg.norm(b - a) / 1.5)) + 1
            for t in np.linspace(0.0, 1.0, n):
                p = a + (b - a) * t
                i, j = int(p[1] // 3), int(p[0] // 3)
                if 0 <= i < self.occ.shape[0] and 0 <= j < self.occ.shape[1]:
                    self.occ[i, j] = True

    def walk(self, p0, heading, length, designated=False, skip=3, branch_p=0.008, depth=0):
        rng = self.rng
        step = 6.0
        pts = [np.asarray(p0, np.float64)]
        h = heading
        n = max(2, int(length / step))
        stop_edge = CLEAN + 0.03 if designated else LONG_ONLY
        branches = []
        for i in range(n):
            h += rng.normal(0.0, math.radians(0.8 if designated else 1.2))
            if rng.random() < 0.02:
                h += rng.choice((-1.0, 1.0)) * math.radians(rng.uniform(8.0, 18.0))
            p = pts[-1] + step * np.array([math.cos(h), math.sin(h)])
            if not (-14.0 <= p[0] <= VW + 14.0 and -14.0 <= p[1] <= VH + 14.0):
                pts.append(p)
                break
            if float(edge_metric(p[0] / VW, p[1] / VH)) < stop_edge:
                break
            if not designated and i > max(skip, 0.4 * n) and self.hit(p) and rng.random() < 0.7:
                pts.append(p)      # T-junction: the crack runs into an older one and stops
                break
            pts.append(p)
            if depth == 0 and i > 3 and rng.random() < branch_p:
                rem = (n - i) * step
                branches.append((p.copy(), h + rng.choice((-1.0, 1.0)) * math.radians(rng.uniform(12.0, 30.0)),
                                 rem * rng.uniform(0.3, 0.6), (i + 1) * step))
        pts = np.array(pts)
        self.mark(pts)
        return pts, branches

    def add(self, pts, s0, kind, site, designated=False, width=(2.2, 0.9), mag=(0.35, 0.85), mist_k=1.0):
        if len(pts) < 2:
            return
        rng = self.rng
        seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
        s = np.concatenate([[0.0], np.cumsum(seg)])
        L = max(s[-1], 1e-6)
        f = s / L
        w = width[0] + (width[1] - width[0]) * f
        nz = noise1d(rng, L / 40.0 + 2)(s / 40.0)
        m = (mag[0] + (mag[1] - mag[0]) * nz) * (1.0 - smoothstep(0.78, 1.0, f))
        flips = rng.random(len(pts)) < 0.01 * np.concatenate([[0.0], seg]) / 6.0
        sign = np.where(np.cumsum(flips) % 2 == 0, 1.0, -1.0) * rng.choice((-1.0, 1.0))
        mz = noise1d(rng, L / 30.0 + 2)(s / 30.0)
        mist = mist_k * np.exp(-(s0 + s) / (0.08 * VH)) * (0.4 + 0.6 * mz)
        self.cracks.append(dict(pts=pts, w=w, m=m, sign=sign, mist=mist, sid=float(rng.uniform(0.05, 1.0)),
                                designated=designated, site=site, kind=kind))


def ray_length(rng):
    u = rng.random()
    if u < 0.25:
        return rng.uniform(0.03, 0.08) * VH
    if u < 0.7:
        return rng.uniform(0.1, 0.25) * VH
    return rng.uniform(0.25, 0.45) * VH


def ray_polar(pts, c, inward):
    d = pts - c
    r = np.maximum.accumulate(np.hypot(d[:, 0], d[:, 1]))
    th = np.unwrap(wrap_pi(np.arctan2(d[:, 1], d[:, 0]) - inward))
    return r, th


def point_at_radius(pts, c, rad):
    d = np.hypot(pts[:, 0] - c[0], pts[:, 1] - c[1])
    idx = np.nonzero(d >= rad)[0]
    if len(idx) == 0 or idx[0] == 0:
        return None
    i = idx[0]
    t = (rad - d[i - 1]) / max(d[i] - d[i - 1], 1e-6)
    return pts[i - 1] + (pts[i] - pts[i - 1]) * t


def build_layout(rng):
    L = Layout(rng)
    for si, site in enumerate(SITES):
        c = np.array([site["uv"][0] * VW, site["uv"][1] * VH])
        lo, hi = site["rng"]
        inward = math.radians(0.5 * (lo + hi))
        r0 = site["r0"]
        n = site["rays"]
        ang = lo + (hi - lo) * (np.arange(n) + 0.5 + rng.uniform(-0.3, 0.3, n)) / n
        ang[0], ang[-1] = lo + rng.uniform(0, 3), hi - rng.uniform(0, 3)    # two rays run along the border
        des_k = -1
        if site["name"] in DESIGNATED:
            des_k = int(np.argmin(np.abs(ang - DESIGNATED[site["name"]])))
            ang[des_k] = DESIGNATED[site["name"]]
        primary = []
        for k, a in enumerate(ang):
            des = k == des_k
            length = 0.55 * VH if des else ray_length(rng)
            h = math.radians(a)
            start = c + 0.6 * r0 * np.array([math.cos(h), math.sin(h)])
            pts, br = L.walk(start, h, length, designated=des)
            L.add(pts, 0.6 * r0, "ray", si, designated=des)
            if len(pts) >= 2:
                primary.append((pts, a))
            for bp, bh, bl, bs in br:
                bpts, _ = L.walk(bp, bh, bl, skip=5, depth=1)
                L.add(bpts, 0.6 * r0 + bs, "branch", si, width=(1.5, 0.8), mag=(0.3, 0.7))
        # short spikes around the crushed centre (the star)
        for _ in range(int(rng.integers(8, 15))):
            a = math.radians(rng.uniform(lo - 5, hi + 5))
            start = c + 0.7 * r0 * np.array([math.cos(a), math.sin(a)])
            pts, _ = L.walk(start, a, rng.uniform(0.6, 1.8) * r0, skip=99, branch_p=0.0, depth=1)
            L.add(pts, 0.7 * r0, "spike", si, width=(1.6, 0.8), mag=(0.3, 0.7), mist_k=1.2)
        # concentric chords between adjacent primary rays, never full rings
        primary.sort(key=lambda t: t[1])
        chords = []
        for w in range(1, len(primary)):
            pa, pb = primary[w - 1][0], primary[w][0]
            for mult in (2.2, 3.6, 5.5):
                if rng.random() > 0.55:
                    continue
                rc = r0 * mult * rng.uniform(0.85, 1.15)
                A = point_at_radius(pa, c, rc)
                B = point_at_radius(pb, c, rc)
                if A is None or B is None:
                    continue
                ta = math.atan2(A[1] - c[1], A[0] - c[0])
                tb = math.atan2(B[1] - c[1], B[0] - c[0])
                tb = ta + wrap_pi(tb - ta)
                nseg = int(rng.integers(3, 5))
                bow = rng.uniform(-0.06, 0.08)
                ts = np.linspace(0.0, 1.0, nseg + 1)
                rr = np.hypot(*(A - c)) * (1 - ts) + np.hypot(*(B - c)) * ts
                rr = rr * (1.0 + bow * np.sin(np.pi * ts)) + np.r_[0.0, rng.normal(0, 0.8, nseg - 1), 0.0]
                th = ta + (tb - ta) * ts
                cp = np.stack([c[0] + rr * np.cos(th), c[1] + rr * np.sin(th)], 1)
                dense = np.concatenate([cp[i] + (cp[i + 1] - cp[i]) * np.linspace(0, 1, 5)[:-1, None]
                                        for i in range(nseg)] + [cp[-1:]])
                L.add(dense, rc, "chord", si, width=(1.4, 1.0), mag=(0.3, 0.6))
                L.mark(dense)
                thr = np.unwrap(wrap_pi(th - inward))
                chords.append((w, thr, rr))
        L.sites.append(dict(c=c, inward=inward, r0=r0, name=site["name"],
                            primary=[(p, float(np.hypot(*(p[-1] - c)))) for p, _ in primary], chords=chords))
    # the long sagging arc along the top edge, with two short offshoots
    (u0, v0), (u1, v1), sag = ARC
    t = np.linspace(0.0, 1.0, 60)
    x = (u0 + (u1 - u0) * t) * VW
    y = (sag * np.sin(np.pi * t) ** 0.8 + rng.normal(0, 0.002, len(t)) * np.sin(np.pi * t)) * VH
    y[0], y[-1] = -2.0, -2.0
    arc = np.stack([x, y], 1)
    L.add(arc, 0.12 * VH, "arc", -1, width=(1.8, 1.0), mag=(0.4, 0.75), mist_k=2.0)
    L.mark(arc)
    for tt in (0.3, 0.7):
        i = int(tt * (len(arc) - 1))
        h = math.atan2(arc[i + 1, 1] - arc[i, 1], arc[i + 1, 0] - arc[i, 0]) + math.radians(rng.choice((-1, 1)) * rng.uniform(50, 80))
        if math.sin(h) < 0:
            h = -h
        pts, _ = L.walk(arc[i], h, rng.uniform(0.04, 0.09) * VH, skip=4, depth=1)
        L.add(pts, 0.14 * VH, "branch", -1, width=(1.3, 0.8), mag=(0.3, 0.6))
    return L


# --------------------------------------------------------------------------- crack raster
def densify(L):
    P, PERP, W, M, S, MI, SID, DES = [], [], [], [], [], [], [], []
    for cr in L.cracks:
        pts = cr["pts"]
        for i in range(len(pts) - 1):
            a, b = pts[i], pts[i + 1]
            seg = np.linalg.norm(b - a)
            if seg < 1e-6:
                continue
            n = max(2, int(np.ceil(seg / 0.5)) + 1)
            t = np.linspace(0.0, 1.0, n)[:-1] if i < len(pts) - 2 else np.linspace(0.0, 1.0, n)
            d = (b - a) / seg
            P.append(a + (b - a) * t[:, None])
            PERP.append(np.repeat([[-d[1], d[0]]], len(t), 0))
            for arr, key in ((W, "w"), (M, "m"), (S, "sign"), (MI, "mist")):
                arr.append(cr[key][i] * (1 - t) + cr[key][i + 1] * t)
            S[-1] = np.where(S[-1] >= 0, 1.0, -1.0)
            SID.append(np.full(len(t), cr["sid"]))
            DES.append(np.full(len(t), cr["designated"]))
    cat = np.concatenate
    return dict(p=cat(P), perp=cat(PERP), w=cat(W), m=cat(M), sign=cat(S), mist=cat(MI), sid=cat(SID),
                des=cat(DES))


def tilt_field(L, P, rng):
    """Shard tilts: the glass between two rays (and between concentric chords) is a plate pushed in a little.
    Constant per shard, fading with distance from the impact and ending where the shorter bounding ray ends."""
    n = np.zeros_like(P)
    sid = np.zeros(len(P))
    for si, site in enumerate(L.sites):
        prim = site["primary"]
        if not prim:
            continue
        c, inward, r0 = site["c"], site["inward"], site["r0"]
        rmax = max(m for _, m in prim) * 1.15
        d = P - c
        r = np.hypot(d[:, 0], d[:, 1])
        idx = np.nonzero((r < rmax) & (r > r0 * 0.9))[0]
        if len(idx) == 0:
            continue
        rr = r[idx]
        th = wrap_pi(np.arctan2(d[idx, 1], d[idx, 0]) - inward)
        K = len(prim)
        RT = np.empty((K, len(idx)))
        lens = np.empty(K)
        for k, (pts, maxr) in enumerate(prim):
            rp, tp = ray_polar(pts, c, inward)
            RT[k] = np.interp(rr, rp, tp)
            lens[k] = maxr
        wedge = (RT < th[None, :]).sum(0)
        ring = np.zeros(len(idx), int)
        for w, thr, rch in site["chords"]:
            sel = wedge == w
            order = np.argsort(thr)
            ring[sel] += (rr[sel] > np.interp(th[sel], thr[order], rch[order])).astype(int)
        lo_len = np.where(wedge > 0, lens[np.clip(wedge - 1, 0, K - 1)], np.inf)
        hi_len = np.where(wedge < K, lens[np.clip(wedge, 0, K - 1)], np.inf)
        lmin = np.minimum(lo_len, hi_len)
        lab = wedge * 10 + ring
        labels = np.unique(lab)
        # constant direction per shard: inward radial at the shard's mean angle, turned by up to 50 deg
        ca = np.bincount(np.searchsorted(labels, lab), weights=np.cos(th), minlength=len(labels))
        sa = np.bincount(np.searchsorted(labels, lab), weights=np.sin(th), minlength=len(labels))
        mean_th = np.arctan2(sa, ca) + inward
        turn = rng.uniform(-0.87, 0.87, len(labels))
        mag = rng.uniform(0.004, 0.02, len(labels))
        ids = rng.uniform(0.05, 1.0, len(labels))
        li = np.searchsorted(labels, lab)
        dirx = -np.cos(mean_th[li] + turn[li])
        diry = -np.sin(mean_th[li] + turn[li])
        amp = mag[li] * np.exp(-rr / (0.12 * VH)) * (1.0 - smoothstep(0.85, 1.1, rr / lmin))
        n[idx, 0] += dirx * amp
        n[idx, 1] += diry * amp
        sid[idx] = np.where(amp > 1e-4, ids[li], sid[idx])
    return n, sid


def crush_field(L, P, rng):
    """The crushed star centres: micro-shards (Voronoi cells about 4 px) with steep random facets."""
    n = np.zeros_like(P)
    sid = np.zeros(len(P))
    inside = np.zeros(len(P), bool)
    for site in L.sites:
        c, r0 = site["c"], site["r0"]
        d = P - c
        r = np.hypot(d[:, 0], d[:, 1])
        th = np.arctan2(d[:, 1], d[:, 0])
        harm = sum(rng.uniform(0.03, 0.09) * np.cos(k * th + rng.uniform(0, 6.28)) for k in (3, 5, 8))
        idx = np.nonzero(r < r0 * (1.0 + harm) * 1.05)[0]
        if len(idx) == 0:
            continue
        ns = int(np.pi * (r0 * 1.3) ** 2 / 16.0)
        sr = r0 * 1.3 * np.sqrt(rng.random(ns))
        sa = rng.uniform(0, 2 * np.pi, ns)
        seeds = c + np.stack([sr * np.cos(sa), sr * np.sin(sa)], 1)
        _, nearest = cKDTree(seeds).query(P[idx])
        ang = rng.uniform(0, 2 * np.pi, ns)
        mag = rng.uniform(0.15, 0.45, ns)
        n[idx, 0] = np.cos(ang[nearest]) * mag[nearest]
        n[idx, 1] = np.sin(ang[nearest]) * mag[nearest]
        sid[idx] = rng.uniform(0.05, 1.0, ns)[nearest]
        inside[idx] = True
    return n, sid, inside


def raster_cracks(L, samples, Wt, Ht, rng_t, rng_c):
    k = Ht / VH
    xs = (np.arange(Wt) + 0.5) / k
    ys = (np.arange(Ht) + 0.5) / k
    X, Y = np.meshgrid(xs, ys)
    P = np.stack([X.ravel(), Y.ravel()], 1)
    fw = max(1.0, 1.0 / k)                       # box filter width in 1080p px
    tree = cKDTree(samples["p"])
    d, idx = tree.query(P, distance_upper_bound=3.5 + fw)
    ok = np.isfinite(d)
    ii = idx[ok]
    sp = samples["sign"][ii] * np.einsum("ij,ij->i", P[ok] - samples["p"][ii], samples["perp"][ii])
    w = samples["w"][ii]
    cov = (np.clip(sp + fw / 2, 0, w) - np.clip(sp - fw / 2, 0, w)) / fw
    covm = (np.clip(sp + fw / 2, -0.6, w + 0.6) - np.clip(sp - fw / 2, -0.6, w + 0.6)) / fw
    face = np.zeros((len(P), 2))
    face[ok] = (samples["sign"][ii] * samples["m"][ii])[:, None] * samples["perp"][ii]
    fcov = np.zeros(len(P))
    fcov[ok] = cov
    mist = np.zeros(len(P))
    mist[ok] = np.clip(covm, 0, 1) * samples["mist"][ii]
    fsid = np.zeros(len(P))
    fsid[ok] = samples["sid"][ii]
    des = np.zeros(len(P), bool)
    des[ok] = samples["des"][ii]
    tilt, tsid = tilt_field(L, P, rng_t)
    crn, csid, crushed = crush_field(L, P, rng_c)
    em = edge_metric(P[:, 0] / VW, P[:, 1] / VH)
    tilt *= smoothstep(LONG_ONLY, LONG_ONLY + 0.08, em)[:, None]
    n = face * fcov[:, None] + tilt * (1.0 - fcov[:, None])
    shard = np.where(fcov > 0.02, fsid, tsid)
    n[crushed] = crn[crushed]
    shard[crushed] = csid[crushed]
    mist[crushed] = 1.0
    # clean-zone invariants: nothing below CLEAN; only the designated long rays below LONG_ONLY
    keep = (em >= LONG_ONLY) | ((em >= CLEAN) & des & (fcov > 0))
    n[~keep] = 0.0
    mist[~keep] = 0.0
    shard[~keep] = 0.0
    fcov_k = np.where(keep, fcov, 0.0)
    e = np.sign(n) * np.sqrt(np.abs(n))
    rgba = np.zeros((len(P), 4), np.uint8)
    rgba[:, 0] = enc_signed(e[:, 0])
    rgba[:, 1] = enc_signed(e[:, 1])
    rgba[:, 2] = np.round(np.clip(mist, 0, 1) * 255).astype(np.uint8)
    rgba[:, 3] = np.round(np.clip(shard, 0, 1) * 255).astype(np.uint8)
    stats = dict(face_frac=float((fcov_k > 0.5).mean()), crushed_frac=float(crushed.mean()),
                 shard_frac=float((np.abs(tilt).sum(1) > 1e-4).mean()),
                 max_tilt=float(np.abs(tilt).max()))
    return rgba.reshape(Ht, Wt, 4), stats


def frost_map(L, Wt, Ht, rng):
    k = Ht / VH
    X, Y = np.meshgrid((np.arange(Wt) + 0.5) / k, (np.arange(Ht) + 0.5) / k)
    frost = np.zeros((Ht, Wt))
    crush = np.zeros((Ht, Wt))
    nz = fbm(rng, (Ht, Wt), base=6)
    for site in L.sites:
        c, r0 = site["c"], site["r0"]
        d = np.hypot(X - c[0], Y - c[1])
        halo = np.exp(-np.maximum(d - r0, 0.0) / (2.5 * r0))
        frost = np.maximum(frost, halo * (0.55 + 0.45 * nz))
        crush = np.maximum(crush, 1.0 - smoothstep(0.8 * r0, 1.1 * r0, d))
    for cx, cy in ((0, 0), (VW, 0), (0, VH), (VW, VH)):
        d = np.hypot(X - cx, Y - cy)
        frost = np.maximum(frost, np.exp(-(d / (0.18 * VH)) ** 2) * (0.3 + 0.4 * nz))
    frost = np.maximum(frost, 0.14 * (1.0 - smoothstep(0.0, 0.05 * VH, Y)) * nz)
    frost *= smoothstep(LONG_ONLY, 0.6, edge_metric(X / VW, Y / VH))
    rgba = np.zeros((Ht, Wt, 4), np.uint8)
    rgba[..., 0] = np.round(np.clip(frost, 0, 1) * 255)
    rgba[..., 1] = np.round(np.clip(crush, 0, 1) * 255)
    return rgba


# --------------------------------------------------------------------------- drop sheet
def drop_shape(rng, r):
    """An irregular drop: the union of 1-3 discs (+ a teardrop cap), as a polar radius R(phi) around its
    centroid, with a vertical stretch and +-12 % edge noise."""
    discs = [(0.0, 0.0, r)]
    for _ in range(int(rng.choice([0, 1, 2], p=[0.5, 0.35, 0.15]))):
        a = rng.uniform(0, 2 * np.pi)
        off = rng.uniform(0.2, 0.5) * r
        discs.append((off * math.cos(a), off * math.sin(a), r * rng.uniform(0.45, 0.8)))
    if rng.random() < 0.45:
        discs.append((rng.normal(0, 0.1 * r), -rng.uniform(0.4, 0.7) * r, r * rng.uniform(0.35, 0.6)))
    wts = np.array([d[2] ** 2 for d in discs])
    cx = sum(d[0] * w for d, w in zip(discs, wts)) / wts.sum()
    cy = sum(d[1] * w for d, w in zip(discs, wts)) / wts.sum()
    phi = np.linspace(0, 2 * np.pi, 64, endpoint=False)
    u = np.stack([np.cos(phi), np.sin(phi)], 1)
    R = np.zeros(64)
    for ox, oy, rho in discs:
        o = np.array([ox - cx, oy - cy])
        b = u @ o
        disc = b * b - (o @ o - rho * rho)
        R = np.maximum(R, np.where(disc >= 0, b + np.sqrt(np.maximum(disc, 0)), 0))
    R *= 1.0 + sum(rng.uniform(0.0, 0.05) * np.cos(k * phi + rng.uniform(0, 6.28)) for k in (2, 3, 5))
    return R, rng.uniform(1.0, 1.5)


def build_drops(rng, Wd=DROP_WH[0], Hd=DROP_WH[1], n_drops=900, n_fleck=150):
    k = Hd / VH                                   # texels per 1080p px
    u = rng.random(n_drops)
    rad = np.where(u < 0.6, rng.uniform(2, 4, n_drops), np.where(u < 0.9, rng.uniform(4, 7, n_drops),
                                                                      rng.uniform(7, 10, n_drops)))
    rad = np.concatenate([np.sort(rad)[::-1], rng.uniform(0.8, 2.0, n_fleck)])
    is_fleck = np.r_[np.zeros(n_drops, bool), np.ones(n_fleck, bool)]
    centres = []
    bound = []
    for r in rad:
        rb = r * 1.7                              # bounding radius of the irregular shape (1080p px)
        for _ in range(200):
            c = np.array([rng.uniform(0, Wd), rng.uniform(0, Hd)])
            if centres:
                C = np.array(centres)
                dd = np.abs(C - c)
                dd = np.minimum(dd, np.array([Wd, Hd]) - dd)
                if np.any(np.hypot(dd[:, 0], dd[:, 1]) < (np.array(bound) + rb) * k + 3.0 * k):
                    continue
            centres.append(c)
            bound.append(rb)
            break
        else:
            centres.append(None)
            bound.append(0.0)
    best = np.full((Hd, Wd), 9.0)
    Q = np.zeros((Hd, Wd, 2))
    info = np.zeros((Hd, Wd, 2))                  # phase, code
    placed = 0
    for i, (c, r) in enumerate(zip(centres, rad)):
        if c is None:
            continue
        R, sv = drop_shape(rng, r)
        phase = rng.random()
        rcode = int(np.clip(round(float(R.mean()) / 1.5), 1, 15))
        low = int(rng.integers(12, 16)) if is_fleck[i] else int(rng.integers(0, 12))
        code = rcode * 16 + low
        ext = (R.max() * sv + 3.0) * k + 2
        x0, x1 = int(np.floor(c[0] - ext)), int(np.ceil(c[0] + ext))
        y0, y1 = int(np.floor(c[1] - ext)), int(np.ceil(c[1] + ext))
        xs = np.arange(x0, x1 + 1)
        ys = np.arange(y0, y1 + 1)
        XX, YY = np.meshgrid(xs, ys)
        dx = (XX + 0.5 - c[0]) / k
        dy = (YY + 0.5 - c[1]) / k
        phi = np.arctan2(dy / sv, dx) % (2 * np.pi)
        Rp = np.interp(phi, np.linspace(0, 2 * np.pi, 65), np.r_[R, R[0]])
        rq = np.hypot(dx, dy / sv) / np.maximum(Rp, 1e-6)
        dist = np.hypot(dx, dy)
        qx = dx / np.maximum(dist, 1e-6) * rq
        qy = dy / np.maximum(dist, 1e-6) * rq
        inside = rq < 1.0 + 3.0 / max(float(R.mean()), 0.5)
        yy = YY % Hd
        xx = XX % Wd
        sel = inside & (rq < best[yy, xx])
        best[yy[sel], xx[sel]] = rq[sel]
        Q[yy[sel], xx[sel], 0] = qx[sel]
        Q[yy[sel], xx[sel], 1] = qy[sel]
        info[yy[sel], xx[sel], 0] = phase
        info[yy[sel], xx[sel], 1] = code
        placed += 1
    bg = best >= 9.0
    Q[bg] = 2.0
    rgba = np.zeros((Hd, Wd, 4), np.uint8)
    rgba[..., 0] = enc_signed(Q[..., 0] / 2.0)
    rgba[..., 1] = enc_signed(Q[..., 1] / 2.0)
    rgba[..., 2] = np.round(np.clip(info[..., 0], 0, 1) * 255)
    rgba[..., 3] = info[..., 1].astype(np.uint8)
    return rgba, dict(placed=placed, drops=int(n_drops), flecks=int(n_fleck),
                      cover=float((best < 1.0).mean()))


# --------------------------------------------------------------------------- bake
def bake(out=OUT, seed=SEED):
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    L = build_layout(np.random.default_rng(seed + 1))
    samples = densify(L)
    manifest = dict(seed=seed, sites=[dict(name=s["name"], uv=s["uv"], r0=s["r0"], rays=s["rays"]) for s in SITES],
                    designated=DESIGNATED, arc=ARC, cracks=len(L.cracks), maps={})
    for Wt, Ht, suf in CRACK_SETS:
        rgba, stats = raster_cracks(L, samples, Wt, Ht, np.random.default_rng(seed + 2), np.random.default_rng(seed + 3))
        name = f"T_SensorGlass_CrackN{suf}.png"
        save_rgba(out / name, rgba)
        manifest["maps"][name] = dict(size=[Wt, Ht], **stats)
        print(name, stats)
    fr = frost_map(L, *FROST_WH, np.random.default_rng(seed + 4))
    save_rgba(out / "T_SensorGlass_Frost.png", fr)
    manifest["maps"]["T_SensorGlass_Frost.png"] = dict(size=list(FROST_WH))
    dr, dstats = build_drops(np.random.default_rng(seed + 5))
    save_rgba(out / "T_SensorGlass_DropQ.png", dr)
    manifest["maps"]["T_SensorGlass_DropQ.png"] = dict(size=list(DROP_WH), **dstats)
    print("DropQ", dstats)
    flat = np.zeros((4, 4, 4), np.uint8)
    flat[..., 0], flat[..., 1], flat[..., 2], flat[..., 3] = 128, 128, 255, 255
    save_rgba(out / "T_SensorGlass_FlatN.png", flat)
    save_rgba(out / "T_SensorGlass_Zero.png", np.zeros((4, 4, 4), np.uint8))
    manifest["invariants"] = check_invariants(out)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    contact_sheet(out)
    return manifest


def load_maps(out=OUT, suffix=""):
    rd = lambda n: np.asarray(Image.open(out / n).convert("RGBA"), np.float64) / 255.0
    return dict(crack=rd(f"T_SensorGlass_CrackN{suffix}.png"), frost=rd("T_SensorGlass_Frost.png"),
                drop=rd("T_SensorGlass_DropQ.png"))


def check_invariants(out=OUT):
    res = {}
    for Wt, Ht, suf in CRACK_SETS:
        a = np.asarray(Image.open(out / f"T_SensorGlass_CrackN{suf}.png").convert("RGBA")).astype(int)
        X, Y = np.meshgrid((np.arange(Wt) + 0.5) / Wt, (np.arange(Ht) + 0.5) / Ht)
        em = edge_metric(X, Y)
        feature = (a[..., 0] != 128) | (a[..., 1] != 128) | (a[..., 2] != 0) | (a[..., 3] != 0)
        e = (a[..., :2] - 128) / 127.0
        nmag = np.hypot(*(e * np.abs(e)).transpose(2, 0, 1))
        res[f"crack{suf}"] = dict(
            clean_centre=bool(not feature[em < CLEAN].any()),
            features_below_042_px=int(feature[em < LONG_ONLY].sum()),
            face_px_frac=float((nmag > 0.2).mean()),
        )
    fr = np.asarray(Image.open(out / "T_SensorGlass_Frost.png").convert("RGBA")).astype(int)
    X, Y = np.meshgrid((np.arange(FROST_WH[0]) + 0.5) / FROST_WH[0], (np.arange(FROST_WH[1]) + 0.5) / FROST_WH[1])
    res["frost_clean_centre"] = bool(not (fr[..., :2][edge_metric(X, Y) < CLEAN] > 0).any())
    res["impacts_on_border"] = bool(all(min(abs(s["uv"][0]), abs(1 - s["uv"][0]), abs(s["uv"][1]), abs(1 - s["uv"][1])) <= 0.02
                                        for s in SITES))
    res["ok"] = bool(res["crack"]["clean_centre"] and res["crack_1024"]["clean_centre"] and res["frost_clean_centre"]
                     and res["crack"]["face_px_frac"] < 0.035 and res["impacts_on_border"])
    return res


def contact_sheet(out=OUT):
    m = load_maps(out)
    cr, fr, dr = m["crack"], m["frost"], m["drop"]
    e = (cr[..., :2] * 255 - 128) / 127.0
    n = e * np.abs(e)
    nv = np.clip(0.5 + np.dstack([n[..., 0], n[..., 1], np.zeros_like(n[..., 0])]) * 0.9, 0, 1)
    nv[..., 2] = np.clip(np.hypot(n[..., 0], n[..., 1]) * 1.5, 0, 1)
    tilt = np.clip(0.5 + np.dstack([n[..., 0], n[..., 1], np.zeros_like(n[..., 0])]) * 25.0, 0, 1)
    tilt[..., 2] = 0.5
    mist = np.dstack([cr[..., 2]] * 3)
    shard = np.dstack([cr[..., 3]] * 3)
    frost = np.dstack([fr[..., 0], fr[..., 1] * 0.6, fr[..., 0] * 0.3])
    q = (dr[..., :2] * 255 - 128) / 127.0 * 2
    dv = np.dstack([0.5 + q[..., 0] * 0.5, 0.5 + q[..., 1] * 0.5, (np.hypot(q[..., 0], q[..., 1]) < 1) * 1.0])
    tiles = [("crack normal (x0.9)", nv), ("shard tilt (x25)", tilt), ("mist", mist), ("shard id", shard),
             ("frost r / crush g", frost), ("drop sheet q", dv)]
    TW, TH = 768, 432
    sheet = Image.new("RGB", (TW * 3, (TH + 22) * 2), (20, 20, 20))
    dr_ = ImageDraw.Draw(sheet)
    for i, (label, img) in enumerate(tiles):
        im = Image.fromarray((np.clip(img, 0, 1) * 255).astype(np.uint8)).resize((TW, TH), Image.LANCZOS)
        x, y = (i % 3) * TW, (i // 3) * (TH + 22)
        sheet.paste(im, (x, y + 22))
        dr_.text((x + 6, y + 5), label, fill=(230, 230, 230))
    sheet.save(out / "_maps.png")


# --------------------------------------------------------------------------- numpy port of SensorGlass.ush
def Hash(px, py):
    with np.errstate(over="ignore"):
        vx = np.floor(np.asarray(px, np.float64)).astype(np.int64).astype(np.uint32)
        vy = np.floor(np.asarray(py, np.float64)).astype(np.int64).astype(np.uint32)
        vx = vx * np.uint32(1664525) + np.uint32(1013904223)
        vy = vy * np.uint32(1664525) + np.uint32(1013904223)
        vx = vx + vy * np.uint32(1664525)
        vy = vy + vx * np.uint32(1664525)
        vx = vx ^ (vx >> np.uint32(16))
        vy = vy ^ (vy >> np.uint32(16))
        vx = vx + vy * np.uint32(1664525)
    return (vx >> np.uint32(8)).astype(np.float64) / 16777216.0


def Noise(px, py):
    ix, iy = np.floor(px), np.floor(py)
    fx, fy = px - ix, py - iy
    fx = fx * fx * (3 - 2 * fx)
    fy = fy * fy * (3 - 2 * fy)
    a0, a1 = Hash(ix, iy), Hash(ix + 1, iy)
    a2, a3 = Hash(ix, iy + 1), Hash(ix + 1, iy + 1)
    return (a0 * (1 - fx) + a1 * fx) * (1 - fy) + (a2 * (1 - fx) + a3 * fx) * fy


def bilinear(img, u, v, wrap=False):
    h, w = img.shape[:2]
    x = u * w - 0.5
    y = v * h - 0.5
    x0 = np.floor(x)
    y0 = np.floor(y)
    fx = (x - x0)[..., None]
    fy = (y - y0)[..., None]
    x0 = x0.astype(np.int64)
    y0 = y0.astype(np.int64)
    if wrap:
        x1, y1 = (x0 + 1) % w, (y0 + 1) % h
        x0, y0 = x0 % w, y0 % h
    else:
        x1, y1 = np.clip(x0 + 1, 0, w - 1), np.clip(y0 + 1, 0, h - 1)
        x0, y0 = np.clip(x0, 0, w - 1), np.clip(y0, 0, h - 1)
    return ((img[y0, x0] * (1 - fx) + img[y0, x1] * fx) * (1 - fy) + (img[y1, x0] * (1 - fx) + img[y1, x1] * fx) * fy)


def nearest(img, u, v, wrap=False):
    """Packed drop codes need point sampling; bilinear filtering invents invalid radius/phase codes."""
    h, w = img.shape[:2]
    x, y = np.floor(u * w).astype(np.int64), np.floor(v * h).astype(np.int64)
    if wrap:
        return img[y % h, x % w]
    return img[np.clip(y, 0, h - 1), np.clip(x, 0, w - 1)]


def luma(c):
    return c[..., 0] * 0.2126 + c[..., 1] * 0.7152 + c[..., 2] * 0.0722


def lobe(n3, l, p):
    h = np.asarray(l, np.float64) + np.array([0.0, 0.0, 1.0])
    h = h / np.linalg.norm(h)
    return saturate(n3 @ h) ** p


DEFAULTS = dict(CrackSpread=0.5, DropSpread=0.6, DropDensity=0.8, DropCycle=40.0, DispDrops=0.0015, FrostPx=9.0,
                FrostLift=0.25, GlintK=0.45, Humidity=0.5, Headlight=1.0, SunRef=2.0, RunnerRate=0.45,
                GustPeriod=7.0)


def runner(Px, Py, T, rate):
    cw = 0.05
    colI = np.floor(Px / cw)
    n1 = Hash(colI, 7.0)
    n2 = Hash(colI, 19.0)
    per = 16.0 + 18.0 * n1
    tt = T / per + n2
    cyc = np.floor(tt)
    ti = tt - cyc
    on = (rate >= Hash(colI, cyc)).astype(np.float64)
    n4 = Hash(colI + 57.0, cyc)
    y0 = 0.02 + 0.3 * n4
    ln = 0.12 + 0.35 * Hash(colI + 13.0, cyc)
    mv = saturate(ti / 0.7)
    m = mv - 0.85 * np.sin(18.849556 * mv) / 18.849556
    yh = y0 + ln * m
    fade = 1.0 - smoothstep(0.7, 1.0, ti)
    x0 = (colI + 0.5) * cw + (n1 - 0.5) * cw * 0.3
    xp = x0 + 0.006 * np.sin(Py * 37.0 + n2 * 6.2831853 + np.sin(Py * 11.0))
    rh0 = 0.0045 + 0.003 * n4
    rh = rh0 * fade * on
    qhx = (Px - xp) / np.maximum(rh, 0.0001)
    qhy = (Py - yh) / (np.maximum(rh, 0.0001) * 1.25)
    lh = np.where(rh > 0.0001, np.hypot(qhx, qhy), 9.0)
    sp = 0.014
    kb = np.floor((Py - y0) / sp)
    yb = y0 + (kb + 0.5) * sp
    hb = Hash(kb, colI + cyc * 31.0)
    behind = (yh - rh0 * 1.6 >= yb) * (yb >= y0)
    rb = rh0 * (0.3 + 0.35 * hb) * behind * (hb >= 0.35) * fade * on
    xb = x0 + 0.006 * np.sin(yb * 37.0 + n2 * 6.2831853 + np.sin(yb * 11.0))
    qbx = (Px - xb) / np.maximum(rb, 0.0001)
    qby = (Py - yb) / np.maximum(rb, 0.0001)
    lb = np.where(rb > 0.0001, np.hypot(qbx, qby), 9.0)
    useh = lh < lb
    qx = np.where(useh, qhx, qbx)
    qy = np.where(useh, qhy, qby)
    r = np.where(useh, rh, rb)
    none = ~((lh < 9.0) | (lb < 9.0))
    qx = np.where(none, 9.0, qx)
    qy = np.where(none, 9.0, qy)
    dx = Px - xp
    tx = np.clip(dx / (rh0 * 0.8), -1.0, 1.0)
    trail = on * fade * (1.0 - smoothstep(rh0 * 0.3, rh0 * 0.9, np.abs(dx))) * (Py >= y0) * (yh >= Py)
    return qx, qy, r, trail, tx


def shade(scene, maps, T=20.0, amount=0.6, flash=0.0, storm=0.3, sun_dir_v=(-0.45, 0.25, 0.86),
          sun_lum=(2.0, 1.55, 1.1), hfov=90.0, prm=None, dbg=None):
    """Line-by-line port of Shaders/SensorGlass.ush. scene: linear HDR (H, W, 3). Returns (H, W, 3)."""
    P = dict(DEFAULTS, **(prm or {}))
    Hs, Ws = scene.shape[:2]
    ys, xs = np.mgrid[0:Hs, 0:Ws]
    UV = np.stack([(xs + 0.5) / Ws, (ys + 0.5) / Hs], -1)
    Scene = lambda uv: bilinear(scene, np.clip(uv[..., 0], 0.0005, 0.9995), np.clip(uv[..., 1], 0.0005, 0.9995))
    def Refract(uv):
        # Match FGlass.Refract: rays leaving the viewport show the local scene,
        # rather than stretching a bright edge texel into a colored stripe.
        border = np.minimum(uv, 1.0 - uv).min(-1)
        fade = smoothstep(0.0, 0.01, border)
        return Scene(UV) + (Scene(uv) - Scene(UV)) * fade[..., None]
    a = float(np.clip(amount, 0, 1))
    if a <= 0.001:
        return Scene(UV)
    g = min(a / 0.6, 1.0)
    hi = float(np.clip((a - 0.6) / 0.25, 0, 1))
    asp = Ws / Hs
    s1080 = Hs / 1080.0
    px = UV * np.array([Ws, Hs])
    cq = np.abs(UV - 0.5) * 2.0
    edge = np.sqrt(np.sqrt(cq[..., 0] ** 4 + cq[..., 1] ** 4))
    m00 = 1.0 / math.tan(math.radians(hfov) / 2)
    lens = 0.5 * np.array([m00, m00 * asp])
    st = float(np.clip(storm, 0, 1))
    hum = float(np.clip(P["Humidity"], 0, 1))
    gp = P["GustPeriod"]
    gs = 0.65 * math.sin(6.2831853 * T / gp) + 0.35 * math.sin(6.2831853 * T / (gp * 1.618) + 1.7)
    gust = float(np.clip((gs - 0.55) / 0.45, 0, 1))
    # cracks
    CrackN = bilinear(maps["crack"], UV[..., 0], UV[..., 1])
    FrostM = bilinear(maps["frost"], UV[..., 0], UV[..., 1])
    e = CrackN[..., :2] * 2.00787402 - 1.00787402
    nC = e * np.abs(e)
    mist = CrackN[..., 2]
    shard = CrackN[..., 3]
    frost = FrostM[..., 0]
    crush = FrostM[..., 1]
    ph = shard * 61.0
    wob = ((0.002 + 0.004 * gust) * (shard >= 0.01))[..., None] * np.stack(
        [np.sin(T * (13.0 + 9.0 * shard) + ph), np.cos(T * (11.0 + 7.0 * shard) + ph * 1.3)], -1)
    nC = nC * (0.55 + 0.45 * g)
    lenC = np.hypot(nC[..., 0], nC[..., 1])
    offC = (nC + wob * 0.15) * P["CrackSpread"]
    # drops
    duvS = np.stack([UV[..., 0] * asp * 0.5, UV[..., 1]], -1)
    DropQ = nearest(maps["drop"], duvS[..., 0], duvS[..., 1], wrap=True)
    q = DropQ[..., :2] * 4.01574803 - 2.01574803
    phase = DropQ[..., 2]
    code = np.floor(DropQ[..., 3] * 255.0 + 0.5)
    rcode = np.floor(code / 16.0)
    lo = code - rcode * 16.0
    fleck = np.where(lo > 11.5, 0.5 + (lo - 12.0) * 0.1333, 0.0)
    cvar = saturate(lo / 11.0)
    perm = (fleck >= 0.01).astype(np.float64)
    dens = P["DropDensity"] * (0.35 + 0.65 * g + 0.3 * hi) * (0.22 + 0.78 * smoothstep(0.15, 0.85, edge)) * (
        1.0 + 0.35 * (UV[..., 1] <= 0.45))
    # Radius code zero is the empty sheet. Phase zero otherwise passes the life test.
    alive = np.maximum((dens >= np.mod(phase * 13.73, 1.0)).astype(np.float64), perm) * (rcode >= 0.5)
    life = np.mod(T / (P["DropCycle"] * (0.7 + 0.6 * np.mod(phase * 7.31, 1.0))) + phase, 1.0)
    sr = (smoothstep(0.0, 0.06, life) * (1.0 - smoothstep(0.5, 1.0, life))) * (1 - perm) + perm
    qs = q / np.maximum(sr, 0.05)[..., None]
    rq = np.hypot(qs[..., 0], qs[..., 1])
    rpx = rcode * 1.5 * s1080 * sr
    trail = np.zeros((Hs, Ws))
    offT = np.zeros((Hs, Ws, 2))
    rate = P["RunnerRate"] * (0.6 + 0.4 * hi) * (a >= 0.5) * float(np.clip((hum - 0.3) * 5.0, 0, 1))
    if rate > 0.001:
        band = np.abs(UV[..., 0] - 0.5) > 0.3
        qx, qy, rr, tr, tx = runner(UV[..., 0] * asp, UV[..., 1], T, rate)
        tr = tr * band
        trail = tr
        offT[..., 0] = -tx * 0.03 * tr
        lr = np.hypot(qx, qy)
        # Zero-radius runner sentinels must not create half-covered side strips.
        use = band & (rr > 0.0001) & (lr < rq)
        qs = np.where(use[..., None], np.stack([qx, qy], -1), qs)
        rq = np.where(use, lr, rq)
        rpx = np.where(use, rr * Hs, rpx)
        alive = np.where(use, 1.0, alive)
        sr = np.where(use, 1.0, sr)
        cvar = np.where(use, 0.55, cvar)
        fleck = np.where(use, 0.0, fleck)
    cov = alive * (sr >= 0.2) * saturate((1.0 - rq) * rpx / 1.2 + 0.5)
    sa = np.minimum(rq * (0.6 + 0.35 * cvar), 0.999)
    so = 1.333 * sa
    tir = smoothstep(0.95, 1.0, so) * cov
    dev = np.arcsin(np.minimum(so, 1.0)) - np.arcsin(sa)
    dirq = qs / np.maximum(rq, 0.0001)[..., None]
    offD = -dirq * (np.tan(np.minimum(dev, 0.9)) * P["DropSpread"] * cov)[..., None]
    # refracted scene
    duv = (offC + offD + offT) * lens
    k = P["DispDrops"] * cov * (a >= 0.5)
    dsp = offD * lens * k[..., None]
    col = Refract(UV + duv)
    split = k > 0.0001
    if split.any():
        col[..., 0] = np.where(split, Refract(UV + duv - dsp)[..., 0], col[..., 0])
        col[..., 2] = np.where(split, Refract(UV + duv + dsp)[..., 2], col[..., 2])
    small = np.hypot(duv[..., 0] * Ws, duv[..., 1] * Hs) < 0.3
    col = np.where(small[..., None], Scene(UV), col)
    # condensation
    breath = 0.5 + 0.5 * math.sin(6.2831853 * T / 9.0)
    band_ = smoothstep(0.8, 1.0, UV[..., 1] + 0.06 * (Noise(px[..., 0] / (70.0 * s1080), px[..., 1] / (70.0 * s1080)) - 0.5)) * (
        0.55 + 0.45 * smoothstep(0.2, 0.45, np.abs(UV[..., 0] - 0.5)))
    fog = (max(hum - 0.6, 0.0) * 0.5 * (0.2 + 0.8 * smoothstep(0.3, 1.0, edge)) + band_ * min(hum * 1.4, 1.0) * (0.2 + 0.1 * breath)) * g
    fog = fog * (1.0 - trail) * (1.0 - cov)
    # features
    feat = mist + frost + cov + fleck + saturate(lenC * 40.0) + fog + trail
    fm = feat > 0.01
    R = 0.04 * np.array([1.0 / asp, 1.0])
    m = 0.25 * (Refract(UV + [R[0], 0]) + Refract(UV - [R[0], 0]) + Refract(UV + [0, R[1]]) + Refract(UV - [0, R[1]]))
    mL = luma(m)
    c2 = col.copy()
    c2 = c2 + (m * 0.08 - c2) * (tir * 0.9)[..., None]
    c2 = c2 * (1.0 - 0.55 * fleck * cov)[..., None]
    face = saturate((lenC - 0.12) * 4.0)
    c2 = c2 * (1.0 - 0.3 * face)[..., None]
    fz = saturate(frost * (0.6 + 0.4 * g + 0.15 * hi) + fog)
    fzm = fz > 0.01
    if fzm.any():
        rad = P["FrostPx"] * s1080 * fz
        rot = 6.2831853 * np.mod(52.9829189 * np.mod(px[..., 0] * 0.06711056 + px[..., 1] * 0.00583715, 1.0), 1.0)
        nt = 4 if a < 0.45 else (6 if a < 0.7 else 8)
        b = np.zeros_like(col)
        for i in range(nt):
            fi = i + 0.5
            an = fi * 2.3999632 + rot
            rr_ = math.sqrt(fi / nt) * rad
            b += Refract(UV + duv + np.stack([np.cos(an) * rr_ / Ws, np.sin(an) * rr_ / Hs], -1))
        b /= nt
        cf = c2 + (b - c2) * saturate(0.9 * fz)[..., None]
        cf = cf + m * (fz * P["FrostLift"] * (1.0 + crush))[..., None]
        c2 = np.where(fzm[..., None], cf, c2)
    mk = saturate(0.35 * mist * (0.6 + 0.4 * g))[..., None]
    c2 = c2 + (np.maximum(c2, 1.1 * m) - c2) * mk
    nxy = nC + wob + dirq * (sa * cov)[..., None]
    n3 = np.dstack([nxy[..., 0], -nxy[..., 1], np.sqrt(saturate(1.0 - (nxy ** 2).sum(-1)))])
    tilt = saturate((np.hypot(nxy[..., 0], nxy[..., 1]) - 0.05) * 10.0)
    L = np.asarray(sun_dir_v, np.float64)
    L = L / np.linalg.norm(L)
    SunLum = np.asarray(sun_lum, np.float64)
    sunL = float(SunLum @ [0.2126, 0.7152, 0.0722])
    sunC = np.minimum(SunLum / max(sunL, 1e-4), 3.0)
    sunK = min(sunL / max(P["SunRef"], 0.01), 1.0) * float(np.clip(2 * L[2] + 0.35, 0, 1)) * (1 - 0.55 * st)
    headK = float(np.clip(P["Headlight"], 0, 1)) * (0.06 + 0.3 * st)
    Lf = (0.1414, 0.8485, 0.5092)
    Lh = (0.0, -0.2425, 0.9701)
    pw = 90.0 + 150.0 * saturate(2.0 * lenC)
    h = L + [0, 0, 1.0]
    h = h / np.linalg.norm(h)
    lobe_sun = saturate(n3 @ h) ** pw
    gl = (2.2 * sunK * lobe_sun)[..., None] * sunC + (1.6 * flash * lobe(n3, Lf, 24.0))[..., None] * np.array(
        [0.88, 0.94, 1.0]) + (headK * lobe(n3, Lh, 60.0))[..., None] * np.array([1.0, 0.86, 0.62])
    c2 = c2 + gl * (tilt * P["GlintK"] * np.maximum(mL, 0.02) * (0.7 + 0.3 * g + 0.2 * hi))[..., None]
    col = np.where(fm[..., None], c2, col)
    if dbg is not None:
        dbg.update(locals())
    return np.maximum(col, 0.0)


# --------------------------------------------------------------------------- previews
FRAMES = {
    "haze": "Saved/Screenshots/SetDressV2/S07_WaitingWater/carrier_b.png",
    "dark": "Saved/Screenshots/Look2/B1_road_200.png",
    "bright": "Saved/Screenshots/SetDress/L02_ApricotTerraces/carrier.png",
}
LIGHTS = {
    "sunA": dict(sun_dir_v=(-0.45, 0.25, 0.86), flash=0.0, storm=0.3),
    "sunB": dict(sun_dir_v=(0.62, 0.08, 0.78), flash=0.0, storm=0.3),
    "flash": dict(sun_dir_v=(0.0, 0.3, -0.95), flash=1.0, storm=0.9),
}


def srgb_to_lin(x):
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def lin_to_srgb(x):
    x = np.clip(x, 0, 1)
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * x ** (1 / 2.4) - 0.055)


def load_frame(path, W=1920, H=1080):
    im = Image.open(path).convert("RGB")
    if im.size != (W, H):
        im = im.resize((W, H), Image.BICUBIC)
    return srgb_to_lin(np.asarray(im, np.float64) / 255.0)


def synthetic_frame(W=1920, H=1080):
    ys, xs = np.mgrid[0:H, 0:W]
    u, v = xs / W, ys / H
    sky = np.dstack([0.55 - 0.25 * v, 0.5 - 0.25 * v, 0.42 - 0.2 * v])
    ground = np.dstack([0.12 + 0.05 * u, np.full_like(u, 0.09), np.full_like(u, 0.06)])
    img = np.where((v < 0.5)[..., None], sky, ground)
    chk = ((xs // 48 + ys // 48) % 2 == 0) * 0.08
    return img + chk[..., None] * (v >= 0.5)[..., None]


def to_image(lin, bloom=True):
    if bloom:
        ex = np.maximum(lin - 1.0, 0.0)
        if ex.max() > 0:
            lin = lin + ndimage.gaussian_filter(ex, sigma=(6, 6, 0)) * 0.6
    return Image.fromarray((lin_to_srgb(lin) * 255 + 0.5).astype(np.uint8))


def label(im, text):
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, 8 + 7 * len(text), 18), fill=(0, 0, 0))
    d.text((4, 3), text, fill=(235, 235, 235))
    return im


def preview(out=OUT, T=20.0):
    pv = out / "previews"
    pv.mkdir(parents=True, exist_ok=True)
    maps = load_maps(out)
    ref3 = Image.open(ROOT / "docs/look/refs/metro_glass_ref_3.jpg").convert("RGB")
    ref1 = Image.open(ROOT / "docs/look/refs/metro_glass_ref_1.jpg").convert("RGB")
    CW, CH = 960, 540
    frames = {k: load_frame(ROOT / v) for k, v in FRAMES.items()}
    frames["checker"] = synthetic_frame()
    written = []
    for fname, scene in frames.items():
        renders = {}
        for lname, lp in LIGHTS.items():
            renders[lname] = to_image(shade(scene, maps, T=T, amount=0.6, **lp))
        renders["sunA"].save(pv / f"{fname}_medium_sunA.jpg", quality=92)
        cells = [(ref3, "ref 3 (primary): Metro Last Light"), (ref1 if fname == "dark" else ref3.crop((0, 0, 1000, 562)),
                  "ref 1 (dark)" if fname == "dark" else "ref 3 corner (TL)"),
                 (to_image(scene, bloom=False), f"{fname}: no glass"),
                 (renders["sunA"], "glass Medium, sun upper left"), (renders["sunB"], "glass Medium, sun right"),
                 (renders["flash"], "glass Medium, lightning flash")]
        panel = Image.new("RGB", (CW * 3, CH * 2))
        for i, (im, txt) in enumerate(cells):
            panel.paste(label(im.resize((CW, CH), Image.LANCZOS), txt), ((i % 3) * CW, (i // 3) * CH))
        panel.save(pv / f"panel_{fname}.jpg", quality=90)
        # 1:1 crops of the top-left corner and the left edge (refraction detail)
        full = renders["sunA"]
        crop = Image.new("RGB", (1280, 540))
        crop.paste(label(full.crop((0, 0, 640, 540)), "1:1 top-left"), (0, 0))
        crop.paste(label(to_image(scene, bloom=False).crop((0, 0, 640, 540)), "1:1 top-left, no glass"), (640, 0))
        crop.save(pv / f"crop_{fname}.jpg", quality=92)
        written += [f"panel_{fname}.jpg", f"crop_{fname}.jpg", f"{fname}_medium_sunA.jpg"]
        print("preview", fname)
    # tiers on the flat haze frame
    tiers = Image.new("RGB", (CW * 2, CH * 2))
    for i, (nm, amt) in enumerate((("Off", 0.0), ("Low", 0.35), ("Medium", 0.6), ("High", 0.85))):
        im = to_image(shade(frames["haze"], maps, T=T, amount=amt, **LIGHTS["sunA"]))
        tiers.paste(label(im.resize((CW, CH), Image.LANCZOS), f"Sensor filter {nm} (Amount {amt})"), ((i % 2) * CW, (i // 2) * CH))
    tiers.save(pv / "tiers_haze.jpg", quality=90)
    written.append("tiers_haze.jpg")
    return written


def gif(out=OUT, n=48, dt=0.5, humidity=0.75):
    pv = out / "previews"
    pv.mkdir(parents=True, exist_ok=True)
    maps = load_maps(out)
    scene = load_frame(ROOT / FRAMES["haze"])
    ims = []
    for i in range(n):
        T = 30.0 + i * dt
        img = shade(scene, maps, T=T, amount=0.85, prm=dict(Humidity=humidity), **LIGHTS["sunA"])
        im = to_image(img).crop((0, 0, 560, 1080)).resize((336, 648), Image.LANCZOS)
        ims.append(label(im, f"t {T:.1f} s (x6 speed)"))
    ims[0].save(pv / "drops_left_band.gif", save_all=True, append_images=ims[1:], duration=83, loop=0, optimize=True)
    return "drops_left_band.gif"


# --------------------------------------------------------------------------- selftest
def selftest(out=OUT):
    ok = True
    inv = check_invariants(out)
    print("invariants", json.dumps(inv))
    ok &= inv["ok"]
    maps = load_maps(out)
    W, H = 480, 270
    grey = np.full((H, W, 3), 0.3)
    ys, xs = np.mgrid[0:H, 0:W]
    grad = np.dstack([0.2 + 0.6 * ys / H] * 3) + ((xs // 12 + ys // 12) % 2)[..., None] * 0.05
    ident = shade(grad, maps, amount=0.0)
    base = bilinear(grad, (xs + 0.5) / W, (ys + 0.5) / H)
    r = float(np.abs(ident - base).max())
    print("amount0_identity maxdiff", r)
    ok &= r < 1e-9
    nolight = dict(sun_lum=(0.0, 0.0, 0.0), flash=0.0, prm=dict(Headlight=0.0, RunnerRate=0.0))
    img = shade(grey, maps, amount=0.85, **nolight)
    # drops mask (any drop coverage or dispersion) from a run with DispDrops 0
    img0 = shade(grey, maps, amount=0.85, sun_lum=(0.0, 0.0, 0.0), flash=0.0, prm=dict(Headlight=0.0, RunnerRate=0.0, DispDrops=0.0))
    chroma_nodisp = float(np.abs(img0[..., 0] - img0[..., 2]).max())
    print("grey frame, no colour split, no lights: max |R-B| =", chroma_nodisp)
    ok &= chroma_nodisp < 0.004
    # A blank encoded drop sheet must not turn into a screen-wide, pulsing lens.
    blank = {name: value.copy() for name, value in maps.items()}
    blank["crack"][...] = [128 / 255, 128 / 255, 0, 0]
    blank["frost"][...] = 0
    blank["drop"][...] = [128 / 255, 128 / 255, 0, 0]
    blank_errors = []
    for t in (1.0, 20.0, 25.0):
        rendered = shade(grey, blank, T=t, amount=0.85, storm=0.0,
                         prm=dict(Humidity=0.0, Headlight=0.0, RunnerRate=0.0),
                         sun_lum=(0.0, 0.0, 0.0), flash=0.0)
        blank_errors.append(float(np.abs(rendered - grey).max()))
    print("blank drop sheet maxdiff by time", blank_errors)
    ok &= max(blank_errors) < 1e-6
    # A bright last source row used to smear into vertical colored bars above
    # the viewport edge when displaced samples were clamped to that row.
    edge_scene = np.full((H, W, 3), 0.1)
    for x in range(0, W, 24):
        edge_scene[-1, x:x + 12] = (8.0, 0.1, 0.1) if x % 48 == 0 else (0.1, 8.0, 0.1)
    edge_img = shade(edge_scene, maps, T=20.0, amount=0.85, sun_lum=(0.0, 0.0, 0.0), flash=0.0,
                     prm=dict(Headlight=0.0, RunnerRate=0.0))
    edge_bars_max = float(edge_img[H - 40:H - 20].max())
    print("bright source edge, interior band max", edge_bars_max)
    ok &= edge_bars_max < 1.0
    diffdisp = np.abs(img - img0).max(-1) > 1e-6
    print("colour split pixels (drops only):", int(diffdisp.sum()))
    # clean centre in the rendered image, apart from drops
    cq = np.abs(np.dstack([(xs + 0.5) / W, (ys + 0.5) / H]) - 0.5) * 2
    em = np.sqrt(np.sqrt(cq[..., 0] ** 4 + cq[..., 1] ** 4))
    cr = bilinear(maps["crack"], (xs + 0.5) / W, (ys + 0.5) / H)
    print("crack map in centre (edge < 0.2) max deviation", float(np.abs(cr[em < 0.2] - [128 / 255, 128 / 255, 0, 0]).max()))
    taps = {"Low": 1 + 4 + 4 + 3, "Medium": "1-3 + 4 + 6 + 3", "High": "1-3 + 4 + 8 + 3"}
    print("scene taps per pixel (base + light + frost) and texture taps (3):", taps)
    print("SELFTEST", "PASS" if ok else "FAIL")
    return ok


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", nargs="?", choices=["bake", "preview", "gif", "all"], default=None)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--seed", type=int, default=SEED)
    a = ap.parse_args(argv)
    out = Path(a.out)
    if a.cmd in ("bake", "all"):
        bake(out, a.seed)
    if a.cmd in ("preview", "all"):
        print(preview(out))
    if a.cmd in ("gif", "all"):
        print(gif(out))
    if a.selftest:
        return 0 if selftest(out) else 1
    if a.cmd is None:
        ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
