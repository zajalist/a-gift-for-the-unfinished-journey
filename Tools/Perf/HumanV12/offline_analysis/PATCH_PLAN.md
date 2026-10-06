# V12 optimization proposal; no game/plugin implementation

Evidence is `Saved/Verification/human_profile_analysis_20261001/offline_analysis/analysis.json`.
Root must grant exact writable paths before any change below is implemented.
The authored analyzer is an offline artifact tool, not a game performance patch.

1. **Correct the existing capture summary before selecting optimizations.**
   Proposed path: `Tools/Perf/parse_csvprofile.py`, `_read_rows` at line 38,
   and the relevant summary producer that currently calls every >50 ms wall
   record a hitch. Consume the final `EVENTS` header, preserve appended columns
   and distinguish recorded zero from a column absent earlier in the capture.
   Correlate host UTC with native CSV event timestamps, retain focus transition
   uncertainty and separate explicit 30 fps / 3 fps pacing from observed stalls.
   This capture's header grows 363 -> 375 columns. `DictReader` using only the
   opening header loses later `AddToWorld` and other counters, hindering attribution.
   Present the 443 threshold crossings as unclassified wall records, with the
   three foreground-bracketed >50 ms records shown separately. This is a concrete
   reporting correction supported by the evidence; it does not improve game FPS.

2. **Investigate and reduce repeated foreground full GC.**
   Observed GC rows 72 / 97 / 479 cost 32.5953 / 16.9490 / 16.3238 ms and precede
   wall records 73 / 98 / 480 at 73.8663 / 51.2526 / 50.6476 ms. Rows 6 and 386
   also contain full GC at 15.6012 / 15.2613 ms. The executed forcing caller is
   not recorded. Candidate engine path is `World.cpp:5185` ->
   `ForceGarbageCollection(true)` at 5189 / 5193 when levels/actors stream out;
   `CoreSettings.cpp:25` defaults `s.ForceGCAfterLevelStreamedOut` to 1.
   The current loading budget changes that CVar only during opaque loading
   (`SaskartaLoadingBudget.cpp:288`) and restores it in `EndLoadingBudget`.
   Current direct project GC requests are `SaskartaLoadingBudget.cpp:389`
   (normal GC by default) and `SaskartaHeadroomGovernor.cpp:492` (normal GC).
   No matching loading/headroom/explicit-full-GC log was captured, and sampled
   purge counters are zero; attribution to streamed-out levels remains a
   hypothesis. Do not patch an assumed owner or suppress all GC from this pass.
   Once the actual caller is established, a narrow candidate is to suppress
   only forced full purge after streamed-out levels during active play, preserve
   normal/incremental collection and low-memory handling, and restore the CVar
   on stop/teardown with the existing ownership/priority rules. System free RAM
   is only 3.78–4.54 GiB, so pending-purge growth must stay bounded.

3. **Bound foreground loading bursts after the actual producer is established.**
   Foreground row 144 has 31.9459 ms async loading, versus a 5 ms nominal loading
   slice in `SaskartaLoadingBudget.cpp:257`; the budget belongs to loading
   screens and does not establish the active-play CVar state. Actual outstanding
   package count reaches 122, three levels are loading, and AddToWorld peaks at
   6.8924 ms. The log explicitly waits for two LandscapeNaniteMesh assets,
   `pine_roots_b` and `SM_T2_watchtower`; `StaticMeshCompiler.cpp:810` calls
   `FinishCompilation` for those play/collision dependencies. Prepare/finish
   those exact editor source meshes before the later PIE session rather than
   reducing their visual or collision fidelity. A cooked/package build comparison
   is needed to know which waits survive editor compilation. It is not performed
   in this pass. If asset activation remains the culprit, apply an owned active
   gameplay loading budget with small registration batches and no priority extra,
   without globally enabling block-on-streaming or changing accepted visuals.
   Preserve the ground-contact/readiness policy and actual camera source.

4. **Keep existing async audio preload, and inspect the measured timer burst.**
   Foreground row 447 has TimerManager 14.0806 ms and AsyncLoading 6.3119 ms.
   Its aligned wall interval begins at 00:17:33.877930, but no callback name is
   captured, so its producer cannot be assigned. Audio
   exclusive scopes remain small and no `sync load ... (not prefetched: a hitch)`
   warning appears. Existing `SaskartaEventRunner.cpp:1361/1386` sync fallback,
   `SaskartaEventRunner.cpp:1997` sequence fallback and
   `SaskartaRadioStation.cpp:411/427` recall fallback are source risks, not observed
   V12 stall causes. Prefetch already exists at EventRunner 575/646 and
   RadioStation 558. Do not rewrite radio cursor/timing or audio assets based on
   this capture. If a later trace proves a fallback, use an async readiness gate
   for that exact selected asset and preserve the narrative timing/cursor.

5. **Resolve the four background waits separately from active-play work.**
   Generic EventWait in records 852 / 885 / 890 / 957 is
   3986.1667 / 756.1461 / 824.3042 / 3370.5078 ms, preceding long wall records.
   Native `CsvProfiler.cpp:2555` names an unqualified wait `EventWait`; it does
   not identify the waiting dependency. Ordinary intentional 3 fps intervals
   cannot explain an extra 4.0 seconds, but these intervals are sampled
   background focus, not evidence of a four-second foreground play stall.
   No package backlog, significant measured audio, or GC coincides with them.
   `namedevents=0` and `hasgtstalls=0` prevent the missing callstack attribution.
   No engine/renderer/audio patch is justified from the generic wait alone.

No implementation patch is proposed for GPU quality, fog, accepted cinematic
timing, road geometry or assets. V12's GPU max is 14.3479 ms and the frame limit
is explicitly 30 fps; this capture does not establish a GPU bottleneck.
