"""Shared Freesound helper for replacing synthesized sounds with CC0 recordings.

Reads the API key from Saved/freesound.key (git-ignored; never print or copy it).
Uses token auth, so only previews can be downloaded: the HQ OGG preview (~192 kbps)
is decoded with ffmpeg to 48 kHz float32. Every sound used is logged with its
source and licence in Tools/Audio/freesound_credits.json, and CREDITS.md is
regenerated from that file.

    import freesound_fetch as fs
    hits = fs.search('wind mountain', min_dur=60, max_dur=600)
    audio = fs.fetch(hits[0])                      # (n, 2) float32 at 48 kHz
    loop = fs.make_loop(audio[:90 * fs.SR], 2.0)
    fs.write_wav('Saved/GameAudio/Recorded/Ambience/AMB_Valley_Wind.wav', fs.normalize(loop, -12))
    fs.credit('AMB_Valley_Wind', hits[0], alternates=hits[1:4], notes='first 90 s, looped')

    python Tools/Audio/freesound_fetch.py --selftest
"""
import json
import pathlib
import subprocess
import sys
import time
import urllib.parse
import urllib.request

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[2]
KEY_FILE = ROOT / "Saved" / "freesound.key"
CACHE = ROOT / "Saved" / "GameAudio" / "_freesound_cache"
CREDITS_JSON = ROOT / "Tools" / "Audio" / "freesound_credits.json"
CREDITS_MD = ROOT / "Tools" / "Audio" / "CREDITS.md"
API = "https://freesound.org/apiv2"
SR = 48000
CC0 = 'license:"Creative Commons 0"'
FIELDS = "id,name,tags,description,duration,avg_rating,num_ratings,num_downloads,license,username,url,previews,channels,samplerate"
# Never pick these for a no-music, no-people, post-collapse highland.
BANNED_TAGS = {
    "music", "melody", "song", "instrument", "guitar", "piano", "synth", "drone-music", "beat", "loop-music",
    "voice", "speech", "talking", "people", "crowd", "children", "kids", "laugh", "singing",
    "traffic", "car", "cars", "road-traffic", "engine", "motorbike", "airplane", "plane", "aircraft", "helicopter",
    "train", "siren", "city", "urban", "tv", "radio-music",
}
# Freesound allows 60 API calls a minute per key; three agents share it.
MIN_GAP_S = 3.2
_last_call = [0.0]


def _key():
    return json.loads(KEY_FILE.read_text(encoding="utf-8"))["api_key"]


def _get(path, params):
    wait = MIN_GAP_S - (time.monotonic() - _last_call[0])
    if wait > 0:
        time.sleep(wait)
    _last_call[0] = time.monotonic()
    query = urllib.parse.urlencode({**params, "token": _key()})
    with urllib.request.urlopen(f"{API}{path}?{query}", timeout=30) as reply:
        return json.load(reply)


def search(query, min_dur=0.0, max_dur=3600.0, extra_filter="", sort="score", page_size=30, allow_cc_by=False):
    """Text search; returns CC0 hits (optionally CC-BY too) with banned tags removed, best-rated first within relevance."""
    licence = CC0 if not allow_cc_by else '(license:"Creative Commons 0" OR license:"Attribution")'
    filt = f"{licence} duration:[{min_dur} TO {max_dur}]" + (f" {extra_filter}" if extra_filter else "")
    data = _get("/search/text/", {"query": query, "filter": filt, "fields": FIELDS, "sort": sort, "page_size": page_size})
    hits = [h for h in data["results"] if not (set(t.lower() for t in h.get("tags", [])) & BANNED_TAGS)]
    return hits


