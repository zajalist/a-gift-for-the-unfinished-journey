// FSaskartaAmbienceLogic and the asset lookups. See SaskartaAmbienceLogic.h / SaskartaAmbienceAsset.h.

#include "SaskartaAmbienceLogic.h"
#include "SaskartaAmbienceAsset.h"

// ============================================================================ asset lookups

int32 USaskartaAmbienceAsset::FindPoolIndex(FName Name) const
{
    return Pools.IndexOfByPredicate([Name](const FSaskartaAmbiencePool& P) { return P.Name == Name; });
}

int32 USaskartaAmbienceAsset::FindSpotIndex(FName Label) const
{
    return Spots.IndexOfByPredicate([Label](const FSaskartaAmbienceSpot& S) { return S.Label == Label; });
}

const FSaskartaAmbiencePool* USaskartaAmbienceAsset::FindPool(FName Name) const
{
    const int32 I = FindPoolIndex(Name);
    return Pools.IsValidIndex(I) ? &Pools[I] : nullptr;
}

const FSaskartaAmbienceSpot* USaskartaAmbienceAsset::FindSpot(FName Label) const
{
    const int32 I = FindSpotIndex(Label);
    return Spots.IsValidIndex(I) ? &Spots[I] : nullptr;
}

// ============================================================================ shuffle bag

int32 FSaskartaAmbienceBag::Next(int32 Num, FRandomStream& Random)
{
    if (Num <= 0)
    {
        return INDEX_NONE;
    }
    if (Num == 1)
    {
        Last = 0;
        return 0;
    }
    if (Size != Num)
    {
        // The pool changed size: start a fresh cycle (Last still guards the repeat).
        Remaining.Reset();
        Size = Num;
    }
    if (Remaining.Num() == 0)
    {
        for (int32 i = 0; i < Num; ++i)
        {
            Remaining.Add(i);
        }
        // Fisher-Yates.
        for (int32 i = Num - 1; i > 0; --i)
        {
            const int32 j = Random.RandRange(0, i);
            Remaining.Swap(i, j);
        }
        // The new cycle's first draw (the array's end) must not repeat the last one.
        if (Remaining.Last() == Last)
        {
            Remaining.Swap(Remaining.Num() - 1, Random.RandRange(0, Remaining.Num() - 2));
        }
    }
    Last = Remaining.Pop(EAllowShrinking::No);
    return Last;
}

// ============================================================================ zones

namespace SaskartaAmbienceLogicPrivate
{
    static float Sin2(float T) { const float S = FMath::Sin(T * HALF_PI); return S * S; }
    static float Cos2(float T) { const float C = FMath::Cos(T * HALF_PI); return C * C; }
    static float Ramp(float X, float A, float B) { return B > A ? FMath::Clamp((X - A) / (B - A), 0.f, 1.f) : (X >= B ? 1.f : 0.f); }
}

float FSaskartaAmbienceLogic::ZoneWeight(float RoadM, float FromM, float ToM, float XfadeInM, float XfadeOutM, bool bFirst, bool bLast)
{
    using namespace SaskartaAmbienceLogicPrivate;
    float W = 1.f;
    if (!bFirst)
    {
        const float H = FMath::Max(XfadeInM, 0.f) * 0.5f;
        W *= Sin2(Ramp(RoadM, FromM - H, FromM + H));
    }
    if (!bLast)
    {
        const float H = FMath::Max(XfadeOutM, 0.f) * 0.5f;
        W *= Cos2(Ramp(RoadM, ToM - H, ToM + H));
    }
    return W;
}

void FSaskartaAmbienceLogic::ZoneWeights(const TArray<FSaskartaAmbienceZone>& Zones, float RoadM, TArray<float>& OutWeights)
{
    const int32 N = Zones.Num();
    OutWeights.SetNumZeroed(N);
    for (int32 i = 0; i < N; ++i)
    {
        const FSaskartaAmbienceZone& Z = Zones[i];
        const float OutW = (i + 1 < N) ? Zones[i + 1].XfadeM : Z.XfadeM;
        OutWeights[i] = ZoneWeight(RoadM, Z.FromM, Z.ToM, Z.XfadeM, OutW, i == 0, i == N - 1);
    }
}

int32 FSaskartaAmbienceLogic::DominantZone(const TArray<float>& Weights)
{
    int32 Best = INDEX_NONE;
    float BestW = 0.f;
    for (int32 i = 0; i < Weights.Num(); ++i)
    {
        if (Weights[i] > BestW)
        {
            BestW = Weights[i];
            Best = i;
        }
    }
    return Best;
}

float FSaskartaAmbienceLogic::WeightedZoneValue(const TArray<FSaskartaAmbienceZone>& Zones, const TArray<float>& Weights,
    float FSaskartaAmbienceZone::* Field, float Fallback)
{
    float Sum = 0.f;
    float WSum = 0.f;
    for (int32 i = 0; i < Zones.Num() && i < Weights.Num(); ++i)
    {
        Sum += Weights[i] * (Zones[i].*Field);
        WSum += Weights[i];
    }
    return WSum > KINDA_SMALL_NUMBER ? Sum / WSum : Fallback;
}

