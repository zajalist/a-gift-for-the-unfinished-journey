#include "SaskartaRadioRepair.h"

#include "Blueprint/WidgetTree.h"
#include "Components/Border.h"
#include "Components/CanvasPanel.h"
#include "Components/CanvasPanelSlot.h"
#include "Components/ProgressBar.h"
#include "Components/RetainerBox.h"
#include "Components/TextBlock.h"
#include "Components/Image.h"
#include "Components/SizeBox.h"
#include "Components/VerticalBox.h"
#include "Components/VerticalBoxSlot.h"
#include "Engine/Font.h"
#include "Engine/GameViewportClient.h"
#include "Engine/World.h"
#include "Framework/Application/IInputProcessor.h"
#include "Framework/Application/SlateApplication.h"
#include "GameFramework/Character.h"
#include "GameFramework/CharacterMovementComponent.h"
#include "GameFramework/PlayerController.h"
#include "Kismet/GameplayStatics.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "SaskartaEventRunner.h"
#include "SaskartaMotorResonance.h"
#include "SaskartaOnboarding.h"
#include "SaskartaPower.h"
#include "SaskartaRadioStation.h"
#include "SaskartaRouteMap.h"
#include "SaskartaSaveGame.h"
#include "SaskartaSteleScanner.h"
#include "SaskartaTelemetryGraph.h"
#include "Widgets/SViewport.h"

DEFINE_LOG_CATEGORY_STATIC(LogSaskartaRadioRepair, Log, All);

namespace SaskartaRadioRepair
{
    bool EntryKey(const FKey& Key) { return Key == EKeys::T || Key == EKeys::Gamepad_FaceButton_Top; }
    bool ConfirmKey(const FKey& Key) { return Key == EKeys::E || Key == EKeys::Gamepad_FaceButton_Bottom; }
    bool AdjustmentKey(const FKey& Key)
    {
        return Key == EKeys::A || Key == EKeys::D || Key == EKeys::W || Key == EKeys::S ||
            Key == EKeys::Gamepad_DPad_Left || Key == EKeys::Gamepad_DPad_Right ||
            Key == EKeys::Gamepad_DPad_Up || Key == EKeys::Gamepad_DPad_Down;
    }
    bool DriveFlow(FName Flow) { return Flow == TEXT("Playing") || Flow == TEXT("Carrier"); }
}

