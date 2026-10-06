// Adaptive quality governor (task PERF-AUTO). See SaskartaPerfGovernor.h for the rules and
// Tools/Perf/SCALABILITY.md for the table.

#include "SaskartaPerfGovernor.h"

#include "CoreGlobals.h"
#include "DynamicRHI.h"
#include "Engine/Engine.h"
#include "Engine/GameInstance.h"
#include "Engine/World.h"
#include "GameFramework/PlayerController.h"
#include "HAL/IConsoleManager.h"
#include "HAL/PlatformTime.h"
#include "Kismet/GameplayStatics.h"
#include "Misc/App.h"
#include "RenderTimer.h"
#include "SaskartaGameUserSettings.h"
#include "SaskartaHardwareProfile.h"
#include "SaskartaLoadingBudget.h"
#include "Scalability.h"
#include "TimerManager.h"
#include "UObject/UObjectGlobals.h"

DEFINE_LOG_CATEGORY_STATIC(LogSaskartaPerf, Log, All);

// ============================================================================================
// FSaskartaGovernorCore: pure
// ============================================================================================

bool FSaskartaGovernorCore::FState::GroupsEqual(const FState& O) const
{
    for (int32 G = 0; G < NumGroups; ++G)
    {
        if (Levels[G] != O.Levels[G])
        {
            return false;
        }
    }
    return true;
}

bool FSaskartaGovernorCore::FState::operator==(const FState& O) const
{
    return FMath::IsNearlyEqual(ScreenPct, O.ScreenPct, 0.01f) && GroupsEqual(O) && NextGroup == O.NextGroup && NextCpuGroup == O.NextCpuGroup;
}

// View distance and foliage are what the render thread pays for (primitives, draw calls,
// visibility); shadows re-draw non-Nanite casters; effects are particles and fog.
const int32 FSaskartaGovernorCore::CpuLadder[FSaskartaGovernorCore::CpuLadderNum] = {
    FSaskartaGovernorCore::ViewDistance, FSaskartaGovernorCore::Foliage, FSaskartaGovernorCore::Shadow, FSaskartaGovernorCore::Effects };

const TCHAR* FSaskartaGovernorCore::GroupName(int32 Group)
{
    static const TCHAR* Names[NumGroups] = { TEXT("Shadows"), TEXT("GlobalIllumination"), TEXT("Reflections"), TEXT("ViewDistance"), TEXT("Effects"), TEXT("Foliage") };
    return Group >= 0 && Group < NumGroups ? Names[Group] : TEXT("?");
}

void FSaskartaGovernorCore::Reset(const FState& InBaseline, double NowS)
{
    Baseline = InBaseline;
    Current = InBaseline;
    Stack.Reset();
    FrameSamples.Reset();
    BusySamples.Reset();
    GpuSamples.Reset();
    CpuSamples.Reset();
    SettleUntilS = NowS;
    BelowSinceS = -1.0;
    HeadroomSinceS = -1.0;
    LastDownS = -1.0e9;
    LastUpS = -1.0e9;
    UpBlockedUntilS = -1.0e9;
    DroppedHitches = 0;
}

void FSaskartaGovernorCore::Invalidate()
{
    FrameSamples.Reset();
    BusySamples.Reset();
    GpuSamples.Reset();
    CpuSamples.Reset();
    BelowSinceS = -1.0;
    HeadroomSinceS = -1.0;
}

int32 FSaskartaGovernorCore::GroupFloor(int32 Group) const
{
    // GI Low switches Lumen off and Effects Low drops the material quality level (a visible
    // pop and a PSO hitch), so the governor stops those two at Medium.
    const int32 Floor = (Group == GlobalIllumination || Group == Effects) ? 1 : 0;
    return FMath::Min(Baseline.Levels[Group], Floor);
}

bool FSaskartaGovernorCore::IsAtFloor() const
{
    if (Current.ScreenPct > ResFloorPct + 0.01f)
    {
        return false;
    }
    for (int32 G = 0; G < NumGroups; ++G)
    {
        if (Current.Levels[G] > GroupFloor(G))
        {
            return false;
        }
    }
    return true;
}

float FSaskartaGovernorCore::Median(TArray<float> Values)
{
    if (Values.Num() == 0)
    {
        return 0.f;
    }
    Values.Sort();
    const int32 N = Values.Num();
    return (N % 2) ? Values[N / 2] : 0.5f * (Values[N / 2 - 1] + Values[N / 2]);
}

float FSaskartaGovernorCore::GetMedianFrameMs() const
{
    return Median(FrameSamples);
}

float FSaskartaGovernorCore::GetMedianBusyMs() const
{
    return Median(BusySamples);
}

float FSaskartaGovernorCore::GetMedianGpuMs() const
{
    return Median(GpuSamples);
}

float FSaskartaGovernorCore::GetMedianCpuMs() const
{
    return Median(CpuSamples);
}

