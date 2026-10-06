// USaskartaEventRunner. See the header and docs/story/EVENTS.md.

#include "SaskartaEventRunner.h"
#include "SaskartaRadioWaves.h"
#include "GameFramework/Controller.h"
#include "Animation/AnimationAsset.h"
#include "SaskartaAudioMix.h"
#include "SaskartaCollapseStage.h"
#include "SaskartaCarrierAnimInstance.h"
#include "SaskartaDroneSequence.h"
#include "SaskartaFirstLightLogic.h"

#include "SaskartaGameUserSettings.h"
#include "SaskartaLightingDirector.h"
#include "SaskartaPromptLogic.h"
#include "SaskartaRadioStation.h"
#include "SaskartaSaveGame.h"
#include "SaskartaStoryAsset.h"
#include "SaskartaStoryImport.h"
#include "SaskartaStorySettings.h"
#include "SaskartaTetherSubsystem.h"

#include "AssetRegistry/AssetData.h"
#include "AssetRegistry/IAssetRegistry.h"
#include "Camera/PlayerCameraManager.h"
#include "Camera/CameraComponent.h"
#include "Components/AudioComponent.h"
#include "Components/CapsuleComponent.h"
#include "Components/MeshComponent.h"
#include "SceneViewExtension.h"
#include "SaskartaSensorCamera.h"
#include "Components/SkeletalMeshComponent.h"
#include "Components/SplineComponent.h"
#include "Components/WorldPartitionStreamingSourceComponent.h"
#include "DefaultLevelSequenceInstanceData.h"
#include "Engine/AssetManager.h"
#include "Engine/StreamableManager.h"
#include "Engine/Engine.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "GameFramework/Pawn.h"
#include "GameFramework/Character.h"
#include "GameFramework/CharacterMovementComponent.h"
#include "GameFramework/PawnMovementComponent.h"
#include "GameFramework/PlayerController.h"
#include "HAL/IConsoleManager.h"
#include "InputCoreTypes.h"
#include "Kismet/GameplayStatics.h"
#include "LevelSequence.h"
#include "LevelSequenceActor.h"
#include "LevelSequencePlayer.h"
#include "LandscapeProxy.h"
#include "Sound/SoundBase.h"
#include "Sound/SoundMix.h"
#include "Animation/AnimSequence.h"
#include "UObject/UnrealType.h"
#include "WorldPartition/DataLayer/DataLayerInstance.h"
#include "WorldPartition/DataLayer/DataLayerManager.h"
#include "WorldPartition/WorldPartitionRuntimeCell.h"
#include "WorldPartition/WorldPartitionSubsystem.h"

DEFINE_LOG_CATEGORY_STATIC(LogSaskartaEvents, Log, All);

namespace SaskartaEvents
{
    static const FName NamePC(TEXT("PC"));
    static const FName NamePawn(TEXT("Pawn"));
    static const FName NameHuman(TEXT("Human"));
    static const FName NameFlowState(TEXT("FlowState"));
    static const FName NameCarrierPOV(TEXT("CarrierPOV"));
    static const FName NameDroneCam(TEXT("DroneCam"));
    static const FName NameNone(TEXT("None"));
    static const FName NameStartAnimDriver(TEXT("StartAnimDriver"));
    static const FName NameStopAnimDriver(TEXT("StopAnimDriver"));
    static const TCHAR* AudioRoot = TEXT("/Game/SaskartaGaea/Audio");
    static const TCHAR* StoryDuckMixPath = TEXT("/Game/SaskartaGaea/Audio/Classes/SCM_Saskarta_StoryDuck.SCM_Saskarta_StoryDuck");
    static constexpr double RoadResolveIntervalS = 5.0;
    static constexpr double SoundIndexRebuildS = 10.0;
    static constexpr float CineTimeoutPadS = 30.f;
    static constexpr float HumanGroundingRadiusCm = 2000.f;
    static constexpr double HumanGroundingTimeoutS = 30.0;
    static constexpr float CarrierGroundingRadiusCm = 2000.f;
    static constexpr double CarrierGroundingTimeoutS = 30.0;

    static ACharacter* EndingCarrier(UWorld* World)
    {
        UClass* Class = LoadClass<ACharacter>(nullptr,
            TEXT("/Game/SaskartaGaea/Characters/Carrier/BP_Saskarta_Carrier.BP_Saskarta_Carrier_C"));
        return World && Class ? Cast<ACharacter>(UGameplayStatics::GetActorOfClass(World, Class)) : nullptr;
    }

    static UClass* TravellerClass()
    {
        return LoadClass<ACharacter>(nullptr,
            TEXT("/Game/SaskartaGaea/Characters/Traveller/BP_Saskarta_Traveller.BP_Saskarta_Traveller_C"));
    }

    static TAutoConsoleVariable<int32> CVarAllowSkipAll(
        TEXT("Saskarta.Cine.AllowSkipAll"), 0,
        TEXT("1 makes every cinematic skippable (development)."), ECVF_Default);

    static bool SubtitlesEnabled()
    {
        const USaskartaGameUserSettings* S = USaskartaGameUserSettings::GetSaskartaSettings();
        return !S || S->bSubtitles;
    }

    static float Smoothstep(float X)
    {
        X = FMath::Clamp(X, 0.f, 1.f);
        return X * X * (3.f - 2.f * X);
    }

    static bool IsLineAction(ESaskartaActionType T)
    {
        return T == ESaskartaActionType::PlayRadioLine || T == ESaskartaActionType::PlayCarrierLine;
    }

    static USoundMix* StoryDuckMix()
    {
        static TWeakObjectPtr<USoundMix> Cached;
        static bool bTried = false;
        if (!bTried)
        {
            bTried = true;
            Cached = LoadObject<USoundMix>(nullptr, StoryDuckMixPath, nullptr, LOAD_NoWarn | LOAD_Quiet);
        }
        return Cached.Get();
    }
}

// SetupViewPoint is after PlayerCameraManager's pending-target blend and before
// LocalPlayer builds the view/culling matrices. A CameraModifier is too early:
// UE 5.8 blends its two already-modified endpoints afterward.
class FSaskartaCinematicViewGuard final : public FSceneViewExtensionBase
{
public:
    FSaskartaCinematicViewGuard(const FAutoRegister& AutoRegister, USaskartaEventRunner* InRunner)
        : FSceneViewExtensionBase(AutoRegister), Runner(InRunner) {}
    virtual void SetupViewFamily(FSceneViewFamily&) override {}
    virtual void SetupView(FSceneViewFamily&, FSceneView&) override {}
    virtual void BeginRenderViewFamily(FSceneViewFamily&) override {}
    virtual void SetupViewPoint(APlayerController* Player, FMinimalViewInfo& View) override
    {
        if (USaskartaEventRunner* R = Runner.Get()) R->ConstrainCinematicView(Player, View);
    }
private:
    TWeakObjectPtr<USaskartaEventRunner> Runner;
};

namespace SaskartaCineClearance
{
    // Slab intersection against current render bounds. No authored position guesses
    // and no dependency on the carrier's often camera-ignoring physics profile.
    static bool EntryFace(const FBox& Box, const FVector& From, const FVector& To,
        int32& Axis, double& Face)
    {
        double Enter = 0.0, Leave = 1.0;
        Axis = INDEX_NONE;
        const FVector Delta = To - From;
        for (int32 I = 0; I < 3; ++I)
        {
            if (FMath::Abs(Delta[I]) < UE_SMALL_NUMBER)
            {
                if (From[I] < Box.Min[I] || From[I] > Box.Max[I]) return false;
                continue;
            }
            const bool bPositive = Delta[I] > 0.0;
            const double NearFace = bPositive ? Box.Min[I] : Box.Max[I];
            const double A = (NearFace - From[I]) / Delta[I];
            const double B = ((bPositive ? Box.Max[I] : Box.Min[I]) - From[I]) / Delta[I];
            if (A >= Enter) { Enter = A; Axis = I; Face = NearFace; }
            Leave = FMath::Min(Leave, B);
            if (Enter > Leave) return false;
        }
        return Leave >= 0.0 && Enter <= 1.0;
    }

    static FVector OutsidePath(const FBox& Box, const FVector& From, const FVector& To)
    {
        int32 Axis = INDEX_NONE;
        double Face = 0.0;
        if (!Box.IsInsideOrOn(From) && EntryFace(Box, From, To, Axis, Face) && Axis != INDEX_NONE)
        {
            // Slide on the entry face: both ends stay in the same exterior
            // half-space, so neither the keyed segment nor its interpolation crosses the hull.
            FVector Safe = To;
            Safe[Axis] = Face + (Face == Box.Min[Axis] ? -0.1 : 0.1);
            return Safe;
        }
        if (Box.IsInsideOrOn(To))
        {
            // No prior exterior sample (first frame / a cut): nearest measured face.
            double Best = TNumericLimits<double>::Max();
            for (int32 I = 0; I < 3; ++I)
            {
                for (const double Candidate : { Box.Min[I], Box.Max[I] })
                {
                    const double Distance = FMath::Abs(To[I] - Candidate);
                    if (Distance < Best) { Best = Distance; Axis = I; Face = Candidate; }
                }
            }
            FVector Safe = To;
            Safe[Axis] = Face + (Face == Box.Min[Axis] ? -0.1 : 0.1);
            return Safe;
        }
        return To;
    }
}

// ============================================================================ access

USaskartaEventRunner* USaskartaEventRunner::GetEventRunner(const UObject* WorldContextObject)
{
    const UWorld* World = GEngine ? GEngine->GetWorldFromContextObject(WorldContextObject, EGetWorldErrorMode::ReturnNull) : nullptr;
    return World ? World->GetSubsystem<USaskartaEventRunner>() : nullptr;
}

bool USaskartaEventRunner::DoesSupportWorldType(const EWorldType::Type WorldType) const
{
    return WorldType == EWorldType::Game || WorldType == EWorldType::PIE;
}

double USaskartaEventRunner::Now() const
{
    const UWorld* World = GetWorld();
    return World ? World->GetTimeSeconds() : 0.0;
}

APlayerController* USaskartaEventRunner::GetPC() const
{
    const UWorld* World = GetWorld();
    return World ? World->GetFirstPlayerController() : nullptr;
}

APawn* USaskartaEventRunner::GetPawn() const
{
    const APlayerController* PC = GetPC();
    return PC ? PC->GetPawn() : nullptr;
}

AActor* USaskartaEventRunner::ResolveTarget(FName Tag) const
{
    if (Tag.IsNone() || Tag == SaskartaEvents::NamePawn)
    {
        return GetPawn();
    }
    if (Tag == SaskartaEvents::NamePC)
    {
        return GetPC();
    }
    UWorld* World = GetWorld();
    if (!World)
    {
        return nullptr;
    }
    for (TActorIterator<AActor> It(World); It; ++It)
    {
        if (It->ActorHasTag(Tag))
        {
            return *It;
        }
    }
    return nullptr;
}

FName USaskartaEventRunner::GetFlowState() const
{
    const APlayerController* PC = GetPC();
    if (!PC)
    {
        return NAME_None;
    }
    const FNameProperty* Prop = FindFProperty<FNameProperty>(PC->GetClass(), SaskartaEvents::NameFlowState);
    return Prop ? Prop->GetPropertyValue_InContainer(PC) : NAME_None;
}

void USaskartaEventRunner::SetFlowStateByReflection(FName State)
{
    APlayerController* PC = GetPC();
    if (!PC)
    {
        return;
    }
    if (FNameProperty* Prop = FindFProperty<FNameProperty>(PC->GetClass(), SaskartaEvents::NameFlowState))
    {
        Prop->SetPropertyValue_InContainer(PC, State);
        UE_LOG(LogSaskartaEvents, Log, TEXT("FlowState <- %s"), *State.ToString());
    }
    else
    {
        UE_LOG(LogSaskartaEvents, Warning, TEXT("SetFlowState %s: the PC has no FlowState Name variable"), *State.ToString());
    }
    CallHook(PC, TEXT("OnFlowStateSetByRunner"), {}, {});
    // One title-music component follows the walk and ending without resetting
    // its recording cursor at every narrative state transition.
    if (UWorld* World = GetWorld())
    {
        if (USaskartaRadioStation* Station = World->GetSubsystem<USaskartaRadioStation>())
            Station->SetEndingMusicFlow(State);
    }
}

bool USaskartaEventRunner::CallHook(AActor* Target, FName Function, const TArray<FName>& NameArgs, const TArray<float>& FloatArgs) const
{
    if (!Target)
    {
        UE_LOG(LogSaskartaEvents, Warning, TEXT("CallHook %s: no target"), *Function.ToString());
        return false;
    }
    UFunction* Func = Target->FindFunction(Function);
    if (!Func)
    {
        // 2026-10-05: native hooks for the ending. PlayAnim_<AnimAsset> plays a Traveller animation once on the
        // target's skeletal mesh; FaceTag (NameArgs[0] = actor tag) turns the target (and its controller) toward it.
        const FString FnStr = Function.ToString();
        if (FnStr.StartsWith(TEXT("PlayAnim_")))
        {
            const FString AnimName = FnStr.RightChop(9);
            const FString Path = FString::Printf(TEXT("/Game/SaskartaGaea/Characters/Traveller/Anims/%s.%s"), *AnimName, *AnimName);
            UAnimationAsset* Anim = LoadObject<UAnimationAsset>(nullptr, *Path, nullptr, LOAD_NoWarn | LOAD_Quiet);
            USkeletalMeshComponent* Mesh = Target->FindComponentByClass<USkeletalMeshComponent>();
            if (const ACharacter* Ch = Cast<ACharacter>(Target)) Mesh = Ch->GetMesh();
            if (Anim && Mesh)
            {
                Mesh->PlayAnimation(Anim, false);
                UE_LOG(LogSaskartaEvents, Log, TEXT("CallHook native PlayAnim %s on %s"), *AnimName, *Target->GetName());
                return true;
            }
            UE_LOG(LogSaskartaEvents, Warning, TEXT("CallHook native PlayAnim %s: missing anim or mesh"), *AnimName);
            return false;
        }
        if (FnStr == TEXT("FaceTag"))
        {
            const FName Tag = NameArgs.Num() > 0 ? NameArgs[0] : FName(TEXT("Saskarta.Transmitter"));
            for (TActorIterator<AActor> It(Target->GetWorld()); It; ++It)
            {
                if (It->ActorHasTag(Tag))
                {
                    FVector D = It->GetActorLocation() - Target->GetActorLocation(); D.Z = 0.f;
                    if (!D.IsNearlyZero())
                    {
                        const FRotator R = D.Rotation();
                        Target->SetActorRotation(FRotator(0.f, R.Yaw, 0.f));
                        if (APawn* P = Cast<APawn>(Target)) if (AController* C = P->GetController()) C->SetControlRotation(FRotator(-12.f, R.Yaw, 0.f));
                    }
                    return true;
                }
            }
            return false;
        }
        if (FnStr.StartsWith(TEXT("PrefetchTag_")))
        {
            // PrefetchTag_<ActorTag>: switch on the World Partition streaming source of the tagged camera(s) so the
            // cells around a far slideshow view are loaded before the cut.
            const FName PTag(*FnStr.RightChop(12));
            int32 Hits = 0;
            for (TActorIterator<AActor> It(Target->GetWorld()); It; ++It)
            {
                if (!It->ActorHasTag(PTag)) continue;
                if (UWorldPartitionStreamingSourceComponent* Src = It->FindComponentByClass<UWorldPartitionStreamingSourceComponent>()) { Src->EnableStreamingSource(); ++Hits; }
            }
            UE_LOG(LogSaskartaEvents, Log, TEXT("CallHook native prefetch %s: %d source(s)"), *PTag.ToString(), Hits);
            return Hits > 0;
        }
        if (FnStr.StartsWith(TEXT("CutToTag_")))
        {
            // CutToTag_<ActorTag>[__<blend s x10>]: blend the player's view to a placed camera (the slideshow, the antenna shot).
            FString TagStr = FnStr.RightChop(9); float Blend = 1.5f;
            int32 Sep = INDEX_NONE;
            if (TagStr.FindLastChar(TEXT('_'), Sep) && Sep > 0 && TagStr.Mid(Sep + 1).IsNumeric() && TagStr[Sep - 1] == TEXT('_'))
            {
                Blend = FCString::Atof(*TagStr.Mid(Sep + 1)) / 10.f; TagStr = TagStr.Left(Sep - 1);
            }
            APlayerController* PCx = Cast<APlayerController>(Target);
            if (!PCx) if (APawn* Pw = Cast<APawn>(Target)) PCx = Cast<APlayerController>(Pw->GetController());
            if (!PCx) PCx = Target->GetWorld()->GetFirstPlayerController();
            for (TActorIterator<AActor> It(Target->GetWorld()); It && PCx; ++It)
            {
                if (It->ActorHasTag(FName(*TagStr)))
                {
                    // Slideshow: keep this view and the next one streamed in, release the others.
                    if (TagStr.StartsWith(TEXT("Saskarta.Slide.")))
                    {
                        const int32 N = FCString::Atoi(*TagStr.RightChop(15));
                        for (TActorIterator<AActor> S(Target->GetWorld()); S; ++S)
                        {
                            UWorldPartitionStreamingSourceComponent* Src = S->FindComponentByClass<UWorldPartitionStreamingSourceComponent>();
                            if (!Src) continue;
                            for (int32 K = 1; K <= 9; ++K)
                            {
                                if (!S->ActorHasTag(FName(*FString::Printf(TEXT("Saskarta.Slide.%d"), K)))) continue;
                                if (K == N || K == N + 1) Src->EnableStreamingSource(); else Src->DisableStreamingSource();
                            }
                        }
                    }
                    PCx->SetViewTargetWithBlend(*It, Blend, VTBlend_EaseInOut, 2.f);
                    UE_LOG(LogSaskartaEvents, Log, TEXT("CallHook native cut to %s (%.1f s)"), *TagStr, Blend);
                    return true;
                }
            }
            UE_LOG(LogSaskartaEvents, Warning, TEXT("CallHook native cut: no actor tagged %s"), *TagStr);
            return false;
        }
        if (FnStr == TEXT("RadioWaves"))
        {
            for (TActorIterator<AActor> It(Target->GetWorld()); It; ++It)
            {
                if (It->ActorHasTag(FName(TEXT("Saskarta.Antenna"))))
                {
                    FActorSpawnParameters SP; SP.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
                    Target->GetWorld()->SpawnActor<ASaskartaRadioWaves>(ASaskartaRadioWaves::StaticClass(), It->GetActorLocation(), FRotator::ZeroRotator, SP);
                    UE_LOG(LogSaskartaEvents, Log, TEXT("CallHook native radio waves at %s"), *It->GetName());
                    return true;
                }
            }
            return false;
        }
        UE_LOG(LogSaskartaEvents, Log, TEXT("CallHook %s on %s: no such function (skipped)"), *Function.ToString(), *Target->GetName());
        return false;
    }
    uint8* Params = nullptr;
    if (Func->ParmsSize > 0)
    {
        Params = static_cast<uint8*>(FMemory_Alloca(Func->ParmsSize));
        FMemory::Memzero(Params, Func->ParmsSize);
        int32 NameIndex = 0;
        int32 FloatIndex = 0;
        for (TFieldIterator<FProperty> It(Func); It && It->HasAnyPropertyFlags(CPF_Parm); ++It)
        {
            FProperty* P = *It;
            P->InitializeValue_InContainer(Params);
            if (P->HasAnyPropertyFlags(CPF_ReturnParm) || (P->HasAnyPropertyFlags(CPF_OutParm) && !P->HasAnyPropertyFlags(CPF_ConstParm)))
            {
                continue;
            }
            if (FNameProperty* NP = CastField<FNameProperty>(P))
            {
                if (NameArgs.IsValidIndex(NameIndex))
                {
                    NP->SetPropertyValue_InContainer(Params, NameArgs[NameIndex]);
                }
                ++NameIndex;
            }
            else if (FFloatProperty* FP = CastField<FFloatProperty>(P))
            {
                if (FloatArgs.IsValidIndex(FloatIndex))
                {
                    FP->SetPropertyValue_InContainer(Params, FloatArgs[FloatIndex]);
                }
                ++FloatIndex;
            }
            else if (FDoubleProperty* DP = CastField<FDoubleProperty>(P))
            {
                if (FloatArgs.IsValidIndex(FloatIndex))
                {
                    DP->SetPropertyValue_InContainer(Params, FloatArgs[FloatIndex]);
                }
                ++FloatIndex;
            }
        }
    }
    UE_LOG(LogSaskartaEvents, Log, TEXT("CallHook %s.%s"), *Target->GetName(), *Function.ToString());
    Target->ProcessEvent(Func, Params);
    if (Params)
    {
        for (TFieldIterator<FProperty> It(Func); It && It->HasAnyPropertyFlags(CPF_Parm); ++It)
        {
            It->DestroyValue_InContainer(Params);
        }
    }
    return true;
}

void USaskartaEventRunner::LockInput(bool bMove, bool bLook)
{
    APlayerController* PC = GetPC();
    if (!PC)
    {
        return;
    }
    if (bMove)
    {
        PC->SetIgnoreMoveInput(true);
        ++MoveLocks;
    }
    if (bLook)
    {
        PC->SetIgnoreLookInput(true);
        ++LookLocks;
    }
}

void USaskartaEventRunner::UnlockInput()
{
    // Releases every lock this runner applied (the controller's locks stack).
    APlayerController* PC = GetPC();
    for (; MoveLocks > 0; --MoveLocks)
    {
        if (PC) PC->SetIgnoreMoveInput(false);
    }
    for (; LookLocks > 0; --LookLocks)
    {
        if (PC) PC->SetIgnoreLookInput(false);
    }
}

// ============================================================================ lifecycle

void USaskartaEventRunner::Initialize(FSubsystemCollectionBase& Collection)
{
    Super::Initialize(Collection);
    TearDownHandle = FWorldDelegates::OnWorldBeginTearDown.AddUObject(this, &USaskartaEventRunner::HandleWorldTearDown);
    // Every path that hides a prompt broadcasts OnPromptHide; the runner's own on-top line goes with it.
    OnPromptHide.AddDynamic(this, &USaskartaEventRunner::HandlePromptHidden);
}

