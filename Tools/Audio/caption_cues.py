#!/usr/bin/env python3
"""Caption pages timed to the takes: the subtitle follows the voice.

Author takes use the locally reviewed faster-whisper transcript for spoken English and word timestamps for page
boundaries. The script supplies exact Saskartan spelling. Story lines spoken in Saskartan retain their authored
translation, and their pages use pauses in the take. TTS pages also use pauses. Long text is split into clauses of
at most about 90 characters. Review ASR errors in docs/story/caption-spoken-overrides.json.

    python Tools/Audio/transcribe_author.py    # transcribe new takes locally first
    python Tools/Audio/caption_cues.py            # analyse every take, write the pages, print the report
    python Tools/Audio/caption_cues.py --dry-run  # analyse and report only

Takes: Saved/RadioRecordings/author_mp3/<id>.mp3 (the author's; the game plays the aged selected/<id>.wav with the
same timing), else Saved/RadioRecordings/selected/<id>.wav (placeholder TTS). A line with no take gets no pages: the
game splits it by characters at runtime (FSaskartaCaptionPaging::ProportionalPages).

Output (read by the importers, carried into the data assets; no runtime docs/ reads):
  docs/story/station.json        segments[].caption_pages = [{"t": 0.0, "text": "..."}, ...]   (DA_Station)
  docs/story/caption-pages.json  lines.<ID> = [{"t": ..., "text": ..., "sks": ...}]           (DA_Saskarta_Story)
  docs/story/radio-lines-for-translation.tsv   spoken English for story lines
  Saved/RadioRecordings/caption_cues_report.json   differences and rate flags (local only)

The report's top_10 lists the largest reviewed script-versus-spoken differences.
"""
from __future__ import annotations

import csv
import difflib
import json
import math
import re
import subprocess
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
STORY = ROOT / "docs" / "story"
REC = ROOT / "Saved" / "RadioRecordings"
AUTHOR = REC / "author_mp3"
SELECTED = REC / "selected"
TRANSCRIPTS = ROOT / "Saved" / "Whisper" / "out"
OVERRIDES = STORY / "caption-spoken-overrides.json"

MAX_CHARS = 90           # one page: two subtitle lines
MIN_PAUSE_S = 0.25       # a silence this long is a cut candidate
LEAD_S = 0.12            # a page appears this much before its first word
MIN_PAGE_S = 0.7         # shorter pages are merged into a neighbour when they fit
MERGE_MAX_CHARS = 110
SR = 16000
HOP_S = 0.01
WIN_S = 0.02

# Parenthesised directions that mean the voice stops: preferred page cuts.
CUT_DIRECTION = re.compile(r"pause|beat|breath|sip|cough|static|question|hiss", re.IGNORECASE)


# ----------------------------------------------------------------------------------------------- text

def clean_spoken(text: str) -> str:
    """USaskartaStoryImport::CleanSpokenText: drops (directions) and literal quotes, collapses double spaces."""
    out = []
    depth = 0
    for c in text:
        if c == "(":
            depth += 1
            continue
        if c == ")":
            depth = max(0, depth - 1)
            continue
        if depth > 0 or c == '"':
            continue
        out.append(c)
    s = "".join(out)
    while "  " in s:
        s = s.replace("  ", " ")
    return s.strip()


def squash(s: str) -> str:
    return re.sub(r"\s+", "", s)


def letters(s: str) -> int:
    return sum(1 for c in s if c.isalnum())


def word_key(word: str) -> str:
    """Loose match for alignment only; final captions retain the author's spelling."""
    s = unicodedata.normalize("NFKD", word.casefold().replace("’", "'"))
    return "".join(c for c in s if c.isalnum())


def words(text: str) -> list[str]:
    return [w for w in text.split() if word_key(w)]


