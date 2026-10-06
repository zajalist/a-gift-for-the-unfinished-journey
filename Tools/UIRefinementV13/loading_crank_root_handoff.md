# Native loading crank handoff

Prepared only; no editor mutation, Content write, native build, runtime test or GPU work was performed. All authored files are inside the assigned UI refinement lane.

The engine charging wheel is `USaskartaMotorDiagram`, exposed as `/Script/SaskartaCore.SaskartaMotorDiagram`. Its authored gameplay name is `MotorMechanism` under `MotorPhosphor` in `/Game/SaskartaGaea/GameFlow/UI/WBP_Saskarta_Motor`, parent `/Script/SaskartaCore.SaskartaMotorResonanceWidget`. Native source is `Plugins/SaskartaCore/Source/SaskartaCore/Private/SaskartaMotorDiagram.cpp`; declarations are `Public/SaskartaMotorResonance.h`.

## Root-owned native integration

`loading_crank_native/root_native.patch` proposes a shared `DrawCrank` function inside the existing Slate leaf. Charging keeps its wheel center, radii, six spokes, pin, top mark, accepted timing arc, input glyph and gameplay clock. The loading branch uses that same drawing with center `[92,83]`, a readiness ring and 512px line to its right. The leaf remains a single inexpensive drawing. It exposes `PresentLoading(float Readiness)` and editable `bLoadingPresentation`, which must be true on the authored loading instance before Slate construction. Loading mode returns before all charging captions, glyphs and gameplay instructions. The loading instance never calls `Configure`, so it requests no motor glyph textures or font. Desired size is 720x164. Loading stores no timer or input processor.

Readiness drives wheel phase, readiness ring and bar fill. `1.75 * 2pi * fraction - pi/2` gives visible wheel movement between readiness samples; phase can stop or reverse. It does not advance from elapsed time. Same-value samples do not invalidate the native leaf. The root can regenerate proposal copies from current source using `prepare_loading_crank_proposal.ps1`, which writes only this lane. Base hashes identify the original source used. Do not copy an entire proposal source over a newer concurrent source edit without reconciling it.

## Native UMG installation

`loading_crank_native_packet.json` contains schema-checked Hayba tool arguments. The known root is `RootCanvas` (CanvasPanel), confirmed by `Saved/Verification/startup_presentation_20261001/finalization-v2.json` and `live_completion_20261001/notifications_direct_v13/18_loading_before.json`. This is historical evidence; perform packet preflight before applying. Existing variable names retained: `ProgressFill`, `EmberGlow`, `PreparationStage`, `ReadinessChecks`, `LoadingHint`, `LoadingDrive`, `LoadingSteer`, `LoadingLook`. Retain their identity because existing graph nodes reference them.

The packet makes `LoadingBackdrop` opaque black, full viewport, z0; collapses old `EmberGlow`, duplicate `LoadingTrackBox`, and the tutorial controls row plus children. It adds only `LoadingCrankSafeScale -> LoadingCrankDesignSize -> LoadingCrank` under `RootCanvas`, marks `LoadingCrank` as a variable, and uses the native class path. The proposed native mode has no car dependency. Root integrates the Gaussian lane's car as a foreground widget above z0; preserve the black alpha1 backdrop.

## Exact generator integration

Primary contract: the loading line and wheel represent readiness of the current named phase, consistent with `ReadinessChecks`. This avoids the old title aggregate `0.5 + 0.5 * titleFraction` falsely claiming road success after a road timeout. Leave controller readiness gates, phase transition, timeout, focus and skip behavior intact.

In `enhance_widget`, add `CrankTarget` and `CrankShown`, both float default0. In `SetReadiness`, reuse its existing `clamp.ReturnValue` (0..1) to store `CrankTarget`. Its execution chain becomes `entry.then -> setCrankTarget.execute -> stageSet.execute -> checksSet.execute`. Add `setCrankTarget = {"set":"CrankTarget"}` and link `clamp.ReturnValue -> setCrankTarget.CrankTarget`. On a phase change the actual current phase may begin with fewer checks; dropping or reversing is truthful. Existing stage and count text already state this contract.

