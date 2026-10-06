// USaskartaSteleScanner (task STELESCAN). See SaskartaSteleScanner.h and docs/look/STELE_SCAN.md section 3.

#include "SaskartaSteleScanner.h"

#include "SaskartaEventRunner.h"
#include "SaskartaMotorAssist.h"
#include "SaskartaRadioStation.h"
#include "SaskartaSteleScanAsset.h"
#include "Camera/PlayerCameraManager.h"
#include "CollisionQueryParams.h"
#include "Components/PrimitiveComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Engine/AssetManager.h"
#include "Engine/Engine.h"
#include "Engine/HitResult.h"
#include "Engine/Level.h"
#include "Engine/StreamableManager.h"
#include "Engine/World.h"
#include "GameFramework/Actor.h"
#include "GameFramework/Pawn.h"
#include "GameFramework/PlayerController.h"
#include "HAL/IConsoleManager.h"
#include "InputCoreTypes.h"
#include "Kismet/GameplayStatics.h"
#include "Sound/SoundBase.h"
#include "TimerManager.h"

DEFINE_LOG_CATEGORY_STATIC(LogSaskartaSteles, Log, All);

namespace SaskartaSteles
{
    static const FName TagStele(TEXT("Stele"));
    static const FName TargetHud(TEXT("Hud"));
    static const FName FlowPlaying(TEXT("Playing"));
    constexpr float PollS = 0.25f;
    /** Key edge polling while the scan prompt is up (= FSaskartaEventLogic::PromptPollS). */
    constexpr float KeyPollS = 0.01f;
    constexpr float PrefetchAheadM = 150.f;
    /** A road jump larger than this (Continue, GoTo) marks the stones behind as read. */
    constexpr float RoadJumpM = 150.f;
}

// ============================================================================================ setup
USaskartaSteleScanner* USaskartaSteleScanner::GetSteleScanner(const UObject* WorldContextObject)
{
    const UWorld* World = GEngine ? GEngine->GetWorldFromContextObject(WorldContextObject, EGetWorldErrorMode::ReturnNull) : nullptr;
    return World ? World->GetSubsystem<USaskartaSteleScanner>() : nullptr;
}

bool USaskartaSteleScanner::DoesSupportWorldType(const EWorldType::Type WorldType) const
{
    return WorldType == EWorldType::Game || WorldType == EWorldType::PIE;
}

void USaskartaSteleScanner::Initialize(FSubsystemCollectionBase& Collection)
{
    Collection.InitializeDependency<USaskartaEventRunner>();
    Super::Initialize(Collection);
    LevelAddedHandle = FWorldDelegates::LevelAddedToWorld.AddUObject(this, &USaskartaSteleScanner::HandleLevelAdded);
}

void USaskartaSteleScanner::Deinitialize()
{
    FWorldDelegates::LevelAddedToWorld.Remove(LevelAddedHandle);
    LevelAddedHandle.Reset();
    if (USaskartaEventRunner* R = BoundRunner.Get())
    {
        R->OnCaptionShow.RemoveDynamic(this, &USaskartaSteleScanner::HandleCaptionShow);
        R->OnCaptionHide.RemoveDynamic(this, &USaskartaSteleScanner::HandleCaptionHide);
    }
    BoundRunner.Reset();
    if (UWorld* World = GetWorld())
    {
        FTimerManager& TM = World->GetTimerManager();
        TM.ClearTimer(PollTimer);
        TM.ClearTimer(TextTimer);
        TM.ClearTimer(VoiceTimer);
        TM.ClearTimer(HideTimer);
        TM.ClearTimer(KeyTimer);
    }
    PromptStele = INDEX_NONE;
    VoiceHandles.Reset();
    SoundHandle.Reset();
    Components.Reset();
    Super::Deinitialize();
}

void USaskartaSteleScanner::OnWorldBeginPlay(UWorld& InWorld)
{
    Super::OnWorldBeginPlay(InWorld);
    if (!Asset)
    {
        SetAsset(USaskartaSteleScanImport::LoadOrImportTransient(this));
    }
    if (USaskartaEventRunner* R = Runner())
    {
        R->OnCaptionShow.AddUniqueDynamic(this, &USaskartaSteleScanner::HandleCaptionShow);
        R->OnCaptionHide.AddUniqueDynamic(this, &USaskartaSteleScanner::HandleCaptionHide);
        BoundRunner = R;
    }
    for (ULevel* Level : InWorld.GetLevels())
    {
        RegisterLevel(Level);
    }
    InWorld.GetTimerManager().SetTimer(PollTimer, this, &USaskartaSteleScanner::Poll, SaskartaSteles::PollS, true);
    UE_LOG(LogSaskartaSteles, Log, TEXT("Stele scanner up: %d steles in the data, %d registered"),
        Core.Steles.Num(), Components.Num());
}

