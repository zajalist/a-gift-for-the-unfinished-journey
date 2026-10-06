"""Look pass 2 metrics: road-vs-verge contrast, chroma, hue spread and contrast of a capture.

    python Tools/Look/measure_look2.py <view> <png> [<view> <png> ...]      # views: road_200 ... title
    python Tools/Look/measure_look2.py --json <view> <png> ...

Task LOOK2 (task-LOOK2-brief.md). Captures come from Tools/Look/capture_look.py, whose view poses
this reuses (eye 2.5 m over the ground at the camera, 70 deg horizontal FOV, 1920x1080).

Per capture it prints:
- **road/verge**: the mean linear luminance (sRGB decoded, Rec.709 weights) of the pixels that see
  the road core (T_Saskarta_RoadInfluence R >= 0.9) 20-60 m ahead, over that of the pixels that see
  the verge beside it (core < 0.02, within 7 m of the centreline). The ground points are placed on
  the live heightmap (Saved/TerrainRebuild/Current_u16.png) and projected through the view's pose.
  Whatever stands in front of the ground (grass on the road, say) counts: this is what the eye sees.
  Only road views; title and sky views skip it. On a base-colour capture it is the albedo ratio.
- **chroma**: mean CIELAB C* of the whole frame and of its lower half (ground and foliage).
- **hue spread**: circular standard deviation (deg) of the CIELAB hue angle over the lower-half
  pixels with C* >= 4 (below that the hue of a near-grey pixel is noise).
- **contrast**: the standard deviation of CIELAB L* over the lower half, and p90 - p10 of L*.
- **cast** (LOOK2 fix round 1): |mean(a*, b*)| / mean(C*), for the whole frame and its lower half.
  1.0 means every pixel leans the same hue way (one tint over everything); varied colour pulls it
  down, because opposing hues cancel in the mean. Also the cast's hue angle (deg).
"""
import argparse
import json
import math
import pathlib
import sys

import numpy as np
from PIL import Image

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MASK = ROOT / "Saved" / "Masks" / "T_Saskarta_RoadInfluence.png"
X0, Y0, EXTENT = -18920.4, 50.0, 816000.0          # Tools/Terrain/MASKS.md (Ruling R5)
REC709 = np.array([0.2126, 0.7152, 0.0722])
HFOV = 70.0
EYE_CM = 250.0
AHEAD_M = (20.0, 60.0)
VERGE_M = 7.0


def srgb_to_linear(c):
    c = np.asarray(c, float)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def linear_luminance(rgb):
    return srgb_to_linear(rgb) @ REC709


def srgb_to_lab(rgb):
    lin = srgb_to_linear(rgb)
    m = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
    xyz = lin @ m.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > (6 / 29) ** 3, np.cbrt(xyz), xyz / (3 * (6 / 29) ** 2) + 4 / 29)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], axis=-1)


def circ_std_deg(hues_deg):
    a = np.radians(np.asarray(hues_deg, float))
    r = math.hypot(np.sin(a).mean(), np.cos(a).mean())
    return math.degrees(math.sqrt(max(0.0, -2.0 * math.log(max(r, 1e-12)))))