def apply_protected_names(text: str, script: str, name_spellings: list[str]) -> str:
    """Restore names that Whisper spelt approximately, using their position in the script.

    The script and transcript usually share the surrounding English. A name in a replaced
    span is anchored between the nearest equal words, so even a name Whisper split into
    several words is restored without changing the English around it.
    """
    source, said = words(script), words(text)
    known = {word_key(n): n for n in name_spellings}
    protected = {i: w for i, w in enumerate(source) if word_key(w) in known}
    if not protected:
        return text
    a, b = [word_key(w) for w in source], [word_key(w) for w in said]
    ops = difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
    replace: list[tuple[int, int, list[str]]] = []
    for tag, i1, i2, j1, j2 in ops:
        if tag == "equal":
            for k in range(i2 - i1):
                if i1 + k in protected:
                    said[j1 + k] = protected[i1 + k]
            continue
        names = [(i, protected[i]) for i in range(i1, i2) if i in protected]
        if not names or j1 == j2:
            continue
        if len(names) == 1:
            # A one-word name can become several Whisper words (e.g. Iy-la'har-dzehiy).
            # Preserve other English in a wide replacement span by choosing the closest
            # transcript word to the name's script-relative position.
            i, name = names[0]
            if i2 - i1 == 1:
                replace.append((j1, j2, [name]))
            else:
                j = j1 + min(j2 - j1 - 1, max(0, round((i - i1) * (j2 - j1) / (i2 - i1))))
                said[j] = name
        elif len(names) == i2 - i1:
            replace.append((j1, j2, [n for _, n in names]))
    for j1, j2, names in reversed(replace):
        said[j1:j2] = names
    return " ".join(said)


def transcribed_words(line_id: str) -> tuple[str, list[dict]] | None:
    path = TRANSCRIPTS / f"{line_id}.json"
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    timed = [w for segment in data["segments"] for w in segment["words"]
             if word_key(w["word"])]
    return data["text"].strip(), timed


def read_overrides() -> dict[str, str]:
    if not OVERRIDES.is_file():
        return {}
    return json.loads(OVERRIDES.read_text(encoding="utf-8"))["lines"]


def read_page_starts() -> dict[str, list[float]]:
    if not OVERRIDES.is_file():
        return {}
    return json.loads(OVERRIDES.read_text(encoding="utf-8")).get("page_starts", {})


def marker_chunks(raw: str) -> list[str]:
    """The TSV English split at the voice-stopping directions, each chunk cleaned like the runtime text."""
    parts = []
    cur = []
    depth = 0
    direction = []
    for c in raw:
        if c == "(":
            depth += 1
            if depth == 1:
                direction = []
            cur.append(c)
            continue
        if c == ")" and depth > 0:
            depth -= 1
            cur.append(c)
            if depth == 0 and CUT_DIRECTION.search("".join(direction)):
                parts.append("".join(cur))
                cur = []
            continue
        if depth > 0:
            direction.append(c)
        cur.append(c)
    parts.append("".join(cur))
    return [p for p in (clean_spoken(x) for x in parts) if p]


SENTENCE_END = re.compile(r"(?<=[.?!…])[\"'”’)]*\s+")
CLAUSE_END = re.compile(r"(?<=[,;:—–])\s+|\s+(?=[—–]\s)")


def split_sentences(text: str) -> list[str]:
    out = []
    pos = 0
    for m in SENTENCE_END.finditer(text):
        piece = text[pos:m.end()].strip()
        if piece:
            out.append(piece)
        pos = m.end()
    tail = text[pos:].strip()
    if tail:
        out.append(tail)
    return out


def split_long(piece: str, max_chars: int = MAX_CHARS) -> list[str]:
    """A sentence longer than a page: cut at the clause mark nearest its middle, else at the space nearest it."""
    if len(piece) <= max_chars:
        return [piece]
    mid = len(piece) / 2
    cuts = [m.end() for m in CLAUSE_END.finditer(piece) if 12 <= m.end() <= len(piece) - 12]
    if not cuts:
        cuts = [m.end() for m in re.finditer(r"\s+", piece) if 1 <= m.end() < len(piece)]
    if not cuts:
        return [piece]
    cut = min(cuts, key=lambda c: abs(c - mid))
    return split_long(piece[:cut].strip(), max_chars) + split_long(piece[cut:].strip(), max_chars)


def pack(pieces: list[str], max_chars: int = MAX_CHARS) -> list[str]:
    pages: list[str] = []
    for p in pieces:
        if pages and len(pages[-1]) + 1 + len(p) <= max_chars:
            pages[-1] = pages[-1] + " " + p
        else:
            pages.append(p)
    return pages


def page_text(chunks: list[str], max_chars: int = MAX_CHARS) -> list[str]:
    """Pages from chunks (marker cuts are hard: a page never spans one)."""
    pages: list[str] = []
    for ch in chunks:
        pieces = [q for s in split_sentences(ch) for q in split_long(s, max_chars)]
        pages += pack(pieces, max_chars)
    return pages


