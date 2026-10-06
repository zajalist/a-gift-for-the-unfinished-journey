#pragma once

#include "NiagaraActor.h"
#include "TimerManager.h"
#include "SaskartaKeeperPointActor.generated.h"

class ASkeletalMeshActor;
class ASceneCapture2D;
class UStaticMeshComponent;

/** A loading-only point renderer that follows the saved Traveller animation. */
UCLASS()
class SASKARTACORE_API ASaskartaKeeperPointActor : public ANiagaraActor
{
    GENERATED_BODY()

public:
    ASaskartaKeeperPointActor(const FObjectInitializer& ObjectInitializer);

    UPROPERTY(EditInstanceOnly, BlueprintReadWrite, Category = "Saskarta|Keeper Points")
    TObjectPtr<ASkeletalMeshActor> SourceActor;

    UPROPERTY(EditInstanceOnly, BlueprintReadWrite, Category = "Saskarta|Keeper Points")
    TObjectPtr<ASceneCapture2D> CaptureActor;

    /** Hidden mesh whose vertices feed the second, staff-only point emitter. */
    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Saskarta|Keeper Points")
    TObjectPtr<UStaticMeshComponent> StaffSource;

protected:
    virtual void BeginPlay() override;
    virtual void EndPlay(const EEndPlayReason::Type EndPlayReason) override;

private:
    void SyncWithCapture();

    FTimerHandle SyncTimer;
};
