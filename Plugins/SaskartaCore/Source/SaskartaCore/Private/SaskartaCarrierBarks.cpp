// USaskartaCarrierBarks: see SaskartaCarrierBarks.h.

#include "SaskartaCarrierBarks.h"
#include "SaskartaEventRunner.h"
#include "SaskartaEventTypes.h"
#include "SaskartaRadioStation.h"
#include "Components/AudioComponent.h"
#include "Engine/AssetManager.h"
#include "Engine/Engine.h"
#include "Engine/StreamableManager.h"
#include "Engine/World.h"
#include "HAL/IConsoleManager.h"
#include "Kismet/GameplayStatics.h"
#include "Misc/PackageName.h"
#include "Sound/SoundBase.h"

DEFINE_LOG_CATEGORY_STATIC(LogSaskartaBarks, Log, All);

namespace SaskartaBarks
{
    static constexpr float PollS = 0.5f;
    /** First bark after the world starts, then the gap after each bark ends. */
    static constexpr float FirstDelayMinS = 40.f;
    static constexpr float FirstDelayMaxS = 70.f;
    static constexpr float GapMinS = 45.f;
    static constexpr float GapMaxS = 90.f;
    /** A refused window retries this soon (the due time stays). */
    static constexpr float RetryS = 2.f;
    /** The host must have been silent this long (the programme envelope) before a bark starts. */
    static constexpr double StationQuietS = 2.5;
    /** Quiet after the runner's last story / carrier / aux line, and after any busy Voice. */
    static constexpr float AfterVoiceS = 4.f;
    /** The next road beat must be at least bark + this away. */
    static constexpr float BeatLeadS = 6.f;
    /** "Freely driving": moving forward for this long. */
    static constexpr double MovingForS = 3.0;
    static constexpr float MinMoveMPerPoll = 0.25f; // 0.5 m/s
    /** Programme envelope above this counts as the host talking. */
    static constexpr float SpeechEnvelope = 0.01f;
    /** Not one of the last N barks. */
    static constexpr int32 RecentWindow = 10;
    static constexpr float FadeOutS = 0.25f;

    static const TCHAR* Folder = TEXT("/Game/SaskartaGaea/Audio/CarrierBarks");
    // Keep in step with SourceArt/Audio/CarrierBarks/carrier_barks.tsv.
    static const TCHAR* Lines[] =
    {
        TEXT("Terrain stable. Holding pace."),
        TEXT("Crosswind from the west. Compensating."),
        TEXT("Cell temperature nominal."),
        TEXT("Route continues. Next marker ahead."),
        TEXT("Footing loose. Shortening stride."),
        TEXT("Grade rising. Shifting load forward."),
        TEXT("Grade falling. Easing the joints."),
        TEXT("Road surface intact."),
        TEXT("Wind steady. No correction needed."),
        TEXT("Sensor glass clear enough."),
        TEXT("Dust in the intake. Filters holding."),
        TEXT("Left knee actuator warm. Within tolerance."),
        TEXT("Air temperature dropping."),
        TEXT("Loose stone ahead. Stepping around."),
        TEXT("Signal present. Reception fair."),
        TEXT("Distance logged. Counting metres."),
        TEXT("Nothing on the road behind."),
        TEXT("Gyroscopes level."),
        TEXT("Old track markings. Following them."),
        TEXT("Soft ground at the edge. Keeping to the centre."),
        TEXT("Motor rhythm even."),
        TEXT("Gravel. Reducing speed."),
        TEXT("Hull vibration normal."),
        TEXT("Air dry. Seals intact."),
        TEXT("Visibility fair. Proceeding."),
        TEXT("Rock face on the right. Clearance good."),
        TEXT("Hydraulics quiet. All legs responding."),
    };

    static TAutoConsoleVariable<int32> CVarEnabled(
        TEXT("Saskarta.CarrierBarks"), 1,
        TEXT("1: the carrier makes short random remarks while driving (over the radio music, never over speech). 0: off."));

    static FAutoConsoleCommandWithWorld CmdNow(
        TEXT("Saskarta.CarrierBarks.Now"),
        TEXT("Makes the next carrier bark due now (it still waits for a free window)."),
        FConsoleCommandWithWorldDelegate::CreateLambda([](UWorld* World)
        {
            if (USaskartaCarrierBarks* B = World ? World->GetSubsystem<USaskartaCarrierBarks>() : nullptr)
            {
                B->ForceNextBark();
            }
        }));
}

USaskartaCarrierBarks* USaskartaCarrierBarks::GetCarrierBarks(const UObject* WorldContextObject)
{
    const UWorld* World = GEngine ? GEngine->GetWorldFromContextObject(WorldContextObject, EGetWorldErrorMode::ReturnNull) : nullptr;
    return World ? World->GetSubsystem<USaskartaCarrierBarks>() : nullptr;
}

bool USaskartaCarrierBarks::DoesSupportWorldType(const EWorldType::Type WorldType) const
{
    return WorldType == EWorldType::Game || WorldType == EWorldType::PIE;
}