# ----------------------------------------------------------------------------------------------- audio

def load_audio(path: Path) -> np.ndarray:
    cmd = ["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(SR),
           "-af", "highpass=f=120,lowpass=f=4500", "-f", "f32le", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


def frame_db(x: np.ndarray) -> np.ndarray:
    hop = int(SR * HOP_S)
    win = int(SR * WIN_S)
    if len(x) < win:
        return np.full(1, -120.0)
    n = 1 + (len(x) - win) // hop
    idx = np.arange(win)[None, :] + hop * np.arange(n)[:, None]
    rms = np.sqrt(np.mean(x[idx] ** 2, axis=1) + 1e-12)
    return 20 * np.log10(rms)


@dataclass
class Activity:
    duration: float
    speech: list[tuple[float, float]]           # speech runs (s)
    pauses: list[tuple[float, float]] = field(default_factory=list)  # silences >= MIN_PAUSE_S between speech runs

    @property
    def speech_s(self) -> float:
        return sum(b - a for a, b in self.speech)


def detect(db: np.ndarray, duration: float) -> Activity:
    """Speech runs by energy with hysteresis: enter above floor + 50 % of the range, leave below floor + 38 %.
    The floor ignores digital silence (gated or padded takes), so room tone between phrases counts as a pause."""
    live = db[db > -85.0]
    if len(live) < 10:
        live = db
    floor = float(np.percentile(live, 8))
    peak = float(np.percentile(live, 97))
    rng = max(peak - floor, 6.0)
    on = floor + 0.50 * rng
    off = floor + 0.38 * rng
    speech = []
    active = False
    start = 0
    for i, v in enumerate(db):
        if not active and v >= on:
            active, start = True, i
        elif active and v < off:
            active = False
            speech.append((start, i))
    if active:
        speech.append((start, len(db)))
    runs = [(a * HOP_S, b * HOP_S + WIN_S) for a, b in speech]
    # Breaths and clicks: runs shorter than 0.1 s are not speech.
    runs = [r for r in runs if r[1] - r[0] >= 0.1]
    # Gaps shorter than a pause join their runs.
    merged: list[tuple[float, float]] = []
    for r in runs:
        if merged and r[0] - merged[-1][1] < MIN_PAUSE_S:
            merged[-1] = (merged[-1][0], r[1])
        else:
            merged.append(r)
    pauses = [(merged[i][1], merged[i + 1][0]) for i in range(len(merged) - 1)]
    return Activity(duration=duration, speech=merged, pauses=pauses)


def speech_time_before(act: Activity, t: float) -> float:
    return sum(max(0.0, min(b, t) - a) for a, b in act.speech if a < t)


def time_at_speech_share(act: Activity, share: float) -> float:
    target = share * act.speech_s
    acc = 0.0
    for a, b in act.speech:
        if acc + (b - a) >= target:
            return a + (target - acc)
        acc += b - a
    return act.speech[-1][1] if act.speech else share * act.duration


# ----------------------------------------------------------------------------------------------- timing

SKIP_COST = 0.10


def align(shares: list[float], act: Activity) -> list[float]:
    """Start times for pages 1..K-1 (page 0 is at 0). Each boundary takes the nearest pause in speaking-time share,
    in order, at most one boundary per pause (dynamic programming); a boundary with no pause near falls back to its
    share of the speaking time."""
    K = len(shares)
    total = act.speech_s
    if K == 0:
        return []
    if total <= 0.0:
        return [s * act.duration for s in shares]
    ps = [speech_time_before(act, a) / total for a, _ in act.pauses]
    bonus = [0.03 * min(b - a, 1.0) for a, b in act.pauses]
    P = len(ps)
    INF = 1e9
    # dp[k][j]: best cost for the first k boundaries using pauses < j; choice for backtracking.
    dp = [[INF] * (P + 1) for _ in range(K + 1)]
    ch = [[None] * (P + 1) for _ in range(K + 1)]
    for j in range(P + 1):
        dp[0][j] = 0.0
    for k in range(1, K + 1):
        dp[k][0] = dp[k - 1][0] + SKIP_COST
        ch[k][0] = ("skip", 0)
        for j in range(1, P + 1):
            best, how = dp[k][j - 1], ("unused", j - 1)
            c = dp[k - 1][j] + SKIP_COST
            if c < best:
                best, how = c, ("skip", j)
            c = dp[k - 1][j - 1] + abs(ps[j - 1] - shares[k - 1]) - bonus[j - 1]
            if c < best:
                best, how = c, ("use", j - 1)
            dp[k][j], ch[k][j] = best, how
    out: list[float | None] = [None] * K
    k, j = K, P
    while k > 0:
        kind, jj = ch[k][j]
        if kind == "unused":
            j = jj
            continue
        if kind == "use":
            a, b = act.pauses[jj]
            out[k - 1] = max(a, b - LEAD_S)
            j = jj
        else:
            out[k - 1] = max(0.0, time_at_speech_share(act, shares[k - 1]) - LEAD_S)
        k -= 1
    # Strictly increasing.
    res = []
    last = 0.0
    for t in out:
        t = max(float(t), last + 0.3)
        res.append(t)
        last = t
    return res


def time_pages(pages: list[str], weights: list[int], act: Activity) -> list[float]:
    total = sum(weights) or 1
    shares = []
    acc = 0
    for w in weights[:-1]:
        acc += w
        shares.append(acc / total)
    return [0.0] + align(shares, act)


def time_pages_from_words(pages: list[str], timed: list[dict], duration: float) -> list[float]:
    """Align a page's first word to the take's word timestamps, including edited name spellings."""
    page_tokens = [word_key(w) for page in pages for w in words(page)]
    take_tokens = [word_key(w["word"]) for w in timed]
    starts = [sum(len(words(page)) for page in pages[:i]) for i in range(1, len(pages))]
    if not take_tokens or not page_tokens:
        return [0.0] + [duration * n / max(1, len(page_tokens)) for n in starts]
    matches: dict[int, int] = {}
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, page_tokens, take_tokens, autojunk=False).get_opcodes():
        if tag == "equal":
            matches.update((i1 + k, j1 + k) for k in range(i2 - i1))
    out = [0.0]
    for index in starts:
        # Prefer the first matched word of the new page, then interpolate when a
        # Saskartan name is absent from the model transcript.
        after = next(((i, j) for i, j in sorted(matches.items()) if i >= index), None)
        before = next(((i, j) for i, j in sorted(matches.items(), reverse=True) if i < index), None)
        if after and after[0] - index <= 3:
            t = float(timed[after[1]]["start"])
        elif before and after:
            a, b = before, after
            share = (index - a[0]) / (b[0] - a[0])
            t = float(timed[a[1]]["end"]) + share * (float(timed[b[1]]["start"]) - float(timed[a[1]]["end"]))
        elif after:
            t = float(timed[after[1]]["start"]) * index / max(1, after[0])
        elif before:
            t = float(timed[before[1]]["end"]) + (duration - float(timed[before[1]]["end"])) * (
                (index - before[0]) / max(1, len(page_tokens) - before[0]))
        else:
            t = duration * index / len(page_tokens)
        out.append(max(out[-1] + 0.3, min(duration - 0.3, t - LEAD_S)))
    return out


