#include "SaskartaAutopilot.h"

#include "SaskartaEarlyStorm.h"
#include "SaskartaElderWalk.h"
#include "SaskartaEventRunner.h"
#include "SaskartaEventVolume.h"
#include "SaskartaMotorResonance.h"
#include "SaskartaPower.h"
#include "SaskartaRadioStation.h"
#include "SaskartaRouteLog.h"
#include "SaskartaSteleScanner.h"
#include "SaskartaStoryAsset.h"

#include "Components/SplineComponent.h"
#include "Engine/Engine.h"
#include "Engine/GameViewportClient.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "GameFramework/Character.h"
#include "GameFramework/CharacterMovementComponent.h"
#include "GameFramework/PlayerController.h"
#include "HAL/FileManager.h"
#include "HAL/IConsoleManager.h"
#include "HAL/PlatformTime.h"
#include "InputKeyEventArgs.h"
#include "Misc/CommandLine.h"
#include "Misc/DateTime.h"
#include "Misc/FileHelper.h"
#include "Misc/OutputDeviceNull.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"

DEFINE_LOG_CATEGORY_STATIC(LogSaskartaAutopilot, Log, All);

namespace SaskartaAutopilot
{
    static const FName Playing(TEXT("Playing"));
    static const FName CarrierFlow(TEXT("Carrier"));
    static const FName Human(TEXT("Human"));
    static const FName Title(TEXT("Title"));
    static const FName Booting(TEXT("Booting"));

    constexpr float LowCharge = 18.f;
    constexpr float FullCharge = 85.f;
    constexpr float CarrierLookCm = 2500.f;
    constexpr float HumanLookCm = 600.f;

    // Spoiler-light narration for story beats; unknown ids are not narrated.
    static const TCHAR* BeatLine(FName Id)
    {
        static const TMap<FName, const TCHAR*> Lines = {
            {TEXT("B01_BOOT_HANDOVER"), TEXT("Systems online. The route is locked toward the summit.")},
            {TEXT("B02_ARCHIVE_OPENS"), TEXT("The archive opens on the radio.")},
            {TEXT("B03_PROMISE"), TEXT("A promise on the radio. The road starts to climb.")},
            {TEXT("B04A_DUST_FRONT"), TEXT("A dust front is rolling in behind us.")},
            {TEXT("B04_CART_CONVOY"), TEXT("Passing an old cart convoy.")},
            {TEXT("B05_WAITING_WATER"), TEXT("Reaching the Waiting Water.")},
            {TEXT("B06_ROAD_AHEAD"), TEXT("Over the crest. The road ahead opens up.")},
            {TEXT("B07_GEIGER_RISES"), TEXT("The counter starts ticking faster.")},
            {TEXT("B08_NUMBERED_STOP"), TEXT("A numbered stop beside the road.")},
            {TEXT("B09_DEPARTURE_PLATFORM"), TEXT("Rolling past the old departure platform.")},
            {TEXT("B10_DRY_CISTERN"), TEXT("The dry cistern.")},
            {TEXT("B11_LAST_WAYSTATION"), TEXT("Arriving at the last waystation.")},
            {TEXT("B12_KNEE_FAULT"), TEXT("A knock in the carrier's leg. It keeps going.")},
            {TEXT("B13_SECOND_FAULT"), TEXT("A second fault. The carrier is wearing down.")},
            {TEXT("B14_LOOK_BACK"), TEXT("A look back down the valley.")},
            {TEXT("B15_HIGH_VOICE_IN_RANGE"), TEXT("Something high above comes into range.")},
            {TEXT("B16_FAILING_STEPS"), TEXT("The steps are getting heavy.")},
            {TEXT("B17_CUT_OFF"), TEXT("The road narrows near the top.")},
            {TEXT("B18_COLLAPSE"), TEXT("Something gives way.")},
            {TEXT("B19_REVEAL"), TEXT("The hatch.")},
            {TEXT("B20_REST_BOULDER"), TEXT("A boulder to lean on.")},
            {TEXT("B21_LAST_LOOK_BACK"), TEXT("One last look back.")},
            {TEXT("B22_REST_HANDRAIL"), TEXT("A handrail. Time to catch a breath.")},
            {TEXT("B23_LAST_ENTRY"), TEXT("The hut at the top.")},
            {TEXT("P04_AIRSHIP"), TEXT("An old airship off to the side.")},
            {TEXT("P07_WAITING_WATER"), TEXT("The Waiting Water, up close.")},
            {TEXT("P08_WINDPUMPS"), TEXT("Wind pumps turning by the road.")},
            {TEXT("P15_WORKS"), TEXT("The Works.")},
            {TEXT("P17_CISTERN"), TEXT("A stepped cistern.")},
            {TEXT("OX1_EXCHANGE"), TEXT("A short exchange at the waystation.")},
            {TEXT("OA1_OPTICS_FAIL"), TEXT("The optics are failing.")},
            {TEXT("OA2_OPTICS_BACK"), TEXT("The optics come back.")},
            {TEXT("OB1_DRONE"), TEXT("Sending the drone up for a look.")},
        };
        const TCHAR* const* Found = Lines.Find(Id);
        return Found ? *Found : nullptr;
    }

