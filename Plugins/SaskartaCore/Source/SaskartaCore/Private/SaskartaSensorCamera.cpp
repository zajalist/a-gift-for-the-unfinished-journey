#include "SaskartaSensorCamera.h"
#include "SaskartaEventRunner.h"
#include "Engine/World.h"

ASaskartaSensorCamera::ASaskartaSensorCamera(const FObjectInitializer& ObjectInitializer)
    : Super(ObjectInitializer.SetDefaultSubobjectClass<USaskartaSensorCameraComponent>(TEXT("CameraComponent")))
{
}

void USaskartaSensorCameraComponent::GetCameraView(float DeltaTime, FMinimalViewInfo& OutResult)
{
    Super::GetCameraView(DeltaTime, OutResult);
    // PlayerCameraManager reads ACameraActor components directly, bypassing
    // Actor::CalcCamera. Apply the measured correction at this common seam.
    const ASaskartaSensorCamera* Sensor = Cast<ASaskartaSensorCamera>(GetOwner());
    if (const UWorld* World = GetWorld(); World && Sensor)
    {
        if (const USaskartaEventRunner* Runner = World->GetSubsystem<USaskartaEventRunner>())
        {
            FVector Correction;
            if (Runner->GetCinematicSensorOffset(Sensor->AuthoredEyeHeightCm, Correction))
                OutResult.Location += Correction;
        }
    }
}
