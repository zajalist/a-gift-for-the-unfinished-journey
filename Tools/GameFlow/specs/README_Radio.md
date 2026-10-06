# The radio (the Low Voice): player-facing layer (LANE5)

The station's scheduling, reception and ducking are C++ (`USaskartaRadioStation`, `DA_Station`,
`docs/story/station.json`, STATION.md). This lane adds three things:
- a radio that **mostly always plays**;
- an on/off toggle the player can reach;
- a small diegetic panel.

It also queues the zone-aware C++.

Subtitle presentation (2026-09-28): song parts clear the station subtitle and emit
no replacement text. This also clears the intro caption when music enters under
it; the audio overlap remains. Spoken parts keep their subtitles, and song titles
remain available through the station API and in the credits.

Radio presentation (2026-09-28): a 304 × 104 terminal tuner sits 36 px from the
right and bottom at 1080p. All lettering uses Font_Terminal; the frequency scale,
thin signal meter and power state share restrained amber phosphor. The soft
screen scrim sits outside `RadioScreen`, whose RetainerBox uses
`MI_UI_RadioCRT` / texture parameter `Texture`. Its parent is the existing boot
terminal shader; the radio instance disables rolling bands, jitter, curvature,
flicker and raster fill. It renders on invalidation, not on every phase.

Rebuild only this widget while PIE is stopped: run
`ending_editor.py run-file Tools/GameFlow/editor/radio_crt.py`, build
`WBP_Saskarta_Radio.tree.json` with `build_settings_ui.mjs --clear`, then run
`ending_editor.py run-file Tools/GameFlow/editor/radio_crt_finish.py`. The finish
step sets the existing Configure call's key icon to 20 px while preserving the
three station delegate bindings. Save scope is the radio widget and its MI.
The 2026-09-29 install compiled and saved successfully. The standalone capture
`Saved/Screenshots/RadioCRT/standalone-live.png` shows the effect rendering in
game; it also exposed old `TextOn`/`TextOff` asset defaults duplicating the key
prompt. The finish script reset those defaults in the saved widget on 2026-09-29;
the next standalone playtest should confirm the prompt visually.

## What the player gets now (data + Blueprint, no build needed)

- **Always on.** `station.json` → `DA_Station`:

  | Setting | Now | Was |
  |---|---|---|
  | `gap_s` | 4–12 s of the static bed | 45–120 s |
  | `first_segment_delay_s` | 3–8 s | 20–40 s |
  | story lookahead | 12 s | 25 s |
  | fit margin | 2 s | 3 s |
  | hold-off after a story line | 3 s | 6 s |
  | after an idle tape | 8–15 s | 20–40 s |

  - A story line still ducks the station −12 dB and then fades it.
  - A cinematic still suspends it.
  - The station comes on at B02 (road 150 m) as before. With the queued C++ it comes on as soon as the
    carrier is Playing (`start_road_m` 0).
- **Reception tells the journey** (`reception.quality_by_road_m`, tunable in DA_Station → Config → Reception):

  | Stretch (road m) | Signal q |
  |---|---|
  | Valley (0–1,550) | 1.0 → 0.9 |
  | The ridge top (1,980) clears | 0.95 |
  | Behind the ridge, down into the basin | 0.55 → 0.7 |
  | The dry cistern (3,030–3,080) | 0.3: crackle and dropouts |
  | The waystation | 0.62 |
  | The Long Stair / Knees (3,560–4,015) | 0.25–0.35, drifting |
  | The cloud (4,250–4,450) | 0.1–0.18 |
  | Toward the summit (4,790) | 0 |

  - Low q gives:
    - a narrower band (low-pass to 1.9 kHz);
    - quieter voice (−10 dB at q 0.25);
    - a louder static bed (−9 dB between items);
    - more and longer dropouts (up to 0.5/s, 120–700 ms, the voice −26 dB, static +9 dB).
  - Below q 0.25 the current C++ holds the q = 0.25 sound. The fade to nothing (the cloud and the
    summit) is in the queued C++.
- **On/off: `R` on the keyboard, D-pad up on a gamepad.**
  - It flips the existing setting `USaskartaStorySettings.SetRadioStation` (saved in
    GameUserSettings, mirrored in `saskarta.radio`; the Settings → Audio "Radio station" row is the same switch).
  - Off: a knob click and a power-off collapse (the RADIOFX set). The station fades out within 1 s.
  - On: a knob click and a power-on bloom, then the station's own tune sweep and the next segment 3–8 s later.
  - It works only in FlowState Playing.