    struct FShotCine { const TCHAR* Id; const TCHAR* Name; const TCHAR* Label; };
    static const FShotCine ShotCines[] = {
        {TEXT("CIN_06F_CREST_FORT"), TEXT("crest_fort"), TEXT("Still frame: the crest fort.")},
        {TEXT("CIN_P07_WAITING_WATER"), TEXT("waiting_water"), TEXT("Still frame: the Waiting Water.")},
        {TEXT("CIN_P15_WORKS"), TEXT("the_works"), TEXT("Still frame: the Works.")},
        {TEXT("CIN_11_WAYSTATION"), TEXT("waystation"), TEXT("Still frame: the waystation.")},
    };
    static const float VistaRoadM[] = {320.f, 1480.f, 2420.f, 3820.f};

    static void ConsoleToggle(const TArray<FString>& Args, UWorld* World)
    {
        USaskartaAutopilot* Pilot = World ? World->GetSubsystem<USaskartaAutopilot>() : nullptr;
        if (!Pilot) return;
        const bool bOn = Args.Num() > 0 ? FCString::Atoi(*Args[0]) != 0 : !Pilot->IsAutopilotEnabled();
        Pilot->SetAutopilotEnabled(bOn);
    }
    static void ConsoleShots(const TArray<FString>& Args, UWorld* World)
    {
        USaskartaAutopilot* Pilot = World ? World->GetSubsystem<USaskartaAutopilot>() : nullptr;
        if (Pilot) Pilot->SetShotsEnabled(Args.Num() == 0 || FCString::Atoi(*Args[0]) != 0);
    }
    static FAutoConsoleCommandWithWorldAndArgs GAutopilotCmd(TEXT("Saskarta.Autopilot"),
        TEXT("Saskarta.Autopilot 1|0: unattended playthrough driver (docs/AUTOPILOT.md)."),
        FConsoleCommandWithWorldAndArgsDelegate::CreateStatic(&ConsoleToggle));
    static FAutoConsoleCommandWithWorldAndArgs GAutopilotShotsCmd(TEXT("Saskarta.Autopilot.Shots"),
        TEXT("Saskarta.Autopilot.Shots 1|0: HighResShot stills at scenic moments."),
        FConsoleCommandWithWorldAndArgsDelegate::CreateStatic(&ConsoleShots));
}

// ------------------------------------------------------------------ lifecycle

bool USaskartaAutopilot::ShouldCreateSubsystem(UObject* Outer) const
{
    const UWorld* World = Cast<UWorld>(Outer);
    return World && World->IsGameWorld() && World->GetNetMode() != NM_DedicatedServer;
}

void USaskartaAutopilot::Initialize(FSubsystemCollectionBase& Collection)
{
    Super::Initialize(Collection);
    Collection.InitializeDependency<USaskartaEventRunner>();
    const TCHAR* Cmd = FCommandLine::Get();
    bShots = FParse::Param(Cmd, TEXT("autopilotshots"));
    bEnabled = FParse::Param(Cmd, TEXT("autopilot"));
}

void USaskartaAutopilot::OnWorldBeginPlay(UWorld& InWorld)
{
    Super::OnWorldBeginPlay(InWorld);
    if (bEnabled)
    {
        bEnabled = false;
        SetAutopilotEnabled(true);
    }
}

void USaskartaAutopilot::Deinitialize()
{
    ReleaseAllKeys();
    if (USaskartaEventRunner* Runner = GetWorld() ? GetWorld()->GetSubsystem<USaskartaEventRunner>() : nullptr)
    {
        Runner->OnBeatStarted.RemoveDynamic(this, &USaskartaAutopilot::HandleBeatStarted);
        Runner->OnCinematicStarted.RemoveDynamic(this, &USaskartaAutopilot::HandleCinematicStarted);
        Runner->OnCinematicFinished.RemoveDynamic(this, &USaskartaAutopilot::HandleCinematicFinished);
        Runner->OnPromptShow.RemoveDynamic(this, &USaskartaAutopilot::HandlePromptShow);
    }
    bBound = false;
    Super::Deinitialize();
}

TStatId USaskartaAutopilot::GetStatId() const
{
    RETURN_QUICK_DECLARE_CYCLE_STAT(USaskartaAutopilot, STATGROUP_Tickables);
}

double USaskartaAutopilot::Now() const
{
    return FPlatformTime::Seconds();
}

