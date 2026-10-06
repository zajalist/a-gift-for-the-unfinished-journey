# Carrier animation in C++ (USaskartaCarrierAnimInstance)

Task CARRIERANIM. The carrier's clip playback plus the procedural bones that the Single Node setup could not do. There is no AnimBP graph: a C++ `UAnimInstance` with its own proxy samples the clip, then modifies bones in `Evaluate`.

The files, all under `Plugins/SaskartaCore/Source/SaskartaCore/`:

| File | Contents |
|---|---|
| `Public/SaskartaCarrierAnimInstance.h`, `Private/SaskartaCarrierAnimInstance.cpp` | The instance, the proxy, and the `FSaskartaCarrierAnimInputs` / `FSaskartaCarrierAnimTuning` structs. |
| `Private/SaskartaCarrierAnimProxy.h` | The worker-thread half. |
| `Public/SaskartaCarrierMath.h`, `Private/SaskartaCarrierMath.cpp` | The hitch model, the springs and the helpers, as pure functions. |
| `Private/Tests/SaskartaCarrierMathTest.cpp` | `Automation RunTests Saskarta.Carrier` (8 tests). Offline: `Tools/Carrier/hitch_smoke/hitch_smoke.cpp` compiles the same tests with cl. |

## 0. Build first (editor CLOSED)

Close the editor and build with the same command as `README_MenuInput.md` (it is one build for both):

```
start "" /belownormal /wait /b "C:\Program Files\Epic Games\UE_5.8\Engine\Build\BatchFiles\Build.bat" UnrealEditor Win64 Development -Project="D:\UnrealEngine\saskartarad\saskartarad.uproject" -WaitMutex -NoHotReloadFromIDE
```

Don't use Live Coding: this change adds new reflected classes and structs. Then open the editor and run `Automation RunTests Saskarta.Carrier`.

## 1. What it does

**The clip.** It plays whatever the carrier's 0.1 s timer picks (Idle, Start, StartStop, Shutdown, OpenHatch, or `BS_CarrierFull_Drive`), with a 0.2 s crossfade (`Tuning.StateBlendTime`).

- `PlayState(State, Asset, bLoop, InPlayRate)` replaces `PlayAnimation`.
- `SetPlayRate`, `SetBlendSpacePosition` and `IsPlaying` have the same names and pins as on `AnimSingleNodeInstance`, so the existing UpdateDrive nodes only change class.
- `SetDriveState(State, PlayRate, BlendInput)` and `SetStateAsset(State, Asset, bLoop)` are the by-name form.

**Procedural bones, on top of the clip.** They are applied in this order:

| Bones | What |
|---|---|
| `body` | Squat on acceleration and nose dip on braking: 0.005 deg per cm/s², clamped to ±3 deg. Roll outward in turns: 0.004 deg per cm/s² of lateral acceleration, ±4 deg. Both go through a spring (k 80, c 11). Bounce: the body lags a change of the mean wheel ground height by 50 %, then springs back (k 180, c 12, ±4 cm). |
| `mast` | Whip. A spring driven by the body's angular acceleration, the carrier's acceleration and the lateral acceleration. It leans back against 30 % of the slope (±6 deg). |
| `eye_l`, `eye_r` | Saccades: ±8 deg yaw and ±4 deg pitch, every 0.6–2.8 s, quick and critically damped. They glance up to 12 deg into a turn. Blinks: a squash along up to 15 %, 0.15 s long, every 2.5–6 s. The eyes are still in `Off` / `Shutdown`. |
| `steer_fl`, `steer_fr` | Yaw from the yaw rate (bicycle model, `atan(wheelbase · w / v)`, ±30 deg). The wheelbase is measured from the wheel bones. This **replaces** the clip's steer rotation. |
| `wheel_fl/fr/rl/rr` | Spin = distance / 25 cm, with the inner wheels slower in a turn. This **replaces** the clip's wheel rotation, so the wheels roll exactly with the ground at any play rate. |
| `coupler` | Drawbar rattle: a small pitch jitter (≤ 0.8 deg), kicked by speed and by steps in the ground. |
| `capsule_root` | Yaw at the coupler from the kinematic hitch model, dθ = (v/L)·sin(φ − θ), with the coupler 78 cm behind the turning centre (measured from the bone), driven by the pawn's own per-frame motion. **Limit:** the angle at which the top-view footprints of carrier and capsule touch (28.3 deg; `Tuning.CarrierFootprint` / `TrailerFootprint`, measured from carrier01_full.fbx) less 3 deg, capped by `MaxHitchDeg`; the last 8 deg ease into it (a cushioned stop), the swing never exceeds 140 deg/s, and the sway bends softly into the same limit. A teleport (one frame > 2.5 m, > 25 m/s or > 400 deg/s: respawns, checkpoints, sequence cuts) or `ResetHitch()` straightens it. In reverse the jackknife grows at 35 % of the pure model. L is measured coupler-to-axle from the bones. The sway spring adds up to ±4 deg out of a turn. Pitch and roll come from the ground under the capsule's own two wheels (`UpdateTrailerGround`), through a lightly damped spring, so the capsule bobs. Bob: a vertical lag of steps in its ground (±5 cm). Everything rotates **about the coupler pivot**. |
| `capsule_lining` | Jiggle along up, driven by the capsule's vertical acceleration (±1.5 cm). |
| `capsule_wheel_l/r` | Spin = the capsule's own distance (v·cos ψ, inner side slower) / 30 cm. The Drive clip turned them at 150 deg/s against the carrier's 180. |
| `root`, `carrier_root`, `capsule_hatch`, `lock` | Left to the clip. `PlayOpenHatch`'s clip still opens the hatch and the lock. |

