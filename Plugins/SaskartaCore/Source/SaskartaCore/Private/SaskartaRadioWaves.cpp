#include "SaskartaRadioWaves.h"

#include "Components/PointLightComponent.h"
#include "Components/SceneComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Engine/StaticMesh.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Materials/MaterialInterface.h"

ASaskartaRadioWaves::ASaskartaRadioWaves()
{
    PrimaryActorTick.bCanEverTick = true;
    RootComponent = CreateDefaultSubobject<USceneComponent>(TEXT("Root"));
    Glow = CreateDefaultSubobject<UPointLightComponent>(TEXT("Glow"));
    Glow->SetupAttachment(RootComponent);
    Glow->SetIntensity(0.f);
    Glow->SetAttenuationRadius(6000.f);
    Glow->SetLightColor(FLinearColor(1.f, 0.62f, 0.28f));
    Glow->SetCastShadows(false);
}

void ASaskartaRadioWaves::Spawn()
{
    if (!Sphere) Sphere = LoadObject<UStaticMesh>(nullptr, TEXT("/Engine/BasicShapes/Sphere.Sphere"));
    if (!WaveMat) WaveMat = LoadObject<UMaterialInterface>(nullptr, TEXT("/Game/Submission1005/FX/M_RadioWave.M_RadioWave"), nullptr, LOAD_NoWarn | LOAD_Quiet);
    if (!Sphere || !WaveMat) return;
    UStaticMeshComponent* C = NewObject<UStaticMeshComponent>(this);
    C->SetStaticMesh(Sphere);
    C->SetCollisionEnabled(ECollisionEnabled::NoCollision);
    C->SetCastShadow(false);
    C->SetupAttachment(RootComponent);
    C->RegisterComponent();
    UMaterialInstanceDynamic* M = UMaterialInstanceDynamic::Create(WaveMat, this);
    C->SetMaterial(0, M);
    C->SetRelativeScale3D(FVector(0.2f));
    C->SetBoundsScale(4.f);
    Pool.Add(C); MIDs.Add(M);
    Waves.Add({ C, M, 0.f });
}

void ASaskartaRadioWaves::Tick(float DeltaSeconds)
{
    Super::Tick(DeltaSeconds);
    Elapsed += DeltaSeconds;
    if (Elapsed < Duration && Elapsed >= NextSpawn)
    {
        Spawn();
        NextSpawn = Elapsed + Period;
    }
    // the antenna breathes with each pulse
    const float Phase = FMath::Fmod(Elapsed, Period) / Period;
    Glow->SetIntensity(Elapsed < Duration ? 40000.f * FMath::Square(1.f - Phase) : FMath::Max(0.f, Glow->Intensity - DeltaSeconds * 40000.f));
    for (int32 I = Waves.Num() - 1; I >= 0; --I)
    {
        FWave& W = Waves[I];
        W.Age += DeltaSeconds;
        const float T = FMath::Clamp(W.Age / Lifetime, 0.f, 1.f);
        const float R = FMath::Lerp(20.f, MaxRadiusCm, FMath::Pow(T, 0.6f));
        if (W.Comp) W.Comp->SetRelativeScale3D(FVector(R / 50.f)); // engine sphere radius 50 cm
        if (W.MID) W.MID->SetScalarParameterValue(TEXT("Fade"), FMath::Sin(T * PI) * (1.f - T * 0.5f));
        if (T >= 1.f)
        {
            if (W.Comp) W.Comp->DestroyComponent();
            Waves.RemoveAt(I);
        }
    }
    if (Elapsed > Duration + Lifetime + 1.f) Destroy();
}
