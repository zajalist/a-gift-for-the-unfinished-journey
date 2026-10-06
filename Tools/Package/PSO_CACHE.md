# Bundled PSO cache for the packaged Windows build (UE 5.8)

Goal: remove the "N PSO creation hitches ... 0 of them were precached" stutter the user feels on first
play. Written offline on 2026-09-28 and checked against the engine source in
`C:/Program Files/Epic Games/UE_5.8/Engine/Source` (file references below). Nothing here has been run:
no cook, no package, no recording yet.

`Tools/Perf/PSO.md` section 2 has the earlier outline. This file replaces it with verified paths and
names, and `Tools/Package/package_windows.ps1` automates the build steps.

## 1. Why only a cooked build fixes it

| Fact | Source |
|---|---|
| PSO precaching is hard-disabled in any `WITH_EDITOR` binary: `IsPSOPrecachingEnabled()` returns `false`. | `Runtime/RHI/Private/PipelineStateCache.cpp:4951` |
| The file cache defaults (`r.ShaderPipelineCache.Enabled`, `LogPSO`, `ReportPSO`) are `PIPELINE_CACHE_DEFAULT_ENABLED`, which is `!WITH_EDITOR`. | `Runtime/RHI/Public/PipelineFileCache.h:19` |

PIE and `UnrealEditor.exe -game` (`Tools/Perf/PlayStandalone.bat`) are both editor binaries, so they
never precache and never load a bundled cache. Every first draw compiles on the spot, and "0
precached" is expected there. Only the packaged exe runs the real path.

## 2. How the two layers work together in 5.8

1. **PSO precaching (runtime, on by default).** When components PostLoad, the engine requests every PSO
   they could need (`r.PSOPrecaching=1` in DefaultEngine, `r.PSOPrecache.Components` default 1,
   `r.PSOPrecache.GlobalShaders` default -1 = auto). This catches most material/mesh PSOs before first
   draw. It misses the PSOs that depend on runtime state: global/post-process passes, some Lumen,
   Nanite and VSM passes, and anything used before its component finished loading ("TooLate").
2. **Bundled pipeline cache (recorded).** A recording run logs every PSO actually bound, together with
   its precache result. At startup the shipped game opens the bundled cache and compiles it in
   batches (`r.ShaderPipelineCache.StartupMode=1` "Fast", `BatchSize` 50, `BatchTime` 16 ms).
   `r.ShaderPipelineCache.PSOPrecacheIncludeMode` (ReadOnly, default **2**) compiles only entries
   whose recorded result was *not* Complete (Missed, Untracked, TooLate), plus every global-shader
   PSO (`ShaderPipelineCache.cpp:1058`). So the bundled cache fills exactly the gaps that precaching
   leaves.
3. **The loading screen already waits for it.** `USaskartaReadiness` counts
   `FShaderPipelineCache::NumPrecompilesRemaining()` + `NumActivePrecacheRequests()`, so the first
   launch holds the loading screen (capped by `LoadMaxTime`, now 180 s) until the batches are done.
   The GPU driver's own disk cache then makes later launches fast.
4. **Per-player top-up.** In Shipping, `r.ShaderPipelineCache.SaveUserCache` defaults to on
   (`PIPELINE_CACHE_DEFAULT_ENABLED && UE_BUILD_SHIPPING`, `PipelineFileCache.cpp:160`). Each player's
   own misses are saved and precompiled on their next run.

`r.ShaderPipelineCache.ExcludePrecachePSO=1` (ReadOnly, `PipelineFileCache.cpp:135`) drops
successfully precached PSOs from the recording, which gives a smaller file. It is **optional**: with
include mode 2 those entries are skipped at runtime anyway. It is ReadOnly, so it only works from an
ini (see README, recommended lines).

## 3. The flow, with the real file names

