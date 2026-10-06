// FSaskartaAmbienceLogic: the ambience director's pure maths (no world, no audio).
//
// Tested by Saskarta.Ambience.* (Private/Tests/SaskartaAmbienceTest.cpp): zone crossfade
// weights, storm wind gains, the dose table and spikes, the Geiger Poisson rate and click/loop
// mix, the no-repeat bag and the voice-budget culling.

#pragma once

#include "CoreMinimal.h"
#include "Math/RandomStream.h"
#include "SaskartaAmbienceAsset.h"

/** A no-repeat shuffle bag over [0, Num): every item once per cycle, never the same twice in a row. */
struct SASKARTACORE_API FSaskartaAmbienceBag
{
    TArray<int32> Remaining;
    int32 Last = INDEX_NONE;
    int32 Size = 0;

    /** The next index; INDEX_NONE when Num <= 0. */
    int32 Next(int32 Num, FRandomStream& Random);
};

/** One voice as the budget sees it. */
struct SASKARTACORE_API FSaskartaVoiceInfo
{
    float Priority = 0.f;
    /** Current linear gain (quieter loses a priority tie). */
    float Volume = 1.f;
    double StartS = 0.0;
};

/** A dose spike: x Multiplier until HoldUntilS, then decays back to x1 with the time constant. */
struct SASKARTACORE_API FSaskartaDoseSpike
{
    FName Cause;
    float Multiplier = 1.f;
    double HoldUntilS = 0.0;
    /** The dose this spike may push to (the gust's 60 cps). */
    float CapCps = 80.f;
};

/** Where the Geiger's clicks and fallback loop sit for a dose. */
struct SASKARTACORE_API FSaskartaGeigerMix
{
    /** Poisson click rate (counts/s); 0 = no clicks. */
    float ClickRate = 0.f;
    /** Gain of the 80 cps loop (0-1). */
    float LoopGain = 0.f;
};

struct SASKARTACORE_API FSaskartaAmbienceLogic
{
    // ------------------------------------------------------------------ constants
    static constexpr float MinClickRateCps = 1.f;
    static constexpr float MaxClickRateCps = 80.f;
    /** Clicks alone below this; the 80 cps loop takes over across [LoopXfadeStart, LoopXfadeEnd]. */
    static constexpr float LoopXfadeStartCps = 30.f;
    static constexpr float LoopXfadeEndCps = 50.f;
    static constexpr float SpikeDecayTauS = 3.f;
    static constexpr float GustMinIntensity = 0.15f;

    static float DbToLin(float Db) { return FMath::Pow(10.f, Db / 20.f); }

    // ------------------------------------------------------------------ zones
    /**
     * A zone's weight at RoadM: a trapezoid, ramping in over XfadeInM centred on FromM (sin^2) and out
     * over XfadeOutM centred on ToM (cos^2). The first zone has no ramp in and the last no ramp out,
     * so the road ends stay at full level. Neighbours sharing a boundary and its width sum to 1.
     */
    static float ZoneWeight(float RoadM, float FromM, float ToM, float XfadeInM, float XfadeOutM, bool bFirst, bool bLast);

    /**
     * ZoneWeight for every zone (sorted by FromM). A boundary uses the incoming zone's XfadeM
     * on both sides (Climb -> Cloud crossfades over the Cloud's 120 m), so neighbours sum to 1.
     */
    static void ZoneWeights(const TArray<FSaskartaAmbienceZone>& Zones, float RoadM, TArray<float>& OutWeights);

    /** The index of the heaviest zone (INDEX_NONE if none). */
    static int32 DominantZone(const TArray<float>& Weights);

    /** The zone-weighted sum of a per-zone value (e.g. WindMultiplier); Fallback when the weights are all 0. */
    static float WeightedZoneValue(const TArray<FSaskartaAmbienceZone>& Zones, const TArray<float>& Weights,
        float FSaskartaAmbienceZone::* Field, float Fallback);

