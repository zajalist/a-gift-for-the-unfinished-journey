# Ambience beds, Geiger loops and road one-shots

`Tools/Audio/make_ambience.py` synthesises 17 files offline, using numpy only with a fixed seed per sound, so every run writes byte-identical files. It writes them to `Saved/GameAudio/Ambience/` and never touches Unreal.

```
python Tools/Audio/make_ambience.py            # generate everything, then check (about 2 min)
python Tools/Audio/make_ambience.py --check    # re-read the existing files, check only
python Tools/Audio/make_ambience.py --only AMB_Cloud_Wind SFX_Geiger_High
```

## No music

This is the user's rule, and it applies to every file here. There are no instruments, no melodies, no pads, no musical drones and no chords. Nothing here is a score. Everything is wind, water, wood, stone, metal, animals and electricity, built from:

- filtered noise with gust envelopes;
- modal impacts (short, inharmonic, quickly damped);
- stick-slip pulse trains;
- granular crackle.

The only steady tones are physically caused, and they sit low in the mix:

- **Mains hum** (50 / 100 Hz) in `AMB_Infrastructure` and `AMB_Transmitter_Electrical`. Its level is 10-15 dB under the rest of the bed.
- **A rock-edge whistle** in `AMB_Summit_Wind`. It is a noise band about 45 Hz wide that only sounds on strong gusts.

The `--check` pass measures every loop for sustained tone. It looks at each 1 s window: the strongest spectral peak above 150 Hz, against the median of the spectrum within ±200 Hz of it. A window counts as tonal above **12 dB**. At that level a sine is roughly at its masked threshold in its critical band, so it is barely audible (the check prints its own calibration). A loop fails if its tonal windows run for more than 3 s in a row, or make up more than 10 % of the loop. That allowance covers a caw or a knock's ring.

Mains hum below 150 Hz is excluded by design. Current results:

| Loop | Max peak | Median | Windows over 12 dB |
|---|---|---|---|
| AMB_Valley_Wind | 3.5 dB | 2.3 dB | 0/90 |
| AMB_Valley_Life | 14.8 dB | 4.2 dB | 2/90, both single caw windows |
| AMB_Settlement_Creaks | 4.4 dB | 2.5 dB | 0/75 |
| AMB_Infrastructure | 6.4 dB | 3.8 dB | 0/80 |
| AMB_Cloud_Wind | 3.3 dB | 2.3 dB | 0/60 |
| AMB_Summit_Wind | 6.5 dB | 2.8 dB | 0/75 |
| AMB_Transmitter_Electrical | 2.9 dB | 2.3 dB | 0/60 |
| All three Geiger loops | 4.6 dB or less | | 0 |

**If you replace or extend any of these, keep to the same rule.** The title screen's `TitleMusic` should become `AMB_Valley_Wind`; the storyline already asks for this.

## Format and loop mechanics

- **Format.** All files are 48 kHz, 16-bit PCM, stereo.
- **Levels.** `AMB_*` beds peak at **-12 dBFS**. Every `SFX_*` file peaks at **-3 dBFS**, including the Geiger loops, which are transient-only.
- **Noise layers.** They render 2 s of preroll, which is discarded, plus the loop, plus 4 s of overhang (1 s for Geiger). The overhang is equal-power crossfaded onto the head.
- **Discrete events** (knocks, caws, drips, clicks) sit on a circular timeline, and so do their reverb tails. A tail that runs past the end wraps onto the start, and nothing is doubled at the seam.
- **Hum** uses frequencies that complete whole cycles in the loop.
- **Cut point.** Each finished loop gets a circular 20 Hz high-pass (DC is exactly zero). It is then rotated so that the file boundary falls on its most stationary point.
- **What the check verifies:**
  - the RMS of the last 50 ms and the first 50 ms are within 3 dB (all are within 0.06 dB);
  - the step across the wrap is no bigger than the 99th-percentile sample step of the file.

