# Tools/Terrain/bake_masks.py
"""Bake the Saskarta road-influence and ecology masks. See the sprint spec, section 2.

    python Tools/Terrain/bake_masks.py [--size 4096] [--check]
"""
import argparse, json, pathlib, sys
import numpy as np
from PIL import Image
from scipy import ndimage

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Tools" / "Story"))
import build_road_profile as brp

ORIGIN_CM = (brp.LAND_X0_CM, brp.LAND_Y0_CM)
EXTENT_CM = 816000.0
GAEA = pathlib.Path("D:/GaeaBuilds/Saskarta_direct_16k")
SURFACE = json.loads((pathlib.Path(__file__).with_name("road_surface.json")).read_text())
ROAD_LEN_M = 5009.0
Image.MAX_IMAGE_PIXELS = None

def world_to_texel(xy_cm, size):
    return np.clip(((xy_cm - np.array(ORIGIN_CM)) / EXTENT_CM * size).astype(int), 0, size - 1)

def road_polyline_cm(step_m=2.0, lo_m=0.0, hi_m=ROAD_LEN_M):
    return brp.Road(brp.SPLINE_POINTS_CM).xy(np.arange(lo_m, hi_m, step_m))

def fbm(size, scale_px, octaves, seed, warp_px=0.0):
    g = np.random.default_rng(seed)
    out, amp, tot = np.zeros((size, size), np.float32), 1.0, 0.0
    for o in range(octaves):
        n = ndimage.gaussian_filter(g.standard_normal((size, size)).astype(np.float32), max(scale_px / 2 ** o / 2.5, 0.6), mode="wrap")
        out += amp * n / (n.std() + 1e-9); tot += amp; amp *= 0.5
    out /= tot
    if warp_px:
        yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
        wx = ndimage.gaussian_filter(g.standard_normal((size, size)).astype(np.float32), scale_px / 2); wx /= wx.std() + 1e-9
        wy = ndimage.gaussian_filter(g.standard_normal((size, size)).astype(np.float32), scale_px / 2); wy /= wy.std() + 1e-9
        out = ndimage.map_coordinates(out, [yy + wy * warp_px, xx + wx * warp_px], order=1, mode="wrap")
    return ((out - out.min()) / (out.max() - out.min())).astype(np.float32)

def surface_along(d_m):
    """Surface type (0 dirt, 1 paving) along the road with blend_m smoothstep transitions."""
    s = np.zeros_like(d_m, dtype=np.float64)
    for st in SURFACE["stretches"]:
        if st["surface"] != "paving":
            continue
        b = SURFACE["blend_m"]
        rise = np.clip((d_m - (st["from_m"] - b / 2)) / b, 0, 1)
        fall = np.clip(((st["to_m"] + b / 2) - d_m) / b, 0, 1)
        t = np.minimum(rise, fall)
        s = np.maximum(s, t * t * (3 - 2 * t))
    return s.astype(np.float32)

def neglect_bias_along(d_m):
    out = np.zeros_like(d_m, dtype=np.float32)
    for st in SURFACE["stretches"]:
        out[(d_m >= st["from_m"]) & (d_m < st["to_m"])] = st["neglect_bias"]
    return ndimage.uniform_filter1d(out, 101, mode="nearest")

def verge_profile(dist_m):
    return np.clip(1.0 - dist_m / 25.0, 0, 1) ** 1.5