void USaskartaRadioRepairWidget::NativeOnInitialized()
{
    Super::NativeOnInitialized();
    SetIsFocusable(false);
    SetVisibility(ESlateVisibility::Collapsed);
    if (!WidgetTree) return;
    if (WidgetTree->RootWidget)
    {
        Card = Cast<UCanvasPanel>(GetWidgetFromName(TEXT("RepairCard")));
        Prompt = Cast<UBorder>(GetWidgetFromName(TEXT("ReceptionPrompt")));
        PromptText = Cast<UTextBlock>(GetWidgetFromName(TEXT("ReceptionAction")));
        PromptKey = Cast<UTextBlock>(GetWidgetFromName(TEXT("ReceptionKey")));
        PromptGlyph = Cast<UImage>(GetWidgetFromName(TEXT("ReceptionGlyph")));
        PromptGlyphBounds = Cast<USizeBox>(GetWidgetFromName(TEXT("ReceptionGlyphBounds")));
        StageText = Cast<UTextBlock>(GetWidgetFromName(TEXT("RepairStage")));
        ValueText = Cast<UTextBlock>(GetWidgetFromName(TEXT("RepairValues")));
        HintText = Cast<UTextBlock>(GetWidgetFromName(TEXT("RepairInstructions")));
        StabilityText = Cast<UTextBlock>(GetWidgetFromName(TEXT("RepairStability")));
        FooterText = Cast<UTextBlock>(GetWidgetFromName(TEXT("RepairExit")));
        SignalBar = Cast<UProgressBar>(GetWidgetFromName(TEXT("SignalBar")));
        StabilityBar = Cast<UProgressBar>(GetWidgetFromName(TEXT("StabilityBar")));
        EnvelopeGraph = Cast<USaskartaTelemetryGraph>(GetWidgetFromName(TEXT("EnvelopeGraph")));
        if (!Card || !Prompt || !PromptText || !PromptKey || !PromptGlyph || !PromptGlyphBounds
            || !StageText || !ValueText || !HintText || !StabilityText || !FooterText || !SignalBar || !StabilityBar || !EnvelopeGraph)
        {
            UE_LOG(LogSaskartaRadioRepair, Error, TEXT("Authored radio repair UMG has missing or mistyped bindings"));
            Card = nullptr;
        }
        return;
    }
    UCanvasPanel* Root = WidgetTree->ConstructWidget<UCanvasPanel>();
    WidgetTree->RootWidget = Root;
    Card = WidgetTree->ConstructWidget<UCanvasPanel>();
    UCanvasPanelSlot* CardSlot = Root->AddChildToCanvas(Card);
    CardSlot->SetAnchors(FAnchors(0.5f, 0.43f));
    CardSlot->SetAlignment(FVector2D(0.5f, 0.5f));
    CardSlot->SetSize(FVector2D(1056.f, 760.f));
    UBorder* Glass = WidgetTree->ConstructWidget<UBorder>();
    Glass->SetBrushColor(FLinearColor(0.006f, 0.008f, 0.006f, 0.96f));
    Root->SetVisibility(ESlateVisibility::HitTestInvisible);
    Card->AddChildToCanvas(Glass)->SetSize(FVector2D(1056.f, 760.f));
    Retainer = WidgetTree->ConstructWidget<URetainerBox>();
    Retainer->SetTextureParameter(TEXT("Texture"));
    Retainer->SetRenderingPhase(0, 2);
    if (UMaterialInterface* Effect = LoadObject<UMaterialInterface>(nullptr,
        TEXT("/Game/SaskartaGaea/GameFlow/Materials/MI_UI_RadioCRT.MI_UI_RadioCRT")))
    {
        UMaterialInstanceDynamic* Instance = UMaterialInstanceDynamic::Create(Effect, this);
        Instance->SetScalarParameterValue(TEXT("ScanlineCount"), 240.f);
        Instance->SetScalarParameterValue(TEXT("GlowRadius"), 3.f);
        Retainer->SetEffectMaterial(Instance);
    }
    UCanvasPanelSlot* RetainerSlot = Card->AddChildToCanvas(Retainer);
    RetainerSlot->SetPosition(FVector2D(24.f, 18.f));
    RetainerSlot->SetSize(FVector2D(1008.f, 724.f));
    UVerticalBox* Content = WidgetTree->ConstructWidget<UVerticalBox>();
    Retainer->SetContent(Content);
    UFont* Font = LoadObject<UFont>(nullptr, TEXT("/Game/SaskartaGaea/GameFlow/UI/Fonts/Font_Terminal.Font_Terminal"));
    auto Text = [&](const TCHAR* Name, int32 Size)
    {
        UTextBlock* Label = WidgetTree->ConstructWidget<UTextBlock>(UTextBlock::StaticClass(), Name);
        FSlateFontInfo Info = Label->GetFont();
        if (Font) Info = FSlateFontInfo(Font, Size); else Info.Size = Size;
        Label->SetFont(Info);
        Label->SetColorAndOpacity(FLinearColor::White);
        Label->SetAutoWrapText(true);
        Label->SetWrapTextAt(1008.f);
        Content->AddChildToVerticalBox(Label)->SetPadding(FMargin(0.f, 0.f, 0.f, 8.f));
        return Label;
    };
    Text(TEXT("ReceiverTitle"), 42)->SetText(FText::FromString(TEXT("CISTERN / RECEIVER ALIGNMENT")));
    StageText = Text(TEXT("RepairStage"), 38);
    ValueText = Text(TEXT("RepairValues"), 36);
    SignalBar = WidgetTree->ConstructWidget<UProgressBar>();
    SignalBar->SetFillColorAndOpacity(FLinearColor::White);
    Content->AddChildToVerticalBox(SignalBar)->SetPadding(FMargin(0.f, 4.f, 0.f, 8.f));
    HintText = Text(TEXT("RepairInstructions"), 36);
    Text(TEXT("EnvelopeLabel"), 36)->SetText(FText::FromString(TEXT("LIVE VOICE ENVELOPE . RANGE 0 - 0.1")));
    EnvelopeGraph = WidgetTree->ConstructWidget<USaskartaTelemetryGraph>();
    Content->AddChildToVerticalBox(EnvelopeGraph)->SetPadding(FMargin(0.f, 0.f, 0.f, 8.f));
    StabilityText = Text(TEXT("RepairStability"), 36);
    StabilityBar = WidgetTree->ConstructWidget<UProgressBar>();
    StabilityBar->SetFillColorAndOpacity(FLinearColor::White);
    Content->AddChildToVerticalBox(StabilityBar)->SetPadding(FMargin(0.f, 0.f, 0.f, 8.f));
    FooterText = Text(TEXT("RepairExit"), 36);

    Prompt = WidgetTree->ConstructWidget<UBorder>();
    Prompt->SetBrushColor(FLinearColor::Transparent);
    Prompt->SetPadding(FMargin(0.f));
    PromptText = WidgetTree->ConstructWidget<UTextBlock>();
    FSlateFontInfo PromptFont = PromptText->GetFont();
    if (Font) PromptFont = FSlateFontInfo(Font, 20); else PromptFont.Size = 20;
    PromptText->SetFont(PromptFont);
    PromptText->SetColorAndOpacity(FLinearColor(.94f, .91f, .81f));
    PromptText->SetShadowColorAndOpacity(FLinearColor(0.f, 0.f, 0.f, .92f));
    PromptText->SetShadowOffset(FVector2D(1.5f, 2.f));
    Prompt->SetContent(PromptText);
    UCanvasPanelSlot* PromptSlot = Root->AddChildToCanvas(Prompt);
    PromptSlot->SetAnchors(FAnchors(0.f, 1.f));
    PromptSlot->SetAlignment(FVector2D(0.f, 1.f));
    PromptSlot->SetPosition(FVector2D(28.f, -32.f));
    PromptSlot->SetAutoSize(true);
    SetVisibility(ESlateVisibility::Collapsed);
}

