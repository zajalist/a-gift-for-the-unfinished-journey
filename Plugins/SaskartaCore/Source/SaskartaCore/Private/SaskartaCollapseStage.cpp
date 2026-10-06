#include "SaskartaCollapseStage.h"

#include "SaskartaCarrierAnimInstance.h"
#include "SaskartaCollapseStageLogic.h"
#include "SaskartaCollapseStageMath.h"
#include "SaskartaDroneSequence.h"
#include "SaskartaEventLogic.h"
#include "SaskartaEventRunner.h"
#include "SaskartaStoryAsset.h"

#include "Camera/PlayerCameraManager.h"
#include "Components/AudioComponent.h"
#include "Components/CapsuleComponent.h"
#include "Components/SkeletalMeshComponent.h"
#include "Components/SplineComponent.h"
#include "Engine/World.h"
#include "GameFramework/Character.h"
#include "GameFramework/CharacterMovementComponent.h"
#include "GameFramework/PlayerController.h"
#include "Kismet/GameplayStatics.h"
#include "LandscapeProxy.h"
#include "Particles/ParticleSystem.h"
#include "Particles/ParticleSystemComponent.h"
#include "TimerManager.h"
#include "UObject/ConstructorHelpers.h"
#include "UObject/UObjectGlobals.h"

DEFINE_LOG_CATEGORY_STATIC(LogSaskartaCollapse, Log, All);

namespace SaskartaCollapseStage
{
    /** A beat and its cinematic both trigger; the second within this window is the same collapse. */
    constexpr double RestageGuardS = 5.0;
    /** The hitch model is off this long (a few anim updates), which zeroes its angle; then it is restored. */
    constexpr float TrailerOffS = 0.3f;
    /** Behind / ahead samples for a zero tangent, cm. */
    constexpr float ChordCm = 150.f;

    /** The highest landscape hit in the column, or false. */
    bool TraceLandscape(UWorld* World, const FVector& XY, float TopZ, float BottomZ, const FCollisionQueryParams& Params, double& OutZ)
    {
        TArray<FHitResult> Hits;
        const FVector Start(XY.X, XY.Y, TopZ);
        const FVector End(XY.X, XY.Y, BottomZ);
        World->LineTraceMultiByObjectType(Hits, Start, End, FCollisionObjectQueryParams(ECC_WorldStatic), Params);
        for (const FHitResult& H : Hits)
        {
            const AActor* A = H.GetActor();
            if (A && A->IsA<ALandscapeProxy>())
            {
                OutZ = H.ImpactPoint.Z;
                return true;
            }
        }
        return false;
    }
}

USaskartaCollapseStageSubsystem::USaskartaCollapseStageSubsystem()
{
    // Constructor reference on the subsystem CDO keeps this existing particle asset in cooked builds.
    static ConstructorHelpers::FObjectFinder<UParticleSystem> Smoke(
        TEXT("/Game/AshesOfBazaar/Particles/P_Smoke.P_Smoke"));
    CollapseSmoke = Smoke.Object;
}

bool USaskartaCollapseStageSubsystem::ShouldCreateSubsystem(UObject* Outer) const
{
    const UWorld* World = Cast<UWorld>(Outer);
    return World && World->IsGameWorld();
}

void USaskartaCollapseStageSubsystem::OnWorldBeginPlay(UWorld& InWorld)
{
    Super::OnWorldBeginPlay(InWorld);
    Runner = InWorld.GetSubsystem<USaskartaEventRunner>();
    if (Runner.IsValid())
    {
        Runner->OnBeatStarted.AddDynamic(this, &USaskartaCollapseStageSubsystem::HandleBeatStarted);
        Runner->OnCinematicStarted.AddDynamic(this, &USaskartaCollapseStageSubsystem::HandleCinematicStarted);
    }
}

void USaskartaCollapseStageSubsystem::Deinitialize()
{
    if (USaskartaEventRunner* R = Runner.Get())
    {
        R->OnBeatStarted.RemoveDynamic(this, &USaskartaCollapseStageSubsystem::HandleBeatStarted);
        R->OnCinematicStarted.RemoveDynamic(this, &USaskartaCollapseStageSubsystem::HandleCinematicStarted);
    }
    if (UWorld* World = GetWorld())
    {
        World->GetTimerManager().ClearTimer(TrailerTimer);
        World->GetTimerManager().ClearTimer(FadeTimer);
    }
    RestoreTrailer();
    for (UParticleSystemComponent* Emitter : SmokeEmitters)
    {
        if (Emitter) Emitter->DestroyComponent();
    }
    SmokeEmitters.Reset();
    Super::Deinitialize();
}

