"""Generate the small UI textures of the direction-A redo (Task TITLE, addendum 2) into SourceArt/UI.

    python Tools/GameFlow/gen_ui_textures.py

All are straight-alpha PNGs (colour everywhere, coverage in alpha), drawn at 2x their 1080p size
so they stay crisp at 4K. The mock-up (SourceArt/UI/ui-directions-mockup.html, direction A)
gives the numbers; cqw = 1 % of the frame width (19.2 px at 1920).

- T_UI_TitleScrim     the title's shade: rgba(14,11,9) at .78 -> .45 (34 %) -> 0 (62 %) across,
                      combined with a bottom fade .55 -> 0 over the lower 40 %.
- T_UI_RowGlow        the focused settings row: gold #E8B070, alpha .14 -> 0 left to right.
- T_UI_Toggle_Off/On  3.2 x 1.5 cqw pill with a 1.1 cqw ivory knob; on = gold .55 track.
- T_UI_Knob           the slider thumb: ivory disc.
- T_UI_FocusMark      the menu focus mark: a .9 cqw gold line with a .8 cqw glow.
- T_UI_Chip           key-hint chip: 1 px ivory .35 outline, radius .3 cqw (9-slice, margin .25).
- T_UI_Arrow_L/R       the selector arrows (gold triangles).
- T_Saskarta_TitleName_Shadow  the calligraphy's drop shadow (alpha blurred, black).
- T_UI_SoftPlate      the caption plate (LANE5): a black rounded rect feathered by a wide blur, dense in the
                      middle, 9-slice margin 0.4 so the soft edge keeps its size however the plate stretches.
"""
import pathlib
import sys

import numpy as np
from PIL import Image, ImageFilter

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / "SourceArt" / "UI"
IVORY = (237, 229, 218)
GOLD = (232, 176, 112)
SHADE = (14, 11, 9)


def save(name, rgb, alpha):
    h, w = alpha.shape
    img = np.zeros((h, w, 4), np.uint8)
    img[..., :3] = np.array(rgb, np.uint8)
    img[..., 3] = np.clip(alpha * 255 + 0.5, 0, 255).astype(np.uint8)
    Image.fromarray(img, "RGBA").save(OUT / f"{name}.png")
    print(name, w, h)


def title_scrim():
    w, h = 1024, 576
    x = (np.arange(w) + 0.5) / w
    y = (np.arange(h) + 0.5) / h
    across = np.interp(x, [0, 0.34, 0.62, 1], [0.78, 0.45, 0, 0])
    up = np.interp(1 - y, [0, 0.40, 1], [0.55, 0, 0])  # 1 - y: distance from the bottom
    a = 1 - (1 - across[None, :]) * (1 - up[:, None])
    save("T_UI_TitleScrim", SHADE, a)


def row_glow():
    w, h = 512, 8
    x = (np.arange(w) + 0.5) / w
    save("T_UI_RowGlow", GOLD, np.tile(0.14 * (1 - x), (h, 1)))


def disc(w, h, cx, cy, r):
    ss = 4
    yy, xx = np.mgrid[0:h * ss, 0:w * ss]
    d = np.hypot((xx + 0.5) / ss - cx, (yy + 0.5) / ss - cy)
    m = (d <= r).astype(np.float32)
    return m.reshape(h, ss, w, ss).mean(axis=(1, 3))


def pill(w, h):
    r = h / 2
    ss = 4
    yy, xx = np.mgrid[0:h * ss, 0:w * ss]
    px = (xx + 0.5) / ss
    py = (yy + 0.5) / ss
    cx = np.clip(px, r, w - r)
    m = (np.hypot(px - cx, py - r) <= r).astype(np.float32)
    return m.reshape(h, ss, w, ss).mean(axis=(1, 3))