void USaskartaEventRunner::HandleWorldTearDown(UWorld* World)
{
    if (World && World == GetWorld())
    {
        // PIE end or a level change: the controller still exists here, so every lock is released cleanly.
        if (IsHoldingInput() || IsCinematicActive())
        {
            UE_LOG(LogSaskartaEvents, Log, TEXT("world teardown: releasing input (cinematic %s)"), *ActiveCineId.ToString());
        }
        StopAll();
    }
}

void USaskartaEventRunner::OnWorldBeginPlay(UWorld& InWorld)
{
    Super::OnWorldBeginPlay(InWorld);
    if (!Story)
    {
        SetStory(USaskartaStoryImport::LoadStoryOrImportTransient(this));
    }
    LoadProfile();
    FTimerManager& TM = InWorld.GetTimerManager();
    TM.SetTimer(PollRoadTimer, this, &USaskartaEventRunner::PollRoad, FSaskartaEventLogic::RoadPollS, true);
    TM.SetTimer(StepTimer, this, &USaskartaEventRunner::Step, FSaskartaEventLogic::StepS, true);
    UE_LOG(LogSaskartaEvents, Log, TEXT("Event runner up: %d beats, %d lines, %d cinematics"),
        Story ? Story->Beats.Num() : 0, Story ? Story->Lines.Num() : 0, Story ? Story->Cinematics.Num() : 0);
}

void USaskartaEventRunner::Deinitialize()
{
    FWorldDelegates::OnWorldBeginTearDown.Remove(TearDownHandle);
    TearDownHandle.Reset();
    StopAll();
    RemovePromptOverlay();
    if (UWorld* World = GetWorld())
    {
        FTimerManager& TM = World->GetTimerManager();
        TM.ClearTimer(PollRoadTimer);
        TM.ClearTimer(StepTimer);
        TM.ClearTimer(PromptTimer);
        TM.ClearTimer(SkipTimer);
        TM.ClearTimer(GlanceTimer);
    }
    CinematicViewGuard.Reset();
    Super::Deinitialize();
}

void USaskartaEventRunner::SetStory(USaskartaStoryAsset* InStory)
{
    Story = InStory;
    EnabledTags.Reset();
    if (Story)
    {
        EnabledTags.Append(Story->EnabledTags);
    }
}

void USaskartaEventRunner::SetEnabledTags(const TArray<FName>& Tags)
{
    EnabledTags.Reset();
    EnabledTags.Append(Tags);
    UE_LOG(LogSaskartaEvents, Log, TEXT("Enabled tags: %d"), EnabledTags.Num());
}

// ============================================================================ triggers

bool USaskartaEventRunner::ResolveRoad()
{
    if (RoadSpline.IsValid())
    {
        return true;
    }
    const double T = Now();
    if (T - LastRoadResolveS < SaskartaEvents::RoadResolveIntervalS)
    {
        return false;
    }
    LastRoadResolveS = T;
    UWorld* World = GetWorld();
    if (!World)
    {
        return false;
    }
    // The tether's method: the BP_Saskarta_Road actor's spline (or any actor tagged Saskarta.Road).
    static const FName RoadTag(TEXT("Saskarta.Road"));
    for (TActorIterator<AActor> It(World); It; ++It)
    {
        AActor* A = *It;
        if (A->ActorHasTag(RoadTag) || A->GetClass()->GetName().StartsWith(TEXT("BP_Saskarta_Road")))
        {
            if (USplineComponent* S = A->FindComponentByClass<USplineComponent>())
            {
                RoadSpline = S;
                UE_LOG(LogSaskartaEvents, Log, TEXT("RoadSpline: %s (%.0f m)"), *A->GetName(), S->GetSplineLength() / 100.f);
                return true;
            }
        }
    }
    if (!bWarnedNoRoad)
    {
        bWarnedNoRoad = true;
        UE_LOG(LogSaskartaEvents, Log, TEXT("No BP_Saskarta_Road spline in this world yet; road beats wait."));
    }
    return false;
}

USplineComponent* USaskartaEventRunner::GetRoadSpline() const
{
    return RoadSpline.Get();
}

void USaskartaEventRunner::PollRoad()
{
    if (bHumanGroundingActive || bCarrierGroundingActive) return;
    APawn* Pawn = GetPawn();
    if (!Story || !Pawn || !ResolveRoad())
    {
        return;
    }
    const bool bHuman = GetFlowState() == SaskartaEvents::NameHuman;
    // Carrier detours hold road progress. The untethered elder must still reach
    // the authored road-pass rest/lookback offers while walking off that route.
    if (const USaskartaTetherSubsystem* Tether = GetWorld() ? GetWorld()->GetSubsystem<USaskartaTetherSubsystem>() : nullptr)
    {
        if (!bHuman && Tether->IsDetour(Pawn->GetActorLocation()))
        {
            SpeedMps = Pawn->GetVelocity().Size() / 100.f;
            return;
        }
    }
    USplineComponent* Spline = RoadSpline.Get();
    const float Key = Spline->FindInputKeyClosestToWorldLocation(Pawn->GetActorLocation());
    const float UeM = Spline->GetDistanceAlongSplineAtSplineInputKey(Key) / 100.f;
    CurrentUeM = UeM;
    CurrentRoadM = FSaskartaEventLogic::RoadMFromUeM(Story->RoadMToUeM, UeM);
    SpeedMps = Pawn->GetVelocity().Size() / 100.f;

    if (HighWaterUeM == TNumericLimits<float>::Max())
    {
        // First sample: start the mark here without firing what lies behind the spawn.
        HighWaterUeM = UeM;
    }
    else
    {
        TArray<FName> Hits;
        FSaskartaEventLogic::CollectRoadPasses(Story->Beats, HighWaterUeM, UeM, bHuman, FiredBeats, EnabledTags, Hits);
        HighWaterUeM = FSaskartaEventLogic::UpdateHighWater(HighWaterUeM, UeM);
        for (const FName& Id : Hits)
        {
            if (const FSaskartaBeatDef* B = Story->FindBeat(Id))
            {
                EnqueueBeat(*B, false);
            }
        }
    }

    if (Story->bDriveLightingRoadProgress && CurrentRoadM >= 0.f)
    {
        if (USaskartaLightingDirector* Dir = USaskartaLightingDirector::GetLightingDirector(this))
        {
            Dir->SetRoadProgress(CurrentRoadM);
        }
    }
    PrefetchAhead();
}

void USaskartaEventRunner::PrefetchAhead()
{
    if (!Story)
    {
        return;
    }
    // Road beats within 400 m ahead (at 5 m/s that is 80 s of warning), and every non-road beat
    // (flow / volume / chained) once: they are few and can fire at any moment.
    constexpr float AheadM = 400.f;
    for (const FSaskartaBeatDef& B : Story->Beats)
    {
        if (PrefetchedBeats.Contains(B.Id) || FiredBeats.Contains(B.Id))
        {
            continue;
        }
        const bool bRoad = B.Trigger.RoadM >= 0.f;
        if (!bRoad || (CurrentRoadM >= 0.f && B.Trigger.RoadM >= CurrentRoadM - 20.f && B.Trigger.RoadM <= CurrentRoadM + AheadM))
        {
            PrefetchBeat(B);
        }
    }
}

void USaskartaEventRunner::PrefetchBeat(const FSaskartaBeatDef& Beat)
{
    PrefetchedBeats.Add(Beat.Id);
    TArray<FSoftObjectPath> Paths;
    auto AddLine = [this, &Paths](FName Id)
    {
        const FSaskartaLineDef* L = Story->FindLine(Id);
        const FSoftObjectPath P = SoundPathFor(Id, L ? L->Sound : TSoftObjectPtr<USoundBase>());
        if (!P.IsNull() && !P.ResolveObject())
        {
            Paths.AddUnique(P);
        }
    };
    auto AddAction = [this, &Paths, &AddLine](const FSaskartaEventAction& A)
    {
        switch (A.Type)
        {
        case ESaskartaActionType::PlayRadioLine:
        case ESaskartaActionType::PlayCarrierLine:
        case ESaskartaActionType::PlaySfx:
            AddLine(A.Id);
            break;
        case ESaskartaActionType::PlayCinematic:
            if (const FSaskartaCinematicDef* C = Story->FindCinematic(A.Id))
            {
                if (!C->Sequence.IsNull() && !C->Sequence.Get())
                {
                    Paths.AddUnique(C->Sequence.ToSoftObjectPath());
                }
                for (const FSaskartaEventAction& Cue : C->Cues)
                {
                    if (Cue.Type == ESaskartaActionType::PlayRadioLine || Cue.Type == ESaskartaActionType::PlayCarrierLine || Cue.Type == ESaskartaActionType::PlaySfx)
                    {
                        AddLine(Cue.Id);
                    }
                }
            }
            break;
        default:
            break;
        }
    };
    for (const FSaskartaEventAction& A : Beat.Actions)
    {
        AddAction(A);
    }
    if (Paths.Num() > 0 && UAssetManager::IsInitialized())
    {
        PrefetchHandles.Add(UAssetManager::GetStreamableManager().RequestAsyncLoad(Paths, FStreamableDelegate(), FStreamableManager::DefaultAsyncLoadPriority));
        UE_LOG(LogSaskartaEvents, Verbose, TEXT("prefetch %s: %d assets"), *Beat.Id.ToString(), Paths.Num());
    }
}

FSoftObjectPath USaskartaEventRunner::SoundPathFor(FName Id, const TSoftObjectPtr<USoundBase>& Preferred)
{
    IAssetRegistry* AR = IAssetRegistry::Get();
    if (!Preferred.IsNull() && (Preferred.Get() || (AR && AR->GetAssetByObjectPath(Preferred.ToSoftObjectPath()).IsValid())))
    {
        return Preferred.ToSoftObjectPath();
    }
    if (!bSoundIndexBuilt && AR)
    {
        bSoundIndexBuilt = true;
        SoundIndex.Reset();
        TArray<FAssetData> Assets;
        AR->GetAssetsByPath(FName(SaskartaEvents::AudioRoot), Assets, /*bRecursive*/ true);
        for (const FAssetData& D : Assets)
        {
            SoundIndex.Add(D.AssetName, D.GetSoftObjectPath());
        }
    }
    const FSoftObjectPath* Found = SoundIndex.Find(Id);
    return Found ? *Found : FSoftObjectPath();
}

float USaskartaEventRunner::GetSecondsToNextBeat() const
{
    if (!Story || CurrentRoadM < 0.f)
    {
        return 1.0e6f;
    }
    const bool bHuman = GetFlowState() == SaskartaEvents::NameHuman;
    const float Mark = HighWaterUeM == TNumericLimits<float>::Max() ? CurrentUeM : HighWaterUeM;
    const FSaskartaBeatDef* Next = FSaskartaEventLogic::NextRoadBeat(Story->Beats, Mark, bHuman, FiredBeats, EnabledTags);
    if (!Next)
    {
        return 1.0e6f;
    }
    const float NextRoadM = Next->Trigger.RoadM >= 0.f ? Next->Trigger.RoadM
        : FSaskartaEventLogic::RoadMFromUeM(Story->RoadMToUeM, Next->Trigger.UeDistanceM);
    return FMath::Max(0.f, NextRoadM - CurrentRoadM) / FMath::Max(SpeedMps, 0.5f);
}

void USaskartaEventRunner::ReportFlow(FName FlowEvent)
{
    UE_LOG(LogSaskartaEvents, Log, TEXT("ReportFlow %s"), *FlowEvent.ToString());
    if (!Story)
    {
        return;
    }
    // A beat cut by a tether breach comes back once the reboot's vision is online (EVENTS.md section 7).
    if (FlowEvent == FName(TEXT("RebootVisionOnline")) && !InterruptedBeatId.IsNone())
    {
        const FName Id = InterruptedBeatId;
        InterruptedBeatId = NAME_None;
        FireBeat(Id, true);
    }
    for (const FSaskartaBeatDef& B : Story->Beats)
    {
        if (B.Trigger.Type == ESaskartaTriggerType::Flow && B.Trigger.FlowEvent == FlowEvent)
        {
            EnqueueBeat(B, false);
        }
    }
}

void USaskartaEventRunner::NotifyVolume(FName TriggerId, APawn* Pawn)
{
    if (!Story || TriggerId.IsNone())
    {
        return;
    }
    for (const FSaskartaBeatDef& B : Story->Beats)
    {
        if (B.Trigger.Type == ESaskartaTriggerType::Volume && B.Trigger.VolumeId == TriggerId)
        {
            EnqueueBeat(B, false);
        }
    }
}

bool USaskartaEventRunner::FireBeat(FName BeatId, bool bForce)
{
    const FSaskartaBeatDef* B = Story ? Story->FindBeat(BeatId) : nullptr;
    if (!B)
    {
        UE_LOG(LogSaskartaEvents, Warning, TEXT("FireBeat %s: no such beat"), *BeatId.ToString());
        return false;
    }
    EnqueueBeat(*B, bForce);
    return true;
}

// ============================================================================ queue

void USaskartaEventRunner::EnqueueBeat(const FSaskartaBeatDef& Beat, bool bForce)
{
    const double T = Now();
    if (!bForce)
    {
        if (Beat.Trigger.bOneShot && FiredBeats.Contains(Beat.Id))
        {
            return;
        }
        if (!FSaskartaEventLogic::TagsAllow(Beat.RequiresTags, Beat.ExcludesTags, FSaskartaEventLogic::DeriveTags(EnabledTags)))
        {
            return;
        }
        if (!Beat.Trigger.RequiredFlowState.IsNone() && GetFlowState() != Beat.Trigger.RequiredFlowState)
        {
            UE_LOG(LogSaskartaEvents, Log, TEXT("%s: gated (FlowState %s, needs %s)"), *Beat.Id.ToString(),
                *GetFlowState().ToString(), *Beat.Trigger.RequiredFlowState.ToString());
            return;
        }
        const double* Last = LastFiredS.Find(Beat.Id);
        if (!Beat.Trigger.bOneShot && !FSaskartaEventLogic::CooldownAllows(Beat.Trigger, Last ? *Last : -1.0, T))
        {
            return;
        }
        // A repeatable beat already waiting is not queued twice.
        if (!Beat.Trigger.bOneShot && Queue.ContainsByPredicate([&Beat](const FSaskartaQueuedBeat& Q) { return Q.BeatId == Beat.Id; }))
        {
            return;
        }
    }
    if (Beat.Trigger.bOneShot && !Beat.bSystem)
    {
        FiredBeats.Add(Beat.Id);
    }
    LastFiredS.Add(Beat.Id, T);

    // HUD queries and wreck lines hold no Voice and wait for no beat: they go to HudLine's own lane.
    if (FSaskartaHudLane::IsHudOnlyBeat(Beat))
    {
        for (const FSaskartaEventAction& A : Beat.Actions)
        {
            RunHudAction(A, false);
        }
        return;
    }

    FSaskartaQueuedBeat Q;
    Q.BeatId = Beat.Id;
    Q.Priority = Beat.Priority;
    Q.EnqueueTimeS = T;
    Q.MaxLatenessS = FSaskartaEventLogic::EffectiveMaxLateness(Beat);
    Q.Seq = QueueSeq++;
    Queue.Add(Q);
    PrefetchBeatSounds(Beat);
    UE_LOG(LogSaskartaEvents, Log, TEXT("queued %s (priority %d, road %.0f m)"), *Beat.Id.ToString(), static_cast<int32>(Beat.Priority), CurrentRoadM);

    if (bHasRunning && FSaskartaEventLogic::CanPreempt(Beat.Priority, RunningPriority, IsCinematicActive()))
    {
        UE_LOG(LogSaskartaEvents, Log, TEXT("%s preempts %s"), *Beat.Id.ToString(), *RunningBeatId.ToString());
        AbortRunningBeat(Beat.Id == FName(TEXT("W02_REBOOT_ONLINE")) ? false : true);
    }
    StartNextBeat();
}

void USaskartaEventRunner::StartNextBeat()
{
    if (bHumanGroundingActive || bCarrierGroundingActive || bHasRunning || !Story || IsCinematicActive())
    {
        return;
    }
    const int32 Index = FSaskartaEventLogic::PickNextIndex(Queue);
    if (Index == INDEX_NONE)
    {
        return;
    }
    const FSaskartaQueuedBeat Q = Queue[Index];
    Queue.RemoveAt(Index);
    bHasRunning = true;
    RunningBeatId = Q.BeatId;
    RunningPriority = Q.Priority;
    RunningActionIndex = 0;
    bRunningDelayDone = false;
    RunningWait = ESaskartaRunWait::None;
    UE_LOG(LogSaskartaEvents, Log, TEXT("start %s (waited %.1f s)"), *Q.BeatId.ToString(), Now() - Q.EnqueueTimeS);
    OnBeatStarted.Broadcast(Q.BeatId);
    RunActions();
}

void USaskartaEventRunner::FinishBeat()
{
    const FName Id = RunningBeatId;
    bHasRunning = false;
    RunningBeatId = NAME_None;
    RunningWait = ESaskartaRunWait::None;
    UE_LOG(LogSaskartaEvents, Log, TEXT("end %s"), *Id.ToString());
    OnBeatFinished.Broadcast(Id);
}

void USaskartaEventRunner::AbortRunningBeat(bool bRequeueOnReboot)
{
    if (!bHasRunning)
    {
        return;
    }
    // Critical preemption: fade the line over 0.3 s, stop a glance and a prompt.
    if (VoiceComp && VoiceComp->IsPlaying())
    {
        VoiceComp->FadeOut(FSaskartaEventLogic::CriticalFadeS, 0.f);
    }
    LineEndS = -1.0;
    VoiceBusyUntilS = Now() + FSaskartaEventLogic::CriticalFadeS;
    HideStorySubtitle();
    EndGlance();
    if (bPromptActive && !bPromptFromCue)
    {
        bPromptActive = false;
        OnPromptHide.Broadcast();
    }
    if (bRequeueOnReboot)
    {
        InterruptedBeatId = RunningBeatId;
    }
    // A SetInputLock of the aborted beat must not outlive it (a cinematic keeps its lock until it hands back).
    if (!IsCinematicActive())
    {
        UnlockInput();
    }
    UE_LOG(LogSaskartaEvents, Log, TEXT("aborted %s"), *RunningBeatId.ToString());
    bHasRunning = false;
    RunningBeatId = NAME_None;
    RunningWait = ESaskartaRunWait::None;
}

void USaskartaEventRunner::Step()
{
    if (bHumanGroundingActive || bCarrierGroundingActive) return;
    const double T = Now();
    TArray<FSaskartaQueuedBeat> Dropped;
    FSaskartaEventLogic::DropLate(Queue, T, &Dropped);
    for (const FSaskartaQueuedBeat& D : Dropped)
    {
        UE_LOG(LogSaskartaEvents, Log, TEXT("dropped %s (late %.1f s)"), *D.BeatId.ToString(), T - D.EnqueueTimeS);
    }
    UpdateVoiceBusy();
    if (CinePhase != ESaskartaCinePhase::None)
    {
        CinematicStep();
    }
    if (!bHasRunning)
    {
        StartNextBeat();
    }
    else
    {
        RunActions();
    }
}

void USaskartaEventRunner::RunActions()
{
    int32 Guard = 0;
    while (bHasRunning && ++Guard < 64)
    {
        const FSaskartaBeatDef* Beat = Story ? Story->FindBeat(RunningBeatId) : nullptr;
        if (!Beat)
        {
            FinishBeat();
            return;
        }
        const double T = Now();
        switch (RunningWait)
        {
        case ESaskartaRunWait::Time:      if (T < RunningBlockedUntilS) return; break;
        case ESaskartaRunWait::Voice:     if (T < VoiceBusyUntilS) return; break;
        case ESaskartaRunWait::Cinematic: if (IsCinematicActive()) return; break;
        case ESaskartaRunWait::Prompt:    if (bPromptActive) return; break;
        default: break;
        }
        RunningWait = ESaskartaRunWait::None;

        if (!Beat->Actions.IsValidIndex(RunningActionIndex))
        {
            FinishBeat();
            return;
        }
        const FSaskartaEventAction& A = Beat->Actions[RunningActionIndex];
        const bool bAllowed = FSaskartaEventLogic::TagsAllow(A.RequiresTags, A.ExcludesTags, FSaskartaEventLogic::DeriveTags(EnabledTags))
            && !(A.bFirstPlaythroughOnly && bCompletedOnce);
        if (!bAllowed)
        {
            ++RunningActionIndex;
            bRunningDelayDone = false;
            continue;
        }
        if (A.DelayS > 0.f && !bRunningDelayDone)
        {
            bRunningDelayDone = true;
            RunningWait = ESaskartaRunWait::Time;
            RunningBlockedUntilS = T + A.DelayS;
            continue;
        }
        if (FSaskartaEventLogic::NeedsVoice(A.Type) && (!FSaskartaEventLogic::IsVoiceFree(T, VoiceBusyUntilS) || IsCinematicActive()))
        {
            return; // re-checked on the next step
        }
        double CompleteAt = T;
        ESaskartaRunWait Wait = ESaskartaRunWait::None;
        StartAction(A, false, CompleteAt, Wait);
        ++RunningActionIndex;
        bRunningDelayDone = false;
        if (!A.bParallel)
        {
            RunningWait = Wait;
            RunningBlockedUntilS = CompleteAt;
        }
    }
}

// ============================================================================ actions