void USaskartaSteleScanner::SetAsset(USaskartaSteleScanAsset* InAsset)
{
    Asset = InAsset;
    RebuildCore();
    if (Asset && !Asset->PingSound.IsNull())
    {
        TArray<FSoftObjectPath> Paths;
        Paths.Add(Asset->PingSound.ToSoftObjectPath());
        if (!Asset->MatchSound.IsNull())
        {
            Paths.Add(Asset->MatchSound.ToSoftObjectPath());
        }
        SoundHandle = UAssetManager::GetStreamableManager().RequestAsyncLoad(Paths, FStreamableDelegate(),
            FStreamableManager::DefaultAsyncLoadPriority);
    }
}

void USaskartaSteleScanner::RebuildCore()
{
    SetPromptStele(INDEX_NONE);
    Core = FSaskartaSteleScanCore();
    FaceLocal.Reset();
    if (!Asset)
    {
        return;
    }
    Tuning = Asset->MakeTuning();
    for (const FSaskartaSteleDef& D : Asset->Steles)
    {
        FSaskartaSteleScanCore::FStele S;
        S.Id = D.Id;
        S.Inscription = D.Inscription;
        S.RoadM = D.RoadM;
        S.Wear = D.Wear;
        S.bDock = D.bDock;
        const FSaskartaInscriptionDef* Ins = Asset->FindInscription(D.Inscription);
        S.bNeverVoice = Ins ? Ins->bNeverVoice : true;
        Core.Steles.Add(S);
        FaceLocal.Add(D.Id, D.FaceCentreLocalCm);
    }
    Core.SortByRoad();
}

void USaskartaSteleScanner::HandleLevelAdded(ULevel* Level, UWorld* World)
{
    if (World == GetWorld())
    {
        RegisterLevel(Level);
    }
}

void USaskartaSteleScanner::RegisterLevel(ULevel* Level)
{
    if (!Level)
    {
        return;
    }
    for (AActor* A : Level->Actors)
    {
        if (!A || !A->ActorHasTag(SaskartaSteles::TagStele))
        {
            continue;
        }
        FName Id;
        for (const FName& Tag : A->Tags)
        {
            if (Tag != SaskartaSteles::TagStele && Tag.ToString().StartsWith(TEXT("Stele_")))
            {
                Id = Tag;
                break;
            }
        }
        UStaticMeshComponent* Mesh = A->FindComponentByClass<UStaticMeshComponent>();
        if (!Id.IsNone() && Mesh)
        {
            Components.Add(Id, TWeakObjectPtr<UPrimitiveComponent>(Mesh));
        }
    }
}

USaskartaEventRunner* USaskartaSteleScanner::Runner() const
{
    return USaskartaEventRunner::GetEventRunner(this);
}

double USaskartaSteleScanner::Now() const
{
    const UWorld* World = GetWorld();
    return World ? World->GetTimeSeconds() : 0.0;
}

UPrimitiveComponent* USaskartaSteleScanner::ComponentFor(int32 Index) const
{
    if (!Core.Steles.IsValidIndex(Index))
    {
        return nullptr;
    }
    const TWeakObjectPtr<UPrimitiveComponent>* Found = Components.Find(Core.Steles[Index].Id);
    return Found ? Found->Get() : nullptr;
}

int32 USaskartaSteleScanner::ApplyCpd(UPrimitiveComponent* Component, const TArray<FSaskartaSteleCpdWrite>& Writes)
{
    if (!Component)
    {
        return 0;
    }
    for (const FSaskartaSteleCpdWrite& W : Writes)
    {
        Component->SetCustomPrimitiveDataFloat(W.Index, W.Value);
    }
    return Writes.Num();
}

