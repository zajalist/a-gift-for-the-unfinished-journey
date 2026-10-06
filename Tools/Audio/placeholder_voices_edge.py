#!/usr/bin/env python3
"""Placeholder takes for every story / idle / station radio line that has no current take, from edge-tts.

The author will record the Keeper later; until then each missing or stale line gets a free
Microsoft neural voice (edge-tts), written where the user's selected takes go,
Saved/RadioRecordings/selected/<ID>.wav, and listed in _tts_manifest.json there with
``placeholder: true`` so the station's "your recording wins" logic lets real takes override it.

    python Tools/Audio/placeholder_voices_edge.py --dry-run     # what is missing / stale
    python Tools/Audio/placeholder_voices_edge.py --test        # one line per speaker, to scratch
    python Tools/Audio/placeholder_voices_edge.py               # render every missing / stale line
    python Tools/Audio/placeholder_voices_edge.py --only RADIO_B11_01 RADIO_B11_03

A line is rendered when <ID>.wav is missing, when its manifest entry is flagged
``text_changed``, when its manifest ``cast_now`` differs from the TSV speaker (the old Neighbour
takes of the two Elder lines), or when a previous edge-tts render has a different text hash.
Lines the TSV lists as CARRIER, and breaths, are never touched; a <ID>.wav with no manifest
entry is the user's own take and is never overwritten.

Stage directions are not spoken: each quoted segment is synthesised on its own and real silence
goes between them ((beat) 0.6 s, (pause) 1.2 s, (N s pause) N s, (breath) 0.5 s). Saskartan
lines (Language SKS) read the Saskartan text with the Keeper voice; the neural voice
mispronounces it, which is accepted for a placeholder. Output: 48 kHz mono 16-bit WAV,
-18 LUFS, true peak under -1 dBTP, no tape filter (the game applies it). A replaced stale
file is kept under selected/_stale/.

Live-show lines (TSV Group "Show", docs/story/RADIO_SHOW.md) use a per-act rate and pitch
(SHOW_PROSODY: slower and lower from Act I to Act V) so the placeholders hint at the night's arc.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import re
import shutil
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import carrier_edge_tts as cet  # noqa: E402
import carrier_elevenlabs as ce  # noqa: E402
import make_carrier_voice as mcv  # noqa: E402

SR = ce.SR  # 48 kHz
PROJECT = mcv.PROJECT_ROOT
TSV = PROJECT / "docs" / "story" / "radio-lines-for-translation.tsv"
OUT = PROJECT / "Saved" / "RadioRecordings" / "selected"
STALE = OUT / "_stale"
CACHE = PROJECT / "Saved" / "RadioRecordings" / ".edge_cache"  # outside selected/: the importer scans it
MANIFEST = OUT / "_tts_manifest.json"
LUFS = -18.0
LIMIT_DBFS = -1.5  # sample-peak ceiling, keeps true peak under -1 dBTP

# rate / pitch are edge-tts prosody strings
SPEAKERS = {
    # closest to the ElevenLabs "George" stand-ins (mature British male, median F0 ~129 Hz):
    # Thomas measures ~121 Hz at a similar pace; Ryan sat at ~149 Hz and read slower
    "KEEPER": {"voice": "en-GB-ThomasNeural", "rate": "-3%", "pitch": "+0Hz"},
    # older and slower than the Keeper, a different speaker and accent (Irish), pitched down
    "ELDER": {"voice": "en-IE-ConnorNeural", "rate": "-15%", "pitch": "-18Hz"},
    # British female like the ElevenLabs "Lily" Visitor takes
    "VISITOR": {"voice": "en-GB-SoniaNeural", "rate": "-5%", "pitch": "+0Hz"},
    # 2026-09-29 rewritten show and First Light ending: one distinct English voice per speaker
    "WORKS": {"voice": "en-US-AndrewNeural", "rate": "+6%", "pitch": "+4Hz"},       # works announcer, bright
    "SAMYOR": {"voice": "en-GB-RyanNeural", "rate": "-14%", "pitch": "-14Hz"},      # old man
    "EHB": {"voice": "en-IE-EmilyNeural", "rate": "-6%", "pitch": "+0Hz"},
    "TMAZ": {"voice": "en-AU-WilliamNeural", "rate": "-12%", "pitch": "-10Hz"},     # old man, the cistern steps
    "RSÎSH": {"voice": "en-NZ-MitchellNeural", "rate": "-4%", "pitch": "+0Hz"},
    "ILSÎS": {"voice": "en-ZA-LeahNeural", "rate": "-5%", "pitch": "+0Hz"},
    "NRINUB": {"voice": "en-ZA-LukeNeural", "rate": "-3%", "pitch": "+2Hz"},
    "EB": {"voice": "en-AU-NatashaNeural", "rate": "-16%", "pitch": "-10Hz"},       # ninety-one
    "UNATTRIBUTED": {"voice": "en-CA-LiamNeural", "rate": "-2%", "pitch": "+0Hz"},
    "WALLA": {"voice": "en-CA-ClaraNeural", "rate": "+4%", "pitch": "+0Hz"},
}
TEST_LINES = {"KEEPER": "IDLE_LATE_03", "ELDER": "RADIO_B11_01", "VISITOR": "STN_LETTER_03"}
PAUSE_S = {"beat": 0.6, "pause": 1.2, "breath": 0.5}
RESPELL = {"ehbîket": "eh-bee-ket", "kushiân": "koo-shee-an", "diyal": "dee-yal",
           "zmerban": "zmehr-ban", "Samyâr": "Sam-yar", "îtset": "eet-set"}
HEAD_S, TAIL_S = 0.05, 0.25

# The live show (docs/story/RADIO_SHOW.md): the Keeper slows and drops through the night, so the
# placeholder hints at the arc. Act from the id (SHOW_A3_02, FILL_A4_01, SONGIN_A1_02...) or, for a
# reaction, the first act in the Beat column ("Acts III–IV"); room murmurs are late-night quiet.
SHOW_PROSODY = {1: ("-3%", "+0Hz"), 2: ("-6%", "-2Hz"), 3: ("-12%", "-5Hz"), 4: ("-15%", "-7Hz"), 5: ("-20%", "-9Hz")}
SHOW_ROOM_PROSODY = ("-12%", "-5Hz")
ROMAN_ACT = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5}


def show_act(row: dict) -> int | None:
    """The live-show act of a Show row (0 = a room murmur), or None for any other line."""
    if row.get("group") != "Show":
        return None
    m = re.search(r"_A(\d)_\d\d$", row["id"])
    if m:
        return int(m.group(1))
    m = re.search(r"\bActs? (V|IV|III|II|I)\b", row.get("beat") or "")
    return ROMAN_ACT[m.group(1)] if m else 0


# The works' three advertisements, each in its own voice (the author, 2026-09-29: "the voice for the different
# advertising must be different"); ElevenLabs was out of credit, so edge-tts voices nobody else in the game uses.
LINE_VOICES = {
    "SHOW_A2_07": {"voice": "en-US-JennyNeural", "rate": "+8%", "pitch": "+6Hz"},    # bright, smiling
    "SHOW_A2_08": {"voice": "en-AU-WilliamNeural", "rate": "+2%", "pitch": "-2Hz"},  # smooth salesman
    "SHOW_A2_09": {"voice": "en-US-RogerNeural", "rate": "-6%", "pitch": "-4Hz"},     # older, soothing
}


def speaker_for(row: dict) -> dict:
    """SPEAKERS[speaker], with the per-act rate and pitch for live-show lines."""
    if row["id"] in LINE_VOICES:
        return dict(LINE_VOICES[row["id"]])
    spk = dict(SPEAKERS[row["speaker"]])
    act = show_act(row)
    if act is not None and row["speaker"] == "KEEPER":  # the announcer keeps his own bright read
        spk["rate"], spk["pitch"] = SHOW_PROSODY.get(act, SHOW_ROOM_PROSODY)
    return spk


# --------------------------------------------------------------------------- lines

def base_speaker(raw: str) -> str:
    """'KEEPER (archive, **late at night**)' -> 'KEEPER'."""
    return raw.split("(")[0].strip().upper()


def segments(text: str) -> list[tuple[str, float]]:
    """'"A." (beat) "B."' -> [('A.', 0.0), ('B.', 0.6)]: each spoken segment with the silence before it."""
    out, pending = [], 0.0
    for piece in re.split(r"(\([^)]*\))", text):
        m = re.fullmatch(r"\(([^)]*)\)", piece.strip())
        if m:
            d = m.group(1).strip().lower()
            n = re.fullmatch(r"(\d+(?:\.\d+)?)\s*s\s*pause", d)
            pending += float(n.group(1)) if n else PAUSE_S.get(d, 0.0)
            continue
        seg = piece.replace('"', " ").strip()
        seg = re.sub(r"\s+", " ", seg)
        if not re.search(r"\w", seg):
            continue
        for word, spoken in RESPELL.items():
            seg = seg.replace(word, spoken)
        out.append((seg, pending))
        pending = 0.0
    return out


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def load_lines() -> list[dict]:
    rows = []
    with TSV.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            line_id = (r.get("ID (slate)") or "").strip()
            speaker = base_speaker(r.get("Speaker") or "")
            if speaker not in SPEAKERS or line_id.startswith("BREATH_"):
                continue
            sks = (r.get("Language") or "").startswith("SKS") and (r.get("Saskartan translation") or "").strip()
            source = r["Saskartan translation"].strip() if sks else (r.get("English") or "").strip()
            rows.append({"id": line_id, "speaker": speaker, "language": "SKS" if sks else "EN",
                         "group": (r.get("Group") or "").strip(), "beat": (r.get("Beat / pool / when") or "").strip(),
                         "text": source, "english": (r.get("English") or "").strip(),
                         "segments": segments(source)})
    return rows


# ------------------------------------------------------------------------- manifest

def load_manifest() -> list[dict]:
    return json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.is_file() else []


def save_manifest(entries: list[dict]) -> None:
    mcv.write_json(MANIFEST, sorted(entries, key=lambda e: e["id"]))


def pending_ids(manifest: list[dict]) -> set[str]:
    """Ids the _README entry lists under pending_generation (e.g. the Elder lines)."""
    readme = next((e for e in manifest if e.get("id") == "_README"), {})
    return {i for ids in (readme.get("pending_generation") or {}).values() for i in ids}


def reason_to_render(row: dict, entry: dict | None, pending: set[str] = frozenset()) -> str | None:
    wav = OUT / f"{row['id']}.wav"
    if (OUT.parent / "author_mp3" / f"{row['id']}.mp3").is_file():
        return None  # the author recorded it (the take in selected/ is theirs): never touch
    if not wav.is_file():
        return "missing"
    if entry is None:
        return None  # the user's own take: never touch
    if entry.get("text_changed"):
        return "stale text"
    if entry.get("engine") == "edge-tts":
        return "stale text" if entry.get("text_hash") != text_hash(row["text"]) else None
    if row["id"] in pending or entry.get("speaker") not in (row["speaker"], "NEIGHBOUR"):
        return f"recast {entry.get('speaker')}->{row['speaker']}"
    if entry.get("speaker") == "NEIGHBOUR" and row["speaker"] != "KEEPER":
        return f"recast NEIGHBOUR->{row['speaker']}"
    return None


# ------------------------------------------------------------------------- render

async def _fetch(text: str, voice: str, rate: str, pitch: str) -> bytes:
    import edge_tts
    comm = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, receive_timeout=cet.FETCH_TIMEOUT_S)
    audio = bytearray()
    async for chunk in comm.stream():
        if chunk["type"] == "audio":
            audio += chunk["data"]
    return bytes(audio)


def speak(text: str, spk: dict) -> np.ndarray:
    """One segment -> float samples at 48 kHz, cached by (voice, rate, pitch, text)."""
    key = cet.cache_key(spk["voice"], f"{spk['rate']}|{spk['pitch']}", text)
    mp3 = CACHE / f"{key}.mp3"
    if not mp3.is_file():
        data = asyncio.run(_fetch(text, spk["voice"], spk["rate"], spk["pitch"]))
        if not data:
            raise RuntimeError(f"edge-tts returned no audio for {text!r}")
        CACHE.mkdir(parents=True, exist_ok=True)
        mp3.write_bytes(data)
        (CACHE / f"{key}.json").write_text(json.dumps({**spk, "text": text}, ensure_ascii=False), encoding="utf-8")
    x = ce.ffmpeg_f32(mp3.read_bytes(), "-f mp3", "anull")  # decode + resample to 48 kHz mono
    first, end = mcv._active_span(x, -50.0)
    return x[first:end]


def render(row: dict, spk: dict) -> np.ndarray:
    parts = [np.zeros(int(HEAD_S * SR))]
    for i, (seg, gap) in enumerate(row["segments"]):
        if i and gap == 0.0:
            gap = 0.25  # plain join between quoted sentences
        if i:
            parts.append(np.zeros(int(gap * SR)))
        parts.append(speak(seg, spk))
    parts.append(np.zeros(int(TAIL_S * SR)))
    return ce.loudnorm(np.concatenate(parts), LUFS)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--test", action="store_true", help="one line per speaker, written to --test-dir")
    ap.add_argument("--test-dir", type=Path, default=PROJECT / "Saved" / "RadioRecordings" / "_edge_test")
    ap.add_argument("--only", nargs="+", metavar="ID")
    args = ap.parse_args()

    ce.LIMIT_DBFS = LIMIT_DBFS
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    lines = load_lines()
    manifest = load_manifest()
    by_id = {e["id"]: e for e in manifest}

    if args.test:
        for speaker, line_id in TEST_LINES.items():
            row = next(r for r in lines if r["id"] == line_id)
            ce.write(args.test_dir / f"{line_id}_{SPEAKERS[speaker]['voice']}.wav",
                     render(row, SPEAKERS[speaker]), root=args.test_dir)
        return 0

    pending = pending_ids(manifest)
    todo = []
    for row in lines:
        if args.only and row["id"] not in args.only:
            continue
        why = reason_to_render(row, by_id.get(row["id"]), pending)
        if why:
            todo.append((row, why))
    print(f"{len(todo)} line(s) to render")
    for row, why in todo:
        gaps = "".join(f" [+{g:g}s]" for _s, g in row["segments"] if g)
        print(f"  {row['id']:<16} {row['speaker']:<8} {row['language']} {why:<22}{gaps}  {row['text'][:60]}")
    if args.dry_run:
        return 0

    for row, why in todo:
        spk = speaker_for(row)
        x = render(row, spk)
        wav = OUT / f"{row['id']}.wav"
        if wav.is_file():
            STALE.mkdir(parents=True, exist_ok=True)
            shutil.copy2(wav, STALE / wav.name)
        ce.write(wav, x, root=OUT)
        old = by_id.get(row["id"])
        entry = {"id": row["id"], "speaker": row["speaker"], "engine": "edge-tts", "voice": spk["voice"],
                 "rate": spk["rate"], "pitch": spk["pitch"], "language": row["language"],
                 "spoken_text": " ".join(s for s, _g in row["segments"]),
                 "text_hash": text_hash(row["text"]),
                 "inserted_pauses_s": [g for _s, g in row["segments"] if g],
                 "source": "edge_tts", "cast_now": row["speaker"], "placeholder": True,
                 "note": "edge-tts placeholder (" + time.strftime("%Y-%m-%d") + "); the author's recording replaces it."}
        if show_act(row) is not None and row["speaker"] == "KEEPER":
            entry["show_act"] = show_act(row)
            entry["note"] += " Live show: per-act prosody (slower and lower through the night) hints at the arc."
        if row["language"] == "SKS":
            entry["note"] += (" Saskartan text read by an English neural voice: mispronounced, placeholder only."
                              " English subtitle: " + row["english"])
        if old is not None:
            entry["replaced"] = f"{old.get('source', '?')} {old.get('voice_name', old.get('voice', ''))}".strip() \
                + f" take ({why}); copy in selected/_stale/"
            manifest[manifest.index(old)] = entry
        else:
            manifest.append(entry)
        by_id[row["id"]] = entry
        save_manifest(manifest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
