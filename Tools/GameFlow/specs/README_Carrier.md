# BP_Saskarta_Carrier (the player's pawn)

`/Game/SaskartaGaea/Characters/Carrier/BP_Saskarta_Carrier` is the pawn `GM_Saskarta` spawns (`DefaultPawnClass`). It is a Character, so `BPC_RoadTether` (which reads the pawn's `CapsuleComponent`) and every `GetComponentByClass(CharacterMovementComponent)` chain in `PC_Saskarta` keep working unchanged.

## How it was made (not all expressible in a spec)

1. **Duplicate of `BP_FirstPersonCharacter`** (not a child). The duplicate keeps the template's EventGraph: `IA_Move` -> `Move` (`AddMovementInput` along the actor's forward and right vectors), `IA_Look`/`IA_MouseLook` -> `Aim` (`AddControllerYaw/PitchInput`), `IA_Jump`. bpgraph cannot author Enhanced Input events, so they are inherited this way. `FirstPersonMesh` and `FirstPersonCamera` were deleted with `SubobjectDataSubsystem`.
2. **Components** (Python, `SubobjectDataSubsystem`): `CameraBoom` (SpringArm) on the capsule at (13, 0, 50), just above the mast, `TargetArmLength 190`, `SocketOffset (0, 0, 45)`, `bUsePawnControlRotation = true`, position lag 10 and rotation lag 14, probe 10 cm. `FollowCamera` on the boom, FOV 90, `bUsePawnControlRotation = false`.
3. **Class defaults** (Python): `Mesh = SK_Carrier`, Single Node mode, relative (0, 0, -60), yaw -90 (the model's front is +Y), `FirstPersonPrimitiveType None`, `OwnerNoSee false`. Capsule radius 60 and half-height 60. `bUseControllerRotationYaw/Pitch/Roll = false`, `JumpMaxCount = 0` (no jump; `IA_Jump` does nothing). CharacterMovement: `MaxWalkSpeed 500` (story-events `carrier_speed_cms`), `bOrientRotationToMovement true`, `RotationRate yaw 90`, `MaxAcceleration 400`, `BrakingDecelerationWalking 600`, `bUseControllerDesiredRotation false`.
4. **Functions** from `BP_Saskarta_Carrier.json` (bpgraph build, no `--reset-graphs`: the spec has no EventGraph).
5. **EventGraph additions** (Hayba `blueprint_add_event` / `blueprint_add_node` / `blueprint_connect_nodes`): `Event Possessed -> StartAnimDriver`, `Event Unpossessed -> StopAnimDriver`.

Look is independent of movement: the look input only turns the control rotation, which only the spring arm uses. Movement input is relative to the carrier's own heading, and `bOrientRotationToMovement` turns the body toward the movement at 90 deg/s, so W+A/D drives an arc, like a vehicle.

## Animation driver (Single Node, 0.1 s timer, no Tick)

No AnimBP: Hayba can add states to an existing state machine but cannot create one. `UpdateAnim` runs every `AnimInterval` (0.1 s) and picks one asset for the mesh's single-node instance.

| Mode | Asset | When |
|---|---|---|
| `Off` | `A_Carrier_Shutdown` (plays once, holds the last frame) | From possession until the boot handover |
| `Start` | `A_Carrier_Start`, once | When the controller's move input goes from ignored to not ignored (`PC_Saskarta.TryGround` -> `ResetIgnoreInputFlags`, after the boot and after every reboot), or `PlayStart()` |
| `Drive` | `BS_Carrier_Drive`, looped | Speed > 15 cm/s. Play rate = speed / 62.83 |
| `StartStop` | `A_Carrier_StartStop`, once | Stopping after the peak speed passed 250 cm/s |
| `Idle` | `A_Carrier_Idle`, looped | Stopped, and any one-shot has finished |
| `Shutdown` | `A_Carrier_Shutdown`, once | `PlayShutdown()`; it stays until `PlayStart()` or the next handover |

`BS_Carrier_Drive` is a 2D blend space, sample-weight speed 4/s (0.25 s transitions):

- X `Steer` -1..1: the yaw rate over 0.1 s divided by 60 deg/s, clamped, and zero below 20 deg/s. +1 is a right turn (yaw increasing).
- Y `Strain` 0/1: 1 when the rise over the last 0.1 s divided by the distance covered is above tan 12 deg (0.2126). The pawn's velocity has no Z while walking (`bMaintainHorizontalGroundVelocity`), so the slope comes from the location.

Its six samples are derived clips. Each is `A_Carrier_Drive` (wheel spin 144 deg/s, so 62.83 cm/s of ground at rate 1 on the 25 cm wheels) with some bones held at the peak pose of an authored clip:

| Clip | Held bones and source |
|---|---|
| `A_Carrier_DriveSteerRight` (1, 0) | steer_fl/fr, eye_l/r from `A_Carrier_TurnLeft` at 0.9 s |
| `A_Carrier_DriveSteerLeft` (-1, 0) | the same from `A_Carrier_TurnRight` at 0.9 s |
| `A_Carrier_DriveStrain` (0, 1) | body, mast, eye_l/r from `A_Carrier_Strain` at 2.0 s |
| `A_Carrier_DriveStrainSteerRight/Left` (+-1, 1) | both sets |

**The authored L/R names are mirrored.** `TurnLeft` steers the wheels to the carrier's right (verified from the steer bone's rotated forward vector), and `wheel_fl`/`eye_l` sit on the carrier's right side. The derived clips are named by the real direction. The authored Turn/Strain clips don't spin the wheels, which is why they are not played directly while moving.

