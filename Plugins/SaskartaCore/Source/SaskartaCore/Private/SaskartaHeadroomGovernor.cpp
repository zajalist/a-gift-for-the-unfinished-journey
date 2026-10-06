// Whole-machine headroom governor (task HEADROOM). See SaskartaHeadroomGovernor.h for the rules.

#include "SaskartaHeadroomGovernor.h"

#include "Engine/Engine.h"
#include "Engine/GameInstance.h"
#include "HAL/IConsoleManager.h"
#include "HAL/PlatformMemory.h"
#include "HAL/PlatformTime.h"
#include "Misc/App.h"
#include "Misc/CoreMisc.h"
#include "SaskartaGameUserSettings.h"
#include "SaskartaLoadingBudget.h"
#include "TimerManager.h"

#if PLATFORM_WINDOWS
#include "Windows/AllowWindowsPlatformTypes.h"
#include <windows.h>
#include "Windows/HideWindowsPlatformTypes.h"
#endif

DEFINE_LOG_CATEGORY_STATIC(LogSaskartaHeadroom, Log, All);

// ============================================================================================
// FSaskartaHeadroomCore: pure
// ============================================================================================

float FSaskartaHeadroomCore::Median(TArray<float> Values)
{
    if (Values.Num() == 0)
    {
        return -1.f;
    }
    Values.Sort();
    const int32 N = Values.Num();
    return (N % 2) ? Values[N / 2] : 0.5f * (Values[N / 2 - 1] + Values[N / 2]);
}

float FSaskartaHeadroomCore::GetMedianFreeRamFraction() const
{
    return Median(RamSamples);
}

void FSaskartaHeadroomCore::Reset()
{
    bBackground = false;
    UnfocusedSinceS = -1.0;
    LastFlipS = -1.0;
    bRamPressured = false;
    RamSamples.Reset();
    RamLowSinceS = -1.0;
    RamHighSinceS = -1.0;
    bPendingRamPressureGC = false;
}

FSaskartaHeadroomCore::FStep FSaskartaHeadroomCore::Update(double NowS, bool bFocused, float FreeRamFraction)
{
    FStep S;

    // ---- Focus / background: debounced going in, immediate coming back ----
    if (bFocused)
    {
        UnfocusedSinceS = -1.0;
        if (bBackground)
        {
            bBackground = false;
            LastFlipS = NowS;
            S.bExitBackground = true;
        }
    }
    else
    {
        if (UnfocusedSinceS < 0.0)
        {
            UnfocusedSinceS = NowS;
        }
        if (!bBackground && NowS - UnfocusedSinceS >= FocusLossHoldS - 1.0e-6)
        {
            bBackground = true;
            LastFlipS = NowS;
            S.bEnterBackground = true;
        }
    }

    // ---- RAM pressure: median of the last RamWindowSamples, independent of focus ----
    if (FreeRamFraction >= 0.f)
    {
        RamSamples.Add(FreeRamFraction);
        while (RamSamples.Num() > RamWindowSamples)
        {
            RamSamples.RemoveAt(0);
        }
        if (RamSamples.Num() >= RamWindowSamples)
        {
            const float Med = Median(RamSamples);
            if (!bRamPressured)
            {
                RamLowSinceS = (Med < RamLowFraction) ? (RamLowSinceS < 0.0 ? NowS : RamLowSinceS) : -1.0;
                if (RamLowSinceS >= 0.0 && NowS - RamLowSinceS >= RamPressureHoldS - 1.0e-6)
                {
                    bRamPressured = true;
                    S.bRamPressureOn = true;
                    RamLowSinceS = -1.0;
                    RamHighSinceS = -1.0;
                }
            }
            else
            {
                RamHighSinceS = (Med > RamRecoverFraction) ? (RamHighSinceS < 0.0 ? NowS : RamHighSinceS) : -1.0;
                if (RamHighSinceS >= 0.0 && NowS - RamHighSinceS >= RamPressureHoldS - 1.0e-6)
                {
                    bRamPressured = false;
                    S.bRamPressureOff = true;
                    RamLowSinceS = -1.0;
                    RamHighSinceS = -1.0;
                }
            }
        }
    }

    return S;
}

