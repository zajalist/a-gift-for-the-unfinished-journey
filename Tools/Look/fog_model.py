"""Offline model of the level's ExponentialHeightFog, for tuning the horizontal fog bands (task SKY).

    python Tools/Look/fog_model.py report [--key Valley]        # numbers for the title view
    python Tools/Look/fog_model.py render out.png [--key Valley] # fog transmittance over the title
                                                                 # view, from the Gaea heightmap
    python Tools/Look/fog_model.py road [--keys K.json]          # the blended fog along the road (JSON rows)
    python Tools/Look/fog_model.py table [--keys K.json] [--terrain]  # FOG3: the per-key transmittance table
    python Tools/Look/fog_model.py stretches [--terrain]        # FOG3: the blended fog by road stretch
    python Tools/Look/fog_model.py fit [--write]                 # FOG3: fit every key's fog from FOG3_PLAN

Why offline: in the editor World Partition does not draw the far terrain (HLODs are not built,
Tools/Look/HLOD.md), so an editor capture cannot show how the fog lies on the central mountain.
This reproduces the engine's height-fog integral (ExponentialHeightFogCommon.ush, UE 5.x):

  per layer i:  density_i(z) = (FogDensity_i / 1000) * 2^(-(FogHeightFalloff_i / 1000) * (z - Height_i))
                with z in cm, Height_0 = the fog actor's Z, Height_1 = Height_0 + SecondFogData.FogHeightOffset
  the ray starts StartDistance from the camera; its line integral is closed form per layer,
                density at the ray's origin x (1 - 2^-x) / x x ray length, x = falloff x ray rise
                (the engine's form: ln 2 x the physical integral, Taylor limit ln 2);
  transmittance T = max(2^(-integral), 1 - FogMaxOpacity); FogCutoffDistance > 0 turns fog off
  for receivers beyond it.

The surface under each pixel comes from Tools/Story/build_road_profile.Terrain (the Gaea
heightmap the landscape was built from), ray-marched from the title camera
(build_title_sequence.pose_at). Values come from look_keys.json and apply_look.py, so this model
and the level agree.

What the numbers mean (report):
  T_summit   transmittance to the mountain just under its summit: how much of the silhouette's
             contrast survives the fog (check_silhouette.py scales by about this factor).
  T_mid      the same at the mountain's mid-height (the brief: fog stays below roughly here).
  T_base     the mountain's lower slopes and the valley floor in front of them: low = a visible band.
  top_m      the fog top: the height where the combined density falls to 5 % of its value at the
             valley floor under the camera.
"""
import argparse
import json
import math
import pathlib
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "Tools" / "Story"))

FOG_ACTOR_Z_CM = -42000.0   # the level's ExponentialHeightFog actor (Sky & Light)


def layers_from_key(key, second_falloff, fog_z_cm=FOG_ACTOR_Z_CM):
    f = key["fog"]
    return [
        {"density": f["density"], "falloff": f["falloff"], "height_cm": fog_z_cm},
        {"density": f["second_density"], "falloff": f.get("second_falloff", second_falloff),
         "height_cm": fog_z_cm + f["second_height_m"] * 100.0},
    ]


def density_at(z_cm, layers):
    """Extinction per cm at world height z (cm), both layers (exp2, as the engine)."""
    z = np.asarray(z_cm, dtype=np.float64)
    out = np.zeros_like(z)
    for L in layers:
        e = np.clip(L["falloff"] / 1000.0 * (z - L["height_cm"]), -127.0, 127.0)
        out = out + L["density"] / 1000.0 * np.exp2(-e)
    return out


def line_integral(cam, target, layers, start_cm=0.0):
    """Engine line integral of fog extinction from cam to target (world cm, arrays OK)."""
    cam = np.asarray(cam, dtype=np.float64)
    tgt = np.asarray(target, dtype=np.float64)
    d = tgt - cam
    length = np.linalg.norm(d, axis=-1)
    safe = np.maximum(length, 1e-6)
    excl = np.clip(start_cm / safe, 0.0, 1.0)
    z0 = cam[..., 2] + excl * d[..., 2]
    ray_len = (1.0 - excl) * length
    ray_dz = (1.0 - excl) * d[..., 2]
    total = np.zeros_like(length)
    for L in layers:
        k = L["falloff"] / 1000.0
        origin = L["density"] / 1000.0 * np.exp2(-np.clip(k * (z0 - L["height_cm"]), -127.0, 127.0))
        fall = np.clip(k * ray_dz, -127.0, 127.0)
        # (1 - 2^-x) / x, with its limit ln 2 at x -> 0
        small = np.abs(fall) < 1e-4
        ratio = np.where(small, math.log(2.0) - 0.5 * math.log(2.0) ** 2 * fall,
                         (1.0 - np.exp2(-fall)) / np.where(small, 1.0, fall))
        total = total + origin * ratio
    return total * ray_len


def transmittance(cam, target, layers, start_cm=0.0, max_opacity=0.8, cutoff_cm=0.0):
    t = np.clip(np.exp2(-line_integral(cam, target, layers, start_cm)), 0.0, 1.0)
    t = np.maximum(t, 1.0 - max_opacity)
    if cutoff_cm > 0:
        dist = np.linalg.norm(np.asarray(target, float) - np.asarray(cam, float), axis=-1)
        t = np.where(dist > cutoff_cm, 1.0, t)
    return t


