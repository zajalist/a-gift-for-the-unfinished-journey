// Capture guard (task CAPTURE-CPP). See SaskartaCaptureGuard.h for the rules.

#include "SaskartaCaptureGuard.h"

#include "Blueprint/UserWidget.h"
#include "Components/Image.h"
#include "Components/PanelWidget.h"
#include "Components/SceneCaptureComponent.h"
#include "Components/SceneCaptureComponent2D.h"
#include "Components/SceneCaptureComponentCube.h"
#include "Engine/Engine.h"
#include "Engine/GameInstance.h"
#include "Engine/TextureRenderTarget2D.h"
#include "Engine/TextureRenderTargetCube.h"
#include "Engine/World.h"
#include "GameFramework/Actor.h"
#include "HAL/IConsoleManager.h"
#include "SaskartaLoadingBudget.h"
#include "UObject/UObjectHash.h"

DEFINE_LOG_CATEGORY_STATIC(LogSaskartaCaptureGuard, Log, All);

static TAutoConsoleVariable<int32> CVarCaptureGuardEnable(
    TEXT("saskarta.captureguard.Enable"), 1,
    TEXT("Saskarta: 1 keeps loading-only scene captures (the Keeper point cloud) on only while the loading screen is up and ")
    TEXT("switches editor-leftover captures off. 0 turns back on what the guard switched off and stops."),
    ECVF_Default);

static TAutoConsoleVariable<float> CVarCaptureGuardLingerS(
    TEXT("saskarta.captureguard.LingerS"), 1.5f,
    TEXT("Saskarta: seconds the loading-only captures stay on after the loading signal drops."),
    ECVF_Default);

static TAutoConsoleVariable<float> CVarCaptureGuardStartGraceS(
    TEXT("saskarta.captureguard.StartGraceS"), 8.f,
    TEXT("Saskarta: with no loading signal this long after BeginPlay (a start that skips the intro), the loading-only captures go off."),
    ECVF_Default);

static TAutoConsoleVariable<float> CVarCaptureGuardPollS(
    TEXT("saskarta.captureguard.PollS"), 0.5f,
    TEXT("Saskarta: seconds between capture guard polls (0.1-5)."),
    ECVF_Default);

static TAutoConsoleVariable<int32> CVarCaptureGuardAudit(
    TEXT("saskarta.captureguard.Audit"), 1,
    TEXT("Saskarta: 1 logs one warning per other scene capture that renders every frame in the game world."),
    ECVF_Default);

static TAutoConsoleVariable<FString> CVarCaptureGuardExtraStrays(
    TEXT("saskarta.captureguard.ExtraStrays"), TEXT(""),
    TEXT("Saskarta: comma-separated actor name/label/tag/class prefixes whose scene captures are switched off for the whole game ")
    TEXT("(besides Look_TempCapture and HaybaMCPCaptureActor). Read when a capture is first seen."),
    ECVF_Default);

static FAutoConsoleCommandWithWorld GCaptureGuardDumpCmd(
    TEXT("saskarta.captureguard.Dump"),
    TEXT("Saskarta: logs every scene capture of this world with its capture-guard role and state."),
    FConsoleCommandWithWorldDelegate::CreateLambda([](UWorld* World)
    {
        if (const USaskartaCaptureGuard* Guard = World ? World->GetSubsystem<USaskartaCaptureGuard>() : nullptr)
        {
            Guard->DumpCaptures();
        }
        else
        {
            UE_LOG(LogSaskartaCaptureGuard, Display, TEXT("Capture guard: not running in this world (it runs in Game and PIE worlds)."));
        }
    }));

namespace SaskartaCaptureGuardLocal
{
    /** PC_Saskarta.BeginIntro creates it; it removes itself at the end of its FadeOut. */
    static const TCHAR* LoadingWidgetClassPath = TEXT("/Game/SaskartaGaea/GameFlow/UI/WBP_Saskarta_Loading.WBP_Saskarta_Loading_C");

    static double Now()
    {
        return FPlatformTime::Seconds();
    }