FSaskartaHeadroomCore::EFpsAction FSaskartaHeadroomCore::DecideFpsAction(bool bHoldingClamp, bool bLoadingOwnsFps, bool bBackgroundFpsEnabled) const
{
    if (bLoadingOwnsFps)
    {
        // The loading budget owns t.MaxFPS right now (SaskartaLoadingBudget.h): never write it
        // from here, in either direction, regardless of the background/focus state. Whatever we
        // were holding (if anything) is untouched and resolves correctly next sample once the
        // loading budget releases the CVar.
        return EFpsAction::None;
    }
    if (bBackground && bBackgroundFpsEnabled)
    {
        return EFpsAction::Apply;
    }
    return bHoldingClamp ? EFpsAction::Revert : EFpsAction::None;
}

FSaskartaHeadroomCore::EGCAction FSaskartaHeadroomCore::DecideRamPressureGCAction(const FStep& Step, bool bLoadingOwnsFps)
{
    if (Step.bRamPressureOff)
    {
        // Pressure cleared on its own (possibly while a deferred GC was still pending): cancel
        // it, there is nothing left to collect for.
        bPendingRamPressureGC = false;
        return EGCAction::None;
    }
    if (Step.bRamPressureOn)
    {
        if (bLoadingOwnsFps)
        {
            bPendingRamPressureGC = true;
            return EGCAction::None;
        }
        return EGCAction::ForceNow;
    }
    if (bPendingRamPressureGC && bRamPressured && !bLoadingOwnsFps)
    {
        // Loading released the frame on a later sample while pressure is still on: run the
        // one-shot GC now instead, exactly once.
        bPendingRamPressureGC = false;
        return EGCAction::ForceNow;
    }
    return EGCAction::None;
}

FSaskartaHeadroomCore::EProcessPriorityAction FSaskartaHeadroomCore::DecideProcessPriorityAction(bool bHoldingPriority, bool bEnabled) const
{
    if (bBackground && bEnabled)
    {
        return bHoldingPriority ? EProcessPriorityAction::None : EProcessPriorityAction::Apply;
    }
    return bHoldingPriority ? EProcessPriorityAction::Revert : EProcessPriorityAction::None;
}

// ============================================================================================
// USaskartaHeadroomGovernor: the engine side
// ============================================================================================

namespace SaskartaHeadroomLocal
{
    static TAutoConsoleVariable<int32> CVarEnable(
        TEXT("saskarta.headroom.Enable"), 1,
        TEXT("Saskarta: 1 lets the whole-machine headroom governor (background mode, RAM-pressure pool floor) run."),
        ECVF_Default);

    static TAutoConsoleVariable<float> CVarBackgroundFPS(
        TEXT("saskarta.headroom.BackgroundFPS"), 15.f,
        TEXT("Saskarta: t.MaxFPS ceiling while the window has no OS focus (never raised above the current cap). <= 0 leaves t.MaxFPS alone."),
        ECVF_Default);

    static TAutoConsoleVariable<int32> CVarBackgroundStreamingPoolMB(
        TEXT("saskarta.headroom.BackgroundStreamingPoolMB"), 512,
        TEXT("Saskarta: r.Streaming.PoolSize ceiling (MB) while the window has no OS focus. <= 0 leaves it alone."),
        ECVF_Default);

    static TAutoConsoleVariable<int32> CVarRamPressureStreamingPoolMB(
        TEXT("saskarta.headroom.RamPressureStreamingPoolMB"), 768,
        TEXT("Saskarta: r.Streaming.PoolSize ceiling (MB) while system-wide RAM pressure is on (see RamLowFraction). <= 0 leaves it alone."),
        ECVF_Default);

    static TAutoConsoleVariable<int32> CVarProcessPriority(
        TEXT("saskarta.headroom.ProcessPriority"), 1,
        TEXT("Saskarta: 1 lowers CPU scheduling to BelowNormal while unfocused; preserves memory/IO priority and resident pages. Windows only."),
        ECVF_Default);

    static TAutoConsoleVariable<float> CVarFocusLossHoldSeconds(
        TEXT("saskarta.headroom.FocusLossHoldSeconds"), 1.5f,
        TEXT("Saskarta: continuous seconds without OS focus before entering background mode. Returning focus is immediate."),
        ECVF_Default);

    static TAutoConsoleVariable<float> CVarRamPressureHoldSeconds(
        TEXT("saskarta.headroom.RamPressureHoldSeconds"), 5.f,
        TEXT("Saskarta: seconds the free-RAM median must stay past RamLowFraction/RamRecoverFraction before toggling RAM pressure."),
        ECVF_Default);

