// Storm shells, the pure part (task STORM-SHELLS). See SaskartaStormShellsLogic.h.
#include "SaskartaStormShellsLogic.h"

namespace SaskartaStormShells
{
    namespace
    {
        constexpr double Tau = 6.283185307179586;

        float SmoothStep(float E0, float E1, float X)
        {
            const float T = FMath::Clamp((X - E0) / (E1 - E0), 0.f, 1.f);
            return T * T * (3.f - 2.f * T);
        }
    }

    bool NextGate(bool bWasOn, float StormIntensity, float OffBelow, float OnAbove)
    {
        if (StormIntensity > OnAbove)
        {
            return true;
        }
        if (StormIntensity <= OffBelow)
        {
            return false;
        }
        return bWasOn;
    }

    FSaskartaStormShellTier TierFor(int32 Enabled, int32 Layers, int32 Detail)
    {
        FSaskartaStormShellTier T;
        if (Enabled <= 0 || Layers <= 0)
        {
            T.Shells = 0;
            T.DetailShells = 0;
            return T;
        }
        T.Shells = FMath::Clamp(Layers, 1, MaxShells);
        T.DetailShells = FMath::Clamp(Detail, 0, T.Shells);
        return T;
    }

    float PassWeight(bool bGateOn, const FSaskartaStormShellTier& Tier)
    {
        return (bGateOn && Tier.Shells > 0) ? 1.f : 0.f;
    }

    float FarRootCentered(const FVector3f& Dir, float R)
    {
        const float Dxy = FMath::Max(FMath::Sqrt(Dir.X * Dir.X + Dir.Y * Dir.Y), MinHorizontal);
        return R / Dxy;
    }

    float FarRootOffset(const FVector2f& Offset, const FVector3f& Dir, float R)
    {
        const float A = FMath::Max(Dir.X * Dir.X + Dir.Y * Dir.Y, MinHorizontal * MinHorizontal);
        const float B = Offset.X * Dir.X + Offset.Y * Dir.Y;
        const float C = Offset.X * Offset.X + Offset.Y * Offset.Y - R * R;
        return (-B + FMath::Sqrt(FMath::Max(B * B - A * C, 0.f))) / A;
    }

    float HeightProfile(float H, const FVector4f& Band)
    {
        return FMath::Exp2(-FMath::Max(H, 0.f) / Band.Y)
            * (1.f - SmoothStep(0.6f * Band.Z, Band.Z, H))
            * SmoothStep(-Band.W, -0.5f * Band.W, H);
    }

    double Gust(double TimeS, double PeriodS)
    {
        const double P1 = FMath::Max(PeriodS, 0.1);
        const double P2 = P1 * 1.618;
        return 0.65 * FMath::Sin(Tau * TimeS / P1) + 0.35 * FMath::Sin(Tau * TimeS / P2 + 1.7);
    }

    double GustDriftM(double TimeS, double SpeedMps, double Amp, double PeriodS)
    {
        const double P1 = FMath::Max(PeriodS, 0.1);
        const double P2 = P1 * 1.618;
        const double Integral = -0.65 * P1 / Tau * FMath::Cos(Tau * TimeS / P1) - 0.35 * P2 / Tau * FMath::Cos(Tau * TimeS / P2 + 1.7);
        return SpeedMps * (TimeS + Amp * Integral);
    }

    float LayerAlpha(float Sigma, float Storm, float SlabM, float PathK, float N, float GustK, float Prof, float Vis)
    {
        return 1.f - FMath::Exp(-Sigma * Storm * SlabM * PathK * N * GustK * Prof * Vis);
    }

    float StormResponse(float StormIntensity, float Exponent, float Scale)
    {
        return FMath::Pow(FMath::Clamp(StormIntensity, 0.f, 1.f), FMath::Max(Exponent, 0.05f)) * Scale;
    }
}
