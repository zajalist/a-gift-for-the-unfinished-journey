#include "SaskartaPower.h"

#include "Blueprint/WidgetTree.h"
#include "Camera/CameraComponent.h"
#include "Camera/PlayerCameraManager.h"
#include "Components/Border.h"
#include "Components/AudioComponent.h"
#include "Components/CanvasPanel.h"
#include "Components/CanvasPanelSlot.h"
#include "Components/CapsuleComponent.h"
#include "Components/ChildActorComponent.h"
#include "Components/HorizontalBox.h"
#include "Components/HorizontalBoxSlot.h"
#include "Components/LightComponent.h"
#include "Components/ProgressBar.h"
#include "Components/SizeBox.h"
#include "Components/StaticMeshComponent.h"
#include "Components/TextBlock.h"
#include "Components/VerticalBox.h"
#include "Components/VerticalBoxSlot.h"
#include "Components/WidgetComponent.h"
#include "Engine/Font.h"
#include "Engine/AssetManager.h"
#include "Engine/StreamableManager.h"
#include "Engine/GameViewportClient.h"
#include "Engine/World.h"
#include "Fonts/SlateFontInfo.h"
#include "Framework/Application/SlateApplication.h"
#include "GameFramework/Character.h"
#include "GameFramework/CharacterMovementComponent.h"
#include "GameFramework/PlayerController.h"
#include "HAL/IConsoleManager.h"
#include "InputCoreTypes.h"
#include "Materials/MaterialInterface.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "SaskartaEventRunner.h"
#include "SaskartaRadioStation.h"
#include "SaskartaRouteLog.h"
#include "SaskartaRouteMap.h"
#include "SaskartaTelemetryGraph.h"
#include "SaskartaOnboarding.h"
#include "SaskartaMotorResonance.h"
#include "SaskartaSaveGame.h"
#include "Sound/SoundBase.h"
#include "SaskartaChargeAudio.h"
#include "Kismet/GameplayStatics.h"
#include "Styling/SlateColor.h"
#include "TimerManager.h"
#include "UObject/UObjectGlobals.h"
#include "UObject/UnrealType.h"
#include "UObject/StrongObjectPtr.h"
#include "Widgets/SViewport.h"

DEFINE_LOG_CATEGORY_STATIC(LogSaskartaPower, Log, All);

UClass* SaskartaRuntimeWidgetClass(UClass* NativeClass, const TCHAR* AuthoredClassPath)
{
    static TMap<FString, TStrongObjectPtr<UClass>> Classes;
    const FString Path(AuthoredClassPath);
    if (const TStrongObjectPtr<UClass>* Existing = Classes.Find(Path)) return Existing->Get();
    UClass* Selected = LoadClass<UUserWidget>(nullptr, AuthoredClassPath);
    if (!Selected || !Selected->IsChildOf(NativeClass))
    {
        UE_LOG(LogSaskartaPower, Warning, TEXT("Gameplay UMG layout %s is absent or has the wrong parent; using %s native fallback."),
            AuthoredClassPath, *GetNameSafe(NativeClass));
        Selected = NativeClass;
    }
    Classes.Emplace(Path, TStrongObjectPtr<UClass>(Selected));
    return Selected;
}

namespace SaskartaPower
{
    static const FName Playing(TEXT("Playing"));
    static const FName FlowCarrier(TEXT("Carrier"));
    static const FName HeadlightL(TEXT("HeadlightL"));
    static const FName HeadlightR(TEXT("HeadlightR"));
    static constexpr TCHAR FontPath[] = TEXT("/Game/SaskartaGaea/GameFlow/UI/Fonts/Font_Terminal.Font_Terminal");
    static constexpr float TurboFlatMaxCmS = 800.f;
    static constexpr float TurboSteepBonusCmS = 200.f;
    static constexpr float TurboSteepGrade = 0.15f;
    static constexpr float TurboAccelCmS2 = 260.f;
    static constexpr float EmptyCoastS = 1.75f;
    static constexpr float EmptyFriction = .28f;
    static const FSoftObjectPath EmptySoundPaths[] = {
        FSoftObjectPath(TEXT("/Game/SaskartaGaea/Audio/Storm/SFX_Dosimeter_Chirp_01.SFX_Dosimeter_Chirp_01")),
        FSoftObjectPath(TEXT("/Game/SaskartaGaea/Audio/Carrier/SFX_Carrier_Motor_Strain_Loop.SFX_Carrier_Motor_Strain_Loop")),
        FSoftObjectPath(TEXT("/Game/SaskartaGaea/Audio/Carrier/SFX_Carrier_Motor_Low_Loop.SFX_Carrier_Motor_Low_Loop"))
    };

    static TAutoConsoleVariable<int32> CVarEnable(TEXT("saskarta.Power.Enable"), 1,
        TEXT("1: the carrier's biofuel charge drains and limits speed (ROUTE_BOARD_V3.md POWER). 0: off, lamps and radio untouched."));
    static TAutoConsoleVariable<int32> CVarAscii(TEXT("saskarta.Power.AsciiGlyphs"), 0,
        TEXT("1: draw the power bar with # instead of |."));
    static TAutoConsoleVariable<float> CVarGenerator(TEXT("saskarta.Power.GeneratorPerS"), 1.f,
        TEXT("Generator refill in percent per second (the first playtest knob: 1.1 = one rest fewer for a listener)."));

    static float FloorGrade(const ACharacter* Carrier)
    {
        const UCharacterMovementComponent* Move = Carrier ? Carrier->GetCharacterMovement() : nullptr;
        if (!Move || !Move->IsMovingOnGround())
        {
            return 0.f;
        }
        const FVector Forward = Carrier->GetActorForwardVector().GetSafeNormal2D();
        const FVector Normal = Move->CurrentFloor.HitResult.ImpactNormal;
        return -FVector::DotProduct(FVector(Normal.X, Normal.Y, 0.f), Forward) / FMath::Max(Normal.Z, 0.2f);
    }
}