`PlayClip(Anim, Mode, bLoop)` does `PlayAnimation`, `SetPlayRate(1)` and sets `AnimMode`. `PlayStart()` and `PlayShutdown()` are public; the ending sequence should call `PlayShutdown()` on the carrier before possessing the traveller.

## Camera pitch

`PC_Saskarta.PlayerCameraManagerClass = PCM_Saskarta` (a child of `BP_FirstPersonCameraManager` with `ViewPitchMin -60`, `ViewPitchMax 35`). It is set in `PC_Saskarta.json`'s `cdo_defaults` and was applied with Python, because rebuilding the controller's graphs is not needed for a class default.

# BP_Saskarta_Traveller (the Keeper, possessable, not wired into the ending)

`/Game/SaskartaGaea/Characters/Traveller/BP_Saskarta_Traveller` is made the same way: a duplicate of `BP_FirstPersonCharacter` without the first-person mesh and camera, with `CameraBoom` (350 cm, `bUsePawnControlRotation`, lag 8) and `FollowCamera`. Mesh `SK_Traveller` (168 cm) in Single Node mode at (0, 0, -88), yaw -90; capsule 32/88; `MaxWalkSpeed 110` (story-events `human_speed_cms`), orient to movement at 180 deg/s, acceleration and braking 400. `Event BeginPlay -> StartAnimDriver`; the functions come from `BP_Saskarta_Traveller.json`.

- `BS_Traveller_Locomotion` (1D `Speed` 0..110, smoothing 0.25 s): `A_Traveller_Rest` at 0 and `A_Traveller_SlowWalk` at 110 with `RateScale 5.0`. SlowWalk is in place (no root motion); its planted toe moves 44 cm per 2.0 s step, so the clip's ground speed is 22.0 cm/s and 110 / 22 = 5.0 keeps the feet from sliding.
- `UpdateAnim` (0.1 s timer) feeds the speed into the blend space in `Loco` mode and returns from `SupportedIdle`/`Transmit` to `Loco` once the traveller moves faster than 10 cm/s.
- `PlaySupportedIdle()` (looped) and `PlayTransmit()` (once) play the original clips, so the staff stays in the right hand. `Traveller/Retarget*` (the Manny retarget) is not referenced: its root motion lands on `traveller_rig` and the staff hand opens.