bool USaskartaEventRunner::StartAction(const FSaskartaEventAction& A, bool bInCinematic, double& OutCompleteAtS, ESaskartaRunWait& OutWait)
{
    const double T = Now();
    OutCompleteAtS = T;
    OutWait = ESaskartaRunWait::None;
    APlayerController* PC = GetPC();

    switch (A.Type)
    {
    case ESaskartaActionType::PlayRadioLine:
    case ESaskartaActionType::PlayCarrierLine:
    {
        PlayLine(A.Id, A.Type == ESaskartaActionType::PlayCarrierLine, bInCinematic);
        OutWait = bInCinematic ? ESaskartaRunWait::None : ESaskartaRunWait::Voice;
        return true;
    }
    case ESaskartaActionType::PlayCinematic:
        if (BeginCinematic(A.Id))
        {
            bCineFromBeat = !bInCinematic;
            OutWait = ESaskartaRunWait::Cinematic;
            return true;
        }
        return false;
    case ESaskartaActionType::ShowHudQuery:
        RunHudAction(A, bInCinematic);
        return true;
    case ESaskartaActionType::ShowCaption:
    {
        // Older story assets still contain the opening CRT controls caption.
        // The small native gameplay overlay owns this after actual CIN01 handback.
        if (ActiveCineId == FName(TEXT("CIN_01_DIRECTIVE")) && A.Text.ToString().StartsWith(TEXT("W / RT")))
            return true;
        const FName Target = A.TargetTag;
        if (Target == FName(TEXT("Hud")))
        {
            TArray<FSaskartaHudOutput> HudOut;
            HudLane.NoteExternalLine(T, A.DurationS, HudOut);
            EmitHud(HudOut);
            PumpHud();
        }
        OnCaptionShow.Broadcast(A.Text, Target, A.DurationS);
        if (A.DurationS > 0.f)
        {
            FTimerHandle Handle;
            if (UWorld* World = GetWorld())
            {
                World->GetTimerManager().SetTimer(Handle, FTimerDelegate::CreateWeakLambda(this, [this, Target]()
                {
                    OnCaptionHide.Broadcast(Target);
                }), A.DurationS, false);
            }
            OutWait = ESaskartaRunWait::Time;
            OutCompleteAtS = T + A.DurationS;
        }
        return true;
    }
    case ESaskartaActionType::ShowSubtitle:
        ShowLineSubtitle(A.Id, A.DurationS);
        OutWait = ESaskartaRunWait::Time;
        OutCompleteAtS = T + A.DurationS;
        return true;
    case ESaskartaActionType::SetLook:
    {
        LastLook = A.Id;
        OnLookRequested.Broadcast(A.Id, A.DurationS);
        if (USaskartaLightingDirector* Dir = USaskartaLightingDirector::GetLightingDirector(this))
        {
            // Forwarded only if the director has these UFUNCTIONs (EVENTS.md section 8 adds them).
            UFunction* F = Dir->FindFunction(A.Id.IsNone() ? FName(TEXT("PopLookOverride")) : FName(TEXT("PushLookOverride")));
            if (F)
            {
                uint8* P = static_cast<uint8*>(FMemory_Alloca(FMath::Max<int32>(F->ParmsSize, 1)));
                FMemory::Memzero(P, FMath::Max<int32>(F->ParmsSize, 1));
                for (TFieldIterator<FProperty> It(F); It && It->HasAnyPropertyFlags(CPF_Parm); ++It)
                {
                    if (FNameProperty* NP = CastField<FNameProperty>(*It)) NP->SetPropertyValue_InContainer(P, A.Id);
                    else if (FFloatProperty* FP = CastField<FFloatProperty>(*It)) FP->SetPropertyValue_InContainer(P, A.DurationS);
                    else if (FDoubleProperty* DP = CastField<FDoubleProperty>(*It)) DP->SetPropertyValue_InContainer(P, A.DurationS);
                }
                Dir->ProcessEvent(F, P);
            }
        }
        return true;
    }
    case ESaskartaActionType::SetFog:
    {
        LastFog = A.Value;
        OnFogRequested.Broadcast(A.Value, A.DurationS);
        if (USaskartaLightingDirector* Dir = USaskartaLightingDirector::GetLightingDirector(this))
        {
            if (UFunction* F = Dir->FindFunction(TEXT("PushFogOverride")))
            {
                uint8* P = static_cast<uint8*>(FMemory_Alloca(FMath::Max<int32>(F->ParmsSize, 1)));
                FMemory::Memzero(P, FMath::Max<int32>(F->ParmsSize, 1));
                int32 Index = 0;
                for (TFieldIterator<FProperty> It(F); It && It->HasAnyPropertyFlags(CPF_Parm); ++It, ++Index)
                {
                    const float V = Index == 0 ? A.Value : A.DurationS;
                    if (FFloatProperty* FP = CastField<FFloatProperty>(*It)) FP->SetPropertyValue_InContainer(P, V);
                    else if (FDoubleProperty* DP = CastField<FDoubleProperty>(*It)) DP->SetPropertyValue_InContainer(P, V);
                }
                Dir->ProcessEvent(F, P);
            }
        }
        return true;
    }
    case ESaskartaActionType::SpawnOrReveal:
        Reveal(A.Id);
        return true;
    case ESaskartaActionType::SetFlowState:
        SetFlowStateByReflection(A.Id);
        return true;
    case ESaskartaActionType::Wait:
        OutWait = ESaskartaRunWait::Time;
        OutCompleteAtS = T + A.DurationS;
        return true;
    case ESaskartaActionType::Prompt:
        BeginPrompt(A, bInCinematic);
        OutWait = ESaskartaRunWait::Prompt;
        return true;
    case ESaskartaActionType::PlaySfx:
        PlaySfx(A);
        return true;
    case ESaskartaActionType::Glance:
    {
        BeginGlance(A.Id, A);
        const FSaskartaGlanceDef* G = Story ? Story->FindGlance(A.Id) : nullptr;
        OutWait = ESaskartaRunWait::Time;
        OutCompleteAtS = T + (G ? G->EaseInS : 0.f);
        return true;
    }
    case ESaskartaActionType::SetInputLock:
        if (A.Value > 0.5f)
        {
            LockInput(true, true);
        }
        else
        {
            UnlockInput();
        }
        return true;
    case ESaskartaActionType::CallHook:
        return CallHook(ResolveTarget(A.TargetTag), A.Id, {}, {});
    case ESaskartaActionType::Checkpoint:
        return SaveCheckpoint(A.Id);
    case ESaskartaActionType::SetMode:
    {
        SetPresentationMode(A.Id, A.Value > 0.5f);
        return true;
    }
    case ESaskartaActionType::SetControlRotation:
        if (PC)
        {
            PC->SetControlRotation(FRotator(A.Pitch, A.Yaw, 0.f));
        }
        return true;
    case ESaskartaActionType::ShowLetterbox:
        bCineLetterboxOn = A.Value > 0.5f;
        OnLetterbox.Broadcast(bCineLetterboxOn, FSaskartaEventLogic::LetterboxBlendS);
        return true;
    case ESaskartaActionType::SetGeiger:
        OnGeigerSample.Broadcast(A.Id);
        CallHook(PC, TEXT("SetGeigerSample"), { A.Id }, {});
        return true;
    case ESaskartaActionType::ShowEndCard:
        OnEndCard.Broadcast(A.Id);
        return true;
    case ESaskartaActionType::PlayDawn:
        if (USaskartaLightingDirector* Dir = USaskartaLightingDirector::GetLightingDirector(this))
        {
            Dir->PlayDawn(A.DurationS > 0.f ? A.DurationS : FSaskartaFirstLight::DefaultDurationS,
                A.Value > 0.f ? A.Value : FSaskartaFirstLight::DefaultClearAtS, A.Pitch, A.Yaw);
        }
        return true;
    case ESaskartaActionType::StopSfx:
        StopSfx(A.Id, A.DurationS);
        return true;
    case ESaskartaActionType::OpenLevel:
    {
        bCompletedOnce = true;
        SaveProfile();
        const FString Level = (A.Id.IsNone() || A.Id == FName(TEXT("Title"))) ? UGameplayStatics::GetCurrentLevelName(this, true) : A.Id.ToString();
        StopAll();
        UGameplayStatics::OpenLevel(this, FName(*Level));
        return true;
    }
    default:
        UE_LOG(LogSaskartaEvents, Warning, TEXT("action type %d not handled"), static_cast<int32>(A.Type));
        return false;
    }
}

// ============================================================================ HUD queries

void USaskartaEventRunner::RunHudAction(const FSaskartaEventAction& A, bool bFromCue)
{
    TArray<FSaskartaHudOutput> Out;
    if (A.TargetTag == FSaskartaHudLane::ColumnTarget || A.TargetTag == FSaskartaHudLane::StatusTarget)
    {
        HudLane.SetColumnVisible(A.Value > 0.5f, Out);
        EmitHud(Out);
        return;
    }
    FSaskartaHudItem Item;
    if (!FSaskartaHudLane::ItemFromAction(A, Item))
    {
        return;
    }
    // A cue inside a cinematic's POV shot takes HudLine at once, on the beat's own timing.
    Item.bImmediate = bFromCue && IsCinematicActive();
    HudLane.Push(MoveTemp(Item), Now(), IsCinematicActive(), Out);
    EmitHud(Out);
    PumpHud();
}

void USaskartaEventRunner::PumpHud()
{
    UWorld* World = GetWorld();
    if (!World)
    {
        return;
    }
    TArray<FSaskartaHudOutput> Out;
    // Road queries never start under a letterboxed cinematic; they wait (unaged) for the hand-back.
    HudLane.Advance(Now(), IsCinematicActive(), Out);
    EmitHud(Out);
    FTimerManager& TM = World->GetTimerManager();
    if (HudLane.IsIdle())
    {
        TM.ClearTimer(HudTimer);
    }
    else if (!TM.IsTimerActive(HudTimer))
    {
        TM.SetTimer(HudTimer, this, &USaskartaEventRunner::PumpHud, 0.1f, true);
    }
}

void USaskartaEventRunner::EmitHud(const TArray<FSaskartaHudOutput>& Out)
{
    static const FName Hud(TEXT("Hud"));
    for (const FSaskartaHudOutput& O : Out)
    {
        switch (O.Kind)
        {
        case ESaskartaHudOut::ShowLine:
            OnCaptionShow.Broadcast(FText::FromString(O.Text), Hud, O.DurationS);
            break;
        case ESaskartaHudOut::HideLine:
            OnCaptionHide.Broadcast(Hud);
            break;
        case ESaskartaHudOut::ShowColumn:
            OnCaptionShow.Broadcast(FText::FromString(O.Text), FSaskartaHudLane::ColumnTarget, 0.f);
            break;
        case ESaskartaHudOut::HideColumn:
            OnCaptionHide.Broadcast(FSaskartaHudLane::ColumnTarget);
            break;
        case ESaskartaHudOut::Tick:
        {
            FSaskartaEventAction Tick;
            Tick.Type = ESaskartaActionType::PlaySfx;
            Tick.Id = FName(TEXT("SFX_Carrier_HudTick"));
            PlaySfx(Tick);
            break;
        }
        }
    }
}

void USaskartaEventRunner::RebuildHudColumn()
{
    // The status lines are not derived from the beats (USaskartaRouteLog pushes them); only re-show them.
    TArray<FSaskartaHudOutput> Out;
    HudLane.SetColumnVisible(HudLane.bColumnVisible, Out);
    EmitHud(Out);
}

void USaskartaEventRunner::SetHudStatus(const FString& Status)
{
    TArray<FSaskartaHudOutput> Out;
    HudLane.SetStatus(Status, Out);
    EmitHud(Out);
}

void USaskartaEventRunner::ShowHudEvent(const FString& Text, float DurationS)
{
    if (Text.IsEmpty())
    {
        return;
    }
    FSaskartaHudItem Item;
    Item.Id = FName(TEXT("HUD_EVENT"));
    Item.Query = Text;
    Item.QueryS = FMath::Max(0.5f, DurationS);
    TArray<FSaskartaHudOutput> Out;
    HudLane.Push(MoveTemp(Item), Now(), IsCinematicActive(), Out);
    EmitHud(Out);
    PumpHud();
}

bool USaskartaEventRunner::TypeCrtLog(const FString& Line)
{
    bool bBlackUp = false;
    UActorComponent* Terminal = FindCrtTerminal(bBlackUp);
    return bBlackUp && TypeCrtLine(Terminal, Line);
}

void USaskartaEventRunner::PlayNamedSfx(FName SfxId)
{
    if (SfxId.IsNone())
    {
        return;
    }
    FSaskartaEventAction Sfx;
    Sfx.Type = ESaskartaActionType::PlaySfx;
    Sfx.Id = SfxId;
    PlaySfx(Sfx);
}

USoundBase* USaskartaEventRunner::ResolveLineSound(FName LineId, FString& OutText, FName& OutSpeaker)
{
    const FSaskartaLineDef* L = Story ? Story->FindLine(LineId) : nullptr;
    OutText = L ? L->English : FString();
    OutSpeaker = L ? L->Speaker : NAME_None;
    return ResolveSound(LineId, L ? L->Sound : TSoftObjectPtr<USoundBase>());
}

void USaskartaEventRunner::RunImmediate(const FSaskartaEventAction& Action)
{
    double Ignored = 0.0;
    ESaskartaRunWait IgnoredWait = ESaskartaRunWait::None;
    StartAction(Action, true, Ignored, IgnoredWait);
}

// ============================================================================ lines and subtitles

void USaskartaEventRunner::PrefetchBeatSounds(const FSaskartaBeatDef& Beat)
{
    if (!Story || !UAssetManager::IsInitialized())
    {
        return;
    }
    TArray<FSoftObjectPath> Paths;
    auto AddLine = [this, &Paths](FName Id)
    {
        if (const FSaskartaLineDef* L = Story->FindLine(Id))
        {
            if (!L->Sound.IsNull() && L->Sound.IsPending())
            {
                Paths.AddUnique(L->Sound.ToSoftObjectPath());
            }
        }
    };
    for (const FSaskartaEventAction& A : Beat.Actions)
    {
        if (SaskartaEvents::IsLineAction(A.Type))
        {
            AddLine(A.Id);
        }
        else if (A.Type == ESaskartaActionType::PlayCinematic)
        {
            if (const FSaskartaCinematicDef* C = Story->FindCinematic(A.Id))
            {
                if (!C->Sequence.IsNull() && C->Sequence.IsPending())
                {
                    Paths.AddUnique(C->Sequence.ToSoftObjectPath());
                }
                for (const FSaskartaEventAction& Cue : C->Cues)
                {
                    if (SaskartaEvents::IsLineAction(Cue.Type))
                    {
                        AddLine(Cue.Id);
                    }
                }
            }
        }
    }
    // Only paths the registry knows, so a not-yet-imported line never logs a load failure.
    if (IAssetRegistry* AR = IAssetRegistry::Get())
    {
        Paths.RemoveAll([AR](const FSoftObjectPath& P) { return !AR->GetAssetByObjectPath(P).IsValid(); });
    }
    if (Paths.Num() > 0)
    {
        UAssetManager::GetStreamableManager().RequestAsyncLoad(Paths, FStreamableDelegate());
    }
}

USoundBase* USaskartaEventRunner::ResolveSound(FName Id, const TSoftObjectPtr<USoundBase>& Preferred)
{
    if (USoundBase* Loaded = Preferred.Get())
    {
        return Loaded;
    }
    IAssetRegistry* AR = IAssetRegistry::Get();
    if (!Preferred.IsNull() && AR && AR->GetAssetByObjectPath(Preferred.ToSoftObjectPath()).IsValid())
    {
        UE_LOG(LogSaskartaEvents, Warning, TEXT("sync load of %s (not prefetched: a hitch)"), *Preferred.ToString());
        return Preferred.LoadSynchronous();
    }
    // Fall back to any asset of that name under /Game/SaskartaGaea/Audio.
    static double LastBuildS = -1000.0;
    const FSoftObjectPath* Found = SoundIndex.Find(Id);
    if (!Found && AR && (!bSoundIndexBuilt || FPlatformTime::Seconds() - LastBuildS > SaskartaEvents::SoundIndexRebuildS))
    {
        bSoundIndexBuilt = true;
        LastBuildS = FPlatformTime::Seconds();
        SoundIndex.Reset();
        TArray<FAssetData> Assets;
        AR->GetAssetsByPath(FName(SaskartaEvents::AudioRoot), Assets, /*bRecursive*/ true);
        for (const FAssetData& D : Assets)
        {
            SoundIndex.Add(D.AssetName, D.GetSoftObjectPath());
        }
        Found = SoundIndex.Find(Id);
    }
    if (Found)
    {
        if (USoundBase* Resident = Cast<USoundBase>(Found->ResolveObject()))
        {
            return Resident;
        }
        UE_LOG(LogSaskartaEvents, Warning, TEXT("sync load of %s (not prefetched: a hitch)"), *Found->ToString());
        return Cast<USoundBase>(Found->TryLoad());
    }
    if (!WarnedMissing.Contains(Id))
    {
        WarnedMissing.Add(Id);
        UE_LOG(LogSaskartaEvents, Warning, TEXT("sound %s not imported yet: subtitle and timing only"), *Id.ToString());
    }
    return nullptr;
}

float USaskartaEventRunner::PlayLine(FName LineId, bool bCarrier, bool bCinematicLane)
{
    const FSaskartaLineDef* L = Story ? Story->FindLine(LineId) : nullptr;
    USoundBase* Sound = ResolveSound(LineId, L ? L->Sound : TSoftObjectPtr<USoundBase>());
    float Dur = (L && L->DurationS > 0.f) ? L->DurationS : 3.f;
    if (Sound)
    {
        const float SoundDur = Sound->GetDuration();
        if (SoundDur > 0.f && SoundDur < 3600.f)
        {
            Dur = SoundDur;
        }
    }

    TObjectPtr<UAudioComponent>& Comp = bCinematicLane ? CineVoiceComp : VoiceComp;
    if (Comp && Comp->IsPlaying())
    {
        Comp->Stop();
    }
    Comp = nullptr;
    if (Sound)
    {
        const bool bCarrierLine = bCarrier || (L && L->bCarrier);
        const float MixGain = bCarrierLine ? 1.f : SaskartaAudioMix::RadioProgramGain;
        Comp = UGameplayStatics::CreateSound2D(this, Sound, MixGain, 1.f, 0.f, nullptr, false, true);
        if (Comp)
        {
            Comp->Play();
        }
    }

    const double T = Now();
    if (!bCinematicLane)
    {
        const float Gap = Story ? Story->GapS : FSaskartaEventLogic::DefaultGapS;
        LineEndS = T + Dur;
        VoiceBusyUntilS = FSaskartaEventLogic::VoiceBusyUntilAfterLine(T, Dur, Gap);
        CurrentLineId = LineId;
        // The station classifies the line first (archive: force on + cut; carrier: duck), then hears busy.
        OnStoryLine.Broadcast(LineId, bHasRunning ? RunningBeatId : NAME_None, bCarrier || (L && L->bCarrier),
            bHasRunning ? static_cast<int32>(RunningPriority) : static_cast<int32>(ESaskartaEventPriority::Cinematic), Dur);
        BroadcastBusy(true, Dur, false);
    }
    else
    {
        LineEndS = FMath::Max(LineEndS, T + Dur);
        CurrentLineId = LineId;
        if (ShouldKeepStationPlaying())
        {
            // A camera cut is transparent to radio. Only an actual voiced cue ducks
            // the existing component, using the same carrier/story classification.
            const float Gap = Story ? Story->GapS : FSaskartaEventLogic::DefaultGapS;
            VoiceBusyUntilS = FSaskartaEventLogic::VoiceBusyUntilAfterLine(T, Dur, Gap);
            OnStoryLine.Broadcast(LineId, RunningBeatId, bCarrier || (L && L->bCarrier),
                static_cast<int32>(ESaskartaEventPriority::Cinematic), Dur);
            BroadcastBusy(true, Dur, false);
        }
    }
    UE_LOG(LogSaskartaEvents, Log, TEXT("line %s (%.1f s)%s%s"), *LineId.ToString(), Dur, bCarrier ? TEXT(" carrier") : TEXT(""),
        bCinematicLane ? TEXT(" [cine lane]") : TEXT(""));
    ShowLineSubtitle(LineId, Dur);
    return Dur;
}

void USaskartaEventRunner::ShowLineSubtitle(FName LineId, float DurationS)
{
    const FSaskartaLineDef* L = Story ? Story->FindLine(LineId) : nullptr;
    if (!L)
    {
        return;
    }
    SubtitleHideAtS = Now() + FMath::Max(0.5f, DurationS);
    bStorySubtitleActive = true;
    bStationSubtitleActive = false;
    FSaskartaSubtitle Sub;
    Sub.LineId = LineId;
    Sub.Speaker = FSaskartaFirstLight::CaptionSpeaker(LineId, L->Speaker);
    Sub.English = FText::FromString(L->English);
    Sub.bSaskartan = L->bSaskartan;
    Sub.Header = FText::FromString(L->CaptionHeader);
    Sub.DurationS = DurationS;
    Sub.bStation = false;
    StorySubtitleBase = Sub;
    TArray<FSaskartaCaptionPage> Pages = FSaskartaCaptionPaging::Resolve(L->CaptionPages, L->English,
        L->bSaskartan && USaskartaStorySettings::Get()->bShowSaskartan ? L->Saskartan : FString(), DurationS);
    if (L->bCarrier)
    {
        FSaskartaCaptionPaging::AddPrefix(Pages, TEXT("CARRIER: "));
    }
    StorySubtitlePager.Start(Pages, Now(), 0.f, DurationS);
    UpdateSubtitlePages();
}

void USaskartaEventRunner::HideStorySubtitle()
{
    SubtitleHideAtS = -1.0;
    StorySubtitlePager.Reset();
    if (bStorySubtitleActive)
    {
        bStorySubtitleActive = false;
        OnSubtitleHide.Broadcast(false);
    }
    StationSubtitlePager.Reshow();
}

void USaskartaEventRunner::ShowStationSubtitle(const FSaskartaSubtitle& Subtitle)
{
    StationSubtitleBase = Subtitle;
    StationSubtitleBase.bStation = true;
    StationSubtitleBase.Pages.Reset();
    TArray<FSaskartaCaptionPage> Pages = Subtitle.Pages;
    if (Pages.IsEmpty())
    {
        Pages = FSaskartaCaptionPaging::Resolve(TArray<FSaskartaCaptionPage>(), Subtitle.English.ToString(), FString(), Subtitle.DurationS);
    }
    StationSubtitlePager.Start(Pages, Now(), Subtitle.StartOffsetS, Subtitle.DurationS);
    bStationSubtitleActive = false;
    if (FSaskartaEventLogic::SubtitleMayReplace(true, bStorySubtitleActive))
    {
        UpdateSubtitlePages();
    }
}

