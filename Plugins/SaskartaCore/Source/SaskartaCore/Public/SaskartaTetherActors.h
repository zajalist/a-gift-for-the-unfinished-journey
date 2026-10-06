// The tether's level actors (task TETHER). Tools/World/make_tether_paths.py writes the editor scripts
// that place them for the six reachable off-road POIs. Both are always loaded (not spatially loaded in
// World Partition), so the tether sees every spur from the start, and both register with
// USaskartaTetherSubsystem at BeginPlay.

#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"

#include "SaskartaTetherActors.generated.h"

class USphereComponent;
class USplineComponent;

/** A marked spur the carrier may walk: a spline from the road junction (point 0) to a POI. Tag Saskarta.TetherPath. */
UCLASS(Blueprintable, meta = (DisplayName = "Saskarta Tether Path"))
class SASKARTACORE_API ASaskartaTetherPath : public AActor
{
    GENERATED_BODY()

public:
    ASaskartaTetherPath();

    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Saskarta|Tether")
    TObjectPtr<USplineComponent> Path;

    /** The POI this spur leads to (O01, O03, ...). */
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Saskarta|Tether")
    FName PoiId;

protected:
    virtual void BeginPlay() override;
    virtual void EndPlay(const EEndPlayReason::Type EndPlayReason) override;
};

/** An exploration zone around a POI: the tether reads 0 inside RadiusCm (XY). Tag Saskarta.ExploreZone. */
UCLASS(Blueprintable, meta = (DisplayName = "Saskarta Explore Zone"))
class SASKARTACORE_API ASaskartaExploreZone : public AActor
{
    GENERATED_BODY()

public:
    ASaskartaExploreZone();

    /** The editor view of the zone (no collision, hidden in game); its radius follows RadiusCm. */
    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Saskarta|Tether")
    TObjectPtr<USphereComponent> Zone;

    /** The zone radius in cm (the POI radius + 25 m in the set-dressing plan). */
    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Saskarta|Tether", meta = (ClampMin = "100.0"))
    float RadiusCm = 5000.f;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Saskarta|Tether")
    FName PoiId;

    virtual void OnConstruction(const FTransform& Transform) override;

protected:
    virtual void BeginPlay() override;
    virtual void EndPlay(const EEndPlayReason::Type EndPlayReason) override;
};