void USaskartaPowerWidget::NativeOnInitialized()
{
    Super::NativeOnInitialized();
    SetIsFocusable(false);
    SetVisibility(ESlateVisibility::Collapsed);
    if (!WidgetTree) return;
    if (WidgetTree->RootWidget)
    {
        BindAuthoredLayout();
        return;
    }
    UCanvasPanel* Canvas = WidgetTree->ConstructWidget<UCanvasPanel>(UCanvasPanel::StaticClass(), TEXT("PowerCanvas"));
    WidgetTree->RootWidget = Canvas;
    Canvas->SetVisibility(ESlateVisibility::HitTestInvisible);

    // A viewport overlay keeps the landscape visible and does not pass text through the radio CRT.
    UVerticalBox* Content = WidgetTree->ConstructWidget<UVerticalBox>(UVerticalBox::StaticClass(), TEXT("PowerContent"));
    PowerContent = Content;
    USizeBox* Width = WidgetTree->ConstructWidget<USizeBox>(USizeBox::StaticClass(), TEXT("PowerDisplay"));
    Width->SetWidthOverride(480.f);
    Width->SetContent(Content);
    UCanvasPanelSlot* ContentSlot = Canvas->AddChildToCanvas(Width);
    DisplaySlot = ContentSlot;
    ContentSlot->SetAnchors(FAnchors(0.f, 0.f));
    ContentSlot->SetAlignment(FVector2D(0.f, 0.f));
    ContentSlot->SetPosition(FVector2D(28.f, 40.f));
    ContentSlot->SetAutoSize(true);

    UFont* Font = LoadObject<UFont>(nullptr, SaskartaPower::FontPath);
    auto MakeText = [&](UVerticalBox* Parent, const TCHAR* Name, int32 Size)
    {
        UTextBlock* Text = WidgetTree->ConstructWidget<UTextBlock>(UTextBlock::StaticClass(), Name);
        Text->SetColorAndOpacity(FSlateColor(FLinearColor(0.93f, 0.90f, 0.78f, 1.f)));
        Text->SetShadowColorAndOpacity(FLinearColor(0.f, 0.f, 0.f, 0.92f));
        Text->SetShadowOffset(FVector2D(1.f, 2.f));
        if (Font)
        {
            Text->SetFont(FSlateFontInfo(Font, Size));
        }
        else
        {
            FSlateFontInfo Fallback = Text->GetFont();
            Fallback.Size = Size;
            Text->SetFont(Fallback);
        }
        Parent->AddChildToVerticalBox(Text);
        return Text;
    };
    auto MakePanel = [&](const TCHAR* Name, UVerticalBox*& Inner)
    {
        UBorder* Panel = WidgetTree->ConstructWidget<UBorder>(UBorder::StaticClass(), Name);
        Panel->SetBrushColor(FLinearColor::Transparent);
        Panel->SetPadding(FMargin(0.f, 5.f));
        Content->AddChildToVerticalBox(Panel)->SetPadding(FMargin(0.f, 0.f, 0.f, 6.f));
        Inner = WidgetTree->ConstructWidget<UVerticalBox>();
        Panel->SetContent(Inner);
        Panel->SetVisibility(ESlateVisibility::Collapsed);
        return Panel;
    };
    UVerticalBox* NoticeContent;
    NoticePanel = MakePanel(TEXT("PowerNotices"), NoticeContent);
    USizeBox* AccentSize = WidgetTree->ConstructWidget<USizeBox>();
    AccentSize->SetHeightOverride(2.f);
    AccentSize->SetWidthOverride(320.f);
    NoticeAccent = WidgetTree->ConstructWidget<UBorder>(UBorder::StaticClass(), TEXT("PowerWarningAccent"));
    AccentSize->SetContent(NoticeAccent);
    NoticeContent->AddChildToVerticalBox(AccentSize)->SetPadding(FMargin(0.f, 0.f, 0.f, 5.f));
    NoticeTitle = MakeText(NoticeContent, TEXT("PowerWarningTitle"), 24);
    LoadsText = MakeText(NoticeContent, TEXT("PowerLoads"), 19);
    LoadsText->SetAutoWrapText(true);
    UVerticalBox* BatteryContent;
    BatteryPanel = MakePanel(TEXT("BatteryInspection"), BatteryContent);
        MakeText(BatteryContent, TEXT("BatteryLabel"), 16)->SetText(FText::FromString(TEXT("BIOFUEL CELL")));
    LineText = MakeText(BatteryContent, TEXT("BatteryPercent"), 30);
    UHorizontalBox* Gauge = WidgetTree->ConstructWidget<UHorizontalBox>();
    BatteryContent->AddChildToVerticalBox(Gauge)->SetPadding(FMargin(0.f, 5.f, 0.f, 5.f));
    BatteryGauge.Reset();
    for (int32 Index = 0; Index < 7; ++Index)
    {
        USizeBox* CellSize = WidgetTree->ConstructWidget<USizeBox>();
        CellSize->SetHeightOverride(10.f);
        CellSize->SetWidthOverride(32.f);
        UProgressBar* Cell = WidgetTree->ConstructWidget<UProgressBar>(UProgressBar::StaticClass(), FName(*FString::Printf(TEXT("BatterySegment%d"), Index)));
        Cell->SetBarFillType(EProgressBarFillType::LeftToRight);
        FProgressBarStyle Style = Cell->GetWidgetStyle();
        Style.BackgroundImage.TintColor = FSlateColor(FLinearColor(0.03f, 0.03f, 0.02f, 0.26f));
        Style.FillImage.TintColor = FSlateColor(FLinearColor::White);
        Style.MarqueeImage.TintColor = FSlateColor(FLinearColor::Transparent);
        Cell->SetWidgetStyle(Style);
        CellSize->SetContent(Cell);
        Gauge->AddChildToHorizontalBox(CellSize)->SetPadding(FMargin(0.f, 0.f, 4.f, 0.f));
        BatteryGauge.Add(Cell);
    }
    StateText = MakeText(BatteryContent, TEXT("BatteryState"), 19);
    StateText->SetAutoWrapText(true);
    UVerticalBox* Instruments;
    TelemetryPanel = MakePanel(TEXT("DrivingInstruments"), Instruments);
    UHorizontalBox* Columns = WidgetTree->ConstructWidget<UHorizontalBox>();
    Instruments->AddChildToVerticalBox(Columns);
    auto MakeColumn = [&]()
    {
        UVerticalBox* Column = WidgetTree->ConstructWidget<UVerticalBox>();
        UHorizontalBoxSlot* Slot = Columns->AddChildToHorizontalBox(Column);
        Slot->SetSize(FSlateChildSize(ESlateSizeRule::Fill));
        Slot->SetPadding(FMargin(0.f, 0.f, 12.f, 0.f));
        return Column;
    };
    UVerticalBox* SpeedColumn = MakeColumn();
    SpeedText = MakeText(SpeedColumn, TEXT("ActualSpeed"), 26);
    SpeedScaleText = MakeText(SpeedColumn, TEXT("SpeedScale"), 16);
    SpeedGraph = WidgetTree->ConstructWidget<USaskartaTelemetryGraph>(USaskartaTelemetryGraph::StaticClass(), TEXT("SpeedTrace"));
    SpeedColumn->AddChildToVerticalBox(SpeedGraph);
    UVerticalBox* AltitudeColumn = MakeColumn();
    AltitudeText = MakeText(AltitudeColumn, TEXT("ActualAltitude"), 26);
    AltitudeScaleText = MakeText(AltitudeColumn, TEXT("AltitudeScale"), 16);
    AltitudeGraph = WidgetTree->ConstructWidget<USaskartaTelemetryGraph>(USaskartaTelemetryGraph::StaticClass(), TEXT("AltitudeTrace"));
    AltitudeColumn->AddChildToVerticalBox(AltitudeGraph);
    TelemetryDatum = MakeText(Instruments, TEXT("AltitudeDatum"), 16);
    TelemetryHint = MakeText(Instruments, TEXT("TelemetryToggle"), 14);
    SetVisibility(ESlateVisibility::Collapsed);
}

bool USaskartaPowerWidget::BindAuthoredLayout()
{
    LineText = Cast<UTextBlock>(GetWidgetFromName(TEXT("BatteryPercent")));
    LoadsText = Cast<UTextBlock>(GetWidgetFromName(TEXT("PowerLoads")));
    NoticeTitle = Cast<UTextBlock>(GetWidgetFromName(TEXT("PowerWarningTitle")));
    NoticeAccent = Cast<UBorder>(GetWidgetFromName(TEXT("PowerWarningAccent")));
    BatteryPanel = Cast<UBorder>(GetWidgetFromName(TEXT("BatteryInspection")));
    NoticePanel = Cast<UBorder>(GetWidgetFromName(TEXT("PowerNotices")));
    TelemetryPanel = Cast<UBorder>(GetWidgetFromName(TEXT("DrivingInstruments")));
    StateText = Cast<UTextBlock>(GetWidgetFromName(TEXT("BatteryState")));
    SpeedText = Cast<UTextBlock>(GetWidgetFromName(TEXT("ActualSpeed")));
    AltitudeText = Cast<UTextBlock>(GetWidgetFromName(TEXT("ActualAltitude")));
    SpeedScaleText = Cast<UTextBlock>(GetWidgetFromName(TEXT("SpeedScale")));
    AltitudeScaleText = Cast<UTextBlock>(GetWidgetFromName(TEXT("AltitudeScale")));
    SpeedGraph = Cast<USaskartaTelemetryGraph>(GetWidgetFromName(TEXT("SpeedTrace")));
    AltitudeGraph = Cast<USaskartaTelemetryGraph>(GetWidgetFromName(TEXT("AltitudeTrace")));
    TelemetryHint = Cast<UTextBlock>(GetWidgetFromName(TEXT("TelemetryToggle")));
    TelemetryDatum = Cast<UTextBlock>(GetWidgetFromName(TEXT("AltitudeDatum")));
    PowerContent = Cast<UVerticalBox>(GetWidgetFromName(TEXT("PowerContent")));
    UWidget* Display = GetWidgetFromName(TEXT("PowerDisplay"));
    DisplaySlot = Display ? Cast<UCanvasPanelSlot>(Display->Slot) : nullptr;
    BatteryGauge.Reset();
    bool bCellsValid = true;
    for (int32 Index = 0; Index < 7; ++Index)
    {
        UProgressBar* Cell = Cast<UProgressBar>(GetWidgetFromName(FName(*FString::Printf(TEXT("BatterySegment%d"), Index))));
        BatteryGauge.Add(Cell);
        bCellsValid &= Cell != nullptr;
    }
    const bool bValid = LineText && LoadsText && NoticeTitle && NoticeAccent && BatteryPanel && NoticePanel && TelemetryPanel &&
        StateText && SpeedText && AltitudeText && SpeedScaleText && AltitudeScaleText && SpeedGraph && AltitudeGraph &&
        TelemetryHint && TelemetryDatum && PowerContent && DisplaySlot && bCellsValid;
    if (!bValid) UE_LOG(LogSaskartaPower, Error, TEXT("%s: authored power UMG layout has missing or mistyped named widgets. Install Tools/UIRuntime layouts."), *GetClass()->GetPathName());
    return bValid;
}

