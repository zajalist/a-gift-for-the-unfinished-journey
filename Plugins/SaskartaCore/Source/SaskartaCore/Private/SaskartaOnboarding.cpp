#include "SaskartaOnboarding.h"

#include "Components/InputComponent.h"
#include "Engine/Engine.h"
#include "Engine/World.h"
#include "Framework/Application/IInputProcessor.h"
#include "Framework/Application/SlateApplication.h"
#include "GameFramework/Pawn.h"
#include "GameFramework/PlayerController.h"
#include "HAL/IConsoleManager.h"
#include "InputCoreTypes.h"
#include "Kismet/GameplayStatics.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "SaskartaEventRunner.h"
#include "SaskartaGameplayHintWidget.h"
#include "SaskartaSaveGame.h"
#include "SaskartaLightingDirector.h"
#include "SaskartaMotorAssist.h"
#include "SaskartaPower.h"
#include "SaskartaRadioStation.h"
#include "SaskartaRouteLog.h"
#include "SaskartaRouteMap.h"
#include "SaskartaSteleScanner.h"
#include "TimerManager.h"

DEFINE_LOG_CATEGORY_STATIC(LogSaskartaOnboarding, Log, All);

const TCHAR* USaskartaHintSave::Slot = TEXT("Saskarta_Hints");
const TCHAR* USaskartaOnboardingAsset::AssetPath = TEXT("/Game/SaskartaGaea/Story/DA_Saskarta_Onboarding.DA_Saskarta_Onboarding");

namespace SaskartaOnboarding
{
    static const FName Playing(TEXT("Playing"));
    static const FName Carrier(TEXT("Carrier"));
    static const FName AuxMode(TEXT("AuxSensors"));
    static const FName DroneMode(TEXT("DroneCam"));
    static const FName DriveHint(TEXT("drive"));
    static const FName RechargeIntroHint(TEXT("recharge_intro"));
    static constexpr float PollS = 0.25f;
    static constexpr double DriveMinimumVisibleS = 5.0;
    static constexpr float MovingMps = 1.5f;
    static constexpr float PowerLowPercent = 20.f; // ROUTE_BOARD_V3.md: PWR LOW below 20 %
    static constexpr float StormDark = 0.6f;
    /** A stele reading's text holds about this long on the caption channel. */
    static constexpr double AfterScanQuietS = 6.0;

    static TAutoConsoleVariable<int32> CVarEnable(TEXT("saskarta.Hints.Enable"), 1,
        TEXT("1: compact gameplay hints (docs/story/onboarding.json). 0: none."));

    // Only the first controls row uses its displayed gameplay clock. Other hints
    // retain their authored timing and the scheduler's ordinary readable minimum.
    static FSaskartaHintStep StepWithDriveReadTime(FSaskartaOnboardingCore& Core,
        const FSaskartaHintFacts& Facts, double DriveVisibleS)
    {
        const FSaskartaHintDef* Hint = Core.ActiveHint();
        const float PreviousMinReadS = Core.MinReadS;
        if (Hint && Hint->Id == DriveHint)
        {
            Core.ActiveSinceS = Facts.NowS - DriveVisibleS;
            Core.MinReadS = static_cast<float>(DriveMinimumVisibleS);
        }
        const FSaskartaHintStep Result = Core.Step(Facts);
        Core.MinReadS = PreviousMinReadS;
        return Result;
    }

    static FString DocsPath()
    {
        return FPaths::ProjectDir() / TEXT("docs/story/onboarding.json");
    }

    // ---------------------------------------------------------------------------------- input device
    class FInputDeviceProcessor : public IInputProcessor
    {
    public:
        virtual void Tick(const float, FSlateApplication&, TSharedRef<ICursor>) override {}

        virtual bool HandleKeyDownEvent(FSlateApplication&, const FKeyEvent& Event) override
        {
            bGamepad = Event.GetKey().IsGamepadKey();
            return false;
        }

        virtual bool HandleAnalogInputEvent(FSlateApplication&, const FAnalogInputEvent& Event) override
        {
            if (Event.GetKey().IsGamepadKey() && FMath::Abs(Event.GetAnalogValue()) > 0.3f)
            {
                bGamepad = true;
            }
            return false;
        }

