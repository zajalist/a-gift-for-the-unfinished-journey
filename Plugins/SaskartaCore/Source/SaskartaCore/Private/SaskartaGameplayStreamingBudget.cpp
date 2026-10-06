#include "SaskartaGameplayStreamingBudget.h"

#include "Blueprint/UserWidget.h"
#include "Components/ActorComponent.h"
#include "CoreGlobals.h"
#include "Engine/Engine.h"
#include "Engine/GameInstance.h"
#include "Engine/World.h"
#include "GameFramework/Character.h"
#include "GameFramework/Pawn.h"
#include "GameFramework/PlayerController.h"
#include "HAL/IConsoleManager.h"
#include "HAL/PlatformTime.h"
#include "Misc/App.h"
#include "Misc/CoreDelegates.h"
#include "SaskartaEventRunner.h"
#include "SaskartaLoadingBudget.h"
#include "UObject/UObjectGlobals.h"
#include "UObject/UnrealType.h"
#include "WorldPartition/WorldPartitionSubsystem.h"

DEFINE_LOG_CATEGORY_STATIC(LogSaskartaGameplayStreaming, Log, All);

namespace SaskartaGameplayStreaming
{
    static TAutoConsoleVariable<int32> Enable(TEXT("saskarta.gameplaystreaming.Enable"), 1,
        TEXT("Time-slice streaming during interactive Carrier play and the elder walk; restores on pause/loading/cinematic/teardown."));
    static TAutoConsoleVariable<int32> Log(TEXT("saskarta.gameplaystreaming.Log"), 0,
        TEXT("Optional five-second and pre-GC native streaming snapshots. Does not identify the GC caller or full-purge flag."));
    static TWeakObjectPtr<UWorld> LeaseWorld;

    struct FCap { const TCHAR* Name; float Limit; bool bZeroIsUnlimited; };
    // Verified against local UE 5.8.2 CoreSettings.cpp and WorldPartitionSubsystem.cpp.
    static const FCap Caps[] = {
        { TEXT("s.AsyncLoadingTimeLimit"), 3.f, false },
        { TEXT("s.AsyncLoadingUseFullTimeLimit"), 0.f, false },
        { TEXT("s.PriorityAsyncLoadingExtraTime"), 0.f, false },
        { TEXT("s.LevelStreamingActorsUpdateTimeLimit"), 2.f, false },
        { TEXT("s.PriorityLevelStreamingActorsUpdateExtraTime"), 0.f, false },
        { TEXT("s.AdaptiveAddToWorld.Enabled"), 0.f, false },
        { TEXT("s.LevelStreamingComponentsRegistrationGranularity"), 4.f, true },
        { TEXT("s.LevelStreamingAddPrimitiveGranularity"), 32.f, true },
        { TEXT("s.LevelStreamingRouteActorInitializationGranularity"), 4.f, true },
        { TEXT("s.UnregisterComponentsTimeLimit"), 1.f, true },
        { TEXT("s.LevelStreamingComponentsUnregistrationGranularity"), 2.f, true },
        { TEXT("wp.Runtime.MaxLoadingStreamingCells"), 2.f, true }
    };

    bool VisibleWidget(const UObject* Object, FName Name)
    {
        if (!Object) return false;
        const FObjectPropertyBase* P = FindFProperty<FObjectPropertyBase>(Object->GetClass(), Name);
        const UUserWidget* Widget = P ? Cast<UUserWidget>(P->GetObjectPropertyValue_InContainer(Object)) : nullptr;
        return Widget && Widget->IsInViewport() && Widget->IsVisible() && Widget->GetRenderOpacity() > 0.f;
    }

    bool IsInteractiveTraveller(const APawn* Pawn, const APlayerController* PC)
    {
        if (!Cast<ACharacter>(Pawn) || PC->IsMoveInputIgnored() || PC->IsLookInputIgnored()) return false;
        // Match the EventRunner's authored traveller class (including derived classes)
        // without loading an asset on the gameplay thread. Human flow also covers
        // handoff/ending poses, so the explicit StartWalk/StopWalk flag is required.
        bool bTraveller = false;
        for (const UClass* Class = Pawn->GetClass(); Class; Class = Class->GetSuperClass())
        {
            if (Class->GetPathName() == TEXT("/Game/SaskartaGaea/Characters/Traveller/BP_Saskarta_Traveller.BP_Saskarta_Traveller_C"))
            {
                bTraveller = true;
                break;
            }
        }
        const FBoolProperty* Walking = bTraveller ? FindFProperty<FBoolProperty>(Pawn->GetClass(), TEXT("bWalking")) : nullptr;
        return Walking && Walking->GetPropertyValue_InContainer(Pawn);
    }

