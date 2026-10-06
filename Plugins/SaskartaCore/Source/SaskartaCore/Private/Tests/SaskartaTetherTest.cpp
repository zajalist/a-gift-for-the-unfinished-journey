// Automation tests for the road tether's allowed ground (task TETHER; SaskartaTetherSubsystem.h).
//
// FSaskartaTetherLogic on transient spline components (no world: component space is world space):
// the distance to the nearest spline, the zone override, the respawn line choice and the step / facing
// rules, and that road progress (the event runner's high-water mark) holds while the pawn walks a path.
// Run after the closed-editor build with
//   Automation RunTests Saskarta.Tether

#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "Components/SplineComponent.h"
#include "SaskartaEventLogic.h"
#include "SaskartaTetherSubsystem.h"
#include "UObject/StrongObjectPtr.h"

#define SASKARTA_TETHER_TEST_FLAGS (EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)

namespace SaskartaTetherTest
{
    static TStrongObjectPtr<USplineComponent> MakeSpline(std::initializer_list<FVector> Points)
    {
        TStrongObjectPtr<USplineComponent> S(NewObject<USplineComponent>(GetTransientPackage()));
        S->ClearSplinePoints(false);
        for (const FVector& P : Points)
        {
            S->AddSplinePoint(P, ESplineCoordinateSpace::World, false);
        }
        for (int32 i = 0; i < S->GetNumberOfSplinePoints(); ++i)
        {
            S->SetSplinePointType(i, ESplinePointType::Linear, false);
        }
        S->UpdateSpline();
        return S;
    }

    /** The road along +X (1 km), a spur from x = 500 m straight out to +Y 500 m, a zone at its end. */
    struct FTetherScene
    {
        TStrongObjectPtr<USplineComponent> Road = MakeSpline({ FVector(0, 0, 0), FVector(100000, 0, 0) });
        TStrongObjectPtr<USplineComponent> Spur = MakeSpline({ FVector(50000, 0, 0), FVector(50000, 25000, 0), FVector(50000, 50000, 0) });
        TArray<FSaskartaTetherLine> Lines;
        TArray<FSaskartaTetherZone> Zones;

        FTetherScene()
        {
            Lines.Add(FSaskartaTetherLogic::MakeLine(*Road, true, NAME_None, nullptr));
            Lines.Add(FSaskartaTetherLogic::MakeLine(*Spur, false, TEXT("O99"), Road.Get()));
            FSaskartaTetherZone Z;
            Z.Center = FVector(50000, 56000, 0);
            Z.RadiusCm = 5000.f;
            Z.Name = TEXT("O99");
            Zones.Add(Z);
        }
    };
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaTetherDistanceTest, "Saskarta.Tether.NearestSpline", SASKARTA_TETHER_TEST_FLAGS)
bool FSaskartaTetherDistanceTest::RunTest(const FString& Parameters)
{
    using namespace SaskartaTetherTest;
    FTetherScene S;

    // on the spur, 15 m to its side: the road alone would breach (300 m), the spur gives 15 m (warning band)
    FSaskartaTetherQuery Q = FSaskartaTetherLogic::Query(FVector(51500, 30000, 800), S.Lines, S.Zones);
    TestNearlyEqual(TEXT("spur distance"), Q.Distance, 1500.f, 1.f);
    TestNearlyEqual(TEXT("road distance"), Q.RoadDistance, 30000.f, 1.f);
    TestTrue(TEXT("the spur is nearest"), Q.bNearestIsPath);
    TestEqual(TEXT("line name"), Q.LineName, FName(TEXT("O99")));
    TestFalse(TEXT("not in a zone"), Q.bInZone);
    TestNearlyEqual(TEXT("nearest point on the spur"), static_cast<float>(Q.NearestPoint.X), 50000.f, 1.f);

    // by the road, far from the spur: the road wins and the spur is culled by its bounds
    Q = FSaskartaTetherLogic::Query(FVector(10000, 500, 0), S.Lines, S.Zones);
    TestNearlyEqual(TEXT("road distance near the road"), Q.Distance, 500.f, 1.f);
    TestFalse(TEXT("the road is nearest"), Q.bNearestIsPath);
    TestEqual(TEXT("the spur is culled"), Q.PathDistance, -1.f);

    // height does not count (2D), as in BPC_RoadTether's Vector_Distance2D
    Q = FSaskartaTetherLogic::Query(FVector(10000, 500, 4000), S.Lines, S.Zones);
    TestNearlyEqual(TEXT("2D distance"), Q.Distance, 500.f, 1.f);

    // the old thresholds keep their meaning, measured to the nearest line
    Q = FSaskartaTetherLogic::Query(FVector(52100, 30000, 0), S.Lines, S.Zones);
    TestTrue(TEXT("21 m off the spur breaches"), Q.Distance > 2000.f);
    Q = FSaskartaTetherLogic::Query(FVector(50900, 30000, 0), S.Lines, S.Zones);
    TestTrue(TEXT("9 m off the spur is safe"), Q.Distance < 1000.f);

    // no lines: -1 (BPC_RoadTether's ClassifyTetherZone reads it as Safe; the Road guard stops the tether)
    Q = FSaskartaTetherLogic::Query(FVector(0, 0, 0), {}, {});
    TestEqual(TEXT("nothing known"), Q.Distance, -1.f);

    // junction end detection: point 0 on the road leads back with -1; a reversed spur with +1
    TStrongObjectPtr<USplineComponent> Reversed = MakeSpline({ FVector(50000, 50000, 0), FVector(50000, 0, 0) });
    TestEqual(TEXT("spur sign"), S.Lines[1].SignTowardRoad, -1.f);
    TestEqual(TEXT("reversed spur sign"), FSaskartaTetherLogic::MakeLine(*Reversed, false, NAME_None, S.Road.Get()).SignTowardRoad, 1.f);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaTetherZoneTest, "Saskarta.Tether.ZoneOverride", SASKARTA_TETHER_TEST_FLAGS)