// ============================================================================ storm

FVector FSaskartaAmbienceLogic::StormWindGains(float I)
{
    using namespace SaskartaAmbienceLogicPrivate;
    I = FMath::Clamp(I, 0.f, 1.f);
    const float Breeze = Cos2(Ramp(I, 0.15f, 0.5f));
    const float Strong = Sin2(Ramp(I, 0.15f, 0.5f)) * Cos2(Ramp(I, 0.5f, 0.9f));
    const float Gale = Sin2(Ramp(I, 0.5f, 0.9f));
    return FVector(Breeze, Strong, Gale);
}

float FSaskartaAmbienceLogic::StormFactor(ESaskartaBedStormMode Mode, float StormRef, float I)
{
    I = FMath::Clamp(I, 0.f, 1.f);
    switch (Mode)
    {
    case ESaskartaBedStormMode::Linear: return I;
    case ESaskartaBedStormMode::Squared: return I * I;
    case ESaskartaBedStormMode::AboveHalf: return FMath::Clamp((I - 0.5f) * 2.f, 0.f, 1.f);
    case ESaskartaBedStormMode::InverseToRef: return StormRef > KINDA_SMALL_NUMBER ? FMath::Clamp(1.f - I / StormRef, 0.f, 1.f) : 0.f;
    default: return 1.f;
    }
}

float FSaskartaAmbienceLogic::BedGain(const FSaskartaAmbienceBed& Bed, float RoadM, float I)
{
    if (Bed.OffAfterRoadM >= 0.f && RoadM > Bed.OffAfterRoadM)
    {
        return 0.f;
    }
    float Db = Bed.VolumeDb;
    if (Bed.ExtraFromM >= 0.f && Bed.ExtraToM > Bed.ExtraFromM && RoadM >= Bed.ExtraFromM && RoadM <= Bed.ExtraToM)
    {
        Db += Bed.ExtraDb;
    }
    return DbToLin(Db) * StormFactor(Bed.StormMode, Bed.StormRef, I);
}

float FSaskartaAmbienceLogic::GustIntervalS(float I, float Rand01)
{
    if (I < GustMinIntensity)
    {
        return -1.f;
    }
    const float Base = FMath::Lerp(90.f, 20.f, FMath::Clamp(I, 0.f, 1.f));
    const float Jitter = 1.f + (FMath::Clamp(Rand01, 0.f, 1.f) * 2.f - 1.f) * 0.3f;
    return Base * Jitter;
}

// ============================================================================ Geiger

float FSaskartaAmbienceLogic::DoseAtRoadM(const TArray<FVector2D>& P, float RoadM)
{
    if (P.Num() == 0)
    {
        return 0.f;
    }
    if (RoadM <= P[0].X)
    {
        return P[0].Y;
    }
    for (int32 i = 1; i < P.Num(); ++i)
    {
        if (RoadM <= P[i].X)
        {
            const double Span = P[i].X - P[i - 1].X;
            const double T = Span > 0.0 ? (RoadM - P[i - 1].X) / Span : 1.0;
            return static_cast<float>(FMath::Lerp(P[i - 1].Y, P[i].Y, T));
        }
    }
    return P.Last().Y;
}

float FSaskartaAmbienceLogic::SpikeMultiplier(const FSaskartaDoseSpike& Spike, double NowS)
{
    if (NowS <= Spike.HoldUntilS)
    {
        return Spike.Multiplier;
    }
    const double Decay = FMath::Exp(-(NowS - Spike.HoldUntilS) / SpikeDecayTauS);
    return 1.f + (Spike.Multiplier - 1.f) * static_cast<float>(Decay);
}

float FSaskartaAmbienceLogic::ComposeDose(float RoadDose, const TArray<FSaskartaDoseSpike>& Spikes, double NowS)
{
    float BestMult = 1.f;
    float Cap = MaxClickRateCps;
    for (const FSaskartaDoseSpike& S : Spikes)
    {
        const float M = SpikeMultiplier(S, NowS);
        if (M > BestMult)
        {
            BestMult = M;
            Cap = FMath::Min(S.CapCps, MaxClickRateCps);
        }
    }
    const float Dose = FMath::Max(RoadDose, 0.f) * BestMult;
    // A spike never lowers the road's own dose below itself, even past its cap.
    return FMath::Min(Dose, FMath::Max(Cap, FMath::Max(RoadDose, 0.f)));
}

float FSaskartaAmbienceLogic::PoissonRate(float Dose, float MinRate, float MaxRate)
{
    if (Dose <= 0.f)
    {
        return 0.f;
    }
    return FMath::Clamp(Dose, MinRate, MaxRate);
}

float FSaskartaAmbienceLogic::PoissonIntervalS(float Rate, float U)
{
    if (Rate <= 0.f)
    {
        return 1.0e6f;
    }
    U = FMath::Clamp(U, 1.0e-6f, 1.f);
    return -FMath::Loge(U) / Rate;
}