def merge_short(pages: list[str], sks: list[str] | None, times: list[float], duration: float):
    """A page on screen for less than MIN_PAGE_S joins its neighbour when the two still fit."""
    changed = True
    while changed and len(pages) > 1:
        changed = False
        for i in range(len(pages)):
            end = times[i + 1] if i + 1 < len(times) else duration
            if end - times[i] >= MIN_PAGE_S:
                continue
            j = i + 1 if i + 1 < len(pages) else i - 1
            lo, hi = min(i, j), max(i, j)
            if len(pages[lo]) + 1 + len(pages[hi]) > MERGE_MAX_CHARS:
                continue
            pages[lo:hi + 1] = [pages[lo] + " " + pages[hi]]
            if sks is not None:
                sks[lo:hi + 1] = [(sks[lo] + " " + sks[hi]).strip()]
            del times[hi]
            changed = True
            break
    return pages, sks, times


# ----------------------------------------------------------------------------------------------- data

@dataclass
class Line:
    id: str
    text: str                 # the runtime caption text (without prefix)
    chunks: list[str]         # text split at the author's directions (or [text])
    sks: str = ""             # Saskartan original (spoken) when the line is SKS
    station: bool = False


def read_tsv() -> dict[str, dict]:
    rows = list(csv.reader((STORY / "radio-lines-for-translation.tsv").open(encoding="utf-8-sig"), delimiter="\t"))
    head = [h.strip() for h in rows[0]]

    def col(prefix: str) -> int:
        return next((i for i, h in enumerate(head) if h.lower().startswith(prefix.lower())), -1)

    ci, ce, cl, cs = col("ID"), col("English"), col("Language"), col("Saskartan translation")
    out = {}
    for r in rows[1:]:
        cell = lambda c: r[c].strip() if 0 <= c < len(r) else ""
        i = cell(ci)
        if i:
            out[i] = {"english": cell(ce), "sks": cell(cl).upper().startswith("SKS"), "saskartan": cell(cs)}
    return out


