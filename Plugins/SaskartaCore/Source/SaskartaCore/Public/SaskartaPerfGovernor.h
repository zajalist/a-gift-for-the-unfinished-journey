// Adaptive quality: keeps the frame rate at the target by trading resolution first, then one
// scalability group at a time, and gives it back when there is headroom (task PERF-AUTO).
//
// FSaskartaGovernorCore is the pure state machine (no engine calls; the automation tests feed
// it frame times). USaskartaPerfGovernor is the game-instance subsystem that samples the real
// frame at 2 Hz with a timer, feeds the core and applies its steps.
//
// Rules (Tools/Perf/SCALABILITY.md, "Adaptive quality"):
//   - A sample every 0.5 s: the mean frame time over those 0.5 s, and the busiest of the game
//     thread, render thread and GPU times ("busy", which a frame cap or VSync cannot hide).
//   - The decision uses the MEDIAN of the last 10 samples (5 s), so a hitch cannot move it.
//     A sample above 2.5x the median (and above twice the target) is dropped as a hitch.
//   - Below target: median frame time > target x 1.10, or median GPU time > target x 0.85
//     (GPU headroom for recorders and streams), for 10 s -> one step DOWN.
//   - Headroom: median busy < target x 0.75 (and the frame is on target) for 30 s -> one step UP.
//   - Bottleneck: the samples keep the GPU time and the CPU time (max of game and render
//     thread) apart. CPU-bound = median CPU >= median GPU x 1.10.
//   - DOWN ladder when GPU-bound: screen percentage toward 50 % (at most three steps), then
//     one group at a time in the order shadows, GI, reflections, view distance, effects,
//     foliage (round robin). GI and effects stop at Medium (Low switches Lumen off / the
//     material quality, a visible pop and a PSO hitch); the others stop at Low.
//   - DOWN ladder when CPU/render-thread-bound: resolution cannot help, so view distance,
//     foliage, shadows, effects (round robin, same floors); nothing else when they are out.
//   - UP undoes the most recent DOWN (a stack), so it can never go above the user's own
//     settings.
//   - After any step: 2 s settle (samples ignored), then the 5 s window refills.
//   - No UP within 60 s of a DOWN. A DOWN within 90 s of an UP is a flip-flop: UPs are then
//     blocked for 10 minutes.
//   - Samples during loading, pause, cinematics, an unfocused window or a Blueprint
//     suspension (SetSuspended) are not taken, and they reset the window and the hold timers.

#pragma once

#include "CoreMinimal.h"
#include "Subsystems/GameInstanceSubsystem.h"
#include "SaskartaPerfGovernor.generated.h"

/** The pure governor state machine. Engine-free and deterministic: time is passed in. */
struct SASKARTACORE_API FSaskartaGovernorCore
{
    /** The groups the ladder steps, in ladder order. */
    enum EGroup : int32 { Shadow = 0, GlobalIllumination, Reflection, ViewDistance, Effects, Foliage, NumGroups };

    enum class EAction : uint8 { None, StepDown, StepUp };

    struct FState
    {
        float ScreenPct = 100.f;
        int32 Levels[NumGroups] = { 2, 2, 2, 2, 2, 2 };
        /** The group the next group step starts looking at (round robin). */
        int32 NextGroup = 0;
        /** The same for the CPU-bound ladder (an index into CpuLadder). */
        int32 NextCpuGroup = 0;

        bool operator==(const FState& O) const;
        bool GroupsEqual(const FState& O) const;
    };

    /** What the last step changed (for the log). */
    struct FStep
    {
        EAction Action = EAction::None;
        bool bResolution = false;
        int32 Group = -1;
        float FromPct = 0.f;
        float ToPct = 0.f;
        int32 FromLevel = 0;
        int32 ToLevel = 0;
        float MedianFrameMs = 0.f;
        float MedianBusyMs = 0.f;
        /** The CPU ladder was used (the render/game thread was the limit). */
        bool bCpuBound = false;
    };

    /** The CPU-bound ladder, in order. */
    static constexpr int32 CpuLadderNum = 4;
    static const int32 CpuLadder[CpuLadderNum];

    // ---- tuning (see the header comment) ----
    float TargetFps = 60.f;
    int32 WindowSamples = 10;
    double DownHoldS = 10.0;
    double UpHoldS = 30.0;
    double SettleS = 2.0;
    double UpBlockAfterDownS = 60.0;
    double FlipFlopWindowS = 90.0;
    double FlipFlopPenaltyS = 600.0;
    float DownRatio = 1.10f;
    /** GPU headroom: a median GPU time above target x this also counts as below target, so the
     *  capped frame never uses the whole GPU (room for a recorder or a stream). 0.85 = 14.2 ms at 60. */
    float GpuBudgetRatio = 0.85f;
    float UpBusyRatio = 0.75f;
    float UpFrameRatio = 1.05f;
    float HitchRatio = 2.5f;
    float CpuBoundRatio = 1.10f;
    float ResFloorPct = 50.f;
    float MinResStepPct = 8.f;
    int32 MaxResSteps = 3;

