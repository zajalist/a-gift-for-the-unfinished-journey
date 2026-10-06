"""Find the High Voice crown and beam in a look capture and report their pixels and brightness.

    python Tools/Look/beacon_pixels.py <png> --cam X Y Z PITCH YAW HFOV [--site X Y Z]

The camera pose is what Tools/Look/capture_look.py prints (and TitleCam's horizontal FOV).
It projects the crown centre and points up the beam into the image, finds the brightest
pixel near each projection, and compares it with the sky around it. Luma is Rec.709 on the
8-bit sRGB values, 0..1, as in measure_look.py.

Geometry comes from build_high_voice.py: the actor sits at the traced ground under spline
point 0, the crown centre is 43 m above the actor origin, and the beam runs 400 m up from it.
"""
import argparse
import json
import math
import sys

import numpy as np
from PIL import Image

# Actor origin placed by build_high_voice.py place (ground 108.69 m, sunk 0.5 m).
SITE_CM = (298079.6, 483050.0, 10818.7)
CROWN_Z_CM = 4300.0
BEAM_HEIGHT_CM = 40000.0
BEAM_SAMPLES_M = (25, 50, 100, 200, 300, 380)


def project(cam, point, width, height):
    """Pixel (x, y) of a world point for cam = (x, y, z, pitch, yaw, hfov), or None if behind."""
    cx, cy, cz, pitch, yaw, hfov = cam
    p, y = math.radians(pitch), math.radians(yaw)
    fwd = (math.cos(p) * math.cos(y), math.cos(p) * math.sin(y), math.sin(p))
    right = (-math.sin(y), math.cos(y), 0.0)
    up = (-math.sin(p) * math.cos(y), -math.sin(p) * math.sin(y), math.cos(p))
    d = (point[0] - cx, point[1] - cy, point[2] - cz)
    f = sum(a * b for a, b in zip(d, fwd))
    if f <= 0:
        return None
    k = (width / 2) / math.tan(math.radians(hfov) / 2)
    r = sum(a * b for a, b in zip(d, right))
    u = sum(a * b for a, b in zip(d, up))
    return width / 2 + k * r / f, height / 2 - k * u / f


def luma(rgb):
    return float(0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]) / 255.0 \
        if np.ndim(rgb) == 1 else (0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]) / 255.0


def peak(img, x, y, radius=12):
    """Brightest pixel within `radius` of (x, y), and the median luma of a ring around it."""
    h, w = img.shape[:2]
    x0, x1 = max(0, int(x) - radius), min(w, int(x) + radius + 1)
    y0, y1 = max(0, int(y) - radius), min(h, int(y) + radius + 1)
    win = img[y0:y1, x0:x1].astype(np.float64)
    lw = luma(win)
    iy, ix = np.unravel_index(int(np.argmax(lw)), lw.shape)
    px, py = x0 + int(ix), y0 + int(iy)
    ring_r = radius * 3
    bx0, bx1 = max(0, px - ring_r), min(w, px + ring_r + 1)
    by0, by1 = max(0, py - ring_r), min(h, py + ring_r + 1)
    box = luma(img[by0:by1, bx0:bx1].astype(np.float64))
    yy, xx = np.mgrid[by0:by1, bx0:bx1]
    ring = box[np.hypot(xx - px, yy - py) > radius]
    return {"x": px, "y": py, "rgb": tuple(int(v) for v in img[py, px]),
            "luma": round(float(lw[iy, ix]), 3),
            "background_luma": round(float(np.median(ring)) if ring.size else 0.0, 3)}


def measure(png, cam, site=SITE_CM):
    img = np.asarray(Image.open(png).convert("RGB"))
    h, w = img.shape[:2]
    out = {"png": str(png), "size": [w, h], "camera": list(cam)}
    base = (site[0], site[1], site[2] + CROWN_Z_CM)
    dist = math.dist(cam[:3], base) / 100.0
    out["distance_m"] = round(dist, 1)
    c = project(cam, base, w, h)
    out["crown_projected"] = None if c is None else [round(c[0], 1), round(c[1], 1)]
    if c is not None and 0 <= c[0] < w and 0 <= c[1] < h:
        out["crown"] = peak(img, c[0], c[1], radius=8)
    beam = []
    for m in BEAM_SAMPLES_M:
        q = project(cam, (base[0], base[1], base[2] + m * 100.0), w, h)
        if q is None or not (0 <= q[0] < w and 0 <= q[1] < h):
            continue
        r = peak(img, q[0], q[1], radius=6)
        r["height_m"] = m
        r["projected"] = [round(q[0], 1), round(q[1], 1)]
        beam.append(r)
    out["beam"] = beam
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("png")
    ap.add_argument("--cam", nargs=6, type=float, required=True, metavar=("X", "Y", "Z", "PITCH", "YAW", "HFOV"))
    ap.add_argument("--site", nargs=3, type=float, default=SITE_CM)
    a = ap.parse_args(argv)
    print(json.dumps(measure(a.png, tuple(a.cam), tuple(a.site)), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