void USaskartaEventRunner::HideStationSubtitle()
{
    StationSubtitlePager.Reset();
    if (bStationSubtitleActive)
    {
        bStationSubtitleActive = false;
        OnSubtitleHide.Broadcast(true);
    }
}

void USaskartaEventRunner::SetStationSubtitlePaused(bool bPaused)
{
    StationSubtitlePager.SetPaused(bPaused, Now());
}

void USaskartaEventRunner::UpdateSubtitlePages()
{
    const double Time = Now();
    if (bStorySubtitleActive && !StorySubtitlePager.IsLive())
    {
        return;
    }
    FSaskartaCaptionPager* Pager = nullptr;
    const FSaskartaSubtitle* Base = nullptr;
    if (StorySubtitlePager.IsLive())
    {
        Pager = &StorySubtitlePager;
        Base = &StorySubtitleBase;
    }
    else if (StationSubtitlePager.IsLive())
    {
        Pager = &StationSubtitlePager;
        Base = &StationSubtitleBase;
    }
    if (!Pager || !Base || !SaskartaEvents::SubtitlesEnabled())
    {
        return;
    }
    const int32 Index = Pager->TakeDue(Time);
    if (!Pager->Pages.IsValidIndex(Index))
    {
        return;
    }
    const FSaskartaCaptionPage& Page = Pager->Pages[Index];
    FSaskartaSubtitle Sub = *Base;
    Sub.English = FText::FromString(Page.Text);
    Sub.Saskartan = FText::GetEmpty(); // English-only subtitles; the original recordings keep their names.
    Sub.DurationS = FSaskartaCaptionPaging::PageDurationS(Pager->Pages, Index, Pager->DurationS);
    Sub.PageIndex = Index;
    Sub.PageCount = Pager->Pages.Num();
    if (!Sub.bStation && Pager->ElapsedS(Time) >= FSaskartaCaptionPaging::HeaderHoldS)
    {
        Sub.Header = FText::GetEmpty();
    }
    if (Sub.bStation)
    {
        bStationSubtitleActive = true;
    }
    OnSubtitleShow.Broadcast(Sub);
}

bool USaskartaEventRunner::TryPlayAuxCarrierLine(FName LineId, USoundBase* Sound, float DurationS, float MinGapS, float LeadS)
{
    if (bHumanGroundingActive || bCarrierGroundingActive) return false;
    float Dur = DurationS;
    if (Sound)
    {
        const float SoundDur = Sound->GetDuration();
        if (SoundDur > 0.f && SoundDur < 3600.f)
        {
            Dur = SoundDur;
        }
    }
    if (Dur <= 0.f)
    {
        return false;
    }
    const bool bBeatBusy = bHasRunning || Queue.Num() > 0 || PendingKeepLines.Num() > 0;
    if (!FSaskartaEventLogic::CanStartAuxLine(IsVoiceBusy(), IsCinematicActive(), bBeatBusy, SecondsSinceVoice(),
        GetSecondsToNextBeat(), Dur, MinGapS, LeadS))
    {
        return false;
    }
    if (VoiceComp && VoiceComp->IsPlaying())
    {
        VoiceComp->Stop();
    }
    VoiceComp = nullptr;
    if (Sound)
    {
        VoiceComp = UGameplayStatics::CreateSound2D(this, Sound, 1.f, 1.f, 0.f, nullptr, false, true);
        if (VoiceComp)
        {
            VoiceComp->Play();
        }
    }
    const double T = Now();
    const float Gap = Story ? Story->GapS : FSaskartaEventLogic::DefaultGapS;
    LineEndS = T + Dur;
    VoiceBusyUntilS = FSaskartaEventLogic::VoiceBusyUntilAfterLine(T, Dur, Gap);
    CurrentLineId = LineId;
    // Same order as a beat line: the station classifies it first (carrier: duck, never a cut), then hears busy.
    OnStoryLine.Broadcast(LineId, NAME_None, true, static_cast<int32>(ESaskartaEventPriority::Hint), Dur);
    BroadcastBusy(true, Dur, false);
    UE_LOG(LogSaskartaEvents, Log, TEXT("aux carrier line %s (%.1f s)"), *LineId.ToString(), Dur);
    return true;
}

void USaskartaEventRunner::StopStormPanicLine()
{
    // A story line may have taken Voice since the last poll. Never stop that line,
    // its subtitle or its radio duck when this optional warning lane shuts down.
    if (!CurrentLineId.ToString().StartsWith(TEXT("CV_STORM_PANIC_")) || IsCinematicActive()) return;
    if (IsValid(VoiceComp)) VoiceComp->Stop();
    VoiceComp = nullptr;
    CurrentLineId = NAME_None;
    LineEndS = -1.0;
    LastVoiceEndS = Now();
    VoiceBusyUntilS = Now();
    HideStorySubtitle();
    if (bStoryBusyBroadcast) BroadcastBusy(false, 0.f, false);
}

void USaskartaEventRunner::UpdateStormPanic(float GapM, bool bActive, bool bInputWarningActive)
{
    const double T = Now();
    UWorld* World = GetWorld();
    const FName Flow = GetFlowState();
    if (!bActive || !World || World->IsPaused() || !Story || !FMath::IsFinite(GapM) || GapM <= 0.f
        || (Flow != FName(TEXT("Playing")) && Flow != FName(TEXT("Carrier")))
        || IsCinematicActive() || IsHoldingInput() || bPromptActive)
    {
        StopStormPanicLine();
        bStormPanicActive = false;
        NextStormPanicS = T + .75;
        return;
    }
    if (!bStormPanicActive)
    {
        bStormPanicActive = true;
        NextStormPanicS = FMath::Max(NextStormPanicS, T + .75);
        // Only the two approved imported takes exist. Retain this bounded preload
        // across a pause/input hold; no failed requests for the missing four takes.
        TArray<FSoftObjectPath> Paths;
        for (int32 Index = 1; Index <= 2; ++Index)
        {
            const FName Id(*FString::Printf(TEXT("CV_STORM_PANIC_%02d"), Index));
            const FSaskartaLineDef* Line = Story->FindLine(Id);
            const FSoftObjectPath Path = SoundPathFor(Id, Line ? Line->Sound : TSoftObjectPtr<USoundBase>());
            if (!Path.IsNull()) Paths.AddUnique(Path);
        }
        if (!StormPanicLoad.IsValid() && !Paths.IsEmpty() && UAssetManager::IsInitialized())
            StormPanicLoad = UAssetManager::GetStreamableManager().RequestAsyncLoad(Paths, FStreamableDelegate());
    }
    const int32 Stage = GapM <= 25.f ? 2 : GapM <= 50.f ? 1 : 0;
    const double IntervalS = Stage == 2 ? 8.0 : Stage == 1 ? 10.0 : 12.0;
    // Escalation can shorten the next interval, but never below eight seconds after
    // the last spoken warning. Input cues defer its start; normal beat ticks do not cut words.
    if (bInputWarningActive || T < NextStormPanicS || T < LastStormPanicEndS + IntervalS) return;
    const int32 Variant = StormPanicVariant[Stage];
    const int32 Indices[] = { Variant + 1, 2 - Variant };
    FName Id;
    USoundBase* Sound = nullptr;
    for (const int32 Index : Indices)
    {
        const FName Candidate(*FString::Printf(TEXT("CV_STORM_PANIC_%02d"), Index));
        if (Candidate == LastStormPanicLine) continue;
        const FSaskartaLineDef* Line = Story->FindLine(Candidate);
        if (!Line) continue;
        const FSoftObjectPath Path = SoundPathFor(Candidate, Line->Sound);
        if (USoundBase* Loaded = Cast<USoundBase>(Path.ResolveObject()))
        {
            Id = Candidate;
            Sound = Loaded;
            break;
        }
    }
    if (!Sound)
    {
        if (StormPanicLoad && !StormPanicLoad->HasLoadCompleted()) return;
        const FName Missing(TEXT("StormPanicTakes"));
        if (!WarnedMissing.Contains(Missing))
        {
            WarnedMissing.Add(Missing);
            UE_LOG(LogSaskartaEvents, Warning, TEXT("storm panic needs at least two imported carrier takes and DA_Story captions; warning deferred"));
        }
        return;
    }
    const float DurationS = Sound->GetDuration();
    if (!FMath::IsFinite(DurationS) || DurationS <= 0.f || DurationS > 6.f) return;
    if (!TryPlayAuxCarrierLine(Id, Sound, DurationS, 1.f, 3.f)) return;
    ShowLineSubtitle(Id, DurationS); // existing carrier prefix and English caption channel
    LastStormPanicLine = Id;
    StormPanicVariant[Stage] = 1 - StormPanicVariant[Stage];
    LastStormPanicEndS = T + DurationS;
    NextStormPanicS = LastStormPanicEndS + 8.0;
    UE_LOG(LogSaskartaEvents, Log, TEXT("storm panic stage %d, gap %.0f m: %s; next in %.1f s"),
        Stage + 1, GapM, *Id.ToString(), DurationS + IntervalS);
}

bool USaskartaEventRunner::CanPlayStormAlarm() const
{
    const UWorld* World = GetWorld();
    const FName Flow = GetFlowState();
    return World && !World->IsPaused() && !bHumanGroundingActive && !bCarrierGroundingActive
        && (Flow == FName(TEXT("Playing")) || Flow == FName(TEXT("Carrier")))
        && !IsVoiceBusy() && !IsCinematicActive() && !IsHoldingInput() && !bPromptActive
        && !bHasRunning && Queue.IsEmpty() && PendingKeepLines.IsEmpty()
        && SecondsSinceVoice() >= 1.f && GetSecondsToNextBeat() >= 4.f;
}

void USaskartaEventRunner::BroadcastBusy(bool bBusy, float ExpectedS, bool bCinematic)
{
    // A second line while already busy is re-announced (the station extends its hold), but
    // the backstop mix is pushed and popped only on the transitions, so it stays balanced.
    bStoryBusyBroadcast = bBusy;
    // Storm warnings use the station's existing -6dB / .3s carrier duck. Adding
    // the -12dB backstop mix here would stack two reductions on the same cursor.
    const bool bStormWarning = CurrentLineId.ToString().StartsWith(TEXT("CV_STORM_PANIC_"));
    const bool bDuckStation = bBusy && !bStormWarning && !(bCinematic && ShouldKeepStationPlaying());
    if (bDuckStation != bStationDuckMixPushed)
    {
        // Backstop for an unbuilt station: SCM_Saskarta_StoryDuck takes SC_Station and SC_Idle down 12 dB.
        if (USoundMix* Mix = SaskartaEvents::StoryDuckMix())
        {
            if (bDuckStation) UGameplayStatics::PushSoundMixModifier(this, Mix);
            else UGameplayStatics::PopSoundMixModifier(this, Mix);
            bStationDuckMixPushed = bDuckStation;
        }
    }
    OnStoryBusyChanged.Broadcast(bBusy, ExpectedS, bCinematic);
}

void USaskartaEventRunner::UpdateVoiceBusy()
{
    const double T = Now();
    if (LineEndS > 0.0 && T >= LineEndS)
    {
        LastVoiceEndS = LineEndS;
        LineEndS = -1.0;
        CurrentLineId = NAME_None;
        if (bStoryBusyBroadcast && (!IsCinematicActive() || ShouldKeepStationPlaying()))
        {
            BroadcastBusy(false, 0.f, false);
        }
    }
    if (SubtitleHideAtS > 0.0 && T >= SubtitleHideAtS)
    {
        HideStorySubtitle();
    }
    UpdateSubtitlePages();
    // keep_on_skip lines play on Voice once the blend-out is done.
    if (PendingKeepLines.Num() > 0 && !IsCinematicActive() && FSaskartaEventLogic::IsVoiceFree(T, VoiceBusyUntilS))
    {
        const FName Id = PendingKeepLines[0];
        PendingKeepLines.RemoveAt(0);
        const FSaskartaLineDef* L = Story ? Story->FindLine(Id) : nullptr;
        PlayLine(Id, L && L->bCarrier, false);
    }
}

bool USaskartaEventRunner::IsVoiceBusy() const
{
    return IsCinematicActive() || !FSaskartaEventLogic::IsVoiceFree(Now(), VoiceBusyUntilS);
}

bool USaskartaEventRunner::ShouldKeepStationPlaying() const
{
    const FSaskartaCinematicDef* C = Story ? Story->FindCinematic(ActiveCineId) : nullptr;
    return C && (C->bKeepStationPlaying || ActiveCineId == FName(TEXT("CIN_04_DUST_FRONT")));
}

bool USaskartaEventRunner::IsStationVoiceBusy() const
{
    return (IsCinematicActive() && !ShouldKeepStationPlaying())
        || !FSaskartaEventLogic::IsVoiceFree(Now(), VoiceBusyUntilS);
}

float USaskartaEventRunner::SecondsSinceStationVoice() const
{
    if (IsStationVoiceBusy() || LineEndS > 0.0) return 0.f;
    return static_cast<float>(Now() - LastVoiceEndS);
}

float USaskartaEventRunner::SecondsSinceVoice() const
{
    if (IsVoiceBusy() || LineEndS > 0.0)
    {
        return 0.f;
    }
    return static_cast<float>(Now() - LastVoiceEndS);
}

void USaskartaEventRunner::PlaySfx(const FSaskartaEventAction& A)
{
    if (A.Id == FName(TEXT("eyetae_title")))
    {
        if (UWorld* World = GetWorld())
        {
            if (USaskartaRadioStation* Station = World->GetSubsystem<USaskartaRadioStation>())
            {
                Station->StartTitleSongTransition();
                return;
            }
        }
    }
    USoundBase* Sound = ResolveSound(A.Id, TSoftObjectPtr<USoundBase>());
    if (!Sound)
    {
        return;
    }
    AActor* At = (!A.TargetTag.IsNone() && A.TargetTag != FName(TEXT("Hud"))) ? ResolveTarget(A.TargetTag) : nullptr;
    // Spawned (auto-destroying) components instead of fire-and-forget, so StopSfx can cut them (the First Light
    // ending: the hut speaker cut mid-word at the hand, the hiss and the title track).
    UAudioComponent* Comp = At
        ? UGameplayStatics::SpawnSoundAtLocation(this, Sound, At->GetActorLocation())
        : UGameplayStatics::SpawnSound2D(this, Sound);
    if (Comp)
    {
        TrackedSfx.Add(A.Id, Comp);
    }
}

void USaskartaEventRunner::StopSfx(FName Id, float FadeS)
{
    if (Id == FName(TEXT("eyetae_title")))
    {
        if (UWorld* World = GetWorld())
        {
            if (USaskartaRadioStation* Station = World->GetSubsystem<USaskartaRadioStation>())
                Station->StopEndMusic(FadeS);
        }
        return;
    }
    TWeakObjectPtr<UAudioComponent> Comp;
    if (!TrackedSfx.RemoveAndCopyValue(Id, Comp) || !Comp.IsValid())
    {
        UE_LOG(LogSaskartaEvents, Log, TEXT("StopSfx %s: nothing playing"), *Id.ToString());
        return;
    }
    if (FadeS > 0.f)
    {
        Comp->FadeOut(FadeS, 0.f);
    }
    else
    {
        Comp->Stop();
    }
    UE_LOG(LogSaskartaEvents, Log, TEXT("StopSfx %s (fade %.1f s)"), *Id.ToString(), FadeS);
}

void USaskartaEventRunner::Reveal(FName Id)
{
    Revealed.AddUnique(Id);
    UWorld* World = GetWorld();
    if (!World)
    {
        return;
    }
    const FString S = Id.ToString();
    FString LayerRef;
    if (FSaskartaPromptLogic::ParseDataLayerRef(S, LayerRef))
    {
        // By the UDataLayerAsset, never a label (SaskartaEventRunnerPrompt.cpp); it logs why when nothing activates.
        ActivateDataLayer(LayerRef);
        return;
    }
    const FName Tag(*(TEXT("Saskarta.Reveal.") + S));
    int32 Count = 0;
    for (TActorIterator<AActor> It(World); It; ++It)
    {
        if (It->ActorHasTag(Tag))
        {
            It->SetActorHiddenInGame(false);
            It->SetActorEnableCollision(true);
            ++Count;
        }
    }
    UE_LOG(LogSaskartaEvents, Log, TEXT("revealed %s (%d actors)"), *S, Count);
}

// ============================================================================ cinematics

bool USaskartaEventRunner::BeginCinematic(FName CinematicId)
{
    const FSaskartaCinematicDef* C = Story ? Story->FindCinematic(CinematicId) : nullptr;
    if (!C)
    {
        UE_LOG(LogSaskartaEvents, Warning, TEXT("PlayCinematic %s: not defined"), *CinematicId.ToString());
        return false;
    }
    if (CinePhase != ESaskartaCinePhase::None)
    {
        UE_LOG(LogSaskartaEvents, Warning, TEXT("PlayCinematic %s: %s is still playing"), *CinematicId.ToString(), *ActiveCineId.ToString());
        return false;
    }

    // No Level Sequence yet: never freeze the carrier or lock input for a cinematic the player
    // cannot see (user, 2026-09-28: "my car got stuck" = CIN_06 / CIN_11 holding input 16-18 s on
    // the world clock). Its lines play as radio through the Voice channel instead, and its final
    // state still runs.
    {
        IAssetRegistry* AR = IAssetRegistry::Get();
        const bool bHasSequence = !C->Sequence.IsNull()
            && (C->Sequence.Get() || (AR && AR->GetAssetByObjectPath(C->Sequence.ToSoftObjectPath()).IsValid()));
        if (!bHasSequence)
        {
            TArray<FName> CueLines;
            FSaskartaEventLogic::CollectCueLines(*C, FSaskartaEventLogic::DeriveTags(EnabledTags), bCompletedOnce, CueLines);
            PendingKeepLines.Append(CueLines);
            const int32 Lines = CueLines.Num();
            // The flow state and the black it would have cleared still happen (a missing LS_CIN_19 must not
            // leave the Keeper under the collapse's black).
            for (const FSaskartaEventAction& Cue : C->Cues)
            {
                if (FSaskartaPromptLogic::RunsWithoutSequence(Cue)
                    && FSaskartaEventLogic::TagsAllow(Cue.RequiresTags, Cue.ExcludesTags, FSaskartaEventLogic::DeriveTags(EnabledTags)))
                {
                    RunImmediate(Cue);
                }
            }
            for (const FSaskartaEventAction& A : C->FinalState)
            {
                if (FSaskartaEventLogic::TagsAllow(A.RequiresTags, A.ExcludesTags, FSaskartaEventLogic::DeriveTags(EnabledTags))
                    && !(A.bFirstPlaythroughOnly && bCompletedOnce))
                {
                    RunImmediate(A);
                }
            }
            UE_LOG(LogSaskartaEvents, Warning, TEXT("cinematic %s: no sequence asset; %d lines queued as radio, no freeze"), *CinematicId.ToString(), Lines);
            OnCinematicStarted.Broadcast(CinematicId);
            OnCinematicFinished.Broadcast(CinematicId);
            return true;
        }
    }
    ActiveCineId = CinematicId;
    NextCue = 0;
    bCinePromptPending = false;
    bCinePromptAnswered = true;
    bCineSkipped = false;
    CinePausedAtS = -1.0;
    CinePausedTotalS = 0.0;
    SkipHeldS = 0.f;
    bCineLetterboxOn = false;
    bCineFromBeat = false;

    BroadcastBusy(true, C->DurationS, true);
    OnCinematicStarted.Broadcast(CinematicId);
    LockInput(true, true);
    if (C->bStopPawn)
    {
        CallHook(GetPawn(), SaskartaEvents::NameStopAnimDriver, {}, {});
        ClearParkedCarrierMotion(false);
    }

    CinePhase = ESaskartaCinePhase::WaitingStop;
    CinePhaseStartS = Now();
    if (UWorld* World = GetWorld())
    {
        World->GetTimerManager().SetTimer(CineWatchdogTimer, this, &USaskartaEventRunner::CineWatchdog, 1.f, true);
    }
    UE_LOG(LogSaskartaEvents, Log, TEXT("cinematic %s: begin (stop pawn %d)"), *CinematicId.ToString(), C->bStopPawn ? 1 : 0);
    if (!C->bStopPawn)
    {
        StartSequence();
    }
    if (UWorld* World = GetWorld())
    {
        World->GetTimerManager().SetTimer(SkipTimer, this, &USaskartaEventRunner::PollSkip, FSaskartaEventLogic::SkipPollS, true);
    }
    return true;
}

