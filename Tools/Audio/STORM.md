# Storm, wind and radiation soundscape

Recorded layers for the storm/wind/radiation system described in the design spec, section 6
("Storm, wind and radiation soundscape, with lightning"). Distinct from the storyline-driven
ambience in `AMBIENCE.md` / `AMBIENCE_MIX.md` (which carries the road-metre zone mix and the
`SFX_Geiger_Low/Medium/High/Burst` cps ramp) — this system is driven by **`StormIntensity`**, a
0-1 value the lighting director (`USaskartaLightingDirector`, Task L7) exposes per look key, plus
its own lightning/thunder timer.

`Tools/Audio/fetch_storm.py` fetches every file below from Freesound CC0, writes 48 kHz 16-bit
WAVs to `Saved/GameAudio/Recorded/Storm/` plus `manifest.json`, and logs sources in
`freesound_credits.json` / `CREDITS.md`. Import target: `/Game/SaskartaGaea/Audio/Storm`.

## StormIntensity, from the look keys

`StormIntensity` is `storm_intensity` in `Tools/Look/look_keys.json`, blended by the director the
same way it blends every other look value (Task L7). At the time of writing, `look_keys.json`
carries the Valley key only (Task L1 is still authoring the other four); the table below uses the
Valley value where it exists and the spec's narrative for the rest, so the Basin/Climb/InCloud/
Above numbers are **expected, not yet pinned** — read `storm_intensity` from `look_keys.json`
itself once L1 finishes, and treat this table as the intent it must land close to.

| Key | Road m | Spec narrative | `storm_intensity` (expected) |
|---|---|---|---|
| Valley | 0 | Storm dusk, heavy cumulus, warm breaks | **0.6** (pinned in `look_keys.json`) |
| Basin | 2,300 | Heavier and darker storm, still air | ~0.85 (darkest, most oppressive key) |
| Climb | 3,800 | Cloud base lowers, wind rises, fog thickens | ~0.5 (transitional: wind up, storm easing) |
| In the cloud | 4,350 | Inside the cloud layer: dense, muffled, grey | ~0.25 (muffled, not violent) |
| Above | 4,550 | Clear golden light, cloud layer below | **0.0** (no storm above the clouds) |

Lightning only fires in keys with `storm_intensity > 0.3` (Valley, Basin, Climb), per Task L7.

## What StormIntensity drives

Straight from spec section 6:

- **Wind bed volumes** — the `AMB_Storm_Wind*_Loop` beds (see below) scale their volume with
  `StormIntensity`; `AMB_Storm_WindHighAlt_Loop` takes over from the others above the Climb key.
- **Gust rate** — `SFX_Storm_Gust_Heavy_*` and `SFX_Storm_Edge_Whistle_*` fire on a random timer,
  20-90 s between events at `StormIntensity = 1`, scaled the same way as the lightning timer
  below (linearly slower as intensity falls; no gusts below ~0.15). `SFX_Storm_Tarp_Snap_*` rides
  the same timer, spatial-only near the settlement and waterworks ruins.
- **Thunder rate** — see the lightning timer below; there is no independent thunder timer, thunder
  always follows a lightning flash.
- **Geiger rate** — `SFX_Geiger_Spike_*` layers over the storyline's `SFX_Geiger_Low/Medium/High`
  cps loops (`AMBIENCE.md`); its rate follows the **ecology zone and the storyline's Geiger ramp**,
  not `StormIntensity` directly. `SFX_Dosimeter_Chirp_01/02` is the carrier's own instrument and
  also follows the storyline Geiger ramp, 2D, independent of the weather.

## The lightning timer (Task L7, `USaskartaLightingDirector`)

In a key with `storm_intensity > 0.3`:

1. A random timer, **20-90 s** between flashes, **scaled by `StormIntensity`** (short end at
   intensity 1, long end as intensity approaches 0.3; no flashes below 0.3). Each flash pulses
   `LightningFlash` on `MPC_Saskarta_Sky` (0.08 s up, 0.4 s down) and a brief sun-intensity pop.
2. A **strike distance** is rolled, 1-8 km.
3. **`SFX_Lightning_Crack_01..03`** plays immediately with the flash: the sharp crack synced to the
   light itself, before the thunder arrives. Pick a random variant each time.