    static void ListCaptures(const UWorld* World, TArray<USceneCaptureComponent*>& Out)
    {
        TArray<UObject*> Objects;
        GetObjectsOfClass(USceneCaptureComponent::StaticClass(), Objects, true,
            RF_ClassDefaultObject | RF_ArchetypeObject, EInternalObjectFlags::Garbage);
        for (UObject* O : Objects)
        {
            USceneCaptureComponent* C = Cast<USceneCaptureComponent>(O);
            if (IsValid(C) && C->GetWorld() == World)
            {
                Out.Add(C);
            }
        }
    }

    static FString TargetName(const USceneCaptureComponent& C)
    {
        if (const USceneCaptureComponent2D* C2 = Cast<USceneCaptureComponent2D>(&C))
        {
            return C2->TextureTarget ? C2->TextureTarget->GetName() : FString();
        }
        if (const USceneCaptureComponentCube* Cube = Cast<USceneCaptureComponentCube>(&C))
        {
            return Cube->TextureTarget ? Cube->TextureTarget->GetName() : FString();
        }
        return FString();
    }
}

// ============================================================================ subsystem

bool USaskartaCaptureGuard::DoesSupportWorldType(const EWorldType::Type WorldType) const
{
    // Runtime only: the editor world (and so the saved level) keeps the captures as authored.
    return WorldType == EWorldType::Game || WorldType == EWorldType::PIE;
}

USaskartaCaptureGuard* USaskartaCaptureGuard::GetCaptureGuard(const UObject* WorldContext)
{
    const UWorld* World = GEngine ? GEngine->GetWorldFromContextObject(WorldContext, EGetWorldErrorMode::ReturnNull) : nullptr;
    return World ? World->GetSubsystem<USaskartaCaptureGuard>() : nullptr;
}

void USaskartaCaptureGuard::Initialize(FSubsystemCollectionBase& Collection)
{
    Super::Initialize(Collection);
    bBegunPlay = false;
    bDisabled = false;
}

void USaskartaCaptureGuard::Deinitialize()
{
    if (TickerHandle.IsValid())
    {
        FTSTicker::RemoveTicker(TickerHandle);
        TickerHandle.Reset();
    }
    // The world is going away with its components; nothing to restore.
    Tracked.Reset();
    Holds.Reset();
    Super::Deinitialize();
}

void USaskartaCaptureGuard::OnWorldBeginPlay(UWorld& InWorld)
{
    Super::OnWorldBeginPlay(InWorld);
    bBegunPlay = true;
    Tracker.StartGraceS = FMath::Max(0.f, CVarCaptureGuardStartGraceS.GetValueOnGameThread());
    Tracker.LingerS = FMath::Max(0.f, CVarCaptureGuardLingerS.GetValueOnGameThread());
    Tracker.Start(SaskartaCaptureGuardLocal::Now());
    ArmTicker();
    Poll();
}

void USaskartaCaptureGuard::ArmTicker()
{
    if (TickerHandle.IsValid())
    {
        FTSTicker::RemoveTicker(TickerHandle);
    }
    TickerPollS = FMath::Clamp(CVarCaptureGuardPollS.GetValueOnGameThread(), 0.1f, 5.f);
    TickerHandle = FTSTicker::GetCoreTicker().AddTicker(
        FTickerDelegate::CreateUObject(this, &USaskartaCaptureGuard::OnTicker), TickerPollS);
}

bool USaskartaCaptureGuard::OnTicker(float DeltaTime)
{
    Poll();
    const float Wanted = FMath::Clamp(CVarCaptureGuardPollS.GetValueOnGameThread(), 0.1f, 5.f);
    if (!FMath::IsNearlyEqual(Wanted, TickerPollS))
    {
        // A new interval: this ticker ends (return false) and a new one starts.
        TickerPollS = Wanted;
        TickerHandle = FTSTicker::GetCoreTicker().AddTicker(
            FTickerDelegate::CreateUObject(this, &USaskartaCaptureGuard::OnTicker), TickerPollS);
        return false;
    }
    return true;
}

void USaskartaCaptureGuard::Refresh()
{
    Poll();
}