    static const TCHAR* GroupName(int32 Group);

    /** Starts over from the user's settings: clears the stack, the samples and the timers. */
    void Reset(const FState& InBaseline, double NowS);

    /** Loading/pause/cinematic: the window and the hold timers start again. */
    void Invalidate();

    /**
     * One 0.5 s sample. FrameMs = mean frame time, GpuMs = GPU frame time, CpuMs = max(game
     * thread, render thread); 0 = unknown. Returns the step taken, if any; the new state is
     * GetCurrent().
     */
    EAction Update(double NowS, float FrameMs, float GpuMs, float CpuMs, FStep* OutStep = nullptr);

    /** One step down/up now, ignoring the timers (Update uses these). False at the floor / at the baseline. */
    bool StepDown(double NowS, FStep* OutStep = nullptr, bool bCpuBound = false);
    bool StepUp(double NowS, FStep* OutStep = nullptr);

    const FState& GetCurrent() const { return Current; }
    const FState& GetBaseline() const { return Baseline; }
    int32 GetDepth() const { return Stack.Num(); }
    bool IsAtFloor() const;
    bool AreUpsBlocked(double NowS) const { return NowS < UpBlockedUntilS; }
    int32 GetDroppedHitches() const { return DroppedHitches; }
    int32 GetNumSamples() const { return FrameSamples.Num(); }
    float GetMedianFrameMs() const;
    float GetMedianBusyMs() const;
    float GetMedianGpuMs() const;
    float GetMedianCpuMs() const;
    /** Median CPU >= median GPU x CpuBoundRatio (false when either is unknown). */
    bool IsCpuBound() const;
    float GetTargetMs() const { return 1000.f / FMath::Max(TargetFps, 1.f); }
    /** The lowest level the ladder takes a group to. */
    int32 GroupFloor(int32 Group) const;

private:
    void AfterStep(double NowS);
    static float Median(TArray<float> Values);

    FState Baseline;
    FState Current;
    TArray<FState> Stack;
    TArray<float> FrameSamples;
    TArray<float> BusySamples;
    TArray<float> GpuSamples;
    TArray<float> CpuSamples;
    double SettleUntilS = 0.0;
    double BelowSinceS = -1.0;
    double HeadroomSinceS = -1.0;
    double LastDownS = -1.0e9;
    double LastUpS = -1.0e9;
    double UpBlockedUntilS = -1.0e9;
    int32 DroppedHitches = 0;
};

/** Pure ownership rule for the short-lived frame cap used by PIE. */
struct SASKARTACORE_API FSaskartaTransientPIEFpsCap
{
    float PreviousFps = 0.f;
    float AppliedFps = 0.f;
    bool bOwnsCap = false;

    bool Begin(float CurrentFps, float CapFps)
    {
        bOwnsCap = false;
        if (!FMath::IsFinite(CurrentFps) || !FMath::IsFinite(CapFps) || CapFps <= 0.f ||
            (CurrentFps > 0.f && CurrentFps <= CapFps))
        {
            return false;
        }
        PreviousFps = CurrentFps;
        AppliedFps = CapFps;
        bOwnsCap = true;
        return true;
    }

    bool GetRestoreValue(float CurrentFps, float& OutFps) const
    {
        if (!bOwnsCap || CurrentFps != AppliedFps)
        {
            return false;
        }
        OutFps = PreviousFps;
        return true;
    }

    bool CanRestore(int32 ActivePIEWorlds) const
    {
        return bOwnsCap && ActivePIEWorlds == 0;
    }
};

/** Pure ownership policy for the temporary PIE High ceiling (Shadow, GI, Reflection, Effects, Foliage, View Distance, AA). */
struct SASKARTACORE_API FSaskartaTransientPIEQualityCap
{
    TArray<int32> PreviousLevels;
    TArray<int32> AppliedLevels;
    TArray<bool> OwnedGroups;
    bool bOwnsAnyGroup = false;

    bool Begin(const TArray<int32>& CurrentLevels, int32 Ceiling)
    {
        PreviousLevels = CurrentLevels;
        AppliedLevels = CurrentLevels;
        OwnedGroups.Init(false, CurrentLevels.Num());
        bOwnsAnyGroup = false;
        for (int32 Index = 0; Index < CurrentLevels.Num(); ++Index)
        {
            if (CurrentLevels[Index] > Ceiling)
            {
                AppliedLevels[Index] = Ceiling;
                OwnedGroups[Index] = true;
                bOwnsAnyGroup = true;
            }
        }
        return bOwnsAnyGroup;
    }

