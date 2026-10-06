"""gen_lid_notes: the capsule lid's underside (storyline-first-light.md 4.5, B19) as a PLACEHOLDER texture.

    python Tools/Story/gen_lid_notes.py               # -> Saved/Story/LidNotes/T_FL_LidNotes_PLACEHOLDER.png (2048^2)
    python Tools/Story/gen_lid_notes.py --stencils    # also T_FL_Stencil_01..07.png, the wreck numbers (512^2, alpha)

PLACEHOLDER until the author supplies the hand-lettering: typed fonts already in the repo stand in for the many hands
(Cormorant for ink, Cormorant italic for pencil, Aref Ruqaa for the older hand, VT323 for the stencil). The Saskartan
head-words are NOT invented here: each shows as a bracketed slot, [SK kettle], for the author to letter. Every sheet
carries a small PLACEHOLDER mark in a corner.

Layout (InteriorCam looks straight up a hand's width away; at 1080p about eight notes read): notes 1, 2, 4, 5, 6,
19, 20 and 21 large and central, LIGHT: LEAVE ONE ON in the centre, the rest small round the edges as texture.
Deterministic (seeded): the same run gives the same image.
"""
from __future__ import annotations

import math
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "Saved" / "Story" / "LidNotes"
FONTS = {
    "ink": ROOT / "Saved" / "Fonts" / "CormorantGaramond-VariableFont_wght.ttf",
    "pencil": ROOT / "Saved" / "Fonts" / "CormorantGaramond-Italic-VariableFont_wght.ttf",
    "old": ROOT / "SourceArt" / "Fonts" / "ArefRuqaa-Regular.ttf",
    "caps": ROOT / "Saved" / "Fonts" / "Cinzel-VariableFont_wght.ttf",
    "stencil": ROOT / "Saved" / "Fonts" / "VT323-Regular.ttf",
}
INK = {"pencil": (92, 88, 82), "ink": (34, 38, 58), "old": (70, 44, 30), "faded": (120, 96, 70), "red": (128, 40, 32),
       "crayon": (170, 90, 40), "new": (20, 20, 24)}
SIZE = 2048

# (text, hand, colour, size px, centre (u, v) 0..1, angle deg, [later hand's addition])
LARGE = [
    ("[SK kettle]: sings when ready", "pencil", "pencil", 62, (0.30, 0.30), -4, None),
    ("[SK goat]: has a name, eats washing (?)", "ink", "ink", 54, (0.70, 0.27), 3, None),
    ("fourth step = full", "old", "old", 60, (0.26, 0.62), 6, None),
    ("GATE: Tashen's. at Goose Rest.\nnoon means noon.", "ink", "ink", 50, (0.72, 0.64), -3,
     ("he goes home in the end. listen to all of it.", "pencil", "faded", 34)),
    ("first light: ?", "ink", "new", 70, (0.50, 0.80), -1, None),
]
SMALL = [
    ("IY-LA'HAR-DZEHIY: the goat. one horn. going up.", "ink", "ink"),
    ("[SK washing]: bring it in (wind)", "pencil", "pencil"),
    ("[SK swallows]: they know first", "old", "old"),
    ("[SK apricot]: a fruit. on roofs.", "ink", "faded"),
    ("[SK rain]: water that falls. from where? / they asked for it three years.", "pencil", "pencil"),
    ("[SK heron]: a bird (bird = ?) / stands on one leg. looks at the water like it's owed money.", "ink", "ink"),
    ("[SK chairs]: kept. stacked by the wall.", "old", "old"),
    ("[SK window]: a hole to look out of", "pencil", "faded"),
    ("[SK sky]: above the cloud (above = ?)", "ink", "ink"),
    ("[SK sun]: over the cloud. he laughed. at what?", "pencil", "pencil"),
    ("[SK morning]: the bread's in. the cloud goes up.", "old", "old"),
    ("\"you, on the road\": us?  / no.", "ink", "ink"),
    ("keep the wall on your left", "pencil", "pencil"),
    ("that isn't the top", "ink", "faded"),
    ("tea: goes cold if you talk", "old", "old"),
    ("walnut: a tree. older than the radio.", "ink", "ink"),
    ("echo: says it back twice", "pencil", "pencil"),
    ("bench: for waiting", "ink", "faded"),
    ("the Knees: the worst of it (it never was)", "old", "old"),
    ("waystation: somebody was there before you.", "pencil", "pencil"),
]


def font(hand, px):
    return ImageFont.truetype(str(FONTS[hand]), px)