void USaskartaAutopilot::SetAutopilotEnabled(bool bEnable)
{
    if (bEnable == bEnabled) return;
    bEnabled = bEnable;
    if (!bEnable)
    {
        ReleaseAllKeys();
        Say(TEXT("stop"), TEXT("Autopilot off. Handing control back."));
        return;
    }
    StartS = Now();
    bFinished = false;
    if (LogPath.IsEmpty())
    {
        FString Custom;
        if (FParse::Value(FCommandLine::Get(), TEXT("autopilotlog="), Custom) && !Custom.IsEmpty()) LogPath = Custom;
        else LogPath = FPaths::Combine(FPaths::ProjectLogDir(),
            FString::Printf(TEXT("Autopilot-%s.log"), *FDateTime::Now().ToString(TEXT("%Y%m%d-%H%M%S"))));
    }
    BindRunner();
    Say(TEXT("start"), TEXT("Autopilot on. Let's see where this road goes."));
}

void USaskartaAutopilot::BindRunner()
{
    if (bBound) return;
    USaskartaEventRunner* Runner = GetWorld() ? GetWorld()->GetSubsystem<USaskartaEventRunner>() : nullptr;
    if (!Runner) return;
    Runner->OnBeatStarted.AddUniqueDynamic(this, &USaskartaAutopilot::HandleBeatStarted);
    Runner->OnCinematicStarted.AddUniqueDynamic(this, &USaskartaAutopilot::HandleCinematicStarted);
    Runner->OnCinematicFinished.AddUniqueDynamic(this, &USaskartaAutopilot::HandleCinematicFinished);
    Runner->OnPromptShow.AddUniqueDynamic(this, &USaskartaAutopilot::HandlePromptShow);
    bBound = true;
}

// ------------------------------------------------------------------ logging

void USaskartaAutopilot::Say(const TCHAR* Event, const FString& Text)
{
    const double T = StartS > 0.0 ? Now() - StartS : 0.0;
    const FString Line = FString::Printf(TEXT("AP|%.1f|%s|%s"), T, Event, *Text);
    UE_LOG(LogSaskartaAutopilot, Log, TEXT("%s"), *Line);
    if (!LogPath.IsEmpty())
    {
        FFileHelper::SaveStringToFile(FString::Printf(TEXT("LogSaskartaAutopilot: %s\n"), *Line), *LogPath,
            FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM, &IFileManager::Get(), FILEWRITE_Append);
    }
}

void USaskartaAutopilot::TakeShot(const FString& Name)
{
    if (!bShots || ShotsTaken.Contains(Name)) return;
    UWorld* World = GetWorld();
    UGameViewportClient* Viewport = World ? World->GetGameViewport() : nullptr;
    if (!Viewport) return;
    ShotsTaken.Add(Name);
    FOutputDeviceNull Ar;
    Viewport->Exec(World, TEXT("HighResShot 3840x2160"), Ar);
    Say(TEXT("shot"), Name);
}

// ------------------------------------------------------------------ simulated keys

void USaskartaAutopilot::SetKey(APlayerController* PC, const FKey& Key, bool bDown)
{
    if (!PC) return;
    if (KeyController.Get() != PC)
    {
        // A new controller (respawn, possession) never saw our presses.
        Held.Reset();
        LastSent.Reset();
        KeyController = PC;
    }
    const bool* Cur = Held.Find(Key);
    const bool bWas = Cur && *Cur;
    const double T = Now();
    if (bWas == bDown)
    {
        // Re-assert a hold that something flushed (focus change, pause menu).
        const double* Sent = LastSent.Find(Key);
        if (bDown && !PC->IsInputKeyDown(Key) && (!Sent || T - *Sent > 1.0))
        {
            LastSent.Add(Key, T);
            PC->InputKey(FInputKeyEventArgs::CreateSimulated(Key, IE_Released, 0.f));
            PC->InputKey(FInputKeyEventArgs::CreateSimulated(Key, IE_Pressed, 1.f));
        }
        return;
    }
    Held.Add(Key, bDown);
    LastSent.Add(Key, T);
    PC->InputKey(FInputKeyEventArgs::CreateSimulated(Key, bDown ? IE_Pressed : IE_Released, bDown ? 1.f : 0.f));
}

void USaskartaAutopilot::TapKey(APlayerController* PC, const FKey& Key, float HoldS)
{
    if (!PC) return;
    SetKey(PC, Key, true);
    PendingReleases.Add(TPair<FKey, double>(Key, Now() + HoldS));
}

void USaskartaAutopilot::PumpReleases(APlayerController* PC)
{
    const double T = Now();
    for (int32 i = PendingReleases.Num() - 1; i >= 0; --i)
    {
        if (T >= PendingReleases[i].Value)
        {
            SetKey(PC, PendingReleases[i].Key, false);
            PendingReleases.RemoveAtSwap(i);
        }
    }
    USaskartaMotorResonanceSubsystem* Motor = GetWorld() ? GetWorld()->GetSubsystem<USaskartaMotorResonanceSubsystem>() : nullptr;
    for (int32 i = MotorReleases.Num() - 1; i >= 0; --i)
    {
        if (T >= MotorReleases[i].Value)
        {
            if (Motor) Motor->HandleKey(MotorReleases[i].Key, false, false);
            MotorReleases.RemoveAtSwap(i);
        }
    }
}

