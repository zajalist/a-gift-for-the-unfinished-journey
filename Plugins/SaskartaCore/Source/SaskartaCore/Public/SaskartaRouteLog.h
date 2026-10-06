#pragma once

#include "CoreMinimal.h"
#include "InputCoreTypes.h"
#include "Engine/DataAsset.h"
#include "Subsystems/WorldSubsystem.h"
#include "SaskartaRouteLog.generated.h"

/** Kept so existing cooked data assets remain loadable; no gameplay consumes this legacy data. */
UCLASS(BlueprintType)
class SASKARTACORE_API USaskartaRouteBoardAsset : public UPrimaryDataAsset
{
    GENERATED_BODY()
public:
    static const TCHAR* AssetPath;
    UPROPERTY(EditAnywhere, Category = "Saskarta|Legacy", meta = (MultiLine = true))
    FString Json;
#if WITH_EDITOR
    UFUNCTION(CallInEditor, Category = "Saskarta|Legacy")
    void ReimportFromDocs();
#endif
};

/** Tab/View at a recharge stop opens the shared motor rhythm/balance activity. */
UCLASS()
class SASKARTACORE_API USaskartaRouteLog : public UWorldSubsystem
{
    GENERATED_BODY()
public:
    virtual bool ShouldCreateSubsystem(UObject* Outer) const override;
    virtual void Initialize(FSubsystemCollectionBase& Collection) override;
    virtual void OnWorldBeginPlay(UWorld& InWorld) override;
    virtual void Deinitialize() override;

    UFUNCTION(BlueprintCallable, Category = "Saskarta|Motor")
    void SetOpen(bool bInOpen);
    UFUNCTION(BlueprintPure, Category = "Saskarta|Motor")
    bool IsOpen() const;
    UFUNCTION(BlueprintPure, Category = "Saskarta|Motor")
    bool CanOpen() const;
    UFUNCTION(BlueprintPure, Category = "Saskarta|Motor")
    int32 GetOpenCount() const { return OpenCount; }

    // Inert compatibility for existing Blueprints/checkpoints. No evidence is tracked or displayed.
    UFUNCTION(BlueprintPure, Category = "Saskarta|Legacy")
    TArray<FString> GetReportLines() const { return {}; }
    UFUNCTION(BlueprintPure, Category = "Saskarta|Legacy")
    int32 GetWordsToPlace() const { return 0; }
    UFUNCTION(BlueprintPure, Category = "Saskarta|Legacy")
    int32 GetHeardWords() const { return 0; }
    UFUNCTION(BlueprintPure, Category = "Saskarta|Legacy")
    bool NeedsFirstSurvey() const { return false; }
    bool IsListening() const { return false; }
    bool RewriteArrival(FString&, FString&, float&) { return false; }
    FString MapLabelForResult(const FString&) const { return {}; }
    FString NamesLine() const { return {}; }
    FString DumpState() const;

private:
    void PollKeys();
    int32 OpenCount = 0;
    FTimerHandle KeyTimer;
    TMap<FKey, bool> KeyWasDown;
    float PendingOpenS = 0.f;   // Tab pressed while still rolling: open as soon as the carrier stops
};
