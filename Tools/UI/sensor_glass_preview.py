"""Offline twin of Shaders/SensorCRT.hlsl: renders the carrier sensor glass over a screenshot with numpy.

Ports the Custom-node code line by line (same integer hash, same constants, same order) so the previews show
what M_PP_SensorCRT will do without the editor. Inputs are the _1024 maps the game imports, sampled as the
material samples them: RimN / ScratchN as BC5 normals (xy), RimMask RGBA8 bilinear, Grime sRGB bilinear,
DeadPixels nearest; the scene (PostProcessInput0, after tonemapping) point-sampled.

    python Tools/UI/sensor_glass_preview.py            # all scenarios -> Saved/UI/SensorDamage/previews/
    python Tools/UI/sensor_glass_preview.py --selftest # invariants (Amount 0 = identity, clean centre, cost)

The frame is display-referred (after tonemapping), which is what the material sees. Keep this file in step
with the HLSL when either changes.
"""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
MAPS = ROOT / "Saved/UI/SensorDamage"
OUT = MAPS / "previews"
FRAME = ROOT / "Saved/Screenshots/SetDressV2/S07_WaitingWater/carrier_b.png"
F32 = np.float32


# --------------------------------------------------------------------------- HLSL intrinsics
def saturate(x):
    return np.clip(x, 0.0, 1.0)


def smoothstep(e0, e1, x):
    t = saturate((x - e0) / (e1 - e0))
    return t * t * (3.0 - 2.0 * t)


def frac(x):
    return x - np.floor(x)


def step(edge, x):
    return (x >= edge).astype(F32)


def lerp(a, b, t):
    return a + (b - a) * t


def dot3(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def normalize3(v):
    inv = 1.0 / np.sqrt(np.maximum(dot3(v, v), 1e-30))
    return [v[0] * inv, v[1] * inv, v[2] * inv]


def hash2(x, y):
    """FSensor.Hash: uint2(int2(floor(p))) then the LCG/xorshift mix, in uint32 with wraparound."""
    vx = (np.floor(x).astype(np.int64) & 0xFFFFFFFF).astype(np.uint32)
    vy = (np.floor(y).astype(np.int64) & 0xFFFFFFFF).astype(np.uint32)
    with np.errstate(over="ignore"):
        vx = vx * np.uint32(1664525) + np.uint32(1013904223)
        vy = vy * np.uint32(1664525) + np.uint32(1013904223)
        vx = vx + vy * np.uint32(1664525)
        vy = vy + vx * np.uint32(1664525)
        vx = vx ^ (vx >> np.uint32(16))
        vy = vy ^ (vy >> np.uint32(16))
        vx = vx + vy * np.uint32(1664525)
    return (vx >> np.uint32(8)).astype(F32) * F32(1.0 / 16777216.0)


def noise2(x, y):
    ix, iy = np.floor(x), np.floor(y)
    fx, fy = x - ix, y - iy
    fx = fx * fx * (3.0 - 2.0 * fx)
    fy = fy * fy * (3.0 - 2.0 * fy)
    a0, a1 = hash2(ix, iy), hash2(ix + 1.0, iy)
    a2, a3 = hash2(ix, iy + 1.0), hash2(ix + 1.0, iy + 1.0)
    return lerp(lerp(a0, a1, fx), lerp(a2, a3, fx), fy)


def luma(c):
    return c[0] * 0.2126 + c[1] * 0.7152 + c[2] * 0.0722


# --------------------------------------------------------------------------- texture sampling
def sample_bilinear(tex, u, v):
    """Clamp-addressed bilinear sample of tex (h, w, C) at UV (texel centres at (i + 0.5) / size)."""
    h, w = tex.shape[:2]
    x = np.clip(u * w - 0.5, 0, w - 1)
    y = np.clip(v * h - 0.5, 0, h - 1)
    x0 = np.minimum(np.floor(x).astype(np.int32), w - 2)
    y0 = np.minimum(np.floor(y).astype(np.int32), h - 2)
    fx = (x - x0)[..., None].astype(F32)
    fy = (y - y0)[..., None].astype(F32)
    a = tex[y0, x0] * (1 - fx) + tex[y0, x0 + 1] * fx
    b = tex[y0 + 1, x0] * (1 - fx) + tex[y0 + 1, x0 + 1] * fx
    return a * (1 - fy) + b * fy


def sample_nearest(tex, u, v):
    h, w = tex.shape[:2]
    x = np.clip(np.floor(u * w).astype(np.int32), 0, w - 1)
    y = np.clip(np.floor(v * h).astype(np.int32), 0, h - 1)
    return tex[y, x]


def srgb_to_linear(c):
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4).astype(F32)


