// USaskartaCarrierAnimInstance: the carrier's animation in C++, no AnimBP graph
// (task CARRIERANIM). Set it as SK_CarrierFull's anim class on BP_Saskarta_Carrier
// (Tools/GameFlow/specs/README_CarrierAnim.md has the editor-lane steps).
//
// 1. The clip. It plays the asset the carrier's existing 0.1 s timer picks: a clip
//    (Idle, Start, StartStop, Shutdown, OpenHatch) or the drive blend space
//    (BS_CarrierFull_Drive), with a short crossfade between them. PlayState() starts
//    one (like PlayAnimation); SetDriveState() / SetPlayRate() / SetBlendSpacePosition()
//    update it every tick of the timer; IsPlaying() tells when a one-shot has ended.
// 2. Procedural bones on top of the clip pose, in the proxy's Evaluate:
//    - wheel spin from distance / radius (wheel_* and capsule_wheel_*), replacing
//      the clip's wheel rotation, with the inner wheels slower in a turn;
//    - front steer yaw (steer_fl/fr) from the yaw rate (bicycle model) or the steer input;
//    - the towed capsule: yaw at the coupler from the kinematic hitch model
//      dTheta = (v/L) sin(phi - theta), limited where the top-view footprints would touch
//      (a cushioned stop, rate-capped, straightened on a teleport), with a slow jackknife in
//      reverse; pitch and roll from the ground under its own two wheels; capsule_root
//      rotated about the coupler pivot;
//    - spring-damper secondary motion: trailer sway and bob, drawbar (coupler) rattle,
//      mast whip, lining jiggle;
//    - body dynamics: squat on acceleration and dip on braking (+-3 deg), roll in turns
//      (+-4 deg), bounce from the suspension;
//    - idle life: eye saccades (and a glance into turns) and blinks.
// 3. Inputs arrive from the pawn in FSaskartaCarrierAnimInputs, set on its existing
//    timers (UpdateAnim 10 Hz, UpdateGround 30 Hz); no Blueprint Tick.
//
// Bones (SKEL_CarrierFull, from task-CARRIER-report.md): root, carrier_root, body,
// mast, eye_l, eye_r, steer_fl, steer_fr, wheel_fl, wheel_fr, wheel_rl, wheel_rr,
// coupler, capsule_root, capsule_hatch, capsule_lining, capsule_wheel_l,
// capsule_wheel_r, lock. The source file's left/right labels are MIRRORED: *_l /
// *_fl sit on the carrier's RIGHT. Nothing here depends on the labels: each wheel's
// side comes from its reference-pose position.
//
// Mesh space: the carrier's front is mesh +Y, up is +Z, so its right is mesh -X
// (the mesh sits at yaw -90 in the pawn). Change MeshForward / MeshUp in the tuning
// if a re-import turns it.

#pragma once

#include "CoreMinimal.h"
#include "Animation/AnimInstance.h"
#include "SaskartaCarrierAnimInstance.generated.h"

class UAnimationAsset;
class USkeletalMeshComponent;

/** What the pawn feeds in. Set it with SetCarrierInputs from the pawn's timers. */
USTRUCT(BlueprintType)
struct SASKARTACORE_API FSaskartaCarrierAnimInputs
{
    GENERATED_BODY()

    /** Ground speed along the carrier's forward, cm/s (negative in reverse). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Carrier")
    float Speed = 0.f;

    /** Acceleration along the forward, cm/s^2 (+ speeding up, - braking). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Carrier")
    float Accel = 0.f;

    /** Yaw rate, deg/s, + = turning right (UE yaw increasing). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Carrier")
    float YawRate = 0.f;

    /** Steer input -1..1, + = right. Used when Tuning.bSteerFromYawRate is off. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Carrier")
    float Steer = 0.f;

    /** Ground slope along the heading, deg, + = climbing. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Carrier")
    float Slope = 0.f;

    /** World Z (cm) of the ground under each carrier wheel (the pawn's four UpdateGround traces). Only their changes are used (the bounce). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Carrier")
    float GroundFL = 0.f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Carrier")
    float GroundFR = 0.f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Carrier")
    float GroundRL = 0.f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Carrier")
    float GroundRR = 0.f;

    /** The four Ground* values are real trace hits this time. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Carrier")
    bool bHasWheelGround = false;

    /**
     * Ground under capsule_wheel_l / capsule_wheel_r relative to the carrier's ground
     * plane, cm (+ = the ground is higher than the wheel would sit if the capsule were
     * rigid with the carrier). UpdateTrailerGround() fills these; SetCarrierInputs keeps
     * the previous values when bHasTrailerGround is false in the new struct.
     */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Carrier")
    float TrailerGroundL = 0.f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Carrier")
    float TrailerGroundR = 0.f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Carrier")
    bool bHasTrailerGround = false;
};

