"""The heavy robot chain: channel vocoder, fixed-pitch carrier, per-style carriers, and
whole-line rendering. Everything runs on synthetic signals, so no TTS is needed."""
import hashlib

import numpy as np
import pytest

import make_carrier_voice as mcv

SR = mcv.SR


def _glide_voice(seconds=1.6, f_lo=90.0, f_hi=220.0, seed=0):
    """A voiced 'speech-like' signal: a harmonic tone gliding f_lo -> f_hi -> f_lo with
    vibrato, through two moving formant resonances, with a noisy fricative in the middle."""
    n = int(seconds * SR)
    t = np.arange(n) / SR
    u = t / seconds
    f0 = f_lo * (f_hi / f_lo) ** np.sin(np.pi * u) * 2.0 ** (0.03 * np.sin(2 * np.pi * 5.5 * t))
    phase = np.cumsum(f0) / SR
    x = np.zeros(n)
    for k in range(1, int(5000 / f_lo)):
        h = k * f0
        f1 = 500 + 300 * np.sin(2 * np.pi * 1.3 * t)
        f2 = 1500 + 700 * np.sin(2 * np.pi * 0.9 * t + 1)
        amp = (1 / (1 + ((h - f1) / 120) ** 2) + 0.6 / (1 + ((h - f2) / 200) ** 2)) * (h < SR / 2 - 1000)
        x += amp * np.sin(2 * np.pi * k * phase)
    rng = np.random.default_rng(seed)
    fric = (t > 0.7) & (t < 0.85)
    x[fric] = 0.3 * mcv._band(rng.standard_normal(n), lo=3000, hi=6000)[fric]
    return x / np.max(np.abs(x)), f0


def _log_f0(y):
    """Voiced-frame log2 f0 of a 48 kHz signal, tracked at 16 kHz."""
    y16 = mcv._band(y, hi=4000.0)[::3]
    _, f0 = mcv._f0_track(y16, 16_000)
    f0 = f0[~np.isnan(f0)]
    assert len(f0) > 20, "tracker found almost no voiced frames"
    return np.log2(f0)


def _spread(log_f0):
    """Robust pitch spread in octaves: 5th to 95th percentile (a single octave slip at a
    cut edge does not count)."""
    return np.percentile(log_f0, 95) - np.percentile(log_f0, 5)


def test_band_edges_are_16_to_24_mel_spaced_bands():
    edges = mcv.vocoder_band_edges()
    assert 16 <= len(edges) - 1 <= 24
    assert np.all(np.diff(edges) > 0)
    widths = np.diff(edges)
    assert widths[0] >= 60.0  # wide enough at the bottom to hold a harmonic of the buzz
    assert widths[-1] > widths[0]


def test_saw_carrier_is_band_limited_at_the_asked_pitch():
    f0 = np.full(SR, 100.0)
    saw = mcv.saw_carrier(f0)
    spec = np.abs(np.fft.rfft(saw)) ** 2
    freqs = np.fft.rfftfreq(len(saw), 1 / SR)
    assert freqs[np.argmax(spec)] == pytest.approx(100.0, abs=1.0)
    assert spec[freqs > mcv.CARRIER_TOP_HZ + 150].sum() < 1e-6 * spec.sum()
    assert np.std(np.diff(_log_f0(saw))) < 1e-3


def test_vocoder_output_pitch_is_flat_while_the_input_glides():
    x, _ = _glide_voice()
    assert _spread(_log_f0(x)) > 0.8  # the input really moves (over an octave)
    n = len(x)
    y = mcv.channel_vocoder(x, mcv.saw_carrier(np.full(n, 100.0)), np.random.default_rng(1).standard_normal(n),
                            voicing=np.ones(n))
    lf = _log_f0(y)
    assert _spread(lf) < 0.02  # dead flat: under a quarter semitone
    assert 2 ** np.median(lf) == pytest.approx(100.0, rel=0.03)