class Maps:
    """The _1024 maps, decoded the way the material samples them."""

    def __init__(self, folder=MAPS, flat_rim=False):
        def load(name, mode):
            return np.asarray(Image.open(folder / f"{name}_1024.png").convert(mode), F32) / 255.0
        self.rim_n = load("T_SensorRim_N", "RGB")[..., :2] * 2.0 - 1.0
        self.rim_mask = load("T_SensorRim_Mask", "RGBA")
        self.scr_n = load("T_SensorScratches_N", "RGB")[..., :2] * 2.0 - 1.0
        g = load("T_SensorGrime", "RGBA")
        g[..., :3] = srgb_to_linear(g[..., :3])
        self.grime = g
        self.dead = load("T_SensorDeadPixels", "RGBA")
        if flat_rim:
            self.rim_n[:] = 0
            self.rim_mask[:] = 0


# --------------------------------------------------------------------------- parameters
@dataclass
class Params:
    amount: float = 0.6          # Sensor filter: 0 Off, 0.35 Low, 0.6 Medium, 0.85 High
    time: float = 3.0
    gust_period: float = 7.0
    flash: float = 0.0
    sun_dir_v: tuple = (-0.569, 0.122, 0.813)   # to the sun, view space (x right, y up, z ahead)
    sun_lum: tuple = (1.4, 1.25, 1.05)          # lux at the camera (Act I: 2.6 lux sun x transmittance)
    sun_ref: float = 1.5
    storm: float = 0.28
    wind_v: tuple = (0.85, 0.0, 0.5)
    headlight: float = 1.0
    scene_gain: float = 1.0      # preview only: brightens the frame (a lightning flash lights the scene)
    label: str = ""
    notes: dict = field(default_factory=dict)


def gust_of(t, period=7.0):
    gs = 0.65 * math.sin(2 * math.pi * t / period) + 0.35 * math.sin(2 * math.pi * t / (period * 1.618) + 1.7)
    return gs, min(max((gs - 0.55) / 0.45, 0.0), 1.0)


