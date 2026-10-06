// The road tether's allowed ground (task TETHER). See SaskartaTetherSubsystem.h.

#include "SaskartaTetherSubsystem.h"

#include "SaskartaTetherActors.h"

#include "CollisionQueryParams.h"
#include "Components/SphereComponent.h"
#include "Components/SplineComponent.h"
#include "Engine/Engine.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "GameFramework/Pawn.h"
#include "Kismet/GameplayStatics.h"
#include "UObject/UnrealType.h"

DEFINE_LOG_CATEGORY_STATIC(LogSaskartaTether, Log, All);

namespace SaskartaTether
{
    /** A dirty rescan (a level streamed in or out) runs at most this often. */
    static constexpr double ScanIntervalS = 2.0;

    static FName NameOf(const AActor* A)
    {
        if (const ASaskartaTetherPath* P = Cast<ASaskartaTetherPath>(A))
        {
            if (!P->PoiId.IsNone())
            {
                return P->PoiId;
            }
        }
        if (const ASaskartaExploreZone* Z = Cast<ASaskartaExploreZone>(A))
        {
            if (!Z->PoiId.IsNone())
            {
                return Z->PoiId;
            }
        }
        return A->GetFName();
    }

    /** The zone radius: a sphere component (ASaskartaExploreZone's follows RadiusCm), a numeric
        RadiusCm / ExploreRadiusCm / Radius property, or the actor's horizontal bounds (a volume). */
    static float ZoneRadius(const AActor* A)
    {
        if (const USphereComponent* S = A->FindComponentByClass<USphereComponent>())
        {
            return S->GetScaledSphereRadius();
        }
        static const FName Names[] = { TEXT("RadiusCm"), TEXT("ExploreRadiusCm"), TEXT("Radius") };
        for (const FName& N : Names)
        {
            if (const FProperty* Prop = A->GetClass()->FindPropertyByName(N))
            {
                if (const FNumericProperty* Num = CastField<FNumericProperty>(Prop))
                {
                    if (Num->IsFloatingPoint())
                    {
                        return static_cast<float>(Num->GetFloatingPointPropertyValue(Prop->ContainerPtrToValuePtr<void>(A)));
                    }
                    if (Num->IsInteger())
                    {
                        return static_cast<float>(Num->GetSignedIntPropertyValue(Prop->ContainerPtrToValuePtr<void>(A)));
                    }
                }
            }
        }
        const FBox B = A->GetComponentsBoundingBox(true);
        return B.IsValid ? static_cast<float>(FMath::Max(B.GetExtent().X, B.GetExtent().Y)) : 0.f;
    }
}

// ============================================================================ FSaskartaTetherLogic

float FSaskartaTetherLogic::DistanceToSpline2D(const USplineComponent& Spline, const FVector& Location, FVector& OutPoint)
{
    const float Key = Spline.FindInputKeyClosestToWorldLocation(Location);
    OutPoint = Spline.GetLocationAtSplineInputKey(Key, ESplineCoordinateSpace::World);
    return static_cast<float>(FVector::Dist2D(Location, OutPoint));
}

FSaskartaTetherLine FSaskartaTetherLogic::MakeLine(const USplineComponent& Spline, bool bRoad, FName Name, const USplineComponent* Road)
{
    FSaskartaTetherLine L;
    L.Spline = &Spline;
    L.bRoad = bRoad;
    L.Name = Name;
    const int32 N = Spline.GetNumberOfSplinePoints();
    for (int32 i = 0; i < N; ++i)
    {
        const FVector P = Spline.GetLocationAtSplinePoint(i, ESplineCoordinateSpace::World);
        L.Bounds += FVector2D(P.X, P.Y);
    }
    if (L.Bounds.bIsValid)
    {
        L.Bounds = L.Bounds.ExpandBy(BoundsMarginCm);
    }
    L.SignTowardRoad = -1.f;
    if (!bRoad && Road && N >= 2)
    {
        FVector Unused;
        const float D0 = DistanceToSpline2D(*Road, Spline.GetLocationAtSplinePoint(0, ESplineCoordinateSpace::World), Unused);
        const float DN = DistanceToSpline2D(*Road, Spline.GetLocationAtSplinePoint(N - 1, ESplineCoordinateSpace::World), Unused);
        L.SignTowardRoad = D0 <= DN ? -1.f : 1.f;
    }
    return L;
}

