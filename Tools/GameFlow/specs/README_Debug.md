# Debug mode: jump to any story beat (LANE5)

Test every point of interest without driving the whole road. It runs in PIE and in Development
builds. The cheat manager doesn't exist in Shipping builds, so neither does the debug menu.

## Open it

| How | What |
|---|---|
| **F9** | Toggles the debug menu. This is `+DebugExecBindings=(Key=F9,Command="SaskartaDebug")` in `Config/DefaultInput.ini`, and it replaces the engine's F9 screenshot. It takes effect at the next editor start. |
| Console `SaskartaDebug` | Same as F9 (the console key is `~`). |
| Console `saskarta.debug` | The dotted spelling. It needs the queued C++ (see below); until that is built, use `SaskartaDebug`. |

The menu opens in Game-and-UI mode. The carrier keeps its input, and the mouse and the arrow keys
work in the menu: arrows move between buttons, and Enter or Space presses one.

## The menu

- **Left column: every beat and checkpoint,** in road order. Each row shows the id and the road metre
  (from `DA_Saskarta_Story`, baked by `gen_debug_specs.py`); optional beats are marked `(opt)`.
  Clicking a beat:
  1. runs `USaskartaEventRunner::GoToRoadM(road_m + 0.5)`, which marks every beat up to and
     including this one as fired, so the runner never fires it by itself;
  2. moves the carrier **30 m of spline back** along the road, grounded with a line trace
     (`BFL_SaskartaRoad.ComputeRoadRespawn`, facing up-road). If the ground there has not streamed
     in yet, the carrier is held (MOVE_None) and the trace is retried every 0.25 s, for up to 10 s;
  3. **arms** the beat: once the runner's road metre has been seen at least 5 m behind the beat and
     then reaches it, the menu fires it (`FireBeat(id, force)`). This is how the beat's one-shot
     flag is reset from Blueprint, and it fires exactly once;
  4. with **"trigger on teleport"** ticked, fires the beat at once instead.
  Clicking a checkpoint is a plain teleport (`GoToRoadM`, then the same grounding).
