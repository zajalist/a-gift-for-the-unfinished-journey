#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "SaskartaDustFront.generated.h"

class ULocalFogVolumeComponent;
class USaskartaDustBillows;

/** Eight world-positioned fog lobes with ten optional small six-way billows. No camera shell or simulation grid. */
UCLASS()
class SASKARTACORE_API ASaskartaDustFront : public AActor
{
    GENERATED_BODY()
public:
    ASaskartaDustFront();

    /** Centre is the ground point at FrontRoadM; RouteForward points toward increasing road metres.
     * Root updates only while the chase advances, and destroys this actor when it ends. */
    void UpdateFront(FVector Centre, FVector RouteForward, float GapM);

    static constexpr int32 MaxLobes = 8;

protected:
    virtual void BeginPlay() override;
    virtual void EndPlay(const EEndPlayReason::Type EndPlayReason) override;

private:
    UPROPERTY(Transient) TObjectPtr<USaskartaDustBillows> Billows;
    UPROPERTY(VisibleAnywhere, Category="Dust Front")
    TArray<TObjectPtr<ULocalFogVolumeComponent>> Lobes;
    float RollTimeS = 0.f;
    double LastUpdateWorldS = -1.0;
    double LastShapeWorldS = -1.0;
};
