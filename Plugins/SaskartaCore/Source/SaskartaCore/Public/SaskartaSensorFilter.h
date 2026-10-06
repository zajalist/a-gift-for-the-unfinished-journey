// Drives the CRT and optical glass on PPV_Saskarta_Sensor from the Sensor filter setting and flow state.
#pragma once

#include "CoreMinimal.h"
#include "Subsystems/WorldSubsystem.h"
#include "SaskartaSensorFilter.generated.h"

class APostProcessVolume;
class UMaterialInstanceDynamic;
class USaskartaEventRunner;

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
    UFUNCTION()
    void HandleCinematicChanged(FName Id);
    UFUNCTION()
    void HandleModeChanged(FName Mode, bool bOn);

    TWeakObjectPtr<USaskartaEventRunner> BoundRunner;
    TWeakObjectPtr<APostProcessVolume> Volume;
    UPROPERTY(Transient)
    TObjectPtr<UMaterialInstanceDynamic> Mid;
    UPROPERTY(Transient)
    TObjectPtr<UMaterialInstanceDynamic> GlassMid;
    int32 CrtIndex = INDEX_NONE;
    int32 GlassIndex = INDEX_NONE;
    float LastAmount = -1.f;
    float LastGlassAmount = -1.f;
    FTimerHandle Timer;
};