void USaskartaEventRunner::StartSequence()
{
    const FSaskartaCinematicDef* C = Story ? Story->FindCinematic(ActiveCineId) : nullptr;
    if (!C)
    {
        return;
    }
    if (C->bStopPawn) ClearParkedCarrierMotion(true);
    CinePhase = ESaskartaCinePhase::Playing;
    CineStartS = Now();
    bCineSensorOriginValid = false;
    bCineSensorFromDrone = false;
    bHaveSafeCineView = false;
    bReportedCineClearance = false;
    if (!CinematicViewGuard.IsValid())
        CinematicViewGuard = FSceneViewExtensions::NewExtension<FSaskartaCinematicViewGuard>(this);

    ULevelSequence* Seq = nullptr;
    if (!C->Sequence.IsNull())
    {
        IAssetRegistry* AR = IAssetRegistry::Get();
        if (C->Sequence.Get() || (AR && AR->GetAssetByObjectPath(C->Sequence.ToSoftObjectPath()).IsValid()))
        {
            Seq = C->Sequence.LoadSynchronous();
        }
    }
    if (Seq)
    {
        FMovieSceneSequencePlaybackSettings Settings;
        Settings.bDisableMovementInput = true;
        Settings.bDisableLookAtInput = true;
        Settings.bHidePlayer = false;
        Settings.bHideHud = true;
        ALevelSequenceActor* OutActor = nullptr;
        CinePlayer = ULevelSequencePlayer::CreateLevelSequencePlayer(this, Seq, Settings, OutActor);
        CineActor = OutActor;
        if (CineActor && C->bRelativeToPawn && RoadSpline.IsValid() && GetPawn())
        {
            // Keep the authored road frame, but put its origin at the carrier's actual stopped X/Y and feet.
            // Using the spline projection for position leaves a laterally displaced carrier away from the local
            // POV camera; using its yaw instead would rotate the deliberate road-relative scenery shots.
            APawn* Pawn = GetPawn();
            USplineComponent* Spline = RoadSpline.Get();
            const float Key = Spline->FindInputKeyClosestToWorldLocation(Pawn->GetActorLocation());
            const FVector OnSpline = Spline->GetLocationAtSplineInputKey(Key, ESplineCoordinateSpace::World);
            const FVector Tangent = -Spline->GetTangentAtSplineInputKey(Key, ESplineCoordinateSpace::World);
            const FVector Loc = FSaskartaEventLogic::RoadCineOrigin(Pawn->GetActorLocation(), Pawn->GetSimpleCollisionHalfHeight());
            const FRotator Yaw = FSaskartaEventLogic::RoadCineRotation(Tangent);
            CineRoadFrame = FTransform(Yaw, Loc);
            // Sensor-POV shots follow the physical relay eye after the carrier's
            // camera fails. The possessed pawn remains the carrier in that mode.
            AActor* SensorSource = Pawn;
            if (const UWorld* World = GetWorld())
            {
                const USaskartaDroneSequenceSubsystem* Drone = World->GetSubsystem<USaskartaDroneSequenceSubsystem>();
                if (Drone && Drone->IsDroneFeedActive() && IsValid(Drone->GetDroneViewTarget()))
                {
                    SensorSource = Drone->GetDroneViewTarget();
                    bCineSensorFromDrone = true;
                }
            }
            // A historic eye-height guess at local X/Y zero can sit inside the
            // carrier on a slope; capture the selected camera's actual location.
            TArray<UCameraComponent*> Cameras;
            SensorSource->GetComponents(Cameras);
            for (UCameraComponent* Camera : Cameras)
            {
                if (Camera && Camera->IsActive())
                {
                    CineSensorOrigin = Camera->GetComponentLocation();
                    bCineSensorOriginValid = !CineSensorOrigin.ContainsNaN();
                    break;
                }
            }
            if (UDefaultLevelSequenceInstanceData* Data = Cast<UDefaultLevelSequenceInstanceData>(CineActor->DefaultInstanceData))
            {
                CineActor->bOverrideInstanceData = true;
                Data->TransformOrigin = FTransform(Yaw, Loc);
                if (ActiveCineId == FName(TEXT("CIN_19_HATCH")))
                {
                    // The reveal's body and hand contacts were authored against this imported capsule socket.
                    // A yaw-only road frame leaves them outside the pod when its suspension tilts on a slope.
                    ACharacter* Carrier = Cast<ACharacter>(Pawn);
                    USkeletalMeshComponent* Mesh = Carrier ? Carrier->GetMesh() : nullptr;
                    const FName CapsuleRoot(TEXT("capsule_root"));
                    if (Mesh && Mesh->DoesSocketExist(CapsuleRoot))
                    {
                        Data->TransformOrigin = FSaskartaEventLogic::CinematicSocketFrame(
                            Mesh->GetSocketTransform(CapsuleRoot, RTS_World),
                            FVector(-356.4797, 0.0, 30.0239), FRotator(0.0, -90.0, 0.0).Quaternion());
                        UE_LOG(LogSaskartaEvents, Log, TEXT("CIN19 capsule contact frame: %s"),
                            *Data->TransformOrigin.ToHumanReadableString());
                    }
                    else
                    {
                        UE_LOG(LogSaskartaEvents, Warning, TEXT("CIN19 capsule socket unavailable; using road frame"));
                    }
                }
            }
            // PIE check: origin X/Y should be the carrier's stopped position, Z its feet, and yaw the road frame.
            UE_LOG(LogSaskartaEvents, Log, TEXT("cinematic %s: origin (%.0f, %.0f, %.0f) road yaw %.1f, key %.3f (spline z %.0f)"),
                *ActiveCineId.ToString(), Loc.X, Loc.Y, Loc.Z, Yaw.Yaw, Key, OnSpline.Z);
        }
        if (CinePlayer)
        {
            CinePlayer->OnFinished.AddDynamic(this, &USaskartaEventRunner::HandleSequenceFinished);
            CinePlayer->Play();
        }
    }
    else
    {
        UE_LOG(LogSaskartaEvents, Warning, TEXT("cinematic %s: no sequence asset yet; running its cues on the world clock for %.1f s"),
            *ActiveCineId.ToString(), C->DurationS);
    }
    if (FSaskartaEventLogic::AutoLetterbox(*C))
    {
        bCineLetterboxOn = true;
        OnLetterbox.Broadcast(true, FSaskartaEventLogic::LetterboxBlendS);
    }
}

void USaskartaEventRunner::ClearParkedCarrierMotion(bool bStopMovement)
{
    ACharacter* Carrier = Cast<ACharacter>(GetPawn());
    if (!Carrier || !Carrier->FindFunction(SaskartaEvents::NameStopAnimDriver)) return;
    if (bStopMovement)
    {
        Carrier->ConsumeMovementInputVector();
        if (UCharacterMovementComponent* Movement = Carrier->GetCharacterMovement())
            Movement->StopMovementImmediately();
    }
    // Real fields from the installed BP_Saskarta_Carrier graph packet. Stopping
    // AnimTimer alone leaves its native proxy integrating the last supplied speed.
    const TCHAR* Fields[] = { TEXT("MoveX"), TEXT("MoveY"), TEXT("Throttle"), TEXT("PrevThrottle"),
        TEXT("Steer"), TEXT("DriveSpeed"), TEXT("SignedSpeed"), TEXT("PrevSigned"),
        TEXT("DriveAccel"), TEXT("PeakSpeed"), TEXT("StuckTime") };
    for (const TCHAR* Name : Fields)
    {
        if (FNumericProperty* Property = FindFProperty<FNumericProperty>(Carrier->GetClass(), Name))
            if (Property->IsFloatingPoint())
                Property->SetFloatingPointPropertyValue(Property->ContainerPtrToValuePtr<void>(Carrier), 0.0);
    }
    if (USkeletalMeshComponent* Mesh = Carrier->GetMesh())
    {
        if (USaskartaCarrierAnimInstance* Anim = Cast<USaskartaCarrierAnimInstance>(Mesh->GetAnimInstance()))
        {
            Anim->SetMotionInputs(0.f, 0.f, 0.f);
            Anim->Inputs.Accel = 0.f;
            Anim->Inputs.Steer = 0.f;
        }
    }
}

bool USaskartaEventRunner::GetCinematicSensorOffset(float AuthoredEyeHeightCm, FVector& OutOffset) const
{
    if (!bCineSensorOriginValid || !IsCinematicActive() || !FMath::IsFinite(AuthoredEyeHeightCm)) return false;
    OutOffset = CineSensorOrigin - CineRoadFrame.TransformPosition(FVector(0.f, 0.f, AuthoredEyeHeightCm));
    return true;
}

float USaskartaEventRunner::GetCinematicPlaybackSeconds() const
{
    return CinePhase == ESaskartaCinePhase::Playing ? GetCinematicTimeS() : -1.f;
}

float USaskartaEventRunner::GetCinematicTimeS() const
{
    if (CinePlayer)
    {
        return static_cast<float>(CinePlayer->GetCurrentTime().AsSeconds());
    }
    const double Ref = CinePausedAtS >= 0.0 ? CinePausedAtS : Now();
    return static_cast<float>(Ref - CineStartS - CinePausedTotalS);
}

void USaskartaEventRunner::CinematicStep()
{
    const FSaskartaCinematicDef* C = Story ? Story->FindCinematic(ActiveCineId) : nullptr;
    if (!C)
    {
        StopAll();
        return;
    }
    const double T = Now();
    switch (CinePhase)
    {
    case ESaskartaCinePhase::WaitingStop:
    {
        const APawn* Pawn = GetPawn();
        const float Speed = Pawn ? Pawn->GetVelocity().Size() : 0.f;
        if (Speed < FSaskartaEventLogic::StopSpeedCmS || T - CinePhaseStartS > FSaskartaEventLogic::StopTimeoutS)
        {
            StartSequence();
        }
        break;
    }
    case ESaskartaCinePhase::Playing:
    {
        const float TimeS = GetCinematicTimeS();
        TArray<int32> Due;
        FSaskartaEventLogic::CollectDueCues(*C, TimeS, bCinePromptAnswered, NextCue, Due);
        for (const int32 i : Due)
        {
            RunCue(C->Cues[i]);
        }
        const bool bVirtual = CinePlayer == nullptr;
        if (bVirtual && !bCinePromptPending && TimeS >= C->DurationS)
        {
            EndCinematic(false);
        }
        else if (!bVirtual && !bCinePromptPending && T - CineStartS - CinePausedTotalS > C->DurationS + SaskartaEvents::CineTimeoutPadS)
        {
            UE_LOG(LogSaskartaEvents, Warning, TEXT("cinematic %s: no OnFinished after %.0f s; ending it"), *ActiveCineId.ToString(), T - CineStartS);
            EndCinematic(false);
        }
        break;
    }
    case ESaskartaCinePhase::BlendingOut:
        if (T - CinePhaseStartS >= C->BlendOutS)
        {
            FinishBlendOut();
        }
        break;
    default:
        break;
    }
}

void USaskartaEventRunner::RunCue(const FSaskartaEventAction& Cue)
{
    if (!FSaskartaEventLogic::TagsAllow(Cue.RequiresTags, Cue.ExcludesTags, FSaskartaEventLogic::DeriveTags(EnabledTags)))
    {
        return;
    }
    if (Cue.bFirstPlaythroughOnly && bCompletedOnce)
    {
        return;
    }
    if (Cue.Type == ESaskartaActionType::Prompt)
    {
        BeginPrompt(Cue, true);
        if (Cue.bPausesSequence)
        {
            bCinePromptPending = true;
            bCinePromptAnswered = false;
            if (CinePlayer)
            {
                CinePlayer->Pause();
            }
            // Tracked for both paths: the virtual clock and the watchdog exclude the prompt's wait.
            if (CinePausedAtS < 0.0)
            {
                CinePausedAtS = Now();
            }
        }
        return;
    }
    if (Cue.Type == ESaskartaActionType::PlayCinematic)
    {
        UE_LOG(LogSaskartaEvents, Warning, TEXT("cue PlayCinematic %s inside %s ignored"), *Cue.Id.ToString(), *ActiveCineId.ToString());
        return;
    }
    RunImmediate(Cue);
}

void USaskartaEventRunner::HandleSequenceFinished()
{
    if (CinePhase == ESaskartaCinePhase::Playing && !bCineSkipped)
    {
        EndCinematic(false);
    }
}

bool USaskartaEventRunner::CanSkipCurrentCinematic() const
{
    const FSaskartaCinematicDef* C = Story ? Story->FindCinematic(ActiveCineId) : nullptr;
    if (!C || CinePhase != ESaskartaCinePhase::Playing || bCinePromptPending)
    {
        return false;
    }
    return FSaskartaEventLogic::CanSkip(C->SkipRule, SeenCinematics.Contains(ActiveCineId), GetCinematicTimeS(), C->SkipMinS,
        SaskartaEvents::CVarAllowSkipAll.GetValueOnGameThread() != 0);
}

void USaskartaEventRunner::SkipCurrentCinematic()
{
    if (!CanSkipCurrentCinematic())
    {
        return;
    }
    UE_LOG(LogSaskartaEvents, Log, TEXT("cinematic %s: skipped at %.1f s"), *ActiveCineId.ToString(), GetCinematicTimeS());
    EndCinematic(true);
}

void USaskartaEventRunner::PauseCinematic(bool bPause)
{
    if (CinePhase != ESaskartaCinePhase::Playing || bCinePromptPending)
    {
        return;
    }
    if (CinePlayer)
    {
        if (bPause) CinePlayer->Pause(); else CinePlayer->Play();
    }
    // Paused time is tracked for both paths: the virtual clock and the watchdog exclude it.
    if (bPause && CinePausedAtS < 0.0)
    {
        CinePausedAtS = Now();
    }
    else if (!bPause && CinePausedAtS >= 0.0)
    {
        CinePausedTotalS += Now() - CinePausedAtS;
        CinePausedAtS = -1.0;
    }
}

void USaskartaEventRunner::PollSkip()
{
    const FSaskartaCinematicDef* C = Story ? Story->FindCinematic(ActiveCineId) : nullptr;
    APlayerController* PC = GetPC();
    if (!C || !PC || !CanSkipCurrentCinematic())
    {
        if (SkipHeldS > 0.f)
        {
            SkipHeldS = 0.f;
            OnSkipProgress.Broadcast(0.f);
        }
        return;
    }
    if (C->SkipRule == ESaskartaSkipRule::AnyKeyAfter)
    {
        if (PC->WasInputKeyJustPressed(EKeys::SpaceBar) || PC->WasInputKeyJustPressed(EKeys::Enter)
            || PC->WasInputKeyJustPressed(EKeys::LeftMouseButton) || PC->WasInputKeyJustPressed(EKeys::Gamepad_FaceButton_Bottom)
            || PC->WasInputKeyJustPressed(EKeys::Gamepad_FaceButton_Right))
        {
            SkipCurrentCinematic();
        }
        return;
    }
    const bool bHeld = PC->IsInputKeyDown(EKeys::SpaceBar) || PC->IsInputKeyDown(EKeys::Gamepad_FaceButton_Right);
    if (bHeld)
    {
        SkipHeldS += FSaskartaEventLogic::SkipPollS;
        OnSkipProgress.Broadcast(FMath::Clamp(SkipHeldS / FSaskartaEventLogic::SkipHoldS, 0.f, 1.f));
        if (SkipHeldS >= FSaskartaEventLogic::SkipHoldS)
        {
            SkipHeldS = 0.f;
            OnSkipProgress.Broadcast(0.f);
            SkipCurrentCinematic();
        }
    }
    else if (SkipHeldS > 0.f)
    {
        SkipHeldS = 0.f;
        OnSkipProgress.Broadcast(0.f);
    }
}

AActor* USaskartaEventRunner::ResolveCinematicHandback(const FSaskartaCinematicDef& Cinematic) const
{
    // Story cameras may still return to CarrierPOV after the sensor is destroyed.
    // Keep the relay eye until the human reveal takes ownership of the view.
    const bool bCarrierView = Cinematic.HandBack == SaskartaEvents::NameCarrierPOV
        || Cinematic.HandBack == SaskartaEvents::NameDroneCam;
    const UWorld* World = GetWorld();
    const USaskartaDroneSequenceSubsystem* Drone = World
        ? World->GetSubsystem<USaskartaDroneSequenceSubsystem>() : nullptr;
    if (GetFlowState() == SaskartaEvents::NameHuman && Drone && IsValid(Drone->GetHumanDroneViewTarget()))
        return Drone->GetHumanDroneViewTarget();
    if (bCarrierView && GetFlowState() != SaskartaEvents::NameHuman
        && Drone && Drone->IsDroneFeedActive() && IsValid(Drone->GetDroneViewTarget()))
    {
        return Drone->GetDroneViewTarget();
    }
    return GetPawn();
}

FBox USaskartaEventRunner::CarrierCameraBounds()
{
    ACharacter* Carrier = CameraCollisionCarrier.Get();
    if (!IsValid(Carrier) || Carrier->IsActorBeingDestroyed())
    {
        Carrier = nullptr;
        if (UWorld* World = GetWorld())
        {
            for (TActorIterator<ACharacter> It(World); It; ++It)
            {
                if (It->GetClass()->GetName().StartsWith(TEXT("BP_Saskarta_Carrier")))
                { Carrier = *It; CameraCollisionCarrier = Carrier; break; }
            }
        }
    }
    FBox Bounds(ForceInit);
    if (!Carrier) return Bounds;
    TInlineComponentArray<UMeshComponent*> Meshes(Carrier);
    for (UMeshComponent* Mesh : Meshes)
    {
        if (Mesh && Mesh->IsRegistered() && Mesh->IsVisible() && !Mesh->bHiddenInGame)
            Bounds += Mesh->CalcBounds(Mesh->GetComponentTransform()).GetBox();
    }
    // Conservative near-lens clearance, derived from current mesh bounds.
    return Bounds.IsValid ? Bounds.ExpandBy(FMath::Max(12.f, GNearClippingPlane)) : Bounds;
}

FVector USaskartaEventRunner::ConstrainCarrierCameraPath(const FVector& From, const FVector& To)
{
    if (From.ContainsNaN() || To.ContainsNaN()) return From;
    const FBox Bounds = CarrierCameraBounds();
    return Bounds.IsValid ? SaskartaCineClearance::OutsidePath(Bounds, From, To) : To;
}

void USaskartaEventRunner::SetCollisionSafeViewTarget(APlayerController* PC, AActor* Target, float BlendS)
{
    if (!PC || !Target) return;
    FMinimalViewInfo Destination;
    Target->CalcCamera(0.f, Destination);
    const FVector From = bHaveSafeCineView ? LastSafeCineView :
        (PC->PlayerCameraManager ? PC->PlayerCameraManager->GetCameraLocation() : Destination.Location);
    const FBox Bounds = CarrierCameraBounds();
    int32 Axis = INDEX_NONE;
    double Face = 0.0;
    const bool bBlocked = Bounds.IsValid && SaskartaCineClearance::EntryFace(Bounds, From, Destination.Location, Axis, Face);
    if (bBlocked || BlendS <= 0.f)
    {
        PC->SetViewTarget(Target); // preserve the real endpoint; never fly through the pod to reach it
        if (bBlocked) UE_LOG(LogSaskartaEvents, Log, TEXT("camera handback: blocked carrier crossing; cut to %s"), *Target->GetName());
    }
    else PC->SetViewTargetWithBlend(Target, BlendS);
    bHaveSafeCineView = false;
}

void USaskartaEventRunner::ConstrainCinematicView(APlayerController* Player, FMinimalViewInfo& View)
{
    if (!IsCinematicActive() || Player != GetPC() || View.Location.ContainsNaN()) return;
    // Exempt only the actual intentional carrier sensor endpoint, never an entire
    // blended path. Drone sensor shots remain exterior and receive clearance.
    UCameraComponent* ActiveCamera = CinePlayer ? CinePlayer->GetActiveCameraComponent() : nullptr;
    const bool bSensorShot = ActiveCamera && ActiveCamera->GetOwner()->IsA<ASaskartaSensorCamera>();
    const bool bDriverEndpoint = !bCineSensorFromDrone && bCineSensorOriginValid &&
        (bSensorShot || Player->GetViewTarget() == GetPawn()) &&
        View.Location.Equals(CineSensorOrigin, 1.0);
    if (bDriverEndpoint)
    {
        bHaveSafeCineView = false;
        return;
    }
    const FBox Bounds = CarrierCameraBounds();
    if (!Bounds.IsValid) return;
    const FVector Wanted = View.Location;
    View.Location = SaskartaCineClearance::OutsidePath(Bounds,
        bHaveSafeCineView ? LastSafeCineView : Wanted, Wanted);
    if (!View.Location.Equals(Wanted, 0.01) && !bReportedCineClearance)
    {
        bReportedCineClearance = true;
        UE_LOG(LogSaskartaEvents, Warning, TEXT("cinematic %s: camera path intersects carrier render bounds; clearance applied (authored shot needs review)"), *ActiveCineId.ToString());
    }
    // Keep rotation, FOV, postprocess and audio untouched. This is the final
    // viewpoint after both sequence easing and explicit view-target blending.
    LastSafeCineView = View.Location;
    bHaveSafeCineView = true;
}

void USaskartaEventRunner::EndCinematic(bool bSkipped)
{
    const FSaskartaCinematicDef* C = Story ? Story->FindCinematic(ActiveCineId) : nullptr;
    if (!C || CinePhase == ESaskartaCinePhase::None || CinePhase == ESaskartaCinePhase::BlendingOut)
    {
        return;
    }
    bCineSkipped = bSkipped;
    if (UWorld* World = GetWorld())
    {
        World->GetTimerManager().ClearTimer(SkipTimer);
    }
    OnSkipProgress.Broadcast(0.f);

    if (bSkipped)
    {
        if (CineVoiceComp && CineVoiceComp->IsPlaying())
        {
            CineVoiceComp->FadeOut(0.2f, 0.f);
        }
        LineEndS = -1.0;
        HideStorySubtitle();
        if (ShouldKeepStationPlaying())
        {
            LastVoiceEndS = Now();
            VoiceBusyUntilS = Now();
            BroadcastBusy(false, 0.f, false); // release any carrier-cue duck on skip
        }
        FSaskartaEventLogic::CollectKeepOnSkip(*C, NextCue, PendingKeepLines);
        if (bPromptActive)
        {
            bPromptActive = false;
            OnPromptHide.Broadcast();
            if (UWorld* World = GetWorld())
            {
                World->GetTimerManager().ClearTimer(PromptTimer);
            }
        }
        if (CinePlayer)
        {
            CinePlayer->GoToEndAndStop();
        }
    }

    if (ActiveCineId == FName(TEXT("CIN_24_TRANSMISSION")))
    {
        // The authored hiss stop sits at the sequence endpoint: OnFinished can
        // arrive before the next cue poll, and a skip never reaches that cue.
        // Release only this scene's audio; the title score keeps its cursor.
        StopSfx(FName(TEXT("SFX_OpenChannelHiss")), bSkipped ? 0.2f : 0.f);
        StopSfx(FName(TEXT("BREATH_06")), 0.1f);
    }

    APawn* PawnBeforeFinalState = GetPawn();
    bool bSaveHumanAfterHandoff = false;
    for (const FSaskartaEventAction& A : C->FinalState)
    {
        if (FSaskartaEventLogic::TagsAllow(A.RequiresTags, A.ExcludesTags, FSaskartaEventLogic::DeriveTags(EnabledTags))
            && !(A.bFirstPlaythroughOnly && bCompletedOnce))
        {
            if (ActiveCineId == FName(TEXT("CIN_19_HATCH")) && A.Type == ESaskartaActionType::Checkpoint
                && A.Id == FName(TEXT("CP4_HUMAN")))
            {
                bSaveHumanAfterHandoff = true;
                continue; // Save the native grounded handoff, not the earlier Blueprint estimate.
            }
            RunImmediate(A);
        }
    }
    if (ActiveCineId == FName(TEXT("CIN_19_HATCH")))
    {
        if (UWorld* World = GetWorld())
        {
            if (USaskartaCollapseStageSubsystem* Collapse = World->GetSubsystem<USaskartaCollapseStageSubsystem>())
            {
                if (Collapse->EnsureHumanHandoff(GetPC(), PawnBeforeFinalState))
                {
                    // The Blueprint walk hook may have run against the old carrier pawn.
                    CallHook(GetPC(), FName(TEXT("StartHumanWalk")), {}, {});
                }
            }
        }
    }
    UClass* HumanClassAfterHandoff = bSaveHumanAfterHandoff ? SaskartaEvents::TravellerClass() : nullptr;
    if (HumanClassAfterHandoff && GetFlowState() == SaskartaEvents::NameHuman && GetPawn()
        && GetPawn()->IsA(HumanClassAfterHandoff))
    {
        SaveCheckpoint(FName(TEXT("CP4_HUMAN")));
    }
    if (bCineLetterboxOn)
    {
        bCineLetterboxOn = false;
        OnLetterbox.Broadcast(false, FSaskartaEventLogic::LetterboxBlendS);
    }

    // The camera-cut track's ease-out blends back while it plays; after a stop (skip) blend explicitly.
    APlayerController* PC = GetPC();
    AActor* ViewTarget = ResolveCinematicHandback(*C);
    if (PC && ViewTarget && C->HandBack != SaskartaEvents::NameNone && PC->GetViewTarget() != ViewTarget)
    {
        SetCollisionSafeViewTarget(PC, ViewTarget, C->BlendOutS);
    }
    CinePhase = ESaskartaCinePhase::BlendingOut;
    CinePhaseStartS = Now();
    UE_LOG(LogSaskartaEvents, Log, TEXT("cinematic %s: %s, final state run, blending out %.1f s"),
        *ActiveCineId.ToString(), bSkipped ? TEXT("skipped") : TEXT("finished"), C->BlendOutS);
    if (C->BlendOutS <= 0.f)
    {
        FinishBlendOut();
    }
}