void USaskartaPowerWidget::ShowPower(bool bShow, bool bInspecting, bool bTelemetry,
    const FSaskartaPowerHudInput& In, const FSaskartaPowerHudOutput& Out, const FSaskartaPowerTelemetry& History)
{
    if (!LineText || !SpeedGraph || !AltitudeGraph || !DisplaySlot)
    {
        SetVisibility(ESlateVisibility::Collapsed);
        return;
    }
    const ESlateVisibility Desired = bShow ? ESlateVisibility::HitTestInvisible : ESlateVisibility::Collapsed;
    if (GetVisibility() != Desired)
    {
        SetVisibility(Desired);
    }
    if (!bShow)
    {
        return;
    }
    // The 720 x 384 motor diagram occupies the lower left. Move these small instruments to
    // the opposite upper corner during tuning/pursuit, clear of that diagram and lower captions.
    const USaskartaMotorResonanceSubsystem* Motor = GetWorld() ? GetWorld()->GetSubsystem<USaskartaMotorResonanceSubsystem>() : nullptr;
    const bool bRightEdge = (Motor && Motor->IsActive()) || In.bInscriptionReading;
    if (DisplaySlot && bRightEdge != bDisplayAlongRightEdge)
    {
        DisplaySlot->SetAnchors(FAnchors(bRightEdge ? 1.f : 0.f, 0.f));
        DisplaySlot->SetAlignment(FVector2D(bRightEdge ? 1.f : 0.f, 0.f));
        DisplaySlot->SetPosition(FVector2D(bRightEdge ? -28.f : 28.f, 40.f));
        bDisplayAlongRightEdge = bRightEdge;
    }
    auto SetText = [](UTextBlock* Text, const FString& Value)
    {
        if (Text && Text->GetText().ToString() != Value) Text->SetText(FText::FromString(Value));
    };
    auto Visible = [](UWidget* W, bool bVisible)
    {
        if (W) W->SetVisibility(bVisible ? ESlateVisibility::HitTestInvisible : ESlateVisibility::Collapsed);
    };
    FString Notice;
    FString WarningTitle;
    const bool bRecharging = In.bResting && In.RatePerS > 0.f;
    const bool bWarning = In.bLimp || In.bBlink || In.bLow;
    if (In.bLimp)
    {
        WarningTitle = TEXT("[!] Battery depleted");
        Notice = bRecharging ? TEXT("Recharging. Drive resumes at 30%.") : TEXT("Stop to recharge the biofuel cell.");
    }
    else if (In.bBlink)
    {
        WarningTitle = TEXT("[!] Critical charge");
        Notice = bRecharging ? TEXT("Recharging the biofuel cell.") : TEXT("Stop to recharge the biofuel cell.");
    }
    else if (In.bLow)
    {
        WarningTitle = TEXT("[!] Low charge");
        Notice = bRecharging ? TEXT("Recharging the biofuel cell.") : TEXT("Stop to recharge the biofuel cell.");
    }
    if (!Out.Loads.empty())
    {
        const FString Detail(Out.Loads.c_str());
        // Prefer this single clear action over a second legacy low-charge or tune instruction.
        const bool bDuplicateWarning = Detail.Contains(TEXT("PWR LOW")) ||
            (bWarning && (Detail.Contains(TEXT("BATTERY LOW")) || Detail.Contains(TEXT("BATTERY CRITICAL")) ||
                Detail.Contains(TEXT("SYSTEM STOPPED")) || Detail.Contains(TEXT("STOP TO CHARGE"))));
        if (!bDuplicateWarning && Detail != TEXT("TAB . TUNE MOTOR") && Detail != TEXT("VIEW . TUNE MOTOR"))
            Notice += (Notice.IsEmpty() ? TEXT("") : TEXT("\n")) + Detail;
    }
    Visible(NoticePanel, !Notice.IsEmpty());
    Visible(NoticeTitle, bWarning);
    Visible(NoticeAccent, bWarning);
    SetText(NoticeTitle, WarningTitle);
    const FLinearColor WarningColor = (In.bLimp || In.bBlink) ? FLinearColor(1.f, 0.31f, 0.20f, 1.f) :
        FLinearColor(1.f, 0.74f, 0.28f, 1.f);
    if (NoticeTitle) NoticeTitle->SetColorAndOpacity(FSlateColor(WarningColor));
    if (NoticeAccent)
    {
        NoticeAccent->SetBrushColor(WarningColor);
        // A restrained critical accent pulse; the message and charge readout remain steady.
        const bool bCriticalPulse = (In.bLimp || In.bBlink) && !bRecharging;
        const float TimeS = GetWorld() ? GetWorld()->GetTimeSeconds() : 0.f;
        NoticeAccent->SetRenderOpacity(bCriticalPulse ? 0.82f + 0.18f * FMath::Sin(TimeS * PI * 1.4f) : 1.f);
    }
    SetText(LoadsText, Notice);
    Visible(BatteryPanel, bInspecting);
    if (bInspecting)
    {
        // Only this gaze-gated panel contains the total battery percentage.
        SetText(LineText, FString::Printf(TEXT("%.0f%%"), FMath::Clamp(In.Charge, 0.f, 100.f)));
        const FLinearColor CellColor = In.Charge < 10.f ? FLinearColor(1.f, 0.35f, 0.22f, 1.f) :
            In.Charge < 25.f ? FLinearColor(1.f, 0.72f, 0.26f, 1.f) : FLinearColor(0.63f, 0.88f, 0.66f, 1.f);
        LineText->SetColorAndOpacity(FSlateColor(CellColor));
        for (int32 Segment = 0; Segment < BatteryGauge.Num(); ++Segment)
            if (BatteryGauge[Segment])
            {
                BatteryGauge[Segment]->SetPercent(SaskartaBatterySegmentFill(In.Charge, Segment));
                BatteryGauge[Segment]->SetFillColorAndOpacity(CellColor);
            }
        FString State;
        if (In.bResting && In.RatePerS > 0.f)
            State = In.Charge >= 99.5f ? TEXT("CHARGED") : FString::Printf(TEXT("CHARGING  /  FULL IN %.0f s"), FMath::Max(0.f, In.SecondsToFull));
        else if (In.bLimp) State = TEXT("STOPPED  /  RESTARTS AT 30%");
        else State = FString(FSaskartaPowerHud::Range(In.RangeKm).c_str());
        SetText(StateText, State);
    }
    Visible(TelemetryPanel, bTelemetry && !In.bInscriptionReading && History.Count > 0);
    if (bTelemetry && !In.bInscriptionReading && History.Count > 0)
    {
        const int Latest = History.Index(History.Count - 1);
        float SpeedMax = 40.f;
        float AltMin = History.AltitudeM[Latest] - 2.f, AltMax = AltMin + 4.f;
        for (int I = 0; I < History.Count; ++I)
        {
            const int At = History.Index(I);
            SpeedMax = FMath::Max(SpeedMax, History.SpeedKph[At]);
            AltMin = FMath::Min(AltMin, History.AltitudeM[At]);
            AltMax = FMath::Max(AltMax, History.AltitudeM[At]);
        }
        SpeedMax = FMath::CeilToFloat(SpeedMax / 10.f) * 10.f;
        AltMin = FMath::FloorToFloat(AltMin); AltMax = FMath::CeilToFloat(AltMax);
        SetText(SpeedText, FString::Printf(TEXT("SPEED %.1f KM/H"), History.SpeedKph[Latest]));
        SetText(AltitudeText, FString::Printf(TEXT("ALT %.1f M"), History.AltitudeM[Latest]));
        SetText(SpeedScaleText, FString::Printf(TEXT("0 - %.0f KM/H"), SpeedMax));
        SetText(AltitudeScaleText, FString::Printf(TEXT("%.0f - %.0f M"), AltMin, AltMax));
        SetText(TelemetryDatum, In.MotorRpm >= 0.f ? FString::Printf(TEXT("ALT: WORLD DATUM . RPM %.0f"), In.MotorRpm) : TEXT("ALT: WORLD DATUM"));
        SetText(TelemetryHint, In.bGamepad ? TEXT("L3 . HIDE . LAST 12 S") : TEXT("H . HIDE . LAST 12 S"));
        TArray<FVector2D> SpeedPoints, AltitudePoints;
        SpeedPoints.Reserve(History.Count); AltitudePoints.Reserve(History.Count);
        for (int I = 0; I < History.Count; ++I)
        {
            const int At = History.Index(I);
            const double X = 1.0 + (History.TimeS[At] - History.TimeS[Latest]) / 12.0;
            SpeedPoints.Emplace(X, History.SpeedKph[At] / SpeedMax);
            AltitudePoints.Emplace(X, (History.AltitudeM[At] - AltMin) / (AltMax - AltMin));
        }
        SpeedGraph->SetSamples(SpeedPoints); AltitudeGraph->SetSamples(AltitudePoints);
    }

}