def road_distance_fields(size):
    """Per texel: distance to the road (m) and distance along the road (m) of the closest point.

    Analytic against the 54 polyline segments: nearest point on each (clamped to the segment),
    minimum over all segments, evaluated at each texel's centre. Continuous and exact at any
    output resolution -- unlike rasterising the polyline onto the texel grid and running a
    distance transform there, which quantises distance to whole texels (0, 1, sqrt(2), 2, ...).
    That quantisation is negligible at the production size (4096, ~2 m/texel) but not at a
    texel comparable to or wider than the 3.5-5.5 m road itself. Segment-local nearest point
    also resolves hairpins correctly: at a hairpin the two nearby strands are different
    segments, and the true minimum distance (not distance to the nearest of many fixed raster
    samples) picks whichever strand is actually closer, so "along" does not jump between them.

    Controller ruling R20: do not widen the road or its 0.6/1.2 m edge feather to compensate for
    a coarse grid. test_core_on_spline, test_core_width and test_hairpin_continuity must run
    against a texel small next to the road (the 4096 production size, or 2048 at a pinch) --
    see the two-fixture split in Tools/Terrain/tests/test_bake_masks.py. At the shared cheap
    fixture (1024, ~8 m/texel, wider than the road), no distance field, however exact, can make
    a single texel centre resolve a road narrower than the texel; that is a texel-size problem,
    not a distance-field bug.
    """
    road = brp.Road(brp.SPLINE_POINTS_CM)
    P = road.P[:, :2]                                                         # cm, walk order
    xs = ORIGIN_CM[0] + (np.arange(size, dtype=np.float64) + 0.5) * EXTENT_CM / size
    ys = ORIGIN_CM[1] + (np.arange(size, dtype=np.float64) + 0.5) * EXTENT_CM / size
    X, Y = np.meshgrid(xs, ys)                                                # (size, size) cm
    best_d2 = np.full((size, size), np.inf, dtype=np.float64)
    best_along = np.zeros((size, size), dtype=np.float64)
    for k in range(len(P) - 1):
        ax, ay = P[k]
        bx, by = P[k + 1]
        abx, aby = bx - ax, by - ay
        ab2 = abx * abx + aby * aby
        if ab2 == 0.0:
            continue
        t = np.clip(((X - ax) * abx + (Y - ay) * aby) / ab2, 0.0, 1.0)
        px, py = ax + t * abx, ay + t * aby
        dx, dy = X - px, Y - py
        d2 = dx * dx + dy * dy
        along = road.arc[k] + t * road.seg[k]
        better = d2 < best_d2
        np.copyto(best_d2, d2, where=better)
        np.copyto(best_along, along, where=better)
    dist_m = np.sqrt(best_d2) / 100.0
    return dist_m.astype(np.float32), best_along.astype(np.float32)

def gaea(name, size, gaea_dir=GAEA):
    im = np.asarray(Image.open(gaea_dir / f"T_Gaea_{name}.png")).astype(np.float32) / 65535.0
    return np.asarray(Image.fromarray(im).resize((size, size), Image.BILINEAR), np.float32)

def height_mask_correlation(size=512, gaea_dir=GAEA):
    """Correlation between the live heightmap and a GAEA export's Height mask.

    Investigated once for D:/GaeaBuilds/Saskarta_direct_16k (the only export on disk): correlation
    is ~0.19 at best across all 8 rotate/flip combinations of the GAEA image (checked exhaustively,
    with and without a translation search via FFT phase correlation) -- nowhere near the >0.98
    this function's callers require, and not an orientation problem: the peak of Current_u16.png
    (the live heightmap) falls almost exactly on build_road_profile.SUMMIT_HINT_CM, confirming the
    live heightmap is correctly aligned to world space, while every T_Gaea_*.png in that export is
    dated 2026-09-19, three days before the [[saskarta-terrain-was-tiled-2x2]] fix that replaced
    the landscape's heightmap with the corrected, de-duplicated Current_u16.png on 2026-09-22 (no
    later GAEA export exists on disk). That export is spatially stale and not usable at any
    orientation; see task-P1-report.md. This function, and the --gaea-dir refusal gate in bake(),
    exist so a *future* fresh GAEA export can be checked before anything reads it again -- ecology
    channels here are derived from Current_u16.png directly (see flow_accumulation) and do not
    otherwise touch GAEA.
    """
    h = brp.Terrain(brp.HEIGHTMAP).h
    hs = np.asarray(Image.fromarray(h.astype(np.float32)).resize((size, size), Image.BILINEAR))
    return float(np.corrcoef(hs.ravel(), gaea("Height", size, gaea_dir).ravel())[0, 1])

