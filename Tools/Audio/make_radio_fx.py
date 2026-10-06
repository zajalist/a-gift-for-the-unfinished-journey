#!/usr/bin/env python3
"""The carrier's radio receiver: static beds, tuning, power, dropouts, lightning, relay and dead channel.

The carrier has a small receiver tuned to the Low Voice (the valley community station). It is mostly on,
can be toggled, and its reception follows terrain and the dust storm. A second frequency (the High Voice
relay: static with faint technical pilot/carrier tones and data chirps) and a dead channel sit on the dial.

Writes to <project>/Saved/GameAudio/Radio/ (48 kHz 16-bit; beds stereo, one-shots mono):

    AMB_Radio_Static_Soft_Loop        soft AM static                              60 s, -26 LUFS
    AMB_Radio_Static_Heavy_Loop       heavy storm static                          60 s, -26 LUFS
    AMB_Radio_Static_Crackle_Loop     crackly static with pops                    60 s, -26 LUFS
    AMB_Radio_BetweenStations_Loop    interstation hiss                           60 s, -26 LUFS
    AMB_Radio_WeakSignal_Loop         fading/flutter bed under speech at low SNR  60 s, -26 LUFS
    AMB_Radio_StudioRoom_Loop         quiet studio room tone + faint mains hum    60 s, -26 LUFS
    AMB_Radio_Relay_Loop              relay: static + steady pilot + data chirps  60 s, -26 LUFS
    AMB_Radio_DeadChannel_Loop        static + rare faint unintelligible murmurs  60 s, -26 LUFS
    SFX_Radio_Tune_Sweep_01..05       dial sweeps (heterodyne whistles/squeals)   peak -6 dBFS
    SFX_Radio_Tune_BandScan_01        a short band scan past several carriers     peak -6 dBFS
    SFX_Radio_Tune_Click_01..04       fine-tune detent clicks (recorded)          peak -6 dBFS
    SFX_Radio_Knob_On_01..03 / Off    mechanical power knob (recorded)            peak -6 dBFS
    SFX_Radio_Power_On_Bloom          static blooming up as the set warms        peak -6 dBFS
    SFX_Radio_Power_Off_Collapse      static burst collapsing to silence          peak -6 dBFS
    SFX_Radio_Dropout_01..06          crackle cut x2, silence gate x2, swell x2   peak -6 dBFS
    SFX_Radio_Lightning_01..04        sferic static bursts synced to lightning    peak -6 dBFS
    _demo_radio.wav                   30 s walkthrough (not imported)
    manifest.json                     type, loop, use, suggested volume, loudness, sources

No music and no melody. The only steady tones are the relay's technical pilot/carrier (a fixed sine and a
3 Hz beat against a second carrier) and the heterodyne whistles of tuning, which are continuous glides
(the beat between the dial and a carrier), never notes. The murmur on the dead channel is a real crowd
recording (kyles, CC0) band-passed, pitched, spectrally smeared and gated so that no word survives.

Synthesised layers are made circular (FFT filtering, wrapped event placement, periodic modulation), so
every bed loops seamlessly by construction; recorded bed layers are looped with an equal-power crossfade.

    python Tools/Audio/make_radio_fx.py            # fetch (cached), build, write, credit, check
    python Tools/Audio/make_radio_fx.py --check    # only check the files already written

Offline only: never touches Unreal. Import target: /Game/SaskartaGaea/Audio/Radio/.
"""
import hashlib
import json
import pathlib
import sys

import numpy as np
import soundfile
from scipy.signal import butter, resample_poly, sosfilt, sosfiltfilt, stft, istft

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import freesound_fetch as fs  # noqa: E402
from make_intro_fire import limiter_gain, lufs, meta  # noqa: E402

SR = fs.SR
OUT = fs.ROOT / "Saved" / "GameAudio" / "Radio"
UE = "/Game/SaskartaGaea/Audio/Radio"
STATION = fs.ROOT / "Saved" / "RadioRecordings" / "selected"
BED_S = 60.0
BED_N = int(BED_S * SR)
BED_LUFS = -26.0
SHOT_PEAK = -6.0

# role -> Freesound id; every one is CC0 (asserted when fetched)
SOURCES = {
    "sw_noise": 257879,     # zmobie, "Short Wave Radio Noise 2" (real interstation SW noise, U Twente SDR)
    "static_long": 636210,  # lartti, "static noise2.wav"
    "static_grit": 724703,  # 9voltplasma, "Just Regular Radio Static - Industrial SFX"
    "static_harsh": 724701, # 9voltplasma, "Schizoid Radio Static - Industrial SFX"
    "studio": 329550,       # LudwigMueller, "AMBLM tv studio room tone ambience noise lights off xy.wav"
    "crowd": 453905,        # kyles, "crowd int large hall carpeted murmur1 Montreal, Canada.flac"
    "power_switch": 513773, # lartti, "rotary light power switch, on and off.wav"
    "knob_a": 477612,       # Joao_Janz, "Digital Radio Rack Unit Knob Turn Snap 1_1"
    "knob_b": 477611,       # Joao_Janz, "Digital Radio Rack Unit Knob Turn Snap 1_2"
    "button": 686544,       # Troube, "wooden button"
}
_audio = {}
_used = {}   # asset -> [(role, note)]


def src(role, asset=None, note=""):
    if role not in _audio:
        h = meta(SOURCES[role])
        assert "publicdomain/zero" in h["license"], f"{h['id']} is not CC0: {h['license']}"
        _audio[role] = (h, fs.fetch(h))
    if asset:
        _used.setdefault(asset, []).append((role, note))
    return _audio[role][1]


# ---------------------------------------------------------------- helpers
def db(v):
    return 10 ** (v / 20)


def mono(x):
    return x.mean(axis=1) if x.ndim == 2 else x


def rms(x):
    return float(np.sqrt(np.mean(np.square(x))) + 1e-12)


def filt(x, kind, freq, order=4, zero_phase=True):
    sos = butter(order, freq, btype=kind, fs=SR, output="sos")
    return (sosfiltfilt(sos, x, axis=0) if zero_phase else sosfilt(sos, x, axis=0)).astype(np.float32)


def cfilt(x, lo=None, hi=None, slope=4):
    """Circular (FFT) band filter with Butterworth-like magnitude; keeps a loop seamless."""
    n = len(x)
    f = np.fft.rfftfreq(n, 1 / SR)
    g = np.ones_like(f)
    if lo:
        g *= 1 / np.sqrt(1 + (lo / np.maximum(f, 1e-3)) ** (2 * slope))
    if hi:
        g *= 1 / np.sqrt(1 + (f / hi) ** (2 * slope))
    X = np.fft.rfft(x, axis=0)
    return np.fft.irfft(X * (g[:, None] if x.ndim == 2 else g), n=n, axis=0).astype(np.float32)


def pink(n, rng):
    """Circular pink noise."""
    X = np.fft.rfft(rng.standard_normal(n))
    f = np.fft.rfftfreq(n, 1 / SR)
    X[1:] /= np.sqrt(f[1:] / 100.0)
    X[0] = 0
    y = np.fft.irfft(X, n=n)
    return (y / rms(y)).astype(np.float32)


