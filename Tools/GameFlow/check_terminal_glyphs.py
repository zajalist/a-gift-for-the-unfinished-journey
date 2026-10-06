#!/usr/bin/env python3
"""Check that the boot-terminal fonts cover every character the terminal can show.

The characters come from the specs themselves, so an edited boot line is checked too:
every text/string variable default in BPC_CarrierVision.json and
WBP_Saskarta_BootLog.graph.json, every string literal the widget graph concatenates,
the memory counter's digits and "K", and the cursor candidates.

    python Tools/GameFlow/check_terminal_glyphs.py

Exit status 1 when the primary font (VT323) misses a character, or when a boot string
is not uppercase ASCII (the spec forbids arrows, dashes and degree signs; the one
exception is Â, for the author's name ÂLAAWB, which both fonts cover).
Needs fontTools (pip install fonttools).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parents[2]
SPECS = ROOT / "Tools" / "GameFlow" / "specs"
FONTS = ROOT / "Saved" / "Fonts"
PRIMARY = "VT323-Regular.ttf"
ALTERNATIVE = "Glass_TTY_VT220.ttf"
FULL_BLOCK = "█"
ALLOWED = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 -_>/.[]():Â")  # Â: the author's ÂLAAWB (2026-09-28); both fonts have U+00C2


def strings_from_specs() -> list[str]:
    out = []
    for name in ("BPC_CarrierVision.json", "WBP_Saskarta_BootLog.graph.json"):
        spec = json.loads((SPECS / name).read_text(encoding="utf-8"))
        for v in spec["variables"]:
            if v["type"] in ("text", "string") and v.get("default"):
                out.append(v["default"])
        for g in spec["graphs"]:
            for key, value in g.get("defaults", {}).items():
                node = g["nodes"][key.split(".")[0]]
                if node.get("call") == "Concat_StrStr":
                    out.append(value)
    out.append("0123456789K")  # memory counter
    return out


def main() -> int:
    strings = strings_from_specs()
    chars = sorted(set("".join(strings)))
    bad = False
    for s in strings:
        extra = set(s) - ALLOWED
        if extra:
            print(f"FAIL  not uppercase ASCII: {s!r} uses {sorted(extra)}")
            bad = True
    print(f"boot strings: {len(strings)}, distinct characters: {len(chars)}: {''.join(chars)!r}")
    for font in (PRIMARY, ALTERNATIVE):
        cmap = TTFont(FONTS / font).getBestCmap()
        missing = [c for c in chars if ord(c) not in cmap]
        block = ord(FULL_BLOCK) in cmap
        verdict = "ok" if not missing else "MISSING " + " ".join(f"U+{ord(c):04X}" for c in missing)
        print(f"{font:24s} {verdict}; full block U+2588: {'yes' if block else 'no -> cursor is _'}")
        if missing and font == PRIMARY:
            bad = True
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
