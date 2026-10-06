#!/usr/bin/env python3
"""Walk the Saskarta road from the player's start (spline point 54) to its end (point 0)
and write a terrain profile for narrative and level design.

Writes docs/story/road-profile.json (machine-usable) and docs/story/road-profile.md
(readable). Offline only: numpy + Pillow over the Gaea heightmap; never touches Unreal.

    python Tools/Story/build_road_profile.py            # write both files
    python Tools/Story/build_road_profile.py --out DIR  # write somewhere else

Conventions (also written into both outputs):
- Distances are horizontal (map) metres along the road polyline, measured from point 54.
- Slope % is rise over horizontal run in the player's direction (+ = uphill).
- Compass bearings treat the top-down map as north-up: north = -Y, east = +X
  (the Unreal top viewport, +X right and +Y down). UE yaw = atan2(dY, dX) = bearing - 90.
- Heights are terrain heights from the heightmap in metres (Unreal Z / 100).
- Every line-of-sight test is terrain only (no foliage, rocks or props), eye 1.7 m.
"""

from __future__ import annotations

import argparse
import datetime
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
HEIGHTMAP = ROOT / "Saved" / "TerrainRebuild" / "Current_u16.png"
OUT_DIR = ROOT / "docs" / "story"

LAND_X0_CM, LAND_Y0_CM = -18920.4, 50.0  # world position of heightmap pixel (0, 0)
PX_CM = 100.0                            # landscape scale XY: 1 pixel = 1 m
Z_SCALE = 200.0                          # landscape scale Z: z_cm = (u16 - 32768) / 128 * 200
TILE_CM = 51000.0                        # one landscape tile (510 quads)

EYE_M = 1.7             # eye height for every line-of-sight test
STEP_M = 50.0           # sample spacing along the road
VIS_STEP_M = 10.0       # observer spacing for the summit-visibility scan
RAY_STEP_M = 2.0        # ray-march step over the heightmap
SMOOTH_M = 25           # moving average on the 1 m profile before slopes (removes 1 m noise)
SUMMIT_HINT_CM = (287480.0, 444050.0)   # quoted summit; the exact peak pixel is searched near it
SUMMIT_IN_VIEW_M = 10.0  # summit is "in view" when at most this much of its top is below the skyline
SUMMIT_MASSIF_M = 400.0  # a blocker this close to the peak is the mountain's own upper body
SIGHT_TARGET_M = 0.5     # road sight-line target height above the terrain
SIGHT_MAX_M = 3000.0     # road sight-line reach
LAST_STRETCH_M = 300.0
WALKABLE_DEG = 44.765    # UE CharacterMovement default walkable floor angle
MAST_HEIGHTS_M = (10, 20, 30, 50)

# RoadSpline points 0..54 (x, y, z cm), from Saved/TerrainRebuild/saskarta_road_thing.json.
SPLINE_POINTS_CM = np.array([
    (298079.6, 483050, 10898), (297579.6, 478550, 11773), (302079.6, 473550, 11725),
    (302079.6, 471550, 12136), (308579.6, 465550, 10478), (308079.6, 452050, 11167),
    (312579.6, 447550, 10347), (320079.6, 443050, 9787), (320079.6, 435550, 9059),
    (324079.6, 430050, 6214), (331079.6, 423050, 2297), (347079.6, 421050, -2943),
    (351079.6, 419050, -4255), (352579.6, 417050, -5205), (352079.6, 412050, -7329),
    (347579.6, 407550, -9343), (345079.6, 406550, -9334), (343579.6, 404050, -10140),
    (348079.6, 399550, -13255), (353579.6, 396550, -15962), (353579.6, 387550, -22176.25),
    (357079.6, 384050, -26635.625), (365079.6, 380550, -30212), (369579.6, 376050, -31701),
    (372079.6, 375050, -31968), (386079.6, 375050, -33759), (391579.6, 373050, -36102),
    (426579.6, 338550, -41341), (434079.6, 336550, -41455), (451079.6, 336550, -40266),
    (454579.6, 335550, -39948), (469079.6, 321550, -36634), (474579.6, 320550, -35574),
    (492079.6, 320550, -30109), (495079.6, 321550, -29648), (506579.6, 329050, -31821),
    (512579.6, 330050, -32620), (517079.6, 332550, -34218), (522579.6, 337550, -35138),
    (537579.6, 359050, -35951), (537579.6, 360550, -36034), (542079.6, 367050, -36109),
    (546079.6, 378550, -36237), (546579.6, 389550, -35854), (548079.6, 392050, -35535),
    (548579.6, 397550, -34643), (551579.6, 403550, -34359), (572079.6, 423550, -35274),
    (579579.6, 428050, -35093), (590579.6, 431050, -35429), (595579.6, 434050, -35891),
    (604579.6, 443050, -36065), (613579.6, 458550, -36030), (613579.6, 460050, -36055),
    (616579.6, 463550, -35726),
], dtype=np.float64)

COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
           "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


# ----------------------------------------------------------------------------- terrain