bool USaskartaPowerSubsystem::ShouldCreateSubsystem(UObject* Outer) const
{
    const UWorld* World = Cast<UWorld>(Outer);
    return World && World->IsGameWorld();
}

void USaskartaPowerSubsystem::Initialize(FSubsystemCollectionBase& Collection)
{
    Super::Initialize(Collection);
    WritingRunHandle = USaskartaSaveGame::OnWritingRun.AddUObject(this, &USaskartaPowerSubsystem::HandleWritingRun);
    RestoredRunHandle = USaskartaSaveGame::OnRestoredRun.AddUObject(this, &USaskartaPowerSubsystem::HandleRestoredRun);
}

void USaskartaPowerSubsystem::OnWorldBeginPlay(UWorld& InWorld)
{
    Super::OnWorldBeginPlay(InWorld);
    if (UAssetManager::IsInitialized())
    {
        TArray<FSoftObjectPath> Sounds;
        for (const FSoftObjectPath& Path : SaskartaPower::EmptySoundPaths) Sounds.Add(Path);
        EmptySoundLoad = UAssetManager::GetStreamableManager().RequestAsyncLoad(Sounds, FStreamableDelegate());
    }
    ChargeAudio = NewObject<USaskartaChargeAudio>(this);
    ChargeAudio->Start();
    SaskartaRuntimeWidgetClass(USaskartaPowerWidget::StaticClass(), TEXT("/Game/SaskartaGaea/GameFlow/UI/WBP_Saskarta_Power.WBP_Saskarta_Power_C"));
    if (USaskartaEventRunner* Runner = InWorld.GetSubsystem<USaskartaEventRunner>())
    {
        Runner->OnCaptionShow.AddUniqueDynamic(this, &USaskartaPowerSubsystem::HandleCaptionShow);
        Runner->OnCaptionHide.AddUniqueDynamic(this, &USaskartaPowerSubsystem::HandleCaptionHide);
        CaptionRunner = Runner;
    }
    InWorld.GetTimerManager().SetTimer(Timer, this, &USaskartaPowerSubsystem::Poll, 0.1f, true);
    InWorld.GetTimerManager().SetTimer(KeyTimer, this, &USaskartaPowerSubsystem::PollKeys, 0.02f, true);
}

void USaskartaPowerSubsystem::Deinitialize()
{
    ReleaseEmptyDrive();
    if (ChargeAudio) ChargeAudio->Shutdown();
    ChargeAudio = nullptr;
    StopEmptyAudio();
    if (IsValid(EmptyAudio)) EmptyAudio->DestroyComponent();
    EmptyAudio = nullptr;
    if (EmptySoundLoad.IsValid()) EmptySoundLoad->CancelHandle();
    EmptySoundLoad.Reset();
    EmptySounds.Reset();
    if (USaskartaEventRunner* Runner = CaptionRunner.Get())
    {
        Runner->OnCaptionShow.RemoveDynamic(this, &USaskartaPowerSubsystem::HandleCaptionShow);
        Runner->OnCaptionHide.RemoveDynamic(this, &USaskartaPowerSubsystem::HandleCaptionHide);
    }
    CaptionRunner.Reset();
    USaskartaSaveGame::OnWritingRun.Remove(WritingRunHandle);
    USaskartaSaveGame::OnRestoredRun.Remove(RestoredRunHandle);
    if (UWorld* World = GetWorld())
    {
        World->GetTimerManager().ClearTimer(Timer);
        World->GetTimerManager().ClearTimer(KeyTimer);
    }
    if (WidgetPlane)
    {
        WidgetPlane->DestroyComponent();
        WidgetPlane = nullptr;
    }
    if (Widget)
    {
        Widget->RemoveFromParent();
        Widget = nullptr;
    }
    // Leave the world as we found it: lamps visible.
    bLampsOn = true;
    bRestActivityOpen = false;
    BatteryGaze.Reset(); BatterySegments.Reset();
    Core.bLimp = false;
    ApplyLamps(LampCarrier.Get());
    Super::Deinitialize();
}

void USaskartaPowerSubsystem::SetCharge(float Percent)
{
    FSaskartaPowerSaveState State = Core.Save();
    State.Charge = Percent;
    // A recharge reward must not release the empty-cell latch before the existing 30% recovery threshold.
    State.bLimp = State.bLimp || Percent <= 0.f;
    Core.Load(State);
    if (!Core.bLimp && Core.Charge > 0.f) { ReleaseEmptyDrive(); bEmptyEpisode = false; }
}

void USaskartaPowerSubsystem::HandleCaptionShow(const FText& Text, FName Target, float DurationS)
{
    if (Target == TEXT("Scan")) bInscriptionReading = !Text.IsEmpty();
}

void USaskartaPowerSubsystem::HandleCaptionHide(FName Target)
{
    if (Target == TEXT("Scan")) bInscriptionReading = false;
}

void USaskartaPowerSubsystem::HandleWritingRun(UWorld* World, USaskartaSaveGame* Save)
{
    if (!Save || World != GetWorld()) return;
    const FSaskartaPowerSaveState State = Core.Save();
    Save->bHasPowerState = true;
    Save->PowerCharge = State.Charge;
    Save->PowerStoppedForS = State.StoppedForS;
    Save->bPowerLimp = State.bLimp;
    Save->bPowerFirstRechargeComplete = State.bFirstRechargeComplete;
}

