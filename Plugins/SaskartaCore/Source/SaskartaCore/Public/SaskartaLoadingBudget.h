// Loading budget (task LOADBUDGET): while the start sequence's loading screen is up, the world
// streams in behind it in small, steady slices instead of big bursts, so the loading UI keeps a
// steady frame. Loading takes longer; nothing hitches.
//
// FSaskartaLoadBudgetCore is the pure part (no engine calls; the automation tests drive it with a
// fake CVar store): owner ref counting, save on the first Begin, restore on the last End.
// USaskartaLoadingBudget is the game-instance subsystem that applies it to the real CVars.
//
// Hook: USaskartaPerfGovernor::SetSuspended("Loading", true/false) (PC_Saskarta.BeginIntro /
// BeginTitle) calls Begin/End("Loading"), so no Blueprint change is needed. Begin/End are also
// BlueprintCallable for explicit use with any other owner name.
//
// Rules:
//   - Owners are a set: Begin twice with the same owner counts once; the budget stays on until
//     every owner has ended. The CVars are saved on the first Begin and restored on the last End.
//   - A restore only writes the saved value back when the CVar still holds the value the budget
//     wrote; if something else (the settings menu, GameUserSettings) changed it meanwhile, that
//     newer value is kept.
//   - Writes use the CVar's current SetBy priority, raised to SetByScalability when the CVar still has
//     its constructor priority (SetWithCurrentPriority refuses those), so the settings class and
//     scalability can still write it afterwards.
//   - World teardown and Deinitialize restore everything (ForceRestore), whatever the owners.
//   - On the last End: one GC with incremental purge (saskarta.loadbudget.GCAtEnd; 2 = the old full
//     blocking GC), so the first gameplay seconds do not hit the GC that was held back during loading.
//
// See Tools/GameFlow/specs/README_LoadingBudget.md for the CVar table.

#pragma once

#include "CoreMinimal.h"
#include "Subsystems/GameInstanceSubsystem.h"
#include "SaskartaLoadingBudget.generated.h"

class UGameViewportClient;
class UUserWidget;

/** Where the core reads and writes CVars; the engine side uses IConsoleManager, the tests a map. */
class ISaskartaCVarAccess
{
public:
    virtual ~ISaskartaCVarAccess() = default;
    /** False when the CVar does not exist. */
    virtual bool Read(const FString& Name, FString& OutValue) const = 0;
    virtual void Write(const FString& Name, const FString& Value) = 0;
};

/** The pure loading-budget state machine. */
struct SASKARTACORE_API FSaskartaLoadBudgetCore
{
    enum class EOp : uint8
    {
        /** Write Value. */
        Set,
        /** A limit where <= 0 means unlimited: write min(current, Value), never raise it. */
        Cap,
        /** Write max(current, Value), never lower it. */
        AtLeast,
    };

    struct FSetting
    {
        FString Name;
        float Value = 0.f;
        EOp Op = EOp::Set;
    };

    /** One CVar the budget changed. */
    struct FSaved
    {
        FString Name;
        FString Original;
        FString Applied;
    };

    /**
     * Adds Owner. On the first owner, saves and applies Settings (unknown CVars are skipped)
     * and returns true. A repeated Owner or a later owner changes nothing and returns false.
     */
    bool Begin(FName Owner, const TArray<FSetting>& Settings, ISaskartaCVarAccess& CVars);

    /** Removes Owner. When it was the last one, restores and returns true. Unknown owner: false. */
    bool End(FName Owner, ISaskartaCVarAccess& CVars);

    /** Restores and forgets every owner. Returns true if anything was active. */
    bool ForceRestore(ISaskartaCVarAccess& CVars);

    bool IsActive() const { return Owners.Num() > 0; }
    int32 NumOwners() const { return Owners.Num(); }
    bool HasOwner(FName Owner) const { return Owners.Contains(Owner); }
    const TArray<FSaved>& GetSaved() const { return Saved; }
    /** CVars left alone on the last restore because something else changed them. */
    const TArray<FString>& GetKeptOnRestore() const { return KeptOnRestore; }