| Step | What | Where (verified) |
|---|---|---|
| 0 | Stable shader keys must be on for the cook: `[DevOptions.Shaders] NeedsShaderStableKeys=true` (the Engine ini, or `Config/Windows/WindowsEngine.ini`). Until that line exists, the script passes `-ini:Engine:[DevOptions.Shaders]:NeedsShaderStableKeys=true`, which UAT forwards to the cooker. | `Editor/UnrealEd/Private/Cooker/ShaderLibraryCooking.cpp:262-279`; UAT `CookCommand.Automation.cs:110` (ConfigOverrideParams) |
| 0 | `bShareMaterialShaderCode=True` (the shader code library). Without it the cooker never runs the pipeline-cache step. **Already set** in `Config/DefaultGame.ini`. | `CookOnTheFlyServer.cpp:9790-9798` |
| 1 | **Recording build**: `package_windows.ps1 -LogPSO` (Development). The cook writes `ShaderStableInfo-saskartarad-PCD3D_SM6.shk` and `ShaderStableInfo-Global-PCD3D_SM6.shk` (plus SM5) under `Saved/Cooked/Windows/saskartarad/Metadata/PipelineCaches/`. The script copies them to `<archive>/_pso/keys/`, because each recording must be expanded with the keys from its own cook. | name pattern `ShaderStableInfo-<lib>-<format>.shk`: `ShaderCodeLibraryUtilities.cpp:38` |
| 2 | **Record**: run the packaged exe with `-logPSO` (`Record-PSO.bat` next to the archive). `-logPSO` forces `SaveBoundPSOLog` and also deletes the old user PSO cache. | `ShaderPipelineCache.cpp:209`, `PipelineFileCache.cpp:1880` |
| 2 | The recording is `<branch>-CL-<cl>-<name>_PCD3D_SM6_<guid>.rec.upipelinecache` in `FPaths::ProjectSavedDir()/CollectedPSOs`. For a **Development** package that is `<archive>/Windows/saskartarad/Saved/CollectedPSOs/`. A **Shipping** package counts as "installed" (`FApp::IsInstalled`), so its Saved dir is `%LOCALAPPDATA%/saskartarad/Saved/`. Record with Development. | `PipelineFileCache.cpp:2288-2290`; `Core/Private/Misc/App.cpp:218`, `Paths.cpp:460` |
| 2 | **When it is written**: on quit (`CloseUserPipelineFileCache`), when the window loses focus (Alt-Tab), or with the console command `r.ShaderPipelineCache.Save`. Autosave is disabled on purpose (`AutoSaveTimeBoundPSO` = MAX_int32, "the feature is broken"). A crash loses everything since the last save. | `ShaderPipelineCache.cpp:132-140, 664-673, 968-984` |
| 3 | **Expand**: `package_windows.ps1 -ExpandPSO -RecordingsDir ... -KeysDir ...` runs `UnrealEditor-Cmd saskartarad.uproject -run=ShaderPipelineCacheTools expand <*.rec.upipelinecache> <*PCD3D_SM6*.shk> <out>.spc`. The output must end in `.spc` (binary stable cache; `.stablepc.csv` is the deprecated text form). Check the log for `Loaded N PSOs total`. | `ShaderPipelineCacheToolsCommandlet.cpp:1110-1213, 2968` |
| 4 | The output goes to **`Build/Windows/PipelineCaches/saskartarad_PCD3D_SM6.spc`**. The cooker looks for `Build/<IniPlatform>/PipelineCaches/*<LibraryName>_<ShaderFormat>.spc` **recursively**. LibraryName is the project name. Don't keep backup `.spc` files anywhere under that folder: the script backs up to `Saved/PSO/backup/`. | `ShaderLibraryCooking.cpp:436-448`, `:367-380` |
| 5 | **Package again** (`-Config Development` or `Both`). At the end of the cook the cooker runs `ShaderPipelineCacheTools build` with the `.spc` and the new `.shk` files. It writes `Content/PipelineCaches/Windows/saskartarad_PCD3D_SM6.stable.upipelinecache` into the cooked output (staged inside the IoStore container) and copies it to `Metadata/PipelineCaches/` for inspection. Cook log: `---- Running UShaderPipelineCacheToolsCommandlet for platform Windows shader format PCD3D_SM6`. If you see `---- NOT Running ... no files found` instead, the `.spc` was not found. If you see `had stable pipeline cache files, but no stable keys files`, stable keys were off. | `ShaderLibraryCooking.cpp:457-545` |
| 6 | Commit `Build/Windows/PipelineCaches/saskartarad_PCD3D_SM6.spc` by pathspec (`Build/` is not git-ignored). Re-record after big material or scalability changes. The cache is keyed by stable shader keys (material + vertex factory + permutation), not raw hashes, so small edits don't invalidate it. New materials only get precaching. | |

