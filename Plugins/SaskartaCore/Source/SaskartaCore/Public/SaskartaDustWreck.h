#pragma once
#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "SaskartaDustWreck.generated.h"

class ACharacter;
class UPointLightComponent;
class UMaterialInterface;
class UMaterialInstanceDynamic;
class UStaticMesh;

/** An inert visual copy: no controller, drivetrain, radio, passengers or gameplay timers. */
UCLASS()
class SASKARTACORE_API ASaskartaDustWreck : public AActor
{
    GENERATED_BODY()
public:
    ASaskartaDustWreck();
    void BuildFromCarrier(ACharacter* Carrier, const FTransform& LostPose);
    virtual void Tick(float DeltaSeconds) override;
private:
    struct FEmissiveFlicker
    {
        TWeakObjectPtr<UMaterialInstanceDynamic> Material;
        FName ColorParameter;
        FLinearColor Color = FLinearColor::Black;
        float MapWeight = 0.f;
        bool bMapWeight = false;
        int32 Channel = 0;
    };
    UPROPERTY(Transient) TArray<TObjectPtr<UPointLightComponent>> Lamps;
    UPROPERTY(Transient) TObjectPtr<UStaticMesh> FallbackLampMesh;
    UPROPERTY(Transient) TObjectPtr<UMaterialInterface> FallbackLampMaterial;
    TArray<FEmissiveFlicker> EmissiveFlickers;
    bool bBuilt = false;
    float FlickerTime = 0.f;
};