bool FSaskartaGovernorCore::IsCpuBound() const
{
    const float Gpu = GetMedianGpuMs();
    const float Cpu = GetMedianCpuMs();
    return Gpu > 0.f && Cpu > 0.f && Cpu >= Gpu * CpuBoundRatio;
}

void FSaskartaGovernorCore::AfterStep(double NowS)
{
    // The step itself hitches (grass rebuild, shadow pages): settle, then refill the window.
    FrameSamples.Reset();
    BusySamples.Reset();
    GpuSamples.Reset();
    CpuSamples.Reset();
    BelowSinceS = -1.0;
    HeadroomSinceS = -1.0;
    SettleUntilS = NowS + SettleS;
}

bool FSaskartaGovernorCore::StepDown(double NowS, FStep* OutStep, bool bCpuBound)
{
    FStep S;
    S.Action = EAction::StepDown;
    S.MedianFrameMs = GetMedianFrameMs();
    S.MedianBusyMs = GetMedianBusyMs();
    S.bCpuBound = bCpuBound;

    if (bCpuBound)
    {
        // Render/game thread is the limit: fewer primitives, not fewer pixels.
        bool bFound = false;
        for (int32 I = 0; I < CpuLadderNum && !bFound; ++I)
        {
            const int32 Slot = (Current.NextCpuGroup + I) % CpuLadderNum;
            const int32 G = CpuLadder[Slot];
            if (Current.Levels[G] > GroupFloor(G))
            {
                Stack.Push(Current);
                S.Group = G;
                S.FromLevel = Current.Levels[G];
                Current.Levels[G] -= 1;
                S.ToLevel = Current.Levels[G];
                Current.NextCpuGroup = (Slot + 1) % CpuLadderNum;
                bFound = true;
            }
        }
        if (!bFound)
        {
            return false; // resolution, GI and reflections would not help the CPU
        }
    }
    else if (Current.ScreenPct > ResFloorPct + 0.01f)
    {
        // At most MaxResSteps even steps from the user's percentage to the floor
        // (66.7 -> 58.4 -> 50; 100 -> 83.3 -> 66.7 -> 50).
        const float Span = FMath::Max(Baseline.ScreenPct - ResFloorPct, 0.f);
        const int32 NumSteps = FMath::Clamp(FMath::RoundToInt(Span / MinResStepPct), 1, MaxResSteps);
        const float StepPct = FMath::Max(Span / NumSteps, 1.f);
        Stack.Push(Current);
        S.bResolution = true;
        S.FromPct = Current.ScreenPct;
        float To = Current.ScreenPct - StepPct;
        if (To < ResFloorPct + 0.5f)
        {
            To = ResFloorPct;
        }
        Current.ScreenPct = To;
        S.ToPct = To;
    }
    else
    {
        bool bFound = false;
        for (int32 I = 0; I < NumGroups && !bFound; ++I)
        {
            const int32 G = (Current.NextGroup + I) % NumGroups;
            if (Current.Levels[G] > GroupFloor(G))
            {
                Stack.Push(Current);
                S.Group = G;
                S.FromLevel = Current.Levels[G];
                Current.Levels[G] -= 1;
                S.ToLevel = Current.Levels[G];
                Current.NextGroup = (G + 1) % NumGroups;
                bFound = true;
            }
        }
        if (!bFound)
        {
            return false;
        }
    }

    if (NowS - LastUpS < FlipFlopWindowS)
    {
        // Went up, then had to come back down: stop going up for a while.
        UpBlockedUntilS = NowS + FlipFlopPenaltyS;
    }
    LastDownS = NowS;
    AfterStep(NowS);
    if (OutStep)
    {
        *OutStep = S;
    }
    return true;
}

bool FSaskartaGovernorCore::StepUp(double NowS, FStep* OutStep)
{
    if (Stack.Num() == 0)
    {
        return false;
    }
    FStep S;
    S.Action = EAction::StepUp;
    S.MedianFrameMs = GetMedianFrameMs();
    S.MedianBusyMs = GetMedianBusyMs();
    const FState Prev = Stack.Pop();
    if (!FMath::IsNearlyEqual(Prev.ScreenPct, Current.ScreenPct, 0.01f))
    {
        S.bResolution = true;
        S.FromPct = Current.ScreenPct;
        S.ToPct = Prev.ScreenPct;
    }
    for (int32 G = 0; G < NumGroups; ++G)
    {
        if (Prev.Levels[G] != Current.Levels[G])
        {
            S.Group = G;
            S.FromLevel = Current.Levels[G];
            S.ToLevel = Prev.Levels[G];
        }
    }
    Current = Prev;
    LastUpS = NowS;
    AfterStep(NowS);
    if (OutStep)
    {
        *OutStep = S;
    }
    return true;
}

