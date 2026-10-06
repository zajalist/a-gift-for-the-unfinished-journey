"""edge-tts engine for make_carrier_voice.py: Microsoft's online neural voices, cached.

edge-tts sends each line's text to Microsoft's online text-to-speech service and gets
back 24 kHz mono MP3 plus WordBoundary events (word start and duration). This module
fetches a line once, stores the MP3 and the raw events in a cache folder under a hash of
(voice, rate, text), and serves every later run from that cache, so reruns need no network
and always decode to the same samples.

    synthesize([(id, text), ...], voice, rate, cache_dir) -> {id: (float samples, 24000, words)}

``words`` is ``[{text, start_s}]``, the shape make_carrier_voice's chain expects. Any
failure to reach the service raises EdgeTTSError, which the caller turns into a fall back
to System.Speech.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable

import numpy as np

EDGE_SR = 24_000  # edge-tts always returns audio-24khz-48kbitrate-mono-mp3
CACHE_VERSION = 1  # bump to invalidate every cached line
# Measured on this service: after a pause, a WordBoundary offset is fine, but the first
# word's offset is a fixed ~0.10 s marker while speech starts ~0.22 s in. Mid-phrase
# offsets run ~30 ms early against the decoded MP3 (decoder delay). So each start moves
# by WORD_LAG_S, then forward to the first frame of speech if it still lands in silence.
WORD_LAG_S = 0.030
ONSET_DB = -35.0  # "speech" = 5 ms windows within 35 dB of the loudest
ONSET_WIN_S = 0.005
FETCH_TIMEOUT_S = 60


class EdgeTTSError(RuntimeError):
    """The online service could not be reached or returned nothing usable."""


Fetch = Callable[[str, str, str], "tuple[bytes, list[dict]]"]


def cache_key(voice: str, rate: str, text: str) -> str:
    blob = json.dumps({"v": CACHE_VERSION, "voice": voice, "rate": rate, "text": text},
                      sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]


# ------------------------------------------------------------------------ service

async def _fetch_async(text: str, voice: str, rate: str) -> tuple[bytes, list[dict]]:
    import edge_tts  # imported here so the cache and the tests work without it

    comm = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary",
                                receive_timeout=FETCH_TIMEOUT_S)
    audio, words = bytearray(), []
    async for chunk in comm.stream():
        if chunk["type"] == "audio":
            audio += chunk["data"]
        elif chunk["type"] == "WordBoundary":  # offset and duration are in 100 ns ticks
            words.append({"text": chunk["text"], "offset_s": chunk["offset"] / 1e7,
                          "duration_s": chunk["duration"] / 1e7})
    return bytes(audio), words


def fetch(text: str, voice: str, rate: str) -> tuple[bytes, list[dict]]:
    """One line from the online service: (MP3 bytes, [{text, offset_s, duration_s}])."""
    try:
        audio, words = asyncio.run(_fetch_async(text, voice, rate))
    except ImportError as exc:
        raise EdgeTTSError(f"edge-tts is not installed ({exc})") from exc
    except Exception as exc:  # network, TLS, service or protocol errors
        raise EdgeTTSError(f"{type(exc).__name__}: {exc}") from exc
    if not audio:
        raise EdgeTTSError(f"no audio returned for {text!r} with {voice}")
    return audio, words


def list_voices() -> list[dict]:
    import edge_tts

    try:
        return asyncio.run(edge_tts.list_voices())
    except Exception as exc:
        raise EdgeTTSError(f"{type(exc).__name__}: {exc}") from exc


# ------------------------------------------------------------------------- decode

def decode_mp3(data: bytes) -> np.ndarray:
    """MP3 bytes -> float64 mono samples at EDGE_SR, in [-1, 1).

    Uses PyAV when it is installed, else the ffmpeg command line.
    """
    try:
        import av
    except ImportError:
        av = None
    if av is not None:
        with av.open(io.BytesIO(data)) as container:
            stream = container.streams.audio[0]
            resampler = av.AudioResampler(format="s16", layout="mono", rate=EDGE_SR)
            parts = [f.to_ndarray().ravel() for frame in container.decode(stream) for f in resampler.resample(frame)]
            parts += [f.to_ndarray().ravel() for f in resampler.resample(None)]
        pcm = np.concatenate(parts) if parts else np.zeros(0, dtype=np.int16)
    else:
        exe = shutil.which("ffmpeg")
        if not exe:
            raise EdgeTTSError("cannot decode MP3: neither PyAV nor ffmpeg is available")
        proc = subprocess.run([exe, "-hide_banner", "-loglevel", "error", "-i", "pipe:0", "-ac", "1",
                               "-ar", str(EDGE_SR), "-f", "s16le", "pipe:1"], input=data, capture_output=True)
        if proc.returncode != 0:
            raise EdgeTTSError(f"ffmpeg could not decode MP3: {proc.stderr.decode(errors='replace')}")
        pcm = np.frombuffer(proc.stdout, dtype="<i2")
    return pcm.astype(np.float64) / 32768.0


def align_words(audio: np.ndarray, sr: int, raw_words: list[dict]) -> list[dict]:
    """[{text, offset_s, duration_s}] from the service -> [{text, start_s}] in ``audio``."""
    win = max(1, int(ONSET_WIN_S * sr))
    n = len(audio) // win
    if n == 0:
        return [{"text": w["text"], "start_s": float(w["offset_s"])} for w in raw_words]
    rms = np.sqrt(np.mean(audio[:n * win].reshape(n, win) ** 2, axis=1))
    active = rms >= rms.max() * 10.0 ** (ONSET_DB / 20.0) if rms.max() > 0 else np.ones(n, dtype=bool)
    words = []
    for w in raw_words:
        start = float(w["offset_s"]) + WORD_LAG_S
        end = float(w["offset_s"]) + float(w.get("duration_s", 0.0))
        i = int(start * sr) // win
        if i < n and not active[i]:
            later = np.flatnonzero(active[i:])
            if len(later):
                onset = (i + int(later[0])) * win / sr
                if onset < max(end, start + 0.05):
                    start = onset
        words.append({"text": str(w["text"]), "start_s": start})
    return words


# -------------------------------------------------------------------------- cache

class EdgeCache:
    """``<dir>/<key>.mp3`` (the service's audio, untouched) + ``<key>.json`` (the request
    and the raw WordBoundary events)."""

    def __init__(self, folder: Path):
        self.folder = Path(folder)

    def _paths(self, key: str) -> tuple[Path, Path]:
        return self.folder / f"{key}.mp3", self.folder / f"{key}.json"

    def load(self, voice: str, rate: str, text: str) -> tuple[bytes, list[dict]] | None:
        mp3, meta = self._paths(cache_key(voice, rate, text))
        if not (mp3.is_file() and meta.is_file()):
            return None
        info = json.loads(meta.read_text(encoding="utf-8"))
        if (info.get("voice"), info.get("rate"), info.get("text")) != (voice, rate, text):
            return None  # a hash collision or a hand-edited file: fetch again
        return mp3.read_bytes(), info["words"]

    def store(self, voice: str, rate: str, text: str, audio: bytes, words: list[dict]) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        mp3, meta = self._paths(cache_key(voice, rate, text))
        for path, blob in ((mp3, audio),
                           (meta, json.dumps({"voice": voice, "rate": rate, "text": text, "words": words},
                                             indent=1, ensure_ascii=False).encode("utf-8"))):
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_bytes(blob)
            os.replace(tmp, path)


def synthesize(jobs: list[tuple[str, str]], voice: str, rate: str, cache_dir: Path,
               fetch: Fetch = fetch, decode: Callable[[bytes], np.ndarray] = decode_mp3,
               log: Callable[[str], None] = lambda _msg: None) -> dict[str, tuple[np.ndarray, int, list[dict]]]:
    """Speaks every (id, text); returns {id: (samples, EDGE_SR, [{text, start_s}])}.

    Cached lines never touch the network. Raises EdgeTTSError if an uncached line
    cannot be fetched.
    """
    cache = EdgeCache(cache_dir)
    out, fetched = {}, 0
    for job_id, text in jobs:
        hit = cache.load(voice, rate, text)
        if hit is None:
            audio_bytes, raw_words = fetch(text, voice, rate)
            cache.store(voice, rate, text, audio_bytes, raw_words)
            fetched += 1
        else:
            audio_bytes, raw_words = hit
        audio = decode(audio_bytes)
        if len(audio) == 0:
            raise EdgeTTSError(f"{job_id}: decoded to no samples")
        out[job_id] = (audio, EDGE_SR, align_words(audio, EDGE_SR, raw_words))
    log(f"edge-tts {voice} {rate}: {len(jobs) - fetched} line(s) from cache, {fetched} fetched")
    return out
