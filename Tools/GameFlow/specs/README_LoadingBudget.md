# Loading budget (task LOADBUDGET)

While the start sequence streams the world in behind the opaque intro and loading screen, the
**loading budget** caps the frame rate and removes the unsliced bursts of work. The loading UI
(the Keeper point cloud) then keeps a steady frame. Loading takes longer, which is the intended
trade.

Code: `Plugins/SaskartaCore/Source/SaskartaCore/{Public,Private}/SaskartaLoadingBudget.*`
Tests: `Private/Tests/SaskartaLoadBudgetTest.cpp` (`Automation RunTests Saskarta.LoadBudget`)

## When it is on

- **Automatically:** `USaskartaPerfGovernor::SetSuspended("Loading", true)` turns it on and
  `("Loading", false)` turns it off. `PC_Saskarta.BeginIntro` and `BeginTitle` already make these
  calls (Tools/Perf/SCALABILITY.md step 5), so **no Blueprint change is needed**. The budget
  therefore covers the fire card, the Tripothon and Hayba cards and the loading screen, all of
  which stream behind an overlay.
- **Explicitly:** `USaskartaLoadingBudget::GetLoadingBudget(self)` → `BeginLoadingBudget(Owner)` and
  `EndLoadingBudget(Owner)`.
- **Owners:** each owner counts once, however many times it calls Begin. The budget stays on until
  every owner has ended.
- **Save and restore:** the first Begin saves each CVar's current value and the last End writes it
  back. A value that something else changed during loading (for example the settings menu writing
  `t.MaxFPS`) is kept, not overwritten; the OFF log line lists these as "kept".
- **Priority:** the budget writes at each CVar's *current* SetBy priority, so the settings class can
  still write the CVar afterwards.
- **Teardown:** world cleanup (stopping PIE, changing map) and game-instance shutdown restore every
  CVar, whatever owners are still registered.
- **At the end:** one forced full GC (`GEngine->ForceGarbageCollection(true)`) runs on the next
  tick, while the loading screen is still opaque. This is the GC that was held back during loading,
  so the first seconds of gameplay do not hit it.

## CVars (every name verified in UE 5.8 source; none is `ECVF_Cheat`)

| CVar | Before (engine default / project) | During loading | Op | Why |
|---|---|---|---|---|
| `t.MaxFPS` | user's frame cap (60 on the tiers; 0 = uncapped) | **30** (`saskarta.loadbudget.MaxFPS`) | cap, never raised | Steady 33 ms frames; the per-frame slices below fit inside one frame |
| `s.AsyncLoadingTimeLimit` | 5 ms | 5 ms | cap | Kept: at 30 fps it already runs half as often |
| `s.AsyncLoadingUseFullTimeLimit` | 0 | 0 | set | No full slice while blocked on I/O (normally a no-op) |
| `s.PriorityAsyncLoadingExtraTime` | 15 ms | **0** | set | High-priority loads added +15 ms to a frame |
| `s.LevelStreamingActorsUpdateTimeLimit` | 5 ms | **4 ms** | cap | AddToWorld slice (World.cpp) |
| `s.PriorityLevelStreamingActorsUpdateExtraTime` | 5 ms | **0** | set | High-priority streaming added +5 ms |
| `s.LevelStreamingComponentsRegistrationGranularity` | 10 | **4** | cap | Smaller batches: the time limit is checked more often |
| `s.LevelStreamingAddPrimitiveGranularity` | 120 | **40** | cap | Same, for the parallel add-to-scene batches |
| `s.LevelStreamingComponentsUnregistrationGranularity` | 5 | **2** | cap | Same, for streaming out |
| `s.LevelStreamingRouteActorInitializationGranularity` | 10 | **4** | cap | Same, for BeginPlay and initialization |
| `wp.Runtime.MaxLoadingStreamingCells` | 4 | **2** | cap | Fewer cells in flight, so the 230k–350k-instance cells land in different frames |
| `wp.Runtime.BlockOnSlowStreaming` | 1 | **0** | set | Never flush-block the game thread to catch up while the screen hides it |
| `pcg.RuntimeGeneration.NumGeneratingComponents` | 16 / project 4 | **2** | cap | Fewer components generating at once (`pcg.FrameTime` is already 3 ms in the project) |
| `grass.GrassCreationPrioritizedMultipler` | 4 | **1** | cap | No 4x grass creation burst after the camera cut to the title view |
| `grass.MaxCreatePerFrame` | 1 | 1 | cap | Guard only (no-op at the default) |
| `r.ShaderPipelineCache.BatchTime` | 16 ms | **8 ms** | cap | Render-thread PSO precompile slice (packaged builds with a bundled cache) |
| `r.ShaderPipelineCache.BatchSize` | 50 (project) | **25** | cap | Same |
| `gc.TimeBetweenPurgingPendingKillObjects` | 60 s | **600 s** | at least | No ~50 ms GC during loading; one forced at the end instead |
| `s.ForceGCAfterLevelStreamedOut` | 1 | **0** | set | No forced GC per level streamed out (the road-to-title view switch) |
| `r.ScreenPercentage` | user's | untouched (opt-in `saskarta.loadbudget.ScreenPercentage`) | cap | See "GPU" below |