**Mirrored names.** The source file's left/right labels are mirrored: `wheel_fl`, `eye_l` and `capsule_wheel_l` sit on the carrier's **right** (see `task-CARRIER-report.md`). The code never relies on the labels. Each wheel's side comes from its reference-pose position along the carrier's right (mesh −X), so the differential and the capsule roll come out right either way.

**Axes.** Mesh +Y is forward, +Z is up, and −X is the carrier's right (the mesh sits at yaw −90 in the pawn). If a re-import turns the rig, change `Tuning.MeshForward` / `Tuning.MeshUp`. Every bone rotation is about that mesh axis expressed in the bone's own reference frame, so it does not depend on how each bone's local axes were authored.

**Camera.** `GetCameraBodyDynamics()` returns 30 % (`Tuning.CameraBodyShare`) of the body pitch and roll, as an `FRotator` in actor space: Pitch is positive nose up, Roll is positive right side down. `GetBodyDynamics` returns the full values plus the heave. `GetHitchAngle()` returns the capsule's yaw relative to the carrier, in degrees.

**Inputs.** The pawn sets these on its existing timers; there is no Blueprint Tick.

| Call | From | Sets |
|---|---|---|
| `SetMotionInputs(Speed, YawRate, SlopeRiseOverRun)` | `UpdateAnim` (10 Hz) | Speed, yaw rate and slope, using the values UpdateAnim already computes. The acceleration is derived from successive calls. |
| `SetWheelGround(FL, FR, RL, RR)` | `UpdateGround` (30 Hz) | The four trace-hit Z values. Only the mean's changes are used (the bounce), so the order does not matter. |
| `UpdateTrailerGround()` | `UpdateGround` (30 Hz) | Traces under the two capsule wheels. For each wheel it uses where the wheel would sit with the current hitch yaw, rigid in the carrier's already ground-fitted plane, and stores the offset of the real ground from there. |
| `SetCarrierInputs(struct)` | Anywhere | The whole `FSaskartaCarrierAnimInputs`. It keeps the previous trailer ground unless the struct's `bHasTrailerGround` is true. |

`UpdateAnim` feeds `VSizeXY` into Speed, which is never negative. The carrier never reverses anyway: S turns it round. So the reverse jackknife only shows if a signed speed is fed in (dot of velocity and forward).

**Tunables.** Every stiffness, damping, clamp and bone name is an `EditAnywhere` field of `FSaskartaCarrierAnimTuning`. To tune from the pawn, add a BP variable `AnimTuning` of that type to `BP_Saskarta_Carrier` (Instance Editable) and call `SetTuning(AnimTuning)` in `StartAnimDriver`.