FSaskartaTetherQuery FSaskartaTetherLogic::Query(const FVector& Location, TConstArrayView<FSaskartaTetherLine> Lines, TConstArrayView<FSaskartaTetherZone> Zones)
{
    FSaskartaTetherQuery Q;
    const FVector2D P(Location.X, Location.Y);
    float Best = TNumericLimits<float>::Max();
    // the road first: its distance is almost always the smallest, so the paths' bounds cull them
    for (int32 Pass = 0; Pass < 2; ++Pass)
    {
        const bool bRoadPass = Pass == 0;
        for (const FSaskartaTetherLine& L : Lines)
        {
            if (L.bRoad != bRoadPass)
            {
                continue;
            }
            const USplineComponent* S = L.Spline.Get();
            if (!S || S->GetNumberOfSplinePoints() < 1)
            {
                continue;
            }
            if (!L.bRoad && L.Bounds.bIsValid && FMath::Sqrt(L.Bounds.ComputeSquaredDistanceToPoint(P)) > Best)
            {
                continue;
            }
            FVector Point;
            const float D = DistanceToSpline2D(*S, Location, Point);
            if (L.bRoad)
            {
                Q.RoadDistance = Q.RoadDistance < 0.f ? D : FMath::Min(Q.RoadDistance, D);
            }
            else
            {
                Q.PathDistance = Q.PathDistance < 0.f ? D : FMath::Min(Q.PathDistance, D);
            }
            if (D < Best)
            {
                Best = D;
                Q.bNearestIsPath = !L.bRoad;
                Q.LineName = L.bRoad ? NAME_None : L.Name;
                Q.NearestPoint = Point;
            }
        }
    }
    for (const FSaskartaTetherZone& Z : Zones)
    {
        if (Z.RadiusCm > 0.f && FVector2D::DistSquared(P, FVector2D(Z.Center.X, Z.Center.Y)) <= FMath::Square(Z.RadiusCm))
        {
            Q.bInZone = true;
            Q.ZoneName = Z.Name;
            break;
        }
    }
    Q.Distance = Q.bInZone ? 0.f : (Best < TNumericLimits<float>::Max() ? Best : -1.f);
    return Q;
}

bool FSaskartaTetherLogic::HoldsRoadProgress(const FSaskartaTetherQuery& Q, float HoldCm)
{
    return Q.RoadDistance > HoldCm && (Q.bNearestIsPath || Q.bInZone);
}

int32 FSaskartaTetherLogic::PlanRespawn(const FVector& From, TConstArrayView<FSaskartaTetherLine> Lines, float TravelSign, float StepCm,
    FVector& OutPoint, FRotator& OutFacing)
{
    int32 BestIdx = INDEX_NONE;
    float BestD = TNumericLimits<float>::Max();
    for (int32 i = 0; i < Lines.Num(); ++i)
    {
        const USplineComponent* S = Lines[i].Spline.Get();
        if (!S || S->GetNumberOfSplinePoints() < 2)
        {
            continue;
        }
        FVector Unused;
        const float D = DistanceToSpline2D(*S, From, Unused);
        // the road wins a tie (a breach right at a junction goes back to the road)
        if (D < BestD || (D == BestD && Lines[i].bRoad))
        {
            BestD = D;
            BestIdx = i;
        }
    }
    if (BestIdx == INDEX_NONE)
    {
        OutPoint = FVector::ZeroVector;
        OutFacing = FRotator::ZeroRotator;
        return INDEX_NONE;
    }
    const FSaskartaTetherLine& L = Lines[BestIdx];
    const USplineComponent& S = *L.Spline.Get();
    const float Sign = L.bRoad ? TravelSign : L.SignTowardRoad;
    const float Len = S.GetSplineLength();
    const float KeyDistance = S.GetDistanceAlongSplineAtSplineInputKey(S.FindInputKeyClosestToWorldLocation(From));
    const float Forward = KeyDistance + StepCm * Sign;
    const float Backward = KeyDistance - StepCm * Sign;
    // BFL_SaskartaRoad.ComputeRoadRespawn: when the step runs off an end, step the other way instead
    const float D = FMath::Clamp((Forward < 0.f || Forward > Len) ? Backward : Forward, 0.f, Len);
    OutPoint = S.GetLocationAtDistanceAlongSpline(D, ESplineCoordinateSpace::World);
    // facing from a 6 m chord (the road's points have zero tangents, so no GetTangent)
    const FVector Ahead = S.GetLocationAtDistanceAlongSpline(FMath::Clamp(D + Sign * FacingStepCm, 0.f, Len), ESplineCoordinateSpace::World);
    const FVector Behind = S.GetLocationAtDistanceAlongSpline(FMath::Clamp(D - Sign * FacingStepCm, 0.f, Len), ESplineCoordinateSpace::World);
    const FVector Chord(Ahead.X - Behind.X, Ahead.Y - Behind.Y, 0.0);
    OutFacing = FRotator(0.0, Chord.IsNearlyZero() ? 0.0 : Chord.Rotation().Yaw, 0.0);
    return BestIdx;
}

