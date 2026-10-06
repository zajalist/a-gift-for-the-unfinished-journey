# Packaging saskartarad for Windows

`package_windows.ps1` wraps `RunUAT BuildCookRun` for Win64 Development and Shipping, and drives the
optional PSO cache flow described in `PSO_CACHE.md`. A provisional Development package completed on
October 1 (`D:/UnrealEngine/Builds/saskartarad_development_20261001-1018`, UAT `ExitCode=0`). It
predates the current ending, Loading, title and terrain work. The final matching package and source
archive have not been built. See `docs/sprint/2026-10-02-hackathon-remaining.md` for acceptance status.

## What the user does (clicks)

1. **Close the Unreal Editor** (File > Exit) and any `-game` window. Make sure no agent (Codex, Claude)
   is using the editor. The script refuses to start if an `UnrealEditor*` process has this project
   open, if `Saved\Locks\binaries.lock` exists, or if a UAT/UBT run is active.
2. After the final source and assets pass the in-editor review, capture their
   runtime fingerprint before the build. Open **PowerShell** (Windows Terminal):
   ```powershell
   cd D:\UnrealEngine\saskartarad
   python Tools\Package\project_archive_manifest.py snapshot --output D:\UnrealEngine\Builds\final-inputs.json
   .\Tools\Package\package_windows.ps1 -DryRun
   .\Tools\Package\package_windows.ps1 -Config Shipping
   ```
   If execution policy blocks the script, run it with `powershell -ExecutionPolicy Bypass -File`.
   Do not use `-SkipCook` for this final build.
3. Launch the extracted Shipping package and complete the route and save/input variants. Require
   a successful UAT log as well as a clean package playtest; an `ExitCode=0` alone is not acceptance.
4. Bind the unchanged prebuild snapshot to that successful UAT log and exact package directory:
   ```powershell
   python Tools\Package\project_archive_manifest.py bind-build --snapshot D:\UnrealEngine\Builds\final-inputs.json --build-log <fresh-uat-log> --package <fresh-package-directory> --output D:\UnrealEngine\Builds\final-build-binding.json
   .\Tools\Package\comrade_project_archive.ps1 -BuildManifest D:\UnrealEngine\Builds\final-build-binding.json -Destination D:\UnrealEngine\Builds\saskartarad_source_final.zip
   ```
   The archive tool checks runtime input hashes against the package binding and verifies ZIP members.
   Extract and launch the package and archive copies before distribution.

PSO recording, expansion and bundling remain optional performance work; use `PSO_CACHE.md` if the
packaged frame trace shows a need. The PSO steps below document that optional flow.

The measurements, estimates and proposed config changes below were recorded on September 28. Treat
them as planning notes; the fresh preflight, UAT log and final archive manifest are the release evidence.

The script runs UAT at **BelowNormal** priority (child processes inherit it), so the PC stays usable.
Pass `-NormalPriority` for full speed.

## Script reference

| Switch | Effect |
|---|---|
| `-Config Development\|Shipping\|Both` | Default Development. `Both` cooks once, then builds Shipping with `-skipcook`. |
| `-LogPSO` | Development recording build. Stable keys are forced. The `.shk` files are copied to `<archive>\_pso\keys`, and `Record-PSO.bat` (`-logPSO`) is written. |
| `-ExpandPSO -RecordingsDir <dir> -KeysDir <dir>` | `ShaderPipelineCacheTools expand` → `Build\Windows\PipelineCaches\saskartarad_PCD3D_SM6.spc`. It backs up an old `.spc` to `Saved\PSO\backup\`. |
| `-Maps` | Default `/Game/level/Saskarta_WP` (joined with `+`). |
| `-ArchiveRoot` | Default `D:\UnrealEngine\Builds`. Each build goes to `saskartarad_<config>_<yyyyMMdd-HHmm>`, and UAT logs to `logs\`. |
| `-MinFreeGB` / `-MinFreeDdcGB` | Refuse below 40 GB on the archive drive or below 25 GB on the Zen/DDC drive (C:). |
| `-SkipCook` | Reuse the last cook: rebuild, stage, pak and archive only. |
| `-Distribution` | With Shipping: `-distribution -nodebuginfo`. |
| `-DryRun` | Checks and commands only. It creates no folders. |

The UAT command it runs (Development, as printed by `-DryRun`):
```
RunUAT.bat BuildCookRun -project=D:\UnrealEngine\saskartarad\saskartarad.uproject -noP4 -unattended -utf8output
  -platform=Win64 -clientconfig=Development -build -cook -map=/Game/level/Saskarta_WP
  -stage -pak -iostore -compressed -prereqs -archive -archivedirectory=D:\UnrealEngine\Builds\saskartarad_development_<stamp>
  -AdditionalCookerOptions=-DisablePlugins=HaybaMCPToolkit -ini:Engine:[DevOptions.Shaders]:NeedsShaderStableKeys=true