def test_vocoder_follows_the_modulator_envelope_and_spectrum():
    n = SR
    rng = np.random.default_rng(3)
    x = np.zeros(n)
    x[:n // 2] = mcv._band(rng.standard_normal(n), lo=300, hi=700)[:n // 2]  # low vowel-ish burst
    x[n // 2 + 4800:] = mcv._band(rng.standard_normal(n), lo=3000, hi=5000)[n // 2 + 4800:]  # hiss
    y = mcv.channel_vocoder(x, mcv.saw_carrier(np.full(n, 100.0)), rng.standard_normal(n), voicing=np.ones(n))

    def band_energy(sig, lo, hi):
        return np.sum(mcv._band(sig, lo=lo, hi=hi, width_oct=0.2) ** 2)

    first, second = y[:n // 2], y[n // 2 + 4800:]
    assert band_energy(first, 250, 800) > 20 * band_energy(first, 2500, 6000)
    assert band_energy(second, 2500, 6000) > 20 * band_energy(second, 250, 800)
    gap = y[n // 2 + 1200:n // 2 + 3600]
    assert np.sqrt(np.mean(gap ** 2)) < 0.03 * np.sqrt(np.mean(first ** 2))  # silence stays silent


def test_unvoiced_frames_use_the_noise_carrier():
    n = SR // 2
    rng = np.random.default_rng(4)
    x = mcv._band(rng.standard_normal(n), lo=300, hi=3000)
    saw = mcv.saw_carrier(np.full(n, 100.0))
    buzz = mcv.channel_vocoder(x, saw, rng.standard_normal(n), voicing=np.ones(n))
    hiss = mcv.channel_vocoder(x, saw, rng.standard_normal(n), voicing=np.zeros(n))

    def peakiness(sig):  # share of energy on the buzz's harmonics
        spec = np.abs(np.fft.rfft(sig)) ** 2
        freqs = np.fft.rfftfreq(len(sig), 1 / SR)
        near = np.abs(freqs - 100.0 * np.round(freqs / 100.0)) < 8.0
        return spec[near].sum() / spec.sum()

    assert peakiness(buzz) > 0.8
    assert peakiness(hiss) < 0.35


def test_style_carriers_system_warning_failing():
    n = 2 * SR
    system = mcv.carrier_pitch("system", n)
    warning = mcv.carrier_pitch("warning", n)
    failing = mcv.carrier_pitch("failing", n)
    assert np.all((system >= 90) & (system <= 110)) and np.ptp(system) == 0
    assert 1.03 < warning[0] / system[0] < 1.2  # a slight pitch up
    assert failing[0] == pytest.approx(system[0])
    assert np.all(np.diff(failing) <= 1e-9)  # never rises
    assert failing[n // 4] == pytest.approx(system[0])  # holds for the first half
    assert failing[-1] < 0.85 * system[0]  # then sags


@pytest.mark.parametrize("style", ["system", "warning", "failing"])
def test_heavy_voice_stage_is_flat_apart_from_the_sag(style):
    x, _ = _glide_voice(f_lo=95.0, f_hi=170.0)
    y, carrier = mcv.heavy_voice(x, style)  # voicing found by the chain's own tracker
    assert len(y) == len(x) and len(carrier) == len(x)
    head = y[:int(0.6 * SR)]  # before any sag
    lf = _log_f0(head)
    assert _spread(lf) < 0.05
    assert 2 ** np.median(lf) == pytest.approx(carrier[0], rel=0.05)


def _synthetic_line(seed=7):
    x, _ = _glide_voice(seconds=2.4, seed=seed)
    # Pretend it came from edge-tts: 24 kHz with silence around it and four "words".
    x24 = np.concatenate((np.zeros(4800), x[::2], np.zeros(7200)))
    words = [{"text": w, "start_s": s} for w, s in (("Carrier", 0.2), ("seven", 0.7), ("Critical", 1.1), ("failure", 1.7))]
    return x24, words


@pytest.mark.parametrize("style", ["system", "warning", "failing"])
def test_heavy_render_is_deterministic_and_passes_the_file_check(style, tmp_path):
    audio, words = _synthetic_line()
    line = mcv.Line("CV_TEST_01", "Carrier seven. Critical failure.", style)
    a, notes = mcv.render_line(line, audio, words, robot="heavy", src_sr=24_000)
    b, _ = mcv.render_line(line, audio, words, robot="heavy", src_sr=24_000)
    assert hashlib.sha256(a.tobytes()).digest() == hashlib.sha256(b.tobytes()).digest()
    path = tmp_path / line.filename
    mcv.write_wav(path, a)
    problems, _ = mcv.check_file(line, path)
    assert problems == []
    if style == "failing":
        assert any(n.startswith("stutter") for n in notes) and any(n.startswith("dropouts") for n in notes)


def test_heavy_and_light_differ_and_light_ignores_the_new_code():
    audio, words = _synthetic_line()
    line = mcv.Line("CV_TEST_02", "Carrier seven.", "system")
    light, _ = mcv.render_line(line, audio, words, robot="light", src_sr=24_000)
    heavy, _ = mcv.render_line(line, audio, words, robot="heavy", src_sr=24_000)
    assert light.tobytes() != heavy.tobytes()
    default, _ = mcv.render_line(line, audio, words, src_sr=24_000)
    assert default.tobytes() == light.tobytes()  # render_line's own default stays the old chain
