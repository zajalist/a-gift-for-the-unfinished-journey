"""Storm shells, the offline model (task STORM-SHELLS): the material defaults and a numpy port of
Shaders/StormShells.ush.

PARAMS is the single source of truth for M_PP_Saskarta_StormShells' parameter defaults; the editor builder
(build_storm_shells_material.py) reads it, and so does the preview (preview_storm_shells.py). The functions
below mirror the shader line by line, so the preview and the tests check the same math the GPU runs, on the
same noise texels: the volume comes from storm_dust_noise.py, which also writes the atlas the editor turns into
VT_Saskarta_StormDust, and `mip_chain` builds the box-filtered mips the engine builds for it.

The fog inputs (Haze, HazeDir, FogA, FogB) are written at run time by USaskartaStormShellsSubsystem from the
level's ExponentialHeightFog (SaskartaStormShellsLogic.cpp MakeFogParams); `fog_inputs_from_key` computes the
same numbers from a look key, and the defaults below are the Valley key's (what the editor viewport shows
before the subsystem runs).

Recipe and sources: docs/look/STORM_SHELLS.md.
"""
from __future__ import annotations

import json
import pathlib

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
LOOK_KEYS = HERE.parent / "look_keys.json"   # read only (the fog lane owns it)
FOG_ACTOR_Z_M = -420.0                       # the level's ExponentialHeightFog actor (fog_model.FOG_ACTOR_Z_CM)
FOG_LUMINANCE_SCALE = 0.08                   # apply_look / the lighting director: a key without "luminance"


def srgb_hex_to_linear(hx):
    hx = hx.lstrip("#")
    c = np.array([int(hx[i:i + 2], 16) for i in (0, 2, 4)], dtype=np.float64) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def fog_inputs(density, falloff, fog_z_m, second_density, second_falloff, second_offset_m, start_m, max_opacity):
    """The material's FogA / FogB from the fog component's values (as SaskartaStormShells::MakeFogParams):
    FogDensity / 1000 per cm = FogDensity / 10 per m, FogHeightFalloff / 1000 per cm = / 10 per m."""
    fog_a = (density / 10.0, falloff / 10.0, second_density / 10.0, second_falloff / 10.0)
    fog_b = (fog_z_m, fog_z_m + second_offset_m, start_m, max_opacity)
    return fog_a, fog_b


def fog_inputs_from_key(key, second_falloff=None):
    """Haze, HazeDir, FogA, FogB for a look key (fog block as in look_keys.json), as the level shows it."""
    f = key["fog"]
    lum = float(f.get("luminance", FOG_LUMINANCE_SCALE))
    haze = srgb_hex_to_linear(f["color"]) * lum
    hdir = srgb_hex_to_linear(f.get("dir_color", "#000000")) * lum
    sf = f.get("second_falloff", 0.5 if second_falloff is None else second_falloff)
    fog_a, fog_b = fog_inputs(f["density"], f["falloff"], FOG_ACTOR_Z_M, f["second_density"], sf,
                              f["second_height_m"], f["start_m"], f.get("max_opacity", 0.8))
    return {"Haze": (*[round(float(v), 5) for v in haze], float(f.get("dir_exponent", 8.0))),
            "HazeDir": (*[round(float(v), 5) for v in hdir], 0.0),
            "FogA": tuple(round(v, 6) for v in fog_a), "FogB": tuple(round(v, 3) for v in fog_b)}


def look_key(name):
    return next(k for k in json.loads(LOOK_KEYS.read_text(encoding="utf-8")) if k["name"] == name)