In `Step`, reuse `dt.StepInterval` and `rate.FillRate` to ease `CrankShown` toward `CrankTarget`. Add nodes:

```json
{
  "crankShown": {"get":"CrankShown"},
  "crankTarget": {"get":"CrankTarget"},
  "crankEase": {"call":"FInterpTo","class":"/Script/Engine.KismetMathLibrary"},
  "setCrankShown": {"set":"CrankShown"},
  "crankWidget": {"get":"LoadingCrank"},
  "presentCrank": {"call":"PresentLoading","class":"/Script/SaskartaCore.SaskartaMotorDiagram"}
}
```

Remove only `setScale.then -> setGlow.execute`; add these links:

```json
[
  ["setScale.then","setCrankShown.execute"],
  ["crankShown.CrankShown","crankEase.Current"],
  ["crankTarget.CrankTarget","crankEase.Target"],
  ["dt.StepInterval","crankEase.DeltaTime"],
  ["rate.FillRate","crankEase.InterpSpeed"],
  ["crankEase.ReturnValue","setCrankShown.CrankShown"],
  ["setCrankShown.then","presentCrank.execute"],
  ["crankWidget.LoadingCrank","presentCrank.self"],
  ["crankEase.ReturnValue","presentCrank.Readiness"],
  ["presentCrank.then","setGlow.execute"]
]
```

The hidden existing aggregate progress graph may remain for compatibility. Do not copy `FadeOut.setTarget.Target=1` into `CrankTarget`, and do not clamp the displayed crank fraction to the old `0.96`. Short easing moves toward measured readiness and stops there; time cannot produce a new target. Polling remains in `PC_Saskarta.PollRoad/PollTitle`, using `/Script/SaskartaCore.SaskartaReadiness.GetReadiness` and `ComputeFraction`, never widget-owned repeated readiness collection. `Step` remains the widget's existing 0.033s timer and existing `Destruct` cleanup removes it. The loading car may animate independently without changing readiness.

If a combined ten-check line is preferred, persist actual road fraction on each road poll and combine `(lastRoadFraction + currentTitleFraction)/2`; retain a below-full result on timeout. Do not assume road fraction1 after timing out. This alternate contract needs root-owned controller changes; the primary current-phase design does not.

## Dependencies and acceptance

Readiness uses five conditions: world partition streaming complete, PCG idle, pending shader/PSO count0, textures settled, grass instance count stable. `ComputeFraction` shares the same value consumed by existing readiness gate graphs. Do not create a second loader or change the gate thresholds to animate the presentation.

Native charging still uses existing glyph paths `/Game/SaskartaGaea/UI/Prompts/Light/T_Prompt_Key_E`, `Key_A`, `Key_D`, `Pad_A`, `Pad_DPad_Left`, `Pad_DPad_Right` and terminal font `/Game/SaskartaGaea/GameFlow/UI/Fonts/Font_Terminal.Font_Terminal`. Loading uses none of these textures, so it teaches no controls before title. The car effect's dependency list belongs to the Gaussian lane.

Root must rebuild native code before Hayba reflects the new property/function, then author native UMG, regenerate the exact graph fragment in canonical generators, compile/save, read back all properties and roots, inspect actual loading and actual charging frames, and preserve fire -> Tripo -> Hayba -> loading -> title. Fresh screenshots should show black viewport corners, no map, Gaussian car, shared crank, and no tutorial glyphs. Runtime readiness stalled/regressed/timed-out samples must leave the charge line below-full or reverse appropriately; a timeout transition may fade without claiming full readiness.

Hayba schema discovery performed: `ui_build_tree`, `ui_add_element`, `ui_set_widget_properties`, `ui_set_slot_layout`, `ui_set_variable`, `ui_compile_widget`, `ui_save_widget`, `ui_query`, `ui_layout_snapshot`, plus blueprint node/connect/pin/inspect contracts. Tool schemas validate argument names; they do not prove runtime property acceptance or compiled native reflection. Those remain root execution receipts.
