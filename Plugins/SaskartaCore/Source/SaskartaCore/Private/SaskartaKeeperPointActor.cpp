#include "SaskartaKeeperPointActor.h"

#include "Animation/SkeletalMeshActor.h"
#include "Components/SceneCaptureComponent2D.h"
#include "Components/StaticMeshComponent.h"
#include "Engine/SceneCapture2D.h"
#include "NiagaraComponent.h"
#include "NiagaraFunctionLibrary.h"
#include "TimerManager.h"

ASaskartaKeeperPointActor::ASaskartaKeeperPointActor(const FObjectInitializer& ObjectInitializer)
    : Super(ObjectInitializer)
{
    if (UNiagaraComponent* Points = GetNiagaraComponent())
    {
        Points->SetAutoActivate(false);
    }
    StaffSource = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("StaffPointSource"));
    StaffSource->SetupAttachment(GetRootComponent());
    StaffSource->SetCollisionEnabled(ECollisionEnabled::NoCollision);
    StaffSource->SetHiddenInGame(true);
    StaffSource->SetVisibility(false);
}

void ASaskartaKeeperPointActor::BeginPlay()
{
    Super::BeginPlay();
    UNiagaraComponent* Points = GetNiagaraComponent();
    USkeletalMeshComponent* Source = SourceActor ? SourceActor->GetSkeletalMeshComponent() : nullptr;
    if (!Points || !Source || !CaptureActor || !StaffSource || !StaffSource->GetStaticMesh())
    {
        UE_LOG(LogTemp, Warning, TEXT("Keeper points missing Niagara, Traveller, staff, or capture reference"));
        return;
    }
    if (!UNiagaraFunctionLibrary::GetSkeletalMeshDataInterface(Points, TEXT("User.KeeperMesh")))
    {
        UE_LOG(LogTemp, Error, TEXT("Keeper points system is missing User.KeeperMesh skeletal data interface"));
        return;
    }
    // The editor PreviewMesh does not survive cooking. Bind the real animated
    // component to the skeletal-mesh data interface before activating particles.
    UNiagaraFunctionLibrary::OverrideSystemUserVariableSkeletalMeshComponent(
        Points, TEXT("User.KeeperMesh"), Source);
    StaffSource->AttachToComponent(Source, FAttachmentTransformRules::SnapToTargetIncludingScale, FName(TEXT("staff011")));
    UNiagaraFunctionLibrary::OverrideSystemUserVariableStaticMeshComponent(
        Points, TEXT("User.StaffMesh"), StaffSource);
    SyncWithCapture();
    GetWorldTimerManager().SetTimer(SyncTimer, this, &ASaskartaKeeperPointActor::SyncWithCapture, 0.1f, true);
}

void ASaskartaKeeperPointActor::EndPlay(const EEndPlayReason::Type EndPlayReason)
{
    GetWorldTimerManager().ClearTimer(SyncTimer);
    Super::EndPlay(EndPlayReason);
}

void ASaskartaKeeperPointActor::SyncWithCapture()
{
    UNiagaraComponent* Points = GetNiagaraComponent();
    const USceneCaptureComponent2D* Capture = CaptureActor ? CaptureActor->GetCaptureComponent2D() : nullptr;
    if (!Points || !Capture)
    {
        return;
    }
    const bool bVisibleToLoading = Capture->bCaptureEveryFrame && Capture->IsActive();
    if (bVisibleToLoading && !Points->IsActive())
    {
        Points->Activate(true);
    }
    else if (!bVisibleToLoading && Points->IsActive())
    {
        Points->Deactivate();
    }
}
