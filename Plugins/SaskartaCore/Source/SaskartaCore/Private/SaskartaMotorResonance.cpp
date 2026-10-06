#include "SaskartaMotorResonance.h"
#include "SaskartaMotorResonanceAudio.h"

#include "SaskartaEventRunner.h"
#include "SaskartaPower.h"
#include "SaskartaOnboarding.h"
#include "SaskartaRouteMap.h"
#include "Engine/GameViewportClient.h"
#include "Engine/World.h"
#include "Framework/Application/IInputProcessor.h"
#include "Framework/Application/SlateApplication.h"
#include "GameFramework/Character.h"
#include "GameFramework/CharacterMovementComponent.h"
#include "GameFramework/PlayerController.h"
#include "Widgets/SViewport.h"

DEFINE_LOG_CATEGORY_STATIC(LogSaskartaMotorResonance, Log, All);

namespace SaskartaResonance
{
    using FLogic = FSaskartaMotorResonanceLogic;

    bool LogicalKey(const FKey& Key, FLogic::EKey& Out)
    {
        if (Key == EKeys::E || Key == EKeys::Gamepad_FaceButton_Bottom) Out = FLogic::EKey::Beat;
        else if (Key == EKeys::A || Key == EKeys::Gamepad_DPad_Left) Out = FLogic::EKey::Left;
        else if (Key == EKeys::D || Key == EKeys::Gamepad_DPad_Right) Out = FLogic::EKey::Right;
        else return false;
        return true;
    }

    bool DriveFlow(FName Flow) { return Flow == TEXT("Playing") || Flow == TEXT("Carrier"); }
}

class FSaskartaMotorResonanceInput : public IInputProcessor
{
public:
    explicit FSaskartaMotorResonanceInput(USaskartaMotorResonanceSubsystem* InOwner) : Owner(InOwner) {}
    virtual void Tick(const float, FSlateApplication&, TSharedRef<ICursor>) override {}
    virtual bool HandleKeyDownEvent(FSlateApplication&, const FKeyEvent& Event) override
    {
        return Owner.IsValid() && Owner->HandleKey(Event.GetKey(), true, Event.IsRepeat());
    }
    virtual bool HandleKeyUpEvent(FSlateApplication&, const FKeyEvent& Event) override
    {
        return Owner.IsValid() && Owner->HandleKey(Event.GetKey(), false, false);
    }
private:
    TWeakObjectPtr<USaskartaMotorResonanceSubsystem> Owner;
};

bool USaskartaMotorResonanceSubsystem::ShouldCreateSubsystem(UObject* Outer) const
{
    const UWorld* World = Cast<UWorld>(Outer);
    return World && World->IsGameWorld() && World->GetNetMode() != NM_DedicatedServer;
}

void USaskartaMotorResonanceSubsystem::OnWorldBeginPlay(UWorld& InWorld)
{
    Super::OnWorldBeginPlay(InWorld);
    SaskartaRuntimeWidgetClass(USaskartaMotorResonanceWidget::StaticClass(), TEXT("/Game/SaskartaGaea/GameFlow/UI/WBP_Saskarta_Motor.WBP_Saskarta_Motor_C"));
    if (FSlateApplication::IsInitialized())
    {
        Processor = MakeShared<FSaskartaMotorResonanceInput>(this);
        FSlateApplication::Get().RegisterInputPreProcessor(Processor);
    }
    MotorAudio = NewObject<USaskartaMotorResonanceAudio>(this);
    MotorAudio->Initialize(&InWorld);
}

void USaskartaMotorResonanceSubsystem::Deinitialize()
{
    End();
    if (MotorAudio) MotorAudio->Shutdown();
    MotorAudio = nullptr;
    if (FSlateApplication::IsInitialized() && Processor.IsValid())
        FSlateApplication::Get().UnregisterInputPreProcessor(Processor);
    Processor.Reset();
    Super::Deinitialize();
}

TStatId USaskartaMotorResonanceSubsystem::GetStatId() const
{
    RETURN_QUICK_DECLARE_CYCLE_STAT(USaskartaMotorResonanceSubsystem, STATGROUP_Tickables);
}

APlayerController* USaskartaMotorResonanceSubsystem::GetPC() const
{
    return GetWorld() ? GetWorld()->GetFirstPlayerController() : nullptr;
}