def fog_top_m(layers, floor_m, frac=0.05):
    """Height (m) where the combined density falls to `frac` of its value at floor_m."""
    ref = float(density_at(floor_m * 100.0, layers))
    z = np.arange(floor_m, floor_m + 2000.0, 1.0)
    d = density_at(z * 100.0, layers)
    above = np.nonzero(d <= frac * ref)[0]
    return float(z[above[0]]) if above.size else None


# ----------------------------------------------------------------------------- title view

def _camera_basis(pitch, yaw):
    p, y = math.radians(pitch), math.radians(yaw)
    fwd = np.array([math.cos(p) * math.cos(y), math.cos(p) * math.sin(y), math.sin(p)])
    right = np.array([-math.sin(y), math.cos(y), 0.0])
    up = np.cross(fwd, right)  # UE is left-handed: X forward, Y right, Z up
    return fwd, right, up


def trace_view(terrain, cam, pitch, yaw, hfov, w=192, h=108, step_m=5.0, max_m=9000.0):
    """Hit points (cm) of the terrain for a w x h pixel grid; NaN where the ray reaches the sky."""
    fwd, right, up = _camera_basis(pitch, yaw)
    k = (w / 2) / math.tan(math.radians(hfov) / 2)
    xs = (np.arange(w) + 0.5 - w / 2) / k
    ys = (h / 2 - (np.arange(h) + 0.5)) / k
    X, Y = np.meshgrid(xs, ys)
    dirs = fwd[None, None, :] + X[..., None] * right + Y[..., None] * up
    dirs /= np.linalg.norm(dirs, axis=-1, keepdims=True)
    hit = np.full(dirs.shape, np.nan)
    alive = np.ones(X.shape, dtype=bool)
    cam = np.asarray(cam, dtype=np.float64)
    for s in np.arange(step_m, max_m, step_m) * 100.0:
        if not alive.any():
            break
        p = cam + dirs[alive] * s
        below = p[:, 2] <= terrain.height(p[:, 0], p[:, 1]) * 100.0
        if below.any():
            idx = np.argwhere(alive)[below]
            hit[idx[:, 0], idx[:, 1]] = p[below]
            alive[idx[:, 0], idx[:, 1]] = False
    return hit, dirs


# The dock view the Valley fog was tuned from (Task SKY): the L3 title camera's t=0 pose, before
# Task TITLE moved the title shots to the valley floor at road metre ~2650.
DOCK_POSE = ((616829.1, 463534.7, -35126.0), (8.86, 178.82))


# The PlayerStart (task MTNVIEW): the carrier's eye about 2.5 m over the road start. The summit is
# 3.3 km away at yaw -176.6, and only ~550 m above the camera, so the dust haze must fall off fast
# with height (halving every ~70 m) for the summit to stand out of it.
SPAWN_POSE = ((616580.0, 463550.0, -35412.0), (4.0, -155.0))


def ground_transmittance(key_name="Valley", pose=SPAWN_POSE, dist_m=1000.0, yaws=(-130.0, -150.0, -100.0, 160.0)):
    """Mean transmittance from the camera to the ground (1 m up) at dist_m, over a few headings:
    how far the dust haze has swallowed the land at that distance."""
    from build_road_profile import Terrain, HEIGHTMAP
    key, layers, fog, cam, _p, _y, _b = title_setup(key_name, 0.0, pose)
    terrain = Terrain(HEIGHTMAP)
    out = []
    for yaw in yaws:
        x = cam[0] + math.cos(math.radians(yaw)) * dist_m * 100.0
        y = cam[1] + math.sin(math.radians(yaw)) * dist_m * 100.0
        pt = (x, y, float(terrain.height(x, y)) * 100.0 + 100.0)
        out.append(float(transmittance(cam, pt, layers, fog["start_cm"], fog["max_opacity"], fog["cutoff_cm"])))
    return float(np.mean(out))


def title_setup(key_name="Valley", t=0.0, pose=None):
    import apply_look
    import build_title_sequence as bts
    key = apply_look.find_key(apply_look.load_keys(), key_name)
    layers = layers_from_key(key, apply_look.SECOND_FOG_FALLOFF)
    pos, (pitch, yaw) = pose or bts.pose_at(t)
    fog = {"start_cm": key["fog"]["start_m"] * 100.0,
           "max_opacity": key["fog"].get("max_opacity", apply_look.FOG_MAX_OPACITY),
           "cutoff_cm": key["fog"].get("cutoff_m", 0.0) * 100.0}
    return key, layers, fog, pos, pitch, yaw, bts


