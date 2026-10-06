"""Turn a cleaned inscription glyph (T_Inscription_<ID>.png, alpha = ink) into carving maps.

Outputs next to the source, per ID:
  T_Inscription_<ID>_H.png   16-bit height: 1 = stone face, 0 = bottom of the cut
  T_Inscription_<ID>_N.png   tangent-space normal map, OpenGL green (+G = up; green = +dh/drow):
                             import it with Flip Green Channel on (UE reads DirectX)
  T_Inscription_<ID>_AO.png  groove occlusion + dust fill mask
  <ID>_carved_preview.png    lit preview on procedural stone (for review only)

The cut is a chisel V-groove: depth grows from the stroke edge to its centre line (distance
transform over the local half-width), so every stroke has two lit-and-shaded walls meeting
in a sharp line, the way a letter-cutter's chisel leaves them. Edges get a small noise chip.
Usage: python Tools/Story/carve_inscription.py I05 I02
"""
import sys
from pathlib import Path
import numpy as np
from PIL import Image
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[2] / "SourceArt" / "Inscriptions"
PAD = 96            # stone margin around the glyph, px (at 2048 long side)
HW_REACH = 14       # px: how far the stroke half-width is spread from the centre line
CHIP = 0.9          # edge chip strength, px of distance noise
STRENGTH = 14.0     # normal slope scale: V walls at roughly 45 degrees


def noise(shape, scale, seed):
    rng = np.random.default_rng(seed)
    small = rng.random((max(2, shape[0] // scale), max(2, shape[1] // scale)))
    return ndimage.zoom(small, (shape[0] / small.shape[0], shape[1] / small.shape[1]), order=3)[:shape[0], :shape[1]]


def carve(gid):
    a = np.array(Image.open(ROOT / f"T_Inscription_{gid}.png"))[..., 3].astype(np.float32) / 255.0
    a = np.pad(a, PAD)
    ink = a > 0.5
    d_in = ndimage.distance_transform_edt(ink)                      # px inside the stroke
    d_in = d_in + CHIP * (noise(ink.shape, 6, 1) - 0.5) * ink        # chipped edges
    # local half-width of the stroke (the medial-axis distance, spread over the stroke), so each
    # stroke gets a true chisel V whose two walls meet in a sharp line down its centre
    hw = ndimage.grey_dilation(d_in, size=(2 * int(HW_REACH) + 1,) * 2)
    hw = np.maximum(ndimage.gaussian_filter(hw, 2.5), 1.0)   # smooth steps; faint ribbing reads as chisel marks
    depth = np.clip(d_in / hw, 0, 1)
    depth = ndimage.gaussian_filter(depth * ink, 0.7)
    h = 1.0 - depth
    # a worn bevel lip just outside the cut
    d_out = ndimage.distance_transform_edt(~ink)
    h -= 0.06 * np.exp(-d_out / 2.5) * (~ink)
    gy, gx = np.gradient(h)
    # y-up normal (rows run down, so d/dy_up = -d/drow and n_y = +dh/drow): OpenGL green, +G = up.
    # UE reads DirectX (+G = down), so the _N map is imported with Flip Green Channel on.
    n = np.dstack([-gx * STRENGTH, gy * STRENGTH, np.ones_like(h)])
    n /= np.linalg.norm(n, axis=2, keepdims=True)
    ao = 1.0 - 0.3 * ndimage.gaussian_filter(depth, 2.0)            # grooves collect shadow and dust
    Image.fromarray((np.clip(h, 0, 1) * 65535).astype(np.uint16)).save(ROOT / f"T_Inscription_{gid}_H.png")
    Image.fromarray(((n * 0.5 + 0.5) * 255).astype(np.uint8)).save(ROOT / f"T_Inscription_{gid}_N.png")
    Image.fromarray((np.clip(ao, 0, 1) * 255).astype(np.uint8)).save(ROOT / f"T_Inscription_{gid}_AO.png")
    # preview: warm sandstone, low raking light from the upper left
    stone = 0.55 + 0.12 * noise(h.shape, 40, 2) + 0.08 * noise(h.shape, 7, 3) + 0.05 * noise(h.shape, 2, 4)
    L = np.array([-0.62, 0.55, 0.56]); L /= np.linalg.norm(L)
    lam = np.clip((n * L).sum(2), 0, 1)                              # n and L are both y-up
    sh = ndimage.gaussian_filter(depth, 1.5) * 0.12                    # self-shadow inside the cut
    lum = stone * (0.25 + 0.95 * lam) * ao * (1 - sh)
    col = np.dstack([lum * 1.0, lum * 0.86, lum * 0.68])
    Image.fromarray((np.clip(col, 0, 1) * 255).astype(np.uint8)).save(ROOT / f"{gid}_carved_preview.png")
    print(gid, h.shape)


if __name__ == "__main__":
    for g in sys.argv[1:] or ["I05", "I02"]:
        carve(g)