        virtual bool HandleMouseMoveEvent(FSlateApplication&, const FPointerEvent& Event) override
        {
            if (Event.GetCursorDelta().SizeSquared() > 4.f)
            {
                bGamepad = false;
            }
            return false;
        }

        virtual bool HandleMouseButtonDownEvent(FSlateApplication&, const FPointerEvent&) override
        {
            bGamepad = false;
            return false;
        }

        static bool bGamepad;
    };

    bool FInputDeviceProcessor::bGamepad = false;
    static TSharedPtr<FInputDeviceProcessor> Processor;
    static int32 ProcessorUsers = 0;
}

// ============================================================================================ input device
bool FSaskartaInputDevice::IsGamepad()
{
    return SaskartaOnboarding::FInputDeviceProcessor::bGamepad;
}

void FSaskartaInputDevice::Register()
{
    using namespace SaskartaOnboarding;
    if (!FSlateApplication::IsInitialized())
    {
        return;
    }
    if (ProcessorUsers++ == 0)
    {
        Processor = MakeShared<FInputDeviceProcessor>();
        FSlateApplication::Get().RegisterInputPreProcessor(Processor);
    }
}

void FSaskartaInputDevice::Unregister()
{
    using namespace SaskartaOnboarding;
    if (ProcessorUsers <= 0 || --ProcessorUsers > 0)
    {
        return;
    }
    if (FSlateApplication::IsInitialized() && Processor.IsValid())
    {
        FSlateApplication::Get().UnregisterInputPreProcessor(Processor);
    }
    Processor.Reset();
}

// ============================================================================================ the asset
#if WITH_EDITOR
void USaskartaOnboardingAsset::ReimportFromDocs()
{
    FString Text;
    if (!FFileHelper::LoadFileToString(Text, *SaskartaOnboarding::DocsPath()))
    {
        UE_LOG(LogSaskartaOnboarding, Error, TEXT("cannot read %s"), *SaskartaOnboarding::DocsPath());
        return;
    }
    FSaskartaOnboardingCore Probe;
    FString Error;
    if (!Probe.ParseJson(Text, Error))
    {
        UE_LOG(LogSaskartaOnboarding, Error, TEXT("%s"), *Error);
        return;
    }
    Modify();
    Json = Text;
    UE_LOG(LogSaskartaOnboarding, Display, TEXT("DA_Saskarta_Onboarding: %d hints imported; save the asset."), Probe.Hints.Num());
}
#endif

// ============================================================================================ the subsystem
USaskartaOnboarding* USaskartaOnboarding::GetOnboarding(const UObject* WorldContextObject)
{
    const UWorld* World = GEngine ? GEngine->GetWorldFromContextObject(WorldContextObject, EGetWorldErrorMode::ReturnNull) : nullptr;
    return World ? World->GetSubsystem<USaskartaOnboarding>() : nullptr;
}

bool USaskartaOnboarding::ShouldCreateSubsystem(UObject* Outer) const
{
    const UWorld* World = Cast<UWorld>(Outer);
    return World && World->IsGameWorld();
}

void USaskartaOnboarding::OnWorldBeginPlay(UWorld& InWorld)
{
    Super::OnWorldBeginPlay(InWorld);
    SaskartaRuntimeWidgetClass(USaskartaGameplayHintWidget::StaticClass(), TEXT("/Game/SaskartaGaea/GameFlow/UI/WBP_Saskarta_GameplayHints.WBP_Saskarta_GameplayHints_C"));
    if (!bInputDeviceRegistered)
    {
        FSaskartaInputDevice::Register();
        bInputDeviceRegistered = true;
    }
    LoadData();
    LoadSeen();
    if (USaskartaEventRunner* Runner = InWorld.GetSubsystem<USaskartaEventRunner>())
    {
        Runner->OnCinematicStarted.AddDynamic(this, &USaskartaOnboarding::HandleCinematicStarted);
        Runner->OnCinematicFinished.AddDynamic(this, &USaskartaOnboarding::HandleCinematicFinished);
    }
    USaskartaSaveGame::OnRestoredRun.AddUObject(this, &USaskartaOnboarding::HandleRestoredRun);
    // A world timer freezes in pause, leaving its last hint over the menu.
    // Real-time polling only evaluates visibility; hint timing still uses world time.
    TickerHandle = FTSTicker::GetCoreTicker().AddTicker(
        FTickerDelegate::CreateUObject(this, &USaskartaOnboarding::OnTicker), SaskartaOnboarding::PollS);
}

