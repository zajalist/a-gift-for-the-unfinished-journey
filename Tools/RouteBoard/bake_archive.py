"""Bake actual audio peaks into route-board.json for its cooked data asset.

No audio playback, editor access, or source-audio modification. Missing audio stays
unavailable rather than receiving a decorative waveform. Re-run after take changes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import wave

import numpy as np

ROOT = Path(__file__).resolve().parents[2]


def envelope(path: Path, bins: int = 64, muted_ranges: list | None = None) -> dict:
    if not 1 <= bins <= 128:
        raise ValueError("waveform bins must be between 1 and 128")
    with wave.open(str(path), "rb") as audio:
        rate, channels, width, frames = audio.getframerate(), audio.getnchannels(), audio.getsampwidth(), audio.getnframes()
        raw = audio.readframes(frames)
    if not frames or not rate or not channels:
        raise ValueError(f"empty audio: {path}")
    if width == 1:
        samples = np.frombuffer(raw, np.uint8).astype(np.float32) - 128
    elif width == 2:
        samples = np.frombuffer(raw, "<i2").astype(np.float32)
    elif width == 3:
        parts = np.frombuffer(raw, np.uint8).reshape(-1, 3).astype(np.int32)
        signed = parts[:, 0] | (parts[:, 1] << 8) | (parts[:, 2] << 16)
        samples = ((signed ^ 0x800000) - 0x800000).astype(np.float32)
    elif width == 4:
        samples = np.frombuffer(raw, "<i4").astype(np.float64)
    else:
        raise ValueError(f"unsupported PCM width: {width}")
    # Maximum across channels avoids phase cancellation; preserve relative silence.
    magnitude = np.max(np.abs(samples.reshape(-1, channels)), axis=1)
    for start, end in muted_ranges or []:
        magnitude[max(0, int(start * rate)):min(len(magnitude), int(end * rate))] = 0
    edges = np.linspace(0, len(magnitude), min(bins, len(magnitude)) + 1, dtype=int)
    peaks = [float(magnitude[a:b].max()) for a, b in zip(edges[:-1], edges[1:])]
    scale = max(peaks, default=0.0)
    return {
        "duration_s": round(frames / rate, 4),
        "peaks": [round(p / scale, 4) if scale else 0.0 for p in peaks],
        "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def bake(project: Path) -> tuple[dict, list[str]]:
    station = json.loads((project / "docs/story/station.json").read_text(encoding="utf-8-sig"))
    selected = project / "Saved/RadioRecordings/selected"
    paths = {s["id"]: selected / f'{s["id"]}.wav' for s in station["segments"]}
    paths.update({p.stem: p for p in selected.glob("RADIO_*.wav")})
    for song in station["songs"]["files"]:
        paths[f"SONG_{song}"] = project / "SourceArt/Audio/StationSongs" / f"{song}.wav"
    clips, missing = {}, []
    dropouts = {s["id"]: s["name_dropout"] for s in station["segments"] if "name_dropout" in s}
    for item, path in sorted(paths.items()):
        if not path.is_file():
            missing.append(item)
            continue
        dropout = dropouts.get(item, {})
        if dropout and hashlib.sha256(path.read_bytes()).hexdigest() != dropout["source_sha256"]:
            raise ValueError(f"{item}: source changed; re-align name dropout before baking")
        clips[item] = envelope(path, muted_ranges=dropout.get("ranges_s"))
        if dropout:
            clips[item]["name_not_recorded"] = True
    return clips, missing


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=ROOT)
    parser.add_argument("--check", action="store_true", help="report drift without changing the board data")
    args = parser.parse_args()
    board_path = args.project / "docs/story/route-board.json"
    board = json.loads(board_path.read_text(encoding="utf-8-sig"))
    clips, missing = bake(args.project)
    changed = board.get("archive_clips") != clips
    if changed and not args.check:
        board.pop("archive_clips", None)
        # Keep one bounded envelope per line so future audio updates remain reviewable.
        text = json.dumps(board, ensure_ascii=False, indent=2)[:-2]
        rows = ["    " + json.dumps(item) + ": " + json.dumps(clip, separators=(",", ":")) for item, clip in clips.items()]
        text += ',\n  "archive_clips": {\n' + ",\n".join(rows) + "\n  }\n}\n"
        board_path.write_text(text, encoding="utf-8")
    print(json.dumps({"clips": len(clips), "missing_audio": missing, "changed": changed, "wrote": changed and not args.check}))
    if args.check and changed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