void USaskartaAutopilot::ReleaseAllKeys()
{
    APlayerController* PC = KeyController.Get();
    if (PC)
    {
        for (const TPair<FKey, bool>& Pair : Held)
        {
            if (Pair.Value) PC->InputKey(FInputKeyEventArgs::CreateSimulated(Pair.Key, IE_Released, 0.f));
        }
    }
    Held.Reset();
    PendingReleases.Reset();
    if (USaskartaMotorResonanceSubsystem* Motor = GetWorld() ? GetWorld()->GetSubsystem<USaskartaMotorResonanceSubsystem>() : nullptr)
    {
        for (const TPair<FKey, double>& Pair : MotorReleases) Motor->HandleKey(Pair.Key, false, false);
    }
    MotorReleases.Reset();
    bSteerLeft = bSteerRight = false;
}

void USaskartaAutopilot::MotorPress(const FKey& Key)
{
    USaskartaMotorResonanceSubsystem* Motor = GetWorld() ? GetWorld()->GetSubsystem<USaskartaMotorResonanceSubsystem>() : nullptr;
    if (!Motor) return;
    for (const TPair<FKey, double>& Pair : MotorReleases)
    {
        if (Pair.Key == Key) return;   // still down from the last press
    }
    Motor->HandleKey(Key, true, false);
    MotorReleases.Add(TPair<FKey, double>(Key, Now() + 0.07));
}

// ------------------------------------------------------------------ runner events

void USaskartaAutopilot::HandleBeatStarted(FName Id)
{
    if (!bEnabled) return;
    if (const TCHAR* Line = SaskartaAutopilot::BeatLine(Id)) Say(TEXT("poi"), Line);
}

void USaskartaAutopilot::HandleCinematicStarted(FName Id)
{
    if (!bEnabled) return;
    const FString IdStr = Id.ToString();
    if (IdStr == TEXT("CIN_25_END_CARD")) Say(TEXT("ending"), TEXT("The ending plays out. Hands off the controls."));
    if (!bShots) return;
    for (const SaskartaAutopilot::FShotCine& Shot : SaskartaAutopilot::ShotCines)
    {
        if (IdStr == Shot.Id && !ShotsTaken.Contains(Shot.Name))
        {
            const USaskartaEventRunner* Runner = GetWorld() ? GetWorld()->GetSubsystem<USaskartaEventRunner>() : nullptr;
            const USaskartaStoryAsset* Story = Runner ? Runner->GetStory() : nullptr;
            const FSaskartaCinematicDef* Def = Story ? Story->FindCinematic(Id) : nullptr;
            ShotCine = Id;
            ShotCineName = Shot.Name;
            ShotCineAtS = Def && Def->DurationS > 1.f ? Def->DurationS * 0.5f : 5.f;
        }
    }
}

void USaskartaAutopilot::HandleCinematicFinished(FName Id)
{
    if (!bEnabled) return;
    if (Id == ShotCine) ShotCine = NAME_None;
    if (Id.ToString() == TEXT("CIN_25_END_CARD"))
    {
        Say(TEXT("end"), TEXT("The end card fades. That's the whole journey."));
        ReleaseAllKeys();
        bFinished = true;
    }
}

void USaskartaAutopilot::HandlePromptShow(const FText& Text)
{
    if (!bEnabled) return;
    LastPromptText = Text.ToString();
}

// ------------------------------------------------------------------ tick

void USaskartaAutopilot::Tick(float DeltaTime)
{
    if (!bEnabled || bFinished) return;
    UWorld* World = GetWorld();
    if (!World || World->IsPaused()) return;
    APlayerController* PC = World->GetFirstPlayerController();
    USaskartaEventRunner* Runner = World->GetSubsystem<USaskartaEventRunner>();
    if (!PC || !Runner) return;
    BindRunner();
    const float Dt = FMath::Clamp(DeltaTime, 0.f, 0.1f);
    PumpReleases(PC);

    const FName Flow = Runner->GetFlowState();
    if (Flow != LastFlow)
    {
        LastFlow = Flow;
        FlowSinceS = Now();
        if (Flow == SaskartaAutopilot::Booting) Say(TEXT("boot"), TEXT("Begin pressed. The carrier is booting up."));
        else if ((Flow == SaskartaAutopilot::Playing || Flow == SaskartaAutopilot::CarrierFlow) && !bSaidPlaying)
        {
            bSaidPlaying = true;
            Say(TEXT("drive"), TEXT("Control handed over. Driving up the road."));
        }
        else if (Flow == SaskartaAutopilot::Human && !bSaidHuman)
        {
            bSaidHuman = true;
            Say(TEXT("walk"), TEXT("On foot now. Walking the last stretch."));
        }
    }

    TickTitle(PC, Flow);
    TickPrompt(PC, Runner);
    TickMotor(Dt);

    APawn* Pawn = PC->GetPawn();
    const bool bDriveFlow = Flow == SaskartaAutopilot::Playing || Flow == SaskartaAutopilot::CarrierFlow;
    if (Pawn && bDriveFlow && Cast<ACharacter>(Pawn))
    {
        TickCarrier(PC, Runner, Pawn, Dt);
    }
    else if (Pawn && Flow == SaskartaAutopilot::Human)
    {
        TickHuman(PC, Runner, Pawn, Dt);
        TickFooting(PC);
    }
    else
    {
        // Title, boot, collapse, reboot, pause: never hold a movement key through them.
        for (const FKey& K : {EKeys::W, EKeys::S, EKeys::A, EKeys::D, EKeys::LeftShift}) SetKey(PC, K, false);
        bSteerLeft = bSteerRight = false;
        StuckS = 0.0;
    }
    TickShots(Runner, bDriveFlow);
}