void USaskartaPowerSubsystem::HandleRestoredRun(UWorld* World, USaskartaSaveGame* Save)
{
    if (!Save || World != GetWorld()) return;
    ReleaseEmptyDrive();
    Telemetry.Reset();
    BatteryGaze.Reset();
    if (Save->bHasPowerState)
    {
        Core.Load({Save->PowerCharge, Save->PowerStoppedForS, Save->bPowerLimp,
            Save->bPowerFirstRechargeComplete});
    }
    else
    {
        Core.Load({Core.Tuning.InitialChargePercent, 0.f, false, false});
    }
    // A restored empty checkpoint is already parked, not a fresh depletion.
    bEmptyEpisode = Core.bLimp || Core.Charge <= 0.f;
}

APlayerController* USaskartaPowerSubsystem::FindController() const
{
    const UWorld* World = GetWorld();
    return World ? World->GetFirstPlayerController() : nullptr;
}

float USaskartaPowerSubsystem::GetRangeKm() const
{
    const USaskartaRadioStation* Station = USaskartaRadioStation::GetRadioStation(this);
    const bool bRadio = Station && Station->IsRadioOn() && !Station->IsRadioForcedOn();
    return Core.RangeKm(bRadio, bLampsOn);
}

void USaskartaPowerSubsystem::ShowNotice(const FString& Text, float Seconds)
{
    Hud.Notify(std::wstring(*Text), Seconds);
}

void USaskartaPowerSubsystem::PollKeys()
{
    APlayerController* PC = FindController();
    const bool bDown = PC && (PC->IsInputKeyDown(EKeys::F) || PC->IsInputKeyDown(LampPadKey()));
    if (bDown && !bLampsKeyWasDown)
    {
        OnLampsPressed();
    }
    bLampsKeyWasDown = bDown;
    const bool bTelemetryDown = PC && (PC->IsInputKeyDown(EKeys::H) || PC->IsInputKeyDown(EKeys::Gamepad_LeftThumbstick));
    if (bTelemetryDown && !bTelemetryKeyWasDown && CanUseInstruments(PC)) bTelemetryOpen = !bTelemetryOpen;
    bTelemetryKeyWasDown = bTelemetryDown;
}

bool USaskartaPowerSubsystem::CanUseInstruments(APlayerController* PC) const
{
    const UWorld* World = GetWorld();
    const USaskartaEventRunner* Runner = World ? World->GetSubsystem<USaskartaEventRunner>() : nullptr;
    const USaskartaRouteMap* Map = World ? World->GetSubsystem<USaskartaRouteMap>() : nullptr;
    if (!World || World->IsPaused() || !PC || !PC->IsLocalController() || !PC->GetLocalPlayer() ||
        PC->GetPawn() != ActiveCarrier.Get() ||
        !Runner || Runner->IsCinematicActive() || Runner->IsHoldingInput() || Runner->IsPromptActive() ||
        (Map && Map->IsOpen())) return false;
    const FName Flow = Runner->GetFlowState();
    if (Flow != SaskartaPower::Playing && Flow != SaskartaPower::FlowCarrier) return false;
    if (!FSlateApplication::IsInitialized() || !FSlateApplication::Get().IsActive()) return false;
    const UGameViewportClient* Viewport = World->GetGameViewport();
    const TSharedPtr<SViewport> SlateViewport = Viewport ? Viewport->GetGameViewportWidget() : nullptr;
    return SlateViewport.IsValid() && SlateViewport->HasAnyUserFocusOrFocusedDescendants();
}

void USaskartaPowerSubsystem::UpdateBattery(ACharacter* Carrier)
{
    if (BatteryCarrier.Get() != Carrier)
    {
        BatteryCarrier = Carrier;
        BatteryActor.Reset(); BatteryBody.Reset(); BatterySegments.Reset();
        LastPhysicalCharge = -1.f; LastBatterySearchS = -10.0;
        BatteryGaze.Reset(); Telemetry.Reset();
    }
    if (!Carrier) return;
    const double NowS = GetWorld()->GetTimeSeconds();
    if (!BatteryBody.IsValid() && NowS - LastBatterySearchS >= 1.0)
    {
        LastBatterySearchS = NowS;
        // Resolve the one authored child on this carrier, never a broken/roadside assembly.
        TArray<UChildActorComponent*> Children;
        Carrier->GetComponents(Children);
        for (UChildActorComponent* Child : Children)
            if (Child && (Child->GetFName() == TEXT("Biofuel01Assembly") || Child->GetName().StartsWith(TEXT("Biofuel01Assembly_"))))
                BatteryActor = Child->GetChildActor();
        if (AActor* Assembly = BatteryActor.Get())
        {
            TArray<UStaticMeshComponent*> Parts;
            Assembly->GetComponents(Parts);
            BatterySegments.Init(nullptr, 7);
            for (UStaticMeshComponent* Part : Parts)
            {
                if (!Part) continue;
                if (Part->GetFName() == TEXT("Biofuel01_Body") || Part->GetName().StartsWith(TEXT("Biofuel01_Body_"))) BatteryBody = Part;
                for (int32 Segment = 0; Segment < 7; ++Segment)
                {
                    const FString SegmentName = FString::Printf(TEXT("Biofuel01_Charge%02d"), Segment + 1);
                    if (Part->GetFName() != FName(*SegmentName) && !Part->GetName().StartsWith(SegmentName + TEXT("_"))) continue;
                    float ExistingFill = 0.f;
                    UMaterialInterface* Material = Part->GetMaterial(0);
                    if (Material && Material->GetScalarParameterValue(FMaterialParameterInfo(TEXT("ChargeFill")), ExistingFill))
                        BatterySegments[Segment] = Part->CreateDynamicMaterialInstance(0);
                    else
                        UE_LOG(LogSaskartaPower, Warning, TEXT("Battery segment %s needs the ChargeFill indicator material"), *Part->GetName());
                }
            }
            LastPhysicalCharge = -1.f;
            if (BatteryBody.IsValid())
                UE_LOG(LogSaskartaPower, Log, TEXT("Rear battery resolved: child=%s body=%s visible=%d actorHidden=%d location=%s size=%s segments=%d"),
                    *Assembly->GetName(), *BatteryBody->GetName(), BatteryBody->IsVisible() && !BatteryBody->bHiddenInGame,
                    Assembly->IsHidden(), *BatteryBody->Bounds.Origin.ToString(), *BatteryBody->Bounds.BoxExtent.ToString(),
                    BatterySegments.FilterByPredicate([](const TObjectPtr<UMaterialInstanceDynamic>& M) { return M != nullptr; }).Num());
        }
    }
    if (FMath::IsNearlyEqual(LastPhysicalCharge, Core.Charge, 0.0001f)) return;
    for (int32 Segment = 0; Segment < BatterySegments.Num(); ++Segment)
        if (UMaterialInstanceDynamic* Material = BatterySegments[Segment])
            Material->SetScalarParameterValue(TEXT("ChargeFill"), SaskartaBatterySegmentFill(Core.Charge, Segment));
    LastPhysicalCharge = Core.Charge;
}