def frame_metrics(rgb):
    lab = srgb_to_lab(rgb)
    chroma = np.hypot(lab[..., 1], lab[..., 2])
    h = rgb.shape[0]
    low = slice(h // 2, h)
    lo_c = chroma[low]
    lo_l = lab[low][..., 0]
    hue = np.degrees(np.arctan2(lab[low][..., 2], lab[low][..., 1]))
    keep = lo_c >= 4.0
    return {
        "chroma_frame": float(chroma.mean()),
        "chroma_lower": float(lo_c.mean()),
        "hue_spread_deg": circ_std_deg(hue[keep]) if keep.any() else 0.0,
        "hue_mean_deg": float(np.degrees(np.arctan2(np.sin(np.radians(hue[keep])).mean(),
                                                    np.cos(np.radians(hue[keep])).mean()))) if keep.any() else 0.0,
        "hued_fraction_lower": float(keep.mean()),
        "Lstar_std_lower": float(lo_l.std()),
        "Lstar_p90_p10_lower": float(np.percentile(lo_l, 90) - np.percentile(lo_l, 10)),
        "luma_mean": float((rgb @ REC709).mean()),
        "cast_frame": cast(lab),
        "cast_lower": cast(lab[low]),
        "cast_hue_deg": float(np.degrees(np.arctan2(lab[..., 2].mean(), lab[..., 1].mean()))),
    }


def cast(lab):
    """|mean(a*, b*)| / mean(C*): 1 when the whole region leans one hue way, 0 when hues cancel or it is grey."""
    a, b = lab[..., 1], lab[..., 2]
    c = np.hypot(a, b).mean()
    return float(math.hypot(a.mean(), b.mean()) / c) if c >= 1.0 else 0.0   # below C* 1 the hue is noise


def project(pts_cm, cam):
    """World points (N, 3, cm) to pixel (u, v) through a UE camera (yaw, pitch deg; hfov deg)."""
    p, y = math.radians(cam["pitch"]), math.radians(cam["yaw"])
    f = np.array([math.cos(p) * math.cos(y), math.cos(p) * math.sin(y), math.sin(p)])
    r = np.array([-math.sin(y), math.cos(y), 0.0])
    u = np.array([-math.sin(p) * math.cos(y), -math.sin(p) * math.sin(y), math.cos(p)])
    d = np.asarray(pts_cm, float) - np.array([cam["x"], cam["y"], cam["z"]])
    zf = d @ f
    k = (cam["w"] / 2.0) / math.tan(math.radians(cam["hfov"]) / 2.0)
    with np.errstate(divide="ignore", invalid="ignore"):
        px = cam["w"] / 2.0 + k * (d @ r) / zf
        py = cam["h"] / 2.0 - k * (d @ u) / zf
    ok = (zf > 1.0) & (px >= 0) & (px < cam["w"]) & (py >= 0) & (py < cam["h"])
    return px, py, ok


_CACHE = {}


def _mask():
    if "mask" not in _CACHE:
        import cv2
        _CACHE["mask"] = cv2.imread(str(MASK), cv2.IMREAD_UNCHANGED).astype(np.float32) / 65535.0  # BGRA
    return _CACHE["mask"]


def core_at(x_cm, y_cm):
    from scipy import ndimage
    m = _mask()
    u = (np.asarray(x_cm) - X0) / EXTENT * m.shape[1] - 0.5
    v = (np.asarray(y_cm) - Y0) / EXTENT * m.shape[0] - 0.5
    return ndimage.map_coordinates(m[..., 2], [v, u], order=1)    # R is channel 2 in BGRA


def road_samples(view):
    """Road-core and verge ground points (cm) 20-60 m ahead of a road view."""
    sys.path.insert(0, str(ROOT / "Tools" / "Story"))
    from build_road_profile import HEIGHTMAP, SPLINE_POINTS_CM, Road, Terrain
    from capture_look import VIEWS
    if "terrain" not in _CACHE:
        _CACHE["terrain"] = Terrain(HEIGHTMAP)
    terrain = _CACHE["terrain"]
    road = Road(SPLINE_POINTS_CM)
    s0 = VIEWS[view][0]
    ss = np.arange(s0 + AHEAD_M[0], s0 + AHEAD_M[1], 0.25)
    offs = np.arange(-VERGE_M, VERGE_M + 1e-6, 0.1)
    c = road.xy(ss)
    c2 = road.xy(ss + 0.5)
    t = (c2 - c) / np.linalg.norm(c2 - c, axis=1)[:, None]
    nrm = np.stack([-t[:, 1], t[:, 0]], axis=1)
    xy = c[:, None, :] + nrm[:, None, :] * (offs[None, :, None] * 100.0)
    x, y = xy[..., 0].ravel(), xy[..., 1].ravel()
    core = core_at(x, y)
    z = terrain.height(x, y) * 100.0
    pts = np.stack([x, y, z], axis=1)
    return pts[core >= 0.9], pts[core < 0.02]


def view_camera(view, w, h):
    sys.path.insert(0, str(ROOT / "Tools" / "Story"))
    from build_road_profile import HEIGHTMAP, Terrain
    from capture_look import view_pose
    if "terrain" not in _CACHE:
        _CACHE["terrain"] = Terrain(HEIGHTMAP)
    x, y, zs, pitch, yaw = view_pose(view)
    gz = float(_CACHE["terrain"].height(x, y)) * 100.0
    return dict(x=x, y=y, z=gz + EYE_CM, pitch=pitch, yaw=yaw, hfov=HFOV, w=w, h=h)


def road_contrast(view, rgb):
    h, w = rgb.shape[:2]
    cam = view_camera(view, w, h)
    lum = linear_luminance(rgb)
    out = {}
    for name, pts in zip(("core", "verge"), road_samples(view)):
        px, py, ok = project(pts, cam)
        idx = np.unique(np.stack([py[ok].astype(int), px[ok].astype(int)], axis=1), axis=0)
        out[name + "_pixels"] = int(len(idx))
        out[name + "_lum"] = float(lum[idx[:, 0], idx[:, 1]].mean()) if len(idx) else float("nan")
    out["road_verge_ratio"] = out["core_lum"] / out["verge_lum"] if out["verge_lum"] > 0 else float("nan")
    return out


def measure(view, path):
    rgb = np.asarray(Image.open(path).convert("RGB"), dtype=np.float64) / 255.0
    m = frame_metrics(rgb)
    if view.startswith("road_"):
        m.update(road_contrast(view, rgb))
    return m


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("pairs", nargs="+", help="view png [view png ...]")
    a = ap.parse_args(argv)
    if len(a.pairs) % 2:
        ap.error("give view/png pairs")
    rows = {}
    for view, path in zip(a.pairs[::2], a.pairs[1::2]):
        m = measure(view, path)
        rows[path] = dict(view=view, **m)
        if not a.json:
            rv = f" road/verge={m['road_verge_ratio']:.2f} (core {m['core_lum']:.4f} n{m['core_pixels']}," \
                 f" verge {m['verge_lum']:.4f} n{m['verge_pixels']})" if "road_verge_ratio" in m else ""
            print(f"{pathlib.Path(path).name} [{view}] C*={m['chroma_frame']:.2f} C*low={m['chroma_lower']:.2f}"
                  f" hue_std={m['hue_spread_deg']:.1f} Lstd={m['Lstar_std_lower']:.2f}"
                  f" L90-10={m['Lstar_p90_p10_lower']:.2f} luma={m['luma_mean']:.3f}"
                  f" cast={m['cast_frame']:.2f}/{m['cast_lower']:.2f}@{m['cast_hue_deg']:.0f}{rv}")
    if a.json:
        print(json.dumps(rows, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