```
- `-DisablePlugins=HaybaMCPToolkit` keeps the MCP TCP server out of the cook commandlet (its module is
  `Editor`-type, so it is never in the game binary anyway).
- `-ini:...` is UAT's own config-override pass-through to the cooker. The script drops it once the ini
  line exists (recommended line 1 below).

### Maps

Only `/Game/level/Saskarta_WP` is needed. It holds the whole flow: the intro card, loading, title,
boot, road and ending (task PACKAGING). The checks:
- `GameDefaultMap` is already `/Game/level/Saskarta_WP.Saskarta_WP` (committed).
- `TransitionMap` is empty.
- `EditorStartupMap` (`Lvl_IntroRoom`) is editor-only, and the cooker doesn't add it.

The cooker also always adds `GameDefaultMap`, `GlobalDefaultGameMode` and `GameInstanceClass`
(`CookOnTheFlyServer.cpp:9031`). Today that means `BP_FirstPersonGameMode` and its FirstPerson template
content get cooked too (recommended line 3). `Config/DefaultGame.ini` already has `MapsToCook`, the
AlwaysCook dirs (SaskartaGaea Audio/Story/Look/GameFlow) and the NeverCook dirs (Hayba, Python,
Developers).

## Disk and time estimates

Measured on 2026-09-28:

| What | Size |
|---|---|
| `Content/` (raw) | 21.6 GB |
| Project `DerivedDataCache/` (D:) | 1.5 GB |
| Zen store / shared DDC (`%LOCALAPPDATA%\UnrealEngine\Common\Zen\Data`, C:) | 25 GB |
| `Saved/` (not cooked) | 17 GB |
| `Intermediate/` | 5 GB |
| Free on D: | 79 GB |
| Free on C: | 179 GB |

The machine has 16 threads and 32 GB RAM.

**Where a build writes.** In 5.8 `bUseZenStore=True` is the default (BaseGame.ini), so the cooked
packages go to the Zen store on **C:**. Staging goes to `Saved\StagedBuilds\Windows` (D:), and the
archive is a second copy on D:.

| Item | Estimate (unmeasured) |
|---|---|
| Final package (IoStore, Oodle Kraken) | 6-10 GB. The task-PACKAGING estimate: landscape Nanite about 3.3 GB, plus external actors, HLODs and the referenced packs, plus about 200 MB of CEF until the `.uproject` fix below. |
| D: per Development build | about 15-22 GB: staged 6-10, archive 6-10, game build and Intermediate 1-2. The staged folder is reused by the next build. |
| D: for the full round (psorec + dev + shipping archives) | about 30-40 GB. Delete old `saskartarad_*` archives between rounds. |
| C: (Zen cook output + new DDC entries: SM5 shaders, cooked texture formats) | about 15-30 GB on the first cook; later cooks overwrite it |
| Game target build (UBT, SaskartaCore + a generated temp target, precompiled engine) | 5-15 min the first time |
| Editor target check/build (UAT does it; needed if SaskartaCore changed since the last editor build) | 1-10 min |
| **First cook** (WP map, 1,734 external actors, 1,056 PCG partition actors, HLODs; SM6 shaders partly warm from the editor, **SM5 shaders fully cold**) | **1.5-4 h** |
| Later cooks with a warm DDC | 20-60 min |
| Stage, IoStore and compression | 10-25 min |
| Archive copy | 2-5 min |
| PSO expand | 2-5 min |
| Recording run | 20 min, plus 8 min per extra run |
| **Whole first round** (psorec build → record → expand → Both) | **about 3.5-7 h of wall time, mostly unattended** |

RAM: a cook of this map can peak at 20-28 GB. Close the browser and other heavy apps during the first
cook; the HLOD build ran out of memory before.

## Prerequisites

- UE 5.8 at `C:\Program Files\Epic Games\UE_5.8` with Win64 target support (`RunUAT.bat`, `UnrealEditor-Cmd.exe`).
- Visual Studio 2022 with the C++ workload and a Windows SDK. SaskartaCore compiled for the `Game`
  target in the provisional October 1 Development package; it must compile again from final source. UAT generates
  `Intermediate\Source\saskartarad.Target.cs`, because the project has no `Source\`.
- The editor closed, and no `Saved\Locks\binaries.lock`.
- The PCG tree blocker from task PACKAGING (B2: `PCG_Saskarta_Trees` still references the skinned
  Megaplant/DynamicWind trees) should be fixed in an editor lane first. Otherwise the cook pulls those
  assets in with missing parents.

## Config changes RECOMMENDED but not made

`Config/DefaultGame.ini` had no uncommitted changes, so it was allowed to change, but it needs nothing:
`bShareMaterialShaderCode=True` (required for the PSO cache), `MapsToCook` and the cook dirs are
already there. **No config file was edited.**
- `DefaultEngine.ini` has the user's pending hunks, so it is off-limits.
- `.uproject` and `Config/Windows/*` changes affect the running editor, so they are listed here instead.

1. **Stable shader keys**. Needed to record AND to bundle; the script forces it until this line exists.
   In `Config/DefaultEngine.ini`:
   ```ini
   [DevOptions.Shaders]
   NeedsShaderStableKeys=true
   ```
   Alternative that avoids DefaultEngine.ini: create `Config/Windows/WindowsEngine.ini` with the same two
   lines. The cooker reads the per-platform Engine ini too (`ShaderLibraryCooking.cpp:276-279`).
2. **Smaller recordings** (optional; include mode 2 already skips precached entries at runtime). In
   `Config/DefaultEngine.ini` `[SystemSettings]` (ReadOnly CVar, so it must be set in an ini):
   ```ini
   r.ShaderPipelineCache.ExcludePrecachePSO=1
   ```
3. **Don't cook the FirstPerson template game mode.** In `Config/DefaultEngine.ini`
   `[/Script/EngineSettings.GameMapsSettings]`, replace the `GlobalDefaultGameMode` line with:
   ```ini
   GlobalDefaultGameMode=/Game/SaskartaGaea/GameFlow/GM_Saskarta.GM_Saskarta_C
   ```
4. **Keep editor plugins out of the game target** (task PACKAGING S1; this drops CEF, RemoteControl,
   MCP and similar from the package). In `saskartarad.uproject`:
   - add `"TargetAllowList": ["Editor"]` to the `Aura` and `AIAssistant` entries;
   - add this entry:
   ```json
   { "Name": "HaybaMCPToolkit", "Enabled": true, "TargetAllowList": ["Editor"] }
   ```
   Rebuild the editor afterwards (editor closed). The staged `Engine\Binaries\ThirdParty\CEF3` should
   then be gone.
5. **Halve the shader cook** (optional). In `Config/DefaultEngine.ini`
   `[/Script/WindowsTargetPlatform.WindowsTargetSettings]`, delete this line:
   ```ini
   +D3D11TargetedShaderFormats=PCD3D_SM5
   ```
   Keep the `-D3D11TargetedShaderFormats=PCD3D_SM5` line. This drops the DX11 fallback: every
   supported GPU (GTX 1060 / RX 580 and up) runs DX12 SM6, which Nanite/Lumen need anyway. Only SM6 gets
   a bundled PSO cache in any case.
6. **Dedupe DefaultEngine.ini** (task PACKAGING N4): `r.Substrate` (True then False),
   `DefaultGraphicsRHI` (3 times) and `r.RayTracing` (2 times). The last value wins today.

## Open risks

- **D: is 96 % full (79 GB free).** One full round fits. Two rounds without deleting archives do not.
  The script refuses below 40 GB.
- **First Game-target compile of SaskartaCore** may fail. It has never been built for `Game`: a
  `WITH_EDITOR` leak, or a test file without `WITH_DEV_AUTOMATION_TESTS` (task PACKAGING S6). Fix in
  C++, then rerun with `-SkipCook` if the cook finished.
- **Editor plugins in the game target** (Aura dependencies; recommendation 4) can add build time,
  size, or a link error until the `.uproject` fix is made.
- **B2 PCG tree graph** can pull the skinned trees in, with missing parents. Fix it before the recording
  build, or the recording contains PSOs for assets that shouldn't ship.
- **The ending must be built** (the ENDING lane) before the recording covers CIN_15-25. If it isn't,
  record again later: every `.rec` file can be expanded together with the old ones, as long as their
  cook's `.shk` keys are passed too.
- **Recording loss:** the recording saves only on quit, on Alt-Tab, or on `r.ShaderPipelineCache.Save`.
  A crash mid-run loses everything since the last save; the route saves three times.
- **Estimates are unmeasured.** Replace them with the real numbers from the first run: the UAT log in
  `D:\UnrealEngine\Builds\logs\`, and the archive size the script prints.
- **Cheat forwarding in packaged Development builds:** the `Saskarta.TP`/`Beat` commands forward to
  `CM_Saskarta`. If the cheat manager isn't created in standalone, run `EnableCheats` first. This is not
  verified in a packaged build.
- **Songs without a licence** (`malak`, `weli`, `hayaa`; task PACKAGING S8): keep them out before any
  *public* Shipping build.
