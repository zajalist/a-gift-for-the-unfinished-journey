# Saskarta performance presets (Task P4)

Target hardware: RTX 5070, 1440p output, TSR Quality, frame generation **off**
(it does not count toward the target). That is an 80 fps / **12.5 ms** GPU
frame budget, split as:

| Nanite geometry | Foliage + shadows | VSM | Lumen | Sky/fog/clouds | Post | Headroom |
|---|---|---|---|---|---|---|
| 2.5 ms | 3.0 ms | 1.5 ms | 3.0 ms | 1.0 ms | 1.0 ms | 0.5 ms |

**Every number in this document, in `Config/DefaultScalability.ini` and in the
`PresetFoliage[5]` table (`SaskartaGameUserSettings.cpp`) is a provisional
starting point.** None of it has been measured yet - the P5 flythrough
(task-P5-brief.md / task-P5-report.md) is what turns these into confirmed
numbers. Treat "High (level 2) hits 80 fps" as the goal this file is aimed
at, not a claim that it currently does.

## Two places foliage/cloud settings come from, and why

`USaskartaGameUserSettings::ApplySettings()` runs `Super::ApplySettings()`
(engine scalability groups) and then `ApplySaskartaSettings()` (the
`saskarta.*` and `grass.*`/`pcg.Saskarta.*` cvar mirrors, from
`ComputeCVars()`). Between those two calls it now applies `PresetFoliage[5]`
(R40: a file-scope table inside the existing `ApplySettings(bool)` override,
not a new function) whenever `GetOverallScalabilityLevel()` returns a clean
preset (0-4), not `-1` ("Custom" - the combos have diverged from any single
preset):

| Level | Preset | FoliageDensity | FoliageDistance | CloudMode |
|---|---|---|---|---|
| 0 | Low | 0.35 | 0.6 | 0 (2D layer) |
| 1 | Medium | 0.6 | 0.75 | 0 (2D layer) |
| 2 | **High** | 0.9 | 1.0 | 1 (volumetric) |
| 3 | Epic | 1.0 | 1.15 | 1 (volumetric) |
| 4 | Cinematic | 1.0 | 1.5 | 1 (volumetric) |

This is deliberately the **only** place `r.VolumetricCloud` on/off per preset
is decided. `DefaultScalability.ini`'s `[EffectsQuality@N]` groups do **not**
set `r.VolumetricCloud`, because `ApplySaskartaSettings()` runs immediately
afterward and would silently overwrite it from `CloudMode` every time - an
ini line there would look like it does something and never do it. Confirmed
against `UGameUserSettings::ApplySettings` / `ApplyNonResolutionSettings` in
`Engine/Source/Runtime/Engine/Private/GameUserSettings.cpp` (UE 5.8.2,
`C:/Program Files/Epic Games/UE_5.8`): `ApplyNonResolutionSettings()`
unconditionally calls `Scalability::SetQualityLevels(ScalabilityQuality)`,
and `ApplySaskartaSettings()` runs after that in our override, last write
wins.

`[FoliageQuality@N]` in `DefaultScalability.ini` still matters as the
**pre-restart baseline**: until the user restarts the editor for
`GameUserSettingsClassName` to take effect (R43), `GetGameUserSettings()`
returns a plain `UGameUserSettings` with no override, so the raw ini values
are what actually apply. Keep the two tables' Low/Medium/High numbers in
sync by hand (0.35 / 0.6 / 0.9) until there is one generated source for both.

## The P3 settings menu now applies both on a preset pick

`Tools/GameFlow/gen_settings_specs.mjs`'s `OnPreset` handler previously only
called `SetOverallScalabilityLevel` (which just sets properties) and then
`RefreshGraphics` (UI-only) before its existing trailing `Preview()` call.
`Preview()` calls `ApplyNonResolutionSettings()` **directly**, not through
the virtual `ApplySettings()`, so it already pushed the engine groups' cvars
live, but it could never reach `USaskartaGameUserSettings`'s override and
`PresetFoliage[5]`. The generator now inserts an explicit `ApplySettings`
call (`bCheckForCommandLineOverrides=false`) between the level write and the
UI refresh, so picking a preset applies both the engine groups and the
foliage/cloud table once `GameUserSettingsClassName` is live (R43). Spec
regenerated and validated offline (`node Tools/GameFlow/bpgraph.mjs check`);
**the built `WBP_Saskarta_Settings` blueprint itself still needs a
`bpgraph.mjs build` pass against the live editor** to pick up the new node -
not done here (see task-P4-report.md; it needs the editor gate this session
never got).

## `DefaultScalability.ini`

Overrides on top of the engine's own `Engine/Config/BaseScalability.ini`
(verified against UE 5.8.2 source, matching this project's own convention in
`docs/performance-budget.md`) - only the groups this task had reasoning for.
**Not overridden** (left at engine defaults): `AntiAliasingQuality`,
`ReflectionQuality`, `PostProcessQuality`, `TextureQuality`,
`ShadingQuality`. No project-specific need was identified for these yet;
revisit after a P5 profile if any of them shows up as a cost.