    bool GetRestoreLevels(const TArray<int32>& CurrentLevels, TArray<int32>& OutLevels) const
    {
        if (CurrentLevels.Num() != PreviousLevels.Num() || OwnedGroups.Num() != PreviousLevels.Num())
        {
            return false;
        }
        OutLevels = CurrentLevels;
        bool bRestoresAny = false;
        for (int32 Index = 0; Index < CurrentLevels.Num(); ++Index)
        {
            if (OwnedGroups[Index] && CurrentLevels[Index] == AppliedLevels[Index])
            {
                OutLevels[Index] = PreviousLevels[Index];
                bRestoresAny = true;
            }
        }
        return bRestoresAny;
    }

    bool CanRestore(int32 ActivePIEWorlds) const
    {
        return ActivePIEWorlds == 0 && bOwnsAnyGroup;
    }
};

/**
 * Samples the frame at 2 Hz (a looping timer on the game instance, no Tick), drives
 * FSaskartaGovernorCore and applies its steps:
 *   - resolution: r.ScreenPercentage (ECVF_SetByGameSetting, the priority the settings use);
 *   - groups: Scalability temporary quality levels, so the user's saved levels (and the ini
 *     GameUserSettings writes) never change;
 *   - foliage: also grass.DensityScale / grass.CullDistanceScale (0.7x / 0.85x per step),
 *     because the settings class owns those two CVars above the scalability priority.
 * Adaptive quality and auto-detect are off in the editor (PIE) unless
 * saskarta.perf.AllowInEditor=1; quality changes are also off while
 * USaskartaGameUserSettings::bAdaptiveQuality is false. PIE separately uses a transient 60 fps
 * cap and High scalability ceiling only when current values are higher, then restores them on teardown if untouched.
 * A user settings change (Apply or Preview in the menu) drops every governor step first.
 *
 * Also runs the first-launch hardware auto-detect (RunAutoDetectIfNeeded) once, 0.5 s after
 * the game instance starts.
 */
UCLASS()
class SASKARTACORE_API USaskartaPerfGovernor : public UGameInstanceSubsystem
{
    GENERATED_BODY()

public:
    virtual void Initialize(FSubsystemCollectionBase& Collection) override;
    virtual void Deinitialize() override;

    UFUNCTION(BlueprintPure, Category = "Saskarta|Performance", meta = (WorldContext = "WorldContext"))
    static USaskartaPerfGovernor* GetPerfGovernor(const UObject* WorldContext);

    /**
     * Pauses sampling while any reason is set: the loading screen ("Loading"), the title
     * sequence ("Title"), a cutscene. Resuming restarts the 5 s window.
     */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Performance")
    void SetSuspended(FName Reason, bool bSuspend);

    /** Drops every governor step and goes back to the user's settings. */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Performance")
    void ResetToUserSettings();

    /** True when sampling (enabled, allowed here, not suspended). */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Performance")
    bool IsActive() const;

    /** How many steps below the user's settings the governor currently is. */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Performance")
    int32 GetStepDepth() const { return Core.GetDepth(); }

    UFUNCTION(BlueprintPure, Category = "Saskarta|Performance")
    float GetTargetFps() const { return Core.TargetFps; }

    /** One line for a debug overlay: target, medians, depth, current screen percentage and levels. */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Performance")
    FString DescribeState() const;

private:
    void OnSampleTimer();
    void OnStartupTimer();
    void OnUserSettingsApplying();
    void OnPostLoadMap(UWorld* World);
    void OnWorldCleanup(UWorld* World, bool bSessionEnded, bool bCleanupResources);
    bool IsAllowedHere() const;
    void ApplyTransientPIEFpsCap(UWorld* World);
    void RestoreTransientPIEFpsCap();
    bool CanSample(FString& OutWhy) const;
    void Rebaseline();
    void ApplyCurrent();
    void DropAllSteps();

    FSaskartaGovernorCore Core;
    FTimerHandle SampleTimer;
    FTimerHandle StartupTimer;
    FDelegateHandle SettingsHandle;
    FDelegateHandle MapHandle;
    FDelegateHandle WorldCleanupHandle;
    TSet<FName> SuspendReasons;
    uint64 LastFrameCounter = 0;
    double LastSampleS = 0.0;
    double GraceUntilS = 0.0;
    bool bNeedsRebaseline = true;
    bool bOwnsTemporaryLevels = false;
    bool bWasEnabled = false;
    TWeakObjectPtr<UWorld> RegisteredPIEWorld;
    float BaseFoliageDensity = 1.f;
    float BaseFoliageDistance = 1.f;
    int32 CachedRefreshHz = -1;
};