Ops: **cap** writes min(current, value), treats values ≤ 0 as unlimited and never raises. **at least**
never lowers. **set** writes the value. A CVar that is already within budget is neither written nor
restored.

### Considered and left out

- `wp.Runtime.UpdateStreamingStateTimeLimit` has no effect with one World Partition, because the
  incremental update needs more than one.
- `s.AdaptiveAddToWorld.*` is off by default. Turning it on replaces the fixed AddToWorld slice with
  an adaptive one that can grow up to 6 ms and more; we want a fixed slice.
- `FShaderPipelineCache::SetBatchMode` has no getter, so the mode cannot be restored exactly.
  Startup mode 1 (Fast) is already the right mode behind a loading screen, and the two BatchTime and
  BatchSize CVars bound it instead.
- **GPU.** The texture streamer sizes mips from `View.UnscaledViewRect` (UnrealClient.cpp
  `AddStreamingViewInfo`), so a lower `r.ScreenPercentage` behind the screen does **not** starve
  mips. Views, texture streaming and PSO precaching all keep running. It is still off by default:
  restoring the value at the reveal reallocates render targets and resets the TSR history and VSM
  pages on the first title frames, and at 30 fps the GPU (about 12–16 ms on the 5070) is not the
  limit. Set `saskarta.loadbudget.ScreenPercentage 50` if a profile shows the GPU above 33 ms during
  loading.

### What it cannot fix

A single PCG or foliage component with 230k+ instances still registers, and uploads its GPU scene
data, in one frame. No time-slice CVar splits one component. `MaxLoadingStreamingCells 2` only stops
several of them landing in the same frame. The real fix is content: smaller PCG partition cells, or
fewer instances per component (see Tools/Perf/BUDGET.md, "Hitch attribution").

## Control CVars

| CVar | Default | Meaning |
|---|---|---|
| `saskarta.loadbudget.Enable` | 1 | 0 = Begin does nothing (A/B profiling) |
| `saskarta.loadbudget.Log` | 1 | One `LogSaskartaLoadBudget` line per second while active |
| `saskarta.loadbudget.MaxFPS` | 30 | Frame cap during loading; 0 = leave `t.MaxFPS` alone |
| `saskarta.loadbudget.ScreenPercentage` | 0 | > 0 = cap `r.ScreenPercentage` during loading |
| `saskarta.loadbudget.GCAtEnd` | 1 | Force one full GC when the budget ends |

## Verify with a profile

1. Launch the game or PIE through the start sequence and read the log:
   ```
   LogSaskartaLoadBudget: Loading budget ON (Loading): t.MaxFPS 60.000000->30.000000, s.PriorityAsyncLoadingExtraTime ...
   LogSaskartaLoadBudget: Loading t= 12.0 s | frames 30, mean 33.3 ms, max 41.2 ms, >50 ms 0 | game 18.4, render 12.0, GPU 14.1 ms | readiness 60 % (waiting: pcg, grass)
   LogSaskartaLoadBudget: Loading budget OFF (Loading) after 97.3 s: 17 CVar(s) restored.
   ```
   **Pass:** `max` stays under about 50 ms and `>50 ms` is 0 in most lines, with none above 100 ms.
   `frames` is close to 30.
2. For an A/B comparison, run once with `saskarta.loadbudget.Enable 0`. That shows the old 190–440 ms
   maxima and the load time without the budget.
3. For a trace: `-trace=cpu,frame,loadtime` (Unreal Insights). Look for `FlushAsyncLoading`,
   `BlockTillLevelStreamingCompleted` and `CollectGarbage` inside the loading window; all three
   should be gone.
4. After the OFF line, `t.MaxFPS` and the rest must be back to their earlier values
   (`GetCVarValue t.MaxFPS`, or the "Before" column).

## Post-build steps

1. Close the editor and build the real project (the code has been compile-checked on a copy,
   D:/tmp/sask-loadbudget).
2. `Automation RunTests Saskarta.LoadBudget` should give 6 tests, all passing. `CVarsExist` checks
   every budget CVar in the running build.
3. Run the start sequence once and read the per-second lines (above).
4. If loading now runs into the timeout (the OFF log line comes from the `LoadMaxTime` path and
   DescribeUnmet is logged), raise `LoadMaxTime`. The proposal is in the task report; this lane did
   not edit `gen_loading_specs.py`.