def report(key_name="Valley", t=0.0, pose=None):
    from build_road_profile import Terrain, HEIGHTMAP, SUMMIT_HINT_CM
    key, layers, fog, cam, pitch, yaw, bts = title_setup(key_name, t, pose)
    terrain = Terrain(HEIGHTMAP)
    sx, sy, sz_m = terrain.peak_near(*SUMMIT_HINT_CM)
    floor_m = float(terrain.height(cam[0], cam[1]))

    def T(pt):
        return float(transmittance(cam, pt, layers, fog["start_cm"], fog["max_opacity"], fog["cutoff_cm"]))

    # points on the camera-facing side of the mountain, on the line camera -> summit
    dx, dy = sx - cam[0], sy - cam[1]
    n = math.hypot(dx, dy)
    ts = np.linspace(0.0, 1.0, 2001)
    xs, ys = cam[0] + dx * ts, cam[1] + dy * ts
    zs = terrain.height(xs, ys)
    base_i = int(np.nonzero(zs > floor_m + 10.0)[0][0])  # where the mountain leaves the valley floor
    base_m = float(zs[base_i])

    def on_face(z_m):
        i = base_i + int(np.nonzero(zs[base_i:] >= z_m)[0][0])
        return (float(xs[i]), float(ys[i]), z_m * 100.0), float(n * ts[i] / 100.0)

    mid_m = (base_m + sz_m) / 2.0
    out = {"key": key_name, "t": t, "camera_z_m": round(cam[2] / 100.0, 1), "valley_floor_m": round(floor_m, 1),
           "mountain_base_m": round(base_m, 1), "summit_m": round(sz_m, 1), "mid_height_m": round(mid_m, 1),
           "layers": layers, "fog": fog}
    pts = {"summit_minus_20m": sz_m - 20.0, "upper_quarter": base_m + 0.75 * (sz_m - base_m),
           "mid_height": mid_m, "lower_quarter": base_m + 0.25 * (sz_m - base_m), "base_plus_20m": base_m + 20.0}
    for name, z in pts.items():
        p, dist = on_face(z)
        out[f"T_{name}"] = round(T(p), 3)
        out[f"dist_{name}_m"] = round(dist, 0)
    floor_pt = (cam[0] + dx * 0.6, cam[1] + dy * 0.6, float(terrain.height(cam[0] + dx * 0.6, cam[1] + dy * 0.6)) * 100.0)
    out["T_valley_floor_60pct"] = round(T(floor_pt), 3)
    out["top_m"] = fog_top_m(layers, floor_m)
    for d_m in (100, 300, 1000, 3000):
        out[f"T_level_{d_m}m"] = round(T((cam[0] + dx / n * d_m * 100, cam[1] + dy / n * d_m * 100, cam[2])), 3)
    return out


def render(path, key_name="Valley", t=0.0, w=384, h=216):
    from PIL import Image
    from build_road_profile import Terrain, HEIGHTMAP
    key, layers, fog, cam, pitch, yaw, bts = title_setup(key_name, t)
    terrain = Terrain(HEIGHTMAP)
    hit, dirs = trace_view(terrain, cam, pitch, yaw, bts.hfov_deg(bts.lens_at(t)), w, h)
    sky = np.isnan(hit[..., 0])
    far = np.asarray(cam) + dirs * 3.0e6  # the sky: a receiver 30 km out
    tgt = np.where(sky[..., None], far, hit)
    T = transmittance(np.broadcast_to(np.asarray(cam, float), tgt.shape), tgt, layers,
                      fog["start_cm"], fog["max_opacity"], fog["cutoff_cm"])
    # grey terrain (0.25) and sky (0.55) under a pale fog (0.75): only T is from the engine model
    base = np.where(sky, 0.55, 0.25)
    img = base * T + 0.75 * (1.0 - T)
    Image.fromarray((np.clip(img, 0, 1) * 255).astype(np.uint8), "L").save(path)
    return {"png": str(path), "terrain_pixels": int((~sky).sum())}


def blend_key_fog(keys, road_m):
    """The fog of the keys blended at road_m, linear by road metre (as USaskartaLightingDirector).
    The director blends only these five numbers (and the colour); second_falloff, max_opacity, the
    directional inscattering and the volumetric fog are the level's, saved by apply_look, so they are
    taken from the lower key (every key carries the same values)."""
    ks = sorted(keys, key=lambda k: float(k["road_m"]))
    if road_m <= ks[0]["road_m"]:
        return dict(ks[0]["fog"])
    for a, b in zip(ks, ks[1:]):
        if road_m <= b["road_m"]:
            t = (road_m - a["road_m"]) / float(b["road_m"] - a["road_m"])
            out = dict(a["fog"])
            for n in ("density", "falloff", "start_m", "second_density", "second_height_m"):
                out[n] = a["fog"][n] + (b["fog"][n] - a["fog"][n]) * t
            return out
    return dict(ks[-1]["fog"])


# ----------------------------------------------------------------------------- FOG3
# User, 2026-09-28: "the fog shouldn't be dense, it should be close to the player, but not dense,
# especially for objects that are very high". FOG2's dust wall (T <= 0.15 by 80-300 m) became a thin
# ground-hugging veil (ca5c9482). FOG3 fix round 1 (verifier): that veil was too faint to notice (0.8-4.9 %
# at 50 m), its per-key fit bulged between keys, and on the climb its anchor rode just under the road, so
# the basin and the valley below filled with an opaque sea (the dust doubles every 25 m below its anchor).
# Two layers, each doing one job:
#   second layer = the DUST. It hugs the ground: halving every 20 m (Fog 3b: 14.3 m; FOG3_DUST_FALLOFF, the
#       level's second-layer falloff, the same in every key), so about 90 % of it lies in the first 60 m (47 m). Its
#       height (second_height_m, blended by the director) is anchored per key on the low ground under
#       the road (the road's lower envelope, _dust_anchors), so it pools in the dips and the basin, and
#       the crests and the ridge top stand above it. From Stair on (the climb) it stays on the basin
#       floor (the road's lowest ground) with FOG3_CLIMB_DUST_FROM's ground density: the carrier climbs
#       out of it, and the basin below keeps the thin layer it had from inside. Any anchor above the
#       basin floor would fill the basin with a sea, since the density keeps growing below the anchor.
#   main layer = the HAZE: the valley-wide aerial perspective from the fog actor (-420 m, the basin
#       floor), halving every 50 m on every key (one falloff, so the director's linear blend of the
#       densities cannot bulge between keys). The climb keys carry the last valley key's haze.
# The densities are a least-squares fit along the road (every FOG3_FIT_STEP_M, blended as the director
# does, the key metres weighted FOG3_KEY_WEIGHT) to the veil FOG3_PLAN asks for, not a fit at the key
# metres alone (that bulged between keys, where the carrier's height in the dust layer changes).
# Start 12 m (Fog 3b: 10 m), FogMaxOpacity 0.8 (the far ground keeps at least 20 % of its contrast).
# The physics limit: along a level ray the height fog is uniform, so T1000 = T50^26 (start 12 m; T50^24.75 at
# 10 m). A veil you notice at 50 m (>= 5 %) leaves flat ground at the carrier's height about 0.25 at 1 km and
# puts it on the 0.2 floor by 2 km; ground that rises out of the dust (the valley sides, the mountain) stays clearer.
# Near dust that thins with distance needs local volumes or particles, which height fog cannot do.
# Measured by targets(): level rays at the carrier's eye (road + 2.5 m) at 20-2,000 m, the top of a 40 m
# tower at 300 m, a ridge 400 m over the road at 2 km, the sky 30 deg up, the summit from the spawn and
# from road metre 2,300 (the storm peak) with the fog the director blends there, and terrain_ring(): the
# real ground at 300 / 1,000 / 2,000 m on 16 headings (the downhill views a level ray misses).
#
# FOG3B (2026-09-28, playtest: "we can't see distant mountains, and not enough dust effect and storm visible";
# the game still ran Fog 2). The Fog 3 veil (4.4-6.5 % at 50 m) was still too faint to notice, so the near
# dust roughly doubles: 8 % at the calm keys, 12-13 % at the storm keys, and up to ~25 % in the dust pools
# of the basin descent. The tall things must not pay for it (ridge 400 m up at 2 km >= 0.6 calm, >= 0.45
# storm; the summit >= 0.6 wherever it is in view). Three changes do that:
#   - the dust is steeper: it halves every 14.3 m (falloff 0.7), so a ray that rises out of it (a ridge, the
#     summit, the sky) crosses about as much dust as a 50 m level ray, and 95 % of the near veil is dust
#     (FOG3_DUST_SHARE; the haze, halving every 50 m, is what dimmed the summit);
#   - the fit aims at each key's veil AT the key's own road metre (FOG3_PLAN is that veil; the fit iterates
#     its aim, FOG3_AIM_ITERS), and rows where the blend overshoots (the dips between keys, where the road
#     falls below the straight line between the keys' heights and the dust pools) weigh FOG3_OVER_WEIGHT;
#   - the veil starts 10 m out (was 12).
# The price: along a level ray the height fog is uniform, so where the near veil is 12 % flat ground at 300 m
# keeps about 0.35 and the storm pools sit on the 0.2 floor by 300 m; and ground below the carrier (a dip, the
# basin seen from the ridge) holds exponentially more dust. More near dust than this has to come from the
# camera-centred storm shells (docs/look/STORM_SHELLS.md), which thin out by 200 m and never reach the ridge.

EYE_M = 2.5
GROUND_M = (20, 50, 150, 300, 1000, 2000)
PROFILE = ROOT / "docs" / "story" / "road-profile.json"
FOG3_DUST_FALLOFF = 0.7        # second layer, every key: density halves every 10 / 0.7 = 14.3 m (Fog 3: 0.5, 20 m)
FOG3_HAZE_FALLOFF = 0.2        # main layer, every key: halves every 50 m
FOG3_CLIMB_FROM_M = 3650.0     # Stair: the switchback climb out of the basin
FOG3_CLIMB_DUST_FROM = "Cistern"  # the climb keys' dust: this calm key's ground density, on the basin floor
FOG3_START_M = 10.0            # Fog 3b (Fog 3: 12)
FOG3_MAX_OPACITY = 0.8
FOG3_ENVELOPE_TOL_M = 2.0      # the blended dust anchor may sit at most this far above the road
FOG3_FIT_STEP_M = 10.0
FOG3_KEY_WEIGHT = 10.0         # a key's own road metre counts as this many fit rows (Fog 3: 5)
FOG3_OVER_WEIGHT = 4.0         # Fog 3b: a row whose fitted veil overshoots its aim weighs this much more
FOG3_IRLS_ITERS = 6            # reweighting passes for FOG3_OVER_WEIGHT
FOG3_AIM_ITERS = 8             # Fog 3b: passes that move the aim until every key lands on its plan veil
FOG3_DUST_SHARE = 0.95         # Fog 3b: the dust's share of the near veil at every key (Fog 3: 0.35-0.8)
# Fog 3b: key -> (veil at 50 m = 1 - T50 at the carrier's eye AT the key's own road metre, the dust's share).
# Act I and the cistern 8 % (the calm keys: dusty near the ground), the storm keys 12 % (Ridge, BasinHold) and
# 13 % (BasinPeak, the storm peak). 13-14 % at the storm keys pushed the ridge seen from the basin dip at road
# metre 2,400 under 0.45 (0.42 / 0.40), so the storm's extra near dust is the storm shells' job. Between keys
# the veil follows the road: thinner on the crests (the ridge climb and top stand above the dust), thicker in
# the dips (up to ~25 % in the basin descent, 17 % in Act I's dip at 1,100-1,200 m). The climb keys (Stair
# on) are derived, see above.
FOG3_PLAN = {
    "Valley": (0.08, FOG3_DUST_SHARE), "ValleyHold": (0.08, FOG3_DUST_SHARE), "Ridge": (0.12, FOG3_DUST_SHARE),
    "BasinPeak": (0.13, FOG3_DUST_SHARE), "BasinHold": (0.12, FOG3_DUST_SHARE), "Cistern": (0.08, FOG3_DUST_SHARE),
    "CisternHold": (0.08, FOG3_DUST_SHARE),
}
LN2 = math.log(2.0)


def _profile():
    samples = json.loads(PROFILE.read_text(encoding="utf-8"))["samples"]
    return (np.array([s["dist_m"] for s in samples]), np.array([s["x_cm"] for s in samples]),
            np.array([s["y_cm"] for s in samples]), np.array([s["terrain_z_m"] for s in samples]))


def road_point(road_m):
    """The road's ground point (x, y, z in cm) at a road metre (docs/story/road-profile.json)."""
    d, x, y, z = _profile()
    return np.array([np.interp(road_m, d, x), np.interp(road_m, d, y), np.interp(road_m, d, z) * 100.0])


def summit_point():
    s = json.loads(PROFILE.read_text(encoding="utf-8"))["summit"]
    return np.array([s["x_cm"], s["y_cm"], s["z_m"] * 100.0])


def _fog_T(f, cam, tgt):
    import apply_look
    layers = layers_from_key({"fog": f}, apply_look.SECOND_FOG_FALLOFF)
    return float(transmittance(cam, tgt, layers, f["start_m"] * 100.0,
                               f.get("max_opacity", apply_look.FOG_MAX_OPACITY), f.get("cutoff_m", 0.0) * 100.0))


def targets(f, road_m, eye_m=EYE_M):
    """FOG3 transmittances for one fog block with the carrier's eye at road_m (see the FOG3 notes).
    Ground rays are level (the fog depends on height only, so the heading does not matter); the tower
    and the ridge stand on ground at the road's height; veil50 = 1 - T50, the near dust; half_m is where
    a level ray keeps half its contrast."""
    g = road_point(road_m)
    cam = g + np.array([0.0, 0.0, eye_m * 100.0])
    out = {"road_m": float(road_m), "z_m": round(float(g[2]) / 100.0, 1)}
    for d in GROUND_M:
        out[f"T{d}"] = round(_fog_T(f, cam, cam + np.array([d * 100.0, 0.0, 0.0])), 3)
    out["veil50"] = round(1.0 - _fog_T(f, cam, cam + np.array([5000.0, 0.0, 0.0])), 4)
    out["tower40_300"] = round(_fog_T(f, cam, g + np.array([30000.0, 0.0, 4000.0])), 3)
    out["ridge400_2k"] = round(_fog_T(f, cam, g + np.array([200000.0, 0.0, 40000.0])), 3)
    e = math.radians(30.0)
    out["sky30"] = round(_fog_T(f, cam, cam + np.array([5e5 * math.cos(e), 0.0, 5e5 * math.sin(e)])), 3)
    out["half_m"] = next((float(d) for d in np.arange(5.0, 3001.0, 5.0)
                          if _fog_T(f, cam, cam + np.array([d * 100.0, 0.0, 0.0])) <= 0.5), None)
    return out


RING_HEADINGS = np.radians(np.arange(0.0, 360.0, 22.5))  # 16 headings
RING_M = (300, 1000, 2000)
SUMMIT_IN_VIEW_TO_M = 2140.0  # road-profile.json: the summit is on the skyline from the boot point to here


def load_terrain():
    """The Gaea heightmap the landscape was built from (Tools/Story/build_road_profile.Terrain)."""
    from build_road_profile import Terrain, HEIGHTMAP
    return Terrain(HEIGHTMAP)


def terrain_ring(f, road_m, dist_m, terrain, eye_m=EYE_M):
    """(mean, min) transmittance from the carrier's eye to the real ground (+1 m) dist_m away on 16
    headings: the downhill views a level ray misses (ground below the dust anchor is denser than the
    carrier's air, so a dip or the basin below reads hazier). Occlusion is ignored."""
    import apply_look
    cam = road_point(road_m) + np.array([0.0, 0.0, eye_m * 100.0])
    xs = cam[0] + np.cos(RING_HEADINGS) * dist_m * 100.0
    ys = cam[1] + np.sin(RING_HEADINGS) * dist_m * 100.0
    tgt = np.stack([xs, ys, terrain.height(xs, ys) * 100.0 + 100.0], axis=-1)
    layers = layers_from_key({"fog": f}, apply_look.SECOND_FOG_FALLOFF)
    t = transmittance(np.broadcast_to(cam, tgt.shape), tgt, layers, f["start_m"] * 100.0,
                      f.get("max_opacity", apply_look.FOG_MAX_OPACITY), f.get("cutoff_m", 0.0) * 100.0)
    return round(float(t.mean()), 3), round(float(t.min()), 3)