def flow_accumulation(size):
    """D8 flow accumulation over the live heightmap, computed at `size` (1024-2048 is plenty;
    this is a hydrology proxy for moisture, not a geometry test, so it does not need texel
    precision against the road). Each cell starts with 1 unit and drains to its single steepest
    of 8 neighbours; cells are processed from highest to lowest so accumulation only ever flows
    downhill, giving each cell the upstream catchment area (in cells) that drains through it.
    Flat cells / local pits have no downhill neighbour and just keep their own 1 unit.
    Returns a (size, size) float64 array, NOT normalised (see moisture in bake()).
    """
    h = np.asarray(Image.fromarray(brp.Terrain(brp.HEIGHTMAP).h.astype(np.float32))
                    .resize((size, size), Image.BILINEAR)).astype(np.float64)
    offsets = ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1))
    dists = (2 ** 0.5, 1.0, 2 ** 0.5, 1.0, 1.0, 2 ** 0.5, 1.0, 2 ** 0.5)
    rows, cols = np.arange(size)[:, None], np.arange(size)[None, :]
    best_slope = np.zeros((size, size))
    target = np.full((size, size), -1, dtype=np.int64)
    for (dr, dc), dd in zip(offsets, dists):
        rr, cc = np.clip(rows + dr, 0, size - 1), np.clip(cols + dc, 0, size - 1)
        slope = (h - h[rr, cc]) / dd
        better = slope > best_slope
        best_slope = np.where(better, slope, best_slope)
        target = np.where(better, rr * size + cc, target)
    flat_target = np.where(best_slope > 1e-9, target, -1).ravel()
    order = np.argsort(-h.ravel(), kind="stable")                            # highest first
    acc = np.ones(size * size, dtype=np.float64)
    for idx in order:
        t = flat_target[idx]
        if t >= 0:
            acc[t] += acc[idx]
    return acc.reshape(size, size)

