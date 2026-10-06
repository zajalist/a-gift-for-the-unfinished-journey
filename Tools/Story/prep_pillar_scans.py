"""The road texts (W01-W12) onto their steles, offline: placeholder scans, clean ink, carve, stele rows.

    python Tools/Story/prep_pillar_scans.py            # all W texts that have the author's Saskartan
    python Tools/Story/prep_pillar_scans.py --force    # also redraw existing placeholder scans
    then: python Tools/Story/build_inscription_atlas.py

Per W text whose Saskartan is in docs/story/inscriptions.json (not AUTHOR / empty):
  1. source = SourceArt/Inscriptions/<ID>_scan.png (the author's hand) when it exists, else
     <ID>_scan_placeholder.png, drawn here if missing. A placeholder is the author's exact spelling in
     Latin letters (ArefRuqaa), one word per line, with a little jitter and weight variation: it only
     keeps the right text on the right stone until the hand scan exists. It never invents Saskartan
     script, and a real <ID>_scan.png is never written.
  2. T_Inscription_<ID>.png: the ink as alpha (dark strokes on white or transparent), cropped to the
     ink, 2048 px on the long side (the I02 / I05 convention).
  3. carve_inscription.carve(<ID>): the _H / _N / _AO chisel maps.
  4. inscriptions.json: every stele whose planned_inscription is a carved text now carries it
     (inscription = planned, wear = planned_wear); ink_cm follows the ink's aspect; status
     "placeholder_carved" or "in_atlas" (the atlas script gives the cell).
W04 and W12 stay AUTHOR, so their steles keep I05 "The Way".
"""
import argparse
import json
import pathlib
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Tools" / "Story"))
import carve_inscription  # noqa: E402

DATA = ROOT / "docs" / "story" / "inscriptions.json"
INSCR = ROOT / "SourceArt" / "Inscriptions"
FONT = ROOT / "SourceArt" / "Fonts" / "ArefRuqaa-Bold.ttf"
SCAN_W, SCAN_H = 960, 1280
LONG_SIDE = 2048
MACRON = {"ā": "a", "ē": "e", "ī": "i", "ō": "o", "ū": "u"}
MAX_INK_CM = (32.0, 60.0)          # inside the way-stones' flat glyph box (32.9 x 60 cm, SourceArt/Steles/steles.json)


def has_text(r):
    return r["saskartan"] not in ("AUTHOR", "", None)