void USaskartaRadioRepairWidget::Present(bool bOpen, bool bPrompt, bool bParked, bool bPad,
    const FSaskartaRadioRepairLogic& State, const TArray<FVector2D>& VoiceEnvelope)
{
    if (!Card || !Prompt || !PromptText) return;
    SetVisibility(bOpen || bPrompt ? ESlateVisibility::HitTestInvisible : ESlateVisibility::Collapsed);
    Card->SetVisibility(bOpen ? ESlateVisibility::HitTestInvisible : ESlateVisibility::Collapsed);
    Prompt->SetVisibility(bPrompt && !bOpen ? ESlateVisibility::HitTestInvisible : ESlateVisibility::Collapsed);
    auto SetText = [](UTextBlock* Label, const FString& Value)
    {
        if (Label->GetText().ToString() != Value) Label->SetText(FText::FromString(Value));
    };
    if (bPrompt && !bOpen)
    {
        if (PromptKey && PromptGlyph && PromptGlyphBounds)
        {
            PromptGlyphBounds->SetVisibility(bParked ? ESlateVisibility::HitTestInvisible : ESlateVisibility::Collapsed);
            PromptGlyph->SetVisibility(bPad ? ESlateVisibility::HitTestInvisible : ESlateVisibility::Collapsed);
            PromptKey->SetVisibility(bPad ? ESlateVisibility::Collapsed : ESlateVisibility::HitTestInvisible);
            SetText(PromptText, bParked ? TEXT("ADJUST THE AERIAL") : TEXT("PARK TO ADJUST THE AERIAL"));
        }
        else SetText(PromptText, bParked ? (bPad ? TEXT("Y . ADJUST THE AERIAL") : TEXT("T . ADJUST THE AERIAL")) :
            TEXT("PARK TO ADJUST THE AERIAL"));
    }
    if (!bOpen) return;
    const bool bAerial = State.Stage == FSaskartaRadioRepairLogic::EStage::Aerial;
    SetText(StageText, State.IsComplete() ? TEXT("SIGNAL STABLE / RECEIVER ALIGNED") :
        bAerial ? TEXT("1 / AIM THE AERIAL") : TEXT("2 / FINE TUNE . 3 / HOLD STEADY"));
    const float Quality = bAerial ? State.AerialQuality() : State.Signal();
    SetText(ValueText, FString::Printf(TEXT("AERIAL %+.0f DEG   TUNE %+.2f   SIGNAL %.0f%%"),
        State.AerialDeg, State.Frequency, Quality * 100.f));
    SignalBar->SetPercent(Quality);
    if (State.IsComplete()) SetText(HintText, TEXT("The programme continues. You can drive on."));
    else if (bAerial)
        SetText(HintText, State.CanLockAerial() ? (bPad ? TEXT("STRONG SIGNAL . A / CROSS TO LOCK") : TEXT("STRONG SIGNAL . E TO LOCK DIRECTION")) :
            (bPad ? TEXT("HOLD D-PAD LEFT / RIGHT . FIND THE STRONG SIGNAL") : TEXT("HOLD A / D . TURN TOWARD THE STRONG SIGNAL")));
    else SetText(HintText, bPad ? TEXT("D-PAD UP / DOWN . PEAK THE SIGNAL, THEN RELEASE") : TEXT("HOLD W / S . PEAK THE SIGNAL, THEN RELEASE"));
    SetText(StabilityText, State.IsComplete() ? TEXT("ALIGNMENT COMPLETE") : bAerial ?
        TEXT("LOCK DIRECTION AT 90% SIGNAL OR HIGHER") :
        FString::Printf(TEXT("HOLD STEADY  %.1f / 3.0 S . STRONG = 86%%+"), State.StableS));
    StabilityBar->SetPercent(State.StableS / FSaskartaRadioRepairLogic::StableDurationS);
    SetText(FooterText, bAerial || State.IsComplete() ?
        (bPad ? TEXT("Y / TRIANGLE CLOSE . MENU PAUSE") : TEXT("T CLOSE . ESC PAUSE")) :
        (bPad ? TEXT("Y / TRIANGLE CLOSE . A / CROSS RE-AIM . MENU PAUSE") : TEXT("T CLOSE . E RE-AIM . ESC PAUSE")));
    EnvelopeGraph->SetSamples(VoiceEnvelope);
    if (Retainer) Retainer->RequestRender();
}