In Unreal, import the beds with **Looping** on and leave them streaming. Set the 90 s beds to load on demand.

## The beds

Levels in the tables are suggested Sound Cue or AmbientSound volumes relative to 0 dB. Balance them in the mix pass.

| File | Length | What it is | Suggested use |
|---|---|---|---|
| `AMB_Valley_Wind` | 90 s | Low, gusty wind in an open, abandoned valley, gusting every 5-15 s. Dry grass and reed rustle rides the gusts. About four times a loop, a loose metal sheet far off knocks once or twice. | Base bed from the start of the road to the Mountain Foot. 2D, 0 dB. Also replaces `TitleMusic` on the title screen, at -6 dB. |
| `AMB_Valley_Life` | 90 s | Surviving nature, sparse on purpose. There are four distant sequences of 1-4 harsh crow-like caws, with long reverb across the valley. Now and then a small insect ticks a few times. Between them are long stretches of faint air. The landscape is dying, not dead. | Layer over `AMB_Valley_Wind` in the lowlands only. 2D, -4 dB. |
| `AMB_Settlement_Creaks` | 75 s | Lighter wind, with detail on top: <br>- wood creaks (beams and doors, placed on the gusts); <br>- a slow, irregular knock of a rope and pulley, 3-8 s apart, in one fixed spot; <br>- a faint drip into one puddle; <br>- a loose shutter tapping 2-5 times on strong gusts. | Numbered Basin. Place it as a spatialised AmbientSound at the Numbered Stop (V5: gutted buildings and the dead pulley on its timber frame), with attenuation as below. |
| `AMB_Infrastructure` | 80 s | A large, empty reservoir or works. <br>- Drips from three spots, each with a 4.5 s hall tail. <br>- Distant settling stone, about three times a loop. <br>- Metal ticking as the structure cools, in clusters of 1-4. <br>- Low room air. <br>- Mains hum from two units at 50.0 and 50.2 Hz, beating every 5 s, well under everything else. | Industrial ruins: the works around the departure platform (B09, 2,540-2,620 m) and the dry cistern (B10, 3,050 m). Spatialised. The drips are sparse; where a site must read as bone-dry, drop it 6 dB. **Do not use it at the Waiting Water (B05, 1,220 m), where the storyline wants no water sound at all.** |
| `AMB_Cloud_Wind` | 60 s | Dense, close, wet wind, muffled (mostly below 700 Hz). It moves slowly and deliberately has no detail. | The silent cloud-layer stretch: the fog on the Climb, 3,540-4,250 m. 2D, 0 dB, replacing the valley wind there. |
| `AMB_Summit_Wind` | 75 s | Thin, high-altitude wind: more hiss, less body, gusts every 3-10 s. On the strongest gusts a faint whistle comes off a rock edge. Now and then a small trickle of gravel skitters. | From the cloud's upper edge (4,250 m) to the road end, including the 8 s held black at the collapse. 2D, 0 dB, then -3 dB for the Human Walk. |
| `AMB_Transmitter_Electrical` | 60 s | Transformer hum (100 Hz over a weak 50 Hz, a second unit beating slowly, very little above 150 Hz). Relay armatures clack in and out at irregular times. There is faint arcing crackle, and corona hiss pulsing at 100 Hz. Faint outside wind. No tone or melody. | Spatialised at the High Voice relay hut and the mast foot (V10). It carries the "mast hum" of the Human Walk. The scripted B24 relay clunk and rising hum stay separate. |

## Placement along the road

The road metres and the Geiger curve come from `docs/story/storyline.md` (zone table and beats). The carrier walks from the eastern valley (road 0 m, spline point 54) to the High Voice (5,009 m, point 0). Cross-fade 2D beds over about 60-80 m of road, driven by the story director's road-metre high-water mark (the same "pass" mechanism as the beats).