void USaskartaAutopilot::TickTitle(APlayerController* PC, FName Flow)
{
    if (Flow != SaskartaAutopilot::Title) return;
    const double T = Now();
    if (!bSaidTitle)
    {
        bSaidTitle = true;
        Say(TEXT("title"), TEXT("Title screen. Starting a new journey."));
    }
    // Let the title breathe for the recording, then press Begin (the same PC function its button calls).
    if (T - FlowSinceS < 5.0 || T - LastStartGameS < 15.0) return;
    LastStartGameS = T;
    UFunction* Fn = PC->FindFunction(TEXT("StartGame"));
    if (!Fn)
    {
        Say(TEXT("warn"), TEXT("No StartGame on the player controller."));
        return;
    }
    TArray<uint8> Params;
    Params.SetNumZeroed(FMath::Max<int32>(Fn->ParmsSize, 1));
    Fn->InitializeStruct(Params.GetData());
    PC->ProcessEvent(Fn, Params.GetData());
    Fn->DestroyStruct(Params.GetData());
}

void USaskartaAutopilot::TickPrompt(APlayerController* PC, USaskartaEventRunner* Runner)
{
    const double T = Now();
    if (!Runner->IsPromptActive())
    {
        PromptSinceS = -1.0;
        return;
    }
    if (PromptSinceS < 0.0)
    {
        PromptSinceS = T;
        const FString Text = LastPromptText.TrimStartAndEnd();
        if (Text.Contains(TEXT("Transmit"))) Say(TEXT("choice"), TEXT("The last choice. Transmit, not silence."));
        else if (!Text.IsEmpty()) Say(TEXT("prompt"), FString::Printf(TEXT("Prompt: \"%s\" Pressing E."), *Text));
        else Say(TEXT("prompt"), TEXT("A prompt. Pressing E."));
    }
    // Read it for a moment, as a player would, then tap E; retry if it did not take.
    if (T - PromptSinceS >= 1.6 && T - LastPromptTapS >= 2.5)
    {
        LastPromptTapS = T;
        TapKey(PC, EKeys::E, 0.25f);
    }
}

void USaskartaAutopilot::TickMotor(float DeltaTime)
{
    UWorld* World = GetWorld();
    USaskartaMotorResonanceSubsystem* Motor = World ? World->GetSubsystem<USaskartaMotorResonanceSubsystem>() : nullptr;
    const USaskartaEarlyStormSubsystem* Storm = World ? World->GetSubsystem<USaskartaEarlyStormSubsystem>() : nullptr;
    const bool bTuning = Motor && Motor->IsTuning();
    const bool bChasing = Storm && Storm->IsChasing();
    const bool bFailed = Storm && Storm->HasFailed();
    if (bChasing && !bWasChasing) { MotorHits = 0; Say(TEXT("chase_start"), TEXT("Dust front on our tail. Cranking the motor in rhythm.")); }
    if (!bChasing && bWasChasing && !bFailed) Say(TEXT("chase_end"), FString::Printf(TEXT("Outran the dust. %d clean beats."), MotorHits));
    if (bFailed && !bWasFailed) Say(TEXT("chase_caught"), TEXT("The dust caught us. Trying that stretch again."));
    if (bTuning && !bWasTuning) { MotorHits = 0; Say(TEXT("tuning_start"), TEXT("Parked. Tuning the motor while the generator charges.")); }
    if (!bTuning && bWasTuning) Say(TEXT("tuning_done"), FString::Printf(TEXT("Motor tuned, %d beats on time."), MotorHits));
    bWasChasing = bChasing;
    bWasFailed = bFailed;
    bWasTuning = bTuning;

    if (!Motor || !Motor->IsActive() || !Motor->CanAcceptInput()) return;
    const FSaskartaMotorResonanceLogic& L = Motor->GetLogic();
    if (L.bComplete) return;
    // Beat: E inside the perfect window (+-85 ms). The reading may be one frame old; aim just before.
    const double BeatErr = L.ElapsedS - L.NextBeatS;
    if (!L.bBeatJudged && BeatErr >= -0.03 && BeatErr <= 0.06)
    {
        MotorPress(EKeys::E);
        ++MotorHits;
    }
    // Balance: A when it wants left, D when it wants right, inside its +-250 ms window.
    const double BalErr = L.ElapsedS - L.NextBalanceS;
    if (L.BalanceVisible() && !L.bBalanceJudged && BalErr >= -0.05 && BalErr <= 0.08)
    {
        MotorPress(L.WantsLeft() ? EKeys::A : EKeys::D);
    }
}

