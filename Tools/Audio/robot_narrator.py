#!/usr/bin/env python3
"""The tape's last line in a narrator's voice with a light robotic edge (the author, 2026-09-29: "said by a robotic
voice, narrator-like"; then "less intense, it feels fake" and "take it from ElevenLabs").

    python Tools/Audio/robot_narrator.py            # SHOW_A5_TAIL_01/02 -> Saved/RadioRecordings/selected/<id>.wav
    python Tools/Audio/robot_narrator.py --clean    # the same, without the robotic layer
    python Tools/Audio/robot_narrator.py --preview  # also both previews (robotic and clean), with the pause, in fx_preview/

ElevenLabs voice "Brian" (a deep narration voice, distinct from the carrier's "Daniel"), through the project's key
handling (Tools/Audio/carrier_elevenlabs.py: ELEVENLABS_API_KEY or Saved/, never printed; cached, so re-runs are free).
The robotic layer is light: a faint phase-flattened copy under the dry voice and a small metallic comb, then
loudness-matched to the other voices (-18 LUFS, -1.5 dBTP). These takes are final, not placeholders: the ids are removed
from _tts_manifest.json, so the placeholder tools never render over them. Import like any line
(/Game/SaskartaGaea/Audio/Lines/<ID>).
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent))
import carrier_elevenlabs as ce  # noqa: E402

PROJECT = Path(__file__).resolve().parents[2]
SELECTED = PROJECT / "Saved" / "RadioRecordings" / "selected"
PREVIEW = PROJECT / "Saved" / "RadioRecordings" / "fx_preview"
CACHE = PROJECT / "Saved" / "RadioRecordings" / ".elevenlabs_cache"
FFMPEG = "ffmpeg"

NARRATOR = {"voice_id": "nPczCjzI2devNBz1zQrb", "voice_name": "Brian",
            "settings": {"stability": 0.62, "similarity_boost": 0.75, "style": 0.0,
                         "use_speaker_boost": True, "speed": 0.9}}
LINES = [
    ("SHOW_A5_TAIL_01", "Every house. They've all left one on."),
    ("SHOW_A5_TAIL_02", "The world swallowed its pride, and became pious in its sleep."),
]
PAUSE_S = 6.5  # the preview's long pause; in the game CIN_24's cue sheet times the two clips

ROBOT = (
    "[0:a]aformat=sample_rates=48000:channel_layouts=mono,apad=pad_dur=0.6,asplit=2[a][b];"
    "[a]afftfilt=real='hypot(re,im)*cos(0)':imag='hypot(re,im)*sin(0)':win_size=512:overlap=0.75,volume=0.3[r];"
    "[b]volume=0.85[d];"
    "[r][d]amix=inputs=2:normalize=0,aecho=0.8:0.3:5|9:0.15|0.1,highpass=f=100,lowpass=f=8000,"
    "loudnorm=I=-18:TP=-1.5:LRA=11"
)
CLEAN = "[0:a]aformat=sample_rates=48000:channel_layouts=mono,apad=pad_dur=0.6,loudnorm=I=-18:TP=-1.5:LRA=11"


def render(line_id: str, text: str, chain: str, out: Path, tmp: Path) -> Path:
    x, _alignment = ce.tts_raw(NARRATOR["voice_id"], text, ce.MODEL, NARRATOR["settings"], CACHE)
    raw = tmp / f"{line_id}_raw.wav"
    sf.write(str(raw), np.asarray(x, dtype=np.float32), 48000, subtype="FLOAT")
    subprocess.run([FFMPEG, "-loglevel", "error", "-y", "-i", str(raw), "-filter_complex", chain,
                    "-ac", "1", "-ar", "48000", "-c:a", "pcm_s24le", str(out)], check=True)
    return out


def drop_from_manifest(ids: list[str]) -> int:
    p = SELECTED / "_tts_manifest.json"
    if not p.is_file():
        return 0
    m = json.loads(p.read_text(encoding="utf-8"))
    keep = [e for e in m if e.get("id") not in ids]
    p.write_text(json.dumps(keep, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return len(m) - len(keep)


def join(a: Path, b: Path, out: Path) -> None:
    subprocess.run([FFMPEG, "-loglevel", "error", "-y", "-i", str(a), "-i", str(b), "-filter_complex",
                    f"[0:a]apad=pad_dur={PAUSE_S}[p];[p][1:a]concat=n=2:v=0:a=1",
                    "-c:a", "aac", "-b:a", "192k", str(out)], check=True)


def main() -> int:
    game_chain = CLEAN if "--clean" in sys.argv else ROBOT
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        outs = [render(i, text, game_chain, SELECTED / f"{i}.wav", tmp) for i, text in LINES]
        for o in outs:
            print("wrote", o.relative_to(PROJECT))
        print("manifest entries removed:", drop_from_manifest([i for i, _ in LINES]))
        if "--preview" in sys.argv:
            PREVIEW.mkdir(parents=True, exist_ok=True)
            for name, chain in (("NARRATOR_TAIL_robotic.m4a", ROBOT), ("NARRATOR_TAIL_clean.m4a", CLEAN)):
                parts = [render(i, text, chain, tmp / f"{i}_{name}.wav", tmp) for i, text in LINES]
                join(parts[0], parts[1], PREVIEW / name)
                print("preview", (PREVIEW / name).relative_to(PROJECT))
    print(ce.Usage.summary() if hasattr(ce.Usage, "summary") else "")
    return 0


if __name__ == "__main__":
    sys.exit(main())