FSaskartaGeigerMix FSaskartaAmbienceLogic::GeigerMix(float Dose, float MinRate)
{
    FSaskartaGeigerMix M;
    if (Dose <= 0.f)
    {
        return M;
    }
    const float Rate = PoissonRate(Dose, MinRate, MaxClickRateCps);
    const float W = SaskartaAmbienceLogicPrivate::Ramp(Dose, LoopXfadeStartCps, LoopXfadeEndCps);
    M.ClickRate = Rate * (1.f - W);
    M.LoopGain = W * FMath::Clamp(Dose / MaxClickRateCps, 0.f, 1.f);
    return M;
}

void FSaskartaAmbienceLogic::GeigerLoopWeights(const TArray<float>& Rates, float Dose, TArray<float>& OutGains)
{
    OutGains.SetNumZeroed(Rates.Num());
    if (Rates.Num() == 0 || Dose <= 0.f)
    {
        return;
    }
    if (Dose <= Rates[0])
    {
        // Below the slowest loop: fade it with the dose.
        OutGains[0] = FMath::Clamp(Dose / Rates[0], 0.f, 1.f);
        return;
    }
    if (Dose >= Rates.Last())
    {
        OutGains.Last() = 1.f;
        return;
    }
    for (int32 i = 1; i < Rates.Num(); ++i)
    {
        if (Dose <= Rates[i])
        {
            const float T = FMath::Clamp((FMath::Loge(Dose) - FMath::Loge(Rates[i - 1])) / (FMath::Loge(Rates[i]) - FMath::Loge(Rates[i - 1])), 0.f, 1.f);
            // Equal power.
            OutGains[i - 1] = FMath::Cos(T * HALF_PI);
            OutGains[i] = FMath::Sin(T * HALF_PI);
            return;
        }
    }
}

bool FSaskartaAmbienceLogic::ShouldChirp(float PrevDose, float Dose, float Threshold, double NowS, double LastChirpS, float CooldownS)
{
    return PrevDose < Threshold && Dose >= Threshold && (NowS - LastChirpS) >= CooldownS;
}

// ============================================================================ voices

bool FSaskartaAmbienceLogic::IsLowerVoice(const FSaskartaVoiceInfo& A, const FSaskartaVoiceInfo& B)
{
    if (A.Priority != B.Priority)
    {
        return A.Priority < B.Priority;
    }
    if (!FMath::IsNearlyEqual(A.Volume, B.Volume, 1.0e-4f))
    {
        return A.Volume < B.Volume;
    }
    return A.StartS < B.StartS;
}

int32 FSaskartaAmbienceLogic::PickVoiceToCull(const TArray<FSaskartaVoiceInfo>& Active, const FSaskartaVoiceInfo& Candidate,
    int32 Budget, bool& bOutRejectCandidate)
{
    bOutRejectCandidate = false;
    if (Budget <= 0)
    {
        bOutRejectCandidate = true;
        return INDEX_NONE;
    }
    if (Active.Num() < Budget)
    {
        return INDEX_NONE;
    }
    int32 Lowest = INDEX_NONE;
    for (int32 i = 0; i < Active.Num(); ++i)
    {
        if (Lowest == INDEX_NONE || IsLowerVoice(Active[i], Active[Lowest]))
        {
            Lowest = i;
        }
    }
    // The candidate is newest, so on a full tie it is not the "older" one: an equal voice already
    // playing is culled only when strictly lower by priority or volume.
    if (Lowest == INDEX_NONE
        || Candidate.Priority < Active[Lowest].Priority
        || (Candidate.Priority == Active[Lowest].Priority && Candidate.Volume <= Active[Lowest].Volume))
    {
        bOutRejectCandidate = true;
        return INDEX_NONE;
    }
    return Lowest;
}

// ============================================================================ placement

FVector FSaskartaAmbienceLogic::PointAround(const FVector& Origin, const FVector& Forward, float MinM, float MaxM, float ArcDeg,
    float HeightM, float RandDist01, float RandAngle01)
{
    FVector F = Forward;
    F.Z = 0.f;
    if (!F.Normalize())
    {
        F = FVector::ForwardVector;
    }
    const float Dist = FMath::Lerp(MinM, FMath::Max(MinM, MaxM), FMath::Clamp(RandDist01, 0.f, 1.f)) * 100.f;
    const float Arc = FMath::Clamp(ArcDeg, 0.f, 180.f);
    const float Yaw = (FMath::Clamp(RandAngle01, 0.f, 1.f) * 2.f - 1.f) * Arc;
    const FVector Dir = F.RotateAngleAxis(Yaw, FVector::UpVector);
    return Origin + Dir * Dist + FVector(0.f, 0.f, HeightM * 100.f);
}

float FSaskartaAmbienceLogic::PoolIntervalS(float MinS, float MaxS, float Rand01)
{
    if (MinS <= 0.f && MaxS <= 0.f)
    {
        return -1.f;
    }
    const float Lo = FMath::Max(0.1f, FMath::Min(MinS, MaxS));
    const float Hi = FMath::Max(Lo, FMath::Max(MinS, MaxS));
    return FMath::Lerp(Lo, Hi, FMath::Clamp(Rand01, 0.f, 1.f));
}
