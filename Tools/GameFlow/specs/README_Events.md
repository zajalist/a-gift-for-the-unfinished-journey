# Story event runner and Low Voice station: editor-lane steps

C++ in `Plugins/SaskartaCore` (task EVENTS phase 1 + RADIOSYS part 2). Design: `docs/story/EVENTS.md`,
`docs/story/CINEMATICS.md`, `docs/story/STATION.md`. Everything below happens **after** the plugin is
built with the editor closed.

| Class | Kind | What it does |
|---|---|---|
| `USaskartaEventRunner` | World subsystem | Loads `DA_Saskarta_Story`, polls road m (0.25 s), takes flow reports and volumes, runs beats from a priority queue: lines on an exclusive Voice channel, cinematics, captions, subtitles, glances, prompts, look/fog requests, hooks, checkpoints |
| `USaskartaEventLibrary` | BP function library | Static wrappers for Blueprint (`ReportFlow`, `FireBeat`, `IsCinematicActive`, `IsVoiceBusy`, `SkipCurrentCinematic`, `PauseCinematic`, `StopAll`, `SaveCheckpoint`, `RestoreFromSave`) |
| `ASaskartaEventVolume` | Actor | Box trigger with `TriggerId` for `Volume` beats |
| `USaskartaSaveGame` | SaveGame | Slots `Saskarta_Run` and `Saskarta_Profile` |
| `USaskartaStoryAsset` / `USaskartaStoryImport` | DataAsset / importer | `DA_Saskarta_Story` from `docs/story/*.json` + the TSV |
| `USaskartaRadioStation` | World subsystem | The Low Voice scheduler (segments, gaps, IDs, song blocks, reception, story gate, ducking) |
| `USaskartaStationAsset` / `USaskartaStationImport` | DataAsset / importer | `DA_Station` from `docs/story/station.json`, plus the archive-filter submix chain |
| `USaskartaStorySettings` | Config object (GameUserSettings ini) | `bRadioStation`, `StationVolume`, `bShowSaskartan`, with cvar mirrors |

No Blueprint Tick anywhere: every clock is an `FTimerHandle`.

## 0. Build (editor closed)

```powershell
cmd /c start "" /belownormal /wait "C:\Program Files\Epic Games\UE_5.8\Engine\Build\BatchFiles\Build.bat" UnrealEditor Win64 Development -Project="D:\UnrealEngine\saskartarad\saskartarad.uproject" -WaitMutex -NoHotReloadFromIDE
```

Then open the editor and run the tests (Session Frontend, or the console):

```
Automation RunTests Saskarta.Events
Automation RunTests Saskarta.Station
```

`LogSaskartaEvents` and `LogSaskartaStation` appear once a game world starts.

## 1. The data assets

Packaging choice: the JSON lives in `docs/`, which is not staged, so both are baked into DataAssets that
cook normally. The parsing is C++ (tested), so the editor step is two calls. In editor builds only, a
missing asset falls back to a transient import straight from `docs/story/`, so PIE works before this step
(a warning says so). A packaged build without the assets has an idle runner and a silent station.

```python
import unreal
at = unreal.AssetToolsHelpers.get_asset_tools()
eal = unreal.EditorAssetLibrary
proj = unreal.Paths.project_dir()

def data_asset(folder, name, cls):
    path = f'{folder}/{name}'
    if eal.does_asset_exist(path):
        return unreal.load_asset(path)
    f = unreal.DataAssetFactory()
    f.set_editor_property('data_asset_class', cls)
    return at.create_asset(name, folder, cls, f)

story = data_asset('/Game/SaskartaGaea/Story', 'DA_Saskarta_Story', unreal.SaskartaStoryAsset)
ok, report = unreal.SaskartaStoryImport.import_story_from_files(story, proj)
print(ok, report)          # counts plus every problem (missing TSV rows, cue past duration)

station = data_asset('/Game/SaskartaGaea/Audio/Station', 'DA_Station', unreal.SaskartaStationAsset)
ok, report = unreal.SaskartaStationImport.import_station_from_files(station, proj)
print(ok, report)

for a in (story, station):  # check IsReadOnly first (committed uassets are LFS-locked)
    unreal.EditorAssetLibrary.save_loaded_asset(a, only_if_is_dirty=False)
```

Re-run the import whenever `story-events.json`, the TSV, `carrier-voice-lines.json`,
`Saved/RadioRecordings/durations.json` or `station.json` change. `EnabledTags` (optional scenes) and
`bDriveLightingRoadProgress` on `DA_Saskarta_Story` are hand-set and survive a re-import.

