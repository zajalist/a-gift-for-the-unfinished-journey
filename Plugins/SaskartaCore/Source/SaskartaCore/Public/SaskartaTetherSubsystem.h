// The road tether's allowed ground (task TETHER; docs/world/SETDRESS_PLAN.md section 8).
//
// The carrier may leave BP_Saskarta_Road's spline only along a tether path (an actor tagged
// Saskarta.TetherPath with a spline: ASaskartaTetherPath, placed by Tools/World/make_tether_paths.py)
// or inside an exploration zone (an actor tagged Saskarta.ExploreZone: ASaskartaExploreZone, a sphere
// component, or any volume). BPC_RoadTether keeps its 10 m warning and 20 m reboot, measured with
// GetTetherDistance: the 2D distance to the nearest road or path, 0 inside a zone.
//
// Story progress stays road-only. BP_Saskarta_Road's road_m (USaskartaEventRunner) holds while the
// carrier is on a detour (IsDetour), so a spur never fires or skips a beat.
//
// No Tick. The callers' timers drive the queries (BPC_RoadTether.CheckRoad every 0.2 s, the event
// runner's road poll); the actor scan runs when a level streams in or out, at most every 2 s, and the
// tether actors register themselves at BeginPlay. Each query checks each spline's cached 2D bounds
// first, so the six spurs cost nothing while the carrier is on the road.

#pragma once

#include "CoreMinimal.h"
#include "Subsystems/WorldSubsystem.h"

#include "SaskartaTetherSubsystem.generated.h"

class AActor;
class ULevel;
class USplineComponent;

/** One tether query: where the carrier stands relative to the allowed ground. Distances are in cm, 2D. */
USTRUCT(BlueprintType)
struct SASKARTACORE_API FSaskartaTetherQuery
{
    GENERATED_BODY()

    /** The tether distance: min over the road and every path; 0 inside a zone; -1 when nothing is known. */
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Tether")
    float Distance = -1.f;

    /** The distance to the road alone (-1 without a road). */
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Tether")
    float RoadDistance = -1.f;

    /** The distance to the nearest tether path (-1 without paths, or when every path was culled by its bounds). */
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Tether")
    float PathDistance = -1.f;

    /** True when a path, not the road, is the nearest line. */
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Tether")
    bool bNearestIsPath = false;

    /** True inside an exploration zone. */
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Tether")
    bool bInZone = false;

    /** The zone's POI id (or actor name) when bInZone. */
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Tether")
    FName ZoneName;

    /** The nearest line's POI id (or actor name); NAME_None for the road. */
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Tether")
    FName LineName;

    /** The nearest point on the nearest line (world). */
    UPROPERTY(BlueprintReadOnly, Category = "Saskarta|Tether")
    FVector NearestPoint = FVector::ZeroVector;
};

/** One allowed line, as the logic sees it. */
struct SASKARTACORE_API FSaskartaTetherLine
{
    TWeakObjectPtr<const USplineComponent> Spline;
    /** 2D bounds of the spline's points, grown by FSaskartaTetherLogic::BoundsMarginCm. */
    FBox2D Bounds = FBox2D(ForceInit);
    bool bRoad = false;
    /** Along-spline direction (+1 / -1) that leads back to the road: the end nearer the road is the junction. */
    float SignTowardRoad = -1.f;
    FName Name;
};

/** One exploration zone (a vertical cylinder: the XY distance counts). */
struct SASKARTACORE_API FSaskartaTetherZone
{
    FVector Center = FVector::ZeroVector;
    float RadiusCm = 0.f;
    FName Name;
};

/** The pure maths, on spline components and plain data (the automation tests drive it directly). */
struct SASKARTACORE_API FSaskartaTetherLogic
{
    /** Splines bend between points; the bounds grow by this much so the cull never drops a nearer line. */
    static constexpr float BoundsMarginCm = 2000.f;
    /** The facing chord half-length (BFL_SaskartaRoad.ComputeRoadRespawn's 300 cm). */
    static constexpr float FacingStepCm = 300.f;

    /** A line for a spline; SignTowardRoad from which end is nearer Road (null Road or bRoad: -1). */
    static FSaskartaTetherLine MakeLine(const USplineComponent& Spline, bool bRoad, FName Name, const USplineComponent* Road);

    /** BPC_RoadTether's measure: the closest input key in 3D, then the 2D distance to that point. */
    static float DistanceToSpline2D(const USplineComponent& Spline, const FVector& Location, FVector& OutPoint);

    /** The tether query over lines and zones. */
    static FSaskartaTetherQuery Query(const FVector& Location, TConstArrayView<FSaskartaTetherLine> Lines, TConstArrayView<FSaskartaTetherZone> Zones);

    /** Road progress holds: off the road by more than HoldCm while a path is nearest or inside a zone. */
    static bool HoldsRoadProgress(const FSaskartaTetherQuery& Q, float HoldCm);