bool FSaskartaTetherZoneTest::RunTest(const FString& Parameters)
{
    using namespace SaskartaTetherTest;
    FTetherScene S;

    // 95 m from the spur's end but 42 m from the zone centre (50 m radius): 0
    FSaskartaTetherQuery Q = FSaskartaTetherLogic::Query(FVector(53000, 59000, 0), S.Lines, S.Zones);
    TestTrue(TEXT("in the zone"), Q.bInZone);
    TestEqual(TEXT("zone distance"), Q.Distance, 0.f);
    TestEqual(TEXT("zone name"), Q.ZoneName, FName(TEXT("O99")));

    // the zone is a cylinder: height does not matter
    Q = FSaskartaTetherLogic::Query(FVector(53000, 59000, 20000), S.Lines, S.Zones);
    TestTrue(TEXT("in the zone, any height"), Q.bInZone);

    // just outside: back to the distance to the spur's end (50000, 50000)
    Q = FSaskartaTetherLogic::Query(FVector(50000, 62000, 0), S.Lines, S.Zones);
    TestFalse(TEXT("outside the zone"), Q.bInZone);
    TestNearlyEqual(TEXT("distance to the spur end"), Q.Distance, 12000.f, 1.f);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaTetherRespawnTest, "Saskarta.Tether.RespawnSelection", SASKARTA_TETHER_TEST_FLAGS)
