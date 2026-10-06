# Saskarta scalability: auto-detect, adaptive quality and the tier audit (task PERF-AUTO)

The goal (user, 2026-09-27): "run on any normal consumer PC and automatically assign graphics
based on the running device specs".

- **Min spec:** GTX 1060 6 GB / RX 580 at 1080p Low, 30+ fps.
- **Recommended spec:** RTX 3060 at 1080p High, 60 fps.
- **Dev machine:** RTX 5070 12 GB, Ryzen 7 5800X, 1440p.

**Status: written offline and compile-checked against an isolated copy of the plugin. It is
not built into the live project and not run.** Every millisecond figure below is an estimate:
it is reasoned from the CVar's cost model, and nothing has been measured. The PERF2 lane
(`.superpowers/sdd/2026-09-26-saskarta-world-sprint/task-PERF2-brief.md`) measures them.

## Files

| File | What |
|---|---|
| `Plugins/SaskartaCore/Source/SaskartaCore/Public/SaskartaHardwareProfile.h`, `Private/SaskartaHardwareProfile.cpp` | `USaskartaHardwareProfileLibrary`: `GatherHardwareSpecs()`, the known-GPU table `ClassifyGPU()`, the pure `Recommend()`, and the structs `FSaskartaHardwareSpecs` and `FSaskartaDetectedProfile`. |
| `Public/SaskartaPerfGovernor.h`, `Private/SaskartaPerfGovernor.cpp` | `FSaskartaGovernorCore`, the pure state machine, and `USaskartaPerfGovernor`, a game-instance subsystem with a 2 Hz timer. |
| `Public/SaskartaGameUserSettings.h`, `Private/SaskartaGameUserSettings.cpp` | Additive changes: `RunAutoDetect()`, `RunAutoDetectIfNeeded()`, `GetDetectedProfile()`, `GetQualityWarning()`, `bAdaptiveQuality`, `AdaptiveTargetMode`, `bAutoDetected` and the `AutoDetect*` stamps. Also `ComputeTierCVars()`/`ApplyTierCVars()`, the `saskarta.adaptive*` mirrors, overrides of `ApplyNonResolutionSettings` and `LoadSettings`, and the `saskarta.perf.AllowInEditor` CVar. |
| `Private/Tests/SaskartaPerfTest.cpp` | The `Saskarta.Perf.*` automation tests. |
| `Config/DefaultScalability.ini` | The audit hunks (see "Ini changes"). |
| `Tools/GameFlow/gen_settings_specs.mjs` | Data only: the **Adaptive quality** and **Target frame rate** rows, plus row descriptions. |

`SaskartaCore.Build.cs` was **not** changed. Everything used (Engine, RHI, RenderCore) is
already a dependency.

## 1. Hardware auto-detect

### When it runs

`USaskartaPerfGovernor` (a game-instance subsystem) calls
`USaskartaGameUserSettings::RunAutoDetectIfNeeded()` 0.5 s after the game instance starts, during
the black screen before the fire card. It runs `RunAutoDetect()` in two cases:

- **First launch.** `GameUserSettings.ini` had no `[/Script/SaskartaCore.SaskartaGameUserSettings]`
  section when `LoadSettings` first ran. Only the Saved (user) layer ever has that section.
- **The GPU changed.** The saved `AutoDetectGPU` differs from the current adapter name.

A player who has settings from before this feature keeps them; only the adapter is stamped. A
driver update is logged and stamped, and it does not re-detect.

It does **not** run in the editor or PIE (see "Editor safety").

### What it reads

`GatherHardwareSpecs()` reads:

- **GPU:** `GRHIAdapterName`, `GRHIVendorId`, `GRHIDeviceIsIntegrated`,
  `GRHIAdapterUserDriverVersion`, and dedicated VRAM from `RHIGetTextureMemoryStats`.
- **CPU:** `FPlatformMisc::GetCPUBrand`/`NumberOfCores`/`NumberOfCoresIncludingHyperthreads`. The
  clock comes from `HKLM\HARDWARE\DESCRIPTION\System\CentralProcessor\0\~MHz` on Windows.
- **RAM:** `FPlatformMemory` total physical memory.
- **Display:** the desktop resolution. The refresh rate comes from
  `EnumDisplaySettingsW(ENUM_CURRENT_SETTINGS)`, falling back to the RHI mode list.