4. **Thunder follows after `distance_km * 1000 / 343` seconds** (speed of sound, 343 m/s):
   - strike distance **< 2.5 km** -> a random `SFX_Thunder_Close_01..04` (louder, sharper, shorter
     onset delay reads as "close");
   - strike distance **>= 2.5 km** -> a random `SFX_Thunder_Rolling_01..04` (softer, longer,
     rolling tail).
5. No extra lights or shadows are spawned for lightning; it is a material/scalar pulse plus these
   sounds. Cost is unmeasurable per spec.

`SaskartaDirectorTest.cpp` (Task L7) checks the delay is exactly `distance / 343`.

## Asset table

Beds (`AMB_*`, seamless loop, peak **-14 dBFS**, 60-120 s — see `fetch_storm.py: tile_to_floor`
for how a shorter source is tiled up to the 60 s floor without breaking the seam):

| Asset | Use | 2D / spatial |
|---|---|---|
| `AMB_Storm_WindHeavy_Loop` | Main storm wind bed, Valley/Basin/Climb; volume scales with `StormIntensity` | 2D |
| `AMB_Storm_WindRuins_Loop` | Wind howling through the settlement and waterworks ruins | Spatial |
| `AMB_Storm_WindHighAlt_Loop` | Thin, cold wind above the tree line (Climb, In-the-cloud) | 2D |
| `AMB_Storm_GritDebris_Loop` | Blowing grit/sand/debris, low under the wind beds on the driest switchbacks | 2D |
| `AMB_Storm_Distant_Loop` | Far storm rumble, always-on low layer under the thunder one-shots | 2D |
| `AMB_Storm_DryStatic_Loop` | Charged-air static hum just ahead of a lightning timer firing | 2D |
| `AMB_Storm_FacilityHum_Loop` | Distant ruined-facility hum at the waterworks and basin | Spatial |
| `AMB_Storm_PowerlineBuzz_Loop` | Power-line buzz near the old transmission run, layers with FacilityHum | Spatial |

One-shots (`SFX_*`, peak **-3 dBFS**), each cut from one longer recording (see `manifest.json`
for the exact source stretch of every variant):

| Family | Variants | Fired by |
|---|---|---|
| `SFX_Storm_Gust_Heavy` | 01-06 | Gust timer (20-90 s, scaled by `StormIntensity`) |
| `SFX_Storm_Edge_Whistle` | 01-03 | Same gust timer, layered with a heavy gust |
| `SFX_Storm_Tarp_Snap` | 01-03 | Same gust timer, spatial at ruined structures only |
| `SFX_Lightning_Crack` | 01-03 | Immediately on each lightning flash |
| `SFX_Thunder_Close` | 01-04 | Lightning timer, strike distance < 2.5 km |
| `SFX_Thunder_Rolling` | 01-04 | Lightning timer, strike distance >= 2.5 km |
| `SFX_Geiger_Spike` | 01-04 | Storyline Geiger ramp / ecology zone, layered over the loops in `AMBIENCE.md` |
| `SFX_Electrical_Arc` | 01-04 | Random slow timer near the works and power-line buzz bed |
| `SFX_Metal_Tick` | 01-04 | Random slow timer at the ruined facility, layered with `AMB_Storm_FacilityHum_Loop` |
| `SFX_Dosimeter_Chirp` | 01-02 | Storyline Geiger ramp (the carrier's instrument), independent of weather |
| `SFX_Siren_Distant` | single | Rare: at most once per session (a scripted beat, not a timer) |

All of it is environmental; the siren is mechanical, not music, per spec section 6.

## Levels and measurement

Run `python Tools/Audio/fetch_storm.py --measure` to reprint RMS/peak/seam metrics for the written
files without re-fetching. Beds must show a seam level gap under about 1 dB (the `make_loop`
crossfade); one-shots peak at -3 dBFS by construction (`freesound_fetch.normalize`).

## Sources

Every source, its licence, and its next-best alternates (for a one-line swap) are in
`Tools/Audio/CREDITS.md` and `Tools/Audio/freesound_credits.json`, written by `fs.credit()`.