FSaskartaGovernorCore::EAction FSaskartaGovernorCore::Update(double NowS, float FrameMs, float GpuMs, float CpuMs, FStep* OutStep)
{
    if (FrameMs <= 0.f || NowS < SettleUntilS)
    {
        return EAction::None;
    }
    const float TargetMs = GetTargetMs();

    // Hitch rejection: one long sample (a streaming hitch, a shader compile) is not a trend.
    if (FrameSamples.Num() >= 3)
    {
        const float Med = GetMedianFrameMs();
        if (FrameMs > Med * HitchRatio && FrameMs > TargetMs * 2.f)
        {
            ++DroppedHitches;
            return EAction::None;
        }
    }
    FrameSamples.Add(FrameMs);
    GpuSamples.Add(FMath::Max(GpuMs, 0.f));
    CpuSamples.Add(FMath::Max(CpuMs, 0.f));
    BusySamples.Add(FMath::Max3(GpuMs, CpuMs, 0.f));
    while (FrameSamples.Num() > WindowSamples)
    {
        FrameSamples.RemoveAt(0);
        BusySamples.RemoveAt(0);
        GpuSamples.RemoveAt(0);
        CpuSamples.RemoveAt(0);
    }
    if (FrameSamples.Num() < WindowSamples)
    {
        return EAction::None;
    }

    const float MedFrame = GetMedianFrameMs();
    const float MedBusy = GetMedianBusyMs();
    const bool bBelow = MedFrame > TargetMs * DownRatio || GetMedianGpuMs() > TargetMs * GpuBudgetRatio;
    // With a frame cap or VSync the frame time sits on the target however idle the machine
    // is, so headroom is judged by the busiest of game, render and GPU.
    const float Load = MedBusy > 0.f ? MedBusy : MedFrame;
    const bool bHeadroom = !bBelow && Stack.Num() > 0 && MedFrame <= TargetMs * UpFrameRatio && Load < TargetMs * UpBusyRatio;

    BelowSinceS = bBelow ? (BelowSinceS < 0.0 ? NowS : BelowSinceS) : -1.0;
    HeadroomSinceS = bHeadroom ? (HeadroomSinceS < 0.0 ? NowS : HeadroomSinceS) : -1.0;

    if (bBelow && NowS - BelowSinceS >= DownHoldS - 1.0e-6)
    {
        if (StepDown(NowS, OutStep, IsCpuBound()))
        {
            return EAction::StepDown;
        }
        BelowSinceS = NowS; // at the floor: do not retry every sample
        return EAction::None;
    }
    if (bHeadroom && NowS - HeadroomSinceS >= UpHoldS - 1.0e-6 && NowS >= UpBlockedUntilS
        && NowS - LastDownS >= UpBlockAfterDownS - 1.0e-6)
    {
        if (StepUp(NowS, OutStep))
        {
            return EAction::StepUp;
        }
    }
    return EAction::None;
}

// ============================================================================================
// USaskartaPerfGovernor: the engine side
// ============================================================================================

namespace SaskartaPerfGovernorLocal
{
    constexpr float TransientPIEFpsCap = 60.f;
    constexpr int32 TransientPIEQualityCeiling = 2;
    constexpr int32 PIEQualityGroupCount = 7;
    static const TCHAR* PIEQualityCVars[PIEQualityGroupCount] = {
        TEXT("sg.ShadowQuality"), TEXT("sg.GlobalIlluminationQuality"), TEXT("sg.ReflectionQuality"),
        TEXT("sg.EffectsQuality"), TEXT("sg.FoliageQuality"), TEXT("sg.ViewDistanceQuality"), TEXT("sg.AntiAliasingQuality")
    };

    static TArray<int32> ReadPIEQualityGroups()
    {
        TArray<int32> Out;
        Out.Reserve(PIEQualityGroupCount);
        for (const TCHAR* Name : PIEQualityCVars)
        {
            IConsoleVariable* CVar = IConsoleManager::Get().FindConsoleVariable(Name);
            if (!CVar)
            {
                Out.Reset();
                return Out;
            }
            Out.Add(CVar->GetInt());
        }
        return Out;
    }

    static void SetPIEQualityGroups(Scalability::FQualityLevels& Levels, const TArray<int32>& Values)
    {
        check(Values.Num() == PIEQualityGroupCount);
        Levels.SetShadowQuality(Values[0]);
        Levels.SetGlobalIlluminationQuality(Values[1]);
        Levels.SetReflectionQuality(Values[2]);
        Levels.SetEffectsQuality(Values[3]);
        Levels.SetFoliageQuality(Values[4]);
        Levels.SetViewDistanceQuality(Values[5]);
        Levels.SetAntiAliasingQuality(Values[6]);
    }

    static EConsoleVariableFlags CVarWritePriority(const IConsoleVariable& CVar)
    {
        const uint32 Current = static_cast<uint32>(CVar.GetFlags()) & static_cast<uint32>(ECVF_SetByMask);
        return static_cast<EConsoleVariableFlags>(FMath::Max(Current, static_cast<uint32>(ECVF_SetByScalability)));
    }