class Terrain:
    """Bilinear height lookup over the 16-bit Gaea heightmap, in metres."""

    def __init__(self, path: Path):
        Image.MAX_IMAGE_PIXELS = None
        raw = np.asarray(Image.open(path))
        if raw.dtype != np.uint16:
            raise SystemExit(f"{path}: expected a 16-bit heightmap, got {raw.dtype}")
        self.h = (raw.astype(np.float32) - 32768.0) / 128.0 * Z_SCALE / 100.0
        self.rows, self.cols = self.h.shape

    def inside(self, x_cm, y_cm):
        px = (np.asarray(x_cm) - LAND_X0_CM) / PX_CM
        py = (np.asarray(y_cm) - LAND_Y0_CM) / PX_CM
        return (px >= 0) & (py >= 0) & (px <= self.cols - 1) & (py <= self.rows - 1)

    def height(self, x_cm, y_cm):
        px = np.clip((np.asarray(x_cm, float) - LAND_X0_CM) / PX_CM, 0, self.cols - 1.0001)
        py = np.clip((np.asarray(y_cm, float) - LAND_Y0_CM) / PX_CM, 0, self.rows - 1.0001)
        i = np.floor(py).astype(np.intp)
        j = np.floor(px).astype(np.intp)
        fy, fx = py - i, px - j
        h = self.h
        return (h[i, j] * (1 - fx) * (1 - fy) + h[i, j + 1] * fx * (1 - fy)
                + h[i + 1, j] * (1 - fx) * fy + h[i + 1, j + 1] * fx * fy)

    def gradient(self, x_cm, y_cm):
        """Terrain steepness (rise/run, any direction) from 2 m central differences."""
        dx = (self.height(x_cm + PX_CM, y_cm) - self.height(x_cm - PX_CM, y_cm)) / 2.0
        dy = (self.height(x_cm, y_cm + PX_CM) - self.height(x_cm, y_cm - PX_CM)) / 2.0
        return np.hypot(dx, dy)

    def peak_near(self, x_cm, y_cm, radius_m=300):
        c = int(round((x_cm - LAND_X0_CM) / PX_CM))
        r = int(round((y_cm - LAND_Y0_CM) / PX_CM))
        win = self.h[r - radius_m:r + radius_m + 1, c - radius_m:c + radius_m + 1]
        wr, wc = np.unravel_index(int(np.argmax(win)), win.shape)
        rr, cc = r - radius_m + wr, c - radius_m + wc
        return LAND_X0_CM + cc * PX_CM, LAND_Y0_CM + rr * PX_CM, float(self.h[rr, cc])

    def horizon_tan(self, ox, oy, oz, tx, ty, skip_near_m=RAY_STEP_M, skip_far_m=RAY_STEP_M,
                    step_m=RAY_STEP_M):
        """Ray-march from observers (ox, oy cm; oz m) toward targets (tx, ty cm).

        Returns (tan, d): the steepest terrain elevation tangent along each ray between
        skip_near_m and (distance - skip_far_m), and the distance in metres where it occurs.
        A target at height z is visible when (z - oz) / distance > tan. Rays with no samples
        return -inf. Samples outside the map are ignored.
        """
        ox, oy, oz, tx, ty = np.broadcast_arrays(*(np.asarray(v, float) for v in (ox, oy, oz, tx, ty)))
        dist = np.hypot(tx - ox, ty - oy) / 100.0
        tan = np.full(dist.shape, -np.inf)
        at = np.zeros(dist.shape)
        n = int(math.ceil(float(dist.max()) / step_m)) if dist.size else 0
        if n == 0:
            return tan, at
        d = step_m * np.arange(1, n + 1)
        chunk = max(1, int(4_000_000 // n))
        for a in range(0, dist.size, chunk):
            sl = slice(a, a + chunk)
            D = dist[sl][:, None]
            f = d[None, :] / np.maximum(D, 1e-6)
            x = ox[sl][:, None] + (tx[sl] - ox[sl])[:, None] * f
            y = oy[sl][:, None] + (ty[sl] - oy[sl])[:, None] * f
            ok = (d[None, :] >= skip_near_m) & (d[None, :] <= D - skip_far_m) & self.inside(x, y)
            t = np.where(ok, (self.height(x, y) - oz[sl][:, None]) / d[None, :], -np.inf)
            k = np.argmax(t, axis=1)
            tan[sl] = t[np.arange(t.shape[0]), k]
            at[sl] = d[k]
        return tan, at


# ----------------------------------------------------------------------------- road

class Road:
    """The spline points walked in the player's direction, 54 -> 0, as a polyline."""

    def __init__(self, pts_cm: np.ndarray):
        self.idx = np.arange(len(pts_cm) - 1, -1, -1)            # spline index of walk vertex k
        self.P = pts_cm[::-1].copy()                             # walk order
        self.seg = np.linalg.norm(np.diff(self.P[:, :2], axis=0), axis=1) / 100.0
        self.arc = np.concatenate([[0.0], np.cumsum(self.seg)])  # m, per walk vertex
        self.length = float(self.arc[-1])
        seg3 = np.linalg.norm(np.diff(self.P, axis=0), axis=1) / 100.0
        self.arc3 = np.concatenate([[0.0], np.cumsum(seg3)])     # 3D, along the spline's own z
        self.length3 = float(self.arc3[-1])

    def locate(self, s):
        s = np.clip(np.asarray(s, float), 0, self.length)
        k = np.clip(np.searchsorted(self.arc, s, side="right") - 1, 0, len(self.P) - 2)
        return k, (s - self.arc[k]) / self.seg[k]

    def xy(self, s):
        k, t = self.locate(s)
        a, b = self.P[k, :2], self.P[k + 1, :2]
        return a + (b - a) * np.asarray(t)[..., None]

    def spline_z_m(self, s):
        k, t = self.locate(s)
        return (self.P[k, 2] + (self.P[k + 1, 2] - self.P[k, 2]) * t) / 100.0

    def ue_spline_distance(self, s):
        """Distance from point 0 along the spline, as UE measures it (3D, linear segments)."""
        k, t = self.locate(s)
        return self.length3 - (self.arc3[k] + (self.arc3[k + 1] - self.arc3[k]) * t)

    def input_key(self, s):
        """UE spline input key (point index + fraction) at walk distance s."""
        k, t = self.locate(s)
        return self.idx[k] - t

    def nearest_point(self, s):
        """Spline point index closest along the road (not straight-line) to distance s."""
        s = np.asarray(s, float)
        return self.idx[np.argmin(np.abs(self.arc - s[..., None]), axis=-1)]

    def heading(self, s):
        """Compass bearing of travel (deg, 0 = north = -Y, clockwise)."""
        k, _ = self.locate(s)
        d = self.P[k + 1, :2] - self.P[k, :2]
        return np.degrees(np.arctan2(d[..., 0], -d[..., 1])) % 360.0


# ----------------------------------------------------------------------------- helpers

def compass(b):
    return COMPASS[int(((float(b) % 360) + 11.25) // 22.5) % 16]


def ue_yaw(bearing_deg):
    return float(wrap180(bearing_deg - 90.0))


def wrap180(a):
    return (np.asarray(a, float) + 180.0) % 360.0 - 180.0


def circ_mean(deg):
    r = np.radians(np.asarray(deg, float))
    return float(np.degrees(np.arctan2(np.sin(r).mean(), np.cos(r).mean())))


def relative_words(rel):
    """Signed angle (+ = right of travel) as words a writer can use."""
    a, side = abs(float(rel)), ("right" if rel > 0 else "left")
    if a <= 20:
        return "dead ahead"
    if a <= 60:
        return f"ahead-{side}"
    if a <= 120:
        return f"to the {side}"
    if a <= 160:
        return f"behind-{side}"
    return "behind"


def tile_of(x_cm, y_cm):
    return [int((x_cm - LAND_X0_CM) // TILE_CM), int((y_cm - LAND_Y0_CM) // TILE_CM)]


def smooth(a, w):
    if w <= 1:
        return np.asarray(a, float).copy()
    pad = w // 2
    ap = np.pad(a, (pad, w - 1 - pad), mode="edge")
    return np.convolve(ap, np.ones(w) / w, mode="valid")


def runs(mask):
    """[(start, end_exclusive)] index runs where mask is True."""
    m = np.concatenate([[False], np.asarray(mask, bool), [False]])
    edges = np.flatnonzero(m[1:] != m[:-1])
    return list(zip(edges[0::2], edges[1::2]))


def prominent_extrema(h, min_prom_m, kind):
    """Local maxima (kind='max') or minima ('min') of a profile, with prominence."""
    v = h if kind == "max" else -h
    n, out = len(v), []
    for i in range(1, n - 1):
        if not (v[i] >= v[i - 1] and v[i] > v[i + 1]):
            continue
        bases = []
        for step in (-1, 1):
            j, lo = i + step, v[i]
            while 0 <= j < n and v[j] <= v[i]:
                lo = min(lo, v[j])
                j += step
            bases.append(lo)
        prom = float(v[i] - max(bases))
        if prom >= min_prom_m:
            out.append((i, prom))
    return out


def r(x, nd=1):
    return None if x is None else round(float(x), nd)


def fmt_range(a, b):
    return f"{a:,.0f}–{b:,.0f} m"


# ----------------------------------------------------------------------------- analysis

def summit_view(terrain: Terrain, road: Road, summit, s):
    """Line of sight from eye height at road distances s to the summit peak."""
    sx, sy, sz = summit
    xy = road.xy(s)
    eye = terrain.height(xy[:, 0], xy[:, 1]) + EYE_M
    tan, block_d = terrain.horizon_tan(xy[:, 0], xy[:, 1], eye, sx, sy)
    D = np.hypot(sx - xy[:, 0], sy - xy[:, 1]) / 100.0
    fin = np.isfinite(tan)
    skyline = np.where(fin, eye + np.where(fin, tan, 0.0) * D, -np.inf)  # skyline height above the peak
    hidden = np.maximum(0.0, skyline - sz)
    from_summit = np.where(fin, D - block_d, 0.0)
    brg = np.degrees(np.arctan2(sx - xy[:, 0], -(sy - xy[:, 1]))) % 360
    cls = np.where(hidden <= SUMMIT_IN_VIEW_M, "in view",
                   np.where(from_summit <= SUMMIT_MASSIF_M, "behind its own shoulder",
                            "blocked by nearer terrain"))
    return dict(s=np.asarray(s, float), dist=D, hidden=hidden, blocker_from_summit=from_summit,
                bearing=brg, rel=wrap180(brg - road.heading(s)),
                elev=np.degrees(np.arctan2(sz - eye, D)), cls=cls)


def road_visibility(terrain: Terrain, road: Road, s):
    """What of the road ahead (within SIGHT_MAX_M) can be seen from eye height at s."""
    o = road.xy(np.array([s]))[0]
    eye = float(terrain.height(o[0], o[1])) + EYE_M
    st = s + np.arange(10.0, SIGHT_MAX_M + 1e-6, 10.0)
    st = st[st <= road.length]
    if st.size == 0:
        return dict(continuous=0.0, farthest=0.0, total=0.0, ranges=[])
    t = road.xy(st)
    tz = terrain.height(t[:, 0], t[:, 1]) + SIGHT_TARGET_M
    tan, _ = terrain.horizon_tan(o[0], o[1], eye, t[:, 0], t[:, 1])
    D = np.hypot(t[:, 0] - o[0], t[:, 1] - o[1]) / 100.0
    seen = (tz - eye) / np.maximum(D, 1e-6) > tan
    blocked = np.flatnonzero(~seen)
    cont = (st[-1] - s) if blocked.size == 0 else ((st[blocked[0] - 1] - s) if blocked[0] > 0 else 0.0)
    ranges = [[float(st[a]), float(st[b - 1])] for a, b in runs(seen) if b - a >= 3]
    return dict(continuous=float(cont), farthest=float(st[seen][-1] - s) if seen.any() else 0.0,
                total=float(seen.sum() * 10.0), ranges=ranges)


def openness(terrain: Terrain, xy, eye):
    """Mean and max terrain-horizon elevation (deg) over 36 directions, 4 km reach."""
    az = np.radians(np.arange(0, 360, 10))
    n = len(xy)
    ox, oy, oz = np.repeat(xy[:, 0], az.size), np.repeat(xy[:, 1], az.size), np.repeat(eye, az.size)
    tx = ox + np.tile(np.sin(az), n) * 400000.0
    ty = oy - np.tile(np.cos(az), n) * 400000.0
    tan, _ = terrain.horizon_tan(ox, oy, oz, tx, ty, skip_near_m=10.0, step_m=5.0)
    deg = np.degrees(np.arctan(np.where(np.isfinite(tan), tan, np.nan))).reshape(n, az.size)
    return np.nanmean(deg, axis=1), np.nanmax(deg, axis=1)


def steepest(s1, h, window_m, count, sign):
    """Top non-overlapping windows by grade (sign +1 = climbs, -1 = descents)."""
    w = int(window_m)
    g = (h[w:] - h[:-w]) / window_m * 100.0 * sign
    out, used = [], np.zeros(len(g), bool)
    for _ in range(count):
        cand = np.where(used, -np.inf, g)
        i = int(np.argmax(cand))
        if not np.isfinite(cand[i]) or cand[i] <= 0:
            break
        out.append(dict(from_m=float(s1[i]), to_m=float(s1[i + w]), grade_pct=float(g[i] * sign),
                        rise_m=float(h[i + w] - h[i])))
        used[max(0, i - w):i + w] = True
    return out


def turn_events(road: Road, half_m=40.0, min_deg=45.0):
    """Bends: net heading change across a +/-half_m window, peaks above min_deg."""
    s = np.arange(half_m, road.length - half_m, 5.0)
    d = wrap180(road.heading(s + half_m) - road.heading(s - half_m))
    out = []
    for a, b in runs(np.abs(d) >= min_deg):
        k = a + int(np.argmax(np.abs(d[a:b])))
        out.append(dict(at_m=float(s[k]), turn_deg=float(d[k])))
    return out


def zigzags(turns, max_gap_m=200.0, min_count=3):
    """Runs of >= min_count bends that alternate direction, each within max_gap_m of the last."""
    groups, cur = [], []
    for t in turns:
        if cur and (t["at_m"] - cur[-1]["at_m"] <= max_gap_m) and (np.sign(t["turn_deg"]) != np.sign(cur[-1]["turn_deg"])
                                                                   or abs(t["turn_deg"]) >= 90):
            cur.append(t)
        else:
            if len(cur) >= min_count:
                groups.append(cur)
            cur = [t]
    if len(cur) >= min_count:
        groups.append(cur)
    return groups


def straight_runs(road: Road, min_len_m=250.0, tol_deg=8.0):
    """Longest non-overlapping stretches whose heading stays within tol of their start."""
    s = np.arange(0.0, road.length, 5.0)
    a = road.xy(np.maximum(s - 15, 0))
    b = road.xy(np.minimum(s + 15, road.length))
    hd = np.degrees(np.arctan2(b[:, 0] - a[:, 0], -(b[:, 1] - a[:, 1]))) % 360
    best = []
    for i in range(len(s)):
        j = i
        while j + 1 < len(s) and abs(float(wrap180(hd[j + 1] - hd[i]))) <= tol_deg:
            j += 1
        best.append((s[j] - s[i], s[i], s[j]))
    best.sort(reverse=True)
    out = []
    for length, a0, b0 in best:
        if length < min_len_m:
            break
        if any(not (b0 <= o["from_m"] or a0 >= o["to_m"]) for o in out):
            continue
        out.append(dict(from_m=float(a0), to_m=float(b0), length_m=float(length)))
    return sorted(out, key=lambda o: o["from_m"])


def unwalkable_pitches(s1, grad, join_m=40.0):
    """Clusters of road where the terrain is steeper than the default walkable floor angle."""
    limit = math.tan(math.radians(WALKABLE_DEG))
    g = smooth(grad, 5)
    spans = [(float(s1[a]), float(s1[b - 1]), float(g[a:b].max())) for a, b in runs(g > limit)]
    out = []
    for a, b, m in spans:
        if out and a - out[-1]["to_m"] <= join_m:
            out[-1]["to_m"] = b
            out[-1]["steep_m"] += b - a + 1
            out[-1]["max_pct"] = max(out[-1]["max_pct"], m * 100)
        else:
            out.append(dict(from_m=a, to_m=b, steep_m=b - a + 1, max_pct=m * 100))
    for o in out:
        o["max_deg"] = math.degrees(math.atan(o["max_pct"] / 100))
    return out


ZONE_INFO = {
    "valley_floor": "Valley floor",
    "ridge_climb": "Ridge climb",
    "ridge_top": "Ridge top",
    "descent": "Descent into the basin",
    "basin_floor": "Basin floor",
    "lower_slopes": "Mountain foot",
    "switchback_climb": "Switchback climb",
    "mountain_approach": "Summit approach",
}


def find_zones(s1, hs, g150):
    """Natural zone boundaries from the profile: valley -> ridge -> basin -> climb -> shoulder."""
    i_low = int(np.argmin(hs))
    i_ridge = int(np.argmax(hs[:i_low]))
    h_ridge, h_low = hs[i_ridge], hs[i_low]
    j = i_ridge
    while j > 0 and g150[j] < 5.0 and hs[j] > h_ridge - 10.0:
        j -= 1
    while j > 0 and g150[j] >= 5.0:
        j -= 1
    climb_start = j + 1
    top_a = i_ridge
    while top_a > 0 and hs[top_a - 1] >= h_ridge - 10.0:
        top_a -= 1
    top_b = i_ridge
    while top_b < len(hs) - 1 and hs[top_b + 1] >= h_ridge - 10.0:
        top_b += 1
    basin_a = top_b + int(np.argmax(hs[top_b:] <= h_low + 10.0))
    basin_b = i_low + int(np.argmax(hs[i_low:] > h_low + 10.0))
    steep = [(a, b) for a, b in runs(g150 >= 25.0) if a > i_low]
    if not steep:
        raise SystemExit("zone rules: no sustained >= 25 % climb after the basin; revisit find_zones")
    wall_a, wall_b = max(steep, key=lambda ab: ab[1] - ab[0])
    cuts = [0, climb_start, top_a, top_b, basin_a, basin_b, wall_a, wall_b, len(s1) - 1]
    if any(b <= a for a, b in zip(cuts, cuts[1:])):
        raise SystemExit(f"zone rules produced unordered cuts {[float(s1[c]) for c in cuts]}")
    keys = list(ZONE_INFO)
    edges = [float(round(s1[c] / 10.0) * 10.0) for c in cuts]
    edges[-1] = float(s1[-1])
    return [(keys[n], edges[n], edges[n + 1]) for n in range(len(keys))], i_ridge, i_low


def setting_words(horizon_deg):
    if horizon_deg < 4.0:
        return "open"
    if horizon_deg < 9.0:
        return "semi-enclosed"
    return "enclosed"


# ----------------------------------------------------------------------------- build

def build(terrain: Terrain, road: Road) -> dict:
    L = road.length
    s1 = np.append(np.arange(0.0, L, 1.0), L)
    xy1 = road.xy(s1)
    h1 = terrain.height(xy1[:, 0], xy1[:, 1]).astype(float)
    hs = smooth(h1, SMOOTH_M)
    g150 = np.gradient(smooth(h1, 150), s1) * 100.0
    grad1 = terrain.gradient(xy1[:, 0], xy1[:, 1])

    def hs_at(s):
        return np.interp(s, s1, hs)

    def grade(s, half=25.0):
        a, b = np.maximum(np.asarray(s) - half, 0), np.minimum(np.asarray(s) + half, L)
        return (hs_at(b) - hs_at(a)) / (b - a) * 100.0

    g25 = grade(s1)

    def pos(s):
        x, y = road.xy(np.array([float(s)]))[0]
        return dict(dist_m=r(s), x_cm=r(x, 0), y_cm=r(y, 0), z_m=r(np.interp(s, s1, h1)),
                    tile=tile_of(x, y), nearest_spline_point=int(road.nearest_point(float(s))))

    sx, sy, sz = terrain.peak_near(*SUMMIT_HINT_CM)
    summit = (sx, sy, sz)

    # summit line of sight every 10 m
    sv = np.append(np.arange(0.0, L, VIS_STEP_M), L)
    V = summit_view(terrain, road, summit, sv)

    def vi(s):
        return int(np.argmin(np.abs(sv - s)))

    # 50 m samples
    ss = np.arange(0.0, L, STEP_M)
    if L - ss[-1] > 1.0:
        ss = np.append(ss, L)
    sxy = road.xy(ss)
    sh = terrain.height(sxy[:, 0], sxy[:, 1]).astype(float)
    hor_mean, hor_max = openness(terrain, sxy, sh + EYE_M)
    rv = [road_visibility(terrain, road, float(s)) for s in ss]

    zones, i_ridge, i_low = find_zones(s1, hs, g150)

    def zone_at(s):
        for key, a, b in zones:
            if a <= s < b or (s >= b and key == zones[-1][0]):
                return key
        return zones[-1][0]

    samples = []
    for n, s in enumerate(ss):
        x, y = sxy[n]
        k = vi(s)
        hd = float(road.heading(s))
        samples.append(dict(
            dist_m=r(s), dist_to_end_m=r(L - s), x_cm=r(x, 0), y_cm=r(y, 0), terrain_z_m=r(sh[n]),
            slope_pct=r(grade(s)), heading_deg=r(hd, 0), heading_compass=compass(hd), heading_ue_yaw=r(ue_yaw(hd), 0),
            nearest_spline_point=int(road.nearest_point(s)), spline_input_key=r(road.input_key(s), 2),
            ue_spline_distance_m=r(road.ue_spline_distance(s)), spline_z_m=r(road.spline_z_m(s)),
            tile=tile_of(x, y),
            summit_dist_m=r(V["dist"][k], 0), summit_bearing_deg=r(V["bearing"][k], 0),
            summit_bearing_compass=compass(V["bearing"][k]), summit_ue_yaw=r(ue_yaw(V["bearing"][k]), 0),
            summit_relative_deg=r(V["rel"][k], 0), summit_relative=relative_words(V["rel"][k]),
            summit_elevation_deg=r(V["elev"][k]), summit_hidden_m=r(V["hidden"][k]), summit_view=str(V["cls"][k]),
            road_sightline_m=r(rv[n]["continuous"], 0), road_ahead_visible_m=r(rv[n]["total"], 0),
            road_farthest_seen_m=r(rv[n]["farthest"], 0), road_ahead_visible_ranges_m=rv[n]["ranges"],
            horizon_mean_deg=r(hor_mean[n]), horizon_max_deg=r(hor_max[n]),
            zone=zone_at(s)))

    # ---- summary numbers
    d5 = hs[::5]
    steps = np.diff(d5)
    climb, descent = float(steps[steps > 0].sum()), float(-steps[steps < 0].sum())
    walk = float(np.sum(np.hypot(np.diff(s1), np.diff(hs))))
    i_hi, i_lo = int(np.argmax(h1)), int(np.argmin(h1))
    h5 = smooth(h1, 5)
    steep = dict(
        pitch_20m=steepest(s1, h5, 20, 3, 1),
        climbs_100m=steepest(s1, hs, 100, 3, 1),
        climbs_250m=steepest(s1, hs, 250, 3, 1),
        descents_100m=steepest(s1, hs, 100, 3, -1),
        descents_250m=steepest(s1, hs, 250, 2, -1),
    )
    pitches = unwalkable_pitches(s1, grad1)
    turns = turn_events(road)
    zz = zigzags(turns)
    straights = straight_runs(road)
    crests = prominent_extrema(smooth(h1, 75)[::5], 8.0, "max")
    valleys = prominent_extrema(smooth(h1, 75)[::5], 8.0, "min")

    def zones_seen(ranges):
        """'Zone name (N m), ...' for the parts of each zone inside the visible road ranges."""
        parts = []
        for key, za, zb in zones:
            m = sum(max(0.0, min(b, zb) - max(a, za)) for a, b in ranges)
            if m >= 50:
                parts.append(f"{ZONE_INFO[key].lower()} ({m:,.0f} m)")
        return ", ".join(parts)

    # ---- summit visibility summary
    view_runs = []
    for cls in ("in view", "behind its own shoulder", "blocked by nearer terrain"):
        for a, b in runs(V["cls"] == cls):
            view_runs.append(dict(view=cls, from_m=r(sv[a], 0), to_m=r(sv[b - 1], 0),
                                  hidden_min_m=r(V["hidden"][a:b].min()), hidden_max_m=r(V["hidden"][a:b].max())))
    view_runs.sort(key=lambda v: v["from_m"])
    phases = []
    for v in view_runs:
        short = v["to_m"] - v["from_m"] + VIS_STEP_M < 30
        if phases and (short or v["view"] == phases[-1]["view"]):
            ph = phases[-1]
            if v["view"] != ph["view"] and v["view"] not in ph["briefly"]:
                ph["briefly"].append(v["view"])
            ph["to_m"] = v["to_m"]
            ph["hidden_min_m"] = min(ph["hidden_min_m"], v["hidden_min_m"])
            ph["hidden_max_m"] = max(ph["hidden_max_m"], v["hidden_max_m"])
        else:
            phases.append(dict(v, briefly=[]))
    masts = {}
    for H in MAST_HEIGHTS_M:
        masts[str(H)] = [[r(sv[a], 0), r(sv[b - 1], 0)] for a, b in runs(V["hidden"] < H) if sv[b - 1] - sv[a] >= 20]

    # ---- landmarks
    landmarks = []

    def add(kind, name, s, desc, to=None, **data):
        lm = dict(type=kind, name=name, **pos(s))
        if to is not None:
            lm["to_m"] = r(to)
            end = pos(to)
            lm["to_x_cm"], lm["to_y_cm"], lm["to_z_m"] = end["x_cm"], end["y_cm"], end["z_m"]
            lm["length_m"] = r(to - s)
        lm["description"] = desc
        if data:
            lm["data"] = data
        landmarks.append(lm)

    def summit_phrase(s):
        k = vi(s)
        return (f"summit {V['dist'][k] / 1000:.2f} km {compass(V['bearing'][k])}, "
                f"{relative_words(V['rel'][k])} ({V['rel'][k]:+.0f}°), {V['elev'][k]:.1f}° up")

    sp0 = summit_phrase(0.0)
    add("start", "Boot point (spline point 54)", 0.0,
        f"The carrier boots at {h1[0]:.0f} m on the east valley floor, facing up-road "
        f"{compass(road.heading(0.0))} ({float(road.heading(0.0)):.0f}°). {sp0[0].upper() + sp0[1:]}.")

    in_view = runs(V["cls"] == "in view")
    if in_view:
        a, b = in_view[0]
        rel_a = float(V["rel"][a])
        side = (f"near the {'left' if rel_a < 0 else 'right'} edge of a 90° forward view"
                if 35 <= abs(rel_a) <= 55 else relative_words(rel_a))
        add("summit_first_view", "Summit first in clear view", float(sv[a]),
            f"The summit's top is on the skyline from here: only {V['hidden'][a]:.1f} m of the peak is tucked "
            f"behind its own rounded dome. It sits {abs(V['rel'][a]):.0f}° {'left' if V['rel'][a] < 0 else 'right'} "
            f"of the road's heading ({side}), {V['dist'][a] / 1000:.2f} km away and {V['elev'][a]:.1f}° up. "
            f"It stays on the skyline until {sv[b - 1]:,.0f} m.",
            hidden_m=r(V["hidden"][a]))
        ahead = runs((V["cls"] == "in view") & (np.abs(V["rel"]) <= 20))
        if ahead:
            a2, b2 = ahead[0]
            rr = V["rel"][a2:b2]
            span = f"{rr.min():+.0f}°" if abs(rr.max() - rr.min()) < 1 else f"{rr.min():+.0f}° to {rr.max():+.0f}°"
            add("summit_dead_ahead", "Road points at the summit", float(sv[a2]),
                f"For {sv[b2 - 1] - sv[a2] + VIS_STEP_M:.0f} m the road aims almost straight at the summit "
                f"({span} off the heading) while it is on the skyline, {V['dist'][a2] / 1000:.2f} km away: "
                f"the first time the goal sits in the middle of a forward view.",
                to=float(sv[b2 - 1]))
        a3 = b
        if a3 < len(sv):
            e3 = a3 + runs(V["cls"][a3:] == V["cls"][a3])[0][1] - 1
            returns = bool((V["cls"][a3:] == "in view").any())
            add("summit_lost", "Summit top sinks behind its own shoulder", float(sv[a3]),
                f"The peak drops below the brow of its own dome ({V['hidden'][a3]:.0f} m hidden, growing to "
                f"{V['hidden'][e3]:.0f} m by {sv[e3]:,.0f} m). The mountain's upper slopes stay in view"
                + ("." if returns else "; the peak itself is not back on the skyline for the rest of the road."),
                to=float(sv[e3]))
    blocked = [(a, b) for a, b in runs(V["cls"] == "blocked by nearer terrain")]
    if blocked:
        a, b = max(blocked, key=lambda ab: ab[1] - ab[0])
        add("summit_blocked", "The face closes the sky", float(sv[a]),
            f"Climbing the mountain's face, the slope right in front hides the summit completely "
            f"(up to {V['hidden'][a:b].max():.0f} m of it below the skyline).", to=float(sv[b - 1]))
    kc = int(np.argmin(V["dist"]))
    add("summit_closest", "Closest pass to the summit", float(sv[kc]),
        f"The road passes {V['dist'][kc]:.0f} m from the summit, which is {relative_words(V['rel'][kc])} "
        f"({V['rel'][kc]:+.0f}°) and {V['elev'][kc]:.0f}° up; its top is still {V['hidden'][kc]:.0f} m below the "
        f"brow of the dome.")
    face_end = sv[max(blocked, key=lambda ab: ab[1] - ab[0])[1] - 1] if blocked else 0.0
    late = sv > face_end
    if late.any():
        kk = int(np.flatnonzero(late)[np.argmin(V["hidden"][late])])
        add("summit_near_reveal", "Nearest the summit comes to reappearing", float(sv[kk]),
            f"On the shoulder only {V['hidden'][kk]:.0f} m of the peak is hidden, {V['dist'][kk]:.0f} m away and "
            f"{relative_words(V['rel'][kk])}: anything on the summit taller than that shows here.")

    hi_note = lo_note = ""
    crest_s = []
    for i, prom in crests:
        s = i * 5.0
        if abs(s - s1[i_hi]) <= 60:
            hi_note = f" It tops a rise of {prom:.0f} m."
            continue
        k = int(np.argmin(np.abs(ss - s)))
        crest_s.append(s)
        add("crest", "Ridge crest" if prom >= 30 else "Crest", s,
            f"Crest at {np.interp(s, s1, h1):.0f} m, {prom:.0f} m above the low ground either side. "
            f"About {rv[k]['total']:,.0f} m of the road ahead is in sight from here: "
            f"{zones_seen(rv[k]['ranges'])}.", prominence_m=r(prom))
    for i, prom in valleys:
        s = i * 5.0
        if abs(s - s1[i_lo]) <= 60:
            lo_note = f" It is the bottom of a {prom:.0f} m-deep basin."
            continue
        add("valley", "Dip", s,
            f"Low point of a {prom:.0f} m-deep hollow, {np.interp(s, s1, h1):.0f} m.", prominence_m=r(prom))
    add("highest_point", "Highest point of the road", float(s1[i_hi]),
        f"{h1[i_hi]:.1f} m on the mountain shoulder, {L - s1[i_hi]:.0f} m before the end.{hi_note}")
    add("lowest_point", "Lowest point of the road", float(s1[i_lo]),
        f"{h1[i_lo]:.1f} m on the basin floor between the ridge and the mountain, {h1[0] - h1[i_lo]:.0f} m below "
        f"the boot point.{lo_note}")

    c100 = steep["climbs_100m"][0]
    add("steepest_climb", "Steepest climb (100 m)", c100["from_m"],
        f"{c100['grade_pct']:.0f}% average ({math.degrees(math.atan(c100['grade_pct'] / 100)):.0f}°), "
        f"+{c100['rise_m']:.0f} m in 100 m.", to=c100["to_m"])
    c250 = steep["climbs_250m"][0]
    add("steepest_climb", "Steepest climb (250 m)", c250["from_m"],
        f"{c250['grade_pct']:.0f}% average, +{c250['rise_m']:.0f} m in 250 m.", to=c250["to_m"])
    d100 = steep["descents_100m"][0]
    add("steepest_descent", "Steepest descent (100 m)", d100["from_m"],
        f"{d100['grade_pct']:.0f}% average, {d100['rise_m']:.0f} m in 100 m, off the ridge.", to=d100["to_m"])
    for p in pitches:
        add("unwalkable_pitch", "Pitch steeper than the walkable limit", p["from_m"],
            f"{p['steep_m']:.0f} m of ground in this stretch is steeper than {WALKABLE_DEG:.1f}° (UE's default "
            f"walkable floor angle); worst {p['max_pct']:.0f}% ({p['max_deg']:.0f}°).", to=p["to_m"],
            steep_m=r(p["steep_m"], 0), max_pct=r(p["max_pct"], 0))

    for t in turns:
        side = "right" if t["turn_deg"] > 0 else "left"
        hair = abs(t["turn_deg"]) >= 90
        add("switchback" if hair else "bend", "Hairpin" if hair else "Sharp bend", t["at_m"],
            f"{abs(t['turn_deg']):.0f}° turn to the {side} within 80 m of road.", turn_deg=r(t["turn_deg"], 0))
    for g in zz:
        a, b = g[0]["at_m"] - 40, g[-1]["at_m"] + 40
        hp = sum(abs(t["turn_deg"]) >= 90 for t in g)
        add("switchback_sequence", "Switchback run" if hp else "Winding stretch", a,
            f"{len(g)} alternating bends in {b - a:.0f} m" + (f", {hp} of them hairpins" if hp else "") + ".",
            to=b, bends=len(g), hairpins=int(hp))
    for st in straights:
        mid = (st["from_m"] + st["to_m"]) / 2
        k = vi(mid)
        k2 = int(np.argmin(np.abs(ss - st["from_m"])))
        view = ("on the skyline" if V["cls"][k] == "in view"
                else f"its top hidden {V['hidden'][k]:.0f} m {V['cls'][k]}")
        add("straight", "Long straight", st["from_m"],
            f"{st['length_m']:.0f} m dead straight heading {compass(road.heading(mid))}; the summit is "
            f"{relative_words(V['rel'][k])} ({V['rel'][k]:+.0f}°), {view}. From its start "
            f"{rv[k2]['total']:,.0f} m of the road ahead is in sight: {zones_seen(rv[k2]['ranges']) or 'nothing far'}.",
            to=st["to_m"])

    # vistas: where the most road ahead is visible (>= 1 km, 400 m apart, not on a crest already listed)
    tot = np.array([v["total"] for v in rv])
    picks = []
    for n in np.argsort(-tot):
        if tot[n] < 1000:
            break
        if all(abs(ss[n] - ss[m]) >= 400 for m in picks) and all(abs(ss[n] - c) > 150 for c in crest_s):
            picks.append(n)
        if len(picks) == 3:
            break
    for n in sorted(picks):
        add("vista", "Road-ahead vista", float(ss[n]),
            f"{tot[n]:,.0f} m of the road ahead is in sight from here: {zones_seen(rv[n]['ranges'])}.")
    wall = next(z for z in zones if z[0] == "switchback_climb")
    for n, v in enumerate(rv):
        seen_wall = sum(max(0.0, min(b, wall[2]) - max(a, wall[1])) for a, b in v["ranges"])
        if seen_wall >= 100:
            add("foreshadow", "First sight of the switchback climb", float(ss[n]),
                f"The road can be seen climbing the mountain's face from here: {seen_wall:.0f} m of the "
                f"switchback climb, which starts {wall[1] - ss[n]:,.0f} m further on.")
            break

    a = L - LAST_STRETCH_M
    last = (sv >= a)
    rise = float(np.interp(L, s1, h1) - np.interp(a, s1, h1))
    add("final_stretch", f"Last {LAST_STRETCH_M:.0f} m", a,
        f"Heading {compass(circ_mean(road.heading(np.arange(a, L, 5.0))) % 360)}, {rise:+.0f} m "
        f"(from {np.interp(a, s1, h1):.0f} to {np.interp(L, s1, h1):.0f} m) over a crest at "
        f"{h1[i_hi]:.0f} m. The summit is {relative_words(circ_mean(V['rel'][last]))} the whole way, "
        f"{V['dist'][last].min():.0f}–{V['dist'][last].max():.0f} m off, hidden by "
        f"{V['hidden'][last].min():.0f}–{V['hidden'][last].max():.0f} m behind its shoulder.", to=L)
    ke = len(sv) - 1
    add("end", "End of the road (spline point 0)", L,
        f"The road stops at {h1[-1]:.0f} m on the mountain's flank heading {compass(road.heading(L))}. "
        f"The summit is {V['dist'][ke]:.0f} m {compass(V['bearing'][ke])} and {sz - h1[-1]:.0f} m higher, "
        f"{relative_words(V['rel'][ke])} ({V['rel'][ke]:+.0f}°) and out of sight ({V['hidden'][ke]:.0f} m below "
        f"the skyline).")

    landmarks.sort(key=lambda x: (x["dist_m"], x.get("to_m", x["dist_m"])))
    landmarks = [dict(id=f"L{n + 1:02d}", **lm) for n, lm in enumerate(landmarks)]

    # ---- zones
    zone_rows = []
    for key, a, b in zones:
        m1 = (s1 >= a) & (s1 <= b)
        mv = (sv >= a) & (sv <= b)
        msm = (ss >= a) & (ss <= b)
        zd = np.diff(hs[m1][::5])
        classes = {str(c): r((V["cls"][mv] == c).mean() * 100, 0) for c in np.unique(V["cls"][mv])}
        hmean = float(np.nanmean(hor_mean[msm])) if msm.any() else float(hor_mean[np.argmin(np.abs(ss - a))])
        zone_rows.append(dict(
            key=key, name=ZONE_INFO[key], from_m=r(a), to_m=r(b), length_m=r(b - a),
            start=pos(a), end=pos(b),
            start_z_m=r(np.interp(a, s1, h1)), end_z_m=r(np.interp(b, s1, h1)),
            min_z_m=r(h1[m1].min()), max_z_m=r(h1[m1].max()),
            climb_m=r(zd[zd > 0].sum()), descent_m=r(-zd[zd < 0].sum()),
            mean_grade_pct=r((hs_at(b) - hs_at(a)) / (b - a) * 100),
            max_climb_pct=r(max(0.0, g25[m1].max())), max_descent_pct=r(min(0.0, g25[m1].min())),
            heading_compass=compass(circ_mean(road.heading(np.arange(a, b, 5.0))) % 360),
            spline_points=[int(road.nearest_point(a)), int(road.nearest_point(b))],
            summit_view_pct=classes,
            summit_relative=relative_words(circ_mean(V["rel"][mv])),
            summit_dist_m=[r(V["dist"][mv].max(), 0), r(V["dist"][mv].min(), 0)],
            summit_hidden_m=[r(V["hidden"][mv].min()), r(V["hidden"][mv].max())],
            horizon_mean_deg=r(hmean), setting=setting_words(hmean)))

    summary = dict(
        length_m=r(L), walk_length_m=r(walk), ue_spline_length_m=r(road.length3),
        start_z_m=r(h1[0]), end_z_m=r(h1[-1]), net_rise_m=r(h1[-1] - h1[0]),
        total_climb_m=r(climb), total_descent_m=r(descent),
        highest=dict(**pos(float(s1[i_hi]))), lowest=dict(**pos(float(s1[i_lo]))),
        steepest=steep, unwalkable_pitches=[{k: r(v) for k, v in p.items()} for p in pitches],
        last_stretch=dict(from_m=r(L - LAST_STRETCH_M), to_m=r(L), rise_m=r(rise)),
    )
    summit_doc = dict(
        x_cm=r(sx, 0), y_cm=r(sy, 0), z_m=r(sz), quoted_x_cm=SUMMIT_HINT_CM[0], quoted_y_cm=SUMMIT_HINT_CM[1],
        offset_from_quoted_m=r(math.hypot(sx - SUMMIT_HINT_CM[0], sy - SUMMIT_HINT_CM[1]) / 100.0),
        tile=tile_of(sx, sy),
        view_phases=phases, view_ranges=view_runs, mast_visible_ranges_m=masts,
        closest_approach=dict(**pos(float(sv[kc])), summit_dist_m=r(V["dist"][kc], 0)),
    )
    meta = dict(
        generated=datetime.date.today().isoformat(),
        generator="Tools/Story/build_road_profile.py",
        spline_vs_heightmap_max_m=r(np.abs(terrain.height(SPLINE_POINTS_CM[:, 0], SPLINE_POINTS_CM[:, 1])
                                           - SPLINE_POINTS_CM[:, 2] / 100.0).max(), 2),
        level="/Game/level/Saskarta_WP",
        heightmap="Saved/TerrainRebuild/Current_u16.png",
        landscape=dict(origin_cm=[LAND_X0_CM, LAND_Y0_CM], scale=[PX_CM, PX_CM, Z_SCALE], tile_cm=TILE_CM,
                       height_formula="z_cm = (u16 - 32768) / 128 * 200"),
        direction="spline point 54 (start, east valley) -> point 0 (end, central mountain flank)",
        conventions=dict(
            dist_m="horizontal metres along the road polyline from point 54",
            slope_pct="terrain rise over horizontal run in the travel direction over +/-25 m (+ = uphill)",
            bearings="compass degrees, north = -Y (up on the top-down map), east = +X, clockwise",
            ue_yaw="Unreal yaw in degrees = atan2(dY, dX) = bearing - 90",
            relative_deg="angle from the travel direction to the summit, + = right, - = left",
            ue_spline_distance_m="distance from point 0 along RoadSpline, 3D, assuming linear segments "
                                 "(sums to the 5.13 km spline length); use with GetLocationAtDistanceAlongSpline",
            spline_input_key="float point index for GetLocationAtSplineInputKey",
            summit_hidden_m="how many metres of the summit's top lie below the terrain skyline seen from 1.7 m "
                            "eye height; 0 = the peak itself is visible; a structure taller than this shows",
            summit_view=f"'in view' = hidden <= {SUMMIT_IN_VIEW_M:.0f} m; 'behind its own shoulder' = blocked by "
                        f"terrain within {SUMMIT_MASSIF_M:.0f} m of the peak; 'blocked by nearer terrain' otherwise",
            road_sightline_m=f"continuous length of road ahead in view (target {SIGHT_TARGET_M} m above ground)",
            road_ahead_visible_m=f"total road within {SIGHT_MAX_M:.0f} m ahead that is in view, in 10 m steps",
            horizon_mean_deg="mean terrain-horizon elevation over 36 directions (4 km reach); high = enclosed",
            line_of_sight="terrain only; foliage, rocks, buildings and props are not counted"),
    )
    return dict(meta=meta, summary=summary, summit=summit_doc, zones=zone_rows, landmarks=landmarks,
                samples=samples)


# ----------------------------------------------------------------------------- markdown

VIEW_SHORT = {"in view": "on skyline", "behind its own shoulder": "behind its shoulder",
              "blocked by nearer terrain": "blocked"}
PLOT_MARKS = [("start", "B"), ("summit_dead_ahead", "A"), ("crest", "^"), ("lowest_point", "L"),
              ("straight", "="), ("switchback", "H"), ("summit_closest", "C"), ("highest_point", "T"),
              ("end", "E")]


def m(x):
    return f"{x:,.0f}"


def pct(v):
    v = round(float(v))
    return "0%" if v == 0 else f"{v:+d}%"


def at(lm):
    return f"{m(lm['dist_m'])}–{m(lm['to_m'])}" if "to_m" in lm else m(lm["dist_m"])


def table(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return out


def ascii_profile(doc, rows=14):
    S = doc["samples"]
    h = np.array([p["terrain_z_m"] for p in S])
    lo, hi = math.floor(h.min() / 50) * 50, math.ceil(h.max() / 50) * 50
    step = (hi - lo) / rows
    out = []
    for rr in range(rows):
        top = hi - rr * step
        label = f"{top:>6.0f} m |" if rr % 2 == 0 else " " * 9 + "|"
        out.append(label + "".join("█" if v >= top - step / 2 else " " for v in h))
    out.append(" " * 9 + "+" + "-" * len(h))
    marks = [" "] * len(h)
    for kind, ch in PLOT_MARKS:
        for lm in doc["landmarks"]:
            if lm["type"] == kind:
                c = min(len(h) - 1, int(round(lm["dist_m"] / STEP_M)))
                marks[c] = ch
    out.append("   marks |" + "".join(marks))
    keys = list(ZONE_INFO)
    out.append("    zone |" + "".join(str(keys.index(p["zone"]) + 1) for p in S))
    ticks = [" "] * len(h)
    for km in range(int(S[-1]["dist_m"] // 1000) + 1):
        c = int(round(km * 1000 / STEP_M))
        for j, ch in enumerate(f"{km} km"):
            if c + j < len(h):
                ticks[c + j] = ch
    out.append(" " * 10 + "".join(ticks))
    return out


def prose(doc):
    S, Z, LM, SM = doc["summary"], {z["key"]: z for z in doc["zones"]}, doc["landmarks"], doc["summit"]
    one = {}
    for lm in LM:
        one.setdefault(lm["type"], lm)

    def of(kind, a, b):
        return [lm for lm in LM if lm["type"] == kind and a <= lm["dist_m"] < b]

    vf, rc, rt, de = Z["valley_floor"], Z["ridge_climb"], Z["ridge_top"], Z["descent"]
    bf, lo, sc, ma = Z["basin_floor"], Z["lower_slopes"], Z["switchback_climb"], Z["mountain_approach"]
    samples = doc["samples"]
    first = samples[0]
    lowest, highest, end = one["lowest_point"], one["highest_point"], one["end"]
    ridge = [c for c in of("crest", rc["from_m"], rt["to_m"] + 1) if c["name"] == "Ridge crest"][0]
    best = max(samples, key=lambda p: p["road_ahead_visible_m"])
    straight = max(of("straight", bf["from_m"] - 200, lo["to_m"]), key=lambda x: x["length_m"])
    sp = min(samples, key=lambda p: abs(p["dist_m"] - straight["dist_m"]))
    straight_elev, straight_dist = sp["summit_elevation_deg"], sp["summit_dist_m"]
    straight_z_gap = SM["z_m"] - sp["terrain_z_m"]
    hairpins = of("switchback", sc["from_m"], sc["to_m"])
    seqs = [lm for lm in LM if lm["type"] == "switchback_sequence"]
    zz = [q for q in seqs if sc["from_m"] <= (q["dist_m"] + q["to_m"]) / 2 < sc["to_m"]]
    winding = [q for q in seqs if ma["from_m"] <= (q["dist_m"] + q["to_m"]) / 2 <= ma["to_m"]]
    blocked = one.get("summit_blocked")
    pitches = S["unwalkable_pitches"]
    c100 = S["steepest"]["climbs_100m"][0]
    d100 = S["steepest"]["descents_100m"][0]
    closest = one["summit_closest"]
    lost, ahead, fore = one.get("summit_lost"), one.get("summit_dead_ahead"), one.get("foreshadow")
    ends = [p for p in samples if p["dist_m"] >= S["length_m"] - LAST_STRETCH_M]
    last_sample = samples[-1]

    feats = []
    for c in of("crest", vf["from_m"], vf["to_m"]):
        feats.append(f"a low rise at {m(c['dist_m'])} m ({c['z_m']:.0f} m)")
    for v in of("valley", vf["from_m"], vf["to_m"]):
        feats.append(f"a dip at {m(v['dist_m'])} m ({v['z_m']:.0f} m)")
    ps = []
    ps.append(
        f"The road is {S['length_m'] / 1000:.2f} km on the map ({S['walk_length_m'] / 1000:.2f} km over the ground). "
        f"It starts at {S['start_z_m']:.0f} m on the east valley floor and ends at {S['end_z_m']:.0f} m on the "
        f"central mountain's flank, {S['net_rise_m']:.0f} m higher, after {S['total_climb_m']:.0f} m of climbing and "
        f"{S['total_descent_m']:.0f} m of descending. The first {sc['from_m'] / 1000:.1f} km are low ground: a long, "
        f"nearly level valley, one low ridge, and a basin that sinks {S['start_z_m'] - lowest['z_m']:.0f} m below "
        f"the start. Then nearly all the height comes at once: the switchback climb gains {sc['climb_m']:.0f} m in "
        f"{sc['length_m']:.0f} m, and the road ends on a rolling shoulder below the summit.")
    ps.append(
        f"**{vf['name']} (0–{m(vf['to_m'])} m).** The carrier boots facing {first['heading_compass']}. For "
        f"{vf['length_m'] / 1000:.1f} km the road wanders {vf['heading_compass']} between {vf['min_z_m']:.0f} and "
        f"{vf['max_z_m']:.0f} m, never much steeper than {max(vf['max_climb_pct'], -vf['max_descent_pct']):.0f}%"
        + (f", past {' and '.join(feats)}" if feats else "") + ". "
        f"The ground rises about {vf['horizon_mean_deg']:.0f}° on every side ({vf['setting']}). The summit is on the "
        f"skyline the whole way, {vf['summit_relative']}, {vf['summit_dist_m'][0] / 1000:.1f}–"
        f"{vf['summit_dist_m'][1] / 1000:.1f} km off"
        + (f"; for about {ahead['length_m'] + VIS_STEP_M:.0f} m from {m(ahead['dist_m'])} m the road points "
           f"straight at it" if ahead else "") + "."
        + (f" From {m(fore['dist_m'])} m on, the far climb up the mountain's face is already visible, "
           f"{(sc['from_m'] - fore['dist_m']) / 1000:.1f} km ahead." if fore else ""))
    ps.append(
        f"**Ridge ({m(rc['from_m'])}–{m(rt['to_m'])} m).** The road climbs {rc['climb_m'] + rt['climb_m']:.0f} m "
        f"{rc['heading_compass']} in {rc['length_m'] + rt['length_m']:.0f} m (up to {rc['max_climb_pct']:.0f}% "
        f"over 50 m) to a narrow crest at {ridge['z_m']:.0f} m, {m(ridge['dist_m'])} m in (tile "
        f"{ridge['tile'][0]},{ridge['tile'][1]}). The top is only about {rt['length_m']:.0f} m long. "
        + ridge["description"].split(". ", 1)[1]
        + (" No other point on the road shows as much of the way ahead."
           if abs(best["dist_m"] - ridge["dist_m"]) <= 60 else ""))
    ps.append(
        f"**{de['name']} ({m(de['from_m'])}–{m(de['to_m'])} m).** Off the crest the road drops "
        f"{de['descent_m']:.0f} m in {de['length_m']:.0f} m heading {de['heading_compass']}, steepest right at the top "
        f"({abs(d100['grade_pct']):.0f}% over 100 m)."
        + (f" At {m(lost['dist_m'])} m the summit's peak slips behind the brow of its own dome: the mountain "
           f"stays ahead, but its top does not come back into view." if lost else ""))
    ps.append(
        f"**{bf['name']} ({m(bf['from_m'])}–{m(bf['to_m'])} m).** The lowest ground of the journey, "
        f"{lowest['z_m']:.0f} m at {m(lowest['dist_m'])} m. The road swings {bf['heading_compass']}, and at "
        f"{m(straight['dist_m'])} m begins its longest straight: {straight['length_m']:.0f} m aimed at the mountain, "
        f"whose top stands about {straight_elev:.0f}° above eye level, "
        f"{straight_z_gap:.0f} m higher and {straight_dist / 1000:.1f} km ahead.")
    ps.append(
        f"**{lo['name']} ({m(lo['from_m'])}–{m(lo['to_m'])} m).** The ground tilts up: +{lo['climb_m']:.0f} m in "
        f"{lo['length_m']:.0f} m ({lo['mean_grade_pct']:.0f}% on average, a step of up to "
        f"{lo['max_climb_pct']:.0f}%), and the terrain starts to close in (horizon about "
        f"{lo['horizon_mean_deg']:.0f}°).")
    hp_txt = " and ".join(m(h["dist_m"]) for h in hairpins) + " m"
    ps.append(
        f"**{sc['name']} ({m(sc['from_m'])}–{m(sc['to_m'])} m).** The hard part: +{sc['climb_m']:.0f} m in "
        f"{sc['length_m']:.0f} m, {sc['mean_grade_pct']:.0f}% on average and {c100['grade_pct']:.0f}% over the worst "
        f"100 m ({m(c100['from_m'])}–{m(c100['to_m'])} m)."
        + (f" The road zigzags through {sum(z['data']['bends'] for z in zz)} alternating bends"
           + (f", with hairpins at {hp_txt}" if hairpins else "") + "." if zz else "")
        + (f" From {m(blocked['dist_m'])} to {m(blocked['to_m'])} m the slope in front hides the summit "
           f"completely." if blocked else "")
        + (f" About {sum(p['steep_m'] for p in pitches):.0f} m of ground on this line is steeper than the default "
           f"walkable angle of the UE character ({WALKABLE_DEG:.1f}°)." if pitches else ""))
    open_most = ma["horizon_mean_deg"] == min(z["horizon_mean_deg"] for z in doc["zones"])
    ps.append(
        f"**{ma['name']} ({m(ma['from_m'])}–{m(ma['to_m'])} m).** The road tops out at {ma['start_z_m']:.0f} m and "
        f"rolls along the shoulder between {ma['min_z_m']:.0f} and {ma['max_z_m']:.0f} m"
        + (f" through {winding[0]['data']['bends']} alternating bends" if winding else "")
        + f", the horizon dropping to about {ma['horizon_mean_deg']:.0f}°"
        + (" (the most open ground on the route)" if open_most else "") + ". "
        f"At {m(closest['dist_m'])} m it passes {SM['closest_approach']['summit_dist_m']:.0f} m from the summit, "
        f"but the peak stays {ma['summit_hidden_m'][0]:.0f}–{ma['summit_hidden_m'][1]:.0f} m below the brow of its "
        f"dome. The last {LAST_STRETCH_M:.0f} m run {compass(circ_mean([p['heading_deg'] for p in ends]) % 360)}, "
        f"with the summit {relative_words(circ_mean([p['summit_relative_deg'] for p in ends]))}, over the road's "
        f"high point ({highest['z_m']:.0f} m at {m(highest['dist_m'])} m). At the end of the road the summit is "
        f"{last_sample['summit_relative']}: {last_sample['summit_dist_m']:.0f} m "
        f"{last_sample['summit_bearing_compass']}, {SM['z_m'] - end['z_m']:.0f} m higher, and out of sight.")
    return ps


def render_markdown(doc) -> str:
    S, SM, Z, LM, P, M = doc["summary"], doc["summit"], doc["zones"], doc["landmarks"], doc["samples"], doc["meta"]
    o = []
    o += ["# Road profile: Saskarta_WP", ""]
    o += [f"The road as the player walks it, from spline point 54 (the carrier's boot point, east valley) to "
          f"point 0 (the central mountain's flank). Generated {M['generated']} by `{M['generator']}` from "
          f"`{M['heightmap']}`. Machine-readable twin: [`road-profile.json`](road-profile.json). Re-run the script "
          f"instead of editing numbers by hand.", ""]

    o += ["## At a glance", ""]
    c100, c250 = S["steepest"]["climbs_100m"][0], S["steepest"]["climbs_250m"][0]
    d100 = S["steepest"]["descents_100m"][0]
    o += [
        f"- **Length:** {m(S['length_m'])} m on the map, {m(S['walk_length_m'])} m over the ground "
        f"(RoadSpline reports {S['ue_spline_length_m'] / 1000:.2f} km).",
        f"- **Height:** starts {S['start_z_m']:.0f} m, ends {S['end_z_m']:.0f} m: net {S['net_rise_m']:+.0f} m, "
        f"total climb {S['total_climb_m']:.0f} m, total descent {S['total_descent_m']:.0f} m.",
        f"- **Highest point:** {S['highest']['z_m']:.0f} m at {m(S['highest']['dist_m'])} m (spline point "
        f"{S['highest']['nearest_spline_point']}). **Lowest:** {S['lowest']['z_m']:.0f} m at "
        f"{m(S['lowest']['dist_m'])} m (point {S['lowest']['nearest_spline_point']}).",
        f"- **Steepest:** {c100['grade_pct']:.0f}% over 100 m ({m(c100['from_m'])}–{m(c100['to_m'])} m), "
        f"{c250['grade_pct']:.0f}% over 250 m; steepest descent {abs(d100['grade_pct']):.0f}% over 100 m "
        f"({m(d100['from_m'])}–{m(d100['to_m'])} m).",
        f"- **Summit** ({SM['z_m']:.0f} m, tile {SM['tile'][0]},{SM['tile'][1]}): on the skyline from the boot "
        f"point to {m(SM['view_phases'][0]['to_m'])} m; after that its peak stays hidden (behind its own dome, "
        f"or behind the slope ahead on the climb). The road passes {SM['closest_approach']['summit_dist_m']:.0f} m "
        f"from it and ends with it {P[-1]['summit_relative']}, {P[-1]['summit_dist_m']:.0f} m away.",
        "",
    ]

    o += ["## The shape of the journey", ""]
    for p in prose(doc):
        o += [p, ""]

    o += ["## Elevation profile", "",
          "One column per 50 m sample, height from the heightmap. `marks`: B boot point, A road points at the "
          "summit, ^ crest, L lowest point, = long straight, H hairpin, C closest pass to the summit, T highest "
          "point, E end. `zone` numbers match the zone table.", "", "```"]
    o += ascii_profile(doc)
    o += ["```", ""]

    o += ["## Zones", "",
          "Boundaries come from the terrain: the valley floor ends where the sustained climb to the ridge begins; "
          "the ridge top and basin floor are the ground within 10 m of the crest and of the lowest point; the "
          "switchback climb is the longest stretch steeper than 25% (150 m average). *Setting* is how boxed-in "
          "the ground is, the mean elevation of the terrain horizon around the road (open under 4°, "
          "semi-enclosed 4–9°, enclosed 9° and up): a physical cue for placing nature-only ambience such as wind "
          "exposure against shelter.", ""]
    rows = []
    for n, z in enumerate(Z, 1):
        views = sorted(z["summit_view_pct"].items(), key=lambda kv: -kv[1])
        view = ", ".join(f"{VIEW_SHORT[k]}" + ("" if v == 100 else f" {v:.0f}%") for k, v in views)
        rows.append([n, f"**{z['name']}**", f"{m(z['from_m'])}–{m(z['to_m'])}", m(z["length_m"]),
                     f"{z['start_z_m']:.0f} → {z['end_z_m']:.0f}", f"+{z['climb_m']:.0f} / -{z['descent_m']:.0f}",
                     pct(z["mean_grade_pct"]), f"{pct(z['max_climb_pct'])} / {pct(z['max_descent_pct'])}",
                     z["heading_compass"], f"{view}; {z['summit_relative']}",
                     f"{z['setting']} ({z['horizon_mean_deg']:.0f}°)", f"{z['spline_points'][0]}→{z['spline_points'][1]}"])
    o += table(["#", "Zone", "From–to (m)", "Length (m)", "Height (m)", "Climb / descent (m)", "Avg slope",
                "Steepest up / down (50 m)", "Heading", "Summit", "Setting", "Spline pts"], rows)
    o += [""]

    o += ["## Key moments", "",
          "Landmarks a level designer can hang beats on, in road order. Positions are Unreal world units (cm); "
          "bends, walkability pitches and every value below are also in the JSON.", ""]
    rows = []
    for lm in LM:
        if lm["type"] in ("bend", "unwalkable_pitch"):
            continue
        rows.append([at(lm), f"**{lm['name']}**", lm["description"], f"{m(lm['x_cm'])}, {m(lm['y_cm'])}",
                     f"{lm['tile'][0]},{lm['tile'][1]}", lm["nearest_spline_point"]])
    o += table(["At (m)", "Moment", "What is there", "X, Y (cm)", "Tile", "Pt"], rows)
    o += [""]

    o += ["## The summit", "",
          f"The summit is the highest pixel of the heightmap: ({m(SM['x_cm'])}, {m(SM['y_cm'])}) cm, "
          f"{SM['z_m']:.1f} m, tile {SM['tile'][0]},{SM['tile'][1]}, {SM['offset_from_quoted_m']:.0f} m from the "
          f"quoted ({m(SM['quoted_x_cm'])}, {m(SM['quoted_y_cm'])}). Its top is a rounded dome, so from below the "
          f"brow of the dome always hides the exact peak by a little. *Hidden* is how many metres of the peak are "
          f"below the terrain skyline, seen from 1.7 m eye height: anything standing on the summit taller than "
          f"that is visible.", ""]
    rows = [[f"{m(v['from_m'])}–{m(v['to_m'])}",
             VIEW_SHORT[v["view"]] + "".join(f", briefly {VIEW_SHORT[b]}" for b in v["briefly"]),
             f"{v['hidden_min_m']:.0f}–{v['hidden_max_m']:.0f}"] for v in SM["view_phases"]]
    o += table(["Road (m)", "Summit", "Hidden (m)"], rows)
    o += ["", "What a structure on the summit (for example a mast at the Âlaawb site) would need to be seen:", ""]
    rows = [[f"{h} m", "; ".join(f"{m(a)}–{m(b)}" for a, b in rs) or "nowhere"]
            for h, rs in SM["mast_visible_ranges_m"].items()]
    o += table(["Height above the peak", "Top visible from road (m)"], rows)
    o += [""]

    o += ["## Steepness", ""]
    rows = []
    for label, key in (("Climb, 20 m pitch", "pitch_20m"), ("Climb, 100 m", "climbs_100m"),
                       ("Climb, 250 m", "climbs_250m"), ("Descent, 100 m", "descents_100m"),
                       ("Descent, 250 m", "descents_250m")):
        for w in S["steepest"][key]:
            rows.append([label, f"{m(w['from_m'])}–{m(w['to_m'])}", f"{w['grade_pct']:+.0f}%",
                         f"{math.degrees(math.atan(abs(w['grade_pct']) / 100)):.0f}°", f"{w['rise_m']:+.0f}"])
    o += table(["Window", "Road (m)", "Grade", "Angle", "Rise (m)"], rows)
    o += ["", f"Ground steeper than UE's default walkable floor angle ({WALKABLE_DEG:.1f}°, about 99%), from the "
              f"terrain gradient under the road centreline. The template character cannot walk up these pitches "
              f"unless the angle is raised or the road surface is eased:", ""]
    rows = [[f"{m(p['from_m'])}–{m(p['to_m'])}", f"{p['steep_m']:.0f}", f"{p['max_pct']:.0f}% ({p['max_deg']:.0f}°)"]
            for p in S["unwalkable_pitches"]]
    o += table(["Road (m)", "Steeper than the limit (m)", "Worst"], rows) if rows else ["None."]
    o += [""]

    o += ["## Bends", "", "Net heading change across 80 m of road, 45° and up. + = right, - = left.", ""]
    rows = [[m(lm["dist_m"]), lm["name"], f"{lm['data']['turn_deg']:+.0f}°", lm["nearest_spline_point"]]
            for lm in LM if lm["type"] in ("bend", "switchback")]
    o += table(["At (m)", "Kind", "Turn", "Pt"], rows)
    o += [""]

    o += ["## Every 50 m", "", f"<details><summary>Sample table ({len(P)} rows; the JSON has more fields)</summary>", ""]
    rows = []
    zshort = {k: v.split(" (")[0] for k, v in ZONE_INFO.items()}
    for p in P:
        view = f"{VIEW_SHORT[p['summit_view']]} ({p['summit_hidden_m']:.0f} m)"
        rows.append([m(p["dist_m"]), m(p["x_cm"]), m(p["y_cm"]), f"{p['terrain_z_m']:.1f}", pct(p["slope_pct"])[:-1],
                     p["heading_compass"], p["nearest_spline_point"], f"{p['tile'][0]},{p['tile'][1]}",
                     m(p["summit_dist_m"]), f"{p['summit_bearing_deg']:.0f}° {p['summit_bearing_compass']}",
                     pct(p["summit_relative_deg"])[:-1] + "°", view, zshort[p["zone"]]])
    o += table(["m", "X (cm)", "Y (cm)", "Z (m)", "Slope %", "Heading", "Pt", "Tile", "Summit (m)",
                "Summit bearing", "Summit rel.", "Summit view (hidden)", "Zone"], rows)
    o += ["", "</details>", ""]

    C = M["conventions"]
    o += ["## How this was measured", "",
          f"- **Road.** Straight lines between the 55 RoadSpline points, walked from 54 to 0. Their 3D length is "
          f"{S['ue_spline_length_m']:,.1f} m, the 5.13 km the editor reports for RoadSpline, which suggests the points "
          f"are linear; if they are curved the real road cuts corners by up to about 20 m. Distances are horizontal "
          f"map metres from point 54; the JSON also gives `ue_spline_distance_m` (from point 0, as UE measures) and "
          f"`spline_input_key` for placing things with the spline API.",
          f"- **Terrain.** `{M['heightmap']}`, 1 px = 1 m, {M['landscape']['height_formula']}, bilinear lookups. "
          f"The 55 spline points' own Z match it to within {M['spline_vs_heightmap_max_m']:.1f} m.",
          "- **Slope.** 25 m moving average of the 1 m profile, grade over ±25 m. Steepness windows use the same "
          "profile (5 m average for the 20 m pitch). Walkability uses the full terrain gradient at the road "
          "centreline.",
          f"- **Summit visibility.** {C['summit_hidden_m'][0].upper() + C['summit_hidden_m'][1:]}. Ray-marched every "
          f"2 m across the heightmap from every 10 m of road. Classes: {C['summit_view']}.",
          f"- **Road ahead.** {C['road_ahead_visible_m'][0].upper() + C['road_ahead_visible_m'][1:]}; target "
          f"{SIGHT_TARGET_M} m above the road surface.",
          f"- **Setting.** {C['horizon_mean_deg'][0].upper() + C['horizon_mean_deg'][1:]}.",
          f"- **Directions.** {C['bearings'][0].upper() + C['bearings'][1:]}. {C['ue_yaw']}. Relative angles: "
          f"{C['relative_deg']}.",
          f"- **Limits.** Every line of sight is {C['line_of_sight']}. Views through forests will be shorter.",
          ""]
    return "\n".join(o)


def main():
    ap = argparse.ArgumentParser(description="Write docs/story/road-profile.{md,json}.")
    ap.add_argument("--out", type=Path, default=OUT_DIR, help="output folder (default docs/story)")
    args = ap.parse_args()
    terrain = Terrain(HEIGHTMAP)
    road = Road(SPLINE_POINTS_CM)
    doc = build(terrain, road)
    args.out.mkdir(parents=True, exist_ok=True)
    js = args.out / "road-profile.json"
    md = args.out / "road-profile.md"
    js.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    md.write_text(render_markdown(doc), encoding="utf-8")
    S = doc["summary"]
    print(f"road {S['length_m']:.0f} m, climb {S['total_climb_m']:.0f} m, descent {S['total_descent_m']:.0f} m, "
          f"{len(doc['samples'])} samples, {len(doc['landmarks'])} landmarks, {len(doc['zones'])} zones")
    print(f"wrote {js}\nwrote {md}")


if __name__ == "__main__":
    main()