// ============================================================================================ the clock
void USaskartaSteleScanner::Poll()
{
    UWorld* World = GetWorld();
    USaskartaEventRunner* R = Runner();
    if (!World || !R || !Asset || Core.Steles.Num() == 0)
    {
        return;
    }
    const float RoadM = R->GetRoadM();
    if (RoadM < 0.f)
    {
        return;
    }
    if (LastRoadM < 0.f || FMath::Abs(RoadM - LastRoadM) > SaskartaSteles::RoadJumpM)
    {
        const int32 Marked = Core.MarkBehind(RoadM, Tuning);
        if (Marked > 0)
        {
            UE_LOG(LogSaskartaSteles, Log, TEXT("road %.0f m: %d steles behind count as read"), RoadM, Marked);
        }
    }
    LastRoadM = RoadM;
    Prefetch(RoadM);

    const double T = Now();
    if (T < Core.BusyUntilS)
    {
        SetPromptStele(INDEX_NONE);
        return;
    }
    const FName Flow = R->GetFlowState();
    const bool bCanRead = (Flow.IsNone() || Flow == SaskartaSteles::FlowPlaying) && !R->IsCinematicActive()
        && (!Tuning.bPrompted || CanPrompt(R));
    if (!bCanRead)
    {
        SetPromptStele(INDEX_NONE);
        return;
    }
    APlayerController* PC = World->GetFirstPlayerController();
    if (!PC || !PC->PlayerCameraManager)
    {
        SetPromptStele(INDEX_NONE);
        return;
    }
    const FVector CamLoc = PC->PlayerCameraManager->GetCameraLocation();
    const FVector CamFwd = PC->PlayerCameraManager->GetCameraRotation().Vector();

    TArray<int32> Candidates;
    Core.Candidates(RoadM, Tuning, Candidates);
    TArray<FSaskartaSteleView> Views;
    TArray<FVector> Faces;
    for (const int32 I : Candidates)
    {
        FSaskartaSteleView V;
        FVector Face;
        if (BuildView(I, CamLoc, CamFwd, V, Face))
        {
            Views.Add(V);
            Faces.Add(Face);
        }
    }
    // One visibility trace per tick: for the closest view that passes everything but sight.
    int32 Best = INDEX_NONE;
    for (int32 I = 0; I < Views.Num(); ++I)
    {
        FSaskartaSteleView Probe = Views[I];
        Probe.bLineOfSight = true;
        const bool bDock = Core.Steles[Probe.Index].bDock;
        const bool bOk = Tuning.bPrompted
            ? FSaskartaSteleScanCore::EligibleForPrompt(Probe, bDock, Probe.Index == PromptStele, Tuning)
            : FSaskartaSteleScanCore::Eligible(Probe, bDock, Tuning);
        if (bOk && Tuning.bPrompted && Probe.Index == PromptStele)
        {
            Best = I;   // the offered stone keeps the trace (hysteresis), as PromptTarget keeps it
            break;
        }
        if (bOk
            && (Best == INDEX_NONE || Probe.DistanceM < Views[Best].DistanceM))
        {
            Best = I;
        }
    }
    if (Best == INDEX_NONE)
    {
        SetPromptStele(INDEX_NONE);
        return;
    }
    const UPrimitiveComponent* Comp = ComponentFor(Views[Best].Index);
    Views[Best].bLineOfSight = LineOfSight(CamLoc, Faces[Best], Comp ? Comp->GetOwner() : nullptr);
    if (Tuning.bPrompted)
    {
        SetPromptStele(Core.PromptTarget(T, true, PromptStele, Views, Tuning));
        return;
    }
    const float HudFor = bHudBusy ? static_cast<float>(T - HudBusySinceS) : 0.f;
    const FSaskartaSteleReadDecision D = Core.Decide(T, true, bHudBusy, HudFor, Views, Tuning);
    if (D.IsRead())
    {
        StartReading(D, T);
    }
}

// ============================================================================================ the prompt
bool USaskartaSteleScanner::CanPrompt(const USaskartaEventRunner* R) const
{
    if (!R || R->IsPromptActive() || R->IsStorySubtitleActive() || R->IsHoldingInput())
    {
        return false;
    }
    const UWorld* World = GetWorld();
    const USaskartaMotorAssistSubsystem* Motor = World ? World->GetSubsystem<USaskartaMotorAssistSubsystem>() : nullptr;
    return !(Motor && Motor->IsMotorPromptActive());
}