bool FSaskartaTetherRespawnTest::RunTest(const FString& Parameters)
{
    using namespace SaskartaTetherTest;
    FTetherScene S;
    FVector P;
    FRotator R;

    // a breach off the spur respawns on the spur, facing back toward the road junction (-Y)
    int32 Line = FSaskartaTetherLogic::PlanRespawn(FVector(52100, 30000, 0), S.Lines, -1.f, 0.f, P, R);
    TestEqual(TEXT("spur chosen"), Line, 1);
    TestTrue(TEXT("on the spur"), P.Equals(FVector(50000, 30000, 0), 1.0));
    TestNearlyEqual(TEXT("faces the road"), static_cast<float>(R.Yaw), -90.f, 0.5f);
    TestEqual(TEXT("yaw only"), static_cast<float>(R.Pitch) + static_cast<float>(R.Roll), 0.f);

    // later tries step toward the junction
    FSaskartaTetherLogic::PlanRespawn(FVector(52100, 30000, 0), S.Lines, -1.f, 600.f, P, R);
    TestTrue(TEXT("stepped toward the road"), P.Equals(FVector(50000, 29400, 0), 1.0));

    // a step past the junction end goes the other way instead (ComputeRoadRespawn's rule)
    Line = FSaskartaTetherLogic::PlanRespawn(FVector(52100, 2500, 0), S.Lines, -1.f, 5000.f, P, R);
    TestEqual(TEXT("still the spur"), Line, 1);
    TestTrue(TEXT("stepped away from the end"), P.Equals(FVector(50000, 7500, 0), 1.0));

    // a breach off the road (far from the spur) respawns on the road, facing the travel sign (-X)
    Line = FSaskartaTetherLogic::PlanRespawn(FVector(10000, 2100, 0), S.Lines, -1.f, 0.f, P, R);
    TestEqual(TEXT("road chosen"), Line, 0);
    TestTrue(TEXT("on the road"), P.Equals(FVector(10000, 0, 0), 1.0));
    TestNearlyEqual(TEXT("faces up-road"), FMath::Abs(static_cast<float>(R.Yaw)), 180.f, 0.5f);
    FSaskartaTetherLogic::PlanRespawn(FVector(10000, 2100, 0), S.Lines, -1.f, 400.f, P, R);
    TestTrue(TEXT("road step follows TravelSign"), P.Equals(FVector(9600, 0, 0), 1.0));

    // beside the junction, nearer the road than the spur: the road
    Line = FSaskartaTetherLogic::PlanRespawn(FVector(48000, 1500, 0), S.Lines, -1.f, 0.f, P, R);
    TestEqual(TEXT("junction side goes to the road"), Line, 0);

    // no lines: nothing
    TestEqual(TEXT("no lines"), FSaskartaTetherLogic::PlanRespawn(FVector::ZeroVector, {}, -1.f, 0.f, P, R), static_cast<int32>(INDEX_NONE));
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSaskartaTetherRoadProgressTest, "Saskarta.Tether.RoadProgressHolds", SASKARTA_TETHER_TEST_FLAGS)
bool FSaskartaTetherRoadProgressTest::RunTest(const FString& Parameters)
{
    using namespace SaskartaTetherTest;
    // travel runs toward x = 0 (the real road's TravelSign -1: UE distance falls as road_m rises).
    // The spur leaves at x = 500 m and runs diagonally AHEAD to x = 200 m, 400 m out: walking it, the
    // nearest road point slides 300 m ahead. The runner's high-water mark must stay at the junction.
    TStrongObjectPtr<USplineComponent> Road = MakeSpline({ FVector(0, 0, 0), FVector(100000, 0, 0) });
    TStrongObjectPtr<USplineComponent> Spur = MakeSpline({ FVector(50000, 0, 0), FVector(20000, 40000, 0) });
    TArray<FSaskartaTetherLine> Lines;
    Lines.Add(FSaskartaTetherLogic::MakeLine(*Road, true, NAME_None, nullptr));
    Lines.Add(FSaskartaTetherLogic::MakeLine(*Spur, false, TEXT("O99"), Road.Get()));
    TArray<FSaskartaTetherZone> Zones;
    FSaskartaTetherZone Z;
    Z.Center = FVector(20000, 45000, 0);
    Z.RadiusCm = 6000.f;
    Zones.Add(Z);

    auto Walk = [&](const TArray<FVector>& Points, float HighWaterUeM, bool bHold, float& OutMinFree)
    {
        OutMinFree = HighWaterUeM;
        for (const FVector& P : Points)
        {
            const float UeM = Road->GetDistanceAlongSplineAtSplineInputKey(Road->FindInputKeyClosestToWorldLocation(P)) / 100.f;
            OutMinFree = FMath::Min(OutMinFree, UeM);
            if (bHold && FSaskartaTetherLogic::HoldsRoadProgress(FSaskartaTetherLogic::Query(P, Lines, Zones), 1000.f))
            {
                continue;       // USaskartaEventRunner::PollRoad returns before the high-water update
            }
            HighWaterUeM = FSaskartaEventLogic::UpdateHighWater(HighWaterUeM, UeM);
        }
        return HighWaterUeM;
    };

    TArray<FVector> Trip;
    for (int32 x = 80000; x >= 50000; x -= 500)
    {
        Trip.Add(FVector(x, 0, 0));                             // up the road to the junction
    }
    for (int32 k = 0; k <= 100; ++k)
    {
        Trip.Add(FMath::Lerp(FVector(50000, 0, 0), FVector(20000, 40000, 0), k / 100.f));   // out the spur
    }
    for (int32 a = 0; a < 24; ++a)
    {
        const float T = 2.f * PI * a / 24.f;
        Trip.Add(Z.Center + FVector(FMath::Cos(T), FMath::Sin(T), 0) * 5000.f);            // round the POI
    }
    for (int32 k = 100; k >= 0; --k)
    {
        Trip.Add(FMath::Lerp(FVector(50000, 0, 0), FVector(20000, 40000, 0), k / 100.f));   // and back
    }

    float MinFree = 0.f;
    const float Held = Walk(Trip, 800.f, true, MinFree);
    TestTrue(TEXT("road_m held at the junction (UE 500 m, +/- the 10 m band)"), Held >= 490.f && Held <= 500.5f);
    TestTrue(TEXT("the projection alone would have run ~300 m ahead"), MinFree < 250.f);
    float Unused = 0.f;
    TestTrue(TEXT("without the hold the beats ahead would fire"), Walk(Trip, 800.f, false, Unused) < 250.f);

    // the warning band off the plain road does not hold progress (the old behaviour)
    TestFalse(TEXT("15 m off the road, no path: progress moves"),
        FSaskartaTetherLogic::HoldsRoadProgress(FSaskartaTetherLogic::Query(FVector(70000, 1500, 0), Lines, Zones), 1000.f));
    // walking on along the road after the detour moves it again
    TArray<FVector> After = { FVector(49000, 0, 0), FVector(40000, 0, 0) };
    TestNearlyEqual(TEXT("progress resumes on the road"), Walk(After, Held, true, Unused), 400.f, 0.5f);
    return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS
