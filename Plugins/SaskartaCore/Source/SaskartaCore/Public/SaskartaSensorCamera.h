#pragma once

#include "CoreMinimal.h"
#include "CineCameraActor.h"
#include "CineCameraComponent.h"
#include "SaskartaSensorCamera.generated.h"

UCLASS()
class SASKARTACORE_API USaskartaSensorCameraComponent : public UCineCameraComponent
{
    GENERATED_BODY()
public:
    virtual void GetCameraView(float DeltaTime, FMinimalViewInfo& DesiredView) override;
};

/** A road-cinematic POV whose lens starts at the carrier's measured sensor.
 * The sequence still owns its pan, zoom and small impact offsets. */
UCLASS()
class SASKARTACORE_API ASaskartaSensorCamera : public ACineCameraActor
{
    GENERATED_BODY()
public:
    ASaskartaSensorCamera(const FObjectInitializer& ObjectInitializer);

    UPROPERTY(EditAnywhere, Category = "Saskarta|Camera")
    float AuthoredEyeHeightCm = 120.f;
};
