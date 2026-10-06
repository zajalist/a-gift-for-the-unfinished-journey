# Saskarta_WP level requirements (game flow)

This list collects what the graph specs in `Tools/GameFlow/specs/` expect of the level `/Game/level/Saskarta_WP`. T7 (level setup) must meet every item. Each entry names the spec that depends on it.

## Actors that must exist exactly once

1. **One `CineCameraActor`: the title camera.**
   - `PC_Saskarta.BeginTitle` finds it with `GetActorOfClass(/Script/CinematicCamera.CineCameraActor)`. It does not use the `Saskarta_TitleCam` tag from the plan.
   - It must be the only CineCameraActor in the loaded world at BeginPlay. Any other one would make the pick ambiguous, including one spawned by a Level Sequence.
   - It must not be spatially loaded (always loaded).
   - The plan's `TitleCam` name and `Saskarta_TitleCam` tag can stay, but nothing reads them.
2. **One `BP_CarrierVisionVolume`: the vision post-process volume.**
   - `PC_Saskarta.BeginTitle` finds it with `GetActorOfClass(BP_CarrierVisionVolume_C)`. It casts it to PostProcessVolume and passes it to `CarrierVision.SetVisionVolume`.
   - Use a placed `BP_CarrierVisionVolume`, **not** a plain `PostProcessVolume` named `PPV_CarrierVision`. The `Saskarta_CarrierVision` tag is not read.
   - The class defaults already set `bUnbound`, `Priority 1000`, `BlendWeight 1` and `bIsSpatiallyLoaded false`. Do **not** change `bIsSpatiallyLoaded` on the placed instance: the engine refuses that change on unbound volumes, and the C++ setter `check()`s.
   - Keep `BlendWeight` at 1 and place no blendables in the editor. CarrierVision controls the effect only through the material's blendable weight.
   - Risk: `PostProcessVolume` is not Blueprintable (it inherits `NotBlueprintable` from `ABrush`). Probe the class on a scratch asset before T6. The fallback is an Actor Blueprint with a `PostProcessComponent`, and that fallback changes `SetVisionVolume`'s input type.
3. **One `BP_Saskarta_Road`.**
   - `BPC_RoadTether.FindRoad` finds it with `GetActorOfClass(BP_Saskarta_Road_C)`, then takes its single `SplineComponent` (`RoadSpline`).
   - The road actor must not be spatially loaded.
   - The Codex timer and `UpdateRoadBoundary` must be removed from `BP_Saskarta_Road` (plan).

## World and placement

4. World Settings GameMode = `GM_Saskarta`. That sets `PlayerControllerClass = PC_Saskarta_C`.
5. `PlayerStart` goes on the ground at road spline point 54 (the east end). Travel runs toward point 0 (`TravelSign = -1`).
6. All new level actors are not spatially loaded. Put the always-loaded actors in the outliner folders `GameFlow/`, `Terrain/`, `PCG/` and `Lighting/`.
7. Keep the ground under the road traceable on `Visibility` (TraceTypeQuery1). `ComputeRoadRespawn` and `TryGround` both trace for it. The Pawn and CharacterMesh profiles ignore Visibility, so the carrier cannot block its own trace.

## Assets that must exist before the graphs are built (T6)

8. The graphs reference these assets, and all of them must exist first:
   - `M_PP_CarrierVision` (T2)
   - the five `SFX_Carrier_*` sounds (T3)
   - `WBP_Saskarta_Title`, `WBP_Saskarta_Subtitle` and `WBP_Saskarta_BootLog` (T5)
9. `WBP_Saskarta_BootLog` must expose `BootStatus` and `BootDetail` (TextBlock) and `BootBlack` (Image) as variables. `WBP_Saskarta_Title` must expose `StartButton` and `QuitButton`.
10. `PC_Saskarta.TitleMusic` needs these component template settings, which the spec format cannot express:
    - `Sound = /Game/Pallbearer/UI/eyetae_title.eyetae_title`
    - `bAutoActivate = false`

    Set them after the build (for example with Python through `SubobjectDataSubsystem`). Until then the title plays no music, and nothing reports an error.

## Test constraints (T7)

11. Run the `ComputeRoadRespawn` Python test near point 54 with at most 4 landscape proxies loaded. Never load more than 24.