def stamp(base, text, hand, colour, px, centre, angle, alpha=235):
    f = font(hand, px)
    d = ImageDraw.Draw(Image.new("L", (1, 1)))
    box = d.multiline_textbbox((0, 0), text, font=f, spacing=px // 4)
    w, h = box[2] - box[0] + 40, box[3] - box[1] + 40
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(layer).multiline_text((20 - box[0], 20 - box[1]), text, font=f, fill=INK[colour] + (alpha,), spacing=px // 4)
    layer = layer.rotate(angle, resample=Image.BICUBIC, expand=True)
    x, y = int(centre[0] * SIZE - layer.width / 2), int(centre[1] * SIZE - layer.height / 2)
    base.alpha_composite(layer, (max(0, x), max(0, y)))


def paper(rng):
    img = Image.new("RGBA", (SIZE, SIZE), (196, 184, 160, 255))
    d = ImageDraw.Draw(img)
    for _ in range(90):  # overlapping slips of paper, decades of them
        x, y = rng.randrange(-100, SIZE), rng.randrange(-100, SIZE)
        w, h = rng.randrange(260, 620), rng.randrange(140, 380)
        tone = rng.randrange(170, 226)
        d.rectangle((x, y, x + w, y + h), fill=(tone, tone - 10, tone - 34, 255), outline=(tone - 40, tone - 48, tone - 70, 255))
    return img


def goat(base, centre, scale):
    """The child's crayon goat, drawn wrong: two horns, legs like a table (note 6)."""
    d = ImageDraw.Draw(base)
    cx, cy = centre[0] * SIZE, centre[1] * SIZE
    c = INK["crayon"] + (255,)
    s = scale
    d.rounded_rectangle((cx - 110 * s, cy - 40 * s, cx + 110 * s, cy + 40 * s), 30 * s, outline=c, width=int(9 * s))
    for lx in (-85, -40, 40, 85):
        d.line((cx + lx * s, cy + 40 * s, cx + lx * s, cy + 120 * s), fill=c, width=int(9 * s))
    d.ellipse((cx + 95 * s, cy - 95 * s, cx + 175 * s, cy - 25 * s), outline=c, width=int(9 * s))
    d.line((cx + 115 * s, cy - 90 * s, cx + 100 * s, cy - 150 * s), fill=c, width=int(8 * s))
    d.line((cx + 150 * s, cy - 90 * s, cx + 170 * s, cy - 150 * s), fill=c, width=int(8 * s))
    stamp(base, "IY-LA'HAR-DZEHIY", "pencil", "crayon", int(40 * s), (centre[0], centre[1] + 0.085 * s), 2)


def tally(base, rng, origin, count=420):
    d = ImageDraw.Draw(base)
    x0, y0 = origin[0] * SIZE, origin[1] * SIZE
    for i in range(count):
        g, k = divmod(i, 5)
        col, row = g % 14, g // 14
        x, y = x0 + col * 34, y0 + row * 30
        c = INK[rng.choice(["pencil", "ink", "faded", "old"])] + (220,)
        if k < 4:
            d.line((x + k * 6, y, x + k * 6 + rng.uniform(-2, 2), y + 22), fill=c, width=2)
        else:
            d.line((x - 3, y + 18, x + 24, y + 4), fill=c, width=2)


def lid(seed=582):
    rng = random.Random(seed)
    img = paper(rng)
    # the rest as texture, round the edges
    ring = len(SMALL)
    for i, (text, hand, colour) in enumerate(SMALL):
        a = 2 * math.pi * i / ring + rng.uniform(-0.08, 0.08)
        r = rng.uniform(0.34, 0.41)
        centre = (0.5 + r * math.cos(a), 0.5 + r * math.sin(a))
        stamp(img, text.replace(" / ", "\n"), hand, colour, rng.randrange(24, 32), centre, rng.uniform(-12, 12), 200)
    tally(img, rng, (0.05, 0.05))
    # the large, central eight
    for text, hand, colour, px, centre, angle, later in LARGE:
        stamp(img, text, hand, colour, px, centre, angle)
        if later:
            stamp(img, later[0], later[1], later[2], later[3], (centre[0], centre[1] + 0.07), angle + 2)
    goat(img, (0.57, 0.35), 1.0)
    for k in range(4):  # LIGHT: LEAVE ONE ON, re-inked by later hands
        stamp(img, "LIGHT: LEAVE ONE ON", "caps", ["faded", "old", "ink", "red"][k], 92,
              (0.5 + 0.0015 * k, 0.51 + 0.001 * k), -1 + 0.4 * k, 120 + 40 * k)
    stamp(img, "582", "stencil", "new", 120, (0.40, 0.90), 0)
    stamp(img, "SAMYOR", "pencil", "new", 46, (0.52, 0.905), -6)
    stamp(img, "PLACEHOLDER - author's hand-lettering to come", "stencil", "red", 28, (0.82, 0.975), 0, 255)
    return img


def stencil(n):
    img = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    f = font("stencil", 420)
    d = ImageDraw.Draw(img)
    text = f"{n:02d}"
    box = d.textbbox((0, 0), text, font=f)
    d.text(((512 - (box[2] - box[0])) / 2 - box[0], (512 - (box[3] - box[1])) / 2 - box[1]), text, font=f, fill=(235, 230, 220, 255))
    return img


def main(argv):
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "T_FL_LidNotes_PLACEHOLDER.png"
    lid().convert("RGB").save(path)
    print("wrote", path.relative_to(ROOT).as_posix())
    if "--stencils" in argv:
        for n in range(1, 8):
            p = OUT / f"T_FL_Stencil_{n:02d}.png"
            stencil(n).save(p)
        print("wrote T_FL_Stencil_01..07.png")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