void USaskartaSteleScanner::SetPromptStele(int32 Index)
{
    if (Index == PromptStele)
    {
        return;
    }
    UWorld* World = GetWorld();
    USaskartaEventRunner* R = Runner();
    const FName Target = Asset ? Asset->PromptTarget : FName(TEXT("ScanPrompt"));
    PromptStele = Index;
    if (Index == INDEX_NONE)
    {
        if (World)
        {
            World->GetTimerManager().ClearTimer(KeyTimer);
        }
        if (R)
        {
            TGuardValue<bool> Self(bSelfCaption, true);
            R->OnCaptionHide.Broadcast(Target);
        }
        OnScanPromptChanged.Broadcast(NAME_None);
        return;
    }
    // A key held while the prompt appears must be released before it can answer it.
    const APlayerController* PC = World ? World->GetFirstPlayerController() : nullptr;
    bScanKeyWasDown = PC && PC->IsInputKeyDown(EKeys::E);
    bScanPadWasDown = PC && PC->IsInputKeyDown(EKeys::Gamepad_FaceButton_Bottom);
    if (R)
    {
        TGuardValue<bool> Self(bSelfCaption, true);
        R->OnCaptionShow.Broadcast(FText::FromString(FSaskartaSteleScanCore::PromptLine(Asset ? Asset->PromptLabel : FString())),
            Target, 0.f);
    }
    if (World)
    {
        World->GetTimerManager().SetTimer(KeyTimer, this, &USaskartaSteleScanner::PollScanKey, SaskartaSteles::KeyPollS, true);
    }
    OnScanPromptChanged.Broadcast(Core.Steles[Index].Id);
}

void USaskartaSteleScanner::PollScanKey()
{
    UWorld* World = GetWorld();
    const APlayerController* PC = World ? World->GetFirstPlayerController() : nullptr;
    if (PromptStele == INDEX_NONE || !PC)
    {
        return;
    }
    const bool bKey = PC->IsInputKeyDown(EKeys::E);
    const bool bPad = PC->IsInputKeyDown(EKeys::Gamepad_FaceButton_Bottom);
    const bool bPressed = (bKey && !bScanKeyWasDown) || (bPad && !bScanPadWasDown);
    bScanKeyWasDown = bKey;
    bScanPadWasDown = bPad;
    if (bPressed)
    {
        ScanPromptedStele();
    }
}

bool USaskartaSteleScanner::ScanPromptedStele()
{
    const int32 Index = PromptStele;
    USaskartaEventRunner* R = Runner();
    if (Index == INDEX_NONE || !Asset || !Core.Steles.IsValidIndex(Index))
    {
        return false;
    }
    // Something took the screen since the last poll (a cinematic, a story line, another E prompt).
    const FName Flow = R ? R->GetFlowState() : NAME_None;
    if (!R || !(Flow.IsNone() || Flow == SaskartaSteles::FlowPlaying) || R->IsCinematicActive() || !CanPrompt(R))
    {
        SetPromptStele(INDEX_NONE);
        return false;
    }
    const FName Id = Core.Steles[Index].Id;
    if (ScanChargeHook.IsBound() && !ScanChargeHook.Execute(Id, Tuning.ScanChargeCost))
    {
        UE_LOG(LogSaskartaSteles, Log, TEXT("%s: scan refused by the charge hook"), *Id.ToString());
        return false;
    }
    const double T = Now();
    const FSaskartaSteleReadDecision D = Core.BeginRead(T, Index, Tuning);
    SetPromptStele(INDEX_NONE);
    if (!D.IsRead())
    {
        return false;
    }
    StartReading(D, T);
    return true;
}

bool USaskartaSteleScanner::BuildView(int32 Index, const FVector& CamLoc, const FVector& CamFwd, FSaskartaSteleView& OutView, FVector& OutFace) const
{
    const UPrimitiveComponent* Comp = ComponentFor(Index);
    const AActor* Owner = Comp ? Comp->GetOwner() : nullptr;
    if (!Owner)
    {
        return false; // not streamed in
    }
    const FVector* Local = FaceLocal.Find(Core.Steles[Index].Id);
    OutFace = Owner->GetActorTransform().TransformPosition(Local ? *Local : FVector::ZeroVector);
    const FVector ToCam = CamLoc - OutFace;
    const float DistCm = static_cast<float>(ToCam.Size());
    OutView.Index = Index;
    OutView.DistanceM = DistCm / 100.f;
    OutView.FaceDot = DistCm > 1.f ? static_cast<float>(FVector::DotProduct(Owner->GetActorForwardVector(), ToCam / DistCm)) : 1.f;
    const FVector ToFace = DistCm > 1.f ? -ToCam / DistCm : CamFwd;
    const double Cos = FMath::Clamp(FVector::DotProduct(CamFwd.GetSafeNormal(), ToFace), -1.0, 1.0);
    OutView.ViewAngleDeg = static_cast<float>(FMath::RadiansToDegrees(FMath::Acos(Cos)));
    OutView.bLineOfSight = false;
    return true;
}

