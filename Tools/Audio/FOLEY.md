# Saskarta foley set (carrier, human, UI)

Generated offline by `Tools/Audio/make_foley_sfx.py` into `Saved/GameAudio/Foley/`
(31 WAVs, `manifest.json`, `_spectrograms.png`). Fixed seeds mean every run writes identical files.

    python Tools/Audio/make_foley_sfx.py           # generate + manifest + contact sheet + check
    python Tools/Audio/make_foley_sfx.py --check   # check only

No music: every sound is a physical source (motor, gear mesh, hydraulics, metal, stone,
gravel, air). The `--check` no-music test rejects any tone above 150 Hz that holds a
spectral peak 18 dB or more over its local median for 0.5 s or longer. The script
docstring gives the exact method and all the other limits.

Format: 48 kHz, 16-bit PCM. One-shots are mono, peak -3 dBFS, with 5 ms fades. Loops
are stereo (L/R correlation 0.06 to 0.32), peak -12 dBFS, and loop seamlessly
(level-matched cut plus a 1 s equal-power crossfade).

## What each sound is for

| Sound | Use | Attenuation (m) |
|---|---|---|
| `SFX_Carrier_Step_Servo_01..06` | Leg servo whirr ending in a hydraulic thump. Always layered over a recorded footstep (see below). **The thump lands 150 ms into every variation.** | 25 |
| `SFX_Carrier_FootPlate_01..04` | Damped metal foot-plate clank for hard surfaces. 02 and 04 have a second rocking tap. | 25 |
| `SFX_Carrier_Servo_Idle_Loop` (20 s) | Standing idle: 50/100 Hz mains hum, cooling air, holding-current hiss, occasional servo micro-corrections and settling ticks. Play at about -18 dB and fade in after 1 s of standing still. | 10 |
| `SFX_Capsule_Tow_Gravel_Loop` (30 s) | Towed capsule rolling on gravel or the old road: rumble, crunch, mid grind, stone pops. | 35 |
| `SFX_Capsule_Tow_Dirt_Loop` (30 s) | The same on dirt or grass: softer rumble, dragging shush, crumbs, clod knocks. | 30 |
| `SFX_Capsule_Scrape_Failing` (3 s) | The failing final carrier: capsule grinding on stone (stick-slip), a motor that sags and cuts out, a drop-out and lurch at about 1.2 s. | 40 |
| `SFX_Carrier_Collapse` (2.5 s) | Servos die (0 s), knee hits stone (0.22 s), body slams (0.50 s), tow bar jolts (0.86 s), then a bouncing loose part, a panel rattle and grit trickle. | 60 |
| `SFX_Carrier_Dock_Clamp` (1 s) | Carrier exchange: the cradle drive closes, the jaws clank at 0.33 s, pawls click, the hydraulic lock bleeds. | 30 |
| `SFX_Carrier_Reconnect` (1.2 s) | Control handover: a relay chain (0 to 0.33 s), a 100 Hz coil buzz, a servo spin-up (0.45 to 1.1 s), a latch tick. | 25 |
| `SFX_WalkingAid_Tap_Stone_01..04` | Ending walk: ferrule tip on stone. 02 skids; 04 bounces into a double tap. | 15 |
| `SFX_WalkingAid_Tap_Gravel_01..04` | Ending walk: tip into gravel. 02 and 03 knock a pebble loose. | 15 |
| `SFX_Cloth_Rustle_01..03` | Human body/clothing movement. **Placeholder**; replace it (see the weak list). | 8 |
| `SFX_Capsule_Hatch_Open` (2 s) | Plays after `SFX_Capsule_Latch`: the seal hisses open, the gasket peels, the hinge creaks, and the hatch swings onto its stop at 1.55 s. | 30 |
| `SFX_UI_Hover` (60 ms) | Title menu hover: tiny relay tick. 2D. | - |
| `SFX_UI_Confirm` (0.45 s) | Title menu confirm: contactor clack plus a short servo. 2D. | - |

Randomise variations in a Sound Cue (Random node, no repeats) and add Modulator pitch
0.96 to 1.04 and volume 0.85 to 1.0. The variations already differ in seed, pitch, mix
and extra layers, so the modulator only adds spread.

## Layering carrier steps over the recorded footsteps

A carrier step has up to three layers:

1. **Surface:** the recorded footstep (`/Game/AzielArts_Material/Footsteps/SoundWav/`).
2. **Servo:** `SFX_Carrier_Step_Servo_*`.
3. **Plate:** `SFX_Carrier_FootPlate_*`, on hard surfaces only.

Timing: the servo file's thump lands **150 ms** after it starts. Trigger the servo from
an anim notify placed 150 ms before foot contact, and fire the surface and plate layers
on the contact notify. If there is only a contact notify, fire the servo on contact and
delay the surface and plate layers by 0.15 s (a Delay node in the cue).

| Surface (recorded set) | Surface layer | Servo layer | Plate layer |
|---|---|---|---|
| Rock (`Rock_Mono_01-05`) | 0 dB | -6 dB | -8 dB, 60 % chance |
| Pavement / old road (`PavementTiles_Mono_*`) | 0 dB | -6 dB | -4 dB, always |
| Glass / grit (`Glass_Grit_Mono_*`) | 0 dB | -6 dB | -10 dB, 40 % chance |
| Mud (`Mud_Mono_*`) | 0 dB | -8 dB, lowpass 4 kHz | none (the plate sinks) |
| Undergrowth (`Undergrowth_Mono_*`) | 0 dB | -8 dB | none |
| Wet snow (`Wet_Snow_Mono_*`, above the clouds) | 0 dB | -9 dB, lowpass 5 kHz | none |

The servo layer carries the "this is a machine" identity. Keep it on every surface,
even when the plate is dropped.

## Tow loops: speed to volume and pitch

Both tow loops contain no periodic wheel or step rhythm, so any playback rate works.
Run the loop for the current surface (gravel for road, stone and settlement; dirt for
grass, mud and snow) and crossfade the two over 0.5 s when the surface changes.

With `v` = capsule speed (m/s), `v_max` = normal carrier walking speed, and
`s = clamp(v / v_max, 0, 1.25)`:

    volume = 0                          if s < 0.03   (fade out over 0.3 s, stop the component after 1 s silent)
    volume = s ^ 0.7                    otherwise     (linear gain; about -7 dB at half speed)
    pitch  = 0.80 + 0.25 * s                           (0.80 at a crawl, 1.05 at walking speed, 1.11 hurried)
    lowpass cutoff = 2500 + 15500 * s  Hz              (optional: slow means duller, no crunch sparkle)

Smooth `s` with a 0.15 s interpolation so step-to-step speed wobble does not flutter the
volume. On slopes steeper than 10 degrees, add +1.5 dB and -0.03 pitch: the load strains and slows.

`SFX_Capsule_Scrape_Failing` replaces the tow loop during the final carrier's failure
(crossfade over 0.3 s); it is a one-shot, so re-trigger it with a random start while the
failure state lasts.
