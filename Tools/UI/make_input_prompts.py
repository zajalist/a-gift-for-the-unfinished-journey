"""Build the Saskarta input-prompt icon set from Kenney's "Input Prompts" (CC0).

Offline: reads the vendored SVGs in Tools/UI/ThirdParty/Kenney_InputPrompts_1.5
(copied from kenney_input-prompts_1.5.zip, kenney.nl/assets/input-prompts) and
writes 256x256 RGBA PNGs to Saved/UI/InputPrompts/{light,dark}/, plus
manifest.json and _contact_sheet.png.

Kenney's glyphs are flat white silhouettes with the label knocked out (and a
red accent for the "active" part, e.g. a pressed D-pad arm). The Kenney shape
is kept exactly; this script only re-grades it into a keycap:
  body   = the silhouette with its knock-outs filled
  label  = the knock-outs (engraved, umber on ivory / ivory on dark)
  accent = Kenney's red, recoloured to the stele gold
then adds a keycap skirt, a top-face gradient, a bevel, a thin gold rim, a
contrast outline and the baked drop shadow (0,6 px offset, 8 px blur, 45%).

Work is done at 4x (1024 px) and box-filtered down, so every edge is clean.

Needs: numpy, scipy, Pillow, resvg_py (pip install resvg-py).
Usage: python Tools/UI/make_input_prompts.py [--out Saved/UI/InputPrompts]
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage

try:
    import resvg_py
except ImportError:  # pragma: no cover - environment guard
    sys.exit("resvg_py is missing: pip install resvg-py")

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "Tools/UI/ThirdParty/Kenney_InputPrompts_1.5"
OUT_DEFAULT = ROOT / "Saved/UI/InputPrompts"

SIZE = 256          # output (the @2x of 128)
SS = 4              # supersampling factor
W = SIZE * SS

# (name, device, source svg relative to SRC)
GLYPHS = [
    ("Key_W", "keyboard", "Keyboard_Mouse/keyboard_w.svg"),
    ("Key_A", "keyboard", "Keyboard_Mouse/keyboard_a.svg"),
    ("Key_S", "keyboard", "Keyboard_Mouse/keyboard_s.svg"),
    ("Key_D", "keyboard", "Keyboard_Mouse/keyboard_d.svg"),
    ("Key_R", "keyboard", "Keyboard_Mouse/keyboard_r.svg"),
    ("Key_E", "keyboard", "Keyboard_Mouse/keyboard_e.svg"),  # drawn in Kenney's 64-px key style (not in the vendored 36)
    ("Key_F9", "keyboard", "Keyboard_Mouse/keyboard_f9.svg"),
    ("Key_Space", "keyboard", "Keyboard_Mouse/keyboard_space.svg"),
    ("Key_Esc", "keyboard", "Keyboard_Mouse/keyboard_escape.svg"),
    ("Key_Enter", "keyboard", "Keyboard_Mouse/keyboard_enter.svg"),
    ("Key_Shift", "keyboard", "Keyboard_Mouse/keyboard_shift.svg"),
    ("Key_Tab", "keyboard", "Keyboard_Mouse/keyboard_tab.svg"),
    ("Key_Left", "keyboard", "Keyboard_Mouse/keyboard_arrow_left.svg"),
    ("Key_Right", "keyboard", "Keyboard_Mouse/keyboard_arrow_right.svg"),
    ("Key_Up", "keyboard", "Keyboard_Mouse/keyboard_arrow_up.svg"),
    ("Key_Down", "keyboard", "Keyboard_Mouse/keyboard_arrow_down.svg"),
    ("Mouse", "mouse", "Keyboard_Mouse/mouse.svg"),
    ("Mouse_Move", "mouse", "Keyboard_Mouse/mouse_move.svg"),
    ("Mouse_Left", "mouse", "Keyboard_Mouse/mouse_left.svg"),
    ("Mouse_Right", "mouse", "Keyboard_Mouse/mouse_right.svg"),
    ("Mouse_Scroll", "mouse", "Keyboard_Mouse/mouse_scroll.svg"),
    ("Pad_LStick", "gamepad", "Xbox_Series/xbox_stick_l.svg"),
    ("Pad_RStick", "gamepad", "Xbox_Series/xbox_stick_r.svg"),
    ("Pad_A", "gamepad", "Xbox_Series/xbox_button_a.svg"),
    ("Pad_B", "gamepad", "Xbox_Series/xbox_button_b.svg"),
    ("Pad_X", "gamepad", "Xbox_Series/xbox_button_x.svg"),
    ("Pad_Y", "gamepad", "Xbox_Series/xbox_button_y.svg"),
    ("Pad_DPad_Up", "gamepad", "Xbox_Series/xbox_dpad_up.svg"),
    ("Pad_DPad_Left", "gamepad", "Xbox_Series/xbox_dpad_left.svg"),
    ("Pad_DPad_Right", "gamepad", "Xbox_Series/xbox_dpad_right.svg"),
    ("Pad_DPad_Down", "gamepad", "Xbox_Series/xbox_dpad_down.svg"),
    ("Pad_LB", "gamepad", "Xbox_Series/xbox_lb.svg"),
    ("Pad_RB", "gamepad", "Xbox_Series/xbox_rb.svg"),
    ("Pad_LT", "gamepad", "Xbox_Series/xbox_lt.svg"),
    ("Pad_RT", "gamepad", "Xbox_Series/xbox_rt.svg"),
    ("Pad_Menu", "gamepad", "Xbox_Series/xbox_button_menu.svg"),
    ("Pad_View", "gamepad", "Xbox_Series/xbox_button_view.svg"),
]


def hex3(h: str) -> np.ndarray:
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)], np.float32)


# Stele UI palette. "light" = ivory keycap / umber label, "dark" = the inverse.
THEMES = {
    "light": dict(
        face_top=hex3("#F7F0E1"), face_bot=hex3("#E2D5BB"),   # ~#ECE2CE mid
        skirt_top=hex3("#B39A76"), skirt_bot=hex3("#8A7152"),
        label=hex3("#2A1E16"), label_lip=hex3("#FFFFFF"), label_lip_a=0.45,
        rim=hex3("#D2AE66"), rim_a=(0.30, 0.75),               # (bottom, top)
        accent_top=hex3("#E3C27A"), accent_bot=hex3("#B8893A"),
        outline=hex3("#2A1E16"), outline_a=0.55,
        bevel_hi=0.55, bevel_lo=0.22,
    ),
    "dark": dict(
        face_top=hex3("#3F342C"), face_bot=hex3("#221B16"),
        skirt_top=hex3("#15100C"), skirt_bot=hex3("#0A0806"),
        label=hex3("#ECE2CE"), label_lip=hex3("#000000"), label_lip_a=0.55,
        rim=hex3("#D9B56C"), rim_a=(0.45, 0.95),
        accent_top=hex3("#E3C27A"), accent_bot=hex3("#B8893A"),
        outline=hex3("#ECE2CE"), outline_a=0.30,
        bevel_hi=0.22, bevel_lo=0.35,
    ),
}

# Geometry at output scale (multiplied by SS internally).
SKIRT_PX = 5          # keycap side depth
RIM_PX = 1.75         # gold edge width
OUTLINE_PX = 1.25     # contrast outline
LIP_PX = 1.0          # engraved-label lip offset
SHADOW_DY = 6
SHADOW_SIGMA = 4.0    # an "8 px blur" (CSS/UMG blur radius ~ 2 sigma)
SHADOW_A = 0.45


# ---------------------------------------------------------------- helpers

def render_svg(path: Path) -> np.ndarray:
    png = resvg_py.svg_to_bytes(svg_path=str(path), width=W, height=W)
    im = Image.open(io.BytesIO(bytes(png))).convert("RGBA")
    return np.asarray(im, np.float32) / 255.0


def shift(m: np.ndarray, dy: int, dx: int = 0) -> np.ndarray:
    out = np.zeros_like(m)
    h, w = m.shape
    ys, yd = (slice(0, h - dy), slice(dy, h)) if dy >= 0 else (slice(-dy, h), slice(0, h + dy))
    xs, xd = (slice(0, w - dx), slice(dx, w)) if dx >= 0 else (slice(-dx, w), slice(0, w + dx))
    out[yd, xd] = m[ys, xs]
    return out


def disk(r: float) -> np.ndarray:
    k = int(np.ceil(r))
    y, x = np.mgrid[-k:k + 1, -k:k + 1]
    return (x * x + y * y) <= r * r


def vgrad(mask: np.ndarray, top: np.ndarray, bot: np.ndarray) -> np.ndarray:
    """Vertical gradient top->bot across the mask's own bounding box."""
    rows = np.where(mask.any(axis=1))[0]
    y0, y1 = (rows[0], rows[-1]) if rows.size else (0, W - 1)
    t = np.clip((np.arange(W, dtype=np.float32) - y0) / max(1, y1 - y0), 0, 1)
    col = top[None, :] * (1 - t[:, None]) + bot[None, :] * t[:, None]
    return np.broadcast_to(col[:, None, :], (W, W, 3))


