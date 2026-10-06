"""Silhouette check for the title capture (spec section 6, "The central mountain, always visible").

    python Tools/Look/check_silhouette.py <png> <mountain_box> <sky_box>

Boxes are pixel rectangles "x0,y0,x1,y1" (x1/y1 exclusive). The script prints the absolute
difference between the mean luma of the two boxes, then PASS or FAIL.

Luma is Rec.709 weights on the display-encoded (sRGB) 8-bit values, scaled to 0..1, which is
what the eye compares on screen. Pass rule: difference >= 0.08.

Exit codes: 0 pass, 1 fail, 2 bad arguments (unparsable box or box outside the image).
"""
import sys

import numpy as np
from PIL import Image

THRESHOLD = 0.08
REC709 = np.array([0.2126, 0.7152, 0.0722])


def parse_box(text):
    parts = [int(round(float(v))) for v in text.split(",")]
    if len(parts) != 4:
        raise ValueError(f"box needs 4 numbers x0,y0,x1,y1: {text!r}")
    x0, y0, x1, y1 = parts
    if x1 <= x0 or y1 <= y0:
        raise ValueError(f"empty box: {text!r}")
    return x0, y0, x1, y1


def _luma(path):
    rgb = np.asarray(Image.open(path).convert("RGB"), dtype=np.float64) / 255.0
    return rgb @ REC709


def box_mean(luma, box):
    x0, y0, x1, y1 = box
    h, w = luma.shape
    if x0 < 0 or y0 < 0 or x1 > w or y1 > h:
        raise ValueError(f"box {box} outside image {w}x{h}")
    return float(luma[y0:y1, x0:x1].mean())


def luminance_difference(path, mountain_box, sky_box):
    luma = _luma(path)
    return abs(box_mean(luma, sky_box) - box_mean(luma, mountain_box))


def main(argv):
    if len(argv) != 4:
        print(__doc__)
        return 2
    path = argv[1]
    try:
        mountain, sky = parse_box(argv[2]), parse_box(argv[3])
        luma = _luma(path)
        m, s = box_mean(luma, mountain), box_mean(luma, sky)
    except (ValueError, OSError) as e:
        print(f"error: {e}")
        return 2
    diff = abs(s - m)
    verdict = "PASS" if diff >= THRESHOLD else "FAIL"
    print(f"{diff:.4f} {verdict} (mountain {m:.4f}, sky {s:.4f}, threshold {THRESHOLD})")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
