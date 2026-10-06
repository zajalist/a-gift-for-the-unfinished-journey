# GameFlow graph specs

Each `*.json` file here describes one Blueprint: its variables, its function signatures and every graph's nodes, links and pin literals. `Tools/GameFlow/bpgraph.mjs` builds the Blueprint in the live editor from the file. The format and the list of verified engine calls are in `docs/superpowers/plans/2026-09-26-saskarta-game-flow.md`. JSON has no comments, so the explanations live in this file. Each asset has its own section below, and other specs add their own sections.

Conventions used by every spec:

- Pin names are UE parameter names. The exec pins are `execute`/`then`, a branch has `then`/`else`, and a cast has `then`/`CastFailed`. A call's target is `self`, and a return value is `ReturnValue`.
- A cast's output pin is `As` followed by the target class's display name, and that name can contain a space. These are the exact pin names from `K2Node_DynamicCast::AllocateDefaultPins` and `FDisplayNameHelper` in UE 5.8:
  - `PC_Saskarta_C` gives `AsPC Saskarta`.
  - `SplineComponent` gives `AsSpline Component`.
  - `CapsuleComponent` gives `AsCapsule Collision`, because the class has `DisplayName="Capsule Collision"` metadata.
- Some exec outputs are left unconnected on purpose: a guard's `else` or a cast's `CastFailed` that should do nothing. Every impure node is reachable from its graph's entry or event. Every data input is linked, given a literal under `defaults`, or has a usable C++ default. World-context pins are never linked by hand. In the component they are hidden and default to self. Inside the function library, the compiler connects them to the caller's context (`K2Node_CallFunction::ExpandNode`).
- Functions called only by timers take no parameters.

## BFL_SaskartaRoad

This is a Blueprint Function Library (`/Script/Engine.BlueprintFunctionLibrary`) at `/Game/SaskartaGaea/GameFlow/BFL_SaskartaRoad`. It holds only math, so it can be tested from editor Python through `unreal.get_default_object(cls).call_method(...)`, passing the world context first. See `Tools/GameFlow/tests/test_road_math.py`.

### ClassifyTetherZone (pure)

`ClassifyTetherZone(Distance, CurrentZone, WarnDistance, ClearDistance, BreachDistance) -> NewZone`. The zone is one of the name values `Safe`, `Warning` or `Breach`.

The exec path is just `entry.then -> result.execute`. The rest of the graph is four comparisons feeding a chain of `SelectName` nodes:

1. `overBreach = Distance > BreachDistance`
2. `wasWarning = CurrentZone == 'Warning'`
3. `underClear = Distance < ClearDistance`
4. `overWarn = Distance > WarnDistance`
5. `fromWarning = underClear ? 'Safe' : 'Warning'`. This is the hysteresis: once warned, the zone only clears below `ClearDistance`.
6. `fromSafe = overWarn ? 'Warning' : 'Safe'`
7. `held = wasWarning ? fromWarning : fromSafe`
8. `NewZone = overBreach ? 'Breach' : held`

The comparisons are strict, so exactly 1000 cm from `Safe` stays `Safe`, and exactly 2000 cm is not a breach. A `CurrentZone` of `Breach` is treated like `Safe`. The function is idempotent, `Classify(D, Classify(D, Z)) == Classify(D, Z)`, whenever `ClearDistance <= WarnDistance`.

### ComputeRoadRespawn (impure: it traces)

`ComputeRoadRespawn(Road, From, CapsuleHalfHeight, TravelSign, StepCm) -> Found, Location, Rotation`.

Pure data chain:

- `key = Road.FindInputKeyClosestToWorldLocation(From)`
- `L = Road.GetSplineLength()`
- `forward = Road.GetDistanceAlongSplineAtSplineInputKey(key) + StepCm * TravelSign`, `backward = keyDistance - StepCm * TravelSign`
- `D = FClamp(forward < 0 OR forward > L ? backward : forward, 0, L)`. When the step would run off an end of the road, the candidate steps the other way instead, so each retry near an end still tests a new spot (a clamped `forward` would re-test the end point every time).
- `S = Road.GetLocationAtDistanceAlongSpline(D, World)`
- facing: `ahead = FClamp(D + TravelSign * 300, 0, L)`, `behind = FClamp(D - TravelSign * 300, 0, L)`, chord = `location(ahead) - location(behind)`, then `BreakVector`, `MakeVector(X, Y, 0)`, `Conv_VectorToRotator`, `BreakRotator`, `MakeRotator(0, 0, Yaw)`. Only the yaw is kept, so the carrier stands upright facing up-road.
- The facing comes from positions, not from `GetTangentAtDistanceAlongSpline`: every `RoadSpline` point is CurveClamped with zero arrive/leave tangents (they also drive the road RVT and PCG, so they stay as they are). The tangent is therefore (0,0,0) at both ends (yaw 0) and noisy near the bend vertices. The 6 m chord is never zero: at an end one of its two points is clamped, the other is 300 cm in.

