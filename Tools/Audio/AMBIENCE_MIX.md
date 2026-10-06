# Ambience mix: layer recipe along the road

This is the recipe for the recorded ambience, zone by zone, from the boot point (road 0 m, spline point 54) to the High Voice (5,009 m, point 0). Zones and metres come from [`docs/story/road-profile.md`](../../docs/story/road-profile.md). Beats and the Geiger curve come from [`docs/story/storyline.md`](../../docs/story/storyline.md).

The files are made by `Tools/Audio/fetch_ambience.py` from Freesound CC0 recordings. It writes them to `Saved/GameAudio/Recorded/Ambience/`, and they import to `/Game/SaskartaGaea/Audio/Ambience`. Sources, alternates and processing notes are in `Tools/Audio/CREDITS.md`.

The goal is a moodier game: darker, lonelier, bigger and more melancholic, and still pure environment. **There is no music and nothing tonal is added.** The only tones are physical ones: wind whistle and moan, crickets, metal stress, and the synthesised mains hum.

## How to read the levels

- Levels are **Sound Cue or AmbientSound volume in dB**, relative to the zone's main bed at 0 dB.
- The recorded beds peak at -14 dBFS and the spot loops at -12 dBFS. Their loudness is very different, so the table below is already corrected for it (measured RMS of each file).
- **2D beds** cross-fade over 60-80 m of road. They are driven by the story director's road-metre high-water mark, the same "pass" mechanism the beats use.
- **Spatial layers** are AmbientSounds with a Non-Spatialized Radius, a wide 3D Stereo Spread, log falloff and air absorption on (as in `AMBIENCE.md`).

| File | Kind | Length | RMS dBFS | Base volume | Note |
|---|---|---|---|---|---|
| `AMB_Valley_Wind` | 2D bed | 95 s | -35.5 | 0 dB | Reference bed |
| `AMB_Valley_Life` | 2D layer | 110 s | -44.4 | -3 dB | Already sparse and quiet |
| `AMB_Settlement_Creaks` | spatial | 80 s | -34.2 | -2 dB | |
| `AMB_Infrastructure` | spatial | 90 s | -45.6 | +2 dB | Drips and air, quiet by nature |
| `AMB_Cloud_Wind` | 2D bed | 90 s | -38.2 | 0 dB | Muffled below 750 Hz |
| `AMB_Summit_Wind` | 2D bed | 90 s | -36.9 | 0 dB | Thin: high-passed at 160 Hz |
| `AMB_Mountain_Rumble` | 2D layer | 100 s | -27.2 | **-14 dB** | Steady sub energy. Keep it felt more than heard |
| `AMB_Ruins_Wind_Moan` | spatial | 34 s | -29.0 | -8 dB | |
| `AMB_Reed_Marsh` | spatial | 34 s | -34.9 | -4 dB | |
| `AMB_Cloud_Drizzle` | 2D layer | 76 s | -40.6 | -6 dB | |
| `AMB_Thunder_Far_Loop` | 2D layer | 110 s | -40.5 | -8 dB | Silence between rolls |
| `AMB_Transmitter_Electrical` (synth, kept) | spatial | 60 s | | as in `AMBIENCE.md` | |
| `SFX_Geiger_*` (synth, kept) | 2D | 30 s | | see the Geiger section | |

One-shots peak at -3 dBFS: `SFX_Thunder_Distant_01..03`, `SFX_Raven_Distant_01..03`, `SFX_Metal_Groan_Distant_01..03`, `SFX_Wind_Gust_Heavy` and `SFX_Rockfall_Distant`. Play them on random timers with the volumes given per zone, pitch ±3 %, and never two of the same family inside 20 s.

## Zone by zone