- **The panel** (`WBP_Saskarta_Radio`, bottom right, small; terminal font) shows:
  - the dial: `Low Voice  94.3`;
  - a signal meter (the station's reception q; empty when off);
  - what is on: `on air` / `static . . .` / `no signal`. The item title, "Weather" or "Song · Hayaa", comes with the queued C++;
  - the state: `ON (R)` / `OFF (R)`.

  It shows for 4 s after a toggle or a change (on air ↔ static, on ↔ off), and stays while R is held. It fades
  out otherwise, and it is hidden outside FlowState Playing. The runner's subtitle events carry the
  station's speech lines (English, and Saskartan above when the setting is on).
- **Wiring:** `BP_Saskarta_HUD` (GM_Saskarta's HUD class) creates the panel at BeginPlay.

## Unique content (for the user)

There are 179 segments with takes in the editor (61 in the first batch, 118 in the second), plus 1 song.
The durations come from the selected WAVs.

| What | Length |
|---|---|
| Everyday segments (NOTICE, TALK, LETTER, KITCHEN, WEATHER, DEDIC) | 14.1 min |
| IDs and song links | 3.7 min |
| **ZONE** segments: the host talks about the ground being crossed, 9 zones | **17.0 min** |
| FRAG lines (the station breaking up in the cloud) | 0.4 min |
| Song ("Hayaa") | 1.4 min |
| **Total** | **36.6 min** |

**What plays today, before the C++ build:**
- The current C++ draws only categories listed in `category_weights`, so today's station plays the
  everyday segments, IDs and song blocks: about **18 minutes of unique voice**.
- The ZONE and FRAG lines play only once the queued patch is built (it adds the zone bags and the fragments rule).
- After that build, a 22–40 min drive hears about 35 minutes of unique material, and the zone lines
  follow the road. Repeats become rare.

## Queued C++ (next closed-editor build)

The patch is `Tools/GameFlow/cpp_queue/lane5_radio/lane5_radio.patch`. It applies cleanly today:

```bash
cd Plugins/SaskartaCore/Source/SaskartaCore && git apply -p1 ../../../../Tools/GameFlow/cpp_queue/lane5_radio/lane5_radio.patch
```

- **Zones.**
  - `FSaskartaStationZone` and `Config.Zones` (from `reception.zones`);
  - `FSaskartaStationSegment::Zone` (from the segment's `zone` or `tags.zone`);
  - zone-tagged segments get their own bag `ZONE_<name>`, and a non-ID slot tries the current zone's bag first
    with `zone_segment_chance` (0.6);
  - `USaskartaRadioStation::GetCurrentZone()` / `GetCurrentZoneLabel()`.
- **Below q 0.25:**
  - the voice keeps fading to `voice_gain_db_at_q0` (−40 dB): fragments in the static;
  - the static bed rises to `static_between_db_at_q0` (−6 dB);
  - at q 0 the Low Voice is gone (the summit).
- **Lightning:**
  - the station binds `USaskartaLightingDirector::OnLightningStrike`;
  - a strike plays `StaticIn` at `lightning_burst_db` (−8 dB close, −14 far) and buries the voice for 0.3–0.6 s.
- **The panel:**
  - `GetCurrentItemTitle()`, the category label ("Weather", "Letters", from `scheduler.category_labels`),
    or "Song · Title" during a song;
  - after the build, add it to `WBP_Saskarta_Radio`'s NowText (gen_radio_specs.py).
- **Start:** `station_on.start_road_m` (0) replaces the hard-coded 400 m.

Not in the patch yet (next steps, design):
- **Tuning.** Left/right on the dial, with the sweep between:
  - channel 1 is the **High Voice relay**: static with faint carrier tones, then later the Keeper's archive;
  - channel 2 is a dead numbers-style channel, static only.
  - Near the summit the dial auto-drifts to the relay as the Low Voice fades.
  - It needs relay beds from the audio lane (`Saved/GameAudio/Radio/`, task RADIOFX) and a channel index on the station.
- **Terrain / dust occlusion:**
  - a line trace from the carrier to the valley transmitter, and a dust-wall volume overlap;
  - both multiply q. At the moment q comes from road m only.
- **The archive submix chain scaled by q** (`SetSubmixEffectChainOverride` with a q-driven band-pass and noise).
  The chain exists as data (`DA_Station.ArchiveFilterChain`) but has no presets yet.

## The live show (RADIOSHOW; C++ in source, next closed-editor build)

`station.json` says `scheduler.mode: "show"`: the Low Voice is one continuous live show keyed to the road
(`docs/story/RADIO_SHOW.md`). The C++ is in `Plugins/SaskartaCore` (`SaskartaShowScheduler.h/.cpp`, the station,
the importer, the save) and compiles on a copy. **It is not built in the project yet.** Until the build, the
station keeps playing the shuffle loop.

**What it does after the build.**
- Five acts by the high-water road m, each with an ordered backbone:
  - a MUST item (`must` 1) is dropped only when the road is more than 250 m past its act;
  - a `must` 2 item is never dropped (the premise, the names, the last song, the hand-over, the last line);
  - a fast drive skips an optional item as soon as a later MUST of the act is due.
- Nothing stays silent for more than 3 s. When nothing is due, the order is:
  1. a FILL;
  2. a LINGER line (no talk line repeats within 20 min);
  3. a song with the act's links;
  4. a room murmur every 45–90 s.
- Song slots (Acts I–III) talk over the song: the song starts under the intro's last 2 s at −10 dB, and the
  outro starts 1.5 s before the song ends.
- The REACT_* layer ("the signal knows"):
  - per-event probability and cooldown, a 75 s global cooldown, a limit per act;
  - each line plays at most once per run, and only in its act range;
  - LIGHTNING reactions start in Act II (the author's decision).
- Story lines interrupt the show as before, and the show resumes:
  - an item heard under half goes back to the front;
  - a cut song resumes from its position;
  - after B11 and B15 the tied AFTER_TAPE line comes first.
- The sign-off: once B15's line has ended, `SHOW_A5_04` + `SHOW_A5_05` always end before the collapse (4,790 m).
  After the last line:
  1. 1.5 s of static, then it dies over 4 s, and the station is off for good;
  2. the author's last song (`show.last_song.song`, empty for now) plays as the signal dies;
  3. the title song (eyetae) fades in for the end card and keeps playing until `StopEndMusic`.
- **Loading is asynchronous only:**
  - `DA_Station`, the filter chain and the static sounds are loaded through the streamable manager;
  - a prefetch window stays loaded: the next backbone items, every MUST left in the act, the next act's
    opening, a planned fill and linger line, the song block when near, and the act's reaction takes;
  - played items are released after 4 s, with at most 64 resident;
  - a take that is not loaded in time waits at most 1.5 s, then plays as a subtitle only.
- Pause and save:
  - the pause menu pauses every station sound;
  - the checkpoint saves the show (act, played backbone, used pools with their ages, cooldowns, the song
    position);
  - Continue resumes the arc with a fill.

**Post-build steps (editor, no PIE; in this order).**
1. **Build** with the editor closed: `Build.bat UnrealEditor Win64 Development -Project=...saskartarad.uproject`.
   Then run `Automation RunTests Saskarta.Station` (the `Saskarta.Station.Show.*` tests are new).
2. **Re-import `DA_Station`** (`unreal.SaskartaStationImport.import_station_from_files`) and save it. It gains
   the show block and the segments' show fields. Until then the transient import covers PIE in the editor only.
3. **Import the 206 show takes** (`Saved/RadioRecordings/selected/<ID>.wav` →
   `/Game/SaskartaGaea/Audio/Station/Host/VO_Station_<ID>`) with the existing host-take script. Until then each
   show line plays as a subtitle only, for its `target_s`.
4. **The reaction sources:**

| Event | Source | Hookup |
|---|---|---|
| `LIGHTNING` | the lighting director's `OnLightningStrike` | none (C++ binds it) |
| `DROPOUT` | the station's own `OnRadioGlitch`, a Dropout of 0.3 s or more | none (C++) |
| `STORM_UP` | `GetStormIntensityForRadio()` up 0.15 in 20 s | none (C++) |
| `AFTER_TAPE` | the runner's story line end (`OnStoryLine` + `OnStoryBusyChanged`), `OnBeatFinished` | none (C++) |
| `SILENCE` | the station's own dead air, 6 s or more | none (C++) |
| `STOPPED` | no road progress for 20 s | none (C++) |
| `PASSING_POI` | the road passes a ruin's `road_m` (9 POIs in `show.reactions.poi`) | none. Optional: an event volume may call `NotifyPassingPoi(Zone)` |
| `RADIO_BACK_ON` | `SetRadioOn(true)` after 10 s or more off | none (the R toggle already calls it) |
| `OFFROAD` | the carrier tether | **BPC_RoadTether**: where it plays `CV_WARN_01`, add `GetRadioStation(self)` → `NotifyOffroad()` |
| `RESUMED` | the pause menu | **the pause menu (P3)**: on open `GetRadioStation(self)` → `NotifyPaused(true)`; on close `NotifyPaused(false)` |

5. **Save hooks:** none needed. The runner's `SaveCheckpoint` / `RestoreFromSave` broadcast
   `USaskartaSaveGame::OnWritingRun` / `OnRestoredRun` (two lines added in the runner). The station writes
   and reads `ShowState` itself.
6. **The end card (optional):** bind `OnShowEnd(Phase)`, which fires with `SignalDeath`, `LastSong` and
   `TitleSong`. Call `StopEndMusic(FadeS)` when the credits end or on quit to title. `StartTitleSongTransition()`
   starts the title song early if the end card needs it.
7. **The panel:** `WBP_Saskarta_Radio` already binds `GetCurrentItemTitle()`. In show mode it reads
   `Live · Act II` (`Song · Title` during a song).
8. **The last song:** when the author supplies it, import it (for example `SONG_last` in the Songs folder),
   set `show.last_song.song` to `last` (or a full object path), then re-import `DA_Station`. It never enters
   the shelf's song bag. A shelf song id (hayaa, malak, weli) is refused.

**Debug (console).**
- `Saskarta.Station.Debug` shows the act, the next backbone item and its `at_m`, the pools left, and the
  reaction cooldowns.
- `Saskarta.Station.Next` starts the next item now.
- `Saskarta.Station.React <EVENT> [close]` fires a reaction event.
- `Saskarta.Station.ShowDryRun <speed_mps> [stop_at_m stop_s] [seed]` prints a whole simulated drive.

**What to test in PIE after the build.**
1. From B02 the show starts within 1.5–3 s with `SHOW_A1_01`, and never goes silent for more than 3 s.
2. Stop the carrier for a few minutes. You hear Act I's fills and linger lines, no repeats, a STOPPED line
   (sometimes), then songs, then room murmurs.
3. Press Esc for more than 15 s, then resume. The station was paused mid-word; a RESUMED line is possible.
4. Run `Saskarta.Station.React LIGHTNING close` in Act I: nothing. In Act IV: an Act IV line.
5. Save at `CP2_WAYSTATION`, quit, and Continue. The show resumes in Act IV with a fill; no Act I–III item repeats.

## Assets

- **Imported:** the RADIOFX set, 36 files, to `/Game/SaskartaGaea/Audio/Radio/` (`Tools/GameFlow/editor/import_radio_fx.py`; the `*_Loop` beds loop).
- **On/off sounds on the panel:** `SFX_Radio_Knob_On_01` + `SFX_Radio_Power_On_Bloom`, and `SFX_Radio_Knob_Off_01` + `SFX_Radio_Power_Off_Collapse`.
- **Not yet wired:**
  - the layered beds of the RADIOFX brief (soft, weak and heavy static, crackle, the studio room between segments);
  - the relay and dead channels.
  
  Both need the station C++ (the next patch after `lane5_radio.patch`). `DA_Station` still uses the old single static bed.

## What to test in PIE

1. Drive past 150 m. The station comes on (tune sweep) and a segment starts within about 8 s.
   Between segments you hear 4–12 s of static, then the next one.
2. Press R. You hear a click and a static burst, and the station fades out. The panel shows `OFF (R)` and fades after 4 s.
3. Press R again. Click, static, then the tune sweep and a segment. The panel shows `ON (R)`, `on air`.
4. Quit and restart. The on/off state is kept. The Settings → Audio "Radio station" row matches.
5. Use the debug menu (F9) to teleport to `B10_DRY_CISTERN`. The voice narrows and crackles, and the meter drops.
   Teleport to 4,300 m (`SaskartaTP 4300`): it is mostly static.
6. A story line (B02, B05) ducks the station; CIN_06 suspends it.
