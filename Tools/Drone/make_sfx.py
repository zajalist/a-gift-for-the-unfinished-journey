"""Deterministic, mono 48 kHz cues for the auxiliary-sensor and drone sequence.

    python Tools/Drone/make_sfx.py

The return cue is dry: the runtime owns its spatial position and the round-trip
delay from each trace hit. These are effects, not music or a baked echo bed.
The ping is a soft low 'tok' with an airy tail (one every 3 s), the return a filtered
click, the wind loop a faint bed between pings. Also writes a stereo listening check
to Saved/UI/AuxSensors/previews/aux_echo_preview.wav.
"""
from pathlib import Path
import wave

import numpy as np

SR = 48000
OUT = Path(__file__).resolve().parents[2] / "SourceArt/Audio/Drone"


def _tone(t, frequency):
    return np.sin(2 * np.pi * frequency * t)


def _soft(x):
    return np.tanh(1.5 * x) / np.tanh(1.5)


def _band(x, lo, hi, order=2):
    """Zero-phase FFT band-pass with soft (Butterworth-like) skirts."""
    hz = np.fft.rfftfreq(len(x), 1 / SR)
    gain = np.ones_like(hz)
    if lo > 0:
        gain /= np.sqrt(1 + (lo / np.maximum(hz, 1e-3)) ** (2 * order))
    if hi > 0:
        gain /= np.sqrt(1 + (hz / hi) ** (2 * order))
    return np.fft.irfft(np.fft.rfft(x) * gain, n=len(x))


