#include "SaskartaPauseGuard.h"

#include "SaskartaEventRunner.h"
#include "SaskartaPauseLogic.h"

#include "Blueprint/UserWidget.h"
#include "Engine/World.h"
#include "Framework/Application/IInputProcessor.h"
#include "Framework/Application/SlateApplication.h"
#include "GameFramework/PlayerController.h"
#include "InputCoreTypes.h"
#include "UObject/UnrealType.h"

DEFINE_LOG_CATEGORY_STATIC(LogSaskartaPauseGuard, Log, All);

class FSaskartaPauseKeyProcessor : public IInputProcessor
{
public:
    explicit FSaskartaPauseKeyProcessor(USaskartaPauseGuardSubsystem* InGuard) : Guard(InGuard) {}
    virtual void Tick(const float, FSlateApplication&, TSharedRef<ICursor>) override {}
    virtual bool HandleKeyDownEvent(FSlateApplication&, const FKeyEvent& Event) override
    {
        const FKey Key = Event.GetKey();
        if (Key != EKeys::Escape && Key != EKeys::Gamepad_Special_Right) return false;
        return Guard.IsValid() && Guard->HandlePauseKey(Event.IsRepeat());
    }
private:
    TWeakObjectPtr<USaskartaPauseGuardSubsystem> Guard;
};

bool USaskartaPauseGuardSubsystem::ShouldCreateSubsystem(UObject* Outer) const
{
    const UWorld* World = Cast<UWorld>(Outer);
    return World && World->IsGameWorld() && World->WorldType != EWorldType::PIE;
}

void USaskartaPauseGuardSubsystem::OnWorldBeginPlay(UWorld& InWorld)
{
    Super::OnWorldBeginPlay(InWorld);
    Runner = InWorld.GetSubsystem<USaskartaEventRunner>();
    if (FSlateApplication::IsInitialized())
    {
        Processor = MakeShared<FSaskartaPauseKeyProcessor>(this);
        FSlateApplication::Get().RegisterInputPreProcessor(Processor, 0);
        UE_LOG(LogSaskartaPauseGuard, Log, TEXT("pause keys registered for %s"), *InWorld.GetName());
    }
}

void USaskartaPauseGuardSubsystem::Deinitialize()
{
    if (FSlateApplication::IsInitialized() && Processor.IsValid())
        FSlateApplication::Get().UnregisterInputPreProcessor(Processor);
    Processor.Reset();
    if (bHeldCinematic && Runner.IsValid()) Runner->PauseCinematic(false);
    Super::Deinitialize();
}

TStatId USaskartaPauseGuardSubsystem::GetStatId() const
{
    RETURN_QUICK_DECLARE_CYCLE_STAT(USaskartaPauseGuardSubsystem, STATGROUP_Tickables);
}

void USaskartaPauseGuardSubsystem::Tick(float)
{
    WatchMenu();
}

APlayerController* USaskartaPauseGuardSubsystem::GetPC() const
{
    const UWorld* World = GetWorld();
    return World ? World->GetFirstPlayerController() : nullptr;
}

FName USaskartaPauseGuardSubsystem::GetFlow(APlayerController* PC) const
{
    if (!PC) return NAME_None;
    const FNameProperty* Prop = FindFProperty<FNameProperty>(PC->GetClass(), TEXT("FlowState"));
    return Prop ? Prop->GetPropertyValue_InContainer(PC) : NAME_None;
}

bool USaskartaPauseGuardSubsystem::SetName(APlayerController* PC, FName Property, FName Value) const
{
    if (!PC) return false;
    FNameProperty* Prop = FindFProperty<FNameProperty>(PC->GetClass(), Property);
    if (!Prop) return false;
    Prop->SetPropertyValue_InContainer(PC, Value);
    return true;
}

UUserWidget* USaskartaPauseGuardSubsystem::GetMenu(APlayerController* PC) const
{
    if (!PC) return nullptr;
    const FObjectProperty* Prop = FindFProperty<FObjectProperty>(PC->GetClass(), TEXT("PauseWidget"));
    return Prop ? Cast<UUserWidget>(Prop->GetObjectPropertyValue_InContainer(PC)) : nullptr;
}

bool USaskartaPauseGuardSubsystem::Call(AActor* Object, FName Function) const
{
    if (!Object) return false;
    UFunction* Fn = Object->FindFunction(Function);
    if (!Fn) return false;
    Object->ProcessEvent(Fn, nullptr);
    return true;
}