bool USaskartaMotorResonanceSubsystem::HasViewportFocus() const
{
    // Slate retains widget focus across Alt-Tab; application activation is a
    // separate signal. Both must hold before timing or the shared chase advances.
    if (!FSlateApplication::IsInitialized() || !FSlateApplication::Get().IsActive()) return false;
    const UWorld* World = GetWorld();
    const UGameViewportClient* Viewport = World ? World->GetGameViewport() : nullptr;
    const TSharedPtr<SViewport> SlateViewport = Viewport ? Viewport->GetGameViewportWidget() : nullptr;
    return SlateViewport.IsValid() && SlateViewport->HasAnyUserFocusOrFocusedDescendants();
}

bool USaskartaMotorResonanceSubsystem::ControlsAvailable() const
{
    const UWorld* World = GetWorld();
    const APlayerController* PC = GetPC();
    const USaskartaEventRunner* Runner = World ? World->GetSubsystem<USaskartaEventRunner>() : nullptr;
    const USaskartaRouteMap* Map = World ? World->GetSubsystem<USaskartaRouteMap>() : nullptr;
    return World && !World->IsPaused() && PC && PC->IsLocalController() && PC->GetPawn() == SessionPawn.Get() &&
        Runner && SaskartaResonance::DriveFlow(Runner->GetFlowState()) && !Runner->IsCinematicActive() &&
        !Runner->IsHoldingInput() && !Runner->IsPromptActive() && !(Map && Map->IsOpen()) && HasViewportFocus();
    // Both modes intentionally own a move lock: tuning parks; EarlyStorm follows the road.
}

void USaskartaMotorResonanceSubsystem::Begin(FSaskartaMotorResonanceLogic::EMode Mode)
{
    Logic.Begin(Mode);
    SessionPawn = GetPC() ? GetPC()->GetPawn() : nullptr;
    if (MotorAudio) MotorAudio->BeginSession();
    bGamepad = FSaskartaInputDevice::IsGamepad();
    HeldKeys.Reset();
    const APlayerController* PC = GetPC();
    for (FKey Key : {EKeys::E, EKeys::A, EKeys::D, EKeys::Gamepad_FaceButton_Bottom,
                     EKeys::Gamepad_DPad_Left, EKeys::Gamepad_DPad_Right})
    {
        if (PC && PC->IsInputKeyDown(Key))
        {
            HeldKeys.Add(Key);
            FSaskartaMotorResonanceLogic::EKey Logical;
            if (SaskartaResonance::LogicalKey(Key, Logical)) Logic.Input(Logical, true);
        }
    }
    UpdateDisplay(false);
    const USaskartaPowerSubsystem* Power = GetWorld()->GetSubsystem<USaskartaPowerSubsystem>();
    UE_LOG(LogSaskartaMotorResonance, Log, TEXT("begin %s charge=%.1f empty=%d"),
        Logic.IsTuning() ? TEXT("tuning") : TEXT("pursuit"), Power ? Power->GetCharge() : 0.f,
        Power && Power->IsLimp() ? 1 : 0);
}

void USaskartaMotorResonanceSubsystem::BeginTuning()
{
    UWorld* World = GetWorld();
    APlayerController* PC = GetPC();
    USaskartaPowerSubsystem* Power = World ? World->GetSubsystem<USaskartaPowerSubsystem>() : nullptr;
    const USaskartaEventRunner* Runner = World ? World->GetSubsystem<USaskartaEventRunner>() : nullptr;
    const USaskartaRouteMap* Map = World ? World->GetSubsystem<USaskartaRouteMap>() : nullptr;
    ACharacter* Carrier = PC ? Cast<ACharacter>(PC->GetPawn()) : nullptr;
    if (IsActive() || !World || World->IsPaused() || !PC || !PC->IsLocalController() || !Carrier || !Power ||
        !Power->CanRest() || Carrier->GetVelocity().Size2D() > 20.f || PC->IsMoveInputIgnored() || !Runner ||
        !SaskartaResonance::DriveFlow(Runner->GetFlowState()) || Runner->IsCinematicActive() ||
        Runner->IsHoldingInput() || Runner->IsPromptActive() || (Map && Map->IsOpen())) return;
    TuningController = PC;
    PC->SetIgnoreMoveInput(true);
    bOwnsMoveLock = true;
    if (UCharacterMovementComponent* Movement = Carrier->GetCharacterMovement()) Movement->StopMovementImmediately();
    Power->SetRestActivityOpen(true);
    Begin(FSaskartaMotorResonanceLogic::EMode::Tuning);
}

