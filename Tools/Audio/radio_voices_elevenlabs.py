#!/usr/bin/env python3
"""Placeholder takes for the NEIGHBOUR and VISITOR radio lines, from ElevenLabs.

Natural human voices, NOT robotised and NOT tape-filtered (the game applies the archive /
radio filter at runtime). Each take is written where the user's own selected takes go,
Saved/RadioRecordings/selected/<ID>.wav, so the station and story import pipeline picks
it up, and is listed in _tts_manifest.json there so the user's real takes can replace it.
KEEPER lines (the user records them) and breaths are never touched.

    python Tools/Audio/radio_voices_elevenlabs.py --dry-run     # what would be fetched, and the characters
    python Tools/Audio/radio_voices_elevenlabs.py --test        # one short line per speaker
    python Tools/Audio/radio_voices_elevenlabs.py               # every missing line, story + idle first
    python Tools/Audio/radio_voices_elevenlabs.py --only STN_ID_01 STN_ID_02
    python Tools/Audio/radio_voices_elevenlabs.py --force ...   # regenerate even if <ID>.wav exists

A line whose <ID>.wav already exists is skipped (it may be the user's take). Stage
directions in the text ("(beat)", "(pause)", "(2 s pause)") are not spoken: the line is
spoken in one request and the silence is inserted afterwards at that point, using the
API's character timings. The Saskartan words are respelled for the TTS as the recording
script gives them. The run stops cleanly on the first API refusal (for example an
exhausted character quota) and says what is left. The key handling is carrier_elevenlabs's.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import carrier_elevenlabs as ce  # noqa: E402
import make_carrier_voice as mcv  # noqa: E402

SR = ce.SR
PROJECT = mcv.PROJECT_ROOT
TSV = PROJECT / "docs" / "story" / "radio-lines-for-translation.tsv"
OUT = PROJECT / "Saved" / "RadioRecordings" / "selected"
CACHE = PROJECT / "Saved" / "RadioRecordings" / ".elevenlabs_cache"  # outside selected/: the importer scans it
MANIFEST = OUT / "_tts_manifest.json"
MODEL = "eleven_multilingual_v2"
LUFS = -18.0
LIMIT_DBFS = -1.5  # sample-peak ceiling; -1.2 let one long take reach -0.6 dBTP

SPEAKERS = {
    # warm, older valley local; unhurried, dry
    "NEIGHBOUR": {"voice_id": "JBFqnCBsd6RMkjVDRZzb", "voice_name": "George",
                  "settings": {"stability": 0.55, "similarity_boost": 0.75, "style": 0.15,
                               "use_speaker_boost": True, "speed": 0.93}},
    # left for the lowlands and came back; measured, careful
    "VISITOR": {"voice_id": "pFZP5JQG7iQjIQuC4Bku", "voice_name": "Lily",
                "settings": {"stability": 0.50, "similarity_boost": 0.75, "style": 0.10,
                             "use_speaker_boost": True, "speed": 0.95}},
}
# The works' three advertisements (SHOW_A2_07..09), each in its own voice (the author, 2026-09-29: "the voice for the
# different advertising must be different"). Final takes, not placeholders for the author.
AD_SETTINGS = {"stability": 0.35, "similarity_boost": 0.75, "style": 0.45, "use_speaker_boost": True, "speed": 1.02}
LINE_VOICES = {
    "SHOW_A2_07": {"voice_id": "cgSgspJ2msm6clMCkdW9", "voice_name": "Jessica", "settings": AD_SETTINGS},
    "SHOW_A2_08": {"voice_id": "cjVigY5qzO86Huf0OWal", "voice_name": "Eric", "settings": AD_SETTINGS},
    "SHOW_A2_09": {"voice_id": "pqHfZKP75CvOlQylNhV4", "voice_name": "Bill", "settings": AD_SETTINGS},
}
TEST_LINES = {"NEIGHBOUR": "STN_ID_03", "VISITOR": "IDLE_MIDDLE_08"}
# Group order: story and idle first (the game needs them most), then the station by how
# often a category airs.
GROUP_ORDER = ("Story", "Idle", "Station")
STATION_ORDER = ("STN_ID", "STN_INTRO", "STN_OUTRO", "STN_REQUEST", "STN_WEATHER", "STN_NOTICE",
                 "STN_DEDIC", "STN_TALK", "STN_KITCHEN", "STN_LETTER")
# Respellings from recording-script.md ("Saskartan words", "Names").
RESPELL = {"ehbîket": "eh-bee-ket", "kushiân": "koo-shee-an", "diyal": "dee-yal",
           "zmerban": "zmehr-ban", "Samyâr": "Sam-yar"}
PAUSE_S = {"beat": 0.6, "pause": 1.2}
HEAD_S, TAIL_S = 0.05, 0.25


# --------------------------------------------------------------------------- lines

def parse_english(english: str) -> tuple[str, list[tuple[int, float]]]:
    """'"A." (beat) "B."' -> ('A. B.', [(index of 'B' in the text, 0.6)])."""
    parts = re.findall(r'"([^"]*)"|\(([^)]*)\)', english)
    if not parts:
        return english.strip(), []
    text, pauses, pending = "", [], 0.0
    for quoted, direction in parts:
        if direction:
            d = direction.strip().lower()
            m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*s\s*pause", d)
            pending += float(m.group(1)) if m else PAUSE_S.get(d, 0.0)
            continue
        seg = quoted.strip()
        if not seg:
            continue
        if text:
            text += " "
            if pending:
                pauses.append((len(text), pending))
        pending = 0.0
        text += seg
    return text, pauses


def respell(text: str, pauses: list[tuple[int, float]]) -> tuple[str, list[tuple[int, float]]]:
    for word, spoken in RESPELL.items():
        while word in text:
            i = text.index(word)
            delta = len(spoken) - len(word)
            text = text[:i] + spoken + text[i + len(word):]
            pauses = [(k + delta if k > i else k, s) for k, s in pauses]
    return text, pauses


def load_lines() -> list[dict]:
    rows = []
    with TSV.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            speaker = (r.get("Speaker") or "").strip()
            if speaker not in SPEAKERS and (r.get("ID (slate)") or "").strip() not in LINE_VOICES:
                continue
            text, pauses = respell(*parse_english(r.get("English") or ""))
            rows.append({"id": r["ID (slate)"].strip(), "speaker": speaker, "group": r["Group"].strip(),
                         "text": text, "pauses": pauses})

    def order(row: dict) -> tuple:
        g = GROUP_ORDER.index(row["group"]) if row["group"] in GROUP_ORDER else len(GROUP_ORDER)
        prefix = row["id"].rsplit("_", 1)[0]
        s = STATION_ORDER.index(prefix) if prefix in STATION_ORDER else len(STATION_ORDER)
        return g, s
    return sorted(rows, key=order)  # stable: TSV order within a category


# ------------------------------------------------------------------------- render

def insert_pauses(audio: np.ndarray, alignment: dict, pauses: list[tuple[int, float]]) -> np.ndarray:
    """Adds silence at each (char index, seconds): the gap the voice left there is topped up
    to ``seconds``, cut in at the middle of that gap."""
    starts = alignment.get("character_start_times_seconds") or []
    ends = alignment.get("character_end_times_seconds") or []
    cuts = []
    for k, seconds in pauses:
        if k >= len(starts) or k < 2:
            continue
        prev_end, next_start = float(ends[k - 2]), float(starts[k])  # k - 1 is the joining space
        extra = seconds - max(0.0, next_start - prev_end)
        if extra > 0:
            cuts.append((int((prev_end + next_start) / 2 * SR), int(extra * SR)))
    out, last = [], 0
    for at, n in sorted(cuts):
        out += [audio[last:at], np.zeros(n)]
        last = at
    out.append(audio[last:])
    return np.concatenate(out)


def trim(audio: np.ndarray) -> np.ndarray:
    first, end = mcv._active_span(audio, -50.0)
    return audio[max(0, first - int(HEAD_S * SR)):min(len(audio), end + int(TAIL_S * SR))]


def load_manifest() -> dict[str, dict]:
    if MANIFEST.is_file():
        return {e["id"]: e for e in json.loads(MANIFEST.read_text(encoding="utf-8"))}
    return {}


def save_manifest(entries: dict[str, dict]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    mcv.write_json(MANIFEST, sorted(entries.values(), key=lambda e: e["id"]))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--test", action="store_true", help="one short line per speaker")
    ap.add_argument("--only", nargs="+", metavar="ID")
    ap.add_argument("--force", action="store_true", help="regenerate even if <ID>.wav exists")
    args = ap.parse_args()

    ce.LIMIT_DBFS = LIMIT_DBFS
    lines = load_lines()
    if args.test:
        lines = [row for row in lines if row["id"] in TEST_LINES.values()]
    if args.only:
        lines = [row for row in lines if row["id"] in args.only]
    todo = [row for row in lines if args.force or not (OUT / f"{row['id']}.wav").is_file()]
    need = sum(len(row["text"]) for row in todo)
    print(f"{len(lines)} line(s) selected, {len(todo)} to render, {need} characters at most "
          f"(cached takes cost nothing)")
    if args.dry_run:
        for row in todo:
            p = "".join(f" [+{s:g}s@{k}]" for k, s in row["pauses"])
            print(f"  {row['id']:<16} {row['speaker']:<9} {len(row['text']):4d}{p}  {row['text'][:70]}")
        return 0

    manifest = load_manifest()
    failed = None
    for n, row in enumerate(todo):
        spk = LINE_VOICES.get(row["id"]) or SPEAKERS[row["speaker"]]
        try:
            audio, alignment = ce.tts_raw(spk["voice_id"], row["text"], MODEL, spk["settings"], CACHE)
        except ce.ElevenLabsError as exc:
            failed = (row, exc)
            break
        x = ce.loudnorm(trim(insert_pauses(audio, alignment, row["pauses"])), LUFS)
        ce.write(OUT / f"{row['id']}.wav", x, root=OUT)
        manifest[row["id"]] = {"id": row["id"], "speaker": row["speaker"], "voice_id": spk["voice_id"],
                               "voice_name": spk["voice_name"], "model": MODEL, "settings": spk["settings"],
                               "chars": len(row["text"]), "spoken_text": row["text"],
                               "inserted_pauses_s": [s for _k, s in row["pauses"]], "source": "elevenlabs_tts"}
        save_manifest(manifest)
    print(f"ElevenLabs: {ce.Usage.fetched} request(s), {ce.Usage.characters} characters billed this run, "
          f"{ce.Usage.cached} from cache")
    if failed:
        row, exc = failed
        left = todo[todo.index(row):]
        print(f"STOPPED at {row['id']}: {exc}")
        print(f"{len(left)} line(s) not rendered, {sum(len(r['text']) for r in left)} characters: "
              + " ".join(r["id"] for r in left))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
