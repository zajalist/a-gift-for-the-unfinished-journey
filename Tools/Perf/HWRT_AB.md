# Hardware ray tracing off: the A/B plan (task PERF-URGENT)

Why: in the traced PIE runs, the largest remaining D3D12 stall source was
`D3D12Device::CreateDescriptorHeap(BindlessResources, 32768)`, which totalled 16.1 s in run A. That heap
exists because bindless runs in its RayTracing configuration ("Bindless is enabled
(Configuration=RayTracing)"). The RT scene also rebuilt its shader binding tables mid-play as it grew
(512 -> 768 -> 1280 geometry segments).

Hardware RT is a startup setting, so the A/B needs an editor restart: the next closed-editor build window.

## 1. The ini hunk (Config/DefaultEngine.ini, [/Script/Engine.RendererSettings])

Before (lines 51-60; the duplicated keys are already in the file):

```ini
r.RayTracing=True
r.RayTracing=True
...
r.Lumen.HardwareRayTracing=True
```

After (for the A/B, before the editor starts):

```ini
r.RayTracing=False
r.RayTracing=False
...
r.Lumen.HardwareRayTracing=False
```

Leave the rest alone:
- `r.RayTracing.RayTracingProxies.ProjectEnabled` and `r.Lumen.HardwareRayTracing.LightingMode` do nothing
  without RT.
- `r.GenerateMeshDistanceFields=True` is already on, which software Lumen needs.

**Optional variant C: software Lumen with mesh SDF tracing.** The project sets `r.Lumen.TraceMeshSDFs=0`, so
software Lumen would trace only the global distance field, which gives coarser occlusion in the arcade. For a
fair HWRT-off look, also capture with `r.Lumen.TraceMeshSDFs 1`. It's a runtime console change, so no second
restart is needed.

**Revert.** Restore the three lines (`git checkout` of only that hunk; the file also carries other people's
uncommitted edits). Commit the change only if the user picks "off".

**Settings code.** `ComputeTierCVars` still writes `r.Lumen.HardwareRayTracing=1` at GI High and above. With
`r.RayTracing=False` that write is ignored, so no C++ change is needed for the A/B.

## 2. Measurement (same as runs A/B; ≤ 60 s Hayba PIE, gate held, throttle override on)

1. Set `saskarta.loadbudget.Enable 0` (gameplay streaming settings), then
   `Trace.File D:/tmp/sask-perfurgent/meas/hwrt_<on|off>.utrace cpu,frame,gpu,bookmark,loadtime,task,log`.
2. Start PIE with Hayba `editor_start_pie`. Don't use unreal_editor `start_pie`: its Aura recorder stalls
   9-15 s.
3. From about t=12 s, send the 12 `python Tools/Perf/hwrt_ab.py route-steps` snippets through Hayba
   `python_run`, one every ~2-3 s. They move the view target 250 m along the road each time, which is what
   drives WP and grass streaming.
4. Stop PIE by t ≤ 55 s, run `Trace.Stop`, then set `saskarta.loadbudget.Enable 1`.
5. Export with Insights:
   `UnrealInsights.exe -OpenTraceFile=... -ExecOnAnalysisCompleteCmd="TimingInsights.ExportTimingEvents <csv> -threads=GameThread,RenderThread*,RHIThread,RHISubmissionThread -columns=ThreadName,TimerName,StartTime,Duration,Depth -maxdepth=16" -NoUI -AutoQuit`
6. Summarise with `python Tools/Perf/hwrt_ab.py stalls <csv> <t0> <t1>` plus frame p50/p95/p99/max and the
   counts of frames > 50 ms and > 100 ms (D:/tmp/sask-perfurgent/meas/hitch.py).

The "on" baseline is run A (PERF-URGENT part 2):

| Measure | Run A (on) |
|---|---|
| CreateDescriptorHeap | 16.1 s |
| CommitReservedResource | 6.9 s |
| ExecuteCommandLists | 6.9 s |
| Submission_Wait | 5.0 s |
| Texture FinishCompilation | 3.1 s |

The VSM reserved-pool stall is already removed (afcf1ea2). So the "on" run gets repeated on the same build,
for a like-for-like pair.

**GPU cost** (the same three poses in PIE): `stat gpu` at each route step, or a `ProfileGPU` at the spawn.
Compare the Lumen passes (ScreenProbeGather, Reflections) HWRT vs SWRT at 1080p High. Target: GPU < 12 ms.

## 3. Visual A/B (three fixed poses, editor world, the same capture both ways)

The poses are in `hwrt_ab.py poses`, taken from Tools/World/setdress_sites.json:

| Pose | Where | What it judges |
|---|---|---|
| spawn | the carrier dock at PlayerStart (S01 "carrier" view) | open daylight, sky light, the carrier's contact and AO |
| waitingwater | the Waiting Water village (S07 "orbit_a") | bounce light between the houses, market roofs, water reflections |
| arcade | 8 m in front of the S13 Numbered Stop arch row, standing height, looking through the arches | arch shadows, occlusion under the arcade, indirect light on the back wall: where HWRT and SWRT differ most |

For each pose, with the gate held, one call per step:

```
python Tools/Perf/hwrt_ab.py load <pose>
python Tools/Perf/hwrt_ab.py capture <pose> on      # (or off, after the restart)
python Tools/Perf/hwrt_ab.py unload <pose>
```

After both states:
- run `python Tools/Perf/hwrt_ab.py compose`, which writes `Saved/HWRT_AB/<pose>_on_vs_off.png`;
- optionally, variant C: `r.Lumen.TraceMeshSDFs 1`, then `capture <pose> offsdf`.

**Taken 2026-09-28 13:55-14:00 UTC** (HWRT on, the current look key, the editor world):
- `Saved/HWRT_AB/spawn_on.png`: backlit, and the near ground reads almost black in the Fog 2 look.
- `Saved/HWRT_AB/waitingwater_on.png`
- `Saved/HWRT_AB/arcade_on.png`: the shadowed arch faces are where software Lumen would differ most.

For the "off" side (after the restart), capture each pose twice:
- `capture <pose> off`;
- then, after `r.Lumen.TraceMeshSDFs 1` on the console, `capture <pose> offsdf` (variant C).

`compose` pairs on and off. Put offsdf next to them by hand, or extend compose.

The "on" captures could be taken **at any time** in any gate window: they need no restart. The "off" captures are
taken right after the restart. Captures use the same look key and time of day; `apply_look` is left
untouched in between.

Show the user the three side-by-side images and the stall table, and let them decide. Keep HWRT if the
arcade and village read clearly worse in software Lumen and the stall gain is small.

## 4. Standalone-run plan (later; only with the controller's go)

The goal is to see whether the PIE-start and streaming stalls happen outside the editor (one scene, no
editor world, no texture compilation).

- **Command** (≤ 90 s; the editor may stay open; the user must not be playing):
  `"C:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor.exe" D:\UnrealEngine\saskartarad\saskartarad.uproject /Game/level/Saskarta_WP -game -windowed -ResX=1280 -ResY=720 -trace=cpu,frame,gpu,loadtime,task,log -tracefile=D:\tmp\sask-perfurgent\meas\standalone.utrace -csvprofile -log -NoSound`
  - `-NoSound` is optional: drop it to keep audio decode in the measurement.
- **Memory:** a second UnrealEditor process with about 7 GB working set and 4-6 GB of VRAM, next to the open
  editor. It fits the 32 GB / 12 GB machine, but check `is_pie_active` pie_capacity first (≥ 6 GB
  available). Close it if VRAM is short.
- **Stop:** a watchdog kills the process at 90 s (`Stop-Process` on its PID). It never touches the
  editor's PID.
- **What to read:**
  - the first-frame and loading stalls (the same D3D12 calls as the PIE runs);
  - the loading-budget lines (the LoadBudget log);
  - the time to Title;
  - whether the title renders smoothly.
- **What it can't show:** a standalone -game run still uses editor-format (uncooked) data and DDC. The true
  shipping check is the packaged Development build (PSO.md section 2).