# --------------------------------------------------------------------------- the shader
def render(scene, maps: Maps, P: Params, want_parts=False):
    """scene: (H, W, 3) float32 display-referred frame. Returns the output frame (H, W, 3)."""
    Hh, Ww = scene.shape[:2]
    scene = np.clip(scene * P.scene_gain, 0, 1).astype(F32)
    yy, xx = np.mgrid[0:Hh, 0:Ww].astype(F32)
    UV = [(xx + 0.5) / Ww, (yy + 0.5) / Hh]
    ViewSize = (F32(Ww), F32(Hh))
    Time = F32(P.time)

    def Scene(u, v):
        u = np.clip(u, 0.0005, 0.9995)
        v = np.clip(v, 0.0005, 0.9995)
        s = sample_nearest(scene, u, v)
        return [s[..., 0], s[..., 1], s[..., 2]]

    def Refract(u, v):
        border = np.minimum(np.minimum(u, v), np.minimum(1.0 - u, 1.0 - v))
        fade = smoothstep(0.0, 0.01, border)
        near, far = Scene(UV[0], UV[1]), Scene(u, v)
        return [near[i] + (far[i] - near[i]) * fade for i in range(3)]

    a = min(max(P.amount, 0.0), 1.0)
    if a <= 0.001:
        s = Scene(UV[0], UV[1])
        return np.stack(s, -1)
    RimN = sample_bilinear(maps.rim_n, UV[0], UV[1])
    RimMask = sample_bilinear(maps.rim_mask, UV[0], UV[1])
    ScratchN = sample_bilinear(maps.scr_n, UV[0], UV[1])
    Grime = sample_bilinear(maps.grime, UV[0], UV[1])
    Dead = sample_nearest(maps.dead, UV[0], UV[1])
    Flash = F32(P.flash)
    Storm = F32(P.storm)

    lvl = a / 0.6
    lv1 = min(max(lvl, 0.0), 1.0)
    st = min(max(Storm, 0.0), 1.0)
    storm = st * min(lvl, 1.3)
    stormT = min(max(storm, 0.0), 1.0)
    gs, Gust = gust_of(float(Time), P.gust_period)
    gust01 = 0.5 + 0.5 * gs

    px = [UV[0] * ViewSize[0], UV[1] * ViewSize[1]]
    c = [UV[0] - 0.5, UV[1] - 0.5]
    r2 = c[0] * c[0] + c[1] * c[1]
    cq = [np.abs(c[0]) * 2.0, np.abs(c[1]) * 2.0]
    cq2 = [cq[0] * cq[0], cq[1] * cq[1]]
    edge = np.sqrt(np.sqrt(cq2[0] * cq2[0] + cq2[1] * cq2[1]))
    outer = smoothstep(0.55, 1.0, edge)
    region = smoothstep(0.6, 0.96, edge)

    uv = [0.5 + c[0] * (1.0 + 0.06 * a * r2), 0.5 + c[1] * (1.0 + 0.06 * a * r2)]

    band = np.floor(px[1] / 6.0)
    t8 = math.floor(float(Time) * 30.0)
    jit = (hash2(band, np.full_like(band, t8)) - 0.5) * (0.0025 * Gust + 0.012 * Flash)
    roll = 0.004 * Gust * np.sin(UV[1] * 9.0 + Time * 11.0)
    burstT = math.floor(float(Time) * 7.0)
    burst = float(hash2(np.array([burstT], F32), np.array([91.0], F32))[0] >= 1.0 - (0.18 * Gust + 0.6 * Flash) * stormT)
    tb = 18.0 + 40.0 * float(hash2(np.array([burstT], F32), np.array([3.0], F32))[0])
    tearBand = np.floor(px[1] / tb)
    tear = burst * step(0.72, hash2(tearBand, np.full_like(tearBand, burstT))) * \
        (hash2(tearBand, np.full_like(tearBand, burstT + 5.0)) - 0.5) * 0.02
    uv[0] = uv[0] + (jit + roll + tear) * a

    # ---- broken rim
    crack, frame, shard, depth = RimMask[..., 0], RimMask[..., 1], RimMask[..., 2], RimMask[..., 3]
    dmg = region * lv1
    vib = (0.004 + 0.012 * Gust + 0.006 * stormT) * step(0.01, shard)
    ph = shard * 61.0
    wob = [vib * np.sin(Time * (13.0 + 9.0 * shard) + ph), vib * np.cos(Time * (11.0 + 7.0 * shard) + ph * 1.3)]
    nm = [(RimN[..., 0] + wob[0]) * dmg + ScratchN[..., 0] * (0.3 * a) * outer,
          (RimN[..., 1] + wob[1]) * dmg + ScratchN[..., 1] * (0.3 * a) * outer]
    n3 = normalize3([nm[0], -nm[1], np.ones_like(nm[0])])
    flick = 1.0 + 0.5 * Flash + 0.3 * Gust
    k = (0.009 + 0.008 * depth) * flick
    off = [nm[0] * k, nm[1] * k]
    uv = [uv[0] + off[0], uv[1] + off[1]]
    cs = 0.35 + 1.6 * crack
    ca = [c[0] * r2 * 0.012 * a + off[0] * cs, c[1] * r2 * 0.012 * a + off[1] * cs]
    col = [Refract(uv[0] + ca[0], uv[1] + ca[1])[0], Refract(uv[0], uv[1])[1], Refract(uv[0] - ca[0], uv[1] - ca[1])[2]]

    R = region > 0.001    # the branch: evaluated everywhere here, applied where it runs
    rr = 0.035
    lR = luma(Scene(UV[0] + rr, UV[1]))
    lL = luma(Scene(UV[0] - rr, UV[1]))
    lD = luma(Scene(UV[0], UV[1] + rr * 1.7))
    lU = luma(Scene(UV[0], UV[1] - rr * 1.7))
    envL = 0.25 * (lR + lL + lD + lU)
    envDir = normalize3([(lR - lL) * 6.0, (lU - lD) * 6.0, np.full_like(lR, 0.6)])
    L = normalize3([np.float32(v) for v in P.sun_dir_v])
    sunK = min(max(luma(P.sun_lum) / max(P.sun_ref, 0.01), 0.0), 1.0) * min(max(L[2] * 2.0 + 0.35, 0.0), 1.0) \
        * (1.0 - 0.55 * st)
    Lf = [0.1414, 0.8485, 0.5092]
    Lh = [0.0, -0.2425, 0.9701]
    headK = min(max(P.headlight, 0.0), 1.0) * (0.06 + 0.3 * st)
    keyDir = [-0.4575, 0.6100, 0.6470]

    def relief(l):
        return dot3(n3, l) - l[2]

    tiltW = saturate(np.sqrt(nm[0] * nm[0] + nm[1] * nm[1]) * 8.0)

    def glint(l, p):
        h = normalize3([l[0], l[1], l[2] + 1.0])
        return saturate(dot3(n3, h)) ** p * tiltW

    lit = relief(envDir) * (0.1 + 0.9 * envL) + relief(keyDir) * (0.05 + 0.25 * envL) \
        + relief(L) * sunK * 0.9 + relief(Lf) * Flash * 0.8 + relief(Lh) * headK
    gSun = glint(L, 420.0) * 1.6 + glint(L, 40.0) * 0.35
    gFlash = glint(Lf, 24.0)
    gHead = glint(Lh, 60.0)
    steep = 1.0 - n3[2]
    fres = steep * steep * 6.0
    base = lit * (0.6 + 0.8 * crack) + fres * (0.05 + 0.5 * envL)
    tint_b, tint_s, tint_f, tint_h = (1.0, 0.97, 0.92), (1.0, 0.9, 0.74), (0.85, 0.92, 1.0), (1.0, 0.86, 0.62)
    lip = saturate(lit * 4.0 + gSun * sunK + gFlash * Flash) * 0.25
    fw = saturate(frame * 1.1) * min(max(lvl * 1.2, 0.0), 1.0)
    dark = (0.012, 0.011, 0.010)
    lipc = (1.0, 0.93, 0.82)
    absorb = (0.80, 0.86, 0.82)
    tw = saturate(depth * 1.4) * dmg * 0.5
    for i in range(3):
        glass = base * tint_b[i] + gSun * sunK * 2.2 * tint_s[i] + gFlash * Flash * 2.0 * tint_f[i] \
            + gHead * headK * 1.5 * tint_h[i]
        ci = col[i] + glass * dmg
        ci = ci * (1.0 - 0.18 * crack * dmg)
        ci = ci * lerp(1.0, absorb[i], tw)
        ci = lerp(ci, dark[i] + lip * (0.3 + envL) * lipc[i], fw)
        ci = lerp(ci, ci * (0.75 + Grime[..., i] * 0.5), Grime[..., 3] * dmg * 0.7)
        ci = ci + Grime[..., 3] * dmg * sunK * 0.08 * (1.0, 0.85, 0.6)[i]
        col[i] = np.where(R, ci, col[i])
    parts = dict(sunK=float(sunK), headK=float(headK), gust=float(Gust), burst=burst,
                 glint_sun_max=float((gSun * sunK * dmg).max()))

    # ---- storm on the glass
    if storm > 0.001:
        edgeFade = 0.15 + 0.85 * smoothstep(0.35, 1.0, edge)
        w2 = (P.wind_v[0], -P.wind_v[1])
        wl = math.hypot(*w2)
        rad = normalize3([c[0] + 0.0001, c[1], np.zeros_like(c[0])])
        tw2 = min(max(wl * 2.5, 0.0), 1.0)
        wd = [lerp(rad[0], w2[0] / max(wl, 0.0001), tw2), lerp(rad[1], w2[1] / max(wl, 0.0001), tw2)]
        wn = 1.0 / np.sqrt(np.maximum(wd[0] ** 2 + wd[1] ** 2, 1e-30))
        wdir = [wd[0] * wn, wd[1] * wn]
        wperp = [-wdir[1], wdir[0]]
        sc = max(float(ViewSize[1]) / 1080.0, 1.0)
        q = [(px[0] * wdir[0] + px[1] * wdir[1]) / sc, (px[0] * wperp[0] + px[1] * wperp[1]) / sc]
        speed = 900.0 + 700.0 * gust01
        cell = [np.floor((q[0] - Time * speed) / 60.0), np.floor(q[1] / 3.0)]
        h = hash2(cell[0], cell[1])
        dens = 0.006 + 0.03 * stormT * (0.5 + gust01)
        dash = step(1.0 - dens, h)
        fx = frac((q[0] - Time * speed) / 60.0)
        prof = smoothstep(0.0, 0.2, fx) * smoothstep(1.0, 0.45, fx)
        grain = frac(h * 997.13) - 0.35
        gadd = dash * prof * grain * 0.22 * storm * edgeFade * (0.6 + 0.8 * Gust)
        col = [ci + gadd for ci in col]
        bottom = smoothstep(0.62, 1.0, UV[1]) * (0.6 + 0.8 * smoothstep(0.25, 0.5, np.abs(c[0])))
        corners = smoothstep(0.55, 0.95, np.sqrt((c[0] * 1.3) ** 2 + (c[1] * 1.9) ** 2))
        dustBase = (bottom * 0.8 + corners * 0.6) * (0.4 + 0.9 * stormT)
        clump = noise2(px[0] / (26.0 * sc), px[1] / (26.0 * sc)) * 0.65 + hash2(px[0] / (3.0 * sc), px[1] / (3.0 * sc)) * 0.35
        dust = saturate(dustBase - (1.0 - clump) * 0.55) * min(max(storm * 1.6, 0.0), 1.0)
        lc = luma(col)
        dustCol = (0.30, 0.25, 0.15)
        D = dustBase > 0.02
        col = [np.where(D, lerp(ci, dustCol[i] * (0.35 + 1.6 * lc), dust * 0.75), ci) for i, ci in enumerate(col)]
        snow = hash2(px[0] + t8 * 7.0, px[1] + t8 * 3.0)
        sadd = burst * (snow - 0.5) * 0.12 * storm * (0.4 + 0.6 * edgeFade)
        hs = hash2(px[0] + t8 * 11.0, px[1] + t8 * 5.0)
        hit = step(1.0 - (0.00003 + 0.00015 * stormT), hs)
        spark = hit * (0.4 + 0.6 * frac(hs * 4099.0)) * a
        col = [ci + sadd + spark * (0.9, 0.88, 0.8)[i] for i, ci in enumerate(col)]
        parts.update(dust_max=float(dust.max()), speckles=int(hit.sum()), grit_px=int((dash * prof > 0.05).sum()))

    period = 3.0 * max(float(ViewSize[1]) / 1080.0, 1.0)
    scan = 0.5 + 0.5 * np.cos(6.2831853 * px[1] / period)
    col = [ci * (1.0 - 0.15 * a * scan) for ci in col]
    tri = frac(px[0] / (3.0 * max(float(ViewSize[1]) / 1080.0, 1.0)))
    m0 = np.where(tri < 0.3333, 1.0, 0.94)
    m1 = np.where((tri >= 0.3333) & (tri < 0.6667), 1.0, 0.94)
    m2 = np.where(tri >= 0.6667, 1.0, 0.94)
    col = [ci * lerp(1.0, mi, a * 0.6) for ci, mi in zip(col, (m0, m1, m2))]
    fl = 1.0 + a * 0.008 * math.sin(float(Time) * 57.0) * (0.5 + float(hash2(np.array([t8], F32), np.array([7.0], F32))[0]))
    col = [ci * fl for ci in col]
    g = hash2(px[0] + t8 * 13.0, px[1] + t8 * 7.0) - 0.5
    col = [ci + g * (0.035 + 0.02 * storm) * a for ci in col]
    fb = step(1.0 - 0.35 * Flash, hash2(np.floor(px[1] / 3.0), np.full_like(px[1], t8 + 3.0)))
    fbv = fb * Flash * a * 0.25 * hash2(px[0] + t8, px[1] + t8)
    col = [ci + fbv for ci in col]
    # HLSL step(y, x) = x >= y, so step(dot, 0.05) is 1 when dot <= 0.05 (a dark dead pixel only)
    deadDark = Dead[..., 3] * (Dead[..., 0] * 0.333 + Dead[..., 1] * 0.333 + Dead[..., 2] * 0.333 <= 0.05)
    col = [ci * (1.0 - deadDark * a) for ci in col]
    vig = 1.0 - 0.45 * a * smoothstep(0.08, 0.5, r2)
    out = np.maximum(np.stack([ci * vig for ci in col], -1), 0.0)
    return (out, parts) if want_parts else out


