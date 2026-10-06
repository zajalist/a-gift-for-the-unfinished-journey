// USaskartaReadiness: is the world ready to reveal the title without pop-in? (Task L7)
//
// Spec: docs/superpowers/specs/2026-09-26-saskarta-world-sprint-design.md, section 6
// ("Readiness gate"). The intro widget polls GetReadiness every 0.25 s during the loading
// hold (at least 6 s, at most 25 s; on timeout it proceeds and logs the failed conditions).
//
//   bStreamingComplete  World Partition streaming complete at the view (and for all sources)
//   bPCGIdle            no PCG component in the world is generating
//   PendingPSOs         PSO precompiles remaining (pipeline cache + PSO precache requests)
//   bTexturesSettled    the texture streamer has no wanting resources
//   bGrassSettled       instance counts near the view unchanged for 1 s
//   Fraction            the share of the five conditions met (PendingPSOs == 0 counts as met)
//
// A world subsystem only to keep the grass history between polls; GetReadiness is static.

#pragma once

#include "CoreMinimal.h"
#include "Subsystems/WorldSubsystem.h"
#include "SaskartaReadiness.generated.h"

USTRUCT(BlueprintType)
struct SASKARTACORE_API FSaskartaReadinessState
{
    GENERATED_BODY()

    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Readiness")
    bool bStreamingComplete = false;

    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Readiness")
    bool bPCGIdle = false;

    /** -1 until GetReadiness fills it. */
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Readiness")
    int32 PendingPSOs = -1;

    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Readiness")
    bool bTexturesSettled = false;

    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Readiness")
    bool bGrassSettled = false;

    /** 0..1; -1 until GetReadiness fills it. */
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Readiness")
    float Fraction = -1.f;
};

UCLASS()
class SASKARTACORE_API USaskartaReadiness : public UWorldSubsystem
{
    GENERATED_BODY()

public:
    /** Instances are counted within this distance of the view. */
    static constexpr float GrassRadiusCm = 20000.f;
    /** Counts must stay unchanged this long to be settled. */
    static constexpr double GrassStableS = 1.0;

    /** Checks every readiness condition at ViewLocation (the title camera). */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Readiness", meta = (WorldContext = "WorldContext"))
    static FSaskartaReadinessState GetReadiness(const UObject* WorldContext, FVector ViewLocation);

    /** The share of the five conditions met, 0..1. */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Readiness")
    static float ComputeFraction(const FSaskartaReadinessState& Readiness);

    /** Names of the unmet conditions, for the timeout log. */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Readiness")
    static FString DescribeUnmet(const FSaskartaReadinessState& Readiness);

    /**
     * One stability sample: true once Count has not changed for StableForS seconds.
     * InOutLastCount < 0 means no sample yet. Updates the history.
     */
    static bool UpdateStability(int64 Count, double NowS, int64& InOutLastCount, double& InOutLastChangeS, double StableForS);

    /**
     * The last GetReadiness result (task LOADBUDGET's per-second log): false before the first poll.
     * OutAgeS = seconds since that poll.
     */
    static bool GetLastPolled(float& OutFraction, FString& OutUnmet, double& OutAgeS);

    /** Instanced-mesh instances (landscape grass, PCG and foliage) within RadiusCm of Location. */
    static int64 CountInstancesNear(const UWorld* World, const FVector& Location, float RadiusCm);

private:
    int64 LastGrassCount = -1;
    double LastGrassChangeS = 0.0;
};
