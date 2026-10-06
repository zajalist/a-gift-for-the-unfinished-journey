# Ambience 2 and the Geiger counter: post-build editor steps

The C++ side is `USaskartaAmbienceDirector` (a world subsystem in `Plugins/SaskartaCore`). It needs no
Blueprint, but it has nothing to play until the audio is imported and `DA_Ambience` exists. Until then it
imports a transient copy of the manifest (editor builds only), finds no sounds, and stays silent.

- Brief: `.superpowers/sdd/2026-09-26-saskarta-world-sprint/task-AMBIENCE2-brief.md`
- Data: `Saved/GameAudio/Ambience2/manifest.json` (150 WAVs, the zones, pools, spots and the dose table)
- Code:
  - `SaskartaAmbienceDirector.h/.cpp`: the director
  - `SaskartaAmbienceAsset.h`: `DA_Ambience`
  - `SaskartaAmbienceImport.h/.cpp`: manifest to asset
  - `SaskartaAmbienceLogic.h/.cpp`: the pure maths
  - `SaskartaAmbienceSettings.h/.cpp`: the Geiger setting
  - `Tests/SaskartaAmbienceTest.cpp`: the tests

Rules for every step: one editor lane at a time. Check for PIE first, and never start PIE unasked.
Hayba `python_run` allows 5 s and at most 4 imports per call, and the banned words are `try`, `getattr`,
`open(`, `.replace(`, `new_level(` and `import time`. Commit uassets by pathspec only, because the editor's Git
provider stages new packages by itself.

## 0. Build

Close the editor and build `SaskartaCore` (the live `Binaries` are rebuilt only here). The new reflected
names are:

- `USaskartaAmbienceDirector`, `USaskartaAmbienceAsset`, `USaskartaAmbienceImport` and `USaskartaAmbienceSettings`;
- `FSaskartaAmbienceZone`, `FSaskartaAmbienceBed`, `FSaskartaAmbiencePool`, `FSaskartaAmbienceSpot` and `FSaskartaGeigerLoop`;
- `ESaskartaBedStormMode` and `ESaskartaPoolPlacement`.

None of them has a U/F same-name clash.

`USaskartaLightingDirector` gains one property, `bPlayThunder`. The ambience director clears it once its own
thunder has streamed in, so thunder is never doubled (brief option B). No asset changes.

## 1. Import the 150 WAVs

1. Import every `Saved/GameAudio/Ambience2/*.wav` **except `_demo_road.wav`** to
   `/Game/SaskartaGaea/Audio/Ambience2/`, keeping the file stem as the asset name.
   - `Tools/Audio/import_game_audio.py` has no ambience step yet. Use its `IMPORT` template with jobs
     `(wav_path, "/Game/SaskartaGaea/Audio/Ambience2", stem, loop)`, in batches of 4.
   - `loop` is the manifest's `"loop"` flag. It is true for the beds, the spot loops and the four
     `SFX_Geiger_Rate_*_Loop`.
