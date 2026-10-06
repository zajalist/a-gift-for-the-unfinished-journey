# PSO warm-up: the first-start loading screen and a bundled PSO cache

The user's report (2026-09-27): "im getting 60 fps in the game but when i first start it the fps is
quite bad and i get lag". That first-run lag is shaders and pipeline state objects (PSOs) compiling the
first time each material/mesh combination is drawn, plus World Partition, HLOD and texture streaming
settling. Two layers deal with it.

## 1. At runtime: the loading screen (Task TITLE, addendum 4)

Flow: black, then the fire intro (the calligraphy card), then LOADING, then the title.

- `PC_Saskarta.BeginIntro` puts `WBP_Saskarta_Loading` under the intro card (Z 450 under 500) and makes
  the carrier pawn at the PlayerStart the view target, so the road start streams and renders behind
  the opaque card.
- When the card has burned in (`IsHolding`, 8 s, or at a skip), `StepIntroCard` burns it away onto
  the loading screen.
- `PollRoad` (phase 1) polls `USaskartaReadiness::GetReadiness` at the pawn every 0.25 s. It is done
  when every condition is met and `RoadMinTime` (1.5 s) has passed, or at `RoadMaxTime` (20 s).
  Then the view target becomes the title camera.
- `PollTitle` (phase 2) does the same at the title camera, with `TitleMinTime` 2 s, and the loading
  screen visible at least `LoadMinShown` 4 s from the start of the burn-away (2.5 s burn plus about
  1.5 s fully shown). At `LoadMaxTime`, 55 s after BeginIntro (about 10 s of intro plus 45 s of
  loading), it continues anyway and logs `Saskarta loading: timed out ...; still pending: <list>`.
- Then comes `BeginTitle` (the title sequence and menu start under the loading screen), followed by
  `WBP_Saskarta_Loading.FadeOut(1 s)`.
- Progress line: phase 1 fills 0 to 0.5 by the readiness fraction and phase 2 fills 0.5 to 1. It never
  runs backwards. It eases at 30 Hz and completes during the fade.
- The readiness conditions (C++, `SaskartaReadiness.cpp`):
  - streaming complete, both for all sources and at the view;
  - no PCG component generating;
  - shader/PSO work pending = 0. This is `FShaderPipelineCache::NumPrecompilesRemaining()`
    + `PipelineStateCache::NumActivePrecacheRequests()` + `GShaderCompilingManager` outstanding jobs
    (editor/PIE);
  - textures settled: at most 16 wanting resources;
  - instance counts within 200 m unchanged for 1 s. The history is kept per view, so the two phases
    don't reset each other.
- On a warm run, when everything is cached and compiled, both phases pass at their minimums. The
  loading screen then shows for about 4 s, the minimum that stops it from flashing.
- Tuning is in the `PC_Saskarta` variable defaults (`Tools/GameFlow/gen_loading_specs.py`):
  `RoadMinTime`, `RoadMaxTime`, `TitleMinTime`, `LoadMinShown`, `LoadMaxTime` and `LoadFadeTime`.

Config already in `Config/DefaultEngine.ini` (Task P4): `r.PSOPrecaching=1`,
`r.ShaderPipelineCache.Enabled=1`, `r.ShaderPipelineCache.BatchSize=50`.

## 2. For a packaged build: a bundled PSO cache (not run yet; the user's step)

PSO precaching covers most PSOs from asset data. A recorded cache covers the rest: global shaders,
post-process and anything precaching misses. The engine looks for it at
`Build/Windows/PipelineCaches/*<LibraryName>_<ShaderFormat>.spc`
(`ShaderLibraryCooking.cpp`, UE 5.8). Here that is `saskartarad_PCD3D_SM6.spc`.

1. **One-time config**, before the recording build:
   - In `Config/DefaultGame.ini`, under `[/Script/UnrealEd.ProjectPackagingSettings]`:
     `bShareMaterialShaderCode=True` and `bSharedMaterialNativeLibraries=True`.
   - In `Config/DefaultEngine.ini`, under `[DevOptions.Shaders]`: `NeedsShaderStableKeys=true`.
   - In `Config/DefaultEngine.ini`, under `[SystemSettings]`: `r.ShaderPipelineCache.ExcludePrecachePSO=1`.
     This records only what precaching did NOT catch, which keeps the file small. It is ECVF_ReadOnly,
     so it must be in the ini, not set at runtime.
2. **Package a Development build** (Platforms > Windows > Package Project, or BuildCookRun).
   - The cook writes the stable shader keys to
     `Saved/Cooked/Windows/saskartarad/Metadata/PipelineCaches/ShaderStableInfo-*.shk`.
   - Keep that folder. Each recording must match the cook it came from.
3. **Record.** Run the packaged exe with `-logPSO` (`-logPSO` forces
   `r.ShaderPipelineCache.LogPSO` and a fresh user cache).
   - Play the title, Begin, the boot, the road start, and at least one walk through each look key's
     stretch: Valley, Climb, InCloud, Above. Open and close Settings and pause.
   - Quit normally so the file is written. The recording lands in the packaged game's
     `saskartarad/Saved/CollectedPSOs/*.rec.upipelinecache`.
   - More sessions (different settings presets, resolutions or upscalers) add more files. Use them all.
4. **Expand** the recordings into a stable cache (editor closed or not; this is a commandlet):
   ```powershell
   & "C:/Program Files/Epic Games/UE_5.8/Engine/Binaries/Win64/UnrealEditor-Cmd.exe" `
     "D:/UnrealEngine/saskartarad/saskartarad.uproject" -run=ShaderPipelineCacheTools expand `
     "<recordings>/*.rec.upipelinecache" `
     "D:/UnrealEngine/saskartarad/Saved/Cooked/Windows/saskartarad/Metadata/PipelineCaches/*.shk" `
     "D:/UnrealEngine/saskartarad/Build/Windows/PipelineCaches/saskartarad_PCD3D_SM6.spc"
   ```
   Check the log for `Loaded N PSOs` and a non-zero output count.
5. **Package again.** The cook finds the `.spc`, builds the binary pipeline cache and stages it
   (`Content/PipelineCaches/Windows`).
   - At startup, `FShaderPipelineCache` precompiles it in batches of `BatchSize`.
   - `NumPrecompilesRemaining()` is already part of the readiness check, so the loading screen stays
     up until those batches are done, capped at 45 s.
6. **Commit** `Build/Windows/PipelineCaches/*.spc`, and redo steps 2-5 after big material changes.
   Stale entries are skipped, not harmful, but new materials fall back to precache only.

Verification in the packaged build:
- The log shows `LogRHI: Display: Opened pipeline cache ...` and `... precompiling N PSOs`.
- `stat PSOPrecache` reports low misses.
- The `Saskarta loading:` timeout line does not appear on a warm run.
