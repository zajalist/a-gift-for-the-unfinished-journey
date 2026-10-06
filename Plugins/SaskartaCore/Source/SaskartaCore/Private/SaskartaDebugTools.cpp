// Debug mode support: beat resets, the event log tail, dotted console commands (README_Debug.md).

#include "SaskartaDebugTools.h"
#include "SaskartaEventRunner.h"
#include "SaskartaStoryAsset.h"

#include "Engine/World.h"
#include "GameFramework/PlayerController.h"
#include "HAL/IConsoleManager.h"
#include "Misc/DateTime.h"
#include "Misc/OutputDevice.h"
#include "Misc/OutputDeviceRedirector.h"
#include "Misc/ScopeLock.h"

DEFINE_LOG_CATEGORY_STATIC(LogSaskartaDebug, Log, All);

// ============================================================================ runner: one-shot resets

bool USaskartaEventRunner::ResetBeat(FName BeatId)
{
    const bool bWasFired = FiredBeats.Remove(BeatId) > 0;
    LastFiredS.Remove(BeatId);
    // The runner fires a road beat when the high-water mark (the lowest UE m reached) passes it.
    // Rewinding the mark to the pawn makes every unfired beat between here and the old mark live again.
    if (CurrentUeM >= 0.f)
    {
        HighWaterUeM = CurrentUeM;
    }
    UE_LOG(LogSaskartaDebug, Log, TEXT("debug: reset %s (was fired %d), high-water -> %.0f m"), *BeatId.ToString(), bWasFired ? 1 : 0, HighWaterUeM);
    return bWasFired;
}

void USaskartaEventRunner::ResetAllBeats()
{
    // In memory only: the Saskarta_Run slot (Continue) is never written here.
    const int32 N = FiredBeats.Num();
    FiredBeats.Reset();
    LastFiredS.Reset();
    InterruptedBeatId = NAME_None;
    HighWaterUeM = CurrentUeM >= 0.f ? CurrentUeM : TNumericLimits<float>::Max();
    UE_LOG(LogSaskartaDebug, Log, TEXT("debug: reset all beats (%d were fired), high-water -> %.0f m"), N, HighWaterUeM);
}

bool USaskartaEventRunner::ArmBeat(FName BeatId, float LeadM)
{
    const FSaskartaBeatDef* B = Story ? Story->FindBeat(BeatId) : nullptr;
    if (!B)
    {
        UE_LOG(LogSaskartaDebug, Warning, TEXT("debug: arm %s: no such beat"), *BeatId.ToString());
        return false;
    }
    FiredBeats.Remove(BeatId);
    LastFiredS.Remove(BeatId);

    const FSaskartaEventTrigger& Tr = B->Trigger;
    if (Tr.Type == ESaskartaTriggerType::RoadPass || Tr.Type == ESaskartaTriggerType::RoadPassHuman)
    {
        const float BeatRoadM = Tr.RoadM >= 0.f ? Tr.RoadM : FSaskartaEventLogic::RoadMFromUeM(Story->RoadMToUeM, Tr.UeDistanceM);
        const float BeatUeM = Tr.UeDistanceM >= 0.f ? Tr.UeDistanceM : FSaskartaEventLogic::UeMFromRoadM(Story->RoadMToUeM, BeatRoadM);
        const float AtRoadM = FSaskartaEventLogic::ArmRoadM(BeatRoadM, LeadM);
        if (!TeleportToRoadM(AtRoadM))
        {
            UE_LOG(LogSaskartaDebug, Warning, TEXT("debug: arm %s: cannot teleport to road %.0f m (no road, pawn or story)"), *BeatId.ToString(), AtRoadM);
            return false;
        }
        // Beats behind the carrier stay fired (as GoTo does); this one, and any unfired beat ahead, is live.
        FSaskartaEventLogic::MarkFiredUpTo(Story->Beats, CurrentUeM, FiredBeats);
        FSaskartaEventLogic::RearmConnectedDebugBeats(BeatId, FiredBeats, LastFiredS);
        HighWaterUeM = FSaskartaEventLogic::ArmHighWaterUeM(BeatUeM, CurrentUeM);
        UE_LOG(LogSaskartaDebug, Log, TEXT("debug: armed %s at road %.0f m (carrier at %.0f m, high-water %.1f / beat %.1f UE m)"),
            *BeatId.ToString(), BeatRoadM, AtRoadM, HighWaterUeM, BeatUeM);
        return true;
    }
    if (Tr.Type == ESaskartaTriggerType::Flow)
    {
        UE_LOG(LogSaskartaDebug, Log, TEXT("debug: armed %s: fires on the next ReportFlow %s (Saskarta.Beat %s fires it now)"),
            *BeatId.ToString(), *Tr.FlowEvent.ToString(), *BeatId.ToString());
        return true;
    }
    UE_LOG(LogSaskartaDebug, Log, TEXT("debug: armed %s: fires on its next trigger (type %d)"), *BeatId.ToString(), static_cast<int32>(Tr.Type));
    return true;
}