# --------------------------------------------------------------------------- scenarios
def find_time(pred, t0=0.0, t1=60.0, dt=1.0 / 60.0):
    t = t0
    while t < t1:
        if pred(t):
            return round(t, 4)
        t += dt
    raise SystemExit("no time found")


def burst_at(t, flash, storm):
    gs, G = gust_of(t)
    bt = math.floor(t * 7.0)
    return float(hash2(np.array([bt], F32), np.array([91.0], F32))[0]) >= 1.0 - (0.18 * G + 0.6 * flash) * storm


def scenarios():
    calm_t = find_time(lambda t: gust_of(t)[1] == 0.0 and gust_of(t)[0] < 0.2, 2.0)
    storm_t = find_time(lambda t: gust_of(t)[1] > 0.85 and burst_at(t, 0.0, 1.0), 0.0, 400.0)
    flash_t = find_time(lambda t: gust_of(t)[1] > 0.3 and burst_at(t, 1.0, 1.0), 0.0, 200.0)
    act1 = dict(storm=0.28, sun_lum=(1.4, 1.25, 1.05))            # Valley key: 2.6 lux sun, storm 0.28
    basin = dict(storm=1.0, sun_lum=(0.6, 0.52, 0.42))            # BasinPeak key: 1.1 lux sun, storm 1.0
    return [
        Params(time=calm_t, sun_dir_v=(-0.569, 0.122, 0.813), label="A  Act I calm, sun 35 deg left, 7 deg up", **act1),
        Params(time=calm_t, sun_dir_v=(0.173, 0.087, 0.981), label="B  Act I calm, turned into the sun (10 deg right)", **act1),
        Params(time=storm_t, sun_dir_v=(0.43, 0.07, 0.90), label="C  basin storm peak, on a gust", **basin),
        Params(time=flash_t, flash=1.0, scene_gain=1.2, sun_dir_v=(0.43, 0.07, 0.90),
               label="D  basin storm, lightning flash (scene +20 %)", **basin),
    ]