void USaskartaOnboarding::Deinitialize()
{
    if (UWorld* World = GetWorld())
    {
        if (USaskartaEventRunner* Runner = World->GetSubsystem<USaskartaEventRunner>())
        {
            Runner->OnCinematicStarted.RemoveDynamic(this, &USaskartaOnboarding::HandleCinematicStarted);
            Runner->OnCinematicFinished.RemoveDynamic(this, &USaskartaOnboarding::HandleCinematicFinished);
        }
    }
    FTSTicker::RemoveTicker(TickerHandle);
    TickerHandle.Reset();
    USaskartaSaveGame::OnRestoredRun.RemoveAll(this);
    if (bInputDeviceRegistered)
    {
        FSaskartaInputDevice::Unregister();
        bInputDeviceRegistered = false;
    }
    UnbindInput();
    if (Widget)
    {
        Widget->RemoveFromParent();
        Widget = nullptr;
    }
    Super::Deinitialize();
}

void USaskartaOnboarding::ResetRunTeaching()
{
    bGameplayReady = false;
    bOpeningStarted = false;
    bDriveMotionSeen = false;
    bLookMotionSeen = false;
    bHaveLookBaseline = false;
    DriveHintVisibleS = 0.0;
    LastDriveHintPollS = -1.0;
    bDriveHintCounting = false;
    bRadioKey = false;
    LastLampsOn = -1;
    bLastTurbo = false;
    LastMapOpens = -1;
    LastTuningOpens = -1;
    LastScanned = -1;
    LastScanS = -1.0e9;
    Core.Active = INDEX_NONE;
    Core.Known.Reset();
    Core.TrueSinceS.Reset();
    Core.LastHideS = -1.0e9;
    Core.Seen.Remove(SaskartaOnboarding::DriveHint);
    Core.Seen.Remove(SaskartaOnboarding::RechargeIntroHint);
    Core.Seen.Remove(FName(TEXT("motor_tuning")));
    Core.Seen.Remove(FName(TEXT("battery_inspect")));
    UpdateWidget(nullptr, nullptr);
}

void USaskartaOnboarding::HandleCinematicStarted(FName Id)
{
    if (Id == FName(TEXT("CIN_01_DIRECTIVE")))
    {
        ResetRunTeaching();
        bOpeningStarted = true;
    }
    else if (Core.IsActive())
    {
        // Hide synchronously rather than leave a gameplay overlay over a camera cut.
        FSaskartaHintFacts Blocked;
        Blocked.NowS = GetWorld()->GetTimeSeconds();
        Blocked.bBlocked = true;
        Apply(SaskartaOnboarding::StepWithDriveReadTime(Core, Blocked, DriveHintVisibleS),
            GetWorld()->GetFirstPlayerController());
        bDriveHintCounting = false;
        LastDriveHintPollS = Blocked.NowS;
    }
}

void USaskartaOnboarding::HandleCinematicFinished(FName Id)
{
    if (Id != FName(TEXT("CIN_01_DIRECTIVE")) || !bOpeningStarted) return;
    bOpeningStarted = false;
    bGameplayReady = true;
    UE_LOG(LogSaskartaOnboarding, Log, TEXT("gameplay hints ready after CIN01 handback"));
    Poll(); // runner has released cinematic input and restored the gameplay view
}

void USaskartaOnboarding::HandleRestoredRun(UWorld* World, USaskartaSaveGame* Save)
{
    if (World != GetWorld() || !Save) return;
    ResetRunTeaching();
    bGameplayReady = !Save->IsHumanCheckpoint();
    if (Save->CheckpointId != FName(TEXT("CP0_DOCK")))
    {
        Core.Seen.Add(SaskartaOnboarding::DriveHint);
        Core.Seen.Add(SaskartaOnboarding::RechargeIntroHint);
    }
    // Restore broadcasts before releasing BeginTitle's input stack; the next poll is safe.
}