void USaskartaCollapseStageSubsystem::HandleBeatStarted(FName Id)
{
    MaybeStage(Id);
}

void USaskartaCollapseStageSubsystem::HandleCinematicStarted(FName Id)
{
    MaybeStage(Id);
}

void USaskartaCollapseStageSubsystem::MaybeStage(FName Id)
{
    const USaskartaStoryAsset* Story = Runner.IsValid() ? Runner->GetStory() : nullptr;
    const FSaskartaCollapseStageDef Def = Story ? Story->CollapseStage : FSaskartaCollapseStageDef();
    if (!FSaskartaCollapseStageLogic::Triggers(Def, Id))
    {
        return;
    }
    const UWorld* World = GetWorld();
    if (World && World->GetTimeSeconds() - LastStageS < SaskartaCollapseStage::RestageGuardS)
    {
        return;
    }
    StageNow();
}

bool USaskartaCollapseStageSubsystem::StageNow()
{
    UWorld* World = GetWorld();
    USaskartaEventRunner* R = Runner.Get();
    const USaskartaStoryAsset* Story = R ? R->GetStory() : nullptr;
    APlayerController* PC = World ? World->GetFirstPlayerController() : nullptr;
    APawn* Pawn = PC ? PC->GetPawn() : nullptr;
    USplineComponent* Spline = R ? R->GetRoadSpline() : nullptr;
    if (!World || !Story || !Pawn || !Spline)
    {
        UE_LOG(LogSaskartaCollapse, Warning, TEXT("collapse stage skipped: %s"),
            !Story ? TEXT("no story") : !Pawn ? TEXT("no pawn") : TEXT("no road spline"));
        return false;
    }
    const FSaskartaCollapseStageDef& Def = Story->CollapseStage;
    if (!Def.bEnabled)
    {
        return false;
    }
    const float UeM = FSaskartaEventLogic::UeMFromRoadM(Story->RoadMToUeM, Def.RoadM);
    if (UeM < 0.f)
    {
        UE_LOG(LogSaskartaCollapse, Warning, TEXT("collapse stage skipped: road %.0f m has no UE distance"), Def.RoadM);
        return false;
    }
    LastStageS = World->GetTimeSeconds();

    // Any in-flight drone feed / fall sequence ends here (it also restores a tipped carrier mesh).
    if (USaskartaDroneSequenceSubsystem* Drone = World->GetSubsystem<USaskartaDroneSequenceSubsystem>())
    {
        Drone->StopSequence();
    }

    // The pose on the spline.
    const float Len = Spline->GetSplineLength();
    const float D = FMath::Clamp(UeM * 100.f, 0.f, Len);
    const FVector OnSpline = Spline->GetLocationAtDistanceAlongSpline(D, ESplineCoordinateSpace::World);
    const FVector Tangent = Spline->GetTangentAtDistanceAlongSpline(D, ESplineCoordinateSpace::World);
    const FVector Behind = Spline->GetLocationAtDistanceAlongSpline(FMath::Max(0.f, D - SaskartaCollapseStage::ChordCm), ESplineCoordinateSpace::World);
    const FVector Ahead = Spline->GetLocationAtDistanceAlongSpline(FMath::Min(Len, D + SaskartaCollapseStage::ChordCm), ESplineCoordinateSpace::World);
    const FSaskartaCollapsePose Pose = FSaskartaCollapseStageLogic::Pose(Def, OnSpline, Tangent, Behind, Ahead);

    // The ground: six landscape columns (4 carrier wheels, 2 capsule wheels).
    FCollisionQueryParams Params(SCENE_QUERY_STAT(SaskartaCollapseStage), false, Pawn);
    TArray<AActor*> Attached;
    Pawn->GetAttachedActors(Attached, true, true);
    Params.AddIgnoredActors(Attached);
    TArray<FVector2D> Local;
    FSaskartaCollapseStageLogic::Footprint(Def, Local);
    double Z[6] = { 0, 0, 0, 0, 0, 0 };
    bool bHit[6] = { false, false, false, false, false, false };
    const float Top = Pose.Centre.Z + FMath::Max(0.f, Def.TraceUpCm);
    const float Bottom = Pose.Centre.Z - FMath::Max(0.f, Def.TraceDownCm);
    for (int32 I = 0; I < Local.Num() && I < 6; ++I)
    {
        bHit[I] = SaskartaCollapseStage::TraceLandscape(World, FSaskartaCollapseStageLogic::FootprintWorld(Pose, Local[I]), Top, Bottom, Params, Z[I]);
    }
    // The capsule rests on the ground under its centre (where the movement component settles it, so the
    // sequence origin taken from the pawn's feet next step is already final); the body is fitted to the four
    // wheel columns by the pawn's UpdateGround. No centre hit: the highest wheel hit; none: the spline.
    double Support = Pose.Centre.Z;
    double WheelTop = Pose.Centre.Z;
    double Spread = 0.0;
    const bool bWheels = SaskartaCollapseStageMath::SupportZ(Z, bHit, 4, WheelTop, Spread);
    double CentreZ = 0.0;
    if (SaskartaCollapseStage::TraceLandscape(World, Pose.Centre, Top, Bottom, Params, CentreZ))
    {
        Support = CentreZ;
    }
    else if (bWheels)
    {
        Support = WheelTop;
    }
    else
    {
        UE_LOG(LogSaskartaCollapse, Warning, TEXT("collapse stage: no landscape under the carrier; the spline z is used"));
    }
    const double Front = (bHit[0] && bHit[1]) ? 0.5 * (Z[0] + Z[1]) : Support;
    const double Rear = (bHit[2] && bHit[3]) ? 0.5 * (Z[2] + Z[3]) : Support;
    const float SlopeDeg = static_cast<float>(SaskartaCollapseStageMath::SlopeDeg(Front, Rear, Def.WheelFrontCm - Def.WheelRearCm));

    const float HalfHeight = Pawn->GetSimpleCollisionHalfHeight();
    const FVector Dest(Pose.Centre.X, Pose.Centre.Y, SaskartaCollapseStageMath::ActorZ(Support, HalfHeight, Def.LiftCm));
    const FRotator Rot(0.f, Pose.YawDeg, 0.f);
    const FVector From = Pawn->GetActorLocation();
    const double Moved = FVector::Dist(From, Dest);
    const bool bCover = SaskartaCollapseStageMath::NeedsCover(Moved, Def.CoverBeyondM);

    // Cover first, so the frame the teleport renders on is already black.
    if (bCover && PC->PlayerCameraManager)
    {
        PC->PlayerCameraManager->SetManualCameraFade(1.f, FLinearColor::Black, false);
        PendingFadeS = FMath::Max(0.05f, Def.CoverFadeS);
        World->GetTimerManager().SetTimer(FadeTimer, this, &USaskartaCollapseStageSubsystem::FadeBackIn, FMath::Max(0.01f, Def.CoverHoldS), false);
    }

    // Stopped and settled.
    ACharacter* Carrier = Cast<ACharacter>(Pawn);
    UCharacterMovementComponent* Move = Carrier ? Carrier->GetCharacterMovement() : nullptr;
    if (Move)
    {
        Move->StopMovementImmediately();
        Move->ConsumeInputVector();
    }
    Pawn->SetActorLocationAndRotation(Dest, Rot, false, nullptr, ETeleportType::ResetPhysics);
    PC->SetControlRotation(Rot);
    if (Move)
    {
        Move->StopMovementImmediately();
        if (Move->MovementMode != MOVE_None)
        {
            Move->SetMovementMode(MOVE_Walking);
        }
    }

    // The mesh's tilt and height stay with the carrier's own UpdateGround (30 Hz, it keeps running through the
    // cinematic: StopAnimDriver clears only the AnimTimer), which fits the body to the ground under its wheels
    // here within ~0.5 s, well before the exterior at 3.5 s. A drone fall's tipped mesh was restored above.
    USkeletalMeshComponent* Mesh = Carrier ? Carrier->GetMesh() : nullptr;

    // World Partition maps may omit the parked Keeper actor. The carrier's SpawnTravellerInCapsule hook
    // finds it by class after CIN_18; make that handoff deterministic before the cinematic starts.
    // Loading this Blueprint from the subsystem CDO runs before PCGModule has started in editor
    // commandlets. Resolve it only during gameplay, after engine modules are initialized.
    if (!TravellerClass)
    {
        TravellerClass = LoadClass<ACharacter>(nullptr,
            TEXT("/Game/SaskartaGaea/Characters/Traveller/BP_Saskarta_Traveller.BP_Saskarta_Traveller_C"));
    }
    if (TravellerClass && !UGameplayStatics::GetActorOfClass(World, TravellerClass))
    {
        FActorSpawnParameters Spawn;
        Spawn.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
        ACharacter* Traveller = World->SpawnActor<ACharacter>(TravellerClass, Dest, Rot, Spawn);
        if (Traveller)
        {
            Traveller->SetActorHiddenInGame(true);
            Traveller->SetActorEnableCollision(false);
            if (UCharacterMovementComponent* TravellerMove = Traveller->GetCharacterMovement())
            {
                TravellerMove->DisableMovement();
            }
            UE_LOG(LogSaskartaCollapse, Log, TEXT("spawned hidden Keeper for capsule handoff: %s"), *Traveller->GetName());
        }
        else
        {
            UE_LOG(LogSaskartaCollapse, Error, TEXT("could not spawn Keeper for capsule handoff"));
        }
    }
    else if (!TravellerClass)
    {
        UE_LOG(LogSaskartaCollapse, Error, TEXT("Keeper class is missing; CIN_19 cannot hand back to human play"));
    }

    // The animation: no motion, the road's slope, the hitch straight, the capsule's ground re-read.
    if (USaskartaCarrierAnimInstance* Anim = Mesh ? Cast<USaskartaCarrierAnimInstance>(Mesh->GetAnimInstance()) : nullptr)
    {
        FSaskartaCarrierAnimInputs In = Anim->Inputs;
        In.Speed = 0.f;
        In.Accel = 0.f;
        In.YawRate = 0.f;
        In.Steer = 0.f;
        In.Slope = SlopeDeg;
        // Ground* stay the pawn's own traces (only their changes drive the bounce); the trailer's are re-read below.
        In.bHasTrailerGround = false;
        Anim->SetCarrierInputs(In);
        Anim->SetWheelSpinLocked(true);
        if (!TrailerAnim.IsValid())
        {
            bSavedTrailer = Anim->Tuning.bTrailer;
        }
        TrailerAnim = Anim;
        Anim->Tuning.bTrailer = false; // the hitch model zeroes its angle while off (SaskartaCarrierAnimInstance.cpp)
        Anim->UpdateTrailerGround();
        World->GetTimerManager().SetTimer(TrailerTimer, this, &USaskartaCollapseStageSubsystem::RestoreTrailer, SaskartaCollapseStage::TrailerOffS, false);
    }

    // The motor layers wind down as the carrier dies. FadeOut controls the component's internal
    // fader even while the Blueprint's 30 Hz audio step continues to update its mix.
    static const FName MotorNames[] = { TEXT("AC_Idle"), TEXT("AC_Low"), TEXT("AC_High"), TEXT("AC_Strain") };
    TArray<UAudioComponent*> AudioComponents;
    Pawn->GetComponents(AudioComponents);
    for (UAudioComponent* Audio : AudioComponents)
    {
        bool bMotor = false;
        for (const FName Name : MotorNames) bMotor |= Audio && Audio->GetFName() == Name;
        if (bMotor && Audio->IsPlaying())
        {
            Audio->FadeOut(1.4f, 0.f);
        }
    }

    if (CollapseSmoke && SmokeEmitters.IsEmpty() && Mesh)
    {
        // P_Smoke emits three dark sprites per second at 70-110 cm before scale. The old 0.28-scale
        // emitters started inside the shell and barely cleared it. Put restrained leaks above the two
        // motor vents and the bent drawbar, attached so they follow the shutdown animation.
        struct FLeak { FName Bone; FVector Offset; float Scale; };
        const FLeak Leaks[] = {
            { TEXT("body"), FVector(-42.f, 72.f, 92.f), 0.62f },
            { TEXT("body"), FVector(37.f, 46.f, 84.f), 0.50f },
            { TEXT("coupler"), FVector(0.f, 0.f, 54.f), 0.42f },
        };
        for (const FLeak& Leak : Leaks)
        {
            if (UParticleSystemComponent* Emitter = UGameplayStatics::SpawnEmitterAttached(
                CollapseSmoke, Mesh, Leak.Bone, Leak.Offset, FRotator::ZeroRotator,
                FVector(Leak.Scale), EAttachLocation::KeepRelativeOffset, false))
            {
                SmokeEmitters.Add(Emitter);
            }
        }
        UE_LOG(LogSaskartaCollapse, Log, TEXT("collapse smoke: %d dark leaks active on carrier mesh"), SmokeEmitters.Num());
    }

    UE_LOG(LogSaskartaCollapse, Log,
        TEXT("collapse stage: road %.0f m (UE %.1f m), moved %.1f m (%s), at (%.0f, %.0f, %.0f) yaw %.1f (road %.1f), ground z %.0f, wheel spread %.0f cm, slope %.1f deg, capsule ground %s %.0f / %s %.0f"),
        Def.RoadM, UeM, Moved / 100.0, bCover ? TEXT("covered") : TEXT("in view"), Dest.X, Dest.Y, Dest.Z, Pose.YawDeg, Pose.RoadYawDeg,
        Support, Spread, SlopeDeg, bHit[4] ? TEXT("") : TEXT("miss"), Z[4], bHit[5] ? TEXT("") : TEXT("miss"), Z[5]);
    return true;
}