void USaskartaCarrierBarks::Initialize(FSubsystemCollectionBase& Collection)
{
    Collection.InitializeDependency<USaskartaEventRunner>();
    Collection.InitializeDependency<USaskartaRadioStation>();
    Super::Initialize(Collection);
}

void USaskartaCarrierBarks::Deinitialize()
{
    if (UWorld* World = GetWorld())
    {
        World->GetTimerManager().ClearTimer(PollTimer);
    }
    if (IsValid(BarkComp))
    {
        BarkComp->Stop();
    }
    BarkComp = nullptr;
    if (LoadHandle.IsValid())
    {
        LoadHandle->CancelHandle();
        LoadHandle.Reset();
    }
    Super::Deinitialize();
}

void USaskartaCarrierBarks::OnWorldBeginPlay(UWorld& InWorld)
{
    Super::OnWorldBeginPlay(InWorld);
    Barks.Reset();
    for (int32 i = 0; i < static_cast<int32>(UE_ARRAY_COUNT(SaskartaBarks::Lines)); ++i)
    {
        const FString Name = FString::Printf(TEXT("CARRIER_BARK_%02d"), i + 1);
        FBark& B = Barks.AddDefaulted_GetRef();
        B.Path = FSoftObjectPath(FString::Printf(TEXT("%s/%s.%s"), SaskartaBarks::Folder, *Name, *Name));
        B.Text = SaskartaBarks::Lines[i];
    }
    NextBarkAtS = Now() + FMath::FRandRange(SaskartaBarks::FirstDelayMinS, SaskartaBarks::FirstDelayMaxS);
    InWorld.GetTimerManager().SetTimer(PollTimer, this, &USaskartaCarrierBarks::Poll, SaskartaBarks::PollS, true);
}

double USaskartaCarrierBarks::Now() const
{
    const UWorld* World = GetWorld();
    return World ? World->GetTimeSeconds() : 0.0;
}

bool USaskartaCarrierBarks::IsBarkPlaying() const
{
    return PlayingIndex != INDEX_NONE;
}

void USaskartaCarrierBarks::ForceNextBark()
{
    NextBarkAtS = Now();
}

void USaskartaCarrierBarks::ScheduleNext(double FromS)
{
    NextBarkAtS = FromS + FMath::FRandRange(SaskartaBarks::GapMinS, SaskartaBarks::GapMaxS);
}

void USaskartaCarrierBarks::StartLoad()
{
    // Only the packages that exist: the WAVs are imported separately, and a missing one must stay silent.
    bLoadStarted = true;
    TArray<FSoftObjectPath> Paths;
    for (const FBark& B : Barks)
    {
        if (FPackageName::DoesPackageExist(B.Path.GetLongPackageName()))
        {
            Paths.Add(B.Path);
        }
    }
    UE_LOG(LogSaskartaBarks, Log, TEXT("carrier barks: %d of %d takes imported"), Paths.Num(), Barks.Num());
    if (!Paths.IsEmpty() && UAssetManager::IsInitialized())
    {
        LoadHandle = UAssetManager::GetStreamableManager().RequestAsyncLoad(Paths, FStreamableDelegate());
    }
}

bool USaskartaCarrierBarks::CanStartBark(const USaskartaEventRunner* R, const USaskartaRadioStation* Station, float DurationS) const
{
    const FName Flow = R->GetFlowState();
    if (Flow != FName(TEXT("Playing")) && Flow != FName(TEXT("Carrier")))
    {
        return false;
    }
    if (R->IsVoiceBusy() || R->IsCinematicActive() || R->IsHoldingInput() || R->IsPromptActive() || R->IsStorySubtitleActive())
    {
        return false;
    }
    if (R->SecondsSinceVoice() < SaskartaBarks::AfterVoiceS || R->GetSecondsToNextBeat() < DurationS + SaskartaBarks::BeatLeadS)
    {
        return false;
    }
    const double T = Now();
    if (T - LastStoryBusyS < SaskartaBarks::AfterVoiceS || MovingSinceS < 0.0 || T - MovingSinceS < SaskartaBarks::MovingForS)
    {
        return false;
    }
    if (Station)
    {
        // The host's speech is never talked over; a song or the static bed is (no duck, no pause).
        if (Station->IsRecallPlaying() || Station->IsRadioForcedOn() || T - LastStationSpeechS < SaskartaBarks::StationQuietS)
        {
            return false;
        }
    }
    return true;
}