void USaskartaOnboarding::LoadData()
{
    FString Json;
#if WITH_EDITOR
    // PIE and standalone -game from the editor binaries: the file is the source of truth.
    FFileHelper::LoadFileToString(Json, *SaskartaOnboarding::DocsPath());
#endif
    if (Json.IsEmpty())
    {
        if (const USaskartaOnboardingAsset* Asset = LoadObject<USaskartaOnboardingAsset>(nullptr,
                USaskartaOnboardingAsset::AssetPath, nullptr, LOAD_NoWarn | LOAD_Quiet))
        {
            Json = Asset->Json;
        }
    }
    FString Error;
    if (Json.IsEmpty())
    {
        UE_LOG(LogSaskartaOnboarding, Warning, TEXT("no onboarding data (docs/story/onboarding.json or DA_Saskarta_Onboarding): no hints."));
    }
    else if (!Core.ParseJson(Json, Error))
    {
        UE_LOG(LogSaskartaOnboarding, Warning, TEXT("%s: no hints."), *Error);
    }
    // Old cooked onboarding assets can outlive native changes; never revive removed gameplay hints.
    Core.Hints.RemoveAll([](const FSaskartaHintDef& Hint)
    {
        return Hint.Id == FName(TEXT("heard_first")) || Hint.Id == FName(TEXT("board"));
    });
    for (FSaskartaHintDef& Hint : Core.Hints)
    {
        if (Hint.Id == SaskartaOnboarding::DriveHint)
        {
            // Also cover an older cooked data asset with a shorter authored timeout.
            Hint.HoldS = FMath::Max(Hint.HoldS, static_cast<float>(SaskartaOnboarding::DriveMinimumVisibleS));
            Hint.bSkipIfKnown = false;
        }
        else if (Hint.Id == FName(TEXT("motor_tuning")))
        {
            Hint.HoldS = 7.f;
            Hint.Priority = 18;
            Hint.bSkipIfKnown = false;
        }
    }
    if (Core.FindHint(FName(TEXT("battery_inspect"))) == INDEX_NONE)
    {
        FSaskartaHintDef Inspection;
        Inspection.Id = FName(TEXT("battery_inspect"));
        Inspection.Text = TEXT("LOOK BACK TO INSPECT THE BIOFUEL CELL");
        Inspection.When = {FName(TEXT("playing"))};
        Inspection.After = {SaskartaOnboarding::DriveHint};
        Inspection.DoneWhen = {FName(TEXT("battery_inspected"))};
        Inspection.FromRoadM = 0.f;
        Inspection.ToRoadM = 800.f;
        Inspection.DelayS = 8.f;
        Inspection.HoldS = 7.f;
        Inspection.Priority = 17;
        Core.Hints.Add(MoveTemp(Inspection));
    }
    bLoaded = Core.Hints.Num() > 0;
}

void USaskartaOnboarding::LoadSeen()
{
    if (UGameplayStatics::DoesSaveGameExist(USaskartaHintSave::Slot, 0))
    {
        if (const USaskartaHintSave* Save = Cast<USaskartaHintSave>(UGameplayStatics::LoadGameFromSlot(USaskartaHintSave::Slot, 0)))
        {
            Core.Seen.Append(Save->SeenHints);
        }
    }
    // Opening controls and the low-start power rule belong to each run, not the profile.
    Core.Seen.Remove(SaskartaOnboarding::DriveHint);
    Core.Seen.Remove(SaskartaOnboarding::RechargeIntroHint);
    Core.Seen.Remove(FName(TEXT("motor_tuning")));
    Core.Seen.Remove(FName(TEXT("battery_inspect")));
    SavedSeenCount = Core.Seen.Num();
}