def collect() -> tuple[dict, list[Line]]:
    station = json.loads((STORY / "station.json").read_text(encoding="utf-8"))
    tsv = read_tsv()
    lines: list[Line] = []
    seg_ids = set()
    for s in station["segments"]:
        sid, text = s["id"], s.get("text", "")
        seg_ids.add(sid)
        chunks = [text]
        row = tsv.get(sid)
        if row:
            mc = marker_chunks(row["english"])
            if len(mc) > 1 and squash(" ".join(mc)) == squash(text):
                chunks = mc
        lines.append(Line(sid, text, chunks, station=True))
    for sid, row in tsv.items():
        if sid in seg_ids:
            continue
        text = clean_spoken(row["english"])
        if not text:
            continue
        sks = clean_spoken(row["saskartan"]) if row["sks"] else ""
        chunks = marker_chunks(row["english"]) if not sks else [text]
        if squash(" ".join(chunks)) != squash(text):
            chunks = [text]
        lines.append(Line(sid, text, chunks, sks=sks))
    return station, lines


def take_for(line_id: str) -> tuple[Path | None, str]:
    a = AUTHOR / f"{line_id}.mp3"
    if a.is_file():
        return a, "author"
    w = SELECTED / f"{line_id}.wav"
    if w.is_file():
        return w, "tts"
    return None, ""


def pages_for(line: Line, act: Activity, timed: list[dict] | None = None) -> list[dict]:
    pages = page_text(line.chunks)
    sks_pages = None
    if line.sks:
        en_s = split_sentences(line.text)
        sk_s = split_sentences(line.sks)
        if len(en_s) == len(sk_s) and len(en_s) > 1:
            # Pair sentence by sentence; group like the English pages.
            groups = []
            i = 0
            for p in pack([q for q in en_s]):
                n = len(split_sentences(p))
                groups.append((p, " ".join(sk_s[i:i + n])))
                i += n
            pages = [g[0] for g in groups]
            sks_pages = [g[1] for g in groups]
    if len(pages) < 2:
        return []
    weights = [letters(p) for p in (sks_pages if sks_pages else pages)]
    times = time_pages_from_words(pages, timed, act.duration) if timed and not line.sks else time_pages(pages, weights, act)
    pages, sks_pages, times = merge_short(pages, sks_pages, times, act.duration)
    if len(pages) < 2:
        return []
    out = []
    for i, (t, p) in enumerate(zip(times, pages)):
        d = {"t": round(t, 2), "text": p}
        if sks_pages:
            d["sks"] = sks_pages[i]
        out.append(d)
    return out


def analyse(path: Path) -> Activity:
    x = load_audio(path)
    return detect(frame_db(x), len(x) / SR)


MIN_JUDGED_LETTERS = 30   # shorter lines (room murmurs, single words) are listed as low confidence


def flag_rates(rows: list[dict]) -> list[dict]:
    """Author takes whose letters-per-second of speech sit far from the author's median (robust z on log rate)."""
    rates = np.array([r["rate"] for r in rows if r["rate"] > 0 and r["letters"] >= MIN_JUDGED_LETTERS])
    if len(rates) < 5:
        return []
    lr = np.log(rates)
    med = float(np.median(lr))
    mad = float(np.median(np.abs(lr - med))) * 1.4826 or 0.1
    flagged = []
    for r in rows:
        if r["rate"] <= 0:
            continue
        z = (math.log(r["rate"]) - med) / mad
        ratio = r["rate"] / math.exp(med)
        r["z"] = round(z, 2)
        r["vs_median"] = round(ratio, 2)
        if abs(z) >= 2.5 or ratio < 0.72 or ratio > 1.38:
            r["flag"] = "fewer words than the script?" if ratio > 1 else "more words than the script (or long gaps)?"
            r["confidence"] = "high" if r["letters"] >= MIN_JUDGED_LETTERS else "low (short line)"
            flagged.append(r)
    return flagged