void USaskartaEventRunner::FinishBlendOut()
{
    const FSaskartaCinematicDef* C = Story ? Story->FindCinematic(ActiveCineId) : nullptr;
    const bool bKeepStationPlaying = ShouldKeepStationPlaying();
    const FName Id = ActiveCineId;
    UnlockInput();
    if (UWorld* World = GetWorld())
    {
        World->GetTimerManager().ClearTimer(CineWatchdogTimer);
    }
    if (C && C->HandBack != SaskartaEvents::NameNone)
    {
        const bool bFinalStarts = C->FinalState.ContainsByPredicate([](const FSaskartaEventAction& A)
        {
            return A.Type == ESaskartaActionType::CallHook && A.Id == SaskartaEvents::NameStartAnimDriver;
        });
        if (!bFinalStarts && (C->HandBack == SaskartaEvents::NameCarrierPOV
            || C->HandBack == SaskartaEvents::NameDroneCam))
        {
            CallHook(GetPawn(), SaskartaEvents::NameStartAnimDriver, {}, {});
        }
    }
    if (CinePlayer)
    {
        CinePlayer->OnFinished.RemoveDynamic(this, &USaskartaEventRunner::HandleSequenceFinished);
        if (CinePlayer->IsPlaying())
        {
            CinePlayer->Stop();
        }
    }
    if (CineActor)
    {
        CineActor->Destroy();
    }
    CinePlayer = nullptr;
    CineActor = nullptr;
    // Destroying a sequence can restore its pre-animated pawn camera. Reassert
    // the resolved view only after its spawnables and camera cuts are released.
    if (C && C->HandBack != SaskartaEvents::NameNone)
    {
        APlayerController* PC = GetPC();
        AActor* ViewTarget = ResolveCinematicHandback(*C);
        if (PC && ViewTarget && PC->GetViewTarget() != ViewTarget)
        {
            PC->SetViewTarget(ViewTarget);
        }
    }
    CinePhase = ESaskartaCinePhase::None;
    ActiveCineId = NAME_None;
    bCinePromptPending = false;
    SeenCinematics.Add(Id);
    SaveProfile();
    if (!C || !bKeepStationPlaying)
    {
        LastVoiceEndS = Now();
        BroadcastBusy(false, 0.f, true);
    }
    else if (LineEndS <= Now())
    {
        BroadcastBusy(false, 0.f, true);
    }
    // A continuous scene's last spoken cue can finish after the camera handback.
    // Its normal line-end release owns the duck; the camera must not reset its clock.
    OnCinematicFinished.Broadcast(Id);
    UE_LOG(LogSaskartaEvents, Log, TEXT("cinematic %s: handed back"), *Id.ToString());
}

void USaskartaEventRunner::PlayCinematicById(FName CinematicId)
{
    if (bHumanGroundingActive || bCarrierGroundingActive) return;
    BeginCinematic(CinematicId);
}

void USaskartaEventRunner::CineWatchdog()
{
    if (CinePhase == ESaskartaCinePhase::None)
    {
        if (UWorld* World = GetWorld())
        {
            World->GetTimerManager().ClearTimer(CineWatchdogTimer);
        }
        return;
    }
    const FSaskartaCinematicDef* C = Story ? Story->FindCinematic(ActiveCineId) : nullptr;
    const double T = Now();
    const double PausedNowS = CinePausedAtS >= 0.0 ? T - CinePausedAtS : 0.0;
    double ActiveS = 0.0;
    float BudgetS = 0.f;
    switch (CinePhase)
    {
    case ESaskartaCinePhase::WaitingStop:
        ActiveS = T - CinePhaseStartS;
        BudgetS = FSaskartaEventLogic::StopTimeoutS;
        break;
    case ESaskartaCinePhase::Playing:
        ActiveS = T - CineStartS - CinePausedTotalS - PausedNowS;
        BudgetS = C ? C->DurationS : 0.f;
        break;
    case ESaskartaCinePhase::BlendingOut:
        ActiveS = T - CinePhaseStartS;
        BudgetS = C ? C->BlendOutS : 0.f;
        break;
    default:
        break;
    }
    if (FSaskartaEventLogic::CineWatchdogExpired(ActiveS, BudgetS))
    {
        UE_LOG(LogSaskartaEvents, Warning, TEXT("cinematic %s: watchdog: phase %d ran %.1f s (budget %.1f + %.0f s); ending it and releasing input"),
            *ActiveCineId.ToString(), static_cast<int32>(CinePhase), ActiveS, BudgetS, FSaskartaEventLogic::CineWatchdogPadS);
        ForceReleaseInput();
    }
}

void USaskartaEventRunner::ForceReleaseInput()
{
    if (bCarrierGroundingActive)
    {
        FailCarrierGrounding(TEXT("manual release before ground was ready"));
        return;
    }
    if (bHumanGroundingActive)
    {
        FailHumanGrounding(TEXT("manual release before ground was ready"));
        return;
    }
    if (CinePhase == ESaskartaCinePhase::WaitingStop || CinePhase == ESaskartaCinePhase::Playing)
    {
        if (bCinePromptPending || bPromptActive)
        {
            bCinePromptPending = false;
            bCinePromptAnswered = true;
            if (bPromptActive)
            {
                bPromptActive = false;
                OnPromptHide.Broadcast();
            }
        }
        if (Story && Story->FindCinematic(ActiveCineId))
        {
            EndCinematic(false); // runs the final state (EnterPlaying, the checkpoint) and starts the blend-out
        }
    }
    if (CinePhase != ESaskartaCinePhase::None)
    {
        FinishBlendOut(); // unlocks, restarts the carrier's anim driver, broadcasts finished
    }
    EndGlance();
    const bool bHeld = MoveLocks > 0 || LookLocks > 0;
    UnlockInput();
    if (UWorld* World = GetWorld())
    {
        World->GetTimerManager().ClearTimer(CineWatchdogTimer);
    }
    UE_LOG(LogSaskartaEvents, Log, TEXT("input released (runner locks held: %d)"), bHeld ? 1 : 0);
}

// ============================================================================ glance and prompt

void USaskartaEventRunner::BeginGlance(FName GlanceId, const FSaskartaEventAction& Action)
{
    const FSaskartaGlanceDef* G = Story ? Story->FindGlance(GlanceId) : nullptr;
    const FName Tag = G ? G->TargetTag : Action.TargetTag;
    AActor* Target = ResolveTarget(Tag);
    APlayerController* PC = GetPC();
    if (!Target || !PC || Tag.IsNone())
    {
        UE_LOG(LogSaskartaEvents, Warning, TEXT("glance %s: no target tagged %s"), *GlanceId.ToString(), *Tag.ToString());
        return;
    }
    EndGlance();
    GlanceTarget = Target;
    GlanceStartRot = PC->GetControlRotation();
    GlanceStartS = Now();
    GlanceEaseS = G ? FMath::Max(0.05f, G->EaseInS) : FMath::Max(0.05f, Action.DurationS);
    GlanceHoldS = G ? G->HoldS : 0.f;
    bGlanceActive = true;
    // The glance's own locks, released by EndGlance alone (not the runner's other locks).
    bGlanceMoveLocked = G && G->bLockMove;
    if (bGlanceMoveLocked)
    {
        PC->SetIgnoreMoveInput(true);
    }
    PC->SetIgnoreLookInput(true);
    bGlanceLookLocked = true;
    if (UWorld* World = GetWorld())
    {
        World->GetTimerManager().SetTimer(GlanceTimer, this, &USaskartaEventRunner::GlanceTick, FSaskartaEventLogic::GlanceTickS, true);
    }
}

void USaskartaEventRunner::GlanceTick()
{
    APlayerController* PC = GetPC();
    APawn* Pawn = GetPawn();
    AActor* Target = GlanceTarget.Get();
    if (!bGlanceActive || !PC || !Pawn || !Target)
    {
        EndGlance();
        return;
    }
    // A real look input cancels the glance, so the player is never fought.
    float MX = 0.f, MY = 0.f;
    PC->GetInputMouseDelta(MX, MY);
    const float Stick = FMath::Max(FMath::Abs(PC->GetInputAnalogKeyState(EKeys::Gamepad_RightX)), FMath::Abs(PC->GetInputAnalogKeyState(EKeys::Gamepad_RightY)));
    if (Stick > 0.5f || FMath::Abs(MX) + FMath::Abs(MY) > 2.f)
    {
        EndGlance();
        return;
    }
    const double Elapsed = Now() - GlanceStartS;
    const FRotator Want = (Target->GetActorLocation() - Pawn->GetPawnViewLocation()).Rotation();
    if (Elapsed <= GlanceEaseS)
    {
        const float A = SaskartaEvents::Smoothstep(static_cast<float>(Elapsed / GlanceEaseS));
        const FQuat Q = FQuat::Slerp(GlanceStartRot.Quaternion(), Want.Quaternion(), A);
        FRotator R = Q.Rotator();
        R.Roll = 0.f;
        PC->SetControlRotation(R);
    }
    else if (Elapsed <= GlanceEaseS + GlanceHoldS)
    {
        PC->SetControlRotation(FRotator(Want.Pitch, Want.Yaw, 0.f));
    }
    else
    {
        EndGlance();
    }
}

void USaskartaEventRunner::EndGlance()
{
    if (UWorld* World = GetWorld())
    {
        World->GetTimerManager().ClearTimer(GlanceTimer);
    }
    if (!bGlanceActive)
    {
        return;
    }
    bGlanceActive = false;
    GlanceTarget.Reset();
    if (APlayerController* PC = GetPC())
    {
        if (bGlanceMoveLocked) PC->SetIgnoreMoveInput(false);
        if (bGlanceLookLocked) PC->SetIgnoreLookInput(false);
    }
    bGlanceMoveLocked = false;
    bGlanceLookLocked = false;
}

void USaskartaEventRunner::BeginPrompt(const FSaskartaEventAction& Action, bool bFromCue)
{
    bPromptActive = true;
    bPromptFromCue = bFromCue;
    PromptNextBeat = Action.NextBeat;
    // A key held while the prompt appears must be released before it can answer this prompt.
    ReadPromptKeys(bPromptEWasDown, bPromptGamepadWasDown);
    OnPromptShow.Broadcast(Action.Text);
    // Typed onto the CRT when the boot-log black covers the caption; re-shown while unanswered.
    NotePromptShown(Action.Text);
    UE_LOG(LogSaskartaEvents, Log, TEXT("prompt shown: next beat %s"), *PromptNextBeat.ToString());
    if (UWorld* World = GetWorld())
    {
        World->GetTimerManager().SetTimer(PromptTimer, this, &USaskartaEventRunner::PollPrompt, FSaskartaEventLogic::PromptPollS, true);
    }
}

void USaskartaEventRunner::PollPrompt()
{
    APlayerController* PC = GetPC();
    if (!bPromptActive || !PC)
    {
        return;
    }
    // WasInputKeyJustPressed lasts one frame, so a timer can miss it. Track held-key edges instead.
    // E / Enter (keyboard) and gamepad A; ReadPromptKeys also reads the keyboard directly on Windows.
    bool bEDown = false;
    bool bGamepadDown = false;
    ReadPromptKeys(bEDown, bGamepadDown);
    const bool bPressed = FSaskartaPromptLogic::IsPressEdge(bEDown, bPromptEWasDown)
        || FSaskartaPromptLogic::IsPressEdge(bGamepadDown, bPromptGamepadWasDown);
    bPromptEWasDown = bEDown;
    bPromptGamepadWasDown = bGamepadDown;
    // 2026-10-05: the last choice. At the transmitter, Q / gamepad B keeps silent (B24S_SILENCE) instead.
    {
        static bool bQWasDown = true;
        const bool bQDown = PC->IsInputKeyDown(EKeys::Q) || PC->IsInputKeyDown(EKeys::Gamepad_FaceButton_Right);
        const bool bQPressed = bQDown && !bQWasDown;
        bQWasDown = bQDown;
        if (bQPressed && PromptNextBeat == FName(TEXT("B24_TRANSMISSION")))
        {
            PromptNextBeat = FName(TEXT("B24S_SILENCE"));
            AnswerPrompt();
            return;
        }
    }
    if (bPressed)
    {
        AnswerPrompt();
        return;
    }
    TickPromptReminder();
}

void USaskartaEventRunner::AnswerPrompt()
{
    if (UWorld* World = GetWorld())
    {
        World->GetTimerManager().ClearTimer(PromptTimer);
    }
    bPromptActive = false;
    OnPromptHide.Broadcast();
    if (bPromptFromCue && bCinePromptPending)
    {
        bCinePromptPending = false;
        bCinePromptAnswered = true;
        if (CinePlayer)
        {
            CinePlayer->Play();
        }
        if (CinePausedAtS >= 0.0)
        {
            CinePausedTotalS += Now() - CinePausedAtS;
            CinePausedAtS = -1.0;
        }
    }
    const FName Next = PromptNextBeat;
    PromptNextBeat = NAME_None;
    UE_LOG(LogSaskartaEvents, Log, TEXT("prompt answered: next beat %s"), *Next.ToString());
    if (!Next.IsNone())
    {
        // The player asked for it: a one-shot flag left by a restore or a GoTo must not swallow the chain.
        const bool bAlreadyFired = FiredBeats.Contains(Next);
        if (bAlreadyFired)
        {
            UE_LOG(LogSaskartaEvents, Warning, TEXT("prompt: %s was already marked fired; forcing it so the chain goes on"), *Next.ToString());
        }
        FireBeat(Next, bAlreadyFired);
    }
}

// ============================================================================ stop, save, restore

void USaskartaEventRunner::SetPresentationMode(FName Mode, bool bOn)
{
    if (Mode.IsNone() || ActiveModes.Contains(Mode) == bOn)
    {
        return;
    }
    if (bOn) ActiveModes.Add(Mode); else ActiveModes.Remove(Mode);
    OnModeChanged.Broadcast(Mode, bOn);
}

void USaskartaEventRunner::StopAll()
{
    ClearCarrierGroundingHold();
    ClearHumanGroundingHold();
    bHaveSafeCineView = false;
    bReportedCineClearance = false;
    CameraCollisionCarrier.Reset();
    // Title/reset can change FlowState before reaching this cleanup. Use the
    // live pawn's hook, not flow or a PC cast, and never load a class at startup.
    APawn* WalkingPawn = GetPawn();
    if (IsValid(WalkingPawn) && !WalkingPawn->IsActorBeingDestroyed()
        && WalkingPawn->FindFunction(TEXT("StopWalk")))
    {
        CallHook(WalkingPawn, TEXT("StopWalk"), {}, {});
    }
    // Aborting a scene does not run its final cues. Release the runner's own
    // hiss/hut/breath effects before a reset can replace their tracked IDs.
    // RadioStation owns the broadcast and title score outside this map.
    TArray<TWeakObjectPtr<UAudioComponent>> SfxToStop;
    TrackedSfx.GenerateValueArray(SfxToStop);
    TrackedSfx.Reset();
    for (const TWeakObjectPtr<UAudioComponent>& WeakComp : SfxToStop)
    {
        if (UAudioComponent* Comp = WeakComp.Get()) Comp->Stop();
    }
    // Preserve the busy kind before clearing CinePhase; the station must release
    // the cinematic suspension even when a checkpoint restore aborts the sequence.
    const bool bWasCinematic = IsCinematicActive();
    const bool bKeptStationPlaying = ShouldKeepStationPlaying();
    bStormPanicActive = false;
    NextStormPanicS = Now() + .75;
    StormPanicLoad.Reset();
    {
        TArray<FSaskartaHudOutput> HudOut;
        HudLane.Reset(HudOut);
        EmitHud(HudOut);
        if (UWorld* World = GetWorld())
        {
            World->GetTimerManager().ClearTimer(HudTimer);
        }
    }
    const TArray<FName> OldModes = ActiveModes.Array();
    ActiveModes.Reset();
    for (const FName& Mode : OldModes)
    {
        OnModeChanged.Broadcast(Mode, false);
    }
    // A cinematic can be aborted before its first SetMode cue; restore the
    // staged mesh fall and destroy any pending swarm even when no mode was on.
    if (UWorld* World = GetWorld())
    {
        if (USaskartaDroneSequenceSubsystem* Drone = World->GetSubsystem<USaskartaDroneSequenceSubsystem>())
        {
            Drone->StopSequence();
        }
    }
    Queue.Reset();
    if (bHasRunning)
    {
        bHasRunning = false;
        RunningBeatId = NAME_None;
        RunningWait = ESaskartaRunWait::None;
    }
    if (VoiceComp && VoiceComp->IsPlaying())
    {
        VoiceComp->Stop();
    }
    if (CineVoiceComp && CineVoiceComp->IsPlaying())
    {
        CineVoiceComp->Stop();
    }
    VoiceComp = nullptr;
    CineVoiceComp = nullptr;
    LineEndS = -1.0;
    VoiceBusyUntilS = 0.0;
    PendingKeepLines.Reset();
    if (CinePlayer)
    {
        CinePlayer->OnFinished.RemoveDynamic(this, &USaskartaEventRunner::HandleSequenceFinished);
        CinePlayer->Stop();
    }
    if (CineActor)
    {
        CineActor->Destroy();
    }
    CinePlayer = nullptr;
    CineActor = nullptr;
    if (CinePhase != ESaskartaCinePhase::None)
    {
        CinePhase = ESaskartaCinePhase::None;
        ActiveCineId = NAME_None;
        if (bCineLetterboxOn)
        {
            bCineLetterboxOn = false;
            OnLetterbox.Broadcast(false, 0.f);
        }
    }
    EndGlance();
    if (bPromptActive)
    {
        bPromptActive = false;
        OnPromptHide.Broadcast();
    }
    if (UWorld* World = GetWorld())
    {
        World->GetTimerManager().ClearTimer(PromptTimer);
        World->GetTimerManager().ClearTimer(SkipTimer);
        World->GetTimerManager().ClearTimer(CineWatchdogTimer);
    }
    UnlockInput();
    HideStorySubtitle();
    HideStationSubtitle();
    if (bStoryBusyBroadcast)
    {
        BroadcastBusy(false, 0.f, bWasCinematic && !bKeptStationPlaying);
    }
}

void USaskartaEventRunner::LoadProfile()
{
    if (USaskartaSaveGame* P = Cast<USaskartaSaveGame>(UGameplayStatics::LoadGameFromSlot(USaskartaSaveGame::ProfileSlot, 0)))
    {
        SeenCinematics.Append(P->SeenCinematics);
        bCompletedOnce = P->bCompletedOnce;
    }
}

void USaskartaEventRunner::SaveProfile()
{
    USaskartaSaveGame* P = Cast<USaskartaSaveGame>(UGameplayStatics::CreateSaveGameObject(USaskartaSaveGame::StaticClass()));
    if (!P)
    {
        return;
    }
    P->SeenCinematics = SeenCinematics.Array();
    P->bCompletedOnce = bCompletedOnce;
    UGameplayStatics::SaveGameToSlot(P, USaskartaSaveGame::ProfileSlot, 0);
}

USaskartaSaveGame* USaskartaEventRunner::CreateCheckpointSnapshot(FName CheckpointId, bool bExactCarrierPose)
{
    // Never persist an ungrounded/incomplete Continue destination.
    if (bHumanGroundingActive || bCarrierGroundingActive) return nullptr;
    USaskartaSaveGame* S = Cast<USaskartaSaveGame>(UGameplayStatics::CreateSaveGameObject(USaskartaSaveGame::StaticClass()));
    if (!S)
    {
        return nullptr;
    }
    S->CheckpointId = CheckpointId;
    S->HighWaterUeM = HighWaterUeM;
    S->FiredBeats = FiredBeats.Array();
    S->FlowState = GetFlowState();
    S->ActiveModes = ActiveModes.Array();
    S->LastLook = LastLook;
    S->LastFogMultiplier = LastFog;
    S->Revealed = Revealed;
    if (S->IsHumanCheckpoint() && GetPawn() && GetPC())
    {
        ACharacter* Carrier = SaskartaEvents::EndingCarrier(GetWorld());
        UClass* HumanClass = SaskartaEvents::TravellerClass();
        if (HumanClass && GetPawn()->IsA(HumanClass))
        {
            S->bHasHumanPose = true;
            S->HumanPose = GetPawn()->GetActorTransform();
            S->HumanViewRotation = GetPC()->GetControlRotation();
            if (Carrier)
            {
                S->bHasHumanCarrierPose = true;
                S->HumanCarrierPose = Carrier->GetActorTransform();
            }
        }
    }
    if (bExactCarrierPose && !S->IsHumanCheckpoint() && GetPawn() && GetPC())
    {
        S->bHasExactCarrierPose = true;
        S->CarrierPose = GetPawn()->GetActorTransform();
        S->CarrierViewRotation = GetPC()->GetControlRotation();
        S->CheckpointRoadM = CurrentRoadM;
    }
    USaskartaSaveGame::OnWritingRun.Broadcast(GetWorld(), S); // RADIOSHOW: the station adds the show state
    return S;
}

