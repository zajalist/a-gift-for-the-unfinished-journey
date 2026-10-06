"""A numpy port of Shaders/RoadRVT.hlsl, for the offline numeric checks (world sprint, V1b, ROADNOISE).

Every step mirrors the HLSL body line for line, vectorised over sample points, so the
tests can measure what the shader writes into the RVT: the road frame from the exact
polyline distance, the domain-warped slab cells, the decay field (missing stones,
crumbled patch edges, potholes and mud, cracks), burial, the dirt profile, the edge
coverage and the normal. Keep the two in step: a change to a constant in the HLSL must
be made here too (test_road_rvt.py cross-checks the key constants).

Positions are metres in the mask frame (world cm minus the mask origin, / 100), the
frame the HLSL's P input uses.
"""
import numpy as np

U32 = np.uint32
DIRT = np.array([0.130, 0.092, 0.066])
GRAVEL = np.array([0.145, 0.120, 0.096])
PAVING = np.array([0.140, 0.124, 0.104])
GRASS = np.array([0.080, 0.086, 0.046])

SLAB_PITCH = 0.9
SLAB_JITTER = 0.9
SLAB_WEIGHT = 0.0992
NOISE_SCALES = (5.0, 2.3, 0.06, 2.5, 0.9, 1.6, 0.35, 0.07, 0.45)
# noises 3 and 4 are sampled at the slab centre cW, the rest at the pixel q
SLAB_WARP = (3.0, 0.3)          # metres of the 15 m and the 3 m warp octaves on the slab lattice
DECAY_WARP = 1.1                # metres of the 3 m warp on the decay field
FBM = ((15.0, 14, 0.4), (3.0, 15, 0.35), (0.5, 16, 0.25))   # (scale m, noise id, weight)

# The decay and burial tuning, pasted into the HLSL as literals (see TUNING_TOKENS in
# the test). The names are the tokens the shader source uses in their place.
TUNING = dict(
    DEC_NEG=0.7, DEC_WEAR=0.25, DEC_RUT=0.12, DEC_VERGE=0.5, DEC_GONE=0.62, DEC_CHIP=0.66,
    BUR_NEG=0.2, BUR_OFF=0.09, PIT_LO=0.66, PIT_NEG=0.35, EDGE_AMP=0.7, EDGE_DEC=0.3,
)