Line sounds are expected at `/Game/SaskartaGaea/Audio/Lines/<LineId>`; if a line is elsewhere under
`/Game/SaskartaGaea/Audio`, the runner finds it by asset name. A line with no sound yet still shows its
subtitle and holds the Voice channel for its TSV duration.

## 2. The road spline

The runner finds the road the way the tether does: the first actor whose class name starts with
`BP_Saskarta_Road` (or any actor tagged `Saskarta.Road`), and its first `SplineComponent`. It retries every
5 s, so a streamed-in road is picked up late. Check it in PIE with `Saskarta.Events.Dump`: the first line
shows road m, UE m and the high-water mark.

- Road m comes from UE m through `RoadMToUeM` (the 102 `road-profile.json` samples); every beat matches
  its documented road m to within 1 m (test `Saskarta.Events.RealData.RoadProfile`).
- The first poll only sets the high-water mark, so starting PIE mid-road never fires the beats behind.
- The tether keeps calling `SetRoadProgress`; leave `bDriveLightingRoadProgress` off unless the tether stops.

## 3. PC_Saskarta wiring (small bpgraph edits)

| Where | Call |
|---|---|
| `HandleVisionOnline`, first boot (`FlowState == Booting`) | `SaskartaEventLibrary.ReportFlow(FirstBootVisionOnline)` **instead of** `TryGround`/`EnterPlaying`. CIN_01's final state calls `EnterPlaying` on the PC at the hand-back |
| `HandleVisionOnline`, reboot | unchanged, plus `ReportFlow(RebootVisionOnline)` (plays `CV_REBOOT_04`, re-queues a beat a breach cut off) |
| `HandleZoneChanged` Safe → Warning | `ReportFlow(TetherWarning)` (W01_WARN, repeatable, 8 s cooldown) |
| `HandleBlackout`, Collapsing branch | `ReportFlow(Collapsing)` (B18, Critical) |
| `QuitToTitle` | `StopAll` first (no spawnable camera survives into `BeginTitle`) |
| Pause menu | `PauseCinematic(true/false)`; show "Skip scene" when `CanSkipCinematic`, calling `SkipCurrentCinematic` |
| Optional | a no-parameter `OnFlowStateSetByRunner` event (called after `SetFlowState` actions); a `RestoreFlow(Name)` function for checkpoint restores |

Hooks the data calls by name (no parameters; a missing one is logged and skipped, never a crash):
`PlayStart`, `StopAnimDriver`, `StartAnimDriver` on the carrier (`Pawn`); `EnterPlaying`,
`SetGeigerSample(Name)` on the PC. `FlowState` must stay a **Name** variable on `PC_Saskarta` (read and
written by reflection).

## 4. Subtitle, caption and letterbox widgets

Bind in the widget's `Construct` (not Tick): `Get Event Runner` → bind each event. All are
`BlueprintAssignable` on `USaskartaEventRunner`.

| Event | Payload | Widget |
|---|---|---|
| `OnSubtitleShow` | `FSaskartaSubtitle`: `English` (prefix `CARRIER: ` or `RADIO · ` already applied), `Saskartan` (empty unless the line is SKS **and** "Show original Saskartan" is on), `Header` (ARCHIVE nn · PLACE, show 4 s), `DurationS`, `bStation` | `SaskartanLine` small, 55 % opacity, Aref Ruqaa, **above** `EnglishLine` |
| `OnSubtitleHide` | `bStation` | clear the lines |
| `OnCaptionShow` / `OnCaptionHide` | `Text`, `Target` (`Hud` → the top-left monospace `HudLine`; otherwise the plain caption), `DurationS` | |
| `OnPromptShow` / `OnPromptHide` | `Text` (`Release the inner latch.`, `Rise.`) | `PromptLine`, plain type, centred low |
| `OnLetterbox` | `bOn`, `BlendS` (0.6) | animate `LetterboxTop`/`Bottom` to 2.39:1 with a timer lerp |
| `OnSkipProgress` | 0..1 while Space / Gamepad Right is held | `SkipRing` fill |
| `OnEndCard` | `Title` or `Credits` | end card panel |

Precedence is handled in C++: a story subtitle replaces a station caption at once; a station caption never
replaces a story subtitle. The runner already respects the Accessibility subtitle toggle
(`USaskartaGameUserSettings.bSubtitles`). Add a row "Show original Saskartan" bound to
`SaskartaStorySettings.SetShowSaskartan` / `bShowSaskartan`.

