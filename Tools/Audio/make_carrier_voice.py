#!/usr/bin/env python3
"""Render the carrier's robotic voice lines for the Saskarta game flow.

Reads docs/story/carrier-voice-lines.json and writes one 48 kHz mono 16-bit PCM WAV per
line to <project>/Saved/GameAudio/CarrierVoice/VO_Carrier_<id>.wav, the CV_BOOT pre-mix
(VO_Carrier_CV_BOOT.wav) and manifest.json ([{id, file, text, style, duration_s}]).
These are placeholders until the lines are recorded; see Tools/Audio/CARRIER_VOICE.md.

    python Tools/Audio/make_carrier_voice.py                # edge-tts + heavy chain, every line, then check
    python Tools/Audio/make_carrier_voice.py --check        # re-read existing files, check only
    python Tools/Audio/make_carrier_voice.py --samples      # candidate voices -> <out>/samples/
    python Tools/Audio/make_carrier_voice.py --list-voices  # voices for --engine (edge or sapi)
    python Tools/Audio/make_carrier_voice.py --engine sapi --robot light   # the original render
    python Tools/Audio/make_carrier_voice.py --voice en-GB-RyanNeural --rate=-5%

Speech comes from edge-tts (Microsoft's online neural voices, cached per voice, rate and
text under <out>/.tts_cache/ so reruns are offline) or from the Windows built-in
System.Speech synthesizer (--engine sapi, and the fall back when edge-tts fails).
Everything after that is numpy only. The processing is seeded per line id, so for given
cached speech every run writes the same files. The check exits with status 1 on any
failure. This script never touches Unreal.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import wave
import zlib
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np

import carrier_edge_tts as cet

SR = 48_000
# System.Speech reports SpeakProgress.AudioPosition as if the output were 16 kHz 16-bit
# mono (bytes / 32000), whatever format is requested: at 22.05 kHz the word times come
# out 1.38x late, at 48 kHz 3x late. So speech is rendered at 16 kHz, where the word
# times are exact, and upsampled here.
TTS_SR = 16_000
UPSAMPLE = SR // TTS_SR
PEAK_DBFS = -3.0
EDGE_FADE_S = 0.005
PCM_SCALE = 32767.0  # float -> int16 when writing
FULL_SCALE = 32768.0  # 0 dBFS reference when measuring

PREFERRED_VOICES = ("Microsoft David Desktop", "Microsoft Zira Desktop")
DEFAULT_RATE = -2  # System.Speech rate runs -10..10; -2 is about 0.8x the default speed
STYLES = ("system", "warning", "failing")

# Robotise chain (every style)
FLATTEN = 0.5  # pull each voiced frame's pitch half-way to the line's median pitch
MAX_SHIFT_OCT = 0.35
SHIFTER_WINDOW_S = 0.030
RING_HZ = 48.0
RING_MIX = 0.22
CRUSH_HOLD = 6  # sample-and-hold every 6 samples: 8 kHz effective rate
CRUSH_BITS = 8
CRUSH_MIX = 0.20
BAND_HZ = (300.0, 4000.0)
BAND_EDGE_OCT = 0.3
COMB_DELAYS_S = (0.0021, 0.0034)  # two short feedback combs -> tin-can resonance
COMB_FEEDBACK = 0.5
COMB_MIX = 0.35

ENGINES = ("edge", "sapi")
ROBOTS = ("heavy", "light")
EDGE_DEFAULT_VOICE = "en-US-GuyNeural"  # picked from the samples; see docs/story/CARRIER_VOICE_SAMPLES.md
EDGE_DEFAULT_RATE = "-10%"  # slightly slow
EDGE_RATE_RE = re.compile(r"[+-]\d{1,3}%")
CACHE_DIR_NAME = ".tts_cache"
SAMPLES_DIR_NAME = "samples"
# --samples: each candidate voice speaks the CV_BOOT pre-mix, one warning and one failing line.
SAMPLE_VOICES = (("A", "en-US-GuyNeural"), ("B", "en-GB-RyanNeural"), ("C", "en-US-AndrewNeural"))
SAMPLE_LINES = ("CV_WARN_01", "CV_FAIL_01")

# Heavy chain (--robot heavy, the default). A channel vocoder re-voices the speech on a
# fixed-pitch buzz, a little of the pitch-flattened original goes back under it for the
# consonants, then the light chain's ring modulator, crush, speaker and comb, set harder.
VOCODER_BANDS = 20
VOCODER_RANGE_HZ = (180.0, 6500.0)  # mel-spaced band edges
VOCODER_EDGE_OCT = 0.12  # raised-cosine crossover width; the band masks sum to 1
VOCODER_ENV_S = 0.008  # box smoother, applied twice: a 16 ms triangle, about 50 Hz
CARRIER_ENV_S = 0.020  # the carrier bands are levelled over a slower window
CARRIER_HZ = 100.0  # the buzz: a band-limited sawtooth
CARRIER_TOP_HZ = 7000.0  # highest buzz harmonic
NOISE_FLOOR_HZ = 2800.0  # bands centred above this always carry some noise (sibilants)
NOISE_FLOOR = 0.35
VOICING_SMOOTH_S = 0.030
HEAVY_BLEND = 0.25  # share of the flattened original under the vocoder
HEAVY_FLATTEN = 0.9  # the original is pulled 90 % of the way onto the carrier's pitch
HEAVY_MAX_SHIFT_OCT = 0.8
HEAVY_SAG_OCT = -5.0 / 12.0  # "failing": the carrier sags 5 semitones by the last sample
# Per style: carrier offset in semitones, tanh drive (1 = none), ring-mod mix, crush
# (hold, bits, wet), comb (delays, feedback, wet).
HEAVY_STYLES = {
    "system": {"carrier_st": 0.0, "drive": 1.0, "ring_mix": 0.28,
               "crush": (6, 7, 0.25), "comb": ((0.0013, 0.0021, 0.0034), 0.6, 0.40)},
    "warning": {"carrier_st": 2.0, "drive": 3.0, "ring_mix": 0.36,
                "crush": (6, 6, 0.32), "comb": ((0.0011, 0.0019, 0.0034), 0.65, 0.45)},
    "failing": {"carrier_st": 0.0, "drive": 1.6, "ring_mix": 0.32,
                "crush": (7, 6, 0.30), "comb": ((0.0013, 0.0021, 0.0034), 0.6, 0.40)},
}

# "warning": two-tone prefix beep
BEEP_TONES = ((1320.0, 0.090), (990.0, 0.090))  # (Hz, seconds), falling fourth
BEEP_GAP_S = 0.030
BEEP_TO_VOICE_S = 0.150
BEEP_LEVEL = 0.45  # relative to the voice peak

# "failing": pitch sag, one stutter, dropouts
SAG_START = 0.5  # fraction of the line where the sag begins
SAG_OCT = -0.29  # about -3.5 semitones by the last sample
STUTTER_REPEATS = 2  # extra copies of the syllable: "ca-ca-carrier"
STUTTER_LEN_S = (0.060, 0.110)
DROPOUT_LEN_S = (0.035, 0.085)
DROPOUT_EVERY_S = 0.9
DROPOUT_COUNT = (2, 4)
DROPOUT_SPACING_S = 0.18

# Per-line extras asked for by the "when" notes in the lines JSON.
CUT_LAST_WORD = {"CV_FAIL_02": 0.55}  # "Cuts to static mid-word": stop 55 % into the last word
# Clips pre-mixed from rendered lines, per the lines JSON's "voice_wiring": CV_BOOT_01..04
# play as one clip, CV_BOOT, with 0.4 s gaps. {clip id: (line ids, gap seconds)}
PREMIXES = {"CV_BOOT": (("CV_BOOT_01", "CV_BOOT_02", "CV_BOOT_03", "CV_BOOT_04"), 0.4)}

# Silence trimming. System.Speech pauses ~1.1 s at a full stop and ~0.5 s at a colon or
# comma at rate -2; every pause inside a line is cut down to MAX_PAUSE_S for an even pace.
MAX_PAUSE_S = 0.35
PAUSE_DB = -40.0
TTS_TRIM_DB = -50.0
FINAL_TRIM_DB = -45.0
TRIM_HEAD_S = 0.010
TRIM_TAIL_S = 0.030

# --check limits
DURATION_RANGE_S = (0.3, 15.0)
PEAK_RANGE_DBFS = (-3.5, -2.5)
MIN_RMS_DBFS = -40.0
MIN_ACTIVE = 0.25  # share of 20 ms windows within 30 dB of the loudest
MAX_DC_PERCENT = 1.0
MAX_EDGE_LSB = 16
MIN_IN_BAND = 0.95  # share of energy between 200 Hz and 5 kHz
MIN_BEEP_PURITY = 0.5  # share of a beep window's energy within 60 Hz of the tone
MANIFEST_KEYS = ("id", "file", "text", "style", "duration_s")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LINES = PROJECT_ROOT / "docs" / "story" / "carrier-voice-lines.json"
DEFAULT_OUT = PROJECT_ROOT / "Saved" / "GameAudio" / "CarrierVoice"
MANIFEST_NAME = "manifest.json"


# ----------------------------------------------------------------------------- lines

@dataclass(frozen=True)
class Line:
    id: str
    text: str
    style: str

    @property
    def filename(self) -> str:
        return f"VO_Carrier_{self.id}.wav"

    @property
    def seed(self) -> int:
        return zlib.crc32(self.id.encode("utf-8"))


def load_lines(path: Path) -> list[Line]:
    if not path.is_file():
        raise SystemExit(f"error: lines file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    lines, seen = [], set()
    for i, raw in enumerate(data.get("lines", [])):
        line = Line(str(raw.get("id", "")), str(raw.get("text", "")).strip(), str(raw.get("style", "")))
        where = f"{path.name} lines[{i}]"
        if not re.fullmatch(r"[A-Za-z0-9_]+", line.id):
            raise SystemExit(f"error: {where}: id {line.id!r} is not a safe file-name part")
        if line.id in seen:
            raise SystemExit(f"error: {where}: duplicate id {line.id}")
        if not line.text:
            raise SystemExit(f"error: {where}: empty text")
        if line.style not in STYLES:
            raise SystemExit(f"error: {where}: style {line.style!r} not one of {STYLES}")
        seen.add(line.id)
        lines.append(line)
    if not lines:
        raise SystemExit(f"error: {path} has no lines")
    return lines


def premix_clips(lines: list[Line]) -> list[tuple[Line, tuple[str, ...], float]]:
    """The PREMIXES whose source lines all exist, as (clip, source ids, gap seconds)."""
    by_id = {line.id: line for line in lines}
    clips = []
    for clip_id, (sources, gap) in PREMIXES.items():
        if all(s in by_id for s in sources):
            text = " ".join(by_id[s].text for s in sources)
            clips.append((Line(clip_id, text, "system"), sources, gap))
    return clips


# ------------------------------------------------------------------ text-to-speech

PS_TTS = r"""
param([string]$ResultFile, [string]$JobFile = '', [string]$Voice = '', [int]$Rate = 0, [switch]$List)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$utf8 = New-Object System.Text.UTF8Encoding $false
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    if ($List) {
        $voices = @($synth.GetInstalledVoices() | Where-Object { $_.Enabled } | ForEach-Object {
            $v = $_.VoiceInfo
            [pscustomobject]@{ name = $v.Name; culture = $v.Culture.Name; gender = "$($v.Gender)"; age = "$($v.Age)" }
        })
        [System.IO.File]::WriteAllText($ResultFile, (ConvertTo-Json -InputObject $voices -Depth 3), $utf8)
        exit 0
    }
    $synth.SelectVoice($Voice)
    $synth.Rate = $Rate
    $synth.Volume = 100
    $format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000,
        [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
    # -InputObject, not the pipeline: piped, Windows PowerShell 5.1 hands the array on as one item
    $jobs = ConvertFrom-Json -InputObject ([System.IO.File]::ReadAllText($JobFile, [System.Text.Encoding]::UTF8))
    if ($jobs -isnot [array]) { $jobs = @($jobs) }
    $null = Register-ObjectEvent -InputObject $synth -EventName SpeakProgress -SourceIdentifier CarrierWord
    $prompts = @()
    foreach ($job in $jobs) {
        $prompt = New-Object System.Speech.Synthesis.Prompt([string]$job.text)
        $synth.SetOutputToWaveFile([string]$job.wav, $format)
        $synth.Speak($prompt)
        $synth.SetOutputToNull()  # closes the wave file
        $prompts += $prompt
    }
    # Word events are queued from worker threads and can land after Speak returns (and
    # out of order), so wait until the queue stops growing, then match them by prompt.
    $seen = -1
    while ($true) {
        Start-Sleep -Milliseconds 150
        $count = @(Get-Event -SourceIdentifier CarrierWord -ErrorAction SilentlyContinue).Count
        if ($count -eq $seen) { break }
        $seen = $count
    }
    $events = @(Get-Event -SourceIdentifier CarrierWord -ErrorAction SilentlyContinue)
    $results = @()
    for ($i = 0; $i -lt $jobs.Count; $i++) {
        $mine = @($events | Where-Object { [object]::ReferenceEquals($_.SourceEventArgs.Prompt, $prompts[$i]) })
        $words = @($mine | ForEach-Object {
            $a = $_.SourceEventArgs
            [pscustomobject]@{ text = $a.Text; char = $a.CharacterPosition; start_s = $a.AudioPosition.TotalSeconds }
        })
        $results += [pscustomobject]@{ id = $jobs[$i].id; words = $words }
    }
    [System.IO.File]::WriteAllText($ResultFile, (ConvertTo-Json -InputObject $results -Depth 5), $utf8)
} finally {
    Unregister-Event -SourceIdentifier CarrierWord -ErrorAction SilentlyContinue  # else exit code 2
    $synth.Dispose()
}
exit 0
"""


@dataclass(frozen=True)
class Word:
    text: str
    start: float  # seconds in the current signal
    end: float


def _powershell() -> str:
    exe = shutil.which("powershell.exe") or shutil.which("powershell") or shutil.which("pwsh")
    if not exe:
        raise SystemExit("error: PowerShell not found; System.Speech needs Windows")
    return exe


def _run_tts_script(work: Path, *args: str) -> None:
    script = work / "carrier_tts.ps1"
    script.write_text(PS_TTS, encoding="ascii")
    cmd = [_powershell(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
           "-File", str(script), *args]
    proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=900)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()
        raise SystemExit(f"error: System.Speech step failed (exit {proc.returncode}):\n{detail}")


def list_voices(work: Path) -> list[dict]:
    result = work / "voices.json"
    _run_tts_script(work, "-List", "-ResultFile", str(result))
    voices = json.loads(result.read_text(encoding="utf-8-sig"))
    return [voices] if isinstance(voices, dict) else voices


def pick_voice(voices: list[dict], requested: str | None) -> str:
    names = [v["name"] for v in voices]
    if not names:
        raise SystemExit("error: no enabled System.Speech voices installed")
    if requested:
        for name in names:
            if name.lower() == requested.lower():
                return name
        raise SystemExit(f"error: voice {requested!r} not installed; have: {', '.join(names)}")
    for name in PREFERRED_VOICES:
        if name in names:
            return name
    english = [v["name"] for v in voices if str(v.get("culture", "")).lower().startswith("en")]
    return (english or names)[0]


def _read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as wav:
        if wav.getnchannels() != 1 or wav.getsampwidth() != 2:
            raise SystemExit(f"error: {path}: expected mono 16-bit from System.Speech")
        rate = wav.getframerate()
        pcm = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2")
    return pcm.astype(np.float64) / FULL_SCALE, rate


def synthesize(lines: list[Line], voice: str, rate: int, work: Path) -> dict[str, tuple[np.ndarray, list[dict]]]:
    """Speaks every line at 16 kHz. Returns {id: (samples, [{text, char, start_s}])}."""
    jobs = [{"id": line.id, "text": line.text, "wav": str(work / f"{line.id}.wav")} for line in lines]
    job_file, result_file = work / "jobs.json", work / "tts_result.json"
    job_file.write_text(json.dumps(jobs), encoding="utf-8")
    _run_tts_script(work, "-JobFile", str(job_file), "-ResultFile", str(result_file),
                    "-Voice", voice, "-Rate", str(rate))
    results = json.loads(result_file.read_text(encoding="utf-8-sig"))
    results = [results] if isinstance(results, dict) else results
    words_by_id = {}
    for entry in results:
        words = entry.get("words") or []
        words_by_id[entry["id"]] = [words] if isinstance(words, dict) else words
    out = {}
    for job in jobs:
        audio, tts_rate = _read_wav(Path(job["wav"]))
        if tts_rate != TTS_SR:
            raise SystemExit(f"error: System.Speech wrote {tts_rate} Hz for {job['id']}, asked for {TTS_SR}")
        out[job["id"]] = (audio, words_by_id.get(job["id"], []))
    return out


def parse_rate(engine: str, value: str | int | None) -> str | int:
    """--rate for an engine: "-10%"-style for edge, an int -10..10 for sapi."""
    if engine == "edge":
        if value is None:
            return EDGE_DEFAULT_RATE
        if not EDGE_RATE_RE.fullmatch(str(value)):
            raise SystemExit(f"error: edge rate {value!r} must look like -10% or +5% (write --rate=-10%)")
        return str(value)
    if value is None:
        return DEFAULT_RATE
    try:
        rate = int(value)
    except ValueError:
        raise SystemExit(f"error: sapi rate {value!r} is not an integer -10..10") from None
    if not -10 <= rate <= 10:
        raise SystemExit(f"error: sapi rate {rate} outside -10..10")
    return rate


@dataclass
class Speech:
    """What a TTS engine said: {id: (samples, [{text, start_s}])} at ``sample_rate``."""
    engine: str
    voice: str
    rate: str | int
    sample_rate: int
    lines: dict[str, tuple[np.ndarray, list[dict]]]


def _speak_sapi(lines: list[Line], voice_request: str | None, rate: int, work: Path) -> Speech:
    voices = list_voices(work)
    voice = pick_voice(voices, voice_request)
    print("System.Speech voices installed: "
          + "; ".join(f"{v['name']} ({v.get('culture')}, {v.get('gender')})" for v in voices))
    print(f"using System.Speech voice {voice!r}, rate {rate}")
    return Speech("sapi", voice, rate, TTS_SR, synthesize(lines, voice, rate, work))


def speak(lines: list[Line], engine: str, voice_request: str | None, rate: str | int | None,
          cache_dir: Path, work: Path) -> Speech:
    """Speaks every line with ``engine``. If edge-tts fails, says so and speaks every line
    with System.Speech instead (its default voice and rate: an edge voice name means
    nothing to SAPI)."""
    if engine == "sapi":
        return _speak_sapi(lines, voice_request, parse_rate("sapi", rate), work)
    voice = voice_request or EDGE_DEFAULT_VOICE
    edge_rate = parse_rate("edge", rate)
    try:
        spoken = cet.synthesize([(line.id, line.text) for line in lines], voice, edge_rate, cache_dir, log=print)
    except cet.EdgeTTSError as exc:
        print(f"WARNING: edge-tts failed ({exc}); falling back to System.Speech for every line")
        return _speak_sapi(lines, None, DEFAULT_RATE, work)
    print(f"using edge-tts voice {voice!r}, rate {edge_rate}, cache {cache_dir}")
    return Speech("edge", voice, edge_rate, cet.EDGE_SR, {k: (a, w) for k, (a, _sr, w) in spoken.items()})


# --------------------------------------------------------------------------- helpers

def _time(duration: float) -> np.ndarray:
    return np.arange(int(round(duration * SR))) / SR


def _edge_fades(n: int, fade_s: float) -> np.ndarray:
    """Gain curve with raised-cosine fades on both edges; first and last values are 0."""
    k = min(int(round(fade_s * SR)), n // 2)
    gain = np.ones(n)
    if k > 0:
        ramp = 0.5 - 0.5 * np.cos(np.pi * np.arange(k) / k)
        gain[:k] *= ramp
        gain[n - k:] *= ramp[::-1]
    return gain


def _soft_step(octaves: np.ndarray, centre: float, width: float) -> np.ndarray:
    u = np.clip((octaves - centre) / width + 0.5, 0.0, 1.0)
    return 0.5 - 0.5 * np.cos(np.pi * u)


def _band(x: np.ndarray, lo: float | None = None, hi: float | None = None,
          width_oct: float = 0.5) -> np.ndarray:
    """Zero-phase FFT band limit with raised-cosine edges ``width_oct`` octaves wide.

    Zero-padded to at least twice the length, so the filter never wraps the end of the
    signal back onto its start.
    """
    n = len(x)
    nfft = 1 << int(np.ceil(np.log2(2 * n)))
    spectrum = np.fft.rfft(x, nfft)
    octaves = np.log2(np.maximum(np.fft.rfftfreq(nfft, 1.0 / SR), 1e-6))
    mask = np.ones_like(octaves)
    if lo:
        mask *= _soft_step(octaves, np.log2(lo), width_oct)
    if hi:
        mask *= 1.0 - _soft_step(octaves, np.log2(hi), width_oct)
    return np.fft.irfft(spectrum * mask, nfft)[:n]


def _upsample(x: np.ndarray, factor: int) -> np.ndarray:
    """Band-limited integer upsampling by zero-padding the spectrum."""
    pad = 512  # the clip is silent at both ends, so the circular FFT never wraps audibly
    x = np.pad(x, pad)
    n = len(x)
    spectrum = np.fft.rfft(x)
    wide = np.zeros(n * factor // 2 + 1, dtype=complex)
    wide[:len(spectrum)] = spectrum
    if n % 2 == 0:
        wide[len(spectrum) - 1] *= 0.5  # the old Nyquist bin is now an ordinary bin
    return np.fft.irfft(wide, n * factor)[pad * factor: -pad * factor] * factor


def _window_rms(x: np.ndarray, win: int) -> np.ndarray:
    n = len(x) // win
    if n == 0:
        return np.array([np.sqrt(np.mean(x ** 2))]) if len(x) else np.zeros(1)
    return np.sqrt(np.mean(x[:n * win].reshape(n, win) ** 2, axis=1))


def _active_span(x: np.ndarray, rel_db: float, win_s: float = 0.005) -> tuple[int, int]:
    """(first, end) sample of the windows within ``rel_db`` of the loudest window."""
    win = max(1, int(win_s * SR))
    rms = _window_rms(x, win)
    active = np.flatnonzero(rms >= rms.max() * 10.0 ** (rel_db / 20.0))
    if rms.max() <= 0 or len(active) == 0:
        return 0, len(x)
    return int(active[0] * win), int(min(len(x), (active[-1] + 1) * win))


def _db(value: float) -> float:
    return 20.0 * np.log10(value) if value > 0 else float("-inf")


# ------------------------------------------------------------------------- robotise

def _prepare(audio: np.ndarray, raw_words: list[dict], src_sr: int = TTS_SR) -> tuple[np.ndarray, list[Word]]:
    """Upsample to 48 kHz, trim the synthesizer's silence, turn word events into spans,
    and shorten long pauses."""
    if SR % src_sr:
        raise SystemExit(f"error: speech at {src_sr} Hz does not divide {SR} Hz")
    x = _upsample(audio, SR // src_sr)
    first, end = _active_span(x, TTS_TRIM_DB)
    a = max(0, first - int(0.020 * SR))
    b = min(len(x), end + int(0.050 * SR))
    x = x[a:b]
    offset, speech_end = a / SR, (end - a) / SR

    starts = sorted((max(0.0, float(w["start_s"]) - offset), str(w.get("text", ""))) for w in raw_words)
    if not starts:  # no word events: fall back to the gaps in the energy envelope
        starts = [(s, "?") for s in _energy_onsets(x)]
    words = []
    for i, (start, text) in enumerate(starts):
        stop = starts[i + 1][0] if i + 1 < len(starts) else max(speech_end, start + 0.05)
        words.append(Word(text, start, stop))
    return _cap_pauses(x, words)


def _cap_pauses(x: np.ndarray, words: list[Word]) -> tuple[np.ndarray, list[Word]]:
    """Cuts the middle out of every internal pause longer than MAX_PAUSE_S."""
    win = int(0.010 * SR)
    rms = _window_rms(x, win)
    silent = rms < rms.max() * 10.0 ** (PAUSE_DB / 20.0)
    loud = np.flatnonzero(~silent)
    if len(loud) == 0:
        return x, words
    cuts = []  # (start, end) samples to remove
    run_start = None
    for i in range(int(loud[0]), int(loud[-1]) + 1):
        if silent[i] and run_start is None:
            run_start = i
        elif not silent[i] and run_start is not None:
            excess = (i - run_start) * win - int(MAX_PAUSE_S * SR)
            if excess > 0:
                a = run_start * win + int(MAX_PAUSE_S * SR) // 2
                cuts.append((a, a + excess))
            run_start = None
    if not cuts:
        return x, words

    def moved(t: float) -> float:
        s = t * SR
        removed = sum(min(max(s - a, 0.0), b - a) for a, b in cuts)
        return (s - removed) / SR

    keep = np.ones(len(x), dtype=bool)
    for a, b in cuts:
        keep[a:b] = False
    return x[keep], [replace(w, start=moved(w.start), end=moved(w.end)) for w in words]


def _energy_onsets(x: np.ndarray) -> list[float]:
    win = int(0.010 * SR)
    rms = _window_rms(x, win)
    active = rms >= rms.max() * 10.0 ** (-30.0 / 20.0)
    rises = np.flatnonzero(active & ~np.concatenate(([False], active[:-1])))
    return [float(i * win / SR) for i in rises] or [0.0]


def _f0_track(x: np.ndarray, sr: int, hop_s: float = 0.010, win_s: float = 0.040,
              fmin: float = 60.0, fmax: float = 400.0) -> tuple[np.ndarray, np.ndarray]:
    """Normalised-autocorrelation pitch track. Returns (frame centre times, f0 or NaN)."""
    hop, win = int(hop_s * sr), int(win_s * sr)
    lag_min, lag_max = int(sr / fmax), int(np.ceil(sr / fmin))
    seg = win + lag_max
    n_frames = max(1, int(np.ceil(len(x) / hop)))
    xp = np.pad(x, (0, seg + hop))
    frames = xp[hop * np.arange(n_frames)[:, None] + np.arange(seg)[None, :]]
    head = frames[:, :win]
    nfft = 1 << int(np.ceil(np.log2(seg + win)))
    corr = np.fft.irfft(np.conj(np.fft.rfft(head, nfft)) * np.fft.rfft(frames, nfft), nfft)[:, :lag_max + 1]
    cum = np.concatenate((np.zeros((n_frames, 1)), np.cumsum(frames ** 2, axis=1)), axis=1)
    lags = np.arange(lag_max + 1)
    energy_lag = cum[:, lags + win] - cum[:, lags]
    energy_0 = energy_lag[:, :1]
    nacf = corr / np.sqrt(energy_0 * energy_lag + 1e-12)

    frame_rms = np.sqrt(energy_0[:, 0] / win)
    loud_enough = frame_rms >= frame_rms.max() * 10.0 ** (-35.0 / 20.0)
    f0 = np.full(n_frames, np.nan)
    for k in np.flatnonzero(loud_enough):
        curve = nacf[k, lag_min:lag_max + 1]
        best = curve.max()
        if best < 0.5:
            continue
        i = int(np.argmax(curve >= 0.9 * best))  # first near-best peak: avoids octave-down picks
        while i + 1 < len(curve) and curve[i + 1] > curve[i]:
            i += 1
        lag = float(i + lag_min)
        if 0 < i < len(curve) - 1:  # parabolic refinement
            y0, y1, y2 = curve[i - 1], curve[i], curve[i + 1]
            denom = y0 - 2.0 * y1 + y2
            if denom < 0:
                lag += 0.5 * (y0 - y2) / denom
        f0[k] = sr / lag
    times = (hop * np.arange(n_frames) + win / 2) / sr
    return times, f0


def _flatten_curve(x: np.ndarray, factor: int = UPSAMPLE) -> np.ndarray:
    """Per-sample pitch shift (octaves) pulling the voiced pitch towards its median."""
    times, f0 = _f0_track(x[::factor], SR // factor)  # x was upsampled by factor, so decimation is safe
    voiced = ~np.isnan(f0)
    if voiced.sum() < 3:
        return np.zeros(len(x))
    log_f0 = np.log2(f0[voiced])
    log_f0 = np.median(np.lib.stride_tricks.sliding_window_view(np.pad(log_f0, 2, mode="edge"), 5), axis=1)
    shift_voiced = np.clip(-FLATTEN * (log_f0 - np.median(log_f0)), -MAX_SHIFT_OCT, MAX_SHIFT_OCT)
    shift = np.interp(times, times[voiced], shift_voiced)
    shift = np.convolve(np.pad(shift, 2, mode="edge"), np.ones(5) / 5.0, mode="valid")  # 50 ms smoothing
    return np.interp(np.arange(len(x)) / SR, times, shift)


def _sag_curve(n: int, octaves: float = SAG_OCT) -> np.ndarray:
    u = np.clip((np.arange(n) / max(n - 1, 1) - SAG_START) / (1.0 - SAG_START), 0.0, 1.0)
    return octaves * u ** 2  # slow at first, then falling away like a dying motor


def _pitch_shift(x: np.ndarray, ratio: np.ndarray) -> np.ndarray:
    """Resample-based pitch shift with a time-varying ratio (two crossfaded delay-line heads).

    Each head reads the input at ``ratio`` x speed through a delay that sweeps across a
    30 ms window and wraps where that head's gain is zero. Resampling moves the formants
    with the pitch, so flattening the pitch also flattens the formant movement riding on it.
    The W/2 read offset makes ratio == 1 an identity.
    """
    window = SHIFTER_WINDOW_S * SR
    n = np.arange(len(x))
    phase = (0.5 + np.cumsum(1.0 - ratio) / window) % 1.0
    out = np.zeros(len(x))
    for head_phase in (phase, (phase + 0.5) % 1.0):
        gain = np.sin(np.pi * head_phase) ** 2  # the two gains sum to 1
        read = n + window / 2.0 - head_phase * window
        out += gain * np.interp(read, n, x, left=0.0, right=0.0)
    return out


def _ring_mod(x: np.ndarray, mix: float = RING_MIX) -> np.ndarray:
    t = np.arange(len(x)) / SR
    return x * ((1.0 - mix) + mix * np.sin(2.0 * np.pi * RING_HZ * t))


def _crush(x: np.ndarray, hold: int = CRUSH_HOLD, bits: int = CRUSH_BITS, mix: float = CRUSH_MIX) -> np.ndarray:
    """Sample-and-hold (48 kHz / hold) and ``bits``-bit quantisation, mixed in at ``mix``.
    The light chain's defaults: 8 kHz, 8 bits, 20 %."""
    held = np.repeat(x[::hold], hold)[:len(x)]
    peak = np.max(np.abs(held)) or 1.0
    steps = 2 ** (bits - 1) - 1
    crushed = np.round(held / peak * steps) / steps * peak
    return (1.0 - mix) * x + mix * crushed