    static TAutoConsoleVariable<float> CVarRamLowFraction(
        TEXT("saskarta.headroom.RamLowFraction"), 0.10f,
        TEXT("Saskarta: system-wide free-RAM-of-total fraction below which RAM pressure turns on."),
        ECVF_Default);

    static TAutoConsoleVariable<float> CVarRamRecoverFraction(
        TEXT("saskarta.headroom.RamRecoverFraction"), 0.18f,
        TEXT("Saskarta: system-wide free-RAM-of-total fraction above which RAM pressure turns back off (hysteresis)."),
        ECVF_Default);

    // Same rule SaskartaLoadingBudget.h documents for its own CVar restores (FConsoleCVarAccess::
    // Write there; this is a fresh implementation, that file is never edited by this one): keep the
    // CVar's own SetBy priority, so a later, more authoritative writer (the settings menu,
    // scalability, the loading budget) can still overwrite it afterwards - but never below
    // SetByScalability, because SetWithCurrentPriority refuses a CVar that still holds
    // ECVF_SetByConstructor ("Trying to Replace Cvar=... Set By Constructor") and falls back to the
    // reserved SETBY_ERROR priority. t.MaxFPS and r.Streaming.PoolSize both start at
    // ECVF_SetByConstructor in a fresh process until something else claims them first.
    static EConsoleVariableFlags WritePriority(EConsoleVariableFlags Flags)
    {
        const uint32 Current = static_cast<uint32>(Flags) & static_cast<uint32>(ECVF_SetByMask);
        return static_cast<EConsoleVariableFlags>(FMath::Max(Current, static_cast<uint32>(ECVF_SetByScalability)));
    }
}

USaskartaHeadroomGovernor* USaskartaHeadroomGovernor::GetHeadroomGovernor(const UObject* WorldContext)
{
    const UWorld* World = GEngine ? GEngine->GetWorldFromContextObject(WorldContext, EGetWorldErrorMode::ReturnNull) : nullptr;
    const UGameInstance* GI = World ? World->GetGameInstance() : nullptr;
    return GI ? GI->GetSubsystem<USaskartaHeadroomGovernor>() : nullptr;
}

bool USaskartaHeadroomGovernor::IsAllowedHere() const
{
    // PIE's process IS the editor: a background-priority drop or an FPS clamp would hit the whole
    // editor, not just the play session, so this shares the project's one editor gate
    // (USaskartaGameUserSettings::IsPerfAutomationAllowed, saskarta.perf.AllowInEditor).
    return USaskartaGameUserSettings::IsPerfAutomationAllowed() && !IsRunningDedicatedServer();
}

void USaskartaHeadroomGovernor::Initialize(FSubsystemCollectionBase& Collection)
{
    Super::Initialize(Collection);
    if (!IsAllowedHere())
    {
        UE_LOG(LogSaskartaHeadroom, Log, TEXT("Headroom governor off (editor/PIE without saskarta.perf.AllowInEditor=1, or a dedicated server)."));
        return;
    }
    GetGameInstance()->GetTimerManager().SetTimer(SampleTimer, this, &USaskartaHeadroomGovernor::OnSampleTimer, 1.0f, true);
}

void USaskartaHeadroomGovernor::Deinitialize()
{
    if (UGameInstance* GI = GetGameInstance())
    {
        GI->GetTimerManager().ClearTimer(SampleTimer);
    }
    RevertAll();
    Super::Deinitialize();
}

void USaskartaHeadroomGovernor::RevertAll()
{
    RevertProcessPriority(); // no-op unless bHoldingProcessPriority
    RevertFpsClamp();
    RevertPoolFloor();
    Core.Reset();
    bWasEnabled = false;
}

void USaskartaHeadroomGovernor::ApplyFpsClamp(float CeilingFps)
{
    IConsoleVariable* V = IConsoleManager::Get().FindConsoleVariable(TEXT("t.MaxFPS"));
    if (!V)
    {
        return;
    }
    if (!bHoldingFpsClamp)
    {
        SavedMaxFpsValue = V->GetString();
        bHoldingFpsClamp = true;
    }
    const float Current = V->GetFloat();
    const float Target = Current <= 0.f ? CeilingFps : FMath::Min(Current, CeilingFps); // 0 = uncapped
    if (!FMath::IsNearlyEqual(Current, Target, 0.001f))
    {
        V->Set(*FString::Printf(TEXT("%.3f"), Target), SaskartaHeadroomLocal::WritePriority(V->GetFlags()));
    }
    LastWrittenMaxFpsValue = V->GetString();
}