def toggles():
    # 1080p: 61 x 29 px pill, 21 px knob, 4 px inset. Drawn at 2x.
    w, h = 124, 58
    track = pill(w, h)
    for name, on in (("T_UI_Toggle_Off", False), ("T_UI_Toggle_On", True)):
        knob_r = 21
        cx = (w - 8 - knob_r) if on else (8 + knob_r)
        knob = disc(w, h, cx, h / 2, knob_r)
        tcol = np.array(GOLD if on else IVORY, np.float32)
        ta = track * (0.55 if on else 0.18)
        a = knob + ta * (1 - knob)
        col = (np.array(IVORY, np.float32)[None, None] * knob[..., None]
               + tcol[None, None] * (ta * (1 - knob))[..., None]) / np.maximum(a, 1e-6)[..., None]
        img = np.zeros((h, w, 4), np.uint8)
        img[..., :3] = np.clip(col, 0, 255).astype(np.uint8)
        img[..., 3] = np.clip(a * 255 + 0.5, 0, 255).astype(np.uint8)
        Image.fromarray(img, "RGBA").save(OUT / f"{name}.png")
        print(name, w, h)


def knob():
    save("T_UI_Knob", IVORY, disc(40, 40, 20, 20, 17))


def focus_mark():
    # a 34 px x 2 px gold line (2x) centred in 96 x 48, with a soft glow around it
    w, h = 96, 48
    a = np.zeros((h, w), np.float32)
    a[23:25, 31:65] = 1
    glow = np.asarray(Image.fromarray((a * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(7)), np.float32) / 255
    glow = glow / max(glow.max(), 1e-6) * 0.55
    save("T_UI_FocusMark", GOLD, np.maximum(a, glow))


def chip():
    # 32 x 32 at 2x: rounded outline, 2 px (1 px at 1080p), radius 6 px
    w = h = 32
    outer = np.ones((h, w), np.float32)
    ss = 4
    yy, xx = np.mgrid[0:h * ss, 0:w * ss]
    px = (xx + 0.5) / ss
    py = (yy + 0.5) / ss

    def rrect(inset, r):
        cx = np.clip(px, inset + r, w - inset - r)
        cy = np.clip(py, inset + r, h - inset - r)
        return (np.hypot(px - cx, py - cy) <= r).astype(np.float32)

    ring = rrect(0, 6) - rrect(2, 4)
    outer = np.clip(ring, 0, 1).reshape(h, ss, w, ss).mean(axis=(1, 3))
    save("T_UI_Chip", IVORY, outer)  # the .35 opacity is the brush tint


def arrows():
    # the selector arrows: gold triangles, 12 x 14 px at 1080p (24 x 28 drawn)
    w, h = 24, 28
    ss = 4
    yy, xx = np.mgrid[0:h * ss, 0:w * ss]
    px = (xx + 0.5) / ss
    py = (yy + 0.5) / ss
    # right-pointing: tip at (w-3, h/2), base x=3 from y=2 to h-2
    t = (px - 3) / (w - 6)
    half = (h / 2 - 2) * (1 - t)
    m = ((px >= 3) & (px <= w - 3) & (np.abs(py - h / 2) <= half)).astype(np.float32)
    right = m.reshape(h, ss, w, ss).mean(axis=(1, 3))
    save("T_UI_Arrow_R", GOLD, right)
    save("T_UI_Arrow_L", GOLD, right[:, ::-1])


def title_shadow():
    src = Image.open(OUT / "T_Saskarta_TitleName_Ivory.png").convert("RGBA")
    a = src.split()[3].resize((src.width // 4, src.height // 4), Image.LANCZOS)
    pad = 40
    canvas = Image.new("L", (a.width + 2 * pad, a.height + 2 * pad), 0)
    canvas.paste(a, (pad, pad))
    blurred = np.asarray(canvas.filter(ImageFilter.GaussianBlur(8)), np.float32) / 255
    save("T_Saskarta_TitleName_Shadow", (0, 0, 0), np.clip(blurred * 1.2, 0, 1))
    print("shadow pad (at 1/4 scale)", pad)


def soft_plate():
    n, inset = 128, 30
    a = np.zeros((n, n), np.float32)
    a[inset:n - inset, inset:n - inset] = 1.0
    img = Image.fromarray((a * 255).astype(np.uint8), "L").filter(ImageFilter.GaussianBlur(13))
    b = np.asarray(img, np.float32) / 255
    b = b / b.max()
    save("T_UI_SoftPlate", (0, 0, 0), b * b * (3 - 2 * b))  # smoothstep: a dense core, a long soft tail


if __name__ == "__main__" and sys.argv[1:] == ["soft_plate"]:
    soft_plate()
elif __name__ == "__main__":
    title_scrim()
    row_glow()
    toggles()
    knob()
    focus_mark()
    chip()
    arrows()
    title_shadow()
    soft_plate()