def _comb(x: np.ndarray, delays_s: tuple[float, ...] = COMB_DELAYS_S, feedback: float = COMB_FEEDBACK,
          mix: float = COMB_MIX) -> np.ndarray:
    """Short metallic resonance: feedback combs, impulse response truncated at -60 dB."""
    wet = np.zeros(len(x))
    for delay_s in delays_s:
        d = int(round(delay_s * SR))
        k = 1
        while feedback ** k >= 1e-3 and k * d < len(x):
            wet[k * d:] += feedback ** k * x[:-k * d]
            k += 1
    return x + mix * wet / len(delays_s)


def _speaker(x: np.ndarray, style: dict | None = None) -> np.ndarray:
    """Small-speaker / radio stage. The crush goes before the band limit so its
    sample-rate fold-down lands in band as grit while its images above 4 kHz are removed.
    ``style`` is a HEAVY_STYLES entry, or None for the light chain's settings."""
    if style is None:
        return _comb(_band(_crush(x), lo=BAND_HZ[0], hi=BAND_HZ[1], width_oct=BAND_EDGE_OCT))
    crushed = _crush(x, *style["crush"])
    return _comb(_band(crushed, lo=BAND_HZ[0], hi=BAND_HZ[1], width_oct=BAND_EDGE_OCT), *style["comb"])