class Canvas:
    """Premultiplied RGBA accumulator with an 'over' operator."""

    def __init__(self):
        self.c = np.zeros((W, W, 3), np.float32)
        self.a = np.zeros((W, W), np.float32)

    def over(self, rgb, alpha):
        alpha = np.clip(alpha, 0, 1).astype(np.float32)
        rgb = np.broadcast_to(rgb, (W, W, 3)) if np.ndim(rgb) == 1 else rgb
        self.c = rgb * alpha[..., None] + self.c * (1 - alpha[..., None])
        self.a = alpha + self.a * (1 - alpha)

    def downsample(self) -> Image.Image:
        c = self.c.reshape(SIZE, SS, SIZE, SS, 3).mean(axis=(1, 3))
        a = self.a.reshape(SIZE, SS, SIZE, SS).mean(axis=(1, 3))
        rgb = np.where(a[..., None] > 1e-6, c / np.maximum(a[..., None], 1e-6), 0)
        out = np.dstack([np.clip(rgb, 0, 1), np.clip(a, 0, 1)])
        return Image.fromarray((out * 255 + 0.5).astype(np.uint8), "RGBA")


# ---------------------------------------------------------------- glyph

def split_kenney(src: np.ndarray):
    """-> body (filled silhouette), label (knock-outs), accent (Kenney red)."""
    a = src[..., 3]
    solid = a > 0.5
    body = ndimage.binary_fill_holes(solid)
    label = body & ~solid
    r, g = src[..., 0], src[..., 1]
    accent = solid & ((r - g) > 0.35)
    return body, label, accent


