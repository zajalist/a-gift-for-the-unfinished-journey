// Whole-machine headroom (task HEADROOM): unlike USaskartaPerfGovernor (SaskartaPerfGovernor.h),
// which only trades visual quality to hit a GPU-busy-time budget, this keeps the rest of the
// machine usable while the game runs - CPU scheduling, system RAM and the texture
// streaming VRAM pool - and gets out of the way entirely the instant the game is not the
// focused window, so a recorder/browser/Discord/etc. alongside it stays smooth.
//
// FSaskartaHeadroomCore is the pure state machine (no engine calls; the automation tests feed
// it fake samples). USaskartaHeadroomGovernor is the game-instance subsystem that samples the
// real focus/RAM state at 1 Hz with a timer, feeds the core and applies its two independent
// reasons to back off:
//
//   - Background (focus lost): after the window has had no OS focus for
//     saskarta.headroom.FocusLossHoldSeconds straight (debounced so a one-message flicker, e.g.
//     a tooltip stealing focus, does not trigger it), the governor:
//       - caps t.MaxFPS at saskarta.headroom.BackgroundFPS (never raises it). The loading budget
//         (SaskartaLoadingBudget.h) owns t.MaxFPS for the length of a loading screen: while it is
//         active this governor never writes t.MaxFPS in EITHER direction - not to apply the
//         clamp, and not to revert to the pre-background baseline - checked every sample
//         (FSaskartaHeadroomCore::DecideFpsAction) so a load starting or ending mid-background
//         can never stomp whatever value the loading budget is responsible for at that instant;
//         whatever this governor was holding (if anything) resolves correctly, against whatever
//         value the loading budget left behind, on the very next sample after it releases the
//         CVar;
//       - lowers CPU scheduling to Windows BELOW_NORMAL_PRIORITY_CLASS, preserving the prior
//         class for restoration. Memory/I/O priority is unchanged: the interactive game's
//         loading, rendering and audio threads still need resident pages and prompt reads;
//       - never forcibly empties the working set. Windows may reclaim pages under pressure;
//         evicting an active streaming game's own pages caused persistent packaged stalls;
//       - floors r.Streaming.PoolSize at saskarta.headroom.BackgroundStreamingPoolMB, so the
//         texture streamer evicts VRAM back to the system over the next few frames. The loading
//         budget never touches this CVar, so this floor is unconditional.
//     Returning focus reverses the owned clamps/CPU priority on the next sample (no hold).
//
//   - RAM pressure (independent of focus): when system-wide free physical RAM (not just this
//     process' own usage - other processes' pressure matters too) stays below
//     saskarta.headroom.RamLowFraction for saskarta.headroom.RamPressureHoldSeconds (median of
//     the last few samples, so one transient dip does not trigger it), the governor forces one
//     incremental garbage collection and floors r.Streaming.PoolSize at
//     saskarta.headroom.RamPressureStreamingPoolMB. It clears with hysteresis, once free RAM
//     recovers above saskarta.headroom.RamRecoverFraction for the same hold. The GC never runs
//     while the loading budget owns the frame - it deliberately holds every GC back for the
//     length of a loading screen to avoid a mid-load hitch (see BuildSettings() there) - so if
//     pressure trips mid-load, FSaskartaHeadroomCore::DecideRamPressureGCAction defers the
//     one-shot GC to the first sample after loading ends, and only then if pressure is still on.
//     The pool floor never touches frame rate or process priority: those would cost the
//     *player's* own experience for a problem that is usually just texture residency, which the
//     streamer already knows how to recover from gracefully.
//
// The two reasons share r.Streaming.PoolSize through one snapshot/apply/restore (the tighter of
// the two floors wins while more than one is active); the restore only writes the saved value
// back when the CVar still holds what this governor last wrote it to - the same
// "keep it if something else changed it meanwhile" rule SaskartaLoadingBudget.h documents for
// its own CVar restores (see FConsoleCVarAccess::Write there; never edited by this file).
//
// Deliberately NOT covered in this pass: system-wide CPU pressure while the window stays
// focused. There is no safe lever to hand CPU cycles to another process without either costing
// the player's own frame rate (which nothing here asks for while they are actively looking at
// the game) or reaching into the render/game thread pools at a depth this pass did not verify
// live (the editor is closed for this change). The existing USaskartaPerfGovernor CPU-bound
// ladder already answers "is this process using more CPU than it needs to hit its own target";
// answering "is the *machine* out of CPU" safely needs a follow-up pass with a live profiling
// session.
//
// Off in the editor (PIE) unless saskarta.perf.AllowInEditor=1 (USaskartaGameUserSettings:
// PIE's process IS the editor, so a background-priority drop or an FPS clamp would hit the
// whole editor, not just the play session) and off on a dedicated server (no OS window/focus).

#pragma once

#include "CoreMinimal.h"
#include "Subsystems/GameInstanceSubsystem.h"
#include "SaskartaHeadroomGovernor.generated.h"

/** The pure headroom state machine. Engine-free and deterministic: time and samples are passed in. */
struct SASKARTACORE_API FSaskartaHeadroomCore
{
    /** What changed this sample, if anything (more than one can fire on the same sample). */
    struct FStep
    {
        bool bEnterBackground = false;
        bool bExitBackground = false;
        bool bRamPressureOn = false;
        bool bRamPressureOff = false;
    };

    // ---- tuning (see the header comment) ----
    /** Continuous seconds without OS focus before EnterBackground. Exit is immediate. */
    double FocusLossHoldS = 1.5;
    /** Seconds a median sample must stay past a RAM threshold before toggling pressure. */
    double RamPressureHoldS = 5.0;
    /** Free-RAM-of-total fraction below which pressure turns on. */
    float RamLowFraction = 0.10f;
    /** Free-RAM-of-total fraction above which pressure turns back off (hysteresis gap). */
    float RamRecoverFraction = 0.18f;
    /** The median window for the RAM samples (paired with the subsystem's ~1 s sample cadence). */
    int32 RamWindowSamples = 6;