void USaskartaOnboarding::SaveSeen()
{
    USaskartaHintSave* Save = Cast<USaskartaHintSave>(UGameplayStatics::CreateSaveGameObject(USaskartaHintSave::StaticClass()));
    if (!Save)
    {
        return;
    }
    Save->SeenHints = Core.Seen.Array();
    Save->SeenHints.Remove(SaskartaOnboarding::DriveHint);
    Save->SeenHints.Remove(SaskartaOnboarding::RechargeIntroHint);
    Save->SeenHints.Remove(FName(TEXT("motor_tuning")));
    Save->SeenHints.Remove(FName(TEXT("battery_inspect")));
    UGameplayStatics::AsyncSaveGameToSlot(Save, USaskartaHintSave::Slot, 0);
    SavedSeenCount = Core.Seen.Num();
}

void USaskartaOnboarding::ResetHints()
{
    DriveHintVisibleS = 0.0;
    LastDriveHintPollS = -1.0;
    bDriveHintCounting = false;
    Core.Seen.Reset();
    Core.Known.Reset();
    Core.TrueSinceS.Reset();
    if (Core.IsActive())
    {
        Core.Active = INDEX_NONE;
        UpdateWidget(nullptr, nullptr);
    }
    SaveSeen();
}

void USaskartaOnboarding::BuildFacts(APlayerController* PC, FSaskartaHintFacts& F)
{
    using namespace SaskartaOnboarding;
    UWorld* World = GetWorld();
    const USaskartaEventRunner* R = World->GetSubsystem<USaskartaEventRunner>();
    const USaskartaRadioStation* Station = World->GetSubsystem<USaskartaRadioStation>();
    const USaskartaPowerSubsystem* Power = World->GetSubsystem<USaskartaPowerSubsystem>();
    const USaskartaMotorAssistSubsystem* Motor = World->GetSubsystem<USaskartaMotorAssistSubsystem>();
    const USaskartaSteleScanner* Scanner = World->GetSubsystem<USaskartaSteleScanner>();
    const USaskartaRouteMap* Map = World->GetSubsystem<USaskartaRouteMap>();
    const USaskartaRouteLog* Tuning = World->GetSubsystem<USaskartaRouteLog>();
    const USaskartaLightingDirector* Director = World->GetSubsystem<USaskartaLightingDirector>();

    F.NowS = World->GetTimeSeconds();
    F.RoadM = R ? R->GetRoadM() : -1.f;
    const FName Flow = R ? R->GetFlowState() : NAME_None;
    const APawn* Pawn = PC ? PC->GetPawn() : nullptr;
    const bool bHeld = !R || R->IsCinematicActive() || R->IsHoldingInput() || (PC && PC->IsMoveInputIgnored());
    if (Flow.IsNone() || Flow == FName(TEXT("None")) || Flow == FName(TEXT("Title")) || Flow == FName(TEXT("Booting")))
    {
        bGameplayReady = false;
    }
    const bool bPlaying = bGameplayReady && Pawn && (Flow == Playing || Flow == Carrier) && !bHeld && !UGameplayStatics::IsGamePaused(World);
    auto Cond = [&F](const TCHAR* Name) { F.Conditions.Add(FName(Name)); };
    auto Act = [&F](const TCHAR* Name) { F.Actions.Add(FName(Name)); };
    if (bPlaying)
    {
        Cond(TEXT("playing"));
        if (Pawn->GetVelocity().Size2D() / 100.f > MovingMps)
        {
            Cond(TEXT("moving"));
        }
        const bool bDriveInput = PC->IsInputKeyDown(EKeys::W) || PC->IsInputKeyDown(EKeys::S)
            || PC->IsInputKeyDown(EKeys::A) || PC->IsInputKeyDown(EKeys::D)
            || FMath::Abs(PC->GetInputAnalogKeyState(EKeys::Gamepad_LeftY)) > 0.2f
            || FMath::Abs(PC->GetInputAnalogKeyState(EKeys::Gamepad_LeftX)) > 0.2f;
        bDriveMotionSeen |= bDriveInput && Pawn->GetVelocity().Size2D() > 10.f;
        const FRotator Rotation = PC->GetControlRotation();
        if (bHaveLookBaseline && !PC->IsLookInputIgnored())
        {
            const FRotator Delta = (Rotation - LastControlRotation).GetNormalized();
            bLookMotionSeen |= FMath::Abs(Delta.Yaw) + FMath::Abs(Delta.Pitch) > 0.5f;
        }
        LastControlRotation = Rotation;
        bHaveLookBaseline = true;
        // Remember deliberate movement/look, but Poll admits completion only
        // after the actual controls overlay has had five visible gameplay seconds.
    }
    else bHaveLookBaseline = false;

    // --- the radio and the show
    if (Station)
    {
        if (Station->IsShowMode() ? Station->GetShowAct() >= 1 : Station->IsAudible())
        {
            Cond(TEXT("show_on"));
        }
        const int32 On = Station->IsRadioOn() ? 1 : 0;
        if (bRadioKey)
        {
            Act(TEXT("radio_toggled"));
        }
        if (LastRadioOn == 1 && On == 0 && F.NowS - LastRadioKeyS < 1.0)
        {
            bRadioOffByPlayer = true;
        }
        if (On == 1)
        {
            bRadioOffByPlayer = false;
            Cond(TEXT("radio_on"));
        }
        LastRadioOn = On;
        if (bRadioOffByPlayer)
        {
            Cond(TEXT("radio_off_by_player"));
        }
    }
    bRadioKey = false;

    // --- power, lamps, turbo
    if (Power)
    {
        if (Power->IsInspectingBattery()) Cond(TEXT("battery_inspected"));
        const int32 Lamps = Power->AreLampsOn() ? 1 : 0;
        if (LastLampsOn >= 0 && Lamps != LastLampsOn && !Power->IsLimp())
        {
            Act(TEXT("lamps_toggled"));
        }
        LastLampsOn = Lamps;
        if (Power->IsTurbo() && !bLastTurbo)
        {
            Act(TEXT("turbo_used"));
        }
        bLastTurbo = Power->IsTurbo();
        if (Power->IsTurbo())
        {
            Cond(TEXT("turbo_on"));
        }
        if (Power->CanRest())
        {
            Cond(TEXT("resting"));
            if (Power->GetCharge() < 99.5f)
            {
                Cond(TEXT("charging"));
            }
        }
        if (Power->GetCharge() <= 35.f) Cond(TEXT("charge_needs_rest"));
        if (Power->GetCore().CanTurbo()) Cond(TEXT("boost_available"));
        if (Power->GetCharge() < PowerLowPercent)
        {
            Cond(TEXT("pwr_low"));
        }
    }
    if (Director && Director->GetEffectiveStormIntensity() >= StormDark)
    {
        Cond(TEXT("storm_dark"));
    }

    // --- steles and the route map
    const int32 Scanned = Map ? Map->NumScanned() : 0;
    if (LastScanned >= 0 && Scanned > LastScanned)
    {
        Act(TEXT("scanned"));
        LastScanS = F.NowS;
    }
    LastScanned = Scanned;
    if (Scanned > 0)
    {
        Cond(TEXT("scanned_any"));
    }
    else if (Scanner && F.RoadM >= 0.f)
    {
        int32 Passed = 0;
        for (const FSaskartaSteleScanCore::FStele& S : Scanner->GetCore().Steles)
        {
            Passed += S.RoadM < F.RoadM - 10.f ? 1 : 0;
        }
        if (Passed >= 2)
        {
            Cond(TEXT("steles_missed"));
        }
    }
    const int32 Opens = Map ? Map->GetOpenCount() : 0;
    if (LastMapOpens >= 0 && Opens > LastMapOpens)
    {
        Act(TEXT("map_opened"));
    }
    LastMapOpens = Opens;

    // --- the shared recharge motor activity
    if (Tuning)
    {
        const int32 TuningOpens = Tuning->GetOpenCount();
        if (LastTuningOpens >= 0 && TuningOpens > LastTuningOpens) Act(TEXT("motor_tuning_opened"));
        LastTuningOpens = TuningOpens;
    }

    // --- the sensor sequences
    if (R && R->IsPresentationModeActive(AuxMode))
    {
        Cond(TEXT("optics_lost"));
    }
    if (R && R->IsPresentationModeActive(DroneMode))
    {
        Cond(TEXT("drone_feed"));
    }

    // Ordinary broadcast audio continues. Important story captions/voice have priority.
    const bool bSpeechBlocks = R && (R->IsStorySubtitleActive() || R->IsVoiceBusy());
    F.bBlocked = !bPlaying || !R || bSpeechBlocks || R->IsPromptActive()
        || (Scanner && Scanner->IsScanPromptVisible()) || (Motor && Motor->IsMotorPromptActive())
        || (Map && Map->IsOpen()) || (Tuning && Tuning->IsOpen()) || F.NowS - LastScanS < AfterScanQuietS;
    if (!bPlaying) F.Actions.Reset();
}