Then `RunHardwareBenchmark(10)` runs the synth benchmark for its CPU and GPU scores.

### The tier table (`ClassifyGPU` + `Recommend`)

| Class | Cards | Preset |
|---|---|---|
| Integrated | Intel UHD/Iris Xe/"Arc Graphics" iGPU, AMD Vega 3-11/680M/780M/"Radeon Graphics", NVIDIA MX, GT 1030, GTX 950/960, RX 550, Microsoft Basic Render | **Low** |
| Entry | GTX 1050/1050 Ti/1060/1070, GTX 1630/1650, RX 470-590, RX 5300/5500, RX 6400/6500, Arc A310/A380, GTX 970/980 | **Low**, or **Medium** when the GPU score is at least 250 and VRAM is at least 6 GB |
| Mainstream | GTX 1660 (all), GTX 1080/1080 Ti, RTX 2060, RTX 3050, RTX 4050, RX 5600/5700, RX 6600/6650, RX Vega 56/64, Arc A580 | **Medium** |
| Performance | RTX 2070-2080 Ti, RTX 3060-3070 Ti, RTX 4060/4060 Ti, RTX 5050-5060 Ti, RX 6700/6750, RX 7600-7700, Arc A750/A770/B570/B580 | **High** |
| Enthusiast | RTX 3080+, RTX 4070+, RTX 5070+, RX 6800+, RX 7800+, RX 9070 | **Epic** |
| Unknown | Anything else (Quadro, RTX Axxxx, a future brand) | GPU score below 150 gives Low, below 350 Medium, otherwise **High**. Without a score: Medium. Never Epic. |

The table also applies these rules:

- **Laptop parts** ("Laptop", "Mobile", "Max-Q", RX ####M) drop one class, down to Entry at the
  lowest.
- **The RHI's integrated flag** always means Integrated.
- **Guard:** a known Mainstream, Performance or Enthusiast card whose GPU score is below 40 % of
  its class's expected score (350 / 700 / 1400) drops one level. This catches a throttled laptop
  or a mislabelled card.
- **Cinematic is never automatic.** The recommendation is clamped to 0-3.
- The score thresholds are **PROVISIONAL**. The engine's own thresholds (18/42/115) put every
  modern card on Epic, so the name table decides. PERF2 logs the RTX 5070's real scores (the
  `Auto-detect:` log line) so the thresholds can be calibrated.

### Per-group caps (after the preset)

| Condition | Cap |
|---|---|
| VRAM < 4 GB | Textures Low, Shadows Medium, GI Medium |
| VRAM < 6 GB | Textures Medium |
| VRAM < 8 GB | Textures High |
| RAM < 8 GB / < 12 GB / < 16 GB | View distance, foliage and textures at Low / Medium / High |
| < 4 physical cores or CPU score < 60 | View distance, foliage, effects and shadows at Medium |
| < 6 physical cores | View distance and foliage at High |

Two further adjustments:

- **Anti-aliasing** is at least Medium. TSR at 50-58 % needs its history features.
- **Foliage and clouds:** `PresetFoliage[min(level, foliage)]` and `[min(level, effects)]` are
  written directly. A capped group makes the overall level "Custom", and then `ApplySettings`
  skips the foliage table.

### Upscaler, frame cap and VSync

TSR screen percentage by preset and output size (Quality 66.7 %, Balanced 58 %, Performance
50 %):

| Preset | up to 1080p | 1440p / ultrawide | 4K |
|---|---|---|---|
| Low | 58 | **50** | 50 |
| Medium | 66.7 | **58** | 50 |
| High | 66.7 | 66.7 | 58 |
| Epic | **Native 100** | 66.7 | 58 |

- Integrated GPUs always use 50 %.
- **Frame cap:** the display refresh, with at most 60 on Low. Unknown refresh gives 60.
- **VSync:** on when the display runs at 75 Hz or less.

### Blueprint API (on `USaskartaGameUserSettings`)

- `RunAutoDetect()` returns an `FSaskartaDetectedProfile`. It applies (`ApplySettings(false)`) and
  saves.
- `RunAutoDetectIfNeeded()` returns a bool.
- `GetDetectedProfile()`: `Summary` is the Settings line, for example
  `Detected: NVIDIA GeForce RTX 5070, 12 GB, recommended: Epic`. `Reasons` lists every cap
  applied.
