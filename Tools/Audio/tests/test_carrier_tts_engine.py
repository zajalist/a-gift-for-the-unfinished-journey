"""edge-tts engine: cache keys, cached (offline, deterministic) reruns, word alignment,
and the fall back to System.Speech. No network: the fetcher is always a fake."""
import numpy as np
import pytest

import carrier_edge_tts as cet
import make_carrier_voice as mcv


def _fake_decode(data: bytes) -> np.ndarray:
    """Stands in for the MP3 decoder: the fake 'MP3' is just float32 samples."""
    return np.frombuffer(data, dtype="<f4").astype(np.float64)


def _fake_audio(text: str) -> bytes:
    sr = cet.EDGE_SR
    n = int(0.3 * sr) + int(0.08 * sr) * len(text)
    t = np.arange(n) / sr
    x = np.sin(2 * np.pi * 120 * t) * (t > 0.2)  # 0.2 s of leading silence, like the service
    return x.astype("<f4").tobytes()


class FakeService:
    def __init__(self):
        self.calls = []

    def __call__(self, text, voice, rate):
        self.calls.append((text, voice, rate))
        words = [{"text": w, "offset_s": 0.1 + 0.3 * i, "duration_s": 0.25} for i, w in enumerate(text.split())]
        return _fake_audio(text), words


def test_cache_key_is_stable_and_covers_voice_rate_and_text():
    k = cet.cache_key("en-US-GuyNeural", "-10%", "Route lock: High Voice.")
    assert k == cet.cache_key("en-US-GuyNeural", "-10%", "Route lock: High Voice.")
    assert k != cet.cache_key("en-GB-RyanNeural", "-10%", "Route lock: High Voice.")
    assert k != cet.cache_key("en-US-GuyNeural", "-5%", "Route lock: High Voice.")
    assert k != cet.cache_key("en-US-GuyNeural", "-10%", "Route lock: High Voice")
    assert len(k) >= 16 and all(c in "0123456789abcdef" for c in k)


def test_second_run_is_served_from_the_cache_offline(tmp_path):
    jobs = [("CV_A", "Contactor closing."), ("CV_B", "Load: one capsule. Archive.")]
    service = FakeService()
    first = cet.synthesize(jobs, "en-US-GuyNeural", "-10%", tmp_path, fetch=service, decode=_fake_decode)
    assert len(service.calls) == 2
    assert len(list(tmp_path.glob("*.mp3"))) == 2 and len(list(tmp_path.glob("*.json"))) == 2

    def offline(*_):
        raise cet.EdgeTTSError("no network")

    second = cet.synthesize(jobs, "en-US-GuyNeural", "-10%", tmp_path, fetch=offline, decode=_fake_decode)
    for job_id, _ in jobs:
        audio1, sr1, words1 = first[job_id]
        audio2, sr2, words2 = second[job_id]
        assert sr1 == sr2 == cet.EDGE_SR
        assert np.array_equal(audio1, audio2) and words1 == words2


def test_a_changed_line_is_fetched_again(tmp_path):
    service = FakeService()
    cet.synthesize([("CV_A", "Contactor closing.")], "v", "-10%", tmp_path, fetch=service, decode=_fake_decode)
    cet.synthesize([("CV_A", "Contactor open.")], "v", "-10%", tmp_path, fetch=service, decode=_fake_decode)
    assert [c[0] for c in service.calls] == ["Contactor closing.", "Contactor open."]


def test_word_starts_in_silence_snap_to_the_speech_onset():
    sr = cet.EDGE_SR
    audio = _fake_decode(_fake_audio("Carrier seven"))
    raw = [{"text": "Carrier", "offset_s": 0.1, "duration_s": 0.4}, {"text": "seven", "offset_s": 0.5, "duration_s": 0.3}]
    words = cet.align_words(audio, sr, raw)
    assert words[0]["text"] == "Carrier" and words[0]["start_s"] == pytest.approx(0.2, abs=0.012)
    assert words[1]["start_s"] == pytest.approx(0.5 + cet.WORD_LAG_S, abs=1e-9)  # already in speech
    assert all(set(w) == {"text", "start_s"} for w in words)


def test_edge_failure_falls_back_to_sapi_and_says_so(monkeypatch, capsys, tmp_path):
    lines = [mcv.Line("CV_A", "Contactor closing.", "system")]

    def broken(*_args, **_kwargs):
        raise cet.EdgeTTSError("Cannot connect to host speech.platform.bing.com")

    sapi_audio = np.zeros(1600)
    monkeypatch.setattr(cet, "synthesize", broken)
    monkeypatch.setattr(mcv, "list_voices", lambda work: [{"name": "Microsoft David Desktop", "culture": "en-US"}])
    monkeypatch.setattr(mcv, "synthesize", lambda lines, voice, rate, work: {"CV_A": (sapi_audio, [])})
    speech = mcv.speak(lines, "edge", None, None, tmp_path / "cache", tmp_path)
    assert speech.engine == "sapi" and speech.voice == "Microsoft David Desktop"
    assert speech.sample_rate == mcv.TTS_SR and speech.lines["CV_A"][0] is sapi_audio
    out = capsys.readouterr().out
    assert "edge-tts failed" in out and "falling back to System.Speech" in out


def test_edge_rate_is_validated():
    assert mcv.parse_rate("edge", None) == mcv.EDGE_DEFAULT_RATE
    assert mcv.parse_rate("edge", "-15%") == "-15%"
    assert mcv.parse_rate("sapi", None) == mcv.DEFAULT_RATE
    assert mcv.parse_rate("sapi", "-3") == -3
    with pytest.raises(SystemExit):
        mcv.parse_rate("edge", "fast")
    with pytest.raises(SystemExit):
        mcv.parse_rate("sapi", "11")