The Shipping build can reuse the same cook (`-Config Both` runs Development with `-cook`, then Shipping
with `-skipcook`). The stable keys and the bundled cache don't depend on the exe configuration.

## 4. CVars that matter (5.8 defaults, from the source)

| CVar | Default (cooked) | Note |
|---|---|---|
| `r.PSOPrecaching` | 1 | In DefaultEngine. Editor: always off. |
| `r.ShaderPipelineCache.Enabled` | 1 | In DefaultEngine. `-psocache` forces it on. |
| `r.ShaderPipelineCache.LogPSO` | 1 | Logs new PSOs in memory; `-logPSO` makes them save to `CollectedPSOs`. |
| `r.ShaderPipelineCache.SaveBoundPSOLog` | 0 | Forced on by `-logPSO`. |
| `r.ShaderPipelineCache.SaveUserCache` | 1 in Shipping, 0 otherwise | Per-player cache of misses. |
| `r.ShaderPipelineCache.StartupMode` | 1 (Fast) | 0 = paused, 2 = background. |
| `r.ShaderPipelineCache.BatchSize` / `BatchTime` | 50 / 16 ms | BatchSize is in DefaultEngine. |
| `r.ShaderPipelineCache.BackgroundBatchSize` / `BackgroundBatchTime` | 1 / 0 | Only in background mode. |
| `r.ShaderPipelineCache.PSOPrecacheIncludeMode` | 2 (ReadOnly) | Keep. See section 2. |
| `r.ShaderPipelineCache.ExcludePrecachePSO` | 0 (ReadOnly) | Optional; see section 2. |
| `r.ShaderPipelineCache.IncludeAllPrecachedPSOs` | 0 (ReadOnly) | Leave off: it would bloat the recording. |
| `r.ShaderPipelineCache.PrintNewPSODescriptors` | 0 | 1 or 2 during a recording run prints each new PSO (diagnostics only). |
| `r.ShaderPipelineCache.Save` (command) | | Saves the recording now. |
| `-clearPSODriverCache` (D3D12 command-line flag) | | Wipes the driver's disk cache. Use it only to *test* a cold first launch. |

## 5. The 20-minute recording route

Settings for the main run: fullscreen at the desktop resolution (2560x1440 on the dev PC), and let the
first-launch auto-detect pick the preset (the Epic tier on the 5070). A fresh archive has no
`GameUserSettings.ini`, so the auto-detect runs by itself and gets recorded too.

The console is the `~` key (Development build). Commands used below:
- `Saskarta.TP <beat_id>`: teleport 30 m before a beat and re-arm it;
- `Saskarta.Skip`: skip a cinematic. **Don't use it during recording**, because cinematics bind their own PSOs;
- `r.ShaderPipelineCache.Save`: save the recording now.

If a `Saskarta.*` command does nothing, type `EnableCheats` once and repeat it (they forward to the
cheat manager).