bool USaskartaEventRunner::SaveCheckpoint(FName CheckpointId)
{
    USaskartaSaveGame* S = CreateCheckpointSnapshot(CheckpointId);
    if (!S) return false;
    const bool bOk = UGameplayStatics::SaveGameToSlot(S, USaskartaSaveGame::RunSlot, 0);
    SaveProfile();
    UE_LOG(LogSaskartaEvents, Log, TEXT("checkpoint %s saved (%s)"), *CheckpointId.ToString(), bOk ? TEXT("ok") : TEXT("FAILED"));
    return bOk;
}

bool USaskartaEventRunner::TeleportToRoadM(float RoadM)
{
    APawn* Pawn = GetPawn();
    APlayerController* PC = GetPC();
    if (!Story || !Pawn || !PC || !ResolveRoad())
    {
        return false;
    }
    USplineComponent* Spline = RoadSpline.Get();
    const float UeM = FSaskartaEventLogic::UeMFromRoadM(Story->RoadMToUeM, RoadM);
    if (UeM < 0.f)
    {
        return false;
    }
    const float DistCm = UeM * 100.f;
    const FVector Loc = Spline->GetLocationAtDistanceAlongSpline(DistCm, ESplineCoordinateSpace::World);
    const FVector Forward = -Spline->GetTangentAtDistanceAlongSpline(DistCm, ESplineCoordinateSpace::World);
    const float HalfHeight = Pawn->GetSimpleCollisionHalfHeight();
    Pawn->SetActorLocation(Loc + FVector(0.f, 0.f, HalfHeight + 20.f), false, nullptr, ETeleportType::TeleportPhysics);
    PC->SetControlRotation(FRotator(0.f, Forward.Rotation().Yaw, 0.f));
    HighWaterUeM = UeM;
    CurrentUeM = UeM;
    CurrentRoadM = RoadM;
    return true;
}

bool USaskartaEventRunner::GoToRoadM(float RoadM)
{
    if (!Story || !TeleportToRoadM(RoadM))
    {
        UE_LOG(LogSaskartaEvents, Warning, TEXT("GoTo %.0f: no road, pawn or story"), RoadM);
        return false;
    }
    FSaskartaEventLogic::MarkFiredUpTo(Story->Beats, HighWaterUeM, FiredBeats);
    RebuildHudColumn();
    UE_LOG(LogSaskartaEvents, Log, TEXT("GoTo road %.0f m (UE %.0f m); %d beats marked fired"), RoadM, HighWaterUeM, FiredBeats.Num());
    return true;
}

bool USaskartaEventRunner::RestoreFromSave()
{
    USaskartaSaveGame* S = Cast<USaskartaSaveGame>(UGameplayStatics::LoadGameFromSlot(USaskartaSaveGame::RunSlot, 0));
    return RestoreCheckpointSnapshot(S);
}

void USaskartaEventRunner::BeginCarrierGroundingHold(ACharacter* Carrier, bool bExactPose)
{
    ClearCarrierGroundingHold();
    bCarrierGroundingActive = true;
    bCarrierGroundingExactPose = bExactPose;
    CarrierGroundingPawn = Carrier;
    CarrierGroundingController = GetPC();
    CarrierGroundingPose = Carrier->GetActorTransform();
    CarrierGroundingLastPollS = Now();
    CarrierGroundingActiveElapsedS = 0.0;
    CarrierGroundingReadyPolls = 0;
    CarrierGroundingLastReadyFrame = MAX_uint64;
    UCharacterMovementComponent* CarrierMovement = Carrier->GetCharacterMovement();
    bCarrierGroundingMovementTick = CarrierMovement->IsComponentTickEnabled();
    CarrierMovement->StopMovementImmediately();
    CarrierMovement->DisableMovement();
    // A Blueprint flow hook may select Walking while Continue cleans up the title.
    // Suspend the movement tick as well, so it cannot apply gravity before our poll.
    CarrierMovement->SetComponentTickEnabled(false);
    Carrier->ConsumeMovementInputVector();
    UWorld* World = GetWorld();
    if (World->GetWorldPartition() && World->GetSubsystem<UWorldPartitionSubsystem>())
    {
        CarrierGroundingSource = NewObject<UWorldPartitionStreamingSourceComponent>(Carrier, NAME_None, RF_Transient);
        FStreamingSourceShape Shape;
        Shape.bUseGridLoadingRange = false;
        Shape.Radius = SaskartaEvents::CarrierGroundingRadiusCm;
        CarrierGroundingSource->Shapes.Add(Shape);
        CarrierGroundingSource->TargetState = EStreamingSourceTargetState::Activated;
        CarrierGroundingSource->RegisterComponent();
    }
    if (APlayerController* Controller = CarrierGroundingController.Get())
    {
        APlayerCameraManager* Camera = Controller->PlayerCameraManager;
        if (Camera && (!Camera->bEnableFading || Camera->FadeAmount <= UE_KINDA_SMALL_NUMBER))
        {
            Camera->SetManualCameraFade(1.f, FLinearColor::Black, false);
            bCarrierGroundingFade = true;
        }
    }
    World->GetTimerManager().SetTimer(CarrierGroundingTimer, this, &USaskartaEventRunner::PollCarrierGrounding, 0.1f, true);
    UE_LOG(LogSaskartaEvents, Log, TEXT("Carrier grounding hold: %s at %s (exact pose %d)"),
        *Carrier->GetName(), *CarrierGroundingPose.GetLocation().ToString(), bExactPose);
}

void USaskartaEventRunner::ClearCarrierGroundingHold()
{
    if (UWorld* World = GetWorld())
    {
        World->GetTimerManager().ClearTimer(CarrierGroundingTimer);
    }
    if (CarrierGroundingSource)
    {
        CarrierGroundingSource->DisableStreamingSource();
        CarrierGroundingSource->DestroyComponent();
        CarrierGroundingSource = nullptr;
    }
    if (ACharacter* Carrier = CarrierGroundingPawn.Get())
    {
        if (UCharacterMovementComponent* CarrierMovement = Carrier->GetCharacterMovement())
        {
            CarrierMovement->StopMovementImmediately();
            CarrierMovement->DisableMovement();
            CarrierMovement->SetComponentTickEnabled(bCarrierGroundingMovementTick);
        }
    }
    if (APlayerController* Controller = CarrierGroundingController.Get())
    {
        if (bCarrierGroundingMoveLock) Controller->SetIgnoreMoveInput(false);
        if (bCarrierGroundingLookLock) Controller->SetIgnoreLookInput(false);
        APlayerCameraManager* Camera = Controller->PlayerCameraManager;
        if (bCarrierGroundingFade && Camera && Camera->bEnableFading
            && FMath::IsNearlyEqual(Camera->FadeAmount, 1.f)
            && Camera->FadeColor.Equals(FLinearColor::Black) && !Camera->bFadeAudio)
        {
            Camera->StopCameraFade();
        }
    }
    bCarrierGroundingActive = false;
    bCarrierGroundingMoveLock = bCarrierGroundingLookLock = bCarrierGroundingFade = false;
    CarrierGroundingReadyPolls = 0;
    CarrierGroundingPawn.Reset();
    CarrierGroundingController.Reset();
}

void USaskartaEventRunner::FailCarrierGrounding(const TCHAR* Reason)
{
    APlayerController* Controller = CarrierGroundingController.Get();
    UE_LOG(LogSaskartaEvents, Error, TEXT("Carrier grounding failed: %s; returning to title without changing the save"), Reason);
    StopAll();
    if (Controller && CallHook(Controller, TEXT("QuitToTitle"), {}, {})) return;
    if (UWorld* World = GetWorld())
    {
        UGameplayStatics::OpenLevel(World, FName(*UGameplayStatics::GetCurrentLevelName(World, true)));
    }
}

void USaskartaEventRunner::PollCarrierGrounding()
{
    if (!bCarrierGroundingActive) return;
    UWorld* World = GetWorld();
    ACharacter* Carrier = CarrierGroundingPawn.Get();
    APlayerController* Controller = CarrierGroundingController.Get();
    if (!World || !Controller || !Carrier || Carrier->IsActorBeingDestroyed())
    {
        FailCarrierGrounding(TEXT("destination pawn/controller became invalid"));
        return;
    }
    const double PollS = Now();
    const double DeltaS = FMath::Max(0.0, PollS - CarrierGroundingLastPollS);
    CarrierGroundingLastPollS = PollS;
    const FName Flow = GetFlowState();
    if (Flow == FName(TEXT("Title")) || Flow == FName(TEXT("Booting")) || Controller->GetPawn() != Carrier)
    {
        ClearCarrierGroundingHold();
        return;
    }
    UCharacterMovementComponent* CarrierMovement = Carrier->GetCharacterMovement();
    if (!CarrierMovement)
    {
        FailCarrierGrounding(TEXT("missing carrier movement component"));
        return;
    }
    CarrierMovement->StopMovementImmediately();
    CarrierMovement->DisableMovement();
    CarrierMovement->SetComponentTickEnabled(false);
    Carrier->ConsumeMovementInputVector();
    Carrier->SetActorTransform(CarrierGroundingPose, false, nullptr, ETeleportType::ResetPhysics);
    if (Flow == FName(TEXT("Paused")) || Flow == FName(TEXT("PackageRescue"))) return;
    CarrierGroundingActiveElapsedS += DeltaS;
    if (CarrierGroundingActiveElapsedS >= SaskartaEvents::CarrierGroundingTimeoutS)
    {
        FailCarrierGrounding(TEXT("destination terrain was not ready within 30 active seconds"));
        return;
    }
    bool bStreamingReady = !World->GetWorldPartition();
    if (!bStreamingReady)
    {
        UWorldPartitionSubsystem* PartitionSubsystem = World->GetSubsystem<UWorldPartitionSubsystem>();
        FWorldPartitionStreamingQuerySource Query(CarrierGroundingPose.GetLocation());
        Query.bSpatialQuery = true;
        Query.bUseGridLoadingRange = false;
        Query.bDataLayersOnly = false;
        Query.Radius = SaskartaEvents::CarrierGroundingRadiusCm;
        TArray<FWorldPartitionStreamingQuerySource> Queries;
        Queries.Add(Query);
        bStreamingReady = PartitionSubsystem && CarrierGroundingSource && CarrierGroundingSource->IsRegistered()
            && PartitionSubsystem->IsStreamingCompleted(EWorldPartitionRuntimeCellState::Activated, Queries, false);
    }
    if (!bStreamingReady)
    {
        CarrierGroundingReadyPolls = 0;
        CarrierGroundingLastReadyFrame = MAX_uint64;
        return;
    }
    if (!bCarrierGroundingExactPose)
    {
        // Landmark saves have spline height, not a saved safe capsule Z. Project
        // vertically only; retain the checkpoint's XY, actor rotation and view.
        const FVector At = CarrierGroundingPose.GetLocation();
        FCollisionQueryParams Params(SCENE_QUERY_STAT(SaskartaCarrierContinueGround), false, Carrier);
        TArray<FHitResult> Hits;
        World->LineTraceMultiByObjectType(Hits, At + FVector(0, 0, 3000), At - FVector(0, 0, 6000),
            FCollisionObjectQueryParams(ECC_WorldStatic), Params);
        for (const FHitResult& Hit : Hits)
        {
            if (Hit.GetActor() && Hit.GetActor()->IsA<ALandscapeProxy>())
            {
                FVector Grounded = At;
                Grounded.Z = Hit.ImpactPoint.Z + Carrier->GetCapsuleComponent()->GetScaledCapsuleHalfHeight() + 2.f;
                CarrierGroundingPose.SetLocation(Grounded);
                Carrier->SetActorTransform(CarrierGroundingPose, false, nullptr, ETeleportType::ResetPhysics);
                break;
            }
        }
    }
    FFindFloorResult Floor;
    CarrierMovement->FindFloor(Carrier->GetActorLocation(), Floor, false);
    const AActor* FloorActor = Floor.HitResult.GetActor();
    const bool bGrounded = Floor.IsWalkableFloor() && FloorActor && FloorActor->IsA<ALandscapeProxy>()
        && !Floor.HitResult.bStartPenetrating && Floor.GetDistanceToFloor() <= 10.f;
    // Timer catch-up at a low frame rate must not count the same physics frame twice.
    if (!bGrounded)
    {
        CarrierGroundingReadyPolls = 0;
        CarrierGroundingLastReadyFrame = MAX_uint64;
    }
    else if (CarrierGroundingLastReadyFrame != GFrameCounter)
    {
        ++CarrierGroundingReadyPolls;
        CarrierGroundingLastReadyFrame = GFrameCounter;
    }
    if (CarrierGroundingReadyPolls < 2
        || (Flow != FName(TEXT("Playing")) && Flow != FName(TEXT("Carrier")))) return;
    const double HeldS = CarrierGroundingActiveElapsedS;
    ClearCarrierGroundingHold();
    CarrierMovement->SetMovementMode(MOVE_Walking);
    UE_LOG(LogSaskartaEvents, Log, TEXT("Carrier grounding ready after %.2f active seconds: landscape %s, floor distance %.2fcm; driving released"),
        HeldS, *GetNameSafe(FloorActor), Floor.GetDistanceToFloor());
}

void USaskartaEventRunner::BeginHumanGroundingHold(ACharacter* Human, bool bExactPose)
{
    ClearHumanGroundingHold();
    bHumanGroundingActive = true;
    bHumanGroundingExactPose = bExactPose;
    HumanGroundingPawn = Human;
    HumanGroundingController = GetPC();
    HumanGroundingPose = Human->GetActorTransform();
    HumanGroundingLastPollS = Now();
    HumanGroundingActiveElapsedS = 0.0;
    HumanGroundingReadyPolls = 0;

    UWorld* World = GetWorld();
    if (World->GetWorldPartition() && World->GetSubsystem<UWorldPartitionSubsystem>())
    {
        HumanGroundingSource = NewObject<UWorldPartitionStreamingSourceComponent>(Human, NAME_None, RF_Transient);
        FStreamingSourceShape Shape;
        Shape.bUseGridLoadingRange = false;
        Shape.Radius = SaskartaEvents::HumanGroundingRadiusCm;
        HumanGroundingSource->Shapes.Add(Shape);
        HumanGroundingSource->TargetState = EStreamingSourceTargetState::Activated;
        HumanGroundingSource->RegisterComponent();
    }
    if (APlayerController* PC = HumanGroundingController.Get())
    {
        APlayerCameraManager* Camera = PC->PlayerCameraManager;
        // Do not replace someone else's fade, and never duck ongoing title music.
        if (Camera && (!Camera->bEnableFading || Camera->FadeAmount <= UE_KINDA_SMALL_NUMBER))
        {
            Camera->SetManualCameraFade(1.f, FLinearColor::Black, false);
            bHumanGroundingFade = true;
        }
    }
    World->GetTimerManager().SetTimer(HumanGroundingTimer, this, &USaskartaEventRunner::PollHumanGrounding, 0.1f, true);
    UE_LOG(LogSaskartaEvents, Log, TEXT("CP4 grounding hold: %s at %s (exact pose %d)"),
        *Human->GetName(), *HumanGroundingPose.GetLocation().ToString(), bExactPose);
}

void USaskartaEventRunner::ClearHumanGroundingHold()
{
    if (UWorld* World = GetWorld()) World->GetTimerManager().ClearTimer(HumanGroundingTimer);
    if (HumanGroundingSource)
    {
        HumanGroundingSource->DisableStreamingSource();
        HumanGroundingSource->DestroyComponent();
        HumanGroundingSource = nullptr;
    }
    if (APlayerController* PC = HumanGroundingController.Get())
    {
        if (bHumanGroundingMoveLock) PC->SetIgnoreMoveInput(false);
        if (bHumanGroundingLookLock) PC->SetIgnoreLookInput(false);
        APlayerCameraManager* Camera = PC->PlayerCameraManager;
        if (bHumanGroundingFade && Camera && Camera->bEnableFading
            && FMath::IsNearlyEqual(Camera->FadeAmount, 1.f)
            && Camera->FadeColor.Equals(FLinearColor::Black) && !Camera->bFadeAudio)
            Camera->StopCameraFade();
    }
    // Cancellation leaves the ungrounded pawn safely stopped. StopAll's caller
    // owns the next flow/possession; only successful contact may enable gravity.
    bHumanGroundingActive = false;
    bHumanGroundingMoveLock = bHumanGroundingLookLock = bHumanGroundingFade = false;
    HumanGroundingReadyPolls = 0;
    HumanGroundingPawn.Reset();
    HumanGroundingController.Reset();
}

void USaskartaEventRunner::FailHumanGrounding(const TCHAR* Reason)
{
    APlayerController* PC = HumanGroundingController.Get();
    UE_LOG(LogSaskartaEvents, Error, TEXT("CP4 grounding failed: %s; returning to title without changing the save"), Reason);
    StopAll(); // clears exactly our source/locks/fade and the interrupted walk/escort
    if (PC && CallHook(PC, TEXT("QuitToTitle"), {}, {})) return;
    // The normal Blueprint hook reopens this same level. Keep that recovery if
    // a development controller lacks the hook; never release an elder into void.
    if (UWorld* World = GetWorld())
        UGameplayStatics::OpenLevel(World, FName(*UGameplayStatics::GetCurrentLevelName(World, true)));
}

void USaskartaEventRunner::PollHumanGrounding()
{
    if (!bHumanGroundingActive) return;
    UWorld* World = GetWorld();
    ACharacter* Human = HumanGroundingPawn.Get();
    APlayerController* PC = HumanGroundingController.Get();
    if (!World || !PC || !Human || Human->IsActorBeingDestroyed())
    {
        FailHumanGrounding(TEXT("destination pawn/controller became invalid"));
        return;
    }
    const FName Flow = GetFlowState();
    // OpenPause keeps world time ticking for the settings countdown. Sample
    // every poll, including menu polls, but spend this budget only outside Paused.
    const double PollS = Now();
    const double DeltaS = FMath::Max(0.0, PollS - HumanGroundingLastPollS);
    HumanGroundingLastPollS = PollS;
    if (Flow == FName(TEXT("Paused"))) return;
    HumanGroundingActiveElapsedS += DeltaS;
    if (Flow == FName(TEXT("Title")) || Flow == FName(TEXT("Booting")) || PC->GetPawn() != Human)
    {
        ClearHumanGroundingHold(); // an explicit title/reset/possession superseded this handoff
        return;
    }
    UCharacterMovementComponent* Move = Human->GetCharacterMovement();
    if (!Move || HumanGroundingActiveElapsedS >= SaskartaEvents::HumanGroundingTimeoutS)
    {
        FailHumanGrounding(Move ? TEXT("destination terrain was not ready within 30 seconds") : TEXT("missing elder movement component"));
        return;
    }
    // No gravity or root-motion drift while the destination cells activate.
    Move->StopMovementImmediately();
    Move->DisableMovement();
    Human->ConsumeMovementInputVector();
    Human->SetActorTransform(HumanGroundingPose, false, nullptr, ETeleportType::ResetPhysics);

    bool bStreamingReady = !World->GetWorldPartition();
    if (!bStreamingReady)
    {
        UWorldPartitionSubsystem* WPS = World->GetSubsystem<UWorldPartitionSubsystem>();
        FWorldPartitionStreamingQuerySource Query(HumanGroundingPose.GetLocation());
        Query.bSpatialQuery = true;
        Query.bUseGridLoadingRange = false;
        Query.bDataLayersOnly = false;
        Query.Radius = SaskartaEvents::HumanGroundingRadiusCm;
        TArray<FWorldPartitionStreamingQuerySource> Queries;
        Queries.Add(Query);
        bStreamingReady = WPS && HumanGroundingSource && HumanGroundingSource->IsRegistered()
            && WPS->IsStreamingCompleted(EWorldPartitionRuntimeCellState::Activated, Queries, false);
    }
    if (!bStreamingReady)
    {
        HumanGroundingReadyPolls = 0;
        return;
    }

    if (!bHumanGroundingExactPose)
    {
        // Legacy CP4 has no saved elder Z. Only this fallback may be projected;
        // modern saves keep their full transform and must find supporting floor there.
        const FVector At = HumanGroundingPose.GetLocation();
        FCollisionQueryParams Params(SCENE_QUERY_STAT(SaskartaHumanContinueGround), false, Human);
        TArray<FHitResult> Hits;
        World->LineTraceMultiByObjectType(Hits, At + FVector(0, 0, 3000), At - FVector(0, 0, 6000),
            FCollisionObjectQueryParams(ECC_WorldStatic), Params);
        for (const FHitResult& Hit : Hits)
        {
            if (Hit.GetActor() && Hit.GetActor()->IsA<ALandscapeProxy>())
            {
                FVector Grounded = At;
                Grounded.Z = Hit.ImpactPoint.Z + Human->GetCapsuleComponent()->GetScaledCapsuleHalfHeight() + 2.f;
                HumanGroundingPose.SetLocation(Grounded);
                Human->SetActorTransform(HumanGroundingPose, false, nullptr, ETeleportType::ResetPhysics);
                break;
            }
        }
    }
    FFindFloorResult Floor;
    Move->FindFloor(Human->GetActorLocation(), Floor, false);
    const AActor* FloorActor = Floor.HitResult.GetActor();
    const bool bGrounded = Floor.IsWalkableFloor() && FloorActor && FloorActor->IsA<ALandscapeProxy>()
        && !Floor.HitResult.bStartPenetrating && Floor.GetDistanceToFloor() <= 10.f;
    HumanGroundingReadyPolls = bGrounded ? HumanGroundingReadyPolls + 1 : 0;
    if (HumanGroundingReadyPolls < 2 || Flow != SaskartaEvents::NameHuman) return;

    const double HeldS = HumanGroundingActiveElapsedS;
    ClearHumanGroundingHold();
    Move->SetMovementMode(MOVE_Walking);
    CallHook(PC, TEXT("StartHumanWalk"), {}, {});
    UE_LOG(LogSaskartaEvents, Log, TEXT("CP4 grounding ready after %.2f active seconds: landscape %s, floor distance %.2fcm; walking released"),
        HeldS, *GetNameSafe(FloorActor), Floor.GetDistanceToFloor());
}