2. **Loading.** Stream the loops and keep the one-shots inline:
   - `loop: true` (beds, spot loops, Geiger rate loops): `loading_behavior = LOAD_ON_DEMAND` (streamed).
     `Tools/Audio/set_streaming.py` already targets `AMB_*`; add the four `SFX_Geiger_Rate_*_Loop`.
   - One-shots (`SFX_*` without `_Loop`, the Geiger clicks included): `RETAIN_ON_LOAD` (inline, ready when
     the director's async prefetch lands). Keep the clicks uncompressed or ADPCM. At 30 ms, decode
     latency matters.
3. Check with `python Tools/Audio/import_game_audio.py read /Game/SaskartaGaea/Audio/Ambience2`: 150 SoundWaves.

## 2. Sound classes and submix

1. Create `SC_Ambience` in `/Game/SaskartaGaea/Audio/Ambience2/`. Parent it to the existing ambience class if
   there is one (`/Game/SaskartaGaea/Audio/Classes/`).
2. Create `SC_Geiger` as a **child of `SC_Ambience`**.
3. Create `SMX_Ambience` (a `SoundSubmix`), with its parent set to the master submix.
4. Set the classes on the sounds:
   - every Ambience2 SoundWave: `SoundClassObject = SC_Ambience`;
   - the `SFX_Geiger_*` waves: `SoundClassObject = SC_Geiger`;
   - all of them: submix `SMX_Ambience`.
   The director also sets the class as an override on every voice it creates, from `DA_Ambience`.
5. **The duck:**
   - With `SMX_Ambience` loaded, the director ducks the submix output by -8 dB (0.3 s in, 1.5 s out) under
     story lines and forced radio lines.
   - Without it, the director ducks each of its own voices by the same amount. No SoundMix is needed either way.
   - The Geiger takes a further -2 dB.
6. Optional concurrency: `SCON_Ambience2` (max 24, Stop Quietest) and `SCON_GeigerClick` (max 2, Stop Oldest).
   The director already enforces its own 22-voice budget and plays the clicks on 2 alternating
   components, so these are a backstop only.

## 3. Build DA_Ambience

Create `/Game/SaskartaGaea/Audio/Ambience2/DA_Ambience` (class `SaskartaAmbienceAsset`), import the manifest
into it, and save it:

```python
import unreal
path = '/Game/SaskartaGaea/Audio/Ambience2/DA_Ambience'
asset = unreal.EditorAssetLibrary.load_asset(path)
if asset is None:
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    asset = tools.create_asset('DA_Ambience', '/Game/SaskartaGaea/Audio/Ambience2', unreal.SaskartaAmbienceAsset, None)
ok, report = unreal.SaskartaAmbienceImport.import_ambience_from_manifest(asset, '')
print(ok, report)
unreal.EditorAssetLibrary.save_loaded_asset(asset)
```

The report should read: files 150, zones 6, pools 24 (+ the 16 Geiger clicks), spots 18, dose points 21, rate
loops 4, chirps 3, storm beds 2, and no "not in the file list".

The brief's placement rules are applied by `USaskartaAmbienceImport::ApplyBriefRules`, so re-importing a
regenerated manifest keeps them. They cover:

- the pools' distances, arcs and storm gates;
- the local pools and their emitters;
- the zone wind multipliers (1 / 1 / 0.9 / 0.8 / 0.4 / 0.15) and the Cloud's 0.8 dose washout;
- the bed rules (grass -6 dB on the ridge, insects × (1 - I/0.7) and off after 1,700 m, rock whistle × I,
  sand hiss × I², sand on metal × max(0, I - 0.5) × 2).

## 4. Spot emitters

The director activates each spot by proximity: it turns on within 105 % of `inner + falloff` and off beyond
120 %. It takes a **placed `AmbientSound` tagged with the spot's label** if one exists. Otherwise it creates its own
3D component at the manifest position, so placing them is optional but recommended (visible in the level,
tweakable).

Place one `AmbientSound` per row of the manifest's `placement` that has a loop (17 rows; `A2_WW_GateCreak` is
a pool anchor only):

- Label and **Actor Tag**: the label (`A2_PF_MetalCreak`, …). The tag is what the director looks for.
- Location: the manifest's `x, y, z` (UE world cm).
- Sound: the row's `asset`. **Auto Activate: off**, because the director starts and stops it. Leave the
  volume at 1, because the director sets the row's `volume_db`.
- Attenuation override:
  - Sphere, inner radius = `inner_radius_m`, falloff = `falloff_m`;
  - Natural Sound;
  - Air Absorption on;
  - Non-Spatialized Radius = the inner radius.
- The WATER OPTION rows (`A2_WW_Trickle`, `A2_WW_SluiceDrip`, `A2_HP_Lapping`) stay silent until the author sets
  the director's `bWaitingWaterHasWater`. The default is false, per B05 and V4.

The placement script's shape, 4 per call:

```python
import unreal
rows = [('A2_PF_MetalCreak', '/Game/SaskartaGaea/Audio/Ambience2/AMB_Platform_MetalCreak_Loop', (439856, 334550, -41016), 6, 55)]
for label, snd, xyz, inner, falloff in rows:
    a = unreal.EditorLevelLibrary.spawn_actor_from_class(unreal.AmbientSound, unreal.Vector(*xyz))
    a.set_actor_label(label)
    a.tags = [label]
    c = a.get_editor_property('audio_component')
    c.set_editor_property('sound', unreal.EditorAssetLibrary.load_asset(snd))
    c.set_editor_property('auto_activate', False)
    c.set_editor_property('override_attenuation', True)
    s = c.get_editor_property('attenuation_overrides')
    s.set_editor_property('attenuation_shape_extents', unreal.Vector(inner * 100, 0, 0))
    s.set_editor_property('falloff_distance', falloff * 100)
    s.set_editor_property('distance_algorithm', unreal.AttenuationDistanceModel.NATURAL_SOUND)
    s.set_editor_property('attenuate_with_lpf', True)
    s.set_editor_property('non_spatialized_radius_start', inner * 100)
    c.set_editor_property('attenuation_overrides', s)
```