    // ResolveContext exposes the highest history tag without mutating the CVar.
    bool HasTag(IConsoleVariable* V, FName Tag, uint32 SetBy)
    {
        if (!V || (static_cast<uint32>(V->GetFlags()) & ECVF_SetByMask) != SetBy) return false;
        IConsoleVariable::FSetContext Context;
        Context.PriorityMode = IConsoleVariable::FSetContext::EPriorityMode::ReplaceCurrent;
        Context.TagMode = IConsoleVariable::FSetContext::ETagMode::ReplaceCurrent;
        Context.MinPriority = ECVF_SetByScalability;
        return V->ResolveContext(Context).Tag == Tag;
    }
}

bool USaskartaGameplayStreamingBudget::DoesSupportWorldType(const EWorldType::Type Type) const
{
    return Type == EWorldType::Game || Type == EWorldType::PIE;
}

void USaskartaGameplayStreamingBudget::Initialize(FSubsystemCollectionBase& Collection)
{
    Super::Initialize(Collection);
    OwnerTag = FName(*FString::Printf(TEXT("SaskartaGameplayStreaming_%u"), GetUniqueID()));
    EndFrameHandle = FCoreDelegates::OnEndFrame.AddUObject(this, &USaskartaGameplayStreamingBudget::OnEndFrame);
    CleanupHandle = FWorldDelegates::OnWorldCleanup.AddUObject(this, &USaskartaGameplayStreamingBudget::OnWorldCleanup);
    WorldTickHandle = FWorldDelegates::OnWorldTickStart.AddUObject(this, &USaskartaGameplayStreamingBudget::OnWorldTickStart);
    PreGCHandle = FCoreUObjectDelegates::GetPreGarbageCollectDelegate().AddUObject(this, &USaskartaGameplayStreamingBudget::OnPreGarbageCollect);
}

void USaskartaGameplayStreamingBudget::PreDeinitialize()
{
    bStopped = true;
    ReleaseBudget(TEXT("pre-deinitialize"));
    Super::PreDeinitialize();
}

void USaskartaGameplayStreamingBudget::Deinitialize()
{
    bStopped = true;
    ReleaseBudget(TEXT("deinitialize"));
    FCoreDelegates::OnEndFrame.Remove(EndFrameHandle);
    FWorldDelegates::OnWorldCleanup.Remove(CleanupHandle);
    FWorldDelegates::OnWorldTickStart.Remove(WorldTickHandle);
    FCoreUObjectDelegates::GetPreGarbageCollectDelegate().Remove(PreGCHandle);
    Super::Deinitialize();
}

void USaskartaGameplayStreamingBudget::OnWorldEndPlay(UWorld& InWorld)
{
    if (&InWorld == GetWorld()) { bStopped = true; ReleaseBudget(TEXT("end-play")); }
    Super::OnWorldEndPlay(InWorld);
}

void USaskartaGameplayStreamingBudget::OnWorldCleanup(UWorld* World, bool, bool)
{
    if (World == GetWorld()) { bStopped = true; ReleaseBudget(TEXT("world-cleanup")); }
}

void USaskartaGameplayStreamingBudget::OnWorldTickStart(UWorld* World, ELevelTick, float)
{
    if (World && World != GetWorld() && World->IsGameWorld() && bActive)
    {
        bRelinquished = true;
        ReleaseBudget(TEXT("other-game-world"));
    }
    else if (World == GetWorld() && bActive && !CanApply())
    {
        ReleaseBudget(TEXT("inactive-before-world-tick"));
    }
}