void USaskartaPowerSubsystem::UpdateBatteryGaze(APlayerController* PC, bool bEligible, float DeltaS)
{
    UPrimitiveComponent* Body = BatteryBody.Get();
    AActor* Assembly = BatteryActor.Get();
    if (!bEligible || !PC || !PC->PlayerCameraManager || !Body || !Assembly || Assembly->IsHidden() ||
        !Body->IsVisible() || Body->bHiddenInGame)
    {
        BatteryGaze.Reset();
        return;
    }
    const FVector Eye = PC->PlayerCameraManager->GetCameraLocation();
    const FVector Forward = PC->PlayerCameraManager->GetCameraRotation().Vector();
    const FVector Target = Body->Bounds.Origin;
    const FVector Delta = Target - Eye;
    const double Distance = Delta.Size();
    int32 Width = 0, Height = 0;
    PC->GetViewportSize(Width, Height);
    FVector2D Screen;
    const bool bInFrame = Distance > 1.0 && Distance <= 650.0 && FVector::DotProduct(Forward, Delta) > 0.0 &&
        PC->ProjectWorldLocationToScreen(Target, Screen, true) && Width > 0 && Height > 0 &&
        Screen.X >= 0.0 && Screen.Y >= 0.0 && Screen.X <= Width && Screen.Y <= Height;
    if (!bInFrame) { BatteryGaze.Reset(); return; }
    const double CosAngle = FVector::DotProduct(Forward, Delta / Distance);
    const float BodyAngle = FMath::RadiansToDegrees(FMath::Atan2(Body->Bounds.SphereRadius, Distance));
    // Turning to inspect the roof should reveal the charge without pixel hunting on a small lamp.
    const float EnterAngle = FMath::Clamp(BodyAngle + 14.f, 18.f, 35.f);
    const bool bEnter = CosAngle >= FMath::Cos(FMath::DegreesToRadians(EnterAngle));
    const bool bStay = CosAngle >= FMath::Cos(FMath::DegreesToRadians(EnterAngle + 8.f));
    if (!bStay) { BatteryGaze.Step(DeltaS, true, false, false); return; }

    FCollisionQueryParams Params(SCENE_QUERY_STAT(SaskartaBatteryGaze), true);
    Params.AddIgnoredActor(Assembly);
    // Ignore the capsule surrounding the eye, but keep the carrier's roof/mesh eligible to occlude.
    if (ACharacter* Carrier = BatteryCarrier.Get()) Params.AddIgnoredComponent(Carrier->GetCapsuleComponent());
    const FVector Upper = Target + FVector(0.f, 0.f, Body->Bounds.BoxExtent.Z * 0.8f);
    bool bVisible = false;
    for (const FVector& Aim : {Target, Upper})
    {
        FHitResult Hit;
        if (!GetWorld()->LineTraceSingleByChannel(Hit, Eye, Aim, ECC_Visibility, Params)) { bVisible = true; break; }
    }
    BatteryGaze.Step(DeltaS, bVisible, bEnter, bStay);
}

void USaskartaPowerSubsystem::OnLampsPressed()
{
    const APlayerController* PC = FindController();
    const UWorld* World = GetWorld();
    const USaskartaEventRunner* Runner = World ? World->GetSubsystem<USaskartaEventRunner>() : nullptr;
    if (!PC || !Runner || PC->IsMoveInputIgnored() || Runner->IsHoldingInput() || Runner->IsPromptActive() ||
        SaskartaPower::CVarEnable.GetValueOnGameThread() == 0)
    {
        return;
    }
    const FName Flow = Runner->GetFlowState();
    if (Flow == SaskartaPower::Playing || Flow == SaskartaPower::FlowCarrier)
    {
        bLampsOn = !bLampsOn;
    }
}

void USaskartaPowerSubsystem::ApplyLamps(ACharacter* Carrier)
{
    if (!Carrier)
    {
        return;
    }
    const int32 Want = bLampsOn ? 1 : 0; // limp never cuts the lamps (ROUTE_BOARD_V3.md)
    if (LampCarrier.Get() == Carrier && AppliedLamps == Want)
    {
        return;
    }
    // Visibility, not intensity: DriveStep's LightsStep sets intensity every tick (off in Off/Shutdown).
    TArray<ULightComponent*> Lights;
    Carrier->GetComponents(Lights);
    for (ULightComponent* Light : Lights)
    {
        if (Light && (Light->GetFName() == SaskartaPower::HeadlightL || Light->GetFName() == SaskartaPower::HeadlightR))
        {
            Light->SetVisibility(Want == 1);
        }
    }
    LampCarrier = Carrier;
    AppliedLamps = Want;
}

void USaskartaPowerSubsystem::Poll()
{
    UWorld* World = GetWorld();
    if (!World)
    {
        return;
    }
    const double NowS = World->GetTimeSeconds();
    const float DeltaS = LastPollS < 0.0 ? 0.f : static_cast<float>(NowS - LastPollS);
    LastPollS = NowS;

    APlayerController* PC = FindController();
    ACharacter* Carrier = ActiveCarrier.Get();
    if (bEmptyBrakesOwned && (!Carrier || EmptyDriveCarrier.Get() != Carrier || !PC || PC->GetPawn() != Carrier))
    {
        ReleaseEmptyDrive();
        bEmptyEpisode = true;
    }
    if (SaskartaPower::CVarEnable.GetValueOnGameThread() == 0)
    {
        ReleaseEmptyDrive();
        bEmptyEpisode = false;
        bLampsOn = true;
        Core.Load(FSaskartaPowerSaveState{Core.Charge, 0.f, false});
        ApplyLamps(Carrier);
        BatteryGaze.Reset();
        if (Widget) Widget->ShowPower(false, false, false, FSaskartaPowerHudInput(), FSaskartaPowerHudOutput(), Telemetry);
        if (WidgetPlane) WidgetPlane->SetVisibility(false);
        return;
    }

    const USaskartaEventRunner* Runner = World->GetSubsystem<USaskartaEventRunner>();
    const FName Flow = Runner ? Runner->GetFlowState() : NAME_None;
    const bool bDriving = Carrier && PC && PC->GetPawn() == Carrier;
    USaskartaRadioStation* Station = USaskartaRadioStation::GetRadioStation(this);

    FSaskartaPowerInput In;
    In.DeltaS = DeltaS;
    In.bPlaying = bDriving && (Flow == SaskartaPower::Playing || Flow == SaskartaPower::FlowCarrier);
    const USaskartaMotorResonanceSubsystem* Motor = World->GetSubsystem<USaskartaMotorResonanceSubsystem>();
    // Pursuit/tuning own a move lock. An empty battery also parks the carrier. Neither is a cinematic:
    // drive consumption and passive stopped recharge must continue through those movement restrictions.
    In.bCinematic = !PC || World->IsPaused() || (Runner && (Runner->IsHoldingInput() || Runner->IsCinematicActive())) ||
        (PC->IsMoveInputIgnored() && !Core.bLimp && !(Motor && Motor->IsActive()));
    In.SpeedMps = bDriving ? Carrier->GetVelocity().Size2D() / 100.f : 0.f;
    In.Grade = bDriving ? SaskartaPower::FloorGrade(Carrier) : 0.f;
    In.bRadioRequested = Station && Station->IsRadioOn();
    In.bRadioForced = Station && Station->IsRadioForcedOn();
    In.bLampsRequested = bLampsOn;
    In.bTurboHeld = PC && (PC->IsInputKeyDown(EKeys::LeftShift) || PC->IsInputKeyDown(EKeys::Gamepad_RightTrigger));
    const USaskartaRouteLog* Log = World->GetSubsystem<USaskartaRouteLog>();
    In.bListening = Station && Station->IsRecallPlaying();
    // Motor tuning parks movement while the generator keeps charging.
    if (PC && ((Log && Log->IsOpen()) || bRestActivityOpen) &&
        !(Runner && (Runner->IsHoldingInput() || Runner->IsCinematicActive())))
    {
        In.bCinematic = false;
    }
    Core.Tuning.GeneratorPerS = FMath::Clamp(SaskartaPower::CVarGenerator.GetValueOnGameThread(), 0.f, 5.f);
    Core.Step(In);

    if ((Core.bLimp || Core.Charge <= 0.f) && Carrier) ApplyDriveLimits(Carrier, 0.f, false);
    else if (!Core.bLimp && Core.Charge > 0.f) { ReleaseEmptyDrive(); bEmptyEpisode = false; }
    UpdateEmptyAudio();
    if (ChargeAudio) ChargeAudio->Update(!In.bCinematic && Core.IsCharging(), Core.Charge, World->GetTimeSeconds());
    UpdateBattery(Carrier);

    ApplyLamps(Carrier);

    const bool bRadioSwitch = In.bRadioRequested && !In.bRadioForced;
    FSaskartaPowerHudInput HudIn;
    HudIn.Charge = Core.Charge;
    HudIn.RatePerS = Core.LastRatePerS;
    HudIn.bLimp = Core.bLimp;
    HudIn.bTurbo = Core.bTurbo;
    HudIn.bResting = Core.CanRest();
    HudIn.bRadioOn = In.bRadioRequested;
    HudIn.bLampsOn = bLampsOn;
    HudIn.RangeKm = Core.RangeKm(bRadioSwitch, bLampsOn);
    HudIn.SecondsToFull = Core.SecondsToFull(bRadioSwitch || In.bListening, bLampsOn);
    HudIn.bMotorReady = Log && !Log->IsOpen() && Log->CanOpen();
    HudIn.bGamepad = FSaskartaInputDevice::IsGamepad();
    HudIn.bLow = Core.IsLow();
    HudIn.bBlink = Core.Charge < Core.Tuning.BlinkPercent && !Core.bLimp;
    HudIn.bAscii = SaskartaPower::CVarAscii.GetValueOnGameThread() != 0;
    HudIn.bInscriptionReading = bInscriptionReading;
    if (bTelemetryOpen && Carrier)
    {
        // Read the existing drivetrain's engine model; never manufacture RPM from road speed.
        if (const FNumericProperty* RpmProperty = FindFProperty<FNumericProperty>(Carrier->GetClass(), TEXT("RPM")))
        {
            const void* Value = RpmProperty->ContainerPtrToValuePtr<void>(Carrier);
            const double Rpm = RpmProperty->IsFloatingPoint() ? RpmProperty->GetFloatingPointPropertyValue(Value) :
                static_cast<double>(RpmProperty->GetSignedIntPropertyValue(Value));
            if (FMath::IsFinite(Rpm) && Rpm >= 0.0) HudIn.MotorRpm = static_cast<float>(Rpm);
        }
    }
    const bool bCanDisplay = CanUseInstruments(PC);
    UpdateBatteryGaze(PC, bCanDisplay, DeltaS);
    if (In.bPlaying && !In.bCinematic && Carrier)
        Telemetry.Push(Carrier->GetVelocity().Size(), Carrier->GetActorLocation().Z, NowS);
    // Control teaching belongs to the single authored gameplay notification.
    // The power panel carries charge and system faults only.
    const bool bShow = bCanDisplay;
    UpdateWidget(PC, bShow, HudIn, DeltaS);
}

