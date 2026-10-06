// SaskartaCarrierMath: the pure math behind USaskartaCarrierAnimInstance (task
// CARRIERANIM): the kinematic hitch model for the towed capsule, spring-dampers
// for the secondary motion, and small helpers. Free functions, so they are unit
// tested without a mesh (Private/Tests/SaskartaCarrierMathTest.cpp).
//
// Conventions (UE yaw): angles are positive for a RIGHT turn / yaw; the hitch
// angle Psi is the trailer's heading minus the carrier's heading, so a trailer
// pointing to the left of the carrier has Psi < 0.

#pragma once

#include "CoreMinimal.h"

namespace SaskartaCarrierMath
{
    /** Larger integration steps are split into steps of at most this. */
    inline constexpr float MaxSubstepS = 1.f / 240.f;
    /** Longer frames are clamped to this before integrating (hitches, breakpoints). */
    inline constexpr float MaxFrameS = 0.25f;

    /** A 1D spring-damper (unit mass). */
    struct FSpring
    {
        float X = 0.f;
        float V = 0.f;
    };

    /**
     * One step of X'' = -Stiffness (X - Target) - Damping X' + ExternalAccel, semi-implicit
     * Euler in substeps of at most MaxSubstepS. Non-finite state resets to Target at rest.
     */
    SASKARTACORE_API void StepSpring(FSpring& S, float Target, float Stiffness, float Damping, float DtS, float ExternalAccel = 0.f);

    /** The damping that makes a unit-mass spring of this stiffness critically damped (2 sqrt(k)). */
    SASKARTACORE_API float CriticalDamping(float Stiffness);

    /**
     * dPsi/dt of the kinematic single-axle trailer, with the hitch HitchOffsetCm behind
     * the carrier's turning centre:
     *   dPsi/dt = -(v / L) sin Psi - w (1 + (h / L) cos Psi)
     * (the brief's dTheta = (v/L) sin(phi - theta) with Psi = theta - phi, h = 0).
     * In reverse the first term destabilises (the jackknife); it is scaled by
     * ReverseGrowthScale so the jackknife is slow.
     */
    SASKARTACORE_API float HitchAngleRate(float PsiRad, float SpeedCmS, float YawRateRadS, float LengthCm, float HitchOffsetCm, float ReverseGrowthScale);

    /** Integrates HitchAngleRate over DtS (substepped) and clamps to +-MaxPsiRad. */
    SASKARTACORE_API float StepHitchAngle(float PsiRad, float SpeedCmS, float YawRateRadS, float LengthCm, float HitchOffsetCm, float DtS, float MaxPsiRad, float ReverseGrowthScale);

    /**
     * The hitch's limits (radians). The capsule may never fold into the carrier, so
     * MaxPsiRad comes from the footprints (SafeHitchAngle). Inside the last SoftZoneRad
     * the rate that opens the angle further fades to 0 (a cushioned stop, not a wall);
     * the rate that closes it is untouched. |dPsi/dt| never exceeds MaxRateRadS.
     */
    struct FHitchLimits
    {
        float MaxPsiRad = 0.5f;
        float SoftZoneRad = 0.f;
        float MaxRateRadS = 1.0e6f;
    };

    /** The rate after the soft stop and the rate limit (see FHitchLimits). */
    SASKARTACORE_API float LimitHitchRate(float PsiRad, float RateRadS, const FHitchLimits& Limits);

    /** StepHitchAngle with the soft stop and the rate limit; the hard clamp at MaxPsiRad stays as the last guard. */
    SASKARTACORE_API float StepHitchAngleLimited(float PsiRad, float SpeedCmS, float YawRateRadS, float LengthCm, float HitchOffsetCm, float DtS, const FHitchLimits& Limits, float ReverseGrowthScale);

    /**
     * The first hitch angle (radians, the smaller of the two sides) at which the trailer's
     * footprint touches the carrier's, turning the trailer about the coupler. Both are
     * CONVEX polygons in the top view, relative to the coupler: X across (either side),
     * Y along the carrier's forward (+ ahead of the coupler). Returns SearchMaxRad when
     * they never touch below it, and -1 when the polygons are unusable (fewer than 3
     * points each, or already overlapping when straight).
     */
    SASKARTACORE_API float FootprintContactAngle(const FVector2D* Carrier, int32 NumCarrier, const FVector2D* Trailer, int32 NumTrailer, float SearchMaxRad);

    /**
     * The hitch limit the anim uses: the footprint contact angle less ClearanceRad, never
     * above UserMaxRad (the tuning's MaxHitchDeg). Unusable footprints give UserMaxRad.
     */
    SASKARTACORE_API float SafeHitchAngle(const FVector2D* Carrier, int32 NumCarrier, const FVector2D* Trailer, int32 NumTrailer, float ClearanceRad, float UserMaxRad);

    /**
     * An angle that follows X up to Max - Knee, then bends smoothly towards Max without
     * ever reaching it (C1; the sway added on top of the hitch cannot push past the limit).
     */
    SASKARTACORE_API float SoftClampAngle(float X, float Max, float Knee);

    /**
     * True when one frame's motion cannot be driving: a teleport, a respawn, a checkpoint
     * or a sequence that moved the carrier. DistanceCm is the ground (XY) distance moved,
     * YawStepRad the wrapped yaw change, over DtS.
     */
    SASKARTACORE_API bool IsTeleportStep(float DistanceCm, float YawStepRad, float DtS, float TeleportDistanceCm, float MaxSpeedCmS, float MaxYawRateRadS);

    /** The forward steady-state hitch angle of a constant turn (h = 0): asin(-w L / v), or 0 when v ~ 0. */
    SASKARTACORE_API float SteadyHitchAngle(float SpeedCmS, float YawRateRadS, float LengthCm);

    /**
     * Front-wheel steer angle from the yaw rate (bicycle model): atan(Wheelbase w / |v|),
     * signed by the direction of travel, clamped to +-MaxSteerRad. Below MinSpeedCmS the
     * speed is taken as MinSpeedCmS (turning on the spot does not snap to full lock).
     */
    SASKARTACORE_API float SteerFromYawRate(float YawRateRadS, float SpeedCmS, float WheelbaseCm, float MaxSteerRad, float MinSpeedCmS);

    /** Centripetal acceleration of a turn, cm/s^2 (+ for a right turn going forward). */
    SASKARTACORE_API float LateralAccel(float SpeedCmS, float YawRateRadS);

    /** Value * Gain clamped to +-Limit. */
    SASKARTACORE_API float ClampedGain(float Value, float Gain, float Limit);

    /**
     * Trailer pitch and roll from the ground under its two wheels. Heights are relative
     * to the carrier's ground plane (+ = ground higher); Lateral is each wheel's offset to
     * the carrier's right; LengthCm is coupler to axle. Returns (Pitch, Roll) in radians:
     * Pitch + = nose up about the coupler (the rear rising gives a negative pitch),
     * Roll + = right side down.
     */
    SASKARTACORE_API FVector2D TrailerPitchRoll(float HeightA, float LateralA, float HeightB, float LateralB, float LengthCm);

    /** Wraps an angle to (-PI, PI]. */
    SASKARTACORE_API float WrapRadians(float A);
}