void USaskartaHeadroomGovernor::RevertFpsClamp()
{
    if (!bHoldingFpsClamp)
    {
        return;
    }
    if (IConsoleVariable* V = IConsoleManager::Get().FindConsoleVariable(TEXT("t.MaxFPS")))
    {
        if (V->GetString() == LastWrittenMaxFpsValue)
        {
            V->Set(*SavedMaxFpsValue, SaskartaHeadroomLocal::WritePriority(V->GetFlags()));
        }
        // else something more authoritative (settings, scalability, the loading budget) already
        // changed it while we held the clamp: leave that newer value alone.
    }
    bHoldingFpsClamp = false;
    SavedMaxFpsValue.Reset();
    LastWrittenMaxFpsValue.Reset();
}

void USaskartaHeadroomGovernor::ApplyPoolFloor(float FloorMB)
{
    IConsoleVariable* V = IConsoleManager::Get().FindConsoleVariable(TEXT("r.Streaming.PoolSize"));
    if (!V)
    {
        return;
    }
    if (!bHoldingPoolFloor)
    {
        SavedPoolValue = V->GetString();
        bHoldingPoolFloor = true;
    }
    const float Baseline = FCString::Atof(*SavedPoolValue);
    const float Target = Baseline <= 0.f ? FloorMB : FMath::Min(Baseline, FloorMB); // 0 = unlimited pool
    if (!FMath::IsNearlyEqual(V->GetFloat(), Target, 0.5f))
    {
        V->Set(*FString::Printf(TEXT("%.0f"), Target), SaskartaHeadroomLocal::WritePriority(V->GetFlags()));
    }
    LastWrittenPoolValue = V->GetString();
}

void USaskartaHeadroomGovernor::RevertPoolFloor()
{
    if (!bHoldingPoolFloor)
    {
        return;
    }
    if (IConsoleVariable* V = IConsoleManager::Get().FindConsoleVariable(TEXT("r.Streaming.PoolSize")))
    {
        if (V->GetString() == LastWrittenPoolValue)
        {
            V->Set(*SavedPoolValue, SaskartaHeadroomLocal::WritePriority(V->GetFlags()));
        }
    }
    bHoldingPoolFloor = false;
    SavedPoolValue.Reset();
    LastWrittenPoolValue.Reset();
}

void USaskartaHeadroomGovernor::ApplyProcessPriority()
{
#if PLATFORM_WINDOWS
    if (bHoldingProcessPriority)
    {
        return;
    }
    const DWORD Current = ::GetPriorityClass(::GetCurrentProcess());
    if (Current == 0)
    {
        UE_LOG(LogSaskartaHeadroom, Warning, TEXT("GetPriorityClass failed (GetLastError %u)."), ::GetLastError());
        return;
    }
    // Respect an already lower priority and do not claim somebody else's setting.
    if (Current == BELOW_NORMAL_PRIORITY_CLASS || Current == IDLE_PRIORITY_CLASS)
    {
        return;
    }
    if (!::SetPriorityClass(::GetCurrentProcess(), BELOW_NORMAL_PRIORITY_CLASS))
    {
        UE_LOG(LogSaskartaHeadroom, Warning, TEXT("SetPriorityClass(BELOW_NORMAL_PRIORITY_CLASS) failed (GetLastError %u)."), ::GetLastError());
        return;
    }
    SavedProcessPriorityClass = Current;
    bHoldingProcessPriority = true;
#endif
}