bool USaskartaSteleScanner::LineOfSight(const FVector& From, const FVector& To, const AActor* Stele) const
{
    UWorld* World = GetWorld();
    if (!World)
    {
        return false;
    }
    FCollisionQueryParams Params(SCENE_QUERY_STAT(SaskartaSteleScan), false);
    if (APlayerController* PC = World->GetFirstPlayerController())
    {
        if (APawn* Pawn = PC->GetPawn())
        {
            Params.AddIgnoredActor(Pawn);
            TArray<AActor*> Attached;
            Pawn->GetAttachedActors(Attached, true, true);
            Params.AddIgnoredActors(Attached);
        }
    }
    FHitResult Hit;
    if (!World->LineTraceSingleByChannel(Hit, From, To, ECC_Visibility, Params))
    {
        return true;
    }
    return Hit.GetActor() == Stele;
}

void USaskartaSteleScanner::Prefetch(float RoadM)
{
    for (const FSaskartaSteleScanCore::FStele& S : Core.Steles)
    {
        if (S.bRead || S.RoadM < RoadM || S.RoadM > RoadM + SaskartaSteles::PrefetchAheadM
            || VoiceHandles.Contains(S.Inscription))
        {
            continue;
        }
        const FSaskartaInscriptionDef* Ins = Asset->FindInscription(S.Inscription);
        if (!Ins || Ins->Voice.IsNull() || Ins->bNeverVoice || Core.Completed.Contains(S.Inscription))
        {
            continue;
        }
        VoiceHandles.Add(S.Inscription, UAssetManager::GetStreamableManager().RequestAsyncLoad(
            Ins->Voice.ToSoftObjectPath(), FStreamableDelegate(), FStreamableManager::DefaultAsyncLoadPriority));
    }
}

// ============================================================================================ a reading
FString USaskartaSteleScanner::ApproxFor(const FSaskartaInscriptionDef& Ins) const
{
    if (!Ins.ResolvesAfterBeat.IsNone() && !Ins.EnglishApproxResolved.IsEmpty())
    {
        if (const USaskartaEventRunner* R = Runner())
        {
            if (R->HasBeatFired(Ins.ResolvesAfterBeat))
            {
                return Ins.EnglishApproxResolved;
            }
        }
    }
    return Ins.EnglishApprox;
}

bool USaskartaSteleScanner::DescribeStele(FName SteleId, FSaskartaSteleLogEntry& Out) const
{
    const int32 Index = Core.FindStele(SteleId);
    if (Index == INDEX_NONE)
    {
        return false;
    }
    const FSaskartaSteleScanCore::FStele& S = Core.Steles[Index];
    Out = FSaskartaSteleLogEntry();
    Out.SteleId = S.Id;
    Out.InscriptionId = S.Inscription;
    Out.RoadM = S.RoadM;
    if (const FSaskartaInscriptionDef* Ins = Asset ? Asset->FindInscription(S.Inscription) : nullptr)
    {
        // Exactly the full reading's second and third lines.
        TArray<FString> Lines;
        FSaskartaSteleScanCore::FullText(0, Ins->Saskartan, Ins->MachineTranslit, ApproxFor(*Ins), Asset->ResolvedMark)
            .ParseIntoArrayLines(Lines, false);
        Out.Translit = Lines.IsValidIndex(1) ? Lines[1].TrimStartAndEnd() : FString();
        Out.EnglishLine = Lines.IsValidIndex(2) ? Lines[2].TrimStartAndEnd() : FString();
    }
    const UPrimitiveComponent* Comp = ComponentFor(Index);
    if (const AActor* Owner = Comp ? Comp->GetOwner() : nullptr)
    {
        const FVector* Local = FaceLocal.Find(S.Id);
        Out.Location = Owner->GetActorTransform().TransformPosition(Local ? *Local : FVector::ZeroVector);
        Out.bHasLocation = true;
    }
    return true;
}

