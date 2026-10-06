// 2026-10-05: the transmission made visible. Expanding shells of light leave the high-voice antenna
// every Period seconds for Duration seconds, grow to MaxRadiusCm and fade (M_RadioWave, param "Fade").
#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "SaskartaRadioWaves.generated.h"

class UStaticMesh;
class UMaterialInterface;
class UStaticMeshComponent;
class UMaterialInstanceDynamic;
class UPointLightComponent;

UCLASS()
class SASKARTACORE_API ASaskartaRadioWaves : public AActor
{
    GENERATED_BODY()
public:
    ASaskartaRadioWaves();
    virtual void Tick(float DeltaSeconds) override;

    UPROPERTY(EditAnywhere, Category = "Saskarta|Waves") float Period = 0.85f;
    UPROPERTY(EditAnywhere, Category = "Saskarta|Waves") float Duration = 14.f;
    UPROPERTY(EditAnywhere, Category = "Saskarta|Waves") float Lifetime = 6.5f;
    UPROPERTY(EditAnywhere, Category = "Saskarta|Waves") float MaxRadiusCm = 60000.f;

private:
    struct FWave { TObjectPtr<UStaticMeshComponent> Comp; TObjectPtr<UMaterialInstanceDynamic> MID; float Age = 0.f; };
    TArray<FWave> Waves;
    UPROPERTY(Transient) TArray<TObjectPtr<UStaticMeshComponent>> Pool;
    UPROPERTY(Transient) TArray<TObjectPtr<UMaterialInstanceDynamic>> MIDs;
    UPROPERTY(Transient) TObjectPtr<UStaticMesh> Sphere;
    UPROPERTY(Transient) TObjectPtr<UMaterialInterface> WaveMat;
    UPROPERTY(Transient) TObjectPtr<UPointLightComponent> Glow;
    float Elapsed = 0.f;
    float NextSpawn = 0.f;
    void Spawn();
};