// ============================================================================ USaskartaTetherSubsystem

const FName USaskartaTetherSubsystem::RoadTag(TEXT("Saskarta.Road"));
const FName USaskartaTetherSubsystem::PathTag(TEXT("Saskarta.TetherPath"));
const FName USaskartaTetherSubsystem::ZoneTag(TEXT("Saskarta.ExploreZone"));

USaskartaTetherSubsystem* USaskartaTetherSubsystem::GetTether(const UObject* WorldContextObject)
{
    const UWorld* World = GEngine ? GEngine->GetWorldFromContextObject(WorldContextObject, EGetWorldErrorMode::ReturnNull) : nullptr;
    return World ? World->GetSubsystem<USaskartaTetherSubsystem>() : nullptr;
}

bool USaskartaTetherSubsystem::DoesSupportWorldType(const EWorldType::Type WorldType) const
{
    return WorldType == EWorldType::Game || WorldType == EWorldType::PIE;
}

void USaskartaTetherSubsystem::Initialize(FSubsystemCollectionBase& Collection)
{
    Super::Initialize(Collection);
    LevelAddedHandle = FWorldDelegates::LevelAddedToWorld.AddUObject(this, &USaskartaTetherSubsystem::OnLevelChanged);
    LevelRemovedHandle = FWorldDelegates::LevelRemovedFromWorld.AddUObject(this, &USaskartaTetherSubsystem::OnLevelChanged);
}

void USaskartaTetherSubsystem::Deinitialize()
{
    FWorldDelegates::LevelAddedToWorld.Remove(LevelAddedHandle);
    FWorldDelegates::LevelRemovedFromWorld.Remove(LevelRemovedHandle);
    Lines.Reset();
    Zones.Reset();
    Super::Deinitialize();
}

void USaskartaTetherSubsystem::OnWorldBeginPlay(UWorld& InWorld)
{
    Super::OnWorldBeginPlay(InWorld);
    MarkDirty();
}

void USaskartaTetherSubsystem::OnLevelChanged(ULevel* Level, UWorld* World)
{
    if (World == GetWorld())
    {
        bDirty = true;
    }
}

double USaskartaTetherSubsystem::Now() const
{
    return FPlatformTime::Seconds();
}

void USaskartaTetherSubsystem::RefreshTether()
{
    MarkDirty();
    EnsureScanned();
}

void USaskartaTetherSubsystem::EnsureScanned() const
{
    bool bStale = false;
    for (const FSaskartaTetherLine& L : Lines)
    {
        bStale |= !L.Spline.IsValid();
    }
    const double T = Now();
    const bool bDue = (bDirty || Lines.Num() == 0) && T - LastScanS >= SaskartaTether::ScanIntervalS;
    if (bForceScan || bStale || bDue)
    {
        Scan();
        LastScanS = T;
        bDirty = false;
        bForceScan = false;
        MemoFrame = MAX_uint64;
    }
}

void USaskartaTetherSubsystem::Scan() const
{
    const int32 OldPaths = GetPathCount();
    const int32 OldZones = Zones.Num();
    const bool bHadRoad = HasRoad();
    Lines.Reset();
    Zones.Reset();
    UWorld* World = GetWorld();
    if (!World)
    {
        return;
    }
    const USplineComponent* Road = nullptr;
    TArray<const AActor*, TInlineAllocator<16>> PathActors;
    TArray<const AActor*, TInlineAllocator<16>> ZoneActors;
    for (TActorIterator<AActor> It(World); It; ++It)
    {
        const AActor* A = *It;
        if (!IsValid(A))
        {
            continue;
        }
        // the event runner's and the tether's rule: BP_Saskarta_Road (or any actor tagged Saskarta.Road)
        if (!Road && (A->ActorHasTag(RoadTag) || A->GetClass()->GetName().StartsWith(TEXT("BP_Saskarta_Road"))))
        {
            if (const USplineComponent* S = A->FindComponentByClass<USplineComponent>())
            {
                Road = S;
                continue;
            }
        }
        if (A->IsA<ASaskartaTetherPath>() || A->ActorHasTag(PathTag))
        {
            PathActors.Add(A);
        }
        else if (A->IsA<ASaskartaExploreZone>() || A->ActorHasTag(ZoneTag))
        {
            ZoneActors.Add(A);
        }
    }
    if (Road)
    {
        Lines.Add(FSaskartaTetherLogic::MakeLine(*Road, true, NAME_None, nullptr));
    }
    for (const AActor* A : PathActors)
    {
        const USplineComponent* S = A->FindComponentByClass<USplineComponent>();
        if (S && S->GetNumberOfSplinePoints() >= 2)
        {
            Lines.Add(FSaskartaTetherLogic::MakeLine(*S, false, SaskartaTether::NameOf(A), Road));
        }
    }
    for (const AActor* A : ZoneActors)
    {
        FSaskartaTetherZone Z;
        Z.Center = A->GetActorLocation();
        Z.RadiusCm = SaskartaTether::ZoneRadius(A);
        Z.Name = SaskartaTether::NameOf(A);
        if (Z.RadiusCm > 0.f)
        {
            Zones.Add(Z);
        }
    }
    if (bHadRoad != HasRoad() || OldPaths != GetPathCount() || OldZones != Zones.Num())
    {
        UE_LOG(LogSaskartaTether, Log, TEXT("tether: road %s, %d path(s), %d zone(s)"), HasRoad() ? TEXT("found") : TEXT("missing"),
            GetPathCount(), Zones.Num());
    }
    if (!Road && !bLoggedNoRoad)
    {
        bLoggedNoRoad = true;
        UE_LOG(LogSaskartaTether, Log, TEXT("tether: no BP_Saskarta_Road spline in this world yet"));
    }
}