void USaskartaCaptureGuard::SetLoadingHold(FName Reason, bool bHold)
{
    const bool bChanged = bHold ? !Holds.Contains(Reason) : Holds.Contains(Reason);
    if (bHold)
    {
        Holds.Add(Reason);
    }
    else
    {
        Holds.Remove(Reason);
    }
    if (bChanged)
    {
        UE_LOG(LogSaskartaCaptureGuard, Log, TEXT("Capture guard: loading hold %s %s (%d holds)."),
            *Reason.ToString(), bHold ? TEXT("set") : TEXT("cleared"), Holds.Num());
        Poll();
    }
}

bool USaskartaCaptureGuard::AreLoadingCapturesOn() const
{
    return bDisabled || (HasLoadingCaptureConsumer() &&
        (!Tracker.HasStarted() || Tracker.GetPhase() != ESaskartaCapturePhase::Play));
}

void USaskartaCaptureGuard::Poll()
{
    UWorld* World = GetWorld();
    if (!World || !bBegunPlay || World->bIsTearingDown)
    {
        return;
    }

    if (!CVarCaptureGuardEnable.GetValueOnGameThread())
    {
        if (!bDisabled)
        {
            RestoreAll(TEXT("saskarta.captureguard.Enable 0"));
            bDisabled = true;
        }
        return;
    }
    const bool bReenabled = bDisabled;
    bDisabled = false;

    Tracker.StartGraceS = FMath::Max(0.f, CVarCaptureGuardStartGraceS.GetValueOnGameThread());
    Tracker.LingerS = FMath::Max(0.f, CVarCaptureGuardLingerS.GetValueOnGameThread());

    FString Why;
    const bool bLoading = IsLoadingSignal(&Why);
    const ESaskartaCapturePhase Before = Tracker.GetPhase();
    const bool bPhaseChanged = Tracker.Update(SaskartaCaptureGuardLocal::Now(), bLoading);
    if (bPhaseChanged)
    {
        UE_LOG(LogSaskartaCaptureGuard, Log, TEXT("Capture guard: %s -> %s (loading signal: %s)."),
            FSaskartaCaptureGuardLogic::PhaseName(Before), FSaskartaCaptureGuardLogic::PhaseName(Tracker.GetPhase()),
            Why.IsEmpty() ? TEXT("none") : *Why);
    }
    ScanCaptures(bPhaseChanged || bReenabled);
}

bool USaskartaCaptureGuard::IsLoadingSignal(FString* OutWhy) const
{
    TArray<FString> Why;
    if (Holds.Num() > 0)
    {
        TArray<FString> Names;
        for (const FName& H : Holds)
        {
            Names.Add(H.ToString());
        }
        Why.Add(FString::Printf(TEXT("hold %s"), *FString::Join(Names, TEXT("+"))));
    }
    // USaskartaPerfGovernor::SetSuspended("Loading") begins / ends the loading budget; the budget's
    // state is the public read of that reason (the governor keeps its reason set private).
    const UWorld* World = GetWorld();
    const UGameInstance* GI = World ? World->GetGameInstance() : nullptr;
    if (const USaskartaLoadingBudget* Budget = GI ? GI->GetSubsystem<USaskartaLoadingBudget>() : nullptr)
    {
        if (Budget->IsLoadingBudgetActive())
        {
            Why.Add(TEXT("loading budget"));
        }
    }
    if (IsLoadingWidgetShown())
    {
        Why.Add(TEXT("loading widget"));
    }
    if (OutWhy)
    {
        *OutWhy = FString::Join(Why, TEXT(", "));
    }
    return Why.Num() > 0;
}

bool USaskartaCaptureGuard::IsLoadingWidgetShown() const
{
    UClass* WidgetClass = LoadingWidgetClass.Get();
    if (!WidgetClass)
    {
        // Found, never loaded: nothing to show until the flow has loaded the class itself.
        WidgetClass = FindObject<UClass>(nullptr, SaskartaCaptureGuardLocal::LoadingWidgetClassPath);
        if (!WidgetClass)
        {
            return false;
        }
        LoadingWidgetClass = WidgetClass;
    }
    const UWorld* World = GetWorld();
    TArray<UObject*> Widgets;
    GetObjectsOfClass(WidgetClass, Widgets, true, RF_ClassDefaultObject | RF_ArchetypeObject, EInternalObjectFlags::Garbage);
    for (const UObject* O : Widgets)
    {
        const UUserWidget* W = Cast<UUserWidget>(O);
        if (IsValid(W) && W->GetWorld() == World && W->IsInViewport())
        {
            return true;
        }
    }
    return false;
}

bool USaskartaCaptureGuard::HasLoadingCaptureConsumer() const
{
    // Explicit holds support other loading presentations. The generic loading budget alone
    // must not enable the offstage Keeper render behind a logo-only loading screen.
    if (Holds.Num() > 0) return true;
    UClass* WidgetClass = LoadingWidgetClass.Get();
    if (!WidgetClass) return false;
    TArray<UObject*> Widgets;
    GetObjectsOfClass(WidgetClass, Widgets, true, RF_ClassDefaultObject | RF_ArchetypeObject, EInternalObjectFlags::Garbage);
    for (const UObject* O : Widgets)
    {
        const UUserWidget* W = Cast<UUserWidget>(O);
        if (!IsValid(W) || W->GetWorld() != GetWorld() || !W->IsInViewport() ||
            !W->IsVisible() || W->GetRenderOpacity() <= 0.f) continue;
        const UImage* Image = Cast<UImage>(W->GetWidgetFromName(TEXT("TravellerPointCloud")));
        if (!Image || !Image->GetBrush().GetResourceObject()) continue;
        // The loading graph starts this image at opacity zero and reveals it
        // after four seconds. Warm the capture while the carrier is still shown
        // so the first Keeper frame has current pixels instead of a cold RT.
        bool bVisible = true;
        for (const UWidget* Part = Image; Part; Part = Part->GetParent())
        {
            if (!Part->IsVisible() || (Part != Image && Part->GetRenderOpacity() <= 0.f))
            {
                bVisible = false;
                break;
            }
        }
        if (bVisible) return true;
    }
    return false;
}

FSaskartaCaptureIdentity USaskartaCaptureGuard::MakeIdentity(const USceneCaptureComponent& C)
{
    FSaskartaCaptureIdentity Id;
    if (const AActor* Owner = C.GetOwner())
    {
        Id.ActorName = Owner->GetName();
        // The editor label (PIE); a cooked game has none and returns the name.
        const FString NameOrLabel = Owner->GetActorNameOrLabel();
        if (NameOrLabel != Id.ActorName)
        {
            Id.ActorLabel = NameOrLabel;
        }
        Id.Tags.Append(Owner->Tags);
        for (const UClass* Cls = Owner->GetClass(); Cls; Cls = Cls->GetSuperClass())
        {
            Id.ClassNames.Add(Cls->GetName());
        }
    }
    Id.Tags.Append(C.ComponentTags);
    Id.TextureTargetName = SaskartaCaptureGuardLocal::TargetName(C);
    return Id;
}

FString USaskartaCaptureGuard::DescribeCapture(const USceneCaptureComponent& C)
{
    const AActor* Owner = C.GetOwner();
    const FString Target = SaskartaCaptureGuardLocal::TargetName(C);
    return FString::Printf(TEXT("%s.%s -> %s"),
        Owner ? *Owner->GetActorNameOrLabel() : TEXT("(no owner)"), *C.GetName(),
        Target.IsEmpty() ? TEXT("(no render target)") : *Target);
}