void USaskartaMotorResonanceSubsystem::BeginPursuit()
{
    // Each explicit begin is a fresh attempt, including the automatic short rewind.
    End();
    if (!GetPC() || !GetPC()->GetPawn()) return;
    Begin(FSaskartaMotorResonanceLogic::EMode::Pursuit);
}

void USaskartaMotorResonanceSubsystem::End()
{
    if (MotorAudio) MotorAudio->EndSession();
    if (bOwnsMoveLock)
    {
        if (TuningController.IsValid()) TuningController->SetIgnoreMoveInput(false);
        if (USaskartaPowerSubsystem* Power = GetWorld() ? GetWorld()->GetSubsystem<USaskartaPowerSubsystem>() : nullptr)
            Power->SetRestActivityOpen(false);
    }
    bOwnsMoveLock = false;
    TuningController.Reset();
    SessionPawn.Reset();
    HeldKeys.Reset();
    Logic.End();
    if (Widget) { Widget->RemoveFromParent(); Widget = nullptr; }
}

void USaskartaMotorResonanceSubsystem::EndTuning() { if (IsTuning()) End(); }
void USaskartaMotorResonanceSubsystem::EndPursuit()
{
    if (Logic.Mode == FSaskartaMotorResonanceLogic::EMode::Pursuit) End();
}

float USaskartaMotorResonanceSubsystem::GetDriveMultiplier() const { return Logic.DriveMultiplier(); }
void USaskartaMotorResonanceSubsystem::SetPursuitGap(float GapM)
{
    PursuitGapM = FMath::IsFinite(GapM) ? FMath::Max(0.f, GapM) : 0.f;
}

void USaskartaMotorResonanceSubsystem::ApplyReward()
{
    const float Reward = Logic.TakeChargeReward();
    if (Reward <= 0.f) return;
    if (USaskartaPowerSubsystem* Power = GetWorld()->GetSubsystem<USaskartaPowerSubsystem>())
    {
        const float Before = Power->GetCharge();
        // Pursuit recovery must replenish the actual cell, rather than only its
        // drive score. Once it restarts, subsequent beats pay acceleration only.
        const float Ceiling = Logic.bRecoveringCell ? Power->GetRestartCharge() : 100.f;
        Power->SetCharge(FMath::Min(FMath::Max(Before, Ceiling), Before + Reward));
        // Report the charge actually delivered, including clipping at a full cell.
        Logic.EarnedCharge -= FMath::Max(0.f, Reward - (Power->GetCharge() - Before));
        const bool bRecovered = Logic.bRecoveringCell && !Power->IsLimp();
        Logic.bRecoveringCell = Logic.Mode == FSaskartaMotorResonanceLogic::EMode::Pursuit && Power->IsLimp();
        if (bRecovered)
            UE_LOG(LogSaskartaMotorResonance, Log, TEXT("pursuit cell restarted charge=%.1f"), Power->GetCharge());
    }
}

void USaskartaMotorResonanceSubsystem::PlayFeedback(FSaskartaMotorResonanceLogic::EFeedback Result)
{
    if (MotorAudio) MotorAudio->PlayFeedback(Logic);
}

bool USaskartaMotorResonanceSubsystem::HandleKey(const FKey& Key, bool bDown, bool bRepeat)
{
    FSaskartaMotorResonanceLogic::EKey Logical;
    if (!IsActive() || !SaskartaResonance::LogicalKey(Key, Logical)) return false;
    const bool bAllowed = ControlsAvailable();
    if (bRepeat) return bAllowed;
    if (bDown) HeldKeys.Add(Key); else HeldKeys.Remove(Key);
    bool bLogicalHeld = false;
    for (const FKey& Held : HeldKeys)
    {
        FSaskartaMotorResonanceLogic::EKey Other;
        if (SaskartaResonance::LogicalKey(Held, Other) && Logical == Other) bLogicalHeld = true;
    }
    Logic.Advance(0.0, !bAllowed);
    const USaskartaPowerSubsystem* Power = GetWorld()->GetSubsystem<USaskartaPowerSubsystem>();
    Logic.bRecoveringCell = Logic.Mode == FSaskartaMotorResonanceLogic::EMode::Pursuit && Power && Power->IsLimp();
    if (Logic.Input(Logical, bLogicalHeld))
    {
        bGamepad = Key.IsGamepadKey();
        ApplyReward();
        PlayFeedback(Logic.Feedback);
        UpdateDisplay(true);
    }
    // Let releases reach PlayerInput too: a key held before this mode began may
    // already be down there. Swallowing its release would leave stale steering/E.
    return bAllowed && bDown;
}