void USaskartaPowerSubsystem::ApplyDriveLimits(ACharacter* Carrier, float Throttle, bool bReversing)
{
    UWorld* World = IsValid(Carrier) ? Carrier->GetWorld() : nullptr;
    USaskartaPowerSubsystem* Power = World ? World->GetSubsystem<USaskartaPowerSubsystem>() : nullptr;
    UCharacterMovementComponent* Move = Carrier ? Carrier->GetCharacterMovement() : nullptr;
    if (!Power || !Move)
    {
        return;
    }
    Power->ActiveCarrier = Carrier;
    if (SaskartaPower::CVarEnable.GetValueOnGameThread() == 0)
    {
        Power->ReleaseEmptyDrive();
        Power->bEmptyEpisode = false;
        return;
    }
    if (Power->Core.bLimp || Power->Core.Charge <= 0.f)
    {
        Power->ApplyEmptyDrive(Carrier);
        return;
    }
    Power->ReleaseEmptyDrive();
    Power->bEmptyEpisode = false;
    if (Power->Core.bTurbo && !bReversing && FMath::IsFinite(Throttle) && Throttle > 0.55f)
    {
        const float Grade = SaskartaPower::FloorGrade(Carrier);
        Move->MaxWalkSpeed = Grade < SaskartaPower::TurboSteepGrade
            ? FMath::Max(Move->MaxWalkSpeed, SaskartaPower::TurboFlatMaxCmS)
            : Move->MaxWalkSpeed + SaskartaPower::TurboSteepBonusCmS;
        Move->MaxAcceleration = FMath::Max(Move->MaxAcceleration, SaskartaPower::TurboAccelCmS2);
    }
}

void USaskartaPowerSubsystem::ReleaseEmptyDrive()
{
    if (!bEmptyBrakesOwned && !EmptyDriveCarrier.IsValid() && EmptyAudioStage == 0) return;
    if (ACharacter* Carrier = EmptyDriveCarrier.Get())
    {
        if (UCharacterMovementComponent* Move = Carrier->GetCharacterMovement(); Move && bEmptyBrakesOwned)
        {
            // Restore only values this owner still holds. DriveStep and a cinematic
            // may have already installed fresh limits before this cleanup arrives.
            if (FMath::IsNearlyEqual(Move->MaxWalkSpeed, AppliedEmptyMaxSpeed)) Move->MaxWalkSpeed = PreviousEmptyMaxSpeed;
            if (FMath::IsNearlyZero(Move->MaxAcceleration)) Move->MaxAcceleration = PreviousEmptyAcceleration;
            if (FMath::IsNearlyEqual(Move->BrakingDecelerationWalking, EmptyCoastBraking)) Move->BrakingDecelerationWalking = PreviousEmptyBraking;
            if (FMath::IsNearlyEqual(Move->BrakingFriction, SaskartaPower::EmptyFriction)) Move->BrakingFriction = PreviousEmptyFriction;
            if (FMath::IsNearlyEqual(Move->BrakingFrictionFactor, 1.f)) Move->BrakingFrictionFactor = PreviousEmptyFrictionFactor;
            if (Move->bUseSeparateBrakingFriction) Move->bUseSeparateBrakingFriction = bPreviousSeparateBraking;
        }
    }
    EmptyDriveCarrier.Reset();
    bEmptyBrakesOwned = false;
    bEmptyCoasting = false;
    LastEmptyDriveS = -1.0;
    StopEmptyAudio();
}

