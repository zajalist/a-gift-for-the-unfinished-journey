# Carrier voice (placeholder TTS + robotiser)

`Tools/Audio/make_carrier_voice.py` speaks every line in
`docs/story/carrier-voice-lines.json` with the Windows built-in System.Speech synthesizer,
robotises it with numpy, and writes the results to `Saved/GameAudio/CarrierVoice/`. These
files are placeholders: the lines JSON plans for the user to record the lines and run them
through the same kind of chain. The script never touches Unreal, and importing the files
is a separate step.

    python Tools/Audio/make_carrier_voice.py                # speak + robotise every line, then check
    python Tools/Audio/make_carrier_voice.py --check        # re-read the files, check only
    python Tools/Audio/make_carrier_voice.py --list-voices  # installed voices, * = default pick
    python Tools/Audio/make_carrier_voice.py --voice "Microsoft Zira Desktop" --rate -1

`--lines` and `--out` point it at other files. A full run takes about 6 s. For a given
voice and rate, every run writes byte-identical files: SAPI output is deterministic, and
the random choices in the "failing" style are seeded with `crc32(id)`.

## Outputs

| File | What |
|---|---|
| `VO_Carrier_<id>.wav` | One per line in the JSON, for example `VO_Carrier_CV_BOOT_01.wav`. 48 kHz, mono, 16-bit PCM, peak -3 dBFS, silence trimmed, 5 ms fades, no DC |
| `VO_Carrier_CV_BOOT.wav` | CV_BOOT_01..04 pre-mixed with 0.4 s gaps, as the JSON's `voice_wiring` asks: the boot log advances every 0.45 s, so the four lines play as one clip |
| `manifest.json` | `[{id, file, text, style, duration_s}]` in JSON order, with CV_BOOT last. `file` is relative to the manifest |

Every line is rendered, including CV_REBOOT_01..03, which the JSON marks `"record":
"not_recorded"` (log text only, never voiced). An importer that follows the JSON should
skip those three.

## Voice

- **Synthesizer.** `System.Speech.Synthesis.SpeechSynthesizer`, driven through Windows
  PowerShell 5.1 (`powershell.exe`). All the lines are spoken in one PowerShell run.
- **Voice.** Windows PowerShell 5.1 sees two voices on this machine: `Microsoft David
  Desktop` (en-US, male) and `Microsoft Zira Desktop` (en-US, female). The default is
  David, the flattest of the two, which suits "flat, even pace, no emotion". Otherwise
  the script takes the first of `PREFERRED_VOICES` that is installed, then the first
  English voice. `--voice` overrides the choice. pwsh 7 also lists the OneCore voices
  (Mark and others), but the script does not use them.
- **Rate.** -2 on SAPI's -10..10 scale, about 0.8x speed: slightly slow.
- **Pauses.** At -2, SAPI pauses about 1.1 s at a full stop and 0.5 s at a colon or
  comma. Every pause inside a line is cut to 0.35 s. That keeps the pace even and brings
  the four boot lines down from 10.8 s to 9.1 s of speech.
- **Why 16 kHz.** SAPI's `SpeakProgress.AudioPosition` (the word start times) assumes
  16 kHz 16-bit mono output, whatever format you ask for. At 48 kHz the times come out
  3x too late, and at 22.05 kHz 1.38x. So SAPI renders at 16 kHz, where the times are
  exact, and numpy upsamples to 48 kHz by spectral zero-padding. The word times place the
  stutter and the CV_FAIL_02 cut. PowerShell raises the word events on worker threads,
  out of order and sometimes after `Speak` returns, so the script matches them to their
  line by `Prompt` object and sorts them by time.

## Robotise chain

In processing order:

| # | Stage | Setting |
|---|---|---|
| 1 | Trim SAPI silence, cap pauses | -50 dB trim; pauses over 0.35 s are cut to 0.35 s (-40 dB gate) |
| 2 | Pitch/formant flattening | Autocorrelation pitch track (60-400 Hz, 10 ms hop). Each voiced frame is pulled 50 % of the way to the line's median pitch (clamped to ±0.35 oct, smoothed over 50 ms). The shift comes from a resample-based shifter: two crossfaded delay-line heads reading at a time-varying speed, 30 ms window. Resampling moves the formants with the pitch, so the formant movement that rides on intonation flattens too |
| 3 | Ring modulation | 48 Hz sine, 22 % mix (sidebands -17 dB below the voice) |
| 4 | Style variant | See below: stutter, beep, cut and dropouts all happen here, upstream of the speaker |
| 5 | Bitcrush | Sample-and-hold to 8 kHz plus 8-bit quantisation, 20 % wet. It runs before the band limit so the fold-down lands in band as grit, while its images above 4 kHz are filtered out |
| 6 | Band limit | 300 Hz-4 kHz, zero-phase FFT mask, raised-cosine edges 0.3 octave wide |
| 7 | Metallic comb | Two feedback combs (2.1 ms and 3.4 ms, feedback 0.5), 35 % wet, impulse response cut at -60 dB (about 35 ms) |
| 8 | Finalise | Trim at -45 dB (10 ms head, 30 ms tail), 5 ms raised-cosine fades, DC removal, peak-normalise to -3 dBFS, int16 |

## Styles

| Style | Adds |
|---|---|
| `system` | Nothing beyond the chain |
| `warning` | Two-tone prefix: 1320 Hz then 990 Hz (a falling fourth), 90 ms each with a 30 ms gap, at 0.45x the voice peak. The voice starts 0.36 s into the file. The beep passes through the speaker stages but not the ring modulator |
| `failing` | **Pitch sag**: from halfway through the line the pitch falls on a u² curve to -3.5 semitones at the last sample. **Stutter**: the first 60-110 ms of one word (not the last word, and at least 3 letters) plays twice more before the word, like a skipping buffer ("ca-ca-carrier"). **Dropouts**: 2 to 4 gaps of 35-85 ms (one per 0.9 s of line), placed in speech, at least 180 ms apart and clear of the stutter. The speaker's resonance rings briefly into each gap |

Per-line extra: **CV_FAIL_02** ("Load within… within…", "Cuts to static mid-word") stops
55 % of the way into its last word. The static itself is the game's `SFX_Carrier_Static`.

A run prints what each variant did, in file time, for example `stutter on 'Critical' at
1.39 s` and `dropouts at 0.25-0.33, 2.44-2.48, 2.64-2.70 s`.

## Check (`--check`, and after every run)

A file fails if it is:

- missing
- not 48 kHz mono 16-bit PCM
- outside 0.3-15 s
- peaking outside -3.5..-2.5 dBFS
- at RMS -40 dBFS or quieter
- less than 25 % active (20 ms windows within 30 dB of the loudest)
- carrying DC over 1 %
- non-silent at its edges (more than 16 LSB)
- holding less than 95 % of its energy between 200 Hz and 5 kHz
- a `warning` file whose beep windows hold less than 50 % of their energy within 60 Hz
  of the tone

CV_BOOT must also be exactly its four source lines plus the gaps.

The manifest must list the JSON's ids in order, then the pre-mix, with exactly the five
keys. Each entry's file, text and style must match the JSON, and duration_s must match
the file to 1 ms. So after anyone edits the lines JSON, `--check` fails until you
regenerate. Extra `VO_Carrier_*.wav` files not in the JSON get a warning. The exit code
is 1 on any failure.

**Listen proxy.** The check prints one row per file: duration, RMS, peak, active share
and beep purity, so you can sanity-check a file without playing it. For this voice at
-3 dBFS peak, the RMS lands between about -22 and -28 dBFS and the active share between
55 % and 95 %. A row far outside that range means something is wrong with that file.

## Measured on the current render

These are one-off measurements from a scratch script, not part of `--check`:

- Flattening halves the pitch spread of the 13 system lines (median robust spread
  3.7 → 1.8 st), and each line's median pitch stays put (87-110 Hz after).
- The sag averages -1.9 to -2.3 st over the last fifth of each failing line, against
  the same line without sag.
- Every file has at least 75 dB less energy above 6 kHz, and at least 82 dB less below
  200 Hz, than its total.
- In the written files, each stutter copy correlates 0.977-1.000 with the next. The
  dropout cores sit 29-69 dB below the loudest 10 ms.

## Tuning

All the settings are constants at the top of the script: `FLATTEN`, `RING_*`,
`CRUSH_*`, `BAND_*`, `COMB_*`, `BEEP_*`, `SAG_*`, `STUTTER_*`, `DROPOUT_*`,
`MAX_PAUSE_S`, `CUT_LAST_WORD` and `PREMIXES`.

The chain in `render_line` takes 16 kHz mono float audio and optional word start times.
Without word times, the stutter falls back to energy onsets. That is the part to reuse
for the recorded takes.