def white(n, rng):
    return rng.standard_normal(n).astype(np.float32)


def pcurve(n, rng, rate_hz, depth_db, periodic=True):
    """Smooth random gain curve (+-depth_db, bandwidth ~rate_hz). Periodic over n when periodic=True."""
    X = np.fft.rfft(rng.standard_normal(n))
    f = np.fft.rfftfreq(n, 1 / SR)
    X *= np.exp(-(f / rate_hz) ** 2)
    X[0] = 0
    y = np.fft.irfft(X, n=n)
    y /= np.abs(y).max() + 1e-12
    return db(depth_db * y).astype(np.float32)


def wrap_add(dst, clip, at):
    """Add clip at sample `at`, wrapping around the end (for circular beds)."""
    n = len(dst)
    at %= n
    k = min(len(clip), n - at)
    dst[at:at + k] += clip[:k]
    if k < len(clip):
        dst[:len(clip) - k] += clip[k:]


def crackle(rng, dur_s=0.004, bright=4000.0):
    """One sferic tick/pop: a decaying noise impulse, band-limited."""
    n = max(16, int(dur_s * SR))
    env = np.exp(-np.arange(n) / (n / 5))
    c = rng.standard_normal(n) * env
    c[0] += rng.choice([-1, 1]) * 3
    b, a = butter(2, [200, min(bright, 11000)], btype="band", fs=SR)
    from scipy.signal import lfilter
    c = lfilter(b, a, c)
    return (c / (np.abs(c).max() + 1e-12)).astype(np.float32)


def crackle_layer(n, rng, rate_hz, lvl_sigma_db=6.0, dur=(0.001, 0.008), bright=(2500, 7000), pops=0.0):
    out = np.zeros(n, np.float32)
    k = rng.poisson(rate_hz * n / SR)
    for t in rng.integers(0, n, k):
        g = db(rng.normal(0, lvl_sigma_db))
        wrap_add(out, crackle(rng, rng.uniform(*dur), rng.uniform(*bright)) * g, int(t))
    if pops:
        for t in rng.integers(0, n, rng.poisson(pops * n / SR)):
            p = crackle(rng, rng.uniform(0.012, 0.035), rng.uniform(900, 2500))
            wrap_add(out, p * db(rng.uniform(6, 12)), int(t))
    return out


def recorded_loop(role, asset, n, start_s=0.0, xfade_s=2.0, note=""):
    """Mono, RMS-1 loop of exactly n samples cut from a recording, crossfaded (tiled if short)."""
    x = mono(src(role, asset, note))[int(start_s * SR):]
    x = x - x.mean()
    need = n + int(xfade_s * SR)
    if len(x) < need:
        # tile with crossfades until long enough
        seg = fs.make_loop(x, min(xfade_s, len(x) / SR / 4))
        x = np.tile(seg, int(np.ceil(need / len(seg))) + 1)
    y = fs.make_loop(x[:need], xfade_s)[:n]
    return (y / rms(y)).astype(np.float32)


def to_stereo(core, rng, width=0.25, side=None):
    """Mostly-mono stereo: a radio speaker is a point source; a little decorrelated width."""
    if side is None:
        side = cfilt(white(len(core), rng), 200, 6000)
        side *= rms(core) / rms(side)
    return np.stack([core + width * side, core - width * side], axis=1).astype(np.float32)


def to_lufs(x, target):
    g = db(target - lufs(x))
    return (x * g).astype(np.float32)


def peak_to(x, peak_db=SHOT_PEAK):
    return fs.normalize(x, peak_db).astype(np.float32)


def edge_fade(x, a=0.002, b=0.01):
    return fs.fade(x, a, b).astype(np.float32)


def env_ad(n, attack_s, decay_s, curve=1.0):
    t = np.arange(n) / SR
    a = np.clip(t / max(attack_s, 1e-4), 0, 1)
    d = np.exp(-np.maximum(t - attack_s, 0) / max(decay_s, 1e-4)) ** curve
    return (a * d).astype(np.float32)


def smooth_step(t, t0, t1):
    u = np.clip((t - t0) / (t1 - t0), 0.0, 1.0)
    return 0.5 - 0.5 * np.cos(np.pi * u)


def am_static(n, rng, lo=180, hi=4200):
    """Core AM static: pink + white noise through a receiver passband."""
    return cfilt(0.7 * pink(n, rng) + 0.5 * white(n, rng), lo, hi)