class FSaskartaRadioRepairInput : public IInputProcessor
{
public:
    explicit FSaskartaRadioRepairInput(USaskartaRadioRepairSubsystem* InOwner) : Owner(InOwner) {}
    virtual void Tick(const float, FSlateApplication&, TSharedRef<ICursor>) override {}
    virtual bool HandleKeyDownEvent(FSlateApplication&, const FKeyEvent& Event) override
    { return Owner.IsValid() && Owner->HandleKey(Event.GetKey(), true, Event.IsRepeat()); }
    virtual bool HandleKeyUpEvent(FSlateApplication&, const FKeyEvent& Event) override
    { return Owner.IsValid() && Owner->HandleKey(Event.GetKey(), false, false); }
private:
    TWeakObjectPtr<USaskartaRadioRepairSubsystem> Owner;
};

bool USaskartaRadioRepairSubsystem::ShouldCreateSubsystem(UObject* Outer) const
{
    const UWorld* World = Cast<UWorld>(Outer);
    return World && World->IsGameWorld() && World->GetNetMode() != NM_DedicatedServer;
}

void USaskartaRadioRepairSubsystem::OnWorldBeginPlay(UWorld& World)
{
    Super::OnWorldBeginPlay(World);
    SaskartaRuntimeWidgetClass(USaskartaRadioRepairWidget::StaticClass(),
        TEXT("/Game/SaskartaGaea/GameFlow/UI/WBP_Saskarta_RadioRepair.WBP_Saskarta_RadioRepair_C"));
    WritingRunHandle = USaskartaSaveGame::OnWritingRun.AddUObject(this, &USaskartaRadioRepairSubsystem::HandleWritingRun);
    RestoredRunHandle = USaskartaSaveGame::OnRestoredRun.AddUObject(this, &USaskartaRadioRepairSubsystem::HandleRestoredRun);
    if (FSlateApplication::IsInitialized())
    {
        Processor = MakeShared<FSaskartaRadioRepairInput>(this);
        FSlateApplication::Get().RegisterInputPreProcessor(Processor);
    }
}

void USaskartaRadioRepairSubsystem::Deinitialize()
{
    Close(false);
    USaskartaSaveGame::OnWritingRun.Remove(WritingRunHandle);
    USaskartaSaveGame::OnRestoredRun.Remove(RestoredRunHandle);
    if (FSlateApplication::IsInitialized() && Processor.IsValid()) FSlateApplication::Get().UnregisterInputPreProcessor(Processor);
    Processor.Reset();
    if (Widget) { Widget->RemoveFromParent(); Widget = nullptr; }
    Super::Deinitialize();
}

TStatId USaskartaRadioRepairSubsystem::GetStatId() const
{ RETURN_QUICK_DECLARE_CYCLE_STAT(USaskartaRadioRepairSubsystem, STATGROUP_Tickables); }