    struct FSharedPIEFpsCap
    {
        TSet<const UWorld*> ActiveWorlds;
        FSaskartaTransientPIEFpsCap Policy;
        uint32 SavedPriority = 0;
        FSaskartaTransientPIEQualityCap QualityPolicy;
        bool bOwnsTemporaryQualityLevels = false;

        void RegisterWorld(UWorld* World)
        {
            if (!World || World->WorldType != EWorldType::PIE || ActiveWorlds.Contains(World))
            {
                return;
            }
            ActiveWorlds.Add(World);
            if (ActiveWorlds.Num() != 1)
            {
                return;
            }

            IConsoleVariable* MaxFps = IConsoleManager::Get().FindConsoleVariable(TEXT("t.MaxFPS"));
            if (MaxFps && Policy.Begin(MaxFps->GetFloat(), TransientPIEFpsCap))
            {
                SavedPriority = static_cast<uint32>(MaxFps->GetFlags()) & static_cast<uint32>(ECVF_SetByMask);
                MaxFps->Set(Policy.AppliedFps, CVarWritePriority(*MaxFps));
                UE_LOG(LogSaskartaPerf, Log, TEXT("PIE headroom: temporarily capped t.MaxFPS at %.0f (restores when all PIE worlds close unless changed externally)."), Policy.AppliedFps);
            }

            ApplyQualityCeiling();
        }

        void UnregisterWorld(const UWorld* World)
        {
            if (!World || ActiveWorlds.Remove(World) == 0 || ActiveWorlds.Num() != 0)
            {
                return;
            }

            RestoreFpsCap();
            RestoreQualityCeiling();
        }

        void ApplyQualityCeiling()
        {
            if (Scalability::IsTemporaryQualityLevelActive())
            {
                UE_LOG(LogSaskartaPerf, Warning, TEXT("PIE headroom: left scalability untouched because another temporary quality owner is active."));
                return;
            }

            const TArray<int32> Current = ReadPIEQualityGroups();
            if (Current.Num() != PIEQualityGroupCount || !QualityPolicy.Begin(Current, TransientPIEQualityCeiling))
            {
                return;
            }

            Scalability::FQualityLevels Capped = Scalability::GetQualityLevels();
            SetPIEQualityGroups(Capped, QualityPolicy.AppliedLevels);
            // Capture was taken above before BeginIntro can start the loading budget. This
            // engine helper keeps that baseline out of user settings and restores it on teardown.
            Scalability::ToggleTemporaryQualityLevels(true);
            Scalability::SetQualityLevels(Capped, true);
            bOwnsTemporaryQualityLevels = true;
            UE_LOG(LogSaskartaPerf, Log, TEXT("PIE headroom: temporarily capped scalability groups at High (2): Sh%d GI%d Rf%d Fx%d Fo%d VD%d AA%d."),
                Capped.ShadowQuality, Capped.GlobalIlluminationQuality, Capped.ReflectionQuality,
                Capped.EffectsQuality, Capped.FoliageQuality, Capped.ViewDistanceQuality, Capped.AntiAliasingQuality);
        }

        void RestoreFpsCap()
        {
            if (Policy.CanRestore(ActiveWorlds.Num()))
            {
                if (IConsoleVariable* MaxFps = IConsoleManager::Get().FindConsoleVariable(TEXT("t.MaxFPS")))
                {
                    float RestoreValue = 0.f;
                    if (Policy.GetRestoreValue(MaxFps->GetFloat(), RestoreValue))
                    {
                        const uint32 RestorePriority = FMath::Max(SavedPriority, static_cast<uint32>(ECVF_SetByScalability));
                        MaxFps->Set(RestoreValue, static_cast<EConsoleVariableFlags>(RestorePriority));
                        UE_LOG(LogSaskartaPerf, Log, TEXT("PIE headroom: restored t.MaxFPS to %.2f."), RestoreValue);
                    }
                    else
                    {
                        UE_LOG(LogSaskartaPerf, Log, TEXT("PIE headroom: kept externally changed t.MaxFPS at %.2f."), MaxFps->GetFloat());
                    }
                }
                Policy.bOwnsCap = false;
            }
        }