Other events: `OnStoryBusyChanged` (the station binds it itself), `OnLookRequested` / `OnFogRequested`
(forwarded automatically to `USaskartaLightingDirector.PushLookOverride(Name, float)` /
`PopLookOverride(float)` / `PushFogOverride(float, float)` once those UFUNCTIONs exist; until then these
events are the hook), `OnModeChanged`, `OnGeigerSample`, `OnBeatStarted` / `OnBeatFinished`,
`OnCinematicStarted` / `OnCinematicFinished`.

## 5. LS_CIN_01_Directive (CINEMATICS.md section 1)

`/Game/SaskartaGaea/GameFlow/Cinematics/LS_CIN_01_Directive`, 42 s, 30 fps. CIN_01 has
`relative_to_pawn: false`: it plays at the PlayerStart with an identity origin, so key cameras in world
space around the PlayerStart (yaw −160). Road cinematics (`relative_to_pawn: true`) get
`TransformOrigin` = the pawn projected onto the spline, yawed along the direction of travel (toward
falling spline distance), at the height of the pawn's feet (`FSaskartaEventLogic::RoadCineOrigin`, 2026-09-28:
the spline's own z is a chord metres off the landscape between its points); key their cameras relative to that,
+Z up from the road surface.

- **Spawnable CineCameras only** (the level keeps exactly one CineCameraActor at BeginPlay).
- **The carrier** as a possessable bound by the tag `Saskarta.Carrier` (add the tag to
  `BP_Saskarta_Carrier`'s defaults). POV shots: a spawnable CineCamera attached to the carrier's
  `FollowCamera` socket at FOV 90 (≈ 12 mm on 23.76 mm).
- **Camera-cut track `bCanBlend = true`**; first section ease-in 0 (`blend_in_s`), last section
  **ease-out 2.0 s** (`blend_out_s`): that ease is the hand-back into the pawn camera. After a skip the
  runner blends with `SetViewTargetWithBlend(Pawn, 2.0)` instead.
- **Do not key audio or voice in the sequence**: the runner plays every line and SFX from the cues in
  `story-events.json` against the sequence's own clock (pause-safe). Do not key the letterbox (the
  `ShowLetterbox` cue at 3.0 s does it). Key only cameras, the MPC scan track and the carrier's animation.
- **MPC track** `MPC_Saskarta_Scan`: `ScanAmount` 0 → 1 over 0.5 s from 8.0, → 0 over 1.5 s from 24.5;
  `ScanBarY` sweeping at 0.8 Hz during shot 3; `LockUV`/`LockSize` from `build_cinematics.py check`;
  `LockAmount` → 1 at 18.3.

| Shot | t (s) | Camera | Move |
|---|---|---|---|
| 1 | 0–3 | POV | pitch −25 → −12, FOV 90, no letterbox |
| 2 EXT | 3–8 | 3.5 m ahead-left, 60 cm up | 28 mm f/2.8, push-in 0.5 m (the `PlayStart` hook fires at 3.2) |
| 3 | 8–16 | POV | yaw −160 → −115 (3 s ease), hold 0.6, → −200 (3.4 s), hold 1 |
| 4 | 16–26 | POV | yaw → −177, pitch +9.5; stepped zoom 90 → 45 → 22 → 12° with 0.15 s jumps at 17.0/18.0/19.0 |
| 5 EXT | 26–34 | crane behind the capsule, 2 → 14 m up, 6 m forward | 24 → 35 mm, tilt −5 → −12, yaw −155 |
| 6 EXT | 34–39 | 60 m back along the road (yaw ≈ −170), 3 m up | 135 mm f/5.6, locked, 1° drift |
| 7 | 39–42 | blend to POV | ends at yaw −160, pitch −5 (the B01 frame) |

The runner already handles: input lock, `StopAnimDriver`/`StartAnimDriver`, letterbox, the cue lines
(`CV_DIRECTIVE_01`, `CV_SCAN_01/02`, `CV_DETECT_01/02`, `CV_BOOT_04`, `CV_DIRECTIVE_02`, `CV_HANDOFF_01`
kept on skip), the HUD captions, `SetLook Valley`, `SetFog 0.6`, the final state (control rotation
(−5, −160), fog back to 1.0, `EnterPlaying`, the first-playthrough controls caption, `CP0_DOCK`) and
`HoldAlways` skip. The first-boot route can now be skipped; the cinematic's `FinalState` still runs,
including `EnterPlaying`, its handoff caption and `CP0_DOCK`. Before the sequence exists, CIN_01 runs its cues on the world clock for 42 s and
still hands back.

## 6. The station in the settings and the mix

