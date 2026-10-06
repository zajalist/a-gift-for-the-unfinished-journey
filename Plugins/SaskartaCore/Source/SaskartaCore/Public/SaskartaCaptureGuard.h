// Capture guard (task CAPTURE-CPP): scene captures that only feed the loading screen render only
// while the loading screen is up, editor leftovers never render, and every other capture that
// renders every frame is reported once.
//
// Why: KeeperPointCloud_Capture (Tools/Look/build_keeper_pointcloud.py; the Keeper point cloud on
// WBP_Saskarta_Loading) is authored with bCaptureEveryFrame on and is not spatially loaded, so it
// rendered its show-only traveller into RT_Saskarta_LoadingTraveller every frame for the whole game
// (0.5-1.5 ms). Look_TempCapture_0/1 and HaybaMCPCaptureActor are leftovers from editor captures.
//
// Roles, phases and rules: SaskartaCaptureGuardLogic.h (the pure part, covered by the
// Saskarta.CaptureGuard automation tests).
//
// Loading-only renders also require a visible TravellerPointCloud image in the loading widget,
// or an explicit loading hold. A logo-only loading screen must not render the offstage scene.
// Loading signal (any of):
//   - USaskartaLoadingBudget::IsLoadingBudgetActive(): USaskartaPerfGovernor::SetSuspended("Loading")
//     (PC_Saskarta.BeginIntro sets it, BeginTitle clears it) begins/ends the loading budget; the
//     governor keeps its reasons private, so the budget is the public read of that same reason;
//   - a WBP_Saskarta_Loading widget in the viewport of this world (it removes itself after its
//     FadeOut, so this covers the fade; it also works with saskarta.loadbudget.Enable 0);
//   - an explicit hold: SetLoadingHold(Reason, true) (for any other loading screen).
//
// Runtime only (Game and PIE worlds; the editor world and the saved level are never changed). No
// Tick: a core ticker polls every saskarta.captureguard.PollS (0.5 s, real time, runs while paused).
// A poll reads the loading signal and lists the scene capture components of this world (the
// object hash, a handful of objects); commands are applied only when a capture is first seen or
// the phase changes, so a Blueprint that switches a capture itself is not fought every poll.
//
// CVars: saskarta.captureguard.Enable (1; 0 turns back on every capture the guard switched off and
// stops), .LingerS (1.5), .StartGraceS (8), .PollS (0.5), .Audit (1), .ExtraStrays (comma-separated
// name prefixes). Console: saskarta.captureguard.Dump lists every capture of the world and its role.

#pragma once

#include "CoreMinimal.h"
#include "Containers/Ticker.h"
#include "SaskartaCaptureGuardLogic.h"
#include "Subsystems/WorldSubsystem.h"
#include "UObject/ObjectKey.h"

#include "SaskartaCaptureGuard.generated.h"

class USceneCaptureComponent;
class UUserWidget;

UCLASS()
class SASKARTACORE_API USaskartaCaptureGuard : public UWorldSubsystem
{
    GENERATED_BODY()

public:
    virtual bool DoesSupportWorldType(const EWorldType::Type WorldType) const override;
    virtual void Initialize(FSubsystemCollectionBase& Collection) override;
    virtual void Deinitialize() override;
    virtual void OnWorldBeginPlay(UWorld& InWorld) override;

    UFUNCTION(BlueprintPure, Category = "Saskarta|Performance", meta = (WorldContext = "WorldContext"))
    static USaskartaCaptureGuard* GetCaptureGuard(const UObject* WorldContext);

    /**
     * Keeps the loading window open for Reason (another loading screen than the start sequence's),
     * so the loading-only captures render. Clear it with bHold false when that screen goes away.
     */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Performance")
    void SetLoadingHold(FName Reason, bool bHold);

    /** True while loading captures have a visible consumer or explicit hold and are in a loading phase. */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Performance")
    bool AreLoadingCapturesOn() const;

    /** One line: the phase, the loading signals, and the capture counts per role. */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Performance")
    FString DescribeState() const;

    /** Polls now (the loading signal and the capture list) instead of waiting for the next poll. */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Performance")
    void Refresh();

    /** Logs every scene capture of this world with its role and state (saskarta.captureguard.Dump). */
    void DumpCaptures() const;

private:
    struct FTracked
    {
        TWeakObjectPtr<USceneCaptureComponent> Component;
        ESaskartaCaptureRole Role = ESaskartaCaptureRole::Unmanaged;
        /** The last command the guard applied (Leave = never touched). */
        ESaskartaCaptureCommand Applied = ESaskartaCaptureCommand::Leave;
        /** As authored when first seen, restored by On and by Enable 0. */
        bool bOrigEveryFrame = false;
        bool bOrigOnMovement = false;
        bool bOrigActive = false;
        /** The audit warning was logged. */
        bool bWarned = false;
        FString Label;
    };

    bool OnTicker(float DeltaTime);
    void Poll();
    bool IsLoadingSignal(FString* OutWhy = nullptr) const;
    bool IsLoadingWidgetShown() const;
    bool HasLoadingCaptureConsumer() const;
    void ScanCaptures(bool bApplyAll);
    void ApplyCommand(FTracked& T, USceneCaptureComponent& C, ESaskartaCaptureCommand Command);
    void RestoreAll(const TCHAR* Why);
    static FSaskartaCaptureIdentity MakeIdentity(const USceneCaptureComponent& C);
    static FString DescribeCapture(const USceneCaptureComponent& C);
    void ArmTicker();

    FSaskartaLoadingPhaseTracker Tracker;
    TMap<FObjectKey, FTracked> Tracked;
    TSet<FName> Holds;
    FTSTicker::FDelegateHandle TickerHandle;
    float TickerPollS = 0.f;
    mutable TWeakObjectPtr<UClass> LoadingWidgetClass;
    bool bBegunPlay = false;
    bool bDisabled = false;
};