def _with_rings(row, f, terrain):
    if terrain is not None:
        for d in RING_M:
            row[f"G{d}"] = terrain_ring(f, row["road_m"], d, terrain)
    return row


def summit_T(f, from_road_m, eye_m=EYE_M):
    cam = road_point(from_road_m) + np.array([0.0, 0.0, eye_m * 100.0])
    return round(_fog_T(f, cam, summit_point()), 3)


def summit_views(keys):
    """The two summit shots with the fog the director blends there: the spawn (CIN_01's whip-pan,
    3.3 km) and road metre 2,300 (the storm peak, 2.1 km)."""
    return {"spawn": summit_T(blend_key_fog(keys, 0.0), 0.0),
            "road2300": summit_T(blend_key_fog(keys, 2300.0), 2300.0)}


def key_table(keys, terrain=None):
    """One row per key, at its own road metre. summit_spawn / summit_2300 use that key's fog from those
    two cameras; they are None for a key whose road is more than 60 m above or below the camera (the
    director never applies it there). With a terrain, G300 / G1000 / G2000 are terrain_ring() (mean, min)."""
    rows = []
    z0, z23 = float(road_point(0.0)[2]) / 100.0, float(road_point(2300.0)[2]) / 100.0
    for k in sorted(keys, key=lambda k: float(k["road_m"])):
        r = {"name": k["name"], **targets(k["fog"], float(k["road_m"]))}
        r["summit_spawn"] = summit_T(k["fog"], 0.0) if abs(r["z_m"] - z0) <= 60.0 else None
        r["summit_2300"] = summit_T(k["fog"], 2300.0) if abs(r["z_m"] - z23) <= 60.0 else None
        rows.append(_with_rings(r, k["fog"], terrain))
    return rows


def road_report(step_m=100.0, keys=None, terrain=None):
    """The blended fog along the road, every step_m: targets() at each road metre, the summit where it is
    in view (road metre <= SUMMIT_IN_VIEW_TO_M, else None) and, with a terrain, the terrain rings."""
    import apply_look
    keys = keys or apply_look.load_keys()
    d, _x, _y, _z = _profile()
    rows = []
    for m in np.arange(0.0, d[-1] + 1.0, step_m):
        f = blend_key_fog(keys, float(m))
        r = targets(f, float(m))
        r["summit"] = summit_T(f, float(m)) if m <= SUMMIT_IN_VIEW_TO_M else None
        rows.append(_with_rings(r, f, terrain))
    return rows


def _dust_anchors(km, zk, tol=FOG3_ENVELOPE_TOL_M):
    """Per-key anchor heights (m) whose road-metre blend stays under the road (its lower envelope,
    within tol): the dust layer's height, so the director's linear blend never sinks the road into it."""
    d, _x, _y, z = _profile()
    ms = np.arange(0.0, d[-1] + 1.0, 10.0)
    zs = np.interp(ms, d, z)
    a = np.array(zk, dtype=float)
    # before the first key and past the last the director holds that key: its anchor stays under that stretch too
    a[0] = min(a[0], float(zs[ms <= km[0]].min()) + tol)
    a[-1] = min(a[-1], float(zs[ms >= km[-1]].min()) + tol)
    for _ in range(5000):
        worst = 0.0
        for i in range(len(km) - 1):
            sel = (ms >= km[i]) & (ms <= km[i + 1])
            t = (ms[sel] - km[i]) / (km[i + 1] - km[i])
            v = (1.0 - t) * a[i] + t * a[i + 1] - zs[sel] - tol
            j = int(np.argmax(v))
            if v[j] > 1e-4:
                w0, w1 = 1.0 - t[j], t[j]
                n = w0 * w0 + w1 * w1
                a[i] -= v[j] * w0 / n
                a[i + 1] -= v[j] * w1 / n
                worst = max(worst, float(v[j]))
        if worst <= 1e-4:
            break
    return a


def _sig(n):
    return float(f"{n:.4g}")


def _blend_weights(km, m):
    """Each key's weight in the director's linear blend at road metre m (it holds the end keys past them)."""
    w = np.zeros(len(km))
    if m <= km[0]:
        w[0] = 1.0
    elif m >= km[-1]:
        w[-1] = 1.0
    else:
        i = int(np.searchsorted(km, m)) - 1
        t = (m - km[i]) / (km[i + 1] - km[i])
        w[i], w[i + 1] = 1.0 - t, t
    return w