/** Every tunable: bone names, geometry, stiffness, damping and the clamps. */
USTRUCT(BlueprintType)
struct SASKARTACORE_API FSaskartaCarrierAnimTuning
{
    GENERATED_BODY()

    // ── Bones ──
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Bones") FName BoneBody = TEXT("body");
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Bones") FName BoneMast = TEXT("mast");
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Bones") FName BoneEyeL = TEXT("eye_l");
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Bones") FName BoneEyeR = TEXT("eye_r");
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Bones") FName BoneSteerFL = TEXT("steer_fl");
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Bones") FName BoneSteerFR = TEXT("steer_fr");
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Bones") FName BoneWheelFL = TEXT("wheel_fl");
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Bones") FName BoneWheelFR = TEXT("wheel_fr");
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Bones") FName BoneWheelRL = TEXT("wheel_rl");
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Bones") FName BoneWheelRR = TEXT("wheel_rr");
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Bones") FName BoneCoupler = TEXT("coupler");
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Bones") FName BoneCapsuleRoot = TEXT("capsule_root");
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Bones") FName BoneCapsuleLining = TEXT("capsule_lining");
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Bones") FName BoneCapsuleWheelL = TEXT("capsule_wheel_l");
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Bones") FName BoneCapsuleWheelR = TEXT("capsule_wheel_r");

