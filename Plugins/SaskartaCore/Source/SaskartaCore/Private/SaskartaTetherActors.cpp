// The tether's level actors (task TETHER). See SaskartaTetherActors.h.

#include "SaskartaTetherActors.h"

#include "SaskartaTetherSubsystem.h"

#include "Components/SphereComponent.h"
#include "Components/SplineComponent.h"
#include "Engine/CollisionProfile.h"
#include "Engine/World.h"

namespace SaskartaTetherActors
{
    static void Notify(const AActor* A)
    {
        if (UWorld* World = A->GetWorld())
        {
            if (USaskartaTetherSubsystem* T = World->GetSubsystem<USaskartaTetherSubsystem>())
            {
                T->MarkDirty();
            }
        }
    }
}

ASaskartaTetherPath::ASaskartaTetherPath()
{
    PrimaryActorTick.bCanEverTick = false;
    Path = CreateDefaultSubobject<USplineComponent>(TEXT("Path"));
    RootComponent = Path;
    // A logic-only line: never drawn in game (the spline proxy showed as a white line with vertex dots in PIE).
    Path->bDrawDebug = false;
    Path->SetHiddenInGame(true);
    SetActorHiddenInGame(true);
    Tags.Add(USaskartaTetherSubsystem::PathTag);
    SetCanBeDamaged(false);
#if WITH_EDITORONLY_DATA
    // always loaded in World Partition: the tether must see every spur, wherever the carrier is
    bIsSpatiallyLoaded = false;
#endif
}

void ASaskartaTetherPath::BeginPlay()
{
    Super::BeginPlay();
    SaskartaTetherActors::Notify(this);
}

void ASaskartaTetherPath::EndPlay(const EEndPlayReason::Type EndPlayReason)
{
    SaskartaTetherActors::Notify(this);
    Super::EndPlay(EndPlayReason);
}

ASaskartaExploreZone::ASaskartaExploreZone()
{
    PrimaryActorTick.bCanEverTick = false;
    Zone = CreateDefaultSubobject<USphereComponent>(TEXT("Zone"));
    Zone->InitSphereRadius(RadiusCm);
    Zone->SetCollisionProfileName(UCollisionProfile::NoCollision_ProfileName);
    Zone->SetGenerateOverlapEvents(false);
    Zone->SetCanEverAffectNavigation(false);
    Zone->SetHiddenInGame(true);
    Zone->ShapeColor = FColor(80, 200, 120);
    RootComponent = Zone;
    Tags.Add(USaskartaTetherSubsystem::ZoneTag);
    SetCanBeDamaged(false);
#if WITH_EDITORONLY_DATA
    bIsSpatiallyLoaded = false;
#endif
}

void ASaskartaExploreZone::OnConstruction(const FTransform& Transform)
{
    Super::OnConstruction(Transform);
    if (Zone)
    {
        Zone->SetSphereRadius(RadiusCm);
    }
}

void ASaskartaExploreZone::BeginPlay()
{
    Super::BeginPlay();
    SaskartaTetherActors::Notify(this);
}

void ASaskartaExploreZone::EndPlay(const EEndPlayReason::Type EndPlayReason)
{
    SaskartaTetherActors::Notify(this);
    Super::EndPlay(EndPlayReason);
}