// ============================================================================ log tail

namespace SaskartaDebug
{
    /** Keeps the last lines of the story/station log categories. */
    class FEventLogTail : public FOutputDevice
    {
    public:
        static constexpr int32 Capacity = 64;

        virtual void Serialize(const TCHAR* V, ELogVerbosity::Type Verbosity, const FName& Category) override
        {
            static const FName Events(TEXT("LogSaskartaEvents"));
            static const FName Station(TEXT("LogSaskartaStation"));
            static const FName Debug(TEXT("LogSaskartaDebug"));
            static const FName Look(TEXT("LogSaskartaLook"));
            if (Category != Events && Category != Station && Category != Debug && Category != Look)
            {
                return;
            }
            const FDateTime T = FDateTime::Now();
            FString Line = FString::Printf(TEXT("%02d:%02d:%02d %s%s"), T.GetHour(), T.GetMinute(), T.GetSecond(),
                Category == Station ? TEXT("[station] ") : (Category == Look ? TEXT("[look] ") : TEXT("")), V);
            const ELogVerbosity::Type Level = static_cast<ELogVerbosity::Type>(Verbosity & ELogVerbosity::VerbosityMask);
            if (Level == ELogVerbosity::Warning || Level == ELogVerbosity::Error)
            {
                Line = TEXT("! ") + Line;
            }
            FScopeLock Lock(&Guard);
            Lines.Add(MoveTemp(Line));
            if (Lines.Num() > Capacity)
            {
                Lines.RemoveAt(0, Lines.Num() - Capacity);
            }
        }

        virtual bool CanBeUsedOnAnyThread() const override { return true; }

        FString Tail(int32 N)
        {
            FScopeLock Lock(&Guard);
            const int32 Start = FMath::Max(0, Lines.Num() - FMath::Max(1, N));
            FString Out;
            for (int32 i = Start; i < Lines.Num(); ++i)
            {
                if (!Out.IsEmpty())
                {
                    Out += TEXT("\n");
                }
                Out += Lines[i];
            }
            return Out;
        }

    private:
        FCriticalSection Guard;
        TArray<FString> Lines;
    };

    static FEventLogTail* GTail = nullptr;

    static USaskartaEventRunner* RunnerFor(const UObject* WorldContext)
    {
        return USaskartaEventRunner::GetEventRunner(WorldContext);
    }
}

void USaskartaDebugLibrary::EnsureLogCapture()
{
    if (!SaskartaDebug::GTail && GLog)
    {
        // Leaked on purpose: it lives until exit, like the other process-wide output devices.
        SaskartaDebug::GTail = new SaskartaDebug::FEventLogTail();
        GLog->AddOutputDevice(SaskartaDebug::GTail);
        UE_LOG(LogSaskartaDebug, Log, TEXT("debug: event log capture on"));
    }
}

FString USaskartaDebugLibrary::GetRecentEventLog(int32 MaxLines)
{
    EnsureLogCapture();
    return SaskartaDebug::GTail ? SaskartaDebug::GTail->Tail(MaxLines) : FString();
}

bool USaskartaDebugLibrary::ResetBeat(const UObject* WorldContext, FName BeatId)
{
    USaskartaEventRunner* R = SaskartaDebug::RunnerFor(WorldContext);
    return R && R->ResetBeat(BeatId);
}