        void RestoreQualityCeiling()
        {
            if (!QualityPolicy.CanRestore(ActiveWorlds.Num()) || !bOwnsTemporaryQualityLevels)
            {
                return;
            }

            const TArray<int32> Current = ReadPIEQualityGroups();
            TArray<int32> RestoreValues;
            QualityPolicy.GetRestoreLevels(Current, RestoreValues);
            const TArray<int32> Original = QualityPolicy.PreviousLevels;

            // Toggle off restores the engine's backed-up baseline. If a group changed while PIE
            // was active, reapply only the merged result so that external group survives.
            Scalability::ToggleTemporaryQualityLevels(false);
            if (RestoreValues.Num() == PIEQualityGroupCount && RestoreValues != Original)
            {
                Scalability::FQualityLevels Merged = Scalability::GetQualityLevels();
                SetPIEQualityGroups(Merged, RestoreValues);
                Scalability::SetQualityLevels(Merged, true);
            }
            bOwnsTemporaryQualityLevels = false;
            QualityPolicy = FSaskartaTransientPIEQualityCap();
            UE_LOG(LogSaskartaPerf, Log, TEXT("PIE headroom: restored owned scalability groups; externally changed groups were preserved."));
        }

    };

    static FSharedPIEFpsCap& SharedPIEFpsCap()
    {
        static FSharedPIEFpsCap Cap;
        return Cap;
    }

    static void SetCVarIfChanged(const TCHAR* Name, float Value, EConsoleVariableFlags Priority)
    {
        if (IConsoleVariable* V = IConsoleManager::Get().FindConsoleVariable(Name))
        {
            if (!FMath::IsNearlyEqual(V->GetFloat(), Value, 0.001f))
            {
                V->Set(*FString::Printf(TEXT("%.3f"), Value), Priority);
            }
        }
    }
}

USaskartaPerfGovernor* USaskartaPerfGovernor::GetPerfGovernor(const UObject* WorldContext)
{
    const UWorld* World = GEngine ? GEngine->GetWorldFromContextObject(WorldContext, EGetWorldErrorMode::ReturnNull) : nullptr;
    const UGameInstance* GI = World ? World->GetGameInstance() : nullptr;
    return GI ? GI->GetSubsystem<USaskartaPerfGovernor>() : nullptr;
}

bool USaskartaPerfGovernor::IsAllowedHere() const
{
    return USaskartaGameUserSettings::IsPerfAutomationAllowed();
}

void USaskartaPerfGovernor::Initialize(FSubsystemCollectionBase& Collection)
{
    Super::Initialize(Collection);
    SettingsHandle = USaskartaGameUserSettings::OnUserSettingsApplying().AddUObject(this, &USaskartaPerfGovernor::OnUserSettingsApplying);
    MapHandle = FCoreUObjectDelegates::PostLoadMapWithWorld.AddUObject(this, &USaskartaPerfGovernor::OnPostLoadMap);
    WorldCleanupHandle = FWorldDelegates::OnWorldCleanup.AddUObject(this, &USaskartaPerfGovernor::OnWorldCleanup);
    if (UGameInstance* GI = GetGameInstance())
    {
        ApplyTransientPIEFpsCap(GI->GetWorld());
    }

    if (!IsAllowedHere())
    {
        UE_LOG(LogSaskartaPerf, Log, TEXT("Adaptive quality and auto-detect are off in the editor (saskarta.perf.AllowInEditor 0)."));
        return;
    }
    CachedRefreshHz = USaskartaHardwareProfileLibrary::GatherHardwareSpecs().RefreshHz;
    LastSampleS = FPlatformTime::Seconds();
    LastFrameCounter = GFrameCounter;
    GraceUntilS = LastSampleS + 10.0;
    FTimerManager& Timers = GetGameInstance()->GetTimerManager();
    Timers.SetTimer(StartupTimer, this, &USaskartaPerfGovernor::OnStartupTimer, 0.5f, false);
    Timers.SetTimer(SampleTimer, this, &USaskartaPerfGovernor::OnSampleTimer, 0.5f, true);
}

void USaskartaPerfGovernor::Deinitialize()
{
    if (UGameInstance* GI = GetGameInstance())
    {
        GI->GetTimerManager().ClearTimer(SampleTimer);
        GI->GetTimerManager().ClearTimer(StartupTimer);
    }
    USaskartaGameUserSettings::OnUserSettingsApplying().Remove(SettingsHandle);
    FCoreUObjectDelegates::PostLoadMapWithWorld.Remove(MapHandle);
    FWorldDelegates::OnWorldCleanup.Remove(WorldCleanupHandle);
    RestoreTransientPIEFpsCap();
    DropAllSteps();
    Super::Deinitialize();
}

void USaskartaPerfGovernor::OnStartupTimer()
{
    if (USaskartaGameUserSettings* Settings = USaskartaGameUserSettings::GetSaskartaSettings())
    {
        Settings->RunAutoDetectIfNeeded();
    }
    bNeedsRebaseline = true;
}

void USaskartaPerfGovernor::OnUserSettingsApplying()
{
    DropAllSteps();
}

void USaskartaPerfGovernor::OnPostLoadMap(UWorld* World)
{
    ApplyTransientPIEFpsCap(World);
    GraceUntilS = FPlatformTime::Seconds() + 10.0;
    Core.Invalidate();
}