## 2. Editor-lane steps (BP_Saskarta_Carrier)

Do this after step 0, in one editor lane. Check `IsReadOnly` before saving; committed `.uasset` files can be read-only.

### 2a. The mesh's anim class

On the `Mesh` component (`SK_CarrierFull`), set **Animation Mode = Use Animation Blueprint** and **Anim Class = SaskartaCarrierAnimInstance**. The details panel's class picker may list only anim blueprints, so use Python on the class default:

```python
import unreal
bp = unreal.load_asset('/Game/SaskartaGaea/Characters/Carrier/BP_Saskarta_Carrier')
cdo = unreal.get_default_object(bp.generated_class())
mesh = cdo.get_editor_property('mesh')
mesh.set_editor_property('animation_mode', unreal.AnimationMode.ANIMATION_BLUEPRINT)
mesh.set_editor_property('anim_class', unreal.SaskartaCarrierAnimInstance)
unreal.BlueprintEditorLibrary.compile_blueprint(bp)
```

Also add a belt-and-braces call as the **first** node of `StartAnimDriver`: `SaskartaCarrierAnimInstance.InstallOn(Mesh)`, a static function that takes the skeletal mesh component. It switches the mode and class at runtime if the default was lost, and returns the instance.

In spec form (`BP_Saskarta_Carrier.json`, graph `StartAnimDriver`):

```json
"install": { "call": "InstallOn", "class": "/Script/SaskartaCore.SaskartaCarrierAnimInstance" },
"getMeshI": { "call": "GetComponentByClass", "class": "/Script/Engine.Actor" },
"castMeshI": { "cast": "/Script/Engine.SkeletalMeshComponent" }
```

Links: `entry.then -> castMeshI.execute`, `getMeshI.ReturnValue -> castMeshI.Object`, `castMeshI.then -> install.execute`, `castMeshI.AsSkeletal Mesh Component -> install.Mesh`, `install.then -> setYaw.execute` (replacing `entry.then -> setYaw.execute`). Default: `getMeshI.ComponentClass = /Script/Engine.SkeletalMeshComponent`.

### 2b. PlayClip: PlayState instead of PlayAnimation

**Required.** `PlayAnimation` would switch the mesh back to Single Node mode and drop the C++ instance.

In graph `PlayClip`:

1. Replace the nodes `play` (`SkeletalMeshComponent.PlayAnimation`) and `rate` (`SetPlayRate`) with:

   ```json
   "animInst": { "call": "GetAnimInstance", "class": "/Script/Engine.SkeletalMeshComponent" },
   "castCarrier": { "cast": "/Script/SaskartaCore.SaskartaCarrierAnimInstance" },
   "play": { "call": "PlayState", "class": "/Script/SaskartaCore.SaskartaCarrierAnimInstance" }
   ```

2. Rewire the links:
   - `castMesh.then -> castCarrier.execute`
   - `castMesh.AsSkeletal Mesh Component -> animInst.self`
   - `animInst.ReturnValue -> castCarrier.Object`
   - `castCarrier.then -> play.execute`
   - `castCarrier.AsSaskarta Carrier Anim Instance -> play.self`
   - `entry.Mode -> play.State`, `entry.Anim -> play.Asset`, `entry.bLoop -> play.bLoop`
   - `play.then -> setMode.execute`
   - `castCarrier.CastFailed -> setMode.execute`

3. Set the default `play.InPlayRate = 1.0`.

`PlayStart`, `PlayShutdown`, `PlayOpenHatch` and UpdateDrive's `playDrive` / `playStop` / `playIdle` all go through `PlayClip`, so they need no change.

### 2c. UpdateDrive: repoint three nodes

In graph `UpdateDrive`:

1. **Cast.** Change `castSingle` from `/Script/Engine.AnimSingleNodeInstance` to `/Script/SaskartaCore.SaskartaCarrierAnimInstance`. Its output pin becomes `AsSaskarta Carrier Anim Instance`; update the `setPos.self` link.
2. **`setPos`** (`SetBlendSpacePosition`, pin `InPosition`). Change its class to `/Script/SaskartaCore.SaskartaCarrierAnimInstance`. The pins are the same.
3. **`setRate`.** It is currently `SkeletalMeshComponent.SetPlayRate(Rate)`. Change it to `SaskartaCarrierAnimInstance.SetPlayRate(InPlayRate)`:
   - `castSingle.AsSaskarta Carrier Anim Instance -> setRate.self`
   - `rateValue.ReturnValue -> setRate.InPlayRate`
   - keep `castSingle.CastFailed -> setRate.execute` out: link CastFailed to `setPeak.execute` instead.

   The rate now only matters for the non-wheel bones: the wheels are procedural. Keeping `speed / 62.83` is fine.
4. **`busy`** (`SkeletalMeshComponent.IsPlaying`). Change it to `SaskartaCarrierAnimInstance.IsPlaying`:
   - `castMesh2 -> GetAnimInstance -> cast to SaskartaCarrierAnimInstance -> busy.self`
   - its `CastFailed` goes to `ifIdle.execute`.

### 2d. UpdateAnim: feed the motion (10 Hz)

In graph `UpdateAnim`, after `drive` (UpdateDrive), add:

```json
"animSet": { "call": "SetMotionInputs", "class": "/Script/SaskartaCore.SaskartaCarrierAnimInstance" }
```

Get the instance with the same `GetComponentByClass(SkeletalMeshComponent) -> GetAnimInstance -> cast` chain, with nodes `getMeshA` / `castMeshA` / `animA` / `castA`. Then wire:

- `drive.then -> castMeshA.execute`, `castMeshA.then -> castA.execute`, `castA.then -> animSet.execute`
- `speed.ReturnValue -> animSet.Speed`
- `yawRate.ReturnValue -> animSet.YawRate`
- `slope.ReturnValue -> animSet.SlopeRiseOverRun`

Also call it on the `ifLocked.then` path (the boot hold) with the same pins, so the springs settle while held. Or simply move the new chain so it runs before `ifLocked`.

### 2e. UpdateGround: wheel ground, capsule traces, camera (30 Hz)

**Keep the 4-trace ground fit exactly as it is.** It still pitches, rolls and lifts the whole mesh. After `setRel87` (the last node), append:

1. **`SetWheelGround`**, class `/Script/SaskartaCore.SaskartaCarrierAnimInstance`, with:
   - `h15.ReturnValue -> GroundFL`
   - `h27.ReturnValue -> GroundFR`
   - `h39.ReturnValue -> GroundRL`
   - `h51.ReturnValue -> GroundRR`

   These are the four per-wheel hit heights the fit already uses; the order does not matter.
2. **`UpdateTrailerGround`**, same class, no pins.
3. **The camera.** `GetCameraBodyDynamics` (pure, same class) -> `FollowCamera.K2_SetRelativeRotation(NewRotation)`. The camera sits at the end of the zero-length boom (`bUsePawnControlRotation` is on the boom, not the camera), so its relative rotation adds the 30 % body pitch and roll to the look direction.

Get the instance once at the start of these appended nodes, with the same `GetAnimInstance -> cast` chain.

### 2f. Verify (PIE, the user's step)

1. Drive straight. The wheels roll with the ground at any speed; there is no slide at 1–5 m/s.
2. W+D. The front wheels steer right, and the inner (right) wheels turn slower. The body leans out, left side down, about 3 deg at full speed. The mast whips and settles. The eyes glance right.
3. The capsule follows the coupler and tracks **inside** the turn. On straightening it swings back into line within about a second, with a small sway.
4. Press W from a standstill: the nose lifts (squat). Release W: the nose dips.
5. Cross a bump or a road edge. The body bounces; the capsule tilts on its own wheels and bobs; the lining jiggles; the drawbar rattles.
6. Idle. The eyes dart every second or two and blink. In `Off` / `Shutdown` they are still.
7. `PlayOpenHatch` still opens the hatch. Start / StartStop / Shutdown still play once and hand back to Idle (`IsPlaying`).
8. The camera tilts slightly with the body (30 %). If it is too much, set `Tuning.CameraBodyShare`.

If a bone turns the wrong way, the rig's axes differ from the report. Check `Tuning.MeshForward` / `MeshUp` first; every rotation derives from them.