void USaskartaDebugLibrary::ResetAllBeats(const UObject* WorldContext)
{
    if (USaskartaEventRunner* R = SaskartaDebug::RunnerFor(WorldContext))
    {
        R->ResetAllBeats();
    }
}

bool USaskartaDebugLibrary::ArmBeat(const UObject* WorldContext, FName BeatId, float LeadM)
{
    USaskartaEventRunner* R = SaskartaDebug::RunnerFor(WorldContext);
    return R && R->ArmBeat(BeatId, LeadM);
}

FName USaskartaDebugLibrary::GetRunningBeat(const UObject* WorldContext)
{
    const USaskartaEventRunner* R = SaskartaDebug::RunnerFor(WorldContext);
    return R ? R->GetRunningBeatId() : NAME_None;
}

// ============================================================================ dotted console commands

namespace SaskartaDebug
{
    /** Runs a cheat-manager exec function (CM_Saskarta) on the first local player controller. */
    static void ForwardToCheatManager(UWorld* World, const FString& Command)
    {
        USaskartaDebugLibrary::EnsureLogCapture();
        APlayerController* PC = World ? World->GetFirstPlayerController() : nullptr;
        if (!PC)
        {
            UE_LOG(LogSaskartaDebug, Warning, TEXT("debug: no player controller (start PIE or a game world)"));
            return;
        }
        PC->ConsoleCommand(Command, true);
    }

    static FAutoConsoleCommandWithWorldAndArgs CmdDebug(TEXT("Saskarta.Debug"),
        TEXT("Saskarta.Debug: toggle the debug menu (same as F9 or the SaskartaDebug cheat)."),
        FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>& Args, UWorld* World)
        {
            ForwardToCheatManager(World, TEXT("SaskartaDebug"));
        }));

    static FAutoConsoleCommandWithWorldAndArgs CmdTp(TEXT("Saskarta.TP"),
        TEXT("Saskarta.TP <road_m | beat_id>: teleport 30 m before that point on the road and re-arm its beat."),
        FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>& Args, UWorld* World)
        {
            ForwardToCheatManager(World, TEXT("SaskartaTP ") + (Args.Num() > 0 ? Args[0] : FString(TEXT("0"))));
        }));

    static FAutoConsoleCommandWithWorldAndArgs CmdBeat(TEXT("Saskarta.Beat"),
        TEXT("Saskarta.Beat <beat_id>: trigger that beat now (forced)."),
        FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>& Args, UWorld* World)
        {
            if (Args.Num() > 0)
            {
                ForwardToCheatManager(World, TEXT("SaskartaBeat ") + Args[0]);
            }
        }));

    static FAutoConsoleCommandWithWorldAndArgs CmdSkip(TEXT("Saskarta.Skip"),
        TEXT("Saskarta.Skip: skip the current cinematic (any skip rule)."),
        FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>& Args, UWorld* World)
        {
            ForwardToCheatManager(World, TEXT("SaskartaSkip"));
        }));

    static FAutoConsoleCommandWithWorldAndArgs CmdReset(TEXT("Saskarta.ResetBeats"),
        TEXT("Saskarta.ResetBeats: clear every one-shot beat flag (beats ahead fire again)."),
        FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>& Args, UWorld* World)
        {
            USaskartaDebugLibrary::EnsureLogCapture();
            if (USaskartaEventRunner* R = World ? World->GetSubsystem<USaskartaEventRunner>() : nullptr)
            {
                R->ResetAllBeats(); // in memory; the Continue save is untouched
            }
        }));

    static FAutoConsoleCommandWithWorldAndArgs CmdArm(TEXT("Saskarta.Arm"),
        TEXT("Saskarta.Arm <beat_id> [lead_m=30]: re-arm one beat (road beats: teleport lead_m before it; B01: fires on the next first-boot flow report)."),
        FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>& Args, UWorld* World)
        {
            USaskartaDebugLibrary::EnsureLogCapture();
            USaskartaEventRunner* R = World ? World->GetSubsystem<USaskartaEventRunner>() : nullptr;
            if (R && Args.Num() > 0)
            {
                R->ArmBeat(FName(*Args[0]), Args.Num() > 1 ? FCString::Atof(*Args[1]) : 30.f);
            }
        }));
}
