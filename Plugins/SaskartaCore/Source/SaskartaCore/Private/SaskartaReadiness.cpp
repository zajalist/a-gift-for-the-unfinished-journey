// USaskartaReadiness (Task L7). See the header for the conditions.

#include "SaskartaReadiness.h"

#include "Components/InstancedStaticMeshComponent.h"
#include "ContentStreaming.h"
#include "Engine/Engine.h"
#include "Engine/World.h"
#include "HAL/PlatformTime.h"
#include "PCGComponent.h"
#include "PipelineStateCache.h"
#include "ShaderCompiler.h"
#include "ShaderPipelineCache.h"
#include "UObject/UObjectIterator.h"
#include "WorldPartition/WorldPartition.h"
#include "WorldPartition/WorldPartitionRuntimeCell.h"
#include "WorldPartition/WorldPartitionStreamingSource.h"
#include "WorldPartition/WorldPartitionSubsystem.h"

namespace SaskartaReadiness
{
    static bool IsStreamingComplete(UWorld* World, const FVector& ViewLocation)
    {
        if (!World->GetWorldPartition())
        {
            return true; // not a World Partition world: nothing streams
        }
        UWorldPartitionSubsystem* WPS = World->GetSubsystem<UWorldPartitionSubsystem>();
        if (!WPS)
        {
            return false;
        }
        // Every registered streaming source (the player) ...
        if (!WPS->IsStreamingCompleted())
        {
            return false;
        }
        // ... and the cells at the title view, which may not be a streaming source yet.
        FWorldPartitionStreamingQuerySource Query;
        Query.Location = ViewLocation;
        Query.bSpatialQuery = true;
        Query.bUseGridLoadingRange = true;
        Query.bDataLayersOnly = false;
        TArray<FWorldPartitionStreamingQuerySource> Queries;
        Queries.Add(Query);
        return WPS->IsStreamingCompleted(EWorldPartitionRuntimeCellState::Activated, Queries, /*bExactState*/ false);
    }

    static bool IsPCGIdle(const UWorld* World)
    {
        for (TObjectIterator<UPCGComponent> It; It; ++It)
        {
            UPCGComponent* PCG = *It;
            if (PCG && PCG->GetWorld() == World && PCG->IsGenerating())
            {
                return false;
            }
        }
        return true;
    }

    // Shader and PSO work still outstanding (Task TITLE, loading screen). Three sources:
    //  - the bundled pipeline cache's precompiles (packaged builds with a PSO cache),
    //  - PSO precache requests (r.PSOPrecaching=1, set by P4),
    //  - the shader compiling manager's outstanding jobs (editor and PIE, where materials compile
    //    on demand; GShaderCompilingManager can be null in a cooked build).
    static int32 PendingPSOs()
    {
        int64 Pending = static_cast<int64>(FShaderPipelineCache::NumPrecompilesRemaining())
            + static_cast<int64>(PipelineStateCache::NumActivePrecacheRequests());
        if (GShaderCompilingManager)
        {
            const int64 Jobs = FMath::Max<int64>(0, GShaderCompilingManager->GetNumRemainingJobs());
            // IsCompiling also covers shader maps waiting to finalize, which have no job count.
            Pending += (Jobs > 0) ? Jobs : (GShaderCompilingManager->IsCompiling() ? 1 : 0);
        }
        return static_cast<int32>(FMath::Min<int64>(Pending, MAX_int32));
    }

    // The texture streamer rarely reaches exactly zero wanting resources in a large open world
    // (distant mips keep trickling in), so a small remainder counts as settled.
    static constexpr int32 TexturesSettledMaxWanting = 16;

    static bool AreTexturesSettled()
    {
        return IStreamingManager::Get().GetNumWantingResources() <= TexturesSettledMaxWanting;
    }

    // Grass stability history per view location. The loading screen polls two views in turn
    // (the road start, then the title camera); one shared history would restart at every switch.
    // File scope because the subsystem's layout cannot change under Live Coding (R40).
    struct FGrassHistory
    {
        TWeakObjectPtr<const UWorld> World;
        FVector Location = FVector::ZeroVector;
        int64 LastCount = -1;
        double LastChangeS = 0.0;
        double LastUsedS = -1.0;
    };
    static FGrassHistory GGrassHistories[4];

    // The last GetReadiness result, for the loading budget's per-second log (task LOADBUDGET).
    static FSaskartaReadinessState GLastPolled;
    static double GLastPolledS = -1.0;
    static constexpr double SameViewCm = 1000.0;