    /** The carrier's forward and up in mesh (component) space. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Bones") FVector MeshForward = FVector(0.f, 1.f, 0.f);
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Bones") FVector MeshUp = FVector(0.f, 0.f, 1.f);

    // ── Clip ──
    /** Crossfade between states, seconds. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Clip", meta = (ClampMin = "0")) float StateBlendTime = 0.2f;
    /** States in which the idle life (eyes) and the rattle stop (the carrier is switched off). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Clip") TArray<FName> OffStates = { TEXT("Off"), TEXT("Shutdown") };

    // ── Wheels ──
    /** Replace the clip's wheel rotation with the spin from distance travelled. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Wheels") bool bProceduralWheelSpin = true;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Wheels", meta = (ClampMin = "1")) float WheelRadius = 25.f;
    /** capsule_wheel_*: the Drive clip turned them at 150 deg/s against the carrier's 180, so about 30 cm. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Wheels", meta = (ClampMin = "1")) float TrailerWheelRadius = 30.f;
    /** Inner wheels turn slower in a turn. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Wheels") bool bWheelDifferential = true;

    // ── Steering ──
    /** Replace the clip's steer rotation with the procedural steer angle. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Steering") bool bProceduralSteer = true;
    /** Steer from the yaw rate (bicycle model); off: from Inputs.Steer. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Steering") bool bSteerFromYawRate = true;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Steering", meta = (ClampMin = "0", ClampMax = "80")) float MaxSteerDeg = 30.f;
    /** Front to rear axle; 0 = measured from the wheel bones. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Steering", meta = (ClampMin = "0")) float Wheelbase = 0.f;
    /** Below this speed the bicycle model uses this speed (turning in place does not snap to full lock). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Steering", meta = (ClampMin = "1")) float SteerMinSpeed = 60.f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Steering", meta = (ClampMin = "0")) float SteerStiffness = 300.f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Steering", meta = (ClampMin = "0")) float SteerDamping = 35.f;

    // ── Trailer (the towed capsule) ──
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Trailer") bool bTrailer = true;
    /** Coupler to the capsule's axle; 0 = measured from the bones. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Trailer", meta = (ClampMin = "0")) float TrailerLength = 0.f;
    /** How far the coupler sits behind the carrier's turning centre (0 = the simple model). Ignored when bMeasureHitchOffset. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Trailer") float HitchOffset = 0.f;
    /**
     * Take the hitch offset from the coupler bone: its distance behind the mesh origin,
     * which is the pawn's turning centre (78 cm on SK_CarrierFull). The coupler then
     * swings sideways when the carrier turns on the spot, as a real one does.
     */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Trailer") bool bMeasureHitchOffset = true;
    /** An upper cap on the hitch angle. The footprint limit below is usually tighter. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Trailer", meta = (ClampMin = "0", ClampMax = "89")) float MaxHitchDeg = 70.f;
    /**
     * Limit the hitch so the capsule never folds into the carrier: the angle at which the
     * two top-view footprints below first touch, less HitchClearanceDeg.
     */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Trailer") bool bHitchFootprintLimit = true;
    /**
     * The carrier's top-view outline (body and rear wheels), CONVEX, relative to the
     * coupler: X across, Y along the carrier's forward (+ ahead of the coupler), cm.
     * Measured from carrier01_full.fbx (coupler at y -78; body rear y -80, x +-54;
     * rear wheels to x +-65.6).
     */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Trailer")
    TArray<FVector2D> CarrierFootprint = {
        FVector2D(66.0, 158.0), FVector2D(66.0, 22.0), FVector2D(64.0, 8.3), FVector2D(62.6, 5.0), FVector2D(60.0, 3.4),
        FVector2D(21.0, -2.3), FVector2D(-21.0, -2.3), FVector2D(-60.0, 3.4), FVector2D(-62.6, 5.0), FVector2D(-64.0, 8.3),
        FVector2D(-66.0, 22.0), FVector2D(-66.0, 158.0) };
    /**
     * The capsule's top-view outline, CONVEX, same frame with the hitch straight: its
     * rounded nose starts 19 cm behind the coupler and is 105 cm wide from 27 cm back.
     * With these the top views touch at 28.3 deg (the shells themselves would meet near
     * 57 deg, the capsule's upper body over the rear wheels; the top view is what the
     * drone sees, so it is the limit).
     */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Trailer")
    TArray<FVector2D> TrailerFootprint = {
        FVector2D(16.7, -18.8), FVector2D(32.2, -19.5), FVector2D(37.2, -20.0), FVector2D(41.9, -21.1), FVector2D(44.9, -21.9),
        FVector2D(47.8, -23.2), FVector2D(49.6, -24.4), FVector2D(52.1, -27.4), FVector2D(52.5, -30.6), FVector2D(53.4, -38.8),
        FVector2D(64.0, -172.0), FVector2D(64.0, -316.0), FVector2D(-64.0, -316.0), FVector2D(-64.0, -172.0),
        FVector2D(-53.4, -38.8), FVector2D(-52.5, -30.6), FVector2D(-52.1, -27.4), FVector2D(-49.6, -24.4), FVector2D(-47.8, -23.2),
        FVector2D(-44.9, -21.9), FVector2D(-41.9, -21.1), FVector2D(-37.2, -20.0), FVector2D(-32.2, -19.5), FVector2D(-16.7, -18.8) };
    /** The gap kept below the footprint contact angle, deg. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Trailer", meta = (ClampMin = "0")) float HitchClearanceDeg = 3.f;
    /** Over the last this-many degrees before the limit the capsule eases to a stop (a cushioned hitch stop, not a wall). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Trailer", meta = (ClampMin = "0")) float HitchSoftZoneDeg = 8.f;
    /** The hitch never swings faster than this, deg/s (a turn on the spot needs about 115). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Trailer", meta = (ClampMin = "1")) float MaxHitchRateDeg = 140.f;
    /**
     * Drive the hitch from the owner's own per-frame motion (signed speed along its
     * forward, yaw rate) instead of the 10 Hz Inputs, and straighten it on a teleport.
     */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Trailer") bool bHitchFromOwnerMotion = true;
    /** One frame's move farther than this (cm), or faster than TeleportSpeed / TeleportYawRateDeg, is a teleport: the hitch goes straight. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Trailer", meta = (ClampMin = "1")) float TeleportDistance = 250.f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Trailer", meta = (ClampMin = "1")) float TeleportSpeed = 2500.f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Trailer", meta = (ClampMin = "1")) float TeleportYawRateDeg = 400.f;
    /** Scales the jackknife growth in reverse (1 = the pure model; smaller = slower). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Trailer", meta = (ClampMin = "0")) float ReverseJackknifeScale = 0.35f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Trailer", meta = (ClampMin = "0")) float MaxTrailerPitchDeg = 20.f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Trailer", meta = (ClampMin = "0")) float MaxTrailerRollDeg = 15.f;
    /** Pitch / roll follow the ground through this spring (lightly damped, so the capsule bobs). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Trailer", meta = (ClampMin = "0")) float TrailerTiltStiffness = 120.f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Trailer", meta = (ClampMin = "0")) float TrailerTiltDamping = 14.f;
    /** Sway: extra yaw, deg per cm/s^2 of lateral acceleration (the capsule swings out). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Trailer") float SwayPerLateralAccel = 0.003f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Trailer", meta = (ClampMin = "0")) float MaxSwayDeg = 4.f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Trailer", meta = (ClampMin = "0")) float SwayStiffness = 40.f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Trailer", meta = (ClampMin = "0")) float SwayDamping = 5.f;
    /** Bob: the capsule lags a change of the ground under its wheels by this share, then springs back. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Trailer", meta = (ClampMin = "0")) float TrailerBobCoupling = 0.6f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Trailer", meta = (ClampMin = "0")) float TrailerBobStiffness = 150.f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Trailer", meta = (ClampMin = "0")) float TrailerBobDamping = 9.f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Trailer", meta = (ClampMin = "0")) float MaxTrailerBobCm = 5.f;
    /** UpdateTrailerGround: trace from this high above each capsule wheel ... */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Trailer", meta = (ClampMin = "0")) float TrailerTraceUp = 60.f;
    /** ... to this far below it. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Trailer", meta = (ClampMin = "0")) float TrailerTraceDown = 120.f;
    /** Ground offsets beyond this are clamped (a missing hit reads 0). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Trailer", meta = (ClampMin = "0")) float MaxTrailerGroundCm = 60.f;

    // ── Drawbar rattle (a small pitch jitter at the coupler) ──
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Rattle", meta = (ClampMin = "0")) float RattleMaxDeg = 0.8f;
    /** Random velocity kicks per second at 500 cm/s, deg/s. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Rattle", meta = (ClampMin = "0")) float RattleKick = 40.f;
    /** Extra kick per cm of change in the ground under the wheels. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Rattle", meta = (ClampMin = "0")) float RattleRoughnessGain = 8.f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Rattle", meta = (ClampMin = "0")) float RattleStiffness = 900.f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Rattle", meta = (ClampMin = "0")) float RattleDamping = 14.f;

    // ── Body ──
    /** Nose-up deg per cm/s^2 of acceleration (squat; braking dips the nose). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Body") float BodyPitchPerAccel = 0.005f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Body", meta = (ClampMin = "0")) float MaxBodyPitchDeg = 3.f;
    /** Outward roll deg per cm/s^2 of lateral acceleration. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Body") float BodyRollPerLateralAccel = 0.004f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Body", meta = (ClampMin = "0")) float MaxBodyRollDeg = 4.f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Body", meta = (ClampMin = "0")) float BodyStiffness = 80.f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Body", meta = (ClampMin = "0")) float BodyDamping = 11.f;
    /** Bounce: the body lags a change of the mean wheel ground height by this share, then springs back. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Body", meta = (ClampMin = "0")) float BounceCoupling = 0.5f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Body", meta = (ClampMin = "0")) float BounceStiffness = 180.f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Body", meta = (ClampMin = "0")) float BounceDamping = 12.f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Body", meta = (ClampMin = "0")) float MaxBounceCm = 4.f;

    // ── Mast whip ──
    /** The mast lags the body's angular acceleration by this share. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Mast", meta = (ClampMin = "0")) float MastInertia = 0.6f;
    /** Tip-back per cm/s^2 of acceleration, and outward lean per cm/s^2 of lateral acceleration, as accelerations on the spring. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Mast") float MastAccelGain = 0.25f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Mast") float MastLateralGain = 0.25f;
    /** Share of the slope the mast leans back against (stays nearer upright on a climb). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Mast") float MastSlopeCompensation = 0.3f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Mast", meta = (ClampMin = "0")) float MaxMastDeg = 6.f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Mast", meta = (ClampMin = "0")) float MastStiffness = 90.f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Mast", meta = (ClampMin = "0")) float MastDamping = 5.f;

    // ── Lining jiggle (capsule_lining moves along up) ──
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Lining", meta = (ClampMin = "0")) float LiningGain = 0.6f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Lining", meta = (ClampMin = "0")) float MaxLiningCm = 1.5f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Lining", meta = (ClampMin = "0")) float LiningStiffness = 220.f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Lining", meta = (ClampMin = "0")) float LiningDamping = 6.f;

    // ── Idle life ──
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Eyes") bool bIdleLife = true;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Eyes", meta = (ClampMin = "0")) float SaccadeYawDeg = 8.f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Eyes", meta = (ClampMin = "0")) float SaccadePitchDeg = 4.f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Eyes", meta = (ClampMin = "0.05")) float SaccadeIntervalMin = 0.6f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Eyes", meta = (ClampMin = "0.05")) float SaccadeIntervalMax = 2.8f;
    /** High: saccades are quick jumps (critically damped). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Eyes", meta = (ClampMin = "0")) float SaccadeStiffness = 900.f;
    /** The eyes glance this far into a full-lock turn. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Eyes") float EyeSteerLookDeg = 12.f;
    /** Blink: scale the eyes along up to this, for BlinkDuration, every BlinkInterval* seconds. 1 = no blink. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Eyes", meta = (ClampMin = "0", ClampMax = "1")) float BlinkMinScale = 0.15f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Eyes", meta = (ClampMin = "0.02")) float BlinkDuration = 0.15f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Eyes", meta = (ClampMin = "0.1")) float BlinkIntervalMin = 2.5f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Eyes", meta = (ClampMin = "0.1")) float BlinkIntervalMax = 6.f;

    // ── Camera ──
    /** GetCameraBodyDynamics returns this share of the body's pitch and roll. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Camera", meta = (ClampMin = "0", ClampMax = "1")) float CameraBodyShare = 0.3f;
};

UCLASS(Transient, Blueprintable, BlueprintType)
class SASKARTACORE_API USaskartaCarrierAnimInstance : public UAnimInstance
{
    GENERATED_BODY()

    friend struct FSaskartaCarrierAnimProxy;

public:
    /** Puts Mesh in Animation Blueprint mode with this class (if it is not already) and returns the instance. */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Carrier")
    static USaskartaCarrierAnimInstance* InstallOn(USkeletalMeshComponent* Mesh);