void USaskartaAutopilot::TickFooting(APlayerController* PC)
{
    UWorld* World = GetWorld();
    const USaskartaElderWalk* Walk = World ? World->GetSubsystem<USaskartaElderWalk>() : nullptr;
    const bool bActive = Walk && Walk->IsFootingCheckActive();
    if (bActive && !bWasFooting)
    {
        FootingHealthAtStart = Walk->GetFootingHealth();
        Say(TEXT("footing_check"), Walk->GetFootingCheckMode() == 0
            ? TEXT("Loose stones. Tapping for grip.") : TEXT("A gust. Leaning against it."));
    }
    if (!bActive && bWasFooting)
    {
        SetKey(PC, EKeys::SpaceBar, false);
        SetKey(PC, EKeys::A, false);
        SetKey(PC, EKeys::D, false);
        bMashDown = false;
        if (Walk && Walk->GetFootingHealth() >= FootingHealthAtStart) Say(TEXT("footing_ok"), TEXT("Steady. He keeps his footing."));
        else Say(TEXT("footing_lost"), TEXT("He stumbles, then gets back up."));
    }
    bWasFooting = bActive;
    if (!bActive) return;

    const double T = Now();
    if (Walk->GetFootingCheckMode() == 0)
    {
        // Grip: a press edge every ~70 ms (needs 5-7 presses inside 2.4 s).
        if (T - LastMashS >= 0.07)
        {
            LastMashS = T;
            bMashDown = !bMashDown;
            SetKey(PC, EKeys::SpaceBar, bMashDown);
        }
        return;
    }
    // Balance: counter the lean (A pushes left / negative, D right / positive).
    const float Sway = Walk->GetFootingSway();
    float Want = 0.f;
    if (Sway > 0.04f) Want = -1.f;
    else if (Sway < -0.04f) Want = 1.f;
    else Want = Walk->GetFootingSwayPush() > 0.f ? -1.f : 1.f;
    SetKey(PC, EKeys::A, Want < 0.f);
    SetKey(PC, EKeys::D, Want > 0.f);
}

bool USaskartaAutopilot::RoadTarget(USaskartaEventRunner* Runner, const FVector& From, float LookCm, FVector& OutTarget,
                                    float& OutNearCm, float& OutOffCm) const
{
    USplineComponent* Spline = Runner ? Runner->GetRoadSpline() : nullptr;
    if (!Spline) return false;
    const float Key = Spline->FindInputKeyClosestToWorldLocation(From);
    OutNearCm = Spline->GetDistanceAlongSplineAtSplineInputKey(Key);
    const FVector Near = Spline->GetLocationAtDistanceAlongSpline(OutNearCm, ESplineCoordinateSpace::World);
    OutOffCm = FVector::Dist2D(Near, From);
    // Off the line: aim closer so the carrier rejoins the road before the bend.
    const float Look = OutOffCm > 600.f ? LookCm * 0.4f : LookCm;
    // Road progress runs toward spline distance 0 (EVENTS.md: UE m falls as the carrier advances).
    OutTarget = Spline->GetLocationAtDistanceAlongSpline(FMath::Max(0.f, OutNearCm - Look), ESplineCoordinateSpace::World);
    return true;
}

void USaskartaAutopilot::FollowCamera(APlayerController* PC, USaskartaEventRunner* Runner, float TargetYaw, float DeltaTime)
{
    if (!PC || PC->IsLookInputIgnored() || Runner->IsHoldingInput() || Runner->IsCinematicActive()) return;
    FRotator Rot = PC->GetControlRotation();
    const float Roll = Rot.Roll;   // the elder walk owns roll
    FRotator Want(-8.f, TargetYaw, Roll);
    Rot = FMath::RInterpTo(Rot, Want, DeltaTime, 1.4f);
    Rot.Roll = Roll;
    PC->SetControlRotation(Rot);
}

