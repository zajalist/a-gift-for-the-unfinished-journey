// The collapse stage (task COLLAPSE-STAGE): where the carrier and its capsule stand for CIN_18.
//
// The author, packaged game: "ending cinematic can be in a glitched position" (the exterior of the
// collapse showed the carrier and capsule tilted on a slope, half off the road). B18 fires on a road
// pass, so the carrier could be anywhere near UE 221.9 m (off the verge, mid-turn, jackknifed), and
// CIN_18's sequence origin was taken from that pose before the old SnapToRoad cue moved it at 3.2 s.
// Now USaskartaCollapseStageSubsystem stages the carrier when B18 starts, before CIN_18's first frame,
// at this authored pose: a road-spline sample at RoadM, LateralCm to the right of the centre, yawed
// along the road (+YawOffsetDeg), grounded on the landscape from several wheel columns.
//
// Data: story-events.json "collapse_stage" -> USaskartaStoryAsset::CollapseStage (the importer). The
// defaults below match the JSON, so a DataAsset imported before the field existed stages the same.

#pragma once

#include "CoreMinimal.h"
#include "SaskartaCollapseStageLogic.generated.h"

USTRUCT(BlueprintType)
struct SASKARTACORE_API FSaskartaCollapseStageDef
{
    GENERATED_BODY()

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Collapse") bool bEnabled = true;
    /** Staged when this beat starts ... */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Collapse") FName Beat = TEXT("B18_COLLAPSE");
    /** ... or this cinematic (debug PlayCinematic without the beat). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Collapse") FName Cinematic = TEXT("CIN_18_COLLAPSE");
    /** Story road metres (story-events.json distance_m), mapped to spline distance by RoadMToUeM. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Collapse") float RoadM = 4790.f;
    /** + = to the right of the road centre (in the direction of travel). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Collapse") float LateralCm = 0.f;
    /** Added to the road's yaw of travel. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Collapse") float YawOffsetDeg = 0.f;
    /** Moves longer than this are hidden: black at once, then CoverFadeS back in under the POV lurch. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Collapse") float CoverBeyondM = 3.f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Collapse") float CoverHoldS = 0.25f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Collapse") float CoverFadeS = 0.6f;

    // The footprint the ground is traced under (actor local cm: +X forward, +Y right).
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Collapse|Footprint") float WheelFrontCm = 110.f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Collapse|Footprint") float WheelRearCm = -90.f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Collapse|Footprint") float WheelHalfTrackCm = 70.f;
    /** The capsule's wheels (capsule_root_local x in probe_ending.json). */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Collapse|Footprint") float CapsuleWheelXCm = -356.5f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Collapse|Footprint") float CapsuleHalfTrackCm = 55.f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Collapse|Footprint") float TraceUpCm = 500.f;
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Collapse|Footprint") float TraceDownCm = 1500.f;
    /** Clearance over the support so the teleport is clear; the movement component settles it. */
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Collapse|Footprint") float LiftCm = 2.f;
};

/** The stage pose, before the ground traces. */
struct SASKARTACORE_API FSaskartaCollapsePose
{
    /** The carrier's X/Y (Z = the spline's, until grounded). */
    FVector Centre = FVector::ZeroVector;
    /** The yaw of travel plus the offset. */
    float YawDeg = 0.f;
    /** The road's own yaw of travel (the sequence origin's yaw). */
    float RoadYawDeg = 0.f;
};

struct SASKARTACORE_API FSaskartaCollapseStageLogic
{
    /**
     * SplinePoint / SplineTangent at the stage distance (GetLocation/TangentAtDistanceAlongSpline), Behind / Ahead
     * a little before and after it along the spline (the fallback for a zero tangent at a spline point).
     */
    static FSaskartaCollapsePose Pose(const FSaskartaCollapseStageDef& Def, const FVector& SplinePoint, const FVector& SplineTangent,
        const FVector& Behind, const FVector& Ahead);

    /** The six trace columns in actor-local X/Y: carrier FL, FR, RL, RR, then capsule L, R. */
    static void Footprint(const FSaskartaCollapseStageDef& Def, TArray<FVector2D>& OutLocal);

    /** A local footprint point -> world X/Y at the pose (Z = Centre.Z). */
    static FVector FootprintWorld(const FSaskartaCollapsePose& Pose, const FVector2D& Local);

    /** Reads the root object's "collapse_stage" into Out. False (Out untouched) when it is absent or the JSON is bad. */
    static bool ParseJson(const FString& Json, FSaskartaCollapseStageDef& Out);

    /** True when Id (a beat or a cinematic) starts the stage. */
    static bool Triggers(const FSaskartaCollapseStageDef& Def, FName Id)
    {
        return Def.bEnabled && !Id.IsNone() && (Id == Def.Beat || Id == Def.Cinematic);
    }
};