def phase_blur(x, nper=4096):
    """Randomise STFT phase: keeps the spectral envelope of speech/crowd, destroys any word."""
    rng = np.random.default_rng(99)
    f, t, Z = stft(x, SR, nperseg=nper, noverlap=nper * 3 // 4)
    Z = np.abs(Z) * np.exp(1j * rng.uniform(0, 2 * np.pi, Z.shape))
    return istft(Z, SR, nperseg=nper, noverlap=nper * 3 // 4)[1][: len(x)].astype(np.float32)


# ---------------------------------------------------------------- beds
def bed_soft(rng):
    a = "AMB_Radio_Static_Soft_Loop"
    n = BED_N
    core = am_static(n, rng, 200, 3400) * pcurve(n, rng, 0.25, 2.0)
    rec = cfilt(recorded_loop("sw_noise", a, n, 0.0, 1.5, "whole file looped (1.5 s crossfades), 200 Hz-3.6 kHz, -6 dB under synth"), 200, 3600)
    cr = crackle_layer(n, rng, 1.2, dur=(0.001, 0.004), bright=(2000, 3500))
    x = core + db(-6) * rec + db(-14) * cr
    return to_stereo(x, rng, 0.18)


def bed_heavy(rng):
    a = "AMB_Radio_Static_Heavy_Loop"
    n = BED_N
    core = am_static(n, rng, 120, 5500) * pcurve(n, rng, 0.8, 4.0)
    rec = cfilt(recorded_loop("static_long", a, n, 3.0, 2.0, "3 s on, looped (2 s crossfade), 120 Hz-6 kHz"), 120, 6000)
    grit = cfilt(recorded_loop("static_grit", a, n, 0.5, 1.0, "tiled with 1 s crossfades, 300 Hz-5 kHz, -8 dB"), 300, 5000)
    # storm buzz: dust charge on the antenna, low rasp modulated at irregular rates
    rasp = cfilt(white(n, rng), 90, 900) * pcurve(n, rng, 3.0, 9.0)
    cr = crackle_layer(n, rng, 9.0, 7.0, dur=(0.001, 0.006), bright=(2500, 6000), pops=0.3)
    x = core + db(-3) * rec + db(-8) * grit + db(-12) * rasp + db(-9) * cr
    return to_stereo(x, rng, 0.25)


def bed_crackle(rng):
    a = "AMB_Radio_Static_Crackle_Loop"
    n = BED_N
    core = am_static(n, rng, 200, 3800) * pcurve(n, rng, 0.4, 2.5)
    rec = cfilt(recorded_loop("sw_noise", a, n, 4.0, 1.5, "from 4 s, looped, 200 Hz-4 kHz, -8 dB"), 200, 4000)
    cr = crackle_layer(n, rng, 22.0, 6.0, dur=(0.0008, 0.005), bright=(2500, 7000), pops=0.9)
    # bursty clusters of crackle (discharge trains)
    burst = np.zeros(n, np.float32)
    for t in rng.integers(0, n, 14):
        m = int(rng.uniform(0.15, 0.6) * SR)
        cl = crackle_layer(m, rng, rng.uniform(60, 160), 5.0) * np.hanning(m).astype(np.float32)
        wrap_add(burst, cl, int(t))
    x = db(-4) * core + db(-10) * rec + db(0) * cr + db(-3) * burst
    return to_stereo(x, rng, 0.2)


def bed_between(rng):
    a = "AMB_Radio_BetweenStations_Loop"
    n = BED_N
    hiss = cfilt(white(n, rng), 300, 7500) * pcurve(n, rng, 0.3, 1.5)
    rec = cfilt(recorded_loop("sw_noise", a, n, 8.0, 1.5, "from 8 s, looped, 300 Hz-7.5 kHz, -5 dB"), 300, 7500)
    # adjacent-channel splatter: a faint unintelligible garble band 1-2.5 kHz that comes and goes
    garble = cfilt(white(n, rng), 900, 2400) * pcurve(n, rng, 6.0, 12.0) * pcurve(n, rng, 0.12, 10.0)
    x = hiss + db(-5) * rec + db(-16) * garble
    return to_stereo(x, rng, 0.3)


def bed_weak(rng):
    a = "AMB_Radio_WeakSignal_Loop"
    n = BED_N
    # slow selective fading (skywave) plus fast multipath flutter
    fade_slow = pcurve(n, rng, 0.35, 9.0)
    flutter = pcurve(n, rng, 9.0, 3.0)
    core = am_static(n, rng, 250, 3200)
    # moving passband: split into bands with independent fades (selective fading)
    bands = [(250, 600), (600, 1200), (1200, 2200), (2200, 3200)]
    x = np.zeros(n, np.float32)
    for lo, hi in bands:
        x += cfilt(core, lo, hi) * pcurve(n, rng, 0.5, 8.0)
    rec = cfilt(recorded_loop("sw_noise", a, n, 2.0, 1.5, "from 2 s, looped, 250 Hz-3.2 kHz, -6 dB"), 250, 3200)
    cr = crackle_layer(n, rng, 3.0, dur=(0.001, 0.004), bright=(2000, 3200))
    x = (x + db(-6) * rec) * fade_slow * flutter + db(-12) * cr
    return to_stereo(x, rng, 0.15)


def bed_studio(rng):
    a = "AMB_Radio_StudioRoom_Loop"
    n = BED_N
    room = cfilt(recorded_loop("studio", a, n, 5.0, 2.0, "from 5 s, looped (2 s crossfade), heard through the set: 90 Hz-5.5 kHz"), 90, 5500)
    room /= rms(room)
    t = np.arange(n) / SR
    # mains hum: 50 Hz family (integer cycles in 60 s, so the loop is seamless), mostly 100/150 Hz
    hum = (0.25 * np.sin(2 * np.pi * 50 * t) + 1.0 * np.sin(2 * np.pi * 100 * t + 0.3)
           + 0.55 * np.sin(2 * np.pi * 150 * t + 1.1) + 0.2 * np.sin(2 * np.pi * 250 * t + 2.0))
    hum = (hum * pcurve(n, rng, 0.2, 1.0)).astype(np.float32)
    hum /= rms(hum)
    hiss = cfilt(white(n, rng), 2000, 9000)
    x = room + db(-17) * hum + db(-24) * hiss
    return to_stereo(x, rng, 0.12)


def pilot_tone(n, f, phase=0.0):
    """Steady sine, frequency snapped to an integer number of cycles over the loop (seamless)."""
    f = round(f * n / SR) * SR / n
    return np.sin(2 * np.pi * f * np.arange(n) / SR + phase).astype(np.float32)


def fsk_burst(rng, dur_s, baud=300, f0=1200, f1=2200):
    """Random-bit AFSK data burst (phase-continuous). A buzzy data warble, not a melody."""
    nb = int(dur_s * baud)
    bits = rng.integers(0, 2, nb)
    spb = SR / baud
    freq = np.repeat(np.where(bits, f1, f0), int(np.ceil(spb)))[: int(nb * spb)].astype(np.float64)
    ph = 2 * np.pi * np.cumsum(freq) / SR
    y = np.sin(ph) * np.hanning(len(ph)) ** 0.25
    return y.astype(np.float32)


def chirp(rng, dur_s, f_a, f_b):
    t = np.arange(int(dur_s * SR)) / SR
    k = (f_b - f_a) / dur_s
    y = np.sin(2 * np.pi * (f_a * t + 0.5 * k * t * t)) * np.hanning(len(t))
    return y.astype(np.float32)


def bed_relay(rng):
    a = "AMB_Radio_Relay_Loop"
    n = BED_N
    static = am_static(n, rng, 200, 4200) * pcurve(n, rng, 0.5, 3.0)
    rec = cfilt(recorded_loop("sw_noise", a, n, 11.0, 1.5, "from 11 s, looped, -6 dB under synth static"), 200, 4200)
    cr = crackle_layer(n, rng, 2.0, dur=(0.001, 0.004), bright=(2000, 4000))
    # pilot: a steady 1.44 kHz carrier and a second carrier 3 Hz away (slow heterodyne beat), plus a
    # faint 2nd harmonic. Unchanging for the whole loop: a technical tone, not a note sequence.
    pilot = pilot_tone(n, 1440.0) + 0.5 * pilot_tone(n, 1443.0, 1.0) + 0.08 * pilot_tone(n, 2880.0)
    pilot *= pcurve(n, rng, 0.2, 2.5)   # propagation drift
    pilot /= rms(pilot)
    data = np.zeros(n, np.float32)
    times = np.sort(rng.uniform(0, BED_S, 7))
    for i, ts in enumerate(times):
        if i % 3 == 2:
            c = chirp(rng, rng.uniform(0.08, 0.14), 700, 3000) * 0.8
        else:
            c = fsk_burst(rng, rng.uniform(0.25, 0.7))
        wrap_add(data, c * db(rng.uniform(-3, 0)), int(ts * SR))
    data = cfilt(data, 300, 3400)
    x = static + db(-6) * rec + db(-13) * cr + db(-17) * pilot + db(-12) * data / (np.abs(data).max() + 1e-9) * 3
    return to_stereo(x, rng, 0.2)


def murmur_fragments(rng, n, count):
    """Rare, faint, unintelligible 'voices' from a crowd recording, heavily processed."""
    a = "AMB_Radio_DeadChannel_Loop"
    x = mono(src("crowd", a, "crowd murmur: 4 fragments 1.6-3 s, varispeed 0.83, 450 Hz-2.2 kHz, STFT phase-randomised, 5 Hz tremolo; -15 dB under static"))
    out = np.zeros(n, np.float32)
    starts = rng.uniform(10, len(x) / SR - 10, count)
    spots = (np.arange(count) + rng.uniform(0.2, 0.8, count)) * (BED_S / count)
    for s0, at in zip(starts, spots):
        d = rng.uniform(1.6, 3.0)
        seg = x[int(s0 * SR): int((s0 + d / 0.83) * SR)]
        seg = resample_poly(seg, 100, 83).astype(np.float32)          # slower, lower (varispeed 0.83)
        seg = filt(seg, "band", [450, 2200], 3)
        seg = phase_blur(seg, 2048)
        seg = filt(seg, "band", [450, 2200], 2)
        m = len(seg)
        trem = 0.6 + 0.4 * np.sin(2 * np.pi * rng.uniform(3.5, 6) * np.arange(m) / SR)
        w = np.hanning(m) ** 1.5
        seg = seg * trem * w
        wrap_add(out, (seg / rms(seg[m // 4: 3 * m // 4])).astype(np.float32), int(at * SR))
    return out


def bed_dead(rng):
    a = "AMB_Radio_DeadChannel_Loop"
    n = BED_N
    static = am_static(n, rng, 150, 5000) * pcurve(n, rng, 0.3, 1.5)
    rec = cfilt(recorded_loop("static_long", a, n, 20.0, 2.0, "from 20 s, looped (2 s crossfade), -6 dB"), 150, 5000)
    cr = crackle_layer(n, rng, 1.5, dur=(0.001, 0.004), bright=(2000, 4000))
    mur = murmur_fragments(rng, n, 4)
    x = static + db(-6) * rec + db(-14) * cr + db(-15) * mur
    return to_stereo(x, rng, 0.22)


# ---------------------------------------------------------------- one-shots
def shot_noise(n, rng, lo=180, hi=4500):
    return filt(0.7 * white(n, rng) + 0.7 * cfilt(pink(n, rng), None, 8000), "band", [lo, hi], 3)


def heterodyne(rng, dur_s, dial, carriers, width_hz=4500.0, max_pitch=5000.0):
    """Beat whistle of a sweeping local oscillator against fixed carriers.

    dial: array of receiver frequency (kHz, arbitrary units) per sample. Each carrier c whistles at
    |dial - c| scaled to Hz while within width; loudness rises as the beat approaches zero. The pitch is
    a continuous glide by construction (the physics of tuning), never a sequence of notes."""
    n = len(dial)
    y = np.zeros(n)
    width_hz = min(width_hz, max_pitch)   # never hold a capped pitch: a whistle only glides
    for c, lvl in carriers:
        beat = (dial - c) * 1000.0                 # Hz
        f = np.abs(beat)
        on = f < width_hz
        amp = np.clip(1 - f / width_hz, 0.0, 1.0) ** 1.5 * lvl
        ph = 2 * np.pi * np.cumsum(f) / SR
        tone = np.sin(ph) + 0.25 * np.sin(2 * ph)   # a little receiver distortion
        # near zero beat the carrier 'captures' the set: noise ducks, a low thump/flutter
        y += tone * amp
    return y.astype(np.float32)


def dial_curve(n, rng, span_khz, shape="ease"):
    t = np.linspace(0, 1, n)
    if shape == "ease":
        u = 0.5 - 0.5 * np.cos(np.pi * t)
    elif shape == "fast_slow":
        u = 1 - (1 - t) ** 2.2
    else:
        u = t
    jitter = np.cumsum(rng.standard_normal(n)) / np.sqrt(n) * 0.02   # the hand isn't steady
    return (u + jitter) * span_khz


def tune_sweep(rng, dur_s, span_khz, n_car, shape, squeal=False):
    n = int(dur_s * SR)
    dial = dial_curve(n, rng, span_khz, shape)
    lo, hi = min(dial.min(), dial.max()), max(dial.min(), dial.max())
    carriers = [(rng.uniform(lo + 0.1 * (hi - lo), hi - 0.1 * (hi - lo)), rng.uniform(0.5, 1.0)) for _ in range(n_car)]
    wh = heterodyne(rng, dur_s, dial, carriers, 6500 if squeal else 4000, 6500 if squeal else 4000)
    # capture: static ducks near each carrier
    cap = np.zeros(n)
    for c, lvl in carriers:
        cap = np.maximum(cap, np.exp(-((dial - c) * 1000 / 900) ** 2) * lvl)
    noise = shot_noise(n, rng) * (1 - 0.6 * cap) * pcurve(n, rng, 12.0, 4.0, periodic=False)
    # band-sweep: the IF noise colour shifts with the dial
    x = noise + db(0 if not squeal else 2) * wh
    thump = filt(rng.standard_normal(n), "low", 300, 2) * cap * 0.8
    x = x + thump
    x *= smooth_step(np.arange(n) / SR, 0, 0.04) * smooth_step(np.arange(n) / SR, dur_s, dur_s - 0.12)
    return x.astype(np.float32)


def band_scan(rng, dur_s=2.6):
    """A fast scan across the band: several carriers blip past, each with a short garble burst."""
    n = int(dur_s * SR)
    dial = dial_curve(n, rng, 60.0, "lin")
    cars = [(c, rng.uniform(0.5, 1.0)) for c in np.linspace(4, 56, 9) + rng.uniform(-2, 2, 9)]
    wh = heterodyne(rng, dur_s, dial, cars, 3500, 4000)
    noise = shot_noise(n, rng)
    garble = np.zeros(n, np.float32)
    for c, lvl in cars:
        i = int(np.argmin(np.abs(dial - c)))
        m = int(0.07 * SR)
        g = filt(white(m, rng), "band", [500, 2500], 2) * np.hanning(m) * pcurve(m, rng, 30, 10, False)
        garble[max(0, i - m // 2): max(0, i - m // 2) + m] += g[: len(garble[max(0, i - m // 2): max(0, i - m // 2) + m])] * lvl * 2.5
    x = noise + db(-6) * wh + db(-4) * garble
    x *= smooth_step(np.arange(n) / SR, 0, 0.03) * smooth_step(np.arange(n) / SR, dur_s, dur_s - 0.1)
    return x.astype(np.float32)


def find_onsets(x, thresh_rel=0.25, min_gap_s=0.08):
    env = np.abs(x)
    hop = 96
    fr = env[: len(env) // hop * hop].reshape(-1, hop).max(1)
    on, last = [], -1e9
    th = fr.max() * thresh_rel
    for i in range(1, len(fr)):
        if fr[i] > th and fr[i - 1] <= th and (i - last) * hop / SR > min_gap_s:
            on.append(i * hop)
            last = i
    return on


def cut(x, at, pre_s=0.004, dur_s=0.18):
    a = max(0, at - int(pre_s * SR))
    return x[a: a + int(dur_s * SR)].copy()


def knobs(rng):
    """Power knob on/off (3 each) and fine-tune clicks (4), all cut from recorded switches and knobs."""
    out = {}
    ps = filt(mono(src("power_switch")), "high", 80, 2)
    ka = filt(mono(src("knob_a")), "high", 120, 2)
    kb = filt(mono(src("knob_b")), "high", 120, 2)
    bt = filt(mono(src("button")), "high", 100, 2)
    on_ps, on_ka, on_kb, on_bt = find_onsets(ps), find_onsets(ka), find_onsets(kb), find_onsets(bt)
    plan = {
        # on: the switch closing, a firmer detent; a touch of the set's pop as it powers
        "SFX_Radio_Knob_On_01": ("power_switch", ps, on_ps, 0, 1.00, 0.0),
        "SFX_Radio_Knob_On_02": ("knob_a", ka, on_ka, 0, 0.94, 0.0),
        "SFX_Radio_Knob_On_03": ("button", bt, on_bt, 0, 0.90, 0.0),
        "SFX_Radio_Knob_Off_01": ("power_switch", ps, on_ps, 1, 1.00, 0.0),
        "SFX_Radio_Knob_Off_02": ("knob_b", kb, on_kb, 0, 0.92, 0.0),
        "SFX_Radio_Knob_Off_03": ("button", bt, on_bt, 1, 0.86, 0.0),
    }
    for name, (role, x, ons, k, speed, _) in plan.items():
        at = ons[min(k, len(ons) - 1)]
        c = cut(x, at, 0.004, 0.22)
        if speed != 1.0:
            c = resample_poly(c, 100, int(round(100 * speed))).astype(np.float32)
        c = c * env_ad(len(c), 0.001, 0.07)
        _used.setdefault(name, []).append((role, f"onset {k} at {at / SR:.2f} s, 0.22 s cut, varispeed {speed}, high-pass"))
        if "_On_" in name:   # the speaker's power-up pop, very low, just after the click
            m = int(0.12 * SR)
            pop = filt(rng.standard_normal(m), "low", 180, 2) * env_ad(m, 0.004, 0.03)
            pad = np.zeros(len(c) + int(0.05 * SR), np.float32)
            pad[: len(c)] += c
            pad[int(0.03 * SR): int(0.03 * SR) + m][: len(pad) - int(0.03 * SR)] += (pop * 0.25 * np.abs(c).max() / (np.abs(pop).max() + 1e-9))[: len(pad) - int(0.03 * SR)]
            c = pad
        out[name] = edge_fade(c, 0.001, 0.02)
    # fine-tune detents: tiny clicks from the rack knobs + a whisper of static shift
    srcs = [("knob_a", ka, on_ka), ("knob_b", kb, on_kb), ("knob_a", ka, on_ka), ("knob_b", kb, on_kb)]
    for i, (role, x, ons) in enumerate(srcs, 1):
        at = ons[(i - 1) // 2 % len(ons)] if len(ons) > 1 else ons[0]
        c = cut(x, at, 0.002, 0.06) * env_ad(int(0.06 * SR), 0.0005, 0.012)
        c = resample_poly(c, 100, [112, 118, 106, 124][i - 1]).astype(np.float32)   # smaller, finer
        m = len(c)
        sh = shot_noise(m + int(0.1 * SR), rng) * env_ad(m + int(0.1 * SR), 0.005, 0.04)
        y = np.zeros(m + int(0.1 * SR), np.float32)
        y[:m] += c / (np.abs(c).max() + 1e-9)
        y += 0.12 * sh / (np.abs(sh).max() + 1e-9)
        name = f"SFX_Radio_Tune_Click_{i:02d}"
        _used.setdefault(name, []).append((role, f"detent at {at / SR:.2f} s, 60 ms, sped up x{[1.12, 1.18, 1.06, 1.24][i - 1]}; + synth static tick"))
        out[name] = edge_fade(y, 0.0005, 0.02)
    return out


def power_on(rng):
    dur = 2.4
    n = int(dur * SR)
    t = np.arange(n) / SR
    x = shot_noise(n, rng, 120, 6000)
    rec = mono(src("static_grit", "SFX_Radio_Power_On_Bloom", "1.0-3.4 s, under the synth bloom"))[int(1.0 * SR): int(1.0 * SR) + n]
    rec = filt(rec / rms(rec), "band", [150, 5000], 2)
    x = x + db(-6) * rec[:n]
    # warm-up: the passband opens from 300 Hz to full as the level blooms (valves/caps charging)
    lo = filt(x, "low", 400, 2)
    mid = filt(x, "low", 1500, 2)
    w = smooth_step(t, 0.05, 1.3)
    x = lo * (1 - w) + (mid * (1 - smooth_step(t, 0.6, 1.8)) + x * smooth_step(t, 0.6, 1.8)) * w
    lvl = smooth_step(t, 0.0, 1.1) ** 1.5 * (1 - 0.35 * smooth_step(t, 1.3, 2.2)) * (1 - smooth_step(t, dur - 0.15, dur))
    thump = filt(rng.standard_normal(n), "low", 90, 2) * env_ad(n, 0.01, 0.12) * 4
    x = x * lvl + thump + db(-10) * crackle_layer(n, rng, 10, 5) * lvl
    return x.astype(np.float32)


def power_off(rng):
    dur = 0.8
    n = int(dur * SR)
    t = np.arange(n) / SR
    x = shot_noise(n, rng, 100, 7000) + db(-5) * crackle_layer(n, rng, 60, 5)
    rec = mono(src("static_harsh", "SFX_Radio_Power_Off_Collapse", "2.0-2.8 s, burst layer"))[int(2.0 * SR): int(2.0 * SR) + n]
    x = x + db(-4) * filt(rec / rms(rec), "band", [150, 6000], 2)
    # collapse: pitch/band slides down (caps draining), level falls
    cut_lp = np.stack([filt(x, "low", f, 2) for f in (6000, 2500, 1000, 400, 150)], 1)
    pos = np.clip(t / 0.55, 0, 1) * 4
    i0 = np.floor(pos).astype(int).clip(0, 3)
    fr = pos - i0
    y = cut_lp[np.arange(n), i0] * (1 - fr) + cut_lp[np.arange(n), i0 + 1] * fr
    lvl = smooth_step(t, 0, 0.012) * (np.exp(-t / 0.28)) * (1 + 0.8 * np.exp(-t / 0.05))
    thump = filt(rng.standard_normal(n), "low", 70, 2) * env_ad(n, 0.004, 0.09)
    y = y * lvl
    y = np.tanh(2.0 * y / (np.abs(y).max() + 1e-9))
    thump *= 0.5 / (np.abs(thump).max() + 1e-9)
    return (y + thump * np.exp(-t / 0.2)).astype(np.float32)


def dropouts(rng):
    out = {}
    notes = {}
    # 01-02 crackle cut: a crackle burst that chokes the signal, then a clean cut
    for i, dur in ((1, 0.55), (2, 0.8)):
        n = int(dur * SR)
        t = np.arange(n) / SR
        cr = crackle_layer(n, rng, 180, 5, dur=(0.0008, 0.006), bright=(2500, 7000), pops=6)
        nz = shot_noise(n, rng) * 0.4
        cutp = dur * rng.uniform(0.55, 0.7)
        x = (cr + nz) * smooth_step(t, 0, 0.02) * (t < cutp) + (t >= cutp) * 0.0
        tail = np.zeros(n)
        k = int(cutp * SR)
        tail[k:k + 40] = rng.standard_normal(40) * np.exp(-np.arange(40) / 8) * 1.5   # the cut's click
        out[f"SFX_Radio_Dropout_{i:02d}"] = edge_fade((x + tail).astype(np.float32), 0.002, 0.005)
        notes[f"SFX_Radio_Dropout_{i:02d}"] = dict(kind="crackle_cut", gate_s=round(dur - cutp + 0.25, 2), gate_at_s=round(cutp, 2))
    # 03-04 silence gate: a tick, near-silence (the station audio must be gated for gate_s), a tick back
    for i, gate in ((3, 0.35), (4, 0.6)):
        n = int((gate + 0.12) * SR)
        x = np.zeros(n, np.float32)
        a = crackle(rng, 0.006, 5000)
        b = crackle(rng, 0.01, 3000) * 0.7
        x[:len(a)] += a
        k = int((gate + 0.02) * SR)
        x[k:k + len(b)] += b
        # the set's own floor inside the gate: a faint low hiss so it isn't digital black
        x[len(a):k] += shot_noise(k - len(a), rng, 300, 2500)[: k - len(a)] * 0.01
        x[k + len(b):] += shot_noise(n - k - len(b), rng)[: n - k - len(b)] * 0.25 * np.exp(-np.arange(n - k - len(b)) / (0.04 * SR))
        out[f"SFX_Radio_Dropout_{i:02d}"] = edge_fade(x, 0.0005, 0.01)
        notes[f"SFX_Radio_Dropout_{i:02d}"] = dict(kind="silence_gate", gate_s=gate, gate_at_s=0.005)
    # 05-06 static swell: static rises over the signal and falls back (station ducks under it)
    for i, dur in ((5, 1.6), (6, 2.4)):
        n = int(dur * SR)
        t = np.arange(n) / SR
        pk = dur * rng.uniform(0.4, 0.55)
        env = np.exp(-((t - pk) / (dur * 0.22)) ** 2)
        nz = shot_noise(n, rng, 150, 5000) * pcurve(n, rng, 8, 3, False)
        x = nz * env + db(-8) * crackle_layer(n, rng, 40, 5) * env
        x *= smooth_step(t, 0, 0.05) * smooth_step(t, dur, dur - 0.1)
        out[f"SFX_Radio_Dropout_{i:02d}"] = x.astype(np.float32)
        notes[f"SFX_Radio_Dropout_{i:02d}"] = dict(kind="static_swell", duck_peak_at_s=round(pk, 2), duck_width_s=round(dur * 0.5, 2))
    return out, notes


def lightning(rng):
    """Sferic bursts: a lightning flash is heard on AM as a loud crash. 2-5 return strokes 30-90 ms apart,
    each a broadband crack with a sizzling decay, riding on a swell of static."""
    out, notes = {}, {}
    for i, (dur, strokes) in enumerate(((1.4, 2), (2.0, 3), (1.8, 4), (2.6, 5)), 1):
        n = int(dur * SR)
        t = np.arange(n) / SR
        x = np.zeros(n, np.float32)
        at = 0.005
        times = []
        for s in range(strokes):
            m = int(rng.uniform(0.25, 0.6) * SR)
            crack = white(m, rng) * env_ad(m, 0.0005, rng.uniform(0.02, 0.06))
            sizzle = crackle_layer(m, rng, rng.uniform(150, 400), 5) * env_ad(m, 0.002, rng.uniform(0.12, 0.3))
            burst = filt(crack, "band", [120, 7000], 2) * 1.0 + 0.8 * sizzle
            g = 1.0 if s == 0 else db(rng.uniform(-9, -2))
            k = int(at * SR)
            x[k:k + m] += (burst * g)[: n - k]
            times.append(round(at, 3))
            at += rng.uniform(0.03, 0.09) if s < 2 else rng.uniform(0.12, 0.3)
            if at > dur * 0.6:
                break
        rec = mono(src("static_harsh", f"SFX_Radio_Lightning_{i:02d}", f"{1.0 + i:.1f} s on, swell layer"))
        r0 = int((1.0 + i) * SR)
        rec = rec[r0:r0 + n]
        rec = filt(rec / rms(rec), "band", [150, 5000], 2)
        swell = rec * env_ad(n, 0.01, dur * 0.35) * 0.18
        x = x + swell + shot_noise(n, rng) * env_ad(n, 0.005, dur * 0.3) * 0.15
        x = np.tanh(3.0 * x / (np.abs(x).max() + 1e-9)) / np.tanh(3.0)   # the set's front end overloads
        x *= smooth_step(t, dur, dur - 0.15)
        out[f"SFX_Radio_Lightning_{i:02d}"] = edge_fade(x, 0.0005, 0.02)
        notes[f"SFX_Radio_Lightning_{i:02d}"] = dict(strokes_at_s=times, peak_at_s=0.005)
    return out, notes


# ---------------------------------------------------------------- catalogue
BEDS = {
    "AMB_Radio_Static_Soft_Loop": (bed_soft, 11, 0.5, "Soft AM static. The base static layer for the Low Voice at good/moderate signal; always under the station."),
    "AMB_Radio_Static_Heavy_Loop": (bed_heavy, 12, 0.7, "Heavy static: storm charge, rasp and crackle. Crossfade in as signal falls below ~0.4 and with dust-storm intensity."),
    "AMB_Radio_Static_Crackle_Loop": (bed_crackle, 13, 0.5, "Crackly static with pops (atmospherics). Layer on top by storm intensity / nearby lightning activity."),
    "AMB_Radio_BetweenStations_Loop": (bed_between, 14, 0.6, "Interstation hiss while the dial sits off any station (during/after tuning, or off-frequency)."),
    "AMB_Radio_WeakSignal_Loop": (bed_weak, 15, 0.6, "Weak-signal fading bed: selective fading and flutter. Layer under the station speech at low signal (<0.5)."),
    "AMB_Radio_StudioRoom_Loop": (bed_studio, 16, 0.35, "Studio room tone with faint mains hum, heard through the set. Plays on the Low Voice in the gaps between segments."),
    "AMB_Radio_Relay_Loop": (bed_relay, 17, 0.55, "The High Voice relay frequency: static, a steady technical pilot tone (1.44 kHz, 3 Hz beat), sparse data chirps."),
    "AMB_Radio_DeadChannel_Loop": (bed_dead, 18, 0.55, "The dead channel: static with rare faint unintelligible murmurs (4 in 60 s)."),
}


def build_shots():
    shots, extra = {}, {}
    rng = np.random.default_rng(31)
    specs = [
        ("SFX_Radio_Tune_Sweep_01", 1.4, 8.0, 2, "ease", False, "Short dial nudge: two whistles glide through zero beat."),
        ("SFX_Radio_Tune_Sweep_02", 2.2, -12.0, 3, "fast_slow", False, "Dial turned down-band, settling: three whistles."),
        ("SFX_Radio_Tune_Sweep_03", 1.8, 10.0, 2, "ease", True, "Heterodyne squeal: a strong carrier squeals high then drops through zero."),
        ("SFX_Radio_Tune_Sweep_04", 3.0, 16.0, 4, "ease", False, "Longer sweep: four carriers, capture thumps near zero beat."),
        ("SFX_Radio_Tune_Sweep_05", 1.0, -6.0, 1, "fast_slow", True, "Quick flick with one squeal (tune away from a station)."),
    ]
    for name, dur, span, nc, shape, sq, use in specs:
        r = np.random.default_rng(4000 + int(name[-2:]))
        shots[name] = (tune_sweep(r, dur, span, nc, shape, sq), use, 0.6)
    shots["SFX_Radio_Tune_BandScan_01"] = (band_scan(np.random.default_rng(4100)), "A short band scan: carriers blip past with garbled splatter.", 0.55)
    for k, v in knobs(np.random.default_rng(4200)).items():
        use = ("Power knob turned ON (random of 3)." if "_On_" in k else "Power knob turned OFF (random of 3)." if "_Off_" in k
               else "Fine-tune detent click per dial step (random of 4, rate-limit ~12/s).")
        shots[k] = (v, use, 0.6 if "Knob" in k else 0.45)
    shots["SFX_Radio_Power_On_Bloom"] = (power_on(np.random.default_rng(4300)), "Right after Knob_On: static blooms as the set warms; start the beds under its tail at ~1.2 s.", 0.6)
    shots["SFX_Radio_Power_Off_Collapse"] = (power_off(np.random.default_rng(4400)), "With Knob_Off: static bursts and collapses; cut all radio beds and station at its start.", 0.6)
    d, dn = dropouts(np.random.default_rng(4500))
    for k, v in d.items():
        kind = dn[k]["kind"]
        use = {"crackle_cut": "Dropout: crackle then a cut; gate station + beds from gate_at_s for gate_s.",
               "silence_gate": "Dropout: brief silence. Gate station + beds to 0 for gate_s right after the tick.",
               "static_swell": "Dropout: static swells over the station; duck the station ~-15 dB around duck_peak_at_s."}[kind]
        shots[k] = (v, use, 0.55)
        extra[k] = dn[k]
    l, ln = lightning(np.random.default_rng(4600))
    for k, v in l.items():
        shots[k] = (v, "Lightning interference: play at the lightning FLASH (radio is speed-of-light; thunder comes later).", 0.7)
        extra[k] = ln[k]
    return shots, extra


def band_limit_voice(x):
    """Station take through a small AM receiver: 300 Hz-3.2 kHz, light saturation."""
    y = filt(x, "band", [300, 3200], 3)
    y = y / (np.abs(y).max() + 1e-9)
    return (np.tanh(1.6 * y) / np.tanh(1.6)).astype(np.float32)


def demo(beds, shots):
    """30 s: power on, station fades in, dropout, lightning, tune to relay and back, power off."""
    n = 30 * SR
    mix = np.zeros((n, 2), np.float32)
    t = np.arange(n) / SR

    def put(clip, at, gain_db=0.0):
        a = int(at * SR)
        c = clip if clip.ndim == 2 else np.stack([clip, clip], 1)
        c = c[: n - a]
        mix[a:a + len(c)] += c * db(gain_db)

    def bedseg(name, gain_curve):
        b = beds[name]
        reps = int(np.ceil(n / len(b)))
        return np.tile(b, (reps, 1))[:n] * gain_curve[:, None]

    # station programme: STN_ID_01 then STN_DEDIC_01, band-limited, -18 LUFS-ish
    sid, _ = soundfile.read(str(STATION / "STN_ID_01.wav"), dtype="float32")
    ded, _ = soundfile.read(str(STATION / "STN_DEDIC_01.wav"), dtype="float32")
    prog = np.concatenate([np.zeros(int(0.3 * SR), np.float32), band_limit_voice(sid), np.zeros(int(0.6 * SR), np.float32), band_limit_voice(ded)])
    prog = prog / rms(prog) * db(-22)
    station = np.zeros(n, np.float32)
    s0 = 2.4
    k = int(s0 * SR)
    L = min(len(prog), int((15.0 - s0) * SR))
    station[k:k + L] = prog[:L]
    # the programme resumes after tuning back (continuing where it was)
    k2, L2 = int(22.8 * SR), min(len(prog) - L, int((27.6 - 22.8) * SR))
    station[k2:k2 + L2] = prog[L:L + L2]

    # timeline (s)
    ON, BLOOM = 0.3, 0.4
    DROP, LIGHT = 8.2, 11.6
    TUNE_OUT, RELAY_IN, RELAY_OUT, TUNE_BACK = 15.0, 16.6, 20.6, 22.4
    OFF = 27.8
    sig = (smooth_step(t, 2.2, 5.5) * 0.9                          # station fades in (signal 0 -> 0.9)
           * (1 - smooth_step(t, TUNE_OUT, TUNE_OUT + 0.4)) + smooth_step(t, TUNE_BACK + 0.2, TUNE_BACK + 1.2) * 0.9 * (t < OFF))
    power = smooth_step(t, 1.2, 2.2) * (t < OFF)
    # dropout gate (Dropout_04: silence gate) at DROP
    gate = np.ones(n)
    g4 = shots["SFX_Radio_Dropout_04"]
    gate[int((DROP + 0.005) * SR): int((DROP + 0.005 + 0.6) * SR)] = 0.02
    gate = filt(gate.astype(np.float32), "low", 60, 1)
    # lightning: duck station for a moment
    duck = 1 - 0.8 * np.exp(-np.maximum(t - LIGHT, 0) / 0.5) * (t >= LIGHT)
    st_on = (t < TUNE_OUT + 0.4) | (t > TUNE_BACK)
    stat_soft = power * st_on * (1.0 - 0.55 * sig) * gate
    weak = power * st_on * (1 - sig) * np.clip(sig * 3, 0, 1) * gate
    between = power * (smooth_step(t, TUNE_OUT, TUNE_OUT + 0.3) * (1 - smooth_step(t, RELAY_IN - 0.3, RELAY_IN))
                       + smooth_step(t, RELAY_OUT, RELAY_OUT + 0.3) * (1 - smooth_step(t, TUNE_BACK, TUNE_BACK + 0.6)))
    relay = power * smooth_step(t, RELAY_IN - 0.4, RELAY_IN + 0.3) * (1 - smooth_step(t, RELAY_OUT - 0.2, RELAY_OUT + 0.3))
    mix += bedseg("AMB_Radio_Static_Soft_Loop", stat_soft.astype(np.float32) * db(2))
    mix += bedseg("AMB_Radio_WeakSignal_Loop", weak.astype(np.float32) * db(0))
    mix += bedseg("AMB_Radio_BetweenStations_Loop", between.astype(np.float32) * db(0))
    mix += bedseg("AMB_Radio_Relay_Loop", relay.astype(np.float32) * db(2))
    st = station * sig * gate * duck
    mix += np.stack([st, st], 1)
    put(shots["SFX_Radio_Knob_On_01"], ON, -4)
    put(shots["SFX_Radio_Power_On_Bloom"], BLOOM, -8)
    put(g4, DROP, -10)
    put(shots["SFX_Radio_Lightning_03"], LIGHT, -4)
    put(shots["SFX_Radio_Tune_Sweep_02"], TUNE_OUT, -9)
    for i, tt in enumerate(np.arange(RELAY_IN - 0.5, RELAY_IN, 0.12)):
        put(shots[f"SFX_Radio_Tune_Click_{i % 4 + 1:02d}"], tt, -16)
    put(shots["SFX_Radio_Tune_Sweep_03"], RELAY_OUT, -9)
    for i, tt in enumerate(np.arange(TUNE_BACK - 0.2, TUNE_BACK + 0.4, 0.12)):
        put(shots[f"SFX_Radio_Tune_Click_{i % 4 + 1:02d}"], tt, -16)
    put(shots["SFX_Radio_Knob_Off_01"], OFF, -4)
    put(shots["SFX_Radio_Power_Off_Collapse"], OFF + 0.05, -7)
    tl = [(ON, "Knob_On_01"), (BLOOM, "Power_On_Bloom"), (2.2, "Low Voice fades in (STN_ID_01, STN_DEDIC_01, band-limited)"),
          (DROP, "Dropout_04 (silence gate 0.6 s)"), (LIGHT, "Lightning_03 (station ducked)"), (TUNE_OUT, "Tune_Sweep_02 -> between stations"),
          (RELAY_IN, "relay bed (Relay_Loop)"), (RELAY_OUT, "Tune_Sweep_03 back"), (TUNE_BACK, "Low Voice returns"),
          (OFF, "Knob_Off_01 + Power_Off_Collapse")]
    mix = fs.normalize(mix, -3.0) if np.abs(mix).max() > db(-3) else mix
    mix = to_lufs(mix, -20.0)
    if np.abs(mix).max() > db(-1):
        mix = fs.normalize(mix, -1.0)
    return fs.fade(mix, 0.005, 0.05).astype(np.float32), tl


# ---------------------------------------------------------------- check
def check(manifest):
    bad = []
    for e in manifest["sounds"]:
        x, sr = soundfile.read(str(OUT / e["file"]), dtype="float32")
        ch = 1 if x.ndim == 1 else x.shape[1]
        pk = 20 * np.log10(np.abs(x).max() + 1e-12)
        if sr != SR:
            bad.append(f"{e['id']}: sr {sr}")
        if e["loop"]:
            L = lufs(x)
            step = np.abs(x[0] - x[-1]).max()
            p999 = np.percentile(np.abs(np.diff(x, axis=0)).max(axis=1), 99.9)
            seam = abs(fs.rms_db(x[:2400]) - fs.rms_db(x[-2400:]))
            if ch != 2 or abs(L - BED_LUFS) > 0.5 or step > p999 * 1.5 or abs(len(x) / SR - BED_S) > 0.01 or pk > -3:
                bad.append(f"{e['id']}: ch {ch} lufs {L:.2f} wrap {step:.4f} vs p99.9 {p999:.4f} seam {seam:.1f} dB peak {pk:.1f}")
        else:
            if ch != 1 or abs(pk - SHOT_PEAK) > 0.1 or np.abs(x[[0, -1]]).max() > 16 / 32768:
                bad.append(f"{e['id']}: ch {ch} peak {pk:.2f} edges {np.abs(x[[0, -1]]).max():.5f}")
    return bad


def credit_all():
    for asset, uses in sorted(_used.items()):
        for j, (role, note) in enumerate(uses):
            h = _audio[role][0]
            key = asset if j == 0 else f"{asset}__{role}"
            fs.credit(key, h, notes=note)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    mpath = OUT / "manifest.json"
    if "--check" in sys.argv:
        bad = check(json.loads(mpath.read_text(encoding="utf-8")))
        print("\n".join(bad) or "check ok")
        sys.exit(1 if bad else 0)
    sounds, beds = [], {}
    for name, (fn, seed, vol, use) in BEDS.items():
        x = fn(np.random.default_rng(seed))
        x = x - x.mean(axis=0)
        x = to_lufs(x, BED_LUFS)
        for _ in range(3):   # crackle transients: a look-ahead limiter at -6 dBFS, then re-level
            if np.abs(x).max() <= db(-5.5):
                break
            x = to_lufs(x * limiter_gain(x, -6.0, 0.002, 0.05)[:, None], BED_LUFS)
        if np.abs(x).max() > db(-3):
            raise SystemExit(f"{name}: peak {20 * np.log10(np.abs(x).max()):.1f} dBFS at -26 LUFS; tame the crackle")
        beds[name] = x
        fs.write_wav(OUT / f"{name}.wav", x)
        sounds.append(dict(id=name, type="bed", loop=True, channels=2, suggested_use=use, suggested_volume=vol, seed=seed))
    shots, extra = build_shots()
    for name, (x, use, vol) in shots.items():
        x = peak_to(x - x.mean())
        x = edge_fade(x, 0.0005, 0.003)
        x = peak_to(x)
        shots[name] = x
        fs.write_wav(OUT / f"{name}.wav", x)
        e = dict(id=name, type="one-shot", loop=False, channels=1, suggested_use=use, suggested_volume=vol)
        if name in extra:
            e["timing"] = extra[name]
        sounds.append(e)
    d, tl = demo(beds, shots)
    fs.write_wav(OUT / "_demo_radio.wav", d)
    for e in sounds:
        p = OUT / f"{e['id']}.wav"
        x, _ = soundfile.read(str(p), dtype="float32")
        e["file"] = p.name
        e["ue_path"] = f"{UE}/{e['id']}.{e['id']}"
        e["duration_s"] = round(len(x) / SR, 3)
        e["lufs"] = round(float(lufs(x)), 2) if len(x) > 0.4 * SR else None
        e["peak_dbfs"] = round(float(20 * np.log10(np.abs(x).max() + 1e-12)), 2)
        e["sources"] = [f"freesound {SOURCES[r]} ({_audio[r][0]['username']}, CC0): {nt}" for r, nt in _used.get(e["id"], [])] or ["procedural (numpy)"]
        if e["type"] == "bed" and e["sources"] != ["procedural (numpy)"]:
            e["sources"].append("procedural static/crackle layers (numpy)")
        e["sha256"] = hashlib.sha256(p.read_bytes()).hexdigest()
    manifest = dict(ue_folder=UE, generator="Tools/Audio/make_radio_fx.py",
                    brief=".superpowers/sdd/2026-09-26-saskarta-world-sprint/task-RADIOFX-brief.md",
                    sample_rate=SR, bit_depth=16, bed_target_lufs=BED_LUFS, oneshot_peak_dbfs=SHOT_PEAK,
                    demo=dict(file="_demo_radio.wav", **{"import": False}, timeline=[dict(at_s=round(a, 2), what=w) for a, w in tl]),
                    sounds=sounds)
    mpath.write_text(json.dumps(manifest, indent=2), encoding="utf-8", newline="\n")
    credit_all()
    bad = check(manifest)
    for e in sounds:
        print(f"{e['id']:34s} {e['duration_s']:6.2f}s ch{e['channels']} lufs {e['lufs']} peak {e['peak_dbfs']}")
    print("\n".join(bad) or "check ok")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