def update_tsv_english(updates: dict[str, str]) -> None:
    """Change only English cells, preserving the sheet's other columns and formatting."""
    path = STORY / "radio-lines-for-translation.tsv"
    raw = path.read_text(encoding="utf-8-sig")
    lines = raw.splitlines(keepends=True)
    for index, row in enumerate(lines[1:], 1):
        end = "\r\n" if row.endswith("\r\n") else "\n" if row.endswith("\n") else ""
        cells = row.removesuffix(end).split("\t")
        if len(cells) < 6 or cells[1] not in updates:
            continue
        cells[5] = '"""' + updates[cells[1]].replace('"', '""') + '"""'
        lines[index] = "\t".join(cells) + end
    path.write_text("".join(lines), encoding="utf-8-sig", newline="")


def name_tokens() -> list[str]:
    data = json.loads((STORY / "names.json").read_text(encoding="utf-8"))
    out = [n["display_in_english_text"] for n in data["names"]]
    out += ["Zdawet", "Tarsan", "Zenwiy", "Ta'handedya", "abrîdiegm", "yeggar tababghē"]
    return [token for name in out for token in name.split()]


def final_spoken(line: Line, raw: str, overrides: dict[str, str], names: list[str]) -> str:
    caption = overrides.get(line.id, raw)
    if line.id not in overrides and "thank you" not in line.text.casefold():
        # Medium.en invents this sign-off at the end of several clips, often in
        # near-zero time with a very low first-word probability.
        caption = re.sub(r"(?:\s+Thank you(?: very much| for being here)?\.?)+$", "", caption, flags=re.IGNORECASE)
    caption = apply_protected_names(caption, line.text, names)
    return caption.strip()