bool USaskartaOnboarding::OnTicker(float DeltaTime)
{
    Poll();
    return true;
}

void USaskartaOnboarding::Poll()
{
    UWorld* World = GetWorld();
    if (!World || !bLoaded)
    {
        return;
    }
    APlayerController* PC = World->GetFirstPlayerController();
    BindInput(PC);
    if (SaskartaOnboarding::CVarEnable.GetValueOnGameThread() == 0)
    {
        DriveHintVisibleS = 0.0;
        LastDriveHintPollS = -1.0;
        bDriveHintCounting = false;
        if (Core.IsActive())
        {
            Core.Active = INDEX_NONE;
            UpdateWidget(PC, nullptr);
        }
        return;
    }
    FSaskartaHintFacts Facts;
    BuildFacts(PC, Facts);
    const FSaskartaHintDef* PreviousHint = Core.ActiveHint();
    const bool bDriveActive = PreviousHint && PreviousHint->Id == SaskartaOnboarding::DriveHint;
    // OpenPause need not pause world time. Count an interval only when both
    // endpoints show the drive row in unblocked gameplay; menus/voice/cuts spend none.
    if (bDriveActive && !Facts.bBlocked && bDriveHintCounting && LastDriveHintPollS >= 0.0)
    {
        DriveHintVisibleS += FMath::Max(0.0, Facts.NowS - LastDriveHintPollS);
    }
    if (bDriveActive && !Facts.bBlocked && bDriveMotionSeen && bLookMotionSeen
        && DriveHintVisibleS >= SaskartaOnboarding::DriveMinimumVisibleS)
    {
        Facts.Actions.Add(FName(TEXT("drive_controls_used")));
    }
    const FSaskartaHintStep Step = SaskartaOnboarding::StepWithDriveReadTime(Core, Facts, DriveHintVisibleS);
    if (Step.Event == ESaskartaHintEvent::Show && Core.ActiveHint()
        && Core.ActiveHint()->Id == SaskartaOnboarding::DriveHint)
    {
        DriveHintVisibleS = 0.0; // starts at this display, never at Begin or loading
    }
    Apply(Step, PC);
    const FSaskartaHintDef* CurrentHint = Core.ActiveHint();
    bDriveHintCounting = CurrentHint && CurrentHint->Id == SaskartaOnboarding::DriveHint
        && !Facts.bBlocked && Widget && Widget->IsVisible();
    LastDriveHintPollS = Facts.NowS;
    if (Core.Seen.Num() != SavedSeenCount)
    {
        SaveSeen();
    }
}

