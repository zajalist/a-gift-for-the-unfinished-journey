"""Offline preview of the storm shells (task STORM-SHELLS): the numpy port of Shaders/StormShells.ush
(shells_model.py) on the SAME noise texels the engine gets (storm_dust_noise.py -> VT_Saskarta_StormDust), over
the REAL terrain seen from the carrier's eye, with the camera moving.

    python Tools/Look/storm_shells/preview_storm_shells.py            # stills, drives, contact sheet, metrics
    python Tools/Look/storm_shells/preview_storm_shells.py --quick    # stills only

Outputs, in Saved/Look/StormShells/:
    <view>_off.png / <view>_on_t0.png / <view>_on_t1.png   a still without and with the shells (t1 = t0 + 0.5 s)
    <view>_diff.png          |on - off| x 6: where the dust is
    <view>_motion.png        |t1 - t0| x 6: what moved in 0.5 s
    <view>_layers.png        each shell's alpha false-coloured (30 m red, 55 m yellow, 90 m green, 150 m blue), x 3
    drive_<name>.gif         the carrier driving 12 m/s along the road, 2 s at 12 fps, the camera MOVING
    drive_<name>_strip.png   6 frames of the drive (top) and their frame-to-frame |diff| x 6 (bottom)
    preview_sheet.png        every still off/on and the drives' middle frames
    preview_metrics.txt      the numbers quoted in docs/look/STORM_SHELLS.md

THE CAMERA: the carrier's (eye 1.2 m over the road, level, 90 deg horizontal, 16:9), at a road metre, looking
along the road (or yawed: the side-window drive). The terrain is the Gaea heightmap the landscape was built from
(Tools/Story/build_road_profile.Terrain, 1 m per pixel), rendered per screen column (exact for a level camera),
so the depth under every pixel is the real one: the ground 30 m ahead is 2.3 deg under the horizon, as in game.
Stand-in towers (40 m and 25 m tall) and columns stand beside the road so tall objects can be judged.

APPROXIMATIONS (a look check, not the engine):
- The fog is the look key's (look_keys.json, read only): the engine's height-fog integral with its colour,
  directional lobe, start distance and max opacity (shells_model.fog_transmittance, as HeightFogCommon.ush).
  The dust's colour comes from the same numbers (the material's Haze/HazeDir inputs, as the subsystem feeds it).
- Surfaces, sky and the grade are stand-ins: the ground's and the stone's radiance and the per-channel "grade"
  (scene -> display) are calibrated so the Valley haze renders as the S07 carrier capture's sky
  (Saved/Screenshots/SetDressV2/S07_WaitingWater/carrier_b.png, sRGB 159/142/96) and its ground and ruins keep
  their colours. There is no tonemapper curve, bloom, TSR or sensor CRT.
- No DustVolume froxels, sand streams or devils (volumetric fog is off in the level).
"""
from __future__ import annotations

import argparse
import math
import pathlib
import sys
import time

import numpy as np
from PIL import Image, ImageDraw

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "Tools" / "Story"))
import shells_model as sm  # noqa: E402

OUT = ROOT / "Saved" / "Look" / "StormShells"
EYE_M, HFOV_DEG = 1.2, 90.0
T0, T1 = 10.0, 10.5
DRIVE_SPEED = 12.0
LUMA = np.array([0.2126, 0.7152, 0.0722])

# display calibration (see APPROXIMATIONS): sRGB of the S07 carrier capture's sky, ground and lit ruins
REF_SKY, REF_GROUND, REF_STONE = (159, 142, 96), (92, 34, 18), (188, 140, 108)

# stills: name -> (road metre, yaw off the road heading deg). The storm and fog are blended between the look
# keys by road metre, as the lighting director does.
STILLS = {"valley": (300.0, 0.0), "ridge": (1500.0, 0.0), "basin": (2150.0, 0.0), "basin_side": (2150.0, 75.0)}
# drives: name -> (start road metre, yaw off the heading)
DRIVES = {"basin_fwd": (2140.0, 0.0), "basin_side": (2140.0, 75.0), "valley_fwd": (290.0, 0.0)}
# stand-in tall objects beside the road, in the camera's road frame at the still's road metre:
# (metres ahead, metres to the right, radius m, height m)
OBJECTS = [(90.0, -28.0, 3.5, 40.0), (55.0, 22.0, 2.0, 25.0), (140.0, 45.0, 5.0, 30.0), (38.0, -12.0, 0.6, 6.0),
           (70.0, 12.0, 0.6, 7.0), (210.0, -60.0, 8.0, 45.0)]