void USaskartaMotorResonanceSubsystem::UpdateDisplay(bool bShow)
{
    if (bShow && !Widget && GetPC())
    {
        Widget = CreateWidget<USaskartaMotorResonanceWidget>(GetPC(), SaskartaRuntimeWidgetClass(USaskartaMotorResonanceWidget::StaticClass(),
            TEXT("/Game/SaskartaGaea/GameFlow/UI/WBP_Saskarta_Motor.WBP_Saskarta_Motor_C")));
        if (Widget) Widget->AddToViewport(60);
    }
    if (Widget)
    {
        const USaskartaPowerSubsystem* Power = GetWorld()->GetSubsystem<USaskartaPowerSubsystem>();
        Widget->Present(Logic, bShow, bGamepad, Power ? Power->GetCharge() : 0.f, PursuitGapM,
            Power && Power->IsInspectingBattery());
    }
}

void USaskartaMotorResonanceSubsystem::Tick(float DeltaTime)
{
    if (!IsActive()) return;
    APlayerController* PC = GetPC();
    const USaskartaEventRunner* Runner = GetWorld()->GetSubsystem<USaskartaEventRunner>();
    const FName Flow = Runner ? Runner->GetFlowState() : NAME_None;
    // Road tether recovery teleports this same carrier, then restores Playing.
    // Keep its pursuit sequence; ControlsAvailable freezes timing and the shared
    // chase gate stops movement/front progress throughout Rebooting.
    const bool bRecoveringPursuit = Logic.Mode == FSaskartaMotorResonanceLogic::EMode::Pursuit && Flow == TEXT("Rebooting");
    if (!PC || !SessionPawn.IsValid() || PC->GetPawn() != SessionPawn.Get() ||
        (!SaskartaResonance::DriveFlow(Flow) && Flow != TEXT("Paused") && !bRecoveringPursuit && !(Runner && Runner->IsCinematicActive())))
    {
        End();
        return;
    }
    const bool bAllowed = ControlsAvailable();
    const USaskartaPowerSubsystem* Power = GetWorld()->GetSubsystem<USaskartaPowerSubsystem>();
    Logic.bRecoveringCell = Logic.Mode == FSaskartaMotorResonanceLogic::EMode::Pursuit && Power && Power->IsLimp();
    // PC_Saskarta.ClosePause resets all ignore flags in PIE. Reacquire only our
    // own lost park lock; never add another count while a lock still exists.
    if (bAllowed && IsTuning() && bOwnsMoveLock && TuningController.Get() == PC && !PC->IsMoveInputIgnored())
        PC->SetIgnoreMoveInput(true);
    Logic.Advance(DeltaTime, !bAllowed);
    if (MotorAudio)
    {
        MotorAudio->UpdateCues(Logic, bAllowed);
        if (bAllowed)
        {
            const float Stability = FMath::Clamp((Logic.Drive - 0.65f) / 0.85f, 0.f, 1.f);
            MotorAudio->SetCrank(0.18f + 0.24f * FMath::Clamp(Logic.BeatPosition() / 0.8f, 0.f, 1.f), Stability);
        }
    }
    if (Logic.bComplete)
    {
        if (USaskartaPowerSubsystem* LessonPower = GetWorld()->GetSubsystem<USaskartaPowerSubsystem>())
            LessonPower->ShowNotice(FString::Printf(TEXT("%s . +%.0f%% CHARGE . %d/%d BEATS"),
                Logic.GoodBeats >= 6 ? TEXT("MOTOR TUNED") : TEXT("KEEP PRACTICING"),
                Logic.EarnedCharge, Logic.GoodBeats, FSaskartaMotorResonanceLogic::LessonBeats), 4.f);
        UE_LOG(LogSaskartaMotorResonance, Log, TEXT("lesson complete good=%d charge=%.1f"), Logic.GoodBeats, Logic.EarnedCharge);
        End();
        return;
    }
    UpdateDisplay(bAllowed);
}