void USaskartaSteleScanner::StartReading(const FSaskartaSteleReadDecision& D, double NowS)
{
    UWorld* World = GetWorld();
    const FSaskartaSteleScanCore::FStele& S = Core.Steles[D.Stele];
    const FSaskartaInscriptionDef* Ins = Asset ? Asset->FindInscription(S.Inscription) : nullptr;
    if (!World || !Ins)
    {
        return;
    }
    FTimerManager& TM = World->GetTimerManager();
    TM.ClearTimer(TextTimer);
    TM.ClearTimer(VoiceTimer);
    TM.ClearTimer(HideTimer);
    ActiveStele = D.Stele;
    ActiveKind = D.Kind;
    bActiveTryVoice = D.bTryVoice;
    ActiveNumber = D.Number;
    ActiveStartS = NowS;

    const bool bFull = D.Kind == ESaskartaSteleReadKind::Full;
    const float GlowHold = bFull ? Tuning.SweepS + Tuning.TextOnlyHoldS : 0.f;
    ApplyCpd(ComponentFor(D.Stele), FSaskartaSteleScanCore::StartCpd(D.Kind, NowS, GlowHold));
    UE_LOG(LogSaskartaSteles, Log, TEXT("%s: %s %02d (%s)%s"), *S.Id.ToString(), bFull ? TEXT("reading") : TEXT("match"),
        D.Number, *S.Inscription.ToString(), D.bTryVoice ? TEXT(", voice") : TEXT(""));

    if (bFull)
    {
        if (USoundBase* Ping = Asset->PingSound.Get())
        {
            UGameplayStatics::PlaySound2D(this, Ping, Asset->PingVolume);
        }
        ShowCaption(FSaskartaSteleScanCore::ReadingHeader(D.Number));
        TM.SetTimer(TextTimer, this, &USaskartaSteleScanner::ShowReadingText, FMath::Max(0.01f, Tuning.TextAtS), false);
        return;
    }
    if (USoundBase* Tick = Asset->MatchSound.Get())
    {
        UGameplayStatics::PlaySound2D(this, Tick, Asset->PingVolume * 0.5f);
    }
    const FString Approx = ApproxFor(*Ins);
    const FString Line = FSaskartaSteleScanCore::MatchLine(D.Number, Approx, S.Wear, Tuning.WornWear, Asset->ResolvedMark);
    ShowCaption(Line);
    FSaskartaSteleReadout Out;
    Out.SteleId = S.Id;
    Out.InscriptionId = S.Inscription;
    Out.Number = D.Number;
    Out.bMatch = true;
    Out.Text = Line;
    Out.EnglishApprox = Approx;
    Out.AtlasCell = Ins->AtlasCell;
    OnSteleRead.Broadcast(Out);
    TM.SetTimer(HideTimer, this, &USaskartaSteleScanner::HideCaption, FMath::Max(0.1f, Tuning.MatchSweepS + Tuning.MatchHoldS), false);
}

void USaskartaSteleScanner::ShowReadingText()
{
    UWorld* World = GetWorld();
    if (!World || !Core.Steles.IsValidIndex(ActiveStele) || !Asset)
    {
        return;
    }
    const FSaskartaSteleScanCore::FStele& S = Core.Steles[ActiveStele];
    const FSaskartaInscriptionDef* Ins = Asset->FindInscription(S.Inscription);
    if (!Ins)
    {
        return;
    }
    const FString Approx = ApproxFor(*Ins);
    const FString Text = FSaskartaSteleScanCore::FullText(ActiveNumber, Ins->Saskartan, Ins->MachineTranslit, Approx, Asset->ResolvedMark);
    ShowCaption(Text);
    FSaskartaSteleReadout Out;
    Out.SteleId = S.Id;
    Out.InscriptionId = S.Inscription;
    Out.Number = ActiveNumber;
    Out.bMatch = false;
    Out.Text = Text;
    Out.EnglishApprox = Approx;
    Out.AtlasCell = Ins->AtlasCell;
    OnSteleRead.Broadcast(Out);

    if (!bActiveTryVoice || Ins->Voice.IsNull())
    {
        EndVoice(false, false, Tuning.TextOnlyHoldS);
        return;
    }
    // Prefetch can still be in flight when the inscription comes into view. Keep its request alive
    // and give it the same bounded voice window as a busy Voice channel.
    const TSharedPtr<FStreamableHandle>* Handle = VoiceHandles.Find(S.Inscription);
    if (!Ins->Voice.Get() && (!Handle || !Handle->IsValid()))
    {
        VoiceHandles.Add(S.Inscription, UAssetManager::GetStreamableManager().RequestAsyncLoad(
            Ins->Voice.ToSoftObjectPath(), FStreamableDelegate(), FStreamableManager::DefaultAsyncLoadPriority));
    }
    VoiceAskSinceS = Now();
    World->GetTimerManager().SetTimer(VoiceTimer, this, &USaskartaSteleScanner::VoiceStep, SaskartaSteles::PollS, true,
        FMath::Max(0.01f, Tuning.VoiceAtS - Tuning.TextAtS));
}

