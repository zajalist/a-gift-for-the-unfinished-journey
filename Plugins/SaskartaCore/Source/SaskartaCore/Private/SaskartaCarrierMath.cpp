// SaskartaCarrierMath (task CARRIERANIM). See the header.

#include "SaskartaCarrierMath.h"

namespace SaskartaCarrierMath
{
    static int32 SubstepCount(float DtS)
    {
        return FMath::Clamp(FMath::CeilToInt(DtS / MaxSubstepS), 1, 256);
    }

    void StepSpring(FSpring& S, float Target, float Stiffness, float Damping, float DtS, float ExternalAccel)
    {
        if (!FMath::IsFinite(S.X) || !FMath::IsFinite(S.V))
        {
            S.X = FMath::IsFinite(Target) ? Target : 0.f;
            S.V = 0.f;
        }
        const float Dt = FMath::Clamp(DtS, 0.f, MaxFrameS);
        if (Dt <= 0.f)
        {
            return;
        }
        const int32 N = SubstepCount(Dt);
        const float H = Dt / static_cast<float>(N);
        const float K = FMath::Max(0.f, Stiffness);
        const float C = FMath::Max(0.f, Damping);
        for (int32 I = 0; I < N; ++I)
        {
            const float A = -K * (S.X - Target) - C * S.V + ExternalAccel;
            S.V += A * H;
            S.X += S.V * H;
        }
        if (!FMath::IsFinite(S.X) || !FMath::IsFinite(S.V))
        {
            S.X = FMath::IsFinite(Target) ? Target : 0.f;
            S.V = 0.f;
        }
    }

    float CriticalDamping(float Stiffness)
    {
        return 2.f * FMath::Sqrt(FMath::Max(0.f, Stiffness));
    }

    float HitchAngleRate(float PsiRad, float SpeedCmS, float YawRateRadS, float LengthCm, float HitchOffsetCm, float ReverseGrowthScale)
    {
        const float L = FMath::Max(1.f, LengthCm);
        float Follow = -(SpeedCmS / L) * FMath::Sin(PsiRad);
        if (SpeedCmS < 0.f)
        {
            Follow *= FMath::Max(0.f, ReverseGrowthScale);
        }
        return Follow - YawRateRadS * (1.f + (HitchOffsetCm / L) * FMath::Cos(PsiRad));
    }

    float StepHitchAngle(float PsiRad, float SpeedCmS, float YawRateRadS, float LengthCm, float HitchOffsetCm, float DtS, float MaxPsiRad, float ReverseGrowthScale)
    {
        const float Max = FMath::Max(0.f, MaxPsiRad);
        float Psi = FMath::IsFinite(PsiRad) ? FMath::Clamp(PsiRad, -Max, Max) : 0.f;
        const float Dt = FMath::Clamp(DtS, 0.f, MaxFrameS);
        if (Dt <= 0.f)
        {
            return Psi;
        }
        const int32 N = SubstepCount(Dt);
        const float H = Dt / static_cast<float>(N);
        for (int32 I = 0; I < N; ++I)
        {
            Psi += HitchAngleRate(Psi, SpeedCmS, YawRateRadS, LengthCm, HitchOffsetCm, ReverseGrowthScale) * H;
            Psi = FMath::Clamp(Psi, -Max, Max);
        }
        return FMath::IsFinite(Psi) ? Psi : 0.f;
    }

    float LimitHitchRate(float PsiRad, float RateRadS, const FHitchLimits& Limits)
    {
        if (!FMath::IsFinite(RateRadS))
        {
            return 0.f;
        }
        const float Max = FMath::Max(0.f, Limits.MaxPsiRad);
        const float Soft = FMath::Clamp(Limits.SoftZoneRad, 0.f, Max);
        float Rate = RateRadS;
        // Only the rate that opens the angle further is cushioned.
        if (Soft > UE_KINDA_SMALL_NUMBER && PsiRad * Rate > 0.f)
        {
            const float X = FMath::Clamp((FMath::Abs(PsiRad) - (Max - Soft)) / Soft, 0.f, 1.f);
            // 1 - smoothstep: 1 at the zone's start, 0 with zero slope at the limit, so the
            // angle eases into the limit (asymptotically) instead of hitting it.
            Rate *= 1.f - X * X * (3.f - 2.f * X);
        }
        const float MaxRate = FMath::Max(0.f, Limits.MaxRateRadS);
        return FMath::Clamp(Rate, -MaxRate, MaxRate);
    }

