"""Procedural "damaged camera-sensor glass" textures for the Saskarta carrier view.

Offline only (numpy, scipy, Pillow). Everything is generated from a fixed seed;
nothing is downloaded. Writes screen-space textures (16:9) to
Saved/UI/SensorDamage/ at 2048x1152 and 1024x576 (suffix _1024):

  T_SensorCrack_N        RGB normal, DirectX convention (G = +Y down), for UE TC_Normalmap
  T_SensorCrack_Mask     L   crack lines (bright) -> highlight + chromatic split
  T_SensorCrack_Region   L   where distortion is allowed: 0 in the centre, rising to the damage
  T_SensorScratches_N    RGB normal (DirectX) of fine scratches
  T_SensorScratches_Mask L   scratch lines
  T_SensorGrime          RGBA brownish smudge (bottom-left), dust specks, water-stain ring
  T_SensorDeadPixels     RGBA: RGB = colour the pixel is stuck at, A = how much (dead = black)
  _preview.png           damage composited over a game frame with simulated refraction
  _maps.png              contact sheet of the maps
  manifest.json

Layout (LANE4 revision, user: "they shouldn't be big circle cracks"): thin, mostly straight hairline
fractures entering from the edges and corners at shallow angles, with small branch splits, all within
12 % of the frame edge; a slightly chipped bezel; fine micro-scratches. No impact point, no spider-web,
no rings. The centre of the frame is untouched in every map.

Usage: python Tools/UI/make_sensor_damage.py [--out Saved/UI/SensorDamage]
       [--frame Saved/Screenshots/MTNVIEW/spawn_summit_dust.png] [--seed 7]
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

W, H = 2048, 1152
SS = 4  # supersampling for line rasterisation
ROOT = Path(__file__).resolve().parents[2]


# --------------------------------------------------------------------------- helpers
def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def ell_radius(x, y):
    """Super-elliptical radius: 0 at centre, 1 at the frame edge, >1 in corners."""
    dx = np.abs(x / W - 0.5) * 2.0
    dy = np.abs(y / H - 0.5) * 2.0
    return (dx ** 3 + dy ** 3) ** (1.0 / 3.0)


def ell_radius_pt(px, py):
    return float(ell_radius(np.float64(px), np.float64(py)))


def fbm(rng, shape, octaves=5, base=8, persistence=0.55):
    """Value-noise fBm in [0,1]."""
    h, w = shape
    out = np.zeros(shape, np.float64)
    amp, total = 1.0, 0.0
    for o in range(octaves):
        cells = base * (2 ** o)
        g = rng.random((int(math.ceil(cells * h / w)) + 2, cells + 2))
        up = ndimage.zoom(g, (h / (g.shape[0] - 2) * 1.0, w / (g.shape[1] - 2) * 1.0), order=3)
        out += amp * up[:h, :w]
        total += amp
        amp *= persistence
    out /= total
    return (out - out.min()) / (out.max() - out.min() + 1e-9)


def height_to_normal(hgt, strength):
    """Height (image coords, y down) -> DirectX normal (G = +Y down)."""
    gy, gx = np.gradient(hgt)
    nx, ny = -gx * strength, -gy * strength
    return nx, ny


def pack_normal(nx, ny):
    nz = np.ones_like(nx)
    ln = np.sqrt(nx * nx + ny * ny + nz * nz)
    rgb = np.stack([nx / ln, ny / ln, nz / ln], -1) * 0.5 + 0.5
    return (np.clip(rgb, 0, 1) * 255 + 0.5).astype(np.uint8)


def to_l8(a):
    return (np.clip(a, 0, 1) * 255 + 0.5).astype(np.uint8)


# --------------------------------------------------------------------------- crack growth
class Cracks:
    def __init__(self, rng):
        self.rng = rng
        self.segs = []  # (x0, y0, x1, y1, width_px)

    def grow(self, x, y, ang, width, stop_r=0.46, step=(6, 13), jitter=0.22,
             branch_p=0.07, depth=0, max_steps=400, bias=None, max_len=420.0, edge_max=None):
        rng = self.rng
        travelled = 0.0
        for _ in range(max_steps):
            if edge_max is not None and min(x / W, 1 - x / W, y / H, 1 - y / H) > edge_max:
                return
            r = ell_radius_pt(x, y)
            taper = float(smoothstep(stop_r, stop_r + 0.28, r))
            taper *= 1.0 - float(smoothstep(0.55 * max_len, max_len, travelled))
            w = width * (0.25 + 0.75 * taper)
            if r < stop_r or w < 0.28 or travelled > max_len:
                return
            ang += rng.normal(0, jitter) + (rng.normal(0, 0.3) if rng.random() < 0.1 else 0.0)
            if bias is not None:  # gently pull towards a heading
                d = (bias - ang + math.pi) % (2 * math.pi) - math.pi
                ang += 0.08 * d
            L = rng.uniform(*step)
            nx, ny = x + math.cos(ang) * L, y + math.sin(ang) * L
            if not (-4 <= nx <= W + 4 and -4 <= ny <= H + 4):
                self.segs.append((x, y, nx, ny, w))
                return
            self.segs.append((x, y, nx, ny, w))
            x, y = nx, ny
            travelled += L
            width *= rng.uniform(0.975, 0.995)
            if depth < 2 and rng.random() < branch_p:
                side = rng.choice([-1, 1])
                self.grow(x, y, ang + side * rng.uniform(0.3, 0.75), width * rng.uniform(0.5, 0.75),
                          stop_r, step, jitter * 1.2, branch_p * 0.6, depth + 1, max_steps // 2, None,
                          max(60.0, (max_len - travelled) * 0.6), edge_max)

    def ring(self, cx, cy, radius, angles, width):
        """Jagged concentric segment joining consecutive radial angles (spider-web)."""
        rng = self.rng
        pts = []
        for a in angles:
            rr = radius * rng.uniform(0.85, 1.15)
            pts.append((cx + math.cos(a) * rr, cy + math.sin(a) * rr))
        for (x0, y0), (x1, y1) in zip(pts[:-1], pts[1:]):
            if rng.random() < 0.8:
                mx = (x0 + x1) / 2 + rng.normal(0, radius * 0.06)
                my = (y0 + y1) / 2 + rng.normal(0, radius * 0.06)
                self.segs.append((x0, y0, mx, my, width))
                self.segs.append((mx, my, x1, y1, width * 0.85))

    def raster(self):
        img = Image.new("L", (W * SS, H * SS), 0)
        d = ImageDraw.Draw(img)
        for x0, y0, x1, y1, w in self.segs:
            ws = max(1, int(round(w * SS)))
            fill = int(255 * min(1.0, w * SS / ws))
            d.line([(x0 * SS, y0 * SS), (x1 * SS, y1 * SS)], fill=fill, width=ws)
            if ws > 2:  # round the joints
                r = ws / 2
                d.ellipse([x1 * SS - r, y1 * SS - r, x1 * SS + r, y1 * SS + r], fill=fill)
        a = np.asarray(img, np.float32) / 255.0
        return a.reshape(H, SS, W, SS).mean(axis=(1, 3))


# --------------------------------------------------------------------------- builders
def build_cracks(rng):
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float64)
    ER = ell_radius(xx, yy)
    cr = Cracks(rng)

    # LANE4 (user 2026-09-28: "they shouldn't be big circle cracks"): no impact point, no spider-web,
    # no rings. A few thin, mostly straight hairline fractures enter from the edges and corners and run
    # along the glass at shallow angles, with occasional small branch splits, all within EDGE_MAX of
    # the frame edge.
    EDGE_MAX = 0.12
    ix, iy = 0.0, 0.0
    starts = []

    def tilt():
        return rng.uniform(0.08, 0.3)
    for _ in range(3):   # top edge (y = 0), running along it and slowly inward (+y)
        t = tilt()
        starts.append((rng.uniform(0.05, 0.95) * W, 1.0, t if rng.random() < 0.5 else math.pi - t))
    for _ in range(3):   # bottom edge, inward is -y
        t = tilt()
        starts.append((rng.uniform(0.05, 0.95) * W, H - 1.0, -t if rng.random() < 0.5 else math.pi + t))
    for _ in range(2):   # left edge, inward is +x
        t = tilt()
        starts.append((1.0, rng.uniform(0.1, 0.9) * H, 0.5 * math.pi - t if rng.random() < 0.5 else -0.5 * math.pi + t))
    for _ in range(2):   # right edge, inward is -x
        t = tilt()
        starts.append((W - 1.0, rng.uniform(0.1, 0.9) * H, 0.5 * math.pi + t if rng.random() < 0.5 else -0.5 * math.pi - t))
    for cx, cy in ((0, 0), (W, 0), (0, H), (W, H)):   # corners: short diagonal hairlines
        if rng.random() < 0.6:
            head = math.atan2(H / 2 - cy, W / 2 - cx) + rng.normal(0, 0.25)
            starts.append((min(max(cx, 1.0), W - 1.0), min(max(cy, 1.0), H - 1.0), head))
    for sx, sy, head in starts:
        # nudge the heading inward a little so the line runs along the glass at a shallow angle
        cr.grow(sx, sy, head, width=rng.uniform(0.55, 0.95), stop_r=0.0, step=(12, 22), jitter=0.02,
                branch_p=0.04, bias=head, max_len=rng.uniform(160, 420), edge_max=EDGE_MAX)

    lines = cr.raster()

    # chips: conchoidal dents along the top/left border near the TL corner + crushed impact zone
    chip_h = np.zeros((H, W))
    chip_edge = np.zeros((H, W))
    chips = []   # a slightly chipped bezel: small chips along all four edges, no big corner piece
    for _ in range(5):
        chips.append((rng.uniform(0.02, 0.98) * W, 0.0 if rng.random() < 0.5 else float(H), rng.uniform(4, 9), 0.7))
    for _ in range(3):
        chips.append((0.0 if rng.random() < 0.5 else float(W), rng.uniform(0.05, 0.95) * H, rng.uniform(4, 8), 0.7))
    for (cx, cy, r, dep) in chips:
        # irregular radius
        th = np.arctan2(yy - cy, xx - cx)
        rr = r * (1 + 0.18 * np.sin(3 * th + rng.uniform(0, 6)) + 0.1 * np.sin(7 * th + rng.uniform(0, 6)))
        t = np.hypot(xx - cx, yy - cy) / rr
        inside = t < 1
        prof = np.where(inside, -dep * np.clip(1 - t, 0, None) ** 1.4 + 0.12 * dep * np.sin(t * math.pi * 4) * (1 - t), 0)
        chip_h = np.minimum(chip_h, prof)
        chip_edge = np.maximum(chip_edge, np.exp(-((t - 1) * rr / 1.1) ** 2) * 0.9)

    # binary crack net -> shards (enclosed cells get a small random tilt)
    binary = (lines > 0.18) | (chip_edge > 0.5)
    lab, n = ndimage.label(~binary)
    areas = ndimage.sum(np.ones_like(lab), lab, index=np.arange(n + 1))
    tilt = rng.normal(0, 0.07, (n + 1, 2))
    tilt[areas > 0.2 * W * H] = 0
    tilt[0] = 0
    tx = tilt[lab, 0]
    ty = tilt[lab, 1]
    # fill the crack pixels with a neighbour's tilt, soften, and fade before the centre
    idx = ndimage.distance_transform_edt(binary, return_distances=False, return_indices=True)
    tx, ty = tx[idx[0], idx[1]], ty[idx[0], idx[1]]
    fade = smoothstep(0.48, 0.75, ER)
    tx = ndimage.gaussian_filter(tx, 1.2) * fade
    ty = ndimage.gaussian_filter(ty, 1.2) * fade

    # height: soft bevels along the cracks (two scales) + chips
    hgt = -(0.65 * ndimage.gaussian_filter(lines, 1.0) + 0.35 * ndimage.gaussian_filter(lines, 3.0)) * 6.0
    hgt += chip_h * 10.0 + ndimage.gaussian_filter(chip_h, 2.0) * 4.0
    nx, ny = height_to_normal(hgt, 1.0)
    nx = np.clip(nx + tx, -0.85, 0.85)
    ny = np.clip(ny + ty, -0.85, 0.85)

    mask = np.clip(lines * 1.15 + chip_edge * 0.7, 0, 1)
    mask = np.maximum(mask, ndimage.gaussian_filter(mask, 1.5) * 0.35)

    # region: 0 in the clear centre, rising to where the damage is
    dens = ndimage.gaussian_filter(np.maximum(lines, chip_edge), 45)
    dens /= dens.max()
    region = smoothstep(0.42, 0.78, ER) * (0.15 + 0.85 * smoothstep(0.0, 0.35, dens))
    region = np.clip(np.maximum(region, smoothstep(0.02, 0.2, dens) * smoothstep(0.42, 0.7, ER)), 0, 1)

    return nx, ny, mask, region, dict(impact=[ix / W, iy / H], segments=len(cr.segs), shards=int(n))


def build_scratches(rng):
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float64)
    img = Image.new("L", (W * SS, H * SS), 0)
    d = ImageDraw.Draw(img)
    count = 0

    def arc(x, y, ang, length, curv, inten):
        pts, L = [], 0.0
        while L < length:
            pts.append((x * SS, y * SS))
            ang += curv
            x += math.cos(ang) * 4
            y += math.sin(ang) * 4
            L += 4
        d.line(pts, fill=int(255 * inten), width=1 * SS // 2 if SS >= 2 else 1)

    # singles, rejection-sampled towards the edges
    while count < 70:
        x, y = rng.uniform(0, W), rng.uniform(0, H)
        r = ell_radius_pt(x, y)
        if r < 0.55 or rng.random() > smoothstep(0.55, 0.95, np.float64(r)) + 0.05:
            continue
        arc(x, y, rng.uniform(0, 2 * math.pi), rng.uniform(25, 220), rng.normal(0, 0.006), rng.uniform(0.25, 0.8))
        count += 1
    # a few wiper/cleaning bundles of near-parallel arcs
    for _ in range(4):
        while True:
            x, y = rng.uniform(0, W), rng.uniform(0, H)
            if ell_radius_pt(x, y) > 0.72:
                break
        a, c = rng.uniform(0, 2 * math.pi), rng.normal(0, 0.004)
        for k in range(rng.integers(3, 7)):
            off = rng.uniform(-14, 14)
            arc(x - math.sin(a) * off, y + math.cos(a) * off, a + rng.normal(0, 0.02),
                rng.uniform(60, 260), c, rng.uniform(0.15, 0.5))
            count += 1
    lines = np.asarray(img, np.float32).reshape(H, SS, W, SS).mean(axis=(1, 3)) / 255.0
    lines = np.clip(lines * 2.0, 0, 1)
    # never inside the clear centre
    lines *= smoothstep(0.45, 0.6, ell_radius(xx, yy))
    hgt = -ndimage.gaussian_filter(lines, 0.8) * 3.0
    nx, ny = height_to_normal(hgt, 1.0)
    return np.clip(nx, -0.6, 0.6), np.clip(ny, -0.6, 0.6), lines, dict(scratches=count)


def build_grime(rng):
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float64)
    ER = ell_radius(xx, yy)
    rgba = np.zeros((H, W, 4))
    col = np.array([0.36, 0.27, 0.17])
    rgba[..., :3] = col

    # smudge in the bottom-left corner (fingerprint-ish, soft)
    n1 = fbm(rng, (H, W), octaves=6, base=6)
    n2 = fbm(rng, (H, W), octaves=4, base=24)
    cx, cy = 0.0, H * 1.0
    d = np.hypot((xx - cx) / (0.36 * W), (yy - cy) / (0.55 * H))
    smudge = (1 - smoothstep(0.25, 1.0, d + (n1 - 0.5) * 0.5)) * (0.55 + 0.45 * n2)
    alpha = smudge * 0.32

    # dust specks: mostly near the edges
    specks = 0
    while specks < 55:
        x, y = rng.uniform(0, W), rng.uniform(0, H)
        r = ell_radius_pt(x, y)
        if r < 0.5 or rng.random() > smoothstep(0.5, 1.0, np.float64(r)) + 0.1:
            continue
        rad = rng.uniform(0.8, 3.5) if rng.random() < 0.85 else rng.uniform(4, 9)
        x0, x1 = int(max(0, x - rad * 3)), int(min(W, x + rad * 3 + 1))
        y0, y1 = int(max(0, y - rad * 3)), int(min(H, y + rad * 3 + 1))
        dd = np.hypot(xx[y0:y1, x0:x1] - x, yy[y0:y1, x0:x1] - y) / rad
        a = np.exp(-dd ** 2 * 1.6) * rng.uniform(0.25, 0.6)
        alpha[y0:y1, x0:x1] = 1 - (1 - alpha[y0:y1, x0:x1]) * (1 - a)
        specks += 1

    # faint water-stain ring upper-right (dried edge darker than the inside)
    sx, sy, sr = 0.83 * W, 0.2 * H, 85.0
    th = np.arctan2(yy - sy, xx - sx)
    rr = sr * (1 + 0.07 * np.sin(2 * th + 1.3) + 0.04 * np.sin(5 * th + 0.4)) + (n2 - 0.5) * 10
    dist = np.hypot(xx - sx, yy - sy)
    ring = np.exp(-((dist - rr) / 2.2) ** 2) * 0.16 + (dist < rr) * 0.035 * smoothstep(0.0, 1.0, dist / rr)
    ring *= 0.6 + 0.4 * n1
    alpha = 1 - (1 - alpha) * (1 - ring)

    alpha *= smoothstep(0.35, 0.6, ER)  # keep the centre clean
    rgba[..., 3] = np.clip(alpha, 0, 1)
    # a touch of colour variation (darker in the dense parts)
    rgba[..., :3] = col[None, None, :] * (0.85 + 0.3 * n2[..., None])
    return rgba, dict(dust_specks=specks, stain_centre=[sx / W, sy / H], stain_radius_px=sr)


def build_dead_pixels(rng):
    rgba = np.zeros((H, W, 4))
    notes = []

    def put(x, y, colour, a):
        rgba[y, x, :3] = colour
        rgba[y, x, 3] = a

    # a stuck column near the right edge (faint green), a dead row near the bottom,
    # and a partial dead column near the top-left
    xcol = W - 7
    rgba[:, xcol, :3] = (0.2, 1.0, 0.35)
    rgba[:, xcol, 3] = 0.35
    notes.append(dict(kind="stuck_column", x=xcol, colour="green", alpha=0.35))
    yrow = H - 11
    rgba[yrow, :, :3] = 0.0
    rgba[yrow, :, 3] = 0.7
    notes.append(dict(kind="dead_row", y=yrow, alpha=0.7))
    xc2 = 5
    rgba[: int(H * 0.38), xc2, :3] = 0.0
    rgba[: int(H * 0.38), xc2, 3] = 0.9
    notes.append(dict(kind="dead_column_partial", x=xc2, y_to=int(H * 0.38), alpha=0.9))

    # clusters at the very edges
    stuck = [(1, 0.15, 0.1), (0.25, 0.4, 1), (1, 1, 1)]
    for _ in range(9):
        side = rng.integers(0, 4)
        if side == 0:
            x, y = rng.integers(2, W - 2), rng.integers(1, 14)
        elif side == 1:
            x, y = rng.integers(2, W - 2), H - rng.integers(2, 15)
        elif side == 2:
            x, y = rng.integers(1, 14), rng.integers(2, H - 2)
        else:
            x, y = W - rng.integers(2, 15), rng.integers(2, H - 2)
        dead = rng.random() < 0.6
        c = (0, 0, 0) if dead else stuck[rng.integers(0, 3)]
        for _ in range(rng.integers(1, 6)):
            px = int(np.clip(x + rng.integers(-2, 3), 0, W - 1))
            py = int(np.clip(y + rng.integers(-2, 3), 0, H - 1))
            put(px, py, c, 1.0 if dead else 0.85)
        notes.append(dict(kind="dead_cluster" if dead else "stuck_cluster", x=int(x), y=int(y)))
    return rgba, notes


# --------------------------------------------------------------------------- rim (broken glass border)
# User 2026-09-28: "too subtle" -> a clearly visible BROKEN RIM with real normals. Still no circular
# spider-web / concentric rings and no coloured stuck pixels (both rejected earlier).
RIM_HALF = 0.30   # central clean region: superellipse with half-extents 0.30 (UV) -> inner 60 % of W and H
RIM_P = 4.0       # superellipse exponent (rounded rectangle, not a circle)
RS = W / 1024.0   # pixel scale: sizes below are written "at 1024" and multiplied by RS
DEPTH_MAX_PX = 48.0   # T_SensorRim_H / Mask.A full scale: depth below the intact glass, in px at 2048


def rim_dist(xx, yy):
    """Superellipse radius in pixel coords: 1.0 at the edge of the clean central region, ~1.67 at the
    middle of the long edges, ~2 in the corners. Everything with rim_dist <= 1 is exactly clean."""
    u = np.abs((xx + 0.5) / W - 0.5) / RIM_HALF
    v = np.abs((yy + 0.5) / H - 0.5) / RIM_HALF
    return (u ** RIM_P + v ** RIM_P) ** (1.0 / RIM_P)


def vnoise(rng, cells, order=1):
    """Value noise in [-1,1] over (H,W); order=1 is piecewise-linear (angular kinks), order=3 smooth."""
    cy = max(2, int(round(cells * H / W)))
    g = rng.uniform(-1, 1, (cy + 3, cells + 3))
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    return ndimage.map_coordinates(g, [yy / H * cy + 1, xx / W * cells + 1], order=order, mode="nearest")


def inward_normal(x, y, tau=120.0 * RS):
    """Soft 'away from the nearest border' unit vector (diagonal in the corners)."""
    wl, wr = np.exp(-x / tau), np.exp(-(W - 1 - x) / tau)
    wt, wb = np.exp(-y / tau), np.exp(-(H - 1 - y) / tau)
    nx, ny = wl - wr, wt - wb
    ln = np.hypot(nx, ny)
    small = ln < 1e-6
    # far from every border (never happens in the rim zone): fall back to the direction to the centre
    cx, cy = W / 2 - x, H / 2 - y
    cl = np.hypot(cx, cy) + 1e-9
    nx = np.where(small, cx / cl, nx / np.maximum(ln, 1e-9))
    ny = np.where(small, cy / cl, ny / np.maximum(ln, 1e-9))
    return nx, ny


def build_rim(rng):
    from scipy.spatial import cKDTree

    yy, xx = np.mgrid[0:H, 0:W].astype(np.float64)
    D = rim_dist(xx, yy)
    gate = smoothstep(1.0, 1.12, D)          # exactly 0 for D <= 1 (the clean centre)

    # ---- G: dark broken frame at the very border (6-14 px at 1024) + chips where glass is missing
    e = np.minimum(np.minimum(xx, W - 1 - xx), np.minimum(yy, H - 1 - yy))
    thick = RS * (9.5 + 2.6 * vnoise(rng, 10, 3) + 1.4 * vnoise(rng, 110, 1))   # ~6..14 px at 1024
    G = e < thick
    chips = []
    n_small = 46
    for i in range(n_small + 5):
        big = i >= n_small
        side = rng.integers(0, 4)
        t = rng.uniform(0.02, 0.98)
        if big:   # a few larger missing pieces, biased to the corners
            t = rng.choice([rng.uniform(0.0, 0.12), rng.uniform(0.88, 1.0)])
        r = RS * (rng.uniform(9, 16) if big else rng.uniform(1.5, 7.5))   # bite radius (3-15 px dia small)
        depth = RS * 9.5 + r * rng.uniform(-0.35, 0.15)                   # centred on the frame's inner edge
        if side == 0:
            cx, cy = t * W, depth
        elif side == 1:
            cx, cy = t * W, H - 1 - depth
        elif side == 2:
            cx, cy = depth, t * H
        else:
            cx, cy = W - 1 - depth, t * H
        x0, x1 = int(max(0, cx - 2 * r - 4)), int(min(W, cx + 2 * r + 5))
        y0, y1 = int(max(0, cy - 2 * r - 4)), int(min(H, cy + 2 * r + 5))
        sx, sy = xx[y0:y1, x0:x1] - cx, yy[y0:y1, x0:x1] - cy
        th = np.arctan2(sy, sx)
        rr = r * (1 + 0.16 * np.sin(3 * th + rng.uniform(0, 6)) + 0.08 * np.sin(7 * th + rng.uniform(0, 6)))
        G[y0:y1, x0:x1] |= np.hypot(sx, sy) < rr
        chips.append(dict(x=round(cx / W, 4), y=round(cy / H, 4), r_px1024=round(r / RS, 1), big=bool(big)))
    G = ndimage.binary_opening(G, iterations=1) | (e < RS * 5)

    # ---- long jagged fractures: from corners and edges, reaching at most ~20 % inward (D >= 1.05)
    img_w = Image.new("L", (W * SS, H * SS), 0)   # coverage
    img_s = Image.new("L", (W * SS, H * SS), 0)   # strength
    dw, ds = ImageDraw.Draw(img_w), ImageDraw.Draw(img_s)
    walks = dict(corner=0, edge=0, forks=0, segments=0)

    def walk(x, y, ang, width, strength, depth=0, max_len=1e9):
        head = ang
        pts = [(x, y)]
        travelled = 0.0
        while True:
            ang += rng.normal(0, 0.07) + (rng.normal(0, 0.45) if rng.random() < 0.14 else 0.0)
            ang += 0.10 * (((head - ang + math.pi) % (2 * math.pi)) - math.pi)   # keep the overall heading
            L = RS * rng.uniform(7, 16)
            nx_, ny_ = x + math.cos(ang) * L, y + math.sin(ang) * L
            if not (0 <= nx_ < W and 0 <= ny_ < H) or float(rim_dist(np.float64(nx_), np.float64(ny_))) < 1.07 \
                    or travelled > max_len:
                break
            fade = 1.0 - 0.75 * min(1.0, travelled / max(1.0, min(max_len, 420 * RS)))
            w = max(1.0, width * fade)
            dw.line([(x * SS, y * SS), (nx_ * SS, ny_ * SS)], fill=255, width=int(round(w * SS)))
            ds.line([(x * SS, y * SS), (nx_ * SS, ny_ * SS)], fill=int(255 * strength * (0.45 + 0.55 * fade)),
                    width=int(round(w * SS)) + 2)
            walks["segments"] += 1
            x, y = nx_, ny_
            travelled += L
            if depth < 2 and rng.random() < (0.045 if depth == 0 else 0.02):
                walks["forks"] += 1
                side = rng.choice([-1, 1])
                walk(x, y, ang + side * rng.uniform(0.35, 0.95), width * 0.7, strength * 0.85, depth + 1,
                     max_len=RS * rng.uniform(30, 120))

    corners = [(0, 0), (W - 1, 0), (0, H - 1), (W - 1, H - 1)]
    for ci in rng.permutation(4)[: rng.integers(3, 5)]:
        cx, cy = corners[ci]
        base = math.atan2(H / 2 - cy, W / 2 - cx)
        # one fracture per corner, starting a little along an edge (not exactly at the corner point,
        # so corners never read as a radial fan / spider-web)
        off = RS * rng.uniform(8, 45)
        if rng.random() < 0.5:
            sx0, sy0 = (cx + off if cx == 0 else cx - off), float(cy)
        else:
            sx0, sy0 = float(cx), (cy + off if cy == 0 else cy - off)
        walk(float(sx0), float(sy0), base + rng.normal(0, 0.35), RS * 1.3, 1.0)
        walks["corner"] += 1
    for _ in range(rng.integers(3, 7)):
        side = rng.integers(0, 4)
        t = rng.uniform(0.15, 0.85)
        if side == 0:
            x, y, a0 = t * W, 0.0, math.pi / 2
        elif side == 1:
            x, y, a0 = t * W, H - 1.0, -math.pi / 2
        elif side == 2:
            x, y, a0 = 0.0, t * H, 0.0
        else:
            x, y, a0 = W - 1.0, t * H, math.pi
        walk(x, y, a0 + rng.normal(0, 0.35), RS * 1.1, 0.9)
        walks["edge"] += 1
    wcov = np.asarray(img_w, np.float32).reshape(H, SS, W, SS).mean(axis=(1, 3)) / 255.0
    wstr = np.asarray(img_s, np.float32).reshape(H, SS, W, SS).max(axis=(1, 3)) / 255.0
    walk_bin = wcov > 0.3

    # ---- shard zone + anisotropic, domain-warped Voronoi (cells elongated away from the nearest border)
    dz = 1.30 + 0.09 * vnoise(rng, 7, 3)          # inner edge of the shard zone (in rim_dist units)
    zone = (D > dz) & ~G
    seeds = []
    while len(seeds) < 115:
        px, py = rng.uniform(0, W), rng.uniform(0, H)
        d = float(rim_dist(np.float64(px), np.float64(py)))
        if d > 1.22 and rng.random() < float(smoothstep(1.22, 1.85, np.float64(d))) ** 0.8:
            seeds.append((px, py))
    seeds = np.array(seeds)
    wx = RS * (4.0 * vnoise(rng, 26, 1) + 1.0 * vnoise(rng, 120, 1))
    wy = RS * (4.0 * vnoise(rng, 26, 1) + 1.0 * vnoise(rng, 120, 1))
    zy, zx = np.nonzero(D > 1.18)
    qx, qy = zx + wx[zy, zx], zy + wy[zy, zx]
    tree = cKDTree(seeds)
    K = 12
    _, cand = tree.query(np.stack([qx, qy], -1), k=K, workers=-1)
    inx, iny = inward_normal(qx, qy, tau=40.0 * RS)   # sharp split along the corner diagonal: no fan
    rot = (0.4 * vnoise(rng, 9, 3))[zy, zx]            # low-frequency wobble of the elongation axis
    inx, iny = inx * np.cos(rot) - iny * np.sin(rot), inx * np.sin(rot) + iny * np.cos(rot)
    EL = 1.8   # elongation along the inward normal
    dxs = seeds[cand, 0] - qx[:, None]
    dys = seeds[cand, 1] - qy[:, None]
    along = dxs * inx[:, None] + dys * iny[:, None]
    across = -dxs * iny[:, None] + dys * inx[:, None]
    best = cand[np.arange(len(qx)), np.argmin((along / EL) ** 2 + across ** 2, axis=1)]
    vor = np.full((H, W), -1, np.int32)
    vor[zy, zx] = best
    vb = np.zeros((H, W), bool)
    vb[:, :-1] |= vor[:, :-1] != vor[:, 1:]
    vb[:-1, :] |= vor[:-1, :] != vor[1:, :]
    vb &= (D > dz - 0.04) & ~G
    vstr = 0.7 * smoothstep(dz - 0.04, dz + 0.12, D) * (0.7 + 0.3 * smoothstep(1.4, 1.8, D))

    # ---- shard labels: zone split by every crack line
    edge_G = G ^ ndimage.binary_erosion(G) | (ndimage.binary_dilation(G) & ~G)
    lines = vb | walk_bin | edge_G
    lab, nlab = ndimage.label(zone & ~lines)
    sizes = ndimage.sum(np.ones_like(lab), lab, index=np.arange(nlab + 1))
    lab[(sizes < 30 * RS * RS)[lab]] = 0
    # crack / tiny-fragment pixels inside the zone take the nearest shard's label
    idx = ndimage.distance_transform_edt(lab == 0, return_distances=False, return_indices=True)
    lab = np.where(zone | (vb & ~G), lab[idx[0], idx[1]], 0)
    lab[G] = 0
    ids = np.unique(lab[lab > 0])
    shard_id = np.zeros(nlab + 1)
    shard_id[ids] = rng.uniform(0.05, 1.0, len(ids))
    shard_id[ids] = np.maximum(shard_id[ids], 0.05 + 1.0 / 255)   # survive 8-bit as > 0.05
    tilt = np.radians(rng.uniform(3.0, 12.0, nlab + 1))
    az = rng.uniform(0, 2 * math.pi, nlab + 1)
    tfade = smoothstep(dz, dz + 0.20, D)
    # GLASS: the tilt fades in per SHARD (by the shard's mean fade), never within a shard. A tilt that ramps
    # across a shard curves the facet, and one radius of that curve always meets the glint angle: it drew a
    # smooth lens-like ring along the inner edge of the damage in the lit previews. Flat facets only.
    tf_l = np.zeros(nlab + 1)
    if nlab:
        with np.errstate(invalid="ignore"):   # labels emptied as tiny fragments have no pixels
            tf_l[1:] = np.nan_to_num(ndimage.mean(tfade, lab, index=np.arange(1, nlab + 1)))
    sx_l, sy_l = np.tan(tilt) * np.cos(az) * tf_l, np.tan(tilt) * np.sin(az) * tf_l   # facet slope (DirectX xy)
    tx = sx_l[lab] * (lab > 0)
    ty = sy_l[lab] * (lab > 0)
    # GLASS: facet depth below the intact glass plane. normal.xy = +grad(depth) in pixel units (DirectX,
    # y down), so a plane with that slope is depth = sx*x + sy*y + c; c per shard puts its highest point
    # on the glass plane (depth 0) and the rest of the shard sinks below it.
    raw = sx_l[lab] * xx + sy_l[lab] * yy
    lo = np.zeros(nlab + 1)
    if nlab:
        lo[1:] = ndimage.minimum(raw, lab, index=np.arange(1, nlab + 1))
    facet_depth = (raw - lo[lab]) * (lab > 0)

    # ---- bevel across every crack / chip edge (ridge: normals tilt away from the centreline)
    strength = np.zeros((H, W))
    strength = np.where(vb, np.maximum(strength, vstr), strength)
    strength = np.where(edge_G, 1.0, strength)
    dist, nidx = ndimage.distance_transform_edt(~(vb | edge_G), return_indices=True)
    s_near = ndimage.gaussian_filter(strength[nidx[0], nidx[1]], 1.5)
    WB = 2.4 * RS                                   # bevel half-width: ~5 px across at 1024
    prof = 0.5 * (1 + np.cos(math.pi * np.minimum(dist / WB, 1.0)))
    hmax = math.tan(math.radians(44)) * 2 * WB / math.pi
    # long fractures: ridge from the blurred anti-aliased coverage (no EDT stair-step beading)
    wsig = 1.25 * RS
    wref = 1.3 * RS / (math.sqrt(2 * math.pi) * wsig)
    wpro = np.clip(ndimage.gaussian_filter(wcov, wsig) / wref, 0, 1)
    wpro *= np.maximum(ndimage.grey_dilation(wstr, size=5), 0.45)
    wpro = np.clip(ndimage.gaussian_filter(wpro, 0.6), 0, 1)
    ridge = np.maximum(s_near * prof, wpro)
    # GLASS: the bevel is a GROOVE, not a raised ridge: each shard's broken edge chips away and slopes down
    # into the crack (conchoidal fracture), so the normals across a crack tilt toward its centreline.
    bevel_depth = ndimage.gaussian_filter(np.maximum(s_near * prof * hmax, wpro * hmax * 1.15), 1.0)
    bx, by = height_to_normal(bevel_depth, 1.0)
    bx, by = -bx, -by                                # normal = +grad(depth) (depth = -height)
    # the frame material itself is flat beyond its bevel
    inner_G = ndimage.binary_erosion(G, iterations=int(WB) + 1)
    bx[inner_G] = 0
    by[inner_G] = 0

    nx = np.clip(tx + bx, -1.2, 1.2) * gate
    ny = np.clip(ty + by, -1.2, 1.2) * gate

    # depth map (px at 2048 below the intact glass): facet planes + bevel grooves; missing glass = full depth
    depth_px = (facet_depth + bevel_depth) * gate
    depth_px[G] = DEPTH_MAX_PX
    depth_px = np.clip(depth_px, 0.0, DEPTH_MAX_PX)
    depth_px[D <= 1.0] = 0.0

    R = np.clip(ridge, 0, 1) * gate
    Gm = G.astype(np.float64) * gate
    B = shard_id[lab] * gate
    B[B > 0] = np.maximum(B[B > 0], 0.05 + 1.0 / 255)
    B[D <= 1.0] = 0
    # GLASS: A carries the glass depth (thickness of the broken glass for the absorption tint and the
    # refraction strength). The damage region (formerly A = smoothstep(1.0, 1.6, D)) is analytic in the
    # shader: smoothstep(0.6, 0.96, superellipse(|UV - 0.5| * 2, p = 4)).
    A = depth_px / DEPTH_MAX_PX
    glass = (lab > 0) & ~G
    info = dict(shards=int(len(ids)), voronoi_seeds=len(seeds), anisotropy=EL, fractures=walks,
                chips=len(chips), big_chips=sum(c["big"] for c in chips),
                facet_tilt_deg=[3, 12], bevel_width_px1024=round(2 * WB / RS, 1), bevel_max_tilt_deg="~38 after smoothing",
                bevel="groove (normals tilt toward the crack centreline)",
                depth_max_px2048=DEPTH_MAX_PX,
                depth_p99_px2048=round(float(np.percentile(depth_px[glass], 99)), 2) if glass.any() else 0.0,
                depth_clipped_frac=round(float((facet_depth + bevel_depth)[glass].__ge__(DEPTH_MAX_PX).mean()), 5)
                if glass.any() else 0.0,
                frame_px1024=[6, 14], clean_region=dict(shape="superellipse", half_extent_uv=RIM_HALF,
                                                        exponent=RIM_P))
    return nx, ny, R, Gm, B, A, depth_px, info


def shade(nrm_rgb, bg, frame_g, crack_r, light):
    """Lit preview: Lambert + Blinn spec relative to flat glass, over bg. light = (x right, y down, z)."""
    n = nrm_rgb.astype(np.float64) / 255 * 2 - 1
    n /= np.linalg.norm(n, axis=-1, keepdims=True)
    L = np.array(light, np.float64)
    L /= np.linalg.norm(L)
    Hh = L + np.array([0, 0, 1.0])
    Hh /= np.linalg.norm(Hh)
    lam = (n @ L) - L[2]
    spec = np.clip(n @ Hh, 0, 1) ** 90 - Hh[2] ** 90
    out = bg * (1 + 1.6 * lam[..., None]) + 1.4 * np.clip(spec, 0, None)[..., None] * np.array([1, 0.98, 0.94])
    out += 0.10 * crack_r[..., None]
    out = out * (1 - frame_g[..., None]) + frame_g[..., None] * np.array([0.025, 0.025, 0.03])
    return np.clip(out, 0, 1)


def save_l16(arr01, path):
    """Save a [0,1] float array as a 16-bit greyscale PNG."""
    Image.fromarray((np.clip(arr01, 0, 1) * 65535 + 0.5).astype(np.uint16)).save(path, optimize=True)


def facet_consistency(nx, ny, depth_px, B, Gm, D):
    """normal.xy must equal +grad(depth) inside the shards (away from cracks, chips and the zone edge)."""
    gy, gx = np.gradient(depth_px)
    # interior: same shard id in a 13x13 neighbourhood, not frame, well inside the tilt fade
    same = (ndimage.grey_dilation(B, size=13) == ndimage.grey_erosion(B, size=13)) & (B > 0)
    interior = same & (ndimage.grey_dilation(Gm, size=15) == 0) & (D > 1.12) & (depth_px < DEPTH_MAX_PX - 1)
    if not interior.any():
        return dict(pixels=0, ok=False)
    err = np.hypot(gx - nx, gy - ny)[interior]
    return dict(pixels=int(interior.sum()), mean_abs_err=round(float(err.mean()), 5),
                p99_abs_err=round(float(np.percentile(err, 99)), 5), ok=bool(np.percentile(err, 99) < 0.02))


def write_rim(out, rng, frame_path):
    nx, ny, R, Gm, B, A, depth_px, info = build_rim(rng)
    nrm = pack_normal(nx, ny)
    mask = (np.stack([R, Gm, B, A], -1) * 255 + 0.5).clip(0, 255).astype(np.uint8)
    nrm1k = downsize(nrm, "normal")
    mask1k = downsize(mask, "mean")
    mask1k[..., 2] = mask[0::2, 0::2, 2]   # shard IDs must not be averaged
    Image.fromarray(nrm, "RGB").save(out / "T_SensorRim_N.png", optimize=True)
    Image.fromarray(nrm1k, "RGB").save(out / "T_SensorRim_N_1024.png", optimize=True)
    Image.fromarray(mask, "RGBA").save(out / "T_SensorRim_Mask.png", optimize=True)
    Image.fromarray(mask1k, "RGBA").save(out / "T_SensorRim_Mask_1024.png", optimize=True)
    h01 = depth_px / DEPTH_MAX_PX
    h01_1k = h01.reshape(H // 2, 2, W // 2, 2).mean(axis=(1, 3))
    save_l16(h01, out / "T_SensorRim_H.png")
    save_l16(h01_1k, out / "T_SensorRim_H_1024.png")
    yyf, xxf = np.mgrid[0:H, 0:W].astype(np.float64)
    consistency = facet_consistency(nx, ny, depth_px, B, Gm, rim_dist(xxf, yyf))

    # centre check at both resolutions (in 8-bit, as written)
    checks = {}
    for tag, n8, m8, h8 in (("2048", nrm, mask, h01), ("1024", nrm1k, mask1k, h01_1k)):
        h, w = n8.shape[:2]
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
        c = rim_dist(xx * (W / w) + (W / w - 1) / 2, yy * (H / h) + (H / h - 1) / 2) < 1.0
        checks[tag] = dict(
            centre_px=int(c.sum()),
            normal_xy_max_abs=int(np.abs(n8[..., :2][c].astype(int) - 128).max()),
            normal_z_min=int(n8[..., 2][c].min()),
            mask_rgba_max=[int(m8[..., k][c].max()) for k in range(4)],
            height_max=float(h8[c].max()),
            ok=bool((n8[..., :2][c] == 128).all() and (n8[..., 2][c] == 255).all() and (m8[..., :4][c] == 0).all()
                    and (h8[c] == 0).all()))

    # DirectX sanity: a synthetic bump through the same packer must give G > 128 on its LOWER edge
    by_, bx_ = np.mgrid[0:64, 0:64].astype(np.float64)
    bump = np.exp(-((bx_ - 32) ** 2 + (by_ - 32) ** 2) / 60.0) * 8
    bn = pack_normal(*height_to_normal(bump, 1.0))
    dx_ok = bool(bn[40, 32, 1] > 128 and bn[24, 32, 1] < 128 and bn[32, 40, 0] > 128)

    # lit preview: two light directions side by side over the game frame (or a grey gradient)
    fp = Path(frame_path)
    if fp.exists():
        bg = np.asarray(Image.open(fp).convert("RGB").resize((W, H), Image.LANCZOS), np.float64) / 255
        bg = bg * 0.85 + 0.06
    else:
        g = np.linspace(0.35, 0.6, H)[:, None, None]
        bg = np.broadcast_to(g, (H, W, 3)).copy()
    lights = [("light from top-left", (-0.55, -0.55, 0.63)), ("light from right", (0.8, 0.1, 0.59))]
    panels = []
    for label, Ld in lights:
        p = shade(nrm, bg, mask[..., 1] / 255.0, mask[..., 0] / 255.0, Ld)
        im = Image.fromarray((p * 255 + 0.5).astype(np.uint8)).resize((W // 2, H // 2), Image.LANCZOS)
        ImageDraw.Draw(im).text((W // 4 - 50, H // 4 - 6), label, fill=(255, 255, 255))
        panels.append(im)
    prev = Image.new("RGB", (W + 8, H // 2), (10, 10, 10))
    prev.paste(panels[0], (0, 0))
    prev.paste(panels[1], (W // 2 + 8, 0))
    prev.save(out / "_rim_preview.png", optimize=True)
    # full-res top-left quarter under the top-left light, to judge facets/bevels at 100 %
    full = shade(nrm, bg, mask[..., 1] / 255.0, mask[..., 0] / 255.0, lights[0][1])
    Image.fromarray((full[: H // 2, : W // 2] * 255 + 0.5).astype(np.uint8)).save(
        out / "_rim_preview_crop_topleft.png", optimize=True)

    # contact sheet (1024 versions): N | R | G / B (false colour) | A | lit
    rgbB = np.zeros(mask1k.shape[:2] + (3,), np.uint8)
    b = mask1k[..., 2] / 255.0
    hue = (b * 7.3) % 1.0
    rgbB[..., 0] = (255 * (0.5 + 0.5 * np.cos(2 * math.pi * hue)) * (b > 0)).astype(np.uint8)
    rgbB[..., 1] = (255 * (0.5 + 0.5 * np.cos(2 * math.pi * (hue - 1 / 3))) * (b > 0)).astype(np.uint8)
    rgbB[..., 2] = (255 * (0.5 + 0.5 * np.cos(2 * math.pi * (hue - 2 / 3))) * (b > 0)).astype(np.uint8)
    tiles = [Image.fromarray(nrm1k, "RGB"), Image.fromarray(mask1k[..., 0], "L").convert("RGB"),
             Image.fromarray(mask1k[..., 1], "L").convert("RGB"), Image.fromarray(rgbB, "RGB"),
             Image.fromarray(to_l8(np.clip(h01_1k * 3.0, 0, 1)), "L").convert("RGB"), panels[0]]
    names = ["T_SensorRim_N", "Mask.R crack/chip edge", "Mask.G frame+chips", "Mask.B shard ID (false colour)",
             "Mask.A / T_SensorRim_H depth (x3)", "lit (top-left light)"]
    sheet = Image.new("RGB", (W // 2 * 3, H // 2 * 2), (20, 20, 20))
    dr = ImageDraw.Draw(sheet)
    for i, (t, nm) in enumerate(zip(tiles, names)):
        ox, oy = (i % 3) * W // 2, (i // 3) * H // 2
        sheet.paste(t, (ox, oy))
        dr.text((ox + 30, oy + 30), nm, fill=(255, 220, 60))
    sheet.save(out / "_rim_maps.png", optimize=True)

    files = ["T_SensorRim_N.png", "T_SensorRim_N_1024.png", "T_SensorRim_Mask.png", "T_SensorRim_Mask_1024.png",
             "T_SensorRim_H.png", "T_SensorRim_H_1024.png"]
    textures = {
        "T_SensorRim_N": dict(compression="TC_Normalmap", srgb=False, mips="NoMipmaps", group="UI",
                              use="DirectX tangent normal (R=+x right, G=+y down, B=z); lit shard facets + "
                                  "crack/chip bevels; flat (128,128,255) in the clean centre"),
        "T_SensorRim_Mask": dict(compression="TC_VectorDisplacementmap", srgb=False, mips="NoMipmaps", group="UI",
                                 use="R = crack/chip-edge line (1 at core, falls off across bevel); "
                                     "G = dark broken frame + missing-chip occupancy; "
                                     "B = per-shard random ID (0.05..1], 0 = no shard; "
                                     "A = glass depth below the intact plane, 0..1 of %g px at 2048 (= T_SensorRim_H "
                                     "in 8 bit); the damage region is analytic in the shader" % DEPTH_MAX_PX,
                                 note="B is a per-shard ID: sample with TF_Nearest or accept bilinear blends "
                                      "at shard borders; the _1024 B channel is point-sampled, not averaged"),
    }
    textures["T_SensorRim_H"] = dict(compression="TC_Grayscale (16-bit source, optional import)", srgb=False,
                                     mips="NoMipmaps", group="UI",
                                     use="depth below the intact glass, 0..1 of %g px at 2048 (%g UV of the width); "
                                         "0 in the clean centre; missing glass (frame, chips) = 1; "
                                         "normal.xy = +d(depth_px)/d(x,y) inside the shards (DirectX)"
                                         % (DEPTH_MAX_PX, round(DEPTH_MAX_PX / W, 5)))
    rim = dict(info=info, centre_clear_check=dict(region="rim_dist < 1 (superellipse, half-extent 0.30 UV, p=4)",
                                                  results=checks),
               facet_normal_vs_depth_check=consistency,
               directx_check=dict(synthetic_bump_lower_edge_G_gt_128=dx_ok),
               preview=dict(frame=str(fp.relative_to(ROOT)).replace("\\", "/") if fp.exists() else "grey gradient",
                            files=["_rim_preview.png", "_rim_preview_crop_topleft.png", "_rim_maps.png"]),
               files=files)
    return rim, textures, files


# --------------------------------------------------------------------------- preview
def bilinear(img, u, v):
    """Sample img (H,W,C) at pixel coords u (x), v (y) with clamping."""
    h, w = img.shape[:2]
    u = np.clip(u, 0, w - 1.001)
    v = np.clip(v, 0, h - 1.001)
    x0, y0 = np.floor(u).astype(int), np.floor(v).astype(int)
    fx, fy = (u - x0)[..., None], (v - y0)[..., None]
    a = img[y0, x0] * (1 - fx) + img[y0, x0 + 1] * fx
    b = img[y0 + 1, x0] * (1 - fx) + img[y0 + 1, x0 + 1] * fx
    return a * (1 - fy) + b * fy


def composite(frame, cN, cM, region, sN, sM, grime, dead, strength=0.012, ca=0.35):
    """Reference implementation of the PP material the brief describes (UV = pixels here)."""
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float64)
    nx = (cN[..., 0] / 255.0) * 2 - 1 + ((sN[..., 0] / 255.0) * 2 - 1) * 0.5
    ny = (cN[..., 1] / 255.0) * 2 - 1 + ((sN[..., 1] / 255.0) * 2 - 1) * 0.5
    m = cM / 255.0
    reg = region / 255.0
    off = strength * W * reg  # strength is in UV; 0.012 UV = ~25 px at 2048
    ox, oy = nx * off, ny * off
    # chromatic split: R and B pushed apart along the normal, only on the cracks
    k = 1 + ca * m * 6
    r = bilinear(frame[..., :1], xx + ox * k, yy + oy * k)[..., 0]
    g = bilinear(frame[..., 1:2], xx + ox, yy + oy)[..., 0]
    b = bilinear(frame[..., 2:3], xx + ox * (2 - k), yy + oy * (2 - k))[..., 0]
    out = np.stack([r, g, b], -1)
    # crack highlight (low, cold-white) and scratch glints
    lum = out.mean(-1, keepdims=True)
    out += (m[..., None] * 0.22 + (sM / 255.0)[..., None] * 0.06) * (0.35 + lum) * np.array([0.95, 0.98, 1.0])
    # grime: multiply towards the grime colour by its alpha
    ga = grime[..., 3:4] / 255.0
    out = out * (1 - ga) + out * (grime[..., :3] / 255.0) * ga * 1.4
    # dead / stuck pixels
    da = dead[..., 3:4] / 255.0
    out = out * (1 - da) + (dead[..., :3] / 255.0) * da
    return np.clip(out, 0, 1)


def downsize(arr, mode):
    h2, w2 = H // 2, W // 2
    if mode == "normal":
        v = arr.astype(np.float64) / 255 * 2 - 1
        v = v.reshape(h2, 2, w2, 2, 3).mean(axis=(1, 3))
        v /= np.linalg.norm(v, axis=-1, keepdims=True) + 1e-9
        return (np.clip(v * 0.5 + 0.5, 0, 1) * 255 + 0.5).astype(np.uint8)
    if mode == "max":  # dead pixels: keep the strongest so single pixels survive
        a = arr.reshape(h2, 2, w2, 2, arr.shape[-1])
        alpha = a[..., 3]
        flat = alpha.transpose(0, 2, 1, 3).reshape(h2, w2, 4)
        pick = flat.argmax(-1)
        cand = a.transpose(0, 2, 1, 3, 4).reshape(h2, w2, 4, arr.shape[-1])
        return np.take_along_axis(cand, pick[..., None, None], axis=2)[:, :, 0]
    shp = (h2, 2, w2, 2) + arr.shape[2:]
    return (arr.astype(np.float64).reshape(shp).mean(axis=(1, 3)) + 0.5).astype(np.uint8)


# --------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "Saved/UI/SensorDamage"))
    ap.add_argument("--frame", default=str(ROOT / "Saved/Screenshots/MTNVIEW/spawn_summit_dust.png"))
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--rim-only", action="store_true",
                    help="only (re)build the T_SensorRim_* set and merge it into an existing manifest.json")
    ap.add_argument("--no-rim", action="store_true", help="skip the T_SensorRim_* set")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(a.seed)
    # the rim set has its own stream (derived from --seed) so the older maps stay bit-identical
    rim_rng = np.random.default_rng([a.seed, 0x51A])

    if a.rim_only:
        rim, rim_tex, rim_files = write_rim(out, rim_rng, a.frame)
        mp = out / "manifest.json"
        manifest = json.loads(mp.read_text()) if mp.exists() else dict(
            generator="Tools/UI/make_sensor_damage.py", seed=a.seed, resolution=[W, H], textures={}, files=[])
        manifest.setdefault("textures", {}).update(rim_tex)
        manifest["rim"] = dict(rim, seed=a.seed)
        manifest["files"] = [f for f in manifest.get("files", []) if not f.startswith("T_SensorRim_")] + rim_files
        mp.write_text(json.dumps(manifest, indent=2))
        print(json.dumps(dict(out=str(out), rim=rim["info"], centre=rim["centre_clear_check"],
                              directx=rim["directx_check"], facets=rim["facet_normal_vs_depth_check"]), indent=1))
        return

    cnx, cny, cmask, region, cinfo = build_cracks(rng)
    snx, sny, smask, sinfo = build_scratches(rng)
    grime, ginfo = build_grime(rng)
    dead, dinfo = build_dead_pixels(rng)

    maps = {
        "T_SensorCrack_N": (pack_normal(cnx, cny), "RGB", "normal"),
        "T_SensorCrack_Mask": (to_l8(cmask), "L", "mean"),
        "T_SensorCrack_Region": (to_l8(region), "L", "mean"),
        "T_SensorScratches_N": (pack_normal(snx, sny), "RGB", "normal"),
        "T_SensorScratches_Mask": (to_l8(smask), "L", "mean"),
        "T_SensorGrime": ((np.clip(grime, 0, 1) * 255 + 0.5).astype(np.uint8), "RGBA", "mean"),
        "T_SensorDeadPixels": ((np.clip(dead, 0, 1) * 255 + 0.5).astype(np.uint8), "RGBA", "max"),
    }
    files = []
    for name, (arr, mode, ds) in maps.items():
        Image.fromarray(arr, mode).save(out / f"{name}.png", optimize=True)
        Image.fromarray(downsize(arr, ds), mode).save(out / f"{name}_1024.png", optimize=True)
        files += [f"{name}.png", f"{name}_1024.png"]

    # sanity: the centre must be clean in every distortion/overlay map
    yy, xx = np.mgrid[0:H, 0:W]
    centre = ell_radius(xx.astype(float), yy.astype(float)) < 0.42
    centre_max = {
        "crack_normal_xy": float(np.abs(np.stack([cnx, cny])[:, centre]).max()),
        "crack_mask": float(cmask[centre].max()),
        "region": float(region[centre].max()),
        "scratch_mask": float(smask[centre].max()),
        "grime_alpha": float(grime[..., 3][centre].max()),
    }

    # preview over a real frame
    frame = np.asarray(Image.open(a.frame).convert("RGB").resize((W, H), Image.LANCZOS), np.float64) / 255
    comp = composite(frame, maps["T_SensorCrack_N"][0], maps["T_SensorCrack_Mask"][0].astype(float),
                     maps["T_SensorCrack_Region"][0].astype(float), maps["T_SensorScratches_N"][0],
                     maps["T_SensorScratches_Mask"][0].astype(float), maps["T_SensorGrime"][0].astype(float),
                     maps["T_SensorDeadPixels"][0].astype(float))
    Image.fromarray((comp * 255 + 0.5).astype(np.uint8)).save(out / "_preview.png", optimize=True)
    # a 2x crop of the top-left impact so the detail can be judged at 100%
    crop = (comp[: H // 3, : W // 3] * 255 + 0.5).astype(np.uint8)
    Image.fromarray(crop).resize((crop.shape[1] * 2, crop.shape[0] * 2), Image.NEAREST).save(
        out / "_preview_crop_topleft.png", optimize=True)

    # contact sheet of the maps (1024 versions, 3x3)
    tiles = []
    for name, (arr, mode, ds) in maps.items():
        im = Image.fromarray(downsize(arr, ds if ds != "max" else "max"), mode)
        if mode == "RGBA":
            bg = Image.new("RGBA", im.size, (128, 128, 128, 255))
            bg.alpha_composite(im)
            im = bg
        tiles.append(im.convert("RGB"))
    tiles.append(Image.fromarray((comp * 255).astype(np.uint8)).resize((W // 2, H // 2)))
    sheet = Image.new("RGB", (W // 2 * 3, H // 2 * 3), (20, 20, 20))
    for i, t in enumerate(tiles):
        sheet.paste(t, ((i % 3) * W // 2, (i // 3) * H // 2))
    sheet.save(out / "_maps.png", optimize=True)

    manifest = dict(
        generator="Tools/UI/make_sensor_damage.py",
        seed=a.seed,
        licence="Procedural, generated in-repo; no third-party source material.",
        resolution=[W, H],
        variants=["full 2048x1152", "_1024 = 1024x576"],
        normal_convention="DirectX (G = +Y down), tangent space = screen UV space; import as TC_Normalmap",
        textures={
            "T_SensorCrack_N": dict(compression="TC_Normalmap", srgb=False, mips="NoMipmaps", group="UI",
                                    use="UV offset = n.xy * Strength * Region"),
            "T_SensorCrack_Mask": dict(compression="TC_Masks", srgb=False, mips="NoMipmaps", group="UI",
                                       use="crack highlight + chromatic split weight"),
            "T_SensorCrack_Region": dict(compression="TC_Masks", srgb=False, mips="NoMipmaps", group="UI",
                                         use="where distortion is allowed (0 = centre)"),
            "T_SensorScratches_N": dict(compression="TC_Normalmap", srgb=False, mips="NoMipmaps", group="UI"),
            "T_SensorScratches_Mask": dict(compression="TC_Masks", srgb=False, mips="NoMipmaps", group="UI"),
            "T_SensorGrime": dict(compression="TC_Default", srgb=True, mips="NoMipmaps", group="UI",
                                  use="RGB grime colour (sRGB), A = coverage"),
            "T_SensorDeadPixels": dict(compression="TC_VectorDisplacementmap", srgb=False, mips="NoMipmaps",
                                       group="UI", filter="TF_Nearest",
                                       use="RGB = stuck colour, A = amount (dead = black)"),
        },
        cracks=cinfo, scratches=sinfo, grime=ginfo, dead_pixels=dinfo,
        centre_clear_check=dict(ellipse_radius=0.42, max_values=centre_max),
        preview=dict(frame=str(Path(a.frame).relative_to(ROOT)).replace("\\", "/"),
                     strength_uv=0.012, chroma=0.35, files=["_preview.png", "_preview_crop_topleft.png", "_maps.png"]),
        files=files,
    )
    if not a.no_rim:
        rim, rim_tex, rim_files = write_rim(out, rim_rng, a.frame)
        manifest["textures"].update(rim_tex)
        manifest["rim"] = dict(rim, seed=a.seed)
        manifest["files"] += rim_files
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps(dict(out=str(out), centre_max=centre_max, cracks=cinfo, scratches=sinfo), indent=1))


if __name__ == "__main__":
    main()