def bake(out_dir, size=4096, seed=1, gaea_dir=None):
    """gaea_dir: optional path to a GAEA export, for a FUTURE re-export only (see
    height_mask_correlation). Nothing here is derived from GAEA any more -- passing it just
    asserts the export is spatially aligned to Current_u16.png before allowing the bake to run
    at all, and refuses (raises) otherwise. Left out (the default), no GAEA file is touched.
    """
    if gaea_dir is not None:
        corr = height_mask_correlation(gaea_dir=pathlib.Path(gaea_dir))
        if not (corr > 0.98):
            raise RuntimeError(
                f"Refusing to bake: GAEA export at {gaea_dir} does not align with the live "
                f"heightmap (height_mask_correlation={corr:.3f}, need > 0.98). See "
                f"height_mask_correlation()'s docstring and task-P1-report.md."
            )
    rng_seed = seed
    ppm = size / (EXTENT_CM / 100.0)                                          # pixels per metre
    dist_m, along_m = road_distance_fields(size)
    edge = fbm(size, ppm * 12, 3, rng_seed + 1)                               # ~12 m edge wobble
    half_w = 1.75 + 1.0 * edge                                                # 1.75..2.75 m => 3.5..5.5 m
    core = np.clip((half_w + 0.6 - dist_m) / 1.2, 0, 1)
    verge = verge_profile(dist_m)
    n1d = fbm(size, ppm * 300, 3, rng_seed + 2)                               # slow along-road variation (~300 m)
    neglect = np.clip(n1d + neglect_bias_along(along_m), 0, 1)
    surface = surface_along(along_m) * (dist_m < 12)
    h = np.asarray(Image.fromarray(brp.Terrain(brp.HEIGHTMAP).h.astype(np.float32)).resize((size, size), Image.BILINEAR))
    px_m = EXTENT_CM / 100 / size
    gy, gx = np.gradient(ndimage.gaussian_filter(h, 1.0), px_m)
    slope = np.degrees(np.arctan(np.hypot(gx, gy)))
    alt = np.clip((h - h.min()) / (h.max() - h.min()), 0, 1)

    # Ecology channels (R21): derived from the live heightmap only. GAEA's Forest/DriedRiver/Snow
    # masks are no longer read here at all -- see height_mask_correlation()'s docstring for why.
    flow_calc = min(size, 2048) if size >= 2048 else 1024                    # 1024-2048 is plenty
    flow = flow_accumulation(flow_calc)
    flow_norm = np.log1p(flow)
    flow_norm = (flow_norm - flow_norm.min()) / (flow_norm.max() - flow_norm.min() + 1e-9)
    flow_norm = np.asarray(Image.fromarray(flow_norm.astype(np.float32)).resize((size, size), Image.BILINEAR), np.float32)
    hollow_near = np.clip(ndimage.gaussian_laplace(h, 6.0 / px_m) / 0.02, 0, 1)     # ~6 m: rills, gullies
    hollow_far = np.clip(ndimage.gaussian_laplace(h, 30.0 / px_m) / 0.02, 0, 1)     # ~30 m: broad basins
    hollow = np.clip(0.5 * hollow_near + 0.5 * hollow_far, 0, 1)
    moisture = np.clip(0.5 * flow_norm + 0.35 * hollow + 0.15 * (1.0 - alt), 0, 1)
    aspect_south = np.clip(0.5 - 0.5 * gy / (np.hypot(gx, gy) + 1e-6), 0, 1)
    exposure = np.clip(0.55 * np.clip(slope / 40, 0, 1) + 0.3 * alt + 0.15 * aspect_south, 0, 1)
    alt_p85 = float(np.percentile(alt, 85))
    snow = np.clip((alt - alt_p85) / (1.0 - alt_p85 + 1e-6), 0, 1) * (slope < 35).astype(np.float32)
    zone = np.clip(alt * 0.7 + snow * 0.3, 0, 1)
    macro = fbm(size, ppm * 120, 4, rng_seed + 3, warp_px=ppm * 18)

    out = {k: v.astype(np.float32) for k, v in dict(core=core, verge=verge, neglect=neglect, surface=surface,
                                                   moisture=moisture, exposure=exposure, zone=zone, macro=macro).items()}
    if out_dir:
        write_rgba16(out_dir / "T_Saskarta_RoadInfluence.png", out["core"], out["verge"], out["neglect"], out["surface"])
        write_rgba16(out_dir / "T_Saskarta_Ecology.png", out["moisture"], out["exposure"], out["zone"], out["macro"])
    return out

def write_rgba16(path, r, g, b, a):
    """16-bit-per-channel RGBA PNG.

    Not imageio/Pillow: Pillow's PNG encoder has no path for a (H, W, 4) uint16 array
    (Image.fromarray raises "Cannot handle this data type: (1, 1, 4), <u2" -- Pillow's 16-bit
    support is limited to single-channel "I"/"I;16" mode, not RGBA), so imageio.v3.imwrite fails
    outright here regardless of whether imageio itself is installed. cv2.imwrite does write a
    true 16-bit-per-channel 4-channel PNG; verified by round-tripping known per-channel values
    through cv2.imwrite/cv2.imread and recovering them exactly (Pillow/imageio can *read* the
    result back too, but silently truncate to the top 8 bits per channel -- a read-side
    limitation, not a sign the file is wrong). cv2 expects BGRA channel order, so channels are
    swapped going in to land as R, G, B, A in the file.
    """
    import cv2
    path.parent.mkdir(parents=True, exist_ok=True)
    bgra = np.dstack([b, g, r, a])
    ok = cv2.imwrite(str(path), (bgra * 65535 + 0.5).astype(np.uint16))
    if not ok:
        raise IOError(f"cv2.imwrite failed: {path}")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=4096)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--gaea-dir", type=pathlib.Path, default=None,
                     help="Optional GAEA export to validate (see height_mask_correlation). "
                          "Not used for any ecology data; the bake refuses to run if it fails "
                          "the > 0.98 alignment check against the live heightmap.")
    a = ap.parse_args()
    masks = bake(ROOT / "Saved" / "Masks", size=a.size, gaea_dir=a.gaea_dir)
    print({k: (round(float(v.min()), 3), round(float(v.max()), 3)) for k, v in masks.items()})