    /** The value a setting writes over Current. */
    static float Resolve(EOp Op, float Current, float Value);
    /** String compare, or numeric when both parse as numbers. */
    static bool ValuesEqual(const FString& A, const FString& B);
    static FString FormatValue(float Value);

private:
    void Restore(ISaskartaCVarAccess& CVars);

    TSet<FName> Owners;
    TArray<FSaved> Saved;
    TArray<FString> KeptOnRestore;
};

/** Frame statistics over one log interval (pure; fed once per frame). */
struct SASKARTACORE_API FSaskartaFrameWindow
{
    void AddFrame(float FrameMs);
    void Reset();
    int32 NumFrames() const { return Frames; }
    float MeanMs() const { return Frames > 0 ? static_cast<float>(SumMs / Frames) : 0.f; }
    float MaxMs() const { return MaxFrameMs; }
    /** Frames longer than HitchMs. */
    int32 NumHitches() const { return Hitches; }
    float HitchMs = 50.f;

private:
    double SumMs = 0.0;
    float MaxFrameMs = 0.f;
    int32 Frames = 0;
    int32 Hitches = 0;
};

/**
 * Applies FSaskartaLoadBudgetCore to the real CVars (see the header comment), logs one line per
 * second while active (saskarta.loadbudget.Log) and forces a GC at the end.
 */
UCLASS()
class SASKARTACORE_API USaskartaLoadingBudget : public UGameInstanceSubsystem
{
    GENERATED_BODY()

public:
    virtual void Initialize(FSubsystemCollectionBase& Collection) override;
    virtual void Deinitialize() override;

    UFUNCTION(BlueprintPure, Category = "Saskarta|Performance", meta = (WorldContext = "WorldContext"))
    static USaskartaLoadingBudget* GetLoadingBudget(const UObject* WorldContext);

    /** Turns the loading budget on for Owner (idempotent per owner). */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Performance")
    void BeginLoadingBudget(FName Owner = TEXT("Explicit"));

    /** Ends Owner's hold; the last owner restores the CVars and forces one GC. */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Performance")
    void EndLoadingBudget(FName Owner = TEXT("Explicit"));

    UFUNCTION(BlueprintPure, Category = "Saskarta|Performance")
    bool IsLoadingBudgetActive() const { return Core.IsActive(); }

    /** Call immediately after showing the startup loading widget, after the credit-card
     *  world-render suppression has been released. Only the main game viewport is suppressed;
     *  view-based streaming and the widget continue. Call false before hiding it or revealing Title.
     *  This presentation guard also works when the CVar loading budget is disabled. */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Loading")
    void SetStartupLoadingScreenVisible(UUserWidget* LoadingScreen, bool bVisible);

    /** Releases all loading owners during world teardown, without scheduling a GC.
     *  Idempotent: the outer PIE frame cap calls this before restoring its own snapshot,
     *  regardless of subsystem or world-cleanup callback order. */
    void RestoreForWorldTeardown();

    /** The settings Begin applies (from the saskarta.loadbudget.* CVars). */
    static TArray<FSaskartaLoadBudgetCore::FSetting> BuildSettings();

private:
    void OnEndFrame();
    void OnLogTimer();
    void OnWorldCleanup(UWorld* World, bool bSessionEnded, bool bCleanupResources);
    void RestoreAll(const TCHAR* Why);
    void RefreshPipelineCacheAfterLoading();
    void OnStartupViewportBeginDraw();
    void RestoreStartupWorldRendering(const TCHAR* Why);

    FSaskartaLoadBudgetCore Core;
    FSaskartaFrameWindow Window;
    FTimerHandle LogTimer;
    FDelegateHandle EndFrameHandle;
    FDelegateHandle CleanupHandle;
    double LastFrameS = 0.0;
    double BeganS = 0.0;
    bool bRefreshedPipelineCache = false;
    TWeakObjectPtr<UGameViewportClient> StartupViewport;
    TWeakObjectPtr<UUserWidget> StartupLoadingScreen;
    FDelegateHandle StartupBeginDrawHandle;
    bool bHoldingStartupWorldRendering = false;
    bool bSavedDisableWorldRendering = false;
};