void USaskartaCaptureGuard::ScanCaptures(bool bApplyAll)
{
    UWorld* World = GetWorld();
    if (!World)
    {
        return;
    }
    for (auto It = Tracked.CreateIterator(); It; ++It)
    {
        if (!It->Value.Component.IsValid())
        {
            It.RemoveCurrent();
        }
    }

    TArray<USceneCaptureComponent*> Captures;
    SaskartaCaptureGuardLocal::ListCaptures(World, Captures);

    const ESaskartaCapturePhase Phase = Tracker.GetPhase();
    const bool bHasConsumer = HasLoadingCaptureConsumer();
    const bool bAudit = CVarCaptureGuardAudit.GetValueOnGameThread() != 0;
    TOptional<TArray<FString>> Extra;
    for (USceneCaptureComponent* C : Captures)
    {
        if (!C->IsRegistered())
        {
            continue;
        }
        const AActor* Owner = C->GetOwner();
        if (Owner && !Owner->HasActorBegunPlay())
        {
            // Still streaming in: the next poll takes it.
            continue;
        }

        const FObjectKey Key(C);
        FTracked* T = Tracked.Find(Key);
        const bool bNew = T == nullptr;
        if (bNew)
        {
            if (!Extra.IsSet())
            {
                Extra.Emplace(FSaskartaCaptureGuardLogic::ParseList(CVarCaptureGuardExtraStrays.GetValueOnGameThread()));
            }
            T = &Tracked.Add(Key);
            T->Component = C;
            T->Role = FSaskartaCaptureGuardLogic::Classify(MakeIdentity(*C), Extra.GetValue());
            T->bOrigEveryFrame = C->bCaptureEveryFrame;
            T->bOrigOnMovement = C->bCaptureOnMovement;
            T->bOrigActive = C->IsActive();
            T->Label = DescribeCapture(*C);
            if (T->Role != ESaskartaCaptureRole::Unmanaged)
            {
                UE_LOG(LogSaskartaCaptureGuard, Log, TEXT("Capture guard: %s is %s (every frame %d, active %d)."),
                    *T->Label, FSaskartaCaptureGuardLogic::RoleName(T->Role), T->bOrigEveryFrame ? 1 : 0, T->bOrigActive ? 1 : 0);
            }
        }
        const ESaskartaCaptureCommand Command = FSaskartaCaptureGuardLogic::Decide(T->Role, Phase, bHasConsumer);
        if (bNew || bApplyAll || T->Applied != Command)
        {
            ApplyCommand(*T, *C, Command);
        }
        if (bAudit && FSaskartaCaptureGuardLogic::ShouldAudit(T->Role, C->bCaptureEveryFrame, C->IsActive(), T->bWarned))
        {
            T->bWarned = true;
            UE_LOG(LogSaskartaCaptureGuard, Warning,
                TEXT("Capture guard audit: %s renders every frame in the game world (a full scene render per frame, up to ~1 ms GPU%s). ")
                TEXT("If it only feeds a loading screen, tag its actor %s; if it is a leftover, tag it %s or delete it; ")
                TEXT("otherwise switch Capture Every Frame off and capture on demand."),
                *T->Label, SaskartaCaptureGuardLocal::TargetName(*C).IsEmpty() ? TEXT("; no render target, so it renders nothing yet") : TEXT(""),
                *FSaskartaCaptureGuardLogic::LoadingTag.ToString(), *FSaskartaCaptureGuardLogic::StrayTag.ToString());
        }
    }
}

void USaskartaCaptureGuard::ApplyCommand(FTracked& T, USceneCaptureComponent& C, ESaskartaCaptureCommand Command)
{
    if (Command == ESaskartaCaptureCommand::Leave)
    {
        return;
    }
    bool bChanged = false;
    if (Command == ESaskartaCaptureCommand::On)
    {
        bChanged = !C.bCaptureEveryFrame || !C.IsActive();
        C.bCaptureEveryFrame = true;
        C.bCaptureOnMovement = T.bOrigOnMovement;
        if (!C.IsActive())
        {
            C.Activate(false);
        }
    }
    else
    {
        bChanged = C.bCaptureEveryFrame || C.bCaptureOnMovement || C.IsActive();
        // bCaptureEveryFrame is what TickComponent reads; Deactivate also stops the component's tick.
        C.bCaptureEveryFrame = false;
        C.bCaptureOnMovement = false;
        if (C.IsActive())
        {
            C.Deactivate();
        }
    }
    T.Applied = Command;
    if (bChanged)
    {
        UE_LOG(LogSaskartaCaptureGuard, Log, TEXT("Capture guard: %s %s (%s, phase %s)."),
            *T.Label, Command == ESaskartaCaptureCommand::On ? TEXT("ON") : TEXT("OFF"),
            FSaskartaCaptureGuardLogic::RoleName(T.Role), FSaskartaCaptureGuardLogic::PhaseName(Tracker.GetPhase()));
    }
}