bool USaskartaPauseGuardSubsystem::OpenPause(APlayerController* PC, FName From)
{
    if (!PC || !SaskartaPause::IsPausableFlow(From)) return false;
    bHadMoveLock = PC->IsMoveInputIgnored();
    bHadLookLock = PC->IsLookInputIgnored();

    // Reuse the existing widget/focus path even when an older controller graph
    // only accepts Playing. Keep the real flow for the subsequent resume.
    const bool bNeedsGuard = From != FName(TEXT("Playing"));
    if (bNeedsGuard && !SetName(PC, TEXT("FlowState"), TEXT("Playing"))) return false;
    const bool bCalled = Call(PC, TEXT("OpenPause"));
    if (!bCalled || GetFlow(PC) != FName(TEXT("Paused")))
    {
        if (bNeedsGuard) SetName(PC, TEXT("FlowState"), From);
        UE_LOG(LogSaskartaPauseGuard, Warning, TEXT("pause did not open from %s (OpenPause called=%s)"),
            *From.ToString(), bCalled ? TEXT("yes") : TEXT("no"));
        return false;
    }
    SetName(PC, TEXT("PausedFrom"), From);
    OpenedFrom = From;
    bOpenedByGuard = true;
    bFlowMovedOn = false;
    bHeldCinematic = Runner.IsValid() && Runner->IsCinematicActive();
    if (bHeldCinematic) Runner->PauseCinematic(true);
    UE_LOG(LogSaskartaPauseGuard, Log, TEXT("pause opened from %s"), *From.ToString());
    return true;
}

bool USaskartaPauseGuardSubsystem::HandlePauseKey(bool bRepeat)
{
    APlayerController* PC = GetPC();
    if (!PC) return false;
    const FName Flow = GetFlow(PC);
    UUserWidget* Menu = GetMenu(PC);
    const bool bMenuShown = Menu && Menu->IsInViewport();
    switch (SaskartaPause::Decide(Flow, bMenuShown, bRepeat))
    {
    case SaskartaPause::EAction::Pass: return false;
    case SaskartaPause::EAction::Swallow: return true;
    case SaskartaPause::EAction::Open: return OpenPause(PC, Flow);
    case SaskartaPause::EAction::Toggle:
    {
        const bool bCalled = Call(PC, TEXT("TogglePause"));
        if (bCalled) WatchMenu();
        return bCalled;
    }
    case SaskartaPause::EAction::Close:
    {
        const bool bCalled = Call(PC, TEXT("ClosePause"));
        if (bCalled) WatchMenu();
        return bCalled;
    }
    }
    return false;
}

void USaskartaPauseGuardSubsystem::WatchMenu()
{
    if (!bOpenedByGuard) return;
    APlayerController* PC = GetPC();
    if (!PC) return;
    FName Flow = GetFlow(PC);
    UUserWidget* Menu = GetMenu(PC);
    if (Menu && Menu->IsInViewport())
    {
        // A prompt or final cue may move the story while its menu is open. Resume into that state.
        if (Flow != FName(TEXT("Paused")) && SaskartaPause::IsPausableFlow(Flow))
        {
            bFlowMovedOn = true;
            OpenedFrom = Flow;
            SetName(PC, TEXT("PausedFrom"), Flow);
            SetName(PC, TEXT("FlowState"), TEXT("Paused"));
        }
        return;
    }
    // Older ClosePause graphs hardcode Playing. Restore the actual on-foot or
    // cinematic flow before resuming its sequence and input locks.
    if (Flow == FName(TEXT("Playing")) && OpenedFrom != Flow && SaskartaPause::IsPausableFlow(OpenedFrom))
    {
        if (SetName(PC, TEXT("FlowState"), OpenedFrom)) Flow = OpenedFrom;
    }
    if (bHeldCinematic && Runner.IsValid()) Runner->PauseCinematic(false);
    if (!bFlowMovedOn && Flow == OpenedFrom)
    {
        if (bHadMoveLock) PC->SetIgnoreMoveInput(true);
        if (bHadLookLock) PC->SetIgnoreLookInput(true);
    }
    bOpenedByGuard = false;
    bHeldCinematic = false;
    UE_LOG(LogSaskartaPauseGuard, Log, TEXT("pause closed into %s"), *Flow.ToString());
}
