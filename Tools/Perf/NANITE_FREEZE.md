# Landscape Nanite freezes (~15 s) during play, 2026-09-28

Offline diagnosis. The editor was busy with another agent, so nothing here was run in the editor.
Engine source: `C:/Program Files/Epic Games/UE_5.8` (5.8.2-56702186).

## Short answer

- **Cause:** commit `87b5f9b5` (12:38 EDT today, "hardware ray tracing off") set `r.RayTracing=False`.
  - The static-mesh derived-data key includes the ray-tracing flag, so every static mesh got a new DDC key.
  - The landscape Nanite meshes (`LandscapeNaniteMesh_0`, one per streaming proxy) are ordinary `UStaticMesh`es.
  - Each one has to be rebuilt (~15 s, ~1 GB) the first time it is loaded under the new key.
  - PIE and `-game` block the game thread until the rebuild finishes.
  - The commit message already predicted this: "rebuilds the static-mesh render data it loads, once".
- **Not the cause:** landscape edits, material/MIC changes, the Nanite content ID, grass, RVT, edit layers or Codex's
  editor work. Nothing in the landscape changed. Its cached render data simply doesn't exist yet for the new key.
- **Standalone `-game` from the editor binary:** yes, it is hit too. It already happened today; see the evidence below.
- **Cooked/packaged build:** no. Cooked packages carry built render data, and the game has no Nanite builder.
  The cook itself pays the rebuild once.
- **Fix:** warm the DDC once, by loading every landscape proxy in the editor in small batches. Nothing is saved
  (steps below). After that, each mesh comes from the DDC in well under a second. Don't toggle `r.RayTracing` again.
- **Confidence:** high for the cause. The warm-up procedure is inferred from source and hasn't been run yet.

## Evidence (logs are UTC; EDT = UTC-4)

| When (EDT) | Log | Cell (WP streaming level) | Proxies rebuilt | Game-thread stall |
|---|---|---|---|---|
| 14:09-14:13 | `saskartarad_2.log` (**standalone `-game -fullscreen`**) | 4ZUOPICX…, 03XO26EW…, 7TSOVVYW…, BAA1NHA6…, CYG37E3X…, 9A5JMWD0…, 03IS9C5D… | 10 | 6 stalls of 5.7-10.6 s |
| 15:35:22-38 | `saskartarad-backup-2026.09.28-21.03.09.log` (PIE) | `4TNZOB5R0UTT74B71CX3ODNRO` | `0/30/OKF1Q1XLRRBB6YM4L7UHL6`, `5/9X/T50IKA0BAM0JELVZPMLLK2`, `6/LG/UY4F1MWWY4LWK8D9EH7VWW`, `7/L3/OU8K7495DJIIONV4DVOP22` | 15.68 s |
| 18:24:21-36 | `saskartarad.log` (PIE start) | `BET87E3XN27OOCOPA5RBNX6A3` | `A/OK/JAYO7UCKM9I2WDWJULXGKG`, `3/6A/GUG3GZPESG7TF2KARRMCFS`, `0/NV/M10GIG3SMZPBE964JS1F93`, `B/3B/6HOKA1M4N7QZO98GSFJF9T` | 15.18 s |
| 18:24:36-51 | `saskartarad.log` (PIE) | `AXX7OQUXAK9RZS2GATD0DH0EL` | `0/DC/DSVA653WE1OGPG40E7TV22`, `9/G6/RVVFR5OKD2JTPH2HU8J98T`, `2/LJ/OOPOETX61NAFESOCC7D2HO`, `D/QR/MABWSRK31KHY3II8QA6TXX` | 14.79 s |

Proxy paths are under `/Game/__ExternalActors__/level/Saskarta_WP/`. The 15:35 event in the log:

```
[2026.09.28-19.35.22:562][428]LogStaticMesh: Display: Building static mesh LandscapeNaniteMesh_0 (Required Memory Estimate: 987.849879 MB)...   (x4)
[2026.09.28-19.35.22:635][430]LogStaticMesh: Display: Waiting on static mesh StaticMesh /Memory/UEDPIE_0_Saskarta_WP_4TNZOB5R0UTT74B71CX3ODNRO_InstanceOf_/Game/__ExternalActors__/level/Saskarta_WP/0/30/OKF1Q1XLRRBB6YM4L7UHL6.LandscapeNaniteMesh_0 being ready before playing
[2026.09.28-19.35.37:935][430]LogStaticMesh: NaniteBuild [13.55s]
[2026.09.28-19.35.37:995][430]LogStaticMesh: Built static mesh [15.43s] /Memory/UEDPIE_0_..._InstanceOf_/Game/__ExternalActors__/level/Saskarta_WP/5/9X/T50IKA0BAM0JELVZPMLLK2.LandscapeNaniteMesh_0
[2026.09.28-19.35.38:311][430]LogStreaming: Display: UWorld::AddToWorld: updating components for /Memory/UEDPIE_0_Saskarta_WP_4TNZOB5R0UTT74B71CX3ODNRO took (less than) 15676.08 ms
```

