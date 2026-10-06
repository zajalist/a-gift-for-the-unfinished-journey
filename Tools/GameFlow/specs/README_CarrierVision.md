# BPC_CarrierVision: design notes

`BPC_CarrierVision` is the presentation component on `PC_Saskarta` (`/Game/SaskartaGaea/GameFlow/BPC_CarrierVision`, parent `/Script/Engine.ActorComponent`). It owns the vision post-process MID, the three screens, the carrier sounds, every sequence duration and the boot text. It never changes input, the view target or the pawn; those belong to `PC_Saskarta`.

Three spec files make up this graph:

| File | Builds |
|---|---|
| `BPC_CarrierVision.json` | The component: 69 variables, 20 functions, 312 nodes, 369 links |
| `WBP_Saskarta_BootLog.graph.json` | The retro boot terminal on the boot log widget: `ConfigureTerminal`, `ClearTerminal`, `BeginTerminal`, `TypeLine`, `PrintLine`, `SetBlackOpacity` and the timer-driven typewriter (39 variables, 15 functions, 294 nodes, 333 links). Design, layout and timing: `Tools/GameFlow/RETRO_BOOT.md` |
| `WBP_Saskarta_Subtitle.graph.json` | `SetShown(bShow)` on the warning subtitle widget |

The widget helpers exist because Hayba's variable nodes are self-only (`VariableReference.SetSelfMember`), so the component cannot read `BootBlack`, the terminal's text blocks or `SubtitleText` from outside the widget. Each widget exposes a function that works on its own widget variables instead.

## Public API

`PC_Saskarta` calls these functions. Each one's target is the `CarrierVision` component, and the call class is `/Game/SaskartaGaea/GameFlow/BPC_CarrierVision.BPC_CarrierVision_C`.

| Function | Called from | What it does |
|---|---|---|
| `SetVisionVolume(Volume: PostProcessVolume)` | `BeginTitle`, before `Setup` | Stores the level's `BP_CarrierVisionVolume` actor in `VisionVolume` |
| `Setup()` | `BeginTitle` | Creates the MID, pushes the timing params and tint, and adds the MID to the volume at weight 0. Then creates Title, Subtitle and BootLog owned by the PC, adds them to the viewport at Z 0, 10 and 100, and collapses Subtitle and BootLog |
| `ShowTitle()` | `BeginTitle` | Title visible, opacity 1, enabled |
| `GetTitleWidget() -> Widget` (pure) | `BeginTitle` | The title widget, for `SetInputMode_UIOnlyEx.InWidgetToFocus` |
| `DisableTitle()` | `StartGame` | `SetIsEnabled(false)` on the title, so Start and Quit fire once |
| `FadeToBlack()` | `StartGame` | Fades the boot log in over `FadeToBlackTime`, then calls `BreachBlack` (see below) |
| `RemoveTitle()` | `HandleBlackout` (Booting) | `RemoveFromParent` on the title. The reference is kept |
| `PlayBoot(Kind: name)` | `HandleBlackout` (`FirstBoot`), `TryRespawn` (`Reboot`) | Starts the retro terminal (banner, memory test on first boot, typed lines), then power-on. Any `Kind` other than `Reboot` shows the first-boot text. See `Tools/GameFlow/RETRO_BOOT.md` |
| `SkipBoot()` | `PC_Saskarta.PollOpeningSkip` while Booting | Latches a FirstBoot skip until `PlayBoot` has initialized `BootKind`, clears the pending line timer, and calls the normal `PowerOn` path once. The resulting `VisionOnline` callback still performs the regular first-boot story handoff. |
| `ShowWarning(bShow: bool)` | `HandleZoneChanged`, `HandleBreach` | Fades the subtitle in or out over `SubtitleFadeTime` |
| `PlayBreach()` | `HandleBreach` | Glitch, CRT power-off, black, then `HandleBlackout` |

The component calls back into its owner through `GetOwner`, then a cast to `PC_Saskarta_C` (output pin `AsPC Saskarta`), then:

- `HandleBlackout()`: the screen is fully black. `BreachBlack` calls it at the end of both the Start fade and the breach.
- `HandleVisionOnline()`: power-on has finished and the carrier can move. `VisionOnline` calls it.

If the cast fails, `PrintString` names the missing call. `Setup` then creates no widgets.

The remaining functions are internal. `SetVisionWeight`, `StartFade`, `FadeStep` and `StopHum` are helpers. `BreachPowerDown`, `BreachBlack`, `BootLineStep`, `PowerOn`, `VisionOnline` and `CleanUp` are timer targets, and they take no parameters, because `K2_SetTimer` refuses a function with parameters (`KismetSystemLibrary.cpp:698`).