| Road m | Zone | Beds (2D unless noted) | Geiger (storyline cps) | One-shots |
|---|---|---|---|---|
| 0-1,550 | Emptied Valley | `Valley_Wind` 0 dB + `Valley_Life` -4 dB | 0.5, `Geiger_Low` | Occasional `Wind_Gust_Heavy` (-6 dB, every 40-90 s) |
| 1,220 | Waiting Water (B05) | `Valley_Wind` only; duck `Valley_Life` -6 dB. **No water.** | 0.5 | none |
| 1,550-2,020 | The Ridge | `Valley_Wind` +3 dB; `Valley_Life` fades out by 1,700 | 0.6, `Geiger_Low` | `Wind_Gust_Heavy` on the crest line, every 20-40 s |
| 2,020-2,810 | Numbered Basin | `Valley_Wind` -4 dB. Spatial `Settlement_Creaks` at V5; spatial `Infrastructure` at the platform works | 1.5, rising to **10** at 2,600, then 3. Low, then Medium, then Medium+High. | `SFX_Geiger_Burst` once at ~2,560 as the platform comes into view (the peak). Rare `Rockfall_Distant` from the basin walls |
| 2,810-3,490 | Mountain Foot | `Valley_Wind` rising to 0 dB, "wind rising". Spatial `Infrastructure` at the dry cistern (3,050), -6 dB | 2, falling to 1. Medium, then Low. | 1-2 `Rockfall_Distant`, placed 300-600 m off the road |
| 3,490-3,540 | The Climb (below cloud) | `Valley_Wind` cross-fades to `Cloud_Wind` | 0.8, `Geiger_Low` | `Carrier_Joint_Strain` on the knee faults |
| 3,540-4,250 | The Climb, in cloud | `Cloud_Wind` only. The deliberate silent stretch. | 0.8 | `Carrier_Joint_Strain` on knee faults only |
| 4,250-4,460 | The Climb (above cloud) | `Cloud_Wind` cross-fades to `Summit_Wind` | 0.8 | `Wind_Gust_Heavy` |
| 4,460-4,790 | The Shoulder | `Summit_Wind` 0 dB | 2, rising to 4. Low+Medium, then Medium. | `Carrier_Joint_Strain` on the failing steps (4,600-4,790); `Wind_Gust_Heavy` |
| 4,790 | Collapse (B18) | `Summit_Wind` + Geiger only, through the 8 s black | 4, `Geiger_Medium` | `Capsule_Latch` on "Release the inner latch." |
| 4,790-5,009 | The Human Walk | `Summit_Wind` -3 dB; spatial `Transmitter_Electrical` at the hut and mast | 4, rising to **8** at the hut. Medium, then Medium+High. | none |

### Attenuation for the spatial beds

These are stereo beds. Give them a **Non-Spatialized Radius**, so that inside the site they surround the listener instead of collapsing to a point. Give them a wide **3D Stereo Spread** for the approach. Use natural (log) falloff with air absorption on.

| Bed | Non-spatialised radius | Falloff distance | Where to put it |
|---|---|---|---|
| `AMB_Settlement_Creaks` | 20 m | 90 m | Centre of the V5 buildings, near the dead pulley |
| `AMB_Infrastructure` | 25 m | 120 m | Inside the works or cistern, off the road edge |
| `AMB_Transmitter_Electrical` | 8 m | 70 m | The relay hut; a second, quieter instance (-6 dB) at the mast foot |

## Geiger counter

The highlands are irradiated. The counter "ticks faster wherever the old works stood" (storyline §2), which fits the title screen's radiation veil.

| File | Length | Rate | Notes |
|---|---|---|---|
| `SFX_Geiger_Low` | 30 s | about 0.5 cps (16 clicks) | Background count |
| `SFX_Geiger_Medium` | 30 s | about 3 cps (92 clicks) | 1 % doubled clicks |
| `SFX_Geiger_High` | 30 s | about 15 cps (458 clicks) | 5 % doubled clicks (after-pulse 2-6 ms later) on top of natural coincidences |
| `SFX_Geiger_Burst` | 2 s | 4 cps rising to about 80 cps by 1.1 s, holding, then settling toward 15 | Walking into a hotspot. It ends at about the `Geiger_High` rate, so hand over to that loop. |