void USaskartaSteleScanner::VoiceStep()
{
    USaskartaEventRunner* R = Runner();
    if (!R || !Asset || !Core.Steles.IsValidIndex(ActiveStele))
    {
        EndVoice(true, false, Tuning.HoldAfterVoiceS);
        return;
    }
    const FSaskartaInscriptionDef* Ins = Asset->FindInscription(Core.Steles[ActiveStele].Inscription);
    USoundBase* Voice = Ins ? Ins->Voice.Get() : nullptr;
    const double T = Now();
    if (Voice && R->TryPlayAuxCarrierLine(Ins->VoiceLineId, Voice, Ins->DurationS, Tuning.VoiceMinGapS, Tuning.VoiceLeadS))
    {
        const float ClipS = Voice->GetDuration() > 0.f ? Voice->GetDuration() : FMath::Max(Ins->DurationS, 1.f);
        FSaskartaSteleCpdWrite Hold;
        Hold.Index = SaskartaSteleCpd::GlowHold;
        Hold.Value = FSaskartaSteleScanCore::GlowHoldForVoice(ActiveStartS, T, ClipS);
        ApplyCpd(ComponentFor(ActiveStele), { Hold });
        // The reading is spoken over the radio, which dips while it plays (the author, 2026-09-29).
        if (USaskartaRadioStation* Station = USaskartaRadioStation::GetRadioStation(this))
        {
            Station->SetUnderVoice(true);
            if (UWorld* World = GetWorld())
            {
                World->GetTimerManager().SetTimer(UnderReleaseTimer, FTimerDelegate::CreateWeakLambda(this, [this]()
                {
                    if (USaskartaRadioStation* S = USaskartaRadioStation::GetRadioStation(this))
                    {
                        S->SetUnderVoice(false);
                    }
                }), ClipS + 0.25f, false);
            }
        }
        Core.ExtendBusy(T + ClipS + Tuning.HoldAfterVoiceS);
        EndVoice(true, true, ClipS + Tuning.HoldAfterVoiceS);
        return;
    }
    if (T - VoiceAskSinceS >= Tuning.VoiceWaitMaxS)
    {
        // The clip may still be loading, or the Voice channel may be busy. Neither completes a voiced text.
        const float Left = static_cast<float>(ActiveStartS + Tuning.TextAtS + Tuning.TextOnlyHoldS - T);
        EndVoice(true, false, FMath::Max(Left, Tuning.HoldAfterVoiceS));
    }
}

void USaskartaSteleScanner::EndVoice(bool bAttempted, bool bPlayed, float HideInS)
{
    if (UWorld* World = GetWorld())
    {
        World->GetTimerManager().ClearTimer(VoiceTimer);
        World->GetTimerManager().SetTimer(HideTimer, this, &USaskartaSteleScanner::HideCaption, FMath::Max(0.1f, HideInS), false);
    }
    if (Core.Steles.IsValidIndex(ActiveStele) && ActiveKind == ESaskartaSteleReadKind::Full)
    {
        Core.OnVoiceResult(Core.Steles[ActiveStele].Inscription, bAttempted, bPlayed);
        if (!bPlayed && bAttempted)
        {
            UE_LOG(LogSaskartaSteles, Log, TEXT("%s: voice refused for %.1f s, text only"),
                *Core.Steles[ActiveStele].Id.ToString(), Tuning.VoiceWaitMaxS);
        }
    }
}

void USaskartaSteleScanner::ShowCaption(const FString& Text)
{
    if (USaskartaEventRunner* R = Runner())
    {
        TGuardValue<bool> Self(bSelfCaption, true);
        R->OnCaptionShow.Broadcast(FText::FromString(Text), Asset ? Asset->CaptionTarget : FName(TEXT("Scan")), 0.f);
    }
}

void USaskartaSteleScanner::HideCaption()
{
    if (USaskartaEventRunner* R = Runner())
    {
        TGuardValue<bool> Self(bSelfCaption, true);
        R->OnCaptionHide.Broadcast(Asset ? Asset->CaptionTarget : FName(TEXT("Scan")));
    }
    ActiveStele = INDEX_NONE;
    ActiveKind = ESaskartaSteleReadKind::None;
}