def smoothstep(a, b, x):
    t = np.clip((x - a) / (b - a), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _mix(hc_x, hc_y, seed):
    with np.errstate(over="ignore"):
        hh = (hc_x * U32(73856093)) ^ (hc_y * U32(19349663)) ^ seed
        hh = (hh ^ (hh >> U32(16))) * U32(2246822519)
        hh = (hh ^ (hh >> U32(13))) * U32(3266489917)
        hh = hh ^ (hh >> U32(16))
    return hh


def _next(hh):
    with np.errstate(over="ignore"):
        hh = hh * U32(1664525) + U32(1013904223)
        return hh ^ (hh >> U32(15))


def _unit(hh):
    return (hh >> U32(8)).astype(np.float64) / 16777216.0


def _cellhash(c):
    return (c[..., 0].astype(np.int64) + 32768).astype(U32), (c[..., 1].astype(np.int64) + 32768).astype(U32)


def slab_jitter(c):
    """Jitter (jx, jy) and power weight of slab cell c (integer-valued float array, [..., 2])."""
    hx, hy = _cellhash(c)
    hh = _mix(hx, hy, U32(2166136261))
    jx = _unit(hh)
    hh = _next(hh)
    jy = _unit(hh)
    hh = _next(hh)
    jw = _unit(hh)
    return np.stack([jx, jy], -1), SLAB_WEIGHT * jw


def slab_site(c):
    """Jittered site (lattice space, metres) and power weight of slab cell c."""
    j, w = slab_jitter(c)
    return (c + 0.5 + SLAB_JITTER * (j - 0.5)) * SLAB_PITCH, w


def slab_props(c):
    """Per-slab dice: tone, exists, hue, crack, scatter, tilt (x, y)."""
    hx, hy = _cellhash(c)
    hq = _mix(hx, hy, U32(374761393))
    out = []
    for _ in range(7):
        out.append(_unit(hq))
        hq = _next(hq)
    r_tone, r_exist, r_hue, r_crack, r_scat, r_tx, r_ty = out
    return r_tone, r_exist, r_hue, r_crack, r_scat, np.stack([r_tx, r_ty], -1)


def value_noise(x, n):
    """Noise n at scaled positions x ([..., 2])."""
    ip = np.floor(x)
    fp = x - ip
    fp = fp * fp * (3.0 - 2.0 * fp)
    with np.errstate(over="ignore"):
        seed = U32(n) * U32(2654435761) + U32(12345)
    cv = []
    for m in range(4):
        corner = ip + np.array([m % 2, m // 2], dtype=np.float64)
        hx, hy = _cellhash(corner)
        cv.append(_unit(_mix(hx, hy, seed)))
    a = cv[0] + (cv[1] - cv[0]) * fp[..., 0]
    b = cv[2] + (cv[3] - cv[2]) * fp[..., 0]
    return a + (b - a) * fp[..., 1]


def warp3(x):
    return np.stack([value_noise(x / 3.0, 12), value_noise(x / 3.0, 13)], -1) - 0.5


def fbm(x):
    return sum(w * value_noise(x / s, n) for s, n, w in FBM)


def lattice_warp(p):
    """(slabW, decW) at points p: the slab-lattice warp and the decay-field warp, metres."""
    w_a = np.stack([value_noise(p / 15.0, 10), value_noise(p / 15.0, 11)], -1) - 0.5
    w_b = warp3(p)
    return SLAB_WARP[0] * w_a + SLAB_WARP[1] * w_b, DECAY_WARP * w_b


def slab_cells(qw):
    """Power-diagram search in the warped lattice space: best cell, jitter, edge distance, pixel-to-centre."""
    cell = np.floor(qw / SLAB_PITCH)
    lq = qw / SLAB_PITCH - cell
    best_pd = np.full(len(qw), 1e9)
    best_c = cell.copy()
    best_o = lq.copy()
    best_j = np.full_like(qw, 0.5)
    for j in range(9):
        o = np.array([j % 3 - 1, j // 3 - 1], dtype=np.float64)
        jit, wgt = slab_jitter(cell + o)
        lp = o + 0.5 + SLAB_JITTER * (jit - 0.5)
        dv = (lq - lp) * SLAB_PITCH
        pd = (dv * dv).sum(-1) - wgt
        better = pd < best_pd
        best_pd = np.where(better, pd, best_pd)
        best_c = np.where(better[:, None], cell + o, best_c)
        best_o = np.where(better[:, None], lp, best_o)
        best_j = np.where(better[:, None], jit, best_j)
    edge_d = np.full(len(qw), 1e9)
    for j in range(25):
        o = np.array([j % 5 - 2, j // 5 - 2], dtype=np.float64)
        jit, wgt = slab_jitter(cell + o)
        lp = o + 0.5 + SLAB_JITTER * (jit - 0.5)
        ln = np.linalg.norm(lp - best_o, axis=1) * SLAB_PITCH
        dv = (lq - lp) * SLAB_PITCH
        pd = (dv * dv).sum(-1) - wgt
        cand = (pd - best_pd) / (2.0 * np.maximum(ln, 1e-9))
        edge_d = np.where(ln > 1e-5, np.minimum(edge_d, cand), edge_d)
    c_w = (best_c + 0.5 + SLAB_JITTER * (best_j - 0.5)) * SLAB_PITCH
    to_site = (best_o - lq) * SLAB_PITCH
    return best_c, c_w, to_site, edge_d


def polyline_frame(p, pts):
    """Nearest-segment distance, foot, direction and signed-across unit vector per point."""
    a = pts[:-1, :2]
    ab = pts[1:, :2] - a
    rel = p[:, None, :] - a[None, :, :]
    t = np.clip((rel * ab[None]).sum(-1) / np.maximum((ab * ab).sum(-1), 1e-6)[None], 0.0, 1.0)
    e = rel - ab[None] * t[..., None]
    d2 = (e * e).sum(-1)
    k = np.argmin(d2, axis=1)
    idx = np.arange(len(p))
    dist = np.sqrt(d2[idx, k])
    sab = ab[k]
    sdir = sab / np.linalg.norm(sab, axis=1, keepdims=True)
    foot = a[k] + sab * t[idx, k][:, None]
    cr = sdir[:, 0] * (p[:, 1] - a[k][:, 1]) - sdir[:, 1] * (p[:, 0] - a[k][:, 0])
    side = np.where(cr < 0.0, -1.0, 1.0)
    perp = np.stack([-sdir[:, 1], sdir[:, 0]], -1) * side[:, None]
    safe = np.maximum(dist, 1e-9)[:, None]
    across = np.where((dist > 1e-4)[:, None], (p - foot) / safe, perp)
    # road up: grade normals soft-min blended by distance
    seg_len = np.sqrt(np.maximum((ab * ab).sum(-1), 1e-6))
    grade = (pts[1:, 2] - pts[:-1, 2]) / seg_len
    w = np.exp(-3.0 * (np.sqrt(d2) - dist[:, None]))
    upk = np.concatenate([-grade[:, None] * ab / seg_len[:, None], np.ones((len(ab), 1))], 1)
    upk /= np.linalg.norm(upk, axis=1, keepdims=True)
    up = w @ upk
    up /= np.linalg.norm(up, axis=1, keepdims=True)
    return dist, across, k, up


def _taps(q, u, across, hw, core, surface, neglect, wear, fine_k, mid_k, slab_w, dec_w, colour, T):
    qw = q + slab_w
    best_c, c_w, to_site, edge_d = slab_cells(qw)
    r_tone, r_exist, r_hue, r_crack, r_scat, r_tilt = slab_props(best_c)

    src = {3: c_w, 4: c_w}
    nv = [value_noise(src.get(n, q) / s, n) for n, s in enumerate(NOISE_SCALES)]

    rc = 0.45 + 0.12 * (nv[0] - 0.5)
    rw = 0.07 + 0.05 * nv[1]
    ruts = np.exp(-(((u - rc) / rw) ** 2))
    rut_depth = (0.035 + 0.05 * nv[1]) * wear
    crown = 1.0 - smoothstep(0.0, 0.34, u)
    berm = np.exp(-(((u - 0.93) / 0.12) ** 2)) * (0.35 + 0.65 * nv[5])

    uc = np.maximum(u + (to_site * across).sum(-1) / hw, 0.0)
    ruts_c = np.exp(-(((uc - rc) / rw) ** 2))
    d_bias = T["DEC_NEG"] * (neglect - 0.63) + T["DEC_WEAR"] * (wear - 0.6)
    d_slab = (fbm(c_w + DECAY_WARP * warp3(c_w)) + d_bias + T["DEC_RUT"] * ruts_c * wear
              + T["DEC_VERGE"] * smoothstep(0.75, 1.2, uc))
    d_pix = fbm(qw + dec_w) + d_bias + T["DEC_RUT"] * ruts * wear
    crumble = value_noise(q / 0.12, 17)
    exists = (r_exist < surface - 0.001).astype(float)
    gone = (d_slab > T["DEC_GONE"]).astype(float)
    chip = ((d_pix + 0.16 * (crumble - 0.5)) > T["DEC_CHIP"]).astype(float)
    g = T["DEC_GONE"]
    erode = (0.18 * smoothstep(0.75, 1.15, uc) + 0.1 * smoothstep(g - 0.12, g, d_slab)) * (0.5 + nv[7])
    in_slab = (edge_d > erode).astype(float)
    present = exists * (1.0 - gone) * (1.0 - chip) * in_slab
    scat = (exists * (r_scat < 0.2) * smoothstep(0.95, 1.05, uc) * (1.0 - smoothstep(1.15, 1.3, uc))
            * (edge_d > 0.16 + 0.1 * nv[7]))
    stone = np.maximum(present, scat)
    bur = (0.65 * nv[3] + 0.35 * nv[4] + T["BUR_NEG"] * (neglect - 0.5)
           + 0.25 * (1.0 - smoothstep(0.0, 0.14, edge_d)) + 0.14 * (nv[6] - 0.5)
           + 0.2 * smoothstep(0.8, 1.2, uc) - T["BUR_OFF"])
    cover = smoothstep(0.48, 0.6, bur + 0.1 * fine_k * (nv[2] - 0.5))
    slab_vis = stone * (1.0 - cover)
    hole = exists * (1.0 - stone)
    pit_e = d_pix - T["PIT_NEG"] * (neglect - 0.63) + 0.08 * (nv[6] - 0.5) + 0.06 * fine_k * (crumble - 0.5)
    pit = smoothstep(T["PIT_LO"], T["PIT_LO"] + 0.06, pit_e)
    pit_deep = smoothstep(T["PIT_LO"], T["PIT_LO"] + 0.16, pit_e)

    cl = -to_site / 0.42 + r_tilt * 61.0
    cn = 0.7 * value_noise(cl, 18) + 0.3 * value_noise(cl * 2.7, 19)
    crack_p = 0.3 + 0.55 * smoothstep(g - 0.27, g, d_slab)
    crack = ((r_crack < crack_p) * (1.0 - smoothstep(0.006, 0.014 + 0.012 * smoothstep(g - 0.17, g, d_slab), np.abs(cn - 0.5)))
             * mid_k * smoothstep(0.02, 0.06, edge_d))
    tilt_amt = 0.015 + 0.06 * smoothstep(0.7, 1.15, uc) + 0.04 * smoothstep(g - 0.17, g, d_slab) + 0.05 * scat
    h_tilt = (-to_site * (r_tilt - 0.5) * 2.0 * tilt_amt[:, None]).sum(-1) * smoothstep(0.0, 0.08, edge_d)

    bevel = 1.0 + (smoothstep(0.0, 0.06, edge_d) - 1.0) * mid_k
    h_slab = (0.045 * crown + 0.008 * bevel + 0.006 * (r_tone - 0.5) + h_tilt
              - 0.015 * smoothstep(0.8, 1.2, uc) - 0.005 * crack)
    h_dirt = (0.045 * crown - rut_depth * ruts + 0.03 * berm + 0.008 * fine_k * (nv[2] - 0.5)
              + 0.01 * (nv[4] - 0.5) - 0.02 * hole - 0.02 * pit - 0.05 * pit_deep)
    h = h_dirt + (h_slab - h_dirt) * slab_vis
    out = dict(h=h)
    if colour:
        lerp = lambda a, b, t: a + (b - a) * t
        t1 = lambda x: np.asarray(x, dtype=float)[..., None]
        edge_n = 0.45 * value_noise((qw + dec_w) / 6.0, 20) + 0.35 * nv[5] + 0.2 * nv[6]
        ev = core + T["EDGE_AMP"] * (edge_n - 0.5) - T["EDGE_DEC"] * (d_pix - 0.45) + 0.08 * fine_k * (crumble - 0.5)
        dirt = DIRT[None] * t1(0.9 + 0.2 * nv[3]) * t1(1.0 + (0.9 + 0.2 * nv[2] - 1.0) * fine_k)
        dirt = dirt * t1(1.0 + (0.72 - 1.0) * np.clip(ruts * wear * 1.4, 0, 1))
        dirt = dirt * t1(1.0 + 0.1 * crown)
        mud = np.clip(smoothstep(T["PIT_LO"] + 0.02, T["PIT_LO"] + 0.1, pit_e) * np.clip(0.35 + neglect, 0, 1)
                      * (0.75 + 0.5 * nv[6]), 0, 1)
        dirt = lerp(dirt, DIRT[None] * 0.6, t1(mud))
        grav = GRAVEL[None] * t1(1.0 + (0.75 + 0.5 * nv[7] - 1.0) * fine_k)
        gravel_amt = np.clip((1.0 - smoothstep(0.45, 0.8, ev)) * (0.25 + 0.75 * nv[6]) + 0.4 * berm * nv[5], 0, 1)
        dirt = lerp(dirt, grav, t1(gravel_amt * (1.0 - mud)))
        hue = lerp(np.array([1.05, 1.0, 0.92])[None], np.array([0.95, 1.0, 1.07])[None], t1(r_hue))
        slab_c = PAVING[None] * t1(0.9 + 0.2 * r_tone) * t1(0.94 + 0.12 * value_noise(c_w / 12.0, 21)) * hue
        slab_c = lerp(slab_c, dirt, t1(0.35 * (1.0 - smoothstep(0.0, 0.1, edge_d))))
        slab_c = lerp(slab_c, DIRT[None] * 0.45,
                      t1(np.maximum((1.0 - smoothstep(0.01, 0.035, edge_d)) * mid_k, 0.85 * crack)))
        col = lerp(dirt, slab_c, t1(slab_vis))
        grass = (neglect * (1.0 - slab_vis) * smoothstep(0.5, 0.72, nv[8]) * np.clip(crown * 1.5 + 0.8 * hole, 0, 1)
                 * (1.0 - mud))
        col = lerp(col, GRASS[None] * t1(0.85 + 0.3 * nv[7]), t1(grass * 0.85))
        rough = lerp(lerp(0.93 - 0.12 * ruts * wear, 0.72, mud), 0.86, slab_vis)
        opac = smoothstep(0.4, 0.55, ev)
        peb = (nv[7] > 0.74).astype(float) * smoothstep(0.18, 0.4, ev) * fine_k
        col = lerp(col, grav, t1(peb * (1.0 - opac) * (1.0 - slab_vis)))
        opac = np.maximum(opac, np.maximum(peb, scat * slab_vis))
        out.update(col=col, rough=rough, opac=opac, slab_vis=slab_vis, present=present, exists=exists,
                   missing=gone * exists, gone=gone, chip=chip * exists, cover=cover, slab_id=best_c,
                   slab_site=c_w, edge_d=edge_d, ruts=ruts, crown=crown, r_tone=r_tone, hole=hole, ev=ev,
                   grass=grass, d_slab=d_slab, d_pix=d_pix, pit=pit, mud=mud, crack=crack, scat=scat,
                   stone=stone, uc=uc, h_tilt=h_tilt, r_hue=r_hue)
    return out


def evaluate(p, pts, core=1.0, surface=0.0, neglect=0.4, wear=0.5, hw=2.25, ts=0.03, tuning=None):
    """Evaluate the road writer at points p ([N, 2] metres, mask frame) for polyline pts ([M, 3] m).

    core/surface/neglect/wear may be scalars or [N] arrays (the mask samples).
    ts is the RVT texel size in metres (the mip): 0.03 is the finest mip.
    """
    T = dict(TUNING, **(tuning or {}))
    p = np.asarray(p, dtype=np.float64).reshape(-1, 2)
    pts = np.asarray(pts, dtype=np.float64)
    n = len(p)
    full = lambda v: np.broadcast_to(np.asarray(v, dtype=np.float64), (n,)).copy()
    core, surface, neglect, wear = full(core), full(surface), full(neglect), full(wear)
    hw = max(hw, 0.5)
    fine_k = np.clip((0.12 - ts) / 0.08, 0, 1)
    mid_k = np.clip((0.6 - ts) / 0.4, 0, 1)
    eps = max(0.015, 0.5 * ts)
    slab_w, dec_w = lattice_warp(p)
    dist, across, k, up = polyline_frame(p, pts)
    u0 = dist / hw
    res = None
    taps = []
    for s, off in enumerate([(0.0, 0.0), (eps, 0.0), (0.0, eps)]):
        off = np.array(off)
        u = np.maximum(u0 + (across * off[None]).sum(-1) / hw, 0.0)
        r = _taps(p + off[None], u, across, hw, core, surface, neglect, wear, fine_k, mid_k, slab_w, dec_w,
                  s == 0, T)
        if s == 0:
            res = r
        taps.append(r["h"])
    dhx = (taps[1] - taps[0]) / eps
    dhy = (taps[2] - taps[0]) / eps
    nrm = up + np.stack([-dhx, -dhy, np.zeros(n)], -1)
    nrm /= np.linalg.norm(nrm, axis=1, keepdims=True)
    res.update(normal=nrm, u=u0, dist=dist, across=across, seg=k, up=up)
    return res