Note: the P4 brief's interface section lists "Landscape" as one of ten
scalability groups. That is not a real UE 5.8 group - verified against
`BaseScalability.ini`'s own `PerfIndexThresholds_*` list and the settings
menu's own auto-detect loop (`Tools/GameFlow/gen_settings_specs.mjs`, the
`w.autoDetect` branch), both of which agree on the real ten: ViewDistance,
AntiAliasing, Shadow, GlobalIllumination, Reflection, PostProcessing,
Texture, VisualEffect (`EffectsQuality` ini section), Foliage, Shading. No
`LandscapeQuality` group exists to write to. AntiAliasing was almost
certainly what was meant; left at engine defaults (see above) since this
project's AA choice is made through the Upscaler menu (TSR/DLSS), not a
separate quality tier.

### ViewDistanceQuality

`r.ViewDistanceScale` only, ramped 0.5 (Low) to 1.5 (Cinematic), 1.0 at High
(the brief's explicit level-2 value). **This does not affect World
Partition streaming distance, HLODs or the landscape/mountain silhouette** -
those are separate systems (WP runtime cell loading range; no HLODs are
built at all per `docs/performance-budget.md`). Distant-mountain visibility
is a Sky/Look-lane concern, not something this preset table changes.

### ShadowQuality

VSM directional resolution bias and page budget, ramped from cheap (Low:
bias 2.0, 512 pages) to the brief's High values (bias 0.5, 4096 pages) up to
Cinematic (bias -0.5, 8192 pages - matches the project's global
`r.Shadow.Virtual.MaxPhysicalPages` ceiling noted as "Cinematic, not
default" in `docs/performance-budget.md`).

### GlobalIlluminationQuality

Lumen diffuse indirect is off entirely on Low (falls back to the engine's
own DFAO/skylight path for that group - a real, independent cvar with no
Saskarta mirror, so safe to set directly). Medium enables it but skips mesh
SDF tracing and uses a coarse (64x) screen-probe downsample; High (given)
is 32x with mesh SDFs on; Epic/Cinematic tighten to 16x/8x.

### EffectsQuality

Volumetric fog grid pixel size only (16 at High, per the brief), tightening
toward Cinematic; volumetric cloud ray sample counts scale up from the
brief's High values. Cloud on/off is `PresetFoliage[5].CloudMode`, not this
group - see above.

### FoliageQuality

`foliage.DensityScale` / `grass.DensityScale`, matching `PresetFoliage[5]`'s
FoliageDensity column (pre-restart baseline; see above).

## `DefaultEngine.ini` `[SystemSettings]`

Added as its own `[SystemSettings]` block (UE merges duplicate section
headers within one ini file) rather than inserted into the existing
performance-budget block, which is a separate pending user edit this task
must not stage or commit (R44):

| Setting | Value | Why |
|---|---|---|
| `r.PSOPrecaching=1` | on | Precompiles PSOs from asset data ahead of first use instead of hitching on first draw - the standard fix for shader-compile stutter in a foliage-dense open world with thousands of unique material/mesh combinations. |
| `r.ShaderPipelineCache.Enabled=1` | on | Persists the file-based PSO cache across sessions/builds so precaching has something to warm from after the first run. |
| `r.ShaderPipelineCache.BatchSize=50` | 50 | Caps PSOs compiled per frame from the cache so warm-up itself doesn't cause its own hitches; 50 is the conservative middle of Epic's documented range, not yet profiled here. |
| `r.VT.PoolSizeScale=1.5` | 1.5x | The ground material (RVT-backed per `docs/performance-budget.md`'s foliage shader baseline) and the Fab material library added this task use virtual texturing; the existing `r.Streaming.PoolSize=3072` budget is regular streaming textures only and does not cover the RVT physical-texture pool. |

## Task P4 file/step status (see `task-P4-report.md` for the full account)

- `DefaultScalability.ini` - done, offline only (no editor step needed).
- `DefaultEngine.ini` `[SystemSettings]` - done, committed as an isolated
  hunk (R44).
- `PresetFoliage[5]` in `SaskartaGameUserSettings.cpp` - source written;
  **not yet compiled with Live Coding** (R41) - the editor gate was held by
  another lane (owner `LOOK2`) for this task's entire session.
- P3 settings menu generator fix - source + regenerated spec done and
  validated offline; the live `WBP_Saskarta_Settings` blueprint still needs
  a `bpgraph.mjs build` pass.
- `Tools/Audio/set_streaming.py` - plan script written; **not run** against
  the editor (same gate blocker).
- `Tools/GameFlow/specs/BPC_CarrierVision.json` - **not touched.** R10/the
  brief require the retro-boot workflow (`wf_538a1bd5-bcf`) to have finished
  first. `git log -- Tools/GameFlow/specs/BPC_CarrierVision.json` shows zero
  commits ever (the file is untracked in this working tree), and no
  retro-boot completion report exists anywhere under `.superpowers/` or
  `Tools/`. That contradicts the claim that it "finished days ago" - treated
  as unconfirmed and skipped rather than risking a conflicting edit to a
  file another lane may still be mid-write on.