    // ------------------------------------------------------------------ storm
    /**
     * The three wind beds' linear gains at storm intensity I (X breeze, Y strong, Z gale):
     * breeze 1 up to 0.15, cos^2 to 0 at 0.5; strong sin^2 up 0.15-0.5, cos^2 down 0.5-0.9;
     * gale sin^2 up 0.5-0.9.
     */
    static FVector StormWindGains(float I);

    static float StormFactor(ESaskartaBedStormMode Mode, float StormRef, float I);

    /** A bed's linear gain at RoadM and I: its dB, the storm factor, the extra range and the cutoff. */
    static float BedGain(const FSaskartaAmbienceBed& Bed, float RoadM, float I);

    /** Seconds to the next gust: lerp(90, 20, I) +- 30 % (Rand01 picks); negative when I < 0.15 (no gusts). */
    static float GustIntervalS(float I, float Rand01);

    // ------------------------------------------------------------------ Geiger
    /** The table's dose at RoadM (linear between points, clamped at the ends; 0 when empty). */
    static float DoseAtRoadM(const TArray<FVector2D>& SortedPoints, float RoadM);

    /** One spike's multiplier at NowS (hold, then exp decay with SpikeDecayTauS). */
    static float SpikeMultiplier(const FSaskartaDoseSpike& Spike, double NowS);

    /** RoadDose x the strongest live spike, capped by that spike's cap (and MaxClickRateCps). */
    static float ComposeDose(float RoadDose, const TArray<FSaskartaDoseSpike>& Spikes, double NowS);

    /** The Poisson click rate for a dose: clamped to [MinRate, MaxRate]; 0 when Dose <= 0. */
    static float PoissonRate(float Dose, float MinRate = MinClickRateCps, float MaxRate = MaxClickRateCps);

    /** Poisson inter-arrival: -ln(U) / Rate (U in (0, 1]); a large value when Rate <= 0. */
    static float PoissonIntervalS(float Rate, float U);

    /** Clicks up to 30 cps, crossfading into the 80 cps loop (gain Dose / 80) by 50 cps. */
    static FSaskartaGeigerMix GeigerMix(float Dose, float MinRate = MinClickRateCps);

    /**
     * The fallback when there are no click sounds: the gains of the rate loops (sorted rates),
     * crossfaded between the two neighbours by log(Dose). OutGains has one entry per rate.
     */
    static void GeigerLoopWeights(const TArray<float>& SortedRates, float Dose, TArray<float>& OutGains);

    /** True when the dose rises through Threshold and the last chirp is at least CooldownS old. */
    static bool ShouldChirp(float PrevDose, float Dose, float Threshold, double NowS, double LastChirpS, float CooldownS);

    // ------------------------------------------------------------------ voices
    /**
     * The voice budget. Active holds the voices now playing; the candidate wants to start.
     * Returns the index in Active to cull to make room, or INDEX_NONE when there is room
     * (Active.Num() < Budget) or when the candidate itself is the lowest (bOutRejectCandidate).
     * Lowest = lowest priority, then quietest, then oldest.
     */
    static int32 PickVoiceToCull(const TArray<FSaskartaVoiceInfo>& Active, const FSaskartaVoiceInfo& Candidate,
        int32 Budget, bool& bOutRejectCandidate);

    /** True when A should be culled before B. */
    static bool IsLowerVoice(const FSaskartaVoiceInfo& A, const FSaskartaVoiceInfo& B);

    // ------------------------------------------------------------------ placement
    /** A point MinM-MaxM (metres) from Origin (cm) within +-ArcDeg of Forward, HeightM up. */
    static FVector PointAround(const FVector& Origin, const FVector& Forward, float MinM, float MaxM, float ArcDeg,
        float HeightM, float RandDist01, float RandAngle01);

    /** The pool's next-fire delay (uniform in [Min, Max]); negative when the pool is event-driven. */
    static float PoolIntervalS(float MinS, float MaxS, float Rand01);
};