- **Middle column:**
  - Previous / Next beat;
  - Trigger the selected beat now;
  - Skip the current cinematic (this sets `Saskarta.Cine.AllowSkipAll 1` first, so any skip rule works);
  - Reset all beats;
  - carrier speed ×1 / ×3 / ×10 (the pawn's `CustomTimeDilation`; the world clock and the story
    timers are not sped up);
  - god mode (the road tether is stopped and kept stopped every 1 s: no warning, no breach, no reboot);
  - the free-fly camera (the engine's `ToggleDebugCamera`);
  - `stat unit`;
  - Restart, which runs `PC_Saskarta.QuitToTitle`: it reopens the level, so the flow plays again from
    the intro through loading to the title;
  - the weather: the look buttons Valley, Basin, Climb, InCloud and Above, the storm-intensity slider,
    and Release override.
- **Right column: the event log.** Every 0.25 s it shows the road metre, the speed, the FlowState,
  whether a cinematic is running, whether Voice is busy, the seconds to the next beat, the armed
  beat, the speed multiplier and god mode. Under that, the debug menu's own actions, newest first.
  The raw `LogSaskartaEvents` tail needs the queued C++ (`USaskartaDebugLibrary::GetRecentEventLog`).

## Console commands (type them too)

| Now (cheat manager exec) | Queued dotted alias | Does |
|---|---|---|
| `SaskartaDebug` | `saskarta.debug` | toggles the menu |
| `SaskartaTP 450` / `SaskartaTP B03_PROMISE` | `saskarta.tp <road_m or beat_id>` | a number means a road metre (a plain teleport); an id means the beat's teleport and arm |
| `SaskartaBeat B06_ROAD_AHEAD` | `saskarta.beat <id>` | triggers that beat now (forced) |
| `SaskartaSkip` | `saskarta.skip` | skips the current cinematic |
| `SaskartaResetBeats` | `saskarta.resetbeats` | resets every one-shot flag |
| `SaskartaNext`, `SaskartaPrev` | | the next or previous beat in the list |
| `SaskartaSpeed 3` | | the carrier speed multiplier |
| `SaskartaGod`, `SaskartaFly` | | god mode, the free camera |
| `SaskartaStorm 0.9` / `SaskartaStorm -1` | | pins `MPC_Saskarta_Sky.StormIntensity` (every 0.1 s) / releases it |
| `SaskartaLook 3800` | | god mode on, then `LightingDirector.SetRoadProgress(3800)` (it blends toward that key with the director's 25 s smoothing) |

The existing runner commands still work: `Saskarta.Events.GoTo <roadm>`, `Saskarta.Events.Fire <id>`,
`Saskarta.Events.Dump`, `Saskarta.Cine.Play <CinId>`, `Saskarta.Cine.AllowSkipAll 1`.

## On the C++ (rebuilt by LANE5 after the CPPBATCH build, 2026-09-28)

- **Reset all beats** calls `USaskartaDebugLibrary::ResetAllBeats`: every one-shot flag is cleared in memory;
  the Continue save is never written.
- **A beat click** calls `ArmBeat(Id, 30)`: the runner puts the carrier 30 m before the beat on the ground and
  re-arms it; "trigger on teleport" fires it at once. B01 (a flow beat) is re-armed for its next flow report.
- **Weather:** the storm slider calls the director's `SetStormOverride` (negative releases it); the look
  buttons call `PushLookOverrideAtRoadM(RoadM, 1 s)`. No god mode, no fighting the director.
- **Status:** the right column ends with `GetRecentEventLog(10)` (events, station, debug, look).
- **Human-mode beats** (B20–B23) teleport the carrier. They fire only in FlowState Human, unless
  they are triggered, which forces them.

## The debug C++ (integrated in SaskartaCore by CPPBATCH, 2026-09-28; built at the next closed-editor build)

The former `Tools/GameFlow/cpp_queue/lane5_debug/` files are now in the plugin (`SaskartaDebugTools.h/.cpp`,
runner header). Until the plugin is rebuilt none of it exists in the editor.

- `USaskartaEventRunner::ResetBeat(Id)`, `ResetAllBeats()` (in memory: the Continue save is never written),
  `ArmBeat(Id, LeadM = 30)`, `GetRunningBeatId()`, `HasBeatFired(Id)`, `ForceReleaseInput()`;
  - `ArmBeat` on a road beat teleports LeadM before it and leaves the mark behind it; a beat closer than LeadM
    to the dock is armed at the dock. On a flow beat (B01 is `flow:first_boot`) it clears the one-shot so the
    next `ReportFlow` of that event fires it (`Saskarta.Beat B01_BOOT_HANDOVER` fires it now).
- `USaskartaDebugLibrary::GetRecentEventLog(N)` (LogSaskartaEvents, LogSaskartaStation, LogSaskartaDebug,
  LogSaskartaLook), `ResetBeat`, `ResetAllBeats`, `ArmBeat`, `GetRunningBeat`;
- the dotted console commands `Saskarta.Debug`, `Saskarta.TP`, `Saskarta.Beat`, `Saskarta.Skip`,
  `Saskarta.ResetBeats`, `Saskarta.Arm <beat> [lead_m]`, and `Saskarta.Events.ReleaseInput`;
- the lighting director's `PushLookOverride(Name, BlendS)`, `PushLookOverrideAtRoadM(RoadM, BlendS)`,
  `PopLookOverride(BlendS)`, `PushFogOverride(Mult, BlendS)` and `SetStormOverride(x)` (negative releases):
  the debug look buttons and storm slider should call these instead of god mode + SetRoadProgress / the MPC.

Done after that build (LANE5): all of the above is wired in `gen_debug_specs.py`, the "tp before <id> at <m> m"
log text is fixed, and CM_Saskarta / WBP_Saskarta_Debug are rebuilt (compile clean).

## Build / rebuild

```bash
python Tools/GameFlow/gen_debug_specs.py            # specs + Tools/GameFlow/editor/cm_saskarta_post.py
# editor lane, holding a lease on asset:/Game/SaskartaGaea/GameFlow/Debug, no PIE:
node <lane>/ui_build.mjs Tools/GameFlow/specs/WBP_Saskarta_Debug.tree.json [--create]
node Tools/GameFlow/bpgraph.mjs build --reset-graphs Tools/GameFlow/specs/CM_Saskarta.json Tools/GameFlow/specs/WBP_Saskarta_Debug.graph.json
python_run Tools/GameFlow/editor/fix_array_nodes.py   # IMMEDIATELY: until it runs, CM_Saskarta has compile errors
python_run Tools/GameFlow/editor/cm_saskarta_post.py  # Exec flags + the baked beat table, compile, save
```

- **Why `fix_array_nodes.py`.** Hayba places `KismetArrayLibrary` calls as plain `K2Node_CallFunction`
  nodes, so their wildcard pins never get a type. The script swaps each one for the node the editor
  itself spawns (`K2Node_CallArrayFunction`) and relinks it through the schema. Run it in the same shell
  command as the build: a Blueprint left with compile errors warns the user when they press Play.
- **Wiring into the game** (a brief `PC_Saskarta` lease):
  - `PC_Saskarta` class default `CheatClass = CM_Saskarta_C`;
  - the F9 line in `DefaultInput.ini`.

## Checks done in the editor (no PIE)

- Both Blueprints compile with 0 errors. The widget renders:
  `Saved/Screenshots/Hayba/LANE5_debug_menu.png` (1600×900).
- **The teleport maths,** from `road-profile.json`: for every beat, the landing point after
  `GoToRoadM(road_m + 0.5)` plus 30 m of spline back is 24.6–29.5 m of map distance before the beat.
  It is less on the steep Knees, because spline length is measured over the ground. That is always
  more than the 5 m the arm needs, except B01 (see above).

## What to test in PIE

1. Press F9. The menu opens. Close it with F9.
2. Click `B03_PROMISE`. The carrier lands about 30 m before the stones, on the ground, facing up-road.
   Drive forward: B03 fires once, and the log shows `armed beat reached, fired B03_PROMISE`.
3. Tick "trigger on teleport", then click `B06_ROAD_AHEAD`. It fires at once.
4. Speed ×10: the carrier drives fast. Speed ×1 brings it back.
5. God mode: drive off the road. There is no warning and no reboot.
6. Free-fly: the camera detaches. Press it again to return.
7. Console: `SaskartaTP 2500`, `SaskartaTP B10_DRY_CISTERN`, `SaskartaBeat B08_NUMBERED_STOP`, `SaskartaSkip`.