bool USaskartaCollapseStageSubsystem::EnsureHumanHandoff(APlayerController* PC, APawn* Carrier)
{
    UWorld* World = GetWorld();
    if (!TravellerClass)
    {
        TravellerClass = LoadClass<ACharacter>(nullptr,
            TEXT("/Game/SaskartaGaea/Characters/Traveller/BP_Saskarta_Traveller.BP_Saskarta_Traveller_C"));
    }
    if (!World || !PC || !TravellerClass)
    {
        UE_LOG(LogSaskartaCollapse, Error, TEXT("CIN_19 Keeper handoff missing world, controller, or class"));
        return false;
    }

    ACharacter* Traveller = Cast<ACharacter>(UGameplayStatics::GetActorOfClass(World, TravellerClass));
    if (!Traveller)
    {
        FActorSpawnParameters Spawn;
        Spawn.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
        Traveller = World->SpawnActor<ACharacter>(TravellerClass, Carrier ? Carrier->GetActorLocation() : FVector::ZeroVector,
            Carrier ? Carrier->GetActorRotation() : FRotator::ZeroRotator, Spawn);
    }
    if (!Traveller)
    {
        UE_LOG(LogSaskartaCollapse, Error, TEXT("CIN_19 Keeper handoff could not find or spawn Traveller"));
        return false;
    }

    const bool bNeedsPossession = PC->GetPawn() != Traveller;
    FVector Stand = Traveller->GetActorLocation();
    if (bNeedsPossession && Carrier)
    {
        // The blueprint normally positions him beside the hatch. This also works when its cached
        // Traveller reference was absent or a skipped sequence bypassed that placement.
        Stand = Carrier->GetActorLocation() - Carrier->GetActorRightVector() * 110.f;
    }
    FCollisionQueryParams Params(SCENE_QUERY_STAT(SaskartaKeeperGround), false);
    Params.AddIgnoredActor(Traveller);
    if (Carrier) Params.AddIgnoredActor(Carrier);
    double GroundZ = 0.0;
    const float TopZ = (Carrier ? Carrier->GetActorLocation().Z : Stand.Z) + 3000.f;
    if (SaskartaCollapseStage::TraceLandscape(World, Stand, TopZ, TopZ - 9000.f, Params, GroundZ))
    {
        Stand.Z = GroundZ + Traveller->GetCapsuleComponent()->GetScaledCapsuleHalfHeight() + 2.f;
    }
    else
    {
        UE_LOG(LogSaskartaCollapse, Warning, TEXT("CIN_19 Keeper ground trace missed at %s"), *Stand.ToString());
    }

    Traveller->SetActorEnableCollision(false);
    Traveller->SetActorLocationAndRotation(Stand, Carrier ? Carrier->GetActorRotation() : Traveller->GetActorRotation(),
        false, nullptr, ETeleportType::ResetPhysics);
    Traveller->SetActorHiddenInGame(false);
    Traveller->SetActorEnableCollision(true);
    if (UCharacterMovementComponent* Move = Traveller->GetCharacterMovement())
    {
        Move->SetMovementMode(MOVE_Walking);
    }
    if (bNeedsPossession)
    {
        PC->Possess(Traveller);
        PC->SetControlRotation(FRotator(-8.f, Carrier ? Carrier->GetActorRotation().Yaw : Traveller->GetActorRotation().Yaw, 0.f));
    }
    UE_LOG(LogSaskartaCollapse, Log, TEXT("CIN_19 Keeper handoff: %s at %s; possessed=%s"),
        *Traveller->GetName(), *Stand.ToString(), PC->GetPawn() == Traveller ? TEXT("yes") : TEXT("no"));
    return bNeedsPossession;
}

void USaskartaCollapseStageSubsystem::RestoreTrailer()
{
    if (USaskartaCarrierAnimInstance* Anim = TrailerAnim.Get())
    {
        Anim->Tuning.bTrailer = bSavedTrailer;
    }
    TrailerAnim.Reset();
}

void USaskartaCollapseStageSubsystem::FadeBackIn()
{
    const UWorld* World = GetWorld();
    APlayerController* PC = World ? World->GetFirstPlayerController() : nullptr;
    if (PC && PC->PlayerCameraManager)
    {
        PC->PlayerCameraManager->StartCameraFade(1.f, 0.f, PendingFadeS, FLinearColor::Black, false, false);
    }
}