**How the clicks are built.** Click times are Poisson-distributed, with a 0.2 ms dead time. Each click is a broadband tick of about 0.6 ms (1.8 ms to -40 dB). It has a tiny, fixed "device" body resonance at 3.15 and 5.9 kHz, and its level varies by ±1.2 dB (s.d.). Between clicks there is only the counter's own amplifier hiss, about 68 dB under the click peaks.

**Driving them from the storyline's cps curve.** Cross-fade adjacent loops by rate:

- below 1 cps: `Low`;
- 1-6 cps: from `Low` to `Medium`;
- above 6 cps: from `Medium` to `High`.

Independent Poisson streams add, so playing two loops at full volume gives the sum of their rates:

- Low + Medium = 3.5 cps;
- Medium + High = 18 cps.

This is the cheapest way to hit an in-between figure such as the 8 cps at the hut: Medium at 0 dB plus High at about -8 dB.

**Other Geiger rules:**

- Rates rise near **industrial ruins**: the Numbered Basin works and platform (peak 10 at 2,600) and the dry cistern.
- Rates rise near **the summit**: the Shoulder (2 to 4) and the High Voice hut (8).
- Duck the Geiger -6 dB under any spoken line.
- **Hull and open versions.** The storyline's `Geiger_Hull` / `Geiger_Open` swap can use these same files. Put a low-pass (about 2.5 kHz) and -4 dB on the hull variant's Sound Cue.

If `BPC_Geiger` stays a per-click Poisson timer instead, it can play single clicks. Every click in these files is the same device, so the timer and the loops can coexist.

## One-shots

| File | Length | What it is | Use |
|---|---|---|---|
| `SFX_Radio_Static_In` | 0.4 s | Squelch opens with a click. Band-limited static rushes in with crackle and a heterodyne sweeping down as the receiver locks. It settles to low hiss for the voice. | 2D, right before every `RADIO_*` line (Neighbour, Visitor, Keeper). The voice starts at about 0.3 s. |
| `SFX_Radio_Static_Out` | 0.4 s | The carrier drops. Static swells with crackle, then the squelch tail cuts hard at 0.29 s. | 2D, right after every `RADIO_*` line |
| `SFX_Carrier_Joint_Strain` | 0.8 s | A failing joint under load. Gear-mesh grind with slipping teeth, stick-slip creak of stressed metal, and a servo whine bogging down. | The knee faults on the Climb (3,600-4,460) and the failing steps (4,600-4,790). Attach it to the carrier's knee; pitch ±4 %. |
| `SFX_Capsule_Latch` | 0.5 s | Heavy latch release: pawl click, clank (thump plus a short inharmonic ring), a pneumatic hiss as the seal lets go, and one rattle bounce. | B18: "Release the inner latch." A placeholder until the session recording exists. |
| `SFX_Rockfall_Distant` | 3 s | A rock slide across the valley. Impacts swell and thin out over about 1.8 s under a low rumble. Distance low-pass, valley reverb and a late echo off the far wall. | Numbered Basin walls and Mountain Foot slopes, 1-2 times per stretch, placed 300-600 m away. Falloff about 800 m. |
| `SFX_Wind_Gust_Heavy` | 4 s | One heavy gust that builds, buffets and passes, drifting from left to right. | Over the valley bed on random 20-90 s timers; more often on the Ridge and the Shoulder. |

The storyline notes that birds, drips and rockfall had no source and were cut from the MVP (stretch S5). They now exist here as synthesised sources, so the team can decide whether to bring them back.

`Tools/Audio/ENVIRONMENT_SFX.md` covers the spot loops and ruin one-shots (sheet-metal bangs, chains, creaks and so on) that sit on top of these beds.