# ---------------------------------------------------------------- material parameter defaults
# Vector parameters (x, y, z, w). Keep the comments in step with the input list in Shaders/StormShells.ush.
PARAMS = {
    "Radii": (30.0, 55.0, 90.0, 150.0),        # where each shell's dust is sampled, m (angular drift 5 : 2.7 : 1.7 : 1)
    "Edges": (8.0, 185.0, 0.5, 1.0),           # first slab's inner edge m, last slab's outer edge m, storm response exp, storm scale
    "Speed": (1.0, 1.0, 1.0, 1.0),             # one coherent world-space drift (angular parallax comes from radii)
    "Band": (1.2, 14.0, 45.0, 160.0),          # eye height m, halving m, top m, depth below m
    "Wind": (1.0, 0.35, 12.0, 0.35),           # dir xy (the dust volume's), speed m/s, gust amplitude
    "Gust": (7.0, 1500.0, 35.0, 0.5),          # period s, front spacing m, front speed m/s, front contrast
    "Shape": (160.0, 64.0, 36.0, 0.47),        # m per noise tile along the wind / across / vertical, coverage threshold
    "Dens": (0.0055, 0.2, 2.0, 0.35),          # sigma 1/m (thickest dust, storm 1), coverage softness, max path factor, max alpha
    "Tone": (1.0, 0.3, 0.45, 0.6),             # thin shade, thick darkening, relief (lit tops / shaded bellies), clump strength
    "Tint": (1.08, 0.97, 0.84, 1.0),           # the dust's colour relative to the fog's (a little warmer)
    "Wisp": (0.45, 1.35, 3.1, 0.6),            # wisp strength, drift vs the body, frequency vs the body, domain warp
    # Fog inputs: the Valley key's (look_keys.json, read at build time); the subsystem overwrites them each tick.
    "Haze": (0.04091, 0.02528, 0.008, 8.0),    # the fog's inscattering luminance (absolute linear), dir exponent
    "HazeDir": (0.10712, 0.05041, 0.01011, 0.0),  # the fog's directional inscattering luminance
    "FogA": (0.000629, 0.02, 0.006537, 0.07),  # density 1/m at its height and falloff 1/m, both fogs
    "FogB": (-420.0, -364.8, 10.0, 0.8),       # fog height m, second fog height m, start m, max opacity
    "Tier": (4.0, 2.0, 0.0, 0.0),              # shells drawn, shells with the wisp octave (nearest first; the subsystem sets it)
}
try:   # the fog defaults follow the Valley key as it is now (the fog lane retunes it); the values above if unreadable
    PARAMS.update(fog_inputs_from_key(look_key("Valley")))
except (OSError, ValueError, KeyError, StopIteration):
    pass
VECTOR_PARAMS = list(PARAMS)
FOG_PARAMS = ("Haze", "HazeDir", "FogA", "FogB")   # written at run time by the subsystem

# Tiers (docs/look/STORM_SHELLS.md section 9): Low drops the 150 m shell and keeps the wisps on the 30 m shell.
TIERS = {"high": (4, 2), "low": (3, 1), "off": (0, 0)}

GATE_OFF_BELOW = 0.005   # the subsystem's hysteresis on StormIntensity (weight 0 below, 1 above ON)
GATE_ON_ABOVE = 0.015
TAU = 6.2831853
LOG2E = 1.442695


def p(name):
    return np.asarray(PARAMS[name], dtype=np.float64)


# ---------------------------------------------------------------- the pieces, as in the shader
def far_root_centered(d, R, min_xy=1e-3):
    """t where the ray from the axis leaves a vertical cylinder of radius R (the only root ahead)."""
    dxy = np.maximum(np.hypot(d[..., 0], d[..., 1]), min_xy)
    return R / dxy


def far_root_offset(o_xy, d, R):
    """The general root (Quilez): camera at o_xy from the axis, still inside (|o| < R)."""
    a = d[..., 0] ** 2 + d[..., 1] ** 2
    b = o_xy[0] * d[..., 0] + o_xy[1] * d[..., 1]
    c = o_xy[0] ** 2 + o_xy[1] ** 2 - R * R
    return (-b + np.sqrt(b * b - a * c)) / np.maximum(a, 1e-12)


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def height_profile(h, band=None):
    band = p("Band") if band is None else band
    return (np.exp2(-np.maximum(h, 0.0) / band[1])
            * (1.0 - smoothstep(0.6 * band[2], band[2], h))
            * smoothstep(-band[3], -0.5 * band[3], h))


def slab_edges(radii=None, edges=None):
    """The 5 edges of the 4 contiguous slabs: inner edge, midpoints between the radii, outer edge (m)."""
    r = p("Radii") if radii is None else np.asarray(radii, dtype=np.float64)
    e = p("Edges") if edges is None else np.asarray(edges, dtype=np.float64)
    return np.array([e[0], 0.5 * (r[0] + r[1]), 0.5 * (r[1] + r[2]), 0.5 * (r[2] + r[3]), e[1]])


def slab_length(scene_xy, i, radii=None, edges=None):
    """Horizontal metres of slab i in front of a scene point scene_xy metres away (horizontally)."""
    b = slab_edges(radii, edges)
    return np.clip(scene_xy - b[i], 0.0, b[i + 1] - b[i])


def slab_profiled_length(scene_xy, elevation, i, band=None, radii=None, edges=None):
    """Height-weighted visible slab length, using the shader's three-point Simpson rule."""
    b = slab_edges(radii, edges)
    length = slab_length(scene_xy, i, radii, edges)
    band = p("Band") if band is None else np.asarray(band, dtype=np.float64)
    h0 = b[i] * elevation + band[0]
    hm = (b[i] + 0.5 * length) * elevation + band[0]
    h1 = (b[i] + length) * elevation + band[0]
    return length * (height_profile(h0, band) + 4.0 * height_profile(hm, band)
                     + height_profile(h1, band)) / 6.0