## Sequences

The retro terminal (2026-09-26) replaced the fixed 0.45 s line cadence. The full tables, with nominal and simulated worst-case times, are in `Tools/GameFlow/RETRO_BOOT.md` section 3. In short (nominal; 60 fps worst case in brackets):

**Start to first boot.** t = 0 is Start pressed.

| t | Step |
|---|---|
| 0.000 | `DisableTitle`. `FadeToBlack` calls `ClearTerminal`, shows the boot log at opacity 0, starts `StartFade(BootLog, 0 -> 1, FadeToBlackTime)` and sets `StepTimer -> BreachBlack` after `FadeToBlackTime` |
| 0.600 | `BreachBlack` -> `HandleBlackout` -> `PlayBoot(FirstBoot)`: banner, memory count-up to 1.50, memory `[ OK ]` and beep at 1.64 |
| 1.850 / 2.535 / 3.512 / 4.488 | `BootLineStep` types each line (teletype burst); each status lands at most `LineHold` after its line starts |
| 5.516 (5.550) | `PowerOn` plays `SfxContactor`, `SfxPowerOn` and `SfxCrtOff`, sets `VisionStart = now`, `VisionMode = 1` and weight 1, clears and collapses the boot log in the same frame, and fades the fan hum |
| 6.116 (6.150) | `VisionOnline` calls `HandleVisionOnline` |
| 7.116 (7.150) | `CleanUp` sets the weight to 0 |

Holding Space or Gamepad Right while the opening is running latches a skip request. If it is still held
after the player selects Begin on the title, the first-boot terminal narrative also skips; the normal
vision power-on, ground check and `CIN_01_DIRECTIVE` handoff remain in place. A skip is never applied
to reboot lines.

**Breach to reboot.** t = 0 is `HandleBreach`.

| t | Step |
|---|---|
| 0.000 | `PlayBreach` sets `VisionStart = now`, `VisionMode = 0`, `GlitchSeed = RandomFloat * 100` and weight 1, and plays `SfxStatic`. It clears `LineTimer` and `StepTimer`, then sets `StepTimer -> BreachPowerDown` after `RampTime` |
| 0.800 | `BreachPowerDown` plays `SfxPowerDown` and sets `StepTimer -> BreachBlack` after `OffTime` |
| 1.100 | `BreachBlack` clears the terminal, makes the boot log opaque and shows it, then calls `HandleBlackout`. The PC respawns the carrier and calls `PlayBoot(Reboot)`: `WARM RESTART` banner, reboot lines 1-2 replayed at once (`[FAIL]` on the fault) |
| 1.400 / 2.267 | Reboot lines 3 and 4 typed |
| 3.259 (3.283) | `PowerOn` |
| 3.859 (3.883) | `VisionOnline` calls `HandleVisionOnline` |
| 4.859 (4.883) | `CleanUp` |

After each typed line, `BootLineStep` stores `LineHold = Len(line) / CharsPerSecond + StallBudget + StatusDelay`, the latest time that line's status can land. The next line then starts `LineGap` later, or `PowerOn` starts `FinalHold` later. The vision chain (`PowerOn -> VisionOnline -> CleanUp`, `BootBlack + OnTime`, then `Residual`) is unchanged, so the shader timeline still lines up. If `TryRespawn` has to retry, everything after `BreachBlack` shifts by the retry time, because the PC calls `PlayBoot` only after the carrier is placed.

## Timers

There are three handles. Each one is cleared with `K2_ClearAndInvalidateTimerHandle` (fed by a variable get, because the pin is by-ref) immediately before it is set again. Each `K2_SetTimer` is linked to a `self` node.

- **`StepTimer`** runs the one-shot sequence steps: `FadeToBlack -> BreachBlack`, `PlayBreach -> BreachPowerDown -> BreachBlack`, `BootLineStep (last line) -> PowerOn -> VisionOnline -> CleanUp`. Starting any sequence overwrites a pending step, so a breach during the residual cancels the old `CleanUp`.
- **`LineTimer`** is a one-shot re-armed by each `BootLineStep`: first after `FirstLineDelay` (first boot) or `RebootFirstLineDelay` (reboot) from `PlayBoot`, then after `LineHold + LineGap` for each following line. Re-arming from inside its own callback is safe: the handle is cleared first (`InternalClearTimer`, Executing case) and a new timer is set. `PlayBreach` and `PlayBoot` also clear it, so a stale line can never appear during another sequence. The typewriter, cursor blink and memory count run on the widget's own timers (`RETRO_BOOT.md` section 5).
- **`FadeTimer`** is the looping fade tick: 0.016 s, `bMaxOncePerFrame`. It runs only while a fade is in progress.