| Time | Do this | Why |
|---|---|---|
| 0:00 | Double-click `Record-PSO.bat`. Watch the fire intro card, the loading screen and the title sequence. Leave the title idle for 60 s. | Startup, the intro, the title camera and the sky |
| 1:30 | Title > **Settings**: open every tab and move through the lists, then Back. Don't change anything yet. | UI/Slate/CommonUI PSOs |
| 2:30 | **Begin**. Play the boot and B01 handover normally. Walk the first stretch toward B02/B03 (2-3 min). Press R for the radio once, and Esc to pause and resume once. | The real first-play path at walking speed |
| 5:30 | `r.ShaderPipelineCache.Save` | Checkpoint |
| 6:00 | Teleport through the road: `Saskarta.TP B04_CART_CONVOY`, `B05_WAITING_WATER`, `B06_ROAD_AHEAD`, `B07_GEIGER_RISES`, `B08_NUMBERED_STOP`, `B09_DEPARTURE_PLATFORM`. At each one, wait for the view to settle (about 5 s), turn a slow full circle, look up at the sky, walk forward for about 15 s, and let any beat play. | Valley and Climb look keys, the convoy, water, Geiger/storm |
| 10:00 | At `Saskarta.TP B10_DRY_CISTERN`: Esc > Settings > Graphics. Step the preset **Low → Medium → High → Epic → Cinematic**, and look around for about 10 s at each. Then set it back to the auto-detected preset. While in Settings, also switch the upscaler (TSR → Native → DLSS if it is listed; the Quality, Balanced and Performance modes) and toggle the sensor filter, if it is exposed. | Each tier switches shader permutations: 2D and volumetric clouds, post, effects, GI/reflections and TSR modes |
| 13:00 | `r.ShaderPipelineCache.Save`, then `Saskarta.TP B11_LAST_WAYSTATION`, `B12_KNEE_FAULT`, `B13_SECOND_FAULT`, `B14_LOOK_BACK`, using the same routine at each | InCloud and Above look keys, the carrier faults |
| 15:30 | `Saskarta.TP B15_HIGH_VOICE_IN_RANGE`. From here, let the ending play: B16-B17, the **B18 collapse and B19 reveal cinematics (don't skip them)**, the Keeper on foot through B20-B23, then the **B24 transmission and the credits** (CIN_25 is about 97 s). If a stretch doesn't advance, `Saskarta.TP` to the next beat id. | The ending cinematics, the Keeper, the credits UI |
| 19:30 | `r.ShaderPipelineCache.Save`. Then Esc > **Quit** (quit normally; don't close the window from the taskbar). | Writes the final file |

Beat distances (docs/story/story-events.json): B01 is at 0 m and B24 at about 4990 m of a 5 km road.
Walking all of it takes about an hour, so the route walks one representative stretch and teleports
through the rest. The ending depends on the ENDING lane being built. If CIN_15-25 are not in the build
yet, still teleport to B18-B24 for the terrain and sky there, and record again once the ending is in.

### Extra runs (optional, each about 8 min; every run adds a `.rec` file, and all of them go into one expand)

- **Low-end run.** Windowed 1920x1080, the Low preset, TSR Performance. Covers the title, then B01, B05,
  B07, B10, B14 and B19. This matches the min-spec path (GTX 1060 / RX 580 at 1080p Low) that the
  auto-detect picks for those cards, including the 2D cloud layer.
- **High-end run.** The Cinematic preset, DLSS plus frame generation if the plugin is present, and HDR
  output on, if the monitor supports it (HDR changes the tonemapper and output PSOs). Covers the same
  6 spots and the ending.
- **Don't bother varying** window mode or plain resolution at the same upscaler setting: they reuse the
  same pipelines.

The recording covers DX12 SM6 only (`PCD3D_SM6`). A player forced onto DX11 (the SM5 fallback) gets
precaching but no bundled cache.

## 6. Verifying the result

1. In the expand log: `Loaded N PSOs total` with N greater than 0, and the `.spc` exists.
2. In the final cook log: `---- Running UShaderPipelineCacheToolsCommandlet ... PCD3D_SM6`, then
   `Copying the binary PSO cache file`.
3. In the packaged **Development** build log (`<archive>/Windows/saskartarad/Saved/Logs/saskartarad.log`):
   `LogRHI: Opened FPipelineCacheFile: ... saskartarad_PCD3D_SM6.stable.upipelinecache ... with N entries.`
4. A cold first launch: start the exe once with `-clearPSODriverCache`. The loading screen should take
   longer (the batches compile), and gameplay should then not hitch. In the console run
   `log LogPSOHitching Verbose`: the `Runtime graphics PSO creation hitch ... (precache status: ...)`
   lines should be rare, and the `Saskarta loading: timed out` line should not appear on a warm run.
5. Shipping has no log by default, so verify in Development and ship the same cook.
