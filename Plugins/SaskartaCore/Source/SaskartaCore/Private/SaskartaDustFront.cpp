#include "SaskartaDustFront.h"
#include "SaskartaDustBillows.h"

#include "Components/LocalFogVolumeComponent.h"
#include "Components/SceneComponent.h"
#include "Engine/World.h"

namespace SaskartaDustFront
{
    struct FLobe
    {
        float SideM;
        float HeightM;
        float RadiusM;
        float RecessM;
        float Phase;
        bool bCrest;
    };

    // Five ground lobes and three higher billows. Irregular heights and staggered
    // depth avoid a straight sheet silhouette. All transforms remain in the world.
    constexpr FLobe Layout[] = {
        {-155.f, 34.f,  96.f,   0.f, 0.2f, false},
        { -82.f, 27.f,  76.f,   7.f, 2.1f, false},
        {  -8.f, 34.f,  85.f,   0.f, 4.4f, false},
        {  68.f, 30.f, 104.f,  12.f, 1.3f, false},
        { 151.f, 25.f,  82.f,   3.f, 5.7f, false},
        {-107.f,111.f,  77.f, 170.f, 3.0f, true},
        {  12.f,127.f, 105.f, 180.f, 5.0f, true},
        { 118.f,107.f,  92.f, 174.f, 0.8f, true},
    };
    static_assert(UE_ARRAY_COUNT(Layout) == ASaskartaDustFront::MaxLobes, "The front has a fixed eight-volume budget.");
}

ASaskartaDustFront::ASaskartaDustFront()
{
    PrimaryActorTick.bCanEverTick = false;
    SetReplicates(false);
    SetActorEnableCollision(false);
    USceneComponent* Anchor = CreateDefaultSubobject<USceneComponent>(TEXT("FrontGroundAnchor"));
    Anchor->SetMobility(EComponentMobility::Movable);
    SetRootComponent(Anchor);
    // 2026-10-05: the eight spherical lobes read as a row of cloud balls. The front is now only the
    // continuous ground strata in USaskartaDustBillows; Lobes stays empty.
}

void ASaskartaDustFront::BeginPlay()
{
    Super::BeginPlay();
    Billows = NewObject<USaskartaDustBillows>(this);
    Billows->Initialize(this);
}

void ASaskartaDustFront::EndPlay(const EEndPlayReason::Type EndPlayReason)
{
    if (Billows) Billows->Shutdown();
    Billows = nullptr;
    Super::EndPlay(EndPlayReason);
}

void ASaskartaDustFront::UpdateFront(FVector Centre, FVector RouteForward, float GapM)
{
    if (Centre.ContainsNaN() || RouteForward.ContainsNaN() || !FMath::IsFinite(GapM)) return;
    const FVector Forward = RouteForward.GetSafeNormal2D();
    if (Forward.IsNearlyZero()) return;
    // The root follows the supplied actual front, never the camera or carrier.
    SetActorLocationAndRotation(Centre, Forward.Rotation(), false, nullptr, ETeleportType::TeleportPhysics);
    const double Now = GetWorld() ? GetWorld()->GetTimeSeconds() : 0.0;
    if (LastUpdateWorldS >= 0.0)
    {
        const double Delta = Now - LastUpdateWorldS;
        // No visual catch-up after a paused/suppressed interval.
        if (Delta > 0.0 && Delta <= 0.5) RollTimeS += static_cast<float>(Delta);
    }
    LastUpdateWorldS = Now;
    if (LastShapeWorldS >= 0.0 && Now - LastShapeWorldS < 0.1) return;
    LastShapeWorldS = Now;

    const float Near = FMath::Clamp((80.f - GapM) / 80.f, 0.f, 1.f);
    if (Billows) Billows->Update(GetActorTransform(), RollTimeS, Near);
    for (int32 Index = 0; Index < Lobes.Num(); ++Index)
    {
        const SaskartaDustFront::FLobe& Shape = SaskartaDustFront::Layout[Index];
        const float Roll = RollTimeS * (Shape.bCrest ? 0.22f : 0.34f) + Shape.Phase;
        const float Radius = Shape.RadiusM * (1.f + (0.018f + Near * 0.007f) * FMath::Sin(Roll));
        const float Height = Shape.HeightM + FMath::Sin(Roll * 0.73f + 1.7f) * (Shape.bCrest ? 4.f : 2.f);
        const float Side = Shape.SideM + FMath::Sin(Roll * 0.61f) * (Shape.bCrest ? 5.f : 3.f);
        // Ground lobes' leading ground intersection stays at/before FrontRoadM
        // even as they swell. Crest lobes remain farther back with a rising crown.
        const float Behind = Shape.bCrest ? Shape.RecessM
            : FMath::Sqrt(FMath::Max(0.f, Radius * Radius - Height * Height)) + Shape.RecessM;
        const FTransform ShapeTransform(FQuat::Identity, FVector(-Behind, Side, Height) * 100.f,
            FVector(Radius * 100.f / ULocalFogVolumeComponent::GetBaseVolumeSize()));
        Lobes[Index]->SetRelativeTransform(ShapeTransform);
    }
}