void USaskartaOnboarding::UnbindInput()
{
    if (UInputComponent* Input = BoundInput.Get())
    {
        Input->KeyBindings.RemoveAll([this](const FInputKeyBinding& Binding)
        {
            return Binding.KeyDelegate.IsBoundToObject(this);
        });
    }
    BoundInput.Reset();
    BoundController.Reset();
}

void USaskartaOnboarding::BindInput(APlayerController* PC)
{
    UInputComponent* Input = PC ? PC->InputComponent : nullptr;
    if (BoundController.Get() == PC && BoundInput.Get() == Input && Input)
    {
        return;
    }
    UnbindInput();
    if (!PC || !Input)
    {
        return;
    }
    // Listens only (never consumes): the radio keys are the station's.
    for (const FKey& Key : {EKeys::R, EKeys::Gamepad_DPad_Up})
    {
        FInputKeyBinding& Binding = Input->BindKey(Key, IE_Pressed, this, &USaskartaOnboarding::OnRadioKey);
        Binding.bConsumeInput = false;
        Binding.bExecuteWhenPaused = false;
    }
    BoundController = PC;
    BoundInput = Input;
}

void USaskartaOnboarding::OnRadioKey()
{
    bRadioKey = true;
    if (const UWorld* World = GetWorld())
    {
        LastRadioKeyS = World->GetTimeSeconds();
    }
}

