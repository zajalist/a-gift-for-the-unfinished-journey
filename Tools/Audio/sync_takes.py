#!/usr/bin/env python3
"""Import every take in Saved/RadioRecordings/selected whose sound asset is missing or older than its WAV: the
author's new recordings, re-aged takes, the scanner-voice pillar readings and the narrator's tail. It uses
import_game_audio's batches (4 per python_run, each checks for PIE first, saves only what it imported).

    python Tools/Audio/sync_takes.py --dry-run   # list what would be imported
    python Tools/Audio/sync_takes.py             # import (the editor must be open, no PIE)

Destinations: show segments -> /Game/SaskartaGaea/Audio/Station/Host/VO_Station_<ID> (settings copied from STN_ID_01,
routed like the other show takes); RADIO_B*/IDLE_* and the ending lines (SHOW_A5_TAIL_*, BELOW_*, SAMYOR_*) ->
/Game/SaskartaGaea/Audio/Lines/<ID>; the pillar readings INSCR_* -> /Game/SaskartaGaea/Audio/CarrierVoice/VO_Carrier_<ID>.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import import_game_audio as g  # noqa: E402

SEL = g.ROOT / "Saved" / "RadioRecordings" / "selected"
CONTENT = g.ROOT / "Content"


def asset_file(dest: str, name: str) -> Path:
    return CONTENT / dest[len("/Game/"):] / (name + ".uasset")


def stale(job) -> bool:
    src, dest, name = Path(job[0]), job[1], job[2]
    a = asset_file(dest, name)
    return src.is_file() and (not a.is_file() or src.stat().st_mtime > a.stat().st_mtime)


def main() -> int:
    data = g.json.loads((g.ROOT / "docs" / "story" / "station.json").read_text(encoding="utf-8"))
    cats = g.SHOW_CATEGORIES | {"SONGIN", "SONGOUT", "ROOM"}  # the importer's show step misses these three
    ids = [x["id"] for x in data["segments"] if x.get("category") in cats]
    show = [j for j in ((str(SEL / (i + ".wav")).replace("\\", "/"), g.HOST_DEST, "VO_Station_" + i, False) for i in ids) if stale(j)]
    other = [j for j in g.radio_jobs() if stale(j)]
    for p in sorted(SEL.glob("*.wav")):
        i = p.stem
        if i.startswith("INSCR_"):
            j = (p.as_posix(), "/Game/SaskartaGaea/Audio/CarrierVoice", "VO_Carrier_" + i, False)
        elif i.startswith(("SHOW_A5_TAIL", "BELOW_", "SAMYOR_")):
            j = (p.as_posix(), "/Game/SaskartaGaea/Audio/Lines", i, False)
        else:
            continue
        if stale(j):
            other.append(j)
    print(f"{len(show)} show takes and {len(other)} other lines to import")
    for j in show + other:
        print("  ", j[1] + "/" + j[2])
    if "--dry-run" in sys.argv:
        return 0
    g.run_batches(show, ref=g.SHOW_REF, route=True)
    g.run_batches(other)
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
