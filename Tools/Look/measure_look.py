"""Palette gate for look captures: is this frame as dark and desaturated as the concept board?

    python Tools/Look/measure_look.py <png> [<png> ...]

For each capture it prints:
    <file>  L=<mean luminance>  S_mid=<median mid-tone saturation>  mid=<mid-tone fraction>  PASS|FAIL

- Luminance is Rec.709 luma of the display-encoded (sRGB) 8-bit values, scaled to 0..1,
  the same measure check_silhouette.py uses. Rule: mean in 0.14..0.26.
- Mid-tones are pixels with luma in 0.25..0.75. Their saturation is HSV S = (max - min) / max.
  Rule: the median is at most 0.30. A frame with no mid-tones reports 0 for the median
  (the luminance rule still catches a frame that is simply too dark).
- Alpha is ignored (render-target exports can carry alpha 0).

Exit codes: 0 when every capture passes, 1 when any fails, 2 on a bad file.
"""
import sys

import numpy as np
from PIL import Image

LUM_MIN, LUM_MAX = 0.14, 0.26
MID_LO, MID_HI = 0.25, 0.75
SAT_MAX = 0.30
REC709 = np.array([0.2126, 0.7152, 0.0722])


def measure(path):
    rgb = np.asarray(Image.open(path).convert("RGB"), dtype=np.float64) / 255.0
    luma = rgb @ REC709
    mean = float(luma.mean())
    mid = (luma >= MID_LO) & (luma <= MID_HI)
    frac = float(mid.mean())
    if mid.any():
        px = rgb[mid]
        mx, mn = px.max(axis=1), px.min(axis=1)
        sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-9), 0.0)
        s_med = float(np.median(sat))
    else:
        s_med = 0.0
    ok = (LUM_MIN <= mean <= LUM_MAX) and s_med <= SAT_MAX
    return {"mean_luminance": mean, "midtone_saturation_median": s_med,
            "midtone_fraction": frac, "pass": bool(ok)}


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    all_ok = True
    for path in argv[1:]:
        try:
            m = measure(path)
        except OSError as e:
            print(f"{path}  error: {e}")
            return 2
        all_ok &= m["pass"]
        print(f"{path}  L={m['mean_luminance']:.4f}  S_mid={m['midtone_saturation_median']:.4f}"
              f"  mid={m['midtone_fraction']:.3f}  {'PASS' if m['pass'] else 'FAIL'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
