// LANE5 (queued): drives LANE4's sensor look (MI_PP_SensorCRT on PPV_Saskarta_Sensor) from the Sensor filter
// setting (cvar saskarta.sensorfilter) and the flow state: off on the title, menus, loading, cards and the ending.
#pragma once

#include "CoreMinimal.h"
#include "Subsystems/WorldSubsystem.h"
#include "SaskartaSensorFilter.generated.h"

class APostProcessVolume;
class UMaterialInstanceDynamic;

UCLASS()
class SASKARTACORE_API USaskartaSensorFilterSubsystem : public UWorldSubsystem
{
    GENERATED_BODY()

public:
    virtual bool ShouldCreateSubsystem(UObject* Outer) const override;
    virtual void OnWorldBeginPlay(UWorld& InWorld) override;
    virtual void Deinitialize() override;

    /** The MI's Amount for a setting level (0-3) in a flow state. Pure, tested. */
    static float AmountFor(int32 Level, FName FlowState);

private:
    void Poll();
    bool Bind();

    TWeakObjectPtr<APostProcessVolume> Volume;
    UPROPERTY(Transient)
    TObjectPtr<UMaterialInstanceDynamic> Mid;
    float LastAmount = -1.f;
    FTimerHandle Timer;
};