def srgb_to_lin(c):
    c = np.asarray(c, dtype=np.float64) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def lin_to_srgb(c):
    c = np.clip(c, 0.0, 1.0)
    s = np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055)
    return (s * 255.0 + 0.5).astype(np.uint8)


# ---------------------------------------------------------------- the world
class World:
    def __init__(self):
        from build_road_profile import HEIGHTMAP, SPLINE_POINTS_CM, Road, Terrain
        import json
        self.T = Terrain(HEIGHTMAP)
        self.R = Road(SPLINE_POINTS_CM)
        self.keys = sorted(json.loads(sm.LOOK_KEYS.read_text(encoding="utf-8")), key=lambda k: float(k["road_m"]))
        s = np.arange(0.0, self.R.length, 2.0)
        self.road_pts = self.R.xy(s) / 100.0          # m

    def ground(self, x, y):
        return self.T.height(np.asarray(x) * 100.0, np.asarray(y) * 100.0)

    def pose(self, s, yaw_off_deg=0.0):
        p = self.R.xy(s) / 100.0
        q = self.R.xy(min(s + 25.0, self.R.length)) / 100.0
        h = (q - p) / np.linalg.norm(q - p)
        a = math.radians(yaw_off_deg)
        look = np.array([h[0] * math.cos(a) - h[1] * math.sin(a), h[0] * math.sin(a) + h[1] * math.cos(a)])
        z = max(float(self.ground(p[0], p[1])), float(self.R.spline_z_m(s))) + EYE_M
        return np.array([p[0], p[1], z]), h, look

    def blend(self, s):
        """The look keys blended at road metre s (fog numbers and the storm intensity), as the director does."""
        ks = self.keys
        if s <= ks[0]["road_m"]:
            a, b, t = ks[0], ks[0], 0.0
        elif s >= ks[-1]["road_m"]:
            a, b, t = ks[-1], ks[-1], 0.0
        else:
            j = next(i for i in range(1, len(ks)) if s <= ks[i]["road_m"])
            a, b = ks[j - 1], ks[j]
            t = (s - a["road_m"]) / float(b["road_m"] - a["road_m"])
        ia, ib = sm.fog_inputs_from_key(a), sm.fog_inputs_from_key(b)
        out = {k: tuple(np.asarray(ia[k]) * (1 - t) + np.asarray(ib[k]) * t) for k in ia}
        out["storm"] = a["storm_intensity"] * (1 - t) + b["storm_intensity"] * t
        return out

    def road_distance(self, x, y, near_xy, radius=260.0):
        pts = self.road_pts[np.hypot(self.road_pts[:, 0] - near_xy[0], self.road_pts[:, 1] - near_xy[1]) < radius]
        best = np.full(np.shape(x), 1e9)
        if len(pts) < 2:
            return best
        a, b = pts[:-1], pts[1:]
        ab = b - a
        L2 = np.maximum((ab ** 2).sum(-1), 1e-9)
        X, Y = np.ravel(x), np.ravel(y)
        out = np.full(X.shape, 1e9)
        for c0 in range(0, len(X), 20000):
            px, py = X[c0:c0 + 20000, None], Y[c0:c0 + 20000, None]
            t = np.clip(((px - a[None, :, 0]) * ab[None, :, 0] + (py - a[None, :, 1]) * ab[None, :, 1]) / L2[None], 0, 1)
            dx = px - (a[None, :, 0] + t * ab[None, :, 0])
            dy = py - (a[None, :, 1] + t * ab[None, :, 1])
            out[c0:c0 + 20000] = np.sqrt(dx * dx + dy * dy).min(axis=1)
        return out.reshape(np.shape(x))


def _vnoise2(x, y, seed):
    rng = np.random.default_rng(seed)
    table = rng.uniform(-1.0, 1.0, (257, 257))
    xi, yi = np.floor(x), np.floor(y)
    fx, fy = x - xi, y - yi
    xi, yi = xi.astype(np.int64) % 256, yi.astype(np.int64) % 256
    ux, uy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
    a, b = table[xi, yi], table[xi + 1, yi]
    c, e = table[xi, yi + 1], table[xi + 1, yi + 1]
    return (a * (1 - ux) + b * ux) * (1 - uy) + (c * (1 - ux) + e * ux) * uy


def fbm2(x, y, seed, octaves=4):
    return sum(_vnoise2(x * 2 ** o, y * 2 ** o, seed + o) * 0.5 ** o for o in range(octaves)) / 1.875