def draw_placeholder(gid, text, seed):
    """Dark strokes on transparent, 960 x 1280, one word per line, hand-cut jitter."""
    rng = np.random.default_rng(seed)
    words = text.replace(". ", ".\n").replace(": ", ":\n").replace(", ", ",\n").split()
    extra = None
    if gid == "W06":                                   # the name scratched through, 6-8 cut beside it
        words, extra = [text], "6-8"
    lines = words
    size = 150
    font = ImageFont.truetype(str(FONT), size)
    while True:
        widths = [font.getbbox(w)[2] for w in lines]
        if max(widths) <= SCAN_W * 0.8 and len(lines) * size * 1.15 <= SCAN_H * 0.8:
            break
        size -= 6
        font = ImageFont.truetype(str(FONT), size)
    ink = np.zeros((SCAN_H, SCAN_W), np.float32)
    line_h = size * 1.15
    y = (SCAN_H - line_h * (len(lines) + (1 if extra else 0))) / 2
    for w in lines:
        # letter by letter: each glyph nudged and slightly rotated, like a hand-cut line
        x = (SCAN_W - font.getbbox(w)[2]) / 2
        for ch in w:
            adv = font.getlength(ch)
            if ch.strip():
                tile = Image.new("L", (int(size * 2), int(size * 2)), 0)
                base = MACRON.get(ch, ch)             # the font has no macron vowels: base letter + bar
                td = ImageDraw.Draw(tile)
                td.text((size * 0.5, size * 0.3), base, font=font, fill=255)
                if base != ch:
                    td.line([(size * 0.5 + adv * 0.15, size * 0.8), (size * 0.5 + adv * 0.85, size * 0.8)],
                            fill=255, width=max(3, size // 14))
                tile = tile.rotate(rng.normal(0, 3.0), resample=Image.Resampling.BICUBIC)
                t = np.asarray(tile, np.float32) / 255
                ox = int(x - size * 0.5 + rng.normal(0, 2.0))
                oy = int(y - size * 0.3 + rng.normal(0, 3.0))
                y0, x0 = max(0, oy), max(0, ox)
                y1, x1 = min(SCAN_H, oy + t.shape[0]), min(SCAN_W, ox + t.shape[1])
                ink[y0:y1, x0:x1] = np.maximum(ink[y0:y1, x0:x1], t[y0 - oy:y1 - oy, x0 - ox:x1 - ox])
            x += adv
        if extra:                                      # two scratches through the name
            d = Image.fromarray((ink * 255).astype(np.uint8))
            dr = ImageDraw.Draw(d)
            x0 = (SCAN_W - font.getbbox(w)[2]) / 2 - 10
            x1 = x0 + font.getbbox(w)[2] + 20
            for k in range(2):
                yy = y + size * (0.78 + 0.14 * k)
                dr.line([(x0, yy + rng.normal(0, 6)), (x1, yy + rng.normal(0, 6))], fill=255, width=9)
            ink = np.asarray(d, np.float32) / 255
        y += line_h
    if extra:
        d = Image.fromarray((ink * 255).astype(np.uint8))
        dr = ImageDraw.Draw(d)
        dr.text(((SCAN_W - font.getbbox(extra)[2]) / 2, y), extra, font=font, fill=255)
        ink = np.asarray(d, np.float32) / 255
    # weight variation: slow noise thickens / thins the strokes a little
    small = rng.random((SCAN_H // 80, SCAN_W // 80))
    wmap = ndimage.zoom(small, (SCAN_H / small.shape[0], SCAN_W / small.shape[1]), order=3)[:SCAN_H, :SCAN_W]
    soft = ndimage.gaussian_filter(ink, 2.0)
    ink = np.clip((soft - (0.55 - 0.25 * wmap)) * 8, 0, 1)
    rgba = np.zeros((SCAN_H, SCAN_W, 4), np.uint8)
    rgba[..., 3] = (ink * 255).astype(np.uint8)
    return Image.fromarray(rgba, "RGBA")


def ink_of(img):
    """Ink 0..1 from a scan: alpha x darkness (works for dark-on-white and dark-on-transparent)."""
    a = np.asarray(img.convert("RGBA"), np.float32) / 255
    lum = 0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]
    return np.clip((1 - lum) * a[..., 3] * 1.4 - 0.2, 0, 1)


def clean(gid, src):
    ink = ink_of(Image.open(src))
    ys, xs = np.nonzero(ink > 0.5)
    if not len(ys):
        raise SystemExit(f"{src}: no ink")
    m = 6
    ink = ink[max(0, ys.min() - m):ys.max() + m + 1, max(0, xs.min() - m):xs.max() + m + 1]
    k = LONG_SIDE / max(ink.shape)
    img = Image.fromarray((ink * 255).astype(np.uint8), "L").resize(
        (max(1, round(ink.shape[1] * k)), max(1, round(ink.shape[0] * k))), Image.Resampling.LANCZOS)
    rgba = Image.new("RGBA", img.size, (0, 0, 0, 0))
    rgba.putalpha(img)
    rgba.save(INSCR / f"T_Inscription_{gid}.png", optimize=True)
    return img.size


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--force", action="store_true", help="redraw existing placeholder scans")
    a = ap.parse_args(argv)
    data = json.loads(DATA.read_text(encoding="utf-8"))
    rows = {r["id"]: r for r in data["inscriptions"]}
    carved = {"I02", "I05"}
    for gid, r in sorted(rows.items()):
        if not gid.startswith("W") or not has_text(r):
            continue
        real = INSCR / f"{gid}_scan.png"
        ph = INSCR / f"{gid}_scan_placeholder.png"
        if real.exists():
            src, kind = real, "author scan"
        else:
            if a.force or not ph.exists():
                draw_placeholder(gid, r["saskartan"], seed=int(gid[1:]) * 7 + 3).save(ph, optimize=True)
            src, kind = ph, "placeholder"
        w, h = clean(gid, src)
        carve_inscription.carve(gid)
        aspect = w / h
        hcm = min(MAX_INK_CM[1], MAX_INK_CM[0] / aspect)
        r["ink_cm"] = [round(hcm * aspect, 1), round(hcm, 1)]
        r["status"] = "in_atlas" if kind == "author scan" else "placeholder_carved"
        r["scan"] = src.relative_to(ROOT).as_posix()
        carved.add(gid)
        print(f"{gid}: {kind} {src.name} -> ink {w}x{h}px, ink_cm {r['ink_cm']}")
    for s in data["steles"]:
        p = s["planned_inscription"]
        if p in carved and s["inscription"] != p:
            s["inscription"] = p
            s["wear"] = s.get("planned_wear", s["wear"])
    DATA.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    uniq = sorted({s["inscription"] for s in data["steles"]})
    print(f"steles now carry {len(uniq)} texts: {' '.join(uniq)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