def build(src: np.ndarray, th: dict) -> Image.Image:
    body, label, accent = split_kenney(src)
    s = SS
    bodyf = body.astype(np.float32)

    # keycap side: the body extruded straight down
    skirt = np.zeros_like(body)
    for dy in range(1, int(SKIRT_PX * s) + 1):
        skirt |= shift(body, dy)
    whole = body | skirt

    cv = Canvas()

    # 1. baked drop shadow
    sh = ndimage.gaussian_filter(shift(whole, int(SHADOW_DY * s)).astype(np.float32), SHADOW_SIGMA * s)
    cv.over(np.zeros(3, np.float32), sh * SHADOW_A)

    # 2. contrast outline (dark on the light cap for bright sky; ivory on the dark cap)
    ring = ndimage.binary_dilation(whole, disk(OUTLINE_PX * s)) & ~whole
    cv.over(th["outline"], ring.astype(np.float32) * th["outline_a"])

    # 3. skirt, darker toward the floor
    cv.over(vgrad(skirt, th["skirt_top"], th["skirt_bot"]), (skirt & ~body).astype(np.float32))

    # 4. top face: gradient + bevel (lit from above)
    face = vgrad(body, th["face_top"], th["face_bot"]).copy()
    blur = ndimage.gaussian_filter(bodyf, 3.0 * s)
    gy = np.gradient(blur, axis=0) * (3.0 * s) * 2.5      # >0 on top edges, <0 on bottom
    hi = np.clip(gy, 0, 1)[..., None] * th["bevel_hi"]
    lo = np.clip(-gy, 0, 1)[..., None] * th["bevel_lo"]
    face = face + (1 - face) * hi
    face = face * (1 - lo)
    # a soft inner glow just inside the upper edge (the key's lit lip)
    dist = ndimage.distance_transform_edt(body)
    lip = np.exp(-dist / (2.5 * s)) * np.clip(gy * 4, 0, 1)
    face = face + (1 - face) * lip[..., None] * 0.35
    cv.over(face, bodyf)

    # 5. gold accent where Kenney had red
    if accent.any():
        acc = vgrad(accent, th["accent_top"], th["accent_bot"])
        cv.over(acc, accent.astype(np.float32))

    # 6. gold edge highlight: a thin rim inside the silhouette, brighter on top
    inner = ndimage.binary_erosion(body, disk(RIM_PX * s))
    rim = (body & ~inner).astype(np.float32)
    up = np.clip(gy * 3, 0, 1)
    rim_a = th["rim_a"][0] + (th["rim_a"][1] - th["rim_a"][0]) * up
    cv.over(th["rim"], rim * rim_a)

    # 7. engraved label: a lit/dark lip just below each stroke, then the label ink
    lipm = shift(label, int(LIP_PX * s)) & ~label & body & ~accent
    cv.over(th["label_lip"], lipm.astype(np.float32) * th["label_lip_a"])
    cv.over(th["label"], label.astype(np.float32))

    return cv.downsample()