def ping():
    """A soft, low sonar 'tok' with a long airy tail. Not a beep: nothing sustains a pitch."""
    n = int(2.6 * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(2913)
    f = 190 + 130 * np.exp(-t / .012)
    phase = 2 * np.pi * np.cumsum(f) / SR
    body = (np.sin(phase) + .22 * np.sin(2.43 * phase) * np.exp(-t / .012)) * np.exp(-t / .05)
    click = _band(rng.normal(size=n), 1500, 4200) * np.exp(-t / .0025) * .5
    air = _band(rng.normal(size=n), 350, 2600) * (1 - np.exp(-t / .04)) * np.exp(-t / .75) * .09
    x = (body + click + air) * np.minimum(1, t / .0015)
    return x * np.minimum(1, (2.6 - t) / .25)


def echo_return():
    """A delayed, filtered click; runtime places it at the edge, so pan and delay are real."""
    n = int(.32 * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(2914)
    click = _band(rng.normal(size=n) * np.exp(-t / .0015), 900, 3200)
    knock = .35 * np.sin(2 * np.pi * 260 * t) * np.exp(-t / .016)
    air = _band(rng.normal(size=n), 500, 2400) * np.exp(-t / .07) * .05
    x = (click * 3 + knock + air) * np.minimum(1, t / .0008)
    return x * np.minimum(1, (.32 - t) / .05)


def wind_loop():
    """Eight seconds of faint low wind; the spectrum is periodic, so the loop has no seam."""
    n = 8 * SR
    t = np.arange(n) / SR
    rng = np.random.default_rng(2915)
    hz = np.fft.rfftfreq(n, 1 / SR)
    band = (hz >= 40) & (hz <= 2500)
    spec = np.zeros(hz.size, dtype=np.complex128)
    spec[band] = (hz[band] / 120) ** -.9 * np.exp(2j * np.pi * rng.random(band.sum()))
    spec[band] /= np.sqrt(1 + (hz[band] / 900) ** 4)
    x = np.fft.irfft(spec, n=n)
    x /= max(np.max(np.abs(x)), 1e-9)
    gust = 1 + .35 * np.sin(2 * np.pi * t / 8) + .18 * np.sin(2 * np.pi * 3 * t / 8 + 1.1)
    return x * gust


def preview_sequence(seconds=9.5, left=(300., 200., 80.), right=(300., 400., 520.)):
    """Stereo 48 kHz listening check: three pings, panned edge echoes, the wind bed.

    Mirrors the runtime: echo delay 2d/343 s, gain EchoVolume(d) = clamp(250/(d+150), .2, 1).
    """
    n = int(seconds * SR)
    out = np.zeros((n, 2))
    wind = wind_loop()
    out += (np.resize(wind, n) * .045)[:, None]
    tok, click = ping() * .5, echo_return() * .5
    for k, start in enumerate((.5, 3.5, 6.5)):
        i = int(start * SR)
        seg = tok[:n - i]
        out[i:i + len(seg)] += seg[:, None] * .7
        for d, pan in ((left[k], -.85), (right[k], .85)):
            j = i + int(2 * d / 34300 * SR)
            gain = min(max(250 / (d + 150), .2), 1.)
            th = (pan + 1) * np.pi / 4
            seg = click[:n - j] * gain
            out[j:j + len(seg), 0] += seg * np.cos(th)
            out[j:j + len(seg), 1] += seg * np.sin(th)
    return out


def rotor_loop():
    n = 2 * SR
    t = np.arange(n) / SR
    rng = np.random.default_rng(2909)
    spec = np.zeros(n // 2 + 1, dtype=np.complex128)
    hz = np.fft.rfftfreq(n, 1 / SR)
    band = (hz >= 110) & (hz <= 3500)
    amp = np.zeros_like(hz)
    amp[band] = (hz[band] / 300) ** -.75
    spec[band] = amp[band] * np.exp(2j * np.pi * rng.random(band.sum()))
    air = np.fft.irfft(spec, n=n)
    air /= max(np.max(np.abs(air)), 1e-9)
    # Integer cycles in two seconds make every layer wrap without a crossfade.
    blade = (.43 * _tone(t, 168) + .23 * _tone(t, 336)
             + .12 * _tone(t, 504) + .07 * _tone(t, 672))
    pulse = .87 + .13 * _tone(t, 8)
    x = _soft((blade + .18 * air) * pulse)
    # Close the single-sample join without muting either end of the loop.
    delta = x[0] - x[-1]
    return x + delta * (np.arange(n) / (n - 1) - .5)


def scrape():
    n = int(1.15 * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(2910)
    noise = rng.normal(size=n)
    rough = noise - np.convolve(noise, np.ones(17) / 17, mode="same")
    grain = (.52 * rough + .12 * _tone(t, 77)) * (1 - np.exp(-t / .025))
    env = np.minimum(1, t / .025) * np.minimum(1, (1.15 - t) / .18)
    return _soft(grain * env * (.7 + .3 * _tone(t, 17)))


def fall_impact():
    """A heavy metal crunch: a low body thud, buckling inharmonic panels and grit."""
    n = int(1.8 * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(2911)
    noise = rng.normal(size=n)
    thud = (_tone(t, 52) + .5 * _tone(t, 79)) * np.exp(-t / .22)
    panels = sum(amp * _tone(t, f) * np.exp(-t / tau) for f, amp, tau in
                 ((311, .5, .16), (517, .42, .11), (783, .33, .08), (1213, .25, .05), (1877, .18, .035)))
    crunch = _band(noise, 700, 5000) * np.exp(-t / .045) * .9
    grit = _band(noise, 1500, 7000) * np.exp(-np.maximum(t - .06, 0) / .12) * (t >= .06) * .25
    settle = .3 * _tone(np.maximum(t - .21, 0), 143) * np.exp(-np.maximum(t - .21, 0) / .14) * (t >= .21)
    return _soft((thud + panels + crunch + grit + settle) * np.minimum(1, t / .001))


def servo_shriek():
    """The left knee servo stripping: a harsh rising whine with gear chatter, then a stall."""
    n = int(.75 * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(2916)
    f = 900 + 1900 * np.minimum(t / .45, 1) ** 1.5 - 1400 * np.maximum(t - .5, 0) / .25
    phase = 2 * np.pi * np.cumsum(f) / SR
    whine = np.sign(np.sin(phase)) * .25 + np.sin(phase) * .5 + .2 * np.sin(2.01 * phase)
    chatter = .6 + .4 * np.sign(np.sin(2 * np.pi * 70 * t + 3 * np.sin(2 * np.pi * 9 * t)))
    grind = _band(rng.normal(size=n), 2000, 6000) * .25
    env = np.minimum(1, t / .02) * np.minimum(1, (.75 - t) / .12)
    return _soft((whine * chatter + grind) * env)


def optics_snap():
    n = int(.52 * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(2912)
    noise = rng.normal(size=n)
    crack = (noise * .42 + _tone(t, 1830) * .18) * np.exp(-t / .009)
    drop = (.18 * _tone(t, 104) + .1 * noise) * np.exp(-t / .105)
    return _soft((crack + drop) * np.minimum(1, t / .0006))


def write_wav(path, x, peak_db=-6):
    x = np.asarray(x, dtype=np.float64)
    x = x - x.mean(axis=0)
    x = x / max(np.max(np.abs(x)), 1e-9) * 10 ** (peak_db / 20)
    pcm = np.round(np.clip(x, -1, 1) * 32767).astype("<i2")
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1 if x.ndim == 1 else x.shape[1])
        wav.setsampwidth(2)
        wav.setframerate(SR)
        wav.writeframes(pcm.tobytes())
    return pcm.shape[0] / SR, float(np.max(np.abs(pcm)) / 32767)


def main():
    jobs = {
        "SFX_Echo_Ping": (ping(), -9),
        "SFX_Echo_Return": (echo_return(), -12),
        "SFX_Echo_WindLoop": (wind_loop(), -14),
        "SFX_Drone_RotorLoop": (rotor_loop(), -12),
        "SFX_Drone_Scrape": (scrape(), -10),
        "SFX_Drone_FallImpact": (fall_impact(), -8),
        "SFX_Drone_OpticsSnap": (optics_snap(), -10),
        "SFX_Carrier_ServoShriek": (servo_shriek(), -9),
    }
    for name, (pcm, peak) in jobs.items():
        dur, level = write_wav(OUT / (name + ".wav"), pcm, peak)
        print(name, f"{dur:.2f}s", f"peak={level:.3f}")
    preview = OUT.parents[2] / "Saved/UI/AuxSensors/previews/aux_echo_preview.wav"
    dur, _ = write_wav(preview, preview_sequence(), -3)
    print(preview, f"{dur:.2f}s stereo")


if __name__ == "__main__":
    main()