    /** The pawn's inputs (from its timers). Keeps the previous trailer ground when NewInputs.bHasTrailerGround is false. */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Carrier")
    void SetCarrierInputs(const FSaskartaCarrierAnimInputs& NewInputs);

    /**
     * The motion part of the inputs, straight from the values the pawn's 10 Hz UpdateAnim
     * already has: Speed (cm/s), YawRate (deg/s, + right) and SlopeRiseOverRun (its
     * "slope": the rise over the distance covered). Accel is derived here from successive
     * calls; Steer is left as it was. The ground fields are kept.
     */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Carrier")
    void SetMotionInputs(float Speed, float YawRate, float SlopeRiseOverRun);

    /** Holds the wheel angles after a shutdown, even if a late drive timer sends motion inputs. */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Carrier")
    void SetWheelSpinLocked(bool bLocked);

    /** The four wheel ground hits only (world Z, cm; for the pawn's 30 Hz UpdateGround; the motion fields are kept). */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Carrier")
    void SetWheelGround(float GroundFL, float GroundFR, float GroundRL, float GroundRR);

    UFUNCTION(BlueprintCallable, Category = "Saskarta|Carrier")
    void SetTuning(const FSaskartaCarrierAnimTuning& NewTuning);

    /** Starts Asset from its beginning under the name State (crossfading from the current one), like PlayAnimation. */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Carrier", meta = (AdvancedDisplay = "InPlayRate"))
    void PlayState(FName State, UAnimationAsset* Asset, bool bLoop = true, float InPlayRate = 1.f);