FSaskartaTetherQuery USaskartaTetherSubsystem::QueryTether(FVector Location) const
{
    EnsureScanned();
    if (MemoFrame == GFrameCounter && MemoLocation.Equals(Location, 0.5))
    {
        return MemoResult;
    }
    MemoResult = FSaskartaTetherLogic::Query(Location, Lines, Zones);
    MemoFrame = GFrameCounter;
    MemoLocation = Location;
    return MemoResult;
}

float USaskartaTetherSubsystem::GetTetherDistance(FVector Location) const
{
    return QueryTether(Location).Distance;
}

bool USaskartaTetherSubsystem::IsDetour(FVector Location) const
{
    return FSaskartaTetherLogic::HoldsRoadProgress(QueryTether(Location), RoadHoldCm);
}

bool USaskartaTetherSubsystem::IsOffAllowedPaths(FVector Location, float MinDistanceCm) const
{
    const FSaskartaTetherQuery Q = QueryTether(Location);
    return Q.Distance >= 0.f && !Q.bInZone && Q.Distance > MinDistanceCm;
}

bool USaskartaTetherSubsystem::IsPlayerOnAllowedGround() const
{
    const APawn* Pawn = UGameplayStatics::GetPlayerPawn(this, 0);
    if (!Pawn)
    {
        return false;
    }
    const FSaskartaTetherQuery Q = QueryTether(Pawn->GetActorLocation());
    return Q.Distance >= 0.f && Q.Distance <= WarnDistanceCm;
}

bool USaskartaTetherSubsystem::ComputeRespawn(FVector From, float CapsuleHalfHeight, float TravelSign, float StepCm, AActor* IgnoreActor,
    FVector& Location, FRotator& Rotation)
{
    EnsureScanned();
    FVector Point;
    FRotator Facing;
    const int32 Line = FSaskartaTetherLogic::PlanRespawn(From, Lines, TravelSign, StepCm, Point, Facing);
    UWorld* World = GetWorld();
    if (Line == INDEX_NONE || !World)
    {
        Location = FVector::ZeroVector;
        Rotation = FRotator::ZeroRotator;
        return false;
    }
    FCollisionQueryParams Params(SCENE_QUERY_STAT(SaskartaTetherRespawn), false);
    if (IgnoreActor)
    {
        Params.AddIgnoredActor(IgnoreActor);
    }
    FHitResult Hit;
    const bool bHit = World->LineTraceSingleByChannel(Hit, Point + FVector(0.0, 0.0, 1000.0), Point - FVector(0.0, 0.0, 5000.0), ECC_Visibility, Params);
    Location = (bHit ? FVector(Hit.ImpactPoint) : Point) + FVector(0.0, 0.0, CapsuleHalfHeight + 2.0);
    Rotation = Facing;
    UE_LOG(LogSaskartaTether, Log, TEXT("respawn: %s, step %.0f cm, found %d"),
        Lines[Line].bRoad ? TEXT("road") : *Lines[Line].Name.ToString(), StepCm, bHit ? 1 : 0);
    return bHit;
}

bool USaskartaTetherSubsystem::HasRoad() const
{
    for (const FSaskartaTetherLine& L : Lines)
    {
        if (L.bRoad && L.Spline.IsValid())
        {
            return true;
        }
    }
    return false;
}

int32 USaskartaTetherSubsystem::GetPathCount() const
{
    int32 N = 0;
    for (const FSaskartaTetherLine& L : Lines)
    {
        N += L.bRoad ? 0 : 1;
    }
    return N;
}

int32 USaskartaTetherSubsystem::GetZoneCount() const
{
    return Zones.Num();
}