    /**
     * One sample. bFocused is the OS focus state now. FreeRamFraction is system-wide available
     * physical RAM / total physical RAM, or a negative value when unknown (skips the RAM side
     * for that sample; the running median is unaffected). Returns what changed.
     */
    FStep Update(double NowS, bool bFocused, float FreeRamFraction);

    bool IsBackground() const { return bBackground; }
    bool IsRamPressured() const { return bRamPressured; }
    /** Seconds since the last EnterBackground/ExitBackground flip; 0 if never flipped. */
    double SecondsInState(double NowS) const { return LastFlipS < 0.0 ? 0.0 : FMath::Max(NowS - LastFlipS, 0.0); }
    float GetMedianFreeRamFraction() const;

    /** What USaskartaHeadroomGovernor should do to t.MaxFPS this sample. */
    enum class EFpsAction : uint8
    {
        None,
        Apply,
        Revert,
    };

    /**
     * Decides the t.MaxFPS action, given whether the governor is already holding a clamp and
     * whether the loading budget (SaskartaLoadingBudget.h) currently owns t.MaxFPS - which this
     * core otherwise knows nothing about. Never Apply or Revert while bLoadingOwnsFps: that CVar
     * belongs to the loading budget for the length of a loading screen, in either direction, so a
     * load starting or ending mid-background can never stomp its cap. Pure and stateless (reads
     * only IsBackground()); safe to call every sample regardless of what Update() just returned.
     */
    EFpsAction DecideFpsAction(bool bHoldingClamp, bool bLoadingOwnsFps, bool bBackgroundFpsEnabled) const;

    enum class EProcessPriorityAction : uint8
    {
        None,
        Apply,
        Revert,
    };

    /** CPU-only priority ownership, re-evaluated every sample including CVar-off/focus return. */
    EProcessPriorityAction DecideProcessPriorityAction(bool bHoldingPriority, bool bEnabled) const;

    /** What USaskartaHeadroomGovernor should do about the RAM-pressure GC this sample. */
    enum class EGCAction : uint8
    {
        None,
        ForceNow,
    };

    /**
     * Decides the RAM-pressure GC action from this sample's Step and whether the loading budget
     * currently owns the frame. SaskartaLoadingBudget.h deliberately holds every GC back for the
     * length of a loading screen (BuildSettings(): "GC: none during loading") to avoid a mid-load
     * hitch, so a pressure-on edge while bLoadingOwnsFps defers the one-shot GC (remembered
     * internally) instead of forcing it immediately; the deferred GC fires on the first later
     * call where bLoadingOwnsFps is false and pressure is still on, and is cancelled if pressure
     * clears first. Call once per sample, in Step order, so the deferred state stays consistent.
     */
    EGCAction DecideRamPressureGCAction(const FStep& Step, bool bLoadingOwnsFps);

    /** Resets every timer/window; both reasons start off. For tests and for Deinitialize(). */
    void Reset();

private:
    static float Median(TArray<float> Values);

    bool bBackground = false;
    double UnfocusedSinceS = -1.0;
    double LastFlipS = -1.0;

    bool bRamPressured = false;
    TArray<float> RamSamples;
    double RamLowSinceS = -1.0;
    double RamHighSinceS = -1.0;

    bool bPendingRamPressureGC = false;
};

/**
 * Applies FSaskartaHeadroomCore to the real process/CVars (see SaskartaHeadroomGovernor.h):
 * samples FApp::HasFocus() and FPlatformMemory::GetStats() on a 1 Hz timer, no per-frame Tick.
 */
UCLASS()
class SASKARTACORE_API USaskartaHeadroomGovernor : public UGameInstanceSubsystem
{
    GENERATED_BODY()

public:
    virtual void Initialize(FSubsystemCollectionBase& Collection) override;
    virtual void Deinitialize() override;

    UFUNCTION(BlueprintPure, Category = "Saskarta|Performance", meta = (WorldContext = "WorldContext"))
    static USaskartaHeadroomGovernor* GetHeadroomGovernor(const UObject* WorldContext);

    /** True once the window has had no OS focus for FSaskartaHeadroomCore::FocusLossHoldS. */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Performance")
    bool IsBackground() const { return Core.IsBackground(); }

    /** True while system-wide free RAM has been low for FSaskartaHeadroomCore::RamPressureHoldS. */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Performance")
    bool IsRamPressured() const { return Core.IsRamPressured(); }

    /** One line for a debug overlay. */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Performance")
    FString DescribeState() const;

private:
    void OnSampleTimer();
    bool IsAllowedHere() const;

    void ApplyFpsClamp(float CeilingFps);
    void RevertFpsClamp();
    void ApplyPoolFloor(float FloorMB);
    void RevertPoolFloor();
    void ApplyProcessPriority();
    void RevertProcessPriority();
    /** Reverts every held CVar/process-priority change; called on Deinitialize and when the
     *  master CVar is turned off mid-session. */
    void RevertAll();

    FSaskartaHeadroomCore Core;
    FTimerHandle SampleTimer;

    bool bHoldingFpsClamp = false;
    FString SavedMaxFpsValue;
    FString LastWrittenMaxFpsValue;

    bool bHoldingPoolFloor = false;
    FString SavedPoolValue;
    FString LastWrittenPoolValue;

    bool bHoldingProcessPriority = false;
    uint32 SavedProcessPriorityClass = 0;
    bool bWasEnabled = false;
};
