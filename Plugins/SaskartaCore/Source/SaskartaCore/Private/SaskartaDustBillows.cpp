#include "SaskartaDustBillows.h"
#include "SaskartaEarlyStorm.h"
#include "Components/LocalFogVolumeComponent.h"
#include "Engine/World.h"
#include "GameFramework/Actor.h"

USaskartaDustBillows::USaskartaDustBillows() {}

void USaskartaDustBillows::Initialize(AActor* Front)
{
    Shutdown();
    if (!Front || !Front->GetWorld() || !Front->GetWorld()->IsGameWorld()) return;
    OwnerFront = Front;
    // UE5.8 LocalFogVolumeSceneProxy uses the largest scale axis for ALL axes.
    // A stretched sheet is therefore still a sphere. Keep three native volumes,
    // put their circular bounds far behind the front, and shape the visible crown
    // with height extinction (the shader requires BOTH radial and height terms).
    for (int32 Index = 0; Index < 7; ++Index)
    {
        ULocalFogVolumeComponent* Fog = NewObject<ULocalFogVolumeComponent>(Front,
            FName(*FString::Printf(TEXT("ContinuousDustFront%d"), Index)));
        Fog->SetupAttachment(Front->GetRootComponent());
        Fog->SetMobility(EComponentMobility::Movable);
        Fog->RadialFogExtinction = 0.f;
        Fog->HeightFogExtinction = 0.f;
        // Renderer converts this UI falloff by .01. At a 900m radius, 90 gives
        // a 10m vertical e-fold: the upper spherical outline has no visible fog.
        // 2026-10-05: seven overlapping strata of different sizes instead of three equal domes, with a
        // steeper vertical fade (~6 m e-fold) so no lobe shows a round crown against the sky.
        // 2026-10-05: the spherical lobes are gone, so these strata carry the whole wall: ~25 m e-fold
        // (was ~6 m). At 1 km radius the dome top is still far above any visible density.
        Fog->HeightFogFalloff = 3600.f;
        const float HeightOffsets[] = { .014f, .022f, .011f, .019f, .016f, .024f, .013f };
        Fog->HeightFogOffset = HeightOffsets[Index];
        Fog->FogPhaseG = .08f;
        Fog->FogAlbedo = FLinearColor(.24f, .22f, .18f);
        Fog->FogEmissive = FLinearColor::Black;
        Fog->FogStartDistance = 0.f;
        Fog->FogSortPriority = 0;
        Front->AddInstanceComponent(Fog);
        Fog->RegisterComponent();
        Masses.Add(Fog);
    }
}

void USaskartaDustBillows::Update(const FTransform& FrontFrame, float ActiveTimeS, float Near)
{
    AActor* Front = OwnerFront.Get();
    UWorld* World = Front ? Front->GetWorld() : nullptr;
    if (!World || World->IsPaused() || FrontFrame.ContainsNaN()
        || !FMath::IsFinite(ActiveTimeS) || !FMath::IsFinite(Near)) return;
    const USaskartaEarlyStormSubsystem* Storm = World->GetSubsystem<USaskartaEarlyStormSubsystem>();
    const float Alpha = Storm ? Storm->GetFrontPresentationAlpha() : 1.f;
    for (int32 Index = 0; Index < Masses.Num(); ++Index)
    {
        // Broad overlapping ground strata: a continuous >2km front, with no
        // exposed cloud balls. Relative -X is behind the supplied route-forward
        // anchor. Its leading ground intersection never passes that anchor.
        const float Phase = ActiveTimeS * .11f + Index * 1.7f;
        const float Radii[] = { 1150.f, 820.f, 980.f, 760.f, 1060.f, 880.f, 940.f };
        const float Sides[] = { -1.f, -.62f, -.31f, 0.f, .33f, .66f, 1.f };
        const float RecessM[] = { 4.f, 22.f, 9.f, 15.f, 6.f, 26.f, 11.f };
        const float RadiusM = Radii[Index] * (1.f + .01f * FMath::Sin(Phase * .5f));
        const float HeightM = 2.f * FMath::Sin(Phase * .7f);
        const float BehindM = FMath::Sqrt(RadiusM * RadiusM - HeightM * HeightM)
            + RecessM[Index] + 2.f * (1.f + FMath::Sin(Phase));
        const FVector Position(-BehindM, Sides[Index] * 1250.f + 40.f * FMath::Sin(Phase * .37f), HeightM);
        ULocalFogVolumeComponent* Fog = Masses[Index];
        Fog->SetRelativeTransform(FTransform(FQuat::Identity, Position * 100.f,
            FVector(RadiusM * 100.f / ULocalFogVolumeComponent::GetBaseVolumeSize())));
        const float RadialExtinction = 4.2f * Alpha; // more strata overlap: each one thinner, softer edges
        const float HeightExtinction = .08f * Alpha;
        if (!FMath::IsNearlyEqual(Fog->RadialFogExtinction, RadialExtinction, .03f)
            || !FMath::IsNearlyEqual(Fog->HeightFogExtinction, HeightExtinction, .0003f))
        {
            Fog->SetRadialFogExtinction(RadialExtinction);
            Fog->SetHeightFogExtinction(HeightExtinction);
        }
    }
}

void USaskartaDustBillows::Shutdown()
{
    for (ULocalFogVolumeComponent* Fog : Masses) if (IsValid(Fog)) Fog->DestroyComponent();
    Masses.Reset();
    OwnerFront.Reset();
}

void USaskartaDustBillows::BeginDestroy()
{
    // The owning front's EndPlay releases registered components before GC.
    Super::BeginDestroy();
}