- `bAutoDetected`, `AutoDetectGPU`, `AutoDetectDriver`, `AutoDetectLevel`, `AutoDetectVRAMMB`,
  `AutoDetectCPUScore`, `AutoDetectGPUScore`: all Config, and saved.
- `GetQualityWarning()` returns non-empty text while any group is on Cinematic ("Cinematic is for
  screenshots: it can use over 5 GB of video memory and halve the frame rate."). `ApplySettings`
  also logs a warning.

### BP hookup (for the next editor lane; not done here)

1. **The "Run benchmark" button.** In `gen_settings_specs.mjs`, `handlerGraph`, the
   `w.autoDetect` branch still calls the engine's `RunHardwareBenchmark` and caps every group at
   High. Replace the body with one call: `g.call('RunAutoDetect', SGUS, {}, 'bench')`, wired to
   `Settings` (`wire(g, 'Settings', ...self)`), then the existing `quietOn` /
   `RefreshGraphics` / `quietOff` tail. `RunAutoDetect` applies and saves on its own, so the
   trailing `Preview()` is harmless. This is a code change in the generator, not data, so it was
   left out. Regenerate the specs, then run `bpgraph.mjs build` under the editor gate.
2. **The "Detected: ..." line.** Add a TextBlock under the AutoDetect row. Set it from
   `GetDetectedProfile().Summary` in `RefreshGraphics`, and after the button.
3. **The Cinematic warning.** Show `GetQualityWarning()` in the description strip while the
   Preset row (or any group row) is on Cinematic.
4. **The new rows.** These are already in the generator's `TABS` data: **Adaptive quality** (check,
   `bAdaptiveQuality`, mirror `saskarta.adaptive`) and **Target frame rate** (combo 30 / 60 /
   Display, `AdaptiveTargetMode`, mirror `saskarta.adaptive.target`). Running
   `node Tools/GameFlow/gen_settings_specs.mjs` regenerates `WBP_Saskarta_Settings.*.json`. It was
   run in a scratch copy and `bpgraph.mjs check` passed. The real spec files were not regenerated,
   because the menu lane has uncommitted edits in them. It then needs a `bpgraph.mjs build`.
5. **Suspensions.** Call `USaskartaPerfGovernor::GetPerfGovernor(self).SetSuspended(Name, bool)`:
   - in `PC_Saskarta.BeginIntro`: `("Loading", true)`;
   - in `BeginTitle`: `("Loading", false)` and `("Title", true)`;
   - in `EnterPlaying`: `("Title", false)`;
   - around any sequence: `("Cutscene", ...)`.

   Without these, the governor still skips paused, unfocused and `bCinematicMode` frames, and the
   first 10 s after a map load. It would, however, judge the loading screen and the title vista
   as gameplay.

## 2. Adaptive quality (`USaskartaPerfGovernor`)

Default on (`bAdaptiveQuality`). The **target** is:

- **30 fps** when `AdaptiveTargetMode` is 0;
- **60 fps** when it is 1 (the default);
- **Display** when it is 2: the frame cap, else the refresh rate.

In every mode the target is never above the frame cap or a VSync'd refresh.

**Sampling.** A looping 0.5 s timer on the game instance (no Tick) takes these values:

- the **mean frame time** over those 0.5 s (`GFrameCounter` delta);
- the **GPU time**, `RHIGetGPUFrameCycles`;
- the **CPU time**, the maximum of `GGameThreadTime` and `GRenderThreadTime`.

The decision uses the **median of the last 10 samples (5 s)**. A sample over 2.5x the median and
over twice the target is dropped as a hitch. A timer gap over 1.5 s is not a sample.

**It does not sample** (and it restarts the window and the hold timers) while:

- suspended from Blueprint;
- within 10 s of a map load;
- there is no world or it has not begun play;
- the game is paused;
- the window is unfocused;
- the player controller is in `bCinematicMode`.

**Rules and hysteresis:**

| | Condition | Held for | Action |
|---|---|---|---|
| Below target | median frame > target x 1.10 (for example > 18.3 ms at 60 fps) | 10 s after the 5 s window fills | one step DOWN |
| Headroom | median frame <= target x 1.05 **and** median busy (max of GPU and CPU) < target x 0.75 | 30 s | one step UP (undo the latest DOWN) |
| Band | anything in between | - | nothing |

Guards against flip-flopping:

- **Settle:** 2 s after any step, samples are ignored, then the window refills. Consecutive
  DOWNs are therefore at least about 16.5 s apart.
- **No UP within 60 s of a DOWN.**
- **Flip-flop guard:** a DOWN within 90 s of an UP blocks UPs for 10 minutes.
- **Never above the user's settings:** UP only pops the governor's own stack.

**Which ladder.** It is **CPU-bound** when the median CPU time is at least 1.10x the median GPU
time. The user's 5070 PIE profile was exactly that: frame 19.7 ms, GPU 8.6 ms, render thread
19 ms, 443k primitives.

- **GPU-bound:**
  1. The screen percentage goes toward a 50 % floor in at most three even steps (66.7 -> 58.4 ->
     50; Native -> 83.3 -> 66.7 -> 50).
  2. Then one group per step, round robin: **shadows -> GI -> reflections -> view distance ->
     effects -> foliage**.
- **CPU/render-thread-bound:** resolution cannot help. It steps **view distance -> foliage ->
  shadows -> effects**, round robin, and does nothing else when those are out.
- **Floors:** GI and Effects stop at **Medium**. GI Low switches Lumen off and Effects Low drops
  `r.MaterialQualityLevel`, which are a visible pop and a PSO hitch. The other groups stop at
  Low.

**How the steps are applied:**

- **Resolution:** `r.ScreenPercentage` at `ECVF_SetByGameSetting`, the priority
  `ApplySaskartaSettings` uses.
- **Groups:** `Scalability::ToggleTemporaryQualityLevels(true)` +
  `SetQualityLevels(levels, bForce)`. The user's levels stay in `GameUserSettings` and are what
  `SaveSettings` writes (`Scalability::SaveState` saves the backup levels while temporary levels
  are on).
- **The foliage step** also scales `grass.DensityScale` x0.7 and `grass.CullDistanceScale` x0.85
  per step. The settings class holds those two above the FoliageQuality group.
- **Per-tier CVars:** the non-recreating ones (VSM LOD bias, Nanite edge length) follow the
  stepped shadow and view-distance levels. `r.Lumen.HardwareRayTracing` is never touched by the
  governor, because changing it recreates every render proxy.
- **A settings change** (menu Apply or Preview, or `RunAutoDetect`) goes through
  `ApplyNonResolutionSettings`. It broadcasts `OnUserSettingsApplying`, and the governor drops
  every step before the user's levels apply.

Every step is logged under `LogSaskartaPerf`, for example:

```
Adaptive quality DOWN (CPU-bound): ViewDistance High -> Medium (median frame 19.7 ms, busy 19.0 ms, target 60 fps, depth 1)
```

`DescribeState()` returns a one-line string for a debug overlay.

### Editor safety

In the editor, PIE shares the editor's CVars, and the tier CVars are set at the `[SystemSettings]`
priority, so they would outlive the session. So with `saskarta.perf.AllowInEditor` at 0 (the
default), all three are off in the editor:

- the auto-detect;
- the per-tier CVars;
- the governor.

They run in `-game` standalone and packaged builds. To try them in PIE, set
`saskarta.perf.AllowInEditor 1` first. This is why the user's PIE profile ran Cinematic with none
of this active.

## 3. Tier CVars the ini cannot set (`ComputeTierCVars`, C++)

`[/Script/Engine.RendererSettings]` sets its CVars at `ECVF_SetByProjectSetting`, and
`DefaultEngine.ini` `[SystemSettings]` sets its CVars at `ECVF_SetBySystemSettingsIni`. Both are
above `ECVF_SetByScalability`. The engine ignores a lower-priority write, so these
`DefaultScalability.ini` lines **never applied**:

| CVar | Held by | Effect in the ini before |
|---|---|---|
| `r.Shadow.Virtual.ResolutionLodBiasDirectional` | [SystemSettings] 0.0 | ShadowQuality 2.0/1.0/0.5/0.0 ignored: every preset ran 0.0 |
| `r.Nanite.MaxPixelsPerEdge` | [SystemSettings] 1.5 | (nothing set it per tier) |
| `r.Streaming.PoolSize` | [SystemSettings] 3072 | Engine TextureQuality 400-3000 MB ignored: a 4 GB card got a 3 GB pool (clamped to 70 % of VRAM) |
| `r.Lumen.HardwareRayTracing` | RendererSettings True | (nothing set it per tier) |
| `r.Lumen.TraceMeshSDFs`, `r.Lumen.Reflections.MaxRoughnessToTraceForFoliage` | RendererSettings 0 / [SystemSettings] 0 | The GI@1 lines were ignored. Both are 0 anyway. |