void USaskartaCaptureGuard::RestoreAll(const TCHAR* Why)
{
    int32 Restored = 0;
    for (TPair<FObjectKey, FTracked>& Pair : Tracked)
    {
        FTracked& T = Pair.Value;
        USceneCaptureComponent* C = T.Component.Get();
        if (!C || T.Applied == ESaskartaCaptureCommand::Leave)
        {
            continue;
        }
        C->bCaptureEveryFrame = T.bOrigEveryFrame;
        C->bCaptureOnMovement = T.bOrigOnMovement;
        if (T.bOrigActive && !C->IsActive())
        {
            C->Activate(false);
        }
        else if (!T.bOrigActive && C->IsActive())
        {
            C->Deactivate();
        }
        T.Applied = ESaskartaCaptureCommand::Leave;
        ++Restored;
    }
    UE_LOG(LogSaskartaCaptureGuard, Log, TEXT("Capture guard: %d capture(s) restored as authored (%s)."), Restored, Why);
}

FString USaskartaCaptureGuard::DescribeState() const
{
    int32 NumLoading = 0;
    int32 NumStray = 0;
    int32 NumOther = 0;
    int32 NumOtherEveryFrame = 0;
    for (const TPair<FObjectKey, FTracked>& Pair : Tracked)
    {
        const USceneCaptureComponent* C = Pair.Value.Component.Get();
        if (!C)
        {
            continue;
        }
        switch (Pair.Value.Role)
        {
        case ESaskartaCaptureRole::LoadingOnly: ++NumLoading; break;
        case ESaskartaCaptureRole::Stray: ++NumStray; break;
        default:
            ++NumOther;
            NumOtherEveryFrame += (C->bCaptureEveryFrame && C->IsActive()) ? 1 : 0;
            break;
        }
    }
    FString Why;
    IsLoadingSignal(&Why);
    const double InPhase = Tracker.HasStarted() ? SaskartaCaptureGuardLocal::Now() - Tracker.GetPhaseSinceS() : 0.0;
    return FString::Printf(TEXT("%sphase %s (%.1f s, %d loading window(s)) | loading signal: %s | captures: %d loading-only, %d stray, %d other (%d every frame)"),
        bDisabled ? TEXT("DISABLED | ") : TEXT(""),
        FSaskartaCaptureGuardLogic::PhaseName(Tracker.GetPhase()), InPhase, Tracker.GetLoadingCount(),
        Why.IsEmpty() ? TEXT("none") : *Why, NumLoading, NumStray, NumOther, NumOtherEveryFrame);
}

void USaskartaCaptureGuard::DumpCaptures() const
{
    const UWorld* World = GetWorld();
    TArray<USceneCaptureComponent*> Captures;
    SaskartaCaptureGuardLocal::ListCaptures(World, Captures);
    UE_LOG(LogSaskartaCaptureGuard, Display, TEXT("Capture guard: %s"), *DescribeState());
    const TArray<FString> Extra = FSaskartaCaptureGuardLogic::ParseList(CVarCaptureGuardExtraStrays.GetValueOnGameThread());
    for (const USceneCaptureComponent* C : Captures)
    {
        const FTracked* T = Tracked.Find(FObjectKey(C));
        const ESaskartaCaptureRole Role = T ? T->Role : FSaskartaCaptureGuardLogic::Classify(MakeIdentity(*C), Extra);
        UE_LOG(LogSaskartaCaptureGuard, Display, TEXT("  %s | %s%s | every frame %d, on movement %d, active %d, registered %d | guard: %s"),
            *DescribeCapture(*C), FSaskartaCaptureGuardLogic::RoleName(Role), T ? TEXT("") : TEXT(" (not yet tracked)"),
            C->bCaptureEveryFrame ? 1 : 0, C->bCaptureOnMovement ? 1 : 0, C->IsActive() ? 1 : 0, C->IsRegistered() ? 1 : 0,
            T ? FSaskartaCaptureGuardLogic::CommandName(T->Applied) : TEXT("-"));
    }
}