class Render:
    """Scene colour (absolute linear), view Z (m), the rays and the display grade for one camera."""

    def __init__(self, world, W, H):
        self.world, self.W, self.H = world, W, H
        self.f = (W / 2) / math.tan(math.radians(HFOV_DEG / 2))
        haze_v = np.asarray(sm.PARAMS["Haze"][:3])
        self.grade = srgb_to_lin(REF_SKY) / haze_v                 # scene -> display-linear, per channel
        self.ground_rad = srgb_to_lin(REF_GROUND) / self.grade
        self.stone_rad = srgb_to_lin(REF_STONE) / self.grade

    def frame(self, cam, road_dir, look, fog, sun, t, objects=True):
        W, H, f = self.W, self.H, self.f
        wd = self.world
        fwd = np.array([look[0], look[1], 0.0])
        right = np.array([-look[1], look[0], 0.0])        # UE is left-handed: +Y is right of +X
        xs = (np.arange(W) + 0.5 - W / 2) / f
        ys = (H / 2 - (np.arange(H) + 0.5)) / f
        d = fwd[None, None] + xs[None, :, None] * right[None, None] + ys[:, None, None] * np.array([0, 0, 1.0])
        d /= np.linalg.norm(d, axis=-1, keepdims=True)
        cosphi = 1.0 / np.sqrt(1.0 + xs * xs)
        dirh = fwd[None, :2] + xs[:, None] * right[None, :2]
        dirh /= np.linalg.norm(dirh, axis=-1, keepdims=True)
        # column march over the heightmap: r_k, the terrain's screen row there, its running minimum
        r = [0.3]
        while r[-1] < 6000.0:
            r.append(r[-1] + max(0.08, 0.006 * r[-1]))
        r = np.array(r)
        gx = cam[0] + dirh[:, None, 0] * r[None]
        gy = cam[1] + dirh[:, None, 1] * r[None]
        gz = wd.ground(gx, gy)
        yrow = H / 2 - f * (gz - cam[2]) / (r[None] * cosphi[:, None])       # float screen row (down)
        ymin = np.minimum.accumulate(yrow, axis=1)
        rowc = np.arange(H) + 0.5
        rh = np.full((H, W), np.inf)
        for x in range(W):
            k = np.searchsorted(-ymin[x], -rowc, side="left")                 # first k with ymin <= row
            ok = k < len(r)
            kk = np.clip(k, 1, len(r) - 1)
            y0, y1 = ymin[x, kk - 1], ymin[x, kk]
            fr = np.clip((y0 - rowc) / np.maximum(y0 - y1, 1e-6), 0, 1)
            rr = r[kk - 1] + (r[kk] - r[kk - 1]) * fr
            rh[:, x] = np.where(ok, np.where(k == 0, r[0], rr), np.inf)
        kind = np.where(np.isfinite(rh), 1, 0)                                # 0 sky, 1 ground, 2 object
        # stand-in towers, placed in the road frame of the still (fixed in the world while driving)
        if objects:
            rgt = np.array([-road_dir[1], road_dir[0]])
            base = objects if isinstance(objects, np.ndarray) else self.objects_world
            for ox, oy, orad, oh in base:
                o = cam[:2] - np.array([ox, oy])
                b = dirh @ o
                c = o @ o - orad * orad
                disc = b * b - c
                tt = -b - np.sqrt(np.maximum(disc, 0))
                hitc = (disc > 0) & (tt > 0.5)
                bz = float(wd.ground(ox, oy)) - 1.0
                ytop = H / 2 - f * (bz + oh + 1.0 - cam[2]) / (np.maximum(tt, 1e-3) * cosphi)
                ybot = H / 2 - f * (bz - cam[2]) / (np.maximum(tt, 1e-3) * cosphi)
                inside = hitc[None] & (rowc[:, None] >= ytop[None]) & (rowc[:, None] <= ybot[None]) & (tt[None] < rh)
                rh = np.where(inside, tt[None], rh)
                kind = np.where(inside, 2, kind)
            del rgt
        hit = np.isfinite(rh)
        Z = np.where(hit, rh * cosphi[None], 1e7)                              # view Z (m) = r cos(phi)
        P = cam[None, None] + d * np.where(hit, rh / (np.hypot(d[..., 0], d[..., 1]) + 1e-12), 0.0)[..., None]
        col = np.zeros((H, W, 3))
        # ground: red-brown, world-anchored variation, lambert from the terrain normal, lighter road
        g = kind == 1
        px, py = P[..., 0][g], P[..., 1][g]
        hx = (wd.ground(px + 1.0, py) - wd.ground(px - 1.0, py)) / 2.0
        hy = (wd.ground(px, py + 1.0) - wd.ground(px, py - 1.0)) / 2.0
        nrm = np.stack([-hx, -hy, np.ones_like(hx)], -1)
        nrm /= np.linalg.norm(nrm, axis=-1, keepdims=True)
        lam = 0.55 + 0.9 * np.clip(nrm @ sun, 0, 1) / max(sun[2], 0.1) * 0.25
        tex = 1.0 + 0.35 * fbm2(px / 6.0, py / 6.0, 3) + 0.2 * fbm2(px / 0.9, py / 0.9, 9)
        near = np.hypot(px - cam[0], py - cam[1]) < 250.0
        road = np.zeros_like(px)
        if near.any():
            rd = wd.road_distance(px[near], py[near], cam[:2])
            road[near] = np.clip(1.6 - rd / 2.8, 0.0, 1.0)
        gcol = self.ground_rad[None] * (lam * tex)[:, None] * (1.0 + np.array([0.5, 1.4, 1.6])[None] * road[:, None])
        col[g] = gcol
        o = kind == 2
        col[o] = self.stone_rad[None] * (0.55 + 0.25 * fbm2(P[..., 0][o] * 2, P[..., 2][o] * 2, 17))[:, None]
        # sky: the storm deck, darker and textured above the haze, glowing toward the sun (moves slowly)
        s = kind == 0
        az = np.arctan2(d[..., 1], d[..., 0])
        el = np.clip(d[..., 2], 0.0, 1.0)
        cloud = 0.8 + 0.35 * fbm2(az * 5.0 + 0.01 * t, np.log(el + 0.03) * 4.0, 40, 5)
        deck = (np.asarray(fog["Haze"][:3]) * np.array([0.95, 0.85, 0.8]))[None, None] * (1.0 - 0.35 * np.clip(el * 3, 0, 1))[..., None]
        glow = np.clip(np.einsum("hwc,c->hw", d, sun), 0, 1) ** 6
        skyc = deck * cloud[..., None] + np.asarray(fog["HazeDir"][:3])[None, None] * glow[..., None] * 1.5
        col[s] = skyc[s]
        # the height fog (the key's), as the engine applies it to every pixel
        ray = np.where(hit, np.linalg.norm(P - cam[None, None], axis=-1), 30000.0)
        dz = np.where(hit, P[..., 2] - cam[2], 30000.0 * d[..., 2])
        Tf = sm.fog_transmittance(ray, dz, cam[2], fog["FogA"], fog["FogB"])
        lobe = np.clip(np.einsum("hwc,c->hw", d, sun), 0, 1) ** fog["Haze"][3]
        fogc = np.asarray(fog["Haze"][:3])[None, None] + np.asarray(fog["HazeDir"][:3])[None, None] * lobe[..., None]
        col = col * Tf[..., None] + fogc * (1.0 - Tf[..., None])
        return col, Z, d, fwd, kind

    def place_objects(self, cam, road_dir):
        rgt = np.array([-road_dir[1], road_dir[0]])
        self.objects_world = np.array([(cam[0] + road_dir[0] * a + rgt[0] * b, cam[1] + road_dir[1] * a + rgt[1] * b, r, h)
                                       for a, b, r, h in OBJECTS])

    def display(self, col):
        return lin_to_srgb(col * self.grade[None, None])