APlayerController* USaskartaRadioRepairSubsystem::GetPC() const
{ return GetWorld() ? GetWorld()->GetFirstPlayerController() : nullptr; }

bool USaskartaRadioRepairSubsystem::InEncounter() const
{
    const USaskartaEventRunner* Runner = GetWorld() ? GetWorld()->GetSubsystem<USaskartaEventRunner>() : nullptr;
    return Runner && FSaskartaRadioRepairLogic::InZone(Runner->GetRoadM());
}

bool USaskartaRadioRepairSubsystem::ControlsAvailable() const
{
    const UWorld* World = GetWorld();
    const APlayerController* PC = GetPC();
    const USaskartaEventRunner* Runner = World ? World->GetSubsystem<USaskartaEventRunner>() : nullptr;
    const USaskartaMotorResonanceSubsystem* Motor = World ? World->GetSubsystem<USaskartaMotorResonanceSubsystem>() : nullptr;
    const USaskartaRouteMap* Map = World ? World->GetSubsystem<USaskartaRouteMap>() : nullptr;
    const USaskartaSteleScanner* Scanner = World ? World->GetSubsystem<USaskartaSteleScanner>() : nullptr;
    const USaskartaRadioStation* Station = World ? World->GetSubsystem<USaskartaRadioStation>() : nullptr;
    if (!World || World->IsPaused() || !PC || !PC->IsLocalController() || !Cast<ACharacter>(PC->GetPawn()) ||
        !Runner || !SaskartaRadioRepair::DriveFlow(Runner->GetFlowState()) || Runner->IsCinematicActive() ||
        Runner->IsHoldingInput() || Runner->IsPromptActive() || Runner->IsStorySubtitleActive() ||
        (Motor && Motor->IsActive()) || (Map && Map->IsOpen()) || (Scanner && Scanner->IsScanPromptVisible()) ||
        !Station || !Station->IsRadioOn() || Station->IsRadioForcedOn() || Station->IsSignalDead() || !InEncounter()) return false;
    if (bOpen && PC->GetPawn() != SessionPawn.Get()) return false;
    if (!bOpen && PC->IsMoveInputIgnored()) return false;
    if (!FSlateApplication::IsInitialized() || !FSlateApplication::Get().IsActive()) return false;
    const UGameViewportClient* Viewport = World->GetGameViewport();
    const TSharedPtr<SViewport> SlateViewport = Viewport ? Viewport->GetGameViewportWidget() : nullptr;
    return SlateViewport.IsValid() && SlateViewport->HasAnyUserFocusOrFocusedDescendants();
}

bool USaskartaRadioRepairSubsystem::CanOpen() const
{
    const APlayerController* PC = GetPC();
    const USaskartaPowerSubsystem* Power = GetWorld() ? GetWorld()->GetSubsystem<USaskartaPowerSubsystem>() : nullptr;
    return !bOpen && !Logic.IsComplete() && ControlsAvailable() && PC && !PC->IsMoveInputIgnored() &&
        PC->GetPawn()->GetVelocity().Size2D() <= 20.f && Power && Power->CanRest();
}

void USaskartaRadioRepairSubsystem::Open()
{
    if (!CanOpen()) return;
    APlayerController* PC = GetPC();
    bOpen = true; bResumePending = false; CompleteAgeS = 0.f; UiAgeS = 1.f;
    bPad = FSaskartaInputDevice::IsGamepad();
    SessionPawn = PC->GetPawn(); LockedController = PC;
    PC->SetIgnoreMoveInput(true); bOwnsMoveLock = true;
    CastChecked<ACharacter>(SessionPawn.Get())->GetCharacterMovement()->StopMovementImmediately();
    if (USaskartaPowerSubsystem* Power = GetWorld()->GetSubsystem<USaskartaPowerSubsystem>()) Power->SetRestActivityOpen(true);
    HeldKeys.Reset();
    SaveProgress();
    UE_LOG(LogSaskartaRadioRepair, Log, TEXT("Cistern receiver opened; stage %d"), static_cast<int32>(Logic.Stage));
}

void USaskartaRadioRepairSubsystem::ClearReception()
{
    if (USaskartaRadioStation* Station = GetWorld() ? GetWorld()->GetSubsystem<USaskartaRadioStation>() : nullptr)
        Station->SetRepairReception(false, 1.f);
}