void USaskartaAutopilot::TickCarrier(APlayerController* PC, USaskartaEventRunner* Runner, APawn* Pawn, float DeltaTime)
{
    UWorld* World = GetWorld();
    USaskartaPowerSubsystem* Power = World->GetSubsystem<USaskartaPowerSubsystem>();
    USaskartaMotorResonanceSubsystem* Motor = World->GetSubsystem<USaskartaMotorResonanceSubsystem>();
    const USaskartaEarlyStormSubsystem* Storm = World->GetSubsystem<USaskartaEarlyStormSubsystem>();
    const double T = Now();
    const float SpeedMps = Pawn->GetVelocity().Size2D() / 100.f;
    const float RoadM = Runner->GetRoadM();

    // Radio on once the archive has opened (the station normally starts itself at B02's end).
    if (!bRadioDone && RoadM > 200.f && !Runner->IsCinematicActive())
    {
        bRadioDone = true;
        if (USaskartaRadioStation* Radio = World->GetSubsystem<USaskartaRadioStation>())
        {
            if (!Radio->IsRadioOn())
            {
                Radio->SetRadioOn(true);
                Say(TEXT("radio_on"), TEXT("Radio on. Some company for the climb."));
            }
        }
    }
    // Road milestones every 500 m.
    if (RoadM > 0.f)
    {
        const int32 Milestone = FMath::FloorToInt(RoadM / 500.f) * 500;
        if (Milestone > LastMilestone)
        {
            LastMilestone = Milestone;
            Say(TEXT("road"), FString::Printf(TEXT("%d metres up the road."), Milestone));
        }
    }

    const bool bChasing = Storm && (Storm->IsChasing() || Storm->HasFailed());
    const bool bLocked = PC->IsMoveInputIgnored() || Runner->IsCinematicActive() || Runner->IsPromptActive();
    if (bLocked || bChasing)
    {
        // The pursuit drives the carrier itself; A/D there belong to the motor prompts.
        for (const FKey& K : {EKeys::W, EKeys::S, EKeys::A, EKeys::D, EKeys::LeftShift}) SetKey(PC, K, false);
        bSteerLeft = bSteerRight = false;
        StuckS = 0.0;
        if (Motor && Motor->IsTuning()) return;
        return;
    }

    // --- recharge
    if (Power)
    {
        const float Charge = Power->GetCharge();
        if (Mode == EDriveMode::Driving && (Charge < SaskartaAutopilot::LowCharge || Power->IsLimp()))
        {
            Mode = EDriveMode::Charging;
            bTunedThisRest = false;
            Say(TEXT("charge_start"), FString::Printf(TEXT("Cell at %.0f%%. Stopping to recharge."), Charge));
        }
        else if (Mode == EDriveMode::Charging && Charge >= SaskartaAutopilot::FullCharge && !Power->IsLimp() && !(Motor && Motor->IsTuning()))
        {
            Mode = EDriveMode::Driving;
            StuckS = 0.0;
            Say(TEXT("charge_end"), FString::Printf(TEXT("Cell back to %.0f%%. Moving on."), Charge));
        }
    }
    if (Mode == EDriveMode::Charging)
    {
        for (const FKey& K : {EKeys::W, EKeys::S, EKeys::A, EKeys::D, EKeys::LeftShift}) SetKey(PC, K, false);
        bSteerLeft = bSteerRight = false;
        StuckS = 0.0;
        // Parked long enough to rest: open the motor tuning lesson once (Tab's own path), it pays charge too.
        if (!bTunedThisRest && Power && Power->CanRest() && SpeedMps < 0.2f && Motor && !Motor->IsActive())
        {
            USaskartaRouteLog* RouteLog = World->GetSubsystem<USaskartaRouteLog>();
            if (RouteLog && RouteLog->CanOpen()) RouteLog->SetOpen(true);
            else Motor->BeginTuning();
            bTunedThisRest = true;
        }
        return;
    }

    // --- steering toward a point ~25 m ahead on the road
    FVector Target;
    float NearCm = 0.f, OffCm = 0.f;
    if (!RoadTarget(Runner, Pawn->GetActorLocation(), SaskartaAutopilot::CarrierLookCm, Target, NearCm, OffCm))
    {
        for (const FKey& K : {EKeys::W, EKeys::A, EKeys::D}) SetKey(PC, K, false);
        return;
    }
    const FVector To = (Target - Pawn->GetActorLocation()).GetSafeNormal2D();
    const float DesiredYaw = To.IsNearlyZero() ? Pawn->GetActorRotation().Yaw : To.Rotation().Yaw;
    float Err = FMath::FindDeltaAngleDegrees(Pawn->GetActorRotation().Yaw, DesiredYaw);

    // --- unstick: speed ~0 for 4 s while we hold the throttle
    if (SpeedMps < 0.4f) { StuckS += DeltaTime; TotalStuckS += DeltaTime; }
    else { StuckS = 0.0; if (SpeedMps > 1.5f) { TotalStuckS = 0.0; UnstickStage = 0; } }
    if (StuckS > 4.0 && T > UnstickUntilS)
    {
        StuckS = 0.0;
        const int32 Stage = UnstickStage++ % 3;
        if (Stage == 0)
        {
            UnstickUntilS = T + 2.5;
            bReversing = false;
            Say(TEXT("unstick"), TEXT("Wheels spinning. A short burst of turbo."));
        }
        else if (Stage == 1)
        {
            UnstickUntilS = T + 2.0;
            bReversing = true;
            Say(TEXT("unstick"), TEXT("Still stuck. Backing off and trying another line."));
        }
        else
        {
            UnstickUntilS = T + 1.0;
            AssistUntilS = T + 6.0;
            bReversing = false;
            Say(TEXT("unstick"), TEXT("Nudging back onto the road."));
        }
        if (TotalStuckS > 45.0)
        {
            TotalStuckS = 0.0;
            if (Runner->GoToRoadM(RoadM + 15.f)) Say(TEXT("recover"), TEXT("Hopelessly stuck. Placing the carrier back on the road a little ahead."));
        }
    }
    const bool bUnsticking = T < UnstickUntilS;
    const bool bTurbo = bUnsticking && !bReversing && UnstickStage % 3 == 1;
    if (bUnsticking && bReversing) Err = -Err;   // back away while turning the other way

    // Hysteresis bang-bang on A/D: D turns right (yaw increasing).
    if (bSteerRight) bSteerRight = Err > 1.f;
    else bSteerRight = Err > 4.f;
    if (bSteerLeft) bSteerLeft = Err < -1.f;
    else bSteerLeft = Err < -4.f;
    SetKey(PC, EKeys::D, bSteerRight);
    SetKey(PC, EKeys::A, bSteerLeft);
    SetKey(PC, EKeys::W, !(bUnsticking && bReversing));
    SetKey(PC, EKeys::S, bUnsticking && bReversing);
    SetKey(PC, EKeys::LeftShift, bTurbo && Power && Power->GetCharge() > 25.f);
    if (T < AssistUntilS) Pawn->AddMovementInput(To, 1.f);

    FollowCamera(PC, Runner, Pawn->GetActorRotation().Yaw, DeltaTime);

    // Read a stele when one is offered (the E prompt on the CRT).
    if (USaskartaSteleScanner* Scanner = World->GetSubsystem<USaskartaSteleScanner>())
    {
        if (Scanner->IsScanPromptVisible() && T - LastSteleS > 8.0)
        {
            LastSteleS = T;
            if (Scanner->ScanPromptedStele()) Say(TEXT("stele"), TEXT("An inscription by the road. Scanning it."));
        }
    }
}