`ComputeTierCVars` sets them per tier at `ECVF_SetBySystemSettingsIni`, the same priority as the
lines it replaces. A device profile or the console still wins. It is applied at the end of
`USaskartaGameUserSettings::ApplySettings`, and unchanged values are skipped.

| CVar | Low | Medium | High | Epic | Cine | Keyed on | Estimated saving at Low (GTX 1060, 1080p) |
|---|---|---|---|---|---|---|---|
| `r.Shadow.Virtual.ResolutionLodBiasDirectional(+Moving)` | 2.0 | 1.0 | 0.0 | 0.0 | -0.5 | Shadows | 0.5-1.0 ms (VSM raster and page marking, about 1/16 of the pages at +2) |
| `r.Nanite.MaxPixelsPerEdge` | 2.5 | 2.0 | 1.5 | 1.5 | 1.0 | View distance | 0.5-1.5 ms (Nanite raster; about 0.36x the triangles of 1.5 at 2.5) |
| `r.Streaming.PoolSize` (MB) | by VRAM: < 3 GB 600, < 4 GB 1000, < 6 GB 1400, < 8 GB 2000, < 10 GB 2560, else 3072 | | | | | VRAM | This avoids pool-over-budget thrash and hitches on 4-6 GB cards. It does not save ms. |
| `r.Lumen.HardwareRayTracing` | 0 | 0 | 1 | 1 | 1 | GI | On RT cards at Medium: 1-3 ms GPU, plus the RT-scene instance updates on the render thread. Epic's own CVar help warns about "significant scene update costs" over 100k instances. |

High and Epic keep exactly what the project runs today: VSM bias 0.0, MaxPixelsPerEdge 1.5,
pool 3072 at 12 GB, and HWRT on. The High/Epic look is unchanged.

## 4. Ini changes (`Config/DefaultScalability.ini`)

| Change | Why | Estimated effect |
|---|---|---|
| **`@4` -> `@Cine`** in ViewDistance, Shadow, GI, Effects and Foliage | `Scalability.cpp` (`GetScalabilitySectionString`) looks up `<Group>@Cine` for the top level. The `@4` sections never applied, so Cinematic ran the **engine** values. | Cinematic view distance drops from `r.ViewDistanceScale=10` to 1.5 (the render-thread primitive count; see the 443k-primitive profile), and foliage 1.0 -> 1.0. Likely several ms of render thread at Cinematic, and it is the biggest single reason Cinematic is so heavy. Low to Epic are unaffected. |
| `ViewDistanceQuality`: `r.StaticMeshLODDistanceScale` 1.5 / 1.25 / 1.0 / 1.0 / 1.0 | Non-Nanite meshes (skinned and stand-in trees, props) switch LOD sooner on Low/Medium. It is restated at every level so it does not stick. | 0.2-0.5 ms GPU and fewer vertices on the render thread at Low. |
| `ShadowQuality`: LOD-bias lines kept equal to the C++ table; High 0.5 -> **0.0** | They were masked. 0.0 is what High actually ran, so the High look is unchanged. | none (documentation) |
| `ShadowQuality@0`: explicit `r.VolumetricFog=0` | Engine BaseScalability already turns fog off at Low and Medium. It is stated explicitly for clarity. **Note for STORM:** Medium has no volumetric fog either (engine default). | Low already saves the fog pass, about 1-2 ms on a 1060. |
| `ShadowQuality@3` / `@Cine`: `r.VolumetricFog.GridPixelSize=16`, `GridSizeZ=64` (and Cine `HistoryMissSupersampleCount=4`) | The engine's Shadow group also sets the fog grid (Epic 8 px x 128, Cine 4 px x 128 x16). Whichever group applied last won, so a governor shadow step at Epic flipped the fog to 8 px. It now matches EffectsQuality (STORM's 16 x 64). | At Cinematic, 1080p: 480x270x128 = 16.6M froxels down to 120x68x64 = 0.52M. About 0.5 GB of render targets and several ms. This plausibly accounts for part of the 5.2 GB RenderTargetPool measured on Cinematic. |
| `EffectsQuality@0/@1`: `r.VolumetricCloud.ViewRaySampleMaxCount` 128 / 192, `ReflectionRaySampleMaxCount` 8 / 12 | These were unset, so the engine defaults (768 / 80) applied if the player turned volumetric clouds on at Low/Medium (the preset uses the 2D layer). High and up already restate both keys. | 1-3 ms on a 1060 when volumetric clouds are on at Low. |
| `FoliageQuality`: `grass.CullDistanceScale` 0.6 / 0.75 / 1.0 / 1.15 / 1.5 | The pre-restart baseline, matching `PresetFoliage[].FoliageDistance`. After the settings class is live, `ApplySaskartaSettings` owns the CVar. | Render thread and GPU on the grass: roughly proportional to the square of the distance, so about 0.36x the instances at Low. |
| Header note | Records the masking and the "set a key in every level" rule. | - |

