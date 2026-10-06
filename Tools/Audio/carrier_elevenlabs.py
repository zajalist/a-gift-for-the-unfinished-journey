#!/usr/bin/env python3
"""Carrier voice lines from ElevenLabs, robotised harder than the edge-tts render.

Speaks every carrier line with an ElevenLabs premade voice, then runs it through
make_carrier_voice's heavy chain (channel vocoder on a fixed 100 Hz buzz, ring mod,
crush, 300 Hz-4 kHz speaker, metallic comb, plus the per-style beep / stutter / sag /
dropouts / CV_FAIL_02 cut) and, at the default strength, an extra ffmpeg stage (comb
flange, second ring mod, aliasing crush, 300 Hz-5 kHz band-pass, small metallic room,
pitch down 1.5 st). Every file is loudness-normalised to -16 LUFS, -1 dBTP.

    python Tools/Audio/carrier_elevenlabs.py --dry-run                 # lines + character count, no API call
    python Tools/Audio/carrier_elevenlabs.py --audition                # CV_BOOT_02 with the candidate voices
    python Tools/Audio/carrier_elevenlabs.py                           # every line, default voice + strength
    python Tools/Audio/carrier_elevenlabs.py --strength heavy          # one step lighter
    python Tools/Audio/carrier_elevenlabs.py --ab CV_BOOT_02           # light / heavy / heaviest of one line

Outputs (under Saved/GameAudio/CarrierVoice/, the folder make_carrier_voice.py writes):
    VO_Carrier_<id>.wav          processed, 48 kHz mono 16-bit, the files the editor reimports
    VO_Carrier_CV_BOOT.wav       CV_BOOT_01..04 pre-mixed with 0.4 s gaps
    manifest.json                [{id, file, text, style, duration_s}]
    elevenlabs.json              voice, model, settings, characters per line
    _clean/VO_Carrier_<id>.wav   the unprocessed ElevenLabs take (trimmed, same loudness)
    _ab/                         light / heavy / heaviest of one line
    _audition/                   the voice audition
    _edge_tts_backup/            the previous edge-tts render, moved aside on the first full run
    .elevenlabs_cache/           raw API responses (MP3 + alignment), so reruns cost nothing

The API key is read from ELEVENLABS_API_KEY in the process environment, else from the
Windows user environment (HKCU\\Environment). It is never printed or written anywhere.
Only /v1/text-to-speech is called. Never touches Unreal.
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_carrier_voice as mcv  # noqa: E402

SR = mcv.SR  # 48 kHz
API_SR = 44_100
API_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice}/with-timestamps?output_format=mp3_44100_128"  # pcm_44100 needs the Pro tier
MODEL = "eleven_multilingual_v2"
VOICE_SETTINGS = {"stability": 0.30, "similarity_boost": 0.75, "style": 0.0,
                  "use_speaker_boost": False, "speed": 1.0}
DEFAULT_VOICE = "onwK4e9ZLuTAKqWW03F9"  # Daniel; picked by --audition, see CARRIERVO brief
CANDIDATES = {"onwK4e9ZLuTAKqWW03F9": "Daniel", "JBFqnCBsd6RMkjVDRZzb": "George",
              "pNInz6obpgDQGcFmaJgB": "Adam", "N2lVS1w4EtoT3dr4eOWO": "Callum",
              "TX3LPaxmHKxFdv7IpTwY": "Arnold"}
AUDITION_VOICES = ("onwK4e9ZLuTAKqWW03F9", "pNInz6obpgDQGcFmaJgB")
AUDITION_LINE = "CV_BOOT_02"

LUFS, TRUE_PEAK, LRA = -16.0, -1.0, 7.0
STRENGTHS = ("light", "heavy", "heaviest")
DEFAULT_STRENGTH = "heaviest"
# The extra stage on top of mcv's heavy chain for "heaviest" (ffmpeg filter graph).
HEAVIEST_FX = ",".join([
    "flanger=delay=1.2:depth=1.5:regen=45:width=55:speed=0.35:shape=triangular",  # comb flange
    "aeval='val(0)*(0.72+0.28*sin(2*PI*31*t))'",                                   # second ring mod, 31 Hz
    "acrusher=bits=9:mode=log:samples=3:mix=0.30:aa=0.2",                          # aliasing, 16 kHz hold
    "highpass=f=300:poles=2,highpass=f=300:poles=2",                               # 300 Hz-5 kHz speaker
    "lowpass=f=5000:poles=2,lowpass=f=5000:poles=2",
    "aecho=0.85:0.55:4|9|13:0.30|0.22|0.14",                                       # small metallic room
    "rubberband=pitch=0.917:formant=preserved",                                    # -1.5 st
])

# carrier-voice-lines.json "record" values left out unless --include-optional
OPTIONAL_RECORDS = ("tts_optional",)
TSV = mcv.PROJECT_ROOT / "docs" / "story" / "radio-lines-for-translation.tsv"
OUT = mcv.DEFAULT_OUT
CACHE = OUT / ".elevenlabs_cache"


# --------------------------------------------------------------------------- lines

def load_all_lines(include_optional: bool = False) -> list[mcv.Line]:
    """carrier-voice-lines.json (minus the tts_optional lines unless asked), then any
    Carrier-group CV_ line that is only in the TSV."""
    records = {str(raw.get("id")): str(raw.get("record", "")) for raw in
               json.loads(mcv.DEFAULT_LINES.read_text(encoding="utf-8")).get("lines", [])}
    lines = [line for line in mcv.load_lines(mcv.DEFAULT_LINES)
             if include_optional or records.get(line.id) not in OPTIONAL_RECORDS]
    seen = set(records)
    if TSV.is_file():
        with TSV.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f, delimiter="	"):
                lid = (row.get("ID (slate)") or "").strip()
                if not lid.startswith("CV_") or lid in seen or (row.get("Group") or "").strip() != "Carrier":
                    continue
                text = (row.get("English") or "").strip().strip('"').strip()
                style = (row.get("Delivery") or "").strip()
                if text:
                    lines.append(mcv.Line(lid, text, style if style in mcv.STYLES else "system"))
                    seen.add(lid)
    return lines


# ---------------------------------------------------------------------------- API

def _api_key() -> str:
    key = os.environ.get("ELEVENLABS_API_KEY", "")
    if not key and sys.platform == "win32":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                key = str(winreg.QueryValueEx(k, "ELEVENLABS_API_KEY")[0])
        except OSError:
            key = ""
    if not key:
        raise SystemExit("error: ELEVENLABS_API_KEY is not set (process or user environment)")
    return key.strip()


def _cache_key(voice: str, text: str, model: str = MODEL, settings: dict | None = None) -> str:
    blob = json.dumps({"voice": voice, "model": model, "settings": settings or VOICE_SETTINGS,
                       "format": "mp3_44100_128", "text": text}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]


class Usage:
    characters = 0
    fetched = 0
    cached = 0


class ElevenLabsError(RuntimeError):
    """The API refused a request (quota, permission, bad voice id...). Never holds the key."""

    def __init__(self, status: int, detail: str):
        super().__init__(f"ElevenLabs HTTP {status}: {detail}")
        self.status, self.detail = status, detail


def tts_raw(voice: str, text: str, model: str = MODEL, settings: dict | None = None,
            cache: Path = CACHE) -> tuple[np.ndarray, dict]:
    """(float mono samples at 48 kHz, the API's character alignment) for one text; cached on disk.
    Raises ElevenLabsError when the API refuses."""
    settings = settings or VOICE_SETTINGS
    key = _cache_key(voice, text, model, settings)
    mp3_path, meta_path = cache / f"{key}.mp3", cache / f"{key}.json"
    if mp3_path.is_file() and meta_path.is_file():
        raw, alignment = mp3_path.read_bytes(), json.loads(meta_path.read_text(encoding="utf-8"))["alignment"]
        Usage.cached += 1
    else:
        body = json.dumps({"text": text, "model_id": model, "voice_settings": settings}).encode("utf-8")
        req = urllib.request.Request(API_URL.format(voice=voice), data=body, method="POST",
                                     headers={"xi-api-key": _api_key(), "Content-Type": "application/json",
                                              "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise ElevenLabsError(exc.code, exc.read().decode("utf-8", errors="replace")[:400]) from None
        raw = base64.b64decode(data["audio_base64"])
        alignment = data.get("alignment") or {}
        cache.mkdir(parents=True, exist_ok=True)
        mp3_path.write_bytes(raw)
        meta_path.write_text(json.dumps({"voice": voice, "model": model, "settings": settings,
                                         "text": text, "alignment": alignment}, ensure_ascii=False, indent=1),
                             encoding="utf-8")
        Usage.characters += len(text)
        Usage.fetched += 1
    return ffmpeg_f32(raw, "-f mp3", "aresample=48000:filter_size=64"), alignment


def tts(voice: str, text: str) -> tuple[np.ndarray, list[dict]]:
    """(float mono samples at 48 kHz, [{text, start_s}]) for one carrier line."""
    try:
        audio, alignment = tts_raw(voice, text)
    except ElevenLabsError as exc:
        raise SystemExit(f"error: {exc} (text {text!r})") from None
    return audio, words_from_alignment(alignment)


def words_from_alignment(al: dict) -> list[dict]:
    chars, starts = al.get("characters") or [], al.get("character_start_times_seconds") or []
    words, current, start = [], "", 0.0
    for ch, t in zip(chars, starts):
        if ch.isspace():
            if current:
                words.append({"text": current, "start_s": start})
            current = ""
        else:
            if not current:
                start = float(t)
            current += ch
    if current:
        words.append({"text": current, "start_s": start})
    return words


# ------------------------------------------------------------------------- ffmpeg

def ffmpeg_f32(data: bytes, in_fmt: str, graph: str) -> np.ndarray:
    """Raw audio bytes (``in_fmt`` ffmpeg input options) -> float32 mono 48 kHz through ``graph``."""
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", *in_fmt.split(), "-i", "pipe:0",
           "-af", graph, "-ac", "1", "-ar", str(SR), "-f", "f32le", "pipe:1"]
    proc = subprocess.run(cmd, input=data, capture_output=True)
    if proc.returncode != 0:
        raise SystemExit(f"error: ffmpeg failed: {proc.stderr.decode(errors='replace')[:600]}")
    return np.frombuffer(proc.stdout, dtype="<f4").astype(np.float64)


def _f32(x: np.ndarray) -> bytes:
    return np.asarray(x, dtype="<f4").tobytes()


F32_IN = f"-f f32le -ar {SR} -ac 1"


LIMIT_DBFS = -1.2  # limiter ceiling (sample peak), leaves room for inter-sample overs


def loudnorm(x: np.ndarray, target: float = LUFS) -> np.ndarray:
    """Static gain to LUFS, a look-ahead limiter for the TRUE_PEAK ceiling, then 5 ms edge fades.

    (ffmpeg's loudnorm falls short on these peaky clips: its linear mode gives up when the
    gain would break the peak target.) Two gain passes, since the limiter shaves a little
    loudness off.
    """
    pad = np.zeros(int(0.1 * SR))
    y = np.concatenate((x, pad))
    ceiling = 10.0 ** (LIMIT_DBFS / 20.0)
    for _ in range(3):
        i, _tp = measure_f32(y)
        if abs(i - target) < 0.2:
            break
        y = y * 10.0 ** ((target - i) / 20.0)
        y = ffmpeg_f32(_f32(y), F32_IN, f"alimiter=limit={ceiling:.4f}:attack=1:release=40:level=disabled:asc=1")
    y = y[:len(x)]
    return y * mcv._edge_fades(len(y), mcv.EDGE_FADE_S)


def measure_f32(x: np.ndarray) -> tuple[float, float]:
    return _ebur128(["-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", "pipe:0"], _f32(x))


def measure(path: Path) -> tuple[float, float]:
    """(integrated LUFS, true peak dBTP) of a file."""
    return _ebur128(["-i", str(path)], None)


def _ebur128(inputs: list[str], data: bytes | None) -> tuple[float, float]:
    proc = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", *inputs, "-af",
                           "ebur128=peak=true", "-f", "null", "-"], input=data, capture_output=True)
    text = proc.stderr.decode(errors="replace")
    tail = text[text.rindex("Summary:"):]
    i = float(tail.split("I:")[1].split("LUFS")[0])
    tp = float(tail.split("Peak:")[1].split("dBFS")[0])
    return i, tp


# ------------------------------------------------------------------------- render

def trim_clean(audio: np.ndarray) -> np.ndarray:
    first, end = mcv._active_span(audio, mcv.TTS_TRIM_DB)
    return audio[max(0, first - int(0.020 * SR)):min(len(audio), end + int(0.080 * SR))]


def robotise(line: mcv.Line, audio: np.ndarray, words: list[dict], strength: str) -> np.ndarray:
    """Float samples before loudness normalisation."""
    robot = "light" if strength == "light" else "heavy"
    pcm, notes = mcv.render_line(line, audio, words, robot=robot, src_sr=SR)
    for note in notes:
        print(f"        {note}")
    return pcm.astype(np.float64) / mcv.FULL_SCALE


def post(x: np.ndarray, strength: str) -> np.ndarray:
    if strength == "heaviest":
        x = ffmpeg_f32(_f32(np.pad(x, (0, int(0.05 * SR)))), F32_IN, HEAVIEST_FX)
        first, end = mcv._active_span(x, mcv.FINAL_TRIM_DB)
        x = x[max(0, first - int(0.010 * SR)):end + int(0.030 * SR)]
    return loudnorm(x)


def write(path: Path, x: np.ndarray, root: Path = OUT) -> float:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = np.round(np.clip(x, -1.0, 1.0) * mcv.PCM_SCALE).astype("<i2")
    mcv.write_wav(path, pcm)
    i, tp = measure(path)
    print(f"wrote {path.relative_to(root)}  {len(pcm) / SR:5.2f} s  {i:6.1f} LUFS  {tp:5.1f} dBTP")
    return len(pcm) / SR


def audition(lines: list[mcv.Line]) -> None:
    line = next(line for line in lines if line.id == AUDITION_LINE)
    for voice in AUDITION_VOICES:
        audio, words = tts(voice, line.text)
        name = CANDIDATES.get(voice, voice)
        write(OUT / "_audition" / f"{name}_{line.id}_clean.wav", loudnorm(trim_clean(audio)))
        write(OUT / "_audition" / f"{name}_{line.id}_heaviest.wav", post(robotise(line, audio, words, "heaviest"), "heaviest"))


def ab(lines: list[mcv.Line], voice: str, line_id: str) -> None:
    line = next(line for line in lines if line.id == line_id)
    audio, words = tts(voice, line.text)
    write(OUT / "_ab" / f"{line.id}_0_clean.wav", loudnorm(trim_clean(audio)))
    for n, strength in enumerate(STRENGTHS, 1):
        write(OUT / "_ab" / f"{line.id}_{n}_{strength}.wav", post(robotise(line, audio, words, strength), strength))


def backup_edge_render() -> None:
    backup = OUT / "_edge_tts_backup"
    if backup.exists():
        return
    old = sorted(OUT.glob("VO_Carrier_*.wav"))
    if not old:
        return
    backup.mkdir()
    for path in old + [OUT / mcv.MANIFEST_NAME]:
        if path.is_file():
            shutil.move(str(path), backup / path.name)
    print(f"moved {len(old)} edge-tts file(s) to {backup}")


def generate(lines: list[mcv.Line], voice: str, strength: str) -> None:
    backup_edge_render()
    robot_pre: dict[str, np.ndarray] = {}
    clean_pre: dict[str, np.ndarray] = {}
    manifest, info = [], []
    for line in lines:
        audio, words = tts(voice, line.text)
        clean_pre[line.id] = trim_clean(audio)
        write(OUT / "_clean" / line.filename, loudnorm(clean_pre[line.id]))
        robot_pre[line.id] = robotise(line, audio, words, strength)
        duration = write(OUT / line.filename, post(robot_pre[line.id], strength))
        manifest.append({"id": line.id, "file": line.filename, "text": line.text, "style": line.style,
                         "duration_s": round(duration, 3)})
        info.append({"id": line.id, "characters": len(line.text)})
    for clip, sources, gap in mcv.premix_clips(lines):
        silence = np.zeros(int(round(gap * SR)))
        # each line through its own post chain, joined, then the whole clip levelled once
        processed = [post(robot_pre[s], strength) for s in sources]
        joined = np.concatenate([p for q in processed for p in (q, silence)][:-1])
        duration = write(OUT / clip.filename, loudnorm(joined))
        write(OUT / "_clean" / clip.filename,
              loudnorm(np.concatenate([p for s in sources for p in (clean_pre[s], silence)][:-1])))
        manifest.append({"id": clip.id, "file": clip.filename, "text": clip.text, "style": clip.style,
                         "duration_s": round(duration, 3)})
    mcv.write_json(OUT / mcv.MANIFEST_NAME, manifest)
    mcv.write_json(OUT / "elevenlabs.json", {
        "voice_id": voice, "voice_name": CANDIDATES.get(voice, "?"), "model": MODEL, "settings": VOICE_SETTINGS,
        "output_format": "mp3_44100_128 -> 48 kHz (swr, filter_size 64)", "strength": strength, "loudness": [LUFS, TRUE_PEAK],
        "heaviest_fx": HEAVIEST_FX, "lines": info, "characters_total": sum(i["characters"] for i in info)})


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--voice", default=DEFAULT_VOICE, help="ElevenLabs premade voice id")
    ap.add_argument("--strength", choices=STRENGTHS, default=DEFAULT_STRENGTH)
    ap.add_argument("--audition", action="store_true", help=f"{AUDITION_LINE} with {len(AUDITION_VOICES)} voices")
    ap.add_argument("--ab", metavar="LINE_ID", help="light / heavy / heaviest of one line into _ab/")
    ap.add_argument("--include-optional", action="store_true", help="also the tts_optional lines")
    ap.add_argument("--dry-run", action="store_true", help="list lines and characters; no API call")
    args = ap.parse_args()

    lines = load_all_lines(args.include_optional)
    if args.dry_run:
        for line in lines:
            print(f"{line.id:<18} {line.style:<8} {len(line.text):3d}  {line.text}")
        print(f"{len(lines)} lines, {sum(len(line.text) for line in lines)} characters")
        return 0
    if args.audition:
        audition(lines)
    elif args.ab:
        ab(lines, args.voice, args.ab)
    else:
        generate(lines, args.voice, args.strength)
    print(f"ElevenLabs: {Usage.fetched} request(s), {Usage.characters} characters billed this run, "
          f"{Usage.cached} from cache")
    return 0


if __name__ == "__main__":
    sys.exit(main())
