#!/usr/bin/env python3
"""Local word-timestamp transcripts for the author's takes.

    python Tools/Audio/transcribe_author.py               # missing takes only
    python Tools/Audio/transcribe_author.py SHOW_A3_03 --force

Requires the locally cached faster-whisper medium.en model in Saved/Whisper.
No audio or transcript is uploaded. Results stay under Saved/Whisper/out and are
read by caption_cues.py; review transcript errors in caption-spoken-overrides.json.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from faster_whisper import WhisperModel

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "Saved" / "Whisper"
TAKES = ROOT / "Saved" / "RadioRecordings" / "author_mp3"
OUT = CACHE / "out"


def initial_prompt() -> str:
    story = ROOT / "docs" / "story"
    data = json.loads((story / "names.json").read_text(encoding="utf-8"))
    names = [name["display_in_english_text"] for name in data["names"]]
    # Some author-confirmed places still live under the historical pending group.
    # Use only their supplied spellings, never untranslated English placeholders.
    names += [place["saskartan_author_spelling"] for place in data["pending"]["places"]
              if place.get("saskartan_author_spelling")]
    with (story / "saskartan-keywords.tsv").open(encoding="utf-8-sig", newline="") as source:
        names += [word for row in csv.DictReader(source, delimiter="\t")
                  if (word := row["saskartan"].strip())]
    # Preserve the existing prompt's supplemental terms not yet represented by
    # filled keyword entries; this utility does not change authored names or captions.
    names += ["abrîdiegm", "yeggar tababghē"]
    spellings = {}
    for name in names:
        spellings.setdefault(name.casefold(), name)
    return "Radio show from Ilaawb, the post in the valley. Names: " + ", ".join(spellings.values()) + "."


def model() -> WhisperModel:
    from faster_whisper import WhisperModel

    try:
        return WhisperModel("medium.en", device="cuda", compute_type="float16",
                            download_root=str(CACHE), local_files_only=True)
    except (RuntimeError, ValueError):
        return WhisperModel("medium.en", device="cpu", compute_type="int8", cpu_threads=6,
                            download_root=str(CACHE), local_files_only=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("ids", nargs="*", help="Take IDs, default: every author MP3")
    ap.add_argument("--force", action="store_true", help="Replace existing local transcript JSON")
    args = ap.parse_args()
    selected = [TAKES / f"{line_id}.mp3" for line_id in args.ids] if args.ids else sorted(TAKES.glob("*.mp3"))
    missing = [path for path in selected if not path.is_file()]
    if missing:
        ap.error("Missing takes: " + ", ".join(p.stem for p in missing))
    pending = [path for path in selected if args.force or not (OUT / f"{path.stem}.json").is_file()]
    if not pending:
        print("All selected takes already have local transcripts.")
        return
    OUT.mkdir(parents=True, exist_ok=True)
    whisper = model()
    prompt = initial_prompt()
    for path in pending:
        segments, info = whisper.transcribe(str(path), word_timestamps=True, initial_prompt=prompt,
                                             beam_size=5, condition_on_previous_text=False, vad_filter=False)
        rows = list(segments)
        result = {
            "id": path.stem,
            "duration": info.duration,
            "text": " ".join(s.text.strip() for s in rows),
            "segments": [
                {
                    "start": s.start, "end": s.end, "text": s.text,
                    "avg_logprob": s.avg_logprob, "no_speech_prob": s.no_speech_prob,
                    "words": [{"start": w.start, "end": w.end, "word": w.word, "p": w.probability}
                              for w in s.words],
                }
                for s in rows
            ],
        }
        (OUT / f"{path.stem}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                                                    encoding="utf-8")
        print(f"{path.stem}: {info.duration:.1f}s", flush=True)


if __name__ == "__main__":
    main()