    /** Remembers the asset of a state, so SetDriveState can switch to it by name. */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Carrier")
    void SetStateAsset(FName State, UAnimationAsset* Asset, bool bLoop = true);

    /**
     * The per-tick update: play rate and blend-space input (X steer -1..1, Y strain 0..1).
     * A different State with a SetStateAsset asset switches to it; otherwise only the
     * name is recorded.
     */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Carrier")
    void SetDriveState(FName State, float InPlayRate, FVector2D InBlendInput);

    /** Same as on the single-node instance (a drop-in for the existing UpdateDrive nodes). */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Carrier")
    void SetPlayRate(float InPlayRate);

    UFUNCTION(BlueprintCallable, Category = "Saskarta|Carrier")
    void SetBlendSpacePosition(FVector InPosition);

    /** False once a non-looping clip has reached its end (the one-shots: Start, StartStop, Shutdown). */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Carrier")
    bool IsPlaying() const;

    UFUNCTION(BlueprintPure, Category = "Saskarta|Carrier")
    FName GetDriveState() const { return CurrentState; }

    UFUNCTION(BlueprintPure, Category = "Saskarta|Carrier")
    float GetClipTime() const { return OutClipTime; }

    UFUNCTION(BlueprintPure, Category = "Saskarta|Carrier")
    float GetClipLength() const { return OutClipLength; }