def gust(time_s, period=None):
    P1 = max(PARAMS["Gust"][0] if period is None else period, 0.1)
    P2 = P1 * 1.618
    return 0.65 * np.sin(TAU * time_s / P1) + 0.35 * np.sin(TAU * time_s / P2 + 1.7)


def gust_integral(time_s, period=None):
    P1 = max(PARAMS["Gust"][0] if period is None else period, 0.1)
    P2 = P1 * 1.618
    return -0.65 * P1 / TAU * np.cos(TAU * time_s / P1) - 0.35 * P2 / TAU * np.cos(TAU * time_s / P2 + 1.7)


def drift_m(time_s, wind=None, period=None):
    """Metres downwind the field has moved: V (t + A G(t)); d/dt = V (1 + A g(t)), the gusting speed."""
    wind = p("Wind") if wind is None else wind
    return wind[2] * (time_s + wind[3] * gust_integral(time_s, period))


def storm_response(storm_intensity, edges=None):
    e = p("Edges") if edges is None else edges
    return float(np.clip(storm_intensity, 0.0, 1.0)) ** max(e[2], 0.05) * e[3]


def layer_alpha(storm, length_m, path_k, n, gust_k, prof, sigma=None, max_alpha=None):
    """One shell's opacity: 1 - exp(-sigma * storm * pathK * gust * n * prof * length), capped at Dens.w."""
    sigma = PARAMS["Dens"][0] if sigma is None else sigma
    max_alpha = PARAMS["Dens"][3] if max_alpha is None else max_alpha
    tau = sigma * storm * path_k * gust_k * n * prof * length_m
    return 1.0 - np.exp2(-np.minimum(LOG2E * tau, -np.log2(1.0 - min(max(max_alpha, 0.0), 1.0) * 0.999)))


def fog_transmittance(ray_m, dz_m, cam_z_m, fog_a=None, fog_b=None):
    """Height-fog transmittance over the first ray_m metres of a ray rising dz_m over them, from a camera at
    cam_z_m: HeightFogCommon.ush's line integral (both layers, start distance, max opacity), in metres."""
    A = p("FogA") if fog_a is None else np.asarray(fog_a, dtype=np.float64)
    B = p("FogB") if fog_b is None else np.asarray(fog_b, dtype=np.float64)
    ray_m = np.asarray(ray_m, dtype=np.float64)
    dz_rate = np.asarray(dz_m, dtype=np.float64) / np.maximum(ray_m, 1e-6)       # d.z
    z0 = cam_z_m + B[2] * dz_rate
    o1 = A[0] * np.exp2(-np.clip(A[1] * (z0 - B[0]), -127, 127))
    o2 = A[2] * np.exp2(-np.clip(A[3] * (z0 - B[1]), -127, 127))
    rl = np.maximum(ray_m - B[2], 0.0)
    out = 0.0
    for o, k in ((o1, A[1]), (o2, A[3])):
        f = k * rl * dz_rate
        small = np.abs(f) <= 1e-4
        r = np.where(small, 0.6931472 - 0.2402265 * f, (1.0 - np.exp2(-f)) / np.where(small, 1.0, f))
        out = out + o * r
    return np.maximum(np.exp2(-out * rl), 1.0 - np.clip(B[3], 0.0, 1.0))


def dust_relative(n, relief, fog_t, tone=None, tint=None):
    """The dust's radiance over the fog's in that direction: Tint * shade(n, relief), faded to 1 by the fog
    in front of it (fog_t = 1: no fog in front)."""
    tn = p("Tone") if tone is None else tone
    ti = p("Tint") if tint is None else tint
    shade = np.maximum(tn[0] - tn[1] * n + tn[2] * (2.0 * relief - 1.0), 0.0)
    return 1.0 + (ti[None, :3] * shade[..., None] - 1.0) * np.asarray(fog_t)[..., None]


# ---------------------------------------------------------------- the noise volume and SampleGrad
def load_noise():
    import storm_dust_noise
    return storm_dust_noise.load_volume()