- **The timing matches the `r.RayTracing` flip exactly.** Every log up to the 09:09-10:38 session has
  `Set CVar [[r.RayTracing:1]]`. Every session from 13:00 on has `[[r.RayTracing:0]]`.
  - The "16 PIE starts with 0 builds" are exactly the 6+1+1+4+4 PIE starts of the RT=1 sessions.
  - Every landscape build today happened in an RT=0 session.
- **The key changed for all static meshes, not just the landscape.** Since the flip, other long-unchanged meshes
  also rebuild on first load:
  - the 9/27 HLOD meshes (`StaticMesh_Saskarta_WP_HLODLayer_Instanced_*`, 21 in the standalone run, 6 in PIE);
  - props (`SM_Rock`, `SM_Log`);
  - even the template meshes `SM_Cube` and `SM_Plane` (13:01 headless session).
- **Nothing was evicted from the DDC.** Zen GC reported "Found 0 expired items … deleted 0" all day
  (`--gc-cache-duration-seconds 1209600`), and the file DDC maintenance deleted 0 files.
- **It isn't the landscape's own Nanite rebuild:**
  - there are no `LogLandscape` "export of raw static mesh for Nanite landscape" lines;
  - that path is `check(GIsEditor)` (LandscapeNaniteComponent.cpp:237), so it can't run in `-game`, but `-game` rebuilt too;
  - the proxy `.uasset`s were last written 2026-09-27 14:21-14:26 EDT.
- **Nothing in the editor triggered it.** Hayba at 19:33-19:35 UTC shows only `ping`, `lease_status` and
  `editor_get_state`. The rebuilds fire when the player first streams into a cell whose proxies have no RT=0
  entry yet.
- **Why the start area didn't rebuild:** those proxies already had RT=0 entries in the DDC. The logs don't show
  where those entries came from; an earlier ray-tracing-off run is the likely source.
- **Scale:** 22 proxies have been rebuilt under RT=0 so far, so up to ~234 of the 256 are still cold. At ~15 s per
  cell of 4, that's roughly 10-15 min of freezes spread over the first trip across the map.

## Mechanism (UE 5.8 source)

1. `Runtime/Engine/Private/StaticMesh.cpp` builds the render-data key:
   - `BuildStaticMeshDerivedDataKeySuffix` appends `RT1` when `Mesh->bSupportRayTracing && TargetPlatform->UsesRayTracing()`,
     and `RT0` otherwise (lines 3879-3907).
   - `UsesRayTracing()` reads `r.RayTracing` (TargetPlatformBase.cpp:61, TargetPlatformSettingsBase.cpp:57).
   - `bSupportRayTracing` defaults to true (StaticMesh.cpp:4744), and landscape never clears it.
2. `FStaticMeshRenderData::Cache` misses the DDC and builds inline. It logs "Building static mesh {Name} (Required
   Memory Estimate …)" (StaticMesh.cpp:4312).
3. On streaming, `UWorld::AddToWorld` calls `FAssetCompilingManager::ProcessAsyncTasks` (World.cpp:3850/3903), which
   leads to `FStaticMeshCompilingManager::FinishCompilationsForGame`.
   - With `Editor.AsyncStaticMeshPlayInEditorMode` = 0 (default, StaticMeshCompiler.cpp:39), it calls
     `FinishCompilation` on every compiling mesh in a PIE or Game world ("being ready before playing").
   - This runs in PIE **and** in `-game` from the editor binary.
   - Cooked builds have no compiling manager and no builder.
4. The DDC is `ZenLocal` plus the file DDC under `%LOCALAPPDATA%/UnrealEngine/Common`, and it is writable from the
   editor, PIE and `-game` alike. A mesh warmed in any one of them is warm for the others.