def sun_for(road_dir):
    """A low sun (8 deg) 40 deg right of the road ahead: side-lit, as the valley keys."""
    a = math.radians(40.0)
    h = np.array([road_dir[0] * math.cos(a) - road_dir[1] * math.sin(a), road_dir[0] * math.sin(a) + road_dir[1] * math.cos(a)])
    e = math.radians(8.0)
    v = np.array([h[0] * math.cos(e), h[1] * math.cos(e), math.sin(e)])
    return v / np.linalg.norm(v)


def shell_params(fog, sun):
    p = {k: fog[k] for k in sm.FOG_PARAMS}
    p["SunDir"] = tuple(sun)
    return p


# ---------------------------------------------------------------- output helpers
def label(im, text):
    dr = ImageDraw.Draw(im)
    dr.rectangle([0, 0, 8 + 6 * len(text), 16], fill=(0, 0, 0))
    dr.text((4, 2), text, fill=(255, 255, 255))
    return im


def horizon_row(H):
    return H // 2


def stats_rows(a, b, r0, r1):
    diff = np.abs(a.astype(float) - b.astype(float)).mean(axis=-1)[r0:r1]
    return diff.mean(), np.percentile(diff, 99)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--quick", action="store_true", help="stills only")
    ap.add_argument("--frames", type=int, default=24)
    ap.add_argument("--size", default="960x540", help="stills")
    ap.add_argument("--drive-size", default="640x360")
    a = ap.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    t_start = time.time()
    vol = sm.load_noise()
    mips = sm.mip_chain(vol)
    world = World()
    print(f"world loaded {time.time() - t_start:.0f}s")
    lines = [f"noise: {vol.shape} mips {len(mips)}", f"params: {sm.PARAMS}",
             f"camera: eye {EYE_M} m, level, {HFOV_DEG} deg; stills {a.size}, drives {a.drive_size}"]
    W, H = (int(v) for v in a.size.split("x"))
    rnd = Render(world, W, H)
    tiles = []
    hr = horizon_row(H)
    for name, (s, yaw) in STILLS.items():
        cam, road_dir, look = world.pose(s, yaw)
        fog = world.blend(s)
        sun = sun_for(road_dir)
        rnd.place_objects(cam, road_dir)
        col, Z, d, fwd, kind = rnd.frame(cam, road_dir, look, fog, sun, T0)
        prm = shell_params(fog, sun)
        on0, info = sm.shells(col, Z, d, fwd, cam, T0, fog["storm"], mips, prm, return_layers=True)
        on1 = sm.shells(col, Z, d, fwd, cam, T1, fog["storm"], mips, prm)
        off = rnd.display(col)
        s0, s1 = rnd.display(on0), rnd.display(on1)
        Image.fromarray(off).save(OUT / f"{name}_off.png")
        Image.fromarray(s0).save(OUT / f"{name}_on_t0.png")
        Image.fromarray(s1).save(OUT / f"{name}_on_t1.png")
        Image.fromarray(np.clip(np.abs(s0.astype(float) - off) * 6, 0, 255).astype(np.uint8)).save(OUT / f"{name}_diff.png")
        Image.fromarray(np.clip(np.abs(s1.astype(float) - s0) * 6, 0, 255).astype(np.uint8)).save(OUT / f"{name}_motion.png")
        fc = np.array([[1.0, 0.2, 0.1], [1.0, 0.85, 0.1], [0.2, 1.0, 0.3], [0.2, 0.5, 1.0]])
        false = sum(np.clip(l * 3.0, 0, 1)[..., None] * fc[i] for i, l in enumerate(info["alpha"]))
        Image.fromarray((np.clip(false, 0, 1) * 255).astype(np.uint8)).save(OUT / f"{name}_layers.png")
        lines.append(f"[{name}] road {s:.0f} m, yaw {yaw:+.0f}, storm {fog['storm']:.2f}, cam z {cam[2]:.1f} m, "
                     f"Haze {np.round(fog['Haze'][:3], 4)}, FogA {np.round(fog['FogA'], 5)}")
        up = stats_rows(s0, off, 0, hr)
        dn = stats_rows(s0, off, hr, H)
        lines.append(f"  on vs off, 8-bit: above the horizon mean {up[0]:.2f} p99 {up[1]:.1f}; below mean {dn[0]:.2f} p99 {dn[1]:.1f}")
        mu = stats_rows(s1, s0, 0, hr)
        md = stats_rows(s1, s0, hr, H)
        lines.append(f"  t0 vs t1 (0.5 s): above mean {mu[0]:.2f} p99 {mu[1]:.1f}; below mean {md[0]:.2f} p99 {md[1]:.1f}")
        band = slice(hr - int(0.18 * H), hr)
        lum_on = (s0.astype(float) @ LUMA)[band]
        lum_off = (off.astype(float) @ LUMA)[band]
        lines.append(f"  texture the dust adds in the 16 deg above the horizon: sd of (on - off) luma {np.std(lum_on - lum_off):.2f} /255, "
                     f"sd off {np.std(lum_off):.2f}, sd on {np.std(lum_on):.2f}")
        Tsum = np.prod([1 - al for al in info["alpha"]], axis=0)
        lines.append(f"  added opacity 1 - T: frame mean {np.mean(1 - Tsum):.3f}, 16 deg band mean {np.mean(1 - Tsum[band]):.3f}, max {np.max(1 - Tsum):.3f}")
        tops = []
        for (ox, oy, orad, oh) in rnd.objects_world:
            pass
        obj = kind == 2
        if obj.any():
            rows = np.nonzero(obj.any(axis=1))[0]
            top = obj & (np.arange(H)[:, None] < rows.min() + max(3, (rows.max() - rows.min()) // 8))
            lines.append(f"  tall objects: added opacity at their tops mean {np.mean(1 - Tsum[top]):.3f} max {np.max(1 - Tsum[top]):.3f}; "
                         f"over all their pixels mean {np.mean(1 - Tsum[obj]):.3f}")
        for i, (l, n, lod, fm) in enumerate(zip(info["alpha"], info["n"], info["lod"], info["fetched"])):
            nz = l[fm]
            lines.append(f"  shell {i}: fetched on {100 * fm.mean():.0f}% px, alpha p50 {np.percentile(nz, 50) if nz.size else 0:.3f} "
                         f"p95 {np.percentile(nz, 95) if nz.size else 0:.3f} max {l.max():.3f}; body LOD p50 "
                         f"{np.nanpercentile(lod, 50) if fm.any() else 0:.2f} p95 {np.nanpercentile(lod, 95) if fm.any() else 0:.2f}")
        tiles += [(f"{name} off", off), (f"{name} storm {fog['storm']:.2f}", s0)]
        print(f"{name} done {time.time() - t_start:.0f}s")
    if not a.quick:
        DW, DH = (int(v) for v in a.drive_size.split("x"))
        drnd = Render(world, DW, DH)
        dhr = horizon_row(DH)
        for name, (s_start, yaw) in DRIVES.items():
            frames, raws = [], []
            cam0, road_dir0, _ = world.pose(s_start + 40.0, 0.0)
            drnd.place_objects(world.pose(s_start, 0.0)[0], road_dir0)
            for j in range(a.frames):
                t = T0 + j / 12.0
                s = s_start + DRIVE_SPEED * (t - T0)
                cam, road_dir, look = world.pose(s, yaw)
                fog = world.blend(s)
                sun = sun_for(road_dir0)
                col, Z, d, fwd, kind = drnd.frame(cam, road_dir, look, fog, sun, t)
                out = sm.shells(col, Z, d, fwd, cam, t, fog["storm"], mips, shell_params(fog, sun))
                raws.append(drnd.display(out))
            frames = [Image.fromarray(r) for r in raws]
            frames[0].save(OUT / f"drive_{name}.gif", save_all=True, append_images=frames[1:], duration=83, loop=0)
            pick = [0, 4, 8, 12, 16, 20]
            pick = [p for p in pick if p < len(raws)]
            strip = Image.new("RGB", (DW * 3, DH * 4))
            for j, fi in enumerate(pick):
                strip.paste(label(Image.fromarray(raws[fi]), f"{name} t+{fi / 12:.2f}s"), ((j % 3) * DW, (j // 3) * DH))
                if fi + 1 < len(raws):
                    dd = np.clip(np.abs(raws[fi + 1].astype(float) - raws[fi]) * 6, 0, 255).astype(np.uint8)
                    strip.paste(label(Image.fromarray(dd), f"|frame {fi + 1} - {fi}| x6"), ((j % 3) * DW, (2 + j // 3) * DH))
            strip.save(OUT / f"drive_{name}_strip.png")
            fa = [stats_rows(raws[i + 1], raws[i], 0, dhr)[0] for i in range(len(raws) - 1)]
            fb = [stats_rows(raws[i + 1], raws[i], dhr, DH)[0] for i in range(len(raws) - 1)]
            lines.append(f"[drive {name}] from road {s_start:.0f} m at {DRIVE_SPEED} m/s, yaw {yaw:+.0f}: mean frame-to-frame |diff| (12 fps) "
                         f"above the horizon {np.mean(fa):.2f}, below {np.mean(fb):.2f}")
            tiles.append((f"drive {name} (moving {DRIVE_SPEED:.0f} m/s)", raws[len(raws) // 2]))
            print(f"drive {name} done {time.time() - t_start:.0f}s")
    tw, th = 800, 450
    cols = 2
    sheet = Image.new("RGB", (tw * cols, th * ((len(tiles) + cols - 1) // cols)))
    for i, (txt, arr) in enumerate(tiles):
        sheet.paste(label(Image.fromarray(arr).resize((tw, th), Image.BILINEAR), txt), ((i % cols) * tw, (i // cols) * th))
    sheet.save(OUT / "preview_sheet.png")
    (OUT / "preview_metrics.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"wrote {OUT} in {time.time() - t_start:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