Each one-shot step can fire up to one frame late, and the delays add up. Worst case at 60 fps, control returns 0.067 s late on the first boot and 0.083 s late on a reboot. The shader stays in sync regardless, because every shader phase is timed from `VisionStart`, and that is set in the same frame as the Blueprint step that starts the phase.

Every timer delay goes through `FClamp(x, 0.01, 60)`. A zero or negative tuning value would otherwise stop the timer from ever being created (`K2_SetTimerDelegate` warns, then `InternalSetTimer` invalidates the handle for a rate of 0 or less), and the screen would stay black. `StartFade` clamps `Duration` the same way, so `FadeStep` never divides by zero.

## Vision material and volume

- `Setup` creates the MID from `/Game/SaskartaGaea/GameFlow/Materials/M_PP_CarrierVision.M_PP_CarrierVision`. It pushes the scalars `RampTime`, `OffTime`, `BootBlack`, `OnTime` and `Residual` and the vector `OpticsTint`. `PlayBreach` and `PowerOn` set `VisionStart` (from `GetTimeSeconds`, the same game time as the material's Time node), `VisionMode` (0 = breach, 1 = boot) and `GlitchSeed`. These names are the contract with `Shaders/CarrierVision.hlsl` and the material.
- The effect is switched only by the MID's blendable weight on the volume, through `AddOrUpdateBlendable(MID, weight)`: 0 when idle, 1 during a sequence. With weight 0 the renderer skips the blendable, so it costs nothing when idle. `SetVisionWeight` is the one place that does this. It checks `IsValid(VisionVolume)` first and prints a warning if the volume is not set.
- The component does not look up `VisionVolume` itself. It cannot take the first element of an array from `GetAllActorsWithTag`, because Hayba cannot author array access. `GetActorOfClass(PostProcessVolume)` is not reliable either, because the level also has `PPV_Saskarta_Mood`. Instead, `PC_Saskarta.BeginTitle` finds the unique `BP_CarrierVisionVolume` with `GetActorOfClass`, casts it to `PostProcessVolume` and calls `SetVisionVolume` before `Setup`.
- The volume's own `BlendWeight` must stay 1 (`BP_CarrierVisionVolume.json` sets it), because the renderer multiplies it with the blendable weight. Do not place the material as a blendable on the volume in the editor. The runtime MID must be the only one.

## Screens

- **Boot log.** `FadeToBlack` fades the whole `WBP_Saskarta_BootLog` widget's render opacity rather than `BootBlack` alone. `BootBlack` is kept at opacity 1 (`Setup` calls `SetBlackOpacity(1)`) and the terminal is blank during the fade, so the result looks the same, and `FadeStep` stays generic over a `UMG.Widget`. `FadeToBlack` and `BreachBlack` both call `ClearTerminal`, so neither designer preview text nor the last boot line flashes when the black layer comes back. `PowerOn` calls `ClearTerminal` (which also stops the widget's typing, blink and memory timers) and collapses the boot log in the same frame that the MID's boot mode starts, and the shader's first `BootBlack` seconds are black, so there is no flash.
- **Subtitle.** `ShowWarning(true)` calls `StartFade(Subtitle, 0 -> 1)`, then `SetShown(true)` (Not Hit-Testable). `ShowWarning(false)` calls `StartFade(Subtitle, 1 -> 0)`. When a fade ends with `FadeTo < 0.001`, `FadeStep` collapses the widget it faded, so a hidden subtitle is Collapsed.
- **Title.** Created at Z 0 by `Setup` and left Visible. `ShowTitle`, `DisableTitle`, `RemoveTitle` and `GetTitleWidget` exist because the PC cannot read the `TitleWidget` variable. Start and Quit are wired in `WBP_Saskarta_Title.graph.json`.
- **One fade at a time.** There is one fade channel (`FadeWidget`, `FadeTimer`). A new `StartFade` takes over from the old one, and the new fade starts at its given `FromOpacity`. In practice, only the subtitle reversing within 0.25 s causes a visible jump; the 1 m hysteresis between warn and clear makes that rare. The boot log fade happens only on the title screen, when the subtitle is Collapsed.

## Boot text

The terminal text is data on this component. The retro terminal design is in `Tools/GameFlow/RETRO_BOOT.md`.