    static FGrassHistory& FindGrassHistory(const UWorld* World, const FVector& Location, double NowS)
    {
        FGrassHistory* Oldest = &GGrassHistories[0];
        for (FGrassHistory& H : GGrassHistories)
        {
            if (H.World.Get() == World && FVector::Dist(H.Location, Location) <= SameViewCm)
            {
                H.LastUsedS = NowS;
                return H;
            }
            if (H.LastUsedS < Oldest->LastUsedS)
            {
                Oldest = &H;
            }
        }
        *Oldest = FGrassHistory();
        Oldest->World = World;
        Oldest->Location = Location;
        Oldest->LastUsedS = NowS;
        return *Oldest;
    }
}

float USaskartaReadiness::ComputeFraction(const FSaskartaReadinessState& R)
{
    int32 Met = 0;
    Met += R.bStreamingComplete ? 1 : 0;
    Met += R.bPCGIdle ? 1 : 0;
    Met += R.PendingPSOs == 0 ? 1 : 0;
    Met += R.bTexturesSettled ? 1 : 0;
    Met += R.bGrassSettled ? 1 : 0;
    return static_cast<float>(Met) / 5.f;
}

FString USaskartaReadiness::DescribeUnmet(const FSaskartaReadinessState& R)
{
    TArray<FString> Unmet;
    if (!R.bStreamingComplete) { Unmet.Add(TEXT("streaming")); }
    if (!R.bPCGIdle) { Unmet.Add(TEXT("pcg")); }
    if (R.PendingPSOs != 0) { Unmet.Add(FString::Printf(TEXT("psos(%d)"), R.PendingPSOs)); }
    if (!R.bTexturesSettled) { Unmet.Add(TEXT("textures")); }
    if (!R.bGrassSettled) { Unmet.Add(TEXT("grass")); }
    return FString::Join(Unmet, TEXT(", "));
}

bool USaskartaReadiness::UpdateStability(int64 Count, double NowS, int64& InOutLastCount, double& InOutLastChangeS, double StableForS)
{
    if (InOutLastCount < 0 || Count != InOutLastCount)
    {
        InOutLastCount = Count;
        InOutLastChangeS = NowS;
        return false;
    }
    return NowS - InOutLastChangeS >= StableForS;
}

int64 USaskartaReadiness::CountInstancesNear(const UWorld* World, const FVector& Location, float RadiusCm)
{
    if (!World)
    {
        return 0;
    }
    const double RadiusSq = static_cast<double>(RadiusCm) * RadiusCm;
    int64 Total = 0;
    // Landscape grass and PCG/foliage instances are all UInstancedStaticMeshComponent subclasses.
    for (TObjectIterator<UInstancedStaticMeshComponent> It; It; ++It)
    {
        const UInstancedStaticMeshComponent* ISM = *It;
        if (!ISM || !ISM->IsRegistered() || ISM->GetWorld() != World)
        {
            continue;
        }
        if (ISM->Bounds.GetBox().ComputeSquaredDistanceToPoint(Location) <= RadiusSq)
        {
            Total += ISM->GetInstanceCount();
        }
    }
    return Total;
}

FSaskartaReadinessState USaskartaReadiness::GetReadiness(const UObject* WorldContext, FVector ViewLocation)
{
    FSaskartaReadinessState R;
    R.PendingPSOs = SaskartaReadiness::PendingPSOs();
    R.bTexturesSettled = SaskartaReadiness::AreTexturesSettled();

    UWorld* World = (GEngine && WorldContext)
        ? GEngine->GetWorldFromContextObject(WorldContext, EGetWorldErrorMode::ReturnNull)
        : nullptr;
    if (World)
    {
        R.bStreamingComplete = SaskartaReadiness::IsStreamingComplete(World, ViewLocation);
        R.bPCGIdle = SaskartaReadiness::IsPCGIdle(World);
        if (World->GetSubsystem<USaskartaReadiness>())
        {
            const double NowS = FPlatformTime::Seconds();
            const int64 Count = CountInstancesNear(World, ViewLocation, GrassRadiusCm);
            SaskartaReadiness::FGrassHistory& H = SaskartaReadiness::FindGrassHistory(World, ViewLocation, NowS);
            R.bGrassSettled = UpdateStability(Count, NowS, H.LastCount, H.LastChangeS, GrassStableS);
        }
    }
    R.Fraction = ComputeFraction(R);
    SaskartaReadiness::GLastPolled = R;
    SaskartaReadiness::GLastPolledS = FPlatformTime::Seconds();
    return R;
}

bool USaskartaReadiness::GetLastPolled(float& OutFraction, FString& OutUnmet, double& OutAgeS)
{
    if (SaskartaReadiness::GLastPolledS < 0.0)
    {
        return false;
    }
    OutFraction = SaskartaReadiness::GLastPolled.Fraction;
    OutUnmet = DescribeUnmet(SaskartaReadiness::GLastPolled);
    OutAgeS = FPlatformTime::Seconds() - SaskartaReadiness::GLastPolledS;
    return true;
}