void USaskartaPerfGovernor::ApplyTransientPIEFpsCap(UWorld* World)
{
    if (!World || World->WorldType != EWorldType::PIE || World->GetGameInstance() != GetGameInstance())
    {
        return;
    }
    if (RegisteredPIEWorld.Get() == World)
    {
        return;
    }
    if (UWorld* PreviousWorld = RegisteredPIEWorld.Get())
    {
        SaskartaPerfGovernorLocal::SharedPIEFpsCap().UnregisterWorld(PreviousWorld);
    }
    RegisteredPIEWorld = World;
    SaskartaPerfGovernorLocal::SharedPIEFpsCap().RegisterWorld(World);
}

void USaskartaPerfGovernor::RestoreTransientPIEFpsCap()
{
    if (UWorld* World = RegisteredPIEWorld.Get())
    {
        // Loading is nested inside the PIE cap (e.g. editor 120 -> PIE 60 -> loading 30).
        // World/subsystem teardown order is not guaranteed. Release the inner owner first,
        // or 30 looks like an external edit and the original editor cap is lost when the
        // loading subsystem subsequently restores 60. This is idempotent if it ran earlier.
        if (UGameInstance* GI = GetGameInstance())
        {
            if (USaskartaLoadingBudget* LoadingBudget = GI->GetSubsystem<USaskartaLoadingBudget>())
            {
                LoadingBudget->RestoreForWorldTeardown();
            }
        }
        SaskartaPerfGovernorLocal::SharedPIEFpsCap().UnregisterWorld(World);
    }
    RegisteredPIEWorld.Reset();
}

void USaskartaPerfGovernor::OnWorldCleanup(UWorld* World, bool bSessionEnded, bool bCleanupResources)
{
    if (World && World->WorldType == EWorldType::PIE && World->GetGameInstance() == GetGameInstance() && RegisteredPIEWorld.Get() == World)
    {
        RestoreTransientPIEFpsCap();
    }
}

void USaskartaPerfGovernor::SetSuspended(FName Reason, bool bSuspend)
{
    // Task LOADBUDGET: the loading screen's suspension also drives the loading budget
    // (PC_Saskarta.BeginIntro sets "Loading", BeginTitle clears it).
    static const FName LoadingReason(TEXT("Loading"));
    if (Reason == LoadingReason)
    {
        if (USaskartaLoadingBudget* Budget = GetGameInstance() ? GetGameInstance()->GetSubsystem<USaskartaLoadingBudget>() : nullptr)
        {
            if (bSuspend)
            {
                Budget->BeginLoadingBudget(LoadingReason);
            }
            else
            {
                Budget->EndLoadingBudget(LoadingReason);
            }
        }
    }
    if (bSuspend)
    {
        SuspendReasons.Add(Reason);
    }
    else
    {
        SuspendReasons.Remove(Reason);
    }
    Core.Invalidate();
}

bool USaskartaPerfGovernor::IsActive() const
{
    return bWasEnabled && SuspendReasons.Num() == 0 && IsAllowedHere();
}

void USaskartaPerfGovernor::ResetToUserSettings()
{
    DropAllSteps();
}

bool USaskartaPerfGovernor::CanSample(FString& OutWhy) const
{
    if (SuspendReasons.Num() > 0)
    {
        OutWhy = TEXT("suspended");
        return false;
    }
    if (FPlatformTime::Seconds() < GraceUntilS)
    {
        OutWhy = TEXT("map load grace");
        return false;
    }
    const UGameInstance* GI = GetGameInstance();
    UWorld* World = GI ? GI->GetWorld() : nullptr;
    if (!World || !World->HasBegunPlay())
    {
        OutWhy = TEXT("no world");
        return false;
    }
    if (UGameplayStatics::IsGamePaused(World))
    {
        OutWhy = TEXT("paused");
        return false;
    }
    if (!FApp::HasFocus())
    {
        OutWhy = TEXT("unfocused");
        return false;
    }
    const APlayerController* PC = GI->GetFirstLocalPlayerController(World);
    if (PC && PC->bCinematicMode)
    {
        OutWhy = TEXT("cinematic");
        return false;
    }
    return true;
}