bool USaskartaGameplayStreamingBudget::CanApply() const
{
    using namespace SaskartaGameplayStreaming;
    UWorld* World = GetWorld();
    if (bStopped || !World || !World->HasBegunPlay() || World->bIsTearingDown || World->IsBeingCleanedUp()
        || World->IsPaused() || World->GetNetMode() == NM_DedicatedServer || !GEngine || !FApp::HasFocus()) return false;
    // CVars are process-wide. Never acquire while another Game/PIE world can observe them.
    int32 GameWorlds = 0;
    for (const FWorldContext& Context : GEngine->GetWorldContexts())
        if (Context.World() && (Context.WorldType == EWorldType::Game || Context.WorldType == EWorldType::PIE)) ++GameWorlds;
    if (GameWorlds != 1 || (LeaseWorld.IsValid() && LeaseWorld.Get() != World)) return false;
    UGameInstance* GI = World->GetGameInstance();
    const APlayerController* PC = GI ? GI->GetFirstLocalPlayerController(World) : nullptr;
    const APawn* Pawn = PC ? PC->GetPawn() : nullptr;
    if (!PC || PC->GetWorld() != World || PC->bCinematicMode || !Pawn) return false;
    const USaskartaEventRunner* Runner = World->GetSubsystem<USaskartaEventRunner>();
    if (!Runner || Runner->IsCinematicActive() || Runner->IsHoldingInput() || Runner->IsPromptActive()) return false;
    const FName Flow = Runner->GetFlowState();
    const bool bCarrierPlay = (Flow == FName(TEXT("Playing")) || Flow == FName(TEXT("Carrier")))
        && Pawn->GetClass()->GetName().StartsWith(TEXT("BP_Saskarta_Carrier"));
    const bool bElderWalk = Flow == FName(TEXT("Human")) && IsInteractiveTraveller(Pawn, PC);
    if (!bCarrierPlay && !bElderWalk) return false;
    const USaskartaLoadingBudget* Loading = GI->GetSubsystem<USaskartaLoadingBudget>();
    if (Loading && Loading->IsLoadingBudgetActive()) return false;
    if (VisibleWidget(PC, TEXT("LoadingWidget")) || VisibleWidget(PC, TEXT("IntroWidget")) || VisibleWidget(PC, TEXT("PauseWidget"))) return false;
    TInlineComponentArray<UActorComponent*> Components(PC);
    for (const UActorComponent* C : Components)
        if (C && C->GetClass()->GetName().StartsWith(TEXT("BPC_CarrierVision")) && VisibleWidget(C, TEXT("BootLogWidget"))) return false;
    return true;
}

void USaskartaGameplayStreamingBudget::OnEndFrame()
{
    using namespace SaskartaGameplayStreaming;
    if (bCompetingWriter) { bRelinquished = true; ReleaseBudget(TEXT("competing-writer")); }
    if (!Enable.GetValueOnGameThread() || bRelinquished || !CanApply()) { ReleaseBudget(TEXT("inactive-flow")); return; }
    if (!bActive) ApplyBudget();
    // No grass/PCG iteration or full Readiness collection. Optional native snapshot at 0.2 Hz.
    const double Now = FPlatformTime::Seconds();
    if (bActive && Log.GetValueOnGameThread() && Now - LastSnapshotS >= 5.0) { LastSnapshotS = Now; LogSnapshot(TEXT("active")); }
}

void USaskartaGameplayStreamingBudget::OnCVarChanged(IConsoleVariable*)
{
    // Even another writer setting the same value takes ownership. Never reapply in this world.
    // Release on EndFrame, outside the console callback, to avoid recursive CVar callbacks.
    if (!bApplying && bActive) bCompetingWriter = true;
}