void USaskartaRadioRepairSubsystem::Close(bool bSave)
{
    const bool bWasOpen = bOpen;
    bOpen = false; bResumePending = false; bWasAllowed = false;
    ClearReception();
    if (bOwnsMoveLock)
    {
        if (LockedController.IsValid()) LockedController->SetIgnoreMoveInput(false);
        if (USaskartaPowerSubsystem* Power = GetWorld() ? GetWorld()->GetSubsystem<USaskartaPowerSubsystem>() : nullptr)
            Power->SetRestActivityOpen(false);
    }
    bOwnsMoveLock = false; LockedController.Reset(); SessionPawn.Reset(); HeldKeys.Reset();
    if (bSave && bWasOpen) SaveProgress();
    if (Widget) Widget->SetVisibility(ESlateVisibility::Collapsed);
}

bool USaskartaRadioRepairSubsystem::HandleKey(const FKey& Key, bool bDown, bool bRepeat)
{
    if (!bOpen)
    {
        if (bDown && !bRepeat && SaskartaRadioRepair::EntryKey(Key) && CanOpen())
        { Open(); bPad = Key.IsGamepadKey(); return true; }
        return false;
    }
    if (!SaskartaRadioRepair::EntryKey(Key) && !SaskartaRadioRepair::ConfirmKey(Key) && !SaskartaRadioRepair::AdjustmentKey(Key)) return false;
    if (!bDown) { HeldKeys.Remove(Key); return false; }
    const bool bAllowed = ControlsAvailable();
    if (bRepeat) return bAllowed;
    if (!bAllowed) return false;
    bPad = Key.IsGamepadKey();
    if (SaskartaRadioRepair::EntryKey(Key)) { Close(true); return true; }
    if (SaskartaRadioRepair::ConfirmKey(Key))
    {
        if (Logic.Confirm()) { UiAgeS = 1.f; SaveProgress(); }
        return true;
    }
    HeldKeys.Add(Key);
    return true;
}

void USaskartaRadioRepairSubsystem::SaveProgress()
{
    USaskartaEventRunner* Runner = GetWorld() ? GetWorld()->GetSubsystem<USaskartaEventRunner>() : nullptr;
    if (!Runner || !InEncounter() || !GetPC() || !Cast<ACharacter>(GetPC()->GetPawn())) return;
    // Only interaction boundaries write, never a tick or a dial sample. This is an exact-pose encounter
    // checkpoint and invokes every existing station/power/world hook; no separate partial save slot.
    if (USaskartaSaveGame* Save = Runner->CreateCheckpointSnapshot(TEXT("CP_RADIO_REPAIR"), true))
    {
        // Station.Config.PlayFlowStates uses the canonical Playing flow. A paused snapshot must
        // restore that gameplay flow, not Paused or the legacy Carrier alias (which holds radio).
        Save->FlowState = TEXT("Playing");
        const bool bSaved = UGameplayStatics::SaveGameToSlot(Save, USaskartaSaveGame::RunSlot, 0);
        if (bSaved)
        {
            UE_LOG(LogSaskartaRadioRepair, Log, TEXT("Receiver checkpoint saved"));
        }
        else
        {
            UE_LOG(LogSaskartaRadioRepair, Warning, TEXT("Receiver checkpoint FAILED"));
        }
    }
}

void USaskartaRadioRepairSubsystem::HandleWritingRun(UWorld* World, USaskartaSaveGame* Save)
{
    if (World != GetWorld() || !Save) return;
    Save->RadioRepair.bValid = true;
    Save->RadioRepair.bCompleted = Logic.IsComplete();
    Save->RadioRepair.bWasOpen = bOpen && !Logic.IsComplete();
    Save->RadioRepair.Stage = static_cast<int32>(Logic.Stage);
    Save->RadioRepair.AerialDeg = Logic.AerialDeg;
    Save->RadioRepair.Frequency = Logic.Frequency;
    Save->RadioRepair.StableS = Logic.StableS;
}

void USaskartaRadioRepairSubsystem::HandleRestoredRun(UWorld* World, USaskartaSaveGame* Save)
{
    if (World != GetWorld() || !Save) return;
    Close(false); EnvelopeHistory.Reset();
    Logic = FSaskartaRadioRepairLogic();
    if (Save->RadioRepair.bValid)
    {
        const FSaskartaRadioRepairSave& State = Save->RadioRepair;
        Logic.Restore(State.Stage, State.AerialDeg, State.Frequency, State.StableS, State.bCompleted);
        bResumePending = State.bWasOpen && !Logic.IsComplete();
    }
}