def _fit_rows(keys):
    """The fit's fixed geometry: sorted keys, their metres, the dust anchors, the climb mask, and per fit row
    (every FOG3_FIT_STEP_M up to the last valley key) the blend weights and the carrier's eye height (m)."""
    import copy
    ks = sorted(copy.deepcopy(keys), key=lambda k: float(k["road_m"]))
    km = np.array([float(k["road_m"]) for k in ks])
    zk = [float(road_point(m)[2]) / 100.0 for m in km]
    anchors = np.array(_dust_anchors(list(km), zk), dtype=float)
    climb = km >= FOG3_CLIMB_FROM_M
    anchors[climb] = np.minimum(anchors[climb], float(_profile()[3].min()))  # the basin floor
    ms = np.arange(0.0, km[~climb][-1] + 1e-6, FOG3_FIT_STEP_M)
    W = np.array([_blend_weights(km, m) for m in ms])
    d, _x, _y, z = _profile()
    eye = np.interp(ms, d, z) + EYE_M
    return ks, km, anchors, climb, ms, W, eye


def _fit_layer(A, base_w):
    """Least squares A x = 1 (each row: the layer's extinction at the eye over its aim), reweighted so rows that
    overshoot their aim (the dips, where the dust pools) weigh FOG3_OVER_WEIGHT more (Fog 3b)."""
    wt = base_w.copy()
    x = None
    for _ in range(max(FOG3_IRLS_ITERS, 1)):
        x = np.linalg.lstsq(A * wt[:, None], wt, rcond=None)[0]
        wt = base_w * np.where(A @ x > 1.0, FOG3_OVER_WEIGHT, 1.0)
    return x


def _fit_once(rows, aim):
    """One fit of both layers' key densities to `aim` (key -> (veil at 50 m, dust share), linear between keys)."""
    ks, km, anchors, climb, ms, W, eye = rows
    names = [k["name"] for k in ks]
    free = ~climb
    fog_z = FOG_ACTOR_Z_CM / 100.0
    free_names = [n for n, c in zip(names, climb) if not c]
    sigma = np.array([-math.log2(1.0 - aim[n][0]) / (50.0 - FOG3_START_M) for n in free_names])
    share = np.array([aim[n][1] for n in free_names])
    sig = np.interp(ms, km[free], sigma)
    sh = np.interp(ms, km[free], share)
    a_dust = W * (LN2 / 10.0 * 2.0 ** (-FOG3_DUST_FALLOFF / 10.0 * (eye - W @ anchors)) / (sh * sig))[:, None]
    a_haze = W * (LN2 / 10.0 * 2.0 ** (-FOG3_HAZE_FALLOFF / 10.0 * (eye - fog_z)) / ((1.0 - sh) * sig))[:, None]
    # the key metres weigh FOG3_KEY_WEIGHT rows, so each key holds its own veil and the stretches between trade
    base_w = np.where(np.isin(ms, km[free]), FOG3_KEY_WEIGHT, 1.0)
    dust = np.zeros(len(ks))
    haze = np.zeros(len(ks))
    dust[free] = _fit_layer(a_dust[:, free], base_w)
    haze[free] = _fit_layer(a_haze[:, free], base_w)
    if (dust[free] <= 0).any() or (haze[free] <= 0).any():
        raise SystemExit(f"FOG3 fit: a key density came out <= 0 (dust {dust}, haze {haze}); change FOG3_PLAN")
    dust[climb] = dust[names.index(FOG3_CLIMB_DUST_FROM)]
    haze[climb] = haze[int(np.nonzero(free)[0][-1])]
    import copy
    out = copy.deepcopy(ks)
    for i, k in enumerate(out):
        k["fog"].update({"density": _sig(haze[i]), "falloff": FOG3_HAZE_FALLOFF, "start_m": FOG3_START_M,
                         "second_density": _sig(dust[i]),
                         # rounded down, so the blended anchor never rises past the tolerance over the road
                         "second_height_m": math.floor(round((anchors[i] - fog_z) * 10.0, 6)) / 10.0,
                         "second_falloff": FOG3_DUST_FALLOFF, "max_opacity": FOG3_MAX_OPACITY})
        k["fog"].pop("visibility_m", None)
    return out


def fit_keys(keys, plan=None):
    """FOG3 / FOG3B: every key's fog block (returns new keys; look_keys.json holds the result).
    A layer's key density D gives extinction D x ln2 / 10 x 2^(-falloff / 10 x (z - anchor)) per metre (log2
    units: T = 2^-(sigma x metres)); a veil v at 50 m is sigma = -log2(1 - v) / (50 - start). What the
    director blends is linear in the densities, so each layer is a least-squares fit, every FOG3_FIT_STEP_M
    up to the last valley key, of its extinction at the carrier's eye to an aim veil and share (linear
    between keys; relative error; overshooting rows reweighted, _fit_layer). Fog 3b: the aim starts at
    FOG3_PLAN and moves, FOG3_AIM_ITERS times, until the fitted veil at each key's own road metre is the
    plan's (the dips and crests between keys pull the least-squares key values off the aim). The climb keys
    are derived (see the FOG3 notes)."""
    plan = plan or FOG3_PLAN
    rows = _fit_rows(keys)
    ks, km, _a, climb = rows[0], rows[1], rows[2], rows[3]
    free_names = [k["name"] for k, c in zip(ks, climb) if not c]
    aim = {n: tuple(plan[n]) for n in free_names}
    fitted = _fit_once(rows, aim)
    for _ in range(FOG3_AIM_ITERS):
        got = {k["name"]: 1.0 - _fog_T(k["fog"], road_point(float(k["road_m"])) + np.array([0.0, 0.0, EYE_M * 100.0]),
                                       road_point(float(k["road_m"])) + np.array([5000.0, 0.0, EYE_M * 100.0]))
               for k in fitted if k["name"] in aim}
        aim = {n: (min(0.6, aim[n][0] * (plan[n][0] / max(got[n], 1e-4)) ** 0.8), aim[n][1]) for n in aim}
        fitted = _fit_once(rows, aim)
    return fitted