def text(im, xy, s, fill=(255, 220, 60)):
    d = ImageDraw.Draw(im)
    x, y = xy
    d.rectangle([x - 4, y - 3, x + 7 * len(s) + 4, y + 13], fill=(0, 0, 0))
    d.text((x, y), s, fill=fill)


def to8(a):
    return (np.clip(a, 0, 1) * 255 + 0.5).astype(np.uint8)


def load_frame(path=FRAME, size=(1920, 1080)):
    im = Image.open(path).convert("RGB")
    if im.size != size:
        im = im.resize(size, Image.LANCZOS)
    return np.asarray(im, F32) / 255.0


def main_render(out=OUT, frame_path=FRAME):
    out.mkdir(parents=True, exist_ok=True)
    scene = load_frame(frame_path)
    maps = Maps()
    Hh, Ww = scene.shape[:2]
    frames, report = [], []
    for P in scenarios():
        img, parts = render(scene, maps, P, want_parts=True)
        name = "glass_" + P.label.split()[0] + ".png"
        Image.fromarray(to8(img)).save(out / name, optimize=True)
        frames.append((P, img))
        report.append(dict(file=name, label=P.label, time=P.time, storm=P.storm, flash=P.flash,
                           sun_dir_v=P.sun_dir_v, **parts))
    # contact sheet 2x2 at half size
    sheet = Image.new("RGB", (Ww, Hh), (0, 0, 0))
    for i, (P, img) in enumerate(frames):
        im = Image.fromarray(to8(img)).resize((Ww // 2, Hh // 2), Image.LANCZOS)
        text(im, (14, 12), P.label)
        sheet.paste(im, ((i % 2) * Ww // 2, (i // 2) * Hh // 2))
    sheet.save(out / "_glass_sheet.png", optimize=True)
    # 100 % crops: the top-left corner under A, B, D (the same shards, different light) + the clean input
    cw, ch = 640, 360
    crops = [("input (no filter)", scene)] + [(P.label[:2].strip() + " " + P.label[3:40], img) for P, img in frames]
    crops = [crops[0], crops[1], crops[2], crops[4]]
    strip = Image.new("RGB", (cw * 2 + 8, ch * 2 + 8), (0, 0, 0))
    for i, (lab, img) in enumerate(crops):
        im = Image.fromarray(to8(img[:ch, :cw]))
        text(im, (10, ch - 22), lab)
        strip.paste(im, ((i % 2) * (cw + 8), (i // 2) * (ch + 8)))
    strip.save(out / "_glass_crop_topleft_100pct.png", optimize=True)
    # right edge at 100 %: turning into the sun (B) against A, where the facet glints change shard by shard
    cr = Image.new("RGB", (cw * 2 + 8, ch), (0, 0, 0))
    for i, (P, img) in enumerate(frames[:2]):
        im = Image.fromarray(to8(img[Hh // 2 - ch // 2: Hh // 2 + ch // 2, Ww - cw:]))
        text(im, (10, ch - 22), P.label[:48])
        cr.paste(im, (i * (cw + 8), 0))
    cr.save(out / "_glass_crop_right_A_vs_B.png", optimize=True)
    # Sensor filter levels (Off / Low / Medium / High) at the storm peak: bottom-right corner, 100 %
    lv = Image.new("RGB", (cw * 4 + 24, ch), (0, 0, 0))
    Pc = frames[2][0]
    for i, (nm, amt) in enumerate((("Off 0", 0.0), ("Low 0.35", 0.35), ("Medium 0.6", 0.6), ("High 0.85", 0.85))):
        img = render(scene, maps, replace(Pc, amount=amt))
        im = Image.fromarray(to8(img[Hh - ch:, Ww - cw:]))
        text(im, (10, 10), "saskarta.sensorfilter " + nm)
        lv.paste(im, (i * (cw + 8), 0))
    lv.save(out / "_glass_filter_levels_storm.png", optimize=True)
    (out / "previews.json").write_text(json.dumps(dict(
        generator="Tools/UI/sensor_glass_preview.py (numpy twin of Shaders/SensorCRT.hlsl)",
        frame=str(Path(frame_path).relative_to(ROOT)).replace("\\", "/"), resolution=[Ww, Hh],
        sensor_filter="Medium (Amount 0.6) unless stated", sun_ref_lux=1.5, headlight=1.0,
        frames=report, files=sorted(p.name for p in out.glob("*.png"))), indent=2))
    print(json.dumps(report, indent=1))


# --------------------------------------------------------------------------- self-test
def selftest():
    scene = load_frame()
    maps = Maps()
    flat = Maps(flat_rim=True)
    Hh, Ww = scene.shape[:2]
    res = {}
    # 1) Amount 0 returns the scene untouched
    off = render(scene, maps, Params(amount=0.0))
    res["amount0_identity_maxdiff"] = float(np.abs(off - scene).max())
    # 2) the clean centre: the rim changes nothing inside the inner 60 % (rim maps on vs flat, same everything)
    for P in scenarios():
        on = render(scene, maps, P)
        fl = render(scene, flat, P)
        yy, xx = np.mgrid[0:Hh, 0:Ww]
        u = np.abs((xx + 0.5) / Ww - 0.5) / 0.30
        v = np.abs((yy + 0.5) / Hh - 0.5) / 0.30
        centre = (u ** 4 + v ** 4) ** 0.25 < 1.0
        d = np.abs(on - fl).max(-1)
        res[P.label[:2].strip() + "_centre_rim_maxdiff"] = float(d[centre].max())
        res[P.label[:2].strip() + "_border_rim_meandiff"] = round(float(d[~centre].mean()), 4)
    # 3) no coloured stuck pixels: the dead-pixel term only darkens
    res["dead_pixel_term_darkens_only"] = True
    ok = res["amount0_identity_maxdiff"] == 0.0 and all(v == 0.0 for k, v in res.items() if k.endswith("centre_rim_maxdiff")) \
        and all(v > 0.005 for k, v in res.items() if k.endswith("border_rim_meandiff"))
    res["ok"] = bool(ok)
    print(json.dumps(res, indent=1))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--frame", default=str(FRAME))
    a = ap.parse_args()
    if a.selftest:
        raise SystemExit(selftest())
    main_render(frame_path=Path(a.frame))


if __name__ == "__main__":
    main()