| Variables | First boot (`Boot*`) | Reboot (`Reboot*`) |
|---|---|---|
| Header | `BootHeader`: HIGHLAND ASSISTIVE CARRIER  UNIT 07  ROM 2.07 | `RebootHeader`: ... ROM 2.07  WARM RESTART |
| Sub-header | `BootSubHeader`: (C) HIGHLAND ROUTE AUTHORITY | same |
| Memory test | `MemLabel` CORE MEMORY TEST, `BootMemoryKB` 640 | `RebootMemoryKB` 0 (no test) |
| Line 1 / result | CONTACTOR - CLOSING / `OK` | FAULT - ROUTE BOUNDARY EXCEEDED / `FAIL` (printed at once) |
| Line 2 / result | HANDOVER - CARRIER 06 -> CARRIER 07 / `OK` | EMERGENCY SHUTDOWN - COMPLETE / `OK` (printed at once) |
| Line 3 / result | LOAD - 1 CAPSULE / ARCHIVE / 36.6 C / `OK` | REINITIALIZING - CARRIER CORE / `OK` |
| Line 4 / result | ROUTE LOCK - ÂLAAWB / `OK` | ROUTE LOCK - RESTORED / `OK` |

The first-boot lines are storyline beat B01's handover lines in ASCII, except the Â of the author's ÂLAAWB (2026-09-28), which both terminal fonts have (`check_terminal_glyphs.py`). A result is a name: `OK`, `FAIL` or `NONE`.

`BootLineStep` picks the line and result with four `select` nodes (4 options each, `Index <- BootLine`), then `SelectText` / `SelectName` (`A = reboot`, `B = boot`, `bPickA = EqualEqual_NameName(BootKind, 'Reboot')`). Blueprint re-evaluates a pure node for each impure node that uses it, so the order matters:

1. The selects are read when `TypeLine` runs and when `LineHold` is set, both before the increment.
2. The increment reads its own `BootLine` get, before the set.
3. The "more lines" test reads a fresh `BootLine` get, after the set.
4. The next timer's delay reads `LineHold` (a variable), not the selects, because after the increment the selects would measure the next line.

No text pin in these specs has a literal. Blank text comes from the widget's `BlankText` variable, because Hayba refuses an empty string as a pin literal and cannot read text-pin literals back.

## Sounds

| When | Sound |
|---|---|
| Breach starts | `SfxStatic` (0.8 s, the glitch ramp) |
| `RampTime` into the breach | `SfxPowerDown` (CRT off) |
| `PlayBoot` | `SfxCrtOn` (terminal tube degauss + flyback), `SfxDriveSeek`, and `SfxFanHum` spawned into `TermHum` |
| Each typed boot line | `SfxTeletype1..4`, selected by `BootLine` (one burst per line) |
| `PowerOn` | `SfxContactor`, `SfxPowerOn` and `SfxCrtOff` together; `StopHum` fades `TermHum`. The 0.6 s power-on hum covers black, then dot, line and full frame (`BootBlack + OnTime`) |
| Widget (its own timers) | `SfxLineFeed` (banner, replayed lines), `SfxKey1..6` (status stamps), `SfxOkBlip` (memory `[ OK ]`, the one beep) |

The plan's function list has no step for `SfxPowerDown` or `SfxPowerOn`. `BreachPowerDown` is a one-shot step at `RampTime` that plays the power-down and then schedules `BreachBlack` after `OffTime`, so `BreachBlack` stays at `RampTime + OffTime`. All one-shots use `PlaySound2D`, the fan hum uses `SpawnSound2D`, and a missing asset plays nothing. The terminal sounds live in `/Game/SaskartaGaea/Audio/Terminal/` (`Tools/Audio/make_terminal_sfx.py`).

## Deviations from the plan