# ---------------------------------------------------------------- contact sheet

def contact_sheet(out: Path, items: list[tuple[str, str, Image.Image]]):
    cols, cell = 12, 128
    names = [n for n, v, _im in items if v == "light"]
    rows = (len(names) + cols - 1) // cols
    blocks = [
        ("light caps on the dark UI", "light", "dark"),
        ("light caps on bright sky", "light", "sky"),
        ("dark caps on the dark UI", "dark", "dark"),
        ("dark caps on bright sky", "dark", "sky"),
    ]
    head, lab = 34, 18
    bh = head + rows * (cell + lab)
    sheet = Image.new("RGBA", (cols * cell, bh * len(blocks)), (0, 0, 0, 255))
    try:
        font = ImageFont.truetype("segoeui.ttf", 12)
        hfont = ImageFont.truetype("segoeuib.ttf", 16)
    except OSError:
        font = hfont = ImageFont.load_default()
    lookup = {(n, v): im for n, v, im in items}
    for bi, (title, variant, bg) in enumerate(blocks):
        y0 = bi * bh
        panel = Image.new("RGBA", (cols * cell, bh))
        pd = ImageDraw.Draw(panel)
        for y in range(bh):   # background
            t = y / bh
            if bg == "dark":
                c = (int(26 - 8 * t), int(21 - 6 * t), int(18 - 5 * t), 255)
            else:
                c = (int(150 + 80 * t), int(190 + 50 * t), int(230 + 18 * t), 255)
            pd.line([(0, y), (cols * cell, y)], fill=c)
        ink = (236, 226, 206, 255) if bg == "dark" else (42, 30, 22, 255)
        pd.text((10, 8), f"{title}  ({len(names)} glyphs, shown at 1x = 128 px)", font=hfont, fill=ink)
        for i, n in enumerate(names):
            x, y = (i % cols) * cell, head + (i // cols) * (cell + lab)
            im = lookup[(n, variant)].resize((cell, cell), Image.LANCZOS)
            panel.alpha_composite(im, (x, y))
            pd.text((x + cell // 2, y + cell + 2), n, font=font, fill=ink, anchor="mt")
        sheet.alpha_composite(panel, (0, y0))
    sheet.convert("RGB").save(out / "_contact_sheet.png", optimize=True)


# ---------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=OUT_DEFAULT)
    ap.add_argument("--src", type=Path, default=SRC)
    args = ap.parse_args()

    if not (args.src / "License.txt").exists():
        sys.exit(f"Kenney source not found at {args.src}")

    items, manifest = [], []
    for variant in THEMES:
        (args.out / variant).mkdir(parents=True, exist_ok=True)
    for name, device, rel in GLYPHS:
        src = render_svg(args.src / rel)
        for variant, th in THEMES.items():
            im = build(src, th)
            a = np.asarray(im)[..., 3]
            edge = max(a[0].max(), a[-1].max(), a[:, 0].max(), a[:, -1].max())
            if edge > 8:
                print(f"WARN {name}/{variant}: alpha {edge} touches the canvas edge")
            fn = f"T_Prompt_{name}.png"
            im.save(args.out / variant / fn, optimize=True)
            items.append((name, variant, im))
            manifest.append({
                "name": name, "device": device, "variant": variant,
                "file": f"{variant}/{fn}", "size": [SIZE, SIZE],
                "source": f"Kenney Input Prompts 1.5 (CC0): {Path(rel).name}",
            })
        print(f"{name:16s} {device}")

    (args.out / "manifest.json").write_text(json.dumps({
        "set": "Saskarta input prompts",
        "source": "Kenney 'Input Prompts' 1.5 (1.5A, 11-07-2026), https://kenney.nl/assets/input-prompts, CC0",
        "generator": "Tools/UI/make_input_prompts.py",
        "shadow": {"offset": [0, SHADOW_DY], "blur_px": SHADOW_SIGMA * 2, "opacity": SHADOW_A},
        "glyphs": manifest,
    }, indent=2) + "\n", encoding="utf-8")
    contact_sheet(args.out, items)
    print(f"{len(GLYPHS)} glyphs x {len(THEMES)} variants -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