    float StepHitchAngleLimited(float PsiRad, float SpeedCmS, float YawRateRadS, float LengthCm, float HitchOffsetCm, float DtS, const FHitchLimits& Limits, float ReverseGrowthScale)
    {
        const float Max = FMath::Max(0.f, Limits.MaxPsiRad);
        float Psi = FMath::IsFinite(PsiRad) ? FMath::Clamp(PsiRad, -Max, Max) : 0.f;
        const float Dt = FMath::Clamp(DtS, 0.f, MaxFrameS);
        if (Dt <= 0.f || !FMath::IsFinite(SpeedCmS) || !FMath::IsFinite(YawRateRadS))
        {
            return Psi;
        }
        const int32 N = SubstepCount(Dt);
        const float H = Dt / static_cast<float>(N);
        for (int32 I = 0; I < N; ++I)
        {
            const float Rate = HitchAngleRate(Psi, SpeedCmS, YawRateRadS, LengthCm, HitchOffsetCm, ReverseGrowthScale);
            Psi += LimitHitchRate(Psi, Rate, Limits) * H;
            Psi = FMath::Clamp(Psi, -Max, Max);
        }
        return FMath::IsFinite(Psi) ? Psi : 0.f;
    }

    // Separating-axis test of two convex polygons (either winding). Touching counts as overlap.
    static bool ConvexOverlap(const FVector2D* A, int32 NumA, const FVector2D* B, int32 NumB)
    {
        const FVector2D* Polys[2] = { A, B };
        const int32 Nums[2] = { NumA, NumB };
        for (int32 P = 0; P < 2; ++P)
        {
            for (int32 I = 0; I < Nums[P]; ++I)
            {
                const FVector2D E = Polys[P][(I + 1) % Nums[P]] - Polys[P][I];
                const FVector2D Axis(-E.Y, E.X);
                double MinA = 1e30, MaxA = -1e30, MinB = 1e30, MaxB = -1e30;
                for (int32 J = 0; J < NumA; ++J)
                {
                    const double D = A[J].X * Axis.X + A[J].Y * Axis.Y;
                    MinA = FMath::Min(MinA, D);
                    MaxA = FMath::Max(MaxA, D);
                }
                for (int32 J = 0; J < NumB; ++J)
                {
                    const double D = B[J].X * Axis.X + B[J].Y * Axis.Y;
                    MinB = FMath::Min(MinB, D);
                    MaxB = FMath::Max(MaxB, D);
                }
                if (MaxA < MinB || MaxB < MinA)
                {
                    return false;
                }
            }
        }
        return true;
    }

    static constexpr int32 MaxFootprintPoints = 64;

    // The trailer turned by Angle about the coupler (the origin) touches the carrier.
    static bool TouchesAt(const FVector2D* Carrier, int32 NumCarrier, const FVector2D* Trailer, int32 NumTrailer, float Angle)
    {
        FVector2D Turned[MaxFootprintPoints];
        const double C = FMath::Cos(Angle);
        const double S = FMath::Sin(Angle);
        for (int32 I = 0; I < NumTrailer; ++I)
        {
            Turned[I] = FVector2D(C * Trailer[I].X - S * Trailer[I].Y, S * Trailer[I].X + C * Trailer[I].Y);
        }
        return ConvexOverlap(Carrier, NumCarrier, Turned, NumTrailer);
    }

    float FootprintContactAngle(const FVector2D* Carrier, int32 NumCarrier, const FVector2D* Trailer, int32 NumTrailer, float SearchMaxRad)
    {
        if (!Carrier || !Trailer || NumCarrier < 3 || NumTrailer < 3 || NumCarrier > MaxFootprintPoints || NumTrailer > MaxFootprintPoints)
        {
            return -1.f;
        }
        const float SearchMax = FMath::Clamp(SearchMaxRad, 0.f, UE_PI);
        if (TouchesAt(Carrier, NumCarrier, Trailer, NumTrailer, 0.f))
        {
            return -1.f;
        }
        float Best = SearchMax;
        for (const float Side : { 1.f, -1.f })
        {
            // March in 0.5 deg steps to the first touch, then bisect it to ~0.001 deg.
            const float Step = FMath::DegreesToRadians(0.5f);
            float Clear = 0.f;
            float Hit = -1.f;
            for (float A = Step; A <= Best + Step * 0.5f; A += Step)
            {
                const float At = FMath::Min(A, Best);
                if (TouchesAt(Carrier, NumCarrier, Trailer, NumTrailer, Side * At))
                {
                    Hit = At;
                    break;
                }
                Clear = At;
            }
            if (Hit < 0.f)
            {
                continue;
            }
            for (int32 I = 0; I < 20; ++I)
            {
                const float Mid = 0.5f * (Clear + Hit);
                if (TouchesAt(Carrier, NumCarrier, Trailer, NumTrailer, Side * Mid))
                {
                    Hit = Mid;
                }
                else
                {
                    Clear = Mid;
                }
            }
            Best = FMath::Min(Best, Clear);
        }
        return Best;
    }