| Road m | Zone (road profile) | 2D beds and layers | Spatial layers | One-shots |
|---|---|---|---|---|
| 0-1,550 | **Valley floor** | `Valley_Wind` 0 dB. `Valley_Life` -3 dB. `Mountain_Rumble` -20 dB (the far mountain is on the skyline). | none | `Raven_Distant` -8 dB, 150-400 m off the road, every 60-150 s. `Wind_Gust_Heavy` -8 dB, every 40-90 s. |
| 1,160-1,280 | Waiting Water (B05, 1,220 m), inside the valley floor | Duck `Valley_Life` to -9 dB. **No water sound** (storyline rule). | `Reed_Marsh` -4 dB. Place 2-4 instances along the dry channel in the PCG reeds (see PCG below). Radius 10 m, falloff 60 m. | none |
| 1,550-2,020 | **Ridge** (crest at 1,980) | `Valley_Wind` +3 dB. `Valley_Life` fades out by 1,700. `Mountain_Rumble` -16 dB: the widest view of the road, so the mountain is loudest here. | none | `Wind_Gust_Heavy` -4 dB on the crest line, every 20-40 s. `Raven_Distant` -10 dB, only once or twice. |
| 2,020-2,510 | **Descent into the basin** | `Valley_Wind` -3 dB. `Mountain_Rumble` -18 dB. `Thunder_Far_Loop` fades in from 2,150 to -12 dB, as the summit drops from view and the Geiger ramp starts. | none | `Rockfall_Distant` -10 dB from the basin walls, 300-600 m away, once. |
| 2,510-2,810 | **Basin floor**: the Numbered Stop, platform and works (2,540-2,620) | `Valley_Wind` -4 dB. `Thunder_Far_Loop` -10 dB. `Mountain_Rumble` -18 dB. | `Settlement_Creaks` -2 dB at the V5 buildings (radius 20 m, falloff 90 m). `Infrastructure` +2 dB inside the works (radius 25 m, falloff 120 m). `Ruins_Wind_Moan` -8 dB in one gutted building and at the broken arch (radius 6 m, falloff 50 m). | `Metal_Groan_Distant` -10 dB from inside the works, every 60-200 s. `Thunder_Distant` -12 dB, every 90-180 s. |
| 2,810-3,490 | **Mountain foot** (the dry cistern at 3,050) | `Valley_Wind` rising to 0 dB ("wind rising"). `Mountain_Rumble` rising from -18 to -14 dB. `Thunder_Far_Loop` -12 dB. | `Infrastructure` -4 dB at the cistern (the storyline wants it dry, so -6 dB against the works). `Ruins_Wind_Moan` -10 dB at the cistern walls. | `Rockfall_Distant` -8 dB, 1-2 times, 300-600 m away. `Thunder_Distant` -12 dB, every 120-240 s. |
| 3,490-3,540 | **Switchback climb**, below the cloud | `Valley_Wind` cross-fades to `Cloud_Wind`. `Thunder_Far_Loop` fades out. | none | `Carrier_Joint_Strain` (knee faults) |
| 3,540-4,250 | **Switchback climb, in the cloud** (the silent stretch) | `Cloud_Wind` 0 dB. `Cloud_Drizzle` -6 dB. `Mountain_Rumble` -14 dB. Nothing else: this silence is what makes the voices at 4,460 land. | none | `Carrier_Joint_Strain` only. At most one `Thunder_Distant` at -16 dB (heard through the cloud) in the whole stretch. |
| 4,250-4,460 | **Switchback climb**, above the cloud | `Cloud_Wind` cross-fades to `Summit_Wind`. `Cloud_Drizzle` fades out by 4,300. `Mountain_Rumble` fades to -20 dB. | none | `Wind_Gust_Heavy` -6 dB |
| 4,460-4,790 | **Summit approach**: the shoulder, the most open ground | `Summit_Wind` 0 dB. `Mountain_Rumble` -20 dB. | none | `Wind_Gust_Heavy` -4 dB, every 20-50 s. `Carrier_Joint_Strain` on the failing steps (4,600-4,790). `Metal_Groan_Distant` -14 dB from the mast direction, once, near 4,700. |
| 4,790 | Collapse (B18) and the 8 s black | `Summit_Wind` and Geiger only. Everything else is cut on the black. | none | `Capsule_Latch` |
| 4,790-5,009 | Summit approach: the human walk | `Summit_Wind` -3 dB. | `Transmitter_Electrical` at the hut and the mast foot (as in `AMBIENCE.md`). `Ruins_Wind_Moan` -12 dB at the hut. | `Metal_Groan_Distant` -12 dB from the mast, once or twice (the guy wires under load). No ravens and no thunder: the ending is only wind and the Geiger counter. |

**Rules that keep it lonely.**

- Every one-shot family has a zone where it does not play.
- The Valley is the only zone with life, and even there only ravens.
- Above 3,490 m nothing lives.
- Leave the spatial layers out of 2D space: they should be heard coming from their site and then gone.

## Geiger counter

The rates are the storyline's cps curve. The loops (`SFX_Geiger_Low`, `SFX_Geiger_Medium`, `SFX_Geiger_High`, `SFX_Geiger_Burst`) are the synthesised ones, which are kept. Mix them as `AMBIENCE.md` describes: Low below 1 cps, Low to Medium over 1-6 cps, Medium to High above 6 cps. Duck them -6 dB under any spoken line.