# ------------------------------------------------------------------- heavy: vocoder

def _smooth(x: np.ndarray, seconds: float) -> np.ndarray:
    """Zero-phase box smoother applied twice (a triangle ``2 * seconds`` long)."""
    k = max(1, int(round(seconds * SR)) | 1)  # odd, so it stays centred
    for _ in range(2):
        c = np.concatenate(([0.0], np.cumsum(np.pad(x, k // 2, mode="edge"))))
        x = (c[k:] - c[:-k]) / k
    return x


def vocoder_band_edges(bands: int = VOCODER_BANDS, lo: float = VOCODER_RANGE_HZ[0],
                       hi: float = VOCODER_RANGE_HZ[1]) -> np.ndarray:
    """``bands + 1`` band edges in Hz, evenly spaced on the mel scale."""
    mel = np.linspace(2595.0 * np.log10(1 + lo / 700.0), 2595.0 * np.log10(1 + hi / 700.0), bands + 1)
    return 700.0 * (10.0 ** (mel / 2595.0) - 1.0)


def saw_carrier(f0: np.ndarray, top_hz: float = CARRIER_TOP_HZ) -> np.ndarray:
    """Band-limited sawtooth (additive, 1/k harmonics up to ``top_hz``) following the
    per-sample pitch ``f0``."""
    phase = 2.0 * np.pi * np.cumsum(f0) / SR
    out = np.zeros(len(f0))
    for k in range(1, int(top_hz / max(np.min(f0), 1.0)) + 1):
        # each harmonic fades out over the last 10 % below top_hz, per sample, as the pitch moves
        gain = np.clip((top_hz - k * f0) / (0.1 * top_hz), 0.0, 1.0)
        if gain.any():
            out += gain * np.sin(k * phase) / k
    return out * (2.0 / np.pi)


def channel_vocoder(modulator: np.ndarray, voiced_carrier: np.ndarray, noise_carrier: np.ndarray,
                    voicing: np.ndarray, edges: np.ndarray | None = None) -> np.ndarray:
    """Classic channel vocoder on a zero-phase FFT filter bank.

    Each band's envelope (RMS, ~50 Hz smoothing) is measured on ``modulator`` and imposed
    on the same band of the carrier: the buzz where ``voicing`` is 1, the noise where it
    is 0 (bands centred above NOISE_FLOOR_HZ always keep NOISE_FLOOR of noise, for the
    sibilants). Each carrier band is levelled to a steady envelope first, so the output's
    spectral envelope is the modulator's while its pitch is the carrier's.
    """
    edges = vocoder_band_edges() if edges is None else np.asarray(edges, dtype=float)
    n = len(modulator)
    nfft = 1 << int(np.ceil(np.log2(2 * n)))
    octaves = np.log2(np.maximum(np.fft.rfftfreq(nfft, 1.0 / SR), 1e-6))
    steps = [_soft_step(octaves, np.log2(e), VOCODER_EDGE_OCT) for e in edges]
    spectra = [np.fft.rfft(sig, nfft) for sig in (modulator, voiced_carrier, noise_carrier)]

    def level(sig: np.ndarray) -> np.ndarray:
        rms = np.sqrt(np.mean(sig ** 2)) or 1.0
        env = np.sqrt(np.maximum(_smooth(sig ** 2, CARRIER_ENV_S), 0.0))
        return sig / np.maximum(env, 0.25 * rms)

    out = np.zeros(n)
    for b in range(len(edges) - 1):
        mask = steps[b] - steps[b + 1]  # the masks telescope: they sum to 1 inside the range
        mod, buzz, hiss = (np.fft.irfft(spec * mask, nfft)[:n] for spec in spectra)
        env = np.sqrt(np.maximum(_smooth(mod ** 2, VOCODER_ENV_S), 0.0))
        floor = NOISE_FLOOR if np.sqrt(edges[b] * edges[b + 1]) >= NOISE_FLOOR_HZ else 0.0
        v = voicing * (1.0 - floor)
        out += env * (v * level(buzz) + (1.0 - v) * level(hiss))
    return out


def carrier_pitch(style: str, n: int) -> np.ndarray:
    """Per-sample carrier pitch in Hz for a style: flat, up a little for "warning", and
    sagging over the second half for "failing"."""
    base = CARRIER_HZ * 2.0 ** (HEAVY_STYLES[style]["carrier_st"] / 12.0)
    if style == "failing":
        return base * 2.0 ** _sag_curve(n, HEAVY_SAG_OCT)
    return np.full(n, base)


def _pitch_frames(x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Pitch track of 48 kHz speech at 16 kHz (band-limited first, so decimating is safe)."""
    return _f0_track(_band(x, hi=4000.0)[::3], SR // 3)


def _voicing(times: np.ndarray, f0: np.ndarray, n: int) -> np.ndarray:
    """0..1 per sample: 1 where the tracker found a pitch."""
    voiced = (~np.isnan(f0)).astype(float)
    return np.clip(_smooth(np.interp(np.arange(n) / SR, times, voiced), VOICING_SMOOTH_S / 2), 0.0, 1.0)


def _onto_carrier_curve(times: np.ndarray, f0: np.ndarray, carrier: np.ndarray) -> np.ndarray:
    """Per-sample shift (octaves) that pulls the voiced pitch HEAVY_FLATTEN of the way onto
    the carrier's pitch."""
    voiced = ~np.isnan(f0)
    if voiced.sum() < 3:
        return np.zeros(len(carrier))
    log_f0 = np.log2(f0[voiced])
    log_f0 = np.median(np.lib.stride_tricks.sliding_window_view(np.pad(log_f0, 2, mode="edge"), 5), axis=1)
    target = np.log2(np.interp(times[voiced], np.arange(len(carrier)) / SR, carrier))
    shift_voiced = np.clip(HEAVY_FLATTEN * (target - log_f0), -HEAVY_MAX_SHIFT_OCT, HEAVY_MAX_SHIFT_OCT)
    shift = np.interp(times, times[voiced], shift_voiced)
    shift = np.convolve(np.pad(shift, 2, mode="edge"), np.ones(5) / 5.0, mode="valid")  # 50 ms smoothing
    return np.interp(np.arange(len(carrier)) / SR, times, shift)


def heavy_voice(x: np.ndarray, style: str, voicing: np.ndarray | None = None,
                noise_seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """The heavy chain's voice stage: vocoder on a fixed-pitch buzz, the flattened original
    blended under it, the style's drive, then ring modulation. Returns (signal, carrier Hz)."""
    style_cfg = HEAVY_STYLES[style]
    n = len(x)
    carrier = carrier_pitch(style, n)
    times, f0 = _pitch_frames(x)
    if voicing is None:
        voicing = _voicing(times, f0, n)
    noise = np.random.default_rng(noise_seed).standard_normal(n)
    voc = channel_vocoder(x, saw_carrier(carrier), noise, voicing)
    flat = _pitch_shift(x, 2.0 ** _onto_carrier_curve(times, f0, carrier))

    def unit(sig: np.ndarray) -> np.ndarray:
        return sig / (np.sqrt(np.mean(sig ** 2)) or 1.0)

    y = (1.0 - HEAVY_BLEND) * unit(voc) + HEAVY_BLEND * unit(flat)
    drive = style_cfg["drive"]
    if drive > 1.0:  # a harder edge: soft clipping
        y = np.tanh(drive * y / np.max(np.abs(y))) / np.tanh(drive)
    return _ring_mod(y, style_cfg["ring_mix"]), carrier


def _beep() -> np.ndarray:
    parts = []
    for i, (freq, dur) in enumerate(BEEP_TONES):
        t = _time(dur)
        tone = (np.sin(2.0 * np.pi * freq * t) + 0.25 * np.sin(2.0 * np.pi * 3.0 * freq * t)) / 1.25
        parts.append(tone * _edge_fades(len(t), 0.004))
        gap = BEEP_GAP_S if i + 1 < len(BEEP_TONES) else BEEP_TO_VOICE_S
        parts.append(np.zeros(int(round(gap * SR))))
    return BEEP_LEVEL * np.concatenate(parts)


def _stutter(x: np.ndarray, words: list[Word], rng: np.random.Generator
             ) -> tuple[np.ndarray, list[Word], tuple[float, float], str]:
    """Repeats the first syllable of one word, like a skipping buffer."""
    letters = [sum(c.isalpha() for c in w.text) for w in words]
    candidates = [i for i, w in enumerate(words) if letters[i] >= 3 and (i < len(words) - 1 or len(words) == 1)]
    i = int(rng.choice(candidates or list(range(len(words)))))
    word = words[i]
    length = int(np.clip(0.45 * (word.end - word.start), *STUTTER_LEN_S) * SR)
    s = min(int(word.start * SR), max(0, len(x) - length))
    k = int(0.003 * SR)
    ramp = 0.5 - 0.5 * np.cos(np.pi * np.arange(k) / k)
    before, after = x[:s].copy(), x[s:].copy()
    if len(before) >= k:
        before[-k:] *= ramp[::-1]
    after[:k] *= ramp[:len(after[:k])]
    syllable = x[s:s + length] * _edge_fades(length, 0.003)
    inserted = np.tile(syllable, STUTTER_REPEATS)
    shift = len(inserted) / SR
    new_words = [w if j < i else replace(w, start=w.start + shift, end=w.end + shift) for j, w in enumerate(words)]
    region = (s / SR, (s + len(inserted) + length) / SR)
    return np.concatenate((before, inserted, after)), new_words, region, word.text


def _dropouts(x: np.ndarray, rng: np.random.Generator, avoid: list[tuple[float, float]]
              ) -> tuple[np.ndarray, list[tuple[float, float]]]:
    """Gates 2-4 short spans of speech to silence (2 ms edges)."""
    duration = len(x) / SR
    want = int(np.clip(round(duration / DROPOUT_EVERY_S), *DROPOUT_COUNT))
    win = int(0.010 * SR)
    rms = _window_rms(x, win)
    centres = (np.arange(len(rms)) + 0.5) * win / SR
    ok = (rms >= rms.max() * 10.0 ** (-25.0 / 20.0)) & (centres > 0.12) & (centres < duration - 0.12)
    for lo, hi in avoid:
        ok &= (centres < lo - 0.06) | (centres > hi + 0.06)
    pool = centres[ok]
    spans: list[tuple[float, float]] = []
    for _ in range(400):
        if len(spans) == want or len(pool) == 0:
            break
        centre, length = float(rng.choice(pool)), float(rng.uniform(*DROPOUT_LEN_S))
        if all(abs(centre - (a + b) / 2.0) >= DROPOUT_SPACING_S for a, b in spans):
            spans.append((centre - length / 2.0, centre + length / 2.0))
    t = np.arange(len(x)) / SR
    gain = np.ones(len(x))
    edge = 0.002
    for a, b in spans:
        fall = np.clip((t - a) / edge, 0.0, 1.0)
        rise = np.clip((b - t) / edge, 0.0, 1.0)
        closed = np.minimum(fall, rise)  # 1 inside the span, ramps at both edges
        gain *= 1.0 - (0.5 - 0.5 * np.cos(np.pi * closed))
    return x * gain, sorted(spans)


def finalise(x: np.ndarray) -> tuple[np.ndarray, float]:
    """Trim silence, 5 ms edge fades, DC removal, -3 dBFS peak normalisation, int16.

    Returns (samples, seconds trimmed off the start).
    """
    first, end = _active_span(x, FINAL_TRIM_DB)
    start = max(0, first - int(TRIM_HEAD_S * SR))
    x = x[start:min(len(x), end + int(TRIM_TAIL_S * SR))]
    gain = _edge_fades(len(x), EDGE_FADE_S)
    x = x * gain
    x = x - gain * (x.sum() / gain.sum())  # zero mean, and the edges stay exactly 0
    x = x * (10.0 ** (PEAK_DBFS / 20.0) / np.max(np.abs(x)))
    return np.round(x * PCM_SCALE).astype("<i2"), start / SR


def render_line(line: Line, audio: np.ndarray, raw_words: list[dict], robot: str = "light",
                src_sr: int = TTS_SR) -> tuple[np.ndarray, list[str]]:
    """Speech at ``src_sr`` -> (int16 samples at 48 kHz, notes on what the style variant
    did, in file time). ``robot`` is "light" (pitch flattening + ring mod) or "heavy"
    (channel vocoder on a fixed-pitch buzz)."""
    if robot not in ROBOTS:
        raise ValueError(f"robot {robot!r} not one of {ROBOTS}")
    rng = np.random.default_rng(line.seed)
    x, words = _prepare(audio, raw_words, src_sr)
    x = x / (np.max(np.abs(x)) or 1.0)

    speaker_style = None
    if robot == "heavy":
        x, carrier = heavy_voice(x, line.style, noise_seed=line.seed)
        speaker_style = HEAVY_STYLES[line.style]
    else:
        shift = _flatten_curve(x, SR // src_sr)
        if line.style == "failing":
            shift = shift + _sag_curve(len(x))
        x = _ring_mod(_pitch_shift(x, 2.0 ** shift))

    stutter = None
    avoid: list[tuple[float, float]] = []
    if line.style == "failing":
        x, words, region, stuttered = _stutter(x, words, rng)
        stutter = (stuttered, region[0])
        avoid.append(region)
    lead = 0.0
    if line.style == "warning":
        beep = _beep()
        lead = len(beep) / SR
        x = np.concatenate((beep, x))
        words = [replace(w, start=w.start + lead, end=w.end + lead) for w in words]
        avoid = [(a + lead, b + lead) for a, b in avoid]

    # The cut and the dropouts happen upstream of the speaker, so the speaker's band limit
    # smooths their edges (gating after it leaks thumps below 200 Hz) and its resonance
    # rings briefly into each gap.
    cut = None
    if line.id in CUT_LAST_WORD:
        last = words[-1]
        cut = (last.text, last.start + CUT_LAST_WORD[line.id] * (last.end - last.start))
        x = x[:int(cut[1] * SR)]
    spans: list[tuple[float, float]] = []
    if line.style == "failing":
        x, spans = _dropouts(x, rng, avoid)

    x = _speaker(np.pad(x, (0, int(0.060 * SR))), speaker_style)  # room for the comb tail
    pcm, trimmed = finalise(x)

    def at(t: float) -> str:  # a time in the written file
        return f"{max(0.0, t - trimmed):.2f}"

    notes = []
    if robot == "heavy":
        notes.append(f"vocoder {VOCODER_BANDS} bands on a {carrier[0]:.0f} Hz buzz, {HEAVY_BLEND:.0%} original")
    if line.style == "warning":
        notes.append(f"two-tone prefix {BEEP_TONES[0][0]:.0f}/{BEEP_TONES[1][0]:.0f} Hz, voice from {at(lead)} s")
    if line.style == "failing":
        sag = HEAVY_SAG_OCT if robot == "heavy" else SAG_OCT
        notes.append(f"pitch sag to {12 * sag:+.1f} st from {SAG_START:.0%} of the line")
        notes.append(f"stutter on {ascii(stutter[0])} at {at(stutter[1])} s")
    if cut:
        notes.append(f"cut {CUT_LAST_WORD[line.id]:.0%} into {ascii(cut[0])} at {at(cut[1])} s")
    if spans:
        notes.append("dropouts at " + ", ".join(f"{at(a)}-{at(b)}" for a, b in spans) + " s")
    return pcm, notes


# ------------------------------------------------------------------------ generation

def write_wav(path: Path, pcm: np.ndarray) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with wave.open(str(tmp), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SR)
        wav.writeframes(pcm.tobytes())
    os.replace(tmp, path)


def write_json(path: Path, data: object) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def render_all(lines: list[Line], speech: Speech, robot: str) -> dict[str, tuple[np.ndarray, list[str]]]:
    """Renders every line in ``speech`` plus the pre-mixes whose sources are all there."""
    rendered = {}
    for line in lines:
        if line.id not in speech.lines:
            continue
        audio, raw_words = speech.lines[line.id]
        if not raw_words:
            print(f"  note: no word timings for {line.id}; using energy onsets")
        rendered[line.id] = render_line(line, audio, raw_words, robot=robot, src_sr=speech.sample_rate)
    for clip, sources, gap in premix_clips([line for line in lines if line.id in rendered]):
        silence = np.zeros(int(round(gap * SR)), dtype="<i2")
        parts = [part for src in sources for part in (rendered[src][0], silence)][:-1]
        rendered[clip.id] = (np.concatenate(parts), [f"pre-mix of {', '.join(sources)} with {gap} s gaps"])
    return rendered


def _emit(path: Path, pcm: np.ndarray, style: str, notes: list[str]) -> float:
    write_wav(path, pcm)
    duration = len(pcm) / SR
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    print(f"wrote {path.name:<44} {duration:5.2f} s  {style:<7}  sha256 {digest}")
    for note in notes:
        print(f"        {note}")
    return duration


def generate(lines: list[Line], out_dir: Path, voice_request: str | None, rate: str | int | None,
             engine: str = "edge", robot: str = "heavy") -> Speech:
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="carrier_tts_") as tmp:
        speech = speak(lines, engine, voice_request, rate, out_dir / CACHE_DIR_NAME, Path(tmp))
    print(f"robot chain: {robot}")
    rendered = render_all(lines, speech, robot)
    manifest = []
    for line in lines + [clip for clip, _, _ in premix_clips(lines)]:
        pcm, notes = rendered[line.id]
        duration = _emit(out_dir / line.filename, pcm, line.style, notes)
        manifest.append({"id": line.id, "file": line.filename, "text": line.text,
                         "style": line.style, "duration_s": round(duration, 3)})
    write_json(out_dir / MANIFEST_NAME, manifest)
    print(f"wrote {out_dir / MANIFEST_NAME}  ({len(manifest)} entries)")
    return speech


def sample_filename(letter: str, voice: str, clip_id: str) -> str:
    """'A', 'en-US-GuyNeural', 'CV_BOOT' -> 'A_en-US-Guy_CV_BOOT.wav'."""
    return f"{letter}_{voice.removesuffix('Neural')}_{clip_id}.wav"


def generate_samples(lines: list[Line], out_dir: Path, rate: str | int | None, robot: str) -> bool:
    """Each SAMPLE_VOICES voice speaks the pre-mix sources and SAMPLE_LINES into
    <out>/samples/. Edge only: a sample set in the fall-back voice would compare nothing."""
    sample_dir = out_dir / SAMPLES_DIR_NAME
    sample_dir.mkdir(parents=True, exist_ok=True)
    wanted = {src for _, (sources, _) in PREMIXES.items() for src in sources} | set(SAMPLE_LINES)
    subset = [line for line in lines if line.id in wanted]
    clips = [clip for clip, _, _ in premix_clips(subset)] + [line for line in subset if line.id in SAMPLE_LINES]
    edge_rate = parse_rate("edge", rate)
    ok = True
    for letter, voice in SAMPLE_VOICES:
        print(f"sample voice {letter}: {voice}")
        try:
            spoken = cet.synthesize([(line.id, line.text) for line in subset], voice, edge_rate,
                                    out_dir / CACHE_DIR_NAME, log=print)
        except cet.EdgeTTSError as exc:
            print(f"  FAIL  edge-tts failed for {voice}: {exc}")
            ok = False
            continue
        speech = Speech("edge", voice, edge_rate, cet.EDGE_SR, {k: (a, w) for k, (a, _sr, w) in spoken.items()})
        rendered = render_all(subset, speech, robot)
        for clip in clips:
            path = sample_dir / sample_filename(letter, voice, clip.id)
            pcm, notes = rendered[clip.id]
            _emit(path, pcm, clip.style, notes)
            problems, _ = check_file(clip, path)
            for problem in problems:
                print(f"  FAIL  {path.name}: {problem}")
            ok &= not problems
    return ok


# ----------------------------------------------------------------------------- check

def _band_share(pcm: np.ndarray, rate: int, lo: float, hi: float) -> float:
    power = np.abs(np.fft.rfft(pcm)) ** 2
    freqs = np.fft.rfftfreq(len(pcm), 1.0 / rate)
    total = power.sum()
    return float(power[(freqs >= lo) & (freqs <= hi)].sum() / total) if total > 0 else 0.0


def _beep_purity(pcm: np.ndarray, rate: int) -> float:
    """Lowest share of energy near each beep tone's frequency, measured inside that tone."""
    shares, start = [], 0.0
    for freq, dur in BEEP_TONES:
        seg = pcm[int((start + 0.015) * rate):int((start + dur - 0.015) * rate)]
        if len(seg) < 64:
            return 0.0
        power = np.abs(np.fft.rfft(seg * np.hanning(len(seg)), 1 << 14)) ** 2
        freqs = np.fft.rfftfreq(1 << 14, 1.0 / rate)
        shares.append(power[np.abs(freqs - freq) <= 60.0].sum() / (power.sum() or 1.0))
        start += dur + BEEP_GAP_S
    return float(min(shares))


def check_file(line: Line, path: Path) -> tuple[list[str], dict]:
    """Returns (problems, measurements)."""
    if not path.is_file():
        return ["file missing"], {}
    with wave.open(str(path), "rb") as wav:
        channels, width, rate = wav.getnchannels(), wav.getsampwidth(), wav.getframerate()
        frames, comptype = wav.getnframes(), wav.getcomptype()
        raw = wav.readframes(frames)
    problems = []
    if rate != SR:
        problems.append(f"rate {rate} != {SR}")
    if channels != 1:
        problems.append(f"{channels} channels, expected mono")
    if width != 2:
        problems.append(f"{8 * width}-bit, expected 16-bit")
    if comptype != "NONE":
        problems.append(f"compression {comptype}, expected PCM")
    if frames == 0:
        problems.append("no audio frames")
    if width != 2 or channels != 1 or frames == 0:
        return problems, {}

    pcm = np.frombuffer(raw, dtype="<i2").astype(np.float64)
    if len(pcm) != frames:
        problems.append(f"truncated: {len(pcm)} of {frames} frames")
    m = {
        "duration": len(pcm) / rate,
        "peak": _db(np.max(np.abs(pcm)) / FULL_SCALE),
        "rms": _db(np.sqrt(np.mean(pcm ** 2)) / FULL_SCALE),
        "dc": abs(np.mean(pcm)) / FULL_SCALE * 100.0,
        "edges": (int(abs(pcm[0])), int(abs(pcm[-1]))),
        "in_band": _band_share(pcm, rate, 200.0, 5000.0),
    }
    rms20 = _window_rms(pcm, int(0.020 * rate))
    m["active"] = float(np.mean(rms20 >= rms20.max() * 10.0 ** (-30.0 / 20.0))) if rms20.max() > 0 else 0.0

    if not DURATION_RANGE_S[0] <= m["duration"] <= DURATION_RANGE_S[1]:
        problems.append(f"duration {m['duration']:.2f} s outside {DURATION_RANGE_S}")
    if not PEAK_RANGE_DBFS[0] <= m["peak"] <= PEAK_RANGE_DBFS[1]:
        problems.append(f"peak {m['peak']:.2f} dBFS outside {PEAK_RANGE_DBFS}")
    if not m["rms"] > MIN_RMS_DBFS:
        problems.append(f"RMS {m['rms']:.2f} dBFS, not above {MIN_RMS_DBFS} (silent?)")
    if m["active"] < MIN_ACTIVE:
        problems.append(f"only {m['active']:.0%} of 20 ms windows active, want >= {MIN_ACTIVE:.0%}")
    if m["dc"] > MAX_DC_PERCENT:
        problems.append(f"DC offset {m['dc']:.3f}% > {MAX_DC_PERCENT}%")
    if max(m["edges"]) > MAX_EDGE_LSB:
        problems.append(f"edges not silent (first {m['edges'][0]}, last {m['edges'][1]} LSB)")
    if m["in_band"] < MIN_IN_BAND:
        problems.append(f"only {m['in_band']:.1%} of energy in 200 Hz-5 kHz, want >= {MIN_IN_BAND:.0%}")
    if line.style == "warning":
        m["beep"] = _beep_purity(pcm, rate)
        if m["beep"] < MIN_BEEP_PURITY:
            problems.append(f"prefix beep purity {m['beep']:.2f} < {MIN_BEEP_PURITY} (beep missing?)")
    return problems, m


def check_manifest(lines: list[Line], out_dir: Path, durations: dict[str, float]) -> list[str]:
    path = out_dir / MANIFEST_NAME
    if not path.is_file():
        return [f"{MANIFEST_NAME} missing"]
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"{MANIFEST_NAME} is not valid JSON: {exc}"]
    if not isinstance(entries, list):
        return [f"{MANIFEST_NAME} is not a list"]
    problems = []
    ids = [e.get("id") for e in entries if isinstance(e, dict)]
    if ids != [line.id for line in lines]:
        problems.append(f"{MANIFEST_NAME} ids do not match the lines file plus pre-mixes (order included)")
    by_id = {e.get("id"): e for e in entries if isinstance(e, dict)}
    for line in lines:
        entry = by_id.get(line.id)
        if entry is None:
            continue
        if tuple(entry) != MANIFEST_KEYS:
            problems.append(f"{line.id}: manifest keys {tuple(entry)} != {MANIFEST_KEYS}")
        expected = {"file": line.filename, "text": line.text, "style": line.style}
        for key, value in expected.items():
            if entry.get(key) != value:
                problems.append(f"{line.id}: manifest {key} {entry.get(key)!r} != {value!r}")
        listed = entry.get("duration_s")
        if line.id in durations and abs(float(listed or -1) - durations[line.id]) > 0.001:
            problems.append(f"{line.id}: manifest duration_s {listed} != file {durations[line.id]:.3f}")
    return problems


def check(lines: list[Line], out_dir: Path) -> bool:
    print(f"check {out_dir}")
    print(f"  {'':4}  {'file':<36} {'style':<7} {'dur s':>5}  {'rms dBFS':>8}  {'peak':>6}  {'active':>6}  text")
    premixes = premix_clips(lines)
    clips = lines + [clip for clip, _, _ in premixes]
    results = {line.id: check_file(line, out_dir / line.filename) for line in clips}
    for clip, sources, gap in premixes:
        problems, m = results[clip.id]
        if m and all(results[s][1] for s in sources):
            want = sum(results[s][1]["duration"] for s in sources) + gap * (len(sources) - 1)
            if abs(m["duration"] - want) > 0.001:
                problems.append(f"pre-mix is {m['duration']:.3f} s, sources + gaps are {want:.3f} s (stale?)")

    failed, durations = 0, {}
    for line in clips:
        problems, m = results[line.id]
        if m:
            durations[line.id] = m["duration"]
            extra = f"  beep {m['beep']:.2f}" if "beep" in m else ""
            print(f"  {'PASS' if not problems else 'FAIL'}  {line.filename:<36} {line.style:<7} "
                  f"{m['duration']:5.2f}  {m['rms']:8.2f}  {m['peak']:6.2f}  {m['active']:6.0%}  "
                  f"{ascii(line.text)}{extra}")
        else:
            print(f"  FAIL  {line.filename:<36} {line.style:<7}")
        for problem in problems:
            print(f"        - {problem}")
        failed += bool(problems)

    manifest_problems = check_manifest(clips, out_dir, durations)
    print(f"  {'PASS' if not manifest_problems else 'FAIL'}  {MANIFEST_NAME}")
    for problem in manifest_problems:
        print(f"        - {problem}")

    expected = {line.filename for line in clips}
    for stale in sorted(p.name for p in out_dir.glob("VO_Carrier_*.wav") if p.name not in expected):
        print(f"  WARN  {stale} is not in the lines file (stale?)")

    total = sum(durations[line.id] for line in lines if line.id in durations)
    print(f"check: {len(clips) - failed}/{len(clips)} files pass ({len(lines)} lines + {len(premixes)} pre-mix),"
          f" manifest {'ok' if not manifest_problems else 'FAILS'}; {total:.1f} s of line audio"
          f" (48 kHz mono 16-bit PCM, {DURATION_RANGE_S[0]}-{DURATION_RANGE_S[1]:.0f} s, peak -3.5..-2.5 dBFS,"
          f" RMS > {MIN_RMS_DBFS:.0f} dBFS, >= {MIN_ACTIVE:.0%} active, |DC| <= 1%, silent edges,"
          f" >= {MIN_IN_BAND:.0%} energy in 200 Hz-5 kHz, warning beep present)")
    return failed == 0 and not manifest_problems


def _list_edge_voices() -> None:
    voices = [v for v in cet.list_voices() if v["Locale"].startswith("en-")]
    for v in sorted(voices, key=lambda v: (v["Gender"], v["ShortName"])):
        mark = "*" if v["ShortName"] == EDGE_DEFAULT_VOICE else " "
        tags = ", ".join(v.get("VoiceTag", {}).get("VoicePersonalities", []))
        print(f"{mark} {v['ShortName']:<34} {v['Gender']:<7} {tags}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="only re-read and check the existing files")
    parser.add_argument("--engine", choices=ENGINES, default="edge",
                        help="edge: edge-tts neural voices, cached (default); sapi: Windows System.Speech")
    parser.add_argument("--robot", choices=ROBOTS, default="heavy",
                        help="heavy: channel vocoder on a fixed-pitch buzz (default); light: the original chain")
    parser.add_argument("--samples", action="store_true",
                        help=f"render the candidate voices {[v for _, v in SAMPLE_VOICES]} into <out>/samples/")
    parser.add_argument("--list-voices", action="store_true", help="list the engine's voices and exit")
    parser.add_argument("--voice", help=f"voice name (edge default {EDGE_DEFAULT_VOICE}; "
                                        f"sapi default: first of {PREFERRED_VOICES})")
    parser.add_argument("--rate", help=f"speaking rate: edge '-10%%'-style (default {EDGE_DEFAULT_RATE.replace('%', '%%')}, "
                                       f"write --rate=-10%%), sapi -10..10 (default {DEFAULT_RATE})")
    parser.add_argument("--lines", type=Path, default=DEFAULT_LINES, help=f"lines JSON (default {DEFAULT_LINES})")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help=f"output folder (default {DEFAULT_OUT})")
    args = parser.parse_args(argv)

    if args.list_voices:
        if args.engine == "edge":
            _list_edge_voices()
            return 0
        with tempfile.TemporaryDirectory(prefix="carrier_tts_") as tmp:
            voices = list_voices(Path(tmp))
        default = pick_voice(voices, None) if voices else None
        for v in voices:
            mark = "*" if v["name"] == default else " "
            print(f"{mark} {v['name']:<28} {v.get('culture', ''):<6} {v.get('gender', ''):<7} {v.get('age', '')}")
        return 0

    lines = load_lines(args.lines)
    if args.samples:
        return 0 if generate_samples(lines, args.out, args.rate, args.robot) else 1
    parse_rate(args.engine, args.rate)  # fail on a bad rate before any work
    if not args.check:
        generate(lines, args.out, args.voice, args.rate, args.engine, args.robot)
    return 0 if check(lines, args.out) else 1


if __name__ == "__main__":
    sys.exit(main())