void USaskartaCarrierBarks::Poll()
{
    UWorld* World = GetWorld();
    if (!World || World->IsPaused())
    {
        return;
    }
    const double T = Now();
    USaskartaEventRunner* R = World->GetSubsystem<USaskartaEventRunner>();
    USaskartaRadioStation* Station = World->GetSubsystem<USaskartaRadioStation>();
    const bool bStationSpeaking = Station && Station->GetProgrammeEnvelope() > SaskartaBarks::SpeechEnvelope;
    if (bStationSpeaking)
    {
        LastStationSpeechS = T;
    }
    const bool bStoryBusy = R && (R->IsVoiceBusy() || R->IsCinematicActive() || R->IsStorySubtitleActive());
    if (bStoryBusy)
    {
        LastStoryBusyS = T;
    }
    // Freely driving: the road m moves forward.
    const float RoadM = R ? R->GetRoadM() : -1.f;
    if (RoadM >= 0.f && LastRoadM >= 0.f && RoadM - LastRoadM >= SaskartaBarks::MinMoveMPerPoll)
    {
        if (MovingSinceS < 0.0) MovingSinceS = T;
    }
    else
    {
        MovingSinceS = -1.0;
    }
    LastRoadM = RoadM;

    // A bark in progress: yield at once to the host's speech or any story voice / cinematic.
    if (PlayingIndex != INDEX_NONE)
    {
        if (bStationSpeaking || bStoryBusy)
        {
            bStationHeardDuringBark |= bStationSpeaking;
            EndBark(true);
        }
        else if (T >= BarkEndS || !IsValid(BarkComp) || !BarkComp->IsPlaying())
        {
            EndBark(false);
        }
        return;
    }
    if (!R || SaskartaBarks::CVarEnabled.GetValueOnGameThread() == 0 || T < NextBarkAtS)
    {
        return;
    }
    if (!bLoadStarted)
    {
        StartLoad();
    }
    // The loaded barks, not among the recent ones (the oldest recent ones come back when all are recent).
    TArray<int32> Ready;
    for (int32 i = 0; i < Barks.Num(); ++i)
    {
        if (Cast<USoundBase>(Barks[i].Path.ResolveObject()))
        {
            Ready.Add(i);
        }
    }
    if (Ready.IsEmpty())
    {
        NextBarkAtS = T + (LoadHandle.IsValid() && !LoadHandle->HasLoadCompleted() ? SaskartaBarks::RetryS : 60.f);
        return;
    }
    const int32 Window = FMath::Min(SaskartaBarks::RecentWindow, Ready.Num() - 1);
    TArray<int32> Fresh = Ready.FilterByPredicate([this, Window](int32 i)
    {
        const int32 Pos = Recent.Find(i);
        return Pos == INDEX_NONE || Pos < Recent.Num() - Window;
    });
    if (Fresh.IsEmpty())
    {
        Fresh = Ready;
    }
    const int32 Pick = Fresh[FMath::RandRange(0, Fresh.Num() - 1)];
    USoundBase* Sound = Cast<USoundBase>(Barks[Pick].Path.ResolveObject());
    const float Dur = Sound ? Sound->GetDuration() : 0.f;
    if (!Sound || !FMath::IsFinite(Dur) || Dur <= 0.f || Dur > 15.f)
    {
        NextBarkAtS = T + SaskartaBarks::RetryS;
        return;
    }
    if (!CanStartBark(R, Station, Dur))
    {
        NextBarkAtS = T + SaskartaBarks::RetryS;
        return;
    }
    PlayBark(Pick);
}

void USaskartaCarrierBarks::PlayBark(int32 Index)
{
    USoundBase* Sound = Cast<USoundBase>(Barks[Index].Path.ResolveObject());
    if (!Sound)
    {
        return;
    }
    // A plain 2D voice: no Voice channel, no OnStoryBusyChanged, so the station is neither ducked nor paused.
    BarkComp = UGameplayStatics::CreateSound2D(this, Sound, 1.f, 1.f, 0.f, nullptr, false, true);
    if (!BarkComp)
    {
        return;
    }
    BarkComp->Play();
    const float Dur = Sound->GetDuration();
    PlayingIndex = Index;
    BarkEndS = Now() + Dur;
    bStationHeardDuringBark = false;
    Recent.Remove(Index);
    Recent.Add(Index);
    if (Recent.Num() > 32)
    {
        Recent.RemoveAt(0);
    }
    if (USaskartaEventRunner* R = USaskartaEventRunner::GetEventRunner(this))
    {
        FSaskartaSubtitle Sub;
        Sub.LineId = FName(*FString::Printf(TEXT("CARRIER_BARK_%02d"), Index + 1));
        Sub.Speaker = FName(TEXT("CARRIER"));
        Sub.English = FText::FromString(TEXT("CARRIER: ") + Barks[Index].Text);
        Sub.DurationS = Dur;
        R->ShowStationSubtitle(Sub);
    }
    UE_LOG(LogSaskartaBarks, Log, TEXT("carrier bark %02d (%.1f s): %s"), Index + 1, Dur, *Barks[Index].Text);
}

void USaskartaCarrierBarks::EndBark(bool bFade)
{
    if (IsValid(BarkComp))
    {
        if (bFade && BarkComp->IsPlaying())
        {
            BarkComp->FadeOut(SaskartaBarks::FadeOutS, 0.f);
        }
        else
        {
            BarkComp->Stop();
        }
    }
    BarkComp = nullptr;
    // Leave the caption alone if the host or a story line has taken it over.
    USaskartaEventRunner* R = USaskartaEventRunner::GetEventRunner(this);
    if (R && !bStationHeardDuringBark && !R->IsStorySubtitleActive() && Now() - LastStationSpeechS >= SaskartaBarks::StationQuietS)
    {
        R->HideStationSubtitle();
    }
    PlayingIndex = INDEX_NONE;
    BarkEndS = -1.0;
    ScheduleNext(Now());
}