void USaskartaRadioRepairSubsystem::UpdateDisplay(bool bAllowed)
{
    if (!bOpen) bPad = FSaskartaInputDevice::IsGamepad();
    const bool bPrompt = !bOpen && !Logic.IsComplete() && bAllowed;
    if (!Widget && (bPrompt || (bOpen && bAllowed)) && GetPC())
    {
        Widget = CreateWidget<USaskartaRadioRepairWidget>(GetPC(), SaskartaRuntimeWidgetClass(USaskartaRadioRepairWidget::StaticClass(),
            TEXT("/Game/SaskartaGaea/GameFlow/UI/WBP_Saskarta_RadioRepair.WBP_Saskarta_RadioRepair_C")));
        if (Widget) Widget->AddToViewport(65);
    }
    if (!Widget) return;
    TArray<FVector2D> Points;
    for (int32 I = 0; I < EnvelopeHistory.Num(); ++I)
        Points.Emplace(static_cast<double>(120 - EnvelopeHistory.Num() + I) / 119.0, EnvelopeHistory[I]);
    Widget->Present(bOpen && bAllowed, bPrompt, CanOpen(), bPad, Logic, Points);
}

void USaskartaRadioRepairSubsystem::Tick(float DeltaTime)
{
    const bool bAllowed = ControlsAvailable();
    const USaskartaEventRunner* Runner = GetWorld()->GetSubsystem<USaskartaEventRunner>();
    USaskartaRadioStation* Station = GetWorld()->GetSubsystem<USaskartaRadioStation>();
    if (bOpen && (!InEncounter() || !GetPC() || GetPC()->GetPawn() != SessionPawn.Get() || !Station ||
        !Station->IsRadioOn() || (Runner && !SaskartaRadioRepair::DriveFlow(Runner->GetFlowState()) &&
            Runner->GetFlowState() != TEXT("Paused") && !Runner->IsCinematicActive()))) Close(false);
    if (bResumePending && CanOpen()) Open();
    if (bOpen)
    {
        if (bWasAllowed && !bAllowed)
        {
            HeldKeys.Reset(); ClearReception();
            if (GetWorld()->IsPaused()) SaveProgress();
        }
        if (bAllowed && bOwnsMoveLock && LockedController.IsValid() && !LockedController->IsMoveInputIgnored())
            LockedController->SetIgnoreMoveInput(true);
        const auto Held = [&](FKey Keyboard, FKey Pad) { return HeldKeys.Contains(Keyboard) || HeldKeys.Contains(Pad); };
        const float Direction = (Held(EKeys::D, EKeys::Gamepad_DPad_Right) ? 1.f : 0.f) - (Held(EKeys::A, EKeys::Gamepad_DPad_Left) ? 1.f : 0.f);
        const float Frequency = (Held(EKeys::W, EKeys::Gamepad_DPad_Up) ? 1.f : 0.f) - (Held(EKeys::S, EKeys::Gamepad_DPad_Down) ? 1.f : 0.f);
        const bool bWasComplete = Logic.IsComplete();
        Logic.Step(DeltaTime, Direction, Frequency, bAllowed);
        if (!bWasComplete && Logic.IsComplete()) { ClearReception(); SaveProgress(); }
        if (Logic.IsComplete() && bAllowed)
        {
            CompleteAgeS += FMath::Clamp(DeltaTime, 0.f, 0.1f);
            if (CompleteAgeS >= 2.f) Close(false);
        }
    }
    bWasAllowed = bOpen && bAllowed;
    UiAgeS += FMath::Clamp(DeltaTime, 0.f, 0.1f);
    if (UiAgeS >= 0.1f)
    {
        UiAgeS = 0.f;
        if (bOpen && bAllowed && Station && !Logic.IsComplete())
        {
            Station->SetRepairReception(true, Logic.Signal());
            if (EnvelopeHistory.Num() >= 120) EnvelopeHistory.RemoveAt(0, 1, EAllowShrinking::No);
            EnvelopeHistory.Add(FMath::Clamp(Station->GetProgrammeEnvelope() * 10.f, 0.f, 1.f));
        }
        UpdateDisplay(bAllowed);
    }
}