**Kept as they were:** Nanite stays on (it is required). The engine's AntiAliasing, Reflection,
PostProcess, Texture and Shading tables are kept. TSR history is 200 % at Epic/Cine in the engine
AntiAliasing group: that is the Epic look, so it was left alone. It is the next thing to cut if
Epic has to be cheaper (at 1440p output that is a 5120x2880 history). The STORM lane's
`EffectsQuality@3/@4` fog lines were left as they are.

**Already cheap, no change needed:**

- Lumen is off at Low (`r.Lumen.DiffuseIndirect.Allow=0`, engine DFAO off, skylight only), and
  reflections are SSR at Low/Medium (engine ReflectionQuality).
- VSM stays on at Low with 512 pages and bias 2.0. A switch to shadow maps was **not** made: with
  Nanite foliage and landscape, VSM is the path Epic optimises (Nanite rasterises straight into
  the virtual pages), and conventional cascades would re-draw the Nanite geometry per cascade.
  `r.Shadow.Virtual.Enable` is also held by RendererSettings, and changing it recreates every
  proxy.
- The volumetric cloud render target already traces at quarter resolution
  (`r.VolumetricRenderTarget.Mode=0`).

## 5. Tests

`Automation RunTests Saskarta.Perf` runs the five tests below. Rule R33 applies: they were written
offline, and the fail-first step was waived.

| Test | Covers |
|---|---|
| `Saskarta.Perf.ClassifyGPU` | 41 adapter names across NVIDIA, AMD, Intel, iGPUs, laptops, the software renderer and unknown/empty names, mapped to their class. |
| `Saskarta.Perf.Recommend` | 5070 at 1440p gives Epic/66.7 %/165 cap and the summary string. 1060 at 1080p 60 Hz gives Low/58 %/cap 60/VSync. The Entry lift and the 4 GB block. iGPU. 3060 High. The score guard. The VRAM, RAM and CPU caps. Upscaler by resolution. Unknown GPUs. Never Cinematic. |
| `Saskarta.Perf.TierCVars` | The Low/High values, the pool per VRAM, the governor variant without HWRT, and unknown VRAM. |
| `Saskarta.Perf.AutoDetectTriggerAndTarget` | First launch, an existing player, a GPU change, the case-insensitive same GPU, no RHI, and the target-fps modes, cap and VSync. |
| `Saskarta.Perf.Governor` | Injected frame times. The first DOWN at exactly 15 s. The whole 12-step ladder in order with the GI/Effects floors. Hitch drop. The hysteresis band. UP at 60 s and never past the baseline. The flip-flop 10-minute block. Invalidation. The native 3-step resolution ladder. The CPU-bound ladder (the user's profile numbers: VD, Fo, Sh, Fx, VD, Fo, Sh, with resolution and GI untouched). The Low-user floor. |

## 6. Build

The editor must be **closed**. Rule R41 forbids UBT while the editor is running.

```powershell
& "C:/Program Files/Epic Games/UE_5.8/Engine/Build/BatchFiles/Build.bat" UnrealEditor Win64 Development -Project="D:/UnrealEngine/saskartarad/saskartarad.uproject" -WaitMutex
```

Then start the editor and run `Automation RunTests Saskarta.Perf`. To see the auto-detect and
the governor, run the game standalone: `UnrealEditor.exe saskartarad.uproject -game -log`, and
look for the `Auto-detect:` and `Adaptive quality` lines. For a clean first launch, delete
`Saved/Config/Windows/GameUserSettings.ini` first.