AActor* USaskartaAutopilot::FindSummitVolume()
{
    if (SummitVolume.IsValid()) return SummitVolume.Get();
    UWorld* World = GetWorld();
    if (!World) return nullptr;
    for (TActorIterator<ASaskartaEventVolume> It(World); It; ++It)
    {
        if (IsValid(*It) && It->TriggerId == FName(TEXT("SUMMIT_HUT_APPROACH")))
        {
            SummitVolume = *It;
            return *It;
        }
    }
    return nullptr;
}

void USaskartaAutopilot::TickHuman(APlayerController* PC, USaskartaEventRunner* Runner, APawn* Pawn, float DeltaTime)
{
    for (const FKey& K : {EKeys::W, EKeys::S, EKeys::LeftShift}) SetKey(PC, K, false);
    if (PC->IsMoveInputIgnored() || Runner->IsCinematicActive() || Runner->IsPromptActive()) return;
    if (Runner->HasBeatFired(TEXT("B23_LAST_ENTRY"))) return;   // at the hut; the choice comes next

    FVector Target;
    float NearCm = 0.f, OffCm = 0.f;
    const FVector Loc = Pawn->GetActorLocation();
    bool bHave = RoadTarget(Runner, Loc, SaskartaAutopilot::HumanLookCm, Target, NearCm, OffCm);
    // Near the end of the road, walk to the hut's approach volume instead.
    if (!bHave || NearCm < 400.f || Runner->GetRoadM() > 4975.f)
    {
        if (AActor* Volume = FindSummitVolume())
        {
            Target = Volume->GetActorLocation();
            bHave = true;
        }
    }
    if (!bHave) return;
    const FVector To = (Target - Loc).GetSafeNormal2D();
    if (To.IsNearlyZero()) return;
    Pawn->AddMovementInput(To, 1.f);
    FollowCamera(PC, Runner, To.Rotation().Yaw, DeltaTime);
}

void USaskartaAutopilot::TickShots(USaskartaEventRunner* Runner, bool bDriving)
{
    if (!bShots) return;
    if (!ShotCine.IsNone() && Runner->IsCinematicActive() && Runner->GetActiveCinematicId() == ShotCine
        && Runner->GetCinematicPlaybackSeconds() >= ShotCineAtS)
    {
        for (const SaskartaAutopilot::FShotCine& Shot : SaskartaAutopilot::ShotCines)
        {
            if (ShotCineName == Shot.Name) Say(TEXT("shot_note"), Shot.Label);
        }
        TakeShot(ShotCineName);
        ShotCine = NAME_None;
    }
    if (!bDriving || Runner->IsCinematicActive() || Mode == EDriveMode::Charging) return;
    const float RoadM = Runner->GetRoadM();
    for (const float At : SaskartaAutopilot::VistaRoadM)
    {
        if (RoadM >= At && RoadM < At + 60.f)
        {
            TakeShot(FString::Printf(TEXT("road_vista_%d"), FMath::RoundToInt(At)));
        }
    }
}