Exec path: `entry -> LineTraceSingle -> result`.

- The trace runs from `S + (0,0,1000)` to `S + (0,0,-5000)` on `TraceTypeQuery1` (Visibility), with no debug draw, `bTraceComplex=false` and `bIgnoreSelf=true`. Inside a function library, the compiler wires the world context to the caller.
- `Found` is the trace's return value.
- `Location = (Found ? ImpactPoint : S) + (0, 0, CapsuleHalfHeight + 2)`.
- `Rotation` is the yaw-only rotator.

The trace does not list the pawn in `ActorsToIgnore`: it starts 10 m above the road point, and the breach position it comes from is more than 20 m away.

## BPC_RoadTether

This is an ActorComponent at `/Game/SaskartaGaea/GameFlow/BPC_RoadTether`, added to `PC_Saskarta`. It does road math only. It never moves the pawn and has no UI. It reports to its owner by casting `GetOwner()` to `PC_Saskarta_C` and calling `HandleZoneChanged(NewZone)` or `HandleBreach()` on it. It finds the pawn through the owner cast followed by `K2_GetPawn`.

Variables:

| Variable | Type | Default |
|---|---|---|
| `Road` | SplineComponent reference | |
| `Zone` | name | `Safe` |
| `WarnDistance` | float | 1000 |
| `ClearDistance` | float | 900 |
| `BreachDistance` | float | 2000 |
| `CheckInterval` | float | 0.2 s |
| `TravelSign` | float | -1 (travel runs from spline point 54 toward point 0) |
| `bDebugDraw` | bool | false |
| `CheckTimer` | TimerHandle | |
| `LastDistance` | float | |
| `BreachLocation` | vector | |