1. There are seven extra functions. `SetVisionVolume`, `GetTitleWidget`, `DisableTitle` and `RemoveTitle` implement the PC contract, which exists because Hayba cannot read or set another object's variables. `SetVisionWeight` and `StartFade` are internal helpers. `BreachPowerDown` gives the power-down sound its time.
2. There is one extra variable: `SubtitleFadeTime` (0.25 s, from the spec's "0.25 fade in/out"). The retro terminal added its own set (`RETRO_BOOT.md` section 6).
3. `VisionVolume` is handed over by the PC through `SetVisionVolume` instead of being found by tag.
4. The first-boot fade targets the boot log widget, not the `BootBlack` image.
5. The retro terminal replaced the plan's fixed `LineInterval` / `PowerOnDelay` with a per-line schedule (`LineHold`), and the boot log's two lines with a typed terminal (`RETRO_BOOT.md`).

## What other assets and the build must provide

- **Widgets (T5).** `WBP_Saskarta_BootLog` must be laid out as in `RETRO_BOOT.md` section 4 and expose `BootBlack`, `TermHeader`, `TermSubHeader`, `MemLabelText`, `MemCountText`, `MemStatusText`, `Row0Text`-`Row5Text` and `Row0Status`-`Row5Status` as variables (`ui_set_variable is_variable=true`), and be compiled, before `WBP_Saskarta_BootLog.graph.json` is built. `WBP_Saskarta_Subtitle` needs nothing exposed, because `SetShown` works on the widget itself.
- **Material (T2).** The parameter names above, and the `VisionMode` meaning: 0 = breach (black from `RampTime + OffTime`), 1 = boot (black for `BootBlack`). Guard divisions by the timing parameters, because designers can set them to 0.
- **Audio (T3).** `/Game/SaskartaGaea/GameFlow/Audio/SFX_Carrier_{Static,PowerDown,Contactor,PowerOn}` and the terminal set in `/Game/SaskartaGaea/Audio/Terminal/` (manifest in `Saved/GameAudio/Terminal/`) must exist before the variable defaults are applied. `SFX_Carrier_BootTick` is no longer used.
- **Material.** `M_UI_CRTTerminal` (`Tools/GameFlow/build_terminal_material.py`) is the boot log RetainerBox's effect material.
- **Level (T7).** Exactly one `BP_CarrierVisionVolume` must be placed. Its `BlendWeight` stays 1 and it has no blendables.
- **Build (T6).** Build in one `bpgraph.mjs build` run that includes `PC_Saskarta.json`, `BPC_CarrierVision.json` and both widget graph specs. Pass 1 then declares `HandleBlackout`, `HandleVisionOnline`, the boot log's terminal functions and `SetShown` before any graph is wired, which resolves the circular reference between the PC and this component. `M_PP_CarrierVision`, `M_UI_CRTTerminal`, the three widgets and the sounds must already exist. Delete the boot log's old `SetLines` function (and then `BootStatus` / `BootDetail`) before the build: bpgraph never removes functions.
- **Pin names with spaces.** The select options are `Option 0` to `Option 3`, and the cast output is `AsPC Saskarta`. `bpgraph.mjs` accepts both.

## Exec outputs left unconnected on purpose

- `FadeStep: ifDone.then`: the fade is still running, so there is nothing more to do this tick.
- `FadeStep: ifFadedOut.else`: the fade ended visible, so the widget stays shown.
- The boot log widget's own intentional ones are listed in `RETRO_BOOT.md` section 5.
- `Setup`, `BreachBlack`, `VisionOnline`: `noPC.then` after the warning print.

Every other unconnected `then` is the last node of its function.

## Offline verification

- `node Tools/GameFlow/bpgraph.mjs check Tools/GameFlow/specs/*.json`: all nine specs pass.
- A scratch semantic checker and simulator interpreted these three JSON files directly. It checked every pin name, direction and type against the UE 5.8 signatures (`KismetSystemLibrary.h`, `GameplayStatics.h`, `KismetMathLibrary.h`, `KismetMaterialLibrary.h`, `MaterialInstanceDynamic.h`, `PostProcessVolume.h`, `ActorComponent.h`, `Widget.h`, `UserWidget.h`, `TextBlock.h`, `K2Node_Select.cpp`, `K2Node_DynamicCast.cpp`, `K2Node_CreateWidget.cpp`). It also checked that every impure node is reachable, that every required input is linked or given a literal, that timer targets are parameterless, and that each handle is cleared before it is rescheduled. It matched every `PC_Saskarta.json` call into this component: name, pins, pure or impure. It then ran the title, first boot, warning, breach and reboot at 60 fps with the plan's PC behaviour, plus these cases: no volume, wrong owner, all timings 0, a 1 s hitch during the lines, and a breach during the lines. All checks passed.
- **Retro terminal edit (2026-09-26).** Both specs pass `bpgraph.mjs check`. A second scratch semantic check covered the new graphs: pin names and directions against the UE 5.8 signatures, component-to-widget calls against the widget's declared functions, reachability, required inputs, variables, and parameterless timer targets. A frame-quantised simulation covered the new schedule at 60 and 30 fps with random stalls. Details are in `RETRO_BOOT.md` section 10.
- **Not yet verified live.** Hayba compile, readback and a playtest belong to T6 and T8.