These actors go in the World Partition level, so follow the WP load / save / unload rules (separate calls,
saves in chunks). If a spot actor is streamed out while it plays, the director releases it and picks it up
again on the next approach.

## 5. The old beds

Following the brief's section 1, lower `AMB_Valley_Wind`, `AMB_Cloud_Wind` and `AMB_Summit_Wind` by 4 dB, because the
storm wind beds carry the wind now. Leave `AMB_Mountain_Rumble`, `AMB_Thunder_Far_Loop` and the `GEI_*`
AmbientSounds as they are.

- The director reserves 3 voices for them (`ReservedExternalVoices`), so its own share is 19 of the 22.
- Once the new Geiger is confirmed in play, remove the `GEI_*` AmbientSounds and set
  `ReservedExternalVoices` to 2.

## 6. Settings

- **Ambience volume.** This is the existing "Ambience" slider (`USaskartaGameUserSettings::AmbienceVolume`,
  already on `WBP_Saskarta_Settings`). The director multiplies every voice by it, and
  `USaskartaAmbienceSettings::Get/SetAmbienceVolume` wrap it.
- **Geiger counter on/off and volume.** Use `USaskartaAmbienceSettings::SetGeigerCounter(bool)` and
  `SetGeigerVolume(float)`. They are saved to `GameUserSettings.ini`, with the cvar mirrors `saskarta.geiger` and
  `saskarta.volume.geiger`.
  - Add a toggle row to the settings widget when convenient.
  - Turning the counter off plays the switch-off click, then silences the clicks. The dose is still
    computed for the HUD.

## 7. The HUD hook (optional, later)

- `USaskartaAmbienceDirector::GetAmbienceDirector(WorldContext)->GetDose()` returns counts/s.
- `OnDoseSpike(Dose, Cause)` fires as a gust, a dust wall or a close strike begins.
- `OnGust(Intensity, DurationS)` can drive the fog pulse (the STORM brief's ±20 % over 6–10 s).

## 8. Checks (only if the user asks for a PIE pass)

1. Run `Automation RunTests Saskarta.Ambience`. There are 10 tests, and `ManifestFile` reads the real manifest.
2. In PIE:
   - `Saskarta.Ambience.Dump` shows the road metre, the zone weights, the dose, the beds and the voices.
   - `Saskarta.Ambience.Road <m>`, `Saskarta.Ambience.Storm <0-1>`, `Saskarta.Ambience.Gust` and
     `Saskarta.Ambience.Geiger 0|1` drive it without walking.
3. Listen at 0, 1,220, 2,480, 2,580, 3,050, 3,400, 3,700, 4,350 and 4,600 m (`Saskarta.Events.GoTo`), and
   check these things:
   - no thunder before 1,000 m (Act I);
   - the Geiger switches on at the boot, off at the collapse, and on again at the human handover;
   - the chirp sounds near the platform (the dose rises through 6 cps);
   - `stat soundwaves` shows at most 22 voices at the platform during a gust with lightning;
   - the WATER OPTION emitters stay silent.

## Tuning left to the author

- `MinClickRateCps` on the director defaults to **0.3 cps** (the brief's "near silence above the clouds" table
  value; set 2026-09-28, source only until the next build). The pure logic's default stays 1/s (the task's range, 1–80/s).
- `bWaitingWaterHasWater` (default false), `ActIEndRoadM` (1,000), `DuckDb` (-8), `GeigerPan` (-0.35),
  `ChirpThresholdCps` (6) and `ChirpCooldownS` (20) are all `BlueprintReadWrite` on the director.
- The optional `CV_RADIATION_01` carrier line (brief section 6) is not wired. It is a proposal only, and no
  line is recorded.