void USaskartaOnboarding::Apply(const FSaskartaHintStep& Step, APlayerController* PC)
{
    if (Step.Event == ESaskartaHintEvent::Hide)
    {
        UpdateWidget(PC, nullptr);
        UE_LOG(LogSaskartaOnboarding, Log, TEXT("hint %s hidden (%s)"),
            Core.Hints.IsValidIndex(Step.Hint) ? *Core.Hints[Step.Hint].Id.ToString() : TEXT("?"), *Step.Reason.ToString());
        return;
    }
    if (const FSaskartaHintDef* Hint = Core.ActiveHint())
    {
        // Show, or keep the line in step with the last input device.
        const FString Text = FSaskartaOnboardingCore::TextFor(*Hint, FSaskartaInputDevice::IsGamepad());
        UpdateWidget(PC, &Text);
        if (Step.Event == ESaskartaHintEvent::Show)
        {
            UE_LOG(LogSaskartaOnboarding, Log, TEXT("hint %s: %s"), *Hint->Id.ToString(), *Text);
        }
    }
}

void USaskartaOnboarding::UpdateWidget(APlayerController* PC, const FString* Text)
{
    if (Widget && PC && Widget->GetOwningPlayer() != PC)
    {
        Widget->RemoveFromParent();
        Widget = nullptr;
    }
    if (!Widget && Text && PC && PC->IsLocalController())
    {
        Widget = CreateWidget<USaskartaGameplayHintWidget>(PC, SaskartaRuntimeWidgetClass(USaskartaGameplayHintWidget::StaticClass(),
            TEXT("/Game/SaskartaGaea/GameFlow/UI/WBP_Saskarta_GameplayHints.WBP_Saskarta_GameplayHints_C")));
        if (Widget) Widget->AddToPlayerScreen(35);
    }
    if (!Widget) return;
    if (Text && Core.ActiveHint())
        Widget->ShowHint(Core.ActiveHint()->Id, *Text, FSaskartaInputDevice::IsGamepad());
    else Widget->HideHint();
}

FString USaskartaOnboarding::DumpState() const
{
    FString Out = FString::Printf(TEXT("Hints loaded=%d hints=%d seen=%d active=%s gamepad=%d\n"), bLoaded ? 1 : 0,
        Core.Hints.Num(), Core.Seen.Num(), Core.ActiveHint() ? *Core.ActiveHint()->Id.ToString() : TEXT("-"),
        FSaskartaInputDevice::IsGamepad() ? 1 : 0);
    for (const FSaskartaHintDef& H : Core.Hints)
    {
        const double* Since = Core.TrueSinceS.Find(H.Id);
        Out += FString::Printf(TEXT("  %-14s seen=%d trigger=%s  %s\n"), *H.Id.ToString(), Core.Seen.Contains(H.Id) ? 1 : 0,
            Since ? *FString::Printf(TEXT("%.1fs"), GetWorld() ? GetWorld()->GetTimeSeconds() - *Since : 0.0) : TEXT("-"), *H.Text);
    }
    return Out;
}

namespace SaskartaOnboarding
{
    static FAutoConsoleCommandWithWorldAndArgs CmdDump(TEXT("Saskarta.Hints.Dump"),
        TEXT("Logs the onboarding hints: seen, triggers holding, the active one."),
        FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>&, UWorld* World)
        {
            if (const USaskartaOnboarding* O = World ? World->GetSubsystem<USaskartaOnboarding>() : nullptr)
            {
                UE_LOG(LogSaskartaOnboarding, Display, TEXT("%s"), *O->DumpState());
            }
        }));

    static FAutoConsoleCommandWithWorldAndArgs CmdReset(TEXT("Saskarta.Hints.Reset"),
        TEXT("Forgets every shown onboarding hint (and the Saskarta_Hints save)."),
        FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>&, UWorld* World)
        {
            if (USaskartaOnboarding* O = World ? World->GetSubsystem<USaskartaOnboarding>() : nullptr)
            {
                O->ResetHints();
            }
        }));
}