void USaskartaGameplayStreamingBudget::ApplyBudget()
{
    using namespace SaskartaGameplayStreaming;
    LeaseWorld = GetWorld();
    TGuardValue<bool> Writing(bApplying, true);
    for (const FCap& Cap : Caps)
    {
        IConsoleVariable* V = IConsoleManager::Get().FindConsoleVariable(Cap.Name);
        if (!V || V->TestFlags(ECVF_ReadOnly)) continue;
        const float Current = V->GetFloat();
        if (!FMath::IsFinite(Current) || Current < 0.f) continue;
        const float Desired = Cap.bZeroIsUnlimited && Current == 0.f ? Cap.Limit : FMath::Min(Current, Cap.Limit);
        if (Desired == Current) continue; // Leave a tighter user cap untouched.
        const uint32 OriginalSetBy = static_cast<uint32>(V->GetFlags()) & ECVF_SetByMask;
        if (OriginalSetBy > static_cast<uint32>(ECVF_SetByTemp)) continue; // Interactive console remains authoritative.
        FOwnedCVar Saved;
        Saved.Name = Cap.Name; Saved.Variable = V; Saved.Original = V->GetString(); Saved.OriginalSetBy = OriginalSetBy;
        IConsoleVariable::FSetContext PreviousContext;
        PreviousContext.TagMode = IConsoleVariable::FSetContext::ETagMode::ReplaceCurrent;
        PreviousContext.MinPriority = ECVF_SetByConstructor;
        Saved.OriginalTag = V->ResolveContext(PreviousContext).Tag;
        // UE 5.8 Temp is a tagged array priority: Unset removes this layer and restores
        // both the prior value and its exact SetBy/tag, without overwriting base history.
        Saved.AppliedSetBy = static_cast<uint32>(ECVF_SetByTemp);
        Saved.ChangedHandle = V->OnChangedDelegate().AddUObject(this, &USaskartaGameplayStreamingBudget::OnCVarChanged);
        V->Set(Desired, ECVF_SetByTemp, OwnerTag);
        Saved.Applied = V->GetString();
        if (!HasTag(V, OwnerTag, Saved.AppliedSetBy) || V->GetFloat() != Desired)
        {
            V->OnChangedDelegate().Remove(Saved.ChangedHandle);
            V->Unset(ECVF_SetByTemp, OwnerTag);
            continue;
        }
        Owned.Add(MoveTemp(Saved));
    }
    bActive = true;
    UE_LOG(LogSaskartaGameplayStreaming, Log, TEXT("Applied interactive Carrier/elder streaming budget: %d owned CVars, world=%s. No quality/FPS/GC changes."), Owned.Num(), *GetWorld()->GetName());
}

void USaskartaGameplayStreamingBudget::ReleaseBudget(const TCHAR* Reason)
{
    using namespace SaskartaGameplayStreaming;
    if (!bActive && Owned.IsEmpty()) return;
    TGuardValue<bool> Writing(bApplying, true);
    for (int32 I = Owned.Num() - 1; I >= 0; --I)
    {
        FOwnedCVar& S = Owned[I];
        IConsoleVariable* V = IConsoleManager::Get().FindConsoleVariable(*S.Name);
        if (V != S.Variable) continue;
        V->OnChangedDelegate().Remove(S.ChangedHandle);
        const bool bStillOwned = HasTag(V, OwnerTag, S.AppliedSetBy) && V->GetString() == S.Applied;
        // If another tagged writer is topmost, removing our hidden history layer leaves
        // that writer's current value/priority intact. No snapshot Set can stomp it.
        const FString Current = V->GetString();
        const uint32 CurrentSetBy = static_cast<uint32>(V->GetFlags()) & ECVF_SetByMask;
        V->Unset(ECVF_SetByTemp, OwnerTag);
        UE_LOG(LogSaskartaGameplayStreaming, Verbose, TEXT("%s release=%s still_owned=%d original=%s/0x%08x applied=%s/0x%08x before=%s/0x%08x after=%s/0x%08x"),
            *S.Name, Reason, bStillOwned, *S.Original, S.OriginalSetBy, *S.Applied, S.AppliedSetBy, *Current, CurrentSetBy,
            *V->GetString(), static_cast<uint32>(V->GetFlags()) & ECVF_SetByMask);
    }
    Owned.Reset(); bActive = false; bCompetingWriter = false;
    if (LeaseWorld.Get() == GetWorld()) LeaseWorld.Reset();
    UE_LOG(LogSaskartaGameplayStreaming, Log, TEXT("Released active streaming budget: %s; relinquished=%d."), Reason, bRelinquished);
}

void USaskartaGameplayStreamingBudget::LogSnapshot(const TCHAR* Reason)
{
    UWorld* World = GetWorld();
    UWorldPartitionSubsystem* WP = World ? World->GetSubsystem<UWorldPartitionSubsystem>() : nullptr;
    UE_LOG(LogSaskartaGameplayStreaming, Log, TEXT("Snapshot reason=%s world=%s active=%d async_packages=%d wp_complete=%d frame=%llu gc_caller=unknown full_purge=unknown"),
        Reason, World ? *World->GetName() : TEXT("none"), bActive, GetNumAsyncPackages(), WP ? WP->IsAllStreamingCompleted() : false, GFrameCounter);
}

void USaskartaGameplayStreamingBudget::OnPreGarbageCollect()
{
    if (bActive && SaskartaGameplayStreaming::Log.GetValueOnGameThread()) LogSnapshot(TEXT("pre-GC"));
}
