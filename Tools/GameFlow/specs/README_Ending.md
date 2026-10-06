# The ending: the Keeper on foot, and the hooks the ending calls

Task ENDING, 2026-09-27. Offline design and specs. The editor lane builds them following `.superpowers/sdd/2026-09-26-saskarta-world-sprint/task-ENDING-brief.md`. The generator is `Tools/GameFlow/gen_ending_specs.py`. Rerun it after any change here, then run `node Tools/GameFlow/bpgraph.mjs check` on each spec.

| Spec | Kind | What it adds |
|---|---|---|
| `BP_Saskarta_Traveller.json` | full spec (replaces the TRAV lane's) | the Keeper as a playable pawn |
| `BP_Saskarta_Carrier.ending.json` | scoped (six new functions) | the carrier's side of the collapse and the hatch |
| `BPC_CarrierVision.ending.json` | scoped (three new functions) | the log lines and the black |
| `PC_Saskarta.ending.json` | scoped (eleven new functions) | every PC hook `story-events.json` calls |
| `BP_Saskarta_HighVoice.json` | new Blueprint (parent Actor) | the relay set's logic for CIN_24 |

**Build.** Build all five in **one** `bpgraph.mjs build --reset-graphs` run. The carrier calls the traveller's functions and the PC calls the carrier's, so pass 1 has to declare every function before any graph is wired. The scoped specs list only their own graphs; `--reset-graphs` rebuilds just those.

## The flow: Carrier → Human → Transmit → End

`PC_Saskarta.FlowState` is a Name. The runner writes it with `SetFlowState` and reads it for `RoadPassHuman`.

| State | Set by | Effect |
|---|---|---|
| `Playing` (the carrier) | `TryGround` / `EnterPlaying` (CIN_01 final state) | the whole road |
| `Collapsing` | CIN_18 cue at 0.0 | `HandleBlackout` and `HandleBreach` do nothing (they test `Booting`, `Rebooting` and `Playing`), so the breach glitch cannot reboot the carrier |
| `Human` | CIN_19 final state | `RoadPassHuman` beats B20–B23 fire |
| `Transmit` | CIN_24 cue at 0.0 | no input; the hand is on the mark |
| `End` | CIN_25 cue at 0.0 | the end card; `OpenLevel Title` follows |

`Playing` keeps its name because the PC graphs compare against it. "Carrier" in the design is `Playing`.

## The chain, step by step

| # | When | What runs | Owner |
|---|---|---|---|
| 1 | The carrier passes UE 221.9 m (road 4,790) | B18 (`RoadPass`) → `PlayCinematic CIN_18_COLLAPSE` | runner |
| 2 | CIN_18 at 0.0 | `SetFlowState Collapsing` | runner |
| 3 | 2.0 | `Cine_Breach` → `CarrierVision.PlayBreach` (the glitch; black at ~3.1) | PC |
| 4 | 3.2, in the black | `SnapToRoad`: the carrier moves to the spline centre facing up-road, so the local frame of CIN_18 and CIN_19 is the carrier's own | carrier |
| 5 | 3.45 | `Cine_ClearBlack` → `CarrierVision.HideBlack` (boot log collapsed, vision weight 0) | PC |
| 6 | 3.5 | `PlayShutdown` (`A_CarrierFull_Shutdown`, 5 s) on the one exterior shot | carrier |
| 7 | 9.0–17.6 | `Cine_ShowBlack`, then one `Cine_Log*` per carrier line: `CARRIER 07 - CRITICAL FAILURE [FAIL]`, `HANDOVER - SEARCHING` ×2, `NO CARRIER AVAILABLE [FAIL]`, `CAPSULE LOCK - RELEASED [ OK ]` | PC → CarrierVision → BootLog `TypeLine` |
| 8 | CIN_18 final state | `FreezeCarrier` (`MOVE_None`: the runner unlocks input after a cinematic, and the dead carrier must not drive in the black), `SpawnTravellerInCapsule` (the placed, hidden traveller → `EnterCapsule` at the `capsule_root` socket + 50 cm), `SetFlowState Collapsing` | carrier, traveller |
| 9 | Prompt *Release the inner latch.* (E / A) | B19 → `PlayCinematic CIN_19_HATCH` | runner |
| 10 | CIN_19 at 0.0 | `Cine_ClearBlack`, `PlayOpenHatch` (`A_CarrierFull_OpenHatch`: the lock swings 70° in the first quarter, then the hatch opens 105°) | PC, carrier |
| 11 | 13.4 | Prompt *Rise.* pauses the sequence | runner |
| 12 | 13.8 | `TravellerGripRim` → traveller `GripRim` (visible, `SupportedIdle`, inside the capsule: the insert frames only the hand on the rim) | carrier → traveller |
| 13 | 15.8, on the cut | `TravellerStandBeside` → traveller `StandAt` (the capsule's left side, 110 cm, facing up-road, collision on, `MOVE_Walking`, `SupportedIdle`) | carrier → traveller |
| 14 | CIN_19 final state | `PossessTraveller` (calls `TravellerStandBeside` again, so a skip still leaves the Keeper standing; `Possess`; control rotation (−8, the Keeper's yaw); `ApplyPlayerFOV`), `SetFlowState Human`, `StartHumanWalk` (the PC's `RoadTether.StopTether`, then the traveller's `StartWalk`), `Checkpoint CP4_HUMAN`. Then the runner blends 1.6 s into the traveller's camera | PC |
| 15 | B20, B21, (B22) | the rests: `SetInputLock` holds and `G21_LAST_LOOK` | runner |
| 16 | B23 (`RoadPassHuman` UE 19.5) | `RADIO_B23_01`, then the prompt *Lay your hand on the mark.* | runner |
| 17 | The press | B24 → `PlayCinematic CIN_24_TRANSMISSION` | runner |
| 18 | CIN_24 at 0.0 | `SetFlowState Transmit`, `StopHumanWalk` (the breath loop fades, the tether stops), `SnapKeeperToPlate` (the pawn moves to the High Voice `StandPoint` under the cut, since the prompt is not proximity-gated), `PlayTransmit` at 0.05 | PC, HighVoice, traveller |
| 19 | 4.0 | `StartGlowAndColumn`: the crown's `Col` and the column's Z scale ease in over 8 s on a 0.05 s timer | HighVoice |
| 20 | 26.0 | `Cine_ShowBlack` + `Cine_LogTransmissionComplete` over the fade-track black; `CV_TRANSMIT_02` | PC |
| 21 | 31.0–31.8 | `HideKeeper` (the seated shot is the Keeper's own eyes), `ResetGlowAndColumn`, `Cine_ClearBlack` | HighVoice, PC |
| 22 | CIN_24 ends (48 s) | B24's second action: `PlayCinematic CIN_25_END_CARD` | runner |
| 23 | CIN_25 | `SetFlowState End`; `ShowEndCard` `Title` (2.0), `Credits` (10.0), `CreditsRoll` (17.0, 77.5 s); final state `OpenLevel Title` | runner, caption widget |

**Why the hooks go through the PC and the carrier.** `CallHook` resolves an actor by tag (`PC` and `Pawn` are keywords) and calls a no-parameter function on it.
- `BPC_CarrierVision` is a component on the PC, so the old `target_tag: CarrierVision` resolved to nothing.
- The traveller has no tag. Before possession the carrier forwards calls to it; after possession it is the `Pawn`.
- `CallHook` cannot pass text, so each log line has its own wrapper.
- `BP_EndingSet` is superseded: its cameras are sequence spawnables now, and its glow and column moved to `BP_Saskarta_HighVoice`.

## BP_Saskarta_Traveller: the Keeper's walk

The traveller keeps its inherited EventGraph (a duplicate of `BP_FirstPersonCharacter`: `IA_Move` → `Move`, `IA_Look` / `IA_MouseLook` → look, BeginPlay → `StartAnimDriver`). bpgraph cannot author Enhanced Input events, so the spec replaces only the functions.

**Camera: third person, over the right shoulder.** CINEMATICS.md section 6 hands the walk to the traveller's own boom. `ConfigureCamera` runs from `StartAnimDriver` and sets the boom by property name, since the spec cannot set component templates:
- `TargetArmLength` 320 cm (`ArmLength`);
- `SocketOffset` (0, 45, 55);
- camera lag on, speed 6 (`ArmLagSpeed`);
- `bUsePawnControlRotation` true.

Look stays free; the PCM clamps pitch to −60/+35. *First-person option:* set `ArmLength` 0, `SocketOffset` (0, 0, 70) and hide the head bone. Only `ConfigureCamera`'s literals change.

**Walk speed: 110 cm/s.** `StartWalk` sets `MaxWalkSpeed` = `HumanWalkSpeed` (110). The class default is already 110 (TRAV lane); this restates it.

**Movement.** `Move` is relative to the camera's yaw (the forward and right vectors of the control yaw). `bOrientRotationToMovement` turns the body, and controller yaw stays off. The carrier's `Move` was vehicle-style (along its own heading); the Keeper walks like a person.

**Animation: the SupportedIdle / Rest / SlowWalk blend.** `UpdateAnim` runs every 0.1 s (no Tick):
- in `Loco` it feeds the speed to `BS_Traveller_Locomotion` (Rest at 0, SlowWalk at 110, `RateScale` 5, so the feet don't slide);
- in `SupportedIdle` (the lean on the capsule) the first movement over 10 cm/s switches to `Loco`;
- `StartAnimDriver` no longer resets to Loco when it runs again on possession, so the lean holds until the player moves;
- `PlayTransmit` plays the Transmit clip once.

**Hidden start.** The traveller is **placed** in the level: bpgraph has no spawn node, and a placed actor has none of a spawn's streaming problems. `bStartHidden` (default true) makes `StartAnimDriver` call `PrepareHidden` once:
- hidden, no collision;
- `MOVE_None`, so it never falls through terrain that hasn't streamed in yet.

For a test instance (possess from a test spawn), set `bStartHidden` false on it. The class defaults set `AutoPossessAI` and `AutoPossessPlayer` to Disabled, so no AI controller takes the placed actor.

**The road tether to the High Voice path.**
- The PC's `BPC_RoadTether` is the carrier's: its breach reboots the carrier. `StartHumanWalk` stops it.
- The traveller runs its own `CheckTether` every 0.25 s (`TetherInterval`). More than 9 m (`TetherLimit`) from the road spline, it teleports back to the closest spline point, 92 cm up (`HalfHeight`), facing up-road (the same chord rule as `ComputeRoadRespawn`: the spline's tangents are zero at its points).
- The V9 blocking volumes, 8 m either side, are the soft edge. This is only the safety net.
- The walk is the last 222 m of the same `RoadSpline` (4,790 → 5,009), so no second path is needed.

**The prompt to transmit at the relay.** This is the runner's `Prompt` action, not pawn logic. B23 (`RoadPassHuman`, UE 19.5 m) plays `RADIO_B23_01` live and dry, then shows *Lay your hand on the mark.* and polls held-key edges for E / gamepad A every 0.01 s. The press fires B24.
- The prompt is not proximity-gated: the importer has no volume trigger.
- CIN_24 therefore snaps the Keeper to the plate's `StandPoint` under its first cut.
- If the playtest shows players pressing too early, move B23's `ue_distance_from_p0_m` closer to the hut. That is a data change.

**Footstep audio hooks.** `UpdateAnim` adds speed × 0.1 s to `StepAccum`. Every 44 cm (`StepLength`, SlowWalk's measured stride) it calls `PlayFootstep`:
- **the step:** `SfxFootA` / `SfxFootB` alternate (`/Game/AzielArts_Material/Footsteps/SoundWav/Rock_Mono_01`, `_03`) at the feet, volume 0.55, pitch 0.92–1.06;
- **the staff:** on every second step the walking aid taps 40 cm ahead (`SFX_WalkingAid_Tap_Gravel_01` / `_03`, alternating every fourth step), volume 0.45.

Swap any of the four sound variables for a SoundCue with more variations when one exists. `StartWalk` also starts `SfxBreathLoop` (the `BREATH_03` loop, attached to the root) once the user's breath takes are imported; the variable is empty until then. `StopWalk` fades it out over 0.3 s: the storyline's breath rule has the walking breath stop when the hand goes on the mark.

## BP_Saskarta_HighVoice

A new Actor at `/Game/SaskartaGaea/Story/HighVoice/BP_Saskarta_HighVoice`.

**Components.**
- `MastBase`, `StandPoint`, `SeatPoint`: SceneComponents;
- `Plate`, `Crown`, `Column`: StaticMeshComponents.

The V10 placement (brief step 6) sets their meshes and transforms and tags the placed actor `Saskarta.HighVoice`.
- `StandPoint`: where the Keeper stands at the plate, its +X facing the plate.
- `SeatPoint`: the seated view at the mast foot, ~100 cm up, facing east over the valley.
- `Crown`: the 8 m glow sphere with `MI_HighVoice_Glow` (vector `Col`).
- `Column`: `SM_Cylinder` with the same material, pivot at the base.

**Functions.**
- `SnapKeeperToPlate`, `HideKeeper`: act on player pawn 0.
- `StartGlowAndColumn`: `EnsureMID`, column visible, then a 0.05 s `GlowStep` timer that eases `Col` from `ColRest` (4, 1.8, 0.6) to `ColPeak` (40, 18, 6) and the column's Z scale from 0.01 to 60 over 8 s (`FInterpEaseInOut`, exponent 2).
- `ResetGlowAndColumn`: also runs at BeginPlay.

## Known gaps (the brief covers each)

- **Pause in Human and Transmit.** `TogglePause` and `OpenPause` accept only `Playing`, and `ClosePause` returns to `Playing`, which would stop `RoadPassHuman`. The fix: a `PausedFrom` Name; open when the state is `Playing` or `Human`; restore `PausedFrom` on close.
- **The end-card panel.** `WBP_Saskarta_Caption` has no `EndCard` panel yet: `Title` image, `CreditsShort` text and a `CreditsRoll` text in a clipped box. It binds `OnEndCard(Id)` and scrolls the roll by a 0.02 s timer at 48 px/s.
- **The camera-cut restore at CIN_19's end.** The runner's blend starts from the last sequence frame. If the camera-cut track's restore shows one frame of the dead carrier's camera, set the sequence's `bRestoreState` off or move `PossessTraveller` to a cue at 19.7 s.