void USaskartaPerfGovernor::Rebaseline()
{
    const USaskartaGameUserSettings* Settings = USaskartaGameUserSettings::GetSaskartaSettings();
    if (!Settings)
    {
        return;
    }
    FSaskartaGovernorCore::FState B;
    B.ScreenPct = USaskartaHardwareProfileLibrary::ScreenPercentageFor(Settings->UpscalerMethod, Settings->UpscalerMode);
    B.Levels[FSaskartaGovernorCore::Shadow] = Settings->GetShadowQuality();
    B.Levels[FSaskartaGovernorCore::GlobalIllumination] = Settings->GetGlobalIlluminationQuality();
    B.Levels[FSaskartaGovernorCore::Reflection] = Settings->GetReflectionQuality();
    B.Levels[FSaskartaGovernorCore::ViewDistance] = Settings->GetViewDistanceQuality();
    B.Levels[FSaskartaGovernorCore::Effects] = Settings->GetVisualEffectQuality();
    B.Levels[FSaskartaGovernorCore::Foliage] = Settings->GetFoliageQuality();
    BaseFoliageDensity = FMath::Clamp(Settings->FoliageDensity, 0.25f, 1.f);
    BaseFoliageDistance = FMath::Clamp(Settings->FoliageDistance, 0.5f, 1.5f);
    Core.TargetFps = Settings->GetAdaptiveTargetFps(CachedRefreshHz);
    Core.Reset(B, FPlatformTime::Seconds());
    bNeedsRebaseline = false;
    UE_LOG(LogSaskartaPerf, Log, TEXT("Adaptive quality: target %.0f fps, baseline %.1f %% Sh%d GI%d Rf%d VD%d Fx%d Fo%d."),
        Core.TargetFps, B.ScreenPct, B.Levels[0], B.Levels[1], B.Levels[2], B.Levels[3], B.Levels[4], B.Levels[5]);
}

void USaskartaPerfGovernor::ApplyCurrent()
{
    using namespace SaskartaPerfGovernorLocal;
    const FSaskartaGovernorCore::FState& S = Core.GetCurrent();
    const FSaskartaGovernorCore::FState& B = Core.GetBaseline();

    // Resolution, at the priority the settings write it.
    SetCVarIfChanged(TEXT("r.ScreenPercentage"), S.ScreenPct, ECVF_SetByGameSetting);

    // Groups, as temporary quality levels: GameUserSettings keeps (and saves) the user's own.
    if (!S.GroupsEqual(B))
    {
        if (!Scalability::IsTemporaryQualityLevelActive())
        {
            Scalability::ToggleTemporaryQualityLevels(true);
            bOwnsTemporaryLevels = true;
        }
        Scalability::FQualityLevels L = Scalability::GetQualityLevels(); // the backed-up (user) levels
        L.SetShadowQuality(S.Levels[FSaskartaGovernorCore::Shadow]);
        L.SetGlobalIlluminationQuality(S.Levels[FSaskartaGovernorCore::GlobalIllumination]);
        L.SetReflectionQuality(S.Levels[FSaskartaGovernorCore::Reflection]);
        L.SetViewDistanceQuality(S.Levels[FSaskartaGovernorCore::ViewDistance]);
        L.SetEffectsQuality(S.Levels[FSaskartaGovernorCore::Effects]);
        L.SetFoliageQuality(S.Levels[FSaskartaGovernorCore::Foliage]);
        Scalability::SetQualityLevels(L, true);
    }
    else if (bOwnsTemporaryLevels)
    {
        Scalability::ToggleTemporaryQualityLevels(false);
        bOwnsTemporaryLevels = false;
    }

    // Grass density/distance belong to the settings class (ECVF_SetByGameSetting, above the
    // FoliageQuality group), so the foliage step scales them directly.
    const int32 FoliageSteps = FMath::Max(B.Levels[FSaskartaGovernorCore::Foliage] - S.Levels[FSaskartaGovernorCore::Foliage], 0);
    SetCVarIfChanged(TEXT("grass.DensityScale"), BaseFoliageDensity * FMath::Pow(0.7f, static_cast<float>(FoliageSteps)), ECVF_SetByGameSetting);
    SetCVarIfChanged(TEXT("grass.CullDistanceScale"), BaseFoliageDistance * FMath::Pow(0.85f, static_cast<float>(FoliageSteps)), ECVF_SetByGameSetting);

    // The tier CVars that follow shadows/view distance (VSM bias, Nanite edge length); never
    // the render-state-recreating ones.
    USaskartaGameUserSettings::ApplyTierCVars(USaskartaGameUserSettings::ComputeTierCVars(
        S.Levels[FSaskartaGovernorCore::Shadow], S.Levels[FSaskartaGovernorCore::GlobalIllumination],
        S.Levels[FSaskartaGovernorCore::ViewDistance], -1, false));
}

void USaskartaPerfGovernor::DropAllSteps()
{
    const bool bHadSteps = Core.GetDepth() > 0 || bOwnsTemporaryLevels;
    if (bOwnsTemporaryLevels)
    {
        Scalability::ToggleTemporaryQualityLevels(false);
        bOwnsTemporaryLevels = false;
    }
    if (bHadSteps && GEngine)
    {
        if (USaskartaGameUserSettings* Settings = USaskartaGameUserSettings::GetSaskartaSettings())
        {
            Settings->ApplySaskartaSettings(); // r.ScreenPercentage, grass.* back to the user's
            if (IsAllowedHere())
            {
                USaskartaGameUserSettings::ApplyTierCVars(USaskartaGameUserSettings::ComputeTierCVars(
                    Settings->GetShadowQuality(), Settings->GetGlobalIlluminationQuality(), Settings->GetViewDistanceQuality(), -1, false));
            }
        }
        UE_LOG(LogSaskartaPerf, Log, TEXT("Adaptive quality: dropped %d step(s), back to the user's settings."), Core.GetDepth());
    }
    Core.Reset(Core.GetBaseline(), FPlatformTime::Seconds());
    bNeedsRebaseline = true;
}

