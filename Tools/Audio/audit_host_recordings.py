"""Audit station takes against the actual SoundWave import provenance, offline.

The station resolves Recorded/ first, then the plain Host folder. The editor's
CheckRecordingsOnDisk currently warns whenever Recorded/ is absent, even if the
plain SoundWave was imported from the author's selected WAV. This audit checks
the selected WAV's MD5 against the SoundWave's embedded AssetImportData MD5.
It never changes or imports Unreal assets.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HOST_REL = Path("Content/SaskartaGaea/Audio/Station/Host")
SELECTED_REL = Path("Saved/RadioRecordings/selected")
RAW_REL = Path("Saved/RadioRecordings/raw")
AUTHOR_REL = Path("Saved/RadioRecordings/author_mp3")
HOST_GAME = "/Game/SaskartaGaea/Audio/Station/Host"
IMPORT_MD5 = re.compile(rb'"FileMD5"\s*:\s*"([0-9a-fA-F]{32})"')


def file_md5(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def asset_import_md5(path: Path) -> str | None:
    if not path.is_file():
        return None
    match = IMPORT_MD5.search(path.read_bytes())
    return match.group(1).decode("ascii").lower() if match else None


def audit(root: Path) -> dict:
    segments = json.loads((root / "docs/story/station.json").read_text(encoding="utf-8"))["segments"]
    selected = root / SELECTED_REL
    raw = root / RAW_REL
    author = root / AUTHOR_REL
    host = root / HOST_REL
    tts_ids = {item["id"] for item in json.loads((selected / "_tts_manifest.json").read_text(encoding="utf-8"))}
    rows = []
    remap = []

    for segment in segments:
        line_id = segment["id"]
        wav = selected / f"{line_id}.wav"
        has_selected = wav.is_file()
        has_raw = any(raw.glob(f"{line_id}_take*.wav"))
        # Same priority as FSaskartaStationLogic::ClassifyTake.
        source = "author" if has_raw else "missing" if not has_selected else "tts" if line_id in tts_ids else "author"
        name = f"VO_Station_{line_id}"
        plain = host / f"{name}.uasset"
        recorded = host / "Recorded" / f"{name}.uasset"
        wav_md5 = file_md5(wav) if has_selected else None
        plain_md5 = asset_import_md5(plain)
        recorded_md5 = asset_import_md5(recorded)
        row = {
            "id": line_id,
            "category": segment.get("category"),
            "source": source,
            "author_mp3": (author / f"{line_id}.mp3").is_file(),
            "selected_wav": str(wav.relative_to(root)).replace("\\", "/") if has_selected else None,
            "selected_md5": wav_md5,
            "plain_asset": f"{HOST_GAME}/{name}",
            "plain_import_md5": plain_md5,
            "plain_matches_selected": bool(wav_md5 and plain_md5 == wav_md5),
            "recorded_asset": f"{HOST_GAME}/Recorded/{name}",
            "recorded_import_md5": recorded_md5,
            "recorded_matches_selected": bool(wav_md5 and recorded_md5 == wav_md5),
        }
        rows.append(row)
        if source == "author" and has_selected and not row["recorded_matches_selected"]:
            remap.append({
                "id": line_id,
                "source_wav": row["selected_wav"],
                "destination_folder": f"{HOST_GAME}/Recorded",
                "asset_name": name,
                "source_md5": wav_md5,
                "existing_plain_matches_source": row["plain_matches_selected"],
            })

    authors = [row for row in rows if row["source"] == "author"]
    return {
        "summary": {
            "station_segments": len(rows),
            "source_counts": dict(sorted(Counter(row["source"] for row in rows).items())),
            "author_plain_current": sum(row["plain_matches_selected"] for row in authors),
            "author_recorded_current": sum(row["recorded_matches_selected"] for row in authors),
            "author_missing_both": sum(not row["plain_matches_selected"] and not row["recorded_matches_selected"] for row in authors),
            "recorded_import_jobs": len(remap),
        },
        "segments": rows,
        "recorded_import_manifest": remap,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=ROOT / "Saved/Verification/radio_recordings/audit.json")
    args = parser.parse_args()
    report = audit(args.root.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], sort_keys=True))
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