def dump_keys(keys):
    """look_keys.json's layout: one key per line."""
    return "[\n" + ",\n".join("  " + json.dumps(k) for k in keys) + "\n]\n"


TABLE_COLS = ["T20", "T50", "T150", "T300", "T1000", "T2000", "tower40_300", "ridge400_2k", "summit_spawn",
              "summit_2300", "sky30"]


def print_key_table(keys, terrain=None):
    rings = [f"G{d}" for d in RING_M] if terrain is not None else []
    print("| Key | road m | z m | veil50 % | " + " | ".join(TABLE_COLS + [f"{g} mean / min" for g in rings]) + " | half m |")
    print("|---|---|---|---|" + "---|" * (len(TABLE_COLS) + len(rings) + 1))
    for r in key_table(keys, terrain):
        cells = [f"{r[c]:.2f}" if r[c] is not None else "n/a" for c in TABLE_COLS]
        cells += [f"{r[g][0]:.2f} / {r[g][1]:.2f}" for g in rings]
        half = f"{r['half_m']:.0f}" if r["half_m"] is not None else "> 3000"
        print(f"| {r['name']} | {r['road_m']:.0f} | {r['z_m']:.0f} | {100 * r['veil50']:.1f} | " + " | ".join(cells) + f" | {half} |")
    v = summit_views(keys)
    print(f"\nsummit, blended as the director does: from the spawn {v['spawn']:.2f}, from road 2,300 m {v['road2300']:.2f}")


# Road stretches for the blended summary (road-profile.md zones; the basin storm is BasinPeak..BasinHold).
STRETCHES = [("Act I, valley floor", 0.0, 1450.0), ("Ridge climb and top", 1450.0, 2150.0),
             ("Basin storm", 2150.0, 2700.0), ("Basin floor to the mountain foot", 2700.0, 3650.0),
             ("Climb and summit approach", 3650.0, 5009.2)]
STRETCH_COLS = ["veil50", "T300", "T1000", "tower40_300", "ridge400_2k", "sky30"]


def print_stretches(keys, terrain=None, step_m=25.0):
    rows = road_report(step_m, keys, terrain)
    cols = STRETCH_COLS + (["G300 min", "G1000 mean"] if terrain is not None else [])

    def val(r, c):
        if c == "G300 min":
            return r["G300"][1]
        if c == "G1000 mean":
            return r["G1000"][0]
        return 100.0 * r[c] if c == "veil50" else r[c]
    print("| Stretch | road m | " + " | ".join(cols) + " |")
    print("|---|---|" + "---|" * len(cols))
    for name, a, b in STRETCHES:
        sel = [r for r in rows if a <= r["road_m"] <= b]
        cells = []
        for c in cols:
            lo, hi = min(val(r, c) for r in sel), max(val(r, c) for r in sel)
            fmt = "{:.1f}" if c == "veil50" else "{:.2f}"
            cells.append(fmt.format(lo) + ("" if fmt.format(lo) == fmt.format(hi) else "-" + fmt.format(hi))
                         + (" %" if c == "veil50" else ""))
        print(f"| {name} | {a:.0f}-{b:.0f} | " + " | ".join(cells) + " |")
    s = [r["summit"] for r in rows if r["summit"] is not None]
    print(f"\nsummit from every road metre it is in view (0-{SUMMIT_IN_VIEW_TO_M:.0f}): {min(s):.2f}-{max(s):.2f}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("step", choices=["report", "render", "road", "table", "stretches", "fit"])
    ap.add_argument("out", nargs="?")
    ap.add_argument("--key", default="Valley")
    ap.add_argument("--t", type=float, default=0.0)
    ap.add_argument("--keys", help="look_keys.json to read (default Tools/Look/look_keys.json)")
    ap.add_argument("--write", action="store_true", help="fit: write the fitted fog back into the keys file")
    ap.add_argument("--terrain", action="store_true",
                    help="table / stretches / road / fit: add the terrain rings (the Gaea heightmap)")
    a = ap.parse_args(argv)
    import apply_look
    keys_path = a.keys or str(apply_look.KEYS_PATH)
    terrain = load_terrain() if a.terrain else None
    if a.step == "road":
        for r in road_report(keys=apply_look.load_keys(keys_path), terrain=terrain):
            print(json.dumps(r))
        return 0
    if a.step == "table":
        print_key_table(apply_look.load_keys(keys_path), terrain)
        return 0
    if a.step == "stretches":
        print_stretches(apply_look.load_keys(keys_path), terrain)
        return 0
    if a.step == "fit":
        fitted = fit_keys(apply_look.load_keys(keys_path))
        if a.write:
            pathlib.Path(keys_path).write_text(dump_keys(fitted), encoding="utf-8")
        print_key_table(fitted, terrain)
        return 0
    if a.step == "report":
        print(json.dumps(report(a.key, a.t), indent=1))
    else:
        print(json.dumps(render(a.out or "fog_model.png", a.key, a.t)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