def fetch(hit, channels=2):
    """Download (cached) the HQ OGG preview and decode it to float32 (n, channels) at 48 kHz."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{hit['id']}.ogg"
    if not path.exists():
        with urllib.request.urlopen(hit["previews"]["preview-hq-ogg"], timeout=60) as reply:
            path.write_bytes(reply.read())
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-ac", str(channels), "-ar", str(SR), "-"],
        check=True, capture_output=True,
    ).stdout
    return np.frombuffer(raw, dtype=np.float32).reshape(-1, channels).copy()


def rms_db(x):
    return 20 * np.log10(np.sqrt(np.mean(np.square(x))) + 1e-12)


def normalize(x, peak_db):
    peak = np.max(np.abs(x)) + 1e-12
    return x * (10 ** (peak_db / 20) / peak)


def fade(x, fade_in_s=0.005, fade_out_s=0.005):
    x = x.copy()
    for n, sl in ((int(fade_in_s * SR), slice(None, None)), (int(fade_out_s * SR), slice(None, None, -1))):
        if n > 0:
            ramp = np.linspace(0.0, 1.0, n, dtype=np.float32)[:, None] if x.ndim == 2 else np.linspace(0.0, 1.0, n, dtype=np.float32)
            view = x[sl]
            view[:n] *= ramp
    return x


def make_loop(x, crossfade_s=2.0):
    """Seamless loop: equal-power crossfade of the tail into the head; result is len(x) - crossfade."""
    n = int(crossfade_s * SR)
    head, body, tail = x[:n], x[n:-n] if n else x, x[-n:]
    t = np.linspace(0.0, np.pi / 2, n, dtype=np.float32)
    t = t[:, None] if x.ndim == 2 else t
    seam = tail * np.cos(t) + head * np.sin(t)
    return np.concatenate([body, seam]) if n else x


def trim_silence(x, threshold_db=-50.0, pad_s=0.01):
    """Trim leading and trailing audio quieter than threshold (relative to peak)."""
    env = np.abs(x).max(axis=1) if x.ndim == 2 else np.abs(x)
    limit = env.max() * 10 ** (threshold_db / 20)
    idx = np.nonzero(env > limit)[0]
    if not len(idx):
        return x
    pad = int(pad_s * SR)
    return x[max(0, idx[0] - pad): idx[-1] + pad]


def write_wav(path, x):
    """48 kHz 16-bit PCM WAV; mono if 1-D or single column."""
    import soundfile
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if x.ndim == 2 and x.shape[1] == 1:
        x = x[:, 0]
    soundfile.write(str(path), np.clip(x, -1.0, 1.0), SR, subtype="PCM_16")


def credit(asset_name, hit, alternates=(), notes=""):
    """Record which Freesound sound became which asset. Re-crediting an asset replaces its entry."""
    data = json.loads(CREDITS_JSON.read_text(encoding="utf-8")) if CREDITS_JSON.exists() else {}
    data[asset_name] = {
        "freesound_id": hit["id"], "name": hit["name"], "author": hit["username"], "url": hit["url"],
        "license": hit["license"], "duration_s": round(hit["duration"], 2), "notes": notes,
        "alternates": [{"id": a["id"], "name": a["name"], "url": a["url"]} for a in alternates],
    }
    CREDITS_JSON.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8", newline="\n")
    rows = ["# Sound credits", "", "Recordings from [Freesound](https://freesound.org), chosen by `Tools/Audio/freesound_fetch.py`. CC0 needs no credit; it is listed anyway. CC-BY entries must stay credited in the game.", "",
            "| Asset | Sound | Author | Licence | Notes |", "|---|---|---|---|---|"]
    for name in sorted(data):
        e = data[name]
        rows.append(f"| `{name}` | [{e['name']}]({e['url']}) | {e['author']} | {e['license'].rsplit('/', 3)[-3] if 'creativecommons' in e['license'] else e['license']} | {e['notes']} |")
    CREDITS_MD.write_text("\n".join(rows) + "\n", encoding="utf-8", newline="\n")


def selftest():
    hits = search("wind mountain", min_dur=30, max_dur=600, page_size=5)
    assert hits, "no hits"
    audio = fetch(hits[0])
    assert audio.ndim == 2 and audio.shape[1] == 2 and len(audio) > SR * 10, audio.shape
    loop = make_loop(audio[: 20 * SR], 1.0)
    seam = abs(rms_db(loop[-2400:]) - rms_db(loop[:2400]))
    print(f"ok: {len(hits)} hits; '{hits[0]['name']}' decoded {len(audio) / SR:.1f} s; loop seam level gap {seam:.2f} dB")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