void USaskartaHeadroomGovernor::RevertProcessPriority()
{
#if PLATFORM_WINDOWS
    if (!bHoldingProcessPriority)
    {
        return;
    }
    const DWORD Current = ::GetPriorityClass(::GetCurrentProcess());
    if (Current == 0)
    {
        UE_LOG(LogSaskartaHeadroom, Warning, TEXT("GetPriorityClass on restore failed (GetLastError %u)."), ::GetLastError());
        return; // retain ownership so the next sample can retry
    }
    // Preserve a newer external priority selection, just as the CVar restores do.
    if (Current == BELOW_NORMAL_PRIORITY_CLASS &&
        !::SetPriorityClass(::GetCurrentProcess(), SavedProcessPriorityClass))
    {
        UE_LOG(LogSaskartaHeadroom, Warning, TEXT("Restoring CPU process priority failed (GetLastError %u)."), ::GetLastError());
        return;
    }
    bHoldingProcessPriority = false;
    SavedProcessPriorityClass = 0;
#endif
}

void USaskartaHeadroomGovernor::OnSampleTimer()
{
    using namespace SaskartaHeadroomLocal;

    if (CVarEnable.GetValueOnGameThread() == 0)
    {
        if (bWasEnabled || bHoldingProcessPriority)
        {
            RevertAll();
            UE_LOG(LogSaskartaHeadroom, Log, TEXT("Headroom governor: off (saskarta.headroom.Enable 0)."));
        }
        return;
    }
    bWasEnabled = true;

    Core.FocusLossHoldS = CVarFocusLossHoldSeconds.GetValueOnGameThread();
    Core.RamPressureHoldS = CVarRamPressureHoldSeconds.GetValueOnGameThread();
    Core.RamLowFraction = CVarRamLowFraction.GetValueOnGameThread();
    Core.RamRecoverFraction = CVarRamRecoverFraction.GetValueOnGameThread();

    const bool bFocused = FApp::HasFocus();
    const FPlatformMemoryStats Mem = FPlatformMemory::GetStats();
    const float FreeRamFraction = Mem.TotalPhysical > 0
        ? static_cast<float>(static_cast<double>(Mem.AvailablePhysical) / static_cast<double>(Mem.TotalPhysical))
        : -1.f;

    const double Now = FPlatformTime::Seconds();
    const FSaskartaHeadroomCore::FStep Step = Core.Update(Now, bFocused, FreeRamFraction);

    // Sampled once up front so the FPS-clamp and RAM-pressure-GC decisions below agree on it for
    // this sample: SaskartaLoadingBudget.h owns t.MaxFPS, and forbids any GC, for the length of a
    // loading screen (BuildSettings(): "GC: none during loading... no forced GC per streamed-out
    // level"). Never edited by this file - only its public IsLoadingBudgetActive() is read.
    const USaskartaLoadingBudget* LoadingBudget = GetGameInstance() ? GetGameInstance()->GetSubsystem<USaskartaLoadingBudget>() : nullptr;
    const bool bLoadingOwnsFrame = LoadingBudget && LoadingBudget->IsLoadingBudgetActive();

    if (Step.bEnterBackground)
    {
        UE_LOG(LogSaskartaHeadroom, Log, TEXT("Headroom: window lost focus, entering background mode (fps<=%.0f when loading releases its cap, pool<=%d MB; CPU-only priority policy, no working-set eviction)."),
            CVarBackgroundFPS.GetValueOnGameThread(), CVarBackgroundStreamingPoolMB.GetValueOnGameThread());
    }
    else if (Step.bExitBackground)
    {
        UE_LOG(LogSaskartaHeadroom, Log, TEXT("Headroom: window regained focus, leaving background mode."));
    }

    // Lower only CPU scheduling. Process-wide Windows background mode also
    // deprioritizes memory/I/O; paired with working-set eviction it stalled the
    // packaged loader/audio even with >50% physical RAM available.
    switch (Core.DecideProcessPriorityAction(bHoldingProcessPriority, CVarProcessPriority.GetValueOnGameThread() != 0))
    {
    case FSaskartaHeadroomCore::EProcessPriorityAction::Apply:
        ApplyProcessPriority();
        break;
    case FSaskartaHeadroomCore::EProcessPriorityAction::Revert:
        RevertProcessPriority();
        break;
    case FSaskartaHeadroomCore::EProcessPriorityAction::None:
    default:
        break;
    }

    // RAM-pressure GC: never runs while the loading budget owns the frame - it deliberately holds
    // every GC back to avoid a mid-load hitch - so a trip mid-load defers to the first sample
    // after loading ends (still gated on pressure still being on then). See DecideRamPressureGCAction.
    switch (Core.DecideRamPressureGCAction(Step, bLoadingOwnsFrame))
    {
    case FSaskartaHeadroomCore::EGCAction::ForceNow:
        if (GEngine)
        {
            GEngine->ForceGarbageCollection(false); // incremental, not a full blocking purge
        }
        if (Step.bRamPressureOn)
        {
            UE_LOG(LogSaskartaHeadroom, Log, TEXT("Headroom: system RAM pressure on (free %.0f%% < %.0f%%), flooring the streaming pool at %d MB."),
                Core.GetMedianFreeRamFraction() * 100.f, Core.RamLowFraction * 100.f, CVarRamPressureStreamingPoolMB.GetValueOnGameThread());
        }
        else
        {
            UE_LOG(LogSaskartaHeadroom, Log, TEXT("Headroom: loading ended with RAM pressure still on (free %.0f%%); running the GC the loading budget deferred."),
                Core.GetMedianFreeRamFraction() * 100.f);
        }
        break;
    case FSaskartaHeadroomCore::EGCAction::None:
    default:
        if (Step.bRamPressureOn)
        {
            UE_LOG(LogSaskartaHeadroom, Log, TEXT("Headroom: system RAM pressure on (free %.0f%% < %.0f%%) but the loading budget owns the frame - deferring the GC until loading ends."),
                Core.GetMedianFreeRamFraction() * 100.f, Core.RamLowFraction * 100.f);
        }
        else if (Step.bRamPressureOff)
        {
            UE_LOG(LogSaskartaHeadroom, Log, TEXT("Headroom: system RAM pressure off (free %.0f%% > %.0f%%)."),
                Core.GetMedianFreeRamFraction() * 100.f, Core.RamRecoverFraction * 100.f);
        }
        break;
    }

    // t.MaxFPS: re-derived every sample (not just on the Enter/Exit edge) so a loading screen
    // starting or ending while already backgrounded still resolves to the right value. The
    // loading budget owns t.MaxFPS while it is active - DecideFpsAction never applies or reverts
    // the clamp then, in either direction, so a load starting or ending mid-background can never
    // stomp whatever value the loading budget is responsible for at that instant.
    const float BackgroundFps = CVarBackgroundFPS.GetValueOnGameThread();
    switch (Core.DecideFpsAction(bHoldingFpsClamp, bLoadingOwnsFrame, BackgroundFps > 0.f))
    {
    case FSaskartaHeadroomCore::EFpsAction::Apply:
        ApplyFpsClamp(BackgroundFps);
        break;
    case FSaskartaHeadroomCore::EFpsAction::Revert:
        RevertFpsClamp();
        break;
    case FSaskartaHeadroomCore::EFpsAction::None:
    default:
        break;
    }

    // r.Streaming.PoolSize: the loading budget never touches this CVar, so both floors keep
    // applying/re-deriving every sample regardless of bLoadingOwnsFrame. The tighter of the two
    // active floors wins.
    float DesiredFloorMB = -1.f;
    if (Core.IsBackground() && CVarBackgroundStreamingPoolMB.GetValueOnGameThread() > 0)
    {
        DesiredFloorMB = static_cast<float>(CVarBackgroundStreamingPoolMB.GetValueOnGameThread());
    }
    if (Core.IsRamPressured() && CVarRamPressureStreamingPoolMB.GetValueOnGameThread() > 0)
    {
        const float RamFloor = static_cast<float>(CVarRamPressureStreamingPoolMB.GetValueOnGameThread());
        DesiredFloorMB = DesiredFloorMB > 0.f ? FMath::Min(DesiredFloorMB, RamFloor) : RamFloor;
    }
    if (DesiredFloorMB > 0.f)
    {
        ApplyPoolFloor(DesiredFloorMB);
    }
    else if (bHoldingPoolFloor)
    {
        RevertPoolFloor();
    }
}

FString USaskartaHeadroomGovernor::DescribeState() const
{
    const float FreeRam = Core.GetMedianFreeRamFraction();
    return FString::Printf(TEXT("%s%s | free RAM %.0f%%%s"),
        Core.IsBackground() ? TEXT("BACKGROUND") : TEXT("foreground"),
        bHoldingProcessPriority ? TEXT(" (CPU priority: below normal)") : TEXT(""),
        FreeRam >= 0.f ? FreeRam * 100.f : 0.f,
        Core.IsRamPressured() ? TEXT(" | RAM PRESSURE") : TEXT(""));
}