**EventGraph.** `ReceiveBeginPlay` (the component's Begin Play) calls `FindRoad`.

**FindRoad.**

1. `GetActorOfClass(BP_Saskarta_Road_C)`.
2. A branch on `IsValid` of that actor. When it is valid, call `GetComponentByClass(SplineComponent)` on it, cast the result to SplineComponent, and set `Road`.
3. If the actor is missing (branch `else`) or the cast fails, `PrintString("Saskarta tether: road not found")` prints to the screen and the log for 10 s. `Road` stays empty. `CheckRoad` then shuts the tether down the first time it runs (see below).

**StartTether.**

1. Set `Zone = Safe`.
2. `K2_SetTimer(self, "CheckRoad", CheckInterval, looping)`, storing the handle in `CheckTimer`.

Calling it again is safe: `K2_SetTimer` finds the existing timer for the same object and function and restarts it rather than adding a second one.

**StopTether.** `K2_ClearAndInvalidateTimerHandle(CheckTimer)`. The handle is passed by reference from a variable get.

**CheckRoad.** This runs every 0.2 s while the tether is on.

1. Guard on `IsValid(Road)`. If the road is missing, call `StopTether`: the tether switches itself off, as the design requires.
2. Cast `GetOwner()` to `PC_Saskarta_C`. If the cast fails, call `StopTether`.
3. Guard on `IsValid(pawn)`. A missing pawn is treated as a temporary state, so nothing happens and the timer keeps running.
4. `P = pawn.K2_GetActorLocation()`.
5. `C = Road.GetLocationAtSplineInputKey(Road.FindInputKeyClosestToWorldLocation(P), World)`.
6. `LastDistance = Vector_Distance2D(P, C)`.
7. `New = BFL.ClassifyTetherZone(LastDistance, Zone, WarnDistance, ClearDistance, BreachDistance)`.
8. If `New != Zone` (`Not(EqualEqual_NameName)`), set `Zone = New`. Then read `Zone` back:
   - If it is `Breach`: `StopTether`, then `BreachLocation = P`, then `owner.HandleBreach()`.
   - Otherwise: `owner.HandleZoneChanged(Zone)`.

Blueprint re-evaluates a pure node for each impure node that uses it. That is why the zone after the change is read from a fresh `Zone` get after the set, and not from the classify node. The classify node is only read before `Zone` changes, so both of its reads see the same inputs.

**ComputeRespawn(StepCm) -> Found, Location, Rotation.**

1. Guard on `IsValid(Road)`.
2. Cast the owner to `PC_Saskarta_C`, take the pawn from `K2_GetPawn`, get its component with `GetComponentByClass(CapsuleComponent)`, and cast that to CapsuleComponent. The capsule's `GetScaledCapsuleHalfHeight()` is the `CapsuleHalfHeight` input.
3. `BFL.ComputeRoadRespawn(Road, BreachLocation, halfHeight, TravelSign, StepCm)`, and its three outputs go to the result.

If the road guard, the owner cast or the capsule cast fails, execution goes straight to the result without running `ComputeRoadRespawn`. Blueprint function locals start at zero, so the result is `Found=false` with a zero location and rotation. `PC_Saskarta.TryRespawn` already treats `Found=false` as "retry".

**Not in v1.** `bDebugDraw` is declared but no graph reads it yet. The line from the pawn to `C` with the distance is still to be added, and nothing in the tether is drawn.

**Build order.** This spec refers to `PC_Saskarta_C` (the cast and the two `Handle*` calls) and to `BFL_SaskartaRoad_C`. Both must already exist when this graph is built: `PC_Saskarta` needs `HandleZoneChanged(NewZone: name)` and `HandleBreach()` declared, and the BFL must have been compiled.

## PC_Saskarta

This is the player controller at `/Game/SaskartaGaea/GameFlow/PC_Saskarta`. Its parent is `/Game/FirstPerson/Blueprints/BP_FirstPersonPlayerController`, whose BeginPlay adds `IMC_Default` and `IMC_MouseLook`. The controller runs the flow `None -> Title -> Booting -> Playing -> Rebooting -> Playing`, and it is the only Blueprint that changes the input mode, the view target or the pawn's movement.

Components: `RoadTether` (`BPC_RoadTether`), `CarrierVision` (`BPC_CarrierVision`) and `TitleMusic` (`AudioComponent`).

| Variable | Type | Default |
|---|---|---|
| `FlowState` | name | `None` |
| `GroundTries` | int | 0 |
| `RespawnTries` | int | 0 |
| `RespawnStep` | float | 0 |
| `bIntroStarted` | bool | false |
| `IntroWidget` | `WBP_Saskarta_Intro` reference | |
| `IntroTimer` | TimerHandle | |
| `IntroStart` | float | 0 |
| `bStreamReady` | bool | false |
| `IntroMinTime` | float | 6.0 s (the hold lasts at least this long in total; spec section 6) |
| `IntroMaxTime` | float | 25.0 s (the whole intro, burn included, never runs longer) |
| `IntroPollInterval` | float | 0.25 s |
| `RevealLead` | float | 2.0 s (the title sequence starts this long before the reveal) |
| `RevealBurnTime` | float | 2.5 s (the burn-away) |

**EventGraph.** `ReceivePossess` ("On Possess") calls `K2_SetTimer(self, "BeginIntro", 0.05, not looping)` (Task L5; it called `BeginTitle` before the studio intro existed). There is no BeginPlay here, so the parent's BeginPlay (the input mappings) still runs. Possession happens at login, before BeginPlay, and the timer fires on the first ticks after it. The delay is not 0 because `K2_SetTimer` clears the timer when `Time <= 0`.

**BeginIntro** (Task L5). It runs once, guarded on `bIntroStarted`, and leaves `FlowState` at `None` so `BeginTitle`'s own guard still passes later:

1. `bIntroStarted = true`, then the pawn's movement mode to `MOVE_None` (the same `GetComponentByClass` + cast chain as `BeginTitle`; `CastFailed` continues). Without it the carrier could fall through terrain that has not streamed in during a 25 s hold.
2. `SetViewTargetWithBlend(GetActorOfClass(CineCameraActor), 0)`: the view, and so the World Partition streaming source, moves to the title camera while the black card hides it. Streaming then completes where the reveal will look.
3. `CreateWidget(WBP_Saskarta_Intro, self)`, stored in `IntroWidget`, and `AddToViewport(500)` (above the title at 0 and boot log at 100). `SetInputMode_GameAndUIEx(self, IntroWidget, DoNotLock)` keeps `SkipButton` focused while allowing the controller poll to see Space/Gamepad Right; movement and look are ignored until the later ground check restores them. Then `IntroWidget.PlayIntro()`.
4. `IntroStart = GetTimeSeconds()`, then `IntroTimer = K2_SetTimer(self, "PollIntro", IntroPollInterval, looping)`.

**PollIntro** (timer, every 0.25 s). Run 1 of the readiness gate: time, the cards and World Partition streaming. Run 2 swaps the streaming check for the C++ `USaskartaReadiness` from L7.

1. `bStreamReady = GetWorldSubsystem(WorldPartitionSubsystem)`, cast, `.IsAllStreamingCompleted()`. A world without World Partition fails the cast and counts as ready.
2. `elapsed = now - IntroStart`; `ready = elapsed >= IntroMinTime - RevealLead AND IntroWidget.IsHolding() AND bStreamReady`; `timedOut = elapsed >= IntroMaxTime - RevealLead - RevealBurnTime`.
3. On `ready OR timedOut`: stop `IntroTimer`; if it timed out, `PrintString` (log only) names the unmet condition; then `BeginTitle()` and `K2_SetTimer(self, "RevealIntro", RevealLead)`.

The intro accepts Space or Gamepad Right through a controller-owned 0.05 s poll. It requests each active card's existing skip path; the first request latches for the rest of the opening. The ember burn-away shortens to 0.25 s, the event/Hayba cards finish their normal fade-out, and time-only loading minimums are waived. Road and title `USaskartaReadiness` checks remain mandatory, and the title remains an explicit Begin choice. The intro uses GameAndUI so the poll receives keys, while movement and look remain ignored.

**RevealIntro** (timer). `IntroWidget.Reveal(RevealBurnTime)`. The widget burns away and removes itself.

**BeginTitle.** It runs once, guarded on `FlowState == None`. A four-way sequence keeps one failed step from skipping the others:

0. Set the pawn's movement mode to `MOVE_None`.
1. `SetIgnoreMoveInput(true)` and `SetIgnoreLookInput(true)`.
2. `CarrierVision.SetVisionVolume(GetActorOfClass(BP_CarrierVisionVolume_C))`, with the result cast to PostProcessVolume. This step runs before `Setup`.
3. The title itself, in order:
   - `CarrierVision.Setup`
   - `SetViewTargetWithBlend(GetActorOfClass(CineCameraActor), 0)`
   - `CarrierVision.ShowTitle`
   - `SetInputMode_UIOnlyEx(self, CarrierVision.GetTitleWidget(), DoNotLock)`
   - `bShowMouseCursor = true`
   - `TitleMusic.FadeIn(1.0)`
   - `FlowState = Title`

**StartGame.** The title's Start button calls it. It is guarded on `FlowState == Title`, then runs `FlowState = Booting`, `CarrierVision.DisableTitle`, `TitleMusic.FadeOut(1.5, 0)` and `CarrierVision.FadeToBlack`.

While Booting, a latched opening request (or a held skip key) calls `CarrierVision.SkipBoot`. The component waits until the FirstBoot `PlayBoot` path has set its boot kind, then clears the line timer and invokes `PowerOn` once. The regular `VisionOnline` callback, ground check and story handoff still run. `CIN_01_DIRECTIVE` is `HoldAlways`; holding Space or Gamepad Right into it uses the runner's normal skip path, whose final state still calls `EnterPlaying`.

**HandleBlackout.** The vision component calls it once the screen is black.

- In `Booting`: `SetViewTargetWithBlend(pawn, 0)`, `CarrierVision.RemoveTitle`, `SetInputMode_GameOnly(self)`, `bShowMouseCursor = false`, then `CarrierVision.PlayBoot(FirstBoot)`. Move and look input stay ignored.
- In `Rebooting`: `RespawnTries = 0`, `RespawnStep = 0`, then `TryRespawn`.
- In any other state it does nothing.

**TryRespawn.** It calls `RoadTether.ComputeRespawn(RespawnStep)` and sets `giveUp = RespawnTries >= 20`.

- If `Found` or `giveUp`, it runs `pawn.K2_TeleportTo(Location, Rotation)`.
- If the teleport succeeded or `giveUp` is set, it continues:
  1. When `giveUp` is set, it logs a warning with `PrintString` (log only). If the teleport also failed (`K2_TeleportTo` returns false when the capsule does not fit), it forces the carrier there with `pawn.K2_SetActorLocation(Location, bSweep=false, bTeleport=true)`. Without this the carrier would boot at the breach spot and breach again at once.
  2. `SetControlRotation(Rotation)`
  3. `StopMovementImmediately`
  4. `CarrierVision.PlayBoot(Reboot)`
- Otherwise it retries: `RespawnTries += 1`, `RespawnStep += 200`, then `K2_SetTimer(self, "TryRespawn", 0.1)`.

That allows at most 20 retries, 0.1 s apart (2.0 s in total). Each retry moves the candidate 200 cm further along the travel direction. The 21st call places the carrier at the last candidate even without a trace hit, which the tether reports as the spline point plus the capsule half-height. It boots whether or not that teleport succeeds, and a failed teleport is replaced by the unswept `K2_SetActorLocation`. The reboot lines start only after placement, because `PlayBoot` follows the teleport. The tether returns a zero location only when its own guards fail (no road, owner or capsule), and a breach cannot happen in those states.

**HandleVisionOnline.** Sets `GroundTries = 0`, then calls `TryGround`.

**TryGround.** It traces on Visibility from pawn + (0,0,50) to pawn + (0,0,-500). The trace cannot hit the carrier: the capsule's `Pawn` profile and the meshes' `CharacterMesh` profile both ignore Visibility (BaseEngine.ini).

- On a hit, or once `GroundTries >= 50`: `MOVE_Walking`, `ResetIgnoreInputFlags`, `RoadTether.StartTether`, `FlowState = Playing`.
- Otherwise: `GroundTries += 1` and retry after 0.1 s, so the wait is at most 5 s.

**HandleZoneChanged(NewZone).** Calls `CarrierVision.ShowWarning(NewZone == Warning)`.

**HandleBreach.** It is guarded on `FlowState == Playing`. The tether only breaches from Playing, and the guard makes a second call harmless. It then runs:

1. `FlowState = Rebooting`
2. Ignore move and look input.
3. `StopMovementImmediately`, then the movement mode `MOVE_None` (the same cast chain as `BeginTitle`), so the carrier neither walks on nor falls through the reboot. `TryGround` restores `MOVE_Walking`.
4. `CarrierVision.ShowWarning(false)`
5. `CarrierVision.PlayBreach`

The tether has already stopped itself.

**Pawn movement.** The character-movement getter cannot be called from Blueprint, so each use is `GetComponentByClass(CharacterMovementComponent)` followed by a cast. The cast's output pin is `AsCharacter Movement Component`. `CastFailed` continues the chain, so a pawn without that component still gets the rest of the step.

**Contract with BPC_CarrierVision.** All of these are impure except `GetTitleWidget`:

| Function | Signature | Notes |
|---|---|---|
| `SetVisionVolume` | `(Volume: object:/Script/Engine.PostProcessVolume)` | Stores `VisionVolume`. Called before `Setup`, so `Setup` must not look the volume up itself. |
| `Setup` | `()` | |
| `ShowTitle` | `()` | |
| `GetTitleWidget` | `() -> Widget: object:/Script/UMG.Widget` | **Pure.** Returns the `WBP_Saskarta_Title` instance, used as the focus target. |
| `DisableTitle` | `()` | The title's `SetIsEnabled(false)`. |
| `RemoveTitle` | `()` | The title's `RemoveFromParent()`. |
| `FadeToBlack` | `()` | |
| `PlayBoot` | `(Kind: name)` | `Kind` is `FirstBoot` or `Reboot`. |
| `ShowWarning` | `(bShow: bool)` | |
| `PlayBreach` | `()` | |

The vision component calls `HandleBlackout()` and `HandleVisionOnline()` on its owner. The tether calls `HandleZoneChanged(NewZone)` and `HandleBreach()`. The controller uses the tether's `StartTether()` and its impure `ComputeRespawn(StepCm) -> Found, Location, Rotation`.

**Level requirements.** `Saskarta_WP` must hold exactly one `CineCameraActor` (the title camera) and exactly one `BP_CarrierVisionVolume`, and neither may be spatially loaded. `GetActorOfClass` returns the first actor it finds, and a lookup by tag would need an array node that Hayba cannot author.

**Not expressible in the spec.** `TitleMusic` needs `Sound = /Game/Pallbearer/UI/eyetae_title.eyetae_title` and `bAutoActivate = false` on its component template. bpgraph components take only a name and a class, so both must be set after the build. Until then the title is silent, because `FadeIn` on an audio component with no sound does nothing.

**Build.** Build this spec together with `BPC_RoadTether`, `BPC_CarrierVision`, `BFL_SaskartaRoad` and `BP_CarrierVisionVolume`. `BeginTitle` uses the volume's class as a pin literal.

The first build needs `--reset-graphs`. A new child of `BP_FirstPersonPlayerController` starts with a disabled ghost pair, `Event BeginPlay -> Parent: BeginPlay` (`FKismetEditorUtilities::AddDefaultEventNode`), and bpgraph counts the linked pair as existing content. Removing the disabled pair changes nothing: the parent's BeginPlay still runs.

## WBP_Saskarta_Intro (graph)

`WBP_Saskarta_Intro.graph.json` has no `create`: Task L5 builds the widget tree with Hayba's UI tools (tree in `.superpowers/sdd/2026-09-26-saskarta-world-sprint/task-L5-report.md`). The spec adds the variables, the functions below, two class defaults (`bIsFocusable = true`, `DesiredFocusWidget = SkipButton`) and the EventGraph. Designer variables it needs: `EmberRetainer` (RetainerBox, effect `M_UI_EmberFire`, texture parameter `Texture`), `NameImage`, `NameText`, `SubtitleText`, `StatusText`, `SkipButton`.

Every animation runs on widget-owned timers (no Tick, no Timelines). Four ramps (`Ignite`, `Burn`, subtitle and status opacity) each hold `From`, `To`, `Start`, `Dur`; the pure `RampValue(From, To, Start, Duration)` is `Lerp(From, To, clamp((now - Start) / max(Duration, 0.001), 0, 1))`. The ramp defaults are the first card: `Ignite` 0 -> 1 over 4 s, everything else held at 0.

| Function | Called by | Does |
|---|---|---|
| `PlayIntro()` | `PC_Saskarta.BeginIntro` | `EmberMID = EmberRetainer.GetEffectMaterial()`, `IgniteStart = now` (the name burns in), one `EmberStep`, `CardTimer -> ShowSubtitle` after `SubtitleAt` (2.5 s), `StepTimer -> EmberStep` looping every `StepInterval` (0.033 s, max once per frame) |
| `ShowSubtitle()` | `CardTimer` | subtitle opacity 0 -> 1 over `SubDur` (1.5 s), `CardTimer -> EnterHold` after `HoldDelay` (5.5 s) |
| `EnterHold()` | `CardTimer`, `SkipButton.OnClicked` | once only (`bHolding`): clears `CardTimer`; `Ignite` from its current value to `HoldIgnite` (0.35) and the subtitle to 0, both over `HoldBlendTime` (2 s); the status line fades in over `StatusDur` (1 s) |
| `IsHolding() -> bHold` (pure) | `PC_Saskarta.PollIntro` | `bHolding` |
| `Reveal(BurnTime)` | `PC_Saskarta.RevealIntro` | `Burn` 0 -> 1 over `BurnTime`, the status line out over `StatusOutTime` (0.4 s), `CardTimer -> FinishIntro` after `BurnTime` |
| `FinishIntro()` | `CardTimer` | clears `StepTimer`, `RemoveFromParent` |
| `EmberStep()` | `StepTimer` | pushes `Ignite` and `Burn` into `EmberMID`, and the two opacities |

**EventGraph.** `PreConstruct` pushes `PreviewIgnite` and `PreviewBurn` (both 0) into the effect material for the UMG designer; `PlayIntro`'s first `EmberStep` overrides them at runtime. Hayba's offscreen `ui_render_widget_to_png` does not see these pushes (tested: black at PreviewIgnite 0.8), so renders of a given moment use `python Tools/Look/build_ember_material.py defaults IGNITE BURN` (the material's own defaults) and then `defaults 0 0`. `SkipButton.OnClicked` asks the owning PC to latch `RequestOpeningSkip`, then calls `EnterHold`; Space and Gamepad Right are also polled by the controller during the opening. EventCard and HaybaCard retain their own one-card fade skip buttons.

**Swapping in the Saskartan script.** The name card is an Overlay holding `NameImage` (an Image, Collapsed) and `NameText` (the Latin placeholder "Najzen dînefferesen, enisetre" in Cinzel). `NameImage` is Collapsed and its brush is `NoDrawType` at 1 x 1 px, so it neither draws nor takes space (the offscreen renderer still lays out Collapsed widgets). When the art arrives: set `NameImage`'s brush to the texture (white glyphs on transparent, at least 2048 px wide) with Draw As `Image` and its real image size, make it Visible and collapse `NameText`. The effect uses the RetainerBox's alpha as fuel, so no graph or material change is needed.

## GM_Saskarta

This is a child of `BP_FirstPersonGameMode`, whose pawn is `BP_FirstPersonCharacter`. Its only change is `PlayerControllerClass = PC_Saskarta_C`. It is used only as `Saskarta_WP`'s World Settings GameMode override.

## BP_CarrierVisionVolume

This is a child of `/Script/Engine.PostProcessVolume` with no graphs. The level holds exactly one. The controller finds it with `GetActorOfClass` and passes it to `CarrierVision.SetVisionVolume`.

The class defaults are `bUnbound = true`, `Priority = 1000` and `BlendWeight = 1`. The effect is switched by the blendable's own weight, which goes between 0 and 1. The class default also sets `bIsSpatiallyLoaded = false`, for these reasons:

- `AActor::GetIsSpatiallyLoaded` returns the flag unchanged (Actor.cpp:1630).
- PostProcessVolume clears the flag only in `PostEditChangeProperty`, when `bUnbound` is toggled in the Details panel (PostProcessVolume.cpp:168-172). An instance that gets `bUnbound` from the class default would therefore stay spatially loaded.
- Once `bUnbound` is set, the flag cannot be changed on an instance. `CanChangeIsSpatiallyLoadedFlag` returns false for unbound volumes (PostProcessVolume.h:85), and `SetIsSpatiallyLoaded` `check()`s it (Actor.h:2652).

**Probe this parent before the real build.** `ABrush` is `NotBlueprintable` (Brush.h:75), so the editor's own Blueprint UI refuses PostProcessVolume as a parent (`CanCreateBlueprintOfClass`, Kismet2.cpp:1065). Hayba's `blueprint_create` calls `CreateBlueprint` directly and skips that check. The engine does ship a Blueprintable volume, `ALocationVolume` (LocationVolume.h), so Blueprints based on brushes do work in principle.

The fallback is an Actor Blueprint with a `PostProcessComponent`, which is Blueprint-spawnable and has `bUnbound`, `Priority`, `BlendWeight` and `AddOrUpdateBlendable` (PostProcessComponent.h). Switching to it changes the type of `SetVisionVolume`'s input.

## WBP_Saskarta_Title (graph)

`WBP_Saskarta_Title.graph.json` has no `create`, because the UI step builds the widget. The spec adds the EventGraph logic and two class defaults. `StartButton` and `QuitButton` must be marked as variables.

- `StartButton.OnClicked` casts `GetOwningPlayer()` to `PC_Saskarta` (output pin `AsPC Saskarta`) and calls `StartGame`. If the cast fails, nothing happens.
- `QuitButton.OnClicked` calls `QuitGame(SpecificPlayer = GetOwningPlayer(), Quit)`, which ends the session in PIE.
- The class defaults are `bIsFocusable = true` and `DesiredFocusWidget = StartButton`. They make the widget pass focus to Start:
  - The controller calls `SetInputMode_UIOnlyEx` with the title widget as the focus target.
  - A focusable UserWidget forwards focus to its `DesiredFocusWidget` (UserWidget.cpp:2429-2445), so keyboard and gamepad focus starts on Start.
  - A non-focusable one would make Slate walk up the widget path to the game viewport instead (SlateApplication.cpp:3021-3038).

`PC_Saskarta` (with `StartGame`) must be compiled before this graph is built.