def main() -> int:
    dry = "--dry-run" in sys.argv
    station, lines = collect()
    overrides = read_overrides()
    page_starts = read_page_starts()
    names = name_tokens()
    story_pages: dict[str, list[dict]] = {}
    station_pages: dict[str, list[dict]] = {}
    takes: dict[str, dict] = {}
    rate_rows: list[dict] = []
    text_updates: dict[str, str] = {}
    differences: list[dict] = []
    for line in lines:
        path, kind = take_for(line.id)
        if not path:
            continue
        transcript = transcribed_words(line.id) if kind == "author" else None
        timed = transcript[1] if transcript else None
        if transcript and not line.sks:
            before = line.text
            line.text = final_spoken(line, transcript[0], overrides, names)
            line.chunks = [line.text]
            text_updates[line.id] = line.text
            a, b = [word_key(w) for w in words(before)], [word_key(w) for w in words(line.text)]
            ratio = difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()
            if ratio < 0.999:
                differences.append({"id": line.id, "similarity": round(ratio, 3),
                                    "script": before, "spoken": line.text})
        # A caption that fits one page stays whole; only longer ones are paged.
        needs_pages = len(line.text) > MAX_CHARS and len(page_text(line.chunks)) > 1
        if not needs_pages and kind != "author":
            continue
        act = analyse(path)
        if kind == "author":
            spoken = line.sks or line.text
            sp = act.speech_s
            rate_rows.append({"id": line.id, "letters": letters(spoken), "take_s": round(act.duration, 2),
                              "speech_s": round(sp, 2), "pauses": len(act.pauses),
                              "rate": round(letters(spoken) / sp, 2) if sp > 0 else 0.0,
                              "lang": "SKS" if line.sks else "EN"})
        if not needs_pages:
            continue
        pg = pages_for(line, act, timed)
        if not pg:
            continue
        if line.id in page_starts:
            starts = page_starts[line.id]
            if len(starts) != len(pg) or starts[0] != 0 or any(b <= a for a, b in zip(starts, starts[1:])) \
                    or starts[-1] > act.duration - 0.3:
                raise ValueError(f"Invalid page starts for {line.id}: {starts}")
            for page, start in zip(pg, starts):
                page["t"] = start
        (station_pages if line.station else story_pages)[line.id] = pg
        takes[line.id] = {"take": kind, "duration_s": round(act.duration, 2), "pauses": len(act.pauses)}

    # The pillar readings (INSCR_*) are Saskartan words read by the author; their captions belong to the scanner.
    try:
        ins = json.loads((STORY / "inscriptions.json").read_text(encoding="utf-8"))
        for i in ins.get("inscriptions", []):
            vid = i.get("voice_line_id") or ""
            p = AUTHOR / f"{vid}.mp3"
            if vid and p.is_file() and i.get("saskartan"):
                act = analyse(p)
                sp = act.speech_s
                rate_rows.append({"id": vid, "letters": letters(i["saskartan"]), "take_s": round(act.duration, 2),
                                  "speech_s": round(sp, 2), "pauses": len(act.pauses),
                                  "rate": round(letters(i["saskartan"]) / sp, 2) if sp > 0 else 0.0, "lang": "SKS"})
    except (OSError, ValueError):
        pass

    # Rates are judged within a language (a Saskartan reading is slower and more deliberate).
    flagged = []
    for lang in ("EN", "SKS"):
        flagged += flag_rates([r for r in rate_rows if r["lang"] == lang])

    print(f"pages: {len(station_pages)} station segments, {len(story_pages)} story lines "
          f"({sum(1 for t in takes.values() if t['take'] == 'author')} author takes, "
          f"{sum(1 for t in takes.values() if t['take'] == 'tts')} TTS)")
    for lid in sorted(set(station_pages) | set(story_pages)):
        pg = station_pages.get(lid) or story_pages[lid]
        print(f"  {lid:26s} {takes[lid]['take']:6s} {takes[lid]['duration_s']:6.2f} s  "
              + " | ".join(f"{p['t']:.2f}" for p in pg))
    print(f"author takes checked: {len(rate_rows)}; flagged (speaking rate far from the median): {len(flagged)}")
    for r in sorted(flagged, key=lambda r: (r["confidence"] != "high", r["vs_median"])):
        print(f"  {r['id']:26s} {r['lang']} {r['letters']:4d} letters in {r['speech_s']:5.2f} s of speech "
              f"(take {r['take_s']:.2f} s): {r['rate']:.1f}/s = {r['vs_median']:.2f}x median  {r['flag']} [{r['confidence']}]")

    top = sorted(differences, key=lambda r: (r["similarity"], r["id"]))[:10]
    print("largest script-versus-said differences (reviewed English; Saskartan originals excluded):")
    for r in top:
        print(f"  {r['id']:26s} similarity {r['similarity']:.2f}")

    report = {"generated": date.today().isoformat(), "flagged": flagged, "rates": rate_rows,
              "takes": takes, "differences": differences, "top_10": top}
    if dry:
        return 0
    (REC / "caption_cues_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    for s in station["segments"]:
        if s["id"] in text_updates:
            s["text"] = text_updates[s["id"]]
            # A literal template is another copy of the caption. Keep it in step
            # so the importer and Station.RealData's plain-template invariant agree.
            if s.get("template") and "{" not in s["template"]:
                s["template"] = s["text"]
        pg = station_pages.get(s["id"])
        if pg:
            s["caption_pages"] = pg
        else:
            s.pop("caption_pages", None)
    with (STORY / "station.json").open("w", encoding="utf-8", newline="") as f:
        f.write(json.dumps(station, indent=2, ensure_ascii=False).replace("\n", "\r\n") + "\r\n")
    update_tsv_english(text_updates)

    out = {
        "version": 1,
        "generated": date.today().isoformat(),
        "source": "Tools/Audio/caption_cues.py (timed to the takes; re-run after a new take). Station segments carry "
                  "theirs in station.json; these are the story lines (radio-lines-for-translation.tsv ids).",
        "takes": {k: takes[k] for k in sorted(story_pages)},
        "lines": {k: story_pages[k] for k in sorted(story_pages)},
    }
    with (STORY / "caption-pages.json").open("w", encoding="utf-8", newline="") as f:
        f.write(json.dumps(out, indent=2, ensure_ascii=False).replace("\n", "\r\n") + "\r\n")
    print("wrote station.json, radio-lines-for-translation.tsv, caption-pages.json, and local caption_cues_report.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