- **Settings rows** (Audio tab, under Voice volume): "Radio station" → `SaskartaStorySettings.SetRadioStation(bool)`,
  "Station volume" → `SetStationVolume(float 0..1)`; read the current values from
  `Get Saskarta Story Settings` → `bRadioStation` / `StationVolume`. Each setter saves the
  GameUserSettings ini (section `[/Script/SaskartaCore.SaskartaStorySettings]`) and updates the mirrors
  `saskarta.radio`, `saskarta.volume.station`, `saskarta.subtitles.saskartan`. The station polls the
  setting every 0.25 s; switching it off mid-segment fades it out over 1 s.
- **Sound classes** under `/Game/SaskartaGaea/Audio/Classes/`: `SC_Story`, `SC_Carrier`, `SC_Station`
  (child of **Master**, not Voice), `SC_Idle`, `SC_Cine`, `SC_World`; and the mix `SCM_Saskarta_StoryDuck`
  (`SC_Station` and `SC_Idle` at −12 dB). The runner pushes/pops that mix while a story line or cinematic
  is busy, as a backstop; it is optional.
- **Archive filter:** create a submix `SMX_Station` and its effect presets (band-pass, saturation, hiss);
  set `DA_Station.StationSubmix` and `ArchiveFilterChain`. The station applies the chain with
  `SetSubmixEffectChainOverride` at BeginPlay (or call `SetArchiveFilter` at runtime). Set every station
  asset's Sound Submix to `SMX_Station` and Sound Class to `SC_Station` at import.
- **Takes:** host takes import to `/Game/SaskartaGaea/Audio/Station/Host/VO_Station_<id>` (TTS
  placeholders). **The user's recordings import to `.../Host/Recorded/VO_Station_<id>`**, and the station
  always prefers `Recorded/`. A named link pickup `VO_Station_<id>__<song_id>` beats the plain take for
  that song. Which is which comes from disk: a line is the user's when `Saved/RadioRecordings/raw/<id>_take*.wav`
  exists or `selected/<id>.wav` is not listed in `selected/_tts_manifest.json`. In PIE the station logs
  every user recording that is on disk but not yet imported under `Recorded/`.
- **Songs:** any `SONG_<id>` in `/Game/SaskartaGaea/Audio/Station/Songs` plus `station.json` `songs.files`
  (`hayaa`). Title and singer come from the sidecar at import time.

## 7. PIE checks for the user

1. Start → boot log → **CIN_01 plays** (log: `cinematic CIN_01_DIRECTIVE: begin`), lines and subtitles
   in order, letterbox from 3 s, HUD `RANGE 3,300 M` then `ÂLAAWB`.
2. Hand-back at the B01 frame (yaw −160): `CV_HANDOFF_01` heard, controls caption, drive and look work.
   `Saskarta_Run` saved (`checkpoint CP0_DOCK saved (ok)`).
3. Restart PIE: hold Space for 1 s during CIN_01 → it skips (ring fills), the final state runs,
   `CV_HANDOFF_01` still plays after the blend.
4. Drive to 150 m: `CV_ARCHIVE_01` then `RADIO_B02_01` with the small Saskartan line above the English.
   When B02 ends the station may come on: tune sweep, then the first segment after 20–40 s
   (`Saskarta.Station.Debug`; `Saskarta.Station.Next` to hurry it).
5. While a station segment plays, `Saskarta.Events.Fire B03_PROMISE`: the station ducks at once and fades
   within 1.3 s; the story line is clear; the station waits at least 6 s after it.
6. Reverse past a beat and drive on: it does not fire again. Leave the road to 10 m: `CV_WARN_01`, not
   more than once per 8 s.
7. Toggle "Radio station" off in settings mid-segment: it fades within 1 s and stays off.
8. `Saskarta.Events.DryRun` (5 m/s to 4,790 m) and `Saskarta.Station.DryRun 20` in the log.

Console: `Saskarta.Events.GoTo <roadm>`, `.Fire <BeatId>`, `.Dump`, `.Optional <tags>`, `.DryRun [mps] [end]`;
`Saskarta.Cine.Play <CinId>`, `Saskarta.Cine.AllowSkipAll 1`; `Saskarta.Station.Next`, `.Song`, `.Debug`,
`.DryRun [minutes] [seed]`.

## Not in this lane (follow-ups)

- `USaskartaCaptionWidget` (a C++ `BindWidget` base) was not written: the events above cover the same
  surface for a designer widget.
- `PushLookOverride` / `PopLookOverride` / `PushFogOverride` on the lighting director (a header change in
  another file).
- `build_story_asset.py` / `build_cinematics.py` / the CV TTS renders (brief 1A.3–1A.6).