void USaskartaPowerSubsystem::ApplyEmptyDrive(ACharacter* Carrier)
{
    UWorld* World = GetWorld();
    UCharacterMovementComponent* Move = Carrier ? Carrier->GetCharacterMovement() : nullptr;
    const APlayerController* PC = Carrier ? Cast<APlayerController>(Carrier->GetController()) : nullptr;
    const USaskartaEventRunner* Runner = World ? World->GetSubsystem<USaskartaEventRunner>() : nullptr;
    if (!World || !Move) return;
    const double NowS = World->GetTimeSeconds();
    const FName Flow = Runner ? Runner->GetFlowState() : NAME_None;
    const bool bFreeDrive = PC && PC->GetPawn() == Carrier && Runner
        && (Flow == SaskartaPower::Playing || Flow == SaskartaPower::FlowCarrier)
        && !World->IsPaused() && !Runner->IsCinematicActive() && !Runner->IsHoldingInput()
        && !Runner->IsPromptActive() && FMath::IsFinite(World->GetDeltaSeconds()) && World->GetDeltaSeconds() <= .5f;
    if (bEmptyBrakesOwned && EmptyDriveCarrier.Get() != Carrier)
    {
        ReleaseEmptyDrive();
        bEmptyEpisode = true; // replacement/possessed pawns do not inherit a depletion coast
    }
    if (!bFreeDrive)
    {
        // A cinematic takes back its authored movement limits, including driving
        // arrival shots. Gameplay pause/hitches cancel a coast without resuming it.
        if (bEmptyBrakesOwned && !(Runner && Runner->IsCinematicActive()) && !Move->Velocity.IsNearlyZero()) Move->StopMovementImmediately();
        ReleaseEmptyDrive();
        bEmptyEpisode = true;
        return;
    }
    Carrier->ConsumeMovementInputVector();
    for (const TCHAR* Name : {TEXT("InputScale"), TEXT("MoveX"), TEXT("MoveY"), TEXT("Throttle"),
        TEXT("PrevThrottle"), TEXT("Steer"), TEXT("TurnRateNow"), TEXT("StuckTime")})
        if (FNumericProperty* Property = FindFProperty<FNumericProperty>(Carrier->GetClass(), Name))
            if (Property->IsFloatingPoint())
                Property->SetFloatingPointPropertyValue(Property->ContainerPtrToValuePtr<void>(Carrier), 0.0);
    if (!bEmptyBrakesOwned)
    {
        EmptyDriveCarrier = Carrier;
        PreviousEmptyMaxSpeed = Move->MaxWalkSpeed;
        PreviousEmptyAcceleration = Move->MaxAcceleration;
        PreviousEmptyBraking = Move->BrakingDecelerationWalking;
        PreviousEmptyFriction = Move->BrakingFriction;
        PreviousEmptyFrictionFactor = Move->BrakingFrictionFactor;
        bPreviousSeparateBraking = Move->bUseSeparateBrakingFriction;
        const float InitialSpeed = Move->Velocity.Size2D();
        bEmptyCoasting = !bEmptyEpisode && Move->IsMovingOnGround() && FMath::IsFinite(InitialSpeed) && InitialSpeed > 20.f;
        EmptyCoastStartedS = NowS;
        // dv/dt = -k*v-a. This constant a reaches zero in 1.75s under UE's
        // own substepped braking, without a new velocity assignment each frame.
        EmptyCoastBraking = FMath::Max(20.f, InitialSpeed * SaskartaPower::EmptyFriction
            / (FMath::Exp(SaskartaPower::EmptyFriction * SaskartaPower::EmptyCoastS) - 1.f));
        AppliedEmptyMaxSpeed = bEmptyCoasting ? FMath::Max(InitialSpeed, Move->MaxWalkSpeed) : 0.f;
        bEmptyBrakesOwned = true;
        Move->ClearAccumulatedForces(); // discard a powered nudge queued before fuel reached zero
        if (!bEmptyEpisode) StartEmptyAudio();
        bEmptyEpisode = true;
        if (!bEmptyCoasting && !Move->Velocity.IsNearlyZero()) Move->StopMovementImmediately();
    }
    const bool bGap = LastEmptyDriveS >= 0.0 && NowS - LastEmptyDriveS > .5;
    if (bEmptyCoasting && (bGap || NowS - EmptyCoastStartedS >= SaskartaPower::EmptyCoastS || Move->Velocity.Size2D() <= 10.f))
    {
        bEmptyCoasting = false;
        Move->StopMovementImmediately(); // one terminal park, not the depletion transition
        AppliedEmptyMaxSpeed = 0.f;
        StopEmptyAudio();
    }
    LastEmptyDriveS = NowS;
    Move->MaxWalkSpeed = AppliedEmptyMaxSpeed;
    Move->MaxAcceleration = 0.f;
    Move->bUseSeparateBrakingFriction = true;
    Move->BrakingFriction = SaskartaPower::EmptyFriction;
    Move->BrakingFrictionFactor = 1.f;
    Move->BrakingDecelerationWalking = EmptyCoastBraking;
}

void USaskartaPowerSubsystem::StopEmptyAudio()
{
    if (EmptyAudioStage > 0 && IsValid(EmptyAudio)) EmptyAudio->Stop();
    EmptyAudioStage = 0;
    EmptyAudioStartedS = -1.0;
}

void USaskartaPowerSubsystem::StartEmptyAudio()
{
    if (!EmptySoundLoad.IsValid() || !EmptySoundLoad->HasLoadCompleted()) return;
    if (EmptySounds.IsEmpty())
        for (const FSoftObjectPath& Path : SaskartaPower::EmptySoundPaths)
            EmptySounds.Add(Cast<USoundBase>(Path.ResolveObject()));
    if (EmptySounds.Num() != 3 || !EmptySounds[0] || !EmptySounds[1] || !EmptySounds[2]) return;
    const float WarningS = EmptySounds[0]->GetDuration();
    if (!FMath::IsFinite(WarningS) || WarningS <= 0.f || WarningS > .8f) return;
    const USaskartaEventRunner* Runner = GetWorld()->GetSubsystem<USaskartaEventRunner>();
    const bool bVoiceBusy = Runner && Runner->IsVoiceBusy();
    EmptyAudioStage = bVoiceBusy ? 2 : 1;
    USoundBase* Sound = EmptySounds[EmptyAudioStage - 1];
    if (!IsValid(EmptyAudio)) EmptyAudio = UGameplayStatics::CreateSound2D(this, Sound, 1.f, 1.f, 0.f, nullptr, false, false);
    if (!EmptyAudio) { EmptyAudioStage = 0; return; }
    EmptyAudio->bIsUISound = false;
    EmptyAudio->SetSound(Sound);
    EmptyAudio->SetPitchMultiplier(1.f);
    EmptyAudio->FadeIn(.03f, bVoiceBusy ? .08f : .35f);
    EmptyAudioStartedS = GetWorld()->GetTimeSeconds();
}

void USaskartaPowerSubsystem::UpdateEmptyAudio()
{
    if (EmptyAudioStage <= 0 || !IsValid(EmptyAudio) || !GetWorld()) return;
    const double Elapsed = GetWorld()->GetTimeSeconds() - EmptyAudioStartedS;
    if (!bEmptyBrakesOwned || GetWorld()->IsPaused() || Elapsed < 0.0 || Elapsed > 1.8
        || (!bEmptyCoasting && (EmptyAudioStage != 1 || Elapsed > .32)))
    {
        StopEmptyAudio();
        return;
    }
    if (Elapsed >= .65 && EmptyAudioStage < 3)
    {
        EmptyAudioStage = 3;
        EmptyAudio->SetSound(EmptySounds[2]);
        EmptyAudio->SetPitchMultiplier(.88f);
        EmptyAudio->FadeIn(.035f, .18f);
    }
    else if (Elapsed >= .75 && EmptyAudioStage == 3)
    {
        EmptyAudioStage = 4;
        EmptyAudio->FadeOut(.85f, 0.f);
    }
    else if (Elapsed >= .32 && EmptyAudioStage == 1)
    {
        EmptyAudioStage = 2;
        EmptyAudio->SetSound(EmptySounds[1]);
        EmptyAudio->SetPitchMultiplier(.92f);
        EmptyAudio->FadeIn(.025f, .2f);
    }
    else if (EmptyAudioStage == 2)
        EmptyAudio->AdjustVolume(.04f, FMath::Fmod(static_cast<float>(Elapsed), .2f) < .1f ? .2f : .055f);
}

void USaskartaPowerSubsystem::UpdateWidget(APlayerController* PC, bool bShow,
    const FSaskartaPowerHudInput& HudIn, float DeltaS)
{
    // Instruments are transparent screen UI. The separate motor activity retains its authored display.
    // ToggleDebugCamera temporarily detaches the LocalPlayer from the original
    // controller. IsLocalController() alone can remain true during that handoff.
    const bool bLocal = PC && PC->IsLocalController() && PC->GetLocalPlayer();
    if (Widget && (!bLocal || Widget->GetOwningPlayer() != PC))
    {
        Widget->RemoveFromParent();
        Widget = nullptr;
    }
    if (!bLocal) return;
    if (!Widget && bShow)
    {
        Widget = CreateWidget<USaskartaPowerWidget>(PC, SaskartaRuntimeWidgetClass(USaskartaPowerWidget::StaticClass(),
            TEXT("/Game/SaskartaGaea/GameFlow/UI/WBP_Saskarta_Power.WBP_Saskarta_Power_C")));
        if (Widget) Widget->AddToViewport(35);
    }
    if (Widget)
        Widget->ShowPower(bShow, BatteryGaze.bVisible, bTelemetryOpen, HudIn, Hud.Step(DeltaS, HudIn), Telemetry);
}

void USaskartaPowerSubsystem::AttachDisplayToView(APlayerController* PC)
{
    // Kept for the existing subsystem interface; the instruments now render directly in the viewport.
}