void USaskartaPerfGovernor::OnSampleTimer()
{
    const double Now = FPlatformTime::Seconds();
    const uint64 Frames = GFrameCounter - LastFrameCounter;
    const double Dt = Now - LastSampleS;
    LastFrameCounter = GFrameCounter;
    LastSampleS = Now;

    const USaskartaGameUserSettings* Settings = GEngine ? USaskartaGameUserSettings::GetSaskartaSettings() : nullptr;
    if (!Settings)
    {
        return; // the Saskarta settings class is not live (R43)
    }
    if (!Settings->bAdaptiveQuality)
    {
        if (bWasEnabled)
        {
            DropAllSteps();
            UE_LOG(LogSaskartaPerf, Log, TEXT("Adaptive quality: off."));
        }
        bWasEnabled = false;
        return;
    }
    if (!bWasEnabled)
    {
        bWasEnabled = true;
        bNeedsRebaseline = true;
    }
    if (!FMath::IsNearlyEqual(Settings->GetAdaptiveTargetFps(CachedRefreshHz), Core.TargetFps, 0.5f))
    {
        DropAllSteps(); // the target changed (Settings row, frame cap, VSync)
    }
    if (bNeedsRebaseline)
    {
        Rebaseline();
    }

    FString Why;
    // A gap over 1.5 s means the timer did not run (pause, a long hitch): not a sample.
    if (Dt > 1.5 || Frames == 0 || !CanSample(Why))
    {
        Core.Invalidate();
        return;
    }
    const float FrameMs = static_cast<float>(Dt * 1000.0 / static_cast<double>(Frames));
    // Last-frame values; the core's 5 s median smooths them.
    const float CpuMs = FMath::Max(
        static_cast<float>(FPlatformTime::ToMilliseconds(GGameThreadTime)),
        static_cast<float>(FPlatformTime::ToMilliseconds(GRenderThreadTime)));
    const float GpuMs = static_cast<float>(FPlatformTime::ToMilliseconds(RHIGetGPUFrameCycles(0)));

    FSaskartaGovernorCore::FStep Step;
    const FSaskartaGovernorCore::EAction Action = Core.Update(Now, FrameMs, GpuMs, CpuMs, &Step);
    if (Action == FSaskartaGovernorCore::EAction::None)
    {
        return;
    }
    ApplyCurrent();
    const TCHAR* Dir = Action == FSaskartaGovernorCore::EAction::StepDown ? TEXT("DOWN") : TEXT("UP");
    if (Step.bResolution)
    {
        UE_LOG(LogSaskartaPerf, Log, TEXT("Adaptive quality %s: screen percentage %.1f -> %.1f (median frame %.1f ms, busy %.1f ms, target %.0f fps, depth %d)"),
            Dir, Step.FromPct, Step.ToPct, Step.MedianFrameMs, Step.MedianBusyMs, Core.TargetFps, Core.GetDepth());
    }
    else
    {
        UE_LOG(LogSaskartaPerf, Log, TEXT("Adaptive quality %s%s: %s %s -> %s (median frame %.1f ms, busy %.1f ms, target %.0f fps, depth %d)"),
            Dir, Step.bCpuBound ? TEXT(" (CPU-bound)") : TEXT(""), FSaskartaGovernorCore::GroupName(Step.Group),
            *USaskartaHardwareProfileLibrary::LevelName(Step.FromLevel), *USaskartaHardwareProfileLibrary::LevelName(Step.ToLevel),
            Step.MedianFrameMs, Step.MedianBusyMs, Core.TargetFps, Core.GetDepth());
    }
}

FString USaskartaPerfGovernor::DescribeState() const
{
    const FSaskartaGovernorCore::FState& S = Core.GetCurrent();
    return FString::Printf(TEXT("target %.0f fps | frame %.1f ms, GPU %.1f ms, CPU %.1f ms%s (%d samples, %d hitches dropped) | depth %d | %.1f %% Sh%d GI%d Rf%d VD%d Fx%d Fo%d%s"),
        Core.TargetFps, Core.GetMedianFrameMs(), Core.GetMedianGpuMs(), Core.GetMedianCpuMs(), Core.IsCpuBound() ? TEXT(" CPU-bound") : TEXT(""),
        Core.GetNumSamples(), Core.GetDroppedHitches(), Core.GetDepth(),
        S.ScreenPct, S.Levels[0], S.Levels[1], S.Levels[2], S.Levels[3], S.Levels[4], S.Levels[5],
        IsActive() ? TEXT("") : TEXT(" | inactive"));
}
