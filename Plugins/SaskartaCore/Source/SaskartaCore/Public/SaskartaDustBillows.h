#pragma once
#include "CoreMinimal.h"
#include "UObject/Object.h"
#include "SaskartaDustBillows.generated.h"

class AActor;
class ULocalFogVolumeComponent;

/** Three overlapping native height strata behind the actual pursuing world front. */
UCLASS()
class SASKARTACORE_API USaskartaDustBillows : public UObject
{
    GENERATED_BODY()
public:
    USaskartaDustBillows();
    void Initialize(AActor* Front);
    void Update(const FTransform& FrontFrame, float ActiveTimeS, float Near);
    void Shutdown();
    virtual void BeginDestroy() override;
private:
    TWeakObjectPtr<AActor> OwnerFront;
    UPROPERTY(Transient) TArray<TObjectPtr<ULocalFogVolumeComponent>> Masses;
};