    /**
     * Traces the ground under the two capsule wheels (where they would be with the
     * current hitch angle, rigid in the carrier's ground plane) and stores the offsets
     * in Inputs.TrailerGroundL/R. Call it from the pawn's UpdateGround timer.
     */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Carrier")
    void UpdateTrailerGround();

    /**
     * About 30 % (Tuning.CameraBodyShare) of the body's pitch and roll, as a rotator in
     * the carrier's actor space (Pitch + nose up, Roll + right side down), for the
     * camera to add to its relative rotation.
     */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Carrier")
    FRotator GetCameraBodyDynamics() const;

    /** The full body dynamics: pitch (+ nose up), roll (+ right side down), heave (cm, + up). */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Carrier")
    void GetBodyDynamics(float& PitchDeg, float& RollDeg, float& HeaveCm) const;

    /** The capsule's yaw relative to the carrier, deg (+ = its nose points right of the carrier's heading). */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Carrier")
    float GetHitchAngle() const { return OutHitchDeg; }

    /**
     * Straightens the capsule behind the carrier at once (and settles its springs). Call
     * it after moving the carrier by hand: a respawn, a checkpoint, a sequence. Moves that
     * are too far or too fast for driving are caught on their own (Tuning.TeleportDistance).
     */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Carrier")
    void ResetHitch();

    /** The hitch limit in use, deg (the footprint limit, capped by Tuning.MaxHitchDeg). */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Carrier")
    float GetHitchLimit() const { return OutHitchLimitDeg; }

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Carrier")
    FSaskartaCarrierAnimInputs Inputs;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Carrier")
    FSaskartaCarrierAnimTuning Tuning;

protected:
    virtual FAnimInstanceProxy* CreateAnimInstanceProxy() override;
    virtual void DestroyAnimInstanceProxy(FAnimInstanceProxy* InProxy) override;

private:
    /** Game-thread copy of the capsule geometry for UpdateTrailerGround (reference pose, component space). */
    bool CacheTrailerGeometry(const USkeletalMeshComponent* Mesh);

    UPROPERTY(Transient)
    TObjectPtr<UAnimationAsset> CurrentAsset;

    /** Every asset played so far, kept alive while the proxy may still crossfade out of it. */
    UPROPERTY(Transient)
    TArray<TObjectPtr<UAnimationAsset>> KeptAssets;

    UPROPERTY(Transient)
    TMap<FName, TObjectPtr<UAnimationAsset>> StateAssets;

    TMap<FName, bool> StateLoops;

    FName CurrentState;
    bool bLoopRequested = true;
    float PlayRate = 1.f;
    FVector BlendInput = FVector::ZeroVector;
    /** Bumped by PlayState; the proxy restarts the clip when it changes. */
    int32 PlaySerial = 0;

    // Written by the proxy's PostUpdate.
    float OutClipTime = 0.f;
    float OutClipLength = 0.f;
    bool bOutClipFinished = false;
    float OutBodyPitchDeg = 0.f;
    float OutBodyRollDeg = 0.f;
    float OutBodyHeaveCm = 0.f;
    float OutHitchDeg = 0.f;
    float OutHitchLimitDeg = 0.f;
    /** Bumped by ResetHitch; the proxy straightens the hitch when it changes. */
    int32 HitchResetSerial = 0;

    // SetMotionInputs' acceleration estimate.
    float LastMotionSpeed = 0.f;
    double LastMotionTime = -1.0;
    bool bWheelSpinLocked = false;

    // UpdateTrailerGround's geometry.
    TWeakObjectPtr<const USkeletalMesh> TrailerGeometryMesh;
    bool bTrailerGeometryValid = false;
    FVector RefCoupler = FVector::ZeroVector;
    FVector RefTrailerWheelL = FVector::ZeroVector;
    FVector RefTrailerWheelR = FVector::ZeroVector;
};