    /**
     * The respawn spot before the ground trace: on the line nearest From, StepCm along it, facing along it.
     * On the road: BFL_SaskartaRoad.ComputeRoadRespawn exactly (StepCm * TravelSign, the other way when
     * that runs off an end, facing TravelSign). On a path: StepCm toward the road junction, facing it.
     * Returns the chosen line's index (INDEX_NONE when there is no valid line).
     */
    static int32 PlanRespawn(const FVector& From, TConstArrayView<FSaskartaTetherLine> Lines, float TravelSign, float StepCm,
        FVector& OutPoint, FRotator& OutFacing);
};

UCLASS()
class SASKARTACORE_API USaskartaTetherSubsystem : public UWorldSubsystem
{
    GENERATED_BODY()

public:
    UFUNCTION(BlueprintPure, Category = "Saskarta|Tether", meta = (WorldContext = "WorldContextObject"))
    static USaskartaTetherSubsystem* GetTether(const UObject* WorldContextObject);

    /** The tether distance in cm (2D): the nearest road or path, 0 inside a zone, -1 when no line is known. */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Tether")
    float GetTetherDistance(FVector Location) const;

    /** The full query (road and path distances, zone, nearest line). */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Tether")
    FSaskartaTetherQuery QueryTether(FVector Location) const;

    /** True while Location is a detour: more than RoadHoldCm off the road, on a path or in a zone. Road progress holds. */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Tether")
    bool IsDetour(FVector Location) const;

    /** True when Location is more than MinDistanceCm from every allowed line and in no zone (the radio's OFFROAD test). */
    UFUNCTION(BlueprintPure, Category = "Saskarta|Tether")
    bool IsOffAllowedPaths(FVector Location, float MinDistanceCm) const;

    /** True only when the local player's pawn is known to be within WarnDistanceCm of an allowed line or in a
        zone (false without a pawn or lines): the radio's OFFROAD guard. */
    bool IsPlayerOnAllowedGround() const;

    /**
     * The respawn after a breach: the nearest road or path point to From, StepCm along it (see
     * FSaskartaTetherLogic::PlanRespawn), traced to the ground (Visibility, 10 m up to 50 m down, IgnoreActor
     * skipped), lifted by CapsuleHalfHeight + 2 cm, yaw only. Found is false when the trace hits nothing.
     */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Tether")
    bool ComputeRespawn(FVector From, float CapsuleHalfHeight, float TravelSign, float StepCm, AActor* IgnoreActor,
        FVector& Location, FRotator& Rotation);

    UFUNCTION(BlueprintPure, Category = "Saskarta|Tether")
    bool HasRoad() const;

    UFUNCTION(BlueprintPure, Category = "Saskarta|Tether")
    int32 GetPathCount() const;

    UFUNCTION(BlueprintPure, Category = "Saskarta|Tether")
    int32 GetZoneCount() const;

    /** Rescans the world now (road, tagged paths, tagged zones). */
    UFUNCTION(BlueprintCallable, Category = "Saskarta|Tether")
    void RefreshTether();

    /** ASaskartaTetherPath / ASaskartaExploreZone BeginPlay and EndPlay: the next query rescans. */
    void MarkDirty() { bDirty = true; bForceScan = true; }

    /** BPC_RoadTether's WarnDistance, for IsPlayerOnAllowedGround (the radio). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Tether")
    float WarnDistanceCm = 1000.f;

    /** Road progress holds beyond this distance from the road (on a path or in a zone). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Saskarta|Tether")
    float RoadHoldCm = 1000.f;

    static const FName RoadTag;
    static const FName PathTag;
    static const FName ZoneTag;

    // ------------------------------------------------------------------ UWorldSubsystem
    virtual void Initialize(FSubsystemCollectionBase& Collection) override;
    virtual void Deinitialize() override;
    virtual void OnWorldBeginPlay(UWorld& InWorld) override;

protected:
    virtual bool DoesSupportWorldType(const EWorldType::Type WorldType) const override;

private:
    void OnLevelChanged(ULevel* Level, UWorld* World);
    void EnsureScanned() const;
    void Scan() const;
    double Now() const;

    mutable TArray<FSaskartaTetherLine> Lines;
    mutable TArray<FSaskartaTetherZone> Zones;
    mutable bool bDirty = true;
    mutable bool bForceScan = true;
    mutable double LastScanS = -1.0e9;
    mutable bool bLoggedNoRoad = false;

    // one query per frame and location is enough (the tether, the runner and the radio share it)
    mutable uint64 MemoFrame = MAX_uint64;
    mutable FVector MemoLocation = FVector::ZeroVector;
    mutable FSaskartaTetherQuery MemoResult;

    FDelegateHandle LevelAddedHandle;
    FDelegateHandle LevelRemovedHandle;
};
