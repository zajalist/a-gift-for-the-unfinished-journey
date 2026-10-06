#pragma once

#include "CoreMinimal.h"
#include "Subsystems/WorldSubsystem.h"
#include "SaskartaGameplayStreamingBudget.generated.h"

class IConsoleVariable;

/** A temporary streaming slice during interactive Carrier play and the elder walk. No quality/GC policy changes. */
UCLASS()
class SASKARTACORE_API USaskartaGameplayStreamingBudget : public UWorldSubsystem
{
    GENERATED_BODY()

public:
    virtual void Initialize(FSubsystemCollectionBase& Collection) override;
    virtual void PreDeinitialize() override;
    virtual void Deinitialize() override;
    virtual void OnWorldEndPlay(UWorld& InWorld) override;

protected:
    virtual bool DoesSupportWorldType(const EWorldType::Type WorldType) const override;

private:
    struct FOwnedCVar
    {
        FString Name;
        IConsoleVariable* Variable = nullptr;
        FString Original;
        FString Applied;
        uint32 OriginalSetBy = 0;
        uint32 AppliedSetBy = 0;
        FName OriginalTag;
        FDelegateHandle ChangedHandle;
    };

    bool CanApply() const;
    void OnEndFrame();
    void OnWorldCleanup(UWorld* World, bool bSessionEnded, bool bCleanupResources);
    void OnWorldTickStart(UWorld* World, ELevelTick TickType, float DeltaSeconds);
    void OnCVarChanged(IConsoleVariable* Variable);
    void OnPreGarbageCollect();
    void ApplyBudget();
    void ReleaseBudget(const TCHAR* Reason);
    void LogSnapshot(const TCHAR* Reason);

    TArray<FOwnedCVar> Owned;
    FName OwnerTag;
    FDelegateHandle EndFrameHandle;
    FDelegateHandle CleanupHandle;
    FDelegateHandle WorldTickHandle;
    FDelegateHandle PreGCHandle;
    bool bApplying = false;
    bool bActive = false;
    bool bStopped = false;
    bool bCompetingWriter = false;
    bool bRelinquished = false;
    double LastSnapshotS = -1.0;
};