bool USaskartaEventRunner::RestoreHumanCheckpoint(const USaskartaSaveGame& S)
{
    UWorld* World = GetWorld();
    APlayerController* PC = GetPC();
    ACharacter* Carrier = SaskartaEvents::EndingCarrier(World);
    USaskartaCollapseStageSubsystem* Collapse = World ? World->GetSubsystem<USaskartaCollapseStageSubsystem>() : nullptr;
    if (!PC || !Carrier || !Collapse) return false;

    // Existing Human sessions can have a walking loop/tether. Stop them before starting fresh ones.
    if (GetPawn() && GetPawn() != Carrier) CallHook(GetPawn(), TEXT("StopWalk"), {}, {});
    if (S.bHasHumanCarrierPose)
    {
        Carrier->SetActorTransform(S.HumanCarrierPose, false, nullptr, ETeleportType::ResetPhysics);
    }
    else
    {
        // Old CP4 files never stored a pose. Stage the carrier at the authored collapse,
        // before EnsureHumanHandoff uses it; a fresh level's PlayerStart is not a human checkpoint.
        APawn* Previous = GetPawn();
        PC->Possess(Carrier);
        if (!Collapse->StageNow())
        {
            if (Previous) PC->Possess(Previous);
            return false;
        }
    }
    Carrier->ConsumeMovementInputVector();
    if (UCharacterMovementComponent* Move = Carrier->GetCharacterMovement())
    {
        Move->StopMovementImmediately();
        Move->SetMovementMode(MOVE_None);
    }
    CallHook(Carrier, SaskartaEvents::NameStopAnimDriver, {}, {});
    if (FNameProperty* Mode = FindFProperty<FNameProperty>(Carrier->GetClass(), TEXT("AnimMode")))
        Mode->SetPropertyValue_InContainer(Carrier, FName(TEXT("Shutdown")));
    if (USkeletalMeshComponent* Mesh = Carrier->GetMesh())
    {
        if (UAnimSequence* Closed = LoadObject<UAnimSequence>(nullptr,
            TEXT("/Game/SaskartaGaea/Characters/Carrier/Full/A_CarrierFull_CloseHatch.A_CarrierFull_CloseHatch")))
        {
            Mesh->PlayAnimation(Closed, false);
            Mesh->SetPosition(Closed->GetPlayLength(), false);
        }
    }
    TArray<UAudioComponent*> Audio;
    Carrier->GetComponents(Audio);
    for (UAudioComponent* Component : Audio)
    {
        if (Component && (Component->GetFName() == TEXT("AC_Idle") || Component->GetFName() == TEXT("AC_Low")
            || Component->GetFName() == TEXT("AC_High") || Component->GetFName() == TEXT("AC_Strain")))
            Component->Stop();
    }

    UClass* HumanClass = SaskartaEvents::TravellerClass();
    ACharacter* Human = nullptr;
    if (S.bHasHumanPose)
    {
        // Modern saves already have the elder's exact safe pose. A hatch-side
        // fallback trace is both unnecessary and wrong for a progressed walk.
        Human = Cast<ACharacter>(UGameplayStatics::GetActorOfClass(World, HumanClass));
        if (!Human)
        {
            FActorSpawnParameters Spawn;
            Spawn.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
            Human = World->SpawnActor<ACharacter>(HumanClass, S.HumanPose, Spawn);
        }
        if (!Human || !Human->GetCharacterMovement()) return false;
        Human->GetCharacterMovement()->StopMovementImmediately();
        Human->GetCharacterMovement()->DisableMovement();
        Human->SetActorTransform(S.HumanPose, false, nullptr, ETeleportType::ResetPhysics);
        if (PC->GetPawn() != Human) PC->Possess(Human);
    }
    else
    {
        Collapse->EnsureHumanHandoff(PC, Carrier);
        Human = Cast<ACharacter>(GetPawn());
    }
    if (!Human || !HumanClass || !Human->IsA(HumanClass) || PC->GetPawn() != Human) return false;
    // Stop an old carrier tether immediately, as StartHumanWalk normally does.
    // Its breath/elder tether start is deferred until contact, so call only the
    // existing component's no-argument StopTether here (no graph/default change).
    if (FObjectPropertyBase* Property = FindFProperty<FObjectPropertyBase>(PC->GetClass(), TEXT("RoadTether")))
    {
        UObject* Tether = Property->GetObjectPropertyValue_InContainer(PC);
        if (IsValid(Tether))
        {
            UFunction* Stop = Tether->FindFunction(TEXT("StopTether"));
            if (Stop && Stop->ParmsSize == 0) Tether->ProcessEvent(Stop, nullptr);
        }
    }
    // StartAnimDriver normally consumes bStartHidden at BeginPlay. Make repeated restores safe too.
    if (FBoolProperty* Hidden = FindFProperty<FBoolProperty>(Human->GetClass(), TEXT("bStartHidden")))
        Hidden->SetPropertyValue_InContainer(Human, false);
    if (S.bHasHumanPose)
    {
        Human->SetActorTransform(S.HumanPose, false, nullptr, ETeleportType::ResetPhysics);
        PC->SetControlRotation(S.HumanViewRotation);
    }
    Human->SetActorHiddenInGame(false);
    Human->SetActorEnableCollision(true);
    Human->ConsumeMovementInputVector();
    if (UCharacterMovementComponent* Move = Human->GetCharacterMovement())
    {
        Move->StopMovementImmediately();
        Move->DisableMovement(); // destination streaming/contact is checked by the owned hold
    }
    CallHook(Human, SaskartaEvents::NameStartAnimDriver, {}, {});
    CallHook(Human, TEXT("PlaySupportedIdle"), {}, {});
    PC->SetViewTarget(Human);
    BeginHumanGroundingHold(Human, S.bHasHumanPose);
    return true;
}

bool USaskartaEventRunner::RestoreCheckpointSnapshot(USaskartaSaveGame* S)
{
    if (!S || !Story)
    {
        return false;
    }
    const bool bHuman = S->IsHumanCheckpoint();
    APlayerController* PC = GetPC();
    ACharacter* Carrier = SaskartaEvents::EndingCarrier(GetWorld());
    const float RoadM = S->bHasExactCarrierPose ? S->CheckpointRoadM : FSaskartaEventLogic::CheckpointRoadM(S->CheckpointId);
    if (!PC || !Carrier || (!bHuman && !Carrier->GetCharacterMovement()) || !ResolveRoad()
        || (!bHuman && (!FMath::IsFinite(RoadM) || RoadM < 0.f || FSaskartaEventLogic::UeMFromRoadM(Story->RoadMToUeM, RoadM) < 0.f))
        || (bHuman && (!SaskartaEvents::TravellerClass() || (!S->bHasHumanCarrierPose
            && (!Story->CollapseStage.bEnabled || FSaskartaEventLogic::UeMFromRoadM(Story->RoadMToUeM, Story->CollapseStage.RoadM) < 0.f))))
        || (!bHuman && S->bHasExactCarrierPose && (S->CarrierPose.ContainsNaN() || !S->CarrierPose.GetRotation().IsNormalized() || S->CarrierViewRotation.ContainsNaN()))
        || (S->bHasHumanPose && (S->HumanPose.ContainsNaN() || !S->HumanPose.GetRotation().IsNormalized() || S->HumanViewRotation.ContainsNaN()))
        || (S->bHasHumanCarrierPose && (S->HumanCarrierPose.ContainsNaN() || !S->HumanCarrierPose.GetRotation().IsNormalized())))
    {
        UE_LOG(LogSaskartaEvents, Error, TEXT("Checkpoint rejected: missing controller/carrier/road, unknown landmark, or invalid saved pose"));
        return false;
    }
    StopAll();
    // Teleport/possession overlaps must not start a beat before the hold exists.
    bHumanGroundingActive = bHuman;
    bCarrierGroundingActive = !bHuman;
    if (bHuman && !RestoreHumanCheckpoint(*S))
    {
        ClearHumanGroundingHold();
        UE_LOG(LogSaskartaEvents, Error, TEXT("Human checkpoint could not restore the Traveller"));
        return false;
    }
    if (!bHuman)
    {
        APawn* Previous = GetPawn();
        if (Previous && Previous != Carrier) CallHook(Previous, TEXT("StopWalk"), {}, {});
        if (Previous != Carrier) PC->Possess(Carrier);
        if (GetPawn() != Carrier)
        {
            ClearCarrierGroundingHold();
            return false;
        }
        if (Previous && Previous != Carrier)
        {
            Previous->SetActorHiddenInGame(true);
            Previous->SetActorEnableCollision(false);
        }
        Carrier->SetActorHiddenInGame(false);
        Carrier->SetActorEnableCollision(true);
        Carrier->ConsumeMovementInputVector();
        if (UCharacterMovementComponent* Move = Carrier->GetCharacterMovement())
        {
            Move->StopMovementImmediately();
            Move->DisableMovement();
        }
    }
    FiredBeats.Reset();
    FiredBeats.Append(S->FiredBeats);
    LastFiredS.Reset();
    Revealed = S->Revealed;
    LastFog = S->LastFogMultiplier;
    ActiveModes.Reset();
    ActiveModes.Append(S->ActiveModes);
    if (bHuman)
    {
        // A human checkpoint never returns to the old carrier's damaged optics/feed.
        ActiveModes.Remove(FName(TEXT("AuxSensors")));
        ActiveModes.Remove(FName(TEXT("DroneCam")));
    }

    const FName RestoredFlow = bHuman ? SaskartaEvents::NameHuman : (S->FlowState.IsNone() ? FName(TEXT("Playing")) : S->FlowState);
    if (PC && PC->FindFunction(TEXT("RestoreFlow"))) CallHook(PC, TEXT("RestoreFlow"), { RestoredFlow }, {});
    if (!RestoredFlow.IsNone())
    {
        SetFlowStateByReflection(RestoredFlow);
    }
    if (bHuman)
    {
        // The exact Human pose (or grounded legacy handoff) was already restored above.
        const float Key = RoadSpline->FindInputKeyClosestToWorldLocation(GetPawn()->GetActorLocation());
        CurrentUeM = RoadSpline->GetDistanceAlongSplineAtSplineInputKey(Key) / 100.f;
        CurrentRoadM = FSaskartaEventLogic::RoadMFromUeM(Story->RoadMToUeM, CurrentUeM);
        SpeedMps = 0.f;
    }
    else if (S->bHasExactCarrierPose && GetPawn() && PC)
    {
        APawn* Pawn = GetPawn();
        Pawn->SetActorTransform(S->CarrierPose, false, nullptr, ETeleportType::TeleportPhysics);
        Pawn->ConsumeMovementInputVector();
        if (UPawnMovementComponent* Movement = Pawn->GetMovementComponent()) Movement->StopMovementImmediately();
        PC->SetControlRotation(S->CarrierViewRotation);
        CurrentRoadM = RoadM;
        CurrentUeM = FSaskartaEventLogic::UeMFromRoadM(Story->RoadMToUeM, RoadM);
        SpeedMps = 0.f;
    }
    else if (RoadM >= 0.f)
    {
        if (!TeleportToRoadM(RoadM))
        {
            ClearCarrierGroundingHold();
            return false;
        }
    }
    if (!bHuman)
    {
        BeginCarrierGroundingHold(Carrier, S->bHasExactCarrierPose);
        CallHook(Carrier, SaskartaEvents::NameStartAnimDriver, {}, {});
    }
    HighWaterUeM = S->HighWaterUeM;

    TArray<FSaskartaEventAction> Reapply;
    FSaskartaEventLogic::CollectReapplyActions(Story->Beats, FiredBeats, Reapply);
    for (const FSaskartaEventAction& A : Reapply)
    {
        if (bHuman && A.Type == ESaskartaActionType::SetMode
            && (A.Id == FName(TEXT("AuxSensors")) || A.Id == FName(TEXT("DroneCam")))) continue;
        RunImmediate(A);
    }
    if (!S->LastLook.IsNone())
    {
        FSaskartaEventAction Look;
        Look.Type = ESaskartaActionType::SetLook;
        Look.Id = S->LastLook;
        RunImmediate(Look);
    }
    // Listeners may turn another mode off while activating their restored view.
    const TArray<FName> RestoredModes = ActiveModes.Array();
    for (const FName& Mode : RestoredModes)
    {
        if (ActiveModes.Contains(Mode)) OnModeChanged.Broadcast(Mode, true);
    }
    RebuildHudColumn();
    USaskartaSaveGame::OnRestoredRun.Broadcast(GetWorld(), S); // RADIOSHOW: the station restores the show
    // BeginTitle's controller ignores stack independently of this runner's cinematic locks.
    // A successful checkpoint handoff owns the restored pawn's input from this point.
    PC->ResetIgnoreMoveInput();
    PC->ResetIgnoreLookInput();
    USaskartaDroneSequenceSubsystem* Drone = GetWorld()->GetSubsystem<USaskartaDroneSequenceSubsystem>();
    if (bHuman)
    {
        // StartWalk (breath/tether/movement) begins only after destination contact.
        if (Drone)
        {
            if (!Drone->RestoreHumanEscort(Carrier))
                UE_LOG(LogSaskartaEvents, Error, TEXT("Human checkpoint restored but its drone escort could not spawn"));
        }
    }
    AActor* ViewTarget = Drone ? (bHuman ? Drone->GetHumanDroneViewTarget()
        : (Drone->IsDroneFeedActive() ? Drone->GetDroneViewTarget() : nullptr)) : nullptr;
    PC->SetViewTarget(ViewTarget ? ViewTarget : GetPawn());
    if (bHumanGroundingActive)
    {
        // Continue resets the title's ignore stacks above. Acquire our own pair
        // afterwards so cleanup can decrement only what this hold added.
        PC->SetIgnoreMoveInput(true);
        PC->SetIgnoreLookInput(true);
        bHumanGroundingMoveLock = bHumanGroundingLookLock = true;
    }
    if (bCarrierGroundingActive)
    {
        // Reapply/restore delegates may run controller flow hooks. Reassert the
        // frozen movement state before the synchronous Continue cleanup returns.
        UCharacterMovementComponent* CarrierMovement = Carrier->GetCharacterMovement();
        CarrierMovement->StopMovementImmediately();
        CarrierMovement->DisableMovement();
        CarrierMovement->SetComponentTickEnabled(false);
        PC->SetIgnoreMoveInput(true);
        PC->SetIgnoreLookInput(true);
        bCarrierGroundingMoveLock = bCarrierGroundingLookLock = true;
    }
    UE_LOG(LogSaskartaEvents, Log, TEXT("restored %s: %d beats fired, %d reapplied"), *S->CheckpointId.ToString(), FiredBeats.Num(), Reapply.Num());
    return true;
}

// ============================================================================ debug

FString USaskartaEventRunner::DumpState() const
{
    FString Out = FString::Printf(TEXT("road %.1f m (UE %.1f, high-water %.1f), speed %.1f m/s, flow %s\n"),
        CurrentRoadM, CurrentUeM, HighWaterUeM == TNumericLimits<float>::Max() ? -1.f : HighWaterUeM, SpeedMps, *GetFlowState().ToString());
    Out += FString::Printf(TEXT("running %s (action %d), voice busy %.1f s, cinematic %s, prompt %d, glance %d\n"),
        bHasRunning ? *RunningBeatId.ToString() : TEXT("-"), RunningActionIndex, FMath::Max(0.0, VoiceBusyUntilS - Now()),
        IsCinematicActive() ? *ActiveCineId.ToString() : TEXT("-"), bPromptActive ? 1 : 0, bGlanceActive ? 1 : 0);
    for (const FSaskartaQueuedBeat& Q : Queue)
    {
        Out += FString::Printf(TEXT("  queued %s p%d waited %.1f s\n"), *Q.BeatId.ToString(), static_cast<int32>(Q.Priority), Now() - Q.EnqueueTimeS);
    }
    Out += FString::Printf(TEXT("fired %d, seen cinematics %d, next beat in %.0f s"), FiredBeats.Num(), SeenCinematics.Num(), GetSecondsToNextBeat());
    if (bCarrierGroundingActive)
    {
        Out += FString::Printf(TEXT("\ncarrier grounding pending %.2f active seconds, ready frames %d, destination %s"),
            CarrierGroundingActiveElapsedS, CarrierGroundingReadyPolls, *CarrierGroundingPose.GetLocation().ToString());
    }
    return Out;
}

void USaskartaEventRunner::LogDryRun(float InSpeedMps, float EndRoadM) const
{
    if (!Story)
    {
        UE_LOG(LogSaskartaEvents, Warning, TEXT("DryRun: no story data"));
        return;
    }
    TArray<FString> Log;
    FSaskartaEventLogic::DryRun(Story->Beats, Story->Lines, Story->Cinematics, Story->RoadMToUeM, EnabledTags,
        InSpeedMps, EndRoadM, Story->GapS, Log);
    for (const FString& L : Log)
    {
        UE_LOG(LogSaskartaEvents, Log, TEXT("%s"), *L);
    }
}

// ============================================================================ console commands

namespace SaskartaEvents
{
    static USaskartaEventRunner* RunnerFor(UWorld* World)
    {
        USaskartaEventRunner* R = World ? World->GetSubsystem<USaskartaEventRunner>() : nullptr;
        if (!R)
        {
            UE_LOG(LogSaskartaEvents, Warning, TEXT("no event runner in this world (start PIE or a game world)"));
        }
        return R;
    }

    static FAutoConsoleCommandWithWorldAndArgs CmdGoTo(TEXT("Saskarta.Events.GoTo"),
        TEXT("Saskarta.Events.GoTo <roadm>: teleport to that road metre and mark earlier beats fired."),
        FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>& Args, UWorld* World)
        {
            if (USaskartaEventRunner* R = RunnerFor(World))
            {
                R->GoToRoadM(Args.Num() > 0 ? FCString::Atof(*Args[0]) : 0.f);
            }
        }));

    static FAutoConsoleCommandWithWorldAndArgs CmdFire(TEXT("Saskarta.Events.Fire"),
        TEXT("Saskarta.Events.Fire <BeatId>: queue a beat (forced)."),
        FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>& Args, UWorld* World)
        {
            if (USaskartaEventRunner* R = RunnerFor(World))
            {
                if (Args.Num() > 0) R->FireBeat(FName(*Args[0]), true);
            }
        }));

    static FAutoConsoleCommandWithWorldAndArgs CmdDump(TEXT("Saskarta.Events.Dump"),
        TEXT("Saskarta.Events.Dump: the queue, the channels and the high-water mark."),
        FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>& Args, UWorld* World)
        {
            if (USaskartaEventRunner* R = RunnerFor(World))
            {
                UE_LOG(LogSaskartaEvents, Log, TEXT("%s"), *R->DumpState());
            }
        }));

    static FAutoConsoleCommandWithWorldAndArgs CmdOptional(TEXT("Saskarta.Events.Optional"),
        TEXT("Saskarta.Events.Optional <tag> [tag...]: set the optional-content tags (none = clear)."),
        FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>& Args, UWorld* World)
        {
            if (USaskartaEventRunner* R = RunnerFor(World))
            {
                TArray<FName> Tags;
                for (const FString& A : Args) Tags.Add(FName(*A));
                R->SetEnabledTags(Tags);
            }
        }));

    static FAutoConsoleCommandWithWorldAndArgs CmdDryRun(TEXT("Saskarta.Events.DryRun"),
        TEXT("Saskarta.Events.DryRun [speed_mps=5] [end_roadm=4790]: simulate the drive in the log (no audio)."),
        FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>& Args, UWorld* World)
        {
            const float Speed = Args.Num() > 0 ? FCString::Atof(*Args[0]) : 5.f;
            const float End = Args.Num() > 1 ? FCString::Atof(*Args[1]) : 4790.f;
            if (USaskartaEventRunner* R = World ? World->GetSubsystem<USaskartaEventRunner>() : nullptr)
            {
                R->LogDryRun(Speed, End);
                return;
            }
            // Outside a game world (editor console): run on the data directly.
            if (USaskartaStoryAsset* Story = USaskartaStoryImport::LoadStoryOrImportTransient(nullptr))
            {
                TArray<FString> Log;
                TSet<FName> Tags;
                Tags.Append(Story->EnabledTags);
                FSaskartaEventLogic::DryRun(Story->Beats, Story->Lines, Story->Cinematics, Story->RoadMToUeM,
                    Tags, Speed, End, Story->GapS, Log);
                for (const FString& L : Log) UE_LOG(LogSaskartaEvents, Log, TEXT("%s"), *L);
            }
        }));

    static FAutoConsoleCommandWithWorldAndArgs CmdCinePlay(TEXT("Saskarta.Cine.Play"),
        TEXT("Saskarta.Cine.Play <CinId>: play a cinematic now."),
        FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>& Args, UWorld* World)
        {
            if (USaskartaEventRunner* R = RunnerFor(World))
            {
                if (Args.Num() > 0) R->PlayCinematicById(FName(*Args[0]));
            }
        }));

    static FAutoConsoleCommandWithWorldAndArgs CmdReleaseInput(TEXT("Saskarta.Events.ReleaseInput"),
        TEXT("Saskarta.Events.ReleaseInput: end any cinematic now (its final state runs) and release every input lock the runner holds."),
        FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>& Args, UWorld* World)
        {
            if (USaskartaEventRunner* R = RunnerFor(World))
            {
                R->ForceReleaseInput();
            }
        }));
}