def mip_chain(vol, levels=None):
    """Box-filtered mips, as the engine builds for a volume texture (vol: (nx, ny, nz, C) float; every axis
    halves until it reaches 1)."""
    mips = [np.ascontiguousarray(vol, dtype=np.float32)]
    while max(mips[-1].shape[:3]) > 1 and (levels is None or len(mips) < levels):
        v = mips[-1]
        f = [2 if n > 1 else 1 for n in v.shape[:3]]
        s = [n // k for n, k in zip(v.shape[:3], f)]
        mips.append(v.reshape(s[0], f[0], s[1], f[1], s[2], f[2], v.shape[3]).mean(axis=(1, 3, 5)))
    return mips


def _trilinear_wrap(vol, q):
    size = np.array(vol.shape[:3], dtype=np.float64)
    x = q * size - 0.5
    i0 = np.floor(x)
    f = (x - i0).astype(np.float32)
    i0 = i0.astype(np.int64) % size.astype(np.int64)
    i1 = (i0 + 1) % size.astype(np.int64)
    out = np.zeros(q.shape[:-1] + (vol.shape[3],), dtype=np.float32)
    for dx in (0, 1):
        ix = i1[..., 0] if dx else i0[..., 0]
        wx = f[..., 0] if dx else 1 - f[..., 0]
        for dy in (0, 1):
            iy = i1[..., 1] if dy else i0[..., 1]
            wxy = wx * (f[..., 1] if dy else 1 - f[..., 1])
            for dz in (0, 1):
                iz = i1[..., 2] if dz else i0[..., 2]
                wz = f[..., 2] if dz else 1 - f[..., 2]
                out += vol[ix, iy, iz] * (wxy * wz)[..., None]
    return out


def sample_grad(mips, q, qx, qy):
    """Texture3D.SampleGrad with a wrap, trilinear (isotropic) sampler: LOD from the larger gradient in texels
    (each axis scaled by its size), linear between the two nearest mips. Returns (..., C)."""
    size = np.array(mips[0].shape[:3], dtype=np.float64)
    rho = np.maximum(np.linalg.norm(qx * size, axis=-1), np.linalg.norm(qy * size, axis=-1))
    lod = np.clip(np.log2(np.maximum(rho, 1e-8)), 0.0, len(mips) - 1.0)
    out = np.zeros(q.shape[:-1] + (mips[0].shape[3],), dtype=np.float32)
    lo = np.floor(lod).astype(int)
    fr = (lod - lo).astype(np.float32)
    for level in range(len(mips)):
        for m_sel, wgt in ((lo == level, 1.0 - fr), (lo + 1 == level, fr)):
            m = m_sel & (wgt > 0)
            if m.any():
                out[m] += _trilinear_wrap(mips[level], q[m]) * wgt[m][:, None]
    return out, lod


def _ddxy(a):
    """Screen derivatives of an (H, W, C) array like a pixel quad's (coarse: one difference per 2x2 quad)."""
    dx = np.zeros_like(a)
    dy = np.zeros_like(a)
    dx[:, :-1] = a[:, 1:] - a[:, :-1]
    dx[:, -1] = dx[:, -2]
    if a.shape[1] % 2 == 0:
        dx[:, 1::2] = dx[:, 0::2]
    dy[:-1] = a[1:] - a[:-1]
    dy[-1] = dy[-2]
    if a.shape[0] % 2 == 0:
        dy[1::2] = dy[0::2]
    return dx, dy


# ---------------------------------------------------------------- the whole pass
def shells(scene, depth_view_m, d, fwd, cam_m, time_s, storm, mips, params=None, return_layers=False):
    """Composite the dust over `scene` (H, W, 3 linear, absolute like scene colour). d: (H, W, 3) unit view rays
    (world, camera -> pixel). depth_view_m: (H, W) view-space Z in metres (SceneDepth / 100). Mirrors
    StormShells.ush in mode 0 (Scene Color After DOF): returns scene * T + L.
    return_layers adds a dict: 'alpha' (4 per-shell alphas), 'n', 'lod' (body fetch LOD), 'fetched' (bool)."""
    P = {k: np.asarray(v, dtype=np.float64) for k, v in PARAMS.items()}
    if params:
        P.update({k: np.asarray(v, dtype=np.float64) for k, v in params.items()})
    Radii, Edges, Speed, Band, Wind, Gust, Shape, Dens, Tone, Tint, Wisp, Haze, HazeDir, FogA, FogB, Tier = (
        P[k] for k in ("Radii", "Edges", "Speed", "Band", "Wind", "Gust", "Shape", "Dens", "Tone", "Tint", "Wisp",
                       "Haze", "HazeDir", "FogA", "FogB", "Tier"))
    inv_dxy = 1.0 / np.sqrt(np.maximum(d[..., 0] ** 2 + d[..., 1] ** 2, 1e-6))
    e = d * inv_dxy[..., None]
    w = Wind[:2] + np.array([1e-4, 0.0])
    w = w / np.linalg.norm(w)
    wx = np.array([-w[1], w[0]])
    invS = 1.0 / Shape[:3]
    e_along = e[..., 0] * w[0] + e[..., 1] * w[1]
    qe = np.stack([e_along, e[..., 0] * wx[0] + e[..., 1] * wx[1], e[..., 2]], axis=-1) * invS
    qex, qey = _ddxy(qe)
    storm = storm_response(storm, Edges)
    scene_xy = depth_view_m / (np.maximum(np.einsum("hwc,c->hw", d, fwd), 1e-3) * inv_dxy)
    info = {"alpha": [], "n": [], "lod": [], "fetched": []}
    live = (storm > 1e-3) & (Tier[0] > 0.5) & (scene_xy > Edges[0]) & (Radii[0] * e[..., 2] + Band[0] < Band[2])
    T = np.ones(inv_dxy.shape)
    L = np.zeros(scene.shape)
    if not live.any():
        return (scene.copy(), info) if return_layers else scene.copy()
    g = gust(time_s, Gust[0])
    drift = Wind[2] * (time_s + Wind[3] * gust_integral(time_s, Gust[0]))
    cam_along = cam_m[0] * w[0] + cam_m[1] * w[1]
    qc = np.array([cam_along, cam_m[0] * wx[0] + cam_m[1] * wx[1], cam_m[2]]) * invS
    sun = np.asarray(P.get("SunDir", (0.0, 0.0, 1.0)), dtype=np.float64)
    lobe = np.maximum(np.clip(np.einsum("hwc,c->hw", d, sun), 0.0, 1.0), 1e-4) ** max(Haze[3], 1.0)
    haze_d = Haze[None, None, :3] + HazeDir[None, None, :3] * lobe[..., None]
    path_k = np.minimum(inv_dxy, Dens[2])
    sigma_k = LOG2E * Dens[0] * storm * (1.0 + Wind[3] * g) * path_k
    tau_max = -np.log2(1.0 - np.clip(Dens[3], 0.0, 1.0) * 0.999)
    edge = slab_edges(Radii, Edges)
    for i in range(4):
        R = Radii[i]
        k = slab_profiled_length(scene_xy, e[..., 2], i, Band, Radii, Edges)
        m = live & (k > 0.05) & (i < Tier[0])
        alpha = np.zeros(inv_dxy.shape)
        n_full = np.zeros(inv_dxy.shape)
        lod_full = np.full(inv_dxy.shape, np.nan)
        if m.any():
            qr = R * qe[m] + qc
            s, lod = sample_grad(mips, qr - np.array([drift * Speed[i] * invS[0], 0, 0]), R * qex[m], R * qey[m])
            body = s[:, 0].astype(np.float64)
            mm = body.copy()
            if i < Tier[1]:
                qd = Wisp[2] * (qr - np.array([drift * Speed[i] * Wisp[1] * invS[0], 0, 0])) + (body[:, None] - 0.5) * Wisp[3]
                sw, _ = sample_grad(mips, qd, Wisp[2] * R * qex[m], Wisp[2] * R * qey[m])
                mm += (sw[:, 1] - 0.5) * Wisp[0]
            c = np.clip((mm - Shape[3]) / max(Dens[1], 1e-3), 0.0, 1.0)
            n = c * c * (3.0 - 2.0 * c) * (1.0 - Tone[3] + Tone[3] * s[:, 2])
            along = cam_along + R * e_along[m]
            ph = np.mod((along - time_s * Gust[2]) / Gust[1] + body * 0.3, 1.0)
            front = smoothstep(0.0, 0.15, ph) * (1.0 - smoothstep(0.3, 0.6, ph))
            tau = np.minimum(sigma_k[m] * (1.0 - 0.5 * Gust[3] + 2.0 * Gust[3] * front) * n * k[m], tau_max)
            a = 1.0 - np.exp2(-tau)
            fog_t = fog_transmittance(np.maximum(R * inv_dxy[m], 1e-6), R * e[..., 2][m], cam_m[2], FogA, FogB)
            col = haze_d[m] * dust_relative(n, s[:, 3].astype(np.float64), fog_t, Tone, Tint)
            alpha[m] = a
            n_full[m] = n
            lod_full[m] = lod
            L[m] += (T[m] * a)[:, None] * col
            T[m] *= 1.0 - a
        info["alpha"].append(alpha)
        info["n"].append(n_full)
        info["lod"].append(lod_full)
        info["fetched"].append(m)
    out = scene * T[..., None] + L
    return (out, info) if return_layers else out