Other CVars in the same key: `r.Nanite.AdaptiveTessellation.Mode`, `r.TriangleOrderOptimization`,
`r.SupportDepthOnlyIndexBuffers`, `r.SupportReversedIndexBuffers`, and
`r.StaticMesh.StripMinLodDataDuringCooking` + `r.StaticMesh.KeepMobileMinLODSettingOnDesktop`. Changing any of
them (or the engine hotfix) has the same effect.

## Fix: warm the DDC (editor, no saves)

Run this when the editor gate is free, no PIE is running, and no other lane is active. Load only; do **not** save
or modify the proxies, and nothing needs committing. Before starting, confirm the editor log has
`Set CVar [[r.RayTracing:0]]`.

1. **Probe with 1 proxy first.**
   - Use a batch size of 8 after that. Don't go to 24: each build estimates ~1 GB and uses every core.
   - If the load call itself blocks for more than 5 s, stop and rethink. Don't retry a timed-out call unchanged.
2. **For each batch K, make three separate Hayba `python_run` calls** (the snippet has no banned substrings):

   ```python
   import unreal
   K = 0; N = 8; LOAD = True   # call 1: LOAD = True; call 3: LOAD = False
   wpl = unreal.WorldPartitionBlueprintLibrary
   px = [d for d in wpl.get_intersecting_actor_descs(wpl.get_editor_world_bounds())
         if d.native_class and d.native_class.get_name() == "LandscapeStreamingProxy"]
   px.sort(key=lambda d: str(d.actor_package))
   batch = px[K*N:(K+1)*N]
   (wpl.load_actors if LOAD else wpl.unload_actors)([d.guid for d in batch])
   print(len(px), [str(d.actor_package) for d in batch])
   ```

   - **Call 1: load.** In the editor world the meshes compile asynchronously, and each finished build is written
     to the DDC.
   - **Call 2: wait.** Poll from the shell, not from Hayba, until every new `Building static mesh
     LandscapeNaniteMesh_0` in `Saved/Logs/saskartarad.log` has a matching `Built static mesh [..]
     …<package>.LandscapeNaniteMesh_0`. A batch of 8 takes about 30 s. A proxy that is already warm logs nothing.
   - **Call 3: unload** (the same snippet with `LOAD = False`). Nothing is dirty, so nothing gets pinned.
     If a proxy shows as dirty, stop.
3. Do all 32 batches (~20 min). This loads actors only, with no global render-state recreation, so it avoids the
   D3D12 stall class.
4. **Optional:** one standalone `-game` flythrough afterwards warms the remaining HLOD and prop meshes. They cost
   only 0.3-0.8 s each, but they are also waited on. Do it only with the user's go.

**Stopgap, not the fix:** `Editor.AsyncStaticMeshPlayInEditorMode=1`, for editor-binary runs only.
- How to set it: `-dpcvars=Editor.AsyncStaticMeshPlayInEditorMode=1` on the command line, or under `[SystemSettings]`.
- What it does: PIE and `-game` stop waiting for meshes that have no collision or navigation relevance. The landscape
  Nanite component qualifies: NoCollision, no navigation, `CanCharacterStepUpOn=ECB_No` (Landscape.cpp:7336-7340).
- The catch: the build still runs in the background (CPU spike, ~1 GB per mesh).
  `ALandscapeProxy::UpdateRenderingMethod` picks Nanite from the content ID, not the compile state
  (Landscape.cpp:7986-7990), so the cell probably shows a terrain hole for ~15 s. This is inferred, not tested.
- **Not recommended:** reverting to `r.RayTracing=True`. The old RT1 entries would still hit for 14 days, but it
  brings back the D3D12 ray-tracing stalls that `87b5f9b5` removed.

## Verify

1. **During the warm-up:** check `Building` and `Built` counts per batch:
   `grep -c "Building static mesh LandscapeNaniteMesh" Saved/Logs/saskartarad.log` equals the matching `Built … LandscapeNaniteMesh_0` count.
2. **Load a finished batch a second time:** it should log no `Building static mesh LandscapeNaniteMesh` lines, only DDC hits.
3. **Playtest** with `Tools/Perf/PlayStandalone.bat`, walking through the cells in the table above and other
   unvisited areas. Then:
   - `grep -h "Building static mesh LandscapeNaniteMesh" Saved/Logs/saskartarad*.log` should find nothing new;
   - `grep -h "AddToWorld: updating components" … | awk '$(NF-1)+0 > 1000'` should find no stalls over 1 s.
4. **Cooked build:** `Building static mesh` can't appear at runtime. Expect the one-time rebuild in the cook log only.