void USaskartaSteleScanner::HandleCaptionShow(const FText& Text, FName Target, float DurationS)
{
    if (!bSelfCaption && Target == SaskartaSteles::TargetHud)
    {
        bHudBusy = true;
        HudBusySinceS = Now();
    }
}

void USaskartaSteleScanner::HandleCaptionHide(FName Target)
{
    if (!bSelfCaption && Target == SaskartaSteles::TargetHud)
    {
        bHudBusy = false;
    }
}

// ============================================================================================ debug
bool USaskartaSteleScanner::ForceRead(FName SteleId)
{
    const int32 Index = Core.FindStele(SteleId);
    if (Index == INDEX_NONE || !Asset)
    {
        return false;
    }
    SetPromptStele(INDEX_NONE);
    Core.Steles[Index].bRead = false;
    Core.BusyUntilS = 0.0;
    FSaskartaSteleView V;
    V.Index = Index;
    V.DistanceM = FMath::Max(Tuning.MinRangeM, 1.f);
    V.ViewAngleDeg = 0.f;
    V.FaceDot = 1.f;
    V.bLineOfSight = true;
    const double T = Now();
    const FSaskartaSteleReadDecision D = Core.Decide(T, true, false, 0.f, { V }, Tuning);
    if (!D.IsRead())
    {
        return false;
    }
    StartReading(D, T);
    return true;
}

void USaskartaSteleScanner::ResetReadings()
{
    SetPromptStele(INDEX_NONE);
    Core.ResetReadings();
    LastRoadM = -1.f;
    VoiceHandles.Reset();
}

FString USaskartaSteleScanner::DumpState() const
{
    FString Out = FString::Printf(TEXT("Stele scanner: %d steles in the data, %d registered, road %.0f m, busy %.1f s, HUD %s\n"),
        Core.Steles.Num(), Components.Num(), LastRoadM, FMath::Max(0.0, Core.BusyUntilS - Now()), bHudBusy ? TEXT("busy") : TEXT("free"));
    for (const FSaskartaSteleScanCore::FStele& S : Core.Steles)
    {
        const TWeakObjectPtr<UPrimitiveComponent>* C = Components.Find(S.Id);
        const int32* Number = Core.Numbers.Find(S.Inscription);
        Out += FString::Printf(TEXT("  %-20s %6.0f m %-4s wear %.2f %s %s #%d%s\n"), *S.Id.ToString(), S.RoadM,
            *S.Inscription.ToString(), S.Wear, S.bRead ? TEXT("read  ") : TEXT("unread"),
            (C && C->IsValid()) ? TEXT("loaded") : TEXT("-     "), Number ? *Number : 0,
            Core.Completed.Contains(S.Inscription) ? TEXT(" done") : TEXT(""));
    }
    return Out;
}

namespace SaskartaSteles
{
    static USaskartaSteleScanner* ScannerFor(UWorld* World)
    {
        return World ? World->GetSubsystem<USaskartaSteleScanner>() : nullptr;
    }

    static FAutoConsoleCommandWithWorldAndArgs CmdDump(TEXT("Saskarta.Steles.Dump"),
        TEXT("Logs the stele scanner: every stone, its road m, text, read state and number."),
        FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>&, UWorld* World)
        {
            if (USaskartaSteleScanner* S = ScannerFor(World))
            {
                UE_LOG(LogSaskartaSteles, Display, TEXT("%s"), *S->DumpState());
            }
        }));

    static FAutoConsoleCommandWithWorldAndArgs CmdRead(TEXT("Saskarta.Steles.Read"),
        TEXT("Saskarta.Steles.Read <SteleId>: reads that stone now (ignores range, angle, sight and pacing)."),
        FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>& Args, UWorld* World)
        {
            USaskartaSteleScanner* S = ScannerFor(World);
            if (S && Args.Num() > 0)
            {
                UE_LOG(LogSaskartaSteles, Display, TEXT("Saskarta.Steles.Read %s: %s"), *Args[0],
                    S->ForceRead(FName(*Args[0])) ? TEXT("reading") : TEXT("unknown stele"));
            }
        }));

    static FAutoConsoleCommandWithWorldAndArgs CmdReset(TEXT("Saskarta.Steles.Reset"),
        TEXT("Forgets every reading (all stones unread, numbering restarts)."),
        FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>&, UWorld* World)
        {
            if (USaskartaSteleScanner* S = ScannerFor(World))
            {
                S->ResetReadings();
            }
        }));
}