    float SafeHitchAngle(const FVector2D* Carrier, int32 NumCarrier, const FVector2D* Trailer, int32 NumTrailer, float ClearanceRad, float UserMaxRad)
    {
        const float UserMax = FMath::Clamp(UserMaxRad, 0.f, FMath::DegreesToRadians(89.f));
        const float Contact = FootprintContactAngle(Carrier, NumCarrier, Trailer, NumTrailer, UserMax + FMath::Max(0.f, ClearanceRad));
        if (Contact < 0.f)
        {
            return UserMax;
        }
        return FMath::Clamp(Contact - FMath::Max(0.f, ClearanceRad), 0.f, UserMax);
    }

    float SoftClampAngle(float X, float Max, float Knee)
    {
        if (!FMath::IsFinite(X))
        {
            return 0.f;
        }
        const float M = FMath::Max(0.f, Max);
        const float K = FMath::Clamp(Knee, 0.f, M);
        const float Start = M - K;
        const float A = FMath::Abs(X);
        if (A <= Start)
        {
            return X;
        }
        if (K <= UE_KINDA_SMALL_NUMBER)
        {
            return FMath::Clamp(X, -M, M);
        }
        const float Bent = M - K * FMath::Exp(-(A - Start) / K);
        return X < 0.f ? -Bent : Bent;
    }

    bool IsTeleportStep(float DistanceCm, float YawStepRad, float DtS, float TeleportDistanceCm, float MaxSpeedCmS, float MaxYawRateRadS)
    {
        if (!FMath::IsFinite(DistanceCm) || !FMath::IsFinite(YawStepRad))
        {
            return true;
        }
        const float Distance = FMath::Abs(DistanceCm);
        const float Yaw = FMath::Abs(YawStepRad);
        if (Distance > FMath::Max(1.f, TeleportDistanceCm))
        {
            return true;
        }
        const float Dt = FMath::Max(DtS, 1.0e-3f);
        // Small steps are never teleports, whatever the frame time (a hitch in the frame rate).
        const bool bFastMove = Distance > 20.f && Distance / Dt > FMath::Max(1.f, MaxSpeedCmS);
        const bool bFastTurn = Yaw > FMath::DegreesToRadians(5.f) && Yaw / Dt > FMath::Max(0.01f, MaxYawRateRadS);
        return bFastMove || bFastTurn;
    }

    float SteadyHitchAngle(float SpeedCmS, float YawRateRadS, float LengthCm)
    {
        if (FMath::Abs(SpeedCmS) < UE_KINDA_SMALL_NUMBER)
        {
            return 0.f;
        }
        return FMath::Asin(FMath::Clamp(-YawRateRadS * FMath::Max(1.f, LengthCm) / SpeedCmS, -1.f, 1.f));
    }

    float SteerFromYawRate(float YawRateRadS, float SpeedCmS, float WheelbaseCm, float MaxSteerRad, float MinSpeedCmS)
    {
        const float Speed = FMath::Max(FMath::Abs(SpeedCmS), FMath::Max(1.f, MinSpeedCmS));
        const float Sign = SpeedCmS < 0.f ? -1.f : 1.f;
        const float Steer = Sign * FMath::Atan(FMath::Max(0.f, WheelbaseCm) * YawRateRadS / Speed);
        return FMath::Clamp(Steer, -MaxSteerRad, MaxSteerRad);
    }

    float LateralAccel(float SpeedCmS, float YawRateRadS)
    {
        return SpeedCmS * YawRateRadS;
    }

    float ClampedGain(float Value, float Gain, float Limit)
    {
        const float L = FMath::Abs(Limit);
        return FMath::Clamp(Value * Gain, -L, L);
    }

    FVector2D TrailerPitchRoll(float HeightA, float LateralA, float HeightB, float LateralB, float LengthCm)
    {
        const float L = FMath::Max(1.f, LengthCm);
        const float Mean = 0.5f * (HeightA + HeightB);
        const float Pitch = -FMath::Asin(FMath::Clamp(Mean / L, -1.f, 1.f));
        const float Track = LateralA - LateralB;
        float Roll = 0.f;
        if (FMath::Abs(Track) > 1.f)
        {
            // A wheel to the right (positive lateral) standing higher lifts the right side: roll < 0.
            // (Atan of the slope, not Atan2, so the order of the two wheels does not matter.)
            Roll = -FMath::Atan((HeightA - HeightB) / Track);
        }
        return FVector2D(Pitch, Roll);
    }

    float WrapRadians(float A)
    {
        if (!FMath::IsFinite(A))
        {
            return 0.f;
        }
        A = FMath::Fmod(A + UE_PI, 2.f * UE_PI);
        if (A <= 0.f)
        {
            A += 2.f * UE_PI;
        }
        return A - UE_PI;
    }
}