| Road m | Where | cps | Loops |
|---|---|---|---|
| 0-1,550 | Valley floor | 0.5 | Low |
| 1,550-2,150 | Ridge and the top of the descent | 0.6 | Low |
| **2,150-2,600** | **B07, the Geiger rises**: the descent into the basin toward the works | 0.6 → **10** | Low → Medium → Medium+High. `SFX_Geiger_Burst` once at ~2,560, as the platform comes into view. |
| 2,600-2,810 | Basin floor, past the works | 10 → 3 | Medium+High → Medium |
| 2,810-3,490 | Mountain foot. A local rise at the **dry cistern (3,050)**: an old works site | 2 → 1, with a bump to ~4 within 60 m of the cistern | Medium → Low. The bump is Medium at +0 dB. |
| 3,490-4,460 | The climb and the cloud | 0.8 | Low |
| **4,460-4,790** | **Summit approach**: the shoulder | 2 → 4 | Low+Medium → Medium |
| 4,790 | Collapse and the 8 s black | 4 | Medium (the `Geiger_Hull` variant) |
| **4,790-5,009** | The human walk to the hut | 4 → **8** at the hut | Medium → Medium +0 dB with High at -8 dB (the `Geiger_Open` variant) |

The rate rises in three places, and each is an old industrial or transmitter site: the Numbered Basin works and platform (the peak, 10 cps), the dry cistern, and the summit approach to the mast.

## Placing the spatial layers with PCG

The 2D beds should not be PCG. They follow the road metre through the story director, and they need exact cross-fade points.

The **spatial layers and the positioned one-shots** suit PCG, because they follow things PCG already places or can sample. Suggested graphs (design only; nothing has been changed in the editor):

1. **Reed Marsh at the Waiting Water.**
   - Take the existing reed points (`/Game/Megaplant_Library/Plant_Dry_Common_Reeds/`, V4) as input.
   - Apply **Self Pruning** at a 25-30 m radius, so that 40 m of channel yields only 2-4 points.
   - Keep the points within 20 m of the channel.
   - **Spawn Actor** an `AmbientSound` with `AMB_Reed_Marsh` on each point. Give each a random start time, so that neighbours do not play in phase.
2. **Ruins moan and settlement creaks.**
   - Sample the ruin meshes (`AB SM_Broken_Walls`, `SM_300x400_Mid_Damaged_A`, `SM_Broken_Arch_Wall`) by tag.
   - Prune hard: at most one emitter per structure, and at most 3 per site.
   - Spawn `AMB_Ruins_Wind_Moan` at the pruned points.
   - Leave `Settlement_Creaks` and `Infrastructure` as single hand-placed actors at the V5 centre and the works.
3. **Distant one-shot emitters.**
   - Run a **Spline Sampler** on the RoadSpline with a lateral offset of 150-600 m.
   - Keep only the points whose road metre falls in each family's zone range (the table above).
   - Spawn a small `BP_AmbientOneShotEmitter`: an AmbientSound plus a random re-armed timer. Use it for ravens (valley and ridge), rockfall (basin walls and mountain foot) and metal groans (the works and the mast).
   - This places each sound in the real terrain direction, instead of playing it at a random point around the listener.
4. **Keep the emitter count small.**
   - Use a sound concurrency group per family (max 2).
   - Set each emitter's attenuation falloff to match its role.
   - PCG spawners have a cull distance, and **0 means infinite** (see the project memory). Emitters must not be left always live across the 5 km map, so let the attenuation and virtualisation handle distance.

## Picks to check by ear

Nobody has listened to these yet. The least certain picks are:

- `AMB_Reed_Marsh`: the insect layer is tonal crickets and frogs, with 10 of 33 windows over the 12 dB tone threshold. It sits -14 dB under the reeds, but the crickets may read as too alive, or as a pitch. To remove it, drop the `secondary` layer in the script.
- `SFX_Metal_Groan_Distant_01..03`: metal stress is tonal by nature (a squeal pitched down 0.55-0.8x). They may sound like a bowed instrument. If so, use a lower pitch ratio or swap in an alternate.
- `AMB_Infrastructure`: an abandoned plant near Charleroi. There may be faint distant traffic under the drips. Its seam RMS gap is 3.9 dB because a drip sits at the loop point, but the wrap sample step is clean.
- `AMB_Valley_Wind` and `SFX_Wind_Gust_Heavy` come from the same field recording (Freesound 202961). The gust is cut from 145 s and the bed from 32-129 s, so the gust never repeats inside the bed. The two will still share a timbre.
- `AMB_Cloud_Wind`: a snow storm recorded at a car park (Cradle Mountain), with the recorder in the back of a parked car. The low-pass at 750 Hz hides detail, but check it for a door or engine sound.
